import asyncio
import math
import random
from itertools import product
from types import SimpleNamespace as N

import pytest

from core.economy.casino import (
    SLOT_SYMBOLS,
    Blackjack,
    CasinoError,
    CoinflipPayout,
    CrashMultiplier,
    CrashPoint,
    CrashSeconds,
    EffectiveEdge,
    HandValue,
    ParseBet,
    BaseMultiplier,
    SlotScale,
)
from core.economy.config import Merge
from core.economy.constants import DEFAULT_CONFIG, LEDGER
from core.economy.registry import Build
from core.economy.service import EconomyService, InsufficientFunds
from tests.economy.fakes import DB

CONFIG = Merge(DEFAULT_CONFIG, {})
G = 1


@pytest.mark.parametrize(
    "raw,balance,expected",
    [("500", 0, 500), ("1.5k", 0, 1500), ("1,5k", 0, 1500), ("2m", 0, 2_000_000), ("1.000", 0, 1000),
     ("todo", 3000, 3000), ("all", 10**9, 50_000), ("mitad", 3001, 1500), (" 250 ", 0, 250)],
)
def test_parse_bet(raw, balance, expected):
    assert ParseBet(raw, balance, {"max": 50_000}) == expected


@pytest.mark.parametrize("raw", ["abc", "-5", "1kk", ""])
def test_parse_bet_rejects(raw):
    with pytest.raises(CasinoError):
        ParseBet(raw, 100, {"max": 1000})


def test_luck_lowers_edge_but_never_flips_it():
    assert EffectiveEdge(0.04, 0) == 0.04
    assert EffectiveEdge(0.04, 0.15) == pytest.approx(0.034)
    assert EffectiveEdge(0.04, 5) == 0  # even absurd luck only removes the edge


def test_slots_return_exactly_one_minus_edge():
    total = sum(w for _, w in SLOT_SYMBOLS)
    for edge in (0.0, 0.04, 0.1):
        expected = sum(
            math.prod(w / total for _, w in combo) * BaseMultiplier(tuple(s for s, _ in combo)) * SlotScale(edge)
            for combo in product(SLOT_SYMBOLS, repeat=3)
        )
        assert expected == pytest.approx(1 - edge)


def test_coinflip_return():
    rng = random.Random(1)
    n, bet, paid = 200_000, 1000, 0
    for _ in range(n):
        paid += CoinflipPayout(bet, rng.random() < 0.5, 0.02)
    assert paid / (n * bet) == pytest.approx(0.98, abs=0.01)


def test_crash_multiplier_and_time_are_inverse():
    assert CrashMultiplier(0) == 1.0
    assert CrashMultiplier(CrashSeconds(2.0)) == pytest.approx(2.0, abs=0.01)
    assert CrashMultiplier(CrashSeconds(10.0)) == pytest.approx(10.0, abs=0.01)


@pytest.mark.parametrize("target", [1.5, 2.0, 5.0])
def test_crash_return_for_any_target(target):
    rng = random.Random(2)
    edge, n = 0.03, 300_000
    wins = sum(CrashPoint(edge, 1000, rng) > target for _ in range(n))
    # Cashing out at `target` returns (1 - edge) on average.
    assert wins * target / n == pytest.approx(1 - edge, abs=0.02)


def test_crash_instant_rate_and_cap():
    rng = random.Random(3)
    points = [CrashPoint(0.03, 100, rng) for _ in range(200_000)]
    instant = sum(p == 1.0 for p in points) / len(points)
    assert 0.025 < instant < 0.045  # about `edge` (+ rounding just above 1.00)
    assert max(points) <= 100


def card(r):
    return (r, "♠")


@pytest.mark.parametrize(
    "ranks,value,soft",
    [(["A", "K"], 21, True), (["A", "A", "9"], 21, True), (["A", "5", "K"], 16, False), (["10", "Q", "5"], 25, False), (["A", "6"], 17, True)],
)
def test_hand_values(ranks, value, soft):
    assert HandValue([card(r) for r in ranks]) == (value, soft)


def rigged(player, dealer, shoe=()):
    g = Blackjack(1000, 0.0, random.Random(0))
    g.player, g.dealer = [card(r) for r in player], [card(r) for r in dealer]
    g.shoe = [card(r) for r in reversed(shoe)]
    return g


def test_blackjack_outcomes():
    g = rigged(["A", "K"], ["9", "7"]); g.Settle()
    assert (g.result, g.payout) == ("blackjack", 2500)
    g = rigged(["10", "9"], ["10", "7"]); g.Stand()
    assert (g.result, g.payout) == ("win", 2000)
    g = rigged(["10", "7"], ["10", "7"]); g.Stand()
    assert (g.result, g.payout) == ("push", 1000)
    g = rigged(["10", "6"], ["10", "6"], shoe=["9"]); g.Hit()
    assert (g.result, g.payout) == ("bust", 0)
    g = rigged(["10", "6"], ["10", "6"], shoe=["K"]); g.Stand()  # dealer hits 16 and busts
    assert g.result == "win" and len(g.dealer) == 3
    g = rigged(["10", "2"], ["A", "6"]); g.Stand()  # dealer stands on soft 17
    assert len(g.dealer) == 2 and g.result == "lose"
    g = rigged(["5", "6"], ["10", "7"], shoe=["10"]); g.Double()
    assert (g.bet, g.result, g.payout) == (2000, "win", 4000)


def test_blackjack_edge_takes_part_of_winnings():
    g = Blackjack(1000, 0.02, random.Random(0))
    g.player, g.dealer = [card("10"), card("9")], [card("10"), card("7")]
    g.Stand()
    assert g.payout == 1000 + 980


def test_blackjack_return_with_simple_strategy():
    rng = random.Random(4)
    n, bet, paid = 40_000, 100, 0
    for _ in range(n):
        g = Blackjack(bet, 0.02, rng)
        g.Deal()
        while not g.finished:
            total = HandValue(g.player)[0]
            dealer_up = HandValue(g.dealer[:1])[0]
            if total >= 17 or (total >= 13 and dealer_up <= 6):
                g.Stand()
            else:
                g.Hit()
        paid += g.payout
    assert 0.9 < paid / (n * bet) < 1.0  # the house always keeps something


# ---- service ----


def run(coro):
    return asyncio.run(coro)


def services():
    s = Build(EconomyService(DB()))
    run(s.Setup())
    return s


def member(uid):
    return N(id=uid, guild=N(id=G))


def test_start_takes_bet_and_pay_logs_stats():
    s = services()
    run(s.economy.Add(G, 5, 1000, "seed"))
    bet, edge, luck = run(s.casino.Start(member(5), "slots", "500", CONFIG))
    assert (bet, edge, luck) == (500, CONFIG["casino"]["slots"]["edge"], 0.0)
    run(s.casino.Pay(member(5), "slots", 800))
    account = run(s.economy.Account(G, 5))
    assert account["balance"] == 1300
    assert account["casino"] == {"games": 1, "wagered": 500, "won": 800}
    kinds = [e["kind"] for e in s.economy.ledger.c.find({"user_id": 5})]
    assert kinds == ["created", "bet", "payout"]


def test_limits_cooldown_and_funds():
    s = services()
    run(s.economy.Add(G, 5, 100_000, "seed"))
    with pytest.raises(CasinoError):
        run(s.casino.Start(member(5), "slots", "1", CONFIG))  # under min
    with pytest.raises(CasinoError):
        run(s.casino.Start(member(5), "slots", "999999", CONFIG))  # over max
    run(s.casino.Start(member(5), "slots", "100", CONFIG))
    with pytest.raises(CasinoError):
        run(s.casino.Start(member(5), "slots", "100", CONFIG))  # cooldown
    with pytest.raises(InsufficientFunds):
        run(s.casino.Start(member(6), "coinflip", "100", CONFIG))
    # A failed bet doesn't leave a cooldown behind.
    run(s.economy.Add(G, 6, 100, "seed"))
    run(s.casino.Start(member(6), "coinflip", "100", CONFIG))


def test_exclusive_games_one_at_a_time():
    s = services()
    run(s.economy.Add(G, 5, 10_000, "seed"))
    cfg = Merge(DEFAULT_CONFIG, {"casino": {"crash": {"cooldown": 0}}})

    async def both():
        return await asyncio.gather(
            s.casino.Start(member(5), "crash", "100", cfg, exclusive=True),
            s.casino.Start(member(5), "crash", "100", cfg, exclusive=True),
            return_exceptions=True,
        )

    results = run(both())
    assert sum(not isinstance(r, Exception) for r in results) == 1
    s.casino.Finish(member(5), "crash")
    run(s.casino.Start(member(5), "crash", "100", cfg, exclusive=True))


def test_lucky_pet_lowers_edge():
    s = services()
    run(s.pets.SeedStarter(G))
    run(s.pets.Grant(G, 5, "UNICORN", "t", CONFIG))
    run(s.economy.Add(G, 5, 1000, "seed"))
    _, edge, luck = run(s.casino.Start(member(5), "slots", "100", CONFIG))
    assert luck > 0 and edge < CONFIG["casino"]["slots"]["edge"]
