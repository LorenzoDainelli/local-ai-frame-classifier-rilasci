from __future__ import annotations

import json
import os
from pathlib import Path

import numpy

LATO_LPIPS = 512
SOGLIA_AVANZO = 0.5
STACCO_AVANZO = 0.2


def _carica(percorso: Path, misura=None, grigia: bool = False):
    from PIL import Image

    with Image.open(percorso) as immagine:
        immagine = immagine.convert("L" if grigia else "RGB")
        if misura and immagine.size != misura:
            immagine = immagine.resize(misura, Image.NEAREST if grigia else Image.BICUBIC)
        return numpy.asarray(immagine)


def _allarga(maschera, raggio: int):
    import cv2

    if raggio <= 0:
        return maschera
    nocciolo = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * raggio + 1, 2 * raggio + 1))
    return cv2.dilate(maschera.astype(numpy.uint8), nocciolo) > 0


def _stringi(maschera, raggio: int):
    import cv2

    nocciolo = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * raggio + 1, 2 * raggio + 1))
    return cv2.erode(maschera.astype(numpy.uint8), nocciolo) > 0


def _scatola(maschera) -> list[int] | None:
    ys, xs = numpy.nonzero(maschera)
    if not len(xs):
        return None
    return [int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1]


def _iou(a, b) -> float:
    unione = numpy.logical_or(a, b).sum()
    return float(numpy.logical_and(a, b).sum() / unione) if unione else 0.0


def _psnr(a, b, dove) -> float | None:
    if not dove.any():
        return None
    errore = ((a.astype(numpy.float64) - b.astype(numpy.float64)) ** 2)[dove].mean()
    return 99.0 if errore <= 1e-10 else float(10 * numpy.log10(255.0 ** 2 / errore))


def _gradiente(pixel):
    import cv2

    grigio = cv2.cvtColor(pixel, cv2.COLOR_RGB2GRAY).astype(numpy.float32)
    gx = cv2.Sobel(grigio, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(grigio, cv2.CV_32F, 0, 1, ksize=3)
    return numpy.hypot(gx, gy)


class Cercatore:
    def __init__(self):
        import torch
        from transformers import Sam3TrackerModel, Sam3TrackerProcessor

        torch.set_grad_enabled(False)
        chiave = os.environ.get("HF_TOKEN") or None
        self._preparatore = Sam3TrackerProcessor.from_pretrained("facebook/sam3", token=chiave)
        self._modello = Sam3TrackerModel.from_pretrained("facebook/sam3", token=chiave).eval()

    def cerca(self, pixel, scatola: list[int]):
        from PIL import Image

        ingresso = self._preparatore(images=Image.fromarray(pixel), input_boxes=[[scatola]],
                                     return_tensors="pt")
        uscita = self._modello(**ingresso, multimask_output=False)
        maschere = self._preparatore.post_process_masks(
            uscita.pred_masks, ingresso["original_sizes"])[0]
        maschera = maschere[0, 0].numpy() > 0.5
        punteggio = float(uscita.iou_scores[0, 0, 0])
        return maschera, punteggio


class Somiglianza:
    def __init__(self):
        import lpips
        import torch

        torch.set_grad_enabled(False)
        self._rete = lpips.LPIPS(net="alex", verbose=False).eval()

    def distanza(self, a, b) -> float:
        import cv2
        import torch

        def tensore(pixel):
            piccola = cv2.resize(pixel, (LATO_LPIPS, LATO_LPIPS), interpolation=cv2.INTER_AREA)
            return torch.from_numpy(piccola).permute(2, 0, 1)[None].float() / 127.5 - 1

        return float(self._rete(tensore(a), tensore(b)))


def zona(cartella: Path, misura) -> tuple:
    oggetto = _carica(cartella / "maschera.png", misura, grigia=True) > 127
    effetto_file = cartella / "effetto.png"
    effetto = (_carica(effetto_file, misura, grigia=True) > 127) if effetto_file.exists() else None
    diagonale = (misura[0] ** 2 + misura[1] ** 2) ** 0.5
    raggio = max(4, int(0.01 * diagonale))
    toccata = _allarga(numpy.logical_or(oggetto, effetto) if effetto is not None else oggetto,
                       raggio)
    return oggetto, toccata, raggio


def ritaglio(toccata, misura, margine: float = 0.25):
    scatola = _scatola(toccata)
    if scatola is None:
        return (0, 0, misura[0], misura[1])
    x0, y0, x1, y1 = scatola
    dx, dy = int((x1 - x0) * margine) + 8, int((y1 - y0) * margine) + 8
    return (max(0, x0 - dx), max(0, y0 - dy), min(misura[0], x1 + dx), min(misura[1], y1 + dy))


def basi(cartella_foto: Path, cercatore: Cercatore) -> dict:
    vera = _carica(cartella_foto / "vera.png")
    misura = (vera.shape[1], vera.shape[0])
    ingresso = _carica(cartella_foto / "ingresso.png", misura)
    oggetto, toccata, _ = zona(cartella_foto, misura)
    scatola = _scatola(oggetto)
    maschera_ingresso, punti_ingresso = cercatore.cerca(ingresso, scatola)
    maschera_vera, punti_vera = cercatore.cerca(vera, scatola)
    numpy.save(cartella_foto / "sam-ingresso.npy", numpy.packbits(maschera_ingresso))
    return {"scatola": scatola, "iou_vera": _iou(maschera_vera, maschera_ingresso),
            "punti_ingresso": punti_ingresso, "punti_vera": punti_vera,
            "iou_oggetto": _iou(maschera_ingresso, oggetto)}


def voto(cartella_foto: Path, fatta: Path, base: dict, cercatore: Cercatore,
         somiglianza: Somiglianza) -> dict:
    vera = _carica(cartella_foto / "vera.png")
    misura = (vera.shape[1], vera.shape[0])
    ingresso = _carica(cartella_foto / "ingresso.png", misura)
    risultato = _carica(fatta, misura)
    oggetto, toccata, raggio = zona(cartella_foto, misura)
    forma = numpy.unpackbits(numpy.load(cartella_foto / "sam-ingresso.npy"))
    maschera_ingresso = forma[:misura[0] * misura[1]].reshape(misura[1], misura[0]).astype(bool)

    trovata, punti = cercatore.cerca(risultato, base["scatola"])
    iou_fatta = _iou(trovata, maschera_ingresso)
    avanzo = iou_fatta >= SOGLIA_AVANZO and iou_fatta - base["iou_vera"] >= STACCO_AVANZO

    x0, y0, x1, y1 = ritaglio(toccata, misura)
    lpips_zona = somiglianza.distanza(risultato[y0:y1, x0:x1], vera[y0:y1, x0:x1])
    psnr_zona = _psnr(risultato, vera, toccata)
    fuori = ~_allarga(toccata, 3 * raggio)
    psnr_fuori = _psnr(risultato, ingresso, fuori)

    anello = numpy.logical_and(_allarga(toccata, max(3, raggio // 2)),
                               ~_stringi(toccata, max(3, raggio // 2)))
    bordo = 0.0
    if anello.any():
        bordo = float(max(0.0, _gradiente(risultato)[anello].mean()
                          - _gradiente(vera)[anello].mean()))
    return {"avanzo": bool(avanzo), "iou_sam": round(iou_fatta, 4), "punti_sam": round(punti, 4),
            "lpips_zona": round(lpips_zona, 4),
            "psnr_zona": None if psnr_zona is None else round(psnr_zona, 3),
            "psnr_fuori": None if psnr_fuori is None else round(psnr_fuori, 3),
            "bordo": round(bordo, 3)}


def media(valori) -> float | None:
    buoni = [v for v in valori if v is not None]
    return round(float(numpy.mean(buoni)), 4) if buoni else None


def riassumi(chi: str, voti: dict, tutte: int) -> dict:
    fatte = list(voti.values())
    return {"chi": chi, "fatte": len(fatte), "su": tutte,
            "avanzi_percento": round(100 * sum(v["avanzo"] for v in fatte) / len(fatte), 2)
            if fatte else None,
            "lpips_zona": media(v["lpips_zona"] for v in fatte),
            "psnr_zona": media(v["psnr_zona"] for v in fatte),
            "psnr_fuori": media(v["psnr_fuori"] for v in fatte),
            "bordo": media(v["bordo"] for v in fatte)}


def ordine(riga: dict) -> tuple:
    if not riga.get("fatte"):
        return (1, 0, 0, 0, 0, 0)
    mancanti = 1 - riga["fatte"] / max(1, riga["su"])
    return (0, round((riga["avanzi_percento"] or 0) / 2), round(mancanti, 2),
            riga["lpips_zona"] if riga["lpips_zona"] is not None else 9,
            -(riga["psnr_fuori"] or 0), riga["bordo"] or 0)


def scrivi(percorso: Path, dati) -> None:
    percorso.parent.mkdir(parents=True, exist_ok=True)
    percorso.write_text(json.dumps(dati, indent=2, ensure_ascii=False), encoding="utf-8")
