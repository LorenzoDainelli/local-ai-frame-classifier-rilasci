from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from officina.archivio.database import tutti
from officina.telefono import formato

SCHEMA = """
-- Chi ha fatto questo pacchetto, quando, e con che versioni. Le stesse cose
-- della carta d'identita', ripetute qui dentro dove sono cifrate: la carta si
-- può riscrivere da fuori, questa no.
CREATE TABLE informazioni (
    chiave  TEXT PRIMARY KEY,
    valore  TEXT NOT NULL
);

-- Uno scatto è una riga. `posto` e `mini` sono percorsi dentro il pacchetto.
CREATE TABLE scatti (
    id              INTEGER PRIMARY KEY,
    impronta        TEXT NOT NULL UNIQUE,   -- l'identita' vera (regole 39, 380)
    genere          TEXT NOT NULL,          -- foto | live | video
    giorno          TEXT,                   -- 'YYYY-MM-DD', NULL: senza data
    data_locale     TEXT,                   -- l'ora del posto (regole 323, 377)
    istante_utc     TEXT,                   -- solo per ordinare
    origine_data    TEXT NOT NULL,          -- exif | quicktime | manuale | dedotta
    larghezza       INTEGER,
    altezza         INTEGER,
    durata_ms       INTEGER,
    latitudine      REAL,                   -- regola 365
    longitudine     REAL,
    luogo_id        INTEGER,
    nota            TEXT,                   -- quello che hai scritto tu (regola 120)
    posto           TEXT NOT NULL,          -- foto/a3/<nome a caso>
    posto_movimento TEXT,                   -- il .MOV della live photo (regola 361)
    mini            TEXT,                   -- mini/5c/<nome a caso>
    dimensione      INTEGER NOT NULL        -- dell'originale, in chiaro
);

-- L'ordine in cui l'app mostra la griglia (regola 374): i giorni dal più
-- recente, i senza data in fondo.
CREATE INDEX scatti_per_giorno ON scatti(giorno DESC, istante_utc DESC);
CREATE INDEX scatti_per_luogo  ON scatti(luogo_id);

-- L'albero, nell'ordine del PC (regola 377). `quanti` sono le foto attaccate a
-- questo nodo e basta; `quanti_col_ramo` comprende i figli — sono i due numeri
-- che l'interruttore «solo qui» mette uno al posto dell'altro.
CREATE TABLE nodi (
    id             INTEGER PRIMARY KEY,
    genitore_id    INTEGER,
    nome           TEXT NOT NULL,
    posizione      INTEGER NOT NULL DEFAULT 0,
    quanti         INTEGER NOT NULL DEFAULT 0,
    quanti_col_ramo INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX nodi_per_genitore ON nodi(genitore_id);

-- Solo le etichette valide, ciascuna con la sua origine (regola 363): il segno
-- discreto sulla pillola si disegna leggendo questa colonna.
CREATE TABLE etichette (
    scatto_id  INTEGER NOT NULL,
    nodo_id    INTEGER NOT NULL,
    origine    TEXT NOT NULL,          -- utente | sistema (regole 18, 313)
    PRIMARY KEY (scatto_id, nodo_id)
);
CREATE INDEX etichette_per_nodo ON etichette(nodo_id);

-- Le persone con un nome (regola 363). `volto` è il ritaglio quadrato dentro
-- il pacchetto; l'impronta della faccia non c'è e non ci sarà (regola 364).
CREATE TABLE persone (
    id         INTEGER PRIMARY KEY,
    nome       TEXT NOT NULL,
    volto      TEXT,                   -- volti/12.jpg
    quanti     INTEGER NOT NULL DEFAULT 0,
    dal_giorno TEXT,
    al_giorno  TEXT
);

CREATE TABLE persone_negli_scatti (
    scatto_id  INTEGER NOT NULL,
    persona_id INTEGER NOT NULL,
    origine    TEXT NOT NULL,          -- volto | a_mano (regola 294)
    PRIMARY KEY (scatto_id, persona_id)
);
CREATE INDEX persone_per_persona ON persone_negli_scatti(persona_id);

-- «Spesso insieme a» (regola 377): il conto lo fa il PC, il telefono lo legge.
CREATE TABLE insieme (
    persona_id INTEGER NOT NULL,
    altra_id   INTEGER NOT NULL,
    quante     INTEGER NOT NULL,
    PRIMARY KEY (persona_id, altra_id)
);

-- Il nome del luogo viaggia già scritto (regola 365): sul telefono non c'è
-- nessun elenco di località da consultare, e non serve.
CREATE TABLE luoghi (
    id          INTEGER PRIMARY KEY,
    nome        TEXT,
    latitudine  REAL,
    longitudine REAL,
    quanti      INTEGER NOT NULL DEFAULT 0
);

-- Le parole calcolate dal PC (regola 378). Vuota finché non c'è il
-- vocabolario: `informazioni.versione_vocabolario` dice quale, e vuoto vuol
-- dire che sul telefono si cerca solo fra i nomi.
CREATE TABLE parole (
    scatto_id INTEGER NOT NULL,
    parola    TEXT NOT NULL,
    PRIMARY KEY (scatto_id, parola)
);
CREATE INDEX parole_per_parola ON parole(parola);

-- I filtri salvati sul PC (regole 68, 379). Vuota finché sul PC non si
-- possono salvare.
CREATE TABLE filtri (
    id          INTEGER PRIMARY KEY,
    nome        TEXT NOT NULL,
    definizione TEXT NOT NULL          -- JSON
);

-- La copia di scorta dei cuori e delle raccolte (regola 380). Il telefono li
-- possiede e non li perde per un travaso: questa copia serve al giorno in cui
-- l'app viene cancellata e reinstallata, che su iOS porta via tutto lo spazio
-- dell'app (regola 357). Si identificano per impronta, non per numero.
CREATE TABLE cuori (
    impronta TEXT PRIMARY KEY,
    messo_il TEXT
);

-- I cuori tolti sul monitor grande: l'eccezione voluta alla regola 68. Senza
-- questo elenco il gesto fatto sul PC verrebbe annullato dal telefono al
-- travaso successivo.
CREATE TABLE cuori_tolti (
    impronta TEXT PRIMARY KEY,
    tolto_il TEXT
);

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
"""


@dataclass
class Posto:
    scatto_id: int
    impronta: str
    posto: str
    dimensione: int
    posto_movimento: str | None = None
    mini: str | None = None


def costruisci(connessione: sqlite3.Connection, posti: list[Posto],
               volti: dict[int, str], informazioni: dict, lavoro: Path,
               scorta: dict | None = None) -> bytes:
    scelti = [p.scatto_id for p in posti]
    _prepara_i_scelti(connessione, scelti)
    try:
        fuori = sqlite3.connect(":memory:")
        fuori.row_factory = sqlite3.Row
        try:
            fuori.executescript(SCHEMA)
            _scrivi_scatti(fuori, connessione, posti)
            usati = _scrivi_nodi_e_etichette(fuori, connessione, scelti)
            _scrivi_persone(fuori, connessione, volti)
            _scrivi_luoghi(fuori, connessione)
            _scrivi_scorta(fuori, scorta or {})
            _scrivi_informazioni(fuori, informazioni, len(posti), usati)
            fuori.commit()
            fuori.execute("VACUUM")
            return fuori.serialize()
        finally:
            fuori.close()
    finally:
        connessione.execute("DROP TABLE IF EXISTS temp.scelti")


def _prepara_i_scelti(connessione: sqlite3.Connection, scelti: list[int]) -> None:
    connessione.execute("DROP TABLE IF EXISTS temp.scelti")
    connessione.execute("CREATE TEMP TABLE scelti (id INTEGER PRIMARY KEY)")
    connessione.executemany("INSERT OR IGNORE INTO temp.scelti (id) VALUES (?)",
                            [(x,) for x in scelti])


def _scrivi_scatti(fuori, connessione, posti: list[Posto]) -> None:
    dove = {p.scatto_id: p for p in posti}
    luogo_di = _luogo_di_ogni_scatto(connessione)
    righe = tutti(connessione,
                  "SELECT s.* FROM scatti s JOIN temp.scelti c ON c.id = s.id")
    fuori.executemany(
        "INSERT INTO scatti (id, impronta, genere, giorno, data_locale, "
        "istante_utc, origine_data, larghezza, altezza, durata_ms, latitudine, "
        "longitudine, luogo_id, nota, posto, posto_movimento, mini, dimensione) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [(r["id"], dove[r["id"]].impronta, r["genere"], r["giorno"],
          r["data_locale"], r["istante_utc"], r["origine_data"], r["larghezza"],
          r["altezza"], r["durata_ms"], r["latitudine"], r["longitudine"],
          luogo_di.get(r["id"]), r["nota"], dove[r["id"]].posto,
          dove[r["id"]].posto_movimento, dove[r["id"]].mini,
          dove[r["id"]].dimensione)
         for r in righe if r["id"] in dove])


def _scrivi_nodi_e_etichette(fuori, connessione, scelti: list[int]) -> int:
    etichette = tutti(
        connessione,
        "SELECT e.scatto_id, e.nodo_id, e.origine FROM etichette e "
        "JOIN temp.scelti c ON c.id = e.scatto_id "
        "JOIN nodi n ON n.id = e.nodo_id "
        "WHERE e.stato = 'si' AND n.stato = 'attivo'")
    if not etichette:
        return 0

    nodi_righe = tutti(connessione,
                       "SELECT id, genitore_id, nome FROM nodi "
                       "WHERE stato = 'attivo' ORDER BY genitore_id, nome")
    genitore = {r["id"]: r["genitore_id"] for r in nodi_righe}

    diretti: dict[int, set[int]] = defaultdict(set)
    for r in etichette:
        diretti[r["nodo_id"]].add(r["scatto_id"])

    col_ramo: dict[int, set[int]] = defaultdict(set)
    for nodo_id, scatti in diretti.items():
        salita = nodo_id
        visti = set()
        while salita is not None and salita not in visti:
            visti.add(salita)
            col_ramo[salita] |= scatti
            salita = genitore.get(salita)

    da_tenere = {n for n, s in col_ramo.items() if s}
    fuori.executemany(
        "INSERT INTO nodi (id, genitore_id, nome, posizione, quanti, "
        "quanti_col_ramo) VALUES (?,?,?,?,?,?)",
        [(r["id"],
          r["genitore_id"] if r["genitore_id"] in da_tenere else None,
          r["nome"], posizione, len(diretti.get(r["id"], ())),
          len(col_ramo.get(r["id"], ())))
         for posizione, r in enumerate(nodi_righe) if r["id"] in da_tenere])

    fuori.executemany(
        "INSERT OR IGNORE INTO etichette (scatto_id, nodo_id, origine) "
        "VALUES (?,?,?)",
        [(r["scatto_id"], r["nodo_id"], r["origine"]) for r in etichette
         if r["nodo_id"] in da_tenere])
    return len(da_tenere)


def _scrivi_persone(fuori, connessione, volti: dict[int, str]) -> None:
    dentro = tutti(
        connessione,
        """
        SELECT p.id, p.nome, x.scatto_id, x.origine, s.giorno
        FROM persone p
        JOIN (
            SELECT DISTINCT v.persona_id AS persona_id, v.scatto_id AS scatto_id,
                   'volto' AS origine
            FROM volti v JOIN temp.scelti c ON c.id = v.scatto_id
            WHERE v.persona_id IS NOT NULL
            UNION
            SELECT n.persona_id, n.scatto_id, 'a_mano'
            FROM persone_negli_scatti n JOIN temp.scelti c ON c.id = n.scatto_id
        ) x ON x.persona_id = p.id
        JOIN scatti s ON s.id = x.scatto_id
        WHERE p.nome IS NOT NULL AND p.nome <> '' AND p.stato = 'attiva'
        """)
    if not dentro:
        return

    suoi: dict[int, set[int]] = defaultdict(set)
    nome = {}
    giorni: dict[int, list[str]] = defaultdict(list)
    legami = []
    for r in dentro:
        suoi[r["id"]].add(r["scatto_id"])
        nome[r["id"]] = r["nome"]
        if r["giorno"]:
            giorni[r["id"]].append(r["giorno"])
        legami.append((r["scatto_id"], r["id"], r["origine"]))

    fuori.executemany(
        "INSERT INTO persone (id, nome, volto, quanti, dal_giorno, al_giorno) "
        "VALUES (?,?,?,?,?,?)",
        [(persona_id, nome[persona_id], volti.get(persona_id),
          len(scatti), min(giorni[persona_id]) if giorni[persona_id] else None,
          max(giorni[persona_id]) if giorni[persona_id] else None)
         for persona_id, scatti in suoi.items()])

    migliore: dict[tuple[int, int], str] = {}
    for scatto_id, persona_id, origine in legami:
        chiave = (scatto_id, persona_id)
        if migliore.get(chiave) != "a_mano":
            migliore[chiave] = origine
    fuori.executemany(
        "INSERT INTO persone_negli_scatti (scatto_id, persona_id, origine) "
        "VALUES (?,?,?)",
        [(s, p, o) for (s, p), o in migliore.items()])

    elenco = sorted(suoi)
    for uno_id in elenco:
        for altro_id in elenco:
            if uno_id == altro_id:
                continue
            quante = len(suoi[uno_id] & suoi[altro_id])
            if quante >= 2:
                fuori.execute(
                    "INSERT INTO insieme (persona_id, altra_id, quante) "
                    "VALUES (?,?,?)", (uno_id, altro_id, quante))


def _luogo_di_ogni_scatto(connessione) -> dict[int, int]:
    fuori: dict[int, int] = {}
    for riga in tutti(connessione,
                      "SELECT n.scatto_id, n.posto_id FROM posti_negli_scatti n "
                      "JOIN temp.scelti c ON c.id = n.scatto_id "
                      "JOIN posti p ON p.id = n.posto_id WHERE p.stato = 'attivo' "
                      "ORDER BY n.id"):
        fuori.setdefault(riga["scatto_id"], riga["posto_id"])
    return fuori


def _scrivi_luoghi(fuori, connessione) -> None:
    from officina.modello import posti as posti_mod

    quanti: dict[int, int] = {}
    for posto_id in _luogo_di_ogni_scatto(connessione).values():
        quanti[posto_id] = quanti.get(posto_id, 0) + 1
    righe = []
    for posto_id, conto in quanti.items():
        dove = posti_mod.coordinate(connessione, posto_id) or {}
        righe.append((posto_id, posti_mod.percorso(connessione, posto_id),
                      dove.get("latitudine"), dove.get("longitudine"), conto))
    fuori.executemany(
        "INSERT INTO luoghi (id, nome, latitudine, longitudine, quanti) "
        "VALUES (?,?,?,?,?)", righe)


def _scrivi_scorta(fuori, scorta: dict) -> None:
    fuori.executemany("INSERT OR REPLACE INTO cuori (impronta, messo_il) "
                      "VALUES (?,?)", scorta.get("cuori", []))
    fuori.executemany("INSERT OR REPLACE INTO cuori_tolti (impronta, tolto_il) "
                      "VALUES (?,?)", scorta.get("tolti", []))
    fuori.executemany("INSERT OR REPLACE INTO raccolte (id, nome, creata_il) "
                      "VALUES (?,?,?)", scorta.get("raccolte", []))
    for numero, impronte in (scorta.get("raccolte_scatti") or {}).items():
        fuori.executemany(
            "INSERT OR REPLACE INTO raccolte_scatti (raccolta_id, impronta) "
            "VALUES (?,?)", [(numero, x) for x in impronte])


def _scrivi_informazioni(fuori, informazioni: dict, quanti_scatti: int,
                         quanti_nodi: int) -> None:
    dentro = dict(informazioni)
    dentro.setdefault("versione_formato", formato.VERSIONE_FORMATO)
    dentro["quanti_scatti"] = quanti_scatti
    dentro["quanti_nodi"] = quanti_nodi
    fuori.executemany(
        "INSERT INTO informazioni (chiave, valore) VALUES (?,?)",
        [(c, v if isinstance(v, str) else json.dumps(v, ensure_ascii=False))
         for c, v in dentro.items()])
