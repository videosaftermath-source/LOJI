"""
Gacha visuals drawn with Pillow (no external services).

- Pull animations: a shooting star whose color shows the best rarity of the pull
  (blue / purple / gold), ending in a burst. Generated once and cached; drop your own
  blue.gif / purple.gif / gold.gif in assets/gacha/ to replace them.
- Result cards: one big card for x1, a 5x2 grid for x10.

All functions here are CPU-bound and synchronous: call them with asyncio.to_thread.
"""

import io
import math
import os
import random
import re
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FONTS = os.path.join(ROOT, "assets", "fonts")
GIF_DIR = os.path.join(ROOT, "assets", "gacha")
EMOJI_FONT = os.path.join(FONTS, "NotoColorEmoji.ttf")
EMOJI_NATIVE_SIZE = 109  # the only size the color emoji font renders at
CUSTOM_EMOJI = re.compile(r"<a?:\w+:(\d+)>")

# Animation
GIF_SIZE = (480, 270)
TRAVEL_FRAMES = 20
BURST_FRAMES = 18
FRAME_MS = 50
LAST_FRAME_MS = 700
GIF_COLORS = 160

TIERS = {
    # glow color, core color, how big the effects are, rays
    "blue": {"glow": (80, 160, 255), "core": (225, 242, 255), "scale": 1.0, "rays": 8},
    "purple": {"glow": (180, 100, 255), "core": (245, 228, 255), "scale": 1.25, "rays": 12},
    "gold": {"glow": (255, 196, 64), "core": (255, 248, 220), "scale": 1.6, "rays": 18},
}
RARITY_TIER = {"common": "blue", "rare": "blue", "epic": "purple", "legendary": "gold"}
RARITY_ORDER = ["common", "rare", "epic", "legendary"]

# Card colors per rarity: (main, light, dark)
PALETTE = {
    "common": ((150, 165, 180), (205, 215, 225), (44, 52, 64)),
    "rare": ((70, 150, 235), (160, 205, 255), (20, 40, 80)),
    "epic": ((165, 95, 230), (215, 175, 255), (45, 22, 78)),
    "legendary": ((245, 190, 60), (255, 230, 150), (85, 52, 12)),
}
STAR_COUNT = {"common": 1, "rare": 2, "epic": 3, "legendary": 4}
BG_TOP = (10, 12, 32)
BG_BOTTOM = (28, 32, 72)


# ---------------- helpers ----------------


@lru_cache(maxsize=32)
def Font(size: int, bold: bool = True) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(os.path.join(FONTS, "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"), size)


def Lerp(a, b, t: float):
    return tuple(int(x + (y - x) * t) for x, y in zip(a, b))


def Gradient(size, top, bottom) -> Image.Image:
    W, H = size
    Column = Image.new("RGB", (1, H))
    for y in range(H):
        Column.putpixel((0, y), Lerp(top, bottom, y / max(1, H - 1)))
    return Column.resize((W, H))


def Radial(size, center, radius, inner, outer) -> Image.Image:
    """Radial gradient (inner color at `center`, outer beyond `radius`)."""
    W, H = size
    Small = (max(1, W // 4), max(1, H // 4))
    Image_ = Image.new("RGB", Small)
    Cx, Cy, R = center[0] / 4, center[1] / 4, radius / 4
    Pixels = Image_.load()
    for y in range(Small[1]):
        for x in range(Small[0]):
            T = min(1.0, math.hypot(x - Cx, y - Cy) / R)
            Pixels[x, y] = Lerp(inner, outer, T**1.4)
    return Image_.resize((W, H), Image.BICUBIC)


def Glow(layer: Image.Image, radius: float) -> Image.Image:
    return layer.filter(ImageFilter.GaussianBlur(radius))


def StarShape(cx, cy, outer, inner=None, points=5, rotation=-math.pi / 2):
    inner = inner or outer * 0.45
    Shape = []
    for i in range(points * 2):
        R = outer if i % 2 == 0 else inner
        A = rotation + i * math.pi / points
        Shape.append((cx + R * math.cos(A), cy + R * math.sin(A)))
    return Shape


def DrawStars(draw: ImageDraw.ImageDraw, x, y, count, size, color, gap=None):
    gap = gap or size * 2.3
    for i in range(count):
        draw.polygon(StarShape(x + size + i * gap, y + size, size), fill=color)


def Wrap(text: str, font, width: int, lines: int = 2) -> list[str]:
    Words, Out, Line = text.split(), [], ""
    for Word in Words:
        Test = f"{Line} {Word}".strip()
        if font.getlength(Test) <= width:
            Line = Test
        else:
            if Line:
                Out.append(Line)
            Line = Word
    if Line:
        Out.append(Line)
    if len(Out) > lines:
        Out = Out[:lines]
        while Out[-1] and font.getlength(Out[-1] + "…") > width:
            Out[-1] = Out[-1][:-1]
        Out[-1] += "…"
    return Out


def FitFont(text: str, width: int, start: int, minimum: int, lines: int = 2):
    for Size in range(start, minimum - 1, -2):
        F = Font(Size)
        if len(Wrap(text, F, width, lines + 1)) <= lines:
            return F
    return Font(minimum)


# ---------------- emoji ----------------


@lru_cache(maxsize=512)
def UnicodeEmoji(emoji: str) -> Image.Image | None:
    """Renders a unicode emoji with the bundled color font (cropped, transparent)."""
    try:
        F = ImageFont.truetype(EMOJI_FONT, EMOJI_NATIVE_SIZE)
    except OSError:
        return None
    Canvas = Image.new("RGBA", (EMOJI_NATIVE_SIZE * 2, EMOJI_NATIVE_SIZE * 2), (0, 0, 0, 0))
    ImageDraw.Draw(Canvas).text((EMOJI_NATIVE_SIZE // 4, EMOJI_NATIVE_SIZE // 4), emoji, font=F, embedded_color=True)
    Box = Canvas.getbbox()
    if not Box:
        return None
    return Canvas.crop(Box)


def FallbackIcon(name: str, rarity: str, size: int) -> Image.Image:
    """Used when an emoji can't be drawn: a colored badge with the initial."""
    Main, Light, Dark = PALETTE[rarity]
    Icon = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    Mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(Mask).ellipse((0, 0, size - 1, size - 1), fill=255)
    Fill = Radial((size, size), (size * 0.35, size * 0.3), size, Light, Dark).convert("RGBA")
    Icon.paste(Fill, (0, 0), Mask)
    D = ImageDraw.Draw(Icon)
    D.ellipse((2, 2, size - 3, size - 3), outline=Main + (255,), width=max(2, size // 30))
    Letter = (name.strip()[:1] or "?").upper()
    F = Font(int(size * 0.5))
    D.text((size / 2, size / 2), Letter, font=F, fill=(255, 255, 255, 240), anchor="mm")
    return Icon


ART_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "assets", "pets")
_art: dict[str, Image.Image | None] = {}


def Art(name: str | None) -> Image.Image | None:
    """A drawing bundled in assets/pets (e.g. 'pumpkin' -> assets/pets/pumpkin.png)."""
    if not name or not name.replace("_", "").replace("-", "").isalnum():
        return None
    if name not in _art:
        Path = os.path.join(ART_DIR, f"{name}.png")
        _art[name] = Image.open(Path).convert("RGBA") if os.path.exists(Path) else None
    return _art[name]


def Icon(emoji: str | None, name: str, rarity: str, size: int, custom: dict | None = None, art: str | None = None) -> Image.Image:
    """The picture for a prize: bundled art, custom Discord emoji (pre-downloaded in `custom`), unicode emoji, or a fallback."""
    Picture = Art(art)
    if Picture is None and emoji:
        Match = CUSTOM_EMOJI.match(emoji)
        if Match and custom and custom.get(Match.group(1)) is not None:
            Picture = custom[Match.group(1)]
        elif not Match:
            Picture = UnicodeEmoji(emoji)
    if Picture is None:
        return FallbackIcon(name, rarity, size)
    # Scale to fit (up or down): the emoji font only renders at one size.
    Ratio = size / max(Picture.width, Picture.height)
    Picture = Picture.resize((max(1, round(Picture.width * Ratio)), max(1, round(Picture.height * Ratio))), Image.LANCZOS)
    Out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    Out.paste(Picture, ((size - Picture.width) // 2, (size - Picture.height) // 2), Picture)
    return Out


def CustomEmojiIds(emojis) -> set[str]:
    return {M.group(1) for E in emojis if E for M in [CUSTOM_EMOJI.match(E)] if M}


# ---------------- pull animation ----------------


def Bezier(p0, p1, p2, t):
    return (
        (1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t**2 * p2[0],
        (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t**2 * p2[1],
    )


def EaseOut(t):
    return 1 - (1 - t) ** 3


def SkyBackground(tier: str, rng: random.Random) -> Image.Image:
    W, H = GIF_SIZE
    Sky = Gradient(GIF_SIZE, BG_TOP, BG_BOTTOM).convert("RGBA")
    # Soft nebula clouds tinted with the tier color.
    Nebula = Image.new("RGBA", GIF_SIZE, (0, 0, 0, 0))
    D = ImageDraw.Draw(Nebula)
    Color = TIERS[tier]["glow"]
    for _ in range(5):
        X, Y = rng.uniform(0, W), rng.uniform(0, H)
        Rx, Ry = rng.uniform(60, 160), rng.uniform(30, 90)
        D.ellipse((X - Rx, Y - Ry, X + Rx, Y + Ry), fill=Color + (rng.randint(18, 34),))
    return Image.alpha_composite(Sky, Glow(Nebula, 30))


def PullGif(tier: str) -> bytes:
    """Builds the shooting-star animation for a tier (blue, purple or gold)."""
    Settings = TIERS[tier]
    W, H = GIF_SIZE
    Rng = random.Random(f"gacha-{tier}")
    Base = SkyBackground(tier, Rng)
    Stars = [(Rng.uniform(0, W), Rng.uniform(0, H * 0.9), Rng.uniform(0.6, 1.8), Rng.uniform(0, math.tau), Rng.uniform(0.15, 0.45)) for _ in range(110)]
    Start, Control, Impact = (-40, 20), (W * 0.22, H * 0.02), (W * 0.5, H * 0.55)
    Scale = Settings["scale"]
    Glow_, Core = Settings["glow"], Settings["core"]
    Sparks: list[list[float]] = []
    Burst = [
        [Impact[0], Impact[1], math.cos(A) * V, math.sin(A) * V, Rng.uniform(0.55, 1.0)]
        for A, V in ((Rng.uniform(0, math.tau), Rng.uniform(3, 10) * Scale) for _ in range(int(80 * Scale)))
    ]
    Frames = []
    for F in range(TRAVEL_FRAMES + BURST_FRAMES):
        Frame = Base.copy()
        D = ImageDraw.Draw(Frame)
        for X, Y, R, Phase, Speed in Stars:
            A = int(130 + 120 * math.sin(Phase + F * Speed))
            D.ellipse((X - R, Y - R, X + R, Y + R), fill=(255, 255, 255, max(40, A)))
        Soft = Image.new("RGBA", GIF_SIZE, (0, 0, 0, 0))  # heavily blurred glow
        Mid = Image.new("RGBA", GIF_SIZE, (0, 0, 0, 0))  # lightly blurred (rays, trail)
        Sharp = Image.new("RGBA", GIF_SIZE, (0, 0, 0, 0))  # crisp highlights
        Ls, Lm, S = ImageDraw.Draw(Soft), ImageDraw.Draw(Mid), ImageDraw.Draw(Sharp)
        if F < TRAVEL_FRAMES:
            T = ((F + 1) / TRAVEL_FRAMES) ** 1.6
            Head = Bezier(Start, Control, Impact, T)
            Points = [Bezier(Start, Control, Impact, max(0.0, T - k * 0.02)) for k in range(24)]
            for k in range(len(Points) - 1):
                Fade = (1 - k / len(Points)) ** 1.3
                Width = max(1, int((20 * Fade + 3) * Scale))
                Ls.line([Points[k], Points[k + 1]], fill=Glow_ + (int(190 * Fade),), width=Width + 8)
                Lm.line([Points[k], Points[k + 1]], fill=Glow_ + (int(235 * Fade),), width=max(1, Width // 2))
                S.line([Points[k], Points[k + 1]], fill=Core + (int(255 * Fade),), width=max(1, Width // 5))
            R = 13 * Scale * (0.8 + 0.4 * T)
            Ls.ellipse((Head[0] - R * 3, Head[1] - R * 3, Head[0] + R * 3, Head[1] + R * 3), fill=Glow_ + (210,))
            Lm.ellipse((Head[0] - R * 1.3, Head[1] - R * 1.3, Head[0] + R * 1.3, Head[1] + R * 1.3), fill=Core + (255,))
            S.ellipse((Head[0] - R * 0.6, Head[1] - R * 0.6, Head[0] + R * 0.6, Head[1] + R * 0.6), fill=(255, 255, 255, 255))
            for _ in range(int(4 * Scale)):
                Sparks.append([Head[0] + Rng.uniform(-4, 4), Head[1] + Rng.uniform(-4, 4), Rng.uniform(-2.8, 0.3), Rng.uniform(-0.3, 2.8), 1.0])
        else:
            K = (F - TRAVEL_FRAMES) / (BURST_FRAMES - 1)
            Ease = EaseOut(K)
            # Rotating light rays that grow and stay.
            Length = (90 + 420 * Ease) * Scale
            RayAlpha = int(150 + 80 * math.sin(math.pi * min(1.0, K * 1.2)))
            for i in range(Settings["rays"]):
                A = i * math.tau / Settings["rays"] + K * 0.5
                Spread = 0.05 + 0.03 * (i % 2)
                Tip = (Impact[0] + math.cos(A) * Length, Impact[1] + math.sin(A) * Length)
                Left = (Impact[0] + math.cos(A - Spread) * 14, Impact[1] + math.sin(A - Spread) * 14)
                Right = (Impact[0] + math.cos(A + Spread) * 14, Impact[1] + math.sin(A + Spread) * 14)
                Lm.polygon([Left, (Tip[0] + math.cos(A - Spread) * 40, Tip[1] + math.sin(A - Spread) * 40), (Tip[0] + math.cos(A + Spread) * 40, Tip[1] + math.sin(A + Spread) * 40), Right], fill=Glow_ + (RayAlpha,))
                S.line([Impact, Tip], fill=Core + (int(RayAlpha * 0.6),), width=2)
            # Shockwave ring(s).
            for Delay in ((0.0, 0.2) if tier == "gold" else (0.0,)):
                Kr = (K - Delay) / (1 - Delay)
                if 0 < Kr < 0.85:
                    Radius = EaseOut(Kr) * W * 0.75
                    Alpha = int(255 * (1 - Kr / 0.85))
                    Box = (Impact[0] - Radius, Impact[1] - Radius, Impact[0] + Radius, Impact[1] + Radius)
                    Lm.ellipse(Box, outline=Glow_ + (Alpha,), width=int(12 * Scale))
                    S.ellipse(Box, outline=Core + (Alpha,), width=2)
            # The light swells until it fills the screen.
            R = (26 + 300 * K**1.5) * Scale
            Ls.ellipse((Impact[0] - R, Impact[1] - R, Impact[0] + R, Impact[1] + R), fill=Glow_ + (235,))
            for P in Burst:
                P[0] += P[2]
                P[1] += P[3]
                P[3] += 0.1
                P[2] *= 0.965
                Life = max(0.0, P[4] - K * 0.9)
                if Life > 0:
                    Size = 1.6 + 2.4 * Life * Scale
                    S.ellipse((P[0] - Size, P[1] - Size, P[0] + Size, P[1] + Size), fill=(255, 255, 255, int(255 * Life)))
                    Lm.ellipse((P[0] - Size * 2.6, P[1] - Size * 2.6, P[0] + Size * 2.6, P[1] + Size * 2.6), fill=Glow_ + (int(170 * Life),))
            # Bright core on top of the particles so they don't look like stains on it.
            Rc = (16 + 120 * K**1.6) * Scale
            Lm.ellipse((Impact[0] - Rc, Impact[1] - Rc, Impact[0] + Rc, Impact[1] + Rc), fill=Core + (255,))
            if tier in ("gold", "purple"):
                Count = 12 if tier == "gold" else 7
                for i in range(Count):
                    A = i * math.tau / Count + 0.3 + K
                    Dist = 50 + 150 * Ease
                    Cx, Cy = Impact[0] + math.cos(A) * Dist * 1.4, Impact[1] + math.sin(A) * Dist * 0.8
                    Size = 10 * (1 - K) * Scale + 2
                    S.polygon(StarShape(Cx, Cy, Size, Size * 0.28, 4, K * 3), fill=Core + (int(255 * (1 - K * 0.8)),))
        for P in Sparks:
            P[0] += P[2]
            P[1] += P[3]
            P[4] -= 0.08
            if P[4] > 0:
                Size = 1.6 * Scale * P[4] + 0.6
                S.ellipse((P[0] - Size, P[1] - Size, P[0] + Size, P[1] + Size), fill=Core + (int(255 * P[4]),))
        Sparks[:] = [P for P in Sparks if P[4] > 0]
        Frame = Image.alpha_composite(Frame, Glow(Soft, 16 * Scale))
        Frame = Image.alpha_composite(Frame, Glow(Mid, 3.5))
        Frame = Image.alpha_composite(Frame, Glow(Sharp, 0.6))
        if F >= TRAVEL_FRAMES:
            K = (F - TRAVEL_FRAMES) / (BURST_FRAMES - 1)
            # Impact flash, then a final wash of light (the card comes after it).
            Flash = 200 * max(0.0, 1 - (F - TRAVEL_FRAMES) / 3) + 225 * max(0.0, (K - 0.6) / 0.4) ** 1.5
            if Flash > 0:
                Frame = Image.alpha_composite(Frame, Image.new("RGBA", GIF_SIZE, Core + (int(min(235, Flash)),)))
        Frames.append(Frame.convert("RGB"))

    # One palette from a mosaic of frames, so the dark sky and the bright burst both look right.
    Sample = Image.new("RGB", (W * 4, H))
    for i, F in enumerate((Frames[4], Frames[TRAVEL_FRAMES - 2], Frames[TRAVEL_FRAMES + 5], Frames[-2])):
        Sample.paste(F, (i * W, 0))
    Palette = Sample.quantize(colors=GIF_COLORS, method=Image.Quantize.MEDIANCUT)
    Indexed = [F.quantize(palette=Palette, dither=Image.Dither.FLOYDSTEINBERG) for F in Frames]
    Out = io.BytesIO()
    Durations = [FRAME_MS] * (len(Indexed) - 1) + [LAST_FRAME_MS]
    Indexed[0].save(Out, "GIF", save_all=True, append_images=Indexed[1:], duration=Durations, loop=0, optimize=True, disposal=1)
    return Out.getvalue()


_gifs: dict[str, bytes] = {}


def Animation(tier: str) -> bytes:
    """The animation for a tier: your own file in assets/gacha/ if present, else the generated one (cached)."""
    if tier not in _gifs:
        Custom = os.path.join(GIF_DIR, f"{tier}.gif")
        if os.path.isfile(Custom):
            with open(Custom, "rb") as F:
                _gifs[tier] = F.read()
        else:
            _gifs[tier] = PullGif(tier)
    return _gifs[tier]


def AnimationSeconds(data: bytes) -> float:
    try:
        Gif = Image.open(io.BytesIO(data))
        Total = 0
        for i in range(getattr(Gif, "n_frames", 1)):
            Gif.seek(i)
            Total += Gif.info.get("duration", FRAME_MS)
        return Total / 1000
    except Exception:
        return 2.0


def BestTier(rarities: list[str]) -> str:
    return RARITY_TIER[max(rarities, key=RARITY_ORDER.index)]


# ---------------- result cards ----------------


def Rounded(size, radius) -> Image.Image:
    Mask = Image.new("L", size, 0)
    ImageDraw.Draw(Mask).rounded_rectangle((0, 0, size[0] - 1, size[1] - 1), radius=radius, fill=255)
    return Mask


def Pill(draw: ImageDraw.ImageDraw, xy, text: str, font, fill, text_fill=(255, 255, 255), anchor_right=False):
    X, Y = xy
    Width = font.getlength(text) + 22
    Height = font.size + 12
    if anchor_right:
        X -= Width
    draw.rounded_rectangle((X, Y, X + Width, Y + Height), radius=Height // 2, fill=fill)
    draw.text((X + Width / 2, Y + Height / 2), text, font=font, fill=text_fill, anchor="mm")
    return Width


TYPE_LABEL = {"pet": "Mascota", "item": "Item", "credits": "Créditos"}


def Badge(result) -> tuple[str, tuple] | None:
    if result.get("new"):
        return "¡NUEVA!", (230, 70, 90)
    if result.get("detail"):
        return result["detail"], (60, 64, 90)
    return None


def SingleCard(result: dict, info: dict, custom: dict | None = None) -> bytes:
    """Big card for one pull. `result`: name, emoji, rarity, kind, subtitle, featured, new, detail."""
    W, H = 900, 500
    Rarity = result["rarity"]
    Main, Light, Dark = PALETTE[Rarity]
    Card = Radial((W, H), (270, 230), 620, Lerp(Main, Dark, 0.35), BG_TOP).convert("RGBA")
    # Rays behind the icon.
    Rays = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    R = ImageDraw.Draw(Rays)
    Count = 6 + STAR_COUNT[Rarity] * 3
    for i in range(Count):
        A = i * math.tau / Count
        Tip1 = (270 + math.cos(A - 0.09) * 520, 240 + math.sin(A - 0.09) * 520)
        Tip2 = (270 + math.cos(A + 0.09) * 520, 240 + math.sin(A + 0.09) * 520)
        R.polygon([(270, 240), Tip1, Tip2], fill=Light + (34,))
    Card = Image.alpha_composite(Card, Glow(Rays, 6))
    # Glow behind the icon.
    Halo = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(Halo).ellipse((130, 100, 410, 380), fill=Main + (190,))
    Card = Image.alpha_composite(Card, Glow(Halo, 45))
    Picture = Icon(result.get("emoji"), result["name"], Rarity, 230, custom, result.get("art"))
    Shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    Shadow.paste((0, 0, 0, 120), (155 + 8, 125 + 14), Picture)
    Card = Image.alpha_composite(Card, Glow(Shadow, 10))
    Card.paste(Picture, (155, 125), Picture)

    D = ImageDraw.Draw(Card)
    X = 470
    D.text((X, 92), result["rarity_label"].upper(), font=Font(22), fill=Light)
    DrawStars(D, X - 2, 128, STAR_COUNT[Rarity], 15, (255, 214, 90))
    NameFont = FitFont(result["name"], 390, 50, 28)
    Y = 176
    for Line in Wrap(result["name"], NameFont, 390):
        D.text((X, Y), Line, font=NameFont, fill=(255, 255, 255))
        Y += NameFont.size + 8
    D.text((X, Y + 6), result.get("subtitle", ""), font=Font(20, bold=False), fill=(205, 210, 230))
    Y += 52
    Pills = []
    if result.get("featured"):
        Pills.append(("★ DESTACADO", (205, 150, 30)))
    B = Badge(result)
    if B:
        Pills.append(B)
    for Text, Color in Pills:
        X += Pill(D, (X, Y), Text, Font(18), Color) + 10
    # Bottom bar.
    Bar = Image.new("RGBA", (W, 56), (8, 10, 24, 190))
    Card.alpha_composite(Bar, (0, H - 56))
    D = ImageDraw.Draw(Card)
    D.text((24, H - 28), f"{info.get('banner', '')} · {info.get('user', '')}", font=Font(17, bold=False), fill=(200, 205, 225), anchor="lm")
    D.text((W - 24, H - 28), info.get("pity", ""), font=Font(17), fill=(255, 214, 90), anchor="rm")
    Frame = Card.convert("RGB")
    Border = Image.new("RGB", (W, H), Main)
    Inner = Rounded((W - 8, H - 8), 26)
    Border.paste(Frame.crop((4, 4, W - 4, H - 4)), (4, 4), Inner)
    Out = io.BytesIO()
    Final = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    Final.paste(Border, (0, 0), Rounded((W, H), 30))
    Final.save(Out, "PNG", optimize=True)
    return Out.getvalue()


def Tile(result: dict, size, custom: dict | None) -> Image.Image:
    W, H = size
    Rarity = result["rarity"]
    Main, Light, Dark = PALETTE[Rarity]
    Bg = Gradient(size, Lerp(Dark, BG_TOP, 0.4), Lerp(Main, Dark, 0.25)).convert("RGBA")
    Halo = Image.new("RGBA", size, (0, 0, 0, 0))
    ImageDraw.Draw(Halo).ellipse((W * 0.18, 18, W * 0.82, 18 + W * 0.64), fill=Light + (120,))
    Bg = Image.alpha_composite(Bg, Glow(Halo, 22))
    Picture = Icon(result.get("emoji"), result["name"], Rarity, 112, custom, result.get("art"))
    Bg.paste(Picture, ((W - 112) // 2, 26), Picture)
    D = ImageDraw.Draw(Bg)
    Stars = STAR_COUNT[Rarity]
    StarSize, Gap = 7, 17
    DrawStars(D, (W - (Stars - 1) * Gap - StarSize * 2) / 2, 148, Stars, StarSize, (255, 214, 90), Gap)
    F = FitFont(result["name"], W - 20, 18, 13)
    Y = 170
    for Line in Wrap(result["name"], F, W - 20):
        D.text((W / 2, Y), Line, font=F, fill=(255, 255, 255), anchor="ma")
        Y += F.size + 4
    B = Badge(result)
    if B:
        Pill(D, (W - 8, 8), B[0], Font(12), B[1], anchor_right=True)
    if result.get("featured"):
        Pill(D, (8, 8), "★", Font(12), (205, 150, 30))
    Masked = Image.new("RGBA", size, (0, 0, 0, 0))
    Masked.paste(Bg, (0, 0), Rounded(size, 18))
    ImageDraw.Draw(Masked).rounded_rectangle((1, 1, W - 2, H - 2), radius=18, outline=Main + (255,), width=3)
    return Masked


def GridCard(results: list[dict], info: dict, custom: dict | None = None) -> bytes:
    """5x2 grid for a x10 pull, best rarities first."""
    Cols, Rows = 5, 2
    TileSize = (196, 236)
    Gap, Pad, Top, Bottom = 16, 28, 86, 60
    W = Pad * 2 + Cols * TileSize[0] + (Cols - 1) * Gap
    H = Top + Rows * TileSize[1] + (Rows - 1) * Gap + Bottom
    Best = max((R["rarity"] for R in results), key=RARITY_ORDER.index)
    Main, Light, Dark = PALETTE[Best]
    Canvas = Radial((W, H), (W / 2, H * 0.45), W * 0.75, Lerp(Main, Dark, 0.55), BG_TOP).convert("RGBA")
    D = ImageDraw.Draw(Canvas)
    D.text((Pad, 30), f"Tirada x{len(results)}", font=Font(30), fill=(255, 255, 255))
    D.text((Pad + Font(30).getlength(f"Tirada x{len(results)}") + 16, 40), info.get("banner", ""), font=Font(20, bold=False), fill=Light)
    D.text((W - Pad, 42), info.get("user", ""), font=Font(18, bold=False), fill=(200, 205, 225), anchor="rm")
    Ordered = sorted(results, key=lambda R: (RARITY_ORDER.index(R["rarity"]), R.get("featured", False)), reverse=True)
    for i, Result in enumerate(Ordered[: Cols * Rows]):
        X = Pad + (i % Cols) * (TileSize[0] + Gap)
        Y = Top + (i // Cols) * (TileSize[1] + Gap)
        if Result["rarity"] in ("epic", "legendary"):
            Aura = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            ImageDraw.Draw(Aura).rounded_rectangle((X - 6, Y - 6, X + TileSize[0] + 6, Y + TileSize[1] + 6), radius=22, fill=PALETTE[Result["rarity"]][0] + (200,))
            Canvas = Image.alpha_composite(Canvas, Glow(Aura, 12))
        Canvas.alpha_composite(Tile(Result, TileSize, custom), (X, Y))
    D = ImageDraw.Draw(Canvas)
    D.text((W - Pad, H - Bottom / 2), info.get("pity", ""), font=Font(17), fill=(255, 214, 90), anchor="rm")
    D.text((Pad, H - Bottom / 2), info.get("summary", ""), font=Font(17, bold=False), fill=(200, 205, 225), anchor="lm")
    Out = io.BytesIO()
    Canvas.convert("RGB").save(Out, "PNG", optimize=True)
    return Out.getvalue()
