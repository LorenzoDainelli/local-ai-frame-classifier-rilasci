from __future__ import annotations

import math

from PIL import Image, ImageDraw

SCHEMA = ((-0.35, -0.25), (0.35, -0.25), (0.0, 0.05),
          (-0.28, 0.40), (0.28, 0.40))

CARNAGIONI = ((236, 205, 178), (214, 170, 133), (172, 124, 92),
              (120, 84, 62), (247, 224, 205))


def disegna(misura=(400, 400), centro=(200, 200), raggio: float = 120.0,
            gradi: float = 0.0, colore=None):
    if colore is None:
        colore = CARNAGIONI[0]
    lato = max(8, int(raggio * 4))
    foglietto = Image.new("RGBA", (lato, lato), (0, 0, 0, 0))
    disegno = ImageDraw.Draw(foglietto)
    meta = lato / 2

    disegno.ellipse([meta - raggio * 0.75, meta - raggio,
                     meta + raggio * 0.75, meta + raggio], fill=colore + (255,))
    punto = max(2.0, raggio * 0.075)
    for indice, (fx, fy) in enumerate(SCHEMA):
        x, y = meta + fx * raggio, meta + fy * raggio
        tinta = (30, 60, 200) if indice < 2 else (180, 40, 40)
        disegno.ellipse([x - punto, y - punto, x + punto, y + punto],
                        fill=tinta + (255,))

    girato = foglietto.rotate(-gradi, resample=Image.BICUBIC)
    immagine = Image.new("RGB", misura, (24, 24, 32))
    immagine.paste(girato, (int(centro[0] - meta), int(centro[1] - meta)), girato)

    radianti = math.radians(gradi)
    coseno, seno = math.cos(radianti), math.sin(radianti)
    punti = []
    for fx, fy in SCHEMA:
        x, y = fx * raggio, fy * raggio
        punti.append((centro[0] + x * coseno - y * seno,
                      centro[1] + x * seno + y * coseno))
    return immagine, punti


def una_manciata(quante: int = 8, misura=(320, 320)):
    fuori = []
    for indice in range(quante):
        gradi = -30.0 + indice * (60.0 / max(1, quante - 1))
        raggio = misura[0] * (0.20 + 0.06 * ((indice % 3) / 2.0))
        centro = (misura[0] / 2 + (indice % 3 - 1) * misura[0] * 0.07,
                  misura[1] / 2 + (indice % 2 - 0.5) * misura[1] * 0.06)
        immagine, punti = disegna(
            misura=misura, centro=centro, raggio=raggio, gradi=gradi,
            colore=CARNAGIONI[indice % len(CARNAGIONI)])
        fuori.append((round(gradi, 1), immagine, punti))
    return fuori
