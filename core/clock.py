"""
The host's clock can be off (some hosts run minutes behind). Cooldowns are checked with the host clock,
which is consistent, but Discord shows <t:...> timestamps against the viewer's real clock, so a 1h
cooldown on a host 40 min behind looked like "in 20 minutes".

We learn the offset from Discord itself (every interaction's ID carries Discord's time) and add it
when showing a time to users.
"""

import logging
import statistics
from collections import deque
from datetime import datetime, timezone

import discord

logger = logging.getLogger(__name__)
SAMPLES = 15
IGNORE_BELOW = 20  # seconds: smaller differences are just network delay
_samples: deque = deque(maxlen=SAMPLES)
_offset = 0.0
_warned = False


def Learn(snowflake: int):
    """Feed it an interaction/message ID; keeps the median offset (real - host), in seconds."""
    global _offset, _warned
    Real = discord.utils.snowflake_time(snowflake).timestamp()
    _samples.append(Real - datetime.now(timezone.utc).timestamp())
    if len(_samples) >= 3:
        Median = statistics.median(_samples)
        _offset = Median if abs(Median) >= IGNORE_BELOW else 0.0
        if _offset and not _warned:
            _warned = True
            logger.warning(f"[Clock] The host clock is off by {_offset:+.0f}s compared to Discord; times shown to users are corrected.")


def Offset() -> float:
    return _offset


def Shown(dt: datetime) -> datetime:
    """A host-clock time converted to real time, for showing to users."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return datetime.fromtimestamp(dt.timestamp() + _offset, timezone.utc)


def Stamp(dt_or_ts, style: str = "R") -> str:
    """<t:...:R> for a host-clock datetime or unix timestamp, corrected."""
    Ts = dt_or_ts.timestamp() if isinstance(dt_or_ts, datetime) else float(dt_or_ts)
    return f"<t:{int(Ts + _offset)}:{style}>"


def Fmt(dt: datetime, style: str = "R") -> str:
    """discord.utils.format_dt for a host-clock time, corrected."""
    return discord.utils.format_dt(Shown(dt), style)


def Install(client):
    """Learns the offset from each interaction (only times shown with Fmt/Stamp/Shown are corrected)."""

    async def on_interaction(interaction: discord.Interaction):
        Learn(interaction.id)

    client.add_listener(on_interaction, "on_interaction")
