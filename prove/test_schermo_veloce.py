from __future__ import annotations

import http.client
import time

from officina.schermo import collega
from officina.schermo import porta as porta_mod
from prove.test_schermo import _abbina, _vicino, casa, porta  # noqa: F401


def _ponte(porta):  # noqa: F811
    fisso = _abbina(porta)
    ponte = collega.Ponte(fisso, collega.entra(fisso, "cavallo-batteria"))
    ponte.parti()
    return ponte


def test_il_ponte_risponde_senza_aspettare_il_pacchetto_dopo(porta, archivio_pieno):  # noqa: F811
    ponte = _ponte(porta)
    try:
        vicino, biscotto = _vicino(ponte)
        vicino.request("GET", "/statici/css/telaio.css", headers=biscotto)
        vicino.getresponse().read()
        partito = time.perf_counter()
        for _ in range(20):
            vicino.request("GET", "/statici/css/telaio.css", headers=biscotto)
            vicino.getresponse().read()
        assert (time.perf_counter() - partito) / 20 < 0.03
    finally:
        ponte.ferma()


def test_le_connessioni_cifrate_verso_il_fisso_si_riusano(porta, archivio_pieno, monkeypatch):  # noqa: F811
    ponte = _ponte(porta)
    aperte = []
    vera = collega._connessione
    monkeypatch.setattr(collega, "_connessione",
                        lambda *a, **k: (aperte.append(1), vera(*a, **k))[1])
    try:
        _, biscotto = _vicino(ponte)
        for _ in range(10):
            nuova = http.client.HTTPConnection("127.0.0.1", ponte.porta_locale, timeout=30)
            nuova.request("GET", "/statici/css/telaio.css", headers=biscotto)
            risposta = nuova.getresponse()
            risposta.read()
            assert risposta.status == 200
            nuova.close()
        assert len(aperte) <= 2
    finally:
        ponte.ferma()
    assert ponte._tenute == []


def test_una_connessione_ferma_da_troppo_non_si_riusa(porta, archivio_pieno, monkeypatch):  # noqa: F811
    ponte = _ponte(porta)
    try:
        vicino, biscotto = _vicino(ponte)
        vicino.request("GET", "/statici/css/telaio.css", headers=biscotto)
        vicino.getresponse().read()
        aperte = []
        vera = collega._connessione
        monkeypatch.setattr(collega, "_connessione",
                            lambda *a, **k: (aperte.append(1), vera(*a, **k))[1])
        adesso = time.monotonic()
        monkeypatch.setattr(collega.time, "monotonic",
                            lambda: adesso + collega.RIPOSO_MASSIMO + 1)
        vicino.request("GET", "/statici/css/telaio.css", headers=biscotto)
        risposta = vicino.getresponse()
        risposta.read()
        assert risposta.status == 200
        assert len(aperte) == 1
    finally:
        ponte.ferma()


def test_il_codice_del_programma_arriva_compresso_e_si_puo_tenere(porta, archivio_pieno):  # noqa: F811
    ponte = _ponte(porta)
    try:
        vicino, biscotto = _vicino(ponte)
        vicino.request("GET", "/statici/css/telaio.css",
                       headers={"accept-encoding": "gzip", **biscotto})
        risposta = vicino.getresponse()
        risposta.read()
        assert risposta.getheader("content-encoding") == "gzip"
        assert risposta.getheader("cache-control") != "no-store"
        vicino.request("GET", "/stato", headers={"accept-encoding": "gzip", **biscotto})
        risposta = vicino.getresponse()
        risposta.read()
        assert risposta.getheader("content-encoding") is None
        assert risposta.getheader("cache-control") == "no-store"
    finally:
        ponte.ferma()


def test_il_fisso_tiene_aperte_le_connessioni_piu_del_riposo_del_portatile():
    assert porta_mod.TIENI_APERTA > collega.RIPOSO_MASSIMO


def _una_miniatura(archivio) -> int:
    with archivio.lettura() as connessione:
        return connessione.execute(
            "SELECT id FROM file_media WHERE scatto_id IS NOT NULL ORDER BY id LIMIT 1").fetchone()[0]


def _chiedi(vicino, biscotto, metodo, percorso):
    vicino.request(metodo, percorso, headers=biscotto)
    risposta = vicino.getresponse()
    return risposta, risposta.read()


def test_le_miniature_restano_solo_nella_memoria_del_ponte(porta, archivio_pieno, monkeypatch):  # noqa: F811
    ponte = _ponte(porta)
    try:
        vicino, biscotto = _vicino(ponte)
        _chiedi(vicino, biscotto, "GET", "/")
        percorso = f"/miniatura/{_una_miniatura(archivio_pieno)}"
        prima, dati = _chiedi(vicino, biscotto, "GET", percorso)
        assert prima.status == 200 and dati
        assert prima.getheader("cache-control") == "no-store"
        chieste = []
        vera = ponte._verso_il_fisso
        monkeypatch.setattr(ponte, "_verso_il_fisso", lambda: (chieste.append(1), vera())[1])
        dopo, di_nuovo = _chiedi(vicino, biscotto, "GET", percorso)
        assert dopo.status == 200 and di_nuovo == dati and chieste == []
        assert dopo.getheader("cache-control") == "no-store"
        assert dopo.getheader("content-type") == prima.getheader("content-type")
    finally:
        ponte.ferma()
    assert ponte._miniature == {} and ponte._peso_miniature == 0


def test_ogni_modifica_svuota_le_miniature_tenute(porta, archivio_pieno):  # noqa: F811
    ponte = _ponte(porta)
    try:
        vicino, biscotto = _vicino(ponte)
        _chiedi(vicino, biscotto, "GET", "/")
        _chiedi(vicino, biscotto, "GET", f"/miniatura/{_una_miniatura(archivio_pieno)}")
        assert len(ponte._miniature) == 1
        _chiedi(vicino, biscotto, "POST", "/api/niente-di-niente")
        assert len(ponte._miniature) == 0
    finally:
        ponte.ferma()


def test_senza_il_fisso_le_miniature_tenute_non_si_mostrano(porta, archivio_pieno, monkeypatch):  # noqa: F811
    ponte = _ponte(porta)
    try:
        vicino, biscotto = _vicino(ponte)
        _chiedi(vicino, biscotto, "GET", "/")
        percorso = f"/miniatura/{_una_miniatura(archivio_pieno)}"
        _chiedi(vicino, biscotto, "GET", percorso)
        assert ponte._miniatura_tenuta(percorso) is not None
        monkeypatch.setattr(collega.time, "monotonic",
                            lambda vera=time.monotonic: vera() + collega.FISSO_SENTITO_DA + 1)
        assert ponte._miniatura_tenuta(percorso) is None
        ponte._segna_chiuso()
        assert ponte._miniature == {}
    finally:
        ponte.ferma()


def test_la_memoria_delle_miniature_ha_un_tetto(porta, archivio_pieno, monkeypatch):  # noqa: F811
    ponte = _ponte(porta)
    try:
        monkeypatch.setattr(collega, "MINIATURE_AL_MASSIMO", 250)
        for numero in range(10):
            ponte._tieni_la_miniatura(f"/miniatura/{numero}", 200, "OK", [], b"x" * 100)
        assert ponte._peso_miniature <= 250
        assert list(ponte._miniature) == ["/miniatura/8", "/miniatura/9"]
    finally:
        ponte.ferma()
