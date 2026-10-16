from __future__ import annotations

import shutil

import pytest
from PIL import Image

from officina.archivio.database import uno
from officina.importazione import impronta
from officina.importazione.motore import Motore

PESANTI = ((impronta, "del_file"), (Image, "open"), (shutil, "copy2"),
           (shutil, "copyfile"), (shutil, "copyfileobj"), (shutil, "move"))


@pytest.fixture
def con_l_archivio_chiuso(archivio, monkeypatch):
    presi: list[str] = []

    def guarda(nome, vera):
        def avvolta(*argomenti, **nominati):
            if archivio._lucchetto._is_owned():
                presi.append(nome)
            return vera(*argomenti, **nominati)
        return avvolta

    for modulo, nome in PESANTI:
        monkeypatch.setattr(modulo, nome,
                            guarda(f"{modulo.__name__}.{nome}", getattr(modulo, nome)))
    return presi


def test_importare_non_legge_le_foto_mentre_tiene_chiuso_l_archivio(
        archivio, cartella_foto, con_l_archivio_chiuso):
    motore = Motore(archivio)
    motore.prepara([cartella_foto])
    motore.esegui()
    with archivio.lettura() as connessione:
        fatti = uno(connessione, "SELECT count(*) AS q, count(miniatura) AS m FROM file_media")
    assert fatti["q"] > 0 and fatti["m"] > 0
    assert con_l_archivio_chiuso == []
