from __future__ import annotations


def test_tutti_i_risultati_non_ha_un_tetto(archivio_pieno):
    from officina.modello import scatti

    connessione = archivio_pieno.connessione
    filtro = scatti.Filtro()
    numeri = scatti.soli_numeri(connessione, filtro)
    assert len(numeri) == scatti.conta(connessione, filtro)
    assert numeri == [s["id"] for s in scatti.pagina(connessione, filtro, 0, len(numeri) + 1)]
