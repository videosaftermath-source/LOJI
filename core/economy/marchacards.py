"""Table picture for La Larga Marcha (LOJI red, CRT scanlines)."""

import io

from PIL import Image, ImageDraw, ImageFilter

from core.economy.cards import Font
from core.economy.marcha import DISCARDS, HANDS, LADDER, RANK_LABELS, SUIT_SYMBOLS, TARGETS, Score

SIZE = (900, 440)
BG_TOP, BG_BOTTOM = (34, 4, 8), (8, 1, 3)
RED, RED_DARK, RED_GLOW = (214, 32, 44), (110, 12, 20), (255, 60, 70)
TEXT, MUTED = (240, 228, 222), (170, 140, 140)
CARD_W, CARD_H, CARD_GAP = 92, 130, 12
CARD_FACE, CARD_RED, CARD_BLACK = (243, 236, 223), (179, 18, 27), (29, 29, 31)
CARDS_Y = 270
RAISE = 24
SCANLINE_EVERY = 3

BANNERS = {
    "cleared": ("ETAPA SUPERADA", (90, 220, 120)),
    "won": ("MARCHA COMPLETA", (246, 196, 72)),
    "failed": ("LA MARCHA TERMINA", RED_GLOW),
    "cashed": ("RECOMPENSA COBRADA", (90, 220, 120)),
}


def Background() -> Image.Image:
    W, H = SIZE
    Img = Image.new("RGB", SIZE)
    D = ImageDraw.Draw(Img)
    for Y in range(H):
        T = Y / H
        D.line([(0, Y), (W, Y)], fill=tuple(int(BG_TOP[i] + (BG_BOTTOM[i] - BG_TOP[i]) * T) for i in range(3)))
    Img = Img.convert("RGBA")
    Lines = Image.new("RGBA", SIZE, (0, 0, 0, 0))
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
    Rank = RANK_LABELS.get(card[0], card[0])
    Suit = SUIT_SYMBOLS[card[1]]
    D.text((Box[0] + 9, Box[1] + 6), Rank, font=Font(24), fill=Color)
    D.text((Box[0] + 10, Box[1] + 34), Suit, font=Font(18, bold=False), fill=Color)
    D.text(((Box[0] + Box[2]) / 2, (Box[1] + Box[3]) / 2 + 12), Suit, font=Font(52, bold=False), fill=Color, anchor="mm")
    D.text((Box[2] - 9, Box[3] - 6), Rank, font=Font(18), fill=Color, anchor="rd")
    return Img


def Table(game: dict, selected: list[str] | None = None, state: str | None = None) -> bytes:
    """The table: stage, score bar, hands/discards, last play and the hand (selected cards raised)."""
    W, H = SIZE
    Img = Background()
    D = ImageDraw.Draw(Img)
    Stage, Target = game["stage"], TARGETS[game["stage"]]
    GlowText(Img, (32, 26), "LA LARGA MARCHA", Font(30), RED)
    D.text((W - 32, 30), f"ETAPA {Stage + 1} / {len(TARGETS)}", font=Font(22), fill=TEXT, anchor="ra")
    # Score bar
    D.text((32, 82), "SEÑAL", font=Font(16), fill=MUTED)
    D.text((W - 32, 80), f"{game['score']:,} / {Target:,}".replace(",", "."), font=Font(20), fill=TEXT, anchor="ra")
    Bar = (32, 108, W - 32, 128)
    D.rounded_rectangle(Bar, 8, fill=(40, 10, 14))
    Fill = Bar[0] + (Bar[2] - Bar[0]) * min(1.0, game["score"] / Target)
    if Fill > Bar[0] + 8:
        D.rounded_rectangle((Bar[0], Bar[1], Fill, Bar[3]), 8, fill=RED)
    # Hands, discards and the prize ladder
    D.text((32, 146), f"MANOS {game['hands']}/{HANDS}", font=Font(18), fill=TEXT)
    D.text((200, 146), f"DESCARTES {game['discards']}/{DISCARDS}", font=Font(18), fill=TEXT)
    Ladder = "   ".join(f"E{i + 1} x{M:g}" for i, M in enumerate(LADDER))
    D.text((W - 32, 148), Ladder, font=Font(16, bold=False), fill=MUTED, anchor="ra")
    # Last play / selection preview
    Shown, Color = (Score(selected), TEXT) if selected else (game.get("last"), RED_GLOW)
    if Shown:
        Prefix = "▸ " if selected else ""
        Line = f"{Prefix}{Shown['label'].upper()}   {Shown['chips']} × {Shown['mult']} = {Shown['total']:,}".replace(",", ".")
        GlowText(Img, (W / 2, 205), Line, Font(26), Color, anchor="mm")
    # Hand
    Hand = game["hand"]
    Picked = set(selected or [])
    Total = len(Hand) * CARD_W + (len(Hand) - 1) * CARD_GAP
    X = (W - Total) // 2
    for C in Hand:
        Y = CARDS_Y - (RAISE if C in Picked else 0)
        Img.alpha_composite(Card(C, C in Picked), (X - 8, Y - 8))
        X += CARD_W + CARD_GAP
    State = state or game["state"]
    if State in BANNERS:
        Text, Color = BANNERS[State]
        Shade = Image.new("RGBA", SIZE, (0, 0, 0, 150))
        Img.alpha_composite(Shade)
        GlowText(Img, (W / 2, H / 2 + 20), Text, Font(48), Color, anchor="mm")
    Out = io.BytesIO()
    Img.convert("RGB").save(Out, "PNG", optimize=True)
    return Out.getvalue()
