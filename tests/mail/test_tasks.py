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


def test_direct_tasks_and_owners():
    t = Tasks(DB())
    run(t.Setup())
    mine = run(t.Create(G, None, "dep", "high", 8, title="Revisar", text="Canales", owner="self"))
    done = run(t.Create(G, suggestion(3), "dep", "low", 8, owner="done"))
    assert (mine["status"], mine["claimed_by"], mine["department"], mine["suggestion"]) == ("claimed", 8, None, None)
    assert (done["status"], done["done_by"], done["title"]) == ("done", 8, "Torneos")
    assert [x["number"] for x in run(t.List(G, ("claimed",), "central"))] == [mine["number"]]


def test_whoever_took_it_can_finish_it():
    from cogs.Modules.Mail.tasks import AllowedByRole

    config = DefaultConfig(G)
    task = {"department": None, "claimed_by": 8, "status": "claimed"}
    assert AllowedByRole(N(id=8, roles=[]), "done", task, config)
    assert not AllowedByRole(N(id=9, roles=[]), "done", task, config)


def test_tasks_for_several_people():
    t = Tasks(DB())
    run(t.Setup())
    task = run(t.Create(G, None, None, "medium", 9, title="Evento", text="Montarlo", assignees=[7, 8, 7]))
    assert (task["status"], task["assignees"], task["claimed_by"]) == ("claimed", [7, 8], 7)
    assert run(t.Claim(G, task["number"], 10))["assignees"] == [7, 8, 10]  # someone else joins
    left = run(t.Release(G, task["number"], 7))
    assert (left["assignees"], left["claimed_by"], left["status"]) == ([8, 10], 8, "claimed")
    run(t.Release(G, task["number"], 8))
    assert run(t.Release(G, task["number"], 10))["status"] == "open"  # nobody left: open again
    done = run(t.Create(G, None, None, "low", 9, title="X", text="Y", assignees=[5]))
    run(t.Done(G, done["number"], 5))
    assert run(t.Reopen(G, done["number"]))["status"] == "claimed"  # reopened, it goes back to its people


def test_deadlines():
    from datetime import datetime, timedelta, timezone

    import pytest

    from core.mail.tasks import ParseDeadline

    now = datetime(2026, 12, 20, 12, 0, tzinfo=timezone.utc)
    assert ParseDeadline("3d", now) == now + timedelta(days=3)
    assert ParseDeadline("2d6h", now) == now + timedelta(days=2, hours=6)
    assert ParseDeadline("45m", now) == now + timedelta(minutes=45)
    assert ParseDeadline("24/12 18:00", now, utc_offset=1) == datetime(2026, 12, 24, 17, 0, tzinfo=timezone.utc)
    assert ParseDeadline("24/12", now) == datetime(2026, 12, 24, 23, 59, tzinfo=timezone.utc)  # end of that day
    assert ParseDeadline("05/01", now).year == 2027  # January means next year
    for bad in ("", "mañana", "3x", "19/12/2026", "3d hola"):
        with pytest.raises(ValueError):
            ParseDeadline(bad, now)


def test_several_people_can_join_and_finish():
    from cogs.Modules.Mail.tasks import AllowedByRole, TaskView

    config = DefaultConfig(G)
    config["staff_role"] = 30
    task = {"number": 4, "department": None, "claimed_by": 7, "assignees": [7, 8], "status": "claimed"}
    assert AllowedByRole(N(id=8, roles=[]), "done", task, config) and AllowedByRole(N(id=8, roles=[]), "release", task, config)
    assert AllowedByRole(N(id=9, roles=[N(id=30)]), "join", task, config)  # any staff can join
    assert not AllowedByRole(N(id=9, roles=[]), "join", task, config)
    assert [B.custom_id for B in TaskView(task).children] == ["task:done:4", "task:join:4", "task:release:4"]
    assert [B.custom_id for B in TaskView({**task, "assignees": []}).children] == ["task:done:4", "task:release:4"]
