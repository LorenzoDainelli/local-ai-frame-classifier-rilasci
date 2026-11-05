from __future__ import annotations

import hashlib
import io

from officina.miglioria.gara120_casi import MOSSO, OTTURATORE

GAMMA = 2.2
STOP_TOLTI = 3
FOTONI = 600.0
LETTURA = 0.0025
GRANA = 25.0
QUALITA_BASSA = 35
VELOCITA = 30


def seme(nome: str, numero: int) -> int:
    return int.from_bytes(hashlib.sha256(f"{nome}|{numero}".encode()).digest()[:8], "big")


def _lineare(quadro):
    import numpy as np

    return (np.asarray(quadro, dtype=np.float64) / 255.0) ** GAMMA


def _in_otto_bit(lineare):
    import numpy as np

    return np.clip(np.rint(np.clip(lineare, 0, 1) ** (1 / GAMMA) * 255), 0, 255).astype(
        np.uint8)


def buio(quadro, numero_seme: int | None):
    import numpy as np

    luce = _lineare(quadro) * 2.0 ** -STOP_TOLTI
    if numero_seme is not None:
        caso = np.random.default_rng(numero_seme)
        luce = caso.poisson(luce * FOTONI) / FOTONI + caso.normal(0, LETTURA, luce.shape)
    return _in_otto_bit(luce)


def rumore(quadro, numero_seme: int):
    import numpy as np

    caso = np.random.default_rng(numero_seme)
    sporco = np.asarray(quadro, dtype=np.float64) + caso.normal(0, GRANA, np.shape(quadro))
    return np.clip(np.rint(sporco), 0, 255).astype(np.uint8)


def mosso(prendi, numero: int):
    somma = None
    quanti = 0
    for vicino in range(numero + OTTURATORE[0], numero + OTTURATORE[1] + 1):
        luce = _lineare(prendi(vicino))
        somma = luce if somma is None else somma + luce
        quanti += 1
    return _in_otto_bit(somma / quanti)


def compresso(quadri: list) -> list:
    import av
    import numpy as np

    alto, largo = np.asarray(quadri[0]).shape[:2]
    pari = [np.pad(np.asarray(q), ((0, alto % 2), (0, largo % 2), (0, 0)), mode="edge")
            for q in quadri]
    memoria = io.BytesIO()
    with av.open(memoria, mode="w", format="mp4") as uscita:
        flusso = uscita.add_stream("libx264", rate=VELOCITA)
        flusso.width, flusso.height = pari[0].shape[1], pari[0].shape[0]
        flusso.pix_fmt = "yuv420p"
        flusso.options = {"crf": str(QUALITA_BASSA), "preset": "medium", "threads": "1"}
        for quadro in pari:
            uscita.mux(flusso.encode(av.VideoFrame.from_ndarray(quadro, format="rgb24")))
        uscita.mux(flusso.encode(None))
    memoria.seek(0)
    with av.open(memoria, mode="r") as entrata:
        tornati = [f.to_ndarray(format="rgb24")[:alto, :largo]
                   for f in entrata.decode(video=0)]
    if len(tornati) != len(quadri):
        raise ValueError((len(tornati), len(quadri)))
    return tornati


def prepara(caso, prendi) -> tuple[list, list]:
    if caso.rovina == MOSSO:
        entrate = [mosso(prendi, n) for n in caso.tenuti]
        veri = [mosso(prendi, n) for n in caso.veri]
    else:
        entrate = [prendi(n) for n in caso.tenuti]
        veri = [prendi(n) for n in caso.veri]
    if caso.rovina == "buio":
        entrate = [buio(q, seme(caso.nome, n)) for q, n in zip(entrate, caso.tenuti)]
        veri = [buio(q, None) for q in veri]
    elif caso.rovina == "rumore":
        entrate = [rumore(q, seme(caso.nome, n)) for q, n in zip(entrate, caso.tenuti)]
    elif caso.rovina == "compresso":
        entrate = compresso(entrate)
    return entrate, veri


__all__ = ["buio", "compresso", "mosso", "prepara", "rumore", "seme"]
