from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from officina import registro
from officina.archivio.database import adesso, esegui, tutti, uno
from officina.errori import ErroreOfficina
from officina.telefono import cifratura, formato, selezione

SCHEMA = """
CREATE TABLE informazioni (
    chiave  TEXT PRIMARY KEY,
    valore  TEXT NOT NULL
);

-- I cuori. Si identificano per impronta, mai per numero (regola 380).
CREATE TABLE cuori (
    impronta TEXT PRIMARY KEY,
    messo_il TEXT
);

-- Le raccolte: elenchi di foto scelte a mano, niente automatismi.
CREATE TABLE raccolte (
    id        INTEGER PRIMARY KEY,
    nome      TEXT NOT NULL,
    creata_il TEXT
);

CREATE TABLE raccolte_scatti (
    raccolta_id INTEGER NOT NULL,
    impronta    TEXT NOT NULL,
    PRIMARY KEY (raccolta_id, impronta)
);

-- Il diario dell'uso (regola 381): dove, quando, per quanto, su quante foto.
CREATE TABLE diario (
    aperto_il   TEXT PRIMARY KEY,
    durata_s    INTEGER,
    latitudine  REAL,
    longitudine REAL,
    quante_foto INTEGER
);
"""


@dataclass
class Tornato:
    c_era: bool = False
    cuori_nuovi: int = 0
    cuori_gia_visti: int = 0
    cuori_tolti_applicati: int = 0
    raccolte: int = 0
    foto_nelle_raccolte: int = 0
    giornate_di_diario: int = 0
    non_trovati: int = 0
    guai: list = field(default_factory=list)

    @property
    def qualcosa(self) -> bool:
        return bool(self.cuori_nuovi or self.raccolte or self.giornate_di_diario)

    def a_parole(self) -> str:
        if not self.c_era:
            return "il telefono non ha ancora raccontato niente"
        pezzi = []
        if self.cuori_nuovi:
            pezzi.append(selezione.conta(self.cuori_nuovi, "cuore nuovo", "cuori nuovi"))
        if self.raccolte:
            pezzi.append(selezione.conta(self.raccolte, "raccolta", "raccolte")
                         + f" ({self.foto_nelle_raccolte} foto)")
        if self.giornate_di_diario:
            pezzi.append(selezione.conta(self.giornate_di_diario, "riga di diario",
                                "righe di diario"))
        if self.non_trovati:
            pezzi.append(f"{self.non_trovati} su foto che l'archivio non ha più")
        return ", ".join(pezzi) if pezzi else "niente di nuovo"


@dataclass
class Arrivato:
    esito: Tornato
    dentro: sqlite3.Connection | None = None


def apri(cartella: Path, chiave: cifratura.Chiave) -> Arrivato:
    arrivato = Arrivato(Tornato())
    dove = formato.dentro(cartella, formato.RITORNO)
    if not dove.is_file():
        return arrivato
    arrivato.esito.c_era = True

    try:
        grezzo = chiave.leggi_tutto(dove, formato.RITORNO)
    except cifratura.PacchettoRovinato as guaio:
        registro.errore("visore.ritorno_illeggibile")
        arrivato.esito.guai.append(guaio.messaggio)
        return arrivato
    dentro = sqlite3.connect(":memory:")
    dentro.row_factory = sqlite3.Row
    try:
        dentro.deserialize(grezzo)
    except sqlite3.DatabaseError:
        dentro.close()
        _non_e_un_database(arrivato.esito)
        return arrivato
    arrivato.dentro = dentro
    return arrivato


def leggi(connessione: sqlite3.Connection, telefono_id: int,
          arrivato: Arrivato) -> Tornato:
    esito = arrivato.esito
    if not esito.c_era:
        return esito
    if arrivato.dentro is not None:
        try:
            esito = _tutto_o_niente(connessione, telefono_id, arrivato.dentro)
        except sqlite3.DatabaseError:
            _non_e_un_database(esito)
        finally:
            arrivato.dentro.close()
            arrivato.dentro = None

    registro.evento("visore.ritorno_letto", cuori=esito.cuori_nuovi,
                    raccolte=esito.raccolte, diario=esito.giornate_di_diario)
    return esito


def _non_e_un_database(esito: Tornato) -> None:
    registro.errore("visore.ritorno_non_e_un_database")
    esito.guai.append(
        "Il file che il telefono ha scritto non è leggibile. I preferiti "
        "e le raccolte di questo giro sono persi; le foto no.")


def _tutto_o_niente(connessione, telefono_id: int, dentro) -> Tornato:
    esito = Tornato(c_era=True)
    connessione.execute("SAVEPOINT ritorno_dal_telefono")
    try:
        _cuori(connessione, telefono_id, dentro, esito)
        _raccolte(connessione, telefono_id, dentro, esito)
        _diario(connessione, telefono_id, dentro, esito)
    except Exception:
        connessione.execute("ROLLBACK TO ritorno_dal_telefono")
        connessione.execute("RELEASE ritorno_dal_telefono")
        raise
    connessione.execute("RELEASE ritorno_dal_telefono")
    return esito


def _tabelle(dentro: sqlite3.Connection) -> set[str]:
    return {r["name"] for r in dentro.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'")}


def _scatto_di(connessione: sqlite3.Connection, impronta: str) -> int | None:
    riga = uno(connessione,
               "SELECT scatto_id FROM file_media WHERE impronta = ?", impronta)
    return riga["scatto_id"] if riga else None


def _cuori(connessione, telefono_id: int, dentro, esito: Tornato) -> None:
    if "cuori" not in _tabelle(dentro):
        return
    arrivate = {r["impronta"]: r["messo_il"]
                for r in dentro.execute("SELECT impronta, messo_il FROM cuori")}

    gia = {r["impronta"]: r for r in tutti(
        connessione, "SELECT * FROM cuori WHERE telefono_id = ?", telefono_id)}

    for impronta, messo_il in arrivate.items():
        vecchio = gia.get(impronta)
        if vecchio and vecchio["tolto_il"]:
            continue
        if vecchio:
            esito.cuori_gia_visti += 1
            continue
        scatto_id = _scatto_di(connessione, impronta)
        if scatto_id is None:
            esito.non_trovati += 1
        esegui(connessione,
               "INSERT INTO cuori (telefono_id, impronta, scatto_id, messo_il, "
               "tornato_il) VALUES (?, ?, ?, ?, ?) "
               "ON CONFLICT(telefono_id, impronta) DO NOTHING",
               telefono_id, impronta, scatto_id, messo_il, adesso())
        esito.cuori_nuovi += 1

    for impronta, riga in gia.items():
        if riga["tolto_il"] and impronta not in arrivate:
            esegui(connessione, "DELETE FROM cuori WHERE id = ?", riga["id"])
            esito.cuori_tolti_applicati += 1


def _raccolte(connessione, telefono_id: int, dentro, esito: Tornato) -> None:
    tabelle = _tabelle(dentro)
    if "raccolte" not in tabelle:
        return
    for riga in dentro.execute(
            "SELECT id, nome, creata_il FROM raccolte ORDER BY id"):
        raccolta_id = _raccolta(connessione, telefono_id, riga)
        esito.raccolte += 1
        if "raccolte_scatti" not in tabelle:
            continue
        esegui(connessione,
               "DELETE FROM raccolte_scatti WHERE raccolta_id = ?", raccolta_id)
        for dentro_riga in dentro.execute(
                "SELECT impronta FROM raccolte_scatti WHERE raccolta_id = ?",
                (riga["id"],)):
            impronta = dentro_riga["impronta"]
            scatto_id = _scatto_di(connessione, impronta)
            if scatto_id is None:
                esito.non_trovati += 1
            esegui(connessione,
                   "INSERT OR REPLACE INTO raccolte_scatti (raccolta_id, "
                   "impronta, scatto_id) VALUES (?, ?, ?)",
                   raccolta_id, impronta, scatto_id)
            esito.foto_nelle_raccolte += 1


def _raccolta(connessione, telefono_id: int, riga) -> int:
    gia = uno(connessione,
              "SELECT id FROM raccolte WHERE telefono_id = ? AND numero = ?",
              telefono_id, riga["id"])
    if gia:
        esegui(connessione, "UPDATE raccolte SET nome = ?, tornata_il = ? "
                            "WHERE id = ?", riga["nome"], adesso(), gia["id"])
        return gia["id"]
    return connessione.execute(
        "INSERT INTO raccolte (telefono_id, numero, nome, creata_il, "
        "tornata_il) VALUES (?, ?, ?, ?, ?)",
        (telefono_id, riga["id"], riga["nome"], riga["creata_il"],
         adesso())).lastrowid


def _diario(connessione, telefono_id: int, dentro, esito: Tornato) -> None:
    if "diario" not in _tabelle(dentro):
        return
    for riga in dentro.execute(
            "SELECT aperto_il, durata_s, latitudine, longitudine, quante_foto "
            "FROM diario ORDER BY aperto_il"):
        esegui(connessione,
               "INSERT INTO diario_visore (telefono_id, aperto_il, durata_s, "
               "latitudine, longitudine, quante_foto, tornato_il) "
               "VALUES (?, ?, ?, ?, ?, ?, ?) "
               "ON CONFLICT(telefono_id, aperto_il) DO NOTHING",
               telefono_id, riga["aperto_il"], riga["durata_s"],
               riga["latitudine"], riga["longitudine"], riga["quante_foto"],
               adesso())
        esito.giornate_di_diario += 1


def copia_di_scorta(connessione: sqlite3.Connection,
                    telefono_id: int) -> dict:
    cuori = tutti(connessione,
                  "SELECT impronta, messo_il FROM cuori WHERE telefono_id = ? "
                  "AND tolto_il IS NULL", telefono_id)
    tolti = tutti(connessione,
                  "SELECT impronta, tolto_il FROM cuori WHERE telefono_id = ? "
                  "AND tolto_il IS NOT NULL", telefono_id)
    raccolte = tutti(connessione,
                     "SELECT id, numero, nome, creata_il FROM raccolte "
                     "WHERE telefono_id = ? ORDER BY numero", telefono_id)
    dentro = {}
    for riga in raccolte:
        dentro[riga["numero"]] = [
            r["impronta"] for r in tutti(
                connessione,
                "SELECT impronta FROM raccolte_scatti WHERE raccolta_id = ?",
                riga["id"])]
    return {
        "cuori": [(r["impronta"], r["messo_il"]) for r in cuori],
        "tolti": [(r["impronta"], r["tolto_il"]) for r in tolti],
        "raccolte": [(r["numero"], r["nome"], r["creata_il"]) for r in raccolte],
        "raccolte_scatti": dentro,
    }


def togli_cuore(connessione: sqlite3.Connection, telefono_id: int,
                impronta: str) -> None:
    gia = uno(connessione,
              "SELECT id FROM cuori WHERE telefono_id = ? AND impronta = ?",
              telefono_id, impronta)
    if not gia:
        raise ErroreOfficina(
            "Questo cuore non c'è: l'ha messo un altro telefono, oppure non "
            "è mai tornato indietro.")
    esegui(connessione, "UPDATE cuori SET tolto_il = ? WHERE id = ?",
           adesso(), gia["id"])


def scrivi_ritorno_finto(percorso: Path, cuori=(), raccolte=(),
                         raccolte_scatti=None, diario=()) -> None:
    percorso.parent.mkdir(parents=True, exist_ok=True)
    percorso.unlink(missing_ok=True)
    dentro = sqlite3.connect(percorso)
    try:
        dentro.executescript(SCHEMA)
        dentro.executemany("INSERT INTO cuori (impronta, messo_il) VALUES (?,?)",
                           list(cuori))
        dentro.executemany(
            "INSERT INTO raccolte (id, nome, creata_il) VALUES (?,?,?)",
            list(raccolte))
        for numero, impronte in (raccolte_scatti or {}).items():
            dentro.executemany(
                "INSERT INTO raccolte_scatti (raccolta_id, impronta) "
                "VALUES (?,?)", [(numero, x) for x in impronte])
        dentro.executemany(
            "INSERT INTO diario (aperto_il, durata_s, latitudine, longitudine, "
            "quante_foto) VALUES (?,?,?,?,?)", list(diario))
        dentro.commit()
    finally:
        dentro.close()
