from __future__ import annotations

import functools
from dataclasses import dataclass

import numpy as np

BT709 = 1
BT2020 = 9
BT2020_CL = 10
PQ = 16
HLG = 18
GAMMA_709 = (1, 6, 14, 15)

BIANCO_DI_RIFERIMENTO = 203.0
PICCO_HLG = 1000.0
PICCO_PQ = 1000.0
GINOCCHIO = 0.75

DA_2020_A_709 = np.array([
    [1.660491, -0.587641, -0.072850],
    [-0.124550, 1.132900, -0.008349],
    [-0.018151, -0.100579, 1.118730],
], dtype=np.float32)

PESI = {
    BT709: (0.2126, 0.0722),
    BT2020: (0.2627, 0.0593),
    BT2020_CL: (0.2627, 0.0593),
}


@dataclass(frozen=True)
class Colori:

    primarie: int
    trasferimento: int
    matrice: int
    intervallo: int

    @property
    def hdr(self) -> bool:
        return self.trasferimento in (PQ, HLG)


def della_traccia(traccia) -> Colori:
    contesto = traccia.codec_context
    return Colori(primarie=int(getattr(contesto, "color_primaries", 2) or 2),
                  trasferimento=int(getattr(contesto, "color_trc", 2) or 2),
                  matrice=int(getattr(contesto, "colorspace", 2) or 2),
                  intervallo=int(getattr(contesto, "color_range", 0) or 0))


def segna(traccia, colori: Colori | None = None) -> None:
    contesto = traccia.codec_context
    contesto.color_primaries = colori.primarie if colori else BT709
    contesto.color_trc = colori.trasferimento if colori else BT709
    contesto.colorspace = colori.matrice if colori else BT709
    contesto.color_range = 1


def _rgb_non_lineare(fotogramma, colori: Colori, larghezza: int | None = None,
                     altezza: int | None = None) -> np.ndarray:
    piani = fotogramma.reformat(width=larghezza, height=altezza, format="yuv444p16le",
                                interpolation="LANCZOS").to_ndarray()
    if piani.ndim == 3 and piani.shape[-1] == 3:
        piani = np.moveaxis(piani, -1, 0)
    y, u, v = (piano.astype(np.float32) / 65535.0 for piano in piani)
    if colori.intervallo == 2:
        cb, cr = u - 0.5, v - 0.5
    else:
        y = (y - 16 / 255) / (219 / 255)
        cb = (u - 128 / 255) / (224 / 255)
        cr = (v - 128 / 255) / (224 / 255)
    kr, kb = PESI.get(colori.matrice, PESI[BT2020] if colori.primarie == BT2020 else PESI[BT709])
    kg = 1.0 - kr - kb
    r = y + 2.0 * (1.0 - kr) * cr
    b = y + 2.0 * (1.0 - kb) * cb
    g = (y - kr * r - kb * b) / kg
    return np.clip(np.stack([r, g, b], axis=-1), 0.0, 1.0)


LIVELLI = 65535


def _indici(valori: np.ndarray) -> np.ndarray:
    return np.rint(np.clip(valori, 0.0, 1.0) * LIVELLI).astype(np.uint16)


@functools.lru_cache(maxsize=None)
def _tavola(nome: str) -> np.ndarray:
    x = np.linspace(0.0, 1.0, LIVELLI + 1, dtype=np.float64)
    if nome == "hlg":
        a, b, c = 0.17883277, 0.28466892, 0.55991073
        y = np.where(x <= 0.5, x * x / 3.0, (np.exp((np.maximum(x, 0.5) - c) / a) + b) / 12.0)
    elif nome == "pq":
        m1, m2 = 2610 / 16384, 2523 / 4096 * 128
        c1, c2, c3 = 3424 / 4096, 2413 / 4096 * 32, 2392 / 4096 * 32
        potenza = np.power(x, 1.0 / m2)
        y = 10000.0 * np.power(np.maximum(potenza - c1, 0.0) / (c2 - c3 * potenza), 1.0 / m1)
    else:
        y = np.where(x < 0.018, 4.5 * x, 1.099 * np.power(np.maximum(x, 0.018), 0.45) - 0.099)
    return y.astype(np.float32)


def _hlg_in_luce(segnale: np.ndarray) -> np.ndarray:
    scena = _tavola("hlg")[_indici(segnale)]
    luminanza = (0.2627 * scena[..., 0] + 0.6780 * scena[..., 1]
                 + 0.0593 * scena[..., 2])
    gamma = 1.2 + 0.42 * np.log10(PICCO_HLG / 1000.0)
    guadagno = PICCO_HLG * np.power(np.maximum(luminanza, 1e-6), np.float32(gamma - 1.0))
    return scena * guadagno[..., None]


def _pq_in_luce(segnale: np.ndarray) -> np.ndarray:
    return _tavola("pq")[_indici(segnale)]


def _comprimi(luce: np.ndarray, picco: float) -> np.ndarray:
    relativa = luce / BIANCO_DI_RIFERIMENTO
    bianco = max(1.0, picco / BIANCO_DI_RIFERIMENTO)
    luminanza = (0.2126 * relativa[..., 0] + 0.7152 * relativa[..., 1]
                 + 0.0722 * relativa[..., 2])
    tratto = 1.0 - GINOCCHIO
    oltre_il_ginocchio = np.maximum(luminanza - GINOCCHIO, 0.0) / tratto
    fino = max(1e-6, (bianco - GINOCCHIO) / tratto)
    piegata = oltre_il_ginocchio * (1.0 + oltre_il_ginocchio / (fino * fino)) / (1.0 + oltre_il_ginocchio)
    compressa = np.where(luminanza <= GINOCCHIO, luminanza, GINOCCHIO + tratto * piegata)
    rapporto = np.where(luminanza > 1e-6, compressa / np.maximum(luminanza, 1e-6), 1.0)
    uscita = relativa * rapporto[..., None]
    massimo = np.max(uscita, axis=-1, keepdims=True)
    oltre = massimo > 1.0
    grigio = compressa[..., None]
    quanto = np.where(oltre, (massimo - 1.0) / np.maximum(massimo - grigio, 1e-6), 0.0)
    uscita = uscita + (grigio - uscita) * np.clip(quanto, 0.0, 1.0)
    return np.clip(uscita, 0.0, 1.0)


def _in_709(lineare: np.ndarray) -> np.ndarray:
    return _tavola("709")[_indici(lineare)]


def in_sdr(fotogramma, colori: Colori, larghezza: int | None = None,
           altezza: int | None = None) -> np.ndarray:
    segnale = _rgb_non_lineare(fotogramma, colori, larghezza, altezza)
    if colori.trasferimento == HLG:
        luce, picco = _hlg_in_luce(segnale), PICCO_HLG
    else:
        luce, picco = _pq_in_luce(segnale), PICCO_PQ
    if colori.primarie == BT2020:
        luce = np.maximum(luce @ DA_2020_A_709.T, 0.0)
    sdr = _in_709(_comprimi(luce, picco))
    return np.ascontiguousarray(np.round(sdr * 255.0).astype(np.uint8))


def rgb_in_yuv(av, quadro: np.ndarray, pts, base):
    nuovo = av.VideoFrame.from_ndarray(quadro, format="rgb24")
    nuovo = nuovo.reformat(format="yuv420p", dst_colorspace="itu709",
                           dst_color_range="MPEG")
    nuovo.pts = pts
    if base is not None:
        nuovo.time_base = base
    return nuovo


def in_rgb(fotogramma, colori: Colori, larghezza: int | None = None,
           altezza: int | None = None) -> np.ndarray:
    if colori.hdr:
        return in_sdr(fotogramma, colori, larghezza, altezza)
    sorgente = "itu709" if colori.matrice in (BT709, 2) else "itu601"
    return fotogramma.reformat(width=larghezza, height=altezza, format="rgb24",
                               src_colorspace=sorgente,
                               src_color_range="JPEG" if colori.intervallo == 2 else "MPEG"
                               ).to_ndarray()
