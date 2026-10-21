from __future__ import annotations

import json
import sqlite3

from officina.archivio.database import adesso, tutti, uno
from officina.ritocco import elenco, maschere
from officina.ritocco.volti import coperto_da

PERSONE = (elenco.VOLTO, elenco.PERSONA)
CORPO_COPERTO = 0.35


def _attivi(connessione: sqlite3.Connection, scatto_id: int) -> list[sqlite3.Row]:
    return tutti(
        connessione,
        "SELECT r.*, c.volto_id AS volto_del_corpo FROM ritocchi r "
        "JOIN file_media f ON f.id = r.file_id "
        "LEFT JOIN corpi c ON c.id = r.corpo_id "
        "WHERE r.scatto_id = ? AND r.stato = ? AND r.genere = ? AND r.cosa IN (?, ?) "
        "AND f.genere = 'immagine' ORDER BY r.id",
        scatto_id, elenco.FATTO, elenco.TOGLI, *PERSONE)


def _volti_presi(connessione: sqlite3.Connection, ritocco) -> set[int]:
    presi = {volto for volto in (ritocco["volto_id"], ritocco["volto_del_corpo"]) if volto}
    pezzo = maschere.apri(ritocco["maschera"])
    if pezzo is None:
        return presi
    for volto in tutti(connessione,
                       "SELECT id, riquadro FROM volti WHERE scatto_id = ? AND fotogramma = 0 "
                       "AND (file_id IS NULL OR file_id = ?)",
                       ritocco["scatto_id"], ritocco["file_id"]):
        if coperto_da(pezzo, json.loads(volto["riquadro"])):
            presi.add(volto["id"])
    return presi


def _corpi_presi(connessione: sqlite3.Connection, ritocco, volti: set[int]) -> set[int]:
    presi = {ritocco["corpo_id"]} if ritocco["corpo_id"] else set()
    pezzo = maschere.apri(ritocco["maschera"])
    if pezzo is not None and ritocco["cosa"] == elenco.PERSONA:
        for corpo in tutti(connessione,
                           "SELECT id, riquadro FROM corpi WHERE scatto_id = ? AND fotogramma = 0 "
                           "AND (file_id IS NULL OR file_id = ?)",
                           ritocco["scatto_id"], ritocco["file_id"]):
            if coperto_da(pezzo, json.loads(corpo["riquadro"]), CORPO_COPERTO):
                presi.add(corpo["id"])
    if volti:
        presi.update(riga["id"] for riga in tutti(
            connessione, "SELECT id FROM corpi WHERE volto_id IN (SELECT value FROM json_each(?))",
            json.dumps(sorted(volti))))
    return presi


def _segna(connessione: sqlite3.Connection, ritocco, dove: str, riga_id: int,
           persona_id: int | None, com_era: dict) -> None:
    connessione.execute(
        "INSERT INTO persone_tolte (ritocco_id, scatto_id, dove, riga_id, persona_id, "
        "com_era) VALUES (?, ?, ?, ?, ?, ?)",
        (ritocco["id"], ritocco["scatto_id"], dove, riga_id, persona_id, json.dumps(com_era)))


def _togli(connessione: sqlite3.Connection, ritocco) -> None:
    volti = _volti_presi(connessione, ritocco)
    corpi = _corpi_presi(connessione, ritocco, volti)
    persone: set[int] = set()
    for volto in tutti(connessione,
                       "SELECT id, persona_id, deciso_da FROM volti "
                       "WHERE id IN (SELECT value FROM json_each(?))", json.dumps(sorted(volti))):
        _segna(connessione, ritocco, "volto", volto["id"], volto["persona_id"],
               {"deciso_da": volto["deciso_da"]})
        if volto["persona_id"] is not None:
            persone.add(volto["persona_id"])
            connessione.execute("UPDATE volti SET persona_id = NULL WHERE id = ?", (volto["id"],))
    gia = set()
    for detto in tutti(connessione,
                       "SELECT corpo_id, persona_id, risposta, deciso_il FROM corpi_delle_persone "
                       "WHERE corpo_id IN (SELECT value FROM json_each(?))",
                       json.dumps(sorted(corpi))):
        _segna(connessione, ritocco, "corpo", detto["corpo_id"], detto["persona_id"],
               {"risposta": detto["risposta"], "deciso_il": detto["deciso_il"]})
        gia.add(detto["corpo_id"])
        if detto["risposta"] == "si":
            persone.add(detto["persona_id"])
    for corpo_id in sorted(corpi - gia):
        _segna(connessione, ritocco, "corpo", corpo_id, None, {})
    connessione.execute(
        "DELETE FROM corpi_delle_persone WHERE corpo_id IN (SELECT value FROM json_each(?))",
        (json.dumps(sorted(corpi)),))
    connessione.execute(
        "DELETE FROM proposte_dei_corpi WHERE corpo_id IN (SELECT value FROM json_each(?))",
        (json.dumps(sorted(corpi)),))
    for persona_id in sorted(persone):
        if _resta_nello_scatto(connessione, ritocco["scatto_id"], persona_id):
            continue
        messa = uno(connessione, "SELECT messa_il FROM persone_negli_scatti "
                    "WHERE scatto_id = ? AND persona_id = ?", ritocco["scatto_id"], persona_id)
        if messa is None:
            continue
        _segna(connessione, ritocco, "scatto", ritocco["scatto_id"], persona_id,
               {"messa_il": messa["messa_il"]})
        connessione.execute("DELETE FROM persone_negli_scatti WHERE scatto_id = ? "
                            "AND persona_id = ?", (ritocco["scatto_id"], persona_id))


def _resta_nello_scatto(connessione: sqlite3.Connection, scatto_id: int,
                        persona_id: int) -> bool:
    return uno(
        connessione,
        "SELECT 1 FROM volti WHERE scatto_id = ? AND persona_id = ? UNION ALL "
        "SELECT 1 FROM corpi_delle_persone d JOIN corpi c ON c.id = d.corpo_id "
        "WHERE c.scatto_id = ? AND d.persona_id = ? AND d.risposta = 'si' LIMIT 1",
        scatto_id, persona_id, scatto_id, persona_id) is not None


def _rimetti(connessione: sqlite3.Connection, riga) -> None:
    com_era = json.loads(riga["com_era"] or "{}")
    if riga["persona_id"] is None:
        pass
    elif riga["dove"] == "volto":
        connessione.execute(
            "UPDATE volti SET persona_id = ?, deciso_da = ? WHERE id = ? AND persona_id IS NULL "
            "AND EXISTS (SELECT 1 FROM persone WHERE id = ?)",
            (riga["persona_id"], com_era.get("deciso_da") or "sistema", riga["riga_id"],
             riga["persona_id"]))
    elif riga["dove"] == "corpo":
        connessione.execute(
            "INSERT OR IGNORE INTO corpi_delle_persone (corpo_id, persona_id, risposta, deciso_il) "
            "SELECT ?, ?, ?, ? WHERE EXISTS (SELECT 1 FROM corpi WHERE id = ?)",
            (riga["riga_id"], riga["persona_id"], com_era.get("risposta") or "si",
             com_era.get("deciso_il") or adesso(), riga["riga_id"]))
    else:
        connessione.execute(
            "INSERT OR IGNORE INTO persone_negli_scatti (scatto_id, persona_id, messa_il) "
            "VALUES (?, ?, ?)",
            (riga["riga_id"], riga["persona_id"], com_era.get("messa_il") or adesso()))
    connessione.execute("DELETE FROM persone_tolte WHERE id = ?", (riga["id"],))


def allinea(connessione: sqlite3.Connection, scatto_id: int) -> None:
    attivi = _attivi(connessione, scatto_id)
    vivi = {ritocco["id"] for ritocco in attivi}
    segnati = tutti(connessione, "SELECT * FROM persone_tolte WHERE scatto_id = ? ORDER BY id DESC",
                    scatto_id)
    for riga in segnati:
        if riga["ritocco_id"] not in vivi:
            _rimetti(connessione, riga)
    fatti = {riga["ritocco_id"] for riga in segnati if riga["ritocco_id"] in vivi}
    for ritocco in attivi:
        if ritocco["id"] not in fatti:
            _togli(connessione, ritocco)


def allinea_il_file(archivio, file_id: int) -> None:
    with archivio.scrittura() as connessione:
        riga = uno(connessione, "SELECT scatto_id FROM file_media WHERE id = ?", file_id)
        if riga is not None and riga["scatto_id"]:
            allinea(connessione, riga["scatto_id"])


def allinea_il_lavoro(archivio, lavoro_id: int) -> None:
    with archivio.scrittura() as connessione:
        riga = uno(connessione, "SELECT scatto_id FROM ritocchi_lavori WHERE id = ?", lavoro_id)
        if riga is not None and riga["scatto_id"]:
            allinea(connessione, riga["scatto_id"])


def e_tolto(connessione: sqlite3.Connection, dove: str, riga_id: int) -> bool:
    return uno(connessione, "SELECT 1 FROM persone_tolte WHERE dove = ? AND riga_id = ? LIMIT 1",
               dove, riga_id) is not None


def ripara(archivio) -> int:
    with archivio.lettura() as connessione:
        scatti = [riga["scatto_id"] for riga in tutti(
            connessione,
            "SELECT DISTINCT scatto_id FROM ritocchi WHERE genere = ? AND cosa IN (?, ?) "
            "UNION SELECT DISTINCT scatto_id FROM persone_tolte",
            elenco.TOGLI, *PERSONE)]
    for scatto_id in scatti:
        with archivio.scrittura() as connessione:
            allinea(connessione, scatto_id)
    return len(scatti)
