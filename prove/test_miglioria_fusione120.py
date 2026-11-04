from __future__ import annotations

import numpy as np
import pytest

from officina.errori import SpazioInsufficiente
from officina.miglioria import fusione120


def _scena(dove: int, alto: int = 96, largo: int = 160):
    quadro = np.full((alto, largo, 3), 40, dtype=np.uint8)
    righe = np.arange(alto)[:, None]
    colonne = np.arange(largo)[None, :]
    quadro[..., 1] = (60 + 40 * np.sin(colonne / 7.0) + 30 * np.cos(righe / 5.0)).astype(
        np.uint8)
    quadro[30:62, dove:dove + 32] = [220, 180, 30]
    quadro[38:54, dove + 8:dove + 24] = [20, 60, 200]
    return quadro


def _inventato(quadro, dove: int, seme: int = 1):
    fuori = quadro.copy()
    caso = np.random.default_rng(seme)
    fuori[30:62, dove:dove + 32] = caso.integers(0, 255, (32, 32, 3), dtype=np.uint8)
    return fuori


def _media_zona(quadro, dove: int):
    return quadro[30:62, dove:dove + 32].astype(np.float64)


def test_fattore_e_piccolo():
    assert fusione120.fattore(2160, 3840) == 8
    assert fusione120.fattore(100, 200) == 1
    assert fusione120.fattore(481, 10) == 2
    dato = np.arange(4 * 6 * 3, dtype=np.uint8).reshape(4, 6, 3)
    fuori = fusione120.piccolo(dato, 2)
    assert fuori.shape == (2, 3, 3)
    assert fuori[0, 0, 0] == pytest.approx(dato[:2, :2, 0].mean())
    dispari = fusione120.piccolo(np.zeros((5, 7, 3)), 2)
    assert dispari.shape == (3, 4, 3)


def test_scatola_come_la_media_a_mano():
    caso = np.random.default_rng(3)
    mappa = caso.random((9, 11))
    fuori = fusione120.scatola(mappa, 2)
    largo = np.pad(mappa, 2, mode="edge")
    for r in range(9):
        for c in range(11):
            assert fuori[r, c] == pytest.approx(largo[r:r + 5, c:c + 5].mean())
    assert np.array_equal(fusione120.scatola(mappa, 0), mappa)


def test_a_blocchi_media_per_zona():
    mappa = np.arange(36, dtype=np.float64).reshape(6, 6)
    fuori = fusione120.a_blocchi(mappa, 3)
    assert fuori.shape == (2, 2)
    assert fuori[1, 0] == pytest.approx(mappa[3:6, 0:3].mean())
    assert fusione120.a_blocchi(np.zeros((7, 5, 2)), 3).shape == (3, 2, 2)


def test_costo_trova_lo_spostamento():
    caso = np.random.default_rng(5)
    trama = caso.integers(0, 255, (48, 120, 3)).astype(np.float32)
    prima, spostato = trama[:, 0:96], trama[:, 6:102]
    vicino = fusione120.costo(spostato, prima, raggio=8, zona=4)
    lontano = fusione120.costo(spostato, prima, raggio=2, zona=4)
    assert vicino.shape == (12, 24)
    assert vicino[:, :22].max() < 1e-3
    assert lontano[:, :22].min() > 100


def test_ingrandisci_conserva_le_costanti_e_gli_estremi():
    mappa = np.array([[0.0, 1.0], [0.0, 1.0]])
    fuori = fusione120.ingrandisci(mappa, 8, 8, 4)
    assert fuori.shape == (8, 8)
    assert fuori[:, 0].max() == 0.0 and fuori[:, -1].min() == 1.0
    assert np.all(np.diff(fuori[0]) >= 0)
    piatta = fusione120.ingrandisci(np.full((3, 3), 0.25), 12, 10, 4)
    assert np.allclose(piatta, 0.25)


def test_uguali_esce_lo_stesso():
    quadro = _scena(50)
    assert np.array_equal(fusione120.fondi(quadro, quadro, _scena(40), _scena(60)), quadro)


def test_d_accordo_si_uniscono():
    prima, dopo = _scena(40), _scena(60)
    giusto = _scena(50)
    poco = np.clip(giusto.astype(np.int16) + 2, 0, 255).astype(np.uint8)
    fuori = fusione120.fondi(giusto, poco, prima, dopo)
    atteso = (giusto.astype(np.float64) + poco) / 2
    assert np.abs(fuori - atteso).max() <= 1.0


@pytest.mark.parametrize("giusto_e_gimm", [True, False])
def test_in_disaccordo_vince_chi_combacia_coi_veri(giusto_e_gimm):
    prima, dopo = _scena(40), _scena(60)
    giusto = _scena(50)
    sbagliato = _inventato(giusto, 50)
    g, l = (giusto, sbagliato) if giusto_e_gimm else (sbagliato, giusto)
    fuori = fusione120.fondi(g, l, prima, dopo)
    zona_giusta = _media_zona(giusto, 50)[6:-6, 6:-6]
    zona_fuori = _media_zona(fuori, 50)[6:-6, 6:-6]
    zona_sbagliata = _media_zona(sbagliato, 50)[6:-6, 6:-6]
    assert np.abs(zona_fuori - zona_giusta).mean() < 0.25 * np.abs(
        zona_sbagliata - zona_giusta).mean()
    lontano = (slice(0, 20), slice(110, 160))
    assert np.array_equal(fuori[lontano], giusto[lontano])


def test_un_buco_visto_solo_da_un_lato_vale_lo_stesso():
    prima, dopo = _scena(40), _scena(60)
    dopo[30:62, 60:92] = 40
    giusto = _scena(50)
    sbagliato = _inventato(giusto, 50, seme=7)
    fuori = fusione120.fondi(sbagliato, giusto, prima, dopo)
    assert np.abs(_media_zona(fuori, 50)[6:-6, 6:-6]
                  - _media_zona(giusto, 50)[6:-6, 6:-6]).mean() < 20


def test_misure_diverse_si_ferma():
    with pytest.raises(fusione120.FusioneStorta):
        fusione120.fondi(_scena(40), _scena(40, 64), _scena(40), _scena(40))
    with pytest.raises(fusione120.FusioneStorta):
        fusione120.fondi(_scena(40), _scena(40), _scena(40, 64), _scena(40))


def test_grande_lavora_in_piccolo():
    grande = np.zeros((1000, 1500, 3), dtype=np.uint8)
    chiamati = []
    vere = fusione120.mappe

    def spia(*argomenti, **nomi):
        chiamati.append(argomenti[0].shape)
        return vere(*argomenti, **nomi)

    fusione120.mappe = spia
    try:
        assert fusione120.fondi(grande, grande, grande, grande).shape == grande.shape
    finally:
        fusione120.mappe = vere
    assert chiamati == [(250, 375, 3)]


def test_deposito_tiene_e_butta(tmp_path):
    deposito = fusione120.Deposito(tmp_path)
    quadro = _scena(40)
    deposito.metti(3, quadro)
    assert np.array_equal(deposito.prendi(3), quadro)
    assert deposito.casa.parent == tmp_path
    for numero in range(10):
        deposito.metti(10 + numero, quadro)
        deposito.prendi(10 + numero)
    assert len(deposito._vicini) <= fusione120.VICINI_TENUTI
    deposito.butta()
    assert not deposito.casa.exists()


def test_deposito_poco_spazio_si_ferma(tmp_path, monkeypatch):
    deposito = fusione120.Deposito(tmp_path)

    class Poco:
        free = fusione120.MARGINE

    monkeypatch.setattr(fusione120.shutil, "disk_usage", lambda _posto: Poco)
    with pytest.raises(SpazioInsufficiente) as preso:
        deposito.metti(0, _scena(40))
    assert "GB liberi" in preso.value.messaggio
    deposito.butta()


class _Finto:

    def __init__(self, segno: int, quanti_in_piu: int = 0) -> None:
        self.segno = segno
        self.quanti_in_piu = quanti_in_piu
        self.spento = 0
        self.aperti = 0

    def video(self, quadri, volte, al_quadro=None):
        self.aperti += 1
        veri = list(quadri)
        for numero, quadro in enumerate(veri):
            yield quadro
            if numero + 1 < len(veri):
                for passo in range(1, volte):
                    fatto = quadro.copy()
                    fatto[0, 0, 0] = self.segno + passo
                    yield fatto
        for _ in range(volte - 1 + self.quanti_in_piu):
            yield veri[-1]

    def spegni(self):
        self.spento += 1


def _veri(quanti: int):
    return [_scena(30 + 8 * n) for n in range(quanti)]


def test_video_unisce_e_tiene_i_veri(tmp_path, monkeypatch):
    veri = _veri(3)
    fusi = []

    def finto_fondi(g, l, prima, dopo):
        fusi.append((int(g[0, 0, 0]), int(l[0, 0, 0]), prima, dopo))
        return np.full_like(g, 7)

    monkeypatch.setattr(fusione120, "fondi", finto_fondi)
    gimm, ldf = _Finto(100), _Finto(200)
    passi = []
    motore = fusione120.Fusione(gimm, ldf, tmp_path)
    fuori = list(motore.video(lambda: iter(veri), 4, passi.append))
    assert len(fuori) == 12
    for numero in (0, 4, 8):
        assert np.array_equal(fuori[numero], veri[numero // 4])
    for numero in (9, 10, 11):
        assert np.array_equal(fuori[numero], veri[-1])
    assert [int(f[0, 0, 0]) for f in fuori[1:4] + fuori[5:8]] == [7] * 6
    assert [(g, l) for g, l, _, _ in fusi] == [(101, 201), (102, 202), (103, 203)] * 2
    assert np.array_equal(fusi[0][2], veri[0]) and np.array_equal(fusi[0][3], veri[1])
    assert np.array_equal(fusi[3][2], veri[1]) and np.array_equal(fusi[3][3], veri[2])
    assert passi == [1, 2]
    assert gimm.spento == 1 and gimm.aperti == 1 and ldf.aperti == 1
    assert list(tmp_path.iterdir()) == []


def test_video_conti_diversi_si_ferma(tmp_path):
    motore = fusione120.Fusione(_Finto(100), _Finto(200, quanti_in_piu=1), tmp_path)
    with pytest.raises(fusione120.FusioneStorta):
        list(motore.video(lambda: iter(_veri(2)), 2))
    assert list(tmp_path.iterdir()) == []
    meno = fusione120.Fusione(_Finto(100, quanti_in_piu=1), _Finto(200), tmp_path)
    with pytest.raises(fusione120.FusioneStorta):
        list(meno.video(lambda: iter(_veri(2)), 2))
    assert list(tmp_path.iterdir()) == []


def test_video_volte_sbagliate_e_spegni(tmp_path):
    gimm, ldf = _Finto(1), _Finto(2)
    motore = fusione120.Fusione(gimm, ldf, tmp_path)
    with pytest.raises(ValueError):
        list(motore.video(lambda: iter(_veri(2)), 1))
    motore.spegni()
    assert gimm.spento == 1 and ldf.spento == 1


def test_video_vuoto(tmp_path):
    class Vuoto(_Finto):
        def video(self, quadri, volte, al_quadro=None):
            return iter(())

    motore = fusione120.Fusione(Vuoto(1), Vuoto(2), tmp_path)
    assert list(motore.video(lambda: iter(()), 2)) == []
