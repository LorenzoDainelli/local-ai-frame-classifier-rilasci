from __future__ import annotations

import io
import json
import random
import struct
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from PIL import Image

from officina import registro
from officina.importazione import impronta as impronte_file
from officina.immagini import lettura
from officina.finto import contenitore_video, immagini

MODELLI = ["iPhone 13", "iPhone 14 Pro", "iPhone 11"]
MISURE_FOTO = [(4032, 3024), (3024, 4032), (2048, 1536), (1600, 1200)]
MISURE_SCHERMATE = [(1170, 2532), (1284, 2778), (1179, 2556), (1920, 1080)]


TEMI_FINTI = "temi-finti.json"


@dataclass
class Rapporto:
    cartella: Path
    foto: int = 0
    coppie_live: int = 0
    video: int = 0
    schermate: int = 0
    senza_data: int = 0
    doppioni: int = 0
    rotti: int = 0
    byte: int = 0
    formato_foto: str = "HEIF"
    file_scritti: list[Path] = field(default_factory=list)
    temi: dict[str, str] = field(default_factory=dict)

    @property
    def scatti_attesi(self) -> int:
        return self.foto + self.coppie_live + self.video + self.schermate + self.senza_data

    @property
    def file_attesi(self) -> int:
        return len(self.file_scritti)


def nota_apple(identificatore: str) -> bytes:
    testo = identificatore.encode("ascii") + b"\x00"
    intestazione = b"Apple iOS\x00\x00\x01MM"
    scarto = len(intestazione) + 2 + 12 + 4
    voce = struct.pack(">HHI", 0x0011, 2, len(testo)) + struct.pack(">I", scarto)
    return intestazione + struct.pack(">H", 1) + voce + struct.pack(">I", 0) + testo


def _in_gradi(valore: float) -> tuple:
    valore = abs(valore)
    gradi = int(valore)
    minuti = int((valore - gradi) * 60)
    secondi = round((valore - gradi - minuti / 60) * 3600, 2)
    return (gradi, minuti, secondi)


def costruisci_exif(quando: datetime, fuso_minuti: int, modello: str,
                    identificatore: str | None, luogo: tuple[float, float] | None,
                    orientamento: int = 1) -> bytes:
    exif = Image.Exif()
    exif[0x010F] = "Apple"
    exif[0x0110] = modello
    exif[0x0112] = orientamento
    esteso = exif.get_ifd(0x8769)
    esteso[0x9003] = quando.strftime("%Y:%m:%d %H:%M:%S")
    segno = "+" if fuso_minuti >= 0 else "-"
    esteso[0x9011] = f"{segno}{abs(fuso_minuti) // 60:02d}:{abs(fuso_minuti) % 60:02d}"
    if identificatore:
        esteso[0x927C] = nota_apple(identificatore)
    if luogo:
        gps = exif.get_ifd(0x8825)
        latitudine, longitudine = luogo
        gps[1] = "N" if latitudine >= 0 else "S"
        gps[2] = _in_gradi(latitudine)
        gps[3] = "E" if longitudine >= 0 else "W"
        gps[4] = _in_gradi(longitudine)
    return exif.tobytes()


def piano(quanti: int, caso: random.Random) -> list[str]:
    raffiche = max(1, quanti // 25)
    live = max(1, round(quanti * 0.22))
    video = max(1, round(quanti * 0.07))
    schermate = max(1, round(quanti * 0.07))
    senza_data = max(1, round(quanti * 0.05))
    foto = max(0, quanti - raffiche * 5 - live - video - schermate - senza_data)

    elenco = (["raffica"] * raffiche + ["live"] * live + ["video"] * video
              + ["schermata"] * schermate + ["senza_data"] * senza_data
              + ["foto"] * foto)
    caso.shuffle(elenco)
    return elenco


def genera(cartella: Path, quanti: int = 120, seme: int = 1,
           con_rotti: bool = True, leggero: bool = False) -> Rapporto:
    caso = random.Random(seme)
    cartella = Path(cartella)
    cartella.mkdir(parents=True, exist_ok=True)
    rapporto = Rapporto(cartella=cartella)

    formato_foto = "HEIF" if lettura.SA_LEGGERE_HEIC else "JPEG"
    coda_foto = ".HEIC" if lettura.SA_LEGGERE_HEIC else ".JPG"
    rapporto.formato_foto = formato_foto

    misure_foto = [(800, 600), (600, 800)] if leggero else MISURE_FOTO
    misure_schermate = [(640, 1136), (1280, 720)] if leggero else MISURE_SCHERMATE
    misura_video = (160, 120) if leggero else (640, 480)

    luoghi = [(43.7696, 11.2558), (53.3498, -6.2603), (45.4642, 9.1900)]
    temi = list(immagini.TEMI)
    momento = datetime(2021, 3, 14, 10, 5, 0)

    def prossimo_momento(salto_grande: bool = False) -> datetime:
        nonlocal momento
        if salto_grande:
            momento += timedelta(days=caso.randint(3, 40), hours=caso.randint(0, 10))
        else:
            momento += timedelta(minutes=caso.randint(2, 400))
        return momento

    def salva(percorso: Path, dati: bytes, tema: str | None = None) -> None:
        percorso.parent.mkdir(parents=True, exist_ok=True)
        percorso.write_bytes(dati)
        rapporto.file_scritti.append(percorso)
        rapporto.byte += len(dati)
        if tema:
            rapporto.temi[impronte_file.dei_byte(dati)] = tema

    def cartella_del(quando: datetime) -> Path:
        return cartella / f"{quando:%Y}" / f"{quando:%m}"

    numero = 1000
    primi_file_foto: list[Path] = []

    for tipo in piano(quanti, caso):
        numero += 1
        tema = caso.choice(temi)
        quando = prossimo_momento(salto_grande=caso.random() < 0.35)
        fuso = caso.choice([60, 120, 0])
        modello = caso.choice(MODELLI)
        luogo = caso.choice(luoghi) if caso.random() < 0.8 else None

        if tipo == "raffica":
            for indice in range(5):
                numero += 1
                istante = quando + timedelta(seconds=indice * 2)
                immagine = immagini.disegna(tema, numero, caso.choice(misure_foto[:2]))
                appoggio = io.BytesIO()
                immagine.save(appoggio, formato_foto, quality=72,
                              exif=costruisci_exif(istante, fuso, modello, None, luogo))
                salva(cartella_del(istante) / f"IMG_{numero}{coda_foto}",
                      appoggio.getvalue(), tema)
                rapporto.foto += 1
            continue

        if tipo == "live":
            identificatore = f"{caso.getrandbits(48):012X}-FINTO-{numero}"
            misura = caso.choice(misure_foto[:2])
            immagine = immagini.disegna(tema, numero, misura, con_marchio=caso.random() < 0.3)
            appoggio = io.BytesIO()
            immagine.save(appoggio, formato_foto, quality=74,
                          exif=costruisci_exif(quando, fuso, modello, identificatore, luogo))
            base = cartella_del(quando) / f"IMG_{numero}"
            salva(base.with_suffix(coda_foto), appoggio.getvalue(), tema)
            primi_file_foto.append(base.with_suffix(coda_foto))

            fotogrammi = immagini.fotogrammi_video(tema, numero, 45, misura_video)
            contenitore_video.scrivi(base.with_suffix(".MOV"), fotogrammi,
                                     misura_video[0], misura_video[1], 30,
                                     identificatore, quando, fuso, modello)
            rapporto.file_scritti.append(base.with_suffix(".MOV"))
            rapporto.byte += base.with_suffix(".MOV").stat().st_size
            rapporto.coppie_live += 1
            continue

        if tipo == "video":
            secondi = caso.randint(8, 35)
            fermo = rapporto.video == 0
            fotogrammi = immagini.fotogrammi_video(tema, numero, secondi * 4,
                                                   misura_video, fermo=fermo)
            percorso = cartella_del(quando) / f"IMG_{numero}.MOV"
            contenitore_video.scrivi(percorso, fotogrammi,
                                     misura_video[0], misura_video[1], 4,
                                     f"{caso.getrandbits(48):012X}-VIDEO-{numero}",
                                     quando, fuso, modello)
            rapporto.file_scritti.append(percorso)
            rapporto.byte += percorso.stat().st_size
            rapporto.temi[impronte_file.del_file(percorso)] = tema
            rapporto.video += 1
            continue

        if tipo == "schermata":
            misura = caso.choice(misure_schermate)
            immagine = immagini.disegna("tema_e", numero, misura)
            appoggio = io.BytesIO()
            immagine.save(appoggio, "PNG")
            salva(cartella / "Schermate" / f"Schermata_{numero}.png",
                  appoggio.getvalue(), "schermata")
            rapporto.schermate += 1
            continue

        if tipo == "senza_data":
            immagine = immagini.disegna(tema, numero, misure_foto[0])
            appoggio = io.BytesIO()
            immagine.save(appoggio, "JPEG", quality=82)
            salva(cartella_del(quando) / f"IMG_{numero}.JPG", appoggio.getvalue(), tema)
            rapporto.senza_data += 1
            continue

        misura = caso.choice(misure_foto)
        orientamento = caso.choice([1, 1, 1, 6, 8])
        immagine = immagini.disegna(tema, numero, misura,
                                    con_marchio=caso.random() < 0.25)
        appoggio = io.BytesIO()
        immagine.save(appoggio, formato_foto, quality=76,
                      exif=costruisci_exif(quando, fuso, modello, None, luogo, orientamento))
        percorso = cartella_del(quando) / f"IMG_{numero}{coda_foto}"
        salva(percorso, appoggio.getvalue(), tema)
        primi_file_foto.append(percorso)
        rapporto.foto += 1

    for originale in primi_file_foto[:max(2, len(primi_file_foto) // 25)]:
        copia = cartella / "Copie" / originale.name
        copia.parent.mkdir(parents=True, exist_ok=True)
        copia.write_bytes(originale.read_bytes())
        rapporto.file_scritti.append(copia)
        rapporto.doppioni += 1

    if con_rotti:
        rotti = cartella / "Da controllare"
        rotti.mkdir(parents=True, exist_ok=True)

        troncata = io.BytesIO()
        immagini.disegna("tema_b", 999, (400, 300)).save(troncata, "JPEG", quality=80)
        salva(rotti / "IMG_troncata.jpg", troncata.getvalue()[: len(troncata.getvalue()) // 3])

        salva(rotti / "IMG_bugiarda.jpg",
              "Questo file si chiama .jpg ma è testo.\n".encode("utf-8"))

        salva(rotti / "IMG_vuota.heic", b"")
        rapporto.rotti = 3

    (cartella / TEMI_FINTI).write_text(
        json.dumps({"scene": rapporto.temi}, indent=1), encoding="utf-8")

    registro.evento("finto.generato", file=len(rapporto.file_scritti),
                    scatti=rapporto.scatti_attesi)
    return rapporto
