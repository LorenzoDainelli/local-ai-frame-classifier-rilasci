from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageChops, ImageFilter

from officina import registro
from officina.descrittori import vettori
from officina.immagini import fotogrammi, lettura

LATO_DEL_CONFRONTO = 96
SFOCATURA = 1.2
DIFFERENZA_MEDIA_MASSIMA = 10.0
SALTO_FORTE = 40
PARTE_CAMBIATA_MASSIMA = 0.03
VOLTO_UGUALE = 0.75
LATO_PER_I_VOLTI = 1280

CAMBIATA = "immagine_cambiata"
PEZZI_CAMBIATI = "pezzi_cambiati"
VOLTO_CAMBIATO = "volto_cambiato"
VOLTI_DIVERSI = "volti_diversi"

PAROLE = {
    CAMBIATA: "L'immagine nel suo insieme è diversa dall'originale.",
    PEZZI_CAMBIATI: "In alcuni punti sono comparsi o spariti dei dettagli.",
    VOLTO_CAMBIATO: "Un volto non sembra più la stessa persona.",
    VOLTI_DIVERSI: "Il numero di volti trovati è cambiato.",
}


def _in_piccolo(immagine: Image.Image, misura: tuple[int, int]) -> Image.Image:
    return (immagine.convert("L").resize(misura, Image.Resampling.LANCZOS)
            .filter(ImageFilter.GaussianBlur(SFOCATURA)))


def quanto_cambia(prima: Image.Image, dopo: Image.Image) -> tuple[float, float]:
    base = prima.copy()
    base.thumbnail((LATO_DEL_CONFRONTO, LATO_DEL_CONFRONTO), Image.Resampling.LANCZOS)
    misura = base.size
    uno = _in_piccolo(prima, misura)
    altro = _in_piccolo(dopo, misura)
    conti = ImageChops.difference(uno, altro).histogram()
    quanti = sum(conti)
    if not quanti:
        return 0.0, 0.0
    media = sum(valore * volte for valore, volte in enumerate(conti)) / quanti
    forti = sum(conti[SALTO_FORTE + 1:]) / quanti
    return round(media, 2), round(forti, 4)


def _centro(faccia, scala: float) -> tuple[float, float]:
    x, y, larga, alta = faccia.riquadro
    return (x + larga / 2) * scala, (y + alta / 2) * scala


def confronta_volti(rilevatore, prima: Image.Image, dopo: Image.Image) -> dict:
    facce_prima = [f for f in rilevatore.guarda(prima) if f.impronta]
    facce_dopo = [f for f in rilevatore.guarda(dopo) if f.impronta]
    scala = prima.width / dopo.width if dopo.width else 1.0
    peggiore = None
    for faccia in facce_prima:
        cx, cy = _centro(faccia, 1.0)
        vicina = min(
            facce_dopo,
            key=lambda f: (_centro(f, scala)[0] - cx) ** 2 + (_centro(f, scala)[1] - cy) ** 2,
            default=None)
        if vicina is None:
            continue
        simile = vettori.somiglianza(faccia.impronta, vicina.impronta)
        peggiore = simile if peggiore is None else min(peggiore, simile)
    return {"prima": len(facce_prima), "dopo": len(facce_dopo),
            "somiglianza": None if peggiore is None else round(peggiore, 3)}


def giudica(media: float, forti: float, volti: dict | None) -> list[str]:
    motivi = []
    if media > DIFFERENZA_MEDIA_MASSIMA:
        motivi.append(CAMBIATA)
    if forti > PARTE_CAMBIATA_MASSIMA:
        motivi.append(PEZZI_CAMBIATI)
    if volti:
        if volti["prima"] != volti["dopo"]:
            motivi.append(VOLTI_DIVERSI)
        if volti["somiglianza"] is not None and volti["somiglianza"] < VOLTO_UGUALE:
            motivi.append(VOLTO_CAMBIATO)
    return motivi


def _coppia(genere: str, originale: Path, migliorata: Path, lato: int | None):
    if genere == "video":
        return (fotogrammi.copertina(originale, lato),
                fotogrammi.copertina(migliorata, lato))
    return (lettura.copia_di_lavoro(originale, lato),
            lettura.copia_di_lavoro(migliorata, lato))


def controlla(genere: str, originale: Path, migliorata: Path,
              rilevatore=None) -> dict:
    try:
        prima, dopo = _coppia(genere, originale, migliorata, LATO_PER_I_VOLTI)
        if prima is None or dopo is None:
            return {"fatto": False}
        media, forti = quanto_cambia(prima, dopo)
        volti = None
        if rilevatore is not None:
            try:
                volti = confronta_volti(rilevatore, prima, dopo)
            except Exception as errore:                  # noqa: BLE001
                registro.avviso("miglioria.fedelta_volti_non_guardati",
                                motivo=registro.tipo_di(errore))
        motivi = giudica(media, forti, volti)
        return {"fatto": True, "media": media, "forti": forti, "volti": volti,
                "motivi": motivi}
    except Exception as errore:                          # noqa: BLE001
        registro.avviso("miglioria.fedelta_non_misurata",
                        motivo=registro.tipo_di(errore))
        return {"fatto": False}


def in_parole(testo: str | None) -> dict:
    try:
        esito = json.loads(testo) if testo else {}
    except ValueError:
        esito = {}
    motivi = esito.get("motivi") or []
    return {
        "misurata": bool(esito.get("fatto")),
        "sconsigliata": bool(motivi),
        "motivi": [PAROLE[m] for m in motivi if m in PAROLE],
    }
