from datetime import datetime, timedelta, timezone

import discord

import core.clock as clock


def test_learns_offset_and_corrects_shown_times():
    clock._samples.clear()
    clock._offset = 0.0
    # Discord's clock is 40 minutes ahead of this "host".
    real = datetime.now(timezone.utc) + timedelta(minutes=40)
    for _ in range(5):
        clock.Learn(discord.utils.time_snowflake(real))
    assert abs(clock.Offset() - 2400) < 5
    host_now = datetime.now(timezone.utc)
    ready = host_now + timedelta(hours=1)
    # Shown 1h after Discord's "now", not 20 minutes.
    assert abs((clock.Shown(ready) - real).total_seconds() - 3600) < 5
    assert clock.Stamp(ready).endswith(":R>")
    clock._samples.clear()
    clock._offset = 0.0


def test_small_differences_are_ignored():
    clock._samples.clear()
    clock._offset = 0.0
    for _ in range(5):
        clock.Learn(discord.utils.time_snowflake(datetime.now(timezone.utc) + timedelta(seconds=3)))
    assert clock.Offset() == 0.0
