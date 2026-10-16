from __future__ import annotations

from officina.misura import rapporto as resoconto
from officina.web import stato_a_parole


def _righe(massimo, media):
    return {"righe": [
        {"inquadratura": "intera", "azzecca": 0.9},
        {"inquadratura": "caselle · massimo", "azzecca": massimo},
        {"inquadratura": "caselle · media", "azzecca": media},
    ]}


def test_vince_chi_sbaglia_meno():
    assert resoconto.modo_vincente(_righe(0.8, 0.7)) == "massimo"
    assert resoconto.modo_vincente(_righe(0.6, 0.75)) == "media"


def test_il_pareggio_non_cambia_niente():
    assert resoconto.modo_vincente(_righe(0.705, 0.70)) is None
    assert resoconto.modo_vincente({"righe": []}) is None
    assert resoconto.modo_vincente({}) is None


def test_misura_mai_fatta_solo_con_abbastanza_decisi():
    assert stato_a_parole.misura_da_rifare(None, 10) is None
    assert stato_a_parole.misura_da_rifare(None, 60)["titolo"].startswith("La misura")


def test_misura_vecchia_quando_i_decisi_crescono():
    ultima = {"fatta_il": "2026-01-02T10:00:00", "scatti": 100}
    assert stato_a_parole.misura_da_rifare(ultima, 140) is None
    vecchia = stato_a_parole.misura_da_rifare(ultima, 160)
    assert vecchia and "2 gennaio 2026" in vecchia["testo"]


def test_il_tasto_mette_il_vincente(archivio_misurabile):
    import json

    from fastapi.testclient import TestClient

    from officina.web.server import app

    with archivio_misurabile.scrittura() as connessione:
        connessione.execute(
            "INSERT INTO misure (fatta_il, archivio, scatti, gruppi, nodi, rapporto) "
            "VALUES ('2026-01-02', 'finto', 50, 40, 2, ?)",
            (json.dumps(_righe(0.6, 0.8)),))
    archivio_misurabile.imposta("griglia_come_si_somma", "massimo")
    cliente = TestClient(app, client=("127.0.0.1", 5000))
    risposta = cliente.post("/misura/usa-il-migliore", follow_redirects=False)
    assert risposta.status_code == 303
    assert archivio_misurabile.impostazione("griglia_come_si_somma") == "media"
