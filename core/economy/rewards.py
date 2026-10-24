"""Pure logic for /trabajar and /diario, kept apart so it can be tested."""

import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


def Aware(dt: datetime | None) -> datetime | None:
    """Mongo returns naive UTC datetimes; make them timezone-aware."""
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def FormatAmount(amount: int, config: dict) -> str:
    Currency = config["currency"]
    return f"{Currency['emoji']} **{amount:,}** {Currency['name']}".replace(",", ".")


def WorkReadyAt(last: datetime | None, config: dict) -> datetime | None:
    """When /trabajar can be used again, or None if it can be used now."""
    last = Aware(last)
    if last is None:
        return None
    Ready = last + timedelta(seconds=config["work"]["cooldown"])
    return Ready if Ready > datetime.now(timezone.utc) else None


def WorkAmount(config: dict, rng: random.Random = random) -> int:
    return rng.randint(config["work"]["min"], config["work"]["max"])


@dataclass
class Daily:
    ready_at: datetime | None  # None = can claim now
    streak: int  # streak after claiming now
    amount: int
    lost_streak: bool


def DailyStatus(last: datetime | None, streak: int, now: datetime, config: dict) -> Daily:
    """What /diario would give right now."""
    Settings = config["daily"]
    last = Aware(last)
    if last is not None:
        Ready = last + timedelta(seconds=Settings["cooldown"])
        if now < Ready:
            return Daily(Ready, streak, 0, False)
    Kept = last is not None and now - last <= timedelta(seconds=Settings["grace"])
    NewStreak = streak + 1 if Kept else 1
    Bonus = Settings["streak_bonus"] * (min(NewStreak, Settings["max_streak_days"]) - 1)
    return Daily(None, NewStreak, Settings["base"] + Bonus, bool(streak) and not Kept)
