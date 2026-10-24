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


# ---- roulette ----

from core.economy.casino import (  # noqa: E402
    HORSES,
    MINES_TILES,
    HiLoChance,
    HiLoGame,
    MinesFair,
    MinesGame,
    RaceFrames,
    RaceMultiplier,
    RaceWinner,
    RouletteBet,
    RouletteMultiplier,
    ROULETTE_BETS,
)


@pytest.mark.parametrize("choice", list(ROULETTE_BETS) + ["0", "17", "36"])
def test_roulette_every_bet_returns_one_minus_edge(choice):
    _, winning = RouletteBet(choice)
    assert len(winning) / 37 * RouletteMultiplier(winning, 0.027) == pytest.approx(0.973)


def test_roulette_classic_payouts_at_default_edge():
    assert RouletteMultiplier(RouletteBet("rojo")[1], 0.027) == pytest.approx(2.0, abs=0.001)
    assert RouletteMultiplier(RouletteBet("7")[1], 0.027) == pytest.approx(36.0, abs=0.001)
    assert len(RouletteBet("rojo")[1]) == len(RouletteBet("negro")[1]) == 18
    assert 0 not in RouletteBet("par")[1]


@pytest.mark.parametrize("choice", ["azul", "37", "-1", "docena4"])
def test_roulette_bad_bets(choice):
    with pytest.raises(CasinoError):
        RouletteBet(choice)


# ---- mines ----


@pytest.mark.parametrize("mines", [1, 3, 10, 19])
def test_mines_any_cashout_point_returns_one_minus_edge(mines):
    safe = MINES_TILES - mines
    for k in range(1, safe + 1):
        survive = 1 / MinesFair(MINES_TILES, mines, k)
        g = MinesGame(1000, mines, 0.03, random.Random(0))
        assert survive * g.Multiplier(k) == pytest.approx(0.97)


def test_mines_simulated_strategy():
    rng = random.Random(5)
    n, bet, paid = 50_000, 1000, 0
    for _ in range(n):
        g = MinesGame(bet, 3, 0.03, rng)
        for tile in rng.sample(range(MINES_TILES), 4):
            if not g.Reveal(tile):
                break
        g.CashOut()
        paid += g.payout
    assert paid / (n * bet) == pytest.approx(0.97, abs=0.02)


def test_mines_flow():
    g = MinesGame(1000, 1, 0.0, random.Random(1))
    bomb = next(iter(g.bombs))
    safe = [t for t in range(MINES_TILES) if t != bomb]
    assert g.Reveal(safe[0]) and g.Multiplier() == pytest.approx(20 / 19)
    assert g.Reveal(safe[0])  # same tile twice: no change
    assert len(g.revealed) == 1
    assert not g.Reveal(bomb) and g.finished and g.payout == 0 and g.exploded == bomb
    g = MinesGame(1000, 1, 0.0, random.Random(2))
    for t in range(MINES_TILES):
        if t not in g.bombs:
            g.Reveal(t)
    assert g.finished and g.payout == 20_000  # opened everything: auto cash-out at 20x
    g = MinesGame(1000, 5, 0.03, random.Random(3))
    g.CashOut()
    assert g.payout == 1000  # leaving without opening returns the bet
    with pytest.raises(CasinoError):
        MinesGame(1000, MINES_TILES, 0.03, random.Random(0))


# ---- higher / lower ----


def test_hilo_chances_and_ties_lose():
    assert HiLoChance(1, False) == 0 and HiLoChance(13, True) == 0
    assert HiLoChance(7, True) == HiLoChance(7, False) == 6 / 13


def test_hilo_one_guess_returns_one_minus_edge():
    for value in range(1, 14):
        for higher in (True, False):
            p = HiLoChance(value, higher)
            if p:
                g = HiLoGame(1000, 0.03, random.Random(0))
                g.card = (value, "♠")
                assert p * g.Next(higher) == pytest.approx(0.97)


def test_hilo_simulated_streaks():
    rng = random.Random(6)
    n, bet, paid = 60_000, 1000, 0
    for _ in range(n):
        g = HiLoGame(bet, 0.03, rng)
        for _ in range(3):
            higher = g.card[0] <= 7
            if not g.Guess(higher):
                break
        g.CashOut()
        paid += g.payout
    assert paid / (n * bet) == pytest.approx(0.97, abs=0.02)


def test_hilo_flow():
    g = HiLoGame(1000, 0.0, random.Random(0))
    g.card = (13, "♠")
    assert not g.Guess(True) and not g.finished  # impossible guess is refused
    g.CashOut()
    assert g.payout == 1000  # no streak: bet back


# ---- horse race ----


def test_race_every_horse_returns_one_minus_edge():
    assert sum(c for _, c in HORSES) == pytest.approx(1)
    for i, (_, chance) in enumerate(HORSES):
        assert chance * RaceMultiplier(i, 0.05) == pytest.approx(0.95)


def test_race_winner_frequencies():
    rng = random.Random(7)
    wins = [0] * len(HORSES)
    for _ in range(100_000):
        wins[RaceWinner(rng)] += 1
    for i, (_, chance) in enumerate(HORSES):
        assert wins[i] / 100_000 == pytest.approx(chance, abs=0.01)


def test_race_frames_end_with_the_winner_first():
    rng = random.Random(8)
    for winner in range(len(HORSES)):
        frames = RaceFrames(winner, rng)
        last = frames[-1]
        assert last[winner] == max(last) and last.count(max(last)) == 1
        assert all(max(f) <= last[winner] for f in frames)


# ---- balance pass ----


def test_every_slots_win_pays_more_than_the_bet():
    from itertools import product as combos

    from core.economy.casino import SLOT_SYMBOLS

    scale = SlotScale(0.10)
    pays = [BaseMultiplier(tuple(s for s, _ in c)) * scale for c in combos(SLOT_SYMBOLS, repeat=3)]
    assert min(p for p in pays if p > 0) > 1
    assert 0.9 < scale < 1.1  # the table shown is close to what it really pays


def test_mines_cap_cashes_out():
    g = MinesGame(1000, 15, 0.03, random.Random(1), cap=100)
    safe = [t for t in range(g.tiles) if t not in g.bombs]
    for t in safe:
        g.Reveal(t)
        if g.finished:
            break
    assert g.finished and g.payout == 100 * 1000


def test_hilo_cap_cashes_out():
    g = HiLoGame(100, 0.03, random.Random(10), cap=5)  # a seed that gets there
    while not g.finished:
        g.Guess(g.card[0] <= 7)
    assert not g.lost and g.payout == 500
