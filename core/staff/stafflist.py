"""Staff lists: the main one (Birb's) and any others (another branch of the staff, with its own ranks and channel).

Ranks and posted lists saved before there were several have no "list" field: they belong to the main list.
"""

from datetime import datetime

import discord

MAIN = "principal"
DEFAULT_TITLE = "Staff Team"


def Clean(name: str | None) -> str:
    return (name or MAIN).strip().lower()[:40] or MAIN


def Filter(guild_id: int, name: str | None) -> dict:
    """Mongo filter for one list's documents (the main list also matches the old ones without a name)."""
    Name = Clean(name)
    if Name == MAIN:
        return {"guild_id": guild_id, "$or": [{"list": {"$exists": False}}, {"list": None}, {"list": MAIN}]}
    return {"guild_id": guild_id, "list": Name}


def Embed(guild: discord.Guild, ranks: list[dict], title: str | None) -> discord.Embed:
    """The same look as Birb's list: each rank with the members whose highest rank (in this list) it is."""
    Ranks = sorted(ranks, key=lambda R: int(R.get("position", 0)))
    Ids = {R["rank"] for R in Ranks}
    Highest = []  # (member, their highest rank in this list)
    for Member in guild.members:
        Top = max((Role for Role in Member.roles if Role.id in Ids), key=lambda Role: Role.position, default=None)
        if Top:
            Highest.append((Member, Top))
    embed = discord.Embed(title=title or DEFAULT_TITLE, color=discord.Color.dark_embed(), timestamp=datetime.now())
    embed.set_thumbnail(url=guild.icon)
    embed.set_author(name=guild.name, icon_url=guild.icon)
    embed.set_footer(text="Last Updated")
    Text = ""
    for R in Ranks:
        Role = guild.get_role(R.get("rank"))
        if not Role:
            continue
        Members = [M.mention for M, Top in Highest if Top.id == Role.id]
        if Members:
            Text += f"### **{Role.mention}** ({len(Members)})\n\n> " + "\n> ".join(Members) + "\n"
    embed.description = Text[:4096]
    return embed


async def Names(db, guild_id: int) -> list[str]:
    Found = {Clean(D.get("list")) for D in await db["Staff List"].find({"guild_id": guild_id}).to_list(length=None)}
    return sorted(Found | {MAIN}, key=lambda N: (N != MAIN, N))
