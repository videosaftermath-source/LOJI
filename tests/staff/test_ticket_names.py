import asyncio
from types import SimpleNamespace as N

from core.ticket_names import ClaimedName, NextNumber, OpenName, PeekNext, Render, SetNext
from tests.economy.fakes import DB


def run(c):
    return asyncio.run(c)


def test_counter_is_per_panel_and_adjustable():
    db = DB()
    assert [run(NextNumber(db, 1, "Reporte")) for _ in range(3)] == [1, 2, 3]
    assert run(NextNumber(db, 1, "Reporte Staff")) == 1
    assert run(NextNumber(db, 2, "Reporte")) == 1
    run(SetNext(db, 1, "Reporte", 85))
    assert run(PeekNext(db, 1, "Reporte")) == 85 and run(NextNumber(db, 1, "Reporte")) == 85


def test_names():
    user, mod = N(name="reaper85", id=5), N(name="mod", id=6)
    panel = {"name": "Reporte Staff", "TicketNames": {"Open": "reporte-staff-{number}", "Claimed": "✅ {number} {claimer.name}"}}
    assert OpenName(panel, {"Number": 7}, user) == "reporte-staff-007"
    assert ClaimedName(panel, {"Number": 7}, user, mod) == "✅-007-mod"
    assert OpenName({"name": "Reporte"}, {"Number": 12}, user) == "reporte-012"
    assert ClaimedName({"name": "Reporte"}, {"Number": 12}, user, mod) == "claimed-reporte-012"
    assert Render("{user.name}-{number}", "", 1000, "x", user) == "reaper85-1000"
