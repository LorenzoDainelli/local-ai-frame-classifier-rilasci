from __future__ import annotations

import threading

import pytest

from officina.descrittori import scaricamento
from officina.web import lavori


def test_conta_i_byte_che_ci_sono_adesso(tmp_path):
    (tmp_path / "uno.safetensors").write_bytes(b"x" * 1000)
    (tmp_path / "due.json").write_bytes(b"y" * 24)
    assert scaricamento.quanto_pesa(tmp_path) == 1024


def test_conta_anche_i_pezzi_a_meta_nelle_sottocartelle(tmp_path):
    dentro = tmp_path / ".cache" / "huggingface" / "download"
    dentro.mkdir(parents=True)
    (dentro / "pesi.pt.incomplete").write_bytes(b"z" * 500)
    assert scaricamento.quanto_pesa(tmp_path) == 500


def test_una_cartella_vuota_pesa_zero_e_non_si_lamenta(tmp_path):
    assert scaricamento.quanto_pesa(tmp_path) == 0


def test_dice_subito_a_che_punto_e_senza_aspettare_il_primo_giro(tmp_path):
    (tmp_path / "gia_qui").write_bytes(b"a" * 300)
    detti = []
    with scaricamento.Sorvegliante(tmp_path, 1000, lambda f, a: detti.append((f, a))):
        pass
    assert detti[0] == (300, 1000)


def test_il_filo_si_ferma_quando_il_lavoro_finisce(tmp_path):
    quanti_prima = threading.active_count()
    with scaricamento.Sorvegliante(tmp_path, 10, lambda f, a: None, ogni_quanto=0.01):
        pass
    assert threading.active_count() == quanti_prima


def test_il_filo_si_ferma_anche_se_il_lavoro_va_male(tmp_path):
    quanti_prima = threading.active_count()
    with pytest.raises(ValueError):
        with scaricamento.Sorvegliante(tmp_path, 10, lambda f, a: None,
                                       ogni_quanto=0.01):
            raise ValueError("come se la connessione fosse caduta")
    assert threading.active_count() == quanti_prima


def test_racconta_piu_volte_mentre_i_byte_arrivano(tmp_path):
    arrivati = []
    fine = threading.Event()

    def segna(fatti, attesi):
        arrivati.append(fatti)
        if len(arrivati) >= 3:
            fine.set()

    with scaricamento.Sorvegliante(tmp_path, 1000, segna, ogni_quanto=0.01):
        (tmp_path / "pezzo").write_bytes(b"q" * 700)
        fine.wait(timeout=5)
    assert len(arrivati) >= 3
    assert arrivati[-1] == 700


def test_se_chi_racconta_si_rompe_il_lavoro_va_avanti_lo_stesso(tmp_path):
    def rotto(fatti, attesi):
        raise RuntimeError("difetto in chi disegna la barra")

    with scaricamento.Sorvegliante(tmp_path, 10, rotto):
        arrivato = True
    assert arrivato


def test_la_percentuale_e_i_byte_finiscono_nei_numeri_non_nelle_righe():
    lavoro = lavori.Lavoro("i modelli")
    lavoro.a_che_punto(2_000_000_000, 10_000_000_000)
    assert list(lavoro.righe) == []
    come_va = lavoro.come_va()
    assert come_va["percento"] == 20
    assert come_va["scaricati"] == 2_000_000_000
    assert come_va["da_scaricare"] == 10_000_000_000


def test_la_percentuale_non_arriva_a_cento_finche_non_e_finito():
    lavoro = lavori.Lavoro("i modelli")
    lavoro.a_che_punto(11_000_000_000, 9_700_000_000)
    assert lavoro.come_va()["percento"] == 99


def test_se_non_si_sa_quanto_pesa_la_barra_resta_a_zero_e_non_si_rompe():
    lavoro = lavori.Lavoro("i modelli")
    lavoro.a_che_punto(500, 0)
    assert lavoro.come_va()["percento"] == 0


def test_senza_scaricamento_in_corso_la_pagina_non_riceve_nessuna_percentuale():
    lavoro = lavori.Lavoro("i modelli")
    assert "percento" not in lavoro.come_va()


def test_mentre_scarica_la_barra_si_muove_davvero(tmp_path, monkeypatch):
    import sys
    import types

    from officina.descrittori.base import Scheda

    passi = []
    monkeypatch.setattr(scaricamento, "OGNI_QUANTO", 0.01)

    def finto_scaricamento(*_, local_dir=None, **__):
        from pathlib import Path
        cartella = Path(local_dir)
        (cartella / "config.json").write_text("{}", encoding="utf-8")
        (cartella / "pesi.safetensors").write_bytes(b"p" * 2000)
        fine = threading.Event()
        fine.wait(0.05)

    finto = types.ModuleType("huggingface_hub")
    finto.snapshot_download = finto_scaricamento
    monkeypatch.setitem(sys.modules, "huggingface_hub", finto)

    from officina.descrittori.base import PIENA, VISIVO
    carta = Scheda(nome="finto", titolo="Finto", versione="1",
                   precisione=PIENA, famiglia=VISIVO, dimensione=8,
                   licenza="finta", identificatore="chi/che-cosa",
                   byte_attesi=4000, lato=64, nota="solo per la prova")
    scaricamento.scarica(carta, tmp_path,
                         a_che_punto=lambda f, a: passi.append((f, a)))

    assert passi, "il sorvegliante non è stato acceso"
    assert passi[-1][0] > 0
    assert passi[-1][1] == 4000
