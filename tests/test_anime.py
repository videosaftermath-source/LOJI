import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as N

import pytest

from core.anime import EpisodeText, Finished, NextAt, ParseDay, ParseTime, Stage

# Monday 1 Dec 2026, 18:00 UTC = 19:00 server time (UTC+1)
MON = datetime(2026, 11, 30, 18, 0, tzinfo=timezone.utc)
SHOW = {"day": 0, "hour": 21, "minute": 0}


def test_parsing():
    assert ParseTime("21:00") == (21, 0) and ParseTime("9") == (9, 0) and ParseTime("21h30") == (21, 30)
    assert ParseDay("miércoles") == 2 and ParseDay("Vie") == 4
    for bad in ("25:00", "abc"):
        with pytest.raises(ValueError):
            ParseTime(bad)


def test_next_airing_uses_server_time():
    assert NextAt(SHOW, MON, 1) == datetime(2026, 11, 30, 20, 0, tzinfo=timezone.utc)  # 21:00 at UTC+1
    assert NextAt(SHOW, MON + timedelta(hours=3), 1) == datetime(2026, 12, 7, 20, 0, tzinfo=timezone.utc)  # already aired: next Monday
    assert NextAt({**SHOW, "day": 2}, MON, 1).day == 2  # Wednesday


def test_each_reminder_once_in_order():
    Start = NextAt(SHOW, MON, 1)
    S = dict(SHOW, done={})
    At = lambda m: Stage(S, Start - timedelta(minutes=m), 1, 60, 15)  # noqa: E731
    assert At(90)[0] is None
    What, Key = At(59)
    assert What == "staff"
    S["done"] = {Key: ["staff"]}
    assert At(30)[0] is None and At(14)[0] == "viewers"
    S["done"][Key].append("viewers")
    assert Stage(S, Start + timedelta(seconds=30), 1, 60, 15)[0] == "start"
    S["done"][Key].append("start")
    assert Stage(S, Start + timedelta(seconds=90), 1, 60, 15)[0] is None


def test_episodes():
    assert EpisodeText({"episode": 12, "total": 28}) == "Episodio 12 de 28" and EpisodeText({}) == "Episodio 1"
    assert Finished({"episode": 13, "total": 12}) and not Finished({"episode": 12, "total": 12}) and not Finished({"episode": 99})


def test_aired_is_marked_once(monkeypatch):
    import cogs.Modules.Growth.anime as an
    from tests.economy.fakes import DB

    D = DB()
    monkeypatch.setattr(an, "Db", lambda: D)

    async def Settings(g):
        return {"team_role": None}

    async def Refresh(g):
        pass
    monkeypatch.setattr(an, "Settings", Settings)
    monkeypatch.setattr(an, "RefreshSchedule", Refresh)
    asyncio.run(D[an.SHOWS].insert_one({"_id": "ABCDEFGH", "guild_id": 1, "title": "Frieren", "streamer": 5, "episode": 12, "total": 28, "marked": []}))
    Said = []

    def Click(uid):
        async def edit_message(content=None, view=None):
            Said.append(content)

        async def send_message(text, **kw):
            Said.append(text)
        return N(user=N(id=uid), client=N(get_guild=lambda g: None), response=N(edit_message=edit_message, send_message=send_message))

    asyncio.run(an.AiredButton("ABCDEFGH", "202611302000", 2).callback(Click(9)))  # not the streamer
    asyncio.run(an.AiredButton("ABCDEFGH", "202611302000", 2).callback(Click(5)))
    asyncio.run(an.AiredButton("ABCDEFGH", "202611302000", 1).callback(Click(5)))  # second click: already marked
    assert "Solo quien transmite" in Said[0] and "Episodio 14 de 28" in Said[1] and "ya se marcó" in Said[2]
    assert asyncio.run(D[an.SHOWS].find_one({}))["episode"] == 14


def test_schedule_image():
    from core.anime_art import Schedule

    Png = Schedule([{"title": "One Piece", "day": 0, "hour": 22, "minute": 30, "streamer": 1, "episode": 1101},
                    {"title": "Dandadan", "day": 5, "hour": 20, "minute": 0, "streamer": 2, "episode": 1, "total": 12}], "S", {1: "A"})
    assert Png[:8] == b"\x89PNG\r\n\x1a\n" and len(Png) > 10_000
