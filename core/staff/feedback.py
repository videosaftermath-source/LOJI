"""
Staff feedback: a 1-10 rating and an optional comment, from /feedback or from the DM sent when a ticket closes.

Documents live in "feedback" with Birb's fields (guild_id, staff, author, rating, feedback, date, feedbackid),
so the staff profile's average keeps working. Who counts as staff comes from the Mando Central config.
"""

from core.clock import Stamp
import time

from pymongo import ReturnDocument

FEEDBACK = "feedback"
COUNTERS = "feedback_counters"
COOLDOWN_DAYS = 7  # the same person rates the same staff member once a week (tickets don't count)
COMMENT_MAX = 1000
LABELS = {10: "Excelente", 9: "Muy bien", 8: "Bien", 7: "Bien", 6: "Normal", 5: "Normal", 4: "Regular", 3: "Mal", 2: "Mal", 1: "Muy mal"}


class FeedbackError(Exception):
    """Message is safe to show to users."""


def IsStaff(member, config: dict) -> bool:
    """Staff role, any of the profile roles, or one of the high offices."""
    Roles = {R.id for R in getattr(member, "roles", [])}
    Chosen = set(config.get("profile_roles") or [])
    if config.get("staff_role"):
        Chosen.add(config["staff_role"])
    Chosen |= {O.get("role") for O in (config.get("offices") or {}).values() if O.get("role")}
    return bool(Roles & Chosen)


def Stars(rating: int) -> str:
    Full = round(rating / 2)
    return "★" * Full + "☆" * (5 - Full)


class Feedback:
    def __init__(self, db):
        self.col = db[FEEDBACK]
        self.counters = db[COUNTERS]

    async def NextId(self, guild_id: int) -> int:
        Key = f"guild:{guild_id}"
        if not await self.counters.find_one({"_id": Key}):
            # Continue after Birb's old IDs instead of repeating them.
            Last = await self.col.find({"guild_id": guild_id}, {"feedbackid": 1}).sort("feedbackid", -1).limit(1).to_list(length=1)
            Start = int((Last[0].get("feedbackid") or 0) if Last else 0)
            await self.counters.update_one({"_id": Key}, {"$setOnInsert": {"value": Start}}, upsert=True)
        Doc = await self.counters.find_one_and_update({"_id": Key}, {"$inc": {"value": 1}}, return_document=ReturnDocument.AFTER)
        return int(Doc["value"])

    async def Check(self, guild_id: int, author_id: int, staff_id: int, ticket: str | None = None):
        """Raises FeedbackError if this rating isn't allowed."""
        if author_id == staff_id:
            raise FeedbackError("No puedes valorarte a ti mismo.")
        if ticket:
            if await self.col.find_one({"guild_id": guild_id, "ticket": ticket}):
                raise FeedbackError("Ya dejaste tu feedback de este ticket. ¡Gracias!")
            return
        Since = time.time() - COOLDOWN_DAYS * 86400
        Last = await self.col.find_one({"guild_id": guild_id, "author": author_id, "staff": staff_id, "ticket": None, "date": {"$gt": Since}})
        if Last:
            Next = int(Last["date"] + COOLDOWN_DAYS * 86400)
            raise FeedbackError(f"Ya valoraste a esta persona hace poco. Podrás volver a hacerlo {Stamp(Next)}.")

    async def Add(self, guild_id: int, author_id: int, staff_id: int, rating: int, comment: str = "", ticket: str | None = None, ticket_name: str | None = None) -> dict:
        if not 1 <= int(rating) <= 10:
            raise FeedbackError("La nota va del 1 al 10.")
        await self.Check(guild_id, author_id, staff_id, ticket)
        Doc = {
            "guild_id": guild_id,
            "staff": staff_id,
            "author": author_id,
            "rating": int(rating),
            "feedback": (comment or "").strip()[:COMMENT_MAX],
            "date": time.time(),
            "feedbackid": await self.NextId(guild_id),
            "ticket": ticket,
            "ticket_name": ticket_name,
        }
        await self.col.insert_one(Doc)
        return Doc

    async def Of(self, guild_id: int, staff_id: int) -> list[dict]:
        return await self.col.find({"guild_id": guild_id, "staff": staff_id}).sort("date", -1).to_list(length=None)

    async def Remove(self, guild_id: int, feedback_id: int) -> dict | None:
        return await self.col.find_one_and_delete({"guild_id": guild_id, "feedbackid": feedback_id})


def Summary(docs: list[dict]) -> tuple[float | None, int]:
    Values = []
    for D in docs:
        try:
            Values.append(float(str(D.get("rating")).split("/")[0]))
        except ValueError:
            continue
    return (sum(Values) / len(Values), len(Values)) if Values else (None, 0)
