from __future__ import annotations

import threading

import pytest

from officina.programma import avvio, carta, scheda
from officina.schermo import collega
from officina.schermo import porta as porta_mod
from prove.test_programma_finestre import WebviewFinto
from prove.test_schermo import _Password


@pytest.fixture
def fisso(tmp_path, monkeypatch, archivio_pieno):
    monkeypatch.setenv("OFFICINA_CASA_PROGRAMMA", str(tmp_path / "casa"))
    collega.segreti._in_memoria.clear()
    nuova = porta_mod.Porta()
    vecchia, porta_mod.porta = porta_mod.porta, nuova
    nuova.apri(_Password("cavallo-batteria"))
    yield nuova
    nuova.chiudi()
    porta_mod.porta = vecchia
    collega.segreti._in_memoria.clear()


def _programma():
    finto = WebviewFinto()
    return avvio.Programma(webview=finto, esamina=lambda: scheda.Esame()), finto


def _aspetta_la_principale(programma, finto):
    for filo in list(threading.enumerate()):
        if filo.name == "schermo":
            filo.join(timeout=30)
    return programma.principale


def test_il_portatile_sceglie_di_fare_da_schermo_e_si_collega(fisso):
    programma, finto = _programma()
    assert programma.passo() == "archivio"

    programma.scegli_lo_schermo()
    assert programma.passo() == "schermo-cerca"
    assert carta.cartella_dati() is None

    trovati = programma.cerca_il_fisso()["fissi"]
    assert trovati and trovati[0]["password"] is True

    codice, _ = fisso.mostra_il_codice()
    risposta = programma.abbina_il_fisso("127.0.0.1", fisso.porta_tcp, codice,
                                         "cavallo-batteria")
    assert risposta["stato"]["passo"] == "apertura"
    principale = _aspetta_la_principale(programma, finto)
    assert principale is not None
    assert principale.url == programma.ponte.indirizzo
    assert fisso.collegato() is not None
    assert programma.passo() == "schermo-entra"

    programma.spegni()
    assert programma.ponte is None
    assert fisso.collegato() is None


def test_le_volte_dopo_basta_la_password(fisso):
    programma, finto = _programma()
    programma.scegli_lo_schermo()
    codice, _ = fisso.mostra_il_codice()
    programma.abbina_il_fisso("127.0.0.1", fisso.porta_tcp, codice, "cavallo-batteria")
    _aspetta_la_principale(programma, finto)
    programma.ricollegati()
    assert programma.ponte is None
    assert fisso.collegato() is None
    assert programma.finestrina is not None

    dopo, finto_dopo = _programma()
    assert dopo.passo() == "schermo-entra"
    visto = dopo.com_e_il_fisso()
    assert visto["trovato"] and visto["password"] is True
    with pytest.raises(collega.NoDalFisso):
        dopo.entra_nel_fisso("sbagliata")
    dopo.entra_nel_fisso("cavallo-batteria")
    assert _aspetta_la_principale(dopo, finto_dopo) is not None
    dopo.spegni()


def test_chi_cambia_idea_torna_all_archivio_senza_perdere_l_abbinamento(fisso):
    programma, _ = _programma()
    programma.scegli_lo_schermo()
    codice, _ = fisso.mostra_il_codice()
    collega.abbina("127.0.0.1", fisso.porta_tcp, codice)
    programma.lascia_lo_schermo()
    assert programma.passo() == "archivio"
    programma.scegli_lo_schermo()
    assert programma.passo() == "schermo-entra"
    programma.riabbina()
    assert programma.passo() == "schermo-cerca"


def test_sul_portatile_dopo_la_prima_volta_basta_windows_hello(fisso, monkeypatch):
    from officina.programma import sigillo
    from prove.test_sigillo import FintoHello, FintoWindows

    hello = FintoHello()
    monkeypatch.setattr(sigillo, "PortaHello", lambda: hello)
    monkeypatch.setattr(sigillo, "PortaWindows", lambda: FintoWindows())
    programma, finto = _programma()
    programma.scegli_lo_schermo()
    codice, _ = fisso.mostra_il_codice()
    programma.abbina_il_fisso("127.0.0.1", fisso.porta_tcp, codice, "cavallo-batteria")
    _aspetta_la_principale(programma, finto)
    programma.ricollegati()
    assert sigillo.modo("fisso") == sigillo.HELLO

    dopo, finto_dopo = _programma()
    assert dopo.com_e_il_fisso()["sigillo"] == sigillo.HELLO
    firme = hello.firme
    dopo.entra_nel_fisso_con_windows()
    assert _aspetta_la_principale(dopo, finto_dopo) is not None
    assert hello.firme == firme + 1
    dopo.spegni()


def test_se_la_password_del_fisso_cambia_il_sigillo_vecchio_si_butta(fisso, monkeypatch):
    from officina.errori import ErroreOfficina
    from officina.programma import sigillo
    from prove.test_sigillo import FintoHello, FintoWindows

    hello = FintoHello()
    monkeypatch.setattr(sigillo, "PortaHello", lambda: hello)
    monkeypatch.setattr(sigillo, "PortaWindows", lambda: FintoWindows())
    programma, finto = _programma()
    programma.scegli_lo_schermo()
    codice, _ = fisso.mostra_il_codice()
    programma.abbina_il_fisso("127.0.0.1", fisso.porta_tcp, codice, "cavallo-batteria")
    _aspetta_la_principale(programma, finto)
    programma.ricollegati()
    fisso.chi_password = _Password("nuova-password-lunga")

    dopo, _ = _programma()
    with pytest.raises(ErroreOfficina):
        dopo.entra_nel_fisso_con_windows()
    assert not sigillo.c_e("fisso")
    dopo.spegni()
