"""
Events (/config → Crecimiento y Entretenimiento → Eventos).

The events team (one role) creates an event with a short form; LOJI posts it (its own Components V2 design or the
team's JSON), optionally with sign-up (✋ Me apunto, with an optional limit) and a native Discord event. It reminds
before it starts, and /evento finalizar hands out the prizes: economy coins and roles automatically, anything else
(Nitro…) listed for the staff to deliver. Everything stays in the history.

Prizes are written one place per line:  "1: 5000 monedas, @Campeón, Nitro Basic"
"""

import re
from datetime import datetime, timedelta, timezone

EVENTS = "events"
SETTINGS = {
    "organizer_role": None,  # who can create and run events (admins always can)
    "channel": None,  # where events are announced
    "log_channel": None,  # optional history channel
    "ping_role": None,  # optional role called in announcements and reminders
    "color": "#BBA896",
    "remind_minutes": 60,
}
MAX_PLACES = 10
MEDALS = {1: "🥇", 2: "🥈", 3: "🥉"}
COINS = re.compile(r"(\d[\d.,]*)\s*(?:monedas?|cr[ée]ditos?|coins?|🪙|<a?:[A-Za-z0-9_]*moneda[A-Za-z0-9_]*:\d+>)", re.I)
ROLE = re.compile(r"<@&(\d{15,21})>")
PLACE = re.compile(r"^\s*(\d{1,2})\s*(?:º|°|\.|:|-|\))?\s*[:.-]?\s*(.+)$")


def Now() -> datetime:
    return datetime.now(timezone.utc)


def Aware(dt):
    return dt.replace(tzinfo=timezone.utc) if dt is not None and dt.tzinfo is None else dt


def ParsePrizes(text: str) -> list[dict]:
    """'1: 5000 monedas, <@&123>, Nitro' per line -> [{place, coins, roles, manual, text}]. Raises ValueError."""
    Prizes = []
    for Line in (text or "").splitlines():
        if not Line.strip():
            continue
        Match = PLACE.match(Line)
        if not Match:
            raise ValueError(f"No entiendo «{Line.strip()[:60]}»: empieza cada línea con el puesto, por ejemplo `1: 5000 monedas`.")
        Place, Rest = int(Match.group(1)), Match.group(2).strip()
        if not 1 <= Place <= MAX_PLACES:
            raise ValueError(f"Los puestos van del 1 al {MAX_PLACES}.")
        Coins = sum(int(N.replace(".", "").replace(",", "")) for N in COINS.findall(Rest))
        Roles = [int(R) for R in ROLE.findall(Rest)]
        Leftover = ROLE.sub("", COINS.sub("", Rest))
        Manual = [P.strip(" ,;+y") for P in re.split(r"[,;+]| y ", Leftover) if P.strip(" ,;+y")]
        Prizes.append({"place": Place, "coins": Coins, "roles": Roles, "manual": Manual, "text": Rest})
    Places = [P["place"] for P in Prizes]
    if len(Places) != len(set(Places)):
        raise ValueError("Hay un puesto repetido.")
    return sorted(Prizes, key=lambda P: P["place"])


def PrizeLine(prize: dict) -> str:
    Place = prize["place"]
    return f"{MEDALS.get(Place, '`' + str(Place) + 'º`')} {prize['text']}"


def CanJoin(event: dict, user_id: int) -> tuple[bool, str]:
    """(can sign up, why not)."""
    if event.get("status") != "open":
        return False, "Este evento ya no admite inscripciones."
    if user_id in (event.get("participants") or []):
        return True, ""
    Limit = event.get("slots")
    if Limit and len(event.get("participants") or []) >= Limit:
        return False, "No quedan plazas. 😔"
    return True, ""


def Due(event: dict, now: datetime, remind_minutes: int) -> str | None:
    """What the reminder loop should do: "remind", "start" or None."""
    if event.get("status") != "open":
        return None
    Start = Aware(event["start"])
    if not event.get("started") and Start <= now:
        return "start"
    if not event.get("reminded") and not event.get("started") and Start - timedelta(minutes=remind_minutes) <= now < Start:
        return "remind"
    return None


def Awards(prizes: list[dict], winners: list[int]) -> list[tuple[int, dict]]:
    """[(user, prize)] in order: the 1st winner gets place 1, and so on (places without a winner are skipped)."""
    ByPlace = {P["place"]: P for P in prizes}
    return [(User, ByPlace[I]) for I, User in enumerate(winners, 1) if I in ByPlace]


def ResolveRoles(text: str, roles: list[tuple[int, str]]) -> str:
    """'@Campeón' typed in a form (plain text there) -> the role's real mention, longest names first."""
    for Id, Name in sorted(roles, key=lambda R: -len(R[1])):
        if Name and Name != "@everyone":
            text = re.sub(r"@" + re.escape(Name) + r"(?![\w])", f"<@&{Id}>", text, flags=re.I)
    return text
