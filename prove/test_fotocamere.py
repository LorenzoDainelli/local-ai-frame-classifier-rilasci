from __future__ import annotations

from pathlib import Path

from PIL import Image

from officina import ricerca
from officina.importazione import metadati, rileggi_macchine
from officina.modello import fotocamere, scatti
from officina.web import vista

IPHONE = ("Apple", "iPhone 13 Pro", "iPhone 13 Pro back triple camera 5.7mm f/1.5")
CANON = ("Canon", "Canon EOS 80D", "EF-S18-135mm f/3.5-5.6 IS USM")


def _foto(dove: Path, marca=None, modello=None, obiettivo=None, colore=(40, 120, 200)):
    dove.parent.mkdir(parents=True, exist_ok=True)
    exif = Image.Exif()
    if marca:
        exif[0x010F] = marca
    if modello:
        exif[0x0110] = modello
    if obiettivo:
        exif.get_ifd(0x8769)[0xA434] = obiettivo
    Image.new("RGB", (64, 48), colore).save(dove, exif=exif)


def _importa(archivio, cartella: Path) -> None:
    from officina.importazione.motore import Motore

    motore = Motore(archivio)
    motore.prepara([cartella])
    motore.esegui()


def _tre_foto(archivio, tmp_path) -> dict[str, int]:
    _foto(tmp_path / "foto" / "telefono.jpg", *IPHONE, colore=(200, 30, 30))
    _foto(tmp_path / "foto" / "reflex.jpg", *CANON, colore=(30, 200, 30))
    _foto(tmp_path / "foto" / "nessuna.jpg", colore=(30, 30, 200))
    _importa(archivio, tmp_path / "foto")
    with archivio.lettura() as connessione:
        return {Path(r["percorso"]).name: r["scatto_id"] for r in connessione.execute(
            "SELECT p.percorso, f.scatto_id FROM file_media f "
            "JOIN percorsi p ON p.file_id = f.id")}


def _ids(archivio) -> dict[str, tuple]:
    with archivio.lettura() as connessione:
        return {Path(r["percorso"]).name: (r["obiettivo"], r["fotocamera_id"],
                                           r["obiettivo_id"])
                for r in connessione.execute(
                    "SELECT p.percorso, f.obiettivo, f.fotocamera_id, f.obiettivo_id "
                    "FROM file_media f JOIN percorsi p ON p.file_id = f.id")}


def test_l_obiettivo_si_legge_dai_dati_della_foto(tmp_path):
    _foto(tmp_path / "a.jpg", *IPHONE)
    dati = metadati.leggi(tmp_path / "a.jpg")
    assert (dati.marca, dati.modello, dati.obiettivo) == IPHONE
    _foto(tmp_path / "b.jpg")
    assert metadati.leggi(tmp_path / "b.jpg").obiettivo is None


def test_all_importazione_macchina_e_obiettivo_si_salvano(archivio, tmp_path):
    _tre_foto(archivio, tmp_path)
    salvati = _ids(archivio)
    assert salvati["telefono.jpg"][0] == IPHONE[2]
    assert salvati["telefono.jpg"][1] and salvati["telefono.jpg"][2]
    assert salvati["reflex.jpg"][1] != salvati["telefono.jpg"][1]
    assert salvati["nessuna.jpg"] == (None, None, None)
    with archivio.lettura() as connessione:
        nomi = {v["nome"] for v in fotocamere.fotocamere(connessione)}
        lenti = {v["nome"] for v in fotocamere.obiettivi(connessione)}
    assert nomi == {"Apple iPhone 13 Pro", "Canon EOS 80D"}
    assert lenti == {IPHONE[2], CANON[2]}


def test_la_stessa_macchina_scritta_diversa_e_una_sola(archivio):
    with archivio.scrittura() as connessione:
        uno = fotocamere.id_della_fotocamera(connessione, "Apple", "iPhone 13")
        due = fotocamere.id_della_fotocamera(connessione, " APPLE\x00", "iphone  13 ")
        assert uno == due
        assert fotocamere.id_della_fotocamera(connessione, None, "  ") is None
        assert fotocamere.id_dell_obiettivo(connessione, "") is None


def test_il_filtro_tiene_solo_quella_macchina_e_quell_obiettivo(archivio, tmp_path):
    numeri = _tre_foto(archivio, tmp_path)
    salvati = _ids(archivio)
    with archivio.lettura() as connessione:
        con_la_reflex = scatti.soli_numeri(
            connessione, scatti.Filtro(fotocamera=salvati["reflex.jpg"][1]))
        con_quella_lente = scatti.soli_numeri(
            connessione, scatti.Filtro(obiettivo=salvati["telefono.jpg"][2]))
        conti = scatti.conteggi_delle_fotocamere(connessione, scatti.Filtro())
    assert con_la_reflex == [numeri["reflex.jpg"]]
    assert con_quella_lente == [numeri["telefono.jpg"]]
    assert conti["fotocamere"] == {salvati["reflex.jpg"][1]: 1,
                                   salvati["telefono.jpg"][1]: 1}


def test_il_filtro_passa_per_l_indirizzo_e_ha_la_sua_pillola(archivio, tmp_path):
    _tre_foto(archivio, tmp_path)
    salvati = _ids(archivio)
    filtro = scatti.Filtro(fotocamera=salvati["reflex.jpg"][1],
                           obiettivo=salvati["reflex.jpg"][2])
    indirizzo = vista.indirizzo(filtro)
    ritrovato = vista.filtro_da_parametri(dict(
        pezzo.split("=") for pezzo in indirizzo.split("?", 1)[1].split("&")))
    assert ritrovato.fotocamera == filtro.fotocamera
    assert ritrovato.obiettivo == filtro.obiettivo
    assert not filtro.e_vuoto()
    with archivio.lettura() as connessione:
        testi = [p["testo"] for p in vista.pillole_attive(connessione, filtro)]
    assert "con Canon EOS 80D" in testi
    assert f"obiettivo {CANON[2]}" in testi


def test_si_cerca_a_parole_col_nome_della_macchina(archivio, tmp_path):
    numeri = _tre_foto(archivio, tmp_path)
    with archivio.lettura() as connessione:
        trovate = ricerca.cerca(connessione, tmp_path / "modelli", "iPhone 13 Pro")
        reflex = ricerca.cerca(connessione, tmp_path / "modelli", "canon eos 80d")
    assert [t.scatto_id for t in trovate.trovati] == [numeri["telefono.jpg"]]
    assert [t.scatto_id for t in reflex.trovati] == [numeri["reflex.jpg"]]


def test_le_foto_gia_dentro_si_rileggono_anche_per_l_obiettivo(archivio, tmp_path):
    _tre_foto(archivio, tmp_path)
    with archivio.scrittura() as connessione:
        connessione.execute("UPDATE file_media SET obiettivo = NULL, fotocamera_id = NULL, "
                            "obiettivo_id = NULL")
        massimo = connessione.execute("SELECT max(id) FROM file_media").fetchone()[0]
    archivio.salva_stato(rileggi_macchine.FINO_A, massimo)
    assert rileggi_macchine.tutti_i_file(archivio) == 2
    salvati = _ids(archivio)
    assert salvati["telefono.jpg"][0] == IPHONE[2] and salvati["telefono.jpg"][2]
    assert salvati["reflex.jpg"][1] and salvati["nessuna.jpg"] == (None, None, None)


def test_la_galleria_mostra_le_tendine_della_macchina(archivio, tmp_path, monkeypatch):
    from starlette.testclient import TestClient

    from officina.archivio import accesso
    from officina.web.server import app

    _tre_foto(archivio, tmp_path)
    monkeypatch.setattr(accesso, "aperto", lambda: archivio)
    cliente = TestClient(app, client=("127.0.0.1", 51000))
    pagina = cliente.get("/").text
    assert 'data-gruppo="fotocamere"' in pagina and 'data-gruppo="obiettivi"' in pagina
    assert "Canon EOS 80D" in pagina
    numeri = cliente.get("/api/conteggi").json()
    assert sum(numeri["fotocamere"].values()) == 2
