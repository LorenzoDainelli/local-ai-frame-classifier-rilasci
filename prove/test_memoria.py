from __future__ import annotations

import sqlite3

import pytest

from officina.archivio import memoria


@pytest.fixture
def db(tmp_path):
    connessione = sqlite3.connect(tmp_path / "prova.sqlite")
    connessione.execute("CREATE TABLE cose (id INTEGER PRIMARY KEY, valore TEXT)")
    connessione.commit()
    yield connessione
    connessione.close()


def test_non_ricalcola_se_non_e_cambiato_niente(db):
    ricordo = memoria.Ricordo("prova")
    volte = []
    for _ in range(5):
        ricordo.prendi(db, lambda: volte.append(1) or 42)
    assert len(volte) == 1


def test_ricalcola_appena_qualcuno_scrive(db):
    ricordo = memoria.Ricordo("prova")
    quante = {"n": 0}

    def calcola():
        quante["n"] += 1
        return quante["n"]

    assert ricordo.prendi(db, calcola) == 1
    assert ricordo.prendi(db, calcola) == 1
    db.execute("INSERT INTO cose (valore) VALUES ('a')")
    assert ricordo.prendi(db, calcola) == 2


def test_ricalcola_anche_se_ha_scritto_un_altro_programma(db, tmp_path):
    ricordo = memoria.Ricordo("prova")
    quante = {"n": 0}

    def calcola():
        quante["n"] += 1
        return quante["n"]

    db.commit()
    assert ricordo.prendi(db, calcola) == 1
    altro = sqlite3.connect(tmp_path / "prova.sqlite")
    altro.execute("INSERT INTO cose (valore) VALUES ('b')")
    altro.commit()
    altro.close()
    db.commit()
    assert ricordo.prendi(db, calcola) == 2


def test_una_connessione_nuova_non_eredita_il_ricordo(db, tmp_path):
    ricordo = memoria.Ricordo("prova")
    assert ricordo.prendi(db, lambda: "primo") == "primo"
    altro = sqlite3.connect(tmp_path / "secondo.sqlite")
    try:
        assert ricordo.prendi(altro, lambda: "secondo") == "secondo"
    finally:
        altro.close()


def test_scorda_fa_ricalcolare(db):
    ricordo = memoria.Ricordo("prova")
    assert ricordo.prendi(db, lambda: 1) == 1
    ricordo.scorda()
    assert ricordo.prendi(db, lambda: 2) == 2


def test_chiavi_diverse_risposte_diverse(db):
    ricordi = memoria.Ricordi("prova")
    assert ricordi.prendi(db, "a", lambda: "A") == "A"
    assert ricordi.prendi(db, "b", lambda: "B") == "B"
    assert ricordi.prendi(db, "a", lambda: "sbagliata") == "A"


def test_una_scrittura_le_butta_via_tutte(db):
    ricordi = memoria.Ricordi("prova")
    ricordi.prendi(db, "a", lambda: "vecchia")
    ricordi.prendi(db, "b", lambda: "vecchia")
    db.execute("INSERT INTO cose (valore) VALUES ('c')")
    assert ricordi.prendi(db, "a", lambda: "nuova") == "nuova"
    assert ricordi.prendi(db, "b", lambda: "nuova") == "nuova"


def test_si_butta_quella_che_non_si_guarda_da_piu_tempo(db):
    ricordi = memoria.Ricordi("prova", quanti_al_massimo=3)
    for chiave in ("a", "b", "c"):
        ricordi.prendi(db, chiave, lambda chiave=chiave: chiave)
    ricordi.prendi(db, "a", lambda: "non serve")
    ricordi.prendi(db, "d", lambda: "d")
    assert ricordi.prendi(db, "a", lambda: "ricalcolata") == "a"
    assert ricordi.prendi(db, "b", lambda: "ricalcolata") == "ricalcolata"


def test_non_ne_tiene_piu_di_quanti_ne_ha_promessi(db):
    ricordi = memoria.Ricordi("prova", quanti_al_massimo=4)
    for n in range(40):
        ricordi.prendi(db, n, lambda n=n: n)
    assert len(ricordi._tenuti) == 4


def test_il_segno_cambia_solo_quando_cambia_il_database(db):
    prima = memoria.com_e_adesso(db)
    assert memoria.com_e_adesso(db) == prima
    db.execute("INSERT INTO cose (valore) VALUES ('d')")
    assert memoria.com_e_adesso(db) != prima
