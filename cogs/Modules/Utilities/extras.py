from datetime import datetime

import aiohttp
from discord import app_commands
from discord.ext import commands

from core.bot.emojis import *


class Utility(commands.Cog):
    def __init__(self, client: commands.Bot):
        self.client = client
        client.launch_time = datetime.now()
        self.client.help_command = None

    @app_commands.command(name="birb", description="Get silly birb photo")
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def birb(self, interaction: discord.Interaction):
        try:
            async with aiohttp.ClientSession() as session, session.get(
                "https://api.alexflipnote.dev/birb"
            ) as response:
                response.raise_for_status()
                data = await response.json()

            embed = discord.Embed(color=discord.Color.dark_embed())
            embed.set_image(url=data.get("file"))
            await interaction.response.send_message(embed=embed)

        except aiohttp.ClientError as e:
            await interaction.response.send_message(
                f"{Emojis.crisis} {interaction.user.mention}, I couldn't get a birb image for you :c\n**Error:** `{e}`",
            )



async def setup(client: commands.Bot) -> None:
    await client.add_cog(Utility(client))
