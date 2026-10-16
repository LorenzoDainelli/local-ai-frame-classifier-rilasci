from __future__ import annotations

import bisect
import sqlite3

from officina.archivio.database import adesso, esegui, tutti, uno, valore
from officina.errori import OperazioneNonPermessa

_GIA_PASSATO = (
    "EXISTS (SELECT 1 FROM etichette e WHERE e.scatto_id = s.id "
    "AND e.origine = 'utente')"
)

_NON_DECISO_QUI = (
    "NOT EXISTS (SELECT 1 FROM etichette d WHERE d.scatto_id = s.id "
    "AND d.nodo_id = ?)"
)


def apri(connessione: sqlite3.Connection, nodo_id: int) -> None:
    if uno(connessione, "SELECT 1 FROM nodi WHERE id = ?", nodo_id) is None:
        raise OperazioneNonPermessa("Quel nodo non c'è più: ricarica la pagina.")
    esegui(
        connessione,
        "INSERT OR IGNORE INTO ripassi (nodo_id, stato, creato_il) "
        "VALUES (?, 'chiesto', ?)",
        nodo_id, adesso(),
    )


def per_nodo(connessione: sqlite3.Connection, nodo_id: int) -> sqlite3.Row | None:
    return uno(connessione, "SELECT * FROM ripassi WHERE nodo_id = ?", nodo_id)


def quanti_gia_passati(connessione: sqlite3.Connection) -> int:
    return int(valore(
        connessione,
        "SELECT count(*) FROM ("
        "  SELECT DISTINCT e.scatto_id AS id FROM etichette e"
        "   WHERE e.origine = 'utente') tue"
        " JOIN scatti s ON s.id = tue.id WHERE s.fuori_archivio = 0",
        predefinito=0,
    ))


def quanti_restano(connessione: sqlite3.Connection, nodo_id: int) -> int:
    riga = per_nodo(connessione, nodo_id)
    da = (riga["ultimo_scatto_id"] if riga else None) or 0
    return int(valore(
        connessione,
        f"SELECT count(*) FROM scatti s WHERE s.fuori_archivio = 0 "
        f"AND s.id > ? AND {_GIA_PASSATO} AND {_NON_DECISO_QUI}",
        da, nodo_id, predefinito=0,
    ))


def _restano_per_tutti(connessione: sqlite3.Connection,
                       da_dove: dict[int, int]) -> dict[int, int]:
    if not da_dove:
        return {}

    passati = [riga["id"] for riga in tutti(
        connessione,
        f"SELECT s.id FROM scatti s WHERE s.fuori_archivio = 0 AND {_GIA_PASSATO} "
        "ORDER BY s.id",
    )]
    if not passati:
        return {nodo_id: 0 for nodo_id in da_dove}
    e_passato = set(passati)

    fatti = {}
    for nodo_id, da in da_dove.items():
        fatti[nodo_id] = len(passati) - bisect.bisect_right(passati, da)

    dentro = ",".join("?" * len(da_dove))
    for riga in tutti(
        connessione,
        f"SELECT nodo_id, scatto_id FROM etichette WHERE nodo_id IN ({dentro})",
        *da_dove,
    ):
        scatto_id = riga["scatto_id"]
        if scatto_id in e_passato and scatto_id > da_dove[riga["nodo_id"]]:
            fatti[riga["nodo_id"]] -= 1
    return fatti


def da_chiedere(connessione: sqlite3.Connection) -> list[dict]:
    righe = tutti(
        connessione,
        "SELECT r.nodo_id, r.stato, r.ultimo_scatto_id, r.rivisti, n.nome "
        "FROM ripassi r JOIN nodi n ON n.id = r.nodo_id "
        "WHERE r.stato IN ('chiesto','in_corso') AND n.stato = 'attivo' "
        "ORDER BY r.creato_il, r.nodo_id",
    )
    quanti_per_nodo = _restano_per_tutti(
        connessione, {r["nodo_id"]: (r["ultimo_scatto_id"] or 0) for r in righe})
    fuori = []
    for riga in righe:
        restano = quanti_per_nodo.get(riga["nodo_id"], 0)
        if restano == 0:
            if riga["stato"] == "in_corso":
                _segna_stato(connessione, riga["nodo_id"], "finito")
            continue
        fuori.append({
            "nodo_id": riga["nodo_id"],
            "nome": riga["nome"],
            "stato": riga["stato"],
            "restano": restano,
            "rivisti": riga["rivisti"],
        })
    return fuori


def accetta(connessione: sqlite3.Connection, nodo_id: int) -> int | None:
    apri(connessione, nodo_id)
    _segna_stato(connessione, nodo_id, "in_corso")
    return prossimo(connessione, nodo_id)


def rifiuta(connessione: sqlite3.Connection, nodo_id: int) -> None:
    apri(connessione, nodo_id)
    _segna_stato(connessione, nodo_id, "rifiutato")


def prossimo(connessione: sqlite3.Connection, nodo_id: int) -> int | None:
    riga = per_nodo(connessione, nodo_id)
    da = (riga["ultimo_scatto_id"] if riga else None) or 0
    trovato = uno(
        connessione,
        f"SELECT s.id FROM scatti s WHERE s.fuori_archivio = 0 "
        f"AND s.id > ? AND {_GIA_PASSATO} AND {_NON_DECISO_QUI} "
        "ORDER BY s.id LIMIT 1",
        da, nodo_id,
    )
    return int(trovato["id"]) if trovato else None


def segna(connessione: sqlite3.Connection, nodo_id: int, scatto_id: int) -> None:
    esegui(
        connessione,
        "UPDATE ripassi SET ultimo_scatto_id = max(ifnull(ultimo_scatto_id, 0), ?), "
        "rivisti = rivisti + 1 WHERE nodo_id = ? "
        "AND ifnull(ultimo_scatto_id, 0) < ?",
        scatto_id, nodo_id, scatto_id,
    )


def abbandona(connessione: sqlite3.Connection, nodo_id: int) -> None:
    esegui(
        connessione,
        "UPDATE ripassi SET stato = 'chiesto' WHERE nodo_id = ? AND stato = 'in_corso'",
        nodo_id,
    )


def _segna_stato(connessione: sqlite3.Connection, nodo_id: int, stato: str) -> None:
    esegui(
        connessione,
        "UPDATE ripassi SET stato = ?, deciso_il = ? WHERE nodo_id = ?",
        stato, adesso(), nodo_id,
    )
