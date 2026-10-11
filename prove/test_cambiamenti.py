from __future__ import annotations

from officina.modello import cambiamenti, etichette, nodi


def test_la_macchina_nasce_da_sola_e_resta_la_stessa(archivio):
    mia = cambiamenti.questa_macchina(archivio.connessione)
    assert mia["questa"] == 1
    assert len(mia["codice"]) == 32
    assert mia["nome"]
    ancora = cambiamenti.questa_macchina(archivio.connessione)
    assert ancora["id"] == mia["id"]
    assert ancora["codice"] == mia["codice"]


def test_il_nome_si_cambia_e_il_codice_no(archivio):
    mia = cambiamenti.questa_macchina(archivio.connessione)
    cambiamenti.rinomina_macchina(archivio.connessione, mia["id"], "ZenBook")
    dopo = cambiamenti.questa_macchina(archivio.connessione)
    assert dopo["nome"] == "ZenBook"
    assert dopo["codice"] == mia["codice"]


def test_ogni_gesto_lascia_una_riga(archivio):
    connessione = archivio.connessione
    nodo_id = nodi.crea(connessione, "mare")
    connessione.execute(
        "INSERT INTO scatti (id, genere, istante_utc, giorno, creato_il) "
        "VALUES (1, 'foto', ?, ?, ?)",
        ("2026-01-01T10:00:00Z", "2026-01-01", "2026-01-01T10:00:00Z"),
    )
    etichette.metti(connessione, 1, nodo_id, "si", "utente")
    etichette.togli(connessione, 1, nodo_id)
    nodi.rinomina(connessione, nodo_id, "spiaggia")
    nodi.cambia_stato(connessione, nodo_id, "cestino")

    righe = cambiamenti.da_mandare(connessione)
    assert [(r["cosa"], r["azione"]) for r in righe] == [
        ("nodo", "creato"),
        ("etichetta", "messa"),
        ("etichetta", "tolta"),
        ("nodo", "rinominato"),
        ("nodo", "stato"),
    ]
    assert [r["seriale"] for r in righe] == [1, 2, 3, 4, 5]
    assert righe[3]["valore"] == "spiaggia"
    assert righe[4]["valore"] == "cestino"


def test_le_proposte_della_macchina_non_finiscono_nel_registro(archivio):
    connessione = archivio.connessione
    nodo_id = nodi.crea(connessione, "cani")
    connessione.execute(
        "INSERT INTO scatti (id, genere, istante_utc, giorno, creato_il) "
        "VALUES (1, 'foto', ?, ?, ?)",
        ("2026-01-01T10:00:00Z", "2026-01-01", "2026-01-01T10:00:00Z"),
    )
    prima = cambiamenti.quanti_da_mandare(connessione)
    etichette.metti(connessione, 1, nodo_id, "si", "sistema", sicurezza=0.9)
    assert cambiamenti.quanti_da_mandare(connessione) == prima


def test_annullare_non_cancella_la_riga_ma_ne_scrive_una_contraria(archivio):
    connessione = archivio.connessione
    nodo_id = nodi.crea(connessione, "gatti")
    connessione.execute(
        "INSERT INTO scatti (id, genere, istante_utc, giorno, creato_il) "
        "VALUES (1, 'foto', ?, ?, ?)",
        ("2026-01-01T10:00:00Z", "2026-01-01", "2026-01-01T10:00:00Z"),
    )
    etichette.metti(connessione, 1, nodo_id, "si", "utente")
    quante = cambiamenti.quanti_da_mandare(connessione)
    assert etichette.annulla_ultima(connessione) is True

    righe = cambiamenti.da_mandare(connessione)
    assert len(righe) == quante + 1
    assert (righe[-1]["cosa"], righe[-1]["azione"]) == ("etichetta", "tolta")


def test_da_mandare_riparte_da_dove_si_era_fermato(archivio):
    connessione = archivio.connessione
    nodi.crea(connessione, "uno")
    nodi.crea(connessione, "due")
    nodi.crea(connessione, "tre")
    tutte = cambiamenti.da_mandare(connessione)
    assert len(tutte) == 3
    assert cambiamenti.da_mandare(connessione, tutte[-1]["seriale"]) == []
    assert len(cambiamenti.da_mandare(connessione, tutte[0]["seriale"])) == 2
