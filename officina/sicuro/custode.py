from __future__ import annotations

import contextlib
import os
import threading
import time

from officina.errori import ErroreOfficina
from officina.sicuro.chiavetta import Guardiano
from officina.sicuro.copia import Fermato
from officina.sicuro.dentro import _resto, _vero
from officina.sicuro.sottofondo import FERMATO, SPAZIO_FINITO


CHIAVETTA = "chiavetta"
COPIA = "copia"
CONTROLLO = "controllo"
ORDINE = (CHIAVETTA, COPIA, CONTROLLO)
SI_FERMANO = (COPIA, CONTROLLO)

OGNI_GIRO = 2.0
OGNI_COPIA = 3600.0
OGNI_CONTROLLO = 24 * 3600.0

ASPETTO = "aspetto"
COPIO = "copio"
AGGIORNO = "aggiorno"
LAVORO = "lavoro"


def _codice(guasto: BaseException) -> str:
    if isinstance(guasto, ErroreOfficina) and guasto.codice:
        return guasto.codice
    return type(guasto).__name__


class _InFila:

    def __init__(self, custode: Custode, lavoro):
        self._custode = custode
        self.lavoro = lavoro
        self.chiavetta = lavoro.chiavetta

    @property
    def acceso(self) -> bool:
        return self._custode._chiavetta_accesa()

    @property
    def stato(self) -> str:
        return self.lavoro.stato

    @property
    def codice(self) -> str | None:
        return self.lavoro.codice

    @property
    def errore(self) -> str | None:
        return self.lavoro.errore

    def avvia(self, radice) -> bool:
        return self._custode._vuoi(CHIAVETTA, (radice,))

    def ferma(self, aspetta: float | None = None) -> None:
        self._custode._non_vuoi(CHIAVETTA)
        self.lavoro.ferma(aspetta)

    def istantanea(self) -> dict:
        return self.lavoro.istantanea()


class Custode:

    def __init__(self, *, copia=None, chiavetta=None, controllo=None, prima=None,
                 ogni_giro: float = OGNI_GIRO, ogni_copia: float = OGNI_COPIA,
                 ogni_controllo: float = OGNI_CONTROLLO, orologio=time.monotonic,
                 **per_guardiano):
        self.copia = copia
        self.chiavetta = chiavetta
        self.controllo = controllo
        self._lavori = {CHIAVETTA: chiavetta, COPIA: copia, CONTROLLO: controllo}
        self._prima = prima
        self._ogni_giro = ogni_giro
        self._ogni_copia = ogni_copia
        self._ogni_controllo = ogni_controllo
        self._orologio = orologio
        self._cambio = threading.Condition(threading.RLock())
        self._voglie: dict[str, tuple] = {}
        self._rimesse: dict[str, tuple] = {}
        self._ultimi: dict[str, tuple] = {}
        self._da_rivedere: set[str] = set()
        self._fermi: set[str] = set()
        self._utente = None
        self._in_turno = False
        self._con_chiavetta = False
        self._fase: str | None = None
        self._pronto = False
        self._girato = False
        self._prima_fatta = prima is None
        self._in_prima = False
        self._fermo = False
        self._senza_spazio = False
        self._filo: threading.Thread | None = None
        self.problema: str | None = None
        self.problema_iniziale: str | None = None
        self._prossima_copia = orologio()
        self._prossimo_controllo = orologio()
        self.guardiano = (None if chiavetta is None
                          else Guardiano(_InFila(self, chiavetta), **per_guardiano))

    def avvia(self) -> bool:
        with self._cambio:
            if self._fermo or (self._filo is not None and self._filo.is_alive()):
                return False
            self._filo = threading.Thread(target=self._gira, name="archivio-sicuro-custode",
                                          daemon=True)
            self._filo.start()
        if self.guardiano is not None:
            self.guardiano.avvia()
        return True

    def _gira(self) -> None:
        self.comincia()
        while True:
            with self._cambio:
                if self._fermo:
                    return
            self.giro()
            with self._cambio:
                if self._fermo:
                    return
                self._cambio.wait(self._ogni_giro)

    def comincia(self) -> None:
        with self._cambio:
            if self._pronto or self._fermo:
                return
        self._fai_prima()
        with self._cambio:
            self._pronto = True
            self._cambio.notify_all()

    def _fai_prima(self) -> bool:
        if self._prima_fatta:
            return True
        try:
            self._prima()
        except Exception as guasto:
            with self._cambio:
                self.problema_iniziale = _codice(guasto)
            return False
        with self._cambio:
            self._prima_fatta = True
            self.problema_iniziale = None
        return True

    def ferma(self, aspetta: float | None = None) -> bool:
        with self._cambio:
            self._fermo = True
            self._voglie.clear()
            self._rimesse.clear()
            utente = self._utente
            self._cambio.notify_all()
        if self.guardiano is not None:
            self.guardiano.ferma()
        if utente is not None:
            utente.ferma()
        for lavoro in self._lavori.values():
            if lavoro is not None:
                lavoro.ferma()
        if aspetta is None:
            return False
        return self.aspetta_fine(aspetta)

    def aspetta_fine(self, quanto: float | None = None) -> bool:
        fine = None if quanto is None else time.monotonic() + quanto

        def resta() -> float | None:
            return None if fine is None else max(0.0, fine - time.monotonic())

        filo = self._filo
        if filo is not None:
            filo.join(resta())
        if self.guardiano is not None and self._fermo:
            self.guardiano.ferma(resta())
        with self._cambio:
            altri = [lavoro for lavoro in (self._utente, *self._lavori.values())
                     if lavoro is not None]
        for lavoro in altri:
            lavoro.aspetta_fine(resta())
        return ((filo is None or not filo.is_alive())
                and (self.guardiano is None or not self.guardiano.acceso)
                and not any(lavoro.acceso for lavoro in altri))

    def _libero(self) -> bool:
        return (self._pronto and not self._fermo and not self._in_prima
                and not self._in_turno_vivo()
                and (self._utente is None or not self._utente.acceso))

    def _in_turno_vivo(self) -> bool:
        if self._in_turno and (self._utente is None or not self._utente.acceso):
            if self._utente is not None:
                self._utente.turno = None
            self._turno_finito()
        return self._in_turno

    def _turno_finito(self) -> None:
        self._in_turno = False
        self._con_chiavetta = False
        self._fase = None
        self._cambio.notify_all()

    def _acceso(self) -> str | None:
        for nome in ORDINE:
            lavoro = self._lavori[nome]
            if lavoro is not None and lavoro.acceso:
                return nome
        return None

    def _pronti(self) -> list[str]:
        return [nome for nome in ORDINE if nome in self._voglie
                and nome not in self._fermi and self._lavori[nome] is not None
                and (nome != COPIA or self._prima_fatta)]

    def _rivedi(self) -> None:
        for nome in sorted(self._da_rivedere):
            lavoro = self._lavori[nome]
            if lavoro.acceso:
                continue
            self._da_rivedere.discard(nome)
            rimessa = self._rimesse.pop(nome, None)
            if (rimessa is not None and lavoro.stato != FERMATO
                    and self._voglie.get(nome) is rimessa):
                del self._voglie[nome]

    def _ferma_uno(self, nome: str, rimetti: bool = True) -> None:
        lavoro = self._lavori[nome]
        if rimetti and nome not in self._voglie and nome in self._ultimi:
            self._voglie[nome] = self._rimesse[nome] = self._ultimi[nome]
        self._da_rivedere.add(nome)
        lavoro.ferma()

    def _parti_uno(self, nome: str) -> None:
        argomenti = self._voglie.pop(nome)
        self._rimesse.pop(nome, None)
        lavoro = self._lavori[nome]
        if nome == COPIA:
            self._prossima_copia = self._orologio() + self._ogni_copia
            self._senza_spazio = False
        try:
            partito = lavoro.avvia(*argomenti)
        except BaseException:
            self._voglie.setdefault(nome, argomenti)
            raise
        if partito:
            self._ultimi[nome] = argomenti
        else:
            self._voglie.setdefault(nome, argomenti)

    def _ci_sono_radici(self) -> bool:
        return any(not radice["tolta"] for radice in self.copia.elenco.radici())

    def _c_e_da_controllare(self) -> bool:
        return bool(self.controllo.controllore.da_fare())

    def giro(self) -> str | None:
        guasti: list[BaseException] = []
        try:
            esito = self._giro(guasti)
        except Exception as guasto:
            guasti.append(guasto)
            esito = None
        with self._cambio:
            self.problema = _codice(guasti[0]) if guasti else None
        return esito

    @staticmethod
    def _chiedi(domanda, guasti: list[BaseException]) -> bool | None:
        try:
            return bool(domanda())
        except Exception as guasto:
            guasti.append(guasto)
            return None

    def _giro(self, guasti: list[BaseException]) -> str | None:
        adesso = self._orologio()
        with self._cambio:
            if not self._libero():
                return None
            guarda_copia = (self.copia is not None and adesso >= self._prossima_copia
                            and COPIA not in self._voglie and not self.copia.acceso)
            guarda_controllo = (self.controllo is not None
                                and adesso >= self._prossimo_controllo
                                and CONTROLLO not in self._voglie
                                and not self.controllo.acceso)
        copia = self._chiedi(self._ci_sono_radici, guasti) if guarda_copia else None
        controllo = (self._chiedi(self._c_e_da_controllare, guasti) if guarda_controllo
                     else None)
        with self._cambio:
            if self._fermo:
                return None
            self._girato = True
            if copia is not None:
                if copia:
                    self._voglie.setdefault(COPIA, (None, {}))
                else:
                    self._prossima_copia = adesso + self._ogni_copia
            if controllo is not None:
                self._prossimo_controllo = adesso + self._ogni_controllo
                if controllo:
                    self._voglie.setdefault(CONTROLLO, (None,))
            riprova = (not self._prima_fatta and self._libero() and COPIA in self._voglie
                       and COPIA not in self._fermi and self._acceso() is None)
            if riprova:
                self._in_prima = True
        if riprova:
            try:
                self._fai_prima()
            finally:
                with self._cambio:
                    self._in_prima = False
                    self._cambio.notify_all()
        with self._cambio:
            if not self._libero():
                return None
            self._rivedi()
            acceso = self._acceso()
            pronti = self._pronti()
            if acceso is not None:
                if pronti and ORDINE.index(pronti[0]) < ORDINE.index(acceso):
                    self._ferma_uno(acceso)
                elif (acceso == COPIA and self.copia.stato == SPAZIO_FINITO
                      and any(ORDINE.index(nome) > ORDINE.index(COPIA) for nome in pronti)):
                    self._senza_spazio = True
                    self._voglie.pop(COPIA, None)
                    self._rimesse.pop(COPIA, None)
                    self._ferma_uno(COPIA, rimetti=False)
                    self._prossima_copia = adesso + self._ogni_copia
                return acceso
            if not pronti:
                return None
            self._parti_uno(pronti[0])
            return pronti[0]

    def _vuoi(self, nome: str, argomenti: tuple) -> bool:
        with self._cambio:
            if self._fermo:
                return False
            self._voglie[nome] = argomenti
            self._rimesse.pop(nome, None)
            self._cambio.notify_all()
            return True

    def _non_vuoi(self, nome: str) -> None:
        with self._cambio:
            self._voglie.pop(nome, None)
            self._rimesse.pop(nome, None)

    def _chiavetta_accesa(self) -> bool:
        with self._cambio:
            return (CHIAVETTA in self._voglie or self.chiavetta.acceso
                    or (self._con_chiavetta and self._in_turno_vivo()))

    def copia_ora(self, grandezze: dict[str, int] | None = None) -> None:
        if self.copia is None:
            return
        with self._cambio:
            if self._fermo:
                return
            self._voglie[COPIA] = (None, dict(grandezze or {}))
            self._rimesse.pop(COPIA, None)
            self._cambio.notify_all()

    def copia_voluta(self) -> bool | None:
        with self._cambio:
            if self.copia is None or self._fermo:
                return False
            if not self._girato:
                return None
            if not self._prima_fatta:
                return False
            if COPIA in self._fermi:
                return True
            if self.copia.acceso:
                return self.copia.stato != SPAZIO_FINITO
            return COPIA in self._voglie

    def controlla_ora(self) -> None:
        if self.controllo is None:
            return
        with self._cambio:
            if self._fermo:
                return
            self._voglie[CONTROLLO] = (None,)
            self._rimesse.pop(CONTROLLO, None)
            self._cambio.notify_all()

    def pausa(self, nome: str) -> None:
        if nome not in SI_FERMANO:
            raise ValueError(nome)
        with self._cambio:
            self._fermi.add(nome)
            lavoro = self._lavori[nome]
            if lavoro is not None and lavoro.acceso and not self._in_turno_vivo():
                self._ferma_uno(nome)
            self._cambio.notify_all()

    def riprendi(self, nome: str) -> None:
        if nome not in SI_FERMANO:
            raise ValueError(nome)
        with self._cambio:
            self._fermi.discard(nome)
            self._cambio.notify_all()

    def fai(self, lavoro, *argomenti, chiavetta: bool = False) -> bool:
        return self._fai(lavoro, argomenti, chiavetta, None)

    def via_libera(self, fresco, percorsi) -> bool:
        percorsi = [os.fspath(percorso) for percorso in percorsi]
        return self._fai(fresco, (percorsi,), True, percorsi)

    def _fai(self, lavoro, argomenti: tuple, chiavetta: bool, novita) -> bool:
        if any(lavoro is altro for altro in self._lavori.values()):
            raise ValueError(lavoro)
        with self._cambio:
            if self._fermo:
                raise ErroreOfficina("L'Archivio sicuro è chiuso: aprilo e riprova.",
                                     codice="archivio_chiuso")
            if not self._pronto or self._in_prima:
                raise ErroreOfficina(
                    "L'archivio si sta preparando: aspetta un attimo e riprova.",
                    codice="occupato")
            if self._in_turno_vivo() or (self._utente is not None and self._utente.acceso):
                raise ErroreOfficina(
                    "L'archivio sta già facendo un'altra cosa che hai chiesto: aspetta "
                    "che finisca e poi riprova.", codice="occupato")
            self._in_turno = True
            self._con_chiavetta = chiavetta
            self._fase = ASPETTO
            lavoro.turno = lambda: self._turno(lavoro, novita)
            try:
                partito = lavoro.avvia(*argomenti)
            except BaseException:
                lavoro.turno = None
                self._turno_finito()
                raise
            if not partito:
                lavoro.turno = None
                self._turno_finito()
                return False
            self._utente = lavoro
            return True

    @contextlib.contextmanager
    def _turno(self, lavoro, novita):
        try:
            self._fai_posto(lavoro)
            if novita is not None:
                self._prima_le_novita(lavoro, novita)
            with self._cambio:
                self._fase = LAVORO
            yield
        finally:
            lavoro.turno = None
            with self._cambio:
                self._turno_finito()

    def _fai_posto(self, lavoro) -> None:
        with self._cambio:
            for nome in ORDINE:
                altro = self._lavori[nome]
                if altro is not None and altro.acceso:
                    self._ferma_uno(nome)
        for nome in ORDINE:
            altro = self._lavori[nome]
            if altro is not None:
                lavoro.segui(altro)
        with self._cambio:
            self._rivedi()

    def _radici_di(self, percorsi: list[str]) -> list[dict]:
        veri = []
        for percorso in percorsi:
            try:
                veri.append(_vero(percorso))
            except (OSError, ValueError):
                continue
        scelte = []
        for radice in self.copia.elenco.radici():
            if radice["tolta"]:
                continue
            try:
                base = _vero(radice["percorso"])
            except (OSError, ValueError):
                continue
            if any(_resto(base, vero) is not None for vero in veri):
                scelte.append(radice)
        return scelte

    def _prima_le_novita(self, lavoro, percorsi: list[str]) -> None:
        if self.copia is not None:
            radici = self._radici_di(percorsi)
            if radici and self._fai_prima():
                with self._cambio:
                    self._fase = COPIO
                self._dentro(lavoro, COPIA, (radici, {}), (None, {}),
                             basta=lambda: self.copia.stato == SPAZIO_FINITO)
        if self.guardiano is None:
            return
        with self._cambio:
            self._fase = AGGIORNO
            in_fila = CHIAVETTA in self._voglie
        if not in_fila:
            self._chiedi_la_chiavetta()
        with self._cambio:
            argomenti = self._voglie.get(CHIAVETTA)
        if argomenti is not None:
            self._dentro(lavoro, CHIAVETTA, argomenti, argomenti)

    def _chiedi_la_chiavetta(self) -> None:
        self.guardiano.ricomincia()
        with self._cambio:
            self._con_chiavetta = False
        try:
            self.guardiano.giro()
        except Exception:
            pass
        finally:
            with self._cambio:
                self._con_chiavetta = True

    def _dentro(self, lavoro, nome: str, argomenti: tuple, rimetti: tuple,
                basta=None) -> None:
        altro = self._lavori[nome]
        with self._cambio:
            if self._fermo:
                raise Fermato
            tolta = self._voglie.get(nome) is argomenti
            if tolta:
                del self._voglie[nome]
                self._rimesse.pop(nome, None)
            try:
                partito = altro.avvia(*argomenti)
            except BaseException:
                if tolta:
                    self._voglie.setdefault(nome, argomenti)
                raise
            if not partito:
                if tolta:
                    self._voglie.setdefault(nome, argomenti)
                return
        try:
            lavoro.segui(altro, basta)
        except BaseException:
            with self._cambio:
                if not self._fermo and nome not in self._voglie:
                    self._voglie[nome] = self._rimesse[nome] = rimetti
                self._da_rivedere.add(nome)
            altro.ferma()
            raise
        if altro.acceso:
            with self._cambio:
                self._senza_spazio = True
            altro.ferma()
            lavoro.segui(altro)

    def istantanea(self) -> dict:
        with self._cambio:
            utente = self._utente
            return {
                "pronto": self._pronto,
                "ripreso": self._prima_fatta,
                "chiuso": self._fermo,
                "turno": utente.nome if utente is not None and utente.acceso else None,
                "fase": self._fase,
                "acceso": self._acceso(),
                "in_fila": [nome for nome in ORDINE if nome in self._voglie],
                "in_pausa": [nome for nome in ORDINE if nome in self._fermi],
                "senza_spazio": self._senza_spazio,
                "problema": self.problema,
                "problema_iniziale": self.problema_iniziale,
            }


__all__ = ["AGGIORNO", "ASPETTO", "CHIAVETTA", "CONTROLLO", "COPIA", "COPIO", "Custode",
           "LAVORO", "ORDINE"]
