from __future__ import annotations

import importlib
from typing import Iterable, Iterator

from PIL import Image

FINTO = "finto"

SEEDVR2 = "seedvr2"
LUCIDFLUX = "lucidflux"
CODEFORMER = "codeformer"
FACEME = "faceme"
NESSUNO = "nessuno"
DA_SOLI = "da_soli"

FOTO = {
    FINTO: "officina.miglioria.motori:Finto",
    SEEDVR2: "officina.miglioria.seedvr2:SeedVR2",
    LUCIDFLUX: "officina.miglioria.lucidflux:LucidFlux",
}
VIDEO = {
    FINTO: "officina.miglioria.motori:Finto",
    SEEDVR2: "officina.miglioria.seedvr2:SeedVR2",
}
VOLTI = {
    CODEFORMER: "officina.miglioria.codeformer:CodeFormer",
    FACEME: "officina.miglioria.faceme:FaceMe",
}


class MotoreSconosciuto(ValueError):
    pass


class Finto:

    nome = FINTO
    versione = "1"

    def __init__(self, **_opzioni) -> None:
        self.spento = False

    def foto(self, immagine: Image.Image, larghezza: int, altezza: int) -> Image.Image:
        return immagine.resize((larghezza, altezza), Image.Resampling.LANCZOS)

    def video(self, quadri: Iterable, larghezza: int, altezza: int, salta: int = 0,
              al_pezzo=None) -> Iterator:
        import numpy as np

        for visti, quadro in enumerate(quadri):
            if visti < salta:
                continue
            yield np.asarray(Image.fromarray(quadro).resize(
                (larghezza, altezza), Image.Resampling.LANCZOS))

    def spegni(self) -> None:
        self.spento = True


def _classe(indirizzo: str):
    modulo, nome = indirizzo.split(":", 1)
    return getattr(importlib.import_module(modulo), nome)


def apri(elenco: dict[str, str], nome: str, **opzioni):
    indirizzo = elenco.get(nome)
    if indirizzo is None:
        raise MotoreSconosciuto(nome)
    return _classe(indirizzo)(**opzioni)
