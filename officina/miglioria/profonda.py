from __future__ import annotations

import io
import struct
import zlib
from dataclasses import dataclass, field

import numpy as np
from PIL import Image

from officina import registro
from officina.sicuro.dall_archivio import DallArchivio

PIENO = 65535
PASSO = 257
MEZZO_PASSO = 128
RAGGIO = 3
BIT_IN_USCITA = 10
HEIF = (".heic", ".heif")
PNG = (".png",)
TIFF = (".tif", ".tiff")
AVIF = (".avif",)
FIRMA_PNG = b"\x89PNG\r\n\x1a\n"
PNG_RGB = 2
PNG_DEI_COLORI = (b"cHRM", b"gAMA", b"sRGB", b"cICP", b"mDCV", b"cLLI", b"sBIT", b"pHYs")
TESTA_EXIF = b"Exif\0\0"
CHIAVE_XMP_PNG = "XML:com.adobe.xmp"
XMP_TIFF = 700
PROGRAMMA_TIFF = 305
BIT_TIFF = 258
TIFF_GIA_SCRITTE = frozenset({
    0x00FE, 0x0100, 0x0101, 0x0102, 0x0103, 0x0106, 0x0111, 0x0115, 0x0116, 0x0117,
    0x011C, 0x013D, 0x0152, 0x0153, 0x8769, 0x8773, 0x8825, XMP_TIFF})
GPS_TIFF = 0x8825
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
    scatole: list[bytes] = field(default_factory=list)


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


def _scala(valori: np.ndarray, bit: int) -> np.ndarray:
    massimo = (1 << bit) - 1
    return ((valori.astype(np.uint64) * PIENO + massimo // 2) // massimo).astype(np.uint16)


def _pieni(grezzi: np.ndarray, bit: int) -> np.ndarray:
    return _scala(grezzi.astype(np.uint64) >> (16 - bit), bit)


def _byte(originale) -> bytes:
    if isinstance(originale, DallArchivio):
        with originale.apri() as sorgente:
            return sorgente.read()
    with open(originale, "rb") as sorgente:
        return sorgente.read()


def _rgb16(pixel) -> bool:
    return pixel.dtype == np.uint16 and pixel.ndim == 3 and pixel.shape[2] == 3


def _da_heif(originale):
    import pillow_heif

    sorgente = originale.apri() if isinstance(originale, DallArchivio) else originale
    try:
        heif = pillow_heif.open_heif(sorgente, convert_hdr_to_8bit=False)
        bit = int(heif.info.get("bit_depth") or 8)
        if bit <= 8 or bit > 16 or heif.mode != "RGB;16":
            return None
        nclx = heif.info.get("nclx_profile") or {}
        colore = {chiave: nclx[chiave] for chiave in COLORE if chiave in nclx}
        return _pieni(np.asarray(heif), bit), bit, colore
    finally:
        if sorgente is not originale:
            sorgente.close()


def _da_png(originale):
    dati = _byte(originale)
    if dati[:8] != FIRMA_PNG or dati[12:16] != b"IHDR" or dati[24] != 16 \
            or dati[25] != PNG_RGB:
        return None
    import imagecodecs

    pixel = imagecodecs.png_decode(dati)
    return (pixel, 16, {"png": scatole_png(dati)}) if _rgb16(pixel) else None


def _da_tiff(originale):
    import imagecodecs

    pixel = imagecodecs.tiff_decode(_byte(originale))
    return (pixel, 16, {}) if _rgb16(pixel) else None


def colore_avif(dati: bytes) -> tuple[int, dict]:
    from officina.miglioria import heif_scatole

    heif = heif_scatole.leggi(dati)
    bit, colore = 8, {}
    for _essenziale, indice in heif.legami.get(heif.primaria, []):
        if not indice:
            continue
        scatola = heif.proprieta[indice - 1]
        if scatola[4:8] == b"pixi" and len(scatola) > 13:
            bit = scatola[13]
        elif scatola[4:8] == b"colr" and scatola[8:12] == b"nclx" and len(scatola) >= 19:
            colore = {
                "color_primaries": int.from_bytes(scatola[12:14], "big"),
                "transfer_characteristics": int.from_bytes(scatola[14:16], "big"),
                "matrix_coefficients": int.from_bytes(scatola[16:18], "big"),
                "full_range_flag": scatola[18] >> 7,
            }
    return bit, colore


def _da_avif(originale):
    dati = _byte(originale)
    bit, colore = colore_avif(dati)
    if bit <= 8 or bit > 16:
        return None
    import imagecodecs

    pixel = imagecodecs.avif_decode(dati)
    return (_scala(pixel, bit), bit, colore) if _rgb16(pixel) else None


def bit_del_file(originale) -> int:
    suffisso = _suffisso(originale)
    if suffisso in PNG:
        dati = _byte(originale)
        return dati[24] if dati[:8] == FIRMA_PNG and len(dati) > 25 else 8
    if suffisso in AVIF:
        return colore_avif(_byte(originale))[0]
    if suffisso in TIFF:
        sorgente = originale.apri() if isinstance(originale, DallArchivio) else originale
        try:
            with Image.open(sorgente) as tiff:
                bit = tiff.tag_v2.get(BIT_TIFF, 8)
        finally:
            if sorgente is not originale:
                sorgente.close()
        return max(bit) if isinstance(bit, tuple) else int(bit)
    return 8


LETTORI = {**{s: _da_heif for s in HEIF}, **{s: _da_png for s in PNG},
           **{s: _da_tiff for s in TIFF}, **{s: _da_avif for s in AVIF}}


def leggi(originale, dritta: Image.Image, orientamento: int = 1) -> Profonda | None:
    lettore = LETTORI.get(_suffisso(originale))
    if lettore is None or dritta.mode != "RGB":
        return None
    try:
        letta = lettore(originale)
    except Exception as errore:
        registro.avviso("miglioria.profonda_non_letta", motivo=registro.tipo_di(errore))
        return None
    if letta is None:
        return None
    pixel, bit, colore = letta
    scatole = colore.pop("png", [])
    otto = np.asarray(dritta)
    for prova in (pixel, GIRI.get(orientamento, lambda a: a)(pixel)):
        if _torna(prova, otto):
            return Profonda(np.ascontiguousarray(prova), bit, colore, scatole)
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


def _media(valori: np.ndarray, raggio: int) -> np.ndarray:
    for asse in (0, 1):
        bordi = [(0, 0)] * valori.ndim
        bordi[asse] = (raggio + 1, raggio)
        somme = np.cumsum(np.pad(valori, bordi, mode="edge"), axis=asse, dtype=np.float64)
        lungo = valori.shape[asse]
        valori = ((np.take(somme, np.arange(2 * raggio + 1, 2 * raggio + 1 + lungo), asse)
                   - np.take(somme, np.arange(lungo), asse)) / (2 * raggio + 1)
                  ).astype(np.float32)
    return valori


def unisci(pixel: np.ndarray, nuova: Image.Image) -> np.ndarray:
    otto = np.asarray(nuova.convert("RGB")).astype(np.float32) * PASSO
    base = ingrandisci(pixel, *nuova.size).astype(np.float32)
    spinta = _media(_media(otto - base, RAGGIO), RAGGIO)
    return a_sedici(np.clip(base + spinta, otto - MEZZO_PASSO, otto + MEZZO_PASSO))


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


def _senza_testa_exif(exif: bytes) -> bytes:
    return exif[6:] if exif.startswith(TESTA_EXIF) else exif


def _pezzo_png(tipo: bytes, corpo: bytes) -> bytes:
    return (struct.pack(">I", len(corpo)) + tipo + corpo
            + struct.pack(">I", zlib.crc32(tipo + corpo) & 0xFFFFFFFF))


def _testo_png(chiave: str, valore: str) -> bytes:
    return _pezzo_png(b"iTXt", chiave.encode("latin-1", "replace")[:79]
                      + b"\0\0\0\0\0" + valore.encode("utf-8"))


def scatole_png(dati: bytes) -> list[bytes]:
    tenute, dove = [], 8
    while dove + 12 <= len(dati):
        lungo = struct.unpack(">I", dati[dove:dove + 4])[0]
        tipo = dati[dove + 4:dove + 8]
        if tipo in PNG_DEI_COLORI:
            tenute.append(dati[dove:dove + 12 + lungo])
        if tipo == b"IDAT":
            break
        dove += 12 + lungo
    return tenute


def salva_png(pixel: np.ndarray, verso, exif: bytes | None, xmp: bytes | None,
              icc: bytes | None, testi: dict[str, str], scatole: list[bytes]) -> None:
    import imagecodecs

    dati = imagecodecs.png_encode(np.ascontiguousarray(pixel), level=9)
    fine_testa = 8 + 12 + struct.unpack(">I", dati[8:12])[0]
    aggiunte = []
    if icc:
        aggiunte.append(_pezzo_png(b"iCCP", b"ICC\0\0" + zlib.compress(icc, 9)))
    aggiunte += [s for s in scatole if not (icc and s[4:8] in (b"sRGB", b"iCCP"))]
    if exif:
        aggiunte.append(_pezzo_png(b"eXIf", _senza_testa_exif(exif)))
    for chiave, valore in testi.items():
        aggiunte.append(_testo_png(chiave, valore))
    if xmp:
        aggiunte.append(_testo_png(CHIAVE_XMP_PNG, xmp.decode("utf-8", "replace")))
    verso.write(dati[:fine_testa] + b"".join(aggiunte) + dati[fine_testa:])


def _etichetta_tiff(numero: int, valore):
    from PIL.TiffImagePlugin import IFDRational

    if isinstance(valore, str):
        return (numero, "s", 0, valore, True)
    if isinstance(valore, IFDRational):
        return (numero, "2I", 1, (valore.numerator, valore.denominator), True)
    if isinstance(valore, bool) or not isinstance(valore, (int, bytes, tuple)):
        return None
    if isinstance(valore, int):
        return (numero, "I", 1, valore, True) if valore >= 0 else None
    if isinstance(valore, bytes):
        return (numero, "B", len(valore), valore, True)
    if valore and all(isinstance(v, int) and v >= 0 for v in valore):
        return (numero, "I", len(valore), valore, True)
    return None


def _con_gps(dati: bytes, gps: dict) -> bytes:
    from PIL import TiffImagePlugin

    if dati[:4] != b"II*\0":
        raise ValueError("TIFF inatteso")
    uscita = bytearray(dati)
    uscita += b"\0" * (len(uscita) % 2)
    sotto = TiffImagePlugin.ImageFileDirectory_v2(prefix=b"II")
    sotto[GPS_TIFF] = gps
    blocco = sotto.tobytes(len(uscita))
    posto = struct.unpack("<I", blocco[10:14])[0]
    uscita += blocco
    uscita += b"\0" * (len(uscita) % 2)
    prima = struct.unpack("<I", uscita[4:8])[0]
    quante = struct.unpack("<H", uscita[prima:prima + 2])[0]
    voci = [bytes(uscita[prima + 2 + 12 * i:prima + 14 + 12 * i]) for i in range(quante)]
    seguente = uscita[prima + 2 + 12 * quante:prima + 6 + 12 * quante]
    voci.append(struct.pack("<HHII", GPS_TIFF, 4, 1, posto))
    voci.sort(key=lambda voce: struct.unpack("<H", voce[:2])[0])
    nuova = len(uscita)
    uscita += struct.pack("<H", len(voci)) + b"".join(voci) + seguente
    uscita[4:8] = struct.pack("<I", nuova)
    return bytes(uscita)


def salva_tiff(pixel: np.ndarray, verso, exif: bytes | None, xmp: bytes | None,
               icc: bytes | None) -> int:
    import tifffile

    etichette, saltate, programma, gps = [], 0, False, {}
    if exif:
        dati = Image.Exif()
        dati.load(exif)
        gps = dict(dati.get_ifd(GPS_TIFF) or {})
        for numero, valore in sorted(dati.items()):
            if numero in TIFF_GIA_SCRITTE:
                continue
            if numero == PROGRAMMA_TIFF and isinstance(valore, str):
                programma = valore
                continue
            etichetta = _etichetta_tiff(numero, valore)
            if etichetta is None:
                saltate += 1
            else:
                etichette.append(etichetta)
    if xmp:
        etichette.append((XMP_TIFF, "B", len(xmp), xmp, True))
    scritto = io.BytesIO()
    tifffile.imwrite(scritto, np.ascontiguousarray(pixel), photometric="rgb",
                     compression="zlib", predictor=True, iccprofile=icc, byteorder="<",
                     bigtiff=False, extratags=etichette, metadata=None,
                     software=programma)
    dati = scritto.getvalue()
    verso.write(_con_gps(dati, gps) if gps else dati)
    return saltate


def _con_dati(dati: bytes, exif: bytes | None, xmp: bytes | None,
              icc: bytes | None) -> bytes:
    from officina.miglioria import heif_scatole as scatole

    if not (exif or xmp or icc):
        return dati
    heif = scatole.leggi(dati)
    voci = dict(heif.voci)
    contenuti = {n: (heif.dove[n].metodo, scatole.contenuto(heif, n)) for n in heif.dove}
    rimandi = list(heif.rimandi)
    proprieta = list(heif.proprieta)
    legami = {n: list(u) for n, u in heif.legami.items()}
    prossimo = max(voci) + 1
    for tipo, resto, corpo in (
            (b"Exif", b"\0", exif and b"\0\0\0\0" + _senza_testa_exif(exif)),
            (b"mime", b"\0application/rdf+xml\0", xmp)):
        if corpo:
            voci[prossimo] = scatole.Voce(prossimo, tipo, resto)
            contenuti[prossimo] = (0, corpo)
            rimandi.append((scatole.DESCRIVE, prossimo, [heif.primaria]))
            prossimo += 1
    if icc:
        proprieta.append(scatole._scatola(b"colr", b"prof" + icc))
        legami.setdefault(heif.primaria, []).append((False, len(proprieta)))
    return scatole.scrivi(heif, voci, contenuti, rimandi, proprieta, legami)


def salva_avif(pixel: np.ndarray, colore: dict, verso, exif: bytes | None,
               xmp: bytes | None, icc: bytes | None, qualita: int) -> None:
    import imagecodecs

    massimo = (1 << BIT_IN_USCITA) - 1
    dieci = ((pixel.astype(np.uint64) * massimo + PIENO // 2) // PIENO).astype(np.uint16)
    opzioni = {}
    if len(colore) == len(COLORE):
        opzioni = {"primaries": colore["color_primaries"],
                   "transfer": colore["transfer_characteristics"],
                   "matrix": colore["matrix_coefficients"]}
    dati = imagecodecs.avif_encode(np.ascontiguousarray(dieci), level=qualita,
                                   bitspersample=BIT_IN_USCITA, **opzioni)
    verso.write(_con_dati(dati, exif, xmp, icc))
