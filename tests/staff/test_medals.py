import asyncio
from types import SimpleNamespace as N

from core.staff.medals import FALLBACK, EmojiName, MedalEmojis, MedalRoles


def run(c):
    return asyncio.run(c)


class Icon:
    def __init__(self, key):
        self.key = key

    async def read(self):
        return b"png"


class Emoji:
    def __init__(self, name, log):
        self.name, self.id, self.log = name, len(log) + 1, log

    def __str__(self):
        return f"<:{self.name}:{self.id}>"

    async def delete(self):
        self.log.append(("delete", self.name))


def test_medals_in_order_and_icons_uploaded_once():
    log = []

    class Client:
        async def fetch_application_emojis(self):
            log.append("fetch")
            return []

        async def create_application_emoji(self, name, image):
            log.append(("create", name))
            return Emoji(name, log)

    gold = N(id=101, position=9, name="Oro", unicode_emoji=None, icon=Icon("abc123456789"))
    silver = N(id=102, position=5, name="Plata", unicode_emoji="🥈", icon=None)
    plain = N(id=103, position=7, name="Sin icono", unicode_emoji=None, icon=None)
    member = N(roles=[silver, N(id=1, position=1), gold, plain])
    roles = MedalRoles(member, {"medal_roles": [101, 102, 103]})
    assert [r.name for r in roles] == ["Oro", "Sin icono", "Plata"]
    m = MedalEmojis(Client())
    line = run(m.Line(roles))
    assert line.startswith(f"<:{EmojiName(101, 'abc123456789')}:") and line.endswith(f"> Oro · {FALLBACK} Sin icono · 🥈 Plata")
    run(m.Line(roles))
    assert log.count("fetch") == 1 and len([x for x in log if x[0] == "create"]) == 1
    gold.icon = Icon("zzz99999")  # icon changed: new emoji, old one deleted
    run(m.Get(gold))
    assert ("delete", EmojiName(101, "abc123456789")) in log
    assert len(EmojiName(10**19, "a_0123456789abcdef")) <= 32
