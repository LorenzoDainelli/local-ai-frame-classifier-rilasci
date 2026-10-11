from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

CARTELLA = Path(__file__).parent


def adesso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def connetti(percorso: Path) -> sqlite3.Connection:
    percorso.parent.mkdir(parents=True, exist_ok=True)
    connessione = sqlite3.connect(
        percorso,
        check_same_thread=False,
        isolation_level=None,
        timeout=30.0,
    )
    connessione.row_factory = sqlite3.Row
    connessione.execute("PRAGMA journal_mode = WAL")
    connessione.execute("PRAGMA foreign_keys = ON")
    connessione.execute("PRAGMA synchronous = FULL")
    connessione.execute("PRAGMA busy_timeout = 30000")
    connessione.execute("PRAGMA temp_store = MEMORY")
    return connessione


def non_ha_mai_guardato(connessione: sqlite3.Connection) -> bool:
    riga = connessione.execute(
        "SELECT count(*) AS q FROM sqlite_master "
        "WHERE type = 'table' AND name = 'sqlite_stat1'").fetchone()
    return not (riga["q"] if riga else 0)


def impara_com_e_fatto(connessione: sqlite3.Connection) -> None:
    connessione.execute("ANALYZE")


def ripassa_com_e_fatto(connessione: sqlite3.Connection) -> None:
    connessione.execute("PRAGMA optimize")


def istruzioni(testo: str):
    pezzo = []
    dentro_apici = False
    for riga in testo.splitlines():
        if not dentro_apici:
            senza_commento = []
            i = 0
            while i < len(riga):
                if riga[i] == "'":
                    dentro_apici = not dentro_apici
                elif not dentro_apici and riga[i:i + 2] == "--":
                    break
                senza_commento.append(riga[i])
                i += 1
            riga = "".join(senza_commento)
        pezzo.append(riga)
        unite = "\n".join(pezzo)
        while ";" in unite and not dentro_apici:
            prima, _, dopo = unite.partition(";")
            if prima.strip():
                yield prima.strip()
            unite = dopo
            pezzo = [dopo]
    resto = "\n".join(pezzo).strip()
    if resto:
        yield resto


def crea_da_zero(connessione: sqlite3.Connection) -> None:
    testo = (CARTELLA / "schema.sql").read_text(encoding="utf-8")
    for istruzione in istruzioni(testo):
        connessione.execute(istruzione)


def uno(connessione: sqlite3.Connection, sql: str, *parametri) -> sqlite3.Row | None:
    return connessione.execute(sql, parametri).fetchone()


def tutti(connessione: sqlite3.Connection, sql: str, *parametri) -> list[sqlite3.Row]:
    return connessione.execute(sql, parametri).fetchall()


def valore(connessione: sqlite3.Connection, sql: str, *parametri, predefinito=None):
    riga = uno(connessione, sql, *parametri)
    return riga[0] if riga is not None and riga[0] is not None else predefinito


def esegui(connessione: sqlite3.Connection, sql: str, *parametri) -> sqlite3.Cursor:
    return connessione.execute(sql, parametri)


def inserisci(connessione: sqlite3.Connection, sql: str, *parametri) -> int:
    return connessione.execute(sql, parametri).lastrowid


def leggi_impostazione(connessione: sqlite3.Connection, chiave: str, predefinito=None):
    riga = uno(connessione, "SELECT valore FROM impostazioni WHERE chiave = ?", chiave)
    if riga is None:
        return predefinito
    try:
        return json.loads(riga["valore"])
    except json.JSONDecodeError:
        return predefinito


def scrivi_impostazione(connessione: sqlite3.Connection, chiave: str, valore_nuovo,
                        quando: str | None = None) -> None:
    connessione.execute(
        "INSERT INTO impostazioni (chiave, valore, cambiata_il) VALUES (?, ?, ?) "
        "ON CONFLICT(chiave) DO UPDATE SET valore = excluded.valore, "
        "cambiata_il = excluded.cambiata_il",
        (chiave, json.dumps(valore_nuovo, ensure_ascii=False), quando or adesso()),
    )


def scrivi_valore_di_partenza(connessione: sqlite3.Connection, chiave: str,
                              valore) -> None:
    connessione.execute(
        "INSERT INTO impostazioni (chiave, valore, cambiata_il) VALUES (?, ?, NULL) "
        "ON CONFLICT(chiave) DO UPDATE SET valore = excluded.valore, "
        "cambiata_il = NULL",
        (chiave, json.dumps(valore, ensure_ascii=False)),
    )


def leggi_stato(connessione: sqlite3.Connection, chiave: str, predefinito=None):
    riga = uno(connessione, "SELECT valore FROM stato WHERE chiave = ?", chiave)
    if riga is None:
        return predefinito
    try:
        return json.loads(riga["valore"])
    except json.JSONDecodeError:
        return predefinito


def scrivi_stato(connessione: sqlite3.Connection, chiave: str, valore_nuovo) -> None:
    scritto = json.dumps(valore_nuovo, ensure_ascii=False)
    riga = connessione.execute(
        "SELECT valore FROM stato WHERE chiave = ?", (chiave,)).fetchone()
    if riga is not None and riga[0] == scritto:
        return
    connessione.execute(
        "INSERT INTO stato (chiave, valore, aggiornato_il) VALUES (?, ?, ?) "
        "ON CONFLICT(chiave) DO UPDATE SET valore = excluded.valore, "
        "aggiornato_il = excluded.aggiornato_il",
        (chiave, scritto, adesso()),
    )
