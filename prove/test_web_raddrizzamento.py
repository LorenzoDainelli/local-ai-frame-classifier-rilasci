from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def cliente(archivio):
    from officina.web.server import app
    return TestClient(app, client=("127.0.0.1", 51000))


def test_la_pagina_si_disegna(cliente):
    risposta = cliente.get("/volti/raddrizzamento")
    assert risposta.status_code == 200
    assert "raddrizz" in risposta.text.lower()
    assert "inventate" in risposta.text.lower()


def test_non_chiede_niente_a_internet(cliente):
    fuori = re.findall(r'(?:src|href)="(https?://[^"]+)"',
                       cliente.get("/volti/raddrizzamento").text)
    assert fuori == []


def test_le_facce_arrivano_come_immagini(cliente):
    for quale in ("prima", "dopo"):
        risposta = cliente.get(f"/volti/raddrizzamento/0/{quale}.png")
        assert risposta.status_code == 200
        assert risposta.headers["content-type"] == "image/png"
        assert risposta.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_una_faccia_che_non_c_e_non_inventa_niente(cliente):
    assert cliente.get("/volti/raddrizzamento/99/prima.png").status_code == 404
    assert cliente.get("/volti/raddrizzamento/0/altro.png").status_code == 404


def test_dalla_salute_ci_si_arriva(cliente):
    assert "/volti/raddrizzamento" in cliente.get("/stato").text


def test_le_facce_raddrizzate_si_somigliano_fra_loro(cliente):
    numpy = pytest.importorskip("numpy")
    import io

    from PIL import Image

    def quadrato(indice, quale):
        risposta = cliente.get(f"/volti/raddrizzamento/{indice}/{quale}.png")
        return numpy.asarray(Image.open(io.BytesIO(risposta.content)).convert("L"),
                             dtype=numpy.float64).ravel()

    def somiglianza(a, b):
        a, b = a - a.mean(), b - b.mean()
        return float(a @ b / (numpy.linalg.norm(a) * numpy.linalg.norm(b)))

    dopo = [quadrato(i, "dopo") for i in range(4)]
    prima = [quadrato(i, "prima") for i in range(4)]
    assert min(somiglianza(dopo[0], altro) for altro in dopo[1:]) > 0.85
    assert min(somiglianza(prima[0], altro) for altro in prima[1:]) < \
        min(somiglianza(dopo[0], altro) for altro in dopo[1:])
