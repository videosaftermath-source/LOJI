"""
Ticket anti-AFK (replaces Birb's inactivity reminder).

- Waiting on the user: if the last message is from staff and the user is silent, they're reminded every 6 h.
- Waiting on staff: once the user writes and nobody from staff answers, the claimer gets a warning at
  30 min and another at 60 min; with the second, the ticket is unclaimed (the team sees it again) and
  the feedback channel is told the moderator abandoned it.

State lives in the ticket's "afk" field:
  user_last, staff_last  last message from the ticket's author / from staff
  pending_since          first user message still unanswered (None = nothing pending)
  reminded_at            last reminder sent to the user
  warnings               claimer warnings for the current pending message
  claimed_at             when the current claimer took it (they get 30 min from then at least)
"""

from datetime import datetime, timedelta, timezone

USER_REMINDER = timedelta(hours=6)
STAFF_WARNING = timedelta(minutes=30)
MAX_WARNINGS = 2


def Aware(dt):
    return dt.replace(tzinfo=timezone.utc) if dt is not None and dt.tzinfo is None else dt


def OnMessage(ticket: dict, author_id: int, is_bot: bool, now: datetime) -> dict | None:
    """The "$set" for the ticket after a message in it (None = nothing to change)."""
    if is_bot:
        return None
    Afk = ticket.get("afk") or {}
    if author_id == int(ticket.get("UserID") or 0):
        Changes = {"afk.user_last": now}
        if not Afk.get("pending_since"):
            Changes["afk.pending_since"] = now
            Changes["afk.warnings"] = 0
        return Changes
    # Anyone else writing in the ticket is staff answering.
    return {"afk.staff_last": now, "afk.pending_since": None, "afk.warnings": 0}


def Decide(ticket: dict, now: datetime) -> str | None:
    """What the checker should do now: "remind_user", "warn", "abandon" or None."""
    Afk = ticket.get("afk") or {}
    Claimer = (ticket.get("claimed") or {}).get("claimer")
    Pending = Aware(Afk.get("pending_since"))
    if Claimer and Pending:
        Warnings = int(Afk.get("warnings") or 0)
        # Counted from the later of: the user's waiting message, or the claim itself.
        ClaimedAt = Aware(Afk.get("claimed_at"))
        Start = max(Pending, ClaimedAt) if ClaimedAt else Pending
        if now - Start >= STAFF_WARNING * (Warnings + 1):
            return "abandon" if Warnings + 1 >= MAX_WARNINGS else "warn"
        return None
    StaffLast = Aware(Afk.get("staff_last"))
    UserLast = Aware(Afk.get("user_last"))
    if StaffLast and (not UserLast or StaffLast > UserLast):
        Since = max(StaffLast, Aware(Afk.get("reminded_at")) or StaffLast)
        if now - Since >= USER_REMINDER:
            return "remind_user"
    return None
