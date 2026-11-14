import discord


async def StaffListEmbed(interaction: discord.Interaction, embed: discord.Embed):
    embed.set_author(name=f"{interaction.guild.name}", icon_url=interaction.guild.icon)
    embed.set_thumbnail(url=interaction.guild.icon)
    embed.description = (
        "> La **lista de staff** es un mensaje que el bot actualiza solo cada 30 minutos, con el equipo ordenado por rango. "
        "Se prepara con `/staff list add` y se publica con `/staff list send`."
    )
    return embed
