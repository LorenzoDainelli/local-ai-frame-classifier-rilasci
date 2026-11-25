from __future__ import annotations

import json
import os
import secrets
import time
from pathlib import Path

from officina import forziere, registro
from officina.errori import ErroreOfficina

NOME_DEL_FILE = "chiavi.cifrate"
FIRMA = b"OFFICINA-CHIAVI\x00"
VERSIONE = 1
ACCOMPAGNAMENTO = b"officina-chiavi-1"
MASSIME = 100
NOME_LUNGO = 80
TESTO_LUNGO = 20000


class ScritteConUnaltraPassword(ErroreOfficina):
    pass


def file_delle_chiavi(cartella: Path) -> Path:
    return Path(cartella) / NOME_DEL_FILE


def ci_sono(cartella: Path) -> bool:
    return file_delle_chiavi(cartella).exists()


def leggi(cartella: Path, password: str) -> list[dict]:
    file = file_delle_chiavi(cartella)
    if not file.exists():
        return []
    grezzo = file.read_bytes()
    if not grezzo.startswith(FIRMA):
        raise ErroreOfficina("Il file delle chiavi non è di questo programma.")
    resto = grezzo[len(FIRMA):]
    quanto = int.from_bytes(resto[:4], "big")
    testa = json.loads(resto[4:4 + quanto].decode("utf-8"))
    if testa.get("versione") != VERSIONE:
        raise ErroreOfficina(
            "Le chiavi sono state scritte da una versione più nuova del programma.")
    chiuso = resto[4 + quanto:]
    AESGCM = forziere._aead()
    chiave = forziere._chiave(password, bytes.fromhex(testa["sale"]),
                              testa["n"], testa["r"], testa["p"])
    try:
        aperto = AESGCM(chiave).decrypt(bytes.fromhex(testa["nonce"]), chiuso,
                                        ACCOMPAGNAMENTO)
    except Exception as errore:
        raise ScritteConUnaltraPassword(
            "Le chiavi sono chiuse con un'altra password, quella che il "
            "forziere aveva prima.", codice="chiavi_altra_password") from errore
    voci = json.loads(aperto.decode("utf-8"))
    return [{"nome": str(v["nome"]), "testo": str(v["testo"]),
             "quando": str(v.get("quando", ""))} for v in voci]


def scrivi(cartella: Path, password: str, voci: list[dict]) -> None:
    forziere._password_utile(password)
    AESGCM = forziere._aead()
    sale = secrets.token_bytes(forziere.SALE)
    nonce = secrets.token_bytes(12)
    chiave = forziere._chiave(password, sale, forziere.COSTO, forziere.BLOCCO_SCRYPT,
                              forziere.PARALLELO)
    corpo = json.dumps(voci, ensure_ascii=False).encode("utf-8")
    chiuso = AESGCM(chiave).encrypt(nonce, corpo, ACCOMPAGNAMENTO)
    testa = json.dumps({
        "versione": VERSIONE, "kdf": "scrypt",
        "n": forziere.COSTO, "r": forziere.BLOCCO_SCRYPT, "p": forziere.PARALLELO,
        "sale": sale.hex(), "nonce": nonce.hex(), "cifra": "AES-256-GCM",
    }).encode("utf-8")
    file = file_delle_chiavi(cartella)
    provvisorio = file.with_name(file.name + ".nuovo")
    with open(provvisorio, "wb") as fuori:
        fuori.write(FIRMA + len(testa).to_bytes(4, "big") + testa + chiuso)
        fuori.flush()
        os.fsync(fuori.fileno())
    os.replace(provvisorio, file)
    if leggi(cartella, password) != voci:
        raise ErroreOfficina("Le chiavi non si rileggono uguali. Non ho cambiato niente.")


def _pulisci(nome: str, testo: str) -> tuple[str, str]:
    nome = " ".join((nome or "").split())
    testo = (testo or "").replace("\r\n", "\n").strip("\n")
    if not nome:
        raise ErroreOfficina("Dai un nome alla chiave, per riconoscerla.")
    if not testo.strip():
        raise ErroreOfficina("Incolla la chiave nel riquadro grande.")
    if len(nome) > NOME_LUNGO:
        raise ErroreOfficina(f"Il nome può essere lungo al massimo {NOME_LUNGO} caratteri.")
    if len(testo) > TESTO_LUNGO:
        raise ErroreOfficina("La chiave è troppo lunga per essere una chiave.")
    return nome, testo


def aggiungi(cartella: Path, password: str, nome: str, testo: str) -> list[dict]:
    nome, testo = _pulisci(nome, testo)
    voci = leggi(cartella, password)
    if len(voci) >= MASSIME:
        raise ErroreOfficina(f"Ci sono già {MASSIME} chiavi: togline qualcuna prima.")
    if any(v["nome"] == nome for v in voci):
        raise ErroreOfficina("C'è già una chiave con questo nome. Scegline un altro.")
    voci.append({"nome": nome, "testo": testo,
                 "quando": time.strftime("%d/%m/%Y")})
    scrivi(cartella, password, voci)
    registro.evento("chiavi.aggiunta", quante=len(voci))
    return voci


def togli(cartella: Path, password: str, nome: str) -> list[dict]:
    voci = leggi(cartella, password)
    rimaste = [v for v in voci if v["nome"] != nome]
    if len(rimaste) == len(voci):
        raise ErroreOfficina("Questa chiave non c'è più.")
    scrivi(cartella, password, rimaste)
    registro.evento("chiavi.tolta", quante=len(rimaste))
    return rimaste


def rinnova(cartella: Path, vecchia: str, nuova: str) -> list[dict]:
    try:
        voci = leggi(cartella, vecchia)
    except ScritteConUnaltraPassword as errore:
        raise ErroreOfficina(
            "Neanche questa password apre le chiavi. Non ho cambiato niente.") from errore
    scrivi(cartella, nuova, voci)
    registro.evento("chiavi.rinnovate", quante=len(voci))
    return voci
