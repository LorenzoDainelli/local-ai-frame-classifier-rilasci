from __future__ import annotations

import html
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from officina.archivio.database import uno
from officina.importazione import impronta
from officina.miglioria import attesa, coda, da_guardare, preparazione
from prove.test_miglioria import (_gira, _metti, _riga, _scatto_di, cartella,
                                  importato)

pytest.importorskip("av")

JSON = {"Accept": "application/json"}

__all__ = ["cartella", "importato"]


@pytest.fixture
def cliente(importato):
    from officina.web.server import app

    return TestClient(app, client=("127.0.0.1", 51000))


@pytest.fixture
def pronto(monkeypatch):
    monkeypatch.setattr(preparazione, "e_pronto", lambda *argomenti: True)


def _pagina(cliente, dove: str) -> str:
    return html.unescape(cliente.get(dove).text)


def _da_rivedere(importato, genere: str):
    with importato.lettura() as connessione:
        return uno(connessione,
                   "SELECT m.* FROM migliorie AS m JOIN file_media AS f "
                   "ON f.id = m.file_id WHERE m.stato = ? AND f.genere = ?",
                   coda.DA_RIVEDERE, genere)


def test_la_coda_vuota_dice_come_si_comincia(cliente):
    testo = _pagina(cliente, "/miglioramento")
    assert "Niente in coda" in testo
    assert "Migliora" in testo
    assert "SeedVR2" in testo
    assert 'action="/miglioramento/modelli"' in testo
    assert 'class="mg-velato-sotto" inert' in testo
    assert "Avvia</button>" in testo.replace("\n", "").replace("  ", "")


def test_i_modelli_del_miglioramento_si_scaricano_dalla_pagina(cliente, monkeypatch):
    from officina.web.strade import miglioramento

    partiti = []
    monkeypatch.setattr(miglioramento._scaricatore_web(), "parti",
                        lambda quali, dove=None: partiti.append(list(quali)) or True)
    risposta = cliente.post("/miglioramento/modelli", data={"scelti": ["codeformer"]},
                            follow_redirects=False)
    assert risposta.status_code == 303
    assert partiti and partiti[0][0] == "seedvr2" and "codeformer" in partiti[0]
    assert "faceme" not in partiti[0]
    dati = cliente.get("/api/miglioramento/modelli").json()
    assert "percento_tutto" in dati


def test_nel_menu_lavoro_c_e_il_miglioramento(cliente):
    testo = _pagina(cliente, "/miglioramento")
    assert 'href="/miglioramento"' in testo
    assert '<span class="voce-nome">Miglioramento</span>' in testo


def test_migliora_mette_in_coda_e_dice_cosa_ha_scartato(cliente, importato):
    scatti = [_scatto_di(importato, nome)
              for nome in ("piccola.jpg", "grande.jpg", "breve.MOV")]
    risposta = cliente.post("/api/miglioramento/metti", json={"scatti": scatti})
    assert risposta.status_code == 200
    assert risposta.json()["messi"] == 2
    assert "già FHD" in risposta.json()["detto"]

    testo = _pagina(cliente, "/miglioramento")
    assert "piccola.jpg" in testo
    assert "breve.MOV" in testo
    assert "640 × 480" in testo
    assert "1663 × 1247" in testo
    assert "grande.jpg" not in testo


def test_senza_niente_selezionato_lo_dice(cliente):
    risposta = cliente.post("/api/miglioramento/metti", json={"scatti": []},
                            headers=JSON)
    assert risposta.status_code == 400
    assert "selezionato" in risposta.json()["messaggio"]


def test_avvia_senza_seedvr2_rimanda_alla_salute(cliente, importato):
    _metti(importato, "piccola.jpg")
    risposta = cliente.post("/miglioramento/avvia", headers=JSON)
    assert risposta.status_code == 400
    assert "SeedVR2" in risposta.json()["messaggio"]
    assert "La salute" in risposta.json()["messaggio"]
    assert "disabled" in _pagina(cliente, "/miglioramento")


def test_togli_leva_dalla_coda(cliente, importato):
    _metti(importato, "piccola.jpg")
    [riga] = _riga(importato, coda.IN_CODA)
    risposta = cliente.post(f"/miglioramento/{riga['id']}/togli",
                            follow_redirects=False)
    assert risposta.status_code == 303
    assert not _riga(importato, coda.IN_CODA)


def test_una_non_riuscita_si_rimette_in_coda(cliente, importato):
    _metti(importato, "piccola.jpg")
    [riga] = _riga(importato, coda.IN_CODA)
    with importato.scrittura() as connessione:
        coda.segna(connessione, riga["id"], coda.FALLITA,
                   guasto="memoria_scheda_finita")
    testo = _pagina(cliente, "/miglioramento")
    assert "Non riuscite" in testo
    assert "è finita la memoria della scheda video" in testo

    cliente.post(f"/miglioramento/{riga['id']}/rimetti")
    [di_nuovo] = _riga(importato, coda.IN_CODA)
    assert di_nuovo["id"] == riga["id"]
    assert di_nuovo["guasto"] is None


def test_il_menu_conta_quelli_da_rivedere(cliente, importato):
    from officina.web.strade import base

    with importato.lettura() as connessione:
        assert base._conta_la_barra(connessione)["da_rivedere"] == 0
    _metti(importato, "piccola.jpg")
    _gira(importato)
    with importato.lettura() as connessione:
        conti = base._conta_la_barra(connessione)
    assert conti["da_rivedere"] == 1
    stanze = base.barra_di_navigazione("miglioramento", 0, conti)[1]["stanze"]
    [voce] = [s for s in stanze if s["dove"] == "/miglioramento"]
    assert voce["conto"] == 1

    conti["da_rivedere"] = 0
    stanze = base.barra_di_navigazione("miglioramento", 0, conti)[1]["stanze"]
    [voce] = [s for s in stanze if s["dove"] == "/miglioramento"]
    assert voce["conto"] is None


def test_la_foto_si_rivede_affiancata_e_si_approva(cliente, importato, cartella):
    originale = cartella / "2016" / "piccola.jpg"
    prima = impronta.del_file(originale)
    _metti(importato, "piccola.jpg")
    _gira(importato)
    riga = _da_rivedere(importato, "immagine")

    testo = _pagina(cliente, "/miglioramento/rivedi")
    assert f"/miglioramento/{riga['id']}/mostra/prima" in testo
    assert f"/miglioramento/{riga['id']}/mostra/dopo" in testo
    assert "1 di 1" in testo
    assert "Approva" in testo and "Rifiuta" in testo
    assert str(Path("2016") / attesa.ORIGINALI / "piccola.jpg") in testo

    lato = cliente.get(f"/miglioramento/{riga['id']}/mostra/prima")
    assert lato.status_code == 200
    assert lato.content == originale.read_bytes()
    dopo = cliente.get(f"/miglioramento/{riga['id']}/mostra/dopo")
    assert dopo.status_code == 200
    assert dopo.headers["content-type"] == "image/jpeg"

    risposta = cliente.post(f"/api/miglioramento/{riga['id']}/approva", headers=JSON)
    assert risposta.status_code == 200
    assert "Originali" in risposta.json()["detto"]
    assert impronta.del_file(cartella / "2016" / attesa.ORIGINALI / "piccola.jpg") == prima
    assert cliente.get(f"/miglioramento/{riga['id']}/mostra/prima").status_code == 404
    assert "Non c'è niente da rivedere" in _pagina(cliente, "/miglioramento/rivedi")


def test_rifiutare_cancella_la_copia_e_basta(cliente, importato, cartella):
    originale = cartella / "2016" / "piccola.jpg"
    prima = impronta.del_file(originale)
    _metti(importato, "piccola.jpg")
    _gira(importato)
    riga = _da_rivedere(importato, "immagine")

    risposta = cliente.post(f"/api/miglioramento/{riga['id']}/rifiuta", headers=JSON)
    assert risposta.status_code == 200
    assert "mai stato toccato" in risposta.json()["detto"]
    assert not Path(riga["in_revisione"]).exists()
    assert impronta.del_file(originale) == prima


def test_se_l_originale_e_cambiato_l_approvazione_si_ferma_e_lo_dice(
        cliente, importato, cartella):
    originale = cartella / "2016" / "piccola.jpg"
    _metti(importato, "piccola.jpg")
    _gira(importato)
    riga = _da_rivedere(importato, "immagine")
    originale.write_bytes(originale.read_bytes() + b"\0")

    risposta = cliente.post(f"/api/miglioramento/{riga['id']}/approva", headers=JSON)
    assert risposta.status_code == 400
    assert "Nessun file è stato toccato" in risposta.json()["messaggio"]
    assert not (cartella / "2016" / attesa.ORIGINALI).exists()


def test_dopo_passa_alla_prossima_e_poi_ricomincia(cliente, importato):
    _metti(importato, "piccola.jpg", "breve.MOV")
    _gira(importato)
    ids = [riga["id"] for riga in _riga(importato, coda.DA_RIVEDERE)]
    assert len(ids) == 2

    assert "1 di 2" in _pagina(cliente, "/miglioramento/rivedi")
    assert "2 di 2" in _pagina(cliente, f"/miglioramento/rivedi?saltate={ids[0]}")
    tutte = ",".join(str(i) for i in ids)
    assert "1 di 2" in _pagina(cliente, f"/miglioramento/rivedi?saltate={tutte}")


def test_il_video_che_non_parte_ha_la_sua_copia_da_guardare(cliente, importato):
    _metti(importato, "breve.MOV")
    _gira(importato)
    riga = _da_rivedere(importato, "video")
    copia = da_guardare.percorso(importato.dove, riga["id"], da_guardare.PRIMA)
    assert copia.is_file()
    assert da_guardare.si_apre(copia)
    assert not da_guardare.percorso(importato.dove, riga["id"], da_guardare.DOPO).exists()

    testo = _pagina(cliente, "/miglioramento/rivedi")
    assert "<video" in testo
    assert "Audio da" in testo

    pezzo = cliente.get(f"/miglioramento/{riga['id']}/mostra/prima",
                        headers={"Range": "bytes=0-99"})
    assert pezzo.status_code == 206
    assert pezzo.content == copia.read_bytes()[:100]
    assert cliente.get(f"/miglioramento/{riga['id']}/mostra/dopo").status_code == 200

    cliente.post(f"/api/miglioramento/{riga['id']}/rifiuta", headers=JSON)
    assert not copia.exists()


def test_se_la_copia_manca_si_prepara_dalla_revisione(cliente, importato):
    from officina.web import miglioramento

    _metti(importato, "breve.MOV")
    _gira(importato)
    riga = _da_rivedere(importato, "video")
    copia = da_guardare.percorso(importato.dove, riga["id"], da_guardare.PRIMA)
    copia.unlink()

    testo = _pagina(cliente, "/miglioramento/rivedi")
    assert "Prepara la copia" in testo
    assert "<video" not in testo

    risposta = cliente.post(f"/api/miglioramento/{riga['id']}/copie", headers=JSON)
    assert risposta.json()["partito"]
    assert miglioramento.copie.aspetta_che_finisca(60)
    assert cliente.get("/api/miglioramento/copie").json()["finito"]
    assert not miglioramento.copie.guasto
    assert copia.is_file()
    assert "<video" in _pagina(cliente, "/miglioramento/rivedi")


def test_le_copie_di_chi_non_e_piu_da_rivedere_si_puliscono(importato):
    dove = importato.dove
    for miglioria_id in (3, 4):
        arrivo = da_guardare.percorso(dove, miglioria_id, da_guardare.PRIMA)
        arrivo.parent.mkdir(parents=True, exist_ok=True)
        arrivo.write_bytes(b"x")
    assert da_guardare.pulisci(dove, {4}) == 1
    assert not da_guardare.percorso(dove, 3, da_guardare.PRIMA).exists()
    assert da_guardare.percorso(dove, 4, da_guardare.PRIMA).exists()


def test_la_pagina_della_foto_offre_migliora_solo_se_serve(cliente, importato):
    piccola = _scatto_di(importato, "piccola.jpg")
    grande = _scatto_di(importato, "grande.jpg")
    assert 'id="migliora-scatto"' in _pagina(cliente, f"/scatto/{piccola}")
    assert 'id="migliora-scatto"' not in _pagina(cliente, f"/scatto/{grande}")

    cliente.post("/api/miglioramento/metti", json={"scatti": [piccola]})
    testo = _pagina(cliente, f"/scatto/{piccola}")
    assert 'id="migliora-scatto"' not in testo
    assert "in coda per il miglioramento" in testo


def test_le_impostazioni_hanno_i_volti_del_miglioramento(cliente):
    testo = _pagina(cliente, "/impostazioni")
    assert "I volti nel miglioramento" in testo
    assert 'data-chiave="miglioria_volti" data-valore="nessuno"' in testo
    assert 'data-chiave="miglioria_volti" data-valore="codeformer"' in testo


def test_avvia_parte_e_ferma_si_ferma(cliente, importato, pronto, monkeypatch):
    from officina.miglioria import lavoro
    from officina.web import miglioramento

    partito = []

    def lancia(lavoro_da_fare, al_passo, ricorda):
        partito.append(lavoro_da_fare["motori"])
        time.sleep(0.2)
        return {"guasto": "stanza_caduta"}

    miglioramento._miglioratore = lavoro.Miglioratore(importato, lancia=lancia)
    try:
        _metti(importato, "piccola.jpg")
        risposta = cliente.post("/miglioramento/avvia", follow_redirects=False)
        assert risposta.status_code == 303
        assert miglioramento._miglioratore.lavoro.aspetta_che_finisca(30)
        assert partito and partito[0]["foto"] == "seedvr2"
        cliente.post("/miglioramento/ferma")
        assert cliente.get("/api/miglioramento").json()["conti"]["fallita"] == 1
    finally:
        miglioramento._miglioratore = None
