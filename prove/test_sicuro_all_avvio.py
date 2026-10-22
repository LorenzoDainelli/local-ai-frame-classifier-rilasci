from __future__ import annotations

import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from officina import forziere
from officina.archivio import accesso
from officina.errori import ErroreOfficina, PasswordSbagliata
from officina.impostazioni import REALE, posizione
from officina.programma import archivio_sicuro, carta, ponti, sigillo
from officina.programma.archivio_sicuro import (APERTO, ASSENTE, PASSWORD_DIVERSA, SI_APRE,
                                                Collegamento)
from officina.sicuro import chiavi
from officina.sicuro import servizio as modulo
from officina.web import blocco
from officina.web.strade import impostazioni, tentativi
from prove import test_programma_finestre as finestre
from prove import test_sicurezza_strade_password as strade_password
from prove import test_sicuro_nel_programma as nel_programma
from prove import test_sicuro_servizio as servizio_di_prova
from prove import test_sigillo_all_avvio as all_avvio
from prove.test_sicuro_servizio import ATTESA

casa = finestre.casa
porte = all_avvio.porte
con_forziere = strade_password.con_forziere
cliente = strade_password.cliente
costo_leggero = servizio_di_prova.costo_leggero
forziere_leggero = nel_programma.forziere_leggero
_aspetta = nel_programma._aspetta
_codice = nel_programma._codice

PAROLA = all_avvio.PAROLA
NUOVA = "quattro parole nuove davvero"
DEL_FORZIERE = "la password del forziere"
DI_PRIMA = "una password di prima"
SCRITTA_IL = archivio_sicuro.SCRITTA_IL


@pytest.fixture
def fabbrica(casa):
    return nel_programma._leggero(casa)[1]


@pytest.fixture
def guardia_pulita():
    tentativi.freno.dimentica_tutti()
    blocco.guardia.dimentica_tutti()
    yield
    tentativi.freno.dimentica_tutti()
    blocco.guardia.dimentica_tutti()


def _mai(password: str) -> None:
    raise AssertionError("il forziere era già acceso")


def _con_l_archivio(fabbrica) -> None:
    all_avvio._forziere_acceso()
    collegamento = Collegamento(posizione(REALE), fabbrica=fabbrica)
    collegamento.crea(PAROLA, PAROLA, True, accendi_il_forziere=_mai)
    assert collegamento.chiudi(ATTESA)


def _senza_password_scritta(quando=None) -> None:
    carta.aggiorna(**{SCRITTA_IL: quando})


def _programma(fabbrica):
    programma, _ = finestre._programma()
    programma.sicuro = Collegamento(posizione(REALE), fabbrica=fabbrica)
    return programma


def _con_la_finestrina(fabbrica):
    programma = _programma(fabbrica)
    programma.crea_la_finestrina()
    return programma, ponti.PonteFinestrina(programma)


def _scritta_adesso() -> bool:
    scritta = carta.leggi().get(SCRITTA_IL)
    return isinstance(scritta, float) and abs(time.time() - scritta) < 60


def _si_apre_con(parola: str) -> bool:
    try:
        chiavi.apri(archivio_sicuro.cartella(posizione(REALE)), parola, ripara=False)
    except PasswordSbagliata:
        return False
    return True


def _tutto_chiuso(programma) -> None:
    assert programma.sicuro._servizio is None or not programma.sicuro._servizio.aperto
    assert not programma.sicuro._apre()
    assert modulo.attuale() is None


@pytest.mark.parametrize("quanto_fa", [None, "ieri", archivio_sicuro.MESE + 5])
def test_con_l_archivio_windows_hello_aspetta_la_password_del_mese(casa, porte, fabbrica,
                                                                    quanto_fa):
    _con_l_archivio(fabbrica)
    sigillo.sigilla(REALE, PAROLA)
    _senza_password_scritta(time.time() - quanto_fa if isinstance(quanto_fa, int)
                            else quanto_fa)
    programma, ponte = _con_la_finestrina(fabbrica)
    try:
        stato = ponte.stato()
        assert stato["password_del_mese"] is True and stato["sigillo"] is None
        assert ponte.apri_con_windows()["errore"] == archivio_sicuro.OGGI_NIENTE_HELLO
        assert ponte.stato()["passo"] == "password"
        assert sigillo.c_e(REALE)
        assert ponte.apri_il_forziere(PAROLA)["stato"]["passo"] == "apertura"
        all_avvio._aspetta_l_apertura()
        assert _scritta_adesso()
        assert not archivio_sicuro.serve_la_password_scritta(posizione(REALE))
        assert _aspetta(programma.sicuro) == APERTO
        assert sigillo.apri(REALE) == PAROLA
    finally:
        finestre._chiudi_davvero(programma)
    _tutto_chiuso(programma)


def test_dopo_la_password_del_mese_windows_hello_apre_anche_l_archivio(casa, porte,
                                                                       fabbrica):
    _con_l_archivio(fabbrica)
    sigillo.sigilla(REALE, PAROLA)
    scritta = carta.leggi()[SCRITTA_IL]
    programma, ponte = _con_la_finestrina(fabbrica)
    try:
        stato = ponte.stato()
        assert stato["password_del_mese"] is False and stato["sigillo"] == sigillo.HELLO
        assert ponte.apri_con_windows()["stato"]["passo"] == "apertura"
        all_avvio._aspetta_l_apertura()
        assert _aspetta(programma.sicuro) == APERTO
        assert carta.leggi()[SCRITTA_IL] == scritta
    finally:
        finestre._chiudi_davvero(programma)
    _tutto_chiuso(programma)


def test_senza_archivio_windows_hello_va_come_prima(casa, porte, fabbrica):
    all_avvio._forziere_acceso()
    sigillo.sigilla(REALE, PAROLA)
    programma, ponte = _con_la_finestrina(fabbrica)
    try:
        stato = ponte.stato()
        assert stato["password_del_mese"] is False and stato["sigillo"] == sigillo.HELLO
        assert ponte.apri_con_windows()["stato"]["passo"] == "apertura"
        all_avvio._aspetta_l_apertura()
        assert forziere.per(posizione(REALE)).aperto
        assert _aspetta(programma.sicuro) == ASSENTE
        assert SCRITTA_IL not in carta.leggi()
    finally:
        finestre._chiudi_davvero(programma)


def test_un_sigillo_vecchio_non_si_cancella_e_si_rifa_con_la_password(casa, porte, fabbrica):
    all_avvio._forziere_acceso()
    sigillo.sigilla(REALE, DI_PRIMA)
    programma, ponte = _con_la_finestrina(fabbrica)
    try:
        assert ponte.apri_con_windows()["errore"] == sigillo.ROTTO
        assert sigillo.c_e(REALE) and sigillo.apri(REALE) == DI_PRIMA
        assert ponte.stato()["passo"] == "password"
        assert ponte.apri_il_forziere(PAROLA)["stato"]["passo"] == "apertura"
        all_avvio._aspetta_l_apertura()
        assert sigillo.apri(REALE) == PAROLA
    finally:
        finestre._chiudi_davvero(programma)


def test_la_finestrina_dice_se_un_cambio_e_rimasto_a_meta(casa, porte, fabbrica):
    _con_l_archivio(fabbrica)
    carta.aggiorna(**{archivio_sicuro.CAMBIO: archivio_sicuro.VALE_LA_NUOVA})
    programma, ponte = _con_la_finestrina(fabbrica)
    try:
        assert ponte.stato()["cambio_lasciato"] == archivio_sicuro.VALE_LA_NUOVA
        ponte.apri_il_forziere(PAROLA)
        all_avvio._aspetta_l_apertura()
        assert archivio_sicuro.cambio_lasciato() is None
    finally:
        finestre._chiudi_davvero(programma)


def test_se_la_password_del_forziere_non_apre_l_archivio_si_riallinea_a_mano(casa, porte,
                                                                            fabbrica):
    _con_l_archivio(fabbrica)
    cassa = forziere.per(posizione(REALE))
    cassa.apri(PAROLA)
    cassa.chiudi(DEL_FORZIERE)
    programma, ponte = _con_la_finestrina(fabbrica)
    try:
        ponte.apri_il_forziere(DEL_FORZIERE)
        all_avvio._aspetta_l_apertura()
        assert _aspetta(programma.sicuro) == PASSWORD_DIVERSA
        with pytest.raises(PasswordSbagliata):
            programma.apri_l_archivio_sicuro(NUOVA)
        assert programma.sicuro.guarda() == PASSWORD_DIVERSA
        assert programma.riprova_l_archivio_sicuro() == {"stato": SI_APRE}
        assert _aspetta(programma.sicuro) == PASSWORD_DIVERSA
        assert programma.apri_l_archivio_sicuro(PAROLA) == {"aperto": True, "problemi": []}
        assert programma.sicuro.guarda() == APERTO
        assert _si_apre_con(DEL_FORZIERE) and not _si_apre_con(PAROLA)
    finally:
        finestre._chiudi_davvero(programma)
    _tutto_chiuso(programma)


def test_con_l_archivio_il_forziere_non_si_spegne(casa, fabbrica):
    _con_l_archivio(fabbrica)
    accesso.apri(REALE, PAROLA)
    programma = _programma(fabbrica)
    try:
        assert _codice(lambda: programma.spegni_il_forziere(PAROLA)) == "forziere_serve"
        assert _codice(lambda: programma.spegni_il_forziere("")) == "forziere_serve"
        assert forziere.per(posizione(REALE)).acceso
    finally:
        finestre._chiudi_davvero(programma)
    assert forziere.per(posizione(REALE)).la_password_e_giusta(PAROLA)


def test_senza_lavori_non_si_chiede_niente_prima_di_chiudere(casa):
    programma, _ = finestre._programma()
    assert programma.domanda_prima_di_chiudere() is None
    programma.sicuro = SimpleNamespace(lavori_tuoi=lambda: [])
    assert programma.domanda_prima_di_chiudere() is None


def test_prima_di_chiudere_si_dice_cosa_fa_l_archivio(casa):
    programma, _ = finestre._programma()
    programma.sicuro = SimpleNamespace(
        lavori_tuoi=lambda: [archivio_sicuro.PRIMA_COPIA_A_PAROLE, "un'estrazione"])
    assert programma.domanda_prima_di_chiudere() == (
        "Nell'Archivio sicuro è ancora in corso: la prima copia, un'estrazione. Se chiudi "
        "adesso si ferma senza rovinare niente: la prima copia riprende da sola, il resto "
        "lo rifai quando vuoi.\n\nChiudo?")


def test_prima_di_chiudere_si_dicono_tutte_e_due_le_cose(casa, monkeypatch):
    programma, _ = finestre._programma()
    programma.sicuro = SimpleNamespace(lavori_tuoi=lambda: ["un'estrazione"])
    monkeypatch.setattr(programma, "lavori_in_corso", lambda: ["un'importazione"])
    domanda = programma.domanda_prima_di_chiudere()
    prima, dopo, chiudo = domanda.split("\n\n")
    assert prima.startswith("Sta ancora lavorando: un'importazione.")
    assert dopo.startswith("Nell'Archivio sicuro è ancora in corso: un'estrazione.")
    assert chiudo == "Chiudo?"


def test_se_l_archivio_non_dice_i_suoi_lavori_si_chiude_lo_stesso(casa, monkeypatch):
    programma, _ = finestre._programma()

    def rotti():
        raise RuntimeError("guasto")

    programma.sicuro = SimpleNamespace(lavori_tuoi=rotti)
    assert programma.domanda_prima_di_chiudere() is None
    monkeypatch.setattr(programma, "lavori_in_corso", lambda: ["un'importazione"])
    assert "Archivio sicuro" not in programma.domanda_prima_di_chiudere()


def test_spegnendo_si_chiude_anche_l_archivio(casa):
    chiusi = []
    programma, _ = finestre._programma()
    programma.sicuro = SimpleNamespace(chiudi=lambda: chiusi.append(True) or True)
    accesso.apri(REALE)
    programma.spegni()
    assert chiusi == [True]
    with pytest.raises(ErroreOfficina):
        accesso.vero()


def test_se_l_archivio_non_si_chiude_il_programma_si_spegne_lo_stesso(casa):
    programma, _ = finestre._programma()

    def rotto():
        raise RuntimeError("guasto")

    programma.sicuro = SimpleNamespace(chiudi=rotto)
    accesso.apri(REALE)
    programma.spegni()
    with pytest.raises(ErroreOfficina):
        accesso.vero()


def test_rientrare_con_la_password_la_ricorda_e_rifa_windows(casa, porte, fabbrica,
                                                            guardia_pulita):
    _con_l_archivio(fabbrica)
    _senza_password_scritta()
    carta.aggiorna(**{archivio_sicuro.CAMBIO: archivio_sicuro.NON_SI_SA})
    accesso.apri(REALE, PAROLA)
    programma = _programma(fabbrica)
    try:
        with pytest.raises(ErroreOfficina):
            programma.rientra(NUOVA)
        assert SCRITTA_IL not in carta.leggi() and not sigillo.c_e(REALE)
        assert archivio_sicuro.cambio_lasciato() == archivio_sicuro.NON_SI_SA
        assert programma.rientra(PAROLA) == {"vai": "/"}
        assert _scritta_adesso()
        assert archivio_sicuro.cambio_lasciato() is None
        assert sigillo.apri(REALE) == PAROLA
    finally:
        finestre._chiudi_davvero(programma)


def test_rientrare_con_windows_aspetta_la_password_del_mese(casa, porte, fabbrica,
                                                           guardia_pulita):
    _con_l_archivio(fabbrica)
    sigillo.sigilla(REALE, PAROLA)
    accesso.apri(REALE, PAROLA)
    programma = _programma(fabbrica)
    try:
        assert programma.rientra_con_windows() == {"vai": "/"}
        _senza_password_scritta()
        assert _codice(programma.rientra_con_windows) == "password_del_mese"
        assert sigillo.c_e(REALE)
    finally:
        finestre._chiudi_davvero(programma)


def test_rientrando_un_sigillo_vecchio_resta_e_si_rifa(casa, porte, fabbrica,
                                                      guardia_pulita):
    all_avvio._forziere_acceso()
    sigillo.sigilla(REALE, DI_PRIMA)
    accesso.apri(REALE, PAROLA)
    programma = _programma(fabbrica)
    try:
        assert _codice(programma.rientra_con_windows) == "sigillo_rotto"
        assert sigillo.apri(REALE) == DI_PRIMA
        assert programma.rientra(PAROLA) == {"vai": "/"}
        assert sigillo.apri(REALE) == PAROLA
        assert programma.rientra_con_windows() == {"vai": "/"}
    finally:
        finestre._chiudi_davvero(programma)


def test_rientrare_nell_archivio_di_prova_non_conta_come_password_scritta(
        casa, porte, fabbrica, guardia_pulita, monkeypatch):
    carta.comincia_da_zero()
    carta.aggiorna(**{archivio_sicuro.CAMBIO: archivio_sicuro.NON_SI_SA})
    accesso.apri("finto")
    monkeypatch.setattr(forziere, "per", lambda dove: strade_password._ForziereFinto())
    programma = _programma(fabbrica)
    try:
        assert programma.rientra(strade_password.GIUSTA) == {"vai": "/"}
        assert SCRITTA_IL not in carta.leggi()
        assert archivio_sicuro.cambio_lasciato() == archivio_sicuro.NON_SI_SA
        assert not sigillo.c_e(REALE)
    finally:
        finestre._chiudi_davvero(programma)


@pytest.fixture
def reale_col_forziere(tmp_path, monkeypatch, guardia_pulita):
    monkeypatch.setenv("OFFICINA_ARCHIVIO", str(tmp_path / "archivio"))
    monkeypatch.setenv("OFFICINA_CASA_PROGRAMMA", str(tmp_path / "casa"))
    accesso.chiudi(con_copia=False)
    accesso.apri(REALE)
    monkeypatch.setattr(forziere, "per", lambda dove: strade_password._ForziereFinto())
    yield TestClient(_app(), client=("127.0.0.1", 51000))
    accesso.chiudi(con_copia=False)


def _app():
    from officina.web.server import app

    return app


def test_sbloccare_lo_schermo_conta_come_password_scritta(reale_col_forziere):
    blocco.guardia.blocca_adesso("qui")
    risposta = strade_password._riprova(reale_col_forziere, "sbagliata-sbagliata")
    assert risposta.headers["location"] == "/blocco?sbagliata=1"
    assert SCRITTA_IL not in carta.leggi()
    risposta = strade_password._riprova(reale_col_forziere, strade_password.GIUSTA)
    assert risposta.headers["location"] == "/"
    assert _scritta_adesso()


def test_se_la_data_non_si_scrive_lo_schermo_si_sblocca_lo_stesso(reale_col_forziere,
                                                                  monkeypatch):
    def rotta(adesso=None):
        raise OSError("carta in sola lettura")

    monkeypatch.setattr(archivio_sicuro, "password_scritta", rotta)
    blocco.guardia.blocca_adesso("qui")
    risposta = strade_password._riprova(reale_col_forziere, strade_password.GIUSTA)
    assert risposta.headers["location"] == "/"
    assert not blocco.guardia.e_bloccato("qui")


def test_sbloccare_l_archivio_di_prova_non_conta(cliente, con_forziere, tmp_path,
                                                monkeypatch):
    monkeypatch.setenv("OFFICINA_CASA_PROGRAMMA", str(tmp_path / "casa"))
    blocco.guardia.blocca_adesso("qui")
    risposta = strade_password._riprova(cliente, strade_password.GIUSTA)
    assert risposta.headers["location"] == "/"
    assert SCRITTA_IL not in carta.leggi()


def test_la_pagina_del_blocco_non_offre_windows_nel_mese_della_password(casa, porte,
                                                                        fabbrica,
                                                                        monkeypatch):
    _con_l_archivio(fabbrica)
    sigillo.sigilla(REALE, PAROLA)
    assert impostazioni._c_e_il_sigillo()
    _senza_password_scritta()
    assert not impostazioni._c_e_il_sigillo()

    def rotta(posizione, adesso=None):
        raise OSError("carta illeggibile")

    monkeypatch.setattr(archivio_sicuro, "serve_la_password_scritta", rotta)
    assert not impostazioni._c_e_il_sigillo()


def test_creare_l_archivio_accende_il_forziere_e_windows(casa, porte, fabbrica):
    carta.comincia_da_zero()
    accesso.apri(REALE)
    programma = _programma(fabbrica)
    try:
        assert programma.crea_l_archivio_sicuro(PAROLA, PAROLA, True) == {"creato": True}
        cassa = forziere.per(posizione(REALE))
        assert cassa.acceso and cassa.la_password_e_giusta(PAROLA)
        assert accesso.vero().parola_del_forziere == PAROLA
        assert programma.sicuro.guarda() == APERTO
        assert _si_apre_con(PAROLA)
        assert sigillo.apri(REALE) == PAROLA
        assert _scritta_adesso()
    finally:
        finestre._chiudi_davvero(programma)
    _tutto_chiuso(programma)
    accesso.apri(REALE, PAROLA)
    assert archivio_sicuro.c_e(posizione(REALE))


def test_un_archivio_creato_male_non_accende_il_forziere(casa, fabbrica):
    carta.comincia_da_zero()
    accesso.apri(REALE)
    programma = _programma(fabbrica)
    try:
        assert _codice(lambda: programma.crea_l_archivio_sicuro("corta", "corta", True)) \
            == "password_corta"
        assert _codice(lambda: programma.crea_l_archivio_sicuro(PAROLA, PAROLA, False)) \
            == "manca_ho_capito"
        assert _codice(lambda: programma.crea_l_archivio_sicuro(PAROLA, NUOVA, True)) \
            == "non_coincidono"
        assert not forziere.per(posizione(REALE)).acceso
        assert not archivio_sicuro.c_e(posizione(REALE))
    finally:
        finestre._chiudi_davvero(programma)


def test_mentre_lavora_l_archivio_non_si_crea_se_c_e_da_accendere_il_forziere(
        casa, fabbrica, monkeypatch):
    carta.comincia_da_zero()
    accesso.apri(REALE)
    programma = _programma(fabbrica)
    monkeypatch.setattr(programma, "lavori_in_corso", lambda: ["un'importazione"])
    try:
        assert _codice(lambda: programma.crea_l_archivio_sicuro(PAROLA, PAROLA, True)) \
            == "occupato"
        assert not forziere.per(posizione(REALE)).acceso
    finally:
        finestre._chiudi_davvero(programma)


def test_nell_archivio_di_prova_l_archivio_sicuro_non_si_tocca(casa, fabbrica):
    carta.comincia_da_zero()
    accesso.apri("finto")
    programma = _programma(fabbrica)
    try:
        assert _codice(lambda: programma.crea_l_archivio_sicuro(PAROLA, PAROLA, True)) \
            == "non_nel_vero"
        assert _codice(lambda: programma.cambia_la_password(PAROLA, NUOVA, NUOVA)) \
            == "non_nel_vero"
        assert not forziere.per(accesso.vero().dove).acceso
        assert not archivio_sicuro.c_e(posizione(REALE))
    finally:
        finestre._chiudi_davvero(programma)


def test_il_cambio_di_password_porta_tutto_sulla_nuova(casa, porte, fabbrica):
    _con_l_archivio(fabbrica)
    sigillo.sigilla(REALE, PAROLA)
    programma, ponte = _con_la_finestrina(fabbrica)
    try:
        ponte.apri_il_forziere(PAROLA)
        all_avvio._aspetta_l_apertura()
        assert _aspetta(programma.sicuro) == APERTO
        assert programma.cambia_la_password(PAROLA, NUOVA, NUOVA) == {
            "cambiata": True, "avvisi": [], "chiavetta": True}
        cassa = forziere.per(posizione(REALE))
        assert cassa.la_password_e_giusta(NUOVA) and not cassa.la_password_e_giusta(PAROLA)
        assert accesso.vero().parola_del_forziere == NUOVA
        assert sigillo.apri(REALE) == NUOVA
        assert _si_apre_con(NUOVA) and not _si_apre_con(PAROLA)
        assert programma.sicuro.guarda() == APERTO
        assert archivio_sicuro.cambio_lasciato() is None
        assert _scritta_adesso()
    finally:
        finestre._chiudi_davvero(programma)
    _tutto_chiuso(programma)
    cassa = forziere.per(posizione(REALE))
    assert not cassa.aperto
    assert cassa.la_password_e_giusta(NUOVA) and not cassa.la_password_e_giusta(PAROLA)
    accesso.apri(REALE, NUOVA)


def test_senza_archivio_il_cambio_tocca_solo_il_forziere(casa, porte, fabbrica):
    all_avvio._forziere_acceso()
    accesso.apri(REALE, PAROLA)
    programma = _programma(fabbrica)
    try:
        with pytest.raises(PasswordSbagliata):
            programma.cambia_la_password(DI_PRIMA, NUOVA, NUOVA)
        assert forziere.per(posizione(REALE)).la_password_e_giusta(PAROLA)
        assert programma.cambia_la_password(PAROLA, NUOVA, NUOVA) == {
            "cambiata": True, "avvisi": [], "chiavetta": False}
        assert forziere.per(posizione(REALE)).la_password_e_giusta(NUOVA)
        assert not archivio_sicuro.c_e(posizione(REALE))
    finally:
        finestre._chiudi_davvero(programma)
    accesso.apri(REALE, NUOVA)


def test_mentre_lavora_la_password_non_si_cambia(casa, fabbrica, monkeypatch):
    _con_l_archivio(fabbrica)
    accesso.apri(REALE, PAROLA)
    programma = _programma(fabbrica)
    monkeypatch.setattr(programma, "lavori_in_corso", lambda: ["un'importazione"])
    try:
        assert _codice(lambda: programma.cambia_la_password(PAROLA, NUOVA, NUOVA)) \
            == "occupato"
        assert forziere.per(posizione(REALE)).la_password_e_giusta(PAROLA)
        assert archivio_sicuro.CAMBIO not in carta.leggi()
    finally:
        finestre._chiudi_davvero(programma)
