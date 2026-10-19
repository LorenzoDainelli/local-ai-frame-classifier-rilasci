from __future__ import annotations

import io
from pathlib import Path
from typing import Callable

from PIL import Image

from officina.errori import ErroreOfficina
from officina.immagini import fotogrammi

LATO = 1008
MISURE = ((2400, 1008, 90), (7200, 1008, 82), (18000, 720, 78), (None, 512, 72))

NON_SI_APRE = "Questo video non si riesce ad aprire: non lo seguo. Il video non è stato toccato."
SENZA_FOTOGRAMMI = "In questo video non ho trovato fotogrammi da seguire."


class Fermato(Exception):
    pass


def _mai() -> bool:
    return False


def misura_per(quanti: int) -> tuple[int, int]:
    for fino_a, lato, qualita in MISURE:
        if fino_a is None or quanti <= fino_a:
            return lato, qualita
    return MISURE[-1][1], MISURE[-1][2]


def misura_di_lavoro(larga: int, alta: int, lato: int = LATO) -> tuple[int, int]:
    if max(larga, alta) <= lato:
        return larga, alta
    scala = lato / max(larga, alta)
    return max(1, round(larga * scala)), max(1, round(alta * scala))


class Filmato:

    def __init__(self, percorso: Path, lato: int | None = None,
                 fermati: Callable[[], bool] = _mai,
                 al_passo: Callable[[int, int], None] | None = None):
        self.percorso = Path(percorso)
        self._quadri: list[bytes] = []
        self.istanti: list[int] = []
        self.larghezza = 0
        self.altezza = 0
        self.lato = lato
        self._leggi(fermati, al_passo)

    @property
    def quanti(self) -> int:
        return len(self._quadri)

    def quadro(self, indice: int) -> Image.Image:
        with Image.open(io.BytesIO(self._quadri[indice])) as immagine:
            return immagine.convert("RGB")

    def _leggi(self, fermati, al_passo) -> None:
        if not fotogrammi.c_e_il_decodificatore():
            raise ErroreOfficina(NON_SI_APRE, codice="ritocco_video_non_si_apre")
        av = fotogrammi.decodificatore()
        try:
            with av.open(str(self.percorso)) as contenitore:
                traccia = fotogrammi._la_traccia(contenitore)
                if traccia is None:
                    raise ErroreOfficina(SENZA_FOTOGRAMMI, codice="ritocco_video_vuoto")
                attesi, _ = fotogrammi._quanti_e_ritmo(contenitore, traccia)
                lato, qualita = misura_per(attesi)
                if self.lato is None:
                    self.lato = lato
                base = float(traccia.time_base or 0) * 1000
                for quadro in contenitore.decode(traccia):
                    if fermati():
                        raise Fermato()
                    immagine = fotogrammi._quadro_a_immagine(quadro, self.lato).convert("RGB")
                    if not self._quadri:
                        self.larghezza, self.altezza = immagine.size
                    elif immagine.size != (self.larghezza, self.altezza):
                        immagine = immagine.resize((self.larghezza, self.altezza),
                                                   Image.Resampling.BILINEAR)
                    scritto = io.BytesIO()
                    immagine.save(scritto, "JPEG", quality=qualita)
                    self._quadri.append(scritto.getvalue())
                    self.istanti.append(int(round((quadro.pts or 0) * base)))
                    if al_passo is not None:
                        al_passo(len(self._quadri), attesi)
        except (Fermato, ErroreOfficina):
            raise
        except Exception as guasto:
            raise ErroreOfficina(NON_SI_APRE, codice="ritocco_video_non_si_apre") from guasto
        if not self._quadri:
            raise ErroreOfficina(SENZA_FOTOGRAMMI, codice="ritocco_video_vuoto")
        if self.istanti and self.istanti[0]:
            primo = self.istanti[0]
            self.istanti = [istante - primo for istante in self.istanti]
