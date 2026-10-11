from __future__ import annotations

import http.client
import json
import time

import pytest

from officina.schermo import collega, patto
from officina.schermo import porta as porta_mod


class _Password:

    def __init__(self, giusta: str | None):
        self.giusta = giusta

    def serve(self) -> bool:
        return self.giusta is not None

    def e_giusta(self, password: str) -> bool:
        return password == self.giusta


@pytest.fixture
def casa(tmp_path, monkeypatch):
    monkeypatch.setenv("OFFICINA_CASA_PROGRAMMA", str(tmp_path / "casa"))
    collega.segreti._in_memoria.clear()
    yield tmp_path / "casa"
    collega.segreti._in_memoria.clear()


@pytest.fixture
def porta(casa):
    nuova = porta_mod.Porta()
    vecchia, porta_mod.porta = porta_mod.porta, nuova
    nuova.apri(_Password("cavallo-batteria"))
    yield nuova
    nuova.chiudi()
    porta_mod.porta = vecchia


def _abbina(porta) -> collega.Fisso:
    codice, _ = porta.codice()
    return collega.abbina("127.0.0.1", porta.porta_tcp, codice)


def test_il_portatile_si_abbina_con_il_codice_e_poi_entra_con_la_password(porta):
    fisso = _abbina(porta)
    assert fisso.impronta == porta.certificato.impronta
    assert collega.fisso_abbinato() == fisso
    assert collega.serve_la_password(fisso) is True

    with pytest.raises(collega.NoDalFisso, match="password"):
        collega.entra(fisso, "sbagliata")
    sessione = collega.entra(fisso, "cavallo-batteria")
    assert porta.chi_e(sessione) == collega.id_di_questo_portatile()
    assert porta.collegato()["id"] == collega.id_di_questo_portatile()


def test_il_gettone_non_resta_scritto_in_chiaro_sul_fisso(porta):
    _abbina(porta)
    scritto = json.dumps(porta_mod.portatili())
    assert collega.segreti.leggi(collega.GETTONE) not in scritto


def test_senza_forziere_si_entra_senza_password(porta):
    porta.chi_password = _Password(None)
    fisso = _abbina(porta)
    assert collega.serve_la_password(fisso) is False
    assert collega.entra(fisso, "")


def test_un_codice_sbagliato_non_abbina_e_dopo_cinque_il_codice_cambia(porta):
    codice, _ = porta.codice()
    sbagliato = f"{(int(codice) + 1) % 1_000_000:06d}"
    for _ in range(porta_mod.TENTATIVI_PER_CODICE):
        with pytest.raises(collega.NoDalFisso):
            collega.abbina("127.0.0.1", porta.porta_tcp, sbagliato)
    assert porta.codice()[0] != codice
    assert porta_mod.portatili() == {}


def test_a_porta_chiusa_non_si_abbina_e_non_si_entra(porta):
    fisso = _abbina(porta)
    porta.aperta = False
    with pytest.raises(collega.NoDalFisso, match="chiusa"):
        collega.entra(fisso, "cavallo-batteria")


def test_un_fisso_con_un_altro_certificato_non_viene_creduto(porta, casa):
    fisso = _abbina(porta)
    impostore = collega.Fisso(fisso.nome, fisso.indirizzo, fisso.porta,
                              "0" * 64, fisso.pem)
    with pytest.raises(collega.NoDalFisso, match="non è quello abbinato"):
        collega.entra(impostore, "cavallo-batteria")


def test_chi_si_mette_in_mezzo_non_passa_la_prova():
    from spake2 import SPAKE2_A, SPAKE2_B

    a = SPAKE2_A(b"123456", idA=b"portatile", idB=b"fisso")
    b = SPAKE2_B(b"123456", idA=b"portatile", idB=b"fisso")
    ma, mb = a.start(), b.start()
    chiave_a, chiave_b = a.finish(mb), b.finish(ma)
    assert chiave_a == chiave_b
    vera = patto.prova(chiave_a, patto.CHI_PORTATILE, "impronta-vera")
    assert not patto.uguali(vera, patto.prova(chiave_b, patto.CHI_PORTATILE, "impronta-finta"))
    gettone = patto.chiudi_il_gettone(chiave_b, "segreto")
    assert patto.apri_il_gettone(chiave_a, gettone) == "segreto"


def test_senza_sessione_il_fisso_non_mostra_niente(porta):
    fisso = _abbina(porta)
    connessione = collega._connessione("127.0.0.1", porta.porta_tcp, fisso.pem, fisso.impronta)
    connessione.request("GET", "/")
    risposta = connessione.getresponse()
    risposta.read()
    assert risposta.status == 401
    assert risposta.getheader("x-schermo-chiuso") == "1"


def test_il_ponte_porta_le_pagine_del_fisso_e_non_lascia_niente_in_cache(porta, archivio_pieno):
    from officina.schermo import dal_portatile

    fisso = _abbina(porta)
    sessione = collega.entra(fisso, "cavallo-batteria")
    chiuso = []
    ponte = collega.Ponte(fisso, sessione, quando_chiuso=lambda: chiuso.append(True))
    ponte.parti()
    try:
        porta_locale = int(ponte.indirizzo.rsplit(":", 1)[1].strip("/"))
        vicino = http.client.HTTPConnection("127.0.0.1", porta_locale, timeout=30)
        vicino.request("GET", "/stato")
        risposta = vicino.getresponse()
        corpo = risposta.read()
        assert risposta.status == 200
        assert b"Stato" in corpo
        assert risposta.getheader("cache-control") == "no-store"
        assert dal_portatile() is False

        porta.stacca()
        vicino.request("GET", "/stato")
        risposta = vicino.getresponse()
        assert b"collegamento con il fisso" in risposta.read()
        assert chiuso == [True]
    finally:
        ponte.ferma()


def test_il_ponte_rifiuta_i_comandi_che_arrivano_da_altre_pagine(porta, archivio_pieno):
    fisso = _abbina(porta)
    ponte = collega.Ponte(fisso, collega.entra(fisso, "cavallo-batteria"))
    ponte.parti()
    try:
        porta_locale = int(ponte.indirizzo.rsplit(":", 1)[1].strip("/"))
        vicino = http.client.HTTPConnection("127.0.0.1", porta_locale, timeout=30)
        vicino.request("POST", "/misura/esegui", body=b"",
                       headers={"origin": "https://cattivo.example", "content-length": "0"})
        risposta = vicino.getresponse()
        risposta.read()
        assert risposta.status == 403
    finally:
        ponte.ferma()


def test_il_fisso_si_trova_nella_rete_di_casa(porta):
    trovati = collega.cerca(secondi=1.0)
    assert any(voce["impronta"] == porta.certificato.impronta for voce in trovati)


@pytest.fixture
def porta_finta(casa, monkeypatch):
    nuova = porta_mod.Porta()
    monkeypatch.setattr(nuova, "_accendi_il_servitore", lambda: None)
    monkeypatch.setattr(nuova, "_accendi_l_ascolto", lambda: None)
    vecchia, porta_mod.porta = porta_mod.porta, nuova
    yield nuova
    nuova.chiudi()
    porta_mod.porta = vecchia


def test_dal_fisso_si_apre_la_porta_e_il_codice_occupa_la_finestra(porta_finta, archivio_pieno):
    from fastapi.testclient import TestClient

    from officina.web.server import app

    fisso = TestClient(app, client=("127.0.0.1", 51000))
    risposta = fisso.post("/schermo/apri", follow_redirects=False)
    assert risposta.headers["location"] == "/schermo/porta"
    assert porta_finta.aperta
    pagina = fisso.get("/schermo/porta").text
    codice, _ = porta_finta.codice()
    assert all(f"<span>{cifra}</span>" in pagina for cifra in codice)
    assert fisso.get("/api/schermo").json()["codice"] == codice
    assert "Il portatile" in fisso.get("/impostazioni").text

    fisso.post("/schermo/chiudi-porta", follow_redirects=False)
    assert not porta_finta.aperta


def test_mentre_il_portatile_e_collegato_il_fisso_resta_coperto(porta_finta, archivio_pieno):
    from fastapi.testclient import TestClient

    from officina.web.server import app

    porta_finta.apri()
    porta_finta._sessioni["prova"] = porta_mod._Sessione("abc")
    fisso = TestClient(app, client=("127.0.0.1", 51000))
    risposta = fisso.get("/", headers={"accept": "text/html"}, follow_redirects=False)
    assert risposta.headers["location"] == "/schermo/coperta"
    assert "Chiudi il collegamento" in fisso.get("/schermo/coperta").text

    fisso.post("/schermo/stacca", follow_redirects=False)
    assert porta_finta.collegato() is None
    assert fisso.get("/", headers={"accept": "text/html"},
                     follow_redirects=False).status_code == 200


def test_il_portatile_non_vede_il_codice_ne_comanda_la_porta(porta_finta, archivio_pieno):
    from fastapi.testclient import TestClient

    porta_finta.apri()
    porta_finta._sessioni["prova"] = porta_mod._Sessione("abc")
    portatile = TestClient(porta_mod.app_della_porta)
    con = {"x-schermo-sessione": "prova"}
    assert portatile.get("/api/schermo", headers=con).status_code != 200
    assert portatile.post("/schermo/apri", headers=con).status_code == 404
    assert portatile.get("/stato", headers=con).status_code == 200


def test_quando_il_portatile_si_chiude_il_fisso_si_scopre(porta):
    fisso = _abbina(porta)
    ponte = collega.Ponte(fisso, collega.entra(fisso, "cavallo-batteria"))
    assert porta.collegato() is not None
    collega.esci(ponte)
    assert porta.collegato() is None


def test_il_portatile_vede_il_programma_del_fisso(porta_finta, archivio_pieno, monkeypatch):
    from fastapi.testclient import TestClient

    from officina.web import server
    from officina.web.strade import comune

    class Finto:
        def stato_del_programma(self):
            return {"versione": "fisso", "motori": {"mancano": []}}

        def salva_la_chiave(self, valore):
            return {"salvata": valore}

    monkeypatch.setattr(comune, "programma_di_qui", Finto())
    porta_finta.apri()
    porta_finta._sessioni["prova"] = porta_mod._Sessione("abc")
    portatile = TestClient(porta_mod.app_della_porta)
    con = {"x-schermo-sessione": "prova"}
    assert portatile.post("/api/programma/stato_del_programma",
                          headers=con).json()["versione"] == "fisso"
    assert portatile.post("/api/programma/salva_la_chiave", headers=con,
                          json=["hf_x"]).json() == {"salvata": "hf_x"}
    assert portatile.post("/api/programma/spegni_il_forziere", headers=con).status_code == 404
    fisso = TestClient(server.app, client=("127.0.0.1", 51000))
    assert fisso.post("/api/programma/stato_del_programma").status_code == 404


def test_quando_il_fisso_si_aggiorna_il_portatile_vede_i_passi_e_si_ricollega(porta, archivio_pieno):
    fisso = _abbina(porta)
    avvisato = []
    ponte = collega.Ponte(fisso, collega.entra(fisso, "cavallo-batteria"),
                          password="cavallo-batteria",
                          quando_aggiorna=lambda: avvisato.append(True))
    ponte.parti()
    try:
        porta_locale = int(ponte.indirizzo.rsplit(":", 1)[1].strip("/"))
        vicino = http.client.HTTPConnection("127.0.0.1", porta_locale, timeout=30)

        def chiedi(percorso, pagina=False):
            vicino.request("GET", percorso, headers={"accept": "text/html"} if pagina else {})
            risposta = vicino.getresponse()
            return risposta.status, risposta.read()

        assert chiedi("/stato", pagina=True)[0] == 200
        porta.chiusura = {"passi": ["Fermo i lavori in corso", "Salvo le ultime cose",
                                    "Installo l'aggiornamento", "Riparto"], "fatti": 1}
        stato, corpo = chiedi("/api/stato")
        assert stato == 503
        assert avvisato == [True]
        stato, corpo = chiedi("/galleria", pagina=True)
        assert b"Il fisso si sta aggiornando" in corpo

        dati = json.loads(chiedi("/__schermo/aggiorna/stato")[1])
        assert dati["passi"][0] == "Fermo i lavori in corso"
        assert dati["fatti"] == 1
        assert not dati["avviso"] and not dati["scelta"]

        porta.chiudi()
        dati = json.loads(chiedi("/__schermo/aggiorna/stato?subito=1")[1])
        assert dati["fatti"] == 2
        assert "vai" not in dati

        ponte.aggiornamento["partito"] -= collega.AVVISO_DOPO
        dati = json.loads(chiedi("/__schermo/aggiorna/stato")[1])
        assert dati["avviso"] and not dati["scelta"]

        porta.apri(_Password("cavallo-batteria"))
        dati = json.loads(chiedi("/__schermo/aggiorna/stato?subito=1")[1])
        assert dati["vai"] == "/galleria"
        assert porta.collegato() is not None
        assert chiedi("/stato", pagina=True)[0] == 200
    finally:
        ponte.ferma()


def test_se_il_fisso_non_torna_il_portatile_torna_alla_scelta(porta, archivio_pieno):
    fisso = _abbina(porta)
    ponte = collega.Ponte(fisso, collega.entra(fisso, "cavallo-batteria"))
    ponte._comincia_l_aggiornamento()
    porta.chiudi()
    ponte.aggiornamento["partito"] -= collega.SCELTA_DOPO
    dati = ponte.stato_dell_aggiornamento(subito=True)
    assert dati["scelta"] is True


def test_dopo_aggiorna_il_portatile_si_accorge_da_solo_che_il_fisso_si_chiude(porta, archivio_pieno,
                                                                               monkeypatch):
    monkeypatch.setattr(collega, "OGNI_QUANTO_GUARDO", 0.05)
    fisso = _abbina(porta)
    avvisato = []
    ponte = collega.Ponte(fisso, collega.entra(fisso, "cavallo-batteria"),
                          quando_aggiorna=lambda: avvisato.append(True))
    try:
        ponte.guarda_l_aggiornamento()
        time.sleep(0.3)
        assert avvisato == []
        porta.chiusura = {"passi": ["Fermo i lavori in corso", "Riparto"], "fatti": 0}
        for _ in range(100):
            if avvisato:
                break
            time.sleep(0.05)
        assert avvisato == [True]
        assert ponte.aggiornamento is not None
    finally:
        ponte.ferma()
