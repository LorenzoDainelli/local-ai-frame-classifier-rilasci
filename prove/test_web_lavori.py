from __future__ import annotations

import threading
import time

import pytest
from fastapi.testclient import TestClient

from officina.errori import ErroreOfficina
from officina.web.lavori import Lavoro


def aspetta(lavoro: Lavoro, entro: float = 3.0) -> None:
    scade = time.monotonic() + entro
    while lavoro.sta_lavorando and time.monotonic() < scade:
        time.sleep(0.01)
    assert not lavoro.sta_lavorando, "il lavoro non è finito in tempo"


def test_racconta_quello_che_sta_facendo():
    lavoro = Lavoro("prova")
    lavoro.parti(lambda: [lavoro.di("primo"), lavoro.di("secondo")])
    aspetta(lavoro)
    assert lavoro.come_va()["righe"] == ["primo", "secondo"]
    assert lavoro.come_va()["finito"] is True


def test_uno_alla_volta():
    lavoro = Lavoro("prova")
    lavoro.parti(lambda: time.sleep(0.3))
    assert lavoro.parti(lambda: None) is False
    aspetta(lavoro)


def test_un_guasto_previsto_si_legge_in_italiano():
    def va_male():
        raise ErroreOfficina("Il posto c'è, il file no.")

    lavoro = Lavoro("prova")
    lavoro.parti(va_male)
    aspetta(lavoro)
    assert lavoro.come_va()["guasto"] == "Il posto c'è, il file no."
    assert lavoro.come_va()["finito"] is True


def test_un_guasto_imprevisto_non_racconta_i_fatti_suoi():
    def esplode():
        raise KeyError(r"C:\Users\qualcuno\Foto\vacanza")

    lavoro = Lavoro("prova")
    lavoro.parti(esplode)
    aspetta(lavoro)
    guasto = lavoro.come_va()["guasto"]
    assert "qualcuno" not in guasto
    assert "vacanza" not in guasto
    assert "difetto del programma" in guasto


def test_tiene_le_ultime_righe_non_tutte():
    lavoro = Lavoro("prova", quante_righe=5)
    lavoro.parti(lambda: [lavoro.di(str(n)) for n in range(50)])
    aspetta(lavoro)
    righe = lavoro.come_va()["righe"]
    assert len(righe) == 5
    assert righe[-1] == "49"


def test_una_riga_vuota_non_e_una_riga():
    lavoro = Lavoro("prova")
    lavoro.di("")
    lavoro.di("   ")
    lavoro.di(" c'è ")
    assert lavoro.come_va()["righe"] == ["c'è"]


@pytest.fixture
def cliente(archivio_pieno):
    from officina.web.server import app

    return TestClient(app, client=("127.0.0.1", 51000))


def test_la_pagina_salute_elenca_i_modelli_con_la_loro_licenza(cliente):
    testo = cliente.get("/stato").text
    assert "I modelli" in testo
    assert "licenza" in testo
    assert ">Scarica</button>" in testo


def test_nessuna_pagina_chiede_il_gettone(cliente):
    for indirizzo in ("/stato", "/persone"):
        testo = cliente.get(indirizzo).text.lower()
        assert "hf_token" not in testo
        assert "gettone" not in testo
        assert 'type="password"' not in testo


def test_scaricare_qualcosa_che_non_si_scarica_lo_dice(cliente):
    from officina.web.strade import comune

    cliente.post("/modelli/scarica", data={"quale": "disegnato"})
    aspetta(comune.lavoro_modelli)
    assert "non è un modello che si scarica" in comune.lavoro_modelli.come_va()["guasto"]


def test_lo_scaricamento_finito_si_vede_dalla_pagina(cliente, monkeypatch):
    from officina.web.strade import comune, modelli

    def finto(quale, dove):
        comune.lavoro_modelli.di("arrivato tutto")

    monkeypatch.setattr(modelli, "_porta_in_casa", finto)
    assert cliente.post("/modelli/scarica",
                        data={"quale": "volti"}).status_code in (200, 303)
    aspetta(comune.lavoro_modelli)

    stato = cliente.get("/api/modelli").json()
    assert stato["sta_lavorando"] is False
    assert "arrivato tutto" in stato["righe"]
    assert stato["guasto"] == ""


def test_senza_i_modelli_i_volti_non_partono_e_si_capisce_perche(cliente):
    risposta = cliente.post("/persone/trova")
    assert risposta.status_code == 400
    assert "volti" in risposta.text


def test_la_pagina_persone_non_manda_piu_al_terminale(cliente):
    testo = cliente.get("/persone").text
    assert "python -m officina volti" not in testo


def test_le_due_domande_rispondono_anche_quando_non_c_e_niente(cliente):
    for indirizzo in ("/api/modelli", "/api/volti"):
        dati = cliente.get(indirizzo).json()
        assert dati["sta_lavorando"] is False


def test_il_riquadro_del_perche_c_e_sempre_anche_da_vuoto(cliente):
    testo = cliente.get("/stato").text
    assert 'id="guasto-modelli"' in testo
    assert "hidden" in testo


def test_la_pagina_viva_scrive_il_motivo_e_non_solo_che_e_fallito(cliente):
    testo = cliente.get("/stato").text
    assert "guasto.textContent = dati.guasto" in testo


def test_non_ricarica_la_pagina_se_non_c_era_niente_da_scaricare(cliente):
    testo = cliente.get("/stato").text
    assert 'data-lavorava="0"' in testo
    assert "visto_lavorare && !dati.guasto" in testo


def test_uno_alla_volta_vuol_dire_uno_anche_se_arrivano_insieme():
    import threading

    lavoro = Lavoro("prova")
    girati = []
    pronti = threading.Barrier(20)
    risposte = []
    lucchetto = threading.Lock()

    def prova():
        pronti.wait()
        acceso = lavoro.parti(lambda: (girati.append(1), time.sleep(0.2)))
        with lucchetto:
            risposte.append(acceso)

    fili = [threading.Thread(target=prova) for _ in range(20)]
    for filo in fili:
        filo.start()
    for filo in fili:
        filo.join()
    aspetta(lavoro)

    assert risposte.count(True) == 1, f"sono partiti in {risposte.count(True)}"
    assert len(girati) == 1


def test_la_barra_di_un_lavoro_nuovo_parte_da_zero():
    lavoro = Lavoro("prova")
    lavoro.parti(lambda: lavoro.a_che_punto(99, 100))
    aspetta(lavoro)
    assert lavoro.come_va()["percento"] == 99

    fermo = threading.Event()
    lavoro.parti(fermo.wait)
    try:
        assert "percento" not in lavoro.come_va(), (
            "la barra del lavoro nuovo parte con il numero di quello vecchio")
    finally:
        fermo.set()
    aspetta(lavoro)


def test_seedvr2_ha_la_sua_riga_e_si_scarica_con_un_clic(cliente, monkeypatch):
    from officina.miglioria import preparazione
    from officina.web.strade import comune

    testo = cliente.get("/stato").text
    assert "SeedVR2, che migliora foto e video" in testo
    assert 'value="seedvr2"' in testo

    chiesti = []

    def prepara(dove, di, chiave=None, a_che_punto=None):
        chiesti.append(dove)
        di("SeedVR2 è in casa, controllato file per file.")

    monkeypatch.setattr(preparazione, "prepara", prepara)
    cliente.post("/modelli/scarica", data={"quale": "seedvr2"})
    aspetta(comune.lavoro_modelli)
    stato = cliente.get("/api/modelli").json()
    assert chiesti and stato["guasto"] == ""
    assert "SeedVR2 è in casa, controllato file per file." in stato["righe"]


def test_codeformer_prende_prima_i_modelli_che_trovano_i_volti(cliente, monkeypatch):
    from officina.miglioria import codeformer_pesi
    from officina.volti import scaricamento as scarica_volti
    from officina.web.strade import comune

    testo = cliente.get("/stato").text
    assert "CodeFormer, che sistema i volti nelle foto" in testo
    assert "uso NON commerciale" in testo

    ordine = []
    monkeypatch.setattr(scarica_volti, "gia_in_casa", lambda dove: False)
    monkeypatch.setattr(scarica_volti, "scarica",
                        lambda dove, **_o: ordine.append("volti"))
    monkeypatch.setattr(codeformer_pesi, "scarica",
                        lambda dove, **_o: ordine.append("codeformer"))
    cliente.post("/modelli/scarica", data={"quale": "codeformer"})
    aspetta(comune.lavoro_modelli)
    assert ordine == ["volti", "codeformer"]
    assert comune.lavoro_modelli.come_va()["guasto"] == ""


def test_faceme_prende_prima_volti_e_codeformer_poi_se_stesso(cliente, monkeypatch):
    from officina.miglioria import codeformer_pesi, preparazione
    from officina.volti import scaricamento as scarica_volti
    from officina.web.strade import comune

    testo = cliente.get("/stato").text
    assert "FaceMe, che sistema i volti con le foto di riferimento" in testo

    ordine = []
    monkeypatch.setattr(scarica_volti, "gia_in_casa", lambda dove: False)
    monkeypatch.setattr(scarica_volti, "scarica", lambda dove, **_o: ordine.append("volti"))
    monkeypatch.setattr(codeformer_pesi, "e_in_casa", lambda dove: False)
    monkeypatch.setattr(codeformer_pesi, "scarica",
                        lambda dove, **_o: ordine.append("codeformer"))
    monkeypatch.setattr(preparazione, "prepara",
                        lambda dove, **o: ordine.append(o["nome"]))
    cliente.post("/modelli/scarica", data={"quale": "faceme"})
    aspetta(comune.lavoro_modelli)
    assert ordine == ["volti", "codeformer", "faceme"]
    assert comune.lavoro_modelli.come_va()["guasto"] == ""


def test_lucidflux_si_scarica_a_parte_e_non_con_quel_che_manca(cliente, monkeypatch):
    from officina.miglioria import lucidflux_pesi, preparazione
    from officina.web.strade import comune, modelli

    testo = cliente.get("/stato").text
    assert "LucidFlux, che sfida SeedVR2 sulle foto" in testo
    assert "FLUX.1 [dev]" in testo

    presi = []
    monkeypatch.setattr(preparazione, "prepara",
                        lambda dove, **o: presi.append((o["nome"], o["scarica"])))
    cliente.post("/modelli/scarica", data={"quale": "lucidflux"})
    aspetta(comune.lavoro_modelli)
    assert presi == [("lucidflux", lucidflux_pesi.scarica)]

    fatti = []
    monkeypatch.setattr(modelli, "_porta_in_casa", lambda quale, dove: fatti.append(quale))
    cliente.post("/modelli/scarica-quel-che-manca")
    aspetta(comune.lavoro_modelli)
    assert "lucidflux" not in fatti


def test_le_librerie_si_contano_a_pezzi_e_poi_la_barra_si_svuota():
    from officina.miglioria import preparazione

    lavoro = Lavoro("prova")

    class Installatore:
        class stato:
            detto = ""
            fase = "scarica"
            fatti = 50
            totale = 93

    def fai():
        time.sleep(preparazione.OGNI_QUANTO * 3)
        assert lavoro.come_va()["unita"] == "pezzi"
        assert lavoro.come_va()["da_scaricare"] == 93

    preparazione._col_resoconto(Installatore, lambda _riga: None, lavoro.a_che_punto, fai)
    assert "percento" not in lavoro.come_va(), (
        "finite le librerie, la barra resta ferma sul loro numero")
