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
