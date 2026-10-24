import asyncio

import pytest

from core.economy.constants import CREATED, DESTROYED, LEDGER, TRANSFER
from core.economy.service import ConditionFailed, EconomyService, InsufficientFunds, InvalidAmount
from tests.economy.fakes import DB

G = 1


def run(coro):
    return asyncio.run(coro)


def service():
    return EconomyService(DB())


def ledger(s):
    return list(s.db.db[LEDGER].find({}, {"_id": 0}))


def test_new_account_starts_at_zero():
    s = service()
    assert run(s.Balance(G, 10)) == 0


def test_add_and_remove_write_ledger():
    s = service()
    run(s.Add(G, 10, 100, "test"))
    run(s.Remove(G, 10, 30, "test"))
    assert run(s.Balance(G, 10)) == 70
    entries = ledger(s)
    assert [(e["amount"], e["kind"], e["balance_after"]) for e in entries] == [
        (100, CREATED, 100),
        (-30, DESTROYED, 70),
    ]


def test_cannot_go_negative():
    s = service()
    run(s.Add(G, 10, 50, "test"))
    with pytest.raises(InsufficientFunds) as e:
        run(s.Remove(G, 10, 51, "test"))
    assert e.value.balance == 50
    assert run(s.Balance(G, 10)) == 50
    assert len(ledger(s)) == 1


def test_remove_exact_balance():
    s = service()
    run(s.Add(G, 10, 50, "test"))
    run(s.Remove(G, 10, 50, "test"))
    assert run(s.Balance(G, 10)) == 0


@pytest.mark.parametrize("amount", [0, -5, 1.5, True])
def test_invalid_amounts(amount):
    s = service()
    with pytest.raises(InvalidAmount):
        run(s.Add(G, 10, amount, "test"))


def test_condition_failed_changes_nothing():
    s = service()
    with pytest.raises(ConditionFailed):
        run(s.Add(G, 10, 100, "test", when={"daily.last": "never matches"}))
    assert run(s.Balance(G, 10)) == 0
    assert ledger(s) == []


def test_also_set_is_written_with_the_change():
    s = service()
    run(s.Add(G, 10, 5, "test", also_set={"work.last": 123}))
    assert run(s.Account(G, 10))["work"]["last"] == 123


def test_transfer_moves_money_and_logs_both_sides():
    s = service()
    run(s.Add(G, 1, 100, "test"))
    From, To = run(s.Transfer(G, 1, 2, 40, "pago"))
    assert (From["balance"], To["balance"]) == (60, 40)
    moves = [e for e in ledger(s) if e["kind"] == TRANSFER]
    assert sorted(e["amount"] for e in moves) == [-40, 40]
    assert moves[0]["ref"] == moves[1]["ref"]


def test_transfer_without_funds_changes_nothing():
    s = service()
    run(s.Add(G, 1, 10, "test"))
    with pytest.raises(InsufficientFunds):
        run(s.Transfer(G, 1, 2, 11, "pago"))
    assert run(s.Balance(G, 1)) == 10
    assert run(s.Balance(G, 2)) == 0


def test_cannot_pay_yourself():
    s = service()
    with pytest.raises(InvalidAmount):
        run(s.Transfer(G, 1, 1, 10, "pago"))


def test_concurrent_removes_never_overdraw():
    """20 simultaneous withdrawals of 10 from a balance of 100: exactly 10 succeed."""
    s = service()
    run(s.Add(G, 10, 100, "test"))

    async def attempt():
        try:
            await s.Remove(G, 10, 10, "spam")
            return True
        except InsufficientFunds:
            return False

    async def all_attempts():
        return await asyncio.gather(*(attempt() for _ in range(20)))

    results = run(all_attempts())
    assert sum(results) == 10
    assert run(s.Balance(G, 10)) == 0


def test_concurrent_transfers_keep_total():
    s = service()
    run(s.Add(G, 1, 100, "test"))
    run(s.Add(G, 2, 100, "test"))

    async def go():
        tasks = [s.Transfer(G, 1, 2, 7, "a") for _ in range(10)] + [s.Transfer(G, 2, 1, 5, "b") for _ in range(10)]
        return await asyncio.gather(*tasks, return_exceptions=True)

    run(go())
    assert run(s.Balance(G, 1)) + run(s.Balance(G, 2)) == 200


def test_top_and_rank():
    s = service()
    for user, amount in [(1, 50), (2, 300), (3, 100)]:
        run(s.Add(G, user, amount, "test"))
    run(s.Account(G, 4))  # zero balance: not ranked
    assert [a["user_id"] for a in run(s.Top(G, 0, 10))] == [2, 3, 1]
    assert run(s.Rank(G, 3)) == 2
    assert run(s.Rank(G, 4)) is None
    assert run(s.CountRanked(G)) == 3
