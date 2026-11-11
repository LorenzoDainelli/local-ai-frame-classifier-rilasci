from __future__ import annotations

import hashlib
import shutil
import threading
import time
from pathlib import Path

import numpy as np
import pytest

from officina.miglioria import catena, fluido, motori, pezzi, veloce, video
from prove.test_miglioria_centoventi import FluidoFinto
from prove.test_miglioria_pezzi import _filmato, _lavoro, piccolo

__all__ = ["piccolo"]


@pytest.fixture(autouse=True)
def x264_sempre_uguale(monkeypatch):
    monkeypatch.setitem(video.OPZIONI, video.H264,
                        {**video.OPZIONI[video.H264], "threads": "1",
                         "x264-params": "mbtree=0"})
    monkeypatch.setitem(video.OPZIONI, video.HEVC,
                        {**video.OPZIONI[video.HEVC], "threads": "1"})


def _impronta(percorso: Path) -> str:
    return hashlib.sha256(Path(percorso).read_bytes()).hexdigest()


def test_spento_fa_subito_e_nello_stesso_filo():
    fili = []
    fondo = veloce.Fondo(3, acceso=False)
    fondo.metti(lambda: fili.append(threading.current_thread()), 1)
    assert fili == [threading.current_thread()]
    fondo.fine()


def test_acceso_fa_dietro_e_aspetta_tutto_alla_fine():
    fatti = []

    def piano(numero):
        time.sleep(0.05)
        fatti.append(numero)

    fondo = veloce.Fondo(2, libera=lambda: None)
    for numero in range(5):
        fondo.metti(piano, 1, numero)
    fondo.fine()
    assert sorted(fatti) == list(range(5))


def test_non_supera_i_fili():
    dentro, massimo = [0], [0]
    serratura = threading.Lock()

    def conta():
        with serratura:
            dentro[0] += 1
            massimo[0] = max(massimo[0], dentro[0])
        time.sleep(0.03)
        with serratura:
            dentro[0] -= 1

    fondo = veloce.Fondo(2, libera=lambda: None)
    for _ in range(8):
        fondo.metti(conta, 1)
    fondo.fine()
    assert massimo[0] == 2


def test_con_la_ram_poca_ne_fa_uno_alla_volta():
    dentro, massimo = [0], [0]
    serratura = threading.Lock()

    def conta():
        with serratura:
            dentro[0] += 1
            massimo[0] = max(massimo[0], dentro[0])
        time.sleep(0.03)
        with serratura:
            dentro[0] -= 1

    fondo = veloce.Fondo(3, libera=lambda: veloce.MARGINE + 10)
    for _ in range(6):
        fondo.metti(conta, 100)
    fondo.fine()
    assert massimo[0] == 1


def test_un_guasto_dietro_esce_alla_fine():
    def rotto():
        raise OSError("disco")

    fondo = veloce.Fondo(2, libera=lambda: None)
    fondo.metti(rotto, 1)
    with pytest.raises(OSError):
        fondo.fine()


def test_si_accendono_solo_le_idee_conosciute():
    assert veloce.accese({"scrittura": True, "altro": True}) == ["scrittura"]
    assert veloce.accese({"scrittura": False}) == []
    assert veloce.accese(None) == []
    assert veloce.acceso({"veloce": ["scrittura"]}, veloce.SCRITTURA)
    assert not veloce.acceso({}, veloce.SCRITTURA)


def test_il_segnale_fermo_sblocca_chi_aspetta():
    segnale = veloce.Segnale()
    errori = []

    def aspetta():
        try:
            segnale.aspetta(lambda: False, ogni=0.01)
        except veloce.Fermo:
            errori.append("fermo")

    filo = threading.Thread(target=aspetta)
    filo.start()
    segnale.ferma()
    filo.join(2)
    assert errori == ["fermo"]


def test_seguire_legge_i_pezzi_man_mano(tmp_path):
    pytest.importorskip("av")
    fatti = pezzi.Pezzi(tmp_path / "x.pezzi", {"a": 1})
    fatti.segnale = veloce.Segnale()
    quadri = [np.random.default_rng(i).integers(0, 256, (24, 32, 3), dtype=np.uint8)
              for i in range(6)]
    letti = []
    filo = threading.Thread(target=lambda: letti.extend(fatti.segui()))
    filo.start()
    fatti.salva(0, quadri[:3])
    time.sleep(0.05)
    fatti.salva(3, quadri[3:])
    fatti.segna_finito()
    filo.join(5)
    assert len(letti) == 6
    assert all((a == b).all() for a, b in zip(letti, quadri, strict=True))


def test_seguire_si_accorge_se_manca_un_pezzo(tmp_path):
    pytest.importorskip("av")
    fatti = pezzi.Pezzi(tmp_path / "x.pezzi", {"a": 1})
    fatti.segnale = veloce.Segnale()
    fatti.salva(0, [np.zeros((24, 32, 3), dtype=np.uint8)])
    fatti.salva(5, [np.zeros((24, 32, 3), dtype=np.uint8)])
    fatti.segna_finito()
    (tmp_path / "x.pezzi" / "00000000-00001.mkv").unlink()
    with pytest.raises(pezzi.PezzoRotto):
        list(fatti.segui())


def _sorgente(tmp_path: Path, cartella: Path) -> Path:
    unica = tmp_path / "sorgente.mp4"
    if not unica.exists():
        _filmato(unica, quanti=37)
    cartella.mkdir()
    shutil.copyfile(unica, cartella / "a.mp4")
    return cartella / "a.mp4"


def _giro(tmp_path: Path, nome: str, accese: list[str], **piu) -> str:
    cartella = tmp_path / nome
    originale = _sorgente(tmp_path, cartella)
    lavoro_ = dict(_lavoro(cartella, originale), **piu)
    if accese:
        lavoro_["veloce"] = accese
    catena.filmato(lavoro_)
    return _impronta(lavoro_["uscita"])


def test_il_video_esce_identico_bit_per_bit(tmp_path, piccolo):
    assert _giro(tmp_path, "vecchio", []) == _giro(tmp_path, "nuovo", ["scrittura"])


def test_il_video_a_120_esce_identico_bit_per_bit(tmp_path, piccolo, monkeypatch):
    monkeypatch.setattr(fluido, "Motore", FluidoFinto)
    monkeypatch.setattr(fluido, "SECONDI_PER_TRATTO", 0.25)
    monkeypatch.setattr(veloce, "fili_per_scrivere", lambda: 3)
    vecchio = _giro(tmp_path, "vecchio", [], fps120="gimm")
    assert vecchio == _giro(tmp_path, "nuovo", ["scrittura"], fps120="gimm")


class Cade(Exception):
    pass


def test_se_il_motore_cade_la_copia_a_meta_sparisce_e_dopo_esce_identico(
        tmp_path, piccolo, monkeypatch):
    pulito = _giro(tmp_path, "pulito", [])
    originale = _sorgente(tmp_path, tmp_path / "cade")
    lavoro_ = dict(_lavoro(tmp_path / "cade", originale), veloce=["scrittura"])
    vero = motori.Finto.video

    def a_meta(self, quadri, *argomenti, **chiavi):
        for numero, quadro in enumerate(vero(self, quadri, *argomenti, **chiavi)):
            if numero == 25:
                raise Cade()
            yield quadro

    monkeypatch.setattr(motori.Finto, "video", a_meta)
    with pytest.raises(Cade):
        catena.filmato(lavoro_)
    assert not Path(lavoro_["uscita"]).exists()
    assert pezzi.Pezzi(pezzi.cartella(Path(lavoro_["uscita"])),
                       _firma_di(lavoro_)).fatti() == 20
    monkeypatch.setattr(motori.Finto, "video", vero)
    catena.filmato(lavoro_)
    assert _impronta(lavoro_["uscita"]) == pulito


def _firma_di(lavoro_: dict) -> dict:
    motore = motori.Finto()
    return catena._firma(Path(lavoro_["originale"]), motore, 64, 48)


def test_ripresa_con_i_pezzi_gia_finiti(tmp_path, piccolo, monkeypatch):
    pulito = _giro(tmp_path, "pulito", [])
    cartella = tmp_path / "ripresa"
    originale = _sorgente(tmp_path, cartella)
    lavoro_ = _lavoro(cartella, originale)
    vero = catena.video.lavora

    def rotto(*_argomenti, **_chiavi):
        raise Cade()

    monkeypatch.setattr(catena.video, "lavora", rotto)
    with pytest.raises(Cade):
        catena.filmato(lavoro_)
    monkeypatch.setattr(catena.video, "lavora", vero)
    fatti = pezzi.Pezzi(pezzi.cartella(Path(lavoro_["uscita"])), _firma_di(lavoro_))
    assert fatti.finito
    catena.filmato(dict(lavoro_, veloce=["scrittura"]))
    assert _impronta(lavoro_["uscita"]) == pulito
    assert not fatti.dove.exists()
