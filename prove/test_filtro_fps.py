from __future__ import annotations

import html
import importlib.util
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from officina import registro
from officina.archivio import migrazioni
from officina.archivio.database import leggi_stato, scrivi_stato, uno
from officina.finto import contenitore_video
from officina.immagini import fotogrammi
from officina.importazione import metadati, rileggi_fps, ripasso
from officina.importazione.motore import Motore
from officina.modello import scatti
from officina.modello.scatti import Filtro
from officina.sicuro.dall_archivio import CHIUSO_ADESSO, da_rifare
from officina.web import conteggi, vista
from officina.web.strade import comune, importazione
from prove.test_video_girati import ALTA, LARGA, _quadri

CON_AV = pytest.mark.skipif(importlib.util.find_spec("av") is None, reason="manca av")
RITMI = {"otto.mov": 8, "trenta.mov": 30, "sessanta.mov": 60, "centoventi.mov": 120}


def _video(dove: Path, al_secondo: int) -> Path:
    dove.parent.mkdir(parents=True, exist_ok=True)
    contenitore_video.scrivi(dove, _quadri(), LARGA, ALTA, al_secondo,
                             f"FPS-{dove.stem}", datetime(2024, 5, 1, 10, 0, 0))
    return dove


def _foto(dove: Path) -> Path:
    dove.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (64, 48), (40, 120, 200)).save(dove)
    return dove


def _importa(archivio, cartella: Path) -> None:
    motore = Motore(archivio)
    motore.prepara([cartella])
    motore.esegui()


def _per_nome(archivio) -> dict:
    with archivio.lettura() as connessione:
        return {Path(riga["percorso"]).name: dict(riga) for riga in connessione.execute(
            "SELECT p.percorso, f.id, f.fps, f.genere, f.scatto_id FROM file_media f "
            "JOIN percorsi p ON p.file_id = f.id")}


@pytest.fixture
def cartella(tmp_path) -> Path:
    dove = tmp_path / "video"
    for nome, al_secondo in RITMI.items():
        _video(dove / nome, al_secondo)
    _foto(dove / "foto.png")
    return dove


@pytest.fixture
def importato(archivio, cartella):
    _importa(archivio, cartella)
    return archivio


def _sentiti(monkeypatch) -> list:
    visti: list = []
    monkeypatch.setattr(registro, "evento",
                        lambda nome, **campi: visti.append((nome, campi)))
    return visti


def _senza_fps(archivio) -> int:
    with archivio.scrittura() as connessione:
        connessione.execute("UPDATE file_media SET fps = NULL")
        return connessione.execute("SELECT max(id) FROM file_media").fetchone()[0]


@CON_AV
def test_gli_fps_si_leggono_da_ogni_video(cartella):
    for nome, al_secondo in RITMI.items():
        assert fotogrammi.fps_dal_decodificatore(cartella / nome) == float(al_secondo)
        assert metadati.da_video(cartella / nome).fps == float(al_secondo)
    rotto = cartella / "rotto.mov"
    rotto.write_bytes(b"non sono un video" * 20)
    assert fotogrammi.fps_dal_decodificatore(rotto) is None
    assert fotogrammi.fps_dal_decodificatore(cartella / "manca.mov") is None


def test_senza_decodificatore_gli_fps_non_si_sanno(monkeypatch, tmp_path):
    monkeypatch.setattr(fotogrammi, "c_e_il_decodificatore", lambda: False)
    monkeypatch.setattr(fotogrammi, "_av", lambda: pytest.fail("non si apre"))
    assert fotogrammi.fps_dal_decodificatore(tmp_path / "x.mov") is None


class _Contenitore:

    def __init__(self, tracce: list):
        self.streams = tracce
        self.duration = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


def _av_finto(monkeypatch, tracce: list, aperti: list) -> None:
    def apri(sorgente):
        aperti.append(sorgente)
        return _Contenitore(tracce)

    monkeypatch.setattr(fotogrammi, "c_e_il_decodificatore", lambda: True)
    monkeypatch.setattr(fotogrammi, "_av", lambda: SimpleNamespace(open=apri))


def _traccia(tipo: str, media, indovinata=None, quanti: int = 10) -> SimpleNamespace:
    return SimpleNamespace(type=tipo, average_rate=media, guessed_rate=indovinata,
                           frames=quanti, duration=None, time_base=None)


@pytest.mark.parametrize("media, indovinata, atteso", [
    (30000 / 1001, None, 29.97), (0, 25.0, 25.0), (None, 60.0, 60.0),
    (1000.0, None, 1000.0), (1000.5, None, None), (0, 0, None), (None, None, None),
    (-30.0, None, None), (float("nan"), None, None), (float("inf"), None, None),
    (0.25, None, 0.25), (59.9405, None, 59.941)])
def test_gli_fps_strani_non_si_scrivono(monkeypatch, tmp_path, media, indovinata, atteso):
    aperti: list = []
    tracce = [_traccia("audio", 44100.0), _traccia("video", media, indovinata)]
    _av_finto(monkeypatch, tracce, aperti)
    assert fotogrammi.fps_dal_decodificatore(tmp_path / "v.mov") == atteso
    assert aperti == [str(tmp_path / "v.mov")]


def test_senza_traccia_video_gli_fps_non_si_sanno(monkeypatch, tmp_path):
    aperti: list = []
    _av_finto(monkeypatch, [_traccia("audio", 44100.0)], aperti)
    assert fotogrammi.fps_dal_decodificatore(tmp_path / "v.m4a") is None
    assert len(aperti) == 1


def test_dall_archivio_gli_fps_si_leggono_dal_suo_lettore(monkeypatch):
    aperti: list = []
    _av_finto(monkeypatch, [_traccia("video", 24.0)], aperti)
    dati = object()

    @contextmanager
    def per_av(percorso):
        assert percorso == "nell'archivio"
        yield dati

    monkeypatch.setattr(fotogrammi, "per_av", per_av)
    assert fotogrammi.fps_dal_decodificatore("nell'archivio") == 24.0
    assert aperti == [dati]


@CON_AV
def test_all_importazione_gli_fps_si_salvano(importato):
    file = _per_nome(importato)
    assert {nome: file[nome]["fps"] for nome in RITMI} == {
        nome: float(al_secondo) for nome, al_secondo in RITMI.items()}
    assert file["foto.png"]["fps"] is None
    assert importato.stato(rileggi_fps.FINO_A) is None


def _a_versione_69() -> sqlite3.Connection:
    connessione = sqlite3.connect(":memory:")
    connessione.row_factory = sqlite3.Row
    connessione.execute("CREATE TABLE file_media (id INTEGER PRIMARY KEY, genere TEXT)")
    connessione.execute("CREATE TABLE stato (chiave TEXT PRIMARY KEY, valore TEXT, "
                        "aggiornato_il TEXT)")
    return connessione


def test_la_migrazione_mette_in_fila_solo_i_video():
    assert migrazioni.MIGRAZIONI[-1].versione == 70
    assert migrazioni.MIGRAZIONI[-1].applica is migrazioni._versione_70
    connessione = _a_versione_69()
    connessione.executemany("INSERT INTO file_media (id, genere) VALUES (?, ?)",
                            [(3, "video"), (7, "video"), (9, "immagine")])
    migrazioni._versione_70(connessione)
    assert leggi_stato(connessione, rileggi_fps.FINO_A) == 7
    riga = uno(connessione, "SELECT aggiornato_il FROM stato WHERE chiave = ?",
               rileggi_fps.FINO_A)
    assert riga["aggiornato_il"].endswith("Z") and len(riga["aggiornato_il"]) == 20
    valori = [r["fps"] for r in connessione.execute("SELECT fps FROM file_media")]
    assert valori == [None] * 3


def test_la_migrazione_senza_video_non_mette_in_fila_niente():
    connessione = _a_versione_69()
    connessione.execute("INSERT INTO file_media (id, genere) VALUES (4, 'immagine')")
    migrazioni._versione_70(connessione)
    assert connessione.execute("SELECT count(*) FROM stato").fetchone()[0] == 0
    vuota = _a_versione_69()
    migrazioni._versione_70(vuota)
    assert vuota.execute("SELECT count(*) FROM stato").fetchone()[0] == 0


@CON_AV
def test_gli_fps_dei_video_gia_in_archivio_si_rileggono(importato, monkeypatch):
    eventi = _sentiti(monkeypatch)
    massimo = _senza_fps(importato)
    importato.salva_stato(rileggi_fps.FINO_A, massimo)
    assert rileggi_fps.quanti_restano(importato) == len(RITMI)

    assert rileggi_fps.tutti_i_file(importato) == len(RITMI)

    file = _per_nome(importato)
    assert {nome: file[nome]["fps"] for nome in RITMI} == {
        nome: float(al_secondo) for nome, al_secondo in RITMI.items()}
    assert file["foto.png"]["fps"] is None
    for chiave in (rileggi_fps.FINO_A, rileggi_fps.DA, rileggi_fps.RIMANDATI):
        assert importato.stato(chiave) is None
    assert rileggi_fps.quanti_restano(importato) == 0
    assert [e for e in eventi if e[0].startswith("rileggi_fps")] == [
        ("rileggi_fps.finito", {"quanti": len(RITMI)})]
    assert rileggi_fps.tutti_i_file(importato) == 0


def _video_in_fila(archivio) -> list[int]:
    with archivio.lettura() as connessione:
        return [riga["id"] for riga in connessione.execute(
            "SELECT id FROM file_media WHERE genere = 'video' ORDER BY id")]


@CON_AV
def test_si_rileggono_solo_i_video_senza_fps_fino_al_segno(importato, monkeypatch):
    primo, secondo, terzo, quarto = _video_in_fila(importato)
    _senza_fps(importato)
    with importato.scrittura() as connessione:
        connessione.execute("UPDATE file_media SET fps = 77.0 WHERE id = ?", (secondo,))
    letti: list = []
    vero = fotogrammi.fps_dal_decodificatore
    monkeypatch.setattr(fotogrammi, "fps_dal_decodificatore",
                        lambda percorso: letti.append(percorso) or vero(percorso))
    importato.salva_stato(rileggi_fps.DA, primo)
    importato.salva_stato(rileggi_fps.FINO_A, terzo)
    assert rileggi_fps.quanti_restano(importato) == 1
    assert rileggi_fps.tutti_i_file(importato) == 1
    assert len(letti) == 1
    with importato.lettura() as connessione:
        fps = {riga["id"]: riga["fps"] for riga in connessione.execute(
            "SELECT id, fps FROM file_media WHERE genere = 'video'")}
    assert fps[primo] is None and fps[secondo] == 77.0 and fps[quarto] is None
    assert fps[terzo] in {float(al_secondo) for al_secondo in RITMI.values()}
    assert rileggi_fps.uno(importato, secondo)
    with importato.lettura() as connessione:
        assert uno(connessione, "SELECT fps FROM file_media WHERE id = ?",
                   secondo)["fps"] == 77.0


@CON_AV
def test_un_video_sparito_o_illeggibile_non_ferma_la_lettura(importato, cartella,
                                                            monkeypatch):
    eventi = _sentiti(monkeypatch)
    massimo = _senza_fps(importato)
    (cartella / "trenta.mov").unlink()
    vero = fotogrammi.fps_dal_decodificatore
    monkeypatch.setattr(fotogrammi, "fps_dal_decodificatore",
                        lambda p: None if Path(p).name == "otto.mov" else vero(p))
    importato.salva_stato(rileggi_fps.FINO_A, massimo)
    assert rileggi_fps.tutti_i_file(importato) == 2
    file = _per_nome(importato)
    assert file["otto.mov"]["fps"] is None and file["trenta.mov"]["fps"] is None
    assert (file["sessanta.mov"]["fps"], file["centoventi.mov"]["fps"]) == (60.0, 120.0)
    assert importato.stato(rileggi_fps.FINO_A) is None
    assert ("rileggi_fps.finito", {"quanti": 2}) in eventi


@CON_AV
def test_basta_ferma_la_lettura_e_la_lascia_in_fila(importato, monkeypatch):
    eventi = _sentiti(monkeypatch)
    massimo = _senza_fps(importato)
    importato.salva_stato(rileggi_fps.FINO_A, massimo)
    letti: list = []
    vero = fotogrammi.fps_dal_decodificatore
    monkeypatch.setattr(fotogrammi, "fps_dal_decodificatore",
                        lambda p: letti.append(p) or vero(p))
    assert rileggi_fps.tutti_i_file(importato, basta=lambda: len(letti) >= 1) == 1
    assert importato.stato(rileggi_fps.FINO_A) == massimo
    assert rileggi_fps.quanti_restano(importato) == len(RITMI) - 1
    assert not [e for e in eventi if e[0].startswith("rileggi_fps")]
    assert rileggi_fps.tutti_i_file(importato) == len(RITMI) - 1
    assert importato.stato(rileggi_fps.FINO_A) is None


@CON_AV
def test_i_rimandati_che_hanno_gia_gli_fps_non_si_rileggono(importato, monkeypatch):
    eventi = _sentiti(monkeypatch)
    primo, secondo, terzo, quarto = _video_in_fila(importato)
    with importato.scrittura() as connessione:
        connessione.execute("UPDATE file_media SET fps = NULL WHERE id = ?", (terzo,))
    letti: list = []
    vero = fotogrammi.fps_dal_decodificatore
    monkeypatch.setattr(fotogrammi, "fps_dal_decodificatore",
                        lambda percorso: letti.append(percorso) or vero(percorso))
    importato.salva_stato(rileggi_fps.FINO_A, quarto)
    importato.salva_stato(rileggi_fps.DA, quarto)
    foto = _per_nome(importato)["foto.png"]["id"]
    importato.salva_stato(rileggi_fps.RIMANDATI, [primo, terzo, foto])
    assert rileggi_fps.quanti_restano(importato) == 1
    assert rileggi_fps.tutti_i_file(importato) == 1
    assert len(letti) == 1 and importato.stato(rileggi_fps.RIMANDATI) is None
    assert ("rileggi_fps.finito", {"quanti": 1}) in eventi
    assert _per_nome(importato)["foto.png"]["fps"] is None


def test_con_l_archivio_chiuso_si_aspetta_e_si_dice(importato, monkeypatch):
    eventi = _sentiti(monkeypatch)
    massimo = _senza_fps(importato)
    importato.salva_stato(rileggi_fps.FINO_A, massimo)

    def chiuso(archivio, file_id):
        raise da_rifare(CHIUSO_ADESSO)

    monkeypatch.setattr(rileggi_fps, "uno", chiuso)
    assert rileggi_fps.tutti_i_file(importato) == 0
    assert len(importato.stato(rileggi_fps.RIMANDATI)) == len(RITMI)
    assert importato.stato(rileggi_fps.FINO_A) == massimo
    assert [e for e in eventi if e[0].startswith("rileggi_fps")] == [
        ("rileggi_fps.rimandati", {"quanti": len(RITMI)})]


def test_il_segno_si_alza_e_non_si_abbassa(archivio):
    with archivio.scrittura() as connessione:
        rileggi_fps.da_leggere(connessione, 5)
        assert leggi_stato(connessione, rileggi_fps.FINO_A) == 5
        rileggi_fps.da_leggere(connessione, 3)
        assert leggi_stato(connessione, rileggi_fps.FINO_A) == 5
        rileggi_fps.da_leggere(connessione, 5)
        assert leggi_stato(connessione, rileggi_fps.FINO_A) == 5
        rileggi_fps.da_leggere(connessione, 9)
        assert leggi_stato(connessione, rileggi_fps.FINO_A) == 9
        for rotto in (True, "12", [1], None):
            scrivi_stato(connessione, rileggi_fps.FINO_A, rotto)
            rileggi_fps.da_leggere(connessione, 1)
            segno = leggi_stato(connessione, rileggi_fps.FINO_A)
            assert (segno, type(segno)) == (1, int)


@CON_AV
def test_un_video_arrivato_durante_la_lettura_si_legge_lo_stesso(importato, monkeypatch):
    eventi = _sentiti(monkeypatch)
    in_fila = _video_in_fila(importato)
    primo, ultimo = in_fila[0], in_fila[-1]
    nomi = {riga["id"]: nome for nome, riga in _per_nome(importato).items()}
    with importato.scrittura() as connessione:
        connessione.execute("UPDATE file_media SET fps = NULL WHERE id IN (?, ?)",
                            (primo, ultimo))
    importato.salva_stato(rileggi_fps.FINO_A, primo)
    vero = ripasso.passa
    giri: list = []

    def e_intanto_ne_arriva_un_altro(*argomenti, **parole):
        esito = vero(*argomenti, **parole)
        giri.append(esito.fatti)
        if len(giri) == 1:
            with importato.scrittura() as connessione:
                rileggi_fps.da_leggere(connessione, ultimo)
        return esito

    monkeypatch.setattr(ripasso, "passa", e_intanto_ne_arriva_un_altro)
    assert rileggi_fps.tutti_i_file(importato) == 2
    assert giri == [1, 1]
    dopo = _per_nome(importato)
    assert (dopo[nomi[primo]]["fps"], dopo[nomi[ultimo]]["fps"]) == (
        float(RITMI[nomi[primo]]), float(RITMI[nomi[ultimo]]))
    assert importato.stato(rileggi_fps.FINO_A) is None
    assert importato.stato(rileggi_fps.DA) is None
    assert [e for e in eventi if e[0].startswith("rileggi_fps")] == [
        ("rileggi_fps.finito", {"quanti": 2})]


@CON_AV
def test_i_video_arrivati_con_la_sincronia_si_mettono_in_fila(archivio, tmp_path):
    from prove.test_sincronia_fusione import _travaso
    from officina.archivio.accesso import Archivio
    from officina.impostazioni import Posizione

    altro = Archivio(Posizione(tmp_path / "zenbook", "finto")).apri()
    try:
        _importa(altro, _video(tmp_path / "di_la" / "trenta.mov", 30).parent)
        _foto(tmp_path / "di_la_foto" / "foto.png")
        _importa(altro, tmp_path / "di_la_foto")
        _travaso(altro, archivio, tmp_path)
    finally:
        altro.chiudi(con_copia=False)
    with archivio.lettura() as connessione:
        video = uno(connessione, "SELECT id, fps FROM file_media WHERE genere = 'video'")
        foto = uno(connessione, "SELECT id FROM file_media WHERE genere = 'immagine'")
    assert video["fps"] is None and foto["id"] > video["id"]
    assert archivio.stato(rileggi_fps.FINO_A) == video["id"]
    assert rileggi_fps.tutti_i_file(archivio) == 1
    with archivio.lettura() as connessione:
        assert uno(connessione, "SELECT fps FROM file_media WHERE id = ?",
                   video["id"])["fps"] == 30.0


VALORI = {"a.mov": 25.0, "b.mov": 29.97, "c.mov": 55.4, "d.mov": 55.5, "e.mov": 56.0,
          "f.mov": 60.0, "g.mov": 85.4, "h.mov": 85.5, "i.mov": 86.0, "j.mov": 240.0,
          "k.mov": None, "l.mov": 0.0}
FASCE = {"ridotti": ["a.mov", "b.mov", "c.mov"],
         "medi": ["d.mov", "e.mov", "f.mov", "g.mov"],
         "alti": ["h.mov", "i.mov", "j.mov"]}


@pytest.fixture
def con_i_valori(archivio, tmp_path):
    dove = tmp_path / "valori"
    for numero, nome in enumerate(VALORI, start=2):
        _video(dove / nome, numero)
    _foto(dove / "foto.png")
    _importa(archivio, dove)
    file = _per_nome(archivio)
    with archivio.scrittura() as connessione:
        connessione.executemany(
            "UPDATE file_media SET fps = ? WHERE id = ?",
            [(valore, file[nome]["id"]) for nome, valore in VALORI.items()])
    return archivio, file


def _quali(archivio, file, filtro: Filtro) -> list[str]:
    with archivio.lettura() as connessione:
        trovati = {riga["id"] for riga in scatti.pagina(connessione, filtro, 0, 100)}
        assert scatti.conta(connessione, filtro) == len(trovati)
    return sorted(nome for nome, riga in file.items() if riga["scatto_id"] in trovati)


def test_le_tre_fasce_stanno_dove_dice_l_arrotondamento(con_i_valori):
    archivio, file = con_i_valori
    for fascia, nomi in FASCE.items():
        assert _quali(archivio, file, Filtro(fps=fascia)) == nomi
    assert _quali(archivio, file, Filtro(fps="altissimi")) == sorted(file)
    assert set(scatti.FASCE_FPS) == set(vista.FPS) == set(FASCE)
    assert _quali(archivio, file, Filtro(fps="medi", genere="video")) == FASCE["medi"]
    assert _quali(archivio, file, Filtro(fps="medi", genere="foto")) == []


def test_contano_solo_i_video_principali_dei_video(con_i_valori):
    archivio, file = con_i_valori
    with archivio.scrittura() as connessione:
        connessione.execute("UPDATE scatti SET genere = 'live' WHERE id = ?",
                            (file["a.mov"]["scatto_id"],))
        connessione.execute("UPDATE file_media SET ruolo = 'movimento' WHERE id = ?",
                            (file["e.mov"]["id"],))
        connessione.execute("UPDATE file_media SET genere = 'immagine' WHERE id = ?",
                            (file["i.mov"]["id"],))
    assert _quali(archivio, file, Filtro(fps="ridotti")) == ["b.mov", "c.mov"]
    assert _quali(archivio, file, Filtro(fps="medi")) == ["d.mov", "f.mov", "g.mov"]
    assert _quali(archivio, file, Filtro(fps="alti")) == ["h.mov", "j.mov"]


def test_il_filtro_fps_va_e_torna_dall_indirizzo():
    assert not Filtro(fps="medi").e_vuoto()
    for fascia in FASCE:
        filtro = vista.filtro_da_parametri({"fps": fascia})
        assert filtro.fps == fascia and not filtro.e_vuoto()
        assert vista.parametri_da_filtro(filtro) == {"fps": fascia}
        assert vista.indirizzo(filtro) == f"/?fps={fascia}"
    for strano in ("", "MEDI", "altissimi", ["medi"], 60, None):
        assert vista.filtro_da_parametri({"fps": strano}).fps is None
    assert vista.parametri_da_filtro(Filtro()) == {}
    assert vista.filtro_da_parametri({}).fps is None


def test_la_pillola_dice_la_fascia_e_si_toglie(connessione):
    filtro = Filtro(fps="alti", genere="video")
    pillole = vista.pillole_attive(connessione, filtro)
    assert [p["testo"] for p in pillole] == ["video", "FPS alti · da 86 FPS in su"]
    assert pillole[1]["senza"] == "/?genere=video"
    assert vista.frase(connessione, Filtro(fps="ridotti"), 3) == (
        "FPS ridotti · fino a 55 FPS — 3 scatti")
    assert [p["testo"] for p in vista.pillole_attive(connessione, Filtro(fps="medi"))] == [
        "FPS medi · da 56 a 85 FPS"]
    assert vista.pillole_attive(connessione, Filtro(fps="altissimi")) == []


def test_i_conti_della_colonna_tengono_conto_degli_fps(con_i_valori):
    archivio, _ = con_i_valori
    assert conteggi.chiave(Filtro(fps="medi")) != conteggi.chiave(Filtro(fps="alti"))
    assert conteggi.chiave(Filtro(fps="medi")) != conteggi.chiave(Filtro())
    conteggi.scorda_tutto()
    with archivio.lettura() as connessione:
        tutti_i_conti = conteggi.della_colonna(connessione, Filtro())
        solo_medi = conteggi.della_colonna(connessione, Filtro(fps="medi"))
    assert tutti_i_conti["fps"] == {fascia: len(nomi) for fascia, nomi in FASCE.items()}
    assert solo_medi["generi"] == {"foto": 0, "live": 0, "video": len(FASCE["medi"])}
    assert solo_medi["fps"] == tutti_i_conti["fps"]


@pytest.fixture
def cliente(con_i_valori):
    from officina.web.server import app

    return TestClient(app, client=("127.0.0.1", 51000))


def test_la_galleria_ha_la_tendina_degli_fps(cliente, monkeypatch):
    monkeypatch.setattr(comune, "gia_ripreso", True)
    pagina = html.unescape(cliente.get("/").text)
    assert pagina.count('data-gruppo="fps"') == 1
    assert "<span>FPS dei video</span>" in pagina
    for fascia, (nome, quanti) in vista.FPS.items():
        assert (f'<a class="voce-filtro " href="/?fps={fascia}">') in pagina
        assert f'{nome} <span class="tenue">· {quanti}</span>' in pagina
        assert f'data-numero="fps:{fascia}"' in pagina
    filtrata = html.unescape(cliente.get("/?fps=medi").text)
    assert '<a class="voce-filtro piena" href="/">' in filtrata
    assert '<a class="voce-filtro " href="/?fps=alti">' in filtrata
    assert "<span>FPS dei video · 1</span>" in filtrata
    assert "FPS medi · da 56 a 85 FPS" in filtrata
    numeri = cliente.get("/api/conteggi?fps=medi").json()
    assert numeri["fps"] == {fascia: len(nomi) for fascia, nomi in FASCE.items()}
    assert numeri["generi"]["video"] == len(FASCE["medi"])


def test_la_galleria_fa_partire_la_lettura_degli_fps(cliente, con_i_valori, monkeypatch):
    archivio, _ = con_i_valori
    partiti: list = []
    for nome in ("raddrizza_i_video_in_sottofondo", "rileggi_le_date_in_sottofondo",
                 "rileggi_le_macchine_in_sottofondo"):
        monkeypatch.setattr(importazione, nome, lambda archivio: None)
    monkeypatch.setattr(importazione, "rileggi_gli_fps_in_sottofondo",
                        lambda archivio: partiti.append(archivio))
    monkeypatch.setattr(comune, "gia_ripreso", False)
    cliente.get("/", follow_redirects=False)
    cliente.get("/", follow_redirects=False)
    assert partiti == [archivio]


def test_la_lettura_in_sottofondo_parte_solo_se_c_e_da_fare(archivio, monkeypatch):
    partiti: list = []
    monkeypatch.setattr(comune.lavoro_fps, "parti",
                        lambda fai, nome: partiti.append((fai, nome)) or True)
    monkeypatch.setattr(rileggi_fps, "tutti_i_file",
                        lambda quale, basta: ("letti", quale, basta()))
    assert importazione.rileggi_gli_fps_in_sottofondo(archivio) is False
    assert partiti == []
    archivio.salva_stato(rileggi_fps.FINO_A, 4)
    comune.fps_basta.set()
    assert importazione.rileggi_gli_fps_in_sottofondo(archivio) is True
    assert [nome for _, nome in partiti] == ["rileggi_fps"]
    assert partiti[0][0]() == ("letti", archivio, False)
    comune.fps_basta.set()
    assert partiti[0][0]() == ("letti", archivio, True)
    comune.fps_basta.clear()
    from officina.archivio import accesso

    monkeypatch.setattr(accesso, "in_prova", lambda: True)
    assert importazione.rileggi_gli_fps_in_sottofondo(archivio) is False
    assert len(partiti) == 1


def test_chiudendo_la_lettura_degli_fps_si_ferma(archivio, monkeypatch):
    from officina.web.strade import generale

    monkeypatch.setitem(comune.fila_ia, "fermata", comune.fila_ia.get("fermata"))
    comune.fps_basta.clear()
    assert comune.lavoro_fps in generale._tutti_i_lavori()
    generale.ferma_tutto(0.1)
    assert comune.fps_basta.is_set()
    comune.fps_basta.clear()
