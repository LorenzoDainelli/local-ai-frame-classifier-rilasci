from __future__ import annotations

import contextlib
import threading
import time

from officina.errori import ErroreOfficina
from officina.sicuro import sveglia
from officina.sicuro.copia import DiscoArchivioGuasto, Fermato


PAUSA_SE_USI = 0.05
SEGUI = 0.05

FERMO = "fermo"
IN_CORSO = "in_corso"
IN_PAUSA = "in_pausa"
SPAZIO_FINITO = "spazio_finito"
FINITO = "finito"
FERMATO = "fermato"
GUASTO = "guasto"
ERRORE = "errore"
ATTIVI = (IN_CORSO, IN_PAUSA, SPAZIO_FINITO)


class Sottofondo:

    nome = "archivio-sicuro"

    def __init__(self, *, sveglio=sveglia.sveglio, rallenta=None,
                 pausa_se_usi: float = PAUSA_SE_USI):
        self._sveglio = sveglio
        self._rallenta = rallenta
        self._pausa_se_usi = pausa_se_usi
        self._cambio = threading.Condition(threading.Lock())
        self._fermo = False
        self._in_pausa = False
        self._senza_spazio = False
        self._filo: threading.Thread | None = None
        self.stato = FERMO
        self.errore: str | None = None
        self.codice: str | None = None
        self.turno = None

    @property
    def acceso(self) -> bool:
        return self._filo is not None and self._filo.is_alive()

    def _parti(self, *argomenti) -> bool:
        with self._cambio:
            if self.acceso:
                return False
            self._fermo = False
            self._in_pausa = False
            self._senza_spazio = False
            self.stato = IN_CORSO
            self.errore = None
            self.codice = None
            self._azzera()
            self._filo = threading.Thread(target=self._gira, args=argomenti,
                                          name=self.nome, daemon=True)
            self._filo.start()
        return True

    def _azzera(self) -> None:
        pass

    def pausa(self) -> None:
        with self._cambio:
            self._in_pausa = True
            if self.stato == IN_CORSO:
                self.stato = IN_PAUSA
            self._cambio.notify_all()

    def riprendi(self) -> None:
        with self._cambio:
            self._in_pausa = False
            if self.stato == IN_PAUSA:
                self.stato = IN_CORSO
            self._cambio.notify_all()

    def ferma(self, aspetta: float | None = None) -> None:
        with self._cambio:
            self._fermo = True
            self._cambio.notify_all()
        if aspetta is not None:
            self.aspetta_fine(aspetta)

    def aspetta_fine(self, quanto: float | None = None) -> bool:
        filo = self._filo
        if filo is not None:
            filo.join(quanto)
        return not self.acceso

    def _metti_stato(self) -> None:
        if self._senza_spazio:
            self.stato = SPAZIO_FINITO
        elif self._in_pausa:
            self.stato = IN_PAUSA
        else:
            self.stato = IN_CORSO

    def _aspetta(self) -> None:
        with self._cambio:
            while True:
                if self._fermo:
                    raise Fermato
                if not self._in_pausa:
                    break
                self._cambio.wait()
        if self._rallenta is not None:
            try:
                piano = self._rallenta()
            except Exception:
                piano = False
            if piano:
                self._dormi_fermabile(self._pausa_se_usi)

    def _dormi_fermabile(self, secondi: float) -> None:
        fine = time.monotonic() + max(0.0, secondi)
        with self._cambio:
            while not self._fermo:
                resta = fine - time.monotonic()
                if resta <= 0:
                    return
                self._cambio.wait(resta)
            raise Fermato

    def _aspetta_che(self, basta, ogni: float) -> None:
        with self._cambio:
            self._senza_spazio = True
            self._metti_stato()
        try:
            while True:
                with self._cambio:
                    if self._fermo:
                        raise Fermato
                    self._cambio.wait(ogni)
                    if self._fermo:
                        raise Fermato
                if basta():
                    return
        finally:
            with self._cambio:
                self._senza_spazio = False
                self._metti_stato()

    def segui(self, altro, basta=None) -> None:
        while altro.acceso:
            with self._cambio:
                if self._fermo:
                    raise Fermato
                in_pausa = self._in_pausa
            if in_pausa:
                altro.pausa()
            else:
                altro.riprendi()
            if basta is not None and basta():
                return
            self._dormi_fermabile(SEGUI)

    def _col_turno(self):
        turno = self.turno
        if turno is None:
            return contextlib.nullcontext()
        return turno()

    def _lavora(self, *argomenti) -> None:
        raise NotImplementedError

    def _alla_fine(self, esito: str) -> None:
        pass

    def _gira(self, *argomenti) -> None:
        esito, errore = FINITO, None
        try:
            with self._sveglio(), self._col_turno():
                self._lavora(*argomenti)
        except Fermato:
            esito = FERMATO
        except DiscoArchivioGuasto as guasto:
            esito, errore = GUASTO, guasto
        except Exception as guasto:
            esito, errore = ERRORE, guasto
        finally:
            try:
                self._alla_fine(esito)
            except Exception as guasto:
                if errore is None and esito == FINITO:
                    esito, errore = ERRORE, guasto
            with self._cambio:
                self._finito()
                self.stato = esito
                if errore is not None:
                    self.errore = str(errore)
                    self.codice = (errore.codice if isinstance(errore, ErroreOfficina)
                                   else type(errore).__name__)
                self._cambio.notify_all()

    def _finito(self) -> None:
        pass
