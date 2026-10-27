from __future__ import annotations

import contextlib
import json
import secrets
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from officina import VERSIONE
from officina.archivio.database import adesso, tutti, uno
from officina.impostazioni import VIAGGIANO
from officina.errori import ErroreOfficina
from officina.modello import cambiamenti, nodi
from officina.sincronia import formato
from officina.telefono import cifratura

APPOGGIO = "sincronia-in-costruzione-"
A_PEZZI = 2000

SCHEMA_VIAGGIANTE = """
CREATE TABLE cambiamenti (
    seriale     INTEGER PRIMARY KEY,
    avvenuto_il TEXT NOT NULL,
    cosa        TEXT NOT NULL,
    azione      TEXT NOT NULL,
    impronta    TEXT,          -- lo scatto, quando ce n'è uno
    sentiero    TEXT,          -- il nodo, per nome dalla radice
    stato       TEXT,
    origine     TEXT,
    valore      TEXT,
    valore_prima TEXT       -- il percorso da cui il nodo partiva (regola 406)
);

CREATE TABLE nodi (
    sentiero     TEXT PRIMARY KEY,
    criterio     TEXT,
    soglia       REAL,
    scegline_uno INTEGER,
    stato        TEXT,
    creato_il    TEXT
);

CREATE TABLE scatti (
    capo             TEXT PRIMARY KEY,   -- l'impronta del file principale
    genere           TEXT,
    data_locale      TEXT,
    fuso_minuti      INTEGER,
    istante_utc      TEXT,
    giorno           TEXT,
    origine_data     TEXT,
    latitudine       REAL,
    longitudine      REAL,
    larghezza        INTEGER,
    altezza          INTEGER,
    durata_ms        INTEGER,
    sembra_schermata INTEGER,
    nota             TEXT
);

CREATE TABLE file (
    impronta           TEXT PRIMARY KEY,
    capo               TEXT,             -- a quale scatto appartiene
    ruolo              TEXT,
    genere             TEXT,
    formato            TEXT,
    dimensione         INTEGER,
    larghezza          INTEGER,
    altezza            INTEGER,
    orientamento       INTEGER,
    durata_ms          INTEGER,
    identificatore_ios TEXT,
    data_locale        TEXT,
    fuso_minuti        INTEGER,
    istante_utc        TEXT,
    origine_data       TEXT,
    latitudine         REAL,
    longitudine        REAL,
    sembra_schermata   INTEGER,
    nome               TEXT,             -- il nome vero dell'originale
    posto              TEXT,             -- dov'è dentro il pacchetto
    mini_posto         TEXT,             -- la miniatura, se c'era
    mini_formato       TEXT
);

CREATE TABLE impronte (
    capo         TEXT NOT NULL,
    descrittore  TEXT NOT NULL,
    versione     TEXT NOT NULL,
    inquadratura TEXT NOT NULL,
    metodo       TEXT NOT NULL,
    riquadro     TEXT,
    fotogramma   INTEGER NOT NULL DEFAULT 0,
    istante_ms   INTEGER,
    dimensione   INTEGER NOT NULL,
    valori       BLOB NOT NULL,
    calcolata_il TEXT NOT NULL
);

CREATE TABLE persone (
    nome    TEXT PRIMARY KEY,      -- solo quelle a cui hai dato un nome tu
    stato   TEXT,
    nata_il TEXT
);

CREATE TABLE persone_scatti (
    nome     TEXT NOT NULL,
    impronta TEXT NOT NULL,        -- lo scatto in cui c'è
    a_mano   INTEGER NOT NULL DEFAULT 0,   -- 1: l'hai detto tu (regola 294)
    PRIMARY KEY (nome, impronta)
);

CREATE TABLE cuori (
    telefono TEXT NOT NULL,        -- il nome del telefono (regola 409)
    sistema  TEXT,
    impronta TEXT NOT NULL,
    messo_il TEXT,
    tolto_il TEXT,
    PRIMARY KEY (telefono, impronta)
);

CREATE TABLE inventario (
    impronta TEXT PRIMARY KEY
) WITHOUT ROWID;

CREATE TABLE impostazioni (
    chiave      TEXT PRIMARY KEY,
    valore      TEXT NOT NULL,      -- JSON, come nell'archivio
    cambiata_il TEXT                -- vuota se non l'ha mai decisa nessuno
);

CREATE TABLE informazioni (
    chiave TEXT PRIMARY KEY,
    valore TEXT NOT NULL
);
"""


@dataclass
class Fatto:
    cartella: Path
    carta: formato.Carta
    note: list = field(default_factory=list)


def _sentieri(connessione: sqlite3.Connection) -> dict[int, str]:
    return {r["id"]: nodi.percorso(connessione, r["id"])
            for r in tutti(connessione, "SELECT id FROM nodi")}


def _capi(connessione: sqlite3.Connection) -> dict[int, str]:
    capi: dict[int, str] = {}
    for riga in tutti(connessione,
                      "SELECT scatto_id, impronta, ruolo FROM file_media "
                      "WHERE scatto_id IS NOT NULL ORDER BY id"):
        se_c_e = capi.get(riga["scatto_id"])
        if se_c_e is None or riga["ruolo"] == "principale":
            capi[riga["scatto_id"]] = riga["impronta"]
    return capi


def _percorsi(connessione: sqlite3.Connection, da: int,
              fino: int) -> dict[int, list[tuple[str, str]]]:
    trovati: dict[int, list[tuple[str, str]]] = {}
    for riga in connessione.execute(
            "SELECT file_id, percorso, nome FROM percorsi "
            "WHERE file_id BETWEEN ? AND ? ORDER BY file_id, presente DESC, id",
            (da, fino)):
        trovati.setdefault(riga["file_id"], []).append((riga["percorso"], riga["nome"]))
    return trovati


def _percorso_sul_disco(percorsi: list[tuple[str, str]]) -> tuple[Path | None, str]:
    nome = ""
    for percorso, suo_nome in percorsi:
        nome = nome or suo_nome
        dove = Path(percorso)
        if dove.is_file():
            return dove, suo_nome
    return None, nome


def _senza_originale(archivio, file_id: int, impronta: str) -> str:
    from officina.modello import file_media
    from officina.sicuro import dall_archivio

    try:
        with archivio.lettura() as connessione:
            perche = file_media.cerca_nell_archivio(connessione, file_id).perche
    except ErroreOfficina:
        perche = dall_archivio.CHIUSO
    if perche == dall_archivio.TROVATA:
        return f"originale solo nell'Archivio sicuro: {impronta[:12]}"
    if perche in (dall_archivio.CHIUSO, dall_archivio.SI_APRE):
        return f"originale non sul disco, e l'Archivio sicuro era chiuso: {impronta[:12]}"
    return f"originale non trovato sul disco: {impronta[:12]}"


def _appoggio(archivio) -> Path:
    lavoro = Path(archivio.dove.radice) / "lavoro"
    lavoro.mkdir(parents=True, exist_ok=True)
    for vecchio in lavoro.glob(f"{APPOGGIO}*.sqlite*"):
        with contextlib.suppress(OSError):
            vecchio.unlink(missing_ok=True)
    return lavoro / f"{APPOGGIO}{secrets.token_hex(8)}.sqlite"


def costruisci(archivio, dove: Path, password: str,
               per_macchina_id: int | None = None,
               avanzamento: Callable[[int, int], None] | None = None) -> Fatto:
    with archivio.scrittura() as connessione:
        cambiamenti.questa_macchina(connessione)
        cambiamenti.recupera_larretrato(connessione)

    with archivio.lettura() as connessione:
        mia = cambiamenti.questa_macchina(connessione)
        destinataria = None
        if per_macchina_id is not None:
            destinataria = uno(connessione, "SELECT * FROM macchine WHERE id = ?",
                               per_macchina_id)
            if destinataria is None:
                raise ErroreOfficina("Questa macchina non la conosco.",
                                     codice="macchina_sconosciuta")
        dal_seriale = destinataria["mi_ha_vista_fino_a"] if destinataria else 0
        visto_di_te = destinataria["visto_fino_a"] if destinataria else 0
        righe = cambiamenti.da_mandare(connessione, dal_seriale)
    al_seriale = righe[-1]["seriale"] if righe else dal_seriale

    cartella = Path(dove) / formato.nome_cartella(mia["nome"], al_seriale)
    cartella.mkdir(parents=True, exist_ok=True)

    sale = cifratura.sale_nuovo()
    chiave = cifratura.Chiave.dalla_password(password, sale, formato.COSTO)
    carta = formato.Carta(
        mittente_codice=mia["codice"],
        mittente_nome=mia["nome"],
        archivio=archivio.dove.nome,
        sale=sale.hex(),
        prova=chiave.prova(),
        versione_officina=VERSIONE,
        fatto_il=adesso(),
        dal_seriale=dal_seriale,
        al_seriale=al_seriale,
        visto_di_te=visto_di_te,
        quanti_cambiamenti=len(righe),
    )
    carta.scrivi(cartella)

    appoggio = _appoggio(archivio)
    try:
        note, quanti, quante_mini, peso = _riempi(
            archivio, appoggio, cartella, chiave, carta, righe, destinataria,
            avanzamento)
        peso += chiave.cifra_file(appoggio, cartella / formato.DATI, formato.DATI).peso
    finally:
        appoggio.unlink(missing_ok=True)

    carta.stato = formato.COMPLETO
    carta.finito_il = adesso()
    carta.quanti_file = quanti
    carta.quante_miniature = quante_mini
    carta.peso = peso
    carta.note = [f"{len(note)} avvisi: si leggono quando il pacchetto viene aperto"] if note else []
    carta.scrivi(cartella)
    return Fatto(cartella=cartella, carta=carta, note=note)


def _riempi(archivio, appoggio: Path, cartella: Path, chiave: cifratura.Chiave,
            carta: formato.Carta, righe: list, destinataria,
            avanzamento: Callable[[int, int], None] | None) -> tuple[list[str], int, int, int]:
    viaggiante = sqlite3.connect(appoggio)
    try:
        viaggiante.execute("PRAGMA journal_mode = OFF")
        viaggiante.execute("PRAGMA synchronous = OFF")
        viaggiante.executescript(SCHEMA_VIAGGIANTE)
        with archivio.lettura() as connessione:
            capi = _capi(connessione)
            gia_di_la = _quello_che_ha_gia(connessione, destinataria)
            _metti_quello_che_si_sa(viaggiante, connessione, righe, capi)
            fino = uno(connessione, "SELECT count(*) AS q, coalesce(max(id), 0) AS ultimo "
                            "FROM file_media")
        note, quanti, quante_mini, peso = _metti_i_file(
            archivio, viaggiante, cartella, chiave, capi, gia_di_la,
            fino["q"], fino["ultimo"], avanzamento)

        garantiti = {nome: getattr(carta, nome) for nome in formato.GARANTITI}
        garantiti["note"] = note
        viaggiante.executemany(
            "INSERT INTO informazioni (chiave, valore) VALUES (?, ?)",
            [(nome, json.dumps(valore, ensure_ascii=False))
             for nome, valore in garantiti.items()])
        viaggiante.commit()
    finally:
        viaggiante.close()
    return note, quanti, quante_mini, peso


def _quello_che_ha_gia(connessione: sqlite3.Connection, destinataria) -> set[str]:
    if destinataria is None:
        return set()
    return {r["impronta"] for r in connessione.execute(
        "SELECT impronta FROM inventario_altrui WHERE macchina_id = ?",
        (destinataria["id"],))}


def _metti_quello_che_si_sa(viaggiante: sqlite3.Connection,
                            connessione: sqlite3.Connection, righe: list,
                            capi: dict[int, str]) -> None:
    sentieri = _sentieri(connessione)

    viaggiante.executemany(
        "INSERT INTO cambiamenti (seriale, avvenuto_il, cosa, azione, "
        "impronta, sentiero, stato, origine, valore, valore_prima) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ((riga["seriale"], riga["avvenuto_il"], riga["cosa"], riga["azione"],
          capi.get(riga["scatto_id"]), sentieri.get(riga["nodo_id"]),
          riga["stato"], riga["origine"], riga["valore"], riga["valore_prima"])
         for riga in righe))

    viaggiante.executemany(
        "INSERT INTO nodi (sentiero, criterio, soglia, scegline_uno, "
        "stato, creato_il) VALUES (?, ?, ?, ?, ?, ?)",
        ((sentieri[riga["id"]], riga["criterio"], riga["soglia"],
          riga["scegline_uno"], riga["stato"], riga["creato_il"])
         for riga in connessione.execute("SELECT * FROM nodi")))

    viaggiante.executemany(
        "INSERT INTO impostazioni (chiave, valore, cambiata_il) VALUES (?, ?, ?)",
        ((riga["chiave"], riga["valore"], riga["cambiata_il"])
         for riga in connessione.execute("SELECT * FROM impostazioni")
         if riga["chiave"] in VIAGGIANO))

    viaggiante.executemany(
        "INSERT INTO scatti (capo, genere, data_locale, fuso_minuti, "
        "istante_utc, giorno, origine_data, latitudine, longitudine, "
        "larghezza, altezza, durata_ms, sembra_schermata, nota) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ((capi[riga["id"]], riga["genere"], riga["data_locale"], riga["fuso_minuti"],
          riga["istante_utc"], riga["giorno"], riga["origine_data"],
          riga["latitudine"], riga["longitudine"], riga["larghezza"],
          riga["altezza"], riga["durata_ms"], riga["sembra_schermata"],
          riga["nota"])
         for riga in connessione.execute("SELECT * FROM scatti")
         if riga["id"] in capi))

    viaggiante.executemany(
        "INSERT INTO impronte (capo, descrittore, versione, inquadratura, "
        "metodo, riquadro, fotogramma, istante_ms, dimensione, valori, "
        "calcolata_il) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ((capi[riga["scatto_id"]], riga["descrittore"], riga["versione"],
          riga["inquadratura"], riga["metodo"], riga["riquadro"],
          riga["fotogramma"], riga["istante_ms"], riga["dimensione"],
          riga["valori"], riga["calcolata_il"])
         for riga in connessione.execute("SELECT * FROM impronte")
         if riga["scatto_id"] in capi))

    for riga in tutti(connessione,
                      "SELECT * FROM persone WHERE nome IS NOT NULL "
                      "AND stato <> 'cestino'"):
        viaggiante.execute(
            "INSERT OR IGNORE INTO persone (nome, stato, nata_il) "
            "VALUES (?, ?, ?)",
            (riga["nome"], riga["stato"], riga["nata_il"]))
        for scatto in tutti(connessione,
                            "SELECT DISTINCT scatto_id FROM volti "
                            "WHERE persona_id = ?", riga["id"]):
            capo = capi.get(scatto["scatto_id"])
            if capo:
                viaggiante.execute(
                    "INSERT OR IGNORE INTO persone_scatti "
                    "(nome, impronta, a_mano) VALUES (?, ?, 0)",
                    (riga["nome"], capo))
        for scatto in tutti(connessione,
                            "SELECT scatto_id FROM persone_negli_scatti "
                            "WHERE persona_id = ?", riga["id"]):
            capo = capi.get(scatto["scatto_id"])
            if capo:
                viaggiante.execute(
                    "INSERT INTO persone_scatti (nome, impronta, a_mano) "
                    "VALUES (?, ?, 1) ON CONFLICT (nome, impronta) "
                    "DO UPDATE SET a_mano = 1", (riga["nome"], capo))

    viaggiante.executemany(
        "INSERT OR IGNORE INTO cuori (telefono, sistema, impronta, "
        "messo_il, tolto_il) VALUES (?, ?, ?, ?, ?)",
        ((riga["telefono"], riga["sistema"], riga["impronta"],
          riga["messo_il"], riga["tolto_il"])
         for riga in connessione.execute(
             "SELECT c.*, t.nome AS telefono, t.sistema AS sistema "
             "FROM cuori c JOIN telefoni t ON t.id = c.telefono_id")))


def _metti_i_file(archivio, viaggiante: sqlite3.Connection, cartella: Path,
                  chiave: cifratura.Chiave, capi: dict[int, str],
                  gia_di_la: set[str], quanti_file: int, ultimo: int,
                  avanzamento: Callable[[int, int], None] | None
                  ) -> tuple[list[str], int, int, int]:
    note: list[str] = []
    peso = 0
    quanti = 0
    quante_mini = 0
    numero = 0
    dopo = -1
    while True:
        with archivio.lettura() as connessione:
            pezzo = tutti(connessione,
                          "SELECT * FROM file_media WHERE id > ? AND id <= ? "
                          "ORDER BY id LIMIT ?", dopo, ultimo, A_PEZZI)
            if not pezzo:
                break
            dopo = pezzo[-1]["id"]
            percorsi = _percorsi(connessione, pezzo[0]["id"], dopo)
        for riga in pezzo:
            numero += 1
            impronta = riga["impronta"]
            viaggiante.execute("INSERT INTO inventario (impronta) VALUES (?)",
                               (impronta,))
            allegare = impronta not in gia_di_la

            sorgente, nome = _percorso_sul_disco(percorsi.get(riga["id"], []))
            posto = None
            if not allegare:
                pass
            elif sorgente is None:
                note.append(_senza_originale(archivio, riga["id"], impronta))
            else:
                posto = formato.posto_dell_originale()
                destinazione = formato.dentro(cartella, posto)
                destinazione.parent.mkdir(parents=True, exist_ok=True)
                scritto = chiave.cifra_file(sorgente, destinazione, posto)
                peso += scritto.peso
                quanti += 1

            mini_posto = None
            mini_formato = None
            if allegare and riga["miniatura"]:
                dati = archivio.leggi_miniatura(riga["miniatura"])
                if dati:
                    mini_formato = Path(riga["miniatura"]).suffix.lstrip(".").lower() or "jpg"
                    mini_posto = formato.posto_della_miniatura()
                    destinazione = formato.dentro(cartella, mini_posto)
                    destinazione.parent.mkdir(parents=True, exist_ok=True)
                    peso += chiave.scrivi_byte(dati, destinazione, mini_posto).peso
                    quante_mini += 1

            viaggiante.execute(
                "INSERT INTO file (impronta, capo, ruolo, genere, formato, "
                "dimensione, larghezza, altezza, orientamento, durata_ms, "
                "identificatore_ios, data_locale, fuso_minuti, istante_utc, "
                "origine_data, latitudine, longitudine, sembra_schermata, "
                "nome, posto, mini_posto, mini_formato) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (impronta, capi.get(riga["scatto_id"]), riga["ruolo"], riga["genere"],
                 riga["formato"], riga["dimensione"], riga["larghezza"],
                 riga["altezza"], riga["orientamento"], riga["durata_ms"],
                 riga["identificatore_ios"], riga["data_locale"], riga["fuso_minuti"],
                 riga["istante_utc"], riga["origine_data"], riga["latitudine"],
                 riga["longitudine"], riga["sembra_schermata"], nome, posto,
                 mini_posto, mini_formato),
            )
            if avanzamento is not None:
                avanzamento(numero, max(quanti_file, numero))
    return note, quanti, quante_mini, peso
