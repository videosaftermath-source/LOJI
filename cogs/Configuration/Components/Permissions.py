from core.bot.HelpEmbeds import NotYourPanel
from core.bot.emojis import *


class PermissionsUpdate(discord.ui.RoleSelect):
    def __init__(
        self, author: discord.Member, type: str, roles: list[discord.Role] = []
    ):
        super().__init__(
            default_values=roles,
            placeholder="Staff Role" if type == "staffrole" else "Admin Role",
            min_values=0,
            max_values=25,
        )
        self.author = author

        self.typed = type
        self.roles = roles

    async def callback(self, interaction):
        from cogs.Configuration.Configuration import ConfigMenu, Options
        from cogs.Configuration.Components.AdvancedPermissions import (
            PermissionsDropdown,
        )

        await interaction.response.defer()
        if interaction.user.id != self.author.id:
            return await interaction.followup.send(embed=NotYourPanel(), ephemeral=True)

        config = await interaction.client.config.find_one({"_id": interaction.guild.id})
        if config is None:
            config = {"_id": interaction.guild.id, "Permissions": {}}
        elif "Permissions" not in config:
            config["Permissions"] = {}
        if self.values:
            config["Permissions"][self.typed] = [role.id for role in self.values]
        else:
            config["Permissions"].pop(self.typed, None)
        await interaction.client.config.update_one(
            {"_id": interaction.guild.id}, {"$set": config}
        )
        Updated = await interaction.client.config.find_one(
            {"_id": interaction.guild.id}
        )
        view = discord.ui.View()
        view.add_item(
            PermissionsUpdate(
                interaction.user,
                "staffrole",
                [
                    role
                    for role in interaction.guild.roles
                    if role.id in Updated.get("Permissions", {}).get("staffrole", [])
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
                    if role.id in Updated.get("Permissions", {}).get("adminrole", [])
                ],
            )
        )
        view.add_item(PermissionsDropdown(interaction.user))
        view.add_item(ConfigMenu(Options(Updated), interaction.user))
        await interaction.edit_original_response(
            view=view,
            embed=await PermissionsEmbed(
                interaction, Updated, discord.Embed(color=discord.Color.dark_embed())
            ),
        )


async def PermissionsEmbed(
    interaction: discord.Interaction, Config: dict, embed: discord.Embed
):
    Config = await interaction.client.config.find_one({"_id": interaction.guild.id})
    if not Config:
        Config = {"Permissions": {}}
    StaffRole = (
        ", ".join(
            f"<@&{int(Role)}>"
            for Role in Config.get("Permissions", {}).get("staffrole") or []
        )
        or "Sin configurar"
    )

    AdminRole = (
        ", ".join(
            f"<@&{int(Role)}>"
            for Role in Config.get("Permissions", {}).get("adminrole") or []
        )
        or "Sin configurar"
    )
    embed.set_author(name=f"{interaction.guild.name}", icon_url=interaction.guild.icon)
    embed.set_thumbnail(url=interaction.guild.icon)
    embed.description = "> Qué roles cuentan como **staff** y como **administración** para los comandos del bot.\n"
    value = f"{Emojis.replytop} `Rol de staff:` {StaffRole} \n{Emojis.replybottom} `Rol de administración:` {AdminRole}"
    if len(value) > 1021:
        value = value[:1018] + "..."

    embed.add_field(
        name=f"{Emojis.permissions} Permisos",
        value=value,
        inline=False,
    )
    return embed
