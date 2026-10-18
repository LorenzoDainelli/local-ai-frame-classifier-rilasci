from __future__ import annotations

import os
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from officina import registro
from officina.archivio.database import adesso, tutti, uno
from officina.errori import ErroreOfficina
from officina.importazione import impronta
from officina.miglioria import attesa, date, metadati
from officina.miglioria.scambio import cambia_il_percorso, sposta, uguali
from officina.modello import file_media
from officina.ritocco import anteprime, elenco, maschere, pixela

IN_SCAMBIO = "in_scambio"
FATTA = "fatta"
IN_RITORNO = "in_ritorno"

ORIGINALE = "originale"
MIGLIORATA = "migliorata"

CARTELLA = ".ritocchi"
PREFISSO = "ritocco"

_UNO_ALLA_VOLTA = threading.RLock()


class RitoccoFermato(ErroreOfficina):
    codice = "ritocco_fermato"


@dataclass
class Base:

    percorso: Path
    impronta: str
    e: str
    miglioria_id: int | None = None


def ritoccata(connessione: sqlite3.Connection, file_id: int) -> sqlite3.Row | None:
    return uno(connessione, "SELECT * FROM ritoccate WHERE file_id = ?", file_id)


def base_di_adesso(connessione: sqlite3.Connection, file_id: int) -> Base | None:
    migliorata = uno(
        connessione,
        "SELECT id, percorso_migliorata, impronta_migliorata FROM migliorie "
        "WHERE file_id = ? AND stato = 'approvata' ORDER BY id DESC LIMIT 1", file_id)
    if migliorata is not None and migliorata["percorso_migliorata"]:
        percorso = Path(migliorata["percorso_migliorata"])
        if percorso.is_file():
            return Base(percorso, migliorata["impronta_migliorata"], MIGLIORATA,
                        migliorata["id"])
    riga = file_media.per_id(connessione, file_id)
    percorso = file_media.percorso_migliore(connessione, file_id)
    if riga is None or percorso is None:
        return None
    return Base(percorso, riga["impronta"], ORIGINALE)


def dove_va_la_base(base: Base) -> Path:
    if base.e == ORIGINALE:
        return attesa.dove_va_l_originale(base.percorso)
    return base.percorso.parent / attesa.ORIGINALI / CARTELLA / base.percorso.name


def disegna(immagine: Image.Image, ritocchi) -> Image.Image:
    larga, alta = immagine.size
    for ritocco in ritocchi:
        if ritocco["genere"] != elenco.PIXELA:
            raise RitoccoFermato("Questo ritocco non si può ancora rifare: lo scatto "
                                 "non è stato toccato.")
        pezzo = maschere.apri(ritocco["maschera"])
        if pezzo is None:
            raise RitoccoFermato("La parte scelta di un ritocco non si legge più: lo "
                                 "scatto non è stato toccato.")
        scala_x = larga / ritocco["larghezza"]
        scala_y = alta / ritocco["altezza"]
        scalato = maschere.per_misura(pezzo, larga, alta)
        lato = pixela.quadretto(ritocco["misura"] * scala_x,
                                round((ritocco["quadretto"] or 0) * scala_x))
        origine_x = pezzo.x if ritocco["origine_x"] is None else ritocco["origine_x"]
        origine_y = pezzo.y if ritocco["origine_y"] is None else ritocco["origine_y"]
        immagine = pixela.pixela(immagine, scalato.maschera, (scalato.x, scalato.y), lato,
                                 (round(origine_x * scala_x), round(origine_y * scala_y)))
    return immagine


def _prepara(file_id: int, sorgente: Path, copia: Path, formato: str, ritocchi,
             dove: Path) -> Path:
    attesa.prepara(dove)
    pronta = dove / f"{PREFISSO}-{int(file_id)}-{copia.name}"
    parziale = pronta.with_name(pronta.name + attesa.PARZIALE)
    for vecchio in (pronta, parziale):
        if vecchio.is_file() and attesa.e_dentro(vecchio):
            vecchio.unlink()
    foto = metadati.apri(sorgente)
    try:
        disegnata = disegna(foto.immagine, ritocchi)
        disegnata.info.clear()
        metadati.salva(disegnata, anteprime.via(foto.metadati), parziale, formato,
                       foto.alfa)
        date.copia(sorgente, parziale)
    except BaseException:
        if parziale.exists():
            parziale.unlink()
        raise
    os.rename(parziale, pronta)
    return pronta


def rifai(archivio, file_id: int) -> Path | None:
    with _UNO_ALLA_VOLTA:
        return _rifai(archivio, file_id)


def _rifai(archivio, file_id: int) -> Path | None:
    with archivio.lettura() as connessione:
        riga = ritoccata(connessione, file_id)
    if riga is not None and riga["stato"] != FATTA:
        porta_a_termine(archivio, file_id)

    with archivio.lettura() as connessione:
        riga = ritoccata(connessione, file_id)
        attivi = elenco.di_file(connessione, file_id)
        media = file_media.per_id(connessione, file_id)
        base = base_di_adesso(connessione, file_id) if riga is None else None
    if media is None:
        raise RitoccoFermato("Questo file non c'è più.")
    if not attivi:
        if riga is None:
            return base.percorso if base else None
        return _torna(archivio, file_id)
    if media["genere"] != "immagine":
        raise RitoccoFermato("Per ora si ritoccano solo le foto: lo scatto non è stato "
                             "toccato.")

    if riga is None:
        if base is None:
            raise RitoccoFermato("Lo scatto non si trova sul disco: non lo ritocco.")
        copia, sorgente = base.percorso, base.percorso
        impronta_base, verso_la_base = base.impronta, dove_va_la_base(base)
        if verso_la_base.exists():
            raise RitoccoFermato(
                "In «Originali» c'è già un file con lo stesso nome: non lo copro. "
                "Spostalo o rinominalo e riprova.")
    else:
        copia, sorgente = Path(riga["percorso_copia"]), Path(riga["percorso_base"])
        impronta_base = riga["impronta_base"]

    try:
        formato = metadati.formato_di(copia)
    except ValueError as errore:
        raise RitoccoFermato("Questo formato non si può ritoccare: lo scatto non è "
                             "stato toccato.") from errore
    if not sorgente.is_file() or impronta.del_file(sorgente) != impronta_base:
        raise RitoccoFermato("Lo scatto non è più quello che c'è in archivio: non lo "
                             "ritocco. Nessun file è stato toccato.")

    with archivio.lettura() as connessione:
        dove = attesa.cartella(connessione, copia)
    pronta = _prepara(file_id, sorgente, copia, formato, attivi, dove)
    nuova = impronta.del_file(pronta)
    if riga is not None and nuova == riga["impronta_copia"]:
        pronta.unlink()
        return copia

    with archivio.scrittura() as connessione:
        if riga is None:
            connessione.execute(
                "INSERT INTO ritoccate (file_id, stato, percorso_copia, percorso_base, "
                "impronta_base, base_e, miglioria_id, in_preparazione, impronta_nuova) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (file_id, IN_SCAMBIO, str(copia), str(verso_la_base), impronta_base,
                 base.e, base.miglioria_id, str(pronta), nuova))
        else:
            connessione.execute(
                "UPDATE ritoccate SET stato = ?, in_preparazione = ?, impronta_nuova = ?, "
                "guasto = NULL WHERE file_id = ?",
                (IN_SCAMBIO, str(pronta), nuova, file_id))
    registro.evento("ritocco.scambio_inizio", file=file_id)
    return porta_a_termine(archivio, file_id)


def porta_a_termine(archivio, file_id: int) -> Path:
    with _UNO_ALLA_VOLTA:
        with archivio.lettura() as connessione:
            riga = ritoccata(connessione, file_id)
        if riga is None:
            raise RitoccoFermato("Questo ritocco non c'è più.")
        if riga["stato"] == FATTA:
            return Path(riga["percorso_copia"])
        if riga["stato"] == IN_RITORNO:
            return _finisci_il_ritorno(archivio, riga)
        return _finisci_lo_scambio(archivio, riga)


def _finisci_lo_scambio(archivio, riga: sqlite3.Row) -> Path:
    file_id = riga["file_id"]
    copia, base = Path(riga["percorso_copia"]), Path(riga["percorso_base"])
    pronta = Path(riga["in_preparazione"] or "")
    prima_volta = riga["impronta_copia"] is None
    segno = impronta.del_file(copia) if copia.is_file() else None

    if prima_volta and segno == riga["impronta_base"]:
        if base.exists() and uguali(copia, base):
            os.unlink(copia)
        elif base.exists():
            _annulla(archivio, riga)
            raise RitoccoFermato(
                "In «Originali» c'è già un file con lo stesso nome: non lo copro. "
                "Spostalo o rinominalo e riprova.")
        else:
            sposta(copia, base)
        segno = None
    elif prima_volta and segno not in (None, riga["impronta_nuova"]) and not base.exists():
        _annulla(archivio, riga)
        raise RitoccoFermato("Lo scatto non è più quello che c'è in archivio: il "
                             "ritocco non è stato salvato.")

    if not base.is_file():
        _ferma(archivio, file_id, "la base non è né al suo posto né in Originali")
        raise RitoccoFermato("Non trovo lo scatto né al suo posto né in «Originali». "
                             "Non ho cancellato niente: controlla la cartella.")
    if impronta.del_file(base) != riga["impronta_base"]:
        if prima_volta and not copia.exists():
            sposta(base, copia)
            _annulla(archivio, riga)
            raise RitoccoFermato("Dopo averlo spostato, lo scatto non era identico: l'ho "
                                 "rimesso dov'era e il ritocco non è stato salvato.")
        _ferma(archivio, file_id, "la base non torna bit per bit")
        raise RitoccoFermato("Lo scatto senza ritocchi in «Originali» non è più identico: "
                             "non lo tocco. Controlla la cartella.")

    if segno is not None:
        if not prima_volta and segno == riga["impronta_copia"]:
            os.unlink(copia)
        elif segno != riga["impronta_nuova"]:
            _ferma(archivio, file_id, "al posto della copia c'è un altro file")
            raise RitoccoFermato("Al posto dello scatto c'è un file che non ho fatto io: "
                                 "non lo copro. Spostalo o rinominalo e riprova.")
    if not copia.exists():
        if not pronta.is_file():
            if prima_volta:
                sposta(base, copia)
                _annulla(archivio, riga)
                raise RitoccoFermato("La copia ritoccata è sparita a metà: ho rimesso lo "
                                     "scatto com'era.")
            _ferma(archivio, file_id, "la copia ritoccata è sparita")
            raise RitoccoFermato("La copia ritoccata è sparita a metà. Lo scatto senza "
                                 "ritocchi è in «Originali», intatto.")
        sposta(pronta, copia)
    if impronta.del_file(copia) != riga["impronta_nuova"]:
        _ferma(archivio, file_id, "la copia spostata non torna bit per bit")
        raise RitoccoFermato("La copia ritoccata, spostata, non era identica. Lo scatto "
                             "senza ritocchi è in «Originali», intatto.")

    with archivio.scrittura() as connessione:
        if riga["base_e"] == ORIGINALE:
            if prima_volta:
                cambia_il_percorso(connessione, file_id, copia, base)
        elif riga["miglioria_id"]:
            connessione.execute("UPDATE migliorie SET percorso_migliorata = ? WHERE id = ?",
                                (str(base), riga["miglioria_id"]))
        connessione.execute(
            "UPDATE ritoccate SET stato = ?, impronta_copia = impronta_nuova, "
            "in_preparazione = NULL, impronta_nuova = NULL, fatta_il = ?, guasto = NULL "
            "WHERE file_id = ?", (FATTA, adesso(), file_id))
        connessione.execute("UPDATE file_media SET miniatura = NULL WHERE id = ?",
                            (file_id,))
    _togli_la_preparazione(riga)
    registro.evento("ritocco.scambio_fatto", file=file_id)
    return copia


def _torna(archivio, file_id: int) -> Path:
    with archivio.scrittura() as connessione:
        connessione.execute(
            "UPDATE ritoccate SET stato = ?, guasto = NULL WHERE file_id = ? AND stato = ?",
            (IN_RITORNO, file_id, FATTA))
    with archivio.lettura() as connessione:
        riga = ritoccata(connessione, file_id)
    return _finisci_il_ritorno(archivio, riga)


def _finisci_il_ritorno(archivio, riga: sqlite3.Row) -> Path:
    file_id = riga["file_id"]
    copia, base = Path(riga["percorso_copia"]), Path(riga["percorso_base"])

    if copia.exists() and base.exists() and uguali(copia, base):
        os.unlink(base)
    if copia.exists():
        segno = impronta.del_file(copia)
        if segno == riga["impronta_copia"]:
            if not base.is_file() or impronta.del_file(base) != riga["impronta_base"]:
                _ferma(archivio, file_id, "la base in Originali manca o è cambiata")
                raise RitoccoFermato("Lo scatto senza ritocchi in «Originali» manca o è "
                                     "cambiato: tengo la copia ritoccata dov'è.")
            os.unlink(copia)
        elif segno != riga["impronta_base"]:
            _ferma(archivio, file_id, "al posto della copia c'è un altro file")
            raise RitoccoFermato("Al posto dello scatto c'è un file che non ho fatto io: "
                                 "non lo tocco.")
    if not copia.exists():
        if not base.is_file():
            _ferma(archivio, file_id, "la base non è in Originali")
            raise RitoccoFermato("Non trovo lo scatto senza ritocchi in «Originali». Non "
                                 "ho cancellato niente: controlla la cartella.")
        sposta(base, copia)
    if impronta.del_file(copia) != riga["impronta_base"]:
        _ferma(archivio, file_id, "la base rimessa a posto non torna bit per bit")
        raise RitoccoFermato("Lo scatto rimesso al suo posto non è identico: controlla "
                             "la cartella «Originali».")

    with archivio.scrittura() as connessione:
        if riga["base_e"] == ORIGINALE:
            cambia_il_percorso(connessione, file_id, base, copia)
        elif riga["miglioria_id"]:
            connessione.execute("UPDATE migliorie SET percorso_migliorata = ? WHERE id = ?",
                                (str(copia), riga["miglioria_id"]))
        connessione.execute("DELETE FROM ritoccate WHERE file_id = ?", (file_id,))
        connessione.execute("UPDATE file_media SET miniatura = NULL WHERE id = ?",
                            (file_id,))
    _togli_la_preparazione(riga)
    if riga["base_e"] == MIGLIORATA:
        try:
            base.parent.rmdir()
        except OSError:
            pass
    registro.evento("ritocco.tornato", file=file_id)
    return copia


def _togli_la_preparazione(riga: sqlite3.Row) -> None:
    if not riga["in_preparazione"]:
        return
    pronta = Path(riga["in_preparazione"])
    if pronta.is_file() and attesa.e_dentro(pronta) and pronta.name.startswith(PREFISSO):
        pronta.unlink()


def _annulla(archivio, riga: sqlite3.Row) -> None:
    with archivio.scrittura() as connessione:
        connessione.execute(
            "DELETE FROM ritoccate WHERE file_id = ? AND impronta_copia IS NULL",
            (riga["file_id"],))
    _togli_la_preparazione(riga)
    registro.errore("ritocco.scambio_disfatto", file=riga["file_id"])


def _ferma(archivio, file_id: int, perche: str) -> None:
    with archivio.scrittura() as connessione:
        connessione.execute("UPDATE ritoccate SET guasto = ? WHERE file_id = ?",
                            (perche, file_id))
    registro.errore("ritocco.scambio_fermo", file=file_id)


def _e_una_live(archivio, file_id: int) -> bool:
    with archivio.lettura() as connessione:
        return uno(connessione,
                   "SELECT 1 FROM file_media f JOIN file_media m ON m.scatto_id = f.scatto_id "
                   "WHERE f.id = ? AND m.id <> f.id AND m.ruolo = 'movimento' LIMIT 1",
                   file_id) is not None


def _in_sospeso(archivio, file_id: int) -> bool:
    with archivio.lettura() as connessione:
        riga = ritoccata(connessione, file_id)
    return riga is not None and riga["stato"] != FATTA


def _prima_finisci(archivio, file_id: int) -> None:
    if _in_sospeso(archivio, file_id):
        porta_a_termine(archivio, file_id)


def metti(archivio, file_id: int, nuovi: list[dict]) -> Path | None:
    with _UNO_ALLA_VOLTA:
        _prima_finisci(archivio, file_id)
        if _e_una_live(archivio, file_id):
            raise RitoccoFermato("Per ora le foto live non si ritoccano: il loro video "
                                 "resterebbe com'è. Lo scatto non è stato toccato.")
        pronti = [_con_le_misure_giuste(nuovo) for nuovo in nuovi]
        with archivio.scrittura() as connessione:
            messi = [elenco.aggiungi(connessione, file_id, **pronto) for pronto in pronti]
        try:
            return _rifai(archivio, file_id)
        except BaseException as errore:
            if not _in_sospeso(archivio, file_id):
                perche = errore.messaggio if isinstance(errore, ErroreOfficina) else None
                with archivio.scrittura() as connessione:
                    for ritocco_id in messi:
                        elenco.segna(connessione, ritocco_id, elenco.FALLITO,
                                     guasto=perche)
            raise


def _con_le_misure_giuste(nuovo: dict) -> dict:
    nuovo = dict(nuovo)
    nuovo.setdefault("genere", elenco.PIXELA)
    pezzo = maschere.apri(nuovo.get("maschera") or b"")
    if pezzo is None:
        raise RitoccoFermato("Non hai scelto niente da ritoccare.")
    if (pezzo.larghezza, pezzo.altezza) != (nuovo["larghezza"], nuovo["altezza"]):
        raise RitoccoFermato("La parte scelta non corrisponde allo scatto: riprova.")
    alta, larga = pezzo.maschera.shape
    minima = larga if nuovo["cosa"] == elenco.VOLTO else min(larga, alta)
    nuovo["misura"] = max(float(nuovo.get("misura") or 0), float(minima))
    nuovo["quadretto"] = pixela.quadretto(nuovo["misura"], nuovo.get("quadretto"))
    if nuovo.get("origine") is None:
        nuovo["origine"] = (pezzo.x, pezzo.y)
    return nuovo


def togli(archivio, ritocco_id: int) -> Path | None:
    with _UNO_ALLA_VOLTA:
        with archivio.lettura() as connessione:
            ritocco = elenco.per_id(connessione, ritocco_id)
        if ritocco is None or ritocco["stato"] != elenco.FATTO:
            raise RitoccoFermato("Questo ritocco non c'è più.")
        _prima_finisci(archivio, ritocco["file_id"])
        with archivio.scrittura() as connessione:
            elenco.segna(connessione, ritocco_id, elenco.TOLTO, tolto_il=adesso())
        try:
            return _rifai(archivio, ritocco["file_id"])
        except BaseException:
            if not _in_sospeso(archivio, ritocco["file_id"]):
                with archivio.scrittura() as connessione:
                    elenco.segna(connessione, ritocco_id, elenco.FATTO, tolto_il=None)
            raise


def ripara(archivio) -> dict:
    with _UNO_ALLA_VOLTA:
        with archivio.lettura() as connessione:
            righe = tutti(connessione, "SELECT file_id FROM ritoccate WHERE stato <> ?",
                          FATTA)
        finiti, fermi = 0, 0
        for riga in righe:
            try:
                porta_a_termine(archivio, riga["file_id"])
                finiti += 1
            except (RitoccoFermato, OSError):
                fermi += 1
    if righe:
        registro.evento("ritocco.riparato", finiti=finiti, fermi=fermi)
    return {"finiti": finiti, "fermi": fermi}
