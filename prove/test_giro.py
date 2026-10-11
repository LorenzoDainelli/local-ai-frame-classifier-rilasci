from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def archivio_reale(tmp_path, monkeypatch):
    from officina.archivio import accesso

    monkeypatch.setenv("OFFICINA_ARCHIVIO", str(tmp_path / "archivio"))
    accesso.chiudi(con_copia=False)
    aperto = accesso.apri("reale")
    yield aperto
    accesso.chiudi(con_copia=False)


@pytest.fixture
def cliente(archivio_reale):
    from officina.web import server

    return TestClient(server.app, client=("127.0.0.1", 51000))


@pytest.fixture(autouse=True)
def giro_pulito(archivio_reale):
    from officina.web import giro
    from officina.web.strade import comune

    giro.stato.passo = None
    giro.stato.cartella_foto = None
    giro.stato.lo_ha_fatto_il_giro = False
    yield
    if getattr(comune.lavoro, "ferma", None):
        comune.lavoro.ferma()
    comune.lavoro = None
    giro.stato.passo = None


def test_il_giro_costruisce_le_foto_finte_e_ci_porta_dentro(cliente):
    from officina.archivio import accesso
    from officina.web import giro

    assert accesso.aperto().dove.nome == "reale"

    risposta = cliente.post("/giro/parti", follow_redirects=False)
    assert risposta.status_code == 303
    assert risposta.headers["location"] == "/"

    assert giro.stato.passo == 1
    assert accesso.aperto().dove.nome == "finto"
    assert giro.stato.cartella_foto.exists()


def test_mentre_il_giro_va_si_vede_dove_si_e(cliente):
    cliente.post("/giro/parti", follow_redirects=False)
    pagina = cliente.get("/").text
    assert 'id="assistente"' in pagina, "la fotina del giro non c'è"
    assert 'data-bersaglio="#apri-lente"' in pagina
    assert "archivio finto" in pagina, "non si vede in quale archivio si lavora"


def test_le_tappe_portano_alle_schermate_e_finiscono_coi_tasti(cliente):
    from officina.web import giro

    cliente.post("/giro/parti", follow_redirects=False)
    dove = []
    for _ in range(len(giro.PASSI) - 1):
        risposta = cliente.post("/giro/avanti", follow_redirects=False)
        dove.append(risposta.headers["location"])
    assert dove == ["/", "/officina", "/stato", "/miglioramento", "/impostazioni", "/"]
    assert giro.stato.passo == len(giro.PASSI)
    pagina = cliente.get("/").text
    assert "I tasti da ricordare" in pagina and "<kbd>Ctrl+Z</kbd>" in pagina
    indietro = cliente.post("/giro/indietro", follow_redirects=False)
    assert indietro.headers["location"] == "/impostazioni"


def test_ogni_bersaglio_esiste_nella_sua_pagina(cliente):
    from officina.web import giro

    cliente.post("/giro/parti", follow_redirects=False)
    for passo in giro.PASSI:
        if not passo["bersaglio"]:
            continue
        pagina = cliente.get(passo["dove"]).text
        segno = passo["bersaglio"].split()[0]
        if segno.startswith("#"):
            assert f'id="{segno[1:]}"' in pagina, passo["bersaglio"]
        else:
            assert segno[1:] in pagina, passo["bersaglio"]


def test_uscire_riporta_al_tuo_archivio_e_butta_il_finto(cliente):
    from officina.archivio import accesso
    from officina.web import giro

    cliente.post("/giro/parti", follow_redirects=False)
    foto = giro.stato.cartella_foto
    assert foto.exists()

    risposta = cliente.post("/giro/esci", follow_redirects=False)
    assert risposta.status_code == 303
    assert risposta.headers["location"].startswith("/benvenuto/pronto?giro=finito")

    assert giro.stato.passo is None
    assert accesso.aperto().dove.nome == "reale"
    assert not foto.exists(), "le foto finte sono rimaste sul disco"


def test_un_archivio_finto_gia_tuo_non_viene_buttato(cliente, tmp_path):
    from officina.archivio import accesso
    from officina.impostazioni import posizione
    from officina.web import giro

    prima = accesso.apri("finto")
    prima.imposta("griglia_altezza_riga", 220)
    database = Path(posizione("finto").database)
    accesso.chiudi(con_copia=False)
    accesso.apri("reale")
    assert database.exists()

    cliente.post("/giro/parti", follow_redirects=False)
    assert giro.stato.lo_ha_fatto_il_giro is False
    cliente.post("/giro/esci", follow_redirects=False)

    assert database.exists(), "il giro ha buttato un archivio finto che non era suo"


def test_il_giro_non_parte_mentre_si_sta_importando(cliente, monkeypatch):
    from officina.web.strade import comune

    class FintoLavoro:
        sta_lavorando = True

        def ferma(self, *argomenti, **parole):
            pass

    monkeypatch.setattr(comune, "lavoro", FintoLavoro())
    risposta = cliente.post("/giro/parti", follow_redirects=False)
    assert risposta.status_code != 303
    assert "importazione in corso" in risposta.text


def test_la_fascia_non_c_e_quando_il_giro_non_c_e(cliente):
    pagina = cliente.get("/impostazioni").text
    assert 'id="assistente"' not in pagina
