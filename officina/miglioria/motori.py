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


def classe(elenco: dict[str, str], nome: str):
    indirizzo = elenco.get(nome)
    if indirizzo is None:
        raise MotoreSconosciuto(nome)
    return _classe(indirizzo)


class Acceso:

    def __init__(self, motore) -> None:
        self.motore = motore

    def __getattr__(self, nome: str):
        return getattr(self.motore, nome)

    def spegni(self) -> None:
        pass


class Parcheggiato(Acceso):

    def __init__(self, motore, chiave: str) -> None:
        super().__init__(motore)
        self.chiave = chiave

    def spegni(self) -> None:
        try:
            peso = int(self.motore.parcheggia())
        except Exception:
            _butta(self.chiave)
            return
        _parcheggiati[self.chiave] = peso


def vero(motore):
    return motore.motore if isinstance(motore, Acceso) else motore


_accesi: dict | None = None
_parcheggiati: dict[str, int] = {}
caricati = 0


def _butta(chiave: str) -> None:
    _parcheggiati.pop(chiave, None)
    acceso = (_accesi or {}).pop(chiave, None)
    if acceso is not None:
        try:
            acceso.motore.spegni()
        except Exception:
            pass


def parcheggiati() -> int:
    return sum(_parcheggiati.values())


def libera_per(serve: int, libera: int | None) -> int | None:
    if libera is None or libera >= serve or not _parcheggiati:
        return libera
    for chiave in list(_parcheggiati):
        _butta(chiave)
    from officina.miglioria.seedvr2_blocchi import ram_libera

    return ram_libera()


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
    _parcheggiati.clear()
    if _accesi is not None:
        _accesi.clear()
    for acceso in accesi:
        try:
            acceso.motore.spegni()
        except Exception:
            pass


def apri(elenco: dict[str, str], nome: str, tieni: bool = False, **opzioni):
    global caricati
    indirizzo = elenco.get(nome)
    if indirizzo is None:
        raise MotoreSconosciuto(nome)
    classe = _classe(indirizzo)
    sempre = getattr(classe, "resta_acceso", False) is True
    a_riposo = bool(tieni) and callable(getattr(classe, "parcheggia", None))
    if _accesi is None or not (sempre or a_riposo):
        return classe(**opzioni)
    chiave = json.dumps([indirizzo, opzioni], sort_keys=True, default=str)
    if chiave not in _accesi:
        motore = classe(**opzioni)
        _accesi[chiave] = Acceso(motore) if sempre else Parcheggiato(motore, chiave)
        caricati += 1
    _parcheggiati.pop(chiave, None)
    return _accesi[chiave]
