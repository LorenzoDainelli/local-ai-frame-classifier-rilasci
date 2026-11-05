from __future__ import annotations

from pathlib import Path

import pytest

from officina import descrittori
from officina.descrittori.grandi import Radio4


@pytest.fixture
def casa(monkeypatch):
    presenti = {"dinov3", "siglip2", "radio4"}
    monkeypatch.setitem(descrittori.SCHEDE, "radio4", Radio4.scheda)
    monkeypatch.setattr(descrittori, "in_casa", lambda nome, _: nome in presenti
                        or nome == "disegnato")
    return presenti


def test_con_radio4_in_casa_siglip2_non_fa_piu_impronte(casa):
    assert descrittori.superato_da("siglip2", Path(".")) == "radio4"
    assert "siglip2" not in descrittori.pronti(Path("."))
    assert "radio4" in descrittori.pronti(Path("."))


def test_senza_radio4_siglip2_resta_pronto(casa):
    casa.discard("radio4")
    assert descrittori.superato_da("siglip2", Path(".")) is None
    assert "siglip2" in descrittori.pronti(Path("."))


def test_radio4_sconosciuto_non_supera(monkeypatch):
    monkeypatch.delitem(descrittori.SCHEDE, "radio4", raising=False)
    monkeypatch.setattr(descrittori, "in_casa", lambda nome, _: True)
    assert descrittori.superato_da("siglip2", Path(".")) is None
