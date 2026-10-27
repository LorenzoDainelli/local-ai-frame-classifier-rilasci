from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageOps
from PIL.PngImagePlugin import PngInfo

from officina.immagini import lettura
from officina.sicuro.dall_archivio import DallArchivio

FORMATI = {
    ".jpg": "JPEG", ".jpeg": "JPEG", ".heic": "HEIF", ".heif": "HEIF",
    ".png": "PNG", ".tif": "TIFF", ".tiff": "TIFF", ".webp": "WEBP",
    ".avif": "AVIF", ".bmp": "BMP",
}

QUALITA_JPEG = 95
QUALITA_HEIF = 95
QUALITA_WEBP = 95
QUALITA_AVIF = 92

ORIENTAMENTO = 0x0112
SOTTO_EXIF = 0x8769
LARGHEZZA_EXIF = 0xA002
ALTEZZA_EXIF = 0xA003
DATA_DELLO_SCATTO = 0x9003
DATA_DEL_FILE = 0x0132

DELLA_STRUTTURA = {
    0x00FE, 0x00FF, 0x0100, 0x0101, 0x0102, 0x0103, 0x0106, 0x0107, 0x0108,
    0x0109, 0x010A, 0x0111, 0x0115, 0x0116, 0x0117, 0x0118, 0x0119, 0x011A,
    0x011B, 0x011C, 0x0122, 0x0123, 0x0124, 0x0125, 0x0128, 0x012D, 0x013D,
    0x0140, 0x0142, 0x0143, 0x0144, 0x0145, 0x014A, 0x0152, 0x0153, 0x0154,
    0x0155, 0x0156, 0x015B, 0x0201, 0x0202, 0x0211, 0x0212, 0x0213, 0x0214,
}
XMP_TIFF = 700
CHIAVE_XMP_PNG = "XML:com.adobe.xmp"

ORIENTAMENTO_XMP = [
    (re.compile(rb'(tiff:Orientation\s*=\s*")\d+(")'), rb"\g<1>1\g<2>"),
    (re.compile(rb"(<tiff:Orientation>)\s*\d+\s*(</tiff:Orientation>)"),
     rb"\g<1>1\g<2>"),
]


@dataclass
class Metadati:

    exif: bytes | None = None
    xmp: bytes | None = None
    icc: bytes | None = None
    testi_png: dict[str, str] = field(default_factory=dict)


@dataclass
class FotoAperta:

    immagine: Image.Image
    alfa: Image.Image | None
    metadati: Metadati


def formato_di(percorso) -> str:
    suffisso = (percorso.suffix if isinstance(percorso, DallArchivio)
                else Path(percorso).suffix)
    formato = FORMATI.get(suffisso.casefold())
    if formato is None:
        raise ValueError(f"formato che non si migliora: {suffisso}")
    return formato


def _come_byte(valore) -> bytes | None:
    if valore is None:
        return None
    if isinstance(valore, str):
        return valore.encode("utf-8")
    if isinstance(valore, (bytes, bytearray)):
        return bytes(valore) or None
    if isinstance(valore, tuple):
        return bytes(valore) or None
    return None


def leggi_i_metadati(immagine: Image.Image) -> Metadati:
    info = immagine.info
    exif = _come_byte(info.get("exif"))
    if exif is None:
        dentro = immagine.getexif()
        if len(dentro):
            exif = dentro.tobytes()
    xmp = _come_byte(info.get("xmp")) or _come_byte(info.get(CHIAVE_XMP_PNG))
    if xmp is None and getattr(immagine, "tag_v2", None) is not None:
        xmp = _come_byte(immagine.tag_v2.get(XMP_TIFF))
    testi = {}
    if immagine.format == "PNG":
        testi = {chiave: valore for chiave, valore in info.items()
                 if isinstance(valore, str) and chiave != CHIAVE_XMP_PNG}
    return Metadati(exif=exif, xmp=xmp, icc=_come_byte(info.get("icc_profile")),
                    testi_png=testi)


def apri(percorso: Path) -> FotoAperta:
    grezza = lettura.apri(percorso)
    metadati = leggi_i_metadati(grezza)
    dritta = ImageOps.exif_transpose(grezza)
    alfa = None
    if dritta.mode in ("RGBA", "LA", "PA") or (
            dritta.mode == "P" and "transparency" in dritta.info):
        con_alfa = dritta.convert("RGBA")
        alfa = con_alfa.getchannel("A")
        dritta = con_alfa.convert("RGB")
    elif dritta.mode != "RGB":
        dritta = dritta.convert("RGB")
    return FotoAperta(immagine=dritta, alfa=alfa, metadati=metadati)


def exif_raddrizzato(exif: bytes | None, larghezza: int, altezza: int) -> bytes | None:
    if not exif:
        return None
    dati = Image.Exif()
    dati.load(exif)
    for etichetta in DELLA_STRUTTURA:
        dati.pop(etichetta, None)
    dati[ORIENTAMENTO] = 1
    sotto = dati.get_ifd(SOTTO_EXIF)
    if sotto:
        if LARGHEZZA_EXIF in sotto:
            sotto[LARGHEZZA_EXIF] = int(larghezza)
        if ALTEZZA_EXIF in sotto:
            sotto[ALTEZZA_EXIF] = int(altezza)
    return dati.tobytes()


def exif_per_tiff(exif: bytes) -> bytes:
    dati = Image.Exif()
    dati.load(exif)
    sotto = dict(dati.get_ifd(SOTTO_EXIF) or {})
    if DATA_DELLO_SCATTO in sotto and DATA_DEL_FILE not in dati:
        dati[DATA_DEL_FILE] = sotto[DATA_DELLO_SCATTO]
    dati.pop(SOTTO_EXIF, None)
    return dati.tobytes()


def xmp_raddrizzato(xmp: bytes | None) -> bytes | None:
    if not xmp:
        return None
    for trova, metti in ORIENTAMENTO_XMP:
        xmp = trova.sub(metti, xmp)
    return xmp


def salva(immagine: Image.Image, metadati: Metadati, verso: Path, formato: str,
          alfa: Image.Image | None = None) -> None:
    larghezza, altezza = immagine.size
    exif = exif_raddrizzato(metadati.exif, larghezza, altezza)
    xmp = xmp_raddrizzato(metadati.xmp)
    icc = metadati.icc

    if alfa is not None and formato in ("PNG", "WEBP", "TIFF", "AVIF", "HEIF"):
        alfa = alfa.resize(immagine.size, Image.Resampling.LANCZOS)
        immagine = immagine.convert("RGBA")
        immagine.putalpha(alfa)
    elif immagine.mode != "RGB":
        immagine = immagine.convert("RGB")

    opzioni: dict = {}
    if icc:
        opzioni["icc_profile"] = icc
    if formato == "JPEG":
        opzioni.update(quality=QUALITA_JPEG, subsampling=0, optimize=True)
        if exif:
            opzioni["exif"] = exif
        if xmp:
            opzioni["xmp"] = xmp
    elif formato == "HEIF":
        opzioni.update(quality=QUALITA_HEIF)
        if exif:
            opzioni["exif"] = exif
        if xmp:
            opzioni["xmp"] = xmp
    elif formato == "WEBP":
        opzioni.update(quality=QUALITA_WEBP, method=6)
        if exif:
            opzioni["exif"] = exif
        if xmp:
            opzioni["xmp"] = xmp
    elif formato == "AVIF":
        opzioni.update(quality=QUALITA_AVIF)
        if exif:
            opzioni["exif"] = exif
        if xmp:
            opzioni["xmp"] = xmp
    elif formato == "PNG":
        testi = PngInfo()
        for chiave, valore in metadati.testi_png.items():
            testi.add_itxt(chiave, valore)
        if xmp:
            testi.add_itxt(CHIAVE_XMP_PNG, xmp.decode("utf-8", "replace"))
        opzioni["pnginfo"] = testi
        if exif:
            opzioni["exif"] = exif
    elif formato == "TIFF":
        opzioni["compression"] = "tiff_adobe_deflate"
        if exif:
            opzioni["exif"] = exif_per_tiff(exif)
        if xmp:
            opzioni["tiffinfo"] = {XMP_TIFF: xmp}
    elif formato == "BMP":
        opzioni.pop("icc_profile", None)
    else:
        raise ValueError(f"formato sconosciuto: {formato}")

    verso.parent.mkdir(parents=True, exist_ok=True)
    with open(verso, "wb") as uscita:
        immagine.save(uscita, formato, **opzioni)
