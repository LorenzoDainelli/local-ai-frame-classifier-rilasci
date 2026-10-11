import threading
import time

from fastapi.testclient import TestClient


import pytest


@pytest.mark.parametrize("pagina", ["/?persona=1&genere=foto", "/persone", "/stato", "/lavoro",
                                    "/impostazioni", "/novita", "/scatto/1", "/api/officina/1"])
def test_le_pagine_non_aspettano_chi_scrive(archivio_pieno, pagina):
    from officina.web import server

    assert not archivio_pieno.di_prova
    cliente = TestClient(server.app, client=("127.0.0.1", 51000))
    cliente.get("/?persona=1")
    preso, lascia = threading.Event(), threading.Event()

    def scrive_a_lungo():
        with archivio_pieno.scrittura():
            preso.set()
            lascia.wait(30)

    filo = threading.Thread(target=scrive_a_lungo, daemon=True)
    filo.start()
    preso.wait(5)
    try:
        partenza = time.monotonic()
        risposta = cliente.get(pagina)
        durata = time.monotonic() - partenza
    finally:
        lascia.set()
        filo.join(5)
    assert risposta.status_code in (200, 303)
    assert durata < 5, durata
