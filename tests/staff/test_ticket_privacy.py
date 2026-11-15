import asyncio
from types import SimpleNamespace as N

import discord

import core.mail.config as C
from cogs.Modules.ticketprivacy import TicketPrivacy
from tests.economy.fakes import DB


class Role:
    def __init__(self, id, name):
        self.id, self.name, self.permissions = id, name, discord.Permissions.none()

    def __eq__(self, other):
        return isinstance(other, Role) and other.id == self.id

    def __hash__(self):
        return hash(("role", self.id))


class Member:
    def __init__(self, id, name, *roles):
        self.id, self.name, self.roles, self.guild_permissions = id, name, list(roles), discord.Permissions.none()

    def __eq__(self, other):
        return isinstance(other, Member) and other.id == self.id

    def __hash__(self):
        return hash(("member", self.id))


def View(**kw):
    return discord.PermissionOverwrite(**kw)


def test_only_the_claimer_sees_it_and_unclaim_restores_everything():
    fake = DB()
    C._shared = C.MailConfig(fake)
    everyone, panel_role, extra_role = Role(1, "@everyone"), Role(50, "Moderación"), Role(52, "Staff general")
    ana, beto, carla = Member(3, "Ana", panel_role), Member(4, "Beto", panel_role), Member(6, "Carla", extra_role)
    author, guest, bot = Member(7, "Pepe"), Member(8, "Testigo"), Member(99, "LOJI")
    people = {m.id: m for m in (ana, beto, carla, author, guest, bot)}
    roles = {1: everyone, 50: panel_role, 52: extra_role}
    guild = N(id=1, default_role=everyone, me=bot, get_role=lambda r: roles.get(r), get_member=lambda u: people.get(u))
    original = {
        everyone: View(read_messages=False), panel_role: View(read_messages=True, send_messages=True),
        extra_role: View(read_messages=True), author: View(read_messages=True, send_messages=True),
        guest: View(read_messages=True), carla: View(read_messages=True, attach_files=True), bot: View(read_messages=True),
    }

    class Channel:
        id, perms = 500, dict(original)
        overwrites = property(lambda self: dict(self.perms))

        async def set_permissions(self, target, *, overwrite=discord.utils.MISSING, reason=None, **kw):
            if overwrite is None:
                self.perms.pop(target, None)
            elif overwrite is not discord.utils.MISSING:
                self.perms[target] = overwrite
            else:
                self.perms[target] = View(**kw)

    channel = Channel()
    channel.guild = guild

    def sees(target):
        o = channel.perms.get(target)
        return bool(o and o.read_messages)

    async def scenario():
        await fake["Panels"].insert_one({"name": "Reporte", "type": "single", "guild": 1, "permissions": [50]})
        ticket = await fake["Tickets"].insert_one({"ChannelID": 500, "GuildID": 1, "panel": "Reporte", "UserID": 7})
        cog = TicketPrivacy(N(db=fake, get_channel=lambda c: channel))
        await cog.on_ticket_claimed(channel, ana)
        claimed = {t.name: sees(t) for t in (panel_role, extra_role, carla, ana, author, guest, bot)}
        await cog.on_ticket_claimed(channel, beto)  # transfer
        transferred = (sees(ana), sees(beto))
        await cog.on_unclaim(ticket.inserted_id)
        return claimed, transferred

    claimed, transferred = asyncio.run(scenario())
    assert claimed == {"Moderación": False, "Staff general": False, "Carla": False, "Ana": True, "Pepe": True, "Testigo": True, "LOJI": True}
    assert transferred == (False, True)
    assert {t.name for t in channel.perms} == {t.name for t in original}, sorted(t.name for t in channel.perms)
    assert channel.perms == original  # exactly as before the claim


def test_two_claims_at_once_only_one_wins():
    import asyncio
    from types import SimpleNamespace as N
    from unittest import mock

    import cogs.Events.on_ticket as OT
    from tests.economy.fakes import DB

    db = DB()
    asyncio.run(db["Tickets"].insert_one({"_id": "t1", "MessageID": 50, "ChannelID": 300, "panel": "Reporte", "claimed": {"claimer": None}}))
    sent, events = [], []

    def inter(uid):
        async def defer(**k):
            pass

        async def send(*a, **k):
            sent.append((uid, a[0] if a else ""))

        async def edit(**k):
            pass

        return N(user=N(id=uid, name=f"u{uid}", display_name=f"u{uid}", mention=f"<@{uid}>", display_avatar=None),
                 guild=N(id=1), channel=N(id=300, name="reporte-001"), message=N(id=50),
                 response=N(defer=defer), followup=N(send=send), edit_original_response=edit,
                 client=N(db=db, dispatch=lambda *a: events.append(a)))

    async def allowed(i):
        return True

    async def main():
        view = OT.PTicketControl()
        with mock.patch.object(OT, "TicketPermissions", allowed):
            await asyncio.gather(*(OT.PTicketControl.claim(view, inter(u), None) for u in (6, 7)))

    try:
        asyncio.run(main())
    except Exception:
        pass  # whatever runs after the claim (renaming) needs a real channel
    claims = [e for e in events if e[0] == "ticket_claimed"]
    assert len(claims) == 1
    winner = asyncio.run(db["Tickets"].find_one({"_id": "t1"}))["claimed"]["claimer"]
    assert any("ya lo reclamó" in t for u, t in sent if u != winner)
