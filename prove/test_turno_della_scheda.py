import threading
import time

from officina.web import lavori


def _aspetta(condizione, entro=5.0):
    scadenza = time.monotonic() + entro
    while not condizione() and time.monotonic() < scadenza:
        time.sleep(0.01)
    return condizione()


def test_il_secondo_aspetta_e_parte_quando_la_scheda_e_libera(monkeypatch):
    with monkeypatch.context() as m:
        m.setattr(lavori, "turno", lavori.TurnoDellaScheda())
        ia = lavori.Lavoro("l'intelligenza artificiale", scheda=True)
        miglioria = lavori.Lavoro("miglioramento", scheda=True)
        via = threading.Event()
        ordine = []

        def primo():
            ordine.append("ia dentro")
            via.wait(5)
            ordine.append("ia fuori")

        assert ia.parti(primo, "intelligenza")
        assert _aspetta(lambda: ordine == ["ia dentro"])
        assert miglioria.parti(lambda: ordine.append("miglioria dentro"), "miglioramento")
        assert _aspetta(lambda: miglioria.numeri.get("in_attesa_della_scheda"))
        assert any("in attesa della scheda" in riga for riga in miglioria.righe)
        assert ordine == ["ia dentro"]
        via.set()
        assert miglioria.aspetta_che_finisca(5)
        assert ordine == ["ia dentro", "ia fuori", "miglioria dentro"]
        assert "in_attesa_della_scheda" not in miglioria.numeri
        assert lavori.turno.chi is None


def test_fermare_chi_aspetta_non_lo_fa_partire(monkeypatch):
    with monkeypatch.context() as m:
        m.setattr(lavori, "turno", lavori.TurnoDellaScheda())
        ia = lavori.Lavoro("l'intelligenza artificiale", scheda=True)
        miglioria = lavori.Lavoro("miglioramento", scheda=True)
        via = threading.Event()
        partito = []
        ia.parti(lambda: via.wait(5), "intelligenza")
        assert _aspetta(lambda: lavori.turno.chi is ia)
        miglioria.parti(lambda: partito.append(True), "miglioramento")
        assert _aspetta(lambda: miglioria.numeri.get("in_attesa_della_scheda"))
        lavori.turno.rinuncia("miglioramento")
        assert miglioria.aspetta_che_finisca(5)
        assert partito == []
        via.set()
        assert ia.aspetta_che_finisca(5)


def test_fermare_tutto_libera_chi_aspetta(monkeypatch):
    with monkeypatch.context() as m:
        m.setattr(lavori, "turno", lavori.TurnoDellaScheda())
        ia = lavori.Lavoro("l'intelligenza artificiale", scheda=True)
        miglioria = lavori.Lavoro("miglioramento", scheda=True)
        via = threading.Event()
        ia.parti(lambda: via.wait(5), "intelligenza")
        assert _aspetta(lambda: lavori.turno.chi is ia)
        miglioria.parti(lambda: None, "miglioramento")
        assert _aspetta(lambda: miglioria.numeri.get("in_attesa_della_scheda"))
        lavori.turno.rinunciano_tutti()
        assert miglioria.aspetta_che_finisca(5)
        via.set()


def test_i_pezzi_della_fila_ia_usano_il_suo_turno(monkeypatch):
    with monkeypatch.context() as m:
        m.setattr(lavori, "turno", lavori.TurnoDellaScheda())
        ia = lavori.Lavoro("l'intelligenza artificiale", scheda=True)
        volti = lavori.Lavoro("i volti", scheda=True)
        ia.figli = (volti,)
        fatti = []

        def fila():
            volti.parti(lambda: fatti.append("volti"), "volti")
            volti.aspetta_che_finisca(5)

        ia.parti(fila, "intelligenza")
        assert ia.aspetta_che_finisca(5)
        assert fatti == ["volti"]
        assert lavori.turno.chi is None


def test_i_lavori_senza_scheda_non_aspettano(monkeypatch):
    with monkeypatch.context() as m:
        m.setattr(lavori, "turno", lavori.TurnoDellaScheda())
        ia = lavori.Lavoro("l'intelligenza artificiale", scheda=True)
        copia = lavori.Lavoro("la copia")
        via = threading.Event()
        fatti = []
        ia.parti(lambda: via.wait(5), "intelligenza")
        assert _aspetta(lambda: lavori.turno.chi is ia)
        copia.parti(lambda: fatti.append(True), "copia")
        assert copia.aspetta_che_finisca(5)
        assert fatti == [True]
        via.set()


def test_la_fila_ia_e_il_miglioramento_usano_la_scheda():
    from officina.miglioria.lavoro import Miglioratore
    from officina.web.strade import comune

    assert comune.lavoro_ia.scheda
    assert set(comune.lavoro_ia.figli) == {comune.lavoro_impronte_passata, comune.lavoro_volti,
                                           comune.lavoro_corpi, comune.lavoro_parole}
    assert Miglioratore(archivio=None).lavoro.scheda
