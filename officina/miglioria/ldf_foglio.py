from __future__ import annotations

import gc
import math
import os
import shutil
from pathlib import Path

from officina.errori import ErroreOfficina
from officina.miglioria import seedvr2_blocchi

CARTELLA = "appoggio"
PREFISSO = "foglio-"
FINE = ".bin"
GIGA = 2 ** 30
MARGINE_DISCO = GIGA
RAM, DISCO = "ram", "disco"


class FoglioSenzaPosto(ErroreOfficina):
    codice = "spazio_modelli"
    senza_nomi = True

    def __init__(self, chi: str, serve: int, libero: int) -> None:
        super().__init__(f"{chi} non sta nella scheda video e la RAM libera non basta: per "
                         f"appoggiare i calcoli sul disco dei modelli servono "
                         f"{math.ceil(serve / GIGA)} GB liberi e ce ne sono "
                         f"{libero // GIGA}. Libera spazio su quel disco e riprova.")
        self.serve = int(serve)
        self.libero = int(libero)

    def dati(self) -> dict:
        return {"serve": self.serve, "libero": self.libero}


def byte_di(forma, tipo) -> int:
    return math.prod(int(lato) for lato in forma) * int(tipo.itemsize)


class Foglio:

    def __init__(self, cartella: Path, chi: str, ram_libera=seedvr2_blocchi.ram_libera,
                 spazio=shutil.disk_usage) -> None:
        self.cartella = Path(cartella)
        self.chi = chi
        self._ram_libera = ram_libera
        self._spazio = spazio
        self.dato = None
        self.dove: str | None = None
        self.file: Path | None = None
        self.byte = 0
        self.usato: str | None = None
        self.picco = 0

    def nuovo_video(self) -> None:
        self.usato = None
        self.picco = 0

    def __call__(self, forma, tipo, in_piu: int = 0):
        forma = tuple(int(lato) for lato in forma)
        if (self.dato is not None and tuple(self.dato.shape) == forma
                and self.dato.dtype == tipo):
            return self.dato
        self.lascia()
        import torch

        byte = byte_di(forma, tipo)
        libera = self._ram_libera()
        if libera is None or byte + int(in_piu) + seedvr2_blocchi.MARGINE_RAM <= libera:
            self.dato = torch.empty(forma, dtype=tipo)
            self.dove = RAM
        else:
            self.dato = self._sul_disco(torch, forma, tipo, byte)
            self.dove = DISCO
        self.byte = byte
        self.picco = max(self.picco, byte)
        if self.usato != DISCO:
            self.usato = self.dove
        return self.dato

    def _sul_disco(self, torch, forma, tipo, byte: int):
        self.cartella.mkdir(parents=True, exist_ok=True)
        self.pulisci()
        libero = int(self._spazio(self.cartella).free)
        if byte + MARGINE_DISCO > libero:
            raise FoglioSenzaPosto(self.chi, byte + MARGINE_DISCO, libero)
        file = self.cartella / f"{PREFISSO}{os.getpid()}{FINE}"
        with open(file, "wb") as aperto:
            aperto.truncate(byte)
        self.file = file
        quanti = byte // int(tipo.itemsize)
        return torch.from_file(str(file), shared=True, size=quanti, dtype=tipo).view(forma)

    def lascia(self) -> None:
        self.dato = None
        self.dove = None
        self.byte = 0
        file, self.file = self.file, None
        if file is None:
            return
        gc.collect()
        try:
            file.unlink(missing_ok=True)
        except OSError:
            return

    def pulisci(self) -> None:
        if not self.cartella.is_dir():
            return
        for vecchio in self.cartella.glob(f"{PREFISSO}*{FINE}"):
            if self.file is not None and vecchio == self.file:
                continue
            try:
                vecchio.unlink()
            except OSError:
                continue

    def giga(self) -> float:
        return round(self.picco / GIGA, 1)


def riassunto(tempi) -> dict | None:
    usati = [tempo for tempo in tempi or []
             if isinstance(tempo, dict) and tempo.get("foglio") in (RAM, DISCO)]
    if not usati:
        return None
    dove = DISCO if any(tempo["foglio"] == DISCO for tempo in usati) else RAM
    return {"dove": dove, "gb": max(float(tempo.get("foglio_gb") or 0) for tempo in usati)}


__all__ = ["DISCO", "Foglio", "FoglioSenzaPosto", "RAM", "byte_di", "riassunto"]
