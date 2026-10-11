from __future__ import annotations

import hashlib
import json
import secrets
from dataclasses import dataclass
from pathlib import Path

from officina.errori import (ErroreOfficina, FileNonLeggibile,
                             PasswordSbagliata)


FIRMA = b"VISORE-FILE\x00"
VERSIONE = 1

BLOCCO = 1024 * 1024
SIGILLO = 16
PREFISSO = 8
CONTATORE = 4

COSTO = 2 ** 15
BLOCCO_SCRYPT = 8
PARALLELO = 1
LUNGHEZZA_CHIAVE = 32
SALE = 16

PROVA = b"officina-visore-prova"


class PacchettoRovinato(ErroreOfficina):
    codice = "pacchetto_rovinato"


def sale_nuovo() -> bytes:
    return secrets.token_bytes(SALE)


def _aead():
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError as errore:
        raise ErroreOfficina(
            "Per costruire un pacchetto per il Visore serve la libreria "
            "«cryptography», che non è installata. Si mette con:\n\n"
            "    pip install cryptography\n\n"
            "Senza, tutto il resto del programma funziona: è solo il "
            "pacchetto per il telefono che non si può fare.",
            codice="manca_cryptography",
        ) from errore
    return AESGCM


def _accompagnamento(numero: int, ultimo: bool, dimensione: int) -> bytes:
    return (b"visore-" + str(VERSIONE).encode("ascii") + b"\x00"
            + numero.to_bytes(4, "big")
            + (b"\x01" if ultimo else b"\x00")
            + dimensione.to_bytes(8, "big"))


@dataclass
class Scritto:
    dimensione: int
    peso: int
    impronta: str


class Chiave:

    def __init__(self, byte: bytes):
        if len(byte) != LUNGHEZZA_CHIAVE:
            raise ErroreOfficina("Chiave di lunghezza sbagliata.")
        self._byte = byte
        self._cifratore = _aead()(byte)


    @classmethod
    def dalla_password(cls, password: str, sale: bytes, costo: int = COSTO,
                       blocco: int = BLOCCO_SCRYPT,
                       parallelo: int = PARALLELO) -> "Chiave":
        if not password or len(password) < 8:
            raise ErroreOfficina(
                "La password deve essere lunga almeno otto caratteri. È la "
                "stessa del forziere (regola 115).")
        return cls(hashlib.scrypt(
            password.encode("utf-8"), salt=sale, n=costo, r=blocco,
            p=parallelo, dklen=LUNGHEZZA_CHIAVE,
            maxmem=costo * blocco * 200))


    def prova(self) -> str:
        return self._cifratore.encrypt(
            _nonce(b"\x00" * PREFISSO, 0), PROVA,
            _accompagnamento(0, True, len(PROVA))).hex()

    def apre(self, prova: str) -> bool:
        try:
            aperto = self._cifratore.decrypt(
                _nonce(b"\x00" * PREFISSO, 0), bytes.fromhex(prova),
                _accompagnamento(0, True, len(PROVA)))
        except Exception:      # noqa: BLE001 — la libreria alza il suo
            return False
        return aperto == PROVA


    def cifra_byte(self, dati: bytes) -> bytes:
        prefisso = secrets.token_bytes(PREFISSO)
        pezzi = [_intestazione(prefisso, len(dati))]
        numero = 0
        inizio = 0
        while True:
            pezzo = dati[inizio:inizio + BLOCCO]
            ultimo = inizio + BLOCCO >= len(dati)
            pezzi.append(self._cifratore.encrypt(
                _nonce(prefisso, numero), pezzo,
                _accompagnamento(numero, ultimo, len(dati))))
            if ultimo:
                break
            inizio += BLOCCO
            numero += 1
        return b"".join(pezzi)

    def scrivi_byte(self, dati: bytes, destinazione: Path) -> Scritto:
        destinazione.parent.mkdir(parents=True, exist_ok=True)
        chiuso = self.cifra_byte(dati)
        provvisorio = destinazione.with_name(destinazione.name + ".parziale")
        provvisorio.write_bytes(chiuso)
        provvisorio.replace(destinazione)
        return Scritto(dimensione=len(dati), peso=len(chiuso),
                       impronta=hashlib.blake2b(dati, digest_size=32).hexdigest())

    def cifra_file(self, sorgente: Path, destinazione: Path) -> Scritto:
        dimensione = sorgente.stat().st_size
        impronta = hashlib.blake2b(digest_size=32)
        prefisso = secrets.token_bytes(PREFISSO)

        destinazione.parent.mkdir(parents=True, exist_ok=True)
        provvisorio = destinazione.with_name(destinazione.name + ".parziale")
        peso = 0
        try:
            with open(sorgente, "rb") as dentro, open(provvisorio, "wb") as fuori:
                testa = _intestazione(prefisso, dimensione)
                fuori.write(testa)
                peso += len(testa)
                numero = 0
                rimasti = dimensione
                while True:
                    quanto = min(BLOCCO, rimasti)
                    pezzo = dentro.read(quanto)
                    if len(pezzo) != quanto:
                        raise FileNonLeggibile(
                            f"«{sorgente.name}» è cambiato mentre lo stavo "
                            "copiando nel pacchetto: adesso è più corto di "
                            "quanto diceva. Rifai il travaso quando il file è "
                            "fermo.", codice="originale_cambiato")
                    rimasti -= quanto
                    ultimo = rimasti <= 0
                    impronta.update(pezzo)
                    chiuso = self._cifratore.encrypt(
                        _nonce(prefisso, numero), pezzo,
                        _accompagnamento(numero, ultimo, dimensione))
                    fuori.write(chiuso)
                    peso += len(chiuso)
                    if ultimo:
                        break
                    numero += 1
        except (OSError, FileNonLeggibile):
            provvisorio.unlink(missing_ok=True)
            raise
        provvisorio.replace(destinazione)
        return Scritto(dimensione=dimensione, peso=peso,
                       impronta=impronta.hexdigest())


    def leggi_tutto(self, sorgente: Path) -> bytes:
        with open(sorgente, "rb") as dentro:
            testa, inizio = _leggi_intestazione(dentro)
            dentro.seek(inizio)
            pezzi = []
            numero = 0
            quanti = quanti_blocchi(testa["dimensione"])
            while numero < quanti:
                pezzi.append(self._apri_un_blocco(
                    dentro.read(BLOCCO + SIGILLO), testa, numero,
                    ultimo=numero == quanti - 1))
                numero += 1
        return b"".join(pezzi)

    def leggi_pezzo(self, sorgente: Path, da: int, quanti: int) -> bytes:
        with open(sorgente, "rb") as dentro:
            testa, inizio = _leggi_intestazione(dentro)
            dimensione = testa["dimensione"]
            da = max(0, min(da, dimensione))
            fino = max(da, min(da + quanti, dimensione))
            if fino == da:
                return b""
            totale = quanti_blocchi(dimensione)
            primo = da // BLOCCO
            ultimo_utile = (fino - 1) // BLOCCO
            dentro.seek(inizio + primo * (BLOCCO + SIGILLO))
            pezzi = []
            for numero in range(primo, ultimo_utile + 1):
                pezzi.append(self._apri_un_blocco(
                    dentro.read(BLOCCO + SIGILLO), testa, numero,
                    ultimo=numero == totale - 1))
        aperto = b"".join(pezzi)
        scarto = da - primo * BLOCCO
        return aperto[scarto:scarto + (fino - da)]

    def decifra_file(self, sorgente: Path, destinazione: Path) -> str:
        impronta = hashlib.blake2b(digest_size=32)
        destinazione.parent.mkdir(parents=True, exist_ok=True)
        with open(sorgente, "rb") as dentro, open(destinazione, "wb") as fuori:
            testa, inizio = _leggi_intestazione(dentro)
            dentro.seek(inizio)
            quanti = quanti_blocchi(testa["dimensione"])
            for numero in range(quanti):
                pezzo = self._apri_un_blocco(
                    dentro.read(BLOCCO + SIGILLO), testa, numero,
                    ultimo=numero == quanti - 1)
                fuori.write(pezzo)
                impronta.update(pezzo)
        return impronta.hexdigest()

    def dimensione_in_chiaro(self, sorgente: Path) -> int:
        with open(sorgente, "rb") as dentro:
            testa, _ = _leggi_intestazione(dentro)
        return testa["dimensione"]


    def _apri_un_blocco(self, chiuso: bytes, testa: dict, numero: int,
                        ultimo: bool) -> bytes:
        if not chiuso:
            raise PacchettoRovinato(
                "Questo file del pacchetto finisce prima di quanto dichiara. "
                "È stato copiato male, o la copia si è interrotta. Si "
                "ricostruisce il pacchetto dal computer.")
        try:
            return self._cifratore.decrypt(
                _nonce(bytes.fromhex(testa["prefisso"]), numero), chiuso,
                _accompagnamento(numero, ultimo, testa["dimensione"]))
        except Exception as errore:      # noqa: BLE001 — la libreria alza il suo
            raise PacchettoRovinato(
                "Questo file del pacchetto non si apre: o la password non è "
                "quella con cui è stato fatto, o il file è rovinato. Se gli "
                "altri file si aprono, è rovinato solo lui e basta ricopiarlo.",
            ) from errore


def _nonce(prefisso: bytes, numero: int) -> bytes:
    return prefisso + numero.to_bytes(CONTATORE, "big")


def _intestazione(prefisso: bytes, dimensione: int) -> bytes:
    testa = json.dumps({
        "versione": VERSIONE,
        "cifra": "AES-256-GCM",
        "blocco": BLOCCO,
        "prefisso": prefisso.hex(),
        "dimensione": dimensione,
    }, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return FIRMA + len(testa).to_bytes(2, "big") + testa


def _leggi_intestazione(dentro) -> tuple[dict, int]:
    firma = dentro.read(len(FIRMA))
    if firma != FIRMA:
        raise PacchettoRovinato(
            "Questo file non fa parte di un pacchetto del Visore.")
    quanto = int.from_bytes(dentro.read(2), "big")
    grezza = dentro.read(quanto)
    if len(grezza) != quanto:
        raise PacchettoRovinato("Questo file del pacchetto è tagliato.")
    try:
        testa = json.loads(grezza.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as errore:
        raise PacchettoRovinato(
            "Questo file del pacchetto ha l'intestazione rovinata.") from errore
    if testa.get("versione") != VERSIONE:
        raise ErroreOfficina(
            "Questo pacchetto è stato scritto da una versione più nuova del "
            "programma (regola 372). Si rifà il pacchetto dal computer.")
    if testa.get("blocco") != BLOCCO:
        raise PacchettoRovinato(
            "Questo file del pacchetto usa blocchi di un'altra misura.")
    return testa, len(FIRMA) + 2 + quanto


def quanti_blocchi(dimensione: int) -> int:
    if dimensione <= 0:
        return 1
    return (dimensione + BLOCCO - 1) // BLOCCO


def peso_cifrato(dimensione: int) -> int:
    return (len(_intestazione(b"\x00" * PREFISSO, dimensione))
            + dimensione + quanti_blocchi(dimensione) * SIGILLO)


def controlla_la_password(password: str, sale: bytes, prova: str,
                          costo: int = COSTO, blocco: int = BLOCCO_SCRYPT,
                          parallelo: int = PARALLELO) -> Chiave:
    chiave = Chiave.dalla_password(password, sale, costo, blocco, parallelo)
    if not chiave.apre(prova):
        raise PasswordSbagliata(
            "La password non apre questo pacchetto. È la stessa del forziere "
            "sul computer (regola 115): se lì è cambiata dopo l'ultimo "
            "travaso, il pacchetto ha ancora quella vecchia, e si rifà.")
    return chiave
