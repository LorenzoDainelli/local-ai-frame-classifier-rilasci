from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from officina import forziere
from officina.web import blocco

PAROLA = "cavallo-verde-quaranta"


QUI = "qui"


@pytest.fixture(autouse=True)
def guardia_pulita():
    blocco.guardia.dimentica_tutti()
    yield
    blocco.guardia.dimentica_tutti()


def indietro_nel_tempo(chi, secondi):
    with blocco.guardia._lucchetto:
        blocco.guardia._suo(chi).ultimo -= secondi


@pytest.fixture
def cliente(archivio_pieno):
    from officina.web.server import app

    return TestClient(app, client=("127.0.0.1", 51000))


def test_spento_non_si_blocca_mai(cliente, archivio_pieno):
    archivio_pieno.imposta("blocco_dopo_minuti", 0)
    indietro_nel_tempo(QUI, 10_000)
    assert cliente.get("/", follow_redirects=False).status_code == 200


def test_senza_forziere_non_si_blocca(cliente, archivio_pieno):
    archivio_pieno.imposta("blocco_dopo_minuti", 5)
    indietro_nel_tempo(QUI, 10_000)
    assert not forziere.per(archivio_pieno.dove).acceso
    assert cliente.get("/", follow_redirects=False).status_code == 200


def test_acceso_e_passato_il_tempo_lo_schermo_si_copre(archivio_pieno):
    assert blocco.guardia.controlla(QUI, 15, acceso=True) is False
    indietro_nel_tempo(QUI, 16 * 60)
    assert blocco.guardia.controlla(QUI, 15, acceso=True) is True
    assert blocco.guardia.e_bloccato(QUI)


def test_un_minuto_prima_non_si_blocca(archivio_pieno):
    indietro_nel_tempo(QUI, 14 * 60)
    assert blocco.guardia.controlla(QUI, 15, acceso=True) is False


def test_spegnere_il_blocco_toglie_anche_quello_gia_scattato(archivio_pieno):
    blocco.guardia.blocca_adesso(QUI)
    assert blocco.guardia.controlla(QUI, 0, acceso=True) is False
    assert not blocco.guardia.e_bloccato(QUI)


@pytest.fixture
def come_se_ci_fosse_un_forziere(monkeypatch, archivio_pieno):
    from officina.web.strade import base

    class Finto:
        acceso = True
        aperto = False

    monkeypatch.setattr(base.forziere, "per", lambda dove: Finto())
    archivio_pieno.imposta("blocco_dopo_minuti", 15)
    return archivio_pieno


def test_bloccato_ogni_pagina_porta_allo_schermo_coperto(
        cliente, come_se_ci_fosse_un_forziere):
    blocco.guardia.blocca_adesso(QUI)
    for dove in ("/", "/officina", "/impostazioni", "/stato"):
        risposta = cliente.get(dove, follow_redirects=False)
        assert risposta.status_code == 303
        assert risposta.headers["location"] == "/blocco"


def test_bloccato_le_chiamate_ricevono_un_no_e_non_i_dati(
        cliente, come_se_ci_fosse_un_forziere):
    blocco.guardia.blocca_adesso(QUI)
    risposta = cliente.get("/api/griglia",
                           headers={"accept": "application/json"})
    assert risposta.status_code == 403
    assert "scatti" not in risposta.json()


def test_lo_schermo_coperto_non_dice_niente_dell_archivio(
        cliente, come_se_ci_fosse_un_forziere):
    blocco.guardia.blocca_adesso(QUI)
    testo = cliente.get("/blocco").text
    assert "barra-alta" not in testo
    assert "scatti</span>" not in testo
    assert "<title>Local AI Frame Classifier</title>" in testo


def test_lo_schermo_coperto_riceve_il_suo_foglio_di_stile(
        cliente, come_se_ci_fosse_un_forziere):
    blocco.guardia.blocca_adesso(QUI)
    risposta = cliente.get("/statici/css/fondamenta.css", follow_redirects=False)
    assert risposta.status_code == 200
    assert "css" in risposta.headers["content-type"]
    assert cliente.get("/miniatura/1", follow_redirects=False).status_code == 303


def test_non_bloccato_lo_schermo_coperto_non_si_apre(cliente):
    risposta = cliente.get("/blocco", follow_redirects=False)
    assert risposta.status_code == 303
    assert risposta.headers["location"] == "/"


def test_solo_la_password_giusta_rientra(tmp_path):
    from officina.archivio.accesso import Posizione

    radice = tmp_path / "finto"
    (radice / "miniature").mkdir(parents=True)
    (radice / "archivio.sqlite").write_bytes(b"non e' un database vero")
    dove = Posizione(radice, "finto")
    forziere.Forziere(dove).accendi(PAROLA)

    blocco.guardia.blocca_adesso(QUI)
    assert blocco.guardia.sblocca(QUI, dove, "un'altra parola lunga") is False
    assert blocco.guardia.e_bloccato(QUI)
    assert blocco.guardia.sblocca(QUI, dove, "corta") is False
    assert blocco.guardia.sblocca(QUI, dove, PAROLA) is True
    assert not blocco.guardia.e_bloccato(QUI)


def test_chiedere_se_la_password_e_giusta_non_apre_il_forziere(tmp_path):
    from officina.archivio.accesso import Posizione

    radice = tmp_path / "finto"
    (radice / "miniature").mkdir(parents=True)
    (radice / "archivio.sqlite").write_bytes(b"non e' un database vero")
    cassa = forziere.Forziere(Posizione(radice, "finto"))
    cassa.accendi(PAROLA)
    peso_prima = cassa.file.stat().st_size
    era_aperto = cassa.aperto

    assert cassa.la_password_e_giusta(PAROLA) is True
    assert cassa.la_password_e_giusta("un'altra parola lunga") is False

    assert cassa.aperto == era_aperto
    assert cassa.file.stat().st_size == peso_prima


def test_su_un_archivio_senza_forziere_la_domanda_e_sempre_no(tmp_path):
    from officina.archivio.accesso import Posizione

    radice = tmp_path / "finto"
    radice.mkdir(parents=True)
    assert forziere.Forziere(Posizione(radice, "finto")
                             ).la_password_e_giusta(PAROLA) is False


def test_il_lavoro_che_gira_da_solo_non_tiene_sveglio_il_programma():
    assert blocco.e_attivita("/api/lavori") is False
    assert blocco.e_attivita("/miniatura/12") is False
    assert blocco.e_attivita("/statici/js/griglia.js") is False
    assert blocco.e_attivita("/officina") is True
    assert blocco.e_attivita("/api/albero/nodo/3") is True


def test_lo_zenbook_non_copre_lo_schermo_del_fisso(come_se_ci_fosse_un_forziere):
    fisso, zenbook = "qui", "192.168.1.40"
    blocco.guardia.visto_qualcuno(fisso)
    indietro_nel_tempo(zenbook, 20 * 60)

    assert blocco.guardia.controlla(zenbook, 15, acceso=True) is True
    assert blocco.guardia.controlla(fisso, 15, acceso=True) is False
    assert not blocco.guardia.e_bloccato(fisso)


def test_chi_lavora_di_la_non_tiene_sbloccato_di_qua(come_se_ci_fosse_un_forziere):
    fisso, zenbook = "qui", "192.168.1.40"
    indietro_nel_tempo(fisso, 20 * 60)
    blocco.guardia.visto_qualcuno(zenbook)

    assert blocco.guardia.controlla(fisso, 15, acceso=True) is True
    assert blocco.guardia.controlla(zenbook, 15, acceso=True) is False


def test_la_password_apre_uno_schermo_solo(come_se_ci_fosse_un_forziere,
                                           monkeypatch):
    from officina.web import blocco as modulo

    class Finto:
        acceso = True
        aperto = False

        @staticmethod
        def la_password_e_giusta(password):
            return True

    monkeypatch.setattr(modulo.forziere, "per", lambda dove: Finto())
    fisso, zenbook = "qui", "192.168.1.40"
    blocco.guardia.blocca_adesso(fisso)
    blocco.guardia.blocca_adesso(zenbook)

    assert blocco.guardia.sblocca(zenbook, None, PAROLA) is True
    assert not blocco.guardia.e_bloccato(zenbook)
    assert blocco.guardia.e_bloccato(fisso)


def test_il_computer_di_casa_e_sempre_lo_stesso_schermo():
    class Finta:
        def __init__(self, host):
            self.client = type("C", (), {"host": host})()

    assert blocco.chi_e(Finta("127.0.0.1")) == blocco.chi_e(Finta("::1"))
    assert blocco.chi_e(Finta("192.168.1.40")) != blocco.chi_e(Finta("127.0.0.1"))
