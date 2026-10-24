import logging
import time
from datetime import datetime, timezone

import discord
from discord.ext import commands, tasks

from core.bot.Module import ModuleCheck
from core.economy.activity import OK, Guard, LocalDay, NextPayout
from core.economy.config import EcoConfig
from core.economy.constants import MODULE, VOICE_TICK_MINUTES
from core.economy.service import EconomyError, Economy

logger = logging.getLogger(__name__)

STREAK_EMOJI = "🔥"


class EconomyActivity(commands.Cog):
    """Pays for chatting in the configured channels (and, optionally, for voice time)."""

    def __init__(self, client: commands.Bot):
        self.client = client
        self.guard = Guard()
        self.Voice.start()

    def cog_unload(self):
        self.Voice.cancel()

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
        if not await ModuleCheck(message.guild.id, MODULE):
            return

        Key = (message.guild.id, message.author.id)
        Now = time.monotonic()
        if self.guard.Check(Key, message.content, Now, Settings) != OK:
            return
        # Mark before any await so a second message right after can't also get paid.
        self.guard.MarkPaid(Key, Now)

        Service = Economy()
        async with Service.Lock(message.guild.id, message.author.id):
            Account = await Service.Account(message.guild.id, message.author.id)
            Payout = NextPayout(Account.get("activity", {}), datetime.now(timezone.utc), Settings)
            if Payout.amount <= 0:
                return  # hit today's cap
            try:
                await Service.Add(
                    message.guild.id,
                    message.author.id,
                    Payout.amount,
                    "Actividad en chat",
                    also_set={
                        **{f"activity.{k}": v for k, v in Payout.fields.items()},
                        "last_active": datetime.now(timezone.utc),
                    },
                )
            except EconomyError as e:
                logger.warning(f"[Economy] Activity pay failed: {e}")
                return

        if Payout.qualified_now and Settings["react_streak"]:
            try:
                await message.add_reaction(STREAK_EMOJI)
            except discord.HTTPException:
                pass

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
                    await Service.Add(
                        guild.id,
                        Member.id,
                        Amount,
                        "Tiempo en voz",
                        also_set={
                            "voice.day": Today,
                            "voice.earned_today": Earned + Amount,
                            "last_active": datetime.now(timezone.utc),
                        },
                    )


async def setup(client: commands.Bot) -> None:
    await client.add_cog(EconomyActivity(client))
