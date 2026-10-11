from __future__ import annotations

import pytest
from PIL import Image

from officina.descrittori.disegnato import (BIDONI, CELLE_BORDI, DIMENSIONE,
                                            LATO, ORDINE, PESI, QUANTI,
                                            Disegnato, pezzi)

numpy = pytest.importorskip("numpy")


def _quanto_simili(uno, altro) -> float:
    uno = numpy.asarray(uno, dtype=numpy.float64)
    altro = numpy.asarray(altro, dtype=numpy.float64)
    lunghezze = numpy.linalg.norm(uno) * numpy.linalg.norm(altro)
    return float(uno @ altro / lunghezze) if lunghezze > 0 else 0.0


def _da_numeri(matrice) -> Image.Image:
    dati = numpy.clip(matrice, 0.0, 1.0) * 255.0
    return Image.fromarray(dati.astype(numpy.uint8), mode="RGB")


def _tinta_unita(colore, lato: int = 256) -> Image.Image:
    matrice = numpy.zeros((lato, lato, 3), dtype=numpy.float32)
    matrice[:, :] = colore
    return _da_numeri(matrice)


def _righe(orizzontali: bool, passo: int = 8, lato: int = 256) -> Image.Image:
    riga = numpy.arange(lato)
    disegno = ((riga // passo) % 2).astype(numpy.float32)
    matrice = (numpy.tile(disegno[:, None], (1, lato)) if orizzontali
               else numpy.tile(disegno[None, :], (lato, 1)))
    return _da_numeri(numpy.repeat(matrice[:, :, None], 3, axis=2))


def _sopra_e_sotto(sopra, sotto, lato: int = 256) -> Image.Image:
    matrice = numpy.zeros((lato, lato, 3), dtype=numpy.float32)
    matrice[:lato // 2] = sopra
    matrice[lato // 2:] = sotto
    return _da_numeri(matrice)


def _disturbo(quanto: float, seme: int = 1, lato: int = 256) -> Image.Image:
    sorte = numpy.random.default_rng(seme)
    matrice = 0.5 + (sorte.random((lato, lato, 1)) - 0.5) * quanto
    return _da_numeri(numpy.repeat(matrice, 3, axis=2))


def test_ogni_pezzo_ha_la_lunghezza_che_dichiara():
    calcolati = pezzi(_righe(True))
    for nome in ORDINE:
        assert len(calcolati[nome]) == QUANTI[nome], nome
    assert sum(QUANTI[nome] for nome in ORDINE) == DIMENSIONE
    assert Disegnato.scheda.dimensione == DIMENSIONE


def test_i_pezzi_dichiarati_sono_tutti_e_soli_quelli_calcolati():
    assert set(pezzi(_righe(True))) == set(ORDINE) == set(PESI) == set(QUANTI)


def test_la_stessa_immagine_da_sempre_la_stessa_impronta():
    immagine = _righe(False)
    assert Disegnato().descrivi_una(immagine) == Disegnato().descrivi_una(immagine)


def test_limpronta_finita_e_lunga_uno():
    valori = Disegnato().descrivi_una(_righe(True))
    assert sum(valore * valore for valore in valori) == pytest.approx(1.0, abs=1e-5)


def test_il_cubo_mette_una_tinta_unita_tutta_in_un_angolo():
    cubo = pezzi(_tinta_unita((1.0, 0.0, 0.0)))["cubo_colori"]
    assert float(cubo.sum()) == pytest.approx(1.0, abs=1e-4)
    assert int(cubo.argmax()) == 3 * 16 + 0 * 4 + 0


def test_due_colori_vicini_restano_vicini_nel_cubo():
    uno = pezzi(_tinta_unita((0.49, 0.49, 0.49)))["cubo_colori"]
    altro = pezzi(_tinta_unita((0.51, 0.51, 0.51)))["cubo_colori"]
    assert _quanto_simili(uno, altro) > 0.9

    netto_uno = numpy.zeros(64)
    netto_uno[1 * 16 + 1 * 4 + 1] = 1.0
    netto_altro = numpy.zeros(64)
    netto_altro[2 * 16 + 2 * 4 + 2] = 1.0
    assert _quanto_simili(netto_uno, netto_altro) == 0.0


def test_il_cubo_non_sa_dove_stanno_i_colori():
    sopra = pezzi(_sopra_e_sotto((0.0, 0.0, 1.0), (0.0, 1.0, 0.0)))["cubo_colori"]
    sotto = pezzi(_sopra_e_sotto((0.0, 1.0, 0.0), (0.0, 0.0, 1.0)))["cubo_colori"]
    assert _quanto_simili(sopra, sotto) > 0.99


def test_un_grigio_non_ha_nessuna_tinta():
    tinte = pezzi(_tinta_unita((0.5, 0.5, 0.5)))["tinte"]
    assert float(numpy.abs(tinte).sum()) == pytest.approx(0.0, abs=1e-6)


def test_due_tinte_diverse_danno_due_pezzi_diversi():
    rosso = pezzi(_tinta_unita((0.9, 0.1, 0.1)))["tinte"]
    blu = pezzi(_tinta_unita((0.1, 0.1, 0.9)))["tinte"]
    assert _quanto_simili(rosso, blu) < 0.2


def test_la_tinta_e_un_cerchio_e_il_rosso_non_e_lontano_da_se_stesso():
    caldo = pezzi(_tinta_unita((0.9, 0.15, 0.1)))["tinte"]
    freddo = pezzi(_tinta_unita((0.9, 0.1, 0.15)))["tinte"]
    assert _quanto_simili(caldo, freddo) > 0.8


def test_la_stessa_tinta_in_ombra_resta_la_stessa_tinta():
    sole = _tinta_unita((0.9, 0.5, 0.1))
    ombra = _tinta_unita((0.45, 0.25, 0.05))
    assert _quanto_simili(pezzi(sole)["tinte"], pezzi(ombra)["tinte"]) > 0.9
    assert _quanto_simili(pezzi(sole)["cubo_colori"], pezzi(ombra)["cubo_colori"]) < 0.2


def test_le_strisce_vedono_la_differenza_fra_sopra_e_sotto():
    sopra = pezzi(_sopra_e_sotto((0.0, 0.0, 1.0), (0.0, 1.0, 0.0)))["strisce"]
    sotto = pezzi(_sopra_e_sotto((0.0, 1.0, 0.0), (0.0, 0.0, 1.0)))["strisce"]
    assert _quanto_simili(sopra, sotto) < 0.7


def test_la_griglia_distingue_un_colore_solo_da_un_miscuglio():
    fermo = pezzi(_tinta_unita((0.5, 0.5, 0.5)))["griglia"]
    agitato = pezzi(_disturbo(0.8))["griglia"]
    meta = len(fermo) // 2
    assert numpy.abs(fermo[:meta] - agitato[:meta]).max() < 0.05
    assert agitato[meta:].max() > fermo[meta:].max() + 0.1


def _direzione_piu_forte(pezzo, celle: int) -> int:
    per_direzione = pezzo.reshape(celle * celle, BIDONI).sum(axis=0)
    return int(per_direzione.argmax())


def test_le_righe_orizzontali_danno_bordi_orizzontali():
    assert _direzione_piu_forte(pezzi(_righe(True))["bordi_fini"], CELLE_BORDI) == BIDONI // 2
    assert _direzione_piu_forte(pezzi(_righe(False))["bordi_fini"], CELLE_BORDI) == 0


def test_una_tinta_unita_non_ha_nessun_bordo():
    fuori = pezzi(_tinta_unita((0.3, 0.4, 0.5)))["bordi_fini"]
    assert float(numpy.abs(fuori).max()) == pytest.approx(0.0, abs=1e-4)
    valori = Disegnato().descrivi_una(_tinta_unita((0.3, 0.4, 0.5)))
    assert sum(v * v for v in valori) == pytest.approx(1.0, abs=1e-5)


def test_un_bordo_netto_conta_piu_di_venti_increspature():
    netto = pezzi(_sopra_e_sotto(0.0, 1.0))["bordi_fini"]
    increspata = pezzi(_disturbo(0.15, seme=3))["bordi_fini"]
    assert float(netto.max()) > float(increspata.max())


def test_i_bordi_in_grande_non_si_accorgono_del_disturbo_minuto():
    sorte = numpy.random.default_rng(11)
    pulita = numpy.zeros((256, 256, 3), dtype=numpy.float32)
    pulita[:128] = 0.2
    pulita[128:] = 0.8
    sporca = pulita + (sorte.random((256, 256, 1)) - 0.5) * 0.25

    grande = _quanto_simili(pezzi(_da_numeri(pulita))["bordi_grossi"], pezzi(_da_numeri(sporca))["bordi_grossi"])
    fine = _quanto_simili(pezzi(_da_numeri(pulita))["bordi_fini"], pezzi(_da_numeri(sporca))["bordi_fini"])
    assert grande > fine


def test_la_trama_distingue_il_liscio_dal_fitto():
    liscia = pezzi(_tinta_unita((0.5, 0.5, 0.5)))["trama"]
    fitta = pezzi(_disturbo(1.0))["trama"]
    assert float(liscia.max()) < 0.01
    assert float(fitta.mean()) > float(liscia.mean()) + 0.02


def test_ai_motivi_minuti_la_luce_non_fa_niente():
    base = numpy.repeat(
        numpy.random.default_rng(5).random((256, 256, 1)).astype(numpy.float32) * 0.4,
        3, axis=2)
    scura = pezzi(_da_numeri(base))["motivi"]
    chiara = pezzi(_da_numeri(base + 0.35))["motivi"]
    assert numpy.abs(scura - chiara).max() < 0.02


def test_i_motivi_di_una_superficie_piatta_non_sono_lasciati_al_caso():
    motivi = pezzi(_tinta_unita((0.42, 0.42, 0.42)))["motivi"]
    per_cella = motivi.reshape(-1, len(motivi) // 4)
    for cella in per_cella:
        assert cella[0] == pytest.approx(1.0, abs=1e-4)


def test_due_superfici_ugualmente_ruvide_ma_diverse_si_distinguono():
    righe = pezzi(_righe(True, passo=2))["motivi"]
    puntini = pezzi(_disturbo(1.0, seme=9))["motivi"]
    assert _quanto_simili(righe, puntini) < 0.9


def test_una_foto_simmetrica_si_riconosce():
    specchiata = numpy.zeros((256, 256, 3), dtype=numpy.float32)
    meta = numpy.random.default_rng(2).random((256, 128, 1)).astype(numpy.float32)
    specchiata[:, :128] = meta
    specchiata[:, 128:] = meta[:, ::-1]

    simmetria = pezzi(_da_numeri(specchiata))["simmetria"]
    assert simmetria[0] > 0.98
    assert simmetria[2] == pytest.approx(0.0, abs=0.01)


def test_il_cielo_sopra_si_vede_da_quanto_e_piu_chiaro():
    simmetria = pezzi(_sopra_e_sotto(0.9, 0.2))["simmetria"]
    assert simmetria[5] > 0.5
    capovolta = pezzi(_sopra_e_sotto(0.2, 0.9))["simmetria"]
    assert capovolta[5] < -0.5


def test_la_luce_separa_la_sera_dal_mezzogiorno():
    sera = pezzi(_tinta_unita((0.12, 0.12, 0.14)))["luce"]
    giorno = pezzi(_tinta_unita((0.85, 0.85, 0.83)))["luce"]
    assert sera[-4] < 0.2 < giorno[-4]
    assert _quanto_simili(sera, giorno) < 0.3


def test_la_luce_riconosce_il_bianco_e_nero():
    grigia = pezzi(_disturbo(1.0))["luce"]
    colorata = pezzi(_tinta_unita((0.9, 0.1, 0.1)))["luce"]
    assert grigia[-1] > 0.9
    assert colorata[-1] < 0.1


def test_nessun_pezzo_decide_da_solo_perche_ha_i_numeri_piu_grandi():
    valori = numpy.array(Disegnato().descrivi_una(_righe(True, passo=4)))
    da = 0
    lunghezze = {}
    for nome in ORDINE:
        lunghezze[nome] = float(numpy.linalg.norm(valori[da:da + QUANTI[nome]]))
        da += QUANTI[nome]

    assert lunghezze["bordi_fini"] / lunghezze["cubo_colori"] == pytest.approx(
        PESI["bordi_fini"] / PESI["cubo_colori"], rel=0.01)
    assert lunghezze["trama"] / lunghezze["simmetria"] == pytest.approx(
        PESI["trama"] / PESI["simmetria"], rel=0.01)


def test_i_pesi_sono_scritti_in_chiaro_e_nessuno_e_zero():
    for nome in ORDINE:
        assert PESI[nome] > 0, nome


def test_limmagine_ridotta_e_divisibile_per_tutte_le_griglie():
    for celle in (2, 3, 4, 6, 8):
        assert LATO % celle == 0
