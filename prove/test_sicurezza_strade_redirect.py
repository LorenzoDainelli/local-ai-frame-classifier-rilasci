from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from officina.web.strade import base


def _cliente() -> TestClient:
    from officina.web.server import app

    return TestClient(app, client=("127.0.0.1", 51000))


@pytest.mark.parametrize("scritto", [
    "//evil.example/x",
    "///evil.example/x",
    "/\\evil.example/x",
    "\\\\evil.example\\x",
    "\\evil.example",
    "https://evil.example/x",
    "http:evil.example",
    "javascript:alert(1)",
    "evil.example/x",
    "",
    "/ok\r\nSet-Cookie: a=b",
    "/ok\tevil",
    "/ok\x00",
])
def test_il_ritorno_da_prova_non_porta_fuori_dal_programma(archivio_pieno, scritto):
    risposta = _cliente().get("/prova/qui-no", params={"da": scritto}, follow_redirects=False)
    assert risposta.status_code == 303
    assert risposta.headers["location"] == "/"


@pytest.mark.parametrize("scritto", ["/", "/stato", "/persone?a=1&b=2", "/impostazioni#aspetto"])
def test_il_ritorno_da_prova_dentro_il_programma_resta(archivio_pieno, scritto):
    risposta = _cliente().get("/prova/qui-no", params={"da": scritto}, follow_redirects=False)
    assert risposta.headers["location"] == scritto


@pytest.mark.parametrize("scritto,atteso", [
    ("/stato", "/stato"),
    ("//evil.example/x", "/"),
    ("/\\evil.example", "/"),
    ("https://evil.example", "/"),
    ("/x\ny", "/"),
    ("x", "/"),
    ("", "/"),
])
def test_percorso_interno(scritto, atteso):
    assert base.percorso_interno(scritto, "/") == atteso


def test_il_ritorno_dal_referer_non_porta_fuori(archivio_pieno):
    class Finta:
        def __init__(self, referer):
            self.headers = {"referer": referer}

    assert base.dove_torna(Finta("http://127.0.0.1:8000//evil.example/x?a=1"), "/qui") == "/qui"
    assert base.dove_torna(Finta("http://127.0.0.1:8000/stato?a=1"), "/qui") == "/stato?a=1"
    assert base.dove_torna(Finta(""), "/qui") == "/qui"
