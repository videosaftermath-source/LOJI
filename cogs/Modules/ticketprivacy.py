"""Claimed tickets become private: the panel's staff roles stop seeing them until it's unclaimed."""

import logging

import discord
from discord.ext import commands

from core.mail.config import Mail

logger = logging.getLogger(__name__)
TICKETS, PANELS = "Tickets", "Panels"
ACCESS = {"read_messages": True, "send_messages": True, "read_message_history": True}


class TicketPrivacy(commands.Cog):
    def __init__(self, client: commands.Bot):
        self.client = client

    async def Panel(self, ticket: dict) -> dict:
        return await self.client.db[PANELS].find_one({"name": ticket.get("panel"), "type": "single", "guild": ticket.get("GuildID")}) or {}

    @commands.Cog.listener()
    async def on_ticket_claimed(self, channel: discord.TextChannel, member: discord.Member):
        """Claim (button, command or transfer): hide it from the panel's roles, keep it for the claimer."""
        if not (await Mail().Get(channel.guild.id)).get("ticket_private_claim", True):
            return
        Ticket = await self.client.db[TICKETS].find_one({"ChannelID": channel.id})
        if not Ticket:
            return
        Roles = [channel.guild.get_role(R) for R in (await self.Panel(Ticket)).get("permissions", [])]
        Hidden = []
        try:
            await channel.set_permissions(member, **ACCESS, reason="Ticket reclamado")
            Previous = channel.guild.get_member(Ticket.get("private_claimer") or 0)
            if Previous and Previous.id != member.id and Previous.id != int(Ticket.get("UserID") or 0):
                await channel.set_permissions(Previous, overwrite=None, reason="Ticket transferido")
            for Role in Roles:
                if Role and Role in channel.overwrites:
                    await channel.set_permissions(Role, read_messages=False, reason="Ticket reclamado: solo lo ve quien lo atiende")
                    Hidden.append(Role.id)
        except discord.HTTPException as e:
            return logger.warning(f"[Tickets] Couldn't make ticket {channel.id} private: {e}")
        await self.client.db[TICKETS].update_one(
            {"_id": Ticket["_id"]},
            {"$set": {"private_claimer": member.id}, "$addToSet": {"hidden_roles": {"$each": Hidden}}},
        )

    @commands.Cog.listener()
    async def on_unclaim(self, objectID):
        """Unclaimed: the panel's roles see it again."""
        Ticket = await self.client.db[TICKETS].find_one({"_id": objectID})
        if not Ticket or not Ticket.get("hidden_roles"):
            return
        Channel = self.client.get_channel(Ticket.get("ChannelID") or 0)
        if not Channel:
            return
        try:
            for RoleId in Ticket["hidden_roles"]:
                Role = Channel.guild.get_role(RoleId)
                if Role:
                    await Channel.set_permissions(Role, **ACCESS, reason="Ticket liberado")
            Claimer = Channel.guild.get_member(Ticket.get("private_claimer") or 0)
            if Claimer and Claimer.id != int(Ticket.get("UserID") or 0):
                await Channel.set_permissions(Claimer, overwrite=None, reason="Ticket liberado")
        except discord.HTTPException as e:
            return logger.warning(f"[Tickets] Couldn't reopen ticket {Channel.id} to the team: {e}")
        await self.client.db[TICKETS].update_one({"_id": Ticket["_id"]}, {"$unset": {"hidden_roles": "", "private_claimer": ""}})


async def setup(client: commands.Bot) -> None:
    await client.add_cog(TicketPrivacy(client))
