"""
Images for the booster colors panel, drawn from the roles' own gradients:
- Swatch(): every color as a glossy gradient card with its number and name (two columns, dark plum background).
- Emoji(): a gradient disc, uploaded as one of the bot's emojis for its button.
"""

import io
import os

from PIL import Image, ImageDraw, ImageFilter, ImageFont

FONTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "fonts")
BOLD = os.path.join(FONTS, "Inter-Bold.otf")
SEMI = os.path.join(FONTS, "Inter-SemiBold.otf")
FALLBACK = os.path.join(FONTS, "DejaVuSans-Bold.ttf")
BACKGROUND = (22, 12, 20)
GLOW = (70, 26, 54)


def Font(path: str, size: int):
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.truetype(FALLBACK, size)


def Rgb(value) -> tuple[int, int, int]:
    if isinstance(value, int):
        return (value >> 16) & 255, (value >> 8) & 255, value & 255
    Text = str(value).lstrip("#")
    return tuple(int(Text[I:I + 2], 16) for I in (0, 2, 4))


def Gradient(width: int, height: int, a, b) -> Image.Image:
    """Left-to-right gradient (drawn as one line, then stretched: fast)."""
    A, B = Rgb(a), Rgb(b)
    Line = Image.new("RGB", (width, 1))
    Px = Line.load()
    for X in range(width):
        T = X / max(1, width - 1)
        Px[X, 0] = tuple(round(A[I] + (B[I] - A[I]) * T) for I in range(3))
    return Line.resize((width, height), Image.NEAREST)


def TextIsDark(a, b, at: float = 0.22) -> bool:
    """Dark text on bright colors, measured where the text sits (the left part)."""
    A, B = Rgb(a), Rgb(b)
    R, G, Bl = (A[I] + (B[I] - A[I]) * at for I in range(3))
    return 0.2126 * R + 0.7152 * G + 0.0722 * Bl > 170


def Swatch(colors: list[tuple[str, object, object]], scale: int = 2) -> bytes:
    """colors: [(name, first color, second color)] in panel order. PNG bytes."""
    Cols = 2 if len(colors) > 1 else 1
    Rows = (len(colors) + Cols - 1) // Cols
    Pad, Gap, CW, CH, Radius = 36 * scale, 18 * scale, 520 * scale, 76 * scale, 22 * scale
    W = Pad * 2 + CW * Cols + Gap * (Cols - 1)
    H = Pad * 2 + CH * Rows + Gap * (Rows - 1)
    Canvas = Image.new("RGB", (W, H), BACKGROUND)
    Glow = Image.new("RGB", (W, H), BACKGROUND)
    ImageDraw.Draw(Glow).ellipse((W * 0.15, -H * 0.3, W * 0.85, H * 0.5), fill=GLOW)
    Canvas = Image.blend(Canvas, Glow.filter(ImageFilter.GaussianBlur(120 * scale)), 0.9).convert("RGBA")
    NameFont, NumFont = Font(BOLD, 32 * scale), Font(SEMI, 15 * scale)
    # Shadows, gloss and card mask are the same for every card: made once.
    Gloss = Image.new("RGBA", (CW, CH), (0, 0, 0, 0))
    GD = ImageDraw.Draw(Gloss)
    for Y in range(CH // 2):
        GD.line([(0, Y), (CW, Y)], fill=(255, 255, 255, int(46 * (1 - Y / (CH / 2)))))
    Mask = Image.new("L", (CW, CH), 0)
    ImageDraw.Draw(Mask).rounded_rectangle((0, 0, CW - 1, CH - 1), radius=Radius, fill=255)
    Shadows = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    SD = ImageDraw.Draw(Shadows)
    Places = []
    for I in range(len(colors)):
        X, Y = Pad + (I % Cols) * (CW + Gap), Pad + (I // Cols) * (CH + Gap)
        Places.append((X, Y))
        SD.rounded_rectangle((X, Y + 6 * scale, X + CW, Y + CH + 6 * scale), radius=Radius, fill=(0, 0, 0, 110))
    Canvas = Image.alpha_composite(Canvas, Shadows.filter(ImageFilter.GaussianBlur(10 * scale)))
    TextShadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    TSD = ImageDraw.Draw(TextShadow)
    Labels = []
    for I, ((Name, A, B), (X, Y)) in enumerate(zip(colors, Places)):
        Card = Image.alpha_composite(Gradient(CW, CH, A, B).convert("RGBA"), Gloss)
        Canvas.paste(Card, (X, Y), Mask)
        Dark = TextIsDark(A, B)
        if not Dark:
            TSD.text((X + 64 * scale, Y + CH / 2 + 2 * scale), Name, font=NameFont, fill=(0, 0, 0, 120), anchor="lm")
        Labels.append((I, Name, X, Y, Dark))
    Canvas = Image.alpha_composite(Canvas, TextShadow.filter(ImageFilter.GaussianBlur(4 * scale)))
    D = ImageDraw.Draw(Canvas)
    for I, Name, X, Y, Dark in Labels:
        Ink = (24, 18, 28) if Dark else (255, 255, 255)
        Soft = (24, 18, 28, 170) if Dark else (255, 255, 255, 200)
        D.text((X + 26 * scale, Y + CH / 2), f"{I + 1:02d}", font=NumFont, fill=Soft, anchor="lm")
        D.text((X + 64 * scale, Y + CH / 2), Name, font=NameFont, fill=Ink, anchor="lm")
    Out = io.BytesIO()
    Canvas.convert("RGB").save(Out, "PNG", optimize=True)
    return Out.getvalue()


def Emoji(a, b, size: int = 128) -> bytes:
    """A glossy gradient disc (PNG bytes) for a button."""
    Big = size * 4
    Disc = Gradient(Big, Big, a, b).rotate(-35, resample=Image.BICUBIC).convert("RGBA")
    Gloss = Image.new("RGBA", (Big, Big), (0, 0, 0, 0))
    ImageDraw.Draw(Gloss).ellipse((Big * 0.18, Big * 0.08, Big * 0.82, Big * 0.5), fill=(255, 255, 255, 60))
    Disc = Image.alpha_composite(Disc, Gloss.filter(ImageFilter.GaussianBlur(Big * 0.04)))
    Mask = Image.new("L", (Big, Big), 0)
    ImageDraw.Draw(Mask).ellipse((Big * 0.06, Big * 0.06, Big * 0.94, Big * 0.94), fill=255)
    Out = Image.new("RGBA", (Big, Big), (0, 0, 0, 0))
    Out.paste(Disc, (0, 0), Mask)
    ImageDraw.Draw(Out).ellipse((Big * 0.06, Big * 0.06, Big * 0.94, Big * 0.94), outline=(255, 255, 255, 90), width=int(Big * 0.025))
    Data = io.BytesIO()
    Out.resize((size, size), Image.LANCZOS).save(Data, "PNG", optimize=True)
    return Data.getvalue()
