"""
Ticket channel names with a number per panel: reporte-001, reporte-002... and the claimed name.

Each panel has its own counter and its own two templates (open and claimed), set in
/config → Tickets → the panel → "Nombres (número)". Variables:
  {number}       the ticket's number in its panel, 3 digits (001)
  {panel}        the panel's name
  {user.name}    who opened the ticket   ({author.name} is the same)
  {user.id}
  {claimer.name} who claimed it (claimed name only)
"""

import re

from pymongo import ReturnDocument

COUNTERS = "ticket_counters"
DEFAULT_OPEN = "{panel}-{number}"
DEFAULT_CLAIMED = "claimed-{panel}-{number}"
NAME_MAX = 100
PAD = 3
VARIABLES = "`{number}` `{panel}` `{user.name}` `{user.id}` `{claimer.name}`"


async def NextNumber(db, guild_id: int, panel: str) -> int:
    """Atomic, so two tickets opened at once never get the same number."""
    Doc = await db[COUNTERS].find_one_and_update(
        {"_id": f"{guild_id}:{panel}"}, {"$inc": {"value": 1}}, upsert=True, return_document=ReturnDocument.AFTER
    )
    return int(Doc["value"])


async def SetNext(db, guild_id: int, panel: str, next_number: int):
    """The next ticket of this panel gets `next_number` (to continue an old count, or restart it)."""
    await db[COUNTERS].update_one({"_id": f"{guild_id}:{panel}"}, {"$set": {"value": max(0, next_number - 1)}}, upsert=True)


async def PeekNext(db, guild_id: int, panel: str) -> int:
    Doc = await db[COUNTERS].find_one({"_id": f"{guild_id}:{panel}"})
    return int((Doc or {}).get("value", 0)) + 1


def Clean(name: str) -> str:
    """What Discord would do to a text channel name, so we can show it beforehand."""
    Name = re.sub(r"\s+", "-", name.strip().lower())
    Name = re.sub(r"-{2,}", "-", Name).strip("-")
    return Name[:NAME_MAX] or "ticket"


def Render(template: str | None, default: str, number: int, panel: str, user=None, claimer=None) -> str:
    Text = template or default
    UserName = getattr(user, "name", "") or ""
    UserId = str(getattr(user, "id", "") or "")
    Values = {
        "{number}": str(number).zfill(PAD),
        "{panel}": panel or "ticket",
        "{user.name}": UserName,
        "{user.id}": UserId,
        "{author.name}": UserName,
        "{author.id}": UserId,
        "{claimer.name}": getattr(claimer, "name", "") or "",
    }
    for Key, Value in Values.items():
        Text = Text.replace(Key, Value)
    return Clean(Text)


def OpenName(panel_doc: dict, ticket: dict, user) -> str:
    return Render((panel_doc.get("TicketNames") or {}).get("Open"), DEFAULT_OPEN, ticket.get("Number", 0), panel_doc.get("name"), user)


def ClaimedName(panel_doc: dict, ticket: dict, user, claimer) -> str:
    return Render(
        (panel_doc.get("TicketNames") or {}).get("Claimed"), DEFAULT_CLAIMED, ticket.get("Number", 0), panel_doc.get("name"), user, claimer
    )
