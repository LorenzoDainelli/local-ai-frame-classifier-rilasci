from __future__ import annotations

import http.client
import json
import threading
import urllib.parse
from pathlib import Path

import pytest

from prove.conftest import tutto_pronto_per_il_telefono
from prove.test_telefono_cavo import PAROLA, _lassu, _ritorno_sul_telefono, _uguali

from officina.modello import telefoni
from officina.schermo import CAVO, collega
from officina.schermo import porta as porta_mod
from officina.telefono import cavo, cavo_lontano, formato, lettore
from officina.web import telefono as pagina

SESSIONE = {"x-schermo-sessione": "prova"}


@pytest.fixture
def casa(tmp_path, monkeypatch):
    monkeypatch.setenv("OFFICINA_CASA_PROGRAMMA", str(tmp_path / "casa"))
    collega.segreti._in_memoria.clear()
    yield tmp_path / "casa"
    collega.segreti._in_memoria.clear()


@pytest.fixture
def porta_finta(casa, monkeypatch):
    nuova = porta_mod.Porta()
    monkeypatch.setattr(nuova, "_accendi_il_servitore", lambda: None)
    monkeypatch.setattr(nuova, "_accendi_l_ascolto", lambda: None)
    vecchia, porta_mod.porta = porta_mod.porta, nuova
    nuova.apri()
    nuova._sessioni["prova"] = porta_mod._Sessione("abc")
    yield nuova
    nuova.chiudi()
    porta_mod.porta = vecchia


@pytest.fixture
def telefono(archivio_pieno, tmp_path):
    tutto_pronto_per_il_telefono(archivio_pieno)
    with archivio_pieno.scrittura() as connessione:
        numero = telefoni.crea(connessione, "iPhone", "ios")
        telefoni.ricorda_cartella(connessione, numero, str(tmp_path / "Visore-iPhone"))
    return numero


@pytest.fixture
def iphone_sul_portatile(tmp_path):
    radice = tmp_path / "iphone-del-portatile"
    (radice / cavo.PACCHETTO).mkdir(parents=True)
    return radice


@pytest.fixture(autouse=True)
def banco_pulito():
    cavo_lontano.banco.chiudi()
    yield
    cavo_lontano.banco.chiudi()


def _dal_portatile():
    from fastapi.testclient import TestClient

    cliente = TestClient(porta_mod.app_della_porta)

    def al_fisso(metodo, percorso, corpo=None, tipo=None, in_file=None):
        intestazioni = dict(SESSIONE)
        if tipo:
            intestazioni["content-type"] = tipo
        risposta = cliente.request(metodo, percorso, content=corpo, headers=intestazioni)
        if in_file is not None and risposta.status_code == 200:
            Path(in_file).write_bytes(risposta.content)
            return 200, b""
        return risposta.status_code, risposta.content

    return al_fisso


def _mani(radice, quanti=None, quante=cavo_lontano.MANI, **finto):
    telefoni_finti: list[cavo.FintoTelefono] = []

    def collega_qui():
        telefoni_finti.append(cavo.FintoTelefono(radice, nome="iPhone del portatile",
                                                 **finto))
        return telefoni_finti[-1]

    mani = cavo_lontano.Mani(_dal_portatile(), collega_qui, quante)
    fermo = threading.Event()
    if quanti is not None:
        vero = mani._fai

        def fai_e_poi_muori(comando):
            if mani.fatti >= quanti:
                fermo.set()
                return {"errore": cavo.STACCATO, "codice": "cavo_staccato"}, None
            return vero(comando)

        mani._fai = fai_e_poi_muori
    filo = threading.Thread(target=mani.lavora, args=(fermo,), daemon=True)
    filo.start()
    return mani, filo, telefoni_finti


def _parti(archivio, telefono_id, dove) -> pagina.InCorso:
    in_corso = pagina.InCorso()
    assert in_corso.parti(archivio, telefono_id, dove, PAROLA, col_cavo=True, lontano=True)
    return in_corso


def test_dal_portatile_copia_tutto_e_sul_portatile_non_resta_niente(
        porta_finta, archivio_pieno, telefono, iphone_sul_portatile, tmp_path):
    dove = tmp_path / "Visore-iPhone"
    in_corso = _parti(archivio_pieno, telefono, dove)
    mani, filo, finti = _mani(iphone_sul_portatile)

    assert in_corso.lavoro.aspetta_che_finisca(120)
    detto = in_corso.come_va()
    assert not detto["guasto"], detto["guasto"]
    assert detto["cavo_completo"] and detto["cavo_lontano"]
    assert any("dal portatile" in riga for riga in detto["righe"])
    _uguali(dove, iphone_sul_portatile)
    with lettore.apri(_lassu(iphone_sul_portatile), PAROLA) as pacchetto:
        assert pacchetto.verifica().tutto_a_posto
    filo.join(30)
    assert not filo.is_alive()
    assert all(finto.chiuso for finto in finti)
    assert not mani._qui.exists()


def test_dal_portatile_due_mani_copiano_insieme(porta_finta, archivio_pieno, telefono,
                                               iphone_sul_portatile, tmp_path):
    dove = tmp_path / "Visore-iPhone"
    in_corso = _parti(archivio_pieno, telefono, dove)
    _, filo, finti = _mani(iphone_sul_portatile)

    assert in_corso.lavoro.aspetta_che_finisca(120)
    assert in_corso.cavo.completo, in_corso.come_va()
    filo.join(30)
    assert len(finti) == 2
    assert all(finto.caricati for finto in finti)
    assert all(finto.chiuso for finto in finti)
    _uguali(dove, iphone_sul_portatile)


def test_un_portatile_vecchio_con_una_mano_sola_copia_lo_stesso(
        porta_finta, archivio_pieno, telefono, iphone_sul_portatile, tmp_path):
    dove = tmp_path / "Visore-iPhone"
    in_corso = _parti(archivio_pieno, telefono, dove)
    _, filo, finti = _mani(iphone_sul_portatile, quante=1)

    assert in_corso.lavoro.aspetta_che_finisca(120)
    assert in_corso.cavo.completo, in_corso.come_va()
    filo.join(30)
    assert len(finti) == 1 and finti[0].chiuso
    _uguali(dove, iphone_sul_portatile)


def test_dal_portatile_il_ritorno_arriva_al_fisso(porta_finta, archivio_pieno, telefono,
                                                  iphone_sul_portatile, tmp_path):
    dove = tmp_path / "Visore-iPhone"
    in_corso = _parti(archivio_pieno, telefono, dove)
    _, filo, _ = _mani(iphone_sul_portatile)
    assert in_corso.lavoro.aspetta_che_finisca(120)
    filo.join(30)
    _ritorno_sul_telefono(dove, iphone_sul_portatile, tmp_path)

    assert in_corso.parti(archivio_pieno, telefono, dove, PAROLA, col_cavo=True,
                          lontano=True)
    _, filo, _ = _mani(iphone_sul_portatile)
    assert in_corso.lavoro.aspetta_che_finisca(120)
    detto = in_corso.come_va()
    assert not detto["guasto"], detto["guasto"]
    assert in_corso.esito.tornato.giornate_di_diario == 1
    assert detto["cavo_completo"]
    filo.join(30)


def test_dal_portatile_un_file_rovinato_tiene_chiuso_il_visore(
        porta_finta, archivio_pieno, telefono, iphone_sul_portatile, tmp_path):
    in_corso = _parti(archivio_pieno, telefono, tmp_path / "Visore-iPhone")
    _, filo, _ = _mani(iphone_sul_portatile, rovina={"foto"})

    assert in_corso.lavoro.aspetta_che_finisca(120)
    assert not in_corso.cavo.completo
    assert in_corso.cavo.guasti
    assert not (_lassu(iphone_sul_portatile) / formato.CARTA).exists()
    filo.join(30)


def test_se_il_portatile_non_risponde_lo_dice(porta_finta, archivio_pieno, telefono,
                                             tmp_path, monkeypatch):
    monkeypatch.setattr(cavo_lontano, "ATTESA_DEL_PORTATILE", 0.5)
    in_corso = _parti(archivio_pieno, telefono, tmp_path / "Visore-iPhone")

    assert in_corso.lavoro.aspetta_che_finisca(60)
    assert in_corso.come_va()["guasto"] == cavo_lontano.PORTATILE_ZITTO
    assert not cavo_lontano.banco.aperto


def test_se_il_portatile_muore_a_meta_il_visore_resta_chiuso_e_poi_riprende(
        porta_finta, archivio_pieno, telefono, iphone_sul_portatile, tmp_path, monkeypatch):
    dove = tmp_path / "Visore-iPhone"
    in_corso = _parti(archivio_pieno, telefono, dove)
    _, filo, _ = _mani(iphone_sul_portatile)
    assert in_corso.lavoro.aspetta_che_finisca(120)
    filo.join(30)
    lassu_mini = _lassu(iphone_sul_portatile) / formato.MINI
    for file in [m for m in sorted(lassu_mini.rglob("*")) if m.is_file()][:3]:
        file.write_bytes(b"corta")

    monkeypatch.setattr(cavo_lontano, "ATTESA_DI_UN_COMANDO", 1.0)
    monkeypatch.setattr(pagina, "ASPETTO_AL_MASSIMO", 1.0)
    monkeypatch.setattr(pagina, "UNA_PROVA", 0.3)
    monkeypatch.setattr(pagina, "PAUSA_TRA_LE_PROVE", 0.05)
    assert in_corso.parti(archivio_pieno, telefono, dove, PAROLA, col_cavo=True,
                          lontano=True)
    _, filo, _ = _mani(iphone_sul_portatile, quanti=20)
    assert in_corso.lavoro.aspetta_che_finisca(120)
    assert in_corso.come_va()["guasto"]
    filo.join(30)
    lassu = json.loads((_lassu(iphone_sul_portatile) / formato.CARTA).read_text("utf-8"))
    assert lassu["stato"] == formato.INTERROTTO

    monkeypatch.setattr(cavo_lontano, "ATTESA_DI_UN_COMANDO", 120.0)
    assert in_corso.parti(archivio_pieno, telefono, dove, PAROLA, col_cavo=True,
                          lontano=True)
    _, filo, _ = _mani(iphone_sul_portatile)
    assert in_corso.lavoro.aspetta_che_finisca(120)
    assert in_corso.cavo.completo, in_corso.come_va()
    _uguali(dove, iphone_sul_portatile)
    lassu = json.loads((_lassu(iphone_sul_portatile) / formato.CARTA).read_text("utf-8"))
    assert lassu["stato"] == formato.COMPLETO
    filo.join(30)


def test_se_il_portatile_sparisce_e_torna_la_copia_riprende_da_sola(
        porta_finta, archivio_pieno, telefono, iphone_sul_portatile, tmp_path, monkeypatch):
    import time

    monkeypatch.setattr(cavo_lontano, "ATTESA_DI_UN_COMANDO", 1.0)
    monkeypatch.setattr(pagina, "UNA_PROVA", 0.5)
    monkeypatch.setattr(pagina, "PAUSA_TRA_LE_PROVE", 0.05)
    dove = tmp_path / "Visore-iPhone"
    in_corso = _parti(archivio_pieno, telefono, dove)
    _, filo, _ = _mani(iphone_sul_portatile, quanti=20)
    filo.join(120)
    fino = time.monotonic() + 60
    while not str(in_corso.fase).startswith("aspetto") and time.monotonic() < fino:
        time.sleep(0.02)
    assert str(in_corso.fase).startswith("aspetto"), in_corso.come_va()
    assert in_corso.lavoro.sta_lavorando
    assert cavo_lontano.banco.aperto
    time.sleep(1.5)
    assert in_corso.lavoro.sta_lavorando

    monkeypatch.setattr(cavo_lontano, "ATTESA_DI_UN_COMANDO", 120.0)
    mani, filo, finti = _mani(iphone_sul_portatile)
    assert in_corso.lavoro.aspetta_che_finisca(120)
    detto = in_corso.come_va()
    assert not detto["guasto"], detto["guasto"]
    assert detto["cavo_completo"]
    assert any(riga.startswith("Il portatile ha smesso") for riga in detto["righe"])
    assert any(riga.startswith("Ricollegato") for riga in detto["righe"])
    _uguali(dove, iphone_sul_portatile)
    lassu = json.loads((_lassu(iphone_sul_portatile) / formato.CARTA).read_text("utf-8"))
    assert lassu["stato"] == formato.COMPLETO
    filo.join(30)
    assert not filo.is_alive()
    assert not cavo_lontano.banco.aperto


def test_le_strade_del_cavo_sono_solo_del_portatile(porta_finta, archivio_pieno, telefono):
    from fastapi.testclient import TestClient

    from officina.web.server import app

    fisso = TestClient(app, client=("127.0.0.1", 51000))
    assert fisso.get("/api/telefono/cavo/prendi").status_code == 403
    assert fisso.get("/api/telefono/cavo/file/qualcosa").status_code == 403
    assert cavo_lontano.PRENDI == "/api/telefono/cavo/prendi"
    assert cavo_lontano.FILE == "/api/telefono/cavo/file/"

    portatile = TestClient(porta_mod.app_della_porta)
    assert portatile.get(cavo_lontano.PRENDI).status_code == 401
    assert portatile.get(cavo_lontano.PRENDI, headers=SESSIONE).json() == {"op": "fine"}
    assert portatile.get(cavo_lontano.FILE + "inventata",
                         headers=SESSIONE).status_code == 404
    senza_cavo = portatile.post(f"/telefono/{telefono}/parti", headers=SESSIONE,
                                data={"password": PAROLA, "ancora": PAROLA},
                                follow_redirects=False)
    assert senza_cavo.status_code == 303
    assert "x-schermo-cavo" not in {k.lower() for k in senza_cavo.headers}
    assert pagina.in_corso.lavoro.aspetta_che_finisca(120)
    assert not pagina.in_corso.lontano


def test_gli_avanzi_di_una_copia_interrotta_si_tolgono(tmp_path):
    vecchia = tmp_path / (cavo_lontano.AVANZI + "abc")
    vecchia.mkdir()
    (vecchia / "su").write_bytes(b"cifrato")
    altra = tmp_path / "altro"
    altra.mkdir()

    assert cavo_lontano.pulisci_gli_avanzi(tmp_path) == 1
    assert not vecchia.exists()
    assert altra.exists()


@pytest.fixture
def porta_vera(casa):
    from prove.test_schermo import _Password

    nuova = porta_mod.Porta()
    vecchia, porta_mod.porta = porta_mod.porta, nuova
    nuova.apri(_Password("cavallo-batteria"))
    yield nuova
    nuova.chiudi()
    porta_mod.porta = vecchia


def test_dal_portatile_vero_il_tasto_fa_partire_le_mani(porta_vera, archivio_pieno,
                                                        telefono, iphone_sul_portatile,
                                                        tmp_path, monkeypatch):
    from prove.test_schermo import _abbina

    monkeypatch.setattr(cavo, "collega", lambda: cavo.FintoTelefono(iphone_sul_portatile))
    fisso = _abbina(porta_vera)
    ponte = collega.Ponte(fisso, collega.entra(fisso, "cavallo-batteria"))
    ponte.parti()
    try:
        vicino = http.client.HTTPConnection("127.0.0.1", ponte.porta_locale, timeout=60)
        vicino.request("GET", urllib.parse.urlsplit(ponte.indirizzo).path)
        entrata = vicino.getresponse()
        entrata.read()
        biscotto = entrata.getheader("set-cookie").split(";")[0]
        corpo = urllib.parse.urlencode({"password": PAROLA, "ancora": PAROLA, "cavo": "1"})
        vicino.request("POST", f"/telefono/{telefono}/parti", body=corpo, headers={
            "cookie": biscotto, "content-type": "application/x-www-form-urlencoded"})
        risposta = vicino.getresponse()
        risposta.read()
        assert risposta.status == 303
        assert risposta.getheader(CAVO) == "1"

        assert pagina.in_corso.lavoro.aspetta_che_finisca(120)
        detto = pagina.in_corso.come_va()
        assert not detto["guasto"], detto["guasto"]
        assert detto["cavo_completo"] and detto["cavo_lontano"]
        _uguali(tmp_path / "Visore-iPhone", iphone_sul_portatile)
        ponte._mani.join(30)
        assert not ponte._mani.is_alive()
    finally:
        ponte.ferma()
