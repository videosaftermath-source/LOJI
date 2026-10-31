import asyncio
from types import SimpleNamespace as N

from core.mail.suggestions import Suggestions
from tests.economy.fakes import DB

G = 1


def run(coro):
    return asyncio.run(coro)


def test_numbering_and_decisions():
    s = Suggestions(DB())
    run(s.Setup())
    a = run(s.Create(G, N(id=5, display_name="Pepe"), "  Más   eventos ", "Texto"))
    b = run(s.Create(G, N(id=6, display_name="Ana"), "Otra", "Texto"))
    assert (a["number"], b["number"], a["title"], a["status"]) == (1, 2, "Más eventos", "pending")
    assert run(s.Create(2, N(id=5), "x", "y"))["number"] == 1  # numbering is per server
    debated = run(s.Decide(G, 1, "debate", {"by": 9, "office": "tenno", "reason": "hablarlo"}))
    assert debated["status"] == "debate"
    assert run(s.Decide(G, 1, "debate", {"by": 9, "office": "tenno", "reason": "otra vez"})) is None  # can't debate twice
    done = run(s.Decide(G, 1, "do", {"by": 9, "office": "consejo", "reason": "sí", "department": "x", "priority": "high"}))
    assert done["status"] == "do" and done["decision"]["priority"] == "high"
    assert run(s.Decide(G, 1, "reject", {"by": 9, "office": "tenno", "reason": "no"})) is None  # already decided
    assert run(s.Decide(G, 2, "reject", {"by": 9, "office": "tenno", "reason": "no"}))["status"] == "reject"
