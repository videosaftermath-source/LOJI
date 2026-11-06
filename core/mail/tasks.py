"""Tasks: what a 'Se realizará' turns into. Pendiente -> Reclamada -> Hecha (and back, if needed)."""

from datetime import datetime, timezone

from pymongo import ReturnDocument

TASKS = "mail_tasks"
COUNTERS = "mail_counters"

# status -> (emoji, label)
TASK_STATUSES = {"open": ("🕓", "Pendiente"), "claimed": ("🙋", "Reclamada"), "done": ("✅", "Hecha")}
ACTIVE = ("open", "claimed")
PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}
PRIORITY_COLORS = {"high": 0xE74C3C, "medium": 0xF1C40F, "low": 0x2ECC71}
DONE_COLOR = 0x95A5A6
LIST_LIMIT = 15


def Now() -> datetime:
    return datetime.now(timezone.utc)


def SortKey(task: dict):
    return (PRIORITY_ORDER.get(task["priority"], 9), task["number"])


class Tasks:
    def __init__(self, db):
        self.col = db[TASKS]
        self.counters = db[COUNTERS]

    async def Setup(self):
        await self.col.create_index([("guild_id", 1), ("number", 1)], unique=True)
        await self.col.create_index([("guild_id", 1), ("status", 1)])

    async def Create(
        self, guild_id: int, suggestion: dict | None, department: str | None, priority: str, created_by: int,
        title: str = "", text: str = "", owner: str = "dept",
    ) -> dict:
        """
        A task from an accepted suggestion, or a direct one (suggestion None, with title and text).
        owner: "dept" (the department claims it), "self" (the decider does it) or "done" (already done).
        """
        Counter = await self.counters.find_one_and_update(
            {"_id": f"task:{guild_id}"}, {"$inc": {"value": 1}}, upsert=True, return_document=ReturnDocument.AFTER
        )
        Doc = {
            "guild_id": guild_id,
            "number": int(Counter["value"]),
            "title": suggestion["title"] if suggestion else title,
            "text": suggestion["text"] if suggestion else text,
            "suggestion": suggestion["number"] if suggestion else None,
            "suggestion_author": suggestion["author_id"] if suggestion else None,
            "department": department if owner == "dept" else None,
            "priority": priority,
            "owner": owner,
            "status": {"dept": "open", "self": "claimed", "done": "done"}[owner],
            "claimed_by": created_by if owner != "dept" else None,
            "done_by": created_by if owner == "done" else None,
            "created_by": created_by,
            "created_at": Now(),
            "message": None,
        }
        await self.col.insert_one(Doc)
        return Doc

    async def Get(self, guild_id: int, number: int) -> dict | None:
        return await self.col.find_one({"guild_id": guild_id, "number": number})

    async def SetMessage(self, guild_id: int, number: int, channel_id: int, message_id: int):
        await self.col.update_one({"guild_id": guild_id, "number": number}, {"$set": {"message": {"channel": channel_id, "id": message_id}}})

    async def Move(self, guild_id: int, number: int, from_states: tuple[str, ...], changes: dict) -> dict | None:
        """Changes a task only if it's still in one of `from_states` (two clicks can't both win)."""
        return await self.col.find_one_and_update(
            {"guild_id": guild_id, "number": number, "status": {"$in": list(from_states)}},
            {"$set": changes},
            return_document=ReturnDocument.AFTER,
        )

    async def Claim(self, guild_id: int, number: int, user_id: int):
        return await self.Move(guild_id, number, ("open",), {"status": "claimed", "claimed_by": user_id, "claimed_at": Now()})

    async def Release(self, guild_id: int, number: int):
        return await self.Move(guild_id, number, ("claimed",), {"status": "open", "claimed_by": None})

    async def Done(self, guild_id: int, number: int, user_id: int):
        return await self.Move(guild_id, number, ACTIVE, {"status": "done", "done_by": user_id, "done_at": Now()})

    async def Reopen(self, guild_id: int, number: int):
        return await self.Move(guild_id, number, ("done",), {"status": "open", "claimed_by": None, "done_by": None})

    async def List(self, guild_id: int, statuses: tuple[str, ...], department: str | None = None) -> list[dict]:
        Query = {"guild_id": guild_id, "status": {"$in": list(statuses)}}
        if department == "central":  # the Mando Central's own tasks (no department)
            Query["department"] = None
        elif department:
            Query["department"] = department
        Docs = await self.col.find(Query).to_list(length=None)
        return sorted(Docs, key=SortKey)
