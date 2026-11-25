from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from pathlib import Path

from officina import registro
from officina.archivio.database import adesso, inserisci, tutti, uno
from officina.importazione import impronta as impronta_file, metadati, miniature, scansione
from officina.miglioria import date
from officina.modello import file_media, scatti
from officina.ritocco import taglio

SOLO_NELL_ARCHIVIO = ("Questo video c'è solo nell'Archivio sicuro: per ora si tagliano solo "
                      "i video che sono anche sul disco. Il video resta com'è.")
NON_TROVATO = "Non trovo questo video sul disco: il video resta com'è."
NON_VIDEO = "Si tagliano solo i video."
NON_SCRITTO = ("Non sono riuscito a scrivere il video tagliato nella cartella "
               "dell'originale: l'originale resta com'è.")
OCCUPATO = "Sto già tagliando un altro video: aspetta che finisca."

_uno_alla_volta = threading.Lock()


@dataclass
class Sorgente:
    scatto_id: int
    file_id: int
    percorso: Path
    impronta: str


def _principale(connessione, scatto_id: int):
    scatto = scatti.per_id(connessione, scatto_id)
    if scatto is None or scatto["genere"] != "video":
        raise taglio.TaglioFermato(NON_VIDEO)
    riga = file_media.quello_da_guardare(file_media.di_scatto(connessione, scatto_id))
    if riga is None or riga["genere"] != "video":
        raise taglio.TaglioFermato(NON_VIDEO)
    return scatto, riga


def sorgente(archivio, scatto_id: int) -> Sorgente:
    with archivio.lettura() as connessione:
        _, riga = _principale(connessione, scatto_id)
        percorso, altra = file_media.da_mostrare(connessione, riga["id"])
        if percorso is None:
            ricerca = file_media.cerca_nell_archivio(connessione, riga["id"])
            if getattr(ricerca, "trovata", None) is not None:
                raise taglio.TaglioFermato(SOLO_NELL_ARCHIVIO)
            raise taglio.TaglioFermato(NON_TROVATO)
    percorso = Path(percorso)
    taglio.formato_di(percorso)
    return Sorgente(scatto_id, riga["id"], percorso, altra or riga["impronta"])


def mappa(archivio, scatto_id: int) -> dict:
    fonte = sorgente(archivio, scatto_id)
    chiavi = taglio.chiavi(fonte.percorso)
    return {"file": fonte.file_id, "durata": chiavi.durata, "chiavi": chiavi.chiavi,
            "nome": fonte.percorso.name}


def nome_libero(originale: Path) -> Path:
    numero = 1
    while True:
        nuovo = originale.with_name(f"{originale.stem}-taglio-{numero}{originale.suffix}")
        if not nuovo.exists() and not nuovo.with_name(nuovo.name + taglio.PARZIALE).exists():
            return nuovo
        numero += 1


def fai(archivio, scatto_id: int, pezzi) -> int:
    if not _uno_alla_volta.acquire(blocking=False):
        raise taglio.TaglioFermato(OCCUPATO)
    try:
        return _fai(archivio, scatto_id, pezzi)
    finally:
        _uno_alla_volta.release()


def _fai(archivio, scatto_id: int, pezzi) -> int:
    fonte = sorgente(archivio, scatto_id)
    uscita = nome_libero(fonte.percorso)
    try:
        fatto = taglio.taglia(fonte.percorso, pezzi, uscita)
        date.copia(fonte.percorso, uscita)
    except taglio.TaglioFermato:
        raise
    except OSError as errore:
        registro.avviso("taglio.non_scritto", motivo=registro.tipo_di(errore))
        if uscita.exists():
            uscita.unlink()
        raise taglio.TaglioFermato(NON_SCRITTO) from errore
    try:
        nuovo = _registra(archivio, fonte, uscita, fatto)
    except BaseException:
        if uscita.exists():
            uscita.unlink()
        raise
    with archivio.lettura() as connessione:
        riga = uno(connessione, "SELECT f.* FROM file_media f JOIN tagli t "
                   "ON t.file_id = f.id WHERE t.scatto_id = ?", nuovo)
    if riga is not None:
        try:
            miniature.per_file(archivio, riga,
                               int(archivio.impostazione("miniatura_lato") or 640))
        except Exception as errore:                     # noqa: BLE001
            registro.avviso("taglio.miniatura_non_fatta", **registro.dove_si_e_rotto(errore))
    if fatto.lasciate:
        registro.avviso("taglio.tracce_lasciate", quante=len(fatto.lasciate))
    return nuovo


def _registra(archivio, fonte: Sorgente, uscita: Path, fatto: taglio.Fatto) -> int:
    dati = metadati.leggi(uscita)
    segno = impronta_file.del_file(uscita)
    dimensione = uscita.stat().st_size
    with archivio.scrittura() as connessione:
        scatto, riga = _principale(connessione, fonte.scatto_id)
        for campo in ("data_locale", "fuso_minuti", "istante_utc", "origine_data",
                      "latitudine", "longitudine"):
            setattr(dati, campo, scatto[campo])
        for campo in ("marca", "modello", "obiettivo"):
            setattr(dati, campo, riga[campo] if riga[campo] is not None
                    else getattr(dati, campo))
        dati.identificatore_ios = None
        dati.sembra_schermata = False
        file_id = file_media.crea(connessione, segno, dimensione, "video", dati)
        file_media.aggiungi_percorso(connessione, file_id, uscita,
                                     scansione.cartella_di(connessione, uscita))
        nuovo = scatti.crea(connessione, "video", dati)
        connessione.execute(
            "UPDATE scatti SET giorno = ?, luogo_id = ?, nota = ?, posto_non_so = ? "
            "WHERE id = ?",
            (scatto["giorno"], scatto["luogo_id"], scatto["nota"], scatto["posto_non_so"],
             nuovo))
        file_media.collega_a_scatto(connessione, file_id, nuovo, "principale")
        quando = adesso()
        connessione.execute(
            "INSERT OR IGNORE INTO etichette (scatto_id, nodo_id, stato, origine, sicurezza, "
            "creata_il) SELECT ?, nodo_id, stato, origine, sicurezza, ? FROM etichette "
            "WHERE scatto_id = ? AND origine = 'utente'", (nuovo, quando, fonte.scatto_id))
        inserisci(
            connessione,
            "INSERT INTO tagli (scatto_id, file_id, da_scatto_id, da_file_id, da_impronta, "
            "pezzi, fatto_il) VALUES (?,?,?,?,?,?,?)",
            nuovo, file_id, fonte.scatto_id, fonte.file_id, fonte.impronta,
            json.dumps([[round(a, 3), round(b, 3)] for a, b in fatto.pezzi]), quando)
    return nuovo


def da_dove(connessione, scatto_id: int) -> dict | None:
    riga = uno(connessione, "SELECT da_scatto_id, pezzi FROM tagli WHERE scatto_id = ?",
               scatto_id)
    if riga is None:
        return None
    return {"scatto_id": riga["da_scatto_id"], "pezzi": json.loads(riga["pezzi"])}


def tagliati_da(connessione, scatto_id: int) -> list[int]:
    return [r["scatto_id"] for r in tutti(
        connessione, "SELECT scatto_id FROM tagli WHERE da_scatto_id = ? ORDER BY id",
        scatto_id)]
