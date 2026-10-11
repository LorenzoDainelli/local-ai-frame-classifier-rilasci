from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

PUNTI_DEL_CORPO = 17
SCALA_DELLA_CAMPANA = 11

TESTA = (0, 1, 2, 3, 4)
GRUPPI = {
    "cck8": (TESTA, (5, 7, 9), (6, 8, 10), (5, 6, 11, 12), (13, 15), (14, 16), (15,), (16,)),
    "cck6": (TESTA, (7, 9), (8, 10), (13, 15), (14, 16), (5, 6, 11, 12)),
    "cck4": (TESTA, (7, 9, 8, 10), (13, 15, 14, 16), (5, 6, 11, 12)),
}

VERSIONI = ("posetrack", "market", "duke")
ALTEZZA = 384
LARGHEZZA = 128
PER_VOLTA = 16


def campana(lato: int) -> np.ndarray:
    raggio = int(lato / SCALA_DELLA_CAMPANA)
    quanti = raggio * 2 + 1
    scarto = quanti / 4
    n = np.arange(quanti) - (quanti - 1) / 2.0
    fila = np.exp(-0.5 * (n / scarto) ** 2).reshape(quanti, 1)
    return np.outer(fila, fila)


def campane(punti: np.ndarray, larga: int, alta: int, soglia: float, continui: bool) -> np.ndarray:
    fuori = np.zeros((len(punti), alta, larga))
    nucleo = campana(larga)
    raggio = nucleo.shape[0] // 2
    for i, (x, y, c) in enumerate(punti):
        if c <= soglia and not continui:
            continue
        px, py = int(x), int(y)
        su, giu = min(raggio, py), min(raggio, alta - 1 - py)
        sx, dx = min(raggio, px), min(raggio, larga - 1 - px)
        pezzo = nucleo[raggio - su:raggio + giu + 1, raggio - sx:raggio + dx + 1]
        if continui:
            pezzo = pezzo * c
        fuori[i, py - su:py + giu + 1, px - sx:px + dx + 1] = pezzo
    return fuori


def nel_ritaglio(punti_immagine, riquadro_pixel, larga_immagine: int, alta_immagine: int,
                 larga: int, alta: int) -> np.ndarray:
    x0, y0, x1, y1 = riquadro_pixel
    lw, lh = max(x1 - x0, 1e-6), max(y1 - y0, 1e-6)
    fuori = np.zeros((PUNTI_DEL_CORPO, 3))
    for i, terna in enumerate(list(punti_immagine)[:PUNTI_DEL_CORPO]):
        x, y, c = float(terna[0]), float(terna[1]), float(terna[2])
        if c <= 0:
            continue
        rx = (x * larga_immagine - x0) * larga / lw
        ry = (y * alta_immagine - y0) * alta / lh
        if 0 <= rx < larga and 0 <= ry < alta:
            fuori[i] = (rx, ry, c)
    return fuori


def suggerimento(bersaglio: np.ndarray, altri: list[np.ndarray], conf) -> np.ndarray:
    larga, alta = conf.larghezza, conf.altezza
    caldi = campane(bersaglio, larga, alta, conf.soglia_punti, conf.punti_continui)
    parti = np.stack([caldi[list(gruppo)].max(axis=0).clip(0, 1)
                      for gruppo in GRUPPI[conf.raggruppamento]])
    canali = [parti]
    if conf.negativi:
        if altri:
            negativo = np.concatenate([campane(a, larga, alta, conf.soglia_punti,
                                               conf.punti_continui) for a in altri])
            negativo = negativo.max(axis=0, keepdims=True)
        else:
            negativo = np.zeros((1, alta, larga))
        canali.insert(0, negativo)
    tutti = np.concatenate(canali)
    sfondo = np.clip(1 - tutti.sum(axis=0, keepdims=True), 0, 1)
    return np.concatenate([sfondo, tutti]).astype(np.float32)


def pixel_del_ritaglio(immagine, riquadro_pixel, larga: int, alta: int):
    import torch
    from torch.nn import functional as F

    larga_immagine, alta_immagine = immagine.size
    x0, y0, x1, y1 = (int(round(v)) for v in riquadro_pixel)
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(larga_immagine, max(x1, x0 + 1)), min(alta_immagine, max(y1, y0 + 1))
    pezzo = np.asarray(immagine.convert("RGB").crop((x0, y0, x1, y1)), dtype=np.float32)
    tensore = torch.from_numpy(pezzo).permute(2, 0, 1).unsqueeze(0)
    if tensore.shape[-2:] != (alta, larga):
        tensore = F.interpolate(tensore, size=(alta, larga), mode="bilinear",
                                align_corners=False).round().clamp(0, 255)
    return tensore[0].permute(1, 2, 0).numpy().astype(np.uint8), (x0, y0, x1, y1)


def normalizza(pixel: np.ndarray, conf):
    import torch

    tensore = torch.from_numpy(np.ascontiguousarray(pixel, dtype=np.float32)).permute(2, 0, 1)
    media = torch.tensor(conf.media).view(3, 1, 1) * 255.0
    scarto = torch.tensor(conf.scarto).view(3, 1, 1) * 255.0
    return (tensore - media) / scarto


def ritaglio(immagine, riquadro_pixel, conf):
    pixel, tagliato = pixel_del_ritaglio(immagine, riquadro_pixel, conf.larghezza, conf.altezza)
    return normalizza(pixel, conf), tagliato


@dataclass
class Preparato:

    pixel: np.ndarray
    mio: np.ndarray
    altri: list[np.ndarray] = field(default_factory=list)


def prepara(immagine, persone, larga: int = LARGHEZZA, alta: int = ALTEZZA) -> list[Preparato]:
    larga_immagine, alta_immagine = immagine.size
    fuori = []
    for indice, (riquadro, punti) in enumerate(persone):
        pixel, tagliato = pixel_del_ritaglio(immagine, riquadro, larga, alta)
        mio = nel_ritaglio(punti, tagliato, larga_immagine, alta_immagine, larga, alta)
        altri = [nel_ritaglio(p, tagliato, larga_immagine, alta_immagine, larga, alta)
                 for j, (_r, p) in enumerate(persone) if j != indice and p]
        fuori.append(Preparato(pixel, mio, altri))
    return fuori


def distanza(a, va, b, vb) -> float:
    a = np.asarray(a, dtype=np.float32)
    b = np.asarray(b, dtype=np.float32)
    peso = np.sqrt(np.asarray(va, dtype=np.float32) * np.asarray(vb, dtype=np.float32))
    if peso.sum() == 0:
        return 1.0
    per_parte = np.linalg.norm(a - b, axis=-1)
    return float((per_parte * peso).sum() / peso.sum() / 2)


class Riconoscitore:

    def __init__(self, cartella: Path, versione: str):
        self.cartella = Path(cartella)
        self.versione = versione
        self.conf = None
        self._modello = None
        self._dispositivo = "cpu"

    @property
    def file_dei_pesi(self) -> Path:
        return self.cartella / f"kpr-{self.versione}.safetensors"

    @property
    def file_della_scheda(self) -> Path:
        return self.cartella / f"kpr-{self.versione}.json"

    def accendi(self) -> None:
        if self._modello is not None:
            return
        from safetensors.torch import load_file

        from officina.corpi import kpr_rete
        from officina.descrittori import torcia

        scheda = json.loads(self.file_della_scheda.read_text(encoding="utf-8"))
        self.conf = kpr_rete.Configurazione(scheda)
        modello = kpr_rete.KPR(self.conf)
        kpr_rete.carica(modello, load_file(str(self.file_dei_pesi)))
        self._dispositivo = torcia.macchina().dispositivo
        self._modello = modello.to(self._dispositivo).eval()

    def spegni(self) -> None:
        if self._modello is None:
            return
        from officina.descrittori import torcia

        self._modello = None
        torcia.libera()

    @property
    def acceso(self) -> bool:
        return self._modello is not None

    def guarda(self, immagine, persone: list[tuple[tuple[float, float, float, float], list]]):
        return self.guarda_preparati(prepara(immagine, persone))

    def guarda_preparati(self, preparati: list[Preparato]):
        import torch

        self.accendi()
        if not preparati:
            return []
        forma = (self.conf.altezza, self.conf.larghezza)
        fuori = []
        for inizio in range(0, len(preparati), PER_VOLTA):
            gruppo = preparati[inizio:inizio + PER_VOLTA]
            if any(p.pixel.shape[:2] != forma for p in gruppo):
                raise ValueError("il ritaglio non ha la misura che vuole KPR")
            immagini = torch.stack([normalizza(p.pixel, self.conf) for p in gruppo])
            suggerimenti = torch.stack([torch.from_numpy(suggerimento(p.mio, p.altri, self.conf))
                                        for p in gruppo])
            with torch.inference_mode():
                immersione, visibili = self._modello(immagini.to(self._dispositivo),
                                                     suggerimenti.to(self._dispositivo))
            immersione = immersione.float().cpu().numpy()
            visibili = visibili.float().cpu().numpy()
            fuori.extend((immersione[i], visibili[i]) for i in range(len(gruppo)))
        return fuori
