from __future__ import annotations

import http.client
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from officina import finestra
from officina.modello import dispositivi
from officina.schermo import porta as porta_mod
from officina.web import origine

pytestmark = pytest.mark.usefixtures("senza_chiavi_delle_prove")

DISPOSITIVO = "192.168.1.40"


def _locale(**parole) -> TestClient:
    from officina.web.server import app

    return TestClient(app, base_url="http://127.0.0.1:8080", client=("127.0.0.1", 51000),
                      follow_redirects=False, **parole)


def _con_la_chiave() -> TestClient:
    cliente = _locale()
    cliente.cookies.set(origine.BISCOTTO_DELLA_FINESTRA, origine.chiave_della_finestra())
    return cliente


def _entrata(dove: str = "/") -> str:
    indirizzo = urlsplit(origine.indirizzo_per_entrare("http://127.0.0.1:8080", dove))
    return f"{indirizzo.path}?{indirizzo.query}"


def test_un_altro_programma_su_questo_computer_non_vede_niente(archivio_pieno):
    cliente = _locale()
    for dove in ("/", "/impostazioni", "/api/in-corso", "/miniatura/1", "/stato"):
        risposta = cliente.get(dove)
        assert risposta.status_code == 403, dove
        assert "sua finestra" in risposta.json()["messaggio"]
    pagina = cliente.get("/", headers={"accept": "text/html"})
    assert pagina.status_code == 403
    assert "sua finestra" in pagina.text
    assert archivio_pieno.dove.nome not in pagina.text


def test_un_altro_programma_su_questo_computer_non_comanda(archivio_pieno):
    risposta = _locale().post("/api/impostazione",
                              data={"chiave": "movimento", "valore": "0"})
    assert risposta.status_code == 403
    assert archivio_pieno.impostazione("movimento") is not False


def test_una_chiave_sbagliata_non_apre(archivio_pieno):
    cliente = _locale()
    cliente.cookies.set(origine.BISCOTTO_DELLA_FINESTRA, "x" * 43)
    assert cliente.get("/").status_code == 403
    assert cliente.get("/entra?t=" + "x" * 43).status_code == 403
    assert origine.BISCOTTO_DELLA_FINESTRA not in cliente.get("/entra").headers.get(
        "set-cookie", "")


def test_la_finestra_entra_col_suo_indirizzo_e_poi_si_muove_libera(archivio_pieno):
    cliente = _locale()
    risposta = cliente.get(_entrata("/stato"))
    assert risposta.status_code == 303
    assert risposta.headers["location"] == "/stato"
    biscotto = risposta.headers["set-cookie"]
    assert biscotto.startswith(origine.BISCOTTO_DELLA_FINESTRA + "=")
    for pezzo in ("HttpOnly", "SameSite=strict", "Path=/"):
        assert pezzo.lower() in biscotto.lower(), pezzo
    assert "max-age" not in biscotto.lower()
    assert cliente.get("/stato").status_code == 200
    assert cliente.get("/api/in-corso").status_code == 200


def test_l_entrata_non_porta_fuori_dal_programma(archivio_pieno):
    cliente = _locale()
    for fuori in ("//truffa.example/x", "https://truffa.example/", "/\\truffa.example"):
        risposta = cliente.get(_entrata(fuori))
        assert risposta.status_code == 303
        assert risposta.headers["location"] == "/", fuori


def test_l_indirizzo_della_finestra_porta_la_chiave_e_la_pagina():
    indirizzo = origine.indirizzo_per_entrare("http://127.0.0.1:8080/")
    pezzi = urlsplit(indirizzo)
    assert pezzi.path == "/entra"
    domanda = parse_qs(pezzi.query)
    assert domanda["t"] == [origine.chiave_della_finestra()]
    assert domanda["vai"] == ["/"]
    assert parse_qs(urlsplit(indirizzo + "benvenuto").query)["vai"] == ["/benvenuto"]
    assert len(origine.chiave_della_finestra()) >= 43


def test_il_browser_di_ripiego_si_apre_con_la_chiave(monkeypatch):
    aperti = []
    monkeypatch.setattr(finestra, "aspetta_che_risponda", lambda porta, host: True)
    monkeypatch.setattr(finestra, "apri", lambda dove: aperti.append(dove) or "finestra")
    assert finestra.apri_quando_e_pronto(8080) == "finestra"
    assert aperti == [origine.indirizzo_per_entrare("http://localhost:8080")]


def test_la_chiave_della_finestra_non_vale_dalla_rete(archivio_pieno):
    from officina.web.server import app

    archivio_pieno.imposta("accesso_dalla_rete", True)
    cliente = TestClient(app, base_url="https://192.168.1.5:8443", client=(DISPOSITIVO, 51000),
                         follow_redirects=False)
    cliente.cookies.set(origine.BISCOTTO_DELLA_FINESTRA, origine.chiave_della_finestra())
    assert cliente.get("/").status_code == 403
    risposta = cliente.get(_entrata())
    assert risposta.status_code == 403
    assert "set-cookie" not in risposta.headers


def test_un_dispositivo_approvato_non_prende_la_chiave_della_finestra(archivio_pieno):
    from officina.web.server import app

    archivio_pieno.imposta("accesso_dalla_rete", True)
    cliente = TestClient(app, base_url="https://192.168.1.5:8443", client=(DISPOSITIVO, 51000),
                         follow_redirects=False)
    cliente.get("/")
    with archivio_pieno.scrittura() as connessione:
        riga = dispositivi.trova(connessione, DISPOSITIVO)
        dispositivi.abbina(connessione, riga["id"], DISPOSITIVO, "segreto-di-prova")
    cliente.cookies.set(dispositivi.BISCOTTO, "segreto-di-prova")
    assert cliente.get("/").status_code == 200
    risposta = cliente.get(_entrata())
    assert risposta.status_code == 403
    assert origine.BISCOTTO_DELLA_FINESTRA not in risposta.headers.get("set-cookie", "")


def test_chi_finge_di_essere_il_portatile_non_passa(archivio_pieno):
    from officina.web.server import app

    finto = TestClient(app, client=("127.0.0.2", 0), follow_redirects=False)
    assert finto.get("/").status_code == 403


@pytest.fixture
def porta_finta(tmp_path, monkeypatch):
    monkeypatch.setenv("OFFICINA_CASA_PROGRAMMA", str(tmp_path / "casa"))
    nuova = porta_mod.Porta()
    monkeypatch.setattr(nuova, "_accendi_il_servitore", lambda: None)
    monkeypatch.setattr(nuova, "_accendi_l_ascolto", lambda: None)
    vecchia, porta_mod.porta = porta_mod.porta, nuova
    yield nuova
    nuova.chiudi()
    porta_mod.porta = vecchia


def test_il_portatile_passa_senza_la_chiave_della_finestra(porta_finta, archivio_pieno):
    porta_finta.apri()
    porta_finta._sessioni["prova"] = porta_mod._Sessione("abc")
    portatile = TestClient(porta_mod.app_della_porta)
    risposta = portatile.get("/stato", headers={"x-schermo-sessione": "prova",
                                                "accept": "text/html"})
    assert risposta.status_code == 200
    assert risposta.headers["cache-control"] == "no-store"
    assert risposta.headers["x-frame-options"] == "DENY"
    senza = TestClient(porta_mod.app_della_porta).get("/stato")
    assert senza.status_code == 401


def test_il_server_vero_vuole_la_chiave_anche_da_questo_computer(archivio_pieno):
    from officina.programma.servitore import Servitore, porta_libera

    servitore = Servitore(porta=porta_libera(0))
    servitore.parti()
    try:
        connessione = http.client.HTTPConnection("127.0.0.1", servitore.porta, timeout=20)
        connessione.request("GET", "/stato", headers={"accept": "text/html"})
        risposta = connessione.getresponse()
        assert risposta.status == 403
        assert "sua finestra" in risposta.read().decode("utf-8")

        connessione.request("GET", _entrata("/stato"))
        risposta = connessione.getresponse()
        risposta.read()
        assert risposta.status == 303
        biscotto = risposta.getheader("set-cookie").split(";", 1)[0]

        connessione.request("GET", "/stato", headers={"accept": "text/html", "cookie": biscotto})
        risposta = connessione.getresponse()
        assert risposta.status == 200
        assert b"Stato" in risposta.read()
        connessione.close()
    finally:
        servitore.ferma()


def test_la_chiave_vive_solo_in_memoria(archivio_pieno, tmp_path):
    from officina.programma import carta

    _locale().get(_entrata())
    chiave = origine.chiave_della_finestra().encode()
    for cartella in (archivio_pieno.dove.radice, carta.casa()):
        for file in cartella.rglob("*"):
            if "registro" in file.parts:
                continue
            if file.is_file() and file.stat().st_size < 50 * 2 ** 20:
                assert chiave not in file.read_bytes(), file


def test_la_chiave_cambia_a_ogni_avvio():
    import subprocess
    import sys

    leggi = [sys.executable, "-c",
             "from officina.web import origine; print(origine.chiave_della_finestra())"]
    prima = subprocess.run(leggi, capture_output=True, text=True, check=True).stdout.strip()
    dopo = subprocess.run(leggi, capture_output=True, text=True, check=True).stdout.strip()
    assert prima and dopo and prima != dopo != origine.chiave_della_finestra()

