from __future__ import annotations

import datetime
import hashlib
import os
import socket
from dataclasses import dataclass
from pathlib import Path

from officina import registro

ANNI = 20
NUOVO = ".nuovo"


@dataclass(frozen=True)
class Certificato:
    certificato: Path
    chiave: Path
    pem: str
    impronta: str


def impronta_di(der: bytes) -> str:
    return hashlib.sha256(der).hexdigest()


def _crea(certificato: Path, chiave: Path) -> None:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    privata = ec.generate_private_key(ec.SECP256R1())
    nome = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,
                                         f"Frame Classifier {socket.gethostname()}"[:64])])
    adesso = datetime.datetime.now(datetime.timezone.utc)
    firmato = (
        x509.CertificateBuilder()
        .subject_name(nome)
        .issuer_name(nome)
        .public_key(privata.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(adesso - datetime.timedelta(days=1))
        .not_valid_after(adesso + datetime.timedelta(days=365 * ANNI))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(x509.SubjectAlternativeName([x509.DNSName("officina-fisso")]),
                       critical=False)
        .sign(privata, hashes.SHA256())
    )
    certificato.parent.mkdir(parents=True, exist_ok=True)
    _scrivi_al_sicuro(chiave, privata.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption()))
    _scrivi_al_sicuro(certificato, firmato.public_bytes(serialization.Encoding.PEM))


def _scrivi_al_sicuro(dove: Path, dati: bytes) -> None:
    provvisorio = dove.with_name(dove.name + NUOVO)
    try:
        provvisorio.write_bytes(dati)
        os.replace(provvisorio, dove)
    finally:
        provvisorio.unlink(missing_ok=True)


def _leggi(certificato: Path, chiave: Path) -> tuple[str, bytes] | None:
    import ssl

    from cryptography import x509
    from cryptography.hazmat.primitives import serialization

    try:
        pem = certificato.read_text(encoding="ascii")
        der = ssl.PEM_cert_to_DER_cert(pem)
        pubblica = x509.load_der_x509_certificate(der).public_key()
        privata = serialization.load_pem_private_key(chiave.read_bytes(), password=None)
    except (OSError, ValueError, TypeError, UnicodeDecodeError):
        return None
    formato = (serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    if privata.public_key().public_bytes(*formato) != pubblica.public_bytes(*formato):
        return None
    return pem, der


def carica_o_crea(cartella: Path) -> Certificato:
    certificato = cartella / "fisso.pem"
    chiave = cartella / "fisso.chiave.pem"
    letto = _leggi(certificato, chiave)
    if letto is None:
        if certificato.exists() or chiave.exists():
            registro.avviso("schermo.certificato_rifatto")
        _crea(certificato, chiave)
        letto = _leggi(certificato, chiave)
        if letto is None:
            raise OSError("Il certificato appena creato non si rilegge.")
    pem, der = letto
    return Certificato(certificato, chiave, pem, impronta_di(der))
