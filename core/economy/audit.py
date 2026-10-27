"""
"Hacienda": who made the most money in a period, split by where it came from, to spot abuse.

Reads the ledger only. Spending (shop, gacha pulls, pet care) and bank moves are left out:
the ranking is about money coming in.
"""

import math
from datetime import datetime, timedelta, timezone

from core.economy.constants import BET, PAYOUT, TRANSFER

PERIODS = {"24h": 1, "3d": 3, "7d": 7, "14d": 14}
TOP = 10

# Category -> (emoji, label)
CATEGORIES = {
    "casino": ("🎲", "Casino"),
    "grind": ("💼", "Trabajo y chat"),
    "rewards": ("🎁", "Códigos, misiones y gacha"),
    "admin": ("🛠️", "Admins"),
    "transfers": ("💸", "Transferencias"),
}
GRIND_REASONS = {"Trabajar", "Diario", "Actividad en chat", "Tiempo en voz", "Intereses del banco"}
GRIND_PREFIXES = ("Ingresos de ",)  # Rentista pets
REWARD_REASONS = {"Premio del gacha", "Gacha: mascota sin espacio", "Gracias por boostear"}
REWARD_PREFIXES = ("Código ", "Misión: ")
ADMIN_PREFIXES = ("Admin ", "Reinicio de economía")
TRANSFER_SHARE_FLAG = 0.5  # flag when more than half of the money came from other users
DAILY_CLAIMS_SLACK = 1  # a window can catch one more daily claim than its length suggests
MAX_PET_INCOME_SHARE = 0.5  # a maxed legendary Rentista makes ~41% of pets.income_base per day


def Classify(kind: str, reason: str) -> str | None:
    """Which category a ledger entry belongs to (None = spending or bank moves, not counted)."""
    Reason = reason or ""
    if kind in (BET, PAYOUT):
        return "casino"
    if kind == TRANSFER:
        return "transfers"
    if Reason.startswith(ADMIN_PREFIXES):
        return "admin"
    if Reason in GRIND_REASONS or Reason.startswith(GRIND_PREFIXES):
        return "grind"
    if Reason in REWARD_REASONS or Reason.startswith(REWARD_PREFIXES):
        return "rewards"
    return None


def MaxGrind(days: float, config: dict) -> int:
    """
    Most anyone could legitimately make from work, daily, chat, voice, pets and bank interest in
    `days`, with every bonus maxed and the booster multiplier. Anything above this is suspicious.
    """
    Work, Daily, Chat, Voice = config["work"], config["daily"], config["activity"], config["voice"]
    Hours = days * 24
    Multiplier = (1 + config["bonuses"]["max"]) * (config["booster"]["multiplier"] if config["booster"]["enabled"] else 1)
    PerDay = Work["max"] * 86400 / max(1, Work["cooldown"]) + Chat["hard_cap"] + (Voice["daily_cap"] if Voice["enabled"] else 0)
    DailyClaims = math.ceil(Hours * 3600 / Daily["cooldown"]) + DAILY_CLAIMS_SLACK
    DailyMax = Daily["base"] + Daily["streak_bonus"] * Daily["max_streak_days"]
    Pets = config["pets"]["income_base"] * MAX_PET_INCOME_SHARE
    Bank = config["bank"]["interest_cap"] * config["bank"]["interest"] if config["bank"]["enabled"] else 0
    return int((PerDay * days + DailyClaims * DailyMax + Pets * days) * Multiplier + Bank * days)


def Summarize(rows: list[dict], days: float, config: dict) -> list[dict]:
    """
    rows: {"user_id", "kind", "reason", "money", "count"} grouped from the ledger.
    Returns one dict per user: categories, total, flags; sorted by total.
    """
    Users: dict[int, dict] = {}
    for Row in rows:
        Category = Classify(Row["kind"], Row["reason"])
        if not Category:
            continue
        User = Users.setdefault(Row["user_id"], {"user_id": Row["user_id"], **{C: 0 for C in CATEGORIES}, "games": 0})
        User[Category] += int(Row["money"])
        if Row["kind"] == BET:
            User["games"] += int(Row["count"])
    Limit = MaxGrind(days, config)
    for User in Users.values():
        User["total"] = sum(User[C] for C in CATEGORIES)
        Flags = []
        if User["grind"] > Limit:
            Flags.append(f"🚩 Trabajo/chat por encima del máximo posible ({Limit:,})".replace(",", "."))
        if User["admin"]:
            Flags.append("🛠️ Recibió o perdió dinero por admins")
        if User["total"] > 0 and User["transfers"] > User["total"] * TRANSFER_SHARE_FLAG:
            Flags.append("💸 Más de la mitad le llegó de otros usuarios")
        User["flags"] = Flags
    return sorted(Users.values(), key=lambda U: U["total"], reverse=True)


async def Audit(economy, guild_id: int, period: str, config: dict) -> list[dict]:
    Days = PERIODS[period]
    Since = datetime.now(timezone.utc) - timedelta(days=Days)
    Rows = await (await economy.ledger.aggregate(
        [
            {"$match": {"guild_id": guild_id, "ts": {"$gte": Since}}},
            {
                "$group": {
                    "_id": {"user_id": "$user_id", "kind": "$kind", "reason": "$reason"},
                    "money": {"$sum": {"$add": ["$amount", {"$ifNull": ["$bank", 0]}]}},
                    "count": {"$sum": 1},
                }
            },
        ]
    )).to_list(length=None)
    Flat = [{**R["_id"], "money": R["money"], "count": R["count"]} for R in Rows]
    return Summarize(Flat, Days, config)
