from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
from pathlib import PurePath

from officina.errori import DaRifare, perche_saltato

TROVATA = "trovata"
CHIUSO = "chiuso"
SI_APRE = "si_apre"
NON_C_E = "non_c_e"
SENZA_ARCHIVIO = "senza_archivio"
NON_ESCE = "Una foto presa dall'Archivio sicuro non esce da questo programma."
PERSA = "persa_nell_archivio"
CHIUSO_ADESSO = "sicuro_chiuso"
DIVERSA = "versione_diversa"


@dataclass(frozen=True)
class Misure:
    st_size: int
    st_mtime: float = 0.0
    st_mtime_ns: int = 0
    st_ctime: float = 0.0


@dataclass(frozen=True, eq=False)
class DallArchivio:
    numero: str
    nome: str
    dimensione: int
    blake2b: str
    intero: bool
    diversa: bool
    _prendi: object = field(repr=False)
    _guasti: list = field(default_factory=list, repr=False)

    @property
    def guasto(self) -> str | None:
        return self.guasto_da(0)

    def guasto_da(self, segno: int) -> str | None:
        nuovi = self._guasti[segno:]
        if PERSA in nuovi:
            return PERSA
        return nuovi[0] if nuovi else None

    def segno(self) -> int:
        return len(self._guasti)

    def segna_guasto(self, codice: str | None) -> None:
        self._guasti.append(codice or "guasto")

    @property
    def name(self) -> str:
        return PurePath(self.nome).name

    @property
    def suffix(self) -> str:
        return PurePath(self.nome).suffix

    @property
    def stem(self) -> str:
        return PurePath(self.nome).stem

    def exists(self) -> bool:
        return True

    def is_file(self) -> bool:
        return True

    def stat(self) -> Misure:
        return Misure(self.dimensione)

    def apri(self):
        try:
            return self._prendi(self)
        except Exception as errore:
            self.segna_guasto(getattr(errore, "codice", None))
            raise

    def __str__(self) -> str:
        return f"«{self.name}» dall'Archivio sicuro"

    def __reduce__(self):
        raise TypeError(NON_ESCE)


@dataclass(frozen=True)
class Ricerca:
    perche: str
    trovata: DallArchivio | None = None

    @property
    def diversa(self) -> bool:
        return self.trovata is not None and self.trovata.diversa


def da_rifare(codice: str) -> DaRifare:
    codice = PERSA if codice == PERSA else CHIUSO_ADESSO
    testo = perche_saltato(codice)
    return DaRifare(testo[:1].upper() + testo[1:] + ".", codice=codice)


@contextlib.contextmanager
def attento(percorso):
    if not isinstance(percorso, DallArchivio):
        yield percorso
        return
    segno = percorso.segno()
    try:
        yield percorso
    except DaRifare:
        raise
    except Exception as errore:
        guasto = percorso.guasto_da(segno)
        if guasto is not None:
            raise da_rifare(guasto) from errore
        raise
    guasto = percorso.guasto_da(segno)
    if guasto is not None:
        raise da_rifare(guasto)


def per_av(percorso):
    if isinstance(percorso, DallArchivio):
        return percorso.apri()
    return contextlib.nullcontext(str(percorso))


__all__ = ["CHIUSO", "CHIUSO_ADESSO", "DIVERSA", "DallArchivio", "Misure", "NON_C_E",
           "PERSA", "Ricerca", "SENZA_ARCHIVIO", "SI_APRE", "TROVATA", "attento",
           "da_rifare", "per_av"]
