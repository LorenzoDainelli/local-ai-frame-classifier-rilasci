from __future__ import annotations

from pathlib import Path

from officina.corpi.rilevatore import SCALA_DEI_PUNTI
from officina.descrittori import vettori

LARGO = 288
ALTO = 384
MARGINE = 1.25
DIVISO = 2.0
MEDIA = (123.675, 116.28, 103.53)
SCARTO = (58.395, 57.12, 57.375)


class Pose:

    def __init__(self, percorso: Path):
        self.percorso = Path(percorso)
        self._sessione = None

    def accendi(self) -> None:
        if self._sessione is not None:
            return
        import onnxruntime

        self._sessione = onnxruntime.InferenceSession(
            str(self.percorso), providers=["CPUExecutionProvider"])

    def spegni(self) -> None:
        self._sessione = None

    def punti(self, immagine, riquadri_pixel) -> list[list[tuple[float, float, float]]]:
        if not riquadri_pixel:
            return []
        self.accendi()
        larga, alta = immagine.size
        nome = self._sessione.get_inputs()[0].name
        fuori = []
        for riquadro in riquadri_pixel:
            ingresso, centro, scala = prepara(immagine, riquadro)
            uscite = self._sessione.run(None, {nome: ingresso})
            fuori.append(leggi(uscite, centro, scala, larga, alta))
        return fuori


def centro_e_scala(riquadro):
    numpy = vettori.numpy_o_spiega()
    sinistra, sopra, destra, sotto = (float(v) for v in riquadro)
    centro = numpy.array([(sinistra + destra) / 2, (sopra + sotto) / 2], dtype=numpy.float32)
    larga = max(1.0, destra - sinistra) * MARGINE
    alta = max(1.0, sotto - sopra) * MARGINE
    if larga > alta * LARGO / ALTO:
        alta = larga * ALTO / LARGO
    else:
        larga = alta * LARGO / ALTO
    return centro, numpy.array([larga, alta], dtype=numpy.float32)


def prepara(immagine, riquadro):
    from PIL import Image

    numpy = vettori.numpy_o_spiega()
    centro, scala = centro_e_scala(riquadro)
    passo_x, passo_y = scala[0] / LARGO, scala[1] / ALTO
    ritaglio = immagine.convert("RGB").transform(
        (LARGO, ALTO), Image.AFFINE,
        (float(passo_x), 0.0, float(centro[0] - scala[0] / 2),
         0.0, float(passo_y), float(centro[1] - scala[1] / 2)),
        resample=Image.BILINEAR, fillcolor=(0, 0, 0))
    pixel = numpy.asarray(ritaglio, dtype=numpy.float32)
    pixel = (pixel - numpy.array(MEDIA, dtype=numpy.float32)) / numpy.array(SCARTO, dtype=numpy.float32)
    ingresso = numpy.ascontiguousarray(pixel.transpose(2, 0, 1)[None, ...], dtype=numpy.float32)
    return ingresso, centro, scala


def leggi(uscite, centro, scala, larga: int, alta: int) -> list[tuple[float, float, float]]:
    numpy = vettori.numpy_o_spiega()
    lungo_x = numpy.asarray(uscite[0], dtype=numpy.float32)
    lungo_y = numpy.asarray(uscite[1], dtype=numpy.float32)
    lungo_x = lungo_x.reshape(-1, lungo_x.shape[-1])
    lungo_y = lungo_y.reshape(-1, lungo_y.shape[-1])
    dove_x = numpy.argmax(lungo_x, axis=1).astype(numpy.float32)
    dove_y = numpy.argmax(lungo_y, axis=1).astype(numpy.float32)
    sicuri = 0.5 * (numpy.amax(lungo_x, axis=1) + numpy.amax(lungo_y, axis=1))
    x = dove_x / DIVISO / LARGO * scala[0] + centro[0] - scala[0] / 2
    y = dove_y / DIVISO / ALTO * scala[1] + centro[1] - scala[1] / 2
    fuori = []
    for px, py, sicuro in zip(x.tolist(), y.tolist(), sicuri.tolist(), strict=True):
        if sicuro <= 0:
            fuori.append((0.0, 0.0, 0.0))
            continue
        fuori.append((min(1.0, max(0.0, px / larga)), min(1.0, max(0.0, py / alta)),
                      min(1.0, max(0.0, float(sicuro) / SCALA_DEI_PUNTI))))
    return fuori


def per_kpr(punti) -> list[tuple[float, float, float]]:
    return [(x, y, min(1.0, c * SCALA_DEI_PUNTI)) for x, y, c in punti]
