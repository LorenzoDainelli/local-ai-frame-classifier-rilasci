from __future__ import annotations

import sqlite3
from pathlib import Path

from officina import registro
from officina.archivio.database import adesso, inserisci, tutti, uno
from officina.errori import DaRifare, ErroreOfficina, FileNonLeggibile, perche_saltato
from officina.modello import segnalazioni
from officina.modello.luoghi import coordinate_valide
from officina.sicuro.dall_archivio import (CHIUSO, CHIUSO_ADESSO, DIVERSA, NON_C_E, SI_APRE,
                                           TROVATA, DallArchivio, Ricerca, da_rifare)


def per_impronta(connessione: sqlite3.Connection, impronta: str) -> sqlite3.Row | None:
    return uno(connessione, "SELECT * FROM file_media WHERE impronta = ?", impronta)


def per_id(connessione: sqlite3.Connection, file_id: int) -> sqlite3.Row | None:
    return uno(connessione, "SELECT * FROM file_media WHERE id = ?", file_id)


def di_scatto(connessione: sqlite3.Connection, scatto_id: int) -> list[sqlite3.Row]:
    return tutti(
        connessione,
        "SELECT * FROM file_media WHERE scatto_id = ? ORDER BY ruolo DESC, id",
        scatto_id,
    )


def crea(connessione: sqlite3.Connection, impronta: str, dimensione: int,
         genere: str, dati) -> int:
    latitudine, longitudine = coordinate_valide(dati.latitudine, dati.longitudine)
    return inserisci(
        connessione,
        """
        INSERT INTO file_media
            (impronta, dimensione, genere, formato, larghezza, altezza,
             orientamento, durata_ms, identificatore_ios, data_locale,
             fuso_minuti, istante_utc, origine_data, latitudine, longitudine,
             sembra_schermata, marca, modello, aggiunto_il)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        impronta, dimensione, genere, dati.formato, dati.larghezza, dati.altezza,
        dati.orientamento, dati.durata_ms, dati.identificatore_ios, dati.data_locale,
        dati.fuso_minuti, dati.istante_utc, dati.origine_data, latitudine,
        longitudine, int(dati.sembra_schermata), dati.marca, dati.modello, adesso(),
    )


def aggiungi_percorso(connessione: sqlite3.Connection, file_id: int, percorso: Path,
                      cartella_id: int | None = None) -> tuple[int, bool]:
    testo = str(percorso)
    esistente = uno(connessione, "SELECT * FROM percorsi WHERE percorso = ?", testo)
    if esistente:
        connessione.execute(
            "UPDATE percorsi SET presente = 1, visto_il = ?, file_id = ? WHERE id = ?",
            (adesso(), file_id, esistente["id"]),
        )
        return esistente["id"], False

    nuovo = inserisci(
        connessione,
        "INSERT INTO percorsi (file_id, cartella_id, percorso, nome, visto_il) "
        "VALUES (?,?,?,?,?)",
        file_id, cartella_id, testo, percorso.name, adesso(),
    )
    return nuovo, True


def percorsi_di(connessione: sqlite3.Connection, file_id: int) -> list[sqlite3.Row]:
    return tutti(
        connessione,
        "SELECT * FROM percorsi WHERE file_id = ? ORDER BY presente DESC, id", file_id
    )


def percorso_migliore(connessione: sqlite3.Connection, file_id: int, *,
                      anche_dall_archivio: bool = False) -> Path | DallArchivio | None:
    for riga in percorsi_di(connessione, file_id):
        percorso = Path(riga["percorso"])
        if percorso.exists():
            return percorso
    if anche_dall_archivio:
        return cerca_nell_archivio(connessione, file_id).trovata
    return None


def cerca_nell_archivio(connessione: sqlite3.Connection, file_id: int) -> Ricerca:
    from officina.programma import archivio_sicuro

    riga = per_id(connessione, file_id)
    if riga is None or not riga["impronta"]:
        return Ricerca(NON_C_E)
    perche, servizio = archivio_sicuro.per_le_foto()
    if servizio is None:
        return Ricerca(perche)
    percorsi = percorsi_di(connessione, file_id)
    nome = next((r["nome"] or Path(r["percorso"]).name for r in percorsi), "")
    return servizio.cerca(riga["impronta"], riga["dimensione"],
                          [r["percorso"] for r in percorsi], nome=nome or str(file_id),
                          intero=riga["genere"] == "immagine")


def casa_nell_archivio(connessione: sqlite3.Connection,
                       file_id: int) -> tuple[Path | None, str]:
    from officina.programma import archivio_sicuro

    riga = per_id(connessione, file_id)
    if riga is None or not riga["impronta"]:
        return None, NON_C_E
    perche, servizio = archivio_sicuro.per_le_foto()
    if servizio is None:
        return None, perche
    try:
        percorso, perche = servizio.casa(riga["impronta"], riga["dimensione"],
                                         [r["percorso"] for r in percorsi_di(connessione,
                                                                             file_id)])
    except ErroreOfficina as errore:
        registro.avviso("sicuro.casa_non_trovata", motivo=registro.Parola(errore.codice))
        return None, CHIUSO
    if percorso is None:
        return None, perche
    return Path(percorso), TROVATA


def date_nell_archivio(connessione: sqlite3.Connection, file_id: int,
                       percorso: Path) -> dict | None:
    from officina.programma import archivio_sicuro

    riga = per_id(connessione, file_id)
    if riga is None or not riga["impronta"]:
        return None
    _, servizio = archivio_sicuro.per_le_foto()
    if servizio is None:
        return None
    return servizio.date(riga["impronta"], riga["dimensione"], str(percorso))


def da_guardare(connessione: sqlite3.Connection,
                file_id: int) -> Path | DallArchivio | None:
    for riga in percorsi_di(connessione, file_id):
        percorso = Path(riga["percorso"])
        if percorso.exists():
            return percorso
    try:
        ricerca = cerca_nell_archivio(connessione, file_id)
    except DaRifare:
        raise
    except ErroreOfficina as errore:
        registro.avviso("sicuro.ricerca_non_riuscita", motivo=registro.Parola(errore.codice))
        raise da_rifare(CHIUSO_ADESSO) from errore
    if ricerca.perche in (CHIUSO, SI_APRE):
        raise da_rifare(CHIUSO_ADESSO)
    if ricerca.diversa:
        testo = perche_saltato(DIVERSA)
        raise FileNonLeggibile(testo[:1].upper() + testo[1:] + ".", codice=DIVERSA,
                               file_id=file_id)
    return ricerca.trovata


def da_mostrare(connessione: sqlite3.Connection, file_id: int, *,
                anche_dall_archivio: bool = False) -> tuple[Path | DallArchivio | None,
                                                            str | None]:
    ritoccata = uno(connessione,
                    "SELECT stato, percorso_copia, impronta_copia FROM ritoccate "
                    "WHERE file_id = ?", file_id)
    if ritoccata is None:
        return senza_ritocchi(connessione, file_id,
                              anche_dall_archivio=anche_dall_archivio)
    if ritoccata["stato"] == "fatta" and ritoccata["impronta_copia"]:
        percorso = Path(ritoccata["percorso_copia"])
        if percorso.exists():
            return percorso, ritoccata["impronta_copia"]
    return None, None


def da_mostrare_con_ricerca(
        connessione: sqlite3.Connection,
        file_id: int) -> tuple[Path | DallArchivio | None, str | None, Ricerca | None]:
    percorso, impronta = da_mostrare(connessione, file_id)
    ritoccata = uno(connessione, "SELECT 1 AS c FROM ritoccate WHERE file_id = ?", file_id)
    if percorso is not None or ritoccata is not None:
        return percorso, impronta, None
    ricerca = cerca_nell_archivio(connessione, file_id)
    return ricerca.trovata, None, ricerca


def da_mostrare_sotto(connessione: sqlite3.Connection, file_id: int, *,
                      anche_dall_archivio: bool = False) -> tuple[Path | DallArchivio | None,
                                                                  str | None]:
    ritoccata = uno(connessione,
                    "SELECT percorso_base, impronta_base FROM ritoccate "
                    "WHERE file_id = ? AND stato = 'fatta'", file_id)
    if ritoccata is not None:
        percorso = Path(ritoccata["percorso_base"])
        if percorso.exists():
            return percorso, ritoccata["impronta_base"]
    return senza_ritocchi(connessione, file_id, anche_dall_archivio=anche_dall_archivio)


def senza_ritocchi(connessione: sqlite3.Connection, file_id: int, *,
                   anche_dall_archivio: bool = False) -> tuple[Path | DallArchivio | None,
                                                               str | None]:
    migliorata = uno(
        connessione,
        "SELECT percorso_migliorata, impronta_migliorata FROM migliorie "
        "WHERE file_id = ? AND stato = 'approvata' ORDER BY id DESC LIMIT 1",
        file_id)
    if migliorata is not None and migliorata["percorso_migliorata"]:
        percorso = Path(migliorata["percorso_migliorata"])
        if percorso.exists():
            return percorso, migliorata["impronta_migliorata"]
    return percorso_migliore(connessione, file_id,
                             anche_dall_archivio=anche_dall_archivio), None


def percorso_da_mostrare(connessione: sqlite3.Connection, file_id: int, *,
                         anche_dall_archivio: bool = False) -> Path | DallArchivio | None:
    return da_mostrare(connessione, file_id, anche_dall_archivio=anche_dall_archivio)[0]


def collega_a_scatto(connessione: sqlite3.Connection, file_id: int, scatto_id: int,
                     ruolo: str) -> None:
    connessione.execute(
        "UPDATE file_media SET scatto_id = ?, ruolo = ? WHERE id = ?",
        (scatto_id, ruolo, file_id),
    )


def imposta_miniatura(connessione: sqlite3.Connection, file_id: int, nome: str,
                      colore: str | None = None) -> None:
    connessione.execute("UPDATE file_media SET miniatura = ?, colore = ? WHERE id = ?",
                        (nome, colore, file_id))


def senza_miniatura(connessione: sqlite3.Connection, quanti: int = 200) -> list[sqlite3.Row]:
    return tutti(
        connessione,
        "SELECT * FROM file_media WHERE miniatura IS NULL AND genere = 'immagine' "
        "ORDER BY id LIMIT ?",
        quanti,
    )


def controlla_presenza(connessione: sqlite3.Connection) -> dict:
    spariti = 0
    tornati = 0
    da_riprovare: set[int] = set()
    messi_da_parte = {
        riga["file_id"]
        for riga in segnalazioni.aperte(connessione, segnalazioni.NON_SI_APRE)
        if riga["file_id"]
    }
    for riga in tutti(connessione,
                      "SELECT p.id, p.file_id, p.percorso, p.presente, "
                      "f.dimensione FROM percorsi p "
                      "JOIN file_media f ON f.id = p.file_id"):
        try:
            misura = Path(riga["percorso"]).stat()
        except OSError:
            misura = None
        if misura is not None and not riga["presente"]:
            connessione.execute("UPDATE percorsi SET presente = 1 WHERE id = ?", (riga["id"],))
            tornati += 1
        elif misura is None and riga["presente"]:
            connessione.execute("UPDATE percorsi SET presente = 0 WHERE id = ?", (riga["id"],))
            spariti += 1
        if (misura is not None and riga["file_id"] in messi_da_parte
                and (not riga["presente"]
                     or misura.st_size != riga["dimensione"])):
            da_riprovare.add(riga["file_id"])

    rimessi_in_coda = segnalazioni.riprova_i_file(connessione,
                                                  sorted(da_riprovare))

    non_trovati = uno(
        connessione,
        "SELECT count(DISTINCT p.file_id) AS quanti FROM percorsi p "
        "WHERE p.presente = 0 AND NOT EXISTS (SELECT 1 FROM percorsi q "
        "WHERE q.file_id = p.file_id AND q.presente = 1)",
    )
    return {
        "spariti": spariti,
        "tornati": tornati,
        "rimessi_in_coda": rimessi_in_coda,
        "file_non_trovati": non_trovati["quanti"] if non_trovati else 0,
    }


def non_trovati(connessione: sqlite3.Connection) -> list[sqlite3.Row]:
    return tutti(
        connessione,
        """
        SELECT f.*, (SELECT p.nome FROM percorsi p WHERE p.file_id = f.id
                     ORDER BY p.id LIMIT 1) AS nome
        FROM file_media f
        WHERE f.id IN (SELECT file_id FROM percorsi WHERE presente = 0)
          AND NOT EXISTS (SELECT 1 FROM percorsi p
                          WHERE p.file_id = f.id AND p.presente = 1)
        ORDER BY f.id
        """,
    )
