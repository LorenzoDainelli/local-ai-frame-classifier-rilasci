import pytest
from PIL import Image

from officina.parole import lettore as modulo


class _Gettoni:

    def __init__(self, righe):
        self.righe = righe
        self.shape = (1, len(righe[0]))

    def __getitem__(self, chiave):
        _righe, colonne = chiave
        return [riga[colonne] for riga in self.righe]

    def to(self, *_a, **_k):
        return self


class _Preparatore:

    def __init__(self, risposta, senza_pensieri=True):
        self.risposta = risposta
        self.senza_pensieri = senza_pensieri
        self.discorsi = []
        self.immagini = None

    def apply_chat_template(self, discorso, tokenize, add_generation_prompt, **altro):
        if "enable_thinking" in altro and not self.senza_pensieri:
            raise TypeError("enable_thinking")
        self.discorsi.append((discorso, altro))
        return "domanda"

    def __call__(self, text, return_tensors, images=None):
        self.immagini = images
        return {"input_ids": _Gettoni([[1, 2, 3]])}

    def batch_decode(self, gettoni, skip_special_tokens):
        assert gettoni == [[9, 9]]
        return [self.risposta]


class _Modello:
    device = "cpu"
    dtype = None

    def __init__(self):
        self.opzioni = None

    def generate(self, **opzioni):
        self.opzioni = opzioni
        return _Gettoni([[1, 2, 3, 9, 9]])


def test_chiedi_toglie_i_pensieri_e_tiene_solo_la_risposta():
    torch = pytest.importorskip("torch")
    del torch
    preparatore = _Preparatore("<think>boh</think>\nDESCRIZIONE: un cane")
    modello = _Modello()
    detto = modulo.chiedi(preparatore, modello, [{"role": "user", "content": "x"}])
    assert detto == "DESCRIZIONE: un cane"
    assert preparatore.discorsi[0][1] == {"enable_thinking": False}
    assert modello.opzioni["do_sample"] is False


def test_il_discorso_si_monta_anche_senza_il_permesso_di_non_pensare():
    preparatore = _Preparatore("", senza_pensieri=False)
    assert modulo.monta_il_discorso(preparatore, []) == "domanda"


def test_senza_scheda_video_lo_dice_chiaro(tmp_path):
    from officina.descrittori.torcia import Macchina

    with pytest.raises(modulo.ServeLaScheda) as guasto:
        modulo.carica(tmp_path, Macchina("cpu", "processore", 0))
    assert "NVIDIA" in str(guasto.value)


@pytest.mark.parametrize("lati", [(4000, 3000), (3000, 4000), (10, 8), (800, 600)])
def test_la_foto_arriva_della_misura_giusta(lati):
    pronta = modulo._pronta(Image.new("L", lati))
    assert pronta.mode == "RGB"
    assert max(pronta.size) <= modulo.LATO
    assert min(pronta.size) >= 32


def test_i_pensieri_lasciati_a_meta_non_finiscono_nel_testo():
    assert modulo.senza_riflessioni("ragiono\n</think>\nSCRITTE: Bar") == "SCRITTE: Bar"
