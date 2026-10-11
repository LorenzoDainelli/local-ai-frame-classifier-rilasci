from __future__ import annotations

from dataclasses import dataclass

from PIL import Image, ImageChops, ImageFilter

INTERA = "intera"
PERSONA = "persona"
STRETTO = "stretto"
INQUADRATURE = (INTERA, PERSONA, STRETTO)

FINE = 192
GRIGLIA = 48
SFOCATURA = 2.0


@dataclass(frozen=True)
class Ritaglio:

    inquadratura: str
    metodo: str
    riquadro: tuple[float, float, float, float]
    immagine: Image.Image


def in_quadrato(immagine: Image.Image, lato: int) -> Image.Image:
    if immagine.mode != "RGB":
        immagine = immagine.convert("RGB")
    larghezza, altezza = immagine.size
    if larghezza == altezza:
        return immagine.resize((lato, lato), Image.Resampling.LANCZOS)

    ridotta = immagine.copy()
    ridotta.thumbnail((lato, lato), Image.Resampling.LANCZOS)
    sfondo = Image.new("RGB", (lato, lato), _colore_dei_bordi(ridotta))
    sfondo.paste(ridotta, ((lato - ridotta.width) // 2, (lato - ridotta.height) // 2))
    return sfondo


def _colore_dei_bordi(immagine: Image.Image) -> tuple[int, int, int]:
    larghezza, altezza = immagine.size
    spessore = max(1, min(larghezza, altezza) // 20)
    strisce = [
        immagine.crop((0, 0, larghezza, spessore)),
        immagine.crop((0, altezza - spessore, larghezza, altezza)),
        immagine.crop((0, 0, spessore, altezza)),
        immagine.crop((larghezza - spessore, 0, larghezza, altezza)),
    ]
    somma = [0, 0, 0]
    pixel = 0
    for striscia in strisce:
        grezzo = striscia.resize((8, 8), Image.Resampling.BILINEAR).tobytes()
        for inizio in range(0, len(grezzo), 3):
            somma[0] += grezzo[inizio]
            somma[1] += grezzo[inizio + 1]
            somma[2] += grezzo[inizio + 2]
            pixel += 1
    return tuple(int(valore / max(pixel, 1)) for valore in somma)  # type: ignore[return-value]


def _mappa_del_dettaglio(immagine: Image.Image) -> list[list[float]]:
    grigia = immagine.convert("L").resize((FINE, FINE), Image.Resampling.BILINEAR)
    sfocata = grigia.filter(ImageFilter.GaussianBlur(SFOCATURA))
    dettaglio = ImageChops.difference(grigia, sfocata)
    riassunto = dettaglio.resize((GRIGLIA, GRIGLIA), Image.Resampling.BOX)
    valori = riassunto.tobytes()
    return [
        [float(valori[riga * GRIGLIA + colonna]) for colonna in range(GRIGLIA)]
        for riga in range(GRIGLIA)
    ]


def _somme_progressive(mappa: list[list[float]]) -> list[list[float]]:
    lato = len(mappa)
    somme = [[0.0] * (lato + 1) for _ in range(lato + 1)]
    for riga in range(lato):
        riga_corrente = 0.0
        for colonna in range(lato):
            riga_corrente += mappa[riga][colonna]
            somme[riga + 1][colonna + 1] = somme[riga][colonna + 1] + riga_corrente
    return somme


def _finestra_migliore(somme: list[list[float]], lato_finestra: int) -> tuple[int, int]:
    lato = len(somme) - 1
    migliore = (-1.0, 0, 0)
    for riga in range(0, lato - lato_finestra + 1):
        for colonna in range(0, lato - lato_finestra + 1):
            totale = (somme[riga + lato_finestra][colonna + lato_finestra]
                      - somme[riga][colonna + lato_finestra]
                      - somme[riga + lato_finestra][colonna]
                      + somme[riga][colonna])
            if totale > migliore[0]:
                migliore = (totale, riga, colonna)
    return migliore[1], migliore[2]


def riquadro_del_dettaglio(immagine: Image.Image,
                           parte: float = 0.32) -> tuple[float, float, float, float]:
    mappa = _mappa_del_dettaglio(immagine)
    somme = _somme_progressive(mappa)
    lato_finestra = max(4, int(GRIGLIA * parte))
    riga, colonna = _finestra_migliore(somme, lato_finestra)
    return (colonna / GRIGLIA, riga / GRIGLIA,
            lato_finestra / GRIGLIA, lato_finestra / GRIGLIA)


def _ritaglia(immagine: Image.Image,
              riquadro: tuple[float, float, float, float]) -> Image.Image:
    larghezza, altezza = immagine.size
    x, y, larga, alta = riquadro
    sinistra = int(x * larghezza)
    sopra = int(y * altezza)
    destra = min(larghezza, sinistra + max(1, int(larga * larghezza)))
    sotto = min(altezza, sopra + max(1, int(alta * altezza)))
    return immagine.crop((sinistra, sopra, destra, sotto))


def _riquadro_centrale(immagine: Image.Image) -> tuple[float, float, float, float]:
    larghezza, altezza = immagine.size
    lato = min(larghezza, altezza) * 0.82
    return ((larghezza - lato) / 2 / larghezza,
            (altezza - lato) / 2 / altezza,
            lato / larghezza, lato / altezza)


def tre_inquadrature(immagine: Image.Image, lato: int = 224) -> list[Ritaglio]:
    if immagine.mode != "RGB":
        immagine = immagine.convert("RGB")

    centrale = _riquadro_centrale(immagine)
    dettaglio = riquadro_del_dettaglio(immagine)
    return [
        Ritaglio(INTERA, "intera", (0.0, 0.0, 1.0, 1.0), in_quadrato(immagine, lato)),
        Ritaglio(PERSONA, "centrale", centrale,
                 in_quadrato(_ritaglia(immagine, centrale), lato)),
        Ritaglio(STRETTO, "dettaglio", dettaglio,
                 in_quadrato(_ritaglia(immagine, dettaglio), lato)),
    ]


def inquadratura_per_profondita(profondita: int) -> str:
    return INQUADRATURE[min(profondita, len(INQUADRATURE) - 1)]
