import io
import os
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
                          turno=TurnoFinto(), pronta=lambda: True, sosta=sosta)
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
    assert foto[piccola["id"]]["fatte"] == ["seedvr2", "grana"]
    assert foto[piccola["id"]]["controllo"] == {"non_fatto": "mancano i modelli dei volti"}
    assert foto[grande["id"]]["fatte"] == []
    with Image.open(fatta.file_di(foto[piccola["id"]], "seedvr2")) as fatto:
        assert fatto.size == (4096, 2731)
    with pytest.raises(Exception):
        fatta.scegli(piccola["id"], "volti")
    fatta.scegli(piccola["id"], "seedvr2")
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
    assert fatta.vista(piccola["id"], "seedvr2").is_file()
    assert fatta.vista(piccola["id"], "volti") is None
    assert not (fatta.cartella / "volti").exists()
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
    assert all(uno["fatte"] == ["seedvr2", "grana"] for uno in fatta.come_va()["foto"])


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


def test_lo_zip_dice_dove_va(archivio, monkeypatch):
    sync_api = pytest.importorskip("playwright.sync_api")
    from fastapi.testclient import TestClient

    from officina.web.server import app
    from officina.web.strade import stampa as strada

    monkeypatch.setattr(strada, "_stampa", None)
    cliente = TestClient(app, client=("127.0.0.1", 51000))
    html = cliente.get("/stampa").text
    with sync_api.sync_playwright() as p:
        pronto = Path("/opt/pw-browsers/chromium")
        try:
            browser = p.chromium.launch(
                executable_path=str(pronto) if pronto.exists() else None)
        except sync_api.Error as guasto:
            pytest.skip(f"niente browser: {guasto}")
        pagina = browser.new_page()
        pagina.route("**/*", lambda rotta: rotta.fulfill(
            status=200, content_type="application/json", body="{}"))
        pagina.set_content(html)
        assert pagina.locator("#st-zip").is_hidden()
        nel_programma = pagina.evaluate("dove_va_lo_zip(3, true)")
        nel_browser = pagina.evaluate("dove_va_lo_zip(1, false)")
        browser.close()
    assert "foto-da-stampare.zip con 3 foto" in nel_programma
    assert "«Salva con nome»" in nel_programma and "Download" in nel_programma
    assert "con 1 foto" in nel_browser and "cartella Download" in nel_browser
    assert "portatile" in nel_browser
    strada.la_stampa(archivio).ferma()


def test_la_finestra_permette_gli_scaricamenti():
    from types import SimpleNamespace

    from officina.programma import avvio

    finta = SimpleNamespace(settings={"ALLOW_DOWNLOADS": False})
    avvio.permetti_gli_scaricamenti(finta)
    assert finta.settings["ALLOW_DOWNLOADS"] is True
    avvio.permetti_gli_scaricamenti(SimpleNamespace())


def _uno_zip(cartella: Path, quanti: int = 3) -> bytes:
    fuori = io.BytesIO()
    with zipfile.ZipFile(fuori, "w", zipfile.ZIP_STORED) as dentro:
        for numero in range(quanti):
            dentro.writestr(f"foto-{numero}.jpg", os.urandom(300_000 + numero))
    return fuori.getvalue()


def test_lo_zip_si_salva_dal_programma_a_pezzi(archivio, monkeypatch, tmp_path):
    import json

    sync_api = pytest.importorskip("playwright.sync_api")
    from fastapi.testclient import TestClient

    from officina.programma.salvataggi import Salvataggi
    from officina.web.server import app
    from officina.web.strade import stampa as strada

    monkeypatch.setattr(strada, "_stampa", None)
    cliente = TestClient(app, client=("127.0.0.1", 51000))
    html = cliente.get("/stampa").text
    zip_vero = _uno_zip(tmp_path, 20)
    salvataggi = Salvataggi(lambda nome: str(tmp_path / "scelto" / nome))
    (tmp_path / "scelto").mkdir()
    stato = {"foto": [], "approvate": 3, "righe": [], "sta_lavorando": False}

    def rispondi(rotta):
        indirizzo = rotta.request.url
        if indirizzo.endswith("/api/stampa/scarica"):
            rotta.fulfill(status=200, content_type="application/zip", body=zip_vero)
        elif indirizzo.endswith("/api/stampa"):
            rotta.fulfill(status=200, content_type="application/json",
                          body=json.dumps(stato))
        elif indirizzo.endswith("/stampa"):
            rotta.fulfill(status=200, content_type="text/html", body=html)
        else:
            rotta.fulfill(status=200, content_type="application/json", body="{}")

    with sync_api.sync_playwright() as p:
        pronto = Path("/opt/pw-browsers/chromium")
        try:
            browser = p.chromium.launch(
                executable_path=str(pronto) if pronto.exists() else None)
        except sync_api.Error as guasto:
            pytest.skip(f"niente browser: {guasto}")
        pagina = browser.new_page(base_url="http://127.0.0.1:51000")
        pagina.route("**/*", rispondi)
        pagina.expose_function("py_apri", lambda nome: salvataggi.apri(nome))
        pagina.expose_function("py_pezzo", lambda chi, testo: salvataggi.pezzo(chi, testo))
        pagina.expose_function("py_fine", lambda chi, quanti: salvataggi.chiudi(chi, quanti))
        pagina.expose_function("py_lascia", lambda chi: salvataggi.lascia(chi))
        pagina.add_init_script("""
            window.pezzi = 0;
            window.pywebview = {api: {
                salva_apri: (n) => window.py_apri(n),
                salva_pezzo: (c, t) => { window.pezzi += 1; return window.py_pezzo(c, t); },
                salva_fine: (c, q) => window.py_fine(c, q),
                salva_lascia: (c) => window.py_lascia(c)}};
        """)
        pagina.goto("/stampa")
        pagina.wait_for_function(
            "document.getElementById('st-approvate').textContent === '3'")
        pagina.click("#st-scarica")
        pagina.wait_for_function(
            "document.getElementById('st-zip').textContent.startsWith('Fatto')",
            timeout=20000)
        detto = pagina.locator("#st-zip").text_content()
        pezzi = pagina.evaluate("window.pezzi")
        assert pagina.url.endswith("/stampa")
        browser.close()
    salvato = tmp_path / "scelto" / "foto-da-stampare.zip"
    assert salvato.read_bytes() == zip_vero
    assert not list((tmp_path / "scelto").glob("*.officina-parziale"))
    assert pezzi >= 1 and "3 foto salvate" in detto and "si apra bene" in detto
    strada.la_stampa(archivio).ferma()


def test_salvataggi_annullato_e_niente_resta(tmp_path):
    from officina.programma.salvataggi import Salvataggi

    assert Salvataggi(lambda _nome: None).apri("a.zip") == {"annullato": True}


def test_salvataggi_misura_sbagliata_non_lascia_niente(tmp_path):
    import base64

    from officina.errori import ErroreOfficina
    from officina.programma.salvataggi import Salvataggi

    salvataggi = Salvataggi(lambda nome: str(tmp_path / nome))
    zip_vero = _uno_zip(tmp_path, 1)
    aperto = salvataggi.apri("a.zip")
    salvataggi.pezzo(aperto["chi"], base64.b64encode(zip_vero[:1000]).decode())
    with pytest.raises(ErroreOfficina):
        salvataggi.chiudi(aperto["chi"], len(zip_vero))
    assert list(tmp_path.iterdir()) == []


def test_salvataggi_zip_rotto_non_si_salva(tmp_path):
    import base64

    from officina.errori import ErroreOfficina
    from officina.programma.salvataggi import Salvataggi

    salvataggi = Salvataggi(lambda nome: str(tmp_path / nome))
    rotto = bytearray(_uno_zip(tmp_path, 2))
    rotto[200] ^= 0xFF
    aperto = salvataggi.apri("a.zip")
    salvataggi.pezzo(aperto["chi"], base64.b64encode(bytes(rotto)).decode())
    with pytest.raises(ErroreOfficina):
        salvataggi.chiudi(aperto["chi"], len(rotto))
    assert list(tmp_path.iterdir()) == []


def test_salvataggi_lascia_toglie_il_parziale(tmp_path):
    import base64

    from officina.programma.salvataggi import Salvataggi

    salvataggi = Salvataggi(lambda nome: str(tmp_path / nome))
    aperto = salvataggi.apri("a.zip")
    salvataggi.pezzo(aperto["chi"], base64.b64encode(b"abc").decode())
    salvataggi.lascia(aperto["chi"])
    assert list(tmp_path.iterdir()) == []


def test_salvataggi_aggiunge_l_estensione(tmp_path):
    import base64

    from officina.programma.salvataggi import Salvataggi

    zip_vero = _uno_zip(tmp_path, 1)
    salvataggi = Salvataggi(lambda _nome: str(tmp_path / "mie"))
    aperto = salvataggi.apri("foto-da-stampare.zip")
    salvataggi.pezzo(aperto["chi"], base64.b64encode(zip_vero).decode())
    fatto = salvataggi.chiudi(aperto["chi"], len(zip_vero))
    assert Path(fatto["dove"]).name == "mie.zip"
    assert (tmp_path / "mie.zip").read_bytes() == zip_vero


def test_il_ponte_ha_il_salvataggio():
    from officina.programma.ponti import PontePrincipale

    for nome in ("salva_apri", "salva_pezzo", "salva_fine", "salva_lascia"):
        assert callable(getattr(PontePrincipale, nome))


def test_la_versione_dei_volti_di_prima_non_si_sceglie_piu(tmp_path, monkeypatch):
    fatta, _sosta = _stampa(tmp_path, monkeypatch)
    uno = fatta.aggiungi("a.jpg", _jpeg(300, 200))
    fatta._gira()
    vecchio = fatta.file_di(uno, "volti")
    vecchio.parent.mkdir(parents=True, exist_ok=True)
    vecchio.write_bytes(b"x")
    stato = fatta._stato()
    stato["foto"][0]["fatte"] = ["seedvr2", "volti"]
    stato["foto"][0]["scelta"] = "volti"
    fatta._salva(stato)
    [letta] = fatta.come_va()["foto"]
    assert letta["fatte"] == ["seedvr2"] and letta["scelta"] is None
    assert fatta.zip(tmp_path / "z.zip") == 0
    fatta.togli(uno["id"])
    assert not vecchio.exists()


def test_la_grana_si_sceglie_e_va_nello_zip(tmp_path, monkeypatch):
    import numpy as np

    from officina.miglioria.pelle_stanza import rimetti_la_grana

    fatta, _sosta = _stampa(tmp_path, monkeypatch)
    sorgente = io.BytesIO()
    casuale = np.random.default_rng(3).integers(0, 255, (200, 300, 3), dtype=np.uint8)
    Image.fromarray(casuale).save(sorgente, "PNG")
    sorgente.seek(0)
    uno = fatta.aggiungi("rumore.png", sorgente)
    fatta._gira()
    with Image.open(fatta.file_di(uno, "seedvr2")) as a, \
            Image.open(fatta.file_di(uno, "grana")) as b:
        liscia, granosa = np.asarray(a.convert("RGB")), np.asarray(b.convert("RGB"))
    assert granosa.shape == liscia.shape
    assert np.array_equal(granosa, rimetti_la_grana(casuale, liscia))
    fatta.scegli(uno["id"], "grana")
    assert fatta.zip(tmp_path / "z.zip") == 1
    assert fatta.vista(uno["id"], "grana").is_file()
    fatta.togli(uno["id"])
    assert not fatta.controllo_di(uno).exists()


def test_se_seedvr2_c_e_gia_fa_solo_grana_e_controllo(tmp_path, monkeypatch):
    fatta, _sosta = _stampa(tmp_path, monkeypatch)
    uno = fatta.aggiungi("a.jpg", _jpeg(300, 200))
    fatta._gira()
    fatta.file_di(uno, "grana").unlink()
    fatta.controllo_di(uno).unlink()

    def nessun_motore(*_a, **_k):
        raise AssertionError("SeedVR2 non doveva ripartire")

    monkeypatch.setattr(motori, "apri", nessun_motore)
    fatta._gira()
    [letta] = fatta.come_va()["foto"]
    assert letta["fatte"] == ["seedvr2", "grana"] and letta["controllo"]


def test_se_il_controllo_si_rompe_lo_dice(tmp_path, monkeypatch):
    fatta, _sosta = _stampa(tmp_path, monkeypatch)
    uno = fatta.aggiungi("a.jpg", _jpeg(300, 200))
    monkeypatch.setattr(stampa_stanza, "il_rilevatore", lambda cartella: object())
    fatta._gira()
    assert fatta.come_va()["foto"][0]["controllo"] == {
        "non_fatto": "il controllo dei volti si è rotto"}
    assert fatta.file_di(uno, "grana").is_file()


def test_la_pagina_dice_se_un_volto_e_cambiato(archivio, monkeypatch):
    import json

    sync_api = pytest.importorskip("playwright.sync_api")
    from fastapi.testclient import TestClient

    from officina.web.server import app
    from officina.web.strade import stampa as strada

    monkeypatch.setattr(strada, "_stampa", None)
    html = TestClient(app, client=("127.0.0.1", 51000)).get("/stampa").text
    controllo = {"seedvr2": {"controllati": 2, "cambiati": 0, "piccoli": 1,
                             "persona": 0.9, "spostati": 0.02},
                 "grana": {"controllati": 2, "cambiati": 1, "piccoli": 1,
                           "persona": 0.3, "spostati": 0.02}}
    stato = {"foto": [{"id": 1, "nome": "a.jpg", "file": "1-a.jpg", "larghezza": 300,
                       "altezza": 200, "arrivo": [600, 400], "due_terzi": True,
                       "fatte": ["seedvr2", "grana"], "scelta": None,
                       "controllo": controllo}],
             "approvate": 0, "righe": [], "sta_lavorando": False}
    immagine = _jpeg(300, 200).getvalue()

    def rispondi(rotta):
        if rotta.request.url.endswith(".jpg"):
            rotta.fulfill(status=200, content_type="image/jpeg", body=immagine)
        else:
            rotta.fulfill(status=200, content_type="application/json",
                          body=json.dumps(stato))

    with sync_api.sync_playwright() as p:
        pronto = Path("/opt/pw-browsers/chromium")
        try:
            browser = p.chromium.launch(
                executable_path=str(pronto) if pronto.exists() else None)
        except sync_api.Error as guasto:
            pytest.skip(f"niente browser: {guasto}")
        pagina = browser.new_page()
        pagina.route("**/*", rispondi)
        pagina.goto("http://127.0.0.1:9/stampa")
        pagina.set_content(html)
        pagina.locator("#st-elenco img").first.wait_for(state="attached", timeout=10000)
        tessera = pagina.locator(".st-tessera").first.inner_text()
        pagina.locator("#st-elenco img").first.click()
        pagina.locator(".st-pannello").nth(2).wait_for(state="attached", timeout=10000)
        pannelli = [p.inner_text() for p in pagina.locator(".st-pannello").all()]
        browser.close()
    strada.la_stampa(archivio).ferma()
    assert "volto cambiato in SeedVR2 + grana" in tessera
    assert "2 volti uguali all'originale" in pannelli[1]
    assert "1 volto troppo piccolo" in pannelli[1]
    assert "1 volto cambiato: guarda" in pannelli[2]
    assert "SeedVR2 + grana" in pannelli[2]
