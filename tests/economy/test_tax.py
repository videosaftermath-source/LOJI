import asyncio

import pytest

from core.economy.config import ConfigError, EconomyConfig, Merge
from core.economy.constants import DEFAULT_CONFIG
from core.economy.service import EconomyService, InsufficientFunds
from core.economy.tax import BracketTax, EffectiveRate, ParseBrackets, TransferFee
from tests.economy.fakes import DB

CONFIG = Merge(DEFAULT_CONFIG, {})


@pytest.mark.parametrize(
    "amount,tax",
    [
        (100, 5),                              # all in the 5% slice
        (1000, 50),
        (2000, 50 + 80),                       # 1000 at 5% + 1000 at 8%
        (10_000, 50 + 720),
        (60_000, 50 + 720 + 4800 + 1500),      # four slices
    ],
)
def test_progressive_brackets(amount, tax):
    assert BracketTax(amount, CONFIG) == pytest.approx(tax)
    assert TransferFee(amount, CONFIG) == tax


def test_no_jumps_at_bracket_limits():
    assert TransferFee(1001, CONFIG) - TransferFee(1000, CONFIG) <= 1


def test_effective_rate_grows_with_amount():
    rates = [EffectiveRate(a, CONFIG) for a in (500, 5_000, 50_000, 500_000)]
    assert rates == sorted(rates) and rates[0] == pytest.approx(0.05)


def test_discount_and_rounding():
    assert TransferFee(100, CONFIG, 0.5) == 3  # 2.5 rounded up
    assert TransferFee(0, CONFIG) == 0
    assert TransferFee(15, CONFIG) == 1


def test_parse_brackets():
    assert ParseBrackets("0:5, 1.000:8; 10000:12%") == [[0, 5.0], [1000, 8.0], [10000, 12.0]]
    for bad in ["", "5", "100:5", "0:5,0:6", "0:99", "a:5", "0:x"]:
        with pytest.raises(ValueError):
            ParseBrackets(bad)


def test_brackets_editable_from_config():
    c = EconomyConfig(DB())
    cfg = asyncio.run(c.Set(1, "transfer.brackets", "0:0, 5000:10"))
    assert TransferFee(4000, cfg) == 0 and TransferFee(6000, cfg) == 100
    with pytest.raises(ConfigError):
        asyncio.run(c.Set(1, "transfer.brackets", "100:5"))


def test_transfer_charges_and_destroys_fee():
    s = EconomyService(DB())
    asyncio.run(s.Add(1, 1, 107, "test"))
    From, To = asyncio.run(s.Transfer(1, 1, 2, 100, "pago", fee=7))
    assert From["balance"] == 0 and To["balance"] == 100
    sender = s.db.db["eco_ledger"].find_one({"user_id": 1, "kind": "transfer"})
    assert sender["amount"] == -107 and sender["fee"] == 7


def test_fee_counts_for_funds():
    s = EconomyService(DB())
    asyncio.run(s.Add(1, 1, 100, "test"))
    with pytest.raises(InsufficientFunds):
        asyncio.run(s.Transfer(1, 1, 2, 100, "pago", fee=7))
    assert asyncio.run(s.Balance(1, 1)) == 100
