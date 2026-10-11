from __future__ import annotations

import platform
import sqlite3
import uuid

from officina.archivio.database import adesso, inserisci, tutti, uno
from officina.errori import OperazioneNonPermessa

COSE = ("etichetta", "nodo", "persona", "cuore")
AZIONI = ("messa", "tolta", "cambiata", "creato", "rinominato", "spostato", "stato")


def _nome_del_computer() -> str:
    nome = (platform.node() or "").strip()
    return nome if nome else "questo PC"


def questa_macchina(connessione: sqlite3.Connection) -> sqlite3.Row:
    riga = uno(connessione, "SELECT * FROM macchine WHERE questa = 1")
    if riga is not None:
        return riga
    inserisci(
        connessione,
        "INSERT OR IGNORE INTO macchine (codice, nome, questa, conosciuta_il) "
        "VALUES (?, ?, 1, ?)",
        uuid.uuid4().hex, _nome_del_computer(), adesso(),
    )
    return uno(connessione, "SELECT * FROM macchine WHERE questa = 1")


def rinomina_macchina(connessione: sqlite3.Connection, macchina_id: int,
                      nome: str) -> None:
    nome = nome.strip()
    if not nome:
        raise OperazioneNonPermessa("Una macchina deve avere un nome.")
    connessione.execute("UPDATE macchine SET nome = ? WHERE id = ?", (nome, macchina_id))


def annota(connessione: sqlite3.Connection, cosa: str, azione: str, *,
           scatto_id: int | None = None, nodo_id: int | None = None,
           stato: str | None = None, origine: str | None = None,
           valore: str | None = None, valore_prima: str | None = None) -> int:
    if cosa not in COSE:
        raise OperazioneNonPermessa(f"Non so annotare un cambiamento di «{cosa}».")
    if azione not in AZIONI:
        raise OperazioneNonPermessa(f"Azione sconosciuta: {azione}")

    macchina = questa_macchina(connessione)
    riga = uno(
        connessione,
        "SELECT max(seriale) AS ultimo FROM cambiamenti WHERE macchina_id = ?",
        macchina["id"],
    )
    seriale = (riga["ultimo"] or 0) + 1
    inserisci(
        connessione,
        """
        INSERT INTO cambiamenti (macchina_id, seriale, avvenuto_il, cosa, azione,
                                 scatto_id, nodo_id, stato, origine, valore,
                                 valore_prima)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        macchina["id"], seriale, adesso(), cosa, azione,
        scatto_id, nodo_id, stato, origine, valore, valore_prima,
    )
    return seriale


def recupera_larretrato(connessione: sqlite3.Connection) -> int:
    macchina = questa_macchina(connessione)
    riga = uno(connessione,
               "SELECT count(*) AS quanti FROM cambiamenti WHERE macchina_id = ?",
               macchina["id"])
    if riga and riga["quanti"]:
        return 0
    if altre_macchine(connessione):
        return 0

    scritti = 0
    seriale = 0

    def scrivi(cosa: str, azione: str, quando: str, **dati) -> None:
        nonlocal scritti, seriale
        seriale += 1
        scritti += 1
        inserisci(
            connessione,
            """
            INSERT INTO cambiamenti (macchina_id, seriale, avvenuto_il, cosa,
                                     azione, scatto_id, nodo_id, stato, origine,
                                     valore, valore_prima)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
            """,
            macchina["id"], seriale, quando, cosa, azione,
            dati.get("scatto_id"), dati.get("nodo_id"), dati.get("stato"),
            dati.get("origine"), dati.get("valore"),
        )

    for nodo in tutti(connessione, "SELECT * FROM nodi ORDER BY id"):
        scrivi("nodo", "creato", nodo["creato_il"], nodo_id=nodo["id"],
               valore=nodo["nome"])
        if nodo["stato"] != "attivo":
            scrivi("nodo", "stato", nodo["cestinato_il"] or nodo["creato_il"],
                   nodo_id=nodo["id"], valore=nodo["stato"])

    for etichetta in tutti(connessione, "SELECT * FROM etichette ORDER BY id"):
        scrivi("etichetta", "messa", etichetta["creata_il"],
               scatto_id=etichetta["scatto_id"], nodo_id=etichetta["nodo_id"],
               stato=etichetta["stato"], origine=etichetta["origine"])

    return scritti


def da_mandare(connessione: sqlite3.Connection,
               dopo_il_seriale: int = 0) -> list[sqlite3.Row]:
    macchina = questa_macchina(connessione)
    return tutti(
        connessione,
        "SELECT * FROM cambiamenti WHERE macchina_id = ? AND seriale > ? "
        "ORDER BY seriale",
        macchina["id"], dopo_il_seriale,
    )


def quanti_da_mandare(connessione: sqlite3.Connection,
                      dopo_il_seriale: int = 0) -> int:
    macchina = questa_macchina(connessione)
    riga = uno(
        connessione,
        "SELECT count(*) AS quanti FROM cambiamenti "
        "WHERE macchina_id = ? AND seriale > ?",
        macchina["id"], dopo_il_seriale,
    )
    return riga["quanti"] if riga else 0


def altre_macchine(connessione: sqlite3.Connection) -> list[sqlite3.Row]:
    return tutti(
        connessione,
        "SELECT * FROM macchine WHERE questa = 0 ORDER BY nome COLLATE NOCASE",
    )


def impara_dal_pacchetto(connessione: sqlite3.Connection, codice: str, nome: str,
                         visto_di_me: int, inventario) -> int:
    riga = uno(connessione, "SELECT * FROM macchine WHERE codice = ?", codice)
    if riga is None:
        macchina_id = inserisci(
            connessione,
            "INSERT INTO macchine (codice, nome, questa, conosciuta_il, vista_il) "
            "VALUES (?, ?, 0, ?, ?)",
            codice, nome, adesso(), adesso(),
        )
    else:
        macchina_id = riga["id"]
        connessione.execute(
            "UPDATE macchine SET nome = ?, vista_il = ? WHERE id = ?",
            (nome, adesso(), macchina_id))

    connessione.execute(
        "UPDATE macchine SET mi_ha_vista_fino_a = max(mi_ha_vista_fino_a, ?) "
        "WHERE id = ?", (int(visto_di_me), macchina_id))

    quando = adesso()
    for impronta in inventario:
        connessione.execute(
            "INSERT INTO inventario_altrui (macchina_id, impronta, saputo_il) "
            "VALUES (?, ?, ?) ON CONFLICT DO NOTHING",
            (macchina_id, impronta, quando))
    return macchina_id
