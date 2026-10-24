import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as N

import pytest

from core.economy.config import Merge
from core.economy.constants import DEFAULT_CONFIG
from core.economy.economics import BankError, Inflate, Interest, NextMultiplier, TargetMultiplier, WithdrawFee
from core.economy.registry import Build
from core.economy.service import EconomyService, InsufficientFunds
from core.economy.shop import DemandBump, Price
from tests.economy.fakes import DB

CONFIG = Merge(DEFAULT_CONFIG, {})
INF = CONFIG["inflation"]
G = 1


def run(coro):
    return asyncio.run(coro)


def services():
    s = Build(EconomyService(DB()))
    run(s.Setup())
    return s


def cfg(**sections):
    return Merge(DEFAULT_CONFIG, sections)


# ---- inflation math ----


def test_target_multiplier():
    target = INF["target_per_user"]
    assert TargetMultiplier(target * 10, 10, INF) == pytest.approx(1.0)
    assert TargetMultiplier(target * 40, 10, INF) == pytest.approx(2.0)  # 4x the money -> sqrt -> 2x prices
    assert TargetMultiplier(target * 1000, 10, INF) == INF["max"]
    assert TargetMultiplier(1, 10, INF) == INF["min"]
    assert TargetMultiplier(0, 0, INF) == 1.0


def test_next_multiplier_moves_slowly():
    assert NextMultiplier(1.0, 2.0, INF) == pytest.approx(1 + INF["max_step"])
    assert NextMultiplier(1.0, 0.5, INF) == pytest.approx(1 - INF["max_step"])
    assert NextMultiplier(1.0, 1.01, INF) == pytest.approx(1.01)
    assert NextMultiplier(INF["max"], 99, INF) == INF["max"]


def test_inflate():
    assert Inflate(100, 1.05) == 105 and Inflate(1, 0.5) == 1


# ---- demand ----


def test_demand_decays_by_half_life():
    now = datetime.now(timezone.utc)
    item = {"price": 1000, "demand": {"bump": 0.4, "at": now - timedelta(hours=CONFIG["shop"]["demand_half_life"])}}
    assert DemandBump(item, CONFIG, now) == pytest.approx(0.2)
    assert Price(item, CONFIG, now=now) == 1200
    assert Price(item, CONFIG, discount=0.1, multiplier=1.5, now=now) == round(1000 * 1.5 * 1.2 * 0.9)
    own = {"price": 1000, "demand": {"bump": 0.4, "at": now - timedelta(hours=2), "half_life": 2}}
    assert DemandBump(own, CONFIG, now) == pytest.approx(0.2)  # the item's own half-life wins


def test_buying_raises_price_and_caps():
    from tests.economy.test_shop import member

    s = services()
    run(s.economy.Add(G, 5, 10**7, "seed"))
    item = run(s.shop.Create(G, {"name": "X", "price": 100, "type": "collectible", "stock": None, "per_user_limit": None}))
    run(s.shop.Buy(member(5), item["item_id"], 5, CONFIG))
    after = run(s.shop.Get(G, item["item_id"]))
    assert DemandBump(after, CONFIG) == pytest.approx(5 * CONFIG["shop"]["demand_step"], rel=0.01)
    run(s.shop.Buy(member(5), item["item_id"], 100, CONFIG))
    assert DemandBump(run(s.shop.Get(G, item["item_id"])), CONFIG) <= CONFIG["shop"]["demand_max"] + 1e-9
    _, total, _ = run(s.shop.Buy(member(5), item["item_id"], 1, CONFIG))
    assert total > 100  # pays the higher price


# ---- inflation service ----


def test_supply_and_update_inflation():
    s = services()
    now = datetime.now(timezone.utc)
    for uid in range(4):
        run(s.economy.Add(G, uid, 100_000, "seed", also_set={"last_active": now}))
    run(s.economy.Add(G, 9, 999_999, "old", also_set={"last_active": now - timedelta(days=60)}))
    supply = run(s.economics.Supply(G, 14))
    assert supply == {"total": 1_399_999, "active": 400_000, "active_users": 4}
    doc = run(s.economics.UpdateInflation(G, CONFIG))
    assert doc["multiplier"] == pytest.approx(1.05)  # 4x the target per user -> moves up one max step
    assert run(s.economics.UpdateInflation(G, CONFIG)) is None  # not due yet
    assert run(s.economics.UpdateInflation(G, CONFIG, force=True))["multiplier"] == pytest.approx(1.05 * 1.05, rel=1e-3)
    s.economics._multiplier.clear()
    assert run(s.economics.Price(G, 100, CONFIG)) == 110
    off = cfg(inflation={"enabled": False})
    assert run(s.economics.Multiplier(G, off)) == 1.0
    nogacha = cfg(inflation={"gacha": False})
    assert run(s.economics.Price(G, 100, nogacha, "gacha")) == 100


def test_inflation_reaches_pets_and_gacha():
    s = services()
    run(s.economics.state.update_one({"_id": G}, {"$set": {"inflation": {"multiplier": 2.0, "updated_at": datetime.now(timezone.utc)}}}, upsert=True))
    assert run(s.pets.Cost(G, 60, CONFIG)) == 120
    assert run(s.gacha.PullCost(G, {"cost": 150}, CONFIG)) == 300


# ---- bank ----


def test_bank_deposit_withdraw_and_fee():
    s = services()
    run(s.economy.Add(G, 5, 1000, "seed"))
    acc = run(s.economics.Deposit(G, 5, 800))
    assert (acc["balance"], acc["bank"]) == (200, 800)
    with pytest.raises(InsufficientFunds):
        run(s.economics.Deposit(G, 5, 500))
    acc, fee = run(s.economics.Withdraw(G, 5, 500, CONFIG))
    assert fee == WithdrawFee(500, CONFIG) == 5
    assert (acc["balance"], acc["bank"]) == (200 + 495, 300)
    with pytest.raises(BankError):
        run(s.economics.Withdraw(G, 5, 301, CONFIG))
    with pytest.raises(BankError):
        run(s.economics.Deposit(G, 5, 0))


def test_interest_once_per_day_and_capped():
    s = services()
    bank = cfg(bank={"enabled": True, "interest": 0.01, "interest_cap": 1000})
    run(s.economy.Add(G, 5, 5000, "seed"))
    run(s.economics.Deposit(G, 5, 5000))
    assert Interest(5000, bank) == 10  # only the first 1000 earns
    assert run(s.economics.PayInterest(G, bank)) == 10
    assert run(s.economics.PayInterest(G, bank)) == 0  # same day: nothing
    assert run(s.economy.Account(G, 5))["bank"] == 5010
    assert run(s.economics.PayInterest(G, CONFIG)) == 0  # bank disabled by default


# ---- stats ----


def test_flows_add_up_to_the_real_change():
    from core.economy.casino import Casino

    s = services()
    since = datetime.now(timezone.utc) - timedelta(minutes=1)
    run(s.economy.Add(G, 1, 10_000, "work"))                       # +10000 created
    run(s.economy.Remove(G, 1, 1_000, "shop"))                      # -1000 destroyed
    run(s.economy.Transfer(G, 1, 2, 2_000, "pay", fee=100))        # -100 tax
    run(s.economics.Deposit(G, 2, 1_000))                           # 0 (moves to bank)
    run(s.economics.Withdraw(G, 2, 500, CONFIG))                    # -5 fee
    bank = cfg(bank={"enabled": True, "interest": 0.01})
    run(s.economics.PayInterest(G, bank))                           # +5 interest (500 left in bank)
    member = N(id=1, guild=N(id=G))
    run(s.casino.Start(member, "coinflip", "500", CONFIG))          # -500 bet
    run(s.casino.Pay(member, "coinflip", 980))                      # +980 payout
    flows = run(s.economics.Flows(G, since))
    supply = run(s.economics.Supply(G, 14))["total"]
    assert flows["net"] == supply  # everything started at 0
    assert flows["created"] == 10_005
    assert flows["destroyed"] == 1_000
    assert flows["taxes"] == 105
    assert flows["casino"] == -480  # players won this time
    run(s.economics.Snapshot(G, CONFIG))
    history = run(s.economics.History(G))
    assert len(history) == 1 and history[0]["supply"] == supply
    assert [r["user_id"] for r in run(s.economics.Richest(G))][0] == 1


def test_stats_chart_renders():
    from core.economy.charts import StatsChart

    assert StatsChart([], "Créditos")[:4] == b"\x89PNG"
    assert StatsChart([{"date": "2026-10-24", "supply": 1000, "created": 10, "destroyed": 5}], "Créditos")[:4] == b"\x89PNG"
