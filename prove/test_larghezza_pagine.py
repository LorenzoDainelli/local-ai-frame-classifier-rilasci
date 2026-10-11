from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from prove.fogli import schermate

FOGLIO = (Path(__file__).resolve().parent.parent
          / "officina" / "web" / "statici" / "css" / "fondamenta.css")

CON_COLONNA = ["/elenchi", "/doppioni", "/impostazioni", "/stato", "/senza-data",
               "/scatto/1", "/telefono", "/fuori", "/importazione", "/miglioramento",
               "/persone", "/persone/mazzo", "/persone/cassetto", "/luoghi",
               "/benvenuto", "/benvenuto/cartella", "/benvenuto/lavoro",
               "/benvenuto/pronto"]


@pytest.fixture
def cliente(archivio_pieno):
    from officina.web.server import app

    return TestClient(app, client=("127.0.0.1", 51000))


class DoveStaLaColonna(HTMLParser):

    def __init__(self) -> None:
        super().__init__()
        self.pila: list[set[str]] = []
        self.dentro = 0
        self.fuori = 0

    def handle_starttag(self, tag, attributi):
        classi = set()
        for nome, valore in attributi:
            if nome == "class" and valore:
                classi = set(valore.split())
        if "pagina" in classi:
            genitore = self.pila[-1] if self.pila else set()
            if "zona-principale" in genitore:
                self.dentro += 1
            else:
                self.fuori += 1
        if tag not in ("br", "hr", "img", "input", "link", "meta", "source"):
            self.pila.append(classi)

    def handle_endtag(self, tag):
        if self.pila:
            self.pila.pop()


def guarda(testo: str) -> DoveStaLaColonna:
    lettore = DoveStaLaColonna()
    lettore.feed(testo)
    return lettore


def test_la_colonna_si_centra():
    css = schermate()
    assert "margin-inline: auto" in css
    assert ".zona-principale > .pagina" in css


def test_chi_scorre_e_la_zona_non_la_colonna():
    css = schermate()
    assert ".zona-principale:has(> .pagina) { overflow-y: auto; }" in css
    assert "overflow: visible" in css


@pytest.mark.parametrize("indirizzo", CON_COLONNA)
def test_ogni_colonna_sta_dove_la_regola_la_trova(cliente, indirizzo):
    dove = guarda(cliente.get(indirizzo).text)
    assert dove.dentro >= 1, (
        f"{indirizzo} non ha nessuna colonna dentro «zona-principale»: "
        "la regola che la centra non la tocca")
    assert dove.fuori == 0, (
        f"{indirizzo} ha {dove.fuori} colonne fuori da «zona-principale»: "
        "quelle restano a sinistra")


def test_la_prova_saprebbe_accorgersene():
    sbagliata = guarda('<div class="corpo"><div class="pagina">ciao</div></div>')
    assert sbagliata.dentro == 0 and sbagliata.fuori == 1

    giusta = guarda('<div class="corpo"><main class="zona-principale">'
                    '<div class="pagina">ciao</div></main></div>')
    assert giusta.dentro == 1 and giusta.fuori == 0


def test_il_corpo_della_galleria_si_puo_stringere():
    foglio = schermate()
    principio = foglio.index(".corpo { display: flex;")
    regola = foglio[principio:foglio.index("}", principio)]
    assert "min-width: 0" in regola, (
        "senza questo la galleria è più larga della finestra, e si porta "
        "dietro una barra di scorrimento orizzontale che non serve a niente")
    assert "min-height: 0" in regola


def test_la_barra_puo_andare_a_capo():
    css = schermate()

    principio = css.index(".guscio {")
    guscio = css[principio:css.index("}", principio)]
    assert "grid-template-rows: auto 1fr;" in guscio, (
        "la riga della barra è tornata fissa: la barra andata a capo si "
        f"taglia invece di farsi posto: {guscio}")

    telaio = (FOGLIO.parent / "telaio.css").read_text(encoding="utf-8")
    assert ".nav-b { flex-wrap: wrap;" in telaio, (
        "la barra non va più a capo quando la finestra è stretta")

    assert "calc(100dvh - var(--barra-alta))" not in css, (
        "qualcuno è tornato a misurare l'altezza della barra a mano: quel "
        "conto non sa né della barra andata a capo né delle fasce del giro "
        "guidato e del travaso, e sfonda sotto")


def test_la_misura_vera_della_barra_ha_un_ripiego():
    fondamenta = (FOGLIO.parent / "fondamenta.css").read_text(encoding="utf-8")
    assert "--barra-vera: 56px;" in fondamenta
    assert "--barra-alta: 56px;" in fondamenta


def test_le_righe_di_comandi_vanno_a_capo():
    componenti = (FOGLIO.parent / "componenti.css").read_text(encoding="utf-8")
    principio = componenti.index(".riga-fra {")
    riga_fra = componenti[principio:componenti.index("}", principio)]
    assert "flex-wrap: wrap" in riga_fra, (
        "«.riga-fra» non va più a capo: in una finestra stretta il gruppo di "
        f"destra esce dal riquadro e i suoi tasti spariscono: {riga_fra}")

    css = schermate()
    for quale in (".mappa-testa {",):
        principio = css.index(quale)
        regola = css[principio:css.index("}", principio)]
        assert "flex-wrap: wrap" in regola, (
            f"«{quale.strip(' {')}» non va più a capo: {regola}")
