import asyncio
import io
from datetime import datetime, timezone
from types import SimpleNamespace as N

import pytest
from PIL import Image

from core.economy.boost import Boosted, EarningsMultiplier, GachaSettings, RewardBoost
from core.economy.config import Merge
from core.economy.constants import DEFAULT_CONFIG
from core.economy.petcards import AlbumCard, EvolutionGif, PetCard
from core.economy.service import EconomyService
from tests.economy.fakes import DB

CONFIG = Merge(DEFAULT_CONFIG, {})
SINCE = datetime(2026, 10, 1, 12, 0, 0, 123456, tzinfo=timezone.utc)


def member(since=SINCE, uid=7):
    return N(id=uid, guild=N(id=1), premium_since=since)


def run(coro):
    return asyncio.run(coro)


def test_multiplier_only_for_boosters():
    assert EarningsMultiplier(member(), CONFIG) == pytest.approx(1.3)
    assert EarningsMultiplier(member(since=None), CONFIG) == 1.0
    assert Boosted(100, member(), CONFIG) == 130
    off = Merge(DEFAULT_CONFIG, {"booster": {"enabled": False}})
    assert Boosted(100, member(), off) == 100


def test_gacha_luck_raises_top_rates_and_keeps_room():
    base = CONFIG["gacha"]
    lucky = GachaSettings(member(), CONFIG)
    assert lucky["rate_legendary"] == pytest.approx(base["rate_legendary"] * 1.2)
    assert lucky["rate_epic"] == pytest.approx(base["rate_epic"] * 1.2)
    assert GachaSettings(member(since=None), CONFIG)["rate_legendary"] == base["rate_legendary"]
    assert base["rate_legendary"] == DEFAULT_CONFIG["gacha"]["rate_legendary"]  # not mutated
    huge = Merge(DEFAULT_CONFIG, {"booster": {"gacha_luck": 20}})
    s = GachaSettings(member(), huge)
    assert s["rate_legendary"] + s["rate_epic"] + s["rate_rare"] <= 0.99 + 1e-9


def test_reward_paid_once_per_boost():
    eco = EconomyService(DB())
    run(eco.Setup())
    m = member()
    assert run(RewardBoost(eco, m, CONFIG)) == 500
    assert run(RewardBoost(eco, m, CONFIG)) == 0  # same boost, repeated event / restart
    assert run(eco.PeekBalance(1, 7)) == 500
    # A new boost later pays again
    assert run(RewardBoost(eco, member(since=datetime(2027, 1, 1, tzinfo=timezone.utc)), CONFIG)) == 500
    assert run(RewardBoost(eco, member(since=None, uid=8), CONFIG)) == 0


PET = {
    "name": "Pelusa", "species": "Hámster", "emoji": "🐹", "rarity": "common", "rarity_label": "Común",
    "archetype": "Trabajador", "level": 3, "xp": 10, "xp_next": 40, "hunger": 80, "happiness": 20,
    "care": 0.8, "perk": "+2.0% trabajo", "perk_note": "", "owner": "Victor", "footer": "Forma final",
}


def test_pet_images_render():
    assert Image.open(io.BytesIO(PetCard(PET))).size == (900, 520)
    assert Image.open(io.BytesIO(AlbumCard([PET, {**PET, "active": True}], "Victor"))).format == "PNG"
    gif = Image.open(io.BytesIO(EvolutionGif({"name": "A", "emoji": "🐹", "rarity": "common"}, {"name": "B", "emoji": "🐉", "rarity": "legendary"})))
    assert gif.format == "GIF" and gif.n_frames > 1
