import asyncio
import datetime
import logging

from bson import ObjectId
from discord.ext import commands, tasks

from core.bot.CustomEmbed import DisplayEmbed
from core.bot.emojis import *
from core.format import ReplaceVariables
from core.integrations.r2 import upload_file_to_r2
from core.ticket_names import ClaimedName, NextNumber, OpenName


async def SendTranscript(client, guild, target, channel, panel: dict, ticket: dict, reason: str, closer, status_msg=None):
    """The whole ticket as one .html file in the transcript channel (Discord stores it, not our database)."""
    import io

    from core.integrations.r2 import CompressImage
    from core.transcript import Collect, Fit

    try:
        if status_msg:
            await status_msg.edit(content=f"{Emojis.loading} Cerrando... (guardando la transcripción)")
    except discord.HTTPException:
        pass
    try:
        Messages = await Collect(channel, CompressImage)
    except discord.HTTPException as e:
        return logging.critical(f"[Transcript] Can't read the ticket channel: {e}")
    Claimer = (ticket.get("claimed") or {}).get("claimer")

    def Name(user_id):
        M = guild.get_member(user_id) if user_id else None
        return f"{M.display_name} (@{M.name})" if M else (str(user_id) if user_id else None)

    Title = channel.name
    Info = {
        "title": Title, "guild": guild.name, "panel": panel.get("name"), "opened_by": Name(ticket.get("UserID")),
        "claimed_by": Name(Claimer), "closed_by": f"{closer.display_name} (@{closer.name})", "reason": reason,
        "opened": ticket.get("opened"), "closed": discord.utils.utcnow().timestamp(),
    }
    Html = await asyncio.to_thread(Fit, Info, Messages)
    People = {}
    for M in Messages:
        if not M["bot"]:
            People[M["author_id"]] = People.get(M["author_id"], 0) + 1
    embed = discord.Embed(title=f"🎫 #{Title} cerrado", color=discord.Color.from_rgb(150, 12, 18), timestamp=discord.utils.utcnow())
    embed.set_author(name=guild.name, icon_url=guild.icon.url if guild.icon else None)
    embed.add_field(name="Panel", value=panel.get("name") or "—", inline=True)
    embed.add_field(name="Abierto por", value=f"<@{ticket.get('UserID')}>", inline=True)
    embed.add_field(name="Atendido por", value=f"<@{Claimer}>" if Claimer else "—", inline=True)
    embed.add_field(name="Cerrado por", value=closer.mention, inline=True)
    if ticket.get("opened"):
        embed.add_field(name="Abierto", value=f"<t:{int(ticket['opened'])}:f>", inline=True)
    embed.add_field(name="Mensajes", value=str(len(Messages)), inline=True)
    embed.add_field(name="✅ Solución", value=(reason or "—")[:1024], inline=False)
    embed.add_field(
        name="Participantes", value="\n".join(f"<@{U}> · {N} msg" for U, N in sorted(People.items(), key=lambda x: -x[1]))[:1024] or "—", inline=False
    )
    embed.set_footer(text="Descarga el .html y ábrelo en el navegador para ver la conversación")
    try:
        Sent = await target.send(embed=embed, file=discord.File(io.BytesIO(Html), filename=f"{Title}.html"))
        await client.db["Tickets"].update_one(
            {"_id": ticket["_id"]}, {"$set": {"transcript_message": {"channel": target.id, "id": Sent.id}}}
        )
    except discord.HTTPException as e:
        logging.critical(f"[Transcript] Couldn't send to the transcript channel: {e}")


class CloseReasonModal(discord.ui.Modal, title="Cerrar ticket"):
    def __init__(self, ticket_id):
        super().__init__()
        self.ticket_id = ticket_id
        self.reason = discord.ui.TextInput(
            label="¿Cómo se solucionó?", style=discord.TextStyle.paragraph, max_length=1000,
            placeholder="Se le enviará al usuario por MD junto con la invitación a dejar feedback.",
        )
        self.add_item(self.reason)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.send_message(f"{Emojis.loading} Cerrando el ticket...", ephemeral=True)
        interaction.client.dispatch("pticket_close", self.ticket_id, self.reason.value.strip(), interaction.user)


async def ClosedDM(user, guild, ticket: dict, reason: str, closer):
    """Tells the user their ticket was closed, why, and invites them to leave feedback."""
    from cogs.Modules.feedback import TicketFeedbackButton, TicketStaff

    Reason = reason if reason and reason != "No reason provided" else "Sin motivo indicado."
    embed = discord.Embed(
        title="🎫 Tu ticket se ha cerrado",
        description=f"Tu ticket **#{ticket.get('name') or 'ticket'}** en **{guild.name}** fue cerrado.",
        color=discord.Color.from_rgb(150, 12, 18),
        timestamp=discord.utils.utcnow(),
    )
    embed.add_field(name="✅ Solución", value=Reason[:1024], inline=False)
    Staff = TicketStaff(ticket)
    if Staff:
        embed.add_field(name="👤 Te atendió", value=f"<@{Staff}>", inline=True)
    embed.add_field(name="🔒 Cerrado por", value=closer.mention, inline=True)
    if guild.icon:
        embed.set_thumbnail(url=guild.icon.url)
    View = None
    Command = f"`/feedback dar` en **{guild.name[:40]}**"
    if Staff:
        embed.add_field(
            name="⭐ ¿Qué tal te atendieron?",
            value=f"Deja tu **feedback** con el botón de abajo: son 10 segundos y nos ayuda a mejorar.\n-# También puedes usar {Command} eligiendo al staff que te atendió.",
            inline=False,
        )
        View = discord.ui.View(timeout=None)
        View.add_item(TicketFeedbackButton(str(ticket["_id"])))
    else:
        embed.add_field(
            name="⭐ ¿Qué tal te atendieron?",
            value=f"Si quieres calificar al staff que te atendió, usa {Command} y elige a esa persona. ¡Nos ayuda a mejorar!",
            inline=False,
        )
    try:
        await user.send(embed=embed, view=View) if View else await user.send(embed=embed)
    except discord.HTTPException:
        pass  # DMs closed


async def Opener(client, guild, user_id):
    """Who opened the ticket, for {user.name} in the channel name."""
    Member = guild.get_member(user_id) if guild else None
    if Member:
        return Member
    try:
        return await client.fetch_user(user_id)
    except (discord.HTTPException, TypeError):
        return None


async def TicketPermissions(interaction: discord.Interaction):
    """Ticket staff: admins, the panel's roles, or anyone in LOJI's staff hierarchy."""
    from core.mail.config import Mail
    from core.ticket_access import IsTicketStaff

    if not interaction.guild:
        return False
    t = await interaction.client.db["Tickets"].find_one(
        {"ChannelID": interaction.channel.id}
    )
    if not t:
        return False
    P = await interaction.client.db["Panels"].find_one(
        {"name": t.get("panel"), "guild": interaction.guild.id, "type": "single"}
    ) or {}
    Config = await Mail().Get(interaction.guild.id)
    return IsTicketStaff(interaction.user, P.get("permissions") or [], Config)


async def DefaultEmbed(Member: discord.Member, Ticket: dict) -> discord.Embed:

    embed = (
        discord.Embed(
            description="Welcome to Support! Please include information about your issue and a staff member will be with you shortly.",
            color=discord.Color.dark_embed(),
        )
        .add_field(
            name="` 👤 ` User Info",
            value=f"{Emojis.replytop} `User:` {Member.mention} (`{Member.id}`)\n {Emojis.replymiddle} `Created:` <t:{int(Member.created_at.timestamp())}:R>\n {Emojis.replybottom} `Joined:` <t:{int(Member.joined_at.timestamp())}:R>",
        )
        .set_author(name="Support", icon_url=Member.guild.icon)
    )
    return embed


class PTicketControl(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Close",
        style=discord.ButtonStyle.red,
        custom_id="PTICKET:CLOSE",
        emoji="🔒",
    )
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await TicketPermissions(interaction):
            return await interaction.response.send_message(
                f"{Emojis.no} **{interaction.user.display_name}** you don't have permission to close this ticket.",
                ephemeral=True,
            )

        Result = await interaction.client.db["Tickets"].find_one(
            {"MessageID": int(interaction.message.id)}
        )
        if not Result:
            return await interaction.response.send_message(
                "This isn't a ticket channel.", ephemeral=True
            )
        # The solution goes to the user's DM along with the feedback button.
        await interaction.response.send_modal(CloseReasonModal(Result.get("_id")))

    @discord.ui.button(
        label="Soltar",
        style=discord.ButtonStyle.grey,
        custom_id="PTICKET:UNCLAIM",
        emoji="↩️",
        disabled=True,
        row=1,
    )
    async def unclaim(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Unclaims the ticket (same as /tickets unclaim): the team sees it again."""
        await interaction.response.defer(ephemeral=True)
        if not await TicketPermissions(interaction):
            return await interaction.followup.send(f"{Emojis.no} No tienes permiso para soltar este ticket.", ephemeral=True)
        Result = await interaction.client.db["Tickets"].find_one({"MessageID": int(interaction.message.id)})
        if not Result:
            return await interaction.followup.send("Este no es un canal de ticket.", ephemeral=True)
        if not (Result.get("claimed") or {}).get("claimer"):
            return await interaction.followup.send("Este ticket no está reclamado.", ephemeral=True)
        await interaction.client.db["Tickets"].update_one(
            {"_id": Result["_id"]}, {"$set": {"claimed": {"claimer": None, "claimedAt": None}}}
        )
        await interaction.followup.send(f"{Emojis.tick} Soltaste el ticket: el equipo vuelve a verlo.", ephemeral=True)
        interaction.client.dispatch("unclaim", Result.get("_id"))

    @discord.ui.button(
        label="Claim",
        style=discord.ButtonStyle.green,
        custom_id="PTICKET:CLAIM",
        emoji="✋",
    )
    async def claim(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        if not await TicketPermissions(interaction):
            return await interaction.followup.send(
                f"{Emojis.no} **{interaction.user.display_name}** you don't have permission to close this ticket.",
                ephemeral=True,
            )
        Result = await interaction.client.db["Tickets"].find_one(
            {"MessageID": int(interaction.message.id)}
        )
        Panel = await interaction.client.db["Panels"].find_one(
            {
                "name": Result.get("panel"),
                "guild": interaction.guild.id,
                "type": "single",
            }
        )
        if not Result:
            return await interaction.followup.send(
                "This isn't a ticket channel.", ephemeral=True
            )
        if Result.get("claimed").get("claimer"):
            return await interaction.followup.send(
                "This ticket is already claimed.", ephemeral=True
            )
        await interaction.client.db["Tickets"].update_one(
            {"ChannelID": interaction.channel.id},
            {
                "$set": {
                    "claimed": {
                        "claimer": interaction.user.id,
                        "claimedAt": datetime.datetime.now(),
                    }
                }
            },
        )
        interaction.client.dispatch("ticket_claimed", interaction.channel, interaction.user)
        embed = discord.Embed(
            color=discord.Color.green(),
            title="Ticket Claimed",
            description=f"This ticket has been claimed by {interaction.user.mention}!",
        ).set_author(
            name=interaction.user.display_name, icon_url=interaction.user.display_avatar
        )
        view = PTicketControl()
        view.claim.disabled = True
        view.claim.label = f"Claimed by @{interaction.user.name}"
        view.unclaim.disabled = False
        await interaction.followup.send(embed=embed)
        await interaction.edit_original_response(view=view)
        if Result.get("Number"):
            User = await Opener(interaction.client, interaction.guild, Result.get("UserID"))
            name = ClaimedName(Panel or {}, Result, User, interaction.user)
        else:  # tickets opened before the numbering keep Birb's old name
            name = f"claimed-{interaction.channel.name.split('-', 1)[-1]}"

        try:
            await interaction.channel.edit(
                name=name,
            )
        except discord.Forbidden:
            return logging.critical(
                f"[on_pticket_claim] Bot does not have permission to edit the channel {interaction.channel.id}"
            )


class TicketsPublic(commands.Cog):
    def __init__(self, client: commands.Bot):
        self.client = client
        # Birb's inactivity reminder is replaced by cogs/Modules/ticketafk.py (anti-AFK).

    @tasks.loop(seconds=360)
    async def AutomAtions(self):
        Filter = {"closed": None}
        if os.getenv("ENVIRONMENT") == "custom":
            Filter["GuildID"] = int(os.getenv("CUSTOM_GUILD"))
        Tickets = await self.client.db["Tickets"].find(Filter).to_list(length=None)

        async def SendAutoMation(Ticket, semaphore):
            async with semaphore:
                await asyncio.sleep(0.4)
                if Ticket.get("lastMessenger") == int(self.client.user.id):
                    return
                Guild = self.client.get_guild(Ticket.get("GuildID"))
                if not Guild:
                    return
                Channel = Guild.get_channel(Ticket.get("ChannelID"))
                if not Channel:
                    return
                P = await self.client.db["Panels"].find_one(
                    {"name": Ticket.get("panel"), "guild": Guild.id}
                )
                if not P:
                    return
                if not P.get("Automations"):
                    return
                ActivityReminder = P.get("Automations", {}).get("Inactivity", {})
                if not ActivityReminder:
                    return
                try:
                    Inactivity = int(ActivityReminder)
                except (ValueError, TypeError):
                    return

                if Ticket.get("LastMessageWasBot", False) is True:
                    return

                LastMessagSent = Ticket.get("lastMessageSent", None)
                if not Ticket.get("automations", True):
                    return

                try:
                    InactivityDelta = datetime.timedelta(minutes=Inactivity)
                except OverflowError:
                    return

                if (
                    not LastMessagSent
                    or datetime.datetime.utcnow() - LastMessagSent > InactivityDelta
                ):
                    await self.client.db["Tickets"].update_one(
                        {"_id": Ticket.get("_id")},
                        {
                            "$set": {
                                "lastMessageSent": datetime.datetime.utcnow(),
                                "LastMessageWasBot": True,
                            }
                        },
                    )
                    try:
                        await Channel.send(
                            embed=discord.Embed(
                                title="⏰️ Activity Reminder",
                                description="It's been a while since we've heard from you. If you still need assistance, please respond to this message.",
                                color=discord.Color.dark_embed(),
                            ),
                            content=f"<@{Ticket.get('UserID')}>",
                        )

                    except discord.Forbidden:
                        return logging.critical(
                            f"[AutomAtions] Bot does not have permission to send messages in the channel {Channel.id}"
                        )

        semaphore = asyncio.Semaphore(5)
        await asyncio.gather(*[SendAutoMation(Ticket, semaphore) for Ticket in Tickets])

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not message.guild:
            return
        Ticket = await self.client.db["Tickets"].find_one(
            {"ChannelID": message.channel.id}
        )
        if not Ticket:
            return
        if not int(Ticket.get("UserID")) == int(message.author.id):
            return
        await self.client.db["Tickets"].update_one(
            {"ChannelID": message.channel.id},
            {
                "$set": {
                    "lastMessageSent": datetime.datetime.utcnow(),
                    "lastMessenger": message.author.id,
                    "LastMessageWasBot": False,
                }
            },
        )

    @commands.Cog.listener()
    async def on_pticket_review(
        self, objectID: ObjectId, rating: int, member: discord.Member
    ):
        Result = await self.client.db["Tickets"].find_one({"_id": objectID})
        if not Result:
            return logging.critical(f"[TICKETS] Ticket with ID {objectID} not found")
        Guild = self.client.get_guild(Result.get("GuildID"))
        if not Guild:
            return logging.critical(
                f"[TICKETS] Guild with ID {Result.get('GuildID')} not found"
            )
        Channel = Guild.get_channel(Result.get("ReviewChannel"))
        if not Channel:
            return logging.critical(
                f"[TICKETS] Channel with ID {Result.get('ReviewChannel')} not found"
            )
        Message = await Channel.fetch_message(Result.get("ReviewMSG"))
        if not Message:
            return logging.critical(
                f"[TICKETS] Message with ID {Result.get('ReviewMSG')} not found"
            )
        embed = Message.embeds[0]
        embed.add_field(
            name="Rating",
            value=f"` ⭐ ` {rating}\n` 💬 ` {Result.get('review', 'N/A')}",
            inline=False,
        )
        try:
            await Message.edit(embed=embed)
        except discord.Forbidden:
            return logging.critical(
                f"[on_pticket_review] Bot does not have permission to edit the message {Message.id}"
            )

    @commands.Cog.listener()
    async def on_pticket_claim(self, objectID: ObjectId, member: discord.Member):
        Result = await self.client.db["Tickets"].find_one({"_id": objectID})
        if not Result:
            return logging.critical(f"[TICKETS] Ticket with ID {objectID} not found")

        Panel = await self.client.db["Panels"].find_one(
            {"name": Result.get("panel"), "guild": int(Result.get("GuildID"))}
        )
        Channel = await self.client.fetch_channel(Result.get("ChannelID"))
        if not Channel:
            return logging.critical(
                f"[TICKETS] Channel with ID {Result.get('ChannelID')} not found"
            )
        Message = await Channel.fetch_message(Result.get("MessageID"))

        if not Message:
            return logging.critical(
                f"[TICKETS] Message with ID {Result.get('MessageID')} not found"
            )
        view = PTicketControl()
        view.claim.disabled = True
        view.claim.label = f"Claimed by @{member.name}"
        view.unclaim.disabled = False
        try:
            await Message.edit(view=view)
        except discord.Forbidden:
            return logging.critical(
                f"[on_pticket_claim] Bot does not have permission to edit the message {Message.id}"
            )
        if Result.get("Number"):
            User = await Opener(self.client, getattr(Channel, "guild", None), Result.get("UserID"))
            name = ClaimedName(Panel or {}, Result, User, member)
        else:
            name = f"claimed-{Channel.name.split('-', 1)[-1]}"

        try:
            await Channel.edit(
                name=name,
            )
        except discord.Forbidden:
            return logging.critical(
                f"[on_pticket_claim] Bot does not have permission to edit the channel {Channel.id}"
            )

    @commands.Cog.listener()
    async def on_unclaim(self, objectID: ObjectId):
        Result = await self.client.db["Tickets"].find_one({"_id": objectID})
        if not Result:
            return logging.critical(f"[TICKETS] Ticket with ID {objectID} not found")
        P = await self.client.db["Panels"].find_one(
            {
                "name": Result.get("panel"),
                "type": "single",
                "guild": Result.get("GuildID"),
            }
        )
        if not P:
            return logging.critical(f"[Tickets] panel is not found.")
        Channel = await self.client.fetch_channel(Result.get("ChannelID"))
        if not Channel:
            return logging.critical(
                f"[TICKETS] Channel with ID {Result.get('ChannelID')} not found"
            )
        Message = await Channel.fetch_message(Result.get("MessageID"))
        if not Message:
            return logging.critical(
                f"[TICKETS] Message with ID {Result.get('MessageID')} not found"
            )
        try:
            author = await self.client.fetch_user(Result.get("UserID"))
        except (discord.HTTPException, discord.NotFound):
            return logging.critical(f"[TICKETS] Authors account is not found")
        if not author:
            return
        view = PTicketControl()
        view.claim.disabled = False
        view.claim.label = "Claim"
        view.unclaim.disabled = True
        try:
            await Message.edit(view=view)
        except discord.Forbidden:
            return logging.critical(
                f"[on_unclaim] Bot does not have permission to edit the message {Message.id}"
            )
        name = OpenName(P, Result, author) if Result.get("Number") else f"ticket-{author.name}"

        try:
            await Channel.edit(
                name=name,
            )
        except discord.Forbidden:
            return logging.critical(
                f"[on_unclaim] Bot does not have permission to edit the channel {Channel.id}"
            )

    @commands.Cog.listener()
    async def on_pticket_open(self, objectID: ObjectId, Panelled: str):
        Ticket = await self.client.db["Tickets"].find_one({"_id": objectID})
        if not Ticket:
            return logging.critical("[on_pticket_open] I can't find the ticket.")

        P = await self.client.db["Panels"].find_one(
            {"name": Panelled, "type": "single", "guild": Ticket.get("GuildID")}
        )
        if not P:
            await self.client.db["Tickets"].update_one(
                {"_id": objectID}, {"$set": {"error.message": "Panel not found."}}
            )
            return logging.critical("[on_pticket_open] I can't find the panel.")
        guild_id = Ticket.get("GuildID")
        guild = await self.client.fetch_guild(guild_id)
        if not guild:
            await self.client.db["Tickets"].update_one(
                {"_id": objectID}, {"$set": {"error.message": "Guild not found."}}
            )
            return logging.critical(
                f"[on_pticket_open] I can't find the server with ID {guild_id}."
            )

        author_id = Ticket.get("UserID", {})
        author = await guild.fetch_member(author_id)
        if not author:
            await self.client.db["Tickets"].update_one(
                {"_id": objectID}, {"$set": {"error.message": "Author not found."}}
            )
            return logging.critical(
                f"[on_pticket_open] can't find the author with ID {author_id}."
            )

        welcome_message = P.get("Welcome Message")
        replacements = {
            "{author.mention}": author.mention,
            "{author.name}": author.name,
            "{author.created_at.relative}": f"<t:{int(author.created_at.timestamp())}:R>",
            "{author.created_at.absolute}": f"<t:{int(author.created_at.timestamp())}:F>",
            "{author.joined_at.relative}": f"<t:{int(author.joined_at.timestamp())}:R>",
            "{author.joined_at.absolute}": f"<t:{int(author.joined_at.timestamp())}:F>",
            "{author.id}": str(author.id),
            "{author.avatar}": str(author.avatar.url) if author.avatar else "",
            "{author.display_name}": author.display_name,
            "{guild.name}": guild.name,
            "{guild.id}": str(guild.id),
            "{time.relative}": f"<t:{int(datetime.datetime.utcnow().timestamp())}:R>",
            "{time.absolute}": f"<t:{int(datetime.datetime.utcnow().timestamp())}:F>",
            "{ticket.id}": str(Ticket.get("_id")),
        }
        Embed = (
            await DisplayEmbed(welcome_message, replacements=replacements)
            if welcome_message
            else await DefaultEmbed(author, Ticket)
        )

        if not Embed:
            Embed = await DefaultEmbed(author, Ticket)
        CategoryID = P.get("Category")
        if not CategoryID:
            await self.client.db["Tickets"].update_one(
                {"_id": objectID},
                {
                    "$set": {
                        "error.message": "The category isn't setup. Make sure to set the category in config."
                    }
                },
            )
            return logging.critical("[on_pticket_open] can't find the category ID.")
        try:
            category = await guild.fetch_channel(CategoryID)
        except (discord.NotFound, discord.HTTPException, discord.Forbidden):
            await self.client.db["Tickets"].update_one(
                {"_id": objectID},
                {
                    "$set": {
                        "error.message": "The bot can't find the category. Make sure to give the bot permission to view the category."
                    }
                },
            )
            return logging.critical(
                f"[on_pticket_open] can't find the category with ID {CategoryID}."
            )
        if not category:
            await self.client.db["Tickets"].update_one(
                {"_id": objectID}, {"$set": {"error.message": "Category not found."}}
            )
            return logging.critical(
                f"[on_pticket_open] can't find the category with ID {CategoryID}."
            )

        if not isinstance(category, discord.CategoryChannel):
            await self.client.db["Tickets"].update_one(
                {"_id": objectID}, {"$set": {"error.message": "Category not found."}}
            )
            return logging.critical(
                f"[on_pticket_open] The fetched channel with ID {CategoryID} is not a valid category."
            )

        if category.guild is None:
            await self.client.db["Tickets"].update_one(
                {"_id": objectID},
                {
                    "$set": {
                        "error.message": f"The category with the ID {CategoryID} does not belong to a valid guild."
                    }
                },
            )
            return logging.critical(
                f"[on_pticket_open] The category with ID {CategoryID} does not belong to a valid guild."
            )
        cli = await guild.fetch_member(self.client.user.id)
        if cli is None or not category.permissions_for(cli).manage_channels:
            await self.client.db["Tickets"].update_one(
                {"_id": objectID},
                {
                    "$set": {
                        "error.message": "Bot does not have permission to manage channels in the category."
                    }
                },
            )
            return logging.critical(
                f"[on_pticket_open] Bot does not have permission to manage channels in the category {CategoryID}."
            )
        Roles = [guild.get_role(role_id) for role_id in P.get("permissions", [])]
        Roles = [role for role in Roles if role]
        Overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            author: discord.PermissionOverwrite(
                read_messages=True, send_messages=True, read_message_history=True
            ),
            cli: discord.PermissionOverwrite(
                read_messages=True, send_messages=True, read_message_history=True
            ),
        }

        for role in Roles:
            Overwrites[role] = discord.PermissionOverwrite(
                read_messages=True, send_messages=True, read_message_history=True
            )
        # Each panel counts its own tickets: reporte-001, reporte-002...
        if not Ticket.get("Number"):
            Ticket["Number"] = await NextNumber(self.client.db, guild.id, P.get("name"))
            await self.client.db["Tickets"].update_one({"_id": objectID}, {"$set": {"Number": Ticket["Number"]}})
        name = OpenName(P, Ticket, author)

        try:
            channel = await category.create_text_channel(
                name=name, overwrites=Overwrites
            )
        except discord.Forbidden as e:
            await self.client.db["Tickets"].update_one(
                {"_id": objectID},
                {
                    "$set": {
                        "error.message": f"Bot does not have permission to create a text channel: {e}"
                    }
                },
            )
            return logging.critical(
                f"[on_pticket_open] The bot does not have permission to create a text channel: {e}"
            )
        except Exception as e:
            await self.client.db["Tickets"].update_one(
                {"_id": objectID},
                {"$set": {"error.message": f"Failed to create text channel: {e}"}},
            )
            return logging.critical(
                f"[on_pticket_open] Failed to create text channel: {e}"
            )

        Mentions = P.get("MentionsOnOpen", [])
        Mentions = [
            guild.get_role(role_id).mention
            for role_id in Mentions
            if guild.get_role(role_id)
        ]
        Mentions.append(author.mention)

        ResponseEmbed = None
        if Ticket.get("responses"):
            ResponseEmbed = discord.Embed(color=discord.Color.dark_embed())
            ResponseEmbed.set_image(url="https://www.astrobirb.dev/invisble.png")
            responses = Ticket.get("responses")
            for question, answer in responses.items():
                ResponseEmbed.add_field(
                    name=question, value=f"> {answer}", inline=False
                )
                if len(ResponseEmbed.fields) == 25:
                    break
        view = PTicketControl()
        try:
            msg = await channel.send(
                embeds=[Embed, ResponseEmbed] if ResponseEmbed else [Embed],
                content=" ".join(Mentions),
                allowed_mentions=discord.AllowedMentions(roles=True, users=True),
                view=view,
            )
        except discord.Forbidden:
            await self.client.db["Tickets"].update_one(
                {"_id": objectID},
                {
                    "$set": {
                        "error.message": "Bot does not have permission to send messages in the channel."
                    }
                },
            )
            return logging.critical(
                f"[on_pticket_open] Bot does not have permission to send messages in the channel {channel.id}"
            )
        await self.client.db["Tickets"].update_one(
            {"_id": objectID}, {"$set": {"ChannelID": channel.id, "MessageID": msg.id}}
        )

    @commands.Cog.listener()
    async def on_pticket_close(
        self, ObjectID: ObjectId, reason: str, member: discord.Member
    ):
        try:
            await self.CloseTicket(ObjectID, reason, member)
        except Exception as e:
            logging.exception(f"[on_pticket_close] Unexpected error closing {ObjectID}: {e!r}")
            # Last resort: don't leave the ticket hanging on "closing".
            T = await self.client.db["Tickets"].find_one({"_id": ObjectID})
            Channel = self.client.get_channel((T or {}).get("ChannelID") or 0)
            if Channel:
                await self.client.db["Tickets"].update_one(
                    {"_id": ObjectID, "closed": None},
                    {"$set": {"closed": {"reason": reason, "closer": member.id, "closedAt": datetime.datetime.now()}}},
                )
                try:
                    await Channel.delete(reason="Ticket cerrado")
                except discord.HTTPException:
                    pass

    async def CloseTicket(self, ObjectID: ObjectId, reason: str, member: discord.Member):
        Result = await self.client.db["Tickets"].find_one({"_id": ObjectID})
        if not Result:
            return logging.critical(f"[TICKETS] Ticket with ID {ObjectID} not found")

        Guild = self.client.get_guild(Result.get("GuildID"))
        if not Guild:
            return logging.critical(
                f"[TICKETS] Guild with ID {Result.get('GuildID')} not found",
                extra={
                    "GuildId": Result.get("GuildID"),
                    "ChannelId": Result.get("ChannelId"),
                    "Author": f"{member.name}/{member.id}",
                },
            )

        Channel = Guild.get_channel(Result.get("ChannelID"))
        if not Channel:
            return logging.critical(
                f"[TICKETS] Channel with ID {Result.get('ChannelID')} not found",
                extra={
                    "GuildId": Result.get("GuildID"),
                    "ChannelId": Result.get("ChannelId"),
                    "Author": f"{member.name}/{member.id}",
                },
            )
        try:
            user = await Guild.fetch_member(Result.get("UserID"))
        except (discord.NotFound, discord.HTTPException):
            user = None
        msg = None
        try:
            msg = await Channel.send(
                f"{Emojis.loading} Ticket closing...",
            )
        except (discord.NotFound, discord.Forbidden):
            logging.warning(
                "[on_ticket_close] The channel wasn't found",
                extra={
                    "GuildId": Result.get("GuildID"),
                    "ChannelId": Result.get("ChannelId"),
                    "Author": f"{member.name}/{member.id}",
                },
            )

        P = await self.client.db["Panels"].find_one(
            {"name": Result.get("panel"), "guild": Guild.id}
        )
        if not P:
            # A renamed or deleted panel used to leave the ticket stuck on "closing" forever.
            logging.critical("[on_pticket_close] I can't find the panel; closing without transcript.")
            P = {"name": Result.get("panel")}
        try:
            await self.client.db["Ticket Quota"].update_one(
                {
                    "GuildID": Guild.id,
                    "UserID": Result.get("claimed", {}).get("claimer"),
                },
                {"$inc": {"ClaimedTickets": 1}},
                upsert=True,
            )
        except:
            pass

        # Always marked closed (before, only when there was a transcript channel).
        Closed = {"reason": reason, "closer": member.id, "closedAt": datetime.datetime.now()}
        await self.client.db["Tickets"].update_one({"_id": ObjectID}, {"$set": {"closed": Closed, "name": Result.get("name") or Channel.name}})
        # Each step is guarded and time-limited: whatever fails, the ticket still gets deleted.
        async def Step(name, coro, seconds):
            try:
                await asyncio.wait_for(coro, timeout=seconds)
            except Exception as e:
                logging.exception(f"[on_pticket_close] {name} failed for ticket {ObjectID}: {e!r}")

        if user:
            await Step("DM", ClosedDM(user, Guild, {**Result, "closed": Closed, "name": Result.get("name") or Channel.name}, reason, member), 20)

        try:
            TranscriptChannel = Guild.get_channel(int(P.get("TranscriptChannel") or 0))
        except (TypeError, ValueError):
            TranscriptChannel = None
        if TranscriptChannel:
            await Step("Transcript", SendTranscript(self.client, Guild, TranscriptChannel, Channel, P, {**Result, "_id": ObjectID}, reason, member, msg), 120)

        try:
            await Channel.delete(reason=f"Ticket cerrado por {member}")
        except discord.HTTPException as e:
            logging.critical(f"[on_pticket_close] Can't delete the channel {Channel.id}: {e}")
            if msg:
                try:
                    await msg.edit(content=f"{Emojis.no} No pude borrar este canal (me falta **Gestionar canales** aquí). El ticket ya está cerrado: bórralo a mano.")
                except discord.HTTPException:
                    pass


class Review(discord.ui.Select):
    def __init__(self):
        super().__init__(
            placeholder="How would you rate the support?",
            options=[
                discord.SelectOption(label="1", value="1"),
                discord.SelectOption(label="2", value="2"),
                discord.SelectOption(label="3", value="3"),
                discord.SelectOption(label="4", value="4"),
                discord.SelectOption(label="5", value="5"),
                discord.SelectOption(label="6", value="6"),
                discord.SelectOption(label="7", value="7"),
                discord.SelectOption(label="8", value="8"),
                discord.SelectOption(label="9", value="9"),
                discord.SelectOption(label="10", value="10"),
            ],
        )

    async def callback(self, interaction: discord.Interaction):
        Ticket = await interaction.client.db["Tickets"].find_one(
            {"ReviewerMsg": interaction.message.id}
        )
        if not Ticket:
            return await interaction.response.send_message(
                "This isn't a review message.", ephemeral=True
            )
        if not Ticket.get("closed"):
            return await interaction.response.send_message(
                "This ticket is not closed.", ephemeral=True
            )
        if Ticket.get("review"):
            return await interaction.response.send_message(
                f"{Emojis.no} **{interaction.user.display_name},** you've already reviewed this.",
                ephemeral=True,
            )

        await interaction.response.send_modal(FormalReview(Ticket, self.values[0]))


class FormalReview(discord.ui.Modal):
    def __init__(self, ticket: dict, rating: int):
        super().__init__(timeout=None, title="Exit Review", custom_id="REVIEW")

        self.ticket = ticket
        self.rating = rating
        self.review = discord.ui.TextInput(
            label="Review",
            placeholder="Write your review here.",
            min_length=10,
            max_length=500,
            required=False,
        )

        self.add_item(self.review)

    async def on_submit(self, interaction: discord.Interaction):
        review = self.review.value if not self.review.value == "" else "N/A"
        if not self.ticket.get("closed"):
            return await interaction.response.send_message(
                "This ticket is not closed.", ephemeral=True
            )
        if self.ticket.get("review"):
            return await interaction.response.send_message(
                f"{Emojis.no} **{interaction.user.display_name},** you've already reviewed this.",
                ephemeral=True,
            )

        await interaction.client.db["Tickets"].update_one(
            {"_id": self.ticket.get("_id")},
            {"$set": {"review": review, "rating": self.rating}},
        )
        Result = await interaction.client.db["Tickets"].find_one(
            {"_id": self.ticket.get("_id")}
        )
        if not Result:
            return await interaction.response.send_message(
                "I can't find the ticket.", ephemeral=True
            )
        interaction.client.dispatch(
            "pticket_review", Result.get("_id"), self.rating, interaction.user
        )
        view = discord.ui.View()
        view.add_item(
            discord.ui.Button(
                label="Reviewed",
                style=discord.ButtonStyle.success,
                disabled=True,
                emoji=f"{Emojis.tick}",
            )
        )
        await interaction.response.edit_message(view=view)


async def setup(client: commands.Bot) -> None:
    await client.add_cog(TicketsPublic(client))
