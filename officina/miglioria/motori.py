from __future__ import annotations

import importlib
import json
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
    resta_acceso = True

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


class Acceso:

    def __init__(self, motore) -> None:
        self.motore = motore

    def __getattr__(self, nome: str):
        return getattr(self.motore, nome)

    def spegni(self) -> None:
        pass


_accesi: dict | None = None
caricati = 0


def tieni_accesi() -> None:
    global _accesi
    _accesi = {}


def resta_acceso(elenco: dict[str, str], nome: str) -> bool:
    indirizzo = elenco.get(nome)
    if indirizzo is None:
        return False
    return getattr(_classe(indirizzo), "resta_acceso", False) is True


def ancora_buoni() -> bool:
    return not any(getattr(acceso.motore, "stretto", False)
                   for acceso in (_accesi or {}).values())


def spegni_tutti() -> None:
    accesi = list((_accesi or {}).values())
    if _accesi is not None:
        _accesi.clear()
    for acceso in accesi:
        try:
            acceso.motore.spegni()
        except Exception:
            pass


def apri(elenco: dict[str, str], nome: str, **opzioni):
    global caricati
    indirizzo = elenco.get(nome)
    if indirizzo is None:
        raise MotoreSconosciuto(nome)
    classe = _classe(indirizzo)
    if _accesi is None or getattr(classe, "resta_acceso", False) is not True:
        return classe(**opzioni)
    chiave = json.dumps([indirizzo, opzioni], sort_keys=True, default=str)
    if chiave not in _accesi:
        _accesi[chiave] = Acceso(classe(**opzioni))
        caricati += 1
    return _accesi[chiave]
