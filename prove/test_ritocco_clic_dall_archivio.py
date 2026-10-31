from __future__ import annotations

import base64
import dataclasses
import io
import os
from pathlib import Path

import numpy
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from officina.errori import ErroreOfficina
from officina.miglioria import attesa, metadati
from officina.modello import file_media
from officina.programma import archivio_sicuro
from officina.ritocco import copia, elenco, scelta, strumento
from officina.sicuro import dall_archivio, sportello
from officina.sicuro.dall_archivio import (CHIUSO, NON_C_E, PERSA, SENZA_ARCHIVIO, SI_APRE,
                                           TROVATA, DallArchivio, Ricerca)
from officina.web import in_disparte, lavori
from officina.web import ritocco as ritocco_web
from officina.web.strade import ritocco as ritocco_strade
from prove import sceglitore_finto
from prove import test_miglioria_mostra_dall_archivio as mostra
from prove import test_ritocco_dall_archivio as ritocco_di_prova
from prove.test_miglioria_coda_dall_archivio import FOTO, SOLE, _file_id
from prove.test_ritocco_dall_archivio import (ALTRA_ZONA, ZONA, _attivi, _falliti,
                                              _in_attesa, _metti, _ritoccata, _storia)
from prove.test_sicuro_dall_archivio import _impronta, _rovina, _stacca
from prove.test_sicuro_servizio import ATTESA

pytest.importorskip("av")

costo_leggero = ritocco_di_prova.costo_leggero
casa = ritocco_di_prova.casa
cartella = ritocco_di_prova.cartella
importato = ritocco_di_prova.importato
solo_nell_archivio = ritocco_di_prova.solo_nell_archivio
pronta = ritocco_di_prova.pronta
scena = ritocco_di_prova.scena

JSON = {"accept": "application/json"}
IN_MEZZO = [{"x": 0.5, "y": 0.5}]
LARGA, ALTA = 96, 64


@pytest.fixture(autouse=True)
def turno_pulito():
    yield
    ritocco_web.al_clic.chiudi()
    if lavori.turno.chi is not None:
        lavori.turno.lascia(lavori.turno.chi)


@pytest.fixture
def sam3(tmp_path) -> Path:
    dove = tmp_path / "sam3"
    dove.mkdir()
    return dove


@pytest.fixture
def clic(sam3, monkeypatch):
    nuovo = ritocco_web.AlClic("prove.sceglitore_finto:Finto")
    monkeypatch.setattr(ritocco_strade, "_cartella_di_sam3", lambda: sam3)
    monkeypatch.setattr(ritocco_web, "al_clic", nuovo)
    yield nuovo
    nuovo.chiudi()


@pytest.fixture
def cliente(scena, clic):
    from officina.web.server import app

    return TestClient(app, client=("127.0.0.1", 51000))


def _fermato(fare) -> ErroreOfficina:
    with pytest.raises(ErroreOfficina) as preso:
        fare()
    return preso.value


def _png(maschera) -> str:
    scritto = io.BytesIO()
    pixel = numpy.asarray(maschera, dtype=numpy.uint8) * 255
    Image.fromarray(pixel, "L").save(scritto, "PNG")
    return base64.b64encode(scritto.getvalue()).decode("ascii")


def _da_salvare(zona=ZONA, larga: int = LARGA, alta: int = ALTA) -> dict:
    maschera = numpy.zeros((alta, larga), dtype=bool)
    sinistra, sopra, destra, sotto = zona
    maschera[sopra:sotto, sinistra:destra] = True
    return {"larghezza": larga, "altezza": alta,
            "pezzi": [{"cosa": elenco.OGGETTO, "png": _png(maschera), "quadretto": None,
                       "volto": None, "corpo": None, "punti": None, "riquadro": None}]}


def test_lo_scatto_solo_nell_archivio_si_guarda_dall_archivio(scena):
    percorso, chiave = ritocco_strade._da_guardare(scena.file_id)
    dati = scena.dati[FOTO]
    assert isinstance(percorso, DallArchivio)
    assert (percorso.blake2b, percorso.dimensione, percorso.intero) == (
        _impronta(dati), len(dati), True)
    assert percorso.name == "mare.jpg" and not percorso.diversa
    assert chiave == _impronta(dati)
    with percorso.apri() as letto:
        assert letto.read() == dati


def test_dopo_un_ritocco_si_guarda_lo_scatto_senza_ritocchi_dell_archivio(scena):
    _metti(scena)
    riga = _ritoccata(scena)
    percorso, chiave = ritocco_strade._da_guardare(scena.file_id)
    assert isinstance(percorso, DallArchivio)
    assert percorso.blake2b == riga["impronta_base"] == _impronta(scena.dati[FOTO])
    assert chiave == riga["impronta_base"] != riga["impronta_copia"]
    with percorso.apri() as letto:
        assert letto.read() == scena.dati[FOTO]


def test_la_migliorata_solo_nell_archivio_si_guarda_dall_archivio(scena):
    migliorata = mostra._approvata(scena)
    percorso, chiave = ritocco_strade._da_guardare(scena.file_id)
    dati = mostra.MIGLIORATA[FOTO]
    assert migliorata["nell_archivio"] == 1
    assert isinstance(percorso, DallArchivio) and percorso.blake2b == _impronta(dati)
    assert chiave == _impronta(dati)
    _metti(scena)
    percorso, chiave = ritocco_strade._da_guardare(scena.file_id)
    assert percorso.blake2b == chiave == _impronta(dati)


@pytest.mark.parametrize("perche, messaggio", [
    (NON_C_E, copia.MIGLIORATA_PERSA),
    (dall_archivio.DIVERSA, copia.MIGLIORATA_PERSA),
    (CHIUSO, copia.SOLO_NELL_ARCHIVIO)])
def test_se_la_migliorata_non_si_trova_non_si_guarda_l_originale(scena, monkeypatch, perche,
                                                                 messaggio):
    migliorata = mostra._approvata(scena)
    vera = file_media.cerca_uguale

    def cerca(connessione, file_id, impronta, percorso, **altro):
        if impronta == migliorata["impronta_migliorata"]:
            return Ricerca(perche)
        return vera(connessione, file_id, impronta, percorso, **altro)

    monkeypatch.setattr(file_media, "cerca_uguale", cerca)
    errore = _fermato(lambda: ritocco_strade._da_guardare(scena.file_id))
    assert str(errore) == messaggio


@pytest.mark.parametrize("prima", [False, True])
@pytest.mark.parametrize("forzata", [CHIUSO, SI_APRE])
def test_con_l_archivio_chiuso_non_si_guarda_e_lo_dice(scena, prima, forzata):
    if prima:
        _metti(scena)
    scena.situazione.forzata = forzata
    errore = _fermato(lambda: ritocco_strade._da_guardare(scena.file_id))
    assert isinstance(errore, copia.RitoccoFermato)
    assert str(errore) == copia.SOLO_NELL_ARCHIVIO and errore.codice == copia.SICURO_CHIUSO


@pytest.mark.parametrize("prima", [False, True])
def test_se_l_archivio_non_lo_trova_non_si_guarda(scena, prima):
    if prima:
        _metti(scena)
    scena.situazione.forzata = NON_C_E
    errore = _fermato(lambda: ritocco_strade._da_guardare(scena.file_id))
    assert str(errore) == copia.DA_NESSUNA_PARTE


def test_senza_archivio_e_senza_disco_non_c_e_niente_da_guardare(scena):
    scena.situazione.forzata = SENZA_ARCHIVIO
    assert str(_fermato(lambda: ritocco_strade._da_guardare(scena.file_id))) == (
        copia.NON_SUL_DISCO)
    scena.situazione.forzata = None
    _metti(scena)
    scena.situazione.forzata = SENZA_ARCHIVIO
    errore = _fermato(lambda: ritocco_strade._da_guardare(scena.file_id))
    assert str(errore) == ritocco_strade.NON_C_E and errore.codice == "ritocco_senza_file"


@pytest.mark.parametrize("ritoccata, messaggio", [
    (False, copia.DIVERSA), (True, copia.CAMBIATO)])
@pytest.mark.parametrize("cambi", [{"diversa": True}, {"blake2b": "ab" * 32}])
def test_una_versione_cambiata_nell_archivio_non_si_guarda(scena, monkeypatch, cambi,
                                                           ritoccata, messaggio):
    if ritoccata:
        _metti(scena)
    servizio = scena.casa.archivio
    vera = servizio.cerca

    def cerca(*argomenti, **altro):
        ricerca = vera(*argomenti, **altro)
        return Ricerca(ricerca.perche, dataclasses.replace(ricerca.trovata, **cambi))

    monkeypatch.setattr(servizio, "cerca", cerca)
    errore = _fermato(lambda: ritocco_strade._da_guardare(scena.file_id))
    assert str(errore) == messaggio


@pytest.mark.parametrize("forzata, messaggio", [
    (None, copia.MESCOLATI), (CHIUSO, copia.MESCOLATI_FORSE),
    (NON_C_E, copia.DA_NESSUNA_PARTE)])
def test_con_la_ritoccata_sul_disco_e_lo_scatto_solo_nell_archivio_non_si_guarda(
        scena, forzata, messaggio):
    _metti(scena)
    scena.scatto.parent.mkdir(parents=True, exist_ok=True)
    scena.scatto.write_bytes(scena.dati[SOLE])
    scena.situazione.forzata = forzata
    assert str(_fermato(lambda: ritocco_strade._da_guardare(scena.file_id))) == messaggio


def test_lo_scatto_sul_disco_si_guarda_dal_disco_anche_ad_archivio_chiuso(scena):
    file_id = _file_id(scena.archivio, "sole.jpg")
    scena.situazione.forzata = CHIUSO
    percorso, chiave = ritocco_strade._da_guardare(file_id)
    assert percorso == scena.casa.foto / SOLE
    assert chiave == _impronta(scena.dati[SOLE])


def test_la_base_sul_disco_si_guarda_dal_disco(scena):
    file_id = _file_id(scena.archivio, "sole.jpg")
    scena.situazione.forzata = SENZA_ARCHIVIO
    ritocco_di_prova.copia.metti(scena.archivio, file_id,
                                 [ritocco_di_prova._volto(scena.dati[SOLE])])
    scena.situazione.forzata = CHIUSO
    percorso, chiave = ritocco_strade._da_guardare(file_id)
    assert percorso == scena.casa.foto / "s" / attesa.ORIGINALI / "sole.jpg"
    assert chiave == _impronta(scena.dati[SOLE])


def test_un_video_non_si_guarda_col_clic_delle_foto(scena):
    errore = _fermato(lambda: ritocco_strade._da_guardare(_file_id(scena.archivio,
                                                                   "onde.mp4")))
    assert str(errore) == ritocco_strade.NON_SI_SCEGLIE


def test_il_clic_guarda_e_sceglie_sullo_scatto_dell_archivio(cliente, scena, sam3):
    risposta = cliente.post(f"/api/ritocco/{scena.file_id}/guarda", headers=JSON)
    assert risposta.status_code == 200
    assert risposta.json() == {"larghezza": LARGA, "altezza": ALTA, "dove": "scheda"}
    risposta = cliente.post(f"/api/ritocco/{scena.file_id}/scegli", headers=JSON,
                            json={"punti": IN_MEZZO})
    assert risposta.status_code == 200 and risposta.json()["vuota"] is False
    [visto] = sceglitore_finto.visti(sam3)
    assert visto["letto"] == visto["chiave"] == _impronta(scena.dati[FOTO])
    assert visto["percorso"] == "«mare.jpg» dall'Archivio sicuro"
    assert visto["pid"] == os.getpid()


def test_dopo_un_ritocco_il_clic_legge_lo_scatto_senza_ritocchi(cliente, scena, sam3):
    _metti(scena)
    risposta = cliente.post(f"/api/ritocco/{scena.file_id}/scegli", headers=JSON,
                            json={"punti": IN_MEZZO})
    assert risposta.status_code == 200
    [visto] = sceglitore_finto.visti(sam3)
    assert visto["letto"] == _impronta(scena.dati[FOTO])


@pytest.mark.parametrize("cosa", ["guarda", "scegli"])
def test_ad_archivio_chiuso_il_clic_non_guarda_e_lo_dice(cliente, scena, sam3, cosa):
    scena.situazione.forzata = CHIUSO
    risposta = cliente.post(f"/api/ritocco/{scena.file_id}/{cosa}", headers=JSON,
                            json={"punti": IN_MEZZO})
    assert risposta.status_code == 400
    assert risposta.json()["messaggio"] == copia.SOLO_NELL_ARCHIVIO
    assert sceglitore_finto.visti(sam3) == [] and not ritocco_web.al_clic.acceso


def test_quando_l_archivio_si_chiude_il_clic_si_ferma_anche_con_lo_scatto_gia_guardato(
        cliente, scena, sam3):
    assert cliente.post(f"/api/ritocco/{scena.file_id}/guarda").status_code == 200
    scena.situazione.forzata = CHIUSO
    risposta = cliente.post(f"/api/ritocco/{scena.file_id}/scegli", headers=JSON,
                            json={"punti": IN_MEZZO})
    assert risposta.status_code == 400
    assert risposta.json()["messaggio"] == copia.SOLO_NELL_ARCHIVIO
    assert sceglitore_finto.visti(sam3) == []
    scena.situazione.forzata = None
    risposta = cliente.post(f"/api/ritocco/{scena.file_id}/scegli", json={"punti": IN_MEZZO})
    assert risposta.status_code == 200


@pytest.mark.parametrize("forzata", [CHIUSO, SI_APRE])
def test_se_l_archivio_si_chiude_prima_che_il_clic_lo_legga_lo_dice(clic, scena, sam3,
                                                                    forzata):
    percorso, chiave = ritocco_strade._da_guardare(scena.file_id)
    scena.situazione.forzata = forzata
    errore = _fermato(lambda: clic.guarda(sam3, chiave, percorso))
    assert errore.messaggio == copia.SOLO_NELL_ARCHIVIO
    assert errore.codice == copia.SICURO_CHIUSO


@pytest.mark.parametrize("perche, messaggio", [
    (NON_C_E, copia.DA_NESSUNA_PARTE), (SENZA_ARCHIVIO, copia.NON_SUL_DISCO)])
def test_se_il_clic_non_ritrova_lo_scatto_lo_dice(clic, scena, sam3, perche, messaggio):
    percorso, chiave = ritocco_strade._da_guardare(scena.file_id)
    scena.situazione.forzata = perche
    errore = _fermato(lambda: clic.scegli(sam3, chiave, percorso, [], None))
    assert errore.messaggio == messaggio and errore.codice == copia.RitoccoFermato.codice
    assert sceglitore_finto.visti(sam3) == []


@pytest.mark.parametrize("cambi", [{"diversa": True}, {"blake2b": "ab" * 32}])
def test_il_clic_non_legge_una_versione_cambiata(clic, scena, sam3, monkeypatch, cambi):
    percorso, chiave = ritocco_strade._da_guardare(scena.file_id)
    servizio = scena.casa.archivio
    vera = servizio.cerca

    def cerca(*argomenti, **altro):
        ricerca = vera(*argomenti, **altro)
        return Ricerca(ricerca.perche, dataclasses.replace(ricerca.trovata, **cambi))

    monkeypatch.setattr(servizio, "cerca", cerca)
    errore = _fermato(lambda: clic.guarda(sam3, chiave, percorso))
    assert errore.messaggio == copia.DIVERSA


def test_il_clic_cerca_lo_scatto_giusto_nell_archivio(clic, scena, sam3, monkeypatch):
    percorso, chiave = ritocco_strade._da_guardare(scena.file_id)
    servizio = scena.casa.archivio
    vera = servizio.cerca
    chieste: list = []

    def cerca(*argomenti, **altro):
        chieste.append((argomenti, altro))
        return vera(*argomenti, **altro)

    monkeypatch.setattr(servizio, "cerca", cerca)
    clic.guarda(sam3, chiave, percorso)
    dati = scena.dati[FOTO]
    assert chieste == [((_impronta(dati), len(dati), []), {"nome": "mare.jpg",
                                                            "intero": True})]


def test_se_l_archivio_non_risponde_al_clic_lo_dice_come_chiuso(clic, scena, sam3,
                                                                monkeypatch):
    percorso, chiave = ritocco_strade._da_guardare(scena.file_id)
    avvisi: list = []
    monkeypatch.setattr(copia.registro, "avviso",
                        lambda nome, **campi: avvisi.append((nome, campi)))

    def rotta(*argomenti, **altro):
        raise ErroreOfficina("rotto", codice="occupato")

    monkeypatch.setattr(scena.casa.archivio, "cerca", rotta)
    errore = _fermato(lambda: clic.guarda(sam3, chiave, percorso))
    assert errore.messaggio == copia.SOLO_NELL_ARCHIVIO
    assert errore.codice == copia.SICURO_CHIUSO
    assert ("ritocco.archivio_non_risponde", {"motivo": "occupato"}) in [
        (nome, {chiave_: str(valore) for chiave_, valore in campi.items()})
        for nome, campi in avvisi]


def test_se_l_archivio_si_chiude_mentre_il_clic_legge_lo_dice(clic, scena, sam3,
                                                              monkeypatch):
    percorso, chiave = ritocco_strade._da_guardare(scena.file_id)
    monkeypatch.setattr(archivio_sicuro, "per_le_foto",
                        lambda: (TROVATA, scena.casa.archivio))
    vera = DallArchivio.apri

    def apri(trovata):
        scena.casa.archivio.chiudi(ATTESA)
        return vera(trovata)

    monkeypatch.setattr(DallArchivio, "apri", apri)
    errore = _fermato(lambda: clic.guarda(sam3, chiave, percorso))
    assert errore.messaggio == copia.SOLO_NELL_ARCHIVIO
    assert errore.codice == copia.SICURO_CHIUSO


def test_uno_scatto_rovinato_nell_archivio_il_clic_lo_dice(clic, scena, sam3):
    percorso, chiave = ritocco_strade._da_guardare(scena.file_id)
    _stacca(scena.casa)
    _rovina(scena.casa, FOTO)
    errore = _fermato(lambda: clic.guarda(sam3, chiave, percorso))
    assert errore.messaggio == copia.ROVINATA
    assert errore.codice == copia.RitoccoFermato.codice


def test_un_guasto_del_clic_che_non_viene_dall_archivio_resta_quello_di_prima(sam3, scena,
                                                                            strumento_rotto):
    percorso, chiave = ritocco_strade._da_guardare(scena.file_id)
    errore = _fermato(lambda: strumento_rotto.scegli(sam3, chiave, percorso, [], None))
    assert errore.messaggio == ritocco_web.NON_GUARDA and errore.codice == "ritocco_scelta"


@pytest.fixture
def strumento_rotto():
    rotto = ritocco_web.AlClic("prove.sceglitore_finto:Rotta")
    yield rotto
    rotto.chiudi()


def test_le_misure_dritte_si_leggono_dall_archivio(scena):
    percorso, _ = ritocco_strade._da_guardare(scena.file_id)
    with copia.leggendo(percorso):
        assert strumento.misure_dritte(percorso) == (LARGA, ALTA)


def test_le_misure_dritte_con_l_archivio_chiuso_a_meta_si_fermano(scena, monkeypatch):
    percorso, _ = ritocco_strade._da_guardare(scena.file_id)
    monkeypatch.setattr(archivio_sicuro, "per_le_foto",
                        lambda: (TROVATA, scena.casa.archivio))
    assert scena.casa.archivio.chiudi(ATTESA)
    assert strumento.misure_dritte(percorso) is None
    errore = _fermato(lambda: _misura_attenta(percorso))
    assert errore.messaggio == copia.SOLO_NELL_ARCHIVIO
    assert errore.codice == copia.SICURO_CHIUSO


def _misura_attenta(percorso):
    with copia.leggendo(percorso):
        return strumento.misure_dritte(percorso)


def test_leggendo_lascia_passare_il_disco_e_gli_altri_guasti(tmp_path):
    percorso = tmp_path / "x.jpg"
    with copia.leggendo(percorso) as dentro:
        assert dentro is percorso
    with pytest.raises(ValueError), copia.leggendo(percorso):
        raise ValueError("altro")


@pytest.mark.parametrize("codice, messaggio, codice_fuori", [
    (PERSA, copia.ROVINATA, copia.RitoccoFermato.codice),
    ("sicuro_chiuso", copia.SOLO_NELL_ARCHIVIO, copia.SICURO_CHIUSO),
    (None, copia.SOLO_NELL_ARCHIVIO, copia.SICURO_CHIUSO)])
def test_leggendo_cambia_i_guasti_dell_archivio_in_un_ritocco_fermato(codice, messaggio,
                                                                     codice_fuori):
    trovata = DallArchivio("00" * 16, "s/a.jpg", 3, "ab" * 32, True, False, lambda _: None)
    with pytest.raises(copia.RitoccoFermato) as preso, copia.leggendo(trovata):
        trovata.segna_guasto(codice)
    assert str(preso.value) == messaggio and preso.value.codice == codice_fuori
    trovata = DallArchivio("00" * 16, "s/a.jpg", 3, "ab" * 32, True, False, lambda _: None)
    with pytest.raises(copia.RitoccoFermato) as preso, copia.leggendo(trovata):
        trovata.segna_guasto(codice)
        raise OSError("letto male")
    assert str(preso.value) == messaggio


def test_salvare_dall_archivio_pixela_e_la_copia_va_solo_nell_archivio(cliente, scena,
                                                                       tmp_path):
    risposta = cliente.post(f"/api/ritocco/{scena.file_id}/salva", headers=JSON,
                            json=_da_salvare())
    assert risposta.status_code == 200 and risposta.json() == {"fatto": True, "quanti": 1}
    riga = _ritoccata(scena)
    assert riga["stato"] == copia.FATTA and riga["nell_archivio"] == 1
    assert riga["impronta_base"] == _impronta(scena.dati[FOTO])
    assert not os.path.lexists(scena.scatto) and not os.path.lexists(scena.base)
    [ritocco] = _attivi(scena)
    assert (ritocco["origine_x"], ritocco["origine_y"]) == (ZONA[0], ZONA[1])
    assert _storia(scena, FOTO)[-1] == (riga["impronta_copia"], True)
    risposta = cliente.post(f"/api/ritocco/{scena.file_id}/salva", headers=JSON,
                            json=_da_salvare(ALTRA_ZONA))
    assert risposta.status_code == 200
    assert len(_attivi(scena)) == 2 and _in_attesa(scena) == []


def test_salvare_dal_lato_di_lavoro_piu_grande_va_anche_dall_archivio(cliente, scena):
    doppia = (ZONA[0] * 2, ZONA[1] * 2, ZONA[2] * 2, ZONA[3] * 2)
    risposta = cliente.post(f"/api/ritocco/{scena.file_id}/salva", headers=JSON,
                            json=_da_salvare(doppia, LARGA * 2, ALTA * 2))
    assert risposta.status_code == 200
    [ritocco] = _attivi(scena)
    assert (ritocco["larghezza"], ritocco["altezza"]) == (LARGA * 2, ALTA * 2)


def test_salvare_con_la_forma_sbagliata_non_tocca_niente(cliente, scena):
    risposta = cliente.post(f"/api/ritocco/{scena.file_id}/salva", headers=JSON,
                            json=_da_salvare(ZONA, ALTA, ALTA))
    assert risposta.status_code == 400
    assert risposta.json()["messaggio"] == ritocco_strade.NON_TORNA
    assert _ritoccata(scena) is None and _attivi(scena) == []
    assert scena.casa.cestino.mosse == []


@pytest.mark.parametrize("forzata", [CHIUSO, SI_APRE])
def test_salvare_ad_archivio_chiuso_non_tocca_niente(cliente, scena, forzata):
    scena.situazione.forzata = forzata
    risposta = cliente.post(f"/api/ritocco/{scena.file_id}/salva", headers=JSON,
                            json=_da_salvare())
    assert risposta.status_code == 400
    assert risposta.json()["messaggio"] == copia.SOLO_NELL_ARCHIVIO
    assert _ritoccata(scena) is None and _attivi(scena) == [] and _falliti(scena) == []
    assert scena.casa.cestino.mosse == [] and _in_attesa(scena) == []


def test_salvare_se_l_archivio_si_chiude_mentre_misura_non_tocca_niente(cliente, scena,
                                                                       monkeypatch):
    monkeypatch.setattr(archivio_sicuro, "per_le_foto",
                        lambda: (TROVATA, scena.casa.archivio))
    vera = strumento.misure_dritte

    def misure(percorso):
        scena.casa.archivio.chiudi(ATTESA)
        return vera(percorso)

    monkeypatch.setattr(strumento, "misure_dritte", misure)
    risposta = cliente.post(f"/api/ritocco/{scena.file_id}/salva", headers=JSON,
                            json=_da_salvare())
    assert risposta.status_code == 400
    assert risposta.json()["messaggio"] == copia.SOLO_NELL_ARCHIVIO
    assert _ritoccata(scena) is None and _attivi(scena) == [] and _falliti(scena) == []
    assert scena.casa.cestino.mosse == []


def test_salvare_uno_scatto_rovinato_nell_archivio_non_tocca_niente(cliente, scena):
    _stacca(scena.casa)
    _rovina(scena.casa, FOTO)
    risposta = cliente.post(f"/api/ritocco/{scena.file_id}/salva", headers=JSON,
                            json=_da_salvare())
    assert risposta.status_code == 400
    assert risposta.json()["messaggio"] == copia.ROVINATA
    assert _ritoccata(scena) is None and _attivi(scena) == [] and _falliti(scena) == []


def test_salvare_non_rilegge_lo_scatto_se_non_serve(cliente, scena, monkeypatch):
    letture: list = []
    vera = metadati.apri

    def apri(sorgente):
        letture.append(type(sorgente).__name__)
        return vera(sorgente)

    monkeypatch.setattr(metadati, "apri", apri)
    assert cliente.post(f"/api/ritocco/{scena.file_id}/salva",
                        json=_da_salvare()).status_code == 200
    assert letture == ["DallArchivio"]


@pytest.fixture
def a_parte(monkeypatch):
    monkeypatch.setattr(in_disparte, "A_PARTE", True)
    yield
    in_disparte.chiudi(1.0)


def test_a_parte_il_clic_legge_dall_archivio_in_un_altro_processo(a_parte, cliente, scena,
                                                                   sam3, clic):
    risposta = cliente.post(f"/api/ritocco/{scena.file_id}/guarda", headers=JSON)
    assert risposta.status_code == 200, risposta.text
    assert in_disparte.sta_girando(ritocco_web.A)
    risposta = cliente.post(f"/api/ritocco/{scena.file_id}/scegli", headers=JSON,
                            json={"punti": IN_MEZZO})
    assert risposta.status_code == 200, risposta.text
    [visto] = sceglitore_finto.visti(sam3)
    assert visto["pid"] != os.getpid()
    assert visto["letto"] == _impronta(scena.dati[FOTO])
    assert clic._sportello is not None and clic._sportello._legata is not None
    percorso, chiave = ritocco_strade._da_guardare(scena.file_id)
    scena.situazione.forzata = CHIUSO
    risposta = cliente.post(f"/api/ritocco/{scena.file_id}/scegli", headers=JSON,
                            json={"punti": IN_MEZZO})
    assert risposta.json()["messaggio"] == copia.SOLO_NELL_ARCHIVIO
    errore = _fermato(lambda: clic.scegli(sam3, chiave, percorso, [], None))
    assert errore.codice == copia.SICURO_CHIUSO and clic._sportello._legata is None
    scena.situazione.forzata = None
    assert scena.casa.archivio.chiudi(ATTESA)
    errore = _fermato(lambda: clic.scegli(sam3, chiave + "#", percorso, [], None))
    assert errore.messaggio == copia.SOLO_NELL_ARCHIVIO
    assert errore.codice == copia.SICURO_CHIUSO
    assert len(sceglitore_finto.visti(sam3)) == 1
    sportello_vecchio = clic._sportello
    clic.chiudi()
    assert clic._sportello is None and sportello_vecchio._legata is None
    assert not in_disparte.sta_girando(ritocco_web.A)


def test_a_parte_se_lo_sportello_non_si_chiude_il_clic_si_spegne_e_lo_segna(
        a_parte, scena, sam3, clic, monkeypatch):
    percorso, chiave = ritocco_strade._da_guardare(scena.file_id)
    clic.guarda(sam3, chiave, percorso)
    avvisi: list = []
    monkeypatch.setattr(ritocco_web.registro, "avviso",
                        lambda nome, **campi: avvisi.append(nome))

    def rotto():
        raise OSError("tubo rotto")

    monkeypatch.setattr(clic._sportello, "chiudi", rotto)
    clic.chiudi()
    assert avvisi == ["ritocco.sportello_non_chiuso"]
    assert clic._sportello is None and clic._processo is None and not clic.acceso
    assert not in_disparte.sta_girando(ritocco_web.A)
    clic.scegli(sam3, chiave, percorso, [], None)
    [visto] = sceglitore_finto.visti(sam3)
    assert visto["letto"] == _impronta(scena.dati[FOTO]) and clic._sportello is not None


def test_a_parte_lo_scatto_rovinato_lo_dice(a_parte, scena, sam3, clic):
    percorso, chiave = ritocco_strade._da_guardare(scena.file_id)
    _stacca(scena.casa)
    _rovina(scena.casa, FOTO)
    errore = _fermato(lambda: clic.guarda(sam3, chiave, percorso))
    assert errore.messaggio == copia.ROVINATA
    assert errore.codice == copia.RitoccoFermato.codice
    assert clic.acceso


def test_a_parte_lo_scatto_sul_disco_si_legge_come_prima(a_parte, scena, sam3, clic):
    file_id = _file_id(scena.archivio, "sole.jpg")
    percorso, chiave = ritocco_strade._da_guardare(file_id)
    clic.scegli(sam3, chiave, percorso, [], None)
    [visto] = sceglitore_finto.visti(sam3)
    assert visto["percorso"] == str(scena.casa.foto / SOLE)
    assert visto["letto"] == _impronta(scena.dati[SOLE]) and visto["pid"] != os.getpid()


def test_lo_scatto_dell_archivio_va_al_clic_senza_chiavi_ne_pezzi_di_archivio(scena):
    percorso, _ = ritocco_strade._da_guardare(scena.file_id)
    mandato = ritocco_web._da_mandare(percorso)
    dati = scena.dati[FOTO]
    assert mandato == {"impronta": _impronta(dati), "dimensione": len(dati),
                       "nome": "mare.jpg", "intero": True}
    assert ritocco_web._da_mandare(Path("a") / "b.jpg") == str(Path("a") / "b.jpg")


def test_nel_processo_a_parte_il_clic_usa_lo_sportello(monkeypatch):
    lontano = object()
    monkeypatch.setattr(sportello, "_lontano", lontano)
    monkeypatch.setattr(archivio_sicuro, "per_le_foto", lambda: pytest.fail("chiesto"))
    assert ritocco_web._servizio_delle_foto() == (TROVATA, lontano)
    monkeypatch.setattr(sportello, "_lontano", None)
    monkeypatch.setattr(archivio_sicuro, "per_le_foto", lambda: (CHIUSO, None))
    assert ritocco_web._servizio_delle_foto() == (CHIUSO, None)


def test_lo_strumento_vero_apre_lo_scatto_dall_archivio_senza_farne_un_percorso(scena):
    percorso, _ = ritocco_strade._da_guardare(scena.file_id)
    sceglitore = scelta.Sceglitore(scena.casa.foto)
    with copia.leggendo(percorso):
        assert sceglitore._immagine("k", percorso, None).size == (LARGA, ALTA)


def test_senza_archivio_aperto_lo_sportello_non_ha_nome(scena, monkeypatch):
    from officina.archivio import accesso

    assert ritocco_web._nome_dell_archivio() == accesso.aperto().dove.nome

    def chiuso():
        raise ErroreOfficina("chiuso", codice="archivio_chiuso")

    monkeypatch.setattr(accesso, "aperto", chiuso)
    assert ritocco_web._nome_dell_archivio() is None
