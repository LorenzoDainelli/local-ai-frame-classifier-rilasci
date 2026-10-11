from __future__ import annotations

from PIL import Image, ImageDraw

from officina.descrittori import preparazione
from officina.finto import immagini


def _con_marchio(dove: tuple[float, float], misura=(800, 600), tema="tema_c",
                 seme=3) -> tuple[Image.Image, tuple[float, float]]:
    immagine = immagini.disegna(tema, seme, misura)
    larghezza, altezza = misura
    lato = int(larghezza * 0.055)
    x, y = int(dove[0] * larghezza), int(dove[1] * altezza)
    disegno = ImageDraw.Draw(immagine, "RGBA")
    disegno.rectangle([x, y, x + lato * 2, y + lato], fill=(245, 245, 240, 235))
    for barra in range(5):
        spessore, passo = lato // 9, lato * 2 // 6
        disegno.rectangle(
            [x + passo // 2 + barra * passo, y + lato // 4,
             x + passo // 2 + barra * passo + spessore, y + lato * 3 // 4],
            fill=(20, 20, 24, 255))
    return immagine, ((x + lato) / larghezza, (y + lato / 2) / altezza)


def test_il_ritaglio_stretto_trova_il_marchio():
    trovati = 0
    posti = [(0.55, 0.62), (0.30, 0.40), (0.70, 0.75), (0.28, 0.70), (0.60, 0.35)]
    for indice, dove in enumerate(posti):
        immagine, centro = _con_marchio(dove, tema=f"tema_{'abcdef'[indice]}",
                                        seme=indice)
        x, y, larga, alta = preparazione.riquadro_del_dettaglio(immagine)
        if x <= centro[0] <= x + larga and y <= centro[1] <= y + alta:
            trovati += 1
    assert trovati == len(posti), (
        f"il ritaglio stretto ha trovato il marchio {trovati} volte su "
        f"{len(posti)}: la regola 37 non regge")


def test_il_marchio_diventa_grande_nel_ritaglio():
    immagine, _ = _con_marchio((0.5, 0.5), misura=(1600, 1200))
    _, _, larga, _ = preparazione.riquadro_del_dettaglio(immagine)
    nel_ritaglio = 224 * (0.11 / larga)
    assert nel_ritaglio > 224 * 0.11 * 2.5
    assert nel_ritaglio >= 70


def test_tre_inquadrature_stessa_misura_e_nomi_giusti():
    immagine = immagini.disegna("tema_a", 1, (900, 600))
    tre = preparazione.tre_inquadrature(immagine, lato=224)
    assert [r.inquadratura for r in tre] == list(preparazione.INQUADRATURE)
    for ritaglio in tre:
        assert ritaglio.immagine.size == (224, 224)
        assert ritaglio.immagine.mode == "RGB"
        assert ritaglio.metodo


def test_il_quadrato_non_taglia_via_niente():
    alta = Image.new("RGB", (600, 1200), (10, 20, 30))
    disegno = ImageDraw.Draw(alta)
    disegno.rectangle([0, 0, 600, 40], fill=(220, 30, 30))
    disegno.rectangle([0, 1160, 600, 1200], fill=(30, 220, 30))

    quadrata = preparazione.in_quadrato(alta, 224)
    assert quadrata.size == (224, 224)
    colori = {colore for _, colore in quadrata.convert("RGB").getcolors(70000)}
    assert any(r > 150 and v < 90 for r, v, _ in colori), "il rosso in cima è sparito"
    assert any(v > 150 and r < 90 for r, v, _ in colori), "il verde in fondo è sparito"


def test_lo_zoom_segue_la_profondita():
    assert preparazione.inquadratura_per_profondita(0) == preparazione.INTERA
    assert preparazione.inquadratura_per_profondita(1) == preparazione.PERSONA
    assert preparazione.inquadratura_per_profondita(2) == preparazione.STRETTO
    assert preparazione.inquadratura_per_profondita(9) == preparazione.STRETTO
