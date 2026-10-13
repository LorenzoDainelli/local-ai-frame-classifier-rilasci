from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from officina.modello import dispositivi, telefoni
from officina.schermo import porta as porta_mod

QUESTO_COMPUTER = "Questa scelta si fa dal computer dove gira il programma."
DISPOSITIVO = "192.168.1.40"


def _cliente(indirizzo: str) -> TestClient:
    from officina.web.server import app

    return TestClient(app, client=(indirizzo, 51000))


@pytest.fixture
def locale(archivio_pieno):
    return _cliente("127.0.0.1")


@pytest.fixture
def remoto(archivio_pieno):
    archivio_pieno.imposta("accesso_dalla_rete", True)
    _cliente(DISPOSITIVO).get("/")
    with archivio_pieno.scrittura() as connessione:
        macchina = dispositivi.elenco(connessione)[0]
        dispositivi.decidi(connessione, macchina["id"], "approvato", "tablet")
    cliente = _cliente(DISPOSITIVO)
    assert cliente.get("/").status_code == 200
    return cliente


@pytest.fixture
def porta_finta(tmp_path, monkeypatch):
    monkeypatch.setenv("OFFICINA_CASA_PROGRAMMA", str(tmp_path / "casa"))
    nuova = porta_mod.Porta()
    monkeypatch.setattr(nuova, "_accendi_il_servitore", lambda: None)
    monkeypatch.setattr(nuova, "_accendi_l_ascolto", lambda: None)
    vecchia, porta_mod.porta = porta_mod.porta, nuova
    yield nuova
    nuova.chiudi()
    porta_mod.porta = vecchia


class _Portatile:

    def __init__(self, porta):
        porta.apri()
        porta._sessioni["prova"] = porta_mod._Sessione("abc")
        self._cliente = TestClient(porta_mod.app_della_porta)
        self._intestazioni = {"x-schermo-sessione": "prova"}

    def get(self, dove, **resto):
        return self._cliente.get(dove, headers={**self._intestazioni, **resto.pop("headers", {})},
                                 **resto)

    def post(self, dove, **resto):
        return self._cliente.post(dove, headers={**self._intestazioni, **resto.pop("headers", {})},
                                  follow_redirects=False, **resto)


@pytest.fixture
def portatile(porta_finta, archivio_pieno):
    return _Portatile(porta_finta)


DA_FARE_SOLO_QUI = [
    ("post", "/impostazioni/azzera-addestramento", {}),
    ("post", "/impostazioni/riporta-i-valori", {}),
    ("post", "/impostazioni/dispositivo/1", {"stato": "approvato"}),
    ("post", "/impostazioni", {"accesso_dalla_rete": "on"}),
    ("post", "/api/impostazione", {"chiave": "accesso_dalla_rete", "valore": "1"}),
    ("post", "/api/impostazione", {"chiave": "porta_del_portatile", "valore": "1"}),
    ("post", "/api/impostazione", {"chiave": "blocco_dopo_minuti", "valore": "0"}),
    ("post", "/api/impostazione", {"chiave": "cartella_raccolta", "valore": "/tmp/fuori"}),
    ("post", "/forziere/accendi", {"password": "a" * 12, "ancora": "a" * 12, "su_carta": "1"}),
    ("post", "/schermo/apri", {}),
    ("post", "/schermo/chiudi-porta", {}),
    ("post", "/schermo/stacca", {}),
    ("post", "/schermo/dimentica/abc", {}),
    ("get", "/schermo/porta", None),
    ("get", "/schermo/coperta", None),
    ("get", "/api/schermo", None),
    ("post", "/importazione/cartella", {"percorso": "/tmp/una-cartella-finta"}),
    ("post", "/raccolta/conta", {"dove": "/tmp/una-cartella-finta"}),
    ("post", "/raccolta/parti", {}),
    ("post", "/sincronia/dove", {"cartella": "/tmp/una-cartella-finta"}),
    ("post", "/sincronia/costruisci", {"password": "x", "ancora": "x"}),
    ("post", "/sincronia/applica", {"quale": "/tmp/una-cartella-finta"}),
    ("post", "/telefono/1/dove", {"cartella": "/tmp/una-cartella-finta"}),
    ("post", "/telefono/1/parti", {}),
    ("post", "/persone/1/insegna", {"cartella": "/tmp/una-cartella-finta"}),
    ("post", "/giro/parti", {}),
]


def _chiama(cliente, metodo, dove, dati):
    if metodo == "get":
        return cliente.get(dove, headers={"accept": "application/json"}, follow_redirects=False)
    return cliente.post(dove, data=dati, headers={"accept": "application/json"},
                        follow_redirects=False)


@pytest.mark.parametrize("metodo,dove,dati", DA_FARE_SOLO_QUI)
def test_un_dispositivo_approvato_non_comanda_il_programma(remoto, metodo, dove, dati):
    risposta = _chiama(remoto, metodo, dove, dati)
    assert risposta.status_code == 403, (dove, risposta.text[:200])
    assert risposta.json()["messaggio"] == QUESTO_COMPUTER


@pytest.mark.parametrize("metodo,dove,dati", DA_FARE_SOLO_QUI)
def test_il_portatile_usato_come_schermo_non_comanda_il_programma(portatile, metodo, dove, dati):
    if metodo == "get":
        risposta = portatile.get(dove, headers={"accept": "application/json"},
                                 follow_redirects=False)
    else:
        risposta = portatile.post(dove, data=dati, headers={"accept": "application/json"})
    if dove.startswith("/schermo/"):
        assert risposta.status_code in (403, 404), (dove, risposta.text[:200])
        return
    assert risposta.status_code == 403, (dove, risposta.text[:200])
    assert "messaggio" in risposta.json()


def test_le_pagine_del_portatile_dicono_a_voce_che_si_fa_dal_computer(remoto):
    for dove in ("/schermo/porta", "/schermo/coperta"):
        risposta = remoto.get(dove, headers={"accept": "text/html"}, follow_redirects=False)
        assert risposta.status_code == 403
        assert QUESTO_COMPUTER in risposta.text
        assert "<html" in risposta.text


def _quante_cartelle(archivio) -> int:
    with archivio.lettura() as connessione:
        return connessione.execute("SELECT count(*) AS q FROM cartelle_sorgente").fetchone()["q"]


def test_un_dispositivo_che_non_puo_non_cambia_niente(remoto, archivio_pieno):
    assert _cliente("192.168.1.41").get("/").status_code == 403
    with archivio_pieno.lettura() as connessione:
        altro = next(d for d in dispositivi.elenco(connessione)
                     if d["indirizzo"] == "192.168.1.41")
    cartelle_prima = _quante_cartelle(archivio_pieno)
    for dove, dati in ((f"/impostazioni/dispositivo/{altro['id']}", {"stato": "approvato"}),
                       ("/api/impostazione", {"chiave": "blocco_dopo_minuti", "valore": "5"}),
                       ("/importazione/cartella", {"percorso": "/tmp/una-cartella-finta"})):
        assert remoto.post(dove, data=dati, follow_redirects=False).status_code == 403
    with archivio_pieno.lettura() as connessione:
        stato = next(d for d in dispositivi.elenco(connessione)
                     if d["indirizzo"] == "192.168.1.41")["stato"]
    assert stato == "in_attesa"
    assert _quante_cartelle(archivio_pieno) == cartelle_prima
    assert archivio_pieno.impostazione("blocco_dopo_minuti") == 0
    assert archivio_pieno.impostazione("accesso_dalla_rete") is True
    assert _cliente("192.168.1.41").get("/").status_code == 403


def test_chi_non_e_il_computer_non_sa_se_un_percorso_esiste(remoto, tmp_path):
    esiste = tmp_path / "c-e"
    esiste.mkdir()
    file = tmp_path / "un-file.txt"
    file.write_text("x")
    detti = set()
    for percorso in (esiste, file, tmp_path / "non-c-e"):
        risposta = remoto.post("/importazione/cartella", data={"percorso": str(percorso)},
                               headers={"accept": "application/json"}, follow_redirects=False)
        assert risposta.status_code == 403
        detti.add(risposta.text)
    assert len(detti) == 1


def test_il_computer_stesso_comanda_ancora(locale, archivio_pieno, tmp_path):
    risposta = locale.post("/api/impostazione",
                           data={"chiave": "blocco_dopo_minuti", "valore": "15"})
    assert risposta.status_code == 200
    assert archivio_pieno.impostazione("blocco_dopo_minuti") == 15

    cartella = tmp_path / "foto-finte"
    cartella.mkdir()
    prima = _quante_cartelle(archivio_pieno)
    risposta = locale.post("/importazione/cartella", data={"percorso": str(cartella)},
                           follow_redirects=False)
    assert risposta.status_code == 303
    assert _quante_cartelle(archivio_pieno) == prima + 1

    assert locale.post("/impostazioni/riporta-i-valori",
                       follow_redirects=False).status_code == 303
    assert archivio_pieno.impostazione("blocco_dopo_minuti") == 0
    assert locale.get("/api/schermo").status_code == 200


def test_le_scelte_di_tutti_i_giorni_restano_aperte_al_dispositivo_approvato(remoto,
                                                                             archivio_pieno):
    assert remoto.post("/api/impostazione",
                       data={"chiave": "griglia_mosaico", "valore": ""}).status_code == 200
    assert archivio_pieno.impostazione("griglia_mosaico") is False
    assert remoto.get("/").status_code == 200
    assert remoto.get("/impostazioni").status_code == 200
    assert remoto.get("/importazione").status_code == 200
    assert remoto.get("/fuori").status_code == 200
    assert remoto.get("/api/importazione").status_code == 200
    assert remoto.post("/api/aspetto", data={"chiave": "tema", "valore": "scuro"}
                       ).status_code == 200


def test_il_portatile_vede_ancora_le_pagine_e_il_programma_del_fisso(portatile, monkeypatch):
    from officina.web.strade import comune

    class Finto:
        def stato_del_programma(self):
            return {"versione": "fisso"}

        def aggiorna_adesso(self):
            return {"partito": True}

        def salva_la_chiave(self, valore):
            return {"salvata": True}

    monkeypatch.setattr(comune, "programma_di_qui", Finto())
    assert portatile.get("/stato").status_code == 200
    assert portatile.get("/impostazioni").status_code == 200
    assert portatile.post("/api/programma/stato_del_programma").json() == {"versione": "fisso"}
    assert portatile.post("/api/programma/aggiorna_adesso").json() == {"partito": True}
    assert portatile.post("/api/programma/salva_la_chiave", json=["hf_x"]).json() == {
        "salvata": True}


def test_chi_comanda_la_porta_dal_fisso_ma_non_dal_portatile(porta_finta, archivio_pieno):
    fisso = _cliente("127.0.0.1")
    portatile = _Portatile(porta_finta)
    assert portatile.get("/api/schermo", headers={"accept": "application/json"}).status_code == 403
    codice, _ = porta_finta.codice()
    assert fisso.get("/api/schermo").json()["codice"] == codice


def _pagine(cliente, dove):
    return cliente.get(dove, headers={"accept": "text/html"}).text


def test_il_dispositivo_approvato_non_vede_i_tasti_che_non_puo_premere(remoto, archivio_pieno):
    with archivio_pieno.scrittura() as connessione:
        numero = telefoni.crea(connessione, "Pippo", "android")
    pagina = _pagine(remoto, "/impostazioni")
    for traccia in ("/impostazioni/dispositivo/", "/forziere/accendi",
                    "/impostazioni/azzera-addestramento", "/impostazioni/riporta-i-valori",
                    'data-chiave="accesso_dalla_rete"', 'data-chiave="blocco_dopo_minuti"'):
        assert traccia not in pagina, traccia
    assert QUESTO_COMPUTER in pagina

    for dove, tracce in ((f"/fuori?quale={numero}",
                          (f"/telefono/{numero}/dove", f"/telefono/{numero}/parti")),
                         ("/fuori?dove=computer", ("/sincronia/dove", "/sincronia/costruisci")),
                         ("/fuori?dove=portatile", ("/schermo/apri",))):
        fuori = _pagine(remoto, dove)
        for traccia in tracce:
            assert traccia not in fuori, (dove, traccia)
        assert QUESTO_COMPUTER in fuori, dove

    importazione = _pagine(remoto, "/importazione")
    assert 'action="/raccolta/conta"' not in importazione
    assert 'action="/importazione/cartella" class="cn-scrivi" id="cn-modulo" ' \
           'data-cartella-nuova hidden' in importazione


def test_il_computer_stesso_vede_tutti_i_tasti(locale, archivio_pieno):
    with archivio_pieno.scrittura() as connessione:
        numero = telefoni.crea(connessione, "Pippo", "android")
        dispositivi.registra_contatto(connessione, "192.168.1.99")
    pagina = _pagine(locale, "/impostazioni")
    for traccia in ("/impostazioni/dispositivo/", "/forziere/accendi",
                    "/impostazioni/azzera-addestramento", "/impostazioni/riporta-i-valori",
                    'data-chiave="accesso_dalla_rete"', 'data-chiave="blocco_dopo_minuti"'):
        assert traccia in pagina, traccia

    for dove, tracce in ((f"/fuori?quale={numero}",
                          (f"/telefono/{numero}/dove", f"/telefono/{numero}/parti")),
                         ("/fuori?dove=computer", ("/sincronia/dove", "/sincronia/costruisci")),
                         ("/fuori?dove=portatile", ("/schermo/apri",))):
        fuori = _pagine(locale, dove)
        for traccia in tracce:
            assert traccia in fuori, (dove, traccia)

    importazione = _pagine(locale, "/importazione")
    assert 'action="/raccolta/conta"' in importazione
    assert 'id="cn-modulo" data-cartella-nuova>' in importazione


def test_il_portatile_non_vede_i_tasti_del_fisso(portatile):
    pagina = portatile.get("/impostazioni", headers={"accept": "text/html"}).text
    assert "/forziere/accendi" not in pagina
    assert QUESTO_COMPUTER in pagina


@pytest.mark.parametrize("scritto", [
    "\\\\server\\condivisa\\pacchetti",
    "//server/condivisa/pacchetti",
    "\\/server/condivisa",
    "/\\server\\condivisa",
    '"\\\\server\\condivisa"',
    "\\\\?\\UNC\\server\\condivisa",
])
def test_la_cartella_dei_pacchetti_non_si_scrive_come_percorso_di_rete(locale, archivio_pieno,
                                                                      scritto):
    risposta = locale.post("/sincronia/dove", data={"cartella": scritto},
                           headers={"accept": "application/json"}, follow_redirects=False)
    assert risposta.status_code == 400
    assert "percorso di rete" in risposta.json()["messaggio"]
    with archivio_pieno.lettura() as connessione:
        from officina.web import sincronia as sincronia_web

        assert sincronia_web.cartella_ricordata(connessione) == ""


def test_la_cartella_del_telefono_non_si_scrive_come_percorso_di_rete(locale, archivio_pieno):
    with archivio_pieno.scrittura() as connessione:
        numero = telefoni.crea(connessione, "Pippo", "android")
    risposta = locale.post(f"/telefono/{numero}/dove", data={"cartella": "\\\\server\\x"},
                           headers={"accept": "application/json"}, follow_redirects=False)
    assert risposta.status_code == 400
    assert "percorso di rete" in risposta.json()["messaggio"]


def test_una_cartella_di_rete_scelta_col_selettore_passa(locale, archivio_pieno, monkeypatch):
    from officina.web import sfoglia
    from officina.web import sincronia as sincronia_web

    scelta = "\\\\nas\\foto\\pacchetti"
    monkeypatch.setattr(sfoglia, "si_puo", lambda: True)
    monkeypatch.setattr(sfoglia, "scegli_cartella", lambda da_dove=None: scelta)
    assert locale.post("/api/sfoglia-cartella").json() == {"percorso": scelta}
    risposta = locale.post("/sincronia/dove", data={"cartella": scelta}, follow_redirects=False)
    assert risposta.status_code == 303
    with archivio_pieno.lettura() as connessione:
        assert sincronia_web.cartella_ricordata(connessione) == scelta


def test_una_cartella_normale_dei_pacchetti_passa(locale, archivio_pieno, tmp_path):
    from officina.web import sincronia as sincronia_web

    risposta = locale.post("/sincronia/dove", data={"cartella": str(tmp_path)},
                           follow_redirects=False)
    assert risposta.status_code == 303
    with archivio_pieno.lettura() as connessione:
        assert sincronia_web.cartella_ricordata(connessione) == str(tmp_path)


PAGINE = ("/", "/impostazioni", "/importazione", "/fuori", "/fuori?dove=computer",
          "/fuori?dove=portatile", "/benvenuto", "/benvenuto/chiave", "/benvenuto/cartella",
          "/benvenuto/pronto", "/persone", "/stato")


@pytest.mark.parametrize("dove", PAGINE)
def test_le_pagine_si_aprono_da_tutti_e_due_i_lati(locale, remoto, dove):
    assert locale.get(dove, headers={"accept": "text/html"}).status_code == 200
    assert remoto.get(dove, headers={"accept": "text/html"}).status_code == 200


@pytest.mark.parametrize("nome", ["persona.html", "blocco.html", "fuori.html", "_portatile.html",
                                  "_cartella_nuova.html", "importazione.html",
                                  "impostazioni.html", "benvenuto.html",
                                  "benvenuto-pronto.html"])
def test_i_modelli_ritoccati_si_compilano(nome):
    from officina.web.strade import base

    base.pagine.env.get_template(nome)
