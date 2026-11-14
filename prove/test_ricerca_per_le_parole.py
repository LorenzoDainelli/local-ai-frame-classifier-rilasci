from __future__ import annotations

from pathlib import Path

import pytest

from officina import descrittori, ricerca
from officina.descrittori.grandi import Radio4


@pytest.fixture
def mondo(monkeypatch):
    stato = {"in_casa": {"radio4", "siglip2"}, "presenti": {"radio4": "1", "siglip2": "1"},
             "da_fare": {"radio4": 0, "siglip2": 0}}
    monkeypatch.setitem(descrittori.SCHEDE, "radio4", Radio4.scheda)
    monkeypatch.setattr(descrittori, "in_casa", lambda nome, _: nome in stato["in_casa"])
    monkeypatch.setattr(ricerca.magazzino, "modelli_presenti",
                        lambda _: list(stato["presenti"].items()))
    monkeypatch.setattr(ricerca.magazzino, "quanti_da_fare",
                        lambda _c, nome, _v: stato["da_fare"][nome])
    return stato


def test_con_le_impronte_nuove_finite_si_usa_radio4(mondo):
    assert ricerca.per_le_parole(None, Path(".")) == ("radio4", "")


def test_durante_il_rifacimento_si_usano_le_vecchie(mondo):
    mondo["da_fare"]["radio4"] = 120
    assert ricerca.per_le_parole(None, Path(".")) == ("siglip2", "")


def test_senza_le_vecchie_si_usa_radio4_anche_a_meta(mondo):
    mondo["da_fare"]["radio4"] = 120
    mondo["presenti"].pop("siglip2")
    assert ricerca.per_le_parole(None, Path(".")) == ("radio4", "")


def test_con_siglip2_tolto_dal_disco_si_usa_radio4_a_meta(mondo):
    mondo["da_fare"]["radio4"] = 120
    mondo["in_casa"].discard("siglip2")
    assert ricerca.per_le_parole(None, Path(".")) == ("radio4", "")


def test_niente_impronte_nuove_si_usano_le_vecchie(mondo):
    mondo["presenti"].pop("radio4")
    assert ricerca.per_le_parole(None, Path(".")) == ("siglip2", "")


def test_niente_modelli_dice_di_scaricare_radio4(mondo):
    mondo["in_casa"].clear()
    nome, detto = ricerca.per_le_parole(None, Path("."))
    assert nome is None and "radio4" in detto


def test_modello_senza_impronte_dice_il_comando(mondo):
    mondo["presenti"].clear()
    nome, detto = ricerca.per_le_parole(None, Path("."))
    assert nome is None and "--descrittore radio4" in detto


class _Parlatore:
    aperti = 0
    frasi: list = []

    def __init__(self):
        type(self).aperti += 1
        self.aperto = False
        self.chiuso = False

    def descrivi_parole(self, frasi):
        type(self).frasi.append(tuple(frasi))
        return [[1.0, 0.0] for _ in frasi]

    def chiudi(self):
        self.chiuso = True


def test_il_modello_delle_parole_si_carica_una_volta_e_le_frasi_si_ricordano(monkeypatch):
    monkeypatch.setattr(descrittori, "apri", lambda nome, cartella: _Parlatore())
    monkeypatch.setattr(_Parlatore, "aperti", 0)
    monkeypatch.setattr(_Parlatore, "frasi", [])
    ricerca.dimentica_i_modelli()
    ricerca._vettori.clear()
    for _ in range(3):
        assert ricerca._parole_in_vettori("radio4", Path("m"), ["cane"]) == [[1.0, 0.0]]
    ricerca._parole_in_vettori("radio4", Path("m"), ["gatto"])
    assert _Parlatore.aperti == 1
    assert _Parlatore.frasi == [("cane",), ("gatto",)]
    ricerca.dimentica_i_modelli()
    ricerca._vettori.clear()


def test_un_modello_aperto_tutto_non_resta_acceso(monkeypatch):
    class Intero(_Parlatore):
        def __init__(self):
            super().__init__()
            self.aperto = True
    fatti = []
    monkeypatch.setattr(descrittori, "apri", lambda *_: fatti.append(Intero()) or fatti[-1])
    ricerca.dimentica_i_modelli()
    ricerca._vettori.clear()
    ricerca._parole_in_vettori("siglip2", Path("m"), ["mare"])
    assert fatti[0].chiuso and ricerca._tenuti == {}
    ricerca._vettori.clear()


def test_le_impronte_si_rileggono_solo_se_cambiano(archivio_misurabile, monkeypatch):
    connessione = archivio_misurabile.connessione
    nome, versione = connessione.execute(
        "SELECT descrittore, versione FROM impronte WHERE inquadratura = 'intera' "
        "LIMIT 1").fetchone()
    letture = []
    vera = ricerca.magazzino.passata
    monkeypatch.setattr(ricerca.magazzino, "passata",
                        lambda *a, **k: letture.append(1) or vera(*a, **k))
    ricerca.dimentica_le_impronte()
    primo, matrice = ricerca._le_impronte(connessione, nome, versione)
    ricerca._le_impronte(connessione, nome, versione)
    assert len(letture) == 1 and len(primo) == matrice.shape[0]
    riga = connessione.execute(
        "SELECT * FROM impronte WHERE descrittore = ? AND versione = ? "
        "AND inquadratura = 'intera' LIMIT 1", (nome, versione)).fetchone()
    connessione.execute(
        "DELETE FROM impronte WHERE rowid = (SELECT rowid FROM impronte WHERE "
        "descrittore = ? AND versione = ? AND inquadratura = 'intera' LIMIT 1)",
        (nome, versione))
    connessione.commit()
    secondo, _ = ricerca._le_impronte(connessione, nome, versione)
    assert len(letture) == 2 and len(secondo) == len(primo) - 1
    assert riga is not None
    ricerca.dimentica_le_impronte()


def test_chiudere_l_archivio_dimentica_le_impronte(archivio_misurabile):
    from officina.archivio import accesso

    connessione = archivio_misurabile.connessione
    nome, versione = connessione.execute(
        "SELECT descrittore, versione FROM impronte LIMIT 1").fetchone()
    ricerca._le_impronte(connessione, nome, versione)
    assert ricerca._impronte
    accesso.chiudi(con_copia=False)
    assert ricerca._impronte == {}
