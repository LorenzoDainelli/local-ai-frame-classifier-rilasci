from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from pathlib import Path

from officina import registro

VECCHIO_DOPO = 3600.0


@dataclass(frozen=True)
class Spazio:
    quante: int
    byte_miniature: int
    byte_video: int
    byte_archivio: int
    contato_il: float

    @property
    def byte_tutti(self) -> int:
        return self.byte_miniature + self.byte_video + self.byte_archivio


_contati: dict[Path, Spazio] = {}
_in_corso: set[Path] = set()
_lucchetto = threading.Lock()


def conta_adesso(miniature: Path, database: Path) -> Spazio:
    quante = 0
    byte_miniature = 0
    byte_video = 0
    for percorso in miniature.rglob("*"):
        try:
            if not percorso.is_file():
                continue
            peso = percorso.stat().st_size
        except OSError:
            continue
        if percorso.suffix.lower() == ".mp4":
            byte_video += peso
        else:
            quante += 1
            byte_miniature += peso
    byte_archivio = 0
    for accanto in (database, database.with_name(database.name + "-wal")):
        try:
            byte_archivio += accanto.stat().st_size
        except OSError:
            pass
    return Spazio(quante, byte_miniature, byte_video, byte_archivio, time.time())


def _conta_e_ricorda(miniature: Path, database: Path) -> None:
    try:
        _contati[miniature] = conta_adesso(miniature, database)
    except Exception as guasto:
        registro.errore("spazio.non_contato", **registro.dove_si_e_rotto(guasto))
    finally:
        with _lucchetto:
            _in_corso.discard(miniature)


def ricalcola(miniature: Path, database: Path) -> bool:
    with _lucchetto:
        if miniature in _in_corso:
            return False
        _in_corso.add(miniature)
    threading.Thread(target=_conta_e_ricorda, args=(miniature, database),
                     name="spazio", daemon=True).start()
    return True


def ricordato(miniature: Path, database: Path) -> Spazio | None:
    gia = _contati.get(miniature)
    if gia is None or time.time() - gia.contato_il > VECCHIO_DOPO:
        ricalcola(miniature, database)
    return gia


def sta_contando(miniature: Path) -> bool:
    with _lucchetto:
        return miniature in _in_corso


def dimentica() -> None:
    _contati.clear()
