import datetime
import logging
import random
import string

import discord
from discord import app_commands
from discord.ext import commands

from core.bot.HelpEmbeds import NotYourPanel
from core.bot.Module import ModuleIsEnabled
from core.bot.emojis import Emojis
from core.bot.permissions import RequireAdmin

logger = logging.getLogger(__name__)

MODULE = "StaffManagement"


def NewId():
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=6))


def Ts(dt: datetime.datetime, style: str) -> str:
    # Mongo hands datetimes back without a timezone, but they are stored in UTC.
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return discord.utils.format_dt(dt, style)


def IsCaretaker(Config: dict, member: discord.Member) -> bool:
    Roles = Config.get(MODULE, {}).get("caretakers", [])
    if any(role.id in Roles for role in member.roles):
        return True
    return RequireAdmin(Config, member)


def IsApprover(Config: dict, member: discord.Member) -> bool:
    Roles = Config.get(MODULE, {}).get("approvers", [])
    if any(role.id in Roles for role in member.roles):
        return True
    return RequireAdmin(Config, member)


async def GetProfile(client: commands.Bot, guild_id: int, staff_id: int) -> dict:
    Profile = await client.db["StaffProfiles"].find_one(
        {"guild_id": guild_id, "staff": staff_id}
    )
    return Profile or {"guild_id": guild_id, "staff": staff_id, "sanctions": 0, "notes": []}


async def ProfileEmbed(client: commands.Bot, guild: discord.Guild, staff: discord.Member):
    Profile = await GetProfile(client, guild.id, staff.id)
    Infractions = await client.db["infractions"].count_documents(
        {"guild_id": guild.id, "staff": staff.id, "voided": {"$ne": True}}
    )
    Promotions = await client.db["promotions"].count_documents(
        {"guild_id": guild.id, "staff": staff.id, "voided": {"$ne": True}}
    )
    Pending = await client.db["StaffPromotionRequests"].count_documents(
        {"guild_id": guild.id, "staff": staff.id, "status": "pending"}
    )

    embed = discord.Embed(
        title=f"Perfil de {staff.display_name}",
        color=discord.Color.dark_embed(),
    )
    embed.set_thumbnail(url=staff.display_avatar)
    embed.set_author(name=guild.name, icon_url=guild.icon)
    embed.add_field(
        name="👤 Información",
        value=(
            f"> **Usuario:** {staff.mention}\n"
            f"> **Rango más alto:** {staff.top_role.mention}\n"
            f"> **En el servidor desde:** "
            f"{discord.utils.format_dt(staff.joined_at, 'R') if staff.joined_at else 'N/A'}"
        ),
        inline=False,
    )
    embed.add_field(
        name="📊 Registro",
        value=(
            f"> **Sanciones:** `{Profile.get('sanctions', 0)}`\n"
            f"> **Infracciones (Birb):** `{Infractions}`\n"
            f"> **Ascensos (Birb):** `{Promotions}`\n"
            f"> **Solicitudes de ascenso pendientes:** `{Pending}`"
        ),
        inline=False,
    )

    Notes = Profile.get("notes", [])
    if Notes:
        Lines = []
        for Note in Notes[-3:][::-1]:
            Text = Note.get("text", "")
            if len(Text) > 150:
                Text = Text[:150] + "..."
            Lines.append(
                f"> `{Note.get('id')}` <@{Note.get('author')}> "
                f"({Ts(Note.get('timestamp'), 'R')}): {Text}"
            )
        Value = "\n".join(Lines)
        if len(Notes) > 3:
            Value += f"\n-# y {len(Notes) - 3} comentario(s) más, pulsa **Comentarios** para verlos."
    else:
        Value = "> Sin comentarios todavía."
    embed.add_field(name="💬 Últimos comentarios", value=Value, inline=False)
    return embed


class AddNote(discord.ui.Modal, title="Añadir comentario"):
    text = discord.ui.TextInput(
        label="Comentario",
        style=discord.TextStyle.paragraph,
        max_length=1000,
    )

    def __init__(self, staff: discord.Member, message: discord.Message):
        super().__init__()
        self.staff = staff
        self.message = message

    async def on_submit(self, interaction: discord.Interaction):
        Note = {
            "id": NewId(),
            "author": interaction.user.id,
            "text": self.text.value,
            "timestamp": discord.utils.utcnow(),
        }
        await interaction.client.db["StaffProfiles"].update_one(
            {"guild_id": interaction.guild.id, "staff": self.staff.id},
            {"$push": {"notes": Note}, "$setOnInsert": {"sanctions": 0}},
            upsert=True,
        )
        await interaction.response.send_message(
            f"{Emojis.tick} **{interaction.user.display_name}**, comentario `{Note['id']}` añadido.",
            ephemeral=True,
        )
        try:
            await self.message.edit(
                embed=await ProfileEmbed(interaction.client, interaction.guild, self.staff)
            )
        except discord.HTTPException:
            pass


class RequestReason(discord.ui.Modal, title="Solicitar ascenso"):
    reason = discord.ui.TextInput(
        label="¿Por qué merece el ascenso?",
        style=discord.TextStyle.paragraph,
        max_length=1000,
    )

    def __init__(self, staff: discord.Member, role: discord.Role):
        super().__init__()
        self.staff = staff
        self.role = role

    async def on_submit(self, interaction: discord.Interaction):
        Config = await interaction.client.config.find_one({"_id": interaction.guild.id})
        ChannelId = (Config or {}).get(MODULE, {}).get("channel")
        Channel = interaction.guild.get_channel(ChannelId) if ChannelId else None
        if not Channel:
            return await interaction.response.send_message(
                f"{Emojis.no} **{interaction.user.display_name}**, no hay un canal de solicitudes configurado. Configúralo en `/config` → **Gestión del Staff**.",
                ephemeral=True,
            )

        RequestId = NewId()
        embed = discord.Embed(
            title="Solicitud de ascenso",
            description=(
                f"> **Staff:** {self.staff.mention}\n"
                f"> **Rango actual:** {self.staff.top_role.mention}\n"
                f"> **Rango propuesto:** {self.role.mention}\n"
                f"> **Solicitado por:** {interaction.user.mention}\n"
                f"> **Motivo:** {self.reason.value}"
            ),
            color=discord.Color.yellow(),
            timestamp=discord.utils.utcnow(),
        )
        embed.set_thumbnail(url=self.staff.display_avatar)
        embed.set_footer(text=f"Solicitud {RequestId} | Pendiente")

        try:
            msg = await Channel.send(embed=embed, view=PromotionRequestView())
        except discord.HTTPException:
            return await interaction.response.send_message(
                f"{Emojis.no} **{interaction.user.display_name}**, no puedo enviar mensajes en {Channel.mention}.",
                ephemeral=True,
            )

        await interaction.client.db["StaffPromotionRequests"].insert_one(
            {
                "_id": RequestId,
                "guild_id": interaction.guild.id,
                "staff": self.staff.id,
                "requester": interaction.user.id,
                "role": self.role.id,
                "reason": self.reason.value,
                "status": "pending",
                "channel_id": Channel.id,
                "message_id": msg.id,
                "timestamp": discord.utils.utcnow(),
            }
        )
        await interaction.response.edit_message(
            content=f"{Emojis.tick} **{interaction.user.display_name}**, solicitud `{RequestId}` enviada a {Channel.mention}.",
            view=None,
        )


class RequestRole(discord.ui.RoleSelect):
    def __init__(self, author: discord.Member, staff: discord.Member):
        super().__init__(placeholder="¿A qué rango quieres ascenderle?")
        self.author = author
        self.staff = staff

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.author.id:
            return await interaction.response.send_message(
                embed=NotYourPanel(), ephemeral=True
            )
        Role = self.values[0]
        if Role in self.staff.roles:
            return await interaction.response.send_message(
                f"{Emojis.no} **{self.staff.display_name}** ya tiene {Role.mention}.",
                ephemeral=True,
            )
        if Role.managed or Role.is_default():
            return await interaction.response.send_message(
                f"{Emojis.no} Ese rol no se puede asignar.", ephemeral=True
            )
        await interaction.response.send_modal(RequestReason(self.staff, Role))


class ProfileView(discord.ui.View):
    def __init__(self, author: discord.Member, staff: discord.Member):
        super().__init__(timeout=900)
        self.author = author
        self.staff = staff

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author.id:
            await interaction.response.send_message(embed=NotYourPanel(), ephemeral=True)
            return False
        return True

    async def ChangeSanctions(self, interaction: discord.Interaction, amount: int):
        Profile = await GetProfile(interaction.client, interaction.guild.id, self.staff.id)
        New = max(0, Profile.get("sanctions", 0) + amount)
        await interaction.client.db["StaffProfiles"].update_one(
            {"guild_id": interaction.guild.id, "staff": self.staff.id},
            {"$set": {"sanctions": New}, "$setOnInsert": {"notes": []}},
            upsert=True,
        )
        await interaction.response.edit_message(
            embed=await ProfileEmbed(interaction.client, interaction.guild, self.staff)
        )

    @discord.ui.button(label="Sanción +1", style=discord.ButtonStyle.red, row=0)
    async def AddSanction(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.ChangeSanctions(interaction, 1)

    @discord.ui.button(label="Sanción -1", style=discord.ButtonStyle.grey, row=0)
    async def RemoveSanction(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.ChangeSanctions(interaction, -1)

    @discord.ui.button(label="Comentar", emoji="💬", style=discord.ButtonStyle.blurple, row=1)
    async def Comment(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(AddNote(self.staff, interaction.message))

    @discord.ui.button(label="Comentarios", emoji="📜", style=discord.ButtonStyle.grey, row=1)
    async def Comments(self, interaction: discord.Interaction, button: discord.ui.Button):
        Profile = await GetProfile(interaction.client, interaction.guild.id, self.staff.id)
        Notes = Profile.get("notes", [])
        if not Notes:
            return await interaction.response.send_message(
                f"**{self.staff.display_name}** no tiene comentarios.", ephemeral=True
            )
        embed = discord.Embed(
            title=f"Comentarios de {self.staff.display_name}",
            color=discord.Color.dark_embed(),
        )
        Description = ""
        for Note in Notes[::-1]:
            Line = (
                f"**`{Note.get('id')}`** · <@{Note.get('author')}> · "
                f"{Ts(Note.get('timestamp'), 'd')}\n> {Note.get('text')}\n\n"
            )
            if len(Description) + len(Line) > 4000:
                Description += "-# Hay más comentarios antiguos que no caben aquí."
                break
            Description += Line
        embed.description = Description
        embed.set_footer(text="Para borrar uno: /gestion borrar-comentario")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="Solicitar ascenso", emoji="⬆️", style=discord.ButtonStyle.green, row=1)
    async def RequestPromotion(self, interaction: discord.Interaction, button: discord.ui.Button):
        Pending = await interaction.client.db["StaffPromotionRequests"].find_one(
            {"guild_id": interaction.guild.id, "staff": self.staff.id, "status": "pending"}
        )
        if Pending:
            return await interaction.response.send_message(
                f"{Emojis.no} Ya hay una solicitud pendiente para **{self.staff.display_name}** (`{Pending['_id']}`).",
                ephemeral=True,
            )
        view = discord.ui.View(timeout=300)
        view.add_item(RequestRole(interaction.user, self.staff))
        await interaction.response.send_message(view=view, ephemeral=True)


class DenyReason(discord.ui.Modal, title="Denegar ascenso"):
    reason = discord.ui.TextInput(
        label="Motivo (opcional)",
        style=discord.TextStyle.paragraph,
        max_length=500,
        required=False,
    )

    def __init__(self, request: dict):
        super().__init__()
        self.request = request

    async def on_submit(self, interaction: discord.Interaction):
        await FinishRequest(interaction, self.request, False, self.reason.value or None)


async def FinishRequest(
    interaction: discord.Interaction, request: dict, approved: bool, reason: str = None
):
    Result = await interaction.client.db["StaffPromotionRequests"].update_one(
        {"_id": request["_id"], "status": {"$in": ["pending", "approving"]}},
        {
            "$set": {
                "status": "approved" if approved else "denied",
                "decided_by": interaction.user.id,
                "decision_reason": reason,
                "decided_at": discord.utils.utcnow(),
            }
        },
    )
    if not Result.modified_count:
        return await interaction.response.send_message(
            "Esta solicitud ya fue resuelta.", ephemeral=True
        )

    embed = interaction.message.embeds[0]
    embed.color = discord.Color.green() if approved else discord.Color.red()
    Status = "Aprobada" if approved else "Denegada"
    embed.add_field(
        name=f"{'✅' if approved else '❌'} {Status}",
        value=f"> **Por:** {interaction.user.mention}"
        + (f"\n> **Motivo:** {reason}" if reason else ""),
        inline=False,
    )
    embed.set_footer(text=f"Solicitud {request['_id']} | {Status}")
    await interaction.response.edit_message(embed=embed, view=None)

    try:
        Requester = await interaction.guild.fetch_member(request["requester"])
        await Requester.send(
            f"Tu solicitud de ascenso para <@{request['staff']}> en **{interaction.guild.name}** fue **{Status.lower()}** por {interaction.user.display_name}."
            + (f"\nMotivo: {reason}" if reason else "")
        )
    except discord.HTTPException:
        pass


async def ApplyPromotion(interaction: discord.Interaction, request: dict, Config: dict):
    """Gives the role. Uses Birb's promotions module (log + role) when it's set up."""
    Role = interaction.guild.get_role(request["role"])
    if not Role:
        return "El rol solicitado ya no existe."
    try:
        Staff = await interaction.guild.fetch_member(request["staff"])
    except discord.HTTPException:
        return "Esa persona ya no está en el servidor."
    if Role >= interaction.guild.me.top_role:
        return f"No puedo dar {Role.mention}: está por encima de mi rol más alto."
    if interaction.user.top_role <= Role and interaction.user.id != interaction.guild.owner_id:
        return f"No puedes aprobar ascensos a {Role.mention}: está por encima de tu rol."

    if Config.get("Modules", {}).get("promotions") and Config.get("Promo", {}).get("channel"):
        Object = await interaction.client.db["promotions"].insert_one(
            {
                "management": interaction.user.id,
                "staff": Staff.id,
                "reason": request["reason"],
                "new": Role.id,
                "previous": None,
                "random_string": "".join(
                    random.choices(string.ascii_uppercase + string.digits, k=10)
                ),
                "guild_id": interaction.guild.id,
                "jump_url": None,
                "timestamp": datetime.datetime.now(),
                "annonymous": False,
            }
        )
        interaction.client.dispatch("promotion", Object.inserted_id, Config)
        return None

    try:
        await Staff.add_roles(Role, reason=f"Ascenso aprobado por {interaction.user.name}")
    except discord.HTTPException:
        return f"No pude darle {Role.mention} a {Staff.mention}."
    return None


class PromotionRequestView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def GetRequest(self, interaction: discord.Interaction):
        Config = await interaction.client.config.find_one({"_id": interaction.guild.id}) or {}
        if not IsApprover(Config, interaction.user):
            await interaction.response.send_message(
                f"{Emojis.no} Solo el alto mando puede resolver solicitudes.", ephemeral=True
            )
            return None, None
        Request = await interaction.client.db["StaffPromotionRequests"].find_one(
            {"message_id": interaction.message.id}
        )
        if not Request or Request.get("status") != "pending":
            await interaction.response.send_message(
                "Esta solicitud ya fue resuelta o no existe.", ephemeral=True
            )
            return None, None
        return Request, Config

    @discord.ui.button(
        label="Aprobar", emoji="✅", style=discord.ButtonStyle.green, custom_id="staffmanagement:approve"
    )
    async def Approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        Request, Config = await self.GetRequest(interaction)
        if not Request:
            return
        Requests = interaction.client.db["StaffPromotionRequests"]
        # Claim it first so a double click can't promote twice.
        Claimed = await Requests.update_one(
            {"_id": Request["_id"], "status": "pending"},
            {"$set": {"status": "approving"}},
        )
        if not Claimed.modified_count:
            return await interaction.response.send_message(
                "Esta solicitud ya se está resolviendo.", ephemeral=True
            )
        Error = await ApplyPromotion(interaction, Request, Config)
        if Error:
            await Requests.update_one(
                {"_id": Request["_id"]}, {"$set": {"status": "pending"}}
            )
            return await interaction.response.send_message(
                f"{Emojis.no} {Error}", ephemeral=True
            )
        await FinishRequest(interaction, Request, True)

    @discord.ui.button(
        label="Denegar", emoji="✖️", style=discord.ButtonStyle.red, custom_id="staffmanagement:deny"
    )
    async def Deny(self, interaction: discord.Interaction, button: discord.ui.Button):
        Request, _ = await self.GetRequest(interaction)
        if not Request:
            return
        await interaction.response.send_modal(DenyReason(Request))


class StaffManagement(commands.Cog):
    def __init__(self, client: commands.Bot):
        self.client = client

    async def CheckCaretaker(self, ctx: commands.Context):
        Config = await self.client.config.find_one({"_id": ctx.guild.id}) or {}
        if not IsCaretaker(Config, ctx.author):
            await ctx.send(
                f"{Emojis.no} **{ctx.author.display_name}**, necesitas el rol de cuidador para usar esto.",
                ephemeral=True,
            )
            return False
        return True

    @commands.hybrid_group(name="gestion", description="Gestión del staff")
    async def gestion(self, ctx: commands.Context):
        pass

    @gestion.command(name="perfil", description="Ver y gestionar el perfil de un miembro del staff")
    @app_commands.describe(staff="El miembro del staff")
    @ModuleIsEnabled(MODULE)
    async def perfil(self, ctx: commands.Context, staff: discord.Member):
        if not await self.CheckCaretaker(ctx):
            return
        if staff.bot:
            return await ctx.send(f"{Emojis.no} Los bots no tienen perfil.", ephemeral=True)
        await ctx.send(
            embed=await ProfileEmbed(self.client, ctx.guild, staff),
            view=ProfileView(ctx.author, staff),
        )

    @gestion.command(name="borrar-comentario", description="Borrar un comentario de un perfil")
    @app_commands.describe(staff="El miembro del staff", id="El ID del comentario")
    @ModuleIsEnabled(MODULE)
    async def borrar_comentario(self, ctx: commands.Context, staff: discord.Member, id: str):
        if not await self.CheckCaretaker(ctx):
            return
        Config = await self.client.config.find_one({"_id": ctx.guild.id}) or {}
        Profile = await GetProfile(self.client, ctx.guild.id, staff.id)
        Note = next(
            (N for N in Profile.get("notes", []) if N.get("id") == id.upper()), None
        )
        if not Note:
            return await ctx.send(
                f"{Emojis.no} No encontré el comentario `{id}`.", ephemeral=True
            )
        if Note.get("author") != ctx.author.id and not IsApprover(Config, ctx.author):
            return await ctx.send(
                f"{Emojis.no} Solo puedes borrar tus propios comentarios.", ephemeral=True
            )
        await self.client.db["StaffProfiles"].update_one(
            {"guild_id": ctx.guild.id, "staff": staff.id},
            {"$pull": {"notes": {"id": Note["id"]}}},
        )
        await ctx.send(f"{Emojis.tick} Comentario `{Note['id']}` borrado.", ephemeral=True)


async def setup(client: commands.Bot) -> None:
    await client.add_cog(StaffManagement(client))
