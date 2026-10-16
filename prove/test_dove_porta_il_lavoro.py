from officina.web.strade import comune, generale


def test_i_lavori_dell_ia_portano_all_intelligenza():
    for lavoro in (comune.lavoro_corpi, comune.lavoro_chi_e, comune.lavoro_ia,
                   comune.lavoro_volti, comune.lavoro_parole):
        assert generale._DOVE_SI_GUARDA[lavoro.cosa] == "/intelligenza"


def test_telefono_e_sincronia_portano_alla_loro_pagina():
    from officina.web import sincronia, telefono

    assert generale._DOVE_SI_GUARDA[telefono.in_corso.lavoro.cosa] == "/telefono"
    assert generale._DOVE_SI_GUARDA[sincronia.in_corso.lavoro.cosa] == "/sincronia"


def test_chi_e_senza_volto_compare_fra_i_lavori():
    assert comune.lavoro_chi_e in generale._tutti_i_lavori()
