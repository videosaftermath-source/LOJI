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


def test_bulk_ids_from_mentions_and_ids():
    from cogs.Modules.roleban import ParseIds

    Text = "<@123456789012345678>, <@!223456789012345678> 323456789012345678\n123456789012345678 hola 42"
    assert ParseIds(Text) == [123456789012345678, 223456789012345678, 323456789012345678]


def test_who_can_be_quarantined():
    from cogs.Modules.roleban import CanQuarantine

    Me = N(top_role=10)
    Guild = N(owner_id=1, me=Me)
    Mod = N(id=2, top_role=8)
    def M(id, top, bot=False):
        return N(id=id, top_role=top, bot=bot, mention=f"<@{id}>")
    assert CanQuarantine(Guild, Mod, M(3, 1)) is None
    assert "tuyo" in CanQuarantine(Guild, Mod, M(3, 8))
    assert CanQuarantine(Guild, Mod, M(1, 1))  # the owner
    assert CanQuarantine(Guild, Mod, M(4, 1, bot=True))
    assert "mío" in CanQuarantine(Guild, N(id=1, top_role=99), M(5, 12))


def test_enforce_fixes_permissions_and_reports():
    import discord
    from cogs.Modules.roleban import Roleban

    class Channel:
        def __init__(self, id, broken=False):
            self.id, self.mention, self.broken, self.ow = id, f"<#{id}>", broken, {}

        def overwrites_for(self, role):
            return discord.PermissionOverwrite(**self.ow.get(role.id, {}))

        async def set_permissions(self, role, overwrite, reason=None):
            if self.broken:
                raise discord.Forbidden(N(status=403, reason="x"), "no")
            self.ow[role.id] = {K: V for K, V in overwrite if V is not None}

    Edited = []

    async def edit(permissions, reason=None):
        Edited.append(permissions.value)

    Role = N(id=7, mention="<@&7>", permissions=discord.Permissions(view_channel=True), edit=edit)
    Own, General, Category, Locked = Channel(70), Channel(71), Channel(72), Channel(73, broken=True)
    General.ow[7] = {"view_channel": True}  # someone gave it access by mistake
    Guild = N(id=G, channels=[Own, General, Category, Locked], get_role=lambda i: Role if i == 7 else None,
              get_channel=lambda i: Own if i == 70 else None)
    Cog = Roleban.__new__(Roleban)
    Cog.locks = {}
    Fixed, Failed = run(Cog.Enforce(Guild, {"slots": [{"channel": 70, "role": 7}]}))
    assert Edited == [0]  # the role grants nothing now
    def Got(channel):
        O = channel.overwrites_for(Role)
        return (O.view_channel, O.send_messages, O.read_message_history)

    assert Got(Own) == (True, True, True)
    assert Got(General) == (False, None, None) and Got(Category) == (False, None, None)
    assert any("3" in F for F in Fixed) and any("<#73>" in F for F in Failed)
    Role.permissions = discord.Permissions.none()
    Fixed, Failed = run(Cog.Enforce(Guild, {"slots": [{"channel": 70, "role": 7}]}))
    assert Fixed == [] and len(Failed) == 1  # nothing left to fix (only the channel it can't touch)
