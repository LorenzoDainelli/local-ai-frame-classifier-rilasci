from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path

from officina.errori import ErroreOfficina

CARTELLA = "mezzi"
PNG = ".png"
TIMBRO = ".json"
PARZIALE = ".parziale"
MARGINE = 2 * 2 ** 30
PER_PIXEL = 4


class MezzoRotto(ErroreOfficina):
    codice = "mezzo_rotto"


def cartella(dove) -> Path:
    return Path(dove.miniature) / CARTELLA


def percorsi(base: Path, miglioria_id: int) -> tuple[Path, Path]:
    numero = int(miglioria_id)
    return Path(base) / f"{numero}{PNG}", Path(base) / f"{numero}{TIMBRO}"


def timbro(impronta_originale: str, nome: str, versione: str, prima: tuple[int, int],
           dopo: tuple[int, int]) -> dict:
    return {"impronta": str(impronta_originale), "nome": str(nome),
            "versione": str(versione), "prima": [int(prima[0]), int(prima[1])],
            "dopo": [int(dopo[0]), int(dopo[1])]}


def dei_pixel(immagine) -> str:
    return hashlib.sha256(immagine.tobytes()).hexdigest()


def ci_sta(base: Path, larghezza: int, altezza: int) -> bool:
    Path(base).mkdir(parents=True, exist_ok=True)
    serve = int(larghezza) * int(altezza) * PER_PIXEL + MARGINE
    return shutil.disk_usage(base).free >= serve


def _scrivi_sicuro(percorso: Path, scrivi) -> None:
    parziale = percorso.with_name(percorso.name + PARZIALE)
    with open(parziale, "wb") as file:
        scrivi(file)
        file.flush()
        os.fsync(file.fileno())
    os.replace(parziale, percorso)


def scrivi(base: Path, miglioria_id: int, immagine, suo_timbro: dict, usato: dict,
           misura: dict) -> bool:
    from PIL import Image

    if immagine.mode != "RGB":
        return False
    png, json_ = percorsi(base, miglioria_id)
    Path(base).mkdir(parents=True, exist_ok=True)
    butta(base, miglioria_id)
    pixel = dei_pixel(immagine)
    _scrivi_sicuro(png, lambda file: immagine.save(file, format="PNG", compress_level=6))
    with Image.open(png) as riletta:
        riletta.load()
        uguale = (riletta.mode == "RGB" and riletta.size == immagine.size
                  and dei_pixel(riletta) == pixel)
    if not uguale:
        butta(base, miglioria_id)
        return False
    dati = {"timbro": suo_timbro, "pixel": pixel, "usato": usato, "misura": misura}
    testo = json.dumps(dati, sort_keys=True).encode("utf-8")
    _scrivi_sicuro(json_, lambda file: file.write(testo))
    return True


def c_e(base: Path, miglioria_id: int, impronta_originale: str, versione: str) -> bool:
    png, json_ = percorsi(base, miglioria_id)
    if not (png.is_file() and json_.is_file()):
        return False
    try:
        dati = json.loads(json_.read_text(encoding="utf-8"))
        suo = dati["timbro"]
        return suo["impronta"] == impronta_originale and suo["versione"] == versione
    except (OSError, ValueError, KeyError, TypeError):
        return False


def leggi(base: Path, miglioria_id: int, suo_timbro: dict):
    from PIL import Image

    png, json_ = percorsi(base, miglioria_id)
    try:
        dati = json.loads(json_.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(dati, dict) or dati.get("timbro") != suo_timbro:
        return None
    try:
        with Image.open(png) as aperta:
            aperta.load()
            immagine = aperta.copy()
    except (OSError, ValueError):
        return None
    dopo = tuple(suo_timbro["dopo"])
    if immagine.mode != "RGB" or immagine.size != dopo:
        return None
    if dei_pixel(immagine) != dati.get("pixel"):
        return None
    usato = dati.get("usato")
    misura = dati.get("misura")
    if not isinstance(usato, dict) or not isinstance(misura, dict):
        return None
    return immagine, usato, misura


def butta(base: Path, miglioria_id: int) -> None:
    for percorso in percorsi(base, miglioria_id):
        for file in (percorso, percorso.with_name(percorso.name + PARZIALE)):
            try:
                file.unlink()
            except FileNotFoundError:
                pass


def pulisci(base: Path, tenuti: set[int]) -> int:
    base = Path(base)
    if not base.is_dir():
        return 0
    tolti = 0
    for file in base.iterdir():
        numero = file.name.split(".", 1)[0]
        if not file.is_file() or (numero.isdecimal() and int(numero) in tenuti):
            continue
        file.unlink()
        tolti += 1
    return tolti


__all__ = ["CARTELLA", "MezzoRotto", "butta", "c_e", "cartella", "ci_sta", "dei_pixel",
           "leggi", "percorsi", "pulisci", "scrivi", "timbro"]
