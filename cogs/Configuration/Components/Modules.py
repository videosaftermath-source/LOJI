import discord

from core.bot.HelpEmbeds import NotYourPanel
from core.bot.emojis import Emojis


async def ModuleOptions(Config, data=None):
    if not Config:
        Config = {"Modules": {}}
    return [
        discord.SelectOption(
            label="Sanciones",
            description="",
            emoji=f"{Emojis.infractions}",
            value="infractions",
            default=(
                Config.get("Modules", {}).get("infractions", False) or False
                if not data
                else False
            ),
        ),
        discord.SelectOption(
            label="Ascensos",
            description="",
            emoji=f"{Emojis.promotions}",
            value="promotions",
            default=(
                Config.get("Modules", {}).get("promotions", False) or False
                if not data
                else False
            ),
        ),
        discord.SelectOption(
            label="Cuota de mensajes",
            description="",
            value="Quota",
            emoji=f"{Emojis.message_quota}",
            default=(
                Config.get("Modules", {}).get("Quota", False) or False
                if not data
                else False
            ),
        ),
        discord.SelectOption(
            label="Ausencias (LOA)",
            description="",
            value="LOA",
            emoji=f"{Emojis.loa}",
            default=(
                Config.get("Modules", {}).get("LOA", False) or False
                if not data
                else False
            ),
        ),
        discord.SelectOption(
            label="Suspensiones",
            description="",
            value="suspensions",
            emoji=f"{Emojis.suspensions}",
            default=(
                Config.get("Modules", {}).get("suspensions", False) or False
                if not data
                else False
            ),
        ),
        discord.SelectOption(
            label="Sugerencias",
            description="",
            value="suggestions",
            emoji=f"{Emojis.suggestion}",
            default=(
                Config.get("Modules", {}).get("suggestions", False) or False
                if not data
                else False
            ),
        ),
        discord.SelectOption(
            label="Tickets",
            description="",
            value="Tickets",
            emoji=f"{Emojis.message_received}",
            default=(
                Config.get("Modules", {}).get("Tickets", False) or False
                if not data
                else False
            ),
        ),
        discord.SelectOption(
            label="Comandos personalizados",
            description="",
            value="customcommands",
            emoji=f"{Emojis.command}",
            default=(
                Config.get("Modules", {}).get("customcommands", False) or False
                if not data
                else False
            ),
        ),
        discord.SelectOption(
            label="Lista de staff",
            description="",
            value="Staff List",
            emoji=f"{Emojis.staff_list}",
            default=(
                Config.get("Modules", {}).get("Staff List", False) or False
                if not data
                else False
            ),
        ),
        discord.SelectOption(
            label="Panel del staff (Birb)",
            description="",
            value="Staff Database",
            emoji=f"{Emojis.staff_db}",
            default=(
                Config.get("Modules", {}).get("Staff Database", False) or False
                if not data
                else False
            ),
        ),
        discord.SelectOption(
            label="Respuestas automáticas",
            value="Auto Responder",
            emoji=f"{Emojis.auto_response}",
            default=(
                Config.get("Modules", {}).get("Auto Responder", False) or False
                if not data
                else False
            ),
        ),
        discord.SelectOption(
            label="Gestión del Staff",
            value="StaffManagement",
            emoji="🧑‍🏫",
            default=(
                Config.get("Modules", {}).get("StaffManagement", False) or False
                if not data
                else False
            ),
        ),
        discord.SelectOption(
            label="Economía",
            value="Economy",
            emoji="🪙",
            default=(
                Config.get("Modules", {}).get("Economy", False) or False
                if not data
                else False
            ),
        ),
    ]


class ModuleToggle(discord.ui.Select):
    def __init__(self, author, options: list):
        self.author = author
        super().__init__(
            placeholder="Elige los módulos que quieres activados",
            options=options,
            min_values=0,
            required=False,
            max_values=len(options),
        )

    async def callback(self, interaction: discord.Interaction):
        from cogs.Configuration.Configuration import ConfigMenu
        from cogs.Configuration.Configuration import Options

        Selected = self.values
        if interaction.user.id != self.author.id:
            return await interaction.response.send_message(
                embed=NotYourPanel(), ephemeral=True
            )

        await interaction.response.defer(ephemeral=True)

        config = await interaction.client.config.find_one({"_id": interaction.guild.id})
        if not config:
            config = {"_id": interaction.guild.id, "Modules": {}}
        elif "Modules" not in config:
            config["Modules"] = {}

        for module in config["Modules"]:
            config["Modules"][module] = False

        for module in Selected:
            config["Modules"][module] = True

        if "Modmail" in Selected and not interaction.guild.chunked:
            await interaction.guild.chunk()

        if "promotions" in Selected:
            from cogs.Modules.promotions import SyncServer

            try:
                await SyncServer(interaction.client, interaction.guild)
            except:
                pass

        await interaction.client.config.update_one(
            {"_id": interaction.guild.id}, {"$set": config}, upsert=True
        )
        Updated = await interaction.client.config.find_one(
            {"_id": interaction.guild.id}
        )

        view = discord.ui.View()
        view.add_item(ModuleToggle(interaction.user, await ModuleOptions(Updated)))
        view.add_item(ConfigMenu(Options(Updated), interaction.user))

        await interaction.edit_original_response(view=view)
        await interaction.followup.send(
            embed=discord.Embed(
                title="✅ Módulos guardados",
                description="Los módulos activados ya aparecen en el menú **¿Qué quieres configurar?**. Elige uno para prepararlo.",
                color=discord.Color.brand_green(),
            ),
            ephemeral=True,
        )
