import io
import logging
import time

import discord
from discord.ext import commands

from core.bot.Module import ModuleCheck
from core.bot.permissions import RequireStaff
from core.quota_spam import Fill, Settings, Tracker

logger = logging.getLogger(__name__)
BANNERS = "quota_spam_banner"  # a saved copy of the level 2 banner (Discord attachment links expire)
L1_DELETE_AFTER = 15


class MessageCounter(commands.Cog):
    def __init__(self, client):
        self.client = client
        self.spam = Tracker()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.guild is None:
            return
        if message.author.bot:
            return
        if message.author is None:
            return
        if message.channel is None:
            return
        config = await self.client.db["Config"].find_one({"_id": message.guild.id})
        if not config:
            return
        if not config.get("Permissions"):
            return
        if message.author and message.channel is None:
            return
        if message.author.bot:
            return
        if not await ModuleCheck(message.guild.id, "Quota"):
            return

        if not RequireStaff(config, message.author):
            return

        if message.channel.id in config.get("Message Quota", {}).get(
            "Ignored Channels", []
        ):
            return

        # LOJI: anti-spam (/config → Quota → Anti-spam). Writing fast or spamming doesn't fill the quota.
        S = Settings(config)
        Count, Level, Back = True, 0, 0
        if S["enabled"]:
            Count, Level, Back = self.spam.Check((message.guild.id, message.author.id), time.monotonic(), S)

        Col = self.client.db["messages"]
        Key = {"guild_id": message.guild.id, "user_id": message.author.id}
        if Count:
            await Col.update_one(Key, {"$inc": {"message_count": 1}}, upsert=True)
        if Back:
            # Never below zero (the quota could have been reset in between).
            await Col.update_one(Key, [{"$set": {"message_count": {"$max": [0, {"$subtract": [{"$ifNull": ["$message_count", 0]}, Back]}]}}}])
        if Level:
            try:
                await self.Alert(message, S, Level, Back)
            except Exception as e:
                logger.warning(f"[Quota] Anti-spam alert failed: {e!r}")

    async def Alert(self, message: discord.Message, s: dict, level: int, back: int):
        Values = {"user": message.author.mention, "nombre": message.author.display_name, "aviso": NotifyMention(s),
                  "cantidad": s["l2_count"], "canal": message.channel.mention}
        if level == 1:
            try:
                await message.channel.send(
                    Fill(s["l1_text"], Values), delete_after=L1_DELETE_AFTER,
                    allowed_mentions=discord.AllowedMentions(users=[message.author]),
                )
            except discord.HTTPException:
                pass
        else:
            Embed, File = await StaringEmbed(self.client.db, message.guild.id, s, Values)
            Pings = discord.AllowedMentions(users=True, roles=True, everyone=False)
            try:
                Kwargs = {"file": File} if File else {}
                await message.channel.send(content=Values["user"] + (f" {Values['aviso']}" if s.get("notify") else ""), embed=Embed, allowed_mentions=Pings, **Kwargs)
            except discord.HTTPException as e:
                logger.warning(f"[Quota] Couldn't post the level 2 warning: {e}")
        await self.Log(message, s, level, back)

    async def Log(self, message: discord.Message, s: dict, level: int, back: int):
        Channel = message.guild.get_channel(s.get("alert_channel") or 0)
        if not Channel:
            return
        Embed = discord.Embed(
            title=f"{'⚠️' if level == 1 else '🚨'} Anti-spam de cuota · Nivel {level}",
            color=discord.Color.orange() if level == 1 else discord.Color.red(),
            timestamp=discord.utils.utcnow(),
        )
        Embed.add_field(name="Staff", value=f"{message.author.mention} (`{message.author.id}`)", inline=True)
        Embed.add_field(name="Canal", value=f"{message.channel.mention}\n[Ir al mensaje]({message.jump_url})", inline=True)
        if level == 1:
            Embed.description = f"Más de **{s['l1_count']}** mensajes en **{s['l1_seconds']} s**. Los que sobran no cuentan (puede ser solo escribir rápido)."
        else:
            Embed.description = (
                f"**{s['l2_count']}** mensajes en **{s['l2_seconds'] // 60 or 1} min**: spam. Se descontaron **{back}** de su cuota "
                f"y no le cuenta nada durante **{s['pause_minutes']} min**."
            )
        try:
            await Channel.send(embed=Embed, allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException as e:
            logger.warning(f"[Quota] Couldn't log the anti-spam alert: {e}")


def NotifyMention(s: dict) -> str:
    Who = s.get("notify") or {}
    if not Who.get("id"):
        return "la administración"
    return f"<@&{Who['id']}>" if Who.get("type") == "role" else f"<@{Who['id']}>"


async def StaringEmbed(db, guild_id: int, s: dict, values: dict) -> tuple[discord.Embed, discord.File | None]:
    """The level 2 warning: LOJI's angry banner (from the saved copy) and the stern text."""
    Embed = discord.Embed(title=Fill(s["l2_title"], values)[:256], description=Fill(s["l2_text"], values)[:4000], color=discord.Color.from_rgb(150, 12, 18))
    File = None
    Saved = await db[BANNERS].find_one({"_id": guild_id})
    if Saved and Saved.get("data"):
        Name = Saved.get("filename") or "loji.png"
        File = discord.File(io.BytesIO(bytes(Saved["data"])), filename=Name)
        Embed.set_image(url=f"attachment://{Name}")
    elif s.get("banner_url"):
        Embed.set_image(url=s["banner_url"])
    return Embed, File


async def setup(client: commands.Bot) -> None:
    await client.add_cog(MessageCounter(client))
