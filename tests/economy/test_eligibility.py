import asyncio
from types import SimpleNamespace as N

import core.economy.config as cfg
import core.economy.service as svc
from tests.economy.fakes import DB


def test_only_users_over_min_balance_earn_and_randoms_get_no_account():
    fake = DB()
    svc.economy = svc.EconomyService(fake)
    cfg._shared = cfg.EconomyConfig(fake)
    from cogs.Modules.Economy.activity import EconomyActivity

    async def go():
        import core.bot.Module as M

        async def yes(*a):
            return True

        cog = EconomyActivity.__new__(EconomyActivity)
        from core.economy.activity import Guard, TTLCache

        cog.guard, cog.eligible, cog.enabled = Guard(), TTLCache(), TTLCache()
        import cogs.Modules.Economy.activity as mod

        mod.ModuleCheck = yes
        await cfg._shared.SetChannels(1, [100])
        await svc.economy.Add(1, 5, 300, "seed")

        def msg(uid, text):
            async def react(e):
                pass

            return N(guild=N(id=1), author=N(id=uid, bot=False), webhook_id=None, content=text, channel=N(id=100), add_reaction=react)

        await cog.on_message(msg(5, "hola a todos como estan"))
        await cog.on_message(msg(6, "hola a todos como estan"))
        rich = await svc.economy.Balance(1, 5)
        random_account = fake.db["eco_users"].find_one({"user_id": 6})
        return rich, random_account

    rich, random_account = asyncio.run(go())
    assert rich > 300
    assert random_account is None  # the random got no account and no pay
