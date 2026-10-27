from __future__ import annotations

import os
import re
import struct
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from PIL import Image

from officina.errori import FileNonLeggibile
from officina.immagini import lettura
from officina.importazione import quicktime
from officina.modello.luoghi import coordinate_valide
from officina.sicuro import dall_archivio


MISURE_SCHERMO = {
    (640, 1136), (750, 1334), (828, 1792), (1080, 1920), (1125, 2436),
    (1170, 2532), (1179, 2556), (1242, 2208), (1242, 2688), (1284, 2778),
    (1290, 2796), (1206, 2622), (1320, 2868),
    (1536, 2048), (1620, 2160), (1668, 2224), (1668, 2388), (2048, 2732),
    (1280, 720), (1280, 800), (1366, 768), (1440, 900), (1600, 900),
    (1680, 1050), (1920, 1080), (1920, 1200), (2560, 1080), (2560, 1440),
    (2560, 1600), (2880, 1800), (3440, 1440), (3840, 2160),
}
MISURE_SCHERMO |= {(alta, larga) for larga, alta in MISURE_SCHERMO}


@dataclass
class Metadati:

    genere: str
    formato: str | None = None
    larghezza: int | None = None
    altezza: int | None = None
    orientamento: int | None = None
    durata_ms: int | None = None

    data_locale: str | None = None
    fuso_minuti: int | None = None
    istante_utc: str | None = None
    origine_data: str = "assente"

    latitudine: float | None = None
    longitudine: float | None = None

    identificatore_ios: str | None = None
    marca: str | None = None
    modello: str | None = None
    sembra_schermata: bool = False

    avvertenze: list[str] = field(default_factory=list)

    @property
    def giorno(self) -> str | None:
        return self.data_locale[:10] if self.data_locale else None

    @property
    def ha_data(self) -> bool:
        return self.data_locale is not None


DATA_GENERICA = 0x0132
FUSO_GENERICO = 0x9010
ORIENTAMENTO = 0x0112
MARCA = 0x010F
MODELLO = 0x0110
IFD_EXIF = 0x8769
IFD_GPS = 0x8825
DATA_ORIGINALE = 0x9003
DATA_DIGITALIZZATA = 0x9004
FUSO_ORIGINALE = 0x9011
FUSO_DIGITALIZZATO = 0x9012
NOTA_COSTRUTTORE = 0x927C

DIMENSIONE_TIPO = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 6: 1, 7: 1, 8: 2, 9: 4, 10: 8, 11: 4, 12: 8}


def _identificatore_apple(nota: bytes) -> str | None:
    if not isinstance(nota, bytes) or not nota.startswith(b"Apple iOS"):
        return None
    try:
        ordine = ">" if nota[12:14] == b"MM" else "<"
        quante = struct.unpack(ordine + "H", nota[14:16])[0]
        for indice in range(min(quante, 128)):
            voce = 16 + indice * 12
            etichetta, tipo, conteggio = struct.unpack(ordine + "HHI", nota[voce:voce + 8])
            if etichetta != 0x0011:
                continue
            lunghezza = conteggio * DIMENSIONE_TIPO.get(tipo, 1)
            if lunghezza <= 4:
                grezzo = nota[voce + 8:voce + 8 + lunghezza]
            else:
                scarto = struct.unpack(ordine + "I", nota[voce + 8:voce + 12])[0]
                grezzo = nota[scarto:scarto + lunghezza]
            testo = grezzo.decode("ascii", "replace").strip("\x00 ")
            return testo or None
    except (struct.error, IndexError, UnicodeDecodeError):
        return None
    return None


def _gradi(valore) -> float | None:
    try:
        gradi, minuti, secondi = (float(x) for x in valore)
        return gradi + minuti / 60 + secondi / 3600
    except (TypeError, ValueError):
        return None


def _luogo(gps: dict) -> tuple[float | None, float | None]:
    latitudine = _gradi(gps.get(2))
    longitudine = _gradi(gps.get(4))
    if latitudine is not None and str(gps.get(1, "N")).upper().startswith("S"):
        latitudine = -latitudine
    if longitudine is not None and str(gps.get(3, "E")).upper().startswith("W"):
        longitudine = -longitudine
    return coordinate_valide(latitudine, longitudine)


CAMPI_XMP = ("exif:DateTimeOriginal", "photoshop:DateCreated", "xmp:CreateDate",
             "exif:DateTimeDigitized", "xap:CreateDate")


LIMITE_XMP = 256 * 1024


def _valore_xmp(testo: str, campo: str) -> str | None:
    nome = re.escape(campo)
    trovato = re.search(nome + r'\s{0,16}=\s{0,16}"([^"]{1,128})"', testo)
    if trovato and trovato.group(1).strip():
        return trovato.group(1).strip()
    for trovato in re.finditer("<" + nome + r">([^<]*)</" + nome + ">", testo):
        valore = trovato.group(1).strip()
        if valore:
            return valore
    return None


def _date_da_xmp(immagine) -> list[tuple[str, str]]:
    grezzo = immagine.info.get("xmp") or immagine.info.get("XML:com.adobe.xmp")
    if not grezzo:
        return []
    if isinstance(grezzo, (bytes, bytearray)):
        testo = bytes(grezzo[:LIMITE_XMP]).decode("utf-8", "replace")
    else:
        testo = str(grezzo)[:LIMITE_XMP]
    trovate = []
    for campo in CAMPI_XMP:
        valore = _valore_xmp(testo, campo)
        if valore:
            trovate.append((campo, valore))
    return trovate


CAMPI_PNG = ("Creation Time", "date:create", "creation_time", "DateTimeOriginal")


def _con_fuso(valore, fuso) -> str:
    testo = str(valore).replace("\x00", "").strip()
    if fuso:
        testo = f"{testo}{str(fuso).replace(chr(0), '').strip()}"
    return testo


def date_candidate(immagine, exif, esteso) -> list[tuple[str, str, str]]:
    candidate = []
    if esteso.get(DATA_ORIGINALE):
        candidate.append(("exif", "data di scatto", _con_fuso(
            esteso.get(DATA_ORIGINALE), esteso.get(FUSO_ORIGINALE))))
    if esteso.get(DATA_DIGITALIZZATA):
        candidate.append(("exif", "data di digitalizzazione", _con_fuso(
            esteso.get(DATA_DIGITALIZZATA),
            esteso.get(FUSO_DIGITALIZZATO) or esteso.get(FUSO_ORIGINALE))))
    for campo, valore in _date_da_xmp(immagine):
        candidate.append(("xmp", "xmp " + campo, valore))
    if exif and exif.get(DATA_GENERICA):
        candidate.append(("exif", "data generica", _con_fuso(
            exif.get(DATA_GENERICA), esteso.get(FUSO_GENERICO))))
    for campo in CAMPI_PNG:
        valore = immagine.info.get(campo)
        if isinstance(valore, str) and valore.strip():
            candidate.append(("exif", "testo " + campo, valore))
    return candidate


def _exif_senza_caricare(immagine):
    if lettura.senza_exif_pesante(immagine):
        return {}
    try:
        return immagine.getexif()
    except Exception:
        return {}


def da_immagine(percorso: Path) -> Metadati:
    immagine = lettura.intestazione(percorso)
    try:
        dati = _leggi_immagine(immagine)
        lettura.controlla_fino_in_fondo(immagine, percorso)
        return dati
    finally:
        immagine.close()


def _leggi_immagine(immagine) -> Metadati:
    dati = Metadati(genere="immagine", formato=(immagine.format or "").lower() or None)

    exif = _exif_senza_caricare(immagine)

    dati.orientamento = exif.get(ORIENTAMENTO) if exif else None
    dati.larghezza, dati.altezza = lettura.misure_raddrizzate(
        immagine.width, immagine.height, dati.orientamento
    )
    if exif:
        dati.marca = str(exif.get(MARCA) or "").replace("\x00", "").strip() or None
        dati.modello = str(exif.get(MODELLO) or "").replace("\x00", "").strip() or None

    esteso = {}
    gps = {}
    if exif:
        try:
            esteso = exif.get_ifd(IFD_EXIF) or {}
        except Exception:
            esteso = {}
        try:
            gps = exif.get_ifd(IFD_GPS) or {}
        except Exception:
            gps = {}

    for origine, _, testo in date_candidate(immagine, exif, esteso):
        locale, minuti, assoluto = quicktime._data_da_stringa(testo)
        if locale:
            dati.data_locale, dati.fuso_minuti, dati.istante_utc = locale, minuti, assoluto
            dati.origine_data = origine
            break

    if gps:
        dati.latitudine, dati.longitudine = _luogo(gps)

    nota = esteso.get(NOTA_COSTRUTTORE)
    if nota:
        dati.identificatore_ios = _identificatore_apple(nota)

    dati.sembra_schermata = (
        not dati.marca
        and not dati.modello
        and (dati.larghezza, dati.altezza) in MISURE_SCHERMO
    )

    return dati


def da_video(percorso: Path) -> Metadati:
    video = quicktime.leggi(percorso)
    larghezza, altezza = quicktime.misure_raddrizzate(video)
    if not larghezza or not altezza:
        from officina.immagini import fotogrammi
        larghezza, altezza = fotogrammi.misure_dal_decodificatore(percorso)
    dati = Metadati(
        genere="video",
        formato=percorso.suffix.lower().lstrip("."),
        larghezza=larghezza,
        altezza=altezza,
        durata_ms=video.durata_ms,
        data_locale=video.data_locale,
        fuso_minuti=video.fuso_minuti,
        istante_utc=video.istante_utc,
        origine_data=video.origine_data,
        latitudine=video.latitudine,
        longitudine=video.longitudine,
        identificatore_ios=video.identificatore_ios,
        marca=video.marca,
        modello=video.modello,
    )
    if dati.durata_ms is None:
        dati.avvertenze.append(
            "Non sono riuscito a leggere la durata: lo tratto come video autonomo."
        )
    return dati


CON_LA_DATA_DEL_FILE = True

NOME_CON_DATA = re.compile(
    r"(?<!\d)((?:19|20)\d\d)[-_.]?(0[1-9]|1[0-2])[-_.]?(0[1-9]|[12]\d|3[01])"
    r"(?:[-_ T.]?([01]\d|2[0-3])[-_.:]?([0-5]\d)[-_.:]?([0-5]\d))?(?!\d)")


def data_dal_nome(nome: str) -> str | None:
    for trovato in NOME_CON_DATA.finditer(nome):
        anno, mese, giorno, ora, minuto, secondo = trovato.groups()
        testo = f"{anno}-{mese}-{giorno}"
        if ora:
            testo += f"T{ora}:{minuto}:{secondo}"
        locale = quicktime._data_da_stringa(testo)[0]
        if locale:
            return locale
    return None


def data_del_file(percorso: Path) -> str | None:
    try:
        stato = percorso.stat()
    except OSError:
        return None
    momenti = [stato.st_mtime]
    nascita = getattr(stato, "st_birthtime", None)
    if nascita:
        momenti.append(nascita)
    elif os.name == "nt":
        momenti.append(stato.st_ctime)
    momenti = [m for m in momenti if m and m > 0]
    if not momenti:
        return None
    try:
        momento = datetime.fromtimestamp(min(momenti))
    except (OverflowError, OSError, ValueError):
        return None
    return quicktime._data_da_stringa(momento.strftime("%Y-%m-%dT%H:%M:%S"))[0]


def _metti_la_data_di_ripiego(dati: Metadati, percorso: Path) -> Metadati:
    if dati.ha_data:
        return dati
    locale, origine = data_dal_nome(percorso.name), "nome"
    if not locale and CON_LA_DATA_DEL_FILE:
        locale, origine = data_del_file(percorso), "file"
    if locale:
        dati.data_locale, dati.fuso_minuti, dati.istante_utc = locale, None, None
        dati.origine_data = origine
    return dati


def leggi(percorso: Path) -> Metadati:
    return _metti_la_data_di_ripiego(_leggi_dentro(percorso), percorso)


def _leggi_dentro(percorso: Path) -> Metadati:
    genere = lettura.genere_dal_nome(percorso)
    if genere == "immagine":
        return da_immagine(percorso)
    if genere == "video":
        return da_video(percorso)

    try:
        with (dall_archivio.per_av(percorso) as sorgente,
              Image.open(sorgente, formats=lettura.formati_aperti()) as prova):
            prova.verify()
        return da_immagine(percorso)
    except Exception as errore:
        raise FileNonLeggibile(
            f"«{percorso.name}» non è né una foto né un video che riesco ad aprire.",
            codice="non_supportato",
        ) from errore


def _esteso_e_exif(immagine):
    exif = _exif_senza_caricare(immagine)
    if not exif:
        return {}, {}
    try:
        esteso = exif.get_ifd(IFD_EXIF) or {}
    except Exception:
        esteso = {}
    return exif, esteso


def diagnosi(percorso: Path) -> list[tuple[str, str]]:
    genere = lettura.genere_dal_nome(percorso)
    if genere == "video":
        video = quicktime.leggi(percorso)
        righe = []
        if video.creazione_mvhd is None:
            righe.append(("data del filmato", "assente: non ho trovato l'intestazione del video"))
        elif video.creazione_mvhd == 0:
            righe.append(("data del filmato", "vuota (zero)"))
        else:
            righe.append(("data del filmato", "c'è"))
        righe.append(("data delle tracce", "c'è" if video.creazione_traccia else "assente o vuota"))
        for campo, valore in (("data Apple", video.data_apple),
                              ("data ©day", video.data_di_scorta)):
            if not valore:
                righe.append((campo, "assente"))
            elif quicktime._data_da_stringa(valore)[0]:
                righe.append((campo, "c'è"))
            else:
                righe.append((campo, f"scritta in un modo che non capisco: «{valore[:40]}»"))
        return righe
    try:
        immagine = lettura.intestazione(percorso)
    except FileNonLeggibile:
        return [("file", "non si apre")]
    try:
        exif, esteso = _esteso_e_exif(immagine)
        candidate = date_candidate(immagine, exif, esteso)
    finally:
        immagine.close()
    if not candidate:
        return [("campi di data", "nessuno: dentro il file non c'è nessuna data")]
    righe = []
    for _, campo, testo in candidate:
        if quicktime._data_da_stringa(testo)[0]:
            righe.append((campo, "c'è"))
        else:
            righe.append((campo, f"scritta in un modo che non capisco: «{testo[:40]}»"))
    return righe
