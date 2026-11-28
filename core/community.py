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


COIN = "<:ESS_moneda:1573482755088711700>"

BOARD = {
    "channel": None,
    "message_id": None,
    "banner": "https://cdn.imgchest.com/files/e4a582843fbf.png",
    "title": "## " + COIN + " Misiones del {server}",
    "description": "Cumple los objetivos, pulsa **Cobrar** y las monedas son tuyas. Las diarias se renuevan cada noche.",
    "footer": (
        "-# 🔄 Las diarias vuelven a las 00:00 · 🎙️ La voz cuenta sin mute ni ensordecer, fuera del AFK y acompañado · "
        "🏷️ El tag y el boost se cobran una sola vez por cuenta."
    ),
    "color": "#BBA896",
    "coin": COIN,  # next to each reward and on the buttons
    "claim_label": "Cobrar",
    "progress_label": "Mi progreso",
}

# "🪄 Misiones de ejemplo" in the board panel creates these (only the ones not there yet, by name).
EXAMPLE_QUESTS = [
    {"name": "Enviar 25 mensajes", "period": "daily", "objective": "messages", "target": 25, "reward": 250},
    {"name": "Pasar 15 minutos en voz", "period": "daily", "objective": "voice", "target": 15, "reward": 300},
    {"name": "Llevar nuestro tag", "period": "once", "objective": "supporter", "target": 1, "reward": 250},
    {"name": "Boostear el servidor", "period": "once", "objective": "boost", "target": 1, "reward": 1000},
]

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

BOOST = {
    "enabled": False,
    "channel": None,
    "title": "### {user} acaba de boostear {server}!",
    "intro": "-# 💎 Booster desde {fecha}",
    "benefits": (
        "🔓 __**Ventajas desbloqueadas**__\n"
        "🪙 **{multiplicador}** en todo lo que ganas en la economía\n"
        "🍀 **{suerte}** de suerte en el gacha"
    ),
    "note": "",
    "footer": "-# 🎁 Ya tienes {premio} en tu cuenta. ¡Gracias por apoyar {server}! 💜",
    "color": "#F47FFF",
    "thumbnail": "avatar",
    "buttons": "Cobrar misiones | 🪙 | {tareas_link}",
    "json": "",  # when set, the card is this Components V2 JSON (with {variables}) instead of the simple design
    "json_name": "",
}
BOOST_VARS = "`{user}` `{nombre}` `{avatar}` `{server}` `{fecha}` `{boosts}` `{multiplicador}` `{suerte}` `{premio}` `{tareas}` `{tareas_link}`"
BOOST_SEEN = "boost_cards"  # one card per boost (same start time = same boost)

JOIN = {
    "enabled": False,
    "channel": None,
    "title": "### ¡Te damos la bienvenida a {server}, {user}!",
    "intro": "-# 👋 Eres el miembro **#{numero}**",
    "benefits": (
        "✨ __**Para empezar**__\n"
        "📜 Lee las **normas** para saber cómo funciona todo\n"
        "🎭 Elige tus **roles** para ver lo que te interesa\n"
        "💬 Saluda en el **chat general**: ¡te estamos esperando!"
    ),
    "note": "",
    "footer": "-# 🌙 Esperamos que disfrutes tu estancia en {server}.",
    "color": "#BBA896",
    "thumbnail": "avatar",
    "buttons": "",
    "json": "",
    "json_name": "",
}
JOIN_VARS = "`{user}` `{nombre}` `{avatar}` `{server}` `{numero}` `{miembros}` `{creada}` `{fecha}` `{tareas}` `{tareas_link}`"
JOIN_SEEN = "join_cards"
JOIN_COOLDOWN_HOURS = 24  # someone who leaves and comes back isn't welcomed again for a day (join/leave spam)

SECTIONS = {"welcome": WELCOME, "board": BOARD, "overflow": OVERFLOW, "boost": BOOST, "join": JOIN}


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


# ---------------- Components V2 from JSON (boost card "modo JSON") ----------------

ALLOWED_TYPES = {1: "fila", 2: "botón", 9: "sección", 10: "texto", 11: "miniatura", 12: "galería", 14: "separador", 17: "contenedor"}
MAX_COMPONENTS = 40
MAX_TEXT = 4000


def ParseCardJson(text: str) -> list[dict]:
    """The components of a pasted/uploaded Components V2 message. Raises ValueError with a message for the admin.
    Accepts {"components": [...]}, a whole message ({"flags": 32768, "components": [...]}) or just the list."""
    import json

    try:
        Data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"No es un JSON válido (línea {e.lineno}, columna {e.colno}: {e.msg}).")
    Components = Data.get("components") if isinstance(Data, dict) else Data
    if not isinstance(Components, list) or not Components:
        raise ValueError("No encuentro la lista `components`.")
    if isinstance(Data, dict) and (Data.get("embeds") or Data.get("content")):
        raise ValueError("Con Components V2 no puede haber `content` ni `embeds`: pon el texto en componentes de texto (tipo 10).")
    Count, Text = 0, 0

    def Walk(items, where):
        nonlocal Count, Text
        for Item in items:
            if not isinstance(Item, dict) or Item.get("type") not in ALLOWED_TYPES:
                Kind = Item.get("type") if isinstance(Item, dict) else Item
                raise ValueError(f"Tipo de componente no permitido en {where}: `{Kind}`. Solo: " + ", ".join(f"{K} ({V})" for K, V in ALLOWED_TYPES.items()) + ".")
            Count += 1
            if Item["type"] == 2 and Item.get("style") != 5:
                raise ValueError("Solo se permiten botones de **enlace** (style 5 con `url`): los demás no harían nada.")
            if Item["type"] == 10:
                Text += len(str(Item.get("content", "")))
            if Item.get("accessory"):
                Walk([Item["accessory"]], "un accesorio")
            Walk(Item.get("components") or [], ALLOWED_TYPES[Item["type"]])

    Walk(Components, "el mensaje")
    if Count > MAX_COMPONENTS:
        raise ValueError(f"Tiene {Count} componentes; Discord permite {MAX_COMPONENTS}.")
    if Text > MAX_TEXT:
        raise ValueError(f"Tiene {Text} caracteres de texto; Discord permite {MAX_TEXT}.")
    return Components


def FillJson(value, values: dict):
    """Replaces {variables} inside every text of the JSON (not in the keys)."""
    if isinstance(value, str):
        return Fill(value, values)
    if isinstance(value, list):
        return [FillJson(V, values) for V in value]
    if isinstance(value, dict):
        return {K: FillJson(V, values) for K, V in value.items()}
    return value


# ---------------- booster icon panels ----------------

ICON_PANELS = "icon_panels"
BOOSTERS = "boosters"  # who LOJI knows is boosting (to notice boosts lost while it was offline)
ICONS = {
    "heading": "### Iconos · {n}/{total}",
    "log": None,
    "ready": False,  # LOJI has learned who boosts (the first check does it quietly)
}
MAX_ICONS = 5
PANEL_DEFAULTS = {
    "banner": "",
    "text": "## 🚀 Iconos Boosters\nApoya al servidor boosteándolo y desbloquea roles exclusivos con iconografía especial para destacar tu perfil.\nSolo {booster} puede elegirlos.",
    "footer": "-# Puedes tener un icono de toda la colección a la vez y cambiarlo cuando quieras. Si dejas de boostear, tu icono se retirará automáticamente.",
    "color": "#C9C9D1",
}
SECTIONS["icons"] = ICONS


def IconSwap(member_role_ids: set[int], icon_role_ids: set[int], clicked: int) -> tuple[set[int], set[int], str]:
    """(roles to add, roles to remove, what happened: "removed" | "added" | "swapped").
    Only one icon at a time across every panel; clicking the one you wear takes it off."""
    Wearing = member_role_ids & icon_role_ids
    if clicked in Wearing:
        return set(), {clicked}, "removed"
    return {clicked}, Wearing, "swapped" if Wearing else "added"


def BoostChanges(known: set[int], current: set[int]) -> tuple[set[int], set[int]]:
    """(new boosters, boosters who stopped) between what LOJI remembered and who boosts now."""
    return current - known, known - current


# ---------------- booster gradient colors ----------------

MAX_COLORS = 20  # 4 rows of 5 buttons (+ the ✖ one) keep the message within Discord's 40 components
COLORS = {
    "banner": "https://cdn.imgchest.com/files/e8f7a1c79afd.png",
    "title": "## <:ESS_pin_jap:1573211465580814336> Colores Boosters",
    "text": "Un degradado exclusivo para quienes boostean **{server}** ✦\n-# Elige el tuyo y lúcelo en tu nombre.",
    "heading": "### <:ESS_texto:1573224502534348923> Colección · {total} degradados",
    "footer": "-# ✦ Un degradado a la vez: pulsa otro para cambiarlo o el tuyo para quitarlo. Si dejas de boostear, se retira solo ✦",
    "color": "#BBA896",
    "roles": [],  # in panel order
    "channel": None,
    "message_id": None,
}
COLOR_EMOJIS = "color_emojis"  # role id -> the bot emoji made from its gradient
SECTIONS["colors"] = COLORS


def ColorKey(first: int, second: int | None) -> str:
    """Identifies a gradient: when the role's colors change, its emoji is redrawn."""
    return f"{first:06x}-{(second if second is not None else first):06x}"


# ---------------- events (Crecimiento y Entretenimiento) ----------------
from core.events import SETTINGS as _EVENT_SETTINGS  # noqa: E402

SECTIONS["events"] = _EVENT_SETTINGS
