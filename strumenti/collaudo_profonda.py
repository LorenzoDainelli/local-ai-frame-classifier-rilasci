from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import struct
import subprocess
import sys
import tarfile
import urllib.request
import zlib
from pathlib import Path

import numpy as np
import pillow_heif
import png
from PIL import Image, ImageCms

from officina.miglioria import catena, fedelta, motori, profonda

TESTIMAGES = ("https://sourceforge.net/projects/testimages/files/SAMPLING/16BIT/RGB/"
              "SAMPLING_16BIT_RGB_600x600.tar.bz2/download")
QUANTE = 8
VARIANTI = ("normale", "buio", "rumore", "sfocata", "compressa", "cielo")
DIFFICILI = ("buio", "rumore", "sfocata", "compressa", "cielo")
DATA = "2021:07:08 09:10:11"
PRIMARIE = 12
TRASFERIMENTO = 13
LATO_LISCIO = 32
FORMATI = {"heic": 10, "png": 16, "tif": 16, "avif": 10}
LATITUDINE = (43.0, 46.0, 12.0)
LISCIO = 0.004


class OttoBit:

    nome = motori.LUCIDFLUX
    versione = "collaudo"

    def __init__(self, **_opzioni) -> None:
        pass

    def foto(self, immagine, larghezza: int, altezza: int):
        return immagine.resize((larghezza, altezza), Image.Resampling.LANCZOS)

    def spegni(self) -> None:
        pass


def scarica(cartella: Path) -> list[dict]:
    cartella.mkdir(parents=True, exist_ok=True)
    archivio = cartella / "testimages.tar.bz2"
    if not archivio.exists():
        with urllib.request.urlopen(TESTIMAGES, timeout=600) as risposta:
            archivio.write_bytes(risposta.read())
    prese = []
    with tarfile.open(archivio) as dentro:
        nomi = sorted(n for n in dentro.getnames() if n.lower().endswith(".png"))
        for nome in nomi[:QUANTE]:
            dati = dentro.extractfile(nome).read()
            prese.append({"nome": Path(nome).name, "dati": dati,
                          "sha256": hashlib.sha256(dati).hexdigest()})
    return {"archivio_sha256": hashlib.sha256(archivio.read_bytes()).hexdigest(),
            "foto": prese}


def sedici(dati: bytes) -> np.ndarray:
    larga, alta, righe, info = png.Reader(bytes=dati).asDirect()
    if info["bitdepth"] != 16 or info["planes"] < 3:
        raise ValueError(f"non è RGB a 16 bit: {info['bitdepth']} bit, {info['planes']}")
    pixel = np.vstack([np.asarray(r, dtype=np.uint16) for r in righe])
    return pixel.reshape(alta, larga, info["planes"])[..., :3]


def variante(pixel: np.ndarray, nome: str, seme: int) -> np.ndarray:
    valori = pixel.astype(np.float64)
    if nome == "buio":
        valori = valori / 10.0
    elif nome == "rumore":
        valori = valori + np.random.default_rng(seme).normal(0, 900, valori.shape)
    elif nome == "sfocata":
        piccola = profonda.ingrandisci(pixel, pixel.shape[1] // 4, pixel.shape[0] // 4)
        valori = profonda.ingrandisci(piccola, pixel.shape[1], pixel.shape[0])
    elif nome == "cielo":
        piccola = profonda.ingrandisci(pixel, 24, 24)
        valori = profonda.ingrandisci(piccola, pixel.shape[1], pixel.shape[0])
    return profonda.a_sedici(valori)


def _exif(gps: bool) -> Image.Exif:
    exif = Image.Exif()
    exif[0x010F] = "Collaudo"
    exif.get_ifd(0x8769)[0x9003] = DATA
    if gps:
        exif.get_ifd(0x8825).update({1: "N", 2: LATITUDINE})
    return exif


def _icc() -> bytes:
    profilo = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB"))
    return profilo.tobytes()


ICC = _icc()


def _pezzo_png(tipo: bytes, corpo: bytes) -> bytes:
    return (struct.pack(">I", len(corpo)) + tipo + corpo
            + struct.pack(">I", zlib.crc32(tipo + corpo) & 0xFFFFFFFF))


def _scrivi_heic(pixel: np.ndarray, verso: Path, qualita: int) -> None:
    dieci = (pixel.astype(np.uint64) * 1023 + 32767) // 65535
    alta, larga = pixel.shape[:2]
    heif = pillow_heif.from_bytes(mode="RGB;16", size=(larga, alta),
                                  data=(dieci << 6).astype(np.uint16).tobytes())
    heif.save(verso, quality=qualita, exif=_exif(False).tobytes(),
              color_primaries=PRIMARIE, transfer_characteristics=TRASFERIMENTO,
              matrix_coefficients=6, full_range_flag=1, save_nclx_profile=True)


def _scrivi_png(pixel: np.ndarray, verso: Path, _qualita: int) -> None:
    import imagecodecs

    dati = imagecodecs.png_encode(np.ascontiguousarray(pixel), level=6)
    fine = 8 + 12 + struct.unpack(">I", dati[8:12])[0]
    aggiunte = (_pezzo_png(b"iCCP", b"Collaudo\0\0" + zlib.compress(ICC))
                + _pezzo_png(b"eXIf", _exif(True).tobytes()[6:]))
    verso.write_bytes(dati[:fine] + aggiunte + dati[fine:])


def _scrivi_tif(pixel: np.ndarray, verso: Path, _qualita: int) -> None:
    import tifffile

    exif = _exif(True)
    uscita = io.BytesIO()
    tifffile.imwrite(uscita, np.ascontiguousarray(pixel), photometric="rgb",
                     compression="zlib", iccprofile=ICC, metadata=None,
                     byteorder="<", bigtiff=False,
                     extratags=[(271, "s", 0, "Collaudo", True),
                                (306, "s", 0, DATA, True)])
    verso.write_bytes(profonda._con_gps(uscita.getvalue(), exif.get_ifd(0x8825)))


def _scrivi_avif(pixel: np.ndarray, verso: Path, qualita: int) -> None:
    import imagecodecs

    dieci = ((pixel.astype(np.uint64) * 1023 + 32767) // 65535).astype(np.uint16)
    dati = imagecodecs.avif_encode(np.ascontiguousarray(dieci), level=qualita,
                                   bitspersample=10, primaries=PRIMARIE,
                                   transfer=TRASFERIMENTO, matrix=6)
    verso.write_bytes(profonda._con_dati(dati, _exif(True).tobytes(), None, None))


SCRITTORI = {"heic": _scrivi_heic, "png": _scrivi_png, "tif": _scrivi_tif,
             "avif": _scrivi_avif}


def scrivi(pixel: np.ndarray, verso: Path, qualita: int) -> None:
    SCRITTORI[verso.suffix[1:]](pixel, verso, qualita)
    os.utime(verso, (1_600_000_000, 1_600_000_000))


def _otto_a_sedici(pixel: np.ndarray) -> np.ndarray:
    return pixel.astype(np.uint16) * profonda.PASSO


def leggi(percorso: Path) -> tuple[int, np.ndarray, dict]:
    formato = percorso.suffix[1:]
    if formato == "heic":
        letta = pillow_heif.open_heif(percorso, convert_hdr_to_8bit=False)
        pixel = np.asarray(letta)
        colore = letta.info.get("nclx_profile") or {}
        if pixel.dtype == np.uint8:
            return 8, _otto_a_sedici(pixel), colore
        bit = int(letta.info["bit_depth"])
        return bit, profonda._pieni(pixel, bit), colore
    if formato == "avif":
        import imagecodecs

        dati = percorso.read_bytes()
        bit, colore = profonda.colore_avif(dati)
        pixel = imagecodecs.avif_decode(dati)
        if pixel.dtype == np.uint8:
            return 8, _otto_a_sedici(pixel), colore
        return bit, profonda._scala(pixel, bit), colore
    if formato == "png":
        import imagecodecs

        pixel = imagecodecs.png_decode(percorso.read_bytes())
    else:
        import tifffile

        pixel = tifffile.imread(percorso)
    pixel = pixel[..., :3]
    if pixel.dtype == np.uint8:
        return 8, _otto_a_sedici(pixel), {}
    return 16, pixel, {}


def lisci(riferimento: np.ndarray) -> np.ndarray:
    alta, larga = riferimento.shape[:2]
    maschera = np.zeros((alta, larga), bool)
    for y in range(0, alta - LATO_LISCIO + 1, LATO_LISCIO):
        for x in range(0, larga - LATO_LISCIO + 1, LATO_LISCIO):
            pezzo = riferimento[y:y + LATO_LISCIO, x:x + LATO_LISCIO] / 65535.0
            salti = (np.abs(np.diff(pezzo, axis=1)).mean()
                     + np.abs(np.diff(pezzo, axis=0)).mean())
            if salti < LISCIO:
                maschera[y:y + LATO_LISCIO, x:x + LATO_LISCIO] = True
    return maschera


def scarto(pixel: np.ndarray, riferimento: np.ndarray, dove: np.ndarray) -> float | None:
    if not dove.any():
        return None
    differenza = (pixel.astype(np.float64) - riferimento) / profonda.PASSO
    return round(float(np.sqrt((differenza[dove] ** 2).mean())), 4)


def una(originale: Path, cartella: Path, motore: str, a_otto: bool) -> dict:
    quanti = "8" if a_otto else "16"
    uscita = cartella / f"{originale.stem}-{motore}-{quanti}{originale.suffix}"
    vero = profonda.leggi
    if a_otto:
        profonda.leggi = lambda *_a, **_k: None
    try:
        catena.foto({"genere": "immagine", "originale": str(originale),
                     "uscita": str(uscita), "motori": {"foto": motore, "volti": None},
                     "misura": "fhd"})
    finally:
        profonda.leggi = vero
    bit, pixel, colore = leggi(uscita)
    with Image.open(uscita) as aperta:
        exif = aperta.getexif()
        icc = aperta.info.get("icc_profile")
        gps = exif.get_ifd(0x8825).get(2)
        data = exif.get_ifd(0x8769).get(0x9003) or exif.get(306)
    return {"file": uscita, "bit": bit, "pixel": pixel, "nclx": colore, "icc": icc,
            "gps": gps, "data": data, "fatta_da": exif.get(0x010F),
            "ora_file": int(uscita.stat().st_mtime),
            "perde": fedelta.cosa_perde(originale, uscita),
            "sedici_vere": motore == motori.FINTO}


def come_la_vede_il_mac(programma: Path | None, percorso: Path) -> dict | None:
    if programma is None:
        return None
    fatto = subprocess.run([str(programma), "bit", str(percorso)], check=True,
                           capture_output=True, text=True)
    return json.loads(fatto.stdout)


def giudica(otto: dict, alta: dict, liscio8: float | None, liscio16: float | None,
            tutto8: float, tutto16: float, formato: str = "heic") -> list[str]:
    guasti = []
    voluti = FORMATI[formato]
    mac = alta.get("mac")
    if mac is not None and mac.get("bit") != voluti:
        guasti.append(f"macOS la vede a {mac.get('bit')} bit")
    if alta["bit"] != voluti:
        guasti.append(f"salvata a {alta['bit']} bit")
    if formato in ("heic", "avif"):
        if alta["nclx"].get("color_primaries") != PRIMARIE or \
                alta["nclx"].get("transfer_characteristics") != TRASFERIMENTO:
            guasti.append("profilo colore cambiato")
    elif alta["icc"] != ICC:
        guasti.append("profilo ICC cambiato")
    if alta["data"] != DATA or alta["fatta_da"] != "Collaudo":
        guasti.append("EXIF perso")
    if formato != "heic" and tuple(float(v) for v in alta["gps"] or ()) != LATITUDINE:
        guasti.append("posizione GPS persa")
    if alta["ora_file"] != 1_600_000_000:
        guasti.append("data del file persa")
    if alta["perde"]:
        guasti.append("dice che perde: " + ", ".join(alta["perde"]))
    if tutto16 > tutto8 + 0.02:
        guasti.append("a 16 bit è più lontana dal vero che a 8")
    if liscio8 is not None and liscio16 is not None:
        if alta["sedici_vere"] and liscio16 >= liscio8:
            guasti.append("a 16 bit le sfumature non migliorano")
        if liscio16 > liscio8 + 0.01:
            guasti.append("a 16 bit le sfumature peggiorano")
    if otto["bit"] != 8:
        guasti.append("la strada a 8 bit non è a 8")
    return guasti


def medie(righe: list[dict]) -> dict:
    uscita = {}
    for motore in sorted({r["motore"] for r in righe}):
        for difficile in (False, True):
            sue = [r for r in righe if r["motore"] == motore and r["difficile"] == difficile
                   and r.get("scarto_liscio_8") is not None]
            if not sue:
                continue
            chiave = f"{motore} · {'difficili' if difficile else 'facili'}"
            uscita[chiave] = {
                campo: round(sum(r[campo] for r in sue) / len(sue), 4)
                for campo in ("scarto_liscio_8", "scarto_liscio_16")}
    return uscita


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cartella", type=Path, required=True)
    parser.add_argument("--uscita", type=Path, required=True)
    parser.add_argument("--programma", type=Path)
    parser.add_argument("--formato", choices=sorted(FORMATI), default="heic")
    argomenti = parser.parse_args()
    cartella = argomenti.cartella
    motori.FOTO[motori.LUCIDFLUX] = f"{__name__}:OttoBit"
    prese = scarica(cartella / "testimages")
    righe = []
    for numero, presa in enumerate(prese["foto"]):
        pixel = sedici(presa["dati"])
        for nome in VARIANTI:
            fatta = variante(pixel, nome, numero)
            originale = cartella / f"{Path(presa['nome']).stem}-{nome}.{argomenti.formato}"
            scrivi(fatta, originale, 40 if nome == "compressa" else 95)
            _bit, vera, _colore = leggi(originale)
            for motore in (motori.FINTO, motori.LUCIDFLUX):
                riga = {"foto": presa["nome"], "sha256": presa["sha256"],
                        "variante": nome, "difficile": nome in DIFFICILI,
                        "motore": "solo ingrandire" if motore == motori.FINTO
                        else "motore a 8 bit"}
                try:
                    otto = una(originale, cartella, motore, True)
                    alta = una(originale, cartella, motore, False)
                    alta["mac"] = come_la_vede_il_mac(argomenti.programma, alta["file"])
                    larga, lunga = alta["pixel"].shape[1], alta["pixel"].shape[0]
                    riferimento = profonda.ingrandisci(vera, larga, lunga).astype(np.float64)
                    dove = lisci(riferimento)
                    tutti = np.ones(dove.shape, bool)
                    liscio8 = scarto(otto["pixel"], riferimento, dove)
                    liscio16 = scarto(alta["pixel"], riferimento, dove)
                    tutto8 = scarto(otto["pixel"], riferimento, tutti)
                    tutto16 = scarto(alta["pixel"], riferimento, tutti)
                    riga.update(bit=alta["bit"], mac=alta["mac"],
                                parte_liscia=round(float(dove.mean()), 3),
                                scarto_liscio_8=liscio8, scarto_liscio_16=liscio16,
                                scarto_8=tutto8, scarto_16=tutto16)
                    riga["guasti"] = giudica(otto, alta, liscio8, liscio16, tutto8, tutto16,
                                             argomenti.formato)
                except Exception as errore:
                    riga["guasti"] = [f"{type(errore).__name__}: {errore}"]
                righe.append(riga)
                print(json.dumps({k: v for k, v in riga.items() if k != "sha256"},
                                 ensure_ascii=False), flush=True)
    difficili = [r for r in righe if r["difficile"]]
    conti = {"formato": argomenti.formato, "tutte": len(righe),
             "giuste": sum(not r["guasti"] for r in righe),
             "difficili": len(difficili),
             "difficili_giuste": sum(not r["guasti"] for r in difficili),
             "archivio_sha256": prese["archivio_sha256"], "medie": medie(righe)}
    argomenti.uscita.write_text(json.dumps({"conti": conti, "righe": righe}, indent=1,
                                           ensure_ascii=False, default=str),
                                encoding="utf-8")
    print(json.dumps(conti))
    return 0 if conti["giuste"] == conti["tutte"] else 1


if __name__ == "__main__":
    sys.exit(main())
