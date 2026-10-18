from __future__ import annotations

import hashlib
import json
import secrets
import time
from pathlib import Path

from officina.errori import ErroreOfficina, PasswordSbagliata
from officina.sicuro.disco import scrivi_tutto


VERSIONE = 1
TIPO = "officina-archivio-sicuro-chiave"
FILE = "chiave.json"
RISERVA = "chiave.riserva.json"

LUNGHEZZA = 32
NOME = 16
SALE = 16
NONCE = 12
COSTO = 2 ** 17
COSTO_LENTO = 2 ** 18
COSTI_AMMESSI = (2 ** 17, 2 ** 18)
BLOCCO_SCRYPT = 8
PARALLELO = 1
SECONDI = 0.6
MINIMO = 12


class ChiaveRovinata(ErroreOfficina):
    codice = "chiave_rovinata"


class Chiave:

    __slots__ = ("_segreto", "_contenuti", "nome")

    def __init__(self, segreto: bytes):
        if len(segreto) != LUNGHEZZA:
            raise ValueError("una chiave interna è lunga 32 byte")
        self._segreto = bytes(segreto)
        self._contenuti = _deriva(self._segreto, b"contenuti")
        self.nome = _deriva(self._segreto, b"nome", NOME).hex()

    def per_contenuto(self, numero: bytes) -> bytes:
        return _deriva(self._contenuti, b"contenuto\x00" + bytes(numero))

    def per(self, uso: str) -> bytes:
        if uso in ("contenuti", "nome"):
            raise ValueError(f"«{uso}» non si chiede da fuori")
        return _deriva(self._segreto, uso.encode("utf-8"))

    def __repr__(self) -> str:
        return f"Chiave({self.nome[:8]}…)"


def _deriva(segreto: bytes, uso: bytes, quanto: int = LUNGHEZZA) -> bytes:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF

    return HKDF(algorithm=hashes.SHA256(), length=quanto, salt=None,
                info=b"officina-sicuro\x00" + uso).derive(segreto)


def _aead():
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError as errore:
        raise ErroreOfficina(
            "Per l'Archivio sicuro serve la libreria «cryptography», che non "
            "è installata. Reinstalla il programma.",
            codice="manca_cryptography") from errore
    return AESGCM


def password_nuova_valida(password: str) -> None:
    if not password or len(password) < MINIMO:
        raise ErroreOfficina(
            "La password deve essere lunga almeno dodici caratteri. Lunga "
            "meglio che complicata: tre parole che ricordi valgono più di "
            "otto caratteri strani.", codice="password_corta")


def _scrypt(password: str, sale: bytes, costo: int, blocco: int,
            parallelo: int) -> bytes:
    return hashlib.scrypt(password.encode("utf-8"), salt=sale, n=costo,
                          r=blocco, p=parallelo, dklen=LUNGHEZZA,
                          maxmem=costo * blocco * 200)


def costo_per_questo_pc() -> int:
    inizio = time.perf_counter()
    _scrypt(secrets.token_hex(8), secrets.token_bytes(SALE), COSTO,
            BLOCCO_SCRYPT, PARALLELO)
    return COSTO if time.perf_counter() - inizio >= SECONDI else COSTO_LENTO


def _accompagnamento(numero: str, costo: int, blocco: int,
                     parallelo: int) -> bytes:
    return (f"{TIPO}\x00{VERSIONE}\x00{numero}\x00{costo}\x00{blocco}\x00"
            f"{parallelo}").encode("ascii")


def _porta(chiave: Chiave, password: str, costo: int) -> dict:
    numero = secrets.token_hex(8)
    sale = secrets.token_bytes(SALE)
    nonce = secrets.token_bytes(NONCE)
    chiusa = _aead()(_scrypt(password, sale, costo, BLOCCO_SCRYPT, PARALLELO)
                     ).encrypt(nonce, chiave._segreto,
                               _accompagnamento(numero, costo, BLOCCO_SCRYPT,
                                                PARALLELO))
    return {"numero": numero, "kdf": "scrypt", "n": costo, "r": BLOCCO_SCRYPT,
            "p": PARALLELO, "sale": sale.hex(), "nonce": nonce.hex(),
            "chiusa": chiusa.hex()}


def _apri_porta(porta: dict, password: str) -> bytes | None:
    from cryptography.exceptions import InvalidTag

    cifratore = _aead()(_scrypt(password, bytes.fromhex(porta["sale"]),
                                porta["n"], porta["r"], porta["p"]))
    try:
        return cifratore.decrypt(bytes.fromhex(porta["nonce"]),
                               bytes.fromhex(porta["chiusa"]),
                               _accompagnamento(porta["numero"], porta["n"],
                                                porta["r"], porta["p"]))
    except InvalidTag:
        return None


def _esadecimale(valore, lunghezza: int) -> bool:
    if not isinstance(valore, str) or len(valore) != lunghezza * 2:
        return False
    try:
        bytes.fromhex(valore)
    except ValueError:
        return False
    return True


def _porta_in_ordine(porta) -> bool:
    return (isinstance(porta, dict)
            and _esadecimale(porta.get("numero"), 8)
            and porta.get("kdf") == "scrypt"
            and type(porta.get("n")) is int and porta["n"] in COSTI_AMMESSI
            and porta.get("r") == BLOCCO_SCRYPT
            and porta.get("p") == PARALLELO
            and _esadecimale(porta.get("sale"), SALE)
            and _esadecimale(porta.get("nonce"), NONCE)
            and _esadecimale(porta.get("chiusa"), LUNGHEZZA + 16))


def _documento(chiave: Chiave, porte: list[dict]) -> dict:
    return {"tipo": TIPO, "versione": VERSIONE, "nome": chiave.nome,
            "porte": porte}


def _in_byte(documento: dict) -> bytes:
    return (json.dumps(documento, ensure_ascii=False, indent=1) + "\n"
            ).encode("utf-8")


def _leggi_uno(percorso: Path) -> dict | None:
    try:
        documento = json.loads(percorso.read_bytes().decode("utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(documento, dict) or documento.get("tipo") != TIPO:
        return None
    versione = documento.get("versione")
    if type(versione) is int and versione > VERSIONE:
        raise ErroreOfficina(
            "Questo Archivio sicuro è stato scritto da una versione più nuova "
            "del programma. Aggiorna il programma prima di aprirlo.",
            codice="versione_piu_nuova")
    porte = documento.get("porte")
    if (versione != VERSIONE or not _esadecimale(documento.get("nome"), NOME)
            or not isinstance(porte, list) or not porte
            or not all(_porta_in_ordine(porta) for porta in porte)):
        return None
    return documento


def esiste(cartella: Path) -> bool:
    return (cartella / FILE).exists() or (cartella / RISERVA).exists()


def _leggi(cartella: Path) -> tuple[dict | None, dict | None]:
    principale = _leggi_uno(cartella / FILE)
    riserva = _leggi_uno(cartella / RISERVA)
    if principale is None and riserva is None:
        if esiste(cartella):
            raise ChiaveRovinata(
                "Il file con la chiave dell'Archivio sicuro è rovinato, e anche "
                "la sua copia. Senza quel file le foto non si aprono: attacca "
                "la chiavetta dell'archivio, che ne ha un'altra copia.")
        raise ErroreOfficina("L'Archivio sicuro non è ancora stato creato.",
                             codice="sicuro_mancante")
    return principale, riserva


def _scrivi(cartella: Path, documento: dict) -> None:
    dati = _in_byte(documento)
    scrivi_tutto(cartella / FILE, dati)
    scrivi_tutto(cartella / RISERVA, dati)


def crea(cartella: Path, password: str, costo: int | None = None) -> Chiave:
    password_nuova_valida(password)
    if esiste(cartella):
        raise ErroreOfficina("L'Archivio sicuro ha già la sua chiave.",
                             codice="chiave_esiste")
    cartella.mkdir(parents=True, exist_ok=True)
    chiave = Chiave(secrets.token_bytes(LUNGHEZZA))
    porta = _porta(chiave, password, costo or costo_per_questo_pc())
    _scrivi(cartella, _documento(chiave, [porta]))
    _prova(cartella, chiave, password)
    return chiave


def _prova(cartella: Path, chiave: Chiave, password: str) -> None:
    aperte: dict[str, bytes | None] = {}
    for documento in _leggi(cartella):
        buono = documento is not None and documento["nome"] == chiave.nome
        if buono:
            buono = False
            for porta in documento["porte"]:
                impronta = json.dumps(porta, sort_keys=True)
                if impronta not in aperte:
                    aperte[impronta] = _apri_porta(porta, password)
                if aperte[impronta] == chiave._segreto:
                    buono = True
                    break
        if not buono:
            raise ChiaveRovinata(
                "Ho scritto la chiave dell'Archivio sicuro ma rileggendola non "
                "torna. La password di prima vale ancora.")


def _cerca(cartella: Path, password: str, ripara: bool = True) -> Chiave | None:
    principale, riserva = _leggi(cartella)
    provate: set[str] = set()
    for documento in (principale, riserva):
        if documento is None:
            continue
        for porta in documento["porte"]:
            impronta = json.dumps(porta, sort_keys=True)
            if impronta in provate:
                continue
            provate.add(impronta)
            segreto = _apri_porta(porta, password)
            if segreto is None:
                continue
            chiave = Chiave(segreto)
            if chiave.nome != documento["nome"]:
                raise ChiaveRovinata(
                    "La password apre la chiave, ma la chiave non è quella "
                    "di questo archivio: qualcuno ha mescolato i file.")
            if ripara:
                _rimetti_le_copie(cartella, principale, riserva, documento)
            return chiave
    return None


def _rimetti_le_copie(cartella: Path, principale: dict | None,
                      riserva: dict | None, buono: dict) -> None:
    dati = _in_byte(buono)
    for nome, documento in ((FILE, principale), (RISERVA, riserva)):
        if documento is None or _in_byte(documento) != dati:
            try:
                scrivi_tutto(cartella / nome, dati)
            except OSError:
                pass


def apri(cartella: Path, password: str, ripara: bool = True) -> Chiave:
    if not password:
        raise PasswordSbagliata("Scrivi la password dell'Archivio sicuro.")
    chiave = _cerca(cartella, password, ripara)
    if chiave is None:
        raise PasswordSbagliata(
            "La password non è quella. Non c'è nessun altro modo di aprire "
            "l'Archivio sicuro: non esiste un «password dimenticata» e non c'è "
            "una chiave di riserva (regola 506). Le foto non sono state "
            "toccate.")
    return chiave


def cambia_password(cartella: Path, chiave: Chiave, nuova: str,
                    costo: int | None = None) -> None:
    password_nuova_valida(nuova)
    principale, riserva = _leggi(cartella)
    documento = principale if principale is not None else riserva
    if documento["nome"] != chiave.nome:
        raise ChiaveRovinata("Questa chiave non è quella dell'archivio.")
    porta = _porta(chiave, nuova, costo or documento["porte"][-1]["n"])
    _scrivi(cartella, _documento(chiave, [*documento["porte"], porta]))
    _prova(cartella, chiave, nuova)
    _scrivi(cartella, _documento(chiave, [porta]))
    _prova(cartella, chiave, nuova)


def copia_in(cartella: Path, altrove: Path) -> None:
    principale, riserva = _leggi(cartella)
    documento = principale if principale is not None else riserva
    altrove.mkdir(parents=True, exist_ok=True)
    _scrivi(altrove, documento)
