from __future__ import annotations

import os
from pathlib import Path

from officina import registro
from officina.archivio.database import adesso, uno
from officina.errori import ErroreOfficina
from officina.importazione import impronta
from officina.miglioria import attesa, coda
from officina.modello import file_media


class ScambioFermato(ErroreOfficina):
    codice = "scambio_fermato"


def _sposta(da: Path, verso: Path) -> None:
    if verso.exists():
        raise ScambioFermato(
            f"In «{verso.parent.name}» c'è già un file che si chiama "
            f"«{verso.name}»: non lo copro. Spostalo o rinominalo e riprova.")
    verso.parent.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        os.rename(da, verso)
        return
    try:
        os.link(da, verso)
    except OSError:
        if verso.exists():
            raise
        os.rename(da, verso)
        return
    os.unlink(da)


def _uguali(una: Path, altra: Path) -> bool:
    try:
        return una.exists() and altra.exists() and os.path.samefile(una, altra)
    except OSError:
        return False


def _leggi(archivio, miglioria_id: int):
    with archivio.lettura() as connessione:
        riga = coda.per_id(connessione, miglioria_id)
    if riga is None:
        raise ScambioFermato("Questo miglioramento non c'è più.")
    return riga


def approva(archivio, miglioria_id: int) -> Path:
    riga = _leggi(archivio, miglioria_id)
    if riga["stato"] == coda.APPROVATA:
        return Path(riga["percorso_migliorata"])
    if riga["stato"] != coda.DA_RIVEDERE:
        raise ScambioFermato("Questo file non è in attesa di una decisione.")

    originale = Path(riga["percorso_originale"])
    in_attesa = Path(riga["in_revisione"] or "")
    spostato = attesa.dove_va_l_originale(originale)
    finale = attesa.dove_va_la_migliorata(originale, in_attesa.suffix)

    if not riga["in_revisione"] or not in_attesa.is_file():
        raise ScambioFermato(
            "La copia migliorata non si trova più nella cartella di attesa: "
            "rifiutala e rimetti il file in coda.")
    if impronta.del_file(in_attesa) != riga["impronta_migliorata"]:
        raise ScambioFermato(
            "La copia migliorata è cambiata da quando è stata fatta: non la "
            "metto al posto dell'originale. Rifiutala e rimetti il file in coda.")
    if not originale.is_file():
        raise ScambioFermato(
            f"L'originale «{originale.name}» non è più dov'era: lo scambio "
            "non parte. Nessun file è stato toccato.")
    if impronta.del_file(originale) != riga["impronta_originale"]:
        raise ScambioFermato(
            f"«{originale.name}» non è più il file che era stato migliorato: "
            "lo scambio non parte. Nessun file è stato toccato.")
    if spostato.exists():
        raise ScambioFermato(
            f"In «{attesa.ORIGINALI}» c'è già un file che si chiama "
            f"«{spostato.name}»: lo scambio non parte, per non coprirlo.")
    if finale != originale and finale.exists():
        raise ScambioFermato(
            f"Accanto all'originale c'è già «{finale.name}»: lo scambio non "
            "parte, per non coprirlo.")

    with archivio.scrittura() as connessione:
        cambiate = connessione.execute(
            "UPDATE migliorie SET stato = ?, percorso_spostato = ?, "
            "percorso_migliorata = ?, guasto = NULL WHERE id = ? AND stato = ?",
            (coda.IN_SCAMBIO, str(spostato), str(finale), miglioria_id,
             coda.DA_RIVEDERE)).rowcount
    if not cambiate:
        raise ScambioFermato("Questo file non è in attesa di una decisione.")
    registro.evento("miglioria.scambio_inizio", miglioria=miglioria_id)
    return porta_a_termine(archivio, miglioria_id)


def porta_a_termine(archivio, miglioria_id: int) -> Path:
    riga = _leggi(archivio, miglioria_id)
    if riga["stato"] == coda.APPROVATA:
        return Path(riga["percorso_migliorata"])
    if riga["stato"] != coda.IN_SCAMBIO:
        raise ScambioFermato("Questo scambio non è in corso.")

    originale = Path(riga["percorso_originale"])
    spostato = Path(riga["percorso_spostato"])
    finale = Path(riga["percorso_migliorata"])
    in_attesa = Path(riga["in_revisione"])

    if not spostato.exists():
        if not originale.is_file():
            _ferma(archivio, miglioria_id,
                   "l'originale non è né al suo posto né in Originali")
            raise ScambioFermato(
                "Non trovo l'originale né al suo posto né in «Originali». Non "
                "ho cancellato niente: controlla la cartella.")
        _sposta(originale, spostato)
    if _uguali(originale, spostato):
        os.unlink(originale)

    if impronta.del_file(spostato) != riga["impronta_originale"]:
        if not originale.exists():
            _sposta(spostato, originale)
        _torna_indietro(archivio, miglioria_id,
                        "l'originale spostato non torna bit per bit")
        raise ScambioFermato(
            "Dopo averlo spostato, l'originale non era identico: l'ho rimesso "
            "dov'era e lo scambio non è avvenuto.")

    if not finale.exists():
        if not in_attesa.is_file():
            _ferma(archivio, miglioria_id, "la copia migliorata è sparita")
            raise ScambioFermato(
                "La copia migliorata è sparita a metà scambio. L'originale è "
                f"in «{attesa.ORIGINALI}», intatto.")
        _sposta(in_attesa, finale)

    if impronta.del_file(finale) != riga["impronta_migliorata"]:
        if not in_attesa.exists():
            _sposta(finale, in_attesa)
        if not originale.exists():
            _sposta(spostato, originale)
        _torna_indietro(archivio, miglioria_id,
                        "la migliorata spostata non torna bit per bit")
        raise ScambioFermato(
            "La copia migliorata, spostata, non era identica: ho rimesso tutto "
            "com'era e lo scambio non è avvenuto.")

    with archivio.scrittura() as connessione:
        _il_percorso_dell_originale(connessione, riga["file_id"], originale,
                                    spostato)
        connessione.execute("UPDATE file_media SET miniatura = NULL WHERE id = ?",
                            (riga["file_id"],))
        coda.segna(connessione, miglioria_id, coda.APPROVATA,
                   decisa_il=adesso(), in_revisione=None, guasto=None)
    registro.evento("miglioria.scambio_fatto", miglioria=miglioria_id)
    return finale


def _il_percorso_dell_originale(connessione, file_id: int, prima: Path,
                                dopo: Path) -> None:
    riga = uno(connessione,
               "SELECT id, cartella_id FROM percorsi WHERE percorso = ?", str(prima))
    if riga is not None:
        connessione.execute(
            "UPDATE percorsi SET percorso = ?, nome = ?, presente = 1, "
            "visto_il = ?, file_id = ? WHERE id = ?",
            (str(dopo), dopo.name, adesso(), file_id, riga["id"]))
        return
    file_media.aggiungi_percorso(connessione, file_id, dopo)


def _torna_indietro(archivio, miglioria_id: int, perche: str) -> None:
    with archivio.scrittura() as connessione:
        coda.segna(connessione, miglioria_id, coda.DA_RIVEDERE,
                   percorso_spostato=None, percorso_migliorata=None,
                   guasto=perche)
    registro.errore("miglioria.scambio_disfatto", miglioria=miglioria_id)


def _ferma(archivio, miglioria_id: int, perche: str) -> None:
    with archivio.scrittura() as connessione:
        connessione.execute("UPDATE migliorie SET guasto = ? WHERE id = ?",
                            (perche, miglioria_id))
    registro.errore("miglioria.scambio_fermo", miglioria=miglioria_id)


def rifiuta(archivio, miglioria_id: int) -> None:
    riga = _leggi(archivio, miglioria_id)
    if riga["stato"] == coda.RIFIUTATA:
        return
    if riga["stato"] != coda.DA_RIVEDERE:
        raise ScambioFermato("Questo file non è in attesa di una decisione.")
    if riga["in_revisione"]:
        in_attesa = Path(riga["in_revisione"])
        if not attesa.e_dentro(in_attesa):
            raise ScambioFermato(
                "La copia non sta nella cartella di attesa: non la cancello.")
        if in_attesa.exists():
            if impronta.del_file(in_attesa) != riga["impronta_migliorata"]:
                raise ScambioFermato(
                    "Nella cartella di attesa c'è un file diverso da quello che "
                    "ho fatto io: non lo cancello.")
            in_attesa.unlink()
    with archivio.scrittura() as connessione:
        coda.segna(connessione, miglioria_id, coda.RIFIUTATA,
                   decisa_il=adesso(), in_revisione=None)
    registro.evento("miglioria.rifiutata", miglioria=miglioria_id)


def ripara(archivio) -> dict:
    with archivio.scrittura() as connessione:
        interrotte = coda.riprendi_interrotte(connessione)
        in_scambio = coda.in_stato(connessione, coda.IN_SCAMBIO)
        cartelle = {riga["id"]: attesa.cartella(connessione,
                                                Path(riga["percorso_originale"]))
                    for riga in interrotte}
    for riga in interrotte:
        togli_i_parziali(cartelle[riga["id"]], riga["id"])
    finiti, fermi = 0, 0
    for riga in in_scambio:
        try:
            porta_a_termine(archivio, riga["id"])
            finiti += 1
        except (ScambioFermato, OSError):
            fermi += 1
    if interrotte or in_scambio:
        registro.evento("miglioria.riparata", riprese=len(interrotte),
                        scambi_finiti=finiti, scambi_fermi=fermi)
    return {"riprese": len(interrotte), "scambi_finiti": finiti,
            "scambi_fermi": fermi}


def togli_i_parziali(dove: Path, miglioria_id: int) -> int:
    if not dove.is_dir():
        return 0
    tolti = 0
    for parziale in dove.glob(f"{int(miglioria_id)}-*{attesa.PARZIALE}"):
        if attesa.e_dentro(parziale) and parziale.is_file():
            parziale.unlink()
            tolti += 1
    return tolti
