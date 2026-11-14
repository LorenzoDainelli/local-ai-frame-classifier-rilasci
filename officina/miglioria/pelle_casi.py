from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass

import numpy as np

from officina.miglioria import gara120_rovina

LATI = (1024, 1536, 2048)
FACILE = "facile"
DIFFICILE = "difficile"
MOLTO_DIFFICILE = "molto difficile"
GRUPPI = (FACILE, DIFFICILE, MOLTO_DIFFICILE)
BUIO = "buio"
RUMORE = "rumore"
COMPRESSO = "compresso"
SFOCATO = "sfocato"
MOSSO = "mosso"
ROVINE = (BUIO, RUMORE, COMPRESSO, SFOCATO, MOSSO)
DOPPIE = ((SFOCATO, COMPRESSO), (MOSSO, COMPRESSO), (BUIO, COMPRESSO),
          (RUMORE, COMPRESSO), (SFOCATO, RUMORE), (MOSSO, BUIO))
INGRANDIMENTO = 2
MARGINE = 0.6
QUALITA_FACILE = 90
QUALITA_BASSA = 30
GRANA = 12.0
SFOCATURA = 1.3
STRISCIA = 9


@dataclass(frozen=True)
class Caso:
    nome: str
    lato: int
    gruppo: str
    rovine: tuple[str, ...]

    @property
    def chiave(self) -> str:
        return f"{self.nome}|{self.lato}"


def seme(*parti) -> int:
    testo = "|".join(str(p) for p in parti)
    return int.from_bytes(hashlib.sha256(testo.encode()).digest()[:8], "big")


def casi_di(nome: str) -> list[Caso]:
    giro = seme(nome, "gruppo") % len(GRUPPI)
    fuori = []
    for posto, lato in enumerate(LATI):
        gruppo = GRUPPI[(giro + posto) % len(GRUPPI)]
        if gruppo == FACILE:
            rovine: tuple[str, ...] = ()
        elif gruppo == DIFFICILE:
            rovine = (ROVINE[seme(nome, lato, "una") % len(ROVINE)],)
        else:
            rovine = DOPPIE[seme(nome, lato, "due") % len(DOPPIE)]
        fuori.append(Caso(nome, lato, gruppo, rovine))
    return fuori


def piano(nomi) -> list[Caso]:
    return [caso for nome in sorted(nomi) for caso in casi_di(nome)]


def _ridimensiona(pixel: np.ndarray, larga: int, alta: int) -> np.ndarray:
    import cv2

    piu_piccola = larga * alta < pixel.shape[0] * pixel.shape[1]
    modo = cv2.INTER_AREA if piu_piccola else cv2.INTER_LANCZOS4
    return cv2.resize(pixel, (larga, alta), interpolation=modo)


def ritaglio(larga: int, alta: int, volto, divisore: int = INGRANDIMENTO):
    x, y, lv, av = volto
    x0, y0 = (x - lv * MARGINE) * larga, (y - av * MARGINE) * alta
    x1, y1 = (x + lv * (1 + MARGINE)) * larga, (y + av * (1 + MARGINE)) * alta
    a = max(0, int(x0) // divisore * divisore)
    b = max(0, int(y0) // divisore * divisore)
    c = min(larga // divisore * divisore, -(-int(x1) // divisore) * divisore)
    d = min(alta // divisore * divisore, -(-int(y1) // divisore) * divisore)
    return a, b, c, d


def vera_di(originale: np.ndarray, caso: Caso) -> np.ndarray:
    alta, larga = originale.shape[:2]
    lungo = min(max(alta, larga), caso.lato * INGRANDIMENTO)
    scala = lungo / max(alta, larga)
    return _ridimensiona(originale, max(2, round(larga * scala)),
                         max(2, round(alta * scala)))


def jpeg(pixel: np.ndarray, qualita: int) -> np.ndarray:
    from PIL import Image

    memoria = io.BytesIO()
    Image.fromarray(pixel).save(memoria, format="JPEG", quality=qualita, subsampling=2)
    memoria.seek(0)
    with Image.open(memoria) as tornata:
        return np.asarray(tornata.convert("RGB")).copy()


def sfocato(pixel: np.ndarray) -> np.ndarray:
    import cv2

    return cv2.GaussianBlur(pixel, (0, 0), SFOCATURA)


def mosso(pixel: np.ndarray, numero_seme: int) -> np.ndarray:
    import cv2

    angolo = (numero_seme % 180) * np.pi / 180.0
    nucleo = np.zeros((STRISCIA, STRISCIA), np.float32)
    mezzo = STRISCIA // 2
    for passo in np.linspace(-mezzo, mezzo, STRISCIA * 4):
        nucleo[int(round(mezzo + passo * np.sin(angolo))),
               int(round(mezzo + passo * np.cos(angolo)))] = 1.0
    nucleo /= nucleo.sum()
    return cv2.filter2D(pixel, -1, nucleo, borderType=cv2.BORDER_REFLECT)


def rumore(pixel: np.ndarray, numero_seme: int) -> np.ndarray:
    caso = np.random.default_rng(numero_seme)
    sporco = pixel.astype(np.float64) + caso.normal(0, GRANA, pixel.shape)
    return np.clip(np.rint(sporco), 0, 255).astype(np.uint8)


def rovina(pixel: np.ndarray, caso: Caso) -> np.ndarray:
    fatto = pixel
    for nome in caso.rovine:
        numero = seme(caso.chiave, nome)
        if nome == BUIO:
            fatto = gara120_rovina.buio(fatto, numero)
        elif nome == RUMORE:
            fatto = rumore(fatto, numero)
        elif nome == SFOCATO:
            fatto = sfocato(fatto)
        elif nome == MOSSO:
            fatto = mosso(fatto, numero)
        elif nome == COMPRESSO:
            fatto = jpeg(fatto, QUALITA_BASSA)
        else:
            raise ValueError(nome)
    if COMPRESSO not in caso.rovine:
        fatto = jpeg(fatto, QUALITA_FACILE)
    return fatto


def vera_scura(vera: np.ndarray, caso: Caso) -> np.ndarray:
    if BUIO in caso.rovine:
        return gara120_rovina.buio(vera, None)
    return vera


def prepara(originale: np.ndarray, volto, caso: Caso) -> dict:
    vera_intera = vera_di(np.asarray(originale)[..., :3], caso)
    alta, larga = vera_intera.shape[:2]
    a, b, c, d = ritaglio(larga, alta, volto)
    vera = np.ascontiguousarray(vera_intera[b:d, a:c])
    piccola = _ridimensiona(vera, (c - a) // INGRANDIMENTO, (d - b) // INGRANDIMENTO)
    x, y, lv, av = volto
    riquadro = (x * larga - a, y * alta - b, (x + lv) * larga - a, (y + av) * alta - b)
    return {"entrata": rovina(piccola, caso), "vera": vera_scura(vera, caso),
            "riquadro": tuple(round(v, 2) for v in riquadro)}


__all__ = ["Caso", "GRUPPI", "LATI", "ROVINE", "casi_di", "piano", "prepara", "rovina"]
