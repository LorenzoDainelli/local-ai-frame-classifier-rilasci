from __future__ import annotations

import re
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from officina import registro
from officina.errori import DatabaseIncoerente
from officina.impostazioni import Posizione

QUANTE_SE_NE_TENGONO = 30
MOTIVO_AMMESSO = re.compile(r"^[a-z_]{1,24}$")


@dataclass(frozen=True)
class Copia:
    percorso: Path
    istante: str
    motivo: str
    byte: int
    nato_il: float = 0.0

    @property
    def nome(self) -> str:
        return self.percorso.name

    @property
    def quando(self) -> str:
        try:
            momento = datetime.strptime(self.istante, "%Y%m%d-%H%M%S")
        except ValueError:
            return self.istante
        mesi = ("gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno",
                "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre")
        return (f"{momento.day} {mesi[momento.month - 1]} {momento.year}, "
                f"{momento.hour:02d}:{momento.minute:02d}")


def _nome_copia(motivo: str, dentro: Path | None = None) -> str:
    if not MOTIVO_AMMESSO.match(motivo):
        motivo = "manuale"
    istante = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    nome = f"{istante}.{motivo}.sqlite"
    if dentro is None:
        return nome
    contatore = 1
    while (dentro / nome).exists():
        nome = f"{istante}-{contatore}.{motivo}.sqlite"
        contatore += 1
    return nome


def verifica(percorso: Path) -> None:
    if not percorso.exists() or percorso.stat().st_size == 0:
        raise DatabaseIncoerente(f"La copia {percorso.name} è vuota o non esiste.")
    prova = sqlite3.connect(percorso)
    try:
        esito = prova.execute("PRAGMA integrity_check").fetchone()
        if not esito or esito[0] != "ok":
            raise DatabaseIncoerente(
                f"La copia {percorso.name} non è integra: il programma non la "
                "considera un backup valido."
            )
        tabelle = prova.execute(
            "SELECT count(*) FROM sqlite_master WHERE type = 'table'"
        ).fetchone()[0]
        if tabelle == 0:
            raise DatabaseIncoerente(f"La copia {percorso.name} non contiene tabelle.")
    except sqlite3.DatabaseError as errore:
        raise DatabaseIncoerente(
            f"La copia {percorso.name} non si riesce nemmeno ad aprire: "
            "non è un backup su cui contare."
        ) from errore
    finally:
        prova.close()


def fai_copia(connessione: sqlite3.Connection, posizione: Posizione,
              motivo: str = "chiusura") -> Copia:
    posizione.copie.mkdir(parents=True, exist_ok=True)
    destinazione = posizione.copie / _nome_copia(motivo, posizione.copie)

    copia_connessione = sqlite3.connect(destinazione)
    try:
        connessione.backup(copia_connessione)
    finally:
        copia_connessione.close()

    verifica(destinazione)
    peso = destinazione.stat().st_size
    nato_il = destinazione.stat().st_mtime
    registro.evento("copie.fatta", byte=peso)
    pota(posizione)

    istante, motivo_letto, _ = destinazione.name.split(".", 2)
    return Copia(destinazione, istante, motivo_letto, peso, nato_il)


def elenco(posizione: Posizione) -> list[Copia]:
    trovate = []
    for percorso in posizione.copie.glob("*.sqlite"):
        pezzi = percorso.name.split(".")
        if len(pezzi) < 3:
            continue
        try:
            informazioni = percorso.stat()
        except OSError:
            continue
        trovate.append(Copia(percorso, pezzi[0], pezzi[1],
                             informazioni.st_size, informazioni.st_mtime))
    return sorted(trovate, key=lambda c: (c.nato_il, c.istante), reverse=True)


def pota(posizione: Posizione) -> int:
    tutte = elenco(posizione)
    tolte = 0
    for vecchia in tutte[QUANTE_SE_NE_TENGONO:]:
        vecchia.percorso.unlink(missing_ok=True)
        tolte += 1
    if tolte:
        registro.evento("copie.potate", quante=tolte)
    return tolte


def ripristina(posizione: Posizione, nome: str) -> Copia:
    sorgente = posizione.copie / nome
    verifica(sorgente)

    if posizione.database.exists():
        rete = posizione.copie / _nome_copia("prima_del_ripristino", posizione.copie)
        vecchia = sqlite3.connect(posizione.database)
        nuova = sqlite3.connect(rete)
        try:
            vecchia.backup(nuova)
        finally:
            nuova.close()
            vecchia.close()
        verifica(rete)

    for compagno in ("-wal", "-shm"):
        Path(str(posizione.database) + compagno).unlink(missing_ok=True)
    shutil.copy2(sorgente, posizione.database)
    verifica(posizione.database)

    registro.evento("copie.ripristinata")
    pezzi = sorgente.name.split(".")
    informazioni = sorgente.stat()
    return Copia(sorgente, pezzi[0], pezzi[1], informazioni.st_size, informazioni.st_mtime)
