from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Iterator

from officina.errori import ErroreOfficina
from officina.miglioria import attesa

CARTELLA = ".pezzi"
FIRMA = "firma.json"
FINITO = "finito"
FINE = ".mkv"
IN_CORSO = ".in-corso"
CODEC = "ffv1"
FORMATO = "bgr0"


class PezzoRotto(ErroreOfficina):
    codice = "pezzi_rotti"


def cartella(parziale: Path) -> Path:
    return parziale.with_name(parziale.name + CARTELLA)


def butta(dove: Path) -> bool:
    if not attesa.e_dentro(dove / FIRMA) or not dove.is_dir():
        return False
    shutil.rmtree(dove, ignore_errors=True)
    return True


def butta_quelli_di(dove: Path, miglioria_id: int) -> int:
    if not dove.is_dir():
        return 0
    return sum(butta(cantiere) for cantiere in dove.glob(f"{int(miglioria_id)}-*{CARTELLA}"))


class Pezzi:

    def __init__(self, dove: Path, firma: dict) -> None:
        self.dove = dove
        self.firma = json.loads(json.dumps(firma))
        try:
            letta = json.loads((dove / FIRMA).read_text("utf-8"))
        except (OSError, ValueError):
            letta = None
        if letta != self.firma:
            butta(dove)
        dove.mkdir(parents=True, exist_ok=True)
        (dove / FIRMA).write_text(json.dumps(self.firma), "utf-8")
        for resto in dove.glob(f"*{IN_CORSO}"):
            resto.unlink(missing_ok=True)

    def elenco(self) -> list[tuple[int, int, Path]]:
        trovati = []
        for file in self.dove.glob(f"*{FINE}"):
            try:
                inizio, quanti = (int(pezzo) for pezzo in file.stem.split("-"))
            except ValueError:
                continue
            trovati.append((inizio, quanti, file))
        di_fila, atteso = [], 0
        for inizio, quanti, file in sorted(trovati):
            if inizio != atteso or quanti <= 0:
                break
            di_fila.append((inizio, quanti, file))
            atteso += quanti
        return di_fila

    def fatti(self) -> int:
        return sum(quanti for _inizio, quanti, _file in self.elenco())

    @property
    def finito(self) -> bool:
        return (self.dove / FINITO).is_file()

    def segna_finito(self) -> None:
        (self.dove / FINITO).write_text("", "utf-8")

    def salva(self, inizio: int, quadri: list) -> None:
        import numpy as np

        from officina.immagini import fotogrammi

        av = fotogrammi.decodificatore()
        nome = f"{int(inizio):08d}-{len(quadri):05d}{FINE}"
        provvisorio = self.dove / f"{nome}{IN_CORSO}"
        altezza, larghezza = np.asarray(quadri[0]).shape[:2]
        with av.open(str(provvisorio), "w", format="matroska") as fuori:
            traccia = fuori.add_stream(CODEC, rate=30)
            traccia.width, traccia.height, traccia.pix_fmt = larghezza, altezza, FORMATO
            for quadro in quadri:
                fatto = av.VideoFrame.from_ndarray(np.ascontiguousarray(quadro), format="rgb24")
                for pacchetto in traccia.encode(fatto):
                    fuori.mux(pacchetto)
            for pacchetto in traccia.encode():
                fuori.mux(pacchetto)
        os.replace(provvisorio, self.dove / nome)

    def rileggi(self) -> Iterator:
        from officina.immagini import fotogrammi

        av = fotogrammi.decodificatore()
        for _inizio, quanti, file in self.elenco():
            letti = 0
            try:
                with av.open(str(file)) as dentro:
                    for fotogramma in dentro.decode(video=0):
                        letti += 1
                        yield fotogramma.to_ndarray(format="rgb24")
            except av.error.FFmpegError as errore:
                raise PezzoRotto("Un pezzo del video già migliorato non si legge più.") from errore
            if letti != quanti:
                raise PezzoRotto("Un pezzo del video già migliorato è incompleto.")
