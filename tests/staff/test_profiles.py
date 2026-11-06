import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as N

from core.mail.config import DefaultConfig
from core.staff.profiles import ADMIN_GROUP, Duration, Groups, Profiles, Rank
from tests.economy.fakes import DB

G = 1


def run(coro):
    return asyncio.run(coro)


def role(rid, pos):
    return N(id=rid, position=pos, is_default=lambda: False)


HELPER, MOD, SENIOR, TENNO = role(10, 5), role(11, 6), role(12, 8), role(20, 20)


def member(uid, *roles):
    return N(id=uid, roles=list(roles), display_name=f"user{uid}")


def test_rank_is_the_highest_role_from_the_minimum():
    assert Rank(member(1, HELPER, SENIOR), HELPER) is SENIOR
    assert Rank(member(1, role(99, 2)), HELPER) is None
    assert Rank(member(1, MOD), None) is None


def test_groups_from_departments_and_offices():
    config = DefaultConfig(G)
    config["offices"]["tenno"]["role"] = 20
    config["departments"][0]["role"] = 11  # Moderación
    config["departments"][1]["role"] = 12  # Comité de Ética (Mod Senior)
    assert Groups(member(1, MOD), config) == [("Moderación", "Moderación")]
    assert Groups(member(1, SENIOR), config) == [("Mod Senior", "Comité de Ética")]
    assert (ADMIN_GROUP, "Tenno") in Groups(member(1, TENNO, MOD), config)


def test_duration():
    now = datetime(2026, 11, 6, tzinfo=timezone.utc)
    assert Duration(now, now) == "hoy"
    assert Duration(now - timedelta(days=12), now) == "12 días"
    assert Duration(now - timedelta(days=95), now) == "3 meses"
    assert Duration(now - timedelta(days=430), now) == "1 año y 2 meses"
    assert Duration(None) == "—"


def test_sync_restarts_time_only_on_promotion_and_archives():
    p = Profiles(DB())
    first = run(p.Sync(G, member(5, MOD), MOD))
    old = datetime(2025, 1, 1, tzinfo=timezone.utc)
    run(p.SetSince(G, 5, old))
    same = run(p.Sync(G, member(5, MOD), MOD))
    assert first["active"] and same["since"].replace(tzinfo=timezone.utc) == old  # same rank: date kept
    promoted = run(p.Sync(G, member(5, MOD, SENIOR), SENIOR))
    assert promoted["rank"] == SENIOR.id and promoted["since"].replace(tzinfo=timezone.utc) > old
    run(p.SetText(G, 5, " Hola ", " Reportes "))
    assert run(p.Get(G, 5))["specialty"] == "Reportes"
    assert run(p.Sync(G, member(5), None)) is None and not run(p.Get(G, 5))["active"]
    assert run(p.Get(G, 5))["description"] == "Hola"  # their text survives being archived


def test_rating_from_feedback():
    db = DB()
    p = Profiles(db)
    for r in ("8", "10", "6/10", "x"):
        run(db["feedback"].insert_one({"guild_id": G, "staff": 5, "rating": r}))
    avg, count = run(p.Rating(G, 5))
    assert count == 3 and abs(avg - 8) < 1e-9
    assert run(p.Rating(G, 6)) == (None, 0)


def test_ticket_card_once_per_staff_member():
    import discord

    import core.mail.config as C
    import cogs.Modules.Profiles.profiles as PP

    db = DB()
    C._shared, PP._store = C.MailConfig(db), Profiles(db)
    roles = {10: N(id=10, position=5, is_default=lambda: False, mention="@Helper", color=discord.Color(0))}
    guild = N(id=G, name="ESS", get_role=lambda r: roles.get(r))
    sent = []

    async def send(**k):
        sent.append(k)

    channel = N(id=500, guild=guild, send=send)
    staff = N(id=3, display_name="Ana", roles=[roles[10]], guild=guild, bot=False, display_avatar=N(url="http://a"))
    owner = N(id=7, display_name="Pepe", roles=[], guild=guild, bot=False)

    async def scenario():
        await C._shared.Set(G, {"profile_min_role": 10})
        await db["Tickets"].insert_one({"ChannelID": 500, "UserID": 7, "closed": None})
        cog = PP.StaffProfiles(N())
        await cog.on_message(N(author=owner, guild=guild, channel=channel))
        await cog.on_ticket_claimed(channel, staff)
        await cog.on_message(N(author=staff, guild=guild, channel=channel))

    run(scenario())
    assert len(sent) == 1 and sent[0]["embed"].title == "🎫 Te atiende Ana"
