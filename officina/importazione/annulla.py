from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

from officina.archivio.database import tutti, uno


@dataclass
class Conto:
    cartella_id: int
    percorso: str
    attiva: bool
    file: int
    spariscono: int
    restano: int


SOLI_QUI = (
    "SELECT f.id FROM file_media f WHERE EXISTS (SELECT 1 FROM percorsi p "
    "WHERE p.file_id = f.id AND p.cartella_id = ?) "
    "AND NOT EXISTS (SELECT 1 FROM percorsi q WHERE q.file_id = f.id "
    "AND (q.cartella_id IS NULL OR q.cartella_id <> ?))")


def _soli_qui(connessione: sqlite3.Connection, cartella_id: int) -> list[int]:
    return [riga["id"] for riga in tutti(connessione, SOLI_QUI, cartella_id, cartella_id)]


def conta(connessione: sqlite3.Connection, cartella_id: int) -> Conto | None:
    cartella = uno(connessione, "SELECT * FROM cartelle_sorgente WHERE id = ?", cartella_id)
    if cartella is None:
        return None
    soli = _soli_qui(connessione, cartella_id)
    tutti_qui = uno(
        connessione,
        "SELECT count(DISTINCT f.scatto_id) AS scatti, count(DISTINCT f.id) AS file "
        "FROM file_media f JOIN percorsi p ON p.file_id = f.id WHERE p.cartella_id = ?",
        cartella_id)
    solo_qui = set(soli)
    tutto_qui: dict[int, bool] = {}
    for riga in tutti(
            connessione,
            "SELECT f.scatto_id, f.id FROM file_media f WHERE f.scatto_id IN ("
            "SELECT g.scatto_id FROM file_media g WHERE g.id IN (SELECT value FROM json_each(?)))",
            json.dumps(soli)):
        tutto_qui[riga["scatto_id"]] = tutto_qui.get(riga["scatto_id"], True) and riga["id"] in solo_qui
    spariscono = sum(tutto_qui.values())
    return Conto(cartella_id=cartella_id, percorso=cartella["percorso"],
                 attiva=bool(cartella["attiva"]), file=tutti_qui["file"],
                 spariscono=spariscono,
                 restano=max(tutti_qui["scatti"] - spariscono, 0))


def tolte_con_scatti(connessione: sqlite3.Connection) -> list[Conto]:
    righe = tutti(
        connessione,
        "SELECT c.id FROM cartelle_sorgente c WHERE c.attiva = 0 "
        "AND EXISTS (SELECT 1 FROM percorsi p WHERE p.cartella_id = c.id) ORDER BY c.id")
    return [conto for riga in righe if (conto := conta(connessione, riga["id"]))]


def annulla(connessione: sqlite3.Connection, cartella_id: int) -> int:
    soli = _soli_qui(connessione, cartella_id)
    toccati = [riga["scatto_id"] for riga in tutti(
        connessione,
        "SELECT DISTINCT scatto_id FROM file_media WHERE scatto_id IS NOT NULL "
        "AND id IN (SELECT value FROM json_each(?))", json.dumps(soli))]
    _rimetti_gli_originali(connessione, soli)
    connessione.execute("DELETE FROM percorsi WHERE cartella_id = ?", (cartella_id,))
    connessione.execute("DELETE FROM file_media WHERE id IN (SELECT value FROM json_each(?))",
                        (json.dumps(soli),))
    vuoti = [riga["id"] for riga in tutti(
        connessione,
        "SELECT s.id FROM scatti s WHERE s.id IN (SELECT value FROM json_each(?)) "
        "AND NOT EXISTS (SELECT 1 FROM file_media f WHERE f.scatto_id = s.id)",
        json.dumps(toccati))]
    connessione.execute("DELETE FROM scatti WHERE id IN (SELECT value FROM json_each(?))",
                        (json.dumps(vuoti),))
    for scatto_id in set(toccati) - set(vuoti):
        _rimetti_in_piedi(connessione, scatto_id)
    connessione.execute("DELETE FROM cartelle_sorgente WHERE id = ?", (cartella_id,))
    return len(vuoti)


def _rimetti_in_piedi(connessione: sqlite3.Connection, scatto_id: int) -> None:
    rimasti = tutti(connessione, "SELECT id, genere, ruolo FROM file_media WHERE scatto_id = ? "
                    "ORDER BY id", scatto_id)
    if any(riga["ruolo"] == "principale" for riga in rimasti):
        if not any(riga["ruolo"] == "movimento" for riga in rimasti):
            connessione.execute(
                "UPDATE scatti SET genere = 'foto' WHERE id = ? AND genere = 'live'", (scatto_id,))
        return
    primo = rimasti[0]
    connessione.execute("UPDATE file_media SET ruolo = 'principale' WHERE id = ?", (primo["id"],))
    connessione.execute("UPDATE scatti SET genere = ? WHERE id = ?",
                        ("video" if primo["genere"] == "video" else "foto", scatto_id))


def _rimetti_gli_originali(connessione: sqlite3.Connection, soli: list[int]) -> None:
    from officina.doppioni.decisioni import _disfa

    for riga in tutti(connessione,
                      "SELECT firma FROM doppioni_decisi WHERE scelta = 'tenuto' "
                      "AND tenuto_id IN (SELECT value FROM json_each(?))", json.dumps(soli)):
        _disfa(connessione, riga["firma"])
