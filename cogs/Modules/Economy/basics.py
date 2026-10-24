import random
import time
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands

from core.bot.HelpEmbeds import NotYourPanel
from core.bot.Module import ModuleIsEnabled
from core.bot.emojis import Emojis
from core.economy.activity import CurrentStreak, LocalDay, Multiplier
from core.economy.config import EcoConfig
from core.economy.constants import MODULE, WORK_LINES
from core.economy.rewards import Aware, DailyStatus, FormatAmount, WorkAmount, WorkReadyAt
from core.economy.service import ConditionFailed, EconomyError, Economy, InsufficientFunds
from core.economy.tax import TransferFee

CONFIRM_TIMEOUT = 60
TOP_TIMEOUT = 300
MEDALS = {1: "🥇", 2: "🥈", 3: "🥉"}


def Relative(dt: datetime) -> str:
    return discord.utils.format_dt(dt, "R")


class ConfirmPay(discord.ui.View):
    def __init__(self, cog: "EconomyBasics", author: discord.Member, target: discord.Member, amount: int, fee: int):
        super().__init__(timeout=CONFIRM_TIMEOUT)
        self.cog = cog
        self.author = author
        self.target = target
        self.amount = amount
        self.fee = fee

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author.id:
            await interaction.response.send_message(embed=NotYourPanel(), ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Pagar", emoji="💸", style=discord.ButtonStyle.green)
    async def Pay(self, interaction: discord.Interaction, _):
        # Stop first so a double click can't pay twice.
        if self.is_finished():
            return await interaction.response.defer()
        self.stop()
        Config = await self.cog.config.Get(interaction.guild.id)
        try:
            From, _ = await Economy().Transfer(
                interaction.guild.id,
                self.author.id,
                self.target.id,
                self.amount,
                f"Pago a {self.target.id}",
                fee=self.fee,
            )
        except InsufficientFunds as e:
            return await interaction.response.edit_message(
                content=f"{Emojis.no} No te alcanza, pobre 😔 Necesitas {FormatAmount(self.amount + self.fee, Config)} (con comisión) y tienes {FormatAmount(e.balance, Config)}.",
                view=None,
            )
        except EconomyError as e:
            return await interaction.response.edit_message(content=f"{Emojis.no} {e}", view=None)
        await interaction.response.edit_message(
            content=f"{Emojis.tick} Le pagaste {FormatAmount(self.amount, Config)} a {self.target.mention}"
            + (f" (+{FormatAmount(self.fee, Config)} de comisión)" if self.fee else "")
            + f". Te quedan {FormatAmount(From['balance'], Config)}.",
            view=None,
        )

    @discord.ui.button(label="Cancelar", style=discord.ButtonStyle.grey)
    async def Cancel(self, interaction: discord.Interaction, _):
        self.stop()
        await interaction.response.edit_message(content="Pago cancelado.", view=None)


class TopView(discord.ui.View):
    def __init__(self, cog: "EconomyBasics", guild: discord.Guild, page: int, pages: int):
        super().__init__(timeout=TOP_TIMEOUT)
        self.cog = cog
        self.guild = guild
        self.page = page
        self.pages = pages
        self.Update()

    def Update(self):
        self.Previous.disabled = self.page <= 0
        self.Next.disabled = self.page >= self.pages - 1

    @discord.ui.button(emoji="⬅️", style=discord.ButtonStyle.grey)
    async def Previous(self, interaction: discord.Interaction, _):
        self.page -= 1
        self.Update()
        await interaction.response.edit_message(embed=await self.cog.TopEmbed(self.guild, self.page, interaction.user), view=self)

    @discord.ui.button(emoji="➡️", style=discord.ButtonStyle.grey)
    async def Next(self, interaction: discord.Interaction, _):
        self.page += 1
        self.Update()
        await interaction.response.edit_message(embed=await self.cog.TopEmbed(self.guild, self.page, interaction.user), view=self)


class EconomyBasics(commands.Cog):
    """Saldo, trabajar, diario, pagar y top."""

    def __init__(self, client: commands.Bot):
        self.client = client
        self.config = EcoConfig()

    async def cog_load(self):
        await Economy().Setup()

    @commands.hybrid_command(name="saldo", description="Mira cuántos créditos tienes (o tiene alguien)")
    @app_commands.describe(usuario="De quién quieres ver el saldo")
    @commands.guild_only()
    @ModuleIsEnabled(MODULE)
    async def saldo(self, ctx: commands.Context, usuario: discord.Member = None):
        Member = usuario or ctx.author
        if Member.bot:
            return await ctx.send(f"{Emojis.no} Los bots no tienen bolsillos.", ephemeral=True)
        Config = await self.config.Get(ctx.guild.id)
        Account = await Economy().Account(ctx.guild.id, Member.id)
        Rank = await Economy().Rank(ctx.guild.id, Member.id)
        Now = datetime.now(timezone.utc)

        WorkAt = WorkReadyAt(Account.get("work", {}).get("last"), Config)
        Daily = DailyStatus(
            Account.get("daily", {}).get("last"), Account.get("daily", {}).get("streak", 0), Now, Config
        )
        Streak = Account.get("daily", {}).get("streak", 0) if Daily.ready_at or not Daily.lost_streak else 0

        embed = discord.Embed(color=discord.Color.gold())
        embed.set_author(name=f"Cartera de {Member.display_name}", icon_url=Member.display_avatar)
        embed.description = (
            f"> **Saldo:** {FormatAmount(int(Account.get('balance', 0)), Config)}\n"
            f"> **Puesto:** {f'#{Rank}' if Rank else 'Sin rankear'}\n"
            f"> **Racha diaria:** 🔥 {Streak} día(s)"
        )
        Chat = Config["activity"]
        if Chat["channels"]:
            Activity = Account.get("activity", {})
            Today = LocalDay(Now, Chat["utc_offset"])
            ChatStreak = CurrentStreak(Activity, Today)
            SameDay = Activity.get("day") == Today.isoformat()
            Paid = int(Activity.get("paid_today", 0)) if SameDay else 0
            Earned = int(Activity.get("earned_today", 0)) if SameDay else 0
            Goal = Chat["streak_messages"]
            Value = (
                f"> **Racha de chat:** 🔥 {ChatStreak} día(s) · x{Multiplier(ChatStreak, Chat):.2f}\n"
                f"> **Hoy:** {FormatAmount(Earned, Config)} de {FormatAmount(Chat['hard_cap'], Config)} · "
                f"{min(Paid, Goal)}/{Goal} mensajes para la racha"
            )
            Guard = getattr(self.client.get_cog("EconomyActivity"), "guard", None)
            Blocked = Guard.BlockedFor((ctx.guild.id, Member.id), time.monotonic()) if Guard else 0
            if Blocked and Member == ctx.author:
                Value += f"\n> 🚫 **Bloqueado por spam** {Relative(Now + timedelta(seconds=Blocked))}"
            embed.add_field(name="💬 Chat", value=Value, inline=False)
        if Member == ctx.author:
            embed.add_field(
                name="⏰ Disponibles",
                value=(
                    f"> `/trabajar` {Relative(WorkAt) if WorkAt else '¡ya!'}\n"
                    f"> `/diario` {Relative(Daily.ready_at) if Daily.ready_at else '¡ya!'}"
                ),
                inline=False,
            )
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="trabajar", description="Trabaja un rato y gana créditos")
    @commands.guild_only()
    @ModuleIsEnabled(MODULE)
    async def trabajar(self, ctx: commands.Context):
        Config = await self.config.Get(ctx.guild.id)
        Account = await Economy().Account(ctx.guild.id, ctx.author.id)
        ReadyAt = WorkReadyAt(Account.get("work", {}).get("last"), Config)
        if ReadyAt:
            return await ctx.send(f"😮‍💨 Estás reventado. Vuelve a trabajar {Relative(ReadyAt)}.", ephemeral=True)

        Now = datetime.now(timezone.utc)
        Amount = WorkAmount(Config)
        Cooldown = timedelta(seconds=Config["work"]["cooldown"])
        try:
            Updated = await Economy().Add(
                ctx.guild.id,
                ctx.author.id,
                Amount,
                "Trabajar",
                # Only pays if the cooldown is still over at the moment of writing.
                when={"$or": [{"work.last": None}, {"work.last": {"$lte": Now - Cooldown}}]},
                also_set={"work.last": Now, "last_active": Now},
            )
        except ConditionFailed:
            return await ctx.send("😮‍💨 Tranqui, ya trabajaste hace nada.", ephemeral=True)
        embed = discord.Embed(
            description=f"💼 {random.choice(WORK_LINES)} y ganaste {FormatAmount(Amount, Config)}.\n-# Ahora tienes {FormatAmount(Updated['balance'], Config)}. Vuelve {Relative(Now + Cooldown)}.",
            color=discord.Color.green(),
        )
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="diario", description="Reclama tu recompensa diaria (¡no pierdas la racha!)")
    @commands.guild_only()
    @ModuleIsEnabled(MODULE)
    async def diario(self, ctx: commands.Context):
        Config = await self.config.Get(ctx.guild.id)
        async with Economy().Lock(ctx.guild.id, ctx.author.id):
            Account = await Economy().Account(ctx.guild.id, ctx.author.id)
            Last = Account.get("daily", {}).get("last")
            Now = datetime.now(timezone.utc)
            Status = DailyStatus(Last, Account.get("daily", {}).get("streak", 0), Now, Config)
            if Status.ready_at:
                return await ctx.send(f"⏳ Ya reclamaste tu diario. El siguiente está listo {Relative(Status.ready_at)}.", ephemeral=True)
            try:
                Updated = await Economy().Add(
                    ctx.guild.id,
                    ctx.author.id,
                    Status.amount,
                    "Diario",
                    # Only matches if nobody claimed since we read it.
                    when={"daily.last": Last},
                    also_set={"daily.last": Now, "daily.streak": Status.streak, "last_active": Now},
                )
            except ConditionFailed:
                return await ctx.send("⏳ Ya reclamaste tu diario.", ephemeral=True)

        MaxDays = Config["daily"]["max_streak_days"]
        Lines = [f"🎁 ¡Toma {FormatAmount(Status.amount, Config)}!"]
        if Status.lost_streak:
            Lines.append("💀 Perdiste tu racha... empiezas de cero.")
        Lines.append(f"🔥 Racha: **{Status.streak}** día(s)" + (" (¡al máximo!)" if Status.streak >= MaxDays else ""))
        Next = Aware(Now) + timedelta(seconds=Config["daily"]["cooldown"])
        Lines.append(f"-# Ahora tienes {FormatAmount(Updated['balance'], Config)}. El siguiente {Relative(Next)}.")
        await ctx.send(embed=discord.Embed(description="\n".join(Lines), color=discord.Color.orange()))

    @commands.hybrid_command(name="pagar", description="Pásale créditos a alguien")
    @app_commands.describe(usuario="A quién le pagas", cantidad="Cuántos créditos")
    @commands.guild_only()
    @ModuleIsEnabled(MODULE)
    async def pagar(self, ctx: commands.Context, usuario: discord.Member, cantidad: commands.Range[int, 1]):
        Config = await self.config.Get(ctx.guild.id)
        if usuario.bot or usuario == ctx.author:
            return await ctx.send(f"{Emojis.no} Buen intento 😏", ephemeral=True)
        if cantidad < Config["transfer"]["min"]:
            return await ctx.send(
                f"{Emojis.no} El mínimo para pagar es {FormatAmount(Config['transfer']['min'], Config)}.", ephemeral=True
            )
        Fee = TransferFee(cantidad, Config)
        Lines = [f"¿Seguro que le quieres pagar {FormatAmount(cantidad, Config)} a {usuario.mention}?"]
        if Fee:
            Lines.append(
                f"-# Comisión del {Config['transfer']['fee_percent']:g}%: {FormatAmount(Fee, Config)} · "
                f"Total que pagas: {FormatAmount(cantidad + Fee, Config)}"
            )
        await ctx.send(
            "\n".join(Lines),
            view=ConfirmPay(self, ctx.author, usuario, cantidad, Fee),
            ephemeral=True,
        )

    async def TopEmbed(self, guild: discord.Guild, page: int, viewer: discord.abc.User) -> discord.Embed:
        Config = await self.config.Get(guild.id)
        Size = Config["leaderboard"]["page_size"]
        Accounts = await Economy().Top(guild.id, page * Size, Size)
        Lines = []
        for i, A in enumerate(Accounts, start=page * Size + 1):
            Lines.append(f"{MEDALS.get(i, f'`#{i}`')} <@{A['user_id']}> · {FormatAmount(int(A['balance']), Config)}")
        embed = discord.Embed(
            title=f"🏆 Los más ricos de {guild.name}",
            description="\n".join(Lines) or "Aquí todos son pobres todavía. ¡Usa `/trabajar`!",
            color=discord.Color.gold(),
        )
        Rank = await Economy().Rank(guild.id, viewer.id)
        embed.set_footer(text=f"Tu puesto: #{Rank}" if Rank else "Todavía no estás en el top")
        return embed

    @commands.hybrid_command(name="top", description="Los más ricos del servidor")
    @commands.guild_only()
    @ModuleIsEnabled(MODULE)
    async def top(self, ctx: commands.Context):
        Config = await self.config.Get(ctx.guild.id)
        Total = await Economy().CountRanked(ctx.guild.id)
        Pages = max(1, -(-Total // Config["leaderboard"]["page_size"]))
        await ctx.send(embed=await self.TopEmbed(ctx.guild, 0, ctx.author), view=TopView(self, ctx.guild, 0, Pages))


async def setup(client: commands.Bot) -> None:
    await client.add_cog(EconomyBasics(client))
