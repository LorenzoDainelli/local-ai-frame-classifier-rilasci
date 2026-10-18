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


def _salta(importato, volte, **esito):
    with importato.scrittura() as connessione:
        for _ in range(volte):
            sfida.segna_il_salto(connessione, esito)


def test_la_coda_dice_perche_lucidflux_non_ha_fatto_la_sua_parte(cliente, importato,
                                                                  monkeypatch):
    monkeypatch.setattr(preparazione, "e_pronto", lambda *argomenti: True)
    assert "data-salto-della-sfida" not in _pagina(cliente, "/miglioramento")
    _salta(importato, 1, guasto="memoria_finita", tipo="RamPoca", dove="lucidflux",
           riga="212", spiegazione="Per LucidFlux servono circa 21 GB di RAM libera "
                                   "e ce ne sono 12.")
    testo = _pagina(cliente, "/miglioramento")
    assert "data-salto-della-sfida" in testo
    assert "Sull'ultima foto" in testo and "L'ha fatta solo SeedVR2" in testo
    assert "servono circa 21 GB di RAM libera e ce ne sono 12." in testo
    assert "ce ne sono 12.." not in testo
    assert "Dettaglio tecnico: RamPoca in lucidflux, riga 212" in testo

    assert 'action="/miglioramento/sfida/riprova"' not in testo

    _salta(importato, 1, guasto="memoria_scheda_finita", tipo="OutOfMemoryError",
           dove="lucidflux", riga="340")
    testo = _pagina(cliente, "/miglioramento")
    assert 'Sulle ultime <b class="numeri">2</b> foto' in testo
    assert "Le ha fatte solo SeedVR2" in testo
    assert "Sfida in pausa" not in testo


def test_il_dettaglio_tecnico_mostra_solo_nomi_del_programma():
    from officina.web import miglioramento

    salto = miglioramento.il_salto({"codice": "rotto", "tipo": "C:/Foto/Nonna",
                                    "dove": "lucidflux", "riga": "1"})
    assert salto["tecnico"] == ""
    salto = miglioramento.il_salto({"codice": "rotto", "tipo": "KeyError",
                                    "dove": "mare di Nonna.jpg", "riga": "x"})
    assert salto["tecnico"] == "KeyError"
    salto = miglioramento.il_salto({"codice": "rotto", "tipo": "KeyError",
                                    "dove": "catena", "riga": "C:/x"})
    assert salto["tecnico"] == "KeyError in catena, riga ?"
    assert miglioramento.il_salto(None) is None


def test_dopo_tre_salti_la_coda_dice_che_la_sfida_e_in_pausa_e_si_riprova(
        cliente, importato, monkeypatch):
    from officina.miglioria import lavoro
    from officina.web import miglioramento

    monkeypatch.setattr(preparazione, "e_pronto", lambda *argomenti: True)
    _salta(importato, sfida.PAUSA_DOPO, guasto="memoria_scheda_finita")
    testo = _pagina(cliente, "/miglioramento")
    assert "Sfida in pausa: su <b class=\"numeri\">3</b> foto di fila" in testo
    assert 'action="/miglioramento/sfida/riprova"' in testo

    partito = []
    miglioramento._miglioratore = lavoro.Miglioratore(
        importato, lancia=lambda *argomenti: partito.append(1) or {},
        sfidanti_pronti=lambda: True)
    try:
        risposta = cliente.post("/miglioramento/sfida/riprova", follow_redirects=False)
        assert risposta.status_code == 303
        assert miglioramento._miglioratore.lavoro.aspetta_che_finisca(30)
    finally:
        miglioramento._miglioratore = None
    assert partito == []
    with importato.lettura() as connessione:
        assert sfida.ultimo_salto(connessione) is None
    testo = _pagina(cliente, "/miglioramento")
    assert "data-salto-della-sfida" not in testo and "Sfida in pausa" not in testo


def test_le_foto_da_riprendere_si_vedono_e_fanno_partire_avvia(cliente, importato,
                                                               monkeypatch):
    from prove.test_miglioria_sfida import _fatta_solo_da_seedvr2

    _fatta_solo_da_seedvr2(importato)
    monkeypatch.setattr(preparazione, "e_pronto", lambda *argomenti: True)
    testo = _pagina(cliente, "/miglioramento")
    assert "data-ripresa-della-sfida" in testo
    assert 'LucidFlux deve ancora rifare <b class="numeri">1</b>' in testo
    assert "foto già fatta da SeedVR2" in testo
    assert 'type="submit" disabled>Avvia' not in testo
    assert "premi Avvia" in testo

    _salta(importato, sfida.PAUSA_DOPO, guasto="memoria_scheda_finita")
    testo = _pagina(cliente, "/miglioramento")
    assert "data-ripresa-della-sfida" not in testo
    assert 'type="submit" disabled>Avvia' in testo
