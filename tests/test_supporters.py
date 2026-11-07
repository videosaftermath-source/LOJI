import asyncio
from types import SimpleNamespace as N

import core.supporters as S
from tests.economy.fakes import DB


def custom(text):
    return N(type=N(name="custom"), name=text, state=None)


def test_vanity_detection():
    assert S.HasVanity(N(activities=[custom("únanse discord.gg/animetv")]), "Discord.gg/animetv")
    assert S.HasVanity(N(activities=[custom("entra a .gg/AnimeTV!")]), "discord.gg/animetv")
    assert S.HasVanity(N(activities=[custom("/animetv")]), "discord.gg/animetv")
    assert not S.HasVanity(N(activities=[custom("discord.gg/animetvfans")]), "discord.gg/animetv")
    assert not S.HasVanity(N(activities=[N(type=N(name="playing"), name="discord.gg/animetv", state=None)]), "discord.gg/animetv")
    assert not S.HasVanity(N(activities=[]), "discord.gg/animetv")


def test_tag_detection():
    assert S.HasTag(N(primary_guild=N(id=1, identity_enabled=True)), 1)
    assert not S.HasTag(N(primary_guild=N(id=1, identity_enabled=False)), 1)
    assert not S.HasTag(N(primary_guild=N(id=2, identity_enabled=True)), 1)
    assert not S.HasTag(N(primary_guild=None), 1)


def test_bonus_and_one_time_reward():
    S.SetActive(1, 5, {"multiplier": 1.1, "gacha_luck": 0.2})
    assert S.Bonus(1, 5) == (1.1, 0.2) and S.Bonus(1, 6) == (1.0, 0.0)
    S.SetActive(1, 5, None)
    assert S.Bonus(1, 5) == (1.0, 0.0)
    store = S.Supporters(DB())

    async def go():
        before, after = await store.Record(1, 5, True, False)
        assert not before.get("supporter") and after["supporter"]
        first, again = await store.ClaimReward(1, 5), await store.ClaimReward(1, 5)
        assert (first, again) == (True, False)
        assert await store.ClaimAnnouncement(1, 5) and not await store.ClaimAnnouncement(1, 5)

    asyncio.run(go())


def test_booster_and_supporter_bonus_stack():
    from core.economy.boost import EarningsMultiplier
    from core.economy.config import Merge
    from core.economy.constants import DEFAULT_CONFIG

    config = Merge(DEFAULT_CONFIG, {})
    member = N(id=9, guild=N(id=1), premium_since=object())
    S.SetActive(1, 9, {"multiplier": 1.1, "gacha_luck": 0.0})
    assert abs(EarningsMultiplier(member, config) - 1.3 * 1.1) < 1e-9
    S.SetActive(1, 9, None)
