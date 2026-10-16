from __future__ import annotations

import hashlib
import json

import pytest

from officina.archivio import riserva
from officina.archivio.database import adesso
from officina.errori import ErroreOfficina


def _impronta(dati: bytes) -> str:
    return hashlib.blake2b(dati, digest_size=32).hexdigest()


@pytest.fixture
def scena(archivio, tmp_path):
    originali = tmp_path / "originali"
    originali.mkdir()
    file = {}
    with archivio.scrittura() as c:
        for i in range(3):
            dati = f"finto-{i}".encode() * 50
            percorso = originali / f"foto_{i}.jpg"
            percorso.write_bytes(dati)
            numero = c.execute(
                "INSERT INTO file_media (impronta, dimensione, genere, aggiunto_il) "
                "VALUES (?, ?, 'immagine', ?)", (_impronta(dati), len(dati), adesso())).lastrowid
            c.execute("INSERT INTO percorsi (file_id, percorso, nome, visto_il) VALUES (?, ?, ?, ?)",
                      (numero, str(percorso), percorso.name, adesso()))
            file[i] = percorso
    disco = tmp_path / "disco"
    disco.mkdir()
    return {"originali": originali, "file": file, "disco": disco}


def _fai(archivio, disco, **altro):
    return riserva.parti(archivio, disco, in_sottofondo=False, **altro)


def _casa(archivio, disco):
    return riserva.dove_va(disco, archivio.dove.nome)


def test_copia_tutto_e_poi_solo_quello_che_manca(archivio, scena):
    primo = _fai(archivio, scena["disco"])
    assert primo["fase"] == "fatto" and primo["copiati"] == 3 and not primo["errori"]
    casa = _casa(archivio, scena["disco"])
    for percorso in scena["file"].values():
        copia = casa / "foto" / riserva.relativo(str(percorso))
        assert copia.read_bytes() == percorso.read_bytes()
    assert (casa / "archivio" / f"{archivio.dove.nome}.sqlite").is_file()
    secondo = _fai(archivio, scena["disco"])
    assert secondo["copiati"] == 0 and secondo["uguali"] == 3
    assert riserva.ultima(scena["disco"], archivio.dove.nome)["uguali"] == 3


def test_un_originale_cambiato_non_rovina_la_copia_buona(archivio, scena):
    _fai(archivio, scena["disco"])
    sorgente = scena["file"][0]
    buono = sorgente.read_bytes()
    sorgente.write_bytes(b"rovinato" * 10)
    esito = _fai(archivio, scena["disco"])
    assert esito["diversi"] == 1
    copia = _casa(archivio, scena["disco"]) / "foto" / riserva.relativo(str(sorgente))
    assert copia.read_bytes() == buono
    assert not list(copia.parent.glob("*" + riserva.IN_ARRIVO))


def test_il_ricontrollo_trova_una_copia_rovinata_e_la_rifa(archivio, scena):
    _fai(archivio, scena["disco"])
    casa = _casa(archivio, scena["disco"])
    copia = casa / "foto" / riserva.relativo(str(scena["file"][1]))
    copia.write_bytes(b"x" * copia.stat().st_size)
    esito = _fai(archivio, scena["disco"], anche_il_ricontrollo=True)
    assert esito["rovinati_nella_copia"] == 1
    di_nuovo = _fai(archivio, scena["disco"])
    assert di_nuovo["copiati"] == 1
    assert copia.read_bytes() == scena["file"][1].read_bytes()


def test_con_la_cassaforte_accesa_non_copia_l_archivio_in_chiaro(archivio, scena, monkeypatch):
    from types import SimpleNamespace

    from officina import forziere

    finto = scena["disco"].parent / "finto.forziere"
    finto.write_bytes(b"cifrato")
    monkeypatch.setattr(forziere, "per", lambda dove: SimpleNamespace(acceso=True, aperto=False, file=finto))
    esito = _fai(archivio, scena["disco"])
    assert esito["fase"] == "fatto"
    cartella = _casa(archivio, scena["disco"]) / "archivio"
    assert [p.name for p in cartella.iterdir()] == ["finto.forziere"]


def test_la_cartella_non_puo_stare_negli_originali_ne_nell_archivio(archivio, scena):
    dentro = scena["originali"] / "sotto"
    dentro.mkdir()
    with pytest.raises(ErroreOfficina, match="originali"):
        riserva.controlla_la_cartella(str(dentro), [str(scena["originali"])],
                                      archivio.dove.radice)
    with pytest.raises(ErroreOfficina, match="non si trova"):
        riserva.controlla_la_cartella(str(scena["disco"] / "boh"), [], archivio.dove.radice)
    assert riserva.controlla_la_cartella(str(scena["disco"]), [str(scena["originali"])],
                                         archivio.dove.radice) == scena["disco"]


def test_l_elenco_sul_disco_e_leggibile(archivio, scena):
    _fai(archivio, scena["disco"])
    elenco = json.loads((_casa(archivio, scena["disco"]) / riserva.ELENCO).read_text("utf-8"))
    assert len(elenco) == 3


def test_dalla_pagina_si_sceglie_il_disco_e_si_fa_la_copia(archivio, scena, monkeypatch, tmp_path):
    import time

    from fastapi.testclient import TestClient

    from officina.web.server import app

    monkeypatch.setenv("OFFICINA_CASA_PROGRAMMA", str(tmp_path / "casa"))
    cliente = TestClient(app, client=("127.0.0.1", 51000))
    assert "data-copia-esterna" in cliente.get("/impostazioni").text
    scelto = cliente.post("/copia-esterna/cartella", data={"percorso": str(scena["disco"])})
    assert scelto.status_code == 200 and scelto.json()["collegata"]
    cliente.post("/copia-esterna/parti")
    for _ in range(200):
        stato = cliente.get("/copia-esterna").json()
        if stato["lavoro"]["finito"]:
            break
        time.sleep(0.02)
    assert stato["ultima"]["copiati"] == 3


def test_chiudendo_l_archivio_la_copia_si_ferma_prima(archivio, scena, monkeypatch):
    import threading

    from officina.archivio import accesso

    partita = threading.Event()

    def lenta(archivio, casa, lavoro):
        partita.set()
        while not riserva._ferma.wait(0.01):
            pass
        raise riserva._Fermato()

    monkeypatch.setattr(riserva, "_copia_le_foto", lenta)
    riserva.parti(archivio, scena["disco"])
    assert partita.wait(10)
    accesso.chiudi(con_copia=False)
    assert riserva.a_che_punto()["fase"] == "fermata"
    assert not riserva._filo.is_alive()
