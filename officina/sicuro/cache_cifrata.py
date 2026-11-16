from __future__ import annotations

import os
import secrets
import threading
import time
import weakref
from pathlib import Path

from officina import registro

SPENTA = "spenta"
APERTA = "aperta"
CHIUSA = "chiusa"
CODA = ".sicuro"
FIRMA = b"OFCC1"
NONCE = 12
USO = "cache delle miniature"
RICONTROLLO = 2.0

_serratura = threading.Lock()
_chiave: tuple = (None, None)
_c_e: dict[str, tuple[float, bool]] = {}


def cifrato(percorso: Path) -> Path:
    return percorso.with_name(percorso.name + CODA)


def _aead():
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    return AESGCM


def cifra(chiave: bytes, nome: str, dati: bytes) -> bytes:
    numero = secrets.token_bytes(NONCE)
    return FIRMA + numero + _aead()(chiave).encrypt(numero, bytes(dati), _aad(nome))


def decifra(chiave: bytes, nome: str, blob: bytes) -> bytes | None:
    from cryptography.exceptions import InvalidTag

    if not blob.startswith(FIRMA) or len(blob) < len(FIRMA) + NONCE + 16:
        return None
    inizio = len(FIRMA)
    numero = blob[inizio:inizio + NONCE]
    try:
        return _aead()(chiave).decrypt(numero, blob[inizio + NONCE:], _aad(nome))
    except InvalidTag:
        return None


def _aad(nome: str) -> bytes:
    return b"officina-miniatura\x00" + nome.replace("\\", "/").encode("utf-8")


def _chiave_di(apertura) -> bytes:
    global _chiave
    with _serratura:
        legata, chiave = _chiave
        if legata is not None and legata() is apertura:
            return chiave
        chiave = apertura.chiave.per(USO)
        _chiave = (weakref.ref(apertura), chiave)
        return chiave


def _archivio_esiste(dove) -> bool:
    from officina.programma import archivio_sicuro

    chiave = str(dove.radice)
    adesso = time.monotonic()
    with _serratura:
        visto = _c_e.get(chiave)
    if visto is not None and (visto[1] or adesso - visto[0] < RICONTROLLO):
        return visto[1]
    try:
        c_e = archivio_sicuro.c_e(dove)
    except Exception:
        c_e = True
    with _serratura:
        _c_e[chiave] = (adesso, c_e)
    return c_e


def dimentica() -> None:
    global _chiave
    with _serratura:
        _chiave = (None, None)
        _c_e.clear()


def _vero(dove) -> bool:
    from officina.impostazioni import REALE

    return getattr(dove, "nome", None) == REALE


def stato(dove) -> tuple[str, bytes | None]:
    from officina.sicuro import servizio as modulo
    from officina.sicuro import sportello

    if not _vero(dove):
        return SPENTA, None
    if sportello.qui() is None:
        servizio = modulo.attuale()
        apertura = servizio.apertura if servizio is not None else None
        if apertura is not None:
            return APERTA, _chiave_di(apertura)
    if _archivio_esiste(dove):
        return CHIUSA, None
    return SPENTA, None


def scrivi(percorso: Path, nome: str, dati: bytes, chiave: bytes) -> Path:
    destinazione = cifrato(percorso)
    destinazione.parent.mkdir(parents=True, exist_ok=True)
    temporaneo = destinazione.with_name(
        f"{destinazione.name}.{secrets.token_hex(4)}.parziale")
    temporaneo.write_bytes(cifra(chiave, nome, dati))
    os.replace(temporaneo, destinazione)
    percorso.unlink(missing_ok=True)
    return destinazione


def leggi(percorso: Path, nome: str, chiave: bytes) -> bytes | None:
    sicuro = cifrato(percorso)
    try:
        blob = sicuro.read_bytes()
    except FileNotFoundError:
        blob = None
    except OSError:
        return None
    if blob is not None:
        dati = decifra(chiave, nome, blob)
        if dati is None:
            registro.avviso("miniature.cifrata_rovinata")
            sicuro.unlink(missing_ok=True)
        return dati
    try:
        dati = percorso.read_bytes()
    except OSError:
        return None
    scrivi(percorso, nome, dati, chiave)
    return dati


def c_e(percorso: Path) -> bool:
    return percorso.exists() or cifrato(percorso).exists()


def butta(percorso: Path) -> None:
    for uno in (percorso, cifrato(percorso)):
        try:
            uno.unlink(missing_ok=True)
        except OSError:
            pass


SOLO_MINIATURE = frozenset({".avif", ".jpg", ".jpeg", ".png", ".webp"})
OGNI = 64
RIPOSO = 0.02
_in_corso = threading.Lock()


def _da_cifrare(cartella: Path):
    try:
        sotto = sorted(cartella.iterdir())
    except OSError:
        return
    for gruppo in sotto:
        if not gruppo.is_dir() or len(gruppo.name) != 2:
            continue
        try:
            dentro = sorted(gruppo.iterdir())
        except OSError:
            continue
        for percorso in dentro:
            if percorso.suffix.lower() in SOLO_MINIATURE and percorso.is_file():
                yield percorso


def cifra_le_vecchie(archivio) -> int:
    if not _in_corso.acquire(blocking=False):
        return 0
    fatte = 0
    try:
        cartella = Path(archivio.dove.miniature)
        for percorso in _da_cifrare(cartella):
            stato_ora, chiave = stato(archivio.dove)
            if stato_ora != APERTA:
                break
            nome = percorso.relative_to(cartella).as_posix()
            try:
                dati = percorso.read_bytes()
                scrivi(percorso, nome, dati, chiave)
            except OSError:
                continue
            fatte += 1
            if fatte % OGNI == 0:
                time.sleep(RIPOSO)
    finally:
        _in_corso.release()
    if fatte:
        registro.evento("miniature.cifrate", quante=fatte)
    return fatte


def in_sottofondo(archivio) -> threading.Thread:
    def gira() -> None:
        try:
            cifra_le_vecchie(archivio)
        except Exception as guasto:
            registro.errore("miniature.cifratura_ferma", **registro.dove_si_e_rotto(guasto))

    filo = threading.Thread(target=gira, name="miniature-cifrate", daemon=True)
    filo.start()
    return filo
