"""
Draws the starter pets (flat chibi heads, same style as the Shiba) into assets/pets/<id>.png.
Run once after changing a design:  python tools/draw_pets.py
"""

import math
import os

from PIL import Image, ImageDraw

K = 4  # supersampling
SIZE = 512
OUT = (52, 30, 22, 255)
WHITE = (255, 255, 255, 255)
CREAM = (255, 244, 226, 255)
PINK = (255, 150, 160, 255)
BLUSH = (255, 140, 150, 200)
GOLD = (246, 196, 72, 255)
LW = 9
ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "pets")


class Pen:
    def __init__(self):
        self.img = Image.new("RGBA", (SIZE * K, SIZE * K), (0, 0, 0, 0))
        self.d = ImageDraw.Draw(self.img)

    def s(self, v):
        return [int(x * K) for x in v]

    def ell(self, box, fill, outline=True, width=LW):
        if outline:
            b = box
            self.d.ellipse(self.s((b[0] - width, b[1] - width, b[2] + width, b[3] + width)), fill=OUT)
        self.d.ellipse(self.s(box), fill=fill)

    def poly(self, pts, fill, outline=True, width=LW):
        P = [(x * K, y * K) for x, y in pts]
        if outline:
            self.d.polygon(P, fill=OUT)
            self.d.line(P + [P[0]], fill=OUT, width=width * 2 * K, joint="curve")
        self.d.polygon(P, fill=fill)

    def line(self, pts, fill=OUT, width=6):
        self.d.line([(x * K, y * K) for x, y in pts], fill=fill, width=width * K, joint="curve")

    def arc(self, box, a, b, fill=OUT, width=6):
        self.d.arc(self.s(box), a, b, fill=fill, width=width * K)

    def rect(self, box, fill, radius=0, outline=True):
        if outline:
            self.d.rounded_rectangle(self.s((box[0] - LW, box[1] - LW, box[2] + LW, box[3] + LW)), radius=(radius + LW) * K, fill=OUT)
        self.d.rounded_rectangle(self.s(box), radius=radius * K, fill=fill)


def Face(p: Pen, eye_y=235, eye_dx=66, eye_color=OUT, mouth="w", nose=True, blush=True, cx=256, eye_r=22):
    for X in (cx - eye_dx, cx + eye_dx):
        p.ell((X - eye_r, eye_y - eye_r - 4, X + eye_r, eye_y + eye_r + 4), eye_color, outline=eye_color != OUT, width=4)
        if eye_color != OUT:
            p.ell((X - 9, eye_y - 12, X + 9, eye_y + 14), OUT, outline=False)
        p.ell((X - 10, eye_y - 16, X + 3, eye_y - 3), WHITE, outline=False)
    if blush:
        p.ell((cx - eye_dx - 58, eye_y + 30, cx - eye_dx - 10, eye_y + 56), BLUSH, outline=False)
        p.ell((cx + eye_dx + 10, eye_y + 30, cx + eye_dx + 58, eye_y + 56), BLUSH, outline=False)
    Y = eye_y + 40
    if nose:
        p.rect((cx - 17, Y, cx + 17, Y + 20), OUT, radius=9, outline=False)
    if mouth == "w":
        p.arc((cx - 34, Y + 10, cx + 2, Y + 44), 20, 160)
        p.arc((cx - 2, Y + 10, cx + 34, Y + 44), 20, 160)
    elif mouth == "smile":
        p.arc((cx - 26, Y + 4, cx + 26, Y + 40), 20, 160)


def Save(p: Pen, name: str):
    Img = p.img.resize((SIZE, SIZE), Image.LANCZOS)
    Img = Img.crop(Img.getbbox())
    Img.save(os.path.join(ROOT, f"{name}.png"), optimize=True)


# ---------------- designs ----------------


def hamster():
    p = Pen(); C = (233, 161, 90, 255)
    p.ell((110, 110, 190, 190), C); p.ell((322, 110, 402, 190), C)
    p.ell((130, 130, 170, 170), PINK, outline=False); p.ell((342, 130, 382, 170), PINK, outline=False)
    p.ell((70, 140, 442, 440), C)
    p.ell((90, 270, 250, 420), CREAM, outline=False); p.ell((262, 270, 422, 420), CREAM, outline=False)
    p.ell((190, 250, 322, 400), CREAM, outline=False)
    Face(p, eye_y=250); Save(p, "hamster")


def beaver():
    p = Pen(); C = (150, 98, 60, 255)
    p.ell((110, 120, 180, 190), C); p.ell((332, 120, 402, 190), C)
    p.ell((70, 140, 442, 430), C)
    p.ell((170, 270, 342, 410), (214, 170, 128, 255), outline=False)
    Face(p, eye_y=240, mouth=None)
    p.rect((232, 330, 254, 372), WHITE, radius=4); p.rect((258, 330, 280, 372), WHITE, radius=4)
    p.arc((214, 300, 298, 340), 20, 160)
    Save(p, "beaver")


def ox():
    p = Pen(); C = (110, 72, 46, 255); Horn = (245, 233, 210, 255)
    p.poly([(120, 170), (60, 110), (40, 40), (95, 90), (150, 140)], Horn)
    p.poly([(392, 170), (452, 110), (472, 40), (417, 90), (362, 140)], Horn)
    p.poly([(80, 210), (20, 200), (50, 250), (110, 250)], C); p.poly([(432, 210), (492, 200), (462, 250), (402, 250)], C)
    p.ell((80, 130, 432, 430), C)
    p.ell((150, 300, 362, 440), (232, 178, 160, 255))
    p.ell((200, 345, 225, 375), OUT, outline=False); p.ell((287, 345, 312, 375), OUT, outline=False)
    p.arc((236, 372, 276, 412), 0, 360, fill=GOLD, width=7)  # nose ring
    Face(p, eye_y=235, nose=False, mouth=None); Save(p, "ox")


def dragon():
    p = Pen(); C = (76, 175, 80, 255); Belly = (255, 226, 140, 255)
    p.poly([(150, 160), (110, 40), (190, 130)], GOLD); p.poly([(362, 160), (402, 40), (322, 130)], GOLD)
    for x in (226, 256, 286):
        p.poly([(x - 16, 140), (x, 95), (x + 16, 140)], (56, 142, 60, 255))
    p.ell((70, 120, 442, 430), C)
    p.ell((160, 290, 352, 430), Belly)
    p.ell((215, 335, 232, 352), OUT, outline=False); p.ell((280, 335, 297, 352), OUT, outline=False)
    p.arc((216, 360, 296, 410), 20, 160)
    Face(p, eye_y=235, nose=False, mouth=None); Save(p, "dragon")


def parrot():
    p = Pen(); C = (59, 181, 74, 255)
    for i, Col in enumerate([(230, 57, 70, 255), (255, 183, 3, 255), (230, 57, 70, 255)]):
        p.poly([(220 + i * 30, 140), (200 + i * 40, 50), (250 + i * 30, 130)], Col)
    p.ell((80, 110, 432, 440), C)
    p.ell((150, 230, 362, 420), (170, 230, 120, 255), outline=False)
    Face(p, eye_y=230, nose=False, mouth=None)
    p.poly([(206, 290), (306, 290), (300, 330), (256, 390), (214, 330)], GOLD)
    p.line([(212, 318), (300, 318)], width=5)
    Save(p, "parrot")


def penguin():
    p = Pen(); C = (43, 45, 66, 255)
    p.ell((80, 110, 432, 450), C)
    p.ell((120, 190, 262, 420), WHITE, outline=False); p.ell((250, 190, 392, 420), WHITE, outline=False)
    Face(p, eye_y=270, nose=False, mouth=None)
    p.poly([(226, 320), (286, 320), (256, 362)], (255, 152, 0, 255))
    Save(p, "penguin")


def dolphin():
    p = Pen(); C = (79, 163, 224, 255)
    p.poly([(236, 130), (290, 40), (300, 140)], C)
    p.ell((70, 110, 442, 420), C)
    p.ell((150, 270, 362, 412), (190, 228, 250, 255), outline=False)
    Face(p, eye_y=230, nose=False, mouth="smile", cx=270)
    Save(p, "dolphin")


def eagle():
    p = Pen(); Brown = (121, 85, 61, 255)
    p.ell((50, 260, 462, 480), Brown)
    p.ell((90, 90, 422, 410), WHITE)
    p.line([(150, 200), (220, 222)], width=12); p.line([(362, 200), (292, 222)], width=12)
    Face(p, eye_y=250, nose=False, mouth=None, blush=False)
    p.poly([(216, 300), (296, 300), (296, 340), (256, 400), (236, 360)], GOLD)
    Save(p, "eagle")


def blackcat():
    p = Pen(); C = (46, 46, 58, 255)
    p.poly([(100, 220), (110, 70), (220, 150)], C); p.poly([(412, 220), (402, 70), (292, 150)], C)
    p.poly([(130, 190), (135, 105), (195, 150)], PINK, outline=False); p.poly([(382, 190), (377, 105), (317, 150)], PINK, outline=False)
    p.ell((70, 120, 442, 420), C)
    Face(p, eye_y=245, eye_color=(196, 230, 70, 255), nose=False, mouth="w", eye_r=28)
    p.poly([(242, 290), (270, 290), (256, 304)], PINK, outline=False)
    for dy in (-10, 10):
        p.line([(90, 300 + dy), (170, 305 + dy)], fill=(200, 200, 210, 255), width=3)
        p.line([(422, 300 + dy), (342, 305 + dy)], fill=(200, 200, 210, 255), width=3)
    Save(p, "blackcat")


def bunny():
    p = Pen(); C = (244, 237, 228, 255)
    p.ell((150, 10, 220, 220), C); p.ell((292, 10, 362, 220), C)
    p.ell((168, 40, 202, 190), PINK, outline=False); p.ell((310, 40, 344, 190), PINK, outline=False)
    p.ell((80, 150, 432, 440), C)
    Face(p, eye_y=270, nose=False, mouth="w")
    p.poly([(240, 304), (272, 304), (256, 322)], PINK, outline=False)
    Save(p, "bunny")


def fox():
    p = Pen(); C = (232, 119, 46, 255)
    p.poly([(90, 230), (100, 50), (230, 150)], C); p.poly([(422, 230), (412, 50), (282, 150)], C)
    p.poly([(102, 110), (100, 50), (150, 85)], OUT, outline=False); p.poly([(410, 110), (412, 50), (362, 85)], OUT, outline=False)
    p.poly([(130, 200), (128, 115), (195, 150)], CREAM, outline=False); p.poly([(382, 200), (384, 115), (317, 150)], CREAM, outline=False)
    p.ell((70, 120, 442, 420), C)
    p.poly([(96, 290), (256, 405), (416, 290), (330, 330), (256, 300), (182, 330)], WHITE, outline=False)
    Face(p, eye_y=240); Save(p, "fox")


def unicorn():
    p = Pen(); C = (250, 246, 252, 255)
    for i, Col in enumerate([(255, 105, 180, 255), (255, 183, 3, 255), (100, 200, 255, 255), (170, 120, 255, 255)]):
        p.ell((300 + i * 22, 90 + i * 40, 440 + i * 18, 230 + i * 40), Col)
    p.ell((70, 130, 432, 440), C)
    p.poly([(226, 150), (256, 20), (286, 150)], GOLD)
    for y in (60, 95, 125):
        p.line([(256 - (150 - y) / 4.3, y), (256 + (150 - y) / 4.3, y + 8)], width=4)
    Face(p, eye_y=270, nose=False, mouth="smile")
    Save(p, "unicorn")


def squirrel():
    p = Pen(); C = (196, 106, 43, 255)
    p.poly([(120, 200), (120, 70), (200, 150)], C); p.poly([(392, 200), (392, 70), (312, 150)], C)
    p.poly([(120, 85), (100, 40), (140, 70)], C, outline=False); p.poly([(392, 85), (412, 40), (372, 70)], C, outline=False)
    p.ell((70, 130, 442, 420), C)
    p.ell((170, 260, 342, 410), CREAM, outline=False)
    Face(p, eye_y=240)
    p.ell((300, 360, 380, 450), (160, 110, 60, 255)); p.ell((296, 340, 384, 384), (110, 70, 40, 255))
    Save(p, "squirrel")


def raccoon():
    p = Pen(); C = (138, 143, 153, 255)
    p.ell((100, 110, 190, 200), C); p.ell((322, 110, 412, 200), C)
    p.ell((122, 132, 168, 178), (70, 72, 80, 255), outline=False); p.ell((344, 132, 390, 178), (70, 72, 80, 255), outline=False)
    p.ell((70, 140, 442, 430), C)
    p.ell((100, 200, 412, 290), (60, 62, 70, 255), outline=False)
    p.ell((170, 270, 342, 410), WHITE, outline=False)
    Face(p, eye_y=245, eye_color=WHITE, eye_r=24)
    Save(p, "raccoon")


def owl():
    p = Pen(); C = (141, 110, 99, 255)
    p.poly([(110, 190), (100, 70), (190, 140)], C); p.poly([(402, 190), (412, 70), (322, 140)], C)
    p.ell((70, 110, 442, 450), C)
    p.ell((260, 250, 440, 440), (215, 190, 170, 255), outline=False)
    p.ell((72, 250, 252, 440), (215, 190, 170, 255), outline=False)
    for X in (180, 332):
        p.ell((X - 62, 190, X + 62, 314), WHITE)
        p.ell((X - 30, 222, X + 30, 282), OUT, outline=False); p.ell((X - 18, 228, X - 2, 246), WHITE, outline=False)
        p.arc((X - 72, 180, X + 72, 324), 0, 360, fill=GOLD, width=8)
    p.line([(244, 250), (268, 250)], fill=GOLD, width=8)
    p.poly([(236, 320), (276, 320), (256, 360)], GOLD)
    Save(p, "owl")


def turtle():
    p = Pen(); C = (124, 179, 66, 255)
    p.ell((70, 150, 442, 440), C)
    p.rect((170, 40, 342, 150), (40, 40, 48, 255), radius=10)
    p.rect((140, 140, 372, 170), (40, 40, 48, 255), radius=8)
    p.rect((172, 112, 340, 132), GOLD, radius=2, outline=False)
    Face(p, eye_y=275, nose=False, mouth="smile")
    p.arc((290, 225, 380, 315), 0, 360, fill=GOLD, width=7)
    p.line([(378, 290), (400, 380)], fill=GOLD, width=4)
    Save(p, "turtle")


def wolf():
    p = Pen(); C = (120, 128, 145, 255); Light = (220, 224, 232, 255)
    p.ell((300, 20, 480, 200), (255, 236, 160, 255))  # full moon behind
    p.poly([(96, 230), (110, 60), (226, 150)], C); p.poly([(416, 230), (402, 60), (286, 150)], C)
    p.poly([(128, 200), (130, 110), (192, 152)], (80, 86, 100, 255), outline=False)
    p.poly([(384, 200), (382, 110), (320, 152)], (80, 86, 100, 255), outline=False)
    p.ell((70, 120, 442, 430), C)
    p.poly([(110, 300), (256, 425), (402, 300), (320, 320), (256, 280), (192, 320)], Light, outline=False)
    Face(p, eye_y=240, eye_color=(255, 200, 60, 255), eye_r=26)
    Save(p, "wolf")


DESIGNS = [wolf, hamster, beaver, ox, dragon, parrot, penguin, dolphin, eagle, blackcat, bunny, fox, unicorn, squirrel, raccoon, owl, turtle]

if __name__ == "__main__":
    for Draw in DESIGNS:
        Draw()
    print(f"{len(DESIGNS)} pets drawn into {ROOT}")
