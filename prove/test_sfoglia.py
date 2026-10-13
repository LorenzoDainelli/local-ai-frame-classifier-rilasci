from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from officina.web import sfoglia


@pytest.fixture
def da_questa_macchina(archivio_pieno):
    from officina.web.server import app

    return TestClient(app, client=("127.0.0.1", 51000))


@pytest.fixture
def dallo_zenbook(archivio_pieno):
    from officina.web.server import app

    archivio_pieno.imposta("accesso_dalla_rete", 1)
    return TestClient(app, client=("192.168.1.42", 51000))


def test_da_fuori_la_finestra_non_si_apre(dallo_zenbook, monkeypatch):
    def non_deve_succedere(*_a, **_k):
        raise AssertionError("ha aperto una finestra per chi non è qui")

    monkeypatch.setattr(sfoglia, "scegli_cartella", non_deve_succedere)
    risposta = dallo_zenbook.post("/api/sfoglia-cartella", data={"da_dove": ""})
    assert risposta.status_code >= 400
    assert "computer" in risposta.text


def test_il_tasto_non_compare_a_chi_non_puo_premerlo(dallo_zenbook):
    pagina = dallo_zenbook.get("/importazione").text
    assert "data-sfoglia" not in pagina


def test_da_questa_macchina_il_tasto_c_e(da_questa_macchina, monkeypatch):
    monkeypatch.setattr(sfoglia, "si_puo", lambda: True)
    pagina = da_questa_macchina.get("/importazione").text
    assert "data-sfoglia" in pagina


def test_senza_tkinter_il_tasto_non_c_e(da_questa_macchina, monkeypatch):
    monkeypatch.setattr(sfoglia, "si_puo", lambda: False)
    pagina = da_questa_macchina.get("/importazione").text
    assert "data-sfoglia" not in pagina
    assert 'name="percorso"' in pagina


def test_annullare_non_e_un_errore(da_questa_macchina, monkeypatch):
    monkeypatch.setattr(sfoglia, "si_puo", lambda: True)
    monkeypatch.setattr(sfoglia, "scegli_cartella", lambda _d=None: None)
    risposta = da_questa_macchina.post("/api/sfoglia-cartella", data={"da_dove": ""})
    assert risposta.status_code == 200
    assert risposta.json() == {"percorso": None}


def test_la_cartella_scelta_torna_indietro(da_questa_macchina, monkeypatch):
    monkeypatch.setattr(sfoglia, "si_puo", lambda: True)
    monkeypatch.setattr(sfoglia, "scegli_cartella",
                        lambda _d=None: r"C:\Users\qualcuno\Foto")
    risposta = da_questa_macchina.post("/api/sfoglia-cartella", data={"da_dove": ""})
    assert risposta.json() == {"percorso": r"C:\Users\qualcuno\Foto"}


def test_due_clic_non_aprono_due_finestre(da_questa_macchina, monkeypatch):
    monkeypatch.setattr(sfoglia, "si_puo", lambda: True)

    def gia_aperta(_d=None):
        raise sfoglia.GiaAperta()

    monkeypatch.setattr(sfoglia, "scegli_cartella", gia_aperta)
    risposta = da_questa_macchina.post("/api/sfoglia-cartella", data={"da_dove": ""})
    assert risposta.status_code >= 400
    assert "dietro" in risposta.text


def test_il_lucchetto_lascia_passare_uno_solo(monkeypatch):
    dentro = []

    class FintoFinito:
        returncode = 0
        stdout = ""

    def finta_finestra(*_a, **_k):
        dentro.append(1)
        with pytest.raises(sfoglia.GiaAperta):
            sfoglia.scegli_cartella()
        return FintoFinito()

    monkeypatch.setattr(sfoglia.subprocess, "run", finta_finestra)
    assert sfoglia.scegli_cartella() is None
    assert dentro == [1], "la seconda chiamata non è nemmeno arrivata"

    monkeypatch.setattr(sfoglia.subprocess, "run",
                        lambda *_a, **_k: type("F", (), {"returncode": 0,
                                                         "stdout": "/tmp/x"})())
    assert sfoglia.scegli_cartella() == "/tmp/x"


def test_una_finestra_che_non_parte_non_ferma_niente(monkeypatch):
    for guaio in (OSError("niente python"),
                  sfoglia.subprocess.TimeoutExpired("py", sfoglia.ATTESA)):
        def scoppia(*_a, **_k):
            raise guaio

        monkeypatch.setattr(sfoglia.subprocess, "run", scoppia)
        assert sfoglia.scegli_cartella() is None


def test_una_cartella_che_non_c_e_si_dice_nel_riquadro(da_questa_macchina, tmp_path):
    scritto = str(tmp_path / "Imagini")
    risposta = da_questa_macchina.post(
        "/importazione/cartella", data={"percorso": scritto},
        headers={"Accept": "application/json"})
    assert risposta.status_code == 400
    messaggio = risposta.json()["messaggio"]
    assert "non c'è" in messaggio
    assert scritto in messaggio


def test_un_file_non_e_una_cartella(da_questa_macchina, tmp_path):
    file = tmp_path / "foto.jpg"
    file.write_bytes(b"finta")
    risposta = da_questa_macchina.post(
        "/importazione/cartella", data={"percorso": str(file)},
        headers={"Accept": "application/json"})
    assert risposta.status_code == 400
    assert "è un file" in risposta.json()["messaggio"]


def test_le_cartelle_scelte_stanno_nel_riquadro(da_questa_macchina, monkeypatch):
    monkeypatch.setattr(sfoglia, "si_puo", lambda: True)
    pagina = da_questa_macchina.get("/importazione").text
    riquadro = pagina.split("data-cartella-nuova-riquadro", 1)[1].split("data-a-mano", 1)[0]
    assert "cn-elenco" in riquadro
    assert "Scegli" in riquadro
