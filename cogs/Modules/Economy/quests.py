import logging

import discord
from discord import app_commands
from discord.ext import commands

from core.bot.Module import ModuleIsEnabled
from core.bot.emojis import Emojis
from core.economy.config import EcoConfig
from core.economy.constants import MODULE, OBJECTIVES, QUEST_PERIODS
from core.economy.registry import Eco
from core.economy.rewards import FormatAmount
from core.economy.service import EconomyError

logger = logging.getLogger(__name__)

VIEW_TIMEOUT = 600
BAR_LENGTH = 10


def Bar(progress: int, target: int) -> str:
    Filled = min(BAR_LENGTH, int(BAR_LENGTH * progress / target)) if target else BAR_LENGTH
    return "▰" * Filled + "▱" * (BAR_LENGTH - Filled)


async def QuestsMessage(member: discord.Member) -> tuple[discord.Embed, discord.ui.View | None]:
    Config = await EcoConfig().Get(member.guild.id)
    Status = await Eco().quests.Status(member.guild.id, member.id, Config)
    Items = {I["item_id"]: I for I in await Eco().shop.List(member.guild.id)}
    embed = discord.Embed(title="📜 Misiones", color=discord.Color.teal())
    embed.set_author(name=member.display_name, icon_url=member.display_avatar)
    if not Status:
        embed.description = "No hay misiones ahora mismo. Los admins están pensando cosas malvadas 😈"
        return embed, None
    Claimable = []
    for Period, Label in QUEST_PERIODS.items():
        Lines = []
        for Quest, Progress, Claimed in Status:
            if Quest["period"] != Period:
                continue
            Target = int(Quest["target"])
            Reward = []
            if Quest.get("reward"):
                Reward.append(FormatAmount(int(Quest["reward"]), Config))
            if Quest.get("reward_item") in Items:
                Reward.append(f"{Items[Quest['reward_item']].get('emoji') or '📦'} {Items[Quest['reward_item']]['name']}")
            State = "✅ Reclamada" if Claimed else ("🎉 ¡Lista para reclamar!" if Progress >= Target else f"{min(Progress, Target)}/{Target}")
            Lines.append(
                f"**{Quest['name']}** · {OBJECTIVES[Quest['objective']]}\n"
                f"{Bar(Progress, Target)} {State}\n-# Premio: {' + '.join(Reward)}"
            )
            if Progress >= Target and not Claimed:
                Claimable.append(Quest)
        if Lines:
            embed.add_field(name=Label, value="\n".join(Lines)[:1024], inline=False)
    if not Claimable:
        return embed, None
    View = discord.ui.View(timeout=VIEW_TIMEOUT)
    View.add_item(ClaimSelect(member.id, Claimable))
    return embed, View


class ClaimSelect(discord.ui.Select):
    def __init__(self, user_id: int, quests: list[dict]):
        super().__init__(
            placeholder="🎁 Reclamar premio",
            options=[discord.SelectOption(label=Q["name"][:100], value=Q["quest_id"]) for Q in quests[:25]],
        )
        self.user_id = user_id

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("Esas no son tus misiones 👀", ephemeral=True)
        Config = await EcoConfig().Get(interaction.guild.id)
        try:
            Quest = await Eco().quests.Claim(interaction.guild.id, interaction.user.id, self.values[0], Config)
        except EconomyError as e:
            return await interaction.response.send_message(f"{Emojis.no} {e}", ephemeral=True)
        embed, View = await QuestsMessage(interaction.user)
        await interaction.response.edit_message(embed=embed, view=View)
        await interaction.followup.send(f"🎉 Reclamaste **{Quest['name']}**. ¡Bien ahí!", ephemeral=True)


class EconomyQuests(commands.Cog):
    """Misiones y códigos de canje."""

    def __init__(self, client: commands.Bot):
        self.client = client

    @commands.Cog.listener()
    async def on_economy_progress(self, guild_id: int, user_id: int, objective: str, amount: int):
        try:
            Config = await EcoConfig().Get(guild_id)
            await Eco().quests.Track(guild_id, user_id, objective, amount, Config)
        except Exception as e:
            logger.error(f"[Economy] Quest tracking failed: {e}")

    @commands.hybrid_command(name="misiones", description="Mira tus misiones y reclama premios")
    @commands.guild_only()
    @ModuleIsEnabled(MODULE)
    async def misiones(self, ctx: commands.Context):
        embed, View = await QuestsMessage(ctx.author)
        await ctx.send(embed=embed, view=View)

    @commands.hybrid_command(name="canjear", description="Canjea un código de regalo")
    @app_commands.describe(codigo="El código")
    @commands.guild_only()
    @ModuleIsEnabled(MODULE)
    async def canjear(self, ctx: commands.Context, codigo: str):
        Config = await EcoConfig().Get(ctx.guild.id)
        try:
            Code = await Eco().codes.Redeem(ctx.guild.id, ctx.author.id, codigo)
        except EconomyError as e:
            return await ctx.send(f"{Emojis.no} {e}", ephemeral=True)
        Items = {I["item_id"]: I for I in await Eco().shop.List(ctx.guild.id)}
        Prizes = []
        if Code.get("credits"):
            Prizes.append(FormatAmount(Code["credits"], Config))
        for R in Code.get("items", []):
            Item = Items.get(R["item_id"])
            if Item:
                Prizes.append(f"{Item.get('emoji') or '📦'} {R['qty']}x {Item['name']}")
        await ctx.send(f"🎁 ¡Código canjeado! Te llevas: {', '.join(Prizes)}", ephemeral=True)


async def setup(client: commands.Bot) -> None:
    await client.add_cog(EconomyQuests(client))
