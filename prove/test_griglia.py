from __future__ import annotations

import pytest
from PIL import Image

from officina.descrittori import griglia


@pytest.mark.parametrize("larghezza, altezza, colonne, righe", [
    (3000, 4000, 6, 8),
    (4000, 3000, 8, 6),
    (1920, 1080, 8, 5),
    (8000, 2000, 8, 2),
    (1000, 1000, 8, 8),
])
def test_la_griglia_segue_la_forma_del_fotogramma(larghezza, altezza, colonne, righe):
    assert griglia.quante(larghezza, altezza) == (colonne, righe)
    assert len(griglia.caselle(larghezza, altezza)) == colonne * righe


def test_le_caselle_sono_quadrate_nei_pixel_veri():
    for larghezza, altezza in [(3000, 4000), (8000, 2000), (1920, 1080)]:
        for casella in griglia.caselle(larghezza, altezza):
            _, _, larga, alta = casella.riquadro
            assert larga * larghezza == pytest.approx(alta * altezza, rel=0.02)


def test_le_caselle_si_sovrappongono():
    caselle = griglia.caselle(1000, 1000)
    prima = next(c for c in caselle if c.riga == 0 and c.colonna == 0)
    seconda = next(c for c in caselle if c.riga == 0 and c.colonna == 1)
    fine_della_prima = prima.riquadro[0] + prima.riquadro[2]
    assert seconda.riquadro[0] < fine_della_prima


def test_nessuna_casella_esce_dalla_fotografia():
    for larghezza, altezza in [(3000, 4000), (8000, 2000), (640, 480)]:
        for casella in griglia.caselle(larghezza, altezza):
            x, y, larga, alta = casella.riquadro
            assert x >= 0 and y >= 0
            assert x + larga <= 1.0 + 1e-9
            assert y + alta <= 1.0 + 1e-9


def test_tutta_la_fotografia_e_coperta():
    larghezza, altezza = 1920, 1080
    caselle = griglia.caselle(larghezza, altezza)
    for x in range(0, larghezza, 37):
        for y in range(0, altezza, 41):
            fx, fy = x / larghezza, y / altezza
            dentro = any(c.riquadro[0] <= fx <= c.riquadro[0] + c.riquadro[2]
                         and c.riquadro[1] <= fy <= c.riquadro[1] + c.riquadro[3]
                         for c in caselle)
            assert dentro, f"il punto {x},{y} non lo guarda nessuno"


def test_i_nomi_si_mettono_in_fila_da_soli():
    nomi = [c.nome for c in griglia.caselle(1000, 1000)]
    assert nomi == sorted(nomi)
    assert nomi[0] == "griglia_r00c00"
    assert all(griglia.e_una_casella(nome) for nome in nomi)
    assert not griglia.e_una_casella("intera")


def test_i_ritagli_escono_quadrati_e_alla_misura_giusta():
    immagine = Image.new("RGB", (1200, 900), (200, 30, 30))
    ritagli = griglia.ritagli(immagine)
    assert len(ritagli) == 8 * 6
    for ritaglio in ritagli:
        assert ritaglio.immagine.size == (griglia.LATO, griglia.LATO)
        assert ritaglio.metodo == griglia.METODO


def test_una_cosa_piccola_in_un_angolo_finisce_dentro_una_casella():
    immagine = Image.new("RGB", (2400, 1600), (240, 240, 240))
    immagine.paste((0, 200, 0), (2200, 1400, 2380, 1580))

    def quanto_verde(pezzo):
        crudi = pezzo.convert("RGB").tobytes()
        terne = [crudi[i:i + 3] for i in range(0, len(crudi), 3)]
        verdi = sum(1 for r, g, _ in terne if g > 150 and r < 120)
        return verdi / len(terne)

    intera = quanto_verde(immagine)
    migliore = max(quanto_verde(r.immagine) for r in griglia.ritagli(immagine))
    assert intera < 0.02
    assert migliore > intera * 5


def test_il_massimo_trova_la_cosa_piccola_e_la_media_la_diluisce():
    punteggi = [0.02] * 39 + [0.95]
    assert griglia.combina(punteggi, griglia.MASSIMO) == pytest.approx(0.95)
    assert griglia.combina(punteggi, griglia.MEDIA) < 0.05


def test_senza_nessuna_casella_non_si_inventa_un_punteggio():
    assert griglia.combina([], griglia.MASSIMO) == 0.0
    assert griglia.combina([], griglia.MEDIA) == 0.0


def test_le_caselle_tornano_al_loro_scatto():
    scatti = [7, 7, 7, 9, 9]
    punteggi = [0.1, 0.8, 0.2, 0.4, 0.5]
    assert griglia.combina_per_scatto(scatti, punteggi, griglia.MASSIMO) == {
        7: pytest.approx(0.8), 9: pytest.approx(0.5)}
    medie = griglia.combina_per_scatto(scatti, punteggi, griglia.MEDIA)
    assert medie[7] == pytest.approx((0.1 + 0.8 + 0.2) / 3)
