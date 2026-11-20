"""
Community (/config → Comunidad): three customizable pieces, each in its own section of one document.

- welcome:  the "thanks for supporting us" card sent when someone starts wearing the tag or the vanity
            (configured from /config → Vanity y tag, which is the one supporters system).
- board:    the public missions board (banner, one row per mission with a "Reclamar" button, "Ver mi progreso").
- overflow: a second general chat that opens when the main one is packed and closes when it goes quiet.

The texts are plain Discord markdown with {variables}; nothing here touches Discord, so it's easy to test.
"""

import re
import time

COLLECTION = "community_config"
CACHE_SECONDS = 30
MAX_BOARD_QUESTS = 8  # Discord allows 40 components per message; each mission row uses 4 (with its divider)
MAX_BUTTONS = 3

WELCOME = {
    # One card per reason: "title/intro/note" when they wear the TAG, "*_vanity" when they put the vanity in their status.
    # Wearing both gives nothing extra (they get the TAG card).
    "title": "### Gracias por apoyarnos {user}!",
    "intro": "🌴 Se te otorgó el rol {rol} como recompensa\nℹ️ Te has **equipado** nuestro **TAG**!",
    "note": "-# Los mismos beneficios si llevas {vanity} en tu estado (vanity).",
    "title_vanity": "### Gracias por apoyarnos {user}!",
    "intro_vanity": "🌴 Se te otorgó el rol {rol} como recompensa\nℹ️ Has puesto nuestra **vanity** {vanity} en tu estado!",
    "note_vanity": "-# Los mismos beneficios si te equipas nuestro **TAG**.",
    # Shared by both cards.
    "benefits": (
        "🏆 **Beneficios** · TAG & VANITY\n"
        "💎 **Rol destacado** arriba de los boosters\n"
        "🖼️ **/avatar** obtén el avatar de otros usuarios\n"
        "🛡️ **Inmunidad** al modo pausa\n"
        "😀 **Emojis y stickers** externos\n"
        "⚡ **+20 %** de XP en niveles de voz y texto"
    ),
    "footer": "-# 🪙 Reclama tus monedas en {tareas} o con **/misiones** (una sola vez por cuenta). Mantén la etiqueta activa para conservar el rol y sus ventajas.",
    "color": "#5865F2",
    "thumbnail": "avatar",  # avatar | servidor | ninguna | an image URL
    # One per line: "label | emoji | where" (where = a link, or #channel-id / a channel mention).
    "buttons": "Reclamar monedas | 🪙 | {tareas_link}\nContactar con staff | 🎟️ |",
}
VARIANT_KEYS = ("title", "intro", "note")


def Variant(settings: dict, tag: bool) -> dict:
    """The welcome card settings for one reason: the TAG texts, or the vanity ones."""
    if tag:
        return dict(settings)
    return {**settings, **{K: settings[f"{K}_vanity"] for K in VARIANT_KEYS}}


BOARD = {
    "channel": None,
    "message_id": None,
    "banner": "",
    "title": "## 🪙 Tareas diarias · {server}",
    "description": "Participa, completa tus objetivos y reclama tus monedas.",
    "footer": (
        "-# Mensajes y voz se reinician cada día a las 00:00. Voz: sin mute/deafen, fuera de AFK y con otra persona. "
        "El TAG y el boost solo se pagan una vez, aunque los quites y vuelvas a poner."
    ),
    "color": "#57F287",
}

OVERFLOW = {
    "enabled": False,
    "main": None,  # the busy general chat
    "extra": None,  # the chat that opens
    "mode": "lock",  # lock: visible but read-only when closed · hide: hidden when closed
    "role": None,  # who gets to write when open (None = @everyone)
    "open_messages": 30,  # this many messages in the main chat...
    "open_seconds": 60,  # ...within this many seconds...
    "open_authors": 4,  # ...from at least this many people opens it
    "idle_minutes": 10,  # closes when, in the last X minutes...
    "close_below": 5,  # ...the extra chat had fewer than this many messages
    "min_open_minutes": 15,  # never closes sooner than this after opening
    "warn_seconds": 60,
    "notice_main": True,  # also say in the main chat that the extra one opened
    "text_open": "🟢 Chat abierto\nSe ha abierto por la actividad de {principal}. ¡Bienvenidos!",
    "text_warn": "⏳ En 1 minuto cerraremos este chat\nHay poca actividad. Seguid la conversación en {principal} 💬",
    "text_close": "🔒 Chat cerrado\n¡Gracias! Nos vemos en {principal}. Se volverá a abrir si el chat se llena.",
    "text_main": "📢 Hay mucha gente hablando\n{extra} está abierto: ¡pasaos para que se pueda leer todo!",
    # state
    "is_open": False,
    "opened_at": None,
    "warned_at": None,
}

SECTIONS = {"welcome": WELCOME, "board": BOARD, "overflow": OVERFLOW}


class Community:
    def __init__(self, db):
        self.col = db[COLLECTION]
        self._cache: dict[int, tuple[float, dict]] = {}

    async def Get(self, guild_id: int) -> dict:
        Cached = self._cache.get(guild_id)
        if Cached and Cached[0] > time.monotonic():
            return Cached[1]
        Doc = await self.col.find_one({"_id": guild_id}) or {}
        Config = {Name: {**Defaults, **(Doc.get(Name) or {})} for Name, Defaults in SECTIONS.items()}
        self._cache[guild_id] = (time.monotonic() + CACHE_SECONDS, Config)
        return Config

    async def Set(self, guild_id: int, section: str, changes: dict) -> dict:
        await self.col.update_one({"_id": guild_id}, {"$set": {f"{section}.{K}": V for K, V in changes.items()}}, upsert=True)
        self._cache.pop(guild_id, None)
        return await self.Get(guild_id)

    async def Reset(self, guild_id: int, section: str, keys: list[str]):
        await self.col.update_one({"_id": guild_id}, {"$unset": {f"{section}.{K}": "" for K in keys}})
        self._cache.pop(guild_id, None)


_store: Community | None = None


def Store() -> Community:
    global _store
    if _store is None:
        from core.db import db

        _store = Community(db)
    return _store


# ---------------- helpers (pure) ----------------


def Fill(text: str, values: dict) -> str:
    for K, V in values.items():
        text = text.replace("{" + K + "}", str(V))
    return text


def Color(value: str, fallback: int = 0x5865F2) -> int:
    Match = re.fullmatch(r"#?([0-9a-fA-F]{6})", (value or "").strip())
    return int(Match.group(1), 16) if Match else fallback


def ValidColor(value: str) -> bool:
    return bool(re.fullmatch(r"#?[0-9a-fA-F]{6}", (value or "").strip()))


def DropLinesWithEmpty(text: str, values: dict) -> str:
    """Lines whose variable has no value are left out (e.g. 'Se te otorgó el rol {rol}' with no role)."""
    Kept = []
    for Line in text.split("\n"):
        if any("{" + K + "}" in Line and not V for K, V in values.items()):
            continue
        Kept.append(Line)
    return "\n".join(Kept)


def ParseButtons(text: str) -> list[dict]:
    """'Etiqueta | emoji | destino' per line -> [{label, emoji, target}] (at most MAX_BUTTONS)."""
    Buttons = []
    for Line in (text or "").splitlines():
        if not Line.strip():
            continue
        Parts = [P.strip() for P in Line.split("|")] + ["", ""]
        Label, Emoji, Target = Parts[0][:80], Parts[1][:60], Parts[2]
        if Label:
            Buttons.append({"label": Label, "emoji": Emoji or None, "target": Target})
    return Buttons[:MAX_BUTTONS]


def ChannelId(target: str) -> int | None:
    Match = re.fullmatch(r"<?#?(\d{15,21})>?", (target or "").strip())
    return int(Match.group(1)) if Match else None


def ButtonUrl(target: str, guild_id: int) -> str | None:
    """A link button needs a URL: channel ids become channel links; anything else must be http(s)."""
    Target = (target or "").strip()
    Channel = ChannelId(Target)
    if Channel:
        return f"https://discord.com/channels/{guild_id}/{Channel}"
    return Target if re.match(r"https?://\S+$", Target) else None


def Title(text: str) -> tuple[str, str]:
    """'First line = title\\nrest = text' -> (title, text)."""
    Head, _, Rest = (text or "").partition("\n")
    return Head.strip(), Rest.strip()


# ---------------- overflow chat (pure decisions) ----------------


class Traffic:
    """Recent messages in the main chat (in memory): enough to know when it's packed."""

    def __init__(self):
        self.messages: dict[int, list[tuple[float, int]]] = {}

    def Add(self, channel_id: int, author_id: int, now: float, keep_seconds: int):
        List = self.messages.setdefault(channel_id, [])
        List.append((now, author_id))
        Cut = now - keep_seconds
        while List and List[0][0] < Cut:
            List.pop(0)

    def Busy(self, channel_id: int, now: float, settings: dict) -> bool:
        Cut = now - int(settings["open_seconds"])
        Recent = [(T, A) for T, A in self.messages.get(channel_id, []) if T >= Cut]
        return len(Recent) >= int(settings["open_messages"]) and len({A for _, A in Recent}) >= int(settings["open_authors"])


def CloseStep(settings: dict, now: float, extra_messages: int, opened_at: float | None, warned_at: float | None,
              since_warning: int) -> str | None:
    """What to do with an open extra chat: "warn", "close", "cancel" (activity came back) or None.

    extra_messages: messages in the extra chat during the last idle_minutes.
    since_warning:  messages in the extra chat since the warning was posted.
    """
    if warned_at:
        if since_warning >= max(2, int(settings["close_below"]) // 2):
            return "cancel"
        return "close" if now - warned_at >= int(settings["warn_seconds"]) else None
    if opened_at and now - opened_at < int(settings["min_open_minutes"]) * 60:
        return None
    return "warn" if extra_messages < int(settings["close_below"]) else None
