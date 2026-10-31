from __future__ import annotations

import contextlib
import os
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from officina import registro
from officina.archivio.database import adesso, tutti, uno
from officina.errori import DaRifare, ErroreOfficina
from officina.importazione import impronta
from officina.miglioria import attesa, date, metadati
from officina.miglioria.scambio import cambia_il_percorso, sposta, uguali
from officina.modello import file_media
from officina.ritocco import anteprime, elenco, in_chiaro, maschere, pixela, tolti
from officina.sicuro.accoglienza import (AGGIUNGI, MESSAGGI, RIMETTI, SENZA_CASA,
                                        SOSTITUISCI, VERSIONE_DIVERSA)
from officina.sicuro.dall_archivio import (CHIUSO, PERSA, SENZA_ARCHIVIO, SI_APRE,
                                           DallArchivio, Ricerca, attento)
from officina.sicuro.sottofondo import FINITO

IN_SCAMBIO = "in_scambio"
FATTA = "fatta"
IN_RITORNO = "in_ritorno"

ORIGINALE = "originale"
MIGLIORATA = "migliorata"

CARTELLA = ".ritocchi"
PREFISSO = "ritocco"

CAMBIATO = ("Lo scatto non è più quello che c'è in archivio: non lo ritocco. Nessun file "
            "è stato toccato.")
NON_SUL_DISCO = "Lo scatto non si trova sul disco: non lo ritocco."
SICURO_CHIUSO = "sicuro_chiuso"
NIENTE_TOCCATO = " Nessun file è stato toccato."
SOLO_NELL_ARCHIVIO = ("Lo scatto senza ritocchi c'è solo nell'Archivio sicuro, che è "
                      "chiuso: aprilo e riprova." + NIENTE_TOCCATO)
DA_NESSUNA_PARTE = ("Non trovo lo scatto senza ritocchi né sul disco né nell'Archivio "
                    "sicuro: non lo ritocco." + NIENTE_TOCCATO)
DIVERSA = ("Nell'Archivio sicuro c'è solo una versione cambiata di questo scatto: non la "
           "ritocco." + NIENTE_TOCCATO)
MIGLIORATA_PERSA = ("Non trovo la versione migliorata di questo scatto né sul disco né "
                    "nell'Archivio sicuro: non lo ritocco." + NIENTE_TOCCATO)
SENZA_CARTELLA = ("Questo scatto è nell'Archivio sicuro, ma non so in che cartella stava: "
                  "non lo ritocco." + NIENTE_TOCCATO)
ROVINATA = ("Nell'Archivio sicuro lo scatto senza ritocchi è rovinato: non lo ritocco."
            + NIENTE_TOCCATO)
MESCOLATI = ("La copia ritoccata è sul disco, ma lo scatto senza ritocchi c'è solo "
             "nell'Archivio sicuro: non lo ritocco per non mescolare." + NIENTE_TOCCATO)
MESCOLATI_FORSE = ("La copia ritoccata è sul disco, ma lo scatto senza ritocchi no: forse è "
                   "solo nell'Archivio sicuro, che è chiuso. Non lo ritocco per non "
                   "mescolare." + NIENTE_TOCCATO)
CHIUSO_DOPO = ("l'Archivio sicuro era chiuso: finisco quando ritocchi di nuovo questo "
               "scatto, ad archivio aperto")
MUTO_DOPO = ("l'Archivio sicuro non ha risposto: finisco quando ritocchi di nuovo questo "
             "scatto")
A_META = ("l'Archivio sicuro si è fermato a metà: finisco quando ritocchi di nuovo questo "
          "scatto")
FERMO_A_META = ("L'Archivio sicuro si è fermato a metà: finisco quando ritocchi di nuovo "
                "questo scatto. Nessun file è stato cancellato.")
SENZA_BASE = ("Non trovo lo scatto senza ritocchi in «Originali»: tengo la copia ritoccata "
              "com'è." + NIENTE_TOCCATO)
NON_PRESO = ("L'Archivio sicuro non ha preso il ritocco: non è stato salvato."
             + NIENTE_TOCCATO)
NON_SALVATO = {codice: f"Il ritocco non è stato salvato. {testo}"
               for codice, testo in MESSAGGI.items()}
TOPPA_CHIUSA = ("Il risultato di una cosa tolta è solo nell'Archivio sicuro, che è chiuso: "
                "aprilo e riprova." + NIENTE_TOCCATO)
TOPPA_ROVINATA = ("Nell'Archivio sicuro il risultato di una cosa tolta è rovinato: non lo "
                  "uso." + NIENTE_TOCCATO)
TOPPE_A_META = ("L'Archivio sicuro si è fermato a metà mentre prendeva il risultato di una "
                "cosa tolta: riprova. Nessun file è stato cancellato.")

_UNO_ALLA_VOLTA = threading.RLock()


class RitoccoFermato(ErroreOfficina):
    codice = "ritocco_fermato"


@dataclass
class Base:

    percorso: Path
    impronta: str
    e: str
    miglioria_id: int | None = None
    trovata: DallArchivio | None = None


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


def _chiuso(toppa: bool = False) -> RitoccoFermato:
    if toppa:
        return RitoccoFermato(TOPPA_CHIUSA, codice=SICURO_CHIUSO)
    return RitoccoFermato(SOLO_NELL_ARCHIVIO, codice=SICURO_CHIUSO)


def _non_risponde(errore: ErroreOfficina, toppa: bool = False) -> RitoccoFermato:
    registro.avviso("ritocco.archivio_non_risponde", motivo=registro.Parola(errore.codice))
    return _chiuso(toppa)


def trovata_o_fermo(ricerca: Ricerca, sua_impronta: str) -> DallArchivio:
    if ricerca.perche == SENZA_ARCHIVIO:
        raise RitoccoFermato(NON_SUL_DISCO)
    if ricerca.perche in (CHIUSO, SI_APRE):
        raise _chiuso()
    if ricerca.trovata is None:
        raise RitoccoFermato(DA_NESSUNA_PARTE)
    if ricerca.diversa or ricerca.trovata.blake2b != sua_impronta:
        raise RitoccoFermato(DIVERSA)
    return ricerca.trovata


def ritrova(perche: str, servizio, sua_impronta: str, dimensione: int | None, nome: str,
            intero: bool) -> DallArchivio:
    if servizio is None:
        return trovata_o_fermo(Ricerca(perche), sua_impronta)
    try:
        ricerca = servizio.cerca(sua_impronta, dimensione, [], nome=nome, intero=intero)
    except ErroreOfficina as errore:
        raise _non_risponde(errore) from None
    return trovata_o_fermo(ricerca, sua_impronta)


def _trovata(ricerca: Ricerca, base: Base) -> Base:
    base.trovata = trovata_o_fermo(ricerca, base.impronta)
    return base


def _base_nell_archivio(archivio, file_id: int) -> Base:
    with archivio.lettura() as connessione:
        migliorata = uno(
            connessione,
            "SELECT id, percorso_migliorata, impronta_migliorata, nell_archivio FROM "
            "migliorie WHERE file_id = ? AND stato = 'approvata' ORDER BY id DESC LIMIT 1",
            file_id)
        file = file_media.per_id(connessione, file_id)
        try:
            if migliorata is not None and migliorata["percorso_migliorata"]:
                percorso = Path(migliorata["percorso_migliorata"])
                ricerca = file_media.cerca_uguale(
                    connessione, file_id, migliorata["impronta_migliorata"],
                    migliorata["percorso_migliorata"],
                    anche_diversa=bool(migliorata["nell_archivio"]))
                if ricerca.trovata is None and ricerca.perche not in (
                        CHIUSO, SI_APRE, SENZA_ARCHIVIO):
                    raise RitoccoFermato(MIGLIORATA_PERSA)
                return _trovata(ricerca, Base(
                    percorso, migliorata["impronta_migliorata"], MIGLIORATA,
                    migliorata["id"]))
            ricerca = file_media.cerca_nell_archivio(connessione, file_id)
            base = _trovata(ricerca, Base(Path(), file["impronta"], ORIGINALE))
            casa, perche = file_media.casa_nell_archivio(connessione, file_id)
        except RitoccoFermato:
            raise
        except ErroreOfficina as errore:
            raise _non_risponde(errore) from None
    if casa is None:
        if perche in (CHIUSO, SI_APRE):
            raise _chiuso()
        if perche == SENZA_CASA:
            raise RitoccoFermato(SENZA_CARTELLA)
        if perche == VERSIONE_DIVERSA:
            raise RitoccoFermato(DIVERSA)
        raise RitoccoFermato(DA_NESSUNA_PARTE)
    base.percorso = casa
    return base


def _base_della_riga(archivio, riga: sqlite3.Row) -> DallArchivio | None:
    base = Path(riga["percorso_base"])
    if os.path.lexists(base):
        return None
    with archivio.lettura() as connessione:
        try:
            ricerca = file_media.cerca_uguale(connessione, riga["file_id"],
                                              riga["impronta_base"], riga["percorso_base"])
        except ErroreOfficina as errore:
            raise _non_risponde(errore) from None
    if ricerca.perche == SENZA_ARCHIVIO:
        return None
    chiuso = ricerca.perche in (CHIUSO, SI_APRE)
    if os.path.lexists(riga["percorso_copia"]):
        if ricerca.trovata is not None:
            raise RitoccoFermato(MESCOLATI)
        if chiuso:
            raise RitoccoFermato(MESCOLATI_FORSE)
        raise RitoccoFermato(DA_NESSUNA_PARTE)
    if chiuso:
        raise _chiuso()
    if ricerca.trovata is None:
        raise RitoccoFermato(DA_NESSUNA_PARTE)
    if ricerca.diversa or ricerca.trovata.blake2b != riga["impronta_base"]:
        raise RitoccoFermato(CAMBIATO)
    return ricerca.trovata


def base_da_guardare(archivio, file_id: int) -> tuple[Path | DallArchivio | None,
                                                      str | None]:
    with archivio.lettura() as connessione:
        riga = ritoccata(connessione, file_id)
        percorso, sua_impronta = file_media.da_mostrare_sotto(connessione, file_id)
    if riga is not None:
        trovata = _base_della_riga(archivio, riga)
        if trovata is not None:
            return trovata, riga["impronta_base"]
    if percorso is not None or riga is not None:
        return percorso, sua_impronta
    base = _base_nell_archivio(archivio, file_id)
    return base.trovata, base.impronta


def _date_nell_archivio(sua_impronta: str, dimensione: int | None, percorso) -> dict:
    from officina.programma import archivio_sicuro

    _, servizio = archivio_sicuro.per_le_foto()
    try:
        trovate = (None if servizio is None
                   else servizio.date(sua_impronta, dimensione, str(percorso)))
    except ErroreOfficina as errore:
        raise _non_risponde(errore) from None
    if trovate is None:
        raise _chiuso()
    return trovate


TOPPA_PERSA = ("Il risultato di una cosa tolta non si trova più o è cambiato: va rifatto. "
               "Lo scatto non è stato toccato.")


def dove_le_toppe(copia: Path) -> Path:
    return copia.parent / attesa.ORIGINALI / CARTELLA


def nome_della_toppa(ritocco_id: int) -> str:
    return f"togli-{int(ritocco_id)}.png"


def nome_della_toppa_video(ritocco_id: int) -> str:
    return f"togli-{int(ritocco_id)}.mkv"


def nome_della_toppa_nell_archivio(ritocco_id: int, sua_impronta: str) -> str:
    return f"togli-{int(ritocco_id)}-{sua_impronta[:12]}.png"


def toppa_in_attesa(connessione: sqlite3.Connection, dove: Path, ritocco_id: int,
                    lato_b: bool = False) -> Path:
    nome, volta = nome_della_toppa(ritocco_id), 0
    while True:
        percorso = dove / (della_b(nome) if lato_b else nome)
        preso = uno(connessione, "SELECT 1 FROM ritocchi WHERE risultato = ? "
                    "AND (id != ? OR ?) LIMIT 1", str(percorso), int(ritocco_id), lato_b)
        if preso is None and not in_chiaro.occupato(connessione, percorso):
            return percorso
        volta += 1
        nome = f"togli-{int(ritocco_id)}-a{volta}.png"


def toppa_pronta(ritocco) -> bool:
    if not ritocco["risultato"] or ritocco["origine_x"] is None:
        return False
    percorso = Path(ritocco["risultato"])
    return percorso.is_file() and impronta.del_file(percorso) == ritocco["impronta_risultato"]


def _toppa_nell_archivio(ritocco) -> DallArchivio:
    from officina.programma import archivio_sicuro

    sua = ritocco["impronta_risultato"]
    perche, servizio = archivio_sicuro.per_le_foto()
    ricerca = Ricerca(perche)
    if servizio is not None and sua:
        try:
            ricerca = servizio.cerca(sua, None, [], nome=Path(ritocco["risultato"]).name,
                                     intero=True)
        except ErroreOfficina as errore:
            raise _non_risponde(errore, True) from None
    if ricerca.perche in (CHIUSO, SI_APRE):
        raise _chiuso(True)
    if ricerca.trovata is None or ricerca.diversa or ricerca.trovata.blake2b != sua:
        raise RitoccoFermato(TOPPA_PERSA)
    return ricerca.trovata


def toppa_gia_fatta(ritocco) -> bool:
    if toppa_pronta(ritocco):
        return True
    if (not ritocco["risultato"] or ritocco["origine_x"] is None
            or os.path.lexists(ritocco["risultato"])):
        return False
    try:
        _toppa_nell_archivio(ritocco)
    except RitoccoFermato as errore:
        if errore.codice == SICURO_CHIUSO:
            raise
        return False
    return True


def _leggi_la_toppa(ritocco) -> bytes:
    if not ritocco["risultato"] or ritocco["origine_x"] is None:
        raise RitoccoFermato(TOPPA_PERSA)
    percorso = Path(ritocco["risultato"])
    if os.path.lexists(percorso):
        if not toppa_pronta(ritocco):
            raise RitoccoFermato(TOPPA_PERSA)
        return percorso.read_bytes()
    trovata = _toppa_nell_archivio(ritocco)
    with leggendo(trovata, True):
        dati = trovata.apri().read()
    if impronta.dei_byte(dati) != ritocco["impronta_risultato"]:
        raise RitoccoFermato(TOPPA_PERSA)
    return dati


def _metti_la_toppa(immagine: Image.Image, ritocco) -> Image.Image:
    from officina.ritocco import togliere

    toppa = togliere.Toppa.da_png(_leggi_la_toppa(ritocco), ritocco["origine_x"],
                                  ritocco["origine_y"])
    larga, alta = immagine.size
    if (larga, alta) != (ritocco["larghezza"], ritocco["altezza"]):
        scala_x = larga / ritocco["larghezza"]
        scala_y = alta / ritocco["altezza"]
        toppa = togliere.Toppa(
            round(toppa.x * scala_x), round(toppa.y * scala_y),
            toppa.immagine.resize((max(1, round(toppa.immagine.width * scala_x)),
                                   max(1, round(toppa.immagine.height * scala_y))),
                                  Image.Resampling.LANCZOS), toppa.rimpicciolita)
    return toppa.metti(immagine)


def _e_una_toppa(percorso: Path, ritocco_id: int) -> bool:
    if percorso.parent.name == CARTELLA and percorso.name == nome_della_toppa(ritocco_id):
        return True
    nome = percorso.name.removesuffix(".png").removesuffix("-b")
    prima = f"togli-{int(ritocco_id)}"
    volta = nome.removeprefix(prima + "-a")
    return attesa.e_dentro(percorso) and (nome == prima or (
        nome.startswith(prima + "-a") and volta.isdigit() and volta.isascii()))


def butta_le_toppe(righe, archivio=None) -> None:
    for riga in righe:
        if riga["genere"] != elenco.TOGLI or not riga["risultato"]:
            continue
        percorso = Path(riga["risultato"])
        if not _e_una_toppa(percorso, riga["id"]) or not percorso.is_file():
            continue
        try:
            percorso.unlink()
        except OSError as errore:
            registro.avviso("ritocco.toppa_non_tolta", **registro.dove_si_e_rotto(errore))
            if archivio is not None and attesa.e_dentro(percorso):
                with archivio.scrittura() as connessione:
                    in_chiaro.segna(connessione, riga["file_id"], percorso,
                                    riga["impronta_risultato"] or "")


def toppa_in_attesa_da_buttare(riga) -> bool:
    if riga["genere"] != elenco.TOGLI or not riga["risultato"]:
        return False
    percorso = Path(riga["risultato"])
    return attesa.e_dentro(percorso) and _e_una_toppa(percorso, riga["id"])


def _toppe_del_lavoro(archivio, file_id: int, lavoro_id: int | None) -> list[sqlite3.Row]:
    if lavoro_id is None:
        return []
    with archivio.lettura() as connessione:
        return tutti(connessione,
                     "SELECT * FROM ritocchi WHERE lavoro_id = ? AND file_id = ? AND "
                     "stato = ? AND genere = ? AND risultato IS NOT NULL ORDER BY id",
                     lavoro_id, file_id, elenco.IN_CODA, elenco.TOGLI)


def _toppe_dentro(archivio, file_id: int, lavoro_id: int | None, copia: Path, base: Path,
                  impronta_base: str) -> None:
    for toppa in _toppe_del_lavoro(archivio, file_id, lavoro_id):
        if not os.path.lexists(toppa["risultato"]):
            _toppa_nell_archivio(toppa)
        elif not toppa_pronta(toppa):
            raise RitoccoFermato(TOPPA_PERSA)
        elif toppa_in_attesa_da_buttare(toppa):
            _aggiungi_la_toppa(archivio, toppa, copia, base, impronta_base)


def _aggiungi_la_toppa(archivio, toppa, copia: Path, base: Path, impronta_base: str) -> None:
    from officina.programma import archivio_sicuro

    percorso, sua = Path(toppa["risultato"]), toppa["impronta_risultato"]
    verso = dove_le_toppe(copia) / nome_della_toppa_nell_archivio(toppa["id"], sua)
    _, servizio = archivio_sicuro.per_le_foto()
    if servizio is None:
        raise _chiuso()
    try:
        fatto = servizio.accogli({"come": AGGIUNGI, "nuova": str(percorso),
                                  "verso": str(verso), "base": str(base),
                                  "impronta_nuova": sua, "impronta_base": impronta_base})
    except ErroreOfficina as errore:
        if errore.codice in (SICURO_CHIUSO, "archivio_chiuso"):
            raise _chiuso() from None
        raise _non_preso(errore.codice) from None
    except Exception as guasto:
        registro.errore("ritocco.archivio_guasto", **registro.dove_si_e_rotto(guasto))
        raise RitoccoFermato(TOPPE_A_META) from None
    if fatto["stato"] != FINITO or fatto["esito"] is None:
        if fatto["scritto"]:
            raise RitoccoFermato(TOPPE_A_META)
        raise _non_preso(fatto["codice"])
    with archivio.scrittura() as connessione:
        connessione.execute(
            "UPDATE ritocchi SET risultato = ? WHERE id = ? AND risultato = ?",
            (fatto["esito"]["verso"], toppa["id"], str(percorso)))
        in_chiaro.segna(connessione, toppa["file_id"], percorso, sua)
    registro.evento("ritocco.toppa_nell_archivio", ritocco=toppa["id"],
                    gia_fatto=bool(fatto["esito"]["gia_fatto"]))
    try:
        in_chiaro.butta(archivio, percorso)
    except Exception as guasto:
        registro.errore("ritocco.cestino_guasto", **registro.dove_si_e_rotto(guasto))


def disegna(immagine: Image.Image, ritocchi) -> Image.Image:
    larga, alta = immagine.size
    for ritocco in ritocchi:
        if ritocco["genere"] == elenco.TOGLI:
            immagine = _metti_la_toppa(immagine, ritocco)
            continue
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


def nome_in_attesa(file_id: int, copia: Path, lavoro_id: int | None = None,
                   variante: str = "") -> str:
    if lavoro_id is None:
        return f"{PREFISSO}-{int(file_id)}-{copia.name}"
    if variante:
        return f"{PREFISSO}-{int(file_id)}-{int(lavoro_id)}-{variante}-{copia.name}"
    return f"{PREFISSO}-{int(file_id)}-{int(lavoro_id)}-{copia.name}"


def della_b(nome: str) -> str:
    percorso = Path(nome)
    return f"{percorso.stem}-b{percorso.suffix}"


def _nome_libero(connessione: sqlite3.Connection, file_id: int, copia: Path,
                 dove: Path) -> str:
    nome, volta = nome_in_attesa(file_id, copia), 0
    while in_chiaro.occupato(connessione, dove / nome):
        volta += 1
        nome = f"{PREFISSO}-{int(file_id)}-a{volta}-{copia.name}"
    return nome


@contextlib.contextmanager
def leggendo(sorgente, toppa: bool = False):
    try:
        with attento(sorgente):
            yield sorgente
    except DaRifare as errore:
        if errore.codice == PERSA and toppa:
            raise RitoccoFermato(TOPPA_ROVINATA) from None
        if errore.codice == PERSA:
            raise RitoccoFermato(ROVINATA) from None
        raise _chiuso(toppa) from None


def apri(sorgente):
    with leggendo(sorgente):
        return metadati.apri(sorgente)


def _prepara(file_id: int, sorgente, copia: Path, formato: str, ritocchi,
             dove: Path, lavoro_id: int | None = None, variante: str = "", *,
             nome: str | None = None, quando: dict | None = None) -> Path:
    attesa.prepara(dove)
    pronta = dove / (nome or nome_in_attesa(file_id, copia, lavoro_id, variante))
    parziale = pronta.with_name(pronta.name + attesa.PARZIALE)
    for vecchio in (pronta, parziale):
        if vecchio.is_file() and attesa.e_dentro(vecchio):
            vecchio.unlink()
    foto = apri(sorgente)
    try:
        disegnata = disegna(foto.immagine, ritocchi)
        disegnata.info.clear()
        metadati.salva(disegnata, anteprime.via(foto.metadati), parziale, formato,
                       foto.alfa)
        if quando is None:
            date.copia(sorgente, parziale)
        else:
            date.rimetti(parziale, quando)
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
            base = _base_nell_archivio(archivio, file_id)
        copia, sorgente = base.percorso, base.trovata or base.percorso
        impronta_base, verso_la_base = base.impronta, dove_va_la_base(base)
        if os.path.lexists(verso_la_base):
            raise RitoccoFermato(
                "In «Originali» c'è già un file con lo stesso nome: non lo copro. "
                "Spostalo o rinominalo e riprova.")
        trovata, dove_sono_le_date = base.trovata, copia
    else:
        copia, sorgente = Path(riga["percorso_copia"]), Path(riga["percorso_base"])
        impronta_base = riga["impronta_base"]
        trovata, dove_sono_le_date = _base_della_riga(archivio, riga), sorgente
        sorgente = trovata or sorgente

    try:
        formato = metadati.formato_di(copia)
    except ValueError as errore:
        raise RitoccoFermato("Questo formato non si può ritoccare: lo scatto non è "
                             "stato toccato.") from errore
    quando, dimensione = None, None
    if trovata is not None:
        dimensione = trovata.dimensione
        quando = _date_nell_archivio(impronta_base, dimensione, dove_sono_le_date)
    elif not sorgente.is_file() or impronta.del_file(sorgente) != impronta_base:
        raise RitoccoFermato(CAMBIATO)

    with archivio.lettura() as connessione:
        dove = attesa.cartella(connessione, copia,
                               None if trovata is None else archivio.dove.radice)
        nome = _nome_libero(connessione, file_id, copia, dove)
    pronta = _prepara(file_id, sorgente, copia, formato, attivi, dove, nome=nome,
                      quando=quando)
    nuova = impronta.del_file(pronta)
    if riga is not None and nuova == riga["impronta_copia"]:
        if trovata is None:
            pronta.unlink()
        else:
            via_la_pronta(archivio, file_id, pronta, nuova)
        if riga["da_rifare"]:
            with archivio.scrittura() as connessione:
                connessione.execute("UPDATE ritoccate SET da_rifare = 0 WHERE file_id = ?",
                                    (file_id,))
        return copia

    nell_archivio = int(trovata is not None)
    with archivio.scrittura() as connessione:
        if riga is None:
            connessione.execute(
                "INSERT INTO ritoccate (file_id, stato, percorso_copia, percorso_base, "
                "impronta_base, base_e, miglioria_id, in_preparazione, impronta_nuova, "
                "nell_archivio, dimensione_base) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (file_id, IN_SCAMBIO, str(copia), str(verso_la_base), impronta_base,
                 base.e, base.miglioria_id, str(pronta), nuova, nell_archivio,
                 dimensione))
        else:
            connessione.execute(
                "UPDATE ritoccate SET stato = ?, in_preparazione = ?, impronta_nuova = ?, "
                "guasto = NULL, nell_archivio = ? WHERE file_id = ?",
                (IN_SCAMBIO, str(pronta), nuova, nell_archivio, file_id))
    registro.evento("ritocco.scambio_inizio", file=file_id)
    return porta_a_termine(archivio, file_id, True)


def porta_a_termine(archivio, file_id: int, appena: bool = False,
                    tieni: bool = False) -> Path:
    with _UNO_ALLA_VOLTA:
        with archivio.lettura() as connessione:
            riga = ritoccata(connessione, file_id)
        if riga is None:
            raise RitoccoFermato("Questo ritocco non c'è più.")
        if riga["stato"] == FATTA:
            return Path(riga["percorso_copia"])
        if riga["nell_archivio"]:
            return _nell_archivio(archivio, riga, appena, tieni)
        if riga["stato"] == IN_RITORNO:
            return _finisci_il_ritorno(archivio, riga)
        return _finisci_lo_scambio(archivio, riga)


def _richiesta(riga: sqlite3.Row) -> dict:
    copia, base = riga["percorso_copia"], riga["percorso_base"]
    if riga["stato"] == IN_RITORNO:
        return {"come": RIMETTI, "copia": copia, "impronta": riga["impronta_copia"] or "",
                "base": base, "impronta_base": riga["impronta_base"]}
    nuova, sua = riga["in_preparazione"] or "", riga["impronta_nuova"] or ""
    if riga["impronta_copia"] is None:
        return {"originale": copia, "impronta": riga["impronta_base"],
                "dimensione": riga["dimensione_base"], "nuova": nuova,
                "impronta_nuova": sua, "verso": copia, "spostato": base}
    return {"come": SOSTITUISCI, "copia": copia, "impronta": riga["impronta_copia"],
            "nuova": nuova, "impronta_nuova": sua, "base": base,
            "impronta_base": riga["impronta_base"]}


def _accogli(archivio, riga: sqlite3.Row, appena: bool, tieni: bool = False) -> dict:
    from officina.programma import archivio_sicuro

    _, servizio = archivio_sicuro.per_le_foto()
    try:
        if servizio is None:
            raise _chiuso()
        fatto = servizio.accogli(_richiesta(riga))
    except ErroreOfficina as errore:
        chiuso = errore.codice in (SICURO_CHIUSO, "archivio_chiuso")
        _non_scritto(archivio, riga, appena, CHIUSO_DOPO if chiuso else MUTO_DOPO, tieni)
        if chiuso:
            raise _chiuso() from None
        raise _non_preso(errore.codice) from None
    except Exception as guasto:
        registro.errore("ritocco.archivio_guasto", **registro.dove_si_e_rotto(guasto))
        _ferma(archivio, riga["file_id"], A_META)
        raise RitoccoFermato(FERMO_A_META) from None
    if fatto["stato"] != FINITO or fatto["esito"] is None:
        if fatto["scritto"]:
            _ferma(archivio, riga["file_id"], A_META)
            raise RitoccoFermato(FERMO_A_META)
        errore = _non_preso(fatto["codice"])
        _non_scritto(archivio, riga, appena, errore.messaggio, tieni)
        raise errore
    return fatto


def _non_preso(codice: str | None) -> RitoccoFermato:
    if codice in NON_SALVATO:
        return RitoccoFermato(NON_SALVATO[codice], codice=codice)
    return RitoccoFermato(NON_PRESO, codice=codice)


def _non_scritto(archivio, riga: sqlite3.Row, appena: bool, perche: str,
                 tieni: bool = False) -> None:
    if not appena:
        _ferma(archivio, riga["file_id"], perche)
    elif riga["impronta_copia"] is None:
        _annulla(archivio, riga, tieni)
    else:
        with archivio.scrittura() as connessione:
            connessione.execute(
                "UPDATE ritoccate SET stato = ?, in_preparazione = NULL, "
                "impronta_nuova = NULL, guasto = NULL WHERE file_id = ? AND stato = ?",
                (FATTA, riga["file_id"], riga["stato"]))
        if not tieni:
            _via_la_preparazione(archivio, riga)
        registro.errore("ritocco.scambio_disfatto", file=riga["file_id"])


def _nell_archivio(archivio, riga: sqlite3.Row, appena: bool, tieni: bool = False) -> Path:
    file_id = riga["file_id"]
    copia, base = Path(riga["percorso_copia"]), Path(riga["percorso_base"])
    esito = _accogli(archivio, riga, appena, tieni)["esito"]
    verso = Path(esito["verso"])
    pronta = Path(riga["in_preparazione"]) if riga["in_preparazione"] else None
    with archivio.scrittura() as connessione:
        if riga["stato"] == IN_RITORNO:
            _la_base_e_qui(connessione, riga, base, verso)
            connessione.execute("DELETE FROM ritoccate WHERE file_id = ?", (file_id,))
        else:
            if riga["impronta_copia"] is None:
                base = Path(esito["spostato"])
                _la_base_e_qui(connessione, riga, copia, base)
            connessione.execute(
                "UPDATE ritoccate SET stato = ?, percorso_copia = ?, percorso_base = ?, "
                "impronta_copia = impronta_nuova, in_preparazione = NULL, "
                "impronta_nuova = NULL, fatta_il = ?, guasto = NULL, da_rifare = 0 "
                "WHERE file_id = ?", (FATTA, str(verso), str(base), adesso(), file_id))
            if pronta is not None:
                in_chiaro.segna(connessione, file_id, pronta, riga["impronta_nuova"])
        connessione.execute("UPDATE file_media SET miniatura = NULL WHERE id = ?",
                            (file_id,))
    tornato = riga["stato"] == IN_RITORNO
    registro.evento("ritocco.tornato" if tornato else "ritocco.scambio_fatto", file=file_id,
                    nell_archivio=True, gia_fatto=bool(esito["gia_fatto"]))
    if not tornato and pronta is not None:
        try:
            in_chiaro.butta(archivio, pronta)
        except Exception as guasto:
            registro.errore("ritocco.cestino_guasto", **registro.dove_si_e_rotto(guasto))
    return verso


def _la_base_e_qui(connessione: sqlite3.Connection, riga: sqlite3.Row, prima: Path,
                   dopo: Path) -> None:
    if riga["base_e"] == ORIGINALE:
        cambia_il_percorso(connessione, riga["file_id"], prima, dopo, presente=False)
        _segui_in_miglioria(connessione, riga["file_id"], prima, dopo)
    elif riga["miglioria_id"]:
        connessione.execute("UPDATE migliorie SET percorso_migliorata = ? WHERE id = ?",
                            (str(dopo), riga["miglioria_id"]))


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
                _segui_in_miglioria(connessione, file_id, copia, base)
        elif riga["miglioria_id"]:
            connessione.execute("UPDATE migliorie SET percorso_migliorata = ? WHERE id = ?",
                                (str(base), riga["miglioria_id"]))
        connessione.execute(
            "UPDATE ritoccate SET stato = ?, impronta_copia = impronta_nuova, "
            "in_preparazione = NULL, impronta_nuova = NULL, fatta_il = ?, guasto = NULL, "
            "da_rifare = 0 WHERE file_id = ?", (FATTA, adesso(), file_id))
        connessione.execute("UPDATE file_media SET miniatura = NULL WHERE id = ?",
                            (file_id,))
    _togli_la_preparazione(riga)
    registro.evento("ritocco.scambio_fatto", file=file_id)
    return copia


def _torna(archivio, file_id: int) -> Path:
    with archivio.lettura() as connessione:
        riga = ritoccata(connessione, file_id)
    if riga is None:
        raise RitoccoFermato("Questo ritocco non c'è più.")
    appena = riga["stato"] == FATTA
    if appena:
        nell_archivio = int(_base_della_riga(archivio, riga) is not None)
        if not nell_archivio and not Path(riga["percorso_base"]).is_file():
            raise RitoccoFermato(SENZA_BASE)
        with archivio.scrittura() as connessione:
            connessione.execute(
                "UPDATE ritoccate SET stato = ?, guasto = NULL, nell_archivio = ? "
                "WHERE file_id = ? AND stato = ?",
                (IN_RITORNO, nell_archivio, file_id, FATTA))
    return porta_a_termine(archivio, file_id, appena)


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
            _segui_in_miglioria(connessione, file_id, base, copia)
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


def _segui_in_miglioria(connessione: sqlite3.Connection, file_id: int, prima: Path,
                        dopo: Path) -> None:
    connessione.execute(
        "UPDATE migliorie SET percorso_originale = ? WHERE file_id = ? "
        "AND percorso_originale = ? AND stato IN ('in_coda','in_lavoro','da_rivedere')",
        (str(dopo), file_id, str(prima)))


def _togli_la_preparazione(riga: sqlite3.Row) -> None:
    if riga["in_preparazione"]:
        butta(Path(riga["in_preparazione"]))


def _via_la_preparazione(archivio, riga: sqlite3.Row) -> None:
    if riga["nell_archivio"] and riga["in_preparazione"]:
        via_la_pronta(archivio, riga["file_id"], Path(riga["in_preparazione"]),
                      riga["impronta_nuova"])
    else:
        _togli_la_preparazione(riga)


def via_la_pronta(archivio, file_id: int, pronta: Path, sua_impronta: str) -> None:
    with archivio.lettura() as connessione:
        if in_chiaro.occupato(connessione, pronta):
            return
    try:
        butta(pronta)
    except OSError as errore:
        registro.avviso("ritocco.copia_non_tolta", file=file_id,
                        **registro.dove_si_e_rotto(errore))
        with archivio.scrittura() as connessione:
            in_chiaro.segna(connessione, file_id, pronta, sua_impronta)


def butta(pronta: Path) -> None:
    for file in (pronta, pronta.with_name(pronta.name + attesa.PARZIALE)):
        if file.is_file() and attesa.e_dentro(file) and file.name.startswith(PREFISSO):
            file.unlink()


def _annulla(archivio, riga: sqlite3.Row, tieni: bool = False) -> None:
    with archivio.scrittura() as connessione:
        connessione.execute(
            "DELETE FROM ritoccate WHERE file_id = ? AND impronta_copia IS NULL",
            (riga["file_id"],))
    if not tieni:
        _via_la_preparazione(archivio, riga)
    registro.errore("ritocco.scambio_disfatto", file=riga["file_id"])


def _ferma(archivio, file_id: int, perche: str) -> None:
    with archivio.scrittura() as connessione:
        connessione.execute("UPDATE ritoccate SET guasto = ? WHERE file_id = ?",
                            (perche, file_id))
    registro.errore("ritocco.scambio_fermo", file=file_id)


def e_una_live(archivio, file_id: int) -> bool:
    with archivio.lettura() as connessione:
        return uno(connessione,
                   "SELECT 1 FROM file_media f JOIN file_media m ON m.scatto_id = f.scatto_id "
                   "WHERE f.id = ? AND m.id <> f.id AND m.ruolo = 'movimento' LIMIT 1",
                   file_id) is not None


def _in_sospeso(archivio, file_id: int) -> bool:
    with archivio.lettura() as connessione:
        riga = ritoccata(connessione, file_id)
    return riga is not None and riga["stato"] != FATTA


def fermo_a_meta(archivio, file_id: int, pronta: str | None) -> bool:
    with archivio.lettura() as connessione:
        riga = ritoccata(connessione, file_id)
    if riga is None or riga["stato"] == FATTA or not riga["nell_archivio"]:
        return False
    if pronta is None:
        return riga["stato"] == IN_RITORNO
    return riga["in_preparazione"] == str(pronta)


def _prima_finisci(archivio, file_id: int) -> None:
    if _in_sospeso(archivio, file_id):
        porta_a_termine(archivio, file_id)


def metti(archivio, file_id: int, nuovi: list[dict]) -> Path | None:
    with _UNO_ALLA_VOLTA:
        _prima_finisci(archivio, file_id)
        if e_una_live(archivio, file_id):
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
            fatta = _rifai(archivio, ritocco["file_id"])
            tolti.allinea_il_file(archivio, ritocco["file_id"])
            return fatta
        except BaseException:
            if not _in_sospeso(archivio, ritocco["file_id"]):
                with archivio.scrittura() as connessione:
                    elenco.segna(connessione, ritocco_id, elenco.FATTO, tolto_il=None)
            raise


@dataclass
class Partenza:

    sorgente: Path | DallArchivio
    impronta_base: str
    copia: Path
    dove_le_date: Path | None = None

    @property
    def trovata(self) -> DallArchivio | None:
        return self.sorgente if isinstance(self.sorgente, DallArchivio) else None

    def in_attesa(self, archivio) -> Path:
        with archivio.lettura() as connessione:
            return attesa.cartella(connessione, self.copia,
                                   None if self.trovata is None else archivio.dove.radice)

    def ancora_lei(self) -> None:
        if self.trovata is not None:
            return
        if (not self.sorgente.is_file()
                or impronta.del_file(self.sorgente) != self.impronta_base):
            raise RitoccoFermato(CAMBIATO)


def partenza(archivio, file_id: int, anche_nell_archivio: bool = False) -> Partenza:
    with _UNO_ALLA_VOLTA:
        _prima_finisci(archivio, file_id)
        with archivio.lettura() as connessione:
            riga = ritoccata(connessione, file_id)
            base = base_di_adesso(connessione, file_id) if riga is None else None
        if riga is not None:
            trovata = _base_della_riga(archivio, riga) if anche_nell_archivio else None
            return Partenza(trovata or Path(riga["percorso_base"]), riga["impronta_base"],
                            Path(riga["percorso_copia"]), Path(riga["percorso_base"]))
        if base is None and anche_nell_archivio:
            base = _base_nell_archivio(archivio, file_id)
            return Partenza(base.trovata, base.impronta, base.percorso, base.percorso)
    if base is None:
        raise RitoccoFermato(NON_SUL_DISCO)
    return Partenza(base.percorso, base.impronta, base.percorso)


def prepara_per_la_coda(archivio, file_id: int, lavoro_id: int, ritocchi,
                        da: Partenza, variante: str = "") -> Path:
    try:
        formato = metadati.formato_di(da.copia)
    except ValueError as errore:
        raise RitoccoFermato("Questo formato non si può ritoccare: lo scatto non è "
                             "stato toccato.") from errore
    da.ancora_lei()
    quando = None
    if da.trovata is not None:
        quando = _date_nell_archivio(da.impronta_base, da.trovata.dimensione,
                                     da.dove_le_date)
    return _prepara(file_id, da.sorgente, da.copia, formato, ritocchi,
                    da.in_attesa(archivio), lavoro_id, variante, quando=quando)


def scambia(archivio, file_id: int, pronta: Path, impronta_pronta: str,
            impronta_base: str, lavoro_id: int | None = None) -> Path:
    with _UNO_ALLA_VOLTA:
        _prima_finisci(archivio, file_id)
        with archivio.lettura() as connessione:
            riga = ritoccata(connessione, file_id)
            base = base_di_adesso(connessione, file_id) if riga is None else None
        if riga is not None and riga["impronta_copia"] == impronta_pronta:
            if riga["nell_archivio"]:
                via_la_pronta(archivio, file_id, pronta, impronta_pronta)
            else:
                butta(pronta)
            return Path(riga["percorso_copia"])
        if not pronta.is_file() or impronta.del_file(pronta) != impronta_pronta:
            raise RitoccoFermato("La copia ritoccata che aspettava di essere approvata è "
                                 "sparita o è cambiata: va rifatta. Lo scatto non è stato "
                                 "toccato.")
        if riga is not None:
            trovata = _base_della_riga(archivio, riga)
        elif base is None:
            base = _base_nell_archivio(archivio, file_id)
            trovata = base.trovata
        else:
            trovata = None
        if riga is None:
            if base.impronta != impronta_base:
                raise RitoccoFermato(CAMBIATO)
            verso_la_base = dove_va_la_base(base)
            if os.path.lexists(verso_la_base):
                raise RitoccoFermato(
                    "In «Originali» c'è già un file con lo stesso nome: non lo copro. "
                    "Spostalo o rinominalo e riprova.")
            copia, sua_base = base.percorso, base.percorso
        else:
            if riga["impronta_base"] != impronta_base:
                raise RitoccoFermato(CAMBIATO)
            copia, sua_base = Path(riga["percorso_copia"]), Path(riga["percorso_base"])
        if trovata is not None:
            _toppe_dentro(archivio, file_id, lavoro_id, copia, sua_base, impronta_base)
        nell_archivio = int(trovata is not None)
        with archivio.scrittura() as connessione:
            if riga is None:
                connessione.execute(
                    "INSERT INTO ritoccate (file_id, stato, percorso_copia, percorso_base, "
                    "impronta_base, base_e, miglioria_id, in_preparazione, impronta_nuova, "
                    "nell_archivio, dimensione_base) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (file_id, IN_SCAMBIO, str(base.percorso), str(verso_la_base),
                     impronta_base, base.e, base.miglioria_id, str(pronta),
                     impronta_pronta, nell_archivio,
                     None if trovata is None else trovata.dimensione))
            else:
                connessione.execute(
                    "UPDATE ritoccate SET stato = ?, in_preparazione = ?, "
                    "impronta_nuova = ?, guasto = NULL, nell_archivio = ? WHERE file_id = ?",
                    (IN_SCAMBIO, str(pronta), impronta_pronta, nell_archivio, file_id))
        registro.evento("ritocco.scambio_inizio", file=file_id)
        if trovata is None:
            return porta_a_termine(archivio, file_id)
        return porta_a_termine(archivio, file_id, True, tieni=True)


def torna(archivio, file_id: int) -> Path | None:
    with _UNO_ALLA_VOLTA:
        _prima_finisci(archivio, file_id)
        with archivio.lettura() as connessione:
            riga = ritoccata(connessione, file_id)
        if riga is None:
            return None
        return _torna(archivio, file_id)


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
