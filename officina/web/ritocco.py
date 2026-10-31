from __future__ import annotations

import contextlib
import itertools
import multiprocessing
import queue
import threading
import time
from pathlib import Path

from officina import registro
from officina.descrittori import torcia
from officina.errori import ErroreOfficina
from officina.ritocco import copia, filmato, scelta
from officina.sicuro import dall_archivio, sportello
from officina.sicuro.dall_archivio import DallArchivio
from officina.web import in_disparte, lavori

A = "ritocco"
FABBRICA = "officina.ritocco.scelta:Sceglitore"
SI_LIBERA_DOPO = 600.0
OGNI_QUANTO = 0.5
PER_PARTIRE = 300.0
PER_RISPONDERE = 900.0
PER_CHIUDERSI = 5.0

NON_PARTE = ("Lo strumento per scegliere non è riuscito a partire. Lo scatto non è "
             "stato toccato: riprova tra poco.")
SI_E_CHIUSO = ("Lo strumento per scegliere si è chiuso da solo. Lo scatto non è stato "
               "toccato: riprova.")
NON_RISPONDE = ("Lo strumento per scegliere non risponde. Lo scatto non è stato toccato: "
                "riprova.")
NON_GUARDA = ("Non sono riuscito a guardare questo scatto per sceglierne una parte. Lo "
              "scatto non è stato toccato.")
NON_SEGUE = ("Non sono riuscito a seguire la parte scelta nel video. Il video non è stato "
             "toccato.")
SCHEDA_OCCUPATA = "La scheda video è occupata: lo seguo appena si libera."
OGNI_QUANTI = 8
FERMATI = ("fermati", "ferma", "basta")
DI_MANO = ("guarda", "scegli", "prepara")
PRIMA_DI_RIPRENDERE = 3.0


class SchedaOccupata(ErroreOfficina):
    codice = "ritocco_scheda_occupata"



def _con_riserva(sceglitore, fai, sulla_scheda: bool):
    try:
        return fai(sulla_scheda)
    except Exception as guasto:
        if not sulla_scheda or not torcia.memoria_finita(guasto):
            raise
        registro.avviso("ritocco.scheda_piena")
        sceglitore.spegni()
        return fai(False)


def _sul_fotogramma(fotogramma) -> dict:
    return {} if fotogramma is None else {"fotogramma": int(fotogramma)}


def _mai() -> bool:
    return False


def _da_mandare(percorso):
    if isinstance(percorso, DallArchivio):
        return {"impronta": percorso.blake2b, "dimensione": percorso.dimensione,
                "nome": percorso.nome, "intero": percorso.intero}
    return str(percorso)


def _servizio_delle_foto():
    lontano = sportello.qui()
    if lontano is not None:
        return dall_archivio.TROVATA, lontano
    from officina.programma import archivio_sicuro

    return archivio_sicuro.per_le_foto()


@contextlib.contextmanager
def _la_foto(percorso):
    if not isinstance(percorso, dict):
        yield Path(percorso)
        return
    perche, servizio = _servizio_delle_foto()
    trovata = copia.ritrova(perche, servizio, str(percorso["impronta"]),
                            int(percorso["dimensione"]), str(percorso["nome"]),
                            bool(percorso["intero"]))
    with copia.leggendo(trovata):
        yield trovata


def _il_codice(guasto: ErroreOfficina) -> dict:
    if isinstance(guasto, copia.RitoccoFermato):
        return {"codice": guasto.codice}
    return {}


def _nome_dell_archivio() -> str | None:
    from officina.archivio import accesso

    try:
        return accesso.aperto().dove.nome
    except ErroreOfficina:
        return None


def _prepara(sceglitore, numero, chiave, percorso, notizia, fermati) -> tuple:
    def al_passo(fatti: int, attesi: int) -> None:
        if fatti % OGNI_QUANTI == 0:
            notizia(("passo", numero, {"preparati": fatti, "attesi": attesi}))

    pronto = sceglitore.prepara(chiave, Path(percorso), al_passo, fermati)
    return ("fatto", numero, {"quanti": pronto.quanti, "larghezza": pronto.larghezza,
                              "altezza": pronto.altezza, "istanti": list(pronto.istanti),
                              "inizio": int(getattr(pronto, "inizio", 0))})


def _segui(sceglitore, numero, chiave, percorso, scelte, tratti, sulla_scheda, notizia,
           fermati) -> tuple:
    from officina.ritocco import segui

    pila: list = []

    def al_fotogramma(indice: int, da: int, maschera: bytes, sicurezza: float) -> None:
        pila.append((int(indice), int(da), maschera, round(float(sicurezza), 4)))
        if len(pila) >= OGNI_QUANTI:
            notizia(("passo", numero, {"fotogrammi": list(pila)}))
            pila.clear()

    def al_passo(fatti: int, attesi: int) -> None:
        if fatti % OGNI_QUANTI == 0:
            notizia(("passo", numero, {"preparati": fatti, "attesi": attesi}))

    pezzi = [segui.Tratto(*tratto) for tratto in tratti]
    dati = _con_riserva(
        sceglitore, lambda scheda: sceglitore.segui(chiave, Path(percorso), scelte, pezzi,
                                                    scheda, al_fotogramma, al_passo, fermati),
        sulla_scheda)
    if pila:
        notizia(("passo", numero, {"fotogrammi": list(pila)}))
    return ("fatto", numero, {**dati, "fermato": bool(fermati())})


def esegui(sceglitore, comando: tuple, notizia=None, fermati=None) -> tuple:
    tipo, numero, *resto = comando
    notizia = notizia or (lambda _: None)
    fermati = fermati or _mai
    messaggio = NON_SEGUE if tipo in ("prepara", "segui") else NON_GUARDA
    try:
        if tipo == "guarda":
            chiave, percorso, fotogramma, sulla_scheda = resto
            with _la_foto(percorso) as foto:
                larga, alta, dove = _con_riserva(
                    sceglitore, lambda scheda: sceglitore.guarda(
                        chiave, foto, scheda, **_sul_fotogramma(fotogramma)),
                    sulla_scheda)
            return ("fatto", numero, {"larghezza": larga, "altezza": alta, "dove": dove})
        if tipo == "scegli":
            chiave, percorso, punti, riquadro, fotogramma, sulla_scheda = resto
            with _la_foto(percorso) as foto:
                fatta = _con_riserva(
                    sceglitore, lambda scheda: sceglitore.scegli(
                        chiave, foto, punti, riquadro, scheda,
                        **_sul_fotogramma(fotogramma)),
                    sulla_scheda)
            return ("fatto", numero, {"maschera": fatta.maschera, "punteggio": fatta.punteggio,
                                      "larghezza": fatta.larghezza, "altezza": fatta.altezza,
                                      "dove": fatta.dove})
        if tipo == "prepara":
            chiave, percorso, _ = resto
            return _prepara(sceglitore, numero, chiave, percorso, notizia, fermati)
        if tipo == "segui":
            chiave, percorso, scelte, tratti, sulla_scheda = resto
            return _segui(sceglitore, numero, chiave, percorso, scelte, tratti, sulla_scheda,
                          notizia, fermati)
    except filmato.Fermato:
        return ("fatto", numero, {"fermato": True})
    except ErroreOfficina as guasto:
        return ("guasto", numero, {"messaggio": guasto.messaggio, "dettaglio": "",
                                   **_il_codice(guasto)})
    except Exception as guasto:
        registro.errore("ritocco.scelta_rotta", **registro.dove_si_e_rotto(guasto))
        return ("guasto", numero, {"messaggio": messaggio,
                                   "dettaglio": registro.passi_del_guasto(guasto)})
    return ("guasto", numero, {"messaggio": messaggio, "dettaglio": ""})


def _figlio(cartella: str, fabbrica: str, dopo: float, dove_registro: str | None, comandi,
            notizie, linea: tuple | None = None) -> None:
    if dove_registro:
        registro.imposta(registro.Registro(Path(dove_registro)))
    if linea is not None:
        sportello.installa(notizie, *linea)
    try:
        sceglitore = in_disparte._trova(fabbrica)(Path(cartella))
        notizie.put(("pronto", None, {"scheda": bool(sceglitore.ha_la_scheda())}))
    except Exception as guasto:
        notizie.put(("guasto", None, {"messaggio": NON_PARTE,
                                      "dettaglio": registro.passi_del_guasto(guasto)}))
        return
    genitore = multiprocessing.parent_process()
    ultimo = time.monotonic()
    chiudi = [False]
    fermato = [False]

    def fermati() -> bool:
        while not fermato[0]:
            try:
                arrivato = comandi.get_nowait()
            except queue.Empty:
                break
            if arrivato[0] in FERMATI:
                fermato[0] = True
                chiudi[0] = chiudi[0] or arrivato[0] != "fermati"
        if genitore is not None and not genitore.is_alive():
            fermato[0] = chiudi[0] = True
        return fermato[0]

    while not chiudi[0]:
        try:
            comando = comandi.get(timeout=OGNI_QUANTO)
        except queue.Empty:
            if genitore is not None and not genitore.is_alive():
                break
            if time.monotonic() - ultimo > dopo:
                break
            continue
        if comando[0] in ("ferma", "basta"):
            break
        if comando[0] == "fermati":
            continue
        fermato[0] = False
        notizie.put(esegui(sceglitore, comando, notizie.put, fermati))
        ultimo = time.monotonic()
    try:
        sceglitore.spegni()
    except Exception as guasto:
        registro.avviso("ritocco.non_spento", **registro.dove_si_e_rotto(guasto))


class AlClic:

    def __init__(self, fabbrica: str = FABBRICA):
        self.fabbrica = fabbrica
        self.lavoro = lavori.Lavoro(A)
        self._lucchetto = threading.Lock()
        self._numeri = itertools.count(1)
        self._processo = None
        self._notizie = None
        self._sportello = None
        self._in_casa = None
        self._cartella: Path | None = None
        self._scheda = False
        self._ultimo = 0.0
        self._sorvegliante: threading.Thread | None = None
        self._fermo = threading.Event()
        self._sfondo: lavori.Lavoro | None = None
        self._in_sfondo = False
        self._seguendo = False
        self._ceduto = False
        self._mani = 0
        self._ultima_mano = 0.0
        self._conta_le_mani = threading.Lock()

    @property
    def acceso(self) -> bool:
        return self._in_casa is not None or (self._processo is not None
                                             and self._processo.is_alive())

    @property
    def ha_la_scheda(self) -> bool:
        return lavori.turno.chi is self.lavoro

    @property
    def ha_una_scheda(self) -> bool:
        return self._scheda

    def guarda(self, cartella: Path, chiave: str, percorso,
               fotogramma: int | None = None) -> dict:
        return self._chiedi(cartella, "guarda", chiave, _da_mandare(percorso), fotogramma)

    def scegli(self, cartella: Path, chiave: str, percorso, punti: list,
               riquadro, fotogramma: int | None = None) -> dict:
        return self._chiedi(cartella, "scegli", chiave, _da_mandare(percorso), list(punti),
                            riquadro, fotogramma)

    def prepara(self, cartella: Path, chiave: str, percorso: Path, al_passo=None) -> dict:
        return self._chiedi(cartella, "prepara", chiave, str(percorso), al_passo=al_passo,
                            scheda=False)

    def segui(self, cartella: Path, chiave: str, percorso: Path, scelte: dict, tratti: list,
              al_passo=None, scheda: bool | None = None, sfondo=None) -> dict:
        pezzi = [(tratto.da, tratto.inizio, tratto.fine) for tratto in tratti]
        return self._chiedi(cartella, "segui", chiave, str(percorso), dict(scelte), pezzi,
                            al_passo=al_passo, scheda=scheda, sfondo=sfondo)

    def ferma(self) -> None:
        self._fermo.set()
        if self._processo is not None:
            in_disparte.manda("fermati", a=A)

    def ferma_lo_sfondo(self) -> None:
        if self._in_sfondo:
            self.ferma()

    def lascia_lo_sfondo(self, sfondo) -> None:
        if lavori.turno.chi is not sfondo:
            if self._sfondo is sfondo:
                self._sfondo = None
            return
        with self._lucchetto:
            if self._sfondo is sfondo:
                self._sfondo = None
            if lavori.turno.chi is sfondo:
                if self._scheda:
                    self._spegni_tutto()
                lavori.turno.lascia(sfondo)

    def chiudi(self) -> None:
        if self._in_sfondo:
            return
        if self._seguendo:
            self.ferma()
        with self._lucchetto:
            self._spegni_tutto()

    def ha_ceduto(self) -> bool:
        ceduto, self._ceduto = self._ceduto, False
        return ceduto

    def lascia_passare(self, quanto: float | None = None, fermati=_mai) -> None:
        quanto = PRIMA_DI_RIPRENDERE if quanto is None else quanto
        while not fermati():
            calma = time.monotonic() - self._ultima_mano
            if self._mani == 0 and calma >= quanto:
                return
            time.sleep(min(OGNI_QUANTO, max(0.05, quanto - calma)))

    def _fai_passare(self, sfondo) -> None:
        if sfondo is not None:
            return
        if self._in_sfondo:
            self.ferma()
        elif self._seguendo:
            self._ceduto = True
            self.ferma()

    def _entra(self, sfondo, di_mano: bool) -> None:
        while not self._lucchetto.acquire(timeout=0.1):
            if sfondo is None and (self._in_sfondo or (di_mano and self._seguendo)):
                self._fai_passare(sfondo)

    def _chiedi(self, cartella: Path, tipo: str, *argomenti, al_passo=None,
                scheda: bool | None = None, sfondo=None) -> dict:
        di_mano = sfondo is None and tipo in DI_MANO
        if di_mano:
            self._una_mano(1)
        try:
            if sfondo is None and (self._in_sfondo or (di_mano and self._seguendo)):
                self._fai_passare(sfondo)
            self._entra(sfondo, di_mano)
            try:
                return self._dentro(cartella, tipo, argomenti, al_passo, scheda, sfondo)
            finally:
                self._lucchetto.release()
        finally:
            if di_mano:
                self._una_mano(-1)

    def _una_mano(self, quante: int) -> None:
        with self._conta_le_mani:
            self._mani += quante
            self._ultima_mano = time.monotonic()

    def _dentro(self, cartella: Path, tipo: str, argomenti: tuple, al_passo,
                scheda: bool | None, sfondo) -> dict:
        if sfondo is not None:
            if lavori.turno.chi is not sfondo:
                raise SchedaOccupata(SCHEDA_OCCUPATA)
            self._sfondo = sfondo
        elif self._sfondo is not None:
            lavori.turno.passa(self._sfondo, self.lavoro)
        self._accendi(Path(cartella))
        if sfondo is not None:
            sulla_scheda = self._scheda
        elif scheda is None:
            sulla_scheda = self._scheda and lavori.turno.prendi_se_libera(self.lavoro)
            if tipo == "segui" and not sulla_scheda:
                raise SchedaOccupata(SCHEDA_OCCUPATA)
        else:
            sulla_scheda = bool(scheda) and self._scheda
        self._ultimo = time.monotonic()
        self._fermo.clear()
        numero = next(self._numeri)
        self._in_sfondo = sfondo is not None
        self._seguendo = sfondo is None and tipo == "segui"
        if self._seguendo:
            self._ceduto = False
        try:
            esito = self._manda((tipo, numero, *argomenti, sulla_scheda), al_passo)
        finally:
            self._in_sfondo = False
            self._seguendo = False
            self._ultimo = time.monotonic()
        self._sorveglia()
        tipo_esito, _, dati = esito
        if tipo_esito != "fatto":
            raise ErroreOfficina(dati.get("messaggio") or NON_GUARDA,
                                 codice=dati.get("codice") or "ritocco_scelta")
        if scheda is None and sfondo is None and sulla_scheda and \
                dati.get("dove") == scelta.PROCESSORE:
            lavori.turno.lascia(self.lavoro)
        return dati

    def _accendi(self, cartella: Path) -> None:
        if self.acceso and cartella == self._cartella:
            return
        self._spegni_tutto()
        self._cartella = cartella
        if not in_disparte.A_PARTE:
            try:
                self._in_casa = in_disparte._trova(self.fabbrica)(cartella)
                self._scheda = bool(self._in_casa.ha_la_scheda())
            except Exception as guasto:
                self._spento()
                registro.errore("ritocco.non_parte", **registro.dove_si_e_rotto(guasto))
                raise ErroreOfficina(NON_PARTE, codice="ritocco_non_parte") from guasto
            return
        dove_registro = registro.attivo().cartella
        self._processo, self._notizie, self._sportello = in_disparte._avvia_con_lo_sportello(
            A, _figlio, (str(cartella), self.fabbrica, SI_LIBERA_DOPO,
                         str(dove_registro) if dove_registro else None),
            _nome_dell_archivio())
        tipo, _, dati = self._aspetta(None, PER_PARTIRE)
        if tipo != "pronto":
            self._spegni_tutto()
            raise ErroreOfficina(dati.get("messaggio") or NON_PARTE, codice="ritocco_non_parte")
        self._scheda = bool(dati.get("scheda"))

    def _manda(self, comando: tuple, al_passo=None) -> tuple:
        if self._in_casa is not None:
            def notizia(arrivata: tuple) -> None:
                if al_passo is not None and arrivata[0] == "passo":
                    al_passo(arrivata[2])

            return esegui(self._in_casa, comando, notizia, self._fermo.is_set)
        in_disparte.manda(*comando, a=A)
        return self._aspetta(comando[1], PER_RISPONDERE, al_passo)

    def _aspetta(self, numero: int | None, entro: float, al_passo=None) -> tuple:
        scadenza = time.monotonic() + entro
        while time.monotonic() < scadenza:
            if self._sportello is not None:
                self._sportello.controlla()
            try:
                tipo, quale, dati = self._notizie.get(timeout=OGNI_QUANTO)
            except queue.Empty:
                if not self._processo.is_alive():
                    self._spento()
                    registro.errore("ritocco.chiuso_da_solo")
                    raise ErroreOfficina(SI_E_CHIUSO, codice="ritocco_chiuso") from None
                continue
            if tipo == "archivio":
                if self._sportello is not None:
                    self._sportello.ricevi(dati)
                continue
            if quale != numero:
                continue
            if tipo == "passo":
                scadenza = time.monotonic() + entro
                self._ultimo = time.monotonic()
                if al_passo is not None:
                    al_passo(dati)
                continue
            return tipo, quale, dati
        self._spegni_tutto()
        registro.errore("ritocco.non_risponde")
        raise ErroreOfficina(NON_RISPONDE, codice="ritocco_lento")

    def _spegni_tutto(self) -> None:
        if self._in_casa is not None:
            try:
                self._in_casa.spegni()
            except Exception as guasto:
                registro.avviso("ritocco.non_spento", **registro.dove_si_e_rotto(guasto))
        processo = self._processo
        if processo is not None:
            in_disparte.manda("basta", a=A)
            processo.join(timeout=PER_CHIUDERSI)
            if processo.is_alive():
                processo.terminate()
                processo.join(timeout=2.0)
        self._spento()

    def _spento(self) -> None:
        allo_sportello, self._sportello = self._sportello, None
        self._in_casa = None
        self._processo = None
        self._notizie = None
        self._scheda = False
        lavori.turno.lascia(self.lavoro)
        if allo_sportello is not None:
            try:
                allo_sportello.chiudi()
            except Exception as guasto:
                registro.avviso("ritocco.sportello_non_chiuso",
                                **registro.dove_si_e_rotto(guasto))

    def _sorveglia(self) -> None:
        if self._sorvegliante is not None and self._sorvegliante.is_alive():
            return
        self._sorvegliante = threading.Thread(target=self._guarda_il_tempo, name=A,
                                              daemon=True)
        self._sorvegliante.start()

    def _guarda_il_tempo(self) -> None:
        while True:
            time.sleep(OGNI_QUANTO)
            if not self._lucchetto.acquire(blocking=False):
                continue
            try:
                if not self.acceso:
                    self._spento()
                    return
                if time.monotonic() - self._ultimo > SI_LIBERA_DOPO:
                    registro.evento("ritocco.scheda_liberata")
                    self._spegni_tutto()
                    return
            except Exception as errore:
                registro.errore("ritocco.sorvegliante", **registro.dove_si_e_rotto(errore))
            finally:
                self._lucchetto.release()


al_clic = AlClic()
