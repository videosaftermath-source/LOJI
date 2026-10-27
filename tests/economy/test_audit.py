import asyncio

from core.economy.audit import Audit, Classify, MaxGrind, Summarize
from core.economy.config import Merge
from core.economy.constants import DEFAULT_CONFIG
from core.economy.registry import Build
from core.economy.service import EconomyService
from tests.economy.fakes import DB

CONFIG = Merge(DEFAULT_CONFIG, {})
G = 1


def run(coro):
    return asyncio.run(coro)


def test_classify():
    assert Classify("bet", "Apuesta: crash") == Classify("payout", "Premio: crash") == "casino"
    assert Classify("created", "Trabajar") == Classify("created", "Ingresos de Shiba Samurái") == "grind"
    assert Classify("created", "Código HALLOWEEN2026") == Classify("created", "Misión: Charla") == "rewards"
    assert Classify("created", "Admin 1: oops") == Classify("destroyed", "Reinicio de economía por admin 1: x") == "admin"
    assert Classify("transfer", "Pago a 5") == "transfers"
    assert Classify("destroyed", "Compra: 1x Pizza") is None
    assert Classify("bank", "Depósito en el banco") is None


def test_flags():
    limit = MaxGrind(1, CONFIG)
    rows = [
        {"user_id": 1, "kind": "created", "reason": "Trabajar", "money": limit + 1, "count": 30},
        {"user_id": 2, "kind": "created", "reason": "Admin 9: error", "money": 50_000, "count": 1},
        {"user_id": 3, "kind": "transfer", "reason": "Pago a 3", "money": 4_000, "count": 2},
        {"user_id": 3, "kind": "created", "reason": "Trabajar", "money": 1_000, "count": 10},
        {"user_id": 4, "kind": "bet", "reason": "Apuesta: slots", "money": -1_000, "count": 10},
        {"user_id": 4, "kind": "payout", "reason": "Premio: slots", "money": 3_000, "count": 4},
        {"user_id": 4, "kind": "destroyed", "reason": "Compra: 1x Pizza", "money": -500, "count": 1},
    ]
    users = {U["user_id"]: U for U in Summarize(rows, 1, CONFIG)}
    assert users[1]["flags"] and "máximo" in users[1]["flags"][0]
    assert any("admins" in F for F in users[2]["flags"])
    assert any("otros usuarios" in F for F in users[3]["flags"])
    assert users[4]["casino"] == 2_000 and users[4]["games"] == 10 and users[4]["total"] == 2_000 and not users[4]["flags"]
    assert [U["user_id"] for U in Summarize(rows, 1, CONFIG)][0] == 2


def test_audit_reads_the_ledger_and_period():
    s = Build(EconomyService(DB()))
    run(s.Setup())
    run(s.economy.Add(G, 5, 120, "Trabajar"))
    run(s.economy.Add(G, 5, 50_000, "Admin 1: oops"))
    run(s.economy.Transfer(G, 5, 6, 1_000, "Pago a 6", fee=50))
    users = {U["user_id"]: U for U in run(Audit(s.economy, G, "24h", CONFIG))}
    assert users[5]["grind"] == 120 and users[5]["admin"] == 50_000 and users[5]["transfers"] == -1_050
    assert users[6]["transfers"] == 1_000
