from __future__ import annotations

import json

import numpy
import pytest

from officina.archivio.database import adesso, tutti, uno
from officina.corpi import imparate
from officina.descrittori import griglia, scheda
from officina.modello import parti as elenco
from officina.modello import sagome
from officina.ritocco import maschere
from officina.ritocco.scelta import Scelta


def _maschera(larga, alta, x0, y0, x1, y1) -> bytes:
    piena = numpy.zeros((alta, larga), dtype=bool)
    piena[y0:y1, x0:x1] = True
    return maschere.comprimi(piena, (0, 0), larga, alta)


def test_le_caselle_dentro_la_sagoma_dicono_si_quelle_fuori_no_quelle_a_meta_niente():
    caselle = griglia.caselle(800, 400, 8)
    coperte = imparate.coperture(_maschera(800, 400, 300, 100, 500, 300), caselle)
    risposte = [imparate.risposta(*voce) for voce in coperte]
    assert risposte.count(1) >= 2
    assert risposte.count(0) >= len(caselle) // 2
    assert None in risposte
    lontana = [i for i, c in enumerate(caselle) if c.riquadro[0] > 0.8 and c.riquadro[1] < 0.1]
    assert all(risposte[i] == 0 for i in lontana)
    assert imparate.coperture(b"", caselle) == []


def test_la_zona_e_il_centro_delle_caselle_vicine_sopra_la_soglia():
    caselle = griglia.caselle(800, 800, 8)
    punteggi = numpy.full(len(caselle), 0.1)
    assert imparate.zona(punteggi, caselle, 0.7) is None
    centro = next(i for i, c in enumerate(caselle) if c.riga == 3 and c.colonna == 3)
    vicina = next(i for i, c in enumerate(caselle) if c.riga == 3 and c.colonna == 4)
    lontana = next(i for i, c in enumerate(caselle) if c.riga == 7 and c.colonna == 7)
    punteggi[centro], punteggi[vicina], punteggi[lontana] = 0.95, 0.95, 0.9
    (cx, cy), regione, sicurezza = imparate.zona(punteggi, caselle, 0.7)
    assert sicurezza == pytest.approx(0.95)
    assert 0.4 < cx < 0.6 and 0.4 < cy < 0.55
    assert regione[0] + regione[2] < 0.8


def test_sam_conta_solo_se_la_sagoma_sta_nella_zona_del_modello():
    regione = (0.4, 0.4, 0.2, 0.2)
    assert imparate.coincide(_maschera(100, 100, 42, 42, 58, 58), regione)
    assert not imparate.coincide(_maschera(100, 100, 0, 0, 30, 30), regione)
    assert not imparate.coincide(_maschera(100, 100, 0, 0, 100, 100), regione)
    assert not imparate.coincide(b"", regione)


def test_la_soglia_sta_sopra_quasi_tutti_i_no_ma_dentro_i_limiti():
    assert imparate.soglia_da([]) == imparate.SOGLIA_SENZA_PROVA
    assert imparate.soglia_da([0.01] * 100) == imparate.SOGLIA_MINIMA
    assert imparate.soglia_da([0.99] * 100) == imparate.SOGLIA_MASSIMA
    valori = [i / 100 for i in range(100)]
    assert 0.9 < imparate.soglia_da(valori) < 0.99


def test_i_pesi_si_salvano_e_si_riaprono_uguali():
    from officina.apprendimento import classificatore

    modello = classificatore.Modello(pesi=numpy.array([0.5, -1.25, 3.0]), scarto=0.75,
                                     esempi_si=3, esempi_no=4)
    riaperto = imparate.da_byte(imparate.in_byte(modello))
    tabella = numpy.array([[1.0, 2.0, 3.0], [0.0, 0.0, 0.0]])
    assert numpy.allclose(riaperto.punteggi(tabella), modello.punteggi(tabella))


def _parte_con_sagome(archivio, quante: int):
    with archivio.lettura() as connessione:
        riga = uno(connessione,
                   "SELECT e.nodo_id, count(*) AS q FROM etichette e JOIN nodi n "
                   "ON n.id = e.nodo_id AND n.stato = 'attivo' WHERE e.stato = 'si' "
                   "GROUP BY e.nodo_id ORDER BY q DESC, e.nodo_id LIMIT 1")
        nodo_id = riga["nodo_id"]
        scatti = [r["scatto_id"] for r in tutti(
            connessione, "SELECT e.scatto_id FROM etichette e JOIN file_media f "
            "ON f.scatto_id = e.scatto_id AND f.genere = 'immagine' "
            "WHERE e.nodo_id = ? AND e.stato = 'si' GROUP BY e.scatto_id "
            "ORDER BY e.scatto_id", nodo_id)]
    assert len(scatti) >= quante
    fatte = []
    with archivio.scrittura() as connessione:
        parte_id = elenco.aggiungi(connessione, "Pezzo nuovo", "thing")
        elenco.scegli_il_nodo(connessione, parte_id, nodo_id)
        for scatto_id in scatti[:quante]:
            file_id = uno(connessione, "SELECT id FROM file_media WHERE scatto_id = ? "
                          "AND genere = 'immagine' ORDER BY id LIMIT 1", scatto_id)["id"]
            fatte.append(sagome.salva(
                connessione, scatto_id=scatto_id, file_id=file_id, nodo_id=nodo_id,
                maschera=_maschera(40, 30, 12, 9, 28, 21), come=sagome.MANO))
        for scatto_id in scatti:
            connessione.execute(
                "INSERT OR REPLACE INTO corpi_guardati (scatto_id, modello, versione, "
                "quanti, guardato_il, da_riguardare) VALUES (?, 'finto', '1', 1, ?, 0)",
                (scatto_id, "2000-01-01T00:00:00"))
    return parte_id, nodo_id, scatti, fatte


class SamFinto:

    def __init__(self, dove: str):
        self.dove = dove
        self.chiesti = []
        self.spento = False

    def scegli_su(self, segno, immagine, punti, riquadro, sulla_scheda):
        larga, alta = immagine.size
        self.chiesti.append((segno, punti[0].x, punti[0].y))
        piena = numpy.zeros((alta, larga), dtype=bool)
        if self.dove == "sul_punto":
            cx, cy = int(punti[0].x * larga), int(punti[0].y * alta)
            lato = max(2, larga // 40)
            piena[max(0, cy - lato):cy + lato, max(0, cx - lato):cx + lato] = True
        else:
            piena[:, :] = True
        return Scelta(maschere.comprimi(piena, (0, 0), larga, alta), 0.9, larga, alta, "finto")

    def spegni(self):
        self.spento = True


def _segna_disegnato(monkeypatch):
    from officina.apprendimento import proposte

    monkeypatch.setattr(proposte, "scegli_descrittore",
                        lambda connessione, voluto=None: ("disegnato", "x"))


def test_poche_sagome_non_fanno_un_modello(archivio_misurabile, monkeypatch):
    _segna_disegnato(monkeypatch)
    archivio = archivio_misurabile
    parte_id, *_ = _parte_con_sagome(archivio, imparate.MINIMO_SAGOME - 1)
    carta = scheda("disegnato")
    with archivio.lettura() as connessione:
        assert imparate.da_allenare(connessione, carta.nome, carta.versione) == []
        assert imparate.quanti_mancano(connessione) == 0
    imparate.Passata(archivio, sceglitore=SamFinto("sul_punto")).esegui()
    with archivio.lettura() as connessione:
        assert uno(connessione, "SELECT 1 FROM parti_imparate WHERE parte_id = ?",
                   parte_id) is None


@pytest.mark.parametrize("dove", ["sul_punto", "dappertutto"])
def test_la_parte_si_impara_dalle_sagome_e_si_cerca_negli_altri_scatti(
        archivio_misurabile, monkeypatch, dove):
    _segna_disegnato(monkeypatch)
    monkeypatch.setattr(imparate, "SOGLIA_MASSIMA", 0.5)
    monkeypatch.setattr(imparate, "SOGLIA_MINIMA", 0.0)
    archivio = archivio_misurabile
    parte_id, nodo_id, scatti, fatte = _parte_con_sagome(archivio, imparate.MINIMO_SAGOME + 2)
    carta = scheda("disegnato")
    with archivio.lettura() as connessione:
        assert [p for p, *_ in imparate.da_allenare(connessione, carta.nome,
                                                    carta.versione)] == [parte_id]
        assert imparate.quanti_mancano(connessione) == 1
    sam = SamFinto(dove)
    avanzamento = imparate.Passata(archivio, sceglitore=sam).esegui()
    assert avanzamento.allenate == 1
    assert sam.spento
    with archivio.lettura() as connessione:
        tenuta = uno(connessione, "SELECT * FROM parti_imparate WHERE parte_id = ?", parte_id)
        resoconto = json.loads(tenuta["misura"])
        assert tenuta["esempi"] == len(fatte)
        assert 0.0 <= resoconto["soglia"] <= 0.5
        assert resoconto["gruppi"]["tutte"]["su"] == resoconto["alla_prova"] > 0
        guardate = tutti(connessione, "SELECT * FROM parti_imparate_guardate")
        assert {r["scatto_id"] for r in guardate} == set(scatti)
        assert all(r["firma"] == tenuta["firma"] for r in guardate)
        trovate = tutti(connessione, "SELECT * FROM parti_trovate WHERE come = 'imparata'")
        assert trovate
        assert {r["parte_id"] for r in trovate} == {parte_id}
        if dove == "sul_punto":
            assert all(r["da_controllare"] == 0 and r["maschera"] for r in trovate)
        else:
            assert all(r["da_controllare"] == 1 and r["maschera"] is None for r in trovate)
        assert imparate.quanti_mancano(connessione) == 0
    sam.chiesti.clear()
    imparate.Passata(archivio, sceglitore=sam).esegui()
    assert sam.chiesti == []


def test_la_parola_trovata_vince_e_togliere_le_sagome_toglie_il_modello(
        archivio_misurabile, monkeypatch):
    _segna_disegnato(monkeypatch)
    monkeypatch.setattr(imparate, "SOGLIA_MASSIMA", 0.0)
    monkeypatch.setattr(imparate, "SOGLIA_MINIMA", 0.0)
    archivio = archivio_misurabile
    parte_id, nodo_id, scatti, fatte = _parte_con_sagome(archivio, imparate.MINIMO_SAGOME + 2)
    with archivio.scrittura() as connessione:
        for scatto_id in scatti:
            connessione.execute(
                "INSERT INTO parti_trovate (parte_id, scatto_id, fotogramma, riquadro, "
                "sicurezza, trovata_il) VALUES (?,?,0,?,0.9,?)",
                (parte_id, scatto_id, json.dumps([0, 0, 1, 1]), adesso()))
    imparate.Passata(archivio, sceglitore=SamFinto("sul_punto")).esegui()
    with archivio.lettura() as connessione:
        assert uno(connessione, "SELECT 1 FROM parti_imparate WHERE parte_id = ?", parte_id)
        assert not tutti(connessione, "SELECT 1 FROM parti_trovate WHERE come = 'imparata'")
        assert len(tutti(connessione, "SELECT 1 FROM parti_trovate WHERE come = 'parola'")) \
            == len(scatti)
    with archivio.scrittura() as connessione:
        for sagoma_id in fatte[:4]:
            sagome.segna_buona(connessione, sagoma_id, False)
    with archivio.lettura() as connessione:
        assert imparate.quanti_mancano(connessione) >= 1
    imparate.Passata(archivio, sceglitore=SamFinto("sul_punto")).esegui()
    with archivio.lettura() as connessione:
        assert uno(connessione, "SELECT 1 FROM parti_imparate WHERE parte_id = ?",
                   parte_id) is None
        assert not tutti(connessione, "SELECT 1 FROM parti_imparate_guardate")


def _pagina_con_una_parte_imparata(archivio):
    from fastapi.testclient import TestClient

    from officina.web.server import app

    parte_id, nodo_id, scatti, fatte = _parte_con_sagome(archivio, imparate.MINIMO_SAGOME)
    resoconto = {"soglia": 0.8, "sagome": len(fatte), "alla_prova": 4,
                 "gruppi": {"tutte": {"giuste": 3, "su": 4},
                            "difficili": {"giuste": 1, "su": 2},
                            "persa": {"giuste": 2, "su": 2}}}
    with archivio.scrittura() as connessione:
        connessione.execute(
            "INSERT INTO parti_imparate (parte_id, descrittore, versione, pesi, esempi, firma, "
            "misura, allenata_il) VALUES (?, 'disegnato', 'x', x'00', ?, 'f', ?, ?)",
            (parte_id, len(fatte), json.dumps(resoconto), adesso()))
        connessione.execute(
            f"UPDATE sagome SET parte_persa = ? WHERE id IN ({','.join('?' * 3)})",
            (parte_id, *fatte[:3]))
        altra = elenco.aggiungi(connessione, "Altro pezzo", "other")
    return TestClient(app, client=("127.0.0.1", 51000)), parte_id, altra, fatte


def test_la_pagina_delle_parti_mostra_il_voto_e_avvisa_se_la_parola_la_perde(
        archivio_misurabile):
    cliente, parte_id, altra, fatte = _pagina_con_una_parte_imparata(archivio_misurabile)
    pagina = cliente.get("/intelligenza/parti")
    assert pagina.status_code == 200
    testo = pagina.text
    assert "Imparate dalle tue sagome" in testo
    assert f"imparata da {len(fatte)} sagome" in testo
    assert "75%" in testo and "sui difficili" in testo and "50%" in testo
    assert "che la parola non trova" in testo
    assert "La parola «thing» non trova questa parte in 3 foto" in testo
    assert f'data-parte="{altra}"' in testo
    assert "scegli un nodo per poter disegnare le sagome" in testo


def test_la_carta_delle_parti_imparate_sta_bene_nel_browser(archivio_misurabile):
    sync_api = pytest.importorskip("playwright.sync_api")
    from prove.test_sagome_nel_browser import _apri

    cliente, parte_id, _, _ = _pagina_con_una_parte_imparata(archivio_misurabile)
    for larga, alta in ((1920, 1080), (1440, 900)):
        with sync_api.sync_playwright() as p:
            browser, scheda, errori = _apri(p, cliente, larga, alta)
            scheda.goto("http://prova/intelligenza/parti")
            carta = scheda.locator("#pdc-imparate")
            carta.wait_for()
            carta.scroll_into_view_if_needed()
            assert carta.is_visible()
            assert scheda.evaluate(
                "document.documentElement.scrollWidth <= document.documentElement.clientWidth")
            voti = scheda.locator(f'[data-parte="{parte_id}"] .pdc-voti li')
            assert voti.count() == 3
            alti = {round(voti.nth(i).bounding_box()["y"]) for i in range(3)}
            assert len(alti) == 1
            assert not errori
            browser.close()
