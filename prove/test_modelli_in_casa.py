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


def test_se_un_modello_non_arriva_gli_altri_si_scaricano_lo_stesso(tmp_path, monkeypatch):
    import pytest

    portati = []

    def porta(quale, dove, lavoro):
        portati.append(quale)
        if quale == "dinov3":
            raise RuntimeError("il file è rovinato")

    monkeypatch.setattr(modelli_in_casa, "porta_in_casa", porta)
    monkeypatch.setattr(modelli_in_casa, "in_casa", lambda quale, dove=None: False)
    fila = modelli_in_casa.Fila(quali=["dinov3", "volti", "seedvr2"])
    with pytest.raises(RuntimeError, match="rovinato"):
        modelli_in_casa.scarica_in_fila(fila, tmp_path, lavori.Lavoro("prova"),
                                        c_e_rete=lambda: True, dormi=lambda s: None)
    assert portati == ["dinov3", "volti", "seedvr2"]
    assert fila.fatti == ["volti", "seedvr2"]
    assert fila.adesso == ""


def test_se_piu_modelli_non_arrivano_si_dicono_tutti_insieme(tmp_path, monkeypatch):
    from officina.errori import ErroreOfficina

    def porta(quale, dove, lavoro):
        if quale in ("seedvr2", "codeformer"):
            raise ErroreOfficina("Hugging Face non risponde.")
        if quale == "faceme":
            raise KeyError("pezzo_che_manca")

    monkeypatch.setattr(modelli_in_casa, "porta_in_casa", porta)
    monkeypatch.setattr(modelli_in_casa, "in_casa", lambda quale, dove=None: False)
    lavoro = lavori.Lavoro("prova")
    fila = modelli_in_casa.Fila(quali=["seedvr2", "volti", "codeformer", "faceme"])
    lavoro.parti(lambda: modelli_in_casa.scarica_in_fila(fila, tmp_path, lavoro,
                                                         c_e_rete=lambda: True,
                                                         dormi=lambda s: None))
    assert lavoro.aspetta_che_finisca(5)
    assert fila.fatti == ["volti"]
    nomi = [modelli_in_casa.nome(q) for q in ("seedvr2", "codeformer", "faceme")]
    assert lavoro.guasto.startswith(modelli_in_casa.NON_ARRIVATI)
    assert lavoro.guasto.count("Hugging Face non risponde.") == 1
    assert f"{nomi[0]}, {nomi[1]}: Hugging Face non risponde." in lavoro.guasto
    assert f"{nomi[2]}: {modelli_in_casa.DIFETTO}" in lavoro.guasto
    assert nomi[2] in lavoro.dettaglio and "KeyError" in lavoro.dettaglio
    assert "pezzo_che_manca" not in lavoro.guasto


def test_se_si_ferma_mentre_un_modello_non_arriva_non_si_dice_niente(tmp_path, monkeypatch):
    fila = modelli_in_casa.Fila(quali=["dinov3", "volti"])
    portati = []

    def porta(quale, dove, lavoro):
        portati.append(quale)
        fila.fermata = True
        raise RuntimeError("fermato a metà")

    monkeypatch.setattr(modelli_in_casa, "porta_in_casa", porta)
    monkeypatch.setattr(modelli_in_casa, "in_casa", lambda quale, dove=None: False)
    modelli_in_casa.scarica_in_fila(fila, tmp_path, lavori.Lavoro("prova"),
                                    c_e_rete=lambda: True, dormi=lambda s: None)
    assert portati == ["dinov3"]
    assert fila.fatti == []


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


def test_il_peso_dei_modelli_viene_dai_file_che_si_scaricano_davvero():
    from officina.corpi import scaricamento as scarica_corpi
    from officina.miglioria import codeformer_pesi, lucidflux_pesi
    from officina.miglioria import scaricamento as scarica_miglioria

    assert modelli_in_casa.peso("corpi") == scarica_corpi.BYTE_IN_TUTTO
    assert modelli_in_casa.peso("corpi") > sum(f.byte for f in scarica_corpi.FIGURE)
    assert modelli_in_casa.peso("seedvr2") == scarica_miglioria.byte_circa("seedvr2")
    assert modelli_in_casa.peso("codeformer") == codeformer_pesi.byte_da_scaricare()
    assert modelli_in_casa.peso("lucidflux") == lucidflux_pesi.byte_circa()
    assert all(modelli_in_casa.peso(q) > 0
               for q in (*modelli_in_casa.OBBLIGATORI, *modelli_in_casa.FACOLTATIVI))
