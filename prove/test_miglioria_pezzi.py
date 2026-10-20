from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from officina.miglioria import catena, motori, pezzi, seedvr2, video
from prove.test_miglioria_seedvr2 import _motore_finto, finto  # noqa: F401


def _filmato(dove: Path, quanti: int = 25) -> Path:
    import av

    with av.open(str(dove), "w") as fuori:
        traccia = fuori.add_stream("libx264", rate=10)
        traccia.width, traccia.height, traccia.pix_fmt = 32, 24, "yuv420p"
        for numero in range(quanti):
            tela = np.full((24, 32, 3), (numero * 9) % 256, dtype=np.uint8)
            tela[:, numero % 32] = 255
            for pacchetto in traccia.encode(av.VideoFrame.from_ndarray(tela, format="rgb24")):
                fuori.mux(pacchetto)
        for pacchetto in traccia.encode():
            fuori.mux(pacchetto)
    return dove


def _quadri(percorso: Path) -> list:
    return list(video.dritti(percorso))


class Spento(Exception):
    pass


@pytest.fixture
def piccolo(monkeypatch):
    monkeypatch.setattr(catena, "PER_VOLTA", 10)
    monkeypatch.setattr(catena.misura, "di_arrivo", lambda larga, alta, pari=False: (64, 48))


def _lavoro(tmp_path: Path, originale: Path) -> dict:
    attesa = tmp_path / ".in-revisione"
    attesa.mkdir(exist_ok=True)
    return {"genere": "video", "originale": str(originale),
            "uscita": str(attesa / "1-a.mp4.parziale"), "motori": {"video": motori.FINTO}}


def test_i_pezzi_si_rileggono_identici_e_solo_di_fila(tmp_path):
    dove = tmp_path / ".in-revisione" / "1-a.mp4.parziale.pezzi"
    fatti = pezzi.Pezzi(dove, {"a": 1})
    primi = [np.random.default_rng(i).integers(0, 256, (24, 32, 3), dtype=np.uint8) for i in range(3)]
    fatti.salva(0, primi)
    fatti.salva(5, primi)
    assert fatti.fatti() == 3
    assert all((a == b).all() for a, b in zip(fatti.rileggi(), primi))
    assert pezzi.Pezzi(dove, {"a": 1}).fatti() == 3
    assert pezzi.Pezzi(dove, {"a": 2}).fatti() == 0


def test_spento_a_meta_riprende_dal_pezzo_dopo_e_viene_uguale(tmp_path, monkeypatch, piccolo):
    originale = _filmato(tmp_path / "a.mp4")
    intero = _lavoro(tmp_path, originale)
    catena.filmato(dict(intero, uscita=str(tmp_path / ".in-revisione" / "2-a.mp4.parziale")))
    atteso = _quadri(tmp_path / ".in-revisione" / "2-a.mp4.parziale")

    vero = motori.Finto.video
    visti = []

    def si_spegne(self, quadri, larghezza, altezza, salta=0, al_pezzo=None):
        for numero, quadro in enumerate(vero(self, quadri, larghezza, altezza, salta=salta),
                                        start=salta):
            if numero == 13:
                raise Spento()
            visti.append(numero)
            yield quadro

    monkeypatch.setattr(motori.Finto, "video", si_spegne)
    with pytest.raises(Spento):
        catena.filmato(intero)
    cantiere = pezzi.cartella(Path(intero["uscita"]))
    assert [file.name for file in cantiere.glob("*.mkv")] == ["00000000-00010.mkv"]
    assert visti == list(range(13))

    contati = []

    def conta(self, quadri, larghezza, altezza, salta=0, al_pezzo=None):
        contati.append(salta)
        return vero(self, quadri, larghezza, altezza, salta=salta)

    monkeypatch.setattr(motori.Finto, "video", conta)
    passi = []
    catena.filmato(intero, al_passo=lambda f, t: passi.append((f, t)))
    assert contati == [10]
    assert passi[0][0] == 10 and passi[-1][0] == 25
    rifatto = _quadri(Path(intero["uscita"]))
    assert len(rifatto) == len(atteso) == 25
    assert all((a == b).all() for a, b in zip(rifatto, atteso))
    assert not cantiere.exists()


def test_cambiato_l_originale_si_rifà_da_capo(tmp_path, monkeypatch, piccolo):
    originale = _filmato(tmp_path / "a.mp4")
    lavoro = _lavoro(tmp_path, originale)
    cantiere = pezzi.cartella(Path(lavoro["uscita"]))
    vecchi = pezzi.Pezzi(cantiere, {"vecchia": True})
    vecchi.salva(0, [np.zeros((48, 64, 3), np.uint8)] * 10)
    contati = []
    vero = motori.Finto.video

    def conta(self, quadri, larghezza, altezza, salta=0, al_pezzo=None):
        contati.append(salta)
        return vero(self, quadri, larghezza, altezza, salta=salta)

    monkeypatch.setattr(motori.Finto, "video", conta)
    catena.filmato(lavoro)
    assert contati == [0]


def test_seedvr2_saltando_ha_lo_stesso_contesto_e_conta_dentro_il_pezzo(finto, monkeypatch):  # noqa: F811
    motore, visti = _motore_finto(finto, monkeypatch)
    quadri = [np.full((4, 6, 3), i, np.uint8) for i in range(100)]
    list(motore.video(iter(quadri), 12, 8))
    tutti = list(visti)
    visti.clear()
    usciti = list(motore.video(iter(quadri), 12, 8, salta=seedvr2.QUADRI_PER_VOLTA))
    assert visti == tutti[1:]
    assert [int(q[0, 0, 0]) for q in usciti] == list(range(seedvr2.QUADRI_PER_VOLTA, 100))


def test_le_fasi_di_seedvr2_fanno_avanzare_il_contatore(finto):  # noqa: F811
    from officina.miglioria import scaricamento

    scaricamento.scarica(finto["modelli"], prendi_testo=finto["prendi_testo"],
                         prendi_peso=finto["prendi_peso"])
    motore = seedvr2.SeedVR2(cartella_modelli=str(finto["modelli"]))
    visto = []
    motore._avanza = visto.append
    motore._fase("upscale")(3, 6, [], "Phase 2")
    motore._fase("decode")(6, 6)
    motore._fase("encode")("x", None)
    assert visto == [pytest.approx(0.5), pytest.approx(0.97)]
    motore._avanza = None
    assert motore._fase("upscale") is None
