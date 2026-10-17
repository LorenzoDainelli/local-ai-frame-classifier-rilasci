from __future__ import annotations

import numpy as np
import pytest

from officina.stanza import costruzione, dettaglio, versioni

pytest.importorskip("cv2")


def test_i_tasselli_coprono_tutta_la_foto_4k_e_si_sovrappongono():
    pezzi = dettaglio.tasselli(3840, 2160)
    coperta = np.zeros((2160, 3840), dtype=bool)
    for x0, y0, x1, y1 in pezzi:
        assert x1 - x0 <= dettaglio.TASSELLO and y1 - y0 <= dettaglio.TASSELLO
        assert 0 <= x0 < x1 <= 3840 and 0 <= y0 < y1 <= 2160
        coperta[y0:y1, x0:x1] = True
    assert coperta.all()
    assert len(pezzi) >= 12


def test_una_foto_piccola_non_si_fa_a_pezzi():
    assert dettaglio.misura_fine(1024, 768, 504, 378) is None
    assert dettaglio.misura_fine(3840, 2160, 504, 284) == (1920, 1080)


def test_la_profondita_fine_tiene_la_forma_della_stanza_e_aggiunge_i_dettagli():
    from PIL import Image

    immagine = Image.new("RGB", (2016, 1008))
    grezza = np.full((126, 252), 2.0, dtype=np.float32)
    piatta = dettaglio.profondita_fine(lambda pezzo: np.full((63, 63), 7.0), immagine, grezza)
    assert piatta.shape == (504, 1008)
    assert piatta == pytest.approx(2.0, abs=1e-4)

    def con_un_gradino(pezzo):
        fuori = np.full((126, 126), 5.0, dtype=np.float32)
        fuori[60:66, 60:66] = 4.0
        return fuori

    fine = dettaglio.profondita_fine(con_un_gradino, immagine, grezza)
    assert float(fine.min()) < 1.9
    assert float(np.median(fine)) == pytest.approx(2.0, abs=0.02)


def _vista(x: float, con_la_scatola: bool, quando: str):
    larga, alta, fuoco = 64, 48, 50.0
    matrice = np.array([[fuoco, 0, larga / 2], [0, fuoco, alta / 2], [0, 0, 1.0]])
    estrinseci = np.eye(4)[:3]
    estrinseci = estrinseci.copy()
    estrinseci[:, 3] = [-x, 0.0, 0.0]
    colonne, righe = np.meshgrid(np.arange(larga) + 0.5, np.arange(alta) + 0.5)
    profondita = np.full((alta, larga), 3.0)
    if con_la_scatola:
        mx = x + (colonne - larga / 2) / fuoco * 1.5
        my = (righe - alta / 2) / fuoco * 1.5
        sulla = (np.abs(mx) <= 0.3) & (np.abs(my) <= 0.3)
        profondita[sulla] = 1.5
    buoni = np.ones_like(profondita, dtype=bool)
    punti, _, _ = costruzione.dalla_profondita(profondita, buoni, matrice, estrinseci,
                                               np.zeros((alta, larga, 3), dtype=np.uint8))
    return punti, versioni.Vista(profondita, matrice, estrinseci, buoni, quando)


def test_le_cose_che_ci_sono_solo_in_alcune_foto_diventano_versioni():
    sistemazione = costruzione.Sistemazione(np.eye(3), np.zeros(3), 1.0)
    dati = [_vista(0.08 * i - 0.2, i < 3, f"2024-0{i + 1}-10T10:00:00") for i in range(6)]
    esito = versioni.trova([p for p, _ in dati], [v for _, v in dati], sistemazione)
    assert esito.ci_sono and len(esito.versioni) == 2
    assert esito.gruppo_della_foto[:3] == [1, 1, 1] and esito.gruppo_della_foto[3:] == [2, 2, 2]
    assert esito.versioni[0]["dal"] == "2024-01-10" and esito.versioni[1]["al"] == "2024-06-10"
    zeta = versioni.centri(esito.cambiano)[:, 2]
    assert len(zeta) >= versioni.CUBI_PROPRI_MINIMI
    assert np.all(np.abs(zeta - 1.5) < 0.1)
    scatola = dati[0][0]
    gruppi = versioni.gruppi_dei_punti(scatola, 1, esito)
    davanti = np.abs(scatola[:, 2] - 1.5) < 0.01
    assert (gruppi[davanti] == 1).mean() > 0.9
    assert (gruppi[~davanti] == 0).mean() > 0.9


def test_una_stanza_che_non_cambia_non_ha_versioni():
    sistemazione = costruzione.Sistemazione(np.eye(3), np.zeros(3), 1.0)
    dati = [_vista(0.08 * i - 0.2, True, None) for i in range(6)]
    esito = versioni.trova([p for p, _ in dati], [v for _, v in dati], sistemazione)
    assert not esito.ci_sono
    assert esito.gruppo_della_foto == [0] * 6


def test_a_cubetti_tiene_il_punto_piu_nitido_e_separa_le_versioni():
    punti = np.array([[0.001, 0.001, 0.001], [0.002, 0.002, 0.002], [0.002, 0.002, 0.002]])
    colori = np.array([[1, 1, 1], [2, 2, 2], [3, 3, 3]], dtype=np.uint8)
    fuori, tinte, passi, gruppi = costruzione.a_cubetti(punti, colori, passi=np.array([0.5, 0.1, 0.9]),
                                                        gruppi=np.array([0, 0, 2], dtype=np.uint8))
    assert len(fuori) == 2
    assert sorted(tinte[:, 0].tolist()) == [2, 3]
    assert sorted(gruppi.tolist()) == [0, 2]


def test_la_nuvola_tiene_i_gruppi(tmp_path):
    percorso = tmp_path / "1.npz"
    costruzione._salva_la_nuvola(percorso, np.ones((3, 3)) * 7.25, np.ones((3, 3), dtype=np.uint8),
                                 np.array([0, 1, 2], dtype=np.uint8))
    punti, colori, gruppi = costruzione.leggi_tutta_la_nuvola(percorso)
    assert punti.dtype == np.float32 and float(punti[0, 0]) == 7.25
    assert gruppi.tolist() == [0, 1, 2]
