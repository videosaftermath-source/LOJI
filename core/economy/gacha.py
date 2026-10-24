"""
Gacha: banners with a prize pool, Genshin-style pity and 50/50.

- Legendary: base rate, rising by `soft_step` per pull from `soft_pity`, certain at `hard_pity`.
- Epic: certain (or better) every `epic_pity` pulls.
- 50/50: when a legendary or epic comes out, it's the banner's featured prize with
  `featured_chance`. Losing it guarantees the featured one next time.
Pity counters are kept per user and banner.
"""

import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from pymongo import ReturnDocument

from core.economy.constants import BANNERS, MAX_BANNERS, MAX_POOL, PITY, PULL_HISTORY_DAYS, PULLS, RARITIES
from core.economy.rewards import Aware
from core.economy.service import EconomyError
from core.economy.shop import NewId

ORDER = ["common", "rare", "epic", "legendary"]
# Credit prizes used by "fill missing rarities", as multiples of the pull cost.
FILLER_CREDITS = {"common": 0.4, "rare": 1.2, "epic": 5, "legendary": 25}


class GachaError(EconomyError):
    """Message is safe to show to users."""


def Now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------- pure logic ----------------


@dataclass
class Pity:
    since_legendary: int = 0
    since_epic: int = 0
    legendary_guaranteed: bool = False
    epic_guaranteed: bool = False
    total: int = 0

    @classmethod
    def From(cls, doc: dict | None) -> "Pity":
        Doc = doc or {}
        return cls(**{k: Doc.get(k, getattr(cls(), k)) for k in cls.__dataclass_fields__})

    def Dict(self) -> dict:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}


def LegendaryRate(pull_number: int, settings: dict) -> float:
    """Chance of a legendary on the Nth pull since the last one."""
    if pull_number >= settings["hard_pity"]:
        return 1.0
    Rate = settings["rate_legendary"]
    if pull_number >= settings["soft_pity"]:
        Rate += settings["soft_step"] * (pull_number - settings["soft_pity"] + 1)
    return min(1.0, Rate)


def RollRarity(pity: Pity, settings: dict, rng: random.Random) -> str:
    """Picks the rarity of one pull and advances the counters (doesn't touch the 50/50)."""
    Legendary = LegendaryRate(pity.since_legendary + 1, settings)
    Roll = rng.random()
    if Roll < Legendary:
        Rarity = "legendary"
    elif pity.since_epic + 1 >= settings["epic_pity"]:
        Rarity = "epic"
    elif Roll < Legendary + settings["rate_epic"]:
        Rarity = "epic"
    elif Roll < Legendary + settings["rate_epic"] + settings["rate_rare"]:
        Rarity = "rare"
    else:
        Rarity = "common"
    pity.total += 1
    if Rarity == "legendary":
        pity.since_legendary = 0
        pity.since_epic += 1
    elif Rarity == "epic":
        pity.since_epic = 0
        pity.since_legendary += 1
    else:
        pity.since_legendary += 1
        pity.since_epic += 1
    return Rarity


def PickPrize(pool: list[dict], rarity: str, pity: Pity, settings: dict, rng: random.Random) -> tuple[dict, bool]:
    """Chooses a prize of that rarity, applying the 50/50. Returns (prize, was it featured)."""
    Options = [P for P in pool if P["rarity"] == rarity]
    if not Options:
        # Shouldn't happen on a valid banner: fall back to the closest lower rarity.
        for Lower in reversed(ORDER[: ORDER.index(rarity)]):
            Options = [P for P in pool if P["rarity"] == Lower]
            if Options:
                break
    Featured = [P for P in Options if P.get("featured")]
    Normal = [P for P in Options if not P.get("featured")]
    if rarity in ("legendary", "epic") and Featured:
        Flag = f"{rarity}_guaranteed"
        Wins = getattr(pity, Flag) or not Normal or rng.random() < settings["featured_chance"]
        setattr(pity, Flag, not Wins)
        return rng.choice(Featured if Wins else Normal), Wins
    return rng.choice(Options), bool(Featured and not Normal)


def Pull(pool: list[dict], pity: Pity, count: int, settings: dict, rng: random.Random = random) -> list[tuple[dict, str, bool]]:
    """`count` pulls: [(prize, rarity, featured)]. Updates `pity` in place."""
    Results = []
    for _ in range(count):
        Rarity = RollRarity(pity, settings, rng)
        Prize, Featured = PickPrize(pool, Rarity, pity, settings, rng)
        Results.append((Prize, Prize["rarity"], Featured))
    return Results


def Problems(banner: dict) -> list[str]:
    """Why a banner can't be activated (empty list = it's fine)."""
    Issues = []
    for Rarity in ORDER:
        if not any(P["rarity"] == Rarity for P in banner.get("pool", [])):
            Issues.append(f"Falta al menos un premio **{RARITIES[Rarity]['label']}**.")
    if Aware(banner["end"]) <= Aware(banner["start"]):
        Issues.append("La fecha de fin es anterior al inicio.")
    return Issues


def Status(banner: dict, now: datetime) -> str:
    if not banner.get("enabled"):
        return "paused"
    if now < Aware(banner["start"]):
        return "scheduled"
    if now >= Aware(banner["end"]):
        return "ended"
    return "active"


# ---------------- service ----------------


@dataclass
class PullResult:
    prize: dict
    rarity: str
    featured: bool
    new: bool = False  # for pets: first time they get it
    detail: str = ""  # e.g. "+150 XP"
    name: str = ""
    emoji: str | None = None


@dataclass
class PullOutcome:
    banner: dict
    results: list[PullResult]
    pity: Pity
    paid: int
    balance: int
    extra: dict = field(default_factory=dict)


class Gacha:
    def __init__(self, db, economy, shop, pets):
        self.banners = db[BANNERS]
        self.pity = db[PITY]
        self.pulls = db[PULLS]
        self.economy = economy
        self.shop = shop
        self.pets = pets
        self.economics = None  # set by the registry (inflation)
        self.rng = random.SystemRandom()

    async def Setup(self):
        await self.banners.create_index([("guild_id", 1), ("banner_id", 1)], unique=True)
        await self.pity.create_index([("guild_id", 1), ("user_id", 1), ("banner_id", 1)], unique=True)
        await self.pulls.create_index([("guild_id", 1), ("user_id", 1), ("ts", -1)])
        await self.pulls.create_index("ts", expireAfterSeconds=PULL_HISTORY_DAYS * 86400)

    # ---- banners (admin) ----

    async def List(self, guild_id: int) -> list[dict]:
        return await self.banners.find({"guild_id": guild_id}).sort("start", -1).to_list(length=MAX_BANNERS)

    async def Get(self, guild_id: int, banner_id: str) -> dict | None:
        return await self.banners.find_one({"guild_id": guild_id, "banner_id": banner_id})

    async def Active(self, guild_id: int) -> list[dict]:
        Now_ = Now()
        return [B for B in await self.List(guild_id) if Status(B, Now_) == "active"]

    async def Create(self, guild_id: int, data: dict) -> dict:
        if await self.banners.count_documents({"guild_id": guild_id}) >= MAX_BANNERS:
            raise GachaError(f"Ya hay {MAX_BANNERS} banners. Borra alguno viejo.")
        Banner = {"guild_id": guild_id, "banner_id": NewId(), "pool": [], "enabled": False, **data}
        await self.banners.insert_one(Banner)
        return Banner

    async def Update(self, guild_id: int, banner_id: str, data: dict) -> dict | None:
        return await self.banners.find_one_and_update(
            {"guild_id": guild_id, "banner_id": banner_id}, {"$set": data}, return_document=ReturnDocument.AFTER
        )

    async def Delete(self, guild_id: int, banner_id: str):
        await self.banners.delete_one({"guild_id": guild_id, "banner_id": banner_id})

    async def SetEnabled(self, guild_id: int, banner_id: str, enabled: bool) -> dict:
        Banner = await self.Get(guild_id, banner_id)
        if enabled:
            Issues = Problems(Banner)
            if Issues:
                raise GachaError("No se puede activar todavía:\n" + "\n".join(f"- {I}" for I in Issues))
        return await self.Update(guild_id, banner_id, {"enabled": enabled})

    async def AddPrizes(self, guild_id: int, banner_id: str, prizes: list[dict]) -> dict:
        Banner = await self.Get(guild_id, banner_id)
        Existing = {(P["type"], P.get("ref"), P.get("amount"), P["rarity"]) for P in Banner["pool"]}
        New = [
            {"key": NewId(5), "featured": False, **P}
            for P in prizes
            if (P["type"], P.get("ref"), P.get("amount"), P["rarity"]) not in Existing
        ]
        if len(Banner["pool"]) + len(New) > MAX_POOL:
            raise GachaError(f"Un banner tiene como mucho {MAX_POOL} premios.")
        return await self.Update(guild_id, banner_id, {"pool": Banner["pool"] + New})

    async def RemovePrize(self, guild_id: int, banner_id: str, key: str) -> dict:
        Banner = await self.Get(guild_id, banner_id)
        Pool = [P for P in Banner["pool"] if P["key"] != key]
        Banner = await self.Update(guild_id, banner_id, {"pool": Pool})
        if Banner.get("enabled") and Problems(Banner):
            Banner = await self.Update(guild_id, banner_id, {"enabled": False})
        return Banner

    async def SetFeatured(self, guild_id: int, banner_id: str, keys: list[str]) -> dict:
        Banner = await self.Get(guild_id, banner_id)
        Pool = [{**P, "featured": P["key"] in keys and P["rarity"] in ("epic", "legendary")} for P in Banner["pool"]]
        return await self.Update(guild_id, banner_id, {"pool": Pool})

    async def FillMissing(self, guild_id: int, banner_id: str) -> dict:
        """Adds a credits prize for every rarity that has none."""
        Banner = await self.Get(guild_id, banner_id)
        Missing = [R for R in ORDER if not any(P["rarity"] == R for P in Banner["pool"])]
        return await self.AddPrizes(
            guild_id,
            banner_id,
            [{"type": "credits", "amount": max(1, round(Banner["cost"] * FILLER_CREDITS[R])), "rarity": R} for R in Missing],
        )

    # ---- pulling ----

    async def PullCost(self, guild_id: int, banner: dict, config: dict) -> int:
        """Price of one pull after inflation (if it applies to the gacha)."""
        Base = int(banner["cost"])
        return await self.economics.Price(guild_id, Base, config, "gacha") if self.economics else Base

    async def UserPity(self, guild_id: int, user_id: int, banner_id: str) -> Pity:
        return Pity.From(await self.pity.find_one({"guild_id": guild_id, "user_id": user_id, "banner_id": banner_id}))

    async def DoPull(self, member, banner_id: str, count: int, config: dict) -> PullOutcome:
        Guild = member.guild
        async with self.economy.Lock(Guild.id, member.id):
            Banner = await self.Get(Guild.id, banner_id)
            if not Banner or Status(Banner, Now()) != "active":
                raise GachaError("Ese banner ya no está disponible.")
            Cost = await self.PullCost(Guild.id, Banner, config) * count
            Pity_ = await self.UserPity(Guild.id, member.id, banner_id)
            Rolled = Pull(Banner["pool"], Pity_, count, config["gacha"], self.rng)
            async with self.economy.Transaction() as Session:
                Account = await self.economy.Remove(
                    Guild.id, member.id, Cost, f"Gacha x{count}: {Banner['name']}", ref=f"banner:{banner_id}", session=Session
                )
                await self.pity.update_one(
                    {"guild_id": Guild.id, "user_id": member.id, "banner_id": banner_id},
                    {"$set": Pity_.Dict()},
                    upsert=True,
                    session=Session,
                )
            Results = [await self.Give(member, Prize, Rarity, Featured, config) for Prize, Rarity, Featured in Rolled]
        await self.pulls.insert_many(
            [
                {
                    "guild_id": Guild.id,
                    "user_id": member.id,
                    "banner_id": banner_id,
                    "rarity": R.rarity,
                    "name": R.name,
                    "featured": R.featured,
                    "ts": Now(),
                }
                for R in Results
            ]
        )
        return PullOutcome(Banner, Results, Pity_, Cost, await self.economy.PeekBalance(Guild.id, member.id))

    async def Give(self, member, prize: dict, rarity: str, featured: bool, config: dict) -> PullResult:
        Guild = member.guild
        Result = PullResult(prize, rarity, featured)
        if prize["type"] == "pet":
            Species = await self.pets.GetSpecies(Guild.id, prize["ref"])
            Result.name, Result.emoji = (Species["name"], Species.get("emoji")) if Species else ("Mascota perdida", "🐾")
            if Species:
                try:
                    _, Result.new = await self.pets.Grant(Guild.id, member.id, prize["ref"], "gacha", config)
                    Result.detail = "¡NUEVA!" if Result.new else f"+{config['pets']['xp_duplicate']} XP"
                except EconomyError:
                    # Collection full: pay it out instead of losing it.
                    Amount = round(int(prize.get("amount") or 0) or config["gacha"]["cost"] * FILLER_CREDITS[rarity])
                    await self.economy.Add(Guild.id, member.id, Amount, "Gacha: mascota sin espacio")
                    Result.detail = f"sin espacio: +{Amount}"
        elif prize["type"] == "item":
            Item = await self.shop.Get(Guild.id, prize["ref"])
            Result.name, Result.emoji = (Item["name"], Item.get("emoji")) if Item else ("Item perdido", "📦")
            if Item:
                await self.shop.Give(Guild.id, member.id, prize["ref"], 1)
                Result.detail = "x1"
        else:
            Amount = int(prize["amount"])
            Currency = config["currency"]
            Result.name, Result.emoji = f"{Amount:,} {Currency['name']}".replace(",", "."), Currency["emoji"]
            await self.economy.Add(Guild.id, member.id, Amount, "Premio del gacha", ref="gacha")
            Result.detail = f"+{Amount:,}".replace(",", ".")
        return Result

    async def History(self, guild_id: int, user_id: int, limit: int = 20) -> list[dict]:
        return await self.pulls.find({"guild_id": guild_id, "user_id": user_id}).sort("ts", -1).limit(limit).to_list(length=limit)
