"""/horario anime: the week's streams as one decorated image (dark plum, gold details, a column per day)."""

import io

from PIL import Image, ImageDraw, ImageFilter

from core.anime import DAYS
from core.gradient_art import BOLD, SEMI, Font

BG = (22, 12, 20)
CARD = (44, 26, 40)
CARD_EDGE = (92, 62, 82)
GOLD = (214, 186, 140)
TEXT = (245, 238, 242)
SOFT = (190, 172, 184)
ACCENTS = [(255, 95, 143), (91, 75, 255), (62, 230, 255), (0, 255, 163), (255, 154, 92), (143, 91, 255), (232, 176, 74)]


def Wrap(draw, text: str, font, width: int, lines: int = 2) -> list[str]:
    Words, Out, Line = text.split(), [], ""
    for W in Words:
        Try = f"{Line} {W}".strip()
        if draw.textlength(Try, font=font) <= width:
            Line = Try
        else:
            if Line:
                Out.append(Line)
            Line = W
        if len(Out) == lines:
            break
    if Line and len(Out) < lines:
        Out.append(Line)
    if len(Out) == lines and " ".join(Out) != text:
        while Out[-1] and draw.textlength(Out[-1] + "…", font=font) > width:
            Out[-1] = Out[-1][:-1]
        Out[-1] += "…"
    return Out


def Schedule(shows: list[dict], server: str, names: dict[int, str], scale: int = 2) -> bytes:
    """shows: {title, day, hour, minute, streamer, episode, total}. Monday to Friday, plus the weekend if it has shows."""
    Days = list(range(5)) + [D for D in (5, 6) if any(S["day"] == D for S in shows)]
    Col, Gap, Pad, Head = 300 * scale, 16 * scale, 40 * scale, 150 * scale
    CardH = 128 * scale
    ByDay = {D: sorted((S for S in shows if S["day"] == D), key=lambda S: (S["hour"], S["minute"])) for D in Days}
    Rows = max([len(V) for V in ByDay.values()] + [1])
    W = Pad * 2 + Col * len(Days) + Gap * (len(Days) - 1)
    H = Head + 70 * scale + Rows * (CardH + Gap) + Pad
    Canvas = Image.new("RGB", (W, H), BG)
    Glow = Image.new("RGB", (W, H), BG)
    ImageDraw.Draw(Glow).ellipse((W * 0.1, -H * 0.4, W * 0.9, H * 0.45), fill=(70, 26, 54))
    Canvas = Image.blend(Canvas, Glow.filter(ImageFilter.GaussianBlur(140 * scale)), 0.9).convert("RGBA")
    D = ImageDraw.Draw(Canvas)
    TitleF, SubF, DayF = Font(BOLD, 46 * scale), Font(SEMI, 18 * scale), Font(BOLD, 22 * scale)
    TimeF, ShowF, SmallF = Font(BOLD, 26 * scale), Font(BOLD, 19 * scale), Font(SEMI, 14 * scale)
    D.text((Pad, Pad), "HORARIO DE ANIME", font=TitleF, fill=GOLD)
    D.text((Pad + 2 * scale, Pad + 58 * scale), f"{server} · transmisiones en el auditorio".upper(), font=SubF, fill=SOFT)
    D.line((Pad, Head - 18 * scale, W - Pad, Head - 18 * scale), fill=(120, 92, 70), width=2 * scale)
    for I, Day in enumerate(Days):
        X = Pad + I * (Col + Gap)
        D.text((X + Col / 2, Head + 18 * scale), DAYS[Day].upper(), font=DayF, fill=TEXT, anchor="mm")
        D.line((X + Col * 0.3, Head + 38 * scale, X + Col * 0.7, Head + 38 * scale), fill=GOLD, width=2 * scale)
        Shows = ByDay[Day]
        if not Shows:
            Y = Head + 70 * scale
            D.rounded_rectangle((X, Y, X + Col, Y + CardH), radius=18 * scale, outline=(60, 40, 55), width=2 * scale)
            D.text((X + Col / 2, Y + CardH / 2), "Sin transmisión", font=SmallF, fill=(130, 110, 125), anchor="mm")
            continue
        for J, S in enumerate(Shows):
            Y = Head + 70 * scale + J * (CardH + Gap)
            Accent = ACCENTS[(Day + J) % len(ACCENTS)]
            D.rounded_rectangle((X, Y, X + Col, Y + CardH), radius=18 * scale, fill=CARD, outline=CARD_EDGE, width=2 * scale)
            D.rounded_rectangle((X, Y, X + 8 * scale, Y + CardH), radius=4 * scale, fill=Accent)
            D.text((X + 24 * scale, Y + 26 * scale), f"{S['hour']:02d}:{S['minute']:02d}", font=TimeF, fill=Accent, anchor="lm")
            for K, Line in enumerate(Wrap(D, S["title"], ShowF, Col - 44 * scale)):
                D.text((X + 24 * scale, Y + 56 * scale + K * 23 * scale), Line, font=ShowF, fill=TEXT, anchor="lm")
            Ep = int(S.get("episode") or 1)
            Total = S.get("total")
            Who = names.get(S.get("streamer") or 0, "Sin encargado")
            D.text((X + 24 * scale, Y + CardH - 18 * scale), f"{Who[:18]}  ·  EP {Ep}" + (f"/{Total}" if Total else ""), font=SmallF, fill=SOFT, anchor="lm")
            if Total:
                Bar = X + Col - 24 * scale
                Left = Bar - 70 * scale
                Done = min(1.0, (Ep - 1) / max(1, int(Total)))
                D.rounded_rectangle((Left, Y + 20 * scale, Bar, Y + 30 * scale), radius=5 * scale, fill=(70, 50, 66))
                if Done > 0:
                    D.rounded_rectangle((Left, Y + 20 * scale, Left + (Bar - Left) * Done, Y + 30 * scale), radius=5 * scale, fill=Accent)
    Out = io.BytesIO()
    Canvas.convert("RGB").save(Out, "PNG", optimize=True)
    return Out.getvalue()
