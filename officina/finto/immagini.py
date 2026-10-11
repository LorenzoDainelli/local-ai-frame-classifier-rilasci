from __future__ import annotations

import io
import math
import random

from PIL import Image, ImageDraw

TEMI = {
    "tema_a": [(28, 44, 78), (52, 96, 148), (120, 170, 200)],
    "tema_b": [(84, 32, 28), (168, 92, 48), (222, 176, 108)],
    "tema_c": [(24, 56, 36), (68, 116, 62), (168, 190, 120)],
    "tema_d": [(46, 30, 60), (110, 70, 130), (196, 158, 210)],
    "tema_e": [(70, 68, 64), (140, 136, 128), (208, 204, 196)],
    "tema_f": [(18, 62, 74), (44, 128, 138), (150, 206, 206)],
}


def _sfumatura(disegno: ImageDraw.ImageDraw, misura: tuple[int, int],
               sopra: tuple[int, int, int], sotto: tuple[int, int, int]) -> None:
    larghezza, altezza = misura
    for riga in range(altezza):
        quota = riga / max(altezza - 1, 1)
        colore = tuple(int(sopra[i] + (sotto[i] - sopra[i]) * quota) for i in range(3))
        disegno.line([(0, riga), (larghezza, riga)], fill=colore)


def disegna(tema: str, seme: int, misura: tuple[int, int] = (1600, 1200),
            con_marchio: bool = False) -> Image.Image:
    caso = random.Random(f"{tema}:{seme}")
    tavolozza = TEMI.get(tema, TEMI["tema_a"])
    immagine = Image.new("RGB", misura, tavolozza[0])
    disegno = ImageDraw.Draw(immagine, "RGBA")

    _sfumatura(disegno, misura, tavolozza[0], tavolozza[1])
    larghezza, altezza = misura

    for _ in range(caso.randint(3, 7)):
        x = caso.randint(-larghezza // 4, larghezza)
        y = caso.randint(altezza // 3, altezza)
        raggio = caso.randint(larghezza // 12, larghezza // 3)
        colore = caso.choice(tavolozza[1:]) + (caso.randint(60, 170),)
        if caso.random() < 0.5:
            disegno.ellipse([x - raggio, y - raggio, x + raggio, y + raggio], fill=colore)
        else:
            disegno.polygon(
                [(x, y - raggio), (x + raggio, y + raggio), (x - raggio, y + raggio)],
                fill=colore,
            )

    orizzonte = int(altezza * caso.uniform(0.45, 0.7))
    disegno.rectangle([0, orizzonte, larghezza, altezza],
                      fill=tavolozza[2] + (caso.randint(90, 160),))

    if con_marchio:
        lato = int(larghezza * 0.055)
        x = caso.randint(larghezza // 4, larghezza - lato * 3)
        y = caso.randint(altezza // 3, altezza - lato * 2)
        disegno.rectangle([x, y, x + lato * 2, y + lato], fill=(245, 245, 240, 235))
        for barra in range(5):
            spessore = lato // 9
            passo = lato * 2 // 6
            disegno.rectangle(
                [x + passo // 2 + barra * passo, y + lato // 4,
                 x + passo // 2 + barra * passo + spessore, y + lato * 3 // 4],
                fill=(20, 20, 24, 255),
            )

    for passo in range(6):
        alfa = 10 + passo * 6
        margine = passo * max(larghezza, altezza) // 90
        disegno.rectangle(
            [margine, margine, larghezza - margine, altezza - margine],
            outline=(0, 0, 0, alfa), width=max(larghezza // 220, 2),
        )

    return immagine


def fotogrammi_video(tema: str, seme: int, quanti: int,
                     misura: tuple[int, int] = (640, 480),
                     fermo: bool = False) -> list[bytes]:
    base = disegna(tema, seme, misura)
    larghezza, altezza = misura
    fotogrammi = []
    for indice in range(quanti):
        quota = indice / max(quanti - 1, 1)
        if fermo:
            mosso = base.copy()
        else:
            spostamento = int(math.sin(quota * math.pi) * larghezza * 0.16)
            mosso = base.transform(
                misura, Image.Transform.AFFINE,
                (1, 0, spostamento, 0, 1, spostamento // 3),
                resample=Image.Resampling.BILINEAR,
            )
            raggio = max(6, larghezza // 14)
            centro = int(-raggio + quota * (larghezza + raggio * 2))
            alto = int(altezza * (0.35 + 0.2 * math.sin(quota * math.pi * 2)))
            ImageDraw.Draw(mosso, "RGBA").ellipse(
                [centro - raggio, alto - raggio, centro + raggio, alto + raggio],
                fill=(250, 248, 240, 230),
            )
        appoggio = io.BytesIO()
        mosso.save(appoggio, "JPEG", quality=72)
        fotogrammi.append(appoggio.getvalue())
    return fotogrammi
