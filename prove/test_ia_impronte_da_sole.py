from __future__ import annotations

import threading
import time
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from officina.impronte import rifacimento
from officina.web import lavori


def _cliente():
    from officina.web.server import app

    return TestClient(app, client=("127.0.0.1", 51000))


def _giro(stato, partiti):
    archivio = SimpleNamespace(di_prova=False)

    def parti(_archivio, nome):
        partiti.append(nome)
        return True

    return rifacimento.Rifacimento(archivio=lambda: archivio, occupata=lambda: False,
                                   parti=parti, restano=lambda _a, _n: stato["restano"])


def test_il_rifacimento_non_riparte_se_il_giro_prima_non_e_andato_avanti(monkeypatch):
    monkeypatch.setattr(rifacimento, "da_rifare", lambda _a: "radio4")
    stato, partiti = {"restano": 7}, []
    giro = _giro(stato, partiti)
    assert giro.un_giro() == "radio4"
    assert giro.un_giro() is None and giro.un_giro() is None
    assert partiti == ["radio4"]


def test_il_rifacimento_riparte_se_e_andato_avanti_o_ci_sono_foto_nuove(monkeypatch):
    monkeypatch.setattr(rifacimento, "da_rifare", lambda _a: "radio4")
    stato, partiti = {"restano": 7}, []
    giro = _giro(stato, partiti)
    assert giro.un_giro() == "radio4"
    stato["restano"] = 3
    assert giro.un_giro() == "radio4"
    stato["restano"] = 9
    assert giro.un_giro() == "radio4"
    assert partiti == ["radio4"] * 3


def test_se_non_parte_non_si_segna_il_giro(monkeypatch):
    monkeypatch.setattr(rifacimento, "da_rifare", lambda _a: "radio4")
    risposte = [False, True]
    giro = rifacimento.Rifacimento(archivio=lambda: SimpleNamespace(di_prova=False),
                                   occupata=lambda: False,
                                   parti=lambda *_: risposte.pop(0),
                                   restano=lambda *_: 5)
    assert giro.un_giro() is None
    assert giro.un_giro() == "radio4"


def test_quanti_restano_conta_quelle_del_modello_nuovo(monkeypatch):
    import contextlib

    from officina import descrittori
    from officina.descrittori.grandi import Radio4
    from officina.modello import impronte as magazzino

    monkeypatch.setitem(descrittori.SCHEDE, "radio4", Radio4.scheda)
    visti = []
    monkeypatch.setattr(magazzino, "quanti_da_fare",
                        lambda _c, nome, versione: visti.append((nome, versione)) or 11)

    class Archivio:
        @contextlib.contextmanager
        def lettura(self):
            yield None

    assert rifacimento.quanti_restano(Archivio(), "radio4") == 11
    assert visti == [("radio4", Radio4.scheda.versione)]


def _sosta_ferma(monkeypatch):
    from officina.web import sosta

    monkeypatch.setattr(sosta, "per_la_copia", SimpleNamespace(
        attiva=False, in_attesa=lambda: [], si_fermano=lambda: []))


def test_la_scheda_e_occupata_se_qualcuno_la_tiene_o_la_aspetta(monkeypatch):
    _sosta_ferma(monkeypatch)
    turno = lavori.TurnoDellaScheda()
    monkeypatch.setattr(lavori, "turno", turno)
    assert rifacimento._occupata() is False
    altro = lavori.Lavoro("la gara dei video", scheda=True)
    assert turno.prendi_se_libera(altro)
    assert rifacimento._occupata() is True
    turno.lascia(altro)
    assert rifacimento._occupata() is False


def test_la_scheda_e_occupata_mentre_gira_la_fila_o_le_impronte(monkeypatch):
    from officina.web.strade import comune

    _sosta_ferma(monkeypatch)
    monkeypatch.setattr(lavori, "turno", lavori.TurnoDellaScheda())
    for lavoro in (comune.lavoro_ia, comune.lavoro_impronte_passata):
        lavoro.rifletti({"sta_lavorando": True})
        try:
            assert rifacimento._occupata() is True
        finally:
            lavoro.riflesso = None
    assert rifacimento._occupata() is False


def test_il_turno_e_libero_solo_senza_nessuno_che_aspetta():
    turno = lavori.TurnoDellaScheda()
    assert turno.libera
    tiene = lavori.Lavoro("le impronte", scheda=True)
    aspetta = lavori.Lavoro("l'intelligenza artificiale", scheda=True)
    assert turno.prendi(tiene, "impronte")
    assert not turno.libera
    filo = threading.Thread(target=turno.prendi, args=(aspetta, "intelligenza"), daemon=True)
    filo.start()
    for _ in range(100):
        if aspetta.numeri.get("in_attesa_della_scheda"):
            break
        time.sleep(0.01)
    assert aspetta.numeri["in_attesa_della_scheda"] == "le impronte"
    turno.lascia(tiene)
    filo.join(2)
    assert turno.chi is aspetta and not turno.libera
    turno.lascia(aspetta)
    assert turno.libera


def test_mentre_gira_la_fila_le_impronte_da_sole_non_partono(archivio_pieno):
    from officina.archivio import accesso
    from officina.web.strade import comune, misura

    comune.lavoro_ia.rifletti({"sta_lavorando": True})
    try:
        assert misura.parti_le_impronte_per(accesso.aperto(), "") is False
        assert not comune.lavoro_impronte_passata.sta_lavorando
    finally:
        comune.lavoro_ia.riflesso = None


def _impronte_da_sole(comune, ferma):
    fermate = threading.Event()

    def lavora():
        fermate.wait(10)

    comune.lavoro_impronte_passata.parti(lavora, "impronte")
    ferma.append(fermate)
    return fermate


def test_avvia_ferma_le_impronte_da_sole_e_parte_la_fila(archivio_pieno, monkeypatch):
    from officina.web.strade import comune, intelligenza, misura, persone

    fermi = []
    monkeypatch.setattr(misura, "ferma_le_impronte",
                        lambda aspetta=0: [evento.set() for evento in fermi])
    fermate = _impronte_da_sole(comune, fermi)
    assert intelligenza.impronte_da_sole()
    partiti = []

    def finto(chiave):
        def parti(_archivio):
            partiti.append(chiave)
        return parti

    monkeypatch.setattr(misura, "parti_le_impronte", finto("impronte"))
    monkeypatch.setattr(persone, "parti_i_volti", finto("volti"))
    risposta = _cliente().post("/intelligenza/avvia", data={"scelti": ["impronte", "volti"]},
                               follow_redirects=False)
    assert risposta.status_code == 303
    assert fermate.is_set()
    assert comune.lavoro_ia.aspetta_che_finisca(10)
    assert partiti == ["impronte", "volti"]
    assert not intelligenza.impronte_da_sole()


def test_la_pagina_mostra_le_impronte_partite_da_sole(archivio_pieno):
    from officina.web.strade import comune

    fermi = []
    fermate = _impronte_da_sole(comune, fermi)
    try:
        pagina = _cliente().get("/intelligenza").text
        assert 'data-da-sole="1"' in pagina
        assert "Partite da sole" in pagina
        assert 'formaction="/misura/impronte/ferma"' in pagina
        assert "si fermano e ripartono nella tua fila" in pagina
        dati = _cliente().get("/api/intelligenza?solo_fila=1").json()
        assert dati["impronte_da_sole"] is True and "mancano" not in dati
    finally:
        fermate.set()
        comune.lavoro_impronte_passata.aspetta_che_finisca(5)
    pagina = _cliente().get("/intelligenza").text
    assert 'data-da-sole="0"' in pagina and "Partite da sole" not in pagina


def test_la_pagina_dice_chi_tiene_la_scheda_mentre_la_fila_aspetta(archivio_pieno):
    from officina.web.strade import comune

    comune.lavoro_ia.rifletti({"sta_lavorando": True,
                               "numeri": {"in_attesa_della_scheda": "gara_video"}})
    try:
        dati = _cliente().get("/api/intelligenza?solo_fila=1").json()
        assert dati["aspetta_la_scheda"] == "la gara dei video"
        pagina = _cliente().get("/intelligenza").text
        assert "Aspetto la scheda video: la sta usando la gara dei video." in pagina
        assert 'data-aspetta="la gara dei video"' in pagina
    finally:
        comune.lavoro_ia.riflesso = None
        comune.lavoro_ia.numeri.clear()


def test_la_pagina_si_aggiorna_da_sola_anche_quando_non_gira_niente():
    testo = Path("officina/web/statici/js/intelligenza.js").read_text(encoding="utf-8")
    assert "if (corre) {" not in testo
    assert "if (pagina) {" in testo
    assert '"/api/intelligenza?solo_fila=1"' in testo
    assert "window.location.reload()" in testo
    for campo in ("sta_lavorando", "impronte_da_sole", "aspetta_la_scheda"):
        assert campo in testo
