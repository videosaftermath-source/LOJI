import asyncio
import random
from types import SimpleNamespace as N

import pytest

import core.economy.marcha as M
from core.economy.config import Merge
from core.economy.constants import DEFAULT_CONFIG
from core.economy.registry import Build
from core.economy.service import EconomyService, InsufficientFunds
from tests.economy.fakes import DB

CONFIG = Merge(DEFAULT_CONFIG, {})
G = 1


def run(coro):
    return asyncio.run(coro)


@pytest.mark.parametrize(
    "cards,hand,scoring",
    [
        (["AS", "KS", "QS", "JS", "TS"], "straight_flush", 5),
        (["9H", "9S", "9D", "9C", "2H"], "four", 4),
        (["9H", "9S", "9D", "2C", "2H"], "full_house", 5),
        (["2H", "7H", "9H", "JH", "KH"], "flush", 5),
        (["AH", "2S", "3D", "4C", "5H"], "straight", 5),
        (["9H", "9S", "9D", "2C"], "three", 3),
        (["9H", "9S", "2D", "2C", "KH"], "two_pair", 4),
        (["9H", "9S", "KD"], "pair", 2),
        (["9H", "KS", "2D"], "high", 1),
        (["2H", "3H", "4H", "5H"], "high", 1),  # 4 suited cards aren't a flush
    ],
)
def test_evaluate(cards, hand, scoring):
    Hand, Scoring = M.Evaluate(cards)
    assert Hand == hand and len(Scoring) == scoring


def test_score_adds_scoring_cards_only():
    s = M.Score(["KH", "KS", "2D"])  # pair of kings: 10 + 10 + 10 chips, x2
    assert (s["chips"], s["mult"], s["total"]) == (30, 2, 60)
    assert M.Score(["AH"])["total"] == (5 + 11) * 1


def test_game_flow():
    rng = random.Random(1)
    g = M.NewGame(100, rng)
    assert len(g["hand"]) == M.HAND_SIZE and g["hands"] == M.HANDS and g["money"] == M.START_MONEY
    with pytest.raises(ValueError):
        M.Play(g, ["XX"])
    with pytest.raises(ValueError):
        M.Play(g, g["hand"][:6])
    M.Discard(g, g["hand"][:3])
    assert g["discards"] == M.DISCARDS - 1 and len(g["hand"]) == M.HAND_SIZE
    # Beat the first blind with 2 hands left after this one: reward 3 + 2 left + interest 0
    g["score"] = M.Target(0, 0) - 1
    M.Play(g, g["hand"][:1], rng)
    assert g["state"] == "shop" and g["earned"]["total"] == 3 + 3 and g["money"] == M.START_MONEY + 6
    assert len(g["shop"]) == M.SHOP_SLOTS
    M.NextBlind(g, rng)
    assert (g["ante"], g["blind"], g["state"]) == (0, 1, "playing")
    for _ in range(M.HANDS):
        if g["state"] == "playing":
            g["score"] = 0
            M.Play(g, g["hand"][:1], rng)
    assert g["state"] == "failed"


def test_boss_gives_the_ante_choice_and_prize():
    rng = random.Random(2)
    g = M.NewGame(1000, rng)
    g["blind"] = len(M.BLINDS) - 1
    M.NewBlind(g, rng)
    g["score"] = M.Target(0, g["blind"])
    M.Play(g, g["hand"][:1], rng)
    assert g["state"] == "ante_cleared" and g["cleared"] == 1 and M.Prize(g) == int(1000 * M.LADDER[0])
    M.EnterShop(g)
    M.NextBlind(g, rng)
    assert (g["ante"], g["blind"]) == (1, 0)


def test_jokers_levels_and_contains():
    base = M.Score(["KH", "KS", "2D"])
    assert (base["chips"], base["mult"]) == (30, 2)
    g = {"jokers": ["camarada", "doble", "colmena", "corazon"], "levels": {"pair": 2}}
    s = M.Score(["KH", "KS", "2D"], g)
    # pair lv2: 25 chips / 3 mult; +10+10 card chips; corazon +3 (KH); camarada +4; doble +8; colmena x2
    assert s["chips"] == 45 and s["mult"] == (3 + 3 + 4 + 8) * 2 and s["total"] == 45 * 36
    assert set(s["triggered"]) == {"camarada", "doble", "colmena", "corazon"}
    assert {"pair", "three", "two_pair"} <= M.Contains(["9H", "9S", "9D", "2C", "2H"], "full_house")
    assert M.Score(["2H", "4S"], {"jokers": ["media"]})["mult"] == 1 + 20


def test_shop_buy_sell_reroll():
    rng = random.Random(3)
    g = M.NewGame(100, rng)
    g["state"], g["money"], g["reroll"] = "shop", 20, M.REROLL_BASE
    g["shop"] = [{"type": "joker", "id": "ojo", "price": 9}, {"type": "planet", "hand": "flush", "price": 3}]
    M.Buy(g, 0)
    M.Buy(g, 1)
    assert g["jokers"] == ["ojo"] and g["levels"]["flush"] == 2 and g["money"] == 8
    with pytest.raises(ValueError):
        M.Buy(g, 0)  # sold out
    M.Reroll(g, rng)
    assert g["money"] == 3 and g["reroll"] == M.REROLL_BASE + 1 and all(g["shop"])
    with pytest.raises(ValueError):
        M.Reroll(g, rng)  # can't afford
    assert M.Sell(g, 0) == M.SellValue("ojo") and g["jokers"] == []


def test_interest_is_capped():
    g = {"blind": 0, "hands": 0, "money": 100}
    assert M.Earnings(g)["interest"] == M.INTEREST_MAX


def services():
    s = Build(EconomyService(DB()))
    run(s.Setup())
    return s


def member(uid):
    return N(id=uid, guild=N(id=G))


def test_start_charges_limits_and_pays_once():
    s = services()
    m = member(5)
    run(s.economy.Add(G, 5, 10_000, "seed"))
    game, left = run(s.marcha.Start(m, "1000", CONFIG))
    assert left == CONFIG["casino"]["marcha"]["daily_limit"] - 1
    assert run(s.economy.PeekBalance(G, 5)) == 9_000
    with pytest.raises(M.MarchaError):  # one game at a time
        run(s.marcha.Start(m, "1000", CONFIG))
    game["cleared"], game["state"] = 2, "cleared"
    assert run(s.marcha.Finish(m, game, cash_out=True)) == int(1000 * M.LADDER[1])
    assert run(s.marcha.Finish(m, game, cash_out=True)) == 0  # double click pays nothing
    assert run(s.economy.PeekBalance(G, 5)) == 9_000 + int(1000 * M.LADDER[1])
    assert run(s.marcha.Active(G, 5)) is None


def test_daily_limit_and_refund_on_failed_start():
    s = services()
    m = member(6)
    config = Merge(DEFAULT_CONFIG, {"casino": {"marcha": {"daily_limit": 2, "cooldown": 0}}})
    run(s.economy.Add(G, 6, 150, "seed"))
    with pytest.raises(InsufficientFunds):
        run(s.marcha.Start(m, "1000", config))  # failed start doesn't use up a game
    for _ in range(2):
        g, _ = run(s.marcha.Start(m, "100", config)) if run(s.economy.PeekBalance(G, 6)) >= 100 else (None, 0)
        if g:
            run(s.marcha.Finish(m, g, cash_out=False))
        run(s.economy.Add(G, 6, 100, "seed"))
    with pytest.raises(M.MarchaError):
        run(s.marcha.Start(m, "100", config))


def test_boss_order_and_rules():
    rng = random.Random(4)
    g = M.NewGame(100, rng)
    assert len(g["bosses"]) == M.ANTES and g["bosses"][-1] == M.FINAL_BOSS
    assert all(B in M.BOSS_POOL for B in g["bosses"][:-1])
    assert M.Rule(g) == {}  # not a boss blind
    g["blind"] = len(M.BLINDS) - 1
    for boss, check in (
        ("nailoong", lambda: M.Score(["KH", "KS"], g)["chips"] == 10 + 10),  # the K♥ doesn't score
        ("calaveras", lambda: M.Score(["KH", "KS"], g)["chips"] == 10),
        ("koala", lambda: M.Score(["AH"], {**g, "hands": M.HANDS})["total"] == 0 and M.Score(["AH"], {**g, "hands": 2})["total"] > 0),
    ):
        g["bosses"][0] = boss
        assert check(), boss
    g["bosses"][0] = "iracundo"
    M.NewBlind(g, rng)
    assert g["discards"] == 1
    g["bosses"][0], g["money"] = "recaudador", 5
    M.NewBlind(g, rng)
    g["score"] = 0
    M.Play(g, g["hand"][:1], rng)
    assert g["money"] == 4


def test_loji_seals_a_joker():
    rng = random.Random(5)
    g = M.NewGame(100, rng)
    g["jokers"] = ["camarada", "ojo"]
    g["ante"], g["blind"] = M.ANTES - 1, len(M.BLINDS) - 1
    M.NewBlind(g, rng)
    assert g["sealed"] in (0, 1)
    s = M.Score(["AH"], g)
    assert len(s["triggered"]) == 1 and g["jokers"][g["sealed"]] not in s["triggered"]


def test_new_boss_rules():
    rng = random.Random(6)
    g = M.NewGame(100, rng)
    g["blind"] = len(M.BLINDS) - 1
    g["bosses"][0] = "griton"
    M.NewBlind(g, rng)
    with pytest.raises(ValueError):
        M.Play(g, g["hand"][:2], rng)
    M.Play(g, g["hand"][:5], rng)
    g["bosses"][0] = "heisenberg"
    M.NewBlind(g, rng)
    g["money"], g["played"] = 9, {"high": 3, "pair": 1}
    hand = g["hand"]
    high = next(([C] for C in hand), None)
    M.Play(g, high, rng)  # one card = high card, the favourite
    assert g["money"] == 0 and g["last"]["robbed"]
    g["bosses"][0] = "corvus"
    M.NewBlind(g, rng)
    g["levels"] = {"high": 3}
    M.Play(g, g["hand"][:1], rng)
    assert g["levels"]["high"] == 2
