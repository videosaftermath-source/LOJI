import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as N

import core.economy.config as cfg
import core.economy.service as svc
from tests.economy.fakes import DB


def setup_cog(fake):
    svc.economy = svc.EconomyService(fake)
    cfg._shared = cfg.EconomyConfig(fake)
    import core.economy.registry as reg

    reg._services = None
    import cogs.Modules.Economy.activity as mod
    from core.economy.activity import Guard, TTLCache

    async def yes(*a):
        return True

    mod.ModuleCheck = yes
    cog = mod.EconomyActivity.__new__(mod.EconomyActivity)
    cog.guard, cog.enabled = Guard(), TTLCache()
    cog.client = N(dispatch=lambda *a: None)
    return cog


def member(uid, dms):
    async def send(text):
        dms.append((uid, text))

    return N(id=uid, bot=False, send=send, guild=N(id=1, name="ESS"))


def test_everyone_earns_and_gets_the_welcome_dm_once():
    fake = DB()
    cog = setup_cog(fake)
    dms = []

    def msg(author, text):
        async def react(e):
            pass

        author.guild = N(id=1, name="ESS")
        return N(guild=author.guild, author=author, webhook_id=None, content=text, channel=N(id=100), add_reaction=react)

    async def go():
        await cfg._shared.SetChannels(1, [100])
        await cfg._shared.Set(1, "activity.cooldown", "5")
        new = member(6, dms)
        await cog.on_message(msg(new, "hola a todos, ¿cómo están?"))  # no minimum balance any more
        first = await svc.economy.Balance(1, 6)
        await svc.economy.Add(1, 6, 200, "seed")  # now over 150
        cog.guard = __import__("core.economy.activity", fromlist=["Guard"]).Guard()
        await cog.on_message(msg(new, "otro mensaje distinto para el chat"))
        cog.guard = __import__("core.economy.activity", fromlist=["Guard"]).Guard()
        await cog.on_message(msg(new, "y uno más, bien diferente al resto"))
        return first

    first = asyncio.run(go())
    assert first > 0
    assert len([d for d in dms if "sin usar" in d[1]]) == 1  # welcome DM only once


def test_streak_reminder_after_24_hours_once():
    fake = DB()
    cog = setup_cog(fake)
    dms = []
    now = datetime(2026, 11, 6, 20, 0, tzinfo=timezone.utc)
    yesterday = (now - timedelta(days=1)).date().isoformat()

    async def go():
        await cfg._shared.SetChannels(1, [100])
        await cfg._shared.Set(1, "activity.utc_offset", "0")
        await svc.economy.Add(1, 7, 10, "seed")
        await svc.economy.Add(1, 8, 10, "seed")
        await fake["eco_users"].update_one({"user_id": 7}, {"$set": {"activity": {"streak": 3, "qualified_day": yesterday, "qualified_at": now - timedelta(hours=25)}}})
        await fake["eco_users"].update_one({"user_id": 8}, {"$set": {"activity": {"streak": 2, "qualified_day": yesterday, "qualified_at": now - timedelta(hours=10)}}})
        guild = N(id=1, name="ESS", get_member=lambda uid: member(uid, dms))
        first = await cog.WarnStreaks(guild, now)
        again = await cog.WarnStreaks(guild, now)
        return first, again

    first, again = asyncio.run(go())
    assert (first, again) == (1, 0)  # only the one past 24 h, and only once
    assert dms[0][0] == 7 and "racha de chat de 3 días" in dms[0][1]
