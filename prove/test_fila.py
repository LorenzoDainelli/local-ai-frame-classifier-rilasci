from __future__ import annotations

import pytest

from officina.archivio.database import tutti, uno
from officina.modello import scatti
from officina.modello.scatti import Filtro


def alla_vecchia(connessione, filtro: Filtro, scatto_id: int) -> dict:
    dove, parametri = scatti._condizioni(connessione, filtro)
    numeri = [riga["id"] for riga in tutti(
        connessione,
        f"SELECT s.id FROM scatti s WHERE ({dove}) OR s.id = ? "
        f"ORDER BY {scatti._ordinamento(filtro)}",
        *parametri, scatto_id)]
    if scatto_id not in numeri:
        return {"prima": None, "dopo": None, "posizione": None,
                "totale": len(numeri)}
    dentro = uno(connessione,
                 f"SELECT s.id FROM scatti s WHERE ({dove}) AND s.id = ?",
                 *parametri, scatto_id) is not None
    indice = numeri.index(scatto_id)
    return {
        "prima": numeri[indice - 1] if indice > 0 else None,
        "dopo": numeri[indice + 1] if indice + 1 < len(numeri) else None,
        "posizione": indice + 1 if dentro else None,
        "totale": len(numeri) if dentro else len(numeri) - 1,
    }


FILTRI = [
    Filtro(),
    Filtro(ordine="data_su"),
    Filtro(genere="video"),
    Filtro(senza_etichetta=True),
    Filtro(senza_data=True),
    Filtro(solo_schermate=True),
    Filtro(escludi_schermate=True),
    Filtro(fuori_archivio=True),
    Filtro(col_cuore=True),
]


def _da_provare(connessione) -> list[int]:
    quali = [riga["id"] for riga in tutti(
        connessione, "SELECT id FROM scatti ORDER BY istante_utc DESC LIMIT 4")]
    quali += [riga["id"] for riga in tutti(
        connessione, "SELECT id FROM scatti ORDER BY istante_utc ASC LIMIT 4")]
    quali += [riga["id"] for riga in tutti(
        connessione, "SELECT id FROM scatti WHERE istante_utc IS NULL ORDER BY id LIMIT 4")]
    quali += [riga["id"] for riga in tutti(
        connessione, "SELECT id FROM scatti ORDER BY id LIMIT 8")]
    return list(dict.fromkeys(quali))


@pytest.mark.parametrize("filtro", FILTRI, ids=lambda f: f.ordine + (
    "-video" if f.genere else "-da_fare" if f.senza_etichetta
    else "-senza_data" if f.senza_data else "-schermate" if f.solo_schermate
    else "-no_schermate" if f.escludi_schermate else "-fuori" if f.fuori_archivio
    else "-cuore" if f.col_cuore else ""))
def test_le_due_strade_danno_gli_stessi_vicini(archivio_pieno, filtro):
    with archivio_pieno.lettura() as connessione:
        for scatto_id in _da_provare(connessione):
            assert scatti.vicini(connessione, filtro, scatto_id) == \
                alla_vecchia(connessione, filtro, scatto_id), (
                    f"scatto {scatto_id} con filtro {filtro}")


def test_anche_quando_lo_scatto_e_uscito_dal_filtro(archivio_pieno):
    with archivio_pieno.scrittura() as connessione:
        from officina.modello import nodi
        nodo = nodi.crea(connessione, "un nodo")
        riga = connessione.execute(
            "SELECT id FROM scatti WHERE fuori_archivio = 0 "
            "ORDER BY istante_utc DESC LIMIT 1 OFFSET 2").fetchone()
        connessione.execute(
            "INSERT INTO etichette (scatto_id, nodo_id, stato, origine, creata_il) "
            "VALUES (?, ?, 'si', 'utente', '2024-01-01T00:00:00Z')",
            (riga["id"], nodo))
    filtro = Filtro(senza_etichetta=True)
    with archivio_pieno.lettura() as connessione:
        adesso = scatti.vicini(connessione, filtro, riga["id"])
        assert adesso == alla_vecchia(connessione, filtro, riga["id"])
        assert adesso["posizione"] is None
        assert adesso["dopo"] is not None


def test_uno_scatto_che_non_esiste(archivio_pieno):
    with archivio_pieno.lettura() as connessione:
        assert scatti.vicini(connessione, Filtro(), 10 ** 9) == {
            "prima": None, "dopo": None, "posizione": None, "totale": 0}


def test_l_ordine_per_somiglianza_passa_dalla_strada_lunga(archivio_pieno):
    with archivio_pieno.lettura() as connessione:
        quali = [riga["id"] for riga in tutti(
            connessione, "SELECT id FROM scatti ORDER BY id LIMIT 4")]
        filtro = Filtro(ordine="somiglianza", simili_ids=quali, simili_a=quali[0])
        adesso = scatti.vicini(connessione, filtro, quali[1])
        assert adesso["prima"] == quali[0]
        assert adesso["dopo"] == quali[2]


def test_la_prova_saprebbe_accorgersene(archivio_pieno):
    import inspect
    sorgente = inspect.getsource(scatti.vicini)
    assert "_chi_confina" in sorgente, (
        "vicini non passa più dalla strada corta: il confronto qui sopra "
        "starebbe confrontando la strada lunga con se stessa")
