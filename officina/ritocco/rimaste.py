from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

from officina import registro
from officina.archivio.database import tutti
from officina.importazione import scansione
from officina.miglioria import attesa
from officina.ritocco import coda, copia

TOPPA = "togli-"
USATI = ("SELECT f.pronta FROM ritocchi_lavori_file f JOIN ritocchi_lavori l "
         "ON l.id = f.lavoro_id WHERE l.stato <> 'fatto'",
         "SELECT in_preparazione FROM ritoccate",
         "SELECT risultato FROM ritocchi",
         "SELECT pronta_b FROM sfide_togli",
         "SELECT percorso FROM ritocchi_in_chiaro")
VICINI = ("SELECT percorso FROM percorsi WHERE file_id IN (SELECT file_id FROM ritocchi) "
          "UNION SELECT percorso_copia FROM ritoccate "
          "UNION SELECT percorso_migliorata FROM migliorie WHERE percorso_migliorata IS NOT "
          "NULL AND file_id IN (SELECT file_id FROM ritocchi)")


def butta(archivio) -> int:
    with copia._UNO_ALLA_VOLTA:
        with archivio.lettura() as connessione:
            cartelle = _cartelle(connessione, Path(archivio.dove.radice))
        trovati = [file for cartella in sorted(cartelle) for file in _di_lavoro(cartella)]
        if not trovati:
            return 0
        with archivio.lettura() as connessione:
            if coda.in_stato(connessione, coda.IN_LAVORO):
                return 0
            nomi = _usati(connessione)
        tolti = 0
        for file in trovati:
            if file.name in nomi:
                continue
            try:
                file.unlink()
            except OSError as errore:
                registro.avviso("ritocco.rimasta_non_tolta",
                                **registro.dove_si_e_rotto(errore))
                continue
            tolti += 1
    if tolti:
        registro.evento("ritocco.rimaste_tolte", file=tolti)
    return tolti


def _cartelle(connessione: sqlite3.Connection, radice: Path) -> set[Path]:
    cartelle = {Path(riga["percorso"]) / attesa.NOME
                for riga in scansione.cartelle(connessione, solo_attive=False)}
    cartelle.add(radice / attesa.NOME)
    cartelle.update(Path(riga[0]).parent / attesa.NOME
                    for riga in tutti(connessione, VICINI) if riga[0])
    return cartelle


def _di_lavoro(cartella: Path) -> list[Path]:
    try:
        with os.scandir(cartella) as voci:
            return [Path(voce.path) for voce in voci
                    if voce.name.startswith((copia.PREFISSO + "-", TOPPA))
                    and voce.is_file(follow_symlinks=False)]
    except OSError:
        return []


def _usati(connessione: sqlite3.Connection) -> set[str]:
    usati = {riga[0] for domanda in USATI for riga in tutti(connessione, domanda) if riga[0]}
    for riga in tutti(connessione, "SELECT toppe_b FROM sfide_togli"):
        toppe = json.loads(riga[0] or "{}")
        usati.update(toppa["risultato"] for toppa in toppe.values()
                     if toppa.get("risultato"))
    return {Path(percorso).name for percorso in usati}
