from __future__ import annotations

import json
import random
import sqlite3
from pathlib import Path

from officina.archivio.database import (adesso, inserisci, leggi_impostazione,
                                        scrivi_impostazione, tutti, uno, valore)
from officina.errori import ErroreOfficina
from officina.miglioria import coda, motori

QUANTE = 100
SFIDANTI = (motori.SEEDVR2, motori.LUCIDFLUX)
VOTI = ("A", "B", "pari", "nessuna")
CHIUSA = "sfida_chiusa"
NOMI = {motori.SEEDVR2: "SeedVR2", motori.LUCIDFLUX: "LucidFlux"}


class VotoRifiutato(ErroreOfficina):
    codice = "voto_rifiutato"


def chiusa(connessione: sqlite3.Connection) -> dict | None:
    esito = leggi_impostazione(connessione, CHIUSA)
    return esito if isinstance(esito, dict) else None


def quante_fatte(connessione: sqlite3.Connection) -> int:
    return int(valore(connessione, "SELECT count(*) FROM sfide", predefinito=0))


def si_fa(connessione: sqlite3.Connection, pronte: bool) -> bool:
    return pronte and chiusa(connessione) is None and quante_fatte(connessione) < QUANTE


def l_altro(motore: str) -> str:
    return SFIDANTI[1] if motore == SFIDANTI[0] else SFIDANTI[0]


def registra(connessione: sqlite3.Connection, miglioria_id: int, versioni: dict,
             caso: random.Random | None = None) -> int:
    caso = caso or random.SystemRandom()
    campi = {}
    for motore in SFIDANTI:
        percorso, impronta, usati = versioni[motore]
        campi[motore] = (str(percorso), impronta, json.dumps(usati or []))
    return inserisci(
        connessione,
        "INSERT INTO sfide (miglioria_id, percorso_seedvr2, percorso_lucidflux, "
        "impronta_seedvr2, impronta_lucidflux, motori_seedvr2, motori_lucidflux, "
        "a_e, a_sinistra, fatta_il) VALUES (?,?,?,?,?,?,?,?,?,?)",
        miglioria_id, campi[motori.SEEDVR2][0], campi[motori.LUCIDFLUX][0],
        campi[motori.SEEDVR2][1], campi[motori.LUCIDFLUX][1],
        campi[motori.SEEDVR2][2], campi[motori.LUCIDFLUX][2],
        caso.choice(SFIDANTI), caso.choice((0, 1)), adesso())


def da_votare(connessione: sqlite3.Connection) -> list[sqlite3.Row]:
    return tutti(connessione,
                 "SELECT s.*, m.percorso_originale, m.larghezza_prima, "
                 "m.altezza_prima, m.larghezza_dopo, m.altezza_dopo, m.scatto_id, "
                 "m.file_id FROM sfide AS s JOIN migliorie AS m ON m.id = s.miglioria_id "
                 "WHERE s.voto IS NULL AND m.stato = ? ORDER BY s.id", coda.DA_RIVEDERE)


def aspettano(connessione: sqlite3.Connection) -> set[int]:
    return {riga["miglioria_id"] for riga in tutti(
        connessione, "SELECT miglioria_id FROM sfide WHERE voto IS NULL OR voto = 'pari'")}


def per_miglioria(connessione: sqlite3.Connection,
                  miglioria_id: int) -> sqlite3.Row | None:
    return uno(connessione, "SELECT * FROM sfide WHERE miglioria_id = ?", miglioria_id)


def chi_e(riga, lettera: str) -> str:
    return riga["a_e"] if lettera == "A" else l_altro(riga["a_e"])


def lettera_del_lato(riga, lato: str) -> str:
    sinistra = "A" if riga["a_sinistra"] else "B"
    if lato == "sinistra":
        return sinistra
    return "B" if sinistra == "A" else "A"


def file_della_lettera(riga, lettera: str) -> Path:
    return Path(riga[f"percorso_{chi_e(riga, lettera)}"] or "")


def _tieni(connessione: sqlite3.Connection, riga, motore: str) -> list[Path]:
    connessione.execute(
        "UPDATE migliorie SET in_revisione = ?, impronta_migliorata = ?, motori = ? "
        "WHERE id = ?", (riga[f"percorso_{motore}"], riga[f"impronta_{motore}"],
                         riga[f"motori_{motore}"], riga["miglioria_id"]))
    return [Path(riga[f"percorso_{l_altro(motore)}"] or "")]


def vota(connessione: sqlite3.Connection, miglioria_id: int, voto: str) -> list[Path]:
    if voto not in VOTI:
        raise VotoRifiutato("Il voto può essere A, B, Pari o Nessuna delle due.")
    riga = per_miglioria(connessione, miglioria_id)
    if riga is None or riga["voto"] is not None:
        raise VotoRifiutato("Questa foto non aspetta un voto.")
    migliorata = coda.per_id(connessione, miglioria_id)
    if migliorata is None or migliorata["stato"] != coda.DA_RIVEDERE:
        raise VotoRifiutato("Questa foto non aspetta un voto.")
    connessione.execute("UPDATE sfide SET voto = ?, votata_il = ? WHERE id = ?",
                        (voto, adesso(), riga["id"]))
    if voto in ("A", "B"):
        return _tieni(connessione, riga, chi_e(riga, voto))
    if voto == "nessuna":
        coda.segna(connessione, miglioria_id, coda.RIFIUTATA, in_revisione=None,
                   decisa_il=adesso())
        return [Path(riga[f"percorso_{m}"] or "") for m in SFIDANTI]
    return []


def conti(connessione: sqlite3.Connection) -> dict:
    fuori = {motore: 0 for motore in SFIDANTI}
    fuori.update(pari=0, nessuna=0, votate=0, da_votare=0, fatte=0)
    for riga in tutti(connessione, "SELECT a_e, voto FROM sfide"):
        fuori["fatte"] += 1
        if riga["voto"] is None:
            fuori["da_votare"] += 1
            continue
        fuori["votate"] += 1
        if riga["voto"] in ("A", "B"):
            fuori[chi_e(riga, riga["voto"])] += 1
        else:
            fuori[riga["voto"]] += 1
    fuori["quante"] = QUANTE
    return fuori


def vincitore(numeri: dict) -> str | None:
    uno_, due = SFIDANTI
    if numeri[uno_] == numeri[due]:
        return None
    return uno_ if numeri[uno_] > numeri[due] else due


def si_puo_chiudere(connessione: sqlite3.Connection, in_coda_foto: int) -> bool:
    if chiusa(connessione) is not None:
        return False
    numeri = conti(connessione)
    if not numeri["votate"] or numeri["da_votare"]:
        return False
    return numeri["fatte"] >= QUANTE or not in_coda_foto


def chiudi(connessione: sqlite3.Connection, principale: str) -> list[Path]:
    if principale not in SFIDANTI:
        raise VotoRifiutato("Si può scegliere solo SeedVR2 o LucidFlux.")
    if chiusa(connessione) is not None:
        raise VotoRifiutato("La sfida è già chiusa.")
    numeri = conti(connessione)
    if numeri["da_votare"]:
        raise VotoRifiutato("Ci sono ancora foto da votare.")
    via: list[Path] = []
    for riga in tutti(connessione,
                      "SELECT s.* FROM sfide AS s JOIN migliorie AS m "
                      "ON m.id = s.miglioria_id WHERE s.voto = 'pari' AND m.stato = ?",
                      coda.DA_RIVEDERE):
        via += _tieni(connessione, riga, principale)
    esito = {"principale": principale, "vincitore": vincitore(numeri),
             "conti": numeri, "chiusa_il": adesso()}
    scrivi_impostazione(connessione, CHIUSA, esito)
    scrivi_impostazione(connessione, "miglioria_foto", principale)
    return via


def butta(file: list[Path]) -> None:
    from officina.miglioria import attesa

    for uno_ in file:
        if str(uno_) not in ("", ".") and attesa.e_dentro(Path(uno_)):
            Path(uno_).unlink(missing_ok=True)
