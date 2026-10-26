from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
from pathlib import PurePath


TROVATA = "trovata"
CHIUSO = "chiuso"
SI_APRE = "si_apre"
NON_C_E = "non_c_e"
SENZA_ARCHIVIO = "senza_archivio"
NON_ESCE = "Una foto presa dall'Archivio sicuro non esce da questo programma."


@dataclass(frozen=True)
class Misure:
    st_size: int
    st_mtime: float = 0.0
    st_mtime_ns: int = 0


@dataclass(frozen=True, eq=False)
class DallArchivio:
    numero: str
    nome: str
    dimensione: int
    blake2b: str
    intero: bool
    diversa: bool
    _prendi: object = field(repr=False)

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
        return self._prendi(self)

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


def per_av(percorso):
    if isinstance(percorso, DallArchivio):
        return percorso.apri()
    return contextlib.nullcontext(str(percorso))


__all__ = ["CHIUSO", "DallArchivio", "Misure", "NON_C_E", "Ricerca", "SENZA_ARCHIVIO",
           "SI_APRE", "TROVATA", "per_av"]
