from __future__ import annotations

import pytest

from officina.apprendimento import esempi as raccolta
from officina.apprendimento import gruppi, pagella
from officina.apprendimento.classificatore import addestra
from officina.descrittori import preparazione, vettori
from officina.descrittori.disegnato import Disegnato
from officina.finto import immagini
from officina.modello import etichette, nodi


def _impronte(tema: str, semi) -> list[list[float]]:
    descrittore = Disegnato()
    return [descrittore.descrivi_una(
        preparazione.in_quadrato(immagini.disegna(tema, seme, (400, 300)), 224))
        for seme in semi]


def test_impara_a_distinguere_due_scene():
    numpy = vettori.numpy_o_spiega()
    si = _impronte("tema_a", range(10))
    no = _impronte("tema_c", range(10)) + _impronte("tema_f", range(10))
    modello = addestra(numpy.array(si + no), numpy.array([1] * 10 + [0] * 20))

    nuovi_si = numpy.array(_impronte("tema_a", range(50, 56)))
    nuovi_no = numpy.array(_impronte("tema_c", range(50, 56)))
    assert modello.punteggi(nuovi_si).mean() > modello.punteggi(nuovi_no).mean()
    assert (modello.punteggi(nuovi_si) > 0.5).all()


def test_due_addestramenti_uguali_danno_lo_stesso_modello():
    numpy = vettori.numpy_o_spiega()
    tabella = numpy.array(_impronte("tema_b", range(6)) + _impronte("tema_d", range(6)))
    risposte = numpy.array([1] * 6 + [0] * 6)
    primo = addestra(tabella, risposte)
    secondo = addestra(tabella, risposte)
    assert numpy.allclose(primo.pesi, secondo.pesi)
    assert primo.scarto == secondo.scarto


def test_tre_si_contro_duecento_no_non_diventano_sempre_no():
    numpy = vettori.numpy_o_spiega()
    si = _impronte("tema_a", range(3))
    no = _impronte("tema_c", range(30)) + _impronte("tema_f", range(30))
    modello = addestra(numpy.array(si + no), numpy.array([1] * 3 + [0] * 60))
    nuovi = numpy.array(_impronte("tema_a", range(80, 84)))
    assert (modello.punteggi(nuovi) > 0.5).mean() >= 0.75


def test_le_fette_non_spezzano_mai_un_gruppo():
    nostri = [1, 1, 1, 2, 2, 3, 4, 4, 4, 4, 5, 6, 7, 8]
    fette = gruppi.a_fette(nostri, quante=4)
    assert sum(len(fetta) for fetta in fette) == len(nostri)
    for numero in set(nostri):
        dove = {indice for indice, fetta in enumerate(fette)
                for posizione in fetta if nostri[posizione] == numero}
        assert len(dove) == 1, f"il gruppo {numero} è finito in {len(dove)} fette"


def test_le_raffiche_diventano_un_gruppo_solo(archivio_misurabile):
    with archivio_misurabile.lettura() as connessione:
        tutti_gli_scatti = [riga["id"] for riga in connessione.execute(
            "SELECT id FROM scatti ORDER BY id").fetchall()]
        gruppo_di = gruppi.per_divisione(connessione, tutti_gli_scatti)
    assert len(gruppo_di) == len(tutti_gli_scatti)
    assert len(set(gruppo_di.values())) < len(tutti_gli_scatti), (
        "nell'archivio finto c'è almeno una raffica: deve essere un gruppo solo")


def test_pochi_esempi_non_ricevono_un_voto():
    numpy = vettori.numpy_o_spiega()
    tabella = numpy.array(_impronte("tema_a", range(2)) + _impronte("tema_c", range(2)))
    voto = pagella.valuta(tabella, [1, 1, 0, 0], [1, 2, 3, 4])
    assert not voto.abbastanza
    assert voto.azzecca is None
    assert pagella.TROPPO_POCHI in voto.a_parole()


def test_il_voto_porta_sempre_il_numero_grezzo():
    numpy = vettori.numpy_o_spiega()
    si = _impronte("tema_a", range(8))
    no = _impronte("tema_c", range(8))
    voto = pagella.valuta(numpy.array(si + no), [1] * 8 + [0] * 8, list(range(16)))
    assert voto.abbastanza
    frase = voto.a_parole()
    assert "%" in frase and "esempi" in frase and "gruppi" in frase


def test_i_si_e_i_no_contano_come_due_meta_uguali():
    voto = pagella.Voto(esempi_si=8, esempi_no=200, gruppi_si=8, gruppi_no=200,
                        abbastanza=True, azzeccati_si=0, azzeccati_no=200,
                        proposti_a_torto=0, mancati=8)
    assert voto.azzecca == pytest.approx(0.5)


def test_un_ramo_esclusivo_regala_i_no(archivio):
    with archivio.scrittura() as connessione:
        connessione.execute(
            "INSERT INTO scatti (genere, creato_il) VALUES ('foto', '2024-01-01')")
        connessione.execute(
            "INSERT INTO scatti (genere, creato_il) VALUES ('foto', '2024-01-01')")
        ramo = nodi.crea(connessione, "ramo", None)
        connessione.execute("UPDATE nodi SET scegline_uno = 1 WHERE id = ?", (ramo,))
        primo = nodi.crea(connessione, "nodo_1", ramo)
        secondo = nodi.crea(connessione, "nodo_2", ramo)
        etichette.metti(connessione, 1, primo, "si")
        etichette.metti(connessione, 2, secondo, "si")

    with archivio.lettura() as connessione:
        del_primo = raccolta.di_nodo(connessione, primo)
    assert del_primo.si == [1]
    assert del_primo.no == [2]
    assert del_primo.no_regalati == 1

    with archivio.lettura() as connessione:
        senza = raccolta.di_nodo(connessione, primo, con_esclusivi=False)
    assert senza.no == []


def test_non_deciso_non_diventa_mai_un_no(archivio):
    with archivio.scrittura() as connessione:
        for _ in range(5):
            connessione.execute(
                "INSERT INTO scatti (genere, creato_il) VALUES ('foto', '2024-01-01')")
        nodo = nodi.crea(connessione, "solo", None)
        etichette.metti(connessione, 1, nodo, "si")

    with archivio.lettura() as connessione:
        suoi = raccolta.di_nodo(connessione, nodo)
    assert suoi.si == [1]
    assert suoi.no == [], "quattro scatti mai guardati non sono quattro «no»"


def test_un_ramo_interno_diventa_scegline_uno_dall_albero(archivio):
    from fastapi.testclient import TestClient

    from officina.apprendimento import proposte
    from officina.web import server
    from officina.web.strade import comune

    with archivio.scrittura() as connessione:
        for _ in range(3):
            connessione.execute(
                "INSERT INTO scatti (genere, creato_il) VALUES ('foto', '2024-01-01')")
        radice = nodi.crea(connessione, "Ramo X", None)
        stato = nodi.crea(connessione, "Stato", radice)
        aperto = nodi.crea(connessione, "Aperto", stato)
        chiuso = nodi.crea(connessione, "Chiuso", stato)
        completezza = nodi.crea(connessione, "Completezza", radice)
        parziale = nodi.crea(connessione, "Parziale", completezza)
        etichette.metti(connessione, 1, aperto, "si")
        etichette.metti(connessione, 2, chiuso, "si")
        etichette.metti(connessione, 3, parziale, "si")

    comune.bottega = proposte.Bottega()
    cliente = TestClient(server.app, client=("127.0.0.1", 51000))
    assert cliente.get(f"/api/albero/nodo/{stato}").json()["scegline_uno"] is False
    assert cliente.post("/api/albero/scegline-uno",
                        data={"nodo_id": stato, "acceso": "1"}).json()["fatto"]
    assert cliente.get(f"/api/albero/nodo/{stato}").json()["scegline_uno"] is True

    with archivio.lettura() as connessione:
        di_aperto = raccolta.di_nodo(connessione, aperto)
    assert di_aperto.no == [2]
    assert di_aperto.no_regalati == 1

    cliente.post("/api/albero/scegline-uno", data={"nodo_id": stato, "acceso": "0"})
    with archivio.lettura() as connessione:
        assert raccolta.di_nodo(connessione, aperto).no == []


def test_un_ramo_si_copia_dentro_piu_oggetti_coi_figli(archivio):
    from fastapi.testclient import TestClient

    from officina.apprendimento import proposte
    from officina.web import server
    from officina.web.strade import comune

    with archivio.scrittura() as connessione:
        connessione.execute(
            "INSERT INTO scatti (genere, creato_il) VALUES ('foto', '2024-01-01')")
        radice = nodi.crea(connessione, "Ramo X", None)
        scatola = nodi.crea(connessione, "Scatola", radice)
        busta = nodi.crea(connessione, "Busta", radice)
        sacchetto = nodi.crea(connessione, "Sacchetto", radice)
        stato = nodi.crea(connessione, "Stato", scatola)
        connessione.execute("UPDATE nodi SET scegline_uno = 1 WHERE id = ?", (stato,))
        for nome in ("Aperto completo", "Aperto parziale",
                     "Chiuso completo", "Chiuso parziale"):
            nodi.crea(connessione, nome, stato)
        etichette.metti(connessione, 1, stato, "si")
        nodi.crea(connessione, "Stato", sacchetto)

    comune.bottega = proposte.Bottega()
    cliente = TestClient(server.app, client=("127.0.0.1", 51000))
    risposta = cliente.post("/api/albero/copia", data={
        "nodo_id": stato, "dentro": f"{busta},{sacchetto},{stato}"}).json()
    assert risposta["copiati"] == ["Busta"]
    assert [s["nome"] for s in risposta["saltati"]] == ["Sacchetto", "Stato"]

    with archivio.lettura() as connessione:
        copia = connessione.execute(
            "SELECT id, scegline_uno FROM nodi WHERE genitore_id = ? AND nome = 'Stato'",
            (busta,)).fetchone()
        assert copia["scegline_uno"] == 1
        figli = [r["nome"] for r in connessione.execute(
            "SELECT nome FROM nodi WHERE genitore_id = ? ORDER BY id", (copia["id"],))]
        assert figli == ["Aperto completo", "Aperto parziale",
                         "Chiuso completo", "Chiuso parziale"]
        assert connessione.execute(
            "SELECT count(*) FROM etichette WHERE nodo_id = ?", (copia["id"],)).fetchone()[0] == 0
        assert connessione.execute(
            "SELECT count(*) FROM nodi WHERE genitore_id = ?",
            (nodi.discendenti(connessione, sacchetto)[1],)).fetchone()[0] == 0
