from __future__ import annotations

import ipaddress
import threading
import time
from dataclasses import dataclass

from officina import forziere, registro

NON_E_ATTIVITA = ("/api/lavori", "/api/coda", "/api/importazione",
                  "/api/telefono", "/statici/", "/miniatura/")

PASSA_COMUNQUE = ("/blocco", "/statici/")


@dataclass
class Stato:
    dopo_minuti: int = 0
    bloccato: bool = False
    ultimo_movimento: float = 0.0


@dataclass
class _Schermo:
    bloccato: bool = False
    ultimo: float = 0.0
    usato: float | None = None


class Guardia:

    def __init__(self) -> None:
        self._lucchetto = threading.Lock()
        self._schermi: dict[str, _Schermo] = {}

    def _suo(self, chi: str) -> _Schermo:
        schermo = self._schermi.get(chi)
        if schermo is None:
            schermo = _Schermo(ultimo=time.monotonic())
            self._schermi[chi] = schermo
        return schermo


    def stato(self, chi: str, dopo_minuti: int) -> Stato:
        with self._lucchetto:
            schermo = self._suo(chi)
            return Stato(dopo_minuti=dopo_minuti, bloccato=schermo.bloccato,
                         ultimo_movimento=schermo.ultimo)

    def e_bloccato(self, chi: str) -> bool:
        with self._lucchetto:
            return self._suo(chi).bloccato


    def visto_qualcuno(self, chi: str) -> None:
        with self._lucchetto:
            self._suo(chi).ultimo = time.monotonic()

    def usato_adesso(self, chi: str) -> None:
        with self._lucchetto:
            self._suo(chi).usato = time.monotonic()

    def usato_da_poco(self, secondi: float) -> bool:
        adesso = time.monotonic()
        with self._lucchetto:
            return any(schermo.usato is not None and adesso - schermo.usato < secondi
                       for schermo in self._schermi.values())

    def controlla(self, chi: str, dopo_minuti: int, acceso: bool) -> bool:
        if not acceso or dopo_minuti <= 0:
            with self._lucchetto:
                for schermo in self._schermi.values():
                    schermo.bloccato = False
                self._suo(chi).bloccato = False
            return False
        with self._lucchetto:
            schermo = self._suo(chi)
            if schermo.bloccato:
                return True
            if time.monotonic() - schermo.ultimo >= dopo_minuti * 60:
                schermo.bloccato = True
                registro.evento("blocco.scattato")
                return True
            return False


    def blocca_adesso(self, chi: str) -> None:
        with self._lucchetto:
            schermo = self._suo(chi)
            if not schermo.bloccato:
                schermo.bloccato = True
                registro.evento("blocco.scattato")

    def sblocca(self, chi: str, posizione, password: str) -> bool:
        if not forziere.per(posizione).la_password_e_giusta(password):
            registro.avviso("blocco.password_sbagliata")
            return False
        with self._lucchetto:
            schermo = self._suo(chi)
            schermo.bloccato = False
            schermo.ultimo = time.monotonic()
        registro.evento("blocco.aperto")
        return True


    def dimentica_tutti(self) -> None:
        with self._lucchetto:
            self._schermi.clear()


guardia = Guardia()


def chi_e(richiesta) -> str:
    cliente = richiesta.client.host if richiesta.client else "?"
    try:
        if ipaddress.ip_address(cliente).is_loopback:
            return "qui"
    except ValueError:
        pass
    return cliente


def passa_comunque(percorso: str) -> bool:
    return any(percorso.startswith(pezzo) for pezzo in PASSA_COMUNQUE)


def e_attivita(percorso: str) -> bool:
    return not any(percorso.startswith(pezzo) for pezzo in NON_E_ATTIVITA)
