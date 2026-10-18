from __future__ import annotations

import errno
import hashlib
import json
import os
import stat
import string
import time
from collections import Counter
from contextlib import ExitStack
from dataclasses import dataclass, field
from pathlib import Path

from officina.errori import ErroreOfficina
from officina.sicuro import elenco as registro
from officina.sicuro import formato, sveglia
from officina.sicuro.copia import (STATI_BUONI, Copiatore, DiscoArchivioGuasto,
                                   Fermato)
from officina.sicuro.diretto import Lettore
from officina.sicuro.disco import fissa_cartella, percorso_lungo
from officina.sicuro.sottofondo import PAUSA_SE_USI, Sottofondo


__all__ = ["COME", "Controllore", "ControlloMensile", "Esito", "Fermato",
           "Rapporto", "buchi_di", "intervalli"]

MESE = 30 * 24 * 3600
GIORNO = 24 * 3600
PEZZO_DI_LETTURA = 4 * 1024 * 1024
OGNI_QUANTI_BLOCCHI = 64
POSTI_NEL_GEMELLO = 50
FATTI_PER_NOTA = 20000
PESO_PER_NOTA = 16 * 1024 * 1024
FIRMA = 16
PIENO = (errno.ENOSPC, getattr(errno, "EDQUOT", errno.ENOSPC))
COME = ("intatto", "pezzetti", "copia", "pezzi", "originale", "trovato",
        "perso")


def intervalli(numeri) -> list[list[int]]:
    fatti: list[list[int]] = []
    for numero in sorted(set(numeri)):
        if fatti and fatti[-1][1] == numero - 1:
            fatti[-1][1] = numero
        else:
            fatti.append([numero, numero])
    return fatti


def buchi_di(dati, blocchi: int) -> frozenset[int] | None:
    if not isinstance(dati, dict):
        return None
    coppie = dati.get("buchi")
    if not isinstance(coppie, list):
        return None
    buchi: set[int] = set()
    for coppia in coppie:
        if (not isinstance(coppia, list) or len(coppia) != 2
                or not all(type(numero) is int and numero >= 0 for numero in coppia)
                or coppia[0] > coppia[1]):
            return None
        buchi.update(range(coppia[0], min(coppia[1], blocchi - 1) + 1))
    return frozenset(buchi)


def _impronte(informazioni) -> dict:
    if isinstance(informazioni, dict):
        return {"blake2b": informazioni["blake2b"], "sha256": informazioni["sha256"]}
    return {"blake2b": informazioni.blake2b, "sha256": informazioni.sha256}


def _stesse(impronte, attese: dict) -> bool:
    return (impronte is not None and impronte.get("blake2b") == attese["blake2b"]
            and impronte.get("sha256") == attese["sha256"])


def _firma(chiaro: bytes) -> bytes:
    return hashlib.blake2b(chiaro, digest_size=FIRMA).digest()


def _salvataggio(informazioni: dict) -> bool:
    return (informazioni.get("perche") or "").startswith(registro.SALVATO)


def _numero(quanti: int) -> str:
    return f"{quanti:,}".replace(",", ".")


def _dischi() -> list[str]:
    if os.name != "nt":
        return []
    cestini, dischi = [], []
    for lettera in string.ascii_uppercase[2:]:
        disco = f"{lettera}:\\"
        if os.path.isdir(disco):
            cestini.append(disco + "$Recycle.Bin")
            dischi.append(disco)
    return cestini + dischi


class _Silenzio:

    def problema(self, codice: str, percorso: str | None = None) -> None:
        pass

    def conta(self, nome: str, quanti: int = 1) -> None:
        pass


@dataclass
class Esito:
    numero: str
    come: str
    prima: str
    dopo: str
    riparato: bool = False
    gemello: str | None = None
    salvataggio: bool = False


@dataclass
class Avanzamento:
    fase: str | None = None
    numero: str | None = None
    fatti: int = 0
    totale: int = 0
    letti: int = 0


@dataclass
class Rapporto:
    totale: int = 0
    controllati: int = 0
    byte: int = 0
    come: Counter = field(default_factory=Counter)
    riparati: list[str] = field(default_factory=list)
    gemelli: dict[str, str] = field(default_factory=dict)
    persi: list[str] = field(default_factory=list)
    salvati: dict[str, str] = field(default_factory=dict)
    rimandati: list[str] = field(default_factory=list)
    note: int = 0
    note_riparate: int = 0
    note_rovinate: list[str] = field(default_factory=list)
    note_rifatte: int = 0
    problemi: list[str] = field(default_factory=list)
    finito: bool = False

    def problema(self, codice: str) -> None:
        if codice not in self.problemi:
            self.problemi.append(codice)

    def segna(self, esito: Esito) -> None:
        self.come[esito.come] += 1
        if esito.riparato:
            self.riparati.append(esito.numero)
        if esito.come == "perso" and not esito.salvataggio:
            self.persi.append(esito.numero)

    def ritrovato(self, esito: Esito) -> None:
        if esito.numero in self.persi:
            self.persi.remove(esito.numero)
            self.come["perso"] -= 1
            if not self.come["perso"]:
                del self.come["perso"]
        self.segna(esito)

    @property
    def allarme(self) -> bool:
        return bool(self.persi)

    @property
    def verde(self) -> bool:
        return (self.finito and not self.persi and not self.rimandati
                and not self.problemi)

    def frase(self) -> str:
        if self.persi:
            quanti = len(self.persi)
            frase = (f"Attenzione: {_numero(quanti)} "
                     + ("file è rovinato e non si ripara."
                        if quanti == 1 else "file sono rovinati e non si riparano."))
            if self.salvati:
                frase += " Ho messo da parte i pezzi buoni."
            return frase
        if not self.finito:
            return "Il controllo non è finito."
        if self.rimandati:
            quanti = len(self.rimandati)
            return (f"Il disco dell'archivio è pieno: {_numero(quanti)} file da "
                    + ("riparare aspetta" if quanti == 1 else "riparare aspettano")
                    + " un po' di spazio.")
        if not self.controllati:
            return "Non c'era niente da rileggere."
        frase = f"Tutto a posto: {_numero(self.controllati)} file riletti"
        if self.riparati:
            frase += f", {_numero(len(self.riparati))} riparati"
        return frase + "."


@dataclass
class _Fonte:
    percorso: Path
    numero: bytes
    testa: bytes | None
    stessa: bool
    salvataggio: bool = False
    aperta: bool = False
    contenuto: formato.Contenuto | None = None
    buchi: frozenset[int] = frozenset()


class _Pezzi:

    def __init__(self, apri, chiave, forma: formato.Forma, pila: ExitStack):
        self._apri = apri
        self._chiave = chiave
        self.forma = forma
        self._pila = pila
        self._fonti: list[_Fonte] = []

    def aggiungi(self, percorso, numero: bytes, testa: bytes | None, stessa: bool,
                 salvataggio: bool = False) -> None:
        self._fonti.append(_Fonte(Path(percorso), numero, testa, stessa, salvataggio))

    def _contenuto(self, fonte: _Fonte) -> formato.Contenuto | None:
        if fonte.aperta:
            return fonte.contenuto
        fonte.aperta = True
        try:
            lettore = self._pila.enter_context(self._apri(fonte.percorso, True))
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

    def blocco(self, numero: int) -> bytes | None:
        for fonte in self._fonti:
            contenuto = self._contenuto(fonte)
            if contenuto is None or numero in fonte.buchi:
                continue
            try:
                return contenuto.blocco(numero)
            except formato.ContenutoRovinato:
                continue
        return None

    def meta(self, attese: dict, testa: bytes) -> dict | None:
        for fonte in self._fonti:
            if not fonte.stessa:
                continue
            contenuto = self._contenuto(fonte)
            if (contenuto is not None and _stesse(contenuto.impronte, attese)
                    and contenuto.forma.testa() == testa
                    and contenuto.riscrivibile()):
                return contenuto.dati
        return None


class Controllore:

    def __init__(self, cartella: Path, elenco, chiave, *, apri=Lettore,
                 aspetta=None, copie=(), luoghi=None, adesso=time.time,
                 salta=()):
        self.cartella = Path(cartella)
        self.elenco = elenco
        self._chiave = chiave
        self._apri = apri
        self._aspetta = aspetta
        self._copie = tuple(copie)
        self._luoghi = luoghi
        self._adesso = adesso
        self._camminatore = Copiatore(self.cartella, elenco, chiave, salta=salta)
        self.avanzamento = Avanzamento()
        self.rapporto: Rapporto | None = None
        self._pieno = False
        self._male = 0
        self._cambi: list[dict] = []

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

    def _blob(self, numero: str) -> Path:
        return registro.percorso_contenuto(self.cartella, numero)

    def da_fare(self) -> list[str]:
        adesso = self._adesso()
        return self.elenco.da_controllare(adesso - MESE, adesso - GIORNO)

    def controlla(self, numeri=None) -> Rapporto:
        tutto = numeri is None
        self._archivio_c_e()
        lista = self.da_fare() if tutto else list(dict.fromkeys(numeri))
        rapporto = Rapporto(totale=len(lista))
        self.rapporto = rapporto
        self.avanzamento = Avanzamento(fase="contenuti", totale=len(lista))
        self._pieno = False
        self._male = 0
        self._cambi = []
        try:
            for numero in lista:
                self._ferma_se_serve()
                esito = self._uno(numero)
                self.avanzamento.fatti += 1
                if esito is not None:
                    rapporto.segna(esito)
            self._riprova_coi_gemelli(list(rapporto.persi))
            if rapporto.persi:
                self.avanzamento.fase = "ricerca"
                self.avanzamento.numero = None
                self._cerca_ovunque(list(rapporto.persi))
                self.avanzamento.fase = "salvataggio"
                for numero in list(rapporto.persi):
                    self._ferma_se_serve()
                    self._salva_i_pezzi(numero)
            if tutto:
                self.avanzamento.fase = "note"
                self._note()
        except BaseException:
            self._metti_via(severo=False)
            raise
        finally:
            self.avanzamento.fase = None
            self.avanzamento.numero = None
        self._metti_via(severo=True)
        if tutto and rapporto.controllati:
            self.elenco.fissa()
        rapporto.finito = True
        return rapporto

    def _metti_via(self, severo: bool) -> None:
        cambi, self._cambi = self._cambi, []
        if cambi and not self._pieno:
            try:
                self.elenco.scrivi_nota(cambi, self._adesso())
            except OSError as guasto:
                if guasto.errno in PIENO:
                    self._senza_spazio()
                if self.rapporto is not None:
                    self.rapporto.problema("nota_non_scritta")
            except ErroreOfficina:
                if self.rapporto is not None:
                    self.rapporto.problema("nota_non_scritta")
        try:
            self.elenco.salva()
        except Exception:
            if severo:
                raise

    def _registra(self, fatti: list[dict]) -> None:
        try:
            self.elenco.registra(fatti)
        except OSError as guasto:
            if guasto.errno in PIENO:
                raise ErroreOfficina(
                    "Il disco dell'Archivio sicuro è pieno: non riesco più a "
                    "scrivere l'elenco. Libera un po' di spazio e riprova.",
                    codice="spazio_finito") from guasto
            raise

    def _senza_spazio(self) -> None:
        self._pieno = True
        if self.rapporto is not None:
            self.rapporto.problema("spazio_finito")

    def _non_scritto(self, guasto: OSError) -> bool:
        if guasto.errno in PIENO:
            self._senza_spazio()
            return False
        self._archivio_c_e()
        if self.rapporto is not None:
            self.rapporto.problema("non_scritto")
        return False

    def _scritto_male(self) -> None:
        self._male += 1
        if self._male >= 2:
            raise DiscoArchivioGuasto(
                "Il disco dell'archivio ha scritto male due volte di fila un file "
                "riparato: mi fermo per non rovinare niente.")

    def _ogni_pezzo(self):
        pezzi = [0]

        def ogni(chiaro: bytes) -> None:
            pezzi[0] += 1
            self.avanzamento.letti += len(chiaro)
            if pezzi[0] % OGNI_QUANTI_BLOCCHI == 0:
                self._ferma_se_serve()

        return ogni

    def _controllo(self, blob: Path, numero: str,
                   informazioni: dict | None) -> formato.Controllo | None:
        try:
            lettore = self._apri(blob, True)
        except (OSError, ValueError):
            self._archivio_c_e()
            return None
        with lettore:
            try:
                return formato.controlla(
                    lettore, self._chiave, numero=bytes.fromhex(numero),
                    testa=None if informazioni is None else informazioni["testa"],
                    impronte=None if informazioni is None else _impronte(informazioni),
                    ogni_pezzo=self._ogni_pezzo())
            except (ErroreOfficina, OSError, ValueError):
                self._archivio_c_e()
                return None

    def _sano(self, percorso: Path, numero: str, testa: bytes | None,
              impronte: dict | None) -> bool:
        try:
            with self._apri(percorso, True) as lettore:
                return formato.controlla(lettore, self._chiave,
                                         numero=bytes.fromhex(numero), testa=testa,
                                         impronte=impronte).buono
        except (ErroreOfficina, OSError, ValueError):
            return False

    def _sostituisci(self, blob: Path, numero: str, scrivi) -> bool:
        if self._pieno:
            return False
        provvisorio = blob.with_name(blob.name + ".nuovo")
        try:
            try:
                blob.parent.mkdir(parents=True, exist_ok=True)
                with open(provvisorio, "w+b") as fuori:
                    attese = scrivi(fuori)
                    if attese is None:
                        return False
                    fuori.flush()
                    os.fsync(fuori.fileno())
            except (formato.ContenutoRovinato, formato.FileCambiato):
                return False
            except OSError as guasto:
                return self._non_scritto(guasto)
            if not self._sano(provvisorio, numero, *attese):
                self._scritto_male()
                return False
            self._male = 0
            try:
                os.replace(provvisorio, blob)
                fissa_cartella(blob.parent)
            except OSError as guasto:
                return self._non_scritto(guasto)
            return True
        finally:
            try:
                provvisorio.unlink(missing_ok=True)
            except OSError:
                pass

    def _copia_byte(self, lettore, fuori) -> bool:
        dove, fine = 0, lettore.dimensione
        while dove < fine:
            self._ferma_se_serve()
            try:
                pezzo = lettore.pezzo(dove, min(PEZZO_DI_LETTURA, fine - dove))
            except OSError:
                return False
            if not pezzo:
                return False
            fuori.write(pezzo)
            dove += len(pezzo)
            self.avanzamento.letti += len(pezzo)
        return True

    def _impronte_di(self, lettore) -> dict | None:
        blake = hashlib.blake2b(digest_size=formato.IMPRONTA)
        sha = hashlib.sha256()
        dove = 0
        while dove < lettore.dimensione:
            self._ferma_se_serve()
            try:
                pezzo = lettore.pezzo(dove, min(PEZZO_DI_LETTURA,
                                                lettore.dimensione - dove))
            except OSError:
                return None
            if not pezzo:
                return None
            blake.update(pezzo)
            sha.update(pezzo)
            dove += len(pezzo)
            self.avanzamento.letti += len(pezzo)
        return {"blake2b": blake.hexdigest(), "sha256": sha.hexdigest()}

    def _attese(self, informazioni: dict | None) -> tuple:
        if informazioni is None:
            return None, None
        return informazioni["testa"], _impronte(informazioni)

    def _con_la_parita(self, blob: Path, numero: str,
                       informazioni: dict | None) -> bool:
        testa, impronte = self._attese(informazioni)

        def scrivi(fuori):
            try:
                lettore = self._apri(blob, True)
            except (OSError, ValueError):
                return None
            with lettore:
                formato.ripara(lettore, fuori, self._chiave,
                               numero=bytes.fromhex(numero), testa=testa,
                               impronte=impronte)
            return testa, impronte

        return self._sostituisci(blob, numero, scrivi)

    def _copie_di(self, numero: str) -> list[Path]:
        trovate: list[Path] = []
        for copie in self._copie:
            try:
                percorso = copie(numero)
            except (ErroreOfficina, OSError, ValueError):
                continue
            if percorso is not None and Path(percorso) not in trovate:
                trovate.append(Path(percorso))
        return trovate

    def _dalla_copia(self, copia: Path, blob: Path, numero: str,
                     informazioni: dict | None) -> bool:
        testa, impronte = self._attese(informazioni)
        try:
            with self._apri(copia, True) as lettore:
                controllo = formato.controlla(lettore, self._chiave,
                                              numero=bytes.fromhex(numero),
                                              testa=testa, impronte=impronte)
        except (ErroreOfficina, OSError, ValueError):
            return False
        if not controllo.leggibile:
            return False

        def scrivi(fuori):
            try:
                lettore = self._apri(copia, True)
            except (OSError, ValueError):
                return None
            with lettore:
                if controllo.buono:
                    if not self._copia_byte(lettore, fuori):
                        return None
                else:
                    formato.ripara(lettore, fuori, self._chiave,
                                   numero=bytes.fromhex(numero), testa=testa,
                                   impronte=impronte)
            return testa, impronte

        return self._sostituisci(blob, numero, scrivi)

    def _gemelli(self, numero: str, informazioni: dict) -> list[tuple[str, dict]]:
        gemelli = []
        for altro in self.elenco.uguali(informazioni["dimensione"],
                                        informazioni["blake2b"],
                                        informazioni["sha256"]):
            if altro == numero:
                continue
            dati = self.elenco.contenuto(altro)
            if dati is not None and not _salvataggio(dati):
                gemelli.append((altro, dati))
        gemelli.sort(key=lambda coppia: coppia[1]["stato"] not in STATI_BUONI)
        return gemelli

    def _salvataggi(self, numero: str) -> list[tuple[str, dict]]:
        salvati = []
        for altro in self.elenco.salvati(numero):
            dati = self.elenco.contenuto(altro)
            if dati is not None:
                salvati.append((altro, dati))
        return salvati

    def _pezzi(self, numero: str, informazioni: dict, copie,
               pila: ExitStack) -> tuple[_Pezzi, list[tuple[str, dict]]]:
        forma = formato.Forma.da_testa(informazioni["testa"])
        pezzi = _Pezzi(self._apri, self._chiave, forma, pila)
        proprio = bytes.fromhex(numero)
        pezzi.aggiungi(self._blob(numero), proprio, informazioni["testa"], True)
        for copia in copie:
            pezzi.aggiungi(copia, proprio, informazioni["testa"], True)
        sani = []
        for altro, dati in self._gemelli(numero, informazioni):
            pezzi.aggiungi(self._blob(altro), bytes.fromhex(altro), dati["testa"],
                           False)
            if dati["stato"] in STATI_BUONI:
                sani.append((altro, dati))
        for altro, dati in self._salvataggi(numero):
            pezzi.aggiungi(self._blob(altro), bytes.fromhex(altro), dati["testa"],
                           False, salvataggio=True)
        return pezzi, sani

    def _leggi(self, pezzi: _Pezzi) -> tuple[list[int], dict, list[bytes | None]]:
        blake = hashlib.blake2b(digest_size=formato.IMPRONTA)
        sha = hashlib.sha256()
        buchi: list[int] = []
        firme: list[bytes | None] = []
        for blocco in range(pezzi.forma.blocchi):
            if blocco % OGNI_QUANTI_BLOCCHI == 0:
                self._ferma_se_serve()
            chiaro = pezzi.blocco(blocco)
            if chiaro is None:
                buchi.append(blocco)
                firme.append(None)
                continue
            blake.update(chiaro)
            sha.update(chiaro)
            firme.append(_firma(chiaro))
            self.avanzamento.letti += len(chiaro)
        return buchi, {"blake2b": blake.hexdigest(), "sha256": sha.hexdigest()}, firme

    def _scrivi_pezzi(self, pezzi: _Pezzi, fuori, firme) -> bool:
        for blocco, firma in enumerate(firme):
            if blocco % OGNI_QUANTI_BLOCCHI == 0:
                self._ferma_se_serve()
            if firma is None:
                fuori.write(bytes(pezzi.forma.lunghezza(blocco)))
                continue
            chiaro = pezzi.blocco(blocco)
            if chiaro is None or _firma(chiaro) != firma:
                return False
            fuori.write(chiaro)
        return True

    def _ricomponi(self, numero: str, informazioni: dict,
                   copie) -> tuple[bool, str | None] | None:
        attese = _impronte(informazioni)
        with ExitStack() as pila:
            pezzi, sani = self._pezzi(numero, informazioni, copie, pila)
            dati = pezzi.meta(attese, informazioni["testa"])
            if dati is None:
                sano = self._gemello_sano(sani)
                if sano is not None:
                    return False, sano
            buchi, impronte, firme = self._leggi(pezzi)
            if buchi or impronte != attese:
                return None
            if dati is not None and self._riscrivi(numero, informazioni, pezzi,
                                                   firme, dati):
                return True, None
            sano = self._gemello_sano(sani) if dati is not None else None
            if sano is not None:
                return False, sano
            gemello = self._nuovo_gemello(
                numero, informazioni,
                lambda scrittore: self._scrivi_pezzi(pezzi, scrittore, firme))
        return None if gemello is None else (False, gemello)

    def _gemello_sano(self, sani: list[tuple[str, dict]]) -> str | None:
        for altro, dati in sani:
            if self._sano(self._blob(altro), altro, dati["testa"], _impronte(dati)):
                return altro
        return None

    def _riscrivi(self, numero: str, informazioni: dict, pezzi: _Pezzi, firme,
                  dati: dict) -> bool:
        attese = _impronte(informazioni)

        def scrivi(fuori):
            scrittore = formato.Scrittore(fuori, self._chiave,
                                          informazioni["dimensione"], dati,
                                          bytes.fromhex(numero))
            if scrittore.forma.testa() != informazioni["testa"]:
                return None
            if not self._scrivi_pezzi(pezzi, scrittore, firme):
                return None
            scritto = scrittore.finisci()
            if not _stesse(_impronte(scritto), attese):
                return None
            return informazioni["testa"], attese

        return self._sostituisci(self._blob(numero), numero, scrivi)

    def _stessi(self, numero: str) -> list[str]:
        informazioni = self.elenco.contenuto(numero)
        altri = [] if informazioni is None else [
            altro for altro in self.elenco.uguali(informazioni["dimensione"],
                                                  informazioni["blake2b"],
                                                  informazioni["sha256"])
            if altro != numero]
        return [numero, *altri][:registro.ORIGINI]

    def _fatti_per(self, numero: str, nuovo: str) -> list[dict]:
        posti = {posto.chiave: posto for stesso in self._stessi(numero)
                 for posto in self.elenco.posti_di(stesso, anche_spariti=True)}
        posti = list(posti.values())[-POSTI_NEL_GEMELLO:]
        radici = {radice["id"]: radice for radice in self.elenco.radici()}
        fatti = []
        for id in dict.fromkeys(posto.radice for posto in posti):
            if id in radici:
                fatti.append(Copiatore._fatto_radice(radici[id]))
        for posto in posti:
            fatti.append({"fatto": "posto", "chiave": posto.chiave,
                          "radice": posto.radice, "percorso": posto.percorso,
                          "tipo": posto.tipo, "contenuto": nuovo,
                          "metadati": dict(posto.metadati),
                          "segni": list(posto.segni), "quando": posto.visto})
            if posto.sparito is not None:
                fatti.append(registro.fatto_sparito(posto.chiave, posto.sparito))
        return [fatto for fatto in fatti if registro.valido(fatto)]

    def _scrivi_nuovo(self, nuovo: bytes, informazioni: dict, dati: dict,
                      scrivi_dentro, stato: str,
                      perche: str | None = None) -> str | None:
        if self._pieno:
            return None
        attese = _impronte(informazioni) if stato == "buono" else None
        scritti: list[formato.Scritto] = []

        def scrivi(fuori):
            scrittore = formato.Scrittore(fuori, self._chiave,
                                          informazioni["dimensione"], dati, nuovo)
            if not scrivi_dentro(scrittore):
                return None
            scritto = scrittore.finisci()
            if attese is not None and not _stesse(_impronte(scritto), attese):
                return None
            scritti.append(scritto)
            return scritto.testa, _impronte(scritto)

        if not self._sostituisci(self._blob(nuovo.hex()), nuovo.hex(), scrivi):
            return None
        self._registra([registro.fatto_contenuto(scritti[0], stato, perche=perche,
                                                 quando=self._adesso())])
        return nuovo.hex()

    def _nuovo_gemello(self, numero: str, informazioni: dict,
                       scrivi_dentro) -> str | None:
        nuovo = formato.nuovo_numero()
        dati = {"gemello_di": self._stessi(numero),
                "fatti": self._fatti_per(numero, nuovo.hex()),
                "scritto": self._adesso()}
        gemello = self._scrivi_nuovo(nuovo, informazioni, dati, scrivi_dentro,
                                     "buono")
        if gemello is not None:
            self.rapporto.gemelli[numero] = gemello
        return gemello

    def _originali(self, numero: str):
        radici = {radice["id"]: radice["percorso"] for radice in self.elenco.radici()}
        visti: set[str] = set()
        for posto in reversed(self.elenco.posti_di(numero, anche_spariti=True)):
            cima = radici.get(posto.radice)
            if posto.tipo != "file" or cima is None:
                continue
            assoluto = os.path.join(cima, *posto.percorso.split("/"))
            if assoluto not in visti:
                visti.add(assoluto)
                yield assoluto

    def _dal_file(self, percorso: str, numero: str, informazioni: dict) -> str | None:
        if self._pieno:
            return None
        try:
            lettore = self._apri(percorso, True)
        except (OSError, ValueError):
            return None
        with lettore:
            if lettore.dimensione != informazioni["dimensione"]:
                return None
            if self._impronte_di(lettore) != _impronte(informazioni):
                return None
            return self._nuovo_gemello(
                numero, informazioni,
                lambda scrittore: self._copia_byte(lettore, scrittore))

    def _uno(self, numero: str) -> Esito | None:
        informazioni = self.elenco.contenuto(numero)
        if informazioni is None:
            return None
        self.avanzamento.numero = numero
        blob = self._blob(numero)
        controllo = self._controllo(blob, numero, informazioni)
        self.rapporto.controllati += 1
        self.rapporto.byte += informazioni["dimensione"]
        if controllo is not None and controllo.buono:
            return self._esito(numero, informazioni, "intatto", controllo)
        if not self._pieno:
            esito = self._ripara(numero, informazioni, blob, controllo)
            if esito is not None:
                return esito
        if self._pieno:
            self.rapporto.rimandati.append(numero)
            return None
        return self._esito(numero, informazioni, "perso", controllo)

    def _ripara(self, numero: str, informazioni: dict, blob: Path,
                controllo: formato.Controllo | None) -> Esito | None:
        if (controllo is not None and controllo.riparabile
                and self._con_la_parita(blob, numero, informazioni)):
            return self._esito(numero, informazioni, "pezzetti", controllo, True)
        copie = self._copie_di(numero)
        for copia in copie:
            if self._dalla_copia(copia, blob, numero, informazioni):
                return self._esito(numero, informazioni, "copia", controllo, True)
        rimesso = self._ricomponi(numero, informazioni, copie)
        if rimesso is not None:
            return self._esito(numero, informazioni, "pezzi", controllo, *rimesso)
        for percorso in self._originali(numero):
            gemello = self._dal_file(percorso, numero, informazioni)
            if gemello is not None:
                rimesso = self._ricomponi(numero, informazioni, copie) or (False, gemello)
                return self._esito(numero, informazioni, "originale", controllo,
                                   *rimesso)
        return None

    def _esito(self, numero: str, informazioni: dict, come: str,
               controllo: formato.Controllo | None, riparato: bool = False,
               gemello: str | None = None) -> Esito:
        prima, perche_prima = informazioni["stato"], informazioni["perche"]
        if come == "intatto":
            stato = "riparato" if prima in ("rovinato", "senza_informazioni") else prima
            perche = perche_prima if stato == prima else "riletto"
        elif riparato:
            stato = "incompleto" if prima == "incompleto" else "riparato"
            perche = come
        elif gemello is not None:
            leggibile = controllo is not None and controllo.leggibile
            stato = ("senza_informazioni"
                     if prima == "senza_informazioni" and leggibile else "rovinato")
            perche = "nel_gemello"
        else:
            stato, perche = "rovinato", "non_riparato"
        if _salvataggio(informazioni):
            perche = perche_prima
            if stato == "riparato":
                stato = "incompleto"
        fatto = registro.fatto_stato(numero, stato, perche, quando=self._adesso())
        self._registra([fatto])
        if (stato, perche) != (prima, perche_prima):
            if stato == "rovinato":
                self._cambi.append(registro.fatto_ricordo(informazioni))
            self._cambi.append(fatto)
        return Esito(numero, come, prima, stato, riparato, gemello,
                     _salvataggio(informazioni))

    def _riprova_coi_gemelli(self, persi: list[str]) -> None:
        for numero in persi:
            self._ferma_se_serve()
            informazioni = self.elenco.contenuto(numero)
            if (self._pieno or informazioni is None
                    or not self._gemelli(numero, informazioni)):
                continue
            self.avanzamento.numero = numero
            rimesso = self._ricomponi(numero, informazioni, self._copie_di(numero))
            if rimesso is not None:
                controllo = self._controllo(self._blob(numero), numero, informazioni)
                self.rapporto.ritrovato(self._esito(numero, informazioni, "pezzi",
                                                    controllo, *rimesso))

    def _dove_cercare(self) -> list[str]:
        if self._luoghi is not None:
            cartelle = [os.fspath(cartella) for cartella in self._luoghi()]
        else:
            radici = sorted(self.elenco.radici(), key=lambda radice: radice["tolta"])
            cartelle = [radice["percorso"] for radice in radici] + _dischi()
        return list(dict.fromkeys(cartelle))

    def _cerca_ovunque(self, persi: list[str]) -> None:
        cercati: dict[int, list[str]] = {}
        for numero in persi:
            informazioni = self.elenco.contenuto(numero)
            if informazioni is not None and not _salvataggio(informazioni):
                cercati.setdefault(informazioni["dimensione"], []).append(numero)
        visti: set[tuple[int, int]] = set()
        for cartella in self._dove_cercare():
            if not cercati or self._pieno:
                return
            for relativo, dati in self._camminatore.cammina(cartella, _Silenzio(),
                                                            set()):
                self._ferma_se_serve()
                if not stat.S_ISREG(dati.st_mode) or dati.st_size not in cercati:
                    continue
                if dati.st_ino:
                    if (dati.st_dev, dati.st_ino) in visti:
                        continue
                    visti.add((dati.st_dev, dati.st_ino))
                self._prova_qui(os.path.join(cartella, *relativo.split("/")),
                                dati.st_size, cercati)
                if not cercati or self._pieno:
                    return

    def _prova_qui(self, percorso: str, dimensione: int,
                   cercati: dict[int, list[str]]) -> None:
        try:
            lettore = self._apri(percorso, True)
        except (OSError, ValueError):
            return
        with lettore:
            if lettore.dimensione != dimensione:
                return
            impronte = self._impronte_di(lettore)
            if impronte is None:
                return
            for numero in list(cercati[dimensione]):
                informazioni = self.elenco.contenuto(numero)
                if informazioni is None or impronte != _impronte(informazioni):
                    continue
                copie = self._copie_di(numero)
                rimesso = self._ricomponi(numero, informazioni, copie)
                if rimesso is None:
                    gemello = self._nuovo_gemello(
                        numero, informazioni,
                        lambda scrittore: self._copia_byte(lettore, scrittore))
                    if gemello is None:
                        continue
                    rimesso = (self._ricomponi(numero, informazioni, copie)
                               or (False, gemello))
                self.rapporto.ritrovato(self._esito(numero, informazioni, "trovato",
                                                    None, *rimesso))
                cercati[dimensione].remove(numero)
        if not cercati[dimensione]:
            del cercati[dimensione]

    def _buchi_del_salvataggio(self, numero: str, informazioni: dict,
                               blocchi: int) -> int | None:
        try:
            with self._apri(self._blob(numero), True) as lettore:
                contenuto = formato.Contenuto(lettore, self._chiave,
                                              numero=bytes.fromhex(numero),
                                              testa=informazioni["testa"])
                buchi = buchi_di(contenuto.dati, blocchi)
        except (ErroreOfficina, OSError, ValueError):
            return None
        return None if buchi is None else len(buchi)

    def _salva_i_pezzi(self, numero: str) -> None:
        informazioni = self.elenco.contenuto(numero)
        if informazioni is None or _salvataggio(informazioni) or self._pieno:
            return
        self.avanzamento.numero = numero
        with ExitStack() as pila:
            pezzi, _ = self._pezzi(numero, informazioni, self._copie_di(numero), pila)
            blocchi = pezzi.forma.blocchi
            buchi, _, firme = self._leggi(pezzi)
            if not buchi or len(buchi) == blocchi:
                return
            for altro, dati in self._salvataggi(numero):
                quanti = self._buchi_del_salvataggio(altro, dati, blocchi)
                if quanti is not None and quanti <= len(buchi):
                    self.rapporto.salvati[numero] = altro
                    return
            nuovo = formato.nuovo_numero()
            dati = {"salvato_da": numero, "buchi": intervalli(buchi),
                    "fatti": self._fatti_per(numero, nuovo.hex()),
                    "scritto": self._adesso()}
            salvato = self._scrivi_nuovo(
                nuovo, informazioni, dati,
                lambda scrittore: self._scrivi_pezzi(pezzi, scrittore, firme),
                "incompleto", registro.SALVATO + numero)
        if salvato is not None:
            self.rapporto.salvati[numero] = salvato

    def _dati_di(self, blob: Path, numero: str) -> dict | None:
        try:
            with self._apri(blob, True) as lettore:
                return formato.Contenuto(lettore, self._chiave,
                                         numero=bytes.fromhex(numero)).dati
        except (ErroreOfficina, OSError, ValueError):
            return None

    def _una_nota(self, numero: str) -> dict | None:
        blob = self._blob(numero)
        controllo = self._controllo(blob, numero, None)
        if controllo is None or not controllo.buono:
            riparata = (controllo is not None and controllo.riparabile
                        and self._con_la_parita(blob, numero, None))
            if not riparata:
                riparata = any(self._dalla_copia(copia, blob, numero, None)
                               for copia in self._copie_di(numero))
            if not riparata:
                return None
            self.rapporto.note_riparate += 1
        return self._dati_di(blob, numero)

    def _note(self) -> None:
        rovinate: list[tuple[str, float]] = []
        riassunto: float | None = None
        for numero, quando in self.elenco.note_scritte():
            self._ferma_se_serve()
            self.avanzamento.numero = numero
            dati = self._una_nota(numero)
            self.rapporto.note += 1
            if dati is None:
                rovinate.append((numero, quando))
            elif dati.get("riassunto") is True:
                riassunto = quando if riassunto is None else max(riassunto, quando)
        self.avanzamento.numero = None
        self.rapporto.note_rovinate = [numero for numero, _ in rovinate]
        if any(riassunto is None or quando >= riassunto for _, quando in rovinate):
            self._rifai_note()

    def _rifai_note(self) -> None:
        if self._pieno:
            self.rapporto.problema("note_non_rifatte")
            return
        quando = self._adesso()
        fatti = self.elenco.fatti_completi()
        gruppo: list[dict] = []
        peso = 0
        scritte = 0
        prossimo = next(fatti, None)
        try:
            while prossimo is not None:
                fatto, prossimo = prossimo, next(fatti, None)
                gruppo.append(fatto)
                peso += len(json.dumps(fatto, ensure_ascii=False))
                if (prossimo is None or len(gruppo) >= FATTI_PER_NOTA
                        or peso >= PESO_PER_NOTA):
                    self.elenco.scrivi_nota(gruppo, quando,
                                            riassunto=prossimo is None)
                    scritte += 1
                    gruppo, peso = [], 0
        except OSError as guasto:
            if guasto.errno in PIENO:
                self._senza_spazio()
            self.rapporto.problema("note_non_rifatte")
            return
        except (ErroreOfficina, ValueError):
            self.rapporto.problema("note_non_rifatte")
            return
        finally:
            self.rapporto.note_rifatte = scritte


class ControlloMensile(Sottofondo):

    nome = "archivio-sicuro-controllo"

    def __init__(self, cartella: Path, elenco, chiave, *, sveglio=sveglia.sveglio,
                 rallenta=None, pausa_se_usi: float = PAUSA_SE_USI,
                 **per_controllore):
        super().__init__(sveglio=sveglio, rallenta=rallenta,
                         pausa_se_usi=pausa_se_usi)
        self.elenco = elenco
        self.controllore = Controllore(cartella, elenco, chiave,
                                       aspetta=self._aspetta, **per_controllore)

    def avvia(self, numeri=None) -> bool:
        return self._parti(None if numeri is None else list(numeri))

    def _azzera(self) -> None:
        self.controllore.rapporto = None
        self.controllore.avanzamento = Avanzamento()

    def _lavora(self, numeri) -> None:
        self.controllore.controlla(numeri)

    def _alla_fine(self, esito: str) -> None:
        self.elenco.salva()

    def istantanea(self) -> dict:
        rapporto = self.controllore.rapporto or Rapporto()
        avanzamento = self.controllore.avanzamento
        return {
            "stato": self.stato,
            "fase": avanzamento.fase,
            "numero": avanzamento.numero,
            "fatti": avanzamento.fatti,
            "totale": avanzamento.totale,
            "letti": avanzamento.letti,
            "controllati": rapporto.controllati,
            "byte": rapporto.byte,
            "come": dict(rapporto.come),
            "riparati": len(rapporto.riparati),
            "gemelli": len(rapporto.gemelli),
            "persi": list(rapporto.persi),
            "salvati": dict(rapporto.salvati),
            "rimandati": len(rapporto.rimandati),
            "note": rapporto.note,
            "note_riparate": rapporto.note_riparate,
            "note_rovinate": len(rapporto.note_rovinate),
            "note_rifatte": rapporto.note_rifatte,
            "problemi": list(rapporto.problemi),
            "allarme": rapporto.allarme,
            "verde": rapporto.verde,
            "finito": rapporto.finito,
            "frase": rapporto.frase(),
            "errore": self.errore,
            "codice": self.codice,
        }
