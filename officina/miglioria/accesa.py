from __future__ import annotations

import json
import subprocess
from typing import Callable

from officina import registro
from officina.miglioria import motori

MODULO = "officina.miglioria.stanza_accesa"
CHIUSO = {"chiuso": True}
ATTESA_DI_CHIUSURA = 60.0


def resta_accesa(lavoro: dict) -> bool:
    foto = lavoro.get("genere") == "immagine"
    nome = (lavoro.get("motori") or {}).get("foto" if foto else "video")
    if foto and nome == motori.LUCIDFLUX and lavoro.get("mezzo"):
        nome = motori.SEEDVR2
    return motori.resta_acceso(motori.FOTO if foto else motori.VIDEO, str(nome))


def _scrivi(processo: subprocess.Popen, messaggio: dict) -> None:
    processo.stdin.write(json.dumps(messaggio) + "\n")
    processo.stdin.flush()


class StanzaAccesa:

    def __init__(self, modulo: str = MODULO) -> None:
        self.modulo = modulo
        self._processo: subprocess.Popen | None = None
        self.file = 0
        self.caricati = 0

    @property
    def accesa(self) -> bool:
        return self._processo is not None and self._processo.poll() is None

    def lancia(self, lavoro: dict, al_passo: Callable[[int, int], None],
               ricorda: Callable[[subprocess.Popen], None]) -> dict:
        from officina.miglioria import lavoro as lavori

        if not resta_accesa(lavoro):
            self.spegni()
            return lavori.lancia_la_stanza(lavoro, al_passo, ricorda)
        if not self.accesa:
            self._dimentica()
            self._processo = lavori.apri_la_stanza(self.modulo)
        processo = self._processo
        ricorda(processo)
        esito = rotto = accesa = None
        allo_sportello = None
        try:
            _scrivi(processo, {"lavoro": lavoro})
            if lavoro.get("dall_archivio"):
                allo_sportello = lavori._sportello(processo)
            esito, rotto, accesa = lavori.ascolta_la_stanza(processo, allo_sportello,
                                                            al_passo)
        except (OSError, ValueError):
            accesa = None
        finally:
            if allo_sportello is not None:
                allo_sportello.chiudi()
            accesa = self._dopo(processo, accesa)
        if accesa is not None:
            self.file += 1
            self.caricati = int(accesa.get("caricati") or 0)
            return esito
        return lavori.esito_della_stanza(esito, rotto, self._chiudi(processo))

    def _dopo(self, processo: subprocess.Popen, accesa: dict | None) -> dict | None:
        if accesa is None:
            return None
        try:
            _scrivi(processo, CHIUSO)
        except (OSError, ValueError):
            return None
        return accesa

    def _chiudi(self, processo: subprocess.Popen) -> int:
        from officina.miglioria import lavoro as lavori

        lavori._chiudi(processo.stdin)
        try:
            codice = processo.wait(timeout=ATTESA_DI_CHIUSURA)
        except subprocess.TimeoutExpired:
            processo.kill()
            codice = processo.wait()
        if processo is self._processo:
            self._dimentica()
        return codice

    def _dimentica(self) -> None:
        if self._processo is not None and self.file:
            registro.evento("miglioria.stanza_accesa", file=self.file,
                            caricati=self.caricati)
        self._processo = None
        self.file = 0
        self.caricati = 0

    def spegni(self) -> None:
        processo = self._processo
        if processo is None:
            return
        self._chiudi(processo)


__all__ = ["CHIUSO", "MODULO", "StanzaAccesa", "resta_accesa"]
