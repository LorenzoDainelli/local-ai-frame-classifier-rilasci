from __future__ import annotations

import itertools
import multiprocessing
import queue
import threading
import time
from pathlib import Path

from officina import registro
from officina.descrittori import torcia
from officina.errori import ErroreOfficina
from officina.ritocco import scelta
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


def _con_riserva(sceglitore, fai, sulla_scheda: bool):
    try:
        return fai(sulla_scheda)
    except Exception as guasto:
        if not sulla_scheda or not torcia.memoria_finita(guasto):
            raise
        registro.avviso("ritocco.scheda_piena")
        sceglitore.spegni()
        return fai(False)


def esegui(sceglitore, comando: tuple) -> tuple:
    tipo, numero, *resto = comando
    try:
        if tipo == "guarda":
            chiave, percorso, sulla_scheda = resto
            larga, alta, dove = _con_riserva(
                sceglitore, lambda scheda: sceglitore.guarda(chiave, Path(percorso), scheda),
                sulla_scheda)
            return ("fatto", numero, {"larghezza": larga, "altezza": alta, "dove": dove})
        if tipo == "scegli":
            chiave, percorso, punti, riquadro, sulla_scheda = resto
            fatta = _con_riserva(
                sceglitore, lambda scheda: sceglitore.scegli(chiave, Path(percorso), punti,
                                                             riquadro, scheda),
                sulla_scheda)
            return ("fatto", numero, {"maschera": fatta.maschera, "punteggio": fatta.punteggio,
                                      "larghezza": fatta.larghezza, "altezza": fatta.altezza,
                                      "dove": fatta.dove})
    except Exception as guasto:
        registro.errore("ritocco.scelta_rotta", **registro.dove_si_e_rotto(guasto))
        return ("guasto", numero, {"messaggio": NON_GUARDA,
                                   "dettaglio": registro.passi_del_guasto(guasto)})
    return ("guasto", numero, {"messaggio": NON_GUARDA, "dettaglio": ""})


def _figlio(cartella: str, fabbrica: str, dopo: float, dove_registro: str | None, comandi,
            notizie) -> None:
    if dove_registro:
        registro.imposta(registro.Registro(Path(dove_registro)))
    try:
        sceglitore = in_disparte._trova(fabbrica)(Path(cartella))
        notizie.put(("pronto", None, {"scheda": bool(sceglitore.ha_la_scheda())}))
    except Exception as guasto:
        notizie.put(("guasto", None, {"messaggio": NON_PARTE,
                                      "dettaglio": registro.passi_del_guasto(guasto)}))
        return
    genitore = multiprocessing.parent_process()
    ultimo = time.monotonic()
    while True:
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
        notizie.put(esegui(sceglitore, comando))
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
        self._in_casa = None
        self._cartella: Path | None = None
        self._scheda = False
        self._ultimo = 0.0
        self._sorvegliante: threading.Thread | None = None

    @property
    def acceso(self) -> bool:
        return self._in_casa is not None or (self._processo is not None
                                             and self._processo.is_alive())

    @property
    def ha_la_scheda(self) -> bool:
        return lavori.turno.chi is self.lavoro

    def guarda(self, cartella: Path, chiave: str, percorso: Path) -> dict:
        return self._chiedi(cartella, "guarda", chiave, str(percorso))

    def scegli(self, cartella: Path, chiave: str, percorso: Path, punti: list,
               riquadro) -> dict:
        return self._chiedi(cartella, "scegli", chiave, str(percorso), list(punti), riquadro)

    def chiudi(self) -> None:
        with self._lucchetto:
            self._spegni_tutto()

    def _chiedi(self, cartella: Path, tipo: str, *argomenti) -> dict:
        with self._lucchetto:
            self._accendi(Path(cartella))
            sulla_scheda = self._scheda and lavori.turno.prendi_se_libera(self.lavoro)
            self._ultimo = time.monotonic()
            numero = next(self._numeri)
            try:
                esito = self._manda((tipo, numero, *argomenti, sulla_scheda))
            finally:
                self._ultimo = time.monotonic()
            self._sorveglia()
            tipo, _, dati = esito
            if tipo != "fatto":
                raise ErroreOfficina(dati.get("messaggio") or NON_GUARDA, codice="ritocco_scelta")
            if sulla_scheda and dati.get("dove") == scelta.PROCESSORE:
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
        self._processo, self._notizie = in_disparte._avvia(
            A, _figlio, (str(cartella), self.fabbrica, SI_LIBERA_DOPO,
                         str(dove_registro) if dove_registro else None))
        tipo, _, dati = self._aspetta(None, PER_PARTIRE)
        if tipo != "pronto":
            self._spegni_tutto()
            raise ErroreOfficina(dati.get("messaggio") or NON_PARTE, codice="ritocco_non_parte")
        self._scheda = bool(dati.get("scheda"))

    def _manda(self, comando: tuple) -> tuple:
        if self._in_casa is not None:
            return esegui(self._in_casa, comando)
        in_disparte.manda(*comando, a=A)
        return self._aspetta(comando[1], PER_RISPONDERE)

    def _aspetta(self, numero: int | None, entro: float) -> tuple:
        scadenza = time.monotonic() + entro
        while time.monotonic() < scadenza:
            try:
                tipo, quale, dati = self._notizie.get(timeout=OGNI_QUANTO)
            except queue.Empty:
                if not self._processo.is_alive():
                    self._spento()
                    registro.errore("ritocco.chiuso_da_solo")
                    raise ErroreOfficina(SI_E_CHIUSO, codice="ritocco_chiuso") from None
                continue
            if quale == numero:
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
        self._in_casa = None
        self._processo = None
        self._notizie = None
        self._scheda = False
        lavori.turno.lascia(self.lavoro)

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
            finally:
                self._lucchetto.release()


al_clic = AlClic()
