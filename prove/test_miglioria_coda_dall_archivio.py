from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from officina import registro
from officina.errori import ErroreOfficina
from officina.importazione import scansione
from officina.importazione.motore import Motore
from officina.miglioria import attesa, coda, da_guardare, lavoro, pezzi, scambio, sfida
from officina.miglioria import motori as motori_mg
from officina.modello import file_media
from officina.programma import archivio_sicuro
from officina.sicuro import accoglienza
from officina.sicuro import elenco as elenco_sicuro
from officina.sicuro.dall_archivio import (CHIUSO, CHIUSO_ADESSO, DIVERSA, NON_C_E, PERSA,
                                           SENZA_ARCHIVIO, SI_APRE, TROVATA, DallArchivio,
                                           Ricerca)
from prove import test_miglioria as miglioria_di_prova
from prove import test_sicuro_servizio as servizio_di_prova
from prove.test_miglioria import SCELTI, _riga, _scatto_di
from prove.test_miglioria_dall_archivio import _mai_in_chiaro
from prove.test_miglioria_sfida import _contato, _il_salto, _versione_finta
from prove.test_sicuro_dall_archivio import _Situazione, _impronta, _jpeg, _video
from prove.test_sicuro_servizio import ATTESA, LEGGERO, PAROLA, _finche

pytest.importorskip("av")

costo_leggero = servizio_di_prova.costo_leggero
casa = servizio_di_prova.casa
cartella = miglioria_di_prova.cartella
importato = miglioria_di_prova.importato

FOTO = "s/mare.jpg"
FILMATO = "s/onde.mp4"
SOLE = "s/sole.jpg"
ALTRA = "ab" * 32


@pytest.fixture
def solo_nell_archivio(archivio, casa, monkeypatch):
    dati = {FOTO: _jpeg(), FILMATO: _video("mpeg4"), SOLE: _jpeg(seme=5)}
    for relativo, contenuto in dati.items():
        casa.metti(relativo, contenuto)
    motore = Motore(archivio)
    motore.prepara([casa.foto])
    motore.esegui()
    casa.archivio.crea(PAROLA, costo=LEGGERO)
    casa.archivio.copia_tutto([casa.foto])
    _finche(casa.copiato)
    casa.con_la_chiavetta()
    misure = {}
    for relativo in (FOTO, FILMATO):
        misure[relativo] = os.stat(casa.foto / relativo)
        (casa.foto / relativo).unlink()
    situazione = _Situazione(casa)
    monkeypatch.setattr(archivio_sicuro, "per_le_foto", situazione.per_le_foto)
    return SimpleNamespace(archivio=archivio, casa=casa, dati=dati, misure=misure,
                           situazione=situazione)


def _metti(pronta, *relativi: str) -> coda.Esito:
    scatti = [_scatto_di(pronta.archivio, Path(relativo).name) for relativo in relativi]
    with pronta.archivio.scrittura() as connessione:
        return coda.metti(connessione, scatti)


def _finta(da_fare, al_passo, ricorda) -> dict:
    Path(da_fare["uscita"]).write_bytes(f"migliorata {da_fare['originale']}".encode())
    return {"fatto": {"larghezza": 1663, "altezza": 1247,
                      "motori": [{"nome": motori_mg.SEEDVR2, "versione": "x"}]}}


def _spia(lancia=None):
    visti: list = []

    def spia(da_fare, al_passo, ricorda):
        visti.append(da_fare)
        return (lancia or lavoro.lancia_la_stanza)(da_fare, al_passo, ricorda)

    spia.visti = visti
    return spia


def _gira(archivio, lancia=None, **piu) -> lavoro.Miglioratore:
    miglioratore = lavoro.Miglioratore(archivio, lancia=lancia, motori_scelti=SCELTI, **piu)
    assert miglioratore.parti()
    assert miglioratore.lavoro.aspetta_che_finisca(120)
    assert not miglioratore.lavoro.guasto, miglioratore.lavoro.dettaglio
    return miglioratore


def _stati(archivio) -> dict:
    return {Path(riga["percorso_originale"]).name: (riga["stato"], riga["guasto"])
            for riga in _riga(archivio)}


def _file_id(archivio, nome: str) -> int:
    with archivio.lettura() as connessione:
        return connessione.execute("SELECT file_id FROM percorsi WHERE nome = ?",
                                   (nome,)).fetchone()["file_id"]


def _percorsi(archivio, nome: str) -> list[str]:
    with archivio.lettura() as connessione:
        return [riga["percorso"] for riga in
                file_media.percorsi_di(connessione, _file_id(archivio, nome))]


def _avvisi(monkeypatch) -> list:
    avvisi: list = []
    monkeypatch.setattr(registro, "avviso",
                        lambda nome, **campi: avvisi.append((nome, campi)))
    return avvisi


def test_in_coda_entra_l_originale_che_sta_solo_nell_archivio(solo_nell_archivio):
    pronta = solo_nell_archivio
    esito = _metti(pronta, FOTO, SOLE)
    assert (esito.messi, esito.dall_archivio, esito.assenti) == (2, 1, [])
    assert esito.a_parole() == "2 in coda · 1 dall'Archivio sicuro"
    percorsi = {Path(riga["percorso_originale"]).name: riga["percorso_originale"]
                for riga in _riga(pronta.archivio, coda.IN_CODA)}
    assert percorsi == {"mare.jpg": _percorsi(pronta.archivio, "mare.jpg")[0],
                        "sole.jpg": _percorsi(pronta.archivio, "sole.jpg")[0]}
    assert Path(percorsi["mare.jpg"]) == pronta.casa.foto / FOTO


@pytest.mark.parametrize("forzata, campo, parole", [
    (CHIUSO, "chiusi", "1 sono solo nell'Archivio sicuro, che è chiuso"),
    (SI_APRE, "chiusi", "1 sono solo nell'Archivio sicuro, che è chiuso"),
    (SENZA_ARCHIVIO, "assenti", "1 non sono sul disco")])
def test_se_l_archivio_non_risponde_non_entra_in_coda_e_si_dice_perche(
        solo_nell_archivio, forzata, campo, parole):
    pronta = solo_nell_archivio
    pronta.situazione.forzata = forzata
    esito = _metti(pronta, FOTO)
    assert esito.messi == 0 and esito.dall_archivio == 0
    assert getattr(esito, campo) == ["mare.jpg"]
    assert esito.a_parole() == parole
    assert _riga(pronta.archivio) == []


def test_se_l_archivio_si_chiude_mentre_si_mette_in_coda_non_entra(solo_nell_archivio,
                                                                   monkeypatch):
    pronta = solo_nell_archivio
    monkeypatch.setattr(archivio_sicuro, "per_le_foto",
                        lambda: (TROVATA, pronta.casa.archivio))
    assert pronta.casa.archivio.chiudi(ATTESA)
    esito = _metti(pronta, FOTO)
    assert esito.chiusi == ["mare.jpg"] and esito.messi == 0


def test_una_versione_diversa_nell_archivio_non_entra_in_coda(solo_nell_archivio):
    pronta = solo_nell_archivio
    with pronta.archivio.scrittura() as connessione:
        connessione.execute("UPDATE file_media SET impronta = ? WHERE id = ?",
                            (ALTRA, _file_id(pronta.archivio, "mare.jpg")))
    esito = _metti(pronta, FOTO)
    assert esito.diversi == ["mare.jpg"] and esito.messi == 0
    assert esito.a_parole() == ("1 nell'Archivio sicuro hanno una versione diversa "
                                "dell'originale")


def test_senza_una_cartella_nell_archivio_non_entra_in_coda(solo_nell_archivio, tmp_path):
    pronta = solo_nell_archivio
    with pronta.archivio.scrittura() as connessione:
        connessione.execute("UPDATE percorsi SET percorso = ? WHERE file_id = ?",
                            (str(tmp_path / "altrove" / "mare.jpg"),
                             _file_id(pronta.archivio, "mare.jpg")))
    esito = _metti(pronta, FOTO)
    assert esito.senza_casa == ["mare.jpg"] and esito.messi == 0
    assert esito.a_parole() == ("1 sono nell'Archivio sicuro, ma non so in che cartella "
                                "stavano")
    with pronta.archivio.scrittura() as connessione:
        connessione.execute("UPDATE file_media SET impronta = ? WHERE id = ?",
                            (ALTRA, _file_id(pronta.archivio, "mare.jpg")))
    esito = _metti(pronta, FOTO)
    assert esito.assenti == ["mare.jpg"] and esito.senza_casa == []


def test_se_l_archivio_si_rompe_mentre_si_mette_in_coda_non_entra(solo_nell_archivio,
                                                                  monkeypatch):
    pronta = solo_nell_archivio

    def casa_rotta(*argomenti):
        raise ErroreOfficina("rotto", codice="occupato")

    monkeypatch.setattr(archivio_sicuro, "per_le_foto",
                        lambda: (TROVATA, SimpleNamespace(casa=casa_rotta)))
    avvisi = _avvisi(monkeypatch)
    esito = _metti(pronta, FOTO)
    assert esito.chiusi == ["mare.jpg"] and esito.messi == 0
    assert avvisi == [("sicuro.casa_non_trovata", {"motivo": "occupato"})]


def test_senza_impronta_non_si_chiede_all_archivio(solo_nell_archivio, monkeypatch):
    pronta = solo_nell_archivio
    file_id = _file_id(pronta.archivio, "mare.jpg")
    monkeypatch.setattr(archivio_sicuro, "per_le_foto", lambda: pytest.fail("chiesto"))
    with pronta.archivio.scrittura() as connessione:
        connessione.execute("UPDATE file_media SET impronta = '' WHERE id = ?", (file_id,))
        assert file_media.casa_nell_archivio(connessione, file_id) == (None, NON_C_E)
        assert file_media.casa_nell_archivio(connessione, 999_999) == (None, NON_C_E)
        assert file_media.date_nell_archivio(connessione, 999_999, Path("x")) is None
        assert file_media.date_nell_archivio(connessione, file_id, Path("x")) is None


@pytest.mark.parametrize("relativo", [FOTO, FILMATO])
def test_il_miglioramento_legge_l_originale_dall_archivio_e_non_lo_rimette_sul_disco(
        solo_nell_archivio, tmp_path, monkeypatch, relativo):
    pronta = solo_nell_archivio
    originale = pronta.casa.foto / relativo
    dati = pronta.dati[relativo]
    _metti(pronta, relativo)
    lati_chiesti: list = []
    vere_mancano = da_guardare.mancano

    def mancano(dove, numero, lati):
        lati_chiesti.append(set(lati))
        return vere_mancano(dove, numero, lati)

    monkeypatch.setattr(da_guardare, "mancano", mancano)
    adesso: list = []
    miglioratore = lavoro.Miglioratore(pronta.archivio, motori_scelti=SCELTI)

    def lancia(da_fare, al_passo, ricorda):
        adesso.append(dict(miglioratore.adesso))
        return lavoro.lancia_la_stanza(da_fare, al_passo, ricorda)

    spia = _spia(lancia)
    miglioratore._lancia = spia
    assert miglioratore.parti()
    assert miglioratore.lavoro.aspetta_che_finisca(120)
    assert not miglioratore.lavoro.guasto, miglioratore.lavoro.guasto

    [riga] = _riga(pronta.archivio, coda.DA_RIVEDERE)
    in_attesa = Path(riga["in_revisione"])
    assert in_attesa.parent == pronta.casa.foto / attesa.NOME
    assert not originale.exists()
    [da_fare] = spia.visti
    radice, = pronta.casa.radici()
    posto = pronta.casa.aperto.elenco.attuale(radice["id"], relativo)
    assert da_fare["date"] == {nome: posto.metadati[nome] for nome in accoglienza.DATE
                               if nome in posto.metadati}
    assert da_fare["date"]["modifica"] == pronta.misure[relativo].st_mtime_ns
    percorsi = _percorsi(pronta.archivio, originale.name)
    assert da_fare["dall_archivio"] == {"impronta": _impronta(dati), "dimensione": len(dati),
                                        "percorsi": percorsi, "nome": originale.name}
    assert da_fare["originale"] == str(originale)
    assert os.stat(in_attesa).st_mtime_ns == pronta.misure[relativo].st_mtime_ns
    assert adesso == [{"id": riga["id"], "nome": originale.name, "fatti": 0, "totale": 0,
                       "dall_archivio": True}]
    assert json.loads(riga["fedelta"])["fatto"]
    prima = da_guardare.percorso(pronta.archivio.dove, riga["id"], da_guardare.PRIMA)
    assert not prima.exists()
    assert lati_chiesti == ([{da_guardare.DOPO}] if relativo == FILMATO else [])
    _mai_in_chiaro(tmp_path, dati)
    if relativo == FILMATO:
        prova = tmp_path / "prova" / "onde.mp4"
        prova.parent.mkdir()
        prova.write_bytes(dati)
        assert da_guardare.da_fare({da_guardare.PRIMA: prova}) == [da_guardare.PRIMA]


def test_con_l_originale_sul_disco_non_si_chiede_all_archivio(solo_nell_archivio,
                                                              monkeypatch):
    pronta = solo_nell_archivio
    _metti(pronta, SOLE)
    adesso: list = []
    miglioratore = lavoro.Miglioratore(pronta.archivio, motori_scelti=SCELTI)

    def lancia(da_fare, al_passo, ricorda):
        adesso.append(dict(miglioratore.adesso))
        return _finta(da_fare, al_passo, ricorda)

    spia = _spia(lancia)
    miglioratore._lancia = spia
    monkeypatch.setattr(file_media, "cerca_nell_archivio", lambda *argomenti: pytest.fail())
    assert miglioratore.parti()
    assert miglioratore.lavoro.aspetta_che_finisca(120)
    assert not miglioratore.lavoro.guasto, miglioratore.lavoro.dettaglio
    [da_fare] = spia.visti
    assert "dall_archivio" not in da_fare and "date" not in da_fare
    assert [set(visto) for visto in adesso] == [{"id", "nome", "fatti", "totale"}]
    assert _stati(pronta.archivio) == {"sole.jpg": (coda.DA_RIVEDERE, None)}


def test_senza_la_riga_del_file_non_parte_anche_con_l_originale_sul_disco(
        solo_nell_archivio, monkeypatch):
    pronta = solo_nell_archivio
    _metti(pronta, SOLE)
    monkeypatch.setattr(file_media, "per_id", lambda *argomenti: None)
    spia = _spia(_finta)
    _gira(pronta.archivio, spia)
    assert spia.visti == []
    assert _stati(pronta.archivio) == {"sole.jpg": (coda.FALLITA, "originale_assente")}


def _poco_spazio(pronta, monkeypatch, relativo: str, di_piu: int) -> list:
    dove = pronta.casa.foto / attesa.NOME
    vero = shutil.disk_usage
    chiesti: list = []

    def disco(percorso):
        if Path(percorso) != dove:
            return vero(percorso)
        chiesti.append(percorso)
        serve = (len(pronta.dati[relativo]) * lavoro.QUANTO_PUO_CRESCERE
                 + lavoro.MARGINE_DI_SPAZIO)
        return vero(percorso)._replace(free=serve + di_piu)

    monkeypatch.setattr(lavoro.shutil, "disk_usage", disco)
    return chiesti


@pytest.mark.parametrize("di_piu, stato, guasto", [(-1, coda.FALLITA, "spazio"),
                                                   (0, coda.DA_RIVEDERE, None)])
def test_lo_spazio_si_conta_sulla_foto_letta_dall_archivio(solo_nell_archivio, monkeypatch,
                                                           di_piu, stato, guasto):
    pronta = solo_nell_archivio
    _metti(pronta, FOTO)
    chiesti = _poco_spazio(pronta, monkeypatch, FOTO, di_piu)
    _gira(pronta.archivio, _finta)
    assert chiesti
    assert _stati(pronta.archivio) == {"mare.jpg": (stato, guasto)}


@pytest.mark.parametrize("di_piu, riprese", [(-1, 0), (0, 1)])
def test_lucidflux_conta_lo_spazio_sulla_foto_letta_dall_archivio(solo_nell_archivio,
                                                                  monkeypatch, di_piu,
                                                                  riprese):
    pronta = solo_nell_archivio
    _fatta_da_seedvr2(pronta)
    chiesti = _poco_spazio(pronta, monkeypatch, FOTO, di_piu)
    spia = _spia(_versione_finta)
    miglioratore = _gira(pronta.archivio, spia, sfidanti_pronti=lambda: True)
    assert chiesti and len(spia.visti) == riprese
    poco = "«mare.jpg» resta solo di SeedVR2: manca spazio sul disco"
    assert (poco in miglioratore.lavoro.righe) == (not riprese)


def test_un_originale_cambiato_sul_disco_non_parte(solo_nell_archivio, monkeypatch):
    pronta = solo_nell_archivio
    _metti(pronta, SOLE)
    (pronta.casa.foto / SOLE).write_bytes(_jpeg(seme=9))
    monkeypatch.setattr(file_media, "cerca_nell_archivio", lambda *argomenti: pytest.fail())
    spia = _spia(_finta)
    _gira(pronta.archivio, spia)
    assert spia.visti == []
    assert _stati(pronta.archivio) == {"sole.jpg": (coda.FALLITA, "originale_cambiato")}


def test_lo_spazio_conta_i_pezzi_del_video_letto_dall_archivio(solo_nell_archivio,
                                                               monkeypatch):
    pronta = solo_nell_archivio
    _metti(pronta, FILMATO)
    dove = pronta.casa.foto / attesa.NOME
    vero = shutil.disk_usage
    chiesti: list = []

    def disco(percorso):
        if Path(percorso) != dove:
            return vero(percorso)
        chiesti.append(percorso)
        senza_pezzi = (len(pronta.dati[FILMATO]) * lavoro.QUANTO_PUO_CRESCERE
                       + lavoro.MARGINE_DI_SPAZIO)
        return vero(percorso)._replace(free=senza_pezzi)

    monkeypatch.setattr(lavoro.shutil, "disk_usage", disco)
    spia = _spia(_finta)
    _gira(pronta.archivio, spia)
    assert chiesti and spia.visti == []
    assert _stati(pronta.archivio) == {"onde.mp4": (coda.FALLITA, "spazio")}


def test_dal_disco_il_lavoro_resta_quello_di_prima(solo_nell_archivio):
    pronta = solo_nell_archivio
    _metti(pronta, SOLE)
    spia = _spia(_finta)
    miglioratore = lavoro.Miglioratore(pronta.archivio, lancia=spia, motori_scelti=SCELTI)
    assert miglioratore.parti()
    assert miglioratore.lavoro.aspetta_che_finisca(120)
    [da_fare] = spia.visti
    assert "dall_archivio" not in da_fare and "date" not in da_fare
    assert da_fare["originale"] == str(pronta.casa.foto / SOLE)


def test_le_copie_da_guardare_dei_video_dall_archivio_non_hanno_il_prima(
        importato, monkeypatch, tmp_path):
    chiesti: list = []
    monkeypatch.setattr(da_guardare, "mancano", lambda dove, numero, lati: list(lati))
    monkeypatch.setattr(da_guardare, "fai",
                        lambda dove, numero, lati, **piu: chiesti.append(dict(lati)))
    miglioratore = lavoro.Miglioratore(importato, motori_scelti=SCELTI)
    originale, finale = tmp_path / "onde.mov", tmp_path / "1-onde.mov"
    miglioratore._copie_da_guardare(1, originale, finale, dal_disco=False)
    miglioratore._copie_da_guardare(2, originale, finale)
    assert chiesti == [{da_guardare.DOPO: finale},
                       {da_guardare.DOPO: finale, da_guardare.PRIMA: originale}]


def test_con_l_archivio_chiuso_la_foto_resta_in_coda_e_le_altre_vanno_avanti(
        solo_nell_archivio, monkeypatch):
    pronta = solo_nell_archivio
    _metti(pronta, FOTO, SOLE)
    assert pronta.casa.archivio.chiudi(ATTESA)
    avvisi = _avvisi(monkeypatch)
    spia = _spia(_finta)
    miglioratore = _gira(pronta.archivio, spia)
    assert [Path(da_fare["originale"]).name for da_fare in spia.visti] == ["sole.jpg"]
    assert _stati(pronta.archivio) == {"mare.jpg": (coda.IN_CODA, CHIUSO_ADESSO),
                                       "sole.jpg": (coda.DA_RIVEDERE, None)}
    assert ("miglioria.aspetta_l_archivio", {"motivo": CHIUSO_ADESSO}) in avvisi
    assert f"«mare.jpg»: {lavoro.a_parole(CHIUSO_ADESSO)}" in miglioratore.lavoro.righe
    assert "resta in coda finché lo apri" in lavoro.a_parole(CHIUSO_ADESSO)

    pronta.casa.archivio.apri(PAROLA)
    di_nuovo = _spia(_finta)
    miglioratore._lancia = di_nuovo
    assert miglioratore.parti()
    assert miglioratore.lavoro.aspetta_che_finisca(120)
    assert not miglioratore.lavoro.guasto, miglioratore.lavoro.dettaglio
    assert [Path(da_fare["originale"]).name for da_fare in di_nuovo.visti] == ["mare.jpg"]
    assert _stati(pronta.archivio)["mare.jpg"] == (coda.DA_RIVEDERE, None)


@pytest.mark.parametrize("guasto", [CHIUSO_ADESSO, PERSA])
def test_se_l_archivio_si_chiude_a_meta_la_foto_resta_in_coda_coi_suoi_pezzi(
        solo_nell_archivio, guasto):
    pronta = solo_nell_archivio
    _metti(pronta, FILMATO, SOLE)
    cantieri: list = []

    def lancia(da_fare, al_passo, ricorda):
        if "dall_archivio" not in da_fare:
            return _finta(da_fare, al_passo, ricorda)
        cantiere = pezzi.cartella(Path(da_fare["uscita"]))
        cantiere.mkdir()
        (cantiere / "0.png").write_bytes(b"pezzo")
        cantieri.append(cantiere)
        Path(da_fare["uscita"]).write_bytes(b"a meta")
        return {"guasto": guasto}

    spia = _spia(lancia)
    miglioratore = _gira(pronta.archivio, spia)
    assert len(spia.visti) == 2
    assert _stati(pronta.archivio) == {"onde.mp4": (coda.IN_CODA, guasto),
                                       "sole.jpg": (coda.DA_RIVEDERE, None)}
    [cantiere] = cantieri
    assert (cantiere / "0.png").read_bytes() == b"pezzo"
    assert not Path(spia.visti[0]["uscita"]).exists()
    assert f"«onde.mp4»: {lavoro.a_parole(guasto)}" in miglioratore.lavoro.righe
    assert lavoro.a_parole(guasto) == lavoro.MESSAGGI[guasto]
    assert "resta in coda finché" in lavoro.a_parole(guasto)


def test_la_versione_diversa_si_dice_a_parole():
    assert lavoro.a_parole(DIVERSA) == lavoro.MESSAGGI[DIVERSA]
    assert "solo una versione diversa dell'originale" in lavoro.a_parole(DIVERSA)


@pytest.mark.parametrize("guasto", [DIVERSA, "originale_assente"])
def test_se_la_stanza_non_trova_l_originale_giusto_non_riesce_col_motivo(
        solo_nell_archivio, guasto):
    pronta = solo_nell_archivio
    _metti(pronta, FILMATO)
    cantieri: list = []

    def lancia(da_fare, al_passo, ricorda):
        cantiere = pezzi.cartella(Path(da_fare["uscita"]))
        cantiere.mkdir()
        cantieri.append(cantiere)
        return {"guasto": guasto}

    miglioratore = _gira(pronta.archivio, lancia)
    assert _stati(pronta.archivio) == {"onde.mp4": (coda.FALLITA, guasto)}
    assert not cantieri[0].exists()
    assert f"non riuscito: {lavoro.a_parole(guasto)}" in miglioratore.lavoro.righe


def _dall_archivio(pronta, nome: str = "mare.jpg", **cambi) -> DallArchivio:
    dati = pronta.dati[FOTO]
    voce = {"numero": "n", "nome": nome, "dimensione": len(dati),
            "blake2b": _impronta(dati), "intero": True, "diversa": False,
            "_prendi": lambda trovata: None, **cambi}
    return DallArchivio(**voce)


@pytest.mark.parametrize("come, stato, guasto", [
    ("chiuso", coda.IN_CODA, CHIUSO_ADESSO),
    ("si_apre", coda.IN_CODA, CHIUSO_ADESSO),
    ("non_c_e", coda.FALLITA, "originale_assente"),
    ("senza_archivio", coda.FALLITA, "originale_assente"),
    ("diversa", coda.FALLITA, DIVERSA),
    ("altra_impronta", coda.FALLITA, DIVERSA),
    ("rotto", coda.IN_CODA, CHIUSO_ADESSO),
    ("senza_date", coda.IN_CODA, CHIUSO_ADESSO),
])
def test_prima_di_partire_il_programma_controlla_l_originale_nell_archivio(
        solo_nell_archivio, monkeypatch, come, stato, guasto):
    pronta = solo_nell_archivio
    _metti(pronta, FOTO)
    ricerche = {"chiuso": Ricerca(CHIUSO), "si_apre": Ricerca(SI_APRE),
                "non_c_e": Ricerca(NON_C_E), "senza_archivio": Ricerca(SENZA_ARCHIVIO),
                "diversa": Ricerca(TROVATA, _dall_archivio(pronta, diversa=True)),
                "altra_impronta": Ricerca(TROVATA, _dall_archivio(pronta, blake2b=ALTRA))}

    def cerca(connessione, file_id):
        if come == "rotto":
            raise ErroreOfficina("rotto", codice="occupato")
        return ricerche.get(come, Ricerca(TROVATA, _dall_archivio(pronta)))

    monkeypatch.setattr(file_media, "cerca_nell_archivio", cerca)
    if come == "senza_date":
        monkeypatch.setattr(file_media, "date_nell_archivio", lambda *argomenti: None)
    avvisi = _avvisi(monkeypatch)
    spia = _spia(_finta)
    _gira(pronta.archivio, spia)
    assert spia.visti == []
    assert _stati(pronta.archivio) == {"mare.jpg": (stato, guasto)}
    assert (("miglioria.archivio_non_risponde", {"motivo": "occupato"}) in avvisi) == (
        come == "rotto")


def test_con_le_date_vuote_si_parte_lo_stesso(solo_nell_archivio, monkeypatch):
    pronta = solo_nell_archivio
    _metti(pronta, FOTO)
    monkeypatch.setattr(file_media, "date_nell_archivio", lambda *argomenti: {})
    spia = _spia(_finta)
    _gira(pronta.archivio, spia)
    [da_fare] = spia.visti
    assert da_fare["date"] == {}
    assert _stati(pronta.archivio) == {"mare.jpg": (coda.DA_RIVEDERE, None)}


def test_un_originale_cambiato_nel_database_non_parte(solo_nell_archivio):
    pronta = solo_nell_archivio
    _metti(pronta, FOTO)
    with pronta.archivio.scrittura() as connessione:
        connessione.execute("UPDATE file_media SET impronta = ? WHERE id = ?",
                            (ALTRA, _file_id(pronta.archivio, "mare.jpg")))
    spia = _spia(_finta)
    _gira(pronta.archivio, spia)
    assert spia.visti == []
    assert _stati(pronta.archivio) == {"mare.jpg": (coda.FALLITA, "originale_cambiato")}


def test_senza_il_file_nel_database_l_originale_manca(importato, tmp_path):
    miglioratore = lavoro.Miglioratore(importato, motori_scelti=SCELTI)
    riga = {"file_id": 999_999, "impronta_originale": ALTRA}
    assert miglioratore._originale(riga, tmp_path / "no.jpg") == (
        None, None, "originale_assente")


@pytest.mark.parametrize("quale", [motori_mg.SEEDVR2, motori_mg.LUCIDFLUX])
@pytest.mark.parametrize("guasto", [CHIUSO_ADESSO, PERSA])
def test_in_sfida_se_l_archivio_si_chiude_la_foto_resta_in_coda_senza_versioni(
        importato, cartella, quale, guasto):
    miglioria_di_prova._metti(importato, "piccola.jpg")

    def lancia(da_fare, al_passo, ricorda):
        if da_fare["motori"]["foto"] == quale:
            return {"guasto": guasto}
        return _versione_finta(da_fare, al_passo, ricorda)

    conta = _contato(lancia)
    miglioratore = _gira(importato, conta, sfidanti_pronti=lambda: True)
    fino = sfida.SFIDANTI.index(quale) + 1
    assert conta.chiamati == list(sfida.SFIDANTI[:fino])
    [riga] = _riga(importato)
    assert (riga["stato"], riga["guasto"]) == (coda.IN_CODA, guasto)
    assert not list((cartella / attesa.NOME).glob("*"))
    assert _il_salto(importato) is None
    with importato.lettura() as connessione:
        assert sfida.quante_fatte(connessione) == 0
    assert f"«piccola.jpg»: {lavoro.a_parole(guasto)}" in miglioratore.lavoro.righe


def _fatta_da_seedvr2(pronta):
    _metti(pronta, FOTO)
    _gira(pronta.archivio, _versione_finta)
    [riga] = _riga(pronta.archivio, coda.DA_RIVEDERE)
    with pronta.archivio.lettura() as connessione:
        assert [r["id"] for r in sfida.da_riprendere(connessione)] == [riga["id"]]
    return riga


def test_lucidflux_riprende_anche_la_foto_che_sta_solo_nell_archivio(solo_nell_archivio):
    pronta = solo_nell_archivio
    prima = _fatta_da_seedvr2(pronta)
    spia = _spia(_versione_finta)
    _gira(pronta.archivio, spia, sfidanti_pronti=lambda: True)
    [da_fare] = spia.visti
    assert da_fare["motori"]["foto"] == motori_mg.LUCIDFLUX
    assert da_fare["dall_archivio"]["nome"] == "mare.jpg"
    assert da_fare["date"]["modifica"] == pronta.misure[FOTO].st_mtime_ns
    with pronta.archivio.lettura() as connessione:
        assert sfida.per_miglioria(connessione, prima["id"]) is not None


def test_con_l_archivio_chiuso_lucidflux_non_riprende_e_non_conta_il_salto(
        solo_nell_archivio):
    pronta = solo_nell_archivio
    prima = _fatta_da_seedvr2(pronta)
    assert pronta.casa.archivio.chiudi(ATTESA)
    spia = _spia(_versione_finta)
    miglioratore = _gira(pronta.archivio, spia, sfidanti_pronti=lambda: True)
    assert spia.visti == []
    assert (f"«mare.jpg» resta solo di SeedVR2: {lavoro.a_parole(CHIUSO_ADESSO)}"
            in miglioratore.lavoro.righe)
    assert _il_salto(pronta.archivio) is None
    with pronta.archivio.lettura() as connessione:
        assert [r["id"] for r in sfida.da_riprendere(connessione)] == [prima["id"]]

    pronta.casa.archivio.apri(PAROLA)
    di_nuovo = _spia(_versione_finta)
    _gira(pronta.archivio, di_nuovo, sfidanti_pronti=lambda: True)
    assert [da_fare["motori"]["foto"] for da_fare in di_nuovo.visti] == [motori_mg.LUCIDFLUX]


@pytest.mark.parametrize("guasto", [CHIUSO_ADESSO, PERSA])
def test_se_l_archivio_si_chiude_mentre_lucidflux_riprende_non_conta_il_salto(
        solo_nell_archivio, guasto):
    pronta = solo_nell_archivio
    prima = _fatta_da_seedvr2(pronta)
    spia = _spia(lambda da_fare, al_passo, ricorda: {"guasto": guasto})
    miglioratore = _gira(pronta.archivio, spia, sfidanti_pronti=lambda: True)
    assert len(spia.visti) == 1
    assert (f"«mare.jpg» resta solo di SeedVR2: {lavoro.a_parole(guasto)}"
            in miglioratore.lavoro.righe)
    assert _il_salto(pronta.archivio) is None
    with pronta.archivio.lettura() as connessione:
        assert [r["id"] for r in sfida.da_riprendere(connessione)] == [prima["id"]]


@pytest.mark.parametrize("come", ["sparita", "fuori"])
def test_lucidflux_non_riprende_senza_la_versione_di_seedvr2_in_attesa(solo_nell_archivio,
                                                                       tmp_path, come):
    pronta = solo_nell_archivio
    prima = _fatta_da_seedvr2(pronta)
    tenuta = Path(prima["in_revisione"])
    if come == "sparita":
        tenuta.unlink()
    else:
        fuori = tmp_path / tenuta.name
        shutil.copy2(tenuta, fuori)
        with pronta.archivio.scrittura() as connessione:
            connessione.execute("UPDATE migliorie SET in_revisione = ? WHERE id = ?",
                                (str(fuori), prima["id"]))
    spia = _spia(_versione_finta)
    miglioratore = _gira(pronta.archivio, spia, sfidanti_pronti=lambda: True)
    assert spia.visti == []
    assert ("«mare.jpg» resta solo di SeedVR2: non trovo la foto o la versione di SeedVR2"
            in miglioratore.lavoro.righe)


def test_lucidflux_non_riprende_una_versione_cambiata_anche_con_l_archivio_chiuso(
        solo_nell_archivio):
    pronta = solo_nell_archivio
    prima = _fatta_da_seedvr2(pronta)
    Path(prima["in_revisione"]).write_bytes(b"cambiata")
    assert pronta.casa.archivio.chiudi(ATTESA)
    spia = _spia(_versione_finta)
    miglioratore = _gira(pronta.archivio, spia, sfidanti_pronti=lambda: True)
    assert spia.visti == []
    assert ("«mare.jpg» resta solo di SeedVR2: la foto è cambiata da quando SeedVR2 "
            "l'ha fatta" in miglioratore.lavoro.righe)


@pytest.mark.parametrize("come, perche", [
    ("diversa", lavoro.a_parole(DIVERSA)),
    ("cambiata", "la foto è cambiata da quando SeedVR2 l'ha fatta"),
    ("assente", "non trovo la foto o la versione di SeedVR2"),
])
def test_lucidflux_non_riprende_un_originale_che_non_torna(solo_nell_archivio,
                                                           monkeypatch, come, perche):
    pronta = solo_nell_archivio
    _fatta_da_seedvr2(pronta)
    if come == "diversa":
        monkeypatch.setattr(file_media, "cerca_nell_archivio", lambda *argomenti: Ricerca(
            TROVATA, _dall_archivio(pronta, diversa=True)))
    elif come == "cambiata":
        with pronta.archivio.scrittura() as connessione:
            connessione.execute("UPDATE file_media SET impronta = ? WHERE id = ?",
                                (ALTRA, _file_id(pronta.archivio, "mare.jpg")))
    else:
        monkeypatch.setattr(file_media, "cerca_nell_archivio",
                            lambda *argomenti: Ricerca(NON_C_E))
    spia = _spia(_versione_finta)
    miglioratore = _gira(pronta.archivio, spia, sfidanti_pronti=lambda: True)
    assert spia.visti == []
    assert f"«mare.jpg» resta solo di SeedVR2: {perche}" in miglioratore.lavoro.righe


def test_senza_la_cartella_importata_la_copia_aspetta_in_quella_del_programma(
        solo_nell_archivio):
    pronta = solo_nell_archivio
    shutil.rmtree(pronta.casa.foto)
    assert _metti(pronta, FOTO).messi == 1
    _gira(pronta.archivio, _finta)
    [riga] = _riga(pronta.archivio, coda.DA_RIVEDERE)
    in_attesa = Path(riga["in_revisione"])
    assert in_attesa.parent == pronta.archivio.dove.radice / attesa.NOME
    assert in_attesa.read_bytes().startswith(b"migliorata ")
    assert attesa.e_dentro(in_attesa)
    assert not pronta.casa.foto.exists()


def test_senza_la_sua_cartella_la_copia_aspetta_in_quella_importata(solo_nell_archivio):
    pronta = solo_nell_archivio
    shutil.rmtree(pronta.casa.foto / "s")
    _metti(pronta, FOTO)
    _gira(pronta.archivio, _finta)
    [riga] = _riga(pronta.archivio, coda.DA_RIVEDERE)
    assert Path(riga["in_revisione"]).parent == pronta.casa.foto / attesa.NOME
    assert not (pronta.casa.foto / "s").exists()


def test_la_cartella_di_attesa_non_ricrea_le_cartelle_cancellate(archivio, tmp_path,
                                                                 monkeypatch):
    importata = tmp_path / "importata"
    (importata / "a").mkdir(parents=True)
    riserva = tmp_path / "programma"
    riserva.mkdir()
    with archivio.scrittura() as connessione:
        scansione.aggiungi_cartella(connessione, importata)
        assert attesa.cartella(connessione, importata / "a" / "x.jpg",
                               riserva) == importata / attesa.NOME
        assert attesa.cartella(connessione, importata / "b" / "x.jpg",
                               riserva) == importata / attesa.NOME
        assert attesa.cartella(connessione, tmp_path / "fuori" / "x.jpg",
                               riserva) == riserva / attesa.NOME
        assert attesa.cartella(connessione, tmp_path / "fuori" / "x.jpg") == (
            tmp_path / "fuori" / attesa.NOME)
        assert attesa.cartella(connessione, tmp_path / "x.jpg",
                               riserva) == tmp_path / attesa.NOME
        monkeypatch.setattr(attesa, "_stesso_disco", lambda una, altra: False)
        assert attesa.cartella(connessione, importata / "a" / "x.jpg",
                               riserva) == importata / "a" / attesa.NOME
        assert attesa.cartella(connessione, importata / "b" / "x.jpg",
                               riserva) == importata / attesa.NOME
        shutil.rmtree(importata)
        assert attesa.cartella(connessione, importata / "a" / "x.jpg",
                               riserva) == riserva / attesa.NOME
    with pytest.raises(FileNotFoundError):
        attesa.prepara(tmp_path / "fuori" / attesa.NOME)
    assert not (tmp_path / "fuori").exists()
    assert attesa.prepara(riserva / attesa.NOME).is_dir()
    assert attesa.prepara(riserva / attesa.NOME).is_dir()


def _in_riserva(pronta, stato: str):
    shutil.rmtree(pronta.casa.foto)
    _metti(pronta, FILMATO)
    [riga] = _riga(pronta.archivio, coda.IN_CODA)
    with pronta.archivio.scrittura() as connessione:
        coda.segna(connessione, riga["id"], stato)
    dove = attesa.prepara(pronta.archivio.dove.radice / attesa.NOME)
    parziale = dove / f"{riga['id']}-onde.mp4{attesa.PARZIALE}"
    parziale.write_bytes(b"a meta")
    cantiere = pezzi.cartella(dove / f"{riga['id']}-onde.mp4{attesa.PARZIALE}")
    cantiere.mkdir()
    return riga, parziale, cantiere


def test_riparare_toglie_i_pezzi_lasciati_nella_cartella_del_programma(solo_nell_archivio):
    pronta = solo_nell_archivio
    riga, parziale, cantiere = _in_riserva(pronta, coda.IN_LAVORO)
    assert scambio.ripara(pronta.archivio)["riprese"] == 1
    assert not parziale.exists()
    assert _stati(pronta.archivio) == {"onde.mp4": (coda.IN_CODA, None)}


def test_se_non_parte_butta_i_pezzi_nella_cartella_del_programma(solo_nell_archivio,
                                                                 monkeypatch):
    pronta = solo_nell_archivio
    riga, parziale, cantiere = _in_riserva(pronta, coda.IN_CODA)
    trovata = _dall_archivio(pronta, nome="onde.mp4", diversa=True)
    monkeypatch.setattr(file_media, "cerca_nell_archivio",
                        lambda *argomenti: Ricerca(TROVATA, trovata))
    spia = _spia(_finta)
    _gira(pronta.archivio, spia)
    assert spia.visti == [] and not cantiere.exists()
    assert _stati(pronta.archivio) == {"onde.mp4": (coda.FALLITA, DIVERSA)}


def test_non_riuscito_butta_i_pezzi_nella_cartella_del_programma(solo_nell_archivio):
    pronta = solo_nell_archivio
    riga, parziale, cantiere = _in_riserva(pronta, coda.IN_CODA)
    _gira(pronta.archivio, lambda da_fare, al_passo, ricorda: {"guasto": "rotto"})
    assert not cantiere.exists()
    assert _stati(pronta.archivio) == {"onde.mp4": (coda.FALLITA, "rotto")}


def test_togliere_dalla_coda_butta_i_pezzi_nella_cartella_del_programma(
        solo_nell_archivio):
    from fastapi.testclient import TestClient

    from officina.web.server import app

    pronta = solo_nell_archivio
    riga, parziale, cantiere = _in_riserva(pronta, coda.IN_CODA)
    cliente = TestClient(app, client=("127.0.0.1", 51000))
    risposta = cliente.post(f"/miglioramento/{riga['id']}/togli", follow_redirects=False)
    assert risposta.status_code == 303
    assert not cantiere.exists()
    assert _riga(pronta.archivio) == []


def test_la_prossima_salta_quelle_che_aspettano(importato):
    miglioria_di_prova._metti(importato, "piccola.jpg", "breve.MOV")
    prima, seconda = (riga["id"] for riga in _riga(importato))
    with importato.lettura() as connessione:
        assert coda.prossima(connessione)["id"] == prima
        assert coda.prossima(connessione, {prima})["id"] == seconda
        assert coda.prossima(connessione, [str(prima)])["id"] == seconda
        assert coda.prossima(connessione, {seconda})["id"] == prima
        assert coda.prossima(connessione, {prima, seconda}) is None


def _posto(contenuto: str, metadati: dict, percorso: str = "s/mare.jpg",
           sparito: float | None = None) -> elenco_sicuro.Posto:
    return elenco_sicuro.Posto(chiave=contenuto + percorso, radice="r", percorso=percorso,
                               tipo="file", contenuto=contenuto, metadati=metadati,
                               segni=(), visto=1.0, sparito=sparito)


class _Elenco:

    def __init__(self, posti, tolta: bool = False, radice: str = "/foto"):
        self.posti = posti
        self.tolta = tolta
        self.radice = radice

    def con_impronta(self, impronta, dimensione):
        return ["buono"] if (impronta, dimensione) == ("i", 3) else []

    def radici(self):
        return [{"id": "r", "percorso": self.radice, "tolta": self.tolta}]

    def storia(self, radice, relativo):
        return [posto for posto in self.posti if posto.percorso == relativo]


def test_le_date_sono_quelle_del_posto_dell_originale():
    date = {"modifica": 5, "accesso": 6, "creazione": 7, "altro": 8}
    assert accoglienza.date(_Elenco([_posto("buono", date)]), "i", 3,
                            "/foto/s/mare.jpg") == {"modifica": 5, "accesso": 6,
                                                    "creazione": 7}
    assert accoglienza.date(_Elenco([_posto("buono", {"modifica": 5, "accesso": "6",
                                                      "creazione": 7.0})]),
                            "i", 3, "/foto/s/mare.jpg") == {"modifica": 5}
    assert accoglienza.date(_Elenco([_posto("buono", {"modifica": True, "accesso": 6})]),
                            "i", 3, "/foto/s/mare.jpg") == {"accesso": 6}
    storia = [_posto("buono", {"modifica": 1}, sparito=2.0),
              _posto("buono", {"modifica": 2}), _posto("altro", {"modifica": 3})]
    assert accoglienza.date(_Elenco(storia), "i", 3, "/foto/s/mare.jpg") == {"modifica": 2}
    assert accoglienza.date(_Elenco([_posto("altro", date)]), "i", 3,
                            "/foto/s/mare.jpg") == {}
    assert accoglienza.date(_Elenco([_posto("buono", date)]), "x", 3,
                            "/foto/s/mare.jpg") == {}
    assert accoglienza.date(_Elenco([_posto("buono", date)], tolta=True), "i", 3,
                            "/foto/s/mare.jpg") == {}
    assert accoglienza.date(_Elenco([_posto("buono", date)]), "i", 3,
                            "/altrove/s/mare.jpg") == {}
    assert accoglienza.date(_Elenco([_posto("buono", date)]), "i", 3, "/foto") == {}
    assert accoglienza.date(_Elenco([_posto("buono", date, percorso="s/mare.jpg")],
                                    radice="/foto/"), "i", 3, "/foto/s/mare.jpg") == {
        "modifica": 5, "accesso": 6, "creazione": 7}


def test_l_archivio_da_le_date_solo_se_e_aperto(solo_nell_archivio, monkeypatch):
    pronta = solo_nell_archivio
    dati = pronta.dati[FOTO]
    originale = str(pronta.casa.foto / FOTO)
    archivio = pronta.casa.archivio
    date = archivio.date(_impronta(dati), len(dati), originale)
    assert date["modifica"] == pronta.misure[FOTO].st_mtime_ns
    assert set(date) <= set(accoglienza.DATE) and "accesso" in date
    assert archivio.date(ALTRA, len(dati), originale) == {}
    aperto = archivio.apertura

    def rotto(*argomenti):
        raise ErroreOfficina("rotto", codice="occupato")

    monkeypatch.setattr(aperto, "date", rotto)
    with pytest.raises(ErroreOfficina):
        archivio.date(_impronta(dati), len(dati), originale)
    monkeypatch.undo()
    monkeypatch.setattr(aperto, "_spento", True)
    assert archivio.date(_impronta(dati), len(dati), originale) is None
    monkeypatch.undo()
    assert archivio.chiudi(ATTESA)
    assert archivio.date(_impronta(dati), len(dati), originale) is None


def test_nel_programma_le_date_si_chiedono_all_archivio_aperto(solo_nell_archivio):
    pronta = solo_nell_archivio
    file_id = _file_id(pronta.archivio, "mare.jpg")
    originale = pronta.casa.foto / FOTO
    with pronta.archivio.scrittura() as connessione:
        date = file_media.date_nell_archivio(connessione, file_id, originale)
        assert date["modifica"] == pronta.misure[FOTO].st_mtime_ns
        assert file_media.casa_nell_archivio(connessione, file_id) == (originale, TROVATA)
        connessione.execute("UPDATE file_media SET dimensione = dimensione + 1 WHERE id = ?",
                            (file_id,))
        assert file_media.date_nell_archivio(connessione, file_id, originale) == {}
        pronta.situazione.forzata = CHIUSO
        assert file_media.date_nell_archivio(connessione, file_id, originale) is None
