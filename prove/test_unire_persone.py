from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from officina.archivio.database import adesso, tutti
from officina.corpi import chi_e
from officina.errori import OperazioneNonPermessa
from officina.modello import persone


def _persona(c, nome: str) -> int:
    return c.execute("INSERT INTO persone (nome, nata_il) VALUES (?, ?)",
                     (nome, adesso())).lastrowid


def _corpo(c) -> int:
    scatto_id = c.execute(
        "INSERT INTO scatti (genere, data_locale, istante_utc, giorno, origine_data, creato_il) "
        "VALUES ('foto', '2024-05-01T10:00:00', '2024-05-01T10:00:00Z', '2024-05-01', 'exif', ?)",
        (adesso(),)).lastrowid
    return c.execute(
        "INSERT INTO corpi (scatto_id, fotogramma, riquadro, area, sicurezza, modello, versione, "
        "trovato_il) VALUES (?, 0, '[0.3,0.1,0.3,0.8]', 0.24, 0.9, 'corpi', '1', ?)",
        (scatto_id, adesso())).lastrowid


def _risposte(c, persona_id: int) -> dict[int, str]:
    return {riga["corpo_id"]: riga["risposta"] for riga in tutti(
        c, "SELECT corpo_id, risposta FROM corpi_delle_persone WHERE persona_id = ?", persona_id)}


@pytest.fixture
def due(archivio):
    with archivio.scrittura() as c:
        return _persona(c, "Persona A"), _persona(c, "Persona B")


def test_i_corpi_confermati_a_mano_passano_a_chi_resta(archivio, due):
    via, resta = due
    with archivio.scrittura() as c:
        confermato = _corpo(c)
        chi_e.rispondi(c, confermato, via, "si")
        persone.unisci(c, via, resta)
    with archivio.lettura() as c:
        assert _risposte(c, resta) == {confermato: "si"}
        assert _risposte(c, via) == {}
        assert {(r["id"], r["persona_id"]) for r in chi_e.noti(c)} == {(confermato, resta)}


def test_i_no_detti_a_mano_passano_a_chi_resta(archivio, due):
    via, resta = due
    with archivio.scrittura() as c:
        scartato = _corpo(c)
        chi_e.rispondi(c, scartato, via, "no")
        persone.unisci(c, via, resta)
    with archivio.lettura() as c:
        assert _risposte(c, resta) == {scartato: "no"}


def test_se_uno_aveva_detto_si_e_l_altro_no_vince_il_si(archivio, due):
    via, resta = due
    with archivio.scrittura() as c:
        primo, secondo = _corpo(c), _corpo(c)
        chi_e.rispondi(c, primo, via, "si")
        chi_e.rispondi(c, primo, resta, "no")
        chi_e.rispondi(c, secondo, via, "no")
        chi_e.rispondi(c, secondo, resta, "si")
        persone.unisci(c, via, resta)
    with archivio.lettura() as c:
        assert _risposte(c, resta) == {primo: "si", secondo: "si"}


def test_le_cartelle_di_riferimento_passano_a_chi_resta(archivio, due):
    via, resta = due
    with archivio.scrittura() as c:
        for persona_id, percorso in ((via, "/finta/a"), (via, "/finta/c"),
                                     (resta, "/finta/b"), (resta, "/finta/c")):
            c.execute("INSERT INTO cartelle_riferimento (persona_id, percorso, data_il) "
                      "VALUES (?, ?, ?)", (persona_id, percorso, adesso()))
        persone.unisci(c, via, resta)
    with archivio.lettura() as c:
        rimaste = [(r["persona_id"], r["percorso"]) for r in tutti(
            c, "SELECT persona_id, percorso FROM cartelle_riferimento ORDER BY percorso")]
    assert rimaste == [(resta, "/finta/a"), (resta, "/finta/b"), (resta, "/finta/c")]


def test_proposte_e_pesi_di_chi_se_ne_va_si_buttano(archivio, due):
    via, resta = due
    with archivio.scrittura() as c:
        corpo = _corpo(c)
        scatto = c.execute("SELECT scatto_id FROM corpi WHERE id = ?", (corpo,)).fetchone()[0]
        c.execute("INSERT INTO proposte_dei_corpi (corpo_id, persona_id, scatto_id, punteggio, "
                  "perche, calcolata_il) VALUES (?, ?, ?, 0.9, 'finto', ?)",
                  (corpo, via, scatto, adesso()))
        c.execute("INSERT INTO pesi_delle_persone (persona_id, pesi, vestiti_giorni, "
                  "corporatura_giorni, si, no, esempi, firma, imparati_il) "
                  "VALUES (?, '[]', 1, 1, 0, 0, 0, 'x', ?)", (via, adesso()))
        persone.unisci(c, via, resta)
    with archivio.lettura() as c:
        for tabella in ("proposte_dei_corpi", "pesi_delle_persone"):
            assert c.execute(f"SELECT count(*) FROM {tabella} WHERE persona_id = ?",
                             (via,)).fetchone()[0] == 0


def test_non_si_unisce_dentro_un_gruppo_gia_unito_a_un_altro(archivio, due):
    via, resta = due
    with archivio.scrittura() as c:
        terza = _persona(c, "Persona C")
        persone.unisci(c, via, resta)
    with pytest.raises(OperazioneNonPermessa):
        with archivio.scrittura() as c:
            persone.unisci(c, terza, via)
    with archivio.lettura() as c:
        assert persone.per_id(c, terza)["stato"] == "attiva"


def test_un_gruppo_gia_unito_non_si_riprende(archivio, due):
    from officina.web.server import app

    via, resta = due
    with archivio.scrittura() as c:
        persone.unisci(c, via, resta)
    cliente = TestClient(app, client=("127.0.0.1", 51000))
    assert cliente.post(f"/api/persone/{via}/riprendi").status_code == 200
    with archivio.lettura() as c:
        assert persone.per_id(c, via)["stato"] == "congelata"
