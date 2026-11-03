from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from officina.archivio import accesso
from officina.archivio.database import uno
from officina.importazione import motore as il_motore
from officina.importazione import scansione
from officina.web import sosta
from officina.web.strade import comune, importazione

PARTI = 'action="/importazione/parti"'
RIPRENDI = 'action="/importazione/riprendi"'
FERMA = 'action="/importazione/ferma"'
NOTE = {"copia": "riparte da sola appena la copia è finita",
        "tu": "L'hai fermata tu",
        "disco": "Non trovo i prossimi file da importare",
        "spazio": "Lo spazio sul disco potrebbe non bastare"}


@pytest.fixture
def cliente(archivio, monkeypatch):
    from officina.web import server

    monkeypatch.setattr(comune, "piano_pronto", None)
    monkeypatch.setattr(comune, "lavoro", None)
    yield TestClient(server.app, client=("127.0.0.1", 51000))
    if comune.lavoro is not None:
        comune.lavoro.ferma()


@pytest.fixture
def foto(tmp_path):
    from officina.finto import generatore

    dove = tmp_path / "foto"
    generatore.genera(dove, quanti=3, seme=7, leggero=True)
    return dove


class _Spento:

    def acceso(self) -> bool:
        return False

    def memoria(self) -> dict:
        return {}

    def ferma(self) -> None:
        return None

    def riparti(self, archivio, memoria: dict) -> None:
        return None


@pytest.fixture
def copia(archivio, monkeypatch):
    carta: dict = {}
    lavori = {nome: _Spento() for nome in sosta.ORDINE}
    lavori[sosta.IMPORTAZIONE] = sosta._Importazione()
    fatta = sosta.Sosta(lavori, leggi=lambda: carta.get("scritta"),
                        scrivi=lambda valore: carta.update(scritta=valore),
                        archivio=lambda: archivio)
    monkeypatch.setattr(sosta, "per_la_copia", fatta)
    yield fatta
    fatta.smetti(5.0)


def _gira(copia, attiva: bool) -> None:
    copia._serve = lambda: attiva
    copia.giro()


def _poco_spazio(monkeypatch) -> None:
    monkeypatch.setattr(scansione, "controlla_spazio",
                        lambda byte, dove: scansione.Spazio(servono=10 ** 12, liberi=1))


def _tasti(cliente) -> set[str]:
    pagina = cliente.get("/importazione").text
    return {nome for nome, cosa in (("parti", PARTI), ("riprendi", RIPRENDI),
                                    ("ferma", FERMA)) if cosa in pagina}


def _note(cliente) -> set[str]:
    pagina = cliente.get("/importazione").text
    return {nome for nome, frase in NOTE.items() if frase in pagina}


def _contato(cliente, foto) -> None:
    cliente.post("/importazione/cartella", data={"percorso": str(foto)})
    cliente.post("/importazione/prepara", data={"parti_da_sola": "si"})


def _aspetta() -> None:
    comune.lavoro._filo.join(timeout=60)


def _ultima(archivio) -> tuple[str, int, int]:
    with archivio.lettura() as connessione:
        riga = uno(connessione, "SELECT id, stato, fatti FROM importazioni "
                                "ORDER BY id DESC LIMIT 1")
        restano = uno(connessione, "SELECT count(*) AS q FROM coda_importazione "
                                   "WHERE importazione_id = ? AND stato = 'in_attesa'",
                      riga["id"])["q"]
    return riga["stato"], restano, riga["fatti"]


def _a_meta(foto) -> int:
    motore = importazione.motore_attuale()
    motore.prepara([foto])
    motore.esegui(al_passo=lambda _: motore.ferma())
    return motore.importazione_id


def _non_e_partita() -> bool:
    return comune.lavoro is None or comune.lavoro._filo is None


def test_dopo_aver_contato_parte_da_sola_se_lo_spazio_basta(cliente, foto, archivio):
    archivio.salva_stato(importazione.FERMATA_DA_TE, 999)
    _contato(cliente, foto)
    _aspetta()
    stato, restano, fatti = _ultima(archivio)
    with archivio.lettura() as connessione:
        scatti = uno(connessione, "SELECT count(*) AS q FROM scatti")["q"]
    assert (stato, restano) == ("finita", 0)
    assert fatti > 0 and scatti > 0
    assert comune.piano_pronto is None
    assert archivio.stato(importazione.FERMATA_DA_TE) is None
    assert _tasti(cliente) == set()


def test_se_lo_spazio_non_basta_aspetta_il_tasto_importa(cliente, foto, archivio,
                                                         monkeypatch):
    _poco_spazio(monkeypatch)
    _contato(cliente, foto)
    assert _non_e_partita()
    pagina = cliente.get("/importazione").text
    assert "Non è partita da sola" in pagina
    assert _tasti(cliente) == {"parti"}
    cliente.post("/importazione/parti")
    _aspetta()
    assert _ultima(archivio)[:2] == ("finita", 0)
    assert _tasti(cliente) == set()


def test_dalla_guida_conta_e_basta(cliente, foto):
    cliente.post("/importazione/cartella", data={"percorso": str(foto)})
    cliente.post("/importazione/prepara", data={"dove_torno": "/benvenuto/cartella"})
    assert _non_e_partita()
    assert comune.piano_pronto["file"] > 0
    assert _tasti(cliente) == {"parti"}


def test_senza_file_non_parte_e_non_c_e_importa(cliente, tmp_path, archivio):
    vuota = tmp_path / "vuota"
    vuota.mkdir()
    _contato(cliente, vuota)
    assert _non_e_partita()
    pagina = cliente.get("/importazione").text
    assert "non ho trovato foto né video" in pagina
    assert _tasti(cliente) == set()
    assert importazione.riprendi_l_importazione_in_sottofondo(archivio) is False
    assert _non_e_partita()


def test_mentre_lavora_c_e_solo_fermati(cliente, foto, monkeypatch):
    _poco_spazio(monkeypatch)
    _contato(cliente, foto)
    monkeypatch.setattr(il_motore.InSottofondo, "sta_lavorando", property(lambda _: True))
    assert _tasti(cliente) == {"ferma"}
    assert _note(cliente) == set()


def test_finita_non_ci_sono_tasti(cliente, foto):
    importazione.motore_attuale().prepara([foto])
    importazione.motore_attuale().esegui()
    assert _tasti(cliente) == set()


def test_i_conteggi_della_pagina_fanno_partire_da_soli(cliente, foto, monkeypatch):
    moduli = r'<form method="post" action="/importazione/prepara"[^>]*>(.*?)</form>'
    da_sola = '<input type="hidden" name="parti_da_sola" value="si">'
    cliente.post("/importazione/cartella", data={"percorso": str(foto)})
    primo = re.findall(moduli, cliente.get("/importazione").text, re.S)
    _poco_spazio(monkeypatch)
    cliente.post("/importazione/prepara", data={"parti_da_sola": "si"})
    secondo = re.findall(moduli, cliente.get("/importazione").text, re.S)
    monkeypatch.setattr(scansione, "controlla_spazio",
                        lambda byte, dove: scansione.Spazio(servono=1, liberi=10 ** 12))
    cliente.post("/importazione/prepara", data={"dove_torno": "/benvenuto/cartella"})
    terzo = re.findall(moduli, cliente.get("/importazione").text, re.S)
    assert len(primo) == len(secondo) == len(terzo) == 1
    assert "Conta e importa" in primo[0] and "Conta e importa" in secondo[0]
    assert "Conta di nuovo" in terzo[0]
    assert all(da_sola in modulo for modulo in primo + secondo + terzo)


def test_la_ripresa_torna_in_corso(cliente, foto, archivio, monkeypatch):
    partite = []
    _a_meta(foto)
    monkeypatch.setattr(il_motore.InSottofondo, "parti",
                        lambda lavoro: partite.append(lavoro))
    assert importazione.riprendi_l_importazione_in_sottofondo(archivio) is True
    assert len(partite) == 1 and _ultima(archivio)[0] == "in_corso"


def test_chiusa_a_meta_riparte_da_sola(cliente, foto, archivio):
    _a_meta(foto)
    stato, restano, fatti = _ultima(archivio)
    assert stato == "interrotta" and restano > 0 and fatti + restano > 1
    assert _tasti(cliente) == {"riprendi"}
    assert _note(cliente) == set()
    assert importazione.riprendi_l_importazione_in_sottofondo(archivio) is True
    _aspetta()
    assert _ultima(archivio)[:2] == ("finita", 0)


def test_rimasta_in_corso_riparte_da_sola(cliente, foto, archivio):
    motore = importazione.motore_attuale()
    motore.prepara([foto])
    motore.esegui(limite=1)
    assert _ultima(archivio)[0] == "in_corso"
    assert importazione.riprendi_l_importazione_in_sottofondo(archivio) is True
    _aspetta()
    assert _ultima(archivio)[:2] == ("finita", 0)


def test_la_galleria_la_fa_ripartire_alla_prima_apertura(cliente, archivio, monkeypatch):
    chiamate = []
    monkeypatch.setattr(comune, "gia_ripreso", False)
    monkeypatch.setattr(importazione, "riprendi_l_importazione_in_sottofondo",
                        chiamate.append)
    cliente.get("/")
    cliente.get("/")
    assert chiamate == [archivio]


def test_fermata_da_te_non_riparte_da_sola(cliente, foto, archivio, monkeypatch):
    importazione_id = _a_meta(foto)
    cliente.post("/importazione/ferma")
    assert archivio.stato(importazione.FERMATA_DA_TE) == importazione_id
    assert importazione.riprendi_l_importazione_in_sottofondo(archivio) is False
    assert _non_e_partita()
    assert _ultima(archivio)[0] == "interrotta"
    assert _tasti(cliente) == {"riprendi"}
    assert _note(cliente) == {"tu"}
    with monkeypatch.context() as finto:
        finto.setattr(il_motore.InSottofondo, "sta_lavorando", property(lambda _: True))
        cliente.post("/importazione/riprendi")
    assert archivio.stato(importazione.FERMATA_DA_TE) == importazione_id
    assert _ultima(archivio)[0] == "interrotta"
    with monkeypatch.context() as finto:
        finto.setattr(il_motore.InSottofondo, "parti", lambda _: None)
        cliente.post("/importazione/riprendi")
    assert _ultima(archivio)[0] == "in_corso"
    cliente.post("/importazione/riprendi")
    _aspetta()
    assert archivio.stato(importazione.FERMATA_DA_TE) is None
    assert _ultima(archivio)[:2] == ("finita", 0)


def test_un_altra_importazione_fermata_non_blocca_questa(cliente, foto, archivio):
    importazione_id = _a_meta(foto)
    archivio.salva_stato(importazione.FERMATA_DA_TE, importazione_id - 1)
    assert importazione.riprendi_l_importazione_in_sottofondo(archivio) is True
    _aspetta()


def test_se_manca_il_disco_non_riparte(cliente, foto, archivio):
    _a_meta(foto)
    foto.rename(foto.with_name("staccato"))
    assert importazione.riprendi_l_importazione_in_sottofondo(archivio) is False
    assert _non_e_partita()
    assert _ultima(archivio)[0] == "interrotta"
    assert _tasti(cliente) == {"riprendi"}
    assert _note(cliente) == {"disco"}


def test_se_manca_il_prossimo_file_non_riparte(cliente, foto, archivio):
    _a_meta(foto)
    Path(importazione.motore_attuale().prossimi(1)[0]["percorso"]).unlink()
    assert importazione.riprendi_l_importazione_in_sottofondo(archivio) is False
    assert _non_e_partita()
    assert _note(cliente) == {"disco"}


def test_se_il_disco_non_risponde_non_riparte(cliente, foto, archivio, monkeypatch):
    _a_meta(foto)
    rimasta = importazione._rimasta_a_meta(archivio)

    class Muto:
        def __init__(self, percorso):
            self.percorso = percorso

        def exists(self):
            raise PermissionError(self.percorso)

    monkeypatch.setattr(importazione, "Path", Muto)
    assert importazione._perche_non_riparte(archivio, rimasta) == "disco"


def test_se_lo_spazio_non_basta_non_riparte(cliente, foto, archivio, monkeypatch):
    _a_meta(foto)
    _poco_spazio(monkeypatch)
    assert importazione.riprendi_l_importazione_in_sottofondo(archivio) is False
    assert _non_e_partita()
    assert _tasti(cliente) == {"riprendi"}
    assert _note(cliente) == {"spazio"}


def test_se_lo_spazio_non_si_legge_non_riparte(cliente, foto, archivio, monkeypatch):
    _a_meta(foto)

    def rotto(byte, dove):
        raise OSError("disco")

    monkeypatch.setattr(scansione, "controlla_spazio", rotto)
    assert importazione.riprendi_l_importazione_in_sottofondo(archivio) is False
    assert _note(cliente) == {"spazio"}


def test_lo_spazio_si_conta_su_quello_che_resta(cliente, foto, archivio, monkeypatch):
    importazione.motore_attuale().prepara([foto])
    importazione_id = _a_meta(foto)
    with archivio.lettura() as connessione:
        resta = uno(connessione, "SELECT sum(dimensione) AS q FROM coda_importazione "
                                 "WHERE stato = 'in_attesa' AND importazione_id = ?",
                    importazione_id)["q"]
    chiesti = []

    def guarda(byte, dove):
        chiesti.append((byte, dove))
        return scansione.Spazio(servono=0, liberi=1)

    monkeypatch.setattr(scansione, "controlla_spazio", guarda)
    assert importazione.riprendi_l_importazione_in_sottofondo(archivio) is True
    _aspetta()
    assert resta > 0 and chiesti == [(resta, archivio.dove.radice)]


def test_durante_la_prima_copia_aspetta_e_poi_riparte(cliente, foto, archivio, copia):
    _gira(copia, True)
    _a_meta(foto)
    assert importazione.riprendi_l_importazione_in_sottofondo(archivio) is False
    assert _non_e_partita()
    assert copia.aspetta_la_copia(sosta.IMPORTAZIONE)
    assert _tasti(cliente) == {"riprendi"}
    assert _note(cliente) == {"copia"}
    _gira(copia, False)
    _aspetta()
    assert _ultima(archivio)[:2] == ("finita", 0)


def test_fermata_durante_la_copia_non_riparte_dopo(cliente, foto, archivio, copia):
    _gira(copia, True)
    _a_meta(foto)
    importazione.riprendi_l_importazione_in_sottofondo(archivio)
    cliente.post("/importazione/ferma")
    assert not copia.aspetta_la_copia(sosta.IMPORTAZIONE)
    _gira(copia, False)
    assert _non_e_partita()
    assert _ultima(archivio)[0] == "interrotta"


def test_la_copia_non_ferma_un_importazione_che_corre(copia):
    assert sosta._Importazione().acceso() is False
    assert copia.si_fermano() == []


def test_mentre_corre_gia_non_riparte_due_volte(cliente, foto, archivio, monkeypatch):
    _a_meta(foto)
    monkeypatch.setattr(il_motore.InSottofondo, "sta_lavorando", property(lambda _: True))
    assert importazione.riprendi_l_importazione_in_sottofondo(archivio) is False
    assert _ultima(archivio)[0] == "interrotta"
    assert _tasti(cliente) == {"ferma"}
    assert _note(cliente) == set()
    pagina = cliente.get("/importazione").text
    assert 'data-sta-lavorando="si"' in pagina and 'data-momento="lavora"' in pagina
    assert 'action="/importazione/prepara"' not in pagina


def test_nella_prova_non_riparte(cliente, foto, archivio, monkeypatch):
    _a_meta(foto)
    monkeypatch.setattr(accesso, "in_prova", lambda: True)
    assert importazione.riprendi_l_importazione_in_sottofondo(archivio) is False
    assert _ultima(archivio)[0] == "interrotta"


def test_senza_importazioni_non_c_e_niente_da_riprendere(cliente, archivio):
    assert importazione._rimasta_a_meta(archivio) is None
    assert importazione.riprendi_l_importazione_in_sottofondo(archivio) is False
    assert comune.lavoro is None


def test_finita_non_si_riprende_anche_se_restano_righe(cliente, foto, archivio):
    importazione_id = _a_meta(foto)
    with archivio.scrittura() as connessione:
        connessione.execute("UPDATE importazioni SET stato = 'finita' WHERE id = ?",
                            (importazione_id,))
    assert importazione._rimasta_a_meta(archivio) is None
    assert importazione.riprendi_l_importazione_in_sottofondo(archivio) is False
    assert _tasti(cliente) == set()


def test_si_riprende_solo_l_ultima(cliente, foto, archivio):
    motore = importazione.motore_attuale()
    motore.prepara([foto])
    prima = motore.importazione_id
    motore.prepara([foto])
    seconda = motore.importazione_id
    with archivio.lettura() as connessione:
        stato_prima = uno(connessione, "SELECT stato FROM importazioni WHERE id = ?",
                          prima)["stato"]
    assert stato_prima == "interrotta"
    assert importazione._rimasta_a_meta(archivio)["id"] == seconda
    assert motore.rimetti_in_corso(prima) is False
    assert motore.importazione_id == seconda
    with archivio.lettura() as connessione:
        assert uno(connessione, "SELECT stato FROM importazioni WHERE id = ?",
                   prima)["stato"] == "interrotta"
    assert motore.rimetti_in_corso(seconda) is True


def test_rimettere_in_corso_una_finita_non_si_fa(cliente, foto, archivio):
    motore = importazione.motore_attuale()
    motore.prepara([foto])
    motore.esegui()
    finita = motore.importazione_id
    motore.importazione_id = None
    assert motore.rimetti_in_corso(finita) is False
    assert motore.importazione_id is None
    assert _ultima(archivio)[0] == "finita"


def test_rimettere_in_corso_cambia_lo_stato(cliente, foto, archivio):
    importazione_id = _a_meta(foto)
    motore = importazione.motore_attuale()
    motore.importazione_id = None
    assert motore.rimetti_in_corso(importazione_id) is True
    assert motore.importazione_id == importazione_id
    assert _ultima(archivio)[0] == "in_corso"


def test_la_x_chiede_prima_di_togliere_la_cartella(cliente, foto, archivio):
    cliente.post("/importazione/cartella", data={"percorso": str(foto)})
    with archivio.lettura() as connessione:
        cartella_id = scansione.cartelle(connessione)[0]["id"]
    pagina = cliente.get("/importazione").text
    azione = f'action="/importazione/cartella/{cartella_id}/togli"'
    assert pagina.count(azione) == 1
    finestra = re.search(r'<dialog class="finestra" id="togli-%d".*?</dialog>' % cartella_id,
                         pagina, re.S)
    assert finestra is not None and azione in finestra.group(0)
    assert "Lascia stare" in finestra.group(0)
    assert "data-chiudi-finestra" in finestra.group(0)
    tasto = re.search(r'<button[^>]*data-apri-finestra="togli-%d"[^>]*>' % cartella_id,
                      pagina).group(0)
    assert 'type="button"' in tasto
    cliente.post(f"/importazione/cartella/{cartella_id}/togli")
    with archivio.lettura() as connessione:
        assert scansione.cartelle(connessione) == []
