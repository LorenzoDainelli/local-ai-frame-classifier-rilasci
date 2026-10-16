from __future__ import annotations

import time

import pytest

from officina.archivio import database


@pytest.fixture
def a_roma(monkeypatch):
    monkeypatch.setenv("TZ", "Europe/Rome")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


def test_un_istante_salvato_si_mostra_nell_ora_di_qui(a_roma):
    assert database.ora_a_parole("2026-10-14T22:30:00Z") == "15 ottobre 2026, 00:30"
    assert database.ora_a_parole("2026-01-10T08:05:00Z") == "10 gennaio 2026, 09:05"


def test_anche_il_nome_delle_copie_e_nell_ora_di_greenwich(a_roma):
    assert database.ora_a_parole("20260701-230000") == "2 luglio 2026, 01:00"
    assert database.ora_a_parole("20260701-230000-2") == "2 luglio 2026, 01:00"


def test_quello_che_non_si_capisce_resta_com_e():
    assert database.ora_a_parole("ieri") == "ieri"
    assert database.ora_a_parole(None) == ""
    assert database.ora_di_qui("") is None


def test_la_copia_dice_l_ora_di_qui(a_roma, tmp_path):
    from officina.archivio.copie import Copia

    copia = Copia(tmp_path / "x.sqlite", "20261014-223000", "chiusura", 10)
    assert copia.quando == "15 ottobre 2026, 00:30"


def test_il_telefono_dice_l_ora_di_qui(a_roma):
    from officina.web import telefono

    detto = telefono._quando_a_parole("2026-10-14T22:30:00Z")
    assert detto.endswith(", 00:30")
