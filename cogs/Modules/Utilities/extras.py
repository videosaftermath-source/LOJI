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

    # /birb (a random bird photo) was Birb's; this cog now only sets the launch time and help command.


async def setup(client: commands.Bot) -> None:
    await client.add_cog(Utility(client))
