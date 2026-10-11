from __future__ import annotations

import json

import numpy as np
import pytest
from fastapi.testclient import TestClient

from officina.archivio.database import adesso
from officina.corpi import VESTITI, chi_e, nome_dell_aspetto, vestiti_a_parole
from officina.corpi.figure import ASPETTO, NUMERI
from officina.corpi.kpr import VERSIONI
from officina.modello import corpi as corpi_mod

LATO = 16
GIORNI = [f"2024-05-{giorno:02d}" for giorno in range(1, 9)]


class Mondo:

    def __init__(self, archivio, seme: int = 3):
        self.archivio = archivio
        self.caso = np.random.default_rng(seme)
        self.chi: dict[str, dict] = {}

    def persona(self, nome: str) -> int:
        with self.archivio.scrittura() as c:
            persona_id = c.execute("INSERT INTO persone (nome, nata_il) VALUES (?, ?)",
                                   (nome, adesso())).lastrowid
        self.chi[nome] = {"id": persona_id, "kpr": self.caso.normal(size=(6, LATO)),
                          "forma": self.caso.normal(size=73), "vestiti": {}}
        return persona_id

    def vestiti_di(self, nome: str, giorno: str):
        return self.chi[nome]["vestiti"].setdefault(giorno, self.caso.normal(size=LATO))

    def scatto(self, quando: str) -> int:
        with self.archivio.scrittura() as c:
            return c.execute(
                "INSERT INTO scatti (genere, data_locale, istante_utc, giorno, origine_data, "
                "creato_il) VALUES ('foto', ?, ?, ?, 'exif', ?)",
                (quando, quando + "Z", quando[:10], adesso())).lastrowid

    def corpo(self, scatto_id: int, come: str, giorno: str, col_volto: bool,
              vestiti=None, rumore: float = 0.08) -> int:
        tipo = self.chi[come]
        with self.archivio.scrittura() as c:
            volto_id = None
            if col_volto:
                volto_id = c.execute(
                    "INSERT INTO volti (scatto_id, fotogramma, riquadro, area, nitidezza, "
                    "sicurezza, modello, versione, persona_id, trovato_il) "
                    "VALUES (?, 0, '[0.4,0.1,0.1,0.1]', 0.01, 1, 0.9, 'volti', '1', ?, ?)",
                    (scatto_id, tipo["id"], adesso())).lastrowid
            corpo_id = c.execute(
                "INSERT INTO corpi (scatto_id, fotogramma, riquadro, area, sicurezza, volto_id, "
                "modello, versione, trovato_il) VALUES (?, 0, '[0.3,0.1,0.3,0.8]', 0.24, 0.9, ?, "
                "'corpi', '1', ?)", (scatto_id, volto_id, adesso())).lastrowid
            for versione in VERSIONI:
                parti = tipo["kpr"] + self.caso.normal(scale=rumore, size=(6, LATO))
                c.execute("INSERT INTO aspetti (corpo_id, modello, parti, vettore, visibili) "
                          "VALUES (?, ?, 6, ?, ?)",
                          (corpo_id, nome_dell_aspetto(versione), corpi_mod.vettore_a_byte(parti),
                           bytes([1] * 6)))
            panni = self.vestiti_di(come, giorno) if vestiti is None else vestiti
            c.execute("INSERT INTO aspetti (corpo_id, modello, parti, vettore, visibili) "
                      "VALUES (?, ?, 1, ?, NULL)",
                      (corpo_id, VESTITI, corpi_mod.vettore_a_byte(
                          panni + self.caso.normal(scale=rumore, size=LATO))))
            figura = np.zeros(NUMERI, dtype=np.float32)
            figura[:73] = tipo["forma"] + self.caso.normal(scale=rumore, size=73)
            c.execute("INSERT INTO aspetti (corpo_id, modello, parti, vettore, visibili) "
                      "VALUES (?, ?, 1, ?, x'')", (corpo_id, ASPETTO, corpi_mod.vettore_a_byte(figura)))
        return corpo_id


@pytest.fixture
def mondo(archivio):
    mondo = Mondo(archivio)
    for nome in ("Giulia", "Marco", "Luca"):
        mondo.persona(nome)
    for numero, giorno in enumerate(GIORNI):
        for nome in ("Giulia", "Marco", "Luca"):
            for minuto in (15, 45):
                scatto_id = mondo.scatto(f"{giorno}T{10 + numero}:{minuto:02d}:00")
                mondo.corpo(scatto_id, nome, giorno, col_volto=True)
    return mondo


def _proposte(archivio, corpo_id: int) -> list[tuple[int, float, str]]:
    with archivio.lettura() as c:
        return [(r[0], r[1], r[2]) for r in c.execute(
            "SELECT persona_id, punteggio, perche FROM proposte_dei_corpi WHERE corpo_id = ? "
            "ORDER BY punteggio DESC", (corpo_id,))]


def test_di_spalle_con_gli_stessi_vestiti_propone_la_persona_giusta(mondo):
    scatto_id = mondo.scatto("2024-05-03T15:40:00")
    corpo_id = mondo.corpo(scatto_id, "Giulia", "2024-05-03", col_volto=False)
    chi_e.Passata(mondo.archivio).esegui()
    proposte = _proposte(mondo.archivio, corpo_id)
    assert proposte and proposte[0][0] == mondo.chi["Giulia"]["id"]
    assert proposte[0][1] >= chi_e.SOGLIA
    assert "stessi vestiti" in proposte[0][2]
    assert "della foto delle 12:" in proposte[0][2]


def test_un_altro_giorno_senza_vestiti_uguali_riconosce_dalla_corporatura(mondo):
    scatto_id = mondo.scatto("2024-06-10T09:00:00")
    corpo_id = mondo.corpo(scatto_id, "Marco", "2024-06-10", col_volto=False)
    chi_e.Passata(mondo.archivio).esegui()
    proposte = _proposte(mondo.archivio, corpo_id)
    assert proposte[0][0] == mondo.chi["Marco"]["id"]
    assert "stessi vestiti" not in proposte[0][2]
    assert "della foto del" in proposte[0][2]


def test_chi_c_e_gia_col_volto_non_viene_riproposto_nello_stesso_scatto(mondo):
    scatto_id = mondo.scatto("2024-05-02T18:00:00")
    mondo.corpo(scatto_id, "Giulia", "2024-05-02", col_volto=True)
    corpo_id = mondo.corpo(scatto_id, "Giulia", "2024-05-02", col_volto=False)
    chi_e.Passata(mondo.archivio).esegui()
    assert mondo.chi["Giulia"]["id"] not in [p for p, _, _ in _proposte(mondo.archivio, corpo_id)]


def test_il_no_toglie_subito_la_proposta_e_non_torna(mondo):
    scatto_id = mondo.scatto("2024-05-04T20:00:00")
    corpo_id = mondo.corpo(scatto_id, "Luca", "2024-05-04", col_volto=False)
    chi_e.Passata(mondo.archivio).esegui()
    luca = mondo.chi["Luca"]["id"]
    assert _proposte(mondo.archivio, corpo_id)[0][0] == luca
    with mondo.archivio.scrittura() as c:
        assert chi_e.rispondi(c, corpo_id, luca, "no") == scatto_id
    assert luca not in [p for p, _, _ in _proposte(mondo.archivio, corpo_id)]
    chi_e.Passata(mondo.archivio).esegui()
    assert luca not in [p for p, _, _ in _proposte(mondo.archivio, corpo_id)]


def test_il_si_mette_la_persona_nello_scatto_e_insegna(mondo):
    scatto_id = mondo.scatto("2024-05-05T11:00:00")
    corpo_id = mondo.corpo(scatto_id, "Giulia", "2024-05-05", col_volto=False)
    altro = mondo.corpo(mondo.scatto("2024-05-05T11:30:00"), "Giulia", "2024-05-05",
                        col_volto=False)
    prima = chi_e.Passata(mondo.archivio)
    prima.esegui()
    giulia = mondo.chi["Giulia"]["id"]
    with mondo.archivio.scrittura() as c:
        chi_e.rispondi(c, corpo_id, giulia, "si")
    with mondo.archivio.lettura() as c:
        assert c.execute("SELECT 1 FROM persone_negli_scatti WHERE scatto_id = ? "
                         "AND persona_id = ?", (scatto_id, giulia)).fetchone()
        assert corpo_id in [r["id"] for r in chi_e.noti(c)]
    assert _proposte(mondo.archivio, corpo_id) == []
    dopo = chi_e.Passata(mondo.archivio)
    dopo.esegui()
    assert dopo.avanzamento.rifatte == 1
    assert _proposte(mondo.archivio, altro)[0][0] == giulia


def test_ogni_persona_impara_i_suoi_pesi(mondo):
    chi_e.Passata(mondo.archivio).esegui()
    with mondo.archivio.lettura() as c:
        righe = {r["persona_id"]: r for r in c.execute("SELECT * FROM pesi_delle_persone")}
    assert set(righe) == {mondo.chi[n]["id"] for n in ("Giulia", "Marco", "Luca")}
    for riga in righe.values():
        assert set(json.loads(riga["pesi"])) == set(chi_e.PESI_DI_BASE)
        assert riga["vestiti_giorni"] in chi_e.GIORNI_DA_PROVARE_VESTITI
        assert riga["esempi"] >= 8


def test_senza_cambiamenti_la_seconda_passata_non_rifa_niente(mondo):
    chi_e.Passata(mondo.archivio).esegui()
    seconda = chi_e.Passata(mondo.archivio)
    seconda.esegui()
    assert seconda.avanzamento.rifatte == 0


def test_imparare_trova_la_direzione_giusta():
    caso = np.random.default_rng(1)
    indizi = caso.uniform(size=(200, len(chi_e.INDIZI)))
    etichette = (indizi[:, 3] > 0.5).astype(float)
    w, _ = chi_e.impara_i_pesi(indizi, etichette, np.ones(200), np.zeros(len(chi_e.INDIZI) + 1), 0.01)
    assert w[3] > 5 and abs(w[0]) < w[3] / 3


def test_con_pochi_esempi_la_persona_usa_i_pesi_di_tutti():
    vuoto = chi_e.Esempio(1, {nome: np.zeros(2) for nome in chi_e.VETTORI}, np.zeros(2), 0.0, 1.0, 1.0)
    assert chi_e.impara_la_persona([vuoto] * 3, chi_e.Pesi()) is None


def test_la_data_a_parole():
    assert chi_e._quando_a_parole("2024-05-03T15:32:00", True) == "della foto delle 15:32"
    assert chi_e._quando_a_parole("2024-05-03T15:32:00", False) == "della foto del 3 maggio 2024"
    assert chi_e._quando_a_parole(None, False) == "di un'altra foto"


def test_i_vestiti_si_chiamano_col_capo_e_il_colore():
    chiavi = ["sopra|felpa gialla", "sopra|maglietta nera", "sotto|jeans blu", "sotto|gonna rossa"]
    matrice = np.eye(4, dtype=np.float32)
    vettore = np.array([0.9, 0.1, 0.8, 0.1], dtype=np.float32)
    assert vestiti_a_parole.nomina(vettore, chiavi, matrice) == "Felpa gialla, jeans blu"
    assert vestiti_a_parole.nomina(vettore, [], matrice[:0]) is None


def test_le_frasi_dei_vestiti_accordano_il_colore():
    chiavi = [chiave for chiave, _ in vestiti_a_parole.frasi()]
    assert "sopra|felpa gialla" in chiavi
    assert "sopra|maglione giallo" in chiavi
    assert "sotto|pantaloncini rossi" in chiavi
    assert len(chiavi) == len(set(chiavi))


def test_le_parole_dei_vestiti_si_preparano_una_volta(archivio):
    class Finto:
        volte = 0

        def descrivi_parole(self, frasi):
            Finto.volte += 1
            return [[1.0, 0.0] for _ in frasi]

    assert vestiti_a_parole.prepara(archivio, Finto()) == len(vestiti_a_parole.frasi())
    assert vestiti_a_parole.prepara(archivio, Finto()) == 0
    assert Finto.volte == 1


@pytest.fixture
def cliente(mondo):
    from officina.web.server import app

    return TestClient(app, client=("127.0.0.1", 51000))


def test_etichetta_mostra_la_proposta_dal_corpo_e_risponde(cliente, mondo, monkeypatch):
    from officina.web import etichettatura
    from officina.web.strade import etichetta

    monkeypatch.setattr(etichetta, "_rifai_chi_e_con_calma", lambda: None)
    scatto_id = mondo.scatto("2024-05-06T16:00:00")
    corpo_id = mondo.corpo(scatto_id, "Marco", "2024-05-06", col_volto=False)
    chi_e.Passata(mondo.archivio).esegui()
    marco = mondo.chi["Marco"]["id"]
    with mondo.archivio.lettura() as c:
        chi = etichettatura.chi_c_e(c, scatto_id)
    proposta = next(voce for voce in chi if voce["persona_id"] == marco)
    assert proposta["corpo"]["id"] == corpo_id and not proposta["confermata"]
    assert proposta["corpo"]["riquadro"] == [0.3, 0.1, 0.3, 0.8]
    assert proposta["corpo"]["simile"]

    risposta = cliente.post("/api/corpo-risposta",
                            data={"corpo_id": corpo_id, "persona_id": marco, "risposta": "si"})
    assert risposta.status_code == 200
    assert any(v["persona_id"] == marco and v["confermata"] for v in risposta.json()["persone"])
    assert risposta.json()["tre"]["persone"]

    tolta = cliente.post("/api/persona-conferma",
                         data={"scatto_id": scatto_id, "persona_id": marco, "stato": "togli"})
    assert tolta.status_code == 200
    with mondo.archivio.lettura() as c:
        assert not c.execute("SELECT 1 FROM corpi_delle_persone WHERE corpo_id = ? "
                             "AND risposta = 'si'", (corpo_id,)).fetchone()


def test_una_risposta_strana_si_rifiuta(cliente):
    risposta = cliente.post("/api/corpo-risposta",
                            data={"corpo_id": 1, "persona_id": 1, "risposta": "forse"})
    assert risposta.status_code == 400
