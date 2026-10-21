from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from PIL import Image, ImageFilter

from officina.descrittori import vettori
from officina.ritocco import maschere, scelta, togliere

VOLTE = len(togliere.MARGINI)
COPRE = 0.25
DENTRO = 0.6
SICURO = 0.8
ALZA_IL_BORDO = 2.2
BORDO_MINIMO = 6.0

Cerca = Callable[[Path, list, "scelta.Riquadro | None"], "tuple[bytes, float] | None"]


@dataclass
class Esito:

    resta: bool = False
    bordo: bool = False
    dove: list[int] = field(default_factory=list)

    @property
    def pulito(self) -> bool:
        return not self.resta and not self.bordo


def _allarga(buco, quanto: int):
    numpy = vettori.numpy_o_spiega()
    grigia = Image.fromarray(buco.astype(numpy.uint8) * 255, "L")
    return numpy.asarray(grigia.filter(ImageFilter.MaxFilter(quanto * 2 + 1))) > 127


def _salti(immagine: Image.Image):
    numpy = vettori.numpy_o_spiega()
    grigia = numpy.asarray(immagine.convert("L"), dtype=numpy.float32)
    dx = numpy.abs(numpy.diff(grigia, axis=1, append=grigia[:, -1:]))
    dy = numpy.abs(numpy.diff(grigia, axis=0, append=grigia[-1:, :]))
    return dx + dy


def bordo_visibile(dopo: Image.Image, toppa: togliere.Toppa) -> bool:
    numpy = vettori.numpy_o_spiega()
    alfa = numpy.zeros((dopo.height, dopo.width), dtype=bool)
    pezzo = numpy.asarray(toppa.immagine.getchannel("A")) > 8
    alta, larga = pezzo.shape
    x1, y1 = min(dopo.width, toppa.x + larga), min(dopo.height, toppa.y + alta)
    alfa[toppa.y:y1, toppa.x:x1] = pezzo[:y1 - toppa.y, :x1 - toppa.x]
    if not alfa.any():
        return False
    cucitura = _allarga(alfa, 2) & ~_erodi(alfa, 2)
    vicino = _allarga(alfa, 10) & ~_allarga(alfa, 4)
    if not cucitura.any() or not vicino.any():
        return False
    salti = _salti(dopo)
    sulla_cucitura = float(salti[cucitura].mean())
    intorno = float(salti[vicino].mean())
    return sulla_cucitura > max(BORDO_MINIMO, intorno * ALZA_IL_BORDO)


def _erodi(buco, quanto: int):
    numpy = vettori.numpy_o_spiega()
    grigia = Image.fromarray(buco.astype(numpy.uint8) * 255, "L")
    return numpy.asarray(grigia.filter(ImageFilter.MinFilter(quanto * 2 + 1))) > 127


def domanda(buco) -> tuple[list, scelta.Riquadro]:
    numpy = vettori.numpy_o_spiega()
    alta, larga = buco.shape
    righe, colonne = numpy.nonzero(buco)
    x0, x1 = colonne.min(), colonne.max() + 1
    y0, y1 = righe.min(), righe.max() + 1
    centro = (float(colonne.mean()) / larga, float(righe.mean()) / alta)
    return ([scelta.Punto(centro[0], centro[1], True)],
            scelta.Riquadro(x0 / larga, y0 / alta, x1 / larga, y1 / alta))


def resta_qualcosa(trovata: bytes, punteggio: float, buco) -> list[int] | None:
    numpy = vettori.numpy_o_spiega()
    pezzo = maschere.apri(trovata)
    if pezzo is None or punteggio < SICURO:
        return None
    alta, larga = buco.shape
    vista = maschere.intera(maschere.per_misura(pezzo, larga, alta))
    if not vista.any():
        return None
    zona = _allarga(buco, max(4, round(min(larga, alta) * 0.01)))
    copre = float((vista & buco).sum()) / max(1, int(buco.sum()))
    dentro = float((vista & zona).sum()) / max(1, int(vista.sum()))
    if copre < COPRE or dentro < DENTRO:
        return None
    righe, colonne = numpy.nonzero(vista & zona)
    return [int(colonne.min()), int(righe.min()), int(colonne.max()) + 1, int(righe.max()) + 1]


def controlla(dopo: Image.Image, toppa: togliere.Toppa, buco, cerca: Cerca | None,
              percorso: Path | None) -> Esito:
    esito = Esito(bordo=bordo_visibile(dopo, toppa))
    if cerca is not None and percorso is not None:
        punti, riquadro = domanda(buco)
        trovato = cerca(percorso, punti, riquadro)
        if trovato is not None:
            dove = resta_qualcosa(trovato[0], trovato[1], buco)
            if dove is not None:
                esito.resta, esito.dove = True, dove
    return esito
