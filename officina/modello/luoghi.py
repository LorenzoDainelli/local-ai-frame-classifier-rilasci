from __future__ import annotations

import math
import sqlite3

from officina.archivio.database import (adesso, esegui, inserisci, tutti,
                                        uno, valore)

RAGGIO_METRI = 200.0

METRI_PER_GRADO = 111_320.0


def distanza_metri(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    mezzo = math.radians((lat1 + lat2) / 2)
    dx = (lon2 - lon1) * METRI_PER_GRADO * math.cos(mezzo)
    dy = (lat2 - lat1) * METRI_PER_GRADO
    return math.hypot(dx, dy)


def per_id(connessione: sqlite3.Connection, luogo_id: int) -> sqlite3.Row | None:
    return uno(connessione, "SELECT * FROM luoghi WHERE id = ?", luogo_id)


def elenco(connessione: sqlite3.Connection) -> list[dict]:
    righe = tutti(
        connessione,
        """
        SELECT l.*,
               count(s.id)   AS scatti,
               min(s.giorno) AS dal,
               max(s.giorno) AS al
        FROM luoghi l
        LEFT JOIN scatti s ON s.luogo_id = l.id AND s.fuori_archivio = 0
        GROUP BY l.id
        ORDER BY count(s.id) DESC, l.id
        """)
    return [dict(riga) for riga in righe]


def senza_nome(connessione: sqlite3.Connection) -> int:
    return valore(connessione,
                  "SELECT count(*) FROM luoghi WHERE nome IS NULL OR nome = ''",
                  predefinito=0)


def del_scatto(connessione: sqlite3.Connection, scatto_id: int
               ) -> sqlite3.Row | None:
    return uno(connessione,
               "SELECT l.* FROM luoghi l "
               "JOIN scatti s ON s.luogo_id = l.id WHERE s.id = ?", scatto_id)


def chiama(connessione: sqlite3.Connection, luogo_id: int, nome: str) -> None:
    pulito = (nome or "").strip()
    esegui(connessione, "UPDATE luoghi SET nome = ? WHERE id = ?",
           pulito or None, luogo_id)


def unisci(connessione: sqlite3.Connection, da_id: int, verso_id: int) -> int:
    if da_id == verso_id:
        return 0
    if per_id(connessione, verso_id) is None:
        return 0
    cursore = esegui(connessione,
                     "UPDATE scatti SET luogo_id = ? WHERE luogo_id = ?",
                     verso_id, da_id)
    spostati = cursore.rowcount
    esegui(connessione, "DELETE FROM luoghi WHERE id = ?", da_id)
    _riassesta(connessione, verso_id)
    return spostati


def raggruppa(connessione: sqlite3.Connection,
              raggio: float = RAGGIO_METRI) -> dict:
    conosciuti = [
        {"id": riga["id"], "lat": riga["centro_lat"], "lon": riga["centro_lon"]}
        for riga in tutti(connessione, "SELECT * FROM luoghi")
    ]

    da_sistemare = tutti(
        connessione,
        "SELECT id, latitudine, longitudine FROM scatti "
        "WHERE luogo_id IS NULL AND latitudine IS NOT NULL "
        "AND longitudine IS NOT NULL ORDER BY id")

    nuovi, sistemati = 0, 0
    for scatto in da_sistemare:
        lat, lon = scatto["latitudine"], scatto["longitudine"]
        vicino, quanto = None, None
        for luogo in conosciuti:
            quanti_metri = distanza_metri(lat, lon, luogo["lat"], luogo["lon"])
            if quanti_metri <= raggio and (quanto is None or quanti_metri < quanto):
                vicino, quanto = luogo, quanti_metri
        if vicino is None:
            vicino = {"id": inserisci(
                connessione,
                "INSERT INTO luoghi (nome, centro_lat, centro_lon, "
                "raggio_metri, quanti, nato_il) VALUES (NULL, ?, ?, 0, 0, ?)",
                lat, lon, adesso()), "lat": lat, "lon": lon}
            conosciuti.append(vicino)
            nuovi += 1
        esegui(connessione, "UPDATE scatti SET luogo_id = ? WHERE id = ?",
               vicino["id"], scatto["id"])
        sistemati += 1

    for luogo in conosciuti:
        _riassesta(connessione, luogo["id"])

    senza = valore(connessione,
                   "SELECT count(*) FROM scatti WHERE latitudine IS NULL",
                   predefinito=0)
    return {"sistemati": sistemati, "nuovi": nuovi,
            "luoghi": len(conosciuti), "senza_coordinate": senza}


def _riassesta(connessione: sqlite3.Connection, luogo_id: int) -> None:
    righe = tutti(connessione,
                  "SELECT latitudine, longitudine FROM scatti "
                  "WHERE luogo_id = ? AND latitudine IS NOT NULL", luogo_id)
    if not righe:
        esegui(connessione, "UPDATE luoghi SET quanti = 0 WHERE id = ?", luogo_id)
        return
    lat = sum(r["latitudine"] for r in righe) / len(righe)
    lon = sum(r["longitudine"] for r in righe) / len(righe)
    raggio = max(distanza_metri(lat, lon, r["latitudine"], r["longitudine"])
                 for r in righe)
    esegui(connessione,
           "UPDATE luoghi SET centro_lat = ?, centro_lon = ?, "
           "raggio_metri = ?, quanti = ? WHERE id = ?",
           lat, lon, raggio, len(righe), luogo_id)
