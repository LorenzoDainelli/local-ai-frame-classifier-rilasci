from __future__ import annotations

import contextvars
import re
import secrets
import shutil
import threading
from dataclasses import dataclass, field
from pathlib import Path

from officina import registro
from officina.archivio import accesso
from officina.archivio.accesso import Archivio, ArchivioDiProva
from officina.errori import ErroreOfficina
from officina.impostazioni import FINTO, Posizione, radice_archivi
from officina.programma import aspetto
from officina.web.lavori import Lavoro

BISCOTTO = "prova"
QUANTE_FOTO_FINTE = 60
VERSIONE_DEL_FINTO = 2
NOME_DEL_FINTO = "finto-per-la-prova"
NOME_DELLE_FOTO = "foto-della-prova"

NON_SI_GUARDA = (
    "/importazione", "/api/importazione", "/raccolta", "/telefono",
    "/sincronia", "/benvenuto", "/giro", "/api/sfoglia-cartella", "/modelli",
)

SI_PUO_SCRIVERE = tuple(re.compile(f"^{strada}$") for strada in (
    r"/api/etichetta", r"/api/cuore", r"/api/stella", r"/api/annulla",
    r"/api/persona-a-mano", r"/api/ripasso/\w+", r"/api/nodi", r"/api/riaddestra",
    r"/api/persona-conferma", r"/api/nessuna-persona", r"/api/luogo", r"/api/non-so-dove",
    r"/api/luoghi", r"/luoghi/(nuovo|da-un-ramo|\d+/(nome|sposta|cestina|coordinate|dallo-scatto))",
    r"/scatto/\d+/(rimetti-in-coda|nota|fuori-archivio)",
    r"/api/albero/\w+", r"/albero/crea", r"/albero/\d+/cestina",
    r"/api/persone/\d+/(nome|rimanda|ignora|riprendi|dimentica)",
    r"/api/persone/(non-e-lui|raggruppa)", r"/api/persone/forse/\d+",
    r"/luoghi/raggruppa",
    r"/api/aspetto", r"/api/impostazione", r"/impostazioni",
    r"/misura/(nodo|ramo|segna|nessuno)",
    r"/senza-data/\d+/(imposta|marca)", r"/senza-data/(blocco|gruppo|lascia)",
    r"/elenchi/schermate-(tienile|fuori-archivio)",
    r"/api/doppioni/(tieni|diverse|rimetti)", r"/scatti/in-blocco",
    r"/api/miglioramento/metti", r"/miglioramento/\d+/(togli|rimetti)",
    r"/blocco/(apri|adesso)", r"/prova/\w+", r"/api/novita/lette", r"/api/sei-qui",
))


@dataclass
class Prova:

    segno: str
    con: str
    chiave: str
    archivio: ArchivioDiProva
    scelte: dict[str, str] = field(default_factory=dict)

    @property
    def valore(self) -> str:
        return self.scelte[self.chiave]

    @property
    def nome(self) -> str:
        return aspetto.nome_della_versione(self.chiave, self.valore)

    @property
    def voce(self) -> dict:
        return aspetto.VOCI[self.chiave]

    def come_e(self) -> tuple[str, str]:
        _, _, come, costa = self.voce["versioni"][self.valore]
        return come, costa


_adesso: Prova | None = None
_lucchetto = threading.Lock()
preparazione = Lavoro("l'archivio finto per la prova")
_le_impronte: list = [None]


def a_che_punto_e_il_finto() -> int:
    passata = _le_impronte[0]
    if passata is not None and passata.avanzamento.totale:
        fatto = passata.avanzamento
        return 58 + int((fatto.fatti + fatto.saltati) * 40 / fatto.totale)
    return int(preparazione.numeri.get("percento", 0))


def dove_sta_il_finto() -> Posizione:
    return Posizione(radice_archivi() / NOME_DEL_FINTO, FINTO)


def _in_costruzione() -> Path:
    return radice_archivi() / f"{NOME_DEL_FINTO}.in-costruzione"


def _dove_stanno_le_foto() -> Path:
    return radice_archivi() / NOME_DELLE_FOTO


def _segno_di_pronto() -> Path:
    return dove_sta_il_finto().radice / f"pronto-{VERSIONE_DEL_FINTO}"


def il_finto_c_e() -> bool:
    return dove_sta_il_finto().database.exists() and _segno_di_pronto().exists()


def prepara_il_finto() -> bool:
    if il_finto_c_e():
        return False
    return contextvars.Context().run(preparazione.parti, _costruisci_il_finto,
                                     "finto-per-la-prova")


def _costruisci_il_finto() -> None:
    from officina.finto import etichette, generatore
    from officina.importazione.motore import Motore
    from officina.impronte.motore import Passata

    cantiere = _in_costruzione()
    foto = _dove_stanno_le_foto()
    for vecchia in (cantiere, foto, dove_sta_il_finto().radice):
        if vecchia.exists():
            shutil.rmtree(vecchia)

    preparazione.di("Disegno le foto finte")
    preparazione.a_che_punto(2, 100)
    generatore.genera(foto, quanti=QUANTE_FOTO_FINTE, seme=11, leggero=True)
    preparazione.a_che_punto(20, 100)

    preparazione.di("Le metto in un archivio finto")
    archivio = Archivio(Posizione(cantiere, FINTO), tiene_il_registro=False).apri()
    try:
        motore = Motore(archivio)
        quanti = max(1, int(motore.prepara([foto])["file"]))
        motore.esegui(al_passo=lambda stato: preparazione.a_che_punto(
            20 + int((stato.fatti + stato.saltati) * 35 / quanti), 100))

        preparazione.di("Ci metto qualche etichetta finta")
        etichette.metti(archivio, foto, lascia_fuori=0.4)

        preparazione.di("Calcolo le impronte, per le proposte")
        preparazione.a_che_punto(58, 100)
        _le_impronte[0] = Passata(archivio, "disegnato", fotogrammi_per_video=4)
        _le_impronte[0].esegui()
    finally:
        _le_impronte[0] = None
        archivio.chiudi(con_copia=False)

    cantiere.rename(dove_sta_il_finto().radice)
    _segno_di_pronto().write_text("pronto\n", encoding="utf-8")
    preparazione.a_che_punto(1, 1)
    registro.evento("prova.finto_costruito")


def dal_biscotto(segno: str | None) -> Prova | None:
    prova = _adesso
    if prova is None or not segno or not secrets.compare_digest(segno, prova.segno):
        return None
    return prova


def adesso() -> Prova | None:
    return _adesso


def perche_no(metodo: str, percorso: str) -> str | None:
    if metodo in ("GET", "HEAD"):
        if any(percorso == strada or percorso.startswith(strada + "/")
               for strada in NON_SI_GUARDA):
            return accesso.NELLA_PROVA_NO
        return None
    if any(strada.match(percorso) for strada in SI_PUO_SCRIVERE):
        return None
    return accesso.NELLA_PROVA_NO


def comincia(chiave: str, valore: str, con: str) -> Prova:
    global _adesso
    if chiave not in aspetto.VERSIONI or valore not in aspetto.SCELTE[chiave]:
        raise ErroreOfficina("Non conosco questa versione.")
    if con not in aspetto.SCELTE["prova_con"]:
        raise ErroreOfficina("La prova si fa sulla copia o sull'archivio finto.")

    with _lucchetto:
        if _adesso is not None:
            _adesso.scelte[chiave] = valore
            _adesso.chiave = chiave
            if _adesso.con == con:
                return _adesso
            vecchia, _adesso = _adesso, None
            vecchia.archivio.chiudi()

        if con == "finto":
            if not il_finto_c_e():
                raise ErroreOfficina("L'archivio finto non è ancora pronto.",
                                     codice="finto_da_preparare")
            archivio = ArchivioDiProva(dove_sta_il_finto(), dove_sta_il_finto().database)
        else:
            vero = accesso.vero()
            archivio = ArchivioDiProva(vero.dove, vero)
        archivio.apri()

        scelte = aspetto.leggi()
        scelte[chiave] = valore
        _adesso = Prova(segno=secrets.token_urlsafe(24), con=con, chiave=chiave,
                        archivio=archivio, scelte=scelte)
    registro.evento("prova.cominciata", con=registro.Parola(con))
    return _adesso


def cambia(chiave: str, valore: str) -> Prova:
    prova = _adesso
    if prova is None:
        raise ErroreOfficina("Non c'è nessuna prova in corso.")
    if chiave not in aspetto.SCELTE or valore not in aspetto.SCELTE[chiave]:
        raise ErroreOfficina("Non conosco questa scelta.")
    prova.scelte[chiave] = valore
    if chiave in aspetto.VERSIONI:
        prova.chiave = chiave
    return prova


def finisci(tieni: bool = False) -> Prova | None:
    global _adesso
    with _lucchetto:
        prova, _adesso = _adesso, None
    if prova is None:
        return None
    try:
        prova.archivio.chiudi()
    finally:
        if tieni:
            vere = aspetto.leggi()
            for chiave, valore in prova.scelte.items():
                if chiave != "prova_con" and vere.get(chiave) != valore:
                    aspetto.imposta(chiave, valore)
        registro.evento("prova.finita", tenuta=tieni)
    return prova
