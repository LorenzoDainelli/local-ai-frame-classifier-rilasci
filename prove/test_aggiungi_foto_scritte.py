from __future__ import annotations

import html
import re

import pytest

from officina.importazione import annulla, pagina, storico
from officina.importazione.motore import Avanzamento
from officina.web.strade import base

PIENO = {"da_questo_computer": True, "si_puo_sfogliare": False, "gruppi": [],
         "gruppo_ultimo": None, "aggiunta": None, "appena_tolta": None, "tessere": [],
         "tolte": [], "mandate": [], "momento": "pronta", "piano": None, "stato": None,
         "perche_e_ferma": None, "ultima": None, "finita_prima": None}


def _scrivi(nome: str, **dati) -> str:
    return base.pagine.env.get_template(nome).render({**PIENO, **dati})


def _pezzi():
    return base.pagine.env.get_template("_ag_pezzi.html").module


def _conto(numero: int, spariscono: int = 0, restano: int = 0,
           file: int | None = None) -> annulla.Conto:
    return annulla.Conto(numero, f"D:\\Foto\\C{numero}", True,
                         spariscono + restano if file is None else file, spariscono, restano)


def _tessera(numero: int = 1, spariscono: int = 0, restano: int = 0, file=None,
             **cambia) -> pagina.Tessera:
    dati = {"id": numero, "percorso": f"D:\\Foto\\C{numero}", "nome": f"C{numero}",
            "sopra": "D:\\Foto\\", "gruppo_id": None, "gruppo": None,
            "conto": _conto(numero, spariscono, restano, file), "arrivati": "",
            "importata": False, "staccata": ""}
    return pagina.Tessera(**{**dati, **cambia})


def _tolta(numero: int = 1, spariscono: int = 0, restano: int = 0, file=None,
           quando: str = "3 mar") -> pagina.Tolta:
    return pagina.Tolta(numero, f"D:\\Foto\\C{numero}", f"C{numero}", quando,
                        _conto(numero, spariscono, restano, file))


def _mandata(numero: int = 5, **cambia) -> storico.Mandata:
    dati = {"id": numero, "stato": "finita", "iniziata_il": "2026-03-01T10:00:00Z",
            "finita_il": "2026-03-01T10:05:00Z", "totale": 1500, "fatti": 1500,
            "saltati": 0, "nuovi_scatti": 1234, "coppie_live": 12, "gia_presenti": 254}
    return storico.Mandata(**{**dati, **cambia})


def _sola(testo: str, numero: int) -> str:
    return testo.split(f'data-cartella="{numero}">', 1)[1].split("</article>", 1)[0]


def _riga(testo: str, numero: int) -> str:
    sua = _sola(testo, numero)
    return re.search(r'<b class="ag-nome".*?<div class="ag-vanno">', sua, re.DOTALL)[0]


@pytest.mark.parametrize("cambia, scritta", [
    ({"spariscono": 1, "arrivati": "ieri"}, "1 scatto · arrivato ieri</span>"),
    ({"spariscono": 1000, "restano": 234, "arrivati": "oggi"},
     "1.234 scatti · ultimi arrivati oggi</span>"),
    ({"spariscono": 5}, "5 scatti</span>"),
    ({"importata": True}, "Qui dentro non ho trovato foto né video</span>"),
    ({}, "Appena aggiunta, da importare</span>"),
    ({"spariscono": 5, "staccata": "Disco E: non attaccato"},
     '<span class="ag-bollo giallo">Disco E: non attaccato</span>'),
])
def test_la_riga_sotto_il_nome(cambia, scritta):
    testo = _scrivi("_ag_cartelle.html", tessere=[_tessera(**cambia)])
    riga = _riga(testo, 1)
    assert scritta in riga
    altre = ("scatt", "Qui dentro", "Appena aggiunta", "ag-bollo")
    assert sum(pezzo in riga for pezzo in altre) == 1


@pytest.mark.parametrize("spariscono, restano, file, scritta", [
    (1, 0, None, "Toglie dall'app anche lo scatto arrivato da qui"),
    (1234, 0, None, "Toglie dall'app anche i 1.234 scatti arrivati da qui"),
    (0, 3, None, "Gli scatti restano: sono anche in un'altra cartella"),
    (0, 0, 2, "Gli scatti restano: sono anche in un'altra cartella"),
    (0, 0, 0, None),
])
def test_il_menu_dice_cosa_fa_annulla(spariscono, restano, file, scritta):
    tessere = [_tessera(1, spariscono, restano, file)]
    sola = _sola(_scrivi("_ag_cartelle.html", tessere=tessere), 1)
    tolte = _scrivi("_ag_storico.html", tolte=[_tolta(1, spariscono, restano, file)])
    if scritta is None:
        assert "Annulla importazione" not in sola and "<hr>" not in sola
        assert "Annulla importazione" not in tolte and "ag-menu" not in tolte
    else:
        assert f"<small>{scritta}</small>" in sola and "<hr>" in sola
        assert f"<small>{scritta}</small>" in tolte
        assert 'data-apri-finestra="annulla-1"' in sola and "annulla-1" in tolte


def test_la_tessera_dice_dove_sta_e_dove_vanno():
    con = _tessera(1, gruppo_id=4, gruppo="Snap", spariscono=7)
    senza = _tessera(2, sopra="")
    testo = _scrivi("_ag_cartelle.html", tessere=[con, senza], aggiunta=2)
    assert '<article class="ag-tessera" data-cartella="1">' in testo
    assert '<article class="ag-tessera nuova" data-cartella="2">' in testo
    assert '<span class="ag-dove" title="D:\\Foto\\C1">D:\\Foto\\</span>' in testo
    assert '<span class="ag-dove" title="D:\\Foto\\C2">D:\\Foto\\C2</span>' in testo
    gruppo = '<button class="ag-gruppo{} type="button" data-cambia-gruppo="{}"'
    assert gruppo.format(' con-gruppo"', 1) in testo
    assert gruppo.format('"', 2) in testo
    assert "<span>Gruppo Snap</span>" in _sola(testo, 1)
    assert "<span>Archivio generale</span>" in _sola(testo, 2)
    assert 'data-gruppo="4"' in _sola(testo, 1) and 'data-gruppo=""' in _sola(testo, 2)
    assert 'data-scatti="7"' in _sola(testo, 1) and 'data-scatti="0"' in _sola(testo, 2)
    assert "2 cartelle · ogni importazione guarda dentro tutte" in testo
    assert testo.count("ag-aggiungi ag-tessera") == 1


@pytest.mark.parametrize("vicino, staccata, si_apre", [
    (True, "", True), (False, "", False), (True, "Non trovo la cartella", False)])
def test_apri_in_esplora_solo_se_si_puo(vicino, staccata, si_apre):
    testo = _scrivi("_ag_cartelle.html", tessere=[_tessera(staccata=staccata)],
                    da_questo_computer=vicino)
    sola = _sola(testo, 1)
    assert ('action="/importazione/cartella/1/apri"' in sola) is si_apre
    assert ("ag-tessera spenta" in testo) is bool(staccata)
    assert 'data-apri-finestra="togli-1"' in sola


@pytest.mark.parametrize("scatti, scritta", [
    (1, "Lo scatto già arrivato da qui resta nell'app e i file sul disco non si toccano."),
    (1234, ("I 1.234 scatti già arrivati da qui restano nell'app e i file sul disco "
            "non si toccano.")),
    (0, '<p class="piccolo attenuato">I file sul disco non si toccano.'),
])
def test_la_finestra_per_togliere(scatti, scritta):
    testo = _scrivi("_ag_finestre.html", tessere=[_tessera(spariscono=scatti)])
    finestra = testo.split('id="togli-1"', 1)[1].split("</dialog>", 1)[0]
    assert scritta in finestra
    assert "La ritrovi in «Cartelle tolte», dove la puoi rimettere.</p>" in finestra
    assert 'action="/importazione/cartella/1/togli"' in finestra
    assert finestra.count("scatt") == (0 if not scatti else 1)


def test_la_finestra_per_annullare():
    tessere = [_tessera(1, 1000, 234), _tessera(2, 3, 0), _tessera(3)]
    tolte = [_tolta(4, 0, 5), _tolta(6)]
    testo = _scrivi("_ag_finestre.html", tessere=tessere, tolte=tolte)
    assert re.findall(r'id="annulla-(\d+)"', testo) == ["1", "2", "4"]
    prima = testo.split('id="annulla-1"', 1)[1].split("</dialog>", 1)[0]
    assert 'Escono dall\'app <b class="numeri">1.000</b> scatti' in prima
    assert '<span class="numeri">234</span> scatti restano' in prima
    assert 'action="/importazione/cartella/1/annulla"' in prima
    assert '<p class="nome-di-file ag-percorso">D:\\Foto\\C1</p>' in prima
    seconda = testo.split('id="annulla-2"', 1)[1].split("</dialog>", 1)[0]
    assert "scatti restano" not in seconda
    quarta = testo.split('id="annulla-4"', 1)[1].split("</dialog>", 1)[0]
    assert '<b class="numeri">0</b>' in quarta and '<span class="numeri">5</span>' in quarta


def test_la_finestra_del_gruppo_solo_con_le_tessere():
    assert 'id="cambia-gruppo"' not in _scrivi("_ag_finestre.html")
    assert 'id="cambia-gruppo"' in _scrivi("_ag_finestre.html", tessere=[_tessera()])


@pytest.mark.parametrize("vicino", [True, False])
def test_l_avviso_della_tolta(vicino):
    tolta = _tolta(9)
    testo = _scrivi("_ag_finestre.html", appena_tolta=tolta, da_questo_computer=vicino)
    avviso = testo.split("data-avviso-tolta", 1)[1]
    assert "<b>Hai tolto «C9» dall'elenco</b>" in avviso
    assert ('action="/importazione/cartella/9/rimetti"' in avviso) is vicino
    assert "data-chiudi-avviso" in avviso
    assert "data-avviso-tolta" not in _scrivi("_ag_finestre.html")


def test_senza_niente_lo_storico_non_c_e():
    assert _scrivi("_ag_storico.html").strip() == ""


def _linguetta(testo: str, quale: str) -> str:
    return testo.split(f'id="ag-linguetta-{quale}"', 1)[1].split("</button>", 1)[0]


def _pannello(testo: str, quale: str) -> str:
    return testo.split(f'id="ag-{quale}"', 1)[1].split(">", 1)[0]


def test_lo_storico_con_le_sole_importazioni():
    testo = _scrivi("_ag_storico.html", mandate=[_mandata()])
    assert 'aria-selected="true"' in _linguetta(testo, "importazioni")
    assert 'aria-selected="false"' in _linguetta(testo, "tolte")
    assert "hidden" not in _pannello(testo, "importazioni")
    assert "hidden" in _pannello(testo, "tolte")
    assert "Nessuna cartella tolta." in testo and "Ancora nessuna importazione" not in testo
    assert "I doppioni sono contati sull'archivio intero" in testo
    assert "ag-punto" not in testo


def test_con_tutte_e_due_si_parte_dalle_importazioni():
    tolta = _tolta(3)
    testo = _scrivi("_ag_storico.html", mandate=[_mandata()], tolte=[tolta],
                    appena_tolta=tolta)
    assert 'aria-selected="true"' in _linguetta(testo, "importazioni")
    assert 'aria-selected="false"' in _linguetta(testo, "tolte")
    assert "hidden" not in _pannello(testo, "importazioni")
    assert "hidden" in _pannello(testo, "tolte")
    assert 'Cartelle tolte <b class="numeri">1</b><i class="ag-punto"' in testo


def test_lo_storico_con_le_sole_tolte():
    tolta = _tolta(3)
    testo = _scrivi("_ag_storico.html", tolte=[tolta, _tolta(4)], appena_tolta=tolta)
    assert 'aria-selected="false"' in _linguetta(testo, "importazioni")
    assert 'aria-selected="true"' in _linguetta(testo, "tolte")
    assert "hidden" in _pannello(testo, "importazioni")
    assert "hidden" not in _pannello(testo, "tolte")
    assert "Ancora nessuna importazione finita." in testo
    assert "Nessuna cartella tolta." not in testo
    assert 'Cartelle tolte <b class="numeri">2</b><i class="ag-punto"' in testo
    assert 'Importazioni di prima <b class="numeri">0</b>' in testo
    assert testo.count('<div class="ag-evento nuova">') == 1
    assert testo.count('<div class="ag-evento">') == 1
    assert "Rimetti» la fa tornare nell'elenco" in testo


@pytest.mark.parametrize("spariscono, restano, scritta", [
    (1, 0, "Il suo scatto è ancora nell'app."),
    (0, 1, "Il suo scatto è ancora nell'app."),
    (1000, 234, "I suoi 1.234 scatti sono ancora nell'app."),
    (0, 0, "Da qui non era arrivato nessuno scatto."),
])
def test_la_tolta_dice_i_suoi_scatti(spariscono, restano, scritta):
    testo = _scrivi("_ag_storico.html", tolte=[_tolta(1, spariscono, restano)])
    assert f'<span class="piccolo tenue numeri">{scritta}</span>' in testo
    assert '<span class="ag-quando numeri">3 mar</span>' in testo
    assert "Hai tolto <b>C1</b> dall'elenco" in testo


@pytest.mark.parametrize("vicino", [True, False])
def test_rimetti_nello_storico_solo_da_qui(vicino):
    testo = _scrivi("_ag_storico.html", tolte=[_tolta(7)], da_questo_computer=vicino)
    assert ('action="/importazione/cartella/7/rimetti"' in testo) is vicino


def _evento(testo: str) -> str:
    dopo = testo.split('<div class="ag-evento">', 1)[1]
    return dopo.split('<span class="ag-azioni">', 1)[0]


@pytest.mark.parametrize("cambia, scritta", [
    ({}, "1.500 file: 1.234 nuovi, 12 live, 254 già presenti · 5 minuti</span>"),
    ({"saltati": 3}, "1.500 file: 1.234 nuovi, 12 live, 254 già presenti, 3 saltati · "),
    ({"finita_il": None}, "254 già presenti</span>"),
    ({"stato": "interrotta"}, "254 già presenti · 5 minuti · interrotta</span>"),
    ({"stato": "in_corso", "finita_il": None}, "254 già presenti · in corso</span>"),
])
def test_la_riga_di_una_importazione(cambia, scritta):
    evento = _evento(_scrivi("_ag_storico.html", mandate=[_mandata(**cambia)]))
    assert scritta in evento


@pytest.mark.parametrize("cambia, nome", [
    ({}, "<b>Importazione 5</b></span>"),
    ({"nome": "Vacanze"}, "<b>Importazione 5</b> · Vacanze</span>"),
    ({"cartelle": ["DCIM", "Foto"]}, "<b>Importazione 5</b> · DCIM, Foto</span>"),
    ({"nome": "Importazione 5"}, "<b>Importazione 5</b></span>"),
])
def test_il_nome_di_una_importazione(cambia, nome):
    assert nome in _evento(_scrivi("_ag_storico.html", mandate=[_mandata(**cambia)]))


def test_il_giorno_e_apri_di_una_importazione():
    testo = _scrivi("_ag_storico.html", mandate=[_mandata(5, quanti_scatti=1234),
                                                  _mandata(6, quanti_scatti=0)])
    giorno = storico.giorno_corto("2026-03-01T10:00:00Z")
    quando = storico.quando_a_parole("2026-03-01T10:00:00Z")
    assert f'<span class="ag-quando numeri" title="{quando}">{giorno}</span>' in testo
    assert re.findall(r'href="/\?importazione=(\d+)"', testo) == ["5"]
    assert ">Apri 1.234</a>" in testo
    assert 'Importazioni di prima <b class="numeri">2</b>' in testo


def _importa(**dati) -> str:
    return _scrivi("_ag_importazione.html", **dati)


@pytest.mark.parametrize("quanti, scritta, apri", [
    (1, "Apri lo scatto nuovo</a>", True),
    (1234, "Apri i 1.234 scatti nuovi</a>", True),
    (0, None, False),
])
def test_finita_apre_gli_scatti_nuovi(quanti, scritta, apri):
    testo = _importa(momento="finita", ultima=_mandata(quanti_scatti=quanti))
    assert ('href="/?importazione=5"' in testo) is apri
    if scritta:
        assert scritta in testo


def test_finita_con_gli_scatti_nuovi():
    testo = _importa(momento="finita", ultima=_mandata())
    assert '<span class="ag-grosso numeri">1.500</span>' in testo
    assert "file · finita in 5 minuti</span>" in testo
    assert "Le ultime arrivate" in testo and "Adesso le foto si guardano" in testo
    assert 'href="/stato#misura"' in testo and "Niente di nuovo" not in testo
    assert 'action="/importazione/prepara"' in testo


def test_finita_senza_niente_di_nuovo():
    testo = _importa(momento="finita", ultima=_mandata(nuovi_scatti=0, finita_il=None))
    assert "Niente di nuovo: questi file erano già tutti nell'archivio." in testo
    assert "Le ultime arrivate" not in testo and 'href="/stato#misura"' not in testo
    assert "file · finita</span>" in testo
    assert "Adesso le foto si guardano" not in testo


@pytest.mark.parametrize("quante, nuovi, prima, scritta", [
    (1, 1, True, "L'ultima volta, il 1º marzo: 1 scatto nuovo."),
    (3, 1234, True, "L'ultima volta, il 1º marzo: 1.234 scatti nuovi."),
    (2, 0, True, "L'ultima volta, il 1º marzo: 0 scatti nuovi."),
    (1, 0, False, None),
])
def test_pronta_dice_l_ultima_volta(monkeypatch, quante, nuovi, prima, scritta):
    monkeypatch.setattr(storico, "_anno", lambda qui, oggi: "")
    finita = _mandata(nuovi_scatti=nuovi) if prima else None
    tessere = [_tessera(numero) for numero in range(quante)]
    testo = _importa(momento="pronta", tessere=tessere, finita_prima=finita)
    dove = "nella cartella" if quante == 1 else f"nelle {quante} cartelle"
    assert f"Conto i file nuovi {dove}. Se lo spazio" in testo
    assert '<span class="ag-bollo">Pronta</span>' in testo
    if scritta is None:
        assert "L'ultima volta" not in testo
    else:
        assert f'<p class="piccolo tenue numeri">{scritta}</p>' in testo


def _stato(fatti: int, saltati: int = 0, totale: int = 1000) -> Avanzamento:
    return Avanzamento("in_corso", totale, fatti, saltati, 7, 2, 1, None)


@pytest.mark.parametrize("fatti, saltati, bollo", [
    (246, 0, "In corso · 25%"), (244, 0, "In corso · 24%"), (240, 5, "In corso · 25%"),
    (230, 5, "In corso · 24%"), (0, 0, "In corso · 0%"), (1000, 0, "In corso · 100%")])
def test_lavora_arrotonda_il_bollo(fatti, saltati, bollo):
    stato = _stato(fatti, saltati)
    testo = _importa(momento="lavora", stato=stato)
    assert f'id="bollo-importazione">{bollo}</span>' in testo
    assert f'<span id="barra" style="width: {stato.percentuale}%"></span>' in testo
    assert f'id="riga-stato">di 1.000 file · {stato.quanto_manca()}</span>' in testo
    assert 'id="conto-scatti">7</dd>' in testo and 'id="conto-saltati">' in testo


@pytest.mark.parametrize("perche, titolo", [
    ("copia", "Aspetta l'Archivio sicuro"), ("tu", "L'hai fermata tu"),
    ("disco", "Non è ripartita da sola"), ("spazio", "Non è ripartita da sola"),
    (None, "Rimasta a metà")])
def test_ferma_dice_perche(perche, titolo):
    testo = _importa(momento="ferma", stato=_stato(300, 20), perche_e_ferma=perche)
    assert f"<b>{titolo}</b>" in testo
    assert '<span class="ag-grosso numeri">300</span>' in testo
    assert "di 1.000 file · ferma</span>" in testo
    assert 'class="barretta ferma"' in testo and 'style="width: 32.0%"' in testo
    assert 'id="conto-scatti"' not in testo and "<dt>Scatti nuovi</dt>" in testo
    assert ("disco esterno" in testo) is (perche == "disco")
    assert ("Liberane un po'" in testo) is (perche == "spazio")


def test_il_piano_dice_lo_spazio():
    piano = {"file": 1234, "peso": "3 GB", "spazio": "servono 3 GB, liberi 900 GB",
             "spazio_basta": True}
    testo = _importa(momento="piano", piano=piano)
    assert '<span class="ag-grosso numeri">1.234</span>' in testo
    assert "file da importare · <span class=\"numeri\">3 GB</span>" in testo
    assert "Lo spazio basta: servono 3 GB, liberi 900 GB." in testo
    poco = _importa(momento="piano", piano={**piano, "spazio_basta": False})
    assert "Lo spazio potrebbe non bastare: servono 3 GB, liberi 900 GB." in poco


def _gruppo(numero: int, nome: str, cartelle: int) -> dict:
    return {"id": numero, "nome": nome, "cartelle": cartelle}


def _scelte(scelto) -> str:
    gruppi = [_gruppo(1, "Uno", 1), _gruppo(2, "Tanti", 4), _gruppo(3, "Vuoto", 0)]
    return str(_pezzi().scelte_gruppo(gruppi, scelto))


def _scelta(testo: str, valore: str) -> str:
    return re.search(rf'<input type="radio" name="gruppo" value="{valore}"[^>]*>', testo)[0]


def test_le_scelte_del_gruppo_contano_le_cartelle():
    testo = _scelte(None)
    for nome, scritta in (("Uno", "1 cartella"), ("Tanti", "4 cartelle"),
                          ("Vuoto", "Ancora nessuna cartella")):
        pezzo = f'<span>Gruppo {nome}</span><span class="piccolo tenue">{scritta}</span>'
        assert pezzo in testo, pezzo


@pytest.mark.parametrize("scelto, acceso", [(None, ""), (2, "2"), (3, "3")])
def test_le_scelte_del_gruppo_accendono_quello_giusto(scelto, acceso):
    testo = _scelte(scelto)
    for valore in ("", "1", "2", "3", "nuovo"):
        assert ("checked" in _scelta(testo, valore)) is (valore == acceso), valore


@pytest.mark.parametrize("primo, sfoglia, scritta", [
    (True, True, "Scegli una cartella…"), (False, True, "Scegli un'altra cartella…"),
    (True, False, "Scrivi il percorso della cartella"),
    (False, False, "Scrivi il percorso di un'altra cartella")])
def test_il_riquadro_per_aggiungere(primo, sfoglia, scritta):
    testo = str(_pezzi().aggiungi(primo, True, sfoglia, [], None))
    assert scritta in html.unescape(testo)
    cima = testo.split(">", 1)[0]
    assert ("primo" in cima) is primo and ("ag-tessera" in cima) is not primo
    assert ("data-autofocus" in cima) is primo
    campo = re.search(r'<input name="percorso"[^>]*>', testo)[0]
    assert ("autofocus" in campo) is (primo and not sfoglia)
    assert ("data-sfoglia" in testo) is sfoglia
    assert ("data-a-mano" in testo) is not sfoglia
    if sfoglia:
        tasto = re.search(r'<button class="tasto-comando cn-sfoglia ([^"]*)"', testo)[1]
        assert tasto.strip() == ("principale" if primo else "")
    assert "data-chiedi-gruppo" in testo


@pytest.mark.parametrize("primo", [True, False])
def test_il_riquadro_da_lontano(primo):
    testo = str(_pezzi().aggiungi(primo, False, True, [], None))
    assert "Le cartelle si aggiungono dal computer dove gira il programma." in testo
    assert "<form" not in testo and "data-sfoglia" not in testo
    assert ('class="ag-aggiungi primo"' in testo) is primo
    assert ('class="ag-aggiungi ag-tessera"' in testo) is not primo


def test_chiedi_gruppo_parte_dall_ultimo():
    gruppi = [_gruppo(1, "Uno", 1), _gruppo(2, "Due", 0)]
    testo = str(_pezzi().aggiungi(False, True, False, gruppi, 2))
    assert "checked" in _scelta(testo, "2") and "checked" not in _scelta(testo, "")
    assert ">Aggiungi la cartella</button>" in testo
