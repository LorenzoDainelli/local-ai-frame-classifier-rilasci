from __future__ import annotations

import base64
import hashlib
import hmac
import os

CHI_PORTATILE = b"portatile"
CHI_FISSO = b"fisso"


def prova(chiave: bytes, chi: bytes, impronta: str) -> str:
    firma = hmac.new(chiave, chi + b"|" + impronta.encode("ascii"), hashlib.sha256)
    return firma.hexdigest()


def uguali(una: str, altra: str) -> bool:
    return hmac.compare_digest(una.encode(), altra.encode())


def _chiave_del_gettone(chiave: bytes) -> bytes:
    return hashlib.sha256(b"gettone|" + chiave).digest()


def chiudi_il_gettone(chiave: bytes, gettone: str) -> str:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    nonce = os.urandom(12)
    chiuso = AESGCM(_chiave_del_gettone(chiave)).encrypt(nonce, gettone.encode(), None)
    return base64.b64encode(nonce + chiuso).decode("ascii")


def apri_il_gettone(chiave: bytes, chiuso: str) -> str:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    grezzo = base64.b64decode(chiuso)
    return AESGCM(_chiave_del_gettone(chiave)).decrypt(grezzo[:12], grezzo[12:], None).decode()


def impronta_del_gettone(gettone: str) -> str:
    return hashlib.sha256(gettone.encode()).hexdigest()


def in_base64(dati: bytes) -> str:
    return base64.b64encode(dati).decode("ascii")


def da_base64(testo: str) -> bytes:
    return base64.b64decode(testo.encode("ascii"), validate=True)
