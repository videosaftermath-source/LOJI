import asyncio
import random
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as N

import pytest

from core.economy.config import Merge
from core.economy.constants import DEFAULT_CONFIG
from core.economy.gacha import GachaError, LegendaryRate, PickPrize, Pity, Problems, Pull, RollRarity, Status
from core.economy.registry import Build
from core.economy.service import EconomyService, InsufficientFunds
from tests.economy.fakes import DB

CONFIG = Merge(DEFAULT_CONFIG, {})
S = CONFIG["gacha"]
G = 1


class Fixed(random.Random):
    """rng that always rolls the same number (to force worst luck)."""

    def __init__(self, value):
        super().__init__(0)
        self.value = value

    def random(self):
        return self.value


def pool(featured=True):
    return [
        {"key": "L1", "rarity": "legendary", "featured": featured, "type": "credits", "amount": 1},
        {"key": "L2", "rarity": "legendary", "featured": False, "type": "credits", "amount": 2},
        {"key": "E1", "rarity": "epic", "featured": featured, "type": "credits", "amount": 3},
        {"key": "E2", "rarity": "epic", "featured": False, "type": "credits", "amount": 4},
        {"key": "R", "rarity": "rare", "type": "credits", "amount": 5},
        {"key": "C", "rarity": "common", "type": "credits", "amount": 6},
    ]


def test_legendary_rate_curve():
    assert LegendaryRate(1, S) == S["rate_legendary"]
    assert LegendaryRate(S["soft_pity"] - 1, S) == S["rate_legendary"]
    assert LegendaryRate(S["soft_pity"], S) == pytest.approx(S["rate_legendary"] + S["soft_step"])
    assert LegendaryRate(S["hard_pity"], S) == 1


def test_hard_pity_with_worst_luck():
    p = Pity()
    rarities = [RollRarity(p, S, Fixed(0.9999)) for _ in range(S["hard_pity"])]
    assert rarities[-1] == "legendary"
    assert "legendary" not in rarities[:-1]
    # Epic guaranteed every epic_pity pulls meanwhile.
    assert all(rarities[i] == "epic" for i in range(S["epic_pity"] - 1, S["hard_pity"] - 1, S["epic_pity"]))


def test_rates_over_many_pulls():
    rng = random.Random(42)
    p = Pity()
    n = 300_000
    counts = {"legendary": 0, "epic": 0, "rare": 0, "common": 0}
    for _ in range(n):
        counts[RollRarity(p, S, rng)] += 1
    # Genshin-like consolidated rates: ~1.6% legendary (one every ~62 pulls), ~13% epic.
    assert 55 < n / counts["legendary"] < 70
    assert 0.11 < counts["epic"] / n < 0.15


def test_fifty_fifty_and_guarantee():
    rng = random.Random(7)
    p = Pity()
    featured = total = 0
    lost_then = []
    for _ in range(20_000):
        was_guaranteed = p.legendary_guaranteed
        prize, is_featured = PickPrize(pool(), "legendary", p, S, rng)
        assert prize["rarity"] == "legendary"
        if was_guaranteed:
            lost_then.append(is_featured)
        featured += is_featured
        total += 1
    assert all(lost_then)  # after losing the 50/50 you always get the featured one
    assert featured / total == pytest.approx(2 / 3, abs=0.02)


def test_no_featured_means_no_guarantee_state():
    p = Pity()
    prize, featured = PickPrize(pool(featured=False), "legendary", p, S, random.Random(1))
    assert not featured and not p.legendary_guaranteed


def test_missing_rarity_falls_back_lower():
    only_common = [{"key": "C", "rarity": "common", "type": "credits", "amount": 1}]
    prize, _ = PickPrize(only_common, "legendary", Pity(), S, random.Random(1))
    assert prize["key"] == "C"


def test_pull_count_and_counters():
    p = Pity()
    results = Pull(pool(), p, 10, S, random.Random(3))
    assert len(results) == 10
    assert p.total == 10
    assert any(r in ("epic", "legendary") for _, r, _ in results)  # epic pity


def test_problems_and_status():
    now = datetime.now(timezone.utc)
    b = {"pool": pool(), "start": now - timedelta(days=1), "end": now + timedelta(days=1), "enabled": True}
    assert Problems(b) == []
    assert Status(b, now) == "active"
    assert Status({**b, "enabled": False}, now) == "paused"
    assert Status({**b, "start": now + timedelta(days=1), "end": now + timedelta(days=2)}, now) == "scheduled"
    assert Status({**b, "end": now - timedelta(hours=1)}, now) == "ended"
    assert len(Problems({**b, "pool": [P for P in pool() if P["rarity"] != "epic"]})) == 1


# ---- service ----


def run(coro):
    return asyncio.run(coro)


def services():
    s = Build(EconomyService(DB()))
    run(s.Setup())
    run(s.pets.SeedStarter(G))
    return s


def member(uid):
    return N(id=uid, guild=N(id=G))


def banner(s):
    now = datetime.now(timezone.utc)
    b = run(s.gacha.Create(G, {"name": "Test", "description": "", "cost": 100, "start": now - timedelta(minutes=1), "end": now + timedelta(days=7)}))
    with pytest.raises(GachaError):
        run(s.gacha.SetEnabled(G, b["banner_id"], True))  # empty pool
    run(s.gacha.AddPrizes(G, b["banner_id"], [{"type": "pet", "ref": "DRAGON", "rarity": "legendary"}, {"type": "pet", "ref": "OWL", "rarity": "epic"}]))
    run(s.gacha.FillMissing(G, b["banner_id"]))
    return run(s.gacha.SetEnabled(G, b["banner_id"], True))


def test_banner_setup():
    s = services()
    b = banner(s)
    assert sorted(P["rarity"] for P in b["pool"]) == ["common", "epic", "legendary", "rare"]
    assert run(s.gacha.Active(G))[0]["banner_id"] == b["banner_id"]
    # Adding the same prize twice doesn't duplicate it.
    again = run(s.gacha.AddPrizes(G, b["banner_id"], [{"type": "pet", "ref": "DRAGON", "rarity": "legendary"}]))
    assert len(again["pool"]) == 4
    # Removing the only epic pauses the banner.
    epic = next(P for P in again["pool"] if P["rarity"] == "epic")
    after = run(s.gacha.RemovePrize(G, b["banner_id"], epic["key"]))
    assert not after["enabled"]


def test_pull_charges_saves_pity_and_gives_prizes():
    s = services()
    b = banner(s)
    run(s.economy.Add(G, 5, 5000, "seed"))
    out = run(s.gacha.DoPull(member(5), b["banner_id"], 10, CONFIG))
    assert out.paid == 1000 and len(out.results) == 10
    credits = sum(int(R.prize.get("amount", 0)) for R in out.results if R.prize["type"] == "credits")
    assert run(s.economy.Balance(G, 5)) == 4000 + credits == out.balance
    pity = run(s.gacha.UserPity(G, 5, b["banner_id"]))
    assert pity.total == 10
    pets = [R for R in out.results if R.prize["type"] == "pet"]
    assert len(run(s.pets.List(G, 5))) == len({R.prize["ref"] for R in pets})
    assert len(run(s.gacha.History(G, 5))) == 10


def test_pull_without_money_keeps_pity():
    s = services()
    b = banner(s)
    run(s.economy.Add(G, 5, 150, "seed"))
    with pytest.raises(InsufficientFunds):
        run(s.gacha.DoPull(member(5), b["banner_id"], 10, CONFIG))
    assert run(s.gacha.UserPity(G, 5, b["banner_id"])).total == 0
    assert run(s.economy.Balance(G, 5)) == 150


def test_cant_pull_on_paused_or_ended_banner():
    s = services()
    b = banner(s)
    run(s.economy.Add(G, 5, 5000, "seed"))
    run(s.gacha.SetEnabled(G, b["banner_id"], False))
    with pytest.raises(GachaError):
        run(s.gacha.DoPull(member(5), b["banner_id"], 1, CONFIG))
    run(s.gacha.SetEnabled(G, b["banner_id"], True))
    run(s.gacha.Update(G, b["banner_id"], {"end": datetime.now(timezone.utc) - timedelta(seconds=1)}))
    with pytest.raises(GachaError):
        run(s.gacha.DoPull(member(5), b["banner_id"], 1, CONFIG))


def test_concurrent_pulls_charge_correctly():
    s = services()
    b = banner(s)
    run(s.economy.Add(G, 5, 350, "seed"))  # enough for 3 single pulls

    async def spam():
        return await asyncio.gather(*(s.gacha.DoPull(member(5), b["banner_id"], 1, CONFIG) for _ in range(6)), return_exceptions=True)

    results = run(spam())
    ok = [r for r in results if not isinstance(r, Exception)]
    won = sum(int(R.prize.get("amount", 0)) for o in ok for R in o.results if R.prize["type"] == "credits")
    # Credit prizes can pay for more pulls, but the books must balance exactly and never go negative.
    assert len(ok) >= 3
    assert run(s.economy.Balance(G, 5)) == 350 - 100 * len(ok) + won >= 0
    assert run(s.gacha.UserPity(G, 5, b["banner_id"])).total == len(ok)
