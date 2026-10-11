from __future__ import annotations

from officina import ricerca
from officina.modello import etichette, nodi, persone


def test_riconosce_un_nodo_dentro_la_frase(archivio_misurabile):
    connessione = archivio_misurabile.connessione
    riga = connessione.execute(
        "SELECT id, nome FROM nodi WHERE nome LIKE 'nodo_%' LIMIT 1").fetchone()

    risposta = ricerca.cerca(connessione, archivio_misurabile.dove.modelli,
                             f"foto di {riga['nome']} al mare")
    nodi_capiti = [c for c in risposta.capito if c.genere == "nodo"]
    assert [c.numero for c in nodi_capiti] == [riga["id"]]
    assert risposta.trovati, "un nodo riconosciuto porta risultati certi"
    assert all(t.sorgente == "tua" for t in risposta.trovati)


def test_riconosce_una_persona_e_un_anno(archivio):
    connessione = archivio.connessione
    quale = persone.crea(connessione, "Persona A")
    connessione.commit()

    risposta = ricerca.cerca(connessione, archivio.dove.modelli,
                             "Persona A al mare nel 2024")
    capiti = {c.genere: c for c in risposta.capito}
    assert capiti["persona"].testo == "Persona A"
    assert capiti["persona"].numero == quale
    assert capiti["quando"].testo == "2024"


def test_preferisce_il_nome_piu_lungo(archivio):
    connessione = archivio.connessione
    corto = nodi.crea(connessione, "nodo_a", None)
    lungo = nodi.crea(connessione, "nodo_a lungo", None)
    connessione.commit()

    risposta = ricerca.cerca(connessione, archivio.dove.modelli, "nodo_a lungo")
    trovati = [c.numero for c in risposta.capito if c.genere == "nodo"]
    assert lungo in trovati
    assert corto not in trovati


def test_senza_il_modello_lo_dice_col_nome_del_comando(archivio_misurabile):
    risposta = ricerca.cerca(archivio_misurabile.connessione,
                             archivio_misurabile.dove.modelli, "un tramonto")
    assert risposta.con_le_parole is False
    assert "siglip2" in risposta.perche_no
    assert "etichettato tu" in risposta.perche_no


def test_una_frase_vuota_non_cerca_niente(archivio):
    risposta = ricerca.cerca(archivio.connessione, archivio.dove.modelli, "   ")
    assert risposta.trovati == []
    assert risposta.capito == []


def test_i_tre_livelli_e_mai_una_percentuale():
    elenco = [
        ricerca.Trovato(1, 1, "somiglianza", punteggio=0.20),
        ricerca.Trovato(2, 2, "somiglianza", punteggio=0.15),
        ricerca.Trovato(3, 3, "somiglianza", punteggio=0.05),
    ]
    ricerca._dai_i_livelli(elenco)
    assert [t.livello for t in elenco] == list(ricerca.LIVELLI)
    for trovato in elenco:
        assert "%" not in trovato.livello


def test_senza_il_modello_linguistico_restano_le_forme_fisse(tmp_path):
    riscritta = ricerca._riscrivi("  cappello   di paglia ", tmp_path, True)
    assert riscritta.modi[0] == "cappello di paglia"
    assert all("cappello di paglia" in modo for modo in riscritta.modi)
    assert riscritta.da_dove == "forme fisse"
    assert not riscritta.dal_modello


def test_il_primo_tempo_non_apre_mai_il_modello(tmp_path, monkeypatch):
    def mai(*_, **__):
        raise AssertionError("il primo tempo ha aperto il modello linguistico")

    monkeypatch.setattr(ricerca.lingua, "apri", mai)
    riscritta = ricerca._riscrivi("cappello di paglia", tmp_path, False)
    assert riscritta.modi


def test_un_nodo_e_una_persona_insieme(archivio_misurabile):
    connessione = archivio_misurabile.connessione
    riga = connessione.execute(
        "SELECT id, nome FROM nodi WHERE nome LIKE 'nodo_%' LIMIT 1").fetchone()
    chi = persone.crea(connessione, "Persona A")
    scatto_id = connessione.execute(
        "SELECT scatto_id FROM etichette WHERE nodo_id = ? AND stato='si' LIMIT 1",
        (riga["id"],)).fetchone()[0]
    persone.metti_a_mano(connessione, scatto_id, chi)
    connessione.commit()

    risposta = ricerca.cerca(connessione, archivio_misurabile.dove.modelli,
                             f"Persona A con {riga['nome']}")
    generi = {c.genere for c in risposta.capito}
    assert {"nodo", "persona"} <= generi
    assert scatto_id in [t.scatto_id for t in risposta.trovati]
    numeri = [t.scatto_id for t in risposta.trovati]
    assert len(numeri) == len(set(numeri))


def test_due_certezze_restringono_non_allargano(archivio_misurabile):
    connessione = archivio_misurabile.connessione
    riga = connessione.execute(
        "SELECT id, nome FROM nodi WHERE nome LIKE 'nodo_%' LIMIT 1").fetchone()
    anno = connessione.execute(
        "SELECT substr(giorno, 1, 4) FROM scatti WHERE giorno IS NOT NULL "
        "LIMIT 1").fetchone()[0]

    solo_nodo = ricerca.cerca(connessione, archivio_misurabile.dove.modelli,
                              riga["nome"])
    con_anno = ricerca.cerca(connessione, archivio_misurabile.dove.modelli,
                             f"{riga['nome']} nel {anno}")
    assert len(con_anno.trovati) <= len(solo_nodo.trovati)
    for trovato in con_anno.trovati:
        assert trovato.giorno is None or trovato.giorno.startswith(anno)


def test_le_etichette_di_qualcun_altro_non_entrano(archivio_misurabile):
    connessione = archivio_misurabile.connessione
    solitario = nodi.crea(connessione, "nodo_solitario", None)
    scatto_id = connessione.execute("SELECT id FROM scatti ORDER BY id LIMIT 1").fetchone()[0]
    etichette.metti(connessione, scatto_id, solitario, "si", "utente")
    connessione.commit()

    risposta = ricerca.cerca(connessione, archivio_misurabile.dove.modelli,
                             "nodo_solitario")
    assert [t.scatto_id for t in risposta.trovati] == [scatto_id]
