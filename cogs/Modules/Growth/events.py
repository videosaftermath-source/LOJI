"""/evento: events made by the events team, with sign-up, reminders, native Discord events and prizes."""

import io
import logging
from datetime import timedelta

import discord
from discord import app_commands, ui
from discord.ext import commands, tasks

from core.community import Color, Store as Community
from core.events import (
    EVENTS, MEDALS, Awards, Aware, CanJoin, Due, Now, ParsePrizes, PrizeLine, ResolveRoles,
)

logger = logging.getLogger(__name__)
BANNER_MAX = 8 * 1024 * 1024
DRAFT_TIMEOUT = 1800


def Db():
    from core.db import db

    return db


async def Settings(guild_id: int) -> dict:
    return (await Community().Get(guild_id))["events"]


def CanRun(member: discord.Member, settings: dict) -> bool:
    from core.ticket_access import IsAdmin

    return IsAdmin(member) or any(R.id == settings.get("organizer_role") for R in member.roles)


async def Get(event_id: str) -> dict | None:
    return await Db()[EVENTS].find_one({"_id": event_id})


async def Save(event_id: str, changes: dict):
    await Db()[EVENTS].update_one({"_id": event_id}, {"$set": changes})


# ---------------- the announcement ----------------


def Values(event: dict, guild: discord.Guild) -> dict:
    Start = Aware(event["start"])
    People = event.get("participants") or []
    Slots = event.get("slots")
    return {
        "titulo": event["title"], "descripcion": event["description"], "server": guild.name,
        "fecha": f"{discord.utils.format_dt(Start, 'F')} · {discord.utils.format_dt(Start, 'R')}",
        "premios": "\n".join(PrizeLine(P) for P in event.get("prizes") or []) or "—",
        "inscritos": f"{len(People)}/{Slots}" if Slots else str(len(People)),
        "organiza": f"<@{event['organizer']}>",
    }


def StatusLine(event: dict) -> str:
    return {"open": "", "finished": "\n-# 🏁 **Evento finalizado**", "cancelled": "\n-# ❌ **Evento cancelado**"}.get(event.get("status"), "")


def Buttons(event: dict) -> list[ui.Item]:
    if not event.get("signup"):
        return []
    Closed = event.get("status") != "open"
    Join = EventButton(event["_id"], "join")
    Join.item.disabled = Closed
    List = EventButton(event["_id"], "list")
    return [Join, List]


def DefaultView(guild: discord.Guild, event: dict, settings: dict) -> ui.LayoutView:
    V = Values(event, guild)
    View = ui.LayoutView(timeout=None)
    Box = ui.Container(accent_colour=Color(settings["color"], 0xBBA896))
    if event.get("banner"):
        Box.add_item(ui.MediaGallery(discord.MediaGalleryItem(f"attachment://{event['banner']}")))
    Box.add_item(ui.TextDisplay(f"## 🎉 {event['title']}\n{event['description']}"[:4000]))
    Box.add_item(ui.Separator())
    Box.add_item(ui.TextDisplay(f"### 📅 Cuándo\n{V['fecha']}"))
    if event.get("prizes"):
        Box.add_item(ui.TextDisplay(f"### 🏆 Premios\n{V['premios']}"[:4000]))
    if event.get("signup"):
        Box.add_item(ui.TextDisplay(f"### 👥 Inscritos · {V['inscritos']}"))
    Rows = Buttons(event)
    if Rows:
        Box.add_item(ui.Separator(visible=False))
        Box.add_item(ui.ActionRow(*Rows))
    Box.add_item(ui.TextDisplay(f"-# Organiza {V['organiza']}{StatusLine(event)}"))
    View.add_item(Box)
    return View


def JsonComponents(guild: discord.Guild, event: dict) -> list[dict]:
    """The team's own JSON design with the variables filled and the sign-up buttons in {botones} (or at the end)."""
    from core.community import FillJson, ParseCardJson
    from core.ticket_v2 import Assemble

    Design = FillJson(ParseCardJson(event["json"]), Values(event, guild))
    Rows = [B.item.to_component_dict() for B in Buttons(event)]
    if not Rows:
        return Design
    return Assemble(Design, [{"type": 1, "components": Rows}])


async def Render(guild: discord.Guild, event: dict, settings: dict) -> tuple[ui.LayoutView | None, list[dict] | None]:
    if event.get("json"):
        return None, JsonComponents(guild, event)
    return DefaultView(guild, event, settings), None


async def Refresh(client, guild: discord.Guild, event: dict):
    """Re-draws the announcement (sign-ups, finished…); the banner attachment stays."""
    Ref = event.get("message")
    Channel = guild.get_channel(Ref["channel"]) if Ref else None
    if not Channel:
        return
    View, Raw = await Render(guild, event, await Settings(guild.id))
    try:
        if Raw is not None:
            from discord.http import Route

            await client.http.request(Route("PATCH", "/channels/{channel_id}/messages/{message_id}", channel_id=Channel.id, message_id=Ref["id"]),
                                      json={"components": Raw})
        else:
            await Channel.get_partial_message(Ref["id"]).edit(view=View)
    except discord.HTTPException as e:
        logger.warning(f"[Events] Couldn't refresh {event['_id']}: {e}")


async def Publish(client, guild: discord.Guild, event: dict) -> str:
    Settings_ = await Settings(guild.id)
    Channel = guild.get_channel(Settings_["channel"] or 0)
    if not Channel:
        return "❌ No hay canal de eventos (`/config` → Crecimiento y Entretenimiento → Eventos)."
    event["status"] = "open"
    Ping = guild.get_role(Settings_.get("ping_role") or 0)
    View, Raw = await Render(guild, event, Settings_)
    Banner = await Db()[EVENTS + "_banners"].find_one({"_id": event["_id"]})
    File = discord.File(io.BytesIO(bytes(Banner["data"])), filename=event["banner"]) if Banner and event.get("banner") else None
    try:
        if Raw is not None:
            from cogs.Modules.Community.community import SendJson

            Sent = await SendJson(client.http, Channel.id, Raw)
            Message = {"channel": Channel.id, "id": int(Sent["id"])}
            if Ping:
                await Channel.send(Ping.mention, allowed_mentions=discord.AllowedMentions(roles=[Ping]))
        else:
            Kwargs = {"file": File} if File else {}
            Sent = await Channel.send(view=View, allowed_mentions=discord.AllowedMentions.none(), **Kwargs)
            Message = {"channel": Channel.id, "id": Sent.id}
            if Ping:
                await Channel.send(Ping.mention, allowed_mentions=discord.AllowedMentions(roles=[Ping]), reference=Sent)
    except discord.HTTPException as e:
        event["status"] = "draft"
        return f"❌ No pude publicar en {Channel.mention}: {e.text or e}"
    Changes = {"status": "open", "message": Message, "published_at": Now()}
    if event.get("native"):
        Changes["native_id"], Note = await CreateNative(guild, event)
    else:
        Note = ""
    await Save(event["_id"], Changes)
    await Db()[EVENTS + "_banners"].delete_one({"_id": event["_id"]})  # the message has it now
    await Log(guild, Settings_, f"🎉 <@{event['organizer']}> publicó **{event['title']}** · https://discord.com/channels/{guild.id}/{Channel.id}/{Message['id']}")
    return f"✅ Evento publicado en {Channel.mention}.{Note}"


async def CreateNative(guild: discord.Guild, event: dict) -> tuple[int | None, str]:
    """The Discord event (top of the server, "Interesado"). In a voice/stage channel if one was chosen."""
    Start = Aware(event["start"])
    if Start <= Now() + timedelta(minutes=1):
        return None, "\n⚠️ El evento de Discord no se creó: la fecha ya pasó o es inminente."
    Channel = guild.get_channel(event.get("voice") or 0)
    try:
        Kwargs = {"name": event["title"][:100], "description": event["description"][:1000], "start_time": Start,
                  "privacy_level": discord.PrivacyLevel.guild_only}
        if isinstance(Channel, (discord.VoiceChannel, discord.StageChannel)):
            Native = await guild.create_scheduled_event(channel=Channel, entity_type=discord.EntityType.stage_instance if isinstance(Channel, discord.StageChannel) else discord.EntityType.voice, **Kwargs)
        else:
            Native = await guild.create_scheduled_event(entity_type=discord.EntityType.external, location=f"#{guild.name}"[:100],
                                                        end_time=Start + timedelta(hours=2), **Kwargs)
        return Native.id, "\n📅 También se creó el **evento de Discord**."
    except discord.HTTPException as e:
        return None, f"\n⚠️ No pude crear el evento de Discord ({e.text or e}). Necesito el permiso **Gestionar eventos**."


async def Log(guild: discord.Guild, settings: dict, text: str):
    Channel = guild.get_channel(settings.get("log_channel") or 0)
    if Channel:
        try:
            await Channel.send(text[:2000], allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException:
            pass


class EventButton(ui.DynamicItem[ui.Button], template=r"ev:(?P<id>[A-Z0-9]{8}):(?P<act>join|list)"):
    def __init__(self, event_id: str, act: str):
        if act == "join":
            Button = ui.Button(label="Me apunto", emoji="✋", style=discord.ButtonStyle.green, custom_id=f"ev:{event_id}:join")
        else:
            Button = ui.Button(label="Inscritos", emoji="👥", style=discord.ButtonStyle.grey, custom_id=f"ev:{event_id}:list")
        super().__init__(Button)
        self.event_id, self.act = event_id, act

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(match["id"], match["act"])

    async def callback(self, interaction: discord.Interaction):
        Event = await Get(self.event_id)
        if not Event:
            return await interaction.response.send_message("❌ Este evento ya no existe.", ephemeral=True)
        if self.act == "list":
            People = Event.get("participants") or []
            Text = "\n".join(f"`{I:02d}` <@{P}>" for I, P in enumerate(People, 1)) or "Nadie todavía. ¡Sé el primero!"
            return await interaction.response.send_message(
                embed=discord.Embed(title=f"👥 Inscritos · {Event['title']}"[:256], description=Text[:4000], color=discord.Color.from_rgb(187, 168, 150)),
                ephemeral=True, allowed_mentions=discord.AllowedMentions.none(),
            )
        Me = interaction.user.id
        if Me in (Event.get("participants") or []):
            Event = await Db()[EVENTS].find_one_and_update({"_id": self.event_id}, {"$pull": {"participants": Me}}, return_document=True)
            Text = "👋 Te has desapuntado."
        else:
            Ok, Why = CanJoin(Event, Me)
            if not Ok:
                return await interaction.response.send_message(f"❌ {Why}", ephemeral=True)
            Filter = {"_id": self.event_id, "status": "open", "participants": {"$ne": Me}}
            if Event.get("slots"):  # two clicks for the last seat can't both get it
                Filter[f"participants.{int(Event['slots']) - 1}"] = {"$exists": False}
            Event = await Db()[EVENTS].find_one_and_update(Filter, {"$push": {"participants": Me}}, return_document=True)
            if not Event:
                return await interaction.response.send_message("❌ Se acaban de llenar las plazas. 😔", ephemeral=True)
            Text = f"✅ ¡Apuntado a **{Event['title']}**! Te avisaré antes de que empiece."
        await interaction.response.send_message(Text, ephemeral=True)
        await Refresh(interaction.client, interaction.guild, Event)


# ---------------- creating ----------------


class EventModal(ui.Modal, title="Nuevo evento"):
    def __init__(self, organizer_id: int):
        super().__init__()
        self.organizer_id = organizer_id
        self.title_ = ui.TextInput(label="Título", max_length=100)
        self.description = ui.TextInput(label="Descripción", style=discord.TextStyle.paragraph, max_length=2000)
        self.when = ui.TextInput(label="Cuándo empieza", placeholder="05/12 18:00 · o dentro de: 2d, 3h…", max_length=30)
        self.prizes = ui.TextInput(
            label="Premios (opcional, un puesto por línea)", style=discord.TextStyle.paragraph, required=False, max_length=1000,
            placeholder="1: 5000 monedas, @Campeón, Nitro\n2: 2000 monedas\n3: 1000 monedas",
        )
        self.banner = ui.FileUpload(min_values=0, max_values=1, required=False)
        for F in (self.title_, self.description, self.when, self.prizes):
            self.add_item(F)
        self.add_item(ui.Label(text="Banner (opcional)", description="Una imagen para el anuncio.", component=self.banner))

    async def on_submit(self, interaction: discord.Interaction):
        from core.economy.shop import NewId
        from core.mail.tasks import ParseDeadline

        try:
            from core.economy.config import EcoConfig

            Offset = (await EcoConfig().Get(interaction.guild.id))["activity"].get("utc_offset", 0)
        except Exception:
            Offset = 0
        try:
            Start = ParseDeadline(self.when.value, Now(), Offset)
        except ValueError:
            return await interaction.response.send_message("❌ No entiendo la fecha. Usa `05/12 18:00` o `2d`, `3h`… (tiene que ser futura).", ephemeral=True)
        Text = ResolveRoles(self.prizes.value or "", [(R.id, R.name) for R in interaction.guild.roles])
        try:
            Prizes = ParsePrizes(Text)
        except ValueError as e:
            return await interaction.response.send_message(f"❌ {e}", ephemeral=True)
        Files = self.banner.values or []
        if Files and (not (Files[0].content_type or "").startswith("image/") or Files[0].size > BANNER_MAX):
            return await interaction.response.send_message("❌ El banner tiene que ser una imagen de menos de 8 MB.", ephemeral=True)
        await interaction.response.defer(ephemeral=True, thinking=True)
        Event = {
            "_id": NewId(8), "guild_id": interaction.guild.id, "organizer": self.organizer_id, "title": self.title_.value.strip(),
            "description": self.description.value.strip(), "start": Start, "prizes": Prizes, "signup": True, "slots": None,
            "native": False, "voice": None, "json": None, "banner": None, "participants": [], "status": "draft", "created_at": Now(),
        }
        if Files:
            Ext = (Files[0].filename.rsplit(".", 1)[-1] or "png").lower()[:4]
            Event["banner"] = f"evento.{Ext}"
            from bson.binary import Binary

            await Db()[EVENTS + "_banners"].update_one({"_id": Event["_id"]}, {"$set": {"data": Binary(await Files[0].read())}}, upsert=True)
        await Db()[EVENTS].insert_one(Event)
        await interaction.followup.send(embed=DraftEmbed(Event), view=DraftView(interaction.user, Event["_id"]), ephemeral=True)


def DraftEmbed(event: dict) -> discord.Embed:
    embed = discord.Embed(title=f"📝 Borrador · {event['title']}"[:256], color=discord.Color.from_rgb(187, 168, 150))
    embed.description = "Ajusta las opciones y pulsa **📤 Publicar**. **👁️ Vista previa** te lo enseña tal cual saldrá."
    embed.add_field(name="📅 Empieza", value=discord.utils.format_dt(Aware(event["start"]), "F"), inline=True)
    embed.add_field(name="✋ Inscripción", value=("Sí" + (f" · {event['slots']} plazas" if event.get("slots") else " · sin límite")) if event["signup"] else "No (evento abierto)", inline=True)
    embed.add_field(name="📅 Evento de Discord", value=("Sí" + (f" · <#{event['voice']}>" if event.get("voice") else "")) if event["native"] else "No", inline=True)
    embed.add_field(name="🏆 Premios", value="\n".join(PrizeLine(P) for P in event["prizes"])[:1024] or "—", inline=False)
    embed.add_field(name="🎨 Diseño", value="📄 JSON propio" if event.get("json") else "🧩 Diseño de LOJI", inline=True)
    embed.add_field(name="🖼️ Banner", value="Sí" if event.get("banner") else "No", inline=True)
    return embed


class DraftView(ui.View):
    def __init__(self, author, event_id: str):
        super().__init__(timeout=DRAFT_TIMEOUT)
        self.author, self.event_id = author, event_id
        Voice = ui.ChannelSelect(placeholder="🔊 Canal de voz o escenario del evento (opcional)",
                                 channel_types=[discord.ChannelType.voice, discord.ChannelType.stage_voice], min_values=0, row=0)
        Voice.callback = self.PickVoice
        self.add_item(Voice)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.author.id

    async def Show(self, interaction: discord.Interaction, note: str | None = None):
        Event = await Get(self.event_id)
        Edit = interaction.edit_original_response if interaction.response.is_done() else interaction.response.edit_message
        await Edit(content=note, embed=DraftEmbed(Event), view=DraftView(self.author, self.event_id))

    async def PickVoice(self, interaction: discord.Interaction):
        Values_ = interaction.data.get("values") or []
        await Save(self.event_id, {"voice": int(Values_[0]) if Values_ else None, **({"native": True} if Values_ else {})})
        await self.Show(interaction, "✅ Canal guardado." if Values_ else "🧹 Sin canal.")

    @ui.button(label="Inscripción", emoji="✋", style=discord.ButtonStyle.blurple, row=1)
    async def Signup(self, interaction: discord.Interaction, _):
        Event = await Get(self.event_id)
        await Save(self.event_id, {"signup": not Event["signup"]})
        await self.Show(interaction)

    @ui.button(label="Plazas", emoji="🔢", style=discord.ButtonStyle.blurple, row=1)
    async def Slots(self, interaction: discord.Interaction, _):
        await interaction.response.send_modal(SlotsModal(self))

    @ui.button(label="Evento de Discord", emoji="📅", style=discord.ButtonStyle.blurple, row=1)
    async def Native(self, interaction: discord.Interaction, _):
        Event = await Get(self.event_id)
        await Save(self.event_id, {"native": not Event["native"]})
        await self.Show(interaction)

    @ui.button(label="Diseño JSON", emoji="📄", style=discord.ButtonStyle.grey, row=2)
    async def Json(self, interaction: discord.Interaction, _):
        await interaction.response.send_modal(JsonModal(self))

    @ui.button(label="Quitar JSON", emoji="🧹", style=discord.ButtonStyle.grey, row=2)
    async def NoJson(self, interaction: discord.Interaction, _):
        await Save(self.event_id, {"json": None})
        await self.Show(interaction, "🧹 Vuelve el diseño de LOJI.")

    @ui.button(label="Vista previa", emoji="👁️", style=discord.ButtonStyle.grey, row=2)
    async def Preview(self, interaction: discord.Interaction, _):
        from cogs.Modules.Community.community import SendJson

        Event = await Get(self.event_id)
        View, Raw = await Render(interaction.guild, {**Event, "status": "open"}, await Settings(interaction.guild.id))
        if Raw is not None:
            await interaction.response.defer(ephemeral=True, thinking=False)
            try:
                await SendJson(interaction.client.http, 0, Raw, ephemeral_token=(interaction.application_id, interaction.token))
            except discord.HTTPException as e:
                await interaction.followup.send(f"❌ Discord no acepta el diseño: {e.text or e}", ephemeral=True)
            return
        Banner = await Db()[EVENTS + "_banners"].find_one({"_id": self.event_id})
        Kwargs = {"file": discord.File(io.BytesIO(bytes(Banner["data"])), filename=Event["banner"])} if Banner and Event.get("banner") else {}
        await interaction.response.send_message(view=View, ephemeral=True, allowed_mentions=discord.AllowedMentions.none(), **Kwargs)

    @ui.button(label="Publicar", emoji="📤", style=discord.ButtonStyle.green, row=3)
    async def Publish_(self, interaction: discord.Interaction, _):
        await interaction.response.defer()
        Event = await Get(self.event_id)
        if Event["status"] != "draft":
            return await interaction.edit_original_response(content="Este evento ya se publicó.", embed=None, view=None)
        Result = await Publish(interaction.client, interaction.guild, Event)
        if Result.startswith("✅"):
            self.stop()
            return await interaction.edit_original_response(content=Result, embed=None, view=None)
        await self.Show(interaction, Result)

    @ui.button(label="Descartar", emoji="🗑️", style=discord.ButtonStyle.red, row=3)
    async def Discard(self, interaction: discord.Interaction, _):
        await Db()[EVENTS].delete_one({"_id": self.event_id, "status": "draft"})
        await Db()[EVENTS + "_banners"].delete_one({"_id": self.event_id})
        self.stop()
        await interaction.response.edit_message(content="🗑️ Borrador descartado.", embed=None, view=None)


class SlotsModal(ui.Modal, title="Plazas"):
    def __init__(self, draft: DraftView):
        super().__init__()
        self.draft = draft
        self.value = ui.TextInput(label="Plazas máximas (vacío = sin límite)", required=False, max_length=4)
        self.add_item(self.value)

    async def on_submit(self, interaction: discord.Interaction):
        Text = self.value.value.strip()
        if Text and (not Text.isdigit() or not 1 <= int(Text) <= 5000):
            return await interaction.response.send_message("❌ Un número entre 1 y 5000, o vacío.", ephemeral=True)
        await Save(self.draft.event_id, {"slots": int(Text) if Text else None, **({"signup": True} if Text else {})})
        await self.draft.Show(interaction)


class JsonModal(ui.Modal, title="Diseño JSON del evento"):
    def __init__(self, draft: DraftView):
        super().__init__()
        self.draft = draft
        self.file = ui.FileUpload(min_values=1, max_values=1)
        self.add_item(ui.Label(
            text="Archivo .json (Components V2)",
            description="Variables: {titulo} {descripcion} {fecha} {premios} {inscritos} {organiza}. Botones: {botones}.",
            component=self.file,
        ))

    async def on_submit(self, interaction: discord.Interaction):
        from core.community import ParseCardJson

        File = (self.file.values or [None])[0]
        if not File or not File.filename.lower().endswith((".json", ".txt")):
            return await interaction.response.send_message("❌ Sube un archivo `.json`.", ephemeral=True)
        try:
            Text = (await File.read()).decode("utf-8-sig")
            ParseCardJson(Text)
        except (UnicodeDecodeError, ValueError) as e:
            return await interaction.response.send_message(f"❌ {e}", ephemeral=True)
        await Save(self.draft.event_id, {"json": Text})
        await self.draft.Show(interaction, "✅ Diseño guardado. Mira la **Vista previa**.")


# ---------------- the cog ----------------


async def EventChoices(interaction: discord.Interaction, current: str):
    Docs = await Db()[EVENTS].find({"guild_id": interaction.guild.id, "status": "open"}).to_list(length=50)
    return [app_commands.Choice(name=f"{D['title']} · {Aware(D['start']):%d/%m}"[:100], value=D["_id"])
            for D in Docs if current.lower() in D["title"].lower()][:25]


class Events(commands.Cog):
    def __init__(self, client: commands.Bot):
        self.client = client
        self.Reminders.start()

    async def cog_load(self):
        self.client.add_dynamic_items(EventButton)

    def cog_unload(self):
        self.Reminders.cancel()

    evento = app_commands.Group(name="evento", description="Eventos del servidor", guild_only=True)

    async def Allowed(self, interaction: discord.Interaction) -> dict | None:
        S = await Settings(interaction.guild.id)
        if not CanRun(interaction.user, S):
            await interaction.response.send_message("❌ Solo el equipo de eventos (o la administración) gestiona eventos.", ephemeral=True)
            return None
        return S

    @evento.command(name="crear", description="Crear un evento (formulario sencillo, luego opciones y vista previa)")
    async def crear(self, interaction: discord.Interaction):
        if await self.Allowed(interaction) is not None:
            await interaction.response.send_modal(EventModal(interaction.user.id))

    @evento.command(name="finalizar", description="Terminar un evento y repartir los premios a los ganadores (en orden)")
    @app_commands.describe(evento="El evento", ganadores="Menciones o IDs en orden: 1º, 2º, 3º…")
    @app_commands.autocomplete(evento=EventChoices)
    async def finalizar(self, interaction: discord.Interaction, evento: str, ganadores: str | None = None):
        import re

        S = await self.Allowed(interaction)
        if S is None:
            return
        Event = await Db()[EVENTS].find_one_and_update({"_id": evento, "guild_id": interaction.guild.id, "status": "open"},
                                                       {"$set": {"status": "finished", "finished_at": Now()}}, return_document=True)
        if not Event:
            return await interaction.response.send_message("❌ Ese evento no está abierto (¿ya se finalizó?).", ephemeral=True)
        await interaction.response.defer()
        Winners = list(dict.fromkeys(int(I) for I in re.findall(r"\d{15,21}", ganadores or "")))
        Lines, Manual = [], []
        for User, Prize in Awards(Event.get("prizes") or [], Winners):
            Member = interaction.guild.get_member(User)
            Got = []
            if Prize["coins"]:
                try:
                    from core.economy.constants import CREATED
                    from core.economy.service import Economy

                    await Economy().Add(interaction.guild.id, User, Prize["coins"], f"Premio del evento {Event['title']}", kind=CREATED, ref=f"event:{Event['_id']}")
                    Got.append(f"🪙 {Prize['coins']:,}".replace(",", "."))
                except Exception as e:
                    Got.append(f"⚠️ monedas sin pagar ({e})")
            for RoleId in Prize["roles"]:
                Role = interaction.guild.get_role(RoleId)
                try:
                    if Role and Member:
                        await Member.add_roles(Role, reason=f"Premio del evento {Event['title']}")
                        Got.append(Role.mention)
                    else:
                        Got.append(f"⚠️ rol <@&{RoleId}> sin dar")
                except discord.HTTPException:
                    Got.append(f"⚠️ no pude dar <@&{RoleId}>")
            if Prize["manual"]:
                Manual.append(f"<@{User}>: {', '.join(Prize['manual'])}")
                Got.append("🎁 " + ", ".join(Prize["manual"]) + " *(lo entrega el staff)*")
            Lines.append(f"{MEDALS.get(Prize['place'], str(Prize['place']) + 'º')} <@{User}> · " + (" · ".join(Got) or "—"))
        await Save(Event["_id"], {"winners": Winners, "results": Lines})
        await Refresh(self.client, interaction.guild, Event)
        await self.EndNative(interaction.guild, Event)
        Result = discord.Embed(title=f"🏁 {Event['title']} · Resultados"[:256], color=discord.Color.from_rgb(187, 168, 150), timestamp=Now())
        Result.description = "\n".join(Lines) or "Sin ganadores."
        Result.set_footer(text=f"{len(Event.get('participants') or [])} participante(s) · organizado por {interaction.guild.get_member(Event['organizer']) or 'el equipo de eventos'}")
        Ref = Event.get("message")
        Channel = interaction.guild.get_channel(Ref["channel"]) if Ref else None
        if Channel:
            try:
                await Channel.send(" ".join(f"<@{W}>" for W in Winners) or None, embed=Result, reference=Channel.get_partial_message(Ref["id"]),
                                   allowed_mentions=discord.AllowedMentions(users=True))
            except discord.HTTPException:
                pass
        await Log(interaction.guild, S, f"🏁 **{Event['title']}** finalizado por {interaction.user.mention}.\n" + "\n".join(Lines))
        Pending = ("\n\n🎁 **Premios para entregar a mano:**\n" + "\n".join(Manual)) if Manual else ""
        await interaction.followup.send(f"🏁 Evento finalizado y premios repartidos.{Pending}", ephemeral=True)

    @evento.command(name="cancelar", description="Cancelar un evento abierto")
    @app_commands.autocomplete(evento=EventChoices)
    async def cancelar(self, interaction: discord.Interaction, evento: str):
        S = await self.Allowed(interaction)
        if S is None:
            return
        Event = await Db()[EVENTS].find_one_and_update({"_id": evento, "guild_id": interaction.guild.id, "status": "open"},
                                                       {"$set": {"status": "cancelled", "finished_at": Now()}}, return_document=True)
        if not Event:
            return await interaction.response.send_message("❌ Ese evento no está abierto.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        await Refresh(self.client, interaction.guild, Event)
        await self.EndNative(interaction.guild, Event, cancel=True)
        await Log(interaction.guild, S, f"❌ **{Event['title']}** cancelado por {interaction.user.mention}.")
        await interaction.followup.send("❌ Evento cancelado.", ephemeral=True)

    @evento.command(name="historial", description="Últimos eventos, ganadores y quién los organizó")
    async def historial(self, interaction: discord.Interaction):
        if await self.Allowed(interaction) is None:
            return
        Docs = await Db()[EVENTS].find({"guild_id": interaction.guild.id, "status": {"$in": ["open", "finished", "cancelled"]}}).to_list(length=None)
        Docs.sort(key=lambda D: Aware(D["start"]), reverse=True)
        Icons = {"open": "🟢", "finished": "🏁", "cancelled": "❌"}
        Lines = [
            f"{Icons[D['status']]} **{D['title']}** · {discord.utils.format_dt(Aware(D['start']), 'd')} · <@{D['organizer']}> · 👥 {len(D.get('participants') or [])}"
            + (f" · 🥇 <@{D['winners'][0]}>" if D.get("winners") else "")
            for D in Docs[:15]
        ]
        Month = [D for D in Docs if D["status"] == "finished" and Aware(D.get("finished_at") or D["start"]) >= Now() - timedelta(days=30)]
        ByOrganizer: dict[int, int] = {}
        for D in Month:
            ByOrganizer[D["organizer"]] = ByOrganizer.get(D["organizer"], 0) + 1
        embed = discord.Embed(title="🎉 Historial de eventos", description="\n".join(Lines) or "Todavía no hay eventos.", color=discord.Color.from_rgb(187, 168, 150))
        if ByOrganizer:
            embed.add_field(name="🏅 Eventos finalizados en 30 días", value="\n".join(f"<@{U}> · {N}" for U, N in sorted(ByOrganizer.items(), key=lambda X: -X[1]))[:1024], inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

    async def EndNative(self, guild: discord.Guild, event: dict, cancel: bool = False):
        if not event.get("native_id"):
            return
        try:
            Native = await guild.fetch_scheduled_event(event["native_id"])
            if Native.status == discord.EventStatus.active and not cancel:
                await Native.end()
            elif Native.status == discord.EventStatus.scheduled:
                await (Native.cancel() if cancel else Native.delete())
        except (discord.HTTPException, ValueError):
            pass

    @tasks.loop(minutes=2)
    async def Reminders(self):
        Now_ = Now()
        try:
            Docs = await Db()[EVENTS].find({"status": "open", "start": {"$lte": Now_ + timedelta(hours=24)}}).to_list(length=None)
        except Exception as e:
            return logger.warning(f"[Events] Reminder check failed: {e!r}")
        for Event in Docs:
            Guild = self.client.get_guild(Event["guild_id"])
            if not Guild:
                continue
            S = await Settings(Guild.id)
            What = Due(Event, Now_, int(S["remind_minutes"]))
            if not What:
                continue
            Field = "reminded" if What == "remind" else "started"
            Done = await Db()[EVENTS].update_one({"_id": Event["_id"], Field: {"$ne": True}}, {"$set": {Field: True}})
            if not Done.modified_count:
                continue
            Ref = Event.get("message")
            Channel = Guild.get_channel(Ref["channel"]) if Ref else None
            if not Channel:
                continue
            People = Event.get("participants") or []
            Role = Guild.get_role(S.get("ping_role") or 0)
            Call = " ".join(f"<@{P}>" for P in People[:50]) if Event.get("signup") and People else (Role.mention if Role else "")
            Start = Aware(Event["start"])
            Text = (f"⏰ {Call} **{Event['title']}** empieza {discord.utils.format_dt(Start, 'R')}." if What == "remind"
                    else f"🎉 {Call} ¡**{Event['title']}** empieza ya!")
            try:
                await Channel.send(Text.replace("  ", " "), reference=Channel.get_partial_message(Ref["id"]),
                                   allowed_mentions=discord.AllowedMentions(users=True, roles=True))
            except discord.HTTPException:
                pass

    @Reminders.before_loop
    async def BeforeReminders(self):
        await self.client.wait_until_ready()


async def setup(client: commands.Bot) -> None:
    await client.add_cog(Events(client))
