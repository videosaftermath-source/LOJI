import discord
from discord import app_commands
from discord.ext import commands

from core.bot.HelpEmbeds import NotYourPanel
from core.bot.emojis import Emojis
from core.bot.permissions import Permissions
from core.economy.config import ConfigError, EcoConfig, GetPath
from core.economy.constants import DEFAULT_CONFIG, SETTINGS, SETTINGS_BY_PATH
from core.economy.rewards import FormatAmount
from core.economy.service import Economy, InsufficientFunds

PANEL_TIMEOUT = 600


def ConfigEmbed(guild: discord.Guild, config: dict) -> discord.Embed:
    embed = discord.Embed(title="⚙️ Configuración de la economía", color=discord.Color.dark_embed())
    Lines = []
    for S in SETTINGS:
        Value = GetPath(config, S.path)
        Default = GetPath(DEFAULT_CONFIG, S.path)
        Lines.append(f"> **{S.label}:** `{Value}`" + ("" if Value == Default else " ✏️"))
    embed.description = "\n".join(Lines) + "\n\n-# ✏️ = cambiado. Elige una opción abajo para editarla (déjala vacía para volver al valor por defecto)."
    embed.set_author(name=guild.name, icon_url=guild.icon)
    return embed


class EditValue(discord.ui.Modal):
    def __init__(self, path: str, current, message: discord.Message):
        S = SETTINGS_BY_PATH[path]
        super().__init__(title=S.label[:45])
        self.path = path
        self.message = message
        self.value = discord.ui.TextInput(
            label="Nuevo valor (vacío = por defecto)",
            default=str(current),
            required=False,
            max_length=64,
            placeholder=S.help[:100] or None,
        )
        self.add_item(self.value)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            Config = await EcoConfig().Set(interaction.guild.id, self.path, self.value.value)
        except ConfigError as e:
            return await interaction.response.send_message(f"{Emojis.no} {e}", ephemeral=True)
        await interaction.response.edit_message(embed=ConfigEmbed(interaction.guild, Config))


class SettingSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(
            placeholder="Editar una opción",
            options=[discord.SelectOption(label=S.label[:100], value=S.path) for S in SETTINGS],
        )

    async def callback(self, interaction: discord.Interaction):
        Config = await EcoConfig().Get(interaction.guild.id)
        await interaction.response.send_modal(
            EditValue(self.values[0], GetPath(Config, self.values[0]), interaction.message)
        )


class ConfigPanel(discord.ui.View):
    def __init__(self, author: discord.Member):
        super().__init__(timeout=PANEL_TIMEOUT)
        self.author = author
        self.add_item(SettingSelect())

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author.id:
            await interaction.response.send_message(embed=NotYourPanel(), ephemeral=True)
            return False
        return True


class EconomyAdmin(commands.Cog):
    """Comandos de admin de la economía."""

    def __init__(self, client: commands.Bot):
        self.client = client

    @commands.hybrid_group(name="eco-admin", description="Administrar la economía")
    @app_commands.default_permissions(manage_guild=True)
    @commands.guild_only()
    async def eco_admin(self, ctx: commands.Context):
        pass

    @eco_admin.command(name="dar", description="Darle créditos a alguien")
    @app_commands.describe(usuario="A quién", cantidad="Cuántos", motivo="Por qué (queda en el registro)")
    @Permissions("Admin")
    async def dar(self, ctx: commands.Context, usuario: discord.Member, cantidad: commands.Range[int, 1], motivo: str = "Sin motivo"):
        Config = await EcoConfig().Get(ctx.guild.id)
        Updated = await Economy().Add(ctx.guild.id, usuario.id, cantidad, f"Admin {ctx.author.id}: {motivo}")
        await ctx.send(
            f"{Emojis.tick} Le diste {FormatAmount(cantidad, Config)} a {usuario.mention}. Ahora tiene {FormatAmount(Updated['balance'], Config)}.",
            ephemeral=True,
        )

    @eco_admin.command(name="quitar", description="Quitarle créditos a alguien")
    @app_commands.describe(usuario="A quién", cantidad="Cuántos", motivo="Por qué (queda en el registro)")
    @Permissions("Admin")
    async def quitar(self, ctx: commands.Context, usuario: discord.Member, cantidad: commands.Range[int, 1], motivo: str = "Sin motivo"):
        Config = await EcoConfig().Get(ctx.guild.id)
        try:
            Updated = await Economy().Remove(ctx.guild.id, usuario.id, cantidad, f"Admin {ctx.author.id}: {motivo}")
        except InsufficientFunds as e:
            return await ctx.send(
                f"{Emojis.no} {usuario.mention} solo tiene {FormatAmount(e.balance, Config)}.", ephemeral=True
            )
        await ctx.send(
            f"{Emojis.tick} Le quitaste {FormatAmount(cantidad, Config)} a {usuario.mention}. Le quedan {FormatAmount(Updated['balance'], Config)}.",
            ephemeral=True,
        )

    @eco_admin.command(name="config", description="Ver y editar la configuración de la economía")
    @Permissions("Admin")
    async def config(self, ctx: commands.Context):
        Config = await EcoConfig().Get(ctx.guild.id)
        await ctx.send(embed=ConfigEmbed(ctx.guild, Config), view=ConfigPanel(ctx.author), ephemeral=True)


async def setup(client: commands.Bot) -> None:
    await client.add_cog(EconomyAdmin(client))
