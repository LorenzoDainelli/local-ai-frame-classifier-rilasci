from __future__ import annotations

import json

from prove import test_pagine_nel_browser as nel_browser

navigatore = nel_browser.navigatore
cliente = nel_browser.cliente
_guarda = nel_browser._guarda

STATO = {"versione": "2.0.0-beta.196", "canale": "beta",
         "aggiornamento": {"canale": "beta", "versione_attuale": "2.0.0-beta.196",
                           "trovato": None, "in_sospeso": None, "fase": "fermo",
                           "fatti": 0, "totale": 0, "guasto": ""},
         "motori": {"mancano": [], "variante": "cu128", "scheda": "RTX 3060", "perche": None,
                    "quanto": "", "lavora": False, "riavvio": False, "vecchio": None},
         "chiave": True, "chiave_dall_ambiente": False}


def _con_il_programma(navigatore, stato: str):
    prima = navigatore.new_page

    def nuova(**chiavi):
        pagina = prima(**chiavi)
        pagina.add_init_script(
            "window.__risposte = 0; window.pywebview = {api: {"
            "stato_del_programma: () => { window.__risposte += 1; return %s; },"
            "aggiornamento: () => Promise.resolve(%s),"
            "come_vanno_i_motori: () => Promise.resolve({})}};"
            % (stato, json.dumps(STATO["aggiornamento"])))
        return pagina

    navigatore.new_page = nuova
    return prima


def _errori(navigatore, cliente, guarda) -> list[str]:
    return [errore for errore in _guarda(navigatore, cliente, "/impostazioni#programma", guarda)
            if "status of 404" not in errore]


def _testo(pagina, chi: str) -> str:
    return pagina.inner_text(f'[data-programma="{chi}"]')


def test_la_versione_c_e_anche_senza_il_programma(cliente):
    from officina.programma import aggiornamenti

    pagina = cliente.get("/impostazioni").text
    attesa = f"{aggiornamenti.versione_attuale()} · {aggiornamenti.canale_attuale()}"
    assert f'data-programma="versione">{attesa}</p>' in pagina
    assert pagina.count("Chiedo al programma…") >= 3


def test_aperta_su_il_programma_mostra_il_programma(navigatore, cliente):
    visto = {}

    def guarda(pagina):
        pagina.wait_for_timeout(400)
        visto["vista"] = pagina.is_visible("#programma")
        visto["versione"] = _testo(pagina, "versione")
        visto["motori"] = _testo(pagina, "motori")

    prima = _con_il_programma(navigatore, "Promise.resolve(%s)" % json.dumps(STATO))
    try:
        assert _errori(navigatore, cliente, guarda) == []
    finally:
        navigatore.new_page = prima
    assert visto == {"vista": True, "versione": "2.0.0-beta.196 · beta",
                     "motori": "Pronti: i modelli girano sulla scheda video (RTX 3060)."}


def test_se_il_programma_non_risponde_lo_dice_e_si_riprova(navigatore, cliente):
    visto = {}

    def guarda(pagina):
        pagina.wait_for_timeout(9000)
        visto["avviso"] = pagina.is_visible('[data-programma="non-risponde"]')
        visto["riprova"] = pagina.is_visible('[data-programma-fai="riprova"]')
        visto["motori"] = _testo(pagina, "motori")
        pagina.evaluate("window.pywebview.api.stato_del_programma = "
                        "() => Promise.resolve(%s)" % json.dumps(STATO))
        pagina.click('[data-programma-fai="riprova"]')
        pagina.wait_for_timeout(400)
        visto["dopo"] = pagina.is_visible('[data-programma="non-risponde"]')
        visto["chiave"] = _testo(pagina, "chiave")

    prima = _con_il_programma(navigatore, "new Promise(() => {})")
    try:
        assert _errori(navigatore, cliente, guarda) == []
    finally:
        navigatore.new_page = prima
    assert visto["avviso"] and visto["riprova"]
    assert visto["motori"] == "Non lo so ancora."
    assert not visto["dopo"]
    assert visto["chiave"] == "C'è, custodita nel Gestore credenziali di Windows."


def test_lo_stato_del_programma_non_aspetta_il_lucchetto():
    import threading

    from officina.programma import avvio, ponti

    programma = avvio.Programma()
    ponte = ponti.PontePrincipale(programma)
    preso = threading.Event()
    lascia = threading.Event()

    def tiene():
        with programma._lucchetto:
            preso.set()
            lascia.wait(10)

    filo = threading.Thread(target=tiene, daemon=True)
    filo.start()
    preso.wait(5)
    try:
        risposta = {}
        chiede = threading.Thread(target=lambda: risposta.update(ponte.stato_del_programma()),
                                  daemon=True)
        chiede.start()
        chiede.join(5)
        assert "versione" in risposta
    finally:
        lascia.set()
        filo.join(5)
