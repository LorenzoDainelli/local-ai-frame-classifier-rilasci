from __future__ import annotations

import dataclasses
import io
import os
import shutil
import socket
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import numpy
import pytest
from PIL import Image

from officina.archivio import accesso, migrazioni
from officina.errori import ErroreOfficina
from officina.importazione.motore import Motore
from officina.miglioria import attesa, coda, metadati
from officina.modello import file_media
from officina.programma import archivio_sicuro, avvio
from officina.ritocco import copia, elenco, in_chiaro, maschere
from officina.sicuro import cestino as cestino_modulo
from officina.sicuro import dall_archivio
from officina.sicuro import servizio as servizio_sicuro
from officina.sicuro.accoglienza import SENZA_CASA, VERSIONE_DIVERSA
from officina.sicuro.cestino import CHIAVETTA, PROBLEMI, RETE
from officina.sicuro.dall_archivio import (CHIUSO, NON_C_E, SENZA_ARCHIVIO, SI_APRE,
                                           TROVATA, Ricerca)
from prove import test_miglioria_coda_dall_archivio as coda_di_prova
from prove import test_miglioria_mostra_dall_archivio as mostra
from prove import test_miglioria_scambio_dall_archivio as scambio_di_prova
from prove.test_miglioria_coda_dall_archivio import ALTRA, FOTO, _file_id
from prove.test_miglioria_dall_archivio import _mai_in_chiaro
from prove.test_miglioria_scambio_dall_archivio import _Accoglie, _estrai, _eventi, _percorsi
from prove.test_sicuro_cestino import CestinoFinto, Crollo
from prove.test_sicuro_dall_archivio import (_impronta, _jpeg, _rovina, _Situazione,
                                             _stacca)
from prove.test_sicuro_servizio import ATTESA, LEGGERO, PAROLA, _finche

pytest.importorskip("av")

costo_leggero = scambio_di_prova.costo_leggero
casa = scambio_di_prova.casa
cartella = scambio_di_prova.cartella
importato = scambio_di_prova.importato
solo_nell_archivio = scambio_di_prova.solo_nell_archivio
pronta = scambio_di_prova.pronta

IL_VERO_CESTINO = archivio_sicuro.il_cestino

ZONA = (8, 8, 40, 40)
ALTRA_ZONA = (48, 8, 80, 40)


def _misure(dati: bytes) -> tuple[int, int]:
    with Image.open(io.BytesIO(dati)) as foto:
        return foto.size


def _volto(dati: bytes, zona=ZONA) -> dict:
    larga, alta = _misure(dati)
    scelta = numpy.zeros((alta, larga), dtype=bool)
    sinistra, sopra, destra, sotto = zona
    scelta[sopra:sotto, sinistra:destra] = True
    return {"cosa": elenco.VOLTO, "larghezza": larga, "altezza": alta,
            "maschera": maschere.comprimi(scelta, (0, 0), larga, alta),
            "misura": destra - sinistra}


def _ritoccata(scena):
    with scena.archivio.lettura() as connessione:
        return copia.ritoccata(connessione, scena.file_id)


def _rimaste(scena) -> list:
    with scena.archivio.lettura() as connessione:
        return [dict(riga) for riga in in_chiaro.rimaste(connessione)]


def _grigio(dati: bytes) -> numpy.ndarray:
    with Image.open(io.BytesIO(dati)) as foto:
        return numpy.asarray(foto.convert("L"), dtype=float)


def _quanto_varia(dati: bytes, zona=ZONA) -> float:
    sinistra, sopra, destra, sotto = zona
    pezzo = _grigio(dati)[sopra:sotto, sinistra:destra]
    return float(numpy.abs(numpy.diff(pezzo, axis=1)).mean())


@pytest.fixture
def scena(pronta):
    pronta.file_id = _file_id(pronta.archivio, "mare.jpg")
    pronta.scatto = pronta.casa.foto / FOTO
    pronta.base = pronta.scatto.parent / attesa.ORIGINALI / pronta.scatto.name
    return pronta


def _metti(scena, zona=ZONA):
    return copia.metti(scena.archivio, scena.file_id, [_volto(scena.dati[FOTO], zona)])


def _storia(scena, relativo: str) -> list[tuple[str, bool]]:
    radice, = scena.casa.radici()
    quaderno = scena.casa.aperto.elenco
    return [(quaderno.contenuto(posto.contenuto)["blake2b"], posto.sparito is None)
            for posto in quaderno.storia(radice["id"], relativo)]


def _attivi(scena) -> list:
    with scena.archivio.lettura() as connessione:
        return elenco.di_file(connessione, scena.file_id)


def _in_attesa(scena) -> list[Path]:
    return [percorso for percorso in scena.casa.foto.rglob("*")
            if percorso.is_file() and attesa.e_dentro(percorso)]


def _estratta(scena, tmp_path, nome: str = "fuori") -> dict[str, bytes]:
    return _estrai(scena, tmp_path / nome)


def _fermato(fare) -> copia.RitoccoFermato:
    with pytest.raises(copia.RitoccoFermato) as preso:
        fare()
    return preso.value


def _falliti(scena) -> list:
    with scena.archivio.lettura() as connessione:
        return [ritocco["guasto"] for ritocco in
                elenco.di_file(connessione, scena.file_id, elenco.FALLITO)]


def _fai(scena, come: str):
    if come == "metti":
        return _metti(scena, ALTRA_ZONA)
    if come == "togli":
        [ritocco] = _attivi(scena)
        return copia.togli(scena.archivio, ritocco["id"])
    return copia.torna(scena.archivio, scena.file_id)


def _com_era(scena, prima: dict, come: str, perche: str) -> None:
    assert dict(_ritoccata(scena)) == prima
    assert _in_attesa(scena) == [] and len(scena.casa.cestino.mosse) == 1
    assert _storia(scena, FOTO)[-1] == (prima["impronta_copia"], True)
    assert len(_attivi(scena)) == 1
    assert _falliti(scena) == ([perche] if come == "metti" else [])


def test_il_primo_ritocco_va_solo_nell_archivio(scena, tmp_path, monkeypatch):
    eventi = _eventi(monkeypatch)
    with scena.archivio.scrittura() as connessione:
        connessione.execute("UPDATE file_media SET miniatura = 'vecchia.jpg' WHERE id = ?",
                            (scena.file_id,))
    assert _metti(scena) == scena.scatto
    riga = _ritoccata(scena)
    assert riga["stato"] == copia.FATTA and riga["nell_archivio"] == 1
    assert riga["percorso_copia"] == str(scena.scatto)
    assert riga["percorso_base"] == str(scena.base)
    assert riga["impronta_base"] == _impronta(scena.dati[FOTO])
    assert riga["dimensione_base"] == len(scena.dati[FOTO])
    assert riga["base_e"] == copia.ORIGINALE and riga["miglioria_id"] is None
    assert riga["impronta_copia"] not in (None, riga["impronta_base"])
    assert riga["in_preparazione"] is None and riga["impronta_nuova"] is None
    assert riga["guasto"] is None and riga["da_rifare"] == 0 and riga["fatta_il"]
    assert _percorsi(scena.archivio, scena.file_id) == [(str(scena.base), 0)]
    with scena.archivio.lettura() as connessione:
        assert file_media.per_id(connessione, scena.file_id)["miniatura"] is None
    [mossa] = scena.casa.cestino.mosse
    assert Path(mossa).name == f"{copia.PREFISSO}-{scena.file_id}-mare.jpg"
    assert attesa.e_dentro(Path(mossa)) and not os.path.lexists(mossa)
    assert not os.path.lexists(scena.scatto) and not os.path.lexists(scena.base)
    assert _rimaste(scena) == []
    assert eventi[-2:] == [
        ("ritocco.scambio_inizio", {"file": scena.file_id}),
        ("ritocco.scambio_fatto", {"file": scena.file_id, "nell_archivio": True,
                                   "gia_fatto": False})]
    _mai_in_chiaro(tmp_path, scena.dati[FOTO])
    estratti = _estrai(scena, tmp_path / "fuori")
    ritoccata = estratti["foto/s/mare.jpg"]
    assert _impronta(ritoccata) == riga["impronta_copia"]
    assert estratti[f"foto/s/{attesa.ORIGINALI}/mare.jpg"] == scena.dati[FOTO]
    assert _quanto_varia(ritoccata) < _quanto_varia(scena.dati[FOTO])
    dentro = scena.casa.cestino.dentro
    for percorso in tmp_path.rglob("*"):
        if (percorso.is_file() and not str(percorso).startswith(dentro)
                and not str(percorso).startswith(str(tmp_path / "fuori"))):
            assert percorso.read_bytes() != ritoccata, percorso


def test_la_copia_ritoccata_nell_archivio_ha_le_date_dello_scatto(scena):
    _metti(scena)
    riga = _ritoccata(scena)
    date = scena.casa.archivio.date(riga["impronta_copia"], None, str(scena.scatto))
    assert date["modifica"] == scena.misure[FOTO].st_mtime_ns


def test_il_secondo_ritocco_sostituisce_la_copia_e_la_prima_resta_nella_storia(
        scena, tmp_path, monkeypatch):
    _metti(scena)
    prima = _ritoccata(scena)
    spia = _Accoglie(scena, monkeypatch)
    eventi = _eventi(monkeypatch)
    assert _metti(scena, ALTRA_ZONA) == scena.scatto
    dopo = _ritoccata(scena)
    assert dopo["stato"] == copia.FATTA and dopo["nell_archivio"] == 1
    assert dopo["impronta_copia"] not in (None, prima["impronta_copia"],
                                          prima["impronta_base"])
    assert dopo["percorso_copia"] == prima["percorso_copia"]
    assert dopo["percorso_base"] == prima["percorso_base"]
    assert dopo["in_preparazione"] is None and dopo["guasto"] is None
    [chiesta] = spia.chieste
    assert chiesta == {
        "come": copia.SOSTITUISCI, "copia": str(scena.scatto),
        "impronta": prima["impronta_copia"], "nuova": chiesta["nuova"],
        "impronta_nuova": dopo["impronta_copia"], "base": str(scena.base),
        "impronta_base": prima["impronta_base"]}
    assert Path(chiesta["nuova"]).name == f"{copia.PREFISSO}-{scena.file_id}-mare.jpg"
    assert len(scena.casa.cestino.mosse) == 2
    assert not [mossa for mossa in scena.casa.cestino.mosse if os.path.lexists(mossa)]
    assert _rimaste(scena) == [] and _in_attesa(scena) == []
    originale = prima["impronta_base"]
    assert _storia(scena, FOTO) == [(originale, False), (prima["impronta_copia"], False),
                                    (dopo["impronta_copia"], True)]
    assert _storia(scena, f"s/{attesa.ORIGINALI}/mare.jpg") == [(originale, True)]
    assert eventi[-1] == ("ritocco.scambio_fatto", {
        "file": scena.file_id, "nell_archivio": True, "gia_fatto": False})
    assert len(_attivi(scena)) == 2
    _mai_in_chiaro(tmp_path, scena.dati[FOTO])
    estratti = _estratta(scena, tmp_path)
    ritoccata = estratti["foto/s/mare.jpg"]
    assert _impronta(ritoccata) == dopo["impronta_copia"]
    for zona in (ZONA, ALTRA_ZONA):
        assert _quanto_varia(ritoccata, zona) < _quanto_varia(scena.dati[FOTO], zona)


def test_togliere_un_ritocco_rifa_la_copia_dallo_scatto_nell_archivio(scena, tmp_path):
    _metti(scena)
    _metti(scena, ALTRA_ZONA)
    seconda = _ritoccata(scena)
    primo, _ = _attivi(scena)
    assert copia.togli(scena.archivio, primo["id"]) == scena.scatto
    dopo = _ritoccata(scena)
    assert dopo["stato"] == copia.FATTA and dopo["nell_archivio"] == 1
    assert dopo["impronta_copia"] not in (None, seconda["impronta_copia"])
    assert [ritocco["id"] for ritocco in _attivi(scena)] != [primo["id"]]
    assert len(_attivi(scena)) == 1
    assert _storia(scena, FOTO)[-2:] == [(seconda["impronta_copia"], False),
                                         (dopo["impronta_copia"], True)]
    assert _rimaste(scena) == [] and _in_attesa(scena) == []
    _mai_in_chiaro(tmp_path, scena.dati[FOTO])
    ritoccata = _estratta(scena, tmp_path)["foto/s/mare.jpg"]
    assert _impronta(ritoccata) == dopo["impronta_copia"]
    assert _quanto_varia(ritoccata, ZONA) > 0.9 * _quanto_varia(scena.dati[FOTO], ZONA)
    assert _quanto_varia(ritoccata, ALTRA_ZONA) < _quanto_varia(scena.dati[FOTO],
                                                                ALTRA_ZONA)


def _togli_tutti(scena, come: str):
    if come == "togli":
        [ritocco] = _attivi(scena)
        return copia.togli(scena.archivio, ritocco["id"])
    with scena.archivio.scrittura() as connessione:
        for ritocco in elenco.di_file(connessione, scena.file_id):
            elenco.segna(connessione, ritocco["id"], elenco.TOLTO)
    return copia.torna(scena.archivio, scena.file_id)


@pytest.mark.parametrize("come", ["togli", "torna"])
def test_togliendo_tutti_i_ritocchi_torna_lo_scatto_e_la_copia_resta_nella_storia(
        scena, tmp_path, monkeypatch, come):
    _metti(scena)
    prima = _ritoccata(scena)
    with scena.archivio.scrittura() as connessione:
        connessione.execute("UPDATE file_media SET miniatura = 'vecchia.jpg' WHERE id = ?",
                            (scena.file_id,))
    spia = _Accoglie(scena, monkeypatch)
    eventi = _eventi(monkeypatch)
    assert _togli_tutti(scena, come) == scena.scatto
    assert _ritoccata(scena) is None
    assert spia.chieste == [{
        "come": copia.RIMETTI, "copia": str(scena.scatto),
        "impronta": prima["impronta_copia"], "base": str(scena.base),
        "impronta_base": prima["impronta_base"]}]
    assert _percorsi(scena.archivio, scena.file_id) == [(str(scena.scatto), 0)]
    with scena.archivio.lettura() as connessione:
        assert file_media.per_id(connessione, scena.file_id)["miniatura"] is None
    assert eventi[-1] == ("ritocco.tornato", {"file": scena.file_id, "nell_archivio": True,
                                              "gia_fatto": False})
    assert len(scena.casa.cestino.mosse) == 1
    assert not os.path.lexists(scena.scatto) and not os.path.lexists(scena.base)
    assert _rimaste(scena) == [] and _in_attesa(scena) == []
    originale = prima["impronta_base"]
    assert _storia(scena, FOTO) == [(originale, False), (prima["impronta_copia"], False),
                                    (originale, True)]
    assert _storia(scena, f"s/{attesa.ORIGINALI}/mare.jpg") == [(originale, False)]
    _mai_in_chiaro(tmp_path, scena.dati[FOTO])
    estratti = _estratta(scena, tmp_path)
    assert estratti["foto/s/mare.jpg"] == scena.dati[FOTO]
    assert not [nome for nome in estratti if f"/{attesa.ORIGINALI}/" in nome]


def test_dopo_aver_tolto_tutto_si_ritocca_di_nuovo(scena, tmp_path):
    _metti(scena)
    _togli_tutti(scena, "togli")
    assert _metti(scena, ALTRA_ZONA) == scena.scatto
    riga = _ritoccata(scena)
    assert riga["stato"] == copia.FATTA and riga["nell_archivio"] == 1
    assert riga["percorso_base"] == str(scena.base)
    assert _percorsi(scena.archivio, scena.file_id) == [(str(scena.base), 0)]
    assert len(scena.casa.cestino.mosse) == 2
    _mai_in_chiaro(tmp_path, scena.dati[FOTO])
    estratti = _estratta(scena, tmp_path)
    assert _impronta(estratti["foto/s/mare.jpg"]) == riga["impronta_copia"]
    assert estratti[f"foto/s/{attesa.ORIGINALI}/mare.jpg"] == scena.dati[FOTO]


@pytest.mark.parametrize("forzata", [CHIUSO, SI_APRE])
def test_con_l_archivio_chiuso_il_primo_ritocco_non_parte(scena, monkeypatch, forzata):
    percorsi = _percorsi(scena.archivio, scena.file_id)
    spia = _Accoglie(scena, monkeypatch)
    scena.situazione.forzata = forzata
    errore = _fermato(lambda: _metti(scena))
    assert errore.codice == copia.SICURO_CHIUSO
    assert str(errore) == ("Lo scatto senza ritocchi c'è solo nell'Archivio sicuro, che è "
                           "chiuso: aprilo e riprova. Nessun file è stato toccato.")
    assert _ritoccata(scena) is None and spia.chieste == []
    assert _falliti(scena) == [copia.SOLO_NELL_ARCHIVIO] and _attivi(scena) == []
    assert _in_attesa(scena) == [] and scena.casa.cestino.mosse == []
    assert _percorsi(scena.archivio, scena.file_id) == percorsi
    scena.situazione.forzata = None
    assert _metti(scena) == scena.scatto
    assert _ritoccata(scena)["stato"] == copia.FATTA


def test_senza_archivio_lo_scatto_non_si_trova(scena, monkeypatch):
    spia = _Accoglie(scena, monkeypatch)
    scena.situazione.forzata = SENZA_ARCHIVIO
    errore = _fermato(lambda: _metti(scena))
    assert errore.codice == copia.RitoccoFermato.codice
    assert str(errore) == "Lo scatto non si trova sul disco: non lo ritocco."
    assert _ritoccata(scena) is None and spia.chieste == []
    assert _in_attesa(scena) == []


@pytest.mark.parametrize("come", ["metti", "togli", "torna"])
@pytest.mark.parametrize("forzata", [CHIUSO, SI_APRE])
def test_con_l_archivio_chiuso_un_ritocco_fatto_non_si_cambia(scena, monkeypatch, come,
                                                              forzata):
    _metti(scena)
    prima = dict(_ritoccata(scena))
    spia = _Accoglie(scena, monkeypatch)
    scena.situazione.forzata = forzata
    errore = _fermato(lambda: _fai(scena, come))
    assert errore.codice == copia.SICURO_CHIUSO and str(errore) == copia.SOLO_NELL_ARCHIVIO
    assert spia.chieste == []
    _com_era(scena, prima, come, copia.SOLO_NELL_ARCHIVIO)


@pytest.mark.parametrize("come", ["metti", "togli", "torna"])
def test_con_la_copia_sul_disco_e_lo_scatto_solo_nell_archivio_non_si_mescola(
        scena, monkeypatch, come):
    _metti(scena)
    prima = dict(_ritoccata(scena))
    scena.scatto.write_bytes(b"rimessa a mano")
    spia = _Accoglie(scena, monkeypatch)
    errore = _fermato(lambda: _fai(scena, come))
    assert errore.codice == copia.RitoccoFermato.codice
    assert str(errore) == ("La copia ritoccata è sul disco, ma lo scatto senza ritocchi c'è "
                           "solo nell'Archivio sicuro: non lo ritocco per non mescolare. "
                           "Nessun file è stato toccato.")
    assert spia.chieste == [] and scena.scatto.read_bytes() == b"rimessa a mano"
    _com_era(scena, prima, come, copia.MESCOLATI)


@pytest.mark.parametrize("come", ["metti", "togli", "torna"])
@pytest.mark.parametrize("forzata", [CHIUSO, SI_APRE])
def test_con_la_copia_sul_disco_e_l_archivio_chiuso_non_si_mescola(scena, monkeypatch,
                                                                  come, forzata):
    _metti(scena)
    prima = dict(_ritoccata(scena))
    scena.scatto.write_bytes(b"rimessa a mano")
    scena.situazione.forzata = forzata
    errore = _fermato(lambda: _fai(scena, come))
    assert str(errore) == copia.MESCOLATI_FORSE
    assert scena.scatto.read_bytes() == b"rimessa a mano"
    scena.situazione.forzata = None
    _com_era(scena, prima, come, copia.MESCOLATI_FORSE)


@pytest.mark.parametrize("sul_disco", [False, True])
@pytest.mark.parametrize("come", ["metti", "togli", "torna"])
def test_se_l_archivio_non_ha_lo_scatto_senza_ritocchi_non_si_tocca_niente(
        scena, monkeypatch, come, sul_disco):
    _metti(scena)
    with scena.archivio.scrittura() as connessione:
        connessione.execute("UPDATE ritoccate SET impronta_base = ? WHERE file_id = ?",
                            (ALTRA, scena.file_id))
    prima = dict(_ritoccata(scena))
    if sul_disco:
        scena.scatto.write_bytes(b"rimessa a mano")
    spia = _Accoglie(scena, monkeypatch)
    errore = _fermato(lambda: _fai(scena, come))
    assert str(errore) == ("Non trovo lo scatto senza ritocchi né sul disco né "
                           "nell'Archivio sicuro: non lo ritocco. Nessun file è stato "
                           "toccato.")
    assert spia.chieste == []
    _com_era(scena, prima, come, copia.DA_NESSUNA_PARTE)


@pytest.mark.parametrize("come", ["metti", "togli", "torna"])
def test_se_l_archivio_da_un_altro_scatto_non_si_tocca_niente(scena, monkeypatch, come):
    _metti(scena)
    prima = dict(_ritoccata(scena))
    with scena.archivio.lettura() as connessione:
        della_copia = file_media.cerca_uguale(connessione, scena.file_id,
                                              prima["impronta_copia"], str(scena.scatto))
    assert della_copia.trovata is not None
    monkeypatch.setattr(file_media, "cerca_uguale", lambda *argomenti, **piu: della_copia)
    spia = _Accoglie(scena, monkeypatch)
    errore = _fermato(lambda: _fai(scena, come))
    assert str(errore) == copia.CAMBIATO and spia.chieste == []
    monkeypatch.undo()
    _com_era(scena, prima, come, copia.CAMBIATO)


@pytest.mark.parametrize("come", ["metti", "togli", "torna"])
def test_senza_archivio_un_ritocco_fatto_nell_archivio_non_si_cambia(scena, monkeypatch,
                                                                    come):
    _metti(scena)
    prima = dict(_ritoccata(scena))
    spia = _Accoglie(scena, monkeypatch)
    scena.situazione.forzata = SENZA_ARCHIVIO
    errore = _fermato(lambda: _fai(scena, come))
    assert spia.chieste == []
    if come == "metti":
        assert str(errore) == copia.CAMBIATO
    else:
        assert str(errore) == ("Non trovo lo scatto senza ritocchi in «Originali»: tengo la "
                               "copia ritoccata com'è. Nessun file è stato toccato.")
    scena.situazione.forzata = None
    _com_era(scena, prima, come, copia.CAMBIATO)


def _niente_fatto(scena, spia, perche: str) -> None:
    assert _ritoccata(scena) is None and spia.chieste == []
    assert _falliti(scena) == [perche] and _attivi(scena) == []
    assert _in_attesa(scena) == [] and scena.casa.cestino.mosse == []
    assert _storia(scena, FOTO) == [(_impronta(scena.dati[FOTO]), True)]


@pytest.mark.parametrize("perche, messaggio, codice", [
    (SENZA_CASA, copia.SENZA_CARTELLA, copia.RitoccoFermato.codice),
    (VERSIONE_DIVERSA, copia.DIVERSA, copia.RitoccoFermato.codice),
    (NON_C_E, copia.DA_NESSUNA_PARTE, copia.RitoccoFermato.codice),
    (CHIUSO, copia.SOLO_NELL_ARCHIVIO, copia.SICURO_CHIUSO),
    (SI_APRE, copia.SOLO_NELL_ARCHIVIO, copia.SICURO_CHIUSO)])
def test_senza_sapere_dove_stava_lo_scatto_non_si_ritocca(scena, monkeypatch, perche,
                                                         messaggio, codice):
    monkeypatch.setattr(file_media, "casa_nell_archivio",
                        lambda *argomenti: (None, perche))
    spia = _Accoglie(scena, monkeypatch)
    errore = _fermato(lambda: _metti(scena))
    assert str(errore) == messaggio and errore.codice == codice
    _niente_fatto(scena, spia, messaggio)


def test_i_messaggi_quando_non_si_sa_dove_stava_lo_scatto():
    assert copia.SENZA_CARTELLA == ("Questo scatto è nell'Archivio sicuro, ma non so in che "
                                    "cartella stava: non lo ritocco. Nessun file è stato "
                                    "toccato.")
    assert copia.DIVERSA == ("Nell'Archivio sicuro c'è solo una versione cambiata di questo "
                             "scatto: non la ritocco. Nessun file è stato toccato.")


def _trovata_cambiata(scena, **cambi) -> Ricerca:
    with scena.archivio.lettura() as connessione:
        ricerca = file_media.cerca_nell_archivio(connessione, scena.file_id)
    assert ricerca.perche == TROVATA and not ricerca.diversa
    return Ricerca(ricerca.perche, dataclasses.replace(ricerca.trovata, **cambi))


@pytest.mark.parametrize("cambi", [{"diversa": True}, {"blake2b": ALTRA}])
def test_con_solo_una_versione_cambiata_nell_archivio_non_si_ritocca(scena, monkeypatch,
                                                                    cambi):
    ricerca = _trovata_cambiata(scena, **cambi)
    monkeypatch.setattr(file_media, "cerca_nell_archivio", lambda *argomenti: ricerca)
    spia = _Accoglie(scena, monkeypatch)
    errore = _fermato(lambda: _metti(scena))
    assert str(errore) == copia.DIVERSA
    _niente_fatto(scena, spia, copia.DIVERSA)


def test_se_lo_scatto_nel_programma_e_cambiato_non_si_ritocca(scena, monkeypatch):
    with scena.archivio.scrittura() as connessione:
        connessione.execute("UPDATE file_media SET impronta = ? WHERE id = ?",
                            (ALTRA, scena.file_id))
    spia = _Accoglie(scena, monkeypatch)
    errore = _fermato(lambda: _metti(scena))
    assert str(errore) == copia.DIVERSA
    assert _ritoccata(scena) is None and spia.chieste == []
    assert _in_attesa(scena) == [] and scena.casa.cestino.mosse == []


def test_se_l_archivio_non_trova_lo_scatto_non_si_ritocca(scena, monkeypatch):
    monkeypatch.setattr(file_media, "cerca_nell_archivio",
                        lambda *argomenti: Ricerca(NON_C_E))
    spia = _Accoglie(scena, monkeypatch)
    errore = _fermato(lambda: _metti(scena))
    assert str(errore) == copia.DA_NESSUNA_PARTE
    _niente_fatto(scena, spia, copia.DA_NESSUNA_PARTE)


def _non_risponde(*argomenti, **piu):
    raise ErroreOfficina("sta già facendo altro", codice="occupato")


@pytest.mark.parametrize("dove", ["cerca_nell_archivio", "casa_nell_archivio", "date"])
def test_se_l_archivio_non_risponde_il_primo_ritocco_non_parte(scena, monkeypatch, dove):
    if dove == "date":
        monkeypatch.setattr(scena.casa.archivio, "date", _non_risponde)
    else:
        monkeypatch.setattr(file_media, dove, _non_risponde)
    spia = _Accoglie(scena, monkeypatch)
    avvisi = _eventi(monkeypatch, "avviso")
    errore = _fermato(lambda: _metti(scena))
    assert errore.codice == copia.SICURO_CHIUSO and str(errore) == copia.SOLO_NELL_ARCHIVIO
    assert avvisi == [("ritocco.archivio_non_risponde", {"motivo": "occupato"})]
    _niente_fatto(scena, spia, copia.SOLO_NELL_ARCHIVIO)


@pytest.mark.parametrize("come", ["metti", "togli", "torna"])
def test_se_l_archivio_non_risponde_un_ritocco_fatto_non_si_cambia(scena, monkeypatch,
                                                                  come):
    _metti(scena)
    prima = dict(_ritoccata(scena))
    monkeypatch.setattr(file_media, "cerca_uguale", _non_risponde)
    spia = _Accoglie(scena, monkeypatch)
    avvisi = _eventi(monkeypatch, "avviso")
    errore = _fermato(lambda: _fai(scena, come))
    assert errore.codice == copia.SICURO_CHIUSO and spia.chieste == []
    assert avvisi == [("ritocco.archivio_non_risponde", {"motivo": "occupato"})]
    monkeypatch.undo()
    _com_era(scena, prima, come, copia.SOLO_NELL_ARCHIVIO)


def test_se_le_date_non_arrivano_il_secondo_ritocco_non_parte(scena, monkeypatch):
    _metti(scena)
    prima = dict(_ritoccata(scena))
    monkeypatch.setattr(scena.casa.archivio, "date", lambda *argomenti: None)
    spia = _Accoglie(scena, monkeypatch)
    errore = _fermato(lambda: _metti(scena, ALTRA_ZONA))
    assert errore.codice == copia.SICURO_CHIUSO and spia.chieste == []
    monkeypatch.undo()
    _com_era(scena, prima, "metti", copia.SOLO_NELL_ARCHIVIO)


def test_se_le_date_non_arrivano_il_primo_ritocco_non_parte(scena, monkeypatch):
    chieste = []

    def date(*argomenti):
        chieste.append(argomenti)

    monkeypatch.setattr(scena.casa.archivio, "date", date)
    spia = _Accoglie(scena, monkeypatch)
    errore = _fermato(lambda: _metti(scena))
    assert errore.codice == copia.SICURO_CHIUSO
    assert chieste == [(_impronta(scena.dati[FOTO]), len(scena.dati[FOTO]),
                        str(scena.scatto))]
    _niente_fatto(scena, spia, copia.SOLO_NELL_ARCHIVIO)


def test_uno_scatto_rovinato_nell_archivio_non_si_ritocca(scena, monkeypatch):
    _stacca(scena.casa)
    _rovina(scena.casa, FOTO)
    spia = _Accoglie(scena, monkeypatch)
    errore = _fermato(lambda: _metti(scena))
    assert str(errore) == ("Nell'Archivio sicuro lo scatto senza ritocchi è rovinato: non "
                           "lo ritocco. Nessun file è stato toccato.")
    assert _ritoccata(scena) is None and spia.chieste == []
    assert _in_attesa(scena) == [] and scena.casa.cestino.mosse == []


def test_l_archivio_riceve_la_richiesta_giusta_al_primo_ritocco(scena, monkeypatch):
    spia = _Accoglie(scena, monkeypatch)
    _metti(scena)
    riga = _ritoccata(scena)
    [chiesta] = spia.chieste
    dati = scena.dati[FOTO]
    assert chiesta == {
        "originale": str(scena.scatto), "impronta": _impronta(dati),
        "dimensione": len(dati), "nuova": chiesta["nuova"],
        "impronta_nuova": riga["impronta_copia"], "verso": str(scena.scatto),
        "spostato": str(scena.base)}
    assert Path(chiesta["nuova"]) == (scena.casa.foto / attesa.NOME /
                                      f"{copia.PREFISSO}-{scena.file_id}-mare.jpg")


def _sul_disco_prima(scena, spia) -> None:
    def mettine_uno(richiesta):
        scena.scatto.write_bytes(b"un altro")

    spia.prima = mettine_uno


def _intoppo(scena, spia, monkeypatch, modo) -> None:
    if modo == "occupato":
        spia.modo = ErroreOfficina("sta già facendo altro", codice="occupato")
    elif modo == "rotto":
        spia.modo = RuntimeError("rotto")
    elif modo == "sul_disco":
        _sul_disco_prima(scena, spia)
    elif modo == "chiuso":
        monkeypatch.setattr(archivio_sicuro, "per_le_foto",
                            lambda: (TROVATA, scena.casa.archivio))
        spia.prima = lambda richiesta: scena.casa.archivio.chiudi(ATTESA)
    elif modo == "sparito":
        vera, fatte = copia._prepara, []

        def prepara(*argomenti, **piu):
            fatte.append(vera(*argomenti, **piu))
            if len(fatte) == 1:
                scena.situazione.forzata = SENZA_ARCHIVIO
            return fatte[-1]

        monkeypatch.setattr(copia, "_prepara", prepara)
    else:
        spia.modo = modo


NON_SALVATO_SUL_DISCO = ("Il ritocco non è stato salvato. Sul disco c'è già un file con lo "
                         "stesso nome: non lo copro. Non ho cambiato niente nell'archivio.")
NON_PRESO = ("L'Archivio sicuro non ha preso il ritocco: non è stato salvato. Nessun file è "
             "stato toccato.")
CHIUSO_ADESSO = ("Lo scatto senza ritocchi c'è solo nell'Archivio sicuro, che è chiuso: "
                 "aprilo e riprova. Nessun file è stato toccato.")


@pytest.mark.parametrize("modo, messaggio, codice", [
    ("muto", NON_PRESO, copia.RitoccoFermato.codice),
    ("occupato", NON_PRESO, "occupato"),
    ("sul_disco", NON_SALVATO_SUL_DISCO, "sul_disco"),
    ("chiuso", CHIUSO_ADESSO, copia.SICURO_CHIUSO),
    ("sparito", CHIUSO_ADESSO, copia.SICURO_CHIUSO)])
def test_se_l_archivio_non_prende_il_primo_ritocco_non_resta_niente(
        scena, tmp_path, monkeypatch, modo, messaggio, codice):
    spia = _Accoglie(scena, monkeypatch)
    _intoppo(scena, spia, monkeypatch, modo)
    errori = _eventi(monkeypatch, "errore")
    errore = _fermato(lambda: _metti(scena))
    assert str(errore) == messaggio and errore.codice == codice
    assert len(spia.chieste) == (0 if modo == "sparito" else 1)
    assert _ritoccata(scena) is None
    assert _falliti(scena) == [messaggio] and _attivi(scena) == []
    assert _in_attesa(scena) == [] and scena.casa.cestino.mosse == []
    assert ("ritocco.scambio_disfatto", {"file": scena.file_id}) in errori
    if modo == "sul_disco":
        assert scena.scatto.read_bytes() == b"un altro"
        scena.scatto.unlink()
    if modo == "chiuso":
        scena.casa.archivio.apri(PAROLA)
    scena.situazione.forzata = None
    assert _storia(scena, FOTO) == [(_impronta(scena.dati[FOTO]), True)]
    _mai_in_chiaro(tmp_path, scena.dati[FOTO])
    spia.modo, spia.prima = None, None
    assert _metti(scena) == scena.scatto
    assert _ritoccata(scena)["stato"] == copia.FATTA


@pytest.mark.parametrize("modo, messaggio, codice", [
    ("muto", NON_PRESO, copia.RitoccoFermato.codice),
    ("occupato", NON_PRESO, "occupato"),
    ("sul_disco", NON_SALVATO_SUL_DISCO, "sul_disco"),
    ("chiuso", CHIUSO_ADESSO, copia.SICURO_CHIUSO)])
@pytest.mark.parametrize("come", ["metti", "togli", "torna"])
def test_se_l_archivio_non_prende_un_cambio_resta_il_ritocco_di_prima(
        scena, monkeypatch, come, modo, messaggio, codice):
    _metti(scena)
    prima = dict(_ritoccata(scena))
    spia = _Accoglie(scena, monkeypatch)
    _intoppo(scena, spia, monkeypatch, modo)
    errori = _eventi(monkeypatch, "errore")
    errore = _fermato(lambda: _fai(scena, come))
    assert str(errore) == messaggio and errore.codice == codice
    assert len(spia.chieste) == 1
    assert spia.chieste[0].get("come") == (copia.SOSTITUISCI if come == "metti"
                                           else copia.RIMETTI)
    assert ("ritocco.scambio_disfatto", {"file": scena.file_id}) in errori
    if modo == "sul_disco":
        assert scena.scatto.read_bytes() == b"un altro"
        scena.scatto.unlink()
    if modo == "chiuso":
        scena.casa.archivio.apri(PAROLA)
    _com_era(scena, prima, come, messaggio)


def _a_meta(scena, monkeypatch, modo="a_meta"):
    spia = _Accoglie(scena, monkeypatch)
    spia.modo = modo
    errore = _fermato(lambda: _metti(scena))
    riga = _ritoccata(scena)
    assert riga["stato"] == copia.IN_SCAMBIO and riga["nell_archivio"] == 1
    assert riga["guasto"] == copia.A_META and riga["impronta_copia"] is None
    pronta = Path(riga["in_preparazione"])
    assert _impronta(pronta.read_bytes()) == riga["impronta_nuova"]
    assert scena.casa.cestino.mosse == [] and _falliti(scena) == []
    assert len(_attivi(scena)) == 1
    spia.modo = None
    return riga, spia, errore


def test_fermato_a_meta_resta_in_scambio_e_si_finisce_dopo(scena, tmp_path, monkeypatch):
    riga, spia, errore = _a_meta(scena, monkeypatch)
    assert str(errore) == ("L'Archivio sicuro si è fermato a metà: finisco quando ritocchi "
                           "di nuovo questo scatto. Nessun file è stato cancellato.")
    assert errore.codice == copia.RitoccoFermato.codice
    eventi = _eventi(monkeypatch)
    assert copia.ripara(scena.archivio) == {"finiti": 1, "fermi": 0}
    assert ("ritocco.scambio_fatto", {"file": scena.file_id, "nell_archivio": True,
                                      "gia_fatto": True}) in eventi
    dopo = _ritoccata(scena)
    assert dopo["stato"] == copia.FATTA and dopo["impronta_copia"] == riga["impronta_nuova"]
    assert dopo["guasto"] is None and dopo["in_preparazione"] is None
    assert len(spia.chieste) == 2 and spia.chieste[0] == spia.chieste[1]
    assert scena.casa.cestino.mosse == [riga["in_preparazione"]]
    assert _percorsi(scena.archivio, scena.file_id) == [(str(scena.base), 0)]
    assert _rimaste(scena) == [] and _in_attesa(scena) == []
    _mai_in_chiaro(tmp_path, scena.dati[FOTO])
    estratti = _estratta(scena, tmp_path)
    assert _impronta(estratti["foto/s/mare.jpg"]) == riga["impronta_nuova"]


@pytest.mark.parametrize("modo", ["a_meta_con_esito", "senza_esito"])
def test_senza_un_esito_finito_il_ritocco_resta_in_scambio(scena, monkeypatch, modo):
    riga, _, _ = _a_meta(scena, monkeypatch, modo)
    assert copia.porta_a_termine(scena.archivio, scena.file_id) == scena.scatto
    assert _ritoccata(scena)["stato"] == copia.FATTA


def test_un_guasto_dell_archivio_nel_mezzo_lascia_il_ritocco_in_scambio(scena, monkeypatch):
    errori = _eventi(monkeypatch, "errore")
    riga, spia, errore = _a_meta(scena, monkeypatch, RuntimeError("rotto"))
    assert str(errore) == copia.FERMO_A_META
    assert [nome for nome, _ in errori] == ["ritocco.archivio_guasto",
                                            "ritocco.scambio_fermo"]
    assert copia.porta_a_termine(scena.archivio, scena.file_id) == scena.scatto
    assert _ritoccata(scena)["stato"] == copia.FATTA


def test_il_ritocco_dopo_finisce_prima_quello_rimasto_a_meta(scena, monkeypatch):
    riga, spia, _ = _a_meta(scena, monkeypatch)
    assert _metti(scena, ALTRA_ZONA) == scena.scatto
    dopo = _ritoccata(scena)
    assert dopo["stato"] == copia.FATTA
    assert dopo["impronta_copia"] not in (None, riga["impronta_nuova"])
    assert [chiesta.get("come") for chiesta in spia.chieste] == [None, None,
                                                                 copia.SOSTITUISCI]
    assert spia.chieste[2]["impronta"] == riga["impronta_nuova"]
    assert len(_attivi(scena)) == 2 and len(scena.casa.cestino.mosse) == 2


@pytest.mark.parametrize("modo, guasto, codice", [
    ("chiuso", copia.CHIUSO_DOPO, copia.SICURO_CHIUSO),
    ("sparito", copia.CHIUSO_DOPO, copia.SICURO_CHIUSO),
    ("occupato", copia.MUTO_DOPO, "occupato"),
    ("muto", NON_PRESO, copia.RitoccoFermato.codice),
    ("sul_disco", NON_SALVATO_SUL_DISCO, "sul_disco"),
    ("a_meta", copia.A_META, copia.RitoccoFermato.codice),
    ("rotto", copia.A_META, copia.RitoccoFermato.codice)])
def test_riprovando_ogni_intoppo_lascia_il_ritocco_in_scambio(scena, monkeypatch, modo,
                                                              guasto, codice):
    percorsi = _percorsi(scena.archivio, scena.file_id)
    riga, spia, _ = _a_meta(scena, monkeypatch, RuntimeError("rotto"))
    pronta = Path(riga["in_preparazione"])
    dati = pronta.read_bytes()
    if modo == "chiuso":
        assert scena.casa.archivio.chiudi(ATTESA)
        monkeypatch.setattr(archivio_sicuro, "per_le_foto",
                            lambda: (TROVATA, scena.casa.archivio))
    elif modo == "sparito":
        scena.situazione.forzata = SENZA_ARCHIVIO
    else:
        _intoppo(scena, spia, monkeypatch, modo)
    assert copia.ripara(scena.archivio) == {"finiti": 0, "fermi": 1}
    errore = _fermato(lambda: copia.porta_a_termine(scena.archivio, scena.file_id))
    assert errore.codice == codice
    adesso = _ritoccata(scena)
    assert adesso["stato"] == copia.IN_SCAMBIO and adesso["guasto"] == guasto
    assert adesso["impronta_copia"] is None
    assert adesso["percorso_base"] == str(scena.base)
    assert pronta.read_bytes() == dati and scena.casa.cestino.mosse == []
    assert _percorsi(scena.archivio, scena.file_id) == percorsi
    assert len(_attivi(scena)) == 1 and _falliti(scena) == []


def test_togli_tutti_fermato_a_meta_si_finisce_dopo(scena, monkeypatch):
    _metti(scena)
    prima = _ritoccata(scena)
    spia = _Accoglie(scena, monkeypatch)
    spia.modo = "a_meta"
    errore = _fermato(lambda: copia.torna(scena.archivio, scena.file_id))
    assert str(errore) == copia.FERMO_A_META
    adesso = _ritoccata(scena)
    assert adesso["stato"] == copia.IN_RITORNO and adesso["guasto"] == copia.A_META
    assert adesso["nell_archivio"] == 1
    assert adesso["impronta_copia"] == prima["impronta_copia"]
    spia.modo = None
    eventi = _eventi(monkeypatch)
    assert copia.ripara(scena.archivio) == {"finiti": 1, "fermi": 0}
    assert _ritoccata(scena) is None
    assert ("ritocco.tornato", {"file": scena.file_id, "nell_archivio": True,
                                "gia_fatto": True}) in eventi
    assert _percorsi(scena.archivio, scena.file_id) == [(str(scena.scatto), 0)]
    assert _storia(scena, FOTO)[-1] == (prima["impronta_base"], True)
    assert len(spia.chieste) == 2 and spia.chieste[0] == spia.chieste[1]


@pytest.mark.parametrize("modo, guasto", [("muto", NON_PRESO), ("chiuso", copia.CHIUSO_DOPO),
                                          ("rotto", copia.A_META)])
def test_togli_tutti_riprovando_resta_in_ritorno(scena, monkeypatch, modo, guasto):
    _metti(scena)
    spia = _Accoglie(scena, monkeypatch)
    spia.modo = "a_meta"
    _fermato(lambda: copia.torna(scena.archivio, scena.file_id))
    spia.modo = None
    if modo == "chiuso":
        assert scena.casa.archivio.chiudi(ATTESA)
        monkeypatch.setattr(archivio_sicuro, "per_le_foto",
                            lambda: (TROVATA, scena.casa.archivio))
    else:
        _intoppo(scena, spia, monkeypatch, modo)
    assert copia.ripara(scena.archivio) == {"finiti": 0, "fermi": 1}
    adesso = _ritoccata(scena)
    assert adesso["stato"] == copia.IN_RITORNO and adesso["guasto"] == guasto


def _copia_rimasta(scena, monkeypatch, cestino, zona=ZONA):
    monkeypatch.setattr(archivio_sicuro, "il_cestino", lambda: cestino)
    avvisi = _eventi(monkeypatch, "avviso")
    assert _metti(scena, zona) == scena.scatto
    riga = _ritoccata(scena)
    assert riga["stato"] == copia.FATTA and riga["in_preparazione"] is None
    rimasta = _rimaste(scena)[-1]
    pronta = Path(rimasta["percorso"])
    assert pronta.is_file() and attesa.e_dentro(pronta)
    assert rimasta["impronta"] == riga["impronta_copia"] == _impronta(pronta.read_bytes())
    assert rimasta["file_id"] == scena.file_id and rimasta["messa_il"]
    assert avvisi == [("ritocco.copia_in_chiaro", {"file": scena.file_id,
                                                   "cambiata": False})]
    return rimasta, pronta


@pytest.mark.parametrize("cambi, codice", [
    ({"genere": CHIAVETTA}, "non_nel_cestino_chiavetta"),
    ({"genere": RETE}, "disco_di_rete"),
    ({"sistema": "FAT32"}, "sistema_strano"),
    ({"spento": True}, "cestino_spento"),
    ({"giorni": 30}, "sensore_memoria"),
    ({"massimo": 10}, "troppo_grande"),
    ({"in_piu": 8 * 1024 ** 3}, "cestino_pieno")])
def test_se_il_cestino_non_e_sicuro_la_copia_ritoccata_resta_e_si_avvisa(
        scena, tmp_path, monkeypatch, cambi, codice):
    cestino = CestinoFinto(tmp_path, **cambi)
    rimasta, _ = _copia_rimasta(scena, monkeypatch, cestino)
    assert rimasta["guasto"] == f"{in_chiaro.RIMASTA}. {PROBLEMI[codice]}"
    assert cestino.mosse == []


def test_il_messaggio_della_copia_ritoccata_rimasta():
    assert in_chiaro.RIMASTA == ("la copia ritoccata è ancora in chiaro nella cartella di "
                                 "attesa: riprovo a metterla nel Cestino a ogni avvio, o "
                                 "puoi cancellarla tu")
    assert in_chiaro.CAMBIATA == ("la copia in chiaro nella cartella di attesa è cambiata: "
                                  "non l'ho toccata")
    assert in_chiaro.NON_PRESA == "Il Cestino di Windows non l'ha presa."


@pytest.mark.parametrize("modo", ["rifiuta", "eccezione_prima"])
def test_se_il_cestino_non_prende_la_copia_ritoccata_resta(scena, tmp_path, monkeypatch,
                                                          modo):
    cestino = CestinoFinto(tmp_path, modo=modo)
    errori = _eventi(monkeypatch, "errore")
    rimasta, pronta = _copia_rimasta(scena, monkeypatch, cestino)
    assert rimasta["guasto"] == f"{in_chiaro.RIMASTA}. {in_chiaro.NON_PRESA}"
    assert cestino.mosse == [str(pronta)]
    nomi = [nome for nome, _ in errori]
    assert nomi.count("ritocco.cestino_guasto") == (modo == "eccezione_prima")


def test_un_percorso_troppo_lungo_per_il_cestino_resta(scena, tmp_path, monkeypatch):
    monkeypatch.setattr(cestino_modulo, "LUNGO", len(str(scena.casa.foto)))
    cestino = CestinoFinto(tmp_path)
    rimasta, _ = _copia_rimasta(scena, monkeypatch, cestino)
    assert rimasta["guasto"] == f"{in_chiaro.RIMASTA}. {PROBLEMI['percorso_lungo']}"
    assert cestino.mosse == []


def test_se_il_cestino_si_rompe_la_copia_ritoccata_resta(scena, monkeypatch):
    class Rotto:
        def problema(self, *argomenti):
            raise RuntimeError("rotto")

    errori = _eventi(monkeypatch, "errore")
    rimasta, _ = _copia_rimasta(scena, monkeypatch, Rotto())
    assert rimasta["guasto"] == f"{in_chiaro.RIMASTA}. {in_chiaro.NON_PRESA}"
    assert [nome for nome, _ in errori] == ["ritocco.cestino_guasto"]


def test_se_il_cestino_si_rompe_ma_la_copia_e_sparita_conta_come_buttata(
        scena, tmp_path, monkeypatch):
    _, pronta = _copia_rimasta(scena, monkeypatch, CestinoFinto(tmp_path, spento=True))

    class SiRompeDopo:
        def problema(self, *argomenti):
            pronta.unlink()
            raise RuntimeError("rotto")

    monkeypatch.setattr(archivio_sicuro, "il_cestino", SiRompeDopo)
    errori = _eventi(monkeypatch, "errore")
    avvisi = _eventi(monkeypatch, "avviso")
    assert in_chiaro.butta_tutte(scena.archivio) == 1
    assert _rimaste(scena) == [] and avvisi == [] and not os.path.lexists(pronta)
    assert [nome for nome, _ in errori] == ["ritocco.cestino_guasto"]


def test_senza_il_cestino_di_windows_la_copia_ritoccata_resta(scena, monkeypatch):
    monkeypatch.setattr(servizio_sicuro, "_attuale", None)
    rimasta, _ = _copia_rimasta(scena, monkeypatch, IL_VERO_CESTINO())
    assert rimasta["guasto"] == f"{in_chiaro.RIMASTA}. {PROBLEMI['senza_cestino']}"


@pytest.mark.parametrize("modo", ["bene", "eccezione", "bugiardo", "per_sempre"])
def test_se_la_copia_ritoccata_se_ne_va_conta_come_buttata(scena, tmp_path, monkeypatch,
                                                           modo):
    cestino = CestinoFinto(tmp_path, modo=modo)
    monkeypatch.setattr(archivio_sicuro, "il_cestino", lambda: cestino)
    avvisi = _eventi(monkeypatch, "avviso")
    _metti(scena)
    [mossa] = cestino.mosse
    assert not os.path.lexists(mossa) and _rimaste(scena) == [] and avvisi == []


def test_se_buttarla_si_rompe_il_ritocco_resta_fatto(scena, monkeypatch):
    def rotta(*argomenti):
        raise RuntimeError("rotto")

    errori = _eventi(monkeypatch, "errore")
    vera = in_chiaro.butta
    monkeypatch.setattr(in_chiaro, "butta", rotta)
    assert _metti(scena) == scena.scatto
    riga = _ritoccata(scena)
    assert riga["stato"] == copia.FATTA and _falliti(scena) == []
    assert len(_attivi(scena)) == 1
    [rimasta] = _rimaste(scena)
    assert rimasta["impronta"] == riga["impronta_copia"] and rimasta["guasto"] is None
    assert [nome for nome, _ in errori] == ["ritocco.cestino_guasto"]
    monkeypatch.setattr(in_chiaro, "butta", vera)
    assert in_chiaro.butta_tutte(scena.archivio) == 1
    assert _rimaste(scena) == [] and _in_attesa(scena) == []


def test_se_si_spegne_mentre_butta_la_copia_ritoccata_si_ritenta_dopo(scena, tmp_path,
                                                                       monkeypatch):
    cestino = CestinoFinto(tmp_path, modo="crollo_prima")
    monkeypatch.setattr(archivio_sicuro, "il_cestino", lambda: cestino)
    with pytest.raises(Crollo):
        _metti(scena)
    riga = _ritoccata(scena)
    assert riga["stato"] == copia.FATTA
    [rimasta] = _rimaste(scena)
    assert rimasta["guasto"] is None and Path(rimasta["percorso"]).is_file()
    cestino.modo = "bene"
    assert in_chiaro.butta_tutte(scena.archivio) == 1
    assert _rimaste(scena) == [] and not os.path.lexists(rimasta["percorso"])


def test_la_copia_ritoccata_rimasta_si_ritenta_finche_il_cestino_la_prende(
        scena, tmp_path, monkeypatch):
    cestino = CestinoFinto(tmp_path, spento=True)
    rimasta, pronta = _copia_rimasta(scena, monkeypatch, cestino)
    assert in_chiaro.butta_tutte(scena.archivio) == 0
    assert _rimaste(scena) == [rimasta]
    cestino.spento = False
    assert in_chiaro.butta_tutte(scena.archivio) == 1
    assert _rimaste(scena) == [] and not os.path.lexists(pronta)
    assert cestino.mosse == [str(pronta)]


def test_con_una_copia_rimasta_il_ritocco_dopo_usa_un_altro_nome(scena, tmp_path,
                                                                monkeypatch):
    cestino = CestinoFinto(tmp_path, spento=True)
    prima, pronta = _copia_rimasta(scena, monkeypatch, cestino)
    dati = pronta.read_bytes()
    _metti(scena, ALTRA_ZONA)
    _metti(scena, (8, 44, 40, 60))
    nome = f"{copia.PREFISSO}-{scena.file_id}"
    assert [Path(rimasta["percorso"]).name for rimasta in _rimaste(scena)] == [
        f"{nome}-mare.jpg", f"{nome}-a1-mare.jpg", f"{nome}-a2-mare.jpg"]
    assert pronta.read_bytes() == dati
    impronte = [rimasta["impronta"] for rimasta in _rimaste(scena)]
    assert impronte[-1] == _ritoccata(scena)["impronta_copia"]
    assert len(set(impronte)) == 3
    cestino.spento = False
    assert in_chiaro.butta_tutte(scena.archivio) == 3
    assert _rimaste(scena) == [] and _in_attesa(scena) == []


@pytest.mark.parametrize("come", ["diversa", "cartella", "fuori", "collegamento",
                                  "collegamento_uguale", "presa"])
def test_una_copia_ritoccata_cambiata_non_si_tocca(scena, tmp_path, monkeypatch, come):
    cestino = CestinoFinto(tmp_path, spento=True)
    rimasta, pronta = _copia_rimasta(scena, monkeypatch, cestino)
    dati = pronta.read_bytes()
    fuori = tmp_path / "altrove" / pronta.name
    if come == "diversa":
        pronta.write_bytes(b"cambiata dopo")
    elif come == "cartella":
        pronta.unlink()
        pronta.mkdir()
        (pronta / "dentro.jpg").write_bytes(dati)
    elif come.startswith("collegamento"):
        pronta.unlink()
        if come == "collegamento_uguale":
            fuori.parent.mkdir()
            fuori.write_bytes(dati)
        try:
            pronta.symlink_to(fuori)
        except OSError:
            pytest.skip("qui non si fanno collegamenti")
    elif come == "presa":
        if not hasattr(socket, "AF_UNIX"):
            pytest.skip("qui non ci sono prese")
        pronta.unlink()
        monkeypatch.chdir(pronta.parent)
        with socket.socket(socket.AF_UNIX) as presa:
            presa.bind(pronta.name)
    else:
        fuori.parent.mkdir()
        fuori.write_bytes(dati)
        with scena.archivio.scrittura() as connessione:
            connessione.execute("UPDATE ritocchi_in_chiaro SET percorso = ? WHERE id = ?",
                                (str(fuori), rimasta["id"]))
    cestino.spento = False
    avvisi = _eventi(monkeypatch, "avviso")
    assert in_chiaro.butta_tutte(scena.archivio) == 0
    [adesso] = _rimaste(scena)
    assert adesso["guasto"] == in_chiaro.CAMBIATA
    assert avvisi == [("ritocco.copia_in_chiaro", {"file": scena.file_id,
                                                   "cambiata": True})]
    assert cestino.mosse == []
    if come == "diversa":
        assert pronta.read_bytes() == b"cambiata dopo"
    elif come == "cartella":
        assert (pronta / "dentro.jpg").read_bytes() == dati
    elif come.startswith("collegamento"):
        assert pronta.is_symlink()
        assert fuori.exists() == (come == "collegamento_uguale")
    elif come == "presa":
        assert pronta.is_socket()
    else:
        assert fuori.read_bytes() == dati and pronta.read_bytes() == dati
    assert in_chiaro.butta_tutte(scena.archivio) == 0
    assert cestino.mosse == []


def test_una_copia_ritoccata_gia_sparita_conta_come_buttata(scena, tmp_path, monkeypatch):
    cestino = CestinoFinto(tmp_path, spento=True)
    _, pronta = _copia_rimasta(scena, monkeypatch, cestino)
    pronta.unlink()
    avvisi = _eventi(monkeypatch, "avviso")
    assert in_chiaro.butta_tutte(scena.archivio) == 1
    assert _rimaste(scena) == [] and avvisi == [] and cestino.mosse == []


@pytest.mark.parametrize("modo, buttate", [("bene", 1), ("rifiuta", 0)])
def test_una_copia_ritoccata_cambiata_mentre_la_butto_resta_segnata(scena, tmp_path,
                                                                    monkeypatch, modo,
                                                                    buttate):
    cestino = CestinoFinto(tmp_path, spento=True)
    rimasta, pronta = _copia_rimasta(scena, monkeypatch, cestino)
    cestino.spento, cestino.modo = False, modo

    def cambia(percorso):
        with scena.archivio.scrittura() as connessione:
            in_chiaro.segna(connessione, scena.file_id, pronta, ALTRA)

    cestino.prima = cambia
    assert in_chiaro.butta_tutte(scena.archivio) == buttate
    [adesso] = _rimaste(scena)
    assert adesso["impronta"] == ALTRA and adesso["guasto"] is None


def test_buttare_una_copia_che_non_e_segnata_non_fa_niente(scena, tmp_path):
    cestino = CestinoFinto(tmp_path)
    assert in_chiaro.butta(scena.archivio, tmp_path / "mai_vista.jpg") is True
    assert cestino.mosse == [] and _rimaste(scena) == []


def test_all_avvio_si_ritenta_la_copia_ritoccata_rimasta(scena, tmp_path, monkeypatch):
    cestino = CestinoFinto(tmp_path, spento=True)
    _, pronta = _copia_rimasta(scena, monkeypatch, cestino)
    cestino.spento = False
    monkeypatch.setattr(accesso, "aperto", lambda: scena.archivio)
    avvio.Programma._ripara_i_ritocchi(None)
    assert _rimaste(scena) == [] and not os.path.lexists(pronta)


def test_all_avvio_un_guasto_delle_copie_ritoccate_rimaste_si_scrive(monkeypatch):
    from officina.miglioria import scambio, sopra
    from officina.ritocco import tolti
    from officina.web import coda_ritocco

    def rotto(archivio):
        raise RuntimeError("rotto")

    errori = _eventi(monkeypatch, "errore")
    monkeypatch.setattr(accesso, "aperto", lambda: object())
    for modulo, nome in ((copia, "ripara"), (tolti, "ripara"), (sopra, "rifai_i_lasciati"),
                         (coda_ritocco, "ripara"), (scambio, "butta_le_copie_rimaste")):
        monkeypatch.setattr(modulo, nome, lambda archivio: None)
    monkeypatch.setattr(in_chiaro, "butta_tutte", rotto)
    avvio.Programma._ripara_i_ritocchi(None)
    assert [nome for nome, _ in errori] == ["programma.ritocchi_non_riparati"]


def test_segnare_due_volte_la_stessa_copia_la_aggiorna(archivio):
    percorso = Path("/da/qualche/parte") / attesa.NOME / "ritocco-1-mare.jpg"
    with archivio.scrittura() as connessione:
        in_chiaro.segna(connessione, 1, percorso, "aa" * 32)
        connessione.execute("UPDATE ritocchi_in_chiaro SET guasto = 'rotto'")
        assert in_chiaro.occupato(connessione, percorso)
        assert not in_chiaro.occupato(connessione, percorso.with_name("altro.jpg"))
        in_chiaro.segna(connessione, 2, percorso, "bb" * 32)
        [riga] = in_chiaro.rimaste(connessione)
    assert (riga["file_id"], riga["percorso"], riga["impronta"], riga["guasto"]) == (
        2, str(percorso), "bb" * 32, None)


def _miglioria(scena, miglioria_id: int):
    with scena.archivio.lettura() as connessione:
        return coda.per_id(connessione, miglioria_id)


def _mai_fuori_dal_cestino(scena, tmp_path, *tutti: bytes) -> None:
    dentro = scena.casa.cestino.dentro
    for percorso in tmp_path.rglob("*"):
        if (not percorso.is_file() or percorso.is_symlink()
                or str(percorso).startswith(dentro)
                or percorso.relative_to(tmp_path).parts[0] in ("fuori", "dopo")):
            continue
        contenuto = percorso.read_bytes()
        for dati in tutti:
            assert dati not in contenuto, percorso


def test_si_ritocca_la_migliorata_che_c_e_solo_nell_archivio(scena, tmp_path):
    migliorata = mostra._approvata(scena)
    dati = mostra.MIGLIORATA[FOTO]
    assert migliorata["nell_archivio"] == 1 and not os.path.lexists(scena.scatto)
    percorsi = _percorsi(scena.archivio, scena.file_id)
    mosse = len(scena.casa.cestino.mosse)
    assert copia.metti(scena.archivio, scena.file_id, [_volto(dati)]) == scena.scatto
    riga = _ritoccata(scena)
    accanto = scena.base.parent / copia.CARTELLA / scena.scatto.name
    assert riga["stato"] == copia.FATTA and riga["nell_archivio"] == 1
    assert (riga["base_e"], riga["miglioria_id"]) == (copia.MIGLIORATA, migliorata["id"])
    assert riga["percorso_copia"] == str(scena.scatto)
    assert riga["percorso_base"] == str(accanto)
    assert (riga["impronta_base"], riga["dimensione_base"]) == (_impronta(dati), len(dati))
    assert _percorsi(scena.archivio, scena.file_id) == percorsi
    assert _miglioria(scena, migliorata["id"])["percorso_migliorata"] == str(accanto)
    assert len(scena.casa.cestino.mosse) == mosse + 1
    assert _rimaste(scena) == [] and _in_attesa(scena) == []
    _mai_in_chiaro(tmp_path, scena.dati[FOTO])
    estratti = _estratta(scena, tmp_path)
    ritoccata = estratti["foto/s/mare.jpg"]
    assert _impronta(ritoccata) == riga["impronta_copia"] and _misure(ritoccata) == (128, 96)
    assert estratti[f"foto/s/{attesa.ORIGINALI}/{copia.CARTELLA}/mare.jpg"] == dati
    assert estratti[f"foto/s/{attesa.ORIGINALI}/mare.jpg"] == scena.dati[FOTO]
    assert _quanto_varia(ritoccata) < _quanto_varia(dati)
    _mai_fuori_dal_cestino(scena, tmp_path, ritoccata, dati)

    assert _togli_tutti(scena, "togli") == scena.scatto
    assert _ritoccata(scena) is None
    assert _miglioria(scena, migliorata["id"])["percorso_migliorata"] == str(scena.scatto)
    assert _percorsi(scena.archivio, scena.file_id) == percorsi
    assert _storia(scena, FOTO)[-2:] == [(riga["impronta_copia"], False),
                                         (_impronta(dati), True)]
    estratti = _estratta(scena, tmp_path, "dopo")
    assert estratti["foto/s/mare.jpg"] == dati
    assert estratti[f"foto/s/{attesa.ORIGINALI}/mare.jpg"] == scena.dati[FOTO]
    assert f"foto/s/{attesa.ORIGINALI}/{copia.CARTELLA}/mare.jpg" not in estratti
    assert _rimaste(scena) == [] and _in_attesa(scena) == []
    _mai_fuori_dal_cestino(scena, tmp_path, ritoccata, dati)


@pytest.mark.parametrize("come", ["metti", "togli", "torna"])
def test_un_collegamento_rotto_al_posto_dello_scatto_senza_ritocchi_non_si_segue(
        scena, monkeypatch, come):
    _metti(scena)
    prima = dict(_ritoccata(scena))
    scena.base.parent.mkdir(parents=True, exist_ok=True)
    scena.base.symlink_to(scena.base.parent / "non_c_e.jpg")
    cercate: list = []
    vera = file_media.cerca_uguale

    def cerca_uguale(*argomenti, **piu):
        cercate.append(argomenti)
        return vera(*argomenti, **piu)

    monkeypatch.setattr(file_media, "cerca_uguale", cerca_uguale)
    spia = _Accoglie(scena, monkeypatch)
    errore = _fermato(lambda: _fai(scena, come))
    assert str(errore) == (copia.CAMBIATO if come == "metti" else copia.SENZA_BASE)
    assert spia.chieste == [] and cercate == []
    assert scena.base.is_symlink() and not scena.base.exists()
    _com_era(scena, prima, come, copia.CAMBIATO)


def test_una_miglioria_in_coda_segue_lo_scatto_senza_ritocchi(scena):
    assert coda_di_prova._metti(scena, FOTO).messi == 1
    with scena.archivio.lettura() as connessione:
        [in_coda] = coda.in_stato(connessione, coda.IN_CODA)
    assert in_coda["percorso_originale"] == str(scena.scatto)
    _metti(scena)
    assert _miglioria(scena, in_coda["id"])["percorso_originale"] == str(scena.base)
    _togli_tutti(scena, "togli")
    assert _miglioria(scena, in_coda["id"])["percorso_originale"] == str(scena.scatto)


def test_i_percorsi_sono_quelli_che_dice_l_archivio(scena, monkeypatch):
    servizio = scena.casa.archivio
    vero = servizio.accogli
    verso = scena.scatto.with_name("mare (1).jpg")
    spostato = scena.base.with_name("mare (2).jpg")

    def accogli(richiesta, *altro):
        fatto = vero(richiesta, *altro)
        return {**fatto, "esito": {**fatto["esito"], "verso": str(verso),
                                   "spostato": str(spostato)}}

    monkeypatch.setattr(servizio, "accogli", accogli)
    assert _metti(scena) == verso
    riga = _ritoccata(scena)
    assert riga["percorso_copia"] == str(verso)
    assert riga["percorso_base"] == str(spostato)
    assert _percorsi(scena.archivio, scena.file_id) == [(str(spostato), 0)]


def test_i_ritocchi_di_prima_restano_sul_disco(archivio):
    with archivio.lettura() as connessione:
        colonne = {colonna["name"]: colonna for colonna in
                   connessione.execute("PRAGMA table_info(ritoccate)")}
        rimaste = {colonna["name"]: colonna["notnull"] for colonna in
                   connessione.execute("PRAGMA table_info(ritocchi_in_chiaro)")}
        indici = {indice["name"]: indice for indice in
                  connessione.execute("PRAGMA index_list(ritocchi_in_chiaro)")}
        unico = [indice["name"] for indice in indici.values() if indice["unique"]]
        [percorso] = [[colonna["name"] for colonna in connessione.execute(
            f"PRAGMA index_info('{nome}')")] for nome in unico]
        per_file = [colonna["name"] for colonna in connessione.execute(
            "PRAGMA index_info(ritocchi_in_chiaro_per_file)")]
    assert colonne["nell_archivio"]["notnull"] == 1
    assert colonne["nell_archivio"]["dflt_value"] == "0"
    assert colonne["dimensione_base"]["notnull"] == 0
    assert rimaste == {"id": 0, "file_id": 1, "percorso": 1, "impronta": 1, "guasto": 0,
                       "messa_il": 1}
    assert percorso == ["percorso"] and per_file == ["file_id"]
    assert indici["ritocchi_in_chiaro_per_file"]["unique"] == 0
    [migrazione] = [m for m in migrazioni.MIGRAZIONI if m.versione == 69]
    connessione = sqlite3.connect(":memory:")
    try:
        connessione.execute("CREATE TABLE ritoccate (file_id INTEGER PRIMARY KEY)")
        connessione.execute("INSERT INTO ritoccate (file_id) VALUES (1)")
        migrazione.applica(connessione)
        assert connessione.execute(
            "SELECT nell_archivio, dimensione_base FROM ritoccate").fetchall() == [(0, None)]
    finally:
        connessione.close()


VECCHIA = 1_500_000_000_123_456_700


@pytest.fixture
def prima_sul_disco(archivio, casa, monkeypatch):
    dati = {FOTO: _jpeg()}
    casa.metti(FOTO, dati[FOTO])
    motore = Motore(archivio)
    motore.prepara([casa.foto])
    motore.esegui()
    scena = SimpleNamespace(archivio=archivio, casa=casa, dati=dati,
                            file_id=_file_id(archivio, "mare.jpg"), scatto=casa.foto / FOTO)
    scena.base = scena.scatto.parent / attesa.ORIGINALI / scena.scatto.name
    assert _metti(scena) == scena.scatto
    scena.ritoccata = scena.scatto.read_bytes()
    assert scena.base.read_bytes() == dati[FOTO]
    os.utime(scena.base, ns=(VECCHIA, VECCHIA))
    casa.archivio.crea(PAROLA, costo=LEGGERO)
    casa.archivio.copia_tutto([casa.foto])
    _finche(casa.copiato)
    casa.con_la_chiavetta()
    scena.scatto.unlink()
    scena.base.unlink()
    scena.situazione = _Situazione(casa)
    monkeypatch.setattr(archivio_sicuro, "per_le_foto", scena.situazione.per_le_foto)
    monkeypatch.setattr(archivio_sicuro, "il_cestino", lambda: casa.cestino)
    return scena


def test_un_ritocco_fatto_sul_disco_si_cambia_con_lo_scatto_solo_nell_archivio(
        prima_sul_disco, tmp_path):
    scena = prima_sul_disco
    prima = dict(_ritoccata(scena))
    assert prima["nell_archivio"] == 0 and prima["dimensione_base"] is None
    assert _impronta(scena.ritoccata) == prima["impronta_copia"]
    assert _metti(scena, ALTRA_ZONA) == scena.scatto
    dopo = _ritoccata(scena)
    assert dopo["stato"] == copia.FATTA and dopo["nell_archivio"] == 1
    assert dopo["percorso_copia"] == str(scena.scatto)
    assert dopo["percorso_base"] == str(scena.base)
    assert dopo["impronta_base"] == prima["impronta_base"]
    assert dopo["impronta_copia"] not in (None, prima["impronta_copia"])
    assert dopo["guasto"] is None and dopo["in_preparazione"] is None
    assert not os.path.lexists(scena.scatto) and not os.path.lexists(scena.base)
    assert _rimaste(scena) == [] and _in_attesa(scena) == []
    assert len(scena.casa.cestino.mosse) == 1
    assert _storia(scena, FOTO) == [(prima["impronta_copia"], False),
                                    (dopo["impronta_copia"], True)]
    _mai_in_chiaro(tmp_path, scena.dati[FOTO])
    estratti = _estratta(scena, tmp_path)
    ritoccata = estratti["foto/s/mare.jpg"]
    assert _impronta(ritoccata) == dopo["impronta_copia"]
    assert estratti[f"foto/s/{attesa.ORIGINALI}/mare.jpg"] == scena.dati[FOTO]
    for zona in (ZONA, ALTRA_ZONA):
        assert _quanto_varia(ritoccata, zona) < _quanto_varia(scena.dati[FOTO], zona)
    _mai_fuori_dal_cestino(scena, tmp_path, ritoccata)

    assert _togli_tutti(scena, "torna") == scena.scatto
    assert _ritoccata(scena) is None and _attivi(scena) == []
    assert _percorsi(scena.archivio, scena.file_id) == [(str(scena.scatto), 0)]
    assert not os.path.lexists(scena.scatto) and not os.path.lexists(scena.base)
    assert _storia(scena, FOTO)[-1] == (prima["impronta_base"], True)
    estratti = _estratta(scena, tmp_path, "dopo")
    assert estratti["foto/s/mare.jpg"] == scena.dati[FOTO]
    assert not [nome for nome in estratti if f"/{attesa.ORIGINALI}/" in nome]
    _mai_fuori_dal_cestino(scena, tmp_path, ritoccata)


def test_togliere_tutto_da_un_ritocco_fatto_sul_disco_rimette_lo_scatto_nell_archivio(
        prima_sul_disco, tmp_path):
    scena = prima_sul_disco
    prima = dict(_ritoccata(scena))
    assert _togli_tutti(scena, "togli") == scena.scatto
    assert _ritoccata(scena) is None
    assert _percorsi(scena.archivio, scena.file_id) == [(str(scena.scatto), 0)]
    assert not os.path.lexists(scena.scatto) and not os.path.lexists(scena.base)
    assert scena.casa.cestino.mosse == [] and _rimaste(scena) == []
    assert _storia(scena, FOTO) == [(prima["impronta_copia"], False),
                                    (prima["impronta_base"], True)]
    estratti = _estratta(scena, tmp_path)
    assert estratti["foto/s/mare.jpg"] == scena.dati[FOTO]
    assert not [nome for nome in estratti if f"/{attesa.ORIGINALI}/" in nome]


def _cerca_la_migliorata(monkeypatch, migliorata, cambia) -> list:
    vera = file_media.cerca_uguale
    chieste: list = []

    def cerca_uguale(connessione, file_id, sua_impronta, percorso, **piu):
        ricerca = vera(connessione, file_id, sua_impronta, percorso, **piu)
        if sua_impronta != migliorata["impronta_migliorata"]:
            return ricerca
        chieste.append((percorso, piu))
        return cambia(ricerca)

    monkeypatch.setattr(file_media, "cerca_uguale", cerca_uguale)
    return chieste


def _migliorata_intatta(scena, spia, migliorata, prima: dict, messaggio: str) -> None:
    assert _ritoccata(scena) is None and spia.chieste == []
    assert _falliti(scena) == [messaggio] and _attivi(scena) == []
    assert _in_attesa(scena) == [] and scena.casa.cestino.mosse == prima["mosse"]
    assert _percorsi(scena.archivio, scena.file_id) == prima["percorsi"]
    assert dict(_miglioria(scena, migliorata["id"])) == prima["miglioria"]
    assert _storia(scena, FOTO) == prima["storia"]
    assert _storia(scena, f"s/{attesa.ORIGINALI}/mare.jpg") == [
        (_impronta(scena.dati[FOTO]), True)]


def _com_e_adesso(scena, migliorata) -> dict:
    return {"mosse": list(scena.casa.cestino.mosse), "storia": _storia(scena, FOTO),
            "percorsi": _percorsi(scena.archivio, scena.file_id),
            "miglioria": dict(_miglioria(scena, migliorata["id"]))}


@pytest.mark.parametrize("perche, messaggio", [
    (NON_C_E, copia.MIGLIORATA_PERSA),
    (dall_archivio.DIVERSA, copia.MIGLIORATA_PERSA),
    (CHIUSO, copia.SOLO_NELL_ARCHIVIO),
    (SI_APRE, copia.SOLO_NELL_ARCHIVIO),
    (SENZA_ARCHIVIO, copia.NON_SUL_DISCO)])
def test_se_la_migliorata_non_si_trova_non_si_ritocca_l_originale(scena, monkeypatch,
                                                                  perche, messaggio):
    migliorata = mostra._approvata(scena)
    prima = _com_e_adesso(scena, migliorata)
    chieste = _cerca_la_migliorata(monkeypatch, migliorata, lambda ricerca: Ricerca(perche))
    spia = _Accoglie(scena, monkeypatch)
    errore = _fermato(lambda: copia.metti(scena.archivio, scena.file_id,
                                          [_volto(mostra.MIGLIORATA[FOTO])]))
    assert str(errore) == messaggio
    assert chieste == [(str(scena.scatto), {"anche_diversa": True})]
    _migliorata_intatta(scena, spia, migliorata, prima, messaggio)


def test_il_messaggio_della_migliorata_che_non_si_trova():
    assert copia.MIGLIORATA_PERSA == ("Non trovo la versione migliorata di questo scatto né "
                                      "sul disco né nell'Archivio sicuro: non lo ritocco. "
                                      "Nessun file è stato toccato.")


@pytest.mark.parametrize("cambi", [{"diversa": True}, {"blake2b": ALTRA}])
def test_con_solo_una_versione_cambiata_della_migliorata_non_si_ritocca(scena, monkeypatch,
                                                                       cambi):
    migliorata = mostra._approvata(scena)
    prima = _com_e_adesso(scena, migliorata)

    def cambia(ricerca):
        assert ricerca.perche == TROVATA and not ricerca.diversa
        return Ricerca(ricerca.perche, dataclasses.replace(ricerca.trovata, **cambi))

    _cerca_la_migliorata(monkeypatch, migliorata, cambia)
    spia = _Accoglie(scena, monkeypatch)
    errore = _fermato(lambda: copia.metti(scena.archivio, scena.file_id,
                                          [_volto(mostra.MIGLIORATA[FOTO])]))
    assert str(errore) == copia.DIVERSA
    _migliorata_intatta(scena, spia, migliorata, prima, copia.DIVERSA)


def test_una_migliorata_approvata_sul_disco_si_cerca_solo_uguale(scena, monkeypatch):
    migliorata = mostra._approvata(scena)
    with scena.archivio.scrittura() as connessione:
        connessione.execute("UPDATE migliorie SET nell_archivio = 0 WHERE id = ?",
                            (migliorata["id"],))
    chieste = _cerca_la_migliorata(monkeypatch, migliorata, lambda ricerca: ricerca)
    assert copia.metti(scena.archivio, scena.file_id,
                       [_volto(mostra.MIGLIORATA[FOTO])]) == scena.scatto
    assert chieste == [(str(scena.scatto), {"anche_diversa": False})]
    riga = _ritoccata(scena)
    assert (riga["base_e"], riga["nell_archivio"]) == (copia.MIGLIORATA, 1)


def _bloccata(monkeypatch) -> list:
    avvisi = _eventi(monkeypatch, "avviso")

    def butta(pronta):
        raise PermissionError(13, "la usa un altro programma")

    monkeypatch.setattr(copia, "butta", butta)
    return avvisi


def _segnata(scena, avvisi, pronta: Path, sua_impronta: str) -> None:
    [rimasta] = _rimaste(scena)
    assert (rimasta["file_id"], rimasta["percorso"]) == (scena.file_id, str(pronta))
    assert rimasta["impronta"] == sua_impronta == _impronta(pronta.read_bytes())
    assert rimasta["guasto"] is None
    assert [(nome, campi["file"]) for nome, campi in avvisi] == [
        ("ritocco.copia_non_tolta", scena.file_id)]
    assert _in_attesa(scena) == [pronta]


def _poi_va_nel_cestino(scena, monkeypatch, pronta: Path, mosse: int) -> None:
    monkeypatch.setattr(copia, "butta", IL_VERO_BUTTA)
    assert in_chiaro.butta_tutte(scena.archivio) == 1
    assert _rimaste(scena) == [] and _in_attesa(scena) == []
    assert len(scena.casa.cestino.mosse) == mosse + 1
    assert Path(scena.casa.cestino.mosse[-1]) == pronta


IL_VERO_BUTTA = copia.butta


@pytest.mark.parametrize("modo, messaggio", [("sul_disco", NON_SALVATO_SUL_DISCO),
                                             ("muto", NON_PRESO), ("occupato", NON_PRESO)])
def test_se_windows_blocca_il_primo_ritocco_rifiutato_la_copia_resta_segnata(
        scena, monkeypatch, modo, messaggio):
    spia = _Accoglie(scena, monkeypatch)
    _intoppo(scena, spia, monkeypatch, modo)
    avvisi = _bloccata(monkeypatch)
    errore = _fermato(lambda: _metti(scena))
    assert str(errore) == messaggio
    assert _ritoccata(scena) is None and _falliti(scena) == [messaggio]
    [chiesta] = spia.chieste
    pronta = Path(chiesta["nuova"])
    _segnata(scena, avvisi, pronta, chiesta["impronta_nuova"])
    if modo == "sul_disco":
        scena.scatto.unlink()
    _poi_va_nel_cestino(scena, monkeypatch, pronta, 0)


def test_se_windows_blocca_un_cambio_rifiutato_la_copia_resta_segnata(scena, monkeypatch):
    _metti(scena)
    prima = dict(_ritoccata(scena))
    spia = _Accoglie(scena, monkeypatch)
    _intoppo(scena, spia, monkeypatch, "sul_disco")
    avvisi = _bloccata(monkeypatch)
    errore = _fermato(lambda: _fai(scena, "metti"))
    assert str(errore) == NON_SALVATO_SUL_DISCO
    assert dict(_ritoccata(scena)) == prima
    [chiesta] = spia.chieste
    pronta = Path(chiesta["nuova"])
    _segnata(scena, avvisi, pronta, chiesta["impronta_nuova"])
    scena.scatto.unlink()
    _poi_va_nel_cestino(scena, monkeypatch, pronta, 1)
    spia.prima = None
    assert _metti(scena, ALTRA_ZONA) == scena.scatto
    assert _ritoccata(scena)["stato"] == copia.FATTA


@pytest.mark.parametrize("bloccata", [False, True])
def test_rifare_la_stessa_copia_non_cambia_l_archivio(scena, monkeypatch, bloccata):
    _metti(scena)
    prima = dict(_ritoccata(scena))
    with scena.archivio.scrittura() as connessione:
        connessione.execute("UPDATE ritoccate SET da_rifare = 1 WHERE file_id = ?",
                            (scena.file_id,))
    spia = _Accoglie(scena, monkeypatch)
    avvisi = _bloccata(monkeypatch) if bloccata else _eventi(monkeypatch, "avviso")
    assert copia.rifai(scena.archivio, scena.file_id) == scena.scatto
    assert dict(_ritoccata(scena)) == {**prima, "da_rifare": 0}
    assert spia.chieste == [] and len(scena.casa.cestino.mosse) == 1
    if not bloccata:
        assert _rimaste(scena) == [] and _in_attesa(scena) == [] and avvisi == []
        return
    pronta = scena.casa.foto / attesa.NOME / f"{copia.PREFISSO}-{scena.file_id}-mare.jpg"
    _segnata(scena, avvisi, pronta, prima["impronta_copia"])
    _poi_va_nel_cestino(scena, monkeypatch, pronta, 1)


@pytest.mark.parametrize("come", ["metti", "togli", "torna"])
def test_un_collegamento_rotto_al_posto_della_copia_non_si_mescola(scena, monkeypatch,
                                                                    come):
    _metti(scena)
    prima = dict(_ritoccata(scena))
    scena.scatto.symlink_to(scena.scatto.parent / "non_c_e.jpg")
    spia = _Accoglie(scena, monkeypatch)
    errore = _fermato(lambda: _fai(scena, come))
    assert str(errore) == copia.MESCOLATI and spia.chieste == []
    assert scena.scatto.is_symlink() and not scena.scatto.exists()
    scena.scatto.unlink()
    _com_era(scena, prima, come, copia.MESCOLATI)


@pytest.mark.parametrize("primo", [True, False])
def test_se_l_archivio_si_chiude_mentre_legge_lo_scatto_non_si_ritocca(scena, monkeypatch,
                                                                       primo):
    if not primo:
        _metti(scena)
    prima = _ritoccata(scena)
    vera = metadati.apri

    def apri(sorgente):
        scena.casa.archivio.chiudi(ATTESA)
        return vera(sorgente)

    monkeypatch.setattr(metadati, "apri", apri)
    monkeypatch.setattr(archivio_sicuro, "per_le_foto",
                        lambda: (TROVATA, scena.casa.archivio))
    spia = _Accoglie(scena, monkeypatch)
    errore = _fermato(lambda: _metti(scena, ALTRA_ZONA))
    assert str(errore) == copia.SOLO_NELL_ARCHIVIO and errore.codice == copia.SICURO_CHIUSO
    assert spia.chieste == [] and _in_attesa(scena) == []
    assert _falliti(scena) == [copia.SOLO_NELL_ARCHIVIO]
    if primo:
        assert _ritoccata(scena) is None
    else:
        assert dict(_ritoccata(scena)) == dict(prima)


def test_la_copia_cambiata_prende_le_date_dello_scatto_senza_ritocchi(prima_sul_disco):
    scena = prima_sul_disco
    assert scena.casa.archivio.date(_ritoccata(scena)["impronta_base"], None,
                                    str(scena.base))["modifica"] == VECCHIA
    _metti(scena, ALTRA_ZONA)
    dopo = _ritoccata(scena)
    date = scena.casa.archivio.date(dopo["impronta_copia"], None, str(scena.scatto))
    assert date["modifica"] == VECCHIA


GIA_IN_ORIGINALI = ("In «Originali» c'è già un file con lo stesso nome: non lo copro. "
                    "Spostalo o rinominalo e riprova.")


@pytest.mark.parametrize("cosa", ["file", "collegamento"])
def test_se_in_originali_c_e_gia_quel_nome_non_si_ritocca_dall_archivio(scena, monkeypatch,
                                                                        cosa):
    scena.base.parent.mkdir(parents=True, exist_ok=True)
    if cosa == "file":
        scena.base.write_bytes(b"un altro file")
    else:
        scena.base.symlink_to(scena.base.parent / "non_c_e.jpg")
    percorsi, storia = _percorsi(scena.archivio, scena.file_id), _storia(scena, FOTO)
    spia = _Accoglie(scena, monkeypatch)
    errore = _fermato(lambda: _metti(scena))
    assert str(errore) == GIA_IN_ORIGINALI
    assert spia.chieste == [] and _ritoccata(scena) is None
    assert _falliti(scena) == [GIA_IN_ORIGINALI]
    assert _in_attesa(scena) == [] and scena.casa.cestino.mosse == []
    assert _percorsi(scena.archivio, scena.file_id) == percorsi
    assert _storia(scena, FOTO) == storia
    assert not os.path.lexists(scena.scatto)
    if cosa == "file":
        assert scena.base.read_bytes() == b"un altro file"
    else:
        assert scena.base.is_symlink() and not scena.base.exists()


@pytest.mark.parametrize("tolta", ["importata", "sua"])
@pytest.mark.parametrize("primo", [True, False])
def test_senza_la_sua_cartella_la_copia_aspetta_dove_c_e_ancora(scena, tmp_path,
                                                                monkeypatch, tolta, primo):
    if not primo:
        _metti(scena)
    cancellata = scena.casa.foto if tolta == "importata" else scena.scatto.parent
    shutil.rmtree(cancellata)
    spia = _Accoglie(scena, monkeypatch)
    assert _metti(scena, ALTRA_ZONA) == scena.scatto
    [chiesta] = spia.chieste
    attende = Path(chiesta["nuova"])
    assert attende.parent == (scena.archivio.dove.radice / attesa.NOME
                              if tolta == "importata" else scena.casa.foto / attesa.NOME)
    riga = _ritoccata(scena)
    assert riga["stato"] == copia.FATTA and riga["nell_archivio"] == 1
    assert riga["impronta_copia"] == chiesta["impronta_nuova"]
    assert Path(scena.casa.cestino.mosse[-1]) == attende
    assert not os.path.lexists(attende) and not cancellata.exists()
    assert _rimaste(scena) == []
    _mai_fuori_dal_cestino(scena, tmp_path, scena.dati[FOTO])


@pytest.mark.parametrize("come", ["metti", "togli"])
def test_un_ritocco_nuovo_nell_archivio_non_e_piu_da_rifare(scena, come):
    _metti(scena)
    if come == "togli":
        _metti(scena, ALTRA_ZONA)
    with scena.archivio.scrittura() as connessione:
        connessione.execute("UPDATE ritoccate SET da_rifare = 1 WHERE file_id = ?",
                            (scena.file_id,))
    prima = _ritoccata(scena)["impronta_copia"]
    if come == "metti":
        _metti(scena, ALTRA_ZONA)
    else:
        copia.togli(scena.archivio, _attivi(scena)[-1]["id"])
    riga = _ritoccata(scena)
    assert riga["impronta_copia"] != prima and riga["da_rifare"] == 0
    assert riga["stato"] == copia.FATTA and riga["guasto"] is None
    assert len(_attivi(scena)) == (2 if come == "metti" else 1)
