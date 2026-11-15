import numpy as np
import pytest

from officina.miglioria import stampa_controllo as sc

OCCHI = [(100.0, 100.0), (160.0, 100.0), (130.0, 130.0), (110.0, 160.0), (150.0, 160.0)]
RIQUADRO = [70.0, 60.0, 190.0, 200.0]


class Finto:

    def __init__(self, scena):
        self.scena = scena

    def _quale(self, pixel):
        return self.scena[int(np.asarray(pixel)[0, 0, 0])]

    def trova(self, pixel):
        voce = self._quale(pixel)
        return [] if voce is None else [(RIQUADRO, voce["punti"], 0.9)]

    def impronta(self, pixel, punti):
        return self._quale(pixel)["impronta"]


@pytest.fixture
def finto(monkeypatch):
    def fai(scena):
        rilevatore = Finto(scena)
        monkeypatch.setattr(sc, "volti", lambda r, pixel: r.trova(pixel))
        monkeypatch.setattr(sc, "impronta", lambda r, pixel, punti: r.impronta(pixel, punti))
        return rilevatore
    return fai


def _foto(segno):
    pixel = np.zeros((8, 8, 3), dtype=np.uint8)
    pixel[0, 0, 0] = segno
    return pixel


def _sposta(punti, dx):
    return [(x + dx, y) for x, y in punti]


def test_volto_uguale_spostato_cambiato_e_sparito(finto):
    vera = {"punti": OCCHI, "impronta": [1.0, 0.0, 0.0]}
    scena = {0: vera,
             1: {"punti": _sposta(OCCHI, 2.0), "impronta": [0.95, 0.31, 0.0]},
             2: {"punti": _sposta(OCCHI, 9.0), "impronta": [1.0, 0.0, 0.0]},
             3: {"punti": OCCHI, "impronta": [0.3, 0.95, 0.0]},
             4: None}
    rilevatore = finto(scena)
    esito = sc.controlla(rilevatore, _foto(0),
                         {"uguale": _foto(1), "spostato": _foto(2), "altra": _foto(3),
                          "sparito": _foto(4)}, ingrandimento=2.0)
    assert esito["uguale"]["cambiati"] == 0 and esito["uguale"]["controllati"] == 1
    assert esito["spostato"]["cambiati"] == 1
    assert esito["altra"]["cambiati"] == 1
    assert esito["sparito"]["cambiati"] == 1


def test_volto_piccolo_non_si_controlla(finto):
    rilevatore = finto({0: {"punti": OCCHI, "impronta": [1.0, 0.0]},
                        1: {"punti": OCCHI, "impronta": [0.0, 1.0]}})
    esito = sc.controlla(rilevatore, _foto(0), {"x": _foto(1)}, ingrandimento=4.0)
    assert esito["x"] == {"controllati": 0, "cambiati": 0, "piccoli": 1,
                          "persona": None, "spostati": None}


def test_soglie():
    assert sc.STESSA_PERSONA == pytest.approx(0.48)
    assert sc.somiglianza([1, 0], [1, 0]) == pytest.approx(1.0)
    assert sc.somiglianza(None, [1, 0]) == 0.0
    assert sc.spostamento(_sposta(OCCHI, 6.0), OCCHI) == pytest.approx(0.1)


def test_volti_usa_il_rilevatore_vero_a_due_misure():
    from officina.volti import insight

    class Rilevatore:
        def _proposte(self, piccola):
            lato = piccola.shape[0]
            return [([10.0, 10.0, 50.0, 50.0], OCCHI[:], 0.9 if lato == 640 else 0.8),
                    ([0.0, 0.0, 5.0, 5.0], OCCHI[:], 0.1)]

    pixel = np.zeros((1280, 1920, 3), dtype=np.uint8)
    trovati = sc.volti(Rilevatore(), pixel)
    assert len(trovati) == 2
    assert insight.LATI_DEL_QUADRATO == (640, 1280)
    scala = 640 / 1920
    assert trovati[0][0][0] == pytest.approx(10.0 / scala)
    assert all(voce[2] >= sc.SICUREZZA for voce in trovati)
