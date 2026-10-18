from __future__ import annotations

import json
import os
from pathlib import Path

import numpy
from PIL import Image, ImageOps

from officina.ritocco import maschere, scelta

LATO = 10
VISTI = "visti.jsonl"


def visti(cartella: Path) -> list[dict]:
    dove = Path(cartella) / VISTI
    if not dove.exists():
        return []
    return [json.loads(riga) for riga in dove.read_text(encoding="utf-8").splitlines()]


class Finto:

    scheda = True

    def __init__(self, cartella):
        self.cartella = Path(cartella)
        self.dispositivo = None
        self.guardate: dict = {}
        self.spenti = 0
        self.accesi: list[str] = []

    def ha_la_scheda(self) -> bool:
        return type(self).scheda

    def accendi(self, sulla_scheda: bool) -> str:
        voluto = "cuda" if sulla_scheda and self.ha_la_scheda() else "cpu"
        if voluto != self.dispositivo:
            if self.dispositivo is not None:
                self.spegni()
            self.dispositivo = voluto
            self.accesi.append(voluto)
        return voluto

    def spegni(self) -> None:
        self.dispositivo = None
        self.guardate.clear()
        self.spenti += 1

    def _dove(self) -> str:
        return scelta.PROCESSORE if self.dispositivo == "cpu" else scelta.SCHEDA

    def _misura(self, chiave: str, percorso: Path) -> tuple[int, int]:
        if chiave not in self.guardate:
            with Image.open(percorso) as immagine:
                self.guardate[chiave] = ImageOps.exif_transpose(immagine).size
        return self.guardate[chiave]

    def guarda(self, chiave: str, percorso: Path, sulla_scheda: bool) -> tuple[int, int, str]:
        self.accendi(sulla_scheda)
        larga, alta = self._misura(chiave, percorso)
        return larga, alta, self._dove()

    def scegli(self, chiave: str, percorso: Path, punti, riquadro,
               sulla_scheda: bool) -> scelta.Scelta:
        self.accendi(sulla_scheda)
        larga, alta = self._misura(chiave, percorso)
        with open(self.cartella / VISTI, "a", encoding="utf-8") as scritto:
            scritto.write(json.dumps({"chiave": chiave, "percorso": str(percorso),
                                      "sulla_scheda": sulla_scheda, "dove": self._dove(),
                                      "pid": os.getpid()}) + "\n")
        maschera = numpy.zeros((alta, larga), dtype=bool)
        coordinate, etichette, scatola = scelta.in_pixel(punti, riquadro, larga, alta)
        if scatola is not None:
            x1, y1, x2, y2 = (round(valore) for valore in scatola)
            maschera[y1:y2, x1:x2] = True
        for (x, y), dentro in zip(coordinate, etichette, strict=True):
            x0, y0 = max(0, round(x) - LATO // 2), max(0, round(y) - LATO // 2)
            maschera[y0:y0 + LATO, x0:x0 + LATO] = bool(dentro)
        return scelta.Scelta(maschere.comprimi(maschera, (0, 0), larga, alta), 0.875,
                             larga, alta, self._dove())


class SenzaScheda(Finto):

    scheda = False


class Piena(Finto):

    def scegli(self, chiave, percorso, punti, riquadro, sulla_scheda):
        if sulla_scheda:
            raise RuntimeError("CUDA out of memory. Tried to allocate 2.00 GiB")
        return super().scegli(chiave, percorso, punti, riquadro, sulla_scheda)


class Rotta(Finto):

    def scegli(self, chiave, percorso, punti, riquadro, sulla_scheda):
        raise ValueError("dentro c'era /una/cartella/segreta.jpg")


class Crolla(Finto):

    def scegli(self, chiave, percorso, punti, riquadro, sulla_scheda):
        os._exit(3)


class NonParte(Finto):

    def __init__(self, cartella):
        raise ImportError("manca transformers")
