import asyncio
from types import SimpleNamespace as N

import pytest

from core.mail import config as C
from tests.economy.fakes import DB

G = 1


def run(coro):
    return asyncio.run(coro)


def member(*roles, admin=False):
    return N(id=7, roles=[N(id=R) for R in roles], guild_permissions=N(administrator=admin))


def test_credential_format_and_hash():
    assert C.NormalizeCredential(" m1808 ") == "M-1808"
    assert C.NormalizeCredential("C-1243") == "C-1243"
    for bad in ("1808", "MM-1808", "M-180", "M-18089", ""):
        with pytest.raises(C.MailError):
            C.NormalizeCredential(bad)
    stored = C.Hash("M-1808")
    assert "M-1808" not in str(stored)  # only the hash is kept
    assert C.Matches("m-1808", stored) and not C.Matches("M-1809", stored) and not C.Matches("nope", stored)
    assert C.CREDENTIAL.match(C.NewCredential())


def test_lockout_after_too_many_fails():
    config = C.DefaultConfig(G)
    config["offices"]["tenno"]["credential"] = C.Hash("M-1808")
    attempts = C.Attempts()
    for _ in range(C.MAX_FAILS):
        with pytest.raises(C.MailError):
            C.CheckCredential(G, 5, "M-0000", ("tenno",), config, attempts)
    with pytest.raises(C.MailError, match="intentos"):
        C.CheckCredential(G, 5, "M-1808", ("tenno",), config, attempts)  # even the right one, while locked
    assert C.CheckCredential(G, 6, "M-1808", ("tenno",), config, attempts) == "tenno"  # others aren't affected


def test_credential_only_works_for_the_allowed_offices():
    config = C.DefaultConfig(G)
    config["offices"]["director"]["credential"] = C.Hash("D-4321")
    attempts = C.Attempts()
    assert C.CheckCredential(G, 5, "D-4321", C.MANAGE_ANY_TASK, config, attempts) == "director"
    with pytest.raises(C.MailError):
        C.CheckCredential(G, 5, "D-4321", C.DECIDE_SUGGESTIONS, config, attempts)  # the director can't decide suggestions


def test_permissions_by_role():
    config = C.DefaultConfig(G)
    config["staff_role"] = 10
    config["offices"]["tenno"]["role"] = 20
    config["offices"]["consejo"]["role"] = 30
    mods = config["departments"][0]
    mods["role"] = 40
    assert C.IsStaff(member(10), config) and C.IsStaff(member(30), config) and not C.IsStaff(member(99), config)
    assert C.HasAny(member(30), C.DECIDE_SUGGESTIONS, config) and not C.HasAny(member(40), C.DECIDE_SUGGESTIONS, config)
    assert C.InDepartment(member(40), mods) and not C.InDepartment(member(10), mods)
    assert C.CanConfigure(member(20), config) and C.CanConfigure(member(admin=True), config)
    assert not C.CanConfigure(member(30), config)


def test_storage_departments_and_credentials():
    store = C.MailConfig(DB())
    config = run(store.Get(G))
    assert [D["name"] for D in config["departments"]] == [N_ for N_, _ in C.DEFAULT_DEPARTMENTS]
    assert set(config["offices"]) == set(C.OFFICES)
    new = run(store.AddDepartment(G, "  Eventos ", "Extra"))
    with pytest.raises(C.MailError):
        run(store.AddDepartment(G, "eventos"))
    run(store.UpdateDepartment(G, new["id"], {"role": 55, "channel": 66}))
    assert C.Department(run(store.Get(G)), new["id"])["role"] == 55
    run(store.RemoveDepartment(G, new["id"]))
    assert C.Department(run(store.Get(G)), new["id"]) is None
    code = run(store.SetCredential(G, "tenno", "m1808"))
    assert code == "M-1808" and C.Matches("M-1808", run(store.Get(G))["offices"]["tenno"]["credential"])
    generated = run(store.SetCredential(G, "director", ""))
    assert C.CREDENTIAL.match(generated)
    run(store.Set(G, {"offices.tenno.role": 20}))
    assert run(store.Get(G))["offices"]["tenno"]["role"] == 20
