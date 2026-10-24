"""Economy defaults and limits. Everything here can be overridden per guild in eco_config."""

from dataclasses import dataclass

MODULE = "Economy"

# Collections
USERS = "eco_users"
CONFIG = "eco_config"
LEDGER = "eco_ledger"
ITEMS = "eco_items"
INVENTORY = "eco_inventory"
EFFECTS = "eco_effects"
CODES = "eco_codes"
CODE_USES = "eco_code_uses"
QUESTS = "eco_quests"
QUEST_PROGRESS = "eco_quest_progress"
SPECIES = "eco_pet_species"
PETS = "eco_pets"
BANNERS = "eco_banners"
PITY = "eco_pity"
PULLS = "eco_pulls"

# Discord select menus hold at most 25 options, so these are capped there.
MAX_ITEMS = 25
MAX_CODES = 25
MAX_QUESTS = 25
MAX_BUY_AT_ONCE = 100
MAX_SPECIES = 25
MAX_PETS = 25
MAX_BANNERS = 25
MAX_POOL = 25
PULL_HISTORY_DAYS = 90

# Item types
ROLE = "role"
CONSUMABLE = "consumable"
COLLECTIBLE = "collectible"
ITEM_TYPES = {ROLE: "🎭 Rol", CONSUMABLE: "🧪 Consumible", COLLECTIBLE: "💎 Coleccionable"}

# What a consumable boosts (also used by pets later)
BOOSTS = {
    "work": "💼 Ganancias de /trabajar",
    "daily": "🎁 Ganancias de /diario",
    "chat": "💬 Ganancias por chatear",
}

# Quest objectives
OBJECTIVES = {
    "messages": "💬 Mensajes pagados en el chat",
    "work": "💼 Veces usando /trabajar",
    "daily": "🎁 Veces reclamando /diario",
    "spend": "🛒 Créditos gastados en la tienda",
    "buy": "📦 Items comprados",
    "pay": "💸 Créditos enviados con /pagar",
    "play": "🎲 Partidas jugadas (casino)",
    "gacha": "🎰 Tiradas en el gacha",
}
QUEST_PERIODS = {"daily": "📅 Diaria", "weekly": "🗓️ Semanal", "once": "⭐ Única"}

# Rarities (shared with the gacha). Perk = base + per_level * (level - 1).
RARITIES = {
    "common": {"label": "Común", "stars": "⭐", "color": 0x95A5A6, "base": 0.03, "per_level": 0.003},
    "rare": {"label": "Rara", "stars": "⭐⭐", "color": 0x3498DB, "base": 0.05, "per_level": 0.005},
    "epic": {"label": "Épica", "stars": "⭐⭐⭐", "color": 0x9B59B6, "base": 0.08, "per_level": 0.007},
    "legendary": {"label": "Legendaria", "stars": "⭐⭐⭐⭐", "color": 0xF1C40F, "base": 0.12, "per_level": 0.010},
}

# Pet archetypes: which bonus they give, and how strong compared to the rarity table.
ARCHETYPES = {
    "farmer": {"label": "🌾 Farmeador", "bonus": "work", "scale": 1.0, "perk": "extra en /trabajar"},
    "talker": {"label": "🗣️ Charlatán", "bonus": "chat", "scale": 1.0, "perk": "extra por chatear"},
    "lucky": {"label": "🍀 Suertudo", "bonus": "luck", "scale": 0.4, "perk": "más suerte en el casino"},
    "saver": {"label": "💰 Ahorrador", "bonus": "discount", "scale": 0.6, "perk": "de descuento en tienda y comisiones"},
}

# Ledger kinds: money entering the economy, leaving it, or moving between users.
CREATED = "created"
DESTROYED = "destroyed"
TRANSFER = "transfer"
BET = "bet"  # casino: money in
PAYOUT = "payout"  # casino: money out

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
    "bonuses": {"max": 1.0},
    "pets": {
        "max_level": 30,
        "xp_base": 40,
        "xp_per_level": 20,
        "hunger_decay": 2.0,
        "happiness_decay": 1.5,
        "food_price": 60,
        "food_amount": 35,
        "play_price": 40,
        "play_amount": 30,
        "care_cooldown": 30 * 60,
        "xp_care": 15,
        "xp_work": 5,
        "xp_daily": 10,
        "xp_message": 1,
        "xp_game": 2,
        "xp_duplicate": 150,
        "evolve_price": 2500,
        "max_luck": 0.15,
        "max_discount": 0.25,
    },
    "gacha": {
        "cost": 150,
        "cooldown": 8,
        "rate_legendary": 0.006,
        "rate_epic": 0.051,
        "rate_rare": 0.20,
        "soft_pity": 74,
        "soft_step": 0.06,
        "hard_pity": 90,
        "epic_pity": 10,
        "featured_chance": 0.5,
    },
    "casino": {
        "crash": {"min": 50, "max": 50_000, "cooldown": 10, "edge": 0.03, "max_multiplier": 100},
        "slots": {"min": 20, "max": 20_000, "cooldown": 5, "edge": 0.04},
        "coinflip": {"min": 20, "max": 50_000, "cooldown": 3, "edge": 0.02},
        "blackjack": {"min": 50, "max": 50_000, "cooldown": 5, "edge": 0.02},
        "roulette": {"min": 20, "max": 50_000, "cooldown": 5, "edge": 0.027},
        "mines": {"min": 50, "max": 30_000, "cooldown": 5, "edge": 0.03},
        "hilo": {"min": 50, "max": 30_000, "cooldown": 5, "edge": 0.03},
        "race": {"min": 20, "max": 30_000, "cooldown": 10, "edge": 0.05},
    },
}

# Casino games: name shown to players.
GAMES = {
    "crash": "🚀 Crash",
    "slots": "🎰 Slots",
    "coinflip": "🪙 Moneda",
    "blackjack": "🃏 Blackjack",
    "roulette": "🎡 Ruleta",
    "mines": "💣 Mines",
    "hilo": "🔼 Mayor o menor",
    "race": "🏇 Carrera",
}
# The subcommand that plays each game.
GAME_COMMANDS = {
    "crash": "crash", "slots": "slots", "coinflip": "moneda", "blackjack": "blackjack",
    "roulette": "ruleta", "mines": "mines", "hilo": "mayormenor", "race": "carrera",
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
    "pets": "🐾 Mascotas",
    "gacha": "🎰 Gacha",
    "casino": "🎲 Casino",
    "casino2": "🎲 Casino 2",
}

SETTINGS: list[Setting] = [
    Setting("general", "currency.name", "Nombre de la moneda", str, 1, 32),
    Setting("general", "currency.emoji", "Emoji de la moneda", str, 1, 64),
    Setting("general", "transfer.min", "Pagar: mínimo", int, 1, 1_000_000),
    Setting("general", "transfer.fee_percent", "Pagar: comisión (%)", float, 0, 50,
            "Lo paga quien envía, encima de la cantidad. Se destruye."),
    Setting("general", "leaderboard.page_size", "Top: usuarios por página", int, 5, 25),
    Setting("general", "bonuses.max", "Tope de bonificaciones (1 = +100%)", float, 0, 10,
            "Lo máximo que suman todos los boosts juntos."),
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
    Setting("pets", "pets.max_level", "Nivel máximo", int, 1, 100),
    Setting("pets", "pets.food_price", "Precio de la comida", int, 0, 1_000_000),
    Setting("pets", "pets.food_amount", "Hambre que quita la comida (0-100)", int, 1, 100),
    Setting("pets", "pets.play_price", "Precio de jugar", int, 0, 1_000_000),
    Setting("pets", "pets.play_amount", "Felicidad que da jugar (0-100)", int, 1, 100),
    Setting("pets", "pets.care_cooldown", "Espera entre cuidados (segundos)", int, 0, DAY),
    Setting("pets", "pets.hunger_decay", "Hambre que pierde por hora", float, 0, 100),
    Setting("pets", "pets.happiness_decay", "Felicidad que pierde por hora", float, 0, 100),
    Setting("pets", "pets.xp_care", "XP por cuidarla", int, 0, 10_000),
    Setting("pets", "pets.xp_work", "XP cuando trabajas", int, 0, 10_000),
    Setting("pets", "pets.xp_daily", "XP cuando reclamas el diario", int, 0, 10_000),
    Setting("pets", "pets.xp_message", "XP por mensaje pagado", int, 0, 10_000),
    Setting("pets", "pets.xp_duplicate", "XP por mascota repetida", int, 0, 1_000_000),
    Setting("pets", "pets.evolve_price", "Precio de evolucionar", int, 0, 10_000_000),
    Setting("pets", "pets.max_luck", "Tope de suerte (0.15 = 15%)", float, 0, 1),
    Setting("pets", "pets.max_discount", "Tope de descuento (0.25 = 25%)", float, 0, 0.9),
    Setting("gacha", "gacha.cost", "Precio por tirada (banners nuevos)", int, 1, 10_000_000),
    Setting("gacha", "gacha.cooldown", "Espera entre tiradas (segundos)", int, 3, 3600,
            "Mínimo 3 para no chocar con los límites de Discord."),
    Setting("gacha", "gacha.rate_legendary", "Prob. legendaria (0.006 = 0.6%)", float, 0, 0.5),
    Setting("gacha", "gacha.rate_epic", "Prob. épica (0.051 = 5.1%)", float, 0, 0.9),
    Setting("gacha", "gacha.rate_rare", "Prob. rara (0.2 = 20%)", float, 0, 0.95),
    Setting("gacha", "gacha.soft_pity", "Soft pity: desde la tirada nº", int, 1, 1000),
    Setting("gacha", "gacha.soft_step", "Soft pity: prob. extra por tirada", float, 0, 1),
    Setting("gacha", "gacha.hard_pity", "Hard pity: legendaria segura en la nº", int, 1, 1000),
    Setting("gacha", "gacha.epic_pity", "Épica (o mejor) segura cada X", int, 1, 100),
    Setting("gacha", "gacha.featured_chance", "50/50: prob. de que salga la destacada", float, 0, 1),
    *[
        S
        for Section, Game, Label in (
            ("casino", "crash", "Crash"),
            ("casino", "slots", "Slots"),
            ("casino", "coinflip", "Moneda"),
            ("casino", "blackjack", "Blackjack"),
            ("casino2", "roulette", "Ruleta"),
            ("casino2", "mines", "Mines"),
            ("casino2", "hilo", "Mayor o menor"),
            ("casino2", "race", "Carrera"),
        )
        for S in (
            Setting(Section, f"casino.{Game}.min", f"{Label}: apuesta mínima", int, 1, 10_000_000),
            Setting(Section, f"casino.{Game}.max", f"{Label}: apuesta máxima", int, 1, 100_000_000),
            Setting(Section, f"casino.{Game}.cooldown", f"{Label}: espera (segundos)", int, 0, 3600),
            Setting(Section, f"casino.{Game}.edge", f"{Label}: ventaja casa (0.03 = 3%)", float, 0, 0.5),
        )
    ],
    Setting("casino", "casino.crash.max_multiplier", "Crash: multiplicador máximo", int, 2, 1000),
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
