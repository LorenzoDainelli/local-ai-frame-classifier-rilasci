from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from PIL import Image

from officina import registro
from officina.sicuro.dall_archivio import DallArchivio

PIENO = 65535
PASSO = 257
BIT_IN_USCITA = 10
HEIF = (".heic", ".heif")
COLORE = ("color_primaries", "transfer_characteristics", "matrix_coefficients",
          "full_range_flag")
MEDIA_MASSIMA = 1.0
QUASI_TUTTI = 99.0
SCARTO_QUASI_TUTTI = 3
GIRI = {
    2: lambda a: a[:, ::-1],
    3: lambda a: a[::-1, ::-1],
    4: lambda a: a[::-1],
    5: lambda a: a.transpose(1, 0, 2),
    6: lambda a: np.rot90(a, -1),
    7: lambda a: a[::-1, ::-1].transpose(1, 0, 2),
    8: lambda a: np.rot90(a, 1),
}


@dataclass
class Profonda:

    pixel: np.ndarray
    bit: int
    colore: dict = field(default_factory=dict)


def _suffisso(originale) -> str:
    nome = originale.nome if isinstance(originale, DallArchivio) else str(originale)
    return "." + nome.rsplit(".", 1)[-1].casefold() if "." in nome else ""


def a_otto(pixel: np.ndarray) -> np.ndarray:
    return np.floor(pixel.astype(np.float64) / PASSO + 0.5).clip(0, 255).astype(np.uint8)


def _torna(pixel: np.ndarray, otto: np.ndarray) -> bool:
    if pixel.shape != otto.shape:
        return False
    scarto = np.abs(a_otto(pixel).astype(np.int16) - otto.astype(np.int16))
    return (float(scarto.mean()) <= MEDIA_MASSIMA
            and float(np.percentile(scarto, QUASI_TUTTI)) <= SCARTO_QUASI_TUTTI)


def _pieni(grezzi: np.ndarray, bit: int) -> np.ndarray:
    valori = grezzi.astype(np.uint64) >> (16 - bit)
    massimo = (1 << bit) - 1
    return ((valori * PIENO + massimo // 2) // massimo).astype(np.uint16)


def leggi(originale, dritta: Image.Image, orientamento: int = 1) -> Profonda | None:
    if _suffisso(originale) not in HEIF or dritta.mode != "RGB":
        return None
    import pillow_heif

    sorgente = originale.apri() if isinstance(originale, DallArchivio) else originale
    try:
        heif = pillow_heif.open_heif(sorgente, convert_hdr_to_8bit=False)
        bit = int(heif.info.get("bit_depth") or 8)
        if bit <= 8 or bit > 16 or heif.mode != "RGB;16":
            return None
        grezzi = np.asarray(heif)
        nclx = heif.info.get("nclx_profile") or {}
    except Exception as errore:
        registro.avviso("miglioria.profonda_non_letta", motivo=registro.tipo_di(errore))
        return None
    finally:
        if sorgente is not originale:
            sorgente.close()
    pixel = _pieni(grezzi, bit)
    otto = np.asarray(dritta)
    for prova in (pixel, GIRI.get(orientamento, lambda a: a)(pixel)):
        if _torna(prova, otto):
            colore = {chiave: nclx[chiave] for chiave in COLORE if chiave in nclx}
            return Profonda(np.ascontiguousarray(prova), bit, colore)
    registro.avviso("miglioria.profonda_non_torna", bit=bit)
    return None


def ingrandisci(pixel: np.ndarray, larghezza: int, altezza: int) -> np.ndarray:
    if pixel.shape[1::-1] == (larghezza, altezza):
        return pixel.astype(np.float32)
    canali = [np.asarray(Image.fromarray(pixel[..., c].astype(np.float32), "F").resize(
        (larghezza, altezza), Image.Resampling.LANCZOS)) for c in range(pixel.shape[2])]
    return np.stack(canali, axis=-1)


def a_sedici(valori: np.ndarray) -> np.ndarray:
    return np.floor(valori.astype(np.float64) + 0.5).clip(0, PIENO).astype(np.uint16)


def unisci(pixel: np.ndarray, nuova: Image.Image) -> np.ndarray:
    otto = np.asarray(nuova.convert("RGB"))
    base = ingrandisci(pixel, *nuova.size).astype(np.float64)
    resto = base - np.floor(base / PASSO + 0.5) * PASSO
    return a_sedici(otto.astype(np.float64) * PASSO + resto)


def immagine(pixel: np.ndarray) -> Image.Image:
    return Image.fromarray(a_otto(pixel), "RGB")


def salva(pixel: np.ndarray, colore: dict, verso, exif: bytes | None, xmp: bytes | None,
          icc: bytes | None, qualita: int) -> None:
    import pillow_heif

    massimo = (1 << BIT_IN_USCITA) - 1
    dieci = (pixel.astype(np.uint64) * massimo + PIENO // 2) // PIENO
    dati = (dieci << (16 - BIT_IN_USCITA)).astype(np.uint16)
    alta, larga = dati.shape[:2]
    heif = pillow_heif.from_bytes(mode="RGB;16", size=(larga, alta),
                                  data=np.ascontiguousarray(dati).tobytes())
    opzioni: dict = {"quality": qualita}
    if exif:
        opzioni["exif"] = exif
    if xmp:
        opzioni["xmp"] = xmp
    if icc:
        opzioni["icc_profile"] = icc
    if len(colore) == len(COLORE):
        opzioni.update(colore, save_nclx_profile=True)
    heif.save(verso, **opzioni)
