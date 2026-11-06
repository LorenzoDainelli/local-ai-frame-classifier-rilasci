from __future__ import annotations

import json
from fractions import Fraction
from pathlib import Path

import pytest

from officina.miglioria import catena, centoventi, coda, fluido, lavoro, previsione, rifai
from officina.miglioria import video
from officina.web import miglioramento as miglioramento_web
from prove.test_miglioria import _riga, cartella, importato
from prove.test_miglioria_pezzi import _filmato, _lavoro, _quadri, piccolo
from prove.test_miglioria_rifai import (NUOVA, _di, _eventi, _ritoccata,
                                        _scritta)
from prove.test_miglioria_sfida import _gira
from prove.test_web_miglioramento import cliente

__all__ = ["cartella", "cliente", "importato", "piccolo"]

PRIMA = "2026-01-01T00:00:00Z"
NTSC_30 = Fraction(30000, 1001)


@pytest.mark.parametrize(("fps", "arrivo", "volte"), [
    (24, Fraction(120), 5),
    (25, Fraction(120), 5),
    (30, Fraction(120), 4),
    (NTSC_30, centoventi.NTSC, 4),
    (50, Fraction(120), 3),
    (Fraction(60000, 1001), centoventi.NTSC, 2),
    (60, Fraction(120), 2),
    (100, Fraction(120), 2),
    (15, Fraction(120), 8),
])
def test_quante_volte_e_dove_si_arriva(fps, arrivo, volte):
    assert centoventi.arrivo(fps) == arrivo
    assert centoventi.volte(fps, arrivo) == volte


@pytest.mark.parametrize("fps", [119, 120, 240, None, 0, -5, "storto"])
def test_sopra_i_119_o_senza_fps_non_si_tocca(fps):
    assert centoventi.arrivo(fps) is None


@pytest.mark.parametrize(("fps", "secondi"), [(25, 1), (50, 1), (24, 2), (NTSC_30, 1)])
def test_ne_escono_quanti_ne_servono_e_la_durata_resta(fps, secondi):
    verso = centoventi.arrivo(fps)
    entrati = int(round(Fraction(fps) * secondi))
    volte = centoventi.volte(fps, verso)
    scelti = list(centoventi.scegli(range(entrati * volte), fps, verso))
    assert len(scelti) == centoventi.quanti_escono(entrati, fps, verso)
    assert abs(len(scelti) / verso - Fraction(entrati) / Fraction(fps)) < Fraction(1, 60)
    salti = {b - a for a, b in zip(scelti, scelti[1:])}
    assert max(salti) - min(salti) <= 1


def test_ripresa_a_meta_sceglie_gli_stessi():
    verso = centoventi.arrivo(25)
    volte = centoventi.volte(25, verso)
    tutti = list(centoventi.scegli(range(100 * volte), 25, verso))
    gia = 137
    partenza = fluido.da_dove(gia, 25, verso, volte)
    dopo = list(fluido.scelti(range(partenza * volte, 100 * volte), 25, verso, volte, gia,
                              partenza * volte))
    assert dopo == tutti[gia:]


def test_a_parole():
    assert centoventi.a_parole(NTSC_30, centoventi.NTSC) == "da 29,97 a 119,88 FPS"
    assert centoventi.a_parole(25, Fraction(120)) == "da 25 a 120 FPS"
    assert centoventi.a_parole(25, None) == ""


def _fatto(**piu) -> dict:
    return {"nome": centoventi.NOME, "da": "25", "a": "120", "motore": "gimm", **piu}


def test_in_revisione_si_legge_con_che_motore():
    usati = [{"nome": "seedvr2", "versione": NUOVA}, _fatto()]
    assert (miglioramento_web.motori_a_parole(json.dumps(usati))
            == "SeedVR2 · da 25 a 120 FPS con GIMM-VFI-F-P")
    solo = [_fatto(da="30000/1001", a="120000/1001", motore="fusione")]
    assert (miglioramento_web.motori_a_parole(json.dumps(solo))
            == "da 29,97 a 119,88 FPS con Fusione di GIMM-VFI e LDF-VFI")
    saltato = [{"nome": "seedvr2"}, _fatto(a=None, motore=None)]
    assert miglioramento_web.motori_a_parole(json.dumps(saltato)) == "SeedVR2"
    assert miglioramento_web.motori_a_parole('{"a": 1}') == ""


def test_il_messaggio_pronto_da_rivedere_dice_i_120():
    detto = lavoro.misura_del_motore({"motori": [_fatto(motore="ldf", da="60")]})
    assert detto == " · da 60 a 120 FPS con LDF-VFI"
    assert lavoro.misura_del_motore({"motori": [{"nome": "seedvr2"}]}) == ""


def _file(fps, durata_ms=10_000) -> dict:
    return {"genere": "video", "formato": "mp4", "dimensione": 10_000_000,
            "larghezza": 1280, "altezza": 720, "durata_ms": durata_ms, "fps": fps}


def test_la_previsione_conta_i_fotogrammi_in_piu():
    senza = previsione.fattori(_file(30))
    assert (senza["fluidi"], senza["fluido"]) == (0, "")
    con = previsione.fattori(_file(30), fluido="gimm")
    assert (con["fluidi"], con["fluido"]) == (1200, "gimm")
    gia = previsione.fattori(_file(120), fluido="gimm")
    assert gia["fluidi"] == 0


def test_la_previsione_impara_che_i_120_costano():
    misure = []
    for durata in (4_000, 8_000, 16_000, 32_000):
        misure.append((previsione.fattori(_file(30, durata)), durata / 100))
        misure.append((previsione.fattori(_file(30, durata), fluido="ldf"), durata / 20))
    imparato = previsione.impara("video", misure)
    assert "fluido:ldf" in imparato.colonne and "fluidi" in imparato.colonne
    senza = imparato.secondi(previsione.fattori(_file(30, 10_000)))
    con = imparato.secondi(previsione.fattori(_file(30, 10_000), fluido="ldf"))
    assert con > 3 * senza
    vecchia = previsione.fattori(_file(30, 10_000))
    del vecchia["fluidi"], vecchia["fluido"]
    assert imparato.secondi(vecchia) == pytest.approx(senza)


class FluidoFinto:

    def __init__(self, nome, deposito=None, **_opzioni) -> None:
        self.nome = nome
        self.spento = False

    @property
    def a_coppie(self) -> bool:
        return False

    def firma(self) -> dict:
        return {"motore": self.nome, "finto": 1}

    def usati(self) -> list[dict]:
        return [{"nome": "finto120", "versione": "1"}]

    def dove_stanno(self):
        return None

    def foglio(self):
        return None

    def uscite(self, apri, volte):
        ultimo = None
        for quadro in apri():
            for _volta in range(volte):
                yield quadro
            ultimo = quadro
        assert ultimo is not None

    def spegni(self) -> None:
        self.spento = True


@pytest.fixture
def fluido_finto(monkeypatch):
    monkeypatch.setattr(fluido, "Motore", FluidoFinto)


def test_il_video_ingrandito_esce_a_120_con_la_stessa_durata(tmp_path, piccolo,
                                                            fluido_finto):
    originale = _filmato(tmp_path / "a.mp4")
    fatto = catena.filmato(dict(_lavoro(tmp_path, originale), fps120="gimm"))
    uscita = Path(_lavoro(tmp_path, originale)["uscita"])
    piano = video.guarda(uscita)
    assert piano.fps == 120
    assert len(_quadri(uscita)) == 300
    assert _quadri(uscita)[0].shape[:2] == (48, 64)
    assert fatto["fps"] == {"da": "10", "a": "120", "motore": "gimm"}
    assert [usato["nome"] for usato in fatto["motori"]] == ["finto", centoventi.NOME]
    assert fatto["motori"][1]["usati"] == [{"nome": "finto120", "versione": "1"}]
    assert not fluido.cartella(uscita).exists()


def test_il_video_gia_grande_si_porta_solo_a_120(tmp_path, monkeypatch, fluido_finto):
    monkeypatch.setattr(catena.misura, "e_gia_grande", lambda *_a, **_k: True)
    originale = _filmato(tmp_path / "a.mp4", quanti=10)
    lavoro_ = _lavoro(tmp_path, originale)
    with pytest.raises(catena.TroppoGrande):
        catena.filmato(lavoro_)
    fatto = catena.filmato(dict(lavoro_, fps120="ldf"))
    uscita = Path(lavoro_["uscita"])
    assert (fatto["larghezza"], fatto["altezza"]) == (32, 24)
    assert [usato["nome"] for usato in fatto["motori"]] == [centoventi.NOME]
    assert len(_quadri(uscita)) == 120


def test_sopra_i_119_il_segno_dice_che_non_serviva(tmp_path, piccolo, monkeypatch):
    monkeypatch.setattr(catena.centoventi, "arrivo", lambda fps: None)
    originale = _filmato(tmp_path / "a.mp4", quanti=5)
    fatto = catena.filmato(dict(_lavoro(tmp_path, originale), fps120="gimm"))
    assert fatto["motori"][-1] == {"nome": centoventi.NOME, "da": "10", "a": None,
                                   "motore": None}


def _con_la_gara(archivio, vincitore: str | None = "gimm") -> None:
    archivio.imposta(centoventi.SCELTO, vincitore or "")


def _video(archivio, stato: str, fps=30, **campi):
    riga = _scritta(archivio, "breve.MOV", stato, NUOVA, **campi)
    with archivio.scrittura() as connessione:
        connessione.execute("UPDATE file_media SET fps = ? WHERE id = ?",
                            (fps, riga["file_id"]))
    return riga


def _rifai_finto(monkeypatch) -> list:
    visti: list = []

    def una(_archivio, riga):
        visti.append(riga["id"])
        return None

    monkeypatch.setattr(rifai, "_una", una)
    return visti


def test_senza_vincitore_non_si_rifa_niente(importato, monkeypatch):
    visti = _rifai_finto(monkeypatch)
    _video(importato, coda.APPROVATA, finita_il=PRIMA)
    assert rifai.a_centoventi(importato, gara=lambda _a: None) is None
    assert visti == []


def test_spento_non_si_rifa_niente(importato, monkeypatch):
    visti = _rifai_finto(monkeypatch)
    _con_la_gara(importato)
    importato.imposta(centoventi.ACCESO, False)
    _video(importato, coda.APPROVATA, finita_il=PRIMA)
    assert rifai.a_centoventi(importato) is None
    assert visti == []


FATTA_A_120 = json.dumps([{"nome": "seedvr2"}, _fatto()])
DOPO = "2999-01-01T00:00:00Z"


@pytest.mark.parametrize(("stato", "fps", "campi", "si_rifa"), [
    (coda.APPROVATA, 30, {}, True),
    (coda.DA_RIVEDERE, 25, {}, True),
    (coda.APPROVATA, 120, {}, False),
    (coda.APPROVATA, None, {}, False),
    (coda.APPROVATA, 30, {"motori": FATTA_A_120}, False),
    (coda.DA_RIVEDERE, 30, {"motori": FATTA_A_120}, False),
    (coda.RIFIUTATA, 30, {}, False),
    (coda.IN_CODA, 30, {}, False),
    (coda.FALLITA, 30, {"guasto": catena.GIA_GRANDE}, True),
    (coda.FALLITA, 120, {"guasto": catena.GIA_GRANDE}, False),
    (coda.FALLITA, 30, {"guasto": "spazio"}, False),
    (coda.FALLITA, 30, {"guasto": catena.GIA_GRANDE, "finita_il": DOPO}, False),
])
def test_quali_video_si_rifanno(importato, monkeypatch, stato, fps, campi, si_rifa):
    visti = _rifai_finto(monkeypatch)
    _con_la_gara(importato)
    riga = _video(importato, stato, fps=fps, **{"finita_il": PRIMA, **campi})
    esito = rifai.a_centoventi(importato)
    assert visti == ([riga["id"]] if si_rifa else [])
    assert (esito is not None and esito.rimesse == 1) is si_rifa


def test_le_foto_non_si_rifanno(importato, monkeypatch):
    visti = _rifai_finto(monkeypatch)
    _con_la_gara(importato)
    _scritta(importato, "piccola.jpg", coda.APPROVATA, NUOVA, finita_il=PRIMA)
    assert rifai.a_centoventi(importato) is None and visti == []


def test_la_fallita_gia_grande_torna_davvero_in_coda(importato):
    _con_la_gara(importato)
    riga = _video(importato, coda.FALLITA, guasto=catena.GIA_GRANDE, finita_il=PRIMA)
    assert rifai.a_centoventi(importato).rimesse == 1
    assert _di(importato, riga["id"])["stato"] == coda.IN_CODA


def test_ritoccati_restano_e_si_elencano(importato, monkeypatch):
    visti = _rifai_finto(monkeypatch)
    _con_la_gara(importato)
    riga = _video(importato, coda.APPROVATA, finita_il=PRIMA)
    _ritoccata(importato, riga)
    assert rifai.a_centoventi(importato) is None
    assert visti == []
    chiamate: list = []
    vero = rifai.perche_resta

    def la_prima_volta_no(connessione, r):
        chiamate.append(r["id"])
        return None if len(chiamate) == 1 else vero(connessione, r)

    monkeypatch.setattr(rifai, "perche_resta", la_prima_volta_no)
    esito = rifai.a_centoventi(importato)
    assert esito.saltate == [f"breve.MOV: {rifai.RITOCCATO}"]
    with importato.lettura() as connessione:
        assert rifai.a_centoventi_a_parole(connessione)["saltate"] == esito.saltate


def test_il_giro_rimette_in_coda_e_lo_dice(importato):
    _con_la_gara(importato)
    riga = _video(importato, coda.FALLITA, guasto=catena.GIA_GRANDE, finita_il=PRIMA)
    miglioratore = _gira(importato, None, pronti=False)
    assert ("rimetto in coda 1 video sotto i 120 FPS, per rifarli a 120 FPS"
            in miglioratore.lavoro.righe)
    assert _di(importato, riga["id"])["guasto"] != catena.GIA_GRANDE


def test_il_lavoro_non_parte_da_solo(importato, monkeypatch):
    from officina.web.strade import miglioramento as strade

    avviati: list = []
    monkeypatch.setattr(strade, "avvia_il_miglioramento", avviati.append)
    _con_la_gara(importato)
    _video(importato, coda.FALLITA, guasto=catena.GIA_GRANDE, finita_il=PRIMA)
    rifai.a_centoventi(importato)
    assert avviati == []
    assert len(_riga(importato, coda.IN_CODA)) == 1


def test_la_pagina_lo_dice_e_ho_capito_lo_toglie(cliente, importato):
    _con_la_gara(importato)
    _video(importato, coda.FALLITA, guasto=catena.GIA_GRANDE, finita_il=PRIMA)
    rifai.a_centoventi(importato)
    testo = cliente.get("/miglioramento").text
    assert "Da rifare a 120 FPS" in testo and "premi Avvia" in testo
    risposta = cliente.post("/miglioramento/a-120/visto", follow_redirects=False)
    assert risposta.status_code == 303
    assert "Da rifare a 120 FPS" not in cliente.get("/miglioramento").text


def test_l_evento_dice_quante(importato, monkeypatch):
    _con_la_gara(importato)
    _video(importato, coda.FALLITA, guasto=catena.GIA_GRANDE, finita_il=PRIMA)
    eventi = _eventi(monkeypatch)
    rifai.a_centoventi(importato)
    assert ("miglioria.rifatte_a_120", {"rimesse": 1, "saltate": 0, "byte": 0}) in eventi


@pytest.mark.parametrize(("fps120", "fps", "entra"), [
    (False, 30, False),
    (True, 30, True),
    (True, 120, False),
])
def test_in_coda_il_video_gia_grande_entra_solo_per_i_120(importato, fps120, fps, entra):
    from prove.test_miglioria import _scatto_di

    importato.imposta("miglioria_misura", "fhd")
    with importato.scrittura() as connessione:
        connessione.execute("UPDATE file_media SET larghezza = 1920, altezza = 1080, fps = ? "
                            "WHERE genere = 'video'", (fps,))
        esito = coda.metti(connessione, [_scatto_di(importato, "breve.MOV")], fps120=fps120)
    assert esito.messi == (1 if entra else 0)
    assert esito.gia_grandi == ([] if entra else ["breve.MOV"])


def test_le_impostazioni_hanno_l_interruttore_e_la_scelta(cliente, importato):
    testo = cliente.get("/impostazioni").text
    assert "Porta i video a 120 FPS" in testo
    assert "Chi fa i 120 FPS" in testo
    assert "La gara non ha ancora un vincitore" in testo
    for nome in ("GIMM-VFI", "LDF-VFI", "Fusione"):
        assert nome in testo


def test_con_il_vincitore_le_impostazioni_lo_nominano(cliente, importato, monkeypatch):
    from officina.web.strade import impostazioni as strade

    monkeypatch.setattr(strade.centoventi, "dalla_gara", lambda _a: "ldf")
    testo = cliente.get("/impostazioni").text
    assert "cioè <b>LDF-VFI</b>" in testo
