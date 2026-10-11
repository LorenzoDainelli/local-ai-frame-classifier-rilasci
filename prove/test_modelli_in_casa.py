from __future__ import annotations

from officina import modelli_in_casa
from officina.web import lavori


def test_se_la_rete_cade_aspetta_e_riprende_da_solo(tmp_path, monkeypatch):
    tentativi = []
    rete = iter([False, False, True])

    def porta(quale, dove, lavoro):
        tentativi.append(quale)
        if len(tentativi) == 1:
            raise OSError("la rete se n'è andata")

    monkeypatch.setattr(modelli_in_casa, "porta_in_casa", porta)
    monkeypatch.setattr(modelli_in_casa, "in_casa", lambda quale, dove=None: False)
    dormite = []
    fila = modelli_in_casa.Fila(quali=["dinov3", "volti"])
    modelli_in_casa.scarica_in_fila(fila, tmp_path, lavori.Lavoro("prova"),
                                    c_e_rete=lambda: next(rete), dormi=dormite.append)
    assert tentativi == ["dinov3", "dinov3", "volti"]
    assert fila.fatti == ["dinov3", "volti"]
    assert dormite == [modelli_in_casa.ATTESA_RETE]
    assert fila.aspetta_la_rete is False


def test_un_guasto_con_la_rete_accesa_si_dice_subito(tmp_path, monkeypatch):
    import pytest

    def porta(quale, dove, lavoro):
        raise RuntimeError("il file è rovinato")

    monkeypatch.setattr(modelli_in_casa, "porta_in_casa", porta)
    monkeypatch.setattr(modelli_in_casa, "in_casa", lambda quale, dove=None: False)
    fila = modelli_in_casa.Fila(quali=["dinov3"])
    with pytest.raises(RuntimeError):
        modelli_in_casa.scarica_in_fila(fila, tmp_path, lavori.Lavoro("prova"),
                                        c_e_rete=lambda: True, dormi=lambda s: None)


def test_quelli_gia_in_casa_non_si_riscaricano(tmp_path, monkeypatch):
    portati = []
    monkeypatch.setattr(modelli_in_casa, "porta_in_casa",
                        lambda quale, dove, lavoro: portati.append(quale))
    monkeypatch.setattr(modelli_in_casa, "in_casa", lambda quale, dove=None: quale == "volti")
    fila = modelli_in_casa.Fila(quali=["volti", "seedvr2"])
    modelli_in_casa.scarica_in_fila(fila, tmp_path, lavori.Lavoro("prova"))
    assert portati == ["seedvr2"]


def test_i_conti_dei_byte_tornano():
    fila = modelli_in_casa.Fila(quali=["seedvr2", "codeformer"], fatti=["seedvr2"],
                                adesso="codeformer")
    assert fila.byte_totali() == modelli_in_casa.peso("seedvr2") + modelli_in_casa.peso("codeformer")
    fatti = fila.byte_fatti({"unita": "byte", "scaricati": 1000})
    assert fatti == modelli_in_casa.peso("seedvr2") + 1000


def test_senza_i_modelli_obbligatori_il_programma_non_si_apre(tmp_path, monkeypatch):
    from officina.programma import avvio, carta, librerie

    monkeypatch.setenv("OFFICINA_CASA_PROGRAMMA", str(tmp_path / "casa"))
    monkeypatch.setenv("HF_TOKEN", "hf_" + "x" * 34)
    monkeypatch.setattr(carta, "cartella_della_versione_1", lambda: tmp_path / "nessuna")
    monkeypatch.setattr(librerie, "cosa_manca", lambda richieste=None: [])
    monkeypatch.setattr(modelli_in_casa, "mancano_gli_obbligatori", lambda dove=None: ["dinov3"])
    monkeypatch.setattr(modelli_in_casa, "in_casa", lambda quale, dove=None: False)
    carta.comincia_da_zero()
    carta.aggiorna(miglioria_scelti_all_avvio=None)
    programma = avvio.Programma(webview=object())
    monkeypatch.setattr(programma.scaricatore, "parti", lambda quali, dove=None: True)
    assert programma.passo() == "modelli"
    stato = programma.stato_per_la_finestrina()
    modelli = stato["modelli"]
    assert [v["quale"] for v in modelli["obbligatori"]] == list(modelli_in_casa.OBBLIGATORI)
    assert [v["quale"] for v in modelli["facoltativi"] if v["consigliato"]] == ["seedvr2", "codeformer"]

    monkeypatch.setattr(modelli_in_casa, "mancano_gli_obbligatori", lambda dove=None: [])
    assert programma.passo() != "modelli"
