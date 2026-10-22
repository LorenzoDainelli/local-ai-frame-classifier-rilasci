from __future__ import annotations

import errno
import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import stat
import threading
import time
import zlib
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from officina.errori import ErroreOfficina
from officina.sicuro import chiavi, formato, sveglia
from officina.sicuro import elenco as registro
from officina.sicuro.controllo import MESE, Controllore
from officina.sicuro.copia import cartella_esistente
from officina.sicuro.diretto import Lettore
from officina.sicuro.disco import WINDOWS, fissa_cartella, scrivi_tutto
from officina.sicuro.sottofondo import FINITO, PAUSA_SE_USI, Sottofondo


__all__ = ["Avanzamento", "AggiornaChiavetta", "Chiavetta", "ChiavettaStaccata",
           "Esame", "Guardiano", "Resoconto", "dischi_attaccati", "leggi_segno",
           "sistema_dei_file", "tutti_i_dischi"]

CARTELLA = "Archivio sicuro"
SEGNO = "chiavetta.json"
TIPO = "officina-archivio-sicuro-chiavetta"
TIPO_STATO = b"officina-archivio-sicuro-chiavetta-stato"
VERSIONE = 1
STATO = "chiavetta.stato"
RISERVA = "chiavetta.riserva.stato"
PROGRAMMINO = "Recupera foto.exe"
LEGGIMI = "Come sono fatti i file.txt"
NUOVO = ".nuovo"
PEZZO = 4 * 1024 * 1024
BYTE_GROSSI = 1024 ** 3
FILE_GROSSI = 500
TROPPO_PER_UNA_CHIAVETTA = 256 * 1000 ** 3
MARGINE = 256 * 1024 * 1024
SALVA_OGNI = 120.0
TENTATIVI = 2
FOTOGRAFIE_DA_TENERE = 2
OGNI_QUANTI_BLOCCHI = 64
SEGNO_MASSIMO = 64 * 1024
NONCE = 12
OGNI = 3.0
RIPASSA = 600.0
FAT = frozenset({"FAT", "FAT12", "FAT16", "FAT32"})
PIENO = (errno.ENOSPC, getattr(errno, "EDQUOT", errno.ENOSPC))
NOSTRE = ("nostra", "da_adottare")

DA_ATTACCARE = "da_attaccare"
NON_STACCARLA = "non_staccarla"
PUOI_STACCARLA = "puoi_staccarla"
DIVERSA = "diversa"
FERMATA = "fermata"
PROBLEMA = "problema"

_NUMERO = re.compile(r"^[0-9a-f]{32}$")
_FOTOGRAFIA = re.compile(r"^fotografia-(\d{8})\.ofs$")


class ChiavettaStaccata(ErroreOfficina):
    codice = "chiavetta_staccata"


class _Lettura(Exception):
    pass


def _esadecimale(valore, lunghezza: int) -> bool:
    if not isinstance(valore, str) or len(valore) != lunghezza * 2:
        return False
    try:
        bytes.fromhex(valore)
    except ValueError:
        return False
    return valore == valore.lower()


def _momento(valore) -> bool:
    return (isinstance(valore, (int, float)) and not isinstance(valore, bool)
            and valore == valore and 0 <= valore < 1e11)


def _numero(quanti: int) -> str:
    return f"{quanti:,}".replace(",", ".")


def _gb(byte: int) -> str:
    return f"{max(byte, 0) / 1024 ** 3:.1f}".replace(".", ",") + " GB"


def _canonico(dati: dict) -> bytes:
    return json.dumps(dati, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True).encode("ascii")


def _firma(chiave, corpo: dict) -> str:
    return hmac.new(chiave.per("chiavetta-segno"), _canonico(corpo),
                    hashlib.sha256).hexdigest()


def leggi_segno(radice) -> dict | None:
    try:
        with open(Path(radice) / CARTELLA / SEGNO, "rb") as file:
            testo = file.read(SEGNO_MASSIMO + 1)
        segno = json.loads(testo.decode("utf-8"))
    except (OSError, ValueError):
        return None
    if (len(testo) > SEGNO_MASSIMO or not isinstance(segno, dict)
            or segno.get("tipo") != TIPO
            or type(segno.get("versione")) is not int
            or not _esadecimale(segno.get("archivio"), chiavi.NOME)
            or not _esadecimale(segno.get("chiavetta"), 16)
            or not _esadecimale(segno.get("firma"), 32)
            or not _momento(segno.get("creata"))):
        return None
    return segno


def _segno_firmato(segno: dict, chiave) -> bool:
    corpo = {nome: valore for nome, valore in segno.items() if nome != "firma"}
    return hmac.compare_digest(segno["firma"], _firma(chiave, corpo))


def _tutte_uguali(documenti: list[dict | None]) -> bool:
    if any(documento is None for documento in documenti):
        return False
    return len({chiavi._in_byte(documento) for documento in documenti}) == 1


def _dentro(percorso: Path, cartella: Path) -> bool:
    try:
        vero = os.path.normcase(os.path.realpath(percorso))
        base = os.path.normcase(os.path.realpath(cartella))
    except (OSError, ValueError):
        return False
    return vero == base or vero.startswith(base.rstrip(os.sep) + os.sep)


def _cartella_vera(percorso: Path) -> bool:
    try:
        return stat.S_ISDIR(os.stat(percorso).st_mode)
    except (OSError, ValueError):
        return False


def _spazio_libero(radice: Path) -> int:
    return shutil.disk_usage(cartella_esistente(radice)).free


def _stesso_disco(uno: Path, altro: Path) -> bool:
    try:
        return (os.stat(cartella_esistente(uno)).st_dev
                == os.stat(cartella_esistente(altro)).st_dev)
    except OSError:
        return False


def _crea_sotto(base: Path, cartella: Path) -> None:
    mancanti = []
    parte = cartella
    while parte != base:
        if parte == parte.parent:
            raise FileNotFoundError(errno.ENOENT, os.strerror(errno.ENOENT),
                                    os.fspath(cartella))
        mancanti.append(parte)
        parte = parte.parent
    if not os.path.isdir(base):
        raise FileNotFoundError(errno.ENOENT, os.strerror(errno.ENOENT), os.fspath(base))
    for parte in reversed(mancanti):
        try:
            os.mkdir(parte)
        except FileExistsError:
            if not os.path.isdir(parte):
                raise


def _apri_per_scrivere(percorso: Path):
    return open(percorso, "w+b")


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
    kernel32.GetLogicalDrives.restype = wintypes.DWORD
    kernel32.GetLogicalDrives.argtypes = ()
    kernel32.GetDriveTypeW.restype = wintypes.UINT
    kernel32.GetDriveTypeW.argtypes = (wintypes.LPCWSTR,)
    kernel32.SetThreadErrorMode.restype = wintypes.BOOL
    kernel32.SetThreadErrorMode.argtypes = (wintypes.DWORD, wintypes.LPDWORD)
    return kernel32


def senza_finestre_di_errore() -> None:
    if not WINDOWS:
        return
    try:
        _kernel32().SetThreadErrorMode(0x0001 | 0x8000, None)
    except (AttributeError, OSError):
        pass


def sistema_dei_file(percorso) -> str | None:
    if not WINDOWS:
        return None
    import ctypes

    try:
        kernel32 = _kernel32()
        volume = ctypes.create_unicode_buffer(300)
        if not kernel32.GetVolumePathNameW(os.fspath(percorso), volume, 300):
            return None
        nome = ctypes.create_unicode_buffer(300)
        if not kernel32.GetVolumeInformationW(volume.value, None, 0, None, None,
                                              None, nome, 300):
            return None
    except (AttributeError, OSError):
        return None
    return nome.value or None


def tutti_i_dischi() -> list[Path]:
    if WINDOWS:
        try:
            kernel32 = _kernel32()
            maschera = kernel32.GetLogicalDrives()
        except (AttributeError, OSError):
            return []
        dischi = []
        for indice in range(26):
            if maschera & (1 << indice):
                radice = f"{chr(65 + indice)}:\\"
                if kernel32.GetDriveTypeW(radice) in (2, 3):
                    dischi.append(Path(radice))
        return dischi
    dischi = []
    for base in ("/media", "/run/media", "/Volumes", "/mnt"):
        try:
            voci = sorted(voce.path for voce in os.scandir(base)
                          if voce.is_dir(follow_symlinks=False))
        except OSError:
            continue
        for voce in voci:
            dischi.append(Path(voce))
            try:
                dischi += sorted(Path(sotto.path) for sotto in os.scandir(voce)
                                 if sotto.is_dir(follow_symlinks=False))
            except OSError:
                continue
    return dischi


def dischi_attaccati() -> list[Path]:
    dischi = tutti_i_dischi()
    if WINDOWS:
        return dischi
    return [disco for disco in dischi if (disco / CARTELLA / SEGNO).is_file()]


@dataclass
class _Stato:
    chiavetta: str | None = None
    creata: float | None = None
    persa: bool = False
    iniziato: float | None = None
    finito: float | None = None
    numero: int = 0
    sopra: dict[str, float] = field(default_factory=dict)

    def in_byte(self) -> dict:
        return {"chiavetta": self.chiavetta, "creata": self.creata,
                "persa": self.persa, "iniziato": self.iniziato,
                "finito": self.finito, "numero": self.numero, "sopra": self.sopra}

    @classmethod
    def da(cls, dati) -> _Stato | None:
        if not isinstance(dati, dict):
            return None
        chiavetta = dati.get("chiavetta")
        numero = dati.get("numero")
        sopra = dati.get("sopra")
        if ((chiavetta is not None and not _esadecimale(chiavetta, 16))
                or type(numero) is not int or numero < 0
                or not isinstance(sopra, dict)
                or type(dati.get("persa")) is not bool):
            return None
        momenti = {}
        for nome in ("creata", "iniziato", "finito"):
            valore = dati.get(nome)
            momenti[nome] = float(valore) if _momento(valore) else None
        return cls(chiavetta=chiavetta, persa=dati["persa"], numero=numero,
                   sopra={numero: float(quando) for numero, quando in sopra.items()
                          if isinstance(numero, str) and _NUMERO.match(numero)
                          and _momento(quando)},
                   **momenti)


def _accompagnamento() -> bytes:
    return TIPO_STATO + b"\x00" + bytes([VERSIONE])


def _cifra_stato(chiave, stato: _Stato) -> bytes:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    nonce = secrets.token_bytes(NONCE)
    chiaro = zlib.compress(json.dumps(stato.in_byte(), separators=(",", ":"),
                                      ensure_ascii=True).encode("ascii"))
    return (_accompagnamento() + nonce
            + AESGCM(chiave.per("chiavetta-stato")).encrypt(
                nonce, chiaro, _accompagnamento()))


def _decifra_stato(chiave, dati: bytes) -> _Stato | None:
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    testa = _accompagnamento()
    if not dati.startswith(testa) or len(dati) < len(testa) + NONCE + 16:
        return None
    nonce = dati[len(testa):len(testa) + NONCE]
    try:
        chiaro = AESGCM(chiave.per("chiavetta-stato")).decrypt(
            nonce, dati[len(testa) + NONCE:], testa)
        return _Stato.da(json.loads(zlib.decompress(chiaro).decode("ascii")))
    except (InvalidTag, zlib.error, ValueError):
        return None


@dataclass
class Esame:
    chi: str
    sistema: str | None = None
    libero: int = 0
    serve: int = 0
    totale: int = 0
    consiglia_disco: bool = False
    problema: str | None = None
    messaggio: str | None = None

    @property
    def va_bene(self) -> bool:
        return self.problema is None


@dataclass
class Avanzamento:
    fase: str | None = None
    numero: str | None = None
    fatti: int = 0
    totale: int = 0
    byte_fatti: int = 0
    byte_totali: int = 0
    letti: int = 0


@dataclass
class Resoconto:
    copiati: int = 0
    byte: int = 0
    riletti: int = 0
    ricopiati: list[str] = field(default_factory=list)
    riparati_sulla_chiavetta: list[str] = field(default_factory=list)
    rovinati_sulla_chiavetta: list[str] = field(default_factory=list)
    rovinati_sul_pc: list[str] = field(default_factory=list)
    riparati_sul_pc: list[str] = field(default_factory=list)
    persi_sul_pc: list[str] = field(default_factory=list)
    note_rimesse: int = 0
    chiave_rimessa_sul_pc: bool = False
    elenco: bool = False
    problemi: list[str] = field(default_factory=list)
    finito: bool = False

    def problema(self, codice: str) -> None:
        if codice not in self.problemi:
            self.problemi.append(codice)

    @property
    def guai(self) -> list[str]:
        return list(dict.fromkeys([*self.rovinati_sulla_chiavetta, *self.persi_sul_pc]))

    def frase(self) -> str:
        if not self.finito:
            return "La chiavetta non è ancora aggiornata: non staccarla."
        guai = len(self.guai)
        if guai:
            return ("Puoi staccarla, ma attenzione: "
                    + (f"{_numero(guai)} file è rovinato e non si ripara."
                       if guai == 1 else
                       f"{_numero(guai)} file sono rovinati e non si riparano."))
        parti: list[str] = []
        riparati = (len(self.ricopiati) + len(self.riparati_sulla_chiavetta)
                    + len(self.riparati_sul_pc) + self.note_rimesse)
        for quanti, come in ((self.copiati, "nuovi copiati"),
                             (self.riletti, "riletti"), (riparati, "riparati")):
            if quanti:
                parti.append(f"{_numero(quanti)} " + ("file " if not parti else "")
                             + come)
        if not parti:
            return "Puoi staccarla: era già tutto aggiornato."
        frase = ", ".join(parti)
        return f"Puoi staccarla. {frase[0].upper()}{frase[1:]}."


class Chiavetta:

    def __init__(self, cartella: Path, elenco, chiave, *, apri=Lettore,
                 scrivi=None, adesso=time.time, aspetta=None, spazio=None,
                 sistema=None, stesso_disco=None, programmino=None,
                 leggimi: str | None = None):
        self.cartella = Path(cartella)
        self.elenco = elenco
        self._chiave = chiave
        self._apri = apri
        self._scrivi = scrivi or _apri_per_scrivere
        self._adesso = adesso
        self._aspetta = aspetta
        self._spazio = spazio or _spazio_libero
        self._sistema = sistema or sistema_dei_file
        self._stesso_disco = stesso_disco or _stesso_disco
        self._programmino = None if programmino is None else Path(programmino)
        self._leggimi = leggimi
        self._serratura = threading.RLock()
        self.problemi: list[str] = []
        self._stato = self._carica_stato()
        self._salvato = time.monotonic()
        self._in_uso: str | None = None
        self._radice: Path | None = None
        self._da_riparare: set[str] = set()
        self.avanzamento = Avanzamento()
        self.resoconto: Resoconto | None = None

    @property
    def preparata(self) -> bool:
        return self._stato.chiavetta is not None

    @property
    def persa(self) -> bool:
        return self._stato.persa

    @property
    def ultima(self) -> float | None:
        return self._stato.finito

    @property
    def identita(self) -> str | None:
        with self._serratura:
            return self._stato.chiavetta

    def posto_sbagliato(self, radice) -> tuple[str, str] | None:
        return self._problema_di_posto(Path(radice))

    def chiave_del_pc_a_posto(self) -> bool:
        return _tutte_uguali([self._documento(self.cartella / nome)
                              for nome in (chiavi.FILE, chiavi.RISERVA)])

    def chiave_uguale(self, radice) -> bool:
        dove = Path(radice) / CARTELLA
        return _tutte_uguali([self._documento(cartella / nome)
                              for cartella in (self.cartella, dove)
                              for nome in (chiavi.FILE, chiavi.RISERVA)])

    def rileggi_presto(self, numeri) -> None:
        cambiati = False
        with self._serratura:
            for numero in numeri:
                if self._stato.sopra.get(numero, 0.0) > 0.0:
                    self._stato.sopra[numero] = 0.0
                    cambiati = True
        if cambiati:
            self._salva_stato()

    def _carica_stato(self) -> _Stato:
        trovati = []
        esistono = False
        for nome in (STATO, RISERVA):
            try:
                dati = (self.cartella / nome).read_bytes()
            except FileNotFoundError:
                continue
            except OSError:
                esistono = True
                continue
            esistono = True
            stato = _decifra_stato(self._chiave, dati)
            if stato is not None:
                trovati.append(stato)
        if not trovati:
            if esistono:
                self.problemi.append("stato_rovinato")
            return _Stato()
        return max(trovati, key=lambda stato: stato.numero)

    def _salva_stato(self) -> None:
        with self._serratura:
            self._stato.numero += 1
            dati = _cifra_stato(self._chiave, self._stato)
            self._salvato = time.monotonic()
        try:
            for nome in (STATO, RISERVA):
                scrivi_tutto(self.cartella / nome, dati)
        except OSError:
            if not _cartella_vera(self.cartella):
                raise ErroreOfficina(
                    "Il disco dell'Archivio sicuro non si legge più: ricollegalo "
                    "e riprova.", codice="archivio_sparito") from None
            if self.resoconto is not None:
                self.resoconto.problema("stato_non_salvato")

    def _forse_salva(self) -> None:
        if time.monotonic() - self._salvato >= SALVA_OGNI:
            self._salva_stato()

    def _ferma_se_serve(self) -> None:
        if self._aspetta is not None:
            self._aspetta()

    def chi_e(self, radice) -> str:
        segno = leggi_segno(radice)
        if segno is None:
            dove = Path(radice) / CARTELLA
            if (dove / SEGNO).exists():
                return "rovinata"
            return "vuota" if not self._occupata(dove) else "occupata"
        if segno["archivio"] != self._chiave.nome or not _segno_firmato(segno, self._chiave):
            return "diversa"
        if segno["versione"] > VERSIONE:
            return "piu_nuova"
        with self._serratura:
            nostra = self._stato.chiavetta
        if segno["chiavetta"] == nostra:
            return "nostra"
        return "da_adottare" if nostra is None else "vecchia"

    def _occupata(self, dove: Path) -> bool:
        try:
            return any(True for _ in os.scandir(dove))
        except OSError:
            return False

    def _chiave_di(self, dove: Path) -> bool:
        for nome in (chiavi.FILE, chiavi.RISERVA):
            try:
                documento = chiavi._leggi_uno(dove / nome)
            except ErroreOfficina:
                documento = None
            if documento is not None and documento["nome"] == self._chiave.nome:
                return True
        return False

    def esamina(self, radice) -> Esame:
        radice = Path(radice)
        if not _cartella_vera(radice):
            return Esame("vuota", problema="non_trovata",
                         messaggio="Non trovo la chiavetta: attaccala e riprova.")
        chi = self.chi_e(radice)
        dove = radice / CARTELLA
        if chi in ("occupata", "rovinata") and self._chiave_di(dove):
            chi = "senza_segno"
        esame = Esame(chi)
        problema = self._problema_di_chi(chi)
        if problema is None:
            problema = self._problema_di_posto(radice)
        if problema is None:
            esame.sistema = self._sistema(radice)
            if (esame.sistema or "").upper() in FAT:
                problema = ("fat32", _MESSAGGIO_FAT)
        presenti = (self._presenti(dove)
                    if chi in (*NOSTRE, "vecchia", "senza_segno") else {})
        esame.totale, esame.serve = self._misura(presenti)
        esame.consiglia_disco = esame.totale > TROPPO_PER_UNA_CHIAVETTA
        if problema is None:
            try:
                esame.libero = self._spazio(radice)
            except OSError:
                problema = ("non_trovata",
                            "Non riesco a leggere la chiavetta: staccala, "
                            "riattaccala e riprova.")
        if problema is None and esame.libero < esame.serve:
            problema = ("poco_spazio",
                        f"Sulla chiavetta ci sono {_gb(esame.libero)} liberi, ma ne "
                        f"servono {_gb(esame.serve)}: mancano "
                        f"{_gb(esame.serve - esame.libero)}. Serve una chiavetta "
                        "più grande o un disco esterno. Non ho copiato niente.")
        if problema is not None:
            esame.problema, esame.messaggio = problema
        return esame

    def _problema_di_chi(self, chi: str) -> tuple[str, str] | None:
        if chi == "diversa":
            return ("chiavetta_diversa",
                    "Su questa chiavetta c'è l'Archivio sicuro di un'altra "
                    "installazione: non la tocco.")
        if chi == "piu_nuova":
            return ("versione_piu_nuova",
                    "Questa chiavetta è stata preparata da una versione più nuova "
                    "del programma: aggiorna il programma prima di usarla.")
        if chi in ("occupata", "rovinata"):
            return ("cartella_occupata",
                    f"Sulla chiavetta c'è già una cartella «{CARTELLA}» che non è "
                    "di questo archivio: spostala o rinominala tu, io non la tocco.")
        return None

    def _problema_di_posto(self, radice: Path) -> tuple[str, str] | None:
        dove = radice / CARTELLA
        if _dentro(dove, self.cartella) or _dentro(self.cartella, dove):
            return ("dentro_l_archivio",
                    "Questa è la cartella dell'archivio stesso: per la copia di "
                    "riserva serve un'altra chiavetta o un altro disco.")
        for radice_foto in self.elenco.radici():
            if radice_foto["tolta"]:
                continue
            foto = Path(radice_foto["percorso"])
            if _dentro(dove, foto) or _dentro(foto, dove):
                return ("dentro_gli_originali",
                        "Questa chiavetta è una delle cartelle delle foto che "
                        "copio nell'archivio: per la copia di riserva serve una "
                        "chiavetta usata solo per questo.")
        if self._stesso_disco(radice, self.cartella):
            return ("stesso_disco",
                    "Questa chiavetta è lo stesso disco dove sta l'archivio: se "
                    "il disco si rompe si perdono tutte e due le copie. Serve una "
                    "chiavetta o un disco esterno.")
        return None

    def _misura(self, presenti: dict[str, int]) -> tuple[int, int]:
        totale = mancano = 0
        for numero, peso in self.elenco.pesi():
            totale += peso
            if presenti.get(numero) != peso:
                mancano += peso
        for numero in self.elenco.note():
            peso = self._peso(registro.percorso_contenuto(self.cartella, numero))
            totale += peso
            if presenti.get(numero) != peso:
                mancano += peso
        fotografia = self.elenco.fotografia_attuale()
        elenco = 0 if fotografia is None else self._peso(fotografia)
        totale += elenco
        altro = 2 * elenco + 64 * 1024
        if self._programmino is not None:
            altro += self._peso(self._programmino)
        if self._leggimi is not None:
            altro += len(self._leggimi.encode("utf-8"))
        return totale, mancano + altro + MARGINE

    @staticmethod
    def _peso(percorso: Path) -> int:
        try:
            return os.stat(percorso).st_size
        except OSError:
            return 0

    def _presenti(self, dove: Path) -> dict[str, int]:
        trovati: dict[str, int] = {}
        try:
            cartelle = sorted((voce.name, voce.path)
                              for voce in os.scandir(dove / registro.CONTENUTI)
                              if voce.is_dir(follow_symlinks=False))
        except FileNotFoundError:
            return trovati
        for nome, cartella in cartelle:
            for voce in os.scandir(cartella):
                if not voce.name.endswith(registro.ESTENSIONE):
                    continue
                numero = voce.name[:-len(registro.ESTENSIONE)]
                if not _NUMERO.match(numero) or numero[:2] != nome:
                    continue
                stato = voce.stat(follow_symlinks=False)
                if stat.S_ISREG(stato.st_mode):
                    trovati[numero] = stato.st_size
        return trovati

    def prepara(self, radice, al_posto: bool = False) -> Esame:
        radice = Path(radice)
        esame = self.esamina(radice)
        if not esame.va_bene:
            raise ErroreOfficina(esame.messaggio, codice=esame.problema)
        with self._serratura:
            if esame.chi == "nostra":
                return esame
            if esame.chi == "da_adottare":
                self._adotta(leggi_segno(radice))
                self._salva_stato()
                return esame
            if (self._stato.chiavetta is not None and not self._stato.persa
                    and not al_posto):
                raise ErroreOfficina(
                    "L'archivio ha già la sua chiavetta. Se questa deve prendere "
                    "il suo posto, conferma: quella di prima non verrà più "
                    "aggiornata.", codice="c_e_gia_una_chiavetta")
        segno = {"tipo": TIPO, "versione": VERSIONE, "archivio": self._chiave.nome,
                 "chiavetta": secrets.token_hex(16), "creata": self._adesso()}
        segno["firma"] = _firma(self._chiave, segno)
        dove = radice / CARTELLA
        with self._sulla_chiavetta(radice, controlla=False):
            _crea_sotto(radice, dove)
            scrivi_tutto(dove / SEGNO, (json.dumps(segno, ensure_ascii=True, indent=1)
                                        + "\n").encode("ascii"))
        riletto = leggi_segno(radice)
        if riletto is None or riletto["chiavetta"] != segno["chiavetta"]:
            raise ErroreOfficina(
                "Ho scritto sulla chiavetta ma rileggendo non torna: può essere "
                "rovinata. Prova con un'altra.", codice="scrive_male")
        with self._serratura:
            self._adotta(segno)
        self._salva_stato()
        esame.chi = "nostra"
        return esame

    def _adotta(self, segno: dict) -> None:
        self._stato = _Stato(chiavetta=segno["chiavetta"], creata=segno["creata"],
                             numero=self._stato.numero)

    def segna_persa(self) -> None:
        with self._serratura:
            if self._stato.chiavetta is None:
                return
            self._stato.persa = True
        self._salva_stato()

    def mancanti(self) -> tuple[int, int]:
        with self._serratura:
            sopra = set(self._stato.sopra)
        file = byte = 0
        for numero, peso in self.elenco.pesi():
            if numero not in sopra:
                file += 1
                byte += peso
        for numero in self.elenco.note():
            if numero not in sopra:
                file += 1
                byte += self._peso(registro.percorso_contenuto(self.cartella, numero))
        return file, byte

    def promemoria(self, adesso: float | None = None) -> str | None:
        adesso = self._adesso() if adesso is None else adesso
        with self._serratura:
            chiavetta, persa, finito = (self._stato.chiavetta, self._stato.persa,
                                        self._stato.finito)
        if chiavetta is None:
            return "mai_fatta"
        if persa:
            return "persa"
        file, byte = self.mancanti()
        if byte > BYTE_GROSSI or file > FILE_GROSSI:
            return "copia_grossa"
        if finito is None or adesso - finito >= MESE:
            return "mese"
        return None

    def completa(self) -> bool:
        with self._serratura:
            if (self._stato.chiavetta is None or self._stato.persa
                    or self._stato.finito is None):
                return False
        return self.mancanti() == (0, 0)

    def riassunto(self) -> dict:
        file, byte = self.mancanti()
        with self._serratura:
            return {"preparata": self._stato.chiavetta is not None,
                    "persa": self._stato.persa, "ultima": self._stato.finito,
                    "mancanti_file": file, "mancanti_byte": byte,
                    "promemoria": self.promemoria(), "problemi": list(self.problemi)}

    def _attaccata(self, radice: Path) -> bool:
        segno = leggi_segno(radice)
        return segno is not None and segno["chiavetta"] == self._in_uso

    def copia_di(self, radice):
        radice = Path(radice)
        dove = radice / CARTELLA

        def copia(numero: str) -> Path | None:
            segno = leggi_segno(radice)
            with self._serratura:
                nostra = self._stato.chiavetta
            if segno is None or segno["chiavetta"] != nostra:
                return None
            percorso = registro.percorso_contenuto(dove, numero)
            return percorso if percorso.is_file() else None

        return copia

    @contextmanager
    def _sulla_chiavetta(self, radice: Path, controlla: bool = True):
        try:
            yield
        except OSError as guasto:
            if controlla and not self._attaccata(radice):
                raise _staccata() from guasto
            if guasto.errno in PIENO:
                raise ErroreOfficina(
                    "La chiavetta si è riempita prima della fine: serve una "
                    "chiavetta più grande o un disco esterno. Quello che è già "
                    "copiato resta buono.", codice="chiavetta_piena") from guasto
            if guasto.errno == errno.EFBIG:
                raise ErroreOfficina(_MESSAGGIO_FAT, codice="fat32") from guasto
            raise ErroreOfficina(
                "La chiavetta dà errori quando scrivo: può essere rovinata. Mi "
                "fermo; quello che è già copiato resta buono. Prova con "
                "un'altra chiavetta.", codice="chiavetta_guasta") from guasto

    def _archivio_c_e(self) -> None:
        if not _cartella_vera(self.cartella / registro.CONTENUTI):
            raise ErroreOfficina(
                "Il disco dell'Archivio sicuro non si legge più: ricollegalo e "
                "riprova.", codice="archivio_sparito")

    def _riconosci(self, radice: Path) -> None:
        chi = self.chi_e(radice)
        if chi == "da_adottare":
            with self._serratura:
                self._adotta(leggi_segno(radice))
            self._salva_stato()
        elif chi != "nostra":
            problema = self._problema_di_chi(chi)
            if problema is None and chi == "vecchia":
                problema = ("chiavetta_vecchia",
                            "Questa è una vecchia chiavetta dell'archivio, non "
                            "quella di adesso. Se vuoi usarla al suo posto, "
                            "preparala di nuovo.")
            if problema is None:
                problema = ("non_preparata",
                            "Questa chiavetta non è ancora preparata per "
                            "l'Archivio sicuro.")
            raise ErroreOfficina(problema[1], codice=problema[0])
        with self._serratura:
            self._in_uso = self._stato.chiavetta

    def aggiorna(self, radice) -> Resoconto:
        radice = Path(radice)
        dove = radice / CARTELLA
        resoconto = Resoconto()
        self.resoconto = resoconto
        self.avanzamento = Avanzamento(fase="inizio")
        self._da_riparare = set()
        self._archivio_c_e()
        self._riconosci(radice)
        self._radice = radice
        try:
            with self._sulla_chiavetta(radice):
                self._pulisci(dove)
            esame = self.esamina(radice)
            if not esame.va_bene:
                raise ErroreOfficina(esame.messaggio, codice=esame.problema)
            with self._serratura:
                self._stato.iniziato = self._adesso()
            self._chiave_a_posto(radice)
            self._programmi(radice)
            self._novita(radice)
            self._ripara_il_pc(radice)
            self._elenco_sulla_chiavetta(radice)
            self._rileggi(radice)
            if self._novita(radice):
                self._elenco_sulla_chiavetta(radice)
            with self._serratura:
                self._stato.finito = self._adesso()
                self._stato.persa = False
            resoconto.finito = True
        finally:
            self.avanzamento.fase = None
            self.avanzamento.numero = None
            try:
                self._salva_stato()
            except ErroreOfficina:
                if resoconto.finito:
                    raise
        return resoconto

    def _pulisci(self, dove: Path) -> None:
        for base in (dove, dove / registro.CONTENUTI, dove / registro.ELENCO):
            try:
                voci = list(os.scandir(base))
            except FileNotFoundError:
                continue
            for voce in voci:
                if voce.name.endswith(NUOVO) and voce.is_file(follow_symlinks=False):
                    os.unlink(voce.path)
                elif base == dove / registro.CONTENUTI and voce.is_dir(
                        follow_symlinks=False):
                    for dentro in os.scandir(voce.path):
                        if (dentro.name.endswith(NUOVO)
                                and dentro.is_file(follow_symlinks=False)):
                            os.unlink(dentro.path)

    def _ogni_pezzo(self):
        pezzi = [0]

        def ogni(chiaro: bytes) -> None:
            pezzi[0] += 1
            self.avanzamento.letti += len(chiaro)
            if pezzi[0] % OGNI_QUANTI_BLOCCHI == 0:
                self._ferma_se_serve()

        return ogni

    def _controlla(self, percorso: Path, numero: str, testa: bytes | None,
                   impronte: dict | None) -> formato.Controllo | None:
        try:
            lettore = self._apri(percorso, True)
        except (OSError, ValueError):
            return None
        with lettore:
            try:
                return formato.controlla(lettore, self._chiave,
                                         numero=bytes.fromhex(numero), testa=testa,
                                         impronte=impronte,
                                         ogni_pezzo=self._ogni_pezzo())
            except (ErroreOfficina, OSError, ValueError):
                return None

    def _copia(self, sorgente: Path, fuori, conta: bool = False) -> tuple[str, int]:
        try:
            lettore = self._apri(sorgente, True)
        except (OSError, ValueError) as guasto:
            raise _Lettura from guasto
        sha = hashlib.sha256()
        with lettore:
            dove, fine = 0, lettore.dimensione
            while dove < fine:
                self._ferma_se_serve()
                try:
                    pezzo = lettore.pezzo(dove, min(PEZZO, fine - dove))
                except OSError as guasto:
                    raise _Lettura from guasto
                if not pezzo:
                    raise _Lettura
                fuori.write(pezzo)
                sha.update(pezzo)
                dove += len(pezzo)
                if conta:
                    self.avanzamento.byte_fatti += len(pezzo)
        return sha.hexdigest(), fine

    def _impronta(self, percorso: Path) -> tuple[str, int] | None:
        try:
            lettore = self._apri(percorso, True)
        except (OSError, ValueError):
            return None
        sha = hashlib.sha256()
        with lettore:
            dove, fine = 0, lettore.dimensione
            while dove < fine:
                self._ferma_se_serve()
                try:
                    pezzo = lettore.pezzo(dove, min(PEZZO, fine - dove))
                except OSError:
                    return None
                if not pezzo:
                    return None
                sha.update(pezzo)
                dove += len(pezzo)
        return sha.hexdigest(), fine

    def _metti(self, arrivo: Path, scrivi, verifica, base: Path | None = None) -> bool:
        provvisorio = arrivo.with_name(arrivo.name + NUOVO)
        try:
            _crea_sotto(self._radice if base is None else base, arrivo.parent)
            with self._scrivi(provvisorio) as fuori:
                atteso = scrivi(fuori)
                fuori.flush()
                os.fsync(fuori.fileno())
            if not verifica(provvisorio, atteso):
                return False
            os.replace(provvisorio, arrivo)
            fissa_cartella(arrivo.parent)
            return True
        finally:
            try:
                provvisorio.unlink(missing_ok=True)
            except OSError:
                pass

    def _uguale(self, provvisorio: Path, atteso) -> bool:
        return self._impronta(provvisorio) == atteso

    def _sulla_chiavetta_come(self, sorgente: Path, arrivo: Path,
                              conta: bool = False) -> bool:
        radice = self._radice
        for _ in range(TENTATIVI):
            self._ferma_se_serve()
            with self._sulla_chiavetta(radice):
                if self._metti(arrivo, lambda fuori: self._copia(sorgente, fuori, conta),
                               self._uguale):
                    return True
            if not self._attaccata(radice):
                raise _staccata()
        raise ErroreOfficina(
            "La chiavetta ha scritto male lo stesso file due volte: può essere "
            "rovinata. Mi fermo; quello che è già copiato resta buono. Prova con "
            "un'altra chiavetta.", codice="scrive_male")

    def _porta(self, dove: Path, numero: str, testa: bytes | None,
               impronte: dict | None, controllo: formato.Controllo | None = None,
               conta: bool = False) -> bool:
        sorgente = registro.percorso_contenuto(self.cartella, numero)
        if controllo is None:
            controllo = self._controlla(sorgente, numero, testa, impronte)
        if controllo is None or not controllo.leggibile:
            self._archivio_c_e()
            self._rovinato_sul_pc(numero)
            return False
        arrivo = registro.percorso_contenuto(dove, numero)
        try:
            if controllo.buono:
                self._sulla_chiavetta_come(sorgente, arrivo, conta)
            elif not self._ripara_in(sorgente, arrivo, numero, testa, impronte):
                self._rovinato_sul_pc(numero)
                return False
            else:
                self._da_riparare.add(numero)
        except _Lettura:
            self._archivio_c_e()
            self._rovinato_sul_pc(numero)
            return False
        self._sopra(numero)
        return True

    def _ripara_in(self, sorgente: Path, arrivo: Path, numero: str,
                   testa: bytes | None, impronte: dict | None) -> bool:
        radice = self._radice

        def scrivi(fuori):
            try:
                lettore = self._apri(sorgente, True)
            except (OSError, ValueError) as guasto:
                raise _Lettura from guasto
            with lettore:
                formato.ripara(lettore, fuori, self._chiave,
                               numero=bytes.fromhex(numero), testa=testa,
                               impronte=impronte)

        def verifica(provvisorio, _):
            controllo = self._controlla(provvisorio, numero, testa, impronte)
            return controllo is not None and controllo.buono

        for _ in range(TENTATIVI):
            self._ferma_se_serve()
            try:
                with self._sulla_chiavetta(radice):
                    if self._metti(arrivo, scrivi, verifica):
                        return True
            except (formato.ContenutoRovinato, _Lettura):
                return False
            if not self._attaccata(radice):
                raise _staccata()
        return False

    def _rovinato_sul_pc(self, numero: str) -> None:
        self._da_riparare.add(numero)
        if self.resoconto is not None and numero not in self.resoconto.rovinati_sul_pc:
            self.resoconto.rovinati_sul_pc.append(numero)

    def _sopra(self, numero: str) -> None:
        with self._serratura:
            self._stato.sopra[numero] = self._adesso()
        self._forse_salva()

    def _attese(self, numero: str) -> tuple[dict | None, bytes | None, dict | None]:
        informazioni = self.elenco.contenuto(numero)
        if informazioni is None:
            return None, None, None
        return (informazioni, informazioni["testa"],
                {"blake2b": informazioni["blake2b"], "sha256": informazioni["sha256"]})

    def _chiave_a_posto(self, radice: Path) -> None:
        self.avanzamento.fase = "chiave"
        dove = radice / CARTELLA
        sul_pc = [self._documento(self.cartella / nome)
                  for nome in (chiavi.FILE, chiavi.RISERVA)]
        with self._sulla_chiavetta(radice):
            sopra = [self._documento(dove / nome)
                     for nome in (chiavi.FILE, chiavi.RISERVA)]
        buono = next((documento for documento in sul_pc if documento is not None),
                     None)
        if buono is None:
            leggibili = [documento for documento in sopra if documento is not None]
            if not leggibili:
                self.resoconto.problema("chiave_non_copiata")
                return
            try:
                for nome, documento in zip((chiavi.FILE, chiavi.RISERVA), sopra,
                                           strict=True):
                    if self._illeggibile(self.cartella / nome):
                        scrivi_tutto(self.cartella / nome, chiavi._in_byte(
                            leggibili[0] if documento is None else documento))
                        self.resoconto.chiave_rimessa_sul_pc = True
            except OSError:
                self._archivio_c_e()
                self.resoconto.problema("chiave_non_rimessa")
            return
        dati = chiavi._in_byte(buono)
        if not _tutte_uguali(sul_pc):
            self.resoconto.problema("chiave_diversa_sul_pc")
            if any(documento is not None and chiavi._in_byte(documento) != dati
                   for documento in sopra):
                return
        for nome, documento in zip((chiavi.FILE, chiavi.RISERVA), sopra, strict=True):
            if documento is not None and chiavi._in_byte(documento) == dati:
                continue
            with self._sulla_chiavetta(radice):
                scrivi_tutto(dove / nome, dati)
            with self._sulla_chiavetta(radice):
                riletto = self._documento(dove / nome)
            if riletto is None or chiavi._in_byte(riletto) != dati:
                raise ErroreOfficina(
                    "Ho copiato la chiave sulla chiavetta ma rileggendola non "
                    "torna: può essere rovinata. Prova con un'altra chiavetta.",
                    codice="scrive_male")

    @staticmethod
    def _illeggibile(percorso: Path) -> bool:
        try:
            return chiavi._leggi_uno(percorso) is None
        except ErroreOfficina:
            return False

    def _documento(self, percorso: Path) -> dict | None:
        try:
            documento = chiavi._leggi_uno(percorso)
        except ErroreOfficina:
            return None
        if documento is None or documento["nome"] != self._chiave.nome:
            return None
        return documento

    def _programmi(self, radice: Path) -> None:
        self.avanzamento.fase = "programmi"
        if self._programmino is not None:
            try:
                atteso = self._impronta(self._programmino)
            except OSError:
                atteso = None
            if atteso is None:
                self.resoconto.problema("programmino_mancante")
            else:
                arrivo = radice / PROGRAMMINO
                with self._sulla_chiavetta(radice):
                    gia = self._impronta(arrivo) if arrivo.is_file() else None
                if gia != atteso:
                    try:
                        self._sulla_chiavetta_come(self._programmino, arrivo)
                    except _Lettura:
                        self.resoconto.problema("programmino_mancante")
        if self._leggimi is not None:
            dati = self._leggimi.encode("utf-8")
            arrivo = radice / LEGGIMI
            with self._sulla_chiavetta(radice):
                try:
                    gia = arrivo.read_bytes() if arrivo.is_file() else None
                except OSError:
                    gia = None
                if gia != dati:
                    scrivi_tutto(arrivo, dati)
                    if arrivo.read_bytes() != dati:
                        raise ErroreOfficina(
                            "Ho scritto sulla chiavetta ma rileggendo non torna: "
                            "può essere rovinata.", codice="scrive_male")

    def _novita(self, radice: Path) -> int:
        dove = radice / CARTELLA
        with self._sulla_chiavetta(radice):
            presenti = self._presenti(dove)
        try:
            sul_pc = self._presenti(self.cartella)
        except OSError:
            self._archivio_c_e()
            raise
        da_fare: list[tuple[str, int, bool]] = []
        for numero in self.elenco.note():
            peso = sul_pc.get(numero)
            if peso is None:
                self._rovinato_sul_pc(numero)
            elif presenti.get(numero) != peso:
                da_fare.append((numero, peso, True))
        for numero, peso in self.elenco.pesi():
            if sul_pc.get(numero) != peso:
                self._rovinato_sul_pc(numero)
                if numero in sul_pc and presenti.get(numero) != peso:
                    da_fare.append((numero, peso, False))
            elif presenti.get(numero) != peso:
                da_fare.append((numero, peso, False))
        self.avanzamento = Avanzamento(fase="novita", totale=len(da_fare),
                                       byte_totali=sum(peso for _, peso, _ in da_fare))
        copiati = 0
        for numero, peso, nota in da_fare:
            self._ferma_se_serve()
            self.avanzamento.numero = numero
            if nota:
                portato = self._porta(dove, numero, None, None, conta=True)
            else:
                informazioni, testa, impronte = self._attese(numero)
                portato = (informazioni is not None
                           and self._porta(dove, numero, testa, impronte, conta=True))
            self.avanzamento.fatti += 1
            if portato:
                copiati += 1
                self.resoconto.copiati += 1
                self.resoconto.byte += peso
        self.avanzamento.numero = None
        return copiati

    def _ripara_il_pc(self, radice: Path) -> None:
        self.avanzamento = Avanzamento(fase="riparazione")
        note = set(self.elenco.note())
        numeri = sorted({*self.elenco.con_stato("rovinato"),
                         *(numero for numero in self._da_riparare
                           if numero not in note)})
        numeri = [numero for numero in numeri
                  if self.elenco.contenuto(numero) is not None]
        if numeri:
            controllore = Controllore(self.cartella, self.elenco, self._chiave,
                                      apri=self._apri, aspetta=self._aspetta,
                                      copie=[self.copia_di(radice)],
                                      luoghi=lambda: [], adesso=self._adesso)
            self.avanzamento.totale = len(numeri)
            rapporto = controllore.controlla(numeri)
            self.resoconto.riparati_sul_pc = list(rapporto.riparati)
            self.resoconto.persi_sul_pc = list(rapporto.persi)
            for codice in rapporto.problemi:
                self.resoconto.problema(codice)
            self.avanzamento.fatti = len(numeri)
        for numero in sorted(self._da_riparare & note):
            self._ferma_se_serve()
            if self._rimetti_nota(radice, numero):
                self.resoconto.note_rimesse += 1
            else:
                self.resoconto.problema("nota_rovinata")

    def _rimetti_nota(self, radice: Path, numero: str) -> bool:
        copia = registro.percorso_contenuto(radice / CARTELLA, numero)
        controllo = self._controlla(copia, numero, None, None)
        if controllo is None or not controllo.buono:
            return False
        blob = registro.percorso_contenuto(self.cartella, numero)

        def verifica(provvisorio, _):
            controllo = self._controlla(provvisorio, numero, None, None)
            return controllo is not None and controllo.buono

        try:
            return self._metti(blob, lambda fuori: self._copia(copia, fuori),
                               verifica, self.cartella)
        except (OSError, _Lettura):
            self._archivio_c_e()
            return False

    def _elenco_sulla_chiavetta(self, radice: Path) -> None:
        self.avanzamento = Avanzamento(fase="elenco")
        try:
            self.elenco.fissa()
        except (OSError, ErroreOfficina):
            self._archivio_c_e()
            self.resoconto.problema("elenco_non_fissato")
        cartella = radice / CARTELLA / registro.ELENCO
        for _ in range(TENTATIVI):
            fotografia = self.elenco.fotografia_attuale()
            if fotografia is None:
                return
            try:
                self._sulla_chiavetta_come(fotografia, cartella / fotografia.name)
            except _Lettura:
                continue
            self.resoconto.elenco = True
            break
        else:
            self._archivio_c_e()
            self.resoconto.problema("elenco_non_copiato")
            return
        with self._sulla_chiavetta(radice):
            generazioni = sorted(
                (int(trovato.group(1)), voce.path) for voce in os.scandir(cartella)
                if (trovato := _FOTOGRAFIA.match(voce.name))
                and voce.is_file(follow_symlinks=False))
            for _, percorso in generazioni[:-FOTOGRAFIE_DA_TENERE]:
                os.unlink(percorso)
            fissa_cartella(cartella)

    def _rileggi(self, radice: Path) -> None:
        dove = radice / CARTELLA
        adesso = self._adesso()
        with self._sulla_chiavetta(radice):
            presenti = self._presenti(dove)
        with self._serratura:
            sopra = dict(self._stato.sopra)
        vecchi = sorted((sopra.get(numero, 0.0), numero) for numero in presenti
                        if sopra.get(numero, 0.0) <= adesso - MESE)
        note = set(self.elenco.note())
        self.avanzamento = Avanzamento(fase="rilettura", totale=len(vecchi),
                                       byte_totali=sum(presenti[numero]
                                                       for _, numero in vecchi))
        for _, numero in vecchi:
            self._ferma_se_serve()
            self.avanzamento.numero = numero
            self._rileggi_uno(dove, numero, numero in note)
            self.avanzamento.fatti += 1
            self.avanzamento.byte_fatti += presenti[numero]
        self.avanzamento.numero = None

    def _rileggi_uno(self, dove: Path, numero: str, nota: bool) -> None:
        informazioni, testa, impronte = self._attese(numero)
        blob = registro.percorso_contenuto(dove, numero)
        controllo = self._controlla(blob, numero, testa, impronte)
        if controllo is None and not self._attaccata(self._radice):
            raise _staccata()
        self.resoconto.riletti += 1
        if controllo is not None and controllo.buono:
            self._sopra(numero)
            return
        conosciuto = informazioni is not None or nota
        sul_pc = None
        if conosciuto:
            sul_pc = self._controlla(registro.percorso_contenuto(self.cartella, numero),
                                     numero, testa, impronte)
        if sul_pc is not None and sul_pc.buono:
            if self._porta(dove, numero, testa, impronte, sul_pc):
                self.resoconto.ricopiati.append(numero)
                return
        if (controllo is not None and controllo.riparabile
                and self._ripara_in(blob, blob, numero, testa, impronte)):
            self.resoconto.riparati_sulla_chiavetta.append(numero)
            self._sopra(numero)
            return
        if sul_pc is not None and sul_pc.leggibile:
            if self._porta(dove, numero, testa, impronte, sul_pc):
                self.resoconto.ricopiati.append(numero)
                return
        if conosciuto:
            self.resoconto.rovinati_sulla_chiavetta.append(numero)
        else:
            self.resoconto.problema("sconosciuti_rovinati")


def _staccata() -> ChiavettaStaccata:
    return ChiavettaStaccata(
        "Hai staccato la chiavetta prima della fine: non si è rovinato niente. "
        "Riattaccala e riprendo da dove ero.")


_MESSAGGIO_FAT = (
    "Questa chiavetta è formattata in FAT32, che non tiene i file più grandi di "
    "4 GB. Va formattata in exFAT, e lo fai tu: in Esplora file clic destro "
    "sulla chiavetta, «Formatta…», come file system scegli «exFAT» e premi "
    "«Avvia». Attenzione: formattare cancella tutto quello che c'è sopra, "
    "quindi prima sposta altrove quello che ti serve. Il programma non formatta "
    "mai niente.")


class AggiornaChiavetta(Sottofondo):

    nome = "archivio-sicuro-chiavetta"

    def __init__(self, cartella: Path, elenco, chiave, *, sveglio=sveglia.sveglio,
                 rallenta=None, pausa_se_usi: float = PAUSA_SE_USI,
                 **per_chiavetta):
        super().__init__(sveglio=sveglio, rallenta=rallenta,
                         pausa_se_usi=pausa_se_usi)
        self.elenco = elenco
        self.chiavetta = Chiavetta(cartella, elenco, chiave, aspetta=self._aspetta,
                                   **per_chiavetta)
        self.radice: Path | None = None

    def avvia(self, radice) -> bool:
        partito = self._parti(Path(radice))
        if partito:
            self.radice = Path(radice)
        return partito

    def _azzera(self) -> None:
        self.chiavetta.resoconto = None
        self.chiavetta.avanzamento = Avanzamento()

    def _lavora(self, radice: Path) -> None:
        senza_finestre_di_errore()
        self.chiavetta.aggiorna(radice)

    def _alla_fine(self, esito: str) -> None:
        self.elenco.salva()

    def istantanea(self) -> dict:
        resoconto = self.chiavetta.resoconto or Resoconto()
        avanzamento = self.chiavetta.avanzamento
        return {
            "stato": self.stato,
            "fase": avanzamento.fase,
            "fatti": avanzamento.fatti,
            "totale": avanzamento.totale,
            "byte_fatti": avanzamento.byte_fatti,
            "byte_totali": avanzamento.byte_totali,
            "copiati": resoconto.copiati,
            "byte": resoconto.byte,
            "riletti": resoconto.riletti,
            "ricopiati": len(resoconto.ricopiati),
            "riparati_sulla_chiavetta": len(resoconto.riparati_sulla_chiavetta),
            "rovinati_sulla_chiavetta": len(resoconto.rovinati_sulla_chiavetta),
            "rovinati_sul_pc": len(resoconto.rovinati_sul_pc),
            "riparati_sul_pc": len(resoconto.riparati_sul_pc),
            "persi_sul_pc": len(resoconto.persi_sul_pc),
            "note_rimesse": resoconto.note_rimesse,
            "chiave_rimessa_sul_pc": resoconto.chiave_rimessa_sul_pc,
            "problemi": list(resoconto.problemi),
            "allarme": bool(resoconto.guai),
            "finito": resoconto.finito,
            "frase": resoconto.frase(),
            "errore": self.errore,
            "codice": self.codice,
        }


class Guardiano:

    def __init__(self, lavoro: AggiornaChiavetta, *, dischi=dischi_attaccati,
                 ogni: float = OGNI, adesso=time.monotonic):
        self.lavoro = lavoro
        self.chiavetta = lavoro.chiavetta
        self._dischi = dischi
        self._ogni = ogni
        self._adesso = adesso
        self._serratura = threading.Lock()
        self._fermo = threading.Event()
        self._filo: threading.Thread | None = None
        self.radice: Path | None = None
        self.stato = DA_ATTACCARE
        self.codice: str | None = None
        self.messaggio: str | None = None
        self._partito = False
        self._esito: tuple[str, str | None] | None = None
        self._finito_alle: float | None = None

    def trova(self) -> tuple[Path | None, str | None]:
        altra: tuple[Path | None, str | None] = (None, None)
        for radice in self._dischi():
            chi = self.chiavetta.chi_e(radice)
            if chi in NOSTRE:
                return Path(radice), chi
            if chi in ("diversa", "vecchia", "piu_nuova") and altra[0] is None:
                altra = (Path(radice), chi)
        return altra

    def giro(self) -> str:
        with self._serratura:
            self._giro()
            return self.stato

    def _giro(self) -> None:
        if self.lavoro.acceso:
            self.stato = NON_STACCARLA
            return
        if self._partito:
            self._partito = False
            self._esito = (self.lavoro.stato, self.lavoro.codice)
            self._finito_alle = self._adesso()
        radice, chi = self.trova()
        if radice is None:
            self.radice, self._esito, self._finito_alle = None, None, None
            self._metti(DA_ATTACCARE)
            return
        if chi not in NOSTRE:
            self.radice, self._esito = None, None
            self._metti(DIVERSA, "chiavetta_" + chi if chi != "piu_nuova"
                        else "versione_piu_nuova")
            return
        if radice != self.radice:
            self.radice, self._esito = radice, None
        if self._esito is None or self._da_rifare():
            self._parti(radice)
            return
        stato, codice = self._esito
        if stato == FINITO:
            self._metti(PUOI_STACCARLA)
        elif stato == "fermato":
            self._metti(FERMATA)
        else:
            self._metti(PROBLEMA, codice, self.lavoro.errore)

    def ricomincia(self) -> None:
        with self._serratura:
            self._partito = False
            self._esito = None

    def _da_rifare(self) -> bool:
        stato, codice = self._esito
        if codice == ChiavettaStaccata.codice:
            return True
        if stato != FINITO or self._finito_alle is None:
            return False
        if self._adesso() - self._finito_alle < RIPASSA:
            return False
        if self.chiavetta.mancanti() == (0, 0):
            self._finito_alle = self._adesso()
            return False
        return True

    def _parti(self, radice: Path) -> None:
        if self.lavoro.avvia(radice):
            self._partito = True
            self._esito = None
            self._metti(NON_STACCARLA)
        else:
            self._metti(NON_STACCARLA)

    def _metti(self, stato: str, codice: str | None = None,
               messaggio: str | None = None) -> None:
        self.stato, self.codice, self.messaggio = stato, codice, messaggio

    @property
    def acceso(self) -> bool:
        return self._filo is not None and self._filo.is_alive()

    def avvia(self) -> None:
        if self.acceso:
            return
        self._fermo.clear()
        self._filo = threading.Thread(target=self._gira, name="archivio-sicuro-guardiano",
                                      daemon=True)
        self._filo.start()

    def _gira(self) -> None:
        senza_finestre_di_errore()
        while not self._fermo.is_set():
            try:
                self.giro()
            except Exception:
                with self._serratura:
                    self._metti(PROBLEMA, "guardiano")
            self._fermo.wait(self._ogni)

    def ferma(self, aspetta: float | None = None) -> None:
        self._fermo.set()
        self.lavoro.ferma(aspetta)
        if self._filo is not None and aspetta is not None:
            self._filo.join(aspetta)

    def istantanea(self) -> dict:
        with self._serratura:
            return {"stato": self.stato, "codice": self.codice,
                    "messaggio": self.messaggio,
                    "lavoro": self.lavoro.istantanea(),
                    "chiavetta": self.chiavetta.riassunto()}
