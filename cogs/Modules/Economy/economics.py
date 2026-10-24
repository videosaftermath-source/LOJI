import logging

import discord
from discord import app_commands
from discord.ext import commands, tasks

from core.bot.Module import ModuleCheck, ModuleIsEnabled
from core.bot.emojis import Emojis
from core.economy.casino import CasinoError, ParseBet
from core.economy.config import EcoConfig
from core.economy.constants import ECONOMY_TICK_MINUTES, MODULE
from core.economy.boost import RewardBoost
from core.economy.economics import Interest
from core.economy.registry import Eco
from core.economy.rewards import FormatAmount
from core.economy.service import EconomyError, InsufficientFunds

logger = logging.getLogger(__name__)

NO_LIMIT = {"max": 10**12}


class EconomyEconomics(commands.Cog):
    """Inflation, daily snapshots, bank interest and the /banco commands."""

    def __init__(self, client: commands.Bot):
        self.client = client
        self.Tick.start()

    def cog_unload(self):
        self.Tick.cancel()

    @tasks.loop(minutes=ECONOMY_TICK_MINUTES)
    async def Tick(self):
        for Guild in self.client.guilds:
            try:
                if not await ModuleCheck(Guild.id, MODULE):
                    continue
                Config = await EcoConfig().Get(Guild.id)
                Economics = Eco().economics
                Updated = await Economics.UpdateInflation(Guild.id, Config)
                if Updated:
                    logger.info(f"[Economy] {Guild.id} price multiplier x{Updated['multiplier']} (target x{Updated['target']})")
                Paid = await Economics.PayInterest(Guild.id, Config)
                if Paid:
                    logger.info(f"[Economy] {Guild.id} paid {Paid} in bank interest")
                await Economics.Snapshot(Guild.id, Config)
            except Exception as e:
                logger.error(f"[Economy] Tick failed for {Guild.id}: {e}")

    @Tick.before_loop
    async def BeforeTick(self):
        await self.client.wait_until_ready()

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        """Thanks new boosters with a one-time reward."""
        if after.premium_since is None or before.premium_since == after.premium_since:
            return
        try:
            if not await ModuleCheck(after.guild.id, MODULE):
                return
            Config = await EcoConfig().Get(after.guild.id)
            Paid = await RewardBoost(Eco().economy, after, Config)
        except Exception as e:
            return logger.error(f"[Economy] Boost reward failed: {e}")
        if Paid:
            logger.info(f"[Economy] {after.id} boosted {after.guild.id}: +{Paid}")
            try:
                await after.send(
                    f"💎 ¡Gracias por boostear **{after.guild.name}**! Te regalamos {FormatAmount(Paid, Config)} "
                    f"y desde ahora ganas **x{Config['booster']['multiplier']:g}** y tienes más suerte en el gacha."
                )
            except discord.HTTPException:
                pass

    # ---------------- bank ----------------

    async def BankConfig(self, ctx: commands.Context) -> dict | None:
        Config = await EcoConfig().Get(ctx.guild.id)
        if not Config["bank"]["enabled"]:
            await ctx.send("🏦 El banco está cerrado en este servidor.", ephemeral=True)
            return None
        return Config

    @commands.hybrid_group(name="banco", description="Tu cuenta en el banco")
    @commands.guild_only()
    async def banco(self, ctx: commands.Context):
        pass

    @banco.command(name="ver", description="Mira tu cuenta del banco")
    @ModuleIsEnabled(MODULE)
    async def ver(self, ctx: commands.Context):
        Config = await self.BankConfig(ctx)
        if not Config:
            return
        Account = await Eco().economy.Account(ctx.guild.id, ctx.author.id)
        Bank = int(Account.get("bank", 0))
        Settings = Config["bank"]
        embed = discord.Embed(title="🏦 Banco", color=discord.Color.dark_teal())
        embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.display_avatar)
        embed.add_field(name="En el banco", value=FormatAmount(Bank, Config))
        embed.add_field(name="En la cartera", value=FormatAmount(int(Account.get("balance", 0)), Config))
        embed.add_field(
            name="📈 Intereses",
            value=(
                f"{Settings['interest']:.2%} al día (sobre hasta {Settings['interest_cap']:,})\n"
                f"Mañana ganarías: **{Interest(Bank, Config):,}**"
            ).replace(",", "."),
            inline=False,
        )
        embed.set_footer(text=f"Retirar cuesta un {Settings['withdraw_fee']:.1%}. Los intereses se pagan una vez al día.")
        await ctx.send(embed=embed)

    @banco.command(name="depositar", description="Guarda créditos en el banco (generan intereses)")
    @app_commands.describe(cantidad="Cuánto (500, 1.5k, todo, mitad)")
    @ModuleIsEnabled(MODULE)
    async def depositar(self, ctx: commands.Context, cantidad: str):
        Config = await self.BankConfig(ctx)
        if not Config:
            return
        try:
            Amount = ParseBet(cantidad, await Eco().economy.PeekBalance(ctx.guild.id, ctx.author.id), NO_LIMIT)
            Account = await Eco().economics.Deposit(ctx.guild.id, ctx.author.id, Amount)
        except InsufficientFunds as e:
            return await ctx.send(f"{Emojis.no} Solo tienes {FormatAmount(e.balance, Config)} en la cartera.", ephemeral=True)
        except (EconomyError, CasinoError) as e:
            return await ctx.send(f"{Emojis.no} {e}", ephemeral=True)
        await ctx.send(
            f"🏦 Depositaste {FormatAmount(Amount, Config)}. En el banco tienes {FormatAmount(int(Account.get('bank', 0)), Config)}.",
            ephemeral=True,
        )

    @banco.command(name="retirar", description="Saca créditos del banco (con una pequeña comisión)")
    @app_commands.describe(cantidad="Cuánto (500, 1.5k, todo, mitad)")
    @ModuleIsEnabled(MODULE)
    async def retirar(self, ctx: commands.Context, cantidad: str):
        Config = await self.BankConfig(ctx)
        if not Config:
            return
        try:
            Bank = int((await Eco().economy.Account(ctx.guild.id, ctx.author.id)).get("bank", 0))
            Amount = ParseBet(cantidad, Bank, NO_LIMIT)
            Account, Fee = await Eco().economics.Withdraw(ctx.guild.id, ctx.author.id, Amount, Config)
        except (EconomyError, CasinoError) as e:
            return await ctx.send(f"{Emojis.no} {e}", ephemeral=True)
        await ctx.send(
            f"🏦 Retiraste {FormatAmount(Amount, Config)}"
            + (f" (comisión {FormatAmount(Fee, Config)})" if Fee else "")
            + f". En la cartera tienes {FormatAmount(int(Account['balance']), Config)}.",
            ephemeral=True,
        )


async def setup(client: commands.Bot) -> None:
    await client.add_cog(EconomyEconomics(client))
