from __future__ import annotations

from PIL import Image

LATO = 112

PUNTI_DI_RIFERIMENTO = (
    (38.2946, 51.6963),
    (73.5318, 51.5014),
    (56.0252, 71.7366),
    (41.5493, 92.3655),
    (70.7299, 92.2041),
)


class PuntiSbagliati(ValueError):
    pass


def trasformazione(punti, riferimento=PUNTI_DI_RIFERIMENTO):
    numpy = _numpy()

    fonte = numpy.asarray(punti, dtype=numpy.float64)
    arrivo = numpy.asarray(riferimento, dtype=numpy.float64)
    if fonte.shape != arrivo.shape or fonte.ndim != 2 or fonte.shape[1] != 2 \
            or len(fonte) < 2:
        raise PuntiSbagliati(
            f"Servono {len(arrivo)} punti da due coordinate; sono arrivati "
            f"{fonte.shape}.")

    centro_fonte = fonte.mean(axis=0)
    centro_arrivo = arrivo.mean(axis=0)
    scarti_fonte = fonte - centro_fonte
    scarti_arrivo = arrivo - centro_arrivo

    sparpagliamento = float((scarti_fonte ** 2).sum() / len(fonte))
    if sparpagliamento <= 1e-12:
        raise PuntiSbagliati("I cinque punti sono tutti nello stesso posto.")

    covarianza = scarti_arrivo.T @ scarti_fonte / len(fonte)
    u, valori, vt = numpy.linalg.svd(covarianza)

    correzione = numpy.eye(2)
    if numpy.linalg.det(u) * numpy.linalg.det(vt) < 0:
        correzione[1, 1] = -1.0
        valori = valori.copy()
        valori[-1] = -valori[-1]

    rotazione = u @ correzione @ vt
    scala = float(valori.sum()) / sparpagliamento
    matrice = rotazione * scala
    spostamento = centro_arrivo - matrice @ centro_fonte
    return (float(matrice[0, 0]), float(matrice[0, 1]), float(spostamento[0]),
            float(matrice[1, 0]), float(matrice[1, 1]), float(spostamento[1]))


def raddrizza(immagine: Image.Image, punti, lato: int = LATO) -> Image.Image:
    if immagine.mode != "RGB":
        immagine = immagine.convert("RGB")
    scala = lato / LATO
    riferimento = [(x * scala, y * scala) for x, y in PUNTI_DI_RIFERIMENTO]
    a, b, tx, c, d, ty = trasformazione(punti, riferimento)
    return immagine.transform((lato, lato), Image.AFFINE,
                              _al_contrario(a, b, tx, c, d, ty),
                              resample=Image.BICUBIC)


def dove_finisce(punto, trasformata) -> tuple[float, float]:
    a, b, tx, c, d, ty = trasformata
    x, y = punto
    return (a * x + b * y + tx, c * x + d * y + ty)


def _al_contrario(a, b, tx, c, d, ty):
    determinante = a * d - b * c
    if abs(determinante) < 1e-12:
        raise PuntiSbagliati("La trasformazione schiaccia la faccia in una riga.")
    ia, ib = d / determinante, -b / determinante
    ic, id_ = -c / determinante, a / determinante
    return (ia, ib, -(ia * tx + ib * ty), ic, id_, -(ic * tx + id_ * ty))


def _numpy():
    from officina.descrittori import vettori

    return vettori.numpy_o_spiega()
