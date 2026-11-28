"""Tasks: what a 'Se realizará' turns into. Pendiente -> Reclamada -> Hecha (and back, if needed)."""

import re
from datetime import datetime, timedelta, timezone

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
        assignees: list[int] | None = None, deadline: datetime | None = None, banner: str | None = None,
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
            "assignees": list(dict.fromkeys(assignees or [])),  # people it was given to (direct tasks)
            "deadline": deadline,
            "banner": banner,  # file name of the image sent with the task message
        }
        if Doc["assignees"] and owner == "dept":  # given to people: it starts as theirs
            Doc["status"], Doc["claimed_by"] = "claimed", Doc["assignees"][0]
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
        """Takes an open task (one person, as always), or joins a task that was given to several people."""
        Task = await self.col.find_one_and_update(
            {"guild_id": guild_id, "number": number, "status": "open"},
            {"$set": {"status": "claimed", "claimed_by": user_id, "claimed_at": Now()}},
            return_document=ReturnDocument.AFTER,
        )
        if Task:
            return Task
        return await self.col.find_one_and_update(
            {"guild_id": guild_id, "number": number, "status": "claimed", "assignees.0": {"$exists": True}},
            {"$addToSet": {"assignees": user_id}}, return_document=ReturnDocument.AFTER,
        )

    async def Release(self, guild_id: int, number: int, user_id: int | None = None):
        """One person leaves; when nobody is left, the task is open again."""
        Task = await self.Get(guild_id, number)
        if not Task or Task["status"] != "claimed":
            return None
        Left = [A for A in Task.get("assignees") or [] if A != user_id] if user_id else []
        Changes = {"assignees": Left, "claimed_by": Left[0] if Left else None, "status": "claimed" if Left else "open"}
        return await self.Move(guild_id, number, ("claimed",), Changes)

    async def Done(self, guild_id: int, number: int, user_id: int):
        return await self.Move(guild_id, number, ACTIVE, {"status": "done", "done_by": user_id, "done_at": Now()})

    async def Reopen(self, guild_id: int, number: int):
        Task = await self.Get(guild_id, number)
        People = (Task or {}).get("assignees") or []
        return await self.Move(guild_id, number, ("done",), {
            "status": "claimed" if People else "open", "claimed_by": People[0] if People else None, "done_by": None,
            "deadline_warned": None,
        })

    async def Due(self, now: datetime) -> list[dict]:
        """Active tasks with a deadline that need a reminder (24 h before) or are now overdue."""
        return await self.col.find({
            "status": {"$in": list(ACTIVE)}, "deadline": {"$ne": None, "$lte": now + REMIND_BEFORE},
            "deadline_warned": {"$ne": "overdue"},
        }).to_list(length=None)

    async def List(self, guild_id: int, statuses: tuple[str, ...], department: str | None = None) -> list[dict]:
        Query = {"guild_id": guild_id, "status": {"$in": list(statuses)}}
        if department == "central":  # the Mando Central's own tasks (no department)
            Query["department"] = None
        elif department:
            Query["department"] = department
        Docs = await self.col.find(Query).to_list(length=None)
        return sorted(Docs, key=SortKey)


# ---------------- deadlines ----------------

REMIND_BEFORE = timedelta(hours=24)
DURATION = re.compile(r"(\d+)\s*(d|h|m)", re.I)
DATE = re.compile(r"^(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?(?:\s+(\d{1,2}):(\d{2}))?$")


def ParseDeadline(text: str, now: datetime, utc_offset: int = 0) -> datetime:
    """'3d', '12h', '2d6h', '45m' (from now) or '05/12', '05/12/2026', '05/12 18:00' (server time).
    A date without hour means the end of that day. Raises ValueError."""
    Text = (text or "").strip().lower()
    if not Text:
        raise ValueError
    Match = DATE.match(Text)
    if Match:
        Day, Month, Year, Hour, Minute = Match.groups()
        Year = int(Year) + (2000 if Year and len(Year) == 2 else 0) if Year else None
        Local = now + timedelta(hours=utc_offset)
        Year = Year or Local.year
        H, M = (int(Hour), int(Minute)) if Hour else (23, 59)
        When = datetime(Year, int(Month), int(Day), H, M, tzinfo=timezone.utc) - timedelta(hours=utc_offset)
        if not Match.group(3) and When < now:  # "05/01" in December means next year
            When = When.replace(year=When.year + 1)
    else:
        Parts = DURATION.findall(Text)
        if not Parts or DURATION.sub("", Text).strip():
            raise ValueError
        Units = {"d": "days", "h": "hours", "m": "minutes"}
        When = now + sum((timedelta(**{Units[U.lower()]: int(N)}) for N, U in Parts), timedelta())
    if When <= now:
        raise ValueError
    return When
