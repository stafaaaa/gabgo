"""Erzeugt anna.ico (16–256 px) und anna.png aus einfachen Formen.

Große Größen zeigen Beleg, Zapfsäule, Excel-Tabelle und „Anna“; bis 48 px entfällt die Schrift,
damit Beleg und Zapfsäule groß und klar bleiben.
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HIER = Path(__file__).resolve().parent
N = 1024
HINTERGRUND = (22, 35, 46, 255)
PAPIER = (246, 248, 250, 255)
FALZ = (196, 206, 216, 255)
ORANGE = (247, 130, 30, 255)
GRUEN = (24, 158, 88, 255)
WEISS = (255, 255, 255, 255)
LINIE = (150, 165, 180, 255)
SCHRIFT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def zapfsaeule(d: ImageDraw.ImageDraw, x: float, y: float, s: float):
    d.rounded_rectangle((x, y + .12 * s, x + .56 * s, y + s), radius=.07 * s, fill=ORANGE)
    d.rounded_rectangle((x + .11 * s, y + .25 * s, x + .45 * s, y + .5 * s), radius=.04 * s, fill=PAPIER)
    d.rectangle((x - .07 * s, y + .9 * s, x + .63 * s, y + s), fill=ORANGE)
    w = int(.085 * s)
    d.line([(x + .5 * s, y + .36 * s), (x + .76 * s, y + .36 * s), (x + .88 * s, y + .5 * s),
            (x + .88 * s, y + .8 * s)], fill=ORANGE, width=w, joint="curve")
    r = w / 2
    for cx, cy in ((x + .76 * s, y + .36 * s), (x + .88 * s, y + .5 * s)):
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=ORANGE)
    d.rounded_rectangle((x + .82 * s, y + .74 * s, x + .94 * s, y + .9 * s), radius=.03 * s, fill=ORANGE)


def tabelle(d: ImageDraw.ImageDraw, x0: float, y0: float, s: float, rand: float):
    d.rounded_rectangle((x0 - rand, y0 - rand, x0 + s + rand, y0 + s + rand), radius=.16 * s + rand,
                        fill=HINTERGRUND)
    d.rounded_rectangle((x0, y0, x0 + s, y0 + s), radius=.16 * s, fill=GRUEN)
    w = max(int(.075 * s), 1)
    for i in (1, 2):
        d.line([(x0 + .12 * s, y0 + i * s / 3), (x0 + .88 * s, y0 + i * s / 3)], fill=WEISS, width=w)
        d.line([(x0 + i * s / 3, y0 + .12 * s), (x0 + i * s / 3, y0 + .88 * s)], fill=WEISS, width=w)


def beleg(d: ImageDraw.ImageDraw, x0, y0, x1, y1, falz):
    d.polygon([(x0, y0), (x1 - falz, y0), (x1, y0 + falz), (x1, y1), (x0, y1)], fill=PAPIER)
    d.polygon([(x1 - falz, y0), (x1 - falz, y0 + falz), (x1, y0 + falz)], fill=FALZ)


def zeichne(mit_name: bool) -> Image.Image:
    img = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, N - 1, N - 1), radius=200, fill=HINTERGRUND)
    if mit_name:
        beleg(d, 250, 90, 700, 700, 120)
        zapfsaeule(d, 320, 165, 300)
        for yy, breite in ((560, 190), (620, 140)):
            d.rounded_rectangle((310, yy, 310 + breite, yy + 26), radius=13, fill=LINIE)
        tabelle(d, 560, 450, 280, 26)
        font = ImageFont.truetype(SCHRIFT, 215)
        d.text((N / 2, 885), "Anna", font=font, fill=WEISS, anchor="mm")
    else:
        beleg(d, 150, 80, 740, 920, 170)
        zapfsaeule(d, 230, 190, 440)
        tabelle(d, 560, 560, 380, 34)
    return img


def main():
    gross, klein = zeichne(True), zeichne(False)
    groessen = [16, 20, 24, 32, 40, 48, 64, 96, 128, 256]
    bilder = [(klein if g <= 48 else gross).resize((g, g), Image.LANCZOS) for g in groessen]
    bilder[-1].save(HIER / "anna.ico", sizes=[(g, g) for g in groessen], append_images=bilder[:-1])
    gross.resize((256, 256), Image.LANCZOS).save(HIER / "anna.png")
    # Vorschau aller Größen nebeneinander (nicht Teil der App)
    vorschau = Image.new("RGBA", (sum(groessen) + 10 * len(groessen) + 10, 276), (235, 235, 235, 255))
    x = 10
    for g, b in zip(groessen, bilder):
        vorschau.paste(b, (x, 266 - g), b)
        x += g + 10
    return vorschau


if __name__ == "__main__":
    main().save("/tmp/anna_vorschau.png")
