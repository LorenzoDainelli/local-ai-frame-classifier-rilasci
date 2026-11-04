from __future__ import annotations

import json
import random
import sqlite3
from pathlib import Path
from typing import NamedTuple

from officina.archivio.database import adesso, leggi_stato, scrivi_stato, tutti, uno
from officina import tempo_gara
from officina.errori import ErroreOfficina
from officina.miglioria import attesa
from officina.ritocco import togliere

FOTO, VIDEO = "foto", "video"
QUANTE = {FOTO: 50, VIDEO: 20}
SCELTI = {FOTO: "togli_foto_motori", VIDEO: "togli_video_motori"}
VOTI = ("A", "B", "pari", "nessuna")
CHIUSA = "sfida_togli_chiusa_{genere}"
PRINCIPALE_FOTO = "togli_motore"


class VotoRifiutato(ErroreOfficina):
    codice = "sfida_togli_voto"


class DaButtare(NamedTuple):
    percorso: Path
    file_id: int | None = None
    impronta: str | None = None
    ritocco_id: int | None = None


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
        "INSERT INTO sfide_togli (lavoro_id, file_id, genere, motore_a, motore_b, sinistra, "
        "pronta_b, impronta_b, toppe_b, secondi_a, secondi_b, messa_il) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(lavoro_id, file_id) DO UPDATE SET genere = excluded.genere, "
        "motore_a = excluded.motore_a, motore_b = excluded.motore_b, "
        "sinistra = excluded.sinistra, pronta_b = excluded.pronta_b, "
        "impronta_b = excluded.impronta_b, toppe_b = excluded.toppe_b, "
        "secondi_a = excluded.secondi_a, secondi_b = excluded.secondi_b, "
        "messa_il = excluded.messa_il WHERE sfide_togli.voto IS NULL",
        (lavoro_id, file_id, genere, sfida["motore_a"], sfida["motore_b"], sfida["sinistra"],
         sfida.get("pronta_b"), sfida.get("impronta_b"), json.dumps(sfida.get("toppe_b") or {}),
         tempo_gara.buoni(sfida.get("secondi_a")), tempo_gara.buoni(sfida.get("secondi_b")),
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


def file_della_b(riga, file_id: int) -> list[DaButtare]:
    fuori = ([DaButtare(Path(riga["pronta_b"]), file_id, riga["impronta_b"])]
             if riga["pronta_b"] else [])
    for chiave, toppa in _toppe(riga).items():
        if toppa.get("risultato"):
            fuori.append(DaButtare(Path(toppa["risultato"]), file_id,
                                   toppa.get("impronta_risultato"), int(chiave)))
    return fuori


def file_della_a(connessione: sqlite3.Connection, riga) -> list[DaButtare]:
    quali = sorted(int(chiave) for chiave in _toppe(riga))
    fuori = []
    for ritocco in tutti(connessione, "SELECT id, risultato, impronta_risultato "
                         "FROM ritocchi WHERE id IN (SELECT value FROM json_each(?)) "
                         "ORDER BY id", json.dumps(quali)):
        if ritocco["risultato"]:
            fuori.append(DaButtare(Path(ritocco["risultato"]), riga["file_id"],
                                   ritocco["impronta_risultato"], ritocco["id"]))
    pronta = uno(connessione, "SELECT pronta, impronta_pronta FROM ritocchi_lavori_file "
                 "WHERE lavoro_id = ? AND file_id = ?", riga["lavoro_id"], riga["file_id"])
    if pronta is not None and pronta["pronta"]:
        fuori.append(DaButtare(Path(pronta["pronta"]), riga["file_id"],
                               pronta["impronta_pronta"]))
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
         voto: str) -> list[DaButtare]:
    if voto not in VOTI:
        raise VotoRifiutato("Questo voto non esiste.")
    riga = del_file(connessione, lavoro_id, file_id)
    if riga is None or riga["voto"] is not None:
        raise VotoRifiutato("Questa sfida è già stata votata o non c'è più.")
    if voto == "B":
        buttare = file_della_a(connessione, riga)
        _metti_la_b(connessione, riga)
    elif voto == "nessuna":
        buttare = file_della_a(connessione, riga) + file_della_b(riga, file_id)
        _dimentica_le_toppe(connessione, riga)
    else:
        buttare = file_della_b(riga, file_id)
    connessione.execute(
        "UPDATE sfide_togli SET voto = ?, votata_il = ?, pronta_b = NULL, impronta_b = NULL "
        "WHERE lavoro_id = ? AND file_id = ?", (voto, adesso(), lavoro_id, file_id))
    return buttare


def si_butta(voce: DaButtare) -> bool:
    from officina.ritocco import copia

    percorso = Path(voce.percorso)
    if voce.ritocco_id is None:
        return attesa.e_dentro(percorso) and percorso.name.startswith(copia.PREFISSO)
    return copia._e_una_toppa(percorso, voce.ritocco_id)


def butta(file: list) -> None:
    from officina.ritocco import copia

    for voce in file:
        voce = DaButtare(*voce) if isinstance(voce, tuple) else DaButtare(Path(voce))
        if not si_butta(voce):
            continue
        if voce.ritocco_id is None:
            copia.butta(Path(voce.percorso))
        elif Path(voce.percorso).is_file():
            Path(voce.percorso).unlink()


def lascia_il_lavoro(connessione: sqlite3.Connection, lavoro_id: int) -> list[DaButtare]:
    buttare = []
    for riga in da_votare(connessione, lavoro_id):
        buttare += file_della_b(riga, riga["file_id"])
    connessione.execute("DELETE FROM sfide_togli WHERE lavoro_id = ? AND voto IS NULL",
                        (lavoro_id,))
    return buttare


def lettera_del_lato(riga, lato: str) -> str:
    return riga["sinistra"] if lato == "sinistra" else ("B" if riga["sinistra"] == "A" else "A")


def secondi_della_lettera(riga, lettera: str) -> float | None:
    try:
        return tempo_gara.buoni(riga["secondi_a" if lettera == "A" else "secondi_b"])
    except (IndexError, KeyError):
        return None


def tempi_medi(connessione: sqlite3.Connection, genere: str) -> dict:
    misure: dict[str, list[float]] = {}
    for riga in tutti(connessione, "SELECT motore_a, motore_b, secondi_a, secondi_b "
                      "FROM sfide_togli WHERE genere = ?", genere):
        for lettera in ("a", "b"):
            secondi = tempo_gara.buoni(riga[f"secondi_{lettera}"])
            if secondi is not None:
                misure.setdefault(riga[f"motore_{lettera}"], []).append(secondi)
    return {motore: (tempo_gara.media(valori), len(valori))
            for motore, valori in misure.items()}


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
        medi = tempi_medi(connessione, genere)
    return {"genere": genere, "due": list(due), "conti": numeri,
            "vincitore": vincitore(numeri, due),
            "tempi": {motore: tempo_gara.media_a_parole(*medi.get(motore, (None, 0)))
                      for motore in due}}
