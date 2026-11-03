from __future__ import annotations

import html
import time
from pathlib import Path

import pytest

from officina import registro
from officina.miglioria import (catena, coda, lavoro, motori, pezzi, ram, rete,
                               seedvr2_blocchi, stanza)
from prove.test_miglioria import SCELTI, _metti, _riga, cartella, importato
from prove.test_web_miglioramento import cliente

__all__ = ["cartella", "cliente", "importato"]

G = 2 ** 30


def _aspetta(condizione, quanto: float = 30.0) -> None:
    scadenza = time.monotonic() + quanto
    while not condizione():
        assert time.monotonic() < scadenza, "non è successo"
        time.sleep(0.01)


class _Stanza:

    def __init__(self, *esiti: dict) -> None:
        self.esiti = list(esiti)
        self.lavori: list[dict] = []

    def __call__(self, lavoro_da_fare, al_passo, ricorda) -> dict:
        self.lavori.append(lavoro_da_fare)
        esito = self.esiti.pop(0)
        if "fatto" in esito:
            Path(lavoro_da_fare["uscita"]).write_bytes(b"migliorata")
        return esito


def _poca(codice: str = lavoro.RAM_POCA, serve: int = 20 * G, libera: int = 10 * G) -> dict:
    return {"guasto": codice, "serve": serve, "libera": libera, "spiegazione": "poca"}


FATTO = {"fatto": {"larghezza": 1663, "altezza": 1247,
                   "motori": [{"nome": "finto", "versione": "x"}]}}
ROTTO = {"guasto": "rotto"}


@pytest.fixture
def svelto(monkeypatch):
    monkeypatch.setattr(lavoro, "OGNI_QUANTO_LA_RAM", 0.01)
    libere: list = []

    def libera():
        return libere.pop(0) if len(libere) > 1 else (libere[0] if libere else 10 * G)

    monkeypatch.setattr(ram, "libera", libera)
    return libere


def _parti(archivio, stanza_finta) -> lavoro.Miglioratore:
    miglioratore = lavoro.Miglioratore(archivio, lancia=stanza_finta, motori_scelti=SCELTI,
                                       sfidanti_pronti=lambda: False)
    assert miglioratore.parti()
    return miglioratore


def _fine(miglioratore) -> None:
    assert miglioratore.lavoro.aspetta_che_finisca(60)
    assert not miglioratore.lavoro.guasto, list(miglioratore.lavoro.righe)[-6:]
    assert not miglioratore.lavoro.guasto, miglioratore.lavoro.guasto


def _chiede(miglioratore) -> dict:
    _aspetta(lambda: "ram" in miglioratore.adesso)
    return miglioratore.adesso["ram"]


def test_la_stanza_manda_quanta_ram_serve(monkeypatch):
    def esegui(*_argomenti):
        raise seedvr2_blocchi.DiscoNonBasta(20 * G, 10 * G)

    monkeypatch.setattr(catena, "esegui", esegui)
    monkeypatch.setattr(rete, "chiudi", lambda: None)
    mandati: list = []
    assert stanza.un_lavoro({"genere": "immagine", "originale": None}, mandati.append,
                            None) == 1
    assert mandati[-1] == {"guasto": "ram_poca_anche_col_disco", "serve": 20 * G,
                           "libera": 10 * G, "spiegazione": (
                               "Per SeedVR2 servono almeno 20 GB di RAM libera e ce ne "
                               "sono 10.")}


def test_un_altro_errore_della_stanza_non_porta_numeri(monkeypatch):
    from officina.errori import ErroreOfficina

    def esegui(*_argomenti):
        raise ErroreOfficina("no", codice="rotto")

    monkeypatch.setattr(catena, "esegui", esegui)
    monkeypatch.setattr(rete, "chiudi", lambda: None)
    mandati: list = []
    stanza.un_lavoro({"genere": "immagine", "originale": None}, mandati.append, None)
    assert mandati[-1] == {"guasto": "rotto"}


def test_la_ram_poca_rimette_in_coda_e_chiede(importato, svelto, monkeypatch):
    avvisi: list = []
    monkeypatch.setattr(registro, "avviso",
                        lambda nome, **campi: avvisi.append((nome, campi)))
    _metti(importato, "piccola.jpg")
    finta = _Stanza(_poca(serve=20 * G + 1), FATTO)
    miglioratore = _parti(importato, finta)
    assert _chiede(miglioratore) == {"serve": 21, "libera": 10, "anche_col_disco": False,
                                     "disco": False, "aspetto": False}
    assert miglioratore.adesso["nome"] == "piccola.jpg"
    [riga] = _riga(importato, coda.IN_CODA)
    assert riga["guasto"] == "ram_poca"
    assert ("miglioria.ram_poca", {"motivo": registro.Parola("ram_poca"),
                                   "serve_gb": 20.0, "libera_gb": 10.0}) in avvisi
    assert any("piccola.jpg»: per SeedVR2 la RAM libera non basta. Aspetto che si liberi, "
               "o che tu scelga di usare il disco" in riga
               for riga in miglioratore.lavoro.righe)
    time.sleep(0.1)
    assert len(finta.lavori) == 1
    miglioratore.ferma()
    _fine(miglioratore)
    [riga] = _riga(importato, coda.IN_CODA)
    assert riga["guasto"] == "ram_poca" and miglioratore.adesso == {}


def test_aspetto_lo_dice_e_quando_la_ram_si_libera_riparte(importato, svelto):
    _metti(importato, "piccola.jpg")
    finta = _Stanza(_poca(), FATTO)
    miglioratore = _parti(importato, finta)
    _chiede(miglioratore)
    assert miglioratore.rispondi_per_la_ram("aspetto") is True
    _aspetta(lambda: miglioratore.adesso.get("ram", {}).get("aspetto"))
    assert len(finta.lavori) == 1
    svelto.extend([20 * G - 1, 20 * G])
    _fine(miglioratore)
    assert len(finta.lavori) == 2
    assert "disco" not in finta.lavori[1]["opzioni"]
    assert _riga(importato, coda.DA_RIVEDERE)
    assert "la RAM si è liberata: riprendo" in miglioratore.lavoro.righe
    assert miglioratore.adesso == {}


def test_usa_il_disco_riparte_subito_e_vale_per_tutto_il_giro(importato, svelto,
                                                               monkeypatch):
    eventi: list = []
    monkeypatch.setattr(registro, "evento", lambda nome, **campi: eventi.append(nome))
    _metti(importato, "piccola.jpg", "breve.MOV")
    finta = _Stanza(_poca(), FATTO, ROTTO, ROTTO)
    miglioratore = _parti(importato, finta)
    _chiede(miglioratore)
    monkeypatch.setattr(lavoro, "OGNI_QUANTO_LA_RAM", 60.0)
    time.sleep(0.1)
    assert miglioratore.rispondi_per_la_ram("disco") is True
    _fine(miglioratore)
    assert [lavoro_.get("opzioni", {}).get("disco") for lavoro_ in finta.lavori] == [
        None, True, True]
    assert "miglioria.ram_col_disco" in eventi
    assert ("una parte dei pesi di SeedVR2 resta sul disco, fino alla fine del giro"
            in miglioratore.lavoro.righe)
    with importato.scrittura() as connessione:
        connessione.execute("UPDATE migliorie SET stato = 'in_coda' WHERE stato = 'fallita'")
    assert miglioratore.parti()
    _fine(miglioratore)
    assert len(finta.lavori) == 4 and "disco" not in finta.lavori[3]["opzioni"]


def test_se_anche_col_disco_non_basta_aspetta_soltanto(importato, svelto):
    _metti(importato, "piccola.jpg")
    svelto.append(5 * G)
    finta = _Stanza(_poca(lavoro.RAM_POCA_COL_DISCO, serve=6 * G, libera=5 * G), FATTO)
    miglioratore = _parti(importato, finta)
    assert _chiede(miglioratore)["anche_col_disco"] is True
    assert miglioratore.rispondi_per_la_ram("disco") is True
    time.sleep(0.1)
    assert len(finta.lavori) == 1 and "ram" in miglioratore.adesso
    [riga] = _riga(importato, coda.IN_CODA)
    assert riga["guasto"] == "ram_poca_anche_col_disco"
    assert not any("o che tu scelga" in riga for riga in miglioratore.lavoro.righe)
    svelto.append(6 * G)
    _fine(miglioratore)
    assert len(finta.lavori) == 2 and "disco" not in finta.lavori[1]["opzioni"]


def test_col_disco_gia_scelto_il_riquadro_lo_sa(importato, svelto):
    _metti(importato, "piccola.jpg")
    finta = _Stanza(_poca(), _poca(lavoro.RAM_POCA_COL_DISCO), FATTO)
    miglioratore = _parti(importato, finta)
    _chiede(miglioratore)
    miglioratore.rispondi_per_la_ram("disco")
    _aspetta(lambda: len(finta.lavori) == 2)
    _aspetta(lambda: miglioratore.adesso.get("ram", {}).get("anche_col_disco"))
    assert miglioratore.adesso["ram"]["disco"] is True
    svelto.append(30 * G)
    _fine(miglioratore)
    assert finta.lavori[2]["opzioni"]["disco"] is True


def test_senza_sapere_quanta_ne_serve_non_riparte_da_sola(importato, svelto):
    _metti(importato, "piccola.jpg")
    finta = _Stanza({"guasto": lavoro.RAM_POCA, "serve": "tanta", "libera": True}, FATTO)
    miglioratore = _parti(importato, finta)
    assert _chiede(miglioratore)["serve"] == 0
    svelto.append(99 * G)
    time.sleep(0.1)
    assert len(finta.lavori) == 1
    miglioratore.ferma()
    _fine(miglioratore)


def test_senza_misurare_la_ram_aspetta_la_risposta(importato, svelto, monkeypatch):
    monkeypatch.setattr(ram, "libera", lambda: None)
    _metti(importato, "piccola.jpg")
    finta = _Stanza(_poca(), FATTO)
    miglioratore = _parti(importato, finta)
    _chiede(miglioratore)
    time.sleep(0.1)
    assert len(finta.lavori) == 1
    miglioratore.rispondi_per_la_ram("disco")
    _fine(miglioratore)
    assert len(finta.lavori) == 2


def test_ferma_sveglia_subito_l_attesa(importato, svelto, monkeypatch):
    monkeypatch.setattr(lavoro, "OGNI_QUANTO_LA_RAM", 60.0)
    _metti(importato, "piccola.jpg")
    miglioratore = _parti(importato, _Stanza(_poca()))
    _chiede(miglioratore)
    partito = time.monotonic()
    miglioratore.ferma()
    _fine(miglioratore)
    assert time.monotonic() - partito < 10


def test_una_risposta_strana_non_vale(importato):
    miglioratore = lavoro.Miglioratore(importato, motori_scelti=SCELTI)
    assert miglioratore.rispondi_per_la_ram("forse") is False
    assert miglioratore._scelta is None and not miglioratore._risposta.is_set()


def test_i_pezzi_del_video_restano_quando_la_ram_non_basta(importato, svelto, monkeypatch):
    buttati: list = []
    monkeypatch.setattr(pezzi, "butta", buttati.append)
    monkeypatch.setattr(pezzi, "butta_quelli_di", lambda *a: buttati.append(a))
    _metti(importato, "breve.MOV")
    miglioratore = _parti(importato, _Stanza(_poca(), _poca(lavoro.RAM_POCA_COL_DISCO)))
    _chiede(miglioratore)
    miglioratore.rispondi_per_la_ram("disco")
    _aspetta(lambda: miglioratore.adesso.get("ram", {}).get("anche_col_disco"))
    miglioratore.ferma()
    _fine(miglioratore)
    assert buttati == []


def test_nella_sfida_la_ram_poca_butta_le_versioni_e_chiede(importato, svelto, monkeypatch):
    from officina.miglioria import sfida

    buttate: list = []
    monkeypatch.setattr(sfida, "butta", buttate.append)
    _metti(importato, "piccola.jpg")
    finta = _Stanza(_poca(), FATTO, FATTO)
    miglioratore = lavoro.Miglioratore(importato, lancia=finta, motori_scelti=SCELTI,
                                       sfidanti_pronti=lambda: True)
    assert miglioratore.parti()
    _chiede(miglioratore)
    assert buttate == [[]]
    [riga] = _riga(importato, coda.IN_CODA)
    assert riga["guasto"] == "ram_poca"
    miglioratore.rispondi_per_la_ram("disco")
    _fine(miglioratore)
    assert [lavoro_["motori"]["foto"] for lavoro_ in finta.lavori] == [
        motori.SEEDVR2, motori.SEEDVR2, motori.LUCIDFLUX]
    assert all(lavoro_["opzioni"].get("disco") for lavoro_ in finta.lavori[1:])


def test_fermare_mentre_aspetta_non_riprende(importato, svelto, monkeypatch):
    _metti(importato, "piccola.jpg")
    finta = _Stanza(_poca(), FATTO)
    miglioratore = _parti(importato, finta)
    _chiede(miglioratore)
    monkeypatch.setattr(lavoro, "OGNI_QUANTO_LA_RAM", 60.0)
    time.sleep(0.1)
    svelto[:] = [30 * G]
    miglioratore.ferma()
    _fine(miglioratore)
    assert "la RAM si è liberata: riprendo" not in miglioratore.lavoro.righe
    assert len(finta.lavori) == 1


def test_dopo_una_risposta_non_gira_a_vuoto(importato, svelto, monkeypatch):
    chiamate: list = []
    monkeypatch.setattr(ram, "libera", lambda: chiamate.append(1) or 10 * G)
    _metti(importato, "piccola.jpg")
    miglioratore = _parti(importato, _Stanza(_poca(), FATTO))
    _chiede(miglioratore)
    monkeypatch.setattr(lavoro, "OGNI_QUANTO_LA_RAM", 60.0)
    time.sleep(0.1)
    miglioratore.rispondi_per_la_ram("aspetto")
    _aspetta(lambda: miglioratore.adesso.get("ram", {}).get("aspetto"))
    gia = len(chiamate)
    time.sleep(0.3)
    assert len(chiamate) == gia
    miglioratore.ferma()
    _fine(miglioratore)


def test_ogni_volta_che_chiede_dimentica_la_risposta_di_prima(importato, monkeypatch):
    miglioratore = lavoro.Miglioratore(importato, motori_scelti=SCELTI)
    attese: list = []

    def aspetta(serve, anche):
        attese.append((miglioratore._scelta, miglioratore._risposta.is_set()))

    monkeypatch.setattr(miglioratore, "_aspetta_la_ram", aspetta)
    _metti(importato, "piccola.jpg")
    [riga] = _riga(importato, coda.IN_CODA)
    miglioratore._scelta = "aspetto"
    miglioratore._risposta.set()
    miglioratore._ram_poca(riga["id"], Path("piccola.jpg"), _poca())
    assert attese == [(None, False)] and miglioratore.adesso == {}


def test_ogni_dieci_secondi_guarda_la_ram():
    assert lavoro.OGNI_QUANTO_LA_RAM == 10.0


def test_i_numeri_strani_valgono_zero():
    assert lavoro._byte(True) == 0 and lavoro._byte("5") == 0 and lavoro._byte(None) == 0
    assert lavoro._byte(-3) == 0 and lavoro._byte(2.7) == 2 and lavoro._byte(7) == 7


def test_i_due_messaggi_della_ram():
    assert lavoro.a_parole(lavoro.RAM_POCA) == "per SeedVR2 la RAM libera non basta"
    assert lavoro.a_parole(lavoro.RAM_POCA_COL_DISCO) == (
        "per SeedVR2 la RAM libera non basta, anche tenendo una parte dei pesi sul disco")


def test_i_giga_a_parole():
    assert lavoro.in_giga(int(4.56 * G)) == 4.6
    assert lavoro.giga_in_su(20 * G) == 20 and lavoro.giga_in_su(20 * G + 1) == 21
    assert lavoro.giga_in_su(0) == 0


def test_la_riga_dei_pesi_di_seedvr2(monkeypatch):
    eventi: list = []
    monkeypatch.setattr(registro, "evento",
                        lambda nome, **campi: eventi.append((nome, campi)))
    fatto = {"motori": [{"nome": "seedvr2", "versione": "x"}, {"nome": "codeformer"}],
             "dove_stanno": {"scheda": 4.5, "ram": 8.0, "disco": 4.04}, "secondi": 3.0}
    assert lavoro.misura_del_motore(fatto) == (
        " (SeedVR2: scheda 4,5 GB · RAM 8 GB · disco 4 GB)")
    assert eventi == [("miglioria.seedvr2_pesi", {"scheda": 4.5, "ram": 8.0, "disco": 4.04})]
    assert lavoro.misura_di_seedvr2({"dove_stanno": {"ram": 1}}) == (
        " (SeedVR2: scheda 0 GB · RAM 1 GB · disco 0 GB)")
    assert lavoro.misura_di_seedvr2({"dove_stanno": {"ram": None, "disco": 2}}) == (
        " (SeedVR2: scheda 0 GB · RAM 0 GB · disco 2 GB)")
    assert lavoro.misura_di_seedvr2({"dove_stanno": None}) == ""
    assert lavoro.misura_di_seedvr2({"dove_stanno": [("ram", 1)]}) == ""
    assert lavoro.misura_del_motore({"motori": [{"nome": "seedvr2"}]}) == ""


def test_gli_altri_motori_dicono_la_misura_di_lucidflux():
    stanno = {"secondi": 61.0, "dove_stanno": {"scheda": 1.0, "ram": 0.0, "disco": 2.0}}
    atteso = lavoro.misura_di_lucidflux(stanno)
    assert atteso
    assert lavoro.misura_del_motore({**stanno, "motori": [{"nome": "lucidflux"}]}) == atteso
    assert lavoro.misura_del_motore({**stanno, "motori": ["seedvr2"]}) == atteso
    assert lavoro.misura_del_motore({**stanno, "motori": [{"nome": "codeformer"},
                                                          {"nome": "seedvr2"}]}) == atteso
    assert lavoro.misura_del_motore(stanno) == atteso


def _video(monkeypatch, tmp_path, stanno):
    pytest.importorskip("av")
    from prove.test_miglioria_pezzi import _filmato, _lavoro

    monkeypatch.setattr(catena, "PER_VOLTA", 10)
    monkeypatch.setattr(catena.misura, "di_arrivo", lambda larga, alta, pari=False: (64, 48))
    if stanno is not None:
        monkeypatch.setattr(motori.Finto, "dove_stanno", stanno, raising=False)
    return catena.filmato(_lavoro(tmp_path, _filmato(tmp_path / "a.mp4")))


def test_il_video_dice_dove_stavano_i_pesi(monkeypatch, tmp_path):
    stanno = {"scheda": 4.5, "ram": 8.0, "disco": 4.0}
    fatto = _video(monkeypatch, tmp_path, stanno)
    assert fatto["dove_stanno"] == stanno and fatto["dove_stanno"] is not stanno


def test_il_video_senza_blocchi_fuori_non_dice_niente(monkeypatch, tmp_path):
    assert "dove_stanno" not in _video(monkeypatch, tmp_path, None)
    assert "dove_stanno" not in _video(monkeypatch, tmp_path, {})


def test_la_pagina_mostra_il_riquadro_e_le_scelte(cliente, monkeypatch):
    from officina.web import miglioramento as miglioramento_web

    vero = miglioramento_web.come_va
    stato = {"serve": 21, "libera": 10, "anche_col_disco": False, "disco": False,
             "aspetto": False}

    def come_va(archivio):
        risposta = vero(archivio)
        return {**risposta, "sta_lavorando": True, "adesso": {"nome": "a.jpg", "ram": stato}}

    monkeypatch.setattr(miglioramento_web, "come_va", come_va)
    testo = html.unescape(cliente.get("/miglioramento").text)
    assert "La RAM non basta per SeedVR2" in testo
    assert "Servono almeno <b class=\"numeri\">21 GB</b> di RAM libera" in testo
    assert 'value="aspetto"' in testo and 'value="disco"' in testo
    assert "Se non scegli, aspetto che la RAM si liberi e riparto da solo." in testo
    assert '"ram": {"serve": 21' in testo
    stato.update(aspetto=True)
    testo = html.unescape(cliente.get("/miglioramento").text)
    assert 'value="aspetto"' not in testo and 'value="disco"' in testo
    assert "Aspetto che la RAM si liberi: riparto da solo." in testo
    stato.update(disco=True)
    testo = html.unescape(cliente.get("/miglioramento").text)
    assert "La RAM non basta" in testo and 'value="disco"' not in testo
    assert "Anche col disco" not in testo
    stato.update(anche_col_disco=True, disco=False, aspetto=False)
    testo = html.unescape(cliente.get("/miglioramento").text)
    assert "Anche col disco non è bastata" in testo
    assert 'value="aspetto"' not in testo and 'value="disco"' not in testo
    assert "Aspetto che la RAM si liberi: riparto da solo." in testo
    stato.update(disco=True)
    testo = html.unescape(cliente.get("/miglioramento").text)
    assert "Anche col disco non è bastata" in testo
    assert 'value="aspetto"' not in testo and 'value="disco"' not in testo
    stato.clear()
    testo = html.unescape(cliente.get("/miglioramento").text)
    assert "La RAM non basta" not in testo


def test_la_pagina_senza_lavoro_non_mostra_il_riquadro(cliente, monkeypatch):
    from officina.web import miglioramento as miglioramento_web

    vero = miglioramento_web.come_va
    monkeypatch.setattr(miglioramento_web, "come_va", lambda archivio: {
        **vero(archivio), "sta_lavorando": False,
        "adesso": {"ram": {"serve": 21, "libera": 10}}})
    assert "La RAM non basta" not in cliente.get("/miglioramento").text


def test_il_miglioramento_a_parte_ascolta_le_risposte(importato, monkeypatch):
    from officina.miglioria import preparazione
    from officina.web import in_disparte
    from officina.web import miglioramento as miglioramento_web
    from officina.web.strade import miglioramento as strade

    lanciati: list = []
    monkeypatch.setattr(miglioramento_web, "_miglioratore", None)
    monkeypatch.setattr(preparazione, "e_pronto", lambda *argomenti: True)
    monkeypatch.setattr(in_disparte, "A_PARTE", True)
    monkeypatch.setattr(in_disparte, "lancia",
                        lambda *argomenti, **parole: lanciati.append(parole))
    monkeypatch.setattr(importato, "di_prova", False, raising=False)
    monkeypatch.setattr(strade.sosta.per_la_copia, "aspetta", lambda *argomenti: False)
    strade.avvia_il_miglioramento(importato)
    assert lanciati[0]["ascolta"] == "officina.web.miglioramento:ascolta_di_la"


def test_la_scelta_dalla_pagina_arriva_al_lavoro(cliente, monkeypatch):
    from officina.web import in_disparte
    from officina.web import miglioramento as miglioramento_web

    risposte: list = []

    class Finto:
        def rispondi_per_la_ram(self, scelta):
            risposte.append(scelta)
            return True

    monkeypatch.setattr(miglioramento_web, "il_miglioratore", lambda archivio: Finto())
    monkeypatch.setattr(in_disparte, "sta_girando", lambda a: False)
    risposta = cliente.post("/miglioramento/ram", data={"scelta": "disco"},
                            follow_redirects=False)
    assert risposta.status_code == 303 and risposta.headers["location"] == "/miglioramento"
    assert risposte == ["disco"]
    cliente.post("/miglioramento/ram", data={"scelta": "boh"}, follow_redirects=False)
    assert risposte == ["disco"]


def test_di_la_la_scelta_passa_per_il_ponte(monkeypatch):
    from officina.web import in_disparte
    from officina.web import miglioramento as miglioramento_web

    mandati: list = []
    girano: list = []
    monkeypatch.setattr(in_disparte, "sta_girando", lambda a: girano.append(a) or True)
    monkeypatch.setattr(in_disparte, "manda", lambda *c, a: mandati.append((c, a)))
    assert miglioramento_web.rispondi_per_la_ram(None, "aspetto") is True
    assert mandati == [(("ram", "aspetto"), "miglioramento")]
    assert girano == ["miglioramento"]
    assert miglioramento_web.rispondi_per_la_ram(None, "boh") is False
    assert len(mandati) == 1


def test_di_la_si_ascolta_solo_la_ram(monkeypatch):
    from officina.web import miglioramento as miglioramento_web

    sentite: list = []

    class Finto:
        def rispondi_per_la_ram(self, scelta):
            sentite.append(scelta)

    monkeypatch.setattr(miglioramento_web, "_miglioratore", None)
    miglioramento_web.ascolta_di_la("ram", "disco")
    monkeypatch.setattr(miglioramento_web, "_miglioratore", Finto())
    miglioramento_web.ascolta_di_la("altro", "disco")
    miglioramento_web.ascolta_di_la("ram")
    miglioramento_web.ascolta_di_la("ram", "disco", "in più")
    miglioramento_web.ascolta_di_la("ram", 3)
    assert sentite == ["3"]
