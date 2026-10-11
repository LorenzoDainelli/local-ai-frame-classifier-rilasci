from __future__ import annotations

from pathlib import Path

REPO = "depth-anything/DA3NESTED-GIANT-LARGE-1.1"
REVISIONE = "b2359bdf726fb44ef62acca04d629dcf158053e7"
FILE_PESI = "model.safetensors"
SHA256 = "8ebe871a022ed58d2fc8fdfb2ebdb31d57b60fe39611c849095851a7b7c6020c"
BYTE = 6_759_558_100
LICENZA = "CC BY-NC 4.0 per i pesi, Apache 2.0 per il codice — uso personale consentito"
LATO = 504
MEDIA = (0.485, 0.456, 0.406)
DEVIAZIONE = (0.229, 0.224, 0.225)
NON_USATI = (
    "da3.head.scratch.refinenet1_aux.", "da3.head.scratch.refinenet2_aux.",
    "da3.head.scratch.refinenet3_aux.", "da3.head.scratch.refinenet4_aux.",
    "da3.head.scratch.output_conv1_aux.", "da3.head.scratch.output_conv2_aux.",
    "da3.gs_head.", "da3.gs_adapter.",
)
DA_RANSAC = 10


def pesi_da_usare(letti: dict) -> dict:
    pesi = {}
    for nome, valore in letti.items():
        if not nome.startswith("model."):
            raise ValueError(f"nei pesi di Depth Anything 3 c'è un nome strano: {nome}")
        corto = nome[len("model."):]
        if not corto.startswith(NON_USATI):
            pesi[corto] = valore
    return pesi


def costruisci(percorso: Path, dove: str = "cpu", letti: dict | None = None):
    import torch
    from safetensors.torch import load_file

    from officina.stanza.da3_rete import NestedDepthAnything3Net

    with torch.device("meta"):
        rete = NestedDepthAnything3Net()
    if letti is None:
        letti = load_file(str(percorso), device="cpu")
    mancano, avanzano = rete.load_state_dict(pesi_da_usare(letti), strict=False, assign=True)
    if mancano or avanzano:
        raise ValueError(f"i pesi di Depth Anything 3 non tornano: mancano {mancano[:5]}, "
                         f"avanzano {avanzano[:5]}")
    return rete.eval().to(dove)


def _multiplo_vicino(lato: int, passo: int) -> int:
    sotto = (lato // passo) * passo
    sopra = sotto + passo
    return sopra if abs(sopra - lato) <= abs(lato - sotto) else sotto


def _riscala(intrinseci, largo_prima: int, alto_prima: int, largo: int, alto: int):
    if intrinseci is None:
        return None
    nuovi = intrinseci.copy()
    nuovi[:1] *= largo / float(largo_prima)
    nuovi[1:2] *= alto / float(alto_prima)
    return nuovi


def _ridimensiona(immagine, largo: int, alto: int, ingrandisce: bool):
    import cv2
    import numpy as np
    from PIL import Image

    modo = cv2.INTER_CUBIC if ingrandisce else cv2.INTER_AREA
    return Image.fromarray(cv2.resize(np.asarray(immagine), (largo, alto), interpolation=modo))


def prepara(immagini, intrinseci=None, lato: int = LATO):
    import numpy as np
    import torch
    from torchvision.transforms import functional as TF

    from officina.stanza.da3_rete import PASSO

    tensori, misure, matrici = [], [], []
    for numero, immagine in enumerate(immagini):
        immagine = immagine.convert("RGB")
        largo_prima, alto_prima = immagine.size
        matrice = None if intrinseci is None else np.asarray(intrinseci[numero]).copy()
        piu_lungo = max(largo_prima, alto_prima)
        if piu_lungo != lato:
            scala = lato / float(piu_lungo)
            immagine = _ridimensiona(immagine, max(1, int(round(largo_prima * scala))),
                                     max(1, int(round(alto_prima * scala))), scala > 1.0)
        largo, alto = immagine.size
        matrice = _riscala(matrice, largo_prima, alto_prima, largo, alto)
        nuovo_largo, nuovo_alto = max(1, _multiplo_vicino(largo, PASSO)), max(1, _multiplo_vicino(alto, PASSO))
        if (nuovo_largo, nuovo_alto) != (largo, alto):
            immagine = _ridimensiona(immagine, nuovo_largo, nuovo_alto,
                                     nuovo_largo > largo or nuovo_alto > alto)
            matrice = _riscala(matrice, largo, alto, nuovo_largo, nuovo_alto)
        tensore = TF.normalize(TF.to_tensor(immagine), mean=list(MEDIA), std=list(DEVIAZIONE))
        tensori.append(tensore)
        misure.append(tuple(tensore.shape[1:]))
        matrici.append(matrice)
    if len(set(misure)) > 1:
        alto_minimo = min(a for a, _ in misure)
        largo_minimo = min(b for _, b in misure)
        tagliati = []
        for numero, (tensore, (alto, largo)) in enumerate(zip(tensori, misure)):
            tagliati.append(TF.center_crop(tensore, [alto_minimo, largo_minimo]))
            if matrici[numero] is not None:
                matrici[numero] = matrici[numero].copy()
                matrici[numero][0, 2] -= max(0, (largo - largo_minimo) // 2)
                matrici[numero][1, 2] -= max(0, (alto - alto_minimo) // 2)
        tensori = tagliati
    lotto = torch.stack(tensori)
    matrici = (torch.from_numpy(np.asarray(matrici)).float()
               if intrinseci is not None and matrici[0] is not None else None)
    return lotto, matrici


def normalizza_le_macchine(estrinseci):
    import torch

    from officina.stanza.geometria import inversa_affine

    normali = estrinseci @ inversa_affine(estrinseci[:, :1])
    distanze = inversa_affine(normali)[..., :3, 3].norm(dim=-1)
    mediana = torch.clamp(torch.median(distanze), min=1e-1)
    normali[..., :3, 3] = normali[..., :3, 3] / mediana
    return normali


def stima(rete, immagini, estrinseci=None, intrinseci=None, alla_scala_data: bool = True,
          strategia: str = "saddle_balanced", in_mezza=None, lato: int = LATO) -> dict:
    import numpy as np
    import torch

    from officina.stanza.allineamento import allinea_le_macchine

    lotto, matrici = prepara(immagini, intrinseci, lato)
    dove = next(rete.parameters()).device
    x = lotto.to(dove)[None].float()
    date = None
    if estrinseci is not None:
        date = torch.from_numpy(np.asarray(estrinseci)).float()
    estrinseci_in = None if date is None else date.to(dove)[None].float()
    intrinseci_in = None if matrici is None else matrici.to(dove)[None].float()
    normali = None if estrinseci_in is None else normalizza_le_macchine(estrinseci_in.clone())
    with torch.no_grad():
        fuori = rete(x, normali, intrinseci_in, strategia, in_mezza)
    esito = {
        "profondita": fuori["depth"].squeeze(0).cpu().float().numpy(),
        "fiducia": fuori["depth_conf"].squeeze(0).cpu().float().numpy(),
        "estrinseci": fuori["extrinsics"].squeeze(0).cpu().float().numpy(),
        "intrinseci": fuori["intrinsics"].squeeze(0).cpu().float().numpy(),
        "cielo": fuori["sky"].squeeze(0).cpu().float().numpy() >= 0.5,
        "scala_metrica": fuori["scale_factor"],
        "immagini": lotto,
    }
    if date is not None:
        esito["intrinseci"] = matrici.numpy()
        r, t, s = allinea_le_macchine(esito["estrinseci"], date.numpy(), ransac=len(date) >= DA_RANSAC, seme=42)
        esito["allineamento"] = (r, t, s)
        if alla_scala_data:
            esito["estrinseci"] = date[..., :3, :].numpy()
            esito["profondita"] = np.divide(esito["profondita"], s).astype(np.float32)
        else:
            esito["estrinseci"] = _applica(esito["estrinseci"], r, t, s)
    return esito


def _applica(estrinseci, r, t, s):
    import numpy as np

    estrinseci = np.asarray(estrinseci, dtype=np.float64)
    piene = np.repeat(np.eye(4)[None], len(estrinseci), 0)
    piene[:, :3, :4] = estrinseci[:, :3, :4]
    rotazioni = np.transpose(piene[:, :3, :3], (0, 2, 1))
    centri = -np.einsum("nij,nj->ni", rotazioni, piene[:, :3, 3])
    nuove_rotazioni = r @ rotazioni
    nuovi_centri = (r @ (s * centri.T)).T + t
    fuori = np.repeat(np.eye(4)[None], len(estrinseci), 0)
    fuori[:, :3, :3] = np.transpose(nuove_rotazioni, (0, 2, 1))
    fuori[:, :3, 3] = -np.einsum("nij,nj->ni", fuori[:, :3, :3], nuovi_centri)
    return fuori
