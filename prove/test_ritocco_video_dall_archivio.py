from __future__ import annotations

import dataclasses
import os
from pathlib import Path

import numpy
import pytest
from fastapi.testclient import TestClient

from officina.errori import ErroreOfficina
from officina.programma import archivio_sicuro
from officina.ritocco import coda, copia, elenco, lavoro, maschere, seguiti
from officina.sicuro import prendi
from officina.sicuro.dall_archivio import (CHIUSO, NON_C_E, SENZA_ARCHIVIO, SI_APRE, TROVATA,
                                           DallArchivio, Ricerca)
from officina.web import coda_ritocco, in_disparte, lavori, seguire
from officina.web import ritocco as ritocco_web
from officina.web.strade import ritocco as ritocco_strade
from officina.web.strade import ritocco_video
from prove import sceglitore_finto
from prove import test_miglioria_mostra_dall_archivio as mostra
from prove import test_ritocco_dall_archivio as ritocco_di_prova
from prove.test_miglioria_coda_dall_archivio import FILMATO, FOTO, SOLE, _file_id
from prove.test_miglioria_dall_archivio import _mai_in_chiaro
from prove.test_ritocco_video import _aspetta
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
SUL_QUADRATO = {"x1": 0.05, "y1": 0.3, "x2": 0.25, "y2": 0.6}
QUANTI, LARGA, ALTA = 12, 64, 48
DALL_ARCHIVIO = "«onde.mp4» dall'Archivio sicuro"
PEZZETTO = 512
CHIUSO_ORA = (copia.SOLO_NELL_ARCHIVIO, copia.SICURO_CHIUSO)
SENZA_FILE = (ritocco_strade.NON_C_E, "ritocco_senza_file")


@pytest.fixture(autouse=True)
def turno_pulito(monkeypatch):
    monkeypatch.setattr(lavoro, "ASPETTA_IL_SEGUITO", 0.05)
    monkeypatch.setattr(ritocco_web, "PRIMA_DI_RIPRENDERE", 0.3)
    monkeypatch.setattr(seguire, "inseguitore", seguire.Inseguitore())
    yield
    seguire.inseguitore.lascia_tutto()
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
    monkeypatch.setattr(coda_ritocco, "avvia", lambda archivio: False)
    yield nuovo
    nuovo.chiudi()


@pytest.fixture
def cliente(scena, clic):
    from officina.web.server import app

    return TestClient(app, client=("127.0.0.1", 51000))


@pytest.fixture
def filmato_id(scena) -> int:
    return _file_id(scena.archivio, "onde.mp4")


@pytest.fixture
def a_parte(monkeypatch):
    monkeypatch.setattr(in_disparte, "A_PARTE", True)
    yield
    in_disparte.chiudi(1.0)


def _fermato(fare) -> ErroreOfficina:
    with pytest.raises(ErroreOfficina) as preso:
        fare()
    return preso.value


def _dati(scena) -> bytes:
    return scena.dati[FILMATO]


def _pronto(cliente, file_id: int) -> dict:
    risposta = cliente.get(f"/api/ritocco-video/{file_id}/pronto", headers=JSON)
    assert risposta.status_code == 200, risposta.text
    indirizzo = f"/api/ritocco-video/{file_id}/video"
    assert _aspetta(lambda: cliente.get(indirizzo).json()["stato"] == seguire.PRONTO)
    return risposta.json()


def _stato(cliente, seguito_id: int) -> dict:
    return cliente.get(f"/api/ritocco-video/seguito/{seguito_id}").json()


def _seguito_tutto(cliente, seguito_id: int) -> bool:
    return _aspetta(lambda: _stato(cliente, seguito_id)["stato"] == seguiti.SEGUITO)


def _scegli(cliente, file_id: int, fotogramma: int = 5, **altro):
    return cliente.post(f"/api/ritocco-video/{file_id}/scegli", headers=JSON, json={
        "fotogramma": fotogramma, "riquadro": SUL_QUADRATO, "cosa": elenco.VOLTO, **altro})


def _bozza(scena, file_id: int, chiave: str, fotogrammi=(5,)) -> int:
    piena = numpy.zeros((ALTA, LARGA), dtype=bool)
    piena[10:30, 5:25] = True
    with scena.archivio.scrittura() as connessione:
        seguito_id = seguiti.nuovo(connessione, file_id, cosa=elenco.VOLTO, impronta=chiave,
                                   larghezza=LARGA, altezza=ALTA, quanti=QUANTI,
                                   istanti_ms=[indice * 83 for indice in range(QUANTI)])
        for fotogramma in fotogrammi:
            seguiti.metti_scelta(connessione, seguito_id, fotogramma,
                                 maschere.comprimi(piena, (0, 0), LARGA, ALTA))
    return seguito_id


def _percorso(scena, file_id: int) -> str:
    with scena.archivio.lettura() as connessione:
        return connessione.execute("SELECT percorso FROM percorsi WHERE file_id = ?",
                                   (file_id,)).fetchone()[0]


def _ritoccata_sparita(scena, file_id: int, chiave: str) -> None:
    with scena.archivio.scrittura() as connessione:
        connessione.execute(
            "INSERT INTO ritoccate (file_id, stato, percorso_copia, impronta_copia, "
            "percorso_base, impronta_base, base_e) VALUES (?, 'fatta', ?, ?, ?, ?, ?)",
            (file_id, _percorso(scena, file_id), "ee" * 32,
             str(scena.casa.foto / "s" / "Originali" / "onde.mp4"), chiave, "originale"))


def _seguito(scena, seguito_id: int):
    with scena.archivio.lettura() as connessione:
        return seguiti.per_id(connessione, seguito_id)


def _cambia(scena, monkeypatch, cambi: dict) -> None:
    servizio = scena.casa.archivio
    vera = servizio.cerca

    def cerca(*argomenti, **altro):
        ricerca = vera(*argomenti, **altro)
        return Ricerca(ricerca.perche, dataclasses.replace(ricerca.trovata, **cambi))

    monkeypatch.setattr(servizio, "cerca", cerca)


def _in_coda(scena, file_id: int) -> list:
    with scena.archivio.lettura() as connessione:
        return elenco.di_file(connessione, file_id, elenco.IN_CODA)


def test_il_video_solo_nell_archivio_si_guarda_dall_archivio(scena, filmato_id):
    riga, percorso, chiave = ritocco_video._il_video(filmato_id)
    dati = _dati(scena)
    assert riga["id"] == filmato_id and isinstance(percorso, DallArchivio)
    assert (percorso.blake2b, percorso.dimensione, percorso.intero) == (
        _impronta(dati), len(dati), False)
    assert percorso.name == "onde.mp4" and not percorso.diversa
    assert chiave == _impronta(dati) == riga["impronta"]
    with percorso.apri() as letto:
        assert letto.read() == dati


@pytest.mark.parametrize("forzata, messaggio, codice", [
    (CHIUSO, copia.SOLO_NELL_ARCHIVIO, copia.SICURO_CHIUSO),
    (SI_APRE, copia.SOLO_NELL_ARCHIVIO, copia.SICURO_CHIUSO),
    (NON_C_E, copia.DA_NESSUNA_PARTE, copia.RitoccoFermato.codice),
    (SENZA_ARCHIVIO, copia.NON_SUL_DISCO, copia.RitoccoFermato.codice)])
def test_se_il_video_non_si_legge_dall_archivio_lo_strumento_lo_dice(scena, filmato_id,
                                                                     forzata, messaggio,
                                                                     codice):
    scena.situazione.forzata = forzata
    errore = _fermato(lambda: ritocco_video._il_video(filmato_id))
    assert (errore.messaggio, errore.codice) == (messaggio, codice)


@pytest.mark.parametrize("cambi", [{"diversa": True}, {"blake2b": "ab" * 32}])
def test_un_video_cambiato_nell_archivio_non_si_guarda(scena, filmato_id, monkeypatch,
                                                         cambi):
    _cambia(scena, monkeypatch, cambi)
    assert _fermato(lambda: ritocco_video._il_video(filmato_id)).messaggio == copia.DIVERSA


def test_il_video_sul_disco_si_guarda_dal_disco_anche_ad_archivio_chiuso(scena, filmato_id):
    sul_disco = scena.casa.foto / FILMATO
    sul_disco.write_bytes(_dati(scena))
    scena.situazione.forzata = CHIUSO
    _, percorso, chiave = ritocco_video._il_video(filmato_id)
    assert percorso == sul_disco and chiave == _impronta(_dati(scena))


def test_lo_strumento_riconosce_dal_nome_un_formato_che_non_si_riscrive(scena, filmato_id):
    with scena.archivio.scrittura() as connessione:
        connessione.execute("UPDATE percorsi SET nome = ? WHERE file_id = ?",
                            ("onde.avi", filmato_id))
    errore = _fermato(lambda: ritocco_video._il_video(filmato_id))
    assert (errore.messaggio, errore.codice) == (coda.FORMATO, "ritocco_formato")


def test_una_cartella_al_posto_del_video_non_si_guarda(clic, scena, filmato_id, sam3):
    _, _, chiave = ritocco_video._il_video(filmato_id)
    seguito_id = _bozza(scena, filmato_id, chiave)
    Path(_percorso(scena, filmato_id)).mkdir(parents=True)
    errore = _fermato(lambda: ritocco_video._il_video(filmato_id))
    assert (errore.messaggio, errore.codice) == SENZA_FILE
    seguitore = coda_ritocco.Seguitore(scena.archivio, al_clic=clic, cartella=sam3)
    assert _fermato(lambda: seguitore._dove(seguito_id)).messaggio == coda.NON_C_E


def test_un_video_che_non_c_e_da_nessuna_parte_non_si_guarda(clic, scena, filmato_id, sam3):
    _, _, chiave = ritocco_video._il_video(filmato_id)
    seguito_id = _bozza(scena, filmato_id, chiave)
    _ritoccata_sparita(scena, filmato_id, chiave)
    scena.situazione.forzata = SENZA_ARCHIVIO
    errore = _fermato(lambda: ritocco_video._il_video(filmato_id))
    assert (errore.messaggio, errore.codice) == SENZA_FILE
    seguitore = coda_ritocco.Seguitore(scena.archivio, al_clic=clic, cartella=sam3)
    assert _fermato(lambda: seguitore._dove(seguito_id)).messaggio == coda.NON_C_E


def test_la_migliorata_solo_nell_archivio_si_guarda_dall_archivio(scena, filmato_id):
    migliorata = mostra._approvata(scena, FILMATO)
    _, percorso, chiave = ritocco_video._il_video(filmato_id)
    dati = mostra.MIGLIORATA[FILMATO]
    assert migliorata["nell_archivio"] == 1 and isinstance(percorso, DallArchivio)
    assert percorso.blake2b == chiave == _impronta(dati) == migliorata["impronta_migliorata"]
    with scena.archivio.lettura() as connessione:
        assert copia.base_per_la_coda(connessione, filmato_id) == (
            Path(migliorata["percorso_migliorata"]).name, chiave)
    bozza = _bozza(scena, filmato_id, chiave)
    lavoro_id = coda.metti(scena.archivio, [{"file_id": filmato_id, "seguito_id": bozza}])
    [ritocco] = _in_coda(scena, filmato_id)
    assert ritocco["lavoro_id"] == lavoro_id


def test_lo_strumento_prepara_sceglie_e_segue_il_video_dall_archivio(cliente, scena,
                                                                     filmato_id, sam3,
                                                                     tmp_path):
    dati = _dati(scena)
    pronto = _pronto(cliente, filmato_id)
    assert pronto["nome"] == "onde.mp4" and pronto["gia"] == []
    preparato = cliente.get(f"/api/ritocco-video/{filmato_id}/video").json()
    assert (preparato["quanti"], preparato["larghezza"], preparato["altezza"]) == (
        QUANTI, LARGA, ALTA)
    assert preparato["chiave"] == _impronta(dati)
    risposta = _scegli(cliente, filmato_id)
    assert risposta.status_code == 200, risposta.text
    assert risposta.json()["vuota"] is False
    seguito_id = risposta.json()["seguito"]["id"]
    assert _seguito_tutto(cliente, seguito_id)
    [visto] = sceglitore_finto.visti(sam3)
    assert (visto["percorso"], visto["chiave"]) == (DALL_ARCHIVIO, _impronta(dati))
    [seguito] = sceglitore_finto.seguiti(sam3)
    assert (seguito["percorso"], seguito["quanti"]) == (DALL_ARCHIVIO, QUANTI)
    assert seguito["pid"] == os.getpid()
    assert _seguito(scena, seguito_id)["impronta"] == _impronta(dati)
    assert _stato(cliente, seguito_id)["fatti"] == QUANTI
    salvato = cliente.post(f"/api/ritocco-video/{filmato_id}/salva", headers=JSON, json={
        "parti": [{"seguito": seguito_id, "cosa": elenco.VOLTO}]})
    assert salvato.status_code == 200, salvato.text
    [ritocco] = _in_coda(scena, filmato_id)
    assert (ritocco["seguito_id"], ritocco["lavoro_id"]) == (seguito_id,
                                                            salvato.json()["lavoro"])
    assert not os.path.lexists(scena.casa.foto / FILMATO)
    _mai_in_chiaro(tmp_path, dati)


def test_ad_archivio_chiuso_lo_strumento_video_non_legge_e_non_cambia_niente(
        cliente, scena, filmato_id, sam3):
    _pronto(cliente, filmato_id)
    seguito_id = _scegli(cliente, filmato_id, 2).json()["seguito"]["id"]
    assert _seguito_tutto(cliente, seguito_id)
    assert _scegli(cliente, filmato_id, 8, seguito=seguito_id).status_code == 200
    assert _seguito_tutto(cliente, seguito_id)
    seguiti_prima = len(sceglitore_finto.seguiti(sam3))
    parti = {"parti": [{"seguito": seguito_id, "cosa": elenco.VOLTO}]}
    scena.situazione.forzata = CHIUSO
    base = f"/api/ritocco-video/{filmato_id}"
    for risposta in (
            cliente.get(f"{base}/pronto", headers=JSON),
            cliente.get(f"{base}/video", headers=JSON),
            _scegli(cliente, filmato_id, 4),
            _scegli(cliente, filmato_id, 4, seguito=seguito_id),
            cliente.post(f"/api/ritocco-video/seguito/{seguito_id}/segui", headers=JSON),
            cliente.post(f"/api/ritocco-video/seguito/{seguito_id}/togli-correzione",
                         headers=JSON, json={"fotogramma": 8}),
            cliente.post(f"{base}/stima", headers=JSON, json=parti),
            cliente.post(f"{base}/salva", headers=JSON, json=parti)):
        assert risposta.status_code == 400
        assert risposta.json()["messaggio"] == copia.SOLO_NELL_ARCHIVIO
    assert _stato(cliente, seguito_id)["scelte"] == [2, 8]
    assert _seguito(scena, seguito_id)["stato"] == seguiti.SEGUITO
    assert len(sceglitore_finto.seguiti(sam3)) == seguiti_prima
    assert len(sceglitore_finto.visti(sam3)) == 2 and _in_coda(scena, filmato_id) == []
    scena.situazione.forzata = None
    tolta = cliente.post(f"/api/ritocco-video/seguito/{seguito_id}/togli-correzione",
                         headers=JSON, json={"fotogramma": 8})
    assert tolta.status_code == 200 and tolta.json()["scelte"] == [2]


def test_chiudendo_le_parti_scelte_si_buttano_anche_ad_archivio_chiuso(cliente, scena,
                                                                      filmato_id):
    _pronto(cliente, filmato_id)
    seguito_id = _scegli(cliente, filmato_id).json()["seguito"]["id"]
    assert _seguito_tutto(cliente, seguito_id)
    scena.situazione.forzata = CHIUSO
    chiuso = cliente.post(f"/api/ritocco-video/{filmato_id}/chiudi", json={"butta": True})
    assert chiuso.json() == {"chiuso": True, "tolti": 1}
    assert _seguito(scena, seguito_id) is None


def test_chiudendo_si_buttano_le_parti_scelte_sulla_migliorata(cliente, scena, filmato_id):
    migliorata = mostra._approvata(scena, FILMATO)
    sulla_migliorata = _bozza(scena, filmato_id, migliorata["impronta_migliorata"])
    sull_originale = _bozza(scena, filmato_id, _impronta(_dati(scena)))
    scena.situazione.forzata = CHIUSO
    chiuso = cliente.post(f"/api/ritocco-video/{filmato_id}/chiudi", json={"butta": True})
    assert chiuso.json() == {"chiuso": True, "tolti": 1}
    assert _seguito(scena, sulla_migliorata) is None
    assert _seguito(scena, sull_originale) is not None


def test_togliendo_una_correzione_si_ricontrolla_che_non_sia_andata_in_coda(
        cliente, scena, filmato_id, monkeypatch):
    _, _, chiave = ritocco_video._il_video(filmato_id)
    seguito_id = _bozza(scena, filmato_id, chiave, fotogrammi=(5, 8))
    vero = ritocco_video._il_video

    def e_intanto_va_in_coda(file_id: int) -> tuple:
        trovato = vero(file_id)
        coda.metti(scena.archivio, [{"file_id": filmato_id, "seguito_id": seguito_id}])
        return trovato

    monkeypatch.setattr(ritocco_video, "_il_video", e_intanto_va_in_coda)
    risposta = cliente.post(f"/api/ritocco-video/seguito/{seguito_id}/togli-correzione",
                            headers=JSON, json={"fotogramma": 8})
    assert risposta.status_code == 400
    assert risposta.json()["messaggio"] == ritocco_video.GIA_IN_CODA
    with scena.archivio.lettura() as connessione:
        assert sorted(seguiti.scelte(connessione, seguito_id)) == [5, 8]


@pytest.mark.parametrize("forzata", [CHIUSO, SI_APRE])
def test_se_l_archivio_si_chiude_prima_che_il_video_si_prepari_lo_dice(clic, scena,
                                                                       filmato_id, sam3,
                                                                       forzata):
    _, percorso, chiave = ritocco_video._il_video(filmato_id)
    scena.situazione.forzata = forzata
    errore = _fermato(lambda: clic.prepara(sam3, chiave, percorso))
    assert (errore.messaggio, errore.codice) == CHIUSO_ORA


@pytest.mark.parametrize("quando", ["aprendo", "leggendo"])
def test_se_l_archivio_si_chiude_mentre_il_video_si_legge_lo_dice(clic, scena, filmato_id,
                                                                 sam3, monkeypatch, quando):
    _, percorso, chiave = ritocco_video._il_video(filmato_id)
    monkeypatch.setattr(archivio_sicuro, "per_le_foto",
                        lambda: (TROVATA, scena.casa.archivio))
    if quando == "aprendo":
        vera = DallArchivio.apri

        def apri(trovata):
            scena.casa.archivio.chiudi(ATTESA)
            return vera(trovata)

        monkeypatch.setattr(DallArchivio, "apri", apri)
    else:
        vero = prendi.Flusso.readinto
        letti: list = []

        def a_pezzi(flusso, spazio):
            letti.append(flusso.tell())
            if len(letti) == 2:
                scena.casa.archivio.chiudi(ATTESA)
            return vero(flusso, memoryview(spazio)[:PEZZETTO])

        monkeypatch.setattr(prendi.Flusso, "readinto", a_pezzi)
    errore = _fermato(lambda: clic.prepara(sam3, chiave, percorso))
    assert (errore.messaggio, errore.codice) == CHIUSO_ORA
    assert quando == "aprendo" or letti[:2] == [0, PEZZETTO]


def test_un_video_rovinato_nell_archivio_lo_dice(clic, scena, filmato_id, sam3):
    _, percorso, chiave = ritocco_video._il_video(filmato_id)
    _stacca(scena.casa)
    _rovina(scena.casa, FILMATO)
    errore = _fermato(lambda: clic.prepara(sam3, chiave, percorso))
    assert (errore.messaggio, errore.codice) == (copia.ROVINATA, copia.RitoccoFermato.codice)


@pytest.mark.parametrize("cambi", [{"diversa": True}, {"blake2b": "ab" * 32}])
def test_il_video_cambiato_nell_archivio_non_si_prepara(clic, scena, filmato_id, sam3,
                                                       monkeypatch, cambi):
    _, percorso, chiave = ritocco_video._il_video(filmato_id)
    _cambia(scena, monkeypatch, cambi)
    assert _fermato(lambda: clic.prepara(sam3, chiave, percorso)).messaggio == copia.DIVERSA


def test_il_video_si_cerca_giusto_nell_archivio(clic, scena, filmato_id, sam3, monkeypatch):
    _, percorso, chiave = ritocco_video._il_video(filmato_id)
    servizio = scena.casa.archivio
    vera = servizio.cerca
    chieste: list = []

    def cerca(*argomenti, **altro):
        chieste.append((argomenti, altro))
        return vera(*argomenti, **altro)

    monkeypatch.setattr(servizio, "cerca", cerca)
    preparato = clic.prepara(sam3, chiave, percorso)
    dati = _dati(scena)
    assert preparato["quanti"] == QUANTI
    assert chieste == [((_impronta(dati), len(dati), []), {"nome": "onde.mp4",
                                                            "intero": False})]


def test_ad_archivio_chiuso_il_seguito_si_ferma_col_motivo_e_poi_riprende(clic, scena,
                                                                        filmato_id, sam3):
    _, percorso, chiave = ritocco_video._il_video(filmato_id)
    seguito_id = _bozza(scena, filmato_id, chiave)
    scena.situazione.forzata = CHIUSO
    errore = _fermato(lambda: seguire.segui_ora(scena.archivio, seguito_id, clic, sam3,
                                                percorso, chiave, scheda=False))
    assert errore.codice == copia.SICURO_CHIUSO
    riga = _seguito(scena, seguito_id)
    assert (riga["stato"], riga["guasto"]) == (seguiti.FALLITO, copia.SOLO_NELL_ARCHIVIO)
    assert sceglitore_finto.seguiti(sam3) == []
    scena.situazione.forzata = None
    seguire.segui_ora(scena.archivio, seguito_id, clic, sam3, percorso, chiave, scheda=False)
    riga = _seguito(scena, seguito_id)
    assert (riga["stato"], riga["guasto"]) == (seguiti.SEGUITO, None)
    [seguito] = sceglitore_finto.seguiti(sam3)
    assert seguito["percorso"] == DALL_ARCHIVIO


def test_la_coda_segue_il_video_dall_archivio(clic, scena, filmato_id, sam3):
    _, _, chiave = ritocco_video._il_video(filmato_id)
    seguito_id = _bozza(scena, filmato_id, chiave)
    seguitore = coda_ritocco.Seguitore(scena.archivio, al_clic=clic, cartella=sam3)
    dove, percorso, chiave_della_coda = seguitore._dove(seguito_id)
    assert dove == sam3 and isinstance(percorso, DallArchivio)
    assert chiave_della_coda == chiave
    sfondo = lavori.Lavoro(lavoro.COSA)
    try:
        assert seguitore.segui(seguito_id, sfondo)
    finally:
        seguitore.lascia(sfondo)
    assert _seguito(scena, seguito_id)["stato"] == seguiti.SEGUITO
    [seguito] = sceglitore_finto.seguiti(sam3)
    assert (seguito["percorso"], seguito["quanti"]) == (DALL_ARCHIVIO, QUANTI)


@pytest.mark.parametrize("forzata, messaggio", [
    (CHIUSO, copia.SOLO_NELL_ARCHIVIO), (SI_APRE, copia.SOLO_NELL_ARCHIVIO),
    (NON_C_E, copia.DA_NESSUNA_PARTE), (SENZA_ARCHIVIO, copia.NON_SUL_DISCO)])
def test_se_la_coda_non_trova_il_video_nell_archivio_lo_dice(clic, scena, filmato_id, sam3,
                                                            forzata, messaggio):
    _, _, chiave = ritocco_video._il_video(filmato_id)
    seguito_id = _bozza(scena, filmato_id, chiave)
    scena.situazione.forzata = forzata
    seguitore = coda_ritocco.Seguitore(scena.archivio, al_clic=clic, cartella=sam3)
    assert _fermato(lambda: seguitore._dove(seguito_id)).messaggio == messaggio


def test_la_coda_non_segue_una_parte_scelta_su_un_altro_video(clic, scena, filmato_id, sam3):
    seguito_id = _bozza(scena, filmato_id, "cd" * 32)
    seguitore = coda_ritocco.Seguitore(scena.archivio, al_clic=clic, cartella=sam3)
    assert _fermato(lambda: seguitore._dove(seguito_id)).messaggio == coda.SEGUITO_VECCHIO


def _ritoccatore(scena, clic, sam3) -> lavoro.Ritoccatore:
    ritoccatore = lavoro.Ritoccatore(
        scena.archivio, coda_ritocco.Seguitore(scena.archivio, al_clic=clic, cartella=sam3),
        a_parte=False)
    assert ritoccatore.parti()
    assert ritoccatore.lavoro.aspetta_che_finisca(60)
    return ritoccatore


def test_ad_archivio_chiuso_si_mette_in_coda_e_la_coda_aspetta_la_password(clic, scena,
                                                                          filmato_id, sam3):
    _, _, chiave = ritocco_video._il_video(filmato_id)
    seguito_id = _bozza(scena, filmato_id, chiave)
    scena.situazione.forzata = CHIUSO
    lavoro_id = coda.metti(scena.archivio, [{"file_id": filmato_id, "seguito_id": seguito_id,
                                             "cosa": elenco.VOLTO}])
    _ritoccatore(scena, clic, sam3)
    with scena.archivio.lettura() as connessione:
        riga = coda.per_id(connessione, lavoro_id)
    assert (riga["stato"], riga["guasto"]) == (coda.IN_CODA, lavoro.ASPETTA)
    assert _seguito(scena, seguito_id)["stato"] != seguiti.FALLITO
    assert sceglitore_finto.seguiti(sam3) == []
    scena.situazione.forzata = None
    _ritoccatore(scena, clic, sam3)
    assert _seguito(scena, seguito_id)["stato"] == seguiti.SEGUITO
    [seguito] = sceglitore_finto.seguiti(sam3)
    assert seguito["percorso"] == DALL_ARCHIVIO
    with scena.archivio.lettura() as connessione:
        riga = coda.per_id(connessione, lavoro_id)
    assert (riga["stato"], riga["guasto"]) == (coda.DA_RIVEDERE, None)


def test_in_coda_un_formato_che_non_si_riscrive_si_riconosce_dal_nome(scena, filmato_id):
    _, _, chiave = ritocco_video._il_video(filmato_id)
    seguito_id = _bozza(scena, filmato_id, chiave)
    with scena.archivio.scrittura() as connessione:
        connessione.execute("UPDATE percorsi SET nome = ?, percorso = ? WHERE file_id = ?",
                            ("onde.avi", str(scena.casa.foto / "s" / "onde.avi"),
                             filmato_id))
    errore = _fermato(lambda: coda.metti(scena.archivio, [{"file_id": filmato_id,
                                                           "seguito_id": seguito_id}]))
    assert errore.messaggio == coda.FORMATO
    assert _in_coda(scena, filmato_id) == []


def test_in_coda_una_parte_scelta_su_un_altro_video_non_entra(scena, filmato_id):
    seguito_id = _bozza(scena, filmato_id, "cd" * 32)
    errore = _fermato(lambda: coda.metti(scena.archivio, [{"file_id": filmato_id,
                                                           "seguito_id": seguito_id}]))
    assert errore.messaggio == coda.SEGUITO_VECCHIO


def _come_il_lavoro(scena, file_id: int) -> tuple:
    da = copia.partenza(scena.archivio, file_id, True)
    return da.copia.name, da.impronta_base


def test_la_coda_e_il_lavoro_partono_dalla_stessa_versione(scena):
    foto = scena.file_id
    sole = _file_id(scena.archivio, "sole.jpg")
    with scena.archivio.lettura() as connessione:
        assert copia.base_per_la_coda(connessione, foto) == (
            "mare.jpg", _impronta(scena.dati[FOTO])) == _come_il_lavoro(scena, foto)
        assert copia.base_per_la_coda(connessione, sole) == (
            "sole.jpg", _impronta(scena.dati[SOLE])) == _come_il_lavoro(scena, sole)
        assert copia.base_per_la_coda(connessione, 10 ** 6) == (None, None)
    migliorata = mostra._approvata(scena)
    with scena.archivio.lettura() as connessione:
        assert copia.base_per_la_coda(connessione, foto) == (
            Path(migliorata["percorso_migliorata"]).name,
            migliorata["impronta_migliorata"]) == _come_il_lavoro(scena, foto)
    ritocco_di_prova._metti(scena)
    with scena.archivio.lettura() as connessione:
        ritoccata = copia.ritoccata(connessione, foto)
        assert copia.base_per_la_coda(connessione, foto) == (
            scena.scatto.name, ritoccata["impronta_base"]) == _come_il_lavoro(scena, foto)
    assert ritoccata["impronta_base"] == migliorata["impronta_migliorata"]


def test_senza_percorsi_la_coda_non_ha_niente(scena):
    sole = _file_id(scena.archivio, "sole.jpg")
    with scena.archivio.scrittura() as connessione:
        connessione.execute("DELETE FROM percorsi WHERE file_id = ?", (sole,))
    with scena.archivio.lettura() as connessione:
        assert copia.base_per_la_coda(connessione, sole) == (None, None)


def test_in_coda_un_video_senza_percorsi_non_c_e(scena, filmato_id):
    _, _, chiave = ritocco_video._il_video(filmato_id)
    seguito_id = _bozza(scena, filmato_id, chiave)
    with scena.archivio.scrittura() as connessione:
        connessione.execute("DELETE FROM percorsi WHERE file_id = ?", (filmato_id,))
    errore = _fermato(lambda: coda.metti(scena.archivio, [{"file_id": filmato_id,
                                                           "seguito_id": seguito_id}]))
    assert errore.messaggio == coda.NON_C_E
    assert _in_coda(scena, filmato_id) == []


def test_la_coda_parte_dal_percorso_che_c_e_sul_disco(scena, filmato_id):
    dati = _dati(scena)
    giusto = _percorso(scena, filmato_id)
    Path(giusto).write_bytes(dati)
    with scena.archivio.scrittura() as connessione:
        connessione.execute(
            "UPDATE percorsi SET nome = ?, percorso = ?, presente = 1 WHERE file_id = ?",
            ("vecchio.avi", str(scena.casa.foto / "vecchio.avi"), filmato_id))
        connessione.execute(
            "INSERT INTO percorsi (file_id, cartella_id, percorso, nome, presente, "
            "visto_il) SELECT file_id, cartella_id, ?, ?, 1, visto_il FROM percorsi "
            "WHERE file_id = ?",
            (giusto, "onde.mp4", filmato_id))
    with scena.archivio.lettura() as connessione:
        assert copia.base_per_la_coda(connessione, filmato_id) == (
            "onde.mp4", _impronta(dati)) == _come_il_lavoro(scena, filmato_id)
    _, percorso, chiave = ritocco_video._il_video(filmato_id)
    assert str(percorso) == giusto and chiave == _impronta(dati)
    bozza = _bozza(scena, filmato_id, chiave)
    coda.metti(scena.archivio, [{"file_id": filmato_id, "seguito_id": bozza}])
    assert len(_in_coda(scena, filmato_id)) == 1


def test_a_parte_il_video_si_legge_dall_archivio_in_un_altro_processo(a_parte, clic, scena,
                                                                      filmato_id, sam3):
    _, percorso, chiave = ritocco_video._il_video(filmato_id)
    preparato = clic.prepara(sam3, chiave, percorso)
    assert (preparato["quanti"], preparato["larghezza"], preparato["altezza"]) == (
        QUANTI, LARGA, ALTA)
    assert in_disparte.sta_girando(ritocco_web.A)
    seguito_id = _bozza(scena, filmato_id, chiave)
    seguire.segui_ora(scena.archivio, seguito_id, clic, sam3, percorso, chiave, scheda=False)
    [seguito] = sceglitore_finto.seguiti(sam3)
    assert seguito["percorso"] == DALL_ARCHIVIO and seguito["pid"] != os.getpid()
    assert _seguito(scena, seguito_id)["stato"] == seguiti.SEGUITO
    scena.situazione.forzata = CHIUSO
    errore = _fermato(lambda: clic.segui(sam3, chiave + "#", percorso, {}, [], scheda=False))
    assert (errore.messaggio, errore.codice) == CHIUSO_ORA


def test_lo_strumento_vero_prepara_il_video_dall_archivio_senza_farne_un_percorso(
        scena, filmato_id):
    from officina.ritocco import scelta

    _, percorso, chiave = ritocco_video._il_video(filmato_id)
    sceglitore = scelta.Sceglitore(scena.casa.foto)
    with copia.leggendo(percorso):
        pronto = sceglitore.prepara(chiave, percorso)
    assert pronto.percorso is percorso and pronto.quanti == QUANTI
    assert pronto.quadro(3).size == (LARGA, ALTA)
