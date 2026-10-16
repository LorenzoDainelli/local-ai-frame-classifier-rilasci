from __future__ import annotations

import os
import re
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from officina import registro
from officina.archivio.database import ora_a_parole
from officina.errori import DatabaseIncoerente
from officina.impostazioni import Posizione

QUANTE_SE_NE_TENGONO = 30
MOTIVO_AMMESSO = re.compile(r"^[a-z_]{1,24}$")
IN_ARRIVO = ".in-arrivo"
COMPAGNI = ("", "-wal", "-shm", "-journal")


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
        return ora_a_parole(self.istante)


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


def _togli_con_i_compagni(percorso: Path) -> None:
    for resto in COMPAGNI:
        Path(str(percorso) + resto).unlink(missing_ok=True)


def _copia_verificata(da: sqlite3.Connection, destinazione: Path) -> None:
    provvisoria = Path(str(destinazione) + IN_ARRIVO)
    try:
        dentro = sqlite3.connect(provvisoria)
        try:
            da.backup(dentro)
        finally:
            dentro.close()
        verifica(provvisoria)
        os.replace(provvisoria, destinazione)
    finally:
        _togli_con_i_compagni(provvisoria)


def pulisci_i_resti(posizione: Posizione) -> int:
    resti = list(posizione.copie.glob("*" + IN_ARRIVO + "*"))
    resti += [Path(str(posizione.database) + IN_ARRIVO + compagno) for compagno in COMPAGNI]
    tolti = 0
    for resto in resti:
        try:
            resto.unlink()
        except FileNotFoundError:
            continue
        except OSError:
            registro.errore("copie.resto_non_tolto")
            continue
        tolti += 1
    if tolti:
        registro.evento("copie.resti_tolti", quanti=tolti)
    return tolti


def fai_copia(connessione: sqlite3.Connection, posizione: Posizione,
              motivo: str = "chiusura") -> Copia:
    posizione.copie.mkdir(parents=True, exist_ok=True)
    destinazione = posizione.copie / _nome_copia(motivo, posizione.copie)
    _copia_verificata(connessione, destinazione)
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
    tenuta = prenotata(posizione)
    tolte = 0
    for vecchia in tutte[QUANTE_SE_NE_TENGONO:]:
        if vecchia.nome == tenuta:
            continue
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
        try:
            _copia_verificata(vecchia, rete)
        finally:
            vecchia.close()

    arrivo = Path(str(posizione.database) + IN_ARRIVO)
    try:
        shutil.copy2(sorgente, arrivo)
        verifica(arrivo)
        for compagno in ("-wal", "-shm"):
            Path(str(posizione.database) + compagno).unlink(missing_ok=True)
        os.replace(arrivo, posizione.database)
    finally:
        _togli_con_i_compagni(arrivo)
    verifica(posizione.database)

    registro.evento("copie.ripristinata")
    pezzi = sorgente.name.split(".")
    informazioni = sorgente.stat()
    return Copia(sorgente, pezzi[0], pezzi[1], informazioni.st_size, informazioni.st_mtime)


PRENOTAZIONE = "da_rimettere.txt"


def prenotata(posizione: Posizione) -> str | None:
    try:
        nome = (posizione.copie / PRENOTAZIONE).read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return None
    return nome or None


def prenota(posizione: Posizione, nome: str) -> Copia:
    scelta = next((copia for copia in elenco(posizione) if copia.nome == nome), None)
    if scelta is None:
        raise DatabaseIncoerente("Quella copia non c'è più: ricarica la pagina.")
    verifica(scelta.percorso)
    (posizione.copie / PRENOTAZIONE).write_text(scelta.nome, encoding="utf-8")
    registro.evento("copie.prenotata")
    return scelta


def disdici(posizione: Posizione) -> None:
    (posizione.copie / PRENOTAZIONE).unlink(missing_ok=True)


def rimetti_se_prenotata(posizione: Posizione) -> Copia | None:
    nome = prenotata(posizione)
    if nome is None:
        return None
    disdici(posizione)
    if nome not in {copia.nome for copia in elenco(posizione)}:
        registro.errore("copie.prenotata_sparita")
        return None
    return ripristina(posizione, nome)
