from __future__ import annotations

import hashlib
import re

import numpy as np
import pytest
from fastapi.testclient import TestClient

from officina.descrittori.scaricamento import ScaricamentoFallito
from officina.miglioria import pelle_casi as pc
from officina.miglioria import pelle_corsa as corsa
from officina.miglioria import pelle_fonti as fonti
from officina.miglioria import pelle_gara as gara
from officina.miglioria import pelle_stanza as stanza
from officina.miglioria import pelle_voto as voto
from officina.web.strade import comune
from officina.web.strade import gara_pelle as strade

VOLTO = (0.35, 0.3, 0.3, 0.35)


def test_i_ritratti_sono_fissati_e_liberi():
    assert len(fonti.RITRATTI) == 61
    assert len({r.titolo for r in fonti.RITRATTI}) == 61
    assert len({r.sha256 for r in fonti.RITRATTI}) == 61
    for ritratto in fonti.RITRATTI:
        assert re.fullmatch(r"[0-9a-f]{64}", ritratto.sha256)
        assert ritratto.indirizzo.startswith("https://upload.wikimedia.org/")
        assert "?" not in ritratto.indirizzo
        licenza = ritratto.licenza.lower()
        assert licenza.startswith(("cc0", "cc by", "public domain"))
        assert "nc" not in licenza and "nd" not in licenza
        assert "<" not in ritratto.autore and ritratto.autore
        assert min(ritratto.larghezza, ritratto.altezza) >= 2800
        assert all(0 <= v <= 1 for v in ritratto.volto)


def _finti(monkeypatch, quanti=2):
    dati = {}
    ritratti = []
    for numero in range(quanti):
        contenuto = f"ritratto {numero}".encode()
        dati[f"https://upload.wikimedia.org/{numero}.jpg"] = contenuto
        ritratti.append(fonti.Ritratto(f"File:{numero}.jpg",
                                       f"https://upload.wikimedia.org/{numero}.jpg",
                                       3000, 4000, hashlib.sha256(contenuto).hexdigest(),
                                       len(contenuto), "CC0", "Qualcuno", VOLTO))
    monkeypatch.setattr(fonti, "RITRATTI", tuple(ritratti))
    monkeypatch.setattr(gara, "PAUSA", 0)
    return dati


def test_scarica_controlla_l_impronta_e_non_riscarica(tmp_path, monkeypatch):
    dati = _finti(monkeypatch)
    chiesti = []

    def rete(indirizzo, posto):
        chiesti.append(indirizzo)
        posto.write_bytes(dati[indirizzo])
    passi = []
    gara.scarica_ritratti(tmp_path, lambda f, t: passi.append((f, t)), rete)
    assert len(chiesti) == 2 and passi[-1] == (2, 2)
    gara.scarica_ritratti(tmp_path, None, rete)
    assert len(chiesti) == 2
    assert not list(tmp_path.glob("*.parte"))


def test_scarica_rifiuta_un_ritratto_diverso(tmp_path, monkeypatch):
    _finti(monkeypatch, 1)

    def rete(indirizzo, posto):
        posto.write_bytes(b"altro")
    with pytest.raises(ScaricamentoFallito):
        gara.scarica_ritratti(tmp_path, None, rete)
    assert not list(tmp_path.iterdir())


def test_pesi_nitidi_con_l_impronta_sbagliata_si_buttano(tmp_path, monkeypatch):
    from officina.miglioria import scaricamento

    casa = scaricamento.dove(tmp_path) / scaricamento.PESI
    casa.mkdir(parents=True)

    def da_hf(cartella):
        (cartella / fonti.NITIDO).write_bytes(b"finto")
    monkeypatch.setattr(fonti, "NITIDO_BYTE", 1)
    with pytest.raises(ScaricamentoFallito):
        gara.scarica_i_pesi_nitidi(tmp_path, da_hf=da_hf)
    assert not (casa / fonti.NITIDO).exists()
    monkeypatch.setattr(fonti, "NITIDO_SHA256", hashlib.sha256(b"finto").hexdigest())
    gara.scarica_i_pesi_nitidi(tmp_path, da_hf=da_hf)
    gara.scarica_i_pesi_nitidi(tmp_path, da_hf=lambda c: pytest.fail("riscarica"))


def test_prima_corrono_pochi_molto_difficili():
    casi = gara.ordine()
    assert len(casi) == 61 * 3
    giri = gara.giri(casi)
    assert len(giri[0]) == gara.PRIMO_GIRO
    assert all(c.gruppo == pc.MOLTO_DIFFICILE for c in giri[0])
    assert sum(len(g) for g in giri) == len(casi)
    assert casi == gara.ordine()


def _foto(seme):
    return np.random.default_rng(seme).integers(60, 200, (300, 400, 3), dtype=np.uint8)


def _corri(cartella, casi):
    foto = {}

    def prendi(caso):
        if caso.nome not in foto:
            foto[caso.nome] = _foto(len(foto))
        return pc.prepara(foto[caso.nome], VOLTO, caso)

    def volto(pixel):
        alta, larga = pixel.shape[:2]
        punti = [(larga * 0.4, alta * 0.4), (larga * 0.6, alta * 0.4),
                 (larga * 0.5, alta * 0.5), (larga * 0.42, alta * 0.6),
                 (larga * 0.58, alta * 0.6)]
        return {"punti": punti, "impronta": [1.0, float(pixel.mean()) / 1000]}
    registro = corsa.Risultati(cartella)
    cartella.mkdir(parents=True, exist_ok=True)
    for nome in corsa.CONCORRENTI:
        corsa.fase_base(cartella, registro, casi, prendi, nome,
                        lambda e, w, h: corsa.semplice(e, w, h))
    finiture = {corsa.NESSUNA: lambda e, f: f, corsa.GRANA: stanza.rimetti_la_grana,
                corsa.CF07: lambda e, f: f // 2, corsa.CF10: lambda e, f: f}
    corsa.fase_voti(cartella, registro, casi, prendi, finiture, volto)
    return stanza.salvatore_della_vera(cartella, prendi)


def test_il_voto_e_cieco_stabile_e_la_vera_arriva_dopo(tmp_path):
    casi = [c for c in pc.piano(["File:A.jpg", "File:B.jpg", "File:C.jpg"])]
    salva = _corri(tmp_path, casi)
    registro = voto.leggi_risultati(tmp_path)
    assert len(voto.fatti_del_tutto(registro, casi)) == len(casi)
    dati = voto.aggiorna(tmp_path, registro, casi, salva)
    molto = [c for c in casi if c.gruppo == pc.MOLTO_DIFFICILE]
    assert len(dati["casi"]) == len(molto) and len(dati["scelti"]) == 4
    assert dati["scelti"][0] == f"{corsa.OGGI}|{corsa.CF07}"
    di_nuovo = voto.aggiorna(tmp_path, registro, casi, salva)
    assert di_nuovo["lettere"] == dati["lettere"]
    assert voto.immagine_di(tmp_path, dati, 0, voto.VERA) is None
    assert voto.immagine_di(tmp_path, dati, 0, voto.ENTRATA).is_file()
    for lettera in voto.LETTERE:
        assert voto.immagine_di(tmp_path, dati, 0, lettera).is_file()
    with pytest.raises(KeyError):
        voto.vota(tmp_path, 0, "E")
    dati = voto.vota(tmp_path, 0, "B")
    assert voto.immagine_di(tmp_path, dati, 0, voto.VERA).is_file()
    conto = voto.conto(dati)
    scelto = dati["lettere"][dati["casi"][0]]["B"]
    assert conto["votati"] == 1 and conto["punti"][scelto] == 1


def test_la_grana_resta_della_stessa_misura():
    entrata = _foto(1)[:100, :100]
    fatta = corsa.semplice(entrata, 200, 200)
    finita = stanza.rimetti_la_grana(entrata, fatta)
    assert finita.shape == fatta.shape and finita.dtype == np.uint8


def test_la_stanza_dice_il_guasto_e_il_fatto():
    detti = []
    assert stanza.un_lavoro({"azione": "altro"}, detti.append) == 2
    assert detti[-1] == {"guasto": "azione_sconosciuta"}
    assert stanza.un_lavoro({"azione": stanza.CORSA}, detti.append,
                            lambda lavoro, al_passo: {"fatti": 1}) == 0
    assert detti[-1] == {"fatto": {"fatti": 1}}

    def rotto(lavoro, al_passo):
        raise ValueError("rotto")
    assert stanza.un_lavoro({"azione": stanza.CORSA}, detti.append, rotto) == 1
    assert detti[-1]["guasto"] == "rotto"


@pytest.fixture
def cliente(archivio, monkeypatch, tmp_path):
    from officina.web import server

    monkeypatch.setattr(comune, "piano_pronto", None)
    monkeypatch.setattr(comune, "lavoro", None)
    la = gara.GaraPelle(archivio, cartella=tmp_path / "gara",
                        lancia=lambda lavoro, al_passo: {"guasto": "rotto"})
    monkeypatch.setattr(strade, "_gara", la)
    yield TestClient(server.app, client=("127.0.0.1", 51000))
    la.ferma(5.0)


def test_la_pagina_e_lo_stato_senza_niente(cliente):
    pagina = cliente.get("/gara-pelle")
    assert pagina.status_code == 200
    assert "data-gp-avvia" in pagina.text and "Gara della pelle" in pagina.text
    stato = cliente.get("/api/gara-pelle").json()
    assert stato["fase"] == gara.SCARICO and stato["occupa"] == 0
    assert cliente.get("/api/gara-pelle/voto/0").status_code == 404
    assert cliente.get("/gara-pelle/foto/0/A").status_code == 404
    assert cliente.post("/api/gara-pelle/voto/0", json={"lettera": "A"}).status_code == 404
    assert cliente.post("/api/gara-pelle/ferma", json={}).status_code == 200
    assert cliente.post("/api/gara-pelle/cancella", json={}).json()["tolti"] == 0
    assert 'href="/gara-pelle"' in cliente.get("/impostazioni").text


def test_il_voto_dal_web_e_cieco(cliente, monkeypatch):
    nomi = [r.titolo for r in fonti.RITRATTI[:2]]
    casi = pc.piano(nomi)
    risultati = strade._gara.risultati
    salva = _corri(risultati, casi)
    voto.aggiorna(risultati, voto.leggi_risultati(risultati), casi, salva)
    stato = cliente.get("/api/gara-pelle").json()
    assert stato["fase"] == gara.VOTO and stato["esito"]["conto"]["quanti"] == 2
    caso = cliente.get("/api/gara-pelle/voto/0").json()
    assert caso["lettere"] == list("ABCD") and caso["scelta"] is None and "chi" not in caso
    assert "SeedVR2" not in str(caso)
    assert cliente.get("/gara-pelle/foto/0/vera").status_code == 404
    assert cliente.get("/gara-pelle/foto/0/C").headers["content-type"] == "image/png"
    assert cliente.post("/api/gara-pelle/voto/0", json={"lettera": "E"}).status_code == 400
    votato = cliente.post("/api/gara-pelle/voto/0", json={"lettera": "C"}).json()
    assert votato["scelta"] == "C" and len(votato["chi"]) == 4
    assert cliente.get("/gara-pelle/foto/0/vera").status_code == 200


def test_attesa_segue_il_sito():
    import urllib.error

    adagio = urllib.error.HTTPError("https://upload.wikimedia.org/x.jpg", 429, "Too Many",
                                    {"Retry-After": "7"}, None)
    assert gara._attesa(adagio, 0) == 7.0
    pieno = urllib.error.HTTPError("https://upload.wikimedia.org/x.jpg", 429, "Too Many",
                                   {}, None)
    assert gara._attesa(pieno, 1) == 120.0
    assert gara._attesa(OSError("giù"), 2) == 30.0


def test_se_non_scarica_dice_le_parole_esatte_senza_cartelle(archivio, tmp_path,
                                                              monkeypatch):
    import urllib.error

    _finti(monkeypatch, 1)
    monkeypatch.setattr(gara.time, "sleep", lambda secondi: None)
    tentativi = []

    def rete(indirizzo, posto):
        tentativi.append(indirizzo)
        raise urllib.error.HTTPError(indirizzo, 403, "Forbidden", {}, None)
    la = gara.GaraPelle(archivio, cartella=tmp_path / "gara", rete=rete,
                        da_hf=lambda cartella: None)
    monkeypatch.setattr(la, "_parti_coi_pesi", lambda: None)
    with pytest.raises(ScaricamentoFallito) as preso:
        la._corri()
    assert len(tentativi) == 5
    dettaglio = preso.value.dettaglio
    assert "ritratto pubblico 1 di 1" in dettaglio
    assert "upload.wikimedia.org ha risposto HTTP 403" in dettaglio
    assert str(tmp_path) not in dettaglio


def test_la_corsa_parte_mentre_scaricano_i_pesi(archivio, tmp_path, monkeypatch):
    import threading

    dati = _finti(monkeypatch, 2)
    monkeypatch.setattr(fonti, "NITIDO_BYTE", 1)
    monkeypatch.setattr(fonti, "NITIDO_SHA256", hashlib.sha256(b"finto").hexdigest())
    via = threading.Event()
    corse = []

    def da_hf(cartella):
        assert via.wait(30)
        (cartella / fonti.NITIDO).write_bytes(b"finto")

    def lancia(lavoro, al_passo):
        corse.append((bool(lavoro.get("senza_nitido")), tuple(lavoro["casi"]),
                      gara.pesi_nitidi(archivio.dove.modelli).is_file()))
        via.set()
        return {"fatto": {}}
    la = gara.GaraPelle(archivio, cartella=tmp_path / "gara", lancia=lancia,
                        rete=lambda i, posto: posto.write_bytes(dati[i]), da_hf=da_hf)
    la._corri()
    tutti = gara.giri(gara.ordine())
    primo = tuple(c.chiave for c in tutti[0])
    assert corse[0] == (True, primo, False)
    pieni = [c for c in corse if not c[0]]
    assert [c[1] for c in pieni] == [tuple(c.chiave for c in g) for g in tutti]
    assert all(c[2] for c in pieni)


def test_la_stanza_senza_nitido_non_accende_sharp(monkeypatch, tmp_path):
    accesi = []
    monkeypatch.setattr(stanza, "motore_di",
                        lambda cartella, concorrente: (accesi.append(concorrente)
                                                       or (lambda e, l, a: e), None))
    monkeypatch.setattr(corsa, "fase_base", lambda *a, **k: None)
    monkeypatch.setattr(stanza, "finiture_di",
                        lambda cartella: pytest.fail("i voti aspettano sharp"))
    _finti(monkeypatch, 1)
    esito = stanza.corri({"dati": str(tmp_path), "risultati": str(tmp_path / "r"),
                          "cartella_modelli": str(tmp_path), "casi": [],
                          "senza_nitido": True}, lambda f, t: None)
    assert esito["fatti"] == 0
    assert corsa.AFFILATO not in accesi and corsa.AFFILATO_GRANA not in accesi
