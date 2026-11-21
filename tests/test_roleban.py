import asyncio
from types import SimpleNamespace as N

from core.roleban import Plan, Restorable, Rolebans, RolesList
from tests.economy.fakes import DB

G = 1


def run(coro):
    return asyncio.run(coro)


def role(id, position, managed=False, default=False, name=None):
    return N(id=id, position=position, managed=managed, name=name or f"r{id}", is_default=lambda: default)


def test_plan_keeps_what_the_bot_cant_touch():
    Everyone, Normal, Booster, High, Quarantine = role(1, 0, default=True), role(2, 3), role(3, 4, managed=True), role(4, 20), role(5, 2)
    Remove, Keep = Plan([Everyone, Normal, Booster, High, Quarantine], quarantine_id=5, bot_top_position=10)
    assert [R.id for R in Remove] == [2]
    assert [R.id for R in Keep] == [3, 4]


def test_restore_skips_deleted_and_higher_roles():
    Saved = [{"id": 2, "name": "a"}, {"id": 3, "name": "borrado"}, {"id": 4, "name": "alto"}]
    Back, Lost = Restorable(Saved, {2: role(2, 3), 4: role(4, 20)}, bot_top_position=10)
    assert [R.id for R in Back] == [2]
    assert [L["name"] for L in Lost] == ["borrado", "alto"]


def test_one_active_roleban_and_pardon():
    S = Rolebans(DB())
    assert run(S.Start(G, 5, [role(2, 3, name="Economía")], by=9, reason="spam"))
    assert run(S.Start(G, 5, [], by=8, reason="otra vez")) is None  # already in quarantine
    assert run(S.Active(G, 5))["roles"] == [{"id": 2, "name": "Economía"}]
    Ended = run(S.End(G, 5, "pardon", 9))
    assert Ended and not run(S.Active(G, 5))
    assert run(S.End(G, 5, "pardon", 9)) is None
    assert run(S.Start(G, 5, [], by=9, reason="de nuevo"))  # can be rolebanned again later
    assert len(run(S.History(G, 5))) == 2


def test_roles_list_fits():
    Roles = [{"id": 10**17 + I, "name": "x" * 50} for I in range(200)]
    Text = RolesList(Roles)
    assert len(Text) <= 4000 and Text.endswith("más")
    assert RolesList([]) == "*ninguno*"


def test_up_to_three_quarantine_channels():
    import pytest
    from core.roleban import SetSlot, Slots

    assert Slots({"role": 7, "channel": 70}) == [{"channel": 70, "role": 7}]  # old single setup still works
    assert Slots({}) == []
    S = SetSlot([], 70, 7)
    S = SetSlot(S, 71, 8)
    S = SetSlot(S, 72, 9)
    S = SetSlot(S, 71, 10)  # same channel: only the role changes, order kept
    assert S == [{"channel": 70, "role": 7}, {"channel": 71, "role": 10}, {"channel": 72, "role": 9}]
    with pytest.raises(ValueError):
        SetSlot(S, 73, 11)


def test_roleban_remembers_its_channel():
    S = Rolebans(DB())
    run(S.Start(G, 5, [], by=9, reason="x", slot={"channel": 71, "role": 8}))
    Doc = run(S.Active(G, 5))
    assert (Doc["channel"], Doc["role"]) == (71, 8)
