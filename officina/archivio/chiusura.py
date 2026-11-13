from __future__ import annotations

import json
import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from officina import registro
from officina.impostazioni import Posizione

SEGNO = "aperto.segno"
ESITO = "dopo-la-chiusura.json"
SANO = "sano"
ROVINATO = "rovinato"
QUANTI_DIFETTI = 20
TOLLERANZA_ACCENSIONE = 5.0
PROVVISORIO = re.compile(r"\.\d+(\.\d+)?\.tmp$")


def _segno(dove: Posizione) -> Path:
    return dove.radice / SEGNO


def _esito(dove: Posizione) -> Path:
    return dove.radice / ESITO


def _acceso_dal() -> float | None:
    try:
        import psutil

        return float(psutil.boot_time())
    except Exception:
        return None


def _vivo(pid: int) -> bool:
    if pid == os.getpid():
        return True
    try:
        import psutil

        return bool(psutil.pid_exists(pid))
    except Exception:
        return False


def era_aperto(dove: Posizione) -> bool:
    try:
        scritto = json.loads(_segno(dove).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return False
    except (OSError, ValueError):
        return True
    if not isinstance(scritto, dict):
        return True
    pid = scritto.get("pid")
    if not isinstance(pid, int) or isinstance(pid, bool):
        return True
    if pid == os.getpid():
        return False
    allora, adesso = scritto.get("acceso_dal"), _acceso_dal()
    if isinstance(allora, (int, float)) and adesso is not None:
        if abs(float(allora) - adesso) > TOLLERANZA_ACCENSIONE:
            return True
    return not _vivo(pid)


def di_un_altro(dove: Posizione) -> bool:
    try:
        scritto = json.loads(_segno(dove).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    pid = scritto.get("pid") if isinstance(scritto, dict) else None
    if not isinstance(pid, int) or isinstance(pid, bool) or pid == os.getpid():
        return False
    return not era_aperto(dove)


def segna_aperto(dove: Posizione) -> None:
    if di_un_altro(dove):
        return
    provvisorio = _segno(dove).with_name(SEGNO + ".nuovo")
    provvisorio.write_text(json.dumps({"pid": os.getpid(), "acceso_dal": _acceso_dal()}),
                           encoding="utf-8")
    os.replace(provvisorio, _segno(dove))


def segna_chiuso(dove: Posizione) -> None:
    if di_un_altro(dove):
        return
    _segno(dove).unlink(missing_ok=True)


def _cartelle_del_programma(dove: Posizione) -> tuple[Path, ...]:
    return (dove.miniature, dove.stanze, dove.superfici, dove.aiuti, dove.imparato)


def togli_i_provvisori(dove: Posizione) -> int:
    tolti = 0
    for cartella in _cartelle_del_programma(dove):
        if not cartella.is_dir():
            continue
        for resto in cartella.rglob("*.tmp"):
            if not PROVVISORIO.search(resto.name) or not resto.is_file():
                continue
            try:
                resto.unlink()
            except OSError:
                registro.errore("chiusura.provvisorio_non_tolto")
                continue
            tolti += 1
    return tolti


def _difetti(connessione: sqlite3.Connection) -> list[str]:
    try:
        righe = connessione.execute(f"PRAGMA integrity_check({QUANTI_DIFETTI})").fetchall()
    except sqlite3.DatabaseError as guasto:
        return [type(guasto).__name__]
    detti = [str(riga[0]) for riga in righe]
    return [] if detti == ["ok"] else detti


def _legami_rotti(connessione: sqlite3.Connection) -> int:
    try:
        return len(connessione.execute("PRAGMA foreign_key_check").fetchall())
    except sqlite3.DatabaseError:
        return -1


def controlla(connessione: sqlite3.Connection, dove: Posizione) -> dict:
    difetti = _difetti(connessione)
    legami = 0 if difetti else _legami_rotti(connessione)
    try:
        provvisori = togli_i_provvisori(dove)
    except OSError:
        registro.errore("chiusura.provvisori_non_guardati")
        provvisori = 0
    sano = not difetti and legami == 0
    esito = {"quando": datetime.now(timezone.utc).isoformat(timespec="seconds"),
             "archivio": SANO if sano else ROVINATO, "difetti": len(difetti),
             "legami_rotti": max(legami, 0), "provvisori": provvisori, "visto": False}
    if sano:
        registro.avviso("chiusura.di_colpo_tutto_a_posto", provvisori=provvisori)
    else:
        registro.errore("chiusura.di_colpo_archivio_rovinato", difetti=len(difetti),
                        legami_rotti=max(legami, 0))
    scrivi(dove, esito)
    return esito


def scrivi(dove: Posizione, esito: dict) -> None:
    provvisorio = _esito(dove).with_name(ESITO + ".nuovo")
    provvisorio.write_text(json.dumps(esito), encoding="utf-8")
    os.replace(provvisorio, _esito(dove))


def da_dire(dove: Posizione) -> dict | None:
    try:
        esito = json.loads(_esito(dove).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(esito, dict) or esito.get("archivio") not in (SANO, ROVINATO):
        return None
    if esito.get("visto") and esito["archivio"] == SANO:
        return None
    return esito


def visto(dove: Posizione) -> None:
    esito = da_dire(dove)
    if esito is None or esito["archivio"] != SANO:
        return
    scrivi(dove, {**esito, "visto": True})
