from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from officina.miglioria import fluido, pezzi, video
from officina.miglioria import prova_veloce_corsa as corsa
from prove.test_miglioria_centoventi import FluidoFinto
from prove.test_miglioria_pezzi import piccolo
from prove.test_miglioria_veloce import x264_sempre_uguale

__all__ = ["piccolo", "x264_sempre_uguale"]

LAVORO = {"motori": {"video": "finto"}}


@pytest.fixture
def fluido_finto(monkeypatch):
    pytest.importorskip("av")
    monkeypatch.setattr(fluido, "Motore", FluidoFinto)
    monkeypatch.setattr(fluido, "SECONDI_PER_TRATTO", 0.25)


def _foto(cartella: Path, quante: int, seme: int) -> list[str]:
    from PIL import Image

    cartella.mkdir(parents=True, exist_ok=True)
    rumore = np.random.default_rng(seme)
    fatte = []
    for numero in range(quante):
        quadro = rumore.integers(0, 256, (64, 96, 3), dtype=np.uint8)
        posto = cartella / f"{numero:03d}.png"
        Image.fromarray(quadro).save(posto)
        fatte.append(str(posto))
    return fatte


def _clip(tmp_path: Path) -> list[dict]:
    return [{"nome": "a", "codec": video.H264, "gruppo": "facile", "fps120": None,
             "file": _foto(tmp_path / "foto-a", 12, 1)},
            {"nome": "b", "codec": video.HEVC, "gruppo": "difficilissimo",
             "fps120": "gimm", "file": _foto(tmp_path / "foto-b", 12, 2)}]


def test_ordine_alternato():
    assert corsa.ordine(2) == [(0, "vecchio"), (1, "nuovo"), (2, "vecchio"),
                               (3, "nuovo")]
    assert corsa.passi([{"fps120": None}, {"fps120": "gimm"}], 3) == 7 + 8


def test_misura_piccola_pari_e_dentro_720():
    assert corsa.misura_piccola(1920, 1080) == (1280, 720)
    assert corsa.misura_piccola(97, 65) == (96, 64)
    assert corsa.misura_piccola(2000, 500) == (1280, 320)


def test_il_riassunto_vuole_tutto_uguale():
    clip = {"nome": "a", "codec": video.H264}
    giri = [{"clip": "a", "giro": n, "modo": m, "impronta": i, "secondi": 1.0}
            for n, m, i in [(0, "vecchio", "x"), (1, "nuovo", "x"), (2, "vecchio", "x"),
                            (3, "nuovo", "x")]]
    assert corsa.riassunto(clip, giri, 2)["uguale"]
    diverso = [dict(g, impronta="y") if g["giro"] == 3 else g for g in giri]
    assert not corsa.riassunto(clip, diverso, 2)["uguale"]
    instabile = [dict(g, impronta="y") if g["giro"] == 2 else g for g in giri]
    fatto = corsa.riassunto(clip, instabile, 2)
    assert not fatto["stabile"] and not fatto["uguale"]
    assert not corsa.riassunto(clip, giri[:3], 2)["uguale"]
    assert not corsa.esito([clip], giri[:3], 2)["passata"]
    assert not corsa.esito([], [], 2)["passata"]


def test_la_prova_passa_e_riprende_senza_rifare(tmp_path, piccolo, fluido_finto,
                                                monkeypatch):
    clip = _clip(tmp_path)
    passi = []
    dati = corsa.corri(tmp_path / "prova", clip, LAVORO,
                       al_passo=lambda f, t: passi.append((f, t)), volte=2)
    assert dati["passata"], dati
    assert passi[-1] == (corsa.passi(clip, 2), corsa.passi(clip, 2))
    assert corsa.leggi_esito(tmp_path / "prova")["passata"]
    for uno in dati["clip"]:
        assert len(set(uno["vecchi"])) == 1 and uno["uguale"]
    assert not list((tmp_path / "prova").rglob("*.mp4.parziale"))

    def mai(*_argomenti, **_chiavi):
        raise AssertionError("rifatto")

    monkeypatch.setattr(corsa, "un_giro", mai)
    monkeypatch.setattr(corsa.catena, "solo_la_scheda", mai)
    assert corsa.corri(tmp_path / "prova", clip, LAVORO, volte=2)["passata"]


def test_se_il_nuovo_cambia_un_bit_la_prova_non_passa(tmp_path, piccolo, fluido_finto,
                                                      monkeypatch):
    clip = _clip(tmp_path)[:1]
    vero = corsa.un_giro

    def sporco(cartella_clip, uno, lavoro, numero, modo):
        fatto = vero(cartella_clip, uno, lavoro, numero, modo)
        if modo == corsa.NUOVO and numero == 3:
            fatto["impronta"] = "0" * 64
        return fatto

    monkeypatch.setattr(corsa, "un_giro", sporco)
    dati = corsa.corri(tmp_path / "prova", clip, LAVORO, volte=2)
    assert not dati["passata"]
    assert dati["clip"][0]["stabile"]


def test_i_fotogrammi_a_120_si_rileggono_identici(tmp_path, piccolo, fluido_finto):
    clip = _clip(tmp_path)[1]
    cartella = tmp_path / "prova" / clip["nome"]
    originale = cartella / corsa.ORIGINALE
    corsa.fai_l_originale(originale, corsa._quadri_da(clip["file"]), clip["codec"], 12)
    lavoro = dict(LAVORO, genere="video", originale=str(originale), fps120="gimm")
    corsa.la_scheda(cartella, lavoro)
    dove = corsa.registra(cartella, clip, lavoro)
    firma = {"prova": clip["nome"], "fluido": "gimm"}
    assert corsa.registrati_buoni(dove, firma)
    assert not corsa.registrati_buoni(dove, {"prova": "altro", "fluido": "gimm"})
    rifatto = corsa.Riproduttore(dove, firma)
    assert rifatto.firma() == FluidoFinto("gimm").firma()
    letti = list(rifatto.uscite(None, 4))
    attesi = list(pezzi.Pezzi(cartella / corsa.FISSI,
                              _firma_fissi(cartella)).rileggi())
    assert len(letti) == 4 * len(attesi)
    assert all((letti[4 * n] == quadro).all() for n, quadro in enumerate(attesi))
    with pytest.raises(pezzi.PezzoRotto):
        corsa.Riproduttore(dove, {"prova": "altro", "fluido": "gimm"})


def _firma_fissi(cartella: Path) -> dict:
    import json

    return json.loads((cartella / corsa.FISSI / pezzi.FIRMA).read_text("utf-8"))


def test_l_originale_ha_il_suono_e_la_misura_giusta(tmp_path):
    pytest.importorskip("av")
    posto = tmp_path / "o.mp4"
    corsa.fai_l_originale(posto, corsa._quadri_da(_foto(tmp_path / "f", 6, 3)),
                          video.H264, 6)
    piano = video.guarda(posto)
    assert (piano.larghezza, piano.altezza) == (96, 64)
    assert piano.fotogrammi == 6


class _Archivio:

    def __init__(self, cartella: Path) -> None:
        from types import SimpleNamespace

        self.dove = SimpleNamespace(modelli=cartella)
        self.valori: dict = {}

    def impostazione(self, chiave):
        return self.valori.get(chiave)

    def imposta(self, chiave, valore):
        self.valori[chiave] = valore


def _elenco(tmp_path: Path):
    from PIL import Image

    from officina.miglioria import gara120_casi as g
    from officina.miglioria import gara120_scarica as sc

    nomi = {}
    rumore = np.random.default_rng(5)
    for scena in ("f/uno", "f/due", "d/uno", "d/due"):
        for numero in range(1, 41):
            nome = f"{scena}/{numero:05d}.png"
            posto = tmp_path / "prova" / "dati" / sc.SNU / nome
            posto.parent.mkdir(parents=True, exist_ok=True)
            Image.fromarray(rumore.integers(0, 256, (64, 96, 3), dtype=np.uint8)).save(posto)
            nomi[nome] = ("0" * 64, 1)
    presenti, veri_nomi = g.presenti_da_nomi(nomi)
    casi = [g.Caso(f"{s}/x", gruppo, s, 4, 2) for s, gruppo in
            (("f/uno", g.FACILE), ("f/due", g.FACILE), ("d/uno", g.DIFFICILISSIMO),
             ("d/due", g.DIFFICILISSIMO))]
    return sc.Elenco(casi, nomi, veri_nomi, presenti)


def test_di_fila_preferisce_il_passo_dato():
    from officina.miglioria import prova_veloce

    assert prova_veloce.di_fila({1, 5, 9, 13}, 3, 4) == [1, 5, 9]
    assert prova_veloce.di_fila({1, 2, 4, 7}, 3, 2) is None
    assert prova_veloce.di_fila({1, 2, 4, 7}, 2, 1) == [1, 2]


def test_piu_lunga_trova_la_fila_piu_lunga():
    from officina.miglioria import prova_veloce

    assert prova_veloce.piu_lunga({1, 2, 3, 7, 8, 9, 10}) == [7, 8, 9, 10]
    assert prova_veloce.piu_lunga(set()) == []


def test_con_le_scene_lunghe_usa_il_passo_quattro(tmp_path, monkeypatch):
    from officina.miglioria import prova_veloce

    monkeypatch.setattr(prova_veloce, "SCHEMA", (("facile", video.H264, 8, False),))
    clip = prova_veloce.scegli_clip(_elenco(tmp_path))
    assert clip[0]["nomi"][:3] == ["f/due/00001.png", "f/due/00005.png",
                                   "f/due/00009.png"]


def test_le_clip_sono_quattro_e_di_scene_diverse(tmp_path):
    from officina.miglioria import prova_veloce

    clip = prova_veloce.scegli_clip(_elenco(tmp_path))
    assert [uno["codec"] for uno in clip] == [video.H264, video.H264, video.HEVC,
                                              video.HEVC]
    assert [uno["a_120"] for uno in clip] == [False, True, False, True]
    assert len({uno["scena"] for uno in clip}) == 4
    assert [len(uno["nomi"]) for uno in clip] == [40, 40, 40, 40]
    assert clip[0]["nomi"][:2] == ["f/due/00001.png", "f/due/00002.png"]
    with pytest.raises(Exception):
        prova_veloce.scegli_clip(type(_elenco(tmp_path))([], {}, {}, {}))


def _prova(tmp_path, monkeypatch, lancia=None):
    from officina.miglioria import gara120_scarica as sc
    from officina.miglioria import motori, prova_veloce, rete
    from officina.miglioria import prova_veloce_stanza as stanza
    from officina.web.lavori import TurnoDellaScheda

    monkeypatch.setattr(rete, "chiudi", lambda: None)
    monkeypatch.setattr(motori, "_accesi", None)
    monkeypatch.setattr(prova_veloce, "SCHEMA", tuple(
        (gruppo, codec, 10 if a_120 else 8, a_120)
        for gruppo, codec, _quanti, a_120 in prova_veloce.SCHEMA))
    monkeypatch.setattr(corsa, "VOLTE", 2)
    elenco = _elenco(tmp_path)
    monkeypatch.setattr(sc, "elenco_snu", lambda *a, **k: elenco)
    monkeypatch.setattr(sc, "scarica_snu", lambda *a, **k: None)

    def in_casa(lavoro, al_passo):
        messaggi = []
        stanza.un_lavoro(lavoro, messaggi.append)
        return messaggi[-1]

    archivio = _Archivio(tmp_path)
    archivio.valori["miglioria_video"] = "finto"
    prova = prova_veloce.ProvaVeloce(archivio, cartella=tmp_path / "prova",
                                     lancia=lancia or in_casa, turno=TurnoDellaScheda(),
                                     prepara=lambda nome: None, pronta=lambda: True)
    return prova, archivio


def test_la_prova_passa_e_accende_l_idea(tmp_path, piccolo, fluido_finto, monkeypatch):
    from officina.miglioria import veloce

    prova, archivio = _prova(tmp_path, monkeypatch)
    assert not prova.accesa()
    with pytest.raises(Exception):
        prova.accendi(True)
    prova._gira()
    assert prova.lavoro.guasto == "", prova.lavoro.dettaglio
    assert prova.esito()["passata"]
    assert archivio.valori[veloce.CHIAVE] == {"scrittura": True}
    assert prova.accesa() and prova.turno.chi is None
    prova.accendi(False)
    assert not prova.accesa()
    prova.accendi(True)
    assert prova.accesa()


def test_la_prova_non_passata_lascia_spento(tmp_path, monkeypatch):
    prova, archivio = _prova(tmp_path, monkeypatch, lancia=lambda lavoro, al_passo: {
        "fatto": {"passata": False, "clip": []}})
    prova._gira()
    assert not prova.accesa()
    assert "veloce_acceso" not in archivio.valori


def test_senza_seedvr2_lo_dice(tmp_path, monkeypatch):
    prova, _ = _prova(tmp_path, monkeypatch)
    prova._pronta = lambda: False
    with pytest.raises(Exception) as errore:
        prova._corri()
    assert "SeedVR2" in str(errore.value)


def test_un_guasto_nella_stanza_diventa_un_messaggio(tmp_path, monkeypatch):
    prova, _ = _prova(tmp_path, monkeypatch, lancia=lambda lavoro, al_passo: {
        "guasto": "memoria_scheda_finita"})
    with pytest.raises(Exception):
        prova._corri()
    assert prova.turno.chi is None
