"""
Roleban (quarantine): the member loses every role except the quarantine one, which only shows the
quarantine channel. The removed roles are saved, and /roleban pardon gives them back. Leaving the server
while rolebanned means a ban.

Some roles can't be taken away and stay: managed ones (booster, bots, integrations) and any role at or
above the bot's highest role (Discord doesn't let the bot touch those).
"""

from datetime import datetime, timezone

COLLECTION = "rolebans"
CONFIG = "roleban_config"


def Now() -> datetime:
    return datetime.now(timezone.utc)


def Plan(roles: list, quarantine_id: int, bot_top_position: int) -> tuple[list, list]:
    """(roles to take away, roles that stay). @everyone and the quarantine role are in neither."""
    Remove, Keep = [], []
    for R in roles:
        if getattr(R, "is_default", lambda: False)() or R.id == quarantine_id:
            continue
        if getattr(R, "managed", False) or R.position >= bot_top_position:
            Keep.append(R)
        else:
            Remove.append(R)
    return Remove, Keep


def Restorable(saved: list[dict], guild_roles: dict, bot_top_position: int) -> tuple[list, list[dict]]:
    """(roles to give back, saved roles that can't be: deleted, or now above the bot)."""
    Back, Lost = [], []
    for S in saved:
        Role = guild_roles.get(S["id"])
        if Role and not getattr(Role, "managed", False) and Role.position < bot_top_position:
            Back.append(Role)
        else:
            Lost.append(S)
    return Back, Lost


class Rolebans:
    def __init__(self, db):
        self.col = db[COLLECTION]
        self.config = db[CONFIG]

    async def Config(self, guild_id: int) -> dict:
        return await self.config.find_one({"_id": guild_id}) or {}

    async def SetConfig(self, guild_id: int, changes: dict):
        await self.config.update_one({"_id": guild_id}, {"$set": changes}, upsert=True)

    async def Active(self, guild_id: int, user_id: int) -> dict | None:
        return await self.col.find_one({"guild_id": guild_id, "user_id": user_id, "active": True})

    async def Start(self, guild_id: int, user_id: int, roles: list, by: int, reason: str) -> dict | None:
        """Saves the roleban. None if there's already one (two moderators at once: only one wins)."""
        if await self.Active(guild_id, user_id):
            return None
        Doc = {
            "guild_id": guild_id, "user_id": user_id, "active": True, "by": by, "reason": reason, "at": Now(),
            "roles": [{"id": R.id, "name": R.name} for R in roles],
        }
        Result = await self.col.update_one(
            {"guild_id": guild_id, "user_id": user_id, "active": True}, {"$setOnInsert": Doc}, upsert=True,
        )
        return Doc if Result.upserted_id is not None else None

    async def End(self, guild_id: int, user_id: int, how: str, by: int | None, reason: str = "") -> dict | None:
        """Closes the active roleban ("pardon" or "left"). Returns it, or None if there wasn't one."""
        Doc = await self.Active(guild_id, user_id)
        if not Doc:
            return None
        Done = await self.col.update_one(
            {"_id": Doc["_id"], "active": True},
            {"$set": {"active": False, "ended": {"how": how, "by": by, "reason": reason, "at": Now()}}},
        )
        return Doc if Done.modified_count else None

    async def List(self, guild_id: int) -> list[dict]:
        return await self.col.find({"guild_id": guild_id, "active": True}).to_list(length=None)

    async def History(self, guild_id: int, user_id: int) -> list[dict]:
        return await self.col.find({"guild_id": guild_id, "user_id": user_id}).to_list(length=None)


def RolesList(roles: list[dict], limit: int = 3900) -> str:
    """'1. Name (id)' lines, cut to fit an embed."""
    Lines, Size = [], 0
    for I, R in enumerate(roles, 1):
        Line = f"{I}. {R['name']} ({R['id']})"
        if Size + len(Line) + 1 > limit:
            Lines.append(f"… y {len(roles) - I + 1} más")
            break
        Lines.append(Line)
        Size += len(Line) + 1
    return "\n".join(Lines) or "*ninguno*"
