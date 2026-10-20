from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from officina.archivio.database import uno

from prove.fogli import schermate


@pytest.fixture
def cliente(archivio_pieno):
    from officina.web.server import app

    return TestClient(app, client=("127.0.0.1", 51000))


@pytest.fixture
def cliente_senza_data(archivio_pieno):
    from officina.web.server import app

    with archivio_pieno.scrittura() as connessione:
        connessione.execute(
            "UPDATE scatti SET data_locale = NULL, giorno = NULL "
            "WHERE id = (SELECT min(id) FROM scatti)")
    return TestClient(app, client=("127.0.0.1", 51000))


@pytest.fixture
def cliente_da_fuori(archivio_pieno):
    from officina.web.server import app

    return TestClient(app, client=("203.0.113.7", 51000))


PAGINE = ["/", "/albero", "/albero?da=foto", "/importazione", "/elenchi",
          "/impostazioni", "/stato", "/senza-data", "/senza-data/perche", "/misura/banco",
          "/?da_fare=1", "/?senza_data=1", "/?schermate=1", "/api/griglia",
          "/api/importazione", "/api/impronte", "/api/modelli", "/api/volti",
          "/officina", "/officina?da_fare=1", "/api/nodi", "/api/nodi?cerca=nodo",
          "/api/albero",
          "/persone", "/persone/mazzo", "/persone/cassetto", "/luoghi",
          "/tempo", "/tempo?dal=2024-01-01&al=2024-12-31", "/api/tempo/punti",
          "/api/tempo/zona?zona=-90,-180,90,180", "/api/cerca", "/api/cerca?frase=nodo_1", "/scatto/1",
          "/telefono", "/api/telefono", "/fuori", "/fuori?dove=computer",
          "/benvenuto", "/benvenuto/cartella", "/benvenuto/lavoro",
          "/benvenuto/pronto",
          "/doppioni", "/api/doppioni", "/api/doppioni/gruppi",
          "/api/copia-video", "/api/parole", "/api/riferimento"]


@pytest.mark.parametrize("indirizzo", PAGINE)
def test_le_pagine_rispondono(cliente, indirizzo):
    assert cliente.get(indirizzo).status_code == 200


def test_da_fuori_non_risponde(cliente_da_fuori):
    risposta = cliente_da_fuori.get("/")
    assert risposta.status_code == 403


def test_nessuna_pagina_chiede_niente_a_internet(cliente):
    fuori = re.compile(r'(src|href)\s*=\s*["\'](https?:)?//', re.IGNORECASE)
    for indirizzo in PAGINE:
        testo = cliente.get(indirizzo).text
        assert not fuori.search(testo), f"{indirizzo} punta a un indirizzo esterno"


def test_le_foto_arrivano_in_un_formato_che_il_browser_apre(cliente, archivio_pieno):
    file_id = uno(archivio_pieno.connessione,
                  "SELECT id FROM file_media WHERE genere = 'immagine' LIMIT 1")["id"]

    miniatura = cliente.get(f"/miniatura/{file_id}")
    assert miniatura.status_code == 200
    assert miniatura.headers["content-type"] in ("image/avif", "image/jpeg")

    immagine = cliente.get(f"/immagine/{file_id}?lato=400")
    assert immagine.status_code == 200
    assert immagine.headers["content-type"] in ("image/avif", "image/jpeg")
    assert not immagine.content.startswith(b"\x00\x00\x00\x18ftypheic")


def test_la_griglia_porta_le_proporzioni_vere(cliente):
    dati = cliente.get("/api/griglia").json()
    assert dati["scatti"]
    for scatto in dati["scatti"]:
        assert scatto["proporzione"] > 0


def test_il_filtro_sta_nell_indirizzo(cliente, archivio_pieno):
    from officina.modello import etichette, nodi

    with archivio_pieno.scrittura() as connessione:
        nodo = nodi.crea(connessione, "nodo_filtro")
        scatto = uno(connessione, "SELECT id FROM scatti ORDER BY id LIMIT 1")["id"]
        etichette.metti(connessione, scatto, nodo, "si")

    pagina = cliente.get(f"/?nodo={nodo}")
    assert pagina.status_code == 200
    assert "nodo_filtro" in pagina.text
    dati = cliente.get(f"/api/griglia?nodo={nodo}").json()
    assert len(dati["scatti"]) == 1


def test_mettere_fuori_archivio_lo_toglie_dalla_griglia(cliente, archivio_pieno):
    scatto = uno(archivio_pieno.connessione, "SELECT id FROM scatti ORDER BY id LIMIT 1")["id"]
    prima = len(cliente.get("/api/griglia").json()["scatti"])

    cliente.post(f"/scatto/{scatto}/fuori-archivio", data={"fuori": 1},
                 follow_redirects=False)

    dopo = len(cliente.get("/api/griglia").json()["scatti"])
    assert dopo == prima - 1
    assert uno(archivio_pieno.connessione, "SELECT count(*) AS q FROM scatti "
               "WHERE id = ?", scatto)["q"] == 1


def test_le_correzioni_in_blocco(cliente, archivio_pieno):
    numeri = [s["id"] for s in cliente.get("/api/griglia").json()["scatti"][:3]]
    prima = len(cliente.get("/api/griglia").json()["scatti"])

    esito = cliente.post("/scatti/in-blocco",
                         json={"azione": "fuori_archivio", "scatti": numeri})
    assert esito.status_code == 200 and esito.json()["fatti"] == 3
    assert len(cliente.get("/api/griglia").json()["scatti"]) == prima - 3

    cliente.post("/scatti/in-blocco",
                 json={"azione": "rimetti_in_archivio", "scatti": numeri})
    assert len(cliente.get("/api/griglia").json()["scatti"]) == prima


def test_tutti_i_risultati_significa_tutti_quelli_del_filtro(cliente, archivio_pieno):
    quanti = len(cliente.get("/api/griglia?senza_data=1").json()["scatti"])
    assert quanti > 0

    esito = cliente.post("/scatti/in-blocco", json={
        "azione": "data", "giorno": "2024-07-03",
        "scatti": [], "tutti_i_risultati": True, "filtro": {"senza_data": "1"},
    })
    assert esito.json()["fatti"] == quanti
    assert cliente.get("/api/griglia?senza_data=1").json()["scatti"] == []


def test_un_azione_sconosciuta_non_fa_niente(cliente):
    esito = cliente.post("/scatti/in-blocco", json={"azione": "cancella_tutto",
                                                    "scatti": [1]})
    assert esito.status_code == 400


def test_i_file_spariti_non_portano_via_le_etichette(cliente, archivio_pieno, tmp_path):
    import shutil

    from officina.modello import etichette, file_media, nodi

    connessione = archivio_pieno.connessione
    riga = uno(connessione,
               "SELECT p.id, p.percorso, f.scatto_id FROM percorsi p "
               "JOIN file_media f ON f.id = p.file_id "
               "WHERE (SELECT count(*) FROM percorsi q WHERE q.file_id = f.id) = 1 "
               "LIMIT 1")
    nodo = nodi.crea(connessione, "nodo_prima_che_sparisse")
    etichette.metti(connessione, riga["scatto_id"], nodo, "si")

    da_parte = tmp_path / "altrove.dat"
    shutil.move(riga["percorso"], da_parte)

    cliente.post("/elenchi/controlla-i-file", follow_redirects=False)

    assert uno(connessione, "SELECT presente FROM percorsi WHERE id = ?",
               riga["id"])["presente"] == 0
    assert etichette.stato_di(connessione, riga["scatto_id"], nodo) == "si"
    assert file_media.non_trovati(connessione)

    shutil.move(da_parte, riga["percorso"])
    cliente.post("/elenchi/controlla-i-file", follow_redirects=False)
    assert uno(connessione, "SELECT presente FROM percorsi WHERE id = ?",
               riga["id"])["presente"] == 1


def test_il_primo_avvio_spiega_prima_di_chiedere(archivio):
    from fastapi.testclient import TestClient

    from officina.web import server
    from officina.web.strade import comune

    comune.gia_ripreso = False
    cliente_nuovo = TestClient(server.app, client=("127.0.0.1", 51000))
    risposta = cliente_nuovo.get("/", follow_redirects=False)
    assert risposta.status_code == 303
    assert risposta.headers["location"] == "/benvenuto"

    pagina = cliente_nuovo.get("/benvenuto")
    assert "non sposta" in pagina.text
    assert "scheda di rete spenta" in pagina.text


def test_una_copia_cancellata_non_fa_sparire_lo_scatto(cliente, archivio_pieno, tmp_path):
    import shutil

    from officina.modello import file_media

    connessione = archivio_pieno.connessione
    doppio = uno(connessione,
                 "SELECT f.id, (SELECT p.percorso FROM percorsi p "
                 "              WHERE p.file_id = f.id ORDER BY p.id LIMIT 1) AS primo "
                 "FROM file_media f "
                 "WHERE (SELECT count(*) FROM percorsi q WHERE q.file_id = f.id) > 1 "
                 "LIMIT 1")
    assert doppio, "l'archivio finto contiene dei doppioni"

    shutil.move(doppio["primo"], tmp_path / "via.dat")
    try:
        cliente.post("/elenchi/controlla-i-file", follow_redirects=False)

        spariti = [r["id"] for r in file_media.non_trovati(connessione)]
        assert doppio["id"] not in spariti
        assert file_media.percorso_migliore(connessione, doppio["id"]) is not None
    finally:
        shutil.move(tmp_path / "via.dat", doppio["primo"])


def test_ogni_voce_del_menu_porta_da_qualche_parte(cliente):
    import re

    pagina = cliente.get("/").text
    dentro_il_menu = re.search(r"<nav[^>]*>(.*?)</nav>", pagina, re.S)
    assert dentro_il_menu, "il menu non c'è più: la prova va rifatta"

    indirizzi = re.findall(r'href="(/[^"]*)"', dentro_il_menu.group(1))
    assert len(indirizzi) >= 4, f"solo {len(indirizzi)} voci: qualcosa non torna"
    for indirizzo in indirizzi:
        percorso, _, punto = indirizzo.partition("#")
        risposta = cliente.get(percorso or "/")
        assert risposta.status_code == 200, indirizzo
        if punto:
            assert f'id="{punto}"' in risposta.text, indirizzo


def test_la_barra_ha_quattro_gruppi_e_niente_tendine(cliente):
    import re

    pagina = cliente.get("/").text
    dentro = re.search(r'<nav class="nav-a-voci">(.*?)</nav>', pagina, re.S).group(1)
    gruppi = re.findall(r'<p class="nav-gruppo"><a href="[^"]*">([^<]+)</a>', dentro)
    assert gruppi == ["Lavoro", "Archivio", "Collegamenti"], gruppi
    voci = re.findall(r'<span class="voce-nome">([^<]+)</span>', dentro)
    assert voci == ["Galleria", "Persone", "Luoghi", "Tempo e mappa", "Aggiungi scatti",
                    "Intelligenza artificiale", "Da sistemare", "Etichetta",
                    "Miglioramento", "Ritocco", "Albero dei nodi", "Stato", "Dispositivi"], voci
    assert "<details" not in dentro


def test_le_tre_pagine_fuse_non_esistono_piu(cliente):
    for sparita in ("/pagella", "/misura", "/salute", "/cerca", "/scorciatoie"):
        assert cliente.get(sparita).status_code == 404, sparita


def test_lo_stato_tiene_dentro_tutte_e_tre(cliente):
    pagina = cliente.get("/stato").text
    for punto in ('id="pagella"', 'id="misura"', 'id="salute"'):
        assert punto in pagina, punto
    assert "cosa etichettare adesso" in pagina
    assert "Le impronte" in pagina
    assert "Le copie del database" in pagina


def test_da_guardare_si_raggiunge_sempre(cliente):
    import re

    pagina = cliente.get("/").text
    dentro = re.search(r"<nav[^>]*>(.*?)</nav>", pagina, re.S).group(1)
    assert 'href="/sistemare"' in dentro


def test_gli_scatti_senza_data_accendono_il_segno(cliente_senza_data):
    pagina = cliente_senza_data.get("/officina").text
    assert "da guardare" in pagina


def test_i_tasti_stanno_nelle_impostazioni(cliente):
    pagina = cliente.get("/impostazioni").text
    assert 'id="tasti"' in pagina
    assert "barra spaziatrice" in pagina


def test_nessuno_script_contiene_entita_html(cliente):
    entita = re.compile(r"&(?:#\d+|amp|quot|lt|gt|#x[0-9a-fA-F]+);")
    for indirizzo in PAGINE:
        pagina = cliente.get(indirizzo)
        if "text/html" not in pagina.headers.get("content-type", ""):
            continue
        for pezzo in re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>",
                                pagina.text, re.S):
            if 'type="application/json"' in pezzo[:0]:
                continue
            trovate = entita.findall(pezzo)
            assert not trovate, (
                f"{indirizzo}: dentro uno <script> c'è {trovate[0]}, "
                "che il browser non decodifica e che rompe la riga")


def test_ogni_pagina_ha_uno_script_che_si_legge(cliente):
    for indirizzo in PAGINE:
        pagina = cliente.get(indirizzo)
        if "text/html" not in pagina.headers.get("content-type", ""):
            continue
        for pezzo in re.findall(r"<script(?![^>]*\b(?:src|type)=)[^>]*>(.*?)</script>",
                                pagina.text, re.S):
            for apre, chiude in (("(", ")"), ("{", "}"), ("[", "]")):
                assert pezzo.count(apre) == pezzo.count(chiude), \
                    f"{indirizzo}: parentesi «{apre}» spaiate in uno script"


def test_i_fogli_di_stile_e_gli_script_si_richiedono_sempre(cliente):
    for statico in ("/statici/css/schermate/comune.css", "/statici/js/albero.js",
                    "/statici/js/comune.js"):
        risposta = cliente.get(statico)
        assert risposta.status_code == 200, statico
        assert "no-cache" in risposta.headers.get("cache-control", ""), statico


def test_lo_script_dell_albero_e_gli_altri_si_chiedono_fra_loro(cliente):
    dentro = cliente.get("/statici/js/albero.js").text
    assert "comune.js" in dentro


def test_il_piu_dell_albero_c_e_sempre_e_a_riposo_e_spento(cliente):
    dentro = cliente.get("/statici/js/albero.js").text
    assert "dormiente" in dentro, "il + a riposo non è più distinto"
    assert "n.id === stato.scelto || n.id === stato.sotto" in dentro, \
        "manca il risveglio del + sotto il puntatore"
    foglio = schermate()
    assert ".quadratino.dormiente" in foglio, "il + a riposo non è più spento"


def test_una_foto_della_galleria_si_apre_anche_con_la_tastiera(cliente):
    dentro = cliente.get("/statici/js/griglia.js").text
    assert 'apri.href = `/scatto/${scatto.id}`' in dentro, \
        "la miniatura non è più un collegamento vero"
    assert "_comeSiChiama" in dentro, \
        "il collegamento non ha più un nome per chi non vede la miniatura"
    assert 'evento.target.closest("a.apri")' in dentro, \
        "senza questo, un click sulla miniatura chiede la pagina due volte"

    foglio = schermate()
    assert ".scheda .immagine .apri:focus-visible" in foglio, \
        "il collegamento della miniatura non mostra più l'anello del fuoco"


def test_la_mano_sul_puntatore_la_hanno_solo_i_comandi(cliente):
    foglio = cliente.get("/statici/css/componenti.css").text

    regola = re.compile(r"([^{}]+)\{([^{}]*)\}")
    commento = re.compile(r"/\*.*?\*/", re.DOTALL)
    manine = [" ".join(scelta.split())
              for scelta, corpo in regola.findall(commento.sub(" ", foglio))
              if "cursor: pointer" in corpo and "pillola" in scelta]

    assert manine, "nessuna pillola ha più la mano: ora non si clicca più niente"
    for scelta in manine:
        for pezzo in scelta.split(","):
            ultimo = pezzo.split()[-1]
            assert not ultimo.startswith(".pillola"), (
                f"«{pezzo.strip()}» dà la mano a ogni pillola, anche a "
                "quelle che sono solo un'etichetta")


def test_un_nodo_si_puo_creare_anche_senza_il_mouse(cliente):
    dentro = cliente.get("/statici/js/albero.js").text
    assert "async function creaUnNodoDentro(id)" in dentro, \
        "creare un nodo non è più una cosa sola, chiamabile da due parti"
    assert 'evento.key.toLowerCase() === "n"' in dentro, \
        "la mappa non ha più la lettera per fare un nodo"
    assert "creaUnNodoDentro(stato.scelto || 0)" in dentro, \
        "la N non fa più il nodo dentro quello scelto"
    assert "<b>N</b> = nuovo nodo" in dentro, \
        "la N non è più scritta fra i suggerimenti, e un tasto che non si "\
        "sa che c'è non esiste (regola 23)"

    dove_n = dentro.index('evento.key.toLowerCase() === "n"')
    assert dentro.index("if (inUnCampo) return;") < dove_n, \
        "la N vale anche dentro un campo di testo"


def test_il_conto_degli_scatti_non_e_scritto_due_volte(cliente):
    galleria = cliente.get("/").text
    assert galleria.count("scatti</span>") <= 1, \
        "il conto degli scatti compare più di una volta nella galleria"

    altrove = cliente.get("/stato").text
    assert "scatti</span>" in altrove, \
        "fuori dalla galleria il conto dell'archivio deve restare nella barra"


def test_sopra_la_griglia_non_ci_sono_interruttori_travestiti(cliente):
    galleria = cliente.get("/").text
    assert "interruttore-mosaico" not in galleria
    assert ">mosaico<" not in galleria

    impostazioni = cliente.get("/impostazioni").text
    assert "griglia_mosaico" in impostazioni, \
        "tolto dalla galleria, il mosaico deve restare nelle impostazioni"


def test_il_cursore_della_griglia_sta_sopra_le_foto(cliente):
    testo = cliente.get("/").text
    assert 'id="misura-griglia"' in testo
    assert 'type="range"' in testo
    assert testo.index("fascia-filtri") < testo.index('id="misura-griglia"')
    assert testo.index('id="misura-griglia"') < testo.index('id="griglia"')


def test_il_cursore_parte_dalla_dimensione_scelta(cliente, archivio_pieno):
    archivio_pieno.imposta("griglia_altezza_riga", 220)
    assert 'id="misura-griglia"' in cliente.get("/").text
    assert 'value="220"' in cliente.get("/").text


def test_la_dimensione_delle_schede_e_di_questo_computer(archivio_pieno):
    from officina.impostazioni import SOLO_QUESTA_MACCHINA

    assert "griglia_altezza_riga" in SOLO_QUESTA_MACCHINA


@pytest.fixture
def cliente_coi_doppioni(archivio_pieno):
    from officina.doppioni import decisioni
    from officina.web.server import app

    with archivio_pieno.scrittura() as connessione:
        righe = connessione.execute(
            "SELECT id FROM file_media WHERE genere = 'immagine' "
            "AND scatto_id IS NOT NULL ORDER BY id LIMIT 2").fetchall()
        segno = "f0e1d2c3b4a59687"
        for quale, riga in enumerate(righe):
            connessione.execute(
                "UPDATE file_media SET impronta_occhio = ?, dimensione = ? "
                "WHERE id = ?",
                (segno, 4_000_000 if quale == 0 else 180_000, riga["id"]))
    decisioni.conta_e_scrivi(archivio_pieno)
    return TestClient(app, client=("127.0.0.1", 51000))


def test_l_elenco_dei_doppioni_porta_il_conto(cliente_coi_doppioni):
    dati = cliente_coi_doppioni.get("/api/doppioni/gruppi").json()
    assert dati["conto"] == {"totale": 1, "decisi": 0, "restano": 1}
    gruppo = dati["gruppi"][0]
    assert gruppo["quante"] == 2
    assert gruppo["come"] == "identiche"
    assert gruppo["copie"][0]["peso"] == "4,0 MB"
    assert gruppo["copie"][0]["la_piu_grande"] is True
    assert gruppo["copie"][1]["la_piu_grande"] is False


def test_l_elenco_dei_doppioni_non_si_fa_chiedere_tutto_con_un_numero_negativo(
        archivio_pieno):
    from officina.doppioni import decisioni
    from officina.web.server import app

    with archivio_pieno.scrittura() as connessione:
        righe = connessione.execute(
            "SELECT id FROM file_media WHERE genere = 'immagine' "
            "AND scatto_id IS NOT NULL ORDER BY id LIMIT 6").fetchall()
        assert len(righe) == 6
        lontane = ("0000000000000000", "ffffffffffffffff", "00000000ffffffff")
        for posto, riga in enumerate(righe):
            connessione.execute(
                "UPDATE file_media SET impronta_occhio = ?, dimensione = ? "
                "WHERE id = ?",
                (lontane[posto // 2], 1000 + posto, riga["id"]))
    decisioni.conta_e_scrivi(archivio_pieno)
    cliente = TestClient(app, client=("127.0.0.1", 51000))

    tutti = cliente.get("/api/doppioni/gruppi").json()["gruppi"]
    assert len(tutti) == 3
    for quanti in (-1, 0):
        dati = cliente.get(f"/api/doppioni/gruppi?quanti={quanti}").json()
        assert len(dati["gruppi"]) == 1
    da_capo = cliente.get("/api/doppioni/gruppi?da=-5&quanti=2").json()["gruppi"]
    assert [g["firma"] for g in da_capo] == [g["firma"] for g in tutti[:2]]


def test_la_galleria_mette_il_bollo_e_lo_toglie_quando_hai_deciso(
        cliente_coi_doppioni):
    scatti_con_bollo = [s for s in cliente_coi_doppioni.get("/api/griglia").json()["scatti"]
                        if s["doppia"]]
    assert len(scatti_con_bollo) == 2
    firma = scatti_con_bollo[0]["doppia"]

    assert cliente_coi_doppioni.get(f"/doppioni?gruppo={firma}").status_code == 200

    cliente_coi_doppioni.post("/api/doppioni/diverse", data={"firma": firma})

    dopo = [s for s in cliente_coi_doppioni.get("/api/griglia").json()["scatti"]
            if s["doppia"]]
    assert dopo == []


def test_tenere_una_copia_toglie_l_altra_dalla_griglia_senza_cancellarla(
        cliente_coi_doppioni, archivio_pieno):
    dati = cliente_coi_doppioni.get("/api/doppioni/gruppi").json()
    gruppo = dati["gruppi"][0]
    grande = gruppo["copie"][0]
    piccola = gruppo["copie"][1]

    prima = len(cliente_coi_doppioni.get("/api/griglia?quanti=300").json()["scatti"])
    esito = cliente_coi_doppioni.post(
        "/api/doppioni/tieni",
        data={"firma": gruppo["firma"], "file_id": grande["file_id"]}).json()

    assert esito["spostati"] == 1
    assert esito["conto"]["restano"] == 0
    dopo = len(cliente_coi_doppioni.get("/api/griglia?quanti=300").json()["scatti"])
    assert dopo == prima - 1
    assert uno(archivio_pieno.connessione,
               "SELECT count(*) AS q FROM file_media WHERE id = ?",
               piccola["file_id"])["q"] == 1

    cliente_coi_doppioni.post("/api/doppioni/rimetti", data={"firma": gruppo["firma"]})
    assert len(cliente_coi_doppioni.get(
        "/api/griglia?quanti=300").json()["scatti"]) == prima


def test_i_segni_sulla_scheda_non_si_pestano_i_piedi():

    foglio = schermate()

    def angolo(regola: str) -> tuple[str, str]:
        principio = foglio.index(regola + " {")
        corpo = foglio[principio:foglio.index("}", principio)]
        verso = "sinistra" if "left:" in corpo else "destra"
        alto = "alto" if "top:" in corpo else "basso"
        return (verso, alto)

    angoli = {
        ".scheda .bollo": angolo(".scheda .bollo"),
        ".scheda .segno": angolo(".scheda .segno"),
        ".scheda .scelta": angolo(".scheda .scelta"),
    }
    assert len(set(angoli.values())) == len(angoli), \
        f"due segni nello stesso angolo della scheda: {angoli}"


def test_una_riga_spenta_si_riaccende_anche_senza_il_mouse():

    foglio = schermate()

    principio = foglio.index(".dp-c-r.decisa:hover")
    regola = foglio[principio:foglio.index("}", principio)]
    assert ":focus-within" in regola, (
        "la riga spenta si riaccende col mouse e basta: col tasto di "
        "tabulazione il «Rimetti a posto» resta illeggibile")


def test_quello_che_si_accende_col_mouse_si_accende_anche_col_fuoco():
    from pathlib import Path

    statici = Path(__file__).resolve().parent.parent / "officina" / "web" / "statici"

    perdonate = {".quadratino.dormiente:hover"}

    regola = re.compile(r"([^{}]+)\{([^{}]*)\}")
    colpevoli = []
    for foglio in sorted(statici.glob("css/*.css")):
        testo = foglio.read_text(encoding="utf-8")
        for scelta, corpo in regola.findall(testo):
            scelta = " ".join(scelta.split())
            if ":hover" not in scelta:
                continue
            if "opacity: 1" not in corpo and "opacity:1" not in corpo:
                continue
            if scelta in perdonate:
                continue
            if ":focus-visible" in scelta or ":focus-within" in scelta:
                continue
            colpevoli.append(f"{foglio.name}: {scelta}")

    assert not colpevoli, (
        "si accendono col mouse e non col fuoco, e chi gira il programma "
        "con il tasto di tabulazione non li vede: " + "; ".join(colpevoli))


def test_nessuna_regola_spegne_l_anello_del_fuoco():
    from pathlib import Path

    statici = Path(__file__).resolve().parent.parent / "officina" / "web" / "statici"

    perdonate = {
        ('.campo-cerca input', '.campo-cerca:focus-within'),
        ('.campo-lente input', '.campo-lente:focus-within'),
        ('.cerca-a-parole .cerca-frase', '.cerca-a-parole:focus-within'),
        ('.casa-cercone-frase', '.casa-cercone:focus-within'),
        ('.imp-cerca input:focus', '.imp-cerca:focus-within'),
    }

    regola = re.compile(r"([^{}]+)\{([^{}]*)\}")
    spenti = re.compile(r"outline\s*:\s*(none|0)\b")
    commento = re.compile(r"/\*.*?\*/", re.DOTALL)
    fogli = {}
    for foglio in sorted(statici.glob("css/*.css")):
        testo = commento.sub(" ", foglio.read_text(encoding="utf-8"))
        fogli[foglio.name] = [
            (" ".join(scelta.split()), corpo)
            for scelta, corpo in regola.findall(testo)
        ]

    colpevoli = []
    for nome, regole in fogli.items():
        for scelta, corpo in regole:
            if not spenti.search(corpo):
                continue
            riquadri = {r for campo, r in perdonate if campo == scelta}
            if riquadri:
                for riquadro in riquadri:
                    acceso = any(
                        s == riquadro and "outline: 2px solid var(--fill)" in c
                        for altre in fogli.values() for s, c in altre)
                    assert acceso, (
                        f"«{scelta}» spegne l'anello contando su «{riquadro}», "
                        "che però non lo accende più")
                continue
            colpevoli.append(f"{nome}: {scelta}")

    assert not colpevoli, (
        "spengono l'anello del fuoco, e chi arriva lì con la tastiera non "
        "vede dove sta: " + "; ".join(colpevoli))


def test_nessuna_transizione_si_prende_anche_l_anello_del_fuoco():
    from pathlib import Path

    statici = Path(__file__).resolve().parent.parent / "officina" / "web" / "statici"

    colpevoli = []
    for foglio in sorted(statici.glob("css/*.css")):
        for numero, riga in enumerate(
                foglio.read_text(encoding="utf-8").split("\n"), start=1):
            senza = riga.split("/*")[0]
            if re.search(r"transition\s*:\s*all\b", senza):
                colpevoli.append(f"{foglio.name}:{numero}")
            elif re.search(r"transition[^:]*:[^;]*\boutline\b", senza):
                colpevoli.append(f"{foglio.name}:{numero} (outline)")

    assert not colpevoli, (
        "muovono anche l'anello del fuoco, che deve esserci subito: "
        + "; ".join(colpevoli))


def test_la_data_del_conto_dei_doppioni_e_scritta_in_italiano(cliente_coi_doppioni):
    import re as espressioni

    from officina.doppioni import decisioni

    decisioni.conta_e_scrivi(accesso_aperto())
    testo = cliente_coi_doppioni.get("/doppioni").text
    riga = espressioni.search(r"Contato l'ultima volta il ([^.<]+)", testo)
    assert riga, "la riga del conto non c'è"
    detto = riga.group(1).strip()
    assert not espressioni.match(r"^\d{4}-\d{2}-\d{2}$", detto), (
        f"la data arriva com'è scritta nel database: «{detto}»")
    assert espressioni.match(r"^\d{1,2} [a-z]+ \d{4}$", detto), (
        f"non è una data a parole: «{detto}»")


def accesso_aperto():
    from officina.archivio import accesso

    return accesso.aperto()


def test_l_originale_arriva_bit_per_bit(cliente, archivio_pieno):
    from pathlib import Path

    cartella = Path(archivio_pieno.dove.radice) / "prova-originale"
    cartella.mkdir(parents=True, exist_ok=True)
    dove = cartella / "una_foto.jpg"
    byte = bytes(range(256)) * 40
    dove.write_bytes(byte)

    with archivio_pieno.scrittura() as connessione:
        file_id = connessione.execute(
            "INSERT INTO file_media (impronta, dimensione, genere, ruolo, "
            "aggiunto_il) VALUES ('byte-originale', ?, 'immagine', "
            "'principale', '2026-01-01T00:00:00')", (len(byte),)).lastrowid
        connessione.execute(
            "INSERT INTO percorsi (file_id, percorso, nome, presente, visto_il) "
            "VALUES (?, ?, 'una_foto.jpg', 1, '2026-01-01T00:00:00')",
            (file_id, str(dove)))

    risposta = cliente.get(f"/originale/{file_id}")
    assert risposta.status_code == 200
    assert risposta.content == byte, (
        "quello che esce da «originale» non è il file che sta sul disco")
    assert dove.read_bytes() == byte, "e il file sul disco non è stato toccato"


def test_un_originale_che_non_c_e_dice_di_no_e_non_esplode(cliente):
    assert cliente.get("/originale/999999").status_code == 404


def test_una_live_che_non_c_e_dice_di_no_e_non_esplode(cliente):
    assert cliente.get("/live/999999").status_code == 404


def test_ogni_strada_del_programma_viene_aperta_da_qualcuno():
    from pathlib import Path

    from officina.web.server import tutte_le_strade

    di_fastapi = {"/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}
    strade = sorted({
        rotta.path for rotta in tutte_le_strade()
        if "GET" in getattr(rotta, "methods", set())
        and rotta.path not in di_fastapi
    })

    cartella = Path(__file__).resolve().parent
    tutto_il_provato = "\n".join(
        f.read_text(encoding="utf-8") for f in sorted(cartella.glob("test_*.py")))

    orfane = []
    for strada in strade:
        pezzo = strada.split("{")[0].rstrip("/") or "/"
        if pezzo in tutto_il_provato:
            continue
        orfane.append(strada)

    assert not orfane, (
        "queste strade esistono e nessuna prova le apre: " + ", ".join(orfane))


def test_chi_ha_chiesto_meno_movimento_non_ne_riceve_di_nascosto():
    from pathlib import Path

    foglio = (Path(__file__).resolve().parent.parent / "officina" / "web"
              / "statici" / "css" / "fondamenta.css").read_text(encoding="utf-8")

    import re

    """Le regole del foglio, una per una: selettori e dichiarazioni."""
    senza_commenti = re.sub(r"/\*.*?\*/", " ", foglio, flags=re.DOTALL)
    spegne = [scelta.strip() for scelta, corpo
              in re.findall(r"([^{}]+)\{([^{}]*)\}", senza_commenti)
              if "animation: none !important" in corpo]

    for dove, dentro in (
        ("l'impostazione di sistema", "prefers-reduced-motion"),
        ("l'interruttore del programma", "senza-movimento"),
    ):
        """Per il media query il selettore è `*` e la condizione sta nella
           riga prima; per l'interruttore la condizione sta nel selettore."""
        if dentro == "prefers-reduced-motion":
            principio = senza_commenti.index("@media (prefers-reduced-motion")
            blocco = senza_commenti[principio:senza_commenti.index("\n}\n",
                                                                   principio)]
            regole = [s for s in spegne if s in blocco]
        else:
            regole = [s for s in spegne if dentro in s]

        assert regole, (
            f"con {dove} le animazioni senza fine continuano a girare")
        tutti = " ".join(regole)
        for figlio in ("::before", "::after"):
            assert figlio in tutti, (
                f"con {dove} un'animazione dentro un {figlio} non si ferma: "
                "`*` da solo non prende i figli finti")


def test_nessuno_scorrimento_si_muove_di_nascosto():
    from pathlib import Path

    js = Path(__file__).resolve().parent.parent / "officina" / "web" / "statici" / "js"
    for file in sorted(js.glob("*.js")):
        if file.name == "comune.js":
            continue
        dentro = file.read_text(encoding="utf-8")
        assert '"smooth"' not in dentro and "'smooth'" not in dentro, (
            f"{file.name} chiede uno scorrimento morbido scritto a mano: "
            "chi ha chiesto meno movimento non ha modo di fermarlo")

    comune = (js / "comune.js").read_text(encoding="utf-8")
    principio = comune.index("export function movimentoAcceso()")
    corpo = comune[principio:comune.index("\n}", principio)]
    assert "prefers-reduced-motion" in corpo, (
        "`movimentoAcceso()` guarda solo l'interruttore del programma: "
        "chi lo ha chiesto al sistema operativo non viene ascoltato")


def test_nella_galleria_la_voce_galleria_e_accesa(cliente):
    import re

    pagina = cliente.get("/").text
    accesa = re.search(r'<a class="voce qui" href="([^"]*)"', pagina)
    assert accesa and accesa.group(1) == "/"


def test_le_cose_che_non_si_disfano_si_confermano_tenendo_premuto(cliente):
    pagina = cliente.get("/impostazioni").text
    assert "data-misura-forza" in pagina or 'id="modulo-spegni-forziere"' in pagina
    assert "/statici/js/movimenti_pagine.js" in pagina


def test_la_casella_in_alto_apre_la_galleria_con_i_trovati(cliente, monkeypatch):
    from officina.modello import scatti

    monkeypatch.setattr(scatti, "_cerca_a_parole", lambda connessione, frase: [2, 1])
    pagina = cliente.get("/?parole=al%20mare").text
    assert "«al mare»" in pagina
    assert "avviaGalleria(2)" in pagina
    griglia = cliente.get("/api/griglia?parole=al%20mare").json()
    assert [s["id"] for s in griglia["scatti"]][:2] == [2, 1]


def test_controlla_gli_scatti_rimisura_tutto_e_dice_come_va(cliente):
    import time
    partito = cliente.post("/api/miglioramento/qualita/controlla", json={})
    assert partito.status_code == 200
    for _ in range(100):
        stato = cliente.get("/api/miglioramento/qualita/controllo").json()
        if not stato["sta_lavorando"]:
            break
        time.sleep(0.05)
    assert stato["finito"]
    assert stato["totale"] > 0
    assert stato["fatti"] == stato["totale"]
