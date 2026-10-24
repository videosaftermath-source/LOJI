"""Economy defaults and limits. Everything here can be overridden per guild in eco_config."""

from dataclasses import dataclass

MODULE = "Economy"

# Collections
USERS = "eco_users"
CONFIG = "eco_config"
LEDGER = "eco_ledger"

# Ledger kinds: money entering the economy, leaving it, or moving between users.
CREATED = "created"
DESTROYED = "destroyed"
TRANSFER = "transfer"

HOUR = 3600
DAY = 24 * HOUR

DEFAULT_CONFIG: dict = {
    "currency": {"name": "Créditos", "emoji": "🪙"},
    "work": {"min": 50, "max": 150, "cooldown": HOUR},
    "daily": {
        "base": 200,
        "streak_bonus": 25,
        "max_streak_days": 7,
        "cooldown": 20 * HOUR,
        "grace": 48 * HOUR,
    },
    "transfer": {"min": 10, "fee_percent": 7.0},
    "leaderboard": {"page_size": 10},
    "activity": {
        "channels": [],
        "min_balance": 250,
        "min": 5,
        "max": 15,
        "cooldown": 60,
        "min_length": 8,
        "similarity": 0.85,
        "history": 5,
        "flood_count": 6,
        "flood_window": 10,
        "max_strikes": 4,
        "strike_window": 600,
        "block": 30 * 60,
        "soft_cap": 600,
        "hard_cap": 1000,
        "diminish": 0.5,
        "streak_messages": 10,
        "streak_step": 0.05,
        "max_multiplier": 1.5,
        "utc_offset": -5,
        "react_streak": True,
    },
    "voice": {"enabled": False, "per_minute": 2, "daily_cap": 300, "min_members": 2},
}

# How often voice time is paid (the task interval).
VOICE_TICK_MINUTES = 5

# How long the chat listener remembers whether someone can earn (saves DB reads on every message).
ELIGIBILITY_CACHE_SECONDS = 300
MODULE_CACHE_SECONDS = 60


@dataclass(frozen=True)
class Setting:
    """An admin-editable config value."""

    section: str
    path: str
    label: str
    kind: type
    minimum: float = 0
    maximum: float = 0
    help: str = ""


SECTIONS = {
    "general": "💳 General y pagos",
    "work": "💼 Trabajar y diario",
    "activity": "💬 Pago por chat",
    "antispam": "🛡️ Anti-spam",
    "voice": "🔊 Pago por voz",
}

SETTINGS: list[Setting] = [
    Setting("general", "currency.name", "Nombre de la moneda", str, 1, 32),
    Setting("general", "currency.emoji", "Emoji de la moneda", str, 1, 64),
    Setting("general", "transfer.min", "Pagar: mínimo", int, 1, 1_000_000),
    Setting("general", "transfer.fee_percent", "Pagar: comisión (%)", float, 0, 50,
            "Lo paga quien envía, encima de la cantidad. Se destruye."),
    Setting("general", "leaderboard.page_size", "Top: usuarios por página", int, 5, 25),
    Setting("work", "work.min", "Trabajar: mínimo", int, 0, 1_000_000),
    Setting("work", "work.max", "Trabajar: máximo", int, 0, 1_000_000),
    Setting("work", "work.cooldown", "Trabajar: espera (segundos)", int, 0, 7 * DAY),
    Setting("work", "daily.base", "Diario: base", int, 0, 1_000_000),
    Setting("work", "daily.streak_bonus", "Diario: extra por día de racha", int, 0, 1_000_000),
    Setting("work", "daily.max_streak_days", "Diario: racha máxima que suma", int, 1, 365),
    Setting("work", "daily.cooldown", "Diario: espera (segundos)", int, HOUR, 7 * DAY),
    Setting("work", "daily.grace", "Diario: tiempo antes de perder racha (s)", int, HOUR, 14 * DAY,
            "Debe ser mayor que la espera del diario."),
    Setting("activity", "activity.min_balance", "Saldo mínimo para ganar por chat", int, 0, 10_000_000,
            "Quien tenga menos no gana por chat (ni gasta recursos del bot)."),
    Setting("activity", "activity.min", "Por mensaje: mínimo", int, 0, 100_000),
    Setting("activity", "activity.max", "Por mensaje: máximo", int, 0, 100_000),
    Setting("activity", "activity.cooldown", "Espera entre pagos (segundos)", int, 5, DAY),
    Setting("activity", "activity.soft_cap", "Tope diario suave", int, 0, 10_000_000,
            "Pasado este tope se paga menos."),
    Setting("activity", "activity.diminish", "Multiplicador tras tope suave (0-1)", float, 0, 1),
    Setting("activity", "activity.hard_cap", "Tope diario máximo", int, 0, 10_000_000),
    Setting("activity", "activity.streak_messages", "Racha: mensajes pagados por día", int, 1, 1000),
    Setting("activity", "activity.streak_step", "Racha: extra por día (0.05 = +5%)", float, 0, 1),
    Setting("activity", "activity.max_multiplier", "Racha: multiplicador máximo", float, 1, 10),
    Setting("activity", "activity.utc_offset", "Zona horaria (UTC, ej. -5)", int, -12, 14,
            "A qué hora cambia el día para las rachas."),
    Setting("activity", "activity.react_streak", "Reaccionar 🔥 al cumplir la racha", bool),
    Setting("antispam", "activity.min_length", "Longitud mínima (letras/números)", int, 1, 200),
    Setting("antispam", "activity.similarity", "Parecido para contar repetido (0-1)", float, 0.5, 1),
    Setting("antispam", "activity.history", "Mensajes recientes a comparar", int, 1, 20),
    Setting("antispam", "activity.flood_count", "Flood: mensajes...", int, 2, 50),
    Setting("antispam", "activity.flood_window", "...en estos segundos", int, 1, 120),
    Setting("antispam", "activity.max_strikes", "Avisos antes de bloquear", int, 1, 50),
    Setting("antispam", "activity.strike_window", "Ventana de avisos (segundos)", int, 10, DAY),
    Setting("antispam", "activity.block", "Duración del bloqueo (segundos)", int, 10, 7 * DAY),
    Setting("voice", "voice.enabled", "Pagar por estar en voz", bool),
    Setting("voice", "voice.per_minute", "Créditos por minuto", int, 0, 10_000),
    Setting("voice", "voice.daily_cap", "Tope diario por voz", int, 0, 10_000_000),
    Setting("voice", "voice.min_members", "Mínimo de personas en el canal", int, 1, 25),
]

SETTINGS_BY_PATH = {S.path: S for S in SETTINGS}

WORK_LINES = [
    "Repartiste pizzas bajo la lluvia",
    "Le arreglaste el WiFi a tu abuela",
    "Paseaste a 7 perros a la vez",
    "Vendiste stickers en la puerta del colegio",
    "Hiciste de extra en una telenovela",
    "Moderaste un chat lleno de bots",
    "Lavaste platos en un restaurante de dudosa reputación",
    "Fuiste DJ en un cumpleaños infantil",
    "Le hiciste la tarea al primo",
    "Cuidaste el puesto de empanadas",
]
