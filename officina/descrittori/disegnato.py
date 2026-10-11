from __future__ import annotations

from PIL import Image, ImageFilter

from officina.descrittori import vettori
from officina.descrittori.base import SENZA_MODELLO, Descrittore, Scheda


LATO = 192

BIDONI = 8
COLORI = 4
TINTE = 12
SATURAZIONI = 3
STRISCE = 4
CELLE_COLORE = 3
CELLE_BORDI = 4
CELLE_GRANDI = 2
CELLE_TRAMA = 4
CELLE_MOTIVI = 2
MOTIVI = 10
LUCE_BIDONI = 16

PESI = {
    "cubo_colori":   1.0,
    "tinte":         0.8,
    "strisce":       0.8,
    "griglia":       1.0,
    "bordi_fini":    1.2,
    "bordi_grossi":  0.8,
    "trama":         1.0,
    "motivi":        0.8,
    "simmetria":     0.4,
    "luce":          0.6,
}

QUANTI = {
    "cubo_colori":  COLORI ** 3,
    "tinte":        TINTE * SATURAZIONI,
    "strisce":      STRISCE * 3 * BIDONI,
    "griglia":      CELLE_COLORE * CELLE_COLORE * 6,
    "bordi_fini":   CELLE_BORDI * CELLE_BORDI * BIDONI,
    "bordi_grossi": CELLE_GRANDI * CELLE_GRANDI * BIDONI,
    "trama":        2 * 2 * CELLE_TRAMA * CELLE_TRAMA,
    "motivi":       CELLE_MOTIVI * CELLE_MOTIVI * MOTIVI,
    "simmetria":    6,
    "luce":         LUCE_BIDONI + 4,
}

ORDINE = ("cubo_colori", "tinte", "strisce", "griglia", "bordi_fini",
          "bordi_grossi", "trama", "motivi", "simmetria", "luce")

DIMENSIONE = sum(QUANTI[nome] for nome in ORDINE)


class Disegnato(Descrittore):

    scheda = Scheda(
        nome="disegnato",
        titolo="Disegnato a mano (colori e bordi)",
        versione="2",
        famiglia=SENZA_MODELLO,
        dimensione=DIMENSIONE,
        licenza="nessuna: è codice di questo progetto",
        identificatore="",
        byte_attesi=0,
        lato=224,
        nota="Non è un modello: è un conto sui pixel. Serve per provare tutto "
             "il resto senza scaricare niente, e come metro di paragone.",
    )

    def _descrivi(self, immagini: list[Image.Image]) -> list[list[float]]:
        return [_impronta(immagine) for immagine in immagini]

    def dove_gira(self) -> str:
        return "processore"


def pezzi(immagine: Image.Image) -> dict:
    numpy = vettori.numpy_o_spiega()
    tavola = _tavola(numpy, immagine)
    return {
        "cubo_colori":  _cubo_dei_colori(numpy, tavola),
        "tinte":        _cubo_delle_tinte(numpy, tavola),
        "strisce":      _colori_per_striscia(numpy, tavola),
        "griglia":      _griglia_dei_colori(numpy, tavola),
        "bordi_fini":   _direzioni_dei_bordi(numpy, tavola),
        "bordi_grossi": _bordi_in_grande(numpy, tavola),
        "trama":        _trama(numpy, tavola),
        "motivi":       _motivi_minuti(numpy, tavola),
        "simmetria":    _simmetria(numpy, tavola),
        "luce":         _la_luce(numpy, tavola),
    }


def _impronta(immagine: Image.Image) -> list[float]:
    numpy = vettori.numpy_o_spiega()
    calcolati = pezzi(immagine)
    intera = numpy.concatenate([
        _normalizza(numpy, calcolati[nome]) * PESI[nome] for nome in ORDINE
    ])
    return vettori.normalizza(intera.tolist())


def _normalizza(numpy, valori):
    valori = valori.astype(numpy.float32, copy=False)
    lunghezza = float(numpy.linalg.norm(valori))
    return valori / lunghezza if lunghezza > 0 else valori


class _Tavola:

    __slots__ = ("pixel", "luce", "grigia", "hsv")

    def __init__(self, pixel, luce, grigia, hsv):
        self.pixel = pixel
        self.luce = luce
        self.grigia = grigia
        self.hsv = hsv


def _tavola(numpy, immagine: Image.Image) -> _Tavola:
    if immagine.mode != "RGB":
        immagine = immagine.convert("RGB")
    piccola = immagine.resize((LATO, LATO), Image.Resampling.BILINEAR)

    pixel = numpy.frombuffer(piccola.tobytes(), dtype=numpy.uint8)
    pixel = pixel.reshape(LATO, LATO, 3).astype(numpy.float32) / 255.0

    luce = pixel @ numpy.array([0.299, 0.587, 0.114], dtype=numpy.float32)

    return _Tavola(pixel, luce, piccola.convert("L"), _in_hsv(numpy, pixel))


def _in_hsv(numpy, pixel):
    rosso, verde, blu = pixel[..., 0], pixel[..., 1], pixel[..., 2]
    massimo = pixel.max(axis=2)
    minimo = pixel.min(axis=2)
    delta = massimo - minimo

    sicuro = numpy.where(delta > 0, delta, 1.0)

    tinta = numpy.zeros_like(massimo)
    tinta = numpy.where(massimo == rosso, ((verde - blu) / sicuro) % 6.0, tinta)
    tinta = numpy.where(massimo == verde, ((blu - rosso) / sicuro) + 2.0, tinta)
    tinta = numpy.where(massimo == blu, ((rosso - verde) / sicuro) + 4.0, tinta)
    tinta = numpy.where(delta > 0, (tinta / 6.0) % 1.0, 0.0)

    saturazione = numpy.where(massimo > 0, delta / numpy.where(massimo > 0, massimo, 1.0), 0.0)
    return tinta.astype(numpy.float32), saturazione.astype(numpy.float32), massimo


def _cubo_dei_colori(numpy, tavola: _Tavola):
    fuori = numpy.zeros(COLORI ** 3, dtype=numpy.float32)
    scala = tavola.pixel * COLORI - 0.5

    basso = numpy.floor(scala).astype(numpy.int32)
    frazione = (scala - basso).astype(numpy.float32)

    for dr in (0, 1):
        for dv in (0, 1):
            for db in (0, 1):
                indici = []
                peso = numpy.ones(tavola.pixel.shape[:2], dtype=numpy.float32)
                for canale, passo in enumerate((dr, dv, db)):
                    dove = numpy.clip(basso[..., canale] + passo, 0, COLORI - 1)
                    quota = frazione[..., canale] if passo else 1.0 - frazione[..., canale]
                    indici.append(dove)
                    peso = peso * quota
                piatto = (indici[0] * COLORI * COLORI + indici[1] * COLORI + indici[2])
                fuori += numpy.bincount(piatto.ravel(), weights=peso.ravel(),
                                        minlength=COLORI ** 3).astype(numpy.float32)
    return fuori / max(float(fuori.sum()), 1.0)


def _cubo_delle_tinte(numpy, tavola: _Tavola):
    tinta, saturazione, valore = tavola.hsv
    peso = (saturazione * valore).astype(numpy.float32)

    scala = tinta * TINTE
    basso = numpy.floor(scala).astype(numpy.int32)
    quota = (scala - basso).astype(numpy.float32)

    livello = numpy.clip((saturazione * SATURAZIONI).astype(numpy.int32),
                         0, SATURAZIONI - 1)

    fuori = numpy.zeros(TINTE * SATURAZIONI, dtype=numpy.float32)
    for passo in (0, 1):
        spicchio = (basso + passo) % TINTE
        parte = quota if passo else 1.0 - quota
        piatto = spicchio * SATURAZIONI + livello
        fuori += numpy.bincount(piatto.ravel(), weights=(peso * parte).ravel(),
                                minlength=TINTE * SATURAZIONI).astype(numpy.float32)
    return fuori / max(float(fuori.sum()), 1.0)


def _colori_per_striscia(numpy, tavola: _Tavola):
    alta = LATO // STRISCE
    strisce = tavola.pixel.reshape(STRISCE, alta, LATO, 3)
    fuori = []
    for striscia in strisce:
        for canale in range(3):
            conti = numpy.histogram(striscia[..., canale], bins=BIDONI,
                                    range=(0.0, 1.0))[0].astype(numpy.float32)
            fuori.append(conti / max(float(conti.sum()), 1.0))
    return numpy.concatenate(fuori)


def _griglia_dei_colori(numpy, tavola: _Tavola):
    lato = LATO // CELLE_COLORE
    caselle = tavola.pixel.reshape(CELLE_COLORE, lato, CELLE_COLORE, lato, 3)
    medie = caselle.mean(axis=(1, 3))
    scarti = caselle.std(axis=(1, 3))
    return numpy.concatenate([medie.ravel(), scarti.ravel()]).astype(numpy.float32)


def _pendenze(numpy, luce):
    imbottita = numpy.pad(luce, 1, mode="edge")

    su_sinistra    = imbottita[:-2, :-2]
    su_centro      = imbottita[:-2, 1:-1]
    su_destra      = imbottita[:-2, 2:]
    centro_sinistra = imbottita[1:-1, :-2]
    centro_destra   = imbottita[1:-1, 2:]
    giu_sinistra   = imbottita[2:, :-2]
    giu_centro     = imbottita[2:, 1:-1]
    giu_destra     = imbottita[2:, 2:]

    orizzontale = ((su_destra + 2.0 * centro_destra + giu_destra)
                   - (su_sinistra + 2.0 * centro_sinistra + giu_sinistra))
    verticale = ((giu_sinistra + 2.0 * giu_centro + giu_destra)
                 - (su_sinistra + 2.0 * su_centro + su_destra))
    return orizzontale.astype(numpy.float32), verticale.astype(numpy.float32)


def _istogramma_dei_bordi(numpy, orizzontale, verticale, celle):
    forza = numpy.sqrt(orizzontale ** 2 + verticale ** 2)
    angolo = numpy.arctan2(verticale, orizzontale) % numpy.pi

    scala = angolo / numpy.pi * BIDONI
    basso = numpy.floor(scala).astype(numpy.int32)
    quota = (scala - basso).astype(numpy.float32)

    alte, larghe = forza.shape
    lato_r, lato_c = alte // celle, larghe // celle
    riga = numpy.arange(alte)[:, None] // lato_r
    colonna = numpy.arange(larghe)[None, :] // lato_c
    cella = numpy.clip(riga * celle + colonna, 0, celle * celle - 1)

    fuori = numpy.zeros(celle * celle * BIDONI, dtype=numpy.float32)
    for passo in (0, 1):
        direzione = (basso + passo) % BIDONI
        parte = quota if passo else 1.0 - quota
        piatto = cella * BIDONI + direzione
        fuori += numpy.bincount(piatto.ravel(), weights=(forza * parte).ravel(),
                                minlength=celle * celle * BIDONI).astype(numpy.float32)
    return fuori


def _direzioni_dei_bordi(numpy, tavola: _Tavola):
    orizzontale, verticale = _pendenze(numpy, tavola.luce)
    return _istogramma_dei_bordi(numpy, orizzontale, verticale, CELLE_BORDI)


def _bordi_in_grande(numpy, tavola: _Tavola):
    meta = LATO // 2
    ridotta = tavola.luce.reshape(meta, 2, meta, 2).mean(axis=(1, 3))
    orizzontale, verticale = _pendenze(numpy, ridotta)
    return _istogramma_dei_bordi(numpy, orizzontale, verticale, CELLE_GRANDI)


def _trama(numpy, tavola: _Tavola):
    lato = LATO // CELLE_TRAMA
    base = numpy.frombuffer(tavola.grigia.tobytes(), dtype=numpy.uint8)
    base = base.reshape(LATO, LATO).astype(numpy.float32)

    fuori = []
    for raggio in (1.0, 3.0):
        sfocata = numpy.frombuffer(
            tavola.grigia.filter(ImageFilter.GaussianBlur(radius=raggio)).tobytes(),
            dtype=numpy.uint8,
        ).reshape(LATO, LATO).astype(numpy.float32)
        ruvidita = numpy.abs(base - sfocata) / 255.0
        caselle = ruvidita.reshape(CELLE_TRAMA, lato, CELLE_TRAMA, lato)
        fuori.append(caselle.mean(axis=(1, 3)).ravel())
        fuori.append(caselle.std(axis=(1, 3)).ravel())
    return numpy.concatenate(fuori).astype(numpy.float32)


def _tavola_dei_motivi():
    tavola = []
    for disegno in range(256):
        bit = [(disegno >> posto) & 1 for posto in range(8)]
        salti = sum(1 for posto in range(8) if bit[posto] != bit[(posto + 1) % 8])
        tavola.append(sum(bit) if salti <= 2 else MOTIVI - 1)
    return tavola


_MOTIVI_TAVOLA = _tavola_dei_motivi()


def _motivi_minuti(numpy, tavola: _Tavola):
    luce = tavola.luce
    imbottita = numpy.pad(luce, 1, mode="edge")

    vicini = [
        imbottita[1:-1, 2:],
        imbottita[2:, 2:],
        imbottita[2:, 1:-1],
        imbottita[2:, :-2],
        imbottita[1:-1, :-2],
        imbottita[:-2, :-2],
        imbottita[:-2, 1:-1],
        imbottita[:-2, 2:],
    ]
    quasi = numpy.float32(1e-6)
    disegno = numpy.zeros(luce.shape, dtype=numpy.int32)
    for posto, vicino in enumerate(vicini):
        disegno += ((vicino > luce + quasi).astype(numpy.int32) << posto)

    quale = numpy.array(_MOTIVI_TAVOLA, dtype=numpy.int32)[disegno]

    lato = LATO // CELLE_MOTIVI
    riga = numpy.arange(LATO)[:, None] // lato
    colonna = numpy.arange(LATO)[None, :] // lato
    cella = riga * CELLE_MOTIVI + colonna

    piatto = (cella * MOTIVI + quale).ravel()
    conti = numpy.bincount(piatto, minlength=CELLE_MOTIVI * CELLE_MOTIVI * MOTIVI)
    conti = conti.astype(numpy.float32).reshape(-1, MOTIVI)
    somme = conti.sum(axis=1, keepdims=True)
    return (conti / numpy.where(somme > 0, somme, 1.0)).ravel()


def _quanto_si_somigliano(numpy, una, altra) -> float:
    return float(1.0 - numpy.abs(una - altra).mean())


def _simmetria(numpy, tavola: _Tavola):
    luce, pixel = tavola.luce, tavola.pixel
    meta = LATO // 2

    sinistra, destra = luce[:, :meta], luce[:, meta:][:, ::-1]
    sopra, sotto = luce[:meta, :], luce[meta:, :][::-1, :]
    sinistra_c, destra_c = pixel[:, :meta], pixel[:, meta:][:, ::-1]
    sopra_c, sotto_c = pixel[:meta, :], pixel[meta:, :][::-1, :]

    return numpy.array([
        _quanto_si_somigliano(numpy, sinistra, destra),
        _quanto_si_somigliano(numpy, sinistra_c, destra_c),
        float(sinistra.mean() - destra.mean()),
        _quanto_si_somigliano(numpy, sopra, sotto),
        _quanto_si_somigliano(numpy, sopra_c, sotto_c),
        float(sopra.mean() - sotto.mean()),
    ], dtype=numpy.float32)


def _la_luce(numpy, tavola: _Tavola):
    _, saturazione, _ = tavola.hsv
    conti = numpy.histogram(tavola.luce, bins=LUCE_BIDONI,
                            range=(0.0, 1.0))[0].astype(numpy.float32)
    conti = conti / max(float(conti.sum()), 1.0)
    riassunto = numpy.array([
        float(tavola.luce.mean()),
        float(tavola.luce.std()),
        float(saturazione.mean()),
        float((saturazione < 0.1).mean()),
    ], dtype=numpy.float32)
    return numpy.concatenate([conti, riassunto])
