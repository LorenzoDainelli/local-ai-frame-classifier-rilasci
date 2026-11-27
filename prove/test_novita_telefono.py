from __future__ import annotations

import pytest

from prove.conftest import tutto_pronto_per_il_telefono

from officina.archivio.database import adesso
from officina.modello import telefoni
from officina.telefono import cavo, costruzione, orologio
from officina.web import telefono as pagina

PAROLA = "tre parole che ricordi"


@pytest.fixture
def telefono(archivio_pieno, tmp_path):
    tutto_pronto_per_il_telefono(archivio_pieno)
    with archivio_pieno.scrittura() as connessione:
        numero = telefoni.crea(connessione, "iPhone", "ios")
        telefoni.ricorda_cartella(connessione, numero, str(tmp_path / "Visore-iPhone"))
    return numero


def _copia(archivio, telefono, tmp_path):
    travaso = costruzione.Travaso(archivio, telefono, tmp_path / "Visore-iPhone", PAROLA)
    esito = travaso.esegui()
    assert esito.completo
    assert travaso.ricorda_sul_telefono(esito)
    return travaso


def _uno_scatto(archivio, telefono):
    with archivio.lettura() as connessione:
        return min(s for s in telefoni.quello_che_ha(connessione, telefono) if s > 0)


def test_prima_della_prima_copia_non_so_cosa_ha(archivio_pieno, telefono):
    detto = pagina.novita(archivio_pieno, telefono)

    assert not detto["conosciuto"]
    assert not detto["aggiornato"]
    assert "non l'ho ancora visto finire una copia" in detto["a_parole"]


def test_dopo_la_copia_e_gia_aggiornato(archivio_pieno, telefono, tmp_path):
    _copia(archivio_pieno, telefono, tmp_path)

    detto = pagina.novita(archivio_pieno, telefono)

    assert detto["aggiornato"]
    assert (detto["nuove"], detto["migliorate"], detto["cambiate"], detto["tolte"]) == (
        0, 0, 0, 0)
    assert detto["a_parole"] == ("L'iPhone è già aggiornato: dall'ultima copia non è "
                                 "cambiato niente.")


def test_una_etichetta_cambiata_si_conta(archivio_pieno, telefono, tmp_path):
    _copia(archivio_pieno, telefono, tmp_path)
    scatto = max(s for s in _tutti(archivio_pieno, telefono) if s > 0)
    with archivio_pieno.scrittura() as connessione:
        connessione.execute(
            "INSERT INTO nodi (nome, creato_il) VALUES ('ramo_nuovo', ?)", (adesso(),))
        nodo = connessione.execute("SELECT last_insert_rowid()").fetchone()[0]
        connessione.execute(
            "INSERT INTO etichette (scatto_id, nodo_id, stato, origine, creata_il) "
            "VALUES (?, ?, 'si', 'utente', ?)", (scatto, nodo, adesso()))

    detto = pagina.novita(archivio_pieno, telefono)

    assert not detto["aggiornato"]
    assert detto["cambiate"] == 1
    assert detto["nuove"] == 0
    assert "1 scatto con etichette, persone, data o luogo cambiati" in detto["a_parole"]


def test_una_data_cambiata_si_conta(archivio_pieno, telefono, tmp_path):
    _copia(archivio_pieno, telefono, tmp_path)
    scatto = _uno_scatto(archivio_pieno, telefono)
    with archivio_pieno.scrittura() as connessione:
        connessione.execute("UPDATE scatti SET data_locale = '2001-02-03T04:05:06' "
                            "WHERE id = ?", (scatto,))

    detto = pagina.novita(archivio_pieno, telefono)

    assert detto["cambiate"] == 1


def test_un_ramo_rinominato_si_dice(archivio_pieno, telefono, tmp_path):
    _copia(archivio_pieno, telefono, tmp_path)
    with archivio_pieno.scrittura() as connessione:
        connessione.execute("UPDATE nodi SET nome = 'pronti_e_rinominati' "
                            "WHERE nome = 'pronti_per_il_telefono'")

    detto = pagina.novita(archivio_pieno, telefono)

    assert detto["nomi"]
    assert detto["cambiate"] == 0
    assert "nomi di rami, persone o luoghi cambiati" in detto["a_parole"]


def test_uno_scatto_tolto_dalla_scelta_si_conta(archivio_pieno, telefono, tmp_path):
    _copia(archivio_pieno, telefono, tmp_path)
    scatto = _uno_scatto(archivio_pieno, telefono)
    pagina.salva_i_tolti(archivio_pieno, telefono, [scatto])

    detto = pagina.novita(archivio_pieno, telefono)

    assert detto["tolte"] == 1
    assert "1 da togliere" in detto["a_parole"]


def test_uno_scatto_che_non_era_sul_telefono_e_nuovo(archivio_pieno, telefono, tmp_path):
    _copia(archivio_pieno, telefono, tmp_path)
    scatto = _uno_scatto(archivio_pieno, telefono)
    with archivio_pieno.scrittura() as connessione:
        connessione.execute("DELETE FROM sul_telefono WHERE telefono_id = ? AND scatto_id = ?",
                            (telefono, scatto))

    detto = pagina.novita(archivio_pieno, telefono)

    assert detto["nuove"] == 1
    assert "1 foto nuova" in detto["a_parole"]


def test_una_foto_migliorata_si_conta(archivio_pieno, telefono, tmp_path):
    _copia(archivio_pieno, telefono, tmp_path)
    scatto = _uno_scatto(archivio_pieno, telefono)
    with archivio_pieno.scrittura() as connessione:
        connessione.execute("UPDATE sul_telefono SET file = 'vecchia' "
                            "WHERE telefono_id = ? AND scatto_id = ?", (telefono, scatto))

    detto = pagina.novita(archivio_pieno, telefono)

    assert detto["migliorate"] == 1
    assert "1 foto migliorata" in detto["a_parole"]


def test_un_travaso_fermato_non_si_ricorda(archivio_pieno, telefono, tmp_path):
    travaso = costruzione.Travaso(archivio_pieno, telefono, tmp_path / "Visore-iPhone",
                                  PAROLA)
    esito = travaso.esegui()
    esito.interrotto = True

    assert not travaso.ricorda_sul_telefono(esito)
    with archivio_pieno.lettura() as connessione:
        assert telefoni.quello_che_ha(connessione, telefono) == {}


def test_la_copia_col_cavo_pesa_ogni_fase(archivio_pieno, telefono, tmp_path):
    pesate = []
    travaso = costruzione.Travaso(
        archivio_pieno, telefono, tmp_path / "Visore-iPhone", PAROLA,
        quanto_pesa=lambda fase, fatti, quanti: pesate.append((fase, fatti, quanti)))
    assert travaso.esegui().completo
    radice = tmp_path / "iphone"
    (radice / cavo.PACCHETTO).mkdir(parents=True)
    cavo.manda(cavo.FintoTelefono(radice), tmp_path / "Visore-iPhone",
               quanto_pesa=lambda fase, fatti, quanti: pesate.append((fase, fatti, quanti)))

    fasi = [f for f, _, _ in pesate]
    for fase in ("scrivo", "verifico", "conto", "copio"):
        assert fase in fasi
        ultima = [p for p in pesate if p[0] == fase][-1]
        assert 0 < ultima[1] <= ultima[2]
    copio = [p for p in pesate if p[0] == "copio"]
    assert copio[-1][1] == copio[-1][2]


def test_la_stima_prima_di_partire_c_e(archivio_pieno, telefono, tmp_path):
    detto = pagina.novita(archivio_pieno, telefono)

    assert detto["tempo"]
    assert detto["tempo_a_occhio"]


def _tutti(archivio, telefono):
    with archivio.lettura() as connessione:
        return set(telefoni.quello_che_ha(connessione, telefono))


class _Orologio:

    def __init__(self):
        self.ora = 0.0

    def __call__(self):
        return self.ora


def test_orologio_misura_e_ricorda(tmp_path):
    tempo = _Orologio()
    dove = tmp_path / "velocita.json"
    primo = orologio.Orologio(dove, adesso=tempo)
    primo.prevedi("verifico", 1000)
    primo.avanza("scrivo", 0, 1000)
    assert primo.mancano() is None
    tempo.ora = 30
    primo.avanza("scrivo", 300, 1000)
    assert primo.mancano() == pytest.approx(70 + 1000 / orologio.SE_NON_SO["verifico"])
    tempo.ora = 100
    primo.avanza("scrivo", 1000, 1000)
    primo.avanza("verifico", 0, 1000)
    tempo.ora = 125
    primo.avanza("verifico", 1000, 1000)
    primo.fine()

    secondo = orologio.Orologio(dove, adesso=tempo)
    assert secondo.ricordate["scrivo"] == pytest.approx(10)
    assert secondo.ricordate["verifico"] == pytest.approx(40)
    assert secondo.conosce({"scrivo": 1, "verifico": 1})
    assert not secondo.conosce({"copio": 1})
    assert secondo.stima({"scrivo": 600, "verifico": 400}) == pytest.approx(70)


def test_orologio_col_cavo_dal_portatile_ricorda_a_parte(tmp_path):
    tempo = _Orologio()
    dove = tmp_path / "velocita.json"
    lontano = orologio.Orologio(dove, lontano=True, adesso=tempo)
    lontano.avanza("copio", 0, 100)
    tempo.ora = 50
    lontano.avanza("copio", 100, 100)
    lontano.fine()

    letto = orologio.leggi(dove)
    assert letto == {"copio_lontano": pytest.approx(2)}


def test_orologio_in_sosta_non_conta_l_attesa(tmp_path):
    tempo = _Orologio()
    dove = tmp_path / "velocita.json"
    fermo = orologio.Orologio(dove, adesso=tempo)
    fermo.avanza("copio", 0, 1000)
    tempo.ora = 50
    fermo.avanza("copio", 500, 1000)
    fermo.sosta()
    assert fermo.mancano() is None
    tempo.ora = 3650
    fermo.avanza("copio", 0, 500)
    tempo.ora = 3700
    fermo.avanza("copio", 500, 500)
    fermo.fine()

    assert orologio.leggi(dove) == {"copio": pytest.approx(10)}


def test_orologio_non_ricorda_le_fasi_troppo_corte(tmp_path):
    tempo = _Orologio()
    dove = tmp_path / "velocita.json"
    corto = orologio.Orologio(dove, adesso=tempo)
    corto.avanza("scrivo", 0, 10)
    tempo.ora = 5
    corto.avanza("scrivo", 10, 10)
    corto.fine()

    assert orologio.leggi(dove) == {}


@pytest.mark.parametrize("secondi, detto", [
    (None, ""),
    (20, "manca meno di un minuto"),
    (65, "manca circa 1 minuto"),
    (12 * 60, "mancano circa 12 minuti"),
    (60 * 60, "mancano circa 1 ora"),
    (83 * 60, "mancano circa 1 ora e 25 minuti"),
    (3 * 3600 + 58 * 60, "mancano circa 4 ore"),
    (11 * 3600 + 20 * 60, "mancano circa 11 ore"),
])
def test_quanto_manca_a_parole(secondi, detto):
    assert orologio.mancano_a_parole(secondi) == detto


def test_dalla_pagina_col_cavo_si_ricorda_cosa_ha_l_iphone(archivio_pieno, telefono,
                                                            tmp_path, monkeypatch):
    radice = tmp_path / "iphone"
    (radice / cavo.PACCHETTO).mkdir(parents=True)
    monkeypatch.setattr(cavo, "collega", lambda: cavo.FintoTelefono(radice))
    in_corso = pagina.InCorso()

    assert in_corso.parti(archivio_pieno, telefono, tmp_path / "Visore-iPhone", PAROLA,
                          col_cavo=True)
    assert in_corso.lavoro.aspetta_che_finisca(120)
    detto = in_corso.come_va()
    assert detto["cavo_completo"], detto["guasto"]
    assert "mancano" in detto

    assert pagina.novita(archivio_pieno, telefono)["aggiornato"]


def test_solo_prepara_per_l_iphone_non_lo_segna_come_aggiornato(archivio_pieno, telefono,
                                                                tmp_path):
    in_corso = pagina.InCorso()

    assert in_corso.parti(archivio_pieno, telefono, tmp_path / "Visore-iPhone", PAROLA)
    assert in_corso.lavoro.aspetta_che_finisca(120)
    assert in_corso.come_va()["completo"]

    assert not pagina.novita(archivio_pieno, telefono)["conosciuto"]


def test_la_copia_col_cavo_che_non_finisce_non_si_ricorda(archivio_pieno, telefono,
                                                          tmp_path, monkeypatch):
    radice = tmp_path / "iphone"
    (radice / cavo.PACCHETTO).mkdir(parents=True)
    monkeypatch.setattr(cavo, "collega",
                        lambda: cavo.FintoTelefono(radice, rovina={"foto"}))
    in_corso = pagina.InCorso()

    assert in_corso.parti(archivio_pieno, telefono, tmp_path / "Visore-iPhone", PAROLA,
                          col_cavo=True)
    assert in_corso.lavoro.aspetta_che_finisca(120)
    assert not in_corso.come_va()["cavo_completo"]

    assert not pagina.novita(archivio_pieno, telefono)["conosciuto"]
