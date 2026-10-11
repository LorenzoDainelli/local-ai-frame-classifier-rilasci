from __future__ import annotations

import json
import os
import sqlite3
import sys
import threading
from dataclasses import dataclass
from pathlib import Path

from officina.errori import ErroreOfficina
from officina.programma import NOME

VERSIONE_CARTA = 1

_lucchetto = threading.RLock()


def casa() -> Path:
    scelta = os.environ.get("OFFICINA_CASA_PROGRAMMA")
    if scelta:
        return Path(scelta).expanduser().resolve()
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / NOME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / NOME
    return Path.home() / ".local" / "share" / "local-ai-frame-classifier"


def file_carta() -> Path:
    return casa() / "programma.json"


def cartella_librerie() -> Path:
    return casa() / "librerie"


def cartella_scaricati() -> Path:
    return casa() / "scaricati"


def cartella_dati_nuova() -> Path:
    return casa() / "dati"


def leggi() -> dict:
    with _lucchetto:
        try:
            testo = file_carta().read_text(encoding="utf-8")
        except (FileNotFoundError, NotADirectoryError):
            return {}
        except OSError:
            return {}
        try:
            dentro = json.loads(testo)
        except ValueError:
            _metti_da_parte_la_rovinata()
            return {}
        return dentro if isinstance(dentro, dict) else {}


def _metti_da_parte_la_rovinata() -> None:
    try:
        file_carta().replace(file_carta().with_suffix(".rovinata.json"))
    except OSError:
        pass


def scrivi(carta: dict) -> None:
    with _lucchetto:
        dove = file_carta()
        dove.parent.mkdir(parents=True, exist_ok=True)
        provvisorio = dove.with_suffix(".scrittura")
        testo = json.dumps({**carta, "versione_carta": VERSIONE_CARTA},
                           ensure_ascii=True, indent=2, sort_keys=True)
        with open(provvisorio, "w", encoding="utf-8") as f:
            f.write(testo)
            f.flush()
            os.fsync(f.fileno())
        os.replace(provvisorio, dove)


def aggiorna(**campi) -> dict:
    with _lucchetto:
        carta = leggi()
        for chiave, valore in campi.items():
            if valore is None:
                carta.pop(chiave, None)
            else:
                carta[chiave] = valore
        scrivi(carta)
        return carta


def cartella_dati() -> Path | None:
    scritta = leggi().get("cartella_dati")
    if not scritta:
        return None
    return Path(scritta)


def cartella_della_versione_1() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "Officina"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Officina"
    return Path.home() / ".local" / "share" / "officina"


@dataclass(frozen=True)
class ArchivioTrovato:

    dove: Path
    nel_forziere: bool
    scatti: int | None
    peso: int
    toccato_il: float

    @property
    def c_e_qualcosa(self) -> bool:
        return self.nel_forziere or self.peso > 0


def _peso_della_cartella(cartella: Path, fino_a: int = 200_000) -> int:
    totale = 0
    visti = 0
    for radice, _, file in os.walk(cartella):
        for nome in file:
            visti += 1
            if visti > fino_a:
                return totale
            try:
                totale += (Path(radice) / nome).stat().st_size
            except OSError:
                pass
    return totale


def _quanti_scatti(database: Path) -> int | None:
    try:
        uri = database.resolve().as_uri() + "?mode=ro"
        connessione = sqlite3.connect(uri, uri=True, timeout=1.0)
        try:
            riga = connessione.execute(
                "SELECT count(*) FROM scatti WHERE fuori_archivio = 0").fetchone()
        finally:
            connessione.close()
        return int(riga[0]) if riga else None
    except (sqlite3.Error, OSError, ValueError):
        return None


def guarda(dove: Path) -> ArchivioTrovato | None:
    try:
        dove = Path(dove)
        database = dove / "reale" / "archivio.sqlite"
        forziere = dove / "reale.forziere"
        aperto = (dove / "reale" / ".forziere-aperto").exists()
        c_e_il_database = database.is_file()
        c_e_il_forziere = forziere.is_file()
    except OSError:
        return None
    if not c_e_il_database and not c_e_il_forziere:
        return None

    if c_e_il_forziere and not aperto:
        peso = forziere.stat().st_size
        toccato = forziere.stat().st_mtime
        return ArchivioTrovato(dove=dove, nel_forziere=True, scatti=None,
                               peso=peso, toccato_il=toccato)

    return ArchivioTrovato(
        dove=dove,
        nel_forziere=c_e_il_forziere,
        scatti=_quanti_scatti(database),
        peso=_peso_della_cartella(dove / "reale"),
        toccato_il=database.stat().st_mtime,
    )


def archivio_della_versione_1() -> ArchivioTrovato | None:
    candidati = []
    da_ambiente = os.environ.get("OFFICINA_ARCHIVIO")
    if da_ambiente:
        candidati.append(Path(da_ambiente).expanduser())
    candidati.append(cartella_della_versione_1())
    for posto in candidati:
        trovato = guarda(posto)
        if trovato is not None:
            return trovato
    return None


NON_E_UN_ARCHIVIO = (
    "In questa cartella non trovo un archivio. Quello giusto contiene una "
    "cartella chiamata «reale» (oppure un file «reale.forziere»): scegli la "
    "cartella che la contiene, o la cartella «reale» stessa.")


def dalla_scelta(scelta: str | os.PathLike) -> ArchivioTrovato:
    percorso = Path(scelta).expanduser()
    for posto in (percorso, percorso.parent if percorso.name.lower() == "reale" else None):
        if posto is None:
            continue
        trovato = guarda(posto)
        if trovato is not None:
            return trovato
    raise ErroreOfficina(NON_E_UN_ARCHIVIO, codice="non_e_un_archivio")


def _novita_gia_lette() -> int:
    from officina.programma import novita

    return leggi().get("novita_lette", novita.ultima())


def usa_questo_archivio(dove: Path) -> dict:
    return aggiorna(cartella_dati=str(Path(dove).resolve()),
                    novita_lette=_novita_gia_lette())


def comincia_da_zero() -> dict:
    nuova = cartella_dati_nuova()
    nuova.mkdir(parents=True, exist_ok=True)
    return aggiorna(cartella_dati=str(nuova), novita_lette=_novita_gia_lette())
