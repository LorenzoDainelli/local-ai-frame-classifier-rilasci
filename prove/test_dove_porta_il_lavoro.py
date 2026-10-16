from officina.web.strade import comune, generale


def test_i_lavori_dell_ia_portano_all_intelligenza():
    for lavoro in (comune.lavoro_corpi, comune.lavoro_chi_e, comune.lavoro_ia,
                   comune.lavoro_volti, comune.lavoro_parole):
        assert generale._DOVE_SI_GUARDA[lavoro.cosa] == "/intelligenza"
