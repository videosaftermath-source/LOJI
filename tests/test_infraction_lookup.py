import asyncio

from tests.economy.fakes import DB


def run(c):
    return asyncio.run(c)


def test_find_infraction_is_forgiving():
    from cogs.Modules.infractions import FindInfraction

    db = DB()
    run(db["infractions"].insert_one({"guild_id": 1, "random_string": "7J82EEV00B", "voided": True}))
    run(db["infractions"].insert_one({"guild_id": 2, "random_string": "ABCDEF1234"}))
    for typed in ("7J82EEV00B", " 7j82eev00b ", "#7J82EEV00B", "`7J82EEV00B`", "7J82EEVOOB", "7J82EEV0OB"):
        assert run(FindInfraction(db, 1, typed))["random_string"] == "7J82EEV00B", typed  # voided ones too
    assert run(FindInfraction(db, 1, "ABCDEF1234")) is None  # other server
    assert run(FindInfraction(db, 1, "")) is None
