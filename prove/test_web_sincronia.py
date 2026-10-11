from __future__ import annotations

import hashlib
import re

import pytest
from fastapi.testclient import TestClient

from officina.archivio.database import adesso, inserisci
from officina.modello import etichette, nodi
from officina.web import sincronia as sincronia_web

PAROLA = "questa-e-una-password"


@pytest.fixture
def cliente(archivio):
    from officina.web.server import app
    return TestClient(app, client=("127.0.0.1", 51000))


def _foto(archivio, cartella, nome: str, contenuto: bytes) -> int:
    connessione = archivio.connessione
    sorgente = cartella / nome
    sorgente.parent.mkdir(parents=True, exist_ok=True)
    sorgente.write_bytes(contenuto)
    impronta = hashlib.blake2b(contenuto, digest_size=32).hexdigest()
    scatto_id = inserisci(
        connessione,
        "INSERT INTO scatti (genere, origine_data, giorno, creato_il) "
        "VALUES ('foto', 'exif', '2026-01-01', ?)", adesso())
    file_id = inserisci(
        connessione,
        "INSERT INTO file_media (impronta, dimensione, genere, formato, "
        "scatto_id, ruolo, aggiunto_il) "
        "VALUES (?, ?, 'immagine', 'jpeg', ?, 'principale', ?)",
        impronta, len(contenuto), scatto_id, adesso())
    inserisci(
        connessione,
        "INSERT INTO percorsi (file_id, percorso, nome, visto_il) "
        "VALUES (?, ?, ?, ?)", file_id, str(sorgente), nome, adesso())
    return scatto_id


def _aspetta(cliente) -> dict:
    for _ in range(200):
        dati = cliente.get("/api/sincronia").json()
        if not dati["sta_lavorando"] and dati["finito"]:
            return dati
        import time
        time.sleep(0.05)
    raise AssertionError("il lavoro non finisce più")


DISPOSITIVI = "/fuori?dove=computer"


def test_la_vecchia_pagina_porta_ai_dispositivi(cliente):
    risposta = cliente.get("/sincronia", follow_redirects=False)
    assert risposta.status_code == 303
    assert risposta.headers["location"] == DISPOSITIVI


def test_la_pagina_si_disegna_e_dice_come_si_chiama_questo_computer(cliente):
    risposta = cliente.get(DISPOSITIVI)
    assert risposta.status_code == 200
    assert "Questo computer" in risposta.text and "Si chiama" in risposta.text
    assert "internet" in risposta.text.lower()


def test_la_pagina_non_chiede_niente_a_internet(cliente):
    testo = cliente.get(DISPOSITIVI).text
    fuori = re.findall(r'(?:src|href)="(https?://[^"]+)"', testo)
    assert fuori == []


def test_la_cartella_si_ricorda(cliente, tmp_path, archivio):
    dove = tmp_path / "pacchetti"
    dove.mkdir()
    risposta = cliente.post("/sincronia/dove", data={"cartella": str(dove)},
                            follow_redirects=False)
    assert risposta.status_code == 303
    with archivio.lettura() as connessione:
        assert sincronia_web.cartella_ricordata(connessione) == str(dove)
    assert str(dove) in cliente.get(DISPOSITIVI).text


def test_senza_cartella_non_parte_e_lo_dice(cliente, archivio):
    risposta = cliente.post("/sincronia/costruisci",
                            data={"password": PAROLA, "ancora": PAROLA},
                            follow_redirects=False)
    assert risposta.status_code >= 400
    assert "cartella" in risposta.text.lower()


def test_le_due_password_diverse_non_fanno_niente(cliente, tmp_path, archivio):
    dove = tmp_path / "pacchetti"
    dove.mkdir()
    cliente.post("/sincronia/dove", data={"cartella": str(dove)})
    risposta = cliente.post("/sincronia/costruisci",
                            data={"password": PAROLA, "ancora": "un-altra-cosa"},
                            follow_redirects=False)
    assert risposta.status_code >= 400
    assert list(dove.iterdir()) == []


def test_il_tasto_fa_il_pacchetto_e_la_pagina_lo_trova(cliente, tmp_path,
                                                       archivio):
    scatto = _foto(archivio, tmp_path / "foto", "una.jpg", b"il contenuto" * 60)
    nodo = nodi.crea(archivio.connessione, "mare")
    etichette.metti(archivio.connessione, scatto, nodo, "si", "utente")

    dove = tmp_path / "pacchetti"
    dove.mkdir()
    cliente.post("/sincronia/dove", data={"cartella": str(dove)})
    cliente.post("/sincronia/costruisci",
                 data={"password": PAROLA, "ancora": PAROLA})
    dati = _aspetta(cliente)

    assert not dati["guasto"], dati["guasto"]
    fatti = [c for c in dove.iterdir() if c.is_dir()]
    assert len(fatti) == 1
    pagina = cliente.get(DISPOSITIVI).text
    assert fatti[0].name in pagina
    assert "Applicalo" in pagina


def test_la_password_non_esce_mai_verso_il_browser(cliente, tmp_path, archivio):
    dove = tmp_path / "pacchetti"
    dove.mkdir()
    cliente.post("/sincronia/dove", data={"cartella": str(dove)})
    cliente.post("/sincronia/costruisci",
                 data={"password": PAROLA, "ancora": PAROLA})
    _aspetta(cliente)

    detto = cliente.get("/api/sincronia").json()
    assert PAROLA not in str(detto)
    assert PAROLA not in cliente.get(DISPOSITIVI).text


def test_un_pacchetto_di_un_altro_archivio_non_si_puo_applicare(cliente,
                                                                tmp_path,
                                                                archivio):
    _foto(archivio, tmp_path / "foto", "una.jpg", b"contenuto" * 60)
    nodi.crea(archivio.connessione, "mare")
    dove = tmp_path / "pacchetti"
    dove.mkdir()
    cliente.post("/sincronia/dove", data={"cartella": str(dove)})
    cliente.post("/sincronia/costruisci",
                 data={"password": PAROLA, "ancora": PAROLA})
    _aspetta(cliente)

    from officina.sincronia import formato
    fatta = [c for c in dove.iterdir() if c.is_dir()][0]
    carta = formato.Carta.leggi(fatta)
    carta.archivio = "vero"
    carta.scrivi(fatta)

    pagina = cliente.get(DISPOSITIVI).text
    assert "altro archivio" in pagina
    assert "Applicalo" not in pagina


def test_la_voce_c_e_nella_barra_di_ogni_pagina(cliente):
    assert 'href="/fuori"' in cliente.get("/").text
    assert "Farne uno da portare di là" in cliente.get("/fuori?dove=computer").text


def test_applicare_chiede_la_password_una_volta_sola(cliente, tmp_path,
                                                     archivio):
    scatto = _foto(archivio, tmp_path / "foto", "una.jpg", b"il contenuto" * 60)
    nodo = nodi.crea(archivio.connessione, "mare")
    etichette.metti(archivio.connessione, scatto, nodo, "si", "utente")

    dove = tmp_path / "pacchetti"
    dove.mkdir()
    cliente.post("/sincronia/dove", data={"cartella": str(dove)})
    cliente.post("/sincronia/costruisci",
                 data={"password": PAROLA, "ancora": PAROLA})
    _aspetta(cliente)
    fatta = [c for c in dove.iterdir() if c.is_dir()][0]

    pagina = cliente.get(DISPOSITIVI).text
    assert 'name="ancora" value=""' not in pagina

    risposta = cliente.post("/sincronia/applica",
                            data={"quale": str(fatta), "password": PAROLA},
                            follow_redirects=False)
    assert risposta.status_code == 303, risposta.text
    dati = _aspetta(cliente)
    assert not dati["guasto"], dati["guasto"]


def test_applicare_senza_password_lo_dice_invece_di_provarci(cliente, tmp_path,
                                                             archivio):
    _foto(archivio, tmp_path / "foto", "una.jpg", b"il contenuto" * 60)
    nodi.crea(archivio.connessione, "mare")
    dove = tmp_path / "pacchetti"
    dove.mkdir()
    cliente.post("/sincronia/dove", data={"cartella": str(dove)})
    cliente.post("/sincronia/costruisci",
                 data={"password": PAROLA, "ancora": PAROLA})
    _aspetta(cliente)
    fatta = [c for c in dove.iterdir() if c.is_dir()][0]

    risposta = cliente.post("/sincronia/applica",
                            data={"quale": str(fatta), "password": ""},
                            follow_redirects=False)
    assert risposta.status_code >= 400
    assert "password" in risposta.text.lower()
