from __future__ import annotations

import io

from PIL import Image

from officina.corpi import maschere as maschere_dei_corpi
from officina.descrittori import vettori
from officina.ritocco import elenco, maschere, pixela

LATO_DI_LAVORO = 2048
AI_LATI = 0.2
SOPRA = 0.35
SOTTO = 0.1
COPERTO = 0.5
PEZZI_AL_MASSIMO = 60
LATO_MINIMO = 16
ORIENTAMENTO = 0x0112


def volto_allargato(riquadro) -> list[float]:
    x, y, larga, alta = (float(valore) for valore in riquadro)
    return [round(max(0.0, x - larga * AI_LATI), 5), round(max(0.0, y - alta * SOPRA), 5),
            round(min(1.0, x + larga * (1 + AI_LATI)), 5),
            round(min(1.0, y + alta * (1 + SOTTO)), 5)]


def _allarga(maschera):
    numpy = vettori.numpy_o_spiega()
    alta, larga = maschera.shape
    grande = numpy.zeros((alta + 2, larga + 2), dtype=bool)
    for dy in range(3):
        for dx in range(3):
            grande[dy:dy + alta, dx:dx + larga] |= maschera
    return grande


def _png(maschera) -> bytes:
    numpy = vettori.numpy_o_spiega()
    scritto = io.BytesIO()
    Image.fromarray(numpy.asarray(maschera, dtype=numpy.uint8) * 255, "L").convert("1").save(
        scritto, "PNG", optimize=True)
    return scritto.getvalue()


def corpo_per_lo_strumento(maschera: bytes, riquadro) -> tuple[bytes, list[float]]:
    numpy = vettori.numpy_o_spiega()
    x, y, larga, alta = (float(valore) for valore in riquadro)
    piena = maschere_dei_corpi.apri(maschera)
    if not piena.size or not piena.any():
        return _png(numpy.ones((1, 1), dtype=bool)), [x, y, x + larga, y + alta]
    righe, colonne = piena.shape
    passo_x, passo_y = larga / colonne, alta / righe
    return _png(_allarga(piena)), [x - passo_x, y - passo_y,
                                   x + larga + passo_x, y + alta + passo_y]


def misure_dritte(percorso) -> tuple[int, int] | None:
    from officina.immagini import lettura
    from officina.sicuro.dall_archivio import per_av

    try:
        with per_av(percorso) as sorgente, \
                Image.open(sorgente, formats=lettura.formati_aperti()) as immagine:
            larga, alta = immagine.size
            try:
                girata = immagine.getexif().get(ORIENTAMENTO)
            except Exception:
                girata = None
    except Exception:
        return None
    return lettura.misure_raddrizzate(larga, alta, girata)


def stessa_forma(larga: int, alta: int, base: tuple[int, int]) -> bool:
    base_larga, base_alta = base
    return abs(larga * base_alta - alta * base_larga) <= 2 * max(base_larga, base_alta)


def dal_browser(dati: bytes, larga: int, alta: int):
    numpy = vettori.numpy_o_spiega()
    with Image.open(io.BytesIO(dati), formats=("PNG",)) as immagine:
        if immagine.size != (larga, alta):
            raise ValueError
        grigia = numpy.asarray(immagine.convert("L"))
    return grigia > 127


def volti_in_pixel(volti, larga: int, alta: int) -> dict[int, tuple[int, int, int, int]]:
    fuori = {}
    for volto_id, (x, y, w, h) in volti.items():
        x1, y1 = max(0, round(x * larga)), max(0, round(y * alta))
        x2, y2 = min(larga, round((x + w) * larga)), min(alta, round((y + h) * alta))
        if x2 > x1 and y2 > y1:
            fuori[volto_id] = (x1, y1, x2, y2)
    return fuori


def misura_sicura(maschera, cosa: str, volti: dict, suo: int | None = None) -> float:
    numpy = vettori.numpy_o_spiega()
    righe = numpy.flatnonzero(maschera.any(axis=1))
    colonne = numpy.flatnonzero(maschera.any(axis=0))
    larga = int(colonne[-1] - colonne[0] + 1)
    alta = int(righe[-1] - righe[0] + 1)
    misura = float(larga if cosa == elenco.VOLTO else min(larga, alta))
    for volto_id, (x1, y1, x2, y2) in volti.items():
        area = (x2 - x1) * (y2 - y1)
        coperta = int(maschera[y1:y2, x1:x2].sum())
        if volto_id == suo or coperta >= COPERTO * area:
            misura = max(misura, float(x2 - x1))
    return misura


def pezzo_per_la_copia(maschera, cosa: str, larga: int, alta: int, volti: dict, *,
                       quadretto: int | None = None, volto_id: int | None = None,
                       corpo_id: int | None = None, scelta: dict | None = None,
                       suo: int | None = None) -> dict:
    misura = misura_sicura(maschera, cosa, volti, volto_id if suo is None else suo)
    return {"cosa": cosa, "larghezza": larga, "altezza": alta,
            "maschera": maschere.comprimi(maschera, (0, 0), larga, alta),
            "misura": misura, "quadretto": pixela.quadretto(misura, quadretto),
            "volto_id": volto_id, "corpo_id": corpo_id, "scelta": scelta}
