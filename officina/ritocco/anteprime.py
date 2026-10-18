from __future__ import annotations

import dataclasses
import re

from PIL import Image

from officina.miglioria.metadati import SOTTO_EXIF, Metadati

NOTE_DELLA_MACCHINA = 0x927C
DI_PHOTOSHOP = (0x8649, 0x935C)
DI_APPLE = b"Apple iOS"

NELL_XMP = (
    ("http://ns.adobe.com/xap/1.0/", ("Thumbnails",)),
    ("http://ns.adobe.com/xap/1.0/g/img/", ("image",)),
    ("http://ns.google.com/photos/1.0/image/", ("Data",)),
    ("http://ns.google.com/photos/1.0/depthmap/", ("Data", "Confidence")),
    ("http://ns.google.com/photos/1.0/container/", ("Directory",)),
    ("http://ns.google.com/photos/1.0/camera/",
     ("MicroVideo", "MicroVideoVersion", "MicroVideoOffset",
      "MicroVideoPresentationTimestampUs", "MotionPhoto", "MotionPhotoVersion",
      "MotionPhotoPresentationTimestampUs")),
    ("http://ns.adobe.com/xmp/note/", ("HasExtendedXMP",)),
)


def via(metadati: Metadati) -> Metadati:
    return dataclasses.replace(metadati, exif=exif_senza(metadati.exif),
                               xmp=xmp_senza(metadati.xmp))


def exif_senza(exif: bytes | None) -> bytes | None:
    if not exif:
        return exif
    dati = Image.Exif()
    dati.load(exif)
    for etichetta in (*DI_PHOTOSHOP, NOTE_DELLA_MACCHINA):
        dati.pop(etichetta, None)
    sotto = dati.get_ifd(SOTTO_EXIF)
    nota = sotto.get(NOTE_DELLA_MACCHINA)
    if nota is not None and not _di_apple(nota):
        del sotto[NOTE_DELLA_MACCHINA]
    return dati.tobytes()


def _di_apple(nota) -> bool:
    if isinstance(nota, str):
        nota = nota.encode("latin-1", "replace")
    try:
        return bytes(nota).startswith(DI_APPLE)
    except (TypeError, ValueError):
        return False


def _prefissi(xmp: bytes, indirizzo: str) -> set[bytes]:
    cerca = re.compile(rb"xmlns:([A-Za-z_][\w.-]*)\s*=\s*[\"']" + re.escape(indirizzo.encode())
                       + rb"[\"']")
    return set(cerca.findall(xmp))


def xmp_senza(xmp: bytes | None) -> bytes | None:
    if not xmp:
        return xmp
    for indirizzo, nomi in NELL_XMP:
        for prefisso in _prefissi(xmp, indirizzo):
            for nome in nomi:
                etichetta = re.escape(prefisso + b":" + nome.encode())
                xmp = re.sub(rb"\s+" + etichetta + rb"\s*=\s*(\"[^\"]*\"|'[^']*')", b"", xmp)
                xmp = re.sub(rb"<" + etichetta + rb"(\s[^>]*)?/>", b"", xmp)
                xmp = re.sub(rb"<" + etichetta + rb"(\s[^>]*)?>.*?</" + etichetta + rb"\s*>",
                             b"", xmp, flags=re.DOTALL)
    return xmp
