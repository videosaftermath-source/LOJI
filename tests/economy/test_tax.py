import asyncio

import pytest

from core.economy.config import Merge
from core.economy.constants import DEFAULT_CONFIG, LEDGER
from core.economy.service import EconomyService, InsufficientFunds
from core.economy.tax import TransferFee
from tests.economy.fakes import DB


def config(pct):
    return Merge(DEFAULT_CONFIG, {"transfer": {"fee_percent": pct}})


@pytest.mark.parametrize("amount,pct,fee", [(100, 7, 7), (10, 7, 1), (1000, 7, 70), (15, 7, 2), (100, 0, 0), (333, 2.5, 9)])
def test_fee(amount, pct, fee):
    assert TransferFee(amount, config(pct)) == fee


def test_transfer_charges_and_destroys_fee():
    s = EconomyService(DB())
    asyncio.run(s.Add(1, 1, 107, "test"))
    From, To = asyncio.run(s.Transfer(1, 1, 2, 100, "pago", fee=7))
    assert From["balance"] == 0 and To["balance"] == 100
    sender = s.db.db[LEDGER].find_one({"user_id": 1, "kind": "transfer"})
    assert sender["amount"] == -107 and sender["fee"] == 7


def test_fee_counts_for_funds():
    s = EconomyService(DB())
    asyncio.run(s.Add(1, 1, 100, "test"))
    with pytest.raises(InsufficientFunds):
        asyncio.run(s.Transfer(1, 1, 2, 100, "pago", fee=7))
    assert asyncio.run(s.Balance(1, 1)) == 100
