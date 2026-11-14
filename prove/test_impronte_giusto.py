from __future__ import annotations

import io
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from officina.impronte import giusto
from officina.importazione import impronta as impronta_file
from officina.modello import segnalazioni


def _cliente():
    from officina.web.server import app

    return TestClient(app, client=("127.0.0.1", 51000))


def _foto(archivio, quante: int) -> list[int]:
    with archivio.lettura() as connessione:
        return [riga["id"] for riga in connessione.execute(
            "SELECT s.id FROM scatti s WHERE s.genere = 'foto' AND s.fuori_archivio = 0 "
            "ORDER BY s.id LIMIT ?", (quante,))]


def _rompi(archivio, scatto_id: int, cartella: Path) -> tuple[Path, Path, int]:
    with archivio.lettura() as connessione:
        riga = connessione.execute(
            "SELECT f.id AS file_id, p.id AS percorso_id, p.percorso FROM file_media f "
            "JOIN percorsi p ON p.file_id = f.id WHERE f.scatto_id = ? "
            "AND f.ruolo = 'principale' AND p.presente = 1 LIMIT 1",
            (scatto_id,)).fetchone()
    cartella.mkdir(parents=True, exist_ok=True)
    sano = cartella / ("sano" + Path(riga["percorso"]).suffix)
    shutil.copy2(riga["percorso"], sano)
    posto = cartella / "rotto" / Path(riga["percorso"]).name
    posto.parent.mkdir()
    dati = sano.read_bytes()
    posto.write_bytes(dati[: len(dati) // 2])
    segno = impronta_file.del_file(posto)
    with archivio.scrittura() as connessione:
        connessione.execute("DELETE FROM file_media WHERE impronta = ? AND id != ?",
                            (impronta_file.del_file(sano), riga["file_id"]))
        connessione.execute("UPDATE file_media SET impronta = ?, dimensione = ? "
                            "WHERE id = ?", (segno, posto.stat().st_size, riga["file_id"]))
        connessione.execute("UPDATE percorsi SET percorso = ?, presente = 1 WHERE id = ?",
                            (str(posto), riga["percorso_id"]))
        segnalazioni.segna(connessione, segnalazioni.NON_SI_APRE, scatto_id,
                           dettaglio="immagine_rovinata")
    return posto, sano, riga["file_id"]


def _giudica(archivio, scatto_id, candidato, nome=None):
    with archivio.lettura() as connessione:
        guasto = giusto.rotto(connessione, scatto_id)
        return giusto.giudica(connessione, guasto, candidato, nome or candidato.name)


def test_la_copia_intera_e_giusta_e_si_sostituisce(archivio_misurabile, tmp_path):
    [scatto] = _foto(archivio_misurabile, 1)
    posto, sano, file_id = _rompi(archivio_misurabile, scatto, tmp_path / "foto")
    rotto_prima = posto.read_bytes()
    esito = _giudica(archivio_misurabile, scatto, sano)
    assert esito["esito"] == giusto.GIUSTO and "hai ragione" in esito["motivo"]
    with open(sano, "rb") as flusso:
        assert giusto.ricevi(archivio_misurabile, scatto, sano.name, flusso)["esito"] == \
            giusto.GIUSTO
    assert posto.read_bytes() == rotto_prima
    fatto = giusto.salva(archivio_misurabile)
    assert fatto["fermi"] == [] and len(fatto["fatti"]) == 1
    assert posto.read_bytes() == sano.read_bytes()
    rifugio = Path(fatto["fatti"][0]["rifugio"])
    assert rifugio.read_bytes() == rotto_prima
    assert rifugio.parent == Path(archivio_misurabile.dove.rovinati)
    with archivio_misurabile.lettura() as connessione:
        riga = connessione.execute("SELECT * FROM file_media WHERE id = ?",
                                   (file_id,)).fetchone()
        aperte = connessione.execute(
            "SELECT count(*) FROM segnalazioni WHERE scatto_id = ? AND risolta = 0 "
            "AND tipo = ?", (scatto, segnalazioni.NON_SI_APRE)).fetchone()[0]
    assert riga["impronta"] == impronta_file.del_file(sano)
    assert riga["dimensione"] == sano.stat().st_size and riga["larghezza"]
    assert aperte == 0
    assert giusto.caricati(archivio_misurabile) == {}
    assert not list(posto.parent.glob("*.giusto"))


@pytest.mark.parametrize("guasta", ["in_mezzo", "piu_corto", "stesso_rotto", "altro_tipo"])
def test_se_qualcosa_non_torna_non_si_tocca_niente(archivio_misurabile, tmp_path, guasta):
    [scatto] = _foto(archivio_misurabile, 1)
    posto, sano, _ = _rompi(archivio_misurabile, scatto, tmp_path / "foto")
    rotto_prima = posto.read_bytes()
    dati = bytearray(sano.read_bytes())
    candidato = tmp_path / ("candidato" + sano.suffix)
    nome = candidato.name
    if guasta == "in_mezzo":
        dati[100] ^= 0xFF
        candidato.write_bytes(bytes(dati))
    elif guasta == "piu_corto":
        candidato.write_bytes(bytes(dati[: len(rotto_prima) - 10]))
    elif guasta == "stesso_rotto":
        candidato.write_bytes(rotto_prima)
    else:
        candidato.write_bytes(bytes(dati))
        nome = "candidato.png"
    with open(candidato, "rb") as flusso:
        esito = giusto.ricevi(archivio_misurabile, scatto, nome, flusso)
    assert esito["esito"] == giusto.NON_TORNA and esito["motivo"]
    if guasta == "in_mezzo":
        assert esito["byte_diverso"] == 100 and "101" in esito["motivo"]
    assert giusto.salva(archivio_misurabile)["fatti"] == []
    assert posto.read_bytes() == rotto_prima
    assert not list(Path(archivio_misurabile.dove.radice).glob("giusti-in-arrivo/*.file"))


def test_una_foto_gia_nella_galleria_si_rifiuta(archivio_misurabile, tmp_path):
    primo, secondo = _foto(archivio_misurabile, 2)
    posto, _, _ = _rompi(archivio_misurabile, primo, tmp_path / "foto")
    with archivio_misurabile.lettura() as connessione:
        altro = connessione.execute(
            "SELECT p.percorso FROM file_media f JOIN percorsi p ON p.file_id = f.id "
            "WHERE f.scatto_id = ? AND p.presente = 1 LIMIT 1", (secondo,)).fetchone()[0]
    esito = _giudica(archivio_misurabile, primo, Path(altro), "x" + posto.suffix)
    assert esito["esito"] == giusto.GIA_IN_GALLERIA
    assert esito["scatto_doppio"] == secondo


def test_se_il_rotto_cambia_prima_di_salvare_non_si_sostituisce(archivio_misurabile,
                                                                 tmp_path):
    [scatto] = _foto(archivio_misurabile, 1)
    posto, sano, _ = _rompi(archivio_misurabile, scatto, tmp_path / "foto")
    with open(sano, "rb") as flusso:
        giusto.ricevi(archivio_misurabile, scatto, sano.name, flusso)
    posto.write_bytes(posto.read_bytes() + b"x")
    fatto = giusto.salva(archivio_misurabile)
    assert fatto["fatti"] == [] and "cambiato" in fatto["fermi"][0]["motivo"]
    assert posto.read_bytes() != sano.read_bytes()


def test_dalla_pagina_si_carica_si_controlla_e_si_salva(archivio_misurabile, tmp_path):
    [scatto] = _foto(archivio_misurabile, 1)
    with archivio_misurabile.scrittura() as connessione:
        connessione.execute("DELETE FROM impronte WHERE scatto_id = ?", (scatto,))
    posto, sano, _ = _rompi(archivio_misurabile, scatto, tmp_path / "foto")
    cliente = _cliente()
    pagina = cliente.get("/intelligenza/perche-mancano")
    assert pagina.status_code == 200
    assert f'data-pm-giusto="{scatto}"' in pagina.text and "data-pm-salva" in pagina.text
    risposta = cliente.post(f"/api/perche-mancano/{scatto}/giusto",
                            files={"file": (sano.name, io.BytesIO(sano.read_bytes()))})
    assert risposta.json()["esito"] == giusto.GIUSTO
    assert "hai ragione" in cliente.get("/intelligenza/perche-mancano").text
    assert cliente.post(f"/api/perche-mancano/{scatto}/togli").json()["tolto"]
    assert giusto.caricati(archivio_misurabile) == {}
    cliente.post(f"/api/perche-mancano/{scatto}/giusto",
                 files={"file": (sano.name, io.BytesIO(sano.read_bytes()))})
    fatto = cliente.post("/api/perche-mancano/salva").json()
    assert len(fatto["fatti"]) == 1 and posto.read_bytes() == sano.read_bytes()
    rotto = cliente.post("/api/perche-mancano/999999/giusto",
                         files={"file": ("a.jpg", io.BytesIO(b"x"))},
                         headers={"accept": "application/json"})
    assert rotto.status_code == 400 and rotto.json()["messaggio"]
