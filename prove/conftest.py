from __future__ import annotations

import ipaddress
import os
from pathlib import Path

import pytest

CHIAVI_DELLE_PROVE = {"attive": True}
_segreti_dei_dispositivi: dict[tuple[str, int], str] = {}


def pytest_configure(config):
    import tempfile
    import urllib.request

    os.environ.setdefault("OFFICINA_NOMI_AMMESSI", "testserver")
    os.environ.setdefault("OFFICINA_CASA_PROGRAMMA",
                          tempfile.mkdtemp(prefix="casa-programma-"))
    config.addinivalue_line(
        "filterwarnings",
        "error::pytest.PytestUnhandledThreadExceptionWarning")
    urllib.request.install_opener(
        urllib.request.build_opener(urllib.request.HTTPCookieProcessor()))
    _i_clienti_di_prova_entrano_come_la_finestra()


def _segreto_del_dispositivo(indirizzo: str) -> str | None:
    import secrets

    from officina.archivio import accesso
    from officina.errori import ErroreOfficina
    from officina.modello import dispositivi

    try:
        archivio = accesso.aperto()
    except ErroreOfficina:
        return None
    with archivio.scrittura() as connessione:
        riga = dispositivi.trova(connessione, indirizzo)
        if riga is None or riga["stato"] != "approvato":
            return None
        chiave = (str(archivio.dove.database), riga["id"])
        segreto = _segreti_dei_dispositivi.get(chiave)
        if segreto and dispositivi.e_lui(connessione, riga, segreto):
            return segreto
        segreto = secrets.token_urlsafe(32)
        dispositivi.abbina(connessione, riga["id"], indirizzo, segreto)
        _segreti_dei_dispositivi[chiave] = segreto
        return segreto


def _metti_le_chiavi(richiesta, indirizzo: str) -> None:
    from officina.modello import dispositivi
    from officina.web import origine

    if not CHIAVI_DELLE_PROVE["attive"]:
        return
    try:
        ip = ipaddress.ip_address(indirizzo)
    except ValueError:
        return
    if ip.is_loopback:
        biscotto = f"{origine.BISCOTTO_DELLA_FINESTRA}={origine.chiave_della_finestra()}"
    else:
        segreto = _segreto_del_dispositivo(indirizzo)
        if segreto is None:
            return
        biscotto = f"{dispositivi.BISCOTTO}={segreto}"
    gia = richiesta.headers.get("cookie")
    richiesta.headers["cookie"] = f"{gia}; {biscotto}" if gia else biscotto


def _i_clienti_di_prova_entrano_come_la_finestra() -> None:
    from starlette.testclient import TestClient

    partenza_vera = TestClient.__init__

    def partenza(self, app, base_url="http://testserver", *argomenti, **parole):
        indirizzo = (parole.get("client") or ("testclient", 50000))[0]
        try:
            dalla_rete = not ipaddress.ip_address(indirizzo).is_loopback
        except ValueError:
            dalla_rete = False
        if CHIAVI_DELLE_PROVE["attive"] and dalla_rete and base_url.startswith("http://"):
            base_url = "https://" + base_url[len("http://"):]
        partenza_vera(self, app, base_url, *argomenti, **parole)
        self.event_hooks["request"].append(
            lambda richiesta: _metti_le_chiavi(richiesta, indirizzo))

    TestClient.__init__ = partenza


@pytest.fixture
def senza_chiavi_delle_prove(monkeypatch):
    from officina.modello import dispositivi

    monkeypatch.setitem(CHIAVI_DELLE_PROVE, "attive", False)
    dispositivi.dimentica_le_attese()
    yield
    dispositivi.dimentica_le_attese()


@pytest.fixture(autouse=True)
def lavori_nello_stesso_processo(monkeypatch):
    from officina.web import in_disparte

    monkeypatch.setattr(in_disparte, "A_PARTE", False)


@pytest.fixture(autouse=True)
def il_giro_non_resta_aperto():
    import sys

    yield
    giro = sys.modules.get("officina.web.giro")
    if giro is not None:
        giro.stato.passo = None
        giro.stato.cartella_foto = None
        giro.stato.lo_ha_fatto_il_giro = False


@pytest.fixture(autouse=True, scope="session")
def senza_la_data_di_windows():
    from officina.importazione import metadati

    metadati.CON_LA_DATA_DEL_FILE = False
    yield


@pytest.fixture(scope="session")
def cartella_foto(tmp_path_factory) -> Path:
    from officina.finto import generatore

    dove = tmp_path_factory.mktemp("foto-finte")
    generatore.genera(dove, quanti=24, seme=42, leggero=True)
    return dove


@pytest.fixture(scope="session")
def rapporto_finto(cartella_foto) -> "object":
    from officina.finto import generatore

    return generatore.piano(24, __import__("random").Random(42))


@pytest.fixture
def archivio(tmp_path, monkeypatch):
    from officina.archivio import accesso

    monkeypatch.setenv("OFFICINA_ARCHIVIO", str(tmp_path / "archivio"))
    accesso.chiudi(con_copia=False)
    aperto = accesso.apri("finto")
    yield aperto
    accesso.chiudi(con_copia=False)


@pytest.fixture(scope="session")
def archivio_gia_importato(tmp_path_factory, cartella_foto) -> Path:
    from officina.archivio import accesso
    from officina.importazione.motore import Motore

    dove = tmp_path_factory.mktemp("archivio-modello")
    vecchio = os.environ.get("OFFICINA_ARCHIVIO")
    os.environ["OFFICINA_ARCHIVIO"] = str(dove)
    accesso.chiudi(con_copia=False)
    try:
        aperto = accesso.apri("finto")
        motore = Motore(aperto)
        motore.prepara([cartella_foto])
        motore.esegui()
    finally:
        accesso.chiudi(con_copia=False)
        if vecchio is None:
            os.environ.pop("OFFICINA_ARCHIVIO", None)
        else:
            os.environ["OFFICINA_ARCHIVIO"] = vecchio
    return dove


@pytest.fixture
def archivio_pieno(tmp_path, monkeypatch, archivio_gia_importato):
    import shutil

    from officina.archivio import accesso

    mio = tmp_path / "archivio"
    shutil.copytree(archivio_gia_importato, mio)
    monkeypatch.setenv("OFFICINA_ARCHIVIO", str(mio))
    accesso.chiudi(con_copia=False)
    aperto = accesso.apri("finto")
    yield aperto
    accesso.chiudi(con_copia=False)


@pytest.fixture
def connessione(archivio):
    return archivio.connessione


@pytest.fixture(scope="session")
def cartella_foto_grande(tmp_path_factory) -> Path:
    from officina.finto import generatore

    dove = tmp_path_factory.mktemp("foto-finte-grandi")
    generatore.genera(dove, quanti=56, seme=17, leggero=True)
    return dove


@pytest.fixture(scope="session")
def archivio_con_impronte(tmp_path_factory, cartella_foto_grande) -> Path:
    import os

    from officina.archivio import accesso
    from officina.finto import etichette
    from officina.importazione.motore import Motore
    from officina.impronte.motore import Passata

    dove = tmp_path_factory.mktemp("archivio-con-impronte")
    vecchio = os.environ.get("OFFICINA_ARCHIVIO")
    os.environ["OFFICINA_ARCHIVIO"] = str(dove)
    accesso.chiudi(con_copia=False)
    try:
        aperto = accesso.apri("finto")
        motore = Motore(aperto)
        motore.prepara([cartella_foto_grande])
        motore.esegui()
        etichette.metti(aperto, cartella_foto_grande)
        Passata(aperto, "disegnato", fotogrammi_per_video=4).esegui()
    finally:
        accesso.chiudi(con_copia=False)
        if vecchio is None:
            os.environ.pop("OFFICINA_ARCHIVIO", None)
        else:
            os.environ["OFFICINA_ARCHIVIO"] = vecchio
    return dove


@pytest.fixture
def archivio_misurabile(tmp_path, monkeypatch, archivio_con_impronte):
    import shutil

    from officina.archivio import accesso

    mio = tmp_path / "archivio"
    shutil.copytree(archivio_con_impronte, mio)
    monkeypatch.setenv("OFFICINA_ARCHIVIO", str(mio))
    accesso.chiudi(con_copia=False)
    aperto = accesso.apri("finto")
    yield aperto
    accesso.chiudi(con_copia=False)


def tutto_pronto_per_il_telefono(archivio) -> None:
    from officina.archivio.database import adesso

    with archivio.scrittura() as connessione:
        connessione.execute(
            "INSERT INTO nodi (nome, creato_il) VALUES ('pronti_per_il_telefono', ?)",
            (adesso(),))
        nodo = connessione.execute("SELECT last_insert_rowid()").fetchone()[0]
        connessione.execute(
            "INSERT OR IGNORE INTO etichette (scatto_id, nodo_id, stato, origine, creata_il) "
            "SELECT id, ?, 'si', 'utente', ? FROM scatti", (nodo, adesso()))
