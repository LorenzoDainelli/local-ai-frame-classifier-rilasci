from __future__ import annotations

import os
import threading
import time
from pathlib import Path

from officina.errori import ErroreOfficina
from officina.sicuro import chiavi, leggimi
from officina.sicuro import elenco as registro
from officina.sicuro.cestino import (Mandata, Quaderno, Ricontrollo, Ronda, Spedizioniere,
                                     Vedetta, cestino_di_sistema)
from officina.sicuro.chiavetta import AggiornaChiavetta
from officina.sicuro.controllo import ControlloMensile
from officina.sicuro.custode import Custode
from officina.sicuro.dentro import Verifica, _resto, _uguali, _vero
from officina.sicuro.disco import fissa_cartella
from officina.sicuro.estrai import Estrazione
from officina.sicuro.lavoro import Lavoro, da_riprendere
from officina.sicuro.via_libera import ControlloFresco


ASPETTA_CHIUSURA = 30.0
CHIUSO = "L'Archivio sicuro è chiuso: aprilo e riprova."
AVANZI = frozenset({chiavi.FILE + ".nuovo", chiavi.RISERVA + ".nuovo"})
SOLO_LA_CHIAVE = frozenset({chiavi.FILE, chiavi.RISERVA, *AVANZI})


class _EstraiLaProva(Estrazione):

    nome = "archivio-sicuro-estrai-prova"

    def __init__(self, cartella: Path, elenco, chiave, spedizioniere: Spedizioniere,
                 **opzioni):
        super().__init__(cartella, elenco, chiave, **opzioni)
        self.spedizioniere = spedizioniere

    def _lavora(self, richieste: list[dict]) -> None:
        super()._lavora(richieste)
        if self.resoconti and not self.rifiutate:
            self.spedizioniere.segna_estratta(richieste[0], self.resoconti[0])


class _Aperto:

    def __init__(self, servizio: ArchivioSicuro, chiave):
        cartella = servizio.cartella
        salta = servizio.salta
        rallenta = servizio.rallenta
        opzioni = servizio.opzioni

        def per(nome: str, **base) -> dict:
            return {**base, **opzioni.get(nome, {})}

        self.chiave = chiave
        self.cartella = cartella
        self._registra = threading.RLock()
        self._elenco_chiuso = False
        self.elenco = registro.Elenco.apri(cartella, chiave)
        try:
            self.quaderno = Quaderno(cartella, chiave)
            self.copia = Lavoro(cartella, self.elenco, chiave,
                                **per("copia", rallenta=rallenta, salta=salta))
            self.chiavetta = AggiornaChiavetta(
                cartella, self.elenco, chiave,
                **per("chiavetta", programmino=servizio.programmino,
                      leggimi=leggimi.per_la_chiavetta()))
            self.controllo = ControlloMensile(
                cartella, self.elenco, chiave,
                **per("controllo", rallenta=rallenta, salta=salta,
                      copie=(self._dalla_chiavetta,)))
            self.ripara = ControlloMensile(
                cartella, self.elenco, chiave,
                **per("ripara", salta=salta, copie=(self._dalla_chiavetta,)))
            self.fresco = ControlloFresco(cartella, self.elenco, chiave,
                                          self.chiavetta.chiavetta,
                                          **per("fresco", salta=salta))
            self.estrazione = Estrazione(cartella, self.elenco, chiave, **per("estrai"))
            self.verifica = Verifica(cartella, self.elenco, chiave,
                                     **per("verifica", salta=salta))
            self.spedizioniere = Spedizioniere(
                cartella, self.elenco, chiave, self.chiavetta.chiavetta,
                servizio.cestino or cestino_di_sistema(), self.quaderno,
                **per("spedizioniere", salta=salta))
            self.prova = _EstraiLaProva(cartella, self.elenco, chiave, self.spedizioniere,
                                        **per("estrai"))
            self.mandata = Mandata(self.spedizioniere, **per("mandata"))
            self.ricontrollo = Ricontrollo(self.spedizioniere, **per("ricontrollo"))
            self.vedetta = Vedetta(self.elenco, self.spedizioniere.cestino, self.quaderno,
                                   **per("vedetta", salta=salta, avvisa=servizio.avvisa))
            self.ronda = Ronda(self.vedetta, **per("ronda", rallenta=rallenta))
            self.custode = Custode(copia=self.copia, chiavetta=self.chiavetta,
                                   controllo=self.controllo,
                                   prima=self.spedizioniere.riprendi, **per("custode"))
        except BaseException:
            self.chiudi_elenco()
            raise

    def _dalla_chiavetta(self, numero: str) -> Path | None:
        radice, _ = self.custode.guardiano.trova()
        if radice is None:
            return None
        return self.chiavetta.chiavetta.copia_di(radice)(numero)

    def tuoi(self) -> dict:
        return {"via_libera": self.fresco, "cestino": self.mandata,
                "ricontrollo": self.ricontrollo, "estrai": self.estrazione,
                "prova": self.prova, "verifica": self.verifica, "ripara": self.ripara}

    def avvia(self) -> None:
        self.custode.avvia()
        self.ronda.avvia()

    def ferma(self, aspetta: float) -> bool:
        fine = time.monotonic() + max(0.0, aspetta)
        self.custode.ferma()
        self.ronda.ferma()
        custode = self.custode.aspetta_fine(max(0.0, fine - time.monotonic()))
        ronda = self.ronda.aspetta_fine(max(0.0, fine - time.monotonic()))
        return custode and ronda

    @property
    def fermo(self) -> bool:
        return self.custode.aspetta_fine(0.0) and self.ronda.aspetta_fine(0.0)

    def salva(self) -> bool:
        with self._registra:
            if self._elenco_chiuso:
                return True
            try:
                self.elenco.salva()
            except (ErroreOfficina, OSError):
                return False
            return True

    def chiudi_elenco(self) -> bool:
        with self._registra:
            if self._elenco_chiuso:
                return True
            self._elenco_chiuso = True
            try:
                self.elenco.chiudi()
            except (ErroreOfficina, OSError):
                return False
            return True

    def _ancora_aperto(self) -> None:
        if self._elenco_chiuso:
            raise ErroreOfficina(CHIUSO, codice="archivio_chiuso")

    def registra(self, percorsi, prima: bool) -> list[dict]:
        with self._registra:
            self._ancora_aperto()
            radici = self.elenco.radici()
            if not radici and not prima:
                return []
            basi = [_vero(self.cartella), *(_vero(radice["percorso"]) for radice in radici
                                            if not radice["tolta"])]
            fatti = []
            for percorso in percorsi:
                try:
                    assoluto = os.path.abspath(os.fspath(percorso))
                    vero = _vero(assoluto)
                except (OSError, ValueError):
                    continue
                if any(_resto(base, vero) is not None for base in basi):
                    continue
                fatti.append(registro.fatto_radice(registro.nuova_chiave(), assoluto,
                                                   quando=time.time()))
                basi.append(vero)
            if not fatti:
                return []
            self.elenco.registra(fatti)
            self.elenco.salva()
            nuove = {fatto["id"] for fatto in fatti}
            return [radice for radice in self.elenco.radici() if radice["id"] in nuove]

    def aggiungi(self, percorso) -> dict:
        with self._registra:
            self._ancora_aperto()
            if not self.elenco.radici():
                raise ErroreOfficina(
                    "L'archivio è ancora vuoto: prima premi «Copia tutto».",
                    codice="prima_copia_tutto")
            return self.verifica.verificatore.aggiungi(percorso)

    def esami_di(self, cartelle) -> list:
        if self.fresco.acceso:
            raise ErroreOfficina("Il controllo delle cartelle non è ancora finito: aspetta "
                                 "che finisca.", codice="occupato")
        esami = list(self.fresco.esaminatore.esami)
        scelti: list = []
        for cartella in cartelle:
            vero = _vero(cartella)
            esame = next((esame for esame in esami if _uguali(esame.vero, vero)), None)
            if esame is None:
                raise ErroreOfficina(
                    "Per questa cartella non c'è un controllo appena fatto: premi di nuovo "
                    "«Controlla» e poi riprova. Non ho mandato niente nel Cestino.",
                    codice="da_ricontrollare")
            if not any(esame is gia for gia in scelti):
                scelti.append(esame)
        if not scelti:
            raise ErroreOfficina("Scegli almeno una cartella.", codice="niente_scelto")
        return scelti

    def istantanea(self) -> dict:
        return {
            "custode": self.custode.istantanea(),
            "chiavetta": self.custode.guardiano.istantanea(),
            "copia": self.copia.istantanea(),
            "controllo": self.controllo.istantanea(),
            "ronda": self.ronda.istantanea(),
            "tuoi": {nome: lavoro.istantanea() for nome, lavoro in self.tuoi().items()},
            "collaudo": self.quaderno.collaudo,
            "problemi_elenco": list(self.elenco.problemi),
            "problemi_quaderno": list(self.quaderno.problemi),
        }


class ArchivioSicuro:

    def __init__(self, cartella: Path, *, salta=(), cestino=None, programmino=None,
                 avvisa=None, rallenta=None, opzioni: dict | None = None):
        self.cartella = Path(cartella)
        self.salta = (*(os.fspath(cartella) for cartella in salta),
                      os.fspath(self.cartella))
        self.cestino = cestino
        self.programmino = programmino
        self.avvisa = avvisa
        self.rallenta = rallenta
        self.opzioni = dict(opzioni or {})
        self._serratura = threading.RLock()
        self._aperto: _Aperto | None = None
        self._chiusura: _Aperto | None = None
        self.problemi: list[str] = []

    @property
    def esiste(self) -> bool:
        return chiavi.esiste(self.cartella)

    @property
    def aperto(self) -> bool:
        return self._aperto is not None

    @property
    def ha_qualcosa(self) -> bool:
        return self._c_e_qualcosa()

    @property
    def si_chiude(self) -> bool:
        chiusura = self._chiusura
        return chiusura is not None and not chiusura.fermo

    def _di_ora(self) -> _Aperto:
        aperto = self._aperto
        if aperto is None:
            raise ErroreOfficina(CHIUSO, codice="archivio_chiuso")
        return aperto

    def _puo_aprire(self) -> None:
        chiusura = self._chiusura
        if chiusura is None:
            return
        if not chiusura.fermo:
            raise ErroreOfficina(
                "L'Archivio sicuro si sta ancora chiudendo: aspetta un attimo e riprova.",
                codice="si_chiude")
        chiusura.chiudi_elenco()
        self._chiusura = None

    def _c_e_qualcosa(self) -> bool:
        try:
            with os.scandir(self.cartella) as voci:
                return any(not self._avanzo(voce) for voce in voci)
        except FileNotFoundError:
            return False

    @staticmethod
    def _avanzo(voce: os.DirEntry) -> bool:
        if voce.name not in AVANZI or not voce.is_file(follow_symlinks=False):
            return False
        try:
            return chiavi._leggi_uno(Path(voce.path)) is None
        except ErroreOfficina:
            return False

    def _finisci_la_creazione(self) -> None:
        contenuti = self.cartella / registro.CONTENUTI
        if os.path.lexists(contenuti):
            return
        with os.scandir(self.cartella) as voci:
            nomi = {voce.name for voce in voci}
        if nomi <= SOLO_LA_CHIAVE:
            contenuti.mkdir()
            fissa_cartella(self.cartella)

    def crea(self, password: str, costo: int | None = None) -> None:
        with self._serratura:
            if self._aperto is not None or chiavi.esiste(self.cartella):
                raise ErroreOfficina("L'Archivio sicuro c'è già.", codice="chiave_esiste")
            self._puo_aprire()
            chiavi.password_nuova_valida(password)
            if self._c_e_qualcosa():
                raise ErroreOfficina(
                    "Nella cartella dell'Archivio sicuro c'è già qualcosa, ma manca il "
                    "file con la chiave: non ci creo sopra un archivio nuovo. Attacca la "
                    "chiavetta dell'archivio, che ha una copia della chiave.",
                    codice="cartella_non_vuota")
            chiave = chiavi.crea(self.cartella, password, costo)
            self._accendi(chiave, password, False)

    def apri(self, password: str, *, pulisci: bool = True) -> None:
        with self._serratura:
            aperto = self._aperto
            if aperto is not None:
                chiave = chiavi.apri(self.cartella, password)
                if chiave.nome != aperto.chiave.nome:
                    raise chiavi.ChiaveRovinata("Questa chiave non è quella dell'archivio.")
                return
            self._puo_aprire()
            chiave = chiavi.apri(self.cartella, password)
            self._accendi(chiave, password, pulisci)

    def _accendi(self, chiave, password: str, pulisci: bool) -> None:
        self.problemi = []
        if pulisci:
            try:
                if chiavi.porte(self.cartella) > 1:
                    chiavi.tieni_solo(self.cartella, chiave, password)
            except ErroreOfficina as errore:
                mescolata = errore.codice == "chiave_mescolata"
                self.problemi.append("chiave_mescolata" if mescolata
                                     else "password_vecchia_ancora_buona")
            except OSError:
                self.problemi.append("password_vecchia_ancora_buona")
        self._finisci_la_creazione()
        aperto = _Aperto(self, chiave)
        try:
            aperto.avvia()
        except BaseException:
            if aperto.ferma(ASPETTA_CHIUSURA):
                aperto.chiudi_elenco()
            else:
                self._chiusura = aperto
            raise
        self._aperto = aperto

    def chiudi(self, aspetta: float = ASPETTA_CHIUSURA) -> bool:
        with self._serratura:
            aperto, self._aperto = self._aperto, None
            if aperto is None:
                aperto, self._chiusura = self._chiusura, None
                if aperto is None:
                    return True
            if aperto.ferma(aspetta):
                if not aperto.chiudi_elenco():
                    self.problemi.append("elenco_non_salvato")
                return True
            self._chiusura = aperto
            if not aperto.salva():
                self.problemi.append("elenco_non_salvato")
            return False

    def aggiungi_password(self, nuova: str) -> None:
        with self._serratura:
            chiavi.aggiungi_password(self.cartella, self._di_ora().chiave, nuova)

    def tieni_solo(self, password: str) -> None:
        with self._serratura:
            aperto = self._di_ora()
            chiavi.tieni_solo(self.cartella, aperto.chiave, password)
        aperto.custode.guardiano.ricomincia()

    def copia_tutto(self, percorsi, grandezze: dict[str, int] | None = None) -> list[dict]:
        aperto = self._di_ora()
        nuove = aperto.registra(percorsi, prima=True)
        aperto.custode.copia_ora(grandezze)
        return nuove

    def metti_le_cartelle(self, percorsi) -> list[dict]:
        aperto = self._di_ora()
        nuove = aperto.registra(percorsi, prima=False)
        if nuove:
            aperto.custode.copia_ora()
        return nuove

    def aggiungi(self, percorso) -> dict:
        aperto = self._di_ora()
        esito = aperto.aggiungi(percorso)
        if esito["nuova"]:
            aperto.custode.copia_ora()
        return esito

    def via_libera(self, percorsi) -> bool:
        aperto = self._di_ora()
        return aperto.custode.via_libera(aperto.fresco, percorsi)

    def manda_nel_cestino(self, cartelle, parola: str) -> bool:
        aperto = self._di_ora()
        esami = aperto.esami_di(cartelle)
        return aperto.custode.fai(aperto.mandata, esami, parola, chiavetta=True)

    def ricontrolla(self, ids=None) -> bool:
        aperto = self._di_ora()
        return aperto.custode.fai(aperto.ricontrollo,
                                  None if ids is None else list(ids), chiavetta=True)

    def estrai(self, richieste) -> bool:
        aperto = self._di_ora()
        return aperto.custode.fai(aperto.estrazione,
                                  [dict(richiesta) for richiesta in richieste])

    def estrai_la_prova(self, dove) -> bool:
        aperto = self._di_ora()
        richiesta = aperto.spedizioniere.prova_da_estrarre(dove)
        return aperto.custode.fai(aperto.prova, [richiesta])

    def ho_controllato(self) -> None:
        self._di_ora().spedizioniere.ho_controllato()

    def verifica(self, percorso) -> bool:
        aperto = self._di_ora()
        return aperto.custode.fai(aperto.verifica, percorso)

    def ripara(self, numeri) -> bool:
        aperto = self._di_ora()
        numeri = list(dict.fromkeys(numeri))
        aperto.chiavetta.chiavetta.rileggi_presto(numeri)
        return aperto.custode.fai(aperto.ripara, numeri, chiavetta=True)

    def ho_capito(self, id: str) -> bool:
        return self._di_ora().vedetta.ho_capito(id)

    def annulla(self) -> None:
        for lavoro in self._di_ora().tuoi().values():
            if lavoro.acceso:
                lavoro.ferma()

    def pausa(self, nome: str) -> None:
        self._di_ora().custode.pausa(nome)

    def riprendi(self, nome: str) -> None:
        self._di_ora().custode.riprendi(nome)

    def controlla_ora(self) -> None:
        self._di_ora().custode.controlla_ora()

    def tuoi_accesi(self) -> list[str]:
        aperto = self._aperto
        if aperto is None:
            return []
        return [nome for nome, lavoro in aperto.tuoi().items() if lavoro.acceso]

    def copia_voluta(self) -> bool | None:
        aperto = self._aperto
        if aperto is None:
            return None
        return aperto.custode.copia_voluta()

    def da_finire(self) -> set[str] | None:
        aperto = self._aperto
        if aperto is None:
            return None
        with aperto._registra:
            if aperto._elenco_chiuso:
                return None
            return {radice["id"] for radice in da_riprendere(aperto.elenco)}

    def istantanea(self) -> dict:
        aperto = self._aperto
        fuori = {"esiste": self.esiste, "aperto": aperto is not None,
                 "si_chiude": self.si_chiude, "problemi": list(self.problemi)}
        if aperto is None:
            return fuori
        return fuori | aperto.istantanea()


_attuale: ArchivioSicuro | None = None


def attuale() -> ArchivioSicuro | None:
    return _attuale


def imposta(archivio: ArchivioSicuro | None) -> None:
    global _attuale
    _attuale = archivio


__all__ = ["ASPETTA_CHIUSURA", "ArchivioSicuro", "attuale", "imposta"]
