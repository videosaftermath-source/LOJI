import asyncio
from types import SimpleNamespace as N

from core.staff.medals import FALLBACK, MedalEmojis, MedalRoles, PrettyName
from tests.economy.fakes import DB


def run(c):
    return asyncio.run(c)


class Icon:
    def __init__(self, key):
        self.key = key

    async def read(self):
        return b"png"


class Emoji:
    count = 100

    def __init__(self, name, log):
        Emoji.count += 1
        self.name, self.id, self.log = name, Emoji.count, log

    def __str__(self):
        return f"<:{self.name}:{self.id}>"

    async def delete(self):
        self.log.append(("delete", self.name))

    async def edit(self, name):
        self.log.append(("rename", self.name, name))
        self.name = name
        return self


def client(log, existing=()):
    class C:
        async def fetch_application_emojis(self):
            log.append("fetch")
            return list(existing)

        async def create_application_emoji(self, name, image):
            log.append(("create", name))
            return Emoji(name, log)

    return C()


def test_pretty_names():
    assert PrettyName("Medalla de Oro ⭐") == "Medalla_de_Oro"
    assert PrettyName("Guardián del Año") == "Guardian_del_Ano"
    assert PrettyName("🏅") == "medalla"
    assert len(PrettyName("x" * 50)) == 32


def test_named_like_the_role_renamed_and_replaced():
    log = []
    m = MedalEmojis(client(log), DB())
    gold = N(id=101, position=9, name="Medalla de Oro", unicode_emoji=None, icon=Icon("abc123456789"))
    silver = N(id=102, position=5, name="Plata", unicode_emoji="🥈", icon=None)
    plain = N(id=103, position=7, name="Sin icono", unicode_emoji=None, icon=None)
    roles = MedalRoles(N(roles=[silver, N(id=1, position=1), gold, plain]), {"medal_roles": [101, 102, 103]})
    assert [r.name for r in roles] == ["Medalla de Oro", "Sin icono", "Plata"]
    line = run(m.Line(roles))
    assert line.startswith("<:Medalla_de_Oro:") and line.endswith(f"> Medalla de Oro · {FALLBACK} Sin icono · 🥈 Plata")
    run(m.Line(roles))
    assert log.count("fetch") == 1 and len([x for x in log if x[0] == "create"]) == 1
    gold.name = "Oro Supremo"  # renamed role: same emoji, new name
    assert run(m.Get(gold)).startswith("<:Oro_Supremo:")
    assert ("rename", "Medalla_de_Oro", "Oro_Supremo") in log
    gold.icon = Icon("zzz99999")  # new icon: new emoji, old one deleted
    run(m.Get(gold))
    assert ("delete", "Oro_Supremo") in log and log[-1] == ("create", "Oro_Supremo")


def test_old_emojis_are_renamed_not_uploaded_again():
    log = []
    old = Emoji("m1570324415781011497_902e3754", log)
    m = MedalEmojis(client(log, [old]), DB())
    role = N(id=1570324415781011497, position=3, name="Veterano", unicode_emoji=None, icon=Icon("902e3754aaaa"))
    assert run(m.Get(role)) == f"<:Veterano:{old.id}>"
    assert not [x for x in log if x[0] == "create"]


def test_two_roles_with_the_same_name_get_different_emojis():
    log = []
    m = MedalEmojis(client(log), DB())
    a = N(id=1, position=2, name="Héroe", unicode_emoji=None, icon=Icon("aaaa1111"))
    b = N(id=2, position=1, name="Heroe", unicode_emoji=None, icon=Icon("bbbb2222"))
    assert run(m.Get(a)).startswith("<:Heroe:") and run(m.Get(b)).startswith("<:Heroe_2:")


def test_catalog_lists_every_medal_with_how_and_counts():
    from core.staff.medals import CatalogEmbed

    gold = N(id=1, position=9, name="Oro", unicode_emoji="🥇", icon=None, members=[1, 2])
    rare = N(id=2, position=3, name="Rara", unicode_emoji=None, icon=None, members=[1])
    guild = N(get_role=lambda i: {1: gold, 2: rare}.get(i))
    config = {"medal_roles": [2, 1], "medal_info": {"1": "Cerrar 100 tickets"}}
    e = run(CatalogEmbed(guild, config, N(roles=[rare])))
    lines = e.description.split("\n")
    assert lines[0] == "🥇 **Oro** · 2 la tienen" and lines[1] == "> Cerrar 100 tickets"
    assert lines[2].startswith("🏅 **Rara** ✅ · 1 la tiene") and "Sin descripción" in lines[3]
    assert e.footer.text == "Tienes 1 de 2"
