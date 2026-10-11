from __future__ import annotations

import pytest

from officina.volti import insight

numpy = pytest.importorskip("numpy")


def _uscite_con_una_faccia(larghezza, altezza, gradino_scelto, dove,
                           bordi=(2.0, 3.0, 2.0, 3.0), sicurezza=0.9):
    sicurezze, distanze, punti = [], [], []
    for gradino in insight.GRADINI:
        alta = (altezza + gradino - 1) // gradino
        larga = (larghezza + gradino - 1) // gradino
        quante = alta * larga * insight.PROPOSTE_PER_POSIZIONE
        s = numpy.zeros((quante, 1), dtype=numpy.float32)
        d = numpy.zeros((quante, 4), dtype=numpy.float32)
        k = numpy.zeros((quante, 10), dtype=numpy.float32)
        if gradino == gradino_scelto:
            colonna, riga = dove
            indice = (riga * larga + colonna) * insight.PROPOSTE_PER_POSIZIONE
            s[indice] = sicurezza
            d[indice] = bordi
            k[indice] = [-0.7, -0.5, 0.7, -0.5, 0.0, 0.1,
                         -0.5, 0.8, 0.5, 0.8]
        sicurezze.append(s)
        distanze.append(d)
        punti.append(k)
    return sicurezze + distanze + punti


def test_il_riquadro_finisce_dove_il_modello_ha_detto():
    uscite = _uscite_con_una_faccia(320, 320, 8, (10, 6))
    trovate = insight.leggi_le_uscite(uscite, 320, 320, numpy)

    assert len(trovate) == 1
    riquadro, punti, sicurezza = trovate[0]
    assert riquadro == pytest.approx([80 - 16, 48 - 24, 80 + 16, 48 + 24])
    assert sicurezza == pytest.approx(0.9)
    assert len(punti) == 5
    assert punti[0][0] < 80 < punti[1][0]
    assert punti[0][1] == pytest.approx(punti[1][1])


@pytest.mark.parametrize("gradino", insight.GRADINI)
def test_ogni_gradino_si_legge_al_posto_giusto(gradino):
    uscite = _uscite_con_una_faccia(256, 256, gradino, (3, 2))
    trovate = insight.leggi_le_uscite(uscite, 256, 256, numpy)
    assert len(trovate) == 1
    riquadro = trovate[0][0]
    centro_x = (riquadro[0] + riquadro[2]) / 2
    centro_y = (riquadro[1] + riquadro[3]) / 2
    assert centro_x == pytest.approx(3 * gradino)
    assert centro_y == pytest.approx(2 * gradino)


def test_quello_di_cui_non_e_sicuro_non_arriva_nemmeno():
    uscite = _uscite_con_una_faccia(160, 160, 8, (4, 4), sicurezza=0.05)
    assert insight.leggi_le_uscite(uscite, 160, 160, numpy) == []


def test_le_facce_arrivano_dalla_piu_sicura_alla_meno():
    uscite = _uscite_con_una_faccia(160, 160, 8, (4, 4), sicurezza=0.4)
    altre = _uscite_con_una_faccia(160, 160, 16, (2, 2), sicurezza=0.95)
    unite = [numpy.concatenate([a, b]) for a, b in zip(uscite, altre)]
    trovate = insight.leggi_le_uscite(unite, 160, 160, numpy)
    assert [round(t[2], 2) for t in trovate] == sorted(
        [round(t[2], 2) for t in trovate], reverse=True)


def test_le_tabelle_che_non_tornano_danno_nessuna_faccia():
    uscite = _uscite_con_una_faccia(320, 320, 8, (10, 6))
    assert insight.leggi_le_uscite(uscite, 999, 999, numpy) == []


def test_una_risposta_troppo_corta_non_rompe_niente():
    assert insight.leggi_le_uscite([], 100, 100, numpy) == []
    assert insight.leggi_le_uscite([numpy.zeros((4, 1))], 100, 100, numpy) == []


def test_la_stessa_faccia_si_tiene_una_volta_sola():
    quasi_uguali = [
        ([10.0, 10.0, 50.0, 50.0], [], 0.9),
        ([11.0, 11.0, 51.0, 51.0], [], 0.8),
        ([200.0, 200.0, 240.0, 240.0], [], 0.7),
    ]
    tenute = insight._togli_i_doppioni(quasi_uguali, insight.SOVRAPPOSIZIONE_MASSIMA)
    assert [t[2] for t in tenute] == [0.9, 0.7]


def test_due_facce_lontane_restano_due():
    lontane = [
        ([0.0, 0.0, 20.0, 20.0], [], 0.9),
        ([100.0, 100.0, 120.0, 120.0], [], 0.9),
    ]
    assert len(insight._togli_i_doppioni(
        lontane, insight.SOVRAPPOSIZIONE_MASSIMA)) == 2


def test_c_e_un_motore_solo(archivio):
    from officina import volti

    assert isinstance(volti.apri(archivio), insight.Rilevatore)


def test_i_modelli_vecchi_non_si_scaricano_piu():
    from officina.volti import rilevatore, scaricamento

    assert set(scaricamento.DA_DOVE) == {insight.FILE_RILEVATORE,
                                         insight.FILE_RICONOSCITORE}
    assert not set(scaricamento.DA_DOVE) & set(rilevatore.FILE_VECCHI)
    assert "scrfd" in insight.VERSIONE and "adaface" in insight.VERSIONE


def test_la_licenza_non_commerciale_e_scritta():
    from officina.volti import scaricamento

    for fonte in scaricamento.DA_DOVE.values():
        assert "non commerciale" in fonte.licenza


def test_i_due_posti_sono_stati_guardati_davvero():
    from officina.volti import scaricamento

    for fonte in scaricamento.DA_DOVE.values():
        assert fonte.provata is True


def test_il_riconoscitore_si_prende_dove_e_gia_convertito():
    from officina.volti import insight
    from officina.volti import scaricamento

    fonte = scaricamento.DA_DOVE[insight.FILE_RICONOSCITORE]
    assert fonte.nome_sul_sito.endswith(".onnx")
    assert fonte.repo.endswith("_onnx")


def test_il_rilevatore_si_chiede_alla_raccolta_di_dati_non_ai_modelli():
    from officina.volti import insight
    from officina.volti import scaricamento

    fonte = scaricamento.DA_DOVE[insight.FILE_RILEVATORE]
    assert fonte.genere == "dataset"
    assert fonte.nome_sul_sito.endswith("det_10g.onnx")


def test_senza_la_libreria_lo_dice_in_italiano(tmp_path, monkeypatch):
    from officina.volti import rilevatore

    monkeypatch.setattr(rilevatore, "c_e_onnxruntime", lambda: False)
    detto = insight.cosa_manca(tmp_path)
    assert "onnxruntime" in detto and "pip install" in detto
    assert "resto del programma funziona" in detto


def test_senza_i_modelli_lo_dice_e_ricorda_la_licenza(tmp_path, monkeypatch):
    from officina.volti import rilevatore

    monkeypatch.setattr(rilevatore, "c_e_onnxruntime", lambda: True)
    detto = insight.cosa_manca(tmp_path)
    assert "modelli --scarica volti" in detto
    assert "non commerciale" in detto
