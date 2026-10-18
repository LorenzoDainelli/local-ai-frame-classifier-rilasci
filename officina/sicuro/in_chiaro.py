from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

from officina.sicuro.chiavetta import tutti_i_dischi

CARTELLA = "Local AI Frame Classifier"
ELENCO = "elenco.json"
ULTIMA = "ultima.json"
ARCHIVIO = "archivio"
DATABASE = (".sqlite", ".sqlite.in-arrivo")
CHIUSO = (".forziere", ".forziere.in-arrivo")
ULTIMA_MASSIMA = 64 * 1024
RIMANDO = 0x400


@dataclass(frozen=True)
class CopiaInChiaro:
    percorso: Path
    file: int
    byte: int
    quando: float | None
    database: bool
    finita: bool

    def a_parole(self) -> dict:
        return {"percorso": str(self.percorso), "file": self.file, "byte": self.byte,
                "quando": self.quando, "database": self.database,
                "finita": self.finita}


def _voci(cartella: Path) -> list[os.DirEntry]:
    try:
        with os.scandir(cartella) as dentro:
            return list(dentro)
    except OSError:
        return []


def _rimando(informazioni: os.stat_result) -> bool:
    return bool(getattr(informazioni, "st_file_attributes", 0) & RIMANDO)


def _cartella(voce: os.DirEntry) -> bool:
    try:
        return (voce.is_dir(follow_symlinks=False)
                and not _rimando(voce.stat(follow_symlinks=False)))
    except OSError:
        return False


def _file(percorso: Path) -> bool:
    try:
        return stat.S_ISREG(os.lstat(percorso).st_mode)
    except OSError:
        return False


def _cartella_vera(percorso: Path) -> bool:
    try:
        informazioni = os.lstat(percorso)
    except OSError:
        return False
    return stat.S_ISDIR(informazioni.st_mode) and not _rimando(informazioni)


def _nomi_dell_archivio(casa: Path) -> list[str]:
    archivio = casa / ARCHIVIO
    if not _cartella_vera(archivio):
        return []
    return [voce.name.lower() for voce in _voci(archivio)
            if not _cartella(voce)]


def e_una_copia(casa: Path) -> bool:
    if not _cartella_vera(casa):
        return False
    if _file(casa / ELENCO) or _file(casa / ULTIMA):
        return True
    return any(nome.endswith(DATABASE + CHIUSO) for nome in _nomi_dell_archivio(casa))


def misura(casa: Path) -> tuple[int, int]:
    quanti = 0
    peso = 0
    da_vedere = [casa]
    while da_vedere:
        cartella = da_vedere.pop()
        for voce in _voci(cartella):
            try:
                if _cartella(voce):
                    da_vedere.append(Path(voce.path))
                elif voce.is_file(follow_symlinks=False):
                    quanti += 1
                    peso += voce.stat(follow_symlinks=False).st_size
            except OSError:
                continue
    return quanti, peso


def _quando_scritto(testo) -> float | None:
    if not isinstance(testo, str):
        return None
    try:
        momento = datetime.strptime(testo, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return None
    return momento.replace(tzinfo=timezone.utc).timestamp()


def _ultima(casa: Path) -> dict | None:
    percorso = casa / ULTIMA
    if not _file(percorso):
        return None
    try:
        with open(percorso, "rb") as dentro:
            grezzo = dentro.read(ULTIMA_MASSIMA + 1)
    except OSError:
        return None
    if len(grezzo) > ULTIMA_MASSIMA:
        return None
    try:
        letto = json.loads(grezzo.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        return None
    return letto if isinstance(letto, dict) else None


def _ultima_modifica(casa: Path) -> float | None:
    candidati = [casa / ELENCO, casa / ULTIMA]
    candidati += [casa / ARCHIVIO / nome for nome in _nomi_dell_archivio(casa)]
    momenti = []
    for percorso in candidati:
        try:
            informazioni = os.lstat(percorso)
        except OSError:
            continue
        if stat.S_ISREG(informazioni.st_mode):
            momenti.append(informazioni.st_mtime)
    return max(momenti) if momenti else None


def leggi(casa: Path, misurala: bool = True) -> CopiaInChiaro:
    ultima = _ultima(casa)
    quando = _quando_scritto(ultima.get("quando")) if ultima else None
    if quando is None:
        quando = _ultima_modifica(casa)
    quanti, peso = misura(casa) if misurala else (0, 0)
    database = any(nome.endswith(DATABASE) for nome in _nomi_dell_archivio(casa))
    return CopiaInChiaro(percorso=casa, file=quanti, byte=peso, quando=quando,
                         database=database, finita=ultima is not None)


def _stessa(percorso: Path) -> str:
    try:
        return os.path.normcase(os.path.realpath(percorso))
    except (OSError, ValueError):
        return os.path.normcase(os.path.abspath(percorso))


def _basi(cartelle: Iterable, dischi: Iterable) -> list[Path]:
    basi = []
    for cartella in cartelle:
        if cartella:
            basi.append(Path(cartella))
    for disco in dischi:
        disco = Path(disco)
        basi.append(disco)
        basi += [Path(voce.path) for voce in _voci(disco) if _cartella(voce)]
    return basi


def _case(base: Path) -> list[Path]:
    contenitore = base / CARTELLA
    if not _cartella_vera(contenitore):
        return []
    return [Path(voce.path) for voce in _voci(contenitore) if _cartella(voce)]


def trova(cartelle: Iterable = (), dischi: Callable[[], Iterable] | None = None,
          misurale: bool = True) -> list[CopiaInChiaro]:
    try:
        attaccati = list((dischi or tutti_i_dischi)())
    except OSError:
        attaccati = []
    viste: set[str] = set()
    trovate = []
    for base in _basi(cartelle, attaccati):
        for casa in sorted(_case(base)):
            chiave = _stessa(casa)
            if chiave in viste or not e_una_copia(casa):
                continue
            viste.add(chiave)
            trovate.append(leggi(casa, misurale))
    return trovate
