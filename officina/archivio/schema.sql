-- ==========================================================================
-- Lo schema dell'archivio.  Versione 1 — tappa 1 (regola 335).
--
-- Tre idee reggono tutto quello che c'e' qui dentro:
--
--   * l'unita' e' lo **scatto**, non il file (regola 4): un file .HEIC e il
--     suo .MOV sono due righe in `file_media` e una sola in `scatti`, ed e'
--     su quella riga che finiranno le etichette;
--   * un file e' identificato dal **contenuto** (regola 39): l'impronta e'
--     unica, i percorsi sono tanti (regola 135) e possono sparire (regola 96);
--   * esiste **un solo tipo di nodo** (regola 25): categoria, sottocategoria e
--     oggetto sono la stessa cosa a profondita' diverse.
--
-- Gli indici ci sono da subito perche' il programma e' pensato per decine di
-- migliaia di scatti, non per i milletrecento di oggi (regola 97).
-- ==========================================================================

-- --------------------------------------------------------------------------
-- Impostazioni e stato: stanno nel database, non in un file a parte (regola 113)
-- --------------------------------------------------------------------------

CREATE TABLE impostazioni (
    chiave  TEXT PRIMARY KEY,
    valore  TEXT NOT NULL           -- sempre JSON, cosi' i tipi non si perdono
);

-- «Riaprendo il programma si torna dove si era» (regola 98).
CREATE TABLE stato (
    chiave        TEXT PRIMARY KEY,
    valore        TEXT NOT NULL,
    aggiornato_il TEXT NOT NULL
);

-- --------------------------------------------------------------------------
-- Le cartelle da cui arrivano le foto (regola 134)
-- --------------------------------------------------------------------------

CREATE TABLE cartelle_sorgente (
    id           INTEGER PRIMARY KEY,
    percorso     TEXT NOT NULL UNIQUE,
    aggiunta_il  TEXT NOT NULL,
    attiva       INTEGER NOT NULL DEFAULT 1,
    ultima_scansione TEXT
);

-- --------------------------------------------------------------------------
-- I file veri, riconosciuti dal contenuto (regola 39)
-- --------------------------------------------------------------------------

CREATE TABLE file_media (
    id                INTEGER PRIMARY KEY,
    impronta          TEXT NOT NULL UNIQUE,   -- blake2b del contenuto, esadecimale
    dimensione        INTEGER NOT NULL,
    genere            TEXT NOT NULL CHECK (genere IN ('immagine','video')),
    formato           TEXT,                   -- 'heic', 'jpeg', 'mov', ...
    larghezza         INTEGER,
    altezza           INTEGER,
    orientamento      INTEGER,                -- EXIF 1..8, applicato solo in copia (regola 52)
    durata_ms         INTEGER,
    -- L'identificatore che iOS scrive uguale nella foto e nel video della
    -- stessa live photo: e' l'indizio piu' forte dei tre (regola 4).
    identificatore_ios TEXT,
    data_locale       TEXT,                   -- 'YYYY-MM-DDTHH:MM:SS', ora del posto (regola 323)
    fuso_minuti       INTEGER,                -- scostamento dal tempo universale, NULL se ignoto
    istante_utc       TEXT,                   -- lo stesso momento in assoluto, per ordinare
    origine_data      TEXT NOT NULL DEFAULT 'assente',  -- exif | quicktime | manuale | dedotta | assente
    latitudine        REAL,
    longitudine       REAL,
    sembra_schermata  INTEGER NOT NULL DEFAULT 0,       -- regola 321
    miniatura         TEXT,                   -- nome del file in cache, NULL se non ancora fatta
    scatto_id         INTEGER REFERENCES scatti(id) ON DELETE SET NULL,
    ruolo             TEXT CHECK (ruolo IN ('principale','movimento')),
    aggiunto_il       TEXT NOT NULL
);

CREATE INDEX file_per_scatto        ON file_media(scatto_id);
CREATE INDEX file_per_identificatore ON file_media(identificatore_ios)
    WHERE identificatore_ios IS NOT NULL;
CREATE INDEX file_per_istante       ON file_media(istante_utc);

-- Lo stesso file puo' stare in due cartelle (regola 135) e puo' sparire dal
-- disco senza che le sue etichette si perdano (regola 96).
CREATE TABLE percorsi (
    id           INTEGER PRIMARY KEY,
    file_id      INTEGER NOT NULL REFERENCES file_media(id) ON DELETE CASCADE,
    cartella_id  INTEGER REFERENCES cartelle_sorgente(id) ON DELETE SET NULL,
    percorso     TEXT NOT NULL UNIQUE,
    nome         TEXT NOT NULL,
    presente     INTEGER NOT NULL DEFAULT 1,
    visto_il     TEXT NOT NULL
);

CREATE INDEX percorsi_per_file ON percorsi(file_id);

-- --------------------------------------------------------------------------
-- Gli scatti: l'unita' del sistema (regola 4)
-- --------------------------------------------------------------------------

CREATE TABLE scatti (
    id               INTEGER PRIMARY KEY,
    genere           TEXT NOT NULL CHECK (genere IN ('foto','live','video')),
    -- La data si legge solo dai metadati (regola 83) e si tiene doppia:
    -- l'ora del posto per mostrarla e raggruppare, l'istante assoluto per
    -- ordinare (regola 323).
    data_locale      TEXT,
    fuso_minuti      INTEGER,
    istante_utc      TEXT,
    giorno           TEXT,        -- 'YYYY-MM-DD' locale: il raggruppamento della regola 252
    origine_data     TEXT NOT NULL DEFAULT 'assente',
    latitudine       REAL,
    longitudine      REAL,
    larghezza        INTEGER,
    altezza          INTEGER,
    durata_ms        INTEGER,
    sembra_schermata INTEGER NOT NULL DEFAULT 0,   -- regola 321
    fuori_archivio   INTEGER NOT NULL DEFAULT 0,   -- regola 318
    nota             TEXT,                          -- regola 120
    creato_il        TEXT NOT NULL,
    visto_il         TEXT
);

CREATE INDEX scatti_per_istante ON scatti(istante_utc);
CREATE INDEX scatti_per_giorno  ON scatti(giorno);
CREATE INDEX scatti_in_archivio ON scatti(fuori_archivio, istante_utc);

-- --------------------------------------------------------------------------
-- L'albero: un solo tipo di elemento (regola 25), un solo genitore (regola 119)
-- --------------------------------------------------------------------------

CREATE TABLE nodi (
    id            INTEGER PRIMARY KEY,
    genitore_id   INTEGER REFERENCES nodi(id) ON DELETE RESTRICT,
    nome          TEXT NOT NULL,               -- liberi, accenti ed emoji inclusi (regola 159)
    criterio      TEXT,                        -- la definizione scritta del nodo (regola 138)
    soglia        REAL NOT NULL DEFAULT 0.55,  -- prudenza per nodo (regole 44, 333)
    scegline_uno  INTEGER NOT NULL DEFAULT 0,  -- regola 129
    stato         TEXT NOT NULL DEFAULT 'attivo'
                  CHECK (stato IN ('attivo','cestino','congelato')),  -- regola 149
    cestinato_il  TEXT,
    creato_il     TEXT NOT NULL,
    usi           INTEGER NOT NULL DEFAULT 0,          -- regola 122
    posizione_ferma INTEGER NOT NULL DEFAULT 0         -- regola 314
);

CREATE INDEX nodi_per_genitore ON nodi(genitore_id, nome);

-- Due fratelli non possono chiamarsi uguale (regola 221); due nodi con lo
-- stesso nome sotto rami diversi invece si' (regola 159).
CREATE UNIQUE INDEX nodi_fratelli_unici
    ON nodi(ifnull(genitore_id, -1), nome)
    WHERE stato = 'attivo';

-- --------------------------------------------------------------------------
-- Le etichette: tre stati, di cui uno non si scrive (regola 55)
--
-- «si» e «no» sono righe. «non ancora deciso» e' l'assenza della riga — ed e'
-- la ragione per cui il modello non puo' imparare per sbaglio che un'etichetta
-- non c'e' su milletrecento foto mai guardate.
--
-- Gli antenati non si scrivono (regola 36): si calcolano risalendo l'albero.
-- Cosi' spostare un nodo non tocca nessuna etichetta (regola 220) e non esiste
-- il caso «propagazione rimasta indietro».
-- --------------------------------------------------------------------------

CREATE TABLE etichette (
    id         INTEGER PRIMARY KEY,
    scatto_id  INTEGER NOT NULL REFERENCES scatti(id) ON DELETE CASCADE,
    nodo_id    INTEGER NOT NULL REFERENCES nodi(id)   ON DELETE CASCADE,
    stato      TEXT NOT NULL CHECK (stato IN ('si','no')),
    origine    TEXT NOT NULL CHECK (origine IN ('utente','sistema')),  -- regole 18, 130, 313
    sicurezza  REAL,                                   -- solo se origine = 'sistema'
    creata_il  TEXT NOT NULL,
    UNIQUE (scatto_id, nodo_id)
);

CREATE INDEX etichette_per_nodo   ON etichette(nodo_id, stato);
CREATE INDEX etichette_per_scatto ON etichette(scatto_id);

-- «Annulla immediato piu' storico datato» (regola 40).
CREATE TABLE storico_etichette (
    id          INTEGER PRIMARY KEY,
    scatto_id   INTEGER NOT NULL,
    nodo_id     INTEGER NOT NULL,
    azione      TEXT NOT NULL CHECK (azione IN ('messa','tolta','cambiata')),
    stato       TEXT,
    origine     TEXT,
    avvenuto_il TEXT NOT NULL
);

CREATE INDEX storico_per_istante ON storico_etichette(avvenuto_il);

-- --------------------------------------------------------------------------
-- L'importazione: interrompibile e riprendibile (regole 48, 277)
-- --------------------------------------------------------------------------

CREATE TABLE importazioni (
    id            INTEGER PRIMARY KEY,
    iniziata_il   TEXT NOT NULL,
    finita_il     TEXT,
    stato         TEXT NOT NULL DEFAULT 'in_corso'
                  CHECK (stato IN ('in_corso','finita','interrotta')),
    totale        INTEGER NOT NULL DEFAULT 0,
    fatti         INTEGER NOT NULL DEFAULT 0,
    saltati       INTEGER NOT NULL DEFAULT 0,
    nuovi_scatti  INTEGER NOT NULL DEFAULT 0,
    coppie_live   INTEGER NOT NULL DEFAULT 0,
    gia_presenti  INTEGER NOT NULL DEFAULT 0,
    ms_per_file   REAL                       -- misurato, non stimato (regola 162)
);

-- La coda e' scritta su disco: e' cio' che permette di dire «riprendo dallo
-- scatto 812 di 1300» dopo un blackout (regola 277).
CREATE TABLE coda_importazione (
    id               INTEGER PRIMARY KEY,
    importazione_id  INTEGER NOT NULL REFERENCES importazioni(id) ON DELETE CASCADE,
    percorso         TEXT NOT NULL,
    dimensione       INTEGER NOT NULL DEFAULT 0,
    stato            TEXT NOT NULL DEFAULT 'in_attesa'
                     CHECK (stato IN ('in_attesa','fatto','saltato')),
    UNIQUE (importazione_id, percorso)
);

CREATE INDEX coda_da_fare ON coda_importazione(importazione_id, stato);

-- «Nessun file sparisce in silenzio» (regole 53, 279): ogni riga ha il suo motivo.
CREATE TABLE non_importati (
    id          INTEGER PRIMARY KEY,
    percorso    TEXT NOT NULL UNIQUE,
    motivo      TEXT NOT NULL,     -- codice breve, per il registro
    dettaglio   TEXT,              -- frase in italiano, per l'utente
    tentato_il  TEXT NOT NULL
);

-- --------------------------------------------------------------------------
-- Le segnalazioni: il programma dice e non tocca (regole 135, 280, 321, 87)
-- --------------------------------------------------------------------------

CREATE TABLE segnalazioni (
    id         INTEGER PRIMARY KEY,
    tipo       TEXT NOT NULL,      -- doppione_percorso | schermata | senza_data | coppia_incerta
    scatto_id  INTEGER REFERENCES scatti(id) ON DELETE CASCADE,
    file_id    INTEGER REFERENCES file_media(id) ON DELETE CASCADE,
    dettaglio  TEXT,
    risolta    INTEGER NOT NULL DEFAULT 0,
    creata_il  TEXT NOT NULL
);

CREATE INDEX segnalazioni_aperte ON segnalazioni(tipo, risolta);
