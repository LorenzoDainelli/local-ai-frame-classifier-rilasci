from __future__ import annotations

from officina.telefono.costruzione import Esito, Saltato


def test_un_travaso_riuscito_dice_cosa_ha_fatto():
    detto = Esito(scritti=412, tolti=8, peso=3_200_000_000, verificati=420).a_parole()
    assert detto.startswith("Fatto:")
    assert "412 file nuovi" in detto
    assert "3,2 GB" in detto
    assert "8 tolti" in detto
    assert "420 riletti e verificati" in detto


def test_l_italiano_ha_il_singolare():
    detto = Esito(scritti=1, peso=900, verificati=1).a_parole()
    assert "1 file nuovo" in detto
    assert "1 riletto e verificato" in detto


def test_niente_da_cambiare_non_e_niente():
    detto = Esito(verificati=310).a_parole()
    assert "non c'era niente da cambiare" in detto
    assert "310 file riletti e verificati" in detto


def test_fermato_non_si_scrive_come_un_guasto():
    detto = Esito(scritti=5, peso=100, interrotto=True).a_parole()
    assert detto.startswith("Fermato:")
    assert "resta nel pacchetto" in detto
    assert "riprende" in detto


def test_un_file_venuto_diverso_e_l_unico_caso_grave():
    detto = Esito(scritti=100, peso=1000, verificati=100, guasti=["x"]).a_parole()
    assert not detto.startswith("Fatto")
    assert "va rifatto" in detto
    assert "non si aprono" in detto
    assert "100 file nuovi" not in detto


def test_i_guasti_al_singolare_e_al_plurale():
    assert "1 file è venuto diverso rileggendolo" in Esito(guasti=["a"]).a_parole()
    assert "2 file sono venuti diversi rileggendoli" in Esito(
        guasti=["a", "b"]).a_parole()


def test_i_file_non_entrati_si_dicono_e_non_fanno_fallire():
    detto = Esito(scritti=3, peso=100, verificati=3,
                  saltati=[Saltato("x", "y")]).a_parole()
    assert detto.startswith("Fatto:")
    assert "1 file non è entrato" in detto

    tanti = Esito(scritti=3, peso=100, verificati=3,
                  saltati=[Saltato("x", "y")] * 1200).a_parole()
    assert "1.200 file non sono entrati" in tanti


def test_le_migliaia_col_punto_anche_qui():
    detto = Esito(scritti=28740, peso=1000, verificati=28740).a_parole()
    assert "28.740" in detto
    assert "28,740" not in detto


def test_la_riga_esce_verso_la_pagina():
    from officina.web import telefono as telefono_web

    in_corso = telefono_web.InCorso()
    in_corso.esito = Esito(scritti=7, peso=2000, verificati=7)

    detto = in_corso.come_va()

    assert detto["riepilogo"] == in_corso.esito.a_parole()
    assert telefono_web.InCorso().come_va()["riepilogo"] == ""
