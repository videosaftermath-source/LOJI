import json
from types import SimpleNamespace as N

import pytest

from core.community import BoostChanges, FillJson, IconSwap, ParseCardJson


def test_one_icon_at_a_time():
    Icons = {10, 11, 12}
    assert IconSwap({1}, Icons, 10) == ({10}, set(), "added")
    assert IconSwap({1, 10}, Icons, 11) == ({11}, {10}, "swapped")  # from another panel too: same set
    assert IconSwap({1, 11}, Icons, 11) == (set(), {11}, "removed")  # clicking the one you wear takes it off


def test_boost_changes():
    assert BoostChanges({1, 2, 3}, {2, 3, 4}) == ({4}, {1})


def test_json_card_validation():
    Ok = {"components": [{"type": 17, "components": [
        {"type": 9, "components": [{"type": 10, "content": "{user} acaba de boostear {server}!"}],
         "accessory": {"type": 11, "media": {"url": "https://x/a.png"}}},
        {"type": 14},
        {"type": 1, "components": [{"type": 2, "style": 5, "label": "Roles", "url": "https://discord.com/channels/1/2"}]},
    ]}]}
    Parsed = ParseCardJson(json.dumps(Ok))
    Filled = FillJson(Parsed, {"user": "<@5>", "server": "Sótano"})
    assert Filled[0]["components"][0]["components"][0]["content"] == "<@5> acaba de boostear Sótano!"
    assert ParseCardJson(json.dumps(Ok["components"]))  # a bare list works too
    with pytest.raises(ValueError, match="JSON válido"):
        ParseCardJson("{nope")
    with pytest.raises(ValueError, match="enlace"):
        ParseCardJson(json.dumps({"components": [{"type": 1, "components": [{"type": 2, "style": 1, "custom_id": "x"}]}]}))
    with pytest.raises(ValueError, match="no permitido"):
        ParseCardJson(json.dumps({"components": [{"type": 3, "custom_id": "menu"}]}))
    with pytest.raises(ValueError, match="content"):
        ParseCardJson(json.dumps({"content": "hola", "components": [{"type": 10, "content": "x"}]}))
    with pytest.raises(ValueError, match="40"):
        ParseCardJson(json.dumps({"components": [{"type": 10, "content": "x"}] * 41}))


def test_booster_detection_and_emojis():
    from cogs.Modules.Community.icons import CheckEmoji, IsBooster

    Role = N(id=99)
    Guild = N(premium_subscriber_role=Role)
    assert IsBooster(N(guild=Guild, premium_since=None, roles=[Role]))
    assert IsBooster(N(guild=Guild, premium_since=object(), roles=[]))
    assert not IsBooster(N(guild=Guild, premium_since=None, roles=[]))
    Client = N(get_emoji=lambda i: object() if i == 1573482755088711700 else None)
    assert CheckEmoji(Client, "<:ESS_moneda:1573482755088711700>")[1] is None
    assert "LOJI no está" in CheckEmoji(Client, "<:otro:123456789012345678>")[1]
    assert CheckEmoji(Client, "🌟")[1] is None
    assert CheckEmoji(Client, "hola")[1]


def test_icon_panel_renders_within_limits():
    from cogs.Modules.Community.icons import PanelView

    Guild = N(name="Sótano Social", premium_subscriber_role=N(mention="<@&99>"))
    Panel = {"panel_id": "A", "name": "x", "banner": "https://x/b.png",
             "items": [{"role": 123456789012345600 + I, "emoji": "🌟"} for I in range(5)]}
    Data = PanelView(Guild, Panel, 1, 4, "### Iconos · {n}/{total}").to_components()
    Text = str(Data)
    assert "Iconos · 1/4" in Text and "<@&123456789012345604>" in Text and "Solo <@&99> puede elegirlos" in Text
    Row = Data[0]["components"][-1]
    assert Row["type"] == 1 and len(Row["components"]) == 5
    assert all(B["style"] == 2 and "label" not in B for B in Row["components"])  # neutral, emoji only


def test_hourly_check_learns_first_then_dms_once(monkeypatch):
    import asyncio
    import cogs.Modules.Community.icons as icons
    from core.community import Community
    from tests.economy.fakes import DB

    D = DB()
    Store = Community(D)
    monkeypatch.setattr(icons, "Db", lambda: D)
    monkeypatch.setattr(icons, "Store", lambda: Store)
    Sent = []

    def Member(id, boosting):
        async def send(text):
            Sent.append(id)
        return N(id=id, bot=False, premium_since=object() if boosting else None, roles=[], send=send, mention=f"<@{id}>")

    A, B = Member(1, True), Member(2, True)
    Guild = N(id=9, name="S", chunked=True, members=[A, B], premium_subscriber_role=None,
              get_member=lambda i: {1: A, 2: B}.get(i), get_channel=lambda i: None, get_role=lambda i: None)
    A.guild = B.guild = Guild
    Cog = icons.BoosterIcons.__new__(icons.BoosterIcons)
    Cog.locks = {}

    async def Missed(member):
        Sent.append(("card", member.id))
    Cog.Missed = Missed
    asyncio.run(Cog.CheckGuild(Guild))
    assert Sent == []  # first time: learns quietly
    B.premium_since = None  # B stopped while LOJI was offline
    C = Member(3, True)  # C boosted while LOJI was offline
    C.guild = Guild
    Guild.members.append(C)
    Guild.get_member = lambda i: {1: A, 2: B, 3: C}.get(i)
    asyncio.run(Cog.CheckGuild(Guild))
    assert Sent == [2, ("card", 3)]
    asyncio.run(Cog.Lost(Guild, 2))  # the live event arriving late doesn't DM again
    asyncio.run(Cog.CheckGuild(Guild))
    assert Sent == [2, ("card", 3)]
