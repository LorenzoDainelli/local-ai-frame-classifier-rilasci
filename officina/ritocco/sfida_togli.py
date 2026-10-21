from __future__ import annotations

import json
import random
import sqlite3
from pathlib import Path

from officina.archivio.database import adesso, leggi_stato, scrivi_stato, tutti, uno
from officina.errori import ErroreOfficina
from officina.ritocco import togliere

FOTO, VIDEO = "foto", "video"
QUANTE = {FOTO: 50, VIDEO: 20}
SCELTI = {FOTO: "togli_foto_motori", VIDEO: "togli_video_motori"}
VOTI = ("A", "B", "pari", "nessuna")
CHIUSA = "sfida_togli_chiusa_{genere}"
PRINCIPALE_FOTO = "togli_motore"


class VotoRifiutato(ErroreOfficina):
    codice = "sfida_togli_voto"


def genere_del_file(genere_media: str) -> str:
    return VIDEO if genere_media == "video" else FOTO


def i_due(archivio, genere: str) -> tuple[str, str] | None:
    try:
        scelti = json.loads(archivio.impostazione(SCELTI[genere]) or "[]")
    except ValueError:
        return None
    pronti = [nome for nome in scelti if nome in togliere.MOTORI]
    return (pronti[0], pronti[1]) if len(pronti) >= 2 else None


def chiusa(connessione: sqlite3.Connection, genere: str) -> dict | None:
    return leggi_stato(connessione, CHIUSA.format(genere=genere), None)


def quante(connessione: sqlite3.Connection, genere: str) -> int:
    return uno(connessione, "SELECT COUNT(*) AS n FROM sfide_togli WHERE genere = ? "
               "AND (voto IS NULL OR voto != 'nessuna')", genere)["n"]


def votate(connessione: sqlite3.Connection, genere: str) -> int:
    return uno(connessione, "SELECT COUNT(*) AS n FROM sfide_togli WHERE genere = ? "
               "AND voto IS NOT NULL AND voto != 'nessuna'", genere)["n"]


def si_fa(archivio, genere: str) -> tuple[str, str] | None:
    due = i_due(archivio, genere)
    if due is None:
        return None
    with archivio.lettura() as connessione:
        if chiusa(connessione, genere) is not None:
            return None
        if quante(connessione, genere) >= QUANTE[genere]:
            return None
    return due


def sorteggia(due: tuple[str, str], caso: random.Random | None = None) -> dict:
    caso = caso or random.SystemRandom()
    a, b = due if caso.random() < 0.5 else (due[1], due[0])
    return {"motore_a": a, "motore_b": b, "sinistra": "A" if caso.random() < 0.5 else "B"}


def registra(connessione: sqlite3.Connection, lavoro_id: int, file_id: int, genere: str,
             sfida: dict) -> None:
    connessione.execute(
        "INSERT OR REPLACE INTO sfide_togli (lavoro_id, file_id, genere, motore_a, motore_b, "
        "sinistra, pronta_b, impronta_b, toppe_b, messa_il) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (lavoro_id, file_id, genere, sfida["motore_a"], sfida["motore_b"], sfida["sinistra"],
         sfida.get("pronta_b"), sfida.get("impronta_b"), json.dumps(sfida.get("toppe_b") or {}),
         adesso()))


def del_file(connessione: sqlite3.Connection, lavoro_id: int,
             file_id: int) -> sqlite3.Row | None:
    return uno(connessione, "SELECT * FROM sfide_togli WHERE lavoro_id = ? AND file_id = ?",
               lavoro_id, file_id)


def del_lavoro(connessione: sqlite3.Connection, lavoro_id: int) -> list[sqlite3.Row]:
    return tutti(connessione, "SELECT * FROM sfide_togli WHERE lavoro_id = ? ORDER BY file_id",
                 lavoro_id)


def da_votare(connessione: sqlite3.Connection, lavoro_id: int) -> list[sqlite3.Row]:
    return [riga for riga in del_lavoro(connessione, lavoro_id) if riga["voto"] is None]


def _toppe(riga) -> dict:
    toppe = riga["toppe_b"] or {}
    return json.loads(toppe) if isinstance(toppe, str) else toppe


def file_della_b(riga) -> list[Path]:
    fuori = [Path(riga["pronta_b"])] if riga["pronta_b"] else []
    for toppa in _toppe(riga).values():
        if toppa.get("risultato"):
            fuori.append(Path(toppa["risultato"]))
    return fuori


def file_della_a(connessione: sqlite3.Connection, riga) -> list[Path]:
    quali = sorted(int(chiave) for chiave in _toppe(riga))
    fuori = []
    for ritocco in tutti(connessione, "SELECT risultato FROM ritocchi "
                         "WHERE id IN (SELECT value FROM json_each(?))", json.dumps(quali)):
        if ritocco["risultato"]:
            fuori.append(Path(ritocco["risultato"]))
    pronta = uno(connessione, "SELECT pronta FROM ritocchi_lavori_file WHERE lavoro_id = ? "
                 "AND file_id = ?", riga["lavoro_id"], riga["file_id"])
    if pronta is not None and pronta["pronta"]:
        fuori.append(Path(pronta["pronta"]))
    return fuori


def _metti_la_b(connessione: sqlite3.Connection, riga) -> None:
    for chiave, toppa in _toppe(riga).items():
        connessione.execute(
            "UPDATE ritocchi SET risultato = ?, impronta_risultato = ?, origine_x = ?, "
            "origine_y = ?, traccia = ? WHERE id = ?",
            (toppa["risultato"], toppa["impronta_risultato"], toppa["origine_x"],
             toppa["origine_y"], toppa.get("traccia"), int(chiave)))
    connessione.execute(
        "UPDATE ritocchi_lavori_file SET pronta = ?, impronta_pronta = ? "
        "WHERE lavoro_id = ? AND file_id = ?",
        (riga["pronta_b"], riga["impronta_b"], riga["lavoro_id"], riga["file_id"]))


def _dimentica_le_toppe(connessione: sqlite3.Connection, riga) -> None:
    quali = sorted(int(chiave) for chiave in _toppe(riga))
    connessione.execute(
        "UPDATE ritocchi SET risultato = NULL, impronta_risultato = NULL, origine_x = NULL, "
        "origine_y = NULL, traccia = NULL WHERE id IN (SELECT value FROM json_each(?))",
        (json.dumps(quali),))


def vota(connessione: sqlite3.Connection, lavoro_id: int, file_id: int,
         voto: str) -> list[Path]:
    if voto not in VOTI:
        raise VotoRifiutato("Questo voto non esiste.")
    riga = del_file(connessione, lavoro_id, file_id)
    if riga is None or riga["voto"] is not None:
        raise VotoRifiutato("Questa sfida è già stata votata o non c'è più.")
    if voto == "B":
        buttare = file_della_a(connessione, riga)
        _metti_la_b(connessione, riga)
    elif voto == "nessuna":
        buttare = file_della_a(connessione, riga) + file_della_b(riga)
        _dimentica_le_toppe(connessione, riga)
    else:
        buttare = file_della_b(riga)
    connessione.execute(
        "UPDATE sfide_togli SET voto = ?, votata_il = ?, pronta_b = NULL, impronta_b = NULL "
        "WHERE lavoro_id = ? AND file_id = ?", (voto, adesso(), lavoro_id, file_id))
    return buttare


def butta(file: list[Path]) -> None:
    from officina.ritocco import copia

    for percorso in file:
        if percorso.name.startswith(copia.PREFISSO):
            copia.butta(percorso)
        elif percorso.name.startswith("togli-"):
            percorso.unlink(missing_ok=True)


def lascia_il_lavoro(connessione: sqlite3.Connection, lavoro_id: int) -> list[Path]:
    buttare = []
    for riga in da_votare(connessione, lavoro_id):
        buttare += file_della_b(riga)
    connessione.execute("DELETE FROM sfide_togli WHERE lavoro_id = ? AND voto IS NULL",
                        (lavoro_id,))
    return buttare


def lettera_del_lato(riga, lato: str) -> str:
    return riga["sinistra"] if lato == "sinistra" else ("B" if riga["sinistra"] == "A" else "A")


def conti(connessione: sqlite3.Connection, genere: str) -> dict:
    numeri: dict[str, int] = {}
    for riga in tutti(connessione, "SELECT motore_a, motore_b, voto FROM sfide_togli "
                      "WHERE genere = ? AND voto IS NOT NULL", genere):
        if riga["voto"] == "A":
            chi = riga["motore_a"]
        elif riga["voto"] == "B":
            chi = riga["motore_b"]
        else:
            chi = riga["voto"]
        numeri[chi] = numeri.get(chi, 0) + 1
    return numeri


def finita(connessione: sqlite3.Connection, genere: str) -> bool:
    if chiusa(connessione, genere) is not None:
        return False
    votate = uno(connessione, "SELECT COUNT(*) AS n FROM sfide_togli WHERE genere = ? "
                 "AND voto IS NOT NULL AND voto != 'nessuna'", genere)["n"]
    aperte = uno(connessione, "SELECT COUNT(*) AS n FROM sfide_togli WHERE genere = ? "
                 "AND voto IS NULL", genere)["n"]
    return votate >= QUANTE[genere] and not aperte


def vincitore(numeri: dict, due: tuple[str, str]) -> str | None:
    a, b = numeri.get(due[0], 0), numeri.get(due[1], 0)
    if a == b:
        return None
    return due[0] if a > b else due[1]


def chiudi(archivio, genere: str, principale: str) -> None:
    due = i_due(archivio, genere)
    if due is None or principale not in due:
        raise VotoRifiutato("Questo modello non è fra i due della sfida.")
    altro = due[1] if principale == due[0] else due[0]
    if genere == FOTO:
        archivio.imposta(PRINCIPALE_FOTO, principale)
    archivio.imposta(SCELTI[genere], json.dumps([principale, altro]))
    with archivio.scrittura() as connessione:
        scrivi_stato(connessione, CHIUSA.format(genere=genere),
                     {"principale": principale, "chiusa_il": adesso()})


def fine(archivio, genere: str) -> dict | None:
    due = i_due(archivio, genere)
    if due is None:
        return None
    with archivio.lettura() as connessione:
        if not finita(connessione, genere):
            return None
        numeri = conti(connessione, genere)
    return {"genere": genere, "due": list(due), "conti": numeri,
            "vincitore": vincitore(numeri, due)}
