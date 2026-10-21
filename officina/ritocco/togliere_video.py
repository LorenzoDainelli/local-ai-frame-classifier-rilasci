from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator

from PIL import Image, ImageFilter

from officina.descrittori import vettori
from officina.ritocco import pellicola, togliere

FINESTRA = 32
SOVRAPPOSTI = 4
TREMOLA = 2.0
TREMOLIO_MINIMO = 3.0
ANELLO = 8
FORMATO = "bgr0"
CODEC = "ffv1"


def _mai() -> bool:
    return False


@dataclass
class Riquadro:

    x: int
    y: int
    larghezza: int
    altezza: int


def _pronto(strato: pellicola.Strato, larga: int, alta: int) -> pellicola._Pronto:
    return pellicola._Pronto(strato, larga, alta)


def _buco_intero(pronto: pellicola._Pronto, numero: int, larga: int, alta: int):
    numpy = vettori.numpy_o_spiega()
    pezzo = pronto.al(numero)
    buco = numpy.zeros((alta, larga), dtype=bool)
    if pezzo is None:
        return buco
    altezza, larghezza = pezzo.maschera.shape
    x1, y1 = min(larga, pezzo.x + larghezza), min(alta, pezzo.y + altezza)
    buco[pezzo.y:y1, pezzo.x:x1] = pezzo.maschera[:y1 - pezzo.y, :x1 - pezzo.x]
    return buco


def dove_lavorare(strato: pellicola.Strato, larga: int, alta: int,
                  margine: float) -> Riquadro:
    numpy = vettori.numpy_o_spiega()
    pronto = _pronto(strato, larga, alta)
    insieme = numpy.zeros((alta, larga), dtype=bool)
    for numero in range(strato.quanti):
        pezzo = pronto.al(numero)
        if pezzo is None:
            continue
        altezza, larghezza = pezzo.maschera.shape
        insieme[pezzo.y:pezzo.y + altezza, pezzo.x:pezzo.x + larghezza] = True
    x0, y0, x1, y1 = togliere.riquadro(insieme, margine)
    return Riquadro(x0, y0, x1 - x0, y1 - y0)


def _fai_con_le_foto(motore, quadri: list, buchi: list) -> list:
    return [motore.togli(quadro, buco) for quadro, buco in zip(quadri, buchi, strict=True)]


def _a_finestre(motore) -> Callable[[list, list], list]:
    if hasattr(motore, "video"):
        return motore.video
    return lambda quadri, buchi: _fai_con_le_foto(motore, quadri, buchi)


class _Scrittore:

    def __init__(self, verso: Path, larga: int, alta: int):
        from officina.immagini import fotogrammi

        self._av = fotogrammi.decodificatore()
        self._dentro = self._av.open(str(verso), "w", format="matroska")
        self._flusso = self._dentro.add_stream(CODEC, rate=30)
        self._flusso.width, self._flusso.height = larga, alta
        self._flusso.pix_fmt = FORMATO
        self.scritti = 0

    def scrivi(self, immagine: Image.Image) -> None:
        numpy = vettori.numpy_o_spiega()
        quadro = self._av.VideoFrame.from_ndarray(
            numpy.asarray(immagine.convert("RGB")), format="rgb24").reformat(format=FORMATO)
        for pacchetto in self._flusso.encode(quadro):
            self._dentro.mux(pacchetto)
        self.scritti += 1

    def chiudi(self) -> None:
        for pacchetto in self._flusso.encode():
            self._dentro.mux(pacchetto)
        self._dentro.close()


def leggi(percorso: Path) -> Iterator:
    from officina.immagini import fotogrammi

    av = fotogrammi.decodificatore()
    with av.open(str(percorso)) as dentro:
        for quadro in dentro.decode(video=0):
            yield quadro.to_ndarray(format="rgb24")


class _Tremolio:

    def __init__(self):
        self.dentro = 0.0
        self.intorno = 0.0
        self.quante = 0
        self._prima = None

    def guarda(self, rifatto: Image.Image, originale: Image.Image, buco) -> None:
        numpy = vettori.numpy_o_spiega()
        adesso = (numpy.asarray(rifatto.convert("L"), dtype=numpy.float32),
                  numpy.asarray(originale.convert("L"), dtype=numpy.float32), buco)
        prima, self._prima = self._prima, adesso
        if prima is None:
            return
        dentro = buco & prima[2]
        grigia = Image.fromarray(buco.astype(numpy.uint8) * 255, "L")
        anello = (numpy.asarray(grigia.filter(ImageFilter.MaxFilter(ANELLO * 2 + 1))) > 127) & ~buco
        if not dentro.any() or not anello.any():
            return
        self.dentro += float(numpy.abs(adesso[0] - prima[0])[dentro].mean())
        self.intorno += float(numpy.abs(adesso[1] - prima[1])[anello].mean())
        self.quante += 1

    @property
    def tremola(self) -> bool:
        if not self.quante:
            return False
        dentro, intorno = self.dentro / self.quante, self.intorno / self.quante
        return dentro > max(TREMOLIO_MINIMO, intorno * TREMOLA)


def togli_nel_video(sorgente: Path, strato: pellicola.Strato, motore, verso: Path,
                    margine: float = togliere.MARGINI[0],
                    al_passo: Callable[[int, int], None] | None = None,
                    fermati: Callable[[], bool] = _mai, freno=None) -> dict:
    from officina.miglioria import video
    from officina.miglioria.catena import Frenato

    numpy = vettori.numpy_o_spiega()
    piano = video.guarda(Path(sorgente))
    larga, alta = piano.larghezza, piano.altezza
    pronto = _pronto(strato, larga, alta)
    zona = dove_lavorare(strato, larga, alta, margine)
    lavoro_larga, lavoro_alta, piu_piccolo = togliere._misura_di_lavoro(
        zona.larghezza, zona.altezza, int(getattr(motore, "lato", 1024)))
    fai = _a_finestre(motore)
    finestra = max(SOVRAPPOSTI + 1, int(getattr(motore, "finestra", FINESTRA)))
    frenato = Frenato(freno)
    tremolio = _Tremolio()
    parziale = Path(verso).with_name(Path(verso).name + ".parziale")
    scrittore = _Scrittore(parziale, zona.larghezza, zona.altezza)
    attesa: list[tuple[Image.Image, object]] = []
    coda_di_prima: list[Image.Image] = []
    letti = [0]

    def lavora(pezzi: list, ultimi: bool) -> None:
        nonlocal coda_di_prima
        partito = time.monotonic()
        quadri = [ritaglio.resize((lavoro_larga, lavoro_alta), Image.Resampling.LANCZOS)
                  for ritaglio, _ in pezzi]
        buchi = [togliere._allargata(buco, togliere.ALLARGA).resize(
            (lavoro_larga, lavoro_alta), Image.Resampling.NEAREST) for _, buco in pezzi]
        rifatti = []
        for (ritaglio, buco), rifatto in zip(pezzi, fai(quadri, buchi), strict=True):
            rifatto = rifatto.convert("RGB")
            if rifatto.size != (zona.larghezza, zona.altezza):
                rifatto = rifatto.resize((zona.larghezza, zona.altezza),
                                         Image.Resampling.LANCZOS)
            dentro = numpy.asarray(togliere._allargata(buco, togliere.ALLARGA)) > 127
            rifatti.append((togliere.con_la_grana(ritaglio, rifatto, dentro), ritaglio, dentro))
        frenato.conta(time.monotonic() - partito)
        for indice, (rifatto, ritaglio, dentro) in enumerate(rifatti):
            if indice < len(coda_di_prima):
                peso = (indice + 1) / (len(coda_di_prima) + 1)
                rifatto = Image.blend(coda_di_prima[indice], rifatto, peso)
            if not ultimi and indice >= len(rifatti) - SOVRAPPOSTI:
                continue
            tremolio.guarda(rifatto, ritaglio, dentro)
            scrittore.scrivi(rifatto)
        coda_di_prima = [] if ultimi else [voce[0] for voce in rifatti[-SOVRAPPOSTI:]]

    try:
        for numero, quadro in enumerate(video.dritti(Path(sorgente))):
            if fermati():
                raise pellicola.Fermato()
            if numero >= strato.quanti:
                raise togliere.ErroreOfficina(pellicola.NON_TORNA,
                                              codice="ritocco_video_non_torna")
            immagine = Image.fromarray(numpy.asarray(quadro, dtype=numpy.uint8), "RGB")
            buco = _buco_intero(pronto, numero, larga, alta)
            scatola = (zona.x, zona.y, zona.x + zona.larghezza, zona.y + zona.altezza)
            attesa.append((immagine.crop(scatola),
                           buco[zona.y:zona.y + zona.altezza, zona.x:zona.x + zona.larghezza]))
            letti[0] = numero + 1
            if len(attesa) >= finestra:
                lavora(attesa, False)
                attesa = attesa[-SOVRAPPOSTI:]
            if al_passo is not None:
                al_passo(letti[0], strato.quanti)
        if attesa:
            lavora(attesa, True)
    except BaseException:
        scrittore.chiudi()
        parziale.unlink(missing_ok=True)
        raise
    scrittore.chiudi()
    if letti[0] != strato.quanti or scrittore.scritti != strato.quanti:
        parziale.unlink(missing_ok=True)
        raise togliere.ErroreOfficina(pellicola.NON_TORNA, codice="ritocco_video_non_torna")
    os.replace(parziale, verso)
    return {"x": zona.x, "y": zona.y, "larghezza": zona.larghezza, "altezza": zona.altezza,
            "quanti": strato.quanti, "rimpicciolita": piu_piccolo, "tremola": tremolio.tremola}


def alfa(buco):
    numpy = vettori.numpy_o_spiega()
    allargato = togliere._allargata(buco, togliere.ALLARGA)
    sfumata = allargato.filter(ImageFilter.MaxFilter(togliere.SFUMA * 2 + 1)).filter(
        ImageFilter.GaussianBlur(togliere.SFUMA))
    return numpy.maximum(numpy.asarray(sfumata), numpy.asarray(allargato)).astype(
        numpy.float32) / 255.0
