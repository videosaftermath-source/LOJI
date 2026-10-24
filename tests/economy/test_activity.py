import random
from datetime import datetime, timedelta, timezone

import pytest

from core.economy.activity import (
    BLOCKED, COOLDOWN, FLOOD, OK, REPEAT, SHORT,
    CapAmount, Guard, LocalDay, Meaningful, Multiplier, NextPayout, Normalize,
)
from core.economy.config import Merge
from core.economy.constants import DEFAULT_CONFIG

A = Merge(DEFAULT_CONFIG, {})["activity"]
K = (1, 5)


def settings(**over):
    return {**A, **over}


def test_normalize():
    assert Normalize("JAJAJAAAAAA <@123> https://x.com/a  ¡Qué tal!! <:pepe:123>") == "jajajaa que tal"
    assert Meaningful(Normalize("😂😂😂 !!!")) == 0


def test_short_messages_are_not_paid():
    g = Guard()
    assert g.Check(K, "ok", 0, A) == SHORT
    assert g.Check(K, "😂😂😂😂😂😂😂😂", 100, A) == SHORT


def test_normal_message_paid_then_cooldown():
    g = Guard()
    assert g.Check(K, "hola a todos como estan", 0, A) == OK
    g.MarkPaid(K, 0)
    assert g.Check(K, "que van a hacer hoy en la noche", 30, A) == COOLDOWN
    assert g.Check(K, "alguien juega minecraft esta tarde", A["cooldown"] + 1, A) == OK


def test_repeated_and_similar_messages():
    g = Guard()
    assert g.Check(K, "buenos dias a todos", 0, A) == OK
    assert g.Check(K, "buenos dias a todos", 100, A) == REPEAT
    assert g.Check(K, "Buenos días a todoooos!!", 200, A) == REPEAT


def test_flood():
    g = Guard()
    S = settings(cooldown=0)
    texts = [
        "hola como estan todos",
        "alguien vio el partido ayer",
        "que hambre tengo la verdad",
        "voy a pedir una pizza grande",
        "mi gato rompio otro vaso",
        "manana tengo examen de mates",
        "quien se conecta al minecraft",
        "ya llego la pizza por fin",
    ]
    results = [g.Check(K, t, i * 0.5, S) for i, t in enumerate(texts)]
    assert results[0] == OK
    assert results[S["flood_count"] - 1] == FLOOD


def test_block_after_strikes_and_unblock():
    g = Guard()
    S = settings(max_strikes=3, block=600)
    g.Check(K, "spam spam spam spam", 0, S)
    g.Check(K, "spam spam spam spam", 10, S)
    g.Check(K, "spam spam spam spam", 20, S)
    assert g.Check(K, "spam spam spam spam", 30, S) == BLOCKED
    # Even a good message is blocked during the block...
    assert g.Check(K, "ahora si un mensaje normal y largo", 100, S) == BLOCKED
    assert g.BlockedFor(K, 100) > 0
    g.Unblock(K)
    assert g.Check(K, "otro mensaje completamente diferente", 700, S) == OK


def test_strikes_expire():
    g = Guard()
    S = settings(max_strikes=2, strike_window=60)
    g.Check(K, "repetido repetido", 0, S)
    g.Check(K, "repetido repetido", 10, S)  # strike 1
    assert g.Check(K, "repetido repetido", 200, S) == REPEAT  # strike 1 expired: not blocked


def test_users_are_independent():
    g = Guard()
    assert g.Check((1, 1), "hola a todos como estan", 0, A) == OK
    assert g.Check((1, 2), "hola a todos como estan", 0, A) == OK


@pytest.mark.parametrize(
    "amount,earned,expected",
    [
        (10, 0, 10),        # under soft cap: full
        (150, 500, 125),    # 100 full + 50 at 50%
        (100, 700, 50),     # past soft cap: half
        (50, 990, 10),      # stops at hard cap
        (50, 1000, 0),      # at hard cap: nothing
    ],
)
def test_cap_amount(amount, earned, expected):
    assert CapAmount(amount, earned, A) == expected


def test_multiplier_capped():
    assert Multiplier(0, A) == 1
    assert Multiplier(4, A) == pytest.approx(1.2)
    assert Multiplier(100, A) == A["max_multiplier"]


def test_local_day_uses_offset():
    late = datetime(2026, 10, 25, 3, tzinfo=timezone.utc)  # 22:00 on the 24th at UTC-5
    assert LocalDay(late, -5).isoformat() == "2026-10-24"
    assert LocalDay(late, 0).isoformat() == "2026-10-25"


def chat(activity, day, messages, S):
    """Sends `messages` accepted messages on `day` and returns the activity after."""
    rng = random.Random(1)
    paid = 0
    now = datetime(2026, 10, day, 17, tzinfo=timezone.utc)
    for _ in range(messages):
        p = NextPayout(activity, now, S, rng)
        activity = {**activity, **p.fields}
        paid += p.amount
    return activity, paid


def test_streak_grows_daily_and_raises_pay():
    S = settings(streak_messages=3, min=10, max=10)
    act, _ = chat({}, 1, 3, S)
    assert act["streak"] == 1
    act, _ = chat(act, 2, 3, S)
    assert act["streak"] == 2
    p = NextPayout(act, datetime(2026, 10, 3, 17, tzinfo=timezone.utc), S)
    assert p.multiplier == pytest.approx(1 + 2 * S["streak_step"])
    assert p.amount == round(10 * p.multiplier)


def test_streak_needs_enough_messages():
    S = settings(streak_messages=5)
    act, _ = chat({}, 1, 4, S)
    assert act.get("streak", 0) == 0
    act, _ = chat(act, 1, 1, S)
    assert act["streak"] == 1


def test_streak_only_counts_once_per_day():
    S = settings(streak_messages=2)
    act, _ = chat({}, 1, 10, S)
    assert act["streak"] == 1


def test_streak_lost_after_missing_a_day():
    S = settings(streak_messages=1, min=10, max=10)
    act, _ = chat({}, 1, 1, S)
    act, _ = chat(act, 2, 1, S)
    assert act["streak"] == 2
    act, _ = chat(act, 4, 1, S)  # skipped the 3rd
    assert act["streak"] == 1


def test_daily_totals_reset_each_day():
    S = settings(min=10, max=10, soft_cap=1000, hard_cap=1000)
    act, paid = chat({}, 1, 5, S)
    assert act["paid_today"] == 5 and act["earned_today"] == paid
    act, _ = chat(act, 2, 1, S)
    assert act["paid_today"] == 1


def test_daily_hard_cap_respected():
    S = settings(min=100, max=100, soft_cap=300, hard_cap=500, diminish=0.5)
    _, paid = chat({}, 1, 50, S)
    assert paid == 500


def test_ttl_cache():
    from core.economy.activity import TTLCache

    c = TTLCache()
    assert c.Get("a", 0) is None
    c.Set("a", False, 0, 10)
    assert c.Get("a", 5) is False
    assert c.Get("a", 11) is None
