from __future__ import annotations

import os
from pathlib import Path

from officina import registro
from officina.archivio.database import adesso, tutti, uno
from officina.errori import ErroreOfficina
from officina.importazione import impronta
from officina.miglioria import attesa, coda
from officina.modello import file_media
from officina.sicuro.dall_archivio import SENZA_ARCHIVIO

SICURO_CHIUSO = "sicuro_chiuso"
CAMBIATA = "la copia in attesa è cambiata dopo il sì: non l'ho toccata"
NON_PRESA = "il Cestino di Windows non l'ha presa"
RIMASTA = ("la copia migliorata è ancora in chiaro nella cartella di attesa: riprovo a "
           "metterla nel Cestino a ogni avvio, o puoi cancellarla tu")
CHIUSO_ORA = ("l'Archivio sicuro si è chiuso prima di prendere la migliorata: aprilo e "
              "dai di nuovo il sì")
CHIUSO_DOPO = ("l'Archivio sicuro è chiuso: riprovo alla prossima partenza della coda, "
               "ad archivio aperto")
MUTO_ORA = "l'Archivio sicuro non ha risposto: dai di nuovo il sì fra poco"
MUTO_DOPO = "l'Archivio sicuro non ha risposto: riprovo alla prossima partenza della coda"
A_META = "l'Archivio sicuro si è fermato a metà: riprovo alla prossima partenza della coda"
NON_PRESA_DALL_ARCHIVIO = "L'Archivio sicuro non ha preso la migliorata."


class ScambioFermato(ErroreOfficina):
    codice = "scambio_fermato"


def sposta(da: Path, verso: Path) -> None:
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


def uguali(una: Path, altra: Path) -> bool:
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
    from officina.miglioria import sopra

    with archivio.lettura() as connessione:
        ritoccata = sopra.di(connessione, riga)
    if ritoccata is not None:
        return sopra.approva(archivio, riga, ritoccata)

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
    nell_archivio = not os.path.lexists(originale)
    if nell_archivio:
        _si_puo_dall_archivio(archivio, riga, originale)
    elif not originale.is_file():
        raise _non_c_e(originale)
    elif impronta.del_file(originale) != riga["impronta_originale"]:
        raise _cambiato(originale)
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
            "percorso_migliorata = ?, nell_archivio = ?, guasto = NULL "
            "WHERE id = ? AND stato = ?",
            (coda.IN_SCAMBIO, str(spostato), str(finale), int(nell_archivio),
             miglioria_id, coda.DA_RIVEDERE)).rowcount
    if not cambiate:
        raise ScambioFermato("Questo file non è in attesa di una decisione.")
    registro.evento("miglioria.scambio_inizio", miglioria=miglioria_id)
    if nell_archivio:
        return _nell_archivio(archivio, _leggi(archivio, miglioria_id), appena=True)
    return porta_a_termine(archivio, miglioria_id)


def _non_c_e(originale: Path) -> ScambioFermato:
    return ScambioFermato(
        f"L'originale «{originale.name}» non è più dov'era: lo scambio "
        "non parte. Nessun file è stato toccato.")


def _cambiato(originale: Path) -> ScambioFermato:
    return ScambioFermato(
        f"«{originale.name}» non è più il file che era stato migliorato: "
        "lo scambio non parte. Nessun file è stato toccato.")


def _chiuso(originale: Path) -> ScambioFermato:
    return ScambioFermato(
        f"«{originale.name}» c'è solo nell'Archivio sicuro, che è chiuso: aprilo e "
        "riprova. Nessun file è stato toccato.", codice=SICURO_CHIUSO)


def _si_puo_dall_archivio(archivio, riga, originale: Path) -> None:
    from officina.programma import archivio_sicuro

    with archivio.lettura() as connessione:
        file = file_media.per_id(connessione, riga["file_id"])
    if file is None or file["impronta"] != riga["impronta_originale"]:
        raise _cambiato(originale)
    perche, servizio = archivio_sicuro.per_le_foto()
    if servizio is not None:
        return
    if perche == SENZA_ARCHIVIO:
        raise _non_c_e(originale)
    raise _chiuso(originale)


def _nell_archivio(archivio, riga, appena: bool = False) -> Path:
    from officina.programma import archivio_sicuro
    from officina.sicuro.sottofondo import FINITO

    miglioria_id = riga["id"]
    originale = Path(riga["percorso_originale"])
    with archivio.lettura() as connessione:
        file = file_media.per_id(connessione, riga["file_id"])
    if file is None or file["impronta"] != riga["impronta_originale"]:
        _non_scritto(archivio, miglioria_id, appena,
                     "l'originale nel programma non è più quello migliorato")
        raise _cambiato(originale)
    richiesta = {"originale": str(originale), "impronta": riga["impronta_originale"],
                 "dimensione": file["dimensione"], "nuova": riga["in_revisione"] or "",
                 "impronta_nuova": riga["impronta_migliorata"] or "",
                 "verso": riga["percorso_migliorata"] or "",
                 "spostato": riga["percorso_spostato"] or ""}
    _, servizio = archivio_sicuro.per_le_foto()
    try:
        if servizio is None:
            raise _chiuso(originale)
        fatto = servizio.accogli(richiesta)
    except ErroreOfficina as errore:
        chiuso = errore.codice in (SICURO_CHIUSO, "archivio_chiuso")
        if appena:
            _torna_indietro(archivio, miglioria_id, CHIUSO_ORA if chiuso else MUTO_ORA)
        else:
            _ferma(archivio, miglioria_id, CHIUSO_DOPO if chiuso else MUTO_DOPO)
        if chiuso:
            raise _chiuso(originale) from None
        raise ScambioFermato(
            f"L'Archivio sicuro non ha preso la migliorata: {errore}",
            codice=errore.codice) from None
    except Exception as guasto:
        registro.errore("miglioria.archivio_guasto", **registro.dove_si_e_rotto(guasto))
        _ferma(archivio, miglioria_id, A_META)
        raise _a_meta() from None
    esito = fatto["esito"]
    if fatto["stato"] != FINITO or esito is None:
        if fatto["scritto"]:
            _ferma(archivio, miglioria_id, A_META)
            raise _a_meta()
        perche = fatto["errore"] or NON_PRESA_DALL_ARCHIVIO
        _non_scritto(archivio, miglioria_id, appena, perche)
        raise ScambioFermato(f"Lo scambio non è avvenuto. {perche}", codice=fatto["codice"])
    verso = Path(esito["verso"])
    spostato = Path(esito["spostato"])
    with archivio.scrittura() as connessione:
        cambia_il_percorso(connessione, riga["file_id"], originale, spostato,
                           presente=False)
        connessione.execute("UPDATE file_media SET miniatura = NULL WHERE id = ?",
                            (riga["file_id"],))
        coda.segna(connessione, miglioria_id, coda.APPROVATA, decisa_il=adesso(),
                   percorso_spostato=str(spostato), percorso_migliorata=str(verso),
                   guasto=None)
    registro.evento("miglioria.scambio_fatto", miglioria=miglioria_id,
                    nell_archivio=True, gia_fatto=bool(esito["gia_fatto"]))
    butta_la_copia(archivio, miglioria_id)
    return verso


def _a_meta() -> ScambioFermato:
    return ScambioFermato(
        "L'Archivio sicuro si è fermato a metà mentre prendeva la migliorata: riprovo alla "
        "prossima partenza della coda. Nessun file è stato cancellato.")


def _non_scritto(archivio, miglioria_id: int, appena: bool, perche: str) -> None:
    if appena:
        _torna_indietro(archivio, miglioria_id, perche)
    else:
        _ferma(archivio, miglioria_id, perche)


def butta_la_copia(archivio, miglioria_id: int) -> bool:
    riga = _leggi(archivio, miglioria_id)
    if (riga["stato"] != coda.APPROVATA or not riga["nell_archivio"]
            or not riga["in_revisione"]):
        return False
    in_attesa = Path(riga["in_revisione"])
    try:
        motivo = _nel_cestino(riga, in_attesa)
    except Exception as guasto:
        registro.errore("miglioria.cestino_guasto", **registro.dove_si_e_rotto(guasto))
        motivo = NON_PRESA
    with archivio.scrittura() as connessione:
        if motivo is None or motivo == CAMBIATA:
            connessione.execute(
                "UPDATE migliorie SET in_revisione = NULL, guasto = ? WHERE id = ? "
                "AND stato = ?", (motivo, miglioria_id, coda.APPROVATA))
        else:
            connessione.execute(
                "UPDATE migliorie SET guasto = ? WHERE id = ? AND stato = ?",
                (f"{RIMASTA}. {motivo}", miglioria_id, coda.APPROVATA))
    if motivo is not None:
        registro.avviso("miglioria.copia_in_chiaro", miglioria=miglioria_id,
                        cambiata=motivo == CAMBIATA)
    return motivo is None


def _nel_cestino(riga, in_attesa: Path) -> str | None:
    from officina.programma import archivio_sicuro

    if not os.path.lexists(in_attesa):
        return None
    if (not attesa.e_dentro(in_attesa) or not in_attesa.is_file()
            or impronta.del_file(in_attesa) != riga["impronta_migliorata"]):
        return CAMBIATA
    cestino = archivio_sicuro.il_cestino()
    problema = cestino.problema(str(in_attesa.parent), [(str(in_attesa), 0)],
                                in_attesa.stat().st_size)
    if problema is not None:
        return problema[1]
    try:
        cestino.butta(str(in_attesa))
    except Exception as guasto:
        registro.errore("miglioria.cestino_guasto", **registro.dove_si_e_rotto(guasto))
    return NON_PRESA if os.path.lexists(in_attesa) else None


def butta_le_copie_rimaste(archivio) -> int:
    with archivio.lettura() as connessione:
        righe = tutti(connessione,
                      "SELECT id FROM migliorie WHERE stato = ? AND nell_archivio = 1 "
                      "AND in_revisione IS NOT NULL ORDER BY id", coda.APPROVATA)
    return sum(1 for riga in righe if butta_la_copia(archivio, riga["id"]))


def porta_a_termine(archivio, miglioria_id: int) -> Path:
    riga = _leggi(archivio, miglioria_id)
    if riga["stato"] == coda.APPROVATA:
        return Path(riga["percorso_migliorata"])
    if riga["stato"] != coda.IN_SCAMBIO:
        raise ScambioFermato("Questo scambio non è in corso.")
    if riga["nell_archivio"]:
        return _nell_archivio(archivio, riga)
    from officina.miglioria import sopra

    if sopra.in_corso(riga):
        return sopra.porta_a_termine(archivio, miglioria_id)

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
        sposta(originale, spostato)
    if uguali(originale, spostato):
        os.unlink(originale)

    if impronta.del_file(spostato) != riga["impronta_originale"]:
        if not originale.exists():
            sposta(spostato, originale)
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
        sposta(in_attesa, finale)

    if impronta.del_file(finale) != riga["impronta_migliorata"]:
        if not in_attesa.exists():
            sposta(finale, in_attesa)
        if not originale.exists():
            sposta(spostato, originale)
        _torna_indietro(archivio, miglioria_id,
                        "la migliorata spostata non torna bit per bit")
        raise ScambioFermato(
            "La copia migliorata, spostata, non era identica: ho rimesso tutto "
            "com'era e lo scambio non è avvenuto.")

    with archivio.scrittura() as connessione:
        cambia_il_percorso(connessione, riga["file_id"], originale,
                                    spostato)
        connessione.execute("UPDATE file_media SET miniatura = NULL WHERE id = ?",
                            (riga["file_id"],))
        coda.segna(connessione, miglioria_id, coda.APPROVATA,
                   decisa_il=adesso(), in_revisione=None, guasto=None)
    registro.evento("miglioria.scambio_fatto", miglioria=miglioria_id)
    return finale


def cambia_il_percorso(connessione, file_id: int, prima: Path,
                                dopo: Path, presente: bool = True) -> None:
    riga = uno(connessione,
               "SELECT id, cartella_id FROM percorsi WHERE percorso = ?", str(prima))
    if riga is not None:
        connessione.execute(
            "UPDATE percorsi SET percorso = ?, nome = ?, presente = ?, "
            "visto_il = ?, file_id = ? WHERE id = ?",
            (str(dopo), dopo.name, int(presente), adesso(), file_id, riga["id"]))
        return
    nuovo, _ = file_media.aggiungi_percorso(connessione, file_id, dopo)
    if not presente:
        connessione.execute("UPDATE percorsi SET presente = 0 WHERE id = ?", (nuovo,))


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
                                                Path(riga["percorso_originale"]),
                                                archivio.dove.radice)
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
    butta_le_copie_rimaste(archivio)
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
