from __future__ import annotations

import hashlib
import io
import json
import os
import secrets
import shutil
import struct
from pathlib import Path

from officina.errori import ErroreOfficina

CARTELLA = "mezzi"
PNG = ".png"
TIMBRO = ".json"
CIFRATO = ".sicuro"
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


def cifrato(base: Path, miglioria_id: int) -> Path:
    return Path(base) / f"{int(miglioria_id)}{CIFRATO}"


def chiave_nuova() -> bytes:
    return secrets.token_bytes(32)


def _cifra(chiave: bytes, miglioria_id: int, dati: dict, png: bytes) -> bytes:
    from officina.sicuro.chiavi import _aead

    testo = json.dumps(dati, sort_keys=True).encode("utf-8")
    chiaro = struct.pack(">I", len(testo)) + testo + png
    numero = secrets.token_bytes(12)
    return numero + _aead()(chiave).encrypt(numero, chiaro, str(int(miglioria_id)).encode())


def _decifra(chiave: bytes, miglioria_id: int, cifrati: bytes):
    from cryptography.exceptions import InvalidTag

    from officina.sicuro.chiavi import _aead

    try:
        chiaro = _aead()(chiave).decrypt(cifrati[:12], cifrati[12:],
                                         str(int(miglioria_id)).encode())
        lunga = struct.unpack(">I", chiaro[:4])[0]
        dati = json.loads(chiaro[4:4 + lunga].decode("utf-8"))
    except (InvalidTag, ValueError, struct.error, UnicodeDecodeError):
        return None
    if not isinstance(dati, dict):
        return None
    return dati, chiaro[4 + lunga:]


def _carica(base: Path, miglioria_id: int, chiave: bytes | None):
    if chiave is None:
        png, json_ = percorsi(base, miglioria_id)
        try:
            dati = json.loads(json_.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return (dati, png) if isinstance(dati, dict) else None
    try:
        cifrati = cifrato(base, miglioria_id).read_bytes()
    except OSError:
        return None
    letto = _decifra(chiave, miglioria_id, cifrati)
    if letto is None:
        return None
    dati, png = letto
    return dati, io.BytesIO(png)


def _pixel_del_png(sorgente, immagine) -> bool:
    from PIL import Image

    with Image.open(sorgente) as riletta:
        riletta.load()
        return (riletta.mode == "RGB" and riletta.size == immagine.size
                and dei_pixel(riletta) == dei_pixel(immagine))


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


def _scrivi_cifrato(base: Path, miglioria_id: int, immagine, dati: dict,
                    chiave: bytes) -> bool:
    memoria = io.BytesIO()
    immagine.save(memoria, format="PNG", compress_level=6)
    cifrati = _cifra(chiave, miglioria_id, dati, memoria.getvalue())
    del memoria
    dove = cifrato(base, miglioria_id)
    _scrivi_sicuro(dove, lambda file: file.write(cifrati))
    letto = _carica(base, miglioria_id, chiave)
    if letto is None or letto[0] != dati or not _pixel_del_png(letto[1], immagine):
        butta(base, miglioria_id)
        return False
    return True


def scrivi(base: Path, miglioria_id: int, immagine, suo_timbro: dict, usato: dict,
           misura: dict, chiave: bytes | None = None) -> bool:
    if immagine.mode != "RGB":
        return False
    png, json_ = percorsi(base, miglioria_id)
    Path(base).mkdir(parents=True, exist_ok=True)
    butta(base, miglioria_id)
    pixel = dei_pixel(immagine)
    dati = {"timbro": suo_timbro, "pixel": pixel, "usato": usato, "misura": misura}
    dati = json.loads(json.dumps(dati, sort_keys=True))
    if chiave is not None:
        return _scrivi_cifrato(base, miglioria_id, immagine, dati, chiave)
    _scrivi_sicuro(png, lambda file: immagine.save(file, format="PNG", compress_level=6))
    if not _pixel_del_png(png, immagine):
        butta(base, miglioria_id)
        return False
    testo = json.dumps(dati, sort_keys=True).encode("utf-8")
    _scrivi_sicuro(json_, lambda file: file.write(testo))
    return True


def c_e(base: Path, miglioria_id: int, impronta_originale: str, versione: str,
        chiave: bytes | None = None) -> bool:
    if chiave is None and not percorsi(base, miglioria_id)[0].is_file():
        return False
    letto = _carica(base, miglioria_id, chiave)
    if letto is None:
        return False
    try:
        suo = letto[0]["timbro"]
        return suo["impronta"] == impronta_originale and suo["versione"] == versione
    except (OSError, ValueError, KeyError, TypeError):
        return False


def leggi(base: Path, miglioria_id: int, suo_timbro: dict, chiave: bytes | None = None):
    from PIL import Image

    letto = _carica(base, miglioria_id, chiave)
    if letto is None:
        return None
    dati, png = letto
    if dati.get("timbro") != json.loads(json.dumps(suo_timbro)):
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
    for percorso in (*percorsi(base, miglioria_id), cifrato(base, miglioria_id)):
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


def butta_i_cifrati(base: Path) -> int:
    base = Path(base)
    if not base.is_dir():
        return 0
    tolti = 0
    for file in base.iterdir():
        if file.is_file() and (file.name.endswith(CIFRATO)
                               or file.name.endswith(CIFRATO + PARZIALE)):
            file.unlink()
            tolti += 1
    return tolti


__all__ = ["CARTELLA", "CIFRATO", "MezzoRotto", "butta", "butta_i_cifrati", "c_e",
           "cartella", "chiave_nuova", "cifrato", "ci_sta", "dei_pixel", "leggi",
           "percorsi", "pulisci", "scrivi", "timbro"]
