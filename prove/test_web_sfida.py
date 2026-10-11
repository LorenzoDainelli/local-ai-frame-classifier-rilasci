from __future__ import annotations

from pathlib import Path

import pytest

from officina.miglioria import coda, preparazione, sfida
from prove.test_miglioria import _metti, _riga, cartella, importato
from prove.test_miglioria_sfida import _gira_in_sfida, _la_sfida
from prove.test_web_miglioramento import JSON, _pagina, cliente

pytest.importorskip("av")

__all__ = ["cartella", "cliente", "importato"]


@pytest.fixture
def in_sfida(importato):
    _metti(importato, "piccola.jpg")
    _gira_in_sfida(importato)
    return _la_sfida(importato)


def test_la_coda_mostra_la_sfida_quando_ci_sono_tutti_e_due(cliente, monkeypatch):
    assert "Sfida alla cieca" not in _pagina(cliente, "/miglioramento")
    monkeypatch.setattr(preparazione, "e_pronto", lambda *argomenti: True)
    testo = _pagina(cliente, "/miglioramento")
    assert "Sfida alla cieca" in testo and "0 di 100" in testo
    assert "le fanno tutti e due" in testo


def test_la_foto_da_votare_non_si_rivede_e_non_si_approva(cliente, in_sfida):
    testo = _pagina(cliente, "/miglioramento")
    assert 'href="/miglioramento/sfida"' in testo
    assert 'Da votare: <span class="numeri">1</span>' in testo
    assert "Da rivedere <span" not in testo
    rivedi = _pagina(cliente, "/miglioramento/rivedi")
    assert "Non c'è niente da rivedere" in rivedi
    assert "Una foto aspetta il tuo voto" in rivedi and 'href="/miglioramento/sfida"' in rivedi
    risposta = cliente.post(f"/api/miglioramento/{in_sfida['miglioria_id']}/approva",
                            headers=JSON)
    assert risposta.status_code >= 400 and "prima si vota" in risposta.text
    risposta = cliente.post(f"/api/miglioramento/{in_sfida['miglioria_id']}/rifiuta",
                            headers=JSON)
    assert risposta.status_code >= 400
    assert Path(in_sfida["percorso_seedvr2"]).is_file()


def test_la_pagina_del_voto_non_dice_chi_e_chi(cliente, in_sfida):
    testo = _pagina(cliente, "/miglioramento/sfida")
    assert "SeedVR2" not in testo and "LucidFlux" not in testo
    assert "seedvr2" not in testo.lower().replace("/miglioramento", "")
    assert "Lente" in testo and "Nessuna delle due" in testo
    numero = in_sfida["miglioria_id"]
    for lato in ("sinistra", "destra"):
        risposta = cliente.get(f"/miglioramento/{numero}/sfida/{lato}")
        assert risposta.status_code == 200
        lettera = sfida.lettera_del_lato(in_sfida, lato)
        motore = sfida.chi_e(in_sfida, lettera)
        assert risposta.content == Path(in_sfida[f"percorso_{motore}"]).read_bytes()
    assert cliente.get(f"/miglioramento/{numero}/mostra/prima").status_code == 200
    assert cliente.get(f"/miglioramento/{numero}/mostra/dopo").status_code == 404
    assert cliente.get(f"/miglioramento/{numero}/sfida/centro").status_code == 404


def test_votare_passa_la_foto_in_revisione_con_la_versione_scelta(cliente, in_sfida,
                                                                   importato):
    numero = in_sfida["miglioria_id"]
    risposta = cliente.post(f"/api/miglioramento/{numero}/vota", json={"voto": "B"},
                            headers=JSON)
    assert risposta.status_code == 200 and "Nessun file" in risposta.json()["detto"]
    scelto = sfida.chi_e(in_sfida, "B")
    [riga] = _riga(importato, coda.DA_RIVEDERE)
    assert riga["in_revisione"] == in_sfida[f"percorso_{scelto}"]
    assert cliente.get("/miglioramento/sfida", follow_redirects=False).status_code == 303
    assert cliente.get(f"/miglioramento/{numero}/sfida/sinistra").status_code == 404
    assert "Approva" in _pagina(cliente, "/miglioramento/rivedi")
    ripetuto = cliente.post(f"/api/miglioramento/{numero}/vota", json={"voto": "A"},
                            headers=JSON)
    assert ripetuto.status_code >= 400


def test_un_voto_storto_non_rompe_niente(cliente, in_sfida):
    numero = in_sfida["miglioria_id"]
    for corpo in ({"voto": "Z"}, {}, None):
        risposta = cliente.post(f"/api/miglioramento/{numero}/vota", json=corpo,
                                headers=JSON)
        assert 400 <= risposta.status_code < 500


def test_alla_fine_si_vedono_i_nomi_e_si_sceglie_il_principale(cliente, in_sfida,
                                                              importato):
    numero = in_sfida["miglioria_id"]
    cliente.post(f"/api/miglioramento/{numero}/vota", json={"voto": "pari"}, headers=JSON)
    testo = _pagina(cliente, "/miglioramento")
    assert 'href="/miglioramento/sfida/com-e-andata"' in testo
    fine = _pagina(cliente, "/miglioramento/sfida/com-e-andata")
    assert "LucidFlux" in fine and "SeedVR2" in fine and "Sono pari" in fine
    cliente.post("/miglioramento/sfida/chiudi", data={"principale": "lucidflux"})
    assert importato.impostazione("miglioria_foto") == "lucidflux"
    [riga] = _riga(importato, coda.DA_RIVEDERE)
    assert riga["in_revisione"] == in_sfida["percorso_lucidflux"]
    assert "Sfida alla cieca" not in _pagina(cliente, "/miglioramento")
    assert "si usa" in _pagina(cliente, "/miglioramento/sfida/com-e-andata")
    di_nuovo = cliente.post("/miglioramento/sfida/chiudi", data={"principale": "seedvr2"},
                            headers=JSON)
    assert di_nuovo.status_code >= 400


def test_senza_voti_i_risultati_rimandano_alla_coda(cliente):
    risposta = cliente.get("/miglioramento/sfida/com-e-andata", follow_redirects=False)
    assert risposta.status_code == 303
    risposta = cliente.get("/miglioramento/sfida", follow_redirects=False)
    assert risposta.status_code == 303
