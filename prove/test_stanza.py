from __future__ import annotations

import numpy as np
import pytest


def _rotazione(asse, angolo):
    asse = np.asarray(asse, dtype=np.float64)
    asse = asse / np.linalg.norm(asse)
    x, y, z = asse
    c, s = np.cos(angolo), np.sin(angolo)
    return np.array([[c + x * x * (1 - c), x * y * (1 - c) - z * s, x * z * (1 - c) + y * s],
                     [y * x * (1 - c) + z * s, c + y * y * (1 - c), y * z * (1 - c) - x * s],
                     [z * x * (1 - c) - y * s, z * y * (1 - c) + x * s, c + z * z * (1 - c)]])


def _macchine(quante, seme):
    caso = np.random.default_rng(seme)
    fuori = []
    for _ in range(quante):
        matrice = np.eye(4)
        matrice[:3, :3] = _rotazione(caso.normal(size=3), caso.uniform(-1, 1))
        matrice[:3, 3] = caso.normal(size=3)
        fuori.append(matrice)
    return np.asarray(fuori)


def _da_lontano(estrinseci, r, t, s):
    pose = np.linalg.inv(estrinseci)
    nuove = pose.copy()
    nuove[:, :3, :3] = r @ pose[:, :3, :3]
    nuove[:, :3, 3] = s * (pose[:, :3, 3] @ r.T) + t
    return np.linalg.inv(nuove)


def test_umeyama_ritrova_rotazione_spostamento_e_scala():
    from officina.stanza.allineamento import umeyama

    caso = np.random.default_rng(1)
    punti = caso.normal(size=(3, 20))
    r = _rotazione([1, 2, 3], 0.7)
    t = np.array([0.5, -1.0, 2.0])
    spostati = 2.5 * (r @ punti) + t[:, None]
    rr, tt, ss = umeyama(punti, spostati)
    assert np.allclose(rr, r) and np.allclose(tt, t) and ss == pytest.approx(2.5)


def test_umeyama_rifiuta_le_macchine_tutte_nello_stesso_punto():
    from officina.stanza.allineamento import umeyama

    with pytest.raises(ValueError):
        umeyama(np.ones((3, 5)), np.ones((3, 5)))


@pytest.mark.parametrize("ransac", [False, True])
def test_le_macchine_si_allineano_alle_vere(ransac):
    from officina.stanza import da3
    from officina.stanza.allineamento import allinea_le_macchine

    vere = _macchine(12, 2)
    r = _rotazione([0, 1, 0], 0.4)
    t = np.array([1.0, 0.2, -0.3])
    stimate = _da_lontano(vere, r.T, -(r.T @ t) / 3.0, 1 / 3.0)
    rr, tt, ss = allinea_le_macchine(vere, stimate, ransac=ransac, seme=42)
    assert ss == pytest.approx(3.0)
    assert np.allclose(da3._applica(stimate, rr, tt, ss), vere, atol=1e-8)


def test_dai_pesi_si_tolgono_solo_le_parti_che_non_servono():
    from officina.stanza import da3

    letti = {"model.da3.backbone.pretrained.cls_token": 1, "model.da3.gs_head.x": 2,
             "model.da3.head.scratch.refinenet1_aux.out_conv.weight": 3, "model.da3_metric.head.y": 4}
    assert da3.pesi_da_usare(letti) == {"da3.backbone.pretrained.cls_token": 1, "da3_metric.head.y": 4}
    with pytest.raises(ValueError):
        da3.pesi_da_usare({"da3.backbone.cls_token": 1})


def test_le_misure_vanno_al_multiplo_di_14_piu_vicino():
    from officina.stanza import da3

    assert da3._multiplo_vicino(504, 14) == 504
    assert da3._multiplo_vicino(283, 14) == 280
    assert da3._multiplo_vicino(287, 14) == 294
    assert da3._multiplo_vicino(7, 14) == 14
    matrice = np.array([[1000.0, 0, 500], [0, 1000, 375], [0, 0, 1]])
    nuova = da3._riscala(matrice, 1000, 750, 504, 378)
    assert nuova[0, 0] == pytest.approx(504) and nuova[1, 2] == pytest.approx(189)
    assert da3._riscala(None, 1, 1, 2, 2) is None


def test_quaternioni_e_pose_tornano_indietro():
    torch = pytest.importorskip("torch")
    from officina.stanza import geometria

    rotazioni = torch.tensor(np.stack([_rotazione([1, 0, 1], 0.3), _rotazione([0, 1, 2], -1.2)]),
                             dtype=torch.float32)
    di_nuovo = geometria.quaternione_a_matrice(geometria.matrice_a_quaternione(rotazioni))
    assert torch.allclose(di_nuovo, rotazioni, atol=1e-5)
    estrinseci = torch.tensor(_macchine(3, 5), dtype=torch.float32)[None]
    intrinseci = torch.tensor([[[300.0, 0, 252], [0, 310, 168], [0, 0, 1]]] * 3)[None]
    codice = geometria.codifica_posa(estrinseci, intrinseci, (336, 504))
    tornati, fuochi = geometria.decodifica_posa(codice, (336, 504))
    assert torch.allclose(tornati, estrinseci[..., :3, :], atol=1e-5)
    assert torch.allclose(fuochi, intrinseci, atol=1e-3)
    assert torch.allclose(geometria.inversa_affine(estrinseci) @ estrinseci, torch.eye(4).expand(1, 3, 4, 4),
                          atol=1e-5)


def test_vggt_ritaglia_le_foto_troppo_lunghe_o_troppo_alte():
    from PIL import Image

    from officina.stanza import vggt

    larga, taglio = vggt._ritaglia(Image.new("RGB", (1000, 300)))
    assert larga.size == (600, 300) and taglio == (200, 0)
    alta, taglio = vggt._ritaglia(Image.new("RGB", (300, 900)))
    assert alta.size == (300, 600) and taglio == (0, 150)
    normale, taglio = vggt._ritaglia(Image.new("RGB", (640, 480)))
    assert normale.size == (640, 480) and taglio == (0, 0)


def test_vggt_misure_come_l_originale():
    from officina.stanza import vggt

    assert vggt._misura_bilanciata(2 / 3, 512, 16) == (416, 624)
    assert vggt._misura_bilanciata(1.0, 512, 16) == (512, 512)
    assert vggt._misura_massima(2 / 3, 512, 16) == (336, 512)
    assert vggt._misura_massima(1.5, 512, 16) == (512, 336)


def test_vggt_riporta_gli_intrinseci_sulla_foto_vera():
    from officina.stanza import vggt

    viaggio = {"taglio": (200, 0), "scala": (624 / 600, 416 / 400), "aggiunta": (0, 104), "foto": (600, 400)}
    sulla_lastra = np.array([[500.0, 0, 312], [0, 520, 312], [0, 0, 1]])
    sulla_foto = vggt.intrinseci_sulla_foto(sulla_lastra, viaggio)
    assert sulla_foto[0, 0] == pytest.approx(500 * 600 / 624)
    assert sulla_foto[1, 1] == pytest.approx(520 * 400 / 416)
    assert sulla_foto[0, 2] == pytest.approx(312 * 600 / 624 + 200)
    assert sulla_foto[1, 2] == pytest.approx((312 - 104) * 400 / 416)
