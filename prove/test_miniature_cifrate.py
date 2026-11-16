from __future__ import annotations

import io

import pytest
from PIL import Image

from officina.importazione import miniature
from officina.modello import file_media
from officina.programma import archivio_sicuro
from officina.sicuro import cache_cifrata
from prove import test_programma_finestre as finestre
from prove import test_sicuro_servizio as servizio_di_prova
from prove.test_sicuro_dall_archivio import _jpeg, _prepara
from prove.test_sicuro_servizio import ATTESA, PAROLA

costo_leggero = servizio_di_prova.costo_leggero
casa = finestre.casa


@pytest.fixture
def cifrate(tmp_path, archivio_pieno, monkeypatch):
    pronta = _prepara(tmp_path, archivio_pieno, monkeypatch, "s/foto.jpg", _jpeg(),
                      "immagine", "jpeg", ripara={"luoghi": lambda: []},
                      riparatore={"ogni": 0.05})
    monkeypatch.setattr(cache_cifrata, "_vero", lambda dove: True)
    monkeypatch.setattr(archivio_sicuro, "c_e", lambda posizione: True)
    cache_cifrata.dimentica()
    yield pronta
    cache_cifrata.dimentica()
    pronta.casa.chiudi()


def _tutti_i_file(archivio) -> list:
    return sorted(p for p in archivio.dove.miniature.rglob("*") if p.is_file())


def _riga(pronta):
    with pronta.archivio.lettura() as connessione:
        return file_media.per_id(connessione, pronta.file_id)


def _nessuna_in_chiaro(archivio, dati: bytes) -> None:
    for percorso in _tutti_i_file(archivio):
        contenuto = percorso.read_bytes()
        assert dati not in contenuto, percorso.name


def test_ad_archivio_aperto_la_miniatura_si_scrive_solo_cifrata(cifrate):
    pronta = cifrate
    risposta = pronta.cliente.get(f"/miniatura/{pronta.file_id}")
    assert risposta.status_code == 200
    assert risposta.headers["cache-control"] == "no-store"
    assert "etag" not in risposta.headers
    assert Image.open(io.BytesIO(risposta.content)).size
    nome = _riga(pronta)["miniatura"]
    percorso = pronta.archivio.percorso_miniatura(nome)
    assert not percorso.exists() and cache_cifrata.cifrato(percorso).exists()
    _nessuna_in_chiaro(pronta.archivio, risposta.content)
    assert pronta.archivio.leggi_miniatura(nome) == risposta.content
    diretto = "cd/" + "d" * 32 + ".jpg"
    scritto = pronta.archivio.scrivi_miniatura(diretto, b"in chiaro mai")
    assert scritto == cache_cifrata.cifrato(pronta.archivio.percorso_miniatura(diretto))
    assert not pronta.archivio.percorso_miniatura(diretto).exists()
    assert b"in chiaro mai" not in scritto.read_bytes()
    di_nuovo = pronta.cliente.get(f"/miniatura/{pronta.file_id}",
                                  headers={"if-none-match": '"qualcosa"'})
    assert di_nuovo.status_code == 200 and di_nuovo.content == risposta.content


def test_ad_archivio_chiuso_non_si_vede_e_non_si_rifa_in_chiaro(cifrate):
    pronta = cifrate
    fatta = pronta.cliente.get(f"/miniatura/{pronta.file_id}").content
    prima = _tutti_i_file(pronta.archivio)
    assert pronta.casa.archivio.chiudi(ATTESA)
    assert pronta.archivio.cache_delle_miniature() == (cache_cifrata.CHIUSA, None)
    chiusa = pronta.cliente.get(f"/miniatura/{pronta.file_id}")
    assert chiusa.status_code == 404 and chiusa.headers["cache-control"] == "no-store"
    assert pronta.archivio.leggi_miniatura(_riga(pronta)["miniatura"]) is None
    assert miniature.per_file(pronta.archivio, _riga(pronta)) is None
    assert pronta.archivio.scrivi_miniatura("ab/" + "c" * 32 + ".jpg", fatta) is None
    assert _tutti_i_file(pronta.archivio) == prima
    vecchia = "ee/" + "f" * 32 + ".jpg"
    in_chiaro = pronta.archivio.percorso_miniatura(vecchia)
    in_chiaro.parent.mkdir(parents=True, exist_ok=True)
    in_chiaro.write_bytes(fatta)
    assert pronta.archivio.leggi_miniatura(vecchia) is None
    in_chiaro.unlink()
    pronta.casa.archivio.apri(PAROLA)
    assert pronta.cliente.get(f"/miniatura/{pronta.file_id}").content == fatta


def test_dopo_la_riapertura_la_chiave_e_la_stessa_e_si_rilegge(cifrate):
    pronta = cifrate
    fatta = pronta.cliente.get(f"/miniatura/{pronta.file_id}").content
    stato, prima = pronta.archivio.cache_delle_miniature()
    assert stato == cache_cifrata.APERTA and len(prima) == 32
    assert pronta.casa.archivio.chiudi(ATTESA)
    pronta.casa.archivio.apri(PAROLA)
    assert pronta.archivio.cache_delle_miniature()[1] == prima
    assert pronta.cliente.get(f"/miniatura/{pronta.file_id}").content == fatta


def test_una_miniatura_cifrata_toccata_non_si_mostra_e_si_rifa(cifrate):
    pronta = cifrate
    fatta = pronta.cliente.get(f"/miniatura/{pronta.file_id}").content
    nome = _riga(pronta)["miniatura"]
    sicuro = cache_cifrata.cifrato(pronta.archivio.percorso_miniatura(nome))
    blob = bytearray(sicuro.read_bytes())
    blob[-1] ^= 1
    sicuro.write_bytes(bytes(blob))
    assert pronta.archivio.leggi_miniatura(nome) is None
    assert not sicuro.exists()
    assert pronta.cliente.get(f"/miniatura/{pronta.file_id}").content == fatta
    altro = "ff/" + "e" * 32 + ".jpg"
    pronta.archivio.scrivi_miniatura(altro, b"altra")
    scambiato = cache_cifrata.cifrato(pronta.archivio.percorso_miniatura(altro))
    scambiato.write_bytes(cache_cifrata.cifrato(
        pronta.archivio.percorso_miniatura(nome)).read_bytes())
    assert pronta.archivio.leggi_miniatura(altro) is None


def test_quelle_in_chiaro_di_prima_si_cifrano_in_sottofondo(cifrate, monkeypatch):
    pronta = cifrate
    archivio = pronta.archivio
    vecchie = {}
    for numero in range(70):
        nome = f"{numero % 7:02x}/{numero:032x}.jpg"
        dati = _jpeg(16, 16, seme=numero)
        percorso = archivio.percorso_miniatura(nome)
        percorso.parent.mkdir(parents=True, exist_ok=True)
        percorso.write_bytes(dati)
        vecchie[nome] = dati
    da_lasciare = archivio.percorso_miniatura("aa/" + "b" * 32 + ".mp4")
    da_lasciare.parent.mkdir(parents=True, exist_ok=True)
    da_lasciare.write_bytes(b"video")
    monkeypatch.setattr(cache_cifrata, "RIPOSO", 0)
    cache_cifrata.in_sottofondo(archivio).join(30)
    for nome, dati in vecchie.items():
        percorso = archivio.percorso_miniatura(nome)
        assert not percorso.exists()
        assert cache_cifrata.cifrato(percorso).exists()
        assert archivio.leggi_miniatura(nome) == dati
    assert da_lasciare.read_bytes() == b"video"
    assert not list(archivio.dove.miniature.rglob("*.parziale"))


def test_in_sottofondo_si_ferma_se_l_archivio_si_chiude(cifrate, monkeypatch):
    pronta = cifrate
    archivio = pronta.archivio
    for numero in range(5):
        percorso = archivio.percorso_miniatura(f"0{numero}/{numero:032x}.jpg")
        percorso.parent.mkdir(parents=True, exist_ok=True)
        percorso.write_bytes(_jpeg(16, 16, seme=numero))
    assert pronta.casa.archivio.chiudi(ATTESA)
    assert cache_cifrata.cifra_le_vecchie(archivio) == 0
    assert len(list(archivio.dove.miniature.rglob("*.jpg"))) == 5
    pronta.casa.archivio.apri(PAROLA)


def test_senza_archivio_sicuro_le_miniature_restano_come_prima(archivio_pieno):
    assert archivio_pieno.cache_delle_miniature() == (cache_cifrata.SPENTA, None)
    nome = "12/" + "3" * 32 + ".jpg"
    percorso = archivio_pieno.scrivi_miniatura(nome, b"dati")
    assert percorso.read_bytes() == b"dati"
    assert archivio_pieno.leggi_miniatura(nome) == b"dati"
    archivio_pieno.butta_miniatura(nome)
    assert not percorso.exists()


def test_se_l_archivio_sicuro_non_c_e_piu_le_cifrate_si_rifanno_in_chiaro(cifrate,
                                                                       monkeypatch):
    pronta = cifrate
    fatta = pronta.cliente.get(f"/miniatura/{pronta.file_id}").content
    nome = _riga(pronta)["miniatura"]
    monkeypatch.setattr(cache_cifrata, "_vero", lambda dove: False)
    rifatta = pronta.cliente.get(f"/miniatura/{pronta.file_id}")
    assert rifatta.status_code == 200 and rifatta.content == fatta
    percorso = pronta.archivio.percorso_miniatura(nome)
    assert percorso.exists() and not cache_cifrata.cifrato(percorso).exists()


def test_il_formato_cifrato_non_si_apre_con_un_altra_chiave():
    chiave, altra = bytes(32), bytes([1]) * 32
    blob = cache_cifrata.cifra(chiave, "ab/x.jpg", b"miniatura")
    assert blob.startswith(cache_cifrata.FIRMA) and b"miniatura" not in blob
    assert cache_cifrata.decifra(chiave, "ab/x.jpg", blob) == b"miniatura"
    assert cache_cifrata.decifra(altra, "ab/x.jpg", blob) is None
    assert cache_cifrata.decifra(chiave, "ab/y.jpg", blob) is None
    assert cache_cifrata.decifra(chiave, "ab/x.jpg", blob[:10]) is None
    assert cache_cifrata.cifra(chiave, "ab/x.jpg", b"miniatura") != blob


__all__ = ["casa", "costo_leggero"]
