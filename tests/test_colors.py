import asyncio
from types import SimpleNamespace as N

import discord

from core.community import COLORS, ColorKey

GRADIENTS = [
    ("ᗜ· Neón nocturno ·", 0x3EE6FF, 0x5B4BFF), ("Plasma", 0x4A5BFF, 0xFF1FF0), ("Atardecer", 0xFF5F8F, 0xFF9A5C),
    ("Flamingo", 0xFF3DA5, 0xFF8FB1), ("Synthwave", 0xFF00C8, 0xFFE600), ("Ácido", 0x00FF85, 0xD4FF00),
    ("Aurora", 0x00FFA3, 0x7A2CFF), ("Carmesí", 0xFF1E1E, 0xFF0066), ("Vice City", 0xFF2BD6, 0x00E5FF),
    ("Orquídea", 0xFFB199, 0x8F5BFF), ("Oro Rosa", 0xF7A07A, 0xFFE3CF), ("Champagne", 0xE8B04A, 0xFFF6D6),
    ("Black Ice", 0xE9FCFF, 0x20B2C2), ("Iron n Blood", 0xE6ECF2, 0xE5002B),
]


def Roles():
    return [
        N(id=900000000000000000 + I, name=Name, colour=discord.Colour(A), secondary_colour=discord.Colour(B), mention=f"<@&{I}>")
        for I, (Name, A, B) in enumerate(GRADIENTS)
    ]


def test_colors_of_a_role():
    from cogs.Modules.Community.colors import Colors

    assert Colors(N(colour=discord.Colour(0x123456), secondary_colour=discord.Colour(0xABCDEF))) == (0x123456, 0xABCDEF)
    assert Colors(N(colour=discord.Colour(0x123456), secondary_colour=None)) == (0x123456, 0x123456)  # not a gradient
    assert ColorKey(0x123456, None) == "123456-123456"


def test_panel_has_numbered_buttons_and_fits():
    from cogs.Modules.Community.colors import PanelView

    Guild = N(name="El Sótano Social", premium_subscriber_role=None)
    R = Roles()
    Data = PanelView(Guild, COLORS, R, {}).to_components()
    Text = str(Data)
    assert "Colección · 14 degradados" in Text and "attachment://muestrario.png" in Text and "El Sótano Social" in Text
    Buttons = [B for C in Data[0]["components"] if C["type"] == 1 for B in C["components"]]
    assert [B.get("label") for B in Buttons][:3] == ["01", "02", "03"] and len(Buttons) == 15
    assert Buttons[-1]["custom_id"] == "bcolor:off" and all(B["style"] == 2 for B in Buttons)

    def Count(items):
        return sum(1 + Count(I.get("components", [])) + (1 if I.get("accessory") else 0) for I in items)

    Twenty = [N(**{**R[0].__dict__, "id": R[0].id + 100 + I}) for I in range(20)]
    assert Count(PanelView(Guild, COLORS, Twenty, {}).to_components()) <= 40  # the maximum still fits


def test_swatch_draws_every_color():
    from PIL import Image
    import io
    from core.gradient_art import Swatch
    from core.staff.medals import CleanName

    Png = Swatch([(CleanName(Name), A, B) for Name, A, B in GRADIENTS])
    Img = Image.open(io.BytesIO(Png))
    assert Img.size[0] > 2000 and Img.size[1] > 1000
    assert CleanName("ᗜ· Neón nocturno ·") == "Neón nocturno"


def test_gradients_leave_with_the_boost(monkeypatch):
    import cogs.Modules.Community.icons as icons
    from core.community import Community
    from tests.economy.fakes import DB

    D = DB()
    Store = Community(D)
    monkeypatch.setattr(icons, "Db", lambda: D)
    monkeypatch.setattr(icons, "Store", lambda: Store)
    asyncio.run(Store.Set(9, "colors", {"roles": [111111111111111111, 222222222222222222]}))
    assert asyncio.run(icons.BoosterRoles(9)) == {111111111111111111, 222222222222222222}
