import asyncio
from types import SimpleNamespace as N

from core.staff.stafflist import MAIN, Clean, Embed, Filter, Names
from tests.economy.fakes import DB


def run(c):
    return asyncio.run(c)


def test_old_ranks_belong_to_the_main_list():
    D = DB()
    Col = D["Staff List"]
    run(Col.insert_one({"guild_id": 1, "rank": 10, "position": 1}))  # from before (no list)
    run(Col.insert_one({"guild_id": 1, "rank": 20, "position": 1, "list": "eventos"}))
    Main = run(Col.find(Filter(1, None)).to_list(length=None))
    Events = run(Col.find(Filter(1, "Eventos ")).to_list(length=None))
    assert [R["rank"] for R in Main] == [10] and [R["rank"] for R in Events] == [20]
    assert run(Names(D, 1)) == [MAIN, "eventos"]
    assert Clean(None) == MAIN and Clean("  ANIME ") == "anime"


def test_each_list_uses_only_its_ranks():
    def Role(id, pos):
        return N(id=id, position=pos, mention=f"<@&{id}>")

    Boss, Mod, EvLead, EvHelper = Role(1, 50), Role(2, 40), Role(3, 30), Role(4, 20)
    Ana = N(mention="<@100>", roles=[Mod, EvLead])  # in both branches
    Luis = N(mention="<@200>", roles=[EvHelper])
    Guild = N(name="S", icon=None, members=[Ana, Luis], get_role=lambda i: {1: Boss, 2: Mod, 3: EvLead, 4: EvHelper}.get(i))
    Main = Embed(Guild, [{"rank": 1, "position": 1}, {"rank": 2, "position": 2}], None).description
    Events = Embed(Guild, [{"rank": 3, "position": 1}, {"rank": 4, "position": 2}], "Equipo de eventos").description
    assert "<@&2>** (1)" in Main and "<@100>" in Main and "<@200>" not in Main
    assert "<@&3>** (1)" in Events and "<@&4>** (1)" in Events and "<@200>" in Events
