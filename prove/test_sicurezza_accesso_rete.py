from __future__ import annotations

import hashlib
import http.client
import re
import ssl
import sys
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from officina.archivio.database import leggi_stato
from officina.modello import dispositivi
from officina.web import origine

pytestmark = pytest.mark.usefixtures("senza_chiavi_delle_prove")

TABLET = "192.168.1.40"
INTRUSO = "192.168.1.66"


def _dalla_rete(indirizzo: str = TABLET, schema: str = "https") -> TestClient:
    from officina.web.server import app

    return TestClient(app, base_url=f"{schema}://192.168.1.5:8443", client=(indirizzo, 51000),
                      follow_redirects=False)


def _computer() -> TestClient:
    from officina.web.server import app

    cliente = TestClient(app, base_url="http://127.0.0.1:8080", client=("127.0.0.1", 51000),
                         follow_redirects=False)
    cliente.cookies.set(origine.BISCOTTO_DELLA_FINESTRA, origine.chiave_della_finestra())
    return cliente


@pytest.fixture
def in_rete(archivio_pieno):
    archivio_pieno.imposta("accesso_dalla_rete", True)
    return archivio_pieno


def _codice(pagina: str) -> str:
    trovato = re.search(r'id="codice">(\d{3}) (\d{3})<', pagina)
    assert trovato, pagina
    return trovato.group(1) + trovato.group(2)


def _id_di(archivio, indirizzo: str) -> int:
    with archivio.lettura() as connessione:
        return dispositivi.trova(connessione, indirizzo)["id"]


def _abbina(archivio, tablet: TestClient, indirizzo: str = TABLET) -> str:
    pagina = tablet.get("/dispositivo/attesa", headers={"accept": "text/html"})
    assert pagina.status_code == 200
    risposta = _computer().post(f"/impostazioni/dispositivo/{_id_di(archivio, indirizzo)}/codice",
                                data={"codice": _codice(pagina.text)},
                                headers={"origin": "http://127.0.0.1:8080"})
    assert risposta.status_code == 303
    assert "approvato=" in risposta.headers["location"]
    preso = tablet.get("/dispositivo/attesa/stato")
    assert preso.json() == {"vai": "/"}
    return preso.cookies[dispositivi.BISCOTTO]


def test_dalla_rete_in_chiaro_non_risponde(in_rete):
    risposta = _dalla_rete(schema="http").get("/")
    assert risposta.status_code == 403
    assert "https://" in risposta.json()["messaggio"]


def test_un_dispositivo_nuovo_vede_solo_la_pagina_del_codice(in_rete):
    tablet = _dalla_rete()
    pagina = tablet.get("/", headers={"accept": "text/html"})
    assert pagina.status_code == 303
    assert pagina.headers["location"] == "/dispositivo/attesa"
    assert tablet.get("/api/in-corso").status_code == 403
    assert "approvato" in tablet.get("/stato").json()["messaggio"]
    attesa = tablet.get("/dispositivo/attesa", headers={"accept": "text/html"})
    assert attesa.status_code == 200
    assert TABLET in attesa.text
    assert in_rete.dove.nome not in attesa.text
    biscotto = attesa.headers["set-cookie"]
    for pezzo in ("Secure", "HttpOnly", "SameSite=strict", "Path=/dispositivo/attesa"):
        assert pezzo.lower() in biscotto.lower(), pezzo
    assert tablet.get("/dispositivo/attesa/stato").json() == {"approvato": False}
    assert tablet.get("/dispositivo/attesa", headers={"accept": "text/html"}).text == attesa.text


def test_il_giro_completo_da_la_chiave_una_volta_sola(in_rete):
    tablet = _dalla_rete()
    tablet.get("/")
    pagina = tablet.get("/dispositivo/attesa", headers={"accept": "text/html"})
    numero = _id_di(in_rete, TABLET)
    computer = _computer()

    sbagliato = computer.post(f"/impostazioni/dispositivo/{numero}/codice",
                              data={"codice": "000000" if _codice(pagina.text) != "000000"
                                    else "111111"},
                              headers={"origin": "http://127.0.0.1:8080"})
    assert "codice_sbagliato" in sbagliato.headers["location"]
    assert tablet.get("/dispositivo/attesa/stato").json() == {"approvato": False}

    giusto = computer.post(f"/impostazioni/dispositivo/{numero}/codice",
                           data={"codice": _codice(pagina.text)},
                           headers={"origin": "http://127.0.0.1:8080"})
    assert "approvato=" in giusto.headers["location"]
    preso = tablet.get("/dispositivo/attesa/stato")
    assert preso.json() == {"vai": "/"}
    biscotto = preso.headers["set-cookie"]
    assert biscotto.startswith(dispositivi.BISCOTTO + "=")
    for pezzo in ("Secure", "HttpOnly", "SameSite=strict", "Path=/"):
        assert pezzo.lower() in biscotto.lower(), pezzo

    assert tablet.get("/", headers={"accept": "text/html"}).status_code == 200
    assert tablet.get("/dispositivo/attesa/stato").json() == {"vai": "/"}
    assert tablet.get("/dispositivo/attesa").headers["location"] == "/"

    stesso_indirizzo = _dalla_rete()
    assert stesso_indirizzo.get("/stato").status_code == 403
    nuova = stesso_indirizzo.get("/dispositivo/attesa", headers={"accept": "text/html"})
    assert stesso_indirizzo.get("/dispositivo/attesa/stato").json() == {"approvato": False}
    assert _codice(nuova.text) != _codice(pagina.text)


def test_l_indirizzo_finto_senza_chiave_resta_fuori(in_rete):
    segreto = _abbina(in_rete, _dalla_rete())
    finto = _dalla_rete()
    assert finto.get("/stato").status_code == 403
    finto.cookies.set(dispositivi.BISCOTTO, segreto[:-1] + ("A" if segreto[-1] != "A" else "B"))
    assert finto.get("/stato").status_code == 403
    vero = _dalla_rete()
    vero.cookies.set(dispositivi.BISCOTTO, segreto)
    assert vero.get("/stato").status_code == 200


def test_la_chiave_presa_da_un_altro_indirizzo_non_vale(in_rete):
    segreto = _abbina(in_rete, _dalla_rete())
    ladro = _dalla_rete(INTRUSO)
    ladro.cookies.set(dispositivi.BISCOTTO, segreto)
    assert ladro.get("/stato").status_code == 403


def test_l_intruso_sullo_stesso_indirizzo_non_prende_la_chiave_del_tablet(in_rete):
    tablet, intruso = _dalla_rete(), _dalla_rete()
    del_tablet = tablet.get("/dispositivo/attesa", headers={"accept": "text/html"})
    dell_intruso = intruso.get("/dispositivo/attesa", headers={"accept": "text/html"})
    assert _codice(del_tablet.text) != _codice(dell_intruso.text)
    _computer().post(f"/impostazioni/dispositivo/{_id_di(in_rete, TABLET)}/codice",
                     data={"codice": _codice(del_tablet.text)},
                     headers={"origin": "http://127.0.0.1:8080"})
    assert intruso.get("/dispositivo/attesa/stato").json() == {"approvato": False}
    assert dispositivi.BISCOTTO not in intruso.cookies
    assert tablet.get("/dispositivo/attesa/stato").json() == {"vai": "/"}


def test_nell_archivio_resta_solo_l_impronta_della_chiave(in_rete):
    segreto = _abbina(in_rete, _dalla_rete())
    with in_rete.lettura() as connessione:
        scritto = leggi_stato(connessione, dispositivi.CHIAVE_DEGLI_ABBINATI)
    numero = str(_id_di(in_rete, TABLET))
    assert scritto[numero]["impronta"] == hashlib.sha256(segreto.encode()).hexdigest()
    assert scritto[numero]["indirizzo"] == TABLET
    for file in in_rete.dove.database.parent.glob(in_rete.dove.database.name + "*"):
        assert segreto.encode() not in file.read_bytes(), file


def test_un_dispositivo_approvato_prima_va_riapprovato_una_volta(in_rete):
    _dalla_rete().get("/")
    with in_rete.scrittura() as connessione:
        dispositivi.decidi(connessione, _id_di(in_rete, TABLET), "approvato", "tablet")
    vecchio = _dalla_rete()
    assert vecchio.get("/stato").status_code == 403
    assert vecchio.get("/", headers={"accept": "text/html"}).headers["location"] == \
        "/dispositivo/attesa"
    pagina = _computer().get("/impostazioni", headers={"accept": "text/html"}).text
    assert "da riapprovare una volta" in pagina
    assert f"/impostazioni/dispositivo/{_id_di(in_rete, TABLET)}/codice" in pagina
    _abbina(in_rete, vecchio)
    pagina = _computer().get("/impostazioni", headers={"accept": "text/html"}).text
    assert "da riapprovare una volta" not in pagina
    assert f"/impostazioni/dispositivo/{_id_di(in_rete, TABLET)}/codice" not in pagina


def test_rifiutato_o_dimenticato_perde_la_chiave(in_rete):
    tablet = _dalla_rete()
    segreto = _abbina(in_rete, tablet)
    numero = _id_di(in_rete, TABLET)
    computer = _computer()
    computer.post(f"/impostazioni/dispositivo/{numero}", data={"stato": "rifiutato"},
                  headers={"origin": "http://127.0.0.1:8080"})
    assert tablet.get("/stato").status_code == 403
    assert "rifiutato" in tablet.get("/stato").json()["messaggio"]
    assert tablet.get("/dispositivo/attesa").status_code == 403
    computer.post(f"/impostazioni/dispositivo/{numero}", data={"stato": "approvato"},
                  headers={"origin": "http://127.0.0.1:8080"})
    tablet.cookies.set(dispositivi.BISCOTTO, segreto)
    assert tablet.get("/stato").status_code == 403

    segreto = _abbina(in_rete, _dalla_rete())
    computer.post(f"/impostazioni/dispositivo/{numero}", data={"stato": "dimentica"},
                  headers={"origin": "http://127.0.0.1:8080"})
    di_nuovo = _dalla_rete()
    di_nuovo.cookies.set(dispositivi.BISCOTTO, segreto)
    assert di_nuovo.get("/stato").status_code == 403


def test_solo_il_computer_approva_col_codice(in_rete):
    tablet = _dalla_rete()
    _abbina(in_rete, tablet)
    altro = _dalla_rete(INTRUSO)
    pagina = altro.get("/dispositivo/attesa", headers={"accept": "text/html"})
    risposta = tablet.post(f"/impostazioni/dispositivo/{_id_di(in_rete, INTRUSO)}/codice",
                           data={"codice": _codice(pagina.text)},
                           headers={"origin": "https://192.168.1.5:8443"})
    assert risposta.status_code == 403
    assert altro.get("/dispositivo/attesa/stato").json() == {"approvato": False}


def test_al_massimo_venti_dispositivi_in_attesa(in_rete):
    for numero in range(dispositivi.MASSIMO_IN_ATTESA):
        assert _dalla_rete(f"192.168.2.{numero + 1}").get("/").status_code == 403
    troppi = _dalla_rete("192.168.3.1").get("/")
    assert troppi.status_code == 403
    assert "troppi" in troppi.json()["messaggio"]
    with in_rete.lettura() as connessione:
        assert dispositivi.in_attesa(connessione) == dispositivi.MASSIMO_IN_ATTESA
        assert dispositivi.trova(connessione, "192.168.3.1") is None


def test_chi_bussa_scrive_al_massimo_una_volta_al_minuto(in_rete, monkeypatch):
    orologio = SimpleNamespace(adesso=1000.0)
    monkeypatch.setattr(dispositivi.time, "monotonic", lambda: orologio.adesso)
    scritture = []
    vera = type(in_rete).scrittura

    def contata(archivio):
        scritture.append(1)
        return vera(archivio)

    monkeypatch.setattr(type(in_rete), "scrittura", contata)
    tablet = _dalla_rete()
    for _ in range(10):
        tablet.get("/")
    assert len(scritture) == 1
    orologio.adesso += dispositivi.OGNI_QUANTO_SI_SCRIVE
    tablet.get("/")
    assert len(scritture) == 2
    monkeypatch.setattr(type(in_rete), "scrittura", vera)
    with in_rete.lettura() as connessione:
        assert dispositivi.trova(connessione, TABLET)["contatti"] == 11


def test_le_attese_hanno_un_limite_per_indirizzo(in_rete):
    for _ in range(dispositivi.ATTESE_PER_INDIRIZZO + 2):
        _dalla_rete().get("/dispositivo/attesa", headers={"accept": "text/html"})
    aperte = dispositivi.attese_aperte()
    assert aperte[_id_di(in_rete, TABLET)] == dispositivi.ATTESE_PER_INDIRIZZO


def test_le_impostazioni_mostrano_indirizzo_e_impronta_del_certificato(in_rete):
    pagina = _computer().get("/impostazioni", headers={"accept": "text/html"}).text
    assert "si apre quando" in pagina
    origine.segna_la_rete(8443, "ab" * 32)
    try:
        pagina = _computer().get("/impostazioni", headers={"accept": "text/html"}).text
    finally:
        origine.smetti_la_rete()
    assert ":".join(["AB"] * 32) in pagina
    assert "SHA-256" in pagina
    assert "https://" in pagina


@pytest.fixture
def casa(tmp_path, monkeypatch):
    from officina import modelli_in_casa
    from officina.archivio import accesso
    from officina.programma import avvio, carta, librerie
    from officina.programma import segreti as custode

    monkeypatch.setenv("OFFICINA_CASA_PROGRAMMA", str(tmp_path / "casa"))
    monkeypatch.delenv("OFFICINA_ARCHIVIO", raising=False)
    monkeypatch.setattr(carta, "cartella_della_versione_1", lambda: tmp_path / "nessuna")
    monkeypatch.setattr(avvio, "PORTA_PREFERITA", 0)
    monkeypatch.setattr(avvio, "PORTA_DELLA_RETE", 0)
    monkeypatch.setattr(librerie, "cosa_manca", lambda richieste=None: [])
    monkeypatch.setattr(modelli_in_casa, "mancano_gli_obbligatori", lambda dove=None: [])
    monkeypatch.setattr(custode, "si_puo_custodire", lambda: False)
    accesso.chiudi(con_copia=False)
    yield tmp_path
    accesso.chiudi(con_copia=False)
    from officina.web import sfoglia

    sfoglia.imposta_chi_sceglie(None)


def test_la_rete_si_apre_cifrata_e_la_finestra_resta_in_chiaro(casa):
    from officina.archivio import accesso
    from officina.impostazioni import REALE
    from officina.programma import avvio, carta, scheda

    carta.comincia_da_zero()
    carta.aggiorna(obblighi_sospesi=True, chiave_chiesta=True)
    accesso.apri(REALE).imposta("accesso_dalla_rete", True)
    accesso.chiudi(con_copia=False)
    programma = avvio.Programma(webview=SimpleNamespace(), esamina=scheda.Esame)
    try:
        indirizzo = programma.accendi()
        assert indirizzo.startswith("http://127.0.0.1:")
        assert "/entra?t=" + origine.chiave_della_finestra() in indirizzo
        assert programma.servitore.host == "127.0.0.1"
        di_rete = programma.servitore_di_rete
        assert di_rete is not None and di_rete.host == "0.0.0.0"
        assert origine.la_rete()["porta"] == di_rete.porta

        cartella = carta.casa() / "rete"
        pem = (cartella / "fisso.pem").read_text(encoding="ascii")
        if sys.platform != "win32":
            assert (cartella / "fisso.chiave.pem").stat().st_mode & 0o077 == 0
        der = ssl.PEM_cert_to_DER_cert(pem)
        assert origine.la_rete()["impronta"] == hashlib.sha256(der).hexdigest()

        contesto = ssl.create_default_context(cadata=pem)
        contesto.check_hostname = False
        cifrata = http.client.HTTPSConnection("127.0.0.1", di_rete.porta, context=contesto,
                                              timeout=20)
        cifrata.request("GET", "/stato")
        risposta = cifrata.getresponse()
        assert risposta.status == 403
        assert "sua finestra" in risposta.read().decode("utf-8")
        cifrata.close()

        in_chiaro = http.client.HTTPConnection("127.0.0.1", di_rete.porta, timeout=5)
        with pytest.raises((http.client.HTTPException, OSError)):
            in_chiaro.request("GET", "/stato")
            in_chiaro.getresponse().read()
        in_chiaro.close()
    finally:
        programma.spegni()
    assert origine.la_rete() is None
    assert not programma.servitore_di_rete.gira
