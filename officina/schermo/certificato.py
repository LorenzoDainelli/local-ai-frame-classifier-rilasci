from __future__ import annotations

import datetime
import hashlib
import socket
from dataclasses import dataclass
from pathlib import Path

ANNI = 20


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
    chiave.write_bytes(privata.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption()))
    certificato.write_bytes(firmato.public_bytes(serialization.Encoding.PEM))


def carica_o_crea(cartella: Path) -> Certificato:
    import ssl

    certificato = cartella / "fisso.pem"
    chiave = cartella / "fisso.chiave.pem"
    if not certificato.exists() or not chiave.exists():
        _crea(certificato, chiave)
    pem = certificato.read_text(encoding="ascii")
    der = ssl.PEM_cert_to_DER_cert(pem)
    return Certificato(certificato, chiave, pem, impronta_di(der))
