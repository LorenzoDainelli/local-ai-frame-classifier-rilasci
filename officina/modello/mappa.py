from __future__ import annotations

import json
import math
import re
import sqlite3
from collections import Counter
from datetime import date

from officina.archivio import memoria
from officina.archivio.database import tutti, valore

PUNTI_AL_MASSIMO = 30_000
MARGINE_DEL_PUNTO = 0.0006
_GIORNO = re.compile(r"\d{4}-\d{2}-\d{2}")


def zona_da_testo(testo) -> tuple[float, float, float, float] | None:
    pezzi = str(testo or "").split(",")
    if len(pezzi) != 4 or any(len(p.strip()) > 24 for p in pezzi):
        return None
    try:
        sud, ovest, nord, est = (float(p) for p in pezzi)
    except ValueError:
        return None
    if not all(math.isfinite(x) for x in (sud, ovest, nord, est)):
        return None
    if not (-90.0 <= sud <= nord <= 90.0):
        return None
    if not (-180.0 <= ovest <= 180.0 and -180.0 <= est <= 180.0):
        return None
    return (round(sud, 6), round(ovest, 6), round(nord, 6), round(est, 6))


def zona_a_testo(zona: tuple[float, float, float, float]) -> str:
    return ",".join(f"{x:.6f}".rstrip("0").rstrip(".") for x in zona)


def giorno_valido(testo) -> str | None:
    pulito = str(testo or "").strip()
    if not _GIORNO.fullmatch(pulito):
        return None
    try:
        date.fromisoformat(pulito)
    except ValueError:
        return None
    return pulito


_mesi = memoria.Ricordo("mesi della linea del tempo")
_punti = memoria.Ricordi("punti della mappa", 8)


def mesi(connessione: sqlite3.Connection) -> list[dict]:
    return _mesi.prendi(connessione, lambda: [dict(r) for r in tutti(
        connessione,
        "SELECT substr(giorno, 1, 7) AS mese, count(*) AS quanti, "
        "count(latitudine) AS col_luogo FROM scatti "
        "WHERE fuori_archivio = 0 AND giorno IS NOT NULL "
        "AND giorno GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-*' "
        "GROUP BY mese ORDER BY mese")])


def quanti_senza_data(connessione: sqlite3.Connection) -> int:
    return valore(connessione,
                  "SELECT count(*) FROM scatti WHERE fuori_archivio = 0 AND giorno IS NULL",
                  predefinito=0)


def punti(connessione: sqlite3.Connection, dal: str | None = None,
          al: str | None = None) -> dict:
    return _raggruppa(connessione, dal, al)


def punti_in_json(connessione: sqlite3.Connection, dal: str | None = None,
                  al: str | None = None) -> bytes:
    return _punti.prendi(connessione, (dal, al, PUNTI_AL_MASSIMO), lambda: json.dumps(
        _raggruppa(connessione, dal, al), separators=(",", ":"), allow_nan=False).encode())


def _raggruppa(connessione: sqlite3.Connection, dal: str | None, al: str | None) -> dict:
    cursore = connessione.cursor()
    cursore.row_factory = None
    posizioni = cursore.execute(
        "SELECT latitudine, longitudine FROM scatti WHERE fuori_archivio = 0 "
        "AND latitudine BETWEEN -90 AND 90 AND longitudine BETWEEN -180 AND 180 "
        "AND (? IS NULL OR giorno >= ?) AND (? IS NULL OR giorno <= ?)",
        (dal, dal, al, al)).fetchall()
    for cifre in (3, 2, 1, 0):
        conti = Counter((round(la, cifre), round(lo, cifre)) for la, lo in posizioni)
        if len(conti) <= PUNTI_AL_MASSIMO:
            break
    return {"cifre": cifre,
            "punti": [[la, lo, n] for (la, lo), n in conti.items()],
            "quanti": len(posizioni)}


def nomi_dei_posti(connessione: sqlite3.Connection) -> list[dict]:
    return [dict(r) for r in tutti(
        connessione,
        "SELECT p.id AS posto_id, p.nome, p.latitudine AS la, p.longitudine AS lo, "
        "coalesce(p.raggio_metri, 0) AS raggio, "
        "(SELECT count(*) FROM posti_negli_scatti n WHERE n.posto_id = p.id) AS scatti "
        "FROM posti p WHERE p.stato = 'attivo' AND p.latitudine IS NOT NULL "
        "AND p.longitudine IS NOT NULL ORDER BY scatti DESC, p.id")]


def zona_attorno(sud: float, ovest: float, nord: float, est: float,
                 margine: float = MARGINE_DEL_PUNTO) -> tuple[float, float, float, float]:
    return (max(-90.0, sud - margine), max(-180.0, ovest - margine),
            min(90.0, nord + margine), min(180.0, est + margine))
