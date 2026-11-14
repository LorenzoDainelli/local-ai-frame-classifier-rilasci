from __future__ import annotations

import sqlite3

import pytest

from officina import VERSIONE_SCHEMA
from officina.archivio import accesso, apertura, copie, migrazioni


@pytest.fixture
def chiuso_alla_80(tmp_path, monkeypatch):
    monkeypatch.setenv("OFFICINA_ARCHIVIO", str(tmp_path / "archivio"))
    vere = migrazioni.MIGRAZIONI
    monkeypatch.setattr(migrazioni, "MIGRAZIONI", [m for m in vere if m.versione <= 80])
    monkeypatch.setattr(migrazioni, "VERSIONE_SCHEMA", 80)
    accesso.chiudi(con_copia=False)
    aperto = accesso.apri("finto")
    aperto.di_prova = False
    with aperto.scrittura() as connessione:
        connessione.execute(
            "INSERT INTO scatti (genere, data_locale, istante_utc, creato_il) "
            "VALUES ('foto', '2022-07-15T18:30:00', NULL, 'x')")
    dove = aperto.dove
    accesso.chiudi(con_copia=True)
    monkeypatch.setattr(migrazioni, "MIGRAZIONI", vere)
    monkeypatch.setattr(migrazioni, "VERSIONE_SCHEMA", vere[-1].versione)
    yield dove
    accesso.chiudi(con_copia=False)


def test_la_copia_di_chiusura_uguale_vale_prima_dell_aggiornamento(chiuso_alla_80):
    prima = copie.elenco(chiuso_alla_80)
    assert [c.motivo for c in prima] == ["chiusura"]
    fatte = []
    vera = copie.fai_copia
    copie_prima = copie.fai_copia
    try:
        copie.fai_copia = lambda *a, **k: fatte.append(a) or vera(*a, **k)
        connessione = sqlite3.connect(chiuso_alla_80.database, isolation_level=None)
        copia, riusata = copie.copia_prima_dell_aggiornamento(connessione, chiuso_alla_80)
        connessione.close()
    finally:
        copie.fai_copia = copie_prima
    assert riusata and fatte == []
    dopo = copie.elenco(chiuso_alla_80)
    assert [c.motivo for c in dopo] == ["prima_aggiornamento"]
    assert dopo[0].istante == prima[0].istante
    copie.verifica(copia.percorso)
    vecchia = sqlite3.connect(copia.percorso)
    assert vecchia.execute("PRAGMA user_version").fetchone()[0] == 80
    vecchia.close()


def test_se_l_archivio_e_cambiato_dopo_la_chiusura_si_fa_la_copia_vera(chiuso_alla_80):
    connessione = sqlite3.connect(chiuso_alla_80.database, isolation_level=None)
    connessione.execute("PRAGMA journal_mode = WAL")
    connessione.execute("UPDATE scatti SET data_locale = '2022-07-16T18:30:00'")
    connessione.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    copia, riusata = copie.copia_prima_dell_aggiornamento(connessione, chiuso_alla_80)
    connessione.close()
    assert not riusata
    motivi = sorted(c.motivo for c in copie.elenco(chiuso_alla_80))
    assert motivi == ["chiusura", "prima_aggiornamento"]
    dentro = sqlite3.connect(copia.percorso)
    assert dentro.execute("SELECT data_locale FROM scatti").fetchone()[0].startswith(
        "2022-07-16")
    dentro.close()


def test_con_il_diario_pieno_non_si_riusa(chiuso_alla_80):
    connessione = sqlite3.connect(chiuso_alla_80.database, isolation_level=None)
    connessione.execute("PRAGMA journal_mode = WAL")
    connessione.execute("PRAGMA wal_autocheckpoint = 0")
    connessione.execute("UPDATE scatti SET genere = 'foto'")
    _, riusata = copie.copia_prima_dell_aggiornamento(connessione, chiuso_alla_80)
    connessione.close()
    assert not riusata


def test_una_copia_prenotata_non_si_tocca(chiuso_alla_80):
    ultima = copie.elenco(chiuso_alla_80)[0]
    (chiuso_alla_80.copie / copie.PRENOTAZIONE).write_text(ultima.nome, encoding="utf-8")
    connessione = sqlite3.connect(chiuso_alla_80.database, isolation_level=None)
    _, riusata = copie.copia_prima_dell_aggiornamento(connessione, chiuso_alla_80)
    connessione.close()
    (chiuso_alla_80.copie / copie.PRENOTAZIONE).unlink()
    assert not riusata
    assert ultima.percorso.exists()


def test_un_byte_diverso_fuori_dai_contatori_vuol_dire_diversi(tmp_path):
    uno, due = tmp_path / "uno", tmp_path / "due"
    dati = bytearray(range(256)) * 400
    uno.write_bytes(bytes(dati))
    for posto in (24, 41, 95):
        dati[posto] ^= 0xFF
    due.write_bytes(bytes(dati))
    assert copie._uguali_tranne_i_contatori(uno, due)
    for posto in (0, 23, 28, 39, 44, 91, 96, len(dati) - 1, copie.PEZZO_DA_CONFRONTARE - 1):
        if posto >= len(dati):
            continue
        altro = bytearray(dati)
        altro[posto] ^= 0x01
        due.write_bytes(bytes(altro))
        assert not copie._uguali_tranne_i_contatori(uno, due), posto


def test_l_apertura_dice_a_che_punto_e_e_quanto_ci_ha_messo(chiuso_alla_80, monkeypatch):
    visti = []
    vero = apertura.passo
    monkeypatch.setattr(apertura, "passo", lambda cosa: visti.append(cosa) or vero(cosa))
    accesso.chiudi(con_copia=False)
    aperto = accesso.apri("finto")
    stato = apertura.come_va()
    assert not stato["in_corso"]
    nomi = [f["cosa"] for f in stato["fatti"]]
    assert nomi[0].startswith("Copia di sicurezza: uguale a quella di chiusura")
    quante = VERSIONE_SCHEMA - 80
    assert any(n.startswith(f"Aggiornamento {quante} di {quante}:") for n in nomi)
    assert nomi[-1] == "Statistiche del database"
    assert visti[0] == "Copia di sicurezza prima dell'aggiornamento"
    assert all(f["secondi"] >= 0 for f in stato["fatti"])
    riga = aperto.connessione.execute("SELECT per_ordinare FROM scatti").fetchone()
    assert riga[0] is not None
