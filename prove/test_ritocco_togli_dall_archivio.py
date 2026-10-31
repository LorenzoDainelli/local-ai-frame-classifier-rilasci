from __future__ import annotations

import os
import shutil
import sys
from dataclasses import replace
from pathlib import Path

import numpy
import pytest
from PIL import Image

from officina.errori import ErroreOfficina
from officina.importazione import impronta
from officina.miglioria import attesa
from officina.modello import file_media
from officina.programma import archivio_sicuro
from officina.ritocco import coda, copia, elenco, in_chiaro, lavoro, maschere, sfida_togli
from officina.sicuro.dall_archivio import (CHIUSO, NON_C_E, PERSA, SENZA_ARCHIVIO, SI_APRE,
                                           DallArchivio, Ricerca)
from prove import test_ritocco_dall_archivio as di_prova
from prove.test_miglioria_coda_dall_archivio import FILMATO, FOTO, SOLE, _file_id
from prove.test_miglioria_dall_archivio import _mai_in_chiaro
from prove.test_miglioria_scambio_dall_archivio import _Accoglie, _eventi
from prove.test_ritocco_dall_archivio import (ALTRA_ZONA, ZONA, _estratta, _fermato,
                                              _grigio, _in_attesa, _metti, _misure,
                                              _non_risponde, _quanto_varia, _rimaste,
                                              _ritoccata, _storia, _volto)
from prove.test_ritocco_lavoro import _seguito
from prove.test_ritocco_togli_coda import Togliere
from prove.test_sicuro_cestino import CestinoFinto
from prove.test_sicuro_dall_archivio import _impronta, _rovina, _stacca
from prove.test_sicuro_servizio import ATTESA, PAROLA

pytest.importorskip("av")

costo_leggero = di_prova.costo_leggero
casa = di_prova.casa
cartella = di_prova.cartella
importato = di_prova.importato
solo_nell_archivio = di_prova.solo_nell_archivio
pronta = di_prova.pronta
scena = di_prova.scena

ORIGINALI = f"s/{attesa.ORIGINALI}"
LONTANO = (56, 8, 96, 56)


def _da_togliere(scena, zona=ZONA) -> dict:
    larga, alta = _misure(scena.dati[FOTO])
    piena = numpy.zeros((alta, larga), dtype=bool)
    sinistra, sopra, destra, sotto = zona
    piena[sopra:sotto, sinistra:destra] = True
    return {"file_id": scena.file_id, "genere": elenco.TOGLI, "cosa": elenco.OGGETTO,
            "larghezza": larga, "altezza": alta,
            "maschera": maschere.comprimi(piena, (0, 0), larga, alta)}


def _quanto_cambia(dopo: bytes, prima: bytes, zona=ZONA) -> float:
    sinistra, sopra, destra, sotto = zona
    differenza = numpy.abs(_grigio(dopo) - _grigio(prima))
    return float(differenza[sopra:sotto, sinistra:destra].mean())


def _tolta_e_pixelata(ritoccata: bytes, prima: bytes) -> None:
    assert _quanto_cambia(ritoccata, prima) > 20
    assert _quanto_varia(ritoccata, ALTRA_ZONA) < _quanto_varia(prima, ALTRA_ZONA)


def _in_coda(scena, zona=ZONA) -> int:
    return coda.metti(scena.archivio, [_da_togliere(scena, zona)])


def _gira(scena, togliere) -> None:
    ritoccatore = lavoro.Ritoccatore(scena.archivio, a_parte=False, toglie=togliere)
    assert ritoccatore.parti()
    assert ritoccatore.lavoro.aspetta_che_finisca(60)
    assert not ritoccatore.lavoro.guasto, ritoccatore.lavoro.guasto


def _lavoro(scena, lavoro_id: int):
    with scena.archivio.lettura() as connessione:
        return coda.per_id(connessione, lavoro_id)


def _ritocco(scena, ritocco_id: int):
    with scena.archivio.lettura() as connessione:
        return elenco.per_id(connessione, ritocco_id)


def _del_lavoro(scena, lavoro_id: int) -> list:
    with scena.archivio.lettura() as connessione:
        return list(connessione.execute(
            "SELECT * FROM ritocchi WHERE lavoro_id = ? ORDER BY id", (lavoro_id,)))


def _pronte(scena, lavoro_id: int) -> list[Path]:
    with scena.archivio.lettura() as connessione:
        return [Path(riga["pronta"]) for riga in coda.pronti(connessione, lavoro_id)]


def _da_rivedere(scena, togliere=None):
    togliere = togliere or Togliere()
    lavoro_id = _in_coda(scena)
    _gira(scena, togliere)
    adesso = _lavoro(scena, lavoro_id)
    assert adesso["stato"] == coda.DA_RIVEDERE and adesso["guasto"] is None
    [pronta] = _pronte(scena, lavoro_id)
    [ritocco] = _del_lavoro(scena, lavoro_id)
    return lavoro_id, pronta, ritocco, togliere


def _nell_archivio(scena, ritocco) -> Path:
    return scena.base.parent / copia.CARTELLA / copia.nome_della_toppa_nell_archivio(
        ritocco["id"], ritocco["impronta_risultato"])


def _relativo(scena, percorso: Path) -> str:
    return percorso.relative_to(scena.casa.foto).as_posix()


def _mosse(scena) -> list[Path]:
    return [Path(mossa) for mossa in scena.casa.cestino.mosse]


def _solo_la_toppa(spia, poi) -> None:
    spia.prima = lambda richiesta: setattr(
        spia, "modo", None if richiesta.get("come") == copia.AGGIUNGI else poi)


def _toppa_nell_archivio_e_copia_no(scena, monkeypatch):
    lavoro_id, pronta, ritocco, togliere = _da_rivedere(scena)
    spia = _Accoglie(scena, monkeypatch)
    _solo_la_toppa(spia, "muto")
    errore = _fermato(lambda: coda.approva(scena.archivio, lavoro_id))
    assert str(errore) == copia.NON_PRESO
    spia.prima = spia.modo = None
    return lavoro_id, pronta, ritocco, togliere, spia


def test_togliere_con_lo_scatto_solo_nell_archivio_lavora_nella_cartella_di_attesa(
        scena, tmp_path):
    lavoro_id, pronta, ritocco, togliere = _da_rivedere(scena)
    [chiesto] = togliere.lavori
    for chiave in ("immagine", "maschera", "uscita"):
        assert attesa.e_dentro(Path(chiesto[chiave])), chiave
    assert Path(chiesto["immagine"]).parent == Path(chiesto["uscita"]).parent
    assert not os.path.lexists(chiesto["immagine"])
    assert not os.path.lexists(chiesto["maschera"])
    toppa = Path(ritocco["risultato"])
    assert toppa == Path(chiesto["uscita"]) and toppa.parent == pronta.parent
    assert toppa.name == copia.nome_della_toppa(ritocco["id"])
    assert ritocco["stato"] == elenco.IN_CODA and copia.toppa_pronta(ritocco)
    assert attesa.e_dentro(pronta) and pronta.name.startswith(copia.PREFISSO)
    assert sorted(_in_attesa(scena)) == sorted([pronta, toppa])
    assert not os.path.lexists(scena.scatto)
    assert not os.path.lexists(scena.scatto.parent / attesa.ORIGINALI)
    assert _ritoccata(scena) is None and _rimaste(scena) == []
    assert _storia(scena, FOTO) == [(_impronta(scena.dati[FOTO]), True)]
    _mai_in_chiaro(tmp_path, scena.dati[FOTO])


def test_al_si_la_toppa_va_nell_archivio_prima_della_copia(scena, tmp_path, monkeypatch):
    lavoro_id, pronta, ritocco, _ = _da_rivedere(scena)
    toppa = Path(ritocco["risultato"])
    dati_toppa = toppa.read_bytes()
    eventi = _eventi(monkeypatch)
    spia = _Accoglie(scena, monkeypatch)

    coda.approva(scena.archivio, lavoro_id)

    adesso = _lavoro(scena, lavoro_id)
    assert adesso["stato"] == coda.FATTO and adesso["guasto"] is None
    dopo = _ritocco(scena, ritocco["id"])
    verso = _nell_archivio(scena, ritocco)
    assert dopo["stato"] == elenco.FATTO and dopo["risultato"] == str(verso)
    assert dopo["impronta_risultato"] == ritocco["impronta_risultato"]
    assert dopo["impronta_risultato"] == _impronta(dati_toppa)
    assert not os.path.lexists(verso)
    assert spia.chieste[0] == {
        "come": copia.AGGIUNGI, "nuova": str(toppa), "verso": str(verso),
        "base": str(scena.scatto), "impronta_nuova": ritocco["impronta_risultato"],
        "impronta_base": _impronta(scena.dati[FOTO])}
    assert [chiesta.get("come") for chiesta in spia.chieste] == [copia.AGGIUNGI, None]
    riga = _ritoccata(scena)
    assert riga["stato"] == copia.FATTA and riga["nell_archivio"] == 1
    assert riga["percorso_copia"] == str(scena.scatto)
    assert riga["percorso_base"] == str(scena.base)
    assert _in_attesa(scena) == [] and _rimaste(scena) == []
    assert _mosse(scena) == [toppa, pronta]
    assert ("ritocco.toppa_nell_archivio", {"ritocco": ritocco["id"],
                                            "gia_fatto": False}) in eventi
    nomi = [nome for nome, _ in eventi]
    assert nomi.index("ritocco.toppa_nell_archivio") < nomi.index("ritocco.scambio_fatto")
    assert not os.path.lexists(scena.scatto)
    assert not os.path.lexists(scena.scatto.parent / attesa.ORIGINALI)
    _mai_in_chiaro(tmp_path, scena.dati[FOTO])
    assert _storia(scena, _relativo(scena, verso)) == [(ritocco["impronta_risultato"], True)]
    estratti = _estratta(scena, tmp_path)
    assert estratti[f"foto/{_relativo(scena, verso)}"] == dati_toppa
    assert estratti[f"foto/{ORIGINALI}/mare.jpg"] == scena.dati[FOTO]
    ritoccata = estratti[f"foto/{FOTO}"]
    assert _impronta(ritoccata) == riga["impronta_copia"]
    assert _quanto_cambia(ritoccata, scena.dati[FOTO]) > 20
    assert _quanto_cambia(ritoccata, scena.dati[FOTO], LONTANO) < 2
    di_prova._mai_fuori_dal_cestino(scena, tmp_path, dati_toppa, ritoccata)


@pytest.mark.parametrize("come", ["subito", "in_coda"])
def test_dopo_il_si_un_altro_ritocco_rilegge_la_toppa_dall_archivio(scena, tmp_path, come):
    lavoro_id, _, ritocco, togliere = _da_rivedere(scena)
    coda.approva(scena.archivio, lavoro_id)
    prima = _estratta(scena, tmp_path, "prima")[f"foto/{FOTO}"]
    shutil.rmtree(tmp_path / "prima")
    verso = _nell_archivio(scena, ritocco)
    if come == "subito":
        assert _metti(scena, ALTRA_ZONA) == scena.scatto
    else:
        secondo = coda.metti(scena.archivio, [{"file_id": scena.file_id,
                                               **_volto(scena.dati[FOTO], ALTRA_ZONA)}])
        _gira(scena, togliere)
        coda.approva(scena.archivio, secondo)
        assert _lavoro(scena, secondo)["stato"] == coda.FATTO
    assert len(togliere.lavori) == 1
    assert _ritocco(scena, ritocco["id"])["risultato"] == str(verso)
    assert _in_attesa(scena) == [] and _rimaste(scena) == []
    assert _storia(scena, _relativo(scena, verso)) == [(ritocco["impronta_risultato"], True)]
    _mai_in_chiaro(tmp_path, scena.dati[FOTO])
    riga = _ritoccata(scena)
    ritoccata = _estratta(scena, tmp_path)[f"foto/{FOTO}"]
    assert _impronta(ritoccata) == riga["impronta_copia"]
    _tolta_e_pixelata(ritoccata, scena.dati[FOTO])
    assert _quanto_cambia(ritoccata, prima) < 2


@pytest.mark.parametrize("forzata", [CHIUSO, SI_APRE])
def test_con_l_archivio_chiuso_togliere_resta_in_coda_e_poi_si_fa(scena, monkeypatch,
                                                                  forzata):
    lavoro_id = _in_coda(scena)
    scena.situazione.forzata = forzata
    avvisi = _eventi(monkeypatch, "avviso")
    togliere = Togliere()
    _gira(scena, togliere)
    adesso = _lavoro(scena, lavoro_id)
    assert adesso["stato"] == coda.IN_CODA and adesso["guasto"] == lavoro.ASPETTA
    assert adesso["iniziato_il"] is None
    assert togliere.lavori == [] and _in_attesa(scena) == []
    [ritocco] = _del_lavoro(scena, lavoro_id)
    assert ritocco["stato"] == elenco.IN_CODA and ritocco["risultato"] is None
    assert avvisi == [("ritocco.aspetta_l_archivio", {"lavoro": lavoro_id})]
    assert _pronte(scena, lavoro_id) == []
    scena.situazione.forzata = None
    _gira(scena, togliere)
    adesso = _lavoro(scena, lavoro_id)
    assert adesso["stato"] == coda.DA_RIVEDERE and adesso["guasto"] is None
    assert len(togliere.lavori) == 1


def test_il_messaggio_di_quando_si_aspetta_l_archivio():
    assert lavoro.ASPETTA == ("Serve l'Archivio sicuro, che è chiuso: il ritocco resta in "
                              "coda finché lo apri. Lo scatto non è stato toccato.")


def test_mentre_uno_aspetta_l_archivio_gli_altri_si_fanno(scena):
    primo = _in_coda(scena)
    sole = _file_id(scena.archivio, "sole.jpg")
    secondo = coda.metti(scena.archivio, [{"file_id": sole, **_volto(scena.dati[SOLE])}])
    scena.situazione.forzata = CHIUSO
    _gira(scena, Togliere())
    assert _lavoro(scena, primo)["stato"] == coda.IN_CODA
    assert _lavoro(scena, secondo)["stato"] == coda.DA_RIVEDERE


def test_senza_archivio_togliere_non_riesce_e_lo_dice(scena):
    lavoro_id = _in_coda(scena)
    scena.situazione.forzata = SENZA_ARCHIVIO
    togliere = Togliere()
    _gira(scena, togliere)
    adesso = _lavoro(scena, lavoro_id)
    assert adesso["stato"] == coda.FALLITO and adesso["guasto"] == copia.NON_SUL_DISCO
    assert togliere.lavori == [] and _in_attesa(scena) == []


class _PoiSiChiude(Togliere):

    def __init__(self, scena):
        super().__init__()
        self.scena = scena

    def __call__(self, lavoro_togli: dict, ricorda) -> dict:
        fatto = super().__call__(lavoro_togli, ricorda)
        self.scena.situazione.forzata = CHIUSO
        return fatto


def test_se_l_archivio_si_chiude_dopo_la_toppa_la_toppa_resta_e_si_riprende(scena):
    lavoro_id = _in_coda(scena)
    _gira(scena, _PoiSiChiude(scena))
    adesso = _lavoro(scena, lavoro_id)
    assert adesso["stato"] == coda.IN_CODA and adesso["guasto"] == lavoro.ASPETTA
    [ritocco] = _del_lavoro(scena, lavoro_id)
    toppa = Path(ritocco["risultato"])
    assert copia.toppa_pronta(ritocco) and _in_attesa(scena) == [toppa]
    assert _pronte(scena, lavoro_id) == []
    scena.situazione.forzata = None
    togliere = Togliere()
    _gira(scena, togliere)
    assert togliere.lavori == []
    assert _lavoro(scena, lavoro_id)["stato"] == coda.DA_RIVEDERE
    [pronta] = _pronte(scena, lavoro_id)
    assert dict(_del_lavoro(scena, lavoro_id)[0]) == dict(ritocco)
    assert sorted(_in_attesa(scena)) == sorted([pronta, toppa])
    coda.approva(scena.archivio, lavoro_id)
    assert _lavoro(scena, lavoro_id)["stato"] == coda.FATTO
    assert _in_attesa(scena) == []


def _sul_disco_al_posto_della_toppa(scena, spia) -> None:
    def mettine_uno(richiesta):
        if richiesta.get("come") == copia.AGGIUNGI:
            Path(richiesta["verso"]).parent.mkdir(parents=True, exist_ok=True)
            Path(richiesta["verso"]).write_bytes(b"un altro")

    spia.prima = mettine_uno


@pytest.mark.parametrize("modo, messaggio", [
    ("muto", copia.NON_PRESO),
    ("occupato", copia.NON_PRESO),
    ("sul_disco", copia.NON_SALVATO["sul_disco"]),
    ("chiuso", copia.SOLO_NELL_ARCHIVIO),
    ("prima_aprilo", copia.SOLO_NELL_ARCHIVIO),
    ("rotto", copia.TOPPE_A_META),
    ("a_meta", copia.TOPPE_A_META),
    ("a_meta_con_esito", copia.TOPPE_A_META),
    ("senza_esito", copia.TOPPE_A_META)])
def test_se_l_archivio_non_prende_la_toppa_niente_cambia_e_si_riprova(
        scena, monkeypatch, modo, messaggio):
    lavoro_id, pronta, ritocco, _ = _da_rivedere(scena)
    toppa = Path(ritocco["risultato"])
    spia = _Accoglie(scena, monkeypatch)
    if modo == "occupato":
        spia.modo = ErroreOfficina("sta già facendo altro", codice="occupato")
    elif modo == "rotto":
        spia.modo = RuntimeError("rotto")
    elif modo == "prima_aprilo":
        spia.modo = ErroreOfficina("prima aprilo", codice=copia.SICURO_CHIUSO)
    elif modo == "sul_disco":
        _sul_disco_al_posto_della_toppa(scena, spia)
    elif modo == "chiuso":
        spia.prima = lambda richiesta: scena.casa.archivio.chiudi(ATTESA)
    else:
        spia.modo = modo
    errori = _eventi(monkeypatch, "errore")
    errore = _fermato(lambda: coda.approva(scena.archivio, lavoro_id))
    assert str(errore) == messaggio
    codici = {"chiuso": copia.SICURO_CHIUSO, "occupato": "occupato",
              "prima_aprilo": copia.SICURO_CHIUSO, "sul_disco": "sul_disco"}
    assert errore.codice == codici.get(modo, copia.RitoccoFermato.codice)
    adesso = _lavoro(scena, lavoro_id)
    assert adesso["stato"] == coda.DA_RIVEDERE and adesso["guasto"] == messaggio
    assert dict(_ritocco(scena, ritocco["id"])) == dict(ritocco)
    assert sorted(_in_attesa(scena)) == sorted([pronta, toppa])
    assert _ritoccata(scena) is None and scena.casa.cestino.mosse == []
    assert [chiesta.get("come") for chiesta in spia.chieste] == [copia.AGGIUNGI]
    assert ("ritocco.archivio_guasto" in [nome for nome, _ in errori]) == (modo == "rotto")
    if modo == "sul_disco":
        verso = _nell_archivio(scena, ritocco)
        assert verso.read_bytes() == b"un altro"
        verso.unlink()
    if modo == "chiuso":
        scena.casa.archivio.apri(PAROLA)
    assert _storia(scena, FOTO) == [(_impronta(scena.dati[FOTO]), True)]
    spia.modo = spia.prima = None
    coda.approva(scena.archivio, lavoro_id)
    assert _lavoro(scena, lavoro_id)["stato"] == coda.FATTO
    assert _in_attesa(scena) == [] and _rimaste(scena) == []
    verso = _nell_archivio(scena, ritocco)
    assert _storia(scena, _relativo(scena, verso)) == [(ritocco["impronta_risultato"], True)]


def test_con_l_archivio_chiuso_al_si_non_si_tocca_niente(scena, monkeypatch):
    lavoro_id, pronta, ritocco, _ = _da_rivedere(scena)
    spia = _Accoglie(scena, monkeypatch)
    scena.situazione.forzata = CHIUSO
    errore = _fermato(lambda: coda.approva(scena.archivio, lavoro_id))
    assert str(errore) == copia.SOLO_NELL_ARCHIVIO and errore.codice == copia.SICURO_CHIUSO
    assert _lavoro(scena, lavoro_id)["stato"] == coda.DA_RIVEDERE
    assert spia.chieste == [] and scena.casa.cestino.mosse == []
    assert sorted(_in_attesa(scena)) == sorted([pronta, Path(ritocco["risultato"])])
    scena.situazione.forzata = None
    coda.approva(scena.archivio, lavoro_id)
    assert _lavoro(scena, lavoro_id)["stato"] == coda.FATTO


def test_se_la_toppa_in_attesa_e_cambiata_al_si_non_si_tocca_niente(scena, monkeypatch):
    lavoro_id, pronta, ritocco, _ = _da_rivedere(scena)
    toppa = Path(ritocco["risultato"])
    toppa.write_bytes(toppa.read_bytes() + b"x")
    spia = _Accoglie(scena, monkeypatch)
    errore = _fermato(lambda: coda.approva(scena.archivio, lavoro_id))
    assert str(errore) == copia.TOPPA_PERSA
    assert _lavoro(scena, lavoro_id)["stato"] == coda.DA_RIVEDERE
    assert spia.chieste == [] and scena.casa.cestino.mosse == []
    assert toppa.is_file() and pronta.is_file() and _ritoccata(scena) is None


def test_se_l_archivio_prende_la_toppa_ma_non_la_copia_la_toppa_resta_nell_archivio(
        scena, monkeypatch):
    lavoro_id, pronta, ritocco, _, spia = _toppa_nell_archivio_e_copia_no(scena, monkeypatch)
    toppa = Path(ritocco["risultato"])
    verso = _nell_archivio(scena, ritocco)
    adesso = _lavoro(scena, lavoro_id)
    assert adesso["stato"] == coda.DA_RIVEDERE and adesso["guasto"] == copia.NON_PRESO
    dopo = _ritocco(scena, ritocco["id"])
    assert dopo["stato"] == elenco.IN_CODA and dopo["risultato"] == str(verso)
    assert dopo["impronta_risultato"] == ritocco["impronta_risultato"]
    assert _in_attesa(scena) == [pronta] and _mosse(scena) == [toppa]
    assert _ritoccata(scena) is None and _rimaste(scena) == []
    assert copia.toppa_gia_fatta(dopo) and not copia.toppa_pronta(dopo)
    coda.approva(scena.archivio, lavoro_id)
    assert _lavoro(scena, lavoro_id)["stato"] == coda.FATTO
    assert [chiesta.get("come") for chiesta in spia.chieste] == [copia.AGGIUNGI, None, None]
    assert _mosse(scena) == [toppa, pronta] and _in_attesa(scena) == []


def test_con_la_toppa_gia_nell_archivio_rifare_il_lavoro_non_richiama_il_modello(
        scena, tmp_path, monkeypatch):
    lavoro_id, _, ritocco, togliere, spia = _toppa_nell_archivio_e_copia_no(scena,
                                                                            monkeypatch)
    verso = _nell_archivio(scena, ritocco)
    secondo = coda.metti(scena.archivio, [{"file_id": scena.file_id,
                                           **_volto(scena.dati[FOTO], ALTRA_ZONA)}])
    assert secondo == lavoro_id and _in_attesa(scena) == []
    _gira(scena, togliere)
    assert len(togliere.lavori) == 1
    assert _lavoro(scena, lavoro_id)["stato"] == coda.DA_RIVEDERE
    assert _ritocco(scena, ritocco["id"])["risultato"] == str(verso)
    [pronta] = _pronte(scena, lavoro_id)
    assert _in_attesa(scena) == [pronta]
    coda.approva(scena.archivio, lavoro_id)
    assert _lavoro(scena, lavoro_id)["stato"] == coda.FATTO
    assert [chiesta.get("come") for chiesta in spia.chieste] == [copia.AGGIUNGI, None, None]
    _tolta_e_pixelata(_estratta(scena, tmp_path)[f"foto/{FOTO}"], scena.dati[FOTO])


def test_se_la_toppa_nell_archivio_non_si_trova_si_rifa(scena, monkeypatch):
    lavoro_id, _, ritocco, togliere, _ = _toppa_nell_archivio_e_copia_no(scena, monkeypatch)
    with scena.archivio.scrittura() as connessione:
        connessione.execute("UPDATE ritocchi SET impronta_risultato = ? WHERE id = ?",
                            ("cd" * 32, ritocco["id"]))
    coda.metti(scena.archivio, [{"file_id": scena.file_id,
                                 **_volto(scena.dati[FOTO], ALTRA_ZONA)}])
    _gira(scena, togliere)
    assert len(togliere.lavori) == 2
    assert _lavoro(scena, lavoro_id)["stato"] == coda.DA_RIVEDERE
    dopo = _ritocco(scena, ritocco["id"])
    assert copia.toppa_pronta(dopo) and attesa.e_dentro(Path(dopo["risultato"]))


def test_con_l_archivio_chiuso_non_si_sa_se_la_toppa_e_fatta_e_lo_dice(scena, monkeypatch):
    _, _, ritocco, _, _ = _toppa_nell_archivio_e_copia_no(scena, monkeypatch)
    dopo = _ritocco(scena, ritocco["id"])
    assert copia.toppa_gia_fatta(dopo)
    for forzata in (CHIUSO, SI_APRE):
        scena.situazione.forzata = forzata
        errore = _fermato(lambda: copia.toppa_gia_fatta(dopo))
        assert str(errore) == copia.TOPPA_CHIUSA and errore.codice == copia.SICURO_CHIUSO
    scena.situazione.forzata = SENZA_ARCHIVIO
    assert not copia.toppa_gia_fatta(dopo)
    scena.situazione.forzata = None
    assert not copia.toppa_gia_fatta({**dict(dopo), "impronta_risultato": "cd" * 32})
    assert not copia.toppa_gia_fatta({**dict(dopo), "origine_x": None})
    assert not copia.toppa_gia_fatta({**dict(dopo), "risultato": None})


def test_una_toppa_che_c_e_sul_disco_ma_cambiata_non_si_cerca_nell_archivio(scena, tmp_path,
                                                                           monkeypatch):
    _, _, ritocco, _, _ = _toppa_nell_archivio_e_copia_no(scena, monkeypatch)
    al_suo_posto = tmp_path / "toppa.png"
    al_suo_posto.write_bytes(b"un altro")
    scena.situazione.forzata = CHIUSO
    assert not copia.toppa_gia_fatta({**dict(ritocco), "risultato": str(al_suo_posto)})


def test_rifiutare_dopo_la_toppa_nell_archivio_la_lascia_nella_storia(scena, monkeypatch):
    lavoro_id, pronta, ritocco, _, _ = _toppa_nell_archivio_e_copia_no(scena, monkeypatch)
    verso = _nell_archivio(scena, ritocco)
    coda.rifiuta(scena.archivio, lavoro_id)
    assert _lavoro(scena, lavoro_id)["stato"] == coda.RIFIUTATO
    dopo = _ritocco(scena, ritocco["id"])
    assert dopo["stato"] == elenco.RIFIUTATO and dopo["risultato"] is None
    assert _in_attesa(scena) == [] and not os.path.lexists(pronta)
    assert _storia(scena, _relativo(scena, verso)) == [(ritocco["impronta_risultato"], True)]
    assert _storia(scena, FOTO) == [(_impronta(scena.dati[FOTO]), True)]
    assert _ritoccata(scena) is None


def test_rifiutare_butta_la_toppa_e_la_copia_in_attesa(scena):
    lavoro_id, pronta, ritocco, _ = _da_rivedere(scena)
    coda.rifiuta(scena.archivio, lavoro_id)
    assert _lavoro(scena, lavoro_id)["stato"] == coda.RIFIUTATO
    dopo = _ritocco(scena, ritocco["id"])
    assert dopo["stato"] == elenco.RIFIUTATO and dopo["risultato"] is None
    assert _in_attesa(scena) == [] and _rimaste(scena) == []
    assert scena.casa.cestino.mosse == [] and _ritoccata(scena) is None
    assert _storia(scena, FOTO) == [(_impronta(scena.dati[FOTO]), True)]


def test_se_la_copia_in_attesa_non_si_cancella_al_no_resta_segnata(scena, monkeypatch):
    lavoro_id, pronta, ritocco, _ = _da_rivedere(scena)
    vera = sfida_togli.butta

    def bloccata(file):
        raise PermissionError(13, "bloccato")

    monkeypatch.setattr(sfida_togli, "butta", bloccata)
    avvisi = _eventi(monkeypatch, "avviso")
    coda.rifiuta(scena.archivio, lavoro_id)
    [rimasta] = _rimaste(scena)
    assert rimasta["percorso"] == str(pronta) and rimasta["file_id"] == scena.file_id
    assert rimasta["impronta"] == impronta.del_file(pronta)
    assert "ritocco.pronta_non_tolta" in [nome for nome, _ in avvisi]
    assert not os.path.lexists(ritocco["risultato"])
    monkeypatch.setattr(sfida_togli, "butta", vera)
    assert in_chiaro.butta_tutte(scena.archivio) == 1
    assert _mosse(scena) == [pronta] and _rimaste(scena) == []


def test_buttare_segna_solo_le_copie_ritoccate_in_attesa(scena, tmp_path, monkeypatch):
    def bloccata(file):
        raise PermissionError(13, "bloccato")

    monkeypatch.setattr(sfida_togli, "butta", bloccata)
    dove = scena.casa.foto / attesa.NOME
    giusta = dove / f"{copia.PREFISSO}-{scena.file_id}-mare.jpg"
    coda._butta(scena.archivio, [
        (dove / "togli-3-b.png", None, None),
        (scena.base.parent / copia.CARTELLA / "togli-3.png", scena.file_id, "ab" * 32, 3),
        (giusta, scena.file_id, "ab" * 32),
        (tmp_path / f"{copia.PREFISSO}-{scena.file_id}-mare.jpg", scena.file_id, "ab" * 32),
        (dove / "mare.jpg", scena.file_id, "ab" * 32),
        (dove / f"{copia.PREFISSO}-{scena.file_id}-sole.jpg", scena.file_id, None),
        (dove / f"{copia.PREFISSO}-{scena.file_id}-onde.mp4", None, "ab" * 32)])
    assert [(riga["percorso"], riga["impronta"]) for riga in _rimaste(scena)] == [
        (str(giusta), "ab" * 32)]


def _prepara_rotto(monkeypatch, blocca: list | None = None) -> None:
    def prepara(file_id, sorgente, dove, formato, ritocchi, *altro, **piu):
        if blocca is not None:
            blocca.extend(Path(ritocco["risultato"]) for ritocco in ritocchi
                          if ritocco["genere"] == elenco.TOGLI)
        raise copia.RitoccoFermato(copia.ROVINATA)

    monkeypatch.setattr(copia, "_prepara", prepara)


def test_se_il_lavoro_non_riesce_la_toppa_in_attesa_se_ne_va(scena, monkeypatch):
    vero = copia._prepara
    lavoro_id = _in_coda(scena)
    _prepara_rotto(monkeypatch)
    togliere = Togliere()
    _gira(scena, togliere)
    adesso = _lavoro(scena, lavoro_id)
    assert adesso["stato"] == coda.FALLITO and adesso["guasto"] == copia.ROVINATA
    [ritocco] = _del_lavoro(scena, lavoro_id)
    assert ritocco["stato"] == elenco.FALLITO and ritocco["guasto"] == copia.ROVINATA
    assert ritocco["risultato"] is None and ritocco["impronta_risultato"] is None
    [chiesto] = togliere.lavori
    assert not os.path.lexists(chiesto["uscita"])
    assert _in_attesa(scena) == [] and _rimaste(scena) == []
    monkeypatch.setattr(copia, "_prepara", vero)
    coda.rimetti(scena.archivio, lavoro_id)
    _gira(scena, togliere)
    assert len(togliere.lavori) == 2
    assert _lavoro(scena, lavoro_id)["stato"] == coda.DA_RIVEDERE


def test_se_la_toppa_in_attesa_non_si_cancella_resta_segnata(scena, monkeypatch):
    lavoro_id = _in_coda(scena)
    blocca: list[Path] = []
    vero_unlink = Path.unlink

    def unlink(percorso, *altro, **piu):
        if percorso in blocca:
            raise PermissionError(13, "bloccato")
        return vero_unlink(percorso, *altro, **piu)

    monkeypatch.setattr(Path, "unlink", unlink)
    _prepara_rotto(monkeypatch, blocca)
    avvisi = _eventi(monkeypatch, "avviso")
    _gira(scena, Togliere())
    [toppa] = blocca
    assert _lavoro(scena, lavoro_id)["stato"] == coda.FALLITO
    assert toppa.is_file() and attesa.e_dentro(toppa)
    [rimasta] = _rimaste(scena)
    assert rimasta["percorso"] == str(toppa) and rimasta["file_id"] == scena.file_id
    assert rimasta["impronta"] == impronta.del_file(toppa)
    assert "ritocco.toppa_non_tolta" in [nome for nome, _ in avvisi]
    blocca.clear()
    assert in_chiaro.butta_tutte(scena.archivio) == 1
    assert _mosse(scena) == [toppa] and _rimaste(scena) == []
    assert not os.path.lexists(toppa)


def test_il_nome_della_toppa_in_attesa_salta_quelli_rimasti(scena, tmp_path):
    dove = tmp_path / attesa.NOME
    with scena.archivio.lettura() as connessione:
        assert copia.toppa_in_attesa(connessione, dove, 5) == dove / "togli-5.png"
        assert copia.toppa_in_attesa(connessione, dove, 5, True) == dove / "togli-5-b.png"
    with scena.archivio.scrittura() as connessione:
        in_chiaro.segna(connessione, scena.file_id, dove / "togli-5.png", "x")
        in_chiaro.segna(connessione, scena.file_id, dove / "togli-5-a1.png", "x")
        in_chiaro.segna(connessione, scena.file_id, dove / "togli-5-b.png", "x")
    with scena.archivio.lettura() as connessione:
        assert copia.toppa_in_attesa(connessione, dove, 5) == dove / "togli-5-a2.png"
        assert copia.toppa_in_attesa(connessione, dove, 5, True) == dove / "togli-5-a1-b.png"
        assert copia.toppa_in_attesa(connessione, dove, 6) == dove / "togli-6.png"


def _riga(percorso, ritocco_id: int = 5, genere: str = elenco.TOGLI) -> dict:
    return {"id": ritocco_id, "file_id": 1, "genere": genere, "impronta_risultato": "x",
            "risultato": None if percorso is None else str(percorso)}


def test_buttare_le_toppe_tocca_solo_le_toppe_di_quel_ritocco(tmp_path):
    dove = tmp_path / attesa.NOME
    toppe = tmp_path / attesa.ORIGINALI / copia.CARTELLA
    via = [dove / "togli-5.png", dove / "togli-5-a2.png", dove / "togli-5-a2-b.png",
           dove / "togli-5-b.png", dove / "togli-5-a10.png", toppe / "togli-5.png"]
    restano = [dove / "togli-6.png", dove / "togli-5-a.png", dove / "togli-5-a٣.png",
               dove / "togli-5-abc.png", dove / "togli-5.jpg", tmp_path / "togli-5.png",
               toppe / "togli-5-a12345678901.png", toppe / "togli-5-a1.png",
               dove / "togli-15.png", dove / "xtogli-5.png", dove / "12.png",
               dove / "togli-5-12.png"]
    for percorso in via + restano:
        percorso.parent.mkdir(parents=True, exist_ok=True)
        percorso.write_bytes(b"toppa")
    cartella_toppa = dove / "sotto" / "togli-5.png"
    cartella_toppa.mkdir(parents=True)
    pixela = dove / "altra" / "togli-5.png"
    pixela.parent.mkdir()
    pixela.write_bytes(b"toppa")
    copia.butta_le_toppe([_riga(percorso) for percorso in via + restano + [cartella_toppa]]
                         + [_riga(pixela, genere=elenco.PIXELA), _riga(None)])
    assert [percorso for percorso in via if percorso.exists()] == []
    assert [percorso for percorso in restano if not percorso.is_file()] == []
    assert cartella_toppa.is_dir() and pixela.is_file()


def test_si_buttano_al_lavoro_finito_male_solo_le_toppe_in_attesa(tmp_path):
    dove = tmp_path / attesa.NOME
    assert copia.toppa_in_attesa_da_buttare(_riga(dove / "togli-5.png"))
    assert copia.toppa_in_attesa_da_buttare(_riga(dove / "togli-5-a3-b.png"))
    assert not copia.toppa_in_attesa_da_buttare(_riga(dove / "togli-6.png"))
    assert not copia.toppa_in_attesa_da_buttare(
        _riga(tmp_path / attesa.ORIGINALI / copia.CARTELLA / "togli-5.png"))
    assert not copia.toppa_in_attesa_da_buttare(_riga(dove / "togli-5.png",
                                                      genere=elenco.PIXELA))
    assert not copia.toppa_in_attesa_da_buttare(_riga(None))


@pytest.mark.parametrize("come", ["di_nuovo", "ripara"])
def test_se_l_archivio_si_ferma_a_meta_sulla_copia_il_lavoro_resta_in_scambio(
        scena, monkeypatch, come):
    lavoro_id, pronta, ritocco, _ = _da_rivedere(scena)
    spia = _Accoglie(scena, monkeypatch)
    _solo_la_toppa(spia, "a_meta")
    errore = _fermato(lambda: coda.approva(scena.archivio, lavoro_id))
    assert str(errore) == copia.FERMO_A_META
    adesso = _lavoro(scena, lavoro_id)
    assert adesso["stato"] == coda.IN_SCAMBIO and adesso["guasto"] == copia.FERMO_A_META
    riga = _ritoccata(scena)
    assert riga["stato"] == copia.IN_SCAMBIO and riga["in_preparazione"] == str(pronta)
    assert copia.fermo_a_meta(scena.archivio, scena.file_id, str(pronta))
    rifiuto = _fermato(lambda: coda.rifiuta(scena.archivio, lavoro_id))
    assert str(rifiuto) == coda.NON_DA_RIVEDERE and pronta.is_file()
    spia.prima = spia.modo = None
    if come == "ripara":
        assert coda.ripara(scena.archivio) == {"rimessi": 0, "finiti": 1, "fermi": 0}
    else:
        coda.approva(scena.archivio, lavoro_id)
    assert _lavoro(scena, lavoro_id)["stato"] == coda.FATTO
    assert _ritocco(scena, ritocco["id"])["stato"] == elenco.FATTO
    dopo = _ritoccata(scena)
    assert dopo["stato"] == copia.FATTA and dopo["impronta_copia"] == riga["impronta_nuova"]
    assert _in_attesa(scena) == [] and _rimaste(scena) == []
    assert [chiesta.get("come") for chiesta in spia.chieste] == [copia.AGGIUNGI, None, None]
    assert not copia.fermo_a_meta(scena.archivio, scena.file_id, str(pronta))


def test_fermo_a_meta_guarda_solo_lo_scambio_di_quella_copia_nell_archivio(scena,
                                                                         monkeypatch):
    _, pronta, _, _ = _da_rivedere(scena)
    assert not copia.fermo_a_meta(scena.archivio, scena.file_id, str(pronta))
    _lavoro_fermo(scena, monkeypatch)
    assert copia.fermo_a_meta(scena.archivio, scena.file_id, str(pronta))
    assert copia.fermo_a_meta(scena.archivio, scena.file_id, pronta)
    assert not copia.fermo_a_meta(scena.archivio, scena.file_id, str(pronta) + "x")
    assert not copia.fermo_a_meta(scena.archivio, scena.file_id, None)
    assert not copia.fermo_a_meta(scena.archivio, scena.file_id + 1000, str(pronta))
    with scena.archivio.scrittura() as connessione:
        connessione.execute("UPDATE ritoccate SET nell_archivio = 0")
    assert not copia.fermo_a_meta(scena.archivio, scena.file_id, str(pronta))
    with scena.archivio.scrittura() as connessione:
        connessione.execute("UPDATE ritoccate SET nell_archivio = 1, stato = ?",
                            (copia.IN_RITORNO,))
    assert copia.fermo_a_meta(scena.archivio, scena.file_id, None)
    with scena.archivio.scrittura() as connessione:
        connessione.execute("UPDATE ritoccate SET stato = ?", (copia.FATTA,))
    assert not copia.fermo_a_meta(scena.archivio, scena.file_id, None)
    assert not copia.fermo_a_meta(scena.archivio, scena.file_id, str(pronta))


def _lavoro_fermo(scena, monkeypatch) -> None:
    with scena.archivio.lettura() as connessione:
        [lavoro_id] = [riga["id"] for riga in coda.in_stato(connessione, coda.DA_RIVEDERE)]
    spia = _Accoglie(scena, monkeypatch)
    _solo_la_toppa(spia, "a_meta")
    _fermato(lambda: coda.approva(scena.archivio, lavoro_id))


def test_se_l_archivio_non_prende_la_copia_dopo_la_toppa_il_lavoro_torna_da_rivedere(
        scena, monkeypatch):
    lavoro_id, pronta, _, _, _ = _toppa_nell_archivio_e_copia_no(scena, monkeypatch)
    assert not copia.fermo_a_meta(scena.archivio, scena.file_id, str(pronta))
    assert _lavoro(scena, lavoro_id)["stato"] == coda.DA_RIVEDERE


class _LasciaIlParziale(Togliere):

    def __call__(self, lavoro_togli: dict, ricorda) -> dict:
        self.lavori.append(lavoro_togli)
        uscita = Path(lavoro_togli["uscita"])
        uscita.with_name(uscita.name + ".parziale").write_bytes(b"a meta")
        return {"guasto": "togli_motore_sconosciuto"}


def test_se_il_motore_lascia_un_parziale_nella_cartella_di_attesa_se_ne_va(scena):
    lavoro_id = _in_coda(scena)
    togliere = _LasciaIlParziale()
    _gira(scena, togliere)
    adesso = _lavoro(scena, lavoro_id)
    assert adesso["stato"] == coda.FALLITO
    assert adesso["guasto"] == lavoro.NON_TOLTO.format(perche="non è installato")
    [chiesto] = togliere.lavori
    uscita = Path(chiesto["uscita"])
    assert not os.path.lexists(uscita.with_name(uscita.name + ".parziale"))
    assert not os.path.lexists(uscita)
    assert _in_attesa(scena) == [] and _rimaste(scena) == []


def test_la_stessa_coda_dopo_aver_aspettato_l_archivio_riparte_e_lo_fa(scena):
    lavoro_id = _in_coda(scena)
    scena.situazione.forzata = CHIUSO
    togliere = Togliere()
    ritoccatore = lavoro.Ritoccatore(scena.archivio, a_parte=False, toglie=togliere)
    for volta in (1, 2):
        assert ritoccatore.parti()
        assert ritoccatore.lavoro.aspetta_che_finisca(60)
        assert not ritoccatore.lavoro.guasto, ritoccatore.lavoro.guasto
        adesso = _lavoro(scena, lavoro_id)
        if volta == 1:
            assert adesso["stato"] == coda.IN_CODA and adesso["guasto"] == lavoro.ASPETTA
            scena.situazione.forzata = None
    assert adesso["stato"] == coda.DA_RIVEDERE and adesso["guasto"] is None
    assert len(togliere.lavori) == 1


def test_il_nome_della_toppa_nell_archivio_ha_il_numero_e_un_pezzo_dell_impronta():
    assert copia.nome_della_toppa_nell_archivio(7, "0123456789abcdef" * 4) == (
        "togli-7-0123456789ab.png")


def _fatto(scena):
    lavoro_id, _, ritocco, togliere = _da_rivedere(scena)
    coda.approva(scena.archivio, lavoro_id)
    assert _lavoro(scena, lavoro_id)["stato"] == coda.FATTO
    return _ritocco(scena, ritocco["id"]), togliere


def _cerca_per_la_toppa(scena, monkeypatch, sua: str, cambia) -> list:
    vera = scena.casa.archivio.cerca
    chieste: list = []

    def cerca(impronta_cercata, *altro, **piu):
        ricerca = vera(impronta_cercata, *altro, **piu)
        if impronta_cercata != sua:
            return ricerca
        chieste.append((altro, piu))
        return cambia(ricerca)

    monkeypatch.setattr(scena.casa.archivio, "cerca", cerca)
    return chieste


def test_la_toppa_si_cerca_nell_archivio_col_suo_nome_e_intera(scena, monkeypatch):
    dopo, _ = _fatto(scena)
    chieste = _cerca_per_la_toppa(scena, monkeypatch, dopo["impronta_risultato"],
                                  lambda ricerca: ricerca)
    assert copia.toppa_gia_fatta(dopo)
    assert chieste == [((None, []), {"nome": Path(dopo["risultato"]).name, "intero": True})]


def test_se_l_archivio_non_risponde_sulla_toppa_lo_dice_come_chiuso(scena, monkeypatch):
    dopo, _ = _fatto(scena)
    monkeypatch.setattr(scena.casa.archivio, "cerca", _non_risponde)
    avvisi = _eventi(monkeypatch, "avviso")
    errore = _fermato(lambda: copia.toppa_gia_fatta(dopo))
    assert str(errore) == copia.TOPPA_CHIUSA and errore.codice == copia.SICURO_CHIUSO
    assert avvisi == [("ritocco.archivio_non_risponde", {"motivo": "occupato"})]


def _da_rifare_dopo(scena, togliere) -> int:
    secondo = coda.metti(scena.archivio, [{"file_id": scena.file_id,
                                           **_volto(scena.dati[FOTO], ALTRA_ZONA)}])
    _gira(scena, togliere)
    return secondo


@pytest.mark.parametrize("come", ["diversa", "altra_impronta", "altri_byte", "non_c_e"])
def test_una_toppa_nell_archivio_che_non_e_lei_non_si_usa(scena, monkeypatch, come):
    dopo, togliere = _fatto(scena)
    sua = dopo["impronta_risultato"]
    copia_prima = _ritoccata(scena)["impronta_copia"]
    altra = scena.casa.archivio.cerca(_impronta(scena.dati[SOLE]), None, [],
                                      nome="sole.jpg", intero=True).trovata
    assert altra is not None

    def cambia(ricerca):
        if come == "diversa":
            return replace(ricerca, trovata=replace(ricerca.trovata, diversa=True))
        if come == "altra_impronta":
            return replace(ricerca, trovata=replace(ricerca.trovata, blake2b="cd" * 32))
        if come == "altri_byte":
            return replace(ricerca, trovata=replace(altra, blake2b=sua))
        return Ricerca(NON_C_E)

    _cerca_per_la_toppa(scena, monkeypatch, sua, cambia)
    assert copia.toppa_gia_fatta(dopo) == (come == "altri_byte")
    secondo = _da_rifare_dopo(scena, togliere)
    adesso = _lavoro(scena, secondo)
    assert adesso["stato"] == coda.FALLITO and adesso["guasto"] == copia.TOPPA_PERSA
    assert len(togliere.lavori) == 1
    assert _ritoccata(scena)["impronta_copia"] == copia_prima
    assert _in_attesa(scena) == [] and _rimaste(scena) == []


def test_una_toppa_rovinata_nell_archivio_lo_dice_e_non_si_usa(scena):
    dopo, togliere = _fatto(scena)
    copia_prima = _ritoccata(scena)["impronta_copia"]
    _stacca(scena.casa)
    _rovina(scena.casa, _relativo(scena, Path(dopo["risultato"])))
    secondo = _da_rifare_dopo(scena, togliere)
    adesso = _lavoro(scena, secondo)
    assert adesso["stato"] == coda.FALLITO and adesso["guasto"] == copia.TOPPA_ROVINATA
    assert _ritoccata(scena)["impronta_copia"] == copia_prima
    assert _in_attesa(scena) == [] and _rimaste(scena) == []


@pytest.mark.parametrize("codice, messaggio, codice_fuori", [
    (PERSA, copia.TOPPA_ROVINATA, copia.RitoccoFermato.codice),
    ("sicuro_chiuso", copia.TOPPA_CHIUSA, copia.SICURO_CHIUSO),
    (None, copia.TOPPA_CHIUSA, copia.SICURO_CHIUSO)])
def test_leggendo_una_toppa_dice_i_guasti_della_toppa(codice, messaggio, codice_fuori):
    trovata = DallArchivio("00" * 16, "s/togli-5.png", 3, "ab" * 32, True, False,
                           lambda _: None)
    with pytest.raises(copia.RitoccoFermato) as preso, copia.leggendo(trovata, True):
        trovata.segna_guasto(codice)
    assert str(preso.value) == messaggio and preso.value.codice == codice_fuori


def test_una_toppa_sul_disco_cambiata_non_si_mette(scena, tmp_path):
    dopo, _ = _fatto(scena)
    finta = tmp_path / "togli-5.png"
    finta.write_bytes(b"un'altra")
    vuota = Image.new("RGB", _misure(scena.dati[FOTO]))
    with pytest.raises(copia.RitoccoFermato) as preso:
        copia.disegna(vuota, [{**dict(dopo), "risultato": str(finta)}])
    assert str(preso.value) == copia.TOPPA_PERSA


def test_se_l_archivio_si_chiude_proprio_prima_della_toppa_niente_cambia(scena, monkeypatch):
    lavoro_id, pronta, ritocco, _ = _da_rivedere(scena)
    vero = archivio_sicuro.per_le_foto

    def per_le_foto():
        if sys._getframe(1).f_code.co_name == "_aggiungi_la_toppa":
            return CHIUSO, None
        return vero()

    monkeypatch.setattr(archivio_sicuro, "per_le_foto", per_le_foto)
    spia = _Accoglie(scena, monkeypatch)
    errore = _fermato(lambda: coda.approva(scena.archivio, lavoro_id))
    assert str(errore) == copia.SOLO_NELL_ARCHIVIO and errore.codice == copia.SICURO_CHIUSO
    assert _lavoro(scena, lavoro_id)["stato"] == coda.DA_RIVEDERE
    assert spia.chieste == [] and scena.casa.cestino.mosse == []
    assert sorted(_in_attesa(scena)) == sorted([pronta, Path(ritocco["risultato"])])
    assert dict(_ritocco(scena, ritocco["id"])) == dict(ritocco)


def test_al_secondo_ritocco_se_l_archivio_non_prende_la_copia_la_tiene_da_rivedere(
        scena, monkeypatch):
    dopo, togliere = _fatto(scena)
    prima = dict(_ritoccata(scena))
    secondo = _in_coda(scena, ALTRA_ZONA)
    _gira(scena, togliere)
    assert _lavoro(scena, secondo)["stato"] == coda.DA_RIVEDERE
    [pronta] = _pronte(scena, secondo)
    [ritocco] = _del_lavoro(scena, secondo)
    spia = _Accoglie(scena, monkeypatch)
    _solo_la_toppa(spia, "muto")
    errore = _fermato(lambda: coda.approva(scena.archivio, secondo))
    assert str(errore) == copia.NON_PRESO
    assert spia.chieste[0]["base"] == prima["percorso_base"] != prima["percorso_copia"]
    assert spia.chieste[0]["impronta_base"] == prima["impronta_base"]
    assert _lavoro(scena, secondo)["stato"] == coda.DA_RIVEDERE
    assert dict(_ritoccata(scena)) == prima and pronta.is_file()
    assert _ritocco(scena, ritocco["id"])["risultato"] == str(_nell_archivio(scena, ritocco))
    spia.prima = spia.modo = None
    coda.approva(scena.archivio, secondo)
    assert _lavoro(scena, secondo)["stato"] == coda.FATTO
    assert _ritoccata(scena)["impronta_copia"] != prima["impronta_copia"]
    assert _in_attesa(scena) == [] and _rimaste(scena) == []


def test_se_la_toppa_gia_nell_archivio_non_c_e_piu_al_si_si_ferma(scena, monkeypatch):
    lavoro_id, pronta, ritocco, _, spia = _toppa_nell_archivio_e_copia_no(scena, monkeypatch)
    prima = dict(_ritocco(scena, ritocco["id"]))
    _cerca_per_la_toppa(scena, monkeypatch, ritocco["impronta_risultato"],
                        lambda _: Ricerca(NON_C_E))
    errore = _fermato(lambda: coda.approva(scena.archivio, lavoro_id))
    assert str(errore) == copia.TOPPA_PERSA
    assert _lavoro(scena, lavoro_id)["stato"] == coda.DA_RIVEDERE
    assert dict(_ritocco(scena, ritocco["id"])) == prima
    assert _in_attesa(scena) == [pronta] and _ritoccata(scena) is None
    assert [chiesta.get("come") for chiesta in spia.chieste] == [copia.AGGIUNGI, None]


def test_una_toppa_tolta_che_non_c_e_piu_non_ferma_il_si(scena, monkeypatch):
    dopo, togliere = _fatto(scena)
    secondo = _in_coda(scena, ALTRA_ZONA)
    assert coda.togli(scena.archivio, dopo["id"]) == secondo
    _cerca_per_la_toppa(scena, monkeypatch, dopo["impronta_risultato"],
                        lambda _: Ricerca(NON_C_E))
    _gira(scena, togliere)
    assert _lavoro(scena, secondo)["stato"] == coda.DA_RIVEDERE
    coda.approva(scena.archivio, secondo)
    assert _lavoro(scena, secondo)["stato"] == coda.FATTO
    assert _ritocco(scena, dopo["id"])["stato"] == elenco.TOLTO
    assert _in_attesa(scena) == [] and _rimaste(scena) == []


def test_una_toppa_sul_disco_che_non_si_cancella_non_si_segna(scena, monkeypatch):
    sul_disco = scena.scatto.parent / attesa.ORIGINALI / copia.CARTELLA / "togli-5.png"
    in_attesa = scena.scatto.parent / attesa.NOME / "togli-5.png"
    for percorso in (sul_disco, in_attesa):
        percorso.parent.mkdir(parents=True, exist_ok=True)
        percorso.write_bytes(b"toppa")
    vero_unlink = Path.unlink

    def unlink(percorso, *altro, **piu):
        if percorso in (sul_disco, in_attesa):
            raise PermissionError(13, "bloccato")
        return vero_unlink(percorso, *altro, **piu)

    monkeypatch.setattr(Path, "unlink", unlink)
    copia.butta_le_toppe([{**_riga(sul_disco), "file_id": scena.file_id},
                          {**_riga(in_attesa), "file_id": scena.file_id}], scena.archivio)
    assert [riga["percorso"] for riga in _rimaste(scena)] == [str(in_attesa)]
    assert sul_disco.is_file() and in_attesa.is_file()


def test_dopo_lo_scambio_a_meta_la_copia_che_il_cestino_non_prende_resta(
        scena, tmp_path, monkeypatch):
    lavoro_id, pronta, _, _ = _da_rivedere(scena)
    sua = impronta.del_file(pronta)
    spia = _Accoglie(scena, monkeypatch)
    _solo_la_toppa(spia, "a_meta")
    _fermato(lambda: coda.approva(scena.archivio, lavoro_id))
    spia.prima = spia.modo = None
    cestino = CestinoFinto(tmp_path, modo="rifiuta")
    monkeypatch.setattr(archivio_sicuro, "il_cestino", lambda: cestino)
    coda.approva(scena.archivio, lavoro_id)
    assert _lavoro(scena, lavoro_id)["stato"] == coda.FATTO
    assert pronta.is_file() and cestino.mosse == [str(pronta)]
    [rimasta] = _rimaste(scena)
    assert (rimasta["percorso"], rimasta["impronta"]) == (str(pronta), sua)


def test_se_la_cartella_importata_non_c_e_piu_si_lavora_in_quella_del_programma(scena):
    shutil.rmtree(scena.casa.foto)
    lavoro_id, pronta, ritocco, togliere = _da_rivedere(scena)
    dove = scena.archivio.dove.radice / attesa.NOME
    [chiesto] = togliere.lavori
    assert Path(chiesto["uscita"]).parent == dove and pronta.parent == dove
    assert Path(ritocco["risultato"]).parent == dove
    assert not os.path.lexists(scena.casa.foto)
    coda.approva(scena.archivio, lavoro_id)
    assert _lavoro(scena, lavoro_id)["stato"] == coda.FATTO
    assert not os.path.lexists(scena.casa.foto)
    assert [percorso for percorso in dove.rglob("*") if percorso.is_file()] == []
    assert _ritoccata(scena)["percorso_copia"] == str(scena.scatto)


def test_un_video_solo_nell_archivio_per_ora_in_coda_non_si_ritocca(scena, monkeypatch):
    video = _file_id(scena.archivio, "onde.mp4")
    with monkeypatch.context() as cambio:
        cambio.setattr(file_media, "percorso_migliore", lambda *_: scena.casa.foto / FILMATO)
        lavoro_id = coda.metti(scena.archivio, [{
            "file_id": video, "genere": elenco.TOGLI,
            "seguito_id": _seguito(scena.archivio, video, quali=range(3))}])
    togliere = Togliere()
    _gira(scena, togliere)
    adesso = _lavoro(scena, lavoro_id)
    assert adesso["stato"] == coda.FALLITO and adesso["guasto"] == copia.NON_SUL_DISCO
    assert togliere.lavori == [] and _in_attesa(scena) == []


def test_se_il_lavoro_non_riesce_la_toppa_gia_nell_archivio_resta_e_si_riusa(scena,
                                                                           monkeypatch):
    lavoro_id, _, ritocco, togliere, _ = _toppa_nell_archivio_e_copia_no(scena, monkeypatch)
    verso = _nell_archivio(scena, ritocco)
    vero = copia._prepara
    nuovo = {"file_id": scena.file_id, **_volto(scena.dati[FOTO], ALTRA_ZONA)}
    assert coda.metti(scena.archivio, [nuovo]) == lavoro_id
    _prepara_rotto(monkeypatch)
    _gira(scena, togliere)
    assert _lavoro(scena, lavoro_id)["stato"] == coda.FALLITO
    dopo = _ritocco(scena, ritocco["id"])
    assert dopo["risultato"] == str(verso)
    assert dopo["impronta_risultato"] == ritocco["impronta_risultato"]
    monkeypatch.setattr(copia, "_prepara", vero)
    coda.rimetti(scena.archivio, lavoro_id)
    _gira(scena, togliere)
    assert _lavoro(scena, lavoro_id)["stato"] == coda.DA_RIVEDERE
    assert len(togliere.lavori) == 1


def test_al_no_la_toppa_in_attesa_che_non_si_cancella_resta_segnata(scena, monkeypatch):
    lavoro_id, pronta, ritocco, _ = _da_rivedere(scena)
    toppa = Path(ritocco["risultato"])
    vero_unlink = Path.unlink

    def unlink(percorso, *altro, **piu):
        if percorso == toppa:
            raise PermissionError(13, "bloccato")
        return vero_unlink(percorso, *altro, **piu)

    monkeypatch.setattr(Path, "unlink", unlink)
    coda.rifiuta(scena.archivio, lavoro_id)
    assert _lavoro(scena, lavoro_id)["stato"] == coda.RIFIUTATO
    assert [(riga["percorso"], riga["impronta"]) for riga in _rimaste(scena)] == [
        (str(toppa), ritocco["impronta_risultato"])]
    assert toppa.is_file() and not os.path.lexists(pronta)


def test_un_collegamento_rotto_in_originali_conta_come_un_file(scena, monkeypatch):
    lavoro_id, pronta, ritocco, _ = _da_rivedere(scena)
    verso = attesa.dove_va_l_originale(scena.scatto)
    verso.parent.mkdir(parents=True, exist_ok=True)
    os.symlink(scena.scatto.parent / "non_c_e.jpg", verso)
    spia = _Accoglie(scena, monkeypatch)
    errore = _fermato(lambda: coda.approva(scena.archivio, lavoro_id))
    assert str(errore).startswith("In «Originali» c'è già un file con lo stesso nome")
    assert _lavoro(scena, lavoro_id)["stato"] == coda.DA_RIVEDERE
    assert spia.chieste == [] and _ritoccata(scena) is None
    assert sorted(_in_attesa(scena)) == sorted([pronta, Path(ritocco["risultato"])])
    assert os.path.islink(verso)
