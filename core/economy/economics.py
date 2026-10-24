"""
Economy-wide systems: inflation, the bank, daily snapshots and stats.

Inflation: every `interval_hours` the money held by active users is compared to
`target_per_user`. The price multiplier moves towards (supply per user / target) ^ elasticity,
by at most `max_step` per check and within [min, max]. It applies to shop prices, pet care and
evolution, and (optionally) gacha pulls.

Ledger entries store the wallet change in `amount` and the bank change in `bank`, so the total
money change of any entry is amount + bank (a deposit is -X wallet, +X bank = 0).
"""

import math
import time
from datetime import datetime, timedelta, timezone

from core.economy.activity import LocalDay
from core.economy.constants import BANK, CREATED, LEDGER, STATE, STATS_DAILY, STATS_DAYS, USERS
from core.economy.rewards import Aware
from core.economy.service import ConditionFailed, EconomyError, EconomyService

MULTIPLIER_CACHE_SECONDS = 60


class BankError(EconomyError):
    """Message is safe to show to users."""


def Now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------- pure logic ----------------


def TargetMultiplier(supply: int, active: int, settings: dict) -> float:
    """Where prices should be for how much money active users hold."""
    if active <= 0 or supply <= 0:
        return 1.0
    Ratio = supply / active / settings["target_per_user"]
    return max(settings["min"], min(settings["max"], Ratio ** settings["elasticity"]))


def NextMultiplier(current: float, target: float, settings: dict) -> float:
    """One step towards the target, never more than max_step."""
    Step = settings["max_step"]
    Ratio = max(1 - Step, min(1 + Step, target / current)) if current > 0 else 1.0
    return round(max(settings["min"], min(settings["max"], current * Ratio)), 4)


def Inflate(price: int, multiplier: float) -> int:
    return max(1, int(round(price * multiplier)))


def WithdrawFee(amount: int, config: dict) -> int:
    Rate = config["bank"]["withdraw_fee"]
    return math.ceil(amount * Rate - 1e-9) if Rate > 0 and amount > 0 else 0


def Interest(bank: int, config: dict) -> int:
    Settings = config["bank"]
    return int(min(bank, Settings["interest_cap"]) * Settings["interest"])


# ---------------- service ----------------


class Economics:
    def __init__(self, db, economy: EconomyService):
        self.db = db
        self.state = db[STATE]
        self.daily = db[STATS_DAILY]
        self.users = db[USERS]
        self.ledger = db[LEDGER]
        self.economy = economy
        self._multiplier: dict[int, tuple[float, float]] = {}

    async def Setup(self):
        await self.daily.create_index([("guild_id", 1), ("date", 1)], unique=True)

    # ---- inflation ----

    async def Multiplier(self, guild_id: int, config: dict) -> float:
        """Current price multiplier (1.0 when inflation is off)."""
        if not config["inflation"]["enabled"]:
            return 1.0
        Cached = self._multiplier.get(guild_id)
        if Cached and Cached[0] > time.monotonic():
            return Cached[1]
        State = await self.state.find_one({"_id": guild_id}) or {}
        Value = float((State.get("inflation") or {}).get("multiplier", 1.0))
        self._multiplier[guild_id] = (time.monotonic() + MULTIPLIER_CACHE_SECONDS, Value)
        return Value

    async def Price(self, guild_id: int, base: int, config: dict, kind: str = "shop") -> int:
        """A base price after inflation. `kind` 'gacha' follows the inflation.gacha switch."""
        if kind == "gacha" and not config["inflation"]["gacha"]:
            return int(base)
        return Inflate(int(base), await self.Multiplier(guild_id, config))

    async def Supply(self, guild_id: int, active_days: int) -> dict:
        """Money in wallets + banks: in total, and among users active in the last `active_days`."""
        Since = Now() - timedelta(days=active_days)

        async def Sum(match: dict) -> tuple[int, int]:
            Rows = await (await self.users.aggregate(
                [
                    {"$match": match},
                    {
                        "$group": {
                            "_id": None,
                            "money": {"$sum": {"$add": [{"$ifNull": ["$balance", 0]}, {"$ifNull": ["$bank", 0]}]}},
                            "users": {"$sum": 1},
                        }
                    },
                ]
            )).to_list(length=1)
            return (int(Rows[0]["money"]), int(Rows[0]["users"])) if Rows else (0, 0)

        Total, _ = await Sum({"guild_id": guild_id})
        Active, Users = await Sum({"guild_id": guild_id, "last_active": {"$gte": Since}})
        return {"total": Total, "active": Active, "active_users": Users}

    async def UpdateInflation(self, guild_id: int, config: dict, force: bool = False) -> dict | None:
        """Recalculates the multiplier if it's due. Returns the new inflation state, or None if not due."""
        Settings = config["inflation"]
        State = (await self.state.find_one({"_id": guild_id}) or {}).get("inflation") or {}
        Last = Aware(State.get("updated_at"))
        if not force and Last and Now() - Last < timedelta(hours=Settings["interval_hours"]):
            return None
        Supply = await self.Supply(guild_id, Settings["active_days"])
        Current = float(State.get("multiplier", 1.0))
        Target = TargetMultiplier(Supply["active"], Supply["active_users"], Settings)
        New = NextMultiplier(Current, Target, Settings) if Settings["enabled"] else Current
        Doc = {
            "multiplier": New,
            "previous": Current,
            "target": round(Target, 4),
            "supply": Supply["active"],
            "active_users": Supply["active_users"],
            "updated_at": Now(),
        }
        await self.state.update_one({"_id": guild_id}, {"$set": {"inflation": Doc}}, upsert=True)
        self._multiplier.pop(guild_id, None)
        return Doc

    async def InflationState(self, guild_id: int) -> dict:
        return (await self.state.find_one({"_id": guild_id}) or {}).get("inflation") or {"multiplier": 1.0}

    # ---- ledger stats ----

    async def Flows(self, guild_id: int, since: datetime) -> dict:
        """Money created and destroyed since a moment, by source."""
        Rows = await (await self.ledger.aggregate(
            [
                {"$match": {"guild_id": guild_id, "ts": {"$gte": since}}},
                {
                    "$group": {
                        "_id": "$kind",
                        "money": {"$sum": {"$add": ["$amount", {"$ifNull": ["$bank", 0]}]}},
                        "fees": {"$sum": {"$ifNull": ["$fee", 0]}},
                    }
                },
            ]
        )).to_list(length=20)
        By = {R["_id"]: R for R in Rows}

        def Money(kind):
            return int(By.get(kind, {}).get("money", 0))

        Taxes = sum(int(R["fees"]) for R in Rows)
        Casino = -(Money("bet") + Money("payout"))  # what the house kept
        return {
            "created": Money(CREATED),
            "destroyed": -Money("destroyed"),
            "taxes": Taxes,
            "casino": Casino,
            "net": sum(Money(K) for K in By) ,
        }

    async def Snapshot(self, guild_id: int, config: dict):
        """Saves today's numbers (updated through the day) for the stats chart."""
        Offset = config["activity"]["utc_offset"]
        Today = LocalDay(Now(), Offset)
        Midnight = datetime(Today.year, Today.month, Today.day, tzinfo=timezone.utc) - timedelta(hours=Offset)
        Supply = await self.Supply(guild_id, config["inflation"]["active_days"])
        Flows = await self.Flows(guild_id, Midnight)
        await self.daily.update_one(
            {"guild_id": guild_id, "date": Today.isoformat()},
            {
                "$set": {
                    "supply": Supply["total"],
                    "active_users": Supply["active_users"],
                    "multiplier": await self.Multiplier(guild_id, config),
                    **{K: Flows[K] for K in ("created", "destroyed", "taxes", "casino", "net")},
                }
            },
            upsert=True,
        )

    async def History(self, guild_id: int, days: int = STATS_DAYS) -> list[dict]:
        Rows = await self.daily.find({"guild_id": guild_id}).sort("date", -1).limit(days).to_list(length=days)
        return list(reversed(Rows))

    async def Richest(self, guild_id: int, limit: int = 5) -> list[dict]:
        return await (await self.users.aggregate(
            [
                {"$match": {"guild_id": guild_id}},
                {"$project": {"user_id": 1, "money": {"$add": [{"$ifNull": ["$balance", 0]}, {"$ifNull": ["$bank", 0]}]}}},
                {"$sort": {"money": -1}},
                {"$limit": limit},
            ]
        )).to_list(length=limit)

    # ---- bank ----

    async def Deposit(self, guild_id: int, user_id: int, amount: int) -> dict:
        if amount <= 0:
            raise BankError("Pon una cantidad mayor que 0.")
        return await self.economy.Change(
            guild_id, user_id, -amount, "Depósito en el banco", kind=BANK, ref="bank",
            also_inc={"bank": amount}, extra={"bank": amount},
        )

    async def Withdraw(self, guild_id: int, user_id: int, amount: int, config: dict) -> tuple[dict, int]:
        """Takes money out of the bank; the fee is destroyed. Returns (account, fee)."""
        if amount <= 0:
            raise BankError("Pon una cantidad mayor que 0.")
        Fee = WithdrawFee(amount, config)
        try:
            Account = await self.economy.Change(
                guild_id, user_id, amount - Fee, "Retiro del banco", kind=BANK, ref="bank",
                when={"bank": {"$gte": amount}}, also_inc={"bank": -amount}, extra={"bank": -amount, "fee": Fee},
            )
        except ConditionFailed:
            Account = await self.economy.Account(guild_id, user_id)
            raise BankError(f"Solo tienes {int(Account.get('bank', 0)):,} en el banco.".replace(",", "."))
        return Account, Fee

    async def PayInterest(self, guild_id: int, config: dict) -> int:
        """Pays one day of interest to everyone with money in the bank, once per local day. Returns the total."""
        Settings = config["bank"]
        if not Settings["enabled"] or Settings["interest"] <= 0:
            return 0
        Today = LocalDay(Now(), config["activity"]["utc_offset"]).isoformat()
        # Claim today's payment first so it can't run twice.
        Claimed = await self.state.find_one_and_update(
            {"_id": guild_id, "bank_interest_day": {"$ne": Today}},
            {"$set": {"bank_interest_day": Today}},
        )
        if Claimed is None:
            Exists = await self.state.find_one({"_id": guild_id})
            if Exists:
                return 0
            await self.state.update_one({"_id": guild_id}, {"$set": {"bank_interest_day": Today}}, upsert=True)
        Total = 0
        Savers = await self.users.find({"guild_id": guild_id, "bank": {"$gt": 0}}, {"user_id": 1, "bank": 1}).to_list(length=None)
        for Saver in Savers:
            Amount = Interest(int(Saver["bank"]), config)
            if Amount > 0:
                await self.economy.Change(
                    guild_id, Saver["user_id"], 0, "Intereses del banco", kind=CREATED, ref="bank",
                    also_inc={"bank": Amount}, extra={"bank": Amount},
                )
                Total += Amount
        return Total
