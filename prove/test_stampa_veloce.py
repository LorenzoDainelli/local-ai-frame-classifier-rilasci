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


def test_pagina_nel_browser(archivio, monkeypatch, tmp_path):
    sync_api = pytest.importorskip("playwright.sync_api")
    from fastapi.testclient import TestClient

    from officina.web.server import app
    from officina.web.strade import stampa as strada

    monkeypatch.setattr(strada, "_stampa", None)
    cliente = TestClient(app, client=("127.0.0.1", 51000))
    errori = []
    arrivate = []

    def passa(rotta):
        richiesta = rotta.request
        if "aggiungi" in richiesta.url:
            arrivate.append(richiesta.method)
            rotta.fulfill(status=200, content_type="application/json",
                          body='{"aggiunte": 0, "sbagliate": []}')
            return
        risposta = cliente.request(richiesta.method,
                                   richiesta.url.replace("http://prova", ""),
                                   content=richiesta.post_data_buffer,
                                   headers={k: v.replace("http://prova", "http://testserver")
                                            for k, v in richiesta.headers.items()
                                            if k != "host"})
        rotta.fulfill(status=risposta.status_code, body=risposta.content,
                      headers={k: v for k, v in risposta.headers.items()
                               if k.lower() not in ("content-length",
                                                    "content-encoding")})

    with sync_api.sync_playwright() as p:
        pronto = Path("/opt/pw-browsers/chromium")
        try:
            browser = p.chromium.launch(
                executable_path=str(pronto) if pronto.exists() else None)
        except sync_api.Error as guasto:
            pytest.skip(f"niente browser: {guasto}")
        pagina = browser.new_page(viewport={"width": 1440, "height": 900})
        pagina.on("pageerror", lambda e: errori.append(str(e)))
        pagina.route("http://prova/**", passa)
        pagina.goto("http://prova/stampa", wait_until="load")
        pagina.wait_for_timeout(300)
        assert not pagina.locator("#st-guarda").is_visible()
        assert not pagina.locator("#st-forma").is_visible()
        assert pagina.locator("#st-carica").is_visible()
        pagina.evaluate("""() => {
            const dati = new DataTransfer();
            dati.items.add(new File(["x"], "c.jpg", { type: "image/jpeg" }));
            const sopra = new DragEvent("dragover",
                { dataTransfer: dati, cancelable: true });
            window.dispatchEvent(sopra);
            const giu = new DragEvent("drop", { dataTransfer: dati, cancelable: true });
            window.dispatchEvent(giu);
            return [sopra.defaultPrevented, giu.defaultPrevented];
        }""") == [True, True] or pytest.fail("il trascinamento non e preso")
        pagina.wait_for_timeout(500)
        assert arrivate == ["POST"]
        for nome, misura in (("a.jpg", (300, 200)), ("b.jpg", (400, 300))):
            cliente.post("/api/stampa/aggiungi",
                         files=[("foto", (nome, _jpeg(*misura).getvalue(), "image/jpeg"))])
        pagina.reload(wait_until="load")
        pagina.locator("#st-elenco img").nth(1).wait_for(state="attached", timeout=10000)
        assert pagina.locator("#st-forma").is_visible()
        assert "1" in pagina.locator("#st-forma").inner_text()
        stampa_vera = strada.la_stampa(archivio)
        prima = stampa_vera.come_va()["foto"][0]
        fatta = stampa_vera.file_di(prima, "seedvr2")
        fatta.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", tuple(prima["arrivo"]), (0, 90, 200)).save(fatta)
        stampa_vera._segna_le_fatte()
        pagina.reload(wait_until="load")
        pagina.locator("#st-elenco img").first.wait_for(state="attached", timeout=10000)
        pagina.locator("#st-elenco img").first.click()
        assert pagina.locator("#st-guarda").is_visible()
        pagina.locator(".st-vetro img").nth(1).wait_for(state="attached", timeout=10000)
        pagina.wait_for_timeout(800)
        larghe = [round(img.bounding_box()["width"])
                  for img in pagina.locator(".st-vetro img").all()]
        assert len(larghe) == 2 and abs(larghe[0] - larghe[1]) <= 1, larghe
        vetro = pagina.locator(".st-vetro").first.bounding_box()
        pagina.mouse.move(vetro["x"] + 40, vetro["y"] + 40)
        pagina.mouse.wheel(0, -300)
        pagina.wait_for_timeout(300)
        dopo = [img.bounding_box() for img in pagina.locator(".st-vetro img").all()]
        assert abs(dopo[0]["width"] - dopo[1]["width"]) <= 1
        assert dopo[0]["width"] > larghe[0]
        pagina.click("#st-nessuna")
        pagina.wait_for_timeout(300)
        pagina.click("#st-chiudi")
        assert not pagina.locator("#st-guarda").is_visible()
        browser.close()
    strada.la_stampa(archivio).ferma()
    assert errori == []


def test_foto_aggiunte_mentre_lavora(tmp_path, monkeypatch):
    fatta, sosta = _stampa(tmp_path, monkeypatch)
    prima = fatta.aggiungi("a.jpg", _jpeg(300, 200))
    giri = []
    vero = fatta._lancia

    def lancia(lavoro, al_passo):
        giri.append([uno["id"] for uno in lavoro["foto"]])
        if len(giri) == 1:
            fatta.aggiungi("b.jpg", _jpeg(200, 300))
        return vero(lavoro, al_passo)

    fatta._lancia = lancia
    fatta._gira()
    assert len(giri) == 2 and giri[0] == [prima["id"]] and len(giri[1]) == 1
    assert all(uno["fatte"] == ["seedvr2", "volti"] for uno in fatta.come_va()["foto"])


def test_foto_che_non_viene_non_gira_per_sempre(tmp_path, monkeypatch):
    fatta, sosta = _stampa(tmp_path, monkeypatch)
    fatta.aggiungi("a.jpg", _jpeg(300, 200))
    giri = []

    def lancia(lavoro, al_passo):
        giri.append(1)
        return {"fatto": 0}

    fatta._lancia = lancia
    fatta._gira()
    assert len(giri) == 1
    assert fatta.come_va()["foto"][0]["fatte"] == []
