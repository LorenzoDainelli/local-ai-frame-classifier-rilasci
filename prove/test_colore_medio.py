from __future__ import annotations

import io

from fastapi.testclient import TestClient
from PIL import Image

from officina.importazione import miniature


def test_il_colore_medio_si_legge_dalla_miniatura():
    appoggio = io.BytesIO()
    Image.new("RGB", (64, 48), (200, 40, 10)).save(appoggio, "JPEG", quality=95)
    colore = miniature.colore_di(appoggio.getvalue())
    rosso, verde, blu = (int(colore[i:i + 2], 16) for i in (1, 3, 5))
    assert abs(rosso - 200) < 8 and abs(verde - 40) < 8 and abs(blu - 10) < 8
    assert miniature.colore_di(b"non sono una foto") is None


def test_la_griglia_manda_il_colore_delle_miniature_gia_fatte(archivio_pieno):
    from officina.web import server

    cliente = TestClient(server.app, client=("127.0.0.1", 51000))
    primi = cliente.get("/api/griglia?quanti=4").json()["scatti"]
    for scatto in primi:
        assert cliente.get(f"/miniatura/{scatto['file_id']}").status_code == 200
    with archivio_pieno.scrittura() as connessione:
        connessione.execute("UPDATE file_media SET colore = NULL")
    dopo = cliente.get("/api/griglia?quanti=4").json()["scatti"]
    assert all(s["colore"] and s["colore"].startswith("#") for s in dopo)
    import time

    scadenza = time.monotonic() + 10
    salvati = 0
    while time.monotonic() < scadenza:
        with archivio_pieno.lettura() as connessione:
            salvati = connessione.execute(
                "SELECT count(*) FROM file_media WHERE colore IS NOT NULL").fetchone()[0]
        if salvati >= 4:
            break
        time.sleep(0.05)
    assert salvati >= 4
