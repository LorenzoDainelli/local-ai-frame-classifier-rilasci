import re
import threading
from pathlib import Path

from fastapi.testclient import TestClient


def test_nessuna_lettura_aspetta_chi_scrive(archivio_pieno):
    from officina.web import server

    testo = "".join(foglio.read_text(encoding="utf-8")
                    for foglio in (Path(server.__file__).parent / "strade").glob("*.py"))
    strade = sorted(set(re.findall(r'@strada\.get\("(/[^"{]*)"', testo)))
    strade += ["/scatto/1", "/api/officina/1", "/miniatura/1", "/persona/1"]
    cliente = TestClient(server.app, client=("127.0.0.1", 51000), follow_redirects=False)
    for dove in strade:
        try:
            cliente.get(dove)
        except Exception:
            pass
    preso, lascia = threading.Event(), threading.Event()

    def scrive():
        with archivio_pieno.scrittura():
            preso.set()
            lascia.wait(600)

    threading.Thread(target=scrive, daemon=True).start()
    preso.wait(5)
    lente = []
    for dove in strade:
        if dove.startswith("/statici") or "eventi" in dove or "flusso" in dove:
            continue
        esito = {}

        def chiedi():
            try:
                esito["c"] = cliente.get(dove).status_code
            except Exception as e:
                esito["c"] = type(e).__name__

        filo = threading.Thread(target=chiedi, daemon=True)
        filo.start()
        filo.join(3)
        if filo.is_alive():
            lente.append(dove)
    lascia.set()
    assert not lente, f"aspettano chi scrive: {lente}"
