from __future__ import annotations

import io

import pytest
from PIL import Image

from officina.importazione import miniature
from officina.modello import aiuti
from officina.modello import file_media
from officina.programma import archivio_sicuro
from officina.sicuro import cache_cifrata
from prove import test_programma_finestre as finestre
from prove import test_sicuro_servizio as servizio_di_prova
from prove.test_costruzione_stanza import _un_posto_con
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
    copia = archivio.percorso_miniatura("aa/" + "b" * 32 + ".mp4")
    copia.parent.mkdir(parents=True, exist_ok=True)
    copia.write_bytes(b"video")
    monkeypatch.setattr(cache_cifrata, "RIPOSO", 0)
    cache_cifrata.in_sottofondo(archivio).join(30)
    for nome, dati in vecchie.items():
        percorso = archivio.percorso_miniatura(nome)
        assert not percorso.exists()
        assert cache_cifrata.cifrato(percorso).exists()
        assert archivio.leggi_miniatura(nome) == dati
    assert not copia.exists()
    assert b"video" not in cache_cifrata.cifrato(copia).read_bytes()
    aperta = cache_cifrata.copia_da_guardare(archivio.dove, copia)
    assert aperta.read_bytes() == b"video"
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


def _aiuto(pronta, tmp_path, seme=3):
    foto = tmp_path / f"aiuto{seme}.jpg"
    foto.write_bytes(_jpeg(640, 480, seme=seme))
    posto_id = _un_posto_con(pronta.archivio, [], f"Camera {seme}")
    esito = aiuti.aggiungi(pronta.archivio, foto, foto.name, posto_id=posto_id)
    with pronta.archivio.lettura() as connessione:
        elenco = aiuti.di_posto(connessione, posto_id)
    return foto.read_bytes(), esito, elenco


def test_le_foto_di_aiuto_si_salvano_solo_cifrate(cifrate, tmp_path):
    pronta = cifrate
    dati, esito, elenco = _aiuto(pronta, tmp_path)
    assert esito["messe"] == 1 and len(elenco) == 1
    voce = elenco[0]
    in_chiaro = aiuti.percorso(pronta.archivio, voce)
    sicuro = cache_cifrata.cifrato(in_chiaro)
    assert not in_chiaro.exists() and sicuro.exists()
    assert dati not in sicuro.read_bytes()
    letta = aiuti.da_leggere(pronta.archivio, voce)
    with letta.apri() as dentro:
        assert dentro.read() == dati
    risposta = pronta.cliente.get(f"/aiuti/{voce['aiuto_id']}/miniatura")
    assert risposta.status_code == 200 and risposta.headers["cache-control"] == "no-store"
    for percorso in pronta.archivio.dove.aiuti.rglob("*"):
        assert dati not in percorso.read_bytes()
    aiuti.togli(pronta.archivio, voce["aiuto_id"])
    assert not sicuro.exists() and not in_chiaro.exists()


def test_ad_archivio_chiuso_le_foto_di_aiuto_non_entrano_e_non_si_vedono(cifrate,
                                                                         tmp_path):
    pronta = cifrate
    _dati, _esito, elenco = _aiuto(pronta, tmp_path, seme=4)
    prima = sorted(pronta.archivio.dove.aiuti.rglob("*"))
    assert pronta.casa.archivio.chiudi(ATTESA)
    _dati, esito, _ = _aiuto(pronta, tmp_path, seme=5)
    assert esito == {"messe": 0, "scartate": 1, "perche": aiuti.APRI_L_ARCHIVIO}
    assert sorted(pronta.archivio.dove.aiuti.rglob("*")) == prima
    assert aiuti.da_leggere(pronta.archivio, elenco[0]) is None
    chiusa = pronta.cliente.get(f"/aiuti/{elenco[0]['aiuto_id']}/miniatura")
    assert chiusa.status_code == 404
    pronta.casa.archivio.apri(PAROLA)
    assert aiuti.da_leggere(pronta.archivio, elenco[0]) is not None


def test_una_foto_di_aiuto_cifrata_rovinata_non_si_cancella(cifrate, tmp_path):
    pronta = cifrate
    _dati, _esito, elenco = _aiuto(pronta, tmp_path, seme=6)
    sicuro = cache_cifrata.cifrato(aiuti.percorso(pronta.archivio, elenco[0]))
    blob = bytearray(sicuro.read_bytes())
    blob[-3] ^= 4
    sicuro.write_bytes(bytes(blob))
    assert aiuti.da_leggere(pronta.archivio, elenco[0]) is None
    assert sicuro.read_bytes() == bytes(blob)


def test_le_foto_di_aiuto_di_prima_si_cifrano_in_sottofondo(cifrate, tmp_path,
                                                             monkeypatch):
    pronta = cifrate
    monkeypatch.setattr(cache_cifrata, "_vero", lambda dove: False)
    dati, esito, elenco = _aiuto(pronta, tmp_path, seme=7)
    in_chiaro = aiuti.percorso(pronta.archivio, elenco[0])
    assert in_chiaro.read_bytes() == dati
    monkeypatch.setattr(cache_cifrata, "_vero", lambda dove: True)
    vero_scrivi = cache_cifrata.decifra
    monkeypatch.setattr(cache_cifrata, "decifra", lambda *a, **k: b"diversa")
    cache_cifrata.cifra_le_vecchie(pronta.archivio)
    assert in_chiaro.read_bytes() == dati
    assert not cache_cifrata.cifrato(in_chiaro).exists()
    monkeypatch.setattr(cache_cifrata, "decifra", vero_scrivi)
    cache_cifrata.cifra_le_vecchie(pronta.archivio)
    assert not in_chiaro.exists()
    with aiuti.da_leggere(pronta.archivio, elenco[0]).apri() as dentro:
        assert dentro.read() == dati


def test_stanze_e_superfici_si_salvano_solo_cifrate(cifrate):
    import numpy as np

    from officina.corpi import superfici
    from officina.errori import DaRifare
    from officina.stanza import costruzione

    pronta = cifrate
    dove = pronta.archivio.dove
    punti = np.arange(30, dtype=np.float32).reshape(10, 3) * 1.25
    colori = np.full((10, 3), 77, dtype=np.uint8)
    stanza = dove.stanze / "5.npz"
    costruzione._salva_la_nuvola(stanza, punti, colori, None, dove)
    assert not stanza.exists() and cache_cifrata.cifrato(stanza).exists()
    letti, tinte, gruppi = costruzione.leggi_tutta_la_nuvola(stanza, dove)
    assert np.array_equal(letti, punti) and np.array_equal(tinte, colori)
    superficie = dove.superfici / "5.npz"
    superfici.salva(superficie, punti, np.zeros(3), np.ones(10, dtype=bool),
                    np.zeros((10, 2)), dove)
    assert not superficie.exists() and cache_cifrata.cifrato(superficie).exists()
    assert np.allclose(superfici.leggi(superficie, dove)["locali"], punti, atol=0.05)
    cache_cifrata.cifrato(superficie).write_bytes(cache_cifrata.cifrato(stanza).read_bytes())
    with pytest.raises(OSError):
        superfici.leggi(superficie, dove)
    assert cache_cifrata.cifrato(superficie).exists()
    assert pronta.casa.archivio.chiudi(ATTESA)
    with pytest.raises(OSError):
        costruzione.leggi_tutta_la_nuvola(stanza, dove)
    with pytest.raises(DaRifare):
        costruzione._salva_la_nuvola(dove.stanze / "6.npz", punti, colori, None, dove)
    assert not list(dove.stanze.glob("6.npz*"))
    pronta.casa.archivio.apri(PAROLA)


def test_stanze_e_superfici_di_prima_si_cifrano_in_sottofondo(cifrate):
    import numpy as np

    from officina.stanza import costruzione

    pronta = cifrate
    dove = pronta.archivio.dove
    punti = np.ones((4, 3), dtype=np.float32)
    vecchia = dove.stanze / "8.npz"
    costruzione._salva_la_nuvola(vecchia, punti, np.zeros((4, 3)), None, None)
    facce = dove.superfici / "facce.npy"
    facce.parent.mkdir(parents=True, exist_ok=True)
    np.save(facce, np.zeros((2, 3), dtype=np.uint16))
    cache_cifrata.cifra_le_vecchie(pronta.archivio)
    assert not vecchia.exists() and cache_cifrata.cifrato(vecchia).exists()
    assert facce.exists()
    assert np.array_equal(costruzione.leggi_tutta_la_nuvola(vecchia, dove)[0], punti)


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


def test_se_la_cifratura_al_volo_non_riesce_si_mostra_lo_stesso(tmp_path, monkeypatch):
    chiave = bytes(range(32))
    percorso = tmp_path / "aa" / "vecchia.jpg"
    percorso.parent.mkdir()
    percorso.write_bytes(b"in chiaro di prima")

    def bloccato(*argomenti, **opzioni):
        raise PermissionError("aperto da un altro programma")

    monkeypatch.setattr(cache_cifrata.os, "replace", bloccato)
    assert cache_cifrata.leggi(percorso, "aa/vecchia.jpg", chiave) == b"in chiaro di prima"
    assert percorso.exists()
    assert sorted(p.name for p in percorso.parent.iterdir()) == ["vecchia.jpg"]


def test_chiuso_l_archivio_le_chiavi_delle_miniature_si_dimenticano(cifrate):
    pronta = cifrate
    pronta.cliente.get(f"/miniatura/{pronta.file_id}")
    assert cache_cifrata._chiavi
    assert pronta.casa.archivio.chiudi(ATTESA)
    assert pronta.archivio.cache_delle_miniature() == (cache_cifrata.CHIUSA, None)
    assert not cache_cifrata._chiavi
    pronta.casa.archivio.apri(PAROLA)
    assert pronta.archivio.cache_delle_miniature()[0] == cache_cifrata.APERTA
    assert cache_cifrata._chiavi
    cache_cifrata.dimentica_le_chiavi()
    assert not cache_cifrata._chiavi
