"""Ticket anti-AFK: reminds idle users every 6 h; warns an idle claimer twice (30 min apart) and then frees the ticket."""

import logging
import time
from datetime import datetime, timezone

import discord
from discord.ext import commands, tasks

from core.mail.config import Mail
from core.ticket_afk import Decide, OnMessage

logger = logging.getLogger(__name__)
TICKETS = "Tickets"
CACHE_SECONDS = 300
CHECK_MINUTES = 5


def Now() -> datetime:
    return datetime.now(timezone.utc)


class TicketAfk(commands.Cog):
    def __init__(self, client: commands.Bot):
        self.client = client
        self.channels: dict[int, tuple[float, bool]] = {}  # channel -> (expires, is an open ticket)
        self.Check.start()

    def cog_unload(self):
        self.Check.cancel()

    async def IsTicket(self, channel_id: int) -> dict | None:
        Cached = self.channels.get(channel_id)
        if Cached and Cached[0] > time.monotonic() and not Cached[1]:
            return None  # known not to be a ticket: no database call
        Doc = await self.client.db[TICKETS].find_one({"ChannelID": channel_id, "closed": None})
        self.channels[channel_id] = (time.monotonic() + CACHE_SECONDS, bool(Doc))
        return Doc

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not message.guild or message.author.bot:
            return
        Ticket = await self.IsTicket(message.channel.id)
        if not Ticket:
            return
        Changes = OnMessage(Ticket, message.author.id, message.author.bot, Now())
        if Changes:
            await self.client.db[TICKETS].update_one({"_id": Ticket["_id"]}, {"$set": Changes})

    @commands.Cog.listener()
    async def on_ticket_claimed(self, channel, member: discord.Member):
        Ticket = await self.client.db[TICKETS].find_one({"ChannelID": channel.id, "closed": None})
        if not Ticket:
            return
        Afk = Ticket.get("afk") or {}
        Changes = {"afk.claimed_at": Now(), "afk.warnings": 0}
        # Nobody from staff has answered yet: the user who opened it is waiting.
        if not Afk.get("pending_since") and not Afk.get("staff_last"):
            Changes["afk.pending_since"] = Now()
        await self.client.db[TICKETS].update_one({"_id": Ticket["_id"]}, {"$set": Changes})

    @tasks.loop(minutes=CHECK_MINUTES)
    async def Check(self):
        try:
            Tickets = await self.client.db[TICKETS].find({"closed": None, "ChannelID": {"$ne": None}}).to_list(length=None)
            Enabled: dict[int, bool] = {}
            for T in Tickets:
                Guild = self.client.get_guild(T.get("GuildID") or 0)
                Channel = Guild.get_channel(T.get("ChannelID") or 0) if Guild else None
                if not Channel:
                    continue
                if Guild.id not in Enabled:
                    Enabled[Guild.id] = (await Mail().Get(Guild.id)).get("ticket_afk", True)
                if not Enabled[Guild.id]:
                    continue
                Action = Decide(T, Now())
                if Action:
                    try:
                        await self.Act(Action, T, Guild, Channel)
                    except Exception as e:
                        logger.warning(f"[TicketAfk] {Action} failed on {Channel.id}: {e!r}")
        except Exception as e:
            logger.exception(f"[TicketAfk] Check failed: {e!r}")

    @Check.before_loop
    async def BeforeCheck(self):
        await self.client.wait_until_ready()

    async def Act(self, action: str, ticket: dict, guild: discord.Guild, channel):
        User, Claimer = ticket.get("UserID"), (ticket.get("claimed") or {}).get("claimer")
        Col = self.client.db[TICKETS]
        if action == "remind_user":
            await Col.update_one({"_id": ticket["_id"]}, {"$set": {"afk.reminded_at": Now()}})
            await channel.send(
                f"<@{User}> ⏰ Tu ticket sigue abierto y el staff está esperando tu respuesta. "
                "Si ya está todo resuelto, avísanos para cerrarlo.",
                allowed_mentions=discord.AllowedMentions(users=True),
            )
        elif action == "warn":
            # Only if nothing changed meanwhile (a reply between the read and now wins).
            Done = await Col.update_one({"_id": ticket["_id"], "afk.warnings": {"$in": [0, None]}, "afk.pending_since": {"$ne": None}}, {"$set": {"afk.warnings": 1}})
            if Done.modified_count:
                await channel.send(
                    f"<@{Claimer}> ⚠️ **Aviso 1/2:** <@{User}> lleva 30 minutos esperando tu respuesta. "
                    "Si no respondes en otros 30 minutos, el ticket se libera para el resto del equipo.",
                    allowed_mentions=discord.AllowedMentions(users=[discord.Object(Claimer)]),
                )
        elif action == "abandon":
            Done = await Col.update_one(
                {"_id": ticket["_id"], "claimed.claimer": Claimer, "afk.pending_since": {"$ne": None}},
                {"$set": {"claimed": {"claimer": None, "claimedAt": None}, "afk.warnings": 0, "afk.claimed_at": None},
                 "$push": {"abandoned": {"by": Claimer, "at": Now()}}},
            )
            if not Done.modified_count:
                return
            self.client.dispatch("unclaim", ticket["_id"])  # the team sees it again, buttons and name go back
            await channel.send(
                f"🚨 **Aviso 2/2:** <@{Claimer}> no respondió en 1 hora. El ticket queda **libre**: cualquiera del equipo puede reclamarlo. "
                f"<@{User}>, enseguida te atiende otra persona.",
                allowed_mentions=discord.AllowedMentions(users=[discord.Object(User)]),
            )
            await self.Report(guild, channel, ticket, Claimer)

    async def Report(self, guild: discord.Guild, channel, ticket: dict, claimer: int):
        from cogs.Modules.feedback import FeedbackChannel

        Target = await FeedbackChannel(self.client, guild)
        if not Target:
            return logger.warning(f"[TicketAfk] No feedback channel in {guild.id} to report the abandoned ticket.")
        embed = discord.Embed(
            title="🚨 Ticket abandonado",
            description=f"<@{claimer}> reclamó {channel.mention} (`#{channel.name}`) y dejó al usuario sin respuesta durante 1 hora. "
            "El ticket se liberó para el resto del equipo.",
            color=discord.Color.red(),
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(name="Moderador", value=f"<@{claimer}>", inline=True)
        embed.add_field(name="Usuario", value=f"<@{ticket.get('UserID')}>", inline=True)
        embed.add_field(name="Panel", value=ticket.get("panel") or "—", inline=True)
        Times = len(ticket.get("abandoned") or []) + 1
        if Times > 1:
            embed.set_footer(text=f"Es la {Times}.ª vez que se abandona este ticket")
        try:
            await Target.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException as e:
            logger.warning(f"[TicketAfk] Couldn't report to the feedback channel: {e}")


async def setup(client: commands.Bot) -> None:
    await client.add_cog(TicketAfk(client))
