"""
Paying people for chatting: anti-spam guard, daily caps and streaks.

The guard keeps recent messages in memory (they don't need to survive a
restart). Streaks and daily totals live in the user's account (`activity`).
"""

import random
import re
import unicodedata
from collections import deque
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from difflib import SequenceMatcher

URL = re.compile(r"https?://\S+")
DISCORD_TOKEN = re.compile(r"<a?:\w+:\d+>|<[@#][!&]?\d+>")  # custom emojis, mentions
REPEATED = re.compile(r"(.)\1{2,}")  # "jajaaaaa" -> "jajaa"
NOT_WORD = re.compile(r"[^\w]+")

# Guard results
OK = "ok"
BLOCKED = "blocked"
COOLDOWN = "cooldown"
SHORT = "short"
REPEAT = "repeat"
FLOOD = "flood"


def Normalize(text: str) -> str:
    """Lowercase text without links, mentions, emojis, accents or stretched letters."""
    text = DISCORD_TOKEN.sub(" ", URL.sub(" ", text.lower()))
    text = "".join(
        c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c)
    )
    text = REPEATED.sub(r"\1\1", text)
    return " ".join(NOT_WORD.sub(" ", text).replace("_", " ").split())


def Meaningful(normalized: str) -> int:
    """How many letters/digits the message really has."""
    return sum(c.isalnum() for c in normalized)


def Similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


@dataclass
class UserState:
    recent: deque = field(default_factory=lambda: deque(maxlen=20))
    times: deque = field(default_factory=lambda: deque(maxlen=60))
    strikes: deque = field(default_factory=lambda: deque(maxlen=60))
    blocked_until: float = 0.0
    last_paid: float = float("-inf")


class Guard:
    """Decides whether a message deserves pay. `now` is a monotonic time in seconds."""

    def __init__(self):
        self.states: dict[tuple[int, int], UserState] = {}

    def State(self, key) -> UserState:
        return self.states.setdefault(key, UserState())

    def Check(self, key, text: str, now: float, settings: dict) -> str:
        S = self.State(key)
        S.times.append(now)
        while S.times and now - S.times[0] > settings["flood_window"]:
            S.times.popleft()
        Flooding = len(S.times) >= settings["flood_count"]

        Normalized = Normalize(text)
        History = list(S.recent)[-settings["history"]:]
        Repeated = bool(Normalized) and any(
            Similarity(Normalized, Old) >= settings["similarity"] for Old in History
        )
        if Normalized:
            S.recent.append(Normalized)

        if Flooding or Repeated:
            S.strikes.append(now)
        while S.strikes and now - S.strikes[0] > settings["strike_window"]:
            S.strikes.popleft()
        if len(S.strikes) >= settings["max_strikes"]:
            S.blocked_until = now + settings["block"]
            S.strikes.clear()

        if now < S.blocked_until:
            return BLOCKED
        if Flooding:
            return FLOOD
        if Repeated:
            return REPEAT
        if Meaningful(Normalized) < settings["min_length"]:
            return SHORT
        if now - S.last_paid < settings["cooldown"]:
            return COOLDOWN
        return OK

    def MarkPaid(self, key, now: float):
        self.State(key).last_paid = now

    def BlockedFor(self, key, now: float) -> float:
        """Seconds left on a block (0 if not blocked)."""
        S = self.states.get(key)
        return max(0.0, S.blocked_until - now) if S else 0.0

    def Unblock(self, key):
        S = self.states.get(key)
        if S:
            S.blocked_until = 0.0
            S.strikes.clear()


class TTLCache:
    """Tiny time-based cache. `now` is a monotonic time in seconds."""

    def __init__(self):
        self.items: dict = {}

    def Get(self, key, now: float):
        Item = self.items.get(key)
        if Item and Item[0] > now:
            return Item[1]
        return None

    def Set(self, key, value, now: float, ttl: float):
        self.items[key] = (now + ttl, value)
        if len(self.items) > 50_000:  # don't grow forever on huge servers
            self.items = {k: v for k, v in self.items.items() if v[0] > now}

    def Forget(self, key):
        self.items.pop(key, None)


def LocalDay(now: datetime, utc_offset: int) -> date:
    """The server's calendar day (streaks and caps reset at local midnight)."""
    return (now.astimezone(timezone.utc) + timedelta(hours=utc_offset)).date()


def CurrentStreak(activity: dict, today: date) -> int:
    """Streak still alive today (kept if the last qualified day was today or yesterday)."""
    Last = activity.get("qualified_day")
    if not Last:
        return 0
    Last = date.fromisoformat(Last)
    return int(activity.get("streak", 0)) if (today - Last).days <= 1 else 0


def Multiplier(streak: int, settings: dict) -> float:
    return min(settings["max_multiplier"], 1 + settings["streak_step"] * streak)


def CapAmount(amount: int, earned_today: int, settings: dict) -> int:
    """Applies diminishing returns after the soft cap and stops at the hard cap."""
    Soft, Hard = settings["soft_cap"], settings["hard_cap"]
    Paid = 0.0
    Left = float(amount)
    Earned = float(earned_today)
    # Full pay up to the soft cap...
    Full = max(0.0, min(Left, Soft - Earned))
    Paid += Full
    Left -= Full
    Earned += Full
    # ...then reduced pay up to the hard cap.
    if Left > 0 and Earned < Hard:
        Paid += min(Left * settings["diminish"], Hard - Earned)
    return int(min(Paid, max(0, Hard - earned_today)))


@dataclass
class Payout:
    amount: int
    fields: dict  # new `activity` values to save
    multiplier: float
    qualified_now: bool  # this message completed today's streak goal


def NextPayout(activity: dict, now: datetime, settings: dict, rng: random.Random = random) -> Payout:
    """What one accepted message pays, and how the user's activity changes."""
    Today = LocalDay(now, settings["utc_offset"])
    SameDay = activity.get("day") == Today.isoformat()
    PaidToday = int(activity.get("paid_today", 0)) if SameDay else 0
    EarnedToday = int(activity.get("earned_today", 0)) if SameDay else 0

    Streak = CurrentStreak(activity, Today)
    QualifiedToday = activity.get("qualified_day") == Today.isoformat()
    Mult = Multiplier(Streak, settings)
    Base = rng.randint(settings["min"], settings["max"])
    Amount = CapAmount(round(Base * Mult), EarnedToday, settings)

    Fields = {
        "day": Today.isoformat(),
        "paid_today": PaidToday + 1,
        "earned_today": EarnedToday + Amount,
        "streak": Streak,
        "qualified_day": activity.get("qualified_day"),
    }
    QualifiedNow = False
    if not QualifiedToday and PaidToday + 1 >= settings["streak_messages"]:
        Fields["streak"] = Streak + 1
        Fields["qualified_day"] = Today.isoformat()
        QualifiedNow = True
    return Payout(Amount, Fields, Mult, QualifiedNow)
