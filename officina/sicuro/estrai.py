from __future__ import annotations

import errno
import hashlib
import os
import re
import shutil
import stat
from contextlib import ExitStack
from dataclasses import dataclass, field
from pathlib import Path

from officina.errori import ErroreOfficina
from officina.sicuro import elenco as registro
from officina.sicuro import formato, metadati, sveglia
from officina.sicuro.copia import STATI_BUONI, Fermato, cartella_esistente
from officina.sicuro.controllo import buchi_di
from officina.sicuro.diretto import Lettore
from officina.sicuro.disco import percorso_lungo
from officina.sicuro.sottofondo import PAUSA_SE_USI, Sottofondo


MARGINE = 256 * 1024 * 1024
PEZZO_DI_LETTURA = 4 * 1024 * 1024
TENTATIVI = 2
NOMI_LIBERI = 10000
RIMANDO = 0x400
OGNI_QUANTI_BLOCCHI = 64
VIETATI = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
RISERVATI = re.compile(r"^(con|prn|aux|nul|com[0-9¹²³]|lpt[0-9¹²³])(\..*)?$",
                       re.IGNORECASE)
PIENO = (errno.ENOSPC, getattr(errno, "EDQUOT", errno.ENOSPC))
ROSSI = frozenset({
    "contenuto_mancante", "rovinato", "incompleto", "collegamento_non_creato",
    "flusso_mancante", "flusso_rovinato", "flusso_scritto_male",
    "cartella_non_creata", "file_non_creato"})
FATALI = frozenset({"spazio_finito", "dove_cambiato", "scritto_male",
                    "archivio_sparito"})


class _Perso(Exception):
    pass


class _NonCreato(Exception):
    pass


@dataclass
class Resoconto:
    radice: str
    sotto: str = ""
    cartella: str | None = None
    file: int = 0
    cartelle: int = 0
    collegamenti: int = 0
    byte: int = 0
    problemi: list[tuple[str, str]] = field(default_factory=list)
    bersagli: list[tuple[str, str]] = field(default_factory=list)
    finito: bool = False

    def problema(self, codice: str, percorso: str) -> None:
        if (codice, percorso) not in self.problemi:
            self.problemi.append((codice, percorso))

    @property
    def rossi(self) -> list[tuple[str, str]]:
        return [problema for problema in self.problemi if problema[0] in ROSSI]

    @property
    def verde(self) -> bool:
        return self.finito and not self.rossi


@dataclass
class Avanzamento:
    percorso: str | None = None
    file: int = 0
    byte: int = 0
    da_fare: int = 0
    file_veri: int = 0
    byte_da_fare: int = 0


def con_numero(nome: str, volta: int, cartella: bool = False) -> str:
    if volta <= 1:
        return nome
    punto = -1 if cartella else nome.rfind(".")
    if punto > 0:
        return f"{nome[:punto]} ({volta}){nome[punto:]}"
    return f"{nome} ({volta})"


def nome_della_radice(percorso: str) -> str:
    pulito = percorso.replace("\\", "/").rstrip("/")
    ultimo = pulito.rsplit("/", 1)[-1] if pulito else ""
    if re.fullmatch(r"[A-Za-z]:", ultimo):
        return f"Disco {ultimo[0].upper()}"
    return ultimo or "Cartella"


def nome_per_windows(nome: str) -> str:
    buono = VIETATI.sub("_", nome)
    if buono.endswith((".", " ")):
        buono = buono.rstrip(". ") + "_"
    if RISERVATI.match(buono):
        buono = "_" + buono
    return buono or "_"


def scelti(elenco, radice: str, sotto: str = "",
           quando: float | None = None) -> list:
    sotto = registro.percorso_pulito(sotto) if sotto else ""
    ultimi: dict[str, object] = {}
    for posto in elenco.dentro(radice, anche_spariti=quando is not None):
        if sotto and posto.percorso != sotto and not posto.percorso.startswith(
                sotto + "/"):
            continue
        if quando is None:
            if posto.sparito is not None:
                continue
        elif posto.visto > quando or (posto.sparito is not None
                                      and posto.sparito <= quando):
            continue
        ultimi[posto.percorso] = posto
    return [ultimi[percorso] for percorso in sorted(ultimi)]


def _dentro(percorso: Path, cartella: Path) -> bool:
    try:
        percorso = Path(os.path.realpath(percorso))
        cartella = Path(os.path.realpath(cartella))
    except (OSError, ValueError):
        return False
    vero = os.path.normcase(str(percorso))
    base = os.path.normcase(str(cartella))
    return vero == base or vero.startswith(base.rstrip(os.sep) + os.sep)


def _cartella_vera(percorso: Path) -> bool:
    try:
        stato = os.lstat(percorso_lungo(percorso))
    except (OSError, ValueError):
        return False
    if not stat.S_ISDIR(stato.st_mode):
        return False
    return not getattr(stato, "st_file_attributes", 0) & RIMANDO


def _pieno() -> ErroreOfficina:
    return ErroreOfficina(
        "Il disco dove estrai si è riempito: mi fermo. Quello che è già uscito "
        "resta.", codice="spazio_finito")


def _nuovo_file(prova: Path) -> int:
    return os.open(percorso_lungo(prova),
                   os.O_RDWR | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0))


def _segno(stato) -> tuple[int, int]:
    return (stato.st_dev, stato.st_ino)


def _ancora_lui(percorso: Path, segno: tuple[int, int]) -> bool:
    if not _cartella_vera(percorso.parent):
        return False
    try:
        return _segno(os.lstat(percorso_lungo(percorso))) == segno
    except (OSError, ValueError):
        return False


def _togli(percorso: Path, segno: tuple[int, int]) -> None:
    if not _ancora_lui(percorso, segno):
        return
    try:
        os.unlink(percorso_lungo(percorso))
    except OSError:
        pass


def _cambiato() -> ErroreOfficina:
    return ErroreOfficina(
        "Una cartella dove sto estraendo è sparita o è diventata un "
        "collegamento: mi fermo per non scrivere altrove.", codice="dove_cambiato")


class _Stesso:

    def __init__(self, fuori):
        self._fuori = fuori

    def __enter__(self):
        self._fuori.seek(0)
        self._fuori.truncate()
        return self._fuori

    def __exit__(self, *altro):
        return False


class _Conta:

    def __init__(self, fuori):
        self._fuori = fuori
        self._blake = hashlib.blake2b(digest_size=formato.IMPRONTA)
        self._sha = hashlib.sha256()

    def write(self, dati: bytes) -> int:
        self._blake.update(dati)
        self._sha.update(dati)
        return self._fuori.write(dati)

    def impronte(self) -> dict:
        return {"blake2b": self._blake.hexdigest(), "sha256": self._sha.hexdigest()}


def _impronte_di(letto) -> dict:
    blake = hashlib.blake2b(digest_size=formato.IMPRONTA)
    sha = hashlib.sha256()
    while True:
        pezzo = letto.read(PEZZO_DI_LETTURA)
        if not pezzo:
            break
        blake.update(pezzo)
        sha.update(pezzo)
    return {"blake2b": blake.hexdigest(), "sha256": sha.hexdigest()}


class Estrattore:

    def __init__(self, cartella: Path, elenco, chiave, *, apri=Lettore,
                 aspetta=None, apri_flusso=None, spazio=None,
                 windows: bool | None = None):
        self.cartella = Path(cartella)
        self.elenco = elenco
        self._chiave = chiave
        self._apri = apri
        self._aspetta = aspetta
        self._apri_flusso = apri_flusso
        self._spazio = spazio
        self._windows = windows
        self.avanzamento = Avanzamento()
        self.resoconto: Resoconto | None = None

    def _ferma_se_serve(self) -> None:
        if self._aspetta is not None:
            self._aspetta()

    def _su_windows(self) -> bool:
        return metadati._windows() if self._windows is None else self._windows

    def _flussi_si_scrivono(self):
        if self._apri_flusso is not None:
            return self._apri_flusso
        return metadati.apri_flusso if self._su_windows() else None

    def _libero(self, dove: Path) -> int:
        if self._spazio is not None:
            return self._spazio(dove)
        return shutil.disk_usage(cartella_esistente(dove)).free

    def _archivio_c_e(self) -> None:
        if not _cartella_vera(self.cartella / registro.CONTENUTI):
            raise ErroreOfficina(
                "Il disco dell'Archivio sicuro non si legge più: ricollegalo e "
                "riprova.", codice="archivio_sparito")

    def _peso(self, posti) -> int:
        totale = 0
        for posto in posti:
            if posto.tipo != metadati.FILE:
                continue
            for numero in [posto.contenuto, *(numero for _, numero in
                                              self.elenco.flussi_di(posto.chiave))]:
                informazioni = self.elenco.contenuto(numero) if numero else None
                if informazioni is not None:
                    totale += informazioni["dimensione"]
        return totale

    def _prepara_dove(self, dove: Path, posti) -> tuple[Path, int]:
        try:
            dove = Path(os.path.realpath(dove))
        except (OSError, ValueError) as guasto:
            raise ErroreOfficina("La cartella scelta non si trova.",
                                 codice="dove_strano") from guasto
        if _dentro(dove, self.cartella):
            raise ErroreOfficina(
                "Non si può estrarre dentro l'Archivio sicuro: scegli un'altra "
                "cartella.", codice="estrai_nell_archivio")
        serve = self._peso(posti)
        libero = self._libero(dove)
        if libero - serve < MARGINE:
            raise ErroreOfficina(
                f"Per estrarre servono {serve / 1024 ** 3:.1f} GB, ma lì ne "
                f"restano liberi {libero / 1024 ** 3:.1f}: scegli un disco con "
                "più spazio.", codice="poco_spazio")
        try:
            dove.mkdir(parents=True, exist_ok=True)
        except OSError as guasto:
            if guasto.errno in PIENO:
                raise _pieno() from guasto
            raise ErroreOfficina(
                "La cartella scelta non si riesce a creare: scegline un'altra.",
                codice="dove_non_creato") from guasto
        if not _cartella_vera(dove):
            raise ErroreOfficina("La cartella scelta non è una cartella vera.",
                                 codice="dove_strano")
        return dove, serve

    def _inizia(self, radice: str, sotto: str, posti, peso: int) -> Resoconto:
        self.resoconto = Resoconto(radice, sotto)
        self.avanzamento = Avanzamento(da_fare=len(posti), byte_da_fare=peso)
        return self.resoconto

    def estrai(self, radice: str, dove, sotto: str = "",
               quando: float | None = None) -> Resoconto:
        dove = Path(dove)
        sotto = registro.percorso_pulito(sotto) if sotto else ""
        conosciuta = next((voce for voce in self.elenco.radici()
                           if voce["id"] == radice), None)
        if conosciuta is None:
            raise ErroreOfficina("Questa cartella non è nell'Archivio sicuro.",
                                 codice="radice_sconosciuta")
        posti = scelti(self.elenco, radice, sotto, quando)
        if not posti:
            raise ErroreOfficina("Qui non c'è niente da estrarre.",
                                 codice="niente_da_estrarre")
        dove, peso = self._prepara_dove(dove, posti)
        resoconto = self._inizia(radice, sotto, posti, peso)
        cima = posti[0] if sotto and posti[0].percorso == sotto else None
        if cima is not None and cima.tipo != metadati.CARTELLA:
            self._uno_solo(cima, dove, resoconto)
        else:
            nome = (nome_della_radice(conosciuta["percorso"]) if not sotto
                    else sotto.rsplit("/", 1)[-1])
            prima = len(sotto) + 1 if sotto else 0
            lista = [(posto.percorso[prima:], posto) for posto in posti
                     if posto is not cima]
            self._albero(dove, nome, cima, lista, resoconto)
        resoconto.finito = True
        return resoconto

    def estrai_versione(self, chiave: str, dove) -> Resoconto:
        posto = self.elenco.posto(chiave)
        if posto is None:
            raise ErroreOfficina("Questa versione non è nell'Archivio sicuro.",
                                 codice="versione_sconosciuta")
        dove = Path(dove)
        if posto.tipo == metadati.CARTELLA:
            quando = None if posto.sparito is None else posto.sparito - 1e-6
            return self.estrai(posto.radice, dove, posto.percorso, quando)
        dove, peso = self._prepara_dove(dove, [posto])
        resoconto = self._inizia(posto.radice, posto.percorso, [posto], peso)
        self._uno_solo(posto, dove, resoconto)
        resoconto.finito = True
        return resoconto

    def richieste_per_tutto(self, dove, quando: float | None = None) -> list[dict]:
        return [{"radice": radice["id"], "dove": Path(dove), "quando": quando}
                for radice in self.elenco.radici()
                if scelti(self.elenco, radice["id"], "", quando)]

    def _nome(self, nome: str, relativo: str, resoconto: Resoconto) -> str:
        if not self._su_windows():
            return nome
        buono = nome_per_windows(nome)
        if buono != nome:
            resoconto.problema("nome_cambiato", relativo)
        return buono

    def _crea(self, cartella: Path, nome: str, fai, cartella_nuova: bool,
              relativo: str, resoconto: Resoconto):
        if not _cartella_vera(cartella):
            raise _cambiato()
        for volta in range(1, NOMI_LIBERI + 1):
            prova = cartella / con_numero(nome, volta, cartella_nuova)
            try:
                fatto = fai(prova)
            except FileExistsError:
                continue
            except PermissionError as guasto:
                if os.path.lexists(percorso_lungo(prova)):
                    continue
                raise _NonCreato from guasto
            except ErroreOfficina as guasto:
                causa = guasto.__cause__
                if isinstance(causa, FileExistsError) or (
                        isinstance(causa, PermissionError)
                        and os.path.lexists(percorso_lungo(prova))):
                    continue
                if isinstance(causa, OSError) and causa.errno in PIENO:
                    raise _pieno() from causa
                raise _NonCreato from guasto
            except OSError as guasto:
                if guasto.errno in PIENO:
                    raise _pieno() from guasto
                raise _NonCreato from guasto
            if volta > 1:
                resoconto.problema("rinominato", relativo)
            return prova, fatto
        raise _NonCreato

    def _nuova_cartella(self, cartella: Path, nome: str, relativo: str,
                        resoconto: Resoconto) -> Path | None:
        try:
            fatta, _ = self._crea(cartella, self._nome(nome, relativo, resoconto),
                                  lambda prova: os.mkdir(percorso_lungo(prova)),
                                  True, relativo, resoconto)
        except _NonCreato:
            resoconto.problema("cartella_non_creata", relativo)
            return None
        resoconto.cartelle += 1
        return fatta

    def _albero(self, dove: Path, nome: str, cima, lista, resoconto: Resoconto) -> None:
        radice = self._nuova_cartella(dove, nome, resoconto.sotto, resoconto)
        if radice is None:
            raise ErroreOfficina(
                "Non riesco a creare la cartella dove mettere quello che estraggo: "
                "scegline un'altra.", codice="cartella_non_creata")
        resoconto.cartelle -= 1
        resoconto.cartella = str(radice)
        cartelle: dict[str, Path | None] = {"": radice}
        da_sistemare: list[tuple[str, Path, dict]] = []
        if cima is not None:
            da_sistemare.append(("", radice, cima.metadati))
        collegamenti = []
        for relativo, posto in lista:
            self._ferma_se_serve()
            self.avanzamento.percorso = relativo
            if posto.tipo == metadati.COLLEGAMENTO:
                collegamenti.append((relativo, posto))
                continue
            sopra = self._cartella_di(relativo, cartelle, resoconto)
            nome_qui = relativo.rsplit("/", 1)[-1]
            if posto.tipo == metadati.CARTELLA:
                if relativo not in cartelle:
                    cartelle[relativo] = (None if sopra is None else
                                          self._nuova_cartella(sopra, nome_qui,
                                                               relativo, resoconto))
                fatta = cartelle[relativo]
                if fatta is None:
                    resoconto.problema("cartella_non_creata", relativo)
                else:
                    da_sistemare.append((relativo, fatta, posto.metadati))
            elif posto.tipo == metadati.FILE:
                if sopra is None:
                    resoconto.problema("file_non_creato", relativo)
                else:
                    self._file(sopra, nome_qui, relativo, posto, resoconto)
                self.avanzamento.file_veri += 1
            self.avanzamento.file += 1
        for relativo, posto in collegamenti:
            self._ferma_se_serve()
            self.avanzamento.percorso = relativo
            sopra = self._cartella_di(relativo, cartelle, resoconto)
            if sopra is None:
                resoconto.problema("collegamento_non_creato", relativo)
            else:
                self._collegamento(sopra, relativo.rsplit("/", 1)[-1], relativo,
                                   posto, resoconto)
            self.avanzamento.file += 1
            self.avanzamento.file_veri += 1
        for relativo, fatta, informazioni in sorted(
                da_sistemare, key=lambda voce: -voce[0].count("/") - bool(voce[0])):
            if not _cartella_vera(fatta):
                resoconto.problema("cartella_cambiata", relativo)
                continue
            for avviso in metadati.rimetti(fatta, informazioni, metadati.CARTELLA):
                resoconto.problema(avviso, relativo)
        self.avanzamento.percorso = None

    def _cartella_di(self, relativo: str, cartelle: dict[str, Path | None],
                     resoconto: Resoconto) -> Path | None:
        parti = relativo.split("/")[:-1]
        attuale = cartelle[""]
        for fine in range(1, len(parti) + 1):
            sopra = "/".join(parti[:fine])
            if sopra not in cartelle:
                cartelle[sopra] = self._nuova_cartella(attuale, parti[fine - 1],
                                                       sopra, resoconto)
            attuale = cartelle[sopra]
            if attuale is None:
                return None
        return attuale

    def _uno_solo(self, posto, dove: Path, resoconto: Resoconto) -> None:
        nome = posto.percorso.rsplit("/", 1)[-1]
        self.avanzamento.percorso = posto.percorso
        if posto.tipo == metadati.COLLEGAMENTO:
            fatto = self._collegamento(dove, nome, posto.percorso, posto, resoconto)
        else:
            fatto = self._file(dove, nome, posto.percorso, posto, resoconto)
        if fatto is not None:
            resoconto.cartella = str(fatto)
        self.avanzamento.file += 1
        self.avanzamento.file_veri += 1
        self.avanzamento.percorso = None

    def _collegamento(self, sopra: Path, nome: str, relativo: str, posto,
                      resoconto: Resoconto) -> Path | None:
        bersaglio = posto.metadati.get("bersaglio")
        resoconto.bersagli.append((relativo, bersaglio if isinstance(bersaglio, str)
                                   else ""))
        try:
            fatto, _ = self._crea(sopra, self._nome(nome, relativo, resoconto),
                                  lambda prova: metadati.crea_collegamento(
                                      prova, posto.metadati),
                                  False, relativo, resoconto)
        except _NonCreato:
            resoconto.problema("collegamento_non_creato", relativo)
            return None
        resoconto.collegamenti += 1
        return fatto

    def _fonti(self, numero: str) -> list[tuple[str, dict]]:
        informazioni = self.elenco.contenuto(numero)
        if informazioni is None:
            return []
        if (informazioni["perche"] or "").startswith(registro.SALVATO):
            originale = informazioni["perche"][len(registro.SALVATO):]
            dati = self.elenco.contenuto(originale)
            if dati is None or (dati["perche"] or "").startswith(registro.SALVATO):
                return [(numero, {**informazioni, "salvato": True})]
            numero, informazioni = originale, dati
        gemelli = []
        for altro in self.elenco.uguali(informazioni["dimensione"],
                                        informazioni["blake2b"],
                                        informazioni["sha256"]):
            if altro == numero:
                continue
            dati = self.elenco.contenuto(altro)
            if dati is not None and dati["stato"] in STATI_BUONI:
                gemelli.append((altro, dati))
        salvati = []
        for altro in self.elenco.salvati(numero):
            dati = self.elenco.contenuto(altro)
            if dati is not None:
                salvati.append((altro, {**dati, "blake2b": informazioni["blake2b"],
                                        "sha256": informazioni["sha256"],
                                        "stato": informazioni["stato"],
                                        "salvato": True}))
        if informazioni["stato"] in (*STATI_BUONI, "incompleto"):
            return [(numero, informazioni), *gemelli, *salvati]
        return [*gemelli, (numero, informazioni), *salvati]

    def _aiuti(self, fonti, indice: int) -> list[tuple[str, dict]]:
        presi = {numero for numero, _ in fonti}
        informazioni = fonti[indice][1]
        altri = []
        for altro in self.elenco.uguali(informazioni["dimensione"],
                                        informazioni["blake2b"],
                                        informazioni["sha256"]):
            dati = self.elenco.contenuto(altro) if altro not in presi else None
            if dati is not None:
                altri.append((altro, dati))
        return [*fonti[:indice], *fonti[indice + 1:], *altri]

    def _file(self, sopra: Path, nome: str, relativo: str, posto,
              resoconto: Resoconto) -> Path | None:
        fonti = self._fonti(posto.contenuto) if posto.contenuto else []
        if not fonti:
            resoconto.problema("contenuto_mancante", relativo)
            return None
        try:
            fatto, aperto = self._crea(sopra, self._nome(nome, relativo, resoconto),
                                       _nuovo_file, False, relativo, resoconto)
        except _NonCreato:
            resoconto.problema("file_non_creato", relativo)
            return None
        try:
            segno = _segno(os.fstat(aperto))
        except OSError:
            os.close(aperto)
            resoconto.problema("file_non_creato", relativo)
            return None
        riuscito = False
        try:
            with os.fdopen(aperto, "r+b") as fuori:
                pieno = self._riempi(fatto, fuori, fonti, relativo, resoconto)
            if not _ancora_lui(fatto, segno):
                raise _cambiato()
            if pieno:
                self._flussi(fatto, posto, relativo, resoconto)
            riuscito = pieno
        except _NonCreato:
            resoconto.problema("file_non_creato", relativo)
            return None
        except ErroreOfficina as guasto:
            if guasto.codice == "scritto_male" and not _ancora_lui(fatto, segno):
                raise _cambiato() from guasto
            raise
        except OSError as guasto:
            if guasto.errno in PIENO:
                raise _pieno() from guasto
            raise ErroreOfficina(
                "Il disco dove estrai ha dato un errore mentre scrivevo: mi "
                "fermo.", codice="scritto_male") from guasto
        finally:
            if not riuscito:
                _togli(fatto, segno)
        if not riuscito:
            resoconto.problema("contenuto_mancante", relativo)
            return None
        if "in_uso" in posto.segni:
            resoconto.problema("in_uso", relativo)
        if "diverso_da_prima" in posto.segni:
            resoconto.problema("diverso_da_prima", relativo)
        for avviso in metadati.rimetti(fatto, posto.metadati, metadati.FILE):
            resoconto.problema(avviso, relativo)
        resoconto.file += 1
        return fatto

    def _riempi(self, fatto: Path, fuori, fonti, relativo: str,
                resoconto: Resoconto) -> bool:
        for intero in (True, False):
            for indice, (numero, informazioni) in enumerate(fonti):
                aiuti = () if intero else self._aiuti(fonti, indice)
                try:
                    impronte, persi = self._scrivi_verificato(
                        lambda: _Stesso(fuori), lambda: self._rileggi(fatto),
                        lambda conta, n=numero, i=informazioni, e=intero, a=aiuti:
                            self._decifra(n, i, conta, e, a))
                except _Perso:
                    continue
                attese = {"blake2b": informazioni["blake2b"],
                          "sha256": informazioni["sha256"]}
                if persi:
                    resoconto.problema("rovinato", relativo)
                elif impronte != attese:
                    if intero:
                        continue
                    resoconto.problema("rovinato", relativo)
                elif informazioni["stato"] == "incompleto":
                    resoconto.problema("incompleto", relativo)
                resoconto.byte += informazioni["dimensione"]
                self.avanzamento.byte += informazioni["dimensione"]
                return True
        return False

    def _contenuto(self, numero: str, informazioni: dict,
                   pila: ExitStack) -> tuple[formato.Contenuto, frozenset[int]]:
        percorso = registro.percorso_contenuto(self.cartella, numero)
        try:
            blob = pila.enter_context(self._apri(percorso, False))
        except OSError:
            self._archivio_c_e()
            raise _Perso from None
        try:
            contenuto = formato.Contenuto(blob, self._chiave,
                                          numero=bytes.fromhex(numero),
                                          testa=informazioni["testa"])
        except (ErroreOfficina, OSError, ValueError):
            self._archivio_c_e()
            raise _Perso from None
        if contenuto.dimensione != informazioni["dimensione"]:
            raise _Perso
        buchi: frozenset[int] | None = frozenset()
        if informazioni.get("salvato"):
            buchi = buchi_di(contenuto.dati, contenuto.forma.blocchi)
            if buchi is None:
                raise _Perso
        return contenuto, buchi

    def _da_riserva(self, blocco: int, riserve, aperti: dict,
                    pila: ExitStack) -> bytes | None:
        for numero, informazioni in riserve:
            if numero not in aperti:
                try:
                    aperti[numero] = self._contenuto(numero, informazioni, pila)
                except _Perso:
                    aperti[numero] = None
            altro = aperti[numero]
            if altro is None or blocco in altro[1]:
                continue
            try:
                return altro[0].blocco(blocco)
            except formato.ContenutoRovinato:
                continue
        return None

    def _decifra(self, numero: str, informazioni: dict, fuori,
                 solo_intero: bool, riserve=()) -> int:
        persi = 0
        with ExitStack() as pila:
            contenuto, buchi = self._contenuto(numero, informazioni, pila)
            aperti: dict[str, tuple | None] = {}
            for blocco in range(contenuto.forma.blocchi):
                if blocco % OGNI_QUANTI_BLOCCHI == 0:
                    self._ferma_se_serve()
                chiaro = None
                if blocco not in buchi:
                    try:
                        chiaro = contenuto.blocco(blocco)
                    except formato.ContenutoRovinato:
                        self._archivio_c_e()
                if chiaro is None:
                    if solo_intero:
                        raise _Perso
                    chiaro = self._da_riserva(blocco, riserve, aperti, pila)
                    if chiaro is None:
                        chiaro = bytes(contenuto.forma.lunghezza(blocco))
                        persi += 1
                fuori.write(chiaro)
            if persi and persi == contenuto.forma.blocchi:
                raise _Perso
        return persi

    def _scrivi_verificato(self, apri, rileggi, scrivi) -> tuple[dict, int]:
        aperto_mai = True
        ultimo: OSError | None = None
        for _ in range(TENTATIVI):
            try:
                scrittura = apri()
            except OSError as guasto:
                if guasto.errno in PIENO:
                    raise
                ultimo = guasto
                continue
            aperto_mai = False
            try:
                with scrittura as fuori:
                    conta = _Conta(fuori)
                    persi = scrivi(conta)
                    fuori.flush()
                    os.fsync(fuori.fileno())
                if rileggi() == conta.impronte():
                    return conta.impronte(), persi
            except OSError as guasto:
                if guasto.errno in PIENO:
                    raise
                ultimo = guasto
        if aperto_mai:
            raise _NonCreato from ultimo
        raise ErroreOfficina("Il file estratto, riletto, non è uguale: il disco "
                             "dove estrai non scrive bene. Scegline un altro.",
                             codice="scritto_male") from ultimo

    def _rileggi(self, fatto: Path) -> dict:
        blake = hashlib.blake2b(digest_size=formato.IMPRONTA)
        sha = hashlib.sha256()
        with self._apri(fatto, True) as letto:
            dove = 0
            while dove < letto.dimensione:
                pezzo = letto.pezzo(dove, min(PEZZO_DI_LETTURA,
                                              letto.dimensione - dove))
                if not pezzo:
                    break
                blake.update(pezzo)
                sha.update(pezzo)
                dove += len(pezzo)
        return {"blake2b": blake.hexdigest(), "sha256": sha.hexdigest()}

    def _flussi(self, fatto: Path, posto, relativo: str,
                resoconto: Resoconto) -> None:
        flussi = self.elenco.flussi_di(posto.chiave)
        if not flussi:
            return
        apri_flusso = self._flussi_si_scrivono()
        if apri_flusso is None:
            resoconto.problema("flussi_non_rimessi", relativo)
            return
        for nome, numero in flussi:
            if not metadati.nome_di_flusso_buono(nome):
                resoconto.problema("flusso_strano", relativo)
                continue
            fonti = self._fonti(numero)
            if not fonti:
                resoconto.problema("flusso_mancante", relativo)
                continue
            if not self._un_flusso(fatto, nome, fonti, apri_flusso, relativo,
                                   resoconto):
                return

    def _un_flusso(self, fatto: Path, nome: str, fonti, apri_flusso,
                   relativo: str, resoconto: Resoconto) -> bool:
        def rileggi():
            with apri_flusso(fatto, nome, "rb") as letto:
                return _impronte_di(letto)

        for indice, (numero, informazioni) in enumerate(fonti):
            ultima = indice == len(fonti) - 1
            try:
                impronte, persi = self._scrivi_verificato(
                    lambda: apri_flusso(fatto, nome, "wb"), rileggi,
                    lambda conta, n=numero, i=informazioni, a=self._aiuti(
                        fonti, indice): self._decifra(n, i, conta, not ultima, a))
            except _Perso:
                continue
            except _NonCreato:
                resoconto.problema("flussi_non_rimessi", relativo)
                return False
            except ErroreOfficina as guasto:
                if guasto.codice != "scritto_male":
                    raise
                resoconto.problema("flusso_scritto_male", relativo)
                return True
            attese = {"blake2b": informazioni["blake2b"],
                      "sha256": informazioni["sha256"]}
            if persi or impronte != attese:
                if not ultima:
                    continue
                resoconto.problema("flusso_rovinato", relativo)
            return True
        resoconto.problema("flusso_mancante", relativo)
        return True


class Estrazione(Sottofondo):

    nome = "archivio-sicuro-estrai"

    def __init__(self, cartella: Path, elenco, chiave, *, sveglio=sveglia.sveglio,
                 rallenta=None, pausa_se_usi: float = PAUSA_SE_USI,
                 **per_estrattore):
        super().__init__(sveglio=sveglio, rallenta=rallenta,
                         pausa_se_usi=pausa_se_usi)
        self.estrattore = Estrattore(cartella, elenco, chiave,
                                     aspetta=self._aspetta, **per_estrattore)
        self.resoconti: list[Resoconto] = []
        self.rifiutate: list[tuple[dict, str]] = []

    def avvia(self, richieste: list[dict]) -> bool:
        return self._parti([dict(richiesta) for richiesta in richieste])

    def _azzera(self) -> None:
        self.resoconti = []
        self.rifiutate = []

    def _una(self, richiesta: dict) -> Resoconto:
        if "chiave" in richiesta:
            return self.estrattore.estrai_versione(richiesta["chiave"],
                                                   richiesta["dove"])
        return self.estrattore.estrai(richiesta["radice"], richiesta["dove"],
                                      richiesta.get("sotto", ""),
                                      richiesta.get("quando"))

    def _a_meta(self) -> None:
        resoconto = self.estrattore.resoconto
        if resoconto is not None and not resoconto.finito:
            self.resoconti.append(resoconto)

    def _lavora(self, richieste: list[dict]) -> None:
        for richiesta in richieste:
            self._aspetta()
            self.estrattore.resoconto = None
            try:
                resoconto = self._una(richiesta)
            except ErroreOfficina as guasto:
                if guasto.codice not in FATALI:
                    self.rifiutate.append((richiesta, guasto.codice or "errore"))
                    continue
                self._a_meta()
                raise
            except BaseException:
                self._a_meta()
                raise
            self.resoconti.append(resoconto)

    def istantanea(self) -> dict:
        avanzamento = self.estrattore.avanzamento
        resoconti = list(self.resoconti)
        return {
            "stato": self.stato,
            "percorso": avanzamento.percorso,
            "file": avanzamento.file,
            "byte": avanzamento.byte,
            "da_fare": avanzamento.da_fare,
            "byte_da_fare": avanzamento.byte_da_fare,
            "fatte": [{"radice": resoconto.radice, "sotto": resoconto.sotto,
                       "cartella": resoconto.cartella, "verde": resoconto.verde,
                       "finito": resoconto.finito, "file": resoconto.file,
                       "byte": resoconto.byte,
                       "rossi": [list(problema) for problema in resoconto.rossi]}
                      for resoconto in resoconti],
            "rifiutate": [codice for _, codice in self.rifiutate],
            "errore": self.errore,
            "codice": self.codice,
        }


__all__ = ["Estrattore", "Estrazione", "FATALI", "Fermato", "Resoconto",
           "con_numero", "nome_della_radice", "nome_per_windows", "scelti"]
