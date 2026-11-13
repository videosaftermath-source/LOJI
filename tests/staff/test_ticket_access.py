from types import SimpleNamespace as N

from core.mail.config import DefaultConfig
from core.ticket_access import CanForceUnclaim, IsTicketStaff


def member(*roles, admin=False):
    return N(roles=[N(id=r) for r in roles], guild_permissions=N(administrator=admin, manage_guild=False))


def config():
    c = DefaultConfig(1)
    c["staff_role"], c["profile_roles"] = 10, [11]
    c["offices"]["director"]["role"] = 12
    c["departments"][1]["role"] = 13
    return c


def test_who_is_ticket_staff():
    c = config()
    for m in (member(10), member(11), member(12), member(13), member(55), member(admin=True)):
        assert IsTicketStaff(m, [55], c)
    assert not IsTicketStaff(member(99), [55], c)
    assert not IsTicketStaff(member(99), [], DefaultConfig(1))


def test_force_unclaim():
    c = config()
    assert CanForceUnclaim(member(12), c) and CanForceUnclaim(member(admin=True), c)
    assert not CanForceUnclaim(member(10, 11, 13), c)
