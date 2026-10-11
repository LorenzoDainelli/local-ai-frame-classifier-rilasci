from __future__ import annotations

from fastapi.testclient import TestClient

from officina.web import origine


def _cliente(archivio_pieno, base: str = "http://127.0.0.1:8080") -> TestClient:
    from officina.web.server import app

    return TestClient(app, base_url=base, client=("127.0.0.1", 51000),
                      follow_redirects=False)


def test_il_nome_giusto_passa():
    for host in ("localhost:8080", "127.0.0.1:8080", "[::1]:8080",
                 "192.168.1.5:8080", "10.0.0.7", "localhost"):
        assert origine.perche_no("GET", {"host": host}) is None, host


def test_un_nome_che_porta_qui_non_passa():
    for host in ("officina.esempio.it", "evil.com:8080", "8.8.8.8:8080"):
        assert origine.perche_no("GET", {"host": host}) == \
            origine.NON_E_IL_SUO_NOME, host


def test_un_comando_da_un_altra_pagina_non_passa():
    casa = {"host": "127.0.0.1:8080"}
    assert origine.perche_no("POST", {**casa, "origin": "http://evil.com"}) == \
        origine.ARRIVA_DA_FUORI
    assert origine.perche_no(
        "POST", {**casa, "sec-fetch-site": "cross-site"}) == \
        origine.ARRIVA_DA_FUORI
    assert origine.perche_no(
        "POST", {**casa, "origin": "http://127.0.0.1:8080"}) is None
    assert origine.perche_no(
        "POST", {**casa, "sec-fetch-site": "same-origin"}) is None


def test_leggere_da_un_altra_pagina_si_puo_lo_stesso():
    casa = {"host": "127.0.0.1:8080", "sec-fetch-site": "cross-site"}
    assert origine.perche_no("GET", casa) is None


def test_senza_intestazioni_passa(archivio_pieno):
    cliente = _cliente(archivio_pieno)
    assert cliente.get("/sistemare").status_code == 200


def test_il_server_rifiuta_un_comando_da_fuori(archivio_pieno):
    cliente = _cliente(archivio_pieno)
    risposta = cliente.post("/elenchi/controlla-i-file",
                            headers={"origin": "http://truffa.example"})
    assert risposta.status_code == 403
    assert "un'altra pagina" in risposta.json()["messaggio"]


def test_il_server_rifiuta_un_nome_che_porta_qui(archivio_pieno):
    cliente = _cliente(archivio_pieno, base="http://truffa.example")
    risposta = cliente.get("/elenchi")
    assert risposta.status_code == 403
    assert "proprio indirizzo" in risposta.json()["messaggio"]


def test_lo_stesso_comando_dalla_sua_pagina_passa(archivio_pieno):
    cliente = _cliente(archivio_pieno)
    risposta = cliente.post("/elenchi/controlla-i-file",
                            headers={"origin": "http://127.0.0.1:8080",
                                     "sec-fetch-site": "same-origin"})
    assert risposta.status_code == 303


def test_un_nome_in_piu_si_puo_ammettere(monkeypatch):
    monkeypatch.setenv("OFFICINA_NOMI_AMMESSI", "officina.casa")
    assert origine.perche_no("GET", {"host": "officina.casa:8080"}) is None
    assert origine.perche_no("GET", {"host": "altro.casa:8080"}) == \
        origine.NON_E_IL_SUO_NOME
