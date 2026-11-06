"""
Staff profiles: created automatically for everyone who has one of the staff roles the admins chose
(independent of Birb's hierarchy). Their rank is the highest of those roles; departments come from roles; each person writes their description and specialty;
the rating comes from /feedback (1-10). Shares the StaffProfiles documents with /gestion.
"""

from datetime import datetime, timezone

from core.mail.config import OFFICES, InDepartment, OfficesOf

PROFILES = "StaffProfiles"
FEEDBACK = "feedback"
DESCRIPTION_MAX = 500
SPECIALTY_MAX = 100
ADMIN_GROUP = "Departamento Administrativo"


def Now() -> datetime:
    return datetime.now(timezone.utc)


def Rank(member, staff_roles: set[int]) -> object | None:
    """The highest of the chosen staff roles the member has (their cargo), or None if they aren't staff."""
    Roles = [R for R in getattr(member, "roles", []) if R.id in staff_roles]
    return max(Roles, key=lambda R: R.position, default=None)


def Groups(member, config: dict) -> list[tuple[str, str]]:
    """(group, department) pairs the member belongs to: the high offices count as the Departamento Administrativo."""
    Out = [(ADMIN_GROUP, OFFICES[O]) for O in sorted(OfficesOf(member, config))]
    for D in config["departments"]:
        if InDepartment(member, D):
            Out.append((D.get("group") or D["name"], D["name"]))
    return Out


def Duration(since: datetime | None, now: datetime | None = None) -> str:
    """'3 meses', '1 año y 2 meses', '12 días'."""
    if not since:
        return "—"
    Since = since if since.tzinfo else since.replace(tzinfo=timezone.utc)
    Days = max(0, ((now or Now()) - Since).days)
    Years, Rest = divmod(Days, 365)
    Months = Rest // 30
    if Years:
        Text = f"{Years} año{'s' if Years > 1 else ''}"
        return Text + (f" y {Months} mes{'es' if Months > 1 else ''}" if Months else "")
    if Months:
        return f"{Months} mes{'es' if Months > 1 else ''}"
    return "hoy" if Days == 0 else f"{Days} día{'s' if Days > 1 else ''}"


class Profiles:
    def __init__(self, db):
        self.db = db
        self.col = db[PROFILES]
        self.feedback = db[FEEDBACK]

    async def Get(self, guild_id: int, user_id: int) -> dict | None:
        return await self.col.find_one({"guild_id": guild_id, "staff": user_id})

    async def Sync(self, guild_id: int, member, rank) -> dict | None:
        """Creates or updates a profile from the member's current rank. The time in the role restarts
        only when the rank changes. Returns the profile (None if they aren't staff: it's archived)."""
        Key = {"guild_id": guild_id, "staff": member.id}
        Current = await self.col.find_one(Key) or {}
        if rank is None:
            if Current.get("active"):
                await self.col.update_one(Key, {"$set": {"active": False}})
            return None
        Changes = {"active": True, "rank": rank.id, "name": getattr(member, "display_name", "")}
        if Current.get("rank") != rank.id or not Current.get("since"):
            Changes["since"] = Now()
        await self.col.update_one(Key, {"$set": Changes, "$setOnInsert": {"sanctions": 0, "notes": []}}, upsert=True)
        return await self.col.find_one(Key)

    async def SetText(self, guild_id: int, user_id: int, description: str, specialty: str):
        await self.col.update_one(
            {"guild_id": guild_id, "staff": user_id},
            {"$set": {"description": description.strip()[:DESCRIPTION_MAX], "specialty": specialty.strip()[:SPECIALTY_MAX]}},
        )

    async def SetSince(self, guild_id: int, user_id: int, since: datetime) -> bool:
        Done = await self.col.update_one({"guild_id": guild_id, "staff": user_id}, {"$set": {"since": since}})
        return bool(Done.matched_count)

    async def Rating(self, guild_id: int, user_id: int) -> tuple[float | None, int]:
        """Average /feedback rating (1-10) and how many there are."""
        Values = []
        for Doc in await self.feedback.find({"guild_id": guild_id, "staff": user_id}, {"rating": 1}).to_list(length=None):
            try:
                Values.append(float(str(Doc.get("rating")).split("/")[0]))
            except ValueError:
                continue
        return (sum(Values) / len(Values), len(Values)) if Values else (None, 0)

    async def Active(self, guild_id: int) -> list[dict]:
        return await self.col.find({"guild_id": guild_id, "active": True}).to_list(length=None)
