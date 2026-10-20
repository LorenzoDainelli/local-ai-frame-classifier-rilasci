from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

COSA_MANDARE: dict[str, dict] = {
    "/albero/crea": {"nome": "nodo_di_prova"},
    "/api/albero/unisci": {"nodo_id": "1", "dentro": "2"},
    "/api/persone/non-e-lui": {"volti": "1"},
    "/impostazioni/copia": {"dove": ""},
    "/misura/nodo": {"nome": "mucchio_di_prova", "ramo_id": ""},
    "/misura/ramo": {"nome": "ramo_di_prova"},
    "/senza-data/blocco": {"giorno": "2024-07-03", "scatti": "1"},
    "/senza-data/gruppo": {"giorno": "2024-07-03", "scatto": "1"},
    "/senza-data/lascia": {"scatto": "1"},
}

COL_JSON: dict[str, dict] = {
    "/scatti/in-blocco": {"azione": "fuori_archivio", "scatti": []},
}

COL_FRENO = {
    "/importazione/parti": "/importazione/ferma",
    "/doppioni/guarda": "/doppioni/ferma",
    "/doppioni/conta": "/doppioni/ferma",
    "/parole/leggi": "/parole/ferma",
    "/misura/impronte": "/misura/impronte/ferma",
}


def _le_rotte() -> list[str]:
    from officina.web.server import tutte_le_strade

    return sorted({rotta.path for rotta in tutte_le_strade()
                   if "POST" in getattr(rotta, "methods", set())})


@pytest.fixture
def cliente(archivio_pieno):
    from officina.web.server import app

    return TestClient(app, client=("127.0.0.1", 51000), raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def _niente_scaricato_davvero(monkeypatch):
    from officina import modelli_in_casa

    monkeypatch.setattr(modelli_in_casa, "porta_in_casa", lambda quale, dove, lavoro: None)


@pytest.fixture(autouse=True)
def _nessun_lavoro_lasciato_acceso():
    import time

    from officina.web import giro, lavori, server
    from officina.web.strade import comune

    yield

    fili = [cosa for cosa in (*vars(server).values(), *vars(comune).values())
            if isinstance(cosa, lavori.Lavoro)]
    for _ in range(300):
        if not any(uno.sta_lavorando for uno in fili):
            break
        time.sleep(0.01)
    giro.stato.passo = None


@pytest.mark.parametrize("strada", _le_rotte())
def test_ogni_tasto_sta_in_piedi(cliente, strada):
    dove = strada
    for pezzo in ("{scatto_id}", "{file_id}", "{nodo_id}", "{persona_id}",
                  "{volto_id}", "{coppia_id}", "{riferimento_id}",
                  "{dispositivo_id}", "{telefono_id}", "{seguito_id}", "{id}"):
        dove = dove.replace(pezzo, "999999")
    if "{" in dove:
        pytest.skip(f"non so cosa mettere in {strada}")

    if strada in COL_JSON:
        risposta = cliente.post(dove, json=COL_JSON[strada], follow_redirects=False)
    else:
        risposta = cliente.post(dove, data=COSA_MANDARE.get(strada, {}),
                                follow_redirects=False)

    if strada in COL_FRENO:
        cliente.post(COL_FRENO[strada], follow_redirects=False)

    assert risposta.status_code < 500, (
        f"«{strada}» si rompe: {risposta.status_code}")
    if strada in COSA_MANDARE or strada in COL_JSON:
        assert risposta.status_code != 422, (
            f"«{strada}» aspetta campi diversi da quelli che manda la pagina")
