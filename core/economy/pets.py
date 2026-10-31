"""
Pets: species (admin-defined), owned pets, care, XP/levels, evolution and perks.

Hunger and happiness aren't updated by a background task: the stored values
plus the time since `care_at` give the current ones (lazy decay). Every write
saves the current values and resets `care_at`.
"""

import math
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from core.economy.constants import ARCHETYPES, CREATED, MAX_PETS, MAX_SPECIES, MAX_SPECIES_PER_RARITY, PETS, RARITIES, SPECIES, USERS
from core.economy.pet_catalog import ART, STANDALONE, StarterDocs
from core.economy.rewards import Aware
from core.economy.service import EconomyError, EconomyService
from core.economy.shop import NewId

FULL = 100.0
# Care below this average gives no perk; at or above WELL_CARED it gives all of it.
NEGLECTED = 20.0
WELL_CARED = 70.0
NICKNAME_MAX = 24
SPECIES_CACHE_SECONDS = 60
CARE_KINDS = {"food": "hunger", "play": "happiness"}


class PetError(EconomyError):
    """Message is safe to show to users."""


def Now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------- pure logic ----------------


def CurrentCare(pet: dict, now: datetime, config: dict) -> tuple[float, float]:
    """(hunger, happiness) right now, after decay. 100 = full/happy, 0 = starving/sad."""
    Settings = config["pets"]
    Since = Aware(pet.get("care_at")) or now
    Hours = max(0.0, (now - Since).total_seconds() / 3600)
    Hunger = max(0.0, float(pet.get("hunger", FULL)) - Settings["hunger_decay"] * Hours)
    Happiness = max(0.0, float(pet.get("happiness", FULL)) - Settings["happiness_decay"] * Hours)
    return Hunger, Happiness


def CareFactor(hunger: float, happiness: float) -> float:
    """How much of its perk a pet gives (0-1) depending on how well it's cared for."""
    Average = (hunger + happiness) / 2
    return max(0.0, min(1.0, (Average - NEGLECTED) / (WELL_CARED - NEGLECTED)))


def XpToNext(level: int, config: dict) -> int:
    Settings = config["pets"]
    return int(Settings["xp_base"] + Settings["xp_per_level"] * level)


def LevelFor(xp: int, config: dict) -> tuple[int, int, int]:
    """(level, xp into this level, xp needed for the next one) for a total XP."""
    Level, Left = 1, int(xp)
    Max = config["pets"]["max_level"]
    while Level < Max and Left >= XpToNext(Level, config):
        Left -= XpToNext(Level, config)
        Level += 1
    return Level, Left, (XpToNext(Level, config) if Level < Max else 0)


def CareXp(xp: int, config: dict) -> int:
    """XP for one feed/play: a share of what the current level needs (at least 1, 0 at max level)."""
    Needed = LevelFor(xp, config)[2]
    return max(1, math.ceil(Needed * config["pets"]["xp_care_percent"])) if Needed else 0


def IncomePerDay(perk: float, config: dict) -> int:
    """Credits a Rentista pet makes per day for its perk value."""
    return int(round(perk * config["pets"]["income_base"]))


def PerkText(archetype: str, perk: float, config: dict) -> str:
    """How a perk value reads to players ('+12.0% extra en /trabajar', '96 al día ...')."""
    Info = ARCHETYPES[archetype]
    if Info["bonus"] == "income":
        return f"{IncomePerDay(perk, config):,} {Info['perk']}".replace(",", ".")
    return f"+{perk:.1%} {Info['perk']}"


def PerkValue(species: dict, level: int, care: float = 1.0) -> float:
    """Raw perk (0.10 = +10%) before caps."""
    Rarity = RARITIES[species["rarity"]]
    Scale = ARCHETYPES[species["archetype"]]["scale"]
    return (Rarity["base"] + Rarity["per_level"] * (level - 1)) * Scale * care


def CapPerk(bonus: str, value: float, config: dict) -> float:
    Settings = config["pets"]
    if bonus == "luck":
        return min(value, Settings["max_luck"])
    if bonus == "discount":
        return min(value, Settings["max_discount"])
    return value


@dataclass
class PetView:
    """Everything needed to show a pet."""

    pet: dict
    species: dict
    level: int
    xp: int
    xp_next: int
    hunger: float
    happiness: float
    care: float
    perk: float  # after care and caps
    gained: int = 0  # XP from the care action that produced this view


def Describe(pet: dict, species: dict, now: datetime, config: dict) -> PetView:
    Level, Xp, Next = LevelFor(pet.get("xp", 0), config)
    Hunger, Happiness = CurrentCare(pet, now, config)
    Care = CareFactor(Hunger, Happiness)
    Bonus = ARCHETYPES[species["archetype"]]["bonus"]
    return PetView(pet, species, Level, Xp, Next, Hunger, Happiness, Care, CapPerk(Bonus, PerkValue(species, Level, Care), config))


# ---------------- service ----------------


class Pets:
    def __init__(self, db, economy: EconomyService):
        self.species = db[SPECIES]
        self.pets = db[PETS]
        self.users = db[USERS]
        self.economy = economy
        self.economics = None  # set by the registry (inflation)
        self._cache: dict[int, tuple[float, list]] = {}

    async def Setup(self):
        await self.species.create_index([("guild_id", 1), ("species_id", 1)], unique=True)
        await self.pets.create_index([("guild_id", 1), ("user_id", 1), ("species_id", 1)], unique=True)
        await self.pets.create_index([("guild_id", 1), ("pet_id", 1)], unique=True)
        await self.pets.create_index([("guild_id", 1), ("xp", -1)])
        # Starter species loaded before they had drawings get them (custom art is left alone).
        for Key, Art in ART.items():
            await self.species.update_many({"species_id": Key.upper(), "art": None}, {"$set": {"art": Art}})

    # ---- species (admin) ----

    async def AllSpecies(self, guild_id: int) -> list[dict]:
        Cached = self._cache.get(guild_id)
        if not Cached or Cached[0] < time.monotonic():
            All = await self.species.find({"guild_id": guild_id}).to_list(length=MAX_SPECIES * 2)
            Order = list(RARITIES)
            All.sort(key=lambda S: (Order.index(S["rarity"]), S["name"]))
            Cached = (time.monotonic() + SPECIES_CACHE_SECONDS, All)
            self._cache[guild_id] = Cached
        return Cached[1]

    async def GetSpecies(self, guild_id: int, species_id: str) -> dict | None:
        return next((S for S in await self.AllSpecies(guild_id) if S["species_id"] == species_id), None)

    async def CheckRarityRoom(self, guild_id: int, rarity: str, extra: int = 1):
        Count = sum(1 for S in await self.AllSpecies(guild_id) if S["rarity"] == rarity)
        if Count + extra > MAX_SPECIES_PER_RARITY:
            raise PetError(f"Ya hay {MAX_SPECIES_PER_RARITY} especies {RARITIES[rarity]['label'].lower()}s, el máximo por rareza. Borra alguna primero.")

    async def CreateSpecies(self, guild_id: int, data: dict) -> dict:
        await self.CheckRarityRoom(guild_id, data["rarity"])
        Doc = {"guild_id": guild_id, "species_id": NewId(), "enabled": True, "evolves_to": None, "evolve_level": None, "image": None, **data}
        await self.species.insert_one(Doc)
        self._cache.pop(guild_id, None)
        return Doc

    async def UpdateSpecies(self, guild_id: int, species_id: str, data: dict) -> dict | None:
        Current = await self.GetSpecies(guild_id, species_id)
        if Current and data.get("rarity") and data["rarity"] != Current["rarity"]:
            await self.CheckRarityRoom(guild_id, data["rarity"])
        self._cache.pop(guild_id, None)
        return await self.species.find_one_and_update(
            {"guild_id": guild_id, "species_id": species_id}, {"$set": data}, return_document=ReturnDocument.AFTER
        )

    async def DeleteSpecies(self, guild_id: int, species_id: str):
        if await self.pets.count_documents({"guild_id": guild_id, "species_id": species_id}):
            raise PetError("Alguien tiene una mascota de esa especie. Mejor páusala en vez de borrarla.")
        await self.species.delete_one({"guild_id": guild_id, "species_id": species_id})
        await self.species.update_many({"guild_id": guild_id, "evolves_to": species_id}, {"$set": {"evolves_to": None, "evolve_level": None}})
        self._cache.pop(guild_id, None)

    async def SeedStarter(self, guild_id: int) -> int:
        """Loads the example catalog. Returns how many species were added."""
        Existing = {S["species_id"] for S in await self.AllSpecies(guild_id)}
        Docs = [D for D in StarterDocs(guild_id) if D["species_id"] not in Existing]
        for Rarity in RARITIES:
            await self.CheckRarityRoom(guild_id, Rarity, sum(1 for D in Docs if D["rarity"] == Rarity))
        if Docs:
            await self.species.insert_many(Docs)
        # Gacha-only species loaded before the "exclusive" flag existed.
        await self.species.update_many(
            {"guild_id": guild_id, "species_id": {"$in": [K.upper() for K in STANDALONE]}},
            {"$set": {"exclusive": True, "evolves_to": None, "evolve_level": None}},
        )
        self._cache.pop(guild_id, None)
        return len(Docs)

    # ---- owned pets ----

    async def List(self, guild_id: int, user_id: int) -> list[dict]:
        return await self.pets.find({"guild_id": guild_id, "user_id": user_id}).sort("xp", -1).to_list(length=MAX_PETS)

    async def ActiveId(self, guild_id: int, user_id: int) -> str | None:
        Account = await self.users.find_one({"guild_id": guild_id, "user_id": user_id}, {"pet_active": 1})
        return (Account or {}).get("pet_active")

    async def Active(self, guild_id: int, user_id: int) -> dict | None:
        PetId = await self.ActiveId(guild_id, user_id)
        if not PetId:
            return None
        return await self.pets.find_one({"guild_id": guild_id, "user_id": user_id, "pet_id": PetId})

    async def SetActive(self, guild_id: int, user_id: int, pet_id: str) -> dict:
        Pet = await self.pets.find_one({"guild_id": guild_id, "user_id": user_id, "pet_id": pet_id})
        if not Pet:
            raise PetError("Esa mascota no es tuya.")
        await self.economy.Account(guild_id, user_id)
        Previous = await self.ActiveId(guild_id, user_id)
        await self.users.update_one({"guild_id": guild_id, "user_id": user_id}, {"$set": {"pet_active": pet_id}})
        if Previous != pet_id:
            # Only the active pet makes income: it starts counting now.
            await self.pets.update_one({"_id": Pet["_id"]}, {"$set": {"income_at": Now()}})
        return Pet

    async def Grant(self, guild_id: int, user_id: int, species_id: str, source: str, config: dict) -> tuple[dict, bool]:
        """
        Gives a pet. If they already have that species it gets XP instead (duplicate).
        Returns (pet, is_new). Their first pet becomes the active one.
        """
        Species = await self.GetSpecies(guild_id, species_id)
        if not Species:
            raise PetError("Esa especie no existe.")
        Owned = await self.pets.find_one({"guild_id": guild_id, "user_id": user_id, "species_id": species_id})
        if Owned:
            Pet, _, _ = await self.GainXp(Owned, config["pets"]["xp_duplicate"], config)
            return Pet, False
        if await self.pets.count_documents({"guild_id": guild_id, "user_id": user_id}) >= MAX_PETS:
            raise PetError(f"Ya tienes {MAX_PETS} mascotas, no caben más 🏠")
        Pet = {
            "guild_id": guild_id,
            "user_id": user_id,
            "pet_id": NewId(8),
            "species_id": species_id,
            "nickname": None,
            "xp": 0,
            "level": 1,
            "hunger": FULL,
            "happiness": FULL,
            "care_at": Now(),
            "income_at": Now(),
            "last_care": {},
            "source": source,
            "obtained_at": Now(),
        }
        try:
            await self.pets.insert_one(Pet)
        except DuplicateKeyError:
            # Granted twice at the same time: treat the second as a duplicate.
            return await self.Grant(guild_id, user_id, species_id, source, config)
        if not await self.ActiveId(guild_id, user_id):
            await self.SetActive(guild_id, user_id, Pet["pet_id"])
        return Pet, True

    async def GainXp(self, pet: dict, amount: int, config: dict, session=None) -> tuple[dict, int, int]:
        """Adds XP atomically. Returns (pet, old level, new level)."""
        Old = LevelFor(pet.get("xp", 0), config)[0]
        if amount <= 0:
            return pet, Old, Old
        Updated = await self.pets.find_one_and_update(
            {"_id": pet["_id"]}, {"$inc": {"xp": int(amount)}}, return_document=ReturnDocument.AFTER, session=session
        )
        New = LevelFor(Updated["xp"], config)[0]
        if New != Updated.get("level"):
            await self.pets.update_one({"_id": pet["_id"]}, {"$set": {"level": New}}, session=session)
            Updated["level"] = New
        return Updated, Old, New

    async def View(self, pet: dict, config: dict) -> PetView | None:
        Species = await self.GetSpecies(pet["guild_id"], pet["species_id"])
        return Describe(pet, Species, Now(), config) if Species else None

    # ---- care ----

    async def Care(self, guild_id: int, user_id: int, kind: str, config: dict) -> tuple[PetView, int, int]:
        """Feeds (`food`) or plays with (`play`) the active pet. Returns (view, old level, new level)."""
        Stat = CARE_KINDS[kind]
        Settings = config["pets"]
        Price = await self.Cost(guild_id, Settings["food_price" if kind == "food" else "play_price"], config)
        Amount = Settings["food_amount" if kind == "food" else "play_amount"]
        async with self.economy.Lock(guild_id, user_id):
            Pet = await self.Active(guild_id, user_id)
            if not Pet:
                raise PetError("No tienes una mascota activa.")
            Now_ = Now()
            Hunger, Happiness = CurrentCare(Pet, Now_, config)
            Current = {"hunger": Hunger, "happiness": Happiness}
            if Current[Stat] >= FULL - 1:
                raise PetError("Está llenísima 🤰" if kind == "food" else "Ya está feliz de la vida 😊")
            Last = Aware((Pet.get("last_care") or {}).get(kind))
            if Last and (Now_ - Last).total_seconds() < Settings["care_cooldown"]:
                Ready = int(Last.timestamp() + Settings["care_cooldown"])
                raise PetError(f"Dale un respiro, vuelve <t:{Ready}:R>.")
            Current[Stat] = min(FULL, Current[Stat] + Amount)
            async with self.economy.Transaction() as Session:
                if Price:
                    await self.economy.Remove(
                        guild_id, user_id, Price, "Comida para mascota" if kind == "food" else "Jugar con mascota",
                        ref=f"pet:{Pet['pet_id']}", session=Session,
                    )
                await self.pets.update_one(
                    {"_id": Pet["_id"]},
                    {"$set": {**Current, "care_at": Now_, f"last_care.{kind}": Now_}},
                    session=Session,
                )
                Pet.update(Current, care_at=Now_)
                Gained = CareXp(Pet.get("xp", 0), config)
                Pet, Old, New = await self.GainXp(Pet, Gained, config, session=Session)
        View = await self.View(Pet, config)
        View.gained = Gained
        return View, Old, New

    async def Rename(self, guild_id: int, user_id: int, name: str) -> dict:
        Name = " ".join(name.replace("@", "").replace("`", "").split())[:NICKNAME_MAX]
        Pet = await self.Active(guild_id, user_id)
        if not Pet:
            raise PetError("No tienes una mascota activa.")
        await self.pets.update_one({"_id": Pet["_id"]}, {"$set": {"nickname": Name or None}})
        Pet["nickname"] = Name or None
        return Pet

    async def Evolve(self, guild_id: int, user_id: int, config: dict) -> tuple[dict, dict]:
        """Evolves the active pet. Returns (old species, new species)."""
        async with self.economy.Lock(guild_id, user_id):
            Pet = await self.Active(guild_id, user_id)
            if not Pet:
                raise PetError("No tienes una mascota activa.")
            Species = await self.GetSpecies(guild_id, Pet["species_id"])
            Target = await self.GetSpecies(guild_id, Species.get("evolves_to") or "") if Species else None
            if not Species or not Target or Species.get("exclusive") or Target.get("exclusive"):
                raise PetError("Esta mascota no evoluciona.")
            Level = LevelFor(Pet.get("xp", 0), config)[0]
            if Level < int(Species["evolve_level"] or 0):
                raise PetError(f"Tiene que llegar al nivel {Species['evolve_level']} (va por el {Level}).")
            if await self.pets.find_one({"guild_id": guild_id, "user_id": user_id, "species_id": Target["species_id"]}):
                raise PetError(f"Ya tienes un {Target['name']}, no puedes tener dos.")
            Price = await self.Cost(guild_id, config["pets"]["evolve_price"], config)
            async with self.economy.Transaction() as Session:
                if Price:
                    await self.economy.Remove(guild_id, user_id, Price, f"Evolución: {Species['name']}", ref=f"pet:{Pet['pet_id']}", session=Session)
                await self.pets.update_one({"_id": Pet["_id"]}, {"$set": {"species_id": Target["species_id"]}}, session=Session)
        return Species, Target

    async def Cost(self, guild_id: int, base: int, config: dict) -> int:
        """A pet price after inflation."""
        return await self.economics.Price(guild_id, base, config, "pets") if self.economics and base else base

    # ---- perks ----

    async def Collect(self, guild_id: int, user_id: int, config: dict, multiplier: float = 1.0) -> tuple[int, float, PetView]:
        """
        Pays what the active Rentista made since the last collection (up to income_max_hours).
        Returns (credits, hours counted, view). `multiplier` is the booster bonus.
        """
        Settings = config["pets"]
        async with self.economy.Lock(guild_id, user_id):
            Pet = await self.Active(guild_id, user_id)
            if not Pet:
                raise PetError("No tienes una mascota activa.")
            Species = await self.GetSpecies(guild_id, Pet["species_id"])
            if not Species or ARCHETYPES[Species["archetype"]]["bonus"] != "income":
                raise PetError("Tu mascota activa no es 💸 Rentista, así que no genera créditos.")
            Now_ = Now()
            Since = Aware(Pet.get("income_at"))
            if not Since:
                await self.pets.update_one({"_id": Pet["_id"]}, {"$set": {"income_at": Now_}})
                raise PetError("¡Empezó a generar créditos ahora! Vuelve en un rato.")
            View = Describe(Pet, Species, Now_, config)
            Hours = min((Now_ - Since).total_seconds() / 3600, Settings["income_max_hours"])
            Amount = int(IncomePerDay(View.perk, config) * Hours / 24 * multiplier)
            if Amount < 1:
                PerHour = IncomePerDay(View.perk, config) / 24
                if PerHour <= 0:
                    raise PetError("Está tan descuidada que no genera nada 😿 Aliméntala y juega con ella.")
                Ready = int(Since.timestamp() + 3600 / PerHour)
                raise PetError(f"Todavía no generó nada. Vuelve <t:{Ready}:R>.")
            async with self.economy.Transaction() as Session:
                Claimed = await self.pets.update_one(
                    {"_id": Pet["_id"], "income_at": Pet["income_at"]}, {"$set": {"income_at": Now_}}, session=Session
                )
                if not Claimed.modified_count:
                    raise PetError("Ya lo cobraste.")
                await self.economy.Add(
                    guild_id, user_id, Amount, f"Ingresos de {Species['name']}", kind=CREATED,
                    ref=f"pet:{Pet['pet_id']}", session=Session,
                )
        return Amount, Hours, View

    async def Perk(self, guild_id: int, user_id: int, bonus: str, config: dict) -> float:
        """What the active pet gives for `bonus` (work, chat, luck or discount)."""
        Pet = await self.Active(guild_id, user_id)
        if not Pet:
            return 0.0
        Species = await self.GetSpecies(guild_id, Pet["species_id"])
        if not Species or ARCHETYPES[Species["archetype"]]["bonus"] != bonus:
            return 0.0
        return Describe(Pet, Species, Now(), config).perk
