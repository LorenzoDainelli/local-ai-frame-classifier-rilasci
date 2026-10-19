from __future__ import annotations

import json
import os
import time
from pathlib import Path

import numpy
from PIL import Image, ImageOps

from officina.ritocco import maschere, scelta

LATO = 10
VISTI = "visti.jsonl"
SEGUITI = "seguiti.jsonl"
PASSO = 2


def seguiti(cartella: Path) -> list[dict]:
    dove = Path(cartella) / SEGUITI
    if not dove.exists():
        return []
    return [json.loads(riga) for riga in dove.read_text(encoding="utf-8").splitlines()]


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

    def _misura(self, chiave: str, percorso: Path, fotogramma=None) -> tuple[int, int]:
        if fotogramma is not None:
            pronto = self.prepara(chiave, percorso)
            if not 0 <= fotogramma < pronto.quanti:
                raise ValueError("fotogramma fuori dal video")
            return pronto.larghezza, pronto.altezza
        if chiave not in self.guardate:
            with Image.open(percorso) as immagine:
                self.guardate[chiave] = ImageOps.exif_transpose(immagine).size
        return self.guardate[chiave]

    def prepara(self, chiave: str, percorso: Path, al_passo=None, fermati=None):
        from officina.ritocco import filmato

        if getattr(self, "_filmato", None) is not None and self._chiave_del_filmato == chiave:
            return self._filmato
        self._filmato = filmato.Filmato(Path(percorso), fermati=fermati or filmato._mai,
                                        al_passo=al_passo)
        self._chiave_del_filmato = chiave
        return self._filmato

    def segui(self, chiave: str, percorso: Path, scelte: dict, tratti: list,
              sulla_scheda: bool, al_fotogramma, al_passo=None, fermati=None) -> dict:
        self.accendi(sulla_scheda)
        pronto = self.prepara(chiave, percorso, al_passo, fermati)
        with open(self.cartella / SEGUITI, "a", encoding="utf-8") as scritto:
            scritto.write(json.dumps({"tratti": [[t.da, t.inizio, t.fine] for t in tratti],
                                      "dove": self._dove(), "pid": os.getpid()}) + "\n")
        fatti = 0
        for tratto in tratti:
            pezzo = maschere.per_misura(maschere.apri(scelte[tratto.da]), pronto.larghezza,
                                        pronto.altezza)
            ordine = [tratto.da, *range(tratto.da + 1, tratto.fine + 1),
                      *range(tratto.da - 1, tratto.inizio - 1, -1)]
            for indice in ordine:
                if fermati is not None and fermati():
                    return {"fatti": fatti, "dove": self._dove(), "quanti": pronto.quanti,
                            "larghezza": pronto.larghezza, "altezza": pronto.altezza}
                self._aspetta_un_po()
                spostato = maschere.Pezzo(pezzo.larghezza, pezzo.altezza,
                                          pezzo.x + (indice - tratto.da) * PASSO, pezzo.y,
                                          pezzo.maschera)
                piena = maschere.intera(spostato)
                dati = (maschere.comprimi(piena, (0, 0), pronto.larghezza, pronto.altezza)
                        if piena.any() else b"")
                al_fotogramma(indice, tratto.da, dati, 0.9 if dati else 0.1)
                fatti += 1
        return {"fatti": fatti, "dove": self._dove(), "quanti": pronto.quanti,
                "larghezza": pronto.larghezza, "altezza": pronto.altezza}

    def _aspetta_un_po(self) -> None:
        pass

    def guarda(self, chiave: str, percorso: Path, sulla_scheda: bool,
               fotogramma=None) -> tuple[int, int, str]:
        self.accendi(sulla_scheda)
        larga, alta = self._misura(chiave, percorso, fotogramma)
        return larga, alta, self._dove()

    def scegli(self, chiave: str, percorso: Path, punti, riquadro,
               sulla_scheda: bool, fotogramma=None) -> scelta.Scelta:
        self.accendi(sulla_scheda)
        larga, alta = self._misura(chiave, percorso, fotogramma)
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


class Lento(Finto):

    def _aspetta_un_po(self) -> None:
        time.sleep(0.05)


class Piena(Finto):

    def scegli(self, chiave, percorso, punti, riquadro, sulla_scheda, fotogramma=None):
        if sulla_scheda:
            raise RuntimeError("CUDA out of memory. Tried to allocate 2.00 GiB")
        return super().scegli(chiave, percorso, punti, riquadro, sulla_scheda, fotogramma)

    def segui(self, chiave, percorso, scelte, tratti, sulla_scheda, al_fotogramma,
              al_passo=None, fermati=None):
        if sulla_scheda:
            raise RuntimeError("CUDA out of memory. Tried to allocate 2.00 GiB")
        return super().segui(chiave, percorso, scelte, tratti, sulla_scheda, al_fotogramma,
                             al_passo, fermati)


class Rotta(Finto):

    def scegli(self, chiave, percorso, punti, riquadro, sulla_scheda, fotogramma=None):
        raise ValueError("dentro c'era /una/cartella/segreta.jpg")

    def segui(self, chiave, percorso, scelte, tratti, sulla_scheda, al_fotogramma,
              al_passo=None, fermati=None):
        raise ValueError("dentro c'era /una/cartella/segreta.mp4")


class Crolla(Finto):

    def scegli(self, chiave, percorso, punti, riquadro, sulla_scheda, fotogramma=None):
        os._exit(3)


class NonParte(Finto):

    def __init__(self, cartella):
        raise ImportError("manca transformers")
