import logging

from discord.ext import commands

from core.bot.HelpEmbeds import NoPremium, Support, NotYourPanel
from core.bot.emojis import *
from core.bot.permissions import premium

logger = logging.getLogger(__name__)


async def Reset(i: discord.Interaction, *F):
    try:
        view = discord.ui.View()
        for E in F:
            view.add_item(E())
        await i.edit_original_response(view=view)
    except:
        pass


class ConfigMenu(discord.ui.Select):
    def __init__(self, options: list, author: discord.Member) -> None:
        self.author = author
        super().__init__(placeholder="¿Qué quieres configurar?", options=options)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        if interaction.user.id != self.author.id:
            return await interaction.followup.send(embed=NotYourPanel(), ephemeral=True)

        from cogs.Configuration.Components.Modules import ModuleToggle, ModuleOptions

        Config = await interaction.client.config.find_one({"_id": interaction.guild.id})
        if not Config:
            Config = {
                "_id": interaction.guild.id,
                "Modules": {},
                "Infractions": {},
                "Permissions": {},
            }
        view = discord.ui.View()

        selection = self.values[0]
        if interaction.user.id != self.author.id:
            return await interaction.followup.send(embed=NotYourPanel(), ephemeral=True)
        if selection in ("LOJI_MAIL", "LOJI_ECO", "LOJI_VANITY"):
            return await LojiSection(interaction, selection)
        embed = discord.Embed(color=discord.Colour.dark_embed())

        await Reset(interaction, lambda: ConfigMenu(Options(Config), interaction.user))

        if selection == "Permissions":
            from cogs.Configuration.Components.Permissions import (
                PermissionsEmbed,
                PermissionsUpdate,
            )
            from cogs.Configuration.Components.AdvancedPermissions import (
                PermissionsDropdown,
            )

            embed = await PermissionsEmbed(interaction, Config, embed)
            view.add_item(
                PermissionsUpdate(
                    interaction.user,
                    "staffrole",
                    [
                        role
                        for role in interaction.guild.roles
                        if role.id in Config.get("Permissions", {}).get("staffrole", [])
                        or None
                    ],
                )
            )
            view.add_item(
                PermissionsUpdate(
                    interaction.user,
                    "adminrole",
                    [
                        role
                        for role in interaction.guild.roles
                        if role.id in Config.get("Permissions", {}).get("adminrole", [])
                        or None
                    ],
                )
            )
            view.add_item(PermissionsDropdown(interaction.user))
        elif selection == "Edit Profile":
            from cogs.Configuration.Components.WLite import WLiteOption, WLiteEmbed

            embed = await WLiteEmbed(interaction)
            view = discord.ui.View()
            view.add_item(WLiteOption(interaction.user))

        elif selection == "Modules":
            embed.set_author(
                name=f"{interaction.guild.name}", icon_url=interaction.guild.icon
            )
            embed.set_thumbnail(url=interaction.guild.icon)
            embed.title = "🧩 Módulos"
            embed.description = (
                "> Marca los sistemas que quieres **activados** y desmarca los que no uses.\n"
                "> Los activados aparecen en el menú **¿Qué quieres configurar?** para prepararlos.\n"
                "-# Mando Central, Economía y Vanity no dependen de esto: se configuran siempre desde su opción."
            )

            view.add_item(
                ModuleToggle(
                    interaction.user,
                    await ModuleOptions(Config),
                )
            )
        elif selection == "Hierarchy":
            from cogs.Configuration.Components.Hirearchys import HSELECT, HiEmbed

            embed = await HiEmbed(interaction, Config, embed)
            view = discord.ui.View()
            view.add_item(
                HSELECT(
                    interaction.user,
                    Config.get("Promo", {}).get("System", {}).get("type", "og"),
                )
            )
        elif selection == "infractions":
            from cogs.Configuration.Components.Infractions import (
                InfractionEmbed,
                InfractionOption,
            )

            embed = await InfractionEmbed(interaction, Config, embed)
            view = discord.ui.View()
            view.add_item(
                InfractionOption(
                    interaction.user,
                )
            )
        elif selection == "promotions":
            from cogs.Configuration.Components.Promotions import (
                PromotionEmbed,
                PSelect,
            )

            embed = await PromotionEmbed(interaction, Config, embed)
            view = discord.ui.View()
            view.add_item(
                PSelect(
                    interaction.user,
                )
            )
        elif selection == "Modmail":
            from cogs.Configuration.Components.Modmail import (
                ModmailEmbed,
                ModmailOptions,
            )

            embed = await ModmailEmbed(interaction, Config, embed)
            view = discord.ui.View()
            view.add_item(
                ModmailOptions(
                    interaction.user,
                    Config.get("Module Options", {}).get("ModmailType", "channel"),
                )
            )
        elif selection == "Feedback":
            from cogs.Configuration.Components.StaffFeedback import (
                StaffFeedbackEmbed,
                StaffFeedback,
            )

            embed = await StaffFeedbackEmbed(interaction, Config, embed)
            view = discord.ui.View()
            view.add_item(
                StaffFeedback(
                    interaction.user,
                )
            )
        elif selection == "Quota":
            from cogs.Configuration.Components.MessageQuota import (
                MessageQuotaEmbed,
                QuotaOptions,
            )

            embed = await MessageQuotaEmbed(interaction, Config, embed)
            view = discord.ui.View()
            view.add_item(
                QuotaOptions(
                    interaction.user,
                )
            )
        elif selection == "LOA":
            from cogs.Configuration.Components.LOA import (
                LOAEmbed,
                LOAOptions,
            )

            embed = await LOAEmbed(interaction, Config, embed)
            view = discord.ui.View()
            view.add_item(
                LOAOptions(
                    interaction.user,
                )
            )
        elif selection == "suggestions":
            from cogs.Configuration.Components.Suggestions import (
                SuggestionsEmbed,
                Suggestions,
            )

            embed = await SuggestionsEmbed(interaction, Config, embed)
            view = discord.ui.View()
            view.add_item(
                Suggestions(
                    interaction.user,
                )
            )
        elif selection == "Staff Database":
            from cogs.Configuration.Components.StaffPanel import (
                StaffPanelEmbed,
                StaffPanelOptions,
            )

            embed = await StaffPanelEmbed(interaction, embed)
            view = discord.ui.View()
            view.add_item(
                StaffPanelOptions(
                    interaction.user,
                )
            )
        elif selection == "StaffManagement":
            from cogs.Configuration.Components.StaffManagement import (
                StaffManagementEmbed,
                StaffManagementOptions,
            )

            embed = await StaffManagementEmbed(interaction, Config, embed)
            view = discord.ui.View()
            view.add_item(StaffManagementOptions(interaction.user))
        elif selection == "customcommands":
            try:
                from cogs.Configuration.Components.CustomCommands import (
                    CustomCommandsEmbed,
                    CustomCommands,
                )

                view = discord.ui.View()
                embed = await CustomCommandsEmbed(interaction, embed)
                view.add_item(
                    CustomCommands(
                        interaction.user,
                    )
                )
            except Exception as e:
                import traceback

                logger.error(traceback.format_exc(e))
        elif selection == "suspensions":
            from cogs.Configuration.Components.Suspensions import (
                SuspensionEmbed,
                SuspensionOptions,
            )

            embed = await SuspensionEmbed(interaction, Config, embed)
            view = discord.ui.View()
            view.add_item(SuspensionOptions(interaction.user))
        elif selection == "Auto Responder":
            if not await premium(interaction.guild.id):
                return await interaction.followup.send(
                    embed=NoPremium(), view=Support()
                )

            from cogs.Configuration.Components.AutoResponse import (
                AutoResponseEmbed,
                AutoResponderOptions,
            )

            embed = await AutoResponseEmbed(interaction, embed)
            view = discord.ui.View()
            view.add_item(
                AutoResponderOptions(
                    interaction.user,
                )
            )
        elif selection == "Tickets":
            from cogs.Configuration.Components.Tickets import TicketsEmbed, Tickets

            view = discord.ui.View()
            view.add_item(Tickets(interaction.user))
            embed = await TicketsEmbed(interaction, embed=embed)
        elif selection == "Staff List":
            from cogs.Configuration.Components.stafflist import StaffListEmbed

            view = discord.ui.View()
            embed = await StaffListEmbed(interaction, embed=embed)
        view.add_item(ConfigMenu(Options(Config), interaction.user))
        await interaction.edit_original_response(embed=embed, view=view)


async def LojiSection(interaction: discord.Interaction, selection: str):
    """LOJI's own settings live here too, so everything is configured from /config."""
    if selection == "LOJI_VANITY":
        from cogs.Modules.Supporters.supporters import OpenPanel

        return await OpenPanel(interaction)
    if selection == "LOJI_MAIL":
        from cogs.Modules.Mail.config import MainPanel, PanelEmbed
        from core.mail.config import CanConfigure, Mail

        Config = await Mail().Get(interaction.guild.id)
        if not CanConfigure(interaction.user, Config):
            return await interaction.followup.send("❌ Solo el Tenno (o un administrador) configura el Mando Central.", ephemeral=True)
        return await interaction.edit_original_response(embed=PanelEmbed(interaction.guild, Config), view=MainPanel(interaction.user, Config))
    from cogs.Modules.Economy.admin import ConfigEmbed, ConfigPanel
    from core.economy.config import EcoConfig

    Config = await EcoConfig().Get(interaction.guild.id)
    await interaction.edit_original_response(embed=ConfigEmbed(interaction.guild, Config, "general"), view=ConfigPanel(interaction.user, interaction.guild, Config))


def DefaultEmbed(guild: discord.Guild):
    embed = discord.Embed(
        title="⚙️ Configuración de LOJI",
        description="Elige **qué quieres configurar** en el menú de abajo.",
        color=discord.Color.from_rgb(150, 12, 18),
    )
    embed.add_field(
        name="🧭 Por dónde empezar",
        value=(
            "> **📮 Mando Central:** el staff (cargos, departamentos, perfiles, medallas, feedback y tickets).\n"
            "> **🪙 Economía** y **🏷️ Vanity y tag:** los sistemas de la comunidad.\n"
            "> **Módulos:** enciende o apaga el resto; los que actives aparecen aquí debajo."
        ),
        inline=False,
    )
    embed.add_field(name="📖 Ayuda", value="> Todos los comandos, explicados: `/ayuda`.", inline=False)
    embed.set_thumbnail(url=guild.icon)
    embed.set_author(name=guild.name, icon_url=guild.icon)
    embed.set_footer(text="Solo tú puedes usar este panel")
    return embed


def Options(Config: dict = None):
    """The /config menu. `value` is what the code checks, so labels can be in Spanish."""
    if not Config:
        Config = {"Modules": {}}
    Modules = Config.get("Modules", {})
    options = [
        discord.SelectOption(label="Mando Central", value="LOJI_MAIL", emoji="📮",
                             description="Buzón, tareas, departamentos, cargos, perfiles, medallas y tickets"),
        discord.SelectOption(label="Economía", value="LOJI_ECO", emoji="🪙",
                             description="Ganancias, chat, mascotas, gacha, casino, Marcha, inflación..."),
        discord.SelectOption(label="Vanity y tag", value="LOJI_VANITY", emoji="🏷️",
                             description="Roles, beneficios y anuncio para quien lleva la vanity o el tag"),
        discord.SelectOption(label="Módulos", value="Modules", emoji=f"{Emojis.modules}",
                             description="Activa o desactiva cada sistema del bot"),
        discord.SelectOption(label="Permisos", value="Permissions", emoji=f"{Emojis.settings_page}",
                             description="Qué roles son staff y administración para el bot"),
        discord.SelectOption(label="Jerarquía", value="Hierarchy", emoji=f"{Emojis.hierarchy}",
                             description="El orden de rangos para ascensos y sanciones"),
        discord.SelectOption(label="Perfil del bot", value="Edit Profile", emoji=f"{Emojis.pen}",
                             description="Avatar y apodo del bot en este servidor"),
    ]

    ModuleAddons = [
        discord.SelectOption(label="Sanciones", value="infractions", emoji=f"{Emojis.infractions}",
                             description="Tipos de sanción, canal y aprobaciones"),
        discord.SelectOption(label="Ascensos", value="promotions", emoji=f"{Emojis.promotions}",
                             description="Canal y formato de los ascensos"),
        discord.SelectOption(label="Cuota de mensajes", value="Quota", emoji=f"{Emojis.message_quota}",
                             description="Mínimo semanal del staff y reporte automático"),
        discord.SelectOption(label="Ausencias (LOA)", value="LOA", emoji=f"{Emojis.loa}",
                             description="Solicitudes de ausencia del staff"),
        discord.SelectOption(label="Tickets", value="Tickets", emoji=f"{Emojis.tickets}",
                             description="Paneles, categorías, preguntas y nombres de canal"),
        discord.SelectOption(label="Comandos personalizados", value="customcommands", emoji=f"{Emojis.command}",
                             description="Comandos propios del servidor"),
        discord.SelectOption(label="Lista de staff", value="Staff List", emoji=f"{Emojis.staff_list}",
                             description="La lista automática del equipo por roles"),
        discord.SelectOption(label="Suspensiones", value="suspensions", emoji=f"{Emojis.suspensions}",
                             description="Suspensiones temporales del staff"),
        discord.SelectOption(label="Sugerencias", value="suggestions", emoji=f"{Emojis.suggestion}",
                             description="Canal y votación de sugerencias públicas"),
        discord.SelectOption(label="Panel del staff (Birb)", value="Staff Database", emoji=f"{Emojis.staff_db}",
                             description="Panel antiguo de Birb; el nuevo es /perfil panel"),
        discord.SelectOption(label="Respuestas automáticas", value="Auto Responder", emoji=f"{Emojis.auto_response}",
                             description="El bot responde a palabras clave"),
        discord.SelectOption(label="Gestión del Staff", value="StaffManagement", emoji="🧑‍🏫",
                             description="Solicitudes de ascenso y seguimiento del staff"),
    ]

    for module in ModuleAddons:
        if Modules.get(module.value, False):
            options.append(module)

    return options


class ConfigCog(commands.Cog):
    def __init__(self, client: commands.Bot) -> None:
        self.client = client

    @commands.hybrid_command(description="Configura LOJI: staff, economía, tickets y demás sistemas")
    @commands.has_guild_permissions(manage_guild=True)
    async def config(self, ctx: commands.Context):
        Config = await self.client.db["Config"].find_one({"_id": ctx.guild.id})
        if (
            not Config
            or "Infraction" not in Config
            or not Config["Infraction"].get("types")
        ):
            if not Config:
                Config = {
                    "_id": ctx.guild.id,
                    "Modules": {},
                    "Infraction": {"types": []},
                }
            if not Config.get("Infraction"):
                Config["Infraction"] = {}
            Config["Infraction"]["types"] = [
                "Activity Notice",
                "Verbal Warning",
                "Warning",
                "Strike",
                "Demotion",
                "Termination",
            ]
            await self.client.config.update_one(
                {"_id": ctx.guild.id}, {"$set": Config}, upsert=True
            )

        options = Options(Config)
        view = discord.ui.View()
        view.add_item(ConfigMenu(options, ctx.author))

        embed = DefaultEmbed(ctx.guild)
        await ctx.send(embed=embed, view=view)

    @config.error
    async def PermsHandler(self, ctx: commands.Context, error):
        if isinstance(error, commands.MissingPermissions):
            await ctx.send(
                f"{Emojis.no} **{ctx.author.display_name}**, necesitas el permiso **Gestionar servidor** para usar `/config`."
            )


async def setup(client: commands.Bot) -> None:
    await client.add_cog(ConfigCog(client))
