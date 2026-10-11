from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from officina.apprendimento import proposte, rendiconto
from officina.errori import OperazioneNonPermessa
from officina.modello import etichette, fotografie, nodi

from prove.fogli import schermate


@pytest.fixture
def cliente(archivio_misurabile):
    from officina.web import server
    from officina.web.strade import comune

    comune.bottega = proposte.Bottega()
    return TestClient(server.app, client=("127.0.0.1", 51000))


@pytest.fixture
def alberello(archivio):
    connessione = archivio.connessione
    a = nodi.crea(connessione, "nodo_a", None)
    b = nodi.crea(connessione, "nodo_b", a)
    c = nodi.crea(connessione, "nodo_c", b)
    d = nodi.crea(connessione, "nodo_d", b)
    e = nodi.crea(connessione, "nodo_e", None)
    connessione.commit()
    return {"a": a, "b": b, "c": c, "d": d, "e": e, "c!": connessione}


def test_incastrare_fa_scendere_solo_quel_figlio(alberello):
    connessione = alberello["c!"]
    nodi.incastra(connessione, alberello["e"], alberello["c"])

    assert nodi.per_id(connessione, alberello["e"])["genitore_id"] == alberello["b"]
    assert nodi.per_id(connessione, alberello["c"])["genitore_id"] == alberello["e"]
    assert nodi.per_id(connessione, alberello["d"])["genitore_id"] == alberello["b"]


def test_non_si_incastra_sopra_un_proprio_antenato(alberello):
    connessione = alberello["c!"]
    with pytest.raises(OperazioneNonPermessa):
        nodi.incastra(connessione, alberello["b"], alberello["a"])


def test_non_si_mette_un_ramo_dentro_se_stesso(alberello):
    connessione = alberello["c!"]
    with pytest.raises(OperazioneNonPermessa):
        nodi.sposta(connessione, alberello["a"], alberello["c"])


def test_unire_sposta_foto_e_figli_e_archivia_il_primo(archivio, alberello):
    connessione = alberello["c!"]
    connessione.execute(
        "INSERT INTO scatti (genere, origine_data, creato_il) "
        "VALUES ('foto','assente','2026-01-01T00:00:00')")
    connessione.execute(
        "INSERT INTO scatti (genere, origine_data, creato_il) "
        "VALUES ('foto','assente','2026-01-01T00:00:00')")
    primo, secondo = [r[0] for r in connessione.execute("SELECT id FROM scatti")]
    etichette.metti(connessione, primo, alberello["c"], "si", "utente")
    etichette.metti(connessione, secondo, alberello["c"], "si", "utente")
    etichette.metti(connessione, secondo, alberello["d"], "si", "utente")
    connessione.commit()

    fatto = nodi.unisci(connessione, alberello["c"], alberello["d"])

    assert fatto["etichette_spostate"] == 1
    assert etichette.stato_di(connessione, primo, alberello["d"]) == "si"
    assert etichette.stato_di(connessione, primo, alberello["c"]) == "non_deciso"
    assert nodi.per_id(connessione, alberello["c"])["stato"] == "congelato"


def test_non_si_unisce_un_nodo_a_un_proprio_discendente(alberello):
    connessione = alberello["c!"]
    with pytest.raises(OperazioneNonPermessa):
        nodi.unisci(connessione, alberello["b"], alberello["c"])


def test_la_fotografia_contiene_la_forma_e_mai_le_etichette(archivio, alberello):
    connessione = alberello["c!"]
    connessione.execute(
        "INSERT INTO scatti (genere, origine_data, creato_il) "
        "VALUES ('foto','assente','2026-01-01T00:00:00')")
    scatto_id = connessione.execute("SELECT id FROM scatti ORDER BY id LIMIT 1").fetchone()[0]
    etichette.metti(connessione, scatto_id, alberello["c"], "si", "utente")
    connessione.commit()

    numero = fotografie.scatta(connessione, "prova")
    nodi.sposta(connessione, alberello["c"], None)
    connessione.commit()

    fotografie.ripristina(connessione, numero)
    assert nodi.per_id(connessione, alberello["c"])["genitore_id"] == alberello["b"]
    assert etichette.stato_di(connessione, scatto_id, alberello["c"]) == "si"


def test_ripristinare_non_cancella_i_nodi_nati_dopo(alberello):
    connessione = alberello["c!"]
    numero = fotografie.scatta(connessione, "prima")
    nuovo = nodi.crea(connessione, "nodo_nuovo", alberello["a"])
    connessione.commit()

    conseguenze = fotografie.cosa_cambierebbe(connessione, numero)
    assert conseguenze["nati_dopo"] == 1

    fotografie.ripristina(connessione, numero)
    assert nodi.per_id(connessione, nuovo) is not None, \
        "un nodo nato dopo la fotografia resta dov'è"


def test_ne_tiene_solo_le_ultime(alberello, monkeypatch):
    connessione = alberello["c!"]
    monkeypatch.setattr(fotografie, "QUANTE_TENERNE", 3)
    for numero in range(6):
        fotografie.scatta(connessione, f"prova {numero}")
    assert len(fotografie.elenco(connessione, quante=99)) == 3


def test_la_mappa_manda_la_forma_non_le_coordinate(cliente):
    dati = cliente.get("/api/albero").json()
    assert dati["nodi"]
    prima = dati["nodi"][0]
    assert set(prima) == {"id", "genitore", "nome", "esempi", "archiviato", "corsia", "da_solo"}


def test_la_mappa_non_e_piu_una_pagina(cliente):
    risposta = cliente.get("/albero", follow_redirects=False)
    assert risposta.status_code == 303
    assert risposta.headers["location"] == "/officina?albero=1"

    da_foto = cliente.get("/albero?da=foto", follow_redirects=False)
    assert da_foto.headers["location"] == "/?albero=1"


def test_da_fuori_non_si_decide_dove_finisce_il_browser(cliente):
    risposta = cliente.get("/albero?da=https://altrove.example/rubo",
                           follow_redirects=False)
    assert risposta.headers["location"] == "/officina?albero=1"


def test_la_mappa_arriva_come_pezzo_e_non_come_pagina(cliente):
    testo = cliente.get("/api/albero/schermata").text
    assert "<html" not in testo.lower()
    assert "barra-alta" not in testo
    assert 'id="albero-tela"' in testo
    assert 'id="dati-albero"' in testo


def test_il_velo_della_mappa_sta_dove_la_mappa_si_apre(cliente):
    for dove in ("/", "/impostazioni", "/stato", "/importazione"):
        pagina = cliente.get(dove).text
        assert 'id="velo-albero"' in pagina, dove
        assert "data-apri-albero" in pagina, dove


def test_spostare_a_radice_e_annullare(cliente, archivio_misurabile):
    connessione = archivio_misurabile.connessione
    riga = connessione.execute(
        "SELECT id, genitore_id FROM nodi WHERE genitore_id IS NOT NULL LIMIT 1"
    ).fetchone()
    nodo_id, prima = riga["id"], riga["genitore_id"]

    assert cliente.post("/api/albero/sposta", data={
        "nodo_id": nodo_id, "come": "radice"}).status_code == 200
    assert nodi.per_id(connessione, nodo_id)["genitore_id"] is None

    assert cliente.post("/api/albero/rimetti", data={
        "coppie": json.dumps([{"nodo_id": nodo_id, "genitore_id": prima}])
    }).status_code == 200
    assert nodi.per_id(connessione, nodo_id)["genitore_id"] == prima


def test_lasciare_indietro_i_figli(cliente, archivio_misurabile):
    connessione = archivio_misurabile.connessione
    nonno = nodi.crea(connessione, "nodo_nonno", None)
    padre = nodi.crea(connessione, "nodo_padre", nonno)
    figlio = nodi.crea(connessione, "nodo_figlio", padre)
    altrove = nodi.crea(connessione, "nodo_altrove", None)
    connessione.commit()

    cliente.post("/api/albero/sposta", data={
        "nodo_id": padre, "come": "figlio", "destinazione": altrove,
        "con_figli": "0"})
    assert nodi.per_id(connessione, padre)["genitore_id"] == altrove
    assert nodi.per_id(connessione, figlio)["genitore_id"] == nonno, \
        "il figlio lasciato indietro resta dove stava il padre"


def test_ogni_spostamento_lascia_una_fotografia(cliente, archivio_misurabile):
    connessione = archivio_misurabile.connessione
    prima = len(fotografie.elenco(connessione, quante=99))
    nodo_id = connessione.execute(
        "SELECT id FROM nodi WHERE genitore_id IS NOT NULL LIMIT 1").fetchone()[0]
    cliente.post("/api/albero/sposta", data={"nodo_id": nodo_id, "come": "radice"})
    assert len(fotografie.elenco(connessione, quante=99)) == prima + 1


def test_rinominare_non_chiede_e_non_tocca_le_foto(cliente, archivio_misurabile):
    connessione = archivio_misurabile.connessione
    riga = connessione.execute(
        "SELECT nodo_id FROM etichette WHERE stato='si' LIMIT 1").fetchone()
    nodo_id = riga["nodo_id"]
    quante = connessione.execute(
        "SELECT count(*) FROM etichette WHERE nodo_id = ?", (nodo_id,)).fetchone()[0]

    risposta = cliente.post("/api/albero/rinomina",
                            data={"nodo_id": nodo_id, "nome": "nodo_ribattezzato"})
    assert risposta.status_code == 200
    assert nodi.per_id(connessione, nodo_id)["nome"] == "nodo_ribattezzato"
    assert connessione.execute(
        "SELECT count(*) FROM etichette WHERE nodo_id = ?",
        (nodo_id,)).fetchone()[0] == quante


def test_archiviare_e_ripristinare(cliente, archivio_misurabile):
    connessione = archivio_misurabile.connessione
    nodo_id = connessione.execute("SELECT id FROM nodi LIMIT 1").fetchone()[0]

    cliente.post("/api/albero/stato", data={"nodo_id": nodo_id, "stato": "congelato"})
    assert nodi.per_id(connessione, nodo_id)["stato"] == "congelato"

    cliente.post("/api/albero/stato", data={"nodo_id": nodo_id, "stato": "attivo"})
    assert nodi.per_id(connessione, nodo_id)["stato"] == "attivo"


def test_il_pannello_dice_come_sta_non_solo_cosa_e(cliente, archivio_misurabile):
    connessione = archivio_misurabile.connessione
    nodo_id = connessione.execute(
        "SELECT nodo_id FROM etichette WHERE stato='si' LIMIT 1").fetchone()[0]
    dati = cliente.get(f"/api/albero/nodo/{nodo_id}").json()
    for chiave in ("nome", "percorso", "esempi", "figli_sotto", "ultimi", "voto"):
        assert chiave in dati
    assert nodi.per_id(connessione, nodo_id)["nome"] not in dati["percorso"], \
        "il cammino non ripete il nodo stesso, che sta già nel titolo"


def test_la_pagella_divide_in_tre_corsie(archivio_misurabile):
    conto = rendiconto.calcola(archivio_misurabile.connessione)
    assert conto.righe
    for riga in conto.righe:
        assert riga.corsia in ("nutrire", "crescita", "salute")
        assert riga.perche


def test_un_nodo_non_misurabile_finisce_da_nutrire(archivio_misurabile):
    connessione = archivio_misurabile.connessione
    scarso = nodi.crea(connessione, "nodo_scarso", None)
    scatto_id = connessione.execute("SELECT id FROM scatti ORDER BY id LIMIT 1").fetchone()[0]
    etichette.metti(connessione, scatto_id, scarso, "si", "utente")
    connessione.commit()

    conto = rendiconto.calcola(connessione)
    riga = next(r for r in conto.righe if r.nodo_id == scarso)
    assert riga.giudicabile is False
    assert riga.corsia == "nutrire"
    assert riga.azzecca is None


def test_ogni_percentuale_porta_il_numero_grezzo(archivio_misurabile):
    conto = rendiconto.calcola(archivio_misurabile.connessione)
    for riga in conto.righe:
        if riga.giudicabile:
            assert "esempi" in riga.voto.a_parole()


def test_senza_impronte_la_pagella_dice_perche_e_vuota(archivio):
    conto = rendiconto.calcola(archivio.connessione)
    assert conto.righe == []
    assert "impronta" in conto.motivo_vuota


def test_la_coda_dice_cosa_fare_e_dove(archivio_misurabile):
    connessione = archivio_misurabile.connessione
    conto = rendiconto.calcola(connessione, senza_etichetta=7)
    assert conto.coda
    for compito in conto.coda:
        assert compito.testo and compito.perche and compito.dove.startswith("/")


def test_mettere_un_nodo_su_tutta_la_selezione(cliente, archivio_misurabile):
    connessione = archivio_misurabile.connessione
    nodo_id = nodi.crea(connessione, "nodo_in_blocco", None)
    connessione.commit()
    numeri = [r[0] for r in connessione.execute("SELECT id FROM scatti ORDER BY id LIMIT 4")]

    risposta = cliente.post("/scatti/in-blocco", json={
        "azione": "nodo", "scatti": numeri, "nodo_id": nodo_id})
    assert risposta.status_code == 200
    assert risposta.json()["fatti"] == 4
    for numero in numeri:
        assert etichette.stato_di(connessione, numero, nodo_id) == "si"


def test_togliere_in_blocco_non_e_dire_no(cliente, archivio_misurabile):
    connessione = archivio_misurabile.connessione
    nodo_id = nodi.crea(connessione, "nodo_in_blocco", None)
    connessione.commit()
    numeri = [r[0] for r in connessione.execute("SELECT id FROM scatti ORDER BY id LIMIT 3")]

    cliente.post("/scatti/in-blocco", json={
        "azione": "nodo", "scatti": numeri, "nodo_id": nodo_id})
    cliente.post("/scatti/in-blocco", json={
        "azione": "togli_nodo", "scatti": numeri, "nodo_id": nodo_id})
    for numero in numeri:
        assert etichette.stato_di(connessione, numero, nodo_id) == "non_deciso"


def test_in_blocco_su_tutti_i_risultati_del_filtro(cliente, archivio_misurabile):
    connessione = archivio_misurabile.connessione
    nodo_id = nodi.crea(connessione, "nodo_tutti", None)
    connessione.commit()
    quanti = connessione.execute(
        "SELECT count(*) FROM scatti WHERE genere = 'video' "
        "AND fuori_archivio = 0").fetchone()[0]

    risposta = cliente.post("/scatti/in-blocco", json={
        "azione": "nodo", "scatti": [], "tutti_i_risultati": True,
        "filtro": {"genere": "video"}, "nodo_id": nodo_id})
    assert risposta.json()["fatti"] == quanti


def test_una_impostazione_alla_volta_non_azzera_le_altre(cliente, archivio_misurabile):
    archivio_misurabile.imposta("griglia_altezza_riga", 220)
    cliente.post("/api/impostazione", data={"chiave": "griglia_mosaico", "valore": ""})
    assert archivio_misurabile.impostazione("griglia_mosaico") is False
    assert archivio_misurabile.impostazione("griglia_altezza_riga") == 220


def test_una_impostazione_che_non_esiste_viene_rifiutata(cliente):
    risposta = cliente.post("/api/impostazione",
                            data={"chiave": "colore_preferito", "valore": "blu"})
    assert risposta.status_code == 400


def test_i_tipi_non_si_perdono(cliente, archivio_misurabile):
    cliente.post("/api/impostazione",
                 data={"chiave": "quante_proposte", "valore": "8"})
    assert archivio_misurabile.impostazione("quante_proposte") == 8
    cliente.post("/api/impostazione",
                 data={"chiave": "movimento", "valore": "1"})
    assert archivio_misurabile.impostazione("movimento") is True


def test_i_due_tempi_del_movimento_arrivano_davvero_alla_pagina(
        cliente, archivio_misurabile):
    archivio_misurabile.imposta("durata_gesto_ms", 90)
    archivio_misurabile.imposta("durata_scena_ms", 500)
    testo = cliente.get("/impostazioni").text
    assert "--gesto: 90ms" in testo
    assert "--scena: 500ms" in testo


def test_una_impostazione_di_macchina_non_tocca_quella_comune(archivio, monkeypatch):
    monkeypatch.setenv("OFFICINA_MACCHINA", "il-fisso")
    archivio.imposta("intensita_scheda", 100)
    monkeypatch.setenv("OFFICINA_MACCHINA", "lo-zenbook")
    archivio.imposta("intensita_scheda", 20)

    assert archivio.impostazione("intensita_scheda") == 20
    monkeypatch.setenv("OFFICINA_MACCHINA", "il-fisso")
    assert archivio.impostazione("intensita_scheda") == 100


def test_una_macchina_nuova_parte_dal_valore_comune(archivio, monkeypatch):
    archivio.connessione.execute(
        "INSERT OR REPLACE INTO impostazioni (chiave, valore) VALUES "
        "('intensita_scheda', '35')")
    archivio.connessione.commit()
    monkeypatch.setenv("OFFICINA_MACCHINA", "mai-vista-prima")
    assert archivio.impostazione("intensita_scheda") == 35


def test_le_impostazioni_di_un_altra_macchina_non_si_vedono(archivio, monkeypatch):
    monkeypatch.setenv("OFFICINA_MACCHINA", "il-fisso")
    archivio.imposta("intensita_scheda", 90)
    monkeypatch.setenv("OFFICINA_MACCHINA", "lo-zenbook")
    tutte = archivio.tutte_le_impostazioni()
    assert tutte["intensita_scheda"] != 90
    assert not any("@" in chiave for chiave in tutte), \
        "le chiavi con il nome della macchina non escono da qui"


def test_le_impostazioni_comuni_restano_comuni(archivio, monkeypatch):
    monkeypatch.setenv("OFFICINA_MACCHINA", "il-fisso")
    archivio.imposta("quante_proposte", 8)
    monkeypatch.setenv("OFFICINA_MACCHINA", "lo-zenbook")
    assert archivio.impostazione("quante_proposte") == 8


def test_riportare_i_valori_non_tocca_l_albero(cliente, archivio_misurabile):
    connessione = archivio_misurabile.connessione
    quanti = connessione.execute("SELECT count(*) FROM nodi").fetchone()[0]
    etichettate = connessione.execute("SELECT count(*) FROM etichette").fetchone()[0]

    archivio_misurabile.imposta("quante_proposte", 8)
    cliente.post("/impostazioni/riporta-i-valori", follow_redirects=False)

    assert archivio_misurabile.impostazione("quante_proposte") == 5
    assert connessione.execute("SELECT count(*) FROM nodi").fetchone()[0] == quanti
    assert connessione.execute(
        "SELECT count(*) FROM etichette").fetchone()[0] == etichettate


def test_azzerare_l_addestramento_non_tocca_le_etichette(cliente, archivio_misurabile):
    connessione = archivio_misurabile.connessione
    prima = connessione.execute("SELECT count(*) FROM etichette").fetchone()[0]
    risposta = cliente.post("/impostazioni/azzera-addestramento",
                            follow_redirects=False)
    assert risposta.status_code == 303
    assert connessione.execute(
        "SELECT count(*) FROM etichette").fetchone()[0] == prima


def _sorgente(pezzo: str) -> str:
    from pathlib import Path
    import officina
    return (Path(officina.__file__).parent / "web" / "statici" / pezzo).read_text(
        encoding="utf-8")


def test_spegnere_la_pillola_accesa_lascia_vedere_tutte_e_due_le_mappe():
    js = _sorgente("js/mappa_persone.js")

    assert 'mostra(accesa === quale && quale !== "luoghi" ? null : quale)' in js

    assert 'const seCose = quale === "cose" || quale === null' in js
    assert 'const sePersone = quale === "persone" || quale === null' in js


def test_le_due_mappe_insieme_stanno_affiancate_e_non_una_sotto_l_altra():
    css = schermate()
    assert ".mappa.insieme {" in css
    assert "grid-template-columns: 1fr minmax(240px, 340px);" in css


def test_si_vede_quale_pillola_e_accesa():
    css = schermate()
    assert '.mappa-testa .pillola[aria-selected="true"] {' in css


def test_riaprendo_la_mappa_si_torna_sempre_alle_cose():
    js = _sorgente("js/mappa_persone.js")
    assert 'document.addEventListener("albero-chiuso", () => mostra("cose"));' in js
    assert 'let accesa = "cose";' in js
