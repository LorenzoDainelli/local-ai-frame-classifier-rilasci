from __future__ import annotations

import shutil

from fastapi.testclient import TestClient

from officina.apprendimento import proposte
from officina.importazione import annulla, gruppi, scansione
from officina.importazione.motore import Motore


def _importa(archivio, cartelle):
    motore = Motore(archivio)
    motore.prepara(cartelle)
    assert motore.esegui().stato == "finita"


def _quanti(connessione, tabella):
    return connessione.execute(f"SELECT count(*) FROM {tabella}").fetchone()[0]


def test_annullare_toglie_gli_scatti_ma_non_gli_originali(archivio, tmp_path):
    from officina.finto import generatore

    generale = tmp_path / "generale"
    snap = tmp_path / "snap"
    generatore.genera(generale, quanti=6, seme=3, leggero=True)
    generatore.genera(snap, quanti=4, seme=9, leggero=True)
    copiati = sorted(p for p in generale.rglob("*") if p.is_file())[:2]
    for file in copiati:
        shutil.copy2(file, snap / f"copia_{file.name}")
    connessione = archivio.connessione
    scansione.aggiungi_cartella(connessione, generale)
    snap_id = scansione.aggiungi_cartella(connessione, snap, gruppi.trova_o_crea(connessione, "Snap"))
    connessione.commit()
    _importa(archivio, [generale])
    prima = _quanti(connessione, "scatti")
    _importa(archivio, [snap])
    assert _quanti(connessione, "scatti") > prima

    conto = annulla.conta(connessione, snap_id)
    assert conto.spariscono == _quanti(connessione, "scatti") - prima
    annulla.annulla(connessione, snap_id)
    connessione.commit()

    assert _quanti(connessione, "scatti") == prima
    assert connessione.execute(
        "SELECT count(*) FROM cartelle_sorgente WHERE id = ?", (snap_id,)).fetchone()[0] == 0
    assert all(file.exists() for file in snap.rglob("*"))
    assert connessione.execute(
        "SELECT count(*) FROM percorsi WHERE percorso LIKE ?", ("%copia_%",)).fetchone()[0] == 0


def test_il_doppione_tenuto_dalla_cartella_annullata_rimette_l_originale(archivio):
    from officina.archivio.database import adesso

    connessione = archivio.connessione
    connessione.execute("INSERT INTO cartelle_sorgente (id, percorso, aggiunta_il) VALUES (1, 'A', ?)", (adesso(),))
    connessione.execute("INSERT INTO cartelle_sorgente (id, percorso, aggiunta_il) VALUES (2, 'B', ?)", (adesso(),))
    for numero, cartella, fuori in ((1, 1, 1), (2, 2, 0)):
        connessione.execute("INSERT INTO scatti (id, genere, creato_il, fuori_archivio) VALUES (?, 'foto', ?, ?)",
                            (numero, adesso(), fuori))
        connessione.execute(
            "INSERT INTO file_media (id, impronta, dimensione, genere, scatto_id, ruolo, aggiunto_il) "
            "VALUES (?, ?, 1, 'immagine', ?, 'principale', ?)", (numero, f"i{numero}", numero, adesso()))
        connessione.execute(
            "INSERT INTO percorsi (file_id, cartella_id, percorso, nome, visto_il) VALUES (?, ?, ?, 'x', ?)",
            (numero, cartella, f"{cartella}/x{numero}", adesso()))
    connessione.execute(
        "INSERT INTO doppioni_decisi (firma, scelta, tenuto_id, messi_fuori, deciso_il) "
        "VALUES ('f', 'tenuto', 2, '1', ?)", (adesso(),))

    annulla.annulla(connessione, 2)

    assert connessione.execute("SELECT fuori_archivio FROM scatti WHERE id = 1").fetchone()[0] == 0
    assert connessione.execute("SELECT count(*) FROM scatti WHERE id = 2").fetchone()[0] == 0
    assert connessione.execute("SELECT count(*) FROM doppioni_decisi").fetchone()[0] == 0


def test_il_gruppo_scelto_resta_ovunque(archivio, tmp_path):
    from officina.web import server
    from officina.web.strade import comune

    comune.bottega = proposte.Bottega()
    cliente = TestClient(server.app, client=("127.0.0.1", 51000))
    gruppo_id = gruppi.trova_o_crea(archivio.connessione, "Snap")
    archivio.connessione.commit()
    cartella = tmp_path / "nuova"
    cartella.mkdir()
    cliente.post("/importazione/cartella", data={"percorso": str(cartella), "gruppo": str(gruppo_id)},
                 follow_redirects=False)
    assert gruppi.scelto(archivio.connessione, "intelligenza") == gruppo_id
    assert gruppi.scelto(archivio.connessione, "etichetta") == gruppo_id
    pagina = cliente.get("/importazione").text
    assert f'<option value="{gruppo_id}" selected>Snap</option>' in pagina


def test_piu_gruppi_di_persone_si_uniscono_in_uno(archivio):
    from officina.modello import persone
    from officina.web import server
    from officina.web.strade import comune

    comune.bottega = proposte.Bottega()
    cliente = TestClient(server.app, client=("127.0.0.1", 51000))
    connessione = archivio.connessione
    meta, uno, due = (persone.crea(connessione) for _ in range(3))
    connessione.commit()
    risposta = cliente.post("/persone/unisci", data={"gruppi": [str(uno), str(due), str(meta)],
                                                     "verso": str(meta)}, follow_redirects=False)
    assert risposta.status_code == 303
    stati = dict(connessione.execute("SELECT id, stato FROM persone").fetchall())
    assert stati[uno] == stati[due] == "congelata"
    assert stati[meta] != "congelata"


def test_unisci_i_gruppi_sta_accanto_a_dai_i_nomi(archivio):
    from officina.modello import persone
    from officina.web import server
    from officina.web.strade import comune

    comune.bottega = proposte.Bottega()
    cliente = TestClient(server.app, client=("127.0.0.1", 51000))
    connessione = archivio.connessione
    for _ in range(2):
        persone.crea(connessione)
    connessione.commit()
    pagina = cliente.get("/persone").text
    assert "data-unisci-via" in pagina
    assert "pe-barra-unisci" in pagina
    assert "unisci_persone.js" in pagina
    assert "pe-unisci-dentro" not in pagina
