from __future__ import annotations

import io
import pickle
import zipfile

import pytest

from officina.corpi import solo_numeri


class _Comando:

    def __init__(self, bersaglio):
        self.bersaglio = bersaglio

    def __reduce__(self):
        return (open, (str(self.bersaglio), "w"))


def _archivio(percorso, oggetto, radice="archivio"):
    with zipfile.ZipFile(percorso, "w") as zz:
        zz.writestr(f"{radice}/data.pkl", pickle.dumps(oggetto, protocol=2))
        zz.writestr(f"{radice}/version", "3\n")


def test_il_lettore_rifiuta_quello_che_non_e_un_numero(tmp_path):
    bersaglio = tmp_path / "eseguito.txt"
    file = tmp_path / "cattivo.pt"
    _archivio(file, {"pesi": _Comando(bersaglio)})
    with pytest.raises(solo_numeri.FileNonValido):
        solo_numeri.leggi(file, {"__torch__": {"MHRDemo"}})
    assert not bersaglio.exists()


def test_il_lettore_largo_non_esegue_niente(tmp_path):
    bersaglio = tmp_path / "eseguito.txt"
    file = tmp_path / "cattivo.pt"
    _archivio(file, {"state_dict": {}, "hyper_parameters": _Comando(bersaglio)})
    letto = solo_numeri.leggi(file)
    assert not bersaglio.exists()
    assert isinstance(letto["hyper_parameters"], solo_numeri.Oggetto)


def test_il_lettore_prende_i_pesi_e_lascia_il_resto(tmp_path):
    torch = pytest.importorskip("torch")
    bersaglio = tmp_path / "eseguito.txt"
    file = tmp_path / "buono.ckpt"
    pesi = {"a.weight": torch.arange(12, dtype=torch.float32).reshape(3, 4),
            "a.bias": torch.nn.Parameter(torch.ones(4)),
            "b.idx": torch.tensor([3, 1, 2], dtype=torch.int64),
            "c.vista": torch.arange(20, dtype=torch.float32)[5:15:2]}
    torch.save({"state_dict": pesi, "hyper_parameters": _Comando(bersaglio)}, file)
    letti = solo_numeri.pesi(file)
    assert not bersaglio.exists()
    assert set(letti) == set(pesi)
    for nome, valore in pesi.items():
        assert torch.equal(letti[nome], valore.detach())


def test_le_misure_risolvono_i_rimandi(tmp_path):
    pytest.importorskip("yaml")
    from officina.corpi import corpo3d

    file = tmp_path / "model_config.yaml"
    file.write_text("MODEL:\n  IMAGE_SIZE: [512, 512]\n  ALTRO: ${MODEL.IMAGE_SIZE}\n"
                    "  DECODER:\n    DIM: 1024\n")
    misure = corpo3d.carica_le_misure(file)
    assert misure.MODEL.ALTRO == [512, 512]
    assert misure.MODEL.DECODER.DIM == 1024
    assert misure.MODEL.DECODER.get("ASSENTE", 7) == 7


def test_il_ritaglio_mette_la_persona_al_centro():
    pytest.importorskip("cv2")
    import numpy as np

    from officina.corpi import corpo3d

    pezzo = corpo3d._un_ritaglio(np.zeros((480, 640, 3), dtype=np.uint8), [100, 50, 300, 450],
                                 corpo3d.MARGINE_CORPO, (512, 512))
    centro = pezzo["affine_trans"] @ np.array([200.0, 250.0, 1.0])
    assert np.allclose(centro, [256, 256], atol=1e-3)
    assert np.allclose(pezzo["bbox_scale"], [500.0, 500.0])
    assert pezzo["img"].shape == (512, 512, 3)


def test_le_rotazioni_vanno_e_tornano():
    torch = pytest.importorskip("torch")
    from officina.corpi import rotazioni

    torch.manual_seed(0)
    angoli = (torch.rand(200, 3) - 0.5) * 2.0
    for convenzione in ("xyz", "XZY", "ZYX"):
        matrici = rotazioni.euler_in_matrice(convenzione, angoli)
        assert torch.allclose(matrici @ matrici.transpose(-1, -2), torch.eye(3).expand(200, 3, 3), atol=1e-5)
        assert torch.allclose(rotazioni.matrice_in_euler(convenzione, matrici), angoli, atol=1e-4)


def test_dinov3_da_la_griglia_giusta():
    torch = pytest.importorskip("torch")
    from officina.corpi.dinov3_rete import Dinov3Backbone

    rete = Dinov3Backbone("dinov3_vits16").eval()
    with torch.no_grad():
        uscita = rete(torch.randn(1, 3, 64, 48))
    assert uscita.shape == (1, 384, 4, 3)
    assert torch.isfinite(uscita).all()


def _mhr_finto(torch, vertici=18439, giunti=127, nascosti=8):
    numeri = {
        "forme": torch.randn(45, vertici, 3) * 0.01,
        "base": torch.randn(vertici, 3) * 50,
        "espressioni": torch.zeros(72, vertici, 3),
        "trasformazione": torch.randn(giunti * 7, 204 + 45) * 0.01,
        "spostamenti": torch.randn(giunti, 3),
        "prerotazioni": torch.tensor([0.0, 0.0, 0.0, 1.0]).repeat(giunti, 1),
        "catena": torch.stack([torch.arange(1, giunti), torch.zeros(giunti - 1, dtype=torch.long)]),
        "anelli": [giunti - 1],
        "padri": torch.zeros(giunti, dtype=torch.long),
        "posa_inversa": torch.tensor([0, 0, 0, 0, 0, 0, 1, 1.0]).repeat(giunti, 1),
        "pelle_giunti": torch.randint(0, giunti, (vertici,)),
        "pelle_pesi": torch.ones(vertici),
        "pelle_vertici": torch.arange(vertici),
        "vertici": vertici,
        "facce": torch.randint(0, vertici, (36874, 3)),
        "correttivi_primo": torch.zeros(nascosti, (giunti - 2) * 6),
        "correttivi_secondo": torch.zeros(vertici * 3, nascosti),
        "nomi_dei_giunti": [], "nomi_dei_parametri": [], "limiti": None,
    }
    from officina.corpi import mhr

    return mhr.Mhr(numeri)


def test_mhr_fermo_lascia_il_corpo_dov_e():
    torch = pytest.importorskip("torch")
    modello = _mhr_finto(torch, vertici=50, giunti=5)
    modello.n["trasformazione"] = torch.zeros(5 * 7, 204 + 45)
    modello.n["spostamenti"] = torch.zeros(5, 3)
    vertici, scheletro = modello(torch.zeros(2, 45), torch.zeros(2, 204), torch.zeros(2, 72))
    assert torch.allclose(vertici, modello.n["base"].expand(2, 50, 3), atol=1e-4)
    assert scheletro.shape == (2, 5, 8)


MISURE_PICCOLE = """
MODEL:
  IMAGE_SIZE: [128, 128]
  IMAGE_MEAN: [0.485, 0.456, 0.406]
  IMAGE_STD: [0.229, 0.224, 0.225]
  BACKBONE: {TYPE: dinov3_vits16}
  MHR_HEAD: {MLP_DEPTH: 2, MLP_CHANNEL_DIV_FACTOR: 1}
  CAMERA_HEAD: {MLP_DEPTH: 2, MLP_CHANNEL_DIV_FACTOR: 1}
  PROMPT_ENCODER: {ENABLE: true, PROMPT_KEYPOINTS: mhr70, MASK_EMBED_TYPE: v1, MASK_PROMPT: v1}
  DECODER:
    TYPE: sam
    DIM: 64
    DEPTH: 2
    HEADS: 4
    DIM_HEAD: 16
    MLP_DIM: 128
    LAYER_SCALE_INIT: 0.0
    FFN_TYPE: origin
    ENABLE_TWOWAY: true
    REPEAT_PE: true
    DO_INTERM_PREDS: true
    DO_KEYPOINT_TOKENS: true
    KEYPOINT_TOKEN_UPDATE: true
    DO_KEYPOINT3D_TOKENS: true
    DO_HAND_DETECT_TOKENS: true
    CONDITION_TYPE: cliff
"""


def test_la_rete_ricostruisce_una_persona(tmp_path):
    torch = pytest.importorskip("torch")
    pytest.importorskip("cv2")
    pytest.importorskip("yaml")
    import numpy as np

    from officina.corpi import corpo3d
    from officina.corpi.corpo3d_rete import SAM3DBody
    from officina.corpi.dinov3_rete import Dinov3Backbone

    torch.manual_seed(0)
    file = tmp_path / "model_config.yaml"
    file.write_text(MISURE_PICCOLE)
    rete = SAM3DBody(corpo3d.carica_le_misure(file), _mhr_finto(torch), Dinov3Backbone("dinov3_vits16")).eval()
    with torch.no_grad():
        for testa in (rete.head_pose, rete.head_pose_hand):
            testa.scale_comps.normal_(0, 0.05)
            testa.hand_joint_idxs_left.copy_(torch.arange(62, 89))
            testa.hand_joint_idxs_right.copy_(torch.arange(89, 116))
            mappa = torch.rand(308, 18439 + 127)
            testa.keypoint_mapping.copy_(mappa / mappa.sum(1, keepdim=True))
            testa.local_to_world_wrist.copy_(torch.eye(3))
            testa.joint_rotation.copy_(torch.eye(3).repeat(127, 1, 1))
            testa.nonhand_param_idxs.copy_(torch.arange(145))
    immagine = (np.random.default_rng(0).random((120, 160, 3)) * 255).astype(np.uint8)
    maschera = np.zeros((1, 120, 160), dtype=np.uint8)
    maschera[0, 20:100, 50:110] = 1
    posa = corpo3d.ricostruisci(rete, immagine, np.array([[40.0, 10.0, 120.0, 110.0]]), maschera)
    figure = corpo3d.in_figure(posa)
    assert len(figure) == 1
    figura = figure[0]
    assert len(figura.forma) == 45 and len(figura.scala) == 28 and len(figura.parametri) == 204
    assert len(figura.punti_3d) == 70 and len(figura.punti_2d) == 70
    assert posa["pred_vertices"].shape == (1, 18439, 3)
    assert all(np.isfinite(np.array(figura.parametri)))
