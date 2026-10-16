from __future__ import annotations

import pytest

from officina import modelli_in_casa
from officina.errori import ErroreOfficina
from officina.programma import avvio, carta, ponti
from prove.test_programma_finestre import _programma, casa  # noqa: F401

MANCA_SAM3 = [("SAM 3", "https://huggingface.co/facebook/sam3")]


@pytest.fixture
def modelli(casa, monkeypatch):  # noqa: F811
    monkeypatch.setattr(modelli_in_casa, "cartella", lambda: casa / "modelli")
    stato = {"mancano": ["corpi"], "partiti": []}
    monkeypatch.setattr(modelli_in_casa, "mancano_gli_obbligatori",
                        lambda dove=None: list(stato["mancano"]))
    return stato


def _senza_scaricare(programma, stato, monkeypatch):
    monkeypatch.setattr(programma.scaricatore, "parti", lambda quali: stato["partiti"].append(quali))


def test_la_chiave_si_salva_anche_con_un_permesso_in_attesa(modelli, monkeypatch):
    monkeypatch.setattr(modelli_in_casa, "permessi_mancanti", lambda chiave, repo=None: MANCA_SAM3)
    programma, _ = _programma()
    programma.salva_la_chiave("hf_" + "x" * 34)
    from officina.programma import segreti

    assert segreti.c_e_la_chiave_hf()
    assert modelli_in_casa.permessi_in_attesa() == ["SAM 3"]


def test_una_chiave_sconosciuta_non_si_salva(modelli, monkeypatch):
    def rifiuta(chiave, repo=None):
        raise ErroreOfficina("Hugging Face non riconosce questa chiave.")

    monkeypatch.setattr(modelli_in_casa, "permessi_mancanti", rifiuta)
    programma, _ = _programma()
    with pytest.raises(ErroreOfficina):
        programma.salva_la_chiave("hf_" + "x" * 34)
    from officina.programma import segreti

    assert not segreti.c_e_la_chiave_hf()


def test_entra_lo_stesso_solo_se_mancano_solo_i_corpi_per_un_permesso(modelli, monkeypatch):
    programma, _ = _programma()
    _senza_scaricare(programma, modelli, monkeypatch)
    assert not programma.si_entra_senza_i_corpi()
    modelli_in_casa.ricorda_i_permessi(MANCA_SAM3)
    assert programma.si_entra_senza_i_corpi()
    modelli["mancano"] = ["corpi", "volti"]
    assert not programma.si_entra_senza_i_corpi()
    with pytest.raises(ErroreOfficina):
        programma.entra_senza_i_corpi()
    assert not carta.leggi().get("corpi_dopo")


def test_dopo_entra_lo_stesso_non_si_chiedono_piu_i_modelli_e_si_riprova(modelli, monkeypatch):
    modelli_in_casa.ricorda_i_permessi(MANCA_SAM3)
    programma, _ = _programma()
    _senza_scaricare(programma, modelli, monkeypatch)
    assert programma._servono_i_modelli()
    assert "errore" not in ponti.PonteFinestrina(programma).entra_senza_i_corpi()
    assert carta.leggi().get("corpi_dopo")
    assert not programma._servono_i_modelli()
    nuovo, _ = _programma()
    _senza_scaricare(nuovo, modelli, monkeypatch)
    assert not nuovo._servono_i_modelli()
    assert not nuovo._servono_i_modelli()
    assert modelli["partiti"] == [["corpi"]]


def test_se_poi_manca_altro_si_torna_a_chiedere(modelli, monkeypatch):
    carta.aggiorna(corpi_dopo=True)
    modelli["mancano"] = ["corpi", "parole"]
    programma, _ = _programma()
    _senza_scaricare(programma, modelli, monkeypatch)
    assert programma._servono_i_modelli()


def test_il_permesso_arrivato_si_dimentica(modelli):
    modelli_in_casa.ricorda_i_permessi(MANCA_SAM3)
    modelli_in_casa.ricorda_i_permessi([])
    assert modelli_in_casa.permessi_in_attesa() == []


def test_la_finestrina_ha_il_tasto_entra_lo_stesso():
    from pathlib import Path

    pagina = (Path(avvio.__file__).parent / "pagine" / "finestrina.html").read_text(encoding="utf-8")
    assert 'data-fai="entra_senza_i_corpi"' in pagina
    assert "Entra lo stesso" in pagina


def test_lo_stato_dice_quale_permesso_manca():
    from officina.web import stato_a_parole

    salute = {"modelli": [], "scaricamento": {}, "numeri": [], "copie": [1], "capacita": [],
              "permessi_in_attesa": ["SAM 3", "VGGT-Omega"]}
    voci = [v for v in stato_a_parole.da_sistemare(salute) if "permesso" in v["titolo"]]
    assert len(voci) == 1
    assert "SAM 3 e VGGT-Omega" in voci[0]["testo"]


def test_mentre_riprova_i_corpi_in_sottofondo_non_ti_ferma(modelli, monkeypatch):
    carta.aggiorna(corpi_dopo=True)
    programma, _ = _programma()
    _senza_scaricare(programma, modelli, monkeypatch)
    assert not programma._servono_i_modelli()
    monkeypatch.setattr(type(programma.scaricatore.lavoro), "sta_lavorando", property(lambda self: True))
    assert not programma._servono_i_modelli()
