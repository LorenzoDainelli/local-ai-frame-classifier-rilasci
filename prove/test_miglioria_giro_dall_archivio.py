from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from officina.miglioria import catena, coda, lavoro, mezzi, motori, veloce
from prove import test_miglioria_coda_dall_archivio as coda_di_prova
from prove.test_miglioria import _riga
from prove.test_miglioria_coda_dall_archivio import FOTO, SOLE, _metti
from prove.test_miglioria_dall_archivio import _mai_in_chiaro
from prove.test_miglioria_giro_lucidflux import FintoLucid, FintoSeed
from prove.test_sicuro_dall_archivio import _impronta
from prove.test_sicuro_servizio import ATTESA, PAROLA

pytest.importorskip("av")

costo_leggero = coda_di_prova.costo_leggero
casa = coda_di_prova.casa
cartella = coda_di_prova.cartella
importato = coda_di_prova.importato
solo_nell_archivio = coda_di_prova.solo_nell_archivio

SCELTI = {"foto": motori.LUCIDFLUX, "video": motori.FINTO, "volti": None}
PNG = b"\x89PNG"


@pytest.fixture
def finti(monkeypatch):
    monkeypatch.setitem(motori.FOTO, motori.LUCIDFLUX,
                        "prove.test_miglioria_giro_lucidflux:FintoLucid")
    monkeypatch.setitem(motori.FOTO, motori.SEEDVR2,
                        "prove.test_miglioria_giro_lucidflux:FintoSeed")


def _immagine() -> Image.Image:
    return Image.effect_noise((97, 61), 80).convert("RGB")


def test_il_mezzo_cifrato_torna_uguale_bit_per_bit_e_sul_disco_non_c_e_in_chiaro(tmp_path):
    immagine = _immagine()
    chiave = mezzi.chiave_nuova()
    suo = mezzi.timbro("a" * 64, "lucidflux", "v", (10, 6), (97, 61))
    assert mezzi.scrivi(tmp_path, 7, immagine, suo, {"nome": "lucidflux"}, {"s": 1}, chiave)
    assert sorted(file.name for file in tmp_path.iterdir()) == ["7.sicuro"]
    cifrati = mezzi.cifrato(tmp_path, 7).read_bytes()
    assert PNG not in cifrati and b"a" * 64 not in cifrati and b"lucidflux" not in cifrati
    letta, usato, misura_ = mezzi.leggi(tmp_path, 7, suo, chiave)
    assert letta.tobytes() == immagine.tobytes() and letta.mode == "RGB"
    assert usato == {"nome": "lucidflux"} and misura_ == {"s": 1}
    assert mezzi.c_e(tmp_path, 7, "a" * 64, "v", chiave)
    assert not mezzi.c_e(tmp_path, 7, "a" * 64, "v")
    assert not mezzi.c_e(tmp_path, 7, "a" * 64, "v", mezzi.chiave_nuova())
    assert mezzi.leggi(tmp_path, 7, suo, mezzi.chiave_nuova()) is None
    assert mezzi.leggi(tmp_path, 7, suo) is None
    assert mezzi.leggi(tmp_path, 7, dict(suo, impronta="b" * 64), chiave) is None


def test_un_mezzo_cifrato_toccato_o_spostato_non_si_usa(tmp_path):
    immagine = _immagine()
    chiave = mezzi.chiave_nuova()
    suo = mezzi.timbro("a" * 64, "lucidflux", "v", (10, 6), (97, 61))
    assert mezzi.scrivi(tmp_path, 3, immagine, suo, {}, {}, chiave)
    dove = mezzi.cifrato(tmp_path, 3)
    buono = dove.read_bytes()
    for posto in (0, 12, len(buono) // 2, len(buono) - 1):
        dove.write_bytes(buono[:posto] + bytes([buono[posto] ^ 1]) + buono[posto + 1:])
        assert mezzi.leggi(tmp_path, 3, suo, chiave) is None
    dove.write_bytes(buono[:-5])
    assert mezzi.leggi(tmp_path, 3, suo, chiave) is None
    mezzi.cifrato(tmp_path, 4).write_bytes(buono)
    assert mezzi.leggi(tmp_path, 4, suo, chiave) is None
    assert mezzi.butta_i_cifrati(tmp_path) == 2
    assert not any(tmp_path.iterdir())


def test_il_mezzo_cifrato_si_butta_e_si_pulisce_come_gli_altri(tmp_path):
    chiave = mezzi.chiave_nuova()
    suo = mezzi.timbro("a", "l", "v", (2, 2), (4, 4))
    immagine = Image.new("RGB", (4, 4), (1, 2, 3))
    assert mezzi.scrivi(tmp_path, 1, immagine, suo, {}, {}, chiave)
    assert mezzi.scrivi(tmp_path, 2, immagine, suo, {}, {})
    assert mezzi.pulisci(tmp_path, {2}) == 1
    assert mezzi.scrivi(tmp_path, 2, immagine, suo, {}, {}, chiave)
    assert sorted(file.name for file in tmp_path.iterdir()) == ["2.sicuro"]
    mezzi.butta(tmp_path, 2)
    assert not any(tmp_path.iterdir())


def _stanza(lavori: list, prima=None):
    def lancia(da_fare, al_passo, ricorda):
        lavori.append(json.loads(json.dumps(da_fare)))
        if prima is not None:
            prima(da_fare)
        return lavoro.lancia_la_stanza(da_fare, al_passo, ricorda,
                                       modulo="prove.stanza_coi_finti")

    return lancia


def _giro(giri: list, prima=None, dopo=None):
    def lancia_il_giro(da_fare, al_passo, ricorda):
        giri.append(json.loads(json.dumps(da_fare)))
        if prima is not None:
            prima()
        esito = lavoro.lancia_la_stanza(da_fare, al_passo, ricorda,
                                        modulo="prove.giro_coi_finti")
        giri[-1]["esito"] = esito
        if dopo is not None:
            dopo()
        return esito

    return lancia_il_giro


def _gira(archivio, lancia, lancia_il_giro, acceso=True) -> lavoro.Miglioratore:
    archivio.imposta(veloce.CHIAVE, {veloce.SCRITTURA: False,
                                     veloce.GIRO_LUCIDFLUX: acceso})
    miglioratore = lavoro.Miglioratore(archivio, lancia=lancia, motori_scelti=SCELTI,
                                       sfidanti_pronti=lambda: False,
                                       lancia_il_giro=lancia_il_giro)
    assert miglioratore.parti()
    assert miglioratore.lavoro.aspetta_che_finisca(240)
    assert not miglioratore.lavoro.guasto, miglioratore.lavoro.dettaglio
    return miglioratore


def _uscite(archivio) -> dict:
    return {Path(riga["percorso_originale"]).name: Path(riga["in_revisione"]).read_bytes()
            for riga in _riga(archivio, coda.DA_RIVEDERE)}


def _di_prima(solo_nell_archivio, tmp_path, finti) -> dict:
    fatte = {}
    for relativo in (FOTO, SOLE):
        originale = tmp_path / "prima" / Path(relativo).name
        originale.parent.mkdir(parents=True, exist_ok=True)
        originale.write_bytes(solo_nell_archivio.dati[relativo])
        uscita = tmp_path / "prima" / f"fatta-{originale.name}"
        catena.foto({"genere": "immagine", "originale": str(originale),
                     "uscita": str(uscita), "motori": SCELTI, "misura": "4k"})
        fatte[originale.name] = uscita.read_bytes()
    return fatte


def _solo_cifrati(cartella_mezzi: Path, dati: bytes, impronta: str) -> list[str]:
    nomi = []
    for file in cartella_mezzi.iterdir() if cartella_mezzi.is_dir() else []:
        contenuto = file.read_bytes()
        assert dati not in contenuto and impronta.encode() not in contenuto
        nomi.append(file.name)
    return sorted(nomi)


def test_col_giro_la_foto_solo_nell_archivio_esce_uguale_e_il_mezzo_e_cifrato(
        solo_nell_archivio, tmp_path, finti):
    pronta = solo_nell_archivio
    attese = _di_prima(pronta, tmp_path, finti)
    _metti(pronta, FOTO, SOLE)
    dati = pronta.dati[FOTO]
    impronta = _impronta(dati)
    cartella_mezzi = mezzi.cartella(pronta.archivio.dove)
    visti: list = []
    lavori: list = []
    giri: list = []
    _gira(pronta.archivio,
          _stanza(lavori, lambda _da_fare: visti.append(
              _solo_cifrati(cartella_mezzi, dati, impronta))), _giro(giri))
    assert len(giri) == 1
    assert giri[0]["esito"]["fatto"]["mezzi"] == {
        str(cosa["id"]): "fatto" for cosa in giri[0]["giro"]}
    assert sum(1 for cosa in giri[0]["giro"] if "dall_archivio" in cosa) == 1
    nell_archivio = [fatto for fatto in lavori if fatto.get("dall_archivio")]
    sul_disco = [fatto for fatto in lavori if not fatto.get("dall_archivio")]
    assert len(nell_archivio) == len(sul_disco) == 1
    assert nell_archivio[0]["mezzo"]["chiave"] == giri[0]["chiave_dei_mezzi"]
    assert "chiave" not in sul_disco[0]["mezzo"]
    assert any(nome.endswith(".sicuro") for nome in visti[0])
    assert not any(nome.endswith(".png") and nome.split(".")[0] == str(
        nell_archivio[0]["mezzo"]["id"]) for nomi in visti for nome in nomi)
    assert _uscite(pronta.archivio) == {
        Path(FOTO).name: attese[Path(FOTO).name], Path(SOLE).name: attese[Path(SOLE).name]}
    assert not any(cartella_mezzi.iterdir())
    _mai_in_chiaro(pronta.archivio.dove.radice, dati)


def test_un_mezzo_cifrato_rovinato_si_vede_e_la_foto_si_rifa_senza(
        solo_nell_archivio, tmp_path, finti):
    pronta = solo_nell_archivio
    attese = _di_prima(pronta, tmp_path, finti)
    _metti(pronta, FOTO)

    def rovina(da_fare) -> None:
        mezzo = da_fare.get("mezzo")
        if mezzo:
            dove = mezzi.cifrato(Path(mezzo["cartella"]), mezzo["id"])
            buono = dove.read_bytes()
            dove.write_bytes(buono[:40] + bytes([buono[40] ^ 1]) + buono[41:])

    lavori: list = []
    _gira(pronta.archivio, _stanza(lavori, rovina), _giro([]))
    assert [bool(fatto.get("mezzo")) for fatto in lavori] == [True, False]
    assert _uscite(pronta.archivio) == {Path(FOTO).name: attese[Path(FOTO).name]}
    assert not any(mezzi.cartella(pronta.archivio.dove).iterdir())


def test_se_l_archivio_si_chiude_dopo_il_giro_il_mezzo_cifrato_si_butta(
        solo_nell_archivio, tmp_path, finti):
    pronta = solo_nell_archivio
    attese = _di_prima(pronta, tmp_path, finti)
    _metti(pronta, FOTO)
    cartella_mezzi = mezzi.cartella(pronta.archivio.dove)
    rimasti: list = []

    def chiudi_e_riapri() -> None:
        rimasti.append(sorted(file.name for file in cartella_mezzi.iterdir()))
        assert pronta.casa.archivio.chiudi(ATTESA)
        pronta.casa.archivio.apri(PAROLA)

    lavori: list = []
    giri: list = []
    _gira(pronta.archivio, _stanza(lavori), _giro(giri, dopo=chiudi_e_riapri))
    assert [nome.endswith(".sicuro") for nome in rimasti[0]] == [True]
    assert [fatto.get("mezzo") for fatto in lavori] == [None]
    assert _uscite(pronta.archivio) == {Path(FOTO).name: attese[Path(FOTO).name]}
    assert not any(cartella_mezzi.iterdir())


def test_con_l_archivio_chiuso_il_giro_si_ferma_e_non_lascia_niente(
        solo_nell_archivio, tmp_path, finti):
    pronta = solo_nell_archivio
    _metti(pronta, FOTO)
    cartella_mezzi = mezzi.cartella(pronta.archivio.dove)

    def chiudi() -> None:
        assert pronta.casa.archivio.chiudi(ATTESA)

    lavori: list = []
    giri: list = []
    _gira(pronta.archivio, _stanza(lavori), _giro(giri, prima=chiudi))
    assert len(giri) == 1 and "guasto" in giri[0]["esito"]
    assert lavori == []
    assert not cartella_mezzi.is_dir() or not any(cartella_mezzi.iterdir())
    [riga] = _riga(pronta.archivio)
    assert riga["stato"] == coda.IN_CODA
    _mai_in_chiaro(pronta.archivio.dove.radice, pronta.dati[FOTO])


def test_spento_la_foto_solo_nell_archivio_si_fa_come_prima(solo_nell_archivio, tmp_path,
                                                             finti):
    pronta = solo_nell_archivio
    attese = _di_prima(pronta, tmp_path, finti)
    _metti(pronta, FOTO)
    lavori: list = []
    giri: list = []
    _gira(pronta.archivio, _stanza(lavori), _giro(giri), acceso=False)
    assert giri == [] and [fatto.get("mezzo") for fatto in lavori] == [None]
    assert _uscite(pronta.archivio) == {Path(FOTO).name: attese[Path(FOTO).name]}


__all__ = ["FintoLucid", "FintoSeed", "cartella", "casa", "costo_leggero", "importato"]
