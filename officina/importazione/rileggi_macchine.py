from __future__ import annotations

from typing import Callable

from officina import registro
from officina.archivio.accesso import Archivio
from officina.archivio.database import tutti
from officina.errori import FileNonLeggibile
from officina.importazione import metadati
from officina.modello import file_media

FINO_A = "macchine_da_rileggere"
DA = "macchine_rilette_fino_a"
A_GRUPPI = 50


def quanti_restano(archivio: Archivio) -> int:
    fino_a = archivio.stato(FINO_A)
    if not fino_a:
        return 0
    with archivio.lettura() as connessione:
        return tutti(connessione,
                     "SELECT count(*) AS q FROM file_media WHERE id > ? AND id <= ?",
                     int(archivio.stato(DA, 0) or 0), int(fino_a))[0]["q"]


def uno(archivio: Archivio, file_id: int) -> bool:
    with archivio.lettura() as connessione:
        percorso = file_media.percorso_migliore(connessione, file_id)
    if percorso is None:
        return False
    try:
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
    fino_a = archivio.stato(FINO_A)
    if not fino_a:
        return 0
    trovate = 0
    da = int(archivio.stato(DA, 0) or 0)
    while not basta():
        with archivio.lettura() as connessione:
            righe = tutti(
                connessione,
                "SELECT id FROM file_media WHERE id > ? AND id <= ? ORDER BY id LIMIT ?",
                da, int(fino_a), A_GRUPPI)
        if not righe:
            break
        for riga in righe:
            if basta():
                break
            try:
                if uno(archivio, riga["id"]):
                    trovate += 1
            except Exception:
                registro.avviso("rileggi_macchine.file_non_letto")
            da = riga["id"]
            archivio.salva_stato(DA, da)
    if basta():
        return trovate
    with archivio.scrittura() as connessione:
        connessione.execute("DELETE FROM stato WHERE chiave IN (?, ?)", (FINO_A, DA))
    registro.evento("rileggi_macchine.finito", quanti=trovate)
    return trovate
