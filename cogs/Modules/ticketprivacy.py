"""
Claimed tickets become private: only the claimer (plus the ticket's author, the bot and any non-staff
people added to it) can see them. Every overwrite that's changed is saved, so unclaiming puts the
channel back exactly as it was. Server admins always see every channel (Discord's rule).
"""

import logging

import discord
from discord import app_commands
from discord.ext import commands

from core.mail.config import Mail

logger = logging.getLogger(__name__)
TICKETS, PANELS = "Tickets", "Panels"
ACCESS = {"read_messages": True, "send_messages": True, "read_message_history": True}


def IsRole(target) -> bool:
    return hasattr(target, "permissions") and not hasattr(target, "guild_permissions")


def Saved(overwrite: discord.PermissionOverwrite) -> dict:
    Allow, Deny = overwrite.pair()
    return {"allow": Allow.value, "deny": Deny.value}


def Restored(data: dict) -> discord.PermissionOverwrite:
    return discord.PermissionOverwrite.from_pair(discord.Permissions(data["allow"]), discord.Permissions(data["deny"]))


async def CanAddPeople(interaction: discord.Interaction, ticket: dict) -> str | None:
    """
    Who can add/remove people in a ticket. Claimed: the claimer, admins and the high offices.
    Not claimed: any ticket staff. Returns the reason it isn't allowed, or None.
    """
    from cogs.Events.on_ticket import TicketPermissions
    from core.ticket_access import CanForceUnclaim

    Config = await Mail().Get(interaction.guild.id)
    if CanForceUnclaim(interaction.user, Config):
        return None
    Claimer = (ticket.get("claimed") or {}).get("claimer")
    if Claimer:
        return None if Claimer == interaction.user.id else f"Este ticket lo atiende <@{Claimer}>: solo esa persona o un admin pueden añadir gente."
    return None if await TicketPermissions(interaction) else "Solo el staff puede añadir gente a un ticket."


class TicketPrivacy(commands.Cog):
    admin = app_commands.Group(name="admin", description="Herramientas de administración", guild_only=True)

    def __init__(self, client: commands.Bot):
        self.client = client

    async def ClaimedTickets(self, guild_id: int) -> list[dict]:
        return await self.client.db[TICKETS].find(
            {"GuildID": guild_id, "closed": None, "claimed.claimer": {"$ne": None}}
        ).to_list(length=None)

    async def TicketChoices(self, interaction: discord.Interaction, current: str):
        Out = []
        for T in await self.ClaimedTickets(interaction.guild.id):
            Channel = interaction.guild.get_channel(T.get("ChannelID") or 0)
            if not Channel:
                continue
            Claimer = interaction.guild.get_member(T["claimed"]["claimer"])
            Label = f"#{Channel.name} · reclamado por {Claimer.display_name if Claimer else T['claimed']['claimer']}"
            if current.lower() in Label.lower():
                Out.append(app_commands.Choice(name=Label[:100], value=str(Channel.id)))
        return Out[:25]

    @admin.command(name="unclaim", description="Quita a la fuerza la reclamación de un ticket (admins y altos cargos)")
    @app_commands.describe(ticket="El ticket reclamado (si lo dejas vacío, el canal donde estás)")
    async def force_unclaim(self, interaction: discord.Interaction, ticket: str | None = None):
        from core.ticket_access import CanForceUnclaim

        Config = await Mail().Get(interaction.guild.id)
        if not CanForceUnclaim(interaction.user, Config):
            return await interaction.response.send_message(
                "❌ Solo administradores, Tenno, Consejo Supremo y Director de Moderación.", ephemeral=True
            )
        ChannelId = int(ticket) if ticket and ticket.isdigit() else interaction.channel.id
        Doc = await self.client.db[TICKETS].find_one({"GuildID": interaction.guild.id, "ChannelID": ChannelId, "closed": None})
        if not Doc:
            return await interaction.response.send_message("❌ Ese no es un ticket abierto. Elige uno de la lista.", ephemeral=True)
        Claimer = (Doc.get("claimed") or {}).get("claimer")
        if not Claimer:
            return await interaction.response.send_message(f"Ese ticket (<#{ChannelId}>) no está reclamado.", ephemeral=True)
        await self.client.db[TICKETS].update_one({"_id": Doc["_id"]}, {"$set": {"claimed": {"claimer": None, "claimedAt": None}}})
        # Same as a normal unclaim: the team sees it again, the button comes back and the name goes back.
        self.client.dispatch("unclaim", Doc["_id"])
        Channel = interaction.guild.get_channel(ChannelId)
        if Channel:
            try:
                await Channel.send(
                    f"🔓 {interaction.user.mention} quitó la reclamación de <@{Claimer}>. El ticket vuelve a estar libre para el equipo.",
                    allowed_mentions=discord.AllowedMentions(users=[discord.Object(Claimer)]),
                )
            except discord.HTTPException:
                pass
        await interaction.response.send_message(f"✅ <#{ChannelId}> ya no está reclamado por <@{Claimer}>.", ephemeral=True)

    @app_commands.command(name="add", description="Añade a alguien al ticket (quien lo reclamó o un admin)")
    @app_commands.describe(usuario="A quién añades al ticket")
    @app_commands.guild_only()
    async def add_user(self, interaction: discord.Interaction, usuario: discord.Member):
        Ticket = await self.client.db[TICKETS].find_one({"ChannelID": interaction.channel.id, "closed": None})
        if not Ticket:
            return await interaction.response.send_message("❌ Usa `/add` dentro del ticket.", ephemeral=True)
        Problem = await CanAddPeople(interaction, Ticket)
        if Problem:
            return await interaction.response.send_message(f"❌ {Problem}", ephemeral=True)
        if usuario.bot:
            return await interaction.response.send_message("❌ No se pueden añadir bots.", ephemeral=True)
        try:
            await interaction.channel.set_permissions(
                usuario, read_messages=True, send_messages=True, read_message_history=True, attach_files=True,
                embed_links=True, add_reactions=True, reason=f"Añadido al ticket por {interaction.user}",
            )
        except discord.HTTPException:
            return await interaction.response.send_message("❌ No tengo permiso para cambiar los permisos de este canal.", ephemeral=True)
        await self.client.db[TICKETS].update_one({"_id": Ticket["_id"]}, {"$addToSet": {"added": usuario.id}})
        await interaction.response.send_message(
            f"➕ {interaction.user.mention} añadió a {usuario.mention} al ticket.",
            allowed_mentions=discord.AllowedMentions(users=[usuario]),
        )

    @force_unclaim.autocomplete("ticket")
    async def force_unclaim_ticket(self, interaction: discord.Interaction, current: str):
        return await self.TicketChoices(interaction, current)

    async def StaffRoles(self, ticket: dict) -> set[int]:
        Panel = await self.client.db[PANELS].find_one({"name": ticket.get("panel"), "type": "single", "guild": ticket.get("GuildID")}) or {}
        return {int(R) for R in Panel.get("permissions", []) if str(R).isdigit()}

    @commands.Cog.listener()
    async def on_ticket_claimed(self, channel, member: discord.Member):
        """Claim (button, command or transfer): only the claimer keeps access."""
        if not (await Mail().Get(channel.guild.id)).get("ticket_private_claim", True):
            return
        Ticket = await self.client.db[TICKETS].find_one({"ChannelID": channel.id})
        if not Ticket:
            return
        Guild = channel.guild
        Author = int(Ticket.get("UserID") or 0)
        Bot = getattr(Guild.me, "id", None)
        Keep = {member.id, Author, Bot}
        Store = dict(Ticket.get("saved_overwrites") or {})
        Claimers = set(Ticket.get("claimers") or [])  # their current overwrite is ours, not an original to restore
        StaffRoles = await self.StaffRoles(Ticket) | {int(K) for K, V in Store.items() if V.get("role")}
        try:
            for Target, Overwrite in list(channel.overwrites.items()):
                if Target == Guild.default_role or Target.id in Keep:
                    continue
                if IsRole(Target):
                    if Overwrite.read_messages is False:
                        continue
                    StaffRoles.add(Target.id)
                elif not any(R.id in StaffRoles for R in getattr(Target, "roles", [])):
                    continue  # someone added to the ticket who isn't staff: they keep it
                if Target.id not in Claimers:
                    Store.setdefault(str(Target.id), {**Saved(Overwrite), "role": IsRole(Target)})
                await channel.set_permissions(Target, read_messages=False, reason="Ticket reclamado: solo lo ve quien lo atiende")
            Previous = Guild.get_member(Ticket.get("private_claimer") or 0)
            if Previous and Previous.id not in Keep:  # transferred: the old claimer loses it too
                await channel.set_permissions(Previous, read_messages=False, reason="Ticket transferido")
            Mine = channel.overwrites.get(member)
            if Mine is not None and member.id not in Claimers:
                Store.setdefault(str(member.id), {**Saved(Mine), "role": False})
            await channel.set_permissions(member, **ACCESS, reason="Ticket reclamado")
        except discord.HTTPException as e:
            return logger.warning(f"[Tickets] Couldn't make ticket {channel.id} private: {e}")
        await self.client.db[TICKETS].update_one(
            {"_id": Ticket["_id"]}, {"$set": {"private_claimer": member.id, "saved_overwrites": Store}, "$addToSet": {"claimers": member.id}}
        )

    @commands.Cog.listener()
    async def on_unclaim(self, objectID):
        """Unclaimed: every overwrite goes back to how it was before the claim."""
        Ticket = await self.client.db[TICKETS].find_one({"_id": objectID})
        if not Ticket or "private_claimer" not in Ticket:
            return
        Channel = self.client.get_channel(Ticket.get("ChannelID") or 0)
        if not Channel:
            return
        Guild = Channel.guild
        Store = Ticket.get("saved_overwrites") or {}
        try:
            for TargetId, Data in Store.items():
                Target = Guild.get_role(int(TargetId)) if Data.get("role") else Guild.get_member(int(TargetId))
                if Target:
                    await Channel.set_permissions(Target, overwrite=Restored(Data), reason="Ticket liberado")
            for UserId in set(Ticket.get("claimers") or []) | {Ticket.get("private_claimer")}:  # everyone who claimed it
                Claimer = Guild.get_member(UserId or 0)
                if Claimer and str(Claimer.id) not in Store and Claimer.id != int(Ticket.get("UserID") or 0):
                    await Channel.set_permissions(Claimer, overwrite=None, reason="Ticket liberado")
        except discord.HTTPException as e:
            return logger.warning(f"[Tickets] Couldn't reopen ticket {Channel.id} to the team: {e}")
        await self.client.db[TICKETS].update_one({"_id": Ticket["_id"]}, {"$unset": {"saved_overwrites": "", "private_claimer": "", "claimers": "", "hidden_roles": ""}})


async def setup(client: commands.Bot) -> None:
    await client.add_cog(TicketPrivacy(client))
