"""
Pet visuals drawn with Pillow: the pet card (/mascota ver), the album (/mascota lista)
and the evolution animation. Same look as the gacha cards (core/economy/cards.py).
CPU-bound and synchronous: call with asyncio.to_thread.
"""

import io
import math
import random

from PIL import Image, ImageDraw

from core.economy.cards import (
    BG_TOP,
    PALETTE,
    STAR_COUNT,
    DrawStars,
    FitFont,
    Font,
    Glow,
    Icon,
    Lerp,
    Radial,
    Rounded,
    StarShape,
    UnicodeEmoji,
    Wrap,
)

CARD_SIZE = (900, 520)
TEXT = (255, 255, 255)
TEXT_SECONDARY = (205, 210, 230)
TEXT_MUTED = (160, 165, 185)
STAR_COLOR = (255, 214, 90)
# Fixed status colors (good / warning / serious / critical), always shown with an icon and a number.
STATUS = [(70, (12, 163, 12)), (40, (250, 178, 25)), (15, (236, 131, 90)), (0, (208, 59, 59))]
TRACK = (255, 255, 255, 40)
MOOD_DECOR = {"happy": ["✨", "💕", "✨"], "ok": [], "sad": ["💧"], "abandoned": ["💤", "💧"]}

# Evolution animation
EVO_SIZE = (480, 300)
EVO_FRAMES = 40
EVO_FRAME_MS = 60
EVO_LAST_MS = 900


def StatusColor(value: float) -> tuple:
    return next(Color for Limit, Color in STATUS if value >= Limit)


def Mood(hunger: float, happiness: float) -> str:
    Low = min(hunger, happiness)
    if Low >= 70:
        return "happy"
    if Low >= 40:
        return "ok"
    if Low >= 15:
        return "sad"
    return "abandoned"


def SmallEmoji(emoji: str, size: int) -> Image.Image | None:
    Picture = UnicodeEmoji(emoji)
    if Picture is None:
        return None
    Ratio = size / max(Picture.size)
    return Picture.resize((max(1, round(Picture.width * Ratio)), max(1, round(Picture.height * Ratio))), Image.LANCZOS)


def PasteEmoji(canvas: Image.Image, emoji: str, center, size: int, angle: float = 0):
    Picture = SmallEmoji(emoji, size)
    if Picture is None:
        return
    if angle:
        Picture = Picture.rotate(angle, resample=Image.BICUBIC, expand=True)
    canvas.alpha_composite(Picture, (int(center[0] - Picture.width / 2), int(center[1] - Picture.height / 2)))


def Bar(canvas: Image.Image, xy, width: int, value: float, icon: str, label: str):
    """A care bar: icon, label, percentage, and a status-colored fill."""
    X, Y = xy
    D = ImageDraw.Draw(canvas)
    PasteEmoji(canvas, icon, (X + 14, Y + 11), 26)
    D.text((X + 36, Y + 11), label, font=Font(18), fill=TEXT_SECONDARY, anchor="lm")
    D.text((X + width, Y + 11), f"{value:.0f}%", font=Font(18), fill=TEXT, anchor="rm")
    Top = Y + 30
    Layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    L = ImageDraw.Draw(Layer)
    L.rounded_rectangle((X, Top, X + width, Top + 16), radius=8, fill=TRACK)
    Fill = int(width * max(0.0, min(100.0, value)) / 100)
    if Fill > 0:
        L.rounded_rectangle((X, Top, X + max(Fill, 16), Top + 16), radius=8, fill=StatusColor(value) + (255,))
    canvas.alpha_composite(Layer)


def LevelBadge(canvas: Image.Image, center, radius: int, level: int, progress: float, color):
    """Level number inside a ring that fills with XP progress."""
    Cx, Cy = center
    Layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    L = ImageDraw.Draw(Layer)
    Box = (Cx - radius, Cy - radius, Cx + radius, Cy + radius)
    L.ellipse(Box, fill=(10, 12, 28, 200))
    L.arc(Box, 0, 360, fill=TRACK, width=8)
    if progress > 0:
        L.arc(Box, -90, -90 + 360 * min(1.0, progress), fill=color + (255,), width=8)
    canvas.alpha_composite(Layer)
    D = ImageDraw.Draw(canvas)
    D.text((Cx, Cy - 12), "NIVEL", font=Font(13), fill=TEXT_MUTED, anchor="mm")
    D.text((Cx, Cy + 12), str(level), font=Font(30), fill=TEXT, anchor="mm")


def PetCard(pet: dict) -> bytes:
    """
    pet: name, species, emoji, rarity, rarity_label, archetype, level, xp, xp_next,
    hunger, happiness, care, perk, perk_note, owner, footer.
    """
    W, H = CARD_SIZE
    Rarity = pet["rarity"]
    Main, Light, Dark = PALETTE[Rarity]
    Card = Radial((W, H), (230, 250), 560, Lerp(Main, Dark, 0.35), BG_TOP).convert("RGBA")
    Mood_ = Mood(pet["hunger"], pet["happiness"])
    # Sad pets get a darker, bluer scene.
    if Mood_ in ("sad", "abandoned"):
        Card = Image.alpha_composite(Card, Image.new("RGBA", (W, H), (20, 30, 60, 90 if Mood_ == "sad" else 140)))
    # Halo and floor shadow.
    Halo = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(Halo).ellipse((90, 90, 370, 370), fill=Main + (150 if Mood_ == "happy" else 90,))
    Card = Image.alpha_composite(Card, Glow(Halo, 45))
    Shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(Shadow).ellipse((130, 388, 330, 420), fill=(0, 0, 0, 130))
    Card = Image.alpha_composite(Card, Glow(Shadow, 8))
    Picture = Icon(pet.get("emoji"), pet["name"], Rarity, 240)
    if Mood_ == "abandoned":
        Picture = Picture.rotate(-12, resample=Image.BICUBIC)
    Card.alpha_composite(Picture, (110, 150))
    # Mood decorations around the pet.
    Spots = [(105, 140, -15), (365, 175, 12), (350, 365, 0)]
    for (X, Y, Angle), Emoji in zip(Spots, MOOD_DECOR[Mood_]):
        PasteEmoji(Card, Emoji, (X, Y), 46, Angle)
    if Mood_ == "happy":
        D = ImageDraw.Draw(Card)
        Rng = random.Random(pet["name"])
        for _ in range(7):
            X, Y = Rng.uniform(80, 400), Rng.uniform(100, 400)
            D.polygon(StarShape(X, Y, Rng.uniform(4, 8), 2, 4), fill=Light + (220,))

    D = ImageDraw.Draw(Card)
    X, Right = 440, W - 40
    NameFont = FitFont(pet["name"], Right - X - 120, 44, 26, lines=1)
    D.text((X, 42), Wrap(pet["name"], NameFont, Right - X - 120, 1)[0], font=NameFont, fill=TEXT)
    if pet["species"] and pet["species"] != pet["name"]:
        D.text((X, 42 + NameFont.size + 10), pet["species"], font=Font(19, bold=False), fill=TEXT_SECONDARY)
    Y = 42 + NameFont.size + 42
    DrawStars(D, X - 1, Y, STAR_COUNT[Rarity], 11, STAR_COLOR, 26)
    # Must not run into the level badge on the right.
    Tag = f"{pet['rarity_label']} · {pet['archetype']}"
    TagX = X + STAR_COUNT[Rarity] * 26 + 8
    TagFont = FitFont(Tag, Right - 112 - TagX, 17, 12, lines=1)
    D.text((TagX, Y + 11), Wrap(Tag, TagFont, Right - 112 - TagX, 1)[0], font=TagFont, fill=Light, anchor="lm")
    Progress = pet["xp"] / pet["xp_next"] if pet["xp_next"] else 1.0
    LevelBadge(Card, (Right - 52, 82), 50, pet["level"], Progress, Main)
    XpText = f"{pet['xp']}/{pet['xp_next']} XP" if pet["xp_next"] else "Nivel máximo"
    D.text((Right - 52, 146), XpText, font=Font(13, bold=False), fill=TEXT_MUTED, anchor="mm")

    Bar(Card, (X, 190), Right - X, pet["hunger"], "🍖", "Comida")
    Bar(Card, (X, 252), Right - X, pet["happiness"], "🎾", "Felicidad")

    # Perk box.
    Box = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(Box).rounded_rectangle((X, 322, Right, 412), radius=16, fill=(255, 255, 255, 22), outline=Main + (160,), width=2)
    Card = Image.alpha_composite(Card, Box)
    D = ImageDraw.Draw(Card)
    PasteEmoji(Card, "✨", (X + 30, 352), 30)
    D.text((X + 56, 352), pet["perk"], font=FitFont(pet["perk"], Right - X - 76, 22, 15, lines=1), fill=TEXT, anchor="lm")
    if pet.get("perk_note"):
        D.text((X + 56, 386), pet["perk_note"], font=Font(15, bold=False), fill=StatusColor(pet["care"] * 100), anchor="lm")

    # Footer bar.
    Card.alpha_composite(Image.new("RGBA", (W, 52), (8, 10, 24, 190)), (0, H - 52))
    D = ImageDraw.Draw(Card)
    D.text((24, H - 26), f"Mascota de {pet['owner']}", font=Font(16, bold=False), fill=TEXT_SECONDARY, anchor="lm")
    D.text((W - 24, H - 26), pet.get("footer", ""), font=Font(16), fill=STAR_COLOR, anchor="rm")
    return Framed(Card, Main)


def Framed(card: Image.Image, color) -> bytes:
    W, H = card.size
    Out = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    Out.paste(card, (0, 0), Rounded((W, H), 28))
    ImageDraw.Draw(Out).rounded_rectangle((1, 1, W - 2, H - 2), radius=28, outline=color + (255,), width=4)
    Buffer = io.BytesIO()
    Out.save(Buffer, "PNG", optimize=True)
    return Buffer.getvalue()


def AlbumTile(pet: dict, size) -> Image.Image:
    W, H = size
    Rarity = pet["rarity"]
    Main, Light, Dark = PALETTE[Rarity]
    Tile = Radial(size, (W / 2, 80), W * 0.8, Lerp(Main, Dark, 0.3), Lerp(Dark, BG_TOP, 0.5)).convert("RGBA")
    Picture = Icon(pet.get("emoji"), pet["name"], Rarity, 104)
    if Mood(pet["hunger"], pet["happiness"]) in ("sad", "abandoned"):
        Picture.putalpha(Picture.getchannel("A").point(lambda A: int(A * 0.75)))
    Tile.alpha_composite(Picture, ((W - 104) // 2, 22))
    D = ImageDraw.Draw(Tile)
    Stars = STAR_COUNT[Rarity]
    DrawStars(D, (W - (Stars - 1) * 16 - 14) / 2, 134, Stars, 7, STAR_COLOR, 16)
    F = FitFont(pet["name"], W - 16, 17, 12, lines=1)
    D.text((W / 2, 156), Wrap(pet["name"], F, W - 16, 1)[0], font=F, fill=TEXT, anchor="ma")
    D.text((W / 2, 182), f"Nivel {pet['level']}", font=Font(14), fill=Light, anchor="ma")
    # Mini care bars.
    for i, Value in enumerate((pet["hunger"], pet["happiness"])):
        Y = 206 + i * 10
        D.rounded_rectangle((16, Y, W - 16, Y + 5), radius=3, fill=(255, 255, 255, 40))
        D.rounded_rectangle((16, Y, 16 + max(6, (W - 32) * Value / 100), Y + 5), radius=3, fill=StatusColor(Value))
    Masked = Image.new("RGBA", size, (0, 0, 0, 0))
    Masked.paste(Tile, (0, 0), Rounded(size, 16))
    ImageDraw.Draw(Masked).rounded_rectangle((1, 1, W - 2, H - 2), radius=16, outline=(STAR_COLOR if pet.get("active") else Main) + (255,), width=4 if pet.get("active") else 2)
    if pet.get("active"):
        D = ImageDraw.Draw(Masked)
        D.rounded_rectangle((8, 8, 70, 28), radius=10, fill=(205, 150, 30))
        D.text((39, 18), "ACTIVA", font=Font(11), fill=TEXT, anchor="mm")
    return Masked


ALBUM_COLUMNS = 5
ALBUM_TILE = (170, 236)


def AlbumCard(pets: list[dict], owner: str) -> bytes:
    """All of someone's pets, best first (the active one leads)."""
    Cols = min(ALBUM_COLUMNS, max(1, len(pets)))
    Rows = max(1, math.ceil(len(pets) / ALBUM_COLUMNS))
    Gap, Pad, Top = 14, 26, 78
    W = Pad * 2 + Cols * ALBUM_TILE[0] + (Cols - 1) * Gap
    W = max(W, 520)
    H = Top + Rows * ALBUM_TILE[1] + (Rows - 1) * Gap + Pad
    Canvas = Radial((W, H), (W / 2, 0), W, (40, 46, 90), BG_TOP).convert("RGBA")
    D = ImageDraw.Draw(Canvas)
    D.text((Pad, 26), f"Mascotas de {owner}", font=Font(26), fill=TEXT)
    D.text((W - Pad, 38), f"{len(pets)} en la colección", font=Font(16, bold=False), fill=TEXT_SECONDARY, anchor="rm")
    Order = ["legendary", "epic", "rare", "common"]
    Sorted = sorted(pets, key=lambda P: (not P.get("active"), Order.index(P["rarity"]), -P["level"]))
    Offset = (W - (Cols * ALBUM_TILE[0] + (Cols - 1) * Gap)) // 2
    for i, Pet in enumerate(Sorted):
        X = Offset + (i % ALBUM_COLUMNS) * (ALBUM_TILE[0] + Gap)
        Y = Top + (i // ALBUM_COLUMNS) * (ALBUM_TILE[1] + Gap)
        Canvas.alpha_composite(AlbumTile(Pet, ALBUM_TILE), (X, Y))
    Buffer = io.BytesIO()
    Canvas.convert("RGB").save(Buffer, "PNG", optimize=True)
    return Buffer.getvalue()


# ---------------- evolution animation ----------------


def Silhouette(picture: Image.Image, color, strength: float) -> Image.Image:
    """The picture tinted towards a flat color (strength 0-1)."""
    Flat = Image.new("RGBA", picture.size, color + (255,))
    Flat.putalpha(picture.getchannel("A"))
    return Image.blend(picture, Flat, max(0.0, min(1.0, strength)))


def EvolutionGif(old: dict, new: dict) -> bytes:
    """old/new: name, emoji, rarity. The old form glows, turns to light, bursts, and the new one appears."""
    W, H = EVO_SIZE
    Center = (W / 2, H / 2 - 6)
    OldColor, NewColor = PALETTE[old["rarity"]][1], PALETTE[new["rarity"]][1]
    Size = 150
    OldPic = Icon(old.get("emoji"), old["name"], old["rarity"], Size)
    NewPic = Icon(new.get("emoji"), new["name"], new["rarity"], Size)
    Rng = random.Random(f"{old['name']}>{new['name']}")
    Particles = [[Center[0], Center[1], math.cos(A) * V, math.sin(A) * V] for A, V in ((Rng.uniform(0, math.tau), Rng.uniform(2, 7)) for _ in range(70))]
    Frames = []
    Base = Radial((W, H), Center, W * 0.7, (34, 38, 78), BG_TOP).convert("RGBA")
    for F in range(EVO_FRAMES):
        T = F / (EVO_FRAMES - 1)
        Frame = Base.copy()
        Light = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        L = ImageDraw.Draw(Light)
        if T < 0.45:
            # The old form pulses brighter and brighter, turning into light.
            K = T / 0.45
            Pulse = 0.5 + 0.5 * math.sin(K * math.pi * 6)
            R = 80 + 40 * K + 10 * Pulse
            L.ellipse((Center[0] - R, Center[1] - R, Center[0] + R, Center[1] + R), fill=OldColor + (int(90 + 120 * K),))
            Frame = Image.alpha_composite(Frame, Glow(Light, 25))
            Pic = Silhouette(OldPic, (255, 255, 255), K**1.5)
            Scale = 1 + 0.06 * Pulse * K
            Pic = Pic.resize((int(Size * Scale), int(Size * Scale)), Image.LANCZOS)
            Frame.alpha_composite(Pic, (int(Center[0] - Pic.width / 2), int(Center[1] - Pic.height / 2)))
        elif T < 0.65:
            # Burst of light.
            K = (T - 0.45) / 0.2
            Rays = 16
            Length = 60 + 320 * K
            for i in range(Rays):
                A = i * math.tau / Rays + K
                L.polygon(
                    [Center, (Center[0] + math.cos(A - 0.06) * Length, Center[1] + math.sin(A - 0.06) * Length), (Center[0] + math.cos(A + 0.06) * Length, Center[1] + math.sin(A + 0.06) * Length)],
                    fill=NewColor + (200,),
                )
            R = 70 + 260 * K
            L.ellipse((Center[0] - R, Center[1] - R, Center[0] + R, Center[1] + R), fill=(255, 255, 255, int(255 * (1 - K * 0.3))))
            Frame = Image.alpha_composite(Frame, Glow(Light, 10))
        else:
            # The new form appears out of the light and settles.
            K = (T - 0.65) / 0.35
            Ease = 1 - (1 - K) ** 3
            R = 95
            L.ellipse((Center[0] - R, Center[1] - R, Center[0] + R, Center[1] + R), fill=NewColor + (170,))
            Sharp = ImageDraw.Draw(Light)
            for P in Particles:
                P[0] += P[2]
                P[1] += P[3]
                P[3] += 0.08
                Size_ = 2.5 * (1 - K) + 0.5
                Sharp.ellipse((P[0] - Size_, P[1] - Size_, P[0] + Size_, P[1] + Size_), fill=(255, 255, 255, int(255 * (1 - K))))
            Frame = Image.alpha_composite(Frame, Glow(Light, 14))
            Pic = Silhouette(NewPic, (255, 255, 255), (1 - K) ** 2)
            Scale = 0.6 + 0.4 * Ease + 0.05 * math.sin(K * math.pi)
            Pic = Pic.resize((int(Size * Scale), int(Size * Scale)), Image.LANCZOS)
            Frame.alpha_composite(Pic, (int(Center[0] - Pic.width / 2), int(Center[1] - Pic.height / 2)))
            if K > 0.3:
                D = ImageDraw.Draw(Frame)
                Alpha = int(255 * min(1.0, (K - 0.3) / 0.4))
                D.text((W / 2, H - 30), f"¡{new['name']}!", font=Font(24), fill=(255, 255, 255, Alpha), anchor="mm")
        if 0.62 <= T < 0.72:
            Frame = Image.alpha_composite(Frame, Image.new("RGBA", (W, H), (255, 255, 255, int(230 * (1 - (T - 0.62) / 0.1)))))
        Frames.append(Frame.convert("RGB"))
    Sample = Image.new("RGB", (W * 3, H))
    for i, F in enumerate((Frames[5], Frames[int(EVO_FRAMES * 0.55)], Frames[-1])):
        Sample.paste(F, (i * W, 0))
    Palette = Sample.quantize(colors=200, method=Image.Quantize.MEDIANCUT)
    Indexed = [F.quantize(palette=Palette, dither=Image.Dither.FLOYDSTEINBERG) for F in Frames]
    Buffer = io.BytesIO()
    Indexed[0].save(
        Buffer, "GIF", save_all=True, append_images=Indexed[1:],
        duration=[EVO_FRAME_MS] * (len(Indexed) - 1) + [EVO_LAST_MS], loop=0, optimize=True, disposal=1,
    )
    return Buffer.getvalue()
