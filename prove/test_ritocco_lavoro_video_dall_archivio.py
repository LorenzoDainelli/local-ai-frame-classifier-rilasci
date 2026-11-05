from __future__ import annotations

import os
import shutil
from pathlib import Path

import numpy
import pytest

from officina.importazione import impronta
from officina.miglioria import attesa, video
from officina.ritocco import coda, copia, elenco, lavoro, pellicola, seguiti
from officina.sicuro import prendi, sportello
from officina.sicuro.dall_archivio import CHIUSO, DallArchivio
from officina.web import in_disparte, seguire
from officina.web.strade import ritocco_video
from prove import test_ritocco_video_dall_archivio as video_di_prova
from prove.test_miglioria_coda_dall_archivio import FILMATO
from prove.test_miglioria_dall_archivio import _mai_in_chiaro
from prove.test_sicuro_dall_archivio import _rovina, _stacca
from prove.test_sicuro_servizio import ATTESA, PAROLA

pytest.importorskip("av")

costo_leggero = video_di_prova.costo_leggero
casa = video_di_prova.casa
cartella = video_di_prova.cartella
importato = video_di_prova.importato
solo_nell_archivio = video_di_prova.solo_nell_archivio
pronta = video_di_prova.pronta
scena = video_di_prova.scena
turno_pulito = video_di_prova.turno_pulito
sam3 = video_di_prova.sam3
clic = video_di_prova.clic
filmato_id = video_di_prova.filmato_id

QUANTI = video_di_prova.QUANTI
PEZZETTO = video_di_prova.PEZZETTO
DENTRO_E_FUORI = [False, True]


def _dati(scena) -> bytes:
    return scena.dati[FILMATO]


def _seguito_pronto(scena, clic, sam3, file_id: int) -> tuple[int, str]:
    _, percorso, chiave = ritocco_video._il_video(file_id)
    seguito_id = video_di_prova._bozza(scena, file_id, chiave)
    seguire.segui_ora(scena.archivio, seguito_id, clic, sam3, percorso, chiave, scheda=True)
    return seguito_id, chiave


def _metti(scena, file_id: int, seguito_id: int) -> int:
    return coda.metti(scena.archivio, [{"file_id": file_id, "seguito_id": seguito_id,
                                        "cosa": elenco.VOLTO}])


def _in_coda(scena, clic, sam3, file_id: int) -> tuple[int, str]:
    seguito_id, chiave = _seguito_pronto(scena, clic, sam3, file_id)
    return _metti(scena, file_id, seguito_id), chiave


def _gira(scena, fuori: bool = False) -> None:
    ritoccatore = lavoro.Ritoccatore(scena.archivio, a_parte=fuori)
    try:
        assert ritoccatore.parti()
        assert ritoccatore.lavoro.aspetta_che_finisca(60)
    finally:
        in_disparte.chiudi(1.0)


def _lavoro(scena, lavoro_id: int) -> tuple:
    with scena.archivio.lettura() as connessione:
        riga = coda.per_id(connessione, lavoro_id)
    return riga["stato"], riga["guasto"]


def _pronti(scena, lavoro_id: int) -> list:
    with scena.archivio.lettura() as connessione:
        return coda.pronti(connessione, lavoro_id)


def _in_attesa(scena) -> list[Path]:
    return [percorso for percorso in scena.casa.foto.rglob("*")
            if percorso.is_file() and attesa.e_dentro(percorso)]


def _quadri(percorso) -> list:
    return list(video.dritti(percorso))


def _dal_disco(scena, lavoro_id: int, file_id: int, chiave: str, dove: Path) -> list:
    dove.mkdir()
    sul_disco = dove / "onde.mp4"
    sul_disco.write_bytes(_dati(scena))
    with scena.archivio.lettura() as connessione:
        ritocchi = coda.da_disegnare(connessione, file_id, lavoro_id)
    strati = lavoro.Ritoccatore(scena.archivio)._strati(ritocchi, chiave)
    pellicola.pixela_il_video(sul_disco, dove / "pixelato.mp4", strati)
    return _quadri(dove / "pixelato.mp4")


def _spia(monkeypatch, nome: str) -> list:
    chiamate: list = []
    vero = getattr(sportello.Sportello, nome)

    def spia(allo_sportello, *argomenti):
        chiamate.append(argomenti)
        return vero(allo_sportello, *argomenti)

    monkeypatch.setattr(sportello.Sportello, nome, spia)
    return chiamate


@pytest.mark.parametrize("fuori", DENTRO_E_FUORI)
def test_il_pixelato_del_video_si_fa_dall_archivio_come_dal_disco(clic, scena, filmato_id,
                                                                 sam3, tmp_path, monkeypatch,
                                                                 fuori):
    lavoro_id, chiave = _in_coda(scena, clic, sam3, filmato_id)
    spie = {nome: _spia(monkeypatch, nome) for nome in ("_apri", "controlla", "chiudi")}
    _gira(scena, fuori)
    assert _lavoro(scena, lavoro_id) == (coda.DA_RIVEDERE, None)
    [riga] = _pronti(scena, lavoro_id)
    fatta = Path(riga["pronta"])
    assert fatta.name == f"{copia.PREFISSO}-{filmato_id}-{lavoro_id}-onde.mp4"
    assert attesa.e_dentro(fatta) and _in_attesa(scena) == [fatta]
    assert (riga["impronta_base"], riga["fotogrammi"]) == (chiave, QUANTI)
    assert riga["impronta_pronta"] == impronta.del_file(fatta)
    assert os.stat(fatta).st_mtime_ns == scena.misure[FILMATO].st_mtime_ns
    assert not os.path.lexists(scena.casa.foto / FILMATO)
    assert bool(spie["_apri"]) == bool(spie["controlla"]) == fuori
    assert len(spie["chiudi"]) == int(fuori)
    _mai_in_chiaro(tmp_path, _dati(scena))
    pixelati = _quadri(fatta)
    attesi = _dal_disco(scena, lavoro_id, filmato_id, chiave, tmp_path / "disco")
    assert len(pixelati) == len(attesi) == QUANTI
    assert all(numpy.array_equal(fatto, atteso)
               for fatto, atteso in zip(pixelati, attesi, strict=True))
    assert not numpy.array_equal(pixelati[5], _quadri(tmp_path / "disco" / "onde.mp4")[5])


def test_se_l_archivio_si_chiude_mentre_il_video_si_pixela_resta_in_coda_e_poi_si_fa(
        clic, scena, filmato_id, sam3, monkeypatch):
    lavoro_id, _ = _in_coda(scena, clic, sam3, filmato_id)
    vero = prendi.Flusso.readinto
    letti: list = []

    def a_pezzi(flusso, spazio):
        letti.append(flusso.tell())
        if len(letti) == 2:
            scena.casa.archivio.chiudi(ATTESA)
        return vero(flusso, memoryview(spazio)[:PEZZETTO])

    with monkeypatch.context() as cambio:
        cambio.setattr(prendi.Flusso, "readinto", a_pezzi)
        _gira(scena)
    assert letti[:2] == [0, PEZZETTO]
    assert _lavoro(scena, lavoro_id) == (coda.IN_CODA, lavoro.ASPETTA)
    assert _in_attesa(scena) == [] and _pronti(scena, lavoro_id) == []
    scena.casa.archivio.apri(PAROLA)
    _gira(scena)
    assert _lavoro(scena, lavoro_id) == (coda.DA_RIVEDERE, None)


def test_se_l_archivio_si_chiude_mentre_il_video_si_apre_resta_in_coda(clic, scena,
                                                                        filmato_id, sam3,
                                                                        monkeypatch):
    lavoro_id, _ = _in_coda(scena, clic, sam3, filmato_id)
    vera = DallArchivio.apri

    def apri(trovata):
        scena.casa.archivio.chiudi(ATTESA)
        return vera(trovata)

    with monkeypatch.context() as cambio:
        cambio.setattr(DallArchivio, "apri", apri)
        _gira(scena)
    assert _lavoro(scena, lavoro_id) == (coda.IN_CODA, lavoro.ASPETTA)
    assert _in_attesa(scena) == []


@pytest.mark.parametrize("nome", ["_cerca", "_apri"])
def test_a_parte_se_l_archivio_si_chiude_il_pixelato_resta_in_coda_e_poi_si_fa(
        clic, scena, filmato_id, sam3, monkeypatch, nome):
    lavoro_id, _ = _in_coda(scena, clic, sam3, filmato_id)
    vero = getattr(sportello.Sportello, nome)
    chiesti: list = []

    def chiude(allo_sportello, *argomenti):
        chiesti.append(argomenti)
        scena.casa.archivio.chiudi(ATTESA)
        return vero(allo_sportello, *argomenti)

    with monkeypatch.context() as cambio:
        cambio.setattr(sportello.Sportello, nome, chiude)
        _gira(scena, True)
    assert len(chiesti) == 1
    assert _lavoro(scena, lavoro_id) == (coda.IN_CODA, lavoro.ASPETTA)
    assert _in_attesa(scena) == [] and _pronti(scena, lavoro_id) == []
    scena.casa.archivio.apri(PAROLA)
    _gira(scena, True)
    assert _lavoro(scena, lavoro_id) == (coda.DA_RIVEDERE, None)


@pytest.mark.parametrize("fuori", DENTRO_E_FUORI)
def test_se_il_pixelato_non_torna_il_video_scritto_a_meta_se_ne_va(clic, scena, filmato_id,
                                                                  sam3, monkeypatch, fuori):
    seguito_id, _ = _seguito_pronto(scena, clic, sam3, filmato_id)
    with scena.archivio.scrittura() as connessione:
        connessione.execute("UPDATE seguiti SET quanti = ? WHERE id = ?",
                            (QUANTI + 1, seguito_id))
        versioni = {numero: versione for numero, (versione, _) in
                    seguiti.scelte(connessione, seguito_id).items()}
        seguiti.scrivi(connessione, seguito_id, [(QUANTI, 5, b"", 0.1)], versioni)
    lavoro_id = _metti(scena, filmato_id, seguito_id)
    vero = pellicola.pixela_il_video
    scritti: list = []

    def guarda_cosa_resta(sorgente, verso, *argomenti):
        try:
            return vero(sorgente, verso, *argomenti)
        finally:
            scritti.append((verso.name, verso.stat().st_size > 0))

    monkeypatch.setattr(pellicola, "pixela_il_video", guarda_cosa_resta)
    _gira(scena, fuori)
    assert _lavoro(scena, lavoro_id) == (coda.FALLITO, pellicola.NON_TORNA)
    assert scritti == ([] if fuori else [
        (f"{copia.PREFISSO}-{filmato_id}-{lavoro_id}-onde.mp4{attesa.PARZIALE}", True)])
    assert _in_attesa(scena) == [] and _pronti(scena, lavoro_id) == []


@pytest.mark.parametrize("fuori", DENTRO_E_FUORI)
def test_un_video_rovinato_nell_archivio_non_si_pixela(clic, scena, filmato_id, sam3, fuori):
    lavoro_id, _ = _in_coda(scena, clic, sam3, filmato_id)
    _stacca(scena.casa)
    _rovina(scena.casa, FILMATO)
    _gira(scena, fuori)
    assert _lavoro(scena, lavoro_id) == (coda.FALLITO, copia.ROVINATA)
    assert _in_attesa(scena) == [] and _pronti(scena, lavoro_id) == []


def test_se_le_date_non_arrivano_il_pixelato_aspetta_l_archivio(clic, scena, filmato_id,
                                                               sam3, monkeypatch):
    lavoro_id, chiave = _in_coda(scena, clic, sam3, filmato_id)
    chieste: list = []
    with monkeypatch.context() as cambio:
        cambio.setattr(scena.casa.archivio, "date",
                       lambda *argomenti: chieste.append(argomenti))
        _gira(scena)
    assert chieste == [(chiave, len(_dati(scena)), str(scena.casa.foto / FILMATO))]
    assert _lavoro(scena, lavoro_id) == (coda.IN_CODA, lavoro.ASPETTA)
    assert _in_attesa(scena) == []
    assert not os.path.lexists(scena.casa.foto / "s" / attesa.NOME)
    _gira(scena)
    assert _lavoro(scena, lavoro_id) == (coda.DA_RIVEDERE, None)


def test_senza_la_cartella_importata_il_video_si_pixela_in_quella_del_programma(
        clic, scena, filmato_id, sam3):
    lavoro_id, _ = _in_coda(scena, clic, sam3, filmato_id)
    shutil.rmtree(scena.casa.foto)
    _gira(scena)
    assert _lavoro(scena, lavoro_id) == (coda.DA_RIVEDERE, None)
    [riga] = _pronti(scena, lavoro_id)
    assert Path(riga["pronta"]).parent == scena.archivio.dove.radice / attesa.NOME
    assert not os.path.lexists(scena.casa.foto)


def test_con_la_ritoccata_e_la_base_solo_nell_archivio_il_video_si_pixela(clic, scena,
                                                                         filmato_id, sam3):
    seguito_id, chiave = _seguito_pronto(scena, clic, sam3, filmato_id)
    video_di_prova._ritoccata_sparita(scena, filmato_id, chiave)
    lavoro_id = _metti(scena, filmato_id, seguito_id)
    _gira(scena)
    assert _lavoro(scena, lavoro_id) == (coda.DA_RIVEDERE, None)
    [riga] = _pronti(scena, lavoro_id)
    assert riga["impronta_base"] == chiave
    assert Path(riga["pronta"]).name == f"{copia.PREFISSO}-{filmato_id}-{lavoro_id}-onde.mp4"


@pytest.mark.parametrize("fuori", DENTRO_E_FUORI)
def test_il_video_sul_disco_si_pixela_anche_ad_archivio_chiuso(clic, scena, filmato_id, sam3,
                                                                monkeypatch, fuori):
    sul_disco = Path(video_di_prova._percorso(scena, filmato_id))
    sul_disco.write_bytes(_dati(scena))
    lavoro_id, _ = _in_coda(scena, clic, sam3, filmato_id)
    scena.situazione.forzata = CHIUSO
    chiusi = _spia(monkeypatch, "chiudi")
    _gira(scena, fuori)
    assert _lavoro(scena, lavoro_id) == (coda.DA_RIVEDERE, None)
    assert chiusi == []
    [riga] = _pronti(scena, lavoro_id)
    assert os.stat(riga["pronta"]).st_mtime_ns == os.stat(sul_disco).st_mtime_ns
