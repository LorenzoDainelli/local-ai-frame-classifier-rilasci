from __future__ import annotations

import json
from typing import Callable

from officina import registro
from officina.archivio.accesso import Archivio
from officina.archivio.database import tutti
from officina.errori import FileNonLeggibile
from officina.importazione import metadati, ripasso
from officina.modello import file_media
from officina.sicuro import dall_archivio

FINO_A = "macchine_da_rileggere"
DA = "macchine_rilette_fino_a"
RIMANDATE = "macchine_rimandate"
A_GRUPPI = 50
IN_FILA = "SELECT id FROM file_media WHERE id > ? AND id <= ? ORDER BY id LIMIT ?"
RIPRESI = ("SELECT id FROM file_media WHERE id IN (SELECT value FROM json_each(?)) "
           "ORDER BY id")


def quanti_restano(archivio: Archivio) -> int:
    fino_a = archivio.stato(FINO_A)
    if not fino_a:
        return 0
    with archivio.lettura() as connessione:
        return tutti(connessione,
                     "SELECT count(*) AS q FROM file_media WHERE id > ? AND id <= ? "
                     "OR id IN (SELECT value FROM json_each(?))",
                     int(archivio.stato(DA, 0) or 0), int(fino_a),
                     json.dumps(ripasso.rimandati(archivio, RIMANDATE)))[0]["q"]


def uno(archivio: Archivio, file_id: int) -> bool:
    try:
        with archivio.lettura() as connessione:
            percorso = file_media.da_guardare(connessione, file_id)
    except FileNonLeggibile:
        return False
    if percorso is None:
        return False
    try:
        with dall_archivio.attento(percorso):
            dati = metadati.leggi(percorso)
    except FileNonLeggibile:
        return False
    if not dati.marca and not dati.modello:
        return False
    with archivio.scrittura() as connessione:
        connessione.execute(
            "UPDATE file_media SET marca = coalesce(marca, ?), modello = coalesce(modello, ?) "
            "WHERE id = ?", (dati.marca, dati.modello, file_id))
    return True


def tutti_i_file(archivio: Archivio, basta: Callable[[], bool] = lambda: False) -> int:
    if not archivio.stato(FINO_A):
        return 0
    esito = ripasso.passa(archivio, fino_a=FINO_A, da=DA, lasciati=RIMANDATE,
                          in_fila=IN_FILA, ripresi=RIPRESI,
                          fai=lambda riga: uno(archivio, riga["id"]),
                          avviso="rileggi_macchine.file_non_letto", basta=basta,
                          a_gruppi=A_GRUPPI)
    if esito.fermato:
        return esito.fatti
    if esito.rimandati:
        registro.evento("rileggi_macchine.rimandate", quanti=esito.rimandati)
        return esito.fatti
    ripasso.finisci(archivio, FINO_A, DA, RIMANDATE)
    registro.evento("rileggi_macchine.finito", quanti=esito.fatti)
    return esito.fatti
