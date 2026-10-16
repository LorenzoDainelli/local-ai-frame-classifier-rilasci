from __future__ import annotations

from pathlib import Path

import pytest

from officina.errori import ErroreOfficina
from officina.programma import avvio, carta, librerie, ponti, scheda

from prove.test_programma_finestre import WebviewFinto

COSA_MANCA_VERA = librerie.cosa_manca


@pytest.fixture
def casa(tmp_path, monkeypatch):
    from officina import modelli_in_casa
    from officina.archivio import accesso
    from officina.programma import segreti

    monkeypatch.setenv("OFFICINA_CASA_PROGRAMMA", str(tmp_path / "casa"))
    monkeypatch.delenv("OFFICINA_ARCHIVIO", raising=False)
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.setattr(carta, "cartella_della_versione_1", lambda: tmp_path / "nessuna")
    monkeypatch.setattr(avvio, "PORTA_PREFERITA", 0)
    monkeypatch.setattr(modelli_in_casa, "mancano_gli_obbligatori", lambda dove=None: [])
    monkeypatch.setattr(segreti, "si_puo_custodire", lambda: False)
    accesso.chiudi(con_copia=False)
    yield tmp_path
    segreti._in_memoria.pop(segreti.CHIAVE_HF, None)
    accesso.chiudi(con_copia=False)


def _con_torch(versione: str) -> None:
    librerie.cartella("torch").mkdir(parents=True, exist_ok=True)
    librerie.cartella("modelli").mkdir(parents=True, exist_ok=True)
    carta.aggiorna(librerie={
        "torch": {"python": scheda.etichetta_di_python(), "torch": versione,
                  "variante": "cpu", "esame": scheda.Esame().come_dati()},
        "modelli": {"impronta": librerie.impronta_delle_richieste(["transformers==1"])}})


@pytest.fixture
def vera(monkeypatch):
    monkeypatch.setattr(librerie, "cosa_manca",
                        lambda richieste=None: COSA_MANCA_VERA(["transformers==1"]))


def _programma(monkeypatch):
    programma = avvio.Programma(webview=WebviewFinto(), esamina=scheda.Esame)
    partiti = []
    monkeypatch.setattr(programma.installatore, "parti",
                        lambda parti=None: partiti.append(parti) or True)
    return programma, partiti


@pytest.mark.parametrize("versione", ["2.5.1+cu121", "2.4.0", "1.13.1+cpu", "torch"])
def test_un_torch_vecchio_conta_come_mancante(casa, versione):
    _con_torch(versione)
    assert COSA_MANCA_VERA(["transformers==1"]) == ["torch"]
    assert librerie.torch_vecchio() == versione


@pytest.mark.parametrize("versione", ["2.6.0+cu124", "2.14.0+cpu", "3.0.0"])
def test_un_torch_recente_non_si_rifa(casa, versione):
    _con_torch(versione)
    assert COSA_MANCA_VERA(["transformers==1"]) == []
    assert librerie.torch_vecchio() is None


def test_senza_la_cartella_non_e_vecchio_ma_manca(casa):
    _con_torch("2.5.1")
    Path(librerie.cartella("torch")).rmdir()
    assert librerie.torch_vecchio() is None
    assert "torch" in COSA_MANCA_VERA(["transformers==1"])


def test_all_avvio_il_torch_vecchio_si_rifa_da_solo_una_volta(casa, vera, monkeypatch):
    carta.comincia_da_zero()
    _con_torch("2.5.1+cpu")
    programma, partiti = _programma(monkeypatch)
    stato = programma.stato_per_la_finestrina()
    assert stato["passo"] == "motori"
    assert stato["vecchio"] is True
    assert "torch 2.5.1+cpu" in stato["scheda"]
    assert "troppo vecchio" in stato["scheda"]
    assert partiti == [["torch"]]
    programma.stato_per_la_finestrina()
    assert partiti == [["torch"]]


def test_col_torch_recente_non_parte_niente(casa, vera, monkeypatch):
    carta.comincia_da_zero()
    _con_torch("2.6.0+cpu")
    carta.aggiorna(obblighi_sospesi=True, chiave_chiesta=True)
    programma, partiti = _programma(monkeypatch)
    assert programma.passo() == "pronto"
    assert partiti == []


def test_se_lo_scaricamento_non_va_si_entra_lo_stesso(casa, vera, monkeypatch):
    carta.comincia_da_zero()
    _con_torch("2.5.1+cpu")
    carta.aggiorna(obblighi_sospesi=True, chiave_chiesta=True)
    programma, _ = _programma(monkeypatch)
    programma.stato_per_la_finestrina()
    assert programma.passo() == "motori"
    risposta = ponti.PonteFinestrina(programma).entra_col_torch_vecchio()
    assert "errore" not in risposta
    assert programma.passo() == "pronto"
    motori = programma.stato_del_programma()["motori"]
    assert motori["mancano"] == ["torch"]
    assert motori["vecchio"] == "2.5.1+cpu"

    di_nuovo, partiti = _programma(monkeypatch)
    assert di_nuovo.stato_per_la_finestrina()["passo"] == "motori"
    assert partiti == [["torch"]]


def test_entrare_col_torch_vecchio_non_vale_se_non_e_vecchio(casa, vera, monkeypatch):
    carta.comincia_da_zero()
    _con_torch("2.6.0+cpu")
    programma, _ = _programma(monkeypatch)
    with pytest.raises(ErroreOfficina):
        programma.entra_col_torch_vecchio()
    assert not programma._entra_col_torch_vecchio


def test_la_finestrina_ha_il_tasto_per_entrare_lo_stesso():
    html = (Path(avvio.__file__).parent / "pagine" / "finestrina.html").read_text(encoding="utf-8")
    assert 'data-fai="entra_col_torch_vecchio"' in html
    assert "entra_col_torch_vecchio: function" in html
    assert "torch_vecchio ? \"Riprova\"" in html
    programma_js = (Path(avvio.__file__).parent.parent / "web" / "statici" / "js"
                    / "programma.js").read_text(encoding="utf-8")
    assert "m.mancano.length && m.vecchio" in programma_js
