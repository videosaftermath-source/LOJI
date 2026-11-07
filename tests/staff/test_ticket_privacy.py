import asyncio
from types import SimpleNamespace as N

import core.mail.config as C
from cogs.Modules.ticketprivacy import TicketPrivacy
from tests.economy.fakes import DB


class Obj:
    def __init__(self, id, name):
        self.id, self.name = id, name


def test_claim_hides_transfer_moves_unclaim_restores():
    fake = DB()
    C._shared = C.MailConfig(fake)
    roles = {50: Obj(50, "Moderación"), 51: Obj(51, "Comité")}
    people = {3: Obj(3, "Ana"), 4: Obj(4, "Beto"), 7: Obj(7, "Pepe")}
    guild = N(id=1, get_role=lambda r: roles.get(r), get_member=lambda u: people.get(u))

    class Channel:
        id, perms = 500, {roles[50]: "staff", roles[51]: "staff", people[7]: "author"}
        overwrites = property(lambda self: self.perms)

        async def set_permissions(self, target, overwrite="keep", reason=None, **kw):
            if overwrite is None:
                self.perms.pop(target, None)
            else:
                self.perms[target] = "hidden" if kw.get("read_messages") is False else "access"

    channel = Channel()
    channel.guild = guild

    def state():
        return {k.name: v for k, v in channel.perms.items()}

    async def scenario():
        await fake["Panels"].insert_one({"name": "Reporte", "type": "single", "guild": 1, "permissions": [50, 51]})
        ticket = await fake["Tickets"].insert_one({"ChannelID": 500, "GuildID": 1, "panel": "Reporte", "UserID": 7})
        cog = TicketPrivacy(N(db=fake, get_channel=lambda c: channel))
        await cog.on_ticket_claimed(channel, people[3])
        claimed = state()
        await cog.on_ticket_claimed(channel, people[4])
        transferred = state()
        await cog.on_unclaim(ticket.inserted_id)
        return claimed, transferred, state()

    claimed, transferred, unclaimed = asyncio.run(scenario())
    assert claimed == {"Moderación": "hidden", "Comité": "hidden", "Pepe": "author", "Ana": "access"}
    assert transferred == {"Moderación": "hidden", "Comité": "hidden", "Pepe": "author", "Beto": "access"}
    assert unclaimed == {"Moderación": "access", "Comité": "access", "Pepe": "author"}
