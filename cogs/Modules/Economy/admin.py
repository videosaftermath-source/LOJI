import discord
from discord import app_commands
from discord.ext import commands

from core.bot.HelpEmbeds import NotYourPanel
from core.bot.emojis import Emojis
from core.bot.permissions import Permissions
from core.economy.config import ConfigError, EcoConfig, GetPath
from core.economy.constants import DEFAULT_CONFIG, SECTIONS, SETTINGS, SETTINGS_BY_PATH
from core.economy.rewards import FormatAmount
from core.economy.registry import Eco
from core.economy.service import EconomyError, Economy, InsufficientFunds

PANEL_TIMEOUT = 600


def Show(value) -> str:
    if isinstance(value, bool):
        return "sí" if value else "no"
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


def ConfigEmbed(guild: discord.Guild, config: dict, section: str) -> discord.Embed:
    embed = discord.Embed(title=f"⚙️ Economía · {SECTIONS[section]}", color=discord.Color.dark_embed())
    Lines = []
    if section == "activity":
        Channels = ", ".join(f"<#{C}>" for C in config["activity"]["channels"]) or "**ninguno** (no se paga por chat)"
        Lines.append(f"> **Canales que pagan:** {Channels}")
    for S in SETTINGS:
        if S.section != section:
            continue
        Value = GetPath(config, S.path)
        Default = GetPath(DEFAULT_CONFIG, S.path)
        Lines.append(f"> **{S.label}:** `{Show(Value)}`" + ("" if Value == Default else " ✏️"))
    embed.description = "\n".join(Lines) + "\n\n-# ✏️ = cambiado. Elige una opción abajo para editarla (déjala vacía para volver al valor por defecto)."
    embed.set_author(name=guild.name, icon_url=guild.icon)
    return embed


class EditValue(discord.ui.Modal):
    def __init__(self, panel: "ConfigPanel", path: str, current):
        S = SETTINGS_BY_PATH[path]
        super().__init__(title=S.label[:45])
        self.panel = panel
        self.path = path
        self.value = discord.ui.TextInput(
            label="Nuevo valor (vacío = por defecto)",
            default=Show(current),
            required=False,
            max_length=64,
            placeholder=(S.help or ("sí / no" if S.kind is bool else ""))[:100] or None,
        )
        self.add_item(self.value)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            Config = await EcoConfig().Set(interaction.guild.id, self.path, self.value.value)
        except ConfigError as e:
            return await interaction.response.send_message(f"{Emojis.no} {e}", ephemeral=True)
        await interaction.response.edit_message(embed=ConfigEmbed(interaction.guild, Config, self.panel.section))


class SectionSelect(discord.ui.Select):
    def __init__(self, current: str):
        super().__init__(
            placeholder="Sección",
            options=[discord.SelectOption(label=L, value=K, default=K == current) for K, L in SECTIONS.items()],
            row=0,
        )

    async def callback(self, interaction: discord.Interaction):
        Panel: ConfigPanel = self.view
        Panel.Build(self.values[0])
        Config = await EcoConfig().Get(interaction.guild.id)
        await interaction.response.edit_message(embed=ConfigEmbed(interaction.guild, Config, Panel.section), view=Panel)


class SettingSelect(discord.ui.Select):
    def __init__(self, section: str):
        super().__init__(
            placeholder="Editar una opción",
            options=[
                discord.SelectOption(label=S.label[:100], value=S.path)
                for S in SETTINGS
                if S.section == section
            ],
            row=1,
        )

    async def callback(self, interaction: discord.Interaction):
        Config = await EcoConfig().Get(interaction.guild.id)
        await interaction.response.send_modal(
            EditValue(self.view, self.values[0], GetPath(Config, self.values[0]))
        )


class ChannelsSelect(discord.ui.ChannelSelect):
    def __init__(self, guild: discord.Guild, current: list[int]):
        super().__init__(
            placeholder="Canales donde chatear paga",
            channel_types=[discord.ChannelType.text, discord.ChannelType.news],
            min_values=0,
            max_values=10,
            default_values=[C for C in (guild.get_channel(i) for i in current) if C],
            row=2,
        )

    async def callback(self, interaction: discord.Interaction):
        Config = await EcoConfig().SetChannels(interaction.guild.id, [C.id for C in self.values])
        await interaction.response.edit_message(embed=ConfigEmbed(interaction.guild, Config, "activity"))


class ConfigPanel(discord.ui.View):
    def __init__(self, author: discord.Member, guild: discord.Guild, config: dict, section: str = "general"):
        super().__init__(timeout=PANEL_TIMEOUT)
        self.author = author
        self.guild = guild
        self.config = config
        self.Build(section)

    def Build(self, section: str):
        self.section = section
        self.clear_items()
        self.add_item(SectionSelect(section))
        self.add_item(SettingSelect(section))
        if section == "activity":
            self.add_item(ChannelsSelect(self.guild, self.config["activity"]["channels"]))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author.id:
            await interaction.response.send_message(embed=NotYourPanel(), ephemeral=True)
            return False
        # Keep the channel picker's defaults up to date.
        self.config = await EcoConfig().Get(interaction.guild.id)
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
        await ctx.send(
            embed=ConfigEmbed(ctx.guild, Config, "general"),
            view=ConfigPanel(ctx.author, ctx.guild, Config),
            ephemeral=True,
        )

    @eco_admin.command(name="tienda", description="Crear y editar los items de la tienda")
    @Permissions("Admin")
    async def tienda(self, ctx: commands.Context):
        from cogs.Modules.Economy.admin_panels import ShopEmbed, ShopPanel

        Items = await Eco().shop.List(ctx.guild.id)
        await ctx.send(embed=await ShopEmbed(ctx.guild), view=ShopPanel(ctx.author, Items), ephemeral=True)

    @eco_admin.command(name="codigos", description="Crear y borrar códigos de canje")
    @Permissions("Admin")
    async def codigos(self, ctx: commands.Context):
        from cogs.Modules.Economy.admin_panels import CodesEmbed, CodesPanel

        Codes = await Eco().codes.List(ctx.guild.id)
        await ctx.send(embed=await CodesEmbed(ctx.guild), view=CodesPanel(ctx.author, Codes), ephemeral=True)

    @eco_admin.command(name="misiones", description="Crear y editar misiones")
    @Permissions("Admin")
    async def misiones(self, ctx: commands.Context):
        from cogs.Modules.Economy.admin_panels import QuestsEmbed, QuestsPanel

        Quests = await Eco().quests.List(ctx.guild.id)
        await ctx.send(embed=await QuestsEmbed(ctx.guild), view=QuestsPanel(ctx.author, Quests), ephemeral=True)

    @eco_admin.command(name="mascotas", description="Crear y editar las especies de mascotas")
    @Permissions("Admin")
    async def mascotas(self, ctx: commands.Context):
        from cogs.Modules.Economy.admin_panels import SpeciesEmbed, SpeciesPanel

        All = await Eco().pets.AllSpecies(ctx.guild.id)
        await ctx.send(embed=await SpeciesEmbed(ctx.guild), view=SpeciesPanel(ctx.author, All), ephemeral=True)

    @eco_admin.command(name="regalar-mascota", description="Regalarle una mascota a alguien (para pruebas o premios)")
    @app_commands.describe(usuario="A quién", especie="Qué especie")
    @Permissions("Admin")
    async def regalar_mascota(self, ctx: commands.Context, usuario: discord.Member, especie: str):
        Config = await EcoConfig().Get(ctx.guild.id)
        try:
            Pet, New = await Eco().pets.Grant(ctx.guild.id, usuario.id, especie.upper(), f"admin:{ctx.author.id}", Config)
        except EconomyError as e:
            return await ctx.send(f"{Emojis.no} {e}", ephemeral=True)
        Species = await Eco().pets.GetSpecies(ctx.guild.id, Pet["species_id"])
        Text = (
            f"🎁 Le regalaste un {Species.get('emoji') or '🐾'} **{Species['name']}** a {usuario.mention}."
            if New
            else f"{usuario.mention} ya tenía un {Species['name']}: le di +{Config['pets']['xp_duplicate']} XP."
        )
        await ctx.send(Text, ephemeral=True)

    @regalar_mascota.autocomplete("especie")
    async def EspecieAutocomplete(self, interaction: discord.Interaction, current: str):
        return [
            app_commands.Choice(name=f"{S['name']} ({S['rarity']})"[:100], value=S["species_id"])
            for S in await Eco().pets.AllSpecies(interaction.guild.id)
            if current.lower() in S["name"].lower()
        ][:25]

    @eco_admin.command(name="gacha", description="Crear y editar los banners del gacha")
    @Permissions("Admin")
    async def gacha(self, ctx: commands.Context):
        from cogs.Modules.Economy.admin_panels import BannersEmbed, BannersPanel

        Banners = await Eco().gacha.List(ctx.guild.id)
        await ctx.send(embed=await BannersEmbed(ctx.guild), view=BannersPanel(ctx.author, Banners), ephemeral=True)

    @eco_admin.command(name="desbloquear", description="Quitarle el bloqueo anti-spam a alguien")
    @app_commands.describe(usuario="A quién")
    @Permissions("Admin")
    async def desbloquear(self, ctx: commands.Context, usuario: discord.Member):
        Activity = self.client.get_cog("EconomyActivity")
        if Activity:
            Activity.guard.Unblock((ctx.guild.id, usuario.id))
        await ctx.send(f"{Emojis.tick} {usuario.mention} ya puede volver a ganar por chatear.", ephemeral=True)


async def setup(client: commands.Bot) -> None:
    await client.add_cog(EconomyAdmin(client))
