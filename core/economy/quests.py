"""Daily, weekly and one-time quests with automatic progress."""

import time
from datetime import datetime, timezone

from pymongo import ReturnDocument

from core.economy.activity import LocalDay
from core.economy.constants import MAX_QUESTS, QUEST_PROGRESS, QUESTS
from core.economy.service import EconomyError, EconomyService
from core.economy.shop import NewId

QUEST_CACHE_SECONDS = 60


class QuestError(EconomyError):
    """Message is safe to show to users."""


def PeriodKey(period: str, now: datetime, utc_offset: int) -> str:
    """Which daily/weekly window a moment falls in, so progress resets on its own."""
    if period == "once":
        return "once"
    Day = LocalDay(now, utc_offset)
    if period == "daily":
        return Day.isoformat()
    Year, Week, _ = Day.isocalendar()
    return f"{Year}-W{Week:02d}"


class Quests:
    def __init__(self, db, economy: EconomyService, shop=None):
        self.quests = db[QUESTS]
        self.progress = db[QUEST_PROGRESS]
        self.economy = economy
        self.shop = shop
        self._cache: dict[int, tuple[float, list]] = {}

    async def Setup(self):
        await self.quests.create_index([("guild_id", 1), ("quest_id", 1)], unique=True)
        await self.progress.create_index(
            [("guild_id", 1), ("user_id", 1), ("quest_id", 1), ("period_key", 1)], unique=True
        )

    async def Create(self, guild_id: int, data: dict) -> dict:
        if await self.quests.count_documents({"guild_id": guild_id}) >= MAX_QUESTS:
            raise QuestError(f"Ya hay {MAX_QUESTS} misiones. Borra alguna primero.")
        if int(data.get("target", 0)) <= 0:
            raise QuestError("El objetivo tiene que ser mayor que 0.")
        if int(data.get("reward", 0)) <= 0 and not data.get("reward_item"):
            raise QuestError("La misión tiene que dar algo.")
        Quest = {"guild_id": guild_id, "quest_id": NewId(), "enabled": True, **data}
        await self.quests.insert_one(Quest)
        self._cache.pop(guild_id, None)
        return Quest

    async def Update(self, guild_id: int, quest_id: str, data: dict):
        await self.quests.update_one({"guild_id": guild_id, "quest_id": quest_id}, {"$set": data})
        self._cache.pop(guild_id, None)

    async def Delete(self, guild_id: int, quest_id: str):
        await self.quests.delete_one({"guild_id": guild_id, "quest_id": quest_id})
        self._cache.pop(guild_id, None)

    async def List(self, guild_id: int, only_enabled: bool = False) -> list[dict]:
        Cached = self._cache.get(guild_id)
        if not Cached or Cached[0] < time.monotonic():
            All = await self.quests.find({"guild_id": guild_id}).to_list(length=MAX_QUESTS)
            Cached = (time.monotonic() + QUEST_CACHE_SECONDS, All)
            self._cache[guild_id] = Cached
        return [Q for Q in Cached[1] if Q.get("enabled") or not only_enabled]

    async def Track(self, guild_id: int, user_id: int, objective: str, amount: int, config: dict):
        """Adds progress to every active quest with this objective."""
        if amount <= 0:
            return
        Now = datetime.now(timezone.utc)
        Offset = config["activity"]["utc_offset"]
        for Quest in await self.List(guild_id, only_enabled=True):
            if Quest["objective"] != objective:
                continue
            await self.progress.update_one(
                {
                    "guild_id": guild_id,
                    "user_id": user_id,
                    "quest_id": Quest["quest_id"],
                    "period_key": PeriodKey(Quest["period"], Now, Offset),
                },
                {"$inc": {"progress": amount}, "$setOnInsert": {"claimed": False}},
                upsert=True,
            )

    async def Status(self, guild_id: int, user_id: int, config: dict) -> list[tuple[dict, int, bool]]:
        """(quest, progress, claimed) for every active quest in its current period."""
        Now = datetime.now(timezone.utc)
        Offset = config["activity"]["utc_offset"]
        Result = []
        for Quest in await self.List(guild_id, only_enabled=True):
            Doc = await self.progress.find_one(
                {
                    "guild_id": guild_id,
                    "user_id": user_id,
                    "quest_id": Quest["quest_id"],
                    "period_key": PeriodKey(Quest["period"], Now, Offset),
                }
            ) or {}
            Result.append((Quest, int(Doc.get("progress", 0)), bool(Doc.get("claimed"))))
        return Result

    async def Claim(self, guild_id: int, user_id: int, quest_id: str, config: dict) -> dict:
        """Gives the reward of a completed quest (once per period)."""
        Quest = next((Q for Q in await self.List(guild_id, only_enabled=True) if Q["quest_id"] == quest_id), None)
        if not Quest:
            raise QuestError("Esa misión ya no existe.")
        Key = PeriodKey(Quest["period"], datetime.now(timezone.utc), config["activity"]["utc_offset"])
        # Only flips claimed if it's complete and not claimed yet: a double click can't claim twice.
        Doc = await self.progress.find_one_and_update(
            {
                "guild_id": guild_id,
                "user_id": user_id,
                "quest_id": quest_id,
                "period_key": Key,
                "claimed": False,
                "progress": {"$gte": int(Quest["target"])},
            },
            {"$set": {"claimed": True, "claimed_at": datetime.now(timezone.utc)}},
            return_document=ReturnDocument.AFTER,
        )
        if Doc is None:
            raise QuestError("Todavía no la completaste (o ya la reclamaste).")
        if Quest.get("reward"):
            await self.economy.Add(guild_id, user_id, int(Quest["reward"]), f"Misión: {Quest['name']}", ref=f"quest:{quest_id}")
        if Quest.get("reward_item") and self.shop:
            await self.shop.Give(guild_id, user_id, Quest["reward_item"], 1)
        return Quest
