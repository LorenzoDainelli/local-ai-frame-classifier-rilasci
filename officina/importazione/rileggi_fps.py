from __future__ import annotations

import json
import sqlite3
from typing import Callable

from officina import registro
from officina.archivio import database
from officina.archivio.accesso import Archivio
from officina.archivio.database import tutti
from officina.errori import FileNonLeggibile
from officina.immagini import fotogrammi
from officina.importazione import ripasso
from officina.modello import file_media
from officina.sicuro import dall_archivio

FINO_A = "fps_da_leggere"
DA = "fps_letti_fino_a"
RIMANDATI = "fps_rimandati"
A_GRUPPI = 50
IN_FILA = ("SELECT id FROM file_media WHERE genere = 'video' AND fps IS NULL "
           "AND id > ? AND id <= ? ORDER BY id LIMIT ?")
RIPRESI = ("SELECT id FROM file_media WHERE genere = 'video' AND fps IS NULL "
           "AND id IN (SELECT value FROM json_each(?)) ORDER BY id")


def da_leggere(connessione: sqlite3.Connection, file_id: int) -> None:
    fino_a = database.leggi_stato(connessione, FINO_A)
    if not isinstance(fino_a, int) or isinstance(fino_a, bool) or fino_a < file_id:
        database.scrivi_stato(connessione, FINO_A, file_id)


def quanti_restano(archivio: Archivio) -> int:
    fino_a = archivio.stato(FINO_A)
    if not fino_a:
        return 0
    with archivio.lettura() as connessione:
        return tutti(connessione,
                     "SELECT count(*) AS q FROM file_media WHERE genere = 'video' "
                     "AND fps IS NULL "
                     "AND (id > ? AND id <= ? OR id IN (SELECT value FROM json_each(?)))",
                     int(archivio.stato(DA, 0) or 0), int(fino_a),
                     json.dumps(ripasso.rimandati(archivio, RIMANDATI)))[0]["q"]


def uno(archivio: Archivio, file_id: int) -> bool:
    try:
        with archivio.lettura() as connessione:
            percorso = file_media.da_guardare(connessione, file_id)
    except FileNonLeggibile:
        return False
    if percorso is None:
        return False
    with dall_archivio.attento(percorso):
        fps = fotogrammi.fps_dal_decodificatore(percorso)
    if fps is None:
        return False
    with archivio.scrittura() as connessione:
        connessione.execute("UPDATE file_media SET fps = ? WHERE id = ? AND fps IS NULL",
                            (fps, file_id))
    return True


def _chiudi_se_fermo(archivio: Archivio, fino_a) -> bool:
    with archivio.scrittura() as connessione:
        if database.leggi_stato(connessione, FINO_A) != fino_a:
            return False
        connessione.executemany("DELETE FROM stato WHERE chiave = ?",
                                [(chiave,) for chiave in (FINO_A, DA, RIMANDATI)])
    return True


def tutti_i_file(archivio: Archivio, basta: Callable[[], bool] = lambda: False) -> int:
    fatti = 0
    while fino_a := archivio.stato(FINO_A):
        esito = ripasso.passa(archivio, fino_a=FINO_A, da=DA, lasciati=RIMANDATI,
                              in_fila=IN_FILA, ripresi=RIPRESI,
                              fai=lambda riga: uno(archivio, riga["id"]),
                              avviso="rileggi_fps.file_non_letto", basta=basta,
                              a_gruppi=A_GRUPPI)
        fatti += esito.fatti
        if esito.fermato:
            return fatti
        if esito.rimandati:
            registro.evento("rileggi_fps.rimandati", quanti=esito.rimandati)
            return fatti
        if _chiudi_se_fermo(archivio, fino_a):
            registro.evento("rileggi_fps.finito", quanti=fatti)
    return fatti
