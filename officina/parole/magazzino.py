from __future__ import annotations

import json
import sqlite3
import unicodedata
from typing import Sequence

from officina.importazione import gruppi
from officina.archivio.database import adesso, inserisci, tutti, uno
from officina.modello import segnalazioni

CHIUSO = segnalazioni.clausola(segnalazioni.NON_SI_APRE)


def normalizza(testo: str) -> str:
    piatto = unicodedata.normalize("NFKD", testo or "")
    senza = "".join(c for c in piatto if not unicodedata.combining(c))
    return " ".join(senza.lower().replace("'", " ").split())


def scrivi(connessione: sqlite3.Connection, scatto_id: int, file_id: int | None,
           testo: str, modello: str, versione: str,
           riquadro: Sequence[float] | None = None,
           fotogramma: int = 0) -> int | None:
    cercabile = normalizza(testo)
    if not cercabile:
        return None
    return inserisci(
        connessione,
        "INSERT INTO scritte (scatto_id, file_id, testo, cercabile, riquadro, "
        "fotogramma, modello, versione, letta_il) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        scatto_id, file_id, testo.strip(), cercabile,
        json.dumps(list(riquadro)) if riquadro else None,
        fotogramma, modello, versione, adesso(),
    )


def segna_letto(connessione: sqlite3.Connection, scatto_id: int,
                modello: str, versione: str, quante: int) -> None:
    connessione.execute(
        "INSERT INTO scritte_lette (scatto_id, modello, versione, quante, letta_il) "
        "VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT(scatto_id, modello, versione) DO UPDATE SET "
        "quante = excluded.quante, letta_il = excluded.letta_il",
        (scatto_id, modello, versione, quante, adesso()),
    )


def quanti_da_leggere(connessione: sqlite3.Connection, modello: str,
                      versione: str) -> int:
    riga = uno(
        connessione,
        "SELECT count(*) AS q FROM scatti s WHERE s.fuori_archivio = 0"
        + CHIUSO + gruppi.clausola(connessione, "intelligenza") +
        " AND NOT EXISTS (SELECT 1 FROM scritte_lette l WHERE l.scatto_id = s.id "
        "AND l.modello = ? AND l.versione = ?)", modello, versione)
    return int(riga["q"]) if riga else 0


def da_leggere(connessione: sqlite3.Connection, modello: str, versione: str,
               quanti: int = 32, escludi: Sequence[int] = (),
               fra: Sequence[int] | None = None) -> list[sqlite3.Row]:
    parametri: list = []
    if fra is None:
        da_dove = "SELECT s.id, s.genere FROM scatti s WHERE s.fuori_archivio = 0"
    elif not fra:
        return []
    else:
        da_dove = ("SELECT s.id, s.genere FROM json_each(?) AS j "
                   "CROSS JOIN scatti s ON s.id = j.value WHERE s.fuori_archivio = 0")
        parametri.append(json.dumps(list(fra)))
    fuori = ""
    parametri.extend([modello, versione])
    if escludi:
        fuori = " AND s.id NOT IN (SELECT value FROM json_each(?))"
        parametri.append(json.dumps(list(escludi)))
    parametri.append(quanti)
    return tutti(
        connessione,
        f"""
        {da_dove}{CHIUSO}{gruppi.clausola(connessione, 'intelligenza')}
          AND NOT EXISTS (SELECT 1 FROM scritte_lette l
                          WHERE l.scatto_id = s.id AND l.modello = ?
                            AND l.versione = ?){fuori}
        ORDER BY s.id LIMIT ?
        """,
        *parametri,
    )


def di_scatto(connessione: sqlite3.Connection, scatto_id: int) -> list[sqlite3.Row]:
    return tutti(connessione,
                 "SELECT * FROM scritte WHERE scatto_id = ? "
                 "ORDER BY fotogramma, id", scatto_id)


def cerca(connessione: sqlite3.Connection, frase: str,
          quanti: int = 60) -> list[sqlite3.Row]:
    parole = [p for p in normalizza(frase).split() if len(p) >= 2]
    if not parole:
        return []
    condizioni = " AND ".join(["cercabile LIKE ?"] * len(parole))
    parametri = [f"%{parola}%" for parola in parole]
    parametri.append(quanti)
    return tutti(
        connessione,
        f"""
        SELECT scatto_id, file_id, min(testo) AS testo FROM scritte
        WHERE {condizioni}
        GROUP BY scatto_id ORDER BY scatto_id DESC LIMIT ?
        """,
        *parametri,
    )


def quante_ce_ne_sono(connessione: sqlite3.Connection) -> int:
    riga = uno(connessione, "SELECT count(*) AS q FROM scritte")
    return int(riga["q"]) if riga else 0


def dimentica_le_vecchie(connessione: sqlite3.Connection, scatto_id: int) -> None:
    connessione.execute("DELETE FROM scritte WHERE scatto_id = ?", (scatto_id,))
    connessione.execute("DELETE FROM descrizioni WHERE scatto_id = ?", (scatto_id,))


def scrivi_descrizione(connessione: sqlite3.Connection, scatto_id: int,
                       file_id: int | None, testo: str, modello: str,
                       versione: str) -> bool:
    cercabile = normalizza(testo)
    if not cercabile:
        return False
    connessione.execute(
        "INSERT INTO descrizioni (scatto_id, file_id, testo, cercabile, modello, "
        "versione, fatta_il) VALUES (?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(scatto_id) DO UPDATE SET file_id = excluded.file_id, "
        "testo = excluded.testo, cercabile = excluded.cercabile, "
        "modello = excluded.modello, versione = excluded.versione, "
        "fatta_il = excluded.fatta_il",
        (scatto_id, file_id, testo.strip(), cercabile, modello, versione, adesso()),
    )
    return True


def descrizione_di(connessione: sqlite3.Connection, scatto_id: int) -> str:
    riga = uno(connessione, "SELECT testo FROM descrizioni WHERE scatto_id = ?",
               scatto_id)
    return riga["testo"] if riga else ""


PAROLE_VUOTE = {
    "il", "lo", "la", "i", "gli", "le", "un", "uno", "una", "di", "a", "da",
    "in", "con", "su", "per", "tra", "fra", "e", "o", "del", "della", "dei",
    "delle", "degli", "al", "alla", "ai", "alle", "nel", "nella", "nei",
    "nelle", "sul", "sulla", "che", "foto", "fotografia", "immagine",
}


def cerca_descrizioni(connessione: sqlite3.Connection, frase: str,
                      quanti: int = 60) -> list[sqlite3.Row]:
    parole = [p for p in normalizza(frase).split()
              if len(p) >= 3 and p not in PAROLE_VUOTE]
    if not parole:
        return []
    condizioni = " AND ".join(["cercabile LIKE ?"] * len(parole))
    parametri = [f"%{parola}%" for parola in parole]
    parametri.append(quanti)
    return tutti(
        connessione,
        f"""
        SELECT scatto_id, file_id, testo FROM descrizioni
        WHERE {condizioni}
        ORDER BY scatto_id DESC LIMIT ?
        """,
        *parametri,
    )


def ci_sono_letture_vecchie(connessione: sqlite3.Connection, modello: str,
                            versione: str) -> bool:
    riga = uno(connessione,
               "SELECT 1 AS c FROM scritte_lette WHERE modello = ? AND versione <> ? "
               "LIMIT 1", modello, versione)
    return riga is not None
