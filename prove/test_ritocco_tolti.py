from __future__ import annotations

import json

from officina.archivio.database import adesso, uno
from officina.corpi import chi_e
from officina.modello import persone
from officina.ritocco import coda, elenco, tolti
from prove.test_ritocco_togli_coda import (ALTA, COSA, LARGA, Togliere, _da_togliere, _file_id,
                                           _gira, cartella, importato)

assert cartella and importato


def _scatto(archivio, file_id: int) -> int:
    with archivio.lettura() as connessione:
        return uno(connessione, "SELECT scatto_id FROM file_media WHERE id = ?",
                   file_id)["scatto_id"]


def _una_persona_nella_cosa(archivio, file_id: int) -> tuple[int, int, int]:
    x0, y0, x1, y1 = COSA
    riquadro = [x0 / LARGA, y0 / ALTA, (x1 - x0) / LARGA, (y1 - y0) / ALTA]
    scatto_id = _scatto(archivio, file_id)
    with archivio.scrittura() as connessione:
        persona_id = persone.crea(connessione, "Mario Finto")
        volto_id = connessione.execute(
            "INSERT INTO volti (scatto_id, file_id, fotogramma, riquadro, area, nitidezza, "
            "sicurezza, modello, versione, persona_id, deciso_da, trovato_il) "
            "VALUES (?, ?, 0, ?, 0.1, 1, 0.9, 'volti', '1', ?, 'utente', ?)",
            (scatto_id, file_id, json.dumps(riquadro), persona_id, adesso())).lastrowid
        corpo_id = connessione.execute(
            "INSERT INTO corpi (scatto_id, file_id, fotogramma, riquadro, area, sicurezza, "
            "modello, versione, trovato_il) VALUES (?, ?, 0, ?, 0.2, 0.9, 'corpi', '1', ?)",
            (scatto_id, file_id, json.dumps(riquadro), adesso())).lastrowid
        connessione.execute(
            "INSERT INTO corpi_delle_persone (corpo_id, persona_id, risposta, deciso_il) "
            "VALUES (?, ?, 'si', ?)", (corpo_id, persona_id, adesso()))
        connessione.execute(
            "INSERT INTO persone_negli_scatti (scatto_id, persona_id, messa_il) VALUES (?, ?, ?)",
            (scatto_id, persona_id, adesso()))
    return persona_id, volto_id, corpo_id


def _com_e(archivio, persona_id: int, volto_id: int, corpo_id: int) -> tuple:
    with archivio.lettura() as connessione:
        volto = uno(connessione, "SELECT persona_id, deciso_da FROM volti WHERE id = ?", volto_id)
        corpo = uno(connessione, "SELECT risposta FROM corpi_delle_persone WHERE corpo_id = ?",
                    corpo_id)
        a_mano = uno(connessione, "SELECT 1 FROM persone_negli_scatti WHERE persona_id = ?",
                     persona_id)
    return (volto["persona_id"], volto["deciso_da"], corpo["risposta"] if corpo else None,
            a_mano is not None)


def _togli_la_persona(archivio, file_id: int) -> int:
    lavoro_id = coda.metti(archivio, [{"file_id": file_id, **_da_togliere(),
                                        "cosa": elenco.PERSONA}])
    _gira(archivio, Togliere())
    coda.approva(archivio, lavoro_id)
    with archivio.lettura() as connessione:
        return uno(connessione, "SELECT id FROM ritocchi WHERE lavoro_id = ?", lavoro_id)["id"]


def test_chi_togli_esce_dallo_scatto_e_torna_se_togli_il_ritocco(importato):
    file_id = _file_id(importato)
    persona_id, volto_id, corpo_id = _una_persona_nella_cosa(importato, file_id)
    assert _com_e(importato, persona_id, volto_id, corpo_id) == (persona_id, "utente", "si", True)

    ritocco_id = _togli_la_persona(importato, file_id)

    assert _com_e(importato, persona_id, volto_id, corpo_id) == (None, "utente", None, False)
    with importato.lettura() as connessione:
        assert tolti.e_tolto(connessione, "volto", volto_id)
        assert tolti.e_tolto(connessione, "corpo", corpo_id)
        assert corpo_id not in {riga["id"] for riga in chi_e.ignoti(connessione)}

    lavoro_id = coda.togli(importato, ritocco_id)
    if lavoro_id is not None:
        _gira(importato, Togliere())
        coda.approva(importato, lavoro_id)

    assert _com_e(importato, persona_id, volto_id, corpo_id) == (persona_id, "utente", "si", True)
    with importato.lettura() as connessione:
        assert not tolti.e_tolto(connessione, "volto", volto_id)


def test_togliere_un_oggetto_non_tocca_le_persone(importato):
    file_id = _file_id(importato)
    persona_id, volto_id, corpo_id = _una_persona_nella_cosa(importato, file_id)
    lavoro_id = coda.metti(importato, [{"file_id": file_id, **_da_togliere()}])
    _gira(importato, Togliere())
    coda.approva(importato, lavoro_id)
    assert _com_e(importato, persona_id, volto_id, corpo_id) == (persona_id, "utente", "si", True)


def test_allineare_due_volte_non_cambia_niente(importato):
    file_id = _file_id(importato)
    persona_id, volto_id, corpo_id = _una_persona_nella_cosa(importato, file_id)
    _togli_la_persona(importato, file_id)
    with importato.scrittura() as connessione:
        tolti.allinea(connessione, _scatto(importato, file_id))
        quante = uno(connessione, "SELECT count(*) AS q FROM persone_tolte")["q"]
        tolti.allinea(connessione, _scatto(importato, file_id))
        assert uno(connessione, "SELECT count(*) AS q FROM persone_tolte")["q"] == quante


def test_all_avvio_si_rimette_a_posto_chi_era_rimasto_a_meta(importato):
    file_id = _file_id(importato)
    persona_id, volto_id, corpo_id = _una_persona_nella_cosa(importato, file_id)
    ritocco_id = _togli_la_persona(importato, file_id)
    with importato.scrittura() as connessione:
        elenco.segna(connessione, ritocco_id, elenco.TOLTO, tolto_il=adesso())

    assert tolti.ripara(importato) == 1
    assert _com_e(importato, persona_id, volto_id, corpo_id) == (persona_id, "utente", "si", True)
