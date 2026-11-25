from __future__ import annotations

import numpy
import pytest
from PIL import Image

from officina.apprendimento import pezzi, proposte
from officina.archivio.database import tutti, uno
from officina.descrittori import scheda
from officina.modello import etichette, sagome
from officina.ritocco import maschere


def _maschera(larga, alta, x0, y0, x1, y1) -> bytes:
    piena = numpy.zeros((alta, larga), dtype=bool)
    piena[y0:y1, x0:x1] = True
    return maschere.comprimi(piena, (0, 0), larga, alta)


def test_il_ritaglio_spegne_lo_sfondo_fuori_dalla_sagoma():
    tela = numpy.zeros((100, 200, 3), dtype=numpy.uint8)
    tela[:, :] = (255, 0, 0)
    tela[40:60, 90:110] = (0, 255, 0)
    immagine = Image.fromarray(tela, "RGB")
    ritaglio = pezzi.ritaglia(immagine, _maschera(100, 50, 45, 20, 55, 30), 64)
    assert ritaglio.size == (64, 64)
    pixel = numpy.asarray(ritaglio)
    assert tuple(pixel[32, 32]) == (0, 255, 0)
    rossi = numpy.all(pixel == (255, 0, 0), axis=-1).sum()
    assert rossi < 64 * 64 * 0.25
    assert pezzi.ritaglia(immagine, b"", 64) is None


def _nodo_con_tanti_si(connessione) -> tuple[int, list[int]]:
    riga = uno(connessione,
               "SELECT e.nodo_id, count(*) AS q FROM etichette e JOIN nodi n ON n.id = e.nodo_id "
               "AND n.stato = 'attivo' WHERE e.stato = 'si' AND e.origine = 'utente' "
               "GROUP BY e.nodo_id ORDER BY q DESC, e.nodo_id LIMIT 1")
    scatti = [r["scatto_id"] for r in tutti(
        connessione, "SELECT e.scatto_id FROM etichette e JOIN file_media f "
        "ON f.scatto_id = e.scatto_id AND f.genere = 'immagine' "
        "WHERE e.nodo_id = ? AND e.stato = 'si' GROUP BY e.scatto_id ORDER BY e.scatto_id",
        riga["nodo_id"])]
    return riga["nodo_id"], scatti


def _metti_sagome(archivio, nodo_id, scatti) -> list[int]:
    fatte = []
    with archivio.scrittura() as connessione:
        for scatto_id in scatti:
            file_id = uno(connessione, "SELECT id FROM file_media WHERE scatto_id = ? "
                          "AND genere = 'immagine' ORDER BY id LIMIT 1", scatto_id)["id"]
            fatte.append(sagome.salva(
                connessione, scatto_id=scatto_id, file_id=file_id, nodo_id=nodo_id,
                maschera=_maschera(40, 30, 10, 8, 30, 24), come=sagome.MANO))
    return fatte


def test_i_pezzi_si_calcolano_solo_dove_l_etichetta_c_e(archivio_misurabile):
    archivio = archivio_misurabile
    carta = scheda("disegnato")
    with archivio.lettura() as connessione:
        nodo_id, scatti = _nodo_con_tanti_si(connessione)
    assert len(scatti) >= proposte.MINIMO_ESEMPI + 1
    fatte = _metti_sagome(archivio, nodo_id, scatti[:proposte.MINIMO_ESEMPI + 1])
    with archivio.scrittura() as connessione:
        etichette.togli(connessione, scatti[0], nodo_id)
        sagome.segna_buona(connessione, fatte[1], False)
        da = {r["id"] for r in pezzi.da_fare(connessione, carta.nome, carta.versione)}
    assert da == set(fatte[2:])
    fatti = pezzi.Pezzi(archivio, "disegnato").esegui()
    assert fatti == len(fatte) - 2
    with archivio.lettura() as connessione:
        assert pezzi.quanti_da_fare(connessione, carta.nome, carta.versione) == 0
        righe = tutti(connessione, "SELECT sagoma_id, valori FROM impronte_sagome")
        assert {r["sagoma_id"] for r in righe} == set(fatte[2:])
        assert all(len(r["valori"]) > 0 for r in righe)
    assert pezzi.Pezzi(archivio, "disegnato").esegui() == 0


def test_nei_video_si_prende_un_fotogramma_ogni_tanto_e_solo_se_sicuro(archivio_misurabile):
    archivio = archivio_misurabile
    with archivio.lettura() as connessione:
        nodo_id, scatti = _nodo_con_tanti_si(connessione)
    [prima] = _metti_sagome(archivio, nodo_id, scatti[:1])
    with archivio.scrittura() as connessione:
        riga = sagome.per_id(connessione, prima)
        connessione.execute("UPDATE sagome SET fotogramma = 3 WHERE id = ?", (prima,))
        tenute = []
        for numero, sicurezza in ((5, 0.9), (6, 0.9), (10, 0.3), (15, 0.8)):
            nuova = sagome.salva(connessione, scatto_id=riga["scatto_id"],
                                 file_id=riga["file_id"], nodo_id=nodo_id,
                                 maschera=riga["maschera"], come=sagome.SEGUITA,
                                 fotogramma=numero, sicurezza=sicurezza, origine_id=prima,
                                 da_controllare=sicurezza < 0.5)
            if numero in (5, 15):
                tenute.append(nuova)
        da = {r["id"] for r in pezzi.da_fare(connessione, "disegnato", "x")}
    assert da == {prima, *tenute}


def test_le_proposte_imparano_anche_dai_pezzi(archivio_misurabile):
    archivio = archivio_misurabile
    with archivio.lettura() as connessione:
        nodo_id, scatti = _nodo_con_tanti_si(connessione)
    bottega = proposte.Bottega("disegnato")
    with archivio.lettura() as connessione:
        bottega.riaddestra(connessione)
        assert bottega.pezzi_di.get(nodo_id) == ()
        assert not bottega.scaduta(connessione)
    fatte = _metti_sagome(archivio, nodo_id, scatti[:proposte.MINIMO_ESEMPI])
    with archivio.lettura() as connessione:
        assert bottega.scaduta(connessione)
    pezzi.Pezzi(archivio, "disegnato").esegui()
    with archivio.lettura() as connessione:
        assert bottega.scaduta(connessione)
        bottega.assicura(connessione)
        assert set(bottega.pezzi_di[nodo_id]) == set(fatte)
        assert nodo_id in bottega.modelli
        assert not bottega.scaduta(connessione)
    with archivio.scrittura() as connessione:
        sagome.segna_buona(connessione, fatte[0], False)
    with archivio.lettura() as connessione:
        bottega.assicura(connessione)
        assert bottega.pezzi_di[nodo_id] == ()


def test_pochi_pezzi_non_cambiano_il_modello(archivio_misurabile, monkeypatch):
    archivio = archivio_misurabile
    with archivio.lettura() as connessione:
        nodo_id, scatti = _nodo_con_tanti_si(connessione)
    _metti_sagome(archivio, nodo_id, scatti[:proposte.MINIMO_ESEMPI - 1])
    pezzi.Pezzi(archivio, "disegnato").esegui()
    chiamate = []
    vero = proposte._addestra_uno

    def conta(*argomenti):
        chiamate.append(len(argomenti))
        return vero(*argomenti)

    monkeypatch.setattr(proposte, "_addestra_uno", conta)
    with archivio.lettura() as connessione:
        proposte.Bottega("disegnato").riaddestra(connessione)
    assert chiamate and set(chiamate) == {4}


@pytest.mark.parametrize("quanti", [1])
def test_la_coda_delle_impronte_fa_anche_i_pezzi(archivio_misurabile, quanti):
    from officina.impronte.motore import Coda

    archivio = archivio_misurabile
    with archivio.lettura() as connessione:
        nodo_id, scatti = _nodo_con_tanti_si(connessione)
    _metti_sagome(archivio, nodo_id, scatti[:quanti])
    Coda(archivio, ["disegnato"]).esegui()
    with archivio.lettura() as connessione:
        assert uno(connessione, "SELECT count(*) AS q FROM impronte_sagome")["q"] == quanti


def test_i_pezzi_degli_altri_nodi_insegnano_cosa_non_e(archivio_misurabile, monkeypatch):
    archivio = archivio_misurabile
    with archivio.lettura() as connessione:
        nodo_id, scatti = _nodo_con_tanti_si(connessione)
        altro = uno(connessione,
                    "SELECT id FROM nodi WHERE stato = 'attivo' AND id != ? AND id NOT IN "
                    "(SELECT genitore_id FROM nodi WHERE id = ? AND genitore_id IS NOT NULL) "
                    "AND (genitore_id IS NULL OR genitore_id != ?) ORDER BY id LIMIT 1",
                    nodo_id, nodo_id, nodo_id)["id"]
        fuori = [r["id"] for r in tutti(
            connessione, "SELECT s.id FROM scatti s JOIN file_media f ON f.scatto_id = s.id "
            "AND f.genere = 'immagine' WHERE s.id NOT IN (SELECT scatto_id FROM etichette "
            "WHERE nodo_id = ? AND stato = 'si') GROUP BY s.id ORDER BY s.id LIMIT 3", nodo_id)]
    miei = _metti_sagome(archivio, nodo_id, scatti[:proposte.MINIMO_ESEMPI])
    with archivio.scrittura() as connessione:
        for scatto_id in fuori:
            etichette.metti(connessione, scatto_id, altro)
    loro = _metti_sagome(archivio, altro, fuori)
    pezzi.Pezzi(archivio, "disegnato").esegui()
    viste = []
    vero = proposte._addestra_uno

    def spia(connessione, gli_esempi, descrittore, versione, positivi=None, negativi=None):
        if gli_esempi.nodo_id == nodo_id:
            viste.append((len(positivi or []), len(negativi or [])))
        return vero(connessione, gli_esempi, descrittore, versione, positivi, negativi)

    monkeypatch.setattr(proposte, "_addestra_uno", spia)
    bottega = proposte.Bottega("disegnato")
    with archivio.lettura() as connessione:
        bottega.riaddestra(connessione)
    assert viste == [(len(miei), len(loro))]
    assert nodo_id in bottega.modelli


def test_la_carta_delle_impronte_dice_le_sagome_da_imparare(archivio_misurabile, monkeypatch):
    from officina.web.strade import intelligenza

    archivio = archivio_misurabile
    with archivio.lettura() as connessione:
        nodo_id, scatti = _nodo_con_tanti_si(connessione)
    _metti_sagome(archivio, nodo_id, scatti[:2])
    monkeypatch.setattr("officina.descrittori.pronti", lambda *_: ["disegnato"])
    monkeypatch.setattr(proposte, "scegli_descrittore", lambda *_a, **_k: ("disegnato", "x"))
    assert intelligenza._pezzi_che_mancano(archivio) == 2
    pezzi.Pezzi(archivio, "disegnato").esegui()
    assert intelligenza._pezzi_che_mancano(archivio) == 0
