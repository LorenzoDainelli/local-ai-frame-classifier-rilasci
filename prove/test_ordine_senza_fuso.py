from __future__ import annotations

import sqlite3

from officina.archivio import migrazioni
from officina.archivio.database import adesso
from officina.modello import scatti
from officina.modello.scatti import Filtro


def _metti(connessione, data_locale, istante_utc):
    connessione.execute(
        "INSERT INTO scatti (genere, data_locale, istante_utc, giorno, creato_il) "
        "VALUES ('foto', ?, ?, ?, ?)",
        (data_locale, istante_utc, data_locale[:10] if data_locale else None, adesso()))
    return connessione.execute("SELECT last_insert_rowid()").fetchone()[0]


def test_con_la_data_ma_senza_fuso_va_al_suo_posto(archivio):
    connessione = archivio.connessione
    vecchio = _metti(connessione, "2019-03-01T10:00:00", "2019-03-01T09:00:00Z")
    senza_fuso = _metti(connessione, "2022-07-15T18:30:00", None)
    medio = _metti(connessione, "2021-01-10T08:00:00", "2021-01-10T07:00:00Z")
    nuovo = _metti(connessione, "2024-05-02T12:00:00", "2024-05-02T10:00:00Z")
    senza_data = _metti(connessione, None, None)
    connessione.commit()
    ordine = [v["id"] for v in scatti.pagina(connessione, Filtro(), 0, 50)]
    assert ordine == [nuovo, senza_fuso, medio, vecchio, senza_data]
    su = [v["id"] for v in scatti.pagina(connessione, Filtro(ordine="data_su"), 0, 50)]
    assert su == [vecchio, medio, senza_fuso, nuovo, senza_data]
    vicini = scatti.vicini(connessione, Filtro(), senza_fuso)
    assert (vicini["prima"], vicini["dopo"]) == (nuovo, medio)
    assert vicini["posizione"] == 2


def test_cambiare_la_data_cambia_il_posto(archivio):
    connessione = archivio.connessione
    numero = _metti(connessione, "2010-01-01T00:00:00", None)
    connessione.execute("UPDATE scatti SET data_locale = '2030-01-01T00:00:00' "
                        "WHERE id = ?", (numero,))
    connessione.execute("UPDATE scatti SET istante_utc = '2031-06-01T00:00:00Z' "
                        "WHERE id = ?", (numero,))
    riga = connessione.execute("SELECT per_ordinare FROM scatti WHERE id = ?",
                               (numero,)).fetchone()
    assert riga[0] == "2031-06-01T00:00:00Z"


def test_la_migrazione_riempie_gli_scatti_che_c_erano_gia():
    connessione = sqlite3.connect(":memory:")
    connessione.isolation_level = None
    vere = migrazioni.MIGRAZIONI
    try:
        migrazioni.MIGRAZIONI = [m for m in vere if m.versione < 81]
        migrazioni.aggiorna(connessione)
    finally:
        migrazioni.MIGRAZIONI = vere
    connessione.execute(
        "INSERT INTO scatti (genere, data_locale, istante_utc, creato_il) VALUES "
        "('foto', '2022-07-15T18:30:00', NULL, 'x'), "
        "('foto', '2021-01-10T08:00:00', '2021-01-10T07:00:00Z', 'x'), "
        "('foto', NULL, NULL, 'x')")
    migrazioni.aggiorna(connessione)
    valori = [r[0] for r in connessione.execute(
        "SELECT per_ordinare FROM scatti ORDER BY id")]
    atteso = connessione.execute(
        "SELECT strftime('%Y-%m-%dT%H:%M:%SZ', '2022-07-15T18:30:00', 'utc')").fetchone()[0]
    assert valori == [atteso, "2021-01-10T07:00:00Z", None]
    indici = " ".join(r[0] for r in connessione.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'index' AND tbl_name = 'scatti' "
        "AND name != 'scatti_per_istante' AND sql IS NOT NULL"))
    assert "istante_utc" not in indici and "per_ordinare" in indici
