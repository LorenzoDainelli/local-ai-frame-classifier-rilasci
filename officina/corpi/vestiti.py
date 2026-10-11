from __future__ import annotations

from officina.corpi import maschere
from officina.descrittori import vettori

GRIGIO = (128, 128, 128)
LATO_MINIMO = 16


def sagoma(immagine, riquadro, maschera: bytes = b"", sfondo=GRIGIO,
           lato_finale: int | None = None):
    from PIL import Image

    numpy = vettori.numpy_o_spiega()
    larga, alta = immagine.size
    x, y, w, h = riquadro
    sinistra, sopra = max(0, int(round(x * larga))), max(0, int(round(y * alta)))
    destra = min(larga, max(int(round((x + w) * larga)), sinistra + 1))
    sotto = min(alta, max(int(round((y + h) * alta)), sopra + 1))
    pezzo = immagine.convert("RGB").crop((sinistra, sopra, destra, sotto))
    if pezzo.width < LATO_MINIMO or pezzo.height < LATO_MINIMO:
        return None
    forma = maschere.apri(maschera)
    if forma.size:
        grande = Image.fromarray(forma.astype(numpy.uint8) * 255, "L").resize(
            pezzo.size, Image.BILINEAR)
        pezzo = Image.composite(pezzo, Image.new("RGB", pezzo.size, sfondo), grande)
    lato = max(pezzo.size)
    quadro = Image.new("RGB", (lato, lato), sfondo)
    quadro.paste(pezzo, ((lato - pezzo.width) // 2, (lato - pezzo.height) // 2))
    if lato_finale and lato != lato_finale:
        quadro = quadro.resize((lato_finale, lato_finale), Image.BILINEAR)
    return quadro
