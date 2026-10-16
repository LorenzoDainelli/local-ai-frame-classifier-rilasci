from __future__ import annotations

import os
import shutil
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from officina.archivio.database import adesso, tutti, uno, valore
from officina.errori import ErroreOfficina, FileNonLeggibile
from officina.importazione import impronta

SANO = "sano"
ROVINATO = "rovinato"
CAMBIATO = "cambiato"
ILLEGGIBILE = "illeggibile"
ASSENTE = "assente"

DA_RIPARARE = (ROVINATO, CAMBIATO)
ACCETTATO = "accettato"
SOLO_NEL_CLOUD_A_PAROLE = "solo nel cloud"

GIORNI_FRA_UN_CONTROLLO = 30
GIORNI_PER_RIPROVARE = 2
QUANTI_PER_GIRO = 200
MB = 1024 * 1024
BYTE_PER_GIRO = 768 * MB
MARGINE = 50 * MB

SOLO_NEL_CLOUD = 0x400000 | 0x40000 | 0x1000


class RiparazioneFerma(ErroreOfficina):
    codice = "riparazione_ferma"


@dataclass
class Giro:
    guardati: int = 0
    sani: int = 0
    rovinati: int = 0
    cambiati: int = 0
    byte: int = 0


def _prima_di(giorni: int) -> str:
    quando = datetime.now(timezone.utc) - timedelta(days=giorni)
    return quando.strftime("%Y-%m-%dT%H:%M:%SZ")


_COLONNE = """
    p.id AS percorso_id, p.file_id AS file_id, p.percorso AS percorso,
    f.impronta AS impronta, f.dimensione AS attesa,
    s.toccato_ns AS base_ns, s.dimensione AS base_dimensione,
    s.esito AS prima, s.dettaglio AS prima_detto
"""

_STESSO = "s.percorso_id = p.id AND s.file_id = p.file_id AND s.percorso = p.percorso"


def da_guardare(connessione: sqlite3.Connection, quanti: int = QUANTI_PER_GIRO) -> list[sqlite3.Row]:
    scaduti = tutti(
        connessione,
        f"""
        SELECT {_COLONNE}
          FROM salute_file AS s
          JOIN percorsi AS p ON {_STESSO}
          JOIN file_media AS f ON f.id = p.file_id
         WHERE s.controllato_il < ? AND p.presente = 1
         ORDER BY s.controllato_il
         LIMIT ?
        """,
        _prima_di(GIORNI_FRA_UN_CONTROLLO), quanti,
    )
    da_riprovare = tutti(
        connessione,
        f"""
        SELECT {_COLONNE}
          FROM salute_file AS s
          JOIN percorsi AS p ON {_STESSO}
          JOIN file_media AS f ON f.id = p.file_id
         WHERE s.esito IN ('illeggibile', 'assente') AND s.controllato_il < ?
               AND s.controllato_il >= ? AND p.presente = 1
         ORDER BY s.controllato_il
         LIMIT ?
        """,
        _prima_di(GIORNI_PER_RIPROVARE), _prima_di(GIORNI_FRA_UN_CONTROLLO), quanti,
    )
    mai_visti = tutti(
        connessione,
        f"""
        SELECT {_COLONNE}
          FROM percorsi AS p
          JOIN file_media AS f ON f.id = p.file_id
          LEFT JOIN salute_file AS s ON {_STESSO}
         WHERE p.presente = 1 AND s.percorso_id IS NULL
         ORDER BY p.id
         LIMIT ?
        """,
        quanti,
    )
    return (scaduti + da_riprovare + mai_visti)[:quanti]


def _giudica(riga: sqlite3.Row, toccato_ns: int, dimensione: int) -> tuple[str, str | None]:
    if riga["prima_detto"] == ACCETTATO and riga["prima"] == CAMBIATO:
        return CAMBIATO, ACCETTATO
    if riga["base_ns"] is not None:
        return (ROVINATO, None) if toccato_ns == riga["base_ns"] else (CAMBIATO, None)
    return (ROVINATO, None) if dimensione == riga["attesa"] else (CAMBIATO, None)


def _guarda(riga: sqlite3.Row, freno) -> dict | None:
    percorso = Path(riga["percorso"])
    fuori = {
        "percorso_id": riga["percorso_id"], "file_id": riga["file_id"],
        "percorso": riga["percorso"], "dimensione": riga["base_dimensione"],
        "toccato_ns": riga["base_ns"], "dettaglio": None, "letti": 0,
    }
    try:
        prima = os.stat(percorso)
    except FileNotFoundError:
        return {**fuori, "esito": ASSENTE}
    except OSError as guasto:
        return {**fuori, "esito": ILLEGGIBILE, "dettaglio": guasto.strerror or str(guasto)}
    if getattr(prima, "st_file_attributes", 0) & SOLO_NEL_CLOUD:
        return {**fuori, "esito": ASSENTE, "dettaglio": SOLO_NEL_CLOUD_A_PAROLE}
    try:
        segno = impronta.del_file_fermabile(percorso, freno)
    except FileNonLeggibile as guasto:
        return {**fuori, "esito": ILLEGGIBILE, "dettaglio": guasto.messaggio}
    if segno is None:
        return None
    try:
        dopo = os.stat(percorso)
    except OSError:
        return None
    if (dopo.st_mtime_ns, dopo.st_size) != (prima.st_mtime_ns, prima.st_size):
        return None
    fuori["letti"] = dopo.st_size
    if segno == riga["impronta"]:
        return {**fuori, "esito": SANO, "dimensione": dopo.st_size,
                "toccato_ns": dopo.st_mtime_ns}
    esito, detto = _giudica(riga, dopo.st_mtime_ns, dopo.st_size)
    return {**fuori, "esito": esito, "dettaglio": detto}


def _scrivi(connessione: sqlite3.Connection, esito: dict, riparato: bool = False) -> None:
    connessione.execute(
        """
        INSERT INTO salute_file (percorso_id, file_id, percorso, esito, dimensione,
                                 toccato_ns, controllato_il, dettaglio, riparato_il)
        SELECT ?, ?, ?, ?, ?, ?, ?, ?, ?
         WHERE EXISTS (SELECT 1 FROM percorsi
                        WHERE id = ? AND file_id = ? AND percorso = ?)
        ON CONFLICT(percorso_id) DO UPDATE SET
            file_id = excluded.file_id, percorso = excluded.percorso,
            esito = excluded.esito, dimensione = excluded.dimensione,
            toccato_ns = excluded.toccato_ns, controllato_il = excluded.controllato_il,
            dettaglio = excluded.dettaglio,
            riparato_il = CASE
                WHEN excluded.riparato_il IS NOT NULL THEN excluded.riparato_il
                WHEN salute_file.file_id = excluded.file_id
                     AND salute_file.percorso = excluded.percorso
                THEN salute_file.riparato_il END
        """,
        (esito["percorso_id"], esito["file_id"], esito["percorso"], esito["esito"],
         esito["dimensione"], esito["toccato_ns"], adesso(), esito["dettaglio"],
         adesso() if riparato else None,
         esito["percorso_id"], esito["file_id"], esito["percorso"]),
    )


def _mai_fermo() -> bool:
    return False


def _guarda_entro(righe, secondi: float, byte_massimi: int, freno) -> tuple[Giro, list[dict]]:
    giro = Giro()
    inizio = time.monotonic()
    esiti = []
    for riga in righe:
        if freno() or time.monotonic() - inizio > secondi or giro.byte >= byte_massimi:
            break
        esito = _guarda(riga, freno)
        if esito is None:
            continue
        esiti.append(esito)
        giro.guardati += 1
        giro.byte += esito["letti"]
        giro.sani += esito["esito"] == SANO
        giro.rovinati += esito["esito"] == ROVINATO
        giro.cambiati += esito["esito"] == CAMBIATO
    return giro, esiti


def _scrivi_tutti(archivio, esiti: list[dict]) -> None:
    if esiti:
        with archivio.scrittura_di_servizio() as connessione:
            for esito in esiti:
                _scrivi(connessione, esito)


def un_giro(archivio, secondi: float = 10.0, freno=None,
            byte_massimi: int = BYTE_PER_GIRO) -> Giro:
    if archivio.di_prova:
        return Giro()
    with archivio.lettura() as connessione:
        righe = da_guardare(connessione)
    giro, esiti = _guarda_entro(righe, secondi, byte_massimi, freno or _mai_fermo)
    _scrivi_tutti(archivio, esiti)
    return giro


def ricontrolla_quelli_da_riparare(archivio, secondi: float = 5.0,
                                   byte_massimi: int = BYTE_PER_GIRO) -> Giro:
    if archivio.di_prova:
        return Giro()
    with archivio.lettura() as connessione:
        righe = tutti(
            connessione,
            f"""
            SELECT {_COLONNE}
              FROM salute_file AS s
              JOIN percorsi AS p ON {_STESSO}
              JOIN file_media AS f ON f.id = p.file_id
             WHERE s.esito IN ('rovinato', 'cambiato')
                   AND (s.dettaglio IS NULL OR s.dettaglio != ?)
             ORDER BY s.controllato_il, s.percorso_id
            """,
            ACCETTATO,
        )
    giro, esiti = _guarda_entro(righe, secondi, byte_massimi, _mai_fermo)
    _scrivi_tutti(archivio, esiti)
    return giro


def quanti_rovinati(connessione: sqlite3.Connection) -> int:
    return int(valore(
        connessione,
        """
        SELECT count(*) FROM salute_file AS s
          JOIN percorsi AS p
            ON s.percorso_id = p.id AND s.file_id = p.file_id AND s.percorso = p.percorso
         WHERE s.esito = 'rovinato'
        """,
        predefinito=0,
    ) or 0)


def da_riparare(connessione: sqlite3.Connection) -> list[dict]:
    righe = tutti(
        connessione,
        """
        SELECT s.percorso_id AS percorso_id, s.esito AS esito, s.controllato_il AS quando,
               p.nome AS nome, p.percorso AS percorso,
               EXISTS (SELECT 1 FROM percorsi AS altro
                        WHERE altro.file_id = p.file_id AND altro.id != p.id
                              AND altro.presente = 1) AS ha_un_doppione
          FROM salute_file AS s
          JOIN percorsi AS p
            ON s.percorso_id = p.id AND s.file_id = p.file_id AND s.percorso = p.percorso
         WHERE s.esito IN ('rovinato', 'cambiato')
               AND (s.dettaglio IS NULL OR s.dettaglio != ?)
         ORDER BY s.esito DESC, p.nome
        """,
        ACCETTATO,
    )
    return [dict(riga) for riga in righe]


def conti(connessione: sqlite3.Connection) -> dict:
    righe = tutti(
        connessione,
        """
        SELECT s.esito AS esito, count(*) AS quanti
          FROM salute_file AS s
          JOIN percorsi AS p
            ON s.percorso_id = p.id AND s.file_id = p.file_id AND s.percorso = p.percorso
         GROUP BY s.esito
        """,
    )
    fuori = {esito: 0 for esito in (SANO, ROVINATO, CAMBIATO, ILLEGGIBILE, ASSENTE)}
    for riga in righe:
        fuori[riga["esito"]] = riga["quanti"]
    fuori["presenti"] = int(valore(
        connessione,
        "SELECT (SELECT count(*) FROM percorsi) "
        "- (SELECT count(*) FROM percorsi WHERE presente = 0)",
        predefinito=0) or 0)
    fuori["ultimo"] = valore(connessione, "SELECT max(controllato_il) FROM salute_file")
    return fuori


def _segno_o_niente(percorso: Path) -> str | None:
    try:
        return impronta.del_file(percorso)
    except FileNonLeggibile:
        return None


def _quello_da_riparare(connessione: sqlite3.Connection, percorso_id: int) -> sqlite3.Row:
    riga = uno(
        connessione,
        f"""
        SELECT {_COLONNE}, p.nome AS nome
          FROM salute_file AS s
          JOIN percorsi AS p ON {_STESSO}
          JOIN file_media AS f ON f.id = p.file_id
         WHERE s.percorso_id = ?
        """,
        percorso_id,
    )
    if riga is None or riga["prima"] not in DA_RIPARARE:
        raise RiparazioneFerma(
            "Questo file non risulta più rovinato: non c'è niente da rimettere a posto.")
    return riga


def _togli(percorso: Path) -> None:
    try:
        percorso.unlink(missing_ok=True)
    except OSError:
        pass


def _nome_da_parte(percorso_id: int, nome: str) -> str:
    radice, punto, coda = nome.rpartition(".")
    if not punto or len(coda) > 10:
        radice, punto, coda = nome, "", ""
    return f"{percorso_id}-{int(time.time())}-{radice[:100]}{punto}{coda}"


def ripara(archivio, percorso_id: int) -> str:
    if archivio.di_prova:
        raise RiparazioneFerma("Durante una prova i file veri non si toccano.")
    with archivio.lettura() as connessione:
        riga = _quello_da_riparare(connessione, percorso_id)
        compagni = [Path(altro["percorso"]) for altro in tutti(
            connessione,
            "SELECT percorso FROM percorsi WHERE file_id = ? AND id != ? AND presente = 1 "
            "ORDER BY id",
            riga["file_id"], percorso_id)]
    bersaglio = Path(riga["percorso"])
    attesa = riga["impronta"]

    if _segno_o_niente(bersaglio) == attesa:
        stato = bersaglio.stat()
        with archivio.scrittura_di_servizio() as connessione:
            _scrivi(connessione, {
                "percorso_id": percorso_id, "file_id": riga["file_id"],
                "percorso": riga["percorso"], "esito": SANO, "dimensione": stato.st_size,
                "toccato_ns": stato.st_mtime_ns, "dettaglio": None})
        return f"«{riga['nome']}» era già tornato a posto."

    sano = next((altro for altro in compagni if _segno_o_niente(altro) == attesa), None)
    if sano is None:
        raise RiparazioneFerma(
            f"Nell'archivio non c'è una copia sana di «{riga['nome']}». Rimettilo da una "
            "copia di sicurezza (un disco esterno, il cloud): il programma se ne accorge "
            "da solo al prossimo controllo.")

    da_parte = archivio.dove.rovinati
    rifugio = da_parte / _nome_da_parte(percorso_id, bersaglio.name)
    provvisorio = bersaglio.with_name(bersaglio.name + ".riparazione")
    try:
        misura = sano.stat().st_size
        if shutil.disk_usage(bersaglio.parent).free < misura + MARGINE:
            raise RiparazioneFerma(
                f"Sul disco di «{riga['nome']}» non c'è abbastanza spazio per rimetterlo "
                "a posto. Libera un po' di spazio e riprova.")
        da_parte.mkdir(parents=True, exist_ok=True)
        if bersaglio.exists() and shutil.disk_usage(da_parte).free < bersaglio.stat().st_size + MARGINE:
            raise RiparazioneFerma(
                "Non c'è abbastanza spazio per tenere da parte la copia rovinata prima di "
                "sostituirla. Libera un po' di spazio e riprova.")
        _togli(provvisorio)
        shutil.copy2(sano, provvisorio)
        if _segno_o_niente(provvisorio) != attesa:
            raise RiparazioneFerma(
                f"La copia di «{riga['nome']}» non è venuta identica all'originale, quindi "
                "non ho toccato niente. Il disco potrebbe avere dei problemi.")
        if bersaglio.exists():
            shutil.copy2(bersaglio, rifugio)
        os.replace(provvisorio, bersaglio)
    except OSError as guasto:
        raise RiparazioneFerma(
            f"Non sono riuscito a rimettere a posto «{riga['nome']}»: "
            f"{guasto.strerror or guasto}. Forse il file è aperto in un altro programma: "
            "chiudilo e riprova.") from guasto
    finally:
        _togli(provvisorio)

    stato = bersaglio.stat()
    with archivio.scrittura_di_servizio() as connessione:
        _scrivi(connessione, {
            "percorso_id": percorso_id, "file_id": riga["file_id"],
            "percorso": riga["percorso"], "esito": SANO, "dimensione": stato.st_size,
            "toccato_ns": stato.st_mtime_ns,
            "dettaglio": str(rifugio) if rifugio.exists() else None}, riparato=True)
    return f"«{riga['nome']}» è di nuovo com'era."


def ripara_tutti(archivio) -> tuple[int, list[str]]:
    with archivio.lettura() as connessione:
        elenco = [riga for riga in da_riparare(connessione) if riga["ha_un_doppione"]]
    riparati = 0
    guasti = []
    for riga in elenco:
        try:
            ripara(archivio, riga["percorso_id"])
            riparati += 1
        except RiparazioneFerma as guasto:
            guasti.append(guasto.messaggio)
    return riparati, guasti


def accetta(archivio, percorso_id: int) -> None:
    with archivio.scrittura_di_servizio() as connessione:
        riga = _quello_da_riparare(connessione, percorso_id)
        connessione.execute(
            "UPDATE salute_file SET esito = ?, dettaglio = ?, toccato_ns = NULL, "
            "dimensione = NULL WHERE percorso_id = ?",
            (CAMBIATO, ACCETTATO, riga["percorso_id"]))


def si_e_rovinato(connessione: sqlite3.Connection, percorso: Path, segno: str) -> bool:
    riga = uno(
        connessione,
        f"""
        SELECT {_COLONNE}
          FROM percorsi AS p
          JOIN salute_file AS s ON {_STESSO}
          JOIN file_media AS f ON f.id = p.file_id
         WHERE p.percorso = ? AND s.toccato_ns IS NOT NULL
        """,
        str(percorso),
    )
    if riga is None or riga["impronta"] == segno:
        return False
    try:
        stato = os.stat(percorso)
    except OSError:
        return False
    if stato.st_mtime_ns != riga["base_ns"]:
        return False
    _scrivi(connessione, {
        "percorso_id": riga["percorso_id"], "file_id": riga["file_id"],
        "percorso": riga["percorso"], "esito": ROVINATO,
        "dimensione": riga["base_dimensione"], "toccato_ns": riga["base_ns"],
        "dettaglio": None})
    return True
