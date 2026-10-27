import asyncio
import io
import logging
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands

from core.bot.HelpEmbeds import NotYourPanel
from core.bot.emojis import Emojis
from core.bot.permissions import Permissions
from core.economy.audit import CATEGORIES, PERIODS, Audit
from core.economy.audit import TOP as AUDIT_TOP
from core.economy.config import ConfigError, EcoConfig, GetPath
from core.economy.constants import DEFAULT_CONFIG, PETS, SECTIONS, SETTINGS, SETTINGS_BY_PATH, USERS
from core.economy.charts import StatsChart
from core.economy.rewards import Aware, FormatAmount
from core.economy.tax import FormatBrackets
from core.economy.registry import Eco
from core.economy.reset import ResetUser
from core.economy.service import EconomyError, Economy, InsufficientFunds

PANEL_TIMEOUT = 600


def Show(value) -> str:
    if isinstance(value, list):
        return FormatBrackets(value)
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



logger = logging.getLogger(__name__)
RESET_TIMEOUT = 120

class ResetConfirm(discord.ui.View):
    """Second step of /eco-admin reiniciar."""

    def __init__(self, author: discord.Member, target: discord.abc.User, reason: str):
        super().__init__(timeout=RESET_TIMEOUT)
        self.author = author
        self.target = target
        self.reason = reason

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author.id:
            await interaction.response.send_message(embed=NotYourPanel(), ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Sí, borrar todo", emoji="🗑️", style=discord.ButtonStyle.red)
    async def Confirm(self, interaction: discord.Interaction, _):
        await interaction.response.defer()
        Config = await EcoConfig().Get(interaction.guild.id)
        Done = await ResetUser(Economy(), interaction.guild.id, self.target.id, interaction.user.id, self.reason)
        logger.warning(f"[Economy] {interaction.user.id} reset {self.target.id} in {interaction.guild.id}: {Done} ({self.reason})")
        Lines = "\n".join(f"> {Label}: **{Count}**" for Label, Count in Done.items() if Label not in ("wallet", "bank") and Count)
        embed = discord.Embed(
            title=f"{Emojis.tick} Economía reiniciada",
            description=(
                f"{self.target.mention} empieza de cero.\n"
                f"> 💰 Quitado: {FormatAmount(Done['wallet'] + Done['bank'], Config)}\n" + Lines
            ),
            color=discord.Color.green(),
        )
        self.stop()
        await interaction.edit_original_response(embed=embed, view=None)

    @discord.ui.button(label="Cancelar", style=discord.ButtonStyle.grey)
    async def Cancel(self, interaction: discord.Interaction, _):
        self.stop()
        await interaction.response.edit_message(content="Cancelado, no se borró nada.", embed=None, view=None)

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


async def StatsMessage(guild: discord.Guild) -> tuple[discord.Embed, discord.File]:
    """The /eco-admin stats embed and its chart."""
    Config = await EcoConfig().Get(guild.id)
    Economics = Eco().economics
    Settings = Config["inflation"]
    Supply = await Economics.Supply(guild.id, Settings["active_days"])
    State = await Economics.InflationState(guild.id)
    Flows = await Economics.Flows(guild.id, datetime.now(timezone.utc) - timedelta(days=7))
    Richest = await Economics.Richest(guild.id, 5)

    def M(amount):
        return FormatAmount(int(amount), Config)

    embed = discord.Embed(title="📊 Estado de la economía", color=discord.Color.dark_teal())
    Average = Supply["active"] / Supply["active_users"] if Supply["active_users"] else 0
    embed.add_field(
        name="💰 En circulación",
        value=(
            f"{M(Supply['total'])} en total\n"
            f"{Supply['active_users']} activos (últimos {Settings['active_days']} días) con {M(Supply['active'])}\n"
            f"Media por activo: **{int(Average):,}** (objetivo {Settings['target_per_user']:,})"
        ).replace(",", "."),
        inline=False,
    )
    if Settings["enabled"]:
        Next = Aware(State.get("updated_at"))
        Value = f"Precios **x{State.get('multiplier', 1.0):.2f}**"
        if "previous" in State:
            Value += f" (antes x{State['previous']:.2f}, tiende a x{State['target']:.2f})"
        if Next:
            Value += f"\nPróxima revisión {discord.utils.format_dt(Next + timedelta(hours=Settings['interval_hours']), 'R')}"
        Value += f"\n-# Afecta a tienda, mascotas{' y gacha' if Settings['gacha'] else ''}"
    else:
        Value = "Desactivada (precios x1.00)"
    embed.add_field(name="📈 Inflación", value=Value, inline=False)
    embed.add_field(
        name="🔄 Últimos 7 días",
        value=(
            f"➕ Creado: {M(Flows['created'])}\n"
            f"➖ Destruido (tienda, mascotas, gacha): {M(Flows['destroyed'])}\n"
            f"💸 Impuestos: {M(Flows['taxes'])}\n"
            f"🎲 Ganancia del casino: {M(Flows['casino'])}\n"
            f"**Neto: {'+' if Flows['net'] >= 0 else ''}" + f"{Flows['net']:,}".replace(",", ".") + "**"
        ),
        inline=False,
    )
    embed.add_field(
        name="🏆 Mayores fortunas (cartera + banco)",
        value="\n".join(f"`#{i}` <@{R['user_id']}> · {M(R['money'])}" for i, R in enumerate(Richest, 1)) or "Nadie todavía",
        inline=False,
    )
    History = await Economics.History(guild.id)
    Png = await asyncio.to_thread(StatsChart, History, Config["currency"]["name"])
    embed.set_image(url="attachment://economia.png")
    embed.set_footer(text="El gráfico se actualiza cada pocos minutos.")
    return embed, discord.File(io.BytesIO(Png), "economia.png")


class StatsPanel(discord.ui.View):
    def __init__(self, author: discord.Member):
        super().__init__(timeout=PANEL_TIMEOUT)
        self.author = author

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author.id:
            await interaction.response.send_message(embed=NotYourPanel(), ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Revisar inflación ahora", emoji="🔄", style=discord.ButtonStyle.blurple)
    async def Recalculate(self, interaction: discord.Interaction, _):
        await interaction.response.defer()
        Config = await EcoConfig().Get(interaction.guild.id)
        await Eco().economics.UpdateInflation(interaction.guild.id, Config, force=True)
        await Eco().economics.Snapshot(interaction.guild.id, Config)
        embed, File = await StatsMessage(interaction.guild)
        await interaction.edit_original_response(embed=embed, attachments=[File], view=self)


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

    @eco_admin.command(name="reiniciar", description="Borra TODA la economía de alguien: dinero, banco, mascotas, items y progreso")
    @app_commands.describe(usuario="A quién reiniciar", motivo="Por qué (queda en el registro)")
    @Permissions("Admin")
    async def reiniciar(self, ctx: commands.Context, usuario: discord.User, motivo: str = "Sin motivo"):
        Config = await EcoConfig().Get(ctx.guild.id)
        Account = await Economy().db[USERS].find_one({"guild_id": ctx.guild.id, "user_id": usuario.id}) or {}
        Pets = await Economy().db[PETS].count_documents({"guild_id": ctx.guild.id, "user_id": usuario.id})
        embed = discord.Embed(
            title="⚠️ Reiniciar economía",
            description=(
                f"Vas a borrar **todo** lo de {usuario.mention} en la economía:\n"
                f"> 💰 Cartera: {FormatAmount(int(Account.get('balance', 0)), Config)}\n"
                f"> 🏦 Banco: {FormatAmount(int(Account.get('bank', 0)), Config)}\n"
                f"> 🐾 Mascotas: **{Pets}**\n"
                "> 📦 Items, boosts activos, rachas, estadísticas del casino, pity del gacha y progreso de misiones\n\n"
                "**No se puede deshacer.** Los códigos que ya canjeó siguen contando como canjeados."
            ),
            color=discord.Color.red(),
        )
        embed.set_footer(text=f"Motivo: {motivo}"[:2048])
        await ctx.send(embed=embed, view=ResetConfirm(ctx.author, usuario, motivo), ephemeral=True)

    @eco_admin.command(name="hacienda", description="Top 10 de quién más ganó en un periodo, separado por origen (para detectar abusos)")
    @app_commands.describe(periodo="Cuánto mirar hacia atrás", ordenar="Por qué ordenar el top")
    @app_commands.choices(
        periodo=[app_commands.Choice(name=f"Últimas {P}" if P == "24h" else f"Últimos {P[:-1]} días", value=P) for P in PERIODS],
        ordenar=[app_commands.Choice(name="Total", value="total")]
        + [app_commands.Choice(name=f"{E} {L}", value=K) for K, (E, L) in CATEGORIES.items()],
    )
    @Permissions("Admin")
    async def hacienda(self, ctx: commands.Context, periodo: str = "24h", ordenar: str = "total"):
        await ctx.defer(ephemeral=True)
        if periodo not in PERIODS or (ordenar != "total" and ordenar not in CATEGORIES):
            return await ctx.send(f"{Emojis.no} Periodo u orden no válido.", ephemeral=True)
        Config = await EcoConfig().Get(ctx.guild.id)
        Users = await Audit(Economy(), ctx.guild.id, periodo, Config)
        Users.sort(key=lambda U: U[ordenar], reverse=True)
        Name = "las últimas 24 h" if periodo == "24h" else f"los últimos {periodo[:-1]} días"

        def Signed(value: int) -> str:
            return f"{value:+,}".replace(",", ".")

        Lines = []
        for Rank, U in enumerate([U for U in Users if U[ordenar] > 0][:AUDIT_TOP], 1):
            Parts = " · ".join(f"{CATEGORIES[C][0]} {Signed(U[C])}" for C in CATEGORIES if U[C])
            Games = f" ({U['games']} {'partida' if U['games'] == 1 else 'partidas'})" if U["games"] else ""
            Lines.append(f"**{Rank}.** <@{U['user_id']}> · **{Signed(U['total'])}**\n> {Parts}{Games}")
            Lines += [f"> {Flag}" for Flag in U["flags"]]
        Totals = {C: sum(U[C] for U in Users) for C in CATEGORIES}
        embed = discord.Embed(
            title=f"🧾 Hacienda · {Name}",
            description="\n".join(Lines)[:4000] or "Nadie ganó dinero en este periodo.",
            color=discord.Color.dark_red(),
        )
        embed.add_field(
            name="En todo el servidor",
            value="\n".join(f"{E} {L}: **{Signed(Totals[C])}**" for C, (E, L) in CATEGORIES.items()),
            inline=False,
        )
        embed.set_footer(
            text=f"Ordenado por: {'total' if ordenar == 'total' else CATEGORIES[ordenar][1]} · "
            "No cuenta gastos (tienda, gacha, mascotas) ni movimientos del banco"
        )
        await ctx.send(embed=embed, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

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

    @eco_admin.command(name="stats", description="Estado de la economía: dinero, inflación, flujos y gráfico")
    @Permissions("Admin")
    async def stats(self, ctx: commands.Context):
        await ctx.defer(ephemeral=True)
        Config = await EcoConfig().Get(ctx.guild.id)
        await Eco().economics.Snapshot(ctx.guild.id, Config)
        embed, File = await StatsMessage(ctx.guild)
        await ctx.send(embed=embed, file=File, view=StatsPanel(ctx.author), ephemeral=True)

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
