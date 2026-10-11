from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

RADICE = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def collaudo():
    spec = importlib.util.spec_from_file_location("collaudo_corpi",
                                                  RADICE / "strumenti" / "collaudo_corpi.py")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def test_abbina_conta_giuste_sbagliate_e_perse(collaudo):
    sicurezze = [0.9, 0.8, 0.6, 0.4]
    sovrapposte = [[0.9, 0.0, 0.0], [0.7, 0.2, 0.0], [0.0, 0.0, 0.8], [0.0, 0.6, 0.0]]
    ignorate = [False, False, True]
    folla = [False, False, False]
    assert collaudo.abbina(sicurezze, sovrapposte, ignorate, folla, 0.5)[:3] == (1, 1, 1)
    giuste, sbagliate, perse, coppie = collaudo.abbina(sicurezze, sovrapposte, ignorate, folla, 0.3)
    assert (giuste, sbagliate, perse) == (2, 1, 0)
    assert coppie == {0: 0, 3: 1}


def test_abbina_non_conta_sbagliata_una_persona_nella_folla(collaudo):
    assert collaudo.abbina([0.9], [[0.7]], [False], [True], 0.5)[:3] == (0, 0, 0)


def test_confronta_i_punti_per_soglia(collaudo):
    annotazione = {"area": 10000.0, "keypoints": [50, 50, 2, 0, 0, 0, 10, 10, 1] + [0, 0, 0] * 14}
    punti = [(0.5, 0.5, 0.9), (0.2, 0.2, 0.4), (0.9, 0.9, 0.2)] + [(0.0, 0.0, 0.0)] * 14
    conti = {0.3: {"giusti": 0, "sbagliati": 0, "persi": 0},
             0.5: {"giusti": 0, "sbagliati": 0, "persi": 0}}
    segnati = {"segnati": 0, "al_posto_giusto": 0}
    collaudo.confronta_i_punti(punti, annotazione, 100, 100, conti, range(3), segnati)
    assert conti[0.3] == {"giusti": 1, "sbagliati": 1, "persi": 0}
    assert conti[0.5] == {"giusti": 1, "sbagliati": 0, "persi": 0}
    assert segnati == {"segnati": 2, "al_posto_giusto": 1}


def test_le_sicurezze_si_dividono_per_gruppo(collaudo):
    annotazione = {"area": 10000.0, "keypoints": [50, 50, 2, 50, 50, 1, 0, 0, 0] + [0, 0, 0] * 14}
    punti = [(0.5, 0.5, 3.2), (0.9, 0.9, 1.4), (0.2, 0.2, 0.6)] + [(0.0, 0.0, 0.0)] * 14
    conti = {0.3: {"giusti": 0, "sbagliati": 0, "persi": 0}}
    sicurezze = {gruppo: [] for gruppo in collaudo.GRUPPI}
    collaudo.confronta_i_punti(punti, annotazione, 100, 100, conti, range(3), sicurezze=sicurezze)
    assert sicurezze == {"al_posto_giusto": [3.2], "fuori_posto": [1.4], "non_segnati": [0.6]}


def test_i_quantili_delle_sicurezze(collaudo):
    assert collaudo._quantili([]) == {"quanti": 0}
    breve = collaudo._quantili([float(v) for v in range(1, 101)])
    assert breve["quanti"] == 100 and breve["sotto_1"] == 0.0
    assert (breve["p5"], breve["p50"], breve["p95"], breve["massimo"]) == (6.0, 51.0, 96.0, 100.0)
    assert collaudo._quantili([0.5, 2.0])["sotto_1"] == 0.5


class SessioneFinta:

    def get_inputs(self):
        from types import SimpleNamespace

        return [SimpleNamespace(name="input")]

    def run(self, _, ingressi):
        import numpy as np

        assert ingressi["input"].shape == (1, 3, 384, 288)
        lungo_x = np.zeros((1, 2, 576), dtype=np.float32)
        lungo_y = np.zeros((1, 2, 768), dtype=np.float32)
        lungo_x[0, 0, 288], lungo_y[0, 0, 384] = 4.0, 2.0
        lungo_x[0, 1, 100], lungo_y[0, 1, 100] = 0.4, 0.2
        return [lungo_x, lungo_y]


def test_i_punti_grezzi_tengono_la_sicurezza_sopra_uno(collaudo):
    from PIL import Image

    pose = type("Pose", (), {"_sessione": SessioneFinta(), "accendi": lambda self: None})()
    immagine = Image.new("RGB", (200, 400))
    assert collaudo._punti_grezzi(pose, immagine, []) == []
    (punti,) = collaudo._punti_grezzi(pose, immagine, [(50.0, 100.0, 150.0, 300.0)])
    assert punti[0][2] == 3.0 and abs(punti[0][0] - 0.5) < 0.01 and abs(punti[0][1] - 0.5) < 0.01
    assert abs(punti[1][2] - 0.3) < 1e-6


def test_voti_e_la_soglia_migliore(collaudo):
    assert collaudo._voti(8, 2, 2) == {"giusti": 8, "sbagliati": 2, "persi": 2,
                                       "precisione": 0.8, "richiamo": 0.8, "f1": 0.8}
    tabella = {"0.3": {"f1": 0.7}, "0.4": {"f1": 0.8}, "0.6": {"f1": 0.8}}
    assert collaudo._la_migliore(tabella) == "0.4"


def test_le_foto_scelte_hanno_persone_coi_punti(collaudo):
    dati = {"images": [{"id": i} for i in range(1, 11)],
            "annotations": [{"image_id": i, "num_keypoints": 3 if i % 2 else 0, "iscrowd": 0}
                            for i in range(1, 11)]}
    scelte = collaudo.scegli_le_foto(dati, 3)
    assert [foto["id"] for foto, _ in scelte] == [1, 3, 7]
    assert len(collaudo.scegli_le_foto(dati, 50)) == 5


class SeparatoreFinto:

    def __init__(self, *_):
        pass

    def accendi(self):
        pass

    def spegni(self):
        pass

    def guarda(self, immagine):
        return "uscita", (immagine.size[1], immagine.size[0])

    def scegli(self, uscita, misura, sicurezza_minima, soglia_maschera):
        import numpy as np

        alta, larga = misura
        maschera = np.zeros((alta, larga), dtype=bool)
        maschera[10:90, 20:60] = True
        return [((20.0, 10.0, 60.0, 90.0), 0.9, maschera)]


class PoseFinta:

    def __init__(self, *_):
        pass

    def accendi(self):
        pass

    def spegni(self):
        pass

    def punti(self, immagine, riquadri):
        larga, alta = immagine.size
        return [[(40 / larga, 30 / alta, 0.8)] * 17 for _ in riquadri]


def test_la_prova_intera_con_modelli_finti(collaudo, monkeypatch, tmp_path):
    import numpy as np
    from PIL import Image

    from officina.corpi import rtmw, sam3

    dati = {"images": [{"id": 1, "file_name": "uno.jpg"}],
            "annotations": [{"image_id": 1, "num_keypoints": 1, "iscrowd": 0, "area": 3200.0,
                             "bbox": [20, 10, 40, 80],
                             "keypoints": [40, 30, 2] + [0, 0, 0] * 16}]}

    def scarica(url, dove):
        dove.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (100, 100)).save(dove)
        return dove

    def maschera_vera(annotazione, alta, larga):
        maschera = np.zeros((alta, larga), dtype=bool)
        x, y, w, h = annotazione["bbox"]
        maschera[y:y + h, x:x + w] = True
        return maschera

    monkeypatch.setattr(collaudo, "_annotazioni", lambda cartella: dati)
    monkeypatch.setattr(collaudo, "_scarica", scarica)
    monkeypatch.setattr(collaudo, "_maschera_vera", maschera_vera)
    monkeypatch.setattr(collaudo, "_punti_grezzi", lambda pose, immagine, riquadri: pose.punti(immagine, riquadri))
    monkeypatch.setattr(sam3, "Separatore", SeparatoreFinto)
    monkeypatch.setattr(rtmw, "Pose", PoseFinta)
    esito = {"prova": collaudo.prova(tmp_path, tmp_path, 5),
             "sam3": {"file": {"model.safetensors": {"uguale_a_hugging_face": True}}}}
    assert esito["prova"]["persone"]["0.5"]["giusti"] == 1
    assert esito["prova"]["contorni"]["0.5"]["media"] == 1.0
    assert esito["prova"]["al_posto_giusto"] == {"veri": 1.0, "veri_bgr": 1.0, "trovati": 1.0}
    assert esito["prova"]["punti_sui_riquadri_di_sam3"]["corpo"]["0.3"]["sbagliati"] == 16
    assert esito["prova"]["sicurezze_grezze"]["corpo"]["al_posto_giusto"]["quanti"] == 1
    assert esito["prova"]["sicurezze_grezze"]["corpo"]["non_segnati"]["quanti"] == 16
    riassunto = collaudo.riassunto(esito)
    assert riassunto["persona"]["adesso"] == 0.65
    assert collaudo.controlla(esito) == []

    solo = {"prova": collaudo.prova_dei_punti(tmp_path, tmp_path, 5)}
    assert solo["prova"]["persone_coi_punti"] == 1
    assert solo["prova"]["al_posto_giusto"] == {"veri": 1.0, "veri_bgr": 1.0}
    assert "persona" not in collaudo.riassunto(solo)
    assert collaudo.riassunto(solo)["punto"]["voti_adesso_corpo"]["giusti"] == 1
    assert collaudo.controlla(solo) == []
