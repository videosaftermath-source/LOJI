"""Stats chart for /eco-admin stats, drawn with Pillow (dark theme, validated palette)."""

import io
from datetime import date

from PIL import Image, ImageDraw

from core.economy.cards import Font

WIDTH, HEIGHT = 1000, 640
PAD = 56
SURFACE = (26, 26, 25)
TEXT = (240, 239, 236)
TEXT_SECONDARY = (195, 194, 183)
TEXT_MUTED = (138, 137, 132)
GRID = (48, 48, 46)
SERIES_1 = (57, 135, 229)  # blue: money in circulation / created
SERIES_2 = (217, 89, 38)  # orange: destroyed
LINE = 3
MARKER = 6
BAR_GAP = 2
GRID_LINES = 4
MONTHS = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]


def Short(value: float) -> str:
    Sign = "-" if value < 0 else ""
    Value = abs(value)
    for Limit, Suffix in ((1e9, "B"), (1e6, "M"), (1e3, "k")):
        if Value >= Limit:
            return f"{Sign}{Value / Limit:.1f}".rstrip("0").rstrip(".") + Suffix
    return f"{Sign}{int(Value)}"


def DayLabel(day: str) -> str:
    D = date.fromisoformat(day)
    return f"{D.day} {MONTHS[D.month - 1]}"


def Nice(maximum: float) -> float:
    """A round axis top above `maximum`."""
    if maximum <= 0:
        return 1
    Power = 10 ** (len(str(int(maximum))) - 1)
    for Step in (1, 2, 2.5, 5, 10):
        if Step * Power >= maximum:
            return Step * Power
    return 10 * Power


def Axis(draw: ImageDraw.ImageDraw, box, top_value: float):
    """Recessive horizontal grid with muted labels."""
    Left, Top, Right, Bottom = box
    for i in range(GRID_LINES + 1):
        Y = Bottom - (Bottom - Top) * i / GRID_LINES
        draw.line([(Left, Y), (Right, Y)], fill=GRID, width=1)
        draw.text((Left - 8, Y), Short(top_value * i / GRID_LINES), font=Font(13, bold=False), fill=TEXT_MUTED, anchor="rm")


def XLabels(draw: ImageDraw.ImageDraw, days: list[str], xs: list[float], y: float):
    Every = 1 if len(days) <= 7 else 2
    for i, (Day, X) in enumerate(zip(days, xs)):
        # The last day always gets a label, unless it would touch the previous one.
        IsLast = i == len(days) - 1 and (i - 1) % Every != 0
        if i % Every == 0 or IsLast:
            draw.text((X, y), DayLabel(Day), font=Font(12, bold=False), fill=TEXT_MUTED, anchor="mt")


def StatsChart(history: list[dict], currency: str) -> bytes:
    Image_ = Image.new("RGB", (WIDTH, HEIGHT), SURFACE)
    D = ImageDraw.Draw(Image_)
    D.text((PAD - 20, 22), f"Economía · últimos {len(history)} días", font=Font(22), fill=TEXT)
    Days = [H["date"] for H in history]
    if not history:
        D.text((WIDTH / 2, HEIGHT / 2), "Todavía no hay datos: vuelve mañana.", font=Font(18, bold=False), fill=TEXT_SECONDARY, anchor="mm")
        return Save(Image_)

    Left, Right = PAD + 20, WIDTH - PAD

    def Xs(count):
        if count == 1:
            return [(Left + Right) / 2]
        return [Left + (Right - Left) * i / (count - 1) for i in range(count)]

    # ---- panel 1: money in circulation (one series: the title names it, no legend) ----
    Top1, Bottom1 = 96, 300
    D.text((PAD - 20, 66), f"{currency} en circulación", font=Font(16), fill=TEXT_SECONDARY)
    Supply = [max(0, int(H.get("supply", 0))) for H in history]
    Top = Nice(max(Supply) * 1.1)
    Axis(D, (Left, Top1, Right, Bottom1), Top)
    X1 = Xs(len(Supply))
    Points = [(X, Bottom1 - (Bottom1 - Top1) * V / Top) for X, V in zip(X1, Supply)]
    if len(Points) > 1:
        D.line(Points, fill=SERIES_1, width=LINE, joint="curve")
    Last = Points[-1]
    # Ring in the surface color so the marker reads on top of the line.
    D.ellipse((Last[0] - MARKER - 2, Last[1] - MARKER - 2, Last[0] + MARKER + 2, Last[1] + MARKER + 2), fill=SURFACE)
    D.ellipse((Last[0] - MARKER, Last[1] - MARKER, Last[0] + MARKER, Last[1] + MARKER), fill=SERIES_1)
    D.text((Last[0] - 12, Last[1] - 14), Short(Supply[-1]), font=Font(15), fill=TEXT, anchor="rb")
    XLabels(D, Days, X1, Bottom1 + 8)

    # ---- panel 2: created vs destroyed per day (two series: legend + direct identity) ----
    Top2, Bottom2 = 390, 590
    D.text((PAD - 20, 356), "Creado vs destruido por día", font=Font(16), fill=TEXT_SECONDARY)
    Created = [max(0, int(H.get("created", 0))) for H in history]
    Destroyed = [max(0, int(H.get("destroyed", 0)) + int(H.get("taxes", 0)) + int(H.get("casino", 0))) for H in history]
    Top = Nice(max(Created + Destroyed + [1]) * 1.1)
    Axis(D, (Left, Top2, Right, Bottom2), Top)
    Slot = (Right - Left) / len(history)
    BarWidth = max(4, min(26, (Slot - 10) / 2))
    Centers = [Left + Slot * (i + 0.5) for i in range(len(history))]
    for X, C, Dd in zip(Centers, Created, Destroyed):
        for Offset, Value, Color in ((-BarWidth / 2 - BAR_GAP / 2, C, SERIES_1), (BarWidth / 2 + BAR_GAP / 2, Dd, SERIES_2)):
            Height = (Bottom2 - Top2) * Value / Top
            if Height < 1:
                continue
            X0, X1_ = X + Offset - BarWidth / 2, X + Offset + BarWidth / 2
            # Rounded data end at the top, square at the baseline.
            D.rounded_rectangle((X0, Bottom2 - Height, X1_, Bottom2), radius=min(4, Height / 2, BarWidth / 2), fill=Color)
            D.rectangle((X0, Bottom2 - min(Height, 4), X1_, Bottom2), fill=Color)
    XLabels(D, Days, Centers, Bottom2 + 8)
    # Legend (top right of the panel), text in text colors, swatch carries identity.
    X = Right
    for Label, Color in (("Destruido", SERIES_2), ("Creado", SERIES_1)):
        Width = Font(14, bold=False).getlength(Label)
        D.text((X, 366), Label, font=Font(14, bold=False), fill=TEXT_SECONDARY, anchor="rm")
        D.rounded_rectangle((X - Width - 22, 359, X - Width - 8, 373), radius=3, fill=Color)
        X -= Width + 40
    return Save(Image_)


def Save(image: Image.Image) -> bytes:
    Out = io.BytesIO()
    image.save(Out, "PNG", optimize=True)
    return Out.getvalue()
