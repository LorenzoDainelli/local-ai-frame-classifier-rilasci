from __future__ import annotations

import pytest

from officina.descrittori import torcia
from officina.errori import ErroreOfficina
from officina.modello import segnalazioni

FINITA = "CUDA out of memory. Tried to allocate 2.00 GiB"


class OutOfMemoryError(RuntimeError):
    pass


def _troppo_pesanti(archivio) -> int:
    with archivio.lettura() as connessione:
        return connessione.execute(
            "SELECT count(*) FROM segnalazioni WHERE dettaglio = ?",
            (torcia.TROPPO_PER_LA_MEMORIA,)).fetchone()[0]


def _segnate(archivio, tipo: str) -> int:
    with archivio.lettura() as connessione:
        return segnalazioni.quante(connessione, tipo)


@pytest.mark.parametrize("guasto", [
    OutOfMemoryError("qualcosa"),
    MemoryError(),
    RuntimeError(FINITA),
    RuntimeError("CUBLAS_STATUS_ALLOC_FAILED when calling cublasCreate"),
    RuntimeError("[ONNXRuntimeError] : 6 : RUNTIME_EXCEPTION : Failed to allocate memory for requested buffer"),
    RuntimeError("DefaultCPUAllocator: can't allocate memory: you tried to allocate 123 bytes"),
])
def test_la_memoria_finita_si_riconosce(guasto):
    assert torcia.memoria_finita(guasto)


@pytest.mark.parametrize("guasto", [None, RuntimeError("si è rotto"), ValueError("memoria"), KeyError("out")])
def test_gli_altri_guasti_non_sono_memoria_finita(guasto):
    assert not torcia.memoria_finita(guasto)


def test_il_conto_si_azzera_quando_uno_scatto_riesce(monkeypatch):
    monkeypatch.setattr(torcia, "libera", lambda: None)
    conto = torcia.ContoDellaMemoria(di_fila=3)
    conto.finita(1, RuntimeError(FINITA))
    conto.finita(2, RuntimeError(FINITA))
    assert conto.riuscito() == [1, 2]
    conto.finita(3, RuntimeError(FINITA))
    conto.finita(4, RuntimeError(FINITA))
    with pytest.raises(ErroreOfficina) as preso:
        conto.finita(5, RuntimeError(FINITA))
    assert preso.value.codice == "memoria_scheda_finita"
    assert isinstance(preso.value.__cause__, RuntimeError)


def test_la_memoria_finita_libera_la_scheda(monkeypatch):
    liberata = []
    monkeypatch.setattr(torcia, "libera", lambda: liberata.append(True))
    torcia.ContoDellaMemoria().finita(1, RuntimeError(FINITA))
    assert liberata == [True]


class VoltiSenzaMemoria:

    versione = "1"

    def __init__(self, finite_su=None):
        self.finite_su = finite_su
        self.chiamate = 0
        self.spento = False

    def guarda(self, immagine):
        self.chiamate += 1
        if self.finite_su is None or self.chiamate in self.finite_su:
            raise RuntimeError(FINITA)
        return []

    def spegni(self):
        self.spento = True


def test_i_volti_senza_memoria_si_fermano_e_non_segnano_niente(archivio_pieno):
    from officina.volti.motore import Passata

    finto = VoltiSenzaMemoria()
    passata = Passata(archivio_pieno, rilevatore=finto, intensita=100)
    prima = passata.quanti_mancano()
    assert prima > torcia.FINITE_DI_FILA
    with pytest.raises(ErroreOfficina) as preso:
        passata.esegui()
    assert preso.value.codice == "memoria_scheda_finita"
    assert finto.spento and finto.chiamate == torcia.FINITE_DI_FILA
    assert passata.quanti_mancano() == prima
    assert _segnate(archivio_pieno, segnalazioni.VOLTI_NON_LETTI) == 0


def test_uno_scatto_troppo_pesante_per_i_volti_si_segna_dopo(archivio_pieno):
    from officina.volti.motore import Passata

    passata = Passata(archivio_pieno, rilevatore=VoltiSenzaMemoria(finite_su={1}), intensita=100)
    fatto = passata.esegui()
    assert fatto.fatti == fatto.totale - 1
    assert _troppo_pesanti(archivio_pieno) == 1
    assert passata.quanti_mancano() == 0


def test_se_la_memoria_finisce_sull_ultimo_scatto_dei_volti_resta_da_fare(archivio_pieno):
    from officina.volti.motore import Passata

    passata = Passata(archivio_pieno, rilevatore=VoltiSenzaMemoria(), intensita=100)
    prima = passata.quanti_mancano()
    fatto = passata.esegui(quanti=1)
    assert fatto.fatti == 0
    assert passata.quanti_mancano() == prima
    assert _segnate(archivio_pieno, segnalazioni.VOLTI_NON_LETTI) == 0


def _corpi_finti():
    from prove.test_corpi import RilevatoreFinto

    class CorpiSenzaMemoria(RilevatoreFinto):

        def __init__(self, finite_su=None):
            super().__init__()
            self.finite_su = finite_su

        def guarda(self, immagine):
            if self.finite_su is None or self.visti + 1 in self.finite_su:
                self.visti += 1
                raise RuntimeError(FINITA)
            return super().guarda(immagine)

    return CorpiSenzaMemoria


def test_i_corpi_senza_memoria_si_fermano_e_non_segnano_niente(archivio_pieno):
    from officina.corpi.motore import Passata

    finto = _corpi_finti()()
    passata = Passata(archivio_pieno, rilevatore=finto, intensita=100)
    prima = passata.quanti_mancano()
    with pytest.raises(ErroreOfficina) as preso:
        passata.esegui()
    assert preso.value.codice == "memoria_scheda_finita"
    assert finto.spento and finto.visti == torcia.FINITE_DI_FILA
    assert passata.quanti_mancano() == prima
    assert _segnate(archivio_pieno, segnalazioni.CORPI_NON_LETTI) == 0


def test_uno_scatto_troppo_pesante_per_i_corpi_si_segna_dopo(archivio_pieno):
    from officina.corpi.motore import Passata

    passata = Passata(archivio_pieno, rilevatore=_corpi_finti()(finite_su={1}), intensita=100)
    fatto = passata.esegui()
    assert fatto.fatti == fatto.totale - 1
    assert _troppo_pesanti(archivio_pieno) == 1
    assert passata.quanti_mancano() == 0


def test_nella_passata_a_turni_la_memoria_finita_non_segna_niente(archivio_pieno):
    from officina.corpi.motore import Passata
    from prove.test_corpi_aspetto import RilevatoreATurni

    class SenzaMemoria(RilevatoreATurni):
        def completa(self, lotti, fermato=None):
            self.completati.append(len(lotti))
            return [RuntimeError(FINITA) for _ in lotti]

    passata = Passata(archivio_pieno, rilevatore=SenzaMemoria(), intensita=100)
    prima = passata.quanti_mancano()
    with pytest.raises(ErroreOfficina) as preso:
        passata.esegui()
    assert preso.value.codice == "memoria_scheda_finita"
    assert passata.quanti_mancano() == prima
    assert _segnate(archivio_pieno, segnalazioni.CORPI_NON_LETTI) == 0


def test_se_un_modello_del_corpo_non_entra_nella_memoria_lo_dice(archivio_pieno):
    import officina.corpi as corpi_pacchetto
    from officina.corpi.motore import Passata
    from prove.test_corpi_aspetto import RilevatoreATurni

    class NonEntra(RilevatoreATurni):
        def completa(self, lotti, fermato=None):
            try:
                raise RuntimeError(FINITA)
            except RuntimeError as guasto:
                raise corpi_pacchetto.NonSiAccende(str(guasto)) from guasto

    passata = Passata(archivio_pieno, rilevatore=NonEntra(), intensita=100)
    with pytest.raises(ErroreOfficina) as preso:
        passata.esegui()
    assert preso.value.codice == "memoria_scheda_finita"
    assert "memoria" in preso.value.messaggio


def test_i_punti_rifatti_senza_memoria_restano_da_rifare(archivio_pieno):
    from officina.corpi import motore
    from officina.corpi.motore import Passata
    from prove.test_corpi import RilevatoreFinto

    class PuntiSenzaMemoria(RilevatoreFinto):
        def punti_di(self, immagine, riquadri):
            raise RuntimeError(FINITA)

    Passata(archivio_pieno, rilevatore=RilevatoreFinto(), intensita=100).esegui()
    with archivio_pieno.scrittura() as connessione:
        connessione.execute("UPDATE corpi SET punti_scala = 1")
        prima = motore.quanti_da_ripuntare_senza_aprire(connessione)
    finto = PuntiSenzaMemoria()
    with pytest.raises(ErroreOfficina):
        Passata(archivio_pieno, rilevatore=finto, intensita=100).rifai_i_punti()
    assert finto.spento
    with archivio_pieno.lettura() as connessione:
        assert motore.quanti_da_ripuntare_senza_aprire(connessione) == prima
    assert _segnate(archivio_pieno, segnalazioni.CORPI_NON_LETTI) == 0


def _figure_finte(**parole):
    from prove.test_figure import FigureFinte

    class FigureSenzaMemoria(FigureFinte):

        def __init__(self, finite_su=None, lente_finita_su=(), lente_rotta=False, **altro):
            super().__init__(**altro)
            self.finite_su = finite_su
            self.lente_finita_su = set(lente_finita_su)
            self.lente_rotta = lente_rotta
            self.stime = 0

        def stima(self, immagine):
            self.stime += 1
            if self.stime in self.lente_finita_su:
                raise RuntimeError(FINITA)
            if self.lente_rotta:
                raise ValueError("la lente non si stima")
            return super().stima(immagine)

        def ricostruisci(self, pixel, riquadri, intere, fuoco):
            if self.finite_su is None or self.chiamate + 1 in self.finite_su:
                self.chiamate += 1
                raise RuntimeError(FINITA)
            return super().ricostruisci(pixel, riquadri, intere, fuoco)

    return FigureSenzaMemoria(**parole)


def test_le_figure_senza_memoria_si_fermano_e_non_segnano_niente(archivio_pieno):
    from officina.corpi import figure
    from prove.test_figure import _con_i_corpi

    _con_i_corpi(archivio_pieno)
    finte = _figure_finte()
    passata = figure.Passata(archivio_pieno, figure=finte)
    prima = passata.quanti_mancano()
    with pytest.raises(ErroreOfficina) as preso:
        passata.esegui()
    assert preso.value.codice == "memoria_scheda_finita"
    assert finte.spente >= 1 and finte.chiamate == torcia.FINITE_DI_FILA
    assert passata.quanti_mancano() == prima
    assert _segnate(archivio_pieno, segnalazioni.FIGURE_NON_FATTE) == 0


def test_una_figura_troppo_pesante_si_segna_dopo(archivio_pieno):
    from officina.corpi import figure
    from prove.test_figure import _con_i_corpi

    _con_i_corpi(archivio_pieno)
    passata = figure.Passata(archivio_pieno, figure=_figure_finte(finite_su={1}))
    fatto = passata.esegui()
    assert fatto.fatti == fatto.totale - 1
    assert _troppo_pesanti(archivio_pieno) == 1
    assert passata.quanti_mancano() == 0


def test_se_puffin_si_rompe_si_usa_la_lente_di_base_e_si_va_avanti(archivio_pieno):
    from officina.corpi import figure
    from prove.test_figure import _con_i_corpi

    _con_i_corpi(archivio_pieno)
    passata = figure.Passata(archivio_pieno, figure=_figure_finte(finite_su=set(), lente_rotta=True))
    totale = passata.quanti_mancano()
    fatto = passata.esegui()
    assert fatto.fatti == totale and fatto.saltati == 0
    with archivio_pieno.lettura() as connessione:
        fonti = {r["fonte"] for r in connessione.execute("SELECT fonte FROM obiettivi")}
    assert fonti <= {figure.BASE, figure.EXIF}
    assert passata.quanti_mancano() == 0


def test_se_puffin_finisce_la_memoria_lo_scatto_resta_da_fare_o_si_segna_dopo(archivio_pieno):
    from officina.corpi import figure
    from prove.test_figure import _con_i_corpi

    _con_i_corpi(archivio_pieno)
    passata = figure.Passata(archivio_pieno, figure=_figure_finte(finite_su=set(), lente_finita_su={1}))
    fatto = passata.esegui()
    assert fatto.fatti == fatto.totale - 1
    assert _troppo_pesanti(archivio_pieno) == 1
    with archivio_pieno.lettura() as connessione:
        assert connessione.execute("SELECT count(*) FROM obiettivi").fetchone()[0] == fatto.totale - 1


def test_se_le_figure_non_entrano_nella_memoria_lo_dice(archivio_pieno):
    from officina.corpi import figure
    from prove.test_figure import _con_i_corpi

    class NonEntra(type(_figure_finte())):
        def accendi_il_corpo(self):
            raise RuntimeError(FINITA)

    _con_i_corpi(archivio_pieno)
    passata = figure.Passata(archivio_pieno, figure=NonEntra(finite_su=set()))
    prima = passata.quanti_mancano()
    with pytest.raises(ErroreOfficina) as preso:
        passata.esegui()
    assert preso.value.codice == "memoria_scheda_finita"
    assert passata.quanti_mancano() == prima
    assert _segnate(archivio_pieno, segnalazioni.FIGURE_NON_FATTE) == 0


def test_se_le_figure_non_si_accendono_nessuno_scatto_viene_segnato(archivio_pieno):
    from officina.corpi import figure
    from prove.test_figure import _con_i_corpi

    class NonSiAccende(type(_figure_finte())):
        def accendi_la_lente(self):
            raise RuntimeError("la scheda video non risponde")

    _con_i_corpi(archivio_pieno)
    passata = figure.Passata(archivio_pieno, figure=NonSiAccende(finite_su=set()))
    prima = passata.quanti_mancano()
    with pytest.raises(ErroreOfficina) as preso:
        passata.esegui()
    assert preso.value.codice == "figure_non_si_accendono"
    assert passata.quanti_mancano() == prima
    assert _segnate(archivio_pieno, segnalazioni.FIGURE_NON_FATTE) == 0


def _pelle_finta(finite_su=None):
    from prove.test_superfici import PelleFinta

    class PelleSenzaMemoria(PelleFinta):
        def vertici(self, forme, parametri):
            if finite_su is None or self.chiamate + 1 in finite_su:
                self.chiamate += 1
                raise RuntimeError(FINITA)
            return super().vertici(forme, parametri)

    return PelleSenzaMemoria()


def test_le_superfici_senza_memoria_si_fermano_e_non_segnano_niente(archivio_pieno):
    from officina.corpi import superfici
    from prove.test_superfici import _con_le_figure

    _con_le_figure(archivio_pieno)
    pelle = _pelle_finta()
    passata = superfici.Passata(archivio_pieno, pelle=pelle)
    prima = passata.quanti_mancano()
    with pytest.raises(ErroreOfficina) as preso:
        passata.esegui()
    assert preso.value.codice == "memoria_scheda_finita"
    assert pelle.spenta == 1 and pelle.chiamate == torcia.FINITE_DI_FILA
    assert passata.quanti_mancano() == prima
    with archivio_pieno.lettura() as connessione:
        assert connessione.execute("SELECT count(*) FROM superfici").fetchone()[0] == 0


def test_una_superficie_troppo_pesante_si_segna_dopo(archivio_pieno):
    from officina.corpi import superfici
    from prove.test_superfici import _con_le_figure

    _con_le_figure(archivio_pieno)
    passata = superfici.Passata(archivio_pieno, pelle=_pelle_finta(finite_su={1}))
    fatto = passata.esegui()
    assert fatto.saltati == 1
    assert passata.quanti_mancano() == 0
    with archivio_pieno.lettura() as connessione:
        assert connessione.execute("SELECT count(*) FROM superfici WHERE vertici = 0").fetchone()[0] > 0
