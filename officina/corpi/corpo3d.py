from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

NOME = "corpo3d"
FILE_PESI = "model.ckpt"
FILE_MISURE = "model_config.yaml"
FILE_MHR = "mhr_model.pt"
MARGINE_CORPO = 1.25
MARGINE_MANO = 0.9
SOGLIA_DEL_POLSO = 1.4
LATO_MINIMO_DELLA_MANO = 64
MANO_DENTRO = 0.5
POLSO_VICINO = 0.25
POLSO_DESTRO, POLSO_SINISTRO = 41, 62
GOMITO_DESTRO, GOMITO_SINISTRO = 8, 7


class Configurazione(dict):

    def __getattr__(self, nome):
        try:
            valore = self[nome]
        except KeyError as assente:
            raise AttributeError(nome) from assente
        return Configurazione(valore) if isinstance(valore, dict) else valore

    def get(self, nome, altrimenti=None):
        valore = super().get(nome, altrimenti)
        return Configurazione(valore) if isinstance(valore, dict) else valore


@dataclass
class Figura:
    forma: list[float]
    scala: list[float]
    parametri: list[float]
    spostamento: list[float]
    fuoco: float
    punti_3d: list[list[float]]
    punti_2d: list[list[float]]


def _centro_e_misura(riquadro, margine):
    x1, y1, x2, y2 = (float(v) for v in riquadro)
    return np.array([(x1 + x2) * 0.5, (y1 + y2) * 0.5]), np.array([x2 - x1, y2 - y1]) * margine


def _proporzione(misura, rapporto):
    w, h = misura
    return np.array([w, w / rapporto]) if w > h * rapporto else np.array([h * rapporto, h])


def _terzo_punto(a, b):
    verso = a - b
    return b + np.r_[-verso[1], verso[0]]


def matrice_di_ritaglio(centro, misura, lato):
    import cv2

    largo, alto = lato
    sorgente = np.zeros((3, 2), dtype=np.float32)
    sorgente[0, :] = centro
    sorgente[1, :] = centro + np.array([0.0, misura[0] * -0.5])
    sorgente[2, :] = _terzo_punto(sorgente[0, :], sorgente[1, :])
    arrivo = np.zeros((3, 2), dtype=np.float32)
    arrivo[0, :] = [largo * 0.5, alto * 0.5]
    arrivo[1, :] = np.array([largo * 0.5, alto * 0.5]) + np.array([0.0, largo * -0.5])
    arrivo[2, :] = _terzo_punto(arrivo[0, :], arrivo[1, :])
    return cv2.getAffineTransform(np.float32(sorgente), np.float32(arrivo))


def _un_ritaglio(immagine, riquadro, margine, lato, maschera=None):
    import cv2

    centro, misura = _centro_e_misura(riquadro, margine)
    misura = _proporzione(_proporzione(misura, 0.75), lato[0] / lato[1])
    trasformazione = matrice_di_ritaglio(centro, misura, lato)
    ritagliata = cv2.warpAffine(immagine, trasformazione, (int(lato[0]), int(lato[1])), flags=cv2.INTER_LINEAR)
    alto, largo = immagine.shape[:2]
    if maschera is not None:
        maschera_ritagliata = cv2.warpAffine(maschera, trasformazione, (int(lato[0]), int(lato[1])),
                                             flags=cv2.INTER_LINEAR)
        punteggio = np.float32(1.0)
    else:
        maschera_ritagliata = np.zeros((int(lato[1]), int(lato[0])), dtype=np.uint8)
        punteggio = np.float32(0.0)
    return {"img": ritagliata, "bbox": np.asarray(riquadro, dtype=np.float64), "bbox_center": centro,
            "bbox_scale": misura, "ori_img_size": np.array([largo, alto]), "img_size": np.array(lato),
            "affine_trans": trasformazione, "mask": maschera_ritagliata, "mask_score": punteggio}


def fuoco_di_base(larga: int, alta: int) -> float:
    return float((alta ** 2 + larga ** 2) ** 0.5)


def camera(larga: int, alta: int, fuoco: float | None):
    import torch

    f = fuoco if fuoco else fuoco_di_base(larga, alta)
    return torch.tensor([[[f, 0, larga / 2.0], [0, f, alta / 2.0], [0, 0, 1]]])


def prepara(immagine, riquadri, lato, margine, maschere=None, cam_int=None, dispositivo="cpu"):
    import torch

    pezzi = [_un_ritaglio(immagine, r, margine, lato, None if maschere is None else maschere[i])
             for i, r in enumerate(riquadri)]
    lotto = {}
    for chiave in ("bbox", "bbox_center", "bbox_scale", "ori_img_size", "img_size", "affine_trans",
                   "mask", "mask_score"):
        lotto[chiave] = torch.from_numpy(np.stack([p[chiave] for p in pezzi])).unsqueeze(0).float()
    lotto["img"] = torch.from_numpy(np.stack([p["img"] for p in pezzi])).permute(0, 3, 1, 2).float().div(255).unsqueeze(0)
    lotto["mask"] = lotto["mask"].unsqueeze(2)
    lotto["person_valid"] = torch.ones((1, len(pezzi)))
    alto, largo = immagine.shape[:2]
    lotto["cam_int"] = (cam_int if cam_int is not None else camera(largo, alto, None)).clone().float()
    return {k: v.to(dispositivo) for k, v in lotto.items()}


def _scatole_delle_mani(rete, uscita, lotto):
    lato = rete.cfg.MODEL.IMAGE_SIZE[0]
    scatole = uscita["mhr"]["hand_box"].detach().cpu().numpy() * lato
    trasformazione = lotto["affine_trans"][0].cpu().numpy()
    risultato = []
    for indice in (0, 1):
        scatola = scatole[:, indice]
        centro = scatola[:, :2]
        misura = scatola[:, 2:].max(axis=1, keepdims=True).repeat(2, axis=1)
        misura = misura / trasformazione[:, 0, 0][:, None]
        centro = (centro - trasformazione[:, [0, 1], [2, 2]]) / trasformazione[:, 0, 0][:, None]
        risultato.append(np.concatenate([centro - misura / 2, centro + misura / 2], axis=1))
    return risultato[0], risultato[1]


def ricostruisci(rete, immagine, riquadri, maschere=None, cam_int=None):
    import torch

    from officina.corpi import corpo3d_rete as r, rotazioni

    dispositivo = rete.dispositivo
    alto, largo = immagine.shape[:2]
    lato = tuple(r._due(rete.cfg.MODEL.IMAGE_SIZE))
    if cam_int is None:
        cam_int = camera(largo, alto, None)
    lotto = prepara(immagine, riquadri, lato, MARGINE_CORPO, maschere, cam_int, dispositivo)
    with torch.no_grad():
        uscita = rete.passo(lotto, mano=False)
        sinistra, destra = _scatole_delle_mani(rete, uscita, lotto)
        polsi_prima = rotazioni.euler_in_matrice(
            "XZY", uscita["mhr"]["body_pose"][:, [41, 43, 42, 31, 33, 32]].unflatten(1, (2, 3)))
        specchiata = np.ascontiguousarray(immagine[:, ::-1])
        provvisoria = sinistra.copy()
        sinistra[:, 0] = largo - provvisoria[:, 2] - 1
        sinistra[:, 2] = largo - provvisoria[:, 0] - 1
        lotto_s = prepara(specchiata, sinistra, lato, MARGINE_MANO, None, cam_int, dispositivo)
        mano_s = rete.passo(lotto_s, mano=True)["mhr_hand"]
        hp = rete.head_pose
        mano_s["scale"][:, 9] = ((hp.scale_mean[8].item() + hp.scale_comps[8, 8].item() * mano_s["scale"][:, 8])
                                 - hp.scale_mean[9].item()) / hp.scale_comps[9, 9].item()
        mano_s["joint_global_rots"][:, 78] = mano_s["joint_global_rots"][:, 42].clone()
        mano_s["joint_global_rots"][:, 78, [1, 2], :] *= -1
        mano_s["hand"][:, :54] = mano_s["hand"][:, 54:]
        lotto_s["bbox_center"][:, :, 0] = largo - lotto_s["bbox_center"][:, :, 0] - 1
        lotto_d = prepara(immagine, destra, lato, MARGINE_MANO, None, cam_int, dispositivo)
        mano_d = rete.passo(lotto_d, mano=True)["mhr_hand"]
        rotazioni_corpo = uscita["mhr"]["joint_global_rots"]
        avambracci = rotazioni_corpo[:, torch.LongTensor([76, 40]).to(dispositivo)]
        polsi_zero = avambracci @ hp.joint_rotation[torch.LongTensor([77, 41]).to(dispositivo)]
        polsi_mani = torch.stack([mano_s["joint_global_rots"][:, 78], mano_d["joint_global_rots"][:, 42]], dim=1)
        polsi_nuovi = torch.einsum("kabc,kabd->kadc", polsi_mani, polsi_zero)
        valido_angolo = r.differenza_di_rotazione(polsi_prima, polsi_nuovi) < SOGLIA_DEL_POLSO
        valido_misura = torch.stack(
            [(lotto_s["bbox_scale"].flatten(0, 1) > LATO_MINIMO_DELLA_MANO).all(dim=1),
             (lotto_d["bbox_scale"].flatten(0, 1) > LATO_MINIMO_DELLA_MANO).all(dim=1)], dim=1)
        valido_dentro = torch.stack(
            [mano_s["pred_keypoints_2d_cropped"].abs().amax(dim=(1, 2)) < MANO_DENTRO,
             mano_d["pred_keypoints_2d_cropped"].abs().amax(dim=(1, 2)) < MANO_DENTRO], dim=1)
        destro_mano = mano_d["pred_keypoints_2d"][:, [POLSO_DESTRO]].clone()
        sinistro_mano = mano_s["pred_keypoints_2d"][:, [POLSO_DESTRO]].clone()
        sinistro_mano[:, :, 0] = largo - sinistro_mano[:, :, 0] - 1
        destro_corpo = uscita["mhr"]["pred_keypoints_2d"][:, [POLSO_DESTRO]].clone()
        sinistro_corpo = uscita["mhr"]["pred_keypoints_2d"][:, [POLSO_SINISTRO]].clone()
        distanza_d = (destro_mano - destro_corpo).flatten(0, 1).norm(dim=-1) / lotto_s["bbox_scale"].flatten(0, 1)[:, 0]
        distanza_s = (sinistro_mano - sinistro_corpo).flatten(0, 1).norm(dim=-1) / lotto_d["bbox_scale"].flatten(0, 1)[:, 0]
        valido_polso = torch.stack([distanza_s < POLSO_VICINO, distanza_d < POLSO_VICINO], dim=1)
        mani_valide = valido_angolo & valido_misura & valido_dentro & valido_polso

        rete._inizia(lotto)
        rete.hand_batch_idx = []
        rete.body_batch_idx = list(range(lotto["img"].shape[0] * lotto["img"].shape[1]))
        gomito_d = uscita["mhr"]["pred_keypoints_2d"][:, [GOMITO_DESTRO]].clone()
        gomito_s = uscita["mhr"]["pred_keypoints_2d"][:, [GOMITO_SINISTRO]].clone()
        suggerimento = torch.cat([rete._full_to_crop(lotto, destro_mano), rete._full_to_crop(lotto, sinistro_mano),
                                  rete._full_to_crop(lotto, gomito_d), rete._full_to_crop(lotto, gomito_s)], dim=1)
        suggerimento = torch.cat([suggerimento, suggerimento[..., [-1]]], dim=-1)
        suggerimento[:, 0, -1] = POLSO_DESTRO
        suggerimento[:, 1, -1] = POLSO_SINISTRO
        suggerimento[:, 2, -1] = GOMITO_DESTRO
        suggerimento[:, 3, -1] = GOMITO_SINISTRO
        if suggerimento.shape[0] > 1:
            fuori = ((suggerimento[..., 0] < -0.5) | (suggerimento[..., 0] > 0.5) | (suggerimento[..., 1] < -0.5)
                     | (suggerimento[..., 1] > 0.5) | (~mani_valide[..., [1, 0, 1, 0]])).unsqueeze(-1)
            finto = torch.zeros((1, 1, 3)).to(suggerimento)
            finto[:, :, -1] = -2
            suggerimento[:, :, :2] = torch.clamp(suggerimento[:, :, :2] + 0.5, min=0.0, max=1.0)
            suggerimento = torch.where(fuori, finto, suggerimento)
        else:
            dentro = (torch.all((suggerimento[:, :, :2] > -0.5) & (suggerimento[:, :, :2] < 0.5), dim=2)
                      & mani_valide[..., [1, 0, 1, 0]]).squeeze()
            suggerimento = suggerimento[:, dentro]
            suggerimento[:, :, :2] = torch.clamp(suggerimento[:, :, :2] + 0.5, min=0.0, max=1.0)
        if suggerimento.numel() != 0:
            uscita = rete.ancora_con_i_punti(lotto, uscita, suggerimento)
        posa = uscita["mhr"]
        mani_nuove = torch.cat([mano_s["hand"][:, :54], mano_d["hand"][:, 54:]], dim=1)
        scala_nuova = posa["scale"].clone()
        scala_nuova[:, 9] = mano_s["scale"][:, 9]
        scala_nuova[:, 8] = mano_d["scale"][:, 8]
        scala_nuova[:, 18:] = (mano_s["scale"][:, 18:] + mano_d["scale"][:, 18:]) / 2
        forma_nuova = posa["shape"].clone()
        forma_nuova[:, 40:] = (mano_s["shape"][:, 40:] + mano_d["shape"][:, 40:]) / 2
        rotazioni_giunti = hp.mhr_forward(posa["global_rot"] * 0, posa["global_rot"], posa["body_pose"],
                                          mani_nuove, scala_nuova, forma_nuova, posa["face"],
                                          return_joint_rotations=True)[1]
        avambracci = rotazioni_giunti[:, torch.LongTensor([76, 40]).to(dispositivo)]
        polsi_zero = avambracci @ hp.joint_rotation[torch.LongTensor([77, 41]).to(dispositivo)]
        polsi_nuovi = torch.einsum("kabc,kabd->kadc", polsi_mani, polsi_zero)
        polsi_xzy = r.raddrizza_il_polso(rotazioni.matrice_in_euler("XZY", polsi_nuovi))
        valido = (r.differenza_di_rotazione(polsi_prima, polsi_nuovi) < SOGLIA_DEL_POLSO) & mani_valide
        valido = valido.unsqueeze(-1)
        corpo = posa["body_pose"][:, [41, 43, 42, 31, 33, 32]].unflatten(1, (2, 3))
        posa["body_pose"][:, [41, 43, 42, 31, 33, 32]] = torch.where(valido, polsi_xzy, corpo).flatten(1, 2)
        posa["hand"] = torch.where(valido, mani_nuove.unflatten(1, (2, 54)),
                                   posa["hand"].unflatten(1, (2, 54))).flatten(1, 2)
        scala_mani = torch.stack([posa["scale"][:, 9], posa["scale"][:, 8]], dim=1)
        scala_mani_nuova = torch.stack([scala_nuova[:, 9], scala_nuova[:, 8]], dim=1)
        scelte = torch.where(valido.squeeze(-1), scala_mani_nuova, scala_mani)
        posa["scale"][:, 9] = scelte[:, 0]
        posa["scale"][:, 8] = scelte[:, 1]
        pesi = valido.squeeze(-1)
        somma = pesi.sum(dim=1, keepdim=True)
        posa["scale"][:, 18:] = torch.where(
            somma > 0, (mano_s["scale"][:, 18:] * pesi[:, [0]] + mano_d["scale"][:, 18:] * pesi[:, [1]])
            / (somma + 1e-8), posa["scale"][:, 18:])
        posa["shape"][:, 40:] = torch.where(
            somma > 0, (mano_s["shape"][:, 40:] * pesi[:, [0]] + mano_d["shape"][:, 40:] * pesi[:, [1]])
            / (somma + 1e-8), posa["shape"][:, 40:])
        vertici, j3d, coordinate, parametri, _ = hp.mhr_forward(
            posa["global_rot"] * 0, posa["global_rot"], posa["body_pose"], posa["hand"], posa["scale"],
            posa["shape"], posa["face"], return_keypoints=True, return_joint_coords=True,
            return_model_params=True, return_joint_rotations=True)
        j3d = j3d[:, :70]
        vertici[..., [1, 2]] *= -1
        j3d[..., [1, 2]] *= -1
        coordinate[..., [1, 2]] *= -1
        posa["pred_keypoints_3d"] = j3d
        posa["pred_vertices"] = vertici
        posa["pred_joint_coords"] = coordinate
        posa["mhr_model_params"] = parametri
        proiettati = posa["pred_keypoints_3d"] + posa["pred_cam_t"][:, None, :]
        proiettati[:, :, [0, 1]] *= posa["focal_length"][:, None, None]
        proiettati[:, :, [0, 1]] = proiettati[:, :, [0, 1]] + torch.FloatTensor(
            [largo / 2, alto / 2]).to(proiettati)[None, None, :] * proiettati[:, :, [2]]
        proiettati[:, :, :2] = proiettati[:, :, :2] / proiettati[:, :, [2]]
        posa["pred_keypoints_2d"] = proiettati[:, :, :2]
        posa["mani_valide"] = mani_valide
    return posa


def in_figure(posa) -> list[Figura]:
    figure = []
    for i in range(posa["shape"].shape[0]):
        figure.append(Figura(
            forma=posa["shape"][i].tolist(), scala=posa["scale"][i].tolist(),
            parametri=posa["mhr_model_params"][i].tolist(), spostamento=posa["pred_cam_t"][i].tolist(),
            fuoco=float(posa["focal_length"][i]), punti_3d=posa["pred_keypoints_3d"][i].tolist(),
            punti_2d=posa["pred_keypoints_2d"][i].tolist()))
    return figure


def dove_stanno(cartella_modelli: Path) -> Path:
    return Path(cartella_modelli) / "corpi" / NOME


def ci_sono(cartella_modelli: Path) -> bool:
    casa = dove_stanno(cartella_modelli)
    return all((casa / f).exists() for f in (FILE_PESI, FILE_MISURE, FILE_MHR))


def _risolvi(valore, radice):
    import re

    if isinstance(valore, dict):
        return {k: _risolvi(v, radice) for k, v in valore.items()}
    if isinstance(valore, list):
        return [_risolvi(v, radice) for v in valore]
    if isinstance(valore, str):
        trovato = re.fullmatch(r"\$\{([\w.]+)\}", valore.strip())
        if trovato:
            cercato = radice
            for pezzo in trovato.group(1).split("."):
                cercato = cercato[pezzo]
            return _risolvi(cercato, radice)
    return valore


def carica_le_misure(percorso: Path):
    import yaml

    letto = yaml.safe_load(Path(percorso).read_text(encoding="utf-8")) or {}
    return Configurazione(_risolvi(letto, letto))


def costruisci(casa: Path, dispositivo="cpu"):
    import torch

    from officina.corpi import mhr, solo_numeri
    from officina.corpi.corpo3d_rete import SAM3DBody
    from officina.corpi.dinov3_rete import Dinov3Backbone

    misure = carica_le_misure(casa / FILE_MISURE)
    modello_3d = mhr.Mhr.da_file(casa / FILE_MHR, dispositivo)
    rete = SAM3DBody(misure, modello_3d, Dinov3Backbone(misure.MODEL.BACKBONE.TYPE))
    pesi = solo_numeri.pesi(casa / FILE_PESI)
    pesi = {k: v for k, v in pesi.items() if not k.startswith(("head_pose.mhr.", "head_pose_hand.mhr."))}
    mancano, _ = rete.load_state_dict(pesi, strict=False)
    if mancano:
        raise RuntimeError("nei pesi di SAM 3D Body mancano dei pezzi: " + ", ".join(mancano[:8]))
    rete = rete.to(dispositivo).eval()
    torch.set_grad_enabled(False)
    return rete
