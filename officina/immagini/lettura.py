from __future__ import annotations

import contextlib
import functools
import threading
from pathlib import Path
from typing import Iterator

from PIL import Image, ImageOps, UnidentifiedImageError

from officina import registro
from officina.errori import FileNonLeggibile
from officina.sicuro.dall_archivio import DallArchivio


SA_LEGGERE_HEIC = False
try:  # pragma: no cover - dipende da cosa e' installato sulla macchina
    import pillow_heif

    pillow_heif.register_heif_opener()
    SA_LEGGERE_HEIC = True
except ImportError:
    pass


ESTENSIONI_IMMAGINE = {
    ".heic", ".heif", ".jpg", ".jpeg", ".png", ".tif", ".tiff",
    ".webp", ".avif", ".bmp", ".gif",
}
ESTENSIONI_VIDEO = {".mov", ".mp4", ".m4v", ".avi", ".mkv", ".3gp", ".webm"}

FORMATI_AMMESSI = ("JPEG", "PNG", "TIFF", "WEBP", "GIF", "BMP", "HEIF", "AVIF")
FORMATI_A_BLOCCHI = ("JPEG", "MPO")

PESO_MASSIMO_FILE = 1024 * 1024 * 1024
PIXEL_PNG_DA_DECODIFICARE = 16_000_000

ORIENTAMENTO_EXIF = 0x0112

PIXEL_GRANDI = 40_000_000

UNA_GRANDE_ALLA_VOLTA = threading.Semaphore(1)


@functools.cache
def formati_aperti() -> tuple[str, ...]:
    Image.init()
    return tuple(nome for nome in FORMATI_AMMESSI if nome in Image.OPEN)


def genere_dal_nome(percorso: Path) -> str | None:
    suffisso = percorso.suffix.lower()
    if suffisso in ESTENSIONI_IMMAGINE:
        return "immagine"
    if suffisso in ESTENSIONI_VIDEO:
        return "video"
    return None


def intestazione(percorso: Path) -> Image.Image:
    try:
        peso = percorso.stat().st_size
    except OSError as errore:
        raise FileNonLeggibile(
            f"Non riesco ad aprire «{percorso.name}»: {errore.strerror or errore}",
            codice="permesso_negato",
        ) from errore

    if not peso:
        raise FileNonLeggibile(
            f"«{percorso.name}» è vuoto: zero byte.", codice="vuoto"
        )
    if peso > PESO_MASSIMO_FILE:
        raise FileNonLeggibile(
            f"«{percorso.name}» pesa più di 1 GB: è troppo grande per leggerlo "
            "come fotografia. Il file non è stato toccato.",
            codice="file_non_leggibile",
        )

    sorgente = percorso.apri() if isinstance(percorso, DallArchivio) else percorso
    try:
        return Image.open(sorgente, formats=formati_aperti())
    except UnidentifiedImageError as errore:
        raise FileNonLeggibile(
            f"«{percorso.name}» non è un'immagine: dentro c'è qualcos'altro, "
            "anche se il nome dice di sì.",
            codice="estensione_bugiarda",
        ) from errore
    except Image.DecompressionBombError as errore:
        raise FileNonLeggibile(
            f"«{percorso.name}» ha un numero di punti così alto che aprirlo "
            "riempirebbe la memoria del computer. Il file non è stato toccato.",
            codice="file_non_leggibile",
        ) from errore
    except OSError as errore:
        if errore.errno is not None:
            raise FileNonLeggibile(
                f"Non riesco ad aprire «{percorso.name}»: {errore.strerror or errore}",
                codice="permesso_negato",
            ) from errore
        registro.avviso("immagine_non_leggibile",
                        **registro.dove_si_e_rotto(errore))
        raise FileNonLeggibile(
            f"«{percorso.name}» si interrompe a metà: il file è rovinato o "
            "è stato copiato male.",
            codice="corrotto",
        ) from errore
    except Exception as errore:
        registro.avviso("immagine_non_leggibile",
                        **registro.dove_si_e_rotto(errore))
        raise FileNonLeggibile(
            f"«{percorso.name}» si interrompe a metà: il file è rovinato o "
            "è stato copiato male.",
            codice="corrotto",
        ) from errore


def _rovinato(percorso: Path, errore: BaseException) -> FileNonLeggibile:
    registro.avviso("immagine_non_leggibile",
                    **registro.dove_si_e_rotto(errore))
    return FileNonLeggibile(
        f"«{percorso.name}» si interrompe a metà: il file è rovinato o "
        "è stato copiato male.",
        codice="corrotto",
    )


def _senza_memoria(percorso: Path) -> FileNonLeggibile:
    return FileNonLeggibile(
        f"«{percorso.name}» ha troppi punti per la memoria del computer: non "
        "riesco ad aprirla. Il file non è stato toccato.",
        codice="file_non_leggibile",
    )


def controlla_fino_in_fondo(immagine: Image.Image, percorso: Path) -> None:
    try:
        if immagine.format in FORMATI_A_BLOCCHI:
            immagine.draft("RGB", (1, 1))
            immagine.load()
        elif (immagine.format == "PNG"
              and immagine.width * immagine.height > PIXEL_PNG_DA_DECODIFICARE):
            immagine.verify()
        else:
            immagine.load()
    except MemoryError as errore:
        raise _senza_memoria(percorso) from errore
    except Exception as errore:
        raise _rovinato(percorso, errore) from errore


def senza_exif_pesante(immagine: Image.Image) -> bool:
    return (immagine.format == "PNG" and "exif" not in immagine.info
            and immagine.width * immagine.height > PIXEL_PNG_DA_DECODIFICARE)


@contextlib.contextmanager
def _a_turno_se_grande(immagine: Image.Image) -> Iterator[None]:
    if immagine.width * immagine.height > PIXEL_GRANDI:
        with UNA_GRANDE_ALLA_VOLTA:
            yield
    else:
        yield


def _carica(immagine: Image.Image, percorso: Path, lato_massimo: int | None) -> Image.Image:
    try:
        if lato_massimo and immagine.format in FORMATI_A_BLOCCHI:
            immagine.draft("RGB", (lato_massimo * 2, lato_massimo * 2))
        immagine.load()
        return immagine
    except MemoryError as errore:
        immagine.close()
        raise _senza_memoria(percorso) from errore
    except Exception as errore:
        immagine.close()
        raise _rovinato(percorso, errore) from errore


def apri(percorso: Path, lato_massimo: int | None = None) -> Image.Image:
    immagine = intestazione(percorso)
    with _a_turno_se_grande(immagine):
        return _carica(immagine, percorso, lato_massimo)


def copia_di_lavoro(percorso: Path, lato_massimo: int | None = None) -> Image.Image:
    immagine = intestazione(percorso)
    with _a_turno_se_grande(immagine):
        immagine = _carica(immagine, percorso, lato_massimo)
        try:
            orientamento = immagine.getexif().get(ORIENTAMENTO_EXIF, 1)
        except Exception:
            orientamento = 1
        if orientamento in (2, 3, 4, 5, 6, 7, 8):
            raddrizzata = ImageOps.exif_transpose(immagine)
            immagine.close()
            immagine = raddrizzata
        if immagine.mode not in ("RGB", "L"):
            immagine = immagine.convert("RGB")
        if lato_massimo and max(immagine.size) > lato_massimo:
            immagine.thumbnail((lato_massimo, lato_massimo), Image.Resampling.LANCZOS)
        return immagine


def misure_raddrizzate(larghezza: int, altezza: int, orientamento: int | None) -> tuple[int, int]:
    if orientamento in (5, 6, 7, 8):
        return altezza, larghezza
    return larghezza, altezza
