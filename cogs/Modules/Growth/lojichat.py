"""LOJI chat: she joins one channel when it goes quiet and leaves when it fills up again (see core/lojichat.py)."""

import asyncio
import io
import logging
import random
from collections import deque
from datetime import timedelta

import discord
from discord import app_commands, ui
from discord.ext import commands, tasks

from cogs.Modules.Community.panel import Field, Owned, Show
from core.community import Store as Community
from core.lojichat import LOG, NOTES, OBSERVED, OPTOUT, Activity, AddressesLoji, Aware, BuildPrompt, Decide, Now, ParseReply, PickTarget

logger = logging.getLogger(__name__)
LOJI_RED = discord.Color.from_rgb(150, 12, 18)
MAX_PERSONALITY = 40_000
LIVE = 40  # lines of the current conversation kept in memory
FORCED_GAP = 15  # seconds between her messages when she was told to talk in a busy chat


def Db():
    from core.db import db

    return db


def Guide():
    from cogs.Modules.Guide.guide import Store

    return Store()


async def Settings(guild_id: int) -> dict:
    return (await Community().Get(guild_id))["lojichat"]


class LojiChat(commands.Cog):
    def __init__(self, client: commands.Bot):
        self.client = client
        self.activity = Activity()
        self.state: dict[int, dict] = {}  # guild -> {"awake", "quiet_since", "left_at", "woke_at"}
        self.live: dict[int, deque] = {}  # guild -> recent lines while awake
        self.pending: dict[int, asyncio.Task] = {}
        self.last_reply: dict = {}
        self.ticks = 0
        self.Check.start()

    def cog_unload(self):
        self.Check.cancel()

    # ---------------- listening ----------------

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not message.guild or message.author.bot or message.webhook_id:
            return
        S = await Settings(message.guild.id)
        State = self.state.get(message.guild.id) or {}
        Forced = State.get("forced")
        if message.channel.id != S["channel"] or not (S["enabled"] or Forced):
            return
        self.activity.Add(message.channel.id, message.author.id, Now())
        if not State.get("awake") or (S["mode"] != "active" and not Forced):
            return
        Ref = message.reference.resolved if message.reference else None
        ToLoji = AddressesLoji(message.content, self.client.user in message.mentions,
                               bool(Ref and getattr(Ref, "author", None) and Ref.author.id == self.client.user.id))
        Line = {"author": message.author.display_name, "author_id": message.author.id, "content": message.clean_content or "(imagen o archivo)",
                "id": message.id, "to_loji": ToLoji}
        self.live.setdefault(message.guild.id, deque(maxlen=LIVE)).append(Line)
        await self.Remember(message.guild.id, {K: V for K, V in Line.items() if K not in ("id", "to_loji")})
        if Forced and not ToLoji:
            return  # told to talk in a busy chat: she only answers whoever talks to her
        Old = self.pending.get(message.guild.id)
        if Old and not Old.done():
            if Forced:
                return  # busy chat: the reply already on its way will read the newest lines (no endless waiting)
            Old.cancel()  # quiet chat: wait a little, people often write in several messages
        Gap = max(0.0, FORCED_GAP - (Now() - self.last_reply.get(message.guild.id, Now() - timedelta(hours=1))).total_seconds()) if Forced else 0
        self.pending[message.guild.id] = asyncio.create_task(self.ReplyLater(message.guild, message.channel, S, Gap))

    async def ReplyLater(self, guild: discord.Guild, channel, s: dict, at_least: float = 0):
        try:
            await asyncio.sleep(max(at_least, random.uniform(4, 9)))
            await self.Reply(guild, channel, s, opening=False)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.warning(f"[LojiChat] Reply failed in {guild.id}: {e!r}")

    # ---------------- waking up and leaving ----------------

    @tasks.loop(seconds=30)
    async def Check(self):
        self.ticks += 1
        for Guild in self.client.guilds:
            try:
                S = await Settings(Guild.id)
                State = self.state.setdefault(Guild.id, {})
                if not S["enabled"] or State.get("forced"):  # woken up by hand: she stays until told to stop
                    continue
                Channel = Guild.get_channel(S["channel"] or 0)
                if not Channel:
                    continue
                Messages, People = self.activity.Stats(Channel.id, Now(), int(S["window"]))
                What = Decide(State, Messages, People, Now(), S)
                if What:
                    await self.Act(Guild, Channel, S, What, People, Messages)
            except Exception as e:
                logger.warning(f"[LojiChat] Check failed in {Guild.id}: {e!r}")
        if self.ticks % 120 == 1:  # about once an hour: forget what's too old
            await self.Prune()

    @Check.before_loop
    async def BeforeCheck(self):
        await self.client.wait_until_ready()

    async def Act(self, guild: discord.Guild, channel, s: dict, what: str, people: int, messages: int):
        if s["mode"] == "observe":
            if what == "wake":
                await Db()[OBSERVED].insert_one({"guild_id": guild.id, "at": Now(), "people": people, "messages": messages, "ended": None})
            else:
                await Db()[OBSERVED].update_one({"guild_id": guild.id, "ended": None}, {"$set": {"ended": Now()}})
            return
        if what == "wake":
            # What was being said right before, so she joins the conversation instead of interrupting it.
            Live = self.live.setdefault(guild.id, deque(maxlen=LIVE))
            Live.clear()
            try:
                async for M in channel.history(limit=15):
                    if not M.author.bot or M.author.id == self.client.user.id:
                        Live.appendleft({"author": "LOJI" if M.author.id == self.client.user.id else M.author.display_name,
                                         "author_id": M.author.id, "content": M.clean_content or "(imagen o archivo)"})
            except discord.HTTPException:
                pass
            await self.Reply(guild, channel, s, opening=True)
        else:
            Task = self.pending.pop(guild.id, None)
            if Task and not Task.done():
                Task.cancel()
            if s["goodbye"].strip():
                try:
                    await channel.send(s["goodbye"][:2000])
                except discord.HTTPException:
                    pass

    # ---------------- talking ----------------

    async def Used(self, guild_id: int) -> int:
        Doc = await Db()["lojichat_usage"].find_one({"_id": f"{guild_id}:{Now():%Y-%m-%d}"})
        return int((Doc or {}).get("n", 0))

    async def Reply(self, guild: discord.Guild, channel, s: dict, opening: bool):
        from core.guide import Complete, GuideError

        State = self.state.get(guild.id) or {}
        if not State.get("awake") or (s["mode"] != "active" and not State.get("forced")):
            return
        if await self.Used(guild.id) >= int(s["daily_limit"]):
            return
        Doc = await Guide().Get(guild.id) or {}
        Personality, Key = Doc.get("personality_text"), await Guide().Key(guild.id)
        if not Personality or not Key:
            return
        Live = list(self.live.get(guild.id) or [])
        if not opening and Live and Live[-1]["author"] == "LOJI":
            return  # never twice in a row without an answer
        Target, Others = (None, []) if opening else PickTarget(Live, only_addressed=bool(State.get("forced")))
        if not opening and not Target:
            return
        WokeAt = (self.state.get(guild.id) or {}).get("woke_at") or Now()
        Past = await Db()[LOG].find({"guild_id": guild.id, "at": {"$lt": WokeAt}}).sort("at", -1).to_list(length=40)
        Present = {L["author_id"] for L in Live if L.get("author_id")}
        Notes = await Db()[NOTES].find({"guild_id": guild.id, "user_id": {"$in": list(Present)}}).sort("at", -1).to_list(length=30)
        System, User = BuildPrompt(Personality, [{"name": N["name"], "text": N["text"]} for N in Notes], list(reversed(Past)), Live,
                                   int(s["context_tokens"]), guild.name, opening, Target)
        try:
            Text, _ = await Complete(Key, System, User, max_tokens=500, json_mode=True, temperature=0.9,  # chatting: a bit livelier
                                     model=Doc.get("ai_model"))
            Answer = ParseReply(Text)
        except (GuideError, ValueError) as e:
            return logger.warning(f"[LojiChat] {guild.id}: {e}")
        if not (self.state.get(guild.id) or {}).get("awake"):
            return  # the chat filled up while she was thinking
        Outgoing = Answer["messages"][:1]
        if Outgoing and Others and s.get("rest_text", "").strip():
            Outgoing.append(s["rest_text"].strip())  # several people tagged her: she answers one
        for I, Message in enumerate(Outgoing):
            async with channel.typing():
                await asyncio.sleep(min(1.5 + len(Message) / 25, 7) if I == 0 else 1.2)
            if not await self.Send(channel, Message, Target if I == 0 else None):
                break
            Line = {"author": "LOJI", "author_id": self.client.user.id, "content": Message}
            self.live.setdefault(guild.id, deque(maxlen=LIVE)).append(Line)
            await self.Remember(guild.id, Line)
            await Db()["lojichat_usage"].update_one({"_id": f"{guild.id}:{Now():%Y-%m-%d}"}, {"$inc": {"n": 1}}, upsert=True)
            self.last_reply[guild.id] = Now()
        await self.Note(guild.id, Answer["notes"], Live)
        if Answer["alert"]:
            await self.Alert(guild, channel, s, Answer["alert"], Live)

    async def Send(self, channel, text: str, target: dict | None) -> bool:
        """As a Discord reply to that person's message (they get the ping); a plain message if there's no target."""
        try:
            if target and target.get("id"):
                try:
                    await channel.send(text, reference=channel.get_partial_message(target["id"]), mention_author=True,
                                       allowed_mentions=discord.AllowedMentions(users=False, roles=False, everyone=False, replied_user=True))
                    return True
                except discord.HTTPException:  # the message was deleted: tag them instead
                    await channel.send(f"<@{target['author_id']}> {text}", allowed_mentions=discord.AllowedMentions(users=[discord.Object(target["author_id"])]))
                    return True
            await channel.send(text, allowed_mentions=discord.AllowedMentions.none())
            return True
        except discord.HTTPException:
            return False

    async def Remember(self, guild_id: int, line: dict):
        """What's said while she's awake is kept a few days (except for people who opted out)."""
        if line["author"] != "LOJI" and await Db()[OPTOUT].find_one({"_id": f"{guild_id}:{line['author_id']}"}):
            return
        await Db()[LOG].insert_one({"guild_id": guild_id, "at": Now(), **line})

    async def Note(self, guild_id: int, notes: list[dict], live: list[dict]):
        Names = {L["author"].lower(): L["author_id"] for L in live if L.get("author_id") and L["author"] != "LOJI"}
        for N in notes:
            User = Names.get(N["name"].lower())
            if not User or await Db()[OPTOUT].find_one({"_id": f"{guild_id}:{User}"}):
                continue
            await Db()[NOTES].insert_one({"guild_id": guild_id, "user_id": User, "name": N["name"], "text": N["text"], "at": Now()})

    async def Alert(self, guild: discord.Guild, channel, s: dict, why: str, live: list[dict]):
        Staff = guild.get_channel(s.get("alert_channel") or 0)
        if not Staff:
            return
        embed = discord.Embed(title="💗 LOJI cree que alguien necesita ayuda", description=why, color=discord.Color.from_rgb(255, 143, 177), timestamp=Now())
        embed.add_field(name="Últimos mensajes", value="\n".join(f"**{L['author']}:** {L['content'][:120]}" for L in live[-6:])[:1024] or "—", inline=False)
        embed.add_field(name="Canal", value=channel.mention, inline=True)
        embed.set_footer(text="Revísalo con cuidado: la IA puede equivocarse")
        try:
            await Staff.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException:
            pass

    async def Prune(self):
        try:
            for Guild in self.client.guilds:
                S = await Settings(Guild.id)
                await Db()[LOG].delete_many({"guild_id": Guild.id, "at": {"$lt": Now() - timedelta(days=int(S["log_days"]))}})
                await Db()[NOTES].delete_many({"guild_id": Guild.id, "at": {"$lt": Now() - timedelta(days=int(S["notes_days"]))}})
                await Db()[OBSERVED].delete_many({"guild_id": Guild.id, "at": {"$lt": Now() - timedelta(days=30)}})
        except Exception as e:
            logger.warning(f"[LojiChat] Prune failed: {e!r}")

    # ---------------- privacy ----------------

    loji = app_commands.Group(name="loji", description="LOJI", guild_only=True)

    @loji.command(name="interruptor", description="Hacer que LOJI hable ya, que se calle, o encender/apagar su modo automático (credencial del Tenno)")
    async def interruptor(self, interaction: discord.Interaction):
        await interaction.response.send_modal(TennoSwitch())

    async def Wake(self, guild: discord.Guild) -> str:
        """By hand (Tenno): she joins now, busy chat or not, and stays until told to stop."""
        S = await Settings(guild.id)
        Channel = guild.get_channel(S["channel"] or 0)
        if not Channel:
            return "❌ Elige primero el canal en `/config` → Crecimiento y Entretenimiento → LOJI (chat)."
        State = self.state.setdefault(guild.id, {})
        if State.get("awake") and State.get("forced"):
            return "🗣️ LOJI ya está hablando."
        State.update(awake=True, forced=True, woke_at=Now(), quiet_since=None)
        await self.Act(guild, Channel, {**S, "mode": "active"}, "wake", 0, 0)
        return f"🗣️ **LOJI está hablando en {Channel.mention}.** Se queda hasta que la mandes a callar (respeta el límite diario)."

    async def Sleep(self, guild: discord.Guild) -> str:
        S = await Settings(guild.id)
        State = self.state.setdefault(guild.id, {})
        if not State.get("awake"):
            State["forced"] = False
            return "😴 LOJI ya estaba callada."
        State.update(awake=False, forced=False, left_at=Now(), quiet_since=None)
        Channel = guild.get_channel(S["channel"] or 0)
        if Channel:
            await self.Act(guild, Channel, {**S, "mode": "active"}, "leave", 0, 0)
        return "😴 **LOJI se ha callado.**" + (" Volverá sola cuando el chat se calme (el modo automático sigue encendido)." if S["enabled"] else "")

    async def Switch(self, guild: discord.Guild, on: bool):
        """Turns LOJI chat on/off; if she was in the conversation, she says goodbye first."""
        S = await Settings(guild.id)
        await Community().Set(guild.id, "lojichat", {"enabled": on})
        State = self.state.get(guild.id) or {}
        if not on and State.get("awake"):
            State.update(awake=False, forced=False, left_at=Now(), quiet_since=None)
            Task = self.pending.pop(guild.id, None)
            if Task and not Task.done():
                Task.cancel()
            Channel = guild.get_channel(S["channel"] or 0)
            if Channel and S["goodbye"].strip() and S["mode"] == "active":
                try:
                    await Channel.send(S["goodbye"][:2000])
                except discord.HTTPException:
                    pass

    @loji.command(name="olvidame", description="Que LOJI olvide lo que habló contigo y no te recuerde (o vuelva a hacerlo)")
    async def olvidame(self, interaction: discord.Interaction):
        Key = f"{interaction.guild.id}:{interaction.user.id}"
        if await Db()[OPTOUT].find_one({"_id": Key}):
            await Db()[OPTOUT].delete_one({"_id": Key})
            return await interaction.response.send_message("💭 Vale, LOJI volverá a acordarse de las cosas que le cuentes.", ephemeral=True)
        await Db()[OPTOUT].insert_one({"_id": Key})
        await Db()[NOTES].delete_many({"guild_id": interaction.guild.id, "user_id": interaction.user.id})
        await Db()[LOG].delete_many({"guild_id": interaction.guild.id, "author_id": interaction.user.id})
        await interaction.response.send_message("🧹 Hecho: LOJI ha olvidado lo que habló contigo y no guardará nada tuyo. Usa el comando otra vez para deshacerlo.", ephemeral=True)


# ---------------- /config → Crecimiento y Entretenimiento → LOJI (chat) ----------------


async def PanelEmbed(guild: discord.Guild, cog: LojiChat | None) -> discord.Embed:
    S = await Settings(guild.id)
    Doc = await Guide().Get(guild.id) or {}
    embed = discord.Embed(title="🤖 LOJI (chat)", color=LOJI_RED)
    Mode = "👀 **Observación** (no habla, solo apunta cuándo despertaría)" if S["mode"] == "observe" else "💬 **Activo**"
    embed.description = (("✅ Activado · " + Mode) if S["enabled"] else "⏸️ **Desactivado**") + (
        "\nCuando el canal se queda tranquilo, LOJI entra a conversar con su personalidad; cuando se llena, se despide."
    )
    embed.add_field(name="💬 Canal", value=f"<#{S['channel']}>" if S["channel"] else "*sin elegir*", inline=True)
    embed.add_field(name="💗 Alertas al staff", value=f"<#{S['alert_channel']}>" if S["alert_channel"] else "*sin canal*", inline=True)
    Text = Doc.get("personality_text")
    embed.add_field(name="🧠 Personalidad", value=f"`{Doc.get('personality_filename', 'personalidad')}` · ~{len(Text) // 4:,} tokens".replace(",", ".") if Text else "❌ Sube el `.txt`", inline=True)
    embed.add_field(
        name="😴 Se despierta",
        value=f"menos de **{S['dead_people']}** personas y menos de **{S['dead_messages']}** mensajes en **{S['window']} min**, "
        f"durante **{S['sustain']} min** seguidos (y **{S['cooldown']} min** después de irse)",
        inline=False,
    )
    embed.add_field(name="👋 Se va", value=f"con **{S['dead_people']}+** personas en {S['window']} min · «{S['goodbye'][:80]}»", inline=False)
    Used = await cog.Used(guild.id) if cog else 0
    State = (cog.state.get(guild.id) or {}) if cog else {}
    embed.add_field(name="📊 Hoy", value=f"{Used}/{S['daily_limit']} mensajes · {'🌙 despierta' if State.get('awake') else '😴 dormida'}", inline=True)
    embed.add_field(name="🧠 Memoria", value=f"conversación {S['log_days']} d · personas {S['notes_days']} d · contexto {S['context_tokens']:,} tokens".replace(",", "."), inline=True)
    Seen = await Db()[OBSERVED].find({"guild_id": guild.id, "at": {"$gte": Now() - timedelta(days=7)}}).sort("at", -1).to_list(length=50)
    if S["mode"] == "observe" or Seen:
        Lines = [
            f"{discord.utils.format_dt(Aware(O['at']), 'f')} · {O['people']} pers. · "
            + (f"{int((Aware(O['ended']) - Aware(O['at'])).total_seconds() // 60)} min" if O.get("ended") else "ahora")
            for O in Seen[:8]
        ]
        embed.add_field(name=f"👀 Habría despertado {len(Seen)} vez/veces en 7 días", value="\n".join(Lines) or "Ninguna todavía.", inline=False)
    return embed


class ChatPanel(Owned):
    def __init__(self, author, s: dict):
        super().__init__(author)
        for Key, Placeholder, Row, Min in (("channel", "💬 Canal donde conversa", 0, 1), ("alert_channel", "💗 Canal del staff para alertas (opcional)", 1, 0)):
            Pick = ui.ChannelSelect(placeholder=Placeholder, channel_types=[discord.ChannelType.text], min_values=Min, max_values=1, row=Row)
            Pick.callback = self.Saver(Key)
            self.add_item(Pick)
        self.Toggle.label = "Desactivar" if s["enabled"] else "Activar"
        self.Mode.label = "Pasar a activo" if s["mode"] == "observe" else "Modo observación"

    @classmethod
    async def Open(cls, interaction, author, note=None):
        S = await Settings(interaction.guild.id)
        await Show(interaction, await PanelEmbed(interaction.guild, interaction.client.get_cog("LojiChat")), cls(author, S), note)

    def Saver(self, key):
        async def Save(interaction: discord.Interaction):
            Values = interaction.data.get("values") or []
            await Community().Set(interaction.guild.id, "lojichat", {key: int(Values[0]) if Values else None})
            await ChatPanel.Open(interaction, self.author, "✅ Guardado.")
        return Save

    @ui.button(label="Activar", emoji="⏯️", style=discord.ButtonStyle.green, row=2)
    async def Toggle(self, interaction: discord.Interaction, _):
        S = await Settings(interaction.guild.id)
        if not S["enabled"] and not S["channel"]:
            return await ChatPanel.Open(interaction, self.author, "❌ Elige primero el canal.")
        await interaction.response.send_modal(TennoSwitch(panel=self))

    @ui.button(label="Modo observación", emoji="👀", style=discord.ButtonStyle.grey, row=2)
    async def Mode(self, interaction: discord.Interaction, _):
        S = await Settings(interaction.guild.id)
        New = "active" if S["mode"] == "observe" else "observe"
        await Community().Set(interaction.guild.id, "lojichat", {"mode": New})
        await ChatPanel.Open(interaction, self.author, "💬 Modo activo: hablará cuando el chat se calme." if New == "active" else "👀 Modo observación: no habla, solo apunta cuándo habría despertado.")

    @ui.button(label="Umbrales", emoji="⚙️", style=discord.ButtonStyle.blurple, row=2)
    async def Thresholds(self, interaction: discord.Interaction, _):
        await interaction.response.send_modal(ThresholdsModal(self.author, await Settings(interaction.guild.id)))

    @ui.button(label="Límites y memoria", emoji="🧠", style=discord.ButtonStyle.blurple, row=2)
    async def Limits(self, interaction: discord.Interaction, _):
        await interaction.response.send_modal(LimitsModal(self.author, await Settings(interaction.guild.id)))

    @ui.button(label="Subir personalidad", emoji="📤", style=discord.ButtonStyle.green, row=3)
    async def Upload(self, interaction: discord.Interaction, _):
        await interaction.response.send_modal(PersonalityModal(self.author))

    @ui.button(label="Descargar", emoji="📥", style=discord.ButtonStyle.grey, row=3)
    async def Download(self, interaction: discord.Interaction, _):
        Doc = await Guide().Get(interaction.guild.id) or {}
        if not Doc.get("personality_text"):
            return await interaction.response.send_message("Todavía no hay personalidad.", ephemeral=True)
        await interaction.response.send_message("📥 La personalidad que usa LOJI:", ephemeral=True,
                                                file=discord.File(io.BytesIO(Doc["personality_text"].encode()), filename="personalidad-loji.txt"))

    @ui.button(label="Textos fijos", emoji="👋", style=discord.ButtonStyle.grey, row=3)
    async def Goodbye(self, interaction: discord.Interaction, _):
        await interaction.response.send_modal(GoodbyeModal(self.author, await Settings(interaction.guild.id)))

    @ui.button(label="Volver", emoji="⬅️", style=discord.ButtonStyle.grey, row=3)
    async def Back(self, interaction: discord.Interaction, _):
        from cogs.Modules.Growth.panel import GrowthPanel

        await GrowthPanel.Open(interaction, self.author)


class TennoSwitch(ui.Modal, title="Interruptor de LOJI"):
    """Only with the Tenno's credential (not even admins without it): make her talk now, make her stop,
    or turn the automatic mode (joining when the chat goes quiet) on or off."""

    def __init__(self, panel: "ChatPanel | None" = None):
        super().__init__()
        self.panel = panel
        self.action = ui.Select(options=[
            discord.SelectOption(label="Que hable ya", value="talk", emoji="🗣️", description="Aunque el chat esté activo; se queda hasta que la calles", default=True),
            discord.SelectOption(label="Que se calle ya", value="quiet", emoji="😴", description="Se despide y se va"),
            discord.SelectOption(label="Encender / apagar el modo automático", value="toggle", emoji="⏯️", description="Entrar sola cuando el chat se calma"),
        ])
        self.add_item(ui.Label(text="¿Qué hago?", component=self.action))
        self.code = ui.TextInput(label="Credencial del Tenno", placeholder="Tu código", max_length=20)
        self.add_item(self.code)

    async def on_submit(self, interaction: discord.Interaction):
        from core.mail.config import CheckCredential, Mail, MailError

        try:
            CheckCredential(interaction.guild.id, interaction.user.id, self.code.value.strip(), ("tenno",), await Mail().Get(interaction.guild.id))
        except MailError as e:
            return await interaction.response.send_message(f"🔒 {e}", ephemeral=True)
        S = await Settings(interaction.guild.id)
        if not S["channel"]:
            return await interaction.response.send_message("❌ Elige primero el canal en `/config` → Crecimiento y Entretenimiento → LOJI (chat).", ephemeral=True)
        Cog = interaction.client.get_cog("LojiChat")
        Action = (self.action.values or ["talk"])[0]
        Doc = await Guide().Get(interaction.guild.id) or {}
        if Action in ("talk", "quiet") and not Cog:
            return await interaction.response.send_message("❌ El módulo no está cargado.", ephemeral=True)
        if Action == "talk" and not Doc.get("personality_text"):
            return await interaction.response.send_message("❌ Falta subir la personalidad: sin ella no puede hablar.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        if Action == "talk":
            Note = await Cog.Wake(interaction.guild)
        elif Action == "quiet":
            Note = await Cog.Sleep(interaction.guild)
        else:
            On = not S["enabled"]
            if Cog:
                await Cog.Switch(interaction.guild, On)
            else:
                await Community().Set(interaction.guild.id, "lojichat", {"enabled": On})
            Note = "🟢 **Modo automático encendido:** entrará sola cuando el chat se calme." if On else "🔴 **Modo automático apagado.**"
        if self.panel:
            return await ChatPanel.Open(interaction, self.panel.author, Note)
        await interaction.followup.send(Note, ephemeral=True)


def Number(text: str, low: int, high: int) -> int:
    Value = int(text.strip())
    if not low <= Value <= high:
        raise ValueError
    return Value


class ThresholdsModal(ui.Modal, title="Cuándo entra y sale LOJI"):
    def __init__(self, author, s):
        super().__init__()
        self.author = author
        self.people = Field("Personas: se despierta con menos de…", s["dead_people"], 3, long=False, required=True)
        self.messages = Field("Mensajes: y con menos de…", s["dead_messages"], 4, long=False, required=True)
        self.window = Field("…en estos minutos", s["window"], 3, long=False, required=True)
        self.sustain = Field("Minutos tranquilo seguidos para entrar", s["sustain"], 3, long=False, required=True)
        self.cooldown = Field("Minutos de descanso tras irse", s["cooldown"], 4, long=False, required=True)
        for F in (self.people, self.messages, self.window, self.sustain, self.cooldown):
            self.add_item(F)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            Changes = {"dead_people": Number(self.people.value, 2, 50), "dead_messages": Number(self.messages.value, 1, 500),
                       "window": Number(self.window.value, 1, 60), "sustain": Number(self.sustain.value, 0, 120),
                       "cooldown": Number(self.cooldown.value, 0, 1440)}
        except ValueError:
            return await interaction.response.send_message("❌ Revisa los números (personas 2–50, mensajes 1–500, minutos 1–60, seguidos 0–120, descanso 0–1440).", ephemeral=True)
        await Community().Set(interaction.guild.id, "lojichat", Changes)
        await ChatPanel.Open(interaction, self.author, "✅ Umbrales guardados.")


class LimitsModal(ui.Modal, title="Límites y memoria"):
    def __init__(self, author, s):
        super().__init__()
        self.author = author
        self.daily = Field("Mensajes de LOJI al día (máximo)", s["daily_limit"], 4, long=False, required=True)
        self.context = Field("Contexto (tokens por respuesta)", s["context_tokens"], 6, long=False, required=True)
        self.log = Field("Días que recuerda las conversaciones", s["log_days"], 3, long=False, required=True)
        self.notes = Field("Días que recuerda cosas de la gente", s["notes_days"], 3, long=False, required=True)
        for F in (self.daily, self.context, self.log, self.notes):
            self.add_item(F)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            Changes = {"daily_limit": Number(self.daily.value, 0, 2000), "context_tokens": Number(self.context.value, 3000, 30000),
                       "log_days": Number(self.log.value, 0, 30), "notes_days": Number(self.notes.value, 0, 60)}
        except ValueError:
            return await interaction.response.send_message("❌ Mensajes 0–2000, contexto 3000–30000, días 0–30 y 0–60.", ephemeral=True)
        await Community().Set(interaction.guild.id, "lojichat", Changes)
        await ChatPanel.Open(interaction, self.author, "✅ Guardado.")


class GoodbyeModal(ui.Modal, title="Textos fijos de LOJI"):
    def __init__(self, author, s: dict):
        super().__init__()
        self.author = author
        self.text = Field("Lo que dice al irse (vacío = nada)", s["goodbye"], 300, required=False)
        self.rest = Field("Si la etiquetan varios (vacío = nada)", s.get("rest_text", ""), 300, required=False)
        self.add_item(self.text)
        self.add_item(self.rest)

    async def on_submit(self, interaction: discord.Interaction):
        await Community().Set(interaction.guild.id, "lojichat", {"goodbye": self.text.value.strip(), "rest_text": self.rest.value.strip()})
        await ChatPanel.Open(interaction, self.author, "✅ Textos guardados.")


class PersonalityModal(ui.Modal, title="Personalidad de LOJI"):
    def __init__(self, author):
        super().__init__()
        self.author = author
        self.file = ui.FileUpload(min_values=1, max_values=1)
        self.add_item(ui.Label(text="Archivo de personalidad", description=".txt, .md o .docx. Reemplaza la anterior.", component=self.file))

    async def on_submit(self, interaction: discord.Interaction):
        from core.guide import ALLOWED, ExtractText, GuideError

        File = (self.file.values or [None])[0]
        if not File or not File.filename.lower().endswith(ALLOWED + (".doc",)):
            return await interaction.response.send_message("❌ Sube un `.txt`, `.md` o `.docx`.", ephemeral=True)
        await interaction.response.defer()
        try:
            Text = ExtractText(File.filename, await File.read())
        except GuideError as e:
            return await interaction.followup.send(f"❌ {e}", ephemeral=True)
        if len(Text) > MAX_PERSONALITY:
            return await interaction.followup.send("❌ Demasiado larga: déjala por debajo de ~10.000 tokens.", ephemeral=True)
        await Guide().guides.update_one({"_id": interaction.guild.id}, {"$set": {"personality_text": Text, "personality_filename": File.filename}}, upsert=True)
        await ChatPanel.Open(interaction, self.author, f"✅ Personalidad cargada (~{len(Text) // 4:,} tokens).".replace(",", "."))


async def setup(client: commands.Bot) -> None:
    await client.add_cog(LojiChat(client))
