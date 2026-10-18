from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from officina.web import origine

POLITICA = ("default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' "
            "'unsafe-inline'; img-src 'self' data: blob:; media-src 'self' blob:; "
            "connect-src 'self'; font-src 'self' data:; object-src 'none'; base-uri 'none'; "
            "form-action 'self'; frame-ancestors 'none'")


@pytest.fixture
def cliente(archivio_pieno):
    from officina.web.server import app

    return TestClient(app, base_url="http://127.0.0.1:8080", client=("127.0.0.1", 51000),
                      follow_redirects=False)


@pytest.fixture
def tablet(archivio_pieno):
    from officina.modello import dispositivi
    from officina.web.server import app

    archivio_pieno.imposta("accesso_dalla_rete", True)
    _cliente = TestClient(app, client=("192.168.1.40", 51000), follow_redirects=False)
    _cliente.get("/")
    with archivio_pieno.scrittura() as connessione:
        dispositivi.decidi(connessione, dispositivi.elenco(connessione)[0]["id"], "approvato")
    assert _cliente.get("/stato").status_code == 200
    return _cliente


def _sicure(risposta) -> None:
    assert risposta.headers["x-frame-options"] == "DENY"
    assert risposta.headers["content-security-policy"] == POLITICA
    assert risposta.headers["x-content-type-options"] == "nosniff"
    assert risposta.headers["referrer-policy"] == "same-origin"


def test_ogni_risposta_ha_le_intestazioni_di_sicurezza(cliente):
    for dove, accetta in (("/", "text/html"), ("/stato", "text/html"),
                          ("/api/in-corso", "application/json"),
                          ("/statici/js/comune.js", "*/*"), ("/miniatura/1", "image/*"),
                          ("/non-esiste", "text/html"), ("/non-esiste", "application/json")):
        _sicure(cliente.get(dove, headers={"accept": accetta}))
    _sicure(cliente.post("/api/impostazione", data={"chiave": "x"},
                         headers={"origin": "http://truffa.example"}))


def test_pagine_e_dati_non_restano_nella_cache(cliente):
    for dove, accetta in (("/stato", "text/html"), ("/api/in-corso", "application/json"),
                          ("/non-esiste", "text/html")):
        assert cliente.get(dove, headers={"accept": accetta}).headers["cache-control"] == \
            "no-store", dove
    assert cliente.get("/statici/js/comune.js").headers["cache-control"] == "no-cache"


def test_le_miniature_restano_in_cache_solo_su_questo_computer(cliente, tablet):
    qui = cliente.get("/miniatura/1")
    assert qui.status_code == 200
    assert qui.headers["content-type"].startswith("image/")
    assert qui.headers["cache-control"] == "private, no-cache"
    assert qui.headers["etag"].startswith('W/"')
    fuori = tablet.get("/miniatura/1")
    assert fuori.status_code == 200
    assert fuori.headers["cache-control"] == "no-store"
    assert tablet.get("/statici/js/comune.js").headers["cache-control"] == "no-cache"


@pytest.mark.parametrize("destinazione,modo", [("iframe", "navigate"), ("image", "no-cors"),
                                               ("video", "no-cors"), ("empty", "cors"),
                                               ("script", "no-cors")])
def test_un_altro_sito_non_mette_il_programma_dentro_le_sue_pagine(cliente, destinazione, modo):
    for dove in ("/impostazioni", "/miniatura/1", "/api/in-corso"):
        risposta = cliente.get(dove, headers={"sec-fetch-site": "cross-site",
                                              "sec-fetch-mode": modo,
                                              "sec-fetch-dest": destinazione})
        assert risposta.status_code == 403, (dove, destinazione)
        assert risposta.json()["messaggio"] == origine.DENTRO_UN_ALTRO_SITO
        _sicure(risposta)


def test_un_collegamento_da_un_altro_sito_apre_la_pagina(cliente):
    risposta = cliente.get("/stato", headers={"sec-fetch-site": "cross-site",
                                              "sec-fetch-mode": "navigate",
                                              "sec-fetch-dest": "document",
                                              "accept": "text/html"})
    assert risposta.status_code == 200


def test_un_comando_da_una_pagina_senza_origine_non_passa(cliente, archivio_pieno):
    prima = archivio_pieno.impostazione("movimento")
    risposta = cliente.post("/api/impostazione", data={"chiave": "movimento", "valore": "0"},
                            headers={"origin": "null", "accept": "application/json"})
    assert risposta.status_code == 403
    assert risposta.json()["messaggio"] == origine.ARRIVA_DA_FUORI
    assert archivio_pieno.impostazione("movimento") == prima
    assert origine.perche_no("POST", {"host": "127.0.0.1:8080", "origin": "null",
                                      "sec-fetch-site": "same-origin"}) == origine.ARRIVA_DA_FUORI
    assert origine.perche_no("GET", {"host": "127.0.0.1:8080", "origin": "null"}) is None


def test_la_descrizione_delle_strade_non_si_pubblica(cliente):
    from officina.web.server import app

    assert app.openapi_url is None and app.docs_url is None and app.redoc_url is None
    for dove in ("/openapi.json", "/docs", "/redoc", "/docs/oauth2-redirect"):
        assert cliente.get(dove).status_code == 404, dove


def test_un_corpo_troppo_grande_si_ferma_subito(cliente):
    grande = json.dumps({"azione": "fuori_archivio", "scatti": [1] * 400_000}).encode()
    assert len(grande) > 2 ** 20
    risposta = cliente.post("/scatti/in-blocco", content=grande,
                            headers={"content-type": "application/json",
                                     "origin": "http://127.0.0.1:8080"})
    assert risposta.status_code == 413
    assert "1 MB" in risposta.json()["messaggio"]
    _sicure(risposta)


def test_un_corpo_a_pezzi_troppo_grande_si_ferma(cliente):
    def a_pezzi():
        yield b'{"azione": "fuori_archivio", "scatti": ['
        for _ in range(300):
            yield b"1," * 2000
        yield b"1]}"

    risposta = cliente.post("/scatti/in-blocco", content=a_pezzi(),
                            headers={"content-type": "application/json",
                                     "origin": "http://127.0.0.1:8080"})
    assert risposta.status_code == 413
    assert "1 MB" in risposta.json()["messaggio"]


def test_un_modulo_troppo_grande_si_ferma(cliente):
    risposta = cliente.post("/api/impostazione",
                            data={"chiave": "schermo_del_colore", "valore": "x" * (2 ** 20)},
                            headers={"origin": "http://127.0.0.1:8080"})
    assert risposta.status_code == 413


def test_un_corpo_normale_passa(cliente):
    risposta = cliente.post("/scatti/in-blocco",
                            content=json.dumps({"azione": "data",
                                                "scatti": [1] * 150_000}).encode(),
                            headers={"content-type": "application/json",
                                     "origin": "http://127.0.0.1:8080",
                                     "accept": "application/json"})
    assert risposta.status_code == 400
    assert risposta.json()["messaggio"] == "Serve una data."


def test_i_file_mandati_col_modulo_non_hanno_il_limite_del_mb(cliente):
    risposta = cliente.post("/api/impostazione",
                            files={"pacchetto": ("p.bin", b"0" * (2 ** 20 + 10))},
                            data={"chiave": "movimento", "valore": "1"},
                            headers={"origin": "http://127.0.0.1:8080"})
    assert risposta.status_code != 413
