import asyncio
import logging

import sentry_sdk
from discord.ext import commands
from discord.ext import tasks

from core.bot.Module import ModuleCheck
from core.bot.emojis import *

logger = logging.getLogger(__name__)

environment = os.getenv("ENVIRONMENT")
guildid = os.getenv("CUSTOM_GUILD")


class StaffList(commands.Cog):
    def __init__(self, client: commands.Bot):
        self.client = client
        self.updatelist.start()
        client.Tasks.add("Staff List")

    @tasks.loop(minutes=30, reconnect=True)
    @sentry_sdk.trace()
    async def updatelist(self):
        logger.info("Checking Staff List")
        if environment == "custom":
            activelistresult = (
                await self.client.db["Active Staff List"]
                .find({"guild_id": int(guildid)})
                .to_list(length=None)
            )
        else:
            activelistresult = (
                await self.client.db["Active Staff List"].find({}).to_list(length=None)
            )

        if not activelistresult:
            return
        semaphore = asyncio.Semaphore(5)

        async def process(data):
            async with semaphore:
                await self.UpdateList(data)

        await asyncio.gather(*(process(data) for data in activelistresult))
        del activelistresult

    @sentry_sdk.trace()
    async def UpdateList(self, data):
        try:
            guild = self.client.get_guild(data.get("guild_id"))
            if not guild:
                return
            if not await ModuleCheck(guild.id, "Staff List"):
                return

            from core.staff.stafflist import DEFAULT_TITLE, MAIN, Clean, Embed, Filter

            Name = Clean(data.get("list"))
            results = await self.client.db["Staff List"].find(Filter(guild.id, Name)).to_list(length=None)
            if not results:
                return
            if not guild.chunked:
                await guild.chunk()
            embed = Embed(guild, results, data.get("title") or (DEFAULT_TITLE if Name == MAIN else Name.title()))
            ChannelID = data.get("channel_id")
            MessageId = data.get("msg")

            if ChannelID and MessageId:
                try:
                    channel = await self.client.fetch_channel(ChannelID)
                    msg = await channel.fetch_message(MessageId)
                    if msg:
                        await msg.edit(embed=embed)
                except (discord.HTTPException, discord.NotFound):
                    return
        except Exception as e:
            logger.error(f"[ERROR] {e}")

    @updatelist.before_loop
    async def before_updatelist(self):
        await self.client.wait_until_ready()


async def setup(client):
    await client.add_cog(StaffList(client))
