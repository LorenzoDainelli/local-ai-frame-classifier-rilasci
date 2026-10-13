from __future__ import annotations

import threading
import time

import pytest
from fastapi.testclient import TestClient

from officina.web import blocco
from officina.web.strade import tentativi


class Orologio:

    def __init__(self):
        self.adesso = 1000.0

    def __call__(self) -> float:
        return self.adesso


def test_le_prime_cinque_prove_sbagliate_non_fanno_aspettare_poi_si_raddoppia():
    orologio = Orologio()
    freno = tentativi.FrenoDelleProve(orologio)
    attese = []
    for _ in range(12):
        giusta, attesa, occupato = freno.prova("qui", lambda: False)
        assert not giusta and not occupato
        attese.append(attesa)
        orologio.adesso += attesa
    assert attese == [0, 0, 0, 0, 1, 2, 4, 8, 16, 32, 60, 60]


def test_durante_l_attesa_la_password_non_viene_nemmeno_provata():
    orologio = Orologio()
    freno = tentativi.FrenoDelleProve(orologio)
    for _ in range(5):
        freno.prova("qui", lambda: False)
    chiamate = []
    giusta, attesa, occupato = freno.prova("qui", lambda: chiamate.append(1) or True)
    assert (giusta, attesa, occupato) == (False, 1, False)
    assert chiamate == []
    orologio.adesso += 1
    assert freno.prova("qui", lambda: chiamate.append(1) or True) == (True, 0, False)
    assert chiamate == [1]


def test_la_password_giusta_azzera_il_conto():
    orologio = Orologio()
    freno = tentativi.FrenoDelleProve(orologio)
    for _ in range(4):
        freno.prova("qui", lambda: False)
    assert freno.prova("qui", lambda: True) == (True, 0, False)
    for _ in range(4):
        assert freno.prova("qui", lambda: False)[1] == 0
    assert freno.prova("qui", lambda: False)[1] == 1


def test_chi_sbaglia_non_fa_aspettare_gli_altri_schermi():
    orologio = Orologio()
    freno = tentativi.FrenoDelleProve(orologio)
    for _ in range(6):
        freno.prova("192.168.1.40", lambda: False)
    assert freno.da_aspettare("192.168.1.40") > 0
    assert freno.da_aspettare("qui") == 0
    assert freno.prova("qui", lambda: True)[0] is True


def test_una_sola_password_alla_volta_anche_con_quaranta_richieste_insieme():
    freno = tentativi.FrenoDelleProve()
    dentro = 0
    al_massimo = 0
    lucchetto = threading.Lock()
    esiti = []

    def lenta() -> bool:
        nonlocal dentro, al_massimo
        with lucchetto:
            dentro += 1
            al_massimo = max(al_massimo, dentro)
        time.sleep(0.03)
        with lucchetto:
            dentro -= 1
        return False

    def prova():
        esiti.append(freno.prova("qui", lenta))

    fili = [threading.Thread(target=prova) for _ in range(40)]
    for filo in fili:
        filo.start()
    for filo in fili:
        filo.join()
    assert al_massimo == 1
    assert any(occupato for _, _, occupato in esiti)
    assert len(esiti) == 40


def test_un_errore_nel_controllo_non_blocca_il_freno_per_sempre():
    freno = tentativi.FrenoDelleProve()

    def rotta() -> bool:
        raise RuntimeError("archivio chiuso")

    with pytest.raises(RuntimeError):
        freno.prova("qui", rotta)
    assert freno.prova("qui", lambda: True) == (True, 0, False)


GIUSTA = "cavallo-verde-quaranta"


class _ForziereFinto:
    acceso = True
    aperto = False
    chiamate = 0

    def stato(self):
        return type("S", (), {"peso": 0})()

    def la_password_e_giusta(self, password):
        _ForziereFinto.chiamate += 1
        return password == GIUSTA


@pytest.fixture
def con_forziere(archivio_pieno, monkeypatch):
    from officina.web.strade import base

    orologio = Orologio()
    monkeypatch.setattr(tentativi.freno, "_orologio", orologio)
    tentativi.freno.dimentica_tutti()
    _ForziereFinto.chiamate = 0
    monkeypatch.setattr(base.forziere, "per", lambda dove: _ForziereFinto())
    blocco.guardia.dimentica_tutti()
    yield orologio
    tentativi.freno.dimentica_tutti()
    blocco.guardia.dimentica_tutti()


@pytest.fixture
def cliente(con_forziere):
    from officina.web.server import app

    return TestClient(app, client=("127.0.0.1", 51000))


def _riprova(cliente, password):
    return cliente.post("/blocco/apri", data={"password": password}, follow_redirects=False)


def test_dopo_cinque_password_sbagliate_il_blocco_fa_aspettare(cliente, con_forziere):
    blocco.guardia.blocca_adesso("qui")
    for _ in range(5):
        risposta = _riprova(cliente, "sbagliata-sbagliata")
        assert risposta.headers["location"] == "/blocco?sbagliata=1"
    assert _ForziereFinto.chiamate == 5

    risposta = _riprova(cliente, GIUSTA)
    assert risposta.headers["location"] == "/blocco?sbagliata=1"
    assert _ForziereFinto.chiamate == 5
    assert blocco.guardia.e_bloccato("qui")

    pagina = cliente.get("/blocco").text
    assert "Troppi tentativi sbagliati" in pagina
    assert "riprova fra un secondo" in pagina
    assert "Non è quella" not in pagina

    con_forziere.adesso += 1
    risposta = _riprova(cliente, GIUSTA)
    assert risposta.headers["location"] == "/"
    assert not blocco.guardia.e_bloccato("qui")


def test_l_attesa_cresce_e_si_dice_in_secondi(cliente, con_forziere):
    blocco.guardia.blocca_adesso("qui")
    for _ in range(5):
        _riprova(cliente, "sbagliata-sbagliata")
    con_forziere.adesso += 1
    _riprova(cliente, "sbagliata-sbagliata")
    assert "riprova fra 2 secondi" in cliente.get("/blocco").text
    con_forziere.adesso += 2
    _riprova(cliente, "sbagliata-sbagliata")
    assert "riprova fra 4 secondi" in cliente.get("/blocco").text


def test_la_password_giusta_prima_dei_cinque_errori_azzera(cliente, con_forziere):
    blocco.guardia.blocca_adesso("qui")
    for _ in range(4):
        _riprova(cliente, "sbagliata-sbagliata")
    assert _riprova(cliente, GIUSTA).headers["location"] == "/"
    blocco.guardia.blocca_adesso("qui")
    for _ in range(4):
        _riprova(cliente, "sbagliata-sbagliata")
    assert _ForziereFinto.chiamate == 9
    assert "Troppi tentativi" not in cliente.get("/blocco").text


def test_la_password_del_portatile_ha_lo_stesso_freno(con_forziere):
    from officina.schermo.porta import NoDallaPorta
    from officina.web.strade import schermo

    controllo = schermo._PasswordDelForziere()
    for _ in range(5):
        assert controllo.e_giusta("sbagliata-sbagliata") is False
    with pytest.raises(NoDallaPorta) as errore:
        controllo.e_giusta(GIUSTA)
    assert "Troppi tentativi sbagliati" in errore.value.messaggio
    assert _ForziereFinto.chiamate == 5
    con_forziere.adesso += 1
    assert controllo.e_giusta(GIUSTA) is True
