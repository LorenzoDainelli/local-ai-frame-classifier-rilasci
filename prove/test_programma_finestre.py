from __future__ import annotations

import sqlite3
import threading
import urllib.request
from types import SimpleNamespace

import pytest

from officina.programma import aggiornamenti, avvio, carta, finestre, librerie, ponti, scheda


class Evento:

    def __init__(self):
        self.chi = []
        self.fatto = False
        self.attese = []

    def __iadd__(self, funzione):
        self.chi.append(funzione)
        return self

    def set(self):
        self.fatto = True
        return any(funzione() is False for funzione in self.chi)

    def wait(self, timeout=None):
        self.attese.append(timeout)
        return self.fatto


class FinestraFinta:

    def __init__(self, titolo, **opzioni):
        self.titolo = titolo
        self.opzioni = opzioni
        self.url = opzioni.get("url")
        self.html = [opzioni["html"]] if opzioni.get("html") else []
        self.events = SimpleNamespace(closing=Evento(), maximized=Evento(),
                                      restored=Evento(), loaded=Evento())
        self.distrutta = False
        self.risposta = True
        self.scelta = None
        self.domande = []
        self.width, self.height, self.x, self.y = 1300, 850, 10, 20

    def load_url(self, indirizzo):
        self.url = indirizzo

    def load_html(self, html):
        self.html.append(html)

    def evaluate_js(self, codice):
        self.codici = getattr(self, "codici", []) + [codice]
        return getattr(self, "risposta_js", None)

    def destroy(self):
        if not self.events.closing.set():
            self.distrutta = True

    def chiudi_dalla_x(self):
        return self.events.closing.set()

    def create_confirmation_dialog(self, titolo, domanda):
        self.domande.append(domanda)
        return self.risposta

    def create_file_dialog(self, tipo, directory=""):
        return self.scelta


class WebviewFinto:

    FileDialog = SimpleNamespace(FOLDER=20)
    screens = ["schermo principale"]

    def __init__(self):
        self.finestre = []
        self.partito = None

    def create_window(self, titolo, **opzioni):
        finestra = FinestraFinta(titolo, **opzioni)
        self.finestre.append(finestra)
        return finestra

    def start(self, funzione=None, **opzioni):
        self.partito = opzioni
        if funzione is not None:
            funzione()


@pytest.fixture
def casa(tmp_path, monkeypatch):
    from officina.archivio import accesso

    monkeypatch.setenv("OFFICINA_CASA_PROGRAMMA", str(tmp_path / "casa"))
    monkeypatch.delenv("OFFICINA_ARCHIVIO", raising=False)
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.setattr(carta, "cartella_della_versione_1", lambda: tmp_path / "nessuna")
    monkeypatch.setattr(avvio, "PORTA_PREFERITA", 0)
    monkeypatch.setattr(librerie, "cosa_manca", lambda richieste=None: [])
    from officina import modelli_in_casa

    monkeypatch.setattr(modelli_in_casa, "mancano_gli_obbligatori", lambda dove=None: [])
    monkeypatch.setattr(modelli_in_casa, "controlla_la_chiave", lambda chiave: None)
    from officina.programma import segreti as custode

    monkeypatch.setattr(custode, "si_puo_custodire", lambda: False)
    accesso.chiudi(con_copia=False)
    yield tmp_path
    from officina.programma import segreti

    segreti._in_memoria.pop(segreti.CHIAVE_HF, None)
    accesso.chiudi(con_copia=False)
    from officina.web import sfoglia

    sfoglia.imposta_chi_sceglie(None)


def _senza_nvidia():
    return scheda.Esame()


def _programma():
    finto = WebviewFinto()
    return avvio.Programma(webview=finto, esamina=_senza_nvidia), finto


def _aspetta_la_partenza(programma):
    filo = getattr(programma, "_partenza", None)
    if filo is not None:
        filo.join(timeout=30)


def _chiudi_davvero(programma):
    programma.spegni()


def test_la_prima_volta_senza_archivio_vecchio_propone_di_cominciare(casa):
    programma, _ = _programma()
    stato = programma.stato_per_la_finestrina()
    assert stato["passo"] == "archivio"
    assert stato["versione_1"] is None


def test_il_giro_della_prima_volta_arriva_alla_finestra_grande(casa):
    programma, finto = _programma()
    programma.crea_la_finestrina()
    ponte = ponti.PonteFinestrina(programma)
    try:
        assert ponte.comincia_da_zero()["stato"]["passo"] == "chiave"
        assert "errore" in ponte.salva_la_chiave("non una chiave")
        stato = ponte.salva_la_chiave("hf_" + "x" * 34)["stato"]
        assert stato["passo"] == "apertura"
        _aspetta_la_partenza(programma)
        principale = programma.principale
        assert principale is not None and principale.url.startswith("http://127.0.0.1:")
        assert finto.finestre[0].distrutta
        risposta = urllib.request.urlopen(principale.url + "benvenuto", timeout=10)
        assert risposta.status == 200
    finally:
        _chiudi_davvero(programma)


def test_la_finestrina_resta_finche_la_grande_non_ha_caricato(casa):
    programma, finto = _programma()
    finestrina = programma.crea_la_finestrina()
    ordine = []
    crea_davvero = finto.create_window

    def crea(titolo, **opzioni):
        finestra = crea_davvero(titolo, **opzioni)
        finestra.events.loaded.wait = lambda timeout=None: (
            ordine.append(("attesa", finestrina.distrutta, timeout)) or True)
        return finestra

    def distruggi():
        ordine.append(("chiusa",))
        finestrina.distrutta = True

    finto.create_window = crea
    finestrina.destroy = distruggi
    try:
        programma._mostra_la_principale("http://127.0.0.1:1/")
        assert ordine == [("attesa", False, finestre.ATTESA_DELLA_PRINCIPALE), ("chiusa",)]
        assert programma.finestrina is None
    finally:
        _chiudi_davvero(programma)


def test_i_motori_mancanti_si_chiedono_prima_e_si_possono_rimandare(casa, monkeypatch):
    monkeypatch.setattr(librerie, "cosa_manca", lambda richieste=None: ["torch", "modelli"])
    programma, _ = _programma()
    carta.comincia_da_zero()
    stato = programma.stato_per_la_finestrina()
    assert stato["passo"] == "motori"
    assert "processore" in stato["scheda"]
    assert stato["quanto"].startswith("circa")
    stato = programma.fai(programma.motori_piu_tardi)["stato"]
    assert stato["passo"] == "motori", "senza motori il programma non si apre"
    carta.aggiorna(obblighi_sospesi=True)
    assert programma.passo() == "chiave"


def test_motori_gia_installati_ma_vecchi_si_richiedono_anche_se_rimandati(casa, monkeypatch):
    monkeypatch.setattr(librerie, "cosa_manca", lambda richieste=None: ["modelli"])
    carta.comincia_da_zero()
    carta.aggiorna(motori_rimandati=True, librerie={"torch": {"torch": "2"}})
    programma, _ = _programma()
    assert programma.passo() == "motori"


def test_ritrova_l_archivio_della_versione_uno(casa, monkeypatch):
    vecchio = casa / "Officina"
    (vecchio / "reale").mkdir(parents=True)
    connessione = sqlite3.connect(vecchio / "reale" / "archivio.sqlite")
    connessione.execute("CREATE TABLE scatti (id INTEGER, fuori_archivio INTEGER)")
    connessione.executemany("INSERT INTO scatti VALUES (?, 0)", [(n,) for n in range(1234)])
    connessione.commit()
    connessione.close()
    monkeypatch.setattr(carta, "cartella_della_versione_1", lambda: vecchio)
    monkeypatch.setattr(avvio, "la_versione_vecchia_risponde", lambda porta=0: False)
    programma, _ = _programma()
    stato = programma.stato_per_la_finestrina()
    assert stato["versione_1"]["scatti"] == "1.234"
    assert stato["versione_1"]["dove"] == str(vecchio)
    ponti.PonteFinestrina(programma).usa_la_versione_1()
    assert carta.cartella_dati() == vecchio.resolve()
    assert carta.leggi()["migrato_dalla_versione_1"] is True


def test_se_la_versione_vecchia_e_aperta_aspetta(casa, monkeypatch):
    vecchio = casa / "Officina"
    (vecchio / "reale").mkdir(parents=True)
    (vecchio / "reale" / "archivio.sqlite").write_bytes(b"")
    monkeypatch.setattr(carta, "cartella_della_versione_1", lambda: vecchio)
    carta.usa_questo_archivio(vecchio)
    aperta = {"si": True}
    monkeypatch.setattr(avvio, "la_versione_vecchia_risponde", lambda porta=0: aperta["si"])
    programma, _ = _programma()
    assert programma.passo() == "vecchia-aperta"
    aperta["si"] = False
    carta.aggiorna(obblighi_sospesi=True, chiave_chiesta=True)
    assert programma.passo() == "pronto"


def test_sfoglia_mostra_prima_di_usare(casa):
    altrove = casa / "Chiavetta"
    (altrove / "reale").mkdir(parents=True)
    (altrove / "reale" / "archivio.sqlite").write_bytes(b"")
    programma, _ = _programma()
    programma.crea_la_finestrina()
    programma.finestrina.scelta = (str(altrove / "reale"),)
    ponte = ponti.PonteFinestrina(programma)
    stato = ponte.sfoglia_archivio()["stato"]
    assert stato["passo"] == "scelto"
    assert stato["scelto"]["dove"] == str(altrove)
    assert carta.cartella_dati() is None
    ponte.usa_lo_scelto()
    assert carta.cartella_dati() == altrove.resolve()


def test_sfoglia_su_una_cartella_sbagliata_lo_dice(casa):
    programma, _ = _programma()
    programma.crea_la_finestrina()
    programma.finestrina.scelta = (str(casa),)
    risposta = ponti.PonteFinestrina(programma).sfoglia_archivio()
    assert "reale" in risposta["errore"]


def test_la_password_del_forziere_passa_dal_ponte_e_non_dalla_rete(casa):
    from officina import forziere
    from officina.archivio import accesso
    from officina.impostazioni import REALE, posizione

    carta.comincia_da_zero()
    carta.aggiorna(obblighi_sospesi=True, chiave_chiesta=True)
    accesso.apri(REALE)
    accesso.chiudi(con_copia=False)
    forziere.per(posizione(REALE)).accendi("una password lunga")

    programma, _ = _programma()
    programma.crea_la_finestrina()
    ponte = ponti.PonteFinestrina(programma)
    try:
        assert ponte.stato()["passo"] == "password"
        assert ponte.apri_il_forziere("sbagliata di sicuro")["errore"] == "La password non è giusta."
        assert programma.servitore is None
        risposta = ponte.apri_il_forziere("una password lunga")
        assert risposta["stato"]["passo"] == "apertura"
        assert programma.principale is not None
        assert programma.finestrina is None
        for filo in threading.enumerate():
            if filo.name == "apertura":
                filo.join(timeout=30)
        assert programma.principale.url.startswith("http://127.0.0.1:")
        assert forziere.per(posizione(REALE)).aperto
    finally:
        _chiudi_davvero(programma)
    assert not forziere.per(posizione(REALE)).aperto


def test_chiudere_senza_lavori_mette_al_sicuro_e_se_ne_va(casa):
    from officina.archivio import accesso

    carta.comincia_da_zero()
    carta.aggiorna(obblighi_sospesi=True, chiave_chiesta=True)
    programma, _ = _programma()
    indirizzo = programma.accendi()
    programma.crea_la_principale(indirizzo)
    principale = programma.principale
    assert principale.chiudi_dalla_x() is True
    for filo in threading.enumerate():
        if filo.name == "chiusura":
            filo.join(timeout=30)
    assert principale.distrutta
    assert not principale.domande
    assert "al sicuro" in principale.html[-1]
    with pytest.raises(Exception):
        accesso.aperto()
    assert carta.leggi()["finestra"]["larga"] == 1300


def test_chiudere_con_un_lavoro_chiede_e_si_puo_ripensare(casa, monkeypatch):
    carta.comincia_da_zero()
    programma, _ = _programma()
    programma.accendi()
    programma.crea_la_principale("http://127.0.0.1:1/")
    monkeypatch.setattr(programma, "lavori_in_corso", lambda: ["le impronte"])
    programma.principale.risposta = False
    try:
        programma._sta_chiudendo = True
        programma._chiudi_con_calma()
        assert "le impronte" in programma.principale.domande[0]
        assert not programma.principale.distrutta
        assert programma._sta_chiudendo is False
    finally:
        _chiudi_davvero(programma)


def test_la_domanda_prima_di_chiudere_la_fa_la_pagina_se_puo(casa, monkeypatch):
    carta.comincia_da_zero()
    programma, _ = _programma()
    programma.accendi()
    programma.crea_la_principale("http://127.0.0.1:1/")
    monkeypatch.setattr(programma, "lavori_in_corso", lambda: ["le impronte"])
    programma.principale.risposta_js = True
    try:
        programma._sta_chiudendo = True
        programma._chiudi_con_calma()
        assert not programma.principale.domande
        assert any("chiediDiChiudere" in codice and "le impronte" in codice
                   for codice in programma.principale.codici)
        assert not programma.principale.distrutta and programma._sta_chiudendo is False
        programma.chiudi_comunque()
        for filo in threading.enumerate():
            if filo.name == "chiusura":
                filo.join(timeout=30)
        assert programma.principale.distrutta
    finally:
        _chiudi_davvero(programma)


def test_una_seconda_apertura_non_parte(casa, monkeypatch):
    from officina.programma import istanza

    primo = istanza.Istanza(casa / "blocchi")
    assert primo.prendi()
    secondo = istanza.Istanza(casa / "blocchi")
    try:
        assert not secondo.prendi()
    finally:
        primo.lascia()
    assert secondo.prendi()
    secondo.lascia()


def test_in_beta_un_aggiornamento_scaricato_si_installa_prima_di_aprire(casa, monkeypatch, tmp_path):
    lanciati = []
    file = tmp_path / "local-ai-frame-classifier-2.0.0-beta.9.exe"
    rilascio = aggiornamenti.Rilascio("2.0.0-beta.9", "https://x", file.name, 1, "a", "", "")
    monkeypatch.setattr(aggiornamenti, "pronto_da_installare", lambda: (rilascio, file))
    monkeypatch.setattr(aggiornamenti, "installa", lambda f: lanciati.append(f))
    programma, finto = _programma()
    programma.canale = aggiornamenti.BETA
    monkeypatch.setattr(programma.istanza, "prendi", lambda: True)
    assert programma.avvia() == 0
    assert lanciati == [file]
    assert finto.finestre == []


def test_aggiorna_adesso_chiude_e_poi_installa(casa, monkeypatch, tmp_path):
    carta.comincia_da_zero()
    carta.aggiorna(obblighi_sospesi=True, chiave_chiesta=True)
    file = tmp_path / "nuovo.exe"
    rilascio = aggiornamenti.Rilascio("9.0.0", "https://x", "local-ai-frame-classifier-9.0.0.exe",
                                      3, "a" * 64, "", "")
    monkeypatch.setattr(aggiornamenti, "scarica",
                        lambda r, al_passo=None: (al_passo(3, 3), file)[1])
    installati = []
    monkeypatch.setattr(aggiornamenti, "installa", lambda f: installati.append(f))
    programma, finto = _programma()
    monkeypatch.setattr(programma.istanza, "prendi", lambda: True)
    programma.aggiornamento_trovato = rilascio

    def start(funzione=None, **opzioni):
        if funzione is not None:
            funzione()
        _aspetta_la_partenza(programma)
        risposta = ponti.PontePrincipale(programma).aggiorna_adesso()
        assert risposta["trovato"]["versione"] == "9.0.0"
        for filo in threading.enumerate():
            if filo.name == "aggiornamento":
                filo.join(timeout=30)

    finto.start = start
    assert programma.avvia() == 0
    assert programma.principale.distrutta
    assert installati == [file]


def test_rifiutare_lascia_l_aggiornamento_in_sospeso(casa, monkeypatch):
    rilascio = aggiornamenti.Rilascio("9.0.0", "https://x", "local-ai-frame-classifier-9.0.0.exe",
                                      3, "a" * 64, "", "")
    programma, _ = _programma()
    programma.aggiornamento_trovato = rilascio
    stato = ponti.PontePrincipale(programma).rifiuta_aggiornamento()
    assert stato["fase"] == "rifiutato"
    assert stato["in_sospeso"]["versione"] == "9.0.0"


def test_le_parole_per_la_scheda():
    con = scheda.Esame(schede=(scheda.Scheda("NVIDIA GeForce RTX 4070", 12 * 2 ** 30, (8, 9)),),
                       cuda_del_driver=(12, 8))
    assert "RTX 4070" in avvio.descrivi_la_scheda(con)
    assert avvio.quanto_si_scarica(con, ["torch", "modelli"]) == "circa 2,7 GB"
    assert avvio.quanto_si_scarica(scheda.Esame(), ["modelli"]) == "circa 154 MB"
    assert avvio.quanto_si_scarica(con, []) == "niente"


def test_la_finestrina_ha_tutti_i_passi_che_il_programma_puo_chiedere():
    from officina.programma import pagine

    html = pagine.finestrina("2.0.0")
    for passo in ("archivio", "scelto", "sparito", "vecchia-aperta", "motori", "chiave",
                  "modelli", "password", "apertura", "guasto"):
        assert f'data-passo="{passo}"' in html
    for metodo in dir(ponti.PonteFinestrina):
        if not metodo.startswith("_") and metodo not in ("stato", "come_vanno_i_motori",
                                                              "come_vanno_i_modelli"):
            assert f"api().{metodo}(" in html, metodo


def test_lo_stato_del_programma_per_le_impostazioni(casa, monkeypatch):
    monkeypatch.setattr(librerie, "cosa_manca", lambda richieste=None: ["torch"])
    programma, _ = _programma()
    ponte = ponti.PontePrincipale(programma)
    stato = ponte.stato_del_programma()
    assert stato["canale"] == aggiornamenti.SVILUPPO
    assert stato["motori"]["mancano"] == ["torch"]
    assert stato["motori"]["quanto"].startswith("circa")
    assert stato["chiave"] is False


def test_la_chiave_si_mette_e_si_toglie_dal_ponte_grande(casa, monkeypatch):
    from officina.programma import segreti

    monkeypatch.setattr(segreti, "si_puo_custodire", lambda: False)
    programma, _ = _programma()
    ponte = ponti.PontePrincipale(programma)
    assert "errore" in ponte.salva_la_chiave("sbagliata")
    assert ponte.salva_la_chiave("hf_" + "x" * 36) == {"chiave": True}
    assert ponte.stato_del_programma()["chiave"] is True
    assert ponte.togli_la_chiave() == {"chiave": False}


def test_i_motori_non_si_rifanno_con_torch_gia_caricato(casa, monkeypatch):
    programma, _ = _programma()
    monkeypatch.setattr(programma, "_torch_gia_caricato", lambda: True)
    assert "riaprilo" in ponti.PontePrincipale(programma).prepara_i_motori()["errore"]


def test_la_striscia_e_la_sezione_ci_sono_nelle_pagine(casa):
    from pathlib import Path

    radice = Path(avvio.__file__).resolve().parent.parent / "web"
    base = (radice / "templates" / "base.html").read_text(encoding="utf-8")
    impostazioni = (radice / "templates" / "impostazioni.html").read_text(encoding="utf-8")
    script = (radice / "statici" / "js" / "programma.js").read_text(encoding="utf-8")
    assert 'id="striscia-aggiornamento"' in base and "programma.js" in base
    assert 'id="programma"' in impostazioni
    for metodo in ("stato_del_programma", "prepara_i_motori", "come_vanno_i_motori",
                   "salva_la_chiave", "togli_la_chiave", "aggiorna_adesso",
                   "rifiuta_aggiornamento", "aggiornamento"):
        assert f"api().{metodo}(" in script, metodo
        assert hasattr(ponti.PontePrincipale, metodo), metodo


def test_accendere_il_forziere_e_rientrare_passano_dal_ponte(casa):
    from officina import forziere
    from officina.archivio import accesso
    from officina.web import blocco

    carta.comincia_da_zero()
    programma, _ = _programma()
    programma.accendi()
    ponte = ponti.PontePrincipale(programma)
    try:
        assert "spunta" in ponte.accendi_il_forziere("lunga abbastanza", "lunga abbastanza",
                                                     False)["errore"]
        assert "coincidono" in ponte.accendi_il_forziere("lunga abbastanza", "diversa davvero",
                                                         True)["errore"]
        esito = ponte.accendi_il_forziere("lunga abbastanza", "lunga abbastanza", True,
                                          "/impostazioni#c6")
        assert esito == {"vai": "/impostazioni#c6"}
        assert forziere.per(accesso.aperto().dove).acceso
        blocco.guardia.blocca_adesso("qui")
        assert ponte.rientra("sbagliata") == {"errore": "La password non è giusta."}
        assert blocco.guardia.e_bloccato("qui")
        assert ponte.rientra("lunga abbastanza") == {"vai": "/"}
        assert not blocco.guardia.e_bloccato("qui")
    finally:
        _chiudi_davvero(programma)


def test_le_pagine_con_una_password_caricano_il_ponte():
    from pathlib import Path

    radice = Path(avvio.__file__).resolve().parent.parent / "web" / "templates"
    assert "programma.js" in (radice / "blocco.html").read_text(encoding="utf-8")
    assert 'id="modulo-forziere"' in (radice / "_forziere.html").read_text(encoding="utf-8")
    assert 'class="modulo-blocco"' in (radice / "blocco.html").read_text(encoding="utf-8")


def test_spegnere_il_forziere_dal_ponte(casa):
    from officina import forziere
    from officina.archivio import accesso

    carta.comincia_da_zero()
    programma, _ = _programma()
    programma.accendi()
    ponte = ponti.PontePrincipale(programma)
    try:
        assert "non c'è" in ponte.spegni_il_forziere("qualcosa")["errore"]
        ponte.accendi_il_forziere("lunga abbastanza", "lunga abbastanza", True)
        assert ponte.spegni_il_forziere("sbagliata")["errore"] == "La password non è giusta."
        assert ponte.spegni_il_forziere("lunga abbastanza") == {"vai": "/impostazioni#c6"}
        assert not forziere.per(accesso.aperto().dove).acceso
    finally:
        _chiudi_davvero(programma)
    from officina.impostazioni import REALE, posizione

    assert not forziere.per(posizione(REALE)).acceso


def test_un_archivio_sparito_non_diventa_un_archivio_vuoto(casa):
    esterno = casa / "DiscoEsterno" / "Officina"
    (esterno / "reale").mkdir(parents=True)
    (esterno / "reale" / "archivio.sqlite").write_bytes(b"")
    carta.usa_questo_archivio(esterno)
    carta.aggiorna(obblighi_sospesi=True, chiave_chiesta=True)
    import shutil

    shutil.rmtree(casa / "DiscoEsterno")
    programma, _ = _programma()
    stato = programma.stato_per_la_finestrina()
    assert stato["passo"] == "sparito"
    assert stato["dove"] == str(esterno.resolve())
    assert not esterno.exists()
    (esterno / "reale").mkdir(parents=True)
    assert programma.passo() == "pronto"


def test_se_la_finestra_non_parte_lo_dice(casa, monkeypatch):
    carta.comincia_da_zero()
    carta.aggiorna(obblighi_sospesi=True, chiave_chiesta=True)
    programma, finto = _programma()
    monkeypatch.setattr(programma.istanza, "prendi", lambda: True)
    detti = []
    monkeypatch.setattr(avvio, "avvisa", lambda titolo, testo: detti.append(testo))

    def rotto(*a, **k):
        raise RuntimeError("niente WebView2")

    finto.start = rotto
    assert programma.avvia() == 1
    assert "WebView2" in detti[0]


def test_una_scheda_nuova_fa_rivedere_i_motori(casa, monkeypatch):
    carta.comincia_da_zero()
    carta.aggiorna(obblighi_sospesi=True, chiave_chiesta=True, librerie={"torch": {
        "torch": "2.14.0+cpu", "variante": "cpu", "esame": scheda.Esame().come_dati()}})
    rtx = scheda.Esame(schede=(scheda.Scheda("NVIDIA GeForce RTX 5070", 12 * 2 ** 30, (12, 0)),),
                       cuda_del_driver=(12, 9))
    programma = avvio.Programma(webview=WebviewFinto(), esamina=lambda: rtx)
    stato = programma.stato_per_la_finestrina()
    assert stato["passo"] == "motori"
    assert stato["scheda"].startswith("La scheda video è cambiata")
    assert programma._parti_da_preparare() == ["torch"]
    programma.motori_piu_tardi()
    assert carta.leggi()["motori_rimandati_per_la_scheda"] == "NVIDIA GeForce RTX 5070"
    assert programma.passo() == "pronto"


def test_la_stessa_scheda_non_chiede_niente(casa):
    rtx = scheda.Esame(schede=(scheda.Scheda("NVIDIA GeForce RTX 4070", 12 * 2 ** 30, (8, 9)),),
                       cuda_del_driver=(12, 9))
    carta.comincia_da_zero()
    carta.aggiorna(obblighi_sospesi=True, chiave_chiesta=True, librerie={"torch": {
        "torch": "2.14.0+cu128", "variante": "cu128", "esame": rtx.come_dati()}})
    programma = avvio.Programma(webview=WebviewFinto(), esamina=lambda: rtx)
    assert programma.passo() == "pronto"


def test_le_finestre_nuove_si_aprono_al_centro_dello_schermo(casa):
    programma, finto = _programma()
    finestrina = programma.crea_la_finestrina()
    assert finestrina.opzioni["screen"] == "schermo principale"
