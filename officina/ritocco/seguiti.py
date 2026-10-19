from __future__ import annotations

import json
import sqlite3
import zlib

from officina.archivio.database import adesso, inserisci, tutti, uno
from officina.ritocco import segui

DA_SEGUIRE = "da_seguire"
IN_CODA = "in_coda"
IN_LAVORO = "in_lavoro"
SEGUITO = "seguito"
FERMATO = "fermato"
FALLITO = "fallito"


def _istanti_in_byte(istanti: list[int]) -> bytes:
    return zlib.compress(json.dumps([int(istante) for istante in istanti]).encode("ascii"), 6)


def istanti(riga: sqlite3.Row) -> list[int]:
    if not riga["istanti"]:
        return []
    return [int(istante) for istante in json.loads(zlib.decompress(riga["istanti"]))]


def nuovo(connessione: sqlite3.Connection, file_id: int, *, cosa: str, impronta: str,
          larghezza: int, altezza: int, quanti: int, istanti_ms: list[int]) -> int:
    return inserisci(
        connessione,
        "INSERT INTO seguiti (file_id, cosa, stato, impronta, larghezza, altezza, quanti, "
        "istanti, messo_il) VALUES (?,?,?,?,?,?,?,?,?)",
        file_id, cosa, DA_SEGUIRE, impronta, int(larghezza), int(altezza), int(quanti),
        _istanti_in_byte(istanti_ms), adesso())


def per_id(connessione: sqlite3.Connection, seguito_id: int) -> sqlite3.Row | None:
    return uno(connessione, "SELECT * FROM seguiti WHERE id = ?", seguito_id)


def segna(connessione: sqlite3.Connection, seguito_id: int, stato: str, *,
          guasto: str | None = None, dove: str | None = None) -> None:
    connessione.execute(
        "UPDATE seguiti SET stato = ?, guasto = ?, dove = coalesce(?, dove), "
        "seguito_il = CASE WHEN ? = 'seguito' THEN ? ELSE seguito_il END WHERE id = ?",
        (stato, guasto, dove, stato, adesso(), seguito_id))


def metti_scelta(connessione: sqlite3.Connection, seguito_id: int, fotogramma: int,
                 maschera: bytes) -> int:
    ultima = uno(connessione,
                 "SELECT coalesce(max(versione), 0) AS v FROM seguiti_scelte WHERE seguito_id = ?",
                 seguito_id)["v"]
    versione = int(ultima) + 1
    connessione.execute(
        "INSERT INTO seguiti_scelte (seguito_id, fotogramma, versione, maschera, messa_il) "
        "VALUES (?,?,?,?,?) ON CONFLICT (seguito_id, fotogramma) DO UPDATE SET "
        "versione = excluded.versione, maschera = excluded.maschera, messa_il = excluded.messa_il",
        (seguito_id, int(fotogramma), versione, maschera, adesso()))
    connessione.execute("UPDATE seguiti SET stato = ?, guasto = NULL WHERE id = ? AND stato <> ?",
                        (DA_SEGUIRE, seguito_id, IN_LAVORO))
    return versione


def togli_scelta(connessione: sqlite3.Connection, seguito_id: int, fotogramma: int) -> bool:
    quante = uno(connessione, "SELECT count(*) AS q FROM seguiti_scelte WHERE seguito_id = ?",
                 seguito_id)["q"]
    if quante <= 1:
        return False
    tolte = connessione.execute(
        "DELETE FROM seguiti_scelte WHERE seguito_id = ? AND fotogramma = ?",
        (seguito_id, int(fotogramma))).rowcount
    if tolte:
        connessione.execute(
            "UPDATE seguiti SET stato = ?, guasto = NULL WHERE id = ? AND stato <> ?",
            (DA_SEGUIRE, seguito_id, IN_LAVORO))
    return bool(tolte)


def scelte(connessione: sqlite3.Connection, seguito_id: int) -> dict[int, tuple[int, bytes]]:
    return {riga["fotogramma"]: (riga["versione"], riga["maschera"]) for riga in tutti(
        connessione,
        "SELECT fotogramma, versione, maschera FROM seguiti_scelte WHERE seguito_id = ? "
        "ORDER BY fotogramma", seguito_id)}


def fatti(connessione: sqlite3.Connection, seguito_id: int) -> dict[int, tuple[int, int]]:
    return {riga["fotogramma"]: (riga["da"], riga["versione"]) for riga in tutti(
        connessione,
        "SELECT fotogramma, da, versione FROM seguiti_fotogrammi WHERE seguito_id = ?",
        seguito_id)}


def scrivi(connessione: sqlite3.Connection, seguito_id: int, arrivati: list,
           versioni: dict[int, int]) -> None:
    connessione.executemany(
        "INSERT INTO seguiti_fotogrammi (seguito_id, fotogramma, da, versione, maschera, "
        "sicurezza) VALUES (?,?,?,?,?,?) ON CONFLICT (seguito_id, fotogramma) DO UPDATE SET "
        "da = excluded.da, versione = excluded.versione, maschera = excluded.maschera, "
        "sicurezza = excluded.sicurezza",
        [(seguito_id, int(indice), int(da), int(versioni[int(da)]), maschera or None,
          float(sicurezza)) for indice, da, maschera, sicurezza in arrivati])


def tratti_da_fare(connessione: sqlite3.Connection, seguito_id: int) -> list[segui.Tratto]:
    riga = per_id(connessione, seguito_id)
    if riga is None:
        return []
    versioni = {fotogramma: versione
                for fotogramma, (versione, _) in scelte(connessione, seguito_id).items()}
    if not versioni:
        return []
    return segui.da_rifare(versioni, fatti(connessione, seguito_id), riga["quanti"])


def presenze(connessione: sqlite3.Connection, seguito_id: int) -> list[list[int]]:
    fuori: list[list[int]] = []
    for riga in tutti(
            connessione,
            "SELECT fotogramma FROM seguiti_fotogrammi WHERE seguito_id = ? "
            "AND maschera IS NOT NULL ORDER BY fotogramma", seguito_id):
        numero = riga["fotogramma"]
        if fuori and fuori[-1][1] == numero - 1:
            fuori[-1][1] = numero
        else:
            fuori.append([numero, numero])
    return fuori


def quanti_fatti(connessione: sqlite3.Connection, seguito_id: int) -> int:
    return uno(connessione,
               "SELECT count(*) AS q FROM seguiti_fotogrammi WHERE seguito_id = ?",
               seguito_id)["q"]


def maschera_di(connessione: sqlite3.Connection, seguito_id: int,
                fotogramma: int) -> bytes | None:
    scelta = uno(connessione,
                 "SELECT maschera FROM seguiti_scelte WHERE seguito_id = ? AND fotogramma = ?",
                 seguito_id, fotogramma)
    if scelta is not None:
        return scelta["maschera"]
    riga = uno(connessione,
               "SELECT maschera FROM seguiti_fotogrammi WHERE seguito_id = ? AND fotogramma = ?",
               seguito_id, fotogramma)
    return None if riga is None else riga["maschera"]


def tutte_le_maschere(connessione: sqlite3.Connection, seguito_id: int) -> dict[int, bytes]:
    fuori = {riga["fotogramma"]: riga["maschera"] for riga in tutti(
        connessione,
        "SELECT fotogramma, maschera FROM seguiti_fotogrammi WHERE seguito_id = ? "
        "AND maschera IS NOT NULL", seguito_id)}
    for fotogramma, (_, maschera) in scelte(connessione, seguito_id).items():
        fuori[fotogramma] = maschera
    return fuori


def come_sta(connessione: sqlite3.Connection, seguito_id: int) -> dict | None:
    riga = per_id(connessione, seguito_id)
    if riga is None:
        return None
    return {"id": riga["id"], "file": riga["file_id"], "cosa": riga["cosa"],
            "stato": riga["stato"], "guasto": riga["guasto"] or "", "dove": riga["dove"] or "",
            "larghezza": riga["larghezza"], "altezza": riga["altezza"], "quanti": riga["quanti"],
            "fatti": quanti_fatti(connessione, seguito_id),
            "scelte": sorted(scelte(connessione, seguito_id)),
            "presenze": presenze(connessione, seguito_id)}
