from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from officina import registro
from officina.errori import FileNonLeggibile


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


def genere_dal_nome(percorso: Path) -> str | None:
    suffisso = percorso.suffix.lower()
    if suffisso in ESTENSIONI_IMMAGINE:
        return "immagine"
    if suffisso in ESTENSIONI_VIDEO:
        return "video"
    return None


def apri(percorso: Path) -> Image.Image:
    try:
        dati = percorso.read_bytes()
    except OSError as errore:
        raise FileNonLeggibile(
            f"Non riesco ad aprire «{percorso.name}»: {errore.strerror or errore}",
            codice="permesso_negato",
        ) from errore

    import io

    if not dati:
        raise FileNonLeggibile(
            f"«{percorso.name}» è vuoto: zero byte.", codice="vuoto"
        )

    try:
        immagine = Image.open(io.BytesIO(dati))
        immagine.load()
        return immagine
    except UnidentifiedImageError as errore:
        raise FileNonLeggibile(
            f"«{percorso.name}» non è un'immagine: dentro c'è qualcos'altro, "
            "anche se il nome dice di sì.",
            codice="estensione_bugiarda",
        ) from errore
    except Exception as errore:
        registro.avviso("immagine_non_leggibile",
                        **registro.dove_si_e_rotto(errore))
        raise FileNonLeggibile(
            f"«{percorso.name}» si interrompe a metà: il file è rovinato o "
            "è stato copiato male.",
            codice="corrotto",
        ) from errore


def copia_di_lavoro(percorso: Path, lato_massimo: int | None = None) -> Image.Image:
    immagine = apri(percorso)
    immagine = ImageOps.exif_transpose(immagine)
    if immagine.mode not in ("RGB", "L"):
        immagine = immagine.convert("RGB")
    if lato_massimo and max(immagine.size) > lato_massimo:
        immagine.thumbnail((lato_massimo, lato_massimo), Image.Resampling.LANCZOS)
    return immagine


def misure_raddrizzate(larghezza: int, altezza: int, orientamento: int | None) -> tuple[int, int]:
    if orientamento in (5, 6, 7, 8):
        return altezza, larghezza
    return larghezza, altezza
