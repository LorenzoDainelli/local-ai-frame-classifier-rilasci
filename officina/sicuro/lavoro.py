from __future__ import annotations

import errno
import shutil
import time
from pathlib import Path

from officina.sicuro import copia, sveglia
from officina.sicuro.copia import Copiatore
from officina.sicuro.sottofondo import (ATTIVI, ERRORE, FERMATO, FERMO, FINITO,
                                        GUASTO, IN_CORSO, IN_PAUSA, PAUSA_SE_USI,
                                        SPAZIO_FINITO, Sottofondo)


__all__ = ["ATTIVI", "ERRORE", "FERMATO", "FERMO", "FINITO", "GUASTO", "IN_CORSO",
           "IN_PAUSA", "SPAZIO_FINITO", "Lavoro", "da_riprendere", "margine",
           "uso_del_disco"]

MARGINE_MINIMO = 2 * 1024 ** 3
MARGINE_PARTE = 0.01
RICONTROLLA_SPAZIO = 60.0
PIENO = (errno.ENOSPC, getattr(errno, "EDQUOT", errno.ENOSPC))


def da_riprendere(elenco) -> list[dict]:
    radici = []
    for radice in elenco.radici():
        if radice["tolta"]:
            continue
        giro = elenco.giro(radice["id"])
        if giro is None or giro["fine"] is None:
            radici.append(radice)
    return radici


def uso_del_disco(cartella: Path) -> tuple[int, int]:
    uso = shutil.disk_usage(copia.cartella_esistente(cartella))
    return uso.free, uso.total


def margine(totale: int) -> int:
    return max(MARGINE_MINIMO, int(totale * MARGINE_PARTE))


class Lavoro(Sottofondo):

    def __init__(self, cartella: Path, elenco, chiave, *, sveglio=sveglia.sveglio,
                 disco=uso_del_disco, rallenta=None, pausa_se_usi: float = PAUSA_SE_USI,
                 ricontrolla: float = RICONTROLLA_SPAZIO, dormi=time.sleep,
                 **per_copiatore):
        super().__init__(sveglio=sveglio, rallenta=rallenta,
                         pausa_se_usi=pausa_se_usi)
        self.cartella = Path(cartella)
        self.elenco = elenco
        self._disco = disco
        self._ricontrolla = ricontrolla
        self._dormi = dormi
        self.radice: str | None = None
        self.resoconti: dict[str, copia.Giro] = {}
        self.copiatore = Copiatore(self.cartella, elenco, chiave,
                                   aspetta=self._aspetta, spazio=self._spazio,
                                   dormi=self._dormi_fermabile, **per_copiatore)

    def avvia(self, radici: list[dict] | None = None,
              grandezze: dict[str, int] | None = None) -> bool:
        return self._parti(radici, dict(grandezze or {}))

    def _azzera(self) -> None:
        self.resoconti = {}

    def _basta(self, peso: int) -> bool:
        libero, totale = self._disco(self.cartella)
        return libero - peso >= margine(totale)

    def _spazio(self, peso: int) -> None:
        if not self._basta(peso):
            self._aspetta_spazio(peso)
        self._aspetta()

    def _aspetta_spazio(self, peso: int) -> None:
        self._aspetta_che(lambda: self._basta(peso), self._ricontrolla)

    def _radice_viva(self, id: str) -> dict | None:
        for radice in self.elenco.radici():
            if radice["id"] == id:
                return None if radice["tolta"] else radice
        return None

    def _grandezza(self, radice: dict, grandezze: dict[str, int]) -> int:
        if radice["id"] in grandezze:
            return grandezze[radice["id"]]
        giro = self.elenco.giro(radice["id"])
        if giro is not None:
            return int(giro["contati"].get("byte", 0))
        return 0

    def _in_fila(self, radici, fatte: set[str],
                 grandezze: dict[str, int]) -> list[dict]:
        if radici is None:
            radici = [radice for radice in self.elenco.radici()
                      if not radice["tolta"]]
        radici = [radice for radice in radici if radice["id"] not in fatte]
        return sorted(radici, key=lambda radice: (
            self._grandezza(radice, grandezze), radice["aggiunta"], radice["id"]))

    def _una(self, radice: dict) -> copia.Giro:
        while True:
            try:
                return self.copiatore.copia_radice(radice)
            except OSError as guasto:
                if guasto.errno not in PIENO:
                    raise
            self._aspetta_spazio(0)

    def _lavora(self, radici, grandezze: dict[str, int]) -> None:
        self.copiatore.pulisci_provvisori()
        fatte: set[str] = set()
        if radici is not None:
            chieste = {radice["id"] for radice in radici}
            fatte = {radice["id"] for radice in self.elenco.radici()
                     if radice["id"] not in chieste}
        fila = self._in_fila(radici, fatte, grandezze)
        while fila:
            for prossima in fila:
                self._aspetta()
                radice = self._radice_viva(prossima["id"])
                fatte.add(prossima["id"])
                if radice is None:
                    continue
                self.radice = radice["id"]
                self.resoconti[radice["id"]] = self._una(radice)
            fila = self._in_fila(da_riprendere(self.elenco), fatte, grandezze)

    def _alla_fine(self, esito: str) -> None:
        self.elenco.salva()

    def _finito(self) -> None:
        self.radice = None

    def istantanea(self) -> dict:
        avanzamento = self.copiatore.avanzamento
        resoconti = dict(self.resoconti)
        return {
            "stato": self.stato,
            "radice": self.radice,
            "percorso": avanzamento.percorso,
            "file": avanzamento.file,
            "letti": avanzamento.letti,
            "copiati": avanzamento.copiati,
            "doppioni": avanzamento.doppioni,
            "uguali": avanzamento.uguali,
            "fatte": sorted(resoconti),
            "verdi": sorted(id for id, giro in resoconti.items() if giro.verde),
            "rosse": {id: [list(problema) for problema in giro.rossi]
                      for id, giro in resoconti.items() if not giro.verde},
            "errore": self.errore,
            "codice": self.codice,
        }
