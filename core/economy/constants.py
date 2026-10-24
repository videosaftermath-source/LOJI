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
    "transfer": {"min": 10},
    "leaderboard": {"page_size": 10},
}


@dataclass(frozen=True)
class Setting:
    """An admin-editable config value."""

    path: str
    label: str
    kind: type
    minimum: float
    maximum: float
    help: str = ""


SETTINGS: list[Setting] = [
    Setting("currency.name", "Nombre de la moneda", str, 1, 32),
    Setting("currency.emoji", "Emoji de la moneda", str, 1, 64),
    Setting("work.min", "Trabajar: mínimo", int, 0, 1_000_000),
    Setting("work.max", "Trabajar: máximo", int, 0, 1_000_000),
    Setting("work.cooldown", "Trabajar: espera (segundos)", int, 0, 7 * DAY),
    Setting("daily.base", "Diario: base", int, 0, 1_000_000),
    Setting("daily.streak_bonus", "Diario: extra por día de racha", int, 0, 1_000_000),
    Setting("daily.max_streak_days", "Diario: racha máxima que suma", int, 1, 365),
    Setting("daily.cooldown", "Diario: espera (segundos)", int, HOUR, 7 * DAY),
    Setting("daily.grace", "Diario: tiempo antes de perder racha (s)", int, HOUR, 14 * DAY,
            "Debe ser mayor que la espera del diario."),
    Setting("transfer.min", "Pagar: mínimo", int, 1, 1_000_000),
    Setting("leaderboard.page_size", "Top: usuarios por página", int, 5, 25),
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
