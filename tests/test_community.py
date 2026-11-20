import asyncio
from types import SimpleNamespace as N

import discord
import pytest

from core.community import (
    MAX_BOARD_QUESTS, ButtonUrl, ChannelId, CloseStep, Color, Community, DropLinesWithEmpty, Fill, OVERFLOW, ParseButtons,
    Title, Traffic, ValidColor,
)
from core.economy.config import Merge
from core.economy.constants import DEFAULT_CONFIG
from core.economy.quests import QuestError
from core.economy.registry import Build
from core.economy.service import EconomyService
from tests.economy.fakes import DB

G = 1
CONFIG = Merge(DEFAULT_CONFIG, {})


def run(coro):
    return asyncio.run(coro)


# ---------------- texts ----------------


def test_fill_and_drop_empty_lines():
    Values = {"rol": "", "cosa": "nuestro **TAG**"}
    Text = "🌴 Se te otorgó el rol {rol}\nℹ️ Te has equipado {cosa}!"
    assert Fill(DropLinesWithEmpty(Text, Values), Values) == "ℹ️ Te has equipado nuestro **TAG**!"
    Values["rol"] = "<@&5>"
    assert "<@&5>" in Fill(DropLinesWithEmpty(Text, Values), Values)


def test_buttons_parse_and_urls():
    Buttons = ParseButtons("Reclamar | 🪙 | <#123456789012345678>\nWeb | | https://example.com\n\nSin destino | 🎟️ |\nA|b|c\nD|e|f")
    assert len(Buttons) == 3  # at most 3
    assert Buttons[0] == {"label": "Reclamar", "emoji": "🪙", "target": "<#123456789012345678>"}
    assert ButtonUrl(Buttons[0]["target"], 9) == "https://discord.com/channels/9/123456789012345678"
    assert ButtonUrl("https://example.com", 9) == "https://example.com"
    assert ButtonUrl("", 9) is None and ButtonUrl("tickets", 9) is None
    assert ChannelId("123456789012345678") == 123456789012345678


def test_colors_and_titles():
    assert Color("#57F287") == 0x57F287 and Color("nope", 1) == 1
    assert ValidColor("57f287") and not ValidColor("#12")
    assert Title("🟢 Chat abierto\nBienvenidos") == ("🟢 Chat abierto", "Bienvenidos")


def test_config_sections_merge_defaults():
    Store = Community(DB())
    run(Store.Set(G, "overflow", {"main": 10, "extra": 11}))
    Config = run(Store.Get(G))
    assert Config["overflow"]["main"] == 10 and Config["overflow"]["open_messages"] == OVERFLOW["open_messages"]
    assert Config["welcome"]["title_vanity"]
    run(Store.Reset(G, "overflow", ["main"]))
    assert run(Store.Get(G))["overflow"]["main"] is None


# ---------------- overflow ----------------


def test_traffic_needs_messages_and_people():
    T, S = Traffic(), {**OVERFLOW, "open_messages": 10, "open_seconds": 60, "open_authors": 3}
    for I in range(10):
        T.Add(1, 100, I, 60)  # one person spamming
    assert not T.Busy(1, 10, S)
    for I in range(10):
        T.Add(1, 100 + I % 3, 20 + I, 60)
    assert T.Busy(1, 30, S)
    assert not T.Busy(1, 200, S)  # old messages don't count


def test_close_steps():
    S = {**OVERFLOW, "close_below": 5, "min_open_minutes": 15, "warn_seconds": 60}
    Opened = 1
    assert CloseStep(S, 10 * 60, 0, Opened, None, 0) is None  # too soon after opening
    assert CloseStep(S, 20 * 60, 8, Opened, None, 0) is None  # still lively
    assert CloseStep(S, 20 * 60, 2, Opened, None, 0) == "warn"
    assert CloseStep(S, 20 * 60 + 30, 2, Opened, 20 * 60, 0) is None  # warned, waiting
    assert CloseStep(S, 20 * 60 + 61, 2, Opened, 20 * 60, 1) == "close"
    assert CloseStep(S, 20 * 60 + 30, 4, Opened, 20 * 60, 3) == "cancel"  # people came back


# ---------------- condition quests ----------------


def services():
    s = Build(EconomyService(DB()))
    run(s.Setup())
    return s


def test_tag_quest_once_per_account():
    s = services()
    Q = run(s.quests.Create(G, {"name": "Llevar el TAG", "period": "once", "objective": "supporter", "target": 1, "reward": 2000}))
    Status = run(s.quests.Status(G, 5, CONFIG, {"supporter": False}))
    assert Status[0][1] == 0 and not Status[0][2]
    with pytest.raises(QuestError):
        run(s.quests.Claim(G, 5, Q["quest_id"], CONFIG, {"supporter": False}))
    run(s.quests.Claim(G, 5, Q["quest_id"], CONFIG, {"supporter": True}))
    assert run(s.economy.Balance(G, 5)) == 2000
    with pytest.raises(QuestError):  # taking it off and on again doesn't pay twice
        run(s.quests.Claim(G, 5, Q["quest_id"], CONFIG, {"supporter": True}))
    assert run(s.economy.Balance(G, 5)) == 2000
    assert run(s.quests.Status(G, 5, CONFIG, {"supporter": True}))[0][2] is True


def test_voice_minutes_quest_counts():
    s = services()
    Q = run(s.quests.Create(G, {"name": "15 min en voz", "period": "daily", "objective": "voice", "target": 15, "reward": 1200}))
    for _ in range(3):
        run(s.quests.Track(G, 5, "voice", 5, CONFIG))
    run(s.quests.Claim(G, 5, Q["quest_id"], CONFIG))
    assert run(s.economy.Balance(G, 5)) == 1200


# ---------------- rendering ----------------


def Count(components) -> int:
    Total = 0
    for C in components:
        Total += 1
        Total += Count(C.get("components", []))
        if C.get("accessory"):
            Total += 1
    return Total


def test_welcome_card_renders():
    from cogs.Modules.Community.community import WelcomeView
    from core.community import WELCOME

    Guild = N(id=9, name="NWN", icon=None)
    Member = N(guild=Guild, mention="<@5>", display_name="duu", display_avatar=N(url="https://cdn/a.png"))
    Values = {"user": "<@5>", "nombre": "duu", "server": "NWN", "cosa": "nuestro **TAG**", "rol": "", "vanity": "`.gg/nwn`",
              "tareas": "<#123456789012345678>", "tareas_link": "https://discord.com/channels/9/123456789012345678"}
    Data = WelcomeView(Member, {**WELCOME, "buttons": WELCOME["buttons"] + " <#123456789012345679>"}, Values).to_components()
    Text = str(Data)
    assert "Gracias por apoyarnos <@5>" in Text and "Se te otorgó el rol" not in Text  # no role: line dropped
    assert "Reclamar monedas" in Text and "Contactar con staff" in Text
    assert Count(Data) <= 40


def test_board_fits_discord_limit():
    from cogs.Modules.Community.community import ClaimButton, ProgressButton
    from discord import ui

    # The worst case BoardView builds: banner, header, MAX quests with dividers, footer, progress button.
    Box = ui.Container()
    Box.add_item(ui.MediaGallery(discord.MediaGalleryItem("https://x/y.png")))
    Box.add_item(ui.TextDisplay("h"))
    for I in range(MAX_BOARD_QUESTS):
        Box.add_item(ui.Section(ui.TextDisplay("q"), accessory=ClaimButton(f"Q{I}")))
        if I < MAX_BOARD_QUESTS - 1:
            Box.add_item(ui.Separator())
    Box.add_item(ui.TextDisplay("f"))
    Box.add_item(ui.ActionRow(ProgressButton()))
    View = ui.LayoutView()
    View.add_item(Box)
    assert View.total_children_count <= 40 if hasattr(View, "total_children_count") else Count(View.to_components()) <= 40


def test_one_card_per_reason():
    from core.community import WELCOME, Variant

    Tag, Vanity = Variant(WELCOME, True), Variant(WELCOME, False)
    assert "TAG" in Tag["intro"] and "vanity" in Vanity["intro"]
    assert Tag["benefits"] == Vanity["benefits"]  # same benefits either way
    assert Vanity["note"] == WELCOME["note_vanity"]
