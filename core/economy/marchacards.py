"""Pictures for La Larga Marcha: the table (hand, jokers, score) and the shop. LOJI red, CRT lines."""

import io
import textwrap

from PIL import Image, ImageDraw, ImageFilter

from core.economy import marcha as M
from core.economy.cards import Font, Icon

SIZE = (900, 560)
SHOP_SIZE = (900, 520)
BG_TOP, BG_BOTTOM = (34, 4, 8), (8, 1, 3)
RED, RED_GLOW = (214, 32, 44), (255, 60, 70)
TEXT, MUTED, GOLD = (240, 228, 222), (170, 140, 140), (246, 196, 72)
CARD_W, CARD_H, CARD_GAP = 92, 130, 12
CARD_FACE, CARD_RED, CARD_BLACK = (243, 236, 223), (179, 18, 27), (29, 29, 31)
CARDS_Y = 400
RAISE = 24
SCANLINE_EVERY = 3
JOKER_W, JOKER_H = 150, 92
RARITY_COLORS = {"common": (120, 140, 160), "uncommon": (90, 200, 120), "rare": (220, 70, 80), "planet": (90, 140, 230)}

BANNERS = {
    "ante_cleared": ("JEFE DERROTADO", (90, 220, 120)),
    "won": ("MARCHA COMPLETA", GOLD),
    "failed": ("LA MARCHA TERMINA", RED_GLOW),
    "cashed": ("RECOMPENSA COBRADA", (90, 220, 120)),
}


def Background(size) -> Image.Image:
    W, H = size
    Img = Image.new("RGB", size)
    D = ImageDraw.Draw(Img)
    for Y in range(H):
        T = Y / H
        D.line([(0, Y), (W, Y)], fill=tuple(int(BG_TOP[i] + (BG_BOTTOM[i] - BG_TOP[i]) * T) for i in range(3)))
    Img = Img.convert("RGBA")
    Lines = Image.new("RGBA", size, (0, 0, 0, 0))
    L = ImageDraw.Draw(Lines)
    for Y in range(0, H, SCANLINE_EVERY):
        L.line([(0, Y), (W, Y)], fill=(0, 0, 0, 70))
    return Image.alpha_composite(Img, Lines)


def GlowText(img: Image.Image, xy, text: str, font, fill, anchor="la"):
    Layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(Layer).text(xy, text, font=font, fill=fill + (255,), anchor=anchor)
    img.alpha_composite(Layer.filter(ImageFilter.GaussianBlur(6)))
    ImageDraw.Draw(img).text(xy, text, font=font, fill=fill, anchor=anchor)


def Card(card: str, selected: bool) -> Image.Image:
    Img = Image.new("RGBA", (CARD_W + 16, CARD_H + 16), (0, 0, 0, 0))
    D = ImageDraw.Draw(Img)
    Box = (8, 8, 8 + CARD_W, 8 + CARD_H)
    if selected:
        Glow = Image.new("RGBA", Img.size, (0, 0, 0, 0))
        ImageDraw.Draw(Glow).rounded_rectangle(Box, 12, fill=RED_GLOW + (255,))
        Img.alpha_composite(Glow.filter(ImageFilter.GaussianBlur(6)))
    D.rounded_rectangle(Box, 10, fill=CARD_FACE, outline=RED if selected else (60, 50, 50), width=3 if selected else 1)
    Color = CARD_RED if card[1] in "HD" else CARD_BLACK
    Rank = M.RANK_LABELS.get(card[0], card[0])
    Suit = M.SUIT_SYMBOLS[card[1]]
    D.text((Box[0] + 9, Box[1] + 6), Rank, font=Font(24), fill=Color)
    D.text((Box[0] + 10, Box[1] + 34), Suit, font=Font(18, bold=False), fill=Color)
    D.text(((Box[0] + Box[2]) / 2, (Box[1] + Box[3]) / 2 + 12), Suit, font=Font(52, bold=False), fill=Color, anchor="mm")
    D.text((Box[2] - 9, Box[3] - 6), Rank, font=Font(18), fill=Color, anchor="rd")
    return Img


def JokerChip(joker_id: str, lit: bool = False) -> Image.Image:
    """Small joker card for the table row."""
    Info = M.JokerInfo(joker_id)
    Img = Image.new("RGBA", (JOKER_W, JOKER_H), (0, 0, 0, 0))
    D = ImageDraw.Draw(Img)
    Border = GOLD if lit else RARITY_COLORS[Info["rarity"]]
    D.rounded_rectangle((0, 0, JOKER_W - 1, JOKER_H - 1), 10, fill=(28, 10, 14), outline=Border, width=3 if lit else 2)
    Img.alpha_composite(Icon(Info["emoji"], Info["name"], "common", 40), ((JOKER_W - 40) // 2, 8))
    D.text((JOKER_W / 2, 62), Info["name"], font=Font(13), fill=TEXT, anchor="mm")
    D.text((JOKER_W / 2, 80), ShortText(Info["text"], 24), font=Font(10, bold=False), fill=MUTED, anchor="mm")
    return Img


def ShortText(text: str, width: int) -> str:
    return text if len(text) <= width else text[: width - 1] + "…"


def Header(img: Image.Image, game: dict, title: str):
    W = img.size[0]
    D = ImageDraw.Draw(img)
    GlowText(img, (32, 22), title, Font(28), RED)
    D.text((W - 32, 26), f"◈ {game['money']}", font=Font(24), fill=GOLD, anchor="ra")
    D.text((W - 120, 30), f"ANTE {game['ante'] + 1}/{M.ANTES}", font=Font(18), fill=TEXT, anchor="ra")


def JokerRow(img: Image.Image, game: dict, y: int, lit: set[str] = frozenset()):
    W = img.size[0]
    D = ImageDraw.Draw(img)
    Total = M.JOKER_SLOTS * JOKER_W + (M.JOKER_SLOTS - 1) * 12
    X = (W - Total) // 2
    for i in range(M.JOKER_SLOTS):
        if i < len(game["jokers"]):
            img.alpha_composite(JokerChip(game["jokers"][i], game["jokers"][i] in lit), (X, y))
        else:
            D.rounded_rectangle((X, y, X + JOKER_W - 1, y + JOKER_H - 1), 10, outline=(70, 30, 36), width=2)
            D.text((X + JOKER_W / 2, y + JOKER_H / 2), "vacío", font=Font(13, bold=False), fill=(90, 50, 56), anchor="mm")
        X += JOKER_W + 12


def Save(img: Image.Image) -> bytes:
    Out = io.BytesIO()
    img.convert("RGB").save(Out, "PNG", optimize=True)
    return Out.getvalue()


def Table(game: dict, selected: list[str] | None = None, state: str | None = None) -> bytes:
    """The table: ante/blind, jokers, score bar, hands/discards, last play and the hand."""
    W, H = SIZE
    Img = Background(SIZE)
    D = ImageDraw.Draw(Img)
    Name = M.BLINDS[game["blind"]][0]
    Header(Img, game, f"LA LARGA MARCHA · {Name.upper()}")
    Shown = M.Score(selected, game) if selected else game.get("last")
    JokerRow(Img, game, 66, set((Shown or {}).get("triggered", [])))
    Target = M.Target(game["ante"], game["blind"])
    D.text((32, 178), "SEÑAL", font=Font(16), fill=MUTED)
    D.text((W - 32, 176), f"{game['score']:,} / {Target:,}".replace(",", "."), font=Font(20), fill=TEXT, anchor="ra")
    Bar = (32, 204, W - 32, 222)
    D.rounded_rectangle(Bar, 8, fill=(40, 10, 14))
    Fill = Bar[0] + (Bar[2] - Bar[0]) * min(1.0, game["score"] / Target)
    if Fill > Bar[0] + 8:
        D.rounded_rectangle((Bar[0], Bar[1], Fill, Bar[3]), 8, fill=RED)
    D.text((32, 238), f"MANOS {game['hands']}/{M.HANDS}", font=Font(18), fill=TEXT)
    D.text((200, 238), f"DESCARTES {game['discards']}/{M.DISCARDS}", font=Font(18), fill=TEXT)
    D.text((W - 32, 240), f"Premio al vencer al jefe: x{M.LADDER[game['ante']]:g}", font=Font(16, bold=False), fill=MUTED, anchor="ra")
    if Shown:
        Level = f" nv.{Shown['level']}" if Shown.get("level", 1) > 1 else ""
        Mult = f"{Shown['mult']:g}"
        Line = f"{'▸ ' if selected else ''}{Shown['label'].upper()}{Level}   {Shown['chips']} × {Mult} = {Shown['total']:,}".replace(",", ".")
        GlowText(Img, (W / 2, 312), Line, Font(26), TEXT if selected else RED_GLOW, anchor="mm")
    Picked = set(selected or [])
    Hand = game["hand"]
    Total = len(Hand) * CARD_W + (len(Hand) - 1) * CARD_GAP
    X = (W - Total) // 2
    for C in Hand:
        Img.alpha_composite(Card(C, C in Picked), (X - 8, CARDS_Y - (RAISE if C in Picked else 0) - 8))
        X += CARD_W + CARD_GAP
    State = state or game["state"]
    if State in BANNERS:
        Text, Color = BANNERS[State]
        Img.alpha_composite(Image.new("RGBA", SIZE, (0, 0, 0, 150)))
        GlowText(Img, (W / 2, H / 2 + 20), Text, Font(48), Color, anchor="mm")
    return Save(Img)


def OfferCard(offer: dict | None) -> Image.Image:
    W, H = 300, 250
    Img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    D = ImageDraw.Draw(Img)
    if offer is None:
        D.rounded_rectangle((0, 0, W - 1, H - 1), 14, outline=(70, 30, 36), width=2)
        D.text((W / 2, H / 2), "VENDIDO", font=Font(22), fill=(90, 50, 56), anchor="mm")
        return Img
    if offer["type"] == "joker":
        Info = M.JokerInfo(offer["id"])
        Emoji, Name, Kind, Color, Text = Info["emoji"], Info["name"], M.JOKER_RARITY_LABELS[Info["rarity"]], RARITY_COLORS[Info["rarity"]], Info["text"]
    else:
        Label, *_ , PlusChips, PlusMult = M.HANDS_TABLE[offer["hand"]]
        Emoji, Name, Kind, Color = "🛰️", f"Actualización: {Label}", "Mejora de jugada", RARITY_COLORS["planet"]
        Text = f"{Label} sube un nivel: +{PlusChips} fichas y +{PlusMult} multi"
    D.rounded_rectangle((0, 0, W - 1, H - 1), 14, fill=(28, 10, 14), outline=Color, width=3)
    Img.alpha_composite(Icon(Emoji, Name, "common", 64), ((W - 64) // 2, 14))
    D.text((W / 2, 98), Name, font=Font(18), fill=TEXT, anchor="mm")
    D.text((W / 2, 120), Kind, font=Font(13, bold=False), fill=Color, anchor="mm")
    for i, Line in enumerate(textwrap.wrap(Text, 30)[:3]):
        D.text((W / 2, 150 + i * 20), Line, font=Font(14, bold=False), fill=TEXT, anchor="mm")
    D.rounded_rectangle((W / 2 - 44, H - 44, W / 2 + 44, H - 14), 10, fill=(60, 44, 10))
    D.text((W / 2, H - 29), f"◈ {offer['price']}", font=Font(18), fill=GOLD, anchor="mm")
    return Img


def ShopPicture(game: dict) -> bytes:
    W, H = SHOP_SIZE
    Img = Background(SHOP_SIZE)
    D = ImageDraw.Draw(Img)
    Header(Img, game, "INTERCAMBIO DE DATOS")
    Earned = game.get("earned")
    if Earned:
        D.text((32, 64), f"Ganaste ◈{Earned['total']}: recompensa {Earned['reward']} · manos sobrantes {Earned['hands']} · intereses {Earned['interest']}",
               font=Font(15, bold=False), fill=MUTED)
    X = (W - 2 * 300 - 40) // 2
    for i, Offer in enumerate(game["shop"]):
        Img.alpha_composite(OfferCard(Offer), (X + i * 340, 96))
        D.text((X + i * 340 + 150, 360), f"[{i + 1}]", font=Font(16), fill=MUTED, anchor="mm")
    D.text((32, 382), "TUS COMODINES", font=Font(15), fill=MUTED)
    JokerRow(Img, game, 408)
    return Save(Img)
