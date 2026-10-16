from __future__ import annotations

import threading

import pytest

from officina.programma import carta, ponti, sigillo
from prove.test_programma_finestre import _chiudi_davvero, _programma, casa  # noqa: F401
from prove.test_sigillo import FintoHello, FintoWindows

PAROLA = "una password lunga"


@pytest.fixture
def porte(casa, monkeypatch):  # noqa: F811
    hello, windows = FintoHello(), FintoWindows()
    monkeypatch.setattr(sigillo, "PortaHello", lambda: hello)
    monkeypatch.setattr(sigillo, "PortaWindows", lambda: windows)
    return hello, windows


def _forziere_acceso():
    from officina import forziere
    from officina.archivio import accesso
    from officina.impostazioni import REALE, posizione

    carta.comincia_da_zero()
    carta.aggiorna(obblighi_sospesi=True, chiave_chiesta=True)
    accesso.apri(REALE)
    accesso.chiudi(con_copia=False)
    forziere.per(posizione(REALE)).accendi(PAROLA)


def _aspetta_l_apertura():
    for filo in threading.enumerate():
        if filo.name == "apertura":
            filo.join(timeout=30)


def test_la_prima_volta_con_la_password_si_lega_a_windows_hello(porte):
    _forziere_acceso()
    programma, _ = _programma()
    programma.crea_la_finestrina()
    ponte = ponti.PonteFinestrina(programma)
    try:
        assert ponte.stato()["sigillo"] is None
        assert ponte.apri_il_forziere(PAROLA)["stato"]["passo"] == "apertura"
        _aspetta_l_apertura()
        assert sigillo.modo("reale") == sigillo.HELLO
    finally:
        _chiudi_davvero(programma)


def test_poi_si_apre_con_windows_hello_senza_scrivere_niente(porte):
    from officina import forziere
    from officina.impostazioni import REALE, posizione

    _forziere_acceso()
    sigillo.sigilla("reale", PAROLA)
    programma, _ = _programma()
    programma.crea_la_finestrina()
    ponte = ponti.PonteFinestrina(programma)
    try:
        assert ponte.stato()["sigillo"] == sigillo.HELLO
        assert ponte.apri_con_windows()["stato"]["passo"] == "apertura"
        _aspetta_l_apertura()
        assert forziere.per(posizione(REALE)).aperto
    finally:
        _chiudi_davvero(programma)


def test_se_annulli_windows_hello_resta_la_password_della_cassaforte(porte):
    hello, _ = porte
    _forziere_acceso()
    sigillo.sigilla("reale", PAROLA)
    hello.annulla = True
    programma, _ = _programma()
    programma.crea_la_finestrina()
    ponte = ponti.PonteFinestrina(programma)
    try:
        assert ponte.apri_con_windows()["errore"] == sigillo.ANNULLATO
        assert ponte.stato()["passo"] == "password"
    finally:
        _chiudi_davvero(programma)


def test_un_sigillo_rotto_si_rifa_con_la_password_della_cassaforte(porte):
    hello, _ = porte
    _forziere_acceso()
    sigillo.sigilla("reale", PAROLA)
    hello.chiavi.clear()
    programma, _ = _programma()
    programma.crea_la_finestrina()
    ponte = ponti.PonteFinestrina(programma)
    try:
        assert ponte.apri_con_windows()["errore"] == sigillo.HELLO_RIFATTO
        ponte.apri_il_forziere(PAROLA)
        _aspetta_l_apertura()
        assert sigillo.apri("reale") == PAROLA
    finally:
        _chiudi_davvero(programma)


def test_senza_hello_ne_windows_si_apre_lo_stesso_con_la_password(casa, monkeypatch):  # noqa: F811
    monkeypatch.setattr(sigillo, "PortaHello", lambda: FintoHello(c_e=False))
    monkeypatch.setattr(sigillo, "PortaWindows", lambda: FintoWindows(c_e=False))
    _forziere_acceso()
    programma, _ = _programma()
    programma.crea_la_finestrina()
    ponte = ponti.PonteFinestrina(programma)
    try:
        assert ponte.apri_il_forziere(PAROLA)["stato"]["passo"] == "apertura"
        _aspetta_l_apertura()
        assert not sigillo.c_e("reale")
    finally:
        _chiudi_davvero(programma)


def test_le_pagine_hanno_il_tasto_di_windows():
    from pathlib import Path

    from officina.programma import avvio

    radice = Path(avvio.__file__).parent.parent
    finestrina = (radice / "programma" / "pagine" / "finestrina.html").read_text(encoding="utf-8")
    blocco = (radice / "web" / "templates" / "blocco.html").read_text(encoding="utf-8")
    assert 'data-fai="apri_con_windows"' in finestrina
    assert "data-rientra-windows" in blocco
    assert hasattr(ponti.PontePrincipale, "rientra_con_windows")


def test_dopo_l_inattivita_si_rientra_con_windows(porte, monkeypatch):
    from types import SimpleNamespace

    from officina.archivio import accesso
    from officina.web import blocco

    sigillo.sigilla("reale", PAROLA)
    provate = []
    monkeypatch.setattr(accesso, "aperto", lambda: SimpleNamespace(dove="finto"))
    monkeypatch.setattr(blocco.guardia, "sblocca",
                        lambda chi, dove, parola: provate.append((chi, parola)) or True)
    programma, _ = _programma()
    assert ponti.PontePrincipale(programma).rientra_con_windows() == {"vai": "/"}
    assert provate == [("qui", PAROLA)]


def test_accendendo_la_cassaforte_windows_e_obbligatorio(porte):
    from officina import forziere
    from officina.archivio import accesso

    hello, _ = porte
    carta.comincia_da_zero()
    programma, _ = _programma()
    programma.accendi()
    ponte = ponti.PontePrincipale(programma)
    try:
        hello.annulla = True
        esito = ponte.accendi_il_forziere("lunga abbastanza", "lunga abbastanza", True)
        assert esito["errore"] == sigillo.ANNULLATO
        assert not forziere.per(accesso.aperto().dove).acceso
        hello.annulla = False
        ponte.accendi_il_forziere("lunga abbastanza", "lunga abbastanza", True)
        assert forziere.per(accesso.aperto().dove).acceso
        assert sigillo.apri("reale") == "lunga abbastanza"
        assert ponte.spegni_il_forziere("lunga abbastanza") == {"vai": "/impostazioni#c6"}
        assert not sigillo.c_e("reale")
    finally:
        _chiudi_davvero(programma)


def test_dopo_l_inattivita_un_sigillo_rotto_si_rifa_con_la_password(porte, monkeypatch):
    from types import SimpleNamespace

    from officina.archivio import accesso
    from officina.web import blocco

    hello, _ = porte
    sigillo.sigilla("reale", PAROLA)
    hello.chiavi.clear()
    monkeypatch.setattr(accesso, "aperto", lambda: SimpleNamespace(dove="finto"))
    monkeypatch.setattr(blocco.guardia, "sblocca", lambda chi, dove, parola: True)
    programma, _ = _programma()
    ponte = ponti.PontePrincipale(programma)
    assert ponte.rientra_con_windows()["errore"] == sigillo.HELLO_RIFATTO
    ponte.rientra(PAROLA)
    assert sigillo.apri("reale") == PAROLA


def test_senza_password_la_cassaforte_ne_crea_una_e_la_mostra_una_volta(porte):
    from fastapi.testclient import TestClient

    from officina import forziere
    from officina.archivio import accesso
    from officina.web.server import app

    carta.comincia_da_zero()
    programma, _ = _programma()
    programma.accendi()
    ponte = ponti.PontePrincipale(programma)
    try:
        esito = ponte.accendi_il_forziere("", "", True)
        assert esito["vai"].startswith("/forziere/creata?g=")
        assert forziere.per(accesso.aperto().dove).acceso
        creata = sigillo.apri("reale")
        assert len(creata) == 35
        cliente = TestClient(app, client=("127.0.0.1", 51000))
        pagina = cliente.get(esito["vai"], follow_redirects=False)
        assert creata in pagina.text
        assert pagina.headers["cache-control"] == "no-store"
        di_nuovo = cliente.get(esito["vai"], follow_redirects=False)
        assert di_nuovo.status_code == 303
        assert creata not in di_nuovo.text
    finally:
        _chiudi_davvero(programma)


def test_senza_password_e_senza_windows_bisogna_scriverla(casa, monkeypatch):  # noqa: F811
    from officina import forziere
    from officina.archivio import accesso

    monkeypatch.setattr(sigillo, "come_si_puo", lambda: None)
    carta.comincia_da_zero()
    programma, _ = _programma()
    programma.accendi()
    ponte = ponti.PontePrincipale(programma)
    try:
        esito = ponte.accendi_il_forziere("", "", True)
        assert "scrivi tu una password" in esito["errore"]
        assert not forziere.per(accesso.aperto().dove).acceso
    finally:
        _chiudi_davvero(programma)
