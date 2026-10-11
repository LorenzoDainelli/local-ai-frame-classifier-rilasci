from __future__ import annotations

from officina.modello import nodi


def test_un_genitore_si_puo_usare_anche_da_solo(archivio):
    from fastapi.testclient import TestClient

    from officina.apprendimento import proposte
    from officina.web import server
    from officina.web.strade import comune

    with archivio.scrittura() as connessione:
        radice = nodi.crea(connessione, "Animali", None)
        cane = nodi.crea(connessione, "Cane", radice)
        nodi.crea(connessione, "Bassotto", cane)

    comune.bottega = proposte.Bottega()
    cliente = TestClient(server.app, client=("127.0.0.1", 51000))
    assert cliente.get(f"/api/albero/nodo/{cane}").json()["da_solo"] is False
    assert cliente.post("/api/albero/da-solo",
                        data={"nodo_id": cane, "acceso": "1"}).json()["fatto"]
    assert cliente.get(f"/api/albero/nodo/{cane}").json()["da_solo"] is True
    forma = {voce["id"]: voce for voce in cliente.get("/api/albero").json()["nodi"]}
    assert forma[cane]["da_solo"] is True
    assert forma[radice]["da_solo"] is False
    assert cliente.post("/api/albero/da-solo",
                        data={"nodo_id": cane, "acceso": "0"}).json()["fatto"]
    assert cliente.get(f"/api/albero/nodo/{cane}").json()["da_solo"] is False
