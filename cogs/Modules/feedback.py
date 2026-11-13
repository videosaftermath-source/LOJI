"""
/feedback (LOJI): rate a staff member 1-10 with an optional comment, see someone's ratings, remove one.
Also the "⭐ Dejar feedback" button in the DM sent when a ticket closes.

Replaces Birb's feedback module. Staff = the Mando Central's staff role, profile roles or high offices.
Ratings go to the staff profile (/perfil) and, if set, to the feedback channel (/config → Mando Central).
"""

import logging
from datetime import datetime, timezone

import discord
from bson import ObjectId
from discord import app_commands
from discord.ext import commands

from core.mail.config import Mail
from core.staff.feedback import COMMENT_MAX, LABELS, Feedback, FeedbackError, IsStaff, Stars, Summary

logger = logging.getLogger(__name__)
GOLD = discord.Color.from_rgb(241, 196, 15)
_store: Feedback | None = None


def Store() -> Feedback:
    global _store
    if _store is None:
        from core.db import db

        _store = Feedback(db)
    return _store


async def FeedbackChannel(client, guild: discord.Guild):
    """The Mando Central's feedback channel, or Birb's old one if that's all there is."""
    Config = await Mail().Get(guild.id)
    ChannelId = Config.get("feedback_channel")
    if not ChannelId:
        Old = await client.config.find_one({"_id": guild.id}) or {}
        ChannelId = (Old.get("Feedback") or {}).get("channel")
    try:
        return guild.get_channel(int(ChannelId or 0))
    except (TypeError, ValueError):
        return None


async def Post(client, guild: discord.Guild, doc: dict):
    Channel = await FeedbackChannel(client, guild)
    if not Channel:
        return
    Staff = guild.get_member(doc["staff"])
    embed = discord.Embed(title="⭐ Nuevo feedback", color=GOLD, timestamp=datetime.fromtimestamp(doc["date"], timezone.utc))
    embed.add_field(name="Staff", value=f"<@{doc['staff']}>", inline=True)
    embed.add_field(name="Nota", value=f"{Stars(doc['rating'])} **{doc['rating']}/10**", inline=True)
    embed.add_field(name="De", value=f"<@{doc['author']}>", inline=True)
    if doc.get("ticket_name"):
        embed.add_field(name="Ticket", value=f"`#{doc['ticket_name']}`", inline=True)
    embed.description = f"> {doc['feedback']}" if doc.get("feedback") else "*Sin comentario.*"
    if Staff:
        embed.set_thumbnail(url=Staff.display_avatar.url)
    embed.set_footer(text=f"Feedback #{doc['feedbackid']}")
    try:
        await Channel.send(content=f"<@{doc['staff']}>", embed=embed, allowed_mentions=discord.AllowedMentions(users=True))
    except discord.HTTPException as e:
        logger.warning(f"[Feedback] Couldn't post: {e}")


async def Save(interaction: discord.Interaction, guild: discord.Guild, staff_id: int, rating: int, comment: str, ticket: dict | None = None):
    try:
        Doc = await Store().Add(
            guild.id, interaction.user.id, staff_id, rating, comment,
            ticket=str(ticket["_id"]) if ticket else None, ticket_name=(ticket or {}).get("name"),
        )
    except FeedbackError as e:
        return await interaction.response.send_message(f"❌ {e}", ephemeral=True)
    await Post(interaction.client, guild, Doc)
    await interaction.response.send_message(
        f"✅ ¡Gracias! Valoraste a <@{staff_id}> con **{rating}/10** {Stars(rating)}. Tu opinión llega a su perfil de staff.",
        ephemeral=True,
    )


# ---------------- choosing the rating ----------------


class CommentModal(discord.ui.Modal, title="Tu feedback"):
    def __init__(self, guild: discord.Guild, staff_id: int, rating: int, ticket: dict | None):
        super().__init__()
        self.guild, self.staff_id, self.rating, self.ticket = guild, staff_id, rating, ticket
        self.comment = discord.ui.TextInput(
            label=f"Comentario (nota {rating}/10)", style=discord.TextStyle.paragraph, required=False, max_length=COMMENT_MAX,
            placeholder="¿Qué hizo bien? ¿Qué podría mejorar? (opcional)",
        )
        self.add_item(self.comment)

    async def on_submit(self, interaction: discord.Interaction):
        await Save(interaction, self.guild, self.staff_id, self.rating, self.comment.value, self.ticket)


class RatingView(discord.ui.View):
    def __init__(self, guild: discord.Guild, staff_id: int, ticket: dict | None = None):
        super().__init__(timeout=600)
        self.guild, self.staff_id, self.ticket = guild, staff_id, ticket
        Pick = discord.ui.Select(
            placeholder="¿Qué nota le das? (1-10)",
            options=[discord.SelectOption(label=f"{N}/10 · {LABELS[N]}", value=str(N), emoji="⭐" if N >= 7 else "🔸" if N >= 4 else "🔻") for N in range(10, 0, -1)],
        )
        Pick.callback = self.Picked
        self.add_item(Pick)

    async def Picked(self, interaction: discord.Interaction):
        await interaction.response.send_modal(CommentModal(self.guild, self.staff_id, int(interaction.data["values"][0]), self.ticket))


class TicketFeedbackButton(discord.ui.DynamicItem[discord.ui.Button], template=r"fbt:(?P<ticket>[0-9a-f]{24})"):
    """In the ticket-closed DM. Persistent, so it works after restarts."""

    def __init__(self, ticket_id: str):
        super().__init__(discord.ui.Button(label="Dejar feedback", emoji="⭐", style=discord.ButtonStyle.green, custom_id=f"fbt:{ticket_id}"))
        self.ticket_id = ticket_id

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Button, match):
        return cls(match["ticket"])

    async def callback(self, interaction: discord.Interaction):
        Ticket = await interaction.client.db["Tickets"].find_one({"_id": ObjectId(self.ticket_id)})
        if not Ticket or Ticket.get("UserID") != interaction.user.id:
            return await interaction.response.send_message("❌ Este ticket ya no existe.", ephemeral=True)
        Guild = interaction.client.get_guild(Ticket.get("GuildID"))
        Staff = TicketStaff(Ticket)
        if not Guild or not Staff:
            return await interaction.response.send_message("❌ No encuentro a quién te atendió.", ephemeral=True)
        try:
            await Store().Check(Guild.id, interaction.user.id, Staff, str(Ticket["_id"]))
        except FeedbackError as e:
            return await interaction.response.send_message(f"❌ {e}", ephemeral=True)
        await interaction.response.send_message(
            f"¿Qué tal te atendió <@{Staff}>?", view=RatingView(Guild, Staff, Ticket), ephemeral=True,
        )


def TicketStaff(ticket: dict) -> int | None:
    """Who gets the ticket's feedback: who claimed it, or else who closed it (if it wasn't the user)."""
    Claimer = (ticket.get("claimed") or {}).get("claimer")
    if Claimer and Claimer != ticket.get("UserID"):
        return Claimer
    Closer = (ticket.get("closed") or {}).get("closer") if isinstance(ticket.get("closed"), dict) else None
    return Closer if Closer and Closer != ticket.get("UserID") else None


# ---------------- /feedback ----------------


class FeedbackCog(commands.Cog):
    feedback = app_commands.Group(name="feedback", description="Valora al staff", guild_only=True)

    def __init__(self, client: commands.Bot):
        self.client = client

    async def cog_load(self):
        self.client.add_dynamic_items(TicketFeedbackButton)

    @feedback.command(name="dar", description="Valora a un miembro del staff del 1 al 10")
    @app_commands.describe(staff="A quién valoras", nota="Del 1 (muy mal) al 10 (excelente)", comentario="Qué hizo bien o qué puede mejorar")
    async def dar(self, interaction: discord.Interaction, staff: discord.Member, nota: app_commands.Range[int, 1, 10], comentario: str | None = None):
        Config = await Mail().Get(interaction.guild.id)
        if staff.bot or not IsStaff(staff, Config):
            return await interaction.response.send_message(f"❌ {staff.mention} no es del staff.", ephemeral=True)
        await Save(interaction, interaction.guild, staff.id, nota, (comentario or "")[:COMMENT_MAX])

    @feedback.command(name="ver", description="Mira las valoraciones de un miembro del staff")
    async def ver(self, interaction: discord.Interaction, staff: discord.Member):
        Docs = await Store().Of(interaction.guild.id, staff.id)
        Average, Count = Summary(Docs)
        Admin = interaction.user.guild_permissions.manage_guild
        embed = discord.Embed(title=f"⭐ Feedback de {staff.display_name}", color=GOLD)
        embed.set_thumbnail(url=staff.display_avatar.url)
        if Average is None:
            embed.description = "Todavía no tiene valoraciones."
        else:
            embed.description = f"{Stars(round(Average))} **{Average:.1f}/10** · {Count} valoraci{'ón' if Count == 1 else 'ones'}".replace(".", ",", 1)
            Lines = []
            for D in Docs[:8]:
                From = f" · de <@{D['author']}>" if Admin else ""
                Ticket = f" · 🎫 `{D['ticket_name']}`" if D.get("ticket_name") else ""
                Text = f"\n> {D['feedback'][:150]}" if D.get("feedback") else ""
                Lines.append(f"**{D.get('rating')}/10** · <t:{int(D.get('date') or 0)}:d>{Ticket}{From} · `#{D.get('feedbackid')}`{Text}")
            embed.add_field(name="Últimas", value="\n".join(Lines)[:1024], inline=False)
        if Admin:
            embed.set_footer(text="Borrar una: /feedback borrar id")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @feedback.command(name="borrar", description="(Admin) Borra una valoración por su número")
    @app_commands.default_permissions(manage_guild=True)
    async def borrar(self, interaction: discord.Interaction, id: int):
        if not interaction.user.guild_permissions.manage_guild:
            return await interaction.response.send_message("❌ Solo administración.", ephemeral=True)
        Doc = await Store().Remove(interaction.guild.id, id)
        if not Doc:
            return await interaction.response.send_message(f"❌ No hay feedback #{id}.", ephemeral=True)
        await interaction.response.send_message(f"🗑️ Borrado el feedback #{id} ({Doc.get('rating')}/10 a <@{Doc['staff']}>).", ephemeral=True)


async def setup(client: commands.Bot) -> None:
    await client.add_cog(FeedbackCog(client))
