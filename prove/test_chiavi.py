from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from officina import chiavi

PASSWORD = "tre parole che ricordo"
NUOVA = "quattro parole nuove sempre"
SEGRETA = ("-----BEGIN PRIV" "ATE KEY-----\nMC4CAQAwBQYDK2VwBCIEIprova\n"
           "-----END PRIV" "ATE KEY-----")


@pytest.fixture
def cliente(archivio):
    from officina.web.server import app

    return TestClient(app, client=("127.0.0.1", 51000))


@pytest.fixture
def con_forziere(cliente):
    risposta = cliente.post("/forziere/accendi", data={
        "password": PASSWORD, "ancora": PASSWORD, "su_carta": "1"},
        follow_redirects=False)
    assert risposta.status_code == 303
    return cliente


def _radice():
    from officina.archivio import accesso

    return accesso.aperto().dove.radice


def test_senza_forziere_le_chiavi_non_si_tengono(cliente):
    testo = cliente.get("/chiavi").text
    assert "il forziere è spento" in testo
    assert 'action="/chiavi"' not in testo
    risposta = cliente.post("/chiavi/aggiungi", data={
        "password": PASSWORD, "nome": "prova", "testo": SEGRETA})
    assert "il forziere è spento" in risposta.text
    assert not chiavi.ci_sono(_radice())


def test_si_salva_si_vede_si_toglie(con_forziere):
    cliente = con_forziere
    assert 'href="/chiavi"' in cliente.get("/impostazioni").text
    vuota = cliente.post("/chiavi", data={"password": PASSWORD})
    assert "ancora nessuna chiave." in vuota.text
    assert vuota.headers["cache-control"] == "no-store"

    salvata = cliente.post("/chiavi/aggiungi", data={
        "password": PASSWORD, "nome": "Chiave firma", "testo": SEGRETA + "\r\n"})
    assert "Chiave salvata nel forziere." in salvata.text
    assert "MC4CAQAwBQYDK2VwBCIEIprova" in salvata.text

    grezzo = (_radice() / chiavi.NOME_DEL_FILE).read_bytes()
    assert b"MC4CAQAw" not in grezzo and b"Chiave firma" not in grezzo

    nascosta = cliente.get("/chiavi").text
    assert "MC4CAQAwBQYDK2VwBCIEIprova" not in nascosta

    rivista = cliente.post("/chiavi", data={"password": PASSWORD}).text
    assert "Chiave firma" in rivista and "MC4CAQAwBQYDK2VwBCIEIprova" in rivista
    assert chiavi.leggi(_radice(), PASSWORD)[0]["testo"] == SEGRETA

    tolta = cliente.post("/chiavi/togli",
                         data={"password": PASSWORD, "nome": "Chiave firma"})
    assert "Chiave tolta." in tolta.text
    assert chiavi.leggi(_radice(), PASSWORD) == []


def test_con_la_password_sbagliata_non_si_vede_e_non_si_cambia(con_forziere):
    cliente = con_forziere
    chiavi.aggiungi(_radice(), PASSWORD, "Chiave firma", SEGRETA)
    for strada, dati in (("/chiavi", {}),
                         ("/chiavi/aggiungi", {"nome": "altra", "testo": "x"}),
                         ("/chiavi/togli", {"nome": "Chiave firma"})):
        risposta = cliente.post(strada,
                                data={"password": "non è questa la password", **dati})
        assert "Questa non è la password del forziere." in risposta.text
        assert "MC4CAQAwBQYDK2VwBCIEIprova" not in risposta.text
    assert [v["nome"] for v in chiavi.leggi(_radice(), PASSWORD)] == ["Chiave firma"]


def test_nomi_doppi_e_campi_vuoti_si_dicono(con_forziere):
    cliente = con_forziere
    chiavi.aggiungi(_radice(), PASSWORD, "Chiave firma", SEGRETA)
    doppia = cliente.post("/chiavi/aggiungi", data={
        "password": PASSWORD, "nome": "Chiave firma", "testo": "altro"})
    assert "già una chiave con questo nome." in doppia.text
    vuota = cliente.post("/chiavi/aggiungi", data={
        "password": PASSWORD, "nome": "vuota", "testo": "  "})
    assert "Incolla la chiave" in vuota.text
    assert len(chiavi.leggi(_radice(), PASSWORD)) == 1


def test_cambiata_la_password_del_forziere_le_chiavi_si_richiudono(con_forziere,
                                                                    monkeypatch):
    from officina import forziere

    cliente = con_forziere
    radice = _radice()
    chiavi.aggiungi(radice, PASSWORD, "Chiave firma", SEGRETA)
    monkeypatch.setattr(forziere.Forziere, "la_password_e_giusta",
                        lambda self, password: password == NUOVA)
    chiesta = cliente.post("/chiavi", data={"password": NUOVA}).text
    assert "Le chiavi hanno la password di prima" in chiesta
    sbagliata = cliente.post("/chiavi/rinnova", data={
        "password": NUOVA, "vecchia": "neanche questa va bene"}).text
    assert "Neanche questa password apre le chiavi." in sbagliata
    assert chiavi.leggi(radice, PASSWORD)[0]["testo"] == SEGRETA
    giusta = cliente.post("/chiavi/rinnova",
                          data={"password": NUOVA, "vecchia": PASSWORD}).text
    assert "MC4CAQAwBQYDK2VwBCIEIprova" in giusta
    assert chiavi.leggi(radice, NUOVA)[0]["testo"] == SEGRETA
    with pytest.raises(chiavi.ScritteConUnaltraPassword):
        chiavi.leggi(radice, PASSWORD)


def test_il_forziere_porta_con_se_le_chiavi(con_forziere):
    from officina import forziere
    from officina.archivio import accesso

    chiavi.aggiungi(_radice(), PASSWORD, "Chiave firma", SEGRETA)
    dove = accesso.aperto().dove
    accesso.chiudi(con_copia=False)
    cassa = forziere.per(dove)
    cassa.chiudi(PASSWORD)
    assert not chiavi.ci_sono(dove.radice)
    cassa.apri(PASSWORD)
    assert chiavi.leggi(dove.radice, PASSWORD)[0]["testo"] == SEGRETA
