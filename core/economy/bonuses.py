"""Temporary boosts (from consumables, later pets). All boosts together are capped by bonuses.max."""

from datetime import datetime, timedelta, timezone

from core.economy.constants import EFFECTS


class Bonuses:
    def __init__(self, db, pets=None):
        self.effects = db[EFFECTS]
        self.pets = pets  # set by the registry; pets add to work/chat boosts

    async def Setup(self):
        await self.effects.create_index([("guild_id", 1), ("user_id", 1), ("kind", 1)])
        # Mongo deletes expired boosts by itself.
        await self.effects.create_index("expires_at", expireAfterSeconds=0)

    async def Add(self, guild_id: int, user_id: int, kind: str, value: float, seconds: int, source: str):
        Now = datetime.now(timezone.utc)
        await self.effects.insert_one(
            {
                "guild_id": guild_id,
                "user_id": user_id,
                "kind": kind,
                "value": float(value),
                "source": source,
                "expires_at": Now + timedelta(seconds=seconds),
            }
        )

    async def Active(self, guild_id: int, user_id: int) -> list[dict]:
        # The TTL monitor runs about once a minute, so filter expired ones too.
        return await self.effects.find(
            {"guild_id": guild_id, "user_id": user_id, "expires_at": {"$gt": datetime.now(timezone.utc)}}
        ).to_list(length=100)

    async def Total(self, guild_id: int, user_id: int, kind: str, config: dict) -> float:
        """Extra multiplier for `kind` (0.25 = +25%): boosts plus the active pet, capped by config."""
        Sum = sum(E["value"] for E in await self.Active(guild_id, user_id) if E["kind"] == kind)
        if self.pets is not None:
            Sum += await self.pets.Perk(guild_id, user_id, kind, config)
        return Capped(Sum, config)


def Capped(total: float, config: dict) -> float:
    return max(0.0, min(float(total), float(config["bonuses"]["max"])))


def Boosted(amount: int, bonus: float) -> int:
    return int(round(amount * (1 + bonus)))
