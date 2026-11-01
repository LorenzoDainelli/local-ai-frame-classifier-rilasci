from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from officina import registro
from officina.archivio.database import tutti
from officina.importazione import impronta
from officina.importazione.motore import Motore
from officina.miglioria import attesa
from officina.modello import file_media
from officina.ritocco import coda, copia, elenco, in_chiaro, rimaste, sfida_togli, togliere
from officina.ritocco.copia import RitoccoFermato
from officina.web import coda_ritocco
from prove.test_ritocco import ZONA_A, _file_di, _jpeg, _ritoccata, _volto
from prove.test_ritocco_togli_coda import Togliere, _da_togliere, _gira, _scena

SECONDO = "finto-due"
VERO_UNLINK = Path.unlink


@pytest.fixture
def cartella(tmp_path) -> Path:
    dove = tmp_path / "foto"
    _jpeg(dove / "2016" / "piccola.jpg")
    _scena(dove / "2019" / "gita.png")
    return dove


@pytest.fixture
def importato(archivio, cartella):
    motore = Motore(archivio)
    motore.prepara([cartella])
    motore.esegui()
    return archivio


@pytest.fixture
def con_due(importato, monkeypatch):
    monkeypatch.setitem(togliere.MOTORI, SECONDO, togliere.MOTORI[togliere.FINTO])
    importato.imposta(sfida_togli.SCELTI[sfida_togli.FOTO],
                      json.dumps([togliere.FINTO, SECONDO]))
    return importato


def _sentiti(monkeypatch, quale: str = "avviso") -> list:
    visti: list = []
    monkeypatch.setattr(registro, quale, lambda nome, **campi: visti.append((nome, campi)))
    return visti


def _bloccata(pronta):
    raise PermissionError(13, "la usa un altro programma")


def _non_si_toglie(monkeypatch, *bloccati: Path) -> None:
    def unlink(percorso, *altro, **campi):
        if percorso in bloccati:
            raise PermissionError(13, f"bloccata {percorso.name}")
        return VERO_UNLINK(percorso, *altro, **campi)

    monkeypatch.setattr(Path, "unlink", unlink)


def _in_attesa(cartella: Path) -> Path:
    dove = cartella / attesa.NOME
    dove.mkdir(parents=True, exist_ok=True)
    return dove


def _scrivi(*file: Path) -> None:
    for percorso in file:
        percorso.parent.mkdir(parents=True, exist_ok=True)
        percorso.write_bytes(percorso.name.encode())


def _gita(archivio) -> int:
    return _file_di(archivio, "gita.png")


def _in_sfida(archivio) -> tuple[int, int]:
    file_id = _gita(archivio)
    lavoro_id = coda.metti(archivio, [{"file_id": file_id, **_da_togliere()}])
    _gira(archivio, Togliere())
    return lavoro_id, file_id


def _sfida(archivio, lavoro_id: int, file_id: int) -> dict | None:
    with archivio.lettura() as connessione:
        riga = sfida_togli.del_file(connessione, lavoro_id, file_id)
    return None if riga is None else dict(riga)


def _il_togli(archivio, file_id: int):
    with archivio.lettura() as connessione:
        [ritocco] = tutti(connessione, "SELECT * FROM ritocchi WHERE file_id = ? "
                          "AND genere = ?", file_id, elenco.TOGLI)
    return ritocco


def _stato(archivio, lavoro_id: int) -> str:
    with archivio.lettura() as connessione:
        return coda.per_id(connessione, lavoro_id)["stato"]


def test_una_copia_in_preparazione_che_non_si_cancella_non_ferma_il_ritocco(importato,
                                                                           monkeypatch):
    file_id = _file_di(importato, "piccola.jpg")
    avvisi = _sentiti(monkeypatch)
    monkeypatch.setattr(copia, "butta", _bloccata)
    copia.metti(importato, file_id, [_volto(ZONA_A)])
    assert _ritoccata(importato, file_id)["stato"] == copia.FATTA
    assert [(nome, campi["file"]) for nome, campi in avvisi] == [
        ("ritocco.copia_non_tolta", file_id)]


def test_se_la_migliorata_sparisce_dal_disco_non_si_ritocca_l_originale(importato,
                                                                         cartella):
    pytest.importorskip("av")
    from officina.miglioria import coda as coda_miglioria
    from officina.miglioria import lavoro as lavoro_miglioria
    from officina.miglioria import scambio

    scatto = cartella / "2016" / "piccola.jpg"
    file_id = _file_di(importato, "piccola.jpg")
    with importato.scrittura() as connessione:
        scatto_id = file_media.per_id(connessione, file_id)["scatto_id"]
        assert coda_miglioria.metti(connessione, [scatto_id]).messi == 1
    miglioratore = lavoro_miglioria.Miglioratore(importato, motori_scelti={
        "foto": "finto", "video": "finto", "volti": None})
    assert miglioratore.parti() and miglioratore.lavoro.aspetta_che_finisca(120)
    with importato.lettura() as connessione:
        [migliorata] = coda_miglioria.in_stato(connessione, coda_miglioria.DA_RIVEDERE)
    scambio.approva(importato, migliorata["id"])
    with importato.lettura() as connessione:
        migliorata = coda_miglioria.per_id(connessione, migliorata["id"])
    assert migliorata["percorso_migliorata"] == str(scatto)
    originale = cartella / "2016" / attesa.ORIGINALI / "piccola.jpg"
    segno = impronta.del_file(originale)
    scatto.unlink()
    prima = sorted(cartella.rglob("*"))

    for prova in (lambda: copia.metti(importato, file_id, [_volto(ZONA_A)]),
                  lambda: copia.partenza(importato, file_id, True)):
        with pytest.raises(RitoccoFermato) as fermo:
            prova()
        assert fermo.value.messaggio == copia.MIGLIORATA_SPARITA
    with pytest.raises(RitoccoFermato) as fermo:
        copia.partenza(importato, file_id)
    assert fermo.value.messaggio == copia.NON_SUL_DISCO
    with importato.lettura() as connessione:
        assert copia.base_di_adesso(connessione, file_id) is None
        assert copia.base_per_la_coda(connessione, file_id) == (
            "piccola.jpg", migliorata["impronta_migliorata"])
    assert _ritoccata(importato, file_id) is None
    assert impronta.del_file(originale) == segno
    assert sorted(cartella.rglob("*")) == prima


@pytest.mark.parametrize("dove, nome, si", [
    (copia.CARTELLA, "togli-5.png", True),
    (copia.CARTELLA, "togli-5-b.png", True),
    (copia.CARTELLA, "togli-5.mkv", True),
    (copia.CARTELLA, "togli-5-b.mkv", True),
    (copia.CARTELLA, "togli-5-a1.png", True),
    (copia.CARTELLA, "togli-5-a1-b.png", True),
    (copia.CARTELLA, "togli-5-a1234-b.mkv", True),
    (copia.CARTELLA, "togli-5-a12345.png", False),
    (copia.CARTELLA, "togli-5-a12345678901.png", False),
    (copia.CARTELLA, "togli-5-0123456789ab.png", False),
    (copia.CARTELLA, "togli-5-a.png", False),
    (copia.CARTELLA, "togli-5-a١.png", False),
    (copia.CARTELLA, "togli-5-a²-b.png", False),
    (copia.CARTELLA, "togli-5-b-b.png", False),
    (copia.CARTELLA, "togli-5-c.png", False),
    (copia.CARTELLA, "togli-55.png", False),
    (copia.CARTELLA, "togli-6.png", False),
    (copia.CARTELLA, "togli-5.jpg", False),
    (copia.CARTELLA, "togli-5.png.parziale", False),
    (copia.CARTELLA, "togli-5", False),
    (copia.CARTELLA, "xtogli-5.png", False),
    (attesa.NOME, "togli-5.png", True),
    (attesa.NOME, "togli-5-a3-b.mkv", True),
    (attesa.NOME, "togli-5-a12345678901.png", False),
    ("2016", "togli-5.png", False),
    (attesa.ORIGINALI, "togli-5-b.png", False),
])
def test_si_riconoscono_solo_le_toppe_di_quel_ritocco(tmp_path, dove, nome, si):
    assert copia._e_una_toppa(tmp_path / dove / nome, 5) is si


@pytest.mark.parametrize("dove, nome, ritocco_id, si", [
    (attesa.NOME, "ritocco-3-piccola.jpg", None, True),
    (attesa.NOME, "togli-3.png", None, False),
    ("2016", "ritocco-3-piccola.jpg", None, False),
    (attesa.NOME, "togli-3-b.png", 3, True),
    (copia.CARTELLA, "togli-3-a2.mkv", 3, True),
    (copia.CARTELLA, "togli-4.png", 3, False),
])
def test_la_sfida_butta_solo_le_sue_copie(tmp_path, dove, nome, ritocco_id, si):
    voce = sfida_togli.DaButtare(tmp_path / dove / nome, 1, "x", ritocco_id)
    assert sfida_togli.si_butta(voce) is si


def test_un_no_butta_anche_le_toppe_b_e_dei_video_messe_da_parte(tmp_path):
    toppe = tmp_path / "2019" / attesa.ORIGINALI / copia.CARTELLA
    via = ["togli-5-b.png", "togli-5.mkv", "togli-5-a2-b.mkv"]
    restano = ["togli-5-0123456789ab.png", "togli-6.png"]
    _scrivi(*(toppe / nome for nome in via + restano + ["togli-5.png"]))
    righe = [{"genere": elenco.TOGLI, "risultato": str(toppe / nome), "id": 5, "file_id": 1,
              "impronta_risultato": None} for nome in via + restano]
    righe.append({"genere": elenco.PIXELA, "risultato": str(toppe / "togli-5.png"), "id": 5,
                  "file_id": 1, "impronta_risultato": None})
    copia.butta_le_toppe(righe)
    assert sorted(file.name for file in toppe.iterdir()) == sorted(restano + ["togli-5.png"])


def test_un_no_sul_disco_butta_la_toppa_a_e_la_b(con_due, cartella):
    lavoro_id, file_id = _in_sfida(con_due)
    ritocco = _il_togli(con_due, file_id)
    toppe = cartella / "2019" / attesa.ORIGINALI / copia.CARTELLA
    assert sorted(file.name for file in toppe.iterdir()) == [
        f"togli-{ritocco['id']}-b.png", f"togli-{ritocco['id']}.png"]
    coda.rifiuta(con_due, lavoro_id)
    assert not toppe.exists() or list(toppe.iterdir()) == []
    assert _sfida(con_due, lavoro_id, file_id) is None


def test_il_nome_di_una_toppa_nuova_non_copre_quella_scelta(con_due):
    lavoro_id, file_id = _in_sfida(con_due)
    with con_due.scrittura() as connessione:
        sfida_togli.butta(sfida_togli.vota(connessione, lavoro_id, file_id, "B"))
    ritocco = _il_togli(con_due, file_id)
    scelta, numero = Path(ritocco["risultato"]), ritocco["id"]
    assert scelta.name == f"togli-{numero}-b.png" and scelta.is_file()
    dove = scelta.parent
    with con_due.lettura() as connessione:
        a = copia.toppa_in_attesa(connessione, dove, numero)
        b = copia.toppa_in_attesa(connessione, dove, numero, lato_b=True)
        video = copia.toppa_in_attesa(connessione, dove, numero, True, True)
        solo_video = copia.toppa_in_attesa(connessione, dove, numero, video=True)
    assert a == dove / f"togli-{numero}.png"
    assert b == dove / f"togli-{numero}-a1-b.png"
    assert video == dove / f"togli-{numero}-b.mkv"
    assert solo_video == dove / f"togli-{numero}.mkv"
    with con_due.scrittura() as connessione:
        in_chiaro.segna(connessione, file_id, b, "x")
        in_chiaro.segna(connessione, file_id, a, "y")
    with con_due.lettura() as connessione:
        assert copia.toppa_in_attesa(connessione, dove, numero, lato_b=True) == \
            dove / f"togli-{numero}-a2-b.png"
        assert copia.toppa_in_attesa(connessione, dove, numero) == \
            dove / f"togli-{numero}-a1.png"


def test_il_nome_di_una_toppa_nuova_non_copre_un_file_che_c_e_gia(con_due, tmp_path):
    _, file_id = _in_sfida(con_due)
    numero = _il_togli(con_due, file_id)["id"]
    dove, vuota = tmp_path / "altrove" / copia.CARTELLA, tmp_path / "vuota"
    estraneo = dove / f"togli-{numero}.png"
    _scrivi(estraneo, dove / f"togli-{numero}-b.mkv")
    with con_due.lettura() as connessione:
        assert copia.toppa_in_attesa(connessione, dove, numero) == \
            dove / f"togli-{numero}-a1.png"
        assert copia.toppa_in_attesa(connessione, dove, numero, True, True) == \
            dove / f"togli-{numero}-a1-b.mkv"
        assert copia.toppa_in_attesa(connessione, dove, numero, True) == \
            dove / f"togli-{numero}-b.png"
        assert copia.toppa_in_attesa(connessione, dove, numero + 1) == \
            dove / f"togli-{numero + 1}.png"
    with con_due.scrittura() as connessione:
        connessione.execute("UPDATE ritocchi SET risultato = ? WHERE id = ?",
                            (str(estraneo), numero))
    with con_due.lettura() as connessione:
        assert copia.toppa_in_attesa(connessione, dove, numero) == estraneo
    with con_due.scrittura() as connessione:
        connessione.execute("UPDATE ritocchi SET risultato = ? WHERE id = ?",
                            (str(vuota / "togli-900-b.png"), numero))
    with con_due.lettura() as connessione:
        assert copia.toppa_in_attesa(connessione, vuota, numero) == \
            vuota / f"togli-{numero}.png"
        assert copia.toppa_in_attesa(connessione, vuota, 900, True) == \
            vuota / "togli-900-a1-b.png"
        assert copia.toppa_in_attesa(connessione, vuota, 900) == vuota / "togli-900.png"
    with con_due.scrittura() as connessione:
        connessione.execute("UPDATE ritocchi SET risultato = ? WHERE id = ?",
                            (str(vuota / f"togli-{numero}-b.png"), numero))
    with con_due.lettura() as connessione:
        assert copia.toppa_in_attesa(connessione, vuota, numero, True) == \
            vuota / f"togli-{numero}-a1-b.png"


def test_una_sfida_gia_votata_resta_quando_il_lavoro_si_rifa(con_due):
    lavoro_id, file_id = _in_sfida(con_due)
    with con_due.scrittura() as connessione:
        sfida_togli.butta(sfida_togli.vota(connessione, lavoro_id, file_id, "A"))
    votata = _sfida(con_due, lavoro_id, file_id)
    assert votata["voto"] == "A"
    coda.rifiuta(con_due, lavoro_id)
    assert _sfida(con_due, lavoro_id, file_id) == votata
    coda.rimetti(con_due, lavoro_id)
    togli = Togliere()
    _gira(con_due, togli)
    assert len(togli.lavori) == 1
    assert _sfida(con_due, lavoro_id, file_id) == votata
    assert _stato(con_due, lavoro_id) == coda.DA_RIVEDERE
    coda.approva(con_due, lavoro_id)
    assert _stato(con_due, lavoro_id) == coda.FATTO


def test_una_sfida_si_riscrive_solo_finche_non_e_votata(con_due):
    lavoro_id, file_id = _in_sfida(con_due)
    nuova = {"motore_a": "x", "motore_b": "y", "sinistra": "B", "pronta_b": "/altrove/b.png",
             "impronta_b": "z", "toppe_b": {"7": {"risultato": None}}}
    with con_due.scrittura() as connessione:
        sfida_togli.registra(connessione, lavoro_id, file_id, sfida_togli.VIDEO, nuova)
    riscritta = _sfida(con_due, lavoro_id, file_id)
    assert {chiave: riscritta[chiave] for chiave in (
        "genere", "motore_a", "motore_b", "sinistra", "pronta_b", "impronta_b", "voto")} == {
        "genere": sfida_togli.VIDEO, "motore_a": "x", "motore_b": "y", "sinistra": "B",
        "pronta_b": "/altrove/b.png", "impronta_b": "z", "voto": None}
    assert json.loads(riscritta["toppe_b"]) == nuova["toppe_b"]
    with con_due.scrittura() as connessione:
        sfida_togli.vota(connessione, lavoro_id, file_id, "pari")
    votata = _sfida(con_due, lavoro_id, file_id)
    with con_due.scrittura() as connessione:
        sfida_togli.registra(connessione, lavoro_id, file_id, sfida_togli.FOTO,
                             {**nuova, "motore_a": "w", "sinistra": "A"})
    assert _sfida(con_due, lavoro_id, file_id) == votata


def test_una_sfida_non_votata_rimasta_si_rifa_da_capo(con_due):
    lavoro_id, file_id = _in_sfida(con_due)
    coda.rifiuta(con_due, lavoro_id)
    vecchia = {"motore_a": SECONDO, "motore_b": togliere.FINTO, "sinistra": "A",
               "pronta_b": "/altrove/vecchia.png", "impronta_b": "v", "toppe_b": {}}
    with con_due.scrittura() as connessione:
        sfida_togli.registra(connessione, lavoro_id, file_id, sfida_togli.FOTO, vecchia)
    coda.rimetti(con_due, lavoro_id)
    togli = Togliere()
    _gira(con_due, togli)
    assert len(togli.lavori) == 2
    rifatta = _sfida(con_due, lavoro_id, file_id)
    assert rifatta["voto"] is None and rifatta["pronta_b"] != vecchia["pronta_b"]
    assert Path(rifatta["pronta_b"]).is_file()
    assert attesa.e_dentro(Path(rifatta["pronta_b"]))


def test_all_avvio_si_tolgono_le_copie_di_lavoro_rimaste(importato, cartella, monkeypatch):
    eventi = _sentiti(monkeypatch, "evento")
    dove = _in_attesa(cartella)
    radice = Path(importato.dove.radice) / attesa.NOME
    orfane = [dove / "ritocco-1-piccola.jpg", dove / "ritocco-1-piccola.jpg.parziale",
              dove / "togli-9.png", dove / "togli-9-b.mkv", radice / "togli-4.png"]
    altri = [dove / "miglioria-1.jpg", dove / "piccola.jpg", dove / "ritoccox.png",
             dove / "xtogli-9.png", cartella / "togli-9.png", cartella / "ritocco-1.jpg"]
    _scrivi(*orfane, *altri)
    sottocartella = dove / "togli-cartella"
    sottocartella.mkdir()
    collegamento = dove / "ritocco-collegato.png"
    collegamento.symlink_to(altri[0])
    assert rimaste.butta(importato) == len(orfane)
    assert not any(os.path.lexists(file) for file in orfane)
    assert all(file.is_file() for file in altri)
    assert sottocartella.is_dir() and collegamento.is_symlink()
    assert eventi == [("ritocco.rimaste_tolte", {"file": len(orfane)})]
    assert rimaste.butta(importato) == 0
    assert len(eventi) == 1


def test_all_avvio_si_guarda_anche_vicino_agli_scatti_ritoccati(importato, cartella):
    copia.metti(importato, _file_di(importato, "piccola.jpg"), [_volto(ZONA_A)])
    vicina = cartella / "2016" / attesa.NOME / "togli-3.png"
    lontana = cartella / "2019" / attesa.NOME / "togli-3.png"
    _scrivi(vicina, lontana)
    assert rimaste.butta(importato) == 1
    assert not vicina.exists() and lontana.is_file()


def test_all_avvio_le_copie_che_servono_restano(con_due, cartella, tmp_path):
    lavoro_id, file_id = _in_sfida(con_due)
    with con_due.lettura() as connessione:
        [pronto] = coda.pronti(connessione, lavoro_id)
    sfida = _sfida(con_due, lavoro_id, file_id)
    dove = _in_attesa(cartella)
    ritocco = _il_togli(con_due, file_id)
    toppa_a, toppa_b = dove / "togli-77.png", dove / "togli-77-b.png"
    segnata, stesso_nome = dove / "ritocco-5-segnata.jpg", dove / "togli-78.png"
    preparata = dove / "ritocco-6-preparata.jpg"
    _scrivi(toppa_a, toppa_b, segnata, stesso_nome, preparata)
    piccola = _file_di(con_due, "piccola.jpg")
    copia.metti(con_due, piccola, [_volto(ZONA_A)])
    with con_due.scrittura() as connessione:
        connessione.execute("UPDATE ritocchi SET risultato = ? WHERE id = ?",
                            (str(toppa_a), ritocco["id"]))
        connessione.execute("UPDATE sfide_togli SET toppe_b = ? WHERE lavoro_id = ?",
                            (json.dumps({str(ritocco["id"]): {"risultato": str(toppa_b)}}),
                             lavoro_id))
        connessione.execute("UPDATE ritoccate SET in_preparazione = ? WHERE file_id = ?",
                            (str(preparata), piccola))
        in_chiaro.segna(connessione, file_id, segnata, "abc")
        in_chiaro.segna(connessione, file_id, tmp_path / "altrove" / stesso_nome.name, "def")
    tenuti = [Path(pronto["pronta"]), Path(sfida["pronta_b"]), toppa_a, toppa_b, segnata,
              stesso_nome, preparata]
    assert all(file.parent == dove for file in tenuti[:2])
    assert rimaste.butta(con_due) == 0
    assert all(file.is_file() for file in tenuti)


def test_all_avvio_la_copia_di_un_lavoro_finito_si_toglie(con_due):
    lavoro_id, file_id = _in_sfida(con_due)
    with con_due.scrittura() as connessione:
        sfida_togli.butta(sfida_togli.vota(connessione, lavoro_id, file_id, "A"))
        [pronto] = coda.pronti(connessione, lavoro_id)
    pronta = Path(pronto["pronta"])
    dati = pronta.read_bytes()
    coda.approva(con_due, lavoro_id)
    _scrivi(pronta)
    pronta.write_bytes(dati)
    assert rimaste.butta(con_due) == 1 and not pronta.exists()


def test_all_avvio_non_si_toglie_niente_mentre_un_lavoro_gira(importato, cartella):
    lavoro_id = coda.metti(importato, [{"file_id": _gita(importato), **_da_togliere()}])
    orfana = _in_attesa(cartella) / "togli-9.png"
    _scrivi(orfana)
    with importato.scrittura() as connessione:
        coda.segna(connessione, lavoro_id, coda.IN_LAVORO)
    assert rimaste.butta(importato) == 0 and orfana.is_file()
    with importato.scrittura() as connessione:
        coda.segna(connessione, lavoro_id, coda.IN_CODA)
    assert rimaste.butta(importato) == 1 and not orfana.exists()


def test_all_avvio_una_rimasta_che_non_si_toglie_si_lascia_e_si_dice(importato, cartella,
                                                                      monkeypatch):
    dove = _in_attesa(cartella)
    bloccata, libera = dove / "togli-8.png", dove / "togli-9.png"
    _scrivi(bloccata, libera)
    _non_si_toglie(monkeypatch, bloccata)
    avvisi = _sentiti(monkeypatch)
    eventi = _sentiti(monkeypatch, "evento")
    assert rimaste.butta(importato) == 1
    assert bloccata.is_file() and not libera.exists()
    assert [nome for nome, _ in avvisi] == ["ritocco.rimasta_non_tolta"]
    assert eventi == [("ritocco.rimaste_tolte", {"file": 1})]
    assert rimaste.butta(importato) == 0 and bloccata.is_file()
    assert len(avvisi) == 2 and len(eventi) == 1


def test_la_riparazione_all_avvio_toglie_le_rimaste_dopo_aver_rimesso_in_coda(
        importato, cartella, monkeypatch):
    lavoro_id = coda.metti(importato, [{"file_id": _gita(importato), **_da_togliere()}])
    orfana = _in_attesa(cartella) / "togli-9.png"
    _scrivi(orfana)
    with importato.scrittura() as connessione:
        coda.segna(connessione, lavoro_id, coda.IN_LAVORO)
    coda_ritocco.ripara(importato)
    assert _stato(importato, lavoro_id) == coda.IN_CODA and not orfana.exists()
    errori = _sentiti(monkeypatch, "errore")

    def guasta(archivio):
        raise RuntimeError("rotto")

    monkeypatch.setattr(rimaste, "butta", guasta)
    assert coda_ritocco.ripara(importato)["ripartita"] is False
    assert [nome for nome, _ in errori] == ["ritocco.rimaste_guasto"]


def test_una_copia_che_non_si_cancella_si_segna_con_la_sua_parziale(importato, cartella,
                                                                    monkeypatch):
    file_id = _file_di(importato, "piccola.jpg")
    dove = _in_attesa(cartella)
    pronta = dove / "ritocco-1-piccola.jpg"
    parziale = pronta.with_name(pronta.name + attesa.PARZIALE)
    sola = dove / "ritocco-2-piccola.jpg"
    _scrivi(pronta, parziale, sola)
    monkeypatch.setattr(copia, "butta", _bloccata)
    avvisi = _sentiti(monkeypatch)
    copia.via_la_pronta(importato, file_id, pronta, "segno-pronta")
    copia.via_la_pronta(importato, file_id, sola, "segno-sola")
    copia.via_la_pronta(importato, file_id, dove / "ritocco-3-sparita.jpg", "segno-sparita")
    with importato.lettura() as connessione:
        righe = [(riga["file_id"], riga["percorso"], riga["impronta"])
                 for riga in in_chiaro.rimaste(connessione)]
    assert righe == [(file_id, str(pronta), "segno-pronta"),
                     (file_id, str(parziale), impronta.del_file(parziale)),
                     (file_id, str(sola), "segno-sola")]
    assert [nome for nome, _ in avvisi] == ["ritocco.copia_non_tolta"] * 3


def test_una_parziale_che_non_e_un_file_non_si_segna(importato, cartella, monkeypatch):
    file_id = _file_di(importato, "piccola.jpg")
    dove = _in_attesa(cartella)
    pronta = dove / "ritocco-4-piccola.jpg"
    _scrivi(pronta)
    pronta.with_name(pronta.name + attesa.PARZIALE).mkdir()
    monkeypatch.setattr(copia, "butta", _bloccata)
    _sentiti(monkeypatch)
    copia.via_la_pronta(importato, file_id, pronta, "segno-pronta")
    with importato.lettura() as connessione:
        righe = [(riga["percorso"], riga["impronta"])
                 for riga in in_chiaro.rimaste(connessione)]
    assert righe == [(str(pronta), "segno-pronta")]


def test_una_copia_gia_segnata_non_si_tocca(importato, cartella, monkeypatch):
    file_id = _file_di(importato, "piccola.jpg")
    pronta = _in_attesa(cartella) / "ritocco-1-piccola.jpg"
    _scrivi(pronta)
    with importato.scrittura() as connessione:
        in_chiaro.segna(connessione, file_id, pronta, "segno")
    copia.via_la_pronta(importato, file_id, pronta, "altro")
    assert pronta.is_file()


def test_butta_prova_la_copia_e_la_parziale_e_poi_dice_il_primo_guasto(tmp_path,
                                                                       monkeypatch):
    dove = tmp_path / attesa.NOME
    pronta = dove / "ritocco-1-a.jpg"
    parziale = pronta.with_name(pronta.name + attesa.PARZIALE)
    _scrivi(pronta, parziale)
    with monkeypatch.context() as cambio:
        _non_si_toglie(cambio, pronta)
        with pytest.raises(PermissionError, match="ritocco-1-a.jpg$"):
            copia.butta(pronta)
    assert pronta.is_file() and not parziale.exists()
    _scrivi(parziale)
    with monkeypatch.context() as cambio:
        _non_si_toglie(cambio, pronta, parziale)
        with pytest.raises(PermissionError, match="ritocco-1-a.jpg$"):
            copia.butta(pronta)
    _scrivi(pronta)
    with monkeypatch.context() as cambio:
        _non_si_toglie(cambio, parziale)
        with pytest.raises(PermissionError, match="parziale$"):
            copia.butta(pronta)
    assert not pronta.exists() and parziale.is_file()
    copia.butta(pronta)
    assert not parziale.exists()
