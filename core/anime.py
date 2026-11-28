"""
Anime streams (/config → Crecimiento y Entretenimiento → Anime): a fixed weekly schedule. Each show has a day,
a time (server time), who streams it in the auditorium and which episode comes next.

LOJI reminds the streamer, then the viewers' role, says when it starts, and the streamer marks how many episodes
were shown (the count moves on). /horario anime draws the week as an image.
"""

from datetime import datetime, timedelta, timezone

SHOWS = "anime_shows"
SETTINGS = {
    "team_role": None,  # who manages the schedule and streams
    "stage": None,  # the auditorium (stage or voice channel)
    "channel": None,  # where viewers are told
    "ping_role": None,  # viewers who want the pings
    "staff_channel": None,  # where the streamer is reminded (empty = a DM)
    "remind_minutes": 15,
    "staff_minutes": 60,
    "schedule_message": None,  # the posted schedule, kept up to date
}
DAYS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
DAY_KEYS = {D.lower(): I for I, D in enumerate(DAYS)} | {"miercoles": 2, "sabado": 5, "lun": 0, "mar": 1, "mie": 2, "mié": 2,
                                                         "jue": 3, "vie": 4, "sab": 5, "sáb": 5, "dom": 6}


def Now() -> datetime:
    return datetime.now(timezone.utc)


def ParseDay(text: str) -> int:
    Key = (text or "").strip().lower()
    if Key not in DAY_KEYS:
        raise ValueError
    return DAY_KEYS[Key]


def ParseTime(text: str) -> tuple[int, int]:
    Parts = (text or "").strip().replace(".", ":").replace("h", ":").rstrip(":").split(":")
    H, M = int(Parts[0]), int(Parts[1]) if len(Parts) > 1 and Parts[1] else 0
    if not (0 <= H <= 23 and 0 <= M <= 59):
        raise ValueError
    return H, M


def NextAt(show: dict, now: datetime, utc_offset: int) -> datetime:
    """The next time this show airs (today if it hasn't started yet), in UTC."""
    Local = now + timedelta(hours=utc_offset)
    Days = (show["day"] - Local.weekday()) % 7
    Start = Local.replace(hour=show["hour"], minute=show["minute"], second=0, microsecond=0) + timedelta(days=Days)
    if Start <= Local - timedelta(minutes=1):  # this week's already started: next week
        Start += timedelta(days=7)
    return (Start - timedelta(hours=utc_offset)).replace(tzinfo=timezone.utc)


def Stage(show: dict, now: datetime, utc_offset: int, staff_minutes: int, remind_minutes: int) -> tuple[str | None, str]:
    """What to do now: ("staff" | "viewers" | "start" | None, key of that airing). Each step happens once per airing."""
    Start = NextAt(show, now - timedelta(minutes=2), utc_offset)  # still "this" airing for 2 min after it starts
    Key = Start.strftime("%Y-%m-%dT%H:%M")
    Done = (show.get("done") or {}).get(Key, [])
    if Start <= now and "start" not in Done:
        return "start", Key
    if Start - timedelta(minutes=remind_minutes) <= now < Start and "viewers" not in Done:
        return "viewers", Key
    if Start - timedelta(minutes=staff_minutes) <= now < Start and "staff" not in Done:
        return "staff", Key
    return None, Key


def EpisodeText(show: dict) -> str:
    Next = int(show.get("episode") or 1)
    Total = show.get("total")
    return f"Episodio {Next}" + (f" de {Total}" if Total else "")


def Finished(show: dict) -> bool:
    return bool(show.get("total")) and int(show.get("episode") or 1) > int(show["total"])
