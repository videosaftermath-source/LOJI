import asyncio

import pytest

from core.economy.config import ConfigError, EconomyConfig
from core.economy.constants import DEFAULT_CONFIG
from tests.economy.fakes import DB

G = 1


def run(coro):
    return asyncio.run(coro)


def test_defaults():
    c = EconomyConfig(DB())
    assert run(c.Get(G)) == DEFAULT_CONFIG


def test_set_and_reset():
    c = EconomyConfig(DB())
    assert run(c.Set(G, "work.max", "1.000"))["work"]["max"] == 1000
    assert run(c.Set(G, "work.max", ""))["work"]["max"] == DEFAULT_CONFIG["work"]["max"]


def test_other_values_keep_defaults():
    c = EconomyConfig(DB())
    run(c.Set(G, "currency.name", "Monedas"))
    cfg = run(c.Get(G))
    assert cfg["currency"]["name"] == "Monedas"
    assert cfg["currency"]["emoji"] == DEFAULT_CONFIG["currency"]["emoji"]


@pytest.mark.parametrize(
    "path,value",
    [("work.max", "abc"), ("work.max", "-1"), ("work.min", "999999"), ("daily.grace", "3600"), ("nope.x", "1")],
)
def test_invalid_values(path, value):
    c = EconomyConfig(DB())
    with pytest.raises(ConfigError):
        run(c.Set(G, path, value))
    assert run(c.Get(G)) == DEFAULT_CONFIG
