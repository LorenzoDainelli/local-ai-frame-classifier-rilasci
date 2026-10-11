from __future__ import annotations

import math
from dataclasses import dataclass

from PIL import Image

from officina.descrittori.preparazione import Ritaglio, in_quadrato

CASELLE_SUL_LATO_LUNGO = 8

SOVRAPPOSIZIONE = 0.10

LATO = 512

PREFISSO = "griglia"
METODO = "griglia"


@dataclass(frozen=True)
class Casella:

    riga: int
    colonna: int
    riquadro: tuple[float, float, float, float]

    @property
    def nome(self) -> str:
        return f"{PREFISSO}_r{self.riga:02d}c{self.colonna:02d}"


def e_una_casella(inquadratura: str) -> bool:
    return inquadratura.startswith(f"{PREFISSO}_")


def quante(larghezza: int, altezza: int,
           sul_lato_lungo: int = CASELLE_SUL_LATO_LUNGO) -> tuple[int, int]:
    larghezza = max(1, int(larghezza))
    altezza = max(1, int(altezza))
    lungo = max(larghezza, altezza)
    lato_px = lungo / sul_lato_lungo
    corto_quante = max(1, math.ceil(min(larghezza, altezza) / lato_px))
    if larghezza >= altezza:
        return sul_lato_lungo, corto_quante
    return corto_quante, sul_lato_lungo


def caselle(larghezza: int, altezza: int,
            sul_lato_lungo: int = CASELLE_SUL_LATO_LUNGO,
            sovrapposizione: float = SOVRAPPOSIZIONE) -> list[Casella]:
    larghezza = max(1, int(larghezza))
    altezza = max(1, int(altezza))
    colonne, righe = quante(larghezza, altezza, sul_lato_lungo)

    lato_px = min(max(larghezza, altezza) / sul_lato_lungo * (1 + sovrapposizione),
                  larghezza, altezza)
    passo_x = (larghezza - lato_px) / (colonne - 1) if colonne > 1 else 0.0
    passo_y = (altezza - lato_px) / (righe - 1) if righe > 1 else 0.0

    fuori = []
    for riga in range(righe):
        for colonna in range(colonne):
            x = colonna * passo_x
            y = riga * passo_y
            fuori.append(Casella(riga, colonna, (x / larghezza, y / altezza,
                                                 lato_px / larghezza,
                                                 lato_px / altezza)))
    return fuori


def ritagli(immagine: Image.Image, lato: int = LATO,
            sul_lato_lungo: int = CASELLE_SUL_LATO_LUNGO) -> list[Ritaglio]:
    if immagine.mode != "RGB":
        immagine = immagine.convert("RGB")
    larghezza, altezza = immagine.size

    fuori = []
    for casella in caselle(larghezza, altezza, sul_lato_lungo):
        x, y, larga, alta = casella.riquadro
        sinistra, sopra = int(x * larghezza), int(y * altezza)
        pezzo = immagine.crop((
            sinistra, sopra,
            min(larghezza, sinistra + max(1, int(larga * larghezza))),
            min(altezza, sopra + max(1, int(alta * altezza))),
        ))
        fuori.append(Ritaglio(casella.nome, METODO, casella.riquadro,
                              in_quadrato(pezzo, lato)))
    return fuori


MASSIMO = "massimo"
MEDIA = "media"
MODI = (MASSIMO, MEDIA)


def combina(punteggi, come: str = MASSIMO) -> float:
    valori = list(punteggi)
    if not valori:
        return 0.0
    if come == MEDIA:
        return sum(valori) / len(valori)
    return max(valori)


def combina_per_scatto(scatti, punteggi, come: str = MASSIMO) -> dict[int, float]:
    per_scatto: dict[int, list[float]] = {}
    for scatto_id, punteggio in zip(scatti, punteggi, strict=True):
        per_scatto.setdefault(scatto_id, []).append(punteggio)
    return {scatto_id: combina(valori, come)
            for scatto_id, valori in per_scatto.items()}
