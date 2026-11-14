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


def test_rank_is_the_highest_of_the_chosen_roles():
    chosen = {HELPER.id, SENIOR.id}  # MOD isn't chosen: it doesn't count, even if it's in between
    assert Rank(member(1, HELPER, SENIOR), chosen) is SENIOR
    assert Rank(member(1, MOD), chosen) is None
    assert Rank(member(1, MOD, HELPER), chosen) is HELPER
    assert Rank(member(1, SENIOR), set()) is None


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
        await C._shared.Set(G, {"profile_roles": [10]})
        await db["Tickets"].insert_one({"ChannelID": 500, "UserID": 7, "closed": None})
        cog = PP.StaffProfiles(N())
        await cog.on_message(N(author=owner, guild=guild, channel=channel))
        await cog.on_ticket_claimed(channel, staff)
        await cog.on_message(N(author=staff, guild=guild, channel=channel))

    run(scenario())
    assert len(sent) == 1 and sent[0]["embed"].title == "🎫 Te atiende Ana"


def test_wrong_rank_change_is_undone_with_its_original_date():
    store = Profiles(DB())
    long_ago = datetime(2025, 1, 10, tzinfo=timezone.utc)
    run(store.col.insert_one({"guild_id": G, "staff": 1, "rank": SENIOR.id, "since": long_ago, "active": True}))
    m = member(1, HELPER, SENIOR)
    run(store.Sync(G, m, HELPER))  # the mistake
    p = run(store.Get(G, 1))
    assert p["rank"] == HELPER.id and p["history"][-1]["rank"] == SENIOR.id
    p = run(store.Sync(G, m, SENIOR))  # fixed: the date comes back
    assert p["rank"] == SENIOR.id and p["since"].replace(tzinfo=timezone.utc) == long_ago


def test_repair_uses_promotions_and_audit_log():
    import cogs.Modules.Profiles.profiles as P
    from unittest import mock

    db = DB()
    store = Profiles(db)
    now = datetime.now(timezone.utc)
    promoted = datetime(2026, 3, 1)
    given = now - timedelta(days=10)
    for uid, rank in ((1, SENIOR.id), (2, MOD.id), (3, MOD.id)):
        run(db["StaffProfiles"].insert_one({"guild_id": G, "staff": uid, "rank": rank, "since": now, "active": True}))
    run(db["promotions"].insert_one({"guild_id": G, "staff": 1, "new": SENIOR.id, "timestamp": promoted}))

    async def audit(guild, days=45):
        return {(2, MOD.id): given}

    with mock.patch.object(P, "Store", lambda: store), mock.patch.object(P, "RoleAddedDates", audit):
        fixed, unknown = run(P.RepairDates(N(id=G), 72))
    assert {(u, s) for u, _, s in fixed} == {(1, "ascenso registrado"), (2, "registro de auditoría")}
    assert unknown == [3]
    assert run(store.Get(G, 1))["since"].replace(tzinfo=timezone.utc) == promoted.replace(tzinfo=timezone.utc)
