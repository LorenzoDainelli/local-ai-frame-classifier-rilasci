from __future__ import annotations

from fastapi.testclient import TestClient

from officina.modello import dispositivi


def _cliente(indirizzo: str) -> TestClient:
    from officina.web.server import app

    return TestClient(app, client=(indirizzo, 51000))


def test_il_computer_stesso_passa_sempre(archivio_pieno):
    assert _cliente("127.0.0.1").get("/").status_code == 200


def test_con_la_rete_spenta_non_passa_nessun_altro(archivio_pieno):
    archivio_pieno.imposta("accesso_dalla_rete", False)
    risposta = _cliente("192.168.1.40").get("/")
    assert risposta.status_code == 403


def test_un_indirizzo_di_internet_non_passa_mai(archivio_pieno):
    archivio_pieno.imposta("accesso_dalla_rete", True)
    assert _cliente("203.0.113.7").get("/").status_code == 403


def test_un_dispositivo_nuovo_viene_registrato_e_respinto(archivio_pieno):
    archivio_pieno.imposta("accesso_dalla_rete", True)

    risposta = _cliente("192.168.1.40").get("/")
    assert risposta.status_code == 403
    assert "approvato" in risposta.json()["messaggio"]

    with archivio_pieno.lettura() as connessione:
        elenco = dispositivi.elenco(connessione)
    assert [d["indirizzo"] for d in elenco] == ["192.168.1.40"]
    assert elenco[0]["stato"] == "in_attesa"


def test_una_volta_approvato_passa(archivio_pieno):
    archivio_pieno.imposta("accesso_dalla_rete", True)
    _cliente("192.168.1.40").get("/")

    with archivio_pieno.scrittura() as connessione:
        macchina = dispositivi.elenco(connessione)[0]
        dispositivi.decidi(connessione, macchina["id"], "approvato", "zenbook")

    assert _cliente("192.168.1.40").get("/").status_code == 200
    assert _cliente("192.168.1.99").get("/").status_code == 403


def test_un_dispositivo_rifiutato_resta_fuori(archivio_pieno):
    archivio_pieno.imposta("accesso_dalla_rete", True)
    _cliente("192.168.1.55").get("/")

    with archivio_pieno.scrittura() as connessione:
        macchina = dispositivi.elenco(connessione)[0]
        dispositivi.decidi(connessione, macchina["id"], "rifiutato")

    assert _cliente("192.168.1.55").get("/").status_code == 403


def test_i_contatti_si_contano(archivio_pieno, monkeypatch):
    monkeypatch.setattr(dispositivi, "OGNI_QUANTO_SI_SCRIVE", 0.0)
    archivio_pieno.imposta("accesso_dalla_rete", True)
    for _ in range(3):
        _cliente("192.168.1.77").get("/")
    with archivio_pieno.lettura() as connessione:
        assert dispositivi.elenco(connessione)[0]["contatti"] == 3
