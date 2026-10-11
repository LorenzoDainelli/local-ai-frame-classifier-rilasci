from __future__ import annotations

import sqlite3

from officina.archivio import memoria
from officina.archivio.database import adesso, tutti, uno
from officina.errori import OperazioneNonPermessa
from officina.modello import cambiamenti
from officina.modello import nodi


def stato_di(connessione: sqlite3.Connection, scatto_id: int, nodo_id: int) -> str:
    riga = uno(
        connessione,
        "SELECT stato FROM etichette WHERE scatto_id = ? AND nodo_id = ?",
        scatto_id, nodo_id,
    )
    return riga["stato"] if riga else "non_deciso"


def metti(connessione: sqlite3.Connection, scatto_id: int, nodo_id: int,
          stato: str = "si", origine: str = "utente",
          sicurezza: float | None = None) -> None:
    if stato not in ("si", "no"):
        raise OperazioneNonPermessa(
            "Un'etichetta può essere solo «si» o «no». «Non ancora deciso» si "
            "ottiene togliendola (regola 55)."
        )
    if origine not in ("utente", "sistema"):
        raise OperazioneNonPermessa(f"Origine sconosciuta: {origine}")

    precedente = stato_di(connessione, scatto_id, nodo_id)

    if origine == "sistema":
        gia = uno(
            connessione,
            "SELECT origine FROM etichette WHERE scatto_id = ? AND nodo_id = ?",
            scatto_id, nodo_id,
        )
        if gia and gia["origine"] == "utente":
            return

    connessione.execute(
        """
        INSERT INTO etichette (scatto_id, nodo_id, stato, origine, sicurezza, creata_il)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(scatto_id, nodo_id) DO UPDATE SET
            stato = excluded.stato, origine = excluded.origine,
            sicurezza = excluded.sicurezza, creata_il = excluded.creata_il
        """,
        (scatto_id, nodo_id, stato, origine, sicurezza, adesso()),
    )
    connessione.execute(
        "INSERT INTO storico_etichette (scatto_id, nodo_id, azione, stato, origine, avvenuto_il) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (scatto_id, nodo_id,
         "messa" if precedente == "non_deciso" else "cambiata",
         stato, origine, adesso()),
    )
    if origine == "utente":
        nodi.segna_uso(connessione, nodo_id)
        cambiamenti.annota(
            connessione, "etichetta",
            "messa" if precedente == "non_deciso" else "cambiata",
            scatto_id=scatto_id, nodo_id=nodo_id, stato=stato, origine=origine,
        )


def togli(connessione: sqlite3.Connection, scatto_id: int, nodo_id: int) -> None:
    connessione.execute(
        "DELETE FROM etichette WHERE scatto_id = ? AND nodo_id = ?", (scatto_id, nodo_id)
    )
    connessione.execute(
        "INSERT INTO storico_etichette (scatto_id, nodo_id, azione, avvenuto_il) "
        "VALUES (?, ?, 'tolta', ?)",
        (scatto_id, nodo_id, adesso()),
    )
    cambiamenti.annota(connessione, "etichetta", "tolta",
                       scatto_id=scatto_id, nodo_id=nodo_id, origine="utente")


def di_scatto(connessione: sqlite3.Connection, scatto_id: int,
              solo_si: bool = True) -> list[sqlite3.Row]:
    condizione = "AND e.stato = 'si'" if solo_si else ""
    return tutti(
        connessione,
        f"""
        SELECT e.*, n.nome, n.genitore_id
        FROM etichette e JOIN nodi n ON n.id = e.nodo_id
        WHERE e.scatto_id = ? {condizione} AND n.stato = 'attivo'
        ORDER BY n.nome COLLATE NOCASE
        """,
        scatto_id,
    )


def con_antenati(connessione: sqlite3.Connection, scatto_id: int) -> set[int]:
    diretti = {r["nodo_id"] for r in di_scatto(connessione, scatto_id)}
    tutti_i_nodi = set(diretti)
    for nodo_id in diretti:
        tutti_i_nodi.update(nodi.antenati(connessione, nodo_id))
    return tutti_i_nodi


def conta_per_nodo(connessione: sqlite3.Connection) -> dict[int, dict[str, int]]:
    conti: dict[int, dict[str, int]] = {}
    for riga in tutti(connessione,
                      "SELECT nodo_id, stato, count(*) AS quanti FROM etichette "
                      "GROUP BY nodo_id, stato"):
        conti.setdefault(riga["nodo_id"], {"si": 0, "no": 0})[riga["stato"]] = riga["quanti"]
    return conti


_tenuto = memoria.Ricordo("quanti senza etichetta")


def quanti_senza_etichetta(connessione: sqlite3.Connection) -> int:
    return _tenuto.prendi(connessione, lambda: _conta_senza_etichetta(connessione))


def _conta_senza_etichetta(connessione: sqlite3.Connection) -> int:
    riga = uno(
        connessione,
        """
        SELECT count(*) AS quanti FROM scatti s
        WHERE s.fuori_archivio = 0
          AND NOT EXISTS (
              SELECT 1 FROM etichette e JOIN nodi n ON n.id = e.nodo_id
              WHERE e.scatto_id = s.id AND e.stato = 'si' AND n.stato = 'attivo'
          )
        """,
    )
    return riga["quanti"] if riga else 0


def annulla_ultima(connessione: sqlite3.Connection) -> bool:
    ultima = uno(
        connessione,
        "SELECT * FROM storico_etichette ORDER BY id DESC LIMIT 1",
    )
    if ultima is None:
        return False

    if ultima["azione"] == "messa":
        connessione.execute(
            "DELETE FROM etichette WHERE scatto_id = ? AND nodo_id = ?",
            (ultima["scatto_id"], ultima["nodo_id"]),
        )
    else:
        prima = uno(
            connessione,
            "SELECT * FROM storico_etichette WHERE scatto_id = ? AND nodo_id = ? "
            "AND id < ? AND stato IS NOT NULL ORDER BY id DESC LIMIT 1",
            ultima["scatto_id"], ultima["nodo_id"], ultima["id"],
        )
        if prima is None:
            connessione.execute(
                "DELETE FROM etichette WHERE scatto_id = ? AND nodo_id = ?",
                (ultima["scatto_id"], ultima["nodo_id"]),
            )
        else:
            connessione.execute(
                """
                INSERT INTO etichette (scatto_id, nodo_id, stato, origine, creata_il)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(scatto_id, nodo_id) DO UPDATE SET
                    stato = excluded.stato, origine = excluded.origine
                """,
                (prima["scatto_id"], prima["nodo_id"], prima["stato"],
                 prima["origine"] or "utente", adesso()),
            )

    connessione.execute("DELETE FROM storico_etichette WHERE id = ?", (ultima["id"],))

    dopo = stato_di(connessione, ultima["scatto_id"], ultima["nodo_id"])
    if dopo == "non_deciso":
        cambiamenti.annota(connessione, "etichetta", "tolta",
                           scatto_id=ultima["scatto_id"], nodo_id=ultima["nodo_id"],
                           origine="utente")
    else:
        cambiamenti.annota(connessione, "etichetta", "cambiata",
                           scatto_id=ultima["scatto_id"], nodo_id=ultima["nodo_id"],
                           stato=dopo, origine="utente")
    return True
