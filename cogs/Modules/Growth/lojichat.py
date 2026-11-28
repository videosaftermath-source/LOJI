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
from core.lojichat import LOG, NOTES, OBSERVED, OLD_REST, OPTOUT, SLOW_WAIT, Activity, AddressesLoji, Aware, BatchAdd, BatchReady, BuildPrompt, Decide, Ignored, NewBatch, Now, ParseReply, PickFresh, PickTargets, RestPhrase, SpamCheck, Strike

logger = logging.getLogger(__name__)
LOJI_RED = discord.Color.from_rgb(150, 12, 18)
MAX_PERSONALITY = 40_000
LIVE = 40  # lines of the current conversation kept in memory


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
        self.pending: dict[int, asyncio.Task] = {}  # guild -> the batch being collected (waiting to answer)
        self.batches: dict[int, dict] = {}
        self.locks: dict[int, asyncio.Lock] = {}  # one answer at a time per server
        self.handled: dict[int, set] = {}  # guild -> ids of messages she already dealt with
        self.last_reply: dict = {}
        self.spam: dict[tuple, deque] = {}  # (guild, user) -> their recent messages to LOJI
        self.trolls: dict[tuple, dict] = {}  # (guild, user) -> {"warned_at", "ignored_until"}
        self.used_phrases: dict[int, list[str]] = {}  # guild -> phrases for "the rest" said lately (no repeats)
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
        if S.get("antitroll", True) and Ignored(self.trolls.get((message.guild.id, message.author.id)), Now()):
            return  # reported a moment ago: she ignores them for a while
        Ref = message.reference.resolved if message.reference else None
        ToLoji = AddressesLoji(message.content, self.client.user in message.mentions,
                               bool(Ref and getattr(Ref, "author", None) and Ref.author.id == self.client.user.id))
        RefAuthor = getattr(Ref, "author", None)
        Line = {"author": message.author.display_name, "author_id": message.author.id, "content": message.clean_content or "(imagen o archivo)",
                "id": message.id, "to_loji": ToLoji,
                "reply_to": ("LOJI" if RefAuthor.id == self.client.user.id else RefAuthor.display_name) if RefAuthor else None}
        self.live.setdefault(message.guild.id, deque(maxlen=LIVE)).append(Line)
        await self.Remember(message.guild.id, {K: V for K, V in Line.items() if K not in ("id", "to_loji", "reply_to")})
        if ToLoji and S.get("antitroll", True):
            Why = SpamCheck(self.spam.setdefault((message.guild.id, message.author.id), deque()), Now(), message.content, S)
            if Why:
                self.spam[(message.guild.id, message.author.id)].clear()
                Mine = {L.get("id") for L in self.live[message.guild.id] if L.get("author_id") == message.author.id and L.get("id")}
                self.handled.setdefault(message.guild.id, set()).update(Mine)  # their spam gets no normal answers
                return await self.Troll(message.guild, message.channel, S, Line, Why)
        if Forced and not ToLoji:
            return  # told to talk in a busy chat: she only answers whoever talks to her
        Gid = message.guild.id
        Batch, Task = self.batches.get(Gid), self.pending.get(Gid)
        if Batch and Task and not Task.done():
            BatchAdd(Batch, Now())  # joins the batch she's collecting
            return
        Batch = self.batches[Gid] = NewBatch(Now(), random.uniform(*SLOW_WAIT))
        self.pending[Gid] = asyncio.create_task(self.Collect(message.guild, message.channel, S, Batch))

    async def Collect(self, guild: discord.Guild, channel, s: dict, batch: dict):
        """Waits for the window to close (see core/lojichat.py), then answers everyone in one request."""
        try:
            while not BatchReady(batch, Now()):
                await asyncio.sleep(0.5)
            if self.batches.get(guild.id) is batch:
                self.batches.pop(guild.id, None)  # what's written from now on starts a new batch
            async with self.locks.setdefault(guild.id, asyncio.Lock()):
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
                        RefAuthor = getattr(M.reference.resolved if M.reference else None, "author", None)
                        Live.appendleft({"author": "LOJI" if M.author.id == self.client.user.id else M.author.display_name,
                                         "author_id": M.author.id, "content": M.clean_content or "(imagen o archivo)", "id": M.id,
                                         "reply_to": ("LOJI" if RefAuthor.id == self.client.user.id else RefAuthor.display_name) if RefAuthor else None})
            except discord.HTTPException:
                pass
            await self.Reply(guild, channel, s, opening=True)
        else:
            Task = self.pending.pop(guild.id, None)
            self.batches.pop(guild.id, None)
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
        Low = max(1, int(s.get("min_answers", 4)))
        Most = random.randint(Low, max(Low, int(s.get("max_answers", 6))))  # how many of those who tagged her she answers this time
        Handled = self.handled.setdefault(guild.id, set())
        Targets, Rest = ([], 0) if opening else PickTargets(Live, only_addressed=bool(State.get("forced")), most=Most, handled=Handled)
        if not opening and not Targets:
            return  # nothing new for her (never twice in a row without an answer)
        Ids = {L.get("id") for L in Live if L.get("id")}
        self.handled[guild.id] = (Handled & Ids) | Ids  # everything up to now is dealt with (answered or left for "the rest")
        Addressed = bool(Targets) and bool(Targets[0].get("to_loji"))
        WokeAt = (self.state.get(guild.id) or {}).get("woke_at") or Now()
        Past = await Db()[LOG].find({"guild_id": guild.id, "at": {"$lt": WokeAt}}).sort("at", -1).to_list(length=40)
        Present = {L["author_id"] for L in Live if L.get("author_id")}
        Notes = await Db()[NOTES].find({"guild_id": guild.id, "user_id": {"$in": list(Present)}}).sort("at", -1).to_list(length=30)
        System, User = BuildPrompt(Personality, [{"name": N["name"], "text": N["text"]} for N in Notes], list(reversed(Past)), Live,
                                   int(s["context_tokens"]), guild.name, opening, Targets)
        try:
            Text, _ = await Complete(Key, System, User, max_tokens=1500, json_mode=True, temperature=1.0,  # chatting: livelier
                                     model=Doc.get("ai_model"))
            Answer = ParseReply(Text, most=len(Targets) if Addressed else 1)
        except (GuideError, ValueError) as e:
            return logger.warning(f"[LojiChat] {guild.id}: {e}")
        if not (self.state.get(guild.id) or {}).get("awake"):
            return  # the chat filled up while she was thinking
        Trolls = {}
        if s.get("antitroll", True):
            for Name in Answer["trolls"]:
                Last = next((L for L in reversed(Live) if L["author"] != "LOJI" and L["author"].lower() == Name.lower() and L.get("id")), None)
                if Last:
                    Trolls[Last["author_id"]] = Last
        if Addressed:  # one message for each person who talked to her, in order
            Outgoing = list(zip(Answer["messages"], Targets))
        else:  # nobody spoke to her: she picks who to answer (or the whole chat)
            I = Answer["reply_to"]
            Chosen = Live[I] if I is not None and 0 <= I < len(Live) else None
            Outgoing = [(M, Chosen if Chosen and Chosen["author"] != "LOJI" and Chosen.get("id") else None) for M in Answer["messages"][:1]]
        Outgoing = [(M, T) for M, T in Outgoing if not (T and T.get("author_id") in Trolls)]  # no normal answer for them
        for Line in Trolls.values():
            await self.Troll(guild, channel, s, Line, "insultos o acoso a LOJI (según la IA)")
        if Outgoing and Rest:  # more people tagged her than she answers
            Phrase = RestPhrase(s, self.used_phrases.setdefault(guild.id, []), random)
            if Phrase:
                Outgoing.append((Phrase, None))
        for I, (Message, Target) in enumerate(Outgoing):
            async with channel.typing():
                await asyncio.sleep(min(1.5 + len(Message) / 25, 7) if I == 0 else min(1 + len(Message) / 30, 4))
            if not await self.Send(channel, Message, Target):
                break
            Line = {"author": "LOJI", "author_id": self.client.user.id, "content": Message}
            self.live.setdefault(guild.id, deque(maxlen=LIVE)).append(Line)
            await self.Remember(guild.id, Line)
            await Db()["lojichat_usage"].update_one({"_id": f"{guild.id}:{Now():%Y-%m-%d}"}, {"$inc": {"n": 1}}, upsert=True)
            self.last_reply[guild.id] = Now()
        await self.Note(guild.id, Answer["notes"], Live)
        if Answer["alert"]:
            await self.Alert(guild, channel, s, Answer["alert"], Live)

    # ---------------- anti-troll ----------------

    async def Troll(self, guild: discord.Guild, channel, s: dict, line: dict, why: str):
        """Spam or insults aimed at her: a warning the first time; if they keep going, reported to staff and ignored."""
        from core.lojichat_phrases import REPORTED_PHRASES, WARN_PHRASES

        What = Strike(self.trolls.setdefault((guild.id, line["author_id"]), {}), Now(), s)
        if What == "ignore":
            return
        Phrase = PickFresh(WARN_PHRASES if What == "warn" else REPORTED_PHRASES, self.used_phrases.setdefault(f"{guild.id}:{What}", []), random)
        if await self.Send(channel, Phrase, line):
            Said = {"author": "LOJI", "author_id": self.client.user.id, "content": Phrase}
            self.live.setdefault(guild.id, deque(maxlen=LIVE)).append(Said)
            await self.Remember(guild.id, Said)
        if What == "report":
            try:
                await self.TrollReport(guild, channel, s, line, why)
            except Exception as e:
                logger.warning(f"[LojiChat] Troll report failed in {guild.id}: {e!r}")

    async def TrollReport(self, guild: discord.Guild, channel, s: dict, line: dict, why: str):
        """The quick-report card (same buttons), sent by LOJI herself, without a ping."""
        from cogs.Modules.Guide.autoreport import REPORTS, CardView, Config, Quote
        from core.economy.shop import NewId

        _, R = await Config(guild.id)
        Staff = guild.get_channel(R.get("staff_channel") or 0) or guild.get_channel(s.get("alert_channel") or 0)
        if not Staff:
            return logger.warning(f"[LojiChat] No staff channel for troll reports in {guild.id}")
        Theirs = [L for L in (self.live.get(guild.id) or []) if L.get("author_id") == line["author_id"]][-8:] or [line]
        Jump = f"https://discord.com/channels/{guild.id}/{channel.id}/{line['id']}"
        Member = guild.get_member(line["author_id"])
        Report = {
            "_id": NewId(8), "guild_id": guild.id, "message_id": line["id"], "channel_id": channel.id, "jump": Jump,
            "author_id": line["author_id"], "author_name": line["author"], "reporters": [self.client.user.id],
            "at": Now(), "status": None, "verdict": None, "ai": False, "note": why, "source": "lojichat",
        }
        embed = discord.Embed(title="🤖 LOJI: me están molestando", url=Jump, color=LOJI_RED, timestamp=Now())
        embed.set_author(name=f"{line['author']} ({line['author_id']})", icon_url=Member.display_avatar.url if Member else None)
        embed.description = Quote("\n".join(L["content"][:200] for L in Theirs), 1500) + f"\n\n🔗 [Ir al último mensaje]({Jump}) · {channel.mention}"
        embed.add_field(name="⚠️ Motivo", value=why[:1024], inline=False)
        embed.add_field(name="📋 Qué pasó", value=f"LOJI le avisó y siguió en menos de {s['troll_followup']} min. "
                                                    f"Lo ignora durante {s['troll_ignore']} min.", inline=False)
        embed.set_footer(text=f"Reportado por LOJI · revisa el contexto · ID {Report['_id']}", icon_url=guild.me.display_avatar.url if guild.me else None)
        await Db()[REPORTS].insert_one(Report)
        Sent = await Staff.send(embed=embed, view=CardView(Report["_id"]), allowed_mentions=discord.AllowedMentions.none())
        await Db()[REPORTS].update_one({"_id": Report["_id"]}, {"$set": {"card": {"channel": Staff.id, "id": Sent.id}}})

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
            self.batches.pop(guild.id, None)
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
        Rest = s.get("rest_text", "")
        self.text = Field("Lo que dice al irse (vacío = nada)", s["goodbye"], 300, required=False)
        self.rest = Field("Frases si la etiquetan muchos", "" if Rest == OLD_REST else Rest, 4000, required=False,
                          placeholder="Vacío = las 110 frases de LOJI · «nada» = no decir nada · o las tuyas, una por línea")
        self.most = Field("A cuántos responde por tanda (ej. 4-6)", f"{s.get('min_answers', 4)}-{s.get('max_answers', 6)}", 5, long=False, required=True)
        self.ignore = Field("% de veces que ignora al resto (0-100)", str(s.get("rest_ignore", 33)), 3, long=False, required=True)
        for Item in (self.text, self.rest, self.most, self.ignore):
            self.add_item(Item)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            Parts = [int(P) for P in self.most.value.replace(" ", "").split("-")]
            Low, High = (Parts[0], Parts[-1]) if len(Parts) in (1, 2) else (0, 0)
            Ignore = int(self.ignore.value)
            assert 1 <= Low <= High <= 8 and 0 <= Ignore <= 100
        except (ValueError, AssertionError):
            return await interaction.response.send_message("❌ «A cuántos» va de 1 a 8 (por ejemplo `4-6` o `3`) y el % de 0 a 100.", ephemeral=True)
        await Community().Set(interaction.guild.id, "lojichat", {"goodbye": self.text.value.strip(), "rest_text": self.rest.value.strip(),
                                                                 "min_answers": Low, "max_answers": High, "rest_ignore": Ignore})
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
