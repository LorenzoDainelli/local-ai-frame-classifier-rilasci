from __future__ import annotations

import hashlib
import os
import sqlite3
import stat
import time
import uuid
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from officina.errori import ErroreOfficina
from officina.sicuro import elenco as registro
from officina.sicuro import formato, metadati, sveglia
from officina.sicuro.chiavetta import (CARTELLA, ChiavettaStaccata, dischi_attaccati,
                                       leggi_segno)
from officina.sicuro.copia import (DA_SALTARE, SEGNI_DA_RIFARE, STATI_BUONI, Copiatore,
                                   _senza_accesso)
from officina.sicuro.dentro import _categoria_di, _numero, _resto, _uguali, _vero
from officina.sicuro.diretto import Lettore
from officina.sicuro.disco import WINDOWS, percorso_lungo
from officina.sicuro.elenco import Elenco
from officina.sicuro.sottofondo import PAUSA_SE_USI, Sottofondo


ESEMPI = 1000
OGNI_QUANTI_PEZZI = 64
VALIDO_PER = 600.0
APPUNTATO = 0x80000
NON_APPUNTATO = 0x100000
NUVOLA = 0x9000001A
MASCHERA_NUVOLA = 0xFFFF0FFF
VARIABILI_NUVOLA = ("OneDrive", "OneDriveConsumer", "OneDriveCommercial")
VARIABILI_SPECIALI = ("USERPROFILE", "PUBLIC", "SystemRoot", "windir", "ProgramFiles",
                      "ProgramFiles(x86)", "ProgramW6432", "ProgramData", "APPDATA",
                      "LOCALAPPDATA", "HOME")
CARTELLE_NOTE = (
    "B4BFCC3A-DB2C-424C-B029-7FE99A87C641",
    "FDD39AD0-238F-46AF-ADB4-6C85480369C7",
    "33E28130-4E1E-4676-835A-98395C3BC3BB",
    "18989B1D-99B5-455B-841C-AB7C74E4DDFC",
    "4BD8D571-6D19-48D3-BE97-422220080E43",
    "374DE290-123F-4565-9164-39C4925E467B",
    "5E6C858F-0E22-4760-9AFE-EA3317B67173",
    "A52BBA46-E9E1-435F-B3D9-28DAA648C0F6",
    "AB5FB87B-7CE2-4F83-915D-550846C9537B",
    "3B193882-D3AD-4EAB-965A-69829D1FB59F",
    "B7BEDE81-DF94-4682-A7D8-57A52620B86F",
    "DFDF76A2-C82A-4D63-906A-5644AC457385",
    "B6EBFB86-6907-413C-9AF7-4FC2ABF07CC5",
    "2400183A-6185-49FB-A2D8-4A392A602BA3",
    "ED4824AF-DCE4-45A8-81E2-FC7965083634",
    "C4AA340D-F20F-4863-AFEF-F87EF2E6BA25",
    "3214FAB5-9757-4298-BB61-92A9DEAA44FF",
    "3D644C9B-1FB8-4F30-9B45-F670235F79C0",
    "0762D272-C50A-4BB0-A382-697DCD729B80",
    "F38BF404-1D43-42F2-9305-67DE0B28FC23",
    "905E63B6-C1BF-494E-B29C-65B732D3D21A",
    "62AB5D82-FDC1-4DC3-A9DD-070D1D495D97",
    "3EB685DB-65F9-4CF6-A03A-E3EF65729F3D",
    "F1B32785-6FBA-4FCF-9D55-7B8E7F157091",
)
LEGGERE_ATTRIBUTI = 0x80
CONDIVISO = 0x1 | 0x2 | 0x4
ESISTENTE = 3
ANCHE_CARTELLE = 0x02000000
SENZA_SEGUIRE = 0x00200000
INFORMAZIONI_DI_BASE = 0
TOLLERATI = frozenset({"file_ritrovati", "nomi_ritrovati"})
AVVISI_BUONI = frozenset({"permessi_illeggibili", "permessi_troppo_lunghi"})
ROSSI_DEGLI_AVVISI = {"file_speciale": "speciale"}
GLOBALI = frozenset({
    "occupato", "archivio_sparito", "archivio_cambiato", "chiavetta_mai_fatta",
    "chiavetta_persa", "chiavetta_da_aggiornare", "chiavetta_da_attaccare",
    "chiavetta_vecchia", "chiavetta_diversa", "due_chiavette", "dentro_l_archivio",
    "dentro_gli_originali", "stesso_disco", "chiave_diversa_sul_pc",
    "chiavetta_senza_chiave", "chiavetta_illeggibile", "chiavetta_elenco_rovinato",
    "chiavetta_cambiata", ChiavettaStaccata.codice})
PAROLE = {
    "manca": "non è nell'archivio",
    "da_ricopiare": "nell'archivio è copiato a metà o mentre era aperto: va ricopiato",
    "rovinato": "nell'archivio è rovinato",
    "diverso": "non torna con l'archivio",
    "da_riparare": "nell'archivio ha un pezzetto rovinato: va riparato",
    "dettagli_diversi": "ha date, attributi o permessi cambiati dopo l'ultima copia",
    "flussi_diversi": "ha dei flussi nascosti che non tornano con l'archivio",
    "flussi_illeggibili": "ha dei flussi nascosti che non si leggono",
    "cartella_mancante": "non è nell'archivio",
    "collegamento_mancante": "è un collegamento che non è nell'archivio",
    "collegamento_diverso": "è un collegamento cambiato dopo l'ultima copia",
    "bersaglio_illeggibile": "è un collegamento e non si legge dove porta",
    "non_sulla_chiavetta": "non è sulla chiavetta come nell'archivio",
    "manca_sulla_chiavetta": "manca sulla chiavetta",
    "rovinato_sulla_chiavetta": "non torna con la chiavetta",
    "da_riparare_sulla_chiavetta": "sulla chiavetta ha un pezzetto rovinato: va riparato",
    "solo_nel_cloud": "è solo nel cloud, non su questo PC",
    "illeggibile": "non si legge",
    "in_uso": "è aperto in un altro programma",
    "cambiato": "è cambiato mentre lo controllavo",
    "nome_strano": "ha un nome che l'archivio non può tenere",
    "speciale": "non è un file normale e l'archivio non lo tiene",
    "cartella_illeggibile": "è una cartella che non si legge",
    "cartella_di_windows": "è una cartella di Windows che l'archivio non copia",
    "c_e_l_archivio": "è la cartella dell'archivio stesso",
    "altro_disco": "è un altro disco attaccato qui dentro",
}
ALTRO = "ha un problema che non conosco"
ORDINE = ("manca", "diverso", "rovinato", "da_ricopiare", "da_riparare",
          "manca_sulla_chiavetta", "rovinato_sulla_chiavetta",
          "da_riparare_sulla_chiavetta", "non_sulla_chiavetta", "flussi_diversi",
          "flussi_illeggibili", "solo_nel_cloud", "in_uso", "illeggibile", "cambiato",
          "speciale", "nome_strano", "cartella_di_windows", "c_e_l_archivio",
          "altro_disco", "cartella_illeggibile", "collegamento_mancante",
          "collegamento_diverso", "bersaglio_illeggibile", "cartella_mancante",
          "dettagli_diversi")
DIVERSO_DA_PRIMA = "diverso_da_prima"
_FINE = object()


def _gravita(categoria: str) -> int:
    return ORDINE.index(categoria) if categoria in ORDINE else len(ORDINE)


class _Rosso(Exception):

    def __init__(self, categoria: str):
        super().__init__(categoria)
        self.categoria = categoria


@dataclass
class Esame:
    cartella: str
    vero: str
    radici: list[tuple[str, str]]
    solo_dentro: bool
    chiavetta: str
    disco: str
    inizio: float
    fine: float | None = None
    sincronizzata: bool = False
    file: int = 0
    byte: int = 0
    cartelle: int = 0
    collegamenti: int = 0
    bersagli: list[dict] = field(default_factory=list)
    conti: Counter = field(default_factory=Counter)
    esempi: dict[str, list[str]] = field(default_factory=dict)
    avvisi: Counter = field(default_factory=Counter)
    contenuti: set[str] = field(default_factory=set)
    posti: set[str] = field(default_factory=set)
    dove_posti: dict[str, str] = field(default_factory=dict)
    da_controllare: set[str] = field(default_factory=set)
    da_rileggere: set[str] = field(default_factory=set)
    impronta: dict[str, tuple] = field(default_factory=dict)

    def segna(self, categoria: str, relativo: str) -> None:
        self.conti[categoria] += 1
        esempi = self.esempi.setdefault(categoria, [])
        if len(esempi) < ESEMPI:
            esempi.append(relativo)

    def avvisa(self, avviso: str) -> None:
        self.avvisi[avviso] += 1

    def tieni(self, chiave: str, relativo: str) -> None:
        self.posti.add(chiave)
        self.dove_posti[chiave] = relativo

    def vuoto(self) -> Esame:
        return Esame(cartella=self.cartella, vero=self.vero, radici=list(self.radici),
                     solo_dentro=self.solo_dentro, chiavetta=self.chiavetta,
                     disco=self.disco, inizio=self.inizio)

    @property
    def rossi(self) -> dict[str, int]:
        return {categoria: quanti for categoria, quanti in self.conti.items() if quanti}

    @property
    def primo(self) -> tuple[str, str] | None:
        rossi = self.rossi
        if not rossi:
            return None
        categoria = min(rossi, key=_gravita)
        return categoria, self.esempi[categoria][0]

    @property
    def verde(self) -> bool:
        return self.fine is not None and not self.rossi

    def fresco(self, adesso: float) -> bool:
        return self.verde and 0.0 <= adesso - self.fine <= VALIDO_PER

    def nome(self, relativo: str) -> str:
        if relativo:
            return relativo
        return os.path.basename(self.cartella.rstrip("\\/")) or self.cartella

    def frase(self) -> str:
        if self.fine is None:
            return "Il controllo non è finito: la cartella resta rossa."
        if self.verde:
            if not self.file:
                return ("Verde: qui non ci sono file, e le cartelle sono "
                        "nell'archivio e sulla chiavetta.")
            parola = "il file è uguale" if self.file == 1 else (
                f"tutti i {_numero(self.file)} file sono uguali")
            return f"Verde: {parola}, byte per byte, nell'archivio e sulla chiavetta."
        categoria, relativo = self.primo
        frase = f"{self.nome(relativo)} {PAROLE.get(categoria, ALTRO)}."
        altri = sum(self.conti.values()) - 1
        if altri == 1:
            frase += " E c'è un altro problema."
        elif altri:
            frase += f" E ci sono altri {_numero(altri)} problemi."
        return frase + " La rossa non si tocca."

    def istantanea(self) -> dict:
        return {
            "cartella": self.cartella,
            "radici": [list(vicina) for vicina in self.radici],
            "solo_dentro": self.solo_dentro,
            "inizio": self.inizio,
            "fine": self.fine,
            "valido_fino": None if self.fine is None else self.fine + VALIDO_PER,
            "file": self.file,
            "byte": self.byte,
            "cartelle": self.cartelle,
            "collegamenti": self.collegamenti,
            "bersagli": [dict(bersaglio) for bersaglio in self.bersagli],
            "verde": self.verde,
            "frase": self.frase(),
            "rossi": self.rossi,
            "primo": None if self.primo is None else list(self.primo),
            "esempi": {categoria: list(esempi) for categoria, esempi in self.esempi.items()},
            "avvisi": dict(self.avvisi),
            "sincronizzata": self.sincronizzata,
            "da_controllare": sorted(self.da_controllare),
            "da_rileggere": sorted(self.da_rileggere),
        }


@dataclass
class Avanzamento:
    cartella: str | None = None
    percorso: str | None = None
    file: int = 0
    letti: int = 0


@dataclass
class _Scelta:
    testo: str
    assoluto: str
    vero: str
    radici: list[tuple[str, str]]
    solo_dentro: bool
    sincronizzata: bool


@dataclass
class _Riserva:
    disco: Path
    identita: str
    elenco: Elenco


def _kernel32():
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.CreateFileW.argtypes = (
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
        wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE)
    kernel32.GetFileInformationByHandleEx.restype = wintypes.BOOL
    kernel32.GetFileInformationByHandleEx.argtypes = (
        wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD)
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    return kernel32


def cambio_windows(percorso: str) -> int:
    import ctypes
    from ctypes import wintypes

    class Base(ctypes.Structure):
        _fields_ = [("CreationTime", ctypes.c_longlong),
                    ("LastAccessTime", ctypes.c_longlong),
                    ("LastWriteTime", ctypes.c_longlong),
                    ("ChangeTime", ctypes.c_longlong),
                    ("FileAttributes", wintypes.DWORD)]

    kernel32 = _kernel32()
    maniglia = kernel32.CreateFileW(percorso_lungo(percorso), LEGGERE_ATTRIBUTI, CONDIVISO,
                                    None, ESISTENTE, ANCHE_CARTELLE | SENZA_SEGUIRE, None)
    if maniglia in (None, wintypes.HANDLE(-1).value):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        base = Base()
        if not kernel32.GetFileInformationByHandleEx(maniglia, INFORMAZIONI_DI_BASE,
                                                     ctypes.byref(base),
                                                     ctypes.sizeof(base)):
            raise ctypes.WinError(ctypes.get_last_error())
        return int(base.ChangeTime)
    finally:
        kernel32.CloseHandle(maniglia)


def _cartelle_note() -> list[str]:
    import ctypes

    try:
        shell32 = ctypes.WinDLL("shell32")
        ole32 = ctypes.WinDLL("ole32")
    except OSError:
        return []
    shell32.SHGetKnownFolderPath.restype = ctypes.c_long
    shell32.SHGetKnownFolderPath.argtypes = (ctypes.c_void_p, ctypes.c_uint32,
                                             ctypes.c_void_p, ctypes.c_void_p)
    ole32.CoTaskMemFree.restype = None
    ole32.CoTaskMemFree.argtypes = (ctypes.c_void_p,)
    trovate = []
    for testo in CARTELLE_NOTE:
        codice = (ctypes.c_ubyte * 16).from_buffer_copy(uuid.UUID(testo).bytes_le)
        risposta = ctypes.c_void_p()
        esito = shell32.SHGetKnownFolderPath(ctypes.byref(codice), 0, None,
                                             ctypes.byref(risposta))
        try:
            if esito == 0 and risposta.value:
                trovate.append(ctypes.wstring_at(risposta.value))
        finally:
            if risposta.value:
                ole32.CoTaskMemFree(risposta)
    return trovate


def cartelle_speciali() -> list[str]:
    trovate = [os.environ[nome] for nome in VARIABILI_SPECIALI if os.environ.get(nome)]
    if WINDOWS:
        trovate += _cartelle_note()
    return trovate


def cartelle_nel_cloud() -> list[str]:
    return [os.environ[nome] for nome in VARIABILI_NUVOLA if os.environ.get(nome)]


def sincronizzato(stato) -> bool:
    attributi = getattr(stato, "st_file_attributes", 0) or 0
    rimando = getattr(stato, "st_reparse_tag", 0) or 0
    return (bool(attributi & (APPUNTATO | NON_APPUNTATO))
            or rimando & MASCHERA_NUVOLA == NUVOLA)


def _nel(sopra: str, relativo: str) -> str:
    if sopra and relativo:
        return f"{sopra}/{relativo}"
    return sopra or relativo


def _staccata() -> ChiavettaStaccata:
    return ChiavettaStaccata(
        "Hai staccato la chiavetta durante il controllo: non è successo niente. "
        "Riattaccala e rifai il controllo.")


class Esaminatore:

    def __init__(self, cartella: Path, elenco, chiave, chiavetta, *, apri=Lettore,
                 aspetta=None, dischi=dischi_attaccati, occupato=None, salta=(),
                 adesso=time.time, leggi=metadati.leggi,
                 flusso=metadati.percorso_del_flusso,
                 cambio=cambio_windows if WINDOWS else None,
                 speciali=cartelle_speciali, nuvole=cartelle_nel_cloud):
        self.cartella = Path(cartella)
        self.elenco = elenco
        self._chiave = chiave
        self.chiavetta = chiavetta
        self._apri = apri
        self._aspetta = aspetta
        self._dischi = dischi
        self._occupato = occupato
        self._salta = tuple(salta)
        self._adesso = adesso
        self._leggi = leggi
        self._flusso = flusso
        self._cambio = cambio
        self._speciali = speciali
        self._nuvole = nuvole
        self._camminatore = Copiatore(self.cartella, elenco, chiave, salta=salta)
        self.avanzamento = Avanzamento()
        self.esame: Esame | None = None
        self.esami: list[Esame] = []
        self.errori: dict[str, ErroreOfficina] = {}

    def azzera(self) -> None:
        self.avanzamento = Avanzamento()
        self.esame = None
        self.esami = []
        self.errori = {}

    def _ferma_se_serve(self) -> None:
        if self._aspetta is not None:
            self._aspetta()

    def _archivio_c_e(self) -> None:
        dove = percorso_lungo(self.cartella / registro.CONTENUTI)
        try:
            stato = os.lstat(dove)
        except (OSError, ValueError):
            stato = None
        if stato is None or not stat.S_ISDIR(stato.st_mode):
            raise ErroreOfficina(
                "Il disco dell'Archivio sicuro non si legge più: ricollegalo e "
                "rifai il controllo.", codice="archivio_sparito")

    @staticmethod
    def _ancora_attaccata(disco: Path, identita: str) -> None:
        segno = leggi_segno(disco)
        if segno is None or segno["chiavetta"] != identita:
            raise _staccata()

    def _prima(self) -> _Riserva:
        if self._occupato is not None and self._occupato():
            raise ErroreOfficina(
                "L'archivio sta già lavorando: aspetta che finisca e poi rifai il "
                "controllo.", codice="occupato")
        self._archivio_c_e()
        chiavetta = self.chiavetta
        identita = chiavetta.identita
        if identita is None:
            raise ErroreOfficina(
                "Per il via libera serve la chiavetta di riserva, e non è ancora "
                "preparata.", codice="chiavetta_mai_fatta")
        if chiavetta.persa:
            raise ErroreOfficina(
                "La chiavetta di riserva è segnata come persa: preparane una nuova "
                "prima del via libera.", codice="chiavetta_persa")
        if chiavetta.ultima is None:
            raise ErroreOfficina(
                "La chiavetta non ha ancora finito il primo aggiornamento: "
                "aggiornala prima del via libera.", codice="chiavetta_da_aggiornare")
        trovate: list[Path] = []
        altre: list[str] = []
        for disco in self._dischi():
            chi = chiavetta.chi_e(disco)
            if chi == "nostra":
                trovate.append(Path(disco))
            elif chi in ("vecchia", "diversa", "piu_nuova", "rovinata"):
                altre.append(chi)
        if len(trovate) > 1:
            raise ErroreOfficina(
                "Ci sono due chiavette uguali dell'archivio attaccate: lasciane "
                "attaccata una sola.", codice="due_chiavette")
        if not trovate:
            if "rovinata" in altre:
                raise ErroreOfficina(
                    "Sulla chiavetta attaccata il segno dell'archivio non si legge: "
                    "aggiornala e riprova.", codice="chiavetta_illeggibile")
            if "vecchia" in altre:
                raise ErroreOfficina(
                    "Questa è una vecchia chiavetta dell'archivio, non quella di "
                    "adesso: attacca quella giusta.", codice="chiavetta_vecchia")
            if altre:
                raise ErroreOfficina(
                    "La chiavetta attaccata non è quella di questo archivio: "
                    "attacca quella giusta.", codice="chiavetta_diversa")
            raise ErroreOfficina(
                "Per il via libera la chiavetta di riserva deve essere attaccata: "
                "attaccala e riprova.", codice="chiavetta_da_attaccare")
        disco = trovate[0]
        problema = chiavetta.posto_sbagliato(disco)
        if problema is not None:
            raise ErroreOfficina(problema[1], codice=problema[0])
        if not chiavetta.chiave_del_pc_a_posto():
            raise ErroreOfficina(
                "Sul PC una delle due copie della chiave dell'archivio manca o non è "
                "uguale all'altra: chiudi e riapri il programma, poi riprova.",
                codice="chiave_diversa_sul_pc")
        if not chiavetta.chiave_uguale(disco):
            self._ancora_attaccata(disco, identita)
            raise ErroreOfficina(
                "Sulla chiavetta la chiave dell'archivio manca o non è uguale: "
                "aggiorna la chiavetta e riprova.", codice="chiavetta_senza_chiave")
        try:
            sopra = Elenco.apri(disco / CARTELLA, self._chiave, sola_lettura=True)
        except (ErroreOfficina, OSError, ValueError, sqlite3.Error):
            self._ancora_attaccata(disco, identita)
            raise ErroreOfficina(
                "L'elenco sulla chiavetta non si legge: aggiorna la chiavetta e "
                "riprova.", codice="chiavetta_illeggibile") from None
        if set(sopra.problemi) - TOLLERATI or not self._fotografia_buona(sopra):
            sopra.chiudi()
            self._ancora_attaccata(disco, identita)
            raise ErroreOfficina(
                "L'elenco sulla chiavetta è rovinato: aggiorna la chiavetta e "
                "riprova.", codice="chiavetta_elenco_rovinato")
        return _Riserva(disco, identita, sopra)

    def _fotografia_buona(self, sopra: Elenco) -> bool:
        fotografia = sopra.fotografia_attuale()
        if fotografia is None:
            return False
        try:
            with self._apri(fotografia, True) as lettore:
                return formato.controlla(lettore, self._chiave).buono
        except (ErroreOfficina, OSError, ValueError):
            return False

    def _scelta(self, testo: str, riserva: _Riserva) -> _Scelta:
        assoluto = os.path.abspath(testo)
        try:
            stato = os.lstat(percorso_lungo(assoluto))
        except FileNotFoundError:
            raise ErroreOfficina("Questa cartella non c'è più.",
                                 codice="cartella_sparita") from None
        except (OSError, ValueError):
            raise ErroreOfficina("Questa cartella non si legge.",
                                 codice="cartella_illeggibile") from None
        if metadati.tipo_di(stato) == metadati.COLLEGAMENTO:
            raise ErroreOfficina(
                "Questo è un collegamento a un'altra cartella: scegli la cartella "
                "vera.", codice="e_un_collegamento")
        if not stat.S_ISDIR(stato.st_mode):
            raise ErroreOfficina("Qui serve una cartella, non un file.",
                                 codice="non_una_cartella")
        vero = _vero(assoluto)
        if _uguali(vero, os.path.dirname(vero)) or os.path.ismount(vero):
            raise ErroreOfficina(
                "Questo è un disco intero: scegli le cartelle che ci sono dentro.",
                codice="radice_di_un_disco")
        archivio = _vero(self.cartella)
        if _resto(archivio, vero) is not None:
            raise ErroreOfficina(
                "Questa è la cartella dell'Archivio sicuro: dentro ci sono solo i "
                "file cifrati.", codice="nell_archivio")
        chiavetta = _vero(riserva.disco)
        if _resto(chiavetta, vero) is not None:
            raise ErroreOfficina(
                "Questa cartella è sulla chiavetta di riserva: lì non si cancella "
                "niente.", codice="sulla_chiavetta")
        for protetta in (archivio, chiavetta):
            if _resto(vero, protetta) is not None:
                raise ErroreOfficina(
                    "Dentro questa cartella c'è l'Archivio sicuro o la chiavetta: "
                    "non si può mandare nel Cestino.", codice="contiene_l_archivio")
        for cartella in self._salta:
            saltata = _vero(cartella)
            if _resto(saltata, vero) is not None or _resto(vero, saltata) is not None:
                raise ErroreOfficina(
                    "In questa cartella c'è una parte che l'archivio non copia: non "
                    "si può mandare nel Cestino.", codice="contiene_una_saltata")
        solo_dentro = False
        for speciale in self._speciali():
            speciale = _vero(speciale)
            if _uguali(vero, speciale):
                solo_dentro = True
            elif _resto(vero, speciale) is not None:
                raise ErroreOfficina(
                    "Dentro questa cartella ci sono cartelle speciali di Windows, "
                    "come Immagini o Desktop: scegli le cartelle che ci sono dentro.",
                    codice="contiene_cartelle_di_windows")
        radici = []
        for radice in self.elenco.radici():
            if radice["tolta"]:
                continue
            sopra = _resto(_vero(radice["percorso"]), vero)
            if sopra is not None:
                radici.append((radice["id"], sopra))
        if not radici:
            raise ErroreOfficina(
                "Questa cartella non è fra quelle che copio nell'archivio: prima "
                "aggiungila e fai la copia.", codice="fuori_dalle_cartelle")
        for _, sopra in radici:
            parti = sopra.split("/") if sopra else []
            if any(parte.casefold() in DA_SALTARE for parte in parti):
                raise ErroreOfficina(
                    "Questa è una cartella di Windows che l'archivio non copia.",
                    codice="cartella_di_windows")
            try:
                pulito = registro.percorso_pulito(sopra) == sopra
            except ValueError:
                pulito = False
            if not pulito:
                raise ErroreOfficina(
                    "Questa cartella ha un nome che l'archivio non può tenere.",
                    codice="nome_strano")
        solo_dentro = solo_dentro or any(not sopra for _, sopra in radici)
        nuvola = any(_resto(_vero(cartella), vero) is not None
                     for cartella in self._nuvole())
        return _Scelta(testo, assoluto, vero, sorted(radici), solo_dentro, nuvola)

    def esamina(self, percorso) -> Esame:
        esami, errori = self.tutte([percorso])
        if errori:
            raise next(iter(errori.values()))
        return esami[0]

    def tutte(self, percorsi) -> tuple[list[Esame], dict[str, ErroreOfficina]]:
        self.azzera()
        testi = [os.fspath(percorso) for percorso in percorsi]
        riserva = self._prima()
        try:
            scelte: list[_Scelta] = []
            for testo in testi:
                try:
                    scelte.append(self._scelta(testo, riserva))
                except ErroreOfficina as errore:
                    if errore.codice in GLOBALI:
                        raise
                    self.errori[testo] = errore
            for scelta in self._non_annidate(scelte):
                try:
                    self.esami.append(self._esamina(scelta, riserva))
                except ErroreOfficina as errore:
                    if errore.codice in GLOBALI:
                        raise
                    self.errori[scelta.testo] = errore
        except BaseException:
            self.esami = []
            raise
        finally:
            self.esame = None
            self.avanzamento.percorso = None
            riserva.elenco.chiudi()
        return list(self.esami), dict(self.errori)

    def _non_annidate(self, scelte: list[_Scelta]) -> list[_Scelta]:
        buone: list[_Scelta] = []
        for posizione, scelta in enumerate(scelte):
            if any(_uguali(altra.vero, scelta.vero) for altra in scelte[:posizione]):
                if scelta.testo not in self.errori and not any(
                        altra.testo == scelta.testo for altra in buone):
                    self.errori[scelta.testo] = ErroreOfficina(
                        "Questa cartella l'hai già scelta.", codice="gia_scelta")
                continue
            if any(not _uguali(altra.vero, scelta.vero)
                   and _resto(altra.vero, scelta.vero) is not None for altra in scelte):
                self.errori[scelta.testo] = ErroreOfficina(
                    "Questa cartella è già dentro un'altra che hai scelto.",
                    codice="dentro_un_altra")
                continue
            buone.append(scelta)
        return buone

    def _esamina(self, scelta: _Scelta, riserva: _Riserva) -> Esame:
        esame = Esame(cartella=scelta.assoluto, vero=scelta.vero, radici=scelta.radici,
                      solo_dentro=scelta.solo_dentro, chiavetta=riserva.identita,
                      disco=os.fspath(riserva.disco), inizio=self._adesso(),
                      sincronizzata=scelta.sincronizzata)
        if esame.sincronizzata:
            esame.avvisa("sincronizzato")
        self.esame = esame
        self.avanzamento = Avanzamento(cartella=scelta.assoluto)
        try:
            stato = os.lstat(percorso_lungo(esame.vero))
        except FileNotFoundError:
            raise ErroreOfficina("Questa cartella non c'è più.",
                                 codice="cartella_sparita") from None
        except OSError:
            raise ErroreOfficina("Questa cartella non si legge.",
                                 codice="cartella_illeggibile") from None
        if esame.solo_dentro:
            try:
                esame.impronta[""] = self._impronta(esame.vero, stato)
            except _Rosso as rosso:
                esame.segna(rosso.categoria, "")
        else:
            self._una_voce(esame, riserva, "", esame.vero, stato)
        saltare = self._camminatore._da_saltare()
        for relativo, assoluto, figlio in self._cammina(esame, saltare, stato.st_dev):
            self._ferma_se_serve()
            self.avanzamento.percorso = relativo
            self._una_voce(esame, riserva, relativo, assoluto, figlio)
        self.avanzamento.percorso = None
        self._ricontrolla_cartelle(esame)
        self._archivio_c_e()
        self._ancora_attaccata(riserva.disco, riserva.identita)
        esame.fine = self._adesso()
        return esame

    def _cammina(self, esame: Esame, saltare, disco: int):
        pila = [""]
        while pila:
            relativo = pila.pop()
            self._ferma_se_serve()
            try:
                with os.scandir(percorso_lungo(
                        Copiatore._assoluto(esame.vero, relativo))) as voci:
                    nomi = sorted(voce.name for voce in voci)
            except OSError:
                esame.segna("cartella_illeggibile", relativo)
                continue
            figli = []
            for nome in nomi:
                figlio = f"{relativo}/{nome}" if relativo else nome
                if nome.casefold() in DA_SALTARE:
                    esame.segna("cartella_di_windows", figlio)
                    continue
                if not all(Copiatore._nome_buono(nome, _nel(sopra, figlio))
                           for _, sopra in esame.radici):
                    esame.segna("nome_strano", figlio)
                    continue
                assoluto = Copiatore._assoluto(esame.vero, figlio)
                try:
                    stato = os.lstat(percorso_lungo(assoluto))
                except FileNotFoundError:
                    esame.segna("cambiato", figlio)
                    continue
                except OSError as guasto:
                    esame.segna(_categoria_di(guasto), figlio)
                    continue
                if metadati.tipo_di(stato) == metadati.CARTELLA:
                    if Copiatore._saltata(assoluto, stato, saltare):
                        esame.segna("c_e_l_archivio", figlio)
                        continue
                    if stato.st_dev != disco:
                        esame.segna("altro_disco", figlio)
                        continue
                    esame.cartelle += 1
                    figli.append(figlio)
                yield figlio, assoluto, stato
            pila.extend(reversed(figli))

    def _impronta(self, assoluto: str, stato) -> tuple:
        cambio = None
        if self._cambio is not None:
            try:
                cambio = self._cambio(assoluto)
            except FileNotFoundError:
                raise _Rosso("cambiato") from None
            except OSError as guasto:
                raise _Rosso(_categoria_di(guasto)) from guasto
        return (*metadati.segno_di(stato),
                int(getattr(stato, "st_file_attributes", 0) or 0),
                int(getattr(stato, "st_reparse_tag", 0) or 0), cambio)

    def _ancora_lui(self, assoluto: str, impronta: tuple) -> None:
        try:
            dopo = os.lstat(percorso_lungo(assoluto))
        except FileNotFoundError:
            raise _Rosso("cambiato") from None
        except OSError as guasto:
            raise _Rosso(_categoria_di(guasto)) from guasto
        if self._impronta(assoluto, dopo) != impronta:
            raise _Rosso("cambiato")

    def _ricontrolla_cartelle(self, esame: Esame) -> None:
        for relativo, impronta in list(esame.impronta.items()):
            if impronta[0] != metadati.CARTELLA:
                continue
            try:
                self._ancora_lui(Copiatore._assoluto(esame.vero, relativo), impronta)
            except _Rosso as rosso:
                esame.segna(rosso.categoria, relativo)

    def _una_voce(self, esame: Esame, riserva: _Riserva, relativo: str, assoluto: str,
                  stato) -> None:
        try:
            self._voce(esame, riserva, relativo, assoluto, stato)
        except _Rosso as rosso:
            esame.segna(rosso.categoria, relativo)

    def _voce(self, esame: Esame, riserva: _Riserva, relativo: str, assoluto: str,
              stato) -> None:
        impronta = self._impronta(assoluto, stato)
        esame.impronta[relativo] = impronta
        if sincronizzato(stato) and not esame.sincronizzata:
            esame.sincronizzata = True
            esame.avvisa("sincronizzato")
        try:
            letto = self._leggi(assoluto, stato)
        except FileNotFoundError:
            raise _Rosso("cambiato") from None
        except OSError as guasto:
            raise _Rosso(_categoria_di(guasto)) from guasto
        for avviso in letto.avvisi:
            if avviso not in AVVISI_BUONI:
                raise _Rosso(ROSSI_DEGLI_AVVISI.get(avviso, avviso))
            esame.avvisa(avviso)
        if letto.cloud:
            raise _Rosso("solo_nel_cloud")
        if letto.tipo == metadati.CARTELLA:
            self._cartella(esame, riserva, relativo, letto)
        elif letto.tipo == metadati.COLLEGAMENTO:
            self._collegamento(esame, riserva, relativo, letto)
        elif letto.tipo == metadati.FILE:
            self._file(esame, riserva, relativo, assoluto, letto)
        else:
            raise _Rosso("speciale")
        self._ancora_lui(assoluto, impronta)

    def _dove(self, esame: Esame, relativo: str):
        for radice, sopra in esame.radici:
            yield radice, _nel(sopra, relativo)

    @staticmethod
    def _attuale(elenco, radice: str, nel: str):
        try:
            return elenco.attuale(radice, nel)
        except ValueError:
            raise _Rosso("nome_strano") from None

    def _cartella(self, esame: Esame, riserva: _Riserva, relativo: str, letto) -> None:
        if letto.flussi:
            raise _Rosso("flussi_diversi")
        dettagli = _senza_accesso(letto.metadati)
        for radice, nel in self._dove(esame, relativo):
            posto = self._attuale(self.elenco, radice, nel)
            if posto is None or posto.tipo != metadati.CARTELLA:
                raise _Rosso("cartella_mancante")
            if _senza_accesso(posto.metadati) != dettagli:
                raise _Rosso("dettagli_diversi")
            sopra = self._attuale(riserva.elenco, radice, nel)
            if (sopra is None or sopra.tipo != metadati.CARTELLA
                    or _senza_accesso(sopra.metadati) != dettagli):
                raise _Rosso("non_sulla_chiavetta")
            esame.tieni(posto.chiave, relativo)

    def _collegamento(self, esame: Esame, riserva: _Riserva, relativo: str,
                      letto) -> None:
        dettagli = _senza_accesso(letto.metadati)
        for radice, nel in self._dove(esame, relativo):
            posto = self._attuale(self.elenco, radice, nel)
            if posto is None or posto.tipo != metadati.COLLEGAMENTO:
                raise _Rosso("collegamento_mancante")
            if _senza_accesso(posto.metadati) != dettagli:
                raise _Rosso("collegamento_diverso")
            sopra = self._attuale(riserva.elenco, radice, nel)
            if (sopra is None or sopra.tipo != metadati.COLLEGAMENTO
                    or _senza_accesso(sopra.metadati) != dettagli):
                raise _Rosso("non_sulla_chiavetta")
            esame.tieni(posto.chiave, relativo)
        esame.collegamenti += 1
        if len(esame.bersagli) < ESEMPI:
            esame.bersagli.append({
                "percorso": relativo,
                "genere": letto.metadati.get("collegamento"),
                "bersaglio": letto.metadati.get("bersaglio"),
                "verso_cartella": bool(letto.metadati.get("verso_cartella"))})

    def _informazioni(self, esame: Esame, numero: str, dimensione: int,
                      diverso: str = "diverso") -> dict:
        informazioni = self.elenco.contenuto(numero)
        if informazioni is None:
            raise _Rosso("manca")
        if informazioni["stato"] == "incompleto":
            raise _Rosso("da_ricopiare")
        if informazioni["stato"] not in STATI_BUONI:
            esame.da_controllare.add(numero)
            raise _Rosso("rovinato")
        if informazioni["dimensione"] != dimensione:
            raise _Rosso(diverso)
        return informazioni

    def _stesso_contenuto(self, sopra, numero: str) -> bool:
        qui = self.elenco.contenuto(numero)
        la = sopra.contenuto(numero)
        return (qui is not None and la is not None and la["stato"] in STATI_BUONI
                and all(la[chiave] == qui[chiave]
                        for chiave in ("dimensione", "blake2b", "sha256", "peso",
                                       "testa")))

    def _file(self, esame: Esame, riserva: _Riserva, relativo: str, assoluto: str,
              letto) -> None:
        esame.file += 1
        esame.byte += letto.dimensione
        self.avanzamento.file += 1
        grandezze = dict(letto.flussi)
        if (len(grandezze) != len(letto.flussi)
                or not all(metadati.nome_di_flusso_buono(nome) for nome in grandezze)):
            raise _Rosso("flussi_diversi")
        dettagli = _senza_accesso(letto.metadati)
        principali: dict[str, dict] = {}
        nascosti: dict[str, dict[str, dict]] = {}
        for radice, nel in self._dove(esame, relativo):
            posto = self._attuale(self.elenco, radice, nel)
            if posto is None or posto.tipo != metadati.FILE or posto.contenuto is None:
                raise _Rosso("manca")
            if SEGNI_DA_RIFARE & set(posto.segni):
                raise _Rosso("da_ricopiare")
            if DIVERSO_DA_PRIMA in posto.segni:
                esame.avvisa(DIVERSO_DA_PRIMA)
            principali[posto.contenuto] = self._informazioni(esame, posto.contenuto,
                                                             letto.dimensione)
            if _senza_accesso(posto.metadati) != dettagli:
                raise _Rosso("dettagli_diversi")
            salvati = dict(self.elenco.flussi_di(posto.chiave))
            if set(salvati) != set(grandezze):
                raise _Rosso("flussi_diversi")
            for nome, numero in salvati.items():
                nascosti.setdefault(nome, {})[numero] = self._informazioni(
                    esame, numero, grandezze[nome], "flussi_diversi")
            sopra = self._attuale(riserva.elenco, radice, nel)
            if (sopra is None or sopra.tipo != metadati.FILE
                    or sopra.contenuto != posto.contenuto
                    or _senza_accesso(sopra.metadati) != dettagli
                    or dict(riserva.elenco.flussi_di(sopra.chiave)) != salvati
                    or not all(self._stesso_contenuto(riserva.elenco, numero)
                               for numero in (posto.contenuto, *salvati.values()))):
                raise _Rosso("non_sulla_chiavetta")
            esame.tieni(posto.chiave, relativo)
        for numero, informazioni in principali.items():
            self._byte_per_byte(esame, riserva, assoluto, numero, informazioni)
        for nome in sorted(nascosti):
            try:
                dove = self._flusso(assoluto, nome)
            except ErroreOfficina:
                raise _Rosso("flussi_diversi") from None
            for numero, informazioni in nascosti[nome].items():
                self._byte_per_byte(esame, riserva, dove, numero, informazioni,
                                    "flussi_diversi")

    def _blob(self, percorso: Path):
        try:
            stato = os.lstat(percorso_lungo(percorso))
        except (OSError, ValueError):
            return None
        return stato if stat.S_ISREG(stato.st_mode) else None

    def _byte_per_byte(self, esame: Esame, riserva: _Riserva, sorgente: str,
                       numero: str, informazioni: dict, diverso: str = "diverso") -> None:
        esame.contenuti.add(numero)
        qui = registro.percorso_contenuto(self.cartella, numero)
        la = registro.percorso_contenuto(riserva.disco / CARTELLA, numero)
        stato_qui = self._blob(qui)
        if stato_qui is None:
            self._archivio_c_e()
            esame.da_controllare.add(numero)
            raise _Rosso("rovinato")
        stato_la = self._blob(la)
        if stato_la is None or (stato_la.st_ino and (stato_la.st_dev, stato_la.st_ino)
                                == (stato_qui.st_dev, stato_qui.st_ino)):
            self._ancora_attaccata(riserva.disco, riserva.identita)
            raise _Rosso("manca_sulla_chiavetta")
        try:
            originale = self._apri(sorgente, True)
        except FileNotFoundError:
            raise _Rosso("cambiato") from None
        except OSError as guasto:
            raise _Rosso(_categoria_di(guasto)) from guasto
        with originale:
            if originale.dimensione != informazioni["dimensione"]:
                raise _Rosso("cambiato")
            try:
                copia = self._apri(qui, True)
            except OSError:
                self._archivio_c_e()
                esame.da_controllare.add(numero)
                raise _Rosso("rovinato") from None
            with copia:
                try:
                    riserva_aperta = self._apri(la, True)
                except OSError:
                    self._ancora_attaccata(riserva.disco, riserva.identita)
                    esame.da_rileggere.add(numero)
                    raise _Rosso("rovinato_sulla_chiavetta") from None
                with riserva_aperta:
                    self._insieme(esame, riserva, originale, copia, riserva_aperta,
                                  numero, informazioni, diverso)

    def _rilettura(self, file, numero: str, informazioni: dict, attese: dict):
        try:
            return formato.Rilettura(file, self._chiave, numero=bytes.fromhex(numero),
                                     testa=informazioni["testa"], impronte=attese)
        except (ErroreOfficina, OSError, ValueError):
            return None

    def _rovinato_qui(self, esame: Esame, numero: str) -> _Rosso:
        self._archivio_c_e()
        esame.da_controllare.add(numero)
        return _Rosso("rovinato")

    def _rovinato_la(self, esame: Esame, riserva: _Riserva, numero: str) -> _Rosso:
        self._ancora_attaccata(riserva.disco, riserva.identita)
        esame.da_rileggere.add(numero)
        return _Rosso("rovinato_sulla_chiavetta")

    def _insieme(self, esame: Esame, riserva: _Riserva, originale, copia, altra,
                 numero: str, informazioni: dict, diverso: str) -> None:
        attese = {"blake2b": informazioni["blake2b"], "sha256": informazioni["sha256"]}
        sul_pc = self._rilettura(copia, numero, informazioni, attese)
        if sul_pc is None:
            raise self._rovinato_qui(esame, numero)
        sulla_chiavetta = self._rilettura(altra, numero, informazioni, attese)
        pezzi_qui = iter(sul_pc)
        pezzi_la = None if sulla_chiavetta is None else iter(sulla_chiavetta)
        storta = pezzi_la is None
        blake = hashlib.blake2b(digest_size=formato.IMPRONTA)
        sha = hashlib.sha256()
        dove = 0
        pezzi = 0
        while True:
            try:
                pezzo = next(pezzi_qui, _FINE)
            except (ErroreOfficina, OSError, ValueError):
                raise self._rovinato_qui(esame, numero) from None
            if pezzo is _FINE:
                break
            pezzi += 1
            if pezzi % OGNI_QUANTI_PEZZI == 0:
                self._ferma_se_serve()
            try:
                originale.seek(dove)
                letto = originale.read(len(pezzo))
            except OSError as guasto:
                raise _Rosso(_categoria_di(guasto)) from guasto
            if len(letto) != len(pezzo):
                raise _Rosso("cambiato")
            if letto != pezzo:
                raise _Rosso(diverso)
            blake.update(letto)
            sha.update(letto)
            dove += len(letto)
            self.avanzamento.letti += len(letto)
            if not storta:
                try:
                    altro = next(pezzi_la, _FINE)
                except (ErroreOfficina, OSError, ValueError):
                    altro = _FINE
                storta = altro is _FINE or altro != pezzo
        controllo = sul_pc.controllo
        if controllo is None or not controllo.leggibile:
            raise self._rovinato_qui(esame, numero)
        if (dove != informazioni["dimensione"]
                or {"blake2b": blake.hexdigest(), "sha256": sha.hexdigest()} != attese):
            raise _Rosso(diverso)
        if not storta:
            try:
                storta = next(pezzi_la, _FINE) is not _FINE
            except (ErroreOfficina, OSError, ValueError):
                storta = True
        controllo_la = None if storta else sulla_chiavetta.controllo
        if controllo_la is None or not controllo_la.leggibile:
            raise self._rovinato_la(esame, riserva, numero)
        if not controllo.buono:
            esame.da_controllare.add(numero)
            raise _Rosso("da_riparare")
        if not controllo_la.buono:
            esame.da_rileggere.add(numero)
            raise _Rosso("da_riparare_sulla_chiavetta")

    def ancora_uguale(self, esame: Esame) -> list[str]:
        self._archivio_c_e()
        self._ancora_attaccata(Path(esame.disco), esame.chiavetta)
        try:
            stato = os.lstat(percorso_lungo(esame.vero))
        except OSError:
            return [""]
        if (metadati.tipo_di(stato) != metadati.CARTELLA
                or not _uguali(_vero(esame.cartella), esame.vero)):
            return [""]
        prova = esame.vuoto()
        diversi: set[str] = set()
        try:
            prova.impronta[""] = self._impronta(esame.vero, stato)
        except _Rosso:
            diversi.add("")
        saltare = self._camminatore._da_saltare()
        for relativo, assoluto, figlio in self._cammina(prova, saltare, stato.st_dev):
            self._ferma_se_serve()
            try:
                prova.impronta[relativo] = self._impronta(assoluto, figlio)
            except _Rosso:
                diversi.add(relativo)
        for esempi in prova.esempi.values():
            diversi.update(esempi)
        if prova.conti and not diversi:
            diversi.add("")
        for relativo in esame.impronta.keys() | prova.impronta.keys():
            if esame.impronta.get(relativo) != prova.impronta.get(relativo):
                diversi.add(relativo)
        self._archivio_uguale(esame)
        return sorted(diversi)

    def _archivio_uguale(self, esame: Esame) -> None:
        for chiave in sorted(esame.posti):
            posto = self.elenco.posto(chiave)
            if posto is None or posto.sparito is not None:
                raise ErroreOfficina(
                    "Nell'archivio qualcosa è cambiato dopo il controllo: rifai il "
                    "controllo.", codice="archivio_cambiato")
        disco = Path(esame.disco) / CARTELLA
        for numero in sorted(esame.contenuti):
            self._ferma_se_serve()
            informazioni = self.elenco.contenuto(numero)
            qui = self._blob(registro.percorso_contenuto(self.cartella, numero))
            if (informazioni is None or informazioni["stato"] not in STATI_BUONI
                    or qui is None or qui.st_size != informazioni["peso"]):
                self._archivio_c_e()
                raise ErroreOfficina(
                    "Nell'archivio qualcosa è cambiato dopo il controllo: rifai il "
                    "controllo.", codice="archivio_cambiato")
            la = self._blob(registro.percorso_contenuto(disco, numero))
            if la is None or la.st_size != informazioni["peso"]:
                self._ancora_attaccata(Path(esame.disco), esame.chiavetta)
                raise ErroreOfficina(
                    "Sulla chiavetta qualcosa è cambiato dopo il controllo: rifai il "
                    "controllo.", codice="chiavetta_cambiata")


class ControlloFresco(Sottofondo):

    nome = "archivio-sicuro-via-libera"

    def __init__(self, cartella: Path, elenco, chiave, chiavetta, *,
                 sveglio=sveglia.sveglio, rallenta=None,
                 pausa_se_usi: float = PAUSA_SE_USI, **per_esaminatore):
        super().__init__(sveglio=sveglio, rallenta=rallenta,
                         pausa_se_usi=pausa_se_usi)
        self.esaminatore = Esaminatore(cartella, elenco, chiave, chiavetta,
                                       aspetta=self._aspetta, **per_esaminatore)

    def avvia(self, percorsi) -> bool:
        return self._parti([os.fspath(percorso) for percorso in percorsi])

    def _azzera(self) -> None:
        self.esaminatore.azzera()

    def _lavora(self, percorsi: list[str]) -> None:
        self.esaminatore.tutte(percorsi)

    def istantanea(self) -> dict:
        esaminatore = self.esaminatore
        avanzamento = esaminatore.avanzamento
        in_corso = esaminatore.esame
        return {
            "stato": self.stato,
            "errore": self.errore,
            "codice": self.codice,
            "cartella": avanzamento.cartella,
            "percorso": avanzamento.percorso,
            "file": avanzamento.file,
            "letti": avanzamento.letti,
            "in_corso": None if in_corso is None else in_corso.istantanea(),
            "esami": [esame.istantanea() for esame in list(esaminatore.esami)],
            "errori": {testo: {"codice": errore.codice, "messaggio": errore.messaggio}
                       for testo, errore in dict(esaminatore.errori).items()},
        }


__all__ = ["ControlloFresco", "Esame", "Esaminatore", "GLOBALI", "PAROLE",
           "VALIDO_PER", "cambio_windows", "cartelle_nel_cloud", "cartelle_speciali",
           "sincronizzato"]
