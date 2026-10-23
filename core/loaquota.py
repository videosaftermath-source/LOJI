"""
Ties LOA to the message quota.

Every day of approved LOA inside a quota week removes 1/7 of that week's
quota. LOA requests longer than MAX_DAYS, or that would put someone on LOA
for more than MAX_WEEKS quota weeks in a row, are still sent but flagged so
high command can decide.
"""

from datetime import datetime, timedelta

import discord

WEEK = timedelta(days=7)
MAX_DAYS = 5
MAX_WEEKS = 3

# Approved LOAs: accepted requests, or ones an admin created directly.
APPROVED = {
    "request": False,
    "Declined": {"$exists": False},
    "$or": [{"Accepted.user": {"$exists": True}}, {"Created": {"$exists": True}}],
}


async def QuotaWindow(client, guild_id: int) -> tuple[datetime, datetime]:
    """The quota week currently running: (start, end)."""
    Auto = await client.db["auto activity"].find_one({"guild_id": guild_id})
    End = (Auto or {}).get("nextdate")
    if not End:
        # No automatic reset set up: weeks run Monday -> Sunday night.
        Now = datetime.now()
        Monday = (Now - timedelta(days=Now.weekday())).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        End = Monday + WEEK
    return End - WEEK, End


def Overlap(loas: list, start: datetime, end: datetime) -> float:
    """Seconds of LOA inside [start, end), without counting overlapping LOAs twice."""
    Spans = sorted(
        (max(L["start_time"], start), min(L["end_time"], end))
        for L in loas
        if L.get("start_time") and L.get("end_time")
    )
    Total = 0.0
    CurrentStart = CurrentEnd = None
    for S, E in Spans:
        if E <= S:
            continue
        if CurrentEnd is None or S > CurrentEnd:
            if CurrentEnd is not None:
                Total += (CurrentEnd - CurrentStart).total_seconds()
            CurrentStart, CurrentEnd = S, E
        else:
            CurrentEnd = max(CurrentEnd, E)
    if CurrentEnd is not None:
        Total += (CurrentEnd - CurrentStart).total_seconds()
    return Total


async def LOAReduction(
    client, guild_id: int, user_id: int, quota: int, start: datetime, end: datetime
) -> tuple[int, float]:
    """How many messages LOA takes off `quota` in [start, end). Returns (reduction, days)."""
    LOAs = (
        await client.db["loa"]
        .find(
            {
                "guild_id": guild_id,
                "user": user_id,
                "start_time": {"$lt": end},
                "end_time": {"$gt": start},
                **APPROVED,
            }
        )
        .to_list(length=None)
    )
    Days = Overlap(LOAs, start, end) / 86400
    Reduction = min(int(quota), round(int(quota) * Days / 7))
    return Reduction, round(Days, 1)


async def EffectiveQuota(
    client, member: discord.Member, config: dict, window: tuple = None
) -> tuple[int, str, int]:
    """Quota after LOA. Returns (quota, label to show next to it, reduction)."""
    from cogs.Modules.staff import quota as QUOTA

    Quota, Name = QUOTA.GetQuota(None, member, config)
    Start, End = window or await QuotaWindow(client, member.guild.id)
    Reduction, Days = await LOAReduction(
        client, member.guild.id, member.id, Quota, Start, End
    )
    if Reduction:
        Name += f" 🌴 LOA {Days:g}d (-{Reduction}, needs {Quota - Reduction})"
    return Quota - Reduction, Name, Reduction


async def RequestWarnings(
    client, guild_id: int, user_id: int, start: datetime, end: datetime
) -> list[str]:
    """Limits a new LOA request breaks. Empty list = within limits."""
    Warnings = []
    Days = (end - start).total_seconds() / 86400
    if Days > MAX_DAYS + 0.01:
        Warnings.append(f"Dura **{Days:.1f} días** (máximo {MAX_DAYS}).")

    _, Anchor = await QuotaWindow(client, guild_id)

    def WeekOf(t: datetime) -> int:
        return (t - Anchor) // WEEK

    def Weeks(s: datetime, e: datetime) -> set:
        return set(range(WeekOf(s), WeekOf(e - timedelta(microseconds=1)) + 1))

    New = Weeks(start, end)
    Others = (
        await client.db["loa"]
        .find(
            {
                "guild_id": guild_id,
                "user": user_id,
                "end_time": {"$gt": start - WEEK * (MAX_WEEKS + 1)},
                "start_time": {"$lt": end + WEEK * (MAX_WEEKS + 1)},
                "$or": [{"request": True}, APPROVED],
            }
        )
        .to_list(length=None)
    )
    Taken = set(New)
    for L in Others:
        if L.get("start_time") and L.get("end_time") and L["end_time"] > L["start_time"]:
            Taken |= Weeks(L["start_time"], L["end_time"])

    # Longest run of consecutive weeks that includes the new request.
    Low, High = min(New), max(New)
    while Low - 1 in Taken:
        Low -= 1
    while High + 1 in Taken:
        High += 1
    Run = High - Low + 1
    if Run > MAX_WEEKS:
        Warnings.append(
            f"Tendría LOA **{Run} semanas seguidas** de quota (máximo {MAX_WEEKS})."
        )
    return Warnings
