from __future__ import annotations

import io

import numpy as np

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from officina.modello import aiuti, stanze
from officina.stanza import costruzione
from prove.test_costruzione_stanza import ModelliFinti, _foto_dell_archivio, _un_posto_con


@pytest.fixture
def cliente(archivio_pieno):
    from officina.web.server import app

    return TestClient(app, client=("127.0.0.1", 51000))


def _una_foto(percorso, lato=(640, 480), colore=(120, 80, 40)):
    Image.new("RGB", lato, colore).save(percorso, "JPEG", quality=90)
    return percorso


def test_una_foto_di_aiuto_entra_una_volta_sola_e_non_va_nella_galleria(archivio_pieno, tmp_path):
    posto_id = _un_posto_con(archivio_pieno, [], "Camera")
    with archivio_pieno.lettura() as connessione:
        prima = connessione.execute("SELECT count(*) FROM scatti").fetchone()[0]
    foto = _una_foto(tmp_path / "a.jpg")
    assert aiuti.aggiungi(archivio_pieno, foto, "a.jpg", posto_id=posto_id)["messe"] == 1
    di_nuovo = aiuti.aggiungi(archivio_pieno, foto, "a.jpg", posto_id=posto_id)
    assert di_nuovo["messe"] == 0 and di_nuovo["perche"] == "c'era già"
    with archivio_pieno.lettura() as connessione:
        assert connessione.execute("SELECT count(*) FROM scatti").fetchone()[0] == prima
        elenco = aiuti.di_posto(connessione, posto_id)
    assert len(elenco) == 1 and not elenco[0]["in_4k"]
    assert aiuti.percorso(archivio_pieno, elenco[0]).exists()


def test_le_foto_troppo_piccole_o_rotte_si_scartano(archivio_pieno, tmp_path):
    posto_id = _un_posto_con(archivio_pieno, [], "Camera")
    piccola = _una_foto(tmp_path / "p.jpg", (200, 120))
    rotta = tmp_path / "r.jpg"
    rotta.write_bytes(b"non sono una foto")
    assert aiuti.aggiungi(archivio_pieno, piccola, "p.jpg", posto_id=posto_id)["scartate"] == 1
    assert aiuti.aggiungi(archivio_pieno, rotta, "r.jpg", posto_id=posto_id)["scartate"] == 1


def test_una_foto_4k_si_conta_e_togliendola_sparisce_anche_il_file(archivio_pieno, tmp_path):
    posto_id = _un_posto_con(archivio_pieno, [], "Camera")
    aiuti.aggiungi(archivio_pieno, _una_foto(tmp_path / "g.jpg", (3840, 2160)), "g.jpg", posto_id=posto_id)
    with archivio_pieno.lettura() as connessione:
        voce = aiuti.di_posto(connessione, posto_id)[0]
    assert voce["in_4k"] and voce["larghezza"] == 3840
    percorso = aiuti.percorso(archivio_pieno, voce)
    aiuti.togli(archivio_pieno, voce["aiuto_id"])
    assert not percorso.exists()


def test_un_aiuto_e_di_un_luogo_o_di_una_persona(archivio_pieno, tmp_path):
    with pytest.raises(ValueError):
        aiuti.aggiungi(archivio_pieno, _una_foto(tmp_path / "x.jpg"), "x.jpg")


def test_le_foto_di_aiuto_rifanno_la_stanza(archivio_pieno, tmp_path):
    scatti = _foto_dell_archivio(archivio_pieno)[:6]
    posto_id = _un_posto_con(archivio_pieno, scatti, "Cucina")
    costruzione.Passata(archivio_pieno, modelli=ModelliFinti()).esegui()
    with archivio_pieno.lettura() as connessione:
        assert stanze.di_posto(connessione, posto_id)["aiuti_visti"] == 0
        assert (posto_id, "costruisci") not in costruzione.da_fare(connessione)
    for numero in range(2):
        aiuti.aggiungi(archivio_pieno, _una_foto(tmp_path / f"{numero}.jpg", colore=(numero * 90, 60, 30)),
                       f"{numero}.jpg", posto_id=posto_id)
    with archivio_pieno.lettura() as connessione:
        assert (posto_id, "costruisci") in costruzione.da_fare(connessione)
    costruzione.Passata(archivio_pieno, modelli=ModelliFinti()).esegui()
    with archivio_pieno.lettura() as connessione:
        fatta = stanze.di_posto(connessione, posto_id)
        assert fatta["stato"] == stanze.FATTA and fatta["aiuti_visti"] == 2
        assert (posto_id, "costruisci") not in costruzione.da_fare(connessione)


def test_le_strade_caricano_mostrano_e_tolgono_gli_aiuti(archivio_pieno, cliente):
    posto_id = _un_posto_con(archivio_pieno, [], "Camera")
    scritto = io.BytesIO()
    Image.new("RGB", (640, 480), (10, 200, 30)).save(scritto, "JPEG")
    risposta = cliente.post(f"/api/luoghi/luogo/{posto_id}/aiuti",
                            files=[("file", ("uno.jpg", scritto.getvalue(), "image/jpeg")),
                                   ("file", ("due.jpg", b"rotta", "image/jpeg"))])
    assert risposta.status_code == 200
    assert risposta.json()["messe"] == 1 and risposta.json()["scartate"] == 1
    luogo = cliente.get(f"/api/luoghi/luogo/{posto_id}").json()
    assert luogo["stanza"]["stato"] == "da_fare" and len(luogo["stanza"]["aiuti"]) == 1
    aiuto_id = luogo["stanza"]["aiuti"][0]["aiuto_id"]
    miniatura = cliente.get(f"/aiuti/{aiuto_id}/miniatura")
    assert miniatura.status_code == 200 and miniatura.headers["content-type"].startswith("image/")
    assert cliente.post(f"/api/luoghi/aiuto/{aiuto_id}/togli").status_code == 200
    assert cliente.get(f"/aiuti/{aiuto_id}/miniatura").status_code == 404
    assert cliente.get(f"/api/luoghi/luogo/{posto_id}").json()["stanza"]["aiuti"] == []


class _Faccia:
    def __init__(self, riquadro=(0.4, 0.1, 0.2, 0.2)):
        import numpy as np

        self.riquadro, self.area, self.nitidezza, self.sicurezza = riquadro, 0.04, 0.9, 0.95
        self.impronta = np.ones(512, dtype=np.float32) / np.sqrt(512)


class _Corpo:
    def __init__(self, riquadro, quanto=1.0):
        import numpy as np

        from officina.corpi.chi_e import KPR

        self.riquadro, self.maschera = riquadro, b""
        self.area = riquadro[2] * riquadro[3]
        self.aspetto = {nome: (np.full((1, 8), quanto, dtype=np.float32), np.ones(1)) for nome in KPR}
        self.vestiti = np.full(16, quanto, dtype=np.float32)


class _Volti:
    versione = "finta"

    def __init__(self, facce):
        self.facce = facce

    def guarda(self, immagine):
        return self.facce

    def spegni(self):
        pass


class _Corpi:
    versione = "finto"

    def __init__(self, corpi):
        self.corpi = corpi

    def guarda(self, immagine):
        return self.corpi

    def spegni(self):
        pass


def _una_persona(archivio, nome="Anna"):
    from officina.archivio.database import adesso

    with archivio.scrittura() as connessione:
        return connessione.execute(
            "INSERT INTO persone (nome, stato, nata_il) VALUES (?, 'attiva', ?)", (nome, adesso())).lastrowid


def test_le_foto_di_aiuto_di_una_persona_danno_volto_corpo_e_vestiti(archivio_pieno, tmp_path):
    from officina.corpi import VESTITI, aiuti_persona, chi_e

    persona_id = _una_persona(archivio_pieno)
    aiuti.aggiungi(archivio_pieno, _una_foto(tmp_path / "a.jpg"), "a.jpg", persona_id=persona_id)
    lontano, vicino = _Corpo((0.0, 0.0, 0.3, 0.9), 0.5), _Corpo((0.35, 0.05, 0.3, 0.9), 1.0)
    fatto = aiuti_persona.Passata(archivio_pieno, volti=_Volti([_Faccia()]), rilevatore=_Corpi([lontano, vicino]),
                                  figure=None).esegui()
    assert (fatto.fatti, fatto.volti, fatto.corpi) == (1, 1, 1)
    with archivio_pieno.lettura() as connessione:
        assert connessione.execute("SELECT count(*) FROM volti_riferimento WHERE persona_id = ?",
                                   (persona_id,)).fetchone()[0] == 1
        vestiti = connessione.execute("SELECT vettore FROM aspetti_di_aiuto WHERE modello = ?", (VESTITI,)).fetchone()[0]
        assert np.frombuffer(vestiti, dtype="<f4")[0] == pytest.approx(1.0)
        riferimento, segmenti = chi_e.riferimenti(connessione, {persona_id: []})
        a, b = segmenti[persona_id]
        assert b - a == 1 and riferimento.ids[a] < 0 and riferimento.presenti[chi_e._nome_del_vettore(VESTITI)][a]
        assert aiuti_persona.quanti_di_persona(connessione, persona_id) == {"tutte": 1, "guardate": 1,
                                                                            "con_il_corpo": 1}
    di_nuovo = aiuti_persona.Passata(archivio_pieno, volti=_Volti([_Faccia()]), rilevatore=_Corpi([vicino]),
                                     figure=None).esegui()
    assert di_nuovo.totale == 0


def test_con_piu_facce_non_si_impara_il_volto_e_togliendo_l_aiuto_sparisce_tutto(archivio_pieno, tmp_path):
    from officina.corpi import aiuti_persona

    persona_id = _una_persona(archivio_pieno)
    aiuti.aggiungi(archivio_pieno, _una_foto(tmp_path / "a.jpg"), "a.jpg", persona_id=persona_id)
    aiuti_persona.Passata(archivio_pieno, volti=_Volti([_Faccia(), _Faccia((0.0, 0.0, 0.1, 0.1))]),
                          rilevatore=_Corpi([_Corpo((0.1, 0.1, 0.3, 0.8))]), figure=None).esegui()
    with archivio_pieno.lettura() as connessione:
        assert connessione.execute("SELECT count(*) FROM volti_riferimento").fetchone()[0] == 0
        aiuto_id = aiuti.di_persona(connessione, persona_id)[0]["aiuto_id"]
        assert connessione.execute("SELECT count(*) FROM aspetti_di_aiuto").fetchone()[0] > 0
    aiuti.togli(archivio_pieno, aiuto_id)
    with archivio_pieno.lettura() as connessione:
        assert connessione.execute("SELECT count(*) FROM aspetti_di_aiuto").fetchone()[0] == 0


def test_la_pagina_della_persona_mostra_le_foto_di_aiuto(archivio_pieno, cliente):
    persona_id = _una_persona(archivio_pieno)
    scritto = io.BytesIO()
    Image.new("RGB", (640, 480), (200, 30, 30)).save(scritto, "JPEG")
    risposta = cliente.post(f"/api/persone/{persona_id}/aiuti",
                            files=[("file", ("uno.jpg", scritto.getvalue(), "image/jpeg"))])
    assert risposta.json()["messe"] == 1
    pagina = cliente.get(f"/persone/{persona_id}")
    assert pagina.status_code == 200 and "Foto di aiuto" in pagina.text and "/aiuti/" in pagina.text
