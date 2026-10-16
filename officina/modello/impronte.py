from __future__ import annotations

import json
import sqlite3
from typing import Sequence

from officina.importazione import gruppi
from officina.archivio.database import adesso, tutti, uno
from officina.descrittori import vettori
from officina.modello import segnalazioni

CHIUSO = segnalazioni.clausola(segnalazioni.NON_SI_APRE)


def scrivi(connessione: sqlite3.Connection, scatto_id: int, file_id: int | None,
           descrittore: str, versione: str, inquadratura: str, metodo: str,
           riquadro: tuple[float, float, float, float] | None,
           valori: Sequence[float], fotogramma: int = 0,
           istante_ms: int | None = None) -> None:
    dati = vettori.a_byte(valori)
    connessione.execute(
        """
        INSERT INTO impronte (scatto_id, file_id, descrittore, versione,
                              inquadratura, metodo, riquadro, fotogramma,
                              istante_ms, dimensione, valori, calcolata_il)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(scatto_id, descrittore, versione, inquadratura, fotogramma)
        DO UPDATE SET metodo = excluded.metodo, riquadro = excluded.riquadro,
                      istante_ms = excluded.istante_ms,
                      dimensione = excluded.dimensione,
                      valori = excluded.valori,
                      calcolata_il = excluded.calcolata_il
        """,
        (scatto_id, file_id, descrittore, versione, inquadratura, metodo,
         json.dumps([round(v, 5) for v in riquadro]) if riquadro else None,
         fotogramma, istante_ms, vettori.quanti_numeri(dati), dati, adesso()),
    )


def togli_di(connessione: sqlite3.Connection, descrittore: str,
             versione: str | None = None) -> int:
    if versione is None:
        cursore = connessione.execute(
            "DELETE FROM impronte WHERE descrittore = ?", (descrittore,))
    else:
        cursore = connessione.execute(
            "DELETE FROM impronte WHERE descrittore = ? AND versione = ?",
            (descrittore, versione))
    return cursore.rowcount


def scatti_da_fare(connessione: sqlite3.Connection, descrittore: str,
                   versione: str, quanti: int = 200,
                   escludi: Sequence[int] | None = None,
                   fra: Sequence[int] | None = None) -> list[sqlite3.Row]:
    parametri: list = []
    if fra is None:
        da_dove = "SELECT s.id, s.genere, s.durata_ms FROM scatti s WHERE s.fuori_archivio = 0"
    elif not fra:
        return []
    else:
        da_dove = ("SELECT s.id, s.genere, s.durata_ms FROM json_each(?) AS j "
                   "CROSS JOIN scatti s ON s.id = j.value WHERE s.fuori_archivio = 0")
        parametri.append(json.dumps(list(fra)))
    fuori = ""
    if escludi:
        fuori = " AND s.id NOT IN (SELECT value FROM json_each(?))"
        parametri.append(json.dumps(list(escludi)))
    parametri.extend([descrittore, versione, quanti])
    return tutti(
        connessione,
        f"""
        {da_dove}{fuori}{CHIUSO}{gruppi.clausola(connessione, 'intelligenza')}
          AND NOT EXISTS (
              SELECT 1 FROM impronte i
              WHERE i.scatto_id = s.id AND i.descrittore = ?
                AND i.versione = ?
          )
        ORDER BY s.istante_utc DESC, s.id DESC
        LIMIT ?
        """,
        *parametri,
    )


def quanti_da_fare(connessione: sqlite3.Connection, descrittore: str,
                   versione: str) -> int:
    riga = uno(
        connessione,
        """
        SELECT count(*) AS quanti FROM scatti s
        WHERE s.fuori_archivio = 0{chiuso}
          AND NOT EXISTS (
              SELECT 1 FROM impronte i
              WHERE i.scatto_id = s.id AND i.descrittore = ? AND i.versione = ?
          )
        """.format(chiuso=CHIUSO + gruppi.clausola(connessione, "intelligenza")),
        descrittore, versione,
    )
    return riga["quanti"] if riga else 0


def avanzamento(connessione: sqlite3.Connection) -> list[dict]:
    totale = uno(connessione,
                 "SELECT count(*) AS q FROM scatti WHERE fuori_archivio = 0")
    quanti_scatti = totale["q"] if totale else 0
    fuori = []
    for riga in tutti(connessione,
                      """
                      SELECT descrittore, versione, count(*) AS impronte,
                             count(DISTINCT scatto_id) AS scatti,
                             max(calcolata_il) AS ultima,
                             max(dimensione) AS dimensione
                      FROM impronte GROUP BY descrittore, versione
                      ORDER BY descrittore
                      """):
        fuori.append({
            "descrittore": riga["descrittore"],
            "versione": riga["versione"],
            "impronte": riga["impronte"],
            "scatti": riga["scatti"],
            "mancano": max(0, quanti_scatti - riga["scatti"]),
            "ultima": riga["ultima"],
            "dimensione": riga["dimensione"],
        })
    return fuori


def peso(connessione: sqlite3.Connection) -> int:
    riga = uno(connessione, "SELECT sum(dimensione) * 4 AS byte FROM impronte")
    return int(riga["byte"] or 0) if riga else 0


def di_scatto(connessione: sqlite3.Connection, scatto_id: int,
              descrittore: str | None = None) -> list[sqlite3.Row]:
    if descrittore:
        return tutti(connessione,
                     "SELECT * FROM impronte WHERE scatto_id = ? AND descrittore = ? "
                     "ORDER BY inquadratura, fotogramma", scatto_id, descrittore)
    return tutti(connessione,
                 "SELECT * FROM impronte WHERE scatto_id = ? "
                 "ORDER BY descrittore, inquadratura, fotogramma", scatto_id)


def una(connessione: sqlite3.Connection, scatto_id: int, descrittore: str,
        versione: str, inquadratura: str, fotogramma: int = 0) -> sqlite3.Row | None:
    return uno(
        connessione,
        "SELECT * FROM impronte WHERE scatto_id = ? AND descrittore = ? "
        "AND versione = ? AND inquadratura = ? AND fotogramma = ?",
        scatto_id, descrittore, versione, inquadratura, fotogramma,
    )


PEZZO = 900


def _a_pezzi(chi, connessione, *argomenti):
    *davanti, solo_scatti = argomenti
    ordinati = sorted(set(solo_scatti))
    ids: list[int] = []
    valori: list[bytes] = []
    for inizio in range(0, len(ordinati), PEZZO):
        suoi_ids, suoi_valori = chi(connessione, *davanti,
                                    solo_scatti=ordinati[inizio:inizio + PEZZO])
        ids.extend(suoi_ids)
        valori.extend(suoi_valori)
    return ids, valori


def passata(connessione: sqlite3.Connection, descrittore: str, versione: str,
            inquadratura: str, solo_scatti: Sequence[int] | None = None
            ) -> tuple[list[int], list[bytes]]:
    condizione = ""
    parametri: list = [descrittore, versione, inquadratura]
    if solo_scatti is not None:
        if not solo_scatti:
            return [], []
        if len(solo_scatti) > PEZZO:
            return _a_pezzi(passata, connessione, descrittore, versione, inquadratura, solo_scatti)
        segnaposti = ",".join("?" * len(solo_scatti))
        condizione = f" AND scatto_id IN ({segnaposti})"
        parametri.extend(solo_scatti)

    righe = tutti(
        connessione,
        f"""
        SELECT scatto_id, valori FROM impronte
        WHERE descrittore = ? AND versione = ? AND inquadratura = ?{condizione}
          AND fotogramma = 0
        ORDER BY scatto_id
        """,
        *parametri,
    )
    return [riga["scatto_id"] for riga in righe], [riga["valori"] for riga in righe]


def tutti_i_fotogrammi(connessione: sqlite3.Connection, descrittore: str,
                       versione: str, inquadratura: str,
                       solo_scatti: Sequence[int] | None = None
                       ) -> tuple[list[int], list[bytes]]:
    condizione = ""
    parametri: list = [descrittore, versione, inquadratura]
    if solo_scatti is not None:
        if not solo_scatti:
            return [], []
        if len(solo_scatti) > PEZZO:
            return _a_pezzi(tutti_i_fotogrammi, connessione, descrittore, versione, inquadratura, solo_scatti)
        segnaposti = ",".join("?" * len(solo_scatti))
        condizione = f" AND scatto_id IN ({segnaposti})"
        parametri.extend(solo_scatti)
    righe = tutti(
        connessione,
        f"""
        SELECT scatto_id, valori FROM impronte
        WHERE descrittore = ? AND versione = ? AND inquadratura = ?{condizione}
        ORDER BY scatto_id, fotogramma
        """,
        *parametri,
    )
    return [riga["scatto_id"] for riga in righe], [riga["valori"] for riga in righe]


def della_griglia(connessione: sqlite3.Connection, descrittore: str,
                  versione: str, solo_scatti: Sequence[int] | None = None
                  ) -> tuple[list[int], list[bytes]]:
    condizione = ""
    parametri: list = [descrittore, versione]
    if solo_scatti is not None:
        if not solo_scatti:
            return [], []
        if len(solo_scatti) > PEZZO:
            return _a_pezzi(della_griglia, connessione, descrittore, versione, solo_scatti)
        segnaposti = ",".join("?" * len(solo_scatti))
        condizione = f" AND scatto_id IN ({segnaposti})"
        parametri.extend(solo_scatti)
    righe = tutti(
        connessione,
        f"""
        SELECT scatto_id, valori FROM impronte
        WHERE descrittore = ? AND versione = ?
          AND inquadratura GLOB 'griglia_r[0-9][0-9]c[0-9][0-9]'{condizione}
        ORDER BY scatto_id, inquadratura, fotogramma
        """,
        *parametri,
    )
    return [riga["scatto_id"] for riga in righe], [riga["valori"] for riga in righe]


def modelli_presenti(connessione: sqlite3.Connection) -> list[tuple[str, str]]:
    return [(riga["descrittore"], riga["versione"]) for riga in tutti(
        connessione,
        "SELECT DISTINCT descrittore, versione FROM impronte ORDER BY descrittore")]
