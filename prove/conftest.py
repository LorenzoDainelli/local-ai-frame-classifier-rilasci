from __future__ import annotations

import os
from pathlib import Path

import pytest


def pytest_configure(config):
    import tempfile

    os.environ.setdefault("OFFICINA_NOMI_AMMESSI", "testserver")
    os.environ.setdefault("OFFICINA_CASA_PROGRAMMA",
                          tempfile.mkdtemp(prefix="casa-programma-"))
    config.addinivalue_line(
        "filterwarnings",
        "error::pytest.PytestUnhandledThreadExceptionWarning")


@pytest.fixture(autouse=True)
def lavori_nello_stesso_processo(monkeypatch):
    from officina.web import in_disparte

    monkeypatch.setattr(in_disparte, "A_PARTE", False)


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
