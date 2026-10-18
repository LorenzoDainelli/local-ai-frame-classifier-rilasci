from __future__ import annotations

import hashlib
import os
import stat
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from officina.errori import ErroreOfficina
from officina.sicuro import elenco as registro
from officina.sicuro import formato, metadati, sveglia
from officina.sicuro.copia import BLOCCATO, STATI_BUONI, Copiatore, Fermato
from officina.sicuro.diretto import Lettore
from officina.sicuro.disco import percorso_lungo
from officina.sicuro.sottofondo import PAUSA_SE_USI, Sottofondo


PEZZO_DI_LETTURA = 4 * 1024 * 1024
CANDIDATI = 3
ESEMPI = 1000
OGNI_QUANTI_PEZZI = 64
ROSSI = frozenset({
    "manca", "rovinato", "solo_nel_cloud", "illeggibile", "in_uso", "cambiato",
    "nome_strano", "cartella_illeggibile", "radice_illeggibile",
    "radice_nell_archivio"})
DEI_FILE = frozenset({
    "manca", "rovinato", "solo_nel_cloud", "illeggibile", "in_uso", "cambiato",
    "nome_strano"})


class _Diverso(Exception):
    pass


class _Illeggibile(Exception):

    def __init__(self, categoria: str):
        super().__init__(categoria)
        self.categoria = categoria


@dataclass
class Risposta:
    cartella: str
    file: int = 0
    byte: int = 0
    dentro: int = 0
    dalle_date: int = 0
    cartelle: int = 0
    collegamenti: int = 0
    speciali: int = 0
    saltate: int = 0
    byte_mancanti: int = 0
    conti: Counter = field(default_factory=Counter)
    esempi: dict[str, list[str]] = field(default_factory=dict)
    rovinati: set[str] = field(default_factory=set)
    da_riparare: set[str] = field(default_factory=set)
    radici: list[str] = field(default_factory=list)
    finito: bool = False

    def segna(self, categoria: str, relativo: str) -> None:
        self.conti[categoria] += 1
        esempi = self.esempi.setdefault(categoria, [])
        if len(esempi) < ESEMPI:
            esempi.append(relativo)

    def problema(self, codice: str, percorso: str | None = None) -> None:
        if codice in DEI_FILE:
            self.file += 1
        self.segna(codice, percorso or "")

    def conta(self, nome: str, quanti: int = 1) -> None:
        if nome == "saltate":
            self.saltate += quanti

    @property
    def mancano(self) -> int:
        return sum(self.conti[categoria] for categoria in DEI_FILE)

    @property
    def rossi(self) -> dict[str, int]:
        return {categoria: quanti for categoria, quanti in self.conti.items()
                if categoria in ROSSI and quanti}

    @property
    def verde(self) -> bool:
        return self.finito and not self.rossi

    def frase(self) -> str:
        if not self.finito:
            return "Il controllo non è finito: la risposta non è ancora sicura."
        if self.verde:
            if not self.file:
                return "Sì: in questa cartella non ci sono file."
            return f"Sì, è tutto dentro: {_numero(self.file)} file."
        if self.mancano:
            verbo = "manca" if self.mancano == 1 else "mancano"
            return (f"No, {verbo} {_numero(self.mancano)} file su "
                    f"{_numero(self.file)}.")
        cartelle = self.conti["cartella_illeggibile"]
        if cartelle:
            parole = ("cartella non si legge" if cartelle == 1
                      else "cartelle non si leggono")
            return f"Non lo so: {_numero(cartelle)} {parole}."
        return "Non lo so: questa cartella non si legge."


@dataclass
class Avanzamento:
    percorso: str | None = None
    file: int = 0
    letti: int = 0


def _numero(quanti: int) -> str:
    return f"{quanti:,}".replace(",", ".")


def _vero(percorso) -> str:
    return os.path.realpath(os.path.abspath(os.fspath(percorso)))


def _uguali(uno: str, altro: str) -> bool:
    return os.path.normcase(uno) == os.path.normcase(altro)


def _resto(sopra: str, sotto: str) -> str | None:
    if _uguali(sopra, sotto):
        return ""
    base = sopra.rstrip("\\/")
    if not os.path.normcase(sotto).startswith(os.path.normcase(base) + os.sep):
        return None
    return sotto[len(base) + 1:].replace(os.sep, "/")


def _sotto_di(relativo: str, cima: str) -> str | None:
    prefisso = cima + "/"
    if os.name == "nt":
        uguale = relativo.casefold() == cima.casefold()
        dentro = relativo[:len(prefisso)].casefold() == prefisso.casefold()
    else:
        uguale = relativo == cima
        dentro = relativo.startswith(prefisso)
    if uguale:
        return ""
    return relativo[len(prefisso):] if dentro else None


def _categoria_di(guasto: OSError) -> str:
    return ("in_uso" if getattr(guasto, "winerror", None) in BLOCCATO
            else "illeggibile")


def _segno(stato) -> tuple:
    return (stato.st_size, stato.st_mtime_ns, stato.st_ino, stato.st_dev)


class _Paragone:

    def __init__(self, lettore, ferma):
        self._lettore = lettore
        self._ferma = ferma
        self.dove = 0
        self.pezzi = 0
        self.blake = hashlib.blake2b(digest_size=formato.IMPRONTA)
        self.sha = hashlib.sha256()

    def __call__(self, chiaro: bytes) -> None:
        self.pezzi += 1
        if self.pezzi % OGNI_QUANTI_PEZZI == 0:
            self._ferma()
        try:
            letto = self._lettore.pezzo(self.dove, len(chiaro))
        except OSError as guasto:
            raise _Illeggibile(_categoria_di(guasto)) from guasto
        if letto != chiaro:
            raise _Diverso
        self.blake.update(letto)
        self.sha.update(letto)
        self.dove += len(letto)

    def impronte(self) -> dict:
        return {"blake2b": self.blake.hexdigest(), "sha256": self.sha.hexdigest()}


class Verificatore:

    def __init__(self, cartella: Path, elenco, chiave, *, apri=Lettore,
                 aspetta=None, salta=(), nuova_radice=None, adesso=time.time):
        self.cartella = Path(cartella)
        self.elenco = elenco
        self._chiave = chiave
        self._apri = apri
        self._aspetta = aspetta
        self._salta = tuple(salta)
        self._nuova_radice = nuova_radice
        self._adesso = adesso
        self._camminatore = Copiatore(self.cartella, elenco, chiave, salta=salta)
        self.avanzamento = Avanzamento()
        self.risposta: Risposta | None = None

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
                "riprova.", codice="archivio_sparito")

    def _cartella_scelta(self, percorso) -> tuple[str, str]:
        assoluto = os.path.abspath(os.fspath(percorso))
        try:
            stato = os.stat(percorso_lungo(assoluto))
        except FileNotFoundError:
            raise ErroreOfficina("Questa cartella non c'è più.",
                                 codice="cartella_sparita") from None
        except (OSError, ValueError):
            raise ErroreOfficina("Questa cartella non si legge.",
                                 codice="cartella_illeggibile") from None
        if not stat.S_ISDIR(stato.st_mode):
            raise ErroreOfficina("Qui serve una cartella, non un file.",
                                 codice="non_una_cartella")
        vero = _vero(assoluto)
        if _resto(_vero(self.cartella), vero) is not None:
            raise ErroreOfficina(
                "Questa è la cartella dell'Archivio sicuro: dentro ci sono solo "
                "i file cifrati.", codice="nell_archivio")
        return assoluto, vero

    def _vive(self) -> list[dict]:
        return [radice for radice in self.elenco.radici() if not radice["tolta"]]

    def _vicine(self, vero: str) -> list[tuple[str, str, str]]:
        vicine = []
        for radice in self._vive():
            dove = _vero(radice["percorso"])
            sopra = _resto(dove, vero)
            if sopra is not None:
                vicine.append((radice["id"], sopra, ""))
                continue
            sotto = _resto(vero, dove)
            if sotto is not None:
                vicine.append((radice["id"], "", sotto))
        return vicine

    def _posti(self, vicine, relativo: str) -> list:
        posti = []
        for id, sopra, sotto in vicine:
            if sotto:
                dentro = _sotto_di(relativo, sotto)
                if dentro is None or dentro == "":
                    continue
            else:
                dentro = f"{sopra}/{relativo}" if sopra else relativo
            try:
                posto = self.elenco.attuale(id, dentro)
            except ValueError:
                continue
            if posto is not None and posto.tipo == metadati.FILE and posto.contenuto:
                posti.append(posto)
        return posti

    def verifica(self, percorso) -> Risposta:
        assoluto, vero = self._cartella_scelta(percorso)
        risposta = Risposta(cartella=assoluto)
        self.risposta = risposta
        self.avanzamento = Avanzamento()
        vicine = self._vicine(vero)
        risposta.radici = sorted({id for id, _, sotto in vicine if not sotto})
        dimensioni = self.elenco.dimensioni()
        illeggibili: set[str] = set()
        for relativo, stato in self._camminatore.cammina(vero, risposta, illeggibili):
            self._ferma_se_serve()
            self.avanzamento.percorso = relativo
            tipo = metadati.tipo_di(stato)
            if tipo == metadati.CARTELLA:
                risposta.cartelle += 1
            elif tipo == metadati.COLLEGAMENTO:
                risposta.collegamenti += 1
            elif tipo == metadati.SPECIALE:
                risposta.speciali += 1
            else:
                self._un_file(vero, relativo, stato, vicine, dimensioni, risposta)
        self.avanzamento.percorso = None
        risposta.finito = True
        return risposta

    def _un_file(self, vero: str, relativo: str, stato, vicine, dimensioni,
                 risposta: Risposta) -> None:
        assoluto = os.path.join(vero, *relativo.split("/"))
        categoria = self._classifica(assoluto, relativo, stato, vicine, dimensioni,
                                     risposta)
        if categoria is None:
            return
        risposta.file += 1
        risposta.byte += stato.st_size
        self.avanzamento.file += 1
        if categoria in ("dentro", "dalle_date"):
            risposta.dentro += 1
            if categoria == "dalle_date":
                risposta.dalle_date += 1
            return
        risposta.byte_mancanti += stato.st_size
        risposta.segna(categoria, relativo)

    def _classifica(self, assoluto: str, relativo: str, stato, vicine, dimensioni,
                    risposta: Risposta) -> str | None:
        dimensione = int(stato.st_size)
        posti = self._posti(vicine, relativo)
        if metadati.solo_nel_cloud(stato):
            date = metadati.date_di(stato)
            for posto in posti:
                informazioni = self.elenco.contenuto(posto.contenuto)
                if (informazioni is not None
                        and informazioni["stato"] in STATI_BUONI
                        and informazioni["dimensione"] == dimensione
                        and all(posto.metadati.get(chiave) == date.get(chiave)
                                for chiave in ("modifica", "creazione"))):
                    return "dalle_date"
            return "solo_nel_cloud"
        if dimensione not in dimensioni:
            return "manca"
        try:
            lettore = self._apri(assoluto, True)
        except FileNotFoundError:
            return None
        except OSError as guasto:
            return _categoria_di(guasto)
        with lettore:
            if lettore.dimensione != dimensione:
                return "cambiato"
            try:
                esito = self._cerca(lettore, dimensione, posti, risposta)
            except _Illeggibile as guasto:
                return guasto.categoria
        try:
            dopo = os.lstat(percorso_lungo(assoluto))
        except FileNotFoundError:
            return None
        except OSError as guasto:
            return _categoria_di(guasto)
        if _segno(dopo) != _segno(stato):
            return "cambiato"
        return esito

    def _cerca(self, lettore, dimensione: int, posti, risposta: Risposta) -> str:
        provati: set[str] = set()
        rovinati = False
        for posto in posti:
            numero = posto.contenuto
            if numero in provati:
                continue
            informazioni = self.elenco.contenuto(numero)
            if (informazioni is None or informazioni["stato"] not in STATI_BUONI
                    or informazioni["dimensione"] != dimensione):
                continue
            provati.add(numero)
            esito = self._paragona(lettore, numero, informazioni, risposta)
            if esito == "uguale":
                return "dentro"
            rovinati |= esito == "rovinato"
            break
        impronte = self._impronte(lettore)
        if impronte is None:
            return "cambiato"
        trovati = 0
        for numero in self.elenco.uguali(dimensione, impronte["blake2b"],
                                         impronte["sha256"]):
            if numero in provati:
                continue
            informazioni = self.elenco.contenuto(numero)
            if informazioni is None or informazioni["stato"] not in STATI_BUONI:
                continue
            provati.add(numero)
            esito = self._paragona(lettore, numero, informazioni, risposta,
                                   impronte)
            if esito == "uguale":
                return "dentro"
            rovinati |= esito == "rovinato"
            trovati += 1
            if trovati >= CANDIDATI:
                break
        return "rovinato" if rovinati else "manca"

    def _impronte(self, lettore) -> dict | None:
        blake = hashlib.blake2b(digest_size=formato.IMPRONTA)
        sha = hashlib.sha256()
        dove = 0
        while dove < lettore.dimensione:
            self._ferma_se_serve()
            try:
                pezzo = lettore.pezzo(dove, min(PEZZO_DI_LETTURA,
                                                lettore.dimensione - dove))
            except OSError as guasto:
                raise _Illeggibile(_categoria_di(guasto)) from guasto
            if not pezzo:
                return None
            blake.update(pezzo)
            sha.update(pezzo)
            dove += len(pezzo)
            self.avanzamento.letti += len(pezzo)
        return {"blake2b": blake.hexdigest(), "sha256": sha.hexdigest()}

    def _paragona(self, lettore, numero: str, informazioni: dict,
                  risposta: Risposta, impronte: dict | None = None) -> str:
        attese = {"blake2b": informazioni["blake2b"], "sha256": informazioni["sha256"]}
        if impronte is not None and impronte != attese:
            return "diverso"
        blob = registro.percorso_contenuto(self.cartella, numero)
        try:
            copia = self._apri(blob, True)
        except OSError:
            self._archivio_c_e()
            risposta.rovinati.add(numero)
            return "rovinato"
        paragone = _Paragone(lettore, self._ferma_se_serve)
        with copia:
            try:
                controllo = formato.controlla(
                    copia, self._chiave, numero=bytes.fromhex(numero),
                    testa=informazioni["testa"], impronte=attese,
                    ogni_pezzo=paragone)
            except _Diverso:
                return "diverso"
            except (ErroreOfficina, OSError, ValueError):
                self._archivio_c_e()
                risposta.rovinati.add(numero)
                return "rovinato"
            finally:
                self.avanzamento.letti += paragone.dove
        if not controllo.leggibile:
            self._archivio_c_e()
            risposta.rovinati.add(numero)
            return "rovinato"
        if paragone.dove != informazioni["dimensione"] or paragone.impronte() != attese:
            return "diverso"
        if not controllo.buono:
            risposta.da_riparare.add(numero)
        return "uguale"

    def aggiungi(self, percorso) -> dict:
        assoluto, vero = self._cartella_scelta(percorso)
        for radice in self._vive():
            if _resto(_vero(radice["percorso"]), vero) is not None:
                return {"radice": radice["id"], "percorso": radice["percorso"],
                        "nuova": False}
        id = (self._nuova_radice(assoluto) if self._nuova_radice is not None
              else registro.nuova_chiave())
        if any(radice["id"] == id for radice in self.elenco.radici()):
            raise ErroreOfficina(
                "Questo nome di cartella nell'archivio è già usato da un'altra.",
                codice="radice_gia_usata")
        self.elenco.registra([registro.fatto_radice(id, assoluto,
                                                    quando=self._adesso())])
        self.elenco.salva()
        return {"radice": id, "percorso": assoluto, "nuova": True}


class Verifica(Sottofondo):

    nome = "archivio-sicuro-dentro"

    def __init__(self, cartella: Path, elenco, chiave, *, sveglio=sveglia.sveglio,
                 rallenta=None, pausa_se_usi: float = PAUSA_SE_USI,
                 **per_verificatore):
        super().__init__(sveglio=sveglio, rallenta=rallenta,
                         pausa_se_usi=pausa_se_usi)
        self.verificatore = Verificatore(cartella, elenco, chiave,
                                         aspetta=self._aspetta, **per_verificatore)

    def avvia(self, percorso) -> bool:
        return self._parti(os.fspath(percorso))

    def _azzera(self) -> None:
        self.verificatore.risposta = None
        self.verificatore.avanzamento = Avanzamento()

    def _lavora(self, percorso: str) -> None:
        self.verificatore.verifica(percorso)

    def istantanea(self) -> dict:
        risposta = self.verificatore.risposta
        avanzamento = self.verificatore.avanzamento
        fuori = {"stato": self.stato, "percorso": avanzamento.percorso,
                 "letti": avanzamento.letti, "errore": self.errore,
                 "codice": self.codice}
        if risposta is None:
            return fuori | {"cartella": None, "file": 0, "dentro": 0, "mancano": 0,
                            "verde": False, "finito": False, "frase": None,
                            "rossi": {}, "esempi": {}}
        return fuori | {
            "cartella": risposta.cartella,
            "file": risposta.file,
            "byte": risposta.byte,
            "dentro": risposta.dentro,
            "mancano": risposta.mancano,
            "byte_mancanti": risposta.byte_mancanti,
            "cartelle": risposta.cartelle,
            "collegamenti": risposta.collegamenti,
            "verde": risposta.verde,
            "finito": risposta.finito,
            "frase": risposta.frase(),
            "rossi": risposta.rossi,
            "esempi": {categoria: list(esempi)
                       for categoria, esempi in risposta.esempi.items()
                       if categoria in ROSSI},
            "da_controllare": sorted(risposta.rovinati | risposta.da_riparare),
        }


__all__ = ["DEI_FILE", "Fermato", "ROSSI", "Risposta", "Verifica", "Verificatore"]
