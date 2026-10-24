"""Animated slot machine for /casino tragamonedas: spinning reels that stop one by one on the real result."""

import io
import math
import random

from PIL import Image, ImageDraw, ImageFilter

from core.economy.cards import Font, Icon
from core.economy.casino import SLOT_SYMBOLS

SIZE = (480, 392)
SYMBOL = 64  # symbol picture size
ROW = 72  # distance between symbols on a reel
REEL_W, REEL_H = 112, 3 * ROW
REEL_TOP = 66
REEL_GAP = 14
FRAME_MS = 60
STOPS = (16, 23, 30)  # frame where each reel stops
SPIN_SYMBOLS = (14, 20, 26)  # how many symbols each reel travels
END_FRAMES = 10  # result banner after the last reel stops
HOLD_MS = 1600  # last frame
BULBS = 18
BG_TOP, BG_BOTTOM = (40, 10, 52), (12, 4, 20)
GOLD, GOLD_DARK = (246, 196, 72), (150, 100, 20)
WIN, LOSE = (80, 220, 120), (200, 200, 210)

_symbols: dict[str, Image.Image] = {}


def Symbol(emoji: str) -> Image.Image:
    if emoji not in _symbols:
        _symbols[emoji] = Icon(emoji, emoji, "common", SYMBOL)
    return _symbols[emoji]


def EaseOutBack(t: float) -> float:
    """Decelerates and settles with a small bounce, like a real reel."""
    C = 1.4
    return 1 + (C + 1) * (t - 1) ** 3 + C * (t - 1) ** 2


def Strip(final: str, travel: int, rng: random.Random) -> list[str]:
    """Random symbols, with the result at index `travel` (where the reel stops)."""
    Names = [S for S, _ in SLOT_SYMBOLS]
    Weights = [W for _, W in SLOT_SYMBOLS]
    Strip_ = rng.choices(Names, Weights, k=travel + 3)
    Strip_[travel] = final
    return Strip_


def Background() -> Image.Image:
    W, H = SIZE
    Image_ = Image.new("RGB", SIZE)
    D = ImageDraw.Draw(Image_)
    for Y in range(H):
        T = Y / H
        D.line([(0, Y), (W, Y)], fill=tuple(int(BG_TOP[i] + (BG_BOTTOM[i] - BG_TOP[i]) * T) for i in range(3)))
    # Machine body
    D.rounded_rectangle((14, 14, W - 14, H - 14), 26, fill=(70, 16, 40), outline=GOLD, width=5)
    D.rounded_rectangle((26, 52, W - 26, REEL_TOP + REEL_H + 14), 16, fill=(20, 8, 24), outline=GOLD_DARK, width=3)
    D.text((W / 2, 33), "TRAGAMONEDAS", font=Font(24), fill=GOLD, anchor="mm")
    return Image_.convert("RGBA")


def ReelX(i: int) -> int:
    Total = 3 * REEL_W + 2 * REEL_GAP
    return (SIZE[0] - Total) // 2 + i * (REEL_W + REEL_GAP)


def DrawReel(strip: list[str], position: float, speed: float) -> Image.Image:
    """One reel window; `position` is the strip index shown on the payline (can be fractional)."""
    Reel = Image.new("RGBA", (REEL_W, REEL_H), (250, 246, 238, 255))
    Base = math.floor(position)
    Offset = position - Base
    for K in range(-2, 3):
        Index = Base + K
        if 0 <= Index < len(strip):
            Y = REEL_H / 2 + (K - Offset) * ROW - SYMBOL / 2
            Pic = Symbol(strip[Index])
            Reel.alpha_composite(Pic, ((REEL_W - SYMBOL) // 2, int(Y)))
    if speed > 0.25:
        Reel = Reel.filter(ImageFilter.GaussianBlur(min(4, speed * 3)))
    # Shade the top and bottom rows so the payline stands out.
    Shade = Image.new("RGBA", (REEL_W, REEL_H), (0, 0, 0, 0))
    S = ImageDraw.Draw(Shade)
    for Y in range(ROW):
        A = int(110 * (1 - Y / ROW))
        S.line([(0, Y), (REEL_W, Y)], fill=(20, 8, 24, A))
        S.line([(0, REEL_H - 1 - Y), (REEL_W, REEL_H - 1 - Y)], fill=(20, 8, 24, A))
    return Image.alpha_composite(Reel, Shade)


def Bulbs(draw: ImageDraw.ImageDraw, frame: int, color):
    W, H = SIZE
    Spots = [(34 + (W - 68) * i / (BULBS - 1), H - 30) for i in range(BULBS)]
    for i, (X, Y) in enumerate(Spots):
        On = (i + frame) % 3 == 0
        draw.ellipse((X - 5, Y - 5, X + 5, Y + 5), fill=color if On else (90, 40, 50))


def Banner(draw: ImageDraw.ImageDraw, text: str, color, scale: float):
    W = SIZE[0]
    Y = REEL_TOP + REEL_H + 50
    F = Font(max(10, int(26 * scale)))
    draw.text((W / 2 + 2, Y + 2), text, font=F, fill=(0, 0, 0), anchor="mm")
    draw.text((W / 2, Y), text, font=F, fill=color, anchor="mm")


def SlotsAnimation(reels: tuple[str, str, str], multiplier: float, seed: int | None = None) -> tuple[bytes, bytes]:
    """Returns (animated GIF, final PNG). `multiplier` is what the spin paid (0 = lost)."""
    Rng = random.Random(seed)
    Strips = [Strip(R, T, Rng) for R, T in zip(reels, SPIN_SYMBOLS)]
    Jackpot = multiplier >= 50
    Text = "¡JACKPOT!" if Jackpot else f"¡PREMIO x{multiplier:.2f}!" if multiplier > 0 else "SIN PREMIO"
    TextColor = GOLD if Jackpot else WIN if multiplier > 0 else LOSE
    Base = Background()
    Frames, Durations = [], []
    Total = STOPS[-1] + END_FRAMES
    for F in range(Total + 1):
        Frame = Base.copy()
        D = ImageDraw.Draw(Frame)
        for i in range(3):
            T = min(1.0, F / STOPS[i])
            Position = SPIN_SYMBOLS[i] * EaseOutBack(T) if T < 1 else SPIN_SYMBOLS[i]
            Before = SPIN_SYMBOLS[i] * EaseOutBack(max(0.0, (F - 1) / STOPS[i])) if F else 0
            Speed = abs(Position - Before) if T < 1 else 0
            Frame.alpha_composite(DrawReel(Strips[i], Position, Speed), (ReelX(i), REEL_TOP))
        Done = F >= STOPS[-1]
        Highlight = TextColor if Done and multiplier > 0 and (F // 2) % 2 == 0 else GOLD_DARK
        Mid = REEL_TOP + REEL_H / 2
        D.polygon([(20, Mid - 12), (34, Mid), (20, Mid + 12)], fill=Highlight)
        D.polygon([(SIZE[0] - 20, Mid - 12), (SIZE[0] - 34, Mid), (SIZE[0] - 20, Mid + 12)], fill=Highlight)
        if Done and multiplier > 0:
            D.rectangle((ReelX(0) - 4, Mid - ROW / 2, ReelX(2) + REEL_W + 4, Mid + ROW / 2), outline=Highlight, width=3)
        Bulbs(D, F, TextColor if Done else GOLD)
        if Done:
            Grow = min(1.0, (F - STOPS[-1] + 1) / 4)
            Banner(D, Text, TextColor, 0.6 + 0.4 * Grow)
        Frames.append(Frame.convert("RGB"))
        Durations.append(HOLD_MS if F == Total else FRAME_MS)
    # One shared palette (taken from the last frame plus every symbol) so colors don't flicker.
    Sample = Image.new("RGB", (SIZE[0], SIZE[1] + SYMBOL))
    Sample.paste(Frames[-1], (0, 0))
    for i, (S, _) in enumerate(SLOT_SYMBOLS):
        Sample.paste(Symbol(S).convert("RGB"), (i * SYMBOL, SIZE[1]))
    Palette = Sample.quantize(colors=200, method=Image.Quantize.MEDIANCUT)
    Indexed = [Frame.quantize(palette=Palette, dither=Image.Dither.NONE) for Frame in Frames]
    Gif = io.BytesIO()
    Indexed[0].save(Gif, "GIF", save_all=True, append_images=Indexed[1:], duration=Durations, loop=0, optimize=False, disposal=1)
    Png = io.BytesIO()
    Frames[-1].save(Png, "PNG", optimize=True)
    return Gif.getvalue(), Png.getvalue()
