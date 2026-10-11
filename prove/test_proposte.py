from __future__ import annotations

import pytest

from officina.apprendimento import proposte
from officina.modello import etichette, nodi


@pytest.fixture
def bottega(archivio_misurabile):
    bottega = proposte.Bottega()
    bottega.riaddestra(archivio_misurabile.connessione)
    return bottega


def test_sceglie_il_descrittore_che_c_e(archivio_misurabile):
    nome, versione = proposte.scegli_descrittore(archivio_misurabile.connessione)
    assert nome == "disegnato"
    assert versione


def test_senza_impronte_non_propone_e_non_esplode(archivio):
    bottega = proposte.Bottega()
    fatto = bottega.riaddestra(archivio.connessione)
    assert fatto["descrittore"] is None
    assert bottega.per_scatto(archivio.connessione, 1) == []


def test_addestra_un_classificatore_per_nodo(bottega, archivio_misurabile):
    assert len(bottega.modelli) >= 2
    for nodo_id in bottega.modelli:
        riga = nodi.per_id(archivio_misurabile.connessione, nodo_id)
        assert riga["stato"] == "attivo"


def test_propone_qualcosa_su_uno_scatto_gia_etichettato(bottega, archivio_misurabile):
    connessione = archivio_misurabile.connessione
    scatto_id = connessione.execute(
        "SELECT scatto_id FROM etichette WHERE stato = 'si' LIMIT 1"
    ).fetchone()[0]
    elenco = bottega.per_scatto(connessione, scatto_id)
    assert elenco, "con impronte ed esempi qualcosa deve pur uscire"
    assert all(0.0 <= p.punteggio <= 1.0 for p in elenco)


def test_il_filo_e_la_soglia_del_nodo_non_un_numero_unico(bottega, archivio_misurabile):
    connessione = archivio_misurabile.connessione
    scatto_id = connessione.execute(
        "SELECT scatto_id FROM etichette WHERE stato = 'si' LIMIT 1"
    ).fetchone()[0]

    prima = bottega.per_scatto(connessione, scatto_id, quante=9)
    sopra = [p for p in prima if p.ci_crede]
    if not sopra:
        pytest.skip("nessuna proposta sopra il filo su questo campione")

    vittima = sopra[0]
    connessione.execute("UPDATE nodi SET soglia = 0.999 WHERE id = ?",
                        (vittima.nodo_id,))
    connessione.commit()

    dopo = {p.nodo_id: p for p in bottega.per_scatto(connessione, scatto_id, quante=9)}
    assert dopo[vittima.nodo_id].ci_crede is False
    for altro in sopra[1:]:
        assert dopo[altro.nodo_id].ci_crede is True


def test_le_proposte_arrivano_ordinate(bottega, archivio_misurabile):
    connessione = archivio_misurabile.connessione
    scatto_id = connessione.execute(
        "SELECT scatto_id FROM etichette WHERE stato = 'si' LIMIT 1"
    ).fetchone()[0]
    elenco = bottega.per_scatto(connessione, scatto_id, quante=9)
    creduti = [p.ci_crede for p in elenco]
    assert creduti == sorted(creduti, reverse=True), \
        "una proposta sotto il filo non può stare sopra una sopra il filo"


def test_un_nodo_con_pochi_esempi_non_propone(archivio_misurabile):
    connessione = archivio_misurabile.connessione
    scarso = nodi.crea(connessione, "nodo_scarso", None)
    scatti = [riga["id"] for riga in connessione.execute(
        "SELECT id FROM scatti ORDER BY id LIMIT 3")]
    for scatto_id in scatti:
        etichette.metti(connessione, scatto_id, scarso, "si", "utente")
    connessione.commit()

    bottega = proposte.Bottega()
    bottega.riaddestra(connessione)
    assert scarso not in bottega.modelli


def test_il_perche_indica_scatti_veri(bottega, archivio_misurabile):
    connessione = archivio_misurabile.connessione
    scatto_id = connessione.execute(
        "SELECT scatto_id FROM etichette WHERE stato = 'si' LIMIT 1"
    ).fetchone()[0]
    for proposta in bottega.per_scatto(connessione, scatto_id, quante=9):
        for altro in proposta.simili:
            assert connessione.execute(
                "SELECT 1 FROM scatti WHERE id = ?", (altro,)).fetchone()
            assert altro != scatto_id
        assert proposta.perche
        assert "%" not in proposta.perche, "regola 58: mai una percentuale"


def test_si_riaddestra_da_sola_quando_arriva_un_etichetta(bottega, archivio_misurabile):
    connessione = archivio_misurabile.connessione
    assert bottega.scaduta(connessione) is False

    nodo_id = next(iter(bottega.modelli))
    scatto_id = connessione.execute(
        "SELECT id FROM scatti WHERE id NOT IN "
        "(SELECT scatto_id FROM etichette WHERE nodo_id = ?) LIMIT 1",
        (nodo_id,)).fetchone()[0]
    etichette.metti(connessione, scatto_id, nodo_id, "si", "utente")
    connessione.commit()

    assert bottega.scaduta(connessione) is True
    bottega.per_scatto(connessione, scatto_id)
    assert bottega.scaduta(connessione) is False


def test_non_propone_un_nodo_gia_deciso(bottega, archivio_misurabile):
    connessione = archivio_misurabile.connessione
    scatto_id = connessione.execute(
        "SELECT scatto_id FROM etichette WHERE stato = 'si' LIMIT 1"
    ).fetchone()[0]
    gia = {riga["nodo_id"] for riga in connessione.execute(
        "SELECT nodo_id FROM etichette WHERE scatto_id = ?", (scatto_id,))}
    elenco = bottega.per_scatto(connessione, scatto_id, quante=9, escludi=gia)
    assert not (gia & {p.nodo_id for p in elenco})


def test_la_proposta_profonda_porta_il_suo_percorso(archivio_misurabile):
    connessione = archivio_misurabile.connessione
    riga = connessione.execute(
        "SELECT id, genitore_id FROM nodi WHERE genitore_id IS NOT NULL LIMIT 1"
    ).fetchone()
    assert riga, "l'archivio finto ha un ramo, quindi un figlio ci deve essere"
    bottega = proposte.Bottega()
    bottega.riaddestra(connessione)
    if riga["id"] not in bottega.modelli:
        pytest.skip("quel nodo non ha abbastanza esempi")
    scatto_id = connessione.execute("SELECT id FROM scatti ORDER BY id LIMIT 1").fetchone()[0]
    trovata = [p for p in bottega.per_scatto(connessione, scatto_id, quante=99)
               if p.nodo_id == riga["id"]]
    assert trovata and trovata[0].percorso


def test_a_griglia_conta_la_casella_che_ci_crede_di_piu(bottega, archivio_misurabile):
    connessione = archivio_misurabile.connessione
    scatto_id = connessione.execute(
        "SELECT scatto_id FROM etichette WHERE stato = 'si' LIMIT 1"
    ).fetchone()[0]
    prima = {p.nodo_id: p.punteggio
             for p in bottega.per_scatto(connessione, scatto_id, quante=99)}

    colonne = [riga[1] for riga in connessione.execute("PRAGMA table_info(impronte)")
               if riga[1] not in ("id", "scatto_id", "inquadratura")]
    elenco = ", ".join(colonne)
    connessione.execute(
        f"INSERT INTO impronte (scatto_id, inquadratura, {elenco}) "
        f"SELECT ?, 'griglia_r00c00', {elenco} FROM impronte "
        "WHERE inquadratura = 'intera' AND fotogramma = 0 AND scatto_id != ? "
        "AND descrittore = ? LIMIT 1",
        (scatto_id, scatto_id, bottega.descrittore))
    connessione.commit()

    spenta = {p.nodo_id: p.punteggio
              for p in bottega.per_scatto(connessione, scatto_id, quante=99)}
    assert spenta == prima, "a griglia spenta le caselle non contano"

    archivio_misurabile.imposta("impronte_a_griglia", True)
    archivio_misurabile.imposta("griglia_come_si_somma", "massimo")
    dopo = {p.nodo_id: p.punteggio
            for p in bottega.per_scatto(connessione, scatto_id, quante=99)}
    assert all(dopo[n] >= prima[n] for n in prima)
    assert any(dopo[n] > prima[n] for n in prima)

    archivio_misurabile.imposta("griglia_come_si_somma", "media")
    media = {p.nodo_id: p.punteggio
             for p in bottega.per_scatto(connessione, scatto_id, quante=99)}
    assert all(media[n] <= dopo[n] for n in prima)


def test_dopo_un_etichetta_si_riaddestrano_solo_i_nodi_toccati(archivio_misurabile, monkeypatch):
    connessione = archivio_misurabile.connessione
    bottega = proposte.Bottega()
    bottega.riaddestra(connessione)
    nodo_id = next(iter(bottega.modelli))
    scatto_id = connessione.execute(
        "SELECT id FROM scatti WHERE id NOT IN "
        "(SELECT scatto_id FROM etichette WHERE nodo_id = ?) LIMIT 1", (nodo_id,)).fetchone()[0]
    etichette.metti(connessione, scatto_id, nodo_id, "si", "utente")
    connessione.commit()

    rifatti = []
    vero = proposte._addestra_uno
    monkeypatch.setattr(proposte, "_addestra_uno",
                        lambda c, esempi, d, v: rifatti.append(esempi.nodo_id) or vero(c, esempi, d, v))
    bottega.riaddestra(connessione)
    assert nodo_id in rifatti and len(rifatti) < len(bottega.esempi_di)

    da_capo = proposte.Bottega()
    da_capo.riaddestra(connessione)
    assert set(da_capo.modelli) == set(bottega.modelli)
    for quale, modello in da_capo.modelli.items():
        assert list(modello.pesi) == list(bottega.modelli[quale].pesi)
        assert modello.scarto == bottega.modelli[quale].scarto


def test_impronte_nuove_fanno_riaddestrare_tutto(archivio_misurabile, monkeypatch):
    connessione = archivio_misurabile.connessione
    bottega = proposte.Bottega()
    bottega.riaddestra(connessione)
    connessione.execute("UPDATE impronte SET calcolata_il = '2099-01-01T00:00:00' "
                        "WHERE id = (SELECT max(id) FROM impronte WHERE inquadratura = 'intera')")
    connessione.commit()
    rifatti = []
    vero = proposte._addestra_uno
    monkeypatch.setattr(proposte, "_addestra_uno",
                        lambda c, esempi, d, v: rifatti.append(esempi.nodo_id) or vero(c, esempi, d, v))
    bottega.riaddestra(connessione)
    assert len(rifatti) == len(bottega.esempi_di)
