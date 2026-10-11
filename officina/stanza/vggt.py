from __future__ import annotations

from pathlib import Path

REPO = "facebook/VGGT-Omega"
PAGINA = "https://huggingface.co/facebook/VGGT-Omega"
REVISIONE = "1041e80fc0e911235d3426b0a3d9a81075111a53"
FILE_PESI = "vggt_omega_1b_512.pt"
SHA256 = "c02da418b18bb01d0392598d3f6147366bcde1bb70fd08a5e3bf7925b0667934"
BYTE = 4_576_706_117
LICENZA = "FAIR Noncommercial Research License (Meta) — uso personale consentito, da accettare su Hugging Face"
LATO = 512
PASSO = 16
PROPORZIONE_MINIMA = 0.5
PROPORZIONE_MASSIMA = 2.0


def costruisci(percorso: Path, dove: str = "cpu", pesi: dict | None = None):
    import torch

    from officina.corpi import solo_numeri
    from officina.stanza.vggt_rete import DEVIAZIONE, MEDIA, VGGTOmega

    with torch.device("meta"):
        rete = VGGTOmega()
    if pesi is None:
        pesi = solo_numeri.pesi(percorso)
    mancano, avanzano = rete.load_state_dict(pesi, strict=False, assign=True)
    if mancano or avanzano:
        raise ValueError(f"i pesi di VGGT-Omega non tornano: mancano {mancano[:5]}, avanzano {avanzano[:5]}")
    rete.aggregator._resnet_mean = torch.tensor(MEDIA).view(1, 1, 3, 1, 1)
    rete.aggregator._resnet_std = torch.tensor(DEVIAZIONE).view(1, 1, 3, 1, 1)
    return rete.eval().to(dove)


def _rgb(immagine):
    from PIL import Image

    if immagine.mode == "RGBA":
        fondo = Image.new("RGBA", immagine.size, (255, 255, 255, 255))
        immagine = Image.alpha_composite(fondo, immagine)
    return immagine.convert("RGB")


def _ritaglia(immagine):
    largo, alto = immagine.size
    proporzione = alto / max(largo, 1)
    if proporzione < PROPORZIONE_MINIMA:
        taglio = min(largo, max(1, int(round(alto / PROPORZIONE_MINIMA))))
        sinistra = max((largo - taglio) // 2, 0)
        return immagine.crop((sinistra, 0, sinistra + taglio, alto)), (sinistra, 0)
    if proporzione > PROPORZIONE_MASSIMA:
        taglio = min(alto, max(1, int(round(largo * PROPORZIONE_MASSIMA))))
        sopra = max((alto - taglio) // 2, 0)
        return immagine.crop((0, sopra, largo, sopra + taglio)), (0, sopra)
    return immagine, (0, 0)


def _misura_bilanciata(proporzione: float, lato: int, passo: int):
    import numpy as np

    gettoni = (lato // passo) ** 2
    colonne = np.sqrt(gettoni / proporzione)
    righe = gettoni / colonne
    return max(1, int(np.round(righe))) * passo, max(1, int(np.round(colonne))) * passo


def _misura_massima(proporzione: float, lato: int, passo: int):
    import numpy as np

    def al_passo(valore):
        return max(passo, int(np.round(float(valore) / passo)) * passo)

    if proporzione >= 1.0:
        return lato, al_passo(lato / proporzione)
    return al_passo(lato * proporzione), lato


def prepara(immagini, lato: int = LATO, modo: str = "balanced", passo: int = PASSO):
    import torch
    from PIL import Image
    from torchvision.transforms import functional as TF

    if not immagini:
        raise ValueError("serve almeno una foto")
    tensori, viaggi = [], []
    for immagine in immagini:
        ritagliata, taglio = _ritaglia(_rgb(immagine))
        largo, alto = ritagliata.size
        proporzione = alto / max(largo, 1)
        if modo == "balanced":
            alto_nuovo, largo_nuovo = _misura_bilanciata(proporzione, lato, passo)
        else:
            alto_nuovo, largo_nuovo = _misura_massima(proporzione, lato, passo)
        tensori.append(TF.to_tensor(ritagliata.resize((largo_nuovo, alto_nuovo), Image.Resampling.BICUBIC)))
        viaggi.append({"taglio": taglio, "scala": (largo_nuovo / largo, alto_nuovo / alto),
                       "aggiunta": (0, 0), "foto": (largo, alto)})
    misure = {tuple(t.shape[1:]) for t in tensori}
    if len(misure) > 1:
        alto_massimo = max(a for a, _ in misure)
        largo_massimo = max(b for _, b in misure)
        pieni = []
        for tensore, viaggio in zip(tensori, viaggi):
            in_alto = alto_massimo - tensore.shape[1]
            di_lato = largo_massimo - tensore.shape[2]
            if in_alto > 0 or di_lato > 0:
                sopra, sinistra = in_alto // 2, di_lato // 2
                tensore = torch.nn.functional.pad(
                    tensore, (sinistra, di_lato - sinistra, sopra, in_alto - sopra), mode="constant", value=1.0)
                viaggio["aggiunta"] = (sinistra, sopra)
            pieni.append(tensore)
        tensori = pieni
    return torch.stack(tensori), viaggi


def intrinseci_sulla_foto(intrinseci, viaggio):
    import numpy as np

    matrice = np.asarray(intrinseci, dtype=np.float64).copy()
    scala_x, scala_y = viaggio["scala"]
    aggiunta_x, aggiunta_y = viaggio["aggiunta"]
    taglio_x, taglio_y = viaggio["taglio"]
    matrice[0, 0] /= scala_x
    matrice[0, 1] /= scala_x
    matrice[1, 1] /= scala_y
    matrice[0, 2] = (matrice[0, 2] - aggiunta_x) / scala_x + taglio_x
    matrice[1, 2] = (matrice[1, 2] - aggiunta_y) / scala_y + taglio_y
    return matrice


def stima(rete, immagini, lato: int = LATO, modo: str = "balanced", in_mezza=None) -> dict:
    import torch

    from officina.stanza.geometria import decodifica_posa

    lotto, viaggi = prepara(immagini, lato, modo)
    dove = next(rete.parameters()).device
    with torch.no_grad():
        fuori = rete(lotto.to(dove), in_mezza)
        estrinseci, intrinseci = decodifica_posa(fuori["pose_enc"].float(), lotto.shape[-2:], limite=None)
    return {
        "estrinseci": estrinseci[0].cpu().numpy(),
        "intrinseci": intrinseci[0].cpu().numpy(),
        "profondita": fuori["depth"][0, ..., 0].cpu().float().numpy(),
        "fiducia": fuori["depth_conf"][0].cpu().float().numpy(),
        "codice": fuori["pose_enc"][0].cpu().float().numpy(),
        "misura": tuple(lotto.shape[-2:]),
        "viaggi": viaggi,
        "immagini": lotto,
    }
