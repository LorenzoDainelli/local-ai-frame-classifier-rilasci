from __future__ import annotations

import json
import os
import random
import threading
import time
from contextlib import contextmanager
from pathlib import Path

import pytest

from officina.errori import ErroreOfficina
from officina.sicuro import custode as modulo
from officina.sicuro.chiavetta import (DA_ATTACCARE, DIVERSA, NON_STACCARLA,
                                       PUOI_STACCARLA, AggiornaChiavetta)
from officina.sicuro.copia import Fermato
from officina.sicuro.custode import (AGGIORNO, ASPETTO, CHIAVETTA, CONTROLLO, COPIA, COPIO,
                                     LAVORO, ORDINE, Custode)
from officina.sicuro.estrai import Estrazione
from officina.sicuro.lavoro import Lavoro
from officina.sicuro.sottofondo import (ERRORE, FERMATO, FINITO, IN_CORSO, IN_PAUSA,
                                        SPAZIO_FINITO, Sottofondo)
from officina.sicuro.via_libera import ControlloFresco
from prove.test_sicuro_chiavetta import LIBERO, TESTO, chiave, pezzi_piccoli
from prove.test_sicuro_copia import _dati
from prove.test_sicuro_via_libera import FOTO, Via

ATTESA = 20.0

assert chiave and pezzi_piccoli


@contextmanager
def _sveglio():
    yield True


def _finche(condizione, quanto=ATTESA):
    fine = time.monotonic() + quanto
    while time.monotonic() < fine:
        if condizione():
            return True
        time.sleep(0.002)
    return condizione()


class Contatore:

    def __init__(self):
        self.serratura = threading.Lock()
        self.dentro: list[str] = []
        self.massimo = 0
        self.storia: list[tuple[str, str]] = []

    def entra(self, nome: str) -> None:
        with self.serratura:
            self.dentro.append(nome)
            self.massimo = max(self.massimo, len(self.dentro))
            self.storia.append((nome, "entra"))

    def esce(self, nome: str) -> None:
        with self.serratura:
            self.dentro.remove(nome)
            self.storia.append((nome, "esce"))

    def entrati(self) -> list[str]:
        with self.serratura:
            return [nome for nome, cosa in self.storia if cosa == "entra"]


class Finto(Sottofondo):

    def __init__(self, nome: str, contatore: Contatore, sveglio=_sveglio):
        super().__init__(sveglio=sveglio)
        self.nome = nome
        self.contatore = contatore
        self.chiamate: list[tuple] = []
        self.libero = threading.Event()
        self.pieno = threading.Event()
        self.testardo = threading.Event()
        self.porta = threading.Event()
        self.guasto: BaseException | None = None
        self.rotto_ad_avviare: BaseException | None = None
        self.rifiuta = False

    def avvia(self, *argomenti) -> bool:
        if self.rotto_ad_avviare is not None:
            raise self.rotto_ad_avviare
        if self.rifiuta:
            return False
        return self._parti(*argomenti)

    def _lavora(self, *argomenti) -> None:
        self.contatore.entra(self.nome)
        try:
            self.chiamate.append(argomenti)
            if self.testardo.is_set():
                self.porta.wait(ATTESA)
                if self.libero.is_set():
                    return
            while not self.libero.is_set():
                self._aspetta()
                if self.pieno.is_set():
                    self._aspetta_che(lambda: not self.pieno.is_set(), 0.001)
                self._dormi_fermabile(0.001)
            if self.guasto is not None:
                raise self.guasto
        finally:
            self.contatore.esce(self.nome)

    def istantanea(self) -> dict:
        return {"stato": self.stato}


class Lento(Finto):

    def __init__(self, *argomenti, **opzioni):
        super().__init__(*argomenti, **opzioni)
        self.in_fondo = threading.Event()
        self.chiudi = threading.Event()

    def _alla_fine(self, esito: str) -> None:
        self.in_fondo.set()
        self.chiudi.wait(ATTESA)


class ElencoFinto:

    def __init__(self, radici=()):
        self.lista = [dict(radice) for radice in radici]
        self.guasto: BaseException | None = None
        self.chiesto = 0

    def radici(self) -> list[dict]:
        self.chiesto += 1
        if self.guasto is not None:
            raise self.guasto
        return [dict(radice) for radice in self.lista]


class ControlloreFinto:

    def __init__(self):
        self.lista: list[str] = []
        self.chiesto = 0
        self.guasto: BaseException | None = None

    def da_fare(self) -> list[str]:
        self.chiesto += 1
        if self.guasto is not None:
            raise self.guasto
        return list(self.lista)


class ChiavettaFinta:

    def __init__(self):
        self.attaccate: dict[Path, str] = {}

    def chi_e(self, radice) -> str | None:
        return self.attaccate.get(Path(radice))

    def mancanti(self) -> tuple[int, int]:
        return 0, 0

    def riassunto(self) -> dict:
        return {}


class Tempo:

    def __init__(self):
        self.ora = 1000.0

    def __call__(self) -> float:
        return self.ora


class Scena:

    def __init__(self, cartella: Path, radici=("r1",), **opzioni):
        self.cartella = cartella
        self.contatore = Contatore()
        self.copia = Finto("copia", self.contatore)
        self.copia.elenco = ElencoFinto(
            {"id": id, "percorso": str(cartella / id), "tolta": False} for id in radici)
        for id in radici:
            (cartella / id).mkdir(parents=True, exist_ok=True)
        self.chiavetta = Finto("chiavetta", self.contatore)
        self.chiavetta.chiavetta = ChiavettaFinta()
        self.controllo = Finto("controllo", self.contatore)
        self.controllo.controllore = ControlloreFinto()
        self.tempo = Tempo()
        self.disco = cartella / "E"
        opzioni.setdefault("orologio", self.tempo)
        opzioni.setdefault("dischi", lambda: list(self.chiavetta.chiavetta.attaccate))
        opzioni.setdefault("ogni", 0.01)
        self.custode = Custode(copia=self.copia, chiavetta=self.chiavetta,
                               controllo=self.controllo, **opzioni)
        self.guardiano = self.custode.guardiano

    def utente(self, nome: str = "utente", **opzioni) -> Finto:
        return Finto(nome, self.contatore, **opzioni)

    def attacca(self, chi: str = "nostra") -> None:
        self.chiavetta.chiavetta.attaccate[self.disco] = chi

    def stacca(self) -> None:
        self.chiavetta.chiavetta.attaccate.clear()

    def foto(self) -> dict:
        return self.custode.istantanea()

    def fine(self, *lavori) -> None:
        for lavoro in lavori:
            lavoro.libero.set()
            assert lavoro.aspetta_fine(ATTESA)


def _parte(lavoro: Finto, volte: int = 1) -> None:
    assert _finche(lambda: len(lavoro.chiamate) >= volte and lavoro.acceso)


def test_si_comincia_dalla_copia_e_poi_il_controllo(tmp_path):
    scena = Scena(tmp_path)
    scena.controllo.controllore.lista = ["n1"]
    custode = scena.custode
    assert custode.giro() is None
    custode.comincia()
    assert custode.giro() == COPIA
    _parte(scena.copia)
    assert scena.copia.chiamate == [(None, {})]
    assert scena.foto()["in_fila"] == [CONTROLLO]
    assert custode.giro() == COPIA
    assert not scena.controllo.chiamate
    scena.fine(scena.copia)
    assert custode.giro() == CONTROLLO
    _parte(scena.controllo)
    assert scena.controllo.chiamate == [(None,)]
    scena.fine(scena.controllo)
    assert custode.giro() is None
    assert scena.contatore.massimo == 1
    assert scena.contatore.entrati() == [COPIA, CONTROLLO]


def test_quello_che_conta_di_piu_ferma_quello_che_conta_di_meno(tmp_path):
    scena = Scena(tmp_path, radici=())
    scena.controllo.controllore.lista = ["n1"]
    custode = scena.custode
    custode.comincia()
    assert custode.giro() == CONTROLLO
    _parte(scena.controllo)
    custode.copia_ora({"r1": 5})
    assert custode.giro() == CONTROLLO
    assert scena.controllo.aspetta_fine(ATTESA)
    assert scena.controllo.stato == FERMATO
    assert scena.foto()["in_fila"] == [COPIA, CONTROLLO]
    assert custode.giro() == COPIA
    _parte(scena.copia)
    assert scena.copia.chiamate == [(None, {"r1": 5})]
    assert custode.giro() == COPIA
    scena.fine(scena.copia)
    assert custode.giro() == CONTROLLO
    _parte(scena.controllo, 2)
    assert scena.controllo.chiamate == [(None,), (None,)]
    scena.fine(scena.controllo)
    assert scena.contatore.massimo == 1


def test_la_chiavetta_viene_prima_della_copia(tmp_path):
    scena = Scena(tmp_path)
    custode = scena.custode
    custode.comincia()
    assert custode.giro() == COPIA
    _parte(scena.copia)
    assert scena.guardiano.giro() == DA_ATTACCARE
    scena.attacca()
    assert scena.guardiano.giro() == NON_STACCARLA
    assert scena.foto()["in_fila"] == [CHIAVETTA]
    assert custode.giro() == COPIA
    assert scena.copia.aspetta_fine(ATTESA)
    assert scena.guardiano.giro() == NON_STACCARLA
    assert custode.giro() == CHIAVETTA
    _parte(scena.chiavetta)
    assert scena.chiavetta.chiamate == [(scena.disco,)]
    assert scena.guardiano.giro() == NON_STACCARLA
    assert custode.giro() == CHIAVETTA
    scena.fine(scena.chiavetta)
    assert scena.guardiano.giro() == PUOI_STACCARLA
    assert custode.giro() == COPIA
    _parte(scena.copia, 2)
    assert scena.copia.chiamate == [(None, {}), (None, {})]
    assert scena.guardiano.giro() == PUOI_STACCARLA
    scena.fine(scena.copia)
    assert scena.contatore.massimo == 1


def test_la_tua_cosa_ferma_la_copia_e_poi_la_copia_riparte(tmp_path):
    scena = Scena(tmp_path)
    custode = scena.custode
    custode.comincia()
    assert custode.giro() == COPIA
    _parte(scena.copia)
    utente = scena.utente()
    assert custode.fai(utente, "a", 1)
    _parte(utente)
    assert utente.chiamate == [("a", 1)]
    assert scena.copia.stato == FERMATO and not scena.copia.acceso
    foto = scena.foto()
    assert foto["turno"] == "utente" and foto["fase"] == LAVORO
    assert foto["in_fila"] == [COPIA] and foto["acceso"] is None
    assert custode.giro() is None
    assert len(scena.copia.chiamate) == 1
    scena.fine(utente)
    assert utente.stato == FINITO
    foto = scena.foto()
    assert foto["turno"] is None and foto["fase"] is None
    assert custode.giro() == COPIA
    _parte(scena.copia, 2)
    assert scena.copia.chiamate == [(None, {}), (None, {})]
    scena.fine(scena.copia)
    assert scena.contatore.entrati() == [COPIA, "utente", COPIA]
    assert scena.contatore.massimo == 1


def test_una_cosa_alla_volta(tmp_path):
    scena = Scena(tmp_path)
    custode = scena.custode
    custode.comincia()
    utente = scena.utente()
    assert custode.fai(utente)
    _parte(utente)
    altro = scena.utente("altro")
    for prova in (lambda: custode.fai(altro), lambda: custode.fai(altro, chiavetta=True),
                  lambda: custode.via_libera(altro, [tmp_path])):
        with pytest.raises(ErroreOfficina) as preso:
            prova()
        assert preso.value.codice == "occupato"
        assert "aspetta che finisca" in preso.value.messaggio
    assert not altro.chiamate and altro.turno is None
    scena.fine(utente)
    assert custode.fai(altro, "b")
    _parte(altro)
    assert altro.chiamate == [("b",)]
    scena.fine(altro)
    assert scena.contatore.massimo == 1


def test_mentre_si_prepara_e_dopo_chiuso_non_si_fa_niente(tmp_path):
    scena = Scena(tmp_path)
    custode = scena.custode
    utente = scena.utente()
    with pytest.raises(ErroreOfficina) as preso:
        custode.fai(utente)
    assert preso.value.codice == "occupato"
    assert "si sta preparando" in preso.value.messaggio
    assert not scena.foto()["pronto"]
    custode.comincia()
    assert scena.foto()["pronto"]
    custode.ferma(ATTESA)
    with pytest.raises(ErroreOfficina) as preso:
        custode.fai(utente)
    assert preso.value.codice == "archivio_chiuso"
    assert not utente.chiamate
    assert scena.foto()["chiuso"]


def test_se_la_tua_cosa_non_parte_la_copia_non_si_ferma(tmp_path):
    scena = Scena(tmp_path)
    custode = scena.custode
    custode.comincia()
    assert custode.giro() == COPIA
    _parte(scena.copia)
    utente = scena.utente()
    utente.rotto_ad_avviare = ErroreOfficina("Scrivi CANCELLA.", codice="parola_sbagliata")
    with pytest.raises(ErroreOfficina) as preso:
        custode.fai(utente, chiavetta=True)
    assert preso.value.codice == "parola_sbagliata"
    assert utente.turno is None
    assert scena.copia.acceso and scena.copia.stato == IN_CORSO
    foto = scena.foto()
    assert foto["turno"] is None and foto["fase"] is None
    assert custode.giro() == COPIA
    utente.rotto_ad_avviare = None
    assert custode.fai(utente)
    _parte(utente)
    scena.fine(utente)


def test_se_la_tua_cosa_era_gia_accesa_non_riparte(tmp_path):
    scena = Scena(tmp_path)
    custode = scena.custode
    custode.comincia()
    utente = scena.utente()
    assert utente.avvia("da solo")
    _parte(utente)
    assert not custode.fai(utente, "di nuovo")
    assert utente.turno is None and scena.foto()["fase"] is None
    assert custode.giro() == COPIA
    scena.fine(utente, scena.copia)
    assert utente.chiamate == [("da solo",)]


def test_si_aspetta_che_la_copia_arrivi_a_un_punto_sicuro(tmp_path):
    scena = Scena(tmp_path)
    custode = scena.custode
    custode.comincia()
    scena.copia.testardo.set()
    assert custode.giro() == COPIA
    _parte(scena.copia)
    utente = scena.utente()
    assert custode.fai(utente)
    assert _finche(lambda: scena.foto()["fase"] == ASPETTO)
    time.sleep(0.05)
    assert not utente.chiamate and scena.copia.acceso
    assert scena.foto()["turno"] == "utente"
    scena.copia.porta.set()
    _parte(utente)
    assert scena.copia.stato == FERMATO
    scena.fine(utente)
    assert custode.giro() == COPIA
    _parte(scena.copia, 2)
    scena.fine(scena.copia)
    assert scena.contatore.massimo == 1


def test_se_annulli_mentre_aspetti_la_copia_riparte(tmp_path):
    scena = Scena(tmp_path)
    custode = scena.custode
    custode.comincia()
    scena.copia.testardo.set()
    assert custode.giro() == COPIA
    _parte(scena.copia)
    utente = scena.utente()
    assert custode.fai(utente)
    assert _finche(lambda: scena.foto()["fase"] == ASPETTO)
    utente.ferma(ATTESA)
    assert utente.stato == FERMATO and not utente.chiamate
    assert scena.foto()["turno"] is None and utente.turno is None
    assert custode.giro() == COPIA
    scena.copia.porta.set()
    assert scena.copia.aspetta_fine(ATTESA)
    assert custode.giro() == COPIA
    _parte(scena.copia, 2)
    scena.fine(scena.copia)


def test_se_finisce_da_sola_mentre_la_fermi_non_si_rifa(tmp_path):
    scena = Scena(tmp_path)
    custode = scena.custode
    custode.comincia()
    scena.copia.testardo.set()
    assert custode.giro() == COPIA
    _parte(scena.copia)
    utente = scena.utente()
    assert custode.fai(utente)
    assert _finche(lambda: scena.foto()["fase"] == ASPETTO)
    scena.copia.libero.set()
    scena.copia.porta.set()
    _parte(utente)
    assert scena.copia.stato == FINITO
    assert scena.foto()["in_fila"] == []
    scena.fine(utente)
    assert custode.giro() is None
    assert len(scena.copia.chiamate) == 1


def test_la_chiavetta_fermata_per_la_tua_cosa_riparte_e_non_si_stacca(tmp_path):
    scena = Scena(tmp_path, radici=())
    custode = scena.custode
    custode.comincia()
    scena.attacca()
    assert scena.guardiano.giro() == NON_STACCARLA
    assert custode.giro() == CHIAVETTA
    _parte(scena.chiavetta)
    utente = scena.utente()
    assert custode.fai(utente)
    _parte(utente)
    assert scena.chiavetta.stato == FERMATO
    assert scena.foto()["in_fila"] == [CHIAVETTA]
    for _ in range(3):
        assert scena.guardiano.giro() == NON_STACCARLA
    scena.fine(utente)
    assert scena.guardiano.giro() == NON_STACCARLA
    assert custode.giro() == CHIAVETTA
    _parte(scena.chiavetta, 2)
    assert scena.chiavetta.chiamate == [(scena.disco,), (scena.disco,)]
    assert scena.guardiano.giro() == NON_STACCARLA
    scena.fine(scena.chiavetta)
    assert scena.guardiano.giro() == PUOI_STACCARLA
    assert custode.giro() is None


def test_la_chiavetta_finita_mentre_la_fermi_dice_puoi_staccarla(tmp_path):
    scena = Scena(tmp_path, radici=())
    custode = scena.custode
    custode.comincia()
    scena.attacca()
    scena.chiavetta.testardo.set()
    assert scena.guardiano.giro() == NON_STACCARLA
    assert custode.giro() == CHIAVETTA
    _parte(scena.chiavetta)
    utente = scena.utente()
    assert custode.fai(utente)
    assert _finche(lambda: scena.foto()["fase"] == ASPETTO)
    scena.chiavetta.libero.set()
    scena.chiavetta.porta.set()
    _parte(utente)
    assert scena.chiavetta.stato == FINITO
    assert scena.guardiano.giro() == PUOI_STACCARLA
    scena.fine(utente)
    assert custode.giro() is None
    assert len(scena.chiavetta.chiamate) == 1


def test_la_chiavetta_finita_male_si_dice(tmp_path):
    scena = Scena(tmp_path, radici=())
    custode = scena.custode
    custode.comincia()
    scena.attacca()
    scena.chiavetta.guasto = ErroreOfficina("Piena.", codice="chiavetta_piena")
    assert scena.guardiano.giro() == NON_STACCARLA
    assert custode.giro() == CHIAVETTA
    scena.fine(scena.chiavetta)
    assert scena.guardiano.giro() == "problema"
    assert scena.guardiano.codice == "chiavetta_piena"
    assert custode.giro() is None


def test_con_la_chiavetta_in_uso_non_si_stacca(tmp_path):
    scena = Scena(tmp_path, radici=())
    custode = scena.custode
    custode.comincia()
    scena.attacca()
    scena.guardiano.giro()
    custode.giro()
    scena.fine(scena.chiavetta)
    assert scena.guardiano.giro() == PUOI_STACCARLA
    senza = scena.utente("senza")
    assert custode.fai(senza)
    _parte(senza)
    assert scena.guardiano.giro() == PUOI_STACCARLA
    scena.fine(senza)
    con = scena.utente("con")
    assert custode.fai(con, chiavetta=True)
    _parte(con)
    assert scena.guardiano.giro() == NON_STACCARLA
    scena.fine(con)
    assert scena.guardiano.giro() == PUOI_STACCARLA
    assert len(scena.chiavetta.chiamate) == 1
    assert custode.giro() is None


def test_la_copia_e_il_controllo_si_mettono_in_pausa(tmp_path):
    scena = Scena(tmp_path)
    scena.controllo.controllore.lista = ["n1"]
    custode = scena.custode
    custode.comincia()
    assert custode.giro() == COPIA
    _parte(scena.copia)
    custode.pausa(COPIA)
    assert scena.copia.aspetta_fine(ATTESA) and scena.copia.stato == FERMATO
    assert scena.foto()["in_pausa"] == [COPIA]
    assert scena.foto()["in_fila"] == [COPIA, CONTROLLO]
    assert custode.giro() == CONTROLLO
    _parte(scena.controllo)
    custode.pausa(CONTROLLO)
    assert scena.controllo.aspetta_fine(ATTESA)
    assert scena.foto()["in_pausa"] == [COPIA, CONTROLLO]
    assert custode.giro() is None
    custode.riprendi(CONTROLLO)
    assert custode.giro() == CONTROLLO
    _parte(scena.controllo, 2)
    custode.riprendi(COPIA)
    assert scena.foto()["in_pausa"] == []
    assert custode.giro() == CONTROLLO
    assert scena.controllo.aspetta_fine(ATTESA)
    assert custode.giro() == COPIA
    _parte(scena.copia, 2)
    scena.fine(scena.copia)
    assert custode.giro() == CONTROLLO
    _parte(scena.controllo, 3)
    scena.fine(scena.controllo)
    assert scena.contatore.massimo == 1


def test_in_pausa_non_parte_nemmeno_quando_e_ora(tmp_path):
    scena = Scena(tmp_path)
    custode = scena.custode
    custode.comincia()
    custode.pausa(COPIA)
    assert custode.giro() is None
    custode.copia_ora()
    assert custode.giro() is None
    assert not scena.copia.chiamate
    custode.riprendi(COPIA)
    assert custode.giro() == COPIA
    scena.fine(scena.copia)


def test_la_chiavetta_non_si_mette_in_pausa(tmp_path):
    scena = Scena(tmp_path)
    for nome in (CHIAVETTA, "altro"):
        with pytest.raises(ValueError):
            scena.custode.pausa(nome)
        with pytest.raises(ValueError):
            scena.custode.riprendi(nome)


def test_la_pausa_durante_la_tua_cosa_vale_dopo(tmp_path):
    scena = Scena(tmp_path)
    custode = scena.custode
    custode.comincia()
    assert custode.giro() == COPIA
    _parte(scena.copia)
    utente = scena.utente()
    assert custode.fai(utente)
    _parte(utente)
    custode.pausa(COPIA)
    scena.fine(utente)
    assert custode.giro() is None
    custode.riprendi(COPIA)
    assert custode.giro() == COPIA
    _parte(scena.copia, 2)
    scena.fine(scena.copia)


def test_la_copia_torna_da_sola_ogni_tanto(tmp_path):
    scena = Scena(tmp_path, ogni_copia=100.0)
    custode = scena.custode
    custode.comincia()
    scena.copia.libero.set()
    assert custode.giro() == COPIA
    assert scena.copia.aspetta_fine(ATTESA)
    assert custode.giro() is None
    scena.tempo.ora += 99.0
    assert custode.giro() is None
    scena.tempo.ora += 1.0
    assert custode.giro() == COPIA
    assert scena.copia.aspetta_fine(ATTESA)
    assert len(scena.copia.chiamate) == 2


def test_senza_cartelle_da_copiare_non_si_copia(tmp_path):
    scena = Scena(tmp_path, radici=(), ogni_copia=100.0)
    custode = scena.custode
    custode.comincia()
    assert custode.giro() is None
    scena.copia.elenco.lista = [{"id": "r1", "percorso": str(tmp_path / "r1"),
                                 "tolta": True}]
    scena.tempo.ora += 100.0
    assert custode.giro() is None
    scena.copia.elenco.lista[0]["tolta"] = False
    assert custode.giro() is None
    scena.tempo.ora += 100.0
    assert custode.giro() == COPIA
    scena.fine(scena.copia)


def test_il_controllo_si_guarda_una_volta_ogni_tanto(tmp_path):
    scena = Scena(tmp_path, radici=(), ogni_controllo=1000.0)
    custode = scena.custode
    controllore = scena.controllo.controllore
    custode.comincia()
    assert custode.giro() is None
    assert controllore.chiesto == 1
    controllore.lista = ["n1"]
    assert custode.giro() is None
    assert controllore.chiesto == 1
    scena.tempo.ora += 1000.0
    assert custode.giro() == CONTROLLO
    assert controllore.chiesto == 2
    assert custode.giro() == CONTROLLO
    scena.tempo.ora += 1000.0
    assert custode.giro() == CONTROLLO
    assert controllore.chiesto == 2
    scena.fine(scena.controllo)
    custode.controlla_ora()
    assert custode.giro() == CONTROLLO
    assert controllore.chiesto == 2
    _parte(scena.controllo, 2)
    assert custode.giro() == CONTROLLO
    scena.fine(scena.controllo)
    assert custode.giro() == CONTROLLO
    assert controllore.chiesto == 3
    _parte(scena.controllo, 3)
    scena.fine(scena.controllo)
    controllore.lista = []
    assert custode.giro() is None
    assert controllore.chiesto == 3


def test_senza_spazio_la_copia_lascia_passare_il_controllo(tmp_path):
    scena = Scena(tmp_path, ogni_copia=100.0)
    custode = scena.custode
    custode.comincia()
    scena.copia.pieno.set()
    assert custode.giro() == COPIA
    assert _finche(lambda: scena.copia.stato == SPAZIO_FINITO)
    assert custode.giro() == COPIA
    assert scena.copia.acceso and not scena.foto()["senza_spazio"]
    scena.controllo.controllore.lista = ["n1"]
    custode.controlla_ora()
    custode.copia_ora()
    assert custode.giro() == COPIA
    assert scena.copia.aspetta_fine(ATTESA) and scena.copia.stato == FERMATO
    foto = scena.foto()
    assert foto["senza_spazio"] and foto["in_fila"] == [CONTROLLO]
    assert custode.giro() == CONTROLLO
    _parte(scena.controllo)
    scena.tempo.ora += 99.0
    assert custode.giro() == CONTROLLO
    scena.tempo.ora += 1.0
    scena.copia.pieno.clear()
    assert custode.giro() == CONTROLLO
    assert scena.controllo.aspetta_fine(ATTESA)
    assert custode.giro() == COPIA
    assert not scena.foto()["senza_spazio"]
    _parte(scena.copia, 2)
    scena.fine(scena.copia)
    assert custode.giro() == CONTROLLO
    scena.fine(scena.controllo)
    assert scena.contatore.massimo == 1


def _con_le_radici(tmp_path) -> Scena:
    scena = Scena(tmp_path, radici=("r1", "r2"))
    (tmp_path / "r1" / "dentro").mkdir()
    scena.copia.elenco.lista.append({"id": "r3", "percorso": str(tmp_path / "r1" / "dentro"),
                                     "tolta": False})
    scena.copia.elenco.lista.append({"id": "r4", "percorso": str(tmp_path / "r2"),
                                     "tolta": True})
    return scena


@pytest.mark.parametrize("scelte, attese", [
    (["r1"], ["r1"]),
    (["r1/sotto"], ["r1"]),
    (["r1/dentro/x"], ["r1", "r3"]),
    (["r2/y", "r1/z"], ["r1", "r2"]),
    (["altrove"], []),
    (["r1\0"], []),
])
def test_il_via_libera_prima_copia_e_aggiorna_la_chiavetta(tmp_path, scelte, attese):
    scena = _con_le_radici(tmp_path)
    custode = scena.custode
    custode.comincia()
    scena.attacca()
    scena.copia.libero.set()
    scena.chiavetta.libero.set()
    fresco = scena.utente("fresco")
    percorsi = [str(tmp_path / scelta) for scelta in scelte]
    assert custode.via_libera(fresco, [Path(percorso) if "\0" not in percorso else percorso
                                       for percorso in percorsi])
    _parte(fresco)
    assert fresco.chiamate == [(percorsi,)]
    if attese:
        assert [radice["id"] for radice in scena.copia.chiamate[0][0]] == attese
        assert scena.copia.chiamate[0][1] == {}
        assert scena.contatore.entrati() == [COPIA, CHIAVETTA, "fresco"]
    else:
        assert scena.copia.chiamate == []
        assert scena.contatore.entrati() == [CHIAVETTA, "fresco"]
    assert scena.chiavetta.chiamate == [(scena.disco,)]
    assert scena.foto()["fase"] == LAVORO
    assert scena.guardiano.giro() == NON_STACCARLA
    scena.fine(fresco)
    assert scena.guardiano.giro() == PUOI_STACCARLA
    assert scena.foto()["in_fila"] == []
    assert custode.giro() == COPIA
    assert scena.copia.aspetta_fine(ATTESA)
    assert scena.copia.chiamate[-1] == (None, {})
    assert len(scena.chiavetta.chiamate) == 1
    assert scena.contatore.massimo == 1


@pytest.mark.parametrize("chi", [None, "diversa", "vecchia"])
def test_il_via_libera_senza_la_chiavetta_giusta_non_la_aggiorna(tmp_path, chi):
    scena = Scena(tmp_path)
    custode = scena.custode
    custode.comincia()
    if chi is not None:
        scena.attacca(chi)
    scena.copia.libero.set()
    fresco = scena.utente("fresco")
    assert custode.via_libera(fresco, [tmp_path / "r1"])
    _parte(fresco)
    assert scena.chiavetta.chiamate == []
    assert scena.contatore.entrati() == [COPIA, "fresco"]
    assert scena.guardiano.giro() == NON_STACCARLA
    scena.fine(fresco)
    assert scena.guardiano.giro() == (DA_ATTACCARE if chi is None else DIVERSA)


def test_il_via_libera_usa_l_aggiornamento_gia_in_fila(tmp_path):
    scena = Scena(tmp_path)
    custode = scena.custode
    custode.comincia()
    assert custode.giro() == COPIA
    _parte(scena.copia)
    scena.attacca()
    assert scena.guardiano.giro() == NON_STACCARLA
    assert custode.giro() == COPIA
    assert scena.copia.aspetta_fine(ATTESA)
    assert custode.giro() == CHIAVETTA
    _parte(scena.chiavetta)
    fresco = scena.utente("fresco")
    assert custode.via_libera(fresco, [tmp_path / "r1"])
    assert _finche(lambda: scena.foto()["fase"] == COPIO)
    assert scena.chiavetta.stato == FERMATO
    assert scena.guardiano.giro() == NON_STACCARLA
    scena.copia.libero.set()
    assert _finche(lambda: scena.foto()["fase"] == AGGIORNO)
    _parte(scena.chiavetta, 2)
    assert scena.guardiano.giro() == NON_STACCARLA
    scena.chiavetta.libero.set()
    _parte(fresco)
    assert scena.chiavetta.chiamate == [(scena.disco,), (scena.disco,)]
    assert scena.foto()["in_fila"] == [COPIA]
    assert scena.guardiano.giro() == NON_STACCARLA
    scena.fine(fresco)
    assert scena.guardiano.giro() == PUOI_STACCARLA
    assert custode.giro() == COPIA
    _parte(scena.copia, 3)
    assert scena.copia.chiamate[1][0][0]["id"] == "r1"
    assert scena.copia.chiamate[2] == (None, {})
    assert scena.guardiano.giro() == PUOI_STACCARLA
    assert len(scena.chiavetta.chiamate) == 2
    assert scena.contatore.massimo == 1


def test_il_via_libera_senza_spazio_per_la_copia_controlla_lo_stesso(tmp_path):
    scena = Scena(tmp_path)
    custode = scena.custode
    custode.comincia()
    scena.attacca()
    scena.copia.pieno.set()
    scena.chiavetta.libero.set()
    fresco = scena.utente("fresco")
    assert custode.via_libera(fresco, [tmp_path / "r1"])
    _parte(fresco)
    assert scena.copia.stato == FERMATO
    assert scena.foto()["senza_spazio"]
    assert scena.contatore.entrati() == [COPIA, CHIAVETTA, "fresco"]
    assert scena.foto()["in_fila"] == []
    scena.fine(fresco)


def test_il_via_libera_annullato_durante_la_copia(tmp_path):
    scena = Scena(tmp_path)
    custode = scena.custode
    custode.comincia()
    scena.attacca()
    fresco = scena.utente("fresco")
    assert custode.via_libera(fresco, [tmp_path / "r1"])
    _parte(scena.copia)
    assert scena.foto()["fase"] == COPIO and scena.foto()["acceso"] == COPIA
    fresco.ferma(ATTESA)
    assert fresco.stato == FERMATO and not fresco.chiamate
    assert scena.copia.aspetta_fine(ATTESA) and scena.copia.stato == FERMATO
    assert scena.chiavetta.chiamate == []
    assert scena.foto()["in_fila"] == [COPIA]
    assert scena.guardiano.giro() == NON_STACCARLA
    assert custode.giro() == CHIAVETTA
    scena.fine(scena.chiavetta)
    assert custode.giro() == COPIA
    _parte(scena.copia, 2)
    assert scena.copia.chiamate[-1] == (None, {})
    scena.fine(scena.copia)


def test_il_via_libera_annullato_durante_la_copia_con_la_copia_gia_in_fila(tmp_path):
    scena = Scena(tmp_path)
    custode = scena.custode
    custode.comincia()
    custode.copia_ora({"r1": 3})
    fresco = scena.utente("fresco")
    assert custode.via_libera(fresco, [tmp_path / "r1"])
    _parte(scena.copia)
    fresco.ferma(ATTESA)
    assert scena.copia.aspetta_fine(ATTESA)
    assert custode.giro() == COPIA
    _parte(scena.copia, 2)
    assert scena.copia.chiamate[-1] == (None, {"r1": 3})
    scena.fine(scena.copia)


def test_il_via_libera_annullato_durante_la_copia_finita_da_sola(tmp_path):
    scena = Scena(tmp_path)
    custode = scena.custode
    custode.comincia()
    scena.copia.testardo.set()
    fresco = scena.utente("fresco")
    assert custode.via_libera(fresco, [tmp_path / "r1"])
    _parte(scena.copia)
    fresco.ferma(ATTESA)
    assert fresco.stato == FERMATO
    assert scena.foto()["in_fila"] == [COPIA]
    scena.copia.libero.set()
    scena.copia.porta.set()
    assert scena.copia.aspetta_fine(ATTESA) and scena.copia.stato == FINITO
    assert custode.giro() is None
    assert scena.foto()["in_fila"] == []


def test_il_via_libera_annullato_durante_la_chiavetta(tmp_path):
    scena = Scena(tmp_path)
    custode = scena.custode
    custode.comincia()
    scena.attacca()
    scena.copia.libero.set()
    fresco = scena.utente("fresco")
    assert custode.via_libera(fresco, [tmp_path / "r1"])
    _parte(scena.chiavetta)
    assert scena.foto()["fase"] == AGGIORNO
    fresco.ferma(ATTESA)
    assert scena.chiavetta.aspetta_fine(ATTESA) and scena.chiavetta.stato == FERMATO
    assert scena.foto()["in_fila"] == [CHIAVETTA]
    for _ in range(3):
        assert scena.guardiano.giro() == NON_STACCARLA
    assert custode.giro() == CHIAVETTA
    _parte(scena.chiavetta, 2)
    scena.fine(scena.chiavetta)
    assert scena.guardiano.giro() == PUOI_STACCARLA


def test_il_via_libera_in_pausa_mette_in_pausa_anche_la_copia(tmp_path):
    scena = Scena(tmp_path)
    custode = scena.custode
    custode.comincia()
    fresco = scena.utente("fresco")
    assert custode.via_libera(fresco, [tmp_path / "r1"])
    _parte(scena.copia)
    fresco.pausa()
    assert _finche(lambda: scena.copia.stato == IN_PAUSA)
    fresco.riprendi()
    assert _finche(lambda: scena.copia.stato == IN_CORSO)
    scena.copia.libero.set()
    _parte(fresco)
    scena.fine(fresco)


def test_il_via_libera_senza_copia_e_senza_chiavetta(tmp_path):
    contatore = Contatore()
    custode = Custode(orologio=Tempo())
    custode.comincia()
    fresco = Finto("fresco", contatore)
    assert custode.via_libera(fresco, [tmp_path])
    _parte(fresco)
    fresco.libero.set()
    assert fresco.aspetta_fine(ATTESA)
    assert custode.giro() is None
    custode.copia_ora()
    custode.controlla_ora()
    assert custode.istantanea()["in_fila"] == []
    assert custode.guardiano is None


def test_il_via_libera_non_fa_mai_dire_puoi_staccarla(tmp_path):
    scena = Scena(tmp_path)
    custode = scena.custode
    guardiano = scena.guardiano
    custode.comincia()
    scena.attacca()
    scena.copia.libero.set()
    scena.chiavetta.libero.set()
    assert custode.giro() == COPIA
    assert scena.copia.aspetta_fine(ATTESA)
    assert guardiano.giro() == NON_STACCARLA
    assert custode.giro() == CHIAVETTA
    assert scena.chiavetta.aspetta_fine(ATTESA)
    assert guardiano.giro() == PUOI_STACCARLA
    visti: list[str] = []
    vero_giro = guardiano.giro
    vera_ricomincia = guardiano.ricomincia

    def giro():
        visti.append(vero_giro())
        visti.append(vero_giro())
        return visti[-1]

    def ricomincia():
        giro()
        vera_ricomincia()
        giro()

    guardiano.giro = giro
    guardiano.ricomincia = ricomincia
    fresco = scena.utente("fresco")
    assert custode.via_libera(fresco, [tmp_path / "r1"])
    _parte(fresco)
    giro()
    assert len(visti) == 8 and set(visti) == {NON_STACCARLA}
    assert len(scena.chiavetta.chiamate) == 2
    scena.fine(fresco)
    assert vero_giro() == PUOI_STACCARLA


@pytest.mark.parametrize("gia_in_fila", [False, True])
def test_se_la_chiavetta_non_parte_nel_via_libera_resta_in_fila(tmp_path, gia_in_fila):
    scena = Scena(tmp_path)
    custode = scena.custode
    custode.comincia()
    scena.attacca()
    scena.copia.libero.set()
    if gia_in_fila:
        assert scena.guardiano.giro() == NON_STACCARLA
        assert scena.foto()["in_fila"] == [CHIAVETTA]
    scena.chiavetta.rotto_ad_avviare = RuntimeError("non parte")
    fresco = scena.utente("fresco")
    assert custode.via_libera(fresco, [tmp_path / "r1"])
    assert fresco.aspetta_fine(ATTESA)
    assert fresco.stato == ERRORE and fresco.codice == "RuntimeError"
    assert fresco.chiamate == []
    assert scena.foto()["in_fila"] == [CHIAVETTA] and scena.foto()["turno"] is None
    for _ in range(3):
        assert scena.guardiano.giro() == NON_STACCARLA
    scena.chiavetta.rotto_ad_avviare = None
    scena.chiavetta.libero.set()
    assert custode.giro() == CHIAVETTA
    assert scena.chiavetta.aspetta_fine(ATTESA)
    assert scena.guardiano.giro() == PUOI_STACCARLA


@pytest.mark.parametrize("gia_in_fila", [False, True])
def test_se_la_chiavetta_dice_di_no_nel_via_libera_resta_in_fila(tmp_path, gia_in_fila):
    scena = Scena(tmp_path)
    custode = scena.custode
    custode.comincia()
    scena.attacca()
    scena.copia.libero.set()
    if gia_in_fila:
        assert scena.guardiano.giro() == NON_STACCARLA
    scena.chiavetta.rifiuta = True
    fresco = scena.utente("fresco")
    assert custode.via_libera(fresco, [tmp_path / "r1"])
    _parte(fresco)
    assert scena.chiavetta.chiamate == []
    assert scena.foto()["in_fila"] == [CHIAVETTA]
    scena.fine(fresco)
    assert scena.guardiano.giro() == NON_STACCARLA
    scena.chiavetta.rifiuta = False
    scena.chiavetta.libero.set()
    assert custode.giro() == CHIAVETTA
    assert scena.chiavetta.aspetta_fine(ATTESA)
    assert scena.guardiano.giro() == PUOI_STACCARLA


def test_se_la_copia_non_parte_nel_via_libera_l_archivio_non_si_blocca(tmp_path):
    scena = Scena(tmp_path)
    custode = scena.custode
    custode.comincia()
    scena.copia.rotto_ad_avviare = RuntimeError("non parte")
    fresco = scena.utente("fresco")
    assert custode.via_libera(fresco, [tmp_path / "r1"])
    assert fresco.aspetta_fine(ATTESA)
    assert fresco.stato == ERRORE and fresco.chiamate == []
    assert scena.foto()["turno"] is None and scena.foto()["fase"] is None
    scena.copia.rotto_ad_avviare = None
    scena.copia.libero.set()
    altro = scena.utente("altro")
    altro.libero.set()
    assert custode.via_libera(altro, [tmp_path / "r1"])
    assert altro.aspetta_fine(ATTESA) and altro.stato == FINITO
    assert len(scena.copia.chiamate) == 1


def test_se_chiudi_l_archivio_durante_il_via_libera_la_copia_non_parte(tmp_path):
    scena = Scena(tmp_path)
    custode = scena.custode
    custode.comincia()
    scena.attacca()
    vere_radici = custode._radici_di

    def radici_di(percorsi):
        custode.ferma()
        return vere_radici(percorsi)

    custode._radici_di = radici_di
    fresco = scena.utente("fresco")
    assert custode.via_libera(fresco, [tmp_path / "r1"])
    assert fresco.aspetta_fine(ATTESA)
    assert fresco.stato == FERMATO and fresco.chiamate == []
    assert scena.copia.chiamate == [] and scena.chiavetta.chiamate == []
    assert scena.foto()["chiuso"] and scena.foto()["in_fila"] == []
    assert custode.aspetta_fine(ATTESA)


def test_se_non_si_leggono_i_dischi_il_via_libera_controlla_lo_stesso(tmp_path):
    rotto = threading.Event()

    def dischi():
        if rotto.is_set():
            raise OSError("dischi")
        return list(scena.chiavetta.chiavetta.attaccate)

    scena = Scena(tmp_path, dischi=dischi)
    custode = scena.custode
    custode.comincia()
    scena.attacca()
    scena.copia.libero.set()
    rotto.set()
    fresco = scena.utente("fresco")
    assert custode.via_libera(fresco, [tmp_path / "r1"])
    _parte(fresco)
    assert scena.chiavetta.chiamate == []
    assert scena.guardiano.lavoro.acceso
    assert scena.guardiano.giro() == NON_STACCARLA
    rotto.clear()
    scena.fine(fresco)
    assert scena.guardiano.giro() == NON_STACCARLA
    assert custode.giro() == CHIAVETTA
    scena.fine(scena.chiavetta)
    assert scena.guardiano.giro() == PUOI_STACCARLA


def test_se_la_tua_cosa_muore_prima_del_turno_l_archivio_non_resta_bloccato(tmp_path):
    scena = Scena(tmp_path)
    custode = scena.custode
    custode.comincia()

    @contextmanager
    def rotto():
        raise RuntimeError("sveglio rotto")
        yield

    utente = scena.utente(sveglio=rotto)
    assert custode.fai(utente, chiavetta=True)
    assert utente.aspetta_fine(ATTESA)
    assert utente.stato == ERRORE and not utente.chiamate
    assert custode.giro() == COPIA
    assert utente.turno is None
    scena.attacca()
    scena.fine(scena.copia)
    assert scena.guardiano.giro() == NON_STACCARLA
    assert custode.giro() == CHIAVETTA
    scena.fine(scena.chiavetta)
    assert scena.guardiano.giro() == PUOI_STACCARLA
    altro = scena.utente("altro")
    assert custode.fai(altro)
    _parte(altro)
    scena.fine(altro)


def test_dopo_il_turno_la_tua_cosa_non_tocca_piu_il_custode(tmp_path):
    scena = Scena(tmp_path)
    custode = scena.custode
    custode.comincia()
    utente = scena.utente()
    assert custode.fai(utente)
    _parte(utente)
    assert utente.turno is not None
    scena.fine(utente)
    assert utente.turno is None
    assert custode.giro() == COPIA
    _parte(scena.copia)
    utente.libero.clear()
    assert utente.avvia("da solo")
    _parte(utente, 2)
    assert scena.copia.acceso and scena.copia.stato == IN_CORSO
    scena.fine(utente, scena.copia)


def test_un_lavoro_di_sottofondo_non_e_una_tua_cosa(tmp_path):
    scena = Scena(tmp_path)
    scena.custode.comincia()
    for lavoro in (scena.copia, scena.chiavetta, scena.controllo):
        with pytest.raises(ValueError):
            scena.custode.fai(lavoro)
    assert scena.foto()["turno"] is None


def test_prima_di_tutto_si_riprende_quello_lasciato_a_meta(tmp_path):
    visto = {}
    scena = None

    def prima():
        visto["pronto"] = scena.foto()["pronto"]
        visto["giro"] = scena.custode.giro()
        with pytest.raises(ErroreOfficina) as preso:
            scena.custode.fai(scena.utente())
        visto["codice"] = preso.value.codice
        visto["entrati"] = scena.contatore.entrati()

    scena = Scena(tmp_path, prima=prima)
    scena.custode.comincia()
    assert visto == {"pronto": False, "giro": None, "codice": "occupato", "entrati": []}
    scena.custode.comincia()
    assert scena.custode.giro() == COPIA
    scena.fine(scena.copia)


def test_se_la_ripresa_si_rompe_la_copia_aspetta_e_si_riprova(tmp_path):
    rotta = [True]
    chiamate = []

    def prima():
        chiamate.append(scena.contatore.entrati())
        if rotta[0]:
            raise ErroreOfficina("Quaderno rotto.", codice="quaderno_rovinato")

    scena = Scena(tmp_path, prima=prima)
    custode = scena.custode
    scena.controllo.controllore.lista = ["n1"]
    custode.comincia()
    custode.comincia()
    assert chiamate == [[]]
    assert scena.foto()["problema_iniziale"] == "quaderno_rovinato"
    assert scena.foto()["pronto"] and not scena.foto()["ripreso"]
    assert custode.giro() == CONTROLLO
    assert chiamate == [[], []]
    assert scena.foto()["in_fila"] == [COPIA]
    _parte(scena.controllo)
    assert custode.giro() == CONTROLLO
    custode.copia_ora()
    assert custode.giro() == CONTROLLO
    assert len(chiamate) == 2
    scena.fine(scena.controllo)
    custode.pausa(COPIA)
    assert custode.giro() is None
    assert len(chiamate) == 2
    custode.riprendi(COPIA)
    assert custode.giro() is None
    assert chiamate[-1] == [CONTROLLO] and len(chiamate) == 3
    assert scena.foto()["in_fila"] == [COPIA]
    rotta[0] = False
    assert custode.giro() == COPIA
    assert len(chiamate) == 4
    assert scena.foto()["problema_iniziale"] is None and scena.foto()["ripreso"]
    scena.fine(scena.copia)
    custode.copia_ora()
    assert custode.giro() == COPIA
    assert len(chiamate) == 4
    scena.fine(scena.copia)
    altra = Scena(tmp_path / "altra", prima=lambda: 1 / 0)
    altra.custode.comincia()
    assert altra.foto()["problema_iniziale"] == "ZeroDivisionError"


def test_mentre_si_riprova_la_ripresa_non_si_fa_altro(tmp_path):
    visto = []

    def prima():
        if not visto:
            visto.append("prima volta")
            raise OSError("disco")
        with pytest.raises(ErroreOfficina) as preso:
            scena.custode.fai(scena.utente())
        visto.append((preso.value.codice, preso.value.messaggio, scena.custode.giro(),
                      scena.contatore.entrati()))

    scena = Scena(tmp_path, prima=prima)
    custode = scena.custode
    custode.comincia()
    assert scena.foto()["problema_iniziale"] == "OSError"
    assert custode.giro() == COPIA
    assert visto == ["prima volta", (
        "occupato", "L'archivio si sta preparando: aspetta un attimo e riprova.", None, [])]
    scena.fine(scena.copia)
    utente = scena.utente()
    utente.libero.set()
    assert custode.fai(utente)
    assert utente.aspetta_fine(ATTESA)


@pytest.mark.parametrize("si_aggiusta", [False, True])
def test_il_via_libera_copia_solo_dopo_la_ripresa(tmp_path, si_aggiusta):
    volte = []

    def prima():
        volte.append(1)
        if len(volte) == 1 or not si_aggiusta:
            raise ErroreOfficina("Quaderno rotto.", codice="quaderno_rovinato")

    scena = Scena(tmp_path, prima=prima)
    custode = scena.custode
    custode.comincia()
    scena.attacca()
    scena.copia.libero.set()
    scena.chiavetta.libero.set()
    fresco = scena.utente("fresco")
    assert custode.via_libera(fresco, [tmp_path / "r1"])
    _parte(fresco)
    assert len(volte) == 2
    if si_aggiusta:
        assert scena.contatore.entrati() == [COPIA, CHIAVETTA, "fresco"]
        assert scena.foto()["problema_iniziale"] is None and scena.foto()["ripreso"]
    else:
        assert scena.copia.chiamate == []
        assert scena.contatore.entrati() == [CHIAVETTA, "fresco"]
        assert scena.foto()["problema_iniziale"] == "quaderno_rovinato"
    scena.fine(fresco)


def test_se_una_domanda_si_rompe_l_altro_lavoro_parte_lo_stesso(tmp_path):
    scena = Scena(tmp_path)
    custode = scena.custode
    controllore = scena.controllo.controllore
    custode.comincia()
    scena.copia.elenco.guasto = ErroreOfficina("Elenco rotto.", codice="elenco_rovinato")
    controllore.lista = ["n1"]
    assert custode.giro() == CONTROLLO
    assert scena.foto()["problema"] == "elenco_rovinato"
    assert custode.giro() == CONTROLLO
    scena.fine(scena.controllo)
    scena.copia.elenco.guasto = None
    assert custode.giro() == COPIA
    assert scena.foto()["problema"] is None
    scena.fine(scena.copia)
    scena.tempo.ora += modulo.OGNI_CONTROLLO
    controllore.guasto = OSError("note")
    chiesto = controllore.chiesto
    assert custode.giro() == COPIA
    assert scena.foto()["problema"] == "OSError"
    assert custode.giro() == COPIA
    assert controllore.chiesto == chiesto + 2
    controllore.guasto = None
    assert custode.giro() == COPIA
    assert scena.foto()["problema"] is None
    assert scena.foto()["in_fila"] == [CONTROLLO]
    scena.fine(scena.copia)
    assert custode.giro() == CONTROLLO
    scena.fine(scena.controllo)


def test_un_guasto_nel_giro_si_dice_e_poi_passa(tmp_path):
    scena = Scena(tmp_path)
    custode = scena.custode
    custode.comincia()
    scena.copia.elenco.guasto = ErroreOfficina("Elenco rotto.", codice="elenco_rovinato")
    assert custode.giro() is None
    assert scena.foto()["problema"] == "elenco_rovinato"
    scena.copia.elenco.guasto = None
    scena.copia.rotto_ad_avviare = RuntimeError("niente fili")
    assert custode.giro() is None
    assert scena.foto()["problema"] == "RuntimeError"
    assert scena.foto()["in_fila"] == [COPIA]
    scena.copia.rotto_ad_avviare = None
    assert custode.giro() == COPIA
    assert scena.foto()["problema"] is None
    scena.fine(scena.copia)


def test_chiudere_ferma_tutto_e_non_riparte_niente(tmp_path):
    scena = Scena(tmp_path, ogni_giro=0.005)
    custode = scena.custode
    scena.controllo.controllore.lista = ["n1"]
    assert custode.avvia()
    assert not custode.avvia()
    _parte(scena.copia)
    scena.attacca()
    assert _finche(lambda: scena.chiavetta.acceso)
    utente = scena.utente()
    assert custode.fai(utente, chiavetta=True)
    _parte(utente)
    assert custode.ferma(ATTESA)
    assert custode.aspetta_fine(ATTESA)
    assert not custode.guardiano.acceso
    for lavoro in (scena.copia, scena.chiavetta, scena.controllo, utente):
        assert not lavoro.acceso
    assert utente.stato == FERMATO
    custode.copia_ora()
    custode.controlla_ora()
    assert not custode.guardiano.lavoro.avvia(scena.disco)
    assert custode.giro() is None
    assert scena.foto()["in_fila"] == []
    assert not custode.avvia()
    assert scena.contatore.massimo == 1


def test_chiudere_senza_aspettare(tmp_path):
    scena = Scena(tmp_path)
    scena.custode.comincia()
    assert scena.custode.giro() == COPIA
    _parte(scena.copia)
    assert scena.custode.ferma() is False
    assert scena.custode.aspetta_fine(ATTESA)
    assert scena.copia.stato == FERMATO


def test_in_sottofondo_da_solo(tmp_path):
    scena = Scena(tmp_path, ogni_giro=0.005, ogni_copia=1000.0)
    custode = scena.custode
    scena.controllo.controllore.lista = ["n1"]
    assert custode.avvia()
    _parte(scena.copia)
    scena.copia.libero.set()
    _parte(scena.controllo)
    scena.attacca()
    assert _finche(lambda: scena.chiavetta.acceso)
    assert not scena.controllo.acceso
    assert scena.controllo.stato == FERMATO
    scena.chiavetta.libero.set()
    assert _finche(lambda: scena.custode.guardiano.istantanea()["stato"] == PUOI_STACCARLA)
    _parte(scena.controllo, 2)
    assert scena.controllo.stato == IN_CORSO
    scena.controllo.libero.set()
    assert custode.ferma(ATTESA)
    assert scena.contatore.massimo == 1


def test_la_foto_si_puo_mandare(tmp_path):
    scena = Scena(tmp_path)
    foto = scena.foto()
    assert foto == {"pronto": False, "ripreso": True, "chiuso": False, "turno": None,
                    "fase": None,
                    "acceso": None, "in_fila": [], "in_pausa": [], "senza_spazio": False,
                    "problema": None, "problema_iniziale": None}
    scena.custode.comincia()
    scena.custode.giro()
    json.dumps(scena.foto())
    assert scena.foto()["acceso"] == COPIA
    scena.fine(scena.copia)


def test_il_guardiano_lascia_stare_il_lavoro_finto(tmp_path):
    scena = Scena(tmp_path)
    in_fila = scena.guardiano.lavoro
    assert in_fila.chiavetta is scena.chiavetta.chiavetta
    assert in_fila.lavoro is scena.chiavetta
    scena.chiavetta.stato, scena.chiavetta.codice, scena.chiavetta.errore = "a", "b", "c"
    assert (in_fila.stato, in_fila.codice, in_fila.errore) == ("a", "b", "c")
    assert in_fila.istantanea() == {"stato": "a"}
    assert scena.guardiano.istantanea()["lavoro"] == {"stato": "a"}


def test_il_guardiano_ricomincia_da_capo(tmp_path):
    scena = Scena(tmp_path, radici=())
    custode = scena.custode
    custode.comincia()
    scena.attacca()
    scena.chiavetta.libero.set()
    assert scena.guardiano.giro() == NON_STACCARLA
    assert custode.giro() == CHIAVETTA
    assert scena.chiavetta.aspetta_fine(ATTESA)
    assert scena.guardiano.giro() == PUOI_STACCARLA
    assert scena.guardiano.giro() == PUOI_STACCARLA
    scena.guardiano.ricomincia()
    assert scena.guardiano.giro() == NON_STACCARLA
    assert custode.giro() == CHIAVETTA
    assert scena.chiavetta.aspetta_fine(ATTESA)
    assert scena.guardiano.giro() == PUOI_STACCARLA
    assert len(scena.chiavetta.chiamate) == 2


def test_seguire_un_altro_lavoro(tmp_path):
    contatore = Contatore()
    capo = Finto("capo", contatore)
    sotto = Finto("sotto", contatore)
    capo._cambio.acquire()
    capo._cambio.release()
    assert sotto.avvia()
    _parte(sotto)
    errori = []

    def segui():
        try:
            capo.segui(sotto)
        except BaseException as errore:
            errori.append(errore)

    filo = threading.Thread(target=segui)
    filo.start()
    capo.pausa()
    assert _finche(lambda: sotto.stato == IN_PAUSA)
    capo.riprendi()
    assert _finche(lambda: sotto.stato == IN_CORSO)
    capo.ferma()
    filo.join(ATTESA)
    assert len(errori) == 1 and isinstance(errori[0], Fermato)
    assert sotto.acceso
    capo._fermo = False
    assert capo.segui(sotto, basta=lambda: True) is None
    sotto.libero.set()
    capo.segui(sotto)
    assert not sotto.acceso


def test_senza_turno_si_lavora_come_prima(tmp_path):
    contatore = Contatore()
    lavoro = Finto("solo", contatore)
    assert lavoro.turno is None
    lavoro.libero.set()
    assert lavoro.avvia()
    assert lavoro.aspetta_fine(ATTESA)
    assert lavoro.stato == FINITO


def test_il_turno_avvolge_il_lavoro(tmp_path):
    contatore = Contatore()
    lavoro = Finto("solo", contatore)
    storia = []

    @contextmanager
    def turno():
        storia.append(("entra", list(contatore.dentro)))
        try:
            yield
        finally:
            storia.append(("esce", list(contatore.dentro)))

    lavoro.turno = turno
    lavoro.libero.set()
    assert lavoro.avvia()
    assert lavoro.aspetta_fine(ATTESA)
    assert storia == [("entra", []), ("esce", [])]
    assert lavoro.chiamate == [()]

    @contextmanager
    def fermo():
        raise Fermato
        yield

    lavoro.turno = fermo
    assert lavoro.avvia()
    assert lavoro.aspetta_fine(ATTESA)
    assert lavoro.stato == FERMATO and len(lavoro.chiamate) == 1


AZIONI = ("fai", "via_libera", "ferma_utente", "pausa", "riprendi", "copia_ora",
          "controlla_ora", "attacca", "stacca", "libera", "trattieni", "giro")


@pytest.mark.parametrize("seme", range(12))
def test_a_caso_mai_due_lavori_insieme(tmp_path, seme):
    caso = random.Random(seme)
    scena = Scena(tmp_path, ogni_giro=0.002, ogni_copia=0.0, ogni_controllo=0.0)
    custode = scena.custode
    scena.controllo.controllore.lista = ["n1"]
    utenti: list[Finto] = []
    assert custode.avvia()
    for passo in range(60):
        azione = caso.choice(AZIONI)
        if azione in ("fai", "via_libera"):
            utente = scena.utente(f"utente{passo}")
            if caso.random() < 0.5:
                utente.libero.set()
            try:
                if azione == "fai":
                    custode.fai(utente, chiavetta=caso.random() < 0.5)
                else:
                    custode.via_libera(utente, [tmp_path / "r1"])
            except ErroreOfficina as errore:
                assert errore.codice == "occupato"
            else:
                utenti.append(utente)
        elif azione == "ferma_utente" and utenti:
            caso.choice(utenti).ferma()
        elif azione == "pausa":
            custode.pausa(caso.choice((COPIA, CONTROLLO)))
        elif azione == "riprendi":
            custode.riprendi(caso.choice((COPIA, CONTROLLO)))
        elif azione == "copia_ora":
            custode.copia_ora()
        elif azione == "controlla_ora":
            custode.controlla_ora()
        elif azione == "attacca":
            scena.attacca()
        elif azione == "stacca":
            scena.stacca()
        elif azione == "libera":
            tutti = [scena.copia, scena.chiavetta, scena.controllo, *utenti]
            caso.choice(tutti).libero.set()
        elif azione == "trattieni":
            caso.choice([scena.copia, scena.chiavetta, scena.controllo]).libero.clear()
        else:
            custode.giro()
        time.sleep(caso.random() * 0.004)
        assert scena.contatore.massimo == 1, scena.contatore.storia
        foto = scena.foto()
        assert set(foto["in_fila"]) <= set(ORDINE)
    for lavoro in (scena.copia, scena.chiavetta, scena.controllo, *utenti):
        lavoro.libero.set()
    custode.riprendi(COPIA)
    custode.riprendi(CONTROLLO)
    assert _finche(lambda: not any(utente.acceso for utente in utenti))
    assert _finche(lambda: scena.foto()["turno"] is None)
    assert custode.ferma(ATTESA)
    assert scena.contatore.massimo == 1, scena.contatore.storia
    assert scena.contatore.dentro == []


def test_se_si_ferma_il_guardiano_la_chiavetta_in_fila_non_parte(tmp_path):
    scena = Scena(tmp_path, radici=())
    custode = scena.custode
    custode.comincia()
    scena.attacca()
    assert scena.guardiano.giro() == NON_STACCARLA
    assert scena.foto()["in_fila"] == [CHIAVETTA]
    scena.guardiano.ferma()
    assert scena.foto()["in_fila"] == []
    assert custode.giro() is None
    assert not scena.chiavetta.chiamate


def test_se_si_ferma_il_guardiano_la_chiavetta_accesa_si_ferma(tmp_path):
    scena = Scena(tmp_path, radici=())
    custode = scena.custode
    custode.comincia()
    scena.attacca()
    assert scena.guardiano.giro() == NON_STACCARLA
    assert custode.giro() == CHIAVETTA
    _parte(scena.chiavetta)
    scena.guardiano.ferma(ATTESA)
    assert not scena.chiavetta.acceso
    assert scena.chiavetta.stato == FERMATO
    assert custode.giro() is None
    assert len(scena.chiavetta.chiamate) == 1


def test_chiudere_durante_un_giro_non_aspetta_il_giro_dopo(tmp_path):
    scena = Scena(tmp_path, radici=(), ogni_giro=1000.0)
    custode = scena.custode
    vero = custode.giro

    def giro():
        esito = vero()
        custode.ferma()
        return esito

    custode.giro = giro
    assert custode.avvia()
    assert custode.aspetta_fine(ATTESA)


def test_chiudere_senza_aspettare_ferma_anche_il_guardiano(tmp_path):
    scena = Scena(tmp_path, radici=(), ogni_giro=1000.0)
    custode = scena.custode
    assert custode.avvia()
    assert _finche(lambda: custode.guardiano.acceso)
    assert custode.ferma() is False
    assert _finche(lambda: not custode.guardiano.acceso)
    assert custode.aspetta_fine(ATTESA)


def test_chiudere_dice_se_qualcosa_non_si_e_ancora_fermato(tmp_path):
    scena = Scena(tmp_path)
    custode = scena.custode
    custode.comincia()
    scena.copia.testardo.set()
    assert custode.giro() == COPIA
    _parte(scena.copia)
    assert custode.ferma(0.05) is False
    assert not custode.aspetta_fine(0.05)
    scena.copia.libero.set()
    scena.copia.porta.set()
    assert custode.aspetta_fine(ATTESA)


def test_dopo_chiuso_non_parte_niente_nemmeno_quando_e_ora(tmp_path):
    scena = Scena(tmp_path)
    scena.controllo.controllore.lista = ["n1"]
    custode = scena.custode
    custode.comincia()
    assert custode.ferma(ATTESA)
    scena.tempo.ora += 10 * modulo.OGNI_CONTROLLO
    assert custode.giro() is None
    assert scena.foto()["in_fila"] == []
    assert not scena.copia.chiamate
    assert not scena.controllo.chiamate
    assert scena.copia.elenco.chiesto == 0
    assert scena.controllo.controllore.chiesto == 0


def test_la_copia_chiesta_di_nuovo_non_si_perde_se_la_chiavetta_la_ferma(tmp_path):
    scena = Scena(tmp_path)
    custode = scena.custode
    custode.comincia()
    assert custode.giro() == COPIA
    _parte(scena.copia)
    custode.copia_ora({"r1": 5})
    scena.attacca()
    assert scena.guardiano.giro() == NON_STACCARLA
    assert custode.giro() == COPIA
    assert scena.copia.aspetta_fine(ATTESA)
    assert scena.foto()["in_fila"] == [CHIAVETTA, COPIA]
    assert custode.giro() == CHIAVETTA
    scena.fine(scena.chiavetta)
    assert custode.giro() == COPIA
    _parte(scena.copia, 2)
    assert scena.copia.chiamate == [(None, {}), (None, {"r1": 5})]
    scena.fine(scena.copia)
    assert scena.contatore.massimo == 1


def test_se_la_copia_dice_di_no_resta_in_fila(tmp_path):
    scena = Scena(tmp_path)
    custode = scena.custode
    custode.comincia()
    scena.copia.rifiuta = True
    custode.giro()
    assert scena.foto()["in_fila"] == [COPIA]
    assert not scena.copia.chiamate
    scena.copia.rifiuta = False
    assert custode.giro() == COPIA
    _parte(scena.copia)
    scena.fine(scena.copia)


def test_mentre_si_prepara_o_fai_la_tua_cosa_non_si_chiede_niente(tmp_path):
    scena = Scena(tmp_path)
    scena.controllo.controllore.lista = ["n1"]
    custode = scena.custode
    assert custode.giro() is None
    assert scena.copia.elenco.chiesto == 0
    assert scena.controllo.controllore.chiesto == 0
    custode.comincia()
    utente = scena.utente()
    assert custode.fai(utente)
    _parte(utente)
    assert custode.giro() is None
    assert scena.copia.elenco.chiesto == 0
    assert scena.controllo.controllore.chiesto == 0
    assert scena.foto()["in_fila"] == []
    scena.fine(utente)
    assert custode.giro() == COPIA
    assert scena.copia.elenco.chiesto == 1
    assert scena.controllo.controllore.chiesto == 1
    assert scena.foto()["in_fila"] == [CONTROLLO]
    scena.fine(scena.copia)


def test_con_la_copia_gia_in_fila_non_si_richiedono_le_cartelle(tmp_path):
    scena = Scena(tmp_path)
    custode = scena.custode
    custode.comincia()
    custode.pausa(COPIA)
    assert custode.giro() is None
    assert scena.foto()["in_fila"] == [COPIA]
    assert custode.giro() is None
    assert custode.giro() is None
    assert scena.copia.elenco.chiesto == 1
    custode.riprendi(COPIA)
    assert custode.giro() == COPIA
    assert scena.copia.elenco.chiesto == 1
    scena.fine(scena.copia)


def test_la_copia_lunga_non_si_mette_in_fila_due_volte(tmp_path):
    scena = Scena(tmp_path)
    custode = scena.custode
    custode.comincia()
    custode.copia_ora({"r1": 5})
    assert custode.giro() == COPIA
    _parte(scena.copia)
    scena.tempo.ora += 2 * modulo.OGNI_COPIA
    assert custode.giro() == COPIA
    assert scena.foto()["in_fila"] == []
    scena.attacca()
    assert scena.guardiano.giro() == NON_STACCARLA
    assert custode.giro() == COPIA
    assert scena.copia.aspetta_fine(ATTESA)
    assert custode.giro() == CHIAVETTA
    scena.fine(scena.chiavetta)
    assert custode.giro() == COPIA
    _parte(scena.copia, 2)
    assert scena.copia.chiamate == [(None, {"r1": 5}), (None, {"r1": 5})]
    scena.fine(scena.copia)


def test_senza_copia_da_fare_la_ripresa_non_si_riprova_di_continuo(tmp_path):
    chiamate = []

    def prima():
        chiamate.append(1)
        raise OSError("disco")

    scena = Scena(tmp_path, radici=(), prima=prima)
    custode = scena.custode
    custode.comincia()
    for _ in range(3):
        assert custode.giro() is None
    assert len(chiamate) == 1
    scena.copia.elenco.lista.append(
        {"id": "r1", "percorso": str(tmp_path / "r1"), "tolta": False})
    scena.tempo.ora += modulo.OGNI_COPIA
    assert custode.giro() is None
    assert len(chiamate) == 2
    assert scena.foto()["in_fila"] == [COPIA]


@pytest.mark.parametrize("cosa", ["tua_cosa", "chiudi"])
def test_se_succede_qualcosa_mentre_si_guardano_le_cartelle_la_copia_non_parte(tmp_path,
                                                                                cosa):
    scena = Scena(tmp_path)
    custode = scena.custode
    custode.comincia()
    utente = scena.utente()
    vero = scena.copia.elenco.radici

    def radici():
        if cosa == "chiudi":
            custode.ferma()
        else:
            assert custode.fai(utente)
        return vero()

    scena.copia.elenco.radici = radici
    assert custode.giro() is None
    assert not scena.copia.chiamate
    scena.copia.elenco.radici = vero
    if cosa == "chiudi":
        assert custode.aspetta_fine(ATTESA)
        assert scena.foto()["in_fila"] == []
        return
    _parte(utente)
    assert scena.foto()["in_fila"] == [COPIA]
    scena.fine(utente)
    assert custode.giro() == COPIA
    _parte(scena.copia)
    scena.fine(scena.copia)
    assert scena.contatore.massimo == 1


def test_senza_spazio_una_copia_chiesta_di_nuovo_non_ferma_quella_che_aspetta(tmp_path):
    scena = Scena(tmp_path)
    custode = scena.custode
    custode.comincia()
    scena.copia.pieno.set()
    assert custode.giro() == COPIA
    assert _finche(lambda: scena.copia.stato == SPAZIO_FINITO)
    custode.copia_ora({"r1": 5})
    assert custode.giro() == COPIA
    assert custode.giro() == COPIA
    foto = scena.foto()
    assert not foto["senza_spazio"] and foto["in_fila"] == [COPIA]
    assert scena.copia.acceso and scena.copia.stato == SPAZIO_FINITO
    scena.copia.pieno.clear()
    scena.fine(scena.copia)
    assert custode.giro() == COPIA
    _parte(scena.copia, 2)
    assert scena.copia.chiamate == [(None, {}), (None, {"r1": 5})]
    scena.fine(scena.copia)


def test_senza_spazio_la_copia_si_riprova_dopo_un_giro_intero_da_quando_si_ferma(tmp_path):
    scena = Scena(tmp_path, ogni_copia=100.0)
    custode = scena.custode
    custode.comincia()
    scena.copia.pieno.set()
    assert custode.giro() == COPIA
    assert _finche(lambda: scena.copia.stato == SPAZIO_FINITO)
    scena.tempo.ora += 90.0
    scena.controllo.controllore.lista = ["n1"]
    custode.controlla_ora()
    assert custode.giro() == COPIA
    assert scena.copia.aspetta_fine(ATTESA)
    assert custode.giro() == CONTROLLO
    scena.fine(scena.controllo)
    scena.tempo.ora += 20.0
    assert custode.giro() is None
    assert len(scena.copia.chiamate) == 1
    scena.tempo.ora += 80.0
    scena.copia.pieno.clear()
    assert custode.giro() == COPIA
    _parte(scena.copia, 2)
    scena.fine(scena.copia)


@pytest.mark.parametrize("nome", [COPIA, CONTROLLO])
def test_chiesto_di_nuovo_mentre_si_ferma_si_rifa_anche_se_finisce_da_solo(tmp_path, nome):
    scena = Scena(tmp_path, radici=())
    custode = scena.custode
    custode.comincia()
    lavoro = scena.copia if nome == COPIA else scena.controllo
    ora = custode.copia_ora if nome == COPIA else custode.controlla_ora
    ora()
    lavoro.testardo.set()
    assert custode.giro() == nome
    _parte(lavoro)
    utente = scena.utente()
    assert custode.fai(utente)
    assert _finche(lambda: scena.foto()["in_fila"] == [nome])
    ora()
    lavoro.libero.set()
    lavoro.porta.set()
    _parte(utente)
    assert lavoro.stato == FINITO
    assert scena.foto()["in_fila"] == [nome]
    scena.fine(utente)
    lavoro.testardo.clear()
    lavoro.libero.clear()
    assert custode.giro() == nome
    _parte(lavoro, 2)
    scena.fine(lavoro)
    assert scena.contatore.massimo == 1


def test_la_pausa_della_copia_non_ferma_la_copia_del_via_libera(tmp_path):
    scena = Scena(tmp_path)
    custode = scena.custode
    custode.comincia()
    fresco = scena.utente("fresco")
    assert custode.via_libera(fresco, [tmp_path / "r1"])
    _parte(scena.copia)
    custode.pausa(COPIA)
    time.sleep(0.05)
    assert scena.copia.acceso and scena.copia.stato == IN_CORSO
    assert scena.foto()["fase"] == COPIO
    scena.copia.libero.set()
    _parte(fresco)
    assert scena.copia.stato == FINITO
    assert scena.contatore.entrati() == [COPIA, "fresco"]
    scena.fine(fresco)
    assert custode.giro() is None
    assert scena.foto()["in_pausa"] == [COPIA]
    assert len(scena.copia.chiamate) == 1


def test_finche_la_tua_cosa_non_e_chiusa_del_tutto_non_parte_altro(tmp_path):
    scena = Scena(tmp_path)
    custode = scena.custode
    custode.comincia()
    primo = Lento("primo", scena.contatore)
    primo.libero.set()
    assert custode.fai(primo)
    assert primo.in_fondo.wait(ATTESA)
    assert primo.acceso and scena.foto()["fase"] is None
    with pytest.raises(ErroreOfficina) as preso:
        custode.fai(scena.utente())
    assert preso.value.codice == "occupato"
    assert custode.giro() is None
    assert not scena.copia.chiamate
    primo.chiudi.set()
    assert primo.aspetta_fine(ATTESA)
    assert custode.giro() == COPIA
    _parte(scena.copia)
    scena.fine(scena.copia)
    secondo = scena.utente("secondo")
    secondo.libero.set()
    assert custode.fai(secondo)
    assert secondo.aspetta_fine(ATTESA)
    assert scena.contatore.massimo == 1


def test_chiudere_durante_la_copia_del_via_libera_non_lascia_niente_in_fila(tmp_path):
    scena = Scena(tmp_path)
    custode = scena.custode
    custode.comincia()
    scena.copia.testardo.set()
    fresco = scena.utente("fresco")
    assert custode.via_libera(fresco, [tmp_path / "r1"])
    _parte(scena.copia)
    custode.ferma()
    assert fresco.aspetta_fine(ATTESA)
    assert scena.foto()["in_fila"] == []
    scena.copia.porta.set()
    assert custode.aspetta_fine(ATTESA)
    assert fresco.stato == FERMATO and scena.copia.stato == FERMATO
    assert not fresco.chiamate


def test_il_via_libera_aspetta_che_la_copia_senza_spazio_sia_chiusa_del_tutto(tmp_path):
    scena = Scena(tmp_path)
    custode = scena.custode
    custode.comincia()
    scena.attacca()
    scena.chiavetta.libero.set()
    scena.copia.pieno.set()
    in_fondo, chiudi = threading.Event(), threading.Event()

    def alla_fine(esito):
        in_fondo.set()
        chiudi.wait(ATTESA)

    scena.copia._alla_fine = alla_fine
    fresco = scena.utente("fresco")
    assert custode.via_libera(fresco, [tmp_path / "r1"])
    assert in_fondo.wait(ATTESA)
    time.sleep(0.05)
    assert not scena.chiavetta.chiamate
    assert scena.foto()["fase"] == COPIO
    chiudi.set()
    _parte(fresco)
    assert scena.contatore.entrati() == [COPIA, CHIAVETTA, "fresco"]
    assert scena.foto()["senza_spazio"]
    scena.fine(fresco)


def test_il_guardiano_ricomincia_anche_se_non_ha_ancora_visto_la_fine(tmp_path):
    scena = Scena(tmp_path, radici=())
    custode = scena.custode
    custode.comincia()
    scena.attacca()
    scena.chiavetta.libero.set()
    assert scena.guardiano.giro() == NON_STACCARLA
    assert custode.giro() == CHIAVETTA
    assert scena.chiavetta.aspetta_fine(ATTESA)
    scena.guardiano.ricomincia()
    assert scena.guardiano.giro() == NON_STACCARLA
    assert custode.giro() == CHIAVETTA
    assert scena.chiavetta.aspetta_fine(ATTESA)
    assert scena.guardiano.giro() == PUOI_STACCARLA
    assert len(scena.chiavetta.chiamate) == 2


def _contato(lavoro, nome: str, contatore: Contatore):
    vero = lavoro._lavora

    def lavora(*argomenti):
        contatore.entra(nome)
        try:
            vero(*argomenti)
        finally:
            contatore.esce(nome)

    lavoro._lavora = lavora
    return lavoro


class Vera:

    def __init__(self, cartella: Path, chiave):
        self.via = Via(cartella, chiave)
        self.chiave = chiave
        banco = self.via.banco
        orologio = self.via.prova.orologio
        self.radice = self.via.prova.radice
        self.contatore = Contatore()
        self.lento_dopo: int | None = None
        self.copia = _contato(Lavoro(banco.archivio, banco.elenco, chiave, sveglio=_sveglio,
                                     disco=lambda dove: (LIBERO, LIBERO), apri=banco.apri,
                                     rallenta=self._lenta, pausa_se_usi=ATTESA),
                              COPIA, self.contatore)
        self.chiavetta = _contato(AggiornaChiavetta(
            banco.archivio, banco.elenco, chiave, sveglio=_sveglio, apri=banco.apri,
            spazio=lambda radice: LIBERO, stesso_disco=lambda uno, altro: False,
            sistema=lambda radice: "exFAT", adesso=orologio, leggimi=TESTO),
            CHIAVETTA, self.contatore)
        self.custode = Custode(copia=self.copia, chiavetta=self.chiavetta, orologio=Tempo(),
                               dischi=lambda: [self.radice])
        self.custode.comincia()

    def _lenta(self) -> bool:
        return (self.lento_dopo is not None
                and self.copia.copiatore.avanzamento.copiati >= self.lento_dopo)

    def fresco(self) -> ControlloFresco:
        banco = self.via.banco
        return _contato(ControlloFresco(
            banco.archivio, banco.elenco, self.chiave, self.chiavetta.chiavetta,
            sveglio=_sveglio, apri=banco.apri, dischi=lambda: [self.radice],
            speciali=lambda: [], nuvole=lambda: [], adesso=self.via.prova.orologio),
            "fresco", self.contatore)

    def estrazione(self) -> Estrazione:
        banco = self.via.banco
        return _contato(Estrazione(banco.archivio, banco.elenco, self.chiave,
                                   sveglio=_sveglio, spazio=lambda dove: LIBERO,
                                   apri=banco.apri), "estrazione", self.contatore)


def _verdi(lavoro) -> list[bool]:
    return [esame["verde"] for esame in lavoro.istantanea()["esami"]]


def test_dal_vero_un_file_nuovo_e_verde_solo_col_via_libera(tmp_path, chiave):
    vera = Vera(tmp_path, chiave)
    via = vera.via
    via.banco.metti("s/sotto/nuovo.jpg", _dati(1000, 7))
    prima = via.esamina()
    assert not prima.verde and prima.rossi["manca"] == 1
    da_solo = vera.fresco()
    assert da_solo.avvia([via.qui("s")])
    assert da_solo.aspetta_fine(ATTESA)
    assert _verdi(da_solo) == [False]
    fresco = vera.fresco()
    assert vera.custode.via_libera(fresco, [via.qui("s")])
    assert fresco.aspetta_fine(ATTESA)
    assert fresco.stato == FINITO, fresco.istantanea()
    assert _verdi(fresco) == [True], fresco.istantanea()
    assert vera.contatore.entrati() == ["fresco", COPIA, CHIAVETTA, "fresco"]
    assert vera.copia.stato == FINITO and vera.chiavetta.stato == FINITO
    assert vera.custode.guardiano.giro() == PUOI_STACCARLA
    assert via.esamina().verde
    assert vera.contatore.massimo == 1


def test_dal_vero_senza_la_chiavetta_il_via_libera_resta_rosso(tmp_path, chiave):
    vera = Vera(tmp_path, chiave)
    via = vera.via
    via.banco.metti("s/sotto/nuovo.jpg", _dati(1000, 7))
    altrove = via.prova.stacca()
    fresco = vera.fresco()
    assert vera.custode.via_libera(fresco, [via.qui("s")])
    assert fresco.aspetta_fine(ATTESA)
    assert fresco.stato == ERRORE and fresco.codice == "chiavetta_da_attaccare"
    assert _verdi(fresco) == []
    assert vera.contatore.entrati() == [COPIA, "fresco"]
    assert vera.custode.guardiano.giro() == DA_ATTACCARE
    os.rename(altrove, vera.radice)
    assert vera.custode.guardiano.giro() == NON_STACCARLA
    assert vera.custode.giro() == CHIAVETTA
    assert vera.chiavetta.aspetta_fine(ATTESA)
    assert vera.custode.guardiano.giro() == PUOI_STACCARLA
    assert via.esamina().verde


def test_dal_vero_l_estrazione_aspetta_la_copia_e_la_copia_finisce_dopo(tmp_path, chiave):
    vera = Vera(tmp_path, chiave)
    via = vera.via
    nuovi = {f"s/nuovi/f{indice}.jpg": _dati(300 + indice, 40 + indice)
             for indice in range(12)}
    for nome, dati in nuovi.items():
        via.banco.metti(nome, dati)
    vera.lento_dopo = 3
    custode = vera.custode
    assert custode.giro() == COPIA
    assert _finche(lambda: vera.copia.copiatore.avanzamento.copiati >= 3)
    estrazione = vera.estrazione()
    fuori = tmp_path / "fuori"
    assert custode.fai(estrazione, [{"radice": "r1", "dove": fuori}])
    assert estrazione.aspetta_fine(ATTESA)
    assert estrazione.stato == FINITO, estrazione.istantanea()
    assert vera.copia.stato == FERMATO
    resoconto, = estrazione.resoconti
    assert resoconto.verde, resoconto
    estratti = {percorso.relative_to(resoconto.cartella).as_posix(): percorso.read_bytes()
                for percorso in Path(resoconto.cartella).rglob("*") if percorso.is_file()}
    assert set(FOTO) <= set(estratti)
    assert 3 <= len(set(estratti) & set(nuovi)) < len(nuovi)
    for nome, dati in estratti.items():
        assert dati == via.qui(nome).read_bytes()
    vera.lento_dopo = None
    assert custode.giro() == COPIA
    assert vera.copia.aspetta_fine(ATTESA) and vera.copia.stato == FINITO
    assert vera.contatore.entrati() == [COPIA, "estrazione", COPIA]
    assert vera.contatore.massimo == 1
    assert via.banco.provvisori() == []
    via.prova.chiavetta.aggiorna(vera.radice)
    assert via.esamina().verde


def test_i_tempi_di_partenza():
    assert modulo.OGNI_GIRO == 2.0
    assert modulo.OGNI_COPIA == 3600.0
    assert modulo.OGNI_CONTROLLO == 24 * 3600.0
    assert ORDINE == (CHIAVETTA, COPIA, CONTROLLO)
