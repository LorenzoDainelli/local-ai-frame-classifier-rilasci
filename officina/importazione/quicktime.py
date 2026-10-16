from __future__ import annotations

import math
import struct
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import BinaryIO, Iterator

from officina.modello.luoghi import coordinate_valide

SCARTO_1904 = 2082844800

CONTENITORI = {b"moov", b"trak", b"mdia", b"udta", b"meta", b"ilst", b"edts"}

FOGLIA_MASSIMA = 512 * 1024

CAMPIONI_MASSIMI = 2_000_000

MISURA_MASSIMA_CAMPIONE = 64 * 1024 * 1024

FUSO_MASSIMO_MINUTI = 14 * 60


@dataclass
class DatiVideo:
    durata_ms: int | None = None
    larghezza: int | None = None
    altezza: int | None = None
    data_locale: str | None = None
    fuso_minuti: int | None = None
    istante_utc: str | None = None
    origine_data: str = "assente"
    identificatore_ios: str | None = None
    latitudine: float | None = None
    longitudine: float | None = None
    marca: str | None = None
    modello: str | None = None
    rotazione: int = 0
    data_di_scorta: str | None = None
    luogo_di_scorta: str | None = None
    creazione_mvhd: int | None = None
    creazione_traccia: int | None = None
    data_apple: str | None = None


def _atomi(file: BinaryIO, inizio: int, fine: int) -> Iterator[tuple[bytes, int, int]]:
    posizione = inizio
    while posizione + 8 <= fine:
        file.seek(posizione)
        intestazione = file.read(8)
        if len(intestazione) < 8:
            return
        lunghezza = struct.unpack(">I", intestazione[:4])[0]
        nome = intestazione[4:8]
        contenuto = posizione + 8
        if lunghezza == 1:
            esteso = file.read(8)
            if len(esteso) < 8:
                return
            lunghezza = struct.unpack(">Q", esteso)[0]
            contenuto = posizione + 16
        elif lunghezza == 0:
            lunghezza = fine - posizione
        if lunghezza < contenuto - posizione or posizione + lunghezza > fine:
            return
        yield nome, contenuto, posizione + lunghezza
        posizione += lunghezza


def _leggi(file: BinaryIO, inizio: int, fine: int) -> bytes:
    if fine <= inizio:
        return b""
    file.seek(inizio)
    return file.read(min(fine - inizio, FOGLIA_MASSIMA))


ANNO_MINIMO = 1971


def _data_da_stringa(testo: str) -> tuple[str | None, int | None, str | None]:
    testo = testo.replace("\x00", "").strip()
    if not testo:
        return None, None, None
    fuso_minuti = None
    corpo = testo
    if testo.endswith("Z"):
        corpo, fuso_minuti = testo[:-1], 0
    else:
        for segno in ("+", "-"):
            taglio = testo.rfind(segno)
            if taglio > 9:
                corpo = testo[:taglio]
                pezzo = testo[taglio + 1:].replace(":", "")
                if len(pezzo) >= 4 and pezzo[:4].isascii() and pezzo[:4].isdecimal():
                    ore, primi = int(pezzo[:2]), int(pezzo[2:4])
                    minuti = ore * 60 + primi
                    if primi < 60 and minuti <= FUSO_MASSIMO_MINUTI:
                        fuso_minuti = minuti if segno == "+" else -minuti
                break
    corpo = corpo.strip()
    if len(corpo) >= 10 and corpo[4] in "/." and corpo[7] == corpo[4]:
        corpo = corpo[:4] + "-" + corpo[5:7] + "-" + corpo[8:]
    corpo = corpo.split(".")[0].split(",")[0].strip()
    tentativi = (corpo, corpo.replace(" ", "T"), corpo.replace("T", " "))
    for forma, quanto in (("%Y-%m-%dT%H:%M:%S", 19), ("%Y:%m:%d %H:%M:%S", 19),
                          ("%Y-%m-%d %H:%M:%S", 19), ("%Y:%m:%dT%H:%M:%S", 19),
                          ("%Y-%m-%dT%H:%M", 16), ("%Y:%m:%d %H:%M", 16),
                          ("%Y-%m-%d", 10), ("%Y:%m:%d", 10)):
        momento = None
        for tentativo in tentativi:
            try:
                momento = datetime.strptime(tentativo[:quanto], forma)
                break
            except ValueError:
                continue
        if momento is None:
            continue
        if momento.year < ANNO_MINIMO:
            return None, None, None
        if quanto == 10:
            momento = momento.replace(hour=12)
        locale = momento.strftime("%Y-%m-%dT%H:%M:%S")
        if fuso_minuti is None:
            return locale, None, None
        try:
            assoluto = (momento - timedelta(minutes=fuso_minuti)).replace(tzinfo=timezone.utc)
        except OverflowError:
            return None, None, None
        return locale, fuso_minuti, assoluto.strftime("%Y-%m-%dT%H:%M:%SZ")
    return None, None, None


def _iso6709(testo: str) -> tuple[float | None, float | None]:
    numeri = []
    corrente = ""
    for carattere in testo:
        if carattere in "+-":
            if corrente:
                numeri.append(corrente)
            corrente = carattere
        elif carattere.isdecimal() or carattere == ".":
            corrente += carattere
        else:
            break
    if corrente:
        numeri.append(corrente)
    try:
        if len(numeri) >= 2:
            return coordinate_valide(float(numeri[0]), float(numeri[1]))
    except ValueError:
        pass
    return None, None


def _chiavi_e_valori(file: BinaryIO, inizio: int, fine: int) -> dict[str, bytes]:
    nomi: list[str] = []
    valori: dict[int, bytes] = {}

    for nome, contenuto, fine_atomo in _atomi(file, inizio, fine):
        if nome == b"keys":
            dati = _leggi(file, contenuto, fine_atomo)
            if len(dati) < 8:
                continue
            quante = struct.unpack(">I", dati[4:8])[0]
            posizione = 8
            for _ in range(min(quante, 512)):
                if posizione + 8 > len(dati):
                    break
                lunghezza = struct.unpack(">I", dati[posizione:posizione + 4])[0]
                if lunghezza < 8 or posizione + lunghezza > len(dati):
                    break
                nomi.append(dati[posizione + 8:posizione + lunghezza].decode("utf-8", "replace"))
                posizione += lunghezza
        elif nome == b"ilst":
            for indice_bytes, dentro, fine_dentro in _atomi(file, contenuto, fine_atomo):
                indice = struct.unpack(">I", indice_bytes)[0]
                for tipo, d2, f2 in _atomi(file, dentro, fine_dentro):
                    if tipo == b"data":
                        grezzo = _leggi(file, d2, f2)
                        if len(grezzo) > 8:
                            valori[indice] = grezzo[8:]

    return {
        nomi[indice - 1]: valore
        for indice, valore in valori.items()
        if 1 <= indice <= len(nomi)
    }


def leggi(percorso: Path) -> DatiVideo:
    dati = DatiVideo()
    try:
        dimensione = percorso.stat().st_size
        with open(percorso, "rb") as file:
            for nome, contenuto, fine in _atomi(file, 0, dimensione):
                if nome != b"moov":
                    continue
                _leggi_moov(file, contenuto, fine, dati)
            if dati.creazione_mvhd is None:
                _cerca_mvhd(file, dimensione, dati)
    except (OSError, struct.error, RecursionError):
        return dati

    if dati.origine_data != "apple" and dati.data_di_scorta:
        locale, fuso, assoluto = _data_da_stringa(dati.data_di_scorta)
        if locale:
            dati.data_locale, dati.fuso_minuti, dati.istante_utc = locale, fuso, assoluto
            dati.origine_data = "quicktime"
    if dati.data_locale is None and dati.creazione_traccia:
        momento = _momento_1904(dati.creazione_traccia)
        if momento is not None:
            dati.istante_utc = momento.strftime("%Y-%m-%dT%H:%M:%SZ")
            dati.data_locale = momento.strftime("%Y-%m-%dT%H:%M:%S")
            dati.fuso_minuti = 0
            dati.origine_data = "quicktime"
    if dati.origine_data == "apple":
        dati.origine_data = "quicktime"
    if dati.latitudine is None and dati.luogo_di_scorta:
        dati.latitudine, dati.longitudine = _iso6709(dati.luogo_di_scorta)
    return dati


PEZZO_DA_FRUGARE = 16 * 1024 * 1024


def _cerca_mvhd(file: BinaryIO, dimensione: int, dati: DatiVideo) -> None:
    for inizio in (0, max(0, dimensione - PEZZO_DA_FRUGARE)):
        file.seek(inizio)
        pezzo = file.read(PEZZO_DA_FRUGARE)
        dove = pezzo.find(b"mvhd")
        while dove >= 4:
            lunghezza = struct.unpack(">I", pezzo[dove - 4:dove])[0]
            if 100 <= lunghezza <= 200:
                inizio_atomo = inizio + dove + 4
                _leggi_mvhd(file, inizio_atomo, inizio_atomo + lunghezza - 8, dati)
                return
            dove = pezzo.find(b"mvhd", dove + 4)


def chiavi_apple(percorso: Path) -> dict[str, str]:
    trovate: dict[str, str] = {}
    try:
        dimensione = percorso.stat().st_size
        with open(percorso, "rb") as file:
            for nome, contenuto, fine in _atomi(file, 0, dimensione):
                if nome == b"moov":
                    _raccogli_chiavi(file, contenuto, fine, trovate)
    except (OSError, struct.error, RecursionError):
        return trovate
    return trovate


def _raccogli_chiavi(file: BinaryIO, inizio: int, fine: int,
                     trovate: dict[str, str]) -> None:
    for nome, contenuto, fine_atomo in _atomi(file, inizio, fine):
        if nome == b"udta":
            _raccogli_chiavi(file, contenuto, fine_atomo, trovate)
        elif nome == b"meta":
            for scarto in (0, 4):
                valori = _chiavi_e_valori(file, contenuto + scarto, fine_atomo)
                if valori:
                    for chiave, grezzo in valori.items():
                        testo = grezzo.decode("utf-8", "replace").strip("\x00 ")
                        if chiave and testo:
                            trovate.setdefault(chiave, testo)
                    break


def _leggi_moov(file: BinaryIO, inizio: int, fine: int, dati: DatiVideo) -> None:
    for nome, contenuto, fine_atomo in _atomi(file, inizio, fine):
        if nome == b"mvhd":
            _leggi_mvhd(file, contenuto, fine_atomo, dati)
        elif nome == b"trak":
            _leggi_trak(file, contenuto, fine_atomo, dati)
        elif nome in (b"meta", b"udta"):
            _leggi_meta(file, contenuto, fine_atomo, dati)
            _leggi_scorta(file, contenuto, fine_atomo, dati)


def _leggi_mvhd(file: BinaryIO, inizio: int, fine: int, dati: DatiVideo) -> None:
    grezzo = _leggi(file, inizio, fine)
    if len(grezzo) < 20:
        return
    versione = grezzo[0]
    if versione == 1 and len(grezzo) >= 32:
        creazione, _, scala, durata = struct.unpack(">QQIQ", grezzo[4:32])
    else:
        creazione, _, scala, durata = struct.unpack(">IIII", grezzo[4:20])
    if scala:
        dati.durata_ms = int(durata * 1000 / scala)
    dati.creazione_mvhd = creazione
    momento = _momento_1904(creazione)
    if momento is not None and dati.data_locale is None:
        dati.istante_utc = momento.strftime("%Y-%m-%dT%H:%M:%SZ")
        dati.data_locale = momento.strftime("%Y-%m-%dT%H:%M:%S")
        dati.fuso_minuti = 0
        dati.origine_data = "quicktime"


def _creazione(grezzo: bytes) -> int:
    if len(grezzo) >= 12 and grezzo[0] == 1:
        return struct.unpack(">Q", grezzo[4:12])[0]
    if len(grezzo) >= 8:
        return struct.unpack(">I", grezzo[4:8])[0]
    return 0


def _momento_1904(secondi: int) -> datetime | None:
    if secondi <= SCARTO_1904 + 31536000:
        return None
    try:
        return datetime(1904, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=secondi)
    except OverflowError:
        return None


def _leggi_trak(file: BinaryIO, inizio: int, fine: int, dati: DatiVideo) -> None:
    for nome, contenuto, fine_atomo in _atomi(file, inizio, fine):
        if nome == b"mdia":
            for dentro, c2, f2 in _atomi(file, contenuto, fine_atomo):
                if dentro == b"mdhd" and dati.creazione_traccia is None:
                    dati.creazione_traccia = _creazione(_leggi(file, c2, f2)) or None
            continue
        if nome != b"tkhd":
            continue
        grezzo = _leggi(file, contenuto, fine_atomo)
        if dati.creazione_traccia is None:
            dati.creazione_traccia = _creazione(grezzo) or None
        if len(grezzo) < 84:
            continue
        larghezza = struct.unpack(">I", grezzo[-8:-4])[0] >> 16
        altezza = struct.unpack(">I", grezzo[-4:])[0] >> 16
        if larghezza and altezza and larghezza * altezza > (dati.larghezza or 0) * (dati.altezza or 0):
            dati.larghezza, dati.altezza = larghezza, altezza
            dati.rotazione = _gradi_della_matrice(grezzo[-44:-8])


def _gradi_della_matrice(grezzo: bytes) -> int:
    if len(grezzo) != 36:
        return 0
    a, b, _, c, d, _, _, _, _ = struct.unpack(">9i", grezzo)
    if not (math.hypot(a, c) and math.hypot(b, d)):
        return 0
    gradi = -math.degrees(math.atan2(b / math.hypot(b, d), a / math.hypot(a, c)))
    return int(round(gradi / 90)) * 90 % 360


def rotazione(percorso: Path) -> int:
    return leggi(percorso).rotazione


def misure_raddrizzate(dati: DatiVideo) -> tuple[int | None, int | None]:
    if dati.rotazione in (90, 270):
        return dati.altezza, dati.larghezza
    return dati.larghezza, dati.altezza


def _leggi_meta(file: BinaryIO, inizio: int, fine: int, dati: DatiVideo) -> None:
    for scarto in (0, 4):
        trovati = _chiavi_e_valori(file, inizio + scarto, fine)
        if trovati:
            _usa_metadati(trovati, dati)
            return
        for nome, contenuto, fine_atomo in _atomi(file, inizio + scarto, fine):
            if nome in (b"meta", b"ilst", b"keys"):
                _leggi_meta(file, contenuto, fine_atomo, dati)
                return


def _testo_di_scorta(file: BinaryIO, inizio: int, fine: int) -> str | None:
    grezzo = _leggi(file, inizio, fine)
    for tipo, d2, f2 in _atomi(file, inizio, fine):
        if tipo == b"data":
            valore = _leggi(file, d2, f2)[8:]
            return valore.decode("utf-8", "replace").strip("\x00 ") or None
    if len(grezzo) >= 4:
        lunghezza = struct.unpack(">H", grezzo[:2])[0]
        valore = grezzo[4:4 + lunghezza] if lunghezza else grezzo[4:]
        return valore.decode("utf-8", "replace").strip("\x00 ") or None
    return None


def _leggi_scorta(file: BinaryIO, inizio: int, fine: int, dati: DatiVideo,
                  profondita: int = 0) -> None:
    if profondita > 4:
        return
    for scarto in (0, 4):
        for nome, contenuto, fine_atomo in _atomi(file, inizio + scarto, fine):
            if nome == b"\xa9day" and dati.data_di_scorta is None:
                dati.data_di_scorta = _testo_di_scorta(file, contenuto, fine_atomo)
            elif nome == b"\xa9xyz" and dati.luogo_di_scorta is None:
                dati.luogo_di_scorta = _testo_di_scorta(file, contenuto, fine_atomo)
            elif nome in (b"meta", b"ilst", b"udta"):
                _leggi_scorta(file, contenuto, fine_atomo, dati, profondita + 1)


def _usa_metadati(trovati: dict[str, bytes], dati: DatiVideo) -> None:
    def testo(chiave: str) -> str | None:
        grezzo = trovati.get(chiave)
        return grezzo.decode("utf-8", "replace").strip("\x00 ") if grezzo else None

    identificatore = testo("com.apple.quicktime.content.identifier")
    if identificatore:
        dati.identificatore_ios = identificatore

    data = testo("com.apple.quicktime.creationdate")
    dati.data_apple = data
    if data:
        locale, fuso, assoluto = _data_da_stringa(data)
        if locale:
            dati.data_locale, dati.fuso_minuti, dati.istante_utc = locale, fuso, assoluto
            dati.origine_data = "apple"

    luogo = testo("com.apple.quicktime.location.ISO6709")
    if luogo:
        dati.latitudine, dati.longitudine = _iso6709(luogo)

    marca = testo("com.apple.quicktime.make")
    if marca:
        dati.marca = marca
    modello = testo("com.apple.quicktime.model")
    if modello:
        dati.modello = modello


def primo_fotogramma_jpeg(percorso: Path) -> bytes | None:
    try:
        dimensione = percorso.stat().st_size
        with open(percorso, "rb") as file:
            posizione_dati = _trova_stbl(file, 0, dimensione)
            if posizione_dati is None:
                return None
            scarto, misura = posizione_dati
            file.seek(scarto)
            dati = file.read(min(misura, 8 * 1024 * 1024))
            return dati if dati[:3] == b"\xff\xd8\xff" else None
    except (OSError, struct.error, RecursionError):
        return None


def _trova_stbl(file: BinaryIO, inizio: int, fine: int) -> tuple[int, int] | None:
    for nome, contenuto, fine_atomo in _atomi(file, inizio, fine):
        if nome in (b"moov", b"trak", b"mdia", b"minf", b"stbl"):
            if nome == b"stbl":
                e_jpeg = False
                misura = None
                scarto = None
                for figlio, dentro, fine_dentro in _atomi(file, contenuto, fine_atomo):
                    grezzo = _leggi(file, dentro, fine_dentro)
                    if figlio == b"stsd" and len(grezzo) >= 16:
                        e_jpeg = grezzo[12:16] == b"jpeg"
                    elif figlio == b"stsz" and len(grezzo) >= 16:
                        fissa = struct.unpack(">I", grezzo[4:8])[0]
                        misura = fissa or struct.unpack(">I", grezzo[12:16])[0]
                    elif figlio == b"stco" and len(grezzo) >= 12:
                        scarto = struct.unpack(">I", grezzo[8:12])[0]
                if e_jpeg and misura and scarto:
                    return scarto, misura
                return None
            trovato = _trova_stbl(file, contenuto, fine_atomo)
            if trovato:
                return trovato
    return None


CODEC_CHE_IL_BROWSER_APRE = {"avc1", "avc3", "vp09", "av01"}


def codec_video(percorso: Path) -> str | None:
    try:
        with open(percorso, "rb") as file:
            return _cerca_codec(file, 0, percorso.stat().st_size)
    except (OSError, struct.error, RecursionError):
        return None


def _cerca_codec(file: BinaryIO, inizio: int, fine: int) -> str | None:
    for nome, contenuto, fine_atomo in _atomi(file, inizio, fine):
        if nome == b"stsd":
            grezzo = _leggi(file, contenuto, fine_atomo)
            if len(grezzo) >= 16:
                return grezzo[12:16].decode("ascii", "replace")
        if nome in (b"moov", b"trak", b"mdia", b"minf", b"stbl"):
            trovato = _cerca_codec(file, contenuto, fine_atomo)
            if trovato:
                return trovato
    return None


def il_browser_lo_apre(codec: str | None) -> bool:
    return bool(codec) and codec.lower() in CODEC_CHE_IL_BROWSER_APRE


SCALA_TEMPI = 600

@dataclass
class Campione:

    scarto: int
    misura: int
    istante_ms: int


def campioni_jpeg(percorso: Path) -> list[Campione]:
    try:
        with open(percorso, "rb") as file:
            dimensione = percorso.stat().st_size
            tabelle = _tabelle_stbl(file, 0, dimensione)
            if tabelle is None:
                return []
            return _componi_campioni(tabelle, dimensione)
    except Exception:
        return []


def _tabelle_stbl(file: BinaryIO, inizio: int, fine: int) -> dict | None:
    for nome, contenuto, fine_atomo in _atomi(file, inizio, fine):
        if nome == b"stbl":
            trovate: dict = {}
            for figlio, dentro, fine_dentro in _atomi(file, contenuto, fine_atomo):
                if figlio in (b"stsd", b"stsz", b"stco", b"co64", b"stsc", b"stts"):
                    trovate[figlio.decode()] = _leggi(file, dentro, fine_dentro)
            grezzo = trovate.get("stsd", b"")
            if len(grezzo) >= 16 and grezzo[12:16] == b"jpeg":
                return trovate
            return None
        if nome in (b"moov", b"trak", b"mdia", b"minf"):
            trovate = _tabelle_stbl(file, contenuto, fine_atomo)
            if trovate:
                return trovate
    return None


def _componi_campioni(tabelle: dict, dimensione: int | None = None) -> list[Campione]:
    tetto = CAMPIONI_MASSIMI if dimensione is None else min(CAMPIONI_MASSIMI, dimensione)
    misure = _misure(tabelle.get("stsz", b""), tetto)
    if not misure:
        return []
    scarti_chunk = _scarti(tabelle.get("stco"), tabelle.get("co64"))
    if not scarti_chunk:
        return []
    per_chunk = _quanti_per_chunk(tabelle.get("stsc", b""), len(scarti_chunk), len(misure))
    durate = _durate(tabelle.get("stts", b""), len(misure))

    campioni: list[Campione] = []
    indice = 0
    tempo = 0
    for chunk, quanti in enumerate(per_chunk[:len(scarti_chunk)]):
        posizione = scarti_chunk[chunk]
        for _ in range(quanti):
            if indice >= len(misure):
                break
            campioni.append(Campione(posizione, misure[indice], tempo))
            posizione += misure[indice]
            tempo += durate[indice]
            indice += 1
    return campioni


def _misure(grezzo: bytes, tetto: int = CAMPIONI_MASSIMI) -> list[int]:
    if len(grezzo) < 12:
        return []
    fissa, quanti = struct.unpack(">II", grezzo[4:12])
    quanti = min(quanti, tetto)
    if fissa:
        return [fissa] * quanti
    corpo = grezzo[12:12 + quanti * 4]
    return list(struct.unpack(f">{len(corpo) // 4}I", corpo))


def _scarti(stco: bytes | None, co64: bytes | None) -> list[int]:
    if stco and len(stco) >= 8:
        quanti = struct.unpack(">I", stco[4:8])[0]
        corpo = stco[8:8 + quanti * 4]
        return list(struct.unpack(f">{len(corpo) // 4}I", corpo))
    if co64 and len(co64) >= 8:
        quanti = struct.unpack(">I", co64[4:8])[0]
        corpo = co64[8:8 + quanti * 8]
        return list(struct.unpack(f">{len(corpo) // 8}Q", corpo))
    return []


def _quanti_per_chunk(stsc: bytes, quanti_chunk: int, quanti_campioni: int) -> list[int]:
    if len(stsc) < 8 or quanti_chunk == 0:
        return [1] * min(quanti_chunk, quanti_campioni)
    quante_righe = struct.unpack(">I", stsc[4:8])[0]
    righe = []
    for indice in range(quante_righe):
        inizio = 8 + indice * 12
        if inizio + 12 > len(stsc):
            break
        primo, per_blocco, _ = struct.unpack(">III", stsc[inizio:inizio + 12])
        righe.append((primo, per_blocco))
    if not righe:
        return [1] * min(quanti_chunk, quanti_campioni)

    fuori: list[int] = []
    resto = quanti_campioni
    for indice, (primo, per_blocco) in enumerate(righe):
        ultimo = righe[indice + 1][0] - 1 if indice + 1 < len(righe) else quanti_chunk
        for _ in range(max(0, min(ultimo, quanti_chunk) - primo + 1)):
            if resto <= 0:
                return fuori
            preso = min(per_blocco, resto)
            fuori.append(preso)
            resto -= preso
    return fuori


def _durate(stts: bytes, quanti_campioni: int) -> list[int]:
    if len(stts) < 8:
        return [0] * quanti_campioni
    quante_righe = struct.unpack(">I", stts[4:8])[0]
    fuori: list[int] = []
    for indice in range(quante_righe):
        inizio = 8 + indice * 8
        if inizio + 8 > len(stts) or len(fuori) >= quanti_campioni:
            break
        quanti, passo = struct.unpack(">II", stts[inizio:inizio + 8])
        quanti = min(quanti, quanti_campioni - len(fuori))
        fuori.extend([int(passo * 1000 / SCALA_TEMPI)] * quanti)
    if len(fuori) < quanti_campioni:
        fuori.extend([0] * (quanti_campioni - len(fuori)))
    return fuori[:quanti_campioni]


def leggi_campione(percorso: Path, campione: Campione) -> bytes | None:
    try:
        with open(percorso, "rb") as file:
            file.seek(campione.scarto)
            dati = file.read(min(campione.misura, MISURA_MASSIMA_CAMPIONE))
        return dati if dati[:3] == b"\xff\xd8\xff" else None
    except OSError:
        return None
