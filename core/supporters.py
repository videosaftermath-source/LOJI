"""
Supporters: members who wear the server's vanity link in their custom status or its tag next to their
name. Either one gives the benefits (they don't stack): optional roles, an earnings multiplier, more gacha
luck and a one-time welcome reward, plus an announcement.

Privacy: the status text is only read to look for the vanity and is never stored; only whether each
member currently qualifies (and since when) is kept. Anyone can opt out with /privacidad.
"""

import re
import time
from datetime import datetime, timezone

CONFIG = "supporter_config"
STATE = "supporters"
CACHE_SECONDS = 30

DEFAULTS = {
    "enabled": True,
    "vanity": "discord.gg/animetv",
    "vanity_role": None,
    "tag_role": None,
    "multiplier": 1.1,  # earnings (stacks with the booster bonus, not between vanity and tag)
    "gacha_luck": 0.2,  # +20% legendary/epic chance, like the booster's
    "reward": 250,  # paid once ever, the first time someone becomes a supporter
    "announce_channel": None,
    "message": "🏷️ ¡{user} ahora lleva {cosa} de **{server}**! Gracias por apoyarnos 💖",
}
ANNOUNCE_COOLDOWN = 12 * 3600  # don't announce the same person again for a while (status toggling)


def Now() -> datetime:
    return datetime.now(timezone.utc)


def Slug(vanity: str) -> str:
    """'Discord.gg/animetv' -> 'animetv'."""
    return (vanity or "").strip().lower().rstrip("/").split("/")[-1]


def VanityPattern(vanity: str) -> re.Pattern | None:
    """Matches discord.gg/animetv, .gg/animetv or /animetv (any case), but not /animetvfans."""
    Code = Slug(vanity)
    if not Code:
        return None
    return re.compile(r"(?:discord(?:app)?\.(?:gg|com/invite)|\.gg)?/" + re.escape(Code) + r"(?![a-z0-9-])", re.IGNORECASE)


def HasVanity(member, vanity: str) -> bool:
    Pattern = VanityPattern(vanity)
    if not Pattern:
        return False
    for Activity in getattr(member, "activities", ()) or ():
        Text = " ".join(T for T in (getattr(Activity, "name", None), getattr(Activity, "state", None)) if T)
        if getattr(Activity, "type", None) is not None and str(getattr(Activity.type, "name", Activity.type)) == "custom" and Pattern.search(Text):
            return True
    return False


def HasTag(member, guild_id: int) -> bool:
    Primary = getattr(member, "primary_guild", None)
    return bool(Primary and getattr(Primary, "id", None) == guild_id and getattr(Primary, "identity_enabled", False))


# In memory: who has the benefits right now, read by the economy on every payout.
_active: dict[tuple[int, int], tuple[float, float]] = {}


def Bonus(guild_id: int, user_id: int) -> tuple[float, float]:
    """(earnings multiplier, extra gacha luck) for a supporter; (1, 0) otherwise."""
    return _active.get((guild_id, user_id), (1.0, 0.0))


def SetActive(guild_id: int, user_id: int, config: dict | None):
    if config:
        _active[(guild_id, user_id)] = (float(config["multiplier"]), float(config["gacha_luck"]))
    else:
        _active.pop((guild_id, user_id), None)


class Supporters:
    def __init__(self, db):
        self.config = db[CONFIG]
        self.state = db[STATE]
        self._cache: dict[int, tuple[float, dict]] = {}

    async def Get(self, guild_id: int) -> dict:
        Cached = self._cache.get(guild_id)
        if Cached and Cached[0] > time.monotonic():
            return Cached[1]
        Doc = await self.config.find_one({"_id": guild_id}) or {}
        Config = {**DEFAULTS, **{K: V for K, V in Doc.items() if K != "_id"}}
        self._cache[guild_id] = (time.monotonic() + CACHE_SECONDS, Config)
        return Config

    async def Set(self, guild_id: int, changes: dict) -> dict:
        await self.config.update_one({"_id": guild_id}, {"$set": changes}, upsert=True)
        self._cache.pop(guild_id, None)
        return await self.Get(guild_id)

    async def State(self, guild_id: int, user_id: int) -> dict:
        return await self.state.find_one({"guild_id": guild_id, "user_id": user_id}) or {}

    async def Record(self, guild_id: int, user_id: int, vanity: bool, tag: bool) -> tuple[dict, dict]:
        """Saves whether they qualify now. Returns (before, after)."""
        Key = {"guild_id": guild_id, "user_id": user_id}
        Before = await self.state.find_one(Key) or {}
        Supporter = vanity or tag
        Changes = {"vanity": vanity, "tag": tag, "supporter": Supporter}
        if Supporter and not Before.get("supporter"):
            Changes["since"] = Now()
        await self.state.update_one(Key, {"$set": Changes}, upsert=True)
        return Before, {**Before, **Changes}

    async def ClaimReward(self, guild_id: int, user_id: int) -> bool:
        """True only the first time ever (so the welcome reward can't repeat)."""
        Done = await self.state.update_one({"guild_id": guild_id, "user_id": user_id, "rewarded": {"$ne": True}}, {"$set": {"rewarded": True}})
        return bool(Done.modified_count)

    async def ClaimAnnouncement(self, guild_id: int, user_id: int) -> bool:
        Limit = time.time() - ANNOUNCE_COOLDOWN
        Done = await self.state.update_one(
            {"guild_id": guild_id, "user_id": user_id, "$or": [{"announced_at": {"$exists": False}}, {"announced_at": {"$lt": Limit}}]},
            {"$set": {"announced_at": time.time()}},
        )
        return bool(Done.modified_count)

    async def SetOptOut(self, guild_id: int, user_id: int, opted_out: bool):
        await self.state.update_one({"guild_id": guild_id, "user_id": user_id}, {"$set": {"opted_out": opted_out}}, upsert=True)

    async def LoadActive(self, guild_id: int):
        """Fills the in-memory list after a restart."""
        Config = await self.Get(guild_id)
        for Doc in await self.state.find({"guild_id": guild_id, "supporter": True, "opted_out": {"$ne": True}}).to_list(length=None):
            SetActive(guild_id, Doc["user_id"], Config if Config["enabled"] else None)
