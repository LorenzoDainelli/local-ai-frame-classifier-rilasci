from __future__ import annotations

import contextlib
import errno
import hashlib
import io
import os
import threading
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path

from officina.errori import ErroreOfficina
from officina.sicuro import elenco as registro
from officina.sicuro import formato
from officina.sicuro.controllo import buchi_di
from officina.sicuro.copia import Fermato
from officina.sicuro.dentro import _resto, _vero
from officina.sicuro.diretto import Lettore
from officina.sicuro.sottofondo import Sottofondo


OGNI = 120.0
COMPLETI = ("buono", "riparato", "rovinato", "senza_informazioni")
PERSA = ("Questa foto, nell'Archivio sicuro, è rovinata e non sono riuscito a "
         "ripararla qui. Non ho cancellato niente: l'archivio prova a ripararla da "
         "solo, cercando lo stesso file anche sulla chiavetta e sugli altri dischi.")


class Persa(ErroreOfficina):
    codice = "persa_nell_archivio"


def _persa() -> Persa:
    return Persa(PERSA)


def leggi(percorso, senza_cache: bool):
    return Lettore(percorso, senza_cache)


@dataclass
class _Fonte:
    percorso: Path
    numero: bytes
    testa: bytes | None
    salvataggio: bool = False
    aperta: bool = False
    contenuto: formato.Contenuto | None = None
    buchi: frozenset[int] = frozenset()


class Fonti:

    def __init__(self, numero: str, informazioni: dict, chiave, pila: ExitStack, *,
                 apri=leggi, altre=None, segnala=None, letta=None, vivo=None):
        self.numero = numero
        self.forma = formato.Forma.da_testa(informazioni["testa"])
        self._chiave = chiave
        self._pila = pila
        self._apri = apri
        self._altre = altre
        self._segnala = segnala
        self._letta = letta
        self._vivo = vivo
        self._fonti: list[_Fonte] = []
        self._buoni: set[int] = set()
        self._cercate = altre is None
        self._serratura = threading.RLock()
        self.male = False
        self.segnalata = False
        self.persa = False
        self.intera = False

    def aggiungi(self, percorso, numero: str, testa: bytes | None,
                 salvataggio: bool = False) -> None:
        fonte = _Fonte(Path(percorso), bytes.fromhex(numero), testa, salvataggio)
        if all(fonte.percorso != gia.percorso for gia in self._fonti):
            self._fonti.append(fonte)

    def _contenuto(self, fonte: _Fonte) -> formato.Contenuto | None:
        if fonte.aperta:
            return fonte.contenuto
        fonte.aperta = True
        try:
            lettore = self._pila.enter_context(self._apri(fonte.percorso, False))
            contenuto = formato.Contenuto(lettore, self._chiave, numero=fonte.numero,
                                          testa=fonte.testa)
        except (ErroreOfficina, OSError, ValueError):
            return None
        if (contenuto.dimensione != self.forma.dimensione
                or contenuto.forma.blocco != self.forma.blocco):
            return None
        if fonte.salvataggio:
            buchi = buchi_di(contenuto.dati, self.forma.blocchi)
            if buchi is None:
                return None
            fonte.buchi = buchi
        fonte.contenuto = contenuto
        return contenuto

    def _da(self, fonte: _Fonte, numero: int) -> bytes | None:
        contenuto = self._contenuto(fonte)
        if contenuto is None or numero in fonte.buchi:
            return None
        try:
            return contenuto.blocco(numero)
        except formato.ContenutoRovinato:
            return None

    def _cerca_le_altre(self) -> None:
        if self._cercate:
            return
        self._cercate = True
        try:
            altre = list(self._altre())
        except (ErroreOfficina, OSError, ValueError):
            altre = []
        for percorso, numero, testa, salvataggio in altre:
            self.aggiungi(percorso, numero, testa, salvataggio)

    def blocco(self, numero: int) -> bytes | None:
        if self._vivo is not None:
            self._vivo()
        intera = False
        with self._serratura:
            chiaro = self._da(self._fonti[0], numero) if self._fonti else None
            if chiaro is None:
                self.male = True
                self._cerca_le_altre()
                for fonte in self._fonti[1:]:
                    chiaro = self._da(fonte, numero)
                    if chiaro is not None:
                        break
            if chiaro is not None:
                self._buoni.add(numero)
                if not self.intera and len(self._buoni) == self.forma.blocchi:
                    self.intera = intera = True
        if intera and self._letta is not None:
            self._letta(self.numero)
        self.guarda(chiaro is None)
        return chiaro

    @property
    def rovinata(self) -> bool:
        prima = self._fonti[0] if self._fonti else None
        return (self.male or prima is None
                or (prima.aperta and prima.contenuto is None)
                or (prima.contenuto is not None and prima.contenuto.da_riparare))

    def guarda(self, persa: bool) -> None:
        with self._serratura:
            if persa and not self.persa:
                self.persa = self.segnalata = True
            elif not self.segnalata and self.rovinata:
                self.segnalata = True
            else:
                return
        if self._segnala is not None:
            self._segnala(self.numero, persa)


class Flusso(io.RawIOBase):

    def __init__(self, fonti: Fonti, pila: ExitStack, guasto=None):
        super().__init__()
        self._fonti = fonti
        self._pila = pila
        self._guasto = guasto
        self._dove = 0

    def _male(self, codice: str | None) -> None:
        if self._guasto is not None:
            self._guasto(codice)

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self._dove

    def seek(self, dove: int, da: int = io.SEEK_SET) -> int:
        if da == io.SEEK_CUR:
            dove += self._dove
        elif da == io.SEEK_END:
            dove += self._fonti.forma.dimensione
        elif da != io.SEEK_SET:
            raise ValueError(f"da dove? {da}")
        if dove < 0:
            raise ValueError("posizione prima dell'inizio")
        self._dove = dove
        return dove

    def readinto(self, spazio) -> int:
        forma = self._fonti.forma
        if self._dove >= forma.dimensione or not len(spazio):
            return 0
        numero = self._dove // forma.blocco
        try:
            chiaro = self._fonti.blocco(numero)
        except Exception as errore:
            self._male(getattr(errore, "codice", None))
            if isinstance(errore, ErroreOfficina):
                raise OSError(errno.EIO, str(errore)) from errore
            raise
        if chiaro is None:
            self._male(Persa.codice)
            raise OSError(errno.EIO, PERSA)
        da = self._dove - numero * forma.blocco
        quanti = min(len(spazio), len(chiaro) - da)
        spazio[:quanti] = chiaro[da:da + quanti]
        self._dove += quanti
        return quanti

    def close(self) -> None:
        if not self.closed:
            try:
                self._pila.close()
            finally:
                super().close()


def tutto(fonti: Fonti, informazioni: dict) -> io.BytesIO:
    blake = hashlib.blake2b(digest_size=formato.IMPRONTA)
    sha = hashlib.sha256()
    fuori = io.BytesIO()
    for numero in range(fonti.forma.blocchi):
        chiaro = fonti.blocco(numero)
        if chiaro is None:
            raise _persa()
        blake.update(chiaro)
        sha.update(chiaro)
        fuori.write(chiaro)
    if (fuori.tell() != informazioni["dimensione"]
            or blake.hexdigest() != informazioni["blake2b"]
            or sha.hexdigest() != informazioni["sha256"]):
        fonti.guarda(True)
        raise _persa()
    fuori.seek(0)
    return fuori


def lettore(numero: str, informazioni: dict, chiave, percorso, intero: bool, *,
            apri=leggi, altre=None, segnala=None, letta=None, vivo=None, guasto=None):
    pila = ExitStack()
    try:
        fonti = Fonti(numero, informazioni, chiave, pila, apri=apri, altre=altre,
                      segnala=segnala, letta=letta, vivo=vivo)
        fonti.aggiungi(percorso, numero, informazioni["testa"])
        if not intero:
            return io.BufferedReader(Flusso(fonti, pila, guasto=guasto),
                                     buffer_size=fonti.forma.blocco)
        with pila:
            return tutto(fonti, informazioni)
    except BaseException:
        pila.close()
        raise


def _salvataggio(informazioni: dict | None) -> bool:
    return (informazioni.get("perche") or "").startswith(registro.SALVATO)


def trova(elenco, impronta: str, dimensione: int | None,
          percorsi) -> tuple[str, dict, bool] | None:
    for numero in elenco.con_impronta(impronta, dimensione):
        informazioni = elenco.contenuto(numero)
        if informazioni is not None:
            return numero, informazioni, False
    for radice in elenco.radici():
        for percorso in percorsi:
            resto = _dentro_la_radice(radice["percorso"], percorso)
            if not resto:
                continue
            try:
                storia = elenco.storia(radice["id"], resto)
            except ValueError:
                continue
            for posto in reversed(storia):
                if posto.tipo != "file" or not posto.contenuto:
                    continue
                informazioni = elenco.contenuto(posto.contenuto)
                if (informazioni is not None and informazioni["stato"] in COMPLETI
                        and not _salvataggio(informazioni)):
                    return posto.contenuto, informazioni, True
    return None


def _dentro_la_radice(radice: str, percorso: str) -> str | None:
    try:
        resto = _resto(os.path.abspath(radice), os.path.abspath(percorso))
        if resto is None:
            resto = _resto(_vero(radice), _vero(percorso))
    except (OSError, ValueError):
        return None
    return resto


def parenti(elenco, numero: str, informazioni: dict) -> list[tuple[str, bytes, bool]]:
    trovati = []
    for altro in elenco.uguali(informazioni["dimensione"], informazioni["blake2b"],
                               informazioni["sha256"]):
        dati = elenco.contenuto(altro) if altro != numero else None
        if dati is not None and not _salvataggio(dati):
            trovati.append((altro, dati["testa"], False))
    for altro in elenco.salvati(numero):
        dati = elenco.contenuto(altro)
        if dati is not None:
            trovati.append((altro, dati["testa"], True))
    return trovati


def altre_fonti(cartella: Path, numero: str, informazioni: dict, vicini, copie=()):

    def copie_di(altro: str) -> list[Path]:
        trovate = []
        for copia_di in copie:
            try:
                copia = copia_di(altro)
            except (ErroreOfficina, OSError, ValueError):
                continue
            if copia is not None:
                trovate.append(Path(copia))
        return trovate

    fonti = [(copia, numero, informazioni["testa"], False) for copia in copie_di(numero)]
    for altro, testa, salvataggio in vicini:
        fonti.append((registro.percorso_contenuto(cartella, altro), altro, testa,
                      salvataggio))
        fonti.extend((copia, altro, testa, salvataggio) for copia in copie_di(altro))
    return fonti


class Riparatore(Sottofondo):

    nome = "archivio-sicuro-ripara-dopo"

    def __init__(self, prova, *, ogni: float = OGNI):
        super().__init__(sveglio=contextlib.nullcontext)
        self._prova = prova
        self._ogni = ogni

    def avvia(self) -> bool:
        return self._parti()

    def _lavora(self) -> None:
        while True:
            self._dormi_fermabile(self._ogni)
            try:
                if self._prova():
                    return
            except Fermato:
                raise
            except Exception:
                continue

    def istantanea(self) -> dict:
        return {"stato": self.stato}


__all__ = ["COMPLETI", "Flusso", "Fonti", "OGNI", "PERSA", "Persa", "Riparatore",
           "altre_fonti", "leggi", "lettore", "parenti", "trova", "tutto"]
