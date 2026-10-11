from __future__ import annotations

import sqlite3

from officina.archivio.accesso import Archivio
from officina.archivio.database import (adesso, leggi_impostazione, tutti,
                                        uno)
from officina.doppioni import motore
from officina.modello import scatti

QUANTI_ALLA_VOLTA = 60

QUANDO_CONTATO = "doppioni_contati_il"


def firma(file_id: list[int]) -> str:
    return "-".join(str(quale) for quale in sorted(file_id))


def conta_e_scrivi(archivio: Archivio,
                   al_passo=None) -> int:
    fatti = motore.gruppi(archivio)
    quando = adesso()
    with archivio.scrittura() as connessione:
        connessione.execute("DELETE FROM doppioni_gruppi")
        for scritti, gruppo in enumerate(fatti, start=1):
            segno = firma(gruppo.file_id)
            for posto, quale in enumerate(gruppo.file_id):
                connessione.execute(
                    "INSERT INTO doppioni_gruppi "
                    "(firma, file_id, posto, distanza, contato_il) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (segno, quale, posto, gruppo.distanza_massima, quando))
            if al_passo is not None:
                al_passo(scritti, len(fatti))
        archivio.imposta(QUANDO_CONTATO, quando)
    return len(fatti)


def mai_contato(connessione: sqlite3.Connection) -> bool:
    return not quando_contato(connessione)


def quando_contato(connessione: sqlite3.Connection) -> str | None:
    return leggi_impostazione(connessione, QUANDO_CONTATO, None)


def arrivate_dopo_il_conto(connessione: sqlite3.Connection) -> int:
    quando = quando_contato(connessione)
    if not quando:
        return 0
    riga = uno(connessione,
               "SELECT count(*) AS q FROM file_media "
               "WHERE genere = 'immagine' AND aggiunto_il > ?", quando)
    return int(riga["q"]) if riga else 0


def il_conto(connessione: sqlite3.Connection) -> dict:
    gruppi_veri = ("SELECT firma FROM doppioni_gruppi "
                   "GROUP BY firma HAVING count(*) > 1")
    riga = uno(connessione,
               "SELECT count(*) AS totale, count(d.firma) AS decisi "
               f"FROM ({gruppi_veri}) g "
               "LEFT JOIN doppioni_decisi d ON d.firma = g.firma")
    totale, decisi = riga["totale"], riga["decisi"]
    return {"totale": totale, "decisi": decisi,
            "restano": max(totale - decisi, 0)}


_COPIE = """
    SELECT g.firma, g.file_id, g.posto, g.distanza,
           f.dimensione, f.scatto_id, f.miniatura,
           s.fuori_archivio, s.larghezza, s.altezza
    FROM doppioni_gruppi g
    JOIN file_media f ON f.id = g.file_id
    LEFT JOIN scatti s ON s.id = f.scatto_id
    WHERE g.firma IN ({dentro})
    ORDER BY g.firma, g.posto
"""


def da_decidere(connessione: sqlite3.Connection, da: int = 0,
                quanti: int = QUANTI_ALLA_VOLTA) -> list[dict]:
    righe = tutti(
        connessione,
        """
        SELECT g.firma, count(*) AS quante, min(g.distanza) AS distanza
        FROM doppioni_gruppi g
        WHERE NOT EXISTS (SELECT 1 FROM doppioni_decisi d WHERE d.firma = g.firma)
        GROUP BY g.firma
        HAVING quante > 1
        ORDER BY quante DESC, distanza ASC, g.firma
        LIMIT ? OFFSET ?
        """,
        quanti, da,
    )
    return _riempi(connessione, [r["firma"] for r in righe])


def gia_decisi(connessione: sqlite3.Connection,
               quanti: int = QUANTI_ALLA_VOLTA) -> list[dict]:
    righe = tutti(connessione,
                  "SELECT firma, scelta, tenuto_id FROM doppioni_decisi "
                  "ORDER BY deciso_il DESC, firma LIMIT ?", quanti)
    come = {riga["firma"]: riga for riga in righe}
    gruppi = _riempi(connessione, [riga["firma"] for riga in righe])
    for gruppo in gruppi:
        gruppo["scelta"] = come[gruppo["firma"]]["scelta"]
        gruppo["tenuto_id"] = come[gruppo["firma"]]["tenuto_id"]
    return gruppi


def un_gruppo(connessione: sqlite3.Connection, segno: str) -> dict | None:
    trovati = _riempi(connessione, [segno])
    return trovati[0] if trovati else None


def _riempi(connessione: sqlite3.Connection, segni: list[str]) -> list[dict]:
    if not segni:
        return []
    dentro = ",".join("?" * len(segni))
    gruppi: dict[str, dict] = {}
    for riga in tutti(connessione, _COPIE.format(dentro=dentro), *segni):
        gruppo = gruppi.setdefault(riga["firma"], {
            "firma": riga["firma"],
            "distanza": riga["distanza"],
            "identiche": riga["distanza"] == 0,
            "copie": [],
        })
        gruppo["copie"].append({
            "file_id": riga["file_id"],
            "scatto_id": riga["scatto_id"],
            "dimensione": riga["dimensione"] or 0,
            "miniatura": riga["miniatura"],
            "larghezza": riga["larghezza"] or 4,
            "altezza": riga["altezza"] or 3,
            "fuori_archivio": bool(riga["fuori_archivio"]),
        })
    ordinati = [gruppi[s] for s in segni if s in gruppi]
    return [g for g in ordinati if len(g["copie"]) > 1]


def doppie(connessione: sqlite3.Connection,
           file_id: list[int]) -> dict[int, str]:
    if not file_id:
        return {}
    dentro = ",".join("?" * len(file_id))
    righe = tutti(
        connessione,
        f"""
        SELECT g.file_id, g.firma FROM doppioni_gruppi g
        WHERE g.file_id IN ({dentro})
          AND NOT EXISTS (SELECT 1 FROM doppioni_decisi d WHERE d.firma = g.firma)
        """,
        *file_id,
    )
    return {riga["file_id"]: riga["firma"] for riga in righe}


def tieni(archivio: Archivio, segno: str, tenuto_id: int) -> dict:
    with archivio.scrittura() as connessione:
        copie = _copie_di(connessione, segno)
        if not copie:
            return {"spostati": 0}
        if tenuto_id not in [c["file_id"] for c in copie]:
            tenuto_id = copie[0]["file_id"]

        _disfa(connessione, segno)

        spostati: list[int] = []
        for copia in copie:
            if copia["file_id"] == tenuto_id or copia["scatto_id"] is None:
                continue
            if copia["fuori_archivio"]:
                continue
            scatti.fuori_archivio(connessione, copia["scatto_id"], True)
            spostati.append(copia["scatto_id"])

        _scrivi_la_scelta(connessione, segno, "tenuto", tenuto_id, spostati)
    return {"spostati": len(spostati), "tenuto_id": tenuto_id}


def sono_diverse(archivio: Archivio, segno: str) -> dict:
    with archivio.scrittura() as connessione:
        rimessi = _disfa(connessione, segno)
        _scrivi_la_scelta(connessione, segno, "diverse", None, [])
    return {"spostati": 0, "rimessi": rimessi}


def rimetti(archivio: Archivio, segno: str) -> dict:
    with archivio.scrittura() as connessione:
        rimessi = _disfa(connessione, segno)
    return {"rimessi": rimessi}


def _disfa(connessione: sqlite3.Connection, segno: str) -> int:
    riga = uno(connessione,
               "SELECT * FROM doppioni_decisi WHERE firma = ?", segno)
    if riga is None:
        return 0
    quali = [int(x) for x in str(riga["messi_fuori"] or "").split(",") if x]
    for scatto_id in quali:
        scatti.fuori_archivio(connessione, scatto_id, False)
    connessione.execute("DELETE FROM doppioni_decisi WHERE firma = ?", (segno,))
    return len(quali)


def rimetti_tutto(archivio: Archivio) -> int:
    with archivio.lettura() as connessione:
        segni = [r["firma"] for r in tutti(
            connessione, "SELECT firma FROM doppioni_decisi")]
    for segno in segni:
        rimetti(archivio, segno)
    return len(segni)


def _copie_di(connessione: sqlite3.Connection, segno: str) -> list[dict]:
    return [
        {"file_id": r["file_id"], "scatto_id": r["scatto_id"],
         "fuori_archivio": bool(r["fuori_archivio"])}
        for r in tutti(
            connessione,
            "SELECT g.file_id, f.scatto_id, s.fuori_archivio "
            "FROM doppioni_gruppi g "
            "JOIN file_media f ON f.id = g.file_id "
            "LEFT JOIN scatti s ON s.id = f.scatto_id "
            "WHERE g.firma = ? ORDER BY g.posto", segno)
    ]


def _scrivi_la_scelta(connessione: sqlite3.Connection, segno: str, scelta: str,
                      tenuto_id: int | None, spostati: list[int]) -> None:
    connessione.execute(
        "INSERT OR REPLACE INTO doppioni_decisi "
        "(firma, scelta, tenuto_id, messi_fuori, deciso_il) VALUES (?, ?, ?, ?, ?)",
        (segno, scelta, tenuto_id, ",".join(str(x) for x in spostati), adesso()))
