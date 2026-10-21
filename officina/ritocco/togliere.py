from __future__ import annotations

import importlib
import io
import math
from dataclasses import dataclass
from typing import Callable

from PIL import Image, ImageFilter

from officina.descrittori import vettori
from officina.errori import ErroreOfficina

FINTO = "finto"

MOTORI: dict[str, str] = {
    FINTO: "officina.ritocco.togliere:Finto",
}

MARGINI = (0.5, 1.0, 1.6)
BORDO_MINIMO = 24
ALLARGA = 6
SFUMA = 3
PASSO = 16


class MotoreSconosciuto(ErroreOfficina):
    codice = "togli_motore_sconosciuto"


class NienteDaTogliere(ErroreOfficina):
    codice = "togli_niente"


@dataclass
class Toppa:

    x: int
    y: int
    immagine: Image.Image
    rimpicciolita: bool

    def in_png(self) -> bytes:
        uscita = io.BytesIO()
        self.immagine.save(uscita, format="PNG", optimize=False)
        return uscita.getvalue()

    @classmethod
    def da_png(cls, dati: bytes, x: int, y: int) -> "Toppa":
        with Image.open(io.BytesIO(dati)) as aperta:
            return cls(int(x), int(y), aperta.convert("RGBA"), False)

    def metti(self, immagine: Image.Image) -> Image.Image:
        sotto = immagine.convert("RGB").copy()
        sotto.paste(self.immagine.convert("RGB"), (self.x, self.y),
                    self.immagine.getchannel("A"))
        return sotto


class Finto:

    nome = FINTO
    versione = "1"
    lato = 512

    def __init__(self, **_opzioni) -> None:
        self.spento = False

    def togli(self, immagine: Image.Image, maschera: Image.Image) -> Image.Image:
        numpy = vettori.numpy_o_spiega()
        pixel = numpy.asarray(immagine.convert("RGB"), dtype=numpy.float32)
        buco = numpy.asarray(maschera.convert("L")) > 127
        if not buco.any():
            return immagine.convert("RGB")
        fuori = pixel[~buco].mean(axis=0) if (~buco).any() else numpy.full(3, 128.0)
        riempita = pixel.copy()
        riempita[buco] = fuori
        sfocata = Image.fromarray(riempita.clip(0, 255).astype(numpy.uint8), "RGB")
        for _ in range(3):
            sfocata = sfocata.filter(ImageFilter.GaussianBlur(4))
            dentro = numpy.asarray(sfocata, dtype=numpy.float32)
            riempita[buco] = dentro[buco]
            sfocata = Image.fromarray(riempita.clip(0, 255).astype(numpy.uint8), "RGB")
        return sfocata

    def spegni(self) -> None:
        self.spento = True


def apri(nome: str, **opzioni):
    indirizzo = MOTORI.get(nome)
    if indirizzo is None:
        raise MotoreSconosciuto(f"Non conosco il modello per togliere «{nome}».")
    modulo, classe = indirizzo.split(":", 1)
    return getattr(importlib.import_module(modulo), classe)(**opzioni)


def riquadro(buco, margine: float) -> tuple[int, int, int, int]:
    numpy = vettori.numpy_o_spiega()
    righe = numpy.flatnonzero(buco.any(axis=1))
    colonne = numpy.flatnonzero(buco.any(axis=0))
    if not len(righe):
        raise NienteDaTogliere("Non hai scelto niente da togliere.")
    alta, larga = buco.shape
    x0, x1 = int(colonne[0]), int(colonne[-1]) + 1
    y0, y1 = int(righe[0]), int(righe[-1]) + 1
    aggiunta = max(BORDO_MINIMO, math.ceil(max(x1 - x0, y1 - y0) * margine))
    return (max(0, x0 - aggiunta), max(0, y0 - aggiunta),
            min(larga, x1 + aggiunta), min(alta, y1 + aggiunta))


def _misura_di_lavoro(larga: int, alta: int, lato: int) -> tuple[int, int, bool]:
    scala = min(1.0, lato / max(larga, alta))
    nuova_larga = max(PASSO, round(larga * scala / PASSO) * PASSO)
    nuova_alta = max(PASSO, round(alta * scala / PASSO) * PASSO)
    return nuova_larga, nuova_alta, scala < 1.0


def _allargata(buco, quanto: int):
    grigia = Image.fromarray(buco.astype("uint8") * 255, "L")
    if quanto > 0:
        grigia = grigia.filter(ImageFilter.MaxFilter(quanto * 2 + 1))
    return grigia


def _grana(numpy, pixel):
    grigia = Image.fromarray(pixel.clip(0, 255).astype(numpy.uint8), "RGB")
    liscia = numpy.asarray(grigia.filter(ImageFilter.GaussianBlur(1.2)), dtype=numpy.float32)
    return pixel - liscia


def con_la_grana(ritaglio: Image.Image, rifatto: Image.Image, buco, seme: int = 0) -> Image.Image:
    numpy = vettori.numpy_o_spiega()
    prima = numpy.asarray(ritaglio.convert("RGB"), dtype=numpy.float32)
    dopo = numpy.asarray(rifatto.convert("RGB"), dtype=numpy.float32)
    if not buco.any() or buco.all():
        return rifatto.convert("RGB")
    voluta = float(_grana(numpy, prima)[~buco].std())
    avuta = float(_grana(numpy, dopo)[buco].std())
    manca = math.sqrt(max(0.0, voluta ** 2 - avuta ** 2))
    if manca < 0.5:
        return rifatto.convert("RGB")
    rumore = numpy.random.default_rng(seme).normal(0.0, manca, size=dopo.shape[:2])
    dopo[buco] += rumore[buco][:, None]
    return Image.fromarray(dopo.clip(0, 255).astype(numpy.uint8), "RGB")


Ingrandisci = Callable[[Image.Image, int, int], Image.Image]


def togli(immagine: Image.Image, buco, motore, margine: float = MARGINI[0],
          ingrandisci: Ingrandisci | None = None) -> Toppa:
    numpy = vettori.numpy_o_spiega()
    buco = numpy.asarray(buco, dtype=bool)
    immagine = immagine.convert("RGB")
    if buco.shape != (immagine.height, immagine.width):
        raise NienteDaTogliere("La parte scelta non corrisponde allo scatto: riprova.")
    x0, y0, x1, y1 = riquadro(buco, margine)
    ritaglio = immagine.crop((x0, y0, x1, y1))
    pezzo = buco[y0:y1, x0:x1]
    allargato = _allargata(pezzo, ALLARGA)
    larga, alta = ritaglio.size
    lavoro_larga, lavoro_alta, piu_piccolo = _misura_di_lavoro(larga, alta,
                                                               int(getattr(motore, "lato", 1024)))
    da_dare = ritaglio.resize((lavoro_larga, lavoro_alta), Image.Resampling.LANCZOS)
    maschera = allargato.resize((lavoro_larga, lavoro_alta), Image.Resampling.NEAREST)
    rifatto = motore.togli(da_dare, maschera).convert("RGB")
    if rifatto.size != (lavoro_larga, lavoro_alta):
        rifatto = rifatto.resize((lavoro_larga, lavoro_alta), Image.Resampling.LANCZOS)
    if (lavoro_larga, lavoro_alta) != (larga, alta):
        if piu_piccolo and ingrandisci is not None:
            rifatto = ingrandisci(rifatto, larga, alta)
        if rifatto.size != (larga, alta):
            rifatto = rifatto.resize((larga, alta), Image.Resampling.LANCZOS)
    dentro = numpy.asarray(allargato) > 127
    rifatto = con_la_grana(ritaglio, rifatto, dentro)
    sfumata = allargato.filter(ImageFilter.MaxFilter(SFUMA * 2 + 1)).filter(
        ImageFilter.GaussianBlur(SFUMA))
    alfa = numpy.maximum(numpy.asarray(sfumata), numpy.asarray(allargato))
    toppa = rifatto.convert("RGBA")
    toppa.putalpha(Image.fromarray(alfa.astype(numpy.uint8), "L"))
    return Toppa(x0, y0, toppa, piu_piccolo)
