import discord

from core.bot.HelpEmbeds import NotYourPanel
from core.bot.emojis import Emojis


class StaffManagementOptions(discord.ui.Select):
    def __init__(self, author: discord.Member):
        super().__init__(
            placeholder="Gestión del Staff",
            options=[
                discord.SelectOption(
                    label="Rol de cuidador",
                    value="caretakers",
                    description="Quién puede ver perfiles, comentar y pedir ascensos.",
                    emoji="🧑‍🏫",
                ),
                discord.SelectOption(
                    label="Rol de alto mando",
                    value="approvers",
                    description="Quién aprueba o deniega ascensos (los admins siempre pueden).",
                    emoji="👑",
                ),
                discord.SelectOption(
                    label="Canal de solicitudes",
                    value="channel",
                    description="Dónde llegan las solicitudes de ascenso.",
                    emoji="📢",
                ),
            ],
        )
        self.author = author

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.author.id:
            return await interaction.response.send_message(
                embed=NotYourPanel(), ephemeral=True
            )
        Config = await interaction.client.config.find_one({"_id": interaction.guild.id}) or {}
        Settings = Config.get("StaffManagement", {})
        option = self.values[0]
        view = discord.ui.View()
        if option == "channel":
            Channel = interaction.guild.get_channel(Settings.get("channel") or 0)
            view.add_item(SettingChannel(self.author, Channel, interaction.message))
        else:
            Roles = [
                role
                for role in (
                    interaction.guild.get_role(r) for r in Settings.get(option, [])
                )
                if role
            ]
            view.add_item(SettingRoles(self.author, option, Roles, interaction.message))
        await interaction.response.send_message(view=view, ephemeral=True)


async def SaveSetting(interaction: discord.Interaction, key: str, value, message):
    await interaction.client.config.update_one(
        {"_id": interaction.guild.id},
        {"$set": {f"StaffManagement.{key}": value}},
        upsert=True,
    )
    await interaction.response.edit_message(content=f"{Emojis.tick} Guardado.")
    Updated = await interaction.client.config.find_one({"_id": interaction.guild.id})
    try:
        await message.edit(
            embed=await StaffManagementEmbed(
                interaction, Updated, discord.Embed(color=discord.Color.dark_embed())
            )
        )
    except (discord.HTTPException, AttributeError):
        pass


class SettingRoles(discord.ui.RoleSelect):
    def __init__(self, author, key: str, roles: list, message: discord.Message):
        super().__init__(
            min_values=0,
            max_values=10,
            default_values=roles,
            placeholder="Elige los roles",
        )
        self.author = author
        self.key = key
        self.message = message

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.author.id:
            return await interaction.response.send_message(
                embed=NotYourPanel(), ephemeral=True
            )
        await SaveSetting(
            interaction, self.key, [role.id for role in self.values], self.message
        )


class SettingChannel(discord.ui.ChannelSelect):
    def __init__(self, author, channel, message: discord.Message):
        super().__init__(
            min_values=0,
            max_values=1,
            default_values=[channel] if channel else [],
            channel_types=[discord.ChannelType.text, discord.ChannelType.news],
            placeholder="Elige el canal",
        )
        self.author = author
        self.message = message

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.author.id:
            return await interaction.response.send_message(
                embed=NotYourPanel(), ephemeral=True
            )
        await SaveSetting(
            interaction,
            "channel",
            self.values[0].id if self.values else None,
            self.message,
        )


async def StaffManagementEmbed(
    interaction: discord.Interaction, config: dict, embed: discord.Embed
):
    Settings = (config or {}).get("StaffManagement", {})

    def Roles(key):
        Mentions = [f"<@&{r}>" for r in Settings.get(key, [])]
        return ", ".join(Mentions) if Mentions else "No configurado"

    Channel = interaction.guild.get_channel(Settings.get("channel") or 0)

    embed.set_author(name=f"{interaction.guild.name}", icon_url=interaction.guild.icon)
    embed.set_thumbnail(url=interaction.guild.icon)
    embed.description = (
        "> Los **cuidadores** pueden abrir el perfil de un miembro del staff con "
        "`/gestion perfil`, sumarle sanciones, dejar comentarios y **solicitar su ascenso**. "
        "Las solicitudes llegan al canal configurado, donde el **alto mando** las aprueba o deniega.\n"
        "> -# Si el módulo de Promociones está configurado, los ascensos aprobados se registran ahí también."
    )
    embed.add_field(
        name="⚙️ Gestión del Staff",
        value=(
            f"> `Cuidadores:` {Roles('caretakers')}\n"
            f"> `Alto mando:` {Roles('approvers')} (+ administradores)\n"
            f"> `Canal de solicitudes:` {Channel.mention if Channel else 'No configurado'}"
        ),
        inline=False,
    )
    return embed
