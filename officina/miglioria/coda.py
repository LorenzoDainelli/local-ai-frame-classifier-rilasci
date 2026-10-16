from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from officina.importazione import gruppi
from officina.archivio.database import adesso, inserisci, tutti, uno
from officina.miglioria import misura
from officina.modello import file_media

IN_CODA = "in_coda"
IN_LAVORO = "in_lavoro"
DA_RIVEDERE = "da_rivedere"
IN_SCAMBIO = "in_scambio"
APPROVATA = "approvata"
RIFIUTATA = "rifiutata"
FALLITA = "fallita"

ATTIVE = (IN_CODA, IN_LAVORO, DA_RIVEDERE, IN_SCAMBIO)

FORMATI_FOTO = {"heic", "heif", "jpg", "jpeg", "png", "tif", "tiff", "webp",
                "avif", "bmp"}
FORMATI_VIDEO = {"mov", "mp4", "m4v", "avi", "mkv", "3gp", "webm"}


@dataclass
class Esito:

    messi: int = 0
    gia_grandi: list[str] = field(default_factory=list)
    gia_in_coda: int = 0
    gia_migliorati: int = 0
    non_adatti: list[str] = field(default_factory=list)
    assenti: list[str] = field(default_factory=list)

    def a_parole(self) -> str:
        pezzi = []
        if self.messi:
            pezzi.append(f"{self.messi} in coda")
        if self.gia_grandi:
            pezzi.append(f"{len(self.gia_grandi)} scartati: sono già FHD o più")
        if self.gia_in_coda:
            pezzi.append(f"{self.gia_in_coda} c'erano già")
        if self.gia_migliorati:
            pezzi.append(f"{self.gia_migliorati} già migliorati")
        if self.non_adatti:
            pezzi.append(f"{len(self.non_adatti)} in un formato che non si migliora")
        if self.assenti:
            pezzi.append(f"{len(self.assenti)} non sono sul disco")
        return " · ".join(pezzi) if pezzi else "niente da mettere in coda"


def _formato(riga: sqlite3.Row, percorso: Path) -> str:
    return str(riga["formato"] or percorso.suffix.lstrip(".")).casefold()


def si_migliora(riga: sqlite3.Row, percorso: Path) -> bool:
    formato = _formato(riga, percorso)
    if riga["genere"] == "immagine":
        return formato in FORMATI_FOTO
    return formato in FORMATI_VIDEO


def file_da_guardare(connessione: sqlite3.Connection,
                     scatto_id: int) -> list[sqlite3.Row]:
    return [riga for riga in file_media.di_scatto(connessione, scatto_id)
            if riga["ruolo"] in ("principale", "movimento")]


def metti(connessione: sqlite3.Connection, scatti: list[int]) -> Esito:
    esito = Esito()
    for scatto_id in dict.fromkeys(int(s) for s in scatti):
        for riga in file_da_guardare(connessione, scatto_id):
            _metti_uno(connessione, riga, esito)
    return esito


def _metti_uno(connessione: sqlite3.Connection, riga: sqlite3.Row,
               esito: Esito) -> None:
    gia = uno(connessione,
              "SELECT stato FROM migliorie WHERE file_id = ? AND stato IN "
              "('in_coda','in_lavoro','da_rivedere','in_scambio','approvata')",
              riga["id"])
    if gia is not None:
        if gia["stato"] == APPROVATA:
            esito.gia_migliorati += 1
        else:
            esito.gia_in_coda += 1
        return

    percorso = file_media.percorso_migliore(connessione, riga["id"])
    nome = percorso.name if percorso else _un_nome(connessione, riga["id"])
    if percorso is None:
        esito.assenti.append(nome)
        return
    if not si_migliora(riga, percorso):
        esito.non_adatti.append(nome)
        return
    larghezza, altezza = riga["larghezza"], riga["altezza"]
    if larghezza and altezza and misura.e_gia_grande(larghezza, altezza):
        esito.gia_grandi.append(nome)
        return

    inserisci(
        connessione,
        "INSERT INTO migliorie (file_id, scatto_id, stato, impronta_originale, "
        "percorso_originale, larghezza_prima, altezza_prima, messa_il) "
        "VALUES (?,?,?,?,?,?,?,?)",
        riga["id"], riga["scatto_id"], IN_CODA, riga["impronta"],
        str(percorso), larghezza, altezza, adesso())
    esito.messi += 1


def _un_nome(connessione: sqlite3.Connection, file_id: int) -> str:
    riga = uno(connessione,
               "SELECT nome FROM percorsi WHERE file_id = ? ORDER BY id LIMIT 1",
               file_id)
    return riga["nome"] if riga else f"file {file_id}"


def per_id(connessione: sqlite3.Connection, miglioria_id: int) -> sqlite3.Row | None:
    return uno(connessione, "SELECT * FROM migliorie WHERE id = ?", miglioria_id)


def prossima(connessione: sqlite3.Connection) -> sqlite3.Row | None:
    return uno(connessione,
               "SELECT m.* FROM migliorie m JOIN file_media f ON f.id = m.file_id "
               "JOIN scatti s ON s.id = f.scatto_id WHERE m.stato = ?"
               + gruppi.clausola(connessione, "miglioramento")
               + " ORDER BY m.id LIMIT 1",
               IN_CODA)


def in_stato(connessione: sqlite3.Connection, stato: str) -> list[sqlite3.Row]:
    return tutti(connessione,
                 "SELECT * FROM migliorie WHERE stato = ? ORDER BY id", stato)


def conteggi(connessione: sqlite3.Connection) -> dict[str, int]:
    fuori = {stato: 0 for stato in (IN_CODA, IN_LAVORO, DA_RIVEDERE, IN_SCAMBIO,
                                    APPROVATA, RIFIUTATA, FALLITA)}
    for riga in tutti(connessione,
                      "SELECT stato, count(*) AS q FROM migliorie GROUP BY stato"):
        fuori[riga["stato"]] = riga["q"]
    return fuori


AGGIORNA = {
    "fedelta": "UPDATE migliorie SET fedelta = ? WHERE id = ?",
    "in_revisione": "UPDATE migliorie SET in_revisione = ? WHERE id = ?",
    "impronta_migliorata":
        "UPDATE migliorie SET impronta_migliorata = ? WHERE id = ?",
    "percorso_migliorata":
        "UPDATE migliorie SET percorso_migliorata = ? WHERE id = ?",
    "percorso_spostato": "UPDATE migliorie SET percorso_spostato = ? WHERE id = ?",
    "motori": "UPDATE migliorie SET motori = ? WHERE id = ?",
    "guasto": "UPDATE migliorie SET guasto = ? WHERE id = ?",
    "larghezza_dopo": "UPDATE migliorie SET larghezza_dopo = ? WHERE id = ?",
    "altezza_dopo": "UPDATE migliorie SET altezza_dopo = ? WHERE id = ?",
    "larghezza_prima": "UPDATE migliorie SET larghezza_prima = ? WHERE id = ?",
    "altezza_prima": "UPDATE migliorie SET altezza_prima = ? WHERE id = ?",
    "finita_il": "UPDATE migliorie SET finita_il = ? WHERE id = ?",
    "decisa_il": "UPDATE migliorie SET decisa_il = ? WHERE id = ?",
}


def segna(connessione: sqlite3.Connection, miglioria_id: int, stato: str,
          **campi) -> None:
    sconosciuti = set(campi) - set(AGGIORNA)
    if sconosciuti:
        raise ValueError(f"campi sconosciuti: {sorted(sconosciuti)}")
    connessione.execute("UPDATE migliorie SET stato = ? WHERE id = ?",
                        (stato, miglioria_id))
    for nome, valore in campi.items():
        connessione.execute(AGGIORNA[nome], (valore, miglioria_id))


def togli(connessione: sqlite3.Connection, miglioria_id: int) -> bool:
    return connessione.execute(
        "DELETE FROM migliorie WHERE id = ? AND stato = ?",
        (miglioria_id, IN_CODA)).rowcount > 0


def riprendi_interrotte(connessione: sqlite3.Connection) -> list[sqlite3.Row]:
    interrotte = in_stato(connessione, IN_LAVORO)
    connessione.execute(
        "UPDATE migliorie SET stato = ?, in_revisione = NULL, guasto = NULL "
        "WHERE stato = ?", (IN_CODA, IN_LAVORO))
    return interrotte


def di_impronta_migliorata(connessione: sqlite3.Connection,
                           impronta: str) -> sqlite3.Row | None:
    return uno(connessione,
               "SELECT * FROM migliorie WHERE impronta_migliorata = ? "
               "AND stato IN ('da_rivedere','in_scambio','approvata') ORDER BY id DESC LIMIT 1",
               impronta)
