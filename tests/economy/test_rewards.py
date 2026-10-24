from datetime import datetime, timedelta, timezone

from core.economy.config import Merge
from core.economy.constants import DEFAULT_CONFIG
from core.economy.rewards import DailyStatus, WorkAmount, WorkReadyAt

CONFIG = Merge(DEFAULT_CONFIG, {})
NOW = datetime(2026, 10, 24, 12, tzinfo=timezone.utc)
D = CONFIG["daily"]


def test_first_daily():
    s = DailyStatus(None, 0, NOW, CONFIG)
    assert (s.ready_at, s.streak, s.amount, s.lost_streak) == (None, 1, D["base"], False)


def test_daily_on_cooldown():
    s = DailyStatus(NOW - timedelta(hours=2), 3, NOW, CONFIG)
    assert s.ready_at == NOW - timedelta(hours=2) + timedelta(seconds=D["cooldown"])
    assert s.amount == 0


def test_daily_keeps_streak():
    s = DailyStatus(NOW - timedelta(hours=25), 3, NOW, CONFIG)
    assert s.streak == 4
    assert s.amount == D["base"] + 3 * D["streak_bonus"]


def test_daily_streak_bonus_is_capped():
    s = DailyStatus(NOW - timedelta(hours=25), 30, NOW, CONFIG)
    assert s.streak == 31
    assert s.amount == D["base"] + (D["max_streak_days"] - 1) * D["streak_bonus"]


def test_daily_loses_streak_after_grace():
    s = DailyStatus(NOW - timedelta(seconds=D["grace"] + 1), 5, NOW, CONFIG)
    assert (s.streak, s.amount, s.lost_streak) == (1, D["base"], True)


def test_naive_mongo_datetimes_work():
    naive = (NOW - timedelta(hours=25)).replace(tzinfo=None)
    assert DailyStatus(naive, 1, NOW, CONFIG).streak == 2


def test_work_cooldown():
    assert WorkReadyAt(None, CONFIG) is None
    assert WorkReadyAt(datetime.now(timezone.utc), CONFIG) is not None
    assert WorkReadyAt(datetime.now(timezone.utc) - timedelta(seconds=CONFIG["work"]["cooldown"] + 1), CONFIG) is None


def test_work_amount_in_range():
    for _ in range(200):
        assert CONFIG["work"]["min"] <= WorkAmount(CONFIG) <= CONFIG["work"]["max"]
