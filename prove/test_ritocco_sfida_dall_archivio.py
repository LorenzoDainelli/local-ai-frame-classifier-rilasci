from __future__ import annotations

import dataclasses
import io
import json
import os
from pathlib import Path

import numpy
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from officina.archivio import accesso
from officina.errori import ErroreOfficina
from officina.importazione import impronta
from officina.miglioria import attesa
from officina.ritocco import (coda, copia, elenco, in_chiaro, lavoro, pellicola, sfida_togli,
                              togliere)
from officina.sicuro.dall_archivio import (CHIUSO, SENZA_ARCHIVIO, SI_APRE,
                                           DallArchivio)
from officina.web import rivedi_ritocco
from officina.web.lavori import GUASTO_IMPREVISTO
from officina.web.miglioramento import MUTO
from officina.web.strade import ritocco as ritocco_web
from prove import test_ritocco_dall_archivio as di_prova
from prove.test_miglioria_coda_dall_archivio import FOTO
from prove.test_miglioria_dall_archivio import _mai_in_chiaro
from prove.test_miglioria_mostra_dall_archivio import _cerca, _legge
from prove.test_miglioria_scambio_dall_archivio import _Accoglie, _eventi
from prove.test_ritocco_dall_archivio import (ALTRA_ZONA, _estratta, _fermato, _in_attesa,
                                              _rimaste, _ritoccata, _storia)
from prove.test_ritocco_togli_coda import Togliere
from prove.test_ritocco_togli_dall_archivio import (_da_rivedere, _da_togliere, _del_lavoro,
                                                    _gira, _in_coda, _lavoro, _mosse,
                                                    _nell_archivio, _pronte, _relativo,
                                                    _PoiSiChiude, _ritocco,
                                                    _solo_la_toppa)
from prove.test_sicuro_dall_archivio import _impronta

pytest.importorskip("av")

costo_leggero = di_prova.costo_leggero
casa = di_prova.casa
cartella = di_prova.cartella
importato = di_prova.importato
solo_nell_archivio = di_prova.solo_nell_archivio
pronta = di_prova.pronta
scena = di_prova.scena

SECONDO = "finto-due"
PRIMA, DOPO, B = rivedi_ritocco.PRIMA, rivedi_ritocco.DOPO, rivedi_ritocco.B


class Diversi(Togliere):

    def __call__(self, lavoro_togli: dict, ricorda) -> dict:
        fatto = super().__call__(lavoro_togli, ricorda)
        if lavoro_togli["motore"] == SECONDO and "fatto" in fatto:
            uscita = Path(lavoro_togli["uscita"])
            with Image.open(uscita) as aperta:
                pixel = numpy.asarray(aperta.convert("RGB"), dtype=numpy.int16)
            pixel = numpy.clip(pixel + 6, 0, 255).astype(numpy.uint8)
            Image.fromarray(pixel, "RGB").save(uscita, "PNG")
        return fatto


@pytest.fixture
def in_due(scena, monkeypatch):
    monkeypatch.setitem(togliere.MOTORI, SECONDO, togliere.MOTORI[togliere.FINTO])
    scena.archivio.imposta(sfida_togli.SCELTI[sfida_togli.FOTO],
                           json.dumps([togliere.FINTO, SECONDO]))
    monkeypatch.setattr(sfida_togli, "sorteggia", lambda due, caso=None: {
        "motore_a": togliere.FINTO, "motore_b": SECONDO, "sinistra": "A"})
    return scena


def _sfida(scena, lavoro_id: int):
    with scena.archivio.lettura() as connessione:
        return sfida_togli.del_file(connessione, lavoro_id, scena.file_id)


def _toppa_b(riga, ritocco) -> Path:
    return Path(json.loads(riga["toppe_b"])[str(ritocco["id"])]["risultato"])


def _in_sfida(scena, togli=None):
    togli = togli or Diversi()
    lavoro_id = _in_coda(scena)
    _gira(scena, togli)
    assert _lavoro(scena, lavoro_id)["stato"] == coda.DA_RIVEDERE
    [pronta] = _pronte(scena, lavoro_id)
    [ritocco] = _del_lavoro(scena, lavoro_id)
    return lavoro_id, pronta, ritocco, _sfida(scena, lavoro_id), togli


def _quattro(pronta, ritocco, riga) -> dict[str, Path]:
    return {"pronta": pronta, "toppa_a": Path(ritocco["risultato"]),
            "pronta_b": Path(riga["pronta_b"]), "toppa_b": _toppa_b(riga, ritocco)}


def _cliente(scena, monkeypatch) -> TestClient:
    from officina.web.server import app

    monkeypatch.setattr(accesso, "aperto", lambda: scena.archivio)
    return TestClient(app, client=("127.0.0.1", 51000))


def _vota(cliente, lavoro_id: int, file_id: int, voto: str) -> dict:
    risposta = cliente.post(f"/api/ritocco/coda/{lavoro_id}/voto",
                            json={"file_id": file_id, "voto": voto})
    assert risposta.status_code == 200, risposta.text
    return risposta.json()


def test_la_sfida_si_fa_anche_con_lo_scatto_solo_nell_archivio(in_due, tmp_path):
    lavoro_id, pronta, ritocco, riga, togli = _in_sfida(in_due)
    assert sorted(chiesto["motore"] for chiesto in togli.lavori) == sorted(
        [togliere.FINTO, SECONDO])
    assert riga is not None and riga["voto"] is None and riga["genere"] == sfida_togli.FOTO
    file = _quattro(pronta, ritocco, riga)
    assert file["toppa_a"].name == copia.nome_della_toppa(ritocco["id"])
    assert file["toppa_b"] == file["toppa_a"].with_name(
        copia.della_b(copia.nome_della_toppa(ritocco["id"])))
    for percorso in file.values():
        assert attesa.e_dentro(percorso) and percorso.parent == pronta.parent, percorso
    assert file["pronta_b"].name.startswith(copia.PREFISSO)
    assert riga["impronta_b"] == impronta.del_file(file["pronta_b"])
    [toppa] = json.loads(riga["toppe_b"]).values()
    assert toppa["impronta_risultato"] == impronta.del_file(file["toppa_b"])
    assert impronta.del_file(file["pronta_b"]) != impronta.del_file(pronta)
    assert sorted(_in_attesa(in_due)) == sorted(file.values())
    errore = _fermato(lambda: coda.approva(in_due.archivio, lavoro_id))
    assert str(errore) == coda.PRIMA_VOTA
    assert _lavoro(in_due, lavoro_id)["stato"] == coda.DA_RIVEDERE
    assert _ritoccata(in_due) is None and _rimaste(in_due) == []
    assert not os.path.lexists(in_due.scatto)
    assert _storia(in_due, FOTO) == [(_impronta(in_due.dati[FOTO]), True)]
    _mai_in_chiaro(tmp_path, in_due.dati[FOTO])


@pytest.mark.parametrize("voto", ["A", "pari", "B"])
def test_votata_la_sfida_resta_la_scelta_e_al_si_va_nell_archivio(in_due, tmp_path,
                                                                  monkeypatch, voto):
    lavoro_id, pronta, ritocco, riga, _ = _in_sfida(in_due)
    file = _quattro(pronta, ritocco, riga)
    tenute = ((file["toppa_b"], file["pronta_b"]) if voto == "B"
              else (file["toppa_a"], file["pronta"]))
    sua_toppa, sua_pronta = impronta.del_file(tenute[0]), impronta.del_file(tenute[1])
    dati_toppa = tenute[0].read_bytes()
    cliente = _cliente(in_due, monkeypatch)
    detto = _vota(cliente, lavoro_id, in_due.file_id, voto)
    assert detto["fatto"] and detto["detto"] != ritocco_web.NESSUNA
    assert sorted(_in_attesa(in_due)) == sorted(tenute)
    dopo = _ritocco(in_due, ritocco["id"])
    assert dopo["risultato"] == str(tenute[0]) and dopo["impronta_risultato"] == sua_toppa
    assert _pronte(in_due, lavoro_id) == [tenute[1]]
    adesso = _sfida(in_due, lavoro_id)
    assert adesso["voto"] == voto and adesso["pronta_b"] is None
    assert _lavoro(in_due, lavoro_id)["stato"] == coda.DA_RIVEDERE
    assert in_due.casa.cestino.mosse == [] and _rimaste(in_due) == []

    coda.approva(in_due.archivio, lavoro_id)

    assert _lavoro(in_due, lavoro_id)["stato"] == coda.FATTO
    assert _in_attesa(in_due) == [] and _rimaste(in_due) == []
    assert _mosse(in_due) == list(tenute)
    fatto = _ritocco(in_due, ritocco["id"])
    verso = _nell_archivio(in_due, fatto)
    assert fatto["stato"] == elenco.FATTO and fatto["risultato"] == str(verso)
    assert _storia(in_due, _relativo(in_due, verso)) == [(sua_toppa, True)]
    ritoccata = _ritoccata(in_due)
    assert ritoccata["impronta_copia"] == sua_pronta and ritoccata["nell_archivio"] == 1
    assert not os.path.lexists(in_due.scatto)
    _mai_in_chiaro(tmp_path, in_due.dati[FOTO])
    estratti = _estratta(in_due, tmp_path)
    assert _impronta(estratti[f"foto/{FOTO}"]) == sua_pronta
    assert estratti[f"foto/{_relativo(in_due, verso)}"] == dati_toppa


def test_nessuna_delle_due_scarta_tutto_e_lo_scatto_resta(in_due, tmp_path, monkeypatch):
    lavoro_id, _, ritocco, _, _ = _in_sfida(in_due)
    cliente = _cliente(in_due, monkeypatch)
    detto = _vota(cliente, lavoro_id, in_due.file_id, "nessuna")
    assert detto["detto"] == ritocco_web.NESSUNA
    assert _lavoro(in_due, lavoro_id)["stato"] == coda.RIFIUTATO
    dopo = _ritocco(in_due, ritocco["id"])
    assert dopo["stato"] == elenco.RIFIUTATO and dopo["risultato"] is None
    assert _sfida(in_due, lavoro_id)["voto"] == "nessuna"
    assert _in_attesa(in_due) == [] and _rimaste(in_due) == []
    assert in_due.casa.cestino.mosse == [] and _ritoccata(in_due) is None
    assert _storia(in_due, FOTO) == [(_impronta(in_due.dati[FOTO]), True)]
    _mai_in_chiaro(tmp_path, in_due.dati[FOTO])


BUTTATE = {"A": ("pronta_b", "toppa_b"), "pari": ("pronta_b", "toppa_b"),
           "B": ("pronta", "toppa_a"),
           "nessuna": ("pronta", "toppa_a", "pronta_b", "toppa_b")}


@pytest.mark.parametrize("voto, quale", [(voto, quale) for voto in BUTTATE
                                         for quale in BUTTATE[voto]])
def test_un_file_che_non_si_cancella_al_voto_resta_segnato(in_due, monkeypatch, voto, quale):
    lavoro_id, pronta, ritocco, riga, _ = _in_sfida(in_due)
    file = _quattro(pronta, ritocco, riga)
    bloccato = file[quale]
    sua = impronta.del_file(bloccato)
    vera = sfida_togli.butta

    def butta(voci):
        if any(Path(voce[0]) == bloccato for voce in voci):
            raise PermissionError(13, "bloccato")
        vera(voci)

    monkeypatch.setattr(sfida_togli, "butta", butta)
    avvisi = _eventi(monkeypatch, "avviso")
    _vota(_cliente(in_due, monkeypatch), lavoro_id, in_due.file_id, voto)
    [rimasta] = _rimaste(in_due)
    assert rimasta["percorso"] == str(bloccato) and rimasta["file_id"] == in_due.file_id
    assert rimasta["impronta"] == sua and bloccato.is_file()
    assert "ritocco.pronta_non_tolta" in [nome for nome, _ in avvisi]
    for altro in BUTTATE[voto]:
        if altro != quale:
            assert not os.path.lexists(file[altro]), altro
    stato = coda.RIFIUTATO if voto == "nessuna" else coda.DA_RIVEDERE
    assert _lavoro(in_due, lavoro_id)["stato"] == stato
    monkeypatch.setattr(sfida_togli, "butta", vera)
    assert in_chiaro.butta_tutte(in_due.archivio) == 1
    assert _mosse(in_due) == [bloccato] and _rimaste(in_due) == []


def test_rifatto_dopo_la_b_il_nome_della_nuova_b_non_tocca_la_toppa_scelta(in_due,
                                                                          monkeypatch):
    lavoro_id, _, ritocco, _, togli = _in_sfida(in_due)
    cliente = _cliente(in_due, monkeypatch)
    _vota(cliente, lavoro_id, in_due.file_id, "B")
    scelta = Path(_ritocco(in_due, ritocco["id"])["risultato"])
    dati_scelta = scelta.read_bytes()
    assert scelta.name == copia.della_b(copia.nome_della_toppa(ritocco["id"]))
    assert coda.metti(in_due.archivio, [_da_togliere(in_due, ALTRA_ZONA)]) == lavoro_id
    _gira(in_due, togli)
    assert _lavoro(in_due, lavoro_id)["stato"] == coda.DA_RIVEDERE
    primo, secondo = _del_lavoro(in_due, lavoro_id)
    assert primo["id"] == ritocco["id"] and primo["risultato"] == str(scelta)
    assert scelta.read_bytes() == dati_scelta
    riga = _sfida(in_due, lavoro_id)
    assert riga["voto"] is None
    nuove = {chiave: Path(toppa["risultato"]).name
             for chiave, toppa in json.loads(riga["toppe_b"]).items()}
    assert nuove == {str(primo["id"]): f"togli-{primo['id']}-a1-b.png",
                     str(secondo["id"]): f"togli-{secondo['id']}-b.png"}
    _vota(cliente, lavoro_id, in_due.file_id, "A")
    assert scelta.read_bytes() == dati_scelta
    assert sorted(_in_attesa(in_due)) == sorted(
        [scelta, Path(secondo["risultato"]), *_pronte(in_due, lavoro_id)])
    coda.approva(in_due.archivio, lavoro_id)
    assert _lavoro(in_due, lavoro_id)["stato"] == coda.FATTO
    assert _in_attesa(in_due) == [] and _rimaste(in_due) == []
    verso = _nell_archivio(in_due, _ritocco(in_due, ritocco["id"]))
    assert _storia(in_due, _relativo(in_due, verso)) == [(_impronta(dati_scelta), True)]


def test_la_b_votata_non_butta_la_toppa_a_che_sta_nell_archivio(in_due, monkeypatch):
    lavoro_id, _, ritocco, _, togli = _in_sfida(in_due)
    with in_due.archivio.scrittura() as connessione:
        coda._butta(in_due.archivio, sfida_togli.vota(connessione, lavoro_id,
                                                      in_due.file_id, "A"))
    spia = _Accoglie(in_due, monkeypatch)
    _solo_la_toppa(spia, "muto")
    errore = _fermato(lambda: coda.approva(in_due.archivio, lavoro_id))
    assert str(errore) == copia.NON_PRESO
    spia.prima = spia.modo = None
    verso = _nell_archivio(in_due, ritocco)
    assert _ritocco(in_due, ritocco["id"])["risultato"] == str(verso)
    coda.metti(in_due.archivio, [_da_togliere(in_due, ALTRA_ZONA)])
    _gira(in_due, togli)
    riga = _sfida(in_due, lavoro_id)
    assert riga["voto"] is None and str(ritocco["id"]) in json.loads(riga["toppe_b"])
    assert _ritocco(in_due, ritocco["id"])["risultato"] == str(verso)
    verso.parent.mkdir(parents=True)
    verso.write_bytes(b"un altro")
    _vota(_cliente(in_due, monkeypatch), lavoro_id, in_due.file_id, "B")
    assert verso.read_bytes() == b"un altro"
    verso.unlink()
    verso.parent.rmdir()
    verso.parent.parent.rmdir()
    nuova = _ritocco(in_due, ritocco["id"])
    assert attesa.e_dentro(Path(nuova["risultato"])) and Path(nuova["risultato"]).is_file()
    coda.approva(in_due.archivio, lavoro_id)
    assert _lavoro(in_due, lavoro_id)["stato"] == coda.FATTO
    assert _in_attesa(in_due) == [] and _rimaste(in_due) == []
    assert _storia(in_due, _relativo(in_due, verso)) == [
        (ritocco["impronta_risultato"], True)]
    nuovo_verso = _nell_archivio(in_due, nuova)
    assert nuovo_verso != verso
    assert _storia(in_due, _relativo(in_due, nuovo_verso)) == [
        (nuova["impronta_risultato"], True)]


def test_al_voto_si_buttano_solo_i_file_di_lavoro_di_quel_ritocco(tmp_path):
    dove = tmp_path / "s" / attesa.NOME
    toppe = tmp_path / "s" / attesa.ORIGINALI / copia.CARTELLA
    voce = sfida_togli.DaButtare
    via = [voce(dove / f"{copia.PREFISSO}-1-mare.jpg"),
           voce(dove / f"{copia.PREFISSO}-1-mare-b.jpg", 1, "ab"),
           *(voce(toppe / nome, 1, "ab", 7)
             for nome in ("togli-7.png", "togli-7-b.png", "togli-7.mkv", "togli-7-b.mkv")),
           *(voce(dove / nome, 1, "ab", 7) for nome in (
               "togli-7.png", "togli-7-b.png", "togli-7-a2.png", "togli-7-a2-b.png"))]
    restano = [voce(tmp_path / f"{copia.PREFISSO}-1-mare.jpg"),
               voce(dove / "mare.jpg"),
               voce(dove / "togli-9.png"),
               voce(toppe / "togli-9.png"),
               voce(dove / "togli-8.png", 1, "ab", 7),
               voce(toppe / "togli-8-b.png", 1, "ab", 7),
               voce(toppe / "togli-7-0123456789ab.png", 1, "ab", 7),
               voce(toppe.parent / "togli-7.png", 1, "ab", 7),
               voce(tmp_path / "togli-7-b.png", 1, "ab", 7),
               voce(dove / "togli-7-ax-b.png", 1, "ab", 7),
               voce(dove / "togli-7-a²-b.png", 1, "ab", 7),
               voce(dove / f"{copia.PREFISSO}-togli-7.png", 1, "ab", 8)]
    for una in via + restano:
        Path(una.percorso).parent.mkdir(parents=True, exist_ok=True)
        Path(una.percorso).write_bytes(b"x")
    cartella = voce(toppe / "togli-5.png", 1, "ab", 5)
    Path(cartella.percorso).mkdir()
    assert [sfida_togli.si_butta(una) for una in via] == [True] * len(via)
    assert [sfida_togli.si_butta(una) for una in restano] == [False] * len(restano)
    sfida_togli.butta([via[0].percorso, tuple(via[1]), *via[2:], *restano, cartella])
    assert [os.path.lexists(una.percorso) for una in via] == [False] * len(via)
    assert all(Path(una.percorso).is_file() for una in restano)
    assert Path(cartella.percorso).is_dir()


def test_il_nome_della_toppa_in_attesa_salta_i_risultati_dei_ritocchi(scena):
    _, _, ritocco, _ = _da_rivedere(scena)
    toppa = Path(ritocco["risultato"])
    dove, numero = toppa.parent, ritocco["id"]
    with scena.archivio.lettura() as connessione:
        assert copia.toppa_in_attesa(connessione, dove, numero) == toppa
        assert copia.toppa_in_attesa(connessione, dove, numero, True) == dove / (
            f"togli-{numero}-b.png")
        assert copia.toppa_in_attesa(connessione, dove, numero + 1) == dove / (
            f"togli-{numero + 1}.png")
    with scena.archivio.scrittura() as connessione:
        connessione.execute("UPDATE ritocchi SET risultato = ? WHERE id = ?",
                            (str(dove / f"togli-{numero}-b.png"), numero))
    with scena.archivio.lettura() as connessione:
        assert copia.toppa_in_attesa(connessione, dove, numero) == toppa
        assert copia.toppa_in_attesa(connessione, dove, numero, True) == dove / (
            f"togli-{numero}-a1-b.png")
    with scena.archivio.scrittura() as connessione:
        connessione.execute("UPDATE ritocchi SET risultato = ? WHERE id = ?",
                            (str(dove / f"togli-{numero + 1}.png"), numero))
    with scena.archivio.lettura() as connessione:
        assert copia.toppa_in_attesa(connessione, dove, numero) == toppa
        assert copia.toppa_in_attesa(connessione, dove, numero + 1) == dove / (
            f"togli-{numero + 1}-a1.png")
        assert copia.toppa_in_attesa(connessione, dove, numero + 1, True) == dove / (
            f"togli-{numero + 1}-b.png")


class _RottaLaSecondaB(Diversi):

    def __call__(self, lavoro_togli: dict, ricorda) -> dict:
        uscite = {Path(chiesto["uscita"]).name for chiesto in self.lavori}
        uscita = Path(lavoro_togli["uscita"]).name
        if uscita.endswith("-b.png") and any(nome.endswith("-b.png") and nome != uscita
                                             for nome in uscite):
            self.lavori.append(lavoro_togli)
            return {"guasto": "togli_motore_sconosciuto"}
        return super().__call__(lavoro_togli, ricorda)


def _fallito_senza_resti(scena, lavoro_id: int, guasto: str | None = None) -> None:
    adesso = _lavoro(scena, lavoro_id)
    assert adesso["stato"] == coda.FALLITO, adesso["guasto"]
    if guasto is not None:
        assert adesso["guasto"] == guasto
    assert _in_attesa(scena) == [] and _rimaste(scena) == []
    assert _sfida(scena, lavoro_id) is None
    for ritocco in _del_lavoro(scena, lavoro_id):
        assert ritocco["risultato"] is None, dict(ritocco)
    assert not os.path.lexists(scena.scatto)


def test_se_la_b_non_riesce_a_meta_le_sue_toppe_se_ne_vanno(in_due):
    lavoro_id = coda.metti(in_due.archivio, [_da_togliere(in_due),
                                             _da_togliere(in_due, ALTRA_ZONA)])
    togli = _RottaLaSecondaB()
    _gira(in_due, togli)
    fatte_b = [Path(chiesto["uscita"]) for chiesto in togli.lavori
               if chiesto["uscita"].endswith("-b.png")]
    assert len({percorso.name for percorso in fatte_b}) == 2
    _fallito_senza_resti(in_due, lavoro_id)


def test_se_la_copia_b_non_si_prepara_non_resta_niente(in_due, monkeypatch):
    vera = copia.prepara_per_la_coda

    def prepara(*argomenti, **piu):
        if piu.get("variante") == "b":
            raise copia.RitoccoFermato(copia.ROVINATA)
        return vera(*argomenti, **piu)

    monkeypatch.setattr(copia, "prepara_per_la_coda", prepara)
    lavoro_id = _in_coda(in_due)
    togli = Diversi()
    _gira(in_due, togli)
    assert {chiesto["uscita"].endswith("-b.png")
            for chiesto in togli.lavori} == {False, True}
    _fallito_senza_resti(in_due, lavoro_id, copia.ROVINATA)


@pytest.mark.parametrize("lato", ["a", "b"])
def test_se_il_ricontrollo_si_rompe_la_toppa_appena_fatta_se_ne_va(in_due, monkeypatch,
                                                                    lato):
    togli = Diversi()
    vero = lavoro.ricontrollo.controlla

    def controlla(*argomenti, **piu):
        if Path(togli.lavori[-1]["uscita"]).name.endswith("-b.png") == (lato == "b"):
            raise RuntimeError("rotto")
        return vero(*argomenti, **piu)

    monkeypatch.setattr(lavoro.ricontrollo, "controlla", controlla)
    lavoro_id = _in_coda(in_due)
    _gira(in_due, togli)
    assert os.path.basename(togli.lavori[-1]["uscita"]).endswith("-b.png") == (lato == "b")
    _fallito_senza_resti(in_due, lavoro_id, GUASTO_IMPREVISTO)


def test_la_revisione_prende_com_era_dall_archivio(scena):
    lavoro_id, pronta, _, _ = _da_rivedere(scena)
    scelta = rivedi_ritocco.da_rivedere(scena.archivio, lavoro_id, None)
    assert scelta["ci_sono"] and scelta["dall_archivio"] and scelta["archivio"] is None
    assert scelta["nome"] == Path(FOTO).name and scelta["sfida"] is None
    genere, prima = rivedi_ritocco.file_del_lato(scena.archivio, lavoro_id, scena.file_id,
                                                 PRIMA)
    assert genere == "immagine" and isinstance(prima, DallArchivio) and not prima.diversa
    assert _legge(prima) == scena.dati[FOTO]
    assert rivedi_ritocco.file_del_lato(scena.archivio, lavoro_id, scena.file_id,
                                        DOPO) == ("immagine", pronta)
    assert rivedi_ritocco.file_del_lato(scena.archivio, lavoro_id, scena.file_id, B) is None


def test_dalla_pagina_com_era_arriva_dall_archivio_a_pezzi(scena, monkeypatch):
    lavoro_id, pronta, _, _ = _da_rivedere(scena)
    cliente = _cliente(scena, monkeypatch)
    pagina = cliente.get(f"/ritocco/rivedi?lavoro={lavoro_id}")
    assert pagina.status_code == 200, pagina.text
    assert "archivio-chiuso" not in pagina.text and "Uno dei due file" not in pagina.text
    assert pagina.text.count("data-prima") == 2
    indirizzo = f"/ritocco/{lavoro_id}/mostra/{scena.file_id}"
    intera = cliente.get(f"{indirizzo}/prima")
    assert intera.status_code == 200 and intera.content == scena.dati[FOTO]
    assert intera.headers["cache-control"] == "no-store"
    assert intera.headers["content-type"] == "image/jpeg"
    pezzo = cliente.get(f"{indirizzo}/prima", headers={"Range": "bytes=2-9"})
    assert pezzo.status_code == 206 and pezzo.content == scena.dati[FOTO][2:10]
    dopo = cliente.get(f"{indirizzo}/dopo")
    assert dopo.status_code == 200 and dopo.content == pronta.read_bytes()


def test_com_era_in_un_formato_strano_arriva_ricodificata(scena, monkeypatch, tmp_path):
    from officina.web.strade import ritocco_pagina

    lavoro_id, _, _, _ = _da_rivedere(scena)
    cliente = _cliente(scena, monkeypatch)
    monkeypatch.setattr(ritocco_pagina, "FORMATI_CHE_SI_APRONO", {})
    risposta = cliente.get(f"/ritocco/{lavoro_id}/mostra/{scena.file_id}/prima")
    assert risposta.status_code == 200
    assert risposta.headers["cache-control"] == "no-store"
    assert risposta.headers["content-type"] == "image/jpeg"
    assert risposta.content != scena.dati[FOTO]
    assert Image.open(io.BytesIO(risposta.content)).size == Image.open(
        io.BytesIO(scena.dati[FOTO])).size
    _mai_in_chiaro(tmp_path, scena.dati[FOTO])


@pytest.mark.parametrize("perche, cosa", [(CHIUSO, "archivio-chiuso"),
                                          (SI_APRE, "archivio-si-apre")])
def test_con_l_archivio_chiuso_la_revisione_lo_dice(scena, monkeypatch, perche, cosa):
    lavoro_id, _, _, _ = _da_rivedere(scena)
    cliente = _cliente(scena, monkeypatch)
    scena.situazione.forzata = perche
    scelta = rivedi_ritocco.da_rivedere(scena.archivio, lavoro_id, None)
    assert scelta["archivio"] == perche and not scelta["ci_sono"]
    assert not scelta["dall_archivio"] and scelta["nome"] == Path(FOTO).name
    assert rivedi_ritocco.file_del_lato(scena.archivio, lavoro_id, scena.file_id,
                                        PRIMA) is None
    pagina = cliente.get(f"/ritocco/rivedi?lavoro={lavoro_id}")
    assert pagina.status_code == 200, pagina.text
    assert f'id="{cosa}"' in pagina.text and "Uno dei due file" not in pagina.text
    if perche == CHIUSO:
        assert "La foto c'è solo nell'Archivio sicuro" in pagina.text
        assert 'id="modulo-archivio-sicuro"' in pagina.text
    else:
        assert "La foto arriva da sola fra poco." in pagina.text
    mostra = cliente.get(f"/ritocco/{lavoro_id}/mostra/{scena.file_id}/prima")
    assert mostra.status_code == 404


def test_se_l_archivio_non_risponde_la_revisione_dice_muto(scena, monkeypatch):
    lavoro_id, _, _, _ = _da_rivedere(scena)
    cliente = _cliente(scena, monkeypatch)

    def muto(sua, trovata):
        raise ErroreOfficina("non risponde", codice="occupato")

    _cerca(scena, monkeypatch, muto)
    scelta = rivedi_ritocco.da_rivedere(scena.archivio, lavoro_id, None)
    assert scelta["archivio"] == MUTO and not scelta["ci_sono"]
    pagina = cliente.get(f"/ritocco/rivedi?lavoro={lavoro_id}")
    assert 'id="archivio-muto"' in pagina.text and "Uno dei due file" not in pagina.text


def test_una_versione_diversa_nell_archivio_non_fa_da_com_era(scena, monkeypatch):
    lavoro_id, _, _, _ = _da_rivedere(scena)
    cliente = _cliente(scena, monkeypatch)
    _cerca(scena, monkeypatch, lambda sua, trovata: dataclasses.replace(
        trovata, trovata=dataclasses.replace(trovata.trovata, diversa=True)))
    scelta = rivedi_ritocco.da_rivedere(scena.archivio, lavoro_id, None)
    assert scelta["archivio"] is None and not scelta["ci_sono"]
    assert not scelta["dall_archivio"]
    pagina = cliente.get(f"/ritocco/rivedi?lavoro={lavoro_id}")
    assert "Uno dei due file" in pagina.text and "archivio-chiuso" not in pagina.text


def test_la_sfida_dalla_pagina_mostra_com_era_dall_archivio(in_due, monkeypatch):
    lavoro_id, pronta, _, riga, _ = _in_sfida(in_due)
    cliente = _cliente(in_due, monkeypatch)
    pagina = cliente.get(f"/ritocco/rivedi?lavoro={lavoro_id}")
    assert pagina.status_code == 200, pagina.text
    assert "rivedi-tre" in pagina.text and 'data-vota="nessuna"' in pagina.text
    assert pagina.text.count("data-prima") == 1
    indirizzo = f"/ritocco/{lavoro_id}/mostra/{in_due.file_id}"
    attese = {"prima": in_due.dati[FOTO], "dopo": pronta.read_bytes(),
              "b": Path(riga["pronta_b"]).read_bytes()}
    for lato, dati in attese.items():
        risposta = cliente.get(f"{indirizzo}/{lato}")
        assert risposta.status_code == 200 and risposta.content == dati, lato
    for lato in ("sinistra", "destra"):
        assert f'data-vota="{riga[lato] if lato == "sinistra" else "B"}">' in pagina.text
    assert 'data-vota="pari">' in pagina.text
    in_due.situazione.forzata = CHIUSO
    pagina = cliente.get(f"/ritocco/rivedi?lavoro={lavoro_id}")
    assert 'id="archivio-chiuso"' in pagina.text and "rivedi-tre" not in pagina.text
    for voto in ("A", "B", "pari"):
        assert f'data-vota="{voto}" disabled>' in pagina.text, voto
    assert 'data-vota="nessuna">' in pagina.text


def test_con_la_foto_ritoccata_nell_archivio_com_era_e_quella(scena, tmp_path, monkeypatch):
    lavoro_id, _, _, togli = _da_rivedere(scena)
    coda.approva(scena.archivio, lavoro_id)
    ritoccata = _estratta(scena, tmp_path)[f"foto/{FOTO}"]
    secondo = coda.metti(scena.archivio, [_da_togliere(scena, ALTRA_ZONA)])
    _gira(scena, togli)
    genere, prima = rivedi_ritocco.file_del_lato(scena.archivio, secondo, scena.file_id,
                                                 PRIMA)
    assert genere == "immagine" and isinstance(prima, DallArchivio)
    assert _legge(prima) == ritoccata and ritoccata != scena.dati[FOTO]


def test_senza_copia_pronta_il_dopo_e_lo_scatto_senza_ritocchi_dall_archivio(
        scena, tmp_path, monkeypatch):
    lavoro_id, _, _, _ = _da_rivedere(scena)
    coda.approva(scena.archivio, lavoro_id)
    ritoccata = _estratta(scena, tmp_path)[f"foto/{FOTO}"]
    pronto = {"pronta": None, "lavoro_id": lavoro_id}

    def lati():
        with scena.archivio.lettura() as connessione:
            return rivedi_ritocco._prima_e_dopo(connessione, scena.file_id, pronto, True)

    adesso, perche = lati()
    assert perche is None and isinstance(adesso[DOPO], DallArchivio)
    assert _legge(adesso[PRIMA]) == ritoccata and _legge(adesso[DOPO]) == scena.dati[FOTO]
    for forzata in (CHIUSO, SI_APRE):
        scena.situazione.forzata = forzata
        assert lati() == ({PRIMA: None, DOPO: None}, forzata)
    scena.situazione.forzata = None
    sua = _impronta(scena.dati[FOTO])

    def muto_sotto(chiesta, trovata):
        if chiesta == sua:
            raise ErroreOfficina("non risponde", codice="occupato")
        return trovata

    _cerca(scena, monkeypatch, muto_sotto)
    adesso, perche = lati()
    assert perche == MUTO and adesso[DOPO] is None
    assert _legge(adesso[PRIMA]) == ritoccata


def test_senza_archivio_la_revisione_dice_che_manca_un_file(scena, monkeypatch):
    lavoro_id, _, _, _ = _da_rivedere(scena)
    cliente = _cliente(scena, monkeypatch)
    scena.situazione.forzata = SENZA_ARCHIVIO
    scelta = rivedi_ritocco.da_rivedere(scena.archivio, lavoro_id, None)
    assert scelta["archivio"] is None and not scelta["ci_sono"]
    pagina = cliente.get(f"/ritocco/rivedi?lavoro={lavoro_id}")
    assert "Uno dei due file" in pagina.text and 'id="archivio-' not in pagina.text


def test_se_l_archivio_si_chiude_durante_la_sfida_la_toppa_a_resta(in_due):
    lavoro_id = _in_coda(in_due)
    _gira(in_due, _PoiSiChiude(in_due))
    adesso = _lavoro(in_due, lavoro_id)
    assert adesso["stato"] == coda.IN_CODA and adesso["guasto"] == lavoro.ASPETTA
    [ritocco] = _del_lavoro(in_due, lavoro_id)
    toppa = Path(ritocco["risultato"])
    assert copia.toppa_pronta(ritocco) and _in_attesa(in_due) == [toppa]
    assert _sfida(in_due, lavoro_id) is None and _rimaste(in_due) == []
    in_due.situazione.forzata = None
    togli = Diversi()
    _gira(in_due, togli)
    assert [chiesto["motore"] for chiesto in togli.lavori] == [SECONDO]
    assert _lavoro(in_due, lavoro_id)["stato"] == coda.DA_RIVEDERE
    riga = _sfida(in_due, lavoro_id)
    [pronta] = _pronte(in_due, lavoro_id)
    file = _quattro(pronta, _ritocco(in_due, ritocco["id"]), riga)
    assert file["toppa_a"] == toppa and sorted(_in_attesa(in_due)) == sorted(file.values())


def test_se_la_copia_b_non_si_prepara_e_la_a_non_si_cancella_resta_segnata(in_due,
                                                                          monkeypatch):
    vera, vero_butta = copia.prepara_per_la_coda, copia.butta
    fatte: list[Path] = []

    def prepara(*argomenti, **piu):
        if piu.get("variante") == "b":
            raise copia.RitoccoFermato(copia.ROVINATA)
        fatte.append(vera(*argomenti, **piu))
        return fatte[-1]

    def butta(percorso):
        if percorso in fatte:
            raise PermissionError(13, "bloccato")
        vero_butta(percorso)

    monkeypatch.setattr(copia, "prepara_per_la_coda", prepara)
    monkeypatch.setattr(copia, "butta", butta)
    lavoro_id = _in_coda(in_due)
    _gira(in_due, Diversi())
    assert _lavoro(in_due, lavoro_id)["stato"] == coda.FALLITO
    [pronta] = fatte
    [rimasta] = _rimaste(in_due)
    assert rimasta["percorso"] == str(pronta) and rimasta["file_id"] == in_due.file_id
    assert rimasta["impronta"] == impronta.del_file(pronta)
    assert _in_attesa(in_due) == [pronta]


def _resti_della_sfida(fatto: dict) -> list[Path]:
    b = sfida_togli.file_della_b(fatto["sfida"], fatto["file_id"])
    resti = [Path(fatto["pronta"]), *(Path(voce.percorso) for voce in b)]
    assert len(resti) == 3 and all(percorso.is_file() for percorso in resti)
    return resti


@pytest.mark.parametrize("come", ["rotto", "fermato"])
def test_se_il_lavoro_si_rompe_dopo_la_sfida_le_copie_se_ne_vanno(in_due, monkeypatch,
                                                                  come):
    vero_un_file, vere = lavoro.Ritoccatore._un_file, coda.file_coinvolti
    resti: list[Path] = []

    def un_file(ritoccatore, lavoro_id, file_id):
        if resti:
            if come == "fermato":
                ritoccatore._fermati.set()
                raise pellicola.Fermato()
            raise RuntimeError("rotto")
        fatto = vero_un_file(ritoccatore, lavoro_id, file_id)
        resti.extend(_resti_della_sfida(fatto))
        return fatto

    monkeypatch.setattr(lavoro.Ritoccatore, "_un_file", un_file)
    monkeypatch.setattr(coda, "file_coinvolti", lambda *dati: vere(*dati) * 2)
    lavoro_id = _in_coda(in_due)
    _gira(in_due, Diversi())
    stato = coda.FALLITO if come == "rotto" else coda.IN_CODA
    assert resti and _lavoro(in_due, lavoro_id)["stato"] == stato
    assert not any(os.path.lexists(percorso) for percorso in resti)
    assert _sfida(in_due, lavoro_id) is None and _rimaste(in_due) == []
    assert _pronte(in_due, lavoro_id) == []


def test_se_i_ritocchi_cambiano_mentre_lavora_le_copie_della_sfida_se_ne_vanno(
        in_due, monkeypatch):
    vero_un_file = lavoro.Ritoccatore._un_file
    resti: list[Path] = []

    def un_file(ritoccatore, lavoro_id, file_id):
        fatto = vero_un_file(ritoccatore, lavoro_id, file_id)
        resti.extend(_resti_della_sfida(fatto))
        with in_due.archivio.scrittura() as connessione:
            coda.cambiato(connessione, lavoro_id)
        ritoccatore._fermati.set()
        return fatto

    monkeypatch.setattr(lavoro.Ritoccatore, "_un_file", un_file)
    lavoro_id = _in_coda(in_due)
    _gira(in_due, Diversi())
    assert resti and _lavoro(in_due, lavoro_id)["stato"] == coda.IN_CODA
    assert not any(os.path.lexists(percorso) for percorso in resti)
    assert _sfida(in_due, lavoro_id) is None and _rimaste(in_due) == []
    assert _pronte(in_due, lavoro_id) == []
