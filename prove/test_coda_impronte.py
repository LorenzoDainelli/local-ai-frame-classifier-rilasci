from __future__ import annotations

import time

from officina.impronte.motore import Coda, Passata


def test_la_coda_con_un_modello_solo_e_una_passata(archivio_pieno):
    coda = Coda(archivio_pieno, ["disegnato"], fotogrammi_per_video=4)
    assert coda.totale > 0

    coda.esegui()

    assert coda.percentuale == 100.0
    assert coda.impronte > 0
    assert len(coda.finite) == 1
    assert coda.adesso == ""


def test_il_totale_e_la_somma_di_tutta_la_coda(archivio_pieno):
    da_solo = Passata(archivio_pieno, "disegnato").quanti_mancano()

    coda = Coda(archivio_pieno, ["disegnato", "disegnato"])

    assert coda.totale == da_solo * 2
    assert coda.percentuale == 0.0


def test_fermare_la_coda_ferma_anche_quelli_che_non_sono_partiti(archivio_pieno):
    coda = Coda(archivio_pieno, ["disegnato", "disegnato"])
    coda.ferma()

    coda.esegui()

    assert coda.finite == []
    assert coda.impronte == 0


def test_una_coda_vuota_non_e_un_guasto(archivio_pieno):
    coda = Coda(archivio_pieno, [])
    coda.esegui()
    assert coda.percentuale == 100.0
    assert coda.quanto_manca() == "finito"


def test_tutti_vuol_dire_tutti_quelli_che_hai_in_casa(archivio_pieno):
    from officina.web.strade import misura

    quali = misura._quali_in_coda("tutti", archivio_pieno)

    assert quali == ["disegnato"]


def test_in_coda_i_modelli_veri_vengono_prima_del_disegnato():
    from officina.descrittori import TIPI

    nomi = [tipo.scheda.nome for tipo in TIPI]
    assert nomi[-1] == "disegnato"


def test_si_calcolano_sempre_con_tutti_i_modelli(archivio_pieno):
    import pytest

    from officina.errori import ErroreOfficina
    from officina.web.strade import misura

    assert misura._quali_in_coda("disegnato", archivio_pieno) == ["disegnato"]
    assert misura._quali_in_coda("", archivio_pieno) == ["disegnato"]
    with pytest.raises(ErroreOfficina, match="non è ancora scaricato"):
        misura._quali_in_coda("dinov3", archivio_pieno)


def test_se_la_passata_si_rompe_la_pagina_lo_dice(archivio_pieno):
    from fastapi.testclient import TestClient

    from officina.web import server
    from officina.web.strade import comune

    cliente = TestClient(server.app, client=("127.0.0.1", 51000))

    def esplode():
        raise KeyError(r"C:\Users\qualcuno\Foto\vacanza")

    comune.lavoro_impronte_passata.parti(esplode, "impronte")
    for _ in range(300):
        if not comune.lavoro_impronte_passata.sta_lavorando:
            break
        time.sleep(0.01)

    detto = cliente.get("/api/impronte").json()
    assert detto["guasto"], "la passata si è rotta e la pagina non lo sa"
    assert "qualcuno" not in detto["guasto"]
    assert "vacanza" not in detto["guasto"]


def test_gli_scatti_saltati_si_contano_e_si_dicono(archivio_pieno):
    from officina.impronte.motore import Avanzamento

    coda = Coda(archivio_pieno, ["disegnato"])
    assert coda.saltati == 0
    assert coda.motivi_saltati == {}

    finita = Avanzamento(descrittore="disegnato", versione="2")
    finita.saltati = 2
    finita.motivi_saltati = {"file_non_leggibile": 2}
    altra = Avanzamento(descrittore="disegnato", versione="2")
    altra.saltati = 1
    altra.motivi_saltati = {"file_non_leggibile": 1, "errore_imprevisto": 1}
    coda.finite = [finita, altra]

    assert coda.motivi_saltati == {"file_non_leggibile": 2, "errore_imprevisto": 1}
    assert coda.saltati == 3


def test_lo_stesso_file_rotto_non_si_conta_una_volta_per_modello(archivio_pieno):
    from officina.impronte.motore import Avanzamento

    coda = Coda(archivio_pieno, ["disegnato"])
    coda.finite = []
    for _ in range(4):
        passata = Avanzamento(descrittore="disegnato", versione="2")
        passata.saltati = 9
        passata.motivi_saltati = {"video_senza_indice": 7,
                                  "video_danneggiato": 1,
                                  "vuoto": 1}
        passata.scatti_saltati = [(n, "video_senza_indice") for n in range(7)]
        coda.finite.append(passata)

    assert coda.saltati == 9, "i file sono nove, i tentativi trentasei"
    assert coda.motivi_saltati == {"video_senza_indice": 7,
                                   "video_danneggiato": 1,
                                   "vuoto": 1}
    assert coda.saltati >= len(coda.scatti_saltati)


def test_una_passata_a_meta_non_gonfia_il_conto_dei_saltati(archivio_pieno):
    from officina.impronte.motore import Avanzamento

    coda = Coda(archivio_pieno, ["disegnato"])
    finita = Avanzamento(descrittore="disegnato", versione="2")
    finita.saltati = 9
    finita.motivi_saltati = {"video_senza_indice": 9}
    coda.finite = [finita]

    a_meta = Avanzamento(descrittore="disegnato", versione="2")
    a_meta.saltati = 3
    a_meta.motivi_saltati = {"video_senza_indice": 3}

    class _Finta:
        avanzamento = a_meta

    coda.passata = _Finta()
    try:
        assert coda.saltati == 9
    finally:
        coda.passata = None


def test_il_perche_dei_salti_si_dice_in_italiano():
    from officina.web.strade.misura import _perche_saltati

    assert _perche_saltati({}) == ""
    detto = _perche_saltati({"file_non_leggibile": 9})
    assert "file non si è lasciato aprire" in detto
    assert "9" in detto
    assert "file_non_leggibile" not in detto
    detto = _perche_saltati({"un_codice_nuovo": 1})
    assert "un_codice_nuovo" not in detto
    assert "1" in detto
