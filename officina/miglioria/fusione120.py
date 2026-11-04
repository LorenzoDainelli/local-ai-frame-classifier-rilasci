from __future__ import annotations

import io
import math
import shutil
import tempfile
import zlib
from pathlib import Path
from typing import Callable, Iterable, Iterator

from officina.errori import ErroreOfficina, SpazioInsufficiente

LATO = 480
RAGGIO = 10
ZONA = 6
SFUMA = 6
ACCORDO = (4.0, 12.0)
NETTO = 0.25
MARGINE = 2 * 1024 ** 3
VICINI_TENUTI = 4


class FusioneStorta(ErroreOfficina):
    codice = "fusione_storta"


def fattore(alto: int, largo: int, lato: int = LATO) -> int:
    return max(1, math.ceil(max(int(alto), int(largo)) / int(lato)))


def piccolo(quadro, volte: int):
    import numpy as np

    dato = np.asarray(quadro, dtype=np.float32)
    alto, largo = dato.shape[:2]
    sotto, destra = (-alto) % volte, (-largo) % volte
    if sotto or destra:
        dato = np.pad(dato, ((0, sotto), (0, destra), (0, 0)), mode="edge")
    a, b = dato.shape[0] // volte, dato.shape[1] // volte
    return dato.reshape(a, volte, b, volte, -1).mean(axis=(1, 3))


def scatola(mappa, raggio: int):
    import numpy as np

    if raggio <= 0:
        return np.asarray(mappa, dtype=np.float64)
    lato = 2 * raggio + 1
    dato = np.pad(np.asarray(mappa, dtype=np.float64), raggio, mode="edge")
    somme = np.zeros((dato.shape[0] + 1, dato.shape[1] + 1))
    somme[1:, 1:] = dato.cumsum(axis=0).cumsum(axis=1)
    alto, largo = mappa.shape
    totale = (somme[lato:lato + alto, lato:lato + largo] - somme[:alto, lato:lato + largo]
              - somme[lato:lato + alto, :largo] + somme[:alto, :largo])
    return totale / (lato * lato)


def a_blocchi(mappa, zona: int):
    import numpy as np

    alto, largo = mappa.shape[:2]
    sotto, destra = (-alto) % zona, (-largo) % zona
    if sotto or destra:
        giro = ((0, sotto), (0, destra)) + ((0, 0),) * (mappa.ndim - 2)
        mappa = np.pad(mappa, giro, mode="edge")
    a, b = mappa.shape[0] // zona, mappa.shape[1] // zona
    forma = (a, zona, b, zona) + mappa.shape[2:]
    return mappa.reshape(forma).mean(axis=(1, 3))


def costo(candidato, vero, raggio: int = RAGGIO, zona: int = ZONA):
    import numpy as np
    from numpy.lib.stride_tricks import sliding_window_view

    alto, largo = candidato.shape[:2]
    largo_vero = np.pad(grigio(vero), raggio, mode="edge")
    candidato = grigio(candidato)[:, :, None]
    meglio = None
    for su in range(2 * raggio + 1):
        finestre = sliding_window_view(largo_vero[su:su + alto], largo, axis=1)
        errore = (candidato - finestre.transpose(0, 2, 1)) ** 2
        qui = a_blocchi(errore, zona).min(axis=2)
        meglio = qui if meglio is None else np.minimum(meglio, qui)
    return meglio


def grigio(quadro):
    import numpy as np

    dato = np.asarray(quadro, dtype=np.float32)
    return dato[..., 0] * 0.299 + dato[..., 1] * 0.587 + dato[..., 2] * 0.114


def mappe(g, l, prima, dopo, raggio: int = RAGGIO, zona: int = ZONA):
    import numpy as np

    distanza = scatola(np.abs(g - l).mean(axis=2), zona)
    basso, alto = ACCORDO
    lontani = np.clip((distanza - basso) / (alto - basso), 0.0, 1.0)
    costo_g = np.minimum(costo(g, prima, raggio, zona), costo(g, dopo, raggio, zona))
    costo_l = np.minimum(costo(l, prima, raggio, zona), costo(l, dopo, raggio, zona))
    pari = (costo_l - costo_g) / (costo_l + costo_g + 1e-6)
    a_gimm = np.clip(0.5 + pari / (2 * NETTO), 0.0, 1.0)
    a_gimm = ingrandisci(a_gimm, *lontani.shape, zona)
    return scatola(lontani, SFUMA), scatola(a_gimm, SFUMA)


def ingrandisci(mappa, alto: int, largo: int, volte: int):
    import numpy as np

    def assi(quanti: int, fino: int):
        posti = np.clip((np.arange(quanti) + 0.5) / volte - 0.5, 0, fino - 1)
        sotto = np.floor(posti).astype(np.int64)
        sopra = np.minimum(sotto + 1, fino - 1)
        return sotto, sopra, (posti - sotto).astype(np.float32)

    mappa = np.asarray(mappa, dtype=np.float32)
    r0, r1, pr = assi(int(alto), mappa.shape[0])
    c0, c1, pc = assi(int(largo), mappa.shape[1])
    righe = mappa[r0] * (1 - pr)[:, None] + mappa[r1] * pr[:, None]
    return righe[:, c0] * (1 - pc)[None, :] + righe[:, c1] * pc[None, :]


def fondi(g, l, prima, dopo, lato: int = LATO):
    import numpy as np

    g, l = np.asarray(g), np.asarray(l)
    if g.shape != l.shape or g.shape != np.asarray(prima).shape:
        raise FusioneStorta("I fotogrammi di GIMM-VFI e LDF-VFI non hanno la stessa misura.")
    alto, largo = g.shape[:2]
    volte = fattore(alto, largo, lato)
    lontani, a_gimm = mappe(piccolo(g, volte), piccolo(l, volte),
                            piccolo(prima, volte), piccolo(dopo, volte))
    peso = (lontani * a_gimm + (1 - lontani) * 0.5).astype(np.float32)
    peso = ingrandisci(peso, alto, largo, volte)[..., None]
    lf = l.astype(np.float32)
    uscita = lf + peso * (g.astype(np.float32) - lf)
    return np.clip(np.rint(uscita), 0, 255).astype(np.uint8)


class Deposito:

    def __init__(self, cartella: str | Path | None = None) -> None:
        self.casa = Path(tempfile.mkdtemp(prefix="fusione120-",
                                          dir=None if cartella is None else str(cartella)))
        self._vicini: dict[int, object] = {}

    def _posto(self, numero: int) -> Path:
        return self.casa / f"{int(numero):08d}.npz"

    def metti(self, numero: int, quadro) -> None:
        import numpy as np

        dato = np.ascontiguousarray(quadro, dtype=np.uint8)
        libero = shutil.disk_usage(self.casa).free
        if libero < MARGINE + 4 * dato.nbytes:
            raise SpazioInsufficiente(
                "Il disco si sta riempiendo: la fusione tiene da parte i fotogrammi di "
                "GIMM-VFI e servono almeno "
                f"{math.ceil((MARGINE + 4 * dato.nbytes) / 1024 ** 3)} GB liberi. "
                "Libera spazio e rimetti il video in coda.")
        uscita = io.BytesIO()
        np.save(uscita, dato, allow_pickle=False)
        self._posto(numero).write_bytes(zlib.compress(uscita.getvalue(), 1))

    def prendi(self, numero: int):
        import numpy as np

        if numero in self._vicini:
            return self._vicini[numero]
        dato = np.load(io.BytesIO(zlib.decompress(self._posto(numero).read_bytes())),
                       allow_pickle=False)
        self._vicini[numero] = dato
        while len(self._vicini) > VICINI_TENUTI:
            self._vicini.pop(min(self._vicini))
        return dato

    def butta(self) -> None:
        self._vicini.clear()
        shutil.rmtree(self.casa, ignore_errors=True)


class Fusione:

    def __init__(self, gimm, ldf, cartella: str | Path | None = None) -> None:
        self.gimm = gimm
        self.ldf = ldf
        self.cartella = cartella

    def video(self, apri: Callable[[], Iterable], volte: int, al_quadro=None) -> Iterator:
        volte = int(volte)
        if volte < 2:
            raise ValueError(volte)
        deposito = Deposito(self.cartella)
        try:
            quanti = 0
            for numero, quadro in enumerate(self.gimm.video(apri(), volte)):
                deposito.metti(numero, quadro)
                quanti = numero + 1
            self.gimm.spegni()
            fatti = 0
            fatti_tutti = 0
            for numero, quadro in enumerate(self.ldf.video(apri(), volte)):
                if numero >= quanti:
                    raise FusioneStorta("LDF-VFI ha dato più fotogrammi di GIMM-VFI.")
                posto = numero % volte
                base = numero - posto
                g = deposito.prendi(numero)
                if posto == 0 or base + volte >= quanti:
                    yield g
                else:
                    prima = deposito.prendi(base)
                    yield fondi(g, quadro, prima, deposito.prendi(base + volte))
                if posto == volte - 1 and base + volte < quanti:
                    fatti += 1
                    if al_quadro is not None:
                        al_quadro(fatti)
                fatti_tutti = numero + 1
            if quanti and fatti_tutti != quanti:
                raise FusioneStorta("LDF-VFI ha dato meno fotogrammi di GIMM-VFI.")
        finally:
            deposito.butta()

    def spegni(self) -> None:
        self.gimm.spegni()
        self.ldf.spegni()


__all__ = ["Deposito", "Fusione", "FusioneStorta", "a_blocchi", "costo", "fattore", "fondi",
           "grigio", "ingrandisci", "mappe", "piccolo", "scatola"]
