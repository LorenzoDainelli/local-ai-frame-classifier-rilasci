from __future__ import annotations

from pathlib import Path

from officina import registro
from officina.archivio.database import leggi_stato, scrivi_stato
from officina.modello import file_media
from officina.ritocco import coda, seguiti
from officina.ritocco.copia import RitoccoFermato
from officina.web import lavori, sosta

ACCESA = "ritocco_coda_accesa"
UN_ALTRO_LAVORO = "un altro lavoro"

_ritoccatore = None
_gara = None


class Seguitore:

    def __init__(self, archivio, al_clic=None, cartella=None):
        self.archivio = archivio
        self._al_clic = al_clic
        self._cartella = cartella

    @property
    def al_clic(self):
        from officina.web import ritocco as ritocco_web

        return self._al_clic or ritocco_web.al_clic

    def _la_cartella(self) -> Path:
        if self._cartella is not None:
            return Path(self._cartella)
        from officina.web.strade import ritocco as ritocco_strade

        return ritocco_strade._cartella_di_sam3()

    def _dove(self, seguito_id: int) -> tuple[Path, Path, str]:
        with self.archivio.lettura() as connessione:
            seguito = seguiti.per_id(connessione, seguito_id)
            if seguito is None:
                raise RitoccoFermato(coda.NON_SEGUITO)
            media = file_media.per_id(connessione, seguito["file_id"])
            if media is None:
                raise RitoccoFermato(coda.NON_C_E)
            percorso, chiave = file_media.da_mostrare_sotto(connessione, seguito["file_id"])
        if percorso is None or not Path(percorso).is_file():
            raise RitoccoFermato(coda.NON_C_E)
        if (chiave or media["impronta"]) != seguito["impronta"]:
            raise RitoccoFermato(coda.SEGUITO_VECCHIO)
        return self._la_cartella(), Path(percorso), seguito["impronta"]

    def _prendi(self, lavoro) -> bool:
        turno = lavori.turno
        if turno.chi is lavoro or turno.prendi_se_libera(lavoro):
            if lavoro.numeri.pop("in_attesa_della_scheda", None):
                lavoro.di("la scheda è libera: parto")
            return True
        if not lavoro.numeri.get("in_attesa_della_scheda"):
            chi = turno.chi
            nome = (lavori.NOMI_NEL_TURNO.get(chi.cosa, chi.cosa) if chi is not None
                    else UN_ALTRO_LAVORO)
            lavoro.numeri["in_attesa_della_scheda"] = chi.cosa if chi is not None else nome
            lavoro.di(f"in attesa della scheda: la sta usando {nome}")
        return False

    def segui(self, seguito_id: int, lavoro) -> bool:
        from officina.web import seguire

        cartella, percorso, chiave = self._dove(seguito_id)
        if not self._prendi(lavoro):
            return False
        lavoro.di("l'IA segue la parte scelta nel video")
        esito = seguire.segui_ora(self.archivio, seguito_id, self.al_clic, cartella, percorso,
                                  chiave, sfondo=lavoro)
        return not esito.get("in_coda") and not esito.get("fermato")

    def prendi_la_scheda(self, lavoro) -> bool:
        return self._prendi(lavoro)

    def cerca(self, lavoro):
        from officina.errori import ErroreOfficina
        from officina.importazione import impronta

        def cerca(percorso: Path, punti: list, riquadro):
            try:
                cartella = self._la_cartella()
            except ErroreOfficina:
                return None
            if lavori.turno.chi is not lavoro:
                return None
            chiave = f"ricontrollo-{impronta.del_file(Path(percorso))}"
            try:
                dati = self.al_clic._chiedi(cartella, "scegli", chiave, str(percorso),
                                            list(punti), riquadro, None, sfondo=lavoro)
            except ErroreOfficina as errore:
                registro.avviso("ritocco.ricontrollo_saltato", guasto=errore.codice)
                return None
            finally:
                self.spegni_sam3()
            return dati["maschera"], float(dati["punteggio"])

        return cerca

    def spegni_sam3(self) -> None:
        al_clic = self.al_clic
        with al_clic._lucchetto:
            al_clic._spegni_tutto()

    def lascia(self, lavoro) -> None:
        self.al_clic.lascia_lo_sfondo(lavoro)

    def ferma(self) -> None:
        self.al_clic.ferma_lo_sfondo()


def il_ritoccatore(archivio):
    global _ritoccatore
    from officina.ritocco import lavoro

    if archivio.di_prova:
        if _ritoccatore is not None and _ritoccatore.archivio is archivio:
            return _ritoccatore
        return lavoro.Ritoccatore(archivio, Seguitore(archivio))
    if _ritoccatore is not None and _ritoccatore.archivio is not archivio:
        _ritoccatore.ferma()
        _ritoccatore = None
    if _ritoccatore is None:
        _ritoccatore = lavoro.Ritoccatore(archivio, Seguitore(archivio))
    return _ritoccatore


def il_lavoro():
    return None if _ritoccatore is None else _ritoccatore.lavoro


def sta_lavorando() -> bool:
    return _ritoccatore is not None and _ritoccatore.sta_lavorando


def avvia(archivio) -> bool:
    ritoccatore = il_ritoccatore(archivio)
    with archivio.scrittura() as connessione:
        scrivi_stato(connessione, ACCESA, True)
    if not archivio.di_prova and sosta.per_la_copia.aspetta(sosta.RITOCCO):
        return False
    return ritoccatore.parti()


def ferma_dall_utente(archivio, aspetta: float = 2.0) -> None:
    if not archivio.di_prova:
        sosta.per_la_copia.fermato_da_te(sosta.RITOCCO)
    with archivio.scrittura() as connessione:
        scrivi_stato(connessione, ACCESA, False)
    il_ritoccatore(archivio).ferma(aspetta)


def ferma_la_coda(aspetta: float = 0.0) -> None:
    if _ritoccatore is not None:
        _ritoccatore.ferma(aspetta)


def gara_in_corso() -> bool:
    return _gara is not None and _gara.lavoro.sta_lavorando


def ferma_la_gara(aspetta: float = 0.0) -> None:
    if _gara is not None:
        _gara.ferma(aspetta)


def ferma(aspetta: float = 0.0) -> None:
    ferma_la_coda(aspetta)
    ferma_la_gara(aspetta)


def parti_la_gara(archivio) -> bool:
    if not archivio.di_prova and sosta.per_la_copia.aspetta(sosta.GARA):
        return False
    return la_gara(archivio).parti()


def ferma_la_gara_dall_utente(archivio, aspetta: float = 2.0) -> None:
    if not archivio.di_prova:
        sosta.per_la_copia.fermato_da_te(sosta.GARA)
    la_gara(archivio).ferma(aspetta)


def la_gara(archivio):
    global _gara
    from officina.ritocco import gara_video

    if _gara is not None and _gara.archivio is archivio:
        return _gara
    if _gara is not None:
        _gara.ferma()
    _gara = gara_video.Gara(archivio)
    _gara.cerca = Seguitore(archivio).cerca(_gara.lavoro)
    return _gara


def riparti_se_accesa(archivio) -> bool:
    with archivio.lettura() as connessione:
        accesa = bool(leggi_stato(connessione, ACCESA, False))
        in_coda = coda.conteggi(connessione)[coda.IN_CODA]
    if not accesa or not in_coda:
        return False
    if not archivio.di_prova and sosta.per_la_copia.aspetta(sosta.RITOCCO):
        return False
    return il_ritoccatore(archivio).parti()


def ripara(archivio) -> dict:
    with archivio.scrittura() as connessione:
        lasciati = seguiti.ferma_i_lasciati(connessione)
    fatto = coda.ripara(archivio)
    ripartita = riparti_se_accesa(archivio)
    if lasciati or ripartita:
        registro.evento("ritocco.coda_ripresa", seguiti=lasciati, ripartita=ripartita)
    return {**fatto, "seguiti": lasciati, "ripartita": ripartita}
