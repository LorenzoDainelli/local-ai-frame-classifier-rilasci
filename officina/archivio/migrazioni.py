from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import PurePosixPath, PureWindowsPath
from typing import Callable

from officina import VERSIONE_SCHEMA
from officina import registro
from officina.archivio import database
from officina.errori import DatabaseIncoerente


@dataclass(frozen=True)
class Migrazione:
    versione: int
    descrizione: str
    applica: Callable[[sqlite3.Connection], None]


def _versione_1(connessione: sqlite3.Connection) -> None:
    database.crea_da_zero(connessione)


def _versione_2(connessione: sqlite3.Connection) -> None:
    connessione.execute(
        """
        CREATE TABLE dispositivi (
            id             INTEGER PRIMARY KEY,
            indirizzo      TEXT NOT NULL UNIQUE,
            nome           TEXT,
            stato          TEXT NOT NULL DEFAULT 'in_attesa'
                           CHECK (stato IN ('in_attesa','approvato','rifiutato')),
            primo_contatto TEXT NOT NULL,
            ultimo_contatto TEXT,
            contatti       INTEGER NOT NULL DEFAULT 1
        )
        """
    )


def _versione_3(connessione: sqlite3.Connection) -> None:
    connessione.execute(
        """
        CREATE TABLE impronte (
            id            INTEGER PRIMARY KEY,
            scatto_id     INTEGER NOT NULL REFERENCES scatti(id) ON DELETE CASCADE,
            file_id       INTEGER REFERENCES file_media(id) ON DELETE SET NULL,
            descrittore   TEXT NOT NULL,
            versione      TEXT NOT NULL,
            inquadratura  TEXT NOT NULL
                          CHECK (inquadratura IN ('intera','persona','stretto')),
            metodo        TEXT NOT NULL,
            riquadro      TEXT,
            fotogramma    INTEGER NOT NULL DEFAULT 0,
            istante_ms    INTEGER,
            dimensione    INTEGER NOT NULL,
            valori        BLOB NOT NULL,
            calcolata_il  TEXT NOT NULL,
            UNIQUE (scatto_id, descrittore, versione, inquadratura, fotogramma)
        )
        """
    )
    connessione.execute(
        "CREATE INDEX impronte_per_passata "
        "ON impronte(descrittore, versione, inquadratura)"
    )
    connessione.execute("CREATE INDEX impronte_per_scatto ON impronte(scatto_id)")

    connessione.execute(
        """
        CREATE TABLE misure (
            id        INTEGER PRIMARY KEY,
            fatta_il  TEXT NOT NULL,
            archivio  TEXT NOT NULL,
            scatti    INTEGER NOT NULL,
            gruppi    INTEGER NOT NULL,
            nodi      INTEGER NOT NULL,
            rapporto  TEXT NOT NULL,
            nota      TEXT
        )
        """
    )


def _versione_4(connessione: sqlite3.Connection) -> None:
    connessione.execute(
        """
        CREATE TABLE fotografie_albero (
            id        INTEGER PRIMARY KEY,
            fatta_il  TEXT NOT NULL,
            motivo    TEXT,              -- «dopo aver spostato nodo_12»
            nodi      INTEGER NOT NULL,  -- quanti erano, per l'elenco
            forma     TEXT NOT NULL      -- JSON: id, genitore, nome, stato
        )
        """
    )
    connessione.execute(
        "CREATE INDEX fotografie_per_data ON fotografie_albero(fatta_il DESC)")


def _versione_5(connessione: sqlite3.Connection) -> None:
    connessione.execute(
        """
        CREATE TABLE persone (
            id              INTEGER PRIMARY KEY,
            nome            TEXT,          -- NULL: gruppo senza nome (regola 82)
            stato           TEXT NOT NULL DEFAULT 'attiva'
                            CHECK (stato IN ('attiva','ignora','cestino','congelata')),
            volto_copertina INTEGER,       -- il più nitido (regola 292)
            rimandata_il    TEXT,          -- «salta» = in fondo al mazzo (regola 287)
            nata_il         TEXT NOT NULL
        )
        """
    )
    connessione.execute(
        """
        CREATE TABLE volti (
            id           INTEGER PRIMARY KEY,
            scatto_id    INTEGER NOT NULL REFERENCES scatti(id) ON DELETE CASCADE,
            file_id      INTEGER REFERENCES file_media(id) ON DELETE SET NULL,
            fotogramma   INTEGER NOT NULL DEFAULT 0,
            riquadro     TEXT NOT NULL,    -- JSON [x, y, larghezza, altezza], da 0 a 1
            area         REAL NOT NULL,    -- quanto occupa: regole 153, 295
            nitidezza    REAL NOT NULL,    -- regola 292
            sicurezza    REAL NOT NULL,    -- quanto ci crede il rilevatore
            impronta     BLOB,             -- il vettore del volto
            modello      TEXT NOT NULL,
            versione     TEXT NOT NULL,
            persona_id   INTEGER REFERENCES persone(id) ON DELETE SET NULL,
            deciso_da    TEXT NOT NULL DEFAULT 'sistema'
                         CHECK (deciso_da IN ('sistema','utente')),
            trovato_il   TEXT NOT NULL
        )
        """
    )
    connessione.execute("CREATE INDEX volti_per_scatto ON volti(scatto_id)")
    connessione.execute("CREATE INDEX volti_per_persona ON volti(persona_id, area DESC)")
    connessione.execute(
        "CREATE INDEX volti_per_modello ON volti(modello, versione)")

    connessione.execute(
        """
        CREATE TABLE persone_negli_scatti (
            id         INTEGER PRIMARY KEY,
            scatto_id  INTEGER NOT NULL REFERENCES scatti(id) ON DELETE CASCADE,
            persona_id INTEGER NOT NULL REFERENCES persone(id) ON DELETE CASCADE,
            messa_il   TEXT NOT NULL,
            UNIQUE (scatto_id, persona_id)
        )
        """
    )

    connessione.execute(
        """
        CREATE TABLE forse_stessa_persona (
            id           INTEGER PRIMARY KEY,
            una_id       INTEGER NOT NULL REFERENCES persone(id) ON DELETE CASCADE,
            altra_id     INTEGER NOT NULL REFERENCES persone(id) ON DELETE CASCADE,
            somiglianza  REAL NOT NULL,
            risposta     TEXT NOT NULL DEFAULT 'da_guardare'
                         CHECK (risposta IN ('da_guardare','no','non_so')),
            guardata_il  TEXT,
            nata_il      TEXT NOT NULL,
            UNIQUE (una_id, altra_id)
        )
        """
    )


def _versione_6(connessione: sqlite3.Connection) -> None:
    connessione.execute(
        """
        CREATE TABLE luoghi (
            id             INTEGER PRIMARY KEY,
            nome           TEXT,             -- lo metti tu, NULL finché non lo fai
            centro_lat     REAL NOT NULL,
            centro_lon     REAL NOT NULL,
            raggio_metri   REAL NOT NULL DEFAULT 0,
            quanti         INTEGER NOT NULL DEFAULT 0,
            nato_il        TEXT NOT NULL
        )
        """
    )
    connessione.execute(
        "ALTER TABLE scatti ADD COLUMN luogo_id INTEGER "
        "REFERENCES luoghi(id) ON DELETE SET NULL")
    connessione.execute("CREATE INDEX scatti_per_luogo ON scatti(luogo_id)")


def _versione_7(connessione: sqlite3.Connection) -> None:
    connessione.execute(
        """
        CREATE TABLE volti_riferimento (
            id          INTEGER PRIMARY KEY,
            persona_id  INTEGER NOT NULL REFERENCES persone(id) ON DELETE CASCADE,
            da_file     TEXT NOT NULL,    -- solo il nome, non il percorso
            riquadro    TEXT NOT NULL,    -- JSON [x, y, larghezza, altezza], da 0 a 1
            area        REAL NOT NULL,
            nitidezza   REAL NOT NULL,
            sicurezza   REAL NOT NULL,
            impronta    BLOB NOT NULL,
            modello     TEXT NOT NULL,
            versione    TEXT NOT NULL,
            letto_il    TEXT NOT NULL,
            UNIQUE (persona_id, da_file, riquadro)
        )
        """
    )
    connessione.execute(
        "CREATE INDEX riferimento_per_persona "
        "ON volti_riferimento(persona_id, modello, versione)")


def _versione_8(connessione: sqlite3.Connection) -> None:
    connessione.execute(
        """
        CREATE TABLE ripassi (
            nodo_id          INTEGER PRIMARY KEY REFERENCES nodi(id) ON DELETE CASCADE,
            stato            TEXT NOT NULL DEFAULT 'chiesto'
                             CHECK (stato IN ('chiesto','in_corso','finito','rifiutato')),
            ultimo_scatto_id INTEGER,
            rivisti          INTEGER NOT NULL DEFAULT 0,
            creato_il        TEXT NOT NULL,
            deciso_il        TEXT
        )
        """
    )
    connessione.execute("CREATE INDEX ripassi_per_stato ON ripassi(stato)")


def _versione_9(connessione: sqlite3.Connection) -> None:
    connessione.execute(
        """
        CREATE TABLE telefoni (
            id                INTEGER PRIMARY KEY,
            nome              TEXT NOT NULL UNIQUE,     -- «iPhone», «Redmi»
            sistema           TEXT NOT NULL DEFAULT 'android'
                              CHECK (sistema IN ('ios','android')),
            selezione         TEXT NOT NULL DEFAULT '{}',   -- JSON (regola 360)
            spazio            INTEGER,        -- quanto ci sta, se lo sappiamo
            spazio_chiesto_il TEXT,           -- quando lo hai detto tu (regola 369)
            cartella          TEXT,           -- dove si è costruito l'ultima volta
            creato_il         TEXT NOT NULL,
            ultimo_travaso_il TEXT
        )
        """
    )
    connessione.execute(
        """
        CREATE TABLE travasi (
            id             INTEGER PRIMARY KEY,
            telefono_id    INTEGER NOT NULL REFERENCES telefoni(id) ON DELETE CASCADE,
            cartella       TEXT NOT NULL,
            stato          TEXT NOT NULL DEFAULT 'in_corso'
                           CHECK (stato IN ('in_corso','finito','interrotto')),
            iniziato_il    TEXT NOT NULL,
            finito_il      TEXT,
            quanti_scatti  INTEGER NOT NULL DEFAULT 0,
            scritti        INTEGER NOT NULL DEFAULT 0,   -- file nuovi copiati
            tolti          INTEGER NOT NULL DEFAULT 0,   -- file che non ci vanno più
            saltati        INTEGER NOT NULL DEFAULT 0,   -- non letti (regola 370)
            peso           INTEGER NOT NULL DEFAULT 0,
            verificato     INTEGER NOT NULL DEFAULT 0    -- riletto alla fine
        )
        """
    )
    connessione.execute(
        "CREATE INDEX travasi_per_telefono ON travasi(telefono_id, iniziato_il DESC)")

    connessione.execute(
        """
        CREATE TABLE pacchetto_file (
            id          INTEGER PRIMARY KEY,
            telefono_id INTEGER NOT NULL REFERENCES telefoni(id) ON DELETE CASCADE,
            posto       TEXT NOT NULL,        -- il percorso dentro il pacchetto
            genere      TEXT NOT NULL
                        CHECK (genere IN ('originale','miniatura','volto','dati')),
            impronta    TEXT NOT NULL,        -- del contenuto in chiaro (regola 39)
            dimensione  INTEGER NOT NULL,     -- in chiaro
            peso        INTEGER NOT NULL,     -- cifrato, com'è sul telefono
            scatto_id   INTEGER,              -- solo per sapere chi l'ha portato
            scritto_il  TEXT NOT NULL,
            UNIQUE (telefono_id, posto)
        )
        """
    )
    connessione.execute(
        "CREATE INDEX pacchetto_per_impronta ON pacchetto_file(telefono_id, impronta)")


def _versione_10(connessione: sqlite3.Connection) -> None:
    connessione.execute(
        """
        CREATE TABLE cuori (
            id          INTEGER PRIMARY KEY,
            telefono_id INTEGER NOT NULL REFERENCES telefoni(id) ON DELETE CASCADE,
            impronta    TEXT NOT NULL,           -- del contenuto (regola 39)
            scatto_id   INTEGER REFERENCES scatti(id) ON DELETE SET NULL,
            messo_il    TEXT,                    -- l'ora del telefono
            tolto_il    TEXT,                    -- deciso sul monitor grande
            tornato_il  TEXT NOT NULL,
            UNIQUE (telefono_id, impronta)
        )
        """
    )
    connessione.execute("CREATE INDEX cuori_per_scatto ON cuori(scatto_id)")

    connessione.execute(
        """
        CREATE TABLE raccolte (
            id          INTEGER PRIMARY KEY,
            telefono_id INTEGER NOT NULL REFERENCES telefoni(id) ON DELETE CASCADE,
            numero      INTEGER NOT NULL,        -- il suo numero sul telefono
            nome        TEXT NOT NULL,
            creata_il   TEXT,
            tornata_il  TEXT NOT NULL,
            UNIQUE (telefono_id, numero)
        )
        """
    )
    connessione.execute(
        """
        CREATE TABLE raccolte_scatti (
            raccolta_id INTEGER NOT NULL REFERENCES raccolte(id) ON DELETE CASCADE,
            impronta    TEXT NOT NULL,
            scatto_id   INTEGER REFERENCES scatti(id) ON DELETE SET NULL,
            PRIMARY KEY (raccolta_id, impronta)
        )
        """
    )

    connessione.execute(
        """
        CREATE TABLE diario_visore (
            id          INTEGER PRIMARY KEY,
            telefono_id INTEGER NOT NULL REFERENCES telefoni(id) ON DELETE CASCADE,
            aperto_il   TEXT NOT NULL,           -- l'ora esatta, del telefono
            durata_s    INTEGER,
            latitudine  REAL,                    -- le coordinate esatte
            longitudine REAL,
            quante_foto INTEGER,
            tornato_il  TEXT NOT NULL,
            UNIQUE (telefono_id, aperto_il)
        )
        """
    )
    connessione.execute(
        "CREATE INDEX diario_per_telefono ON diario_visore(telefono_id, aperto_il)")


def _versione_11(connessione: sqlite3.Connection) -> None:
    connessione.execute(
        """
        CREATE TABLE macchine (
            id           INTEGER PRIMARY KEY,
            codice       TEXT NOT NULL UNIQUE,   -- nato a caso una volta sola
            nome         TEXT NOT NULL,          -- «fisso», «zenbook»: lo leggi tu
            questa       INTEGER NOT NULL DEFAULT 0,  -- 1 sola riga: sono io
            visto_fino_a INTEGER NOT NULL DEFAULT 0,  -- l'ultimo seriale suo che ho letto
            conosciuta_il TEXT NOT NULL,
            vista_il     TEXT                    -- l'ultimo pacchetto arrivato da lei
        )
        """
    )
    connessione.execute(
        "CREATE UNIQUE INDEX macchine_questa ON macchine(questa) WHERE questa = 1")

    connessione.execute(
        """
        CREATE TABLE cambiamenti (
            id          INTEGER PRIMARY KEY,
            macchina_id INTEGER NOT NULL REFERENCES macchine(id) ON DELETE CASCADE,
            seriale     INTEGER NOT NULL,        -- conta per macchina, da 1
            avvenuto_il TEXT NOT NULL,           -- l'ora di chi l'ha scritto (regola 410)
            cosa        TEXT NOT NULL CHECK (cosa IN
                        ('etichetta','nodo','persona','cuore')),
            azione      TEXT NOT NULL CHECK (azione IN
                        ('messa','tolta','cambiata',
                         'creato','rinominato','spostato','stato')),
            scatto_id   INTEGER,                 -- numero locale: si traduce partendo
            nodo_id     INTEGER,                 -- numero locale: si traduce partendo
            stato       TEXT,
            origine     TEXT,                    -- 'utente' o 'sistema' (regola 405)
            valore      TEXT,                    -- il nome nuovo, lo stato nuovo
            UNIQUE (macchina_id, seriale)
        )
        """
    )
    connessione.execute(
        "CREATE INDEX cambiamenti_da_mandare ON cambiamenti(macchina_id, seriale)")


def _versione_12(connessione: sqlite3.Connection) -> None:
    connessione.execute(
        """
        CREATE TABLE inventario_altrui (
            macchina_id INTEGER NOT NULL REFERENCES macchine(id) ON DELETE CASCADE,
            impronta    TEXT NOT NULL,
            saputo_il   TEXT NOT NULL,
            PRIMARY KEY (macchina_id, impronta)
        ) WITHOUT ROWID
        """
    )
    connessione.execute(
        "ALTER TABLE macchine ADD COLUMN mi_ha_vista_fino_a INTEGER NOT NULL DEFAULT 0")


def _versione_13(connessione: sqlite3.Connection) -> None:
    connessione.execute("ALTER TABLE cambiamenti ADD COLUMN valore_prima TEXT")


def _versione_14(connessione: sqlite3.Connection) -> None:
    connessione.execute("ALTER TABLE impostazioni ADD COLUMN cambiata_il TEXT")


def _versione_15(connessione: sqlite3.Connection) -> None:
    connessione.execute(
        """
        CREATE TABLE impronte_nuove (
            id            INTEGER PRIMARY KEY,
            scatto_id     INTEGER NOT NULL REFERENCES scatti(id) ON DELETE CASCADE,
            file_id       INTEGER REFERENCES file_media(id) ON DELETE SET NULL,
            descrittore   TEXT NOT NULL,
            versione      TEXT NOT NULL,
            inquadratura  TEXT NOT NULL
                          CHECK (inquadratura IN ('intera','persona','stretto')
                                 OR inquadratura GLOB 'griglia_r[0-9][0-9]c[0-9][0-9]'),
            metodo        TEXT NOT NULL,
            riquadro      TEXT,
            fotogramma    INTEGER NOT NULL DEFAULT 0,
            istante_ms    INTEGER,
            dimensione    INTEGER NOT NULL,
            valori        BLOB NOT NULL,
            calcolata_il  TEXT NOT NULL,
            UNIQUE (scatto_id, descrittore, versione, inquadratura, fotogramma)
        )
        """
    )
    connessione.execute(
        """
        INSERT INTO impronte_nuove
            (id, scatto_id, file_id, descrittore, versione, inquadratura,
             metodo, riquadro, fotogramma, istante_ms, dimensione, valori,
             calcolata_il)
        SELECT id, scatto_id, file_id, descrittore, versione, inquadratura,
               metodo, riquadro, fotogramma, istante_ms, dimensione, valori,
               calcolata_il
        FROM impronte
        """
    )
    connessione.execute("DROP TABLE impronte")
    connessione.execute("ALTER TABLE impronte_nuove RENAME TO impronte")
    connessione.execute(
        "CREATE INDEX impronte_per_passata "
        "ON impronte(descrittore, versione, inquadratura)"
    )
    connessione.execute("CREATE INDEX impronte_per_scatto ON impronte(scatto_id)")


def _versione_16(connessione: sqlite3.Connection) -> None:
    connessione.execute(
        """
        CREATE TABLE scritte (
            id          INTEGER PRIMARY KEY,
            scatto_id   INTEGER NOT NULL REFERENCES scatti(id) ON DELETE CASCADE,
            file_id     INTEGER REFERENCES file_media(id) ON DELETE SET NULL,
            testo       TEXT NOT NULL,
            -- Lo stesso testo tutto minuscolo e senza accenti: è quello su cui
            -- si cerca. Cercare «BAR» e non trovare «Bar» sarebbe un difetto
            -- che sembra un archivio vuoto.
            cercabile   TEXT NOT NULL,
            riquadro    TEXT,
            fotogramma  INTEGER NOT NULL DEFAULT 0,
            modello     TEXT NOT NULL,
            versione    TEXT NOT NULL,
            letta_il    TEXT NOT NULL
        )
        """
    )
    connessione.execute("CREATE INDEX scritte_per_scatto ON scritte(scatto_id)")
    connessione.execute("CREATE INDEX scritte_da_cercare ON scritte(cercabile)")
    connessione.execute(
        "CREATE INDEX scritte_per_passata ON scritte(modello, versione, scatto_id)")
    connessione.execute(
        """
        CREATE TABLE scritte_lette (
            scatto_id   INTEGER NOT NULL REFERENCES scatti(id) ON DELETE CASCADE,
            modello     TEXT NOT NULL,
            versione    TEXT NOT NULL,
            quante      INTEGER NOT NULL DEFAULT 0,
            letta_il    TEXT NOT NULL,
            PRIMARY KEY (scatto_id, modello, versione)
        )
        """
    )


def _versione_17(connessione: sqlite3.Connection) -> None:
    connessione.execute(
        "ALTER TABLE scatti ADD COLUMN cuore INTEGER NOT NULL DEFAULT 0")
    connessione.execute("ALTER TABLE scatti ADD COLUMN cuore_il TEXT")
    connessione.execute(
        "ALTER TABLE scatti ADD COLUMN evidenziato INTEGER NOT NULL DEFAULT 0")
    connessione.execute("ALTER TABLE scatti ADD COLUMN evidenziato_il TEXT")
    connessione.execute(
        "CREATE INDEX scatti_evidenziati ON scatti(evidenziato, istante_utc)")
    connessione.execute("CREATE INDEX scatti_col_cuore ON scatti(cuore, istante_utc)")


def _versione_18(connessione: sqlite3.Connection) -> None:
    connessione.execute("ALTER TABLE file_media ADD COLUMN impronta_occhio TEXT")
    connessione.execute(
        "CREATE INDEX file_per_impronta_occhio ON file_media(impronta_occhio)")


def _versione_19(connessione: sqlite3.Connection) -> None:
    connessione.execute(
        """
        CREATE TABLE doppioni_gruppi (
            firma      TEXT NOT NULL,       -- chi c'era nel gruppo, in ordine
            file_id    INTEGER NOT NULL REFERENCES file_media(id) ON DELETE CASCADE,
            posto      INTEGER NOT NULL,    -- 0 è quello che pesa di più
            distanza   INTEGER NOT NULL,    -- quanto lontane al massimo, in bit
            contato_il TEXT NOT NULL,
            PRIMARY KEY (firma, file_id)
        ) WITHOUT ROWID
        """
    )
    connessione.execute(
        "CREATE INDEX doppioni_gruppi_per_file ON doppioni_gruppi(file_id)")

    connessione.execute(
        """
        CREATE TABLE doppioni_decisi (
            firma       TEXT PRIMARY KEY,
            scelta      TEXT NOT NULL CHECK (scelta IN ('tenuto','diverse')),
            tenuto_id   INTEGER,            -- il file rimasto dentro, se scelta = 'tenuto'
            messi_fuori TEXT,               -- gli scatti che ho spostato io, separati da virgola
            deciso_il   TEXT NOT NULL
        ) WITHOUT ROWID
        """
    )

def _versione_20(connessione: sqlite3.Connection) -> None:
    connessione.execute(
        "CREATE INDEX file_media_arrivo ON file_media(aggiunto_il) "
        "WHERE genere = 'immagine'")


def _versione_21(connessione: sqlite3.Connection) -> None:
    connessione.execute(
        "CREATE INDEX impronte_per_peso ON impronte(dimensione)")
    connessione.execute(
        "CREATE INDEX scatti_per_genere ON scatti(genere, fuori_archivio)")
    connessione.execute(
        "CREATE INDEX scatti_senza_data ON scatti(id) "
        "WHERE data_locale IS NULL")
    connessione.execute(
        "CREATE INDEX percorsi_spariti ON percorsi(file_id) "
        "WHERE presente = 0")


def _versione_22(connessione: sqlite3.Connection) -> None:
    connessione.execute("DROP INDEX IF EXISTS etichette_per_nodo")
    connessione.execute(
        "CREATE INDEX etichette_per_nodo ON etichette(nodo_id, stato, creata_il)")
    connessione.execute("DROP INDEX IF EXISTS impronte_per_passata")
    connessione.execute(
        "CREATE INDEX impronte_per_passata ON impronte("
        "descrittore, versione, inquadratura, scatto_id, calcolata_il, "
        "dimensione)")


def _versione_23(connessione: sqlite3.Connection) -> None:
    connessione.execute("ALTER TABLE importazioni ADD COLUMN nome TEXT")
    connessione.execute(
        "ALTER TABLE scatti ADD COLUMN importazione_id INTEGER "
        "REFERENCES importazioni(id) ON DELETE SET NULL")
    connessione.execute(
        "CREATE INDEX scatti_per_importazione "
        "ON scatti(importazione_id, istante_utc)")

    connessione.execute("""
        UPDATE scatti SET importazione_id = (
            SELECT min(coda.importazione_id)
              FROM file_media AS file
              JOIN percorsi AS strada ON strada.file_id = file.id
              JOIN coda_importazione AS coda ON coda.percorso = strada.percorso
             WHERE file.scatto_id = scatti.id
        )
    """)

    cartelle = connessione.execute(
        "SELECT id, percorso FROM cartelle_sorgente").fetchall()
    for riga in connessione.execute("SELECT id FROM importazioni").fetchall():
        dentro = []
        for cartella in cartelle:
            radice = str(cartella["percorso"])
            c_e = connessione.execute(
                "SELECT 1 FROM coda_importazione "
                "WHERE importazione_id = ? AND percorso LIKE ? ESCAPE '\\' "
                "LIMIT 1",
                (riga["id"], radice.replace("\\", "\\\\").replace("%", "\\%")
                 .replace("_", "\\_") + "%")).fetchone()
            if c_e:
                dentro.append(radice.replace("\\", "/").rstrip("/").split("/")[-1])
        if dentro:
            connessione.execute("UPDATE importazioni SET nome = ? WHERE id = ?",
                                (", ".join(dentro), riga["id"]))


def _versione_24(connessione: sqlite3.Connection) -> None:
    connessione.execute(
        "CREATE INDEX scatti_senza_data_in_archivio ON scatti(fuori_archivio) "
        "WHERE data_locale IS NULL")
    connessione.execute(
        "CREATE INDEX scatti_schermate ON scatti(fuori_archivio) "
        "WHERE sembra_schermata = 1")
    connessione.execute(
        "CREATE INDEX scatti_del_luogo ON scatti(luogo_id, fuori_archivio, giorno)")
    connessione.execute(
        "CREATE INDEX etichette_messe ON etichette(scatto_id, nodo_id) "
        "WHERE stato = 'si'")


def _versione_26(connessione: sqlite3.Connection) -> None:
    connessione.execute("DROP INDEX IF EXISTS scatti_evidenziati")
    connessione.execute(
        "CREATE INDEX scatti_evidenziati "
        "ON scatti(evidenziato, fuori_archivio, istante_utc)")

    connessione.execute("DROP INDEX IF EXISTS scatti_per_luogo")

    connessione.execute("DROP INDEX IF EXISTS scatti_schermate")
    connessione.execute(
        "CREATE INDEX scatti_schermate ON scatti(fuori_archivio, istante_utc) "
        "WHERE sembra_schermata = 1")

    connessione.execute(
        "CREATE INDEX etichette_tue ON etichette(scatto_id, creata_il) "
        "WHERE origine = 'utente'")

    connessione.execute("DROP INDEX IF EXISTS scatti_per_importazione")
    connessione.execute(
        "CREATE INDEX scatti_per_importazione "
        "ON scatti(importazione_id, fuori_archivio, istante_utc)")

    connessione.execute(
        "CREATE INDEX scatti_senza_coordinate "
        "ON scatti(fuori_archivio, istante_utc) WHERE latitudine IS NULL")

    connessione.execute("DROP INDEX IF EXISTS scatti_senza_data_in_archivio")
    connessione.execute(
        "CREATE INDEX scatti_senza_data_in_archivio "
        "ON scatti(fuori_archivio, istante_utc) WHERE data_locale IS NULL")


def _versione_25(connessione: sqlite3.Connection) -> None:
    connessione.execute("DROP INDEX IF EXISTS scatti_evidenziati")
    connessione.execute(
        "CREATE INDEX scatti_evidenziati "
        "ON scatti(fuori_archivio, evidenziato, istante_utc)")


def _versione_27(connessione: sqlite3.Connection) -> None:
    connessione.execute(
        """
        CREATE TABLE migliorie (
            id                  INTEGER PRIMARY KEY,
            file_id             INTEGER NOT NULL
                                REFERENCES file_media(id) ON DELETE CASCADE,
            scatto_id           INTEGER REFERENCES scatti(id) ON DELETE SET NULL,
            stato               TEXT NOT NULL DEFAULT 'in_coda'
                                CHECK (stato IN ('in_coda','in_lavoro',
                                                 'da_rivedere','in_scambio',
                                                 'approvata','rifiutata',
                                                 'fallita')),
            impronta_originale  TEXT NOT NULL,
            percorso_originale  TEXT NOT NULL,
            larghezza_prima     INTEGER,
            altezza_prima       INTEGER,
            larghezza_dopo      INTEGER,
            altezza_dopo        INTEGER,
            in_revisione        TEXT,
            impronta_migliorata TEXT,
            percorso_migliorata TEXT,
            percorso_spostato   TEXT,
            motori              TEXT,
            guasto              TEXT,
            messa_il            TEXT NOT NULL,
            finita_il           TEXT,
            decisa_il           TEXT
        )
        """
    )
    connessione.execute(
        "CREATE UNIQUE INDEX migliorie_una_per_file ON migliorie(file_id) "
        "WHERE stato IN ('in_coda','in_lavoro','da_rivedere','in_scambio',"
        "'approvata')")
    connessione.execute(
        "CREATE UNIQUE INDEX migliorie_per_impronta "
        "ON migliorie(impronta_migliorata) "
        "WHERE impronta_migliorata IS NOT NULL "
        "AND stato IN ('da_rivedere','in_scambio','approvata')")
    connessione.execute(
        "CREATE INDEX migliorie_per_stato ON migliorie(stato, id)")
    connessione.execute(
        """
        CREATE TABLE cartelle_riferimento (
            id          INTEGER PRIMARY KEY,
            persona_id  INTEGER NOT NULL
                        REFERENCES persone(id) ON DELETE CASCADE,
            percorso    TEXT NOT NULL,
            data_il     TEXT NOT NULL,
            UNIQUE (persona_id, percorso)
        )
        """
    )


def _versione_28(connessione: sqlite3.Connection) -> None:
    connessione.execute(
        """
        CREATE TABLE sfide (
            id                  INTEGER PRIMARY KEY,
            miglioria_id        INTEGER NOT NULL UNIQUE
                                REFERENCES migliorie(id) ON DELETE CASCADE,
            percorso_seedvr2    TEXT,
            percorso_lucidflux  TEXT,
            impronta_seedvr2    TEXT,
            impronta_lucidflux  TEXT,
            motori_seedvr2      TEXT,
            motori_lucidflux    TEXT,
            a_e                 TEXT NOT NULL
                                CHECK (a_e IN ('seedvr2','lucidflux')),
            a_sinistra          INTEGER NOT NULL CHECK (a_sinistra IN (0, 1)),
            voto                TEXT CHECK (voto IN ('A','B','pari','nessuna')),
            fatta_il            TEXT NOT NULL,
            votata_il           TEXT
        )
        """
    )
    connessione.execute("CREATE INDEX sfide_per_voto ON sfide(voto, id)")


def _versione_29(connessione: sqlite3.Connection) -> None:
    connessione.execute(
        "INSERT OR REPLACE INTO stato (chiave, valore, aggiornato_il) "
        "SELECT 'video_da_raddrizzare', CAST(max(id) AS TEXT), "
        "strftime('%Y-%m-%dT%H:%M:%SZ', 'now') FROM file_media "
        "WHERE genere = 'video' HAVING max(id) IS NOT NULL")


def _versione_30(connessione: sqlite3.Connection) -> None:
    _versione_29(connessione)


def _versione_31(connessione: sqlite3.Connection) -> None:
    connessione.execute("ALTER TABLE migliorie ADD COLUMN fedelta TEXT")


def _versione_32(connessione: sqlite3.Connection) -> None:
    from officina.importazione.motore import riattacca_i_live

    riattacca_i_live(connessione)
    connessione.execute("UPDATE file_media SET miniatura = NULL WHERE genere = 'video'")


def _versione_33(connessione: sqlite3.Connection) -> None:
    connessione.execute("ALTER TABLE file_media ADD COLUMN colore TEXT")


def _versione_34(connessione: sqlite3.Connection) -> None:
    from officina.importazione.motore import riattacca_i_live

    connessione.execute(
        "UPDATE scatti SET genere = 'video' WHERE genere = 'foto' AND EXISTS ("
        "SELECT 1 FROM file_media f WHERE f.scatto_id = scatti.id "
        "AND f.ruolo = 'principale' AND f.genere = 'video') AND NOT EXISTS ("
        "SELECT 1 FROM file_media f WHERE f.scatto_id = scatti.id AND f.genere = 'immagine')")
    riattacca_i_live(connessione)


def _versione_35(connessione: sqlite3.Connection) -> None:
    connessione.execute(
        """
        CREATE TABLE volti_guardati (
            scatto_id   INTEGER NOT NULL REFERENCES scatti(id) ON DELETE CASCADE,
            modello     TEXT NOT NULL,
            versione    TEXT NOT NULL,
            quanti      INTEGER NOT NULL DEFAULT 0,
            guardato_il TEXT NOT NULL,
            PRIMARY KEY (scatto_id, modello, versione)
        )
        """
    )
    connessione.execute(
        "INSERT OR IGNORE INTO volti_guardati (scatto_id, modello, versione, quanti, guardato_il) "
        "SELECT scatto_id, modello, versione, count(*), max(trovato_il) FROM volti "
        "GROUP BY scatto_id, modello, versione")


def _versione_36(connessione: sqlite3.Connection) -> None:
    connessione.execute(
        """
        CREATE TABLE descrizioni (
            scatto_id   INTEGER PRIMARY KEY REFERENCES scatti(id) ON DELETE CASCADE,
            file_id     INTEGER REFERENCES file_media(id) ON DELETE SET NULL,
            testo       TEXT NOT NULL,
            cercabile   TEXT NOT NULL,
            modello     TEXT NOT NULL,
            versione    TEXT NOT NULL,
            fatta_il    TEXT NOT NULL
        )
        """
    )


def _versione_37(connessione: sqlite3.Connection) -> None:
    connessione.execute(
        """
        CREATE TABLE gruppi (
            id          INTEGER PRIMARY KEY,
            nome        TEXT NOT NULL UNIQUE COLLATE NOCASE,
            creato_il   TEXT NOT NULL
        )
        """
    )
    connessione.execute(
        "ALTER TABLE cartelle_sorgente ADD COLUMN gruppo_id INTEGER "
        "REFERENCES gruppi(id) ON DELETE SET NULL")
    connessione.execute(
        "CREATE INDEX cartelle_per_gruppo ON cartelle_sorgente(gruppo_id)")
    connessione.execute(
        "CREATE INDEX percorsi_per_cartella ON percorsi(cartella_id, file_id)")


def _versione_38(connessione: sqlite3.Connection) -> None:
    connessione.execute(
        "UPDATE segnalazioni SET risolta = 1 WHERE tipo = 'non_si_apre' "
        "AND risolta = 0 AND dettaglio = 'senza_file' AND scatto_id IN "
        "(SELECT scatto_id FROM file_media WHERE genere = 'video')")


def _versione_39(connessione: sqlite3.Connection) -> None:
    connessione.execute(
        "INSERT OR REPLACE INTO stato (chiave, valore, aggiornato_il) "
        "SELECT 'date_da_rileggere', CAST(max(id) AS TEXT), "
        "strftime('%Y-%m-%dT%H:%M:%SZ', 'now') FROM file_media "
        "WHERE origine_data = 'assente' HAVING max(id) IS NOT NULL")


def _versione_40(connessione: sqlite3.Connection) -> None:
    connessione.execute("DELETE FROM stato WHERE chiave = 'date_rilette_fino_a'")
    _versione_39(connessione)


def _versione_41(connessione: sqlite3.Connection) -> None:
    connessione.execute("ALTER TABLE file_media ADD COLUMN marca TEXT")
    connessione.execute("ALTER TABLE file_media ADD COLUMN modello TEXT")
    connessione.execute(
        "INSERT OR REPLACE INTO stato (chiave, valore, aggiornato_il) "
        "SELECT 'macchine_da_rileggere', CAST(max(id) AS TEXT), "
        "strftime('%Y-%m-%dT%H:%M:%SZ', 'now') FROM file_media "
        "HAVING max(id) IS NOT NULL")


def _versione_42(connessione: sqlite3.Connection) -> None:
    _versione_40(connessione)


def _versione_44(connessione: sqlite3.Connection) -> None:
    connessione.execute(
        "ALTER TABLE nodi ADD COLUMN anche_da_solo INTEGER NOT NULL DEFAULT 0")


def _versione_43(connessione: sqlite3.Connection) -> None:
    connessione.execute(
        """
        CREATE TABLE posti (
            id            INTEGER PRIMARY KEY,
            genitore_id   INTEGER REFERENCES posti(id) ON DELETE RESTRICT,
            nome          TEXT NOT NULL,
            latitudine    REAL,
            longitudine   REAL,
            raggio_metri  REAL,
            coordinate_da TEXT CHECK (coordinate_da IN ('foto','a_mano','scatto')),
            stato         TEXT NOT NULL DEFAULT 'attivo'
                          CHECK (stato IN ('attivo','cestino')),
            da_nodo_id    INTEGER,
            nato_il       TEXT NOT NULL
        )
        """
    )
    connessione.execute("CREATE INDEX posti_per_genitore ON posti(genitore_id, nome)")
    connessione.execute(
        """
        CREATE TABLE posti_negli_scatti (
            id         INTEGER PRIMARY KEY,
            scatto_id  INTEGER NOT NULL REFERENCES scatti(id) ON DELETE CASCADE,
            posto_id   INTEGER NOT NULL REFERENCES posti(id) ON DELETE CASCADE,
            messo_il   TEXT NOT NULL,
            UNIQUE (scatto_id, posto_id)
        )
        """
    )
    connessione.execute(
        "CREATE INDEX posti_negli_scatti_per_posto ON posti_negli_scatti(posto_id)")
    connessione.execute(
        "CREATE INDEX scatti_per_posizione ON scatti(latitudine, longitudine)")
    connessione.execute(
        "ALTER TABLE scatti ADD COLUMN posto_non_so INTEGER NOT NULL DEFAULT 0")
    connessione.execute(
        "ALTER TABLE scatti ADD COLUMN nessuna_persona INTEGER NOT NULL DEFAULT 0")


def _versione_45(connessione: sqlite3.Connection) -> None:
    connessione.execute(
        """
        CREATE TABLE corpi (
            id          INTEGER PRIMARY KEY,
            scatto_id   INTEGER NOT NULL REFERENCES scatti(id) ON DELETE CASCADE,
            file_id     INTEGER REFERENCES file_media(id) ON DELETE SET NULL,
            fotogramma  INTEGER NOT NULL DEFAULT 0,
            riquadro    TEXT NOT NULL,
            area        REAL NOT NULL,
            sicurezza   REAL NOT NULL,
            maschera    BLOB,
            punti       BLOB,
            volto_id    INTEGER REFERENCES volti(id) ON DELETE SET NULL,
            vicinanza   REAL,
            modello     TEXT NOT NULL,
            versione    TEXT NOT NULL,
            trovato_il  TEXT NOT NULL
        )
        """
    )
    connessione.execute("CREATE INDEX corpi_per_scatto ON corpi(scatto_id, fotogramma)")
    connessione.execute("CREATE INDEX corpi_per_volto ON corpi(volto_id)")
    connessione.execute(
        """
        CREATE TABLE corpi_guardati (
            scatto_id   INTEGER NOT NULL REFERENCES scatti(id) ON DELETE CASCADE,
            modello     TEXT NOT NULL,
            versione    TEXT NOT NULL,
            quanti      INTEGER NOT NULL DEFAULT 0,
            guardato_il TEXT NOT NULL,
            PRIMARY KEY (scatto_id, modello, versione)
        )
        """
    )


def _versione_46(connessione: sqlite3.Connection) -> None:
    connessione.execute(
        """
        CREATE TABLE aspetti (
            corpo_id  INTEGER NOT NULL REFERENCES corpi(id) ON DELETE CASCADE,
            modello   TEXT NOT NULL,
            parti     INTEGER NOT NULL,
            vettore   BLOB NOT NULL,
            visibili  BLOB,
            PRIMARY KEY (corpo_id, modello)
        )
        """
    )


def _versione_47(connessione: sqlite3.Connection) -> None:
    connessione.execute(
        """
        CREATE TABLE obiettivi (
            scatto_id        INTEGER PRIMARY KEY REFERENCES scatti(id) ON DELETE CASCADE,
            fonte            TEXT NOT NULL,
            campo_verticale  REAL NOT NULL,
            rollio           REAL,
            beccheggio       REAL,
            distorsione      REAL,
            versione         TEXT NOT NULL,
            guardato_il      TEXT NOT NULL
        )
        """
    )


def _versione_48(connessione: sqlite3.Connection) -> None:
    connessione.execute(
        "CREATE INDEX IF NOT EXISTS segnalazioni_per_scatto "
        "ON segnalazioni(scatto_id, tipo, risolta)")
    for doppione in ("etichette_per_scatto", "impronte_per_scatto", "diario_per_telefono",
                     "cambiamenti_da_mandare"):
        connessione.execute(f"DROP INDEX IF EXISTS {doppione}")


def _versione_49(connessione: sqlite3.Connection) -> None:
    connessione.execute(
        """
        CREATE TABLE corpi_delle_persone (
            corpo_id    INTEGER NOT NULL REFERENCES corpi(id) ON DELETE CASCADE,
            persona_id  INTEGER NOT NULL REFERENCES persone(id) ON DELETE CASCADE,
            risposta    TEXT NOT NULL CHECK (risposta IN ('si','no')),
            deciso_il   TEXT NOT NULL,
            PRIMARY KEY (corpo_id, persona_id)
        )
        """
    )
    connessione.execute(
        "CREATE INDEX corpi_delle_persone_per_persona ON corpi_delle_persone(persona_id, risposta)")
    connessione.execute(
        """
        CREATE TABLE proposte_dei_corpi (
            corpo_id         INTEGER NOT NULL REFERENCES corpi(id) ON DELETE CASCADE,
            persona_id       INTEGER NOT NULL REFERENCES persone(id) ON DELETE CASCADE,
            scatto_id        INTEGER NOT NULL REFERENCES scatti(id) ON DELETE CASCADE,
            punteggio        REAL NOT NULL,
            perche           TEXT NOT NULL,
            simile_corpo_id  INTEGER REFERENCES corpi(id) ON DELETE SET NULL,
            calcolata_il     TEXT NOT NULL,
            PRIMARY KEY (corpo_id, persona_id)
        )
        """
    )
    connessione.execute(
        "CREATE INDEX proposte_dei_corpi_per_scatto ON proposte_dei_corpi(scatto_id)")
    connessione.execute(
        "CREATE INDEX proposte_dei_corpi_per_persona ON proposte_dei_corpi(persona_id)")
    connessione.execute(
        """
        CREATE TABLE pesi_delle_persone (
            persona_id          INTEGER PRIMARY KEY REFERENCES persone(id) ON DELETE CASCADE,
            pesi                TEXT NOT NULL,
            vestiti_giorni      REAL NOT NULL,
            corporatura_giorni  REAL NOT NULL,
            si                  INTEGER NOT NULL,
            no                  INTEGER NOT NULL,
            esempi              INTEGER NOT NULL,
            firma               TEXT NOT NULL,
            imparati_il         TEXT NOT NULL
        )
        """
    )
    connessione.execute(
        """
        CREATE TABLE parole_dei_vestiti (
            modello  TEXT NOT NULL,
            frase    TEXT NOT NULL,
            vettore  BLOB NOT NULL,
            PRIMARY KEY (modello, frase)
        )
        """
    )


def _versione_50(connessione: sqlite3.Connection) -> None:
    connessione.execute(
        """
        DELETE FROM corpi
        WHERE sicurezza < 0.65
          AND NOT EXISTS (SELECT 1 FROM corpi_delle_persone d WHERE d.corpo_id = corpi.id)
        """
    )
    connessione.execute(
        """
        UPDATE corpi_guardati SET quanti = (
            SELECT count(*) FROM corpi c
            WHERE c.scatto_id = corpi_guardati.scatto_id
              AND c.modello = corpi_guardati.modello AND c.versione = corpi_guardati.versione)
        """
    )


def _versione_51(connessione: sqlite3.Connection) -> None:
    connessione.execute("ALTER TABLE corpi ADD COLUMN punti_scala REAL NOT NULL DEFAULT 1")


def _versione_52(connessione: sqlite3.Connection) -> None:
    connessione.execute(
        """
        CREATE TABLE stanze (
            posto_id      INTEGER PRIMARY KEY REFERENCES posti(id) ON DELETE CASCADE,
            stato         TEXT NOT NULL CHECK (stato IN ('fatta','non_riuscita')),
            file          TEXT NOT NULL,
            versione      TEXT NOT NULL,
            foto_usate    INTEGER NOT NULL,
            foto_viste    INTEGER NOT NULL,
            punti         INTEGER NOT NULL,
            larga         REAL,
            lunga         REAL,
            alta          REAL,
            metri         REAL,
            perche        TEXT,
            costruita_il  TEXT NOT NULL
        )
        """
    )
    connessione.execute(
        """
        CREATE TABLE stanze_foto (
            posto_id     INTEGER NOT NULL REFERENCES stanze(posto_id) ON DELETE CASCADE,
            scatto_id    INTEGER NOT NULL REFERENCES scatti(id) ON DELETE CASCADE,
            usata        INTEGER NOT NULL DEFAULT 0,
            ordine       INTEGER,
            macchina     BLOB NOT NULL,
            campo        REAL NOT NULL,
            centro_x     REAL NOT NULL,
            centro_y     REAL NOT NULL,
            proporzione  REAL NOT NULL,
            allungo      REAL NOT NULL DEFAULT 1.0,
            messa_il     TEXT NOT NULL,
            PRIMARY KEY (posto_id, scatto_id)
        )
        """
    )
    connessione.execute("CREATE INDEX stanze_foto_per_scatto ON stanze_foto(scatto_id)")
    connessione.execute(
        """
        CREATE TABLE superfici (
            corpo_id  INTEGER PRIMARY KEY REFERENCES corpi(id) ON DELETE CASCADE,
            versione  TEXT NOT NULL,
            file      TEXT NOT NULL,
            vertici   INTEGER NOT NULL,
            visti     INTEGER NOT NULL,
            fatta_il  TEXT NOT NULL
        )
        """
    )


def _parti_della_cartella(percorso: str, cartella: str) -> int | None:
    tipo = PureWindowsPath if "\\" in cartella or cartella[1:2] == ":" else PurePosixPath
    base = tipo(cartella)
    return len(base.parts) if tipo(percorso).is_relative_to(base) else None


def _versione_53(connessione: sqlite3.Connection) -> None:
    connessione.execute(
        "UPDATE scatti SET latitudine = NULL, longitudine = NULL "
        "WHERE (latitudine IS NOT NULL AND (typeof(latitudine) NOT IN ('real', 'integer') "
        "OR latitudine > 90 OR latitudine < -90)) "
        "OR (longitudine IS NOT NULL AND (typeof(longitudine) NOT IN ('real', 'integer') "
        "OR longitudine > 180 OR longitudine < -180))")
    connessione.execute(
        "UPDATE file_media SET latitudine = NULL, longitudine = NULL "
        "WHERE (latitudine IS NOT NULL AND (typeof(latitudine) NOT IN ('real', 'integer') "
        "OR latitudine > 90 OR latitudine < -90)) "
        "OR (longitudine IS NOT NULL AND (typeof(longitudine) NOT IN ('real', 'integer') "
        "OR longitudine > 180 OR longitudine < -180))")
    connessione.execute(
        "UPDATE luoghi SET "
        "centro_lat = (SELECT avg(s.latitudine) FROM scatti s WHERE s.luogo_id = luoghi.id "
        "AND s.latitudine IS NOT NULL AND s.longitudine IS NOT NULL), "
        "centro_lon = (SELECT avg(s.longitudine) FROM scatti s WHERE s.luogo_id = luoghi.id "
        "AND s.latitudine IS NOT NULL AND s.longitudine IS NOT NULL), "
        "quanti = (SELECT count(*) FROM scatti s WHERE s.luogo_id = luoghi.id "
        "AND s.latitudine IS NOT NULL AND s.longitudine IS NOT NULL), "
        "raggio_metri = 0 "
        "WHERE (typeof(centro_lat) NOT IN ('real', 'integer') OR centro_lat > 90 "
        "OR centro_lat < -90 OR typeof(centro_lon) NOT IN ('real', 'integer') "
        "OR centro_lon > 180 OR centro_lon < -180) "
        "AND EXISTS (SELECT 1 FROM scatti s WHERE s.luogo_id = luoghi.id "
        "AND s.latitudine IS NOT NULL AND s.longitudine IS NOT NULL)")
    connessione.execute(
        "UPDATE scatti SET luogo_id = NULL WHERE luogo_id IN (SELECT id FROM luoghi "
        "WHERE typeof(centro_lat) NOT IN ('real', 'integer') OR centro_lat > 90 "
        "OR centro_lat < -90 OR typeof(centro_lon) NOT IN ('real', 'integer') "
        "OR centro_lon > 180 OR centro_lon < -180)")
    connessione.execute(
        "DELETE FROM luoghi WHERE typeof(centro_lat) NOT IN ('real', 'integer') "
        "OR centro_lat > 90 OR centro_lat < -90 OR typeof(centro_lon) NOT IN ('real', 'integer') "
        "OR centro_lon > 180 OR centro_lon < -180")

    cartelle = [(riga[0], riga[1]) for riga in connessione.execute(
        "SELECT id, percorso FROM cartelle_sorgente")]
    ultimo = 0
    while True:
        righe = connessione.execute(
            "SELECT id, percorso, cartella_id FROM percorsi "
            "WHERE id > ? AND cartella_id IS NOT NULL ORDER BY id LIMIT 1000",
            (ultimo,)).fetchall()
        if not righe:
            break
        cambi = []
        for riga in righe:
            scelta, lunghezza = None, -1
            for cartella_id, cartella in cartelle:
                parti = _parti_della_cartella(riga[1], cartella)
                if parti is not None and parti > lunghezza:
                    scelta, lunghezza = cartella_id, parti
            if scelta != riga[2]:
                cambi.append((scelta, riga[0]))
        connessione.executemany("UPDATE percorsi SET cartella_id = ? WHERE id = ?", cambi)
        ultimo = righe[-1][0]


def _versione_54(connessione: sqlite3.Connection) -> None:
    connessione.execute(
        "CREATE INDEX IF NOT EXISTS cambiamenti_per_scatto ON cambiamenti"
        "(macchina_id, cosa, scatto_id, nodo_id, seriale)")
    connessione.execute(
        "CREATE INDEX IF NOT EXISTS cambiamenti_per_nodo ON cambiamenti"
        "(macchina_id, cosa, nodo_id, avvenuto_il)")


def _versione_55(connessione: sqlite3.Connection) -> None:
    connessione.execute("""
        CREATE TABLE IF NOT EXISTS salute_file (
            percorso_id    INTEGER PRIMARY KEY REFERENCES percorsi(id) ON DELETE CASCADE,
            file_id        INTEGER NOT NULL REFERENCES file_media(id) ON DELETE CASCADE,
            percorso       TEXT NOT NULL,
            esito          TEXT NOT NULL CHECK (esito IN
                               ('sano','rovinato','cambiato','illeggibile','assente')),
            dimensione     INTEGER,
            toccato_ns     INTEGER,
            controllato_il TEXT NOT NULL,
            dettaglio      TEXT,
            riparato_il    TEXT
        )""")
    connessione.execute(
        "CREATE INDEX IF NOT EXISTS salute_per_esito ON salute_file(esito)")
    connessione.execute(
        "CREATE INDEX IF NOT EXISTS salute_per_data ON salute_file(controllato_il)")
    connessione.execute(
        "CREATE INDEX IF NOT EXISTS salute_per_file ON salute_file(file_id)")


def _versione_56(connessione: sqlite3.Connection) -> None:
    connessione.execute(
        "CREATE INDEX IF NOT EXISTS migliorie_per_file ON migliorie(file_id, stato, id)")
    connessione.execute(
        "CREATE INDEX IF NOT EXISTS migliorie_per_scatto ON migliorie(scatto_id, stato, id)")


def _versione_57(connessione: sqlite3.Connection) -> None:
    connessione.execute(
        "CREATE INDEX IF NOT EXISTS volti_per_scatto_e_modello "
        "ON volti(scatto_id, modello, versione)")
    connessione.execute("DROP INDEX IF EXISTS volti_per_scatto")
    connessione.execute(
        "CREATE INDEX IF NOT EXISTS persone_negli_scatti_per_persona "
        "ON persone_negli_scatti(persona_id, scatto_id)")


def _versione_58(connessione: sqlite3.Connection) -> None:
    connessione.execute(
        "CREATE INDEX IF NOT EXISTS percorsi_per_nome ON percorsi(nome COLLATE NOCASE)")
    connessione.execute(
        "CREATE INDEX IF NOT EXISTS file_per_data_locale ON file_media(data_locale)")


def _versione_59(connessione: sqlite3.Connection) -> None:
    connessione.execute(
        """
        CREATE TABLE aiuti (
            id           INTEGER PRIMARY KEY,
            posto_id     INTEGER REFERENCES posti(id) ON DELETE CASCADE,
            persona_id   INTEGER REFERENCES persone(id) ON DELETE CASCADE,
            file         TEXT NOT NULL,
            impronta     TEXT NOT NULL,
            origine      TEXT NOT NULL DEFAULT 'foto' CHECK (origine IN ('foto','video')),
            larghezza    INTEGER NOT NULL,
            altezza      INTEGER NOT NULL,
            scattata_il  TEXT,
            messa_il     TEXT NOT NULL,
            guardato     TEXT,
            CHECK ((posto_id IS NULL) <> (persona_id IS NULL))
        )
        """
    )
    connessione.execute("CREATE UNIQUE INDEX aiuti_del_posto ON aiuti(posto_id, impronta) "
                        "WHERE posto_id IS NOT NULL")
    connessione.execute("CREATE UNIQUE INDEX aiuti_della_persona ON aiuti(persona_id, impronta) "
                        "WHERE persona_id IS NOT NULL")
    connessione.execute(
        """
        CREATE TABLE aspetti_di_aiuto (
            aiuto_id  INTEGER NOT NULL REFERENCES aiuti(id) ON DELETE CASCADE,
            modello   TEXT NOT NULL,
            parti     INTEGER NOT NULL,
            vettore   BLOB NOT NULL,
            visibili  BLOB,
            PRIMARY KEY (aiuto_id, modello)
        )
        """
    )
    connessione.execute("ALTER TABLE stanze ADD COLUMN aiuti_visti INTEGER NOT NULL DEFAULT 0")
    connessione.execute("ALTER TABLE stanze ADD COLUMN versioni TEXT")
    connessione.execute("ALTER TABLE stanze ADD COLUMN dettaglio TEXT")


def _versione_60(connessione: sqlite3.Connection) -> None:
    connessione.execute(
        """
        CREATE TABLE ritocchi (
            id                 INTEGER PRIMARY KEY,
            file_id            INTEGER NOT NULL
                               REFERENCES file_media(id) ON DELETE CASCADE,
            scatto_id          INTEGER REFERENCES scatti(id) ON DELETE SET NULL,
            genere             TEXT NOT NULL CHECK (genere IN ('pixela','togli')),
            cosa               TEXT NOT NULL CHECK (cosa IN ('volto','persona','oggetto')),
            volto_id           INTEGER REFERENCES volti(id) ON DELETE SET NULL,
            corpo_id           INTEGER REFERENCES corpi(id) ON DELETE SET NULL,
            larghezza          INTEGER NOT NULL,
            altezza            INTEGER NOT NULL,
            maschera           BLOB NOT NULL,
            misura             REAL NOT NULL,
            quadretto          INTEGER,
            origine_x          INTEGER,
            origine_y          INTEGER,
            scelta             TEXT,
            traccia            TEXT,
            stato              TEXT NOT NULL DEFAULT 'fatto'
                               CHECK (stato IN ('in_coda','in_lavoro','da_rivedere',
                                                'fatto','tolto','rifiutato','fallito')),
            risultato          TEXT,
            impronta_risultato TEXT,
            guasto             TEXT,
            messo_il           TEXT NOT NULL,
            fatto_il           TEXT,
            tolto_il           TEXT
        )
        """
    )
    connessione.execute("CREATE INDEX ritocchi_del_file ON ritocchi(file_id, stato, id)")
    connessione.execute("CREATE INDEX ritocchi_per_stato ON ritocchi(stato, id)")
    connessione.execute(
        """
        CREATE TABLE ritoccate (
            file_id          INTEGER PRIMARY KEY
                             REFERENCES file_media(id) ON DELETE CASCADE,
            stato            TEXT NOT NULL
                             CHECK (stato IN ('in_scambio','fatta','in_ritorno')),
            percorso_copia   TEXT NOT NULL,
            impronta_copia   TEXT,
            percorso_base    TEXT NOT NULL,
            impronta_base    TEXT NOT NULL,
            base_e           TEXT NOT NULL CHECK (base_e IN ('originale','migliorata')),
            miglioria_id     INTEGER REFERENCES migliorie(id) ON DELETE SET NULL,
            in_preparazione  TEXT,
            impronta_nuova   TEXT,
            fatta_il         TEXT,
            guasto           TEXT
        )
        """
    )
    connessione.execute(
        "CREATE UNIQUE INDEX ritoccate_per_impronta ON ritoccate(impronta_copia) "
        "WHERE impronta_copia IS NOT NULL")
    connessione.execute(
        "CREATE INDEX ritoccate_in_preparazione ON ritoccate(impronta_nuova) "
        "WHERE impronta_nuova IS NOT NULL")
    connessione.execute("CREATE INDEX ritoccate_per_stato ON ritoccate(stato)")


def _versione_61(connessione: sqlite3.Connection) -> None:
    connessione.execute(
        "CREATE INDEX IF NOT EXISTS ritocchi_per_volto ON ritocchi(volto_id) "
        "WHERE volto_id IS NOT NULL")
    connessione.execute(
        "CREATE INDEX IF NOT EXISTS ritocchi_per_corpo ON ritocchi(corpo_id) "
        "WHERE corpo_id IS NOT NULL")
    connessione.execute(
        "CREATE INDEX IF NOT EXISTS ritocchi_per_scatto ON ritocchi(scatto_id) "
        "WHERE scatto_id IS NOT NULL")



def _versione_62(connessione: sqlite3.Connection) -> None:
    connessione.execute(
        """
        CREATE TABLE seguiti (
            id           INTEGER PRIMARY KEY,
            file_id      INTEGER NOT NULL REFERENCES file_media(id) ON DELETE CASCADE,
            cosa         TEXT NOT NULL CHECK (cosa IN ('volto','persona','oggetto')),
            stato        TEXT NOT NULL DEFAULT 'da_seguire'
                         CHECK (stato IN ('da_seguire','in_coda','in_lavoro','seguito',
                                          'fermato','fallito')),
            impronta     TEXT NOT NULL,
            larghezza    INTEGER NOT NULL,
            altezza      INTEGER NOT NULL,
            quanti       INTEGER NOT NULL,
            istanti      BLOB,
            dove         TEXT,
            guasto       TEXT,
            messo_il     TEXT NOT NULL,
            seguito_il   TEXT
        )
        """
    )
    connessione.execute("CREATE INDEX seguiti_del_file ON seguiti(file_id, id)")
    connessione.execute("CREATE INDEX seguiti_per_stato ON seguiti(stato, id)")
    connessione.execute(
        """
        CREATE TABLE seguiti_scelte (
            seguito_id   INTEGER NOT NULL REFERENCES seguiti(id) ON DELETE CASCADE,
            fotogramma   INTEGER NOT NULL,
            versione     INTEGER NOT NULL,
            maschera     BLOB NOT NULL,
            messa_il     TEXT NOT NULL,
            PRIMARY KEY (seguito_id, fotogramma)
        ) WITHOUT ROWID
        """
    )
    connessione.execute(
        """
        CREATE TABLE seguiti_fotogrammi (
            seguito_id   INTEGER NOT NULL REFERENCES seguiti(id) ON DELETE CASCADE,
            fotogramma   INTEGER NOT NULL,
            da           INTEGER NOT NULL,
            versione     INTEGER NOT NULL,
            maschera     BLOB,
            sicurezza    REAL NOT NULL,
            PRIMARY KEY (seguito_id, fotogramma)
        ) WITHOUT ROWID
        """
    )
    connessione.execute(
        "ALTER TABLE ritocchi ADD COLUMN seguito_id INTEGER REFERENCES seguiti(id) "
        "ON DELETE SET NULL")
    connessione.execute(
        "CREATE INDEX IF NOT EXISTS ritocchi_per_seguito ON ritocchi(seguito_id) "
        "WHERE seguito_id IS NOT NULL")


def _versione_63(connessione: sqlite3.Connection) -> None:
    connessione.execute(
        """
        CREATE TABLE ritocchi_lavori (
            id           INTEGER PRIMARY KEY,
            scatto_id    INTEGER NOT NULL REFERENCES scatti(id) ON DELETE CASCADE,
            stato        TEXT NOT NULL DEFAULT 'in_coda'
                         CHECK (stato IN ('in_coda','in_lavoro','da_rivedere','in_scambio',
                                          'fatto','rifiutato','fallito')),
            versione     INTEGER NOT NULL DEFAULT 1,
            rifatto      INTEGER NOT NULL DEFAULT 0,
            stima        INTEGER,
            secondi      REAL,
            guasto       TEXT,
            messo_il     TEXT NOT NULL,
            iniziato_il  TEXT,
            finito_il    TEXT,
            deciso_il    TEXT
        )
        """
    )
    connessione.execute("CREATE INDEX ritocchi_lavori_per_stato ON ritocchi_lavori(stato, id)")
    connessione.execute(
        "CREATE INDEX ritocchi_lavori_per_scatto ON ritocchi_lavori(scatto_id, stato)")
    connessione.execute(
        """
        CREATE TABLE ritocchi_lavori_file (
            lavoro_id        INTEGER NOT NULL
                             REFERENCES ritocchi_lavori(id) ON DELETE CASCADE,
            file_id          INTEGER NOT NULL REFERENCES file_media(id) ON DELETE CASCADE,
            pronta           TEXT,
            impronta_pronta  TEXT,
            impronta_base    TEXT,
            fotogrammi       INTEGER,
            PRIMARY KEY (lavoro_id, file_id)
        ) WITHOUT ROWID
        """
    )
    connessione.execute(
        "CREATE INDEX ritocchi_lavori_file_per_file ON ritocchi_lavori_file(file_id)")
    connessione.execute(
        "ALTER TABLE ritocchi ADD COLUMN lavoro_id INTEGER REFERENCES ritocchi_lavori(id) "
        "ON DELETE SET NULL")
    connessione.execute(
        "ALTER TABLE ritocchi ADD COLUMN gemello_id INTEGER REFERENCES ritocchi(id) "
        "ON DELETE SET NULL")
    connessione.execute(
        "CREATE INDEX ritocchi_per_lavoro ON ritocchi(lavoro_id, stato) "
        "WHERE lavoro_id IS NOT NULL")
    connessione.execute(
        "CREATE INDEX ritocchi_per_gemello ON ritocchi(gemello_id) WHERE gemello_id IS NOT NULL")


def _versione_64(connessione: sqlite3.Connection) -> None:
    connessione.execute(
        "ALTER TABLE ritocchi ADD COLUMN rifa_id INTEGER REFERENCES ritocchi(id) "
        "ON DELETE SET NULL")
    connessione.execute(
        "CREATE INDEX ritocchi_per_rifatto ON ritocchi(rifa_id) WHERE rifa_id IS NOT NULL")


def _versione_65(connessione: sqlite3.Connection) -> None:
    connessione.execute(
        "ALTER TABLE ritoccate ADD COLUMN da_rifare INTEGER NOT NULL DEFAULT 0")


def _versione_66(connessione: sqlite3.Connection) -> None:
    connessione.execute(
        """
        CREATE TABLE persone_tolte (
            id          INTEGER PRIMARY KEY,
            ritocco_id  INTEGER NOT NULL,
            scatto_id   INTEGER NOT NULL REFERENCES scatti(id) ON DELETE CASCADE,
            dove        TEXT NOT NULL CHECK (dove IN ('volto','corpo','scatto')),
            riga_id     INTEGER NOT NULL,
            persona_id  INTEGER REFERENCES persone(id) ON DELETE SET NULL,
            com_era     TEXT NOT NULL DEFAULT '{}'
        )
        """
    )
    connessione.execute("CREATE INDEX persone_tolte_per_scatto ON persone_tolte(scatto_id)")
    connessione.execute("CREATE INDEX persone_tolte_per_riga ON persone_tolte(dove, riga_id)")


def _versione_67(connessione: sqlite3.Connection) -> None:
    connessione.execute(
        """
        CREATE TABLE sfide_togli (
            lavoro_id   INTEGER NOT NULL REFERENCES ritocchi_lavori(id) ON DELETE CASCADE,
            file_id     INTEGER NOT NULL,
            genere      TEXT NOT NULL CHECK (genere IN ('foto','video')),
            motore_a    TEXT NOT NULL,
            motore_b    TEXT NOT NULL,
            sinistra    TEXT NOT NULL CHECK (sinistra IN ('A','B')),
            pronta_b    TEXT,
            impronta_b  TEXT,
            toppe_b     TEXT NOT NULL DEFAULT '{}',
            voto        TEXT CHECK (voto IN ('A','B','pari','nessuna')),
            messa_il    TEXT NOT NULL,
            votata_il   TEXT,
            PRIMARY KEY (lavoro_id, file_id)
        )
        """
    )
    connessione.execute("CREATE INDEX sfide_togli_per_genere ON sfide_togli(genere, voto)")


def _versione_68(connessione: sqlite3.Connection) -> None:
    connessione.execute(
        "ALTER TABLE migliorie ADD COLUMN nell_archivio INTEGER NOT NULL DEFAULT 0")


MIGRAZIONI: list[Migrazione] = [
    Migrazione(1, "schema iniziale: file, scatti, percorsi, nodi, etichette", _versione_1),
    Migrazione(2, "i dispositivi autorizzati sulla rete di casa", _versione_2),
    Migrazione(3, "le impronte numeriche e le misure", _versione_3),
    Migrazione(4, "le fotografie dell'albero", _versione_4),
    Migrazione(5, "le persone e i volti", _versione_5),
    Migrazione(6, "i luoghi: le coordinate diventano un posto con un nome",
               _versione_6),
    Migrazione(7, "i volti di riferimento: facce insegnate, non archiviate",
               _versione_7),
    Migrazione(8, "il ripasso: cercare all'indietro un nodo nato tardi",
               _versione_8),
    Migrazione(9, "i telefoni, i travasi e cosa c'è dentro ogni pacchetto",
               _versione_9),
    Migrazione(10, "cuori, raccolte e diario: quello che torna dal telefono",
               _versione_10),
    Migrazione(11, "il registro delle modifiche: chi ha fatto cosa, e in che ordine",
               _versione_11),
    Migrazione(12, "cosa so che l'altra macchina ha già", _versione_12),
    Migrazione(13, "da dove partiva un nodo rinominato o spostato", _versione_13),
    Migrazione(14, "quando un'impostazione è stata cambiata", _versione_14),
    Migrazione(15, "la griglia adattiva: una foto guardata anche a pezzi",
               _versione_15),
    Migrazione(16, "le parole scritte dentro le fotografie", _versione_16),
    Migrazione(17, "il cuore e la stella messi col mouse", _versione_17),
    Migrazione(18, "la seconda impronta: i doppioni ricompressi", _versione_18),
    Migrazione(19, "i gruppi di doppioni contati, e cosa ne ho deciso",
               _versione_19),
    Migrazione(20, "l'indice per «quante ne sono arrivate da allora»",
               _versione_20),
    Migrazione(21, "quattro indici per le letture larghe che restavano",
               _versione_21),
    Migrazione(22, "due indici allargati: l'ultimo tocco e il riassunto delle "
               "passate", _versione_22),
    Migrazione(23, "ogni scatto sa da quale importazione è arrivato",
               _versione_23),
    Migrazione(24, "quattro indici per i conti che stanno su ogni schermata",
               _versione_24),
    Migrazione(25, "l'indice della coda dell'etichettatura, allargato",
               _versione_25),
    Migrazione(26, "lo stesso indice, con le colonne nell'ordine che non "
               "confonde la galleria", _versione_26),
    Migrazione(27, "il miglioramento: la coda, la revisione e le cartelle "
               "dei riferimenti", _versione_27),
    Migrazione(28, "la sfida alla cieca fra SeedVR2 e LucidFlux", _versione_28),
    Migrazione(29, "i video girati dal telefono, da raddrizzare", _versione_29),
    Migrazione(30, "i video girati, ripassati per rifare impronte e volti", _versione_30),
    Migrazione(31, "il controllo di fedeltà del miglioramento", _versione_31),
    Migrazione(32, "le foto live rimaste staccate e le copertine nere dei video", _versione_32),
    Migrazione(33, "il colore medio di ogni miniatura, per la galleria che arriva", _versione_33),
    Migrazione(34, "i video presi per foto e le foto live con lo stesso nome del video",
               _versione_34),
    Migrazione(35, "gli scatti già guardati in cerca di volti, anche senza facce",
               _versione_35),
    Migrazione(36, "una descrizione breve di ogni foto, per cercarla a parole",
               _versione_36),
    Migrazione(37, "i gruppi dell'archivio, come Snapchat, scelti all'importazione",
               _versione_37),
    Migrazione(38, "i video tornano fuori da «Da sistemare»: le scritte ora li leggono",
               _versione_38),
    Migrazione(39, "le date nascoste in altri punti dei file, rilette", _versione_39),
    Migrazione(40, "le date scritte in modi diversi e quelle delle tracce, rilette",
               _versione_40),
    Migrazione(41, "la macchina che ha fatto ogni scatto, letta anche nei file già in archivio",
               _versione_41),
    Migrazione(42, "le date prese dal nome del file o dalla data di Windows, quando dentro non c'è",
               _versione_42),
    Migrazione(43, "i luoghi ad albero, «nessuna persona» e «non so dove» su ogni scatto",
               _versione_43),
    Migrazione(44, "un genitore si può etichettare anche da solo, se lo scegli tu",
               _versione_44),
    Migrazione(45, "le persone trovate dal corpo, con i punti del corpo e il volto collegato",
               _versione_45),
    Migrazione(46, "la corporatura e i vestiti di ogni persona trovata dal corpo",
               _versione_46),
    Migrazione(47, "l'obiettivo di ogni scatto, per la figura in 3D delle persone",
               _versione_47),
    Migrazione(48, "le pagine dell'intelligenza più veloci con tante segnalazioni, "
               "e via quattro indici doppi",
               _versione_48),
    Migrazione(49, "chi è una persona senza volto: proposte dal corpo e dai vestiti, "
               "le tue risposte e quello che impara di ognuno",
               _versione_49),
    Migrazione(50, "via le persone trovate dal corpo con poca sicurezza, sotto 0,65 come dice "
               "il collaudo; restano quelle su cui hai già risposto",
               _versione_50),
    Migrazione(51, "i punti del corpo con la sicurezza vera di RTMW: quelli vecchi si rifanno",
               _versione_51),
    Migrazione(52, "le stanze in 3D: la forma di ogni luogo con almeno 5 foto, da dove è stata "
               "fatta ciascuna e il corpo vero di ogni persona",
               _versione_52),
    Migrazione(53, "via le coordinate che non stanno sul mondo, e ogni percorso torna alla "
               "sua vera cartella di partenza",
               _versione_53),
    Migrazione(54, "la sincronia trova in fretta l'ultimo gesto fatto qui su una foto",
               _versione_54),
    Migrazione(55, "la salute dei file: ogni originale si ricontrolla ogni tanto per "
               "scoprire se si è rovinato da solo", _versione_55),
    Migrazione(56, "le foto migliorate si ritrovano in fretta anche quando sono decine di "
               "migliaia", _versione_56),
    Migrazione(57, "guardare i volti di una foto non rallenta più con i volti già trovati, e "
               "le persone messe a mano si ritrovano subito", _versione_57),
    Migrazione(58, "le foto live si ritrovano in fretta all'importazione, anche con "
               "centinaia di migliaia di file", _versione_58),
    Migrazione(59, "le foto di aiuto: caricate per migliorare una stanza in 3D o una persona, "
               "senza entrare nella galleria", _versione_59),
    Migrazione(60, "i ritocchi: volti pixelati e cose tolte, con la copia al posto dello "
               "scatto e l'originale in «Originali»", _versione_60),
    Migrazione(61, "cancellare volti, corpi e scatti non rilegge più tutti i ritocchi",
               _versione_61),
    Migrazione(62, "nei video si segue la parte scelta, fotogramma per fotogramma",
               _versione_62),
    Migrazione(63, "la coda del ritocco: i video e le foto live si pixelano di notte e "
               "poi li approvi", _versione_63),
    Migrazione(64, "prima si migliora, poi si ritocca: il pixelato si rifà sopra la versione "
               "migliorata", _versione_64),
    Migrazione(65, "la foto ritoccata e poi migliorata si ripixela sopra la migliorata, "
               "anche se il programma si spegne a metà", _versione_65),
    Migrazione(66, "chi togli da uno scatto non conta più fra le sue foto, e torna se togli "
               "il ritocco", _versione_66),
    Migrazione(67, "i due migliori modelli per togliere si sfidano alla cieca sui tuoi scatti",
               _versione_67),
    Migrazione(68, "il sì al miglioramento anche quando l'originale è solo nell'Archivio "
               "sicuro", _versione_68),
]


def versione_attuale(connessione: sqlite3.Connection) -> int:
    return int(database.valore(connessione, "PRAGMA user_version", predefinito=0))


def da_applicare(connessione: sqlite3.Connection) -> list[Migrazione]:
    corrente = versione_attuale(connessione)
    return [m for m in MIGRAZIONI if m.versione > corrente]


def aggiorna(connessione: sqlite3.Connection) -> list[Migrazione]:
    if versione_attuale(connessione) > VERSIONE_SCHEMA:
        raise DatabaseIncoerente(
            "Questo archivio è stato scritto da una versione più nuova del "
            "programma. Aggiorna il programma prima di aprirlo: aprirlo così "
            "com'è rischierebbe di rovinarlo."
        )

    mancanti = da_applicare(connessione)
    if not mancanti:
        return []

    applicate = []
    for migrazione in mancanti:
        registro.evento("archivio.migrazione_inizio", versione=migrazione.versione)
        connessione.execute("BEGIN")
        try:
            migrazione.applica(connessione)
            connessione.execute(f"PRAGMA user_version = {migrazione.versione}")
            connessione.execute("COMMIT")
        except Exception:
            connessione.execute("ROLLBACK")
            registro.errore("archivio.migrazione_fallita", versione=migrazione.versione)
            raise
        registro.evento("archivio.migrazione_fatta", versione=migrazione.versione)
        applicate.append(migrazione)
    return applicate
