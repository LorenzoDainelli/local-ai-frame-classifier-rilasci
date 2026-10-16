from __future__ import annotations

import hashlib
import json
import os
import secrets
import shutil
import tarfile
from dataclasses import dataclass
from pathlib import Path

from officina import registro
from officina.errori import ErroreOfficina


FIRMA = b"OFFICINA-FORZIERE\x00"
VERSIONE = 1

COSTO = 2 ** 15
BLOCCO_SCRYPT = 8
PARALLELO = 1
LUNGHEZZA_CHIAVE = 32
SALE = 16
MINIMO_NUOVA = 12

BLOCCO = 4 * 1024 * 1024

MARCATORE_APERTO = ".forziere-aperto"

PROVA = b"officina-forziere-prova"


class ForziereChiuso(ErroreOfficina):
    pass


class PasswordSbagliata(ErroreOfficina):
    pass


@dataclass
class Stato:
    acceso: bool
    aperto: bool
    peso: int

    def a_parole(self) -> str:
        if not self.acceso:
            return ("spento: l'archivio sta sul disco in chiaro (che Windows "
                    "cifra comunque, regola 9)")
        return "aperto" if self.aperto else "chiuso"


class Forziere:

    def __init__(self, posizione):
        self.posizione = posizione
        self.cartella = Path(posizione.radice)
        self.file = self.cartella.parent / f"{posizione.nome}.forziere"


    @property
    def acceso(self) -> bool:
        return self.file.exists()

    @property
    def aperto(self) -> bool:
        return (self.cartella / MARCATORE_APERTO).exists()

    def stato(self) -> Stato:
        return Stato(acceso=self.acceso, aperto=self.aperto,
                     peso=self.file.stat().st_size if self.acceso else 0)

    def la_password_e_giusta(self, password: str) -> bool:
        if not self.acceso:
            return False
        try:
            _password_utile(password)
        except ErroreOfficina:
            return False
        AESGCM = _aead()
        try:
            with open(self.file, "rb") as dentro:
                testa = _leggi_intestazione(dentro)
                cifratore = AESGCM(_chiave(password, bytes.fromhex(testa["sale"]),
                                           testa["n"], testa["r"], testa["p"]))
                _controlla_la_password(cifratore,
                                       bytes.fromhex(testa["prefisso"]),
                                       _leggi_un_blocco(dentro))
        except PasswordSbagliata:
            return False
        except OSError:
            registro.errore("forziere.non_si_legge")
            return False
        return True


    def accendi(self, password: str) -> Stato:
        if self.acceso:
            raise ErroreOfficina(
                "Questo archivio ha già un forziere. Per cambiare la password "
                "si apre e si richiude con quella nuova.")
        _password_nuova(password)
        if not self.cartella.is_dir():
            raise ErroreOfficina("Questo archivio non esiste ancora.")

        _scrivi(self.file, self.cartella, password)
        _svuota(self.cartella)
        self.cartella.mkdir(parents=True, exist_ok=True)
        registro.evento("forziere.acceso")
        return self.stato()


    def apri(self, password: str) -> None:
        if not self.acceso:
            return
        if self.aperto:
            registro.avviso("forziere.era_rimasto_aperto")
            return
        _password_utile(password)
        _leggi(self.file, self.cartella, password)
        (self.cartella / MARCATORE_APERTO).write_text(
            "Questo archivio è aperto. Il file sparisce quando si richiude.\n",
            encoding="utf-8")
        registro.evento("forziere.aperto")


    def chiudi(self, password: str) -> None:
        if not self.acceso or not self.aperto:
            return
        _password_utile(password)
        _scrivi(self.file, self.cartella, password)
        (self.cartella / MARCATORE_APERTO).unlink(missing_ok=True)
        _svuota(self.cartella)
        self.cartella.mkdir(parents=True, exist_ok=True)
        registro.evento("forziere.chiuso")


    def spegni(self, password: str) -> None:
        if not self.acceso:
            return
        if not self.aperto:
            self.apri(password)
        else:
            _password_utile(password)
            _rileggi_per_controllo(self.file, password)
        (self.cartella / MARCATORE_APERTO).unlink(missing_ok=True)
        self.file.unlink()
        registro.evento("forziere.spento")


def _aead():
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError as errore:
        raise ErroreOfficina(
            "Per il forziere serve la libreria «cryptography», che non è "
            "installata. Si mette con:\n\n    pip install cryptography\n\n"
            "Senza, tutto il resto del programma funziona: l'archivio resta "
            "in chiaro sul disco, che Windows cifra comunque (regola 9).",
            codice="manca_cryptography",
        ) from errore
    return AESGCM


def _password_utile(password: str) -> None:
    if not password or len(password) < 8:
        raise ErroreOfficina(
            "La password deve essere lunga almeno otto caratteri. Lunga meglio "
            "che complicata: tre parole che ricordi valgono più di otto "
            "caratteri strani.")


def _password_nuova(password: str) -> None:
    if not password or len(password) < MINIMO_NUOVA:
        raise ErroreOfficina(
            "La password nuova deve essere lunga almeno dodici caratteri. Lunga "
            "meglio che complicata: tre parole che ricordi valgono più di otto "
            "caratteri strani.")


def _chiave(password: str, sale: bytes, costo: int, blocco: int,
            parallelo: int) -> bytes:
    return hashlib.scrypt(password.encode("utf-8"), salt=sale, n=costo,
                          r=blocco, p=parallelo, dklen=LUNGHEZZA_CHIAVE,
                          maxmem=costo * blocco * 200)


def _intestazione(sale: bytes, prefisso: bytes) -> bytes:
    testa = json.dumps({
        "versione": VERSIONE,
        "kdf": "scrypt",
        "n": COSTO, "r": BLOCCO_SCRYPT, "p": PARALLELO,
        "sale": sale.hex(),
        "prefisso": prefisso.hex(),
        "cifra": "AES-256-GCM",
        "blocco": BLOCCO,
    }, ensure_ascii=False).encode("utf-8")
    return FIRMA + len(testa).to_bytes(4, "big") + testa


def _leggi_intestazione(sorgente) -> dict:
    firma = sorgente.read(len(FIRMA))
    if firma != FIRMA:
        raise ErroreOfficina(
            "Questo file non è un forziere di questo programma.")
    quanto = int.from_bytes(sorgente.read(4), "big")
    testa = json.loads(sorgente.read(quanto).decode("utf-8"))
    if testa.get("versione") != VERSIONE:
        raise ErroreOfficina(
            "Questo forziere è stato scritto da una versione più nuova del "
            "programma. Aggiorna il programma prima di aprirlo.")
    return testa


def _nonce(prefisso: bytes, numero: int) -> bytes:
    return prefisso + numero.to_bytes(8, "big")


def _accompagnamento(numero: int, ultimo: bool) -> bytes:
    return (b"officina-forziere-" + str(VERSIONE).encode("ascii") + b"\x00"
            + numero.to_bytes(8, "big") + (b"\x01" if ultimo else b"\x00"))


class _Cifrante:

    def __init__(self, fuori, cifratore, prefisso: bytes):
        self.fuori = fuori
        self.cifratore = cifratore
        self.prefisso = prefisso
        self.numero = 1
        self.attesa = bytearray()

    def write(self, dati) -> int:
        self.attesa += dati
        while len(self.attesa) > BLOCCO:
            self._manda(bytes(self.attesa[:BLOCCO]), ultimo=False)
            del self.attesa[:BLOCCO]
        return len(dati)

    def finisci(self) -> None:
        self._manda(bytes(self.attesa), ultimo=True)
        self.attesa.clear()

    def _manda(self, pezzo: bytes, ultimo: bool) -> None:
        _scrivi_un_blocco(self.fuori, self.cifratore.encrypt(
            _nonce(self.prefisso, self.numero), pezzo,
            _accompagnamento(self.numero, ultimo)))
        self.numero += 1


class _Decifrante:

    def __init__(self, dentro, cifratore, prefisso: bytes):
        self.dentro = dentro
        self.cifratore = cifratore
        self.prefisso = prefisso
        self.numero = 1
        self.pronto = b""
        self.posizione = 0
        self.finito = False

    def read(self, quanti: int = -1) -> bytes:
        pezzi = []
        while quanti != 0:
            if self.posizione >= len(self.pronto):
                if self.finito:
                    break
                self._prossimo()
                continue
            fine = len(self.pronto) if quanti < 0 else min(
                len(self.pronto), self.posizione + quanti)
            pezzi.append(self.pronto[self.posizione:fine])
            if quanti > 0:
                quanti -= fine - self.posizione
            self.posizione = fine
        return b"".join(pezzi)

    def fino_in_fondo(self) -> None:
        while not self.finito:
            self._prossimo()
        self.pronto = b""

    def _prossimo(self) -> None:
        chiuso = _leggi_un_blocco(self.dentro)
        if not chiuso:
            raise ErroreOfficina(
                "Il forziere finisce a metà: manca l'ultimo blocco. "
                "Il file è rovinato, o è stato copiato mentre il "
                "programma stava ancora scrivendo.")
        self.pronto, self.finito = _apri_un_blocco(self.cifratore, self.prefisso,
                                                   self.numero, chiuso)
        self.posizione = 0
        self.numero += 1


def _scrivi(destinazione: Path, cartella: Path, password: str) -> None:
    AESGCM = _aead()
    sale = secrets.token_bytes(SALE)
    prefisso = secrets.token_bytes(4)
    cifratore = AESGCM(_chiave(password, sale, COSTO, BLOCCO_SCRYPT, PARALLELO))

    provvisorio = destinazione.with_suffix(destinazione.suffix + ".nuovo")
    try:
        with open(provvisorio, "wb") as fuori:
            fuori.write(_intestazione(sale, prefisso))
            _scrivi_un_blocco(fuori, cifratore.encrypt(
                _nonce(prefisso, 0), PROVA, _accompagnamento(0, False)))
            flusso = _Cifrante(fuori, cifratore, prefisso)
            _impacchetta(cartella, flusso)
            flusso.finisci()
            fuori.flush()
            os.fsync(fuori.fileno())
        _rileggi_per_controllo(provvisorio, password)
        provvisorio.replace(destinazione)
    finally:
        provvisorio.unlink(missing_ok=True)


def _scrivi_un_blocco(fuori, chiuso: bytes) -> None:
    fuori.write(len(chiuso).to_bytes(4, "big"))
    fuori.write(chiuso)


def _leggi_un_blocco(dentro) -> bytes:
    lunghezza = dentro.read(4)
    if not lunghezza:
        return b""
    if len(lunghezza) < 4:
        raise ErroreOfficina(
            "Il forziere finisce a metà: l'ultimo blocco è tagliato. Il file "
            "è stato copiato mentre il programma stava ancora scrivendo, "
            "oppure è rovinato. Se hai una copia (regola 42), è il momento.")
    atteso = int.from_bytes(lunghezza, "big")
    chiuso = dentro.read(atteso)
    if len(chiuso) != atteso:
        raise ErroreOfficina(
            f"Il forziere finisce a metà: un blocco dichiara {atteso} byte e "
            f"ce ne sono {len(chiuso)}. Il file è tagliato, non cifrato male. "
            "Se hai una copia (regola 42), è il momento di usarla.")
    return chiuso


def _controlla_la_password(cifratore, prefisso: bytes, chiuso: bytes) -> None:
    try:
        aperto = cifratore.decrypt(_nonce(prefisso, 0), chiuso,
                                   _accompagnamento(0, False))
    except Exception as errore:      # noqa: BLE001 — la libreria alza il suo
        raise PasswordSbagliata(
            "La password non è quella. Non c'è nessun altro modo di aprire "
            "questo archivio: non esiste un «password dimenticata», e non è "
            "una dimenticanza — se ci fosse una via di recupero, quella via "
            "sarebbe anche la via di chi non deve entrare (regola 106). Le "
            "foto originali non sono qui dentro: quelle sono ancora nella tua "
            "cartella, intatte.") from errore
    if aperto != PROVA:
        raise ErroreOfficina("Questo forziere è rovinato all'inizio.")


def _impacchetta(cartella: Path, flusso: _Cifrante) -> None:
    with tarfile.open(fileobj=flusso, mode="w|") as pacco:
        for roba in sorted(cartella.rglob("*")):
            if roba.name == MARCATORE_APERTO:
                continue
            pacco.add(roba, arcname=str(roba.relative_to(cartella)),
                      recursive=False)


def _leggi(sorgente_file: Path, cartella: Path, password: str) -> None:
    AESGCM = _aead()
    with open(sorgente_file, "rb") as dentro:
        testa = _leggi_intestazione(dentro)
        sale = bytes.fromhex(testa["sale"])
        prefisso = bytes.fromhex(testa["prefisso"])
        cifratore = AESGCM(_chiave(password, sale, testa["n"], testa["r"],
                                   testa["p"]))
        _controlla_la_password(cifratore, prefisso, _leggi_un_blocco(dentro))
        if cartella.is_dir():
            shutil.rmtree(cartella)
        cartella.mkdir(parents=True, exist_ok=True)
        flusso = _Decifrante(dentro, cifratore, prefisso)
        with tarfile.open(fileobj=flusso, mode="r|") as pacco:
            _estrai_senza_uscire(pacco, cartella)
        flusso.fino_in_fondo()


def _apri_un_blocco(cifratore, prefisso: bytes, numero: int,
                    chiuso: bytes) -> tuple[bytes, bool]:
    for ultimo in (False, True):
        try:
            return (cifratore.decrypt(_nonce(prefisso, numero), chiuso,
                                      _accompagnamento(numero, ultimo)),
                    ultimo)
        except Exception:          # noqa: BLE001 — la libreria alza il suo
            continue
    raise ErroreOfficina(
        f"Il blocco numero {numero} del forziere non torna: la password è "
        "giusta, ma quel pezzo di file è rovinato o è stato spostato. Se hai "
        "una copia (regola 42), è il momento di usarla.")


def _estrai_senza_uscire(pacco: tarfile.TarFile, dove: Path) -> None:
    radice = dove.resolve()
    for voce in pacco:
        arrivo = (radice / voce.name).resolve()
        if arrivo != radice and radice not in arrivo.parents:
            raise ErroreOfficina(
                "Dentro il forziere c'è un percorso che punta fuori "
                "dall'archivio. Non lo apro.")
        try:
            pacco.extract(voce, radice, filter="data")
        except TypeError:
            pacco.extract(voce, radice)


def _rileggi_per_controllo(file: Path, password: str) -> None:
    AESGCM = _aead()
    with open(file, "rb") as dentro:
        testa = _leggi_intestazione(dentro)
        cifratore = AESGCM(_chiave(password, bytes.fromhex(testa["sale"]),
                                   testa["n"], testa["r"], testa["p"]))
        prefisso = bytes.fromhex(testa["prefisso"])
        _controlla_la_password(cifratore, prefisso, _leggi_un_blocco(dentro))
        numero = 1
        while True:
            chiuso = _leggi_un_blocco(dentro)
            if not chiuso:
                raise ErroreOfficina(
                    "Il forziere appena scritto finisce a metà. Non cancello "
                    "niente: l'archivio in chiaro è ancora al suo posto.")
            _, finito = _apri_un_blocco(cifratore, prefisso, numero, chiuso)
            if finito:
                return
            numero += 1


def _svuota(cartella: Path) -> None:
    if cartella.is_dir():
        shutil.rmtree(cartella)
    for avanzo in cartella.parent.glob(f".{cartella.name}.tar.*"):
        avanzo.unlink(missing_ok=True)


def per(posizione) -> Forziere:
    return Forziere(posizione)
