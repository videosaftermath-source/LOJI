from datetime import datetime, timedelta, timezone

from core.ticket_afk import Decide, OnMessage

T0 = datetime(2026, 11, 14, 12, 0, tzinfo=timezone.utc)
M = timedelta(minutes=1)


def ticket(claimer=None, **afk):
    return {"UserID": 5, "claimed": {"claimer": claimer}, "afk": afk}


def apply(t, changes):
    for k, v in (changes or {}).items():
        t["afk"][k.split(".")[1]] = v
    return t


def test_claimer_gets_two_warnings_then_ticket_is_freed():
    t = apply(ticket(claimer=9), OnMessage(ticket(9), 5, False, T0))
    assert Decide(t, T0 + 29 * M) is None
    assert Decide(t, T0 + 30 * M) == "warn"
    t["afk"]["warnings"] = 1
    assert Decide(t, T0 + 45 * M) is None
    assert Decide(t, T0 + 60 * M) == "abandon"


def test_a_staff_reply_resets_the_count():
    t = apply(ticket(claimer=9), OnMessage(ticket(9), 5, False, T0))
    t["afk"]["warnings"] = 1
    apply(t, OnMessage(t, 9, False, T0 + 40 * M))
    assert Decide(t, T0 + 200 * M) is None
    apply(t, OnMessage(t, 5, False, T0 + 300 * M))  # the user writes again
    assert Decide(t, T0 + 329 * M) is None and Decide(t, T0 + 330 * M) == "warn"


def test_new_claimer_gets_30_minutes_from_the_claim():
    t = ticket(claimer=9, pending_since=T0, warnings=0, claimed_at=T0 + 120 * M)
    assert Decide(t, T0 + 140 * M) is None and Decide(t, T0 + 150 * M) == "warn"


def test_idle_user_is_reminded_every_6_hours():
    t = ticket(claimer=9, user_last=T0, staff_last=T0 + 10 * M, pending_since=None)
    H = timedelta(hours=1)
    assert Decide(t, T0 + 10 * M + 5 * H) is None
    assert Decide(t, T0 + 10 * M + 6 * H) == "remind_user"
    t["afk"]["reminded_at"] = T0 + 10 * M + 6 * H
    assert Decide(t, T0 + 10 * M + 11 * H) is None
    assert Decide(t, T0 + 10 * M + 12 * H) == "remind_user"


def test_no_reminder_when_waiting_on_staff_and_unclaimed():
    t = ticket(claimer=None, user_last=T0 + 20 * M, staff_last=T0, pending_since=T0 + 20 * M)
    assert Decide(t, T0 + 24 * 60 * M) is None
    assert OnMessage(t, 5, True, T0) is None  # bots don't count
