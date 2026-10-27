from __future__ import annotations

import json
from typing import Callable

from officina import registro
from officina.archivio.accesso import Archivio
from officina.archivio.database import tutti
from officina.errori import DaRifare, FileNonLeggibile
from officina.importazione import metadati, ripasso
from officina.modello import file_media
from officina.modello.scatti import marca_senza_data
from officina.sicuro import dall_archivio

FINO_A = "date_da_rileggere"
DA = "date_rilette_fino_a"
RIMANDATE = "date_rimandate"
A_GRUPPI = 50
IN_FILA = ("SELECT id, scatto_id FROM file_media WHERE origine_data = 'assente' "
           "AND id > ? AND id <= ? ORDER BY id LIMIT ?")
RIPRESI = ("SELECT id, scatto_id FROM file_media WHERE origine_data = 'assente' "
           "AND id IN (SELECT value FROM json_each(?)) ORDER BY id")
NEL_SICURO_CHIUSO = "è solo nell'Archivio sicuro, che è chiuso: aprilo e riguarda"
NEL_SICURO_ROVINATO = "nell'Archivio sicuro è rovinato"
NEL_SICURO_DIVERSO = ("nell'Archivio sicuro c'è solo una versione cambiata "
                      "dopo l'importazione")


def quanti_restano(archivio: Archivio) -> int:
    fino_a = archivio.stato(FINO_A)
    if not fino_a:
        return 0
    with archivio.lettura() as connessione:
        return tutti(connessione,
                     "SELECT count(*) AS q FROM file_media WHERE origine_data = 'assente' "
                     "AND (id > ? AND id <= ? "
                     "OR id IN (SELECT value FROM json_each(?)))",
                     int(archivio.stato(DA, 0) or 0), int(fino_a),
                     json.dumps(ripasso.rimandati(archivio, RIMANDATE)))[0]["q"]


def uno(archivio: Archivio, riga) -> bool:
    try:
        with archivio.lettura() as connessione:
            percorso = file_media.da_guardare(connessione, riga["id"])
    except FileNonLeggibile:
        return False
    if percorso is None:
        return False
    try:
        with dall_archivio.attento(percorso):
            dati = metadati.leggi(percorso)
    except FileNonLeggibile:
        return False
    if not dati.ha_data:
        return False
    with archivio.scrittura() as connessione:
        connessione.execute(
            "UPDATE file_media SET data_locale = ?, fuso_minuti = ?, istante_utc = ?, "
            "origine_data = ?, latitudine = coalesce(latitudine, ?), "
            "longitudine = coalesce(longitudine, ?) "
            "WHERE id = ? AND origine_data = 'assente'",
            (dati.data_locale, dati.fuso_minuti, dati.istante_utc, dati.origine_data,
             dati.latitudine, dati.longitudine, riga["id"]))
        if riga["scatto_id"]:
            cambiato = connessione.execute(
                "UPDATE scatti SET data_locale = ?, fuso_minuti = ?, istante_utc = ?, "
                "giorno = ?, origine_data = ?, latitudine = coalesce(latitudine, ?), "
                "longitudine = coalesce(longitudine, ?) "
                "WHERE id = ? AND origine_data = 'assente'",
                (dati.data_locale, dati.fuso_minuti, dati.istante_utc, dati.giorno,
                 dati.origine_data, dati.latitudine, dati.longitudine,
                 riga["scatto_id"])).rowcount
            if cambiato:
                marca_senza_data(connessione, riga["scatto_id"])
    return True


def tutti_i_file(archivio: Archivio, basta: Callable[[], bool] = lambda: False,
                 al_passo: Callable[[int], None] | None = None) -> int:
    if not archivio.stato(FINO_A):
        return 0
    esito = ripasso.passa(archivio, fino_a=FINO_A, da=DA, lasciati=RIMANDATE,
                          in_fila=IN_FILA, ripresi=RIPRESI,
                          fai=lambda riga: uno(archivio, riga),
                          avviso="rileggi_date.file_non_letto", basta=basta,
                          al_passo=al_passo, a_gruppi=A_GRUPPI)
    trovate = esito.fatti
    if esito.fermato:
        return trovate
    trovate += dai_compagni(archivio)
    if esito.rimandati:
        registro.evento("rileggi_date.rimandate", quanti=esito.rimandati)
        return trovate
    ripasso.finisci(archivio, FINO_A, DA, RIMANDATE)
    registro.evento("rileggi_date.finito", quanti=trovate)
    return trovate


def dai_compagni(archivio: Archivio) -> int:
    with archivio.scrittura() as connessione:
        righe = tutti(
            connessione,
            "SELECT s.id AS scatto_id, f.data_locale, f.fuso_minuti, f.istante_utc, "
            "f.origine_data FROM scatti s JOIN file_media f ON f.scatto_id = s.id "
            "WHERE s.data_locale IS NULL AND s.origine_data = 'assente' "
            "AND f.data_locale IS NOT NULL ORDER BY s.id, f.ruolo != 'principale', f.id")
        fatti = set()
        for riga in righe:
            if riga["scatto_id"] in fatti:
                continue
            fatti.add(riga["scatto_id"])
            connessione.execute(
                "UPDATE scatti SET data_locale = ?, fuso_minuti = ?, istante_utc = ?, "
                "giorno = ?, origine_data = ? WHERE id = ?",
                (riga["data_locale"], riga["fuso_minuti"], riga["istante_utc"],
                 riga["data_locale"][:10], riga["origine_data"], riga["scatto_id"]))
            marca_senza_data(connessione, riga["scatto_id"])
    return len(fatti)


def perche(archivio: Archivio) -> list[dict]:
    with archivio.lettura() as connessione:
        righe = tutti(
            connessione,
            "SELECT f.id FROM scatti s JOIN file_media f ON f.scatto_id = s.id "
            "WHERE s.data_locale IS NULL AND s.fuori_archivio = 0 ORDER BY f.id")
        percorsi = [(riga["id"], _da_guardare(connessione, riga["id"])) for riga in righe]
    gruppi: dict[tuple, int] = {}
    for _, percorso in percorsi:
        if percorso is None:
            chiave = ("?", (("file", "non trovato: il disco o la cartella non ci sono"),))
        elif isinstance(percorso, str):
            chiave = ("?", (("file", percorso),))
        else:
            try:
                with dall_archivio.attento(percorso):
                    motivi = tuple(metadati.diagnosi(percorso))
            except DaRifare as errore:
                chiuso = errore.codice == dall_archivio.CHIUSO_ADESSO
                motivi = (("file", NEL_SICURO_CHIUSO if chiuso else NEL_SICURO_ROVINATO),)
            except OSError:
                motivi = (("file", "non si legge"),)
            chiave = (percorso.suffix.lower() or "senza estensione", motivi)
        gruppi[chiave] = gruppi.get(chiave, 0) + 1
    return sorted(({"tipo": tipo, "motivi": list(motivi), "quanti": quanti}
                   for (tipo, motivi), quanti in gruppi.items()),
                  key=lambda gruppo: -gruppo["quanti"])


def _da_guardare(connessione, file_id: int):
    try:
        return file_media.da_guardare(connessione, file_id)
    except DaRifare:
        return NEL_SICURO_CHIUSO
    except FileNonLeggibile:
        return NEL_SICURO_DIVERSO
