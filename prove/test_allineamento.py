from __future__ import annotations

import pytest
from PIL import Image

from officina.finto import facce
from officina.volti import allineamento

numpy = pytest.importorskip("numpy")


def faccia_finta(misura=(400, 400), centro=(200, 200), raggio=120.0,
                 gradi=0.0, colore=(230, 200, 170)):
    return facce.disegna(misura=misura, centro=centro, raggio=raggio,
                         gradi=gradi, colore=colore)


def test_i_cinque_punti_finiscono_sui_cinque_punti_di_riferimento():
    _, punti = faccia_finta()
    trasformata = allineamento.trasformazione(punti)

    for arrivato, atteso in zip(
            (allineamento.dove_finisce(p, trasformata) for p in punti),
            allineamento.PUNTI_DI_RIFERIMENTO):
        assert arrivato[0] == pytest.approx(atteso[0], abs=6.0)
        assert arrivato[1] == pytest.approx(atteso[1], abs=6.0)


def test_i_punti_di_riferimento_su_se_stessi_non_si_muovono():
    a, b, tx, c, d, ty = allineamento.trasformazione(
        allineamento.PUNTI_DI_RIFERIMENTO)
    assert (a, b, c, d) == pytest.approx((1.0, 0.0, 0.0, 1.0), abs=1e-9)
    assert (tx, ty) == pytest.approx((0.0, 0.0), abs=1e-9)


def test_il_quadrato_esce_della_misura_giusta():
    immagine, punti = faccia_finta()
    assert allineamento.raddrizza(immagine, punti).size == (
        allineamento.LATO, allineamento.LATO)
    assert allineamento.raddrizza(immagine, punti, lato=224).size == (224, 224)


@pytest.mark.parametrize("gradi", [-25.0, -7.0, 0.0, 12.0, 33.0])
def test_la_stessa_faccia_inclinata_esce_uguale(gradi):
    dritta, dritta_punti = faccia_finta(gradi=0.0)
    storta, storta_punti = faccia_finta(gradi=gradi)

    a = allineamento.raddrizza(dritta, dritta_punti)
    b = allineamento.raddrizza(storta, storta_punti)
    assert _quanto_si_somigliano(a, b) > 0.97


def test_la_stessa_faccia_piu_piccola_e_spostata_esce_uguale():
    grande, punti_grande = faccia_finta(misura=(600, 600), centro=(300, 300),
                                        raggio=200.0)
    piccola, punti_piccola = faccia_finta(misura=(300, 300), centro=(120, 160),
                                          raggio=70.0)
    a = allineamento.raddrizza(grande, punti_grande)
    b = allineamento.raddrizza(piccola, punti_piccola)
    assert _quanto_si_somigliano(a, b) > 0.95


def test_una_faccia_non_esce_mai_specchiata():
    _, punti = faccia_finta()
    a, b, _, c, d, _ = allineamento.trasformazione(punti)
    assert a * d - b * c > 0


def test_cinque_punti_tutti_uguali_lo_dicono_invece_di_dare_un_numero():
    with pytest.raises(allineamento.PuntiSbagliati):
        allineamento.trasformazione([(10.0, 10.0)] * 5)


def test_quattro_punti_invece_di_cinque_lo_dicono():
    with pytest.raises(allineamento.PuntiSbagliati):
        allineamento.trasformazione([(1.0, 2.0)] * 4)


def test_lo_stesso_conto_di_opencv():
    cv2 = pytest.importorskip("cv2", reason="OpenCV non è installato qui")
    if not hasattr(cv2, "estimateAffinePartial2D"):
        pytest.skip("questa versione di OpenCV non ha il conto da confrontare")

    _, punti = faccia_finta(gradi=17.0)
    nostra = allineamento.trasformazione(punti)
    loro, _ = cv2.estimateAffinePartial2D(
        numpy.asarray(punti, dtype=numpy.float32),
        numpy.asarray(allineamento.PUNTI_DI_RIFERIMENTO, dtype=numpy.float32),
        method=cv2.LMEDS)
    assert loro is not None
    suoi = (float(loro[0][0]), float(loro[0][1]), float(loro[0][2]),
            float(loro[1][0]), float(loro[1][1]), float(loro[1][2]))
    for mio, suo in zip(nostra, suoi):
        assert mio == pytest.approx(suo, abs=1.5)


def _quanto_si_somigliano(a: Image.Image, b: Image.Image) -> float:
    prima = numpy.asarray(a.convert("L"), dtype=numpy.float64).ravel()
    dopo = numpy.asarray(b.convert("L"), dtype=numpy.float64).ravel()
    prima = prima - prima.mean()
    dopo = dopo - dopo.mean()
    denominatore = float(numpy.linalg.norm(prima) * numpy.linalg.norm(dopo))
    if denominatore == 0:
        return 0.0
    return float(prima @ dopo / denominatore)
