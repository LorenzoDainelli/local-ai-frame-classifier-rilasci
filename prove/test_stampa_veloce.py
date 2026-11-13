import io
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

PIL = pytest.importorskip("PIL")
from PIL import Image

from officina.miglioria import motori, stampa, stampa_stanza


class TurnoFinto:

    def __init__(self):
        self.chi = None

    def prendi_se_libera(self, lavoro):
        self.chi = lavoro
        return True

    def lascia(self, lavoro):
        self.chi = None


class SostaFinta:

    def __init__(self):
        self.giri = []

    def guarda(self, serve):
        self.serve = serve

    def subito(self):
        self.giri.append(self.serve())

    def giro(self):
        self.giri.append(self.serve())

    def smetti(self, aspetta=0):
        return True


class Ingranditore:

    def foto(self, immagine, larghezza, altezza):
        return immagine.resize((larghezza, altezza))

    def sistema(self, immagine, persone=None):
        return immagine.transpose(Image.Transpose.FLIP_LEFT_RIGHT)

    def spegni(self):
        pass


def _jpeg(larghezza, altezza):
    fuori = io.BytesIO()
    Image.new("RGB", (larghezza, altezza), (200, 30, 30)).save(fuori, "JPEG")
    fuori.seek(0)
    return fuori


def _stampa(tmp_path, monkeypatch):
    monkeypatch.setattr(motori, "apri", lambda *a, **k: Ingranditore())
    monkeypatch.setattr(motori, "tieni_accesi", lambda: None)

    def lancia(lavoro, al_passo):
        return {"fatto": stampa_stanza.corri(lavoro, al_passo)}

    archivio = SimpleNamespace(dove=SimpleNamespace(modelli=tmp_path),
                               impostazione=lambda chiave: None)
    sosta = SostaFinta()
    fatta = stampa.Stampa(archivio, cartella=tmp_path / "s", lancia=lancia,
                          turno=TurnoFinto(), pronta=lambda: True,
                          volti=lambda: motori.CODEFORMER, sosta=sosta)
    monkeypatch.setattr(stampa.Stampa, "_la_sosta", lambda self: sosta)
    return fatta, sosta


def test_misura_di_arrivo_e_forma():
    assert stampa.misura_di(2048, 1365) == (4096, 2730)
    assert stampa.misura_di(2016, 3024) == (2731, 4096)
    assert stampa.misura_di(4284, 5712) is None
    assert stampa.misura_di(4096, 2731) is None
    assert stampa.e_due_terzi(3024, 2016) and stampa.e_due_terzi(2016, 3024)
    assert not stampa.e_due_terzi(4032, 3024)


def test_dall_importazione_allo_zip(tmp_path, monkeypatch):
    fatta, sosta = _stampa(tmp_path, monkeypatch)
    piccola = fatta.aggiungi("mare.jpg", _jpeg(300, 200))
    storta = fatta.aggiungi("../storta.jpg", _jpeg(400, 300))
    grande = fatta.aggiungi("grande.jpg", _jpeg(4500, 3000))
    assert piccola["due_terzi"] and not storta["due_terzi"]
    assert grande["arrivo"] is None
    assert "/" not in storta["file"] and ".." not in storta["file"].split("-", 1)[0]
    fatta._gira()
    assert sosta.giri == [True, False]
    foto = {uno["id"]: uno for uno in fatta.come_va()["foto"]}
    assert foto[piccola["id"]]["fatte"] == ["seedvr2", "volti"]
    assert foto[grande["id"]]["fatte"] == []
    with Image.open(fatta.file_di(foto[piccola["id"]], "seedvr2")) as fatto:
        assert fatto.size == (4096, 2731)
    fatta.scegli(piccola["id"], "volti")
    fatta.scegli(grande["id"], "originali")
    with pytest.raises(Exception):
        fatta.scegli(grande["id"], "seedvr2")
    verso = tmp_path / "z.zip"
    assert fatta.zip(verso) == 2
    with zipfile.ZipFile(verso) as letto:
        nomi = sorted(letto.namelist())
        assert nomi == ["grande.jpg", "mare.jpg"]
        with Image.open(io.BytesIO(letto.read("mare.jpg"))) as uscita:
            assert uscita.size == (4096, 2731) and uscita.format == "JPEG"
    assert fatta.vista(piccola["id"], "volti").is_file()
    assert fatta.vista(piccola["id"], "../x") is None


def test_ripartendo_non_rifa_le_gia_fatte(tmp_path, monkeypatch):
    fatta, _sosta = _stampa(tmp_path, monkeypatch)
    uno = fatta.aggiungi("a.jpg", _jpeg(300, 200))
    fatta._gira()
    prima = fatta.file_di(uno, "seedvr2").stat().st_mtime_ns
    fatta._gira()
    assert fatta.file_di(uno, "seedvr2").stat().st_mtime_ns == prima
    fatta.svuota()
    assert not Path(fatta.cartella).exists()


def test_non_foto_rifiutata(tmp_path, monkeypatch):
    fatta, _sosta = _stampa(tmp_path, monkeypatch)
    with pytest.raises(Exception):
        fatta.aggiungi("x.jpg", io.BytesIO(b"non sono una foto"))
    assert fatta.come_va()["foto"] == []


def test_pagina_e_caricamento(archivio, monkeypatch):
    from fastapi.testclient import TestClient

    from officina.web.server import app
    from officina.web.strade import stampa as strada

    monkeypatch.setattr(strada, "_stampa", None)
    cliente = TestClient(app, client=("127.0.0.1", 51000))
    pagina = cliente.get("/stampa")
    assert pagina.status_code == 200 and "Stampa veloce" in pagina.text
    grande = _jpeg(1500, 1000).getvalue()
    assert len(grande) > 0
    risposta = cliente.post("/api/stampa/aggiungi",
                            files=[("foto", ("a.jpg", grande, "image/jpeg")),
                                   ("foto", ("b.jpg", b"niente", "image/jpeg"))])
    assert risposta.status_code == 200
    assert risposta.json()["aggiunte"] == 1 and len(risposta.json()["sbagliate"]) == 1
    stato = cliente.get("/api/stampa").json()
    assert stato["foto"][0]["arrivo"] == [4096, 2731]
    vista = cliente.get(f"/api/stampa/{stato['foto'][0]['id']}/originali.jpg")
    assert vista.status_code == 200
    assert cliente.get("/api/stampa/scarica").status_code == 409
    assert cliente.post("/api/stampa/svuota").status_code == 200
    strada.la_stampa(archivio).ferma()
