import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as N

import pytest

from core.economy.config import Merge
from core.economy.constants import DEFAULT_CONFIG
from core.economy.registry import Build
from core.economy.service import EconomyService, InsufficientFunds
from core.economy.shop import ShopError
from core.economy.codes import CodeError
from core.economy.quests import PeriodKey, QuestError
from tests.economy.fakes import DB

CONFIG = Merge(DEFAULT_CONFIG, {})
G = 1


def run(coro):
    return asyncio.run(coro)


def services():
    s = Build(EconomyService(DB()))
    run(s.Setup())
    return s


def member(uid, roles=()):
    guild = N(id=G, me=N(guild_permissions=N(manage_roles=True), top_role=10), get_role=lambda rid: None)
    added = []

    async def add_roles(role, reason=None):
        added.append(role)

    return N(id=uid, guild=guild, roles=list(roles), add_roles=add_roles, added=added)


def item(s, **data):
    base = {"name": "Pizza", "price": 100, "type": "collectible", "stock": None, "per_user_limit": None}
    return run(s.shop.Create(G, {**base, **data}))


def test_buy_collectible():
    s = services()
    run(s.economy.Add(G, 5, 250, "seed"))
    i = item(s)
    _, total, account = run(s.shop.Buy(member(5), i["item_id"], 2, CONFIG))
    assert total == 200 and account["balance"] == 50
    assert run(s.shop.Inventory(G, 5))[0]["qty"] == 2


def test_buy_without_money_changes_nothing():
    s = services()
    i = item(s, stock=3)
    with pytest.raises(InsufficientFunds):
        run(s.shop.Buy(member(5), i["item_id"], 1, CONFIG))
    assert run(s.shop.Get(G, i["item_id"]))["stock"] == 3
    assert run(s.shop.Inventory(G, 5)) == []


def test_stock_runs_out_under_concurrency():
    s = services()
    i = item(s, stock=3, price=10)
    for uid in range(10):
        run(s.economy.Add(G, uid, 100, "seed"))

    async def all_buy():
        return await asyncio.gather(*(s.shop.Buy(member(uid), i["item_id"], 1, CONFIG) for uid in range(10)), return_exceptions=True)

    results = run(all_buy())
    assert sum(not isinstance(r, Exception) for r in results) == 3
    assert run(s.shop.Get(G, i["item_id"]))["stock"] == 0
    total = sum(run(s.economy.Balance(G, uid)) for uid in range(10))
    assert total == 1000 - 30


def test_per_user_limit():
    s = services()
    run(s.economy.Add(G, 5, 1000, "seed"))
    i = item(s, per_user_limit=2, price=10)
    run(s.shop.Buy(member(5), i["item_id"], 2, CONFIG))
    with pytest.raises(ShopError):
        run(s.shop.Buy(member(5), i["item_id"], 1, CONFIG))


def test_disabled_items_cant_be_bought():
    s = services()
    run(s.economy.Add(G, 5, 1000, "seed"))
    i = item(s)
    run(s.shop.Update(G, i["item_id"], {"enabled": False}))
    with pytest.raises(ShopError):
        run(s.shop.Buy(member(5), i["item_id"], 1, CONFIG))


def test_role_item():
    s = services()
    run(s.economy.Add(G, 5, 1000, "seed"))
    i = item(s, type="role", role_id=3)
    m = member(5)
    role = N(id=3, mention="@vip", managed=False, is_default=lambda: False, __ge__=lambda a, b: False)

    class Role:
        id = 3
        mention = "@vip"
        managed = False

        def is_default(self):
            return False

        def __ge__(self, other):
            return False

    R = Role()
    m.guild.get_role = lambda rid: R
    run(s.shop.Buy(m, i["item_id"], 5, CONFIG))  # qty forced to 1
    assert m.added == [R]
    assert run(s.economy.Balance(G, 5)) == 900
    m.roles = [R]
    with pytest.raises(ShopError):
        run(s.shop.Buy(m, i["item_id"], 1, CONFIG))


def test_consumable_gives_capped_boost():
    s = services()
    run(s.economy.Add(G, 5, 1000, "seed"))
    i = item(s, type="consumable", price=10, effect={"kind": "work", "value": 0.75, "seconds": 3600})
    run(s.shop.Buy(member(5), i["item_id"], 2, CONFIG))
    run(s.shop.Use(member(5), i["item_id"]))
    assert run(s.bonuses.Total(G, 5, "work", CONFIG)) == pytest.approx(0.75)
    run(s.shop.Use(member(5), i["item_id"]))
    assert run(s.bonuses.Total(G, 5, "work", CONFIG)) == CONFIG["bonuses"]["max"]  # 1.5 capped at 1.0
    assert run(s.bonuses.Total(G, 5, "chat", CONFIG)) == 0
    with pytest.raises(ShopError):
        run(s.shop.Use(member(5), i["item_id"]))  # none left


def test_collectibles_cant_be_used():
    s = services()
    run(s.economy.Add(G, 5, 1000, "seed"))
    i = item(s)
    run(s.shop.Buy(member(5), i["item_id"], 1, CONFIG))
    with pytest.raises(ShopError):
        run(s.shop.Use(member(5), i["item_id"]))


# ---- codes ----


def code(s, **kw):
    args = {"code": "HOLA", "credits": 100, "items": [], "max_uses": None, "expires_at": None, "created_by": 1, **kw}
    return run(s.codes.Create(G, **args))


def test_code_once_per_user():
    s = services()
    code(s)
    run(s.codes.Redeem(G, 5, "hola"))
    assert run(s.economy.Balance(G, 5)) == 100
    with pytest.raises(CodeError):
        run(s.codes.Redeem(G, 5, "HOLA"))
    assert run(s.economy.Balance(G, 5)) == 100


def test_code_max_uses_under_concurrency():
    s = services()
    code(s, max_uses=3)

    async def everyone():
        return await asyncio.gather(*(s.codes.Redeem(G, uid, "HOLA") for uid in range(10)), return_exceptions=True)

    results = run(everyone())
    assert sum(not isinstance(r, Exception) for r in results) == 3


def test_expired_and_missing_codes():
    s = services()
    code(s, expires_at=datetime.now(timezone.utc) - timedelta(minutes=1))
    with pytest.raises(CodeError):
        run(s.codes.Redeem(G, 5, "HOLA"))
    with pytest.raises(CodeError):
        run(s.codes.Redeem(G, 5, "NOPE"))


def test_code_with_item_and_validation():
    s = services()
    i = item(s)
    code(s, code="ITEM", credits=0, items=[{"item_id": i["item_id"], "qty": 2}])
    run(s.codes.Redeem(G, 5, "ITEM"))
    assert run(s.shop.Inventory(G, 5))[0]["qty"] == 2
    with pytest.raises(CodeError):
        code(s, code="EMPTY", credits=0)
    with pytest.raises(CodeError):
        code(s, code="ITEM")  # duplicate
    with pytest.raises(CodeError):
        code(s, code="no válido!")


# ---- quests ----


def test_period_keys():
    now = datetime(2026, 10, 25, 3, tzinfo=timezone.utc)
    assert PeriodKey("daily", now, -5) == "2026-10-24"
    assert PeriodKey("weekly", now, -5) == "2026-W43"
    assert PeriodKey("once", now, -5) == "once"


def quest(s, **kw):
    return run(s.quests.Create(G, {"name": "Q", "period": "daily", "objective": "work", "target": 3, "reward": 50, **kw}))


def test_quest_progress_and_claim_once():
    s = services()
    q = quest(s)
    run(s.quests.Track(G, 5, "work", 2, CONFIG))
    run(s.quests.Track(G, 5, "messages", 10, CONFIG))  # other objective: ignored
    with pytest.raises(QuestError):
        run(s.quests.Claim(G, 5, q["quest_id"], CONFIG))
    run(s.quests.Track(G, 5, "work", 1, CONFIG))
    assert run(s.quests.Status(G, 5, CONFIG))[0][1:] == (3, False)

    async def double_click():
        return await asyncio.gather(*(s.quests.Claim(G, 5, q["quest_id"], CONFIG) for _ in range(5)), return_exceptions=True)

    results = run(double_click())
    assert sum(not isinstance(r, Exception) for r in results) == 1
    assert run(s.economy.Balance(G, 5)) == 50


def test_paused_quests_dont_track():
    s = services()
    q = quest(s)
    run(s.quests.Update(G, q["quest_id"], {"enabled": False}))
    run(s.quests.Track(G, 5, "work", 5, CONFIG))
    assert run(s.quests.Status(G, 5, CONFIG)) == []


def test_quest_validation():
    s = services()
    with pytest.raises(QuestError):
        quest(s, target=0)
    with pytest.raises(QuestError):
        quest(s, reward=0)
