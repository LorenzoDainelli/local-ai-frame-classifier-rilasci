from __future__ import annotations

import pytest

from officina.apprendimento import esempi as esempi_mod, proposte
from officina.archivio.database import adesso, esegui, inserisci
from officina.modello import luoghi

CASA = (43.7731, 11.2560)
CASA_DI_FIANCO = (43.7732, 11.2562)
IN_FONDO_ALLA_VIA = (43.7745, 11.2570)
PISA = (43.7228, 10.3966)


def _scatto(connessione, luogo=None, giorno="2024-05-01") -> int:
    lat, lon = luogo if luogo else (None, None)
    return inserisci(
        connessione,
        "INSERT INTO scatti (genere, giorno, origine_data, latitudine, "
        "longitudine, creato_il) VALUES ('foto', ?, 'exif', ?, ?, ?)",
        giorno, lat, lon, adesso())


def test_gli_scatti_vicini_finiscono_nello_stesso_luogo(connessione):
    uno = _scatto(connessione, CASA)
    due = _scatto(connessione, CASA_DI_FIANCO)
    tre = _scatto(connessione, IN_FONDO_ALLA_VIA)
    lontano = _scatto(connessione, PISA)

    esito = luoghi.raggruppa(connessione)

    assert esito["sistemati"] == 4
    assert esito["nuovi"] == 2
    quale = {riga["id"]: riga["luogo_id"] for riga in connessione.execute(
        "SELECT id, luogo_id FROM scatti")}
    assert quale[uno] == quale[due] == quale[tre]
    assert quale[lontano] != quale[uno]


def test_uno_scatto_senza_coordinate_non_sta_in_nessun_luogo(connessione):
    _scatto(connessione, CASA)
    muto = _scatto(connessione, None)

    esito = luoghi.raggruppa(connessione)

    assert esito["senza_coordinate"] == 1
    riga = connessione.execute("SELECT luogo_id FROM scatti WHERE id = ?",
                               (muto,)).fetchone()
    assert riga["luogo_id"] is None


def test_rifare_i_gruppi_non_perde_il_nome_che_hai_scritto(connessione):
    _scatto(connessione, CASA)
    luoghi.raggruppa(connessione)
    quale = connessione.execute("SELECT id FROM luoghi").fetchone()["id"]
    luoghi.chiama(connessione, quale, "Casa")

    _scatto(connessione, CASA_DI_FIANCO)
    luoghi.raggruppa(connessione)

    righe = connessione.execute("SELECT id, nome FROM luoghi").fetchall()
    assert len(righe) == 1
    assert righe[0]["nome"] == "Casa"


def test_il_nome_arriva_da_solo_alle_foto_di_domani(connessione):
    _scatto(connessione, CASA)
    luoghi.raggruppa(connessione)
    quale = connessione.execute("SELECT id FROM luoghi").fetchone()["id"]
    luoghi.chiama(connessione, quale, "Casa")

    domani = _scatto(connessione, CASA_DI_FIANCO, giorno="2025-01-01")
    luoghi.raggruppa(connessione)

    riga = luoghi.del_scatto(connessione, domani)
    assert riga is not None and riga["nome"] == "Casa"


def test_il_centro_e_la_media_non_il_primo_arrivato(connessione):
    _scatto(connessione, CASA)
    _scatto(connessione, IN_FONDO_ALLA_VIA)
    luoghi.raggruppa(connessione)

    riga = connessione.execute("SELECT * FROM luoghi").fetchone()
    assert riga["centro_lat"] == pytest.approx(
        (CASA[0] + IN_FONDO_ALLA_VIA[0]) / 2)
    assert riga["quanti"] == 2
    assert riga["raggio_metri"] > 0


def test_due_luoghi_si_uniscono_a_mano(connessione):
    _scatto(connessione, CASA)
    _scatto(connessione, PISA)
    luoghi.raggruppa(connessione)
    elenco = luoghi.elenco(connessione)
    primo, secondo = elenco[0]["id"], elenco[1]["id"]

    spostati = luoghi.unisci(connessione, primo, secondo)

    assert spostati == 1
    assert len(luoghi.elenco(connessione)) == 1


def _bottega_finta(si_qui: int, decisi_qui: int, base_si: int, base_quanti: int):
    gli_esempi = esempi_mod.Esempi(nodo_id=1, si=list(range(base_si)),
                                   no=list(range(base_si, base_quanti)))
    proposta = proposte.Proposta(nodo_id=1, nome="cucina", percorso="",
                                 punteggio=0.5, soglia=0.5,
                                 esempi=gli_esempi.quanti)
    proposte._aggiungi_il_luogo(proposta, gli_esempi, {7: (si_qui, decisi_qui)},
                                7, "Casa")
    return proposta


def test_il_luogo_tira_dentro_quando_le_foto_di_li_stanno_quasi_tutte_qui():
    proposta = _bottega_finta(si_qui=9, decisi_qui=10, base_si=10, base_quanti=40)
    assert proposta.spinta > 0
    assert proposta.punteggio > 0.5


def test_il_luogo_tira_fuori_quando_nessuna_foto_di_li_sta_qui():
    proposta = _bottega_finta(si_qui=0, decisi_qui=12, base_si=20, base_quanti=40)
    assert proposta.spinta < 0
    assert proposta.punteggio < 0.5


def test_con_pochi_esempi_nel_luogo_il_dove_non_dice_niente():
    proposta = _bottega_finta(si_qui=2, decisi_qui=2, base_si=10, base_quanti=40)
    assert proposta.spinta == 0
    assert proposta.punteggio == 0.5
    assert proposta.esempi_nel_luogo == 2


def test_la_spinta_e_limitata_e_non_puo_ribaltare_una_certezza():
    gli_esempi = esempi_mod.Esempi(nodo_id=1, si=list(range(50)),
                                   no=list(range(50, 100)))
    proposta = proposte.Proposta(nodo_id=1, nome="cucina", percorso="",
                                 punteggio=0.02, soglia=0.5, esempi=100)
    proposte._aggiungi_il_luogo(proposta, gli_esempi, {7: (100, 100)}, 7, "Casa")
    assert proposta.punteggio < 0.5
    assert not proposta.ci_crede


def test_il_perche_del_luogo_e_un_fatto_contabile():
    proposta = _bottega_finta(si_qui=9, decisi_qui=10, base_si=10, base_quanti=40)
    frase = proposta.perche_il_luogo
    assert "10" in frase and "9" in frase and "Casa" in frase
    assert "%" not in frase


def test_senza_luogo_il_perche_tace():
    proposta = proposte.Proposta(nodo_id=1, nome="cucina", percorso="",
                                 punteggio=0.5, soglia=0.5, esempi=40)
    assert proposta.perche_il_luogo == ""
    assert proposta.spinta == 0


def test_linterruttore_spento_scade_la_bottega(connessione):
    bottega = proposte.Bottega()
    bottega.riaddestra(connessione)
    assert bottega.il_luogo_aiuta is True
    assert not bottega.scaduta(connessione)

    esegui(connessione,
           "INSERT OR REPLACE INTO impostazioni (chiave, valore) "
           "VALUES ('luogo_aiuta', 'false')")

    assert bottega.scaduta(connessione)
