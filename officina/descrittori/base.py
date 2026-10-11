from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from PIL import Image

VISIVO = "visivo"
VISIONE_E_LINGUA = "visione_e_lingua"
SENZA_MODELLO = "senza_modello"

LINGUA = "lingua"

PIENA = "piena"
MEZZA = "mezza"
SENZA_PRECISIONE = "nessuna"

SIGLE = {PIENA: "f32", MEZZA: "f16", SENZA_PRECISIONE: ""}

PESI_CONVERTITI = "pesi-officina.safetensors"


@dataclass(frozen=True)
class Scheda:

    nome: str
    titolo: str
    versione: str
    famiglia: str
    dimensione: int
    licenza: str
    identificatore: str
    byte_attesi: int
    lato: int
    nota: str
    precisione: str = SENZA_PRECISIONE
    esegue_codice_di_terzi: bool = False

    prova_che_c_e: str = "config.json"
    cosa_serve: tuple[str, ...] = ()

    @property
    def va_scaricato(self) -> bool:
        return bool(self.identificatore)

    @property
    def sigla_precisione(self) -> str:
        return SIGLE[self.precisione]

    @property
    def chiave(self) -> str:
        return f"{self.nome}@{self.versione}"

    def versione_coerente(self) -> bool:
        sigla = self.sigla_precisione
        if not sigla:
            return "-f" not in self.versione
        return self.versione.endswith(f"-{sigla}")


class Descrittore:

    scheda: Scheda

    def __init__(self) -> None:
        self.aperto = False


    def apri(self) -> "Descrittore":
        if not self.aperto:
            self._apri()
            self.aperto = True
        return self

    def chiudi(self) -> None:
        if self.aperto:
            self._chiudi()
            self.aperto = False

    def __enter__(self) -> "Descrittore":
        return self.apri()

    def __exit__(self, *_) -> None:
        self.chiudi()


    def descrivi(self, immagini: Sequence[Image.Image]) -> list[list[float]]:
        if not immagini:
            return []
        self.apri()
        return self._descrivi(list(immagini))

    def descrivi_una(self, immagine: Image.Image) -> list[float]:
        return self.descrivi([immagine])[0]


    def _apri(self) -> None:
        pass

    def _chiudi(self) -> None:
        pass

    def _descrivi(self, immagini: list[Image.Image]) -> list[list[float]]:
        raise NotImplementedError


    def dove_gira(self) -> str:
        return "processore"
