from __future__ import annotations

import contextlib
import copy
import hashlib
import json
import os
import re
import secrets
import sqlite3
import stat
import struct
import threading
import time
import uuid
import zlib
from dataclasses import dataclass
from pathlib import Path

from officina.errori import ErroreOfficina
from officina.sicuro import elenco as registro
from officina.sicuro import formato, metadati, sveglia
from officina.sicuro.chiavetta import CARTELLA, ChiavettaStaccata
from officina.sicuro.copia import (CUSTODITO, DA_SALTARE, SEGNI_DA_RIFARE, STATI_BUONI,
                                   Copiatore, Fermato)
from officina.sicuro.dentro import _numero, _resto, _sotto_di, _uguali, _vero
from officina.sicuro.diretto import Lettore
from officina.sicuro.disco import WINDOWS, percorso_lungo, scrivi_tutto
from officina.sicuro.sottofondo import PAUSA_SE_USI, Sottofondo
from officina.sicuro.via_libera import Esaminatore


GIORNI = 30
ATTESA = GIORNI * 86400.0
MARGINE = 0.9
PERCENTO = 4
SISTEMI = frozenset({"NTFS", "REFS"})
CESTINO = "$Recycle.Bin"
LUNGO = 259
CASUALI = 6
PRIMA = 5.0
INFO_MASSIMA = 64 * 1024
DA_LASCIARE = frozenset({"desktop.ini"})
PROVA_FILE = 100
PROVA_BYTE = 2 * 1024 ** 3
OGNI = 60.0
TENTATIVI = 5
PAROLA = "cancella"
GB = 1024 ** 3
MB = 1024 ** 2
SECONDI_WINDOWS = 11644473600.0

FISSO = "fisso"
CHIAVETTA = "chiavetta"
RETE = "rete"
STRANO = "strano"

S_OK = 0
E_ABORT = -2147467260
E_NOINTERFACE = -2147467262
RICICLA_SE_PUOI = 0x80
OPZIONI = 0x4 | 0x10 | 0x40 | 0x200 | 0x400 | 0x80000 | 0x100000
TUTTI_I_CONTESTI = 0x17
PERCORSO_VERO = 0x80058000
OPERAZIONE = "3ad05575-8857-4850-9277-11b85bdb8e09"
IFILEOPERATION = "947aab5f-0a5c-4c13-b4d6-4bf7836fc9f8"
ISHELLITEM = "43826d1e-e718-42ee-bc55-a1e261c37bfe"
IPROGRESSO = "04b0f1a7-9490-44bc-96e1-4296a31252e2"
IUNKNOWN = "00000000-0000-0000-c000-000000000046"
BITBUCKET = r"Software\Microsoft\Windows\CurrentVersion\Explorer\BitBucket"
POLITICHE = r"Software\Microsoft\Windows\CurrentVersion\Policies\Explorer"
SENSORE = r"Software\Microsoft\Windows\CurrentVersion\StorageSense\Parameters\StoragePolicy"

TIPO_QUADERNO = b"officina-archivio-sicuro-cestino"
TIPO_LISTA = b"officina-archivio-sicuro-cestino-lista"
VERSIONE = 1
NONCE = 12
QUADERNO = "cestino.stato"
RISERVA = "cestino.riserva.stato"
LISTE = "cestino"

IN_PARTENZA = "in_partenza"
NEL_CESTINO = "nel_cestino"
NON_PARTITA = "non_partita"
A_META = "a_meta"
DIVERSA = "diversa"
PERSA = "persa"
SVUOTATA = "svuotata"
TORNATA = "tornata"
ESITI = (IN_PARTENZA, NEL_CESTINO, NON_PARTITA, A_META, DIVERSA, PERSA, SVUOTATA, TORNATA)
DA_GUARDARE_ESITI = (A_META, DIVERSA, PERSA)
IN_PARTE = "in_parte"
DA_GUARDARE = "da_guardare"
NON_TOCCATA = "non_toccata"

DA_FARE = "da_fare"
FATTO = "fatto"
COLLAUDI = (DA_FARE, DA_GUARDARE, FATTO)

SVUOTABILE = "svuotabile"
ASPETTA = "aspetta"
FINITA = "finita"

ATTIVO = "attivo"
RIMESSO = "rimesso"
PERSO = "perso"
LASCIATO = "lasciato"
STATI_ALLARME = (ATTIVO, RIMESSO, PERSO, LASCIATO)
DA_MOSTRARE = (ATTIVO, PERSO)

AVVISO = ("Archivio sicuro: nel Cestino ci sono file che non sono nell'archivio. "
          "Aprilo per vedere cosa fare.")
GLOBALI = frozenset({"archivio_sparito", ChiavettaStaccata.codice, "quaderno_non_salvato",
                     "quaderno_rovinato", "quaderno_illeggibile", "quaderno_piu_nuovo",
                     "occupato"})

PROBLEMI = {
    "senza_cestino": "Qui non c'è il Cestino di Windows: non tocco niente.",
    "disco_strano": "Non riesco a capire su che disco è questa cartella: non la tocco.",
    "non_nel_cestino_chiavetta": (
        "Questa cartella è su una chiavetta o una scheda: lì Windows cancella per sempre, "
        "senza Cestino. Non la tocco."),
    "disco_di_rete": (
        "Questa cartella è su un disco di rete: lì Windows cancella per sempre, senza "
        "Cestino. Non la tocco."),
    "sistema_strano": (
        "Questo disco non è NTFS: non sono sicuro che il Cestino funzioni bene, quindi non "
        "la tocco."),
    "cestino_spento": (
        "Su questo disco il Cestino è spento e Windows cancellerebbe subito per sempre: "
        "non la tocco. Puoi riaccenderlo nelle proprietà del Cestino."),
    "cestino_sconosciuto": (
        "Non riesco a leggere com'è fatto il Cestino su questo disco: non la tocco."),
    "troppo_grande": (
        "Questa cartella è troppo grande per il Cestino di questo disco: Windows la "
        "cancellerebbe per sempre. Non la tocco. Mandane una parte alla volta, o "
        "ingrandisci il Cestino nelle sue proprietà."),
    "cestino_pieno": (
        "Il Cestino è quasi pieno: per farle posto Windows cancellerebbe per sempre le "
        "cose più vecchie che ci sono dentro. Non la tocco. Prima fai posto nel Cestino."),
    "percorso_strano": (
        "Un nome finisce con un punto o con uno spazio: Windows potrebbe confonderlo con un "
        "altro. Non la tocco."),
    "percorso_lungo": (
        "Dentro ci sono percorsi troppo lunghi per il Cestino: non la tocco."),
}


class _Altro(Exception):
    pass


class _Spedita(Exception):

    def __init__(self, risultato: dict, codice: str, messaggio: str):
        super().__init__(codice)
        self.risultato = risultato
        self.codice = codice
        self.messaggio = messaggio


@dataclass(frozen=True)
class Capienza:
    massimo: int | None
    spento: bool = False


@dataclass(frozen=True)
class Mossa:
    fatta: bool
    dove: str | None = None
    codice: str | None = None


@dataclass(frozen=True)
class Buttato:
    nome: str
    originale: str
    quando: float
    dimensione: int
    info: str
    dati: str

    @property
    def segno(self) -> str:
        return f"{self.nome}|{self.quando:.3f}"


def leggi_info(grezzi: bytes) -> tuple[str, float, int] | None:
    if len(grezzi) < 24:
        return None
    versione, dimensione, tempo = struct.unpack_from("<qqQ", grezzi)
    if versione == 1:
        testo = grezzi[24:24 + 520]
        if len(testo) < 520:
            return None
    elif versione == 2:
        if len(grezzi) < 28:
            return None
        (lunghezza,) = struct.unpack_from("<i", grezzi, 24)
        if not 0 < lunghezza <= 32768:
            return None
        testo = grezzi[28:28 + 2 * lunghezza]
        if len(testo) != 2 * lunghezza:
            return None
    else:
        return None
    try:
        originale = testo.decode("utf-16-le", "surrogatepass").split("\x00", 1)[0]
    except UnicodeDecodeError:
        return None
    if not originale or dimensione < 0:
        return None
    return originale, tempo / 1e7 - SECONDI_WINDOWS, dimensione


def scrivi_info(originale: str, quando: float, dimensione: int) -> bytes:
    testo = (originale + "\x00").encode("utf-16-le", "surrogatepass")
    tempo = max(0, round((quando + SECONDI_WINDOWS) * 1e7))
    return struct.pack("<qqQi", 2, dimensione, tempo, len(testo) // 2) + testo


def stesso_percorso(uno: str, altro: str) -> bool:
    return (os.path.normcase(os.path.normpath(uno))
            == os.path.normcase(os.path.normpath(altro)))


def permesso(flags: int, elemento: str | None, atteso: str) -> int:
    try:
        if not int(flags) & RICICLA_SE_PUOI:
            return E_ABORT
        if elemento is None or not stesso_percorso(elemento, atteso):
            return E_ABORT
    except Exception:
        return E_ABORT
    return S_OK


def _quanto(byte: int) -> str:
    if round(byte / MB) >= 1024:
        return f"{byte / GB:.1f}".replace(".", ",") + " GB"
    if byte >= MB:
        return f"{round(byte / MB)} MB"
    if byte > 0:
        return "meno di 1 MB"
    return "0 MB"


def _accompagnamento(tipo: bytes) -> bytes:
    return tipo + b"\x00" + bytes([VERSIONE])


def _cifra(chiave, tipo: bytes, dati) -> bytes:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    testa = _accompagnamento(tipo)
    nonce = secrets.token_bytes(NONCE)
    chiaro = zlib.compress(json.dumps(dati, separators=(",", ":"),
                                      ensure_ascii=True).encode("ascii"))
    return testa + nonce + AESGCM(chiave.per("cestino-stato")).encrypt(nonce, chiaro, testa)


def _decifra(chiave, tipo: bytes, grezzi: bytes):
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    testa = _accompagnamento(tipo)
    if not grezzi.startswith(testa) or len(grezzi) < len(testa) + NONCE + 16:
        return None
    nonce = grezzi[len(testa):len(testa) + NONCE]
    try:
        chiaro = AESGCM(chiave.per("cestino-stato")).decrypt(
            nonce, grezzi[len(testa) + NONCE:], testa)
        return json.loads(zlib.decompress(chiaro).decode("ascii"))
    except (InvalidTag, zlib.error, ValueError):
        return None


def _altra_versione(tipo: bytes, grezzi: bytes) -> bool:
    testa = _accompagnamento(tipo)
    return (grezzi[:len(testa) - 1] == testa[:-1] and len(grezzi) >= len(testa)
            and grezzi[len(testa) - 1] > VERSIONE)


def _intero(valore) -> bool:
    return type(valore) is int and valore >= 0


def _quaderno_buono(dati) -> bool:
    return (isinstance(dati, dict) and _intero(dati.get("numero"))
            and isinstance(dati.get("spedizioni"), list)
            and all(isinstance(spedizione, dict) and isinstance(spedizione.get("id"), str)
                    and isinstance(spedizione.get("voci"), list)
                    for spedizione in dati["spedizioni"])
            and dati.get("collaudo") in COLLAUDI
            and isinstance(dati.get("visti"), dict)
            and all(isinstance(volume, str) and isinstance(visti, list)
                    for volume, visti in dati["visti"].items())
            and isinstance(dati.get("allarmi"), list)
            and all(isinstance(allarme, dict) and allarme.get("stato") in STATI_ALLARME
                    for allarme in dati["allarmi"]))


def _lista_buona(dati, id: str) -> bool:
    return (isinstance(dati, dict) and dati.get("id") == id
            and isinstance(dati.get("voci"), list)
            and all(isinstance(voce, dict) and isinstance(voce.get("impronte"), dict)
                    and isinstance(voce.get("posti"), dict) for voce in dati["voci"]))


class Quaderno:

    def __init__(self, cartella: Path, chiave):
        self.cartella = Path(cartella)
        self._chiave = chiave
        self._serratura = threading.RLock()
        self.problemi: list[str] = []
        self._stato = self._carica()

    @staticmethod
    def _vuoto() -> dict:
        return {"numero": 0, "spedizioni": [], "collaudo": DA_FARE, "prova": None,
                "visti": {}, "allarmi": []}

    def _archivio_c_e(self) -> bool:
        try:
            return stat.S_ISDIR(os.stat(percorso_lungo(
                self.cartella / registro.CONTENUTI)).st_mode)
        except (OSError, ValueError):
            return False

    def _carica(self) -> dict:
        if not self._archivio_c_e():
            self.problemi.append("archivio_sparito")
            return self._vuoto()
        trovati = []
        rovinati = illeggibili = piu_nuovi = 0
        for nome in (QUADERNO, RISERVA):
            try:
                grezzi = (self.cartella / nome).read_bytes()
            except FileNotFoundError:
                continue
            except OSError:
                illeggibili += 1
                continue
            dati = _decifra(self._chiave, TIPO_QUADERNO, grezzi)
            if _quaderno_buono(dati):
                trovati.append(dati)
            elif _altra_versione(TIPO_QUADERNO, grezzi):
                piu_nuovi += 1
            else:
                rovinati += 1
        if piu_nuovi:
            self.problemi.append("quaderno_piu_nuovo")
            return self._vuoto()
        if not trovati:
            liste = self._liste_rimaste()
            if illeggibili or liste is None:
                self.problemi.append("quaderno_illeggibile")
            elif rovinati or liste:
                self.problemi.append("quaderno_rovinato")
            return self._vuoto()
        stato = max(trovati, key=lambda dati: dati["numero"])
        stato.setdefault("prova", None)
        return stato

    def _liste_rimaste(self) -> bool | None:
        try:
            with os.scandir(percorso_lungo(self.cartella / LISTE)) as voci:
                return any(voce.name.endswith(".lista") for voce in voci)
        except FileNotFoundError:
            return False
        except (OSError, ValueError):
            return None

    def ricarica(self) -> None:
        with self._serratura:
            self.problemi = []
            self._stato = self._carica()

    def _si_scrive(self) -> None:
        if "archivio_sparito" in self.problemi:
            raise ErroreOfficina(
                "Il disco dell'Archivio sicuro non si leggeva quando ho aperto il quaderno "
                "del Cestino: ricollegalo e riprova.", codice="archivio_sparito")
        if "quaderno_piu_nuovo" in self.problemi:
            raise ErroreOfficina(
                "Il quaderno del Cestino è stato scritto da una versione più nuova del "
                "programma: aggiorna il programma.", codice="quaderno_piu_nuovo")
        if "quaderno_illeggibile" in self.problemi:
            raise ErroreOfficina(
                "Il quaderno dove segno cosa ho mandato nel Cestino adesso non si legge: "
                "riprova fra poco.", codice="quaderno_illeggibile")
        if self.problemi:
            raise ErroreOfficina(
                "Il quaderno dove segno cosa ho mandato nel Cestino è rovinato o sparito: "
                "finché non lo ricominci non mando niente nel Cestino.",
                codice="quaderno_rovinato")

    def _scrivi(self, percorsi, grezzi: bytes) -> None:
        try:
            for percorso in percorsi:
                scrivi_tutto(percorso, grezzi)
        except OSError:
            raise ErroreOfficina(
                "Non riesco a scrivere sul disco dell'Archivio sicuro: non tocco niente.",
                codice="quaderno_non_salvato") from None

    def _cambia(self, cambio) -> None:
        with self._serratura:
            self._si_scrive()
            nuovo = copy.deepcopy(self._stato)
            cambio(nuovo)
            nuovo["numero"] = self._stato["numero"] + 1
            grezzi = _cifra(self._chiave, TIPO_QUADERNO, nuovo)
            self._scrivi([self.cartella / QUADERNO, self.cartella / RISERVA], grezzi)
            self._stato = nuovo

    def ricomincia(self) -> None:
        with self._serratura:
            if self.problemi:
                self.ricarica()
            if self.problemi != ["quaderno_rovinato"]:
                self._si_scrive()
                return
            self.problemi = []
            self._stato = self._vuoto()
            self._cambia(lambda stato: None)

    @property
    def numero(self) -> int:
        with self._serratura:
            return self._stato["numero"]

    def spedizioni(self) -> list[dict]:
        with self._serratura:
            return copy.deepcopy(self._stato["spedizioni"])

    def spedizione(self, id: str) -> dict | None:
        with self._serratura:
            for spedizione in self._stato["spedizioni"]:
                if spedizione["id"] == id:
                    return copy.deepcopy(spedizione)
        return None

    def metti(self, spedizione: dict) -> None:
        def cambio(stato: dict) -> None:
            spedizioni = stato["spedizioni"]
            for posizione, vecchia in enumerate(spedizioni):
                if vecchia["id"] == spedizione["id"]:
                    spedizioni[posizione] = copy.deepcopy(spedizione)
                    return
            spedizioni.append(copy.deepcopy(spedizione))

        self._cambia(cambio)

    @property
    def collaudo(self) -> str:
        with self._serratura:
            return self._stato["collaudo"]

    @property
    def prova(self) -> str | None:
        with self._serratura:
            return self._stato["prova"]

    def metti_collaudo(self, collaudo: str, prova: str | None = None) -> None:
        if collaudo not in COLLAUDI:
            raise ValueError(f"collaudo strano: {collaudo!r}")

        def cambio(stato: dict) -> None:
            stato["collaudo"] = collaudo
            if prova is not None:
                stato["prova"] = prova

        self._cambia(cambio)

    def visti(self, volume: str) -> set[str]:
        with self._serratura:
            return set(self._stato["visti"].get(os.path.normcase(volume), []))

    def metti_visti(self, volume: str, visti) -> None:
        chiave = os.path.normcase(volume)
        elenco = sorted(visti)

        def cambio(stato: dict) -> None:
            stato["visti"][chiave] = elenco

        self._cambia(cambio)

    def allarmi(self) -> list[dict]:
        with self._serratura:
            return copy.deepcopy(self._stato["allarmi"])

    def metti_allarme(self, allarme: dict) -> None:
        def cambio(stato: dict) -> None:
            allarmi = stato["allarmi"]
            for posizione, vecchio in enumerate(allarmi):
                if vecchio["id"] == allarme["id"]:
                    allarmi[posizione] = copy.deepcopy(allarme)
                    return
            allarmi.append(copy.deepcopy(allarme))

        self._cambia(cambio)

    def _liste(self, id: str) -> tuple[Path, Path]:
        if not re.fullmatch(r"[0-9a-f]{16}", id):
            raise ValueError(f"spedizione strana: {id!r}")
        cartella = self.cartella / LISTE
        return cartella / f"{id}.lista", cartella / f"{id}.riserva.lista"

    def scrivi_lista(self, id: str, lista: dict) -> None:
        with self._serratura:
            self._si_scrive()
            percorsi = self._liste(id)
            try:
                percorsi[0].parent.mkdir(exist_ok=True)
            except OSError:
                raise ErroreOfficina(
                    "Non riesco a scrivere sul disco dell'Archivio sicuro: non tocco "
                    "niente.", codice="quaderno_non_salvato") from None
            self._scrivi(percorsi, _cifra(self._chiave, TIPO_LISTA, lista))

    def leggi_lista(self, id: str) -> dict | None:
        for percorso in self._liste(id):
            try:
                grezzi = percorso.read_bytes()
            except OSError:
                continue
            dati = _decifra(self._chiave, TIPO_LISTA, grezzi)
            if _lista_buona(dati, id):
                return dati
        return None


def _voci_dentro(esame) -> list[str]:
    if not esame.solo_dentro:
        return [""]
    voci = []
    for relativo, impronta in esame.impronta.items():
        if not relativo or "/" in relativo or relativo.casefold() in DA_LASCIARE:
            continue
        if impronta[0] == metadati.COLLEGAMENTO:
            continue
        voci.append(relativo)
    return sorted(voci)


def _della_voce(impronte: dict, relativo: str) -> dict[str, list]:
    if not relativo:
        return {chiave: list(valore) for chiave, valore in impronte.items()}
    dentro = {}
    for chiave, valore in impronte.items():
        resto = _sotto_di(chiave, relativo)
        if resto is not None:
            dentro[resto] = list(valore)
    return dentro


def _nella_voce(dove: str, relativo: str) -> bool:
    return not relativo or _sotto_di(dove, relativo) is not None


def stato_di(spedizione: dict) -> str:
    esiti = [voce["esito"] for voce in spedizione["voci"]]
    if IN_PARTENZA in esiti:
        return IN_PARTENZA
    if any(esito in DA_GUARDARE_ESITI for esito in esiti):
        return DA_GUARDARE
    if all(esito == NON_PARTITA for esito in esiti):
        return NON_PARTITA
    if NON_PARTITA in esiti:
        return IN_PARTE
    return NEL_CESTINO


def _non_toccata(cartella: str, codice: str, messaggio: str) -> dict:
    return {"cartella": cartella, "esito": NON_TOCCATA, "codice": codice,
            "messaggio": messaggio, "spedizione": None, "file": 0, "byte": 0}


class Cestino:

    def volume(self, percorso: str) -> str | None:
        raise NotImplementedError

    def tipo(self, volume: str) -> str:
        raise NotImplementedError

    def sistema(self, volume: str) -> str | None:
        raise NotImplementedError

    def capienza(self, volume: str) -> Capienza:
        raise NotImplementedError

    def usato(self, volume: str) -> int | None:
        raise NotImplementedError

    def pulizia(self) -> int | None:
        raise NotImplementedError

    def cartella(self, volume: str) -> str | None:
        raise NotImplementedError

    def _sposta(self, percorso: str) -> Mossa:
        raise NotImplementedError

    @staticmethod
    def _problema(codice: str) -> tuple[str, str]:
        return codice, PROBLEMI[codice]

    def problema(self, cartella: str, voci: list[tuple[str, int]], byte: int,
                 gia: int = 0) -> tuple[str, str] | None:
        try:
            return self._esamina(cartella, voci, byte, gia)
        except (OSError, ValueError, AttributeError):
            return self._problema("cestino_sconosciuto")

    def _esamina(self, cartella: str, voci: list[tuple[str, int]], byte: int,
                 gia: int) -> tuple[str, str] | None:
        volume = self.volume(cartella)
        if volume is None:
            return self._problema("disco_strano")
        tipo = self.tipo(volume)
        if tipo == CHIAVETTA:
            return self._problema("non_nel_cestino_chiavetta")
        if tipo == RETE:
            return self._problema("disco_di_rete")
        if tipo != FISSO:
            return self._problema("disco_strano")
        if (self.sistema(volume) or "").upper() not in SISTEMI:
            return self._problema("sistema_strano")
        for origine, _ in voci:
            altro = self.volume(origine)
            if altro is None or not _uguali(altro, volume):
                return self._problema("disco_strano")
        capienza = self.capienza(volume)
        if capienza.spento:
            return self._problema("cestino_spento")
        if capienza.massimo is None:
            return self._problema("cestino_sconosciuto")
        if byte > MARGINE * capienza.massimo:
            return self._problema("troppo_grande")
        usato = self.usato(volume)
        if usato is None:
            return self._problema("cestino_sconosciuto")
        if usato + gia + byte > MARGINE * capienza.massimo:
            return self._problema("cestino_pieno")
        dove = self.cartella(volume)
        if dove is None:
            return self._problema("cestino_sconosciuto")
        for origine, piu_lungo in voci:
            resto = _resto(volume, origine)
            nomi = [nome for nome in re.split(r"[\\/]", resto or "") if nome]
            if not nomi or any(nome.endswith((".", " ")) for nome in nomi):
                return self._problema("percorso_strano")
            estensione = os.path.splitext(nomi[-1])[1]
            nel_cestino = len(os.path.join(dove, "$R" + "X" * CASUALI + estensione))
            if max(len(origine), nel_cestino) + piu_lungo > LUNGO:
                return self._problema("percorso_lungo")
        return None

    def butta(self, percorso: str) -> Mossa:
        return self._sposta(percorso)

    def leggi(self, info: str) -> Buttato | None:
        nome = os.path.basename(info)
        if not nome[:2].upper() == "$I":
            return None
        try:
            with open(percorso_lungo(info), "rb") as file:
                grezzi = file.read(INFO_MASSIMA + 1)
        except FileNotFoundError:
            return None
        if len(grezzi) > INFO_MASSIMA:
            return None
        letto = leggi_info(grezzi)
        if letto is None:
            return None
        originale, quando, dimensione = letto
        dati = os.path.join(os.path.dirname(info), "$R" + nome[2:])
        return Buttato(nome, originale, quando, dimensione, info, dati)

    def elenca(self, volume: str) -> list[Buttato]:
        dove = self.cartella(volume)
        if dove is None:
            raise OSError("cestino sconosciuto")
        try:
            with os.scandir(percorso_lungo(dove)) as voci:
                nomi = sorted(voce.name for voce in voci)
        except FileNotFoundError:
            return []
        buttati = []
        for nome in nomi:
            if nome[:2].upper() != "$I":
                continue
            try:
                buttato = self.leggi(os.path.join(dove, nome))
            except OSError:
                continue
            if buttato is not None:
                buttati.append(buttato)
        return buttati

    @staticmethod
    def identita(percorso: str) -> tuple[int, int] | None:
        try:
            stato = os.lstat(percorso_lungo(percorso))
        except FileNotFoundError:
            return None
        return stato.st_ino, stato.st_dev

    def _scegli(self, candidati, originale: str, identita: tuple,
                dopo: float) -> Buttato | None:
        trovati = [buttato for buttato in candidati
                   if _uguali(buttato.originale, originale) and buttato.quando >= dopo
                   and self.identita(buttato.dati) == identita]
        if not trovati:
            return None
        return max(trovati, key=lambda buttato: buttato.quando)

    def trova(self, volume: str, originale: str, identita, dopo: float,
              suggerito: str | None = None) -> Buttato | None:
        identita = tuple(identita)
        dove = self.cartella(volume)
        if dove is None:
            raise OSError("cestino sconosciuto")
        nome = os.path.basename(suggerito or "")
        if nome[:2].upper() == "$R" and stesso_percorso(os.path.dirname(suggerito), dove):
            buttato = self.leggi(os.path.join(dove, "$I" + nome[2:]))
            if buttato is not None:
                trovato = self._scegli([buttato], originale, identita, dopo)
                if trovato is not None:
                    return trovato
        return self._scegli(self.elenca(volume), originale, identita, dopo)

    def pezzi(self, volume: str, origine: str, dopo: float) -> list[Buttato]:
        return [buttato for buttato in self.elenca(volume)
                if buttato.quando >= dopo and _resto(origine, buttato.originale) is not None]


class CestinoAssente(Cestino):

    def volume(self, percorso: str) -> str | None:
        return None

    def tipo(self, volume: str) -> str:
        return STRANO

    def sistema(self, volume: str) -> str | None:
        return None

    def capienza(self, volume: str) -> Capienza:
        return Capienza(None, True)

    def usato(self, volume: str) -> int | None:
        return None

    def pulizia(self) -> int | None:
        return None

    def cartella(self, volume: str) -> str | None:
        return None

    def problema(self, cartella: str, voci, byte: int,
                 gia: int = 0) -> tuple[str, str] | None:
        return self._problema("senza_cestino")

    def _sposta(self, percorso: str) -> Mossa:
        return Mossa(False, None, "senza_cestino")


def _basi(percorso) -> tuple[str, ...]:
    return tuple(dict.fromkeys((os.path.abspath(os.fspath(percorso)), _vero(percorso))))


def _guid(testo: str):
    import ctypes

    return (ctypes.c_ubyte * 16).from_buffer_copy(uuid.UUID(testo).bytes_le)


def _kernel32():
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetVolumePathNameW.restype = wintypes.BOOL
    kernel32.GetVolumePathNameW.argtypes = (wintypes.LPCWSTR, wintypes.LPWSTR,
                                            wintypes.DWORD)
    kernel32.GetVolumeInformationW.restype = wintypes.BOOL
    kernel32.GetVolumeInformationW.argtypes = (
        wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD, wintypes.LPDWORD,
        wintypes.LPDWORD, wintypes.LPDWORD, wintypes.LPWSTR, wintypes.DWORD)
    kernel32.GetDriveTypeW.restype = wintypes.UINT
    kernel32.GetDriveTypeW.argtypes = (wintypes.LPCWSTR,)
    kernel32.GetVolumeNameForVolumeMountPointW.restype = wintypes.BOOL
    kernel32.GetVolumeNameForVolumeMountPointW.argtypes = (
        wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD)
    kernel32.GetDiskFreeSpaceExW.restype = wintypes.BOOL
    kernel32.GetDiskFreeSpaceExW.argtypes = (
        wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_ulonglong),
        ctypes.POINTER(ctypes.c_ulonglong), ctypes.POINTER(ctypes.c_ulonglong))
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.GetCurrentProcess.argtypes = ()
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.LocalFree.restype = ctypes.c_void_p
    kernel32.LocalFree.argtypes = (ctypes.c_void_p,)
    return kernel32


def _registro(radice, percorso: str, nome: str) -> int | None:
    import winreg

    try:
        with winreg.OpenKey(radice, percorso) as chiave:
            valore, tipo = winreg.QueryValueEx(chiave, nome)
    except OSError:
        return None
    if tipo in (winreg.REG_DWORD, winreg.REG_QWORD) and isinstance(valore, int):
        return valore
    return None


def _chiama(oggetto, indice: int, tipi, *valori, risultato=None) -> int:
    import ctypes

    tabella = ctypes.cast(oggetto, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    funzione = ctypes.WINFUNCTYPE(risultato or ctypes.c_long, ctypes.c_void_p,
                                  *tipi)(tabella[indice])
    return funzione(oggetto, *valori)


def _rilascia(oggetto) -> None:
    import ctypes

    if oggetto is not None and oggetto.value:
        _chiama(oggetto, 2, (), risultato=ctypes.c_ulong)


def _percorso_di(elemento) -> str | None:
    import ctypes
    from ctypes import wintypes

    ole32 = ctypes.WinDLL("ole32")
    ole32.CoTaskMemFree.restype = None
    ole32.CoTaskMemFree.argtypes = (ctypes.c_void_p,)
    uscita = ctypes.c_void_p()
    esito = _chiama(elemento, 5, (wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p)),
                    PERCORSO_VERO, ctypes.byref(uscita))
    if esito < 0 or not uscita.value:
        return None
    try:
        return ctypes.wstring_at(uscita.value)
    finally:
        ole32.CoTaskMemFree(uscita)


def _ascoltatore(atteso: str, appunti: dict):
    import ctypes
    from ctypes import wintypes

    hr = ctypes.c_long
    pv = ctypes.c_void_p
    dw = wintypes.DWORD
    conti = ctypes.c_ulong
    funzione = ctypes.WINFUNCTYPE
    noti = {bytes(_guid(IUNKNOWN)), bytes(_guid(IPROGRESSO))}

    def chiedi(questo, codice, uscita):
        try:
            puntatore = ctypes.cast(uscita, ctypes.POINTER(ctypes.c_void_p))
            if ctypes.string_at(codice, 16) in noti:
                puntatore[0] = questo
                return S_OK
            puntatore[0] = None
        except Exception:
            pass
        return E_NOINTERFACE

    def prima_di_cancellare(questo, flags, elemento):
        try:
            percorso = _percorso_di(ctypes.c_void_p(elemento)) if elemento else None
            esito = permesso(flags, percorso, atteso)
            appunti["prima"].append((int(flags), esito))
            return esito
        except Exception:
            return E_ABORT

    def dopo_cancellato(questo, flags, elemento, esito, nuovo):
        try:
            dove = _percorso_di(ctypes.c_void_p(nuovo)) if nuovo else None
            appunti["dopo"].append((int(esito), dove))
        except Exception:
            appunti["dopo"].append((int(E_ABORT), None))
        return S_OK

    def no(*argomenti):
        return E_ABORT

    def si(*argomenti):
        return S_OK

    def uno(*argomenti):
        return 1

    forme = [
        (funzione(hr, pv, pv, pv), chiedi),
        (funzione(conti, pv), uno),
        (funzione(conti, pv), uno),
        (funzione(hr, pv), si),
        (funzione(hr, pv, hr), si),
        (funzione(hr, pv, dw, pv, pv), no),
        (funzione(hr, pv, dw, pv, pv, hr, pv), si),
        (funzione(hr, pv, dw, pv, pv, pv), no),
        (funzione(hr, pv, dw, pv, pv, pv, hr, pv), si),
        (funzione(hr, pv, dw, pv, pv, pv), no),
        (funzione(hr, pv, dw, pv, pv, pv, hr, pv), si),
        (funzione(hr, pv, dw, pv), prima_di_cancellare),
        (funzione(hr, pv, dw, pv, hr, pv), dopo_cancellato),
        (funzione(hr, pv, dw, pv, pv), no),
        (funzione(hr, pv, dw, pv, pv, pv, dw, hr, pv), si),
        (funzione(hr, pv, ctypes.c_uint, ctypes.c_uint), si),
        (funzione(hr, pv), si),
        (funzione(hr, pv), si),
        (funzione(hr, pv), si),
    ]
    funzioni = [forma(fatto) for forma, fatto in forme]
    tabella = (ctypes.c_void_p * len(funzioni))(
        *[ctypes.cast(fatto, ctypes.c_void_p).value for fatto in funzioni])
    oggetto = (ctypes.c_void_p * 1)(ctypes.addressof(tabella))
    return oggetto, (funzioni, tabella, oggetto)


def _ricicla(percorso: str, appunti: dict) -> None:
    import ctypes
    from ctypes import wintypes

    ole32 = ctypes.WinDLL("ole32")
    shell32 = ctypes.WinDLL("shell32")
    ole32.CoInitializeEx.restype = ctypes.c_long
    ole32.CoInitializeEx.argtypes = (ctypes.c_void_p, wintypes.DWORD)
    ole32.CoUninitialize.restype = None
    ole32.CoUninitialize.argtypes = ()
    ole32.CoCreateInstance.restype = ctypes.c_long
    ole32.CoCreateInstance.argtypes = (ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD,
                                       ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p))
    shell32.SHCreateItemFromParsingName.restype = ctypes.c_long
    shell32.SHCreateItemFromParsingName.argtypes = (
        wintypes.LPCWSTR, ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p))
    if ole32.CoInitializeEx(None, 0x2 | 0x4) < 0:
        appunti["codice"] = "com"
        return
    try:
        operazione = ctypes.c_void_p()
        if (ole32.CoCreateInstance(ctypes.byref(_guid(OPERAZIONE)), None, TUTTI_I_CONTESTI,
                                   ctypes.byref(_guid(IFILEOPERATION)),
                                   ctypes.byref(operazione)) < 0 or not operazione.value):
            appunti["codice"] = "com"
            return
        try:
            elemento = ctypes.c_void_p()
            if (shell32.SHCreateItemFromParsingName(
                    percorso, None, ctypes.byref(_guid(ISHELLITEM)),
                    ctypes.byref(elemento)) < 0 or not elemento.value):
                appunti["codice"] = "elemento"
                return
            try:
                vero = _percorso_di(elemento)
                if vero is None or not stesso_percorso(vero, percorso):
                    appunti["codice"] = "percorso_strano"
                    return
                ascoltatore, tieni = _ascoltatore(percorso, appunti)
                biglietto = wintypes.DWORD()
                if _chiama(operazione, 3, (ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD)),
                           ctypes.addressof(ascoltatore), ctypes.byref(biglietto)) < 0:
                    appunti["codice"] = "com"
                    return
                try:
                    if (_chiama(operazione, 5, (wintypes.DWORD,), OPZIONI) < 0
                            or _chiama(operazione, 18, (ctypes.c_void_p, ctypes.c_void_p),
                                       elemento, None) < 0):
                        appunti["codice"] = "com"
                        return
                    appunti["esito"] = _chiama(operazione, 21, ())
                    interrotte = wintypes.BOOL()
                    _chiama(operazione, 22, (ctypes.POINTER(wintypes.BOOL),),
                            ctypes.byref(interrotte))
                    appunti["interrotte"] = bool(interrotte.value)
                finally:
                    _chiama(operazione, 4, (wintypes.DWORD,), biglietto)
                    del tieni
            finally:
                _rilascia(elemento)
        finally:
            _rilascia(operazione)
    finally:
        ole32.CoUninitialize()


class CestinoWindows(Cestino):

    def __init__(self):
        self._sid: str | None = None

    def volume(self, percorso: str) -> str | None:
        import ctypes

        buffer = ctypes.create_unicode_buffer(1024)
        if not _kernel32().GetVolumePathNameW(os.fspath(percorso), buffer, 1024):
            return None
        return buffer.value or None

    def tipo(self, volume: str) -> str:
        tipo = {3: FISSO, 2: CHIAVETTA, 4: RETE}.get(_kernel32().GetDriveTypeW(volume),
                                                     STRANO)
        if tipo == FISSO and not re.fullmatch(r"[A-Za-z]:\\", volume):
            return STRANO
        return tipo

    def sistema(self, volume: str) -> str | None:
        import ctypes

        nome = ctypes.create_unicode_buffer(300)
        if not _kernel32().GetVolumeInformationW(volume, None, 0, None, None, None, nome,
                                                 300):
            return None
        return nome.value or None

    def _codice(self, volume: str) -> str | None:
        import ctypes

        buffer = ctypes.create_unicode_buffer(64)
        if not _kernel32().GetVolumeNameForVolumeMountPointW(volume, buffer, 64):
            return None
        trovato = re.search(r"\{[0-9A-Fa-f-]{36}\}", buffer.value)
        return trovato.group(0) if trovato else None

    def _totale(self, volume: str) -> int | None:
        import ctypes

        totale = ctypes.c_ulonglong()
        if not _kernel32().GetDiskFreeSpaceExW(volume, None, ctypes.byref(totale), None):
            return None
        return int(totale.value) or None

    def capienza(self, volume: str) -> Capienza:
        import winreg

        spento = False
        massimi = []
        totale = self._totale(volume)
        for radice in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            if _registro(radice, POLITICHE, "NoRecycleFiles") == 1:
                spento = True
            percento = _registro(radice, POLITICHE, "RecycleBinSize")
            if percento is not None and totale:
                massimi.append(totale * min(percento, 100) // 100)
        if _registro(winreg.HKEY_CURRENT_USER, BITBUCKET, "NukeOnDelete") == 1:
            spento = True
        codice = self._codice(volume)
        if codice is None:
            return Capienza(None, spento)
        chiave = BITBUCKET + "\\Volume\\" + codice
        if _registro(winreg.HKEY_CURRENT_USER, chiave, "NukeOnDelete") == 1:
            spento = True
        capienza = _registro(winreg.HKEY_CURRENT_USER, chiave, "MaxCapacity")
        if capienza is not None:
            massimi.append(capienza * MB)
        if not massimi and totale:
            massimi.append(totale * PERCENTO // 100)
        return Capienza(min(massimi) if massimi else None, spento)

    def usato(self, volume: str) -> int | None:
        import ctypes
        from ctypes import wintypes

        class Informazioni(ctypes.Structure):
            _pack_ = 8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 1
            _fields_ = [("cbSize", wintypes.DWORD), ("i64Size", ctypes.c_longlong),
                        ("i64NumItems", ctypes.c_longlong)]

        shell32 = ctypes.WinDLL("shell32")
        shell32.SHQueryRecycleBinW.restype = ctypes.c_long
        shell32.SHQueryRecycleBinW.argtypes = (wintypes.LPCWSTR, ctypes.c_void_p)
        informazioni = Informazioni()
        informazioni.cbSize = ctypes.sizeof(Informazioni)
        if shell32.SHQueryRecycleBinW(volume, ctypes.byref(informazioni)) < 0:
            return None
        return max(0, int(informazioni.i64Size))

    def pulizia(self) -> int | None:
        import winreg

        acceso = _registro(winreg.HKEY_CURRENT_USER, SENSORE, "01")
        giorni = _registro(winreg.HKEY_CURRENT_USER, SENSORE, "256")
        if acceso == 1 and giorni:
            return int(giorni)
        return None

    def sid(self) -> str | None:
        if self._sid is not None:
            return self._sid
        import ctypes
        from ctypes import wintypes

        kernel32 = _kernel32()
        advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
        advapi32.OpenProcessToken.restype = wintypes.BOOL
        advapi32.OpenProcessToken.argtypes = (wintypes.HANDLE, wintypes.DWORD,
                                              ctypes.POINTER(wintypes.HANDLE))
        advapi32.GetTokenInformation.restype = wintypes.BOOL
        advapi32.GetTokenInformation.argtypes = (
            wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD))
        advapi32.ConvertSidToStringSidW.restype = wintypes.BOOL
        advapi32.ConvertSidToStringSidW.argtypes = (ctypes.c_void_p,
                                                    ctypes.POINTER(ctypes.c_void_p))
        gettone = wintypes.HANDLE()
        if not advapi32.OpenProcessToken(kernel32.GetCurrentProcess(), 0x0008,
                                         ctypes.byref(gettone)):
            return None
        try:
            lunghezza = wintypes.DWORD()
            advapi32.GetTokenInformation(gettone, 1, None, 0, ctypes.byref(lunghezza))
            if not lunghezza.value:
                return None
            buffer = ctypes.create_string_buffer(lunghezza.value)
            if not advapi32.GetTokenInformation(gettone, 1, buffer, lunghezza,
                                                ctypes.byref(lunghezza)):
                return None
            utente = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_void_p))[0]
            testo = ctypes.c_void_p()
            if not advapi32.ConvertSidToStringSidW(utente, ctypes.byref(testo)):
                return None
            try:
                sid = ctypes.wstring_at(testo.value)
            finally:
                kernel32.LocalFree(testo)
        finally:
            kernel32.CloseHandle(gettone)
        if not re.fullmatch(r"S-1(-\d+)+", sid):
            return None
        self._sid = sid
        return sid

    def cartella(self, volume: str) -> str | None:
        sid = self.sid()
        if sid is None:
            return None
        return os.path.join(volume, CESTINO, sid)

    def _sposta(self, percorso: str) -> Mossa:
        appunti: dict = {"prima": [], "dopo": []}
        filo = threading.Thread(target=self._nel_filo, args=(percorso, appunti),
                                name="archivio-sicuro-cestino-windows", daemon=True)
        filo.start()
        filo.join()
        if "codice" in appunti:
            return Mossa(False, None, appunti["codice"])
        esito = appunti.get("esito", E_ABORT)
        dopo = appunti["dopo"]
        dove = dopo[-1][1] if dopo else None
        fatta = (esito >= 0 and not appunti.get("interrotte", True)
                 and len(dopo) == 1 and dopo[0][0] >= 0 and dove is not None)
        return Mossa(fatta, dove, None if fatta else "rifiutata")

    @staticmethod
    def _nel_filo(percorso: str, appunti: dict) -> None:
        try:
            _ricicla(percorso, appunti)
        except Exception:
            appunti.setdefault("codice", "com")


def cestino_di_sistema() -> Cestino:
    return CestinoWindows() if WINDOWS else CestinoAssente()


class Spedizioniere:

    def __init__(self, cartella: Path, elenco, chiave, chiavetta, cestino: Cestino,
                 quaderno: Quaderno, *, adesso=time.time, orologio=time.time,
                 occupato=None, turno=None, nuvola: bool = False, apri=Lettore,
                 **per_esaminatore):
        self.cartella = Path(cartella)
        self.elenco = elenco
        self._chiave = chiave
        self.cestino = cestino
        self.quaderno = quaderno
        self._adesso = adesso
        self._orologio = orologio
        self._occupato = occupato
        self._turno = turno if turno is not None else contextlib.nullcontext
        self._nuvola = nuvola
        self._apri = apri
        self._uno_alla_volta = threading.Lock()
        self.aspetta = None
        self.esaminatore = Esaminatore(cartella, elenco, chiave, chiavetta, apri=apri,
                                       adesso=adesso, aspetta=self._ferma_se_serve,
                                       **per_esaminatore)
        self.risultati: list[dict] = []

    def _ferma_se_serve(self) -> None:
        if self.aspetta is not None:
            self.aspetta()

    @contextlib.contextmanager
    def _da_solo(self):
        if not self._uno_alla_volta.acquire(blocking=False):
            raise ErroreOfficina(
                "Sto già lavorando sul Cestino: aspetta che finisca.", codice="occupato")
        try:
            yield
        finally:
            self._uno_alla_volta.release()

    def _non_occupato(self) -> None:
        if self._occupato is not None and self._occupato():
            raise ErroreOfficina(
                "L'archivio sta già lavorando: aspetta che finisca e poi riprova.",
                codice="occupato")

    def _voci(self, esame) -> list[tuple[str, dict[str, list]]]:
        return [(relativo, _della_voce(esame.impronta, relativo))
                for relativo in _voci_dentro(esame)]

    @staticmethod
    def _piu_lungo(impronte: dict) -> int:
        return max((len(dentro) + 1 for dentro in impronte if dentro), default=0)

    @staticmethod
    def _conti(impronte: dict) -> tuple[int, int]:
        file = [impronta for impronta in impronte.values() if impronta[0] == metadati.FILE]
        return len(file), sum(impronta[1] for impronta in file)

    def _quanti(self, esame) -> tuple[int, int]:
        conti = [self._conti(impronte) for _, impronte in self._voci(esame)]
        return sum(file for file, _ in conti), sum(byte for _, byte in conti)

    def _problema(self, esame, adesso: float,
                  piano: dict[str, int] | None = None) -> tuple[str, str] | None:
        if not esame.verde:
            return ("rossa",
                    "Questa cartella non ha il via libera: la rossa non si tocca.")
        if not esame.fresco(adesso):
            return ("da_ricontrollare",
                    "Il controllo di questa cartella è di più di 10 minuti fa: rifallo, "
                    "poi la mando nel Cestino.")
        if esame.sincronizzata and not self._nuvola:
            return ("sincronizzata",
                    "Questa cartella è sincronizzata con OneDrive: se la cancello qui, "
                    "sparisce anche dal cloud e dagli altri PC. Non la tocco.")
        voci = self._voci(esame)
        if not voci:
            return ("vuota",
                    "Dentro questa cartella non c'è niente da mandare nel Cestino.")
        if any(not impronte.get("") or not impronte[""][3] for _, impronte in voci):
            return self.cestino._problema("disco_strano")
        if any(nome.endswith((".", " ")) for _, impronte in voci
               for dentro in impronte for nome in dentro.split("/") if dentro):
            return self.cestino._problema("percorso_strano")
        byte = sum(self._conti(impronte)[1] for _, impronte in voci)
        disco = None
        if piano is not None:
            try:
                disco = os.path.normcase(self.cestino.volume(esame.vero) or "")
            except (OSError, ValueError, AttributeError):
                disco = ""
        gia = piano.get(disco, 0) if piano is not None else 0
        problema = self.cestino.problema(
            esame.vero, [(Copiatore._assoluto(esame.vero, relativo),
                          self._piu_lungo(impronte)) for relativo, impronte in voci], byte,
            gia)
        if problema is None and piano is not None:
            piano[disco] = gia + byte
        return problema

    def _collaudo(self, buone: list) -> tuple[str, str] | None:
        collaudo = self.quaderno.collaudo
        if collaudo == DA_GUARDARE:
            return ("prima_guarda",
                    "Prima estrai dall'archivio la cartella di prova e guardala con i tuoi "
                    "occhi, poi premi «Ho controllato».")
        if collaudo == DA_FARE and (len(buone) > 1 or any(
                file > PROVA_FILE or byte > PROVA_BYTE
                for file, byte in map(self._quanti, buone))):
            return ("prima_una_piccola",
                    f"La prima volta si manda nel Cestino una cartella sola e piccola, al "
                    f"massimo {PROVA_FILE} file e {_quanto(PROVA_BYTE)}.")
        return None

    def riepilogo(self, esami) -> dict:
        adesso = self._adesso()
        buone, fuori = [], []
        piano: dict[str, int] = {}
        for esame in esami:
            problema = self._problema(esame, adesso, piano)
            if problema is None:
                buone.append(esame)
            else:
                fuori.append({"cartella": esame.cartella, "codice": problema[0],
                              "messaggio": problema[1]})
        conti = [self._quanti(esame) for esame in buone]
        file = sum(quanti for quanti, _ in conti)
        byte = sum(quanti for _, quanti in conti)
        cartelle = "1 cartella" if len(buone) == 1 else f"{_numero(len(buone))} cartelle"
        frasi = []
        if buone:
            frasi.append(f"Vanno nel Cestino di Windows: {cartelle}, {_numero(file)} "
                         f"file, {_quanto(byte)}.")
            frasi.append(f"Fra {GIORNI} giorni ricontrollo archivio e chiavetta e ti dico "
                         "se puoi svuotare il Cestino.")
            try:
                pulizia = self.cestino.pulizia()
            except (OSError, ValueError, AttributeError):
                pulizia = None
            if pulizia:
                frasi.append(
                    f"Attenzione: Windows svuota da solo il Cestino dopo {pulizia} giorni "
                    "(Sensore memoria). Se vuoi tenerle nel Cestino più a lungo, spegnilo "
                    "in Impostazioni, Sistema, Archiviazione.")
            if self.quaderno.collaudo == DA_FARE:
                frasi.append("È la prima volta: dopo, estrai questa cartella dall'archivio "
                             "e guardala con i tuoi occhi.")
        collaudo = self._collaudo(buone) if buone else None
        if collaudo is not None:
            frasi.append(collaudo[1])
        return {"cartelle": len(buone), "file": file, "byte": byte, "frasi": frasi,
                "fuori": fuori, "collaudo": self.quaderno.collaudo,
                "si_puo": bool(buone) and collaudo is None and not self.quaderno.problemi}

    def manda(self, esami, parola: str) -> list[dict]:
        if not isinstance(parola, str) or parola.strip().casefold() != PAROLA:
            raise ErroreOfficina("Per mandarle nel Cestino scrivi CANCELLA.",
                                 codice="parola_sbagliata")
        esami = list(esami)
        with self._da_solo():
            self.quaderno._si_scrive()
            self._non_occupato()
            self._riprendi()
            adesso = self._adesso()
            collaudo = self._collaudo([esame for esame in esami
                                       if self._problema(esame, adesso) is None])
            if collaudo is not None:
                raise ErroreOfficina(collaudo[1], codice=collaudo[0])
            risultati: list[dict] = []
            self.risultati = risultati
            with self._turno():
                for posizione, esame in enumerate(esami):
                    try:
                        self._non_occupato()
                        risultati.append(self._una(esame))
                        continue
                    except _Spedita as spedita:
                        risultati.append(spedita.risultato)
                        codice, messaggio = spedita.codice, spedita.messaggio
                    except ErroreOfficina as errore:
                        codice, messaggio = errore.codice, errore.messaggio
                        risultati.append(_non_toccata(esame.cartella, codice, messaggio))
                        if codice not in GLOBALI:
                            continue
                    for altro in esami[posizione + 1:]:
                        risultati.append(_non_toccata(altro.cartella, codice, messaggio))
                    break
            self._segna_la_prova()
            return risultati

    def _segna_la_prova(self) -> None:
        if self.quaderno.collaudo != DA_FARE or self.quaderno.problemi:
            return
        for spedizione in self.quaderno.spedizioni():
            if any(voce["esito"] == NEL_CESTINO for voce in spedizione["voci"]):
                try:
                    self.quaderno.metti_collaudo(DA_GUARDARE, spedizione["id"])
                except ErroreOfficina:
                    pass
                return

    def _una(self, esame) -> dict:
        problema = self._problema(esame, self._adesso())
        if problema is not None:
            return _non_toccata(esame.cartella, *problema)
        cambiati = self.esaminatore.ancora_uguale(esame)
        if cambiati:
            return _non_toccata(
                esame.cartella, "cambiata",
                "Dopo il controllo qualcosa qui dentro è cambiato: rifai il controllo.")
        voci = self._voci(esame)
        try:
            volume = self.cestino.volume(esame.vero)
        except (OSError, ValueError):
            volume = None
        if not volume:
            return _non_toccata(esame.cartella, *self.cestino._problema("disco_strano"))
        file, byte = self._quanti(esame)
        id = secrets.token_hex(8)
        spedizione = {
            "id": id, "quando": self._adesso(), "partenza": None,
            "cartella": esame.cartella, "vero": esame.vero,
            "solo_dentro": esame.solo_dentro, "file": file, "byte": byte,
            "custodita": False, "ricontrollo": None, "voci": []}
        lista = {"id": id, "voci": []}
        for relativo, impronte in voci:
            quanti, peso = self._conti(impronte)
            spedizione["voci"].append({
                "origine": Copiatore._assoluto(esame.vero, relativo),
                "relativo": relativo, "volume": volume,
                "identita": [impronte[""][3], impronte[""][4]], "file": quanti,
                "byte": peso, "esito": IN_PARTENZA, "dove": None, "info": None,
                "nome": None})
            lista["voci"].append({"impronte": impronte, "posti": {
                chiave: dove for chiave, dove in sorted(esame.dove_posti.items())
                if _nella_voce(dove, relativo)}})
        spedizione["partenza"] = self._orologio()
        self.quaderno.scrivi_lista(id, lista)
        self.quaderno.metti(spedizione)
        for voce, dettagli in zip(spedizione["voci"], lista["voci"], strict=True):
            try:
                mossa = self.cestino.butta(voce["origine"])
            except Exception:
                mossa = Mossa(False, None, "errore")
            self._accerta(voce, dettagli, spedizione["partenza"], mossa.dove)
        try:
            self.quaderno.metti(spedizione)
            self._custodisci(spedizione, lista)
        except ErroreOfficina as errore:
            raise self._spedita(spedizione, errore.codice, errore.messaggio) from None
        except (OSError, ValueError, sqlite3.Error):
            raise self._spedita(spedizione, "quaderno_non_salvato", (
                "Non riesco a scrivere sul disco dell'Archivio sicuro: non tocco "
                "niente.")) from None
        return self._risultato(spedizione)

    def _spedita(self, spedizione: dict, codice: str, messaggio: str) -> _Spedita:
        risultato = self._risultato(spedizione)
        risultato["codice"] = codice
        risultato["messaggio"] = (
            f"{risultato['messaggio']} Però non sono riuscito a segnarlo sul disco "
            "dell'Archivio sicuro: lo segno da solo appena torna a funzionare. Intanto le "
            "altre cartelle non le tocco.")
        return _Spedita(risultato, codice, messaggio)

    def _risultato(self, spedizione: dict) -> dict:
        stato = stato_di(spedizione)
        dentro = [voce for voce in spedizione["voci"] if voce["esito"] == NEL_CESTINO]
        frasi = {
            NEL_CESTINO: "È nel Cestino di Windows, e ho controllato che c'è tutta.",
            IN_PARTE: ("Una parte è nel Cestino; il resto non ci è andato ed è rimasto al "
                       "suo posto."),
            NON_PARTITA: "Windows non l'ha mandata nel Cestino: è rimasta al suo posto.",
            DA_GUARDARE: ("Qualcosa non torna: guarda nel Cestino e rimetti al suo posto "
                          "quello che c'è, poi rifai il controllo."),
            IN_PARTENZA: ("Non riesco ancora a capire se è andata nel Cestino: "
                          "ricontrollo appena posso."),
        }
        return {"cartella": spedizione["cartella"], "esito": stato,
                "codice": None if stato == NEL_CESTINO else stato,
                "messaggio": frasi[stato], "spedizione": spedizione["id"],
                "file": sum(voce["file"] for voce in dentro),
                "byte": sum(voce["byte"] for voce in dentro), "nel_cestino": len(dentro)}

    def _accerta(self, voce: dict, dettagli: dict | None, partenza: float,
                 suggerito: str | None) -> None:
        origine = voce["origine"]
        identita = tuple(voce["identita"])
        try:
            qui = self.cestino.identita(origine)
        except (OSError, ValueError):
            return
        try:
            if qui == identita:
                pezzi = self.cestino.pezzi(voce["volume"], origine, partenza - PRIMA)
                voce["esito"] = A_META if pezzi else NON_PARTITA
                return
            buttato = self.cestino.trova(voce["volume"], origine, identita,
                                         partenza - PRIMA, suggerito)
        except (OSError, ValueError):
            return
        if buttato is None:
            voce["esito"] = PERSA
            return
        voce["dove"] = buttato.dati
        voce["info"] = buttato.info
        voce["nome"] = buttato.nome
        uguale = dettagli is not None and self._uguale(buttato.dati, dettagli["impronte"])
        voce["esito"] = NEL_CESTINO if uguale else DIVERSA

    def _impronta(self, assoluto: str):
        try:
            stato = os.lstat(percorso_lungo(assoluto))
            return stato, list(self.esaminatore._impronta(assoluto, stato))
        except Exception:
            raise _Altro from None

    def _uguale(self, percorso: str, impronte: dict) -> bool:
        try:
            stato, cima = self._impronta(percorso)
        except _Altro:
            return False
        atteso = impronte.get("")
        if atteso is None or cima[:5] != list(atteso[:5]):
            return False
        visti = {""}
        if metadati.tipo_di(stato) == metadati.CARTELLA:
            pila = [""]
            while pila:
                relativo = pila.pop()
                try:
                    with os.scandir(percorso_lungo(
                            Copiatore._assoluto(percorso, relativo))) as voci:
                        nomi = sorted(voce.name for voce in voci)
                except OSError:
                    return False
                for nome in nomi:
                    figlio = f"{relativo}/{nome}" if relativo else nome
                    atteso = impronte.get(figlio)
                    if atteso is None:
                        return False
                    try:
                        stato_figlio, impronta = self._impronta(
                            Copiatore._assoluto(percorso, figlio))
                    except _Altro:
                        return False
                    if impronta != list(atteso):
                        return False
                    visti.add(figlio)
                    if metadati.tipo_di(stato_figlio) == metadati.CARTELLA:
                        pila.append(figlio)
        return visti == set(impronte)

    def _custodisci(self, spedizione: dict, lista: dict) -> None:
        if spedizione["custodita"] or any(voce["esito"] == IN_PARTENZA
                                          for voce in spedizione["voci"]):
            return
        fatti = []
        for voce, dettagli in zip(spedizione["voci"], lista["voci"], strict=True):
            if voce["esito"] != NEL_CESTINO:
                continue
            for chiave in sorted(dettagli["posti"]):
                posto = self.elenco.posto(chiave)
                if posto is None or posto.sparito is not None or CUSTODITO in posto.segni:
                    continue
                attuale = self.elenco.attuale(posto.radice, posto.percorso)
                if attuale is None or attuale.chiave != chiave:
                    continue
                fatti.append(registro.fatto_posto(
                    posto.radice, posto.percorso, posto.tipo, posto.contenuto,
                    posto.metadati, segni=(*posto.segni, CUSTODITO), chiave=chiave,
                    quando=posto.visto))
        if fatti:
            self.elenco.registra(fatti)
            self.elenco.scrivi_nota(fatti)
            self.elenco.salva()
        spedizione["custodita"] = True
        self.quaderno.metti(spedizione)

    def riprendi(self) -> list[str]:
        with self._da_solo():
            return self._riprendi()

    def _riprendi(self) -> list[str]:
        if self.quaderno.problemi:
            return []
        riprese = []
        for spedizione in self.quaderno.spedizioni():
            sospese = [voce for voce in spedizione["voci"] if voce["esito"] == IN_PARTENZA]
            if not sospese and spedizione["custodita"]:
                continue
            lista = self.quaderno.leggi_lista(spedizione["id"])
            if lista is not None and len(lista["voci"]) != len(spedizione["voci"]):
                lista = None
            if sospese:
                for posizione, voce in enumerate(spedizione["voci"]):
                    if voce["esito"] == IN_PARTENZA:
                        dettagli = None if lista is None else lista["voci"][posizione]
                        self._accerta(voce, dettagli, spedizione["partenza"] or 0.0, None)
                self.quaderno.metti(spedizione)
            if lista is not None:
                self._custodisci(spedizione, lista)
            riprese.append(spedizione["id"])
        self._segna_la_prova()
        return riprese

    def ho_controllato(self) -> None:
        if self.quaderno.collaudo != DA_GUARDARE:
            raise ErroreOfficina("Non c'è nessuna cartella di prova da guardare.",
                                 codice="niente_da_guardare")
        self.quaderno.metti_collaudo(FATTO)

    def da_ricontrollare(self) -> list[dict]:
        adesso = self._adesso()
        dovute = []
        for spedizione in self.quaderno.spedizioni():
            ricontrollo = spedizione.get("ricontrollo")
            if (spedizione["quando"] + ATTESA <= adesso
                    and any(voce["esito"] == NEL_CESTINO for voce in spedizione["voci"])
                    and (ricontrollo is None or ricontrollo["esito"] == ASPETTA)):
                dovute.append(spedizione)
        return dovute

    def presenze(self, spedizione: dict) -> bool:
        cambiata = False
        for voce in spedizione["voci"]:
            if voce["esito"] != NEL_CESTINO:
                continue
            identita = tuple(voce["identita"])
            try:
                if voce["dove"] and self.cestino.identita(voce["dove"]) == identita:
                    continue
                if self.cestino.identita(voce["origine"]) is not None:
                    voce["esito"] = TORNATA
                    cambiata = True
                    continue
                buttato = self.cestino.trova(voce["volume"], voce["origine"], identita,
                                             float("-inf"))
            except (OSError, ValueError):
                continue
            if buttato is None:
                voce["esito"] = SVUOTATA
            else:
                voce["dove"] = buttato.dati
                voce["info"] = buttato.info
                voce["nome"] = buttato.nome
            cambiata = True
        return cambiata

    def ricontrolla(self, id: str) -> dict:
        with self._da_solo():
            spedizione = self.quaderno.spedizione(id)
            if spedizione is None:
                raise ErroreOfficina("Questa spedizione non la conosco.",
                                     codice="spedizione_sconosciuta")
            self.quaderno._si_scrive()
            self._non_occupato()
            with self._turno():
                self.presenze(spedizione)
                esito = self._ricontrollo(spedizione)
            esito["quando"] = self._adesso()
            spedizione["ricontrollo"] = esito
            self.quaderno.metti(spedizione)
            return copy.deepcopy(esito)

    @staticmethod
    def _aspetta(codice: str, messaggio: str, **altro) -> dict:
        return {"esito": ASPETTA, "codice": codice, "messaggio": messaggio,
                "da_controllare": [], "da_rileggere": [], **altro}

    def _ricontrollo(self, spedizione: dict) -> dict:
        lista = self.quaderno.leggi_lista(spedizione["id"])
        if lista is None or len(lista["voci"]) != len(spedizione["voci"]):
            return self._aspetta(
                "lista_rovinata",
                "Non riesco più a leggere cosa avevo mandato nel Cestino: prima di "
                "svuotarlo, estrai le cartelle dall'archivio e controllale.")
        posti: set[str] = set()
        for voce, dettagli in zip(spedizione["voci"], lista["voci"], strict=True):
            if voce["esito"] in (NEL_CESTINO, SVUOTATA):
                posti.update(dettagli["posti"])
        if self._ancora_da_guardare(spedizione):
            return self._aspetta(
                "da_guardare",
                "Quando l'ho mandata nel Cestino qualcosa non tornava: guarda nel Cestino, "
                "rimetti al suo posto quello che c'è e rifai il controllo. Finché è lì, non "
                "svuotare il Cestino.")
        if not any(voce["esito"] == NEL_CESTINO for voce in spedizione["voci"]):
            return {"esito": FINITA, "codice": None,
                    "messaggio": "Nel Cestino non c'è più niente di questa cartella.",
                    "da_controllare": [], "da_rileggere": []}
        try:
            riserva = self.esaminatore._prima()
        except ErroreOfficina as errore:
            return self._aspetta(errore.codice, errore.messaggio)
        try:
            return self._ricontrolla_con(riserva, sorted(posti))
        except ErroreOfficina as errore:
            return self._aspetta(errore.codice, errore.messaggio)
        finally:
            riserva.elenco.chiudi()

    def _ancora_da_guardare(self, spedizione: dict) -> bool:
        for voce in spedizione["voci"]:
            if voce["esito"] not in DA_GUARDARE_ESITI:
                continue
            try:
                if voce["esito"] == A_META:
                    if self.cestino.pezzi(voce["volume"], voce["origine"],
                                          (spedizione["partenza"] or 0.0) - PRIMA):
                        return True
                    continue
                identita = tuple(voce["identita"])
                if voce["dove"] and self.cestino.identita(voce["dove"]) == identita:
                    return True
                if self.cestino.trova(voce["volume"], voce["origine"], identita,
                                      float("-inf")) is not None:
                    return True
            except (OSError, ValueError):
                return True
        return False

    def _ricontrolla_con(self, riserva, posti: list[str]) -> dict:
        contenuti: set[str] = set()
        primo = None
        for chiave in posti:
            self._ferma_se_serve()
            qui = self.elenco.posto(chiave)
            la = riserva.elenco.posto(chiave)
            if qui is None:
                primo = primo or ("archivio_cambiato", "Nell'archivio manca qualcosa che "
                                  "avevo mandato nel Cestino.")
                continue
            if (la is None or la.tipo != qui.tipo or la.contenuto != qui.contenuto
                    or dict(riserva.elenco.flussi_di(chiave))
                    != dict(self.elenco.flussi_di(chiave))):
                primo = primo or ("chiavetta_da_aggiornare",
                                  "Sulla chiavetta manca qualcosa: aggiornala e poi "
                                  "ricontrollo.")
            if qui.contenuto is not None:
                contenuti.add(qui.contenuto)
            contenuti.update(numero for _, numero in self.elenco.flussi_di(chiave))
        da_controllare, da_rileggere = [], []
        for numero in sorted(contenuti):
            self._ferma_se_serve()
            informazioni = self.elenco.contenuto(numero)
            if informazioni is None or informazioni["stato"] not in STATI_BUONI:
                da_controllare.append(numero)
                continue
            if not self._sano(registro.percorso_contenuto(self.cartella, numero), numero,
                              informazioni):
                da_controllare.append(numero)
                continue
            if (not self.esaminatore._stesso_contenuto(riserva.elenco, numero)
                    or not self._sano(registro.percorso_contenuto(
                        riserva.disco / CARTELLA, numero), numero, informazioni)):
                da_rileggere.append(numero)
        self.esaminatore._archivio_c_e()
        self.esaminatore._ancora_attaccata(riserva.disco, riserva.identita)
        if da_controllare:
            primo = ("archivio_rovinato", "Nell'archivio c'è qualcosa di rovinato: prima "
                     "lo riparo, poi ricontrollo. Non svuotare il Cestino.")
        elif da_rileggere and primo is None:
            primo = ("chiavetta_rovinata", "Sulla chiavetta c'è qualcosa che non torna: "
                     "aggiornala, poi ricontrollo. Non svuotare il Cestino.")
        if primo is not None:
            return self._aspetta(*primo, da_controllare=da_controllare,
                                 da_rileggere=da_rileggere)
        return {"esito": SVUOTABILE, "codice": None,
                "messaggio": ("Ho ricontrollato: tutto è nell'archivio e sulla chiavetta, "
                              "byte per byte. Puoi svuotare il Cestino."),
                "da_controllare": [], "da_rileggere": []}

    def _sano(self, percorso: Path, numero: str, informazioni: dict) -> bool:
        try:
            with self._apri(percorso, True) as lettore:
                return formato.controlla(
                    lettore, self._chiave, numero=bytes.fromhex(numero),
                    testa=informazioni["testa"],
                    impronte={"blake2b": informazioni["blake2b"],
                              "sha256": informazioni["sha256"]},
                    ogni_pezzo=lambda pezzo: self._ferma_se_serve()).buono
        except (ErroreOfficina, OSError, ValueError):
            return False


class Mandata(Sottofondo):

    nome = "archivio-sicuro-cestino"

    def __init__(self, spedizioniere: Spedizioniere, *, sveglio=sveglia.sveglio,
                 rallenta=None, pausa_se_usi: float = PAUSA_SE_USI):
        super().__init__(sveglio=sveglio, rallenta=rallenta, pausa_se_usi=pausa_se_usi)
        self.spedizioniere = spedizioniere
        self.risultati: list[dict] = []

    def avvia(self, esami, parola: str) -> bool:
        if not isinstance(parola, str) or parola.strip().casefold() != PAROLA:
            raise ErroreOfficina("Per mandarle nel Cestino scrivi CANCELLA.",
                                 codice="parola_sbagliata")
        return self._parti(list(esami), parola)

    def _azzera(self) -> None:
        self.risultati = []
        self.spedizioniere.risultati = []

    def _lavora(self, esami, parola: str) -> None:
        self.spedizioniere.aspetta = self._aspetta
        try:
            self.risultati = self.spedizioniere.manda(esami, parola)
        finally:
            self.spedizioniere.aspetta = None

    def istantanea(self) -> dict:
        risultati = self.risultati or list(self.spedizioniere.risultati)
        return {"stato": self.stato, "errore": self.errore, "codice": self.codice,
                "risultati": copy.deepcopy(risultati)}


class Ricontrollo(Sottofondo):

    nome = "archivio-sicuro-cestino-ricontrollo"

    def __init__(self, spedizioniere: Spedizioniere, *, sveglio=sveglia.sveglio,
                 rallenta=None, pausa_se_usi: float = PAUSA_SE_USI):
        super().__init__(sveglio=sveglio, rallenta=rallenta, pausa_se_usi=pausa_se_usi)
        self.spedizioniere = spedizioniere
        self.esiti: dict[str, dict] = {}

    def avvia(self, ids=None) -> bool:
        return self._parti(None if ids is None else list(ids))

    def _azzera(self) -> None:
        self.esiti = {}

    def _lavora(self, ids) -> None:
        self.spedizioniere.aspetta = self._aspetta
        try:
            if ids is None:
                ids = [spedizione["id"] for spedizione
                       in self.spedizioniere.da_ricontrollare()]
            for id in ids:
                self._aspetta()
                self.esiti[id] = self.spedizioniere.ricontrolla(id)
        finally:
            self.spedizioniere.aspetta = None

    def istantanea(self) -> dict:
        return {"stato": self.stato, "errore": self.errore, "codice": self.codice,
                "esiti": copy.deepcopy(self.esiti)}


class Vedetta:

    def __init__(self, elenco, cestino: Cestino, quaderno: Quaderno, *, salta=(),
                 apri=Lettore, avvisa=None, orologio=time.time):
        self.elenco = elenco
        self.cestino = cestino
        self.quaderno = quaderno
        self._salta = tuple(os.fspath(cartella) for cartella in salta)
        self._apri = apri
        self._avvisa = avvisa
        self._orologio = orologio
        self._serratura = threading.RLock()
        self._visti: dict[str, set[str]] = {}
        self._allarmi: list[dict] = quaderno.allarmi()
        self._tentativi: dict[str, int] = {}
        self._dimensioni: set[int] | None = None
        self._basi_salta: list[str] = []
        self.problemi: set[str] = set()
        self.aspetta = None

    def _ferma_se_serve(self) -> None:
        if self.aspetta is not None:
            self.aspetta()

    def allarmi(self) -> list[dict]:
        with self._serratura:
            return [copy.deepcopy(allarme) for allarme in self._allarmi
                    if allarme["stato"] in DA_MOSTRARE]

    def ho_capito(self, id: str) -> bool:
        with self._serratura:
            for allarme in self._allarmi:
                if allarme["id"] == id and allarme["stato"] in DA_MOSTRARE:
                    allarme["stato"] = LASCIATO
                    self._salva_allarme(allarme)
                    return True
        return False

    def _salva_allarme(self, allarme: dict) -> None:
        try:
            self.quaderno.metti_allarme(allarme)
            self.problemi.discard("quaderno_non_salvato")
        except ErroreOfficina:
            self.problemi.add("quaderno_non_salvato")

    def _nostri(self) -> set[str]:
        nostri = set()
        for spedizione in self.quaderno.spedizioni():
            for voce in spedizione["voci"]:
                if voce["esito"] == NEL_CESTINO and voce.get("dove"):
                    nostri.add(os.path.normcase(voce["dove"]))
        return nostri

    def _radici(self) -> dict[str, list[dict]]:
        per_volume: dict[str, list] = {}
        for radice in self.elenco.radici():
            if radice["tolta"]:
                continue
            try:
                volume = self.cestino.volume(radice["percorso"])
                basi = _basi(radice["percorso"])
            except (OSError, ValueError):
                continue
            if volume:
                gruppo = per_volume.setdefault(os.path.normcase(volume), [volume, []])
                gruppo[1].append({**radice, "basi": basi})
        return {volume: radici for volume, radici in per_volume.values()}

    def guarda(self) -> list[dict]:
        nuovi = []
        self._dimensioni = None
        self._basi_salta = []
        for cartella in self._salta:
            try:
                self._basi_salta.extend(_basi(cartella))
            except (OSError, ValueError):
                continue
        nostri = self._nostri()
        for volume, radici in self._radici().items():
            self._ferma_se_serve()
            try:
                buttati = self.cestino.elenca(volume)
                self.problemi.discard("cestino_illeggibile")
            except (OSError, ValueError):
                self.problemi.add("cestino_illeggibile")
                continue
            chiave = os.path.normcase(volume)
            if chiave not in self._visti:
                self._visti[chiave] = self.quaderno.visti(volume)
            visti = self._visti[chiave]
            ancora = set()
            for buttato in buttati:
                segno = buttato.segno
                if segno in visti:
                    ancora.add(segno)
                    continue
                esito = self._esamina(buttato, radici, nostri)
                if esito is None:
                    continue
                ancora.add(segno)
                self._tentativi.pop(segno, None)
                if esito is not False:
                    nuovi.append(esito)
            if ancora != visti:
                self._visti[chiave] = ancora
                try:
                    self.quaderno.metti_visti(volume, ancora)
                    self.problemi.discard("quaderno_non_salvato")
                except ErroreOfficina:
                    self.problemi.add("quaderno_non_salvato")
        self._risolvi()
        return nuovi

    @staticmethod
    def _toccate(originale: str, radici: list[dict], quando: float) -> list[dict]:
        return [radice for radice in radici if quando >= radice["aggiunta"] and any(
            _resto(base, originale) is not None or _resto(originale, base) is not None
            for base in radice["basi"])]

    def _saltato(self, assoluto: str) -> bool:
        return any(_resto(base, assoluto) is not None for base in self._basi_salta)

    def _dove(self, assoluto: str, radici: list[dict]) -> list[tuple[dict, str | None]]:
        if self._saltato(assoluto):
            return []
        trovate = []
        for radice in radici:
            for base in radice["basi"]:
                sopra = _resto(base, assoluto)
                if sopra is None:
                    continue
                parti = [parte for parte in re.split(r"[\\/]", sopra) if parte]
                if not any(parte.casefold() in DA_SALTARE for parte in parti):
                    try:
                        pulito = registro.percorso_pulito(sopra) == sopra
                    except ValueError:
                        pulito = False
                    trovate.append((radice, sopra if pulito else None))
                break
        return trovate

    def _esamina(self, buttato: Buttato, radici: list[dict], nostri: set[str]):
        if os.path.normcase(buttato.dati) in nostri:
            return False
        toccate = self._toccate(buttato.originale, radici, buttato.quando)
        if not toccate:
            return False
        try:
            file, mancanti, byte = self._conta(buttato, toccate)
        except (OSError, _Altro):
            return self._non_letto(buttato)
        if not mancanti:
            return False
        return self._allarme(buttato, file, mancanti, byte)

    def _non_letto(self, buttato: Buttato):
        try:
            c_e = os.path.lexists(percorso_lungo(buttato.dati))
        except (OSError, ValueError):
            c_e = True
        if not c_e:
            return False
        volte = self._tentativi.get(buttato.segno, 0) + 1
        self._tentativi[buttato.segno] = volte
        if volte < TENTATIVI:
            return None
        return self._allarme(buttato, None, None, None)

    def _allarme(self, buttato: Buttato, file, mancanti, byte) -> dict:
        allarme = {"id": secrets.token_hex(8), "quando": self._orologio(),
                   "nome": buttato.nome, "segno": buttato.segno,
                   "originale": buttato.originale, "dati": buttato.dati,
                   "buttato": buttato.quando, "file": file, "mancanti": mancanti,
                   "byte": byte, "stato": ATTIVO}
        with self._serratura:
            self._allarmi.append(allarme)
            self._salva_allarme(allarme)
        if self._avvisa is not None:
            try:
                self._avvisa(AVVISO)
            except Exception:
                self.problemi.add("avviso_non_mandato")
        return copy.deepcopy(allarme)

    def _voci(self, dati: str):
        stato = os.lstat(percorso_lungo(dati))
        yield "", dati, stato
        if metadati.tipo_di(stato) != metadati.CARTELLA:
            return
        pila = [""]
        while pila:
            relativo = pila.pop()
            with os.scandir(percorso_lungo(Copiatore._assoluto(dati, relativo))) as voci:
                nomi = sorted(voce.name for voce in voci)
            for nome in nomi:
                figlio = f"{relativo}/{nome}" if relativo else nome
                assoluto = Copiatore._assoluto(dati, figlio)
                figlio_stato = os.lstat(percorso_lungo(assoluto))
                yield figlio, assoluto, figlio_stato
                if metadati.tipo_di(figlio_stato) == metadati.CARTELLA:
                    pila.append(figlio)

    def _conta(self, buttato: Buttato, radici: list[dict]) -> tuple[int, int, int]:
        file = mancanti = byte = 0
        for relativo, assoluto, stato in self._voci(buttato.dati):
            self._ferma_se_serve()
            if metadati.tipo_di(stato) != metadati.FILE:
                continue
            dove = self._dove(Copiatore._assoluto(buttato.originale, relativo), radici)
            if not dove:
                continue
            file += 1
            if not self._nell_archivio(dove, assoluto, stato):
                mancanti += 1
                byte += stato.st_size
        return file, mancanti, byte

    def _nell_archivio(self, dove, assoluto: str, stato) -> bool:
        for radice, percorso in dove:
            if percorso is None:
                continue
            try:
                storia = self.elenco.storia(radice["id"], percorso)
            except ValueError:
                continue
            for posto in storia:
                if (posto.tipo != metadati.FILE or posto.contenuto is None
                        or SEGNI_DA_RIFARE & set(posto.segni)
                        or posto.metadati.get("modifica") != stato.st_mtime_ns):
                    continue
                informazioni = self.elenco.contenuto(posto.contenuto)
                if (informazioni is not None and informazioni["stato"] in STATI_BUONI
                        and informazioni["dimensione"] == stato.st_size):
                    return True
        return self._stesso_contenuto(assoluto, stato)

    def _stesso_contenuto(self, assoluto: str, stato) -> bool:
        if self._dimensioni is None:
            self._dimensioni = self.elenco.dimensioni()
        if stato.st_size not in self._dimensioni:
            return False
        blake = hashlib.blake2b(digest_size=formato.IMPRONTA)
        sha = hashlib.sha256()
        letti = 0
        try:
            with self._apri(assoluto, True) as lettore:
                while True:
                    self._ferma_se_serve()
                    pezzo = lettore.read(4 * MB)
                    if not pezzo:
                        break
                    blake.update(pezzo)
                    sha.update(pezzo)
                    letti += len(pezzo)
        except OSError:
            raise _Altro from None
        if letti != stato.st_size:
            raise _Altro
        for numero in self.elenco.uguali(letti, blake.hexdigest(), sha.hexdigest()):
            informazioni = self.elenco.contenuto(numero)
            if informazioni is not None and informazioni["stato"] in STATI_BUONI:
                return True
        return False

    def _risolvi(self) -> None:
        with self._serratura:
            for allarme in self._allarmi:
                if allarme["stato"] != ATTIVO:
                    continue
                try:
                    if os.path.lexists(percorso_lungo(allarme["dati"])):
                        continue
                    tornato = os.path.lexists(percorso_lungo(allarme["originale"]))
                except (OSError, ValueError):
                    continue
                allarme["stato"] = RIMESSO if tornato else PERSO
                self._salva_allarme(allarme)


class Ronda(Sottofondo):

    nome = "archivio-sicuro-vedetta"

    def __init__(self, vedetta: Vedetta, *, ogni: float = OGNI,
                 sveglio=contextlib.nullcontext, rallenta=None,
                 pausa_se_usi: float = PAUSA_SE_USI):
        super().__init__(sveglio=sveglio, rallenta=rallenta, pausa_se_usi=pausa_se_usi)
        self.vedetta = vedetta
        self._ogni = ogni
        self.giri = 0
        self.ultimo: str | None = None

    def avvia(self) -> bool:
        return self._parti()

    def _lavora(self) -> None:
        self.vedetta.aspetta = self._aspetta
        try:
            while True:
                self._aspetta()
                try:
                    self.vedetta.guarda()
                    self.ultimo = None
                except Fermato:
                    raise
                except ErroreOfficina as errore:
                    self.ultimo = errore.codice
                except Exception:
                    self.ultimo = "vedetta_guasta"
                self.giri += 1
                self._dormi_fermabile(self._ogni)
        finally:
            self.vedetta.aspetta = None

    def istantanea(self) -> dict:
        return {"stato": self.stato, "giri": self.giri, "ultimo": self.ultimo,
                "allarmi": self.vedetta.allarmi(), "problemi": sorted(self.vedetta.problemi)}


__all__ = ["AVVISO", "Buttato", "Capienza", "Cestino", "CestinoAssente", "CestinoWindows",
           "Mandata", "Mossa", "Quaderno", "Ricontrollo", "Ronda", "Spedizioniere",
           "Vedetta", "cestino_di_sistema", "leggi_info", "permesso", "scrivi_info",
           "stato_di"]
