import asyncio
from types import SimpleNamespace as N

from core.mail.config import DefaultConfig
from core.mail.tasks import Tasks
from tests.economy.fakes import DB

G = 1


def run(coro):
    return asyncio.run(coro)


def suggestion(number=1):
    return {"number": number, "title": "Torneos", "text": "Semanales", "author_id": 5}


def test_task_lifecycle_and_order():
    t = Tasks(DB())
    run(t.Setup())
    low = run(t.Create(G, suggestion(1), "dep", "low", 9))
    high = run(t.Create(G, suggestion(2), "dep", "high", 9))
    assert (low["number"], high["number"], low["status"]) == (1, 2, "open")
    assert [x["number"] for x in run(t.List(G, ("open",)))] == [2, 1]  # high priority first
    assert run(t.Claim(G, 1, 7))["claimed_by"] == 7
    assert run(t.Claim(G, 1, 8)) is None  # already claimed
    assert run(t.Release(G, 1))["status"] == "open"
    assert run(t.Done(G, 1, 7))["done_by"] == 7
    assert run(t.Done(G, 1, 7)) is None and run(t.Release(G, 1)) is None
    assert run(t.Reopen(G, 1))["status"] == "open"
    assert len(run(t.List(G, ("open",), "other"))) == 0


def test_who_can_do_what():
    from cogs.Modules.Mail.tasks import AllowedByRole

    config = DefaultConfig(G)
    config["departments"][0]["role"] = 40
    config["offices"]["director"]["role"] = 50
    dep = config["departments"][0]["id"]
    task = {"department": dep, "claimed_by": 7, "status": "claimed"}
    member = lambda uid, *roles: N(id=uid, roles=[N(id=r) for r in roles])  # noqa: E731
    assert AllowedByRole(member(1, 40), "done", task, config) and AllowedByRole(member(1, 40), "claim", task, config)
    assert not AllowedByRole(member(1, 99), "claim", task, config)  # other department
    assert AllowedByRole(member(7, 40), "release", task, config) and not AllowedByRole(member(1, 40), "release", task, config)
    assert not AllowedByRole(member(1, 40), "reopen", task, config)
    assert AllowedByRole(member(2, 50), "reopen", task, config) and AllowedByRole(member(2, 50), "claim", task, config)
