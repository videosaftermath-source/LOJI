"""Suggestions sent with /mail: numbered, decided once (debate is a stop on the way)."""

from datetime import datetime, timezone

from pymongo import ReturnDocument

SUGGESTIONS = "mail_suggestions"
COUNTERS = "mail_counters"
TITLE_MAX = 100
TEXT_MAX = 2000
REASON_MAX = 1000

# status -> (emoji, label, color)
STATUSES = {
    "pending": ("⏳", "Pendiente", 0x95A5A6),
    "debate": ("💬", "Se debatirá", 0xE6A23C),
    "do": ("✅", "Se realizará", 0x2ECC71),
    "reject": ("❌", "Rechazada", 0xE74C3C),
}
OPEN = ("pending", "debate")  # can still be decided
PRIORITIES = {"high": ("🔴", "Alta"), "medium": ("🟡", "Media"), "low": ("🟢", "Baja")}


def Now() -> datetime:
    return datetime.now(timezone.utc)


class Suggestions:
    def __init__(self, db):
        self.col = db[SUGGESTIONS]
        self.counters = db[COUNTERS]

    async def Setup(self):
        await self.col.create_index([("guild_id", 1), ("number", 1)], unique=True)

    async def NextNumber(self, guild_id: int) -> int:
        Doc = await self.counters.find_one_and_update(
            {"_id": f"suggestion:{guild_id}"}, {"$inc": {"value": 1}}, upsert=True, return_document=ReturnDocument.AFTER
        )
        return int(Doc["value"])

    async def Create(self, guild_id: int, author, title: str, text: str) -> dict:
        Doc = {
            "guild_id": guild_id,
            "number": await self.NextNumber(guild_id),
            "author_id": author.id,
            "author_name": getattr(author, "display_name", str(author)),
            "author_avatar": str(getattr(getattr(author, "display_avatar", None), "url", "") or ""),
            "title": " ".join(title.split())[:TITLE_MAX],
            "text": text.strip()[:TEXT_MAX],
            "status": "pending",
            "created_at": Now(),
            "message": None,
            "debate_message": None,
            "decision": None,
        }
        await self.col.insert_one(Doc)
        return Doc

    async def Get(self, guild_id: int, number: int) -> dict | None:
        return await self.col.find_one({"guild_id": guild_id, "number": number})

    async def SetMessage(self, guild_id: int, number: int, field: str, channel_id: int, message_id: int):
        await self.col.update_one({"guild_id": guild_id, "number": number}, {"$set": {field: {"channel": channel_id, "id": message_id}}})

    async def Decide(self, guild_id: int, number: int, status: str, decision: dict) -> dict | None:
        """Records a decision if the suggestion is still open. Returns the updated doc, or None."""
        Allowed = [S for S in OPEN if not (status == "debate" and S == "debate")]
        return await self.col.find_one_and_update(
            {"guild_id": guild_id, "number": number, "status": {"$in": Allowed}},
            {"$set": {"status": status, "decision": {**decision, "at": Now()}}},
            return_document=ReturnDocument.AFTER,
        )
