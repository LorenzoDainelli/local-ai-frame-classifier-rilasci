from __future__ import annotations

import os
from pathlib import Path

from officina import registro
from officina.archivio.database import adesso, tutti
from officina.importazione import impronta
from officina.miglioria import attesa, coda
from officina.miglioria.scambio import ScambioFermato, sposta
from officina.ritocco import copia as ritocco_copia


def di(connessione, riga) -> object | None:
    ritoccata = ritocco_copia.ritoccata(connessione, riga["file_id"])
    if ritoccata is None or ritoccata["base_e"] != ritocco_copia.ORIGINALE:
        return None
    if ritoccata["percorso_base"] != riga["percorso_originale"]:
        return None
    return ritoccata


def in_corso(riga) -> bool:
    return bool(riga["percorso_spostato"]) and riga["percorso_spostato"] == riga["percorso_originale"]


def dove_va(ritoccata, in_attesa: Path) -> Path:
    copia = Path(ritoccata["percorso_copia"])
    base = Path(ritoccata["percorso_base"])
    return base.parent / ritocco_copia.CARTELLA / copia.with_suffix(in_attesa.suffix).name


def approva(archivio, riga, ritoccata) -> Path:
    if ritoccata["stato"] != ritocco_copia.FATTA:
        raise ScambioFermato("Sto ancora salvando un ritocco di questo scatto: riprova fra "
                             "qualche secondo.")
    originale = Path(riga["percorso_originale"])
    in_attesa = Path(riga["in_revisione"] or "")
    copia = Path(ritoccata["percorso_copia"])
    finale = dove_va(ritoccata, in_attesa)

    if not riga["in_revisione"] or not in_attesa.is_file():
        raise ScambioFermato(
            "La copia migliorata non si trova più nella cartella di attesa: "
            "rifiutala e rimetti il file in coda.")
    if impronta.del_file(in_attesa) != riga["impronta_migliorata"]:
        raise ScambioFermato(
            "La copia migliorata è cambiata da quando è stata fatta: non la "
            "metto al posto dell'originale. Rifiutala e rimetti il file in coda.")
    if not os.path.lexists(originale):
        raise ScambioFermato(
            f"«{originale.name}» c'è solo nell'Archivio sicuro: per uno scatto ritoccato "
            "questo scambio non si fa ancora. Nessun file è stato toccato.")
    if not originale.is_file() or impronta.del_file(originale) != riga["impronta_originale"]:
        raise ScambioFermato(
            f"«{originale.name}» in «{attesa.ORIGINALI}» non è più il file che era stato "
            "migliorato: lo scambio non parte. Nessun file è stato toccato.")
    if not copia.is_file() or impronta.del_file(copia) != ritoccata["impronta_copia"]:
        raise ScambioFermato(
            f"«{copia.name}» non è più la copia ritoccata: lo scambio non parte. Nessun "
            "file è stato toccato.")
    if finale.exists():
        raise ScambioFermato(
            f"In «{finale.parent.name}» c'è già «{finale.name}»: lo scambio non parte, "
            "per non coprirlo.")

    with archivio.scrittura() as connessione:
        cambiate = connessione.execute(
            "UPDATE migliorie SET stato = ?, percorso_spostato = ?, "
            "percorso_migliorata = ?, nell_archivio = 0, guasto = NULL "
            "WHERE id = ? AND stato = ?",
            (coda.IN_SCAMBIO, str(originale), str(finale), riga["id"],
             coda.DA_RIVEDERE)).rowcount
    if not cambiate:
        raise ScambioFermato("Questo file non è in attesa di una decisione.")
    registro.evento("miglioria.scambio_sopra_inizio", miglioria=riga["id"])
    return porta_a_termine(archivio, riga["id"])


def porta_a_termine(archivio, miglioria_id: int) -> Path:
    with archivio.lettura() as connessione:
        riga = coda.per_id(connessione, miglioria_id)
        ritoccata = ritocco_copia.ritoccata(connessione, riga["file_id"])
    finale = Path(riga["percorso_migliorata"])
    in_attesa = Path(riga["in_revisione"] or "")

    if not finale.exists():
        if not in_attesa.is_file():
            _ferma(archivio, miglioria_id, "la copia migliorata è sparita")
            raise ScambioFermato(
                "La copia migliorata è sparita a metà scambio. Lo scatto ritoccato è al "
                "suo posto, intatto.")
        sposta(in_attesa, finale)
    if impronta.del_file(finale) != riga["impronta_migliorata"]:
        if not in_attesa.exists():
            sposta(finale, in_attesa)
        with archivio.scrittura() as connessione:
            coda.segna(connessione, miglioria_id, coda.DA_RIVEDERE,
                       percorso_spostato=None, percorso_migliorata=None,
                       guasto="la migliorata spostata non torna bit per bit")
        raise ScambioFermato(
            "La copia migliorata, spostata, non era identica: ho rimesso tutto com'era e "
            "lo scambio non è avvenuto.")

    with archivio.scrittura() as connessione:
        if ritoccata is not None and ritoccata["base_e"] == ritocco_copia.ORIGINALE:
            connessione.execute(
                "UPDATE ritoccate SET percorso_base = ?, impronta_base = ?, base_e = ?, "
                "miglioria_id = ?, da_rifare = 1 WHERE file_id = ?",
                (str(finale), riga["impronta_migliorata"], ritocco_copia.MIGLIORATA,
                 miglioria_id, riga["file_id"]))
        coda.segna(connessione, miglioria_id, coda.APPROVATA,
                   decisa_il=adesso(), in_revisione=None, guasto=None)
    registro.evento("miglioria.scambio_sopra_fatto", miglioria=miglioria_id)
    rifai(archivio, riga["file_id"])
    return finale


def rifai(archivio, file_id: int) -> bool:
    try:
        ritocco_copia.rifai(archivio, file_id)
    except (ritocco_copia.RitoccoFermato, ScambioFermato, OSError):
        registro.errore("miglioria.ripixelato_fermo", file=file_id)
        return False
    return True


def rifai_i_lasciati(archivio) -> int:
    with archivio.lettura() as connessione:
        righe = tutti(connessione,
                      "SELECT r.file_id FROM ritoccate r JOIN file_media f ON f.id = r.file_id "
                      "WHERE r.da_rifare = 1 AND f.genere = 'immagine'")
    return sum(1 for riga in righe if rifai(archivio, riga["file_id"]))


def _ferma(archivio, miglioria_id: int, perche: str) -> None:
    with archivio.scrittura() as connessione:
        connessione.execute("UPDATE migliorie SET guasto = ? WHERE id = ?",
                            (perche, miglioria_id))
    registro.errore("miglioria.scambio_fermo", miglioria=miglioria_id)
