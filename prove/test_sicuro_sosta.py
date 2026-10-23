from __future__ import annotations

import copy
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from officina import registro
from officina.archivio import accesso
from officina.errori import ArchivioChiuso, ErroreOfficina
from officina.programma import archivio_sicuro, avvio, carta
from officina.sicuro.custode import COPIA
from officina.sicuro.sottofondo import SPAZIO_FINITO
from officina.web import blocco, coda_ritocco, in_disparte, in_prova, sosta
from officina.web import miglioramento as miglioramento_web
from officina.web.sosta import GARA, IA, MIGLIORAMENTO, NOMI, ORDINE, RITOCCO, Sosta
from officina.web.strade import comune, generale, intelligenza
from officina.web.strade import miglioramento as strade_miglioramento
from officina.web.strade import ritocco as strade_ritocco
from prove import test_programma_finestre as finestre
from prove import test_sicuro_custode as custode_di_prova
from prove import test_sicuro_nel_programma as nel_programma
from prove import test_sicuro_servizio as servizio_di_prova
from prove.test_sicuro_copia import _dati
from prove.test_sicuro_servizio import ATTESA, _finche

posto = nel_programma.posto
forziere_leggero = nel_programma.forziere_leggero
costo_leggero = servizio_di_prova.costo_leggero
casa = finestre.casa
Scena = custode_di_prova.Scena
_parte = custode_di_prova._parte

REALE = "reale"
CHIUSO = ArchivioChiuso("L'archivio non è aperto.")


@pytest.fixture
def scritti(monkeypatch):
    visti: list[tuple[str, str, dict]] = []
    for livello in ("evento", "avviso", "errore"):
        def scrivi(codice, livello=livello, **dati):
            visti.append((livello, codice, dati))
        monkeypatch.setattr(registro, livello, scrivi)
    return visti


def _codici(scritti, livello: str | None = None) -> list[str]:
    return [codice for quale, codice, _ in scritti if livello in (None, quale)]


class Finto:

    def __init__(self, carta_finta):
        self.carta = carta_finta
        self.acceso_ora = False
        self.la_memoria: dict = {}
        self.fermato = 0
        self.ripartiti: list[tuple] = []
        self.rotto: dict[str, BaseException] = {}
        self.vista_alla_fermata = "mai"
        self.alla_ripartenza = None
        self.porta: threading.Event | None = None
        self.entrato = threading.Event()

    def _rompi(self, quale: str) -> None:
        guasto = self.rotto.get(quale)
        if guasto is not None:
            raise guasto

    def acceso(self) -> bool:
        self._rompi("acceso")
        return self.acceso_ora

    def memoria(self) -> dict:
        self._rompi("memoria")
        return copy.deepcopy(self.la_memoria)

    def ferma(self) -> None:
        self.entrato.set()
        if self.porta is not None:
            self.porta.wait(ATTESA)
        self._rompi("ferma")
        self.vista_alla_fermata = copy.deepcopy(self.carta.scritta)
        self.fermato += 1
        self.acceso_ora = False

    def riparti(self, archivio, memoria: dict) -> None:
        if self.alla_ripartenza is not None:
            self.alla_ripartenza()
        self._rompi("riparti")
        self.ripartiti.append((archivio, copy.deepcopy(memoria)))
        self.acceso_ora = True


class CartaFinta:

    def __init__(self, scritta=None):
        self.scritta = copy.deepcopy(scritta)
        self.scritture: list = []
        self.rotta_a_leggere: BaseException | None = None
        self.rotta_a_scrivere: BaseException | None = None
        self.letture = 0

    def leggi(self):
        self.letture += 1
        if self.rotta_a_leggere is not None:
            raise self.rotta_a_leggere
        return copy.deepcopy(self.scritta)

    def scrivi(self, valore) -> None:
        if self.rotta_a_scrivere is not None:
            raise self.rotta_a_scrivere
        self.scritture.append(copy.deepcopy(valore))
        self.scritta = copy.deepcopy(valore)


def _archivio(nome: str = REALE, di_prova: bool = False):
    return SimpleNamespace(dove=SimpleNamespace(nome=nome), di_prova=di_prova)


class Banco:

    def __init__(self, scritta=None, carta_finta: CartaFinta | None = None, **opzioni):
        self.carta = carta_finta or CartaFinta(scritta)
        self.lavori = {nome: Finto(self.carta) for nome in ORDINE}
        self.archivio = _archivio()
        self.chiuso: BaseException | None = None
        self.guardato = 0
        self.risposta = None
        self.chieste = 0
        self.prima_di_rispondere = None
        self.sosta = Sosta(self.lavori, leggi=self.carta.leggi, scrivi=self.carta.scrivi,
                           archivio=self._l_archivio, **opzioni)
        self.sosta._serve = self.serve

    def _l_archivio(self):
        self.guardato += 1
        if self.chiuso is not None:
            raise self.chiuso
        return self.archivio

    def serve(self):
        self.chieste += 1
        if self.prima_di_rispondere is not None:
            self.prima_di_rispondere()
        if isinstance(self.risposta, BaseException):
            raise self.risposta
        return self.risposta

    def giro(self, risposta) -> None:
        self.risposta = risposta
        self.sosta.giro()

    def accendi(self, *nomi, **memorie) -> None:
        for nome in nomi:
            self.lavori[nome].acceso_ora = True
        for nome, memoria in memorie.items():
            self.lavori[nome].la_memoria = memoria

    def fermati(self) -> list[str]:
        return [nome for nome in ORDINE if self.lavori[nome].fermato]

    def ripartiti(self) -> dict[str, list]:
        return {nome: [memoria for _, memoria in self.lavori[nome].ripartiti]
                for nome in ORDINE if self.lavori[nome].ripartiti}


@pytest.fixture
def banchi():
    fatti: list[Banco] = []

    def fai(*argomenti, **opzioni) -> Banco:
        fatti.append(Banco(*argomenti, **opzioni))
        return fatti[-1]

    yield fai
    for fatto in fatti:
        fatto.sosta.smetti(ATTESA)


@pytest.fixture
def banco(banchi):
    return banchi()


def test_senza_la_prima_copia_i_lavori_partono_subito(banco, scritti):
    assert not banco.sosta.attiva
    assert banco.sosta.aspetta(IA, scelti=["volti"]) is False
    assert banco.sosta.in_attesa() == []
    assert not banco.sosta.aspetta_la_copia(IA)
    assert banco.carta.scritture == []
    assert scritti == []


def test_durante_la_prima_copia_si_fermano_solo_quelli_accesi(banco, scritti):
    banco.accendi(IA, RITOCCO, ia={"scelti": ["volti", "corpi"]})
    banco.giro(True)
    assert banco.sosta.attiva
    assert banco.fermati() == [IA, RITOCCO]
    attesa = {"dove": REALE, "lavori": {IA: {"scelti": ["volti", "corpi"]}, RITOCCO: {}}}
    assert banco.carta.scritta == attesa
    assert banco.sosta.in_attesa() == [IA, RITOCCO]
    assert banco.sosta.aspetta_la_copia(RITOCCO) and not banco.sosta.aspetta_la_copia(GARA)
    assert _codici(scritti) == ["sosta.comincia", "sosta.fermato", "sosta.fermato"]
    assert [dati["lavoro"] for _, _, dati in scritti[1:]] == [IA, RITOCCO]
    assert all(isinstance(dati["lavoro"], registro.Parola) for _, _, dati in scritti[1:])


def test_prima_si_scrive_nella_carta_e_poi_si_ferma(banco):
    banco.accendi(IA, MIGLIORAMENTO, ia={"scelti": ["volti"]})
    banco.giro(True)
    assert banco.lavori[IA].vista_alla_fermata == {
        "dove": REALE, "lavori": {IA: {"scelti": ["volti"]}}}
    assert banco.lavori[MIGLIORAMENTO].vista_alla_fermata == {
        "dove": REALE, "lavori": {IA: {"scelti": ["volti"]}, MIGLIORAMENTO: {}}}


def test_alla_fine_della_copia_ripartono_solo_quelli_fermati(banco, scritti):
    banco.accendi(IA, GARA, ia={"scelti": ["volti"]})
    banco.giro(True)
    banco.giro(True)
    assert banco.fermati() == [IA, GARA]
    assert banco.lavori[IA].fermato == 1
    del scritti[:]
    banco.giro(False)
    assert not banco.sosta.attiva
    assert banco.ripartiti() == {IA: [{"scelti": ["volti"]}], GARA: [{}]}
    assert all(archivio is banco.archivio
               for lavoro in banco.lavori.values() for archivio, _ in lavoro.ripartiti)
    assert banco.carta.scritta is None
    assert banco.sosta.in_attesa() == []
    assert _codici(scritti) == ["sosta.finita", "sosta.ripartito", "sosta.ripartito"]
    banco.giro(False)
    assert banco.ripartiti() == {IA: [{"scelti": ["volti"]}], GARA: [{}]}
    assert _codici(scritti) == ["sosta.finita", "sosta.ripartito", "sosta.ripartito"]


def test_se_non_si_sa_non_si_cambia_niente(banco, scritti):
    banco.accendi(IA)
    banco.giro(None)
    assert banco.fermati() == [] and not banco.sosta.attiva
    banco.giro(True)
    banco.giro(None)
    assert banco.sosta.attiva and banco.ripartiti() == {}
    assert banco.sosta.in_attesa() == [IA]
    assert _codici(scritti) == ["sosta.comincia", "sosta.fermato"]


def test_chi_parte_durante_la_copia_aspetta_e_parte_dopo(banco, scritti):
    banco.giro(True)
    assert banco.sosta.aspetta(IA, scelti=["scritte"]) is True
    assert banco.sosta.aspetta(GARA) is True
    assert banco.sosta.in_attesa() == [IA, GARA]
    assert banco.carta.scritta == {"dove": REALE,
                                   "lavori": {IA: {"scelti": ["scritte"]}, GARA: {}}}
    assert _codici(scritti) == ["sosta.comincia", "sosta.in_attesa", "sosta.in_attesa"]
    banco.giro(False)
    assert banco.ripartiti() == {IA: [{"scelti": ["scritte"]}], GARA: [{}]}


def test_chi_aspetta_due_volte_tiene_l_ultima_scelta(banco):
    banco.giro(True)
    banco.sosta.aspetta(IA, scelti=["volti"])
    banco.sosta.aspetta(IA, scelti=["corpi"])
    banco.giro(False)
    assert banco.ripartiti() == {IA: [{"scelti": ["corpi"]}]}


def test_se_lo_fermi_tu_non_riparte_dopo_la_copia(banco):
    banco.accendi(IA, RITOCCO)
    banco.giro(True)
    banco.sosta.fermato_da_te(IA)
    assert banco.sosta.in_attesa() == [RITOCCO]
    assert banco.carta.scritta == {"dove": REALE, "lavori": {RITOCCO: {}}}
    banco.sosta.fermato_da_te(RITOCCO)
    assert banco.carta.scritta is None
    banco.giro(False)
    assert banco.ripartiti() == {}


def test_fermare_chi_non_aspetta_non_scrive_niente(banco):
    banco.sosta.fermato_da_te(MIGLIORAMENTO)
    assert banco.carta.scritture == []


def test_chi_stai_fermando_tu_non_lo_fermo_e_non_lo_ricordo(banco):
    banco.accendi(IA)
    banco.sosta.fermato_da_te(IA)
    banco.giro(True)
    assert banco.fermati() == [] and banco.sosta.in_attesa() == []
    banco.lavori[IA].acceso_ora = False
    banco.giro(True)
    banco.accendi(IA)
    banco.giro(True)
    assert banco.fermati() == [IA] and banco.sosta.in_attesa() == [IA]


def test_a_chi_e_spento_non_si_chiede_a_che_punto_e(banco, scritti):
    banco.lavori[IA].rotto["memoria"] = RuntimeError("non andava chiesto")
    banco.sosta.fermato_da_te(IA)
    banco.giro(True)
    assert _codici(scritti) == ["sosta.comincia"]
    del banco.lavori[IA].rotto["memoria"]
    banco.accendi(IA)
    banco.giro(True)
    assert banco.fermati() == [IA] and banco.sosta.in_attesa() == [IA]


def test_la_memoria_ricordata_non_cambia_se_il_lavoro_cambia_la_sua(banco):
    sua = {"scelti": ["volti"]}
    banco.lavori[IA].memoria = lambda: sua
    banco.accendi(IA)
    banco.giro(True)
    sua["scelti"] = ["corpi"]
    banco.giro(False)
    assert banco.ripartiti() == {IA: [{"scelti": ["volti"]}]}


def test_se_lo_rifai_partire_tu_torna_a_contare(banco):
    banco.accendi(GARA)
    banco.sosta.fermato_da_te(GARA)
    banco.giro(True)
    assert banco.sosta.aspetta(GARA) is True
    banco.giro(True)
    assert banco.fermati() == [GARA]
    banco.sosta.fermato_da_te(GARA)
    assert banco.sosta.aspetta(GARA, cosa=1) is True
    assert banco.sosta.in_attesa() == [GARA]


def test_la_memoria_resta_anche_se_chiudi_il_programma(banco):
    banco.accendi(IA, MIGLIORAMENTO, ia={"scelti": ["impronte"]})
    banco.giro(True)
    dopo = Banco(carta_finta=banco.carta)
    try:
        assert dopo.sosta.in_attesa() == [IA, MIGLIORAMENTO]
        assert dopo.sosta.aspetta_la_copia(MIGLIORAMENTO)
        dopo.giro(False)
        assert dopo.ripartiti() == {IA: [{"scelti": ["impronte"]}], MIGLIORAMENTO: [{}]}
        assert dopo.carta.scritta is None
    finally:
        dopo.sosta.smetti(ATTESA)


def test_la_carta_si_legge_una_volta_sola(banco):
    banco.sosta.in_attesa()
    banco.sosta.in_attesa()
    banco.giro(False)
    assert banco.carta.letture == 1


def test_su_un_altro_archivio_non_riparte_niente(banco, scritti):
    banco.accendi(IA, RITOCCO)
    banco.giro(True)
    banco.archivio = _archivio("altro")
    del scritti[:]
    banco.giro(False)
    assert banco.ripartiti() == {}
    assert banco.carta.scritta is None and banco.sosta.in_attesa() == []
    assert ("avviso", "sosta.archivio_cambiato", {"quanti": 2}) in scritti


def test_senza_sapere_l_archivio_non_riparte_niente(scritti):
    banco = Banco({"dove": None, "lavori": {GARA: {}}})
    banco.archivio = SimpleNamespace(di_prova=False)
    assert banco.sosta.in_attesa() == [GARA]
    banco.giro(False)
    assert banco.ripartiti() == {}
    assert banco.carta.scritta is None
    assert "sosta.archivio_cambiato" in _codici(scritti, "avviso")


def test_ad_archivio_chiuso_la_memoria_resta_e_si_riprova(banco):
    banco.accendi(IA)
    banco.giro(True)
    banco.chiuso = CHIUSO
    banco.giro(False)
    assert banco.ripartiti() == {} and banco.sosta.in_attesa() == [IA]
    assert banco.carta.scritta == {"dove": REALE, "lavori": {IA: {}}}
    banco.chiuso = None
    banco.giro(False)
    assert banco.ripartiti() == {IA: [{}]}


def test_senza_niente_da_rifare_l_archivio_non_si_guarda(banco):
    banco.giro(False)
    assert banco.guardato == 0 and banco.ripartiti() == {}


def test_un_lavoro_che_non_riparte_non_ferma_gli_altri(banco, scritti):
    banco.accendi(IA, MIGLIORAMENTO, RITOCCO)
    banco.giro(True)
    banco.lavori[MIGLIORAMENTO].rotto["riparti"] = ErroreOfficina("Manca SeedVR2.")
    banco.giro(False)
    assert banco.ripartiti() == {IA: [{}], RITOCCO: [{}]}
    assert banco.sosta.in_attesa() == []
    rotti = [dati for livello, codice, dati in scritti if codice == "sosta.non_ripartito"]
    assert len(rotti) == 1 and rotti[0]["lavoro"] == MIGLIORAMENTO
    assert _codici(scritti, "evento").count("sosta.ripartito") == 2
    banco.giro(False)
    assert banco.lavori[MIGLIORAMENTO].ripartiti == []


def test_un_lavoro_che_non_si_ferma_resta_ricordato_e_gli_altri_si_fermano(banco, scritti):
    banco.accendi(IA, RITOCCO)
    banco.lavori[IA].rotto["ferma"] = RuntimeError("non si ferma")
    banco.giro(True)
    assert banco.fermati() == [RITOCCO]
    assert banco.sosta.in_attesa() == [IA, RITOCCO]
    assert _codici(scritti, "errore") == ["sosta.non_fermato"]
    assert _codici(scritti, "evento") == ["sosta.comincia", "sosta.fermato"]


@pytest.mark.parametrize("quale", ["acceso", "memoria"])
def test_un_lavoro_che_non_si_lascia_guardare_si_salta(banco, scritti, quale):
    banco.accendi(IA, GARA)
    banco.lavori[IA].rotto[quale] = RuntimeError("non si guarda")
    banco.giro(True)
    assert banco.fermati() == [GARA] and banco.sosta.in_attesa() == [GARA]
    assert _codici(scritti, "errore") == ["sosta.non_guardato"]


def test_se_non_so_se_serve_non_faccio_niente(banco, scritti):
    banco.accendi(IA)
    banco.giro(RuntimeError("non so"))
    assert banco.fermati() == [] and not banco.sosta.attiva
    assert _codici(scritti) == ["sosta.non_so"]


def test_se_la_carta_non_si_scrive_la_memoria_resta(banco, scritti):
    banco.carta.rotta_a_scrivere = OSError("carta in sola lettura")
    banco.accendi(IA)
    banco.giro(True)
    assert banco.fermati() == [IA] and banco.sosta.in_attesa() == [IA]
    assert "sosta.non_salvata" in _codici(scritti, "avviso")
    banco.giro(False)
    assert banco.ripartiti() == {IA: [{}]}


def test_nella_carta_contano_solo_i_lavori_che_conosco():
    banco = Banco({"dove": REALE, "lavori": {"boh": {}}})
    banco.giro(False)
    assert banco.guardato == 0 and banco.carta.scritture == []


def test_una_carta_che_non_si_legge_vale_vuota(scritti):
    carta_rotta = CartaFinta({"dove": REALE, "lavori": {IA: {}}})
    carta_rotta.rotta_a_leggere = OSError("non si legge")
    banco = Banco(carta_finta=carta_rotta)
    assert banco.sosta.in_attesa() == []
    assert _codici(scritti) == ["sosta.non_letta"]


@pytest.mark.parametrize("scritta, attesi, dove", [
    ("boh", [], None),
    (["ia"], [], None),
    ({"lavori": "tutti"}, [], None),
    ({"dove": 3, "lavori": {IA: {"scelti": ["volti"]}}}, [IA], None),
    ({"dove": REALE, "lavori": {"boh": {}, RITOCCO: 5, GARA: {}, IA: []}}, [GARA], REALE),
])
def test_una_carta_strana_si_legge_con_prudenza(scritta, attesi, dove):
    banco = Banco(scritta)
    assert banco.sosta.in_attesa() == attesi
    banco.giro(False)
    assert banco.ripartiti() == ({nome: [{}] for nome in attesi} if dove else {})


def test_se_cambia_l_archivio_la_memoria_vecchia_si_lascia(banco, scritti):
    banco.accendi(IA)
    banco.giro(True)
    banco.archivio = _archivio("altro")
    assert banco.sosta.aspetta(RITOCCO) is True
    assert banco.carta.scritta == {"dove": "altro", "lavori": {RITOCCO: {}}}
    assert ("avviso", "sosta.archivio_cambiato", {"quanti": 1}) in scritti
    banco.giro(False)
    assert banco.ripartiti() == {RITOCCO: [{}]}


def test_se_l_archivio_non_si_vede_la_memoria_non_si_perde(banco):
    banco.accendi(IA)
    banco.giro(True)
    banco.chiuso = CHIUSO
    assert banco.sosta.aspetta(GARA) is True
    assert banco.carta.scritta == {"dove": REALE, "lavori": {IA: {}, GARA: {}}}


def test_ad_archivio_chiuso_dall_inizio_non_si_sa_dove_e_non_riparte(banco):
    banco.chiuso = CHIUSO
    banco.giro(True)
    banco.sosta.aspetta(IA)
    assert banco.carta.scritta == {"dove": None, "lavori": {IA: {}}}
    banco.chiuso = None
    banco.giro(False)
    assert banco.ripartiti() == {}


def test_nomi_che_non_conosco(banco):
    with pytest.raises(ValueError):
        banco.sosta.aspetta("boh")
    with pytest.raises(ValueError):
        banco.sosta.fermato_da_te("boh")
    assert banco.carta.scritture == []


def test_si_fermano_dice_chi_si_fermerebbe(banco, scritti):
    assert banco.sosta.si_fermano() == []
    banco.accendi(IA, RITOCCO, GARA)
    banco.lavori[RITOCCO].rotto["acceso"] = RuntimeError("non si guarda")
    assert banco.sosta.si_fermano() == [NOMI[IA], NOMI[GARA]]
    assert _codici(scritti) == ["sosta.non_guardato"]
    assert banco.fermati() == []


def test_i_nomi_si_possono_dire():
    assert set(NOMI) == set(ORDINE) and len(ORDINE) == len(set(ORDINE)) == 11
    assert ORDINE[0] == IA
    assert NOMI[GARA] == "la gara dei video"
    assert sosta.ASPETTA_LA_COPIA.format(chi=NOMI[IA]) == (
        "L'Archivio sicuro sta facendo la prima copia: l'intelligenza artificiale parte "
        "appena la copia è finita.")


def test_smettere_mentre_chiedo_non_cambia_niente(banco):
    banco.accendi(IA)
    banco.prima_di_rispondere = lambda: banco.sosta.smetti(0)
    banco.giro(True)
    assert banco.fermati() == [] and not banco.sosta.attiva
    banco.prima_di_rispondere = None
    banco.giro(True)
    assert banco.chieste == 1


def test_smettere_mentre_ripartono_rimette_gli_altri_nella_carta(banco):
    banco.accendi(IA, MIGLIORAMENTO, RITOCCO, GARA, ia={"scelti": ["volti"]})
    banco.giro(True)

    def chiudi():
        banco.sosta.fermato_da_te(RITOCCO)
        banco.sosta.smetti(0)

    banco.lavori[IA].alla_ripartenza = chiudi
    banco.giro(False)
    assert banco.ripartiti() == {IA: [{"scelti": ["volti"]}]}
    assert banco.carta.scritta == {"dove": REALE, "lavori": {MIGLIORAMENTO: {}, GARA: {}}}
    dopo = Banco(carta_finta=banco.carta)
    assert dopo.sosta.in_attesa() == [MIGLIORAMENTO, GARA]


def test_smettere_mentre_ripartono_su_un_archivio_nuovo_lo_dice(banco, scritti):
    banco.accendi(IA, GARA)
    banco.giro(True)

    def riapri():
        banco.archivio = _archivio("altro")
        banco.sosta.guarda(banco.serve, attiva=True)
        assert banco.sosta.aspetta(RITOCCO)
        banco.sosta.smetti(0)

    banco.lavori[IA].alla_ripartenza = riapri
    banco.giro(False)
    assert banco.carta.scritta == {"dove": "altro", "lavori": {RITOCCO: {}}}
    assert ("avviso", "sosta.archivio_cambiato", {"quanti": 1}) in scritti


def test_guarda_con_la_prima_copia_segnata_fa_aspettare_subito(banco):
    banco.risposta = None
    banco.sosta.guarda(banco.serve, attiva=True)
    assert banco.sosta.attiva
    assert banco.sosta.aspetta(MIGLIORAMENTO) is True
    _finche(lambda: banco.chieste >= 1)
    assert banco.sosta.attiva


def test_il_filo_guarda_da_solo_e_smette(banchi):
    banco = banchi(ogni=60.0)
    banco.accendi(IA)
    banco.risposta = True
    banco.sosta.guarda(banco.serve)
    filo = banco.sosta._filo
    assert filo.name == "sosta-per-la-copia" and filo.daemon
    _finche(lambda: banco.fermati() == [IA])
    banco.risposta = False
    banco.sosta.subito()
    _finche(lambda: banco.ripartiti() == {IA: [{}]})
    assert banco.sosta.smetti(ATTESA)
    assert not filo.is_alive()
    chieste = banco.chieste
    banco.risposta = True
    banco.sosta.giro()
    assert banco.chieste == chieste and banco.fermati() == [IA]


def test_guarda_due_volte_fa_un_filo_solo_e_usa_la_domanda_nuova(banchi):
    banco = banchi(ogni=60.0)
    banco.risposta = None
    banco.sosta.guarda(banco.serve)
    filo = banco.sosta._filo
    _finche(lambda: banco.chieste >= 1)
    altre = []
    banco.sosta.guarda(lambda: altre.append(1))
    assert banco.sosta._filo is filo
    _finche(lambda: altre)
    assert banco.sosta._filo is filo and filo.is_alive()


def test_dopo_smetti_si_puo_ricominciare(banco):
    banco.risposta = None
    banco.sosta.guarda(banco.serve)
    primo = banco.sosta._filo
    assert banco.sosta.smetti(ATTESA)
    banco.accendi(GARA)
    banco.risposta = True
    banco.sosta.guarda(banco.serve)
    assert banco.sosta._filo is not primo
    _finche(lambda: banco.fermati() == [GARA])


def test_se_smetti_non_fa_in_tempo_il_filo_vecchio_serve_la_guardia_nuova(banchi):
    banco = banchi(ogni=60.0)
    porta = threading.Event()
    banco.accendi(IA)
    banco.lavori[IA].porta = porta
    banco.risposta = True
    banco.sosta.guarda(banco.serve)
    filo = banco.sosta._filo
    assert banco.lavori[IA].entrato.wait(ATTESA)
    assert banco.sosta.smetti(0.01) is False
    nuove = []
    banco.sosta.guarda(lambda: nuove.append(1))
    porta.set()
    _finche(lambda: nuove)
    assert banco.sosta._filo is filo and filo.is_alive()


def test_smetti_dal_filo_stesso_non_lo_aspetta(banchi):
    banco = banchi(ogni=60.0)
    risposte = []
    banco.sosta.guarda(lambda: risposte.append(banco.sosta.smetti(ATTESA)))
    _finche(lambda: risposte)
    assert risposte == [False]
    _finche(lambda: banco.sosta._filo is None)


def test_smetti_senza_filo_va_bene():
    assert Sosta(leggi=lambda: None, scrivi=lambda valore: None).smetti(0)


def test_un_giro_rotto_non_ferma_il_filo(banchi, scritti):
    banco = banchi(ogni=0.005)
    del banco.lavori[GARA]
    banco.risposta = True
    banco.sosta.guarda(banco.serve)
    _finche(lambda: banco.chieste >= 3)
    assert "sosta.giro_rotto" in _codici(scritti, "errore")
    assert banco.sosta.smetti(ATTESA)


def test_di_serie_la_sosta_guarda_i_lavori_veri(monkeypatch):
    monkeypatch.setattr(comune, "lavoro_ia", SimpleNamespace(sta_lavorando=False))
    monkeypatch.setattr(miglioramento_web, "_miglioratore", None)
    monkeypatch.setattr(coda_ritocco, "_ritoccatore", None)
    monkeypatch.setattr(coda_ritocco, "_gara", None)
    nuova = Sosta(leggi=lambda: None, scrivi=lambda valore: None)
    assert nuova.si_fermano() == []
    monkeypatch.setattr(coda_ritocco, "_gara", _con_lavoro(True))
    assert nuova.si_fermano() == [NOMI[GARA]]
    assert isinstance(sosta.per_la_copia, Sosta)


def _con_lavoro(acceso: bool):
    fermate = []
    return SimpleNamespace(lavoro=SimpleNamespace(sta_lavorando=acceso),
                           sta_lavorando=acceso, fermate=fermate,
                           ferma=lambda aspetta=0.0: fermate.append(aspetta))


def test_di_serie_ci_sono_tutti():
    di_serie = sosta._di_serie()
    assert list(di_serie) == list(ORDINE)
    assert [type(lavoro).__name__ for lavoro in di_serie.values()] == [
        "_Ia", *["_DaSolo"] * 7, "_Miglioramento", "_Ritocco", "_Gara"]


def test_l_intelligenza_si_guarda_si_ferma_e_riparte(monkeypatch):
    lavoro = sosta._Ia()
    monkeypatch.setattr(comune, "lavoro_ia", SimpleNamespace(sta_lavorando=True))
    monkeypatch.setitem(comune.fila_ia, "scelti", ["volti", "corpi"])
    assert lavoro.acceso() is True
    memoria = lavoro.memoria()
    assert memoria == {"scelti": ["volti", "corpi"]}
    memoria["scelti"].append("x")
    assert comune.fila_ia["scelti"] == ["volti", "corpi"]
    chiamate = []
    monkeypatch.setattr(intelligenza, "ferma_la_fila", lambda: chiamate.append("ferma"))
    monkeypatch.setattr(intelligenza, "parti_la_fila",
                        lambda archivio, scelti: chiamate.append((archivio, scelti)))
    lavoro.ferma()
    lavoro.riparti("archivio", {"scelti": ["volti"]})
    lavoro.riparti("archivio", {})
    assert chiamate == ["ferma", ("archivio", ["volti"]), ("archivio", None)]


def test_il_miglioramento_si_guarda_si_ferma_e_riparte(monkeypatch):
    lavoro = sosta._Miglioramento()
    monkeypatch.setattr(miglioramento_web, "_miglioratore", None)
    assert lavoro.acceso() is False and miglioramento_web.sta_lavorando() is False
    monkeypatch.setattr(miglioramento_web, "_miglioratore", _con_lavoro(True))
    assert lavoro.acceso() is True and lavoro.memoria() == {}
    monkeypatch.setattr(miglioramento_web, "_miglioratore", _con_lavoro(False))
    assert lavoro.acceso() is False
    chiamate = []
    monkeypatch.setattr(accesso, "vero", lambda: "vero")
    monkeypatch.setattr(strade_miglioramento, "ferma_il_miglioramento",
                        lambda archivio: chiamate.append(("ferma", archivio)))
    monkeypatch.setattr(strade_miglioramento, "avvia_il_miglioramento",
                        lambda archivio: chiamate.append(("avvia", archivio)))
    lavoro.ferma()
    lavoro.riparti("archivio", {})
    assert chiamate == [("ferma", "vero"), ("avvia", "archivio")]


def test_la_coda_del_ritocco_si_guarda_si_ferma_e_riparte(monkeypatch):
    lavoro = sosta._Ritocco()
    ritoccatore = _con_lavoro(True)
    monkeypatch.setattr(coda_ritocco, "_ritoccatore", ritoccatore)
    assert lavoro.acceso() is True and lavoro.memoria() == {}
    lavoro.ferma()
    assert ritoccatore.fermate == [2.0]
    chiamate = []
    monkeypatch.setattr(coda_ritocco, "riparti_se_accesa", chiamate.append)
    lavoro.riparti("archivio", {})
    assert chiamate == ["archivio"]


def test_la_gara_dei_video_si_guarda_si_ferma_e_riparte(monkeypatch):
    lavoro = sosta._Gara()
    monkeypatch.setattr(coda_ritocco, "_gara", None)
    assert lavoro.acceso() is False
    gara = _con_lavoro(True)
    monkeypatch.setattr(coda_ritocco, "_gara", gara)
    assert lavoro.acceso() is True and lavoro.memoria() == {}
    lavoro.ferma()
    assert gara.fermate == [2.0]
    chiamate = []
    monkeypatch.setattr(coda_ritocco, "parti_la_gara", chiamate.append)
    lavoro.riparti("archivio", {})
    assert chiamate == ["archivio"]


def test_coda_e_gara_si_fermano_anche_una_alla_volta(monkeypatch):
    ritoccatore, gara = _con_lavoro(True), _con_lavoro(False)
    monkeypatch.setattr(coda_ritocco, "_ritoccatore", None)
    monkeypatch.setattr(coda_ritocco, "_gara", None)
    coda_ritocco.ferma(1.0)
    coda_ritocco.ferma_la_coda(1.0)
    coda_ritocco.ferma_la_gara(1.0)
    assert coda_ritocco.sta_lavorando() is False
    monkeypatch.setattr(coda_ritocco, "_ritoccatore", ritoccatore)
    monkeypatch.setattr(coda_ritocco, "_gara", gara)
    assert coda_ritocco.gara_in_corso() is False
    coda_ritocco.ferma_la_coda(0.5)
    assert ritoccatore.fermate == [0.5] and gara.fermate == []
    coda_ritocco.ferma_la_gara(0.25)
    assert gara.fermate == [0.25] and ritoccatore.fermate == [0.5]
    coda_ritocco.ferma(3.0)
    assert ritoccatore.fermate == [0.5, 3.0] and gara.fermate == [0.25, 3.0]


def test_la_memoria_vera_sta_nella_carta(casa):
    assert sosta._dalla_carta() is None
    sosta._nella_carta({"dove": REALE, "lavori": {IA: {"scelti": ["volti"]}}})
    assert carta.leggi()[sosta.DA_RIPARTIRE] == {
        "dove": REALE, "lavori": {IA: {"scelti": ["volti"]}}}
    assert sosta._dalla_carta() == {"dove": REALE, "lavori": {IA: {"scelti": ["volti"]}}}
    sosta._nella_carta(None)
    assert sosta.DA_RIPARTIRE not in carta.leggi()


def test_l_archivio_vero_e_quello_aperto(monkeypatch):
    monkeypatch.setattr(accesso, "vero", lambda: "quello vero")
    assert sosta._l_archivio() == "quello vero"


@pytest.fixture
def per_la_copia(monkeypatch):
    nuova = Banco()
    monkeypatch.setattr(sosta, "per_la_copia", nuova.sosta)
    yield nuova
    nuova.sosta.smetti(ATTESA)


class LavoroFinto:

    def __init__(self, acceso: bool = False):
        self.sta_lavorando = acceso
        self.partiti: list[str] = []
        self.guasto = ""
        self.dettaglio = ""

    def parti(self, funzione, nome="lavoro") -> bool:
        self.partiti.append(nome)
        return True


def test_l_intelligenza_aspetta_la_copia(per_la_copia, monkeypatch):
    finto = LavoroFinto()
    monkeypatch.setattr(comune, "lavoro_ia", finto)
    monkeypatch.setattr(comune, "fila_ia", {"scelti": [], "adesso": "x", "fermata": True,
                                            "dove_guasto": "y"})
    per_la_copia.giro(True)
    archivio = _archivio()
    assert intelligenza.parti_la_fila(archivio, ["scritte", "boh", "volti"]) is False
    assert per_la_copia.sosta.in_attesa() == [IA]
    assert per_la_copia.carta.scritta["lavori"][IA] == {"scelti": ["volti", "scritte"]}
    assert finto.partiti == [] and comune.fila_ia["adesso"] == "x"
    assert intelligenza.come_va_la_fila_ia()["aspetta_la_copia"] is True
    per_la_copia.sosta.fermato_da_te(IA)
    assert intelligenza.come_va_la_fila_ia()["aspetta_la_copia"] is False


def test_l_intelligenza_senza_scelte_o_gia_accesa_non_aspetta(per_la_copia, monkeypatch):
    per_la_copia.giro(True)
    monkeypatch.setattr(comune, "lavoro_ia", LavoroFinto())
    assert intelligenza.parti_la_fila(_archivio(), []) is False
    assert intelligenza.parti_la_fila(_archivio(), None) is False
    monkeypatch.setattr(comune, "lavoro_ia", LavoroFinto(acceso=True))
    assert intelligenza.parti_la_fila(_archivio(), ["volti"]) is False
    assert per_la_copia.sosta.in_attesa() == []


@pytest.mark.parametrize("a_parte", [False, True])
def test_l_intelligenza_parte_se_non_c_e_la_copia(per_la_copia, monkeypatch, a_parte):
    finto = LavoroFinto()
    monkeypatch.setattr(comune, "lavoro_ia", finto)
    monkeypatch.setattr(comune, "fila_ia", {"scelti": [], "adesso": "x", "fermata": True,
                                            "dove_guasto": "y"})
    monkeypatch.setattr(in_disparte, "A_PARTE", a_parte)
    assert intelligenza.parti_la_fila(_archivio(), ["corpi", "impronte"]) is True
    assert finto.partiti == ["intelligenza"]
    assert comune.fila_ia == {"scelti": ["impronte", "corpi"], "adesso": "",
                              "fermata": False, "dove_guasto": ""}


def test_nella_prova_l_intelligenza_non_aspetta(per_la_copia, monkeypatch):
    finto = LavoroFinto()
    monkeypatch.setattr(comune, "lavoro_ia", finto)
    per_la_copia.giro(True)
    assert intelligenza.parti_la_fila(_archivio(di_prova=True), ["volti"]) is True
    assert finto.partiti == ["intelligenza"] and per_la_copia.sosta.in_attesa() == []


def test_il_miglioramento_aspetta_la_copia_ma_prima_dice_se_manca_seedvr2(
        per_la_copia, monkeypatch):
    from officina.miglioria import preparazione

    partiti = []
    monkeypatch.setattr(miglioramento_web, "il_miglioratore",
                        lambda archivio: SimpleNamespace(parti=lambda: partiti.append(1)))
    archivio = SimpleNamespace(dove=SimpleNamespace(nome=REALE, modelli=Path("m")),
                               di_prova=False)
    per_la_copia.giro(True)
    monkeypatch.setattr(preparazione, "e_pronto", lambda dove: False)
    with pytest.raises(ErroreOfficina):
        strade_miglioramento.avvia_il_miglioramento(archivio)
    assert per_la_copia.sosta.in_attesa() == []
    monkeypatch.setattr(preparazione, "e_pronto", lambda dove: True)
    assert strade_miglioramento.avvia_il_miglioramento(archivio) is None
    assert per_la_copia.sosta.in_attesa() == [MIGLIORAMENTO] and partiti == []
    per_la_copia.sosta.fermato_da_te(MIGLIORAMENTO)
    per_la_copia.giro(False)
    strade_miglioramento.avvia_il_miglioramento(archivio)
    assert partiti == [1]
    per_la_copia.giro(True)
    archivio.di_prova = True
    strade_miglioramento.avvia_il_miglioramento(archivio)
    assert partiti == [1, 1] and per_la_copia.sosta.in_attesa() == []


def test_fermare_il_miglioramento_ferma_anche_quello_a_parte(monkeypatch):
    chiamate = []
    monkeypatch.setattr(in_disparte, "ferma", lambda a: chiamate.append(("a parte", a)))
    monkeypatch.setattr(
        miglioramento_web, "il_miglioratore",
        lambda archivio: SimpleNamespace(
            ferma=lambda aspetta: chiamate.append(("qui", archivio, aspetta))))
    strade_miglioramento.ferma_il_miglioramento("archivio")
    assert chiamate == [("a parte", "miglioramento"), ("qui", "archivio", 2.0)]


class RitoccatoreFinto:

    def __init__(self):
        self.partenze = 0
        self.fermate: list[float] = []

    def parti(self) -> bool:
        self.partenze += 1
        return True

    def ferma(self, aspetta: float = 0.0) -> None:
        self.fermate.append(aspetta)


@pytest.fixture
def ritoccatore(monkeypatch):
    finto = RitoccatoreFinto()
    monkeypatch.setattr(coda_ritocco, "il_ritoccatore", lambda archivio: finto)
    return finto


def _accesa(archivio) -> bool:
    from officina.archivio.database import leggi_stato

    with archivio.lettura() as connessione:
        return bool(leggi_stato(connessione, coda_ritocco.ACCESA, False))


def test_la_coda_del_ritocco_aspetta_la_copia_e_resta_accesa(
        archivio_pieno, per_la_copia, ritoccatore):
    per_la_copia.giro(True)
    assert coda_ritocco.avvia(archivio_pieno) is False
    assert _accesa(archivio_pieno) and ritoccatore.partenze == 0
    assert per_la_copia.sosta.in_attesa() == [RITOCCO]
    coda_ritocco.ferma_dall_utente(archivio_pieno, aspetta=0.5)
    assert not _accesa(archivio_pieno) and per_la_copia.sosta.in_attesa() == []
    assert ritoccatore.fermate == [0.5]
    per_la_copia.giro(False)
    assert coda_ritocco.avvia(archivio_pieno) is True and ritoccatore.partenze == 1


def test_la_coda_riparte_solo_se_era_accesa_e_ha_da_fare(
        archivio_pieno, per_la_copia, ritoccatore, monkeypatch):
    from officina.ritocco import coda

    assert coda_ritocco.riparti_se_accesa(archivio_pieno) is False
    coda_ritocco.avvia(archivio_pieno)
    assert ritoccatore.partenze == 1
    assert coda_ritocco.riparti_se_accesa(archivio_pieno) is False
    monkeypatch.setattr(coda, "conteggi", lambda connessione: {coda.IN_CODA: 2})
    assert coda_ritocco.riparti_se_accesa(archivio_pieno) is True
    assert ritoccatore.partenze == 2
    per_la_copia.giro(True)
    assert coda_ritocco.riparti_se_accesa(archivio_pieno) is False
    assert ritoccatore.partenze == 2 and per_la_copia.sosta.in_attesa() == [RITOCCO]
    fatto = coda_ritocco.ripara(archivio_pieno)
    assert fatto["ripartita"] is False and ritoccatore.partenze == 2


def test_la_coda_nella_prova_non_aspetta(archivio_pieno, per_la_copia, ritoccatore,
                                         monkeypatch):
    from officina.ritocco import coda

    monkeypatch.setattr(archivio_pieno, "di_prova", True, raising=False)
    monkeypatch.setattr(coda, "conteggi", lambda connessione: {coda.IN_CODA: 1})
    per_la_copia.giro(True)
    assert coda_ritocco.avvia(archivio_pieno) is True
    assert coda_ritocco.riparti_se_accesa(archivio_pieno) is True
    assert per_la_copia.sosta.in_attesa() == []
    assert ritoccatore.partenze == 2
    per_la_copia.sosta.aspetta(RITOCCO)
    coda_ritocco.ferma_dall_utente(archivio_pieno, aspetta=0.0)
    assert per_la_copia.sosta.in_attesa() == [RITOCCO]


def test_la_gara_aspetta_la_copia(per_la_copia, monkeypatch):
    partite, fermate = [], []
    gara = SimpleNamespace(parti=lambda: partite.append(1) or True,
                           ferma=lambda aspetta: fermate.append(aspetta))
    monkeypatch.setattr(coda_ritocco, "la_gara", lambda archivio: gara)
    per_la_copia.giro(True)
    assert coda_ritocco.parti_la_gara(_archivio()) is False
    assert partite == [] and per_la_copia.sosta.in_attesa() == [GARA]
    coda_ritocco.ferma_la_gara_dall_utente(_archivio(), aspetta=0.5)
    assert fermate == [0.5] and per_la_copia.sosta.in_attesa() == []
    assert coda_ritocco.parti_la_gara(_archivio(di_prova=True)) is True
    assert partite == [1]
    per_la_copia.giro(False)
    assert coda_ritocco.parti_la_gara(_archivio()) is True and partite == [1, 1]
    per_la_copia.giro(True)
    per_la_copia.sosta.aspetta(GARA)
    coda_ritocco.ferma_la_gara_dall_utente(_archivio(di_prova=True))
    assert fermate == [0.5, 2.0] and per_la_copia.sosta.in_attesa() == [GARA]


def test_le_strade_del_ritocco_dicono_se_si_aspetta_la_copia(per_la_copia, monkeypatch):
    archivio = _archivio()
    chiamate = []
    gara = SimpleNamespace(come_va=lambda: {"stato": "fermo", "dettaglio": "segreto"})
    monkeypatch.setattr(accesso, "aperto", lambda: archivio)
    monkeypatch.setattr(coda_ritocco, "la_gara", lambda dove: gara)
    monkeypatch.setattr(coda_ritocco, "parti_la_gara",
                        lambda dove: chiamate.append(("parti", dove)))
    monkeypatch.setattr(coda_ritocco, "ferma_la_gara_dall_utente",
                        lambda dove: chiamate.append(("ferma", dove)))
    assert strade_ritocco._la_gara() == {"stato": "fermo", "aspetta_la_copia": False}
    per_la_copia.giro(True)
    per_la_copia.sosta.aspetta(GARA)
    assert strade_ritocco._avvia_la_gara()["aspetta_la_copia"] is True
    assert strade_ritocco._ferma_la_gara()["aspetta_la_copia"] is True
    assert chiamate == [("parti", archivio), ("ferma", archivio)]


@pytest.fixture
def cliente(archivio_pieno):
    from fastapi.testclient import TestClient

    from officina.web.server import app

    return TestClient(app, client=("127.0.0.1", 51000))


def test_le_strade_dicono_chi_aspetta_la_copia(cliente, per_la_copia):
    assert cliente.get("/api/ritocco/coda").json()["aspetta_la_copia"] is False
    assert cliente.get("/api/miglioramento").json()["aspetta_la_copia"] is False
    per_la_copia.giro(True)
    for nome in (MIGLIORAMENTO, RITOCCO):
        per_la_copia.sosta.aspetta(nome)
    assert cliente.get("/api/ritocco/coda").json()["aspetta_la_copia"] is True
    assert cliente.get("/api/miglioramento").json()["aspetta_la_copia"] is True


def test_fermare_dalle_pagine_vuol_dire_non_ripartire(cliente, per_la_copia, monkeypatch):
    monkeypatch.setattr(intelligenza, "ferma_la_fila", lambda: None)
    monkeypatch.setattr(strade_miglioramento, "ferma_il_miglioramento",
                        lambda archivio: None)
    per_la_copia.giro(True)
    for nome in ORDINE:
        per_la_copia.sosta.aspetta(nome)
    cliente.post("/intelligenza/ferma", follow_redirects=False)
    cliente.post("/miglioramento/ferma", follow_redirects=False)
    assert per_la_copia.sosta.in_attesa() == [
        nome for nome in ORDINE if nome not in (IA, MIGLIORAMENTO)]
    cliente.post("/api/ritocco/coda/ferma")
    assert per_la_copia.sosta.in_attesa() == [
        nome for nome in ORDINE if nome not in (IA, MIGLIORAMENTO, RITOCCO)]


def test_avviare_dalla_pagina_durante_la_copia_aspetta(cliente, per_la_copia, monkeypatch):
    monkeypatch.setattr(comune, "lavoro_ia", LavoroFinto())
    per_la_copia.giro(True)
    risposta = cliente.post("/intelligenza/avvia", data={"scelti": ["volti"]},
                            follow_redirects=False)
    assert risposta.status_code == 303
    assert per_la_copia.sosta.in_attesa() == [IA]
    assert comune.lavoro_ia.partiti == []


def test_sei_qui_segna_che_stai_usando_il_programma(cliente, monkeypatch):
    blocco.guardia.dimentica_tutti()
    try:
        assert not archivio_sicuro.stai_usando()
        cliente.get("/api/in-corso")
        assert not archivio_sicuro.stai_usando()
        risposta = cliente.post("/api/sei-qui")
        assert risposta.status_code == 204 and risposta.content == b""
        assert archivio_sicuro.stai_usando()
        visti = []
        monkeypatch.setattr(blocco.guardia, "usato_da_poco",
                            lambda secondi: visti.append(secondi) or False)
        assert not archivio_sicuro.stai_usando()
        assert visti == [archivio_sicuro.USATO_DA_POCO] == [30.0]
    finally:
        blocco.guardia.dimentica_tutti()


def test_sei_qui_si_puo_dire_anche_nella_prova():
    assert in_prova.perche_no("POST", "/api/sei-qui") is None


def test_la_guardia_conta_solo_gli_ultimi_secondi(monkeypatch):
    adesso = [1000.0]
    monkeypatch.setattr(blocco, "time", SimpleNamespace(monotonic=lambda: adesso[0]))
    guardia = blocco.Guardia()
    assert not guardia.usato_da_poco(30.0)
    guardia.visto_qualcuno("a")
    assert not guardia.usato_da_poco(30.0)
    guardia.usato_adesso("a")
    adesso[0] += 29.5
    assert guardia.usato_da_poco(30.0)
    adesso[0] += 0.5
    assert not guardia.usato_da_poco(30.0)
    guardia.usato_adesso("b")
    assert guardia.usato_da_poco(30.0)
    adesso[0] += 31.0
    assert not guardia.usato_da_poco(30.0)


def test_ogni_pagina_dice_quando_la_stai_usando():
    radice = Path(__file__).resolve().parents[1] / "officina" / "web"
    base = (radice / "templates" / "base.html").read_text(encoding="utf-8")
    assert '<script type="module" src="/statici/js/sei_qui.js"></script>' in base
    codice = (radice / "statici" / "js" / "sei_qui.js").read_text(encoding="utf-8")
    assert '"/api/sei-qui"' in codice and 'method: "POST"' in codice
    for quale in ("mousedown", "keydown", "wheel", "touchstart"):
        assert f'"{quale}"' in codice
    assert "mousemove" not in codice and "setInterval" not in codice
    ogni = int(codice.split("const OGNI = ")[1].split(";")[0])
    assert 0 < ogni < archivio_sicuro.USATO_DA_POCO * 1000


def test_l_archivio_sicuro_rallenta_quando_lo_usi(tmp_path, monkeypatch):
    from officina.sicuro import servizio

    visti = {}

    def finto(dove, **opzioni):
        visti.update(opzioni, dove=dove)
        return "servizio"

    monkeypatch.setattr(servizio, "ArchivioSicuro", finto)
    assert archivio_sicuro._di_serie(tmp_path, ("salta",), None) == "servizio"
    assert visti == {"dove": tmp_path, "salta": ("salta",), "programmino": None,
                     "rallenta": archivio_sicuro.stai_usando}


def test_la_prima_copia_segnata_si_legge_dalla_carta(casa):
    assert archivio_sicuro.prima_copia_segnata() is False
    carta.aggiorna(**{archivio_sicuro.PRIMA_COPIA: [3, None]})
    assert archivio_sicuro.prima_copia_segnata() is False
    carta.aggiorna(**{archivio_sicuro.PRIMA_COPIA: ["uno"]})
    assert archivio_sicuro.prima_copia_segnata() is True


def test_il_custode_dice_se_la_copia_e_voluta(tmp_path):
    scena = Scena(tmp_path)
    custode = scena.custode
    assert custode.copia_voluta() is None
    custode.comincia()
    assert custode.copia_voluta() is None
    assert custode.giro() == COPIA
    _parte(scena.copia)
    assert custode.copia_voluta() is True
    custode.pausa(COPIA)
    assert scena.copia.aspetta_fine(ATTESA)
    assert custode.copia_voluta() is True
    custode.riprendi(COPIA)
    assert custode.copia_voluta() is True
    assert custode.giro() == COPIA
    _parte(scena.copia, 2)
    scena.fine(scena.copia)
    assert custode.copia_voluta() is False
    assert custode.giro() is None
    assert custode.copia_voluta() is False
    custode.copia_ora()
    assert custode.copia_voluta() is True
    custode.pausa(COPIA)
    assert custode.copia_voluta() is True
    custode.ferma(ATTESA)
    assert custode.copia_voluta() is False


def test_senza_copia_il_custode_non_la_vuole(tmp_path):
    from officina.sicuro.custode import Custode

    assert Custode().copia_voluta() is False


def test_se_la_ripresa_non_va_la_copia_non_e_voluta(tmp_path):
    scena = Scena(tmp_path, prima=lambda: 1 / 0)
    custode = scena.custode
    custode.comincia()
    custode.copia_ora()
    assert custode.giro() is None
    assert custode.copia_voluta() is False


def test_durante_il_tuo_turno_il_custode_non_sa_ancora(tmp_path):
    scena = Scena(tmp_path)
    custode = scena.custode
    custode.comincia()
    utente = scena.utente()
    assert custode.fai(utente)
    _parte(utente)
    assert custode.giro() is None
    assert custode.copia_voluta() is None
    scena.fine(utente)
    assert custode.giro() == COPIA
    assert custode.copia_voluta() is True
    scena.fine(scena.copia)


def test_a_disco_pieno_i_lavori_ripartono(tmp_path):
    scena = Scena(tmp_path)
    custode = scena.custode
    custode.comincia()
    scena.copia.pieno.set()
    assert custode.giro() == COPIA
    _finche(lambda: scena.copia.stato == SPAZIO_FINITO)
    assert custode.copia_voluta() is False
    custode.copia_ora()
    assert custode.copia_voluta() is False
    scena.copia.pieno.clear()
    _finche(lambda: scena.copia.stato != SPAZIO_FINITO)
    assert custode.copia_voluta() is True
    scena.fine(scena.copia)


def test_a_disco_pieno_in_pausa_si_resta_fermi(tmp_path):
    scena = Scena(tmp_path)
    custode = scena.custode
    custode.comincia()
    scena.copia.pieno.set()
    assert custode.giro() == COPIA
    _finche(lambda: scena.copia.stato == SPAZIO_FINITO)
    custode.pausa(COPIA)
    assert custode.copia_voluta() is True
    assert scena.copia.aspetta_fine(ATTESA)


def _con_la_prima_copia_ferma(posto):
    posto.crea()
    collegamento = posto.collegamento
    collegamento.servizio.pausa("copia")
    collegamento.copia_tutto([nel_programma._cartella_con_le_foto(posto)])
    return collegamento


def test_la_sosta_serve_solo_durante_la_prima_copia(posto):
    collegamento = _con_la_prima_copia_ferma(posto)
    custode = collegamento.servizio._aperto.custode
    _finche(lambda: custode.copia_voluta() is not None)
    assert collegamento.serve_la_sosta() is True
    collegamento.servizio.riprendi("copia")
    _finche(lambda: collegamento.serve_la_sosta() is False)
    assert not collegamento.prima_copia_in_corso()


def test_dopo_la_prima_copia_la_sosta_non_serve_piu(posto):
    posto.crea()
    collegamento = posto.collegamento
    collegamento.copia_tutto([nel_programma._cartella_con_le_foto(posto)])
    _finche(lambda: not collegamento.prima_copia_in_corso())
    altra = posto.finta.metti("altro/c.jpg", _dati(300, 3)).parent
    collegamento.servizio.pausa("copia")
    collegamento.servizio.metti_le_cartelle([altra])
    _finche(lambda: collegamento.servizio.copia_voluta() is True)
    assert collegamento.serve_la_sosta() is False


def test_senza_archivio_sicuro_la_sosta_non_serve(posto):
    assert posto.collegamento.serve_la_sosta() is False
    posto.crea()
    posto.collegamento.chiudi(ATTESA)
    assert posto.collegamento.serve_la_sosta() is None
    nuovo = posto.nuovo()
    assert nuovo.guarda() == archivio_sicuro.CHIUSO
    assert nuovo.serve_la_sosta() is False


def test_mentre_si_apre_non_si_sa(posto, monkeypatch):
    posto.crea()
    nuovo = posto.nuovo()
    with monkeypatch.context() as finto:
        finto.setattr(nuovo, "_apre", lambda: True)
        nuovo._segna(archivio_sicuro.SI_APRE)
        assert nuovo.serve_la_sosta() is None
    assert nuovo.serve_la_sosta() is False


def test_se_il_custode_non_sa_non_si_sa(posto, monkeypatch):
    collegamento = _con_la_prima_copia_ferma(posto)
    monkeypatch.setattr(collegamento.servizio, "copia_voluta", lambda: None)
    assert collegamento.serve_la_sosta() is None
    monkeypatch.setattr(collegamento.servizio, "copia_voluta", lambda: False)
    assert collegamento.serve_la_sosta() is False


def test_il_servizio_chiuso_non_sa_se_la_copia_e_voluta(posto):
    posto.crea()
    servizio = posto.collegamento.servizio
    servizio.chiudi(ATTESA)
    assert servizio.copia_voluta() is None


def test_il_programma_fa_partire_la_sosta(casa, monkeypatch):
    programma, _ = finestre._programma()
    visti = []
    monkeypatch.setattr(sosta.per_la_copia, "guarda",
                        lambda serve, attiva=False: visti.append((serve, attiva)))
    monkeypatch.setattr(archivio_sicuro, "prima_copia_segnata", lambda: True)
    programma._parti_la_sosta()
    assert visti == [(programma._serve_la_sosta, True)]


def test_se_la_sosta_non_parte_il_programma_va_avanti(casa, monkeypatch, scritti):
    programma, _ = finestre._programma()

    def rotta():
        raise OSError("carta rotta")

    monkeypatch.setattr(archivio_sicuro, "prima_copia_segnata", rotta)
    del scritti[:]
    programma._parti_la_sosta()
    assert _codici(scritti) == ["programma.sosta_non_partita"]


def test_il_programma_chiede_al_collegamento_se_serve_la_sosta(casa):
    programma, _ = finestre._programma()
    assert programma._serve_la_sosta() is None
    programma.sicuro = SimpleNamespace(serve_la_sosta=lambda: True)
    assert programma._serve_la_sosta() is True
    programma._sta_chiudendo = True
    assert programma._serve_la_sosta() is None
    programma._sta_chiudendo = False
    programma._spento = True
    assert programma._serve_la_sosta() is None


def test_accendere_fa_partire_la_sosta_dopo_l_archivio_sicuro():
    import inspect

    corpo = inspect.getsource(avvio.Programma.accendi)
    sicuro = corpo.index("self._apri_l_archivio_sicuro_in_sottofondo(password)")
    assert corpo.index("self._parti_la_sosta()") > sicuro


def test_fermare_tutto_ferma_anche_la_sosta(monkeypatch):
    visti = []
    monkeypatch.setattr(sosta.per_la_copia, "smetti", visti.append)
    generale.ferma_tutto(0.1)
    assert visti == [0.1]
