import logging
import time
from datetime import datetime, timedelta, timezone

import discord
from discord.ext import commands, tasks

from core.bot.Module import ModuleCheck
from core.economy.activity import OK, CurrentStreak, Guard, LocalDay, Multiplier, NextPayout, TTLCache
from core.economy.config import EcoConfig
from core.economy.constants import MODULE, MODULE_CACHE_SECONDS, USERS, VOICE_TICK_MINUTES
from core.economy.rewards import FormatAmount
from core.economy import boost
from core.economy.registry import Eco
from core.economy.service import EconomyError, Economy

logger = logging.getLogger(__name__)

STREAK_EMOJI = "🔥"
STREAK_CHECK_MINUTES = 30
STREAK_WARNING_HOURS = 24  # after completing a streak, warn if it isn't renewed by then


def WelcomeText(guild: discord.Guild, balance: int, config: dict) -> str:
    """The one-time DM for people who have started earning by chatting."""
    return (
        f"👋 **¡Hey!** Tienes {FormatAmount(balance, config)} sin usar que ganaste chateando en **{guild.name}**. "
        "¿Ya probaste nuestro sistema de economía? ¡Es súper fácil!\n\n"
        "**💰 Para empezar**\n"
        "> `/saldo`: cuánto tienes · `/diario`: tu premio de cada día · `/trabajar`: gana más cada hora\n"
        "> `/tienda`: roles y objetos · `/gacha`: consigue **mascotas** que te ayudan a ganar\n\n"
        "**🎲 Juegos**\n"
        "> 🃏 La Larga Marcha · 🎰 Slots y tragamonedas · 🚀 Crash · 🃏 Blackjack · 🎡 Ruleta\n"
        "> 💣 Mines · 🔼 Mayor o menor · 🏇 Carrera · 🪙 Moneda\n"
        "> Todos explicados en `/juegos`, y una práctica gratis con `/tutorial marcha`.\n\n"
        "Chatea y gasta tus monedas con diversión, ¡o gana mascotas súper bonitas! 🐾\n"
        "-# ¿Dudas? Usa `/ayuda` en el servidor."
    )


def StreakText(guild: discord.Guild, streak: int, deadline: datetime, settings: dict) -> str:
    Next = Multiplier(streak + 1, settings)
    return (
        f"🔥 **¡Hey! Vas a perder tu racha de chat de {streak} día{'s' if streak != 1 else ''}** en **{guild.name}**.\n"
        f"Escribe **{settings['streak_messages']} mensajes** en los canales del servidor antes de <t:{int(deadline.timestamp())}:R> "
        f"para mantenerla y subir tu multiplicador a **x{Next:.2f}**."
    )


class EconomyActivity(commands.Cog):
    """Pays for chatting in the configured channels (and, optionally, for voice time)."""

    def __init__(self, client: commands.Bot):
        self.client = client
        self.guard = Guard()
        self.enabled = TTLCache()
        self.Voice.start()
        self.Streaks.start()

    def cog_unload(self):
        self.Voice.cancel()
        self.Streaks.cancel()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.guild is None or message.author.bot or message.webhook_id:
            return
        Config = await EcoConfig().Get(message.guild.id)
        Settings = Config["activity"]
        Parent = message.channel.parent_id if isinstance(message.channel, discord.Thread) else None
        if message.channel.id not in Settings["channels"] and Parent not in Settings["channels"]:
            return
        if message.content.startswith(("!!", "/")):
            return  # commands aren't chatting

        Key = (message.guild.id, message.author.id)
        Now = time.monotonic()
        Enabled = self.enabled.Get(message.guild.id, Now)
        if Enabled is None:
            Enabled = await ModuleCheck(message.guild.id, MODULE)
            self.enabled.Set(message.guild.id, Enabled, Now, MODULE_CACHE_SECONDS)
        if not Enabled:
            return
        if self.guard.Check(Key, message.content, Now, Settings) != OK:
            return
        # Mark before any await so a second message right after can't also get paid.
        self.guard.MarkPaid(Key, Now)

        Service = Economy()
        async with Service.Lock(message.guild.id, message.author.id):
            Account = await Service.Account(message.guild.id, message.author.id)
            Bonus = await Eco().bonuses.Total(message.guild.id, message.author.id, "chat", Config)
            Payout = NextPayout(Account.get("activity", {}), datetime.now(timezone.utc), Settings, bonus=Bonus)
            if Payout.amount <= 0:
                return  # hit today's cap
            try:
                Account = await Service.Add(
                    message.guild.id,
                    message.author.id,
                    boost.Boosted(Payout.amount, message.author, Config),
                    "Actividad en chat",
                    also_set={
                        **{f"activity.{k}": v for k, v in Payout.fields.items()},
                        "last_active": datetime.now(timezone.utc),
                    },
                )
            except EconomyError as e:
                logger.warning(f"[Economy] Activity pay failed: {e}")
                return
        self.client.dispatch("economy_progress", message.guild.id, message.author.id, "messages", 1)
        if Settings["welcome_dm"] and int(Account.get("balance", 0)) >= Settings["welcome_at"] and not Account.get("welcome_dm"):
            await self.Welcome(message.author, int(Account["balance"]), Config)

        if Payout.qualified_now and Settings["react_streak"]:
            try:
                await message.add_reaction(STREAK_EMOJI)
            except discord.HTTPException:
                pass

    async def Welcome(self, member: discord.Member, balance: int, config: dict):
        """Sends the welcome DM once per person (the flag is set first, so it can't repeat)."""
        Claimed = await Economy().users.update_one(
            {"guild_id": member.guild.id, "user_id": member.id, "welcome_dm": {"$ne": True}}, {"$set": {"welcome_dm": True}}
        )
        if not Claimed.modified_count:
            return
        try:
            await member.send(WelcomeText(member.guild, balance, config))
        except discord.HTTPException:
            pass  # DMs closed

    @tasks.loop(minutes=STREAK_CHECK_MINUTES)
    async def Streaks(self):
        for guild in self.client.guilds:
            try:
                await self.WarnStreaks(guild)
            except Exception as e:
                logger.error(f"[Economy] Streak reminders failed in {guild.id}: {e}")

    @Streaks.before_loop
    async def BeforeStreaks(self):
        await self.client.wait_until_ready()

    async def WarnStreaks(self, guild: discord.Guild, now: datetime | None = None) -> int:
        """DMs people whose chat streak will be lost today: 24 h after completing it, once per streak day."""
        Config = await EcoConfig().Get(guild.id)
        Settings = Config["activity"]
        if not Settings["streak_reminder"] or not Settings["channels"] or not await ModuleCheck(guild.id, MODULE):
            return 0
        Now = now or datetime.now(timezone.utc)
        Today = LocalDay(Now, Settings["utc_offset"])
        # The streak is lost when today ends (local midnight) without qualifying again.
        Deadline = datetime(Today.year, Today.month, Today.day, tzinfo=timezone.utc) + timedelta(days=1, hours=-Settings["utc_offset"])
        Users = Economy().db[USERS]
        Sent = 0
        AtRisk = await Users.find({
            "guild_id": guild.id, "activity.streak": {"$gte": 1},
            "activity.qualified_at": {"$lte": Now - timedelta(hours=STREAK_WARNING_HOURS)},
        }).to_list(length=None)
        for Doc in AtRisk:
            Activity = Doc.get("activity", {})
            Day = Activity.get("qualified_day")
            if Day == Today.isoformat() or Activity.get("streak_warned") == Day or not CurrentStreak(Activity, Today):
                continue
            Marked = await Users.update_one({"_id": Doc["_id"], "activity.streak_warned": {"$ne": Day}}, {"$set": {"activity.streak_warned": Day}})
            Member = guild.get_member(Doc["user_id"])
            if not Marked.modified_count or Member is None:
                continue
            try:
                await Member.send(StreakText(guild, CurrentStreak(Activity, Today), Deadline, Settings))
                Sent += 1
            except discord.HTTPException:
                pass
        return Sent

    @tasks.loop(minutes=VOICE_TICK_MINUTES)
    async def Voice(self):
        for guild in self.client.guilds:
            try:
                await self.PayVoice(guild)
            except Exception as e:
                logger.error(f"[Economy] Voice pay failed in {guild.id}: {e}")

    @Voice.before_loop
    async def BeforeVoice(self):
        await self.client.wait_until_ready()

    async def PayVoice(self, guild: discord.Guild):
        Config = await EcoConfig().Get(guild.id)
        Settings = Config["voice"]
        if not Settings["enabled"] or Settings["per_minute"] <= 0:
            return
        if not await ModuleCheck(guild.id, MODULE):
            return
        Today = LocalDay(datetime.now(timezone.utc), Config["activity"]["utc_offset"]).isoformat()
        Service = Economy()
        for Channel in guild.voice_channels + guild.stage_channels:
            if guild.afk_channel and Channel.id == guild.afk_channel.id:
                continue
            # Only people actually there: not bots, not deafened.
            Present = [
                M for M in Channel.members
                if not M.bot and not (M.voice and (M.voice.self_deaf or M.voice.deaf))
            ]
            if len(Present) < Settings["min_members"]:
                continue
            for Member in Present:
                async with Service.Lock(guild.id, Member.id):
                    Account = await Service.Account(guild.id, Member.id)
                    Voice = Account.get("voice", {})
                    Earned = int(Voice.get("earned_today", 0)) if Voice.get("day") == Today else 0
                    Amount = min(Settings["per_minute"] * VOICE_TICK_MINUTES, Settings["daily_cap"] - Earned)
                    if Amount <= 0:
                        continue
                    # The daily cap counts the base amount; boosters get their extra on top.
                    await Service.Add(
                        guild.id,
                        Member.id,
                        boost.Boosted(Amount, Member, Config),
                        "Tiempo en voz",
                        also_set={
                            "voice.day": Today,
                            "voice.earned_today": Earned + Amount,
                            "last_active": datetime.now(timezone.utc),
                        },
                    )


async def setup(client: commands.Bot) -> None:
    await client.add_cog(EconomyActivity(client))
