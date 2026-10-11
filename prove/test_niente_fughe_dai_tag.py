from __future__ import annotations

import json
import re

from officina.web import vista

UN_NODO_CATTIVO = "</script><img src=x onerror=alert(1)>"


def test_il_json_nella_pagina_non_esce_dal_tag():
    scritto = vista.json_per_la_pagina({"nome": UN_NODO_CATTIVO})

    assert "</script" not in scritto
    assert "<" not in scritto and ">" not in scritto and "&" not in scritto
    assert json.loads(scritto)["nome"] == UN_NODO_CATTIVO


def test_gli_accenti_restano_leggibili():
    scritto = vista.json_per_la_pagina({"nome": "perché siè cosià"})
    assert "è" in scritto
    assert "\\u00e8" not in scritto


def test_le_righe_invisibili_di_javascript_sono_scampate():
    scritto = vista.json_per_la_pagina({"nome": "a b c"})
    assert " " not in scritto and " " not in scritto
    assert json.loads(scritto)["nome"] == "a b c"


def test_nessuna_pagina_mette_json_crudo_dentro_uno_script(archivio_pieno):
    from pathlib import Path

    CASA = Path(__file__).resolve().parent.parent
    dentro_uno_script = re.compile(
        r'<script[^>]*type="application/json"[^>]*>(.*?)</script>', re.S)
    colpevoli = []
    for foglio in sorted((CASA / "officina" / "web" / "templates").glob("*.html")):
        testo = foglio.read_text(encoding="utf-8")
        for pezzo in dentro_uno_script.findall(testo):
            nome = re.findall(r"\{\{\s*([A-Za-z_][\w.]*)\s*\|\s*safe\s*\}\}", pezzo)
            colpevoli.extend(f"{foglio.name}: {n}" for n in nome)
    assert colpevoli, "le pagine che mettono json dentro uno script sono sparite"

    from officina.web import server

    fogli = [CASA / "officina" / "web" / "server.py",
             *sorted((CASA / "officina" / "web" / "strade").glob("*.py"))]
    crudo = [riga for foglio in fogli
             for riga in foglio.read_text(encoding="utf-8").splitlines()
             if '"dati' in riga and "json.dumps" in riga]
    assert not crudo, (
        "questi mettono json.dumps dentro la pagina invece di "
        "vista.json_per_la_pagina:\n  " + "\n  ".join(crudo))
    assert server is not None


def test_un_nome_col_tag_dentro_non_rompe_la_pagina(archivio_pieno):
    from fastapi.testclient import TestClient

    from officina.web.server import app

    cliente = TestClient(app, client=("127.0.0.1", 51000),
                         follow_redirects=False)
    fatto = cliente.post("/api/nodi",
                         data={"nome": UN_NODO_CATTIVO, "genitore_id": ""})
    assert fatto.status_code in (200, 303), fatto.status_code

    pagina = cliente.get("/officina").text
    assert "</script><img" not in pagina
    assert "<img src=x" not in pagina
    assert "\\u003c/script\\u003e" in pagina
    assert pagina.count("<script") == pagina.count("</script>")
