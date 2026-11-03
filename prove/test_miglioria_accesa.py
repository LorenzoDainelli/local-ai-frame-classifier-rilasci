from __future__ import annotations

import io
import json

import pytest

from officina import registro
from officina.miglioria import accesa, coda, lavoro, motori, stanza, stanza_accesa
from officina.sicuro import sportello, tubo
from prove import test_sicuro_servizio as servizio_di_prova
from prove.test_miglioria import _riga, quattro_piccole
from prove.test_miglioria_dall_archivio import (FOTO, _cercata, _la_foto_dall_archivio,
                                                _lavoro, nell_archivio)

casa = servizio_di_prova.casa
costo_leggero = servizio_di_prova.costo_leggero
SCELTI = {"foto": motori.FINTO, "video": motori.FINTO, "volti": None}
__all__ = ["casa", "costo_leggero", "nell_archivio", "quattro_piccole"]


@pytest.fixture
def aperte(monkeypatch) -> list:
    aperti: list = []
    vero = lavoro.apri_la_stanza

    def apri(modulo):
        processo = vero(modulo)
        aperti.append((modulo, processo))
        return processo

    monkeypatch.setattr(lavoro, "apri_la_stanza", apri)
    return aperti


@pytest.fixture
def eventi(monkeypatch) -> list:
    scritti: list = []
    vero = registro.evento

    def evento(codice, **dati):
        scritti.append((codice, dati))
        vero(codice, **dati)

    monkeypatch.setattr(registro, "evento", evento)
    return scritti


def _accesi(eventi: list) -> list:
    return [dati for codice, dati in eventi if codice == "miglioria.stanza_accesa"]


def _gira(archivio) -> lavoro.Miglioratore:
    miglioratore = lavoro.Miglioratore(archivio, motori_scelti=SCELTI)
    assert miglioratore.parti()
    assert miglioratore.lavoro.aspetta_che_finisca(120)
    assert not miglioratore.lavoro.guasto, miglioratore.lavoro.guasto
    return miglioratore


def test_per_tutto_il_giro_la_stanza_resta_una_e_il_motore_si_carica_una_volta(
        quattro_piccole, aperte, eventi):
    miglioratore = _gira(quattro_piccole)
    assert len(_riga(quattro_piccole, coda.DA_RIVEDERE)) == 4
    assert [modulo for modulo, _ in aperte] == [accesa.MODULO]
    [(_, processo)] = aperte
    assert processo.poll() == 0 and processo.stdin.closed
    assert _accesi(eventi) == [{"file": 4, "caricati": 1}]
    assert not miglioratore._accesa.accesa


def test_un_motore_che_non_resta_acceso_apre_una_stanza_per_file(
        quattro_piccole, aperte, eventi, monkeypatch):
    monkeypatch.setattr(motori.Finto, "resta_acceso", False)
    _gira(quattro_piccole)
    assert len(_riga(quattro_piccole, coda.DA_RIVEDERE)) == 4
    assert [modulo for modulo, _ in aperte] == ["officina.miglioria.stanza"] * 4
    assert _accesi(eventi) == []


def _lancia(stanza_: accesa.StanzaAccesa, da_fare: dict, presi: list | None = None) -> dict:
    return stanza_.lancia(da_fare, lambda fatti, totale: None,
                          (presi if presi is not None else []).append)


def test_un_guasto_spegne_la_stanza_e_il_file_dopo_ne_apre_una_nuova(
        tmp_path, aperte, eventi):
    from prove.test_miglioria_dall_archivio import _jpeg

    buona = tmp_path / "buona.jpg"
    buona.write_bytes(_jpeg())
    stanza_ = accesa.StanzaAccesa()
    try:
        assert "fatto" in _lancia(stanza_, _lavoro("immagine", buona, tmp_path / "1.jpg"))
        assert stanza_.accesa and stanza_.file == 1 and stanza_.caricati == 1
        rotto = _lancia(stanza_, _lavoro("immagine", tmp_path / "manca.jpg",
                                         tmp_path / "2.jpg"))
        assert "guasto" in rotto and rotto["guasto"] not in ("stanza_muta", "stanza_caduta")
        assert not stanza_.accesa
        assert aperte[0][1].poll() == 1
        assert _accesi(eventi) == [{"file": 1, "caricati": 1}]
        assert "fatto" in _lancia(stanza_, _lavoro("immagine", buona, tmp_path / "3.jpg"))
        assert len(aperte) == 2 and stanza_.file == 1 and stanza_.caricati == 1
    finally:
        stanza_.spegni()
    assert aperte[1][1].poll() == 0
    assert _accesi(eventi) == [{"file": 1, "caricati": 1}, {"file": 1, "caricati": 1}]
    assert stanza_.file == 0 and stanza_.caricati == 0


def test_spegnere_una_stanza_mai_accesa_non_scrive_niente(eventi):
    stanza_ = accesa.StanzaAccesa()
    stanza_.spegni()
    stanza_.spegni()
    assert _accesi(eventi) == [] and not stanza_.accesa


def test_con_l_originale_nell_archivio_lo_sportello_si_chiude_a_ogni_file(
        nell_archivio, casa, aperte, monkeypatch):
    chiusi: list = []
    vero = sportello.Sportello.chiudi

    def chiudi(allo_sportello):
        chiusi.append(allo_sportello)
        return vero(allo_sportello)

    monkeypatch.setattr(sportello.Sportello, "chiudi", chiudi)
    scritte: list = []
    scrivi_vero = tubo.Verso._scrivi

    def scrivi(verso, messaggio):
        scritte.append(messaggio)
        scrivi_vero(verso, messaggio)

    monkeypatch.setattr(tubo.Verso, "_scrivi", scrivi)
    alla_stanza: list = []
    scrivi_alla_stanza = accesa._scrivi

    def spia(processo, messaggio):
        alla_stanza.append(messaggio)
        scrivi_alla_stanza(processo, messaggio)

    monkeypatch.setattr(accesa, "_scrivi", spia)
    stanza_ = accesa.StanzaAccesa()
    try:
        assert "fatto" in _lancia(stanza_, _la_foto_dall_archivio(nell_archivio, casa))
        assert alla_stanza[-1] == accesa.CHIUSO and len(alla_stanza) == 2
        assert len(chiusi) == 1 and "giro" in scritte[-1] and stanza_.accesa
        prima = len(scritte)
        originale = casa.foto / FOTO
        cercata = _cercata(nell_archivio.dati[FOTO], [originale], FOTO)
        secondo = _lavoro("immagine", originale, nell_archivio.attesa / "2-mare.jpg",
                          dall_archivio=cercata)
        assert "fatto" in _lancia(stanza_, secondo)
        assert len(chiusi) == 2 and chiusi[0] is not chiusi[1]
        assert len(scritte) > prima and "giro" in scritte[-1]
        assert len(aperte) == 1 and stanza_.file == 2
        assert [m == accesa.CHIUSO for m in alla_stanza] == [False, True, False, True]
    finally:
        stanza_.spegni()
    assert aperte[0][1].poll() == 0
    assert (nell_archivio.attesa / "2-mare.jpg").exists()


def test_se_la_stanza_accesa_muore_fra_due_file_il_file_dopo_non_si_perde(
        tmp_path, aperte, eventi):
    from prove.test_miglioria_dall_archivio import _jpeg

    buona = tmp_path / "buona.jpg"
    buona.write_bytes(_jpeg())
    stanza_ = accesa.StanzaAccesa()
    presi: list = []
    try:
        assert "fatto" in _lancia(stanza_, _lavoro("immagine", buona, tmp_path / "1.jpg"),
                                  presi)
        aperte[0][1].kill()
        aperte[0][1].wait()
        assert "fatto" in _lancia(stanza_, _lavoro("immagine", buona, tmp_path / "2.jpg"),
                                  presi)
        assert len(aperte) == 2 and presi == [processo for _, processo in aperte]
        assert _accesi(eventi) == [{"file": 1, "caricati": 1}]
    finally:
        stanza_.spegni()
    assert _accesi(eventi) == [{"file": 1, "caricati": 1}] * 2


def test_se_il_primo_file_si_rompe_non_si_scrive_una_stanza_accesa(tmp_path, eventi):
    stanza_ = accesa.StanzaAccesa()
    try:
        rotto = _lancia(stanza_, _lavoro("immagine", tmp_path / "manca.jpg",
                                         tmp_path / "1.jpg"))
        assert "guasto" in rotto and not stanza_.accesa
    finally:
        stanza_.spegni()
    assert _accesi(eventi) == []


def test_un_motore_che_non_resta_acceso_spegne_prima_quella_accesa(tmp_path, aperte,
                                                                   monkeypatch):
    from prove.test_miglioria_dall_archivio import _jpeg

    buona = tmp_path / "buona.jpg"
    buona.write_bytes(_jpeg())
    stanza_ = accesa.StanzaAccesa()
    try:
        assert "fatto" in _lancia(stanza_, _lavoro("immagine", buona, tmp_path / "1.jpg"))
        monkeypatch.setattr(motori.Finto, "resta_acceso", False)
        assert "fatto" in _lancia(stanza_, _lavoro("immagine", buona, tmp_path / "2.jpg"))
        assert aperte[0][1].poll() == 0 and not stanza_.accesa
        assert [modulo for modulo, _ in aperte] == [accesa.MODULO,
                                                     "officina.miglioria.stanza"]
    finally:
        stanza_.spegni()


@pytest.mark.parametrize("quale", ["lavoro", "chiuso"])
def test_se_scrivere_alla_stanza_non_riesce_la_stanza_si_spegne(tmp_path, aperte,
                                                                 monkeypatch, quale):
    from prove.test_miglioria_dall_archivio import _jpeg

    buona = tmp_path / "buona.jpg"
    buona.write_bytes(_jpeg())
    vero = accesa._scrivi

    def scrivi(processo, messaggio):
        if (quale == "chiuso") == (messaggio == accesa.CHIUSO):
            raise OSError("tubo")
        vero(processo, messaggio)

    monkeypatch.setattr(accesa, "_scrivi", scrivi)
    stanza_ = accesa.StanzaAccesa()
    try:
        esito = _lancia(stanza_, _lavoro("immagine", buona, tmp_path / "1.jpg"))
        assert not stanza_.accesa and aperte[0][1].poll() is not None
        if quale == "chiuso":
            assert "fatto" in esito
        else:
            assert esito == {"guasto": "stanza_muta"}
    finally:
        stanza_.spegni()


def test_una_stanza_che_non_si_chiude_da_sola_si_ferma(tmp_path, monkeypatch, aperte):
    (tmp_path / "stanza_testarda.py").write_text(
        "import json, sys, time\n"
        "sys.stdin.readline()\n"
        "print(json.dumps({'fatto': {}}), flush=True)\n"
        "print(json.dumps({'accesa': True}), flush=True)\n"
        "time.sleep(60)\n", encoding="utf-8")
    monkeypatch.setenv("PYTHONPATH", str(tmp_path))
    monkeypatch.setattr(accesa, "resta_accesa", lambda da_fare: True)
    monkeypatch.setattr(accesa, "ATTESA_DI_CHIUSURA", 0.5)
    stanza_ = accesa.StanzaAccesa("stanza_testarda")
    assert _lancia(stanza_, {}) == {"fatto": {}} and stanza_.accesa
    stanza_.spegni()
    assert aperte[0][1].poll() not in (None, 0) and not stanza_.accesa


@pytest.mark.parametrize("genere, nome, resta", [
    ("immagine", motori.SEEDVR2, True), ("video", motori.SEEDVR2, True),
    ("immagine", motori.FINTO, True), ("video", motori.FINTO, True),
    ("immagine", motori.LUCIDFLUX, False), ("video", motori.LUCIDFLUX, False),
    ("immagine", "nessuno", False), ("immagine", None, False),
])
def test_resta_accesa_solo_per_i_motori_che_lo_dicono(genere, nome, resta):
    da_fare = {"genere": genere, "motori": {"foto": nome, "video": nome}}
    assert accesa.resta_accesa(da_fare) is resta


def test_resta_accesa_guarda_il_motore_del_genere_giusto():
    assert accesa.resta_accesa({"genere": "immagine",
                                "motori": {"foto": motori.FINTO, "video": "x"}})
    assert not accesa.resta_accesa({"genere": "immagine",
                                    "motori": {"foto": "x", "video": motori.FINTO}})
    assert accesa.resta_accesa({"genere": "video",
                                "motori": {"foto": "x", "video": motori.FINTO}})
    assert not accesa.resta_accesa({"genere": "video", "motori": None})


def test_resta_accesa_cerca_il_motore_nell_elenco_del_genere(monkeypatch):
    monkeypatch.setitem(motori.VIDEO, "solo_video", "officina.miglioria.motori:Finto")
    assert accesa.resta_accesa({"genere": "video", "motori": {"video": "solo_video"}})
    assert not accesa.resta_accesa({"genere": "immagine", "motori": {"foto": "solo_video"}})


def test_resta_accesa_vuole_proprio_vero(monkeypatch):
    monkeypatch.setattr(motori.Finto, "resta_acceso", "si")
    assert not accesa.resta_accesa({"genere": "immagine", "motori": {"foto": motori.FINTO}})


@pytest.fixture
def accesi(monkeypatch):
    monkeypatch.setattr(motori, "_accesi", None)
    monkeypatch.setattr(motori, "caricati", 0)


def test_senza_tieni_accesi_ogni_apertura_e_un_motore_nuovo(accesi):
    primo = motori.apri(motori.FOTO, motori.FINTO)
    secondo = motori.apri(motori.FOTO, motori.FINTO)
    assert primo is not secondo and isinstance(primo, motori.Finto)
    assert motori.caricati == 0


def test_tenuti_accesi_lo_stesso_motore_si_riusa_e_spegnere_non_lo_spegne(accesi):
    motori.tieni_accesi()
    primo = motori.apri(motori.FOTO, motori.FINTO, scheda=1)
    assert motori.apri(motori.VIDEO, motori.FINTO, scheda=1) is primo
    altro = motori.apri(motori.FOTO, motori.FINTO, scheda=2)
    assert altro is not primo and motori.caricati == 2
    primo.spegni()
    assert not primo.motore.spento and not primo.spento
    assert motori.ancora_buoni()
    motori.spegni_tutti()
    assert primo.motore.spento and altro.motore.spento
    assert motori.apri(motori.FOTO, motori.FINTO, scheda=1) is not primo
    assert motori.caricati == 3


def test_un_motore_che_non_resta_acceso_non_si_tiene(accesi, monkeypatch):
    monkeypatch.setattr(motori.Finto, "resta_acceso", False)
    motori.tieni_accesi()
    primo = motori.apri(motori.FOTO, motori.FINTO)
    assert motori.apri(motori.FOTO, motori.FINTO) is not primo
    assert isinstance(primo, motori.Finto) and motori.caricati == 0


def test_un_motore_stretto_non_e_piu_buono(accesi):
    motori.tieni_accesi()
    acceso = motori.apri(motori.FOTO, motori.FINTO)
    acceso.motore.stretto = True
    assert not motori.ancora_buoni()


def test_spegni_tutti_va_avanti_anche_se_uno_si_rompe(accesi, monkeypatch):
    motori.tieni_accesi()
    primo = motori.apri(motori.FOTO, motori.FINTO, scheda=1)
    secondo = motori.apri(motori.FOTO, motori.FINTO, scheda=2)

    def rotto():
        raise RuntimeError("x")

    primo.motore.spegni = rotto
    motori.spegni_tutti()
    assert secondo.motore.spento
    motori.spegni_tutti()


def test_spegni_tutti_senza_niente_acceso_non_fa_niente(accesi):
    motori.spegni_tutti()
    assert motori.ancora_buoni()


def _righe(*messaggi) -> io.StringIO:
    return io.StringIO("".join(m if isinstance(m, str) else json.dumps(m) + "\n"
                               for m in messaggi))


def test_lo_smistatore_da_a_ogni_file_le_sue_righe():
    smistatore = stanza_accesa.Smistatore(_righe(
        {"lavoro": {"n": 1}}, "a\n", {"lavoro": {"n": 2}}, "b\n", {"chiuso": True},
        "c\n", "non json\n", [1], {"lavoro": {"n": 3}}, "d\n"))
    primo, filo_1 = smistatore.prossimo()
    secondo, filo_2 = smistatore.prossimo()
    terzo, filo_3 = smistatore.prossimo()
    assert (primo, secondo, terzo) == ({"n": 1}, {"n": 2}, {"n": 3})
    assert list(filo_1) == ["a\n"]
    assert list(filo_2) == ["b\n"]
    assert list(filo_3) == ["d\n"]
    assert list(filo_3) == []
    assert smistatore.prossimo() is None


def test_un_lavoro_che_non_e_un_dizionario_non_apre_un_file():
    smistatore = stanza_accesa.Smistatore(_righe({"lavoro": [1]}, "a\n", {"lavoro": "x"}))
    assert smistatore.prossimo() is None


def test_se_l_entrata_si_rompe_il_filo_si_chiude():

    class Rotta:

        def __iter__(self):
            yield json.dumps({"lavoro": {}}) + "\n"
            yield "a\n"
            raise OSError("rotta")

    smistatore = stanza_accesa.Smistatore(Rotta())
    lavoro_, filo = smistatore.prossimo()
    assert lavoro_ == {} and list(filo) == ["a\n"]
    assert smistatore.prossimo() is None


def test_un_filo_chiuso_non_prende_altro():
    filo = stanza_accesa.Filo()
    filo.metti("a")
    filo.chiudi()
    filo.metti("b")
    filo.chiudi()
    assert list(filo) == ["a"] and list(filo) == []


def _nella_stanza(monkeypatch, righe, codici, buoni=lambda: True):
    mandati: list = []
    fatti: list = []
    spenti: list = []
    monkeypatch.setattr(stanza, "_canale", lambda: None)
    monkeypatch.setattr(stanza, "manda_su", lambda canale: mandati.append)
    monkeypatch.setattr("sys.stdin", righe)
    codici = iter(codici)

    def un_lavoro(lavoro_, manda, entrata):
        fatti.append((lavoro_, list(entrata)))
        return next(codici)

    monkeypatch.setattr(stanza, "un_lavoro", un_lavoro)
    monkeypatch.setattr(motori, "_accesi", None)
    monkeypatch.setattr(motori, "caricati", 3)
    monkeypatch.setattr(motori, "ancora_buoni", buoni)
    monkeypatch.setattr(motori, "spegni_tutti", lambda: spenti.append(True))
    return stanza_accesa.main(), mandati, fatti, spenti


def test_la_stanza_accesa_fa_un_file_dopo_l_altro(monkeypatch):
    codice, mandati, fatti, spenti = _nella_stanza(monkeypatch, _righe(
        {"lavoro": {"n": 1}}, "x\n", {"chiuso": True}, {"lavoro": {"n": 2}}), [0, 0])
    assert codice == 0 and spenti == [True]
    assert fatti == [({"n": 1}, ["x\n"]), ({"n": 2}, [])]
    assert mandati == [{"accesa": True, "caricati": 3}] * 2
    assert motori._accesi == {}


def test_la_stanza_accesa_si_spegne_al_primo_guasto(monkeypatch):
    codice, mandati, fatti, spenti = _nella_stanza(monkeypatch, _righe(
        {"lavoro": {"n": 1}}, {"lavoro": {"n": 2}}), [1, 0])
    assert codice == 1 and mandati == [] and spenti == [True]
    assert [lavoro_ for lavoro_, _ in fatti] == [{"n": 1}]


def test_la_stanza_accesa_si_spegne_se_il_motore_e_diventato_stretto(monkeypatch):
    codice, mandati, fatti, spenti = _nella_stanza(monkeypatch, _righe(
        {"lavoro": {"n": 1}}, {"lavoro": {"n": 2}}), [0, 0], buoni=lambda: False)
    assert codice == 0 and mandati == [] and spenti == [True]
    assert [lavoro_ for lavoro_, _ in fatti] == [{"n": 1}]


def test_l_accesa_conta_solo_dopo_un_fatto(tmp_path, monkeypatch):
    finta = tmp_path / "stanza_finta_accesa.py"
    finta.write_text(
        "import json, sys\n"
        "for riga in sys.stdin:\n"
        "    lavoro = json.loads(riga).get('lavoro')\n"
        "    if lavoro is None:\n"
        "        continue\n"
        "    for messaggio in lavoro['manda']:\n"
        "        print(json.dumps(messaggio), flush=True)\n"
        "    if not any('fatto' in messaggio for messaggio in lavoro['manda']):\n"
        "        break\n", encoding="utf-8")
    monkeypatch.setenv("PYTHONPATH", str(tmp_path))
    monkeypatch.setattr(accesa, "resta_accesa", lambda da_fare: True)
    stanza_ = accesa.StanzaAccesa("stanza_finta_accesa")
    try:
        esito = _lancia(stanza_, {"manda": [{"accesa": True}, {"guasto": "rotto"},
                                            {"accesa": True}]})
        assert esito == {"guasto": "rotto"} and not stanza_.accesa
        esito = _lancia(stanza_, {"manda": [[1], {"fatto": {"a": 1}}, {"accesa": True,
                                                                  "caricati": 2}]})
        assert esito == {"fatto": {"a": 1}} and stanza_.accesa and stanza_.caricati == 2
    finally:
        stanza_.spegni()
