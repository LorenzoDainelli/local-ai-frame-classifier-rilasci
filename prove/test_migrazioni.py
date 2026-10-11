from __future__ import annotations

import sqlite3

from officina import VERSIONE_SCHEMA
from officina.archivio import accesso, database, migrazioni


def _fai_un_database_vecchio(percorso) -> None:
    percorso.parent.mkdir(parents=True, exist_ok=True)
    connessione = database.connetti(percorso)
    database.crea_da_zero(connessione)
    connessione.execute("PRAGMA user_version = 1")
    connessione.execute(
        "INSERT INTO nodi (nome, creato_il) VALUES ('nodo_di_prima', '2020-01-01T00:00:00Z')"
    )
    connessione.close()


def test_un_archivio_vecchio_si_aggiorna_da_solo(tmp_path, monkeypatch):
    monkeypatch.setenv("OFFICINA_ARCHIVIO", str(tmp_path / "archivio"))
    accesso.chiudi(con_copia=False)

    from officina.impostazioni import posizione

    dove = posizione("finto")
    _fai_un_database_vecchio(dove.database)

    aperto = accesso.apri("finto")
    try:
        assert migrazioni.versione_attuale(aperto.connessione) == VERSIONE_SCHEMA
        tabelle = {r[0] for r in aperto.connessione.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'")}
        assert "dispositivi" in tabelle
        nomi = [r["nome"] for r in aperto.connessione.execute("SELECT nome FROM nodi")]
        assert nomi == ["nodo_di_prima"]
        assert any(c.motivo == "prima_aggiornamento" for c in aperto.copie_esistenti())
    finally:
        accesso.chiudi(con_copia=False)


def test_un_archivio_gia_aggiornato_non_viene_toccato(archivio):
    assert migrazioni.da_applicare(archivio.connessione) == []


def test_un_archivio_del_futuro_non_si_apre(tmp_path, monkeypatch):
    import pytest

    from officina.errori import DatabaseIncoerente
    from officina.impostazioni import posizione

    monkeypatch.setenv("OFFICINA_ARCHIVIO", str(tmp_path / "archivio"))
    accesso.chiudi(con_copia=False)
    dove = posizione("finto")
    _fai_un_database_vecchio(dove.database)
    connessione = sqlite3.connect(dove.database)
    connessione.execute(f"PRAGMA user_version = {VERSIONE_SCHEMA + 5}")
    connessione.close()

    with pytest.raises(DatabaseIncoerente):
        accesso.apri("finto")
    accesso.chiudi(con_copia=False)


def _un_impronta(connessione, inquadratura: str) -> None:
    connessione.execute(
        "INSERT INTO scatti (genere, origine_data, giorno, creato_il) "
        "VALUES ('foto', 'exif', '2026-01-01', '2026-01-01T00:00:00Z')")
    scatto = connessione.execute("SELECT max(id) FROM scatti").fetchone()[0]
    connessione.execute(
        "INSERT INTO impronte (scatto_id, descrittore, versione, inquadratura, "
        "metodo, dimensione, valori, calcolata_il) "
        "VALUES (?, 'disegnato', '2', ?, 'intera', 2, X'0000', "
        "'2026-01-01T00:00:00Z')", (scatto, inquadratura))


def test_le_impronte_gia_calcolate_sopravvivono_alla_griglia(tmp_path, monkeypatch):
    monkeypatch.setenv("OFFICINA_ARCHIVIO", str(tmp_path / "archivio"))
    accesso.chiudi(con_copia=False)
    from officina.impostazioni import posizione

    dove = posizione("finto")
    dove.database.parent.mkdir(parents=True, exist_ok=True)
    connessione = database.connetti(dove.database)
    database.crea_da_zero(connessione)
    connessione.execute("PRAGMA user_version = 1")
    for migrazione in migrazioni.MIGRAZIONI:
        if 2 <= migrazione.versione <= 14:
            migrazione.applica(connessione)
    connessione.execute("PRAGMA user_version = 14")
    for inquadratura in ("intera", "persona", "stretto"):
        _un_impronta(connessione, inquadratura)
    connessione.commit()
    connessione.close()

    aperto = accesso.apri("finto")
    try:
        righe = list(aperto.connessione.execute(
            "SELECT inquadratura FROM impronte ORDER BY inquadratura"))
        assert [r[0] for r in righe] == ["intera", "persona", "stretto"]

        _un_impronta(aperto.connessione, "griglia_r03c05")
        try:
            _un_impronta(aperto.connessione, "quello_che_mi_pare")
        except sqlite3.IntegrityError:
            pass
        else:
            raise AssertionError("il controllo sull'inquadratura non c'è più")

        indici = {r[0] for r in aperto.connessione.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index'")}
        assert "impronte_per_passata" in indici
        piano = " ".join(r[3] for r in aperto.connessione.execute(
            "EXPLAIN QUERY PLAN SELECT id FROM impronte WHERE scatto_id = 1"))
        assert "INDEX" in piano and "scatto_id=?" in piano
    finally:
        accesso.chiudi(con_copia=False)


def test_la_domanda_delle_arrivate_non_legge_tutto_l_archivio():
    connessione = sqlite3.connect(":memory:")
    connessione.row_factory = sqlite3.Row
    migrazioni.aggiorna(connessione)

    piano = " ".join(
        riga["detail"] for riga in connessione.execute(
            "EXPLAIN QUERY PLAN "
            "SELECT count(*) AS q FROM file_media "
            "WHERE genere = 'immagine' AND aggiunto_il > ?", ("2024",)))
    assert "file_media_arrivo" in piano, (
        f"la domanda legge tutta la tabella invece dell'indice: {piano}")

    """La domanda accanto, sulla stessa schermata, aveva il suo indice buono e
       un indice nuovo può portarglielo via: è successo con la prima forma
       che avevo provato, e l'ha resa quattro volte e mezzo più lenta."""
    accanto = " ".join(
        riga["detail"] for riga in connessione.execute(
            "EXPLAIN QUERY PLAN "
            "SELECT count(*) AS q FROM file_media "
            "WHERE genere = 'immagine' AND impronta_occhio IS NULL"))
    assert "file_per_impronta_occhio" in accanto, (
        f"l'indice nuovo ha portato via l'indice alla domanda accanto: {accanto}")


def test_le_due_letture_col_ritorno_alla_tabella_sono_chiuse():
    connessione = sqlite3.connect(":memory:")
    connessione.row_factory = sqlite3.Row
    migrazioni.aggiorna(connessione)

    def piano(domanda):
        return " ".join(riga["detail"] for riga in connessione.execute(
            "EXPLAIN QUERY PLAN " + domanda))

    tocco = piano("SELECT nodo_id, max(creata_il) AS quando FROM etichette "
                  "WHERE stato = 'si' GROUP BY nodo_id")
    assert "COVERING INDEX etichette_per_nodo" in tocco, (
        f"l'ultimo tocco di ogni nodo torna alla tabella: {tocco}")

    passate = piano(
        "SELECT descrittore, versione, count(*) AS impronte, "
        "count(DISTINCT scatto_id) AS scatti, max(calcolata_il) AS ultima, "
        "max(dimensione) AS dimensione FROM impronte "
        "GROUP BY descrittore, versione")
    assert "COVERING INDEX impronte_per_passata" in passate, (
        f"il riassunto delle passate torna alla tabella: {passate}")

    accanto = piano("SELECT count(*) AS q FROM impronte "
                    "WHERE descrittore = 'dinov3' AND versione = 'v1'")
    assert "impronte_per_passata" in accanto, (
        f"«quante ne mancano» ha perso il suo indice: {accanto}")
    galleria = piano("SELECT nodo_id, count(*) AS quanti FROM etichette "
                     "WHERE stato = 'si' GROUP BY nodo_id")
    assert "COVERING INDEX etichette_per_nodo" in galleria, (
        f"«quante per nodo» ha perso il suo indice: {galleria}")
