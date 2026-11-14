from __future__ import annotations

import time
from pathlib import Path

from officina import registro
from officina.archivio.database import adesso, tutti
from officina.modello import segnalazioni

FORMATI = ("heic", "heif", "avif")
QUANTI_PER_GIRO = 300
DETTAGLIO = "heif_tagliato"


def da_guardare(connessione, quanti: int = QUANTI_PER_GIRO) -> list:
    return tutti(
        connessione,
        "SELECT f.id, f.impronta, f.scatto_id, "
        "(SELECT percorso FROM percorsi p WHERE p.file_id = f.id AND p.presente = 1 "
        "ORDER BY p.id LIMIT 1) AS percorso "
        "FROM file_media f LEFT JOIN heif_controllati h ON h.file_id = f.id "
        "WHERE f.genere = 'immagine' AND lower(f.formato) IN (?, ?, ?) "
        "AND (h.file_id IS NULL OR h.impronta != f.impronta) "
        "AND EXISTS (SELECT 1 FROM percorsi q WHERE q.file_id = f.id AND q.presente = 1) "
        "ORDER BY f.id LIMIT ?",
        *FORMATI, quanti)


def _guarda(percorso: str) -> int | None:
    from officina.miglioria.heif_scatole import pezzi_mancanti

    esito = pezzi_mancanti(Path(percorso))
    return None if esito is None else esito[0]


def _segna(connessione, riga, mancano: int | None) -> bool:
    connessione.execute(
        "INSERT INTO heif_controllati (file_id, impronta, mancano, controllato_il) "
        "SELECT ?, ?, ?, ? WHERE EXISTS (SELECT 1 FROM file_media WHERE id = ? "
        "AND impronta = ?) ON CONFLICT(file_id) DO UPDATE SET impronta = excluded.impronta, "
        "mancano = excluded.mancano, controllato_il = excluded.controllato_il",
        (riga["id"], riga["impronta"], mancano, adesso(), riga["id"], riga["impronta"]))
    if not mancano or riga["scatto_id"] is None:
        return False
    segnalazioni.segna(connessione, segnalazioni.NON_SI_APRE, riga["scatto_id"],
                       dettaglio=DETTAGLIO, file_id=riga["id"])
    connessione.execute("DELETE FROM impronte WHERE scatto_id = ?", (riga["scatto_id"],))
    return True


def un_giro(archivio, secondi: float = 5.0, freno=None) -> int:
    if archivio.di_prova:
        return 0
    with archivio.lettura() as connessione:
        righe = da_guardare(connessione)
    inizio = time.monotonic()
    esiti = []
    for riga in righe:
        if (freno and freno()) or time.monotonic() - inizio > secondi:
            break
        try:
            esiti.append((riga, _guarda(riga["percorso"])))
        except OSError:
            continue
    trovati = 0
    if esiti:
        with archivio.scrittura_di_servizio() as connessione:
            for riga, mancano in esiti:
                trovati += _segna(connessione, riga, mancano)
    if trovati:
        registro.avviso("heif_tagliati.trovati", quanti=trovati)
    return trovati
