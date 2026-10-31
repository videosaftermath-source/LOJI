"""
Builds the starter pets' pictures from game-icons.net silhouettes (CC BY 3.0), tinted by rarity.
Dev-only (needs cairosvg and internet):  python tools/pet_icons.py
"""

import io
import os
import subprocess
import sys

import cairosvg
from PIL import Image, ImageChops, ImageFilter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.economy.pet_catalog import STARTER_SPECIES  # noqa: E402

SIZE = 512
ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "pets")
ICONS = {
    "hamster": "lorc/seated-mouse", "beaver": "delapouite/beaver", "ox": "delapouite/charging-bull", "dragon": "lorc/dragon-head",
    "parrot": "lorc/parrot-head", "penguin": "delapouite/penguin", "dolphin": "delapouite/dolphin",
    "eagle": "delapouite/eagle-head", "blackcat": "lorc/cat", "bunny": "delapouite/rabbit", "fox": "lorc/fox-head",
    "unicorn": "delapouite/unicorn", "squirrel": "delapouite/squirrel", "raccoon": "delapouite/raccoon-head",
    "owl": "lorc/owl", "turtle": "lorc/turtle", "wolf": "lorc/wolf-howl", "shiba": "delapouite/sitting-dog",
}
# rarity -> (top color, bottom color)
GRADIENTS = {
    "common": ((236, 240, 246), (150, 162, 180)),
    "rare": ((150, 210, 255), (40, 110, 225)),
    "epic": ((225, 170, 255), (130, 60, 215)),
    "legendary": ((255, 236, 140), (226, 150, 20)),
}
OUTLINE = (24, 16, 22, 255)
BORDER = 10  # outline thickness in px


def Silhouette(path: str) -> Image.Image:
    Svg = subprocess.run(["curl", "-sS", "-m", "20", f"https://raw.githubusercontent.com/game-icons/icons/master/{path}.svg"],
                         capture_output=True, check=True).stdout
    Png = cairosvg.svg2png(bytestring=Svg, output_width=SIZE, output_height=SIZE)
    return Image.open(io.BytesIO(Png)).convert("L")  # white shape on black = the mask


def Tinted(mask: Image.Image, rarity: str) -> Image.Image:
    Top, Bottom = GRADIENTS[rarity]
    Gradient = Image.new("RGBA", (SIZE, SIZE))
    for Y in range(SIZE):
        T = Y / SIZE
        Gradient.paste(tuple(int(Top[i] + (Bottom[i] - Top[i]) * T) for i in range(3)) + (255,), (0, Y, SIZE, Y + 1))
    Out = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    Thick = mask.filter(ImageFilter.MaxFilter(BORDER * 2 + 1))  # dark outline around the shape
    Out.paste(Image.new("RGBA", (SIZE, SIZE), OUTLINE), (0, 0), Thick)
    Out.paste(Gradient, (0, 0), mask)
    Shine = ImageChops.multiply(mask, Image.linear_gradient("L").rotate(180).resize((SIZE, SIZE)).point(lambda v: v // 4))
    Out.paste(Image.new("RGBA", (SIZE, SIZE), (255, 255, 255, 255)), (0, 0), Shine)  # soft light from the top
    return Out.crop(Out.getbbox())


if __name__ == "__main__":
    Rarity = {Row[0]: Row[3] for Row in STARTER_SPECIES}
    for Key, Path in ICONS.items():
        Tinted(Silhouette(Path), Rarity[Key]).save(os.path.join(ROOT, f"{Key}.png"), optimize=True)
    print(f"{len(ICONS)} pet icons saved in {ROOT}")
