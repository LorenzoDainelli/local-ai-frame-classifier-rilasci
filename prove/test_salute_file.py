from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from officina.archivio.database import tutti, uno
from officina.importazione import impronta
from officina.importazione.motore import Motore
from officina.modello import salute_file


@pytest.fixture
def foto(tmp_path) -> Path:
    from officina.finto import generatore

    dove = tmp_path / "foto"
    generatore.genera(dove, quanti=6, seme=7, con_rotti=False, leggero=True)
    return dove


def _una_foto(cartella: Path) -> Path:
    return sorted(p for p in cartella.rglob("*") if p.is_file()
                  and p.suffix.upper() in {".JPG", ".JPEG", ".HEIC"})[0]


def _rovina(percorso: Path, cambia_la_data: bool = False) -> None:
    prima = percorso.stat()
    dati = bytearray(percorso.read_bytes())
    mezzo = len(dati) // 2
    dati[mezzo] ^= 0xFF
    dati[mezzo + 1] ^= 0x55
    percorso.write_bytes(bytes(dati))
    if cambia_la_data:
        os.utime(percorso, ns=(prima.st_atime_ns, prima.st_mtime_ns + 5_000_000_000))
    else:
        os.utime(percorso, ns=(prima.st_atime_ns, prima.st_mtime_ns))


def _importa(archivio, *cartelle: Path) -> None:
    motore = Motore(archivio)
    motore.prepara(list(cartelle))
    motore.esegui()


def _tutto_controllato(archivio) -> None:
    for _ in range(10):
        if not salute_file.un_giro(archivio, secondi=30).guardati:
            return


def _esito(archivio, percorso: Path) -> str | None:
    riga = uno(archivio.connessione,
               "SELECT s.esito FROM salute_file s JOIN percorsi p ON p.id = s.percorso_id "
               "WHERE p.percorso = ?", str(percorso))
    return riga["esito"] if riga else None


def test_il_primo_giro_trova_tutto_sano(archivio, foto):
    _importa(archivio, foto)
    _tutto_controllato(archivio)
    conti = salute_file.conti(archivio.connessione)
    assert conti["presenti"] > 0
    assert conti["sano"] == conti["presenti"]
    assert salute_file.quanti_rovinati(archivio.connessione) == 0


def test_un_byte_cambiato_con_la_stessa_data_e_un_file_rovinato(archivio, foto):
    _importa(archivio, foto)
    _tutto_controllato(archivio)
    bersaglio = _una_foto(foto)
    _rovina(bersaglio)
    with archivio.scrittura() as connessione:
        connessione.execute("UPDATE salute_file SET controllato_il = '2000-01-01T00:00:00Z'")
    _tutto_controllato(archivio)
    assert _esito(archivio, bersaglio) == salute_file.ROVINATO
    assert salute_file.quanti_rovinati(archivio.connessione) == 1


def test_se_la_data_cambia_lo_ha_modificato_un_altro_programma(archivio, foto):
    _importa(archivio, foto)
    _tutto_controllato(archivio)
    bersaglio = _una_foto(foto)
    _rovina(bersaglio, cambia_la_data=True)
    with archivio.scrittura() as connessione:
        connessione.execute("UPDATE salute_file SET controllato_il = '2000-01-01T00:00:00Z'")
    _tutto_controllato(archivio)
    assert _esito(archivio, bersaglio) == salute_file.CAMBIATO
    assert salute_file.quanti_rovinati(archivio.connessione) == 0


def test_si_ripara_da_un_doppione_e_la_copia_rovinata_resta_da_parte(archivio, foto, tmp_path):
    doppia = tmp_path / "doppia"
    shutil.copytree(foto, doppia)
    _importa(archivio, foto, doppia)
    _tutto_controllato(archivio)
    bersaglio = _una_foto(foto)
    giusta = impronta.del_file(bersaglio)
    _rovina(bersaglio)
    salute_file.ricontrolla_quelli_da_riparare(archivio)
    with archivio.scrittura() as connessione:
        connessione.execute("UPDATE salute_file SET controllato_il = '2000-01-01T00:00:00Z'")
    _tutto_controllato(archivio)
    elenco = salute_file.da_riparare(archivio.connessione)
    assert [riga["percorso"] for riga in elenco] == [str(bersaglio)]
    assert elenco[0]["ha_un_doppione"]

    detto = salute_file.ripara(archivio, elenco[0]["percorso_id"])

    assert "com'era" in detto
    assert impronta.del_file(bersaglio) == giusta
    assert _esito(archivio, bersaglio) == salute_file.SANO
    da_parte = list(archivio.dove.rovinati.iterdir())
    assert len(da_parte) == 1 and impronta.del_file(da_parte[0]) != giusta
    assert not list(bersaglio.parent.glob("*.riparazione"))


def test_senza_doppione_non_si_tocca_niente(archivio, foto):
    _importa(archivio, foto)
    _tutto_controllato(archivio)
    bersaglio = _una_foto(foto)
    _rovina(bersaglio)
    rovinata = bersaglio.read_bytes()
    with archivio.scrittura() as connessione:
        connessione.execute("UPDATE salute_file SET controllato_il = '2000-01-01T00:00:00Z'")
    _tutto_controllato(archivio)
    elenco = salute_file.da_riparare(archivio.connessione)
    assert not elenco[0]["ha_un_doppione"]
    with pytest.raises(salute_file.RiparazioneFerma, match="copia di sicurezza"):
        salute_file.ripara(archivio, elenco[0]["percorso_id"])
    assert bersaglio.read_bytes() == rovinata
    assert salute_file.ripara_tutti(archivio) == (0, [])


def test_un_file_rovinato_non_diventa_una_foto_nuova(archivio, foto):
    _importa(archivio, foto)
    _tutto_controllato(archivio)
    prima = uno(archivio.connessione, "SELECT count(*) AS q FROM file_media")["q"]
    bersaglio = _una_foto(foto)
    _rovina(bersaglio)
    Motore(archivio)._importa(bersaglio)
    assert uno(archivio.connessione, "SELECT count(*) AS q FROM file_media")["q"] == prima
    assert _esito(archivio, bersaglio) == salute_file.ROVINATO


def test_va_bene_cosi_toglie_il_cambiato_dall_elenco(archivio, foto):
    _importa(archivio, foto)
    _tutto_controllato(archivio)
    bersaglio = _una_foto(foto)
    _rovina(bersaglio, cambia_la_data=True)
    salute_file.ricontrolla_quelli_da_riparare(archivio)
    with archivio.scrittura() as connessione:
        connessione.execute("UPDATE salute_file SET controllato_il = '2000-01-01T00:00:00Z'")
    _tutto_controllato(archivio)
    elenco = salute_file.da_riparare(archivio.connessione)
    salute_file.accetta(archivio, elenco[0]["percorso_id"])
    assert salute_file.da_riparare(archivio.connessione) == []
    with archivio.scrittura() as connessione:
        connessione.execute("UPDATE salute_file SET controllato_il = '2000-01-01T00:00:00Z'")
    _tutto_controllato(archivio)
    assert salute_file.da_riparare(archivio.connessione) == []


def test_un_file_sparito_non_e_rovinato(archivio, foto):
    _importa(archivio, foto)
    bersaglio = _una_foto(foto)
    bersaglio.unlink()
    _tutto_controllato(archivio)
    assert _esito(archivio, bersaglio) == salute_file.ASSENTE
    assert salute_file.quanti_rovinati(archivio.connessione) == 0


def test_il_freno_ferma_il_giro_senza_scrivere(archivio, foto):
    _importa(archivio, foto)
    giro = salute_file.un_giro(archivio, freno=lambda: True)
    assert giro.guardati == 0
    assert tutti(archivio.connessione, "SELECT * FROM salute_file") == []


def test_i_controlli_non_bloccano_la_copia_in_sottofondo(archivio, foto, monkeypatch):
    from officina.archivio import copie

    _importa(archivio, foto)
    fatte = []
    monkeypatch.setattr(copie, "fai_copia",
                        lambda *a, **k: fatte.append(1) or type("C", (), {"percorso": Path("x")})())
    monkeypatch.setattr(copie, "elenco", lambda dove: ["una"])
    archivio._cambiato_all_apertura = False
    archivio._modifiche_all_apertura = archivio.connessione.total_changes
    archivio._solo_ricordi = 0
    archivio.copia_se_fermo()
    salute_file.un_giro(archivio, secondi=30)
    assert archivio.connessione.total_changes > archivio._modifiche_all_apertura
    assert not archivio._serve_la_copia()
    assert archivio.copia_se_fermo() is False
    assert fatte == []


def test_la_pagina_mostra_i_rovinati_e_ripara(archivio, foto, tmp_path):
    from fastapi.testclient import TestClient

    from officina.web.server import app

    doppia = tmp_path / "doppia"
    shutil.copytree(foto, doppia)
    _importa(archivio, foto, doppia)
    _tutto_controllato(archivio)
    bersaglio = _una_foto(foto)
    giusta = impronta.del_file(bersaglio)
    _rovina(bersaglio)
    cliente = TestClient(app, client=("127.0.0.1", 51000))
    assert "/elenchi/salute/ripara/" not in cliente.get("/sistemare").text
    with archivio.scrittura() as connessione:
        connessione.execute("UPDATE salute_file SET controllato_il = '2000-01-01T00:00:00Z'")

    cliente.post("/elenchi/salute/controlla", follow_redirects=False)
    pagina = cliente.get("/sistemare")
    assert pagina.status_code == 200
    assert 'id="rovinati"' in pagina.text
    assert "/elenchi/salute/ripara/" in pagina.text
    assert "Ho ricontrollato" in pagina.text
    assert "si sono rovinati da soli" in cliente.get("/stato").text or \
        "si è rovinato da solo" in cliente.get("/stato").text

    percorso_id = salute_file.da_riparare(archivio.connessione)[0]["percorso_id"]
    risposta = cliente.post(f"/elenchi/salute/ripara/{percorso_id}", follow_redirects=False)
    assert risposta.status_code == 303
    assert impronta.del_file(bersaglio) == giusta
    assert "di nuovo com" in cliente.get("/sistemare").text


def test_riparare_dalla_rete_non_si_puo(archivio, foto, tmp_path):
    from fastapi.testclient import TestClient

    from officina.web.server import app

    _importa(archivio, foto)
    cliente = TestClient(app, client=("192.168.1.50", 51000))
    risposta = cliente.post("/elenchi/salute/ripara-tutti", follow_redirects=False)
    assert risposta.status_code in (401, 403, 404)


def test_ricontrollare_non_rilegge_quelli_che_hai_detto_va_bene(archivio, foto, monkeypatch):
    _importa(archivio, foto)
    _tutto_controllato(archivio)
    bersaglio = _una_foto(foto)
    _rovina(bersaglio, cambia_la_data=True)
    salute_file.ricontrolla_quelli_da_riparare(archivio)
    with archivio.scrittura() as connessione:
        connessione.execute("UPDATE salute_file SET controllato_il = '2000-01-01T00:00:00Z'")
    _tutto_controllato(archivio)
    salute_file.accetta(archivio, salute_file.da_riparare(archivio.connessione)[0]["percorso_id"])
    letti = []
    vero = impronta.del_file_fermabile
    with monkeypatch.context() as m:
        m.setattr(impronta, "del_file_fermabile",
                  lambda percorso, freno: letti.append(Path(percorso)) or vero(percorso, freno))
        giro = salute_file.ricontrolla_quelli_da_riparare(archivio)
    assert giro.guardati == 0
    assert bersaglio not in letti


def test_ricontrollare_si_ferma_quando_ha_letto_abbastanza(archivio, foto):
    _importa(archivio, foto)
    _tutto_controllato(archivio)
    tutte = sorted(p for p in foto.rglob("*") if p.is_file()
                   and p.suffix.upper() in {".JPG", ".JPEG", ".HEIC"})[:2]
    for percorso in tutte:
        _rovina(percorso)
    with archivio.scrittura() as connessione:
        connessione.execute("UPDATE salute_file SET controllato_il = '2000-01-01T00:00:00Z'")
    _tutto_controllato(archivio)
    assert salute_file.quanti_rovinati(archivio.connessione) == 2
    primo = salute_file.ricontrolla_quelli_da_riparare(archivio, byte_massimi=1)
    secondo = salute_file.ricontrolla_quelli_da_riparare(archivio, byte_massimi=1)
    assert (primo.guardati, secondo.guardati) == (1, 1)
    assert primo.rovinati == secondo.rovinati == 1
