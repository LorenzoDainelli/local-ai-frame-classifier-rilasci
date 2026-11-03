from __future__ import annotations

import re
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path, PureWindowsPath

import pytest
from fastapi.testclient import TestClient

from officina.archivio import migrazioni
from officina.archivio.database import tutti, uno
from officina.importazione import pagina, scansione, storico
from officina.modello import dispositivi
from officina.web.strade import comune, importazione

ADESSO = datetime(2026, 3, 20, 12, 0, tzinfo=timezone.utc)
JSON = {"accept": "application/json"}


@pytest.fixture
def cliente(archivio, monkeypatch):
    from officina.web import server

    monkeypatch.setattr(comune, "piano_pronto", None)
    monkeypatch.setattr(comune, "lavoro", None)
    yield TestClient(server.app, client=("127.0.0.1", 51000))
    if comune.lavoro is not None:
        comune.lavoro.ferma()


@pytest.fixture
def remoto(archivio, cliente):
    from officina.web import server

    archivio.imposta("accesso_dalla_rete", True)
    fuori = TestClient(server.app, client=("192.168.1.40", 51000))
    fuori.get("/")
    with archivio.scrittura() as connessione:
        macchina = dispositivi.elenco(connessione)[0]
        dispositivi.decidi(connessione, macchina["id"], "approvato", "tablet")
    assert fuori.get("/").status_code == 200
    return fuori


def _aggiungi(cliente, dove: Path, *nomi: str) -> list[int]:
    numeri = []
    for nome in nomi:
        (dove / nome).mkdir()
        risposta = cliente.post("/importazione/cartella", follow_redirects=False,
                                data={"percorso": str(dove / nome), "gruppo": ""})
        numeri.append(int(re.search(r"aggiunta=(\d+)", risposta.headers["location"])[1]))
    return numeri


def _riga(archivio, cartella_id: int) -> tuple[int, str | None]:
    with archivio.lettura() as connessione:
        riga = uno(connessione, "SELECT attiva, tolta_il FROM cartelle_sorgente "
                                "WHERE id = ?", cartella_id)
    return riga["attiva"], riga["tolta_il"]


def _pagina(cliente, dove: str = "/importazione") -> str:
    return cliente.get(dove).text


def _tra(testo: str, inizio: str, fine: str) -> str:
    return testo.split(inizio, 1)[1].split(fine, 1)[0]


def test_la_migrazione_71_aggiunge_il_giorno_in_cui_e_stata_tolta():
    applica = {migrazione.versione: migrazione.applica
               for migrazione in migrazioni.MIGRAZIONI}
    assert applica[71] is migrazioni._versione_71
    connessione = sqlite3.connect(":memory:")
    connessione.row_factory = sqlite3.Row
    connessione.execute("CREATE TABLE cartelle_sorgente (id INTEGER PRIMARY KEY, "
                        "percorso TEXT, attiva INTEGER)")
    connessione.execute("INSERT INTO cartelle_sorgente VALUES (1, 'C:/Foto', 0)")
    migrazioni._versione_71(connessione)
    assert dict(uno(connessione, "SELECT * FROM cartelle_sorgente")) == {
        "id": 1, "percorso": "C:/Foto", "attiva": 0, "tolta_il": None}


def test_togli_segna_il_giorno_e_rimetti_lo_cancella(archivio, tmp_path, monkeypatch):
    (tmp_path / "Foto").mkdir()
    with archivio.scrittura() as connessione:
        cartella_id = scansione.aggiungi_cartella(connessione, tmp_path / "Foto")
    assert _riga(archivio, cartella_id) == (1, None)
    monkeypatch.setattr(scansione, "adesso", lambda: "2026-03-20T12:00:00Z")
    with archivio.scrittura() as connessione:
        scansione.togli_cartella(connessione, cartella_id)
    monkeypatch.setattr(scansione, "adesso", lambda: "2026-03-21T12:00:00Z")
    with archivio.scrittura() as connessione:
        scansione.togli_cartella(connessione, cartella_id)
    assert _riga(archivio, cartella_id) == (0, "2026-03-20T12:00:00Z")
    with archivio.scrittura() as connessione:
        assert scansione.rimetti_cartella(connessione, cartella_id) is True
        assert scansione.rimetti_cartella(connessione, cartella_id) is False
        assert scansione.rimetti_cartella(connessione, cartella_id + 99) is False
    assert _riga(archivio, cartella_id) == (1, None)


def test_aggiungerla_di_nuovo_la_toglie_dalle_tolte(archivio, tmp_path):
    (tmp_path / "Foto").mkdir()
    with archivio.scrittura() as connessione:
        cartella_id = scansione.aggiungi_cartella(connessione, tmp_path / "Foto")
        scansione.togli_cartella(connessione, cartella_id)
    assert _riga(archivio, cartella_id)[1] is not None
    with archivio.scrittura() as connessione:
        assert scansione.aggiungi_cartella(connessione, tmp_path / "Foto") == cartella_id
        assert pagina.tolte(connessione) == []
    assert _riga(archivio, cartella_id) == (1, None)


@pytest.mark.parametrize("oggi, lungo, corto", [
    (date(2026, 3, 8), "oggi", "oggi"),
    (date(2026, 3, 9), "ieri", "ieri"),
    (date(2026, 3, 10), "l'8 marzo", "8 mar"),
    (date(2026, 3, 7), "l'8 marzo", "8 mar"),
    (date(2027, 1, 2), "l'8 marzo 2026", "8 mar 2026"),
])
def test_il_giorno_a_parole(oggi, lungo, corto):
    assert storico.il_giorno("2026-03-08T12:00:00Z", oggi) == lungo
    assert storico.giorno_corto("2026-03-08T12:00:00Z", oggi) == corto


@pytest.mark.parametrize("giorno, detto, corto", [
    (1, "il 1º dicembre", "1 dic"), (8, "l'8 dicembre", "8 dic"),
    (11, "l'11 dicembre", "11 dic"), (18, "il 18 dicembre", "18 dic"),
    (31, "il 31 dicembre", "31 dic"),
])
def test_l_articolo_va_col_numero(giorno, detto, corto):
    istante = f"2026-12-{giorno:02d}T12:00:00Z"
    assert storico.il_giorno(istante, date(2026, 6, 15)) == detto
    assert storico.giorno_corto(istante, date(2026, 6, 15)) == corto


@pytest.mark.parametrize("istante", [None, "", "boh"])
def test_senza_giorno_non_si_scrive_niente(istante):
    assert storico.il_giorno(istante, date(2026, 3, 8)) == ""
    assert storico.giorno_corto(istante, date(2026, 3, 8)) == ""


def test_la_mandata_dice_il_giorno_in_cui_e_finita():
    mandata = storico.Mandata(id=4, stato="finita", iniziata_il="2026-03-05T12:00:00Z",
                              finita_il="2026-03-08T12:00:00Z", totale=3, fatti=3,
                              saltati=0, nuovi_scatti=3, coppie_live=0, gia_presenti=0)
    assert mandata.giorno.startswith("5 mar")
    assert mandata.il_giorno.startswith("l'8 marzo")
    mandata.finita_il = None
    assert mandata.il_giorno.startswith("il 5 marzo")


@pytest.mark.parametrize("percorso, sopra", [
    ("C:\\Users\\Anna\\Foto", "C:\\Users\\Anna\\"),
    ("C:\\Users\\Anna\\Foto\\", "C:\\Users\\Anna\\"),
    ("D:\\Foto", "D:\\"),
    ("C:\\", ""),
    ("\\\\nas\\foto\\2024", "\\\\nas\\foto\\"),
    ("/home/anna/foto", "/home/anna/"),
    ("/", ""),
    ("Foto", ""),
    ("", ""),
    ("D:\\Foto\\\\", "D:\\"),
    ("//nas//foto//", "//nas//"),
])
def test_quello_che_sta_sopra_la_cartella(percorso, sopra):
    assert pagina.sopra(percorso) == sopra


def _windows(attaccati=(), rotto=False):
    class Finto:
        def __init__(self, percorso):
            pezzo = PureWindowsPath(percorso)
            self.anchor, self.drive = pezzo.anchor, pezzo.drive

        def is_dir(self):
            if rotto:
                raise PermissionError(self.anchor)
            return False

        def exists(self):
            return self.drive in attaccati

    return Finto


def test_la_cartella_che_c_e_non_e_staccata(tmp_path):
    assert pagina.perche_staccata(str(tmp_path)) == ""
    assert pagina.perche_staccata(str(tmp_path / "sparita")) == "Non trovo la cartella"


@pytest.mark.parametrize("percorso, attaccati, rotto, detto", [
    ("Z:\\Foto", (), False, "Disco Z: non attaccato"),
    ("C:\\Foto", ("C:",), False, "Non trovo la cartella"),
    ("\\\\nas\\foto\\2024", (), False, "Il disco non è attaccato"),
    ("Foto", (), False, "Non trovo la cartella"),
    ("C:\\Foto", ("C:",), True, "Non riesco a guardarci dentro"),
])
def test_perche_la_cartella_e_staccata(monkeypatch, percorso, attaccati, rotto, detto):
    monkeypatch.setattr(pagina, "Path", _windows(attaccati, rotto))
    assert pagina.perche_staccata(percorso) == detto


BASE = {"cartelle": 2, "piano": None, "sta_lavorando": False, "rimasta_a_meta": False,
        "stato": "pronta", "finita_il": None}
FINITA = {"stato": "finita", "finita_il": "2026-03-20T02:00:00Z"}


@pytest.mark.parametrize("cambia, atteso", [
    ({}, "pronta"),
    ({"cartelle": 0}, "vuota"),
    ({"sta_lavorando": True, "piano": {"file": 1}, "rimasta_a_meta": True,
      "cartelle": 0}, "lavora"),
    ({"piano": {"file": 0}, "rimasta_a_meta": True, "cartelle": 0}, "piano"),
    ({"rimasta_a_meta": True, "cartelle": 0, **FINITA}, "ferma"),
    (FINITA, "finita"),
    ({**FINITA, "finita_il": "2026-03-19T11:00:00Z"}, "pronta"),
    ({**FINITA, "stato": "interrotta"}, "pronta"),
    ({**FINITA, "cartelle": 0}, "vuota"),
])
def test_il_momento_dell_importazione(cambia, atteso):
    assert pagina.momento(**{**BASE, **cambia}, adesso=ADESSO) == atteso


@pytest.mark.parametrize("istante, si", [
    (None, False), ("", False), ("boh", False),
    ("2026-03-20T12:00:00Z", True),
    ("2026-03-19T12:00:01Z", True),
    ("2026-03-19T12:00:00Z", False),
    ("2026-03-20T12:00:01Z", False),
    ("2026-03-20T11:00:00", True),
    ("2026-03-19T12:30:00", True),
    ("2026-03-20T13:00:00", False),
    ("2026-03-20T13:30:00+02:00", True),
    ("2026-03-21T01:00:00+14:00", True),
])
def test_finita_da_poco_vuol_dire_nelle_ultime_24_ore(istante, si):
    assert pagina.ORE_DELLA_FINITA == 24
    assert pagina._da_poco(istante, ADESSO) is si


def test_senza_adesso_conta_l_ora_vera():
    assert pagina._da_poco(datetime.now(timezone.utc).isoformat(), None) is True
    assert pagina._da_poco("2001-01-01T00:00:00Z", None) is False


@pytest.fixture
def foto(tmp_path):
    from officina.finto import generatore

    dove = tmp_path / "Vacanze"
    generatore.genera(dove, quanti=3, seme=7, leggero=True)
    return dove


def _scatti(archivio) -> int:
    with archivio.lettura() as connessione:
        return uno(connessione, "SELECT count(*) AS q FROM scatti")["q"]


def _importa(cartelle) -> None:
    motore = importazione.motore_attuale()
    motore.prepara(cartelle)
    motore.esegui()


def test_le_tessere_dicono_come_sta_ogni_cartella(cliente, archivio, foto, tmp_path):
    cliente.post("/importazione/cartella", data={"percorso": str(foto), "gruppo": "nuovo",
                                                 "gruppo_nuovo": "Snap"})
    _importa([foto])
    nuova, sparita = _aggiungi(cliente, tmp_path, "Nuova", "Sparita")
    (tmp_path / "Sparita").rmdir()
    with archivio.scrittura() as connessione:
        connessione.execute("UPDATE cartelle_sorgente SET aggiunta_il = "
                            "'2999-01-01T00:00:00Z' WHERE id IN (?, ?)", (nuova, sparita))
        connessione.execute("UPDATE file_media SET aggiunto_il = '2001-01-01T00:00:00Z' "
                            "WHERE id = (SELECT min(id) FROM file_media)")
    with archivio.lettura() as connessione:
        prima, seconda, terza = pagina.tessere(connessione)
    assert [t.nome for t in (prima, seconda, terza)] == ["Vacanze", "Nuova", "Sparita"]
    assert prima.sopra == str(tmp_path) + "/" and prima.gruppo == "Snap"
    assert prima.scatti == _scatti(archivio) > 1
    assert prima.arrivati == "oggi" and prima.importata
    assert prima.staccata == "" and prima.gruppo_id is not None
    assert (seconda.scatti, seconda.arrivati, seconda.importata) == (0, "", False)
    assert seconda.gruppo_id is None and seconda.staccata == ""
    assert terza.staccata == "Non trovo la cartella"
    with archivio.scrittura() as connessione:
        connessione.execute("UPDATE file_media SET aggiunto_il = '2001-01-01T12:00:00Z'")
    with archivio.lettura() as connessione:
        assert pagina.tessere(connessione)[0].arrivati == "il 1º gennaio 2001"
        assert pagina.tessere(connessione, oggi=date(2001, 1, 2))[0].arrivati == "ieri"


def test_le_scritte_delle_tessere_sulla_pagina(cliente, archivio, foto, tmp_path):
    [vuota] = _aggiungi(cliente, tmp_path, "Vuota")
    cliente.post("/importazione/cartella", data={"percorso": str(foto), "gruppo": ""})
    _importa([tmp_path / "Vuota", foto])
    [nuova] = _aggiungi(cliente, tmp_path, "Nuova")
    with archivio.scrittura() as connessione:
        connessione.execute("UPDATE cartelle_sorgente SET aggiunta_il = "
                            "'2999-01-01T00:00:00Z' WHERE id = ?", (nuova,))
        piena = scansione.cartella_di(connessione, foto)
    testo = _pagina(cliente)

    def tessera(numero):
        return _tra(testo, f'data-cartella="{numero}">', "</article>")

    assert f"{_scatti(archivio)} scatti · ultimi arrivati oggi" in tessera(piena)
    assert "Qui dentro non ho trovato foto né video" in tessera(vuota)
    assert "Appena aggiunta, da importare" in tessera(nuova)
    assert "Annulla importazione" not in tessera(vuota)


def test_le_tessere_senza_importazioni_non_sono_importate(cliente, archivio, tmp_path):
    _aggiungi(cliente, tmp_path, "Foto")
    with archivio.lettura() as connessione:
        [tessera] = pagina.tessere(connessione)
    assert tessera.importata is False and tessera.scatti == 0


def _mandata(archivio, stato: str, iniziata_il: str, nuovi: int = 0) -> None:
    with archivio.scrittura() as connessione:
        connessione.execute("INSERT INTO importazioni (stato, iniziata_il, nuovi_scatti) "
                            "VALUES (?, ?, ?)", (stato, iniziata_il, nuovi))


def _importata(archivio) -> bool:
    with archivio.lettura() as connessione:
        [tessera] = pagina.tessere(connessione)
    return tessera.importata


def test_importata_vuol_dire_dopo_l_ultima_importazione_finita(cliente, archivio, tmp_path):
    [cartella_id] = _aggiungi(cliente, tmp_path, "Foto")
    with archivio.scrittura() as connessione:
        connessione.execute("UPDATE cartelle_sorgente SET aggiunta_il = "
                            "'2026-03-10T00:00:00Z' WHERE id = ?", (cartella_id,))
    _mandata(archivio, "finita", "2026-03-09T23:59:59Z")
    assert _importata(archivio) is False
    _mandata(archivio, "interrotta", "2026-03-11T00:00:00Z")
    _mandata(archivio, "in_corso", "2026-03-12T00:00:00Z")
    assert _importata(archivio) is False
    _mandata(archivio, "finita", "2026-03-10T00:00:00Z")
    assert _importata(archivio) is True


def test_le_tolte_vanno_dalla_piu_recente(cliente, archivio, tmp_path):
    numeri = _aggiungi(cliente, tmp_path, "Uno", "Due", "Tre", "Quattro", "Cinque")
    giorni = {numeri[0]: "2026-03-01T12:00:00Z", numeri[1]: "2026-03-05T12:00:00Z",
              numeri[2]: None, numeri[4]: None}
    with archivio.scrittura() as connessione:
        for cartella_id, giorno in giorni.items():
            connessione.execute("UPDATE cartelle_sorgente SET attiva = 0, tolta_il = ? "
                                "WHERE id = ?", (giorno, cartella_id))
    with archivio.lettura() as connessione:
        tolte = pagina.tolte(connessione, oggi=date(2026, 3, 5))
        assert [t.nome for t in pagina.tessere(connessione)] == ["Quattro"]
    assert [(t.nome, t.quando) for t in tolte] == [
        ("Due", "oggi"), ("Uno", "1 mar"), ("Cinque", ""), ("Tre", "")]
    assert tolte[0].percorso == str(tmp_path / "Due") and tolte[0].conto.file == 0


def test_togli_porta_all_avviso_con_rimetti(cliente, archivio, tmp_path):
    [cartella_id] = _aggiungi(cliente, tmp_path, "Matrimonio")
    risposta = cliente.post(f"/importazione/cartella/{cartella_id}/togli",
                            follow_redirects=False)
    assert risposta.headers["location"] == f"/importazione?tolta={cartella_id}#cartelle"
    testo = _pagina(cliente, f"/importazione?tolta={cartella_id}")
    avviso = _tra(testo, "data-avviso-tolta", "data-chiudi-avviso")
    assert "Hai tolto «Matrimonio» dall'elenco" in avviso
    assert f'action="/importazione/cartella/{cartella_id}/rimetti"' in avviso
    assert "data-vai-alle-tolte" in avviso
    linguetta = _tra(testo, 'id="ag-linguetta-tolte"', "</button>")
    assert 'aria-selected="true"' in linguetta and "ag-punto" in linguetta
    tolte = _tra(testo, 'id="ag-tolte"', "</section>")
    assert tolte.count('<div class="ag-evento nuova">') == 1
    assert ">Matrimonio</b>" in tolte
    assert "Da qui non era arrivato nessuno scatto." in tolte
    assert "hidden" not in _tra(testo, 'id="ag-tolte"', ">")
    assert "hidden" in _tra(testo, 'id="ag-importazioni"', ">")
    poi = _pagina(cliente)
    assert "data-avviso-tolta" not in poi and "ag-punto" not in poi
    assert '<div class="ag-evento nuova">' not in poi


def test_l_avviso_illumina_solo_la_tolta_di_adesso(cliente, archivio, tmp_path):
    uno_id, due_id = _aggiungi(cliente, tmp_path, "Uno", "Due")
    cliente.post(f"/importazione/cartella/{uno_id}/togli")
    cliente.post(f"/importazione/cartella/{due_id}/togli")
    testo = _pagina(cliente, f"/importazione?tolta={uno_id}")
    tolte = _tra(testo, 'id="ag-tolte"', "</section>")
    assert tolte.count('<div class="ag-evento nuova">') == 1
    assert tolte.count('<div class="ag-evento">') == 1
    assert "Hai tolto «Uno» dall'elenco" in testo


def test_l_avviso_non_compare_per_una_cartella_che_c_e(cliente, tmp_path):
    [cartella_id] = _aggiungi(cliente, tmp_path, "Foto")
    testo = _pagina(cliente, f"/importazione?tolta={cartella_id}")
    assert "data-avviso-tolta" not in testo and 'id="storico"' not in testo


def test_rimetti_la_riporta_nell_elenco_illuminata(cliente, archivio, tmp_path):
    uno_id, due_id = _aggiungi(cliente, tmp_path, "Uno", "Due")
    cliente.post(f"/importazione/cartella/{due_id}/togli")
    risposta = cliente.post(f"/importazione/cartella/{due_id}/rimetti",
                            follow_redirects=False)
    assert risposta.status_code == 303
    assert risposta.headers["location"] == f"/importazione?aggiunta={due_id}#cartelle"
    assert _riga(archivio, due_id) == (1, None)
    testo = _pagina(cliente, f"/importazione?aggiunta={due_id}")
    accese = re.findall(r'<article class="ag-tessera nuova" data-cartella="(\d+)">', testo)
    assert accese == [str(due_id)]
    assert f'<article class="ag-tessera" data-cartella="{uno_id}">' in testo
    assert "ag-tessera nuova" not in _pagina(cliente)


def test_rimetti_e_apri_solo_da_questo_computer(cliente, remoto, archivio, tmp_path,
                                                monkeypatch):
    aperte = []
    monkeypatch.setattr(pagina, "apri_in_esplora", aperte.append)
    uno_id, due_id = _aggiungi(cliente, tmp_path, "Uno", "Due")
    cliente.post(f"/importazione/cartella/{due_id}/togli")
    assert remoto.post(f"/importazione/cartella/{due_id}/rimetti",
                       follow_redirects=False).status_code == 403
    assert remoto.post(f"/importazione/cartella/{uno_id}/apri",
                       follow_redirects=False).status_code == 403
    assert _riga(archivio, due_id)[0] == 0 and aperte == []
    testo = _pagina(remoto, f"/importazione?tolta={due_id}")
    assert "/rimetti" not in testo and "/apri" not in testo
    assert "data-avviso-tolta" in testo and f'data-apri-finestra="togli-{uno_id}"' in testo
    assert "Le cartelle si aggiungono dal computer dove gira il programma." in testo
    vicino = _pagina(cliente, f"/importazione?tolta={due_id}")
    assert vicino.count(f'action="/importazione/cartella/{due_id}/rimetti"') == 2
    assert vicino.count(f'action="/importazione/cartella/{uno_id}/apri"') == 1


def test_apri_in_esplora(cliente, archivio, tmp_path, monkeypatch):
    aperte = []
    monkeypatch.setattr(pagina, "apri_in_esplora", aperte.append)
    [cartella_id] = _aggiungi(cliente, tmp_path, "Foto")
    risposta = cliente.post(f"/importazione/cartella/{cartella_id}/apri",
                            follow_redirects=False)
    assert risposta.status_code == 303
    assert risposta.headers["location"] == "/importazione#cartelle"
    assert aperte == [str(tmp_path / "Foto")]


def test_apri_in_esplora_quando_non_si_puo(cliente, archivio, tmp_path, monkeypatch):
    aperte = []
    monkeypatch.setattr(pagina, "apri_in_esplora", aperte.append)
    [cartella_id] = _aggiungi(cliente, tmp_path, "Foto")

    def detto(numero):
        risposta = cliente.post(f"/importazione/cartella/{numero}/apri", headers=JSON)
        assert risposta.status_code == 400
        return risposta.json()["messaggio"]

    assert detto(cartella_id + 50) == "Questa cartella non è più nell'elenco."
    (tmp_path / "Foto").rmdir()
    assert detto(cartella_id) == "Non trovo la cartella: forse il disco non è attaccato."
    assert aperte == []
    (tmp_path / "Foto").mkdir()

    def rotto(percorso):
        raise OSError(percorso)

    monkeypatch.setattr(pagina, "apri_in_esplora", rotto)
    assert detto(cartella_id) == "Esplora risorse non si è aperto."


def test_apri_in_esplora_usa_il_programma_giusto(monkeypatch):
    chiamate = []
    monkeypatch.setattr(pagina.sys, "platform", "linux")
    monkeypatch.setattr(pagina.subprocess, "Popen", chiamate.append)
    pagina.apri_in_esplora(Path("/foto/vacanze"))
    monkeypatch.setattr(pagina.sys, "platform", "win32")
    monkeypatch.setattr(pagina.os, "startfile", chiamate.append, raising=False)
    pagina.apri_in_esplora(Path("/foto/vacanze"))
    assert chiamate == [["xdg-open", "/foto/vacanze"], "/foto/vacanze"]


def test_la_tessera_staccata_si_spegne_e_non_si_apre(cliente, tmp_path):
    uno_id, due_id = _aggiungi(cliente, tmp_path, "Uno", "Due")
    (tmp_path / "Due").rmdir()
    testo = _pagina(cliente)
    spenta = _tra(testo, f'<article class="ag-tessera spenta" data-cartella="{due_id}">',
                  "</article>")
    assert '<span class="ag-bollo giallo">Non trovo la cartella</span>' in spenta
    assert "/apri" not in spenta and f'data-apri-finestra="togli-{due_id}"' in spenta
    accesa = _tra(testo, f'<article class="ag-tessera" data-cartella="{uno_id}">',
                  "</article>")
    assert f'action="/importazione/cartella/{uno_id}/apri"' in accesa
    assert "Appena aggiunta, da importare" in accesa


def test_la_tessera_porta_quello_che_serve_a_cambiare_gruppo(cliente, archivio, tmp_path):
    [cartella_id] = _aggiungi(cliente, tmp_path, "Telefono")
    cliente.post(f"/importazione/cartella/{cartella_id}/gruppo",
                 data={"gruppo": "nuovo", "gruppo_nuovo": "Snapchat"})
    testo = _pagina(cliente)
    with archivio.lettura() as connessione:
        [gruppo] = tutti(connessione, "SELECT id FROM gruppi WHERE nome = 'Snapchat'")
    tasto = re.search(r'<button class="ag-gruppo con-gruppo"[^>]*>', testo, re.DOTALL)[0]
    for pezzo in (f'data-cambia-gruppo="{cartella_id}"', 'data-nome="Telefono"',
                  f'data-percorso="{tmp_path / "Telefono"}"',
                  f'data-gruppo="{gruppo["id"]}"', 'data-scatti="0"'):
        assert pezzo in tasto, pezzo
    assert "<span>Gruppo Snapchat</span>" in testo
    finestra = _tra(testo, 'id="cambia-gruppo"', "</dialog>")
    assert f'value="{gruppo["id"]}"' in finestra and "data-avviso-scatti hidden" in finestra
    assert 'value="nuovo"' in finestra and "data-errore-gruppo" in finestra


def test_le_finestre_per_togliere_e_annullare(cliente, archivio, foto, tmp_path):
    cliente.post("/importazione/cartella", data={"percorso": str(foto), "gruppo": ""})
    _importa([foto])
    [vuota] = _aggiungi(cliente, tmp_path, "Vuota")
    with archivio.lettura() as connessione:
        piena = scansione.cartella_di(connessione, foto)
    testo = _pagina(cliente)
    togli = _tra(testo, f'id="togli-{piena}"', "</dialog>")
    quanti = _scatti(archivio)
    assert f"I {quanti} scatti già arrivati da qui restano nell'app" in togli
    assert "Togli dall'elenco</button>" in togli
    sua = _tra(testo, f'id="togli-{vuota}"', "</dialog>")
    assert "I file sul disco non si toccano." in sua
    annulla = _tra(testo, f'id="annulla-{piena}"', "</dialog>")
    assert f'action="/importazione/cartella/{piena}/annulla"' in annulla
    assert 'class="tasto-comando pericolo"' in annulla
    assert f'id="annulla-{vuota}"' not in testo
    assert f'data-apri-finestra="annulla-{vuota}"' not in testo
    cliente.post(f"/importazione/cartella/{piena}/togli")
    tolta = _pagina(cliente)
    assert f'id="annulla-{piena}"' in tolta and f'id="togli-{piena}"' not in tolta
    riga = _tra(tolta, 'id="ag-tolte"', "</section>")
    assert f"I suoi {quanti} scatti sono ancora nell'app." in riga
    assert f'data-apri-finestra="annulla-{piena}"' in riga


@pytest.mark.parametrize("quanti, scritta", [
    (0, None), (1, "1 cartella · ogni importazione"),
    (3, "3 cartelle · ogni importazione")])
def test_quante_cartelle(cliente, tmp_path, quanti, scritta):
    _aggiungi(cliente, tmp_path, *[f"C{numero}" for numero in range(quanti)])
    testa = _tra(_pagina(cliente), 'id="ag-titolo-cartelle"', "</div>")
    if scritta is None:
        assert "cartell" not in testa.split("</h2>", 1)[1]
    else:
        assert scritta in testa


def test_senza_cartelle_la_pagina_invita_a_sceglierne_una(cliente):
    testo = _pagina(cliente)
    assert 'data-momento="vuota"' in testo and "ag-vuoto" in testo
    assert "data-proporziona" not in testo and 'id="cambia-gruppo"' not in testo
    assert re.search(r'<button class="tasto-comando principale grande" type="button" '
                     r'disabled>.*?Conta e importa</button>', testo, re.DOTALL)
    assert "Ancora nessuna cartella." in testo
    riquadro = _tra(testo, "data-cartella-nuova-riquadro", "</form>")
    assert "ag-aggiungi primo" in testo and "data-autofocus" in riquadro


def test_finita_da_poco_poi_pronta(cliente, archivio, foto):
    cliente.post("/importazione/cartella", data={"percorso": str(foto), "gruppo": ""})
    _importa([foto])
    testo = _pagina(cliente)
    assert 'data-momento="finita"' in testo and "Le ultime arrivate" in testo
    motore = importazione.motore_attuale()
    assert f'href="/?importazione={motore.importazione_id}"' in testo
    assert f"Apri i {_scatti(archivio)} scatti nuovi" in testo
    assert 'href="/stato#misura"' in testo
    assert '<span class="ag-bollo verde">Finita</span>' in testo
    _mandata(archivio, "interrotta", "2026-03-20T11:00:00Z", nuovi=7777)
    sempre = _pagina(cliente)
    assert 'data-momento="finita"' in sempre
    assert "7777" not in sempre.split('id="storico"')[0]
    assert f"Apri i {_scatti(archivio)} scatti nuovi" in sempre
    with archivio.scrittura() as connessione:
        connessione.execute("DELETE FROM importazioni WHERE nuovi_scatti = 7777")
    with archivio.scrittura() as connessione:
        connessione.execute("UPDATE importazioni SET finita_il = '2026-01-10T12:00:00Z'")
    dopo = _pagina(cliente)
    assert 'data-momento="pronta"' in dopo and "Pronta a partire" in dopo
    scatti = _scatti(archivio)
    assert re.search(rf"L'ultima volta, il 10 gennaio( \d{{4}})?: {scatti} scatti nuovi\.",
                     dopo)
    assert "Conto i file nuovi nella cartella." in dopo
    _mandata(archivio, "interrotta", "2026-02-01T12:00:00Z", nuovi=7777)
    ancora = _pagina(cliente)
    assert 'data-momento="pronta"' in ancora
    assert re.search(rf"L'ultima volta, il 10 gennaio( \d{{4}})?: {scatti} scatti nuovi\.",
                     ancora)


def _piano(monkeypatch, file: int, basta: bool) -> None:
    spazio = scansione.Spazio(servono=10 ** 9, liberi=10 ** 12 if basta else 10 ** 8)
    monkeypatch.setattr(comune, "piano_pronto", {"file": file, "byte": 3 * 10 ** 9,
                                                 "spazio": spazio})


def _tasti(testo: str) -> list[str]:
    zona = _tra(testo, 'id="pannello-avanzamento"', "</section>")
    return re.findall(r'<form method="post" action="([^"]+)"', zona)


def test_il_piano_con_lo_spazio_che_basta(cliente, tmp_path, monkeypatch):
    _aggiungi(cliente, tmp_path, "Foto")
    _piano(monkeypatch, 1234, True)
    testo = _pagina(cliente)
    assert 'data-momento="piano"' in testo
    assert '<span class="ag-bollo">Contati</span>' in testo
    assert "Ferma: spazio" not in testo and "Lo spazio basta: servono circa" in testo
    assert ">Importa 1.234 file</button>" in testo
    assert _tasti(testo) == ["/importazione/parti", "/importazione/prepara"]


def test_il_piano_con_poco_spazio(cliente, tmp_path, monkeypatch):
    _aggiungi(cliente, tmp_path, "Foto")
    _piano(monkeypatch, 1234, False)
    testo = _pagina(cliente)
    assert '<span class="ag-bollo giallo">Ferma: spazio</span>' in testo
    assert "Non è partita da sola" in testo and "Lo spazio potrebbe non bastare" in testo
    assert ">Importa lo stesso</button>" in testo and "Importa 1.234 file" not in testo
    assert _tasti(testo) == ["/importazione/prepara", "/importazione/parti"]


def test_il_piano_senza_niente_da_importare(cliente, tmp_path, monkeypatch):
    _aggiungi(cliente, tmp_path, "Foto")
    _piano(monkeypatch, 0, False)
    testo = _pagina(cliente)
    assert "Qui dentro non ho trovato foto né video da importare." in testo
    assert '<span class="ag-bollo">Contati</span>' in testo and "Ferma: spazio" not in testo
    assert _tasti(testo) == ["/importazione/prepara"]
    assert "/importazione/parti" not in testo and "Conta di nuovo" in testo


def test_ferma_porta_riprendi_e_i_conti(cliente, archivio, foto):
    cliente.post("/importazione/cartella", data={"percorso": str(foto), "gruppo": ""})
    _importa([foto])
    motore = importazione.motore_attuale()
    motore.prepara([foto])
    motore.esegui(al_passo=lambda _: motore.ferma())
    testo = _pagina(cliente)
    assert 'data-momento="ferma"' in testo and "Rimasta a metà" in testo
    assert 'action="/importazione/riprendi"' in testo and "barretta ferma" in testo
    assert '<span class="ag-bollo giallo">Ferma</span>' in testo
    assert testo.count("<dt>Scatti nuovi</dt>") == 1 and 'id="conto-scatti"' not in testo
    storia = _tra(testo, 'id="storico"', "</section>")
    assert storia.count('<div class="ag-evento">') == 1
    assert f"Importazione {motore.importazione_id}</b>" not in storia


def test_lavora_ha_i_numeri_che_si_aggiornano(cliente, foto, monkeypatch):
    from officina.importazione import motore as il_motore

    cliente.post("/importazione/cartella", data={"percorso": str(foto), "gruppo": ""})
    importazione.motore_attuale().prepara([foto])
    comune.lavoro = il_motore.InSottofondo(importazione.motore_attuale())
    monkeypatch.setattr(il_motore.InSottofondo, "sta_lavorando", property(lambda _: True))
    testo = _pagina(cliente)
    assert 'data-momento="lavora"' in testo and 'data-sta-lavorando="si"' in testo
    for numero in ("numero-fatti", "riga-stato", "bollo-importazione", "barra",
                   "conto-scatti", "conto-live", "conto-gia", "conto-saltati", "mosaico"):
        assert f'id="{numero}"' in testo, numero
    assert 'id="storico"' not in testo
    assert cliente.get("/api/importazione").json()["sta_lavorando"] is True


def test_il_piano_vero_non_finisce_nello_storico(cliente, foto):
    cliente.post("/importazione/cartella", data={"percorso": str(foto), "gruppo": ""})
    risposta = cliente.post("/importazione/prepara", follow_redirects=False)
    assert risposta.status_code == 303
    testo = _pagina(cliente)
    assert 'data-momento="piano"' in testo
    assert re.search(r">Importa \d+ file</button>", testo)
    assert 'id="storico"' not in testo


def test_la_pagina_e_l_api_dicono_lo_stesso_sul_lavoro(cliente, tmp_path):
    _aggiungi(cliente, tmp_path, "Foto")
    assert 'data-sta-lavorando="no"' in _pagina(cliente)
    assert cliente.get("/api/importazione").json()["sta_lavorando"] is False


def test_lo_storico_con_le_importazioni_di_prima(cliente, archivio, foto):
    cliente.post("/importazione/cartella", data={"percorso": str(foto), "gruppo": ""})
    _importa([foto])
    _importa([foto])
    testo = _pagina(cliente)
    storia = _tra(testo, 'id="storico"', "</section>")
    assert "Importazioni di prima <b class=\"numeri\">2</b>" in storia
    assert "Cartelle tolte <b class=\"numeri\">0</b>" in storia
    assert "hidden" not in _tra(storia, 'id="ag-importazioni"', ">")
    assert "hidden" in _tra(storia, 'id="ag-tolte"', ">")
    assert storia.count('<div class="ag-evento">') == 2
    assert "Nessuna cartella tolta." in storia
    assert f"Apri {_scatti(archivio)}</a>" in storia
