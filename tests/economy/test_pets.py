import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from core.economy.config import Merge
from core.economy.constants import DEFAULT_CONFIG, LEDGER
from core.economy.pets import CapPerk, CareFactor, CurrentCare, LevelFor, PerkValue, PetError, XpToNext
from core.economy.registry import Build
from core.economy.service import EconomyService, InsufficientFunds
from tests.economy.fakes import DB

CONFIG = Merge(DEFAULT_CONFIG, {})
P = CONFIG["pets"]
G = 1
NOW = datetime(2026, 10, 24, 12, tzinfo=timezone.utc)


def run(coro):
    return asyncio.run(coro)


def services():
    s = Build(EconomyService(DB()))
    run(s.Setup())
    run(s.pets.SeedStarter(G))
    return s


# ---- pure logic ----


def test_care_decays_over_time():
    pet = {"hunger": 100, "happiness": 80, "care_at": NOW - timedelta(hours=10)}
    hunger, happiness = CurrentCare(pet, NOW, CONFIG)
    assert hunger == pytest.approx(100 - 10 * P["hunger_decay"])
    assert happiness == pytest.approx(80 - 10 * P["happiness_decay"])
    assert CurrentCare({"hunger": 5, "happiness": 5, "care_at": NOW - timedelta(days=9)}, NOW, CONFIG) == (0, 0)


def test_naive_care_time_from_mongo():
    pet = {"hunger": 100, "happiness": 100, "care_at": (NOW - timedelta(hours=1)).replace(tzinfo=None)}
    assert CurrentCare(pet, NOW, CONFIG)[0] == pytest.approx(100 - P["hunger_decay"])


@pytest.mark.parametrize("hunger,happiness,factor", [(100, 100, 1), (70, 70, 1), (45, 45, 0.5), (20, 20, 0), (0, 0, 0), (100, 0, 0.6)])
def test_care_factor(hunger, happiness, factor):
    assert CareFactor(hunger, happiness) == pytest.approx(factor)


def test_levels():
    assert LevelFor(0, CONFIG) == (1, 0, XpToNext(1, CONFIG))
    assert LevelFor(XpToNext(1, CONFIG), CONFIG)[0] == 2
    assert LevelFor(10**9, CONFIG)[0] == P["max_level"]
    assert LevelFor(10**9, CONFIG)[2] == 0  # nothing left at max


def test_perk_by_rarity_level_and_care():
    common = {"rarity": "common", "archetype": "farmer"}
    legendary = {"rarity": "legendary", "archetype": "farmer"}
    assert PerkValue(common, 1) == pytest.approx(0.03)
    assert PerkValue(legendary, 30) == pytest.approx(0.12 + 0.01 * 29)
    assert PerkValue(legendary, 30, care=0.5) == pytest.approx((0.12 + 0.01 * 29) / 2)
    assert PerkValue(common, 10) > PerkValue(common, 1)
    lucky = {"rarity": "legendary", "archetype": "lucky"}
    assert CapPerk("luck", PerkValue(lucky, 30), CONFIG) == P["max_luck"]


# ---- service ----


def test_seed_catalog_and_evolution_chain():
    s = services()
    species = run(s.pets.AllSpecies(G))
    assert len(species) == 17
    assert run(s.pets.GetSpecies(G, "DOLPHIN"))["evolves_to"] == "EAGLE"  # the gacha-only wolf doesn't steal the chain
    assert run(s.pets.GetSpecies(G, "WOLF"))["rarity"] == "legendary"
    hamster = run(s.pets.GetSpecies(G, "HAMSTER"))
    assert hamster["evolves_to"] == "BEAVER" and hamster["evolve_level"] == 10
    assert run(s.pets.GetSpecies(G, "DRAGON"))["evolves_to"] is None
    assert run(s.pets.SeedStarter(G)) == 0  # loading twice adds nothing


def test_grant_first_pet_becomes_active_and_duplicate_gives_xp():
    s = services()
    pet, new = run(s.pets.Grant(G, 5, "HAMSTER", "test", CONFIG))
    assert new and run(s.pets.ActiveId(G, 5)) == pet["pet_id"]
    again, new = run(s.pets.Grant(G, 5, "HAMSTER", "test", CONFIG))
    assert not new and again["xp"] == P["xp_duplicate"]
    other, _ = run(s.pets.Grant(G, 5, "PARROT", "test", CONFIG))
    assert run(s.pets.ActiveId(G, 5)) == pet["pet_id"]  # still the first one
    assert len(run(s.pets.List(G, 5))) == 2
    with pytest.raises(PetError):
        run(s.pets.Grant(G, 5, "NOPE", "test", CONFIG))


def test_concurrent_grants_dont_duplicate():
    s = services()

    async def many():
        return await asyncio.gather(*(s.pets.Grant(G, 5, "HAMSTER", "t", CONFIG) for _ in range(5)))

    results = run(many())
    assert sum(new for _, new in results) == 1
    assert len(run(s.pets.List(G, 5))) == 1


def test_feeding_costs_credits_gives_xp_and_respects_cooldown():
    s = services()
    run(s.economy.Add(G, 5, 1000, "seed"))
    pet, _ = run(s.pets.Grant(G, 5, "HAMSTER", "t", CONFIG))
    with pytest.raises(PetError):
        run(s.pets.Care(G, 5, "food", CONFIG))  # full: nothing charged
    assert run(s.economy.Balance(G, 5)) == 1000
    s.pets.pets.c.update_one({"pet_id": pet["pet_id"]}, {"$set": {"hunger": 20}})
    view, old, new = run(s.pets.Care(G, 5, "food", CONFIG))
    assert view.hunger == pytest.approx(20 + P["food_amount"], abs=0.1)
    assert view.pet["xp"] == P["xp_care"]
    assert run(s.economy.Balance(G, 5)) == 1000 - P["food_price"]
    with pytest.raises(PetError):
        run(s.pets.Care(G, 5, "food", CONFIG))  # cooldown
    assert run(s.economy.Balance(G, 5)) == 1000 - P["food_price"]
    entry = s.economy.ledger.c.find_one({"reason": "Comida para mascota"})
    assert entry["kind"] == "destroyed"  # care is a credit sink


def test_care_without_money():
    s = services()
    pet, _ = run(s.pets.Grant(G, 5, "HAMSTER", "t", CONFIG))
    s.pets.pets.c.update_one({"pet_id": pet["pet_id"]}, {"$set": {"happiness": 10}})
    with pytest.raises(InsufficientFunds):
        run(s.pets.Care(G, 5, "play", CONFIG))
    assert s.pets.pets.c.find_one({"pet_id": pet["pet_id"]})["happiness"] == 10


def test_care_double_click_charges_once():
    s = services()
    run(s.economy.Add(G, 5, 1000, "seed"))
    pet, _ = run(s.pets.Grant(G, 5, "HAMSTER", "t", CONFIG))
    s.pets.pets.c.update_one({"pet_id": pet["pet_id"]}, {"$set": {"hunger": 10}})

    async def spam():
        return await asyncio.gather(*(s.pets.Care(G, 5, "food", CONFIG) for _ in range(5)), return_exceptions=True)

    results = run(spam())
    assert sum(not isinstance(r, Exception) for r in results) == 1
    assert run(s.economy.Balance(G, 5)) == 1000 - P["food_price"]


def test_perk_feeds_bonuses_and_global_cap():
    s = services()
    run(s.pets.Grant(G, 5, "DRAGON", "t", CONFIG))
    perk = run(s.pets.Perk(G, 5, "work", CONFIG))
    assert perk == pytest.approx(0.12)
    assert run(s.pets.Perk(G, 5, "chat", CONFIG)) == 0  # wrong archetype
    assert run(s.bonuses.Total(G, 5, "work", CONFIG)) == pytest.approx(0.12)
    run(s.bonuses.Add(G, 5, "work", 0.95, 3600, "test"))
    assert run(s.bonuses.Total(G, 5, "work", CONFIG)) == CONFIG["bonuses"]["max"]


def test_neglected_pet_gives_no_perk():
    s = services()
    pet, _ = run(s.pets.Grant(G, 5, "DRAGON", "t", CONFIG))
    s.pets.pets.c.update_one({"pet_id": pet["pet_id"]}, {"$set": {"care_at": datetime.now(timezone.utc) - timedelta(days=5)}})
    assert run(s.pets.Perk(G, 5, "work", CONFIG)) == 0


def test_saver_discounts_shop_and_fees():
    from core.economy.tax import TransferFee
    from tests.economy.test_shop import member

    s = services()
    run(s.economy.Add(G, 5, 1000, "seed"))
    run(s.pets.Grant(G, 5, "TURTLE", "t", CONFIG))
    discount = run(s.pets.Perk(G, 5, "discount", CONFIG))
    assert discount == pytest.approx(0.12 * 0.6)
    item = run(s.shop.Create(G, {"name": "X", "price": 1000, "type": "collectible", "stock": None, "per_user_limit": None}))
    run(s.economy.Add(G, 5, 1000, "seed"))
    _, total, _ = run(s.shop.Buy(member(5), item["item_id"], 1, CONFIG))
    assert total == round(1000 * (1 - discount))
    assert TransferFee(1000, CONFIG, discount) < TransferFee(1000, CONFIG)


def test_switch_rename_and_evolve():
    s = services()
    run(s.economy.Add(G, 5, 10_000, "seed"))
    pet, _ = run(s.pets.Grant(G, 5, "HAMSTER", "t", CONFIG))
    renamed = run(s.pets.Rename(G, 5, "  @Pelusa   la grande `x` "))
    assert renamed["nickname"] == "Pelusa la grande x"
    with pytest.raises(PetError):
        run(s.pets.Evolve(G, 5, CONFIG))  # level too low
    run(s.pets.GainXp(pet, 10**6, CONFIG))
    old, new = run(s.pets.Evolve(G, 5, CONFIG))
    assert (old["species_id"], new["species_id"]) == ("HAMSTER", "BEAVER")
    assert run(s.economy.Balance(G, 5)) == 10_000 - P["evolve_price"]
    assert run(s.pets.Active(G, 5))["species_id"] == "BEAVER"
    # Can't evolve into a species you already own.
    run(s.pets.Grant(G, 5, "OX", "t", CONFIG))
    with pytest.raises(PetError):
        run(s.pets.Evolve(G, 5, CONFIG))
    with pytest.raises(PetError):
        run(s.pets.SetActive(G, 6, pet["pet_id"]))  # not theirs


def test_delete_species_in_use_is_blocked():
    s = services()
    run(s.pets.Grant(G, 5, "HAMSTER", "t", CONFIG))
    with pytest.raises(PetError):
        run(s.pets.DeleteSpecies(G, "HAMSTER"))
    run(s.pets.DeleteSpecies(G, "BEAVER"))
    assert run(s.pets.GetSpecies(G, "HAMSTER"))["evolves_to"] is None


def test_species_limit_is_per_rarity():
    from core.economy.constants import MAX_SPECIES_PER_RARITY
    from core.economy.pets import PetError

    s = services()
    have = sum(1 for x in run(s.pets.AllSpecies(G)) if x["rarity"] == "epic")
    for i in range(MAX_SPECIES_PER_RARITY - have):
        run(s.pets.CreateSpecies(G, {"name": f"E{i}", "emoji": "🐾", "rarity": "epic", "archetype": "farmer", "description": ""}))
    with pytest.raises(PetError):
        run(s.pets.CreateSpecies(G, {"name": "X", "emoji": "🐾", "rarity": "epic", "archetype": "farmer", "description": ""}))
    run(s.pets.CreateSpecies(G, {"name": "R", "emoji": "🐾", "rarity": "rare", "archetype": "farmer", "description": ""}))  # other rarities still fit
    with pytest.raises(PetError):
        run(s.pets.UpdateSpecies(G, "HAMSTER", {"rarity": "epic"}))
