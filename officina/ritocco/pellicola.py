from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Iterator

from officina.descrittori import vettori
from officina.errori import ErroreOfficina
from officina.ritocco import elenco, maschere, pixela

VICINI = 1
PONTE = 4

NON_TORNA = ("Il video non ha gli stessi fotogrammi di quando l'IA ha seguito la parte "
             "scelta: non lo pixelo. Il video non è stato toccato.")
SENZA_NIENTE = ("In questo video l'IA non ha trovato in nessun fotogramma la parte scelta: "
                "non c'è niente da pixelare.")


class Fermato(Exception):
    pass


def _mai() -> bool:
    return False


@dataclass
class Strato:

    larghezza: int
    altezza: int
    quanti: int
    maschere: dict[int, bytes]
    cosa: str
    quadretto: int | None = None
    origine: tuple[int, int] | None = None


def fonti(presenti: Iterable[int], quanti: int, vicini: int = VICINI,
          ponte: int = PONTE) -> list[tuple[int, ...]]:
    dentro = sorted({int(numero) for numero in presenti if 0 <= int(numero) < quanti})
    insieme = set(dentro)
    fuori = [tuple(vicino for vicino in range(numero - vicini, numero + vicini + 1)
                   if vicino in insieme) for numero in range(quanti)]
    for prima, dopo in zip(dentro, dentro[1:], strict=False):
        if 1 < dopo - prima <= ponte + 1:
            for numero in range(prima + 1, dopo):
                fuori[numero] = tuple(sorted(set(fuori[numero]) | {prima, dopo}))
    return fuori


def misura_di_lavoro(strato: Strato) -> int:
    piu_grande = 0
    for dati in strato.maschere.values():
        letto = maschere.riquadro(dati)
        if letto is None:
            continue
        larga, alta = letto[4], letto[5]
        piu_grande = max(piu_grande, larga if strato.cosa == elenco.VOLTO else min(larga, alta))
    return piu_grande


class _Pronto:

    def __init__(self, strato: Strato, larghezza: int, altezza: int):
        self.strato = strato
        self.larghezza, self.altezza = larghezza, altezza
        scala_x = larghezza / strato.larghezza
        scala_y = altezza / strato.altezza
        misura = misura_di_lavoro(strato)
        if not misura:
            raise ErroreOfficina(SENZA_NIENTE, codice="ritocco_niente_nel_video")
        self.lato = pixela.quadretto(misura * scala_x, round((strato.quadretto or 0) * scala_x))
        origine = strato.origine
        if origine is None:
            primo = maschere.riquadro(strato.maschere[min(strato.maschere)])
            origine = (primo[2], primo[3])
        self.origine = (round(origine[0] * scala_x), round(origine[1] * scala_y))
        self.fonti = fonti(strato.maschere, strato.quanti)
        self._aperti: dict[int, maschere.Pezzo | None] = {}

    def _apri(self, numero: int) -> maschere.Pezzo | None:
        if numero not in self._aperti:
            self._aperti[numero] = maschere.apri(self.strato.maschere[numero])
        return self._aperti[numero]

    def al(self, numero: int) -> maschere.Pezzo | None:
        for vecchio in [chi for chi in self._aperti if chi < numero - PONTE - VICINI - 1]:
            del self._aperti[vecchio]
        if numero >= len(self.fonti):
            return None
        pezzi = [pezzo for pezzo in (self._apri(chi) for chi in self.fonti[numero])
                 if pezzo is not None]
        insieme = maschere.unione(pezzi)
        if insieme is None:
            return None
        return maschere.per_misura(insieme, self.larghezza, self.altezza)


def pixela_il_video(sorgente: Path, verso: Path, strati: list[Strato],
                    al_passo: Callable[[int, int], None] | None = None,
                    fermati: Callable[[], bool] = _mai, freno=None):
    from officina.miglioria import video
    from officina.miglioria.catena import Frenato

    numpy = vettori.numpy_o_spiega()
    piano = video.guarda(sorgente)
    quanti = {strato.quanti for strato in strati}
    if len(quanti) != 1:
        raise ErroreOfficina(NON_TORNA, codice="ritocco_video_non_torna")
    attesi = quanti.pop()
    pronti = [_Pronto(strato, piano.larghezza, piano.altezza) for strato in strati]
    contati = [0]
    frenato = Frenato(freno)

    def trasforma(quadri: Iterable) -> Iterator:
        ultimo = time.monotonic()
        for numero, quadro in enumerate(quadri):
            if fermati():
                raise Fermato()
            if numero >= attesi:
                raise ErroreOfficina(NON_TORNA, codice="ritocco_video_non_torna")
            toccato = None
            for pronto in pronti:
                pezzo = pronto.al(numero)
                if pezzo is None:
                    continue
                if toccato is None:
                    toccato = numpy.array(quadro, dtype=numpy.uint8, copy=True)
                pixela.pixela_nei_pixel(toccato, pezzo.maschera, (pezzo.x, pezzo.y),
                                        pronto.lato, pronto.origine)
            yield quadro if toccato is None else toccato
            contati[0] = numero + 1
            frenato.conta(time.monotonic() - ultimo)
            ultimo = time.monotonic()

    def passo(fatti: int, _totale: int) -> None:
        if al_passo is not None:
            al_passo(fatti, attesi)

    fatto = video.lavora(Path(sorgente), Path(verso), piano.larghezza, piano.altezza,
                         trasforma, passo)
    if contati[0] != attesi:
        raise ErroreOfficina(NON_TORNA, codice="ritocco_video_non_torna")
    return fatto
