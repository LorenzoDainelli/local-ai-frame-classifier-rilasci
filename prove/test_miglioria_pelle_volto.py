import numpy as np

from officina.miglioria import pelle_volto


class Finto:
    def __init__(self, proposte):
        self.proposte = proposte
        self.accesa = False

    def accendi(self):
        self.accesa = True

    def _proposte(self, quadro):
        return self.proposte

    def _raddrizza(self, originale, intera, punti, numpy):
        return "dritta"

    def _impronta_di(self, dritta, numpy):
        return [1.0, 0.0]


PUNTI = [(10, 10), (20, 10), (15, 15), (12, 20), (18, 20)]


def test_prende_il_volto_piu_grande_e_sicuro():
    piccolo = ([0, 0, 10, 10], PUNTI, 0.9)
    grande = ([100, 100, 300, 300], PUNTI, 0.7)
    debole = ([0, 0, 600, 600], PUNTI, 0.3)
    finto = Finto([piccolo, grande, debole])
    misura = pelle_volto.misuratore(finto)
    trovato = misura(np.zeros((640, 640, 3), np.uint8))
    assert finto.accesa
    assert trovato["impronta"] == [1.0, 0.0]
    larga = trovato["riquadro"][2] - trovato["riquadro"][0]
    assert larga > 150 and trovato["sicurezza"] == 0.7
    assert len(trovato["punti"]) == 5


def test_nessun_volto_da_vuoto():
    assert pelle_volto.volto_di(Finto([]), np.zeros((64, 64, 3), np.uint8)) == {}
