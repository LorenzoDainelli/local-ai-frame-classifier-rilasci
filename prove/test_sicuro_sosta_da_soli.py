from __future__ import annotations

import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from officina import parole as parole_mod
from officina.archivio import accesso
from officina.corpi import chi_e as chi_e_mod
from officina.errori import ErroreOfficina
from officina.impronte import motore as impronte_motore
from officina.modello import persone as persone_mod
from officina.volti import riferimento
from officina.volti import rilevatore as volti_rilevatore
from officina.web import coda_ritocco, in_disparte, lavori, sosta
from officina.web import miglioramento as miglioramento_web
from officina.web.sosta import (CHI_E, DOPPIONI, FACCE, IA, IMPRONTE, NOMI, ORDINE, QUALITA,
                                SCRITTE, VOLTI)
from officina.web.strade import comune, doppioni, etichetta, intelligenza, misura, persone
from officina.web.strade import miglioramento as strade_miglioramento
from prove import test_sicuro_sosta as della_sosta
from prove import test_volti as dei_volti

per_la_copia = della_sosta.per_la_copia
cliente = della_sosta.cliente
scritti = della_sosta.scritti
cartella_ritratti = dei_volti.cartella_ritratti
RilevatoreFinto = dei_volti.RilevatoreFinto
_codici = della_sosta._codici
REALE = della_sosta.REALE
CodaVera = impronte_motore.Coda

DA_SOLI = (IMPRONTE, VOLTI, SCRITTE, CHI_E, FACCE, DOPPIONI, QUALITA)
LAVORI = {IMPRONTE: "lavoro_impronte_passata", VOLTI: "lavoro_volti",
          SCRITTE: "lavoro_parole", CHI_E: "lavoro_chi_e", FACCE: "lavoro_riferimento",
          DOPPIONI: "lavoro_doppioni", QUALITA: "lavoro_qualita"}
RITRATTI = str(Path("/ritratti"))
MEMORIE = {IMPRONTE: {"descrittore": "d"}, VOLTI: {}, SCRITTE: {}, CHI_E: {},
           FACCE: {"persona_id": 7, "cartella": RITRATTI}, DOPPIONI: {"come": "guarda"},
           QUALITA: {}}
PARTENZE = {
    IMPRONTE: lambda archivio: misura.parti_le_impronte_per(archivio, "d"),
    VOLTI: lambda archivio: persone.trova_i_volti_in(archivio),
    SCRITTE: lambda archivio: intelligenza.leggi_le_scritte_in(archivio),
    CHI_E: lambda archivio: etichetta.rifai_chi_e(archivio),
    FACCE: lambda archivio: persone.insegna_le_facce(archivio, 7, "/ritratti"),
    DOPPIONI: lambda archivio: doppioni.cerca_i_doppioni(archivio),
    QUALITA: lambda archivio: strade_miglioramento.controlla_la_qualita_in(archivio)}
FILI = {True: {IMPRONTE: "impronte", VOLTI: "volti", SCRITTE: "scritte", CHI_E: "chi_e",
               FACCE: "riferimento", DOPPIONI: "doppioni", QUALITA: "qualita"},
        False: {IMPRONTE: "impronte", VOLTI: "volti", SCRITTE: "parole", CHI_E: "chi_e",
                FACCE: "riferimento", DOPPIONI: "doppioni", QUALITA: "qualita"}}


class LavoroFinto:

    def __init__(self):
        self.sta_lavorando = False
        self.partiti: list[str] = []
        self.funzioni: list = []
        self.attese: list[float] = []
        self.numeri: dict = {}
        self.righe: list[str] = []
        self.guasto = ""

    def parti(self, funzione, nome: str = "lavoro") -> bool:
        if self.sta_lavorando:
            return False
        self.partiti.append(nome)
        self.funzioni.append(funzione)
        return True

    def aspetta_che_finisca(self, secondi: float = lavori.ATTESA_DOPO_FERMA) -> bool:
        self.attese.append(secondi)
        self.sta_lavorando = False
        return True

    def di(self, riga: str) -> None:
        self.righe.append(riga)

    def come_va(self) -> dict:
        return {"sta_lavorando": self.sta_lavorando, **self.numeri}


class CodaFinta:

    def __init__(self, archivio, quali):
        self.archivio = archivio
        self.quali = quali
        self.fermata = False

    def esegui(self) -> None:
        return None

    def ferma(self) -> None:
        self.fermata = True


class PassataFinta:

    def __init__(self):
        self.fermate = 0

    def ferma(self) -> None:
        self.fermate += 1


def _aperto(di_prova: bool = False):
    return SimpleNamespace(dove=SimpleNamespace(nome=REALE, modelli=Path("modelli")),
                           di_prova=di_prova)


@pytest.fixture
def finti(monkeypatch):
    fatti = {nome: LavoroFinto() for nome in (*LAVORI, IA, "corpi")}
    for nome, attributo in LAVORI.items():
        monkeypatch.setattr(comune, attributo, fatti[nome])
    monkeypatch.setattr(comune, "lavoro_ia", fatti[IA])
    monkeypatch.setattr(comune, "lavoro_corpi", fatti["corpi"])
    monkeypatch.setattr(comune, "fila_ia", {"scelti": [], "adesso": "", "fermata": False,
                                            "dove_guasto": ""})
    for nome in ("coda_impronte", "passata_volti", "passata_parole", "passata_doppioni"):
        monkeypatch.setattr(comune, nome, None)
    monkeypatch.setattr(comune, "descrittore_chiesto", "")
    monkeypatch.setattr(comune, "facce_chieste", {})
    monkeypatch.setattr(comune, "doppioni_come", doppioni.GUARDA)
    for nome in ("chi_e_basta", "facce_basta", "ferma_la_qualita"):
        monkeypatch.setattr(comune, nome, threading.Event())
    a_parte: list[str] = []
    monkeypatch.setattr(in_disparte, "ferma", lambda a="fila": a_parte.append(a))
    rinunce: list[str] = []
    monkeypatch.setattr(lavori.turno, "rinuncia", rinunce.append)
    monkeypatch.setattr(misura, "_quali_in_coda", lambda descrittore, archivio: ["uno"])
    monkeypatch.setattr(volti_rilevatore, "cosa_manca", lambda modelli: "")
    monkeypatch.setattr(parole_mod, "in_casa", lambda modelli: True)
    monkeypatch.setattr(impronte_motore, "Coda", CodaFinta)
    monkeypatch.setattr(persone, "parti_i_volti",
                        lambda archivio: comune.lavoro_volti.parti(None, "volti"))
    monkeypatch.setattr(intelligenza, "_parti_le_scritte",
                        lambda archivio: comune.lavoro_parole.parti(None, "parole"))
    monkeypatch.setattr(doppioni, "_cerca_qui",
                        lambda archivio: comune.lavoro_doppioni.parti(None, "doppioni"))
    return SimpleNamespace(lavori=fatti, a_parte=a_parte, rinunce=rinunce)


@pytest.fixture(params=[True, False], ids=["a_parte", "qui"])
def a_parte(request, monkeypatch):
    monkeypatch.setattr(in_disparte, "A_PARTE", request.param)
    return request.param


@pytest.fixture
def vera(per_la_copia, finti, monkeypatch):
    monkeypatch.setattr(miglioramento_web, "_miglioratore", None)
    monkeypatch.setattr(coda_ritocco, "_ritoccatore", None)
    monkeypatch.setattr(coda_ritocco, "_gara", None)
    per_la_copia.sosta._lavori = None
    per_la_copia.archivio = _aperto()
    return per_la_copia


def test_i_lavori_da_soli_hanno_un_nome_e_vengono_dopo_la_fila():
    assert ORDINE[:len(DA_SOLI) + 1] == (IA, *DA_SOLI)
    assert NOMI[VOLTI] == "la ricerca dei volti"
    assert NOMI[FACCE] == "lo studio delle facce insegnate"
    assert sosta.ASPETTA_LA_COPIA.format(chi=NOMI[VOLTI]) == (
        "L'Archivio sicuro sta facendo la prima copia: la ricerca dei volti parte appena "
        "la copia è finita.")


def test_di_serie_ognuno_sa_dove_sono_i_suoi_pezzi():
    di_serie = sosta._di_serie()
    for nome in DA_SOLI:
        lavoro = di_serie[nome]
        assert isinstance(lavoro, sosta._DaSolo)
        for funzione in (lavoro._ferma, lavoro._parti, lavoro._memoria):
            if funzione:
                assert callable(lavoro._funzione(funzione))
        assert getattr(comune, lavoro._lavoro) is getattr(comune, LAVORI[nome])
    assert {nome: di_serie[nome]._con_la_fila for nome in DA_SOLI} == {
        IMPRONTE: "impronte", VOLTI: "volti", SCRITTE: "scritte", CHI_E: "", FACCE: "",
        DOPPIONI: "", QUALITA: ""}
    assert {di_serie[nome]._con_la_fila for nome in (IMPRONTE, VOLTI, SCRITTE)} <= set(
        intelligenza.IA_IN_FILA)


@pytest.mark.parametrize("nome", DA_SOLI)
def test_durante_la_copia_chi_parte_da_solo_aspetta(per_la_copia, finti, a_parte, nome):
    per_la_copia.giro(True)
    assert PARTENZE[nome](_aperto()) is False
    assert per_la_copia.sosta.in_attesa() == [nome]
    assert per_la_copia.carta.scritta["lavori"] == {nome: MEMORIE[nome]}
    assert finti.lavori[nome].partiti == []


@pytest.mark.parametrize("nome", DA_SOLI)
def test_senza_la_copia_chi_parte_da_solo_parte_subito(per_la_copia, finti, a_parte, nome):
    assert PARTENZE[nome](_aperto()) is True
    assert finti.lavori[nome].partiti == [FILI[a_parte][nome]]
    assert per_la_copia.sosta.in_attesa() == []
    assert per_la_copia.carta.scritture == []


@pytest.mark.parametrize("nome", DA_SOLI)
def test_nella_prova_chi_parte_da_solo_non_aspetta(per_la_copia, finti, a_parte, nome):
    per_la_copia.giro(True)
    assert PARTENZE[nome](_aperto(di_prova=True)) is True
    assert finti.lavori[nome].partiti == [FILI[a_parte][nome]]
    assert per_la_copia.sosta.in_attesa() == []


@pytest.mark.parametrize("nome", DA_SOLI)
def test_chi_lavora_gia_non_aspetta(per_la_copia, finti, nome):
    finti.lavori[nome].sta_lavorando = True
    per_la_copia.giro(True)
    assert PARTENZE[nome](_aperto()) is False
    assert per_la_copia.sosta.in_attesa() == []
    assert finti.lavori[nome].partiti == []


@pytest.mark.parametrize("nome, dove, quale, rotto", [
    (VOLTI, volti_rilevatore, "cosa_manca", lambda modelli: "Manca il modello dei volti."),
    (FACCE, volti_rilevatore, "cosa_manca", lambda modelli: "Manca il modello dei volti."),
    (SCRITTE, parole_mod, "in_casa", lambda modelli: False)])
def test_se_manca_il_modello_lo_dice_subito_anche_durante_la_copia(
        per_la_copia, finti, monkeypatch, a_parte, nome, dove, quale, rotto):
    monkeypatch.setattr(dove, quale, rotto)
    per_la_copia.giro(True)
    with pytest.raises(ErroreOfficina):
        PARTENZE[nome](_aperto())
    assert per_la_copia.sosta.in_attesa() == []
    assert finti.lavori[nome].partiti == []


def test_le_impronte_senza_niente_da_fare_non_aspettano(per_la_copia, finti, monkeypatch):
    monkeypatch.setattr(misura, "_quali_in_coda", lambda descrittore, archivio: [])
    per_la_copia.giro(True)
    assert misura.parti_le_impronte_per(_aperto(), "d") is False
    assert per_la_copia.sosta.in_attesa() == []


def test_chi_e_non_parte_e_non_aspetta_mentre_lavorano_i_corpi(per_la_copia, finti):
    finti.lavori["corpi"].sta_lavorando = True
    per_la_copia.giro(True)
    assert etichetta.rifai_chi_e(_aperto()) is False
    assert per_la_copia.sosta.in_attesa() == []
    assert finti.lavori[CHI_E].partiti == []


@pytest.mark.parametrize("nome", DA_SOLI)
def test_chi_parte_durante_la_copia_parte_da_solo_alla_fine(vera, finti, a_parte, nome,
                                                            scritti):
    vera.giro(True)
    assert PARTENZE[nome](vera.archivio) is False
    vera.giro(False)
    assert finti.lavori[nome].partiti == [FILI[a_parte][nome]]
    assert vera.sosta.in_attesa() == []
    assert _codici(scritti) == ["sosta.comincia", "sosta.in_attesa", "sosta.finita",
                                "sosta.ripartito"]


@pytest.mark.parametrize("nome", DA_SOLI)
def test_chi_lavora_da_solo_si_ferma_e_riparte_con_le_stesse_scelte(vera, finti, a_parte,
                                                                    nome, scritti):
    assert PARTENZE[nome](vera.archivio) is True
    lavoro = finti.lavori[nome]
    lavoro.sta_lavorando = True
    vera.giro(True)
    assert lavoro.attese == [2.0] and lavoro.sta_lavorando is False
    assert vera.carta.scritta == {"dove": REALE, "lavori": {nome: MEMORIE[nome]}}
    vera.giro(False)
    assert lavoro.partiti == [FILI[a_parte][nome]] * 2
    assert vera.carta.scritta is None
    assert _codici(scritti) == ["sosta.comincia", "sosta.fermato", "sosta.finita",
                                "sosta.ripartito"]


def test_i_pezzi_della_fila_si_fermano_con_la_fila(vera, finti):
    finti.lavori[IA].sta_lavorando = True
    comune.fila_ia["scelti"] = ["impronte", "volti", "scritte"]
    for nome in (IMPRONTE, VOLTI, SCRITTE, CHI_E, DOPPIONI):
        finti.lavori[nome].sta_lavorando = True
    assert vera.sosta.si_fermano() == [NOMI[IA], NOMI[CHI_E], NOMI[DOPPIONI]]
    finti.lavori[IA].sta_lavorando = False
    assert vera.sosta.si_fermano() == [NOMI[nome] for nome in
                                       (IMPRONTE, VOLTI, SCRITTE, CHI_E, DOPPIONI)]


def test_fermata_la_fila_i_suoi_pezzi_non_si_ricordano_da_soli(vera, finti, monkeypatch):
    finti.lavori[IA].sta_lavorando = True
    comune.fila_ia["scelti"] = ["volti"]
    finti.lavori[VOLTI].sta_lavorando = True

    def ferma_la_fila() -> None:
        finti.lavori[IA].sta_lavorando = False
        finti.lavori[VOLTI].sta_lavorando = False

    monkeypatch.setattr(intelligenza, "ferma_la_fila", ferma_la_fila)
    vera.giro(True)
    assert vera.carta.scritta["lavori"] == {IA: {"scelti": ["volti"]}}
    assert finti.lavori[VOLTI].attese == []


@pytest.mark.parametrize("scelti, ripartiti", [(["volti"], []), (["scritte"], ["volti"])])
def test_ripartendo_la_fila_i_suoi_pezzi_non_ripartono_due_volte(vera, finti, monkeypatch,
                                                                 scelti, ripartiti):
    vera.carta.scritta = {"dove": REALE, "lavori": {IA: {"scelti": scelti}, VOLTI: {}}}

    def parti_la_fila(archivio, voluti) -> None:
        comune.fila_ia["scelti"] = list(voluti)
        finti.lavori[IA].sta_lavorando = True

    monkeypatch.setattr(intelligenza, "parti_la_fila", parti_la_fila)
    vera.giro(False)
    assert finti.lavori[VOLTI].partiti == ripartiti
    assert finti.lavori[IA].sta_lavorando is True


def test_se_la_fila_non_riparte_i_suoi_pezzi_ripartono_da_soli(vera, finti, monkeypatch,
                                                               scritti):
    vera.carta.scritta = {"dove": REALE, "lavori": {IA: {"scelti": ["volti"]}, VOLTI: {}}}

    def rotta(archivio, voluti) -> None:
        raise RuntimeError("la fila non parte")

    monkeypatch.setattr(intelligenza, "parti_la_fila", rotta)
    vera.giro(False)
    assert finti.lavori[VOLTI].partiti == ["volti"]
    assert _codici(scritti, "errore") == ["sosta.non_ripartito"]


def test_un_pezzo_della_fila_partito_da_solo_riparte_anche_a_fila_spenta(vera, finti,
                                                                         a_parte):
    vera.carta.scritta = {"dove": REALE, "lavori": {SCRITTE: {}}}
    comune.fila_ia["scelti"] = ["scritte"]
    vera.giro(False)
    assert finti.lavori[SCRITTE].partiti == [FILI[a_parte][SCRITTE]]


def test_le_impronte_si_fermano_dalla_coda(finti, monkeypatch):
    monkeypatch.setattr(in_disparte, "A_PARTE", False)
    archivio = _aperto()
    assert misura.parti_le_impronte_per(archivio, "d") is True
    coda = comune.coda_impronte
    assert isinstance(coda, CodaFinta) and coda.archivio is archivio
    assert coda.quali == ["uno"]
    assert finti.lavori[IMPRONTE].funzioni == [coda.esegui]
    assert misura.impronte_chieste() == {"descrittore": "d"}
    misura.ferma_le_impronte(1.5)
    assert coda.fermata is True and finti.lavori[IMPRONTE].attese == [1.5]
    monkeypatch.setattr(comune, "coda_impronte", None)
    misura.ferma_le_impronte()
    assert finti.lavori[IMPRONTE].attese == [1.5, lavori.ATTESA_DOPO_FERMA]


def test_le_impronte_a_parte_ricordano_cosa_si_e_chiesto(finti, monkeypatch):
    avvii = []
    monkeypatch.setattr(in_disparte, "A_PARTE", True)
    monkeypatch.setattr(in_disparte, "lancia",
                        lambda *argomenti, **opzioni: avvii.append((argomenti, opzioni))
                        or True)
    assert misura.parti_le_impronte_per(_aperto(), "") is True
    argomenti, opzioni = avvii[0]
    assert argomenti[1:] == ("impronte", REALE, "officina.web.strade.misura:impronte_di_la",
                             (["uno"],))
    assert opzioni["ferma_con"] == "officina.web.strade.misura:ferma_di_la"
    assert misura.impronte_chieste() == {"descrittore": ""}
    assert comune.coda_impronte is None


@pytest.mark.parametrize("passata, ferma, nome, di_solito", [
    ("passata_volti", persone.ferma_la_ricerca_dei_volti, VOLTI, lavori.ATTESA_DOPO_FERMA),
    ("passata_parole", intelligenza.ferma_la_lettura, SCRITTE, lavori.ATTESA_DOPO_FERMA),
    ("passata_doppioni", doppioni.ferma_i_doppioni, DOPPIONI, 0.0)])
def test_fermare_ferma_la_passata_e_aspetta(finti, monkeypatch, passata, ferma, nome,
                                            di_solito):
    ferma(1.5)
    finta = PassataFinta()
    monkeypatch.setattr(comune, passata, finta)
    ferma()
    assert finta.fermate == 1
    assert finti.lavori[nome].attese == [1.5, di_solito]


@pytest.mark.parametrize("nome, passata, chiave", [
    (VOLTI, "passata_volti", "volti"), (SCRITTE, "passata_parole", "scritte")])
def test_a_parte_si_ferma_di_la(finti, monkeypatch, nome, passata, chiave):
    monkeypatch.setattr(in_disparte, "A_PARTE", True)
    assert PARTENZE[nome](_aperto()) is True
    riflessa = getattr(comune, passata)
    assert isinstance(riflessa, in_disparte.PassataRiflessa) and riflessa.chiave == chiave
    riflessa.ferma()
    assert finti.a_parte == [chiave]
    monkeypatch.setattr(comune, passata, None)
    monkeypatch.setattr(in_disparte, "lancia", lambda *argomenti, **opzioni: False)
    assert PARTENZE[nome](_aperto()) is False
    assert getattr(comune, passata) is None


def test_i_doppioni_e_la_qualita_si_fermano_anche_di_la(finti):
    doppioni.ferma_i_doppioni(1.0)
    strade_miglioramento.ferma_il_controllo(2.0)
    assert finti.a_parte == ["doppioni", "qualita"]
    assert comune.ferma_la_qualita.is_set()
    assert finti.lavori[DOPPIONI].attese == [1.0]
    assert finti.lavori[QUALITA].attese == [2.0]
    strade_miglioramento.ferma_il_controllo()
    assert finti.lavori[QUALITA].attese == [2.0, 0.0]


@pytest.fixture
def passate_di_chi_e(monkeypatch):
    fatte: list = []

    class Finta:

        def __init__(self, archivio, fermato=None):
            self.archivio = archivio
            self.fermato = fermato
            fatte.append(self)

        def esegui(self):
            if len(fatte) == 1 and fatte[0].archivio.ancora:
                comune.ultima_risposta_dei_corpi["quando"] = time.monotonic()
            return None

    monkeypatch.setattr(chi_e_mod, "Passata", Finta)
    monkeypatch.setitem(comune.ultima_risposta_dei_corpi, "quando", 0.0)
    return fatte


def _con_risposte(ancora: bool = False):
    archivio = _aperto()
    archivio.ancora = ancora
    return archivio


def test_chi_e_lavora_con_il_freno(finti, passate_di_chi_e, monkeypatch):
    monkeypatch.setattr(etichetta, "QUIETE_DOPO_LE_RISPOSTE", 0.0)
    comune.chi_e_basta.set()
    archivio = _con_risposte()
    assert etichetta.rifai_chi_e(archivio) is True
    assert comune.chi_e_basta.is_set() is False
    assert finti.lavori[CHI_E].partiti == ["chi_e"]
    finti.lavori[CHI_E].funzioni[0]()
    assert len(passate_di_chi_e) == 1
    passata = passate_di_chi_e[0]
    assert passata.archivio is archivio and passata.fermato() is False
    comune.chi_e_basta.set()
    assert passata.fermato() is True


def test_chi_e_rifa_il_giro_se_rispondi_mentre_lavora(finti, passate_di_chi_e,
                                                      monkeypatch):
    monkeypatch.setattr(etichetta, "QUIETE_DOPO_LE_RISPOSTE", 0.0)
    assert etichetta.rifai_chi_e(_con_risposte(ancora=True)) is True
    finti.lavori[CHI_E].funzioni[0]()
    assert len(passate_di_chi_e) == 2


def test_chi_e_fermato_prima_non_comincia_nemmeno(finti, passate_di_chi_e, monkeypatch):
    monkeypatch.setattr(etichetta, "QUIETE_DOPO_LE_RISPOSTE", 0.0)
    assert etichetta.rifai_chi_e(_con_risposte()) is True
    etichetta.ferma_chi_e(0.0)
    finti.lavori[CHI_E].funzioni[0]()
    assert passate_di_chi_e == []
    assert finti.rinunce == ["chi_e"] and finti.lavori[CHI_E].attese == [0.0]


def test_chi_e_fermato_dopo_un_giro_non_ne_fa_un_altro(finti, passate_di_chi_e,
                                                       monkeypatch):
    monkeypatch.setattr(etichetta, "QUIETE_DOPO_LE_RISPOSTE", 0.0)
    assert etichetta.rifai_chi_e(_con_risposte(ancora=True)) is True
    finta = chi_e_mod.Passata

    def e_poi_basta(archivio, fermato=None):
        passata = finta(archivio, fermato)
        comune.chi_e_basta.set()
        return passata

    monkeypatch.setattr(chi_e_mod, "Passata", e_poi_basta)
    finti.lavori[CHI_E].funzioni[0]()
    assert len(passate_di_chi_e) == 1


def test_chi_e_fermato_mentre_aspetta_la_quiete_smette_subito(finti, passate_di_chi_e,
                                                              monkeypatch):
    monkeypatch.setattr(etichetta, "QUIETE_DOPO_LE_RISPOSTE", 60.0)
    comune.ultima_risposta_dei_corpi["quando"] = time.monotonic()
    assert etichetta.rifai_chi_e(_con_risposte()) is True
    filo = threading.Thread(target=finti.lavori[CHI_E].funzioni[0], daemon=True)
    partito = time.monotonic()
    filo.start()
    time.sleep(0.05)
    etichetta.ferma_chi_e()
    filo.join(10.0)
    assert not filo.is_alive() and time.monotonic() - partito < 10.0
    assert passate_di_chi_e == []
    assert finti.lavori[CHI_E].attese == [lavori.ATTESA_DOPO_FERMA]


def test_chi_e_con_calma_segna_l_ora_e_guarda_l_archivio_aperto(per_la_copia, finti,
                                                                monkeypatch):
    monkeypatch.setattr(accesso, "aperto", _aperto)
    monkeypatch.setitem(comune.ultima_risposta_dei_corpi, "quando", 0.0)
    prima = time.monotonic()
    etichetta._rifai_chi_e_con_calma()
    assert comune.ultima_risposta_dei_corpi["quando"] >= prima
    assert finti.lavori[CHI_E].partiti == ["chi_e"]
    per_la_copia.giro(True)
    etichetta._rifai_chi_e_con_calma()
    assert per_la_copia.sosta.in_attesa() == [CHI_E]
    assert finti.lavori[CHI_E].partiti == ["chi_e"]


def test_le_facce_insegnate_si_ricordano_e_si_fermano(finti, monkeypatch):
    monkeypatch.setattr(in_disparte, "A_PARTE", False)
    imparate = []
    monkeypatch.setattr(persone, "_impara_le_facce",
                        lambda archivio, chi, cartella: imparate.append((chi, cartella)))
    comune.facce_basta.set()
    assert persone.insegna_le_facce(_aperto(), 7, "/ritratti") is True
    assert comune.facce_basta.is_set() is False
    finti.lavori[FACCE].funzioni[0]()
    assert imparate == [(7, Path(RITRATTI))]
    chieste = persone.facce_chieste()
    assert chieste == {"persona_id": 7, "cartella": RITRATTI}
    chieste["persona_id"] = 8
    assert persone.facce_chieste()["persona_id"] == 7
    persone.ferma_le_facce(1.5)
    assert comune.facce_basta.is_set()
    assert finti.a_parte == ["riferimento"] and finti.lavori[FACCE].attese == [1.5]
    persone.ferma_le_facce()
    assert finti.lavori[FACCE].attese == [1.5, lavori.ATTESA_DOPO_FERMA]


def test_le_facce_a_parte_si_possono_fermare_di_la(finti, monkeypatch):
    avvii = []
    monkeypatch.setattr(in_disparte, "A_PARTE", True)
    monkeypatch.setattr(in_disparte, "lancia",
                        lambda *argomenti, **opzioni: avvii.append((argomenti, opzioni))
                        or True)
    assert persone.insegna_le_facce(_aperto(), 7, "/ritratti") is True
    argomenti, opzioni = avvii[0]
    assert argomenti[1:] == ("riferimento", REALE, "officina.web.strade.persone:facce_di_la",
                             (7, RITRATTI))
    assert opzioni == {"ferma_con": "officina.web.strade.persone:ferma_le_facce_di_la"}
    assert in_disparte._trova(opzioni["ferma_con"]) is persone.ferma_le_facce_di_la
    persone.ferma_le_facce_di_la()
    assert comune.facce_basta.is_set()
    imparate = []
    monkeypatch.setattr(persone, "_impara_le_facce",
                        lambda archivio, chi, cartella: imparate.append((chi, cartella)))
    assert persone.facce_di_la(_aperto(), 7, RITRATTI) is finti.lavori[FACCE]
    assert comune.facce_basta.is_set() is False
    finti.lavori[FACCE].funzioni[0]()
    assert imparate == [(7, Path(RITRATTI))]


def test_imparare_le_facce_usa_il_freno(finti, monkeypatch):
    freni = []

    def insegna(archivio, persona_id, cartella, fermato=None):
        freni.append(fermato)
        return riferimento.Raccolto()

    monkeypatch.setattr(persone.volti_riferimento, "insegna", insegna)
    persone._impara_le_facce(_aperto(), 7, Path(RITRATTI))
    assert freni[0]() is False
    comune.facce_basta.set()
    assert freni[0]() is True
    assert finti.lavori[FACCE].righe == ["niente da imparare"]


def test_insegnare_si_ferma_fra_una_foto_e_l_altra(archivio, cartella_ritratti):
    with archivio.scrittura() as connessione:
        chi = persone_mod.crea(connessione, "Marco")
    chieste = []

    def fermato() -> bool:
        chieste.append(1)
        return len(chieste) > 1

    rilevatore = RilevatoreFinto()
    fuori = riferimento.insegna(archivio, chi, cartella_ritratti, rilevatore=rilevatore,
                                fermato=fermato)
    assert fuori.lette == 1 and fuori.con_piu_facce == ["due-facce.jpg"]
    assert rilevatore.spento is True
    subito = riferimento.insegna(archivio, chi, cartella_ritratti,
                                 rilevatore=RilevatoreFinto(), fermato=lambda: True)
    assert subito.lette == 0 and subito.a_parole() == "niente da imparare"
    tutte = riferimento.insegna(archivio, chi, cartella_ritratti,
                                rilevatore=RilevatoreFinto(), fermato=lambda: False)
    assert tutte.lette == 3 and tutte.imparate == 1


def test_contare_non_cancella_una_ricerca_che_aspetta(per_la_copia, finti):
    per_la_copia.giro(True)
    assert doppioni.cerca_i_doppioni(_aperto()) is False
    assert doppioni.cerca_i_doppioni(_aperto(), doppioni.CONTA) is False
    assert per_la_copia.carta.scritta["lavori"] == {DOPPIONI: {"come": "guarda"}}


def test_una_ricerca_vale_piu_di_un_conto_che_aspetta(per_la_copia, finti):
    per_la_copia.giro(True)
    assert doppioni.cerca_i_doppioni(_aperto(), doppioni.CONTA) is False
    assert per_la_copia.carta.scritta["lavori"] == {DOPPIONI: {"come": "conta"}}
    assert doppioni.cerca_i_doppioni(_aperto()) is False
    assert per_la_copia.carta.scritta["lavori"] == {DOPPIONI: {"come": "guarda"}}


def test_i_doppioni_si_cercano_o_si_contano_e_basta(per_la_copia, finti):
    per_la_copia.giro(True)
    with pytest.raises(ValueError):
        doppioni.cerca_i_doppioni(_aperto(), "boh")
    assert per_la_copia.sosta.in_attesa() == []


def test_il_conto_qui_parte_dal_conto(finti, monkeypatch):
    monkeypatch.setattr(in_disparte, "A_PARTE", False)
    contati = []
    monkeypatch.setattr(doppioni, "_solo_il_conto", contati.append)
    archivio = _aperto()
    finti.lavori[DOPPIONI].numeri = {"vecchi": 1}
    assert doppioni.cerca_i_doppioni(archivio, doppioni.CONTA) is True
    assert finti.lavori[DOPPIONI].numeri == {"fatte": 0, "totale": 0, "gruppi": None}
    finti.lavori[DOPPIONI].funzioni[0]()
    assert contati == [archivio]
    assert doppioni.doppioni_chiesti() == {"come": "conta"}


def test_conto_e_ricerca_a_parte_partono_ognuno_per_conto_suo(finti, monkeypatch):
    avvii = []
    monkeypatch.setattr(in_disparte, "A_PARTE", True)
    monkeypatch.setattr(in_disparte, "lancia",
                        lambda lavoro, a, nome, avvio, *resto, **opzioni:
                        avvii.append((a, nome, avvio, opzioni)) or True)
    assert doppioni.cerca_i_doppioni(_aperto(), doppioni.CONTA) is True
    assert doppioni.cerca_i_doppioni(_aperto()) is True
    assert avvii == [
        ("doppioni", REALE, "officina.web.strade.doppioni:conto_di_la", {}),
        ("doppioni", REALE, "officina.web.strade.doppioni:doppioni_di_la",
         {"ferma_con": "officina.web.strade.doppioni:ferma_di_la"})]
    assert doppioni.doppioni_chiesti() == {"come": "guarda"}


@pytest.mark.parametrize("come", [doppioni.GUARDA, doppioni.CONTA])
def test_i_doppioni_ripartono_come_erano_stati_chiesti(vera, finti, monkeypatch, come):
    monkeypatch.setattr(in_disparte, "A_PARTE", False)
    contati = []
    monkeypatch.setattr(doppioni, "_solo_il_conto", contati.append)
    vera.giro(True)
    assert doppioni.cerca_i_doppioni(vera.archivio, come) is False
    vera.giro(False)
    assert comune.doppioni_come == come
    funzione = finti.lavori[DOPPIONI].funzioni[0]
    assert (funzione is None) == (come == doppioni.GUARDA)


def test_i_doppioni_dopo_l_importazione_aspettano_la_copia(per_la_copia, finti,
                                                           monkeypatch):
    monkeypatch.setattr(accesso, "in_prova", lambda: False)
    monkeypatch.setattr(accesso, "aperto", _aperto)
    per_la_copia.giro(True)
    doppioni.doppioni_dopo_l_importazione()
    assert per_la_copia.sosta.in_attesa() == [DOPPIONI]
    assert finti.lavori[DOPPIONI].partiti == []


def test_il_controllo_degli_scatti_non_toglie_il_freno_a_chi_lavora(finti, monkeypatch):
    monkeypatch.setattr(in_disparte, "A_PARTE", False)
    controllati = []
    monkeypatch.setattr(strade_miglioramento, "_controlla_la_qualita", controllati.append)
    comune.ferma_la_qualita.set()
    finti.lavori[QUALITA].sta_lavorando = True
    assert strade_miglioramento.controlla_la_qualita_in(_aperto()) is False
    assert comune.ferma_la_qualita.is_set() and finti.lavori[QUALITA].numeri == {}
    finti.lavori[QUALITA].sta_lavorando = False
    archivio = _aperto()
    assert strade_miglioramento.controlla_la_qualita_in(archivio) is True
    assert comune.ferma_la_qualita.is_set() is False
    assert finti.lavori[QUALITA].numeri == {"fatti": 0, "totale": 0, "corretti": 0,
                                            "non_si_aprono": 0}
    finti.lavori[QUALITA].funzioni[0]()
    assert controllati == [archivio]


def test_il_controllo_a_parte_si_ferma_di_la(finti, monkeypatch):
    avvii = []
    monkeypatch.setattr(in_disparte, "A_PARTE", True)
    monkeypatch.setattr(in_disparte, "lancia",
                        lambda lavoro, a, nome, avvio, *resto, **opzioni:
                        avvii.append((a, avvio, opzioni)) or True)
    assert strade_miglioramento.controlla_la_qualita_in(_aperto()) is True
    assert avvii == [("qualita", "officina.web.strade.miglioramento:qualita_di_la",
                      {"ferma_con": "officina.web.strade.miglioramento:"
                                    "ferma_la_qualita_di_la"})]


def test_fermare_dalle_pagine_vuol_dire_non_ripartire_anche_da_soli(cliente, per_la_copia,
                                                                    finti):
    per_la_copia.giro(True)
    for nome in DA_SOLI:
        per_la_copia.sosta.aspetta(nome)
    for strada in ("/misura/impronte/ferma", "/persone/trova/ferma", "/parole/ferma",
                   "/doppioni/ferma"):
        assert cliente.post(strada, follow_redirects=False).status_code == 303
    assert cliente.post("/api/miglioramento/qualita/ferma").json()[
        "aspetta_la_copia"] is False
    assert per_la_copia.sosta.in_attesa() == [CHI_E, FACCE]
    assert finti.a_parte == ["doppioni", "qualita"]


def test_avviare_dalle_pagine_durante_la_copia_aspetta_anche_da_soli(
        cliente, per_la_copia, finti, tmp_path):
    per_la_copia.giro(True)
    for strada, dati in (("/misura/impronte", {"descrittore": "d"}), ("/persone/trova", {}),
                         ("/parole/leggi", {}),
                         ("/persone/7/insegna", {"cartella": str(tmp_path)}),
                         ("/doppioni/guarda", {}), ("/doppioni/conta", {})):
        assert cliente.post(strada, data=dati, follow_redirects=False).status_code == 303
    assert cliente.post("/api/miglioramento/qualita/controlla").json()[
        "aspetta_la_copia"] is True
    assert per_la_copia.sosta.in_attesa() == [IMPRONTE, VOLTI, SCRITTE, FACCE, DOPPIONI,
                                              QUALITA]
    lavori_ricordati = per_la_copia.carta.scritta["lavori"]
    assert lavori_ricordati[FACCE] == {"persona_id": 7, "cartella": str(tmp_path)}
    assert lavori_ricordati[DOPPIONI] == {"come": "guarda"}
    assert lavori_ricordati[IMPRONTE] == {"descrittore": "d"}
    assert all(finti.lavori[nome].partiti == [] for nome in DA_SOLI)


def test_contare_i_doppioni_dalla_pagina_durante_la_copia_si_ricorda_di_contare(
        cliente, per_la_copia, finti):
    per_la_copia.giro(True)
    assert cliente.post("/doppioni/conta", follow_redirects=False).status_code == 303
    assert per_la_copia.carta.scritta["lavori"] == {DOPPIONI: {"come": "conta"}}
    assert finti.lavori[DOPPIONI].partiti == []


def test_le_strade_dei_lavori_da_soli_dicono_se_aspettano_la_copia(cliente, per_la_copia,
                                                                   finti):
    strade = {IMPRONTE: "/api/impronte", VOLTI: "/api/volti", SCRITTE: "/api/parole",
              FACCE: "/api/riferimento", DOPPIONI: "/api/doppioni",
              QUALITA: "/api/miglioramento/qualita/controllo"}

    def dicono() -> dict:
        return {nome: cliente.get(strada).json()["aspetta_la_copia"]
                for nome, strada in strade.items()}

    assert dicono() == dict.fromkeys(strade, False)
    per_la_copia.giro(True)
    for nome in strade:
        per_la_copia.sosta.aspetta(nome)
        assert dicono() == {altro: altro == nome for altro in strade}
        per_la_copia.sosta.fermato_da_te(nome)


def test_le_impronte_in_corso_dicono_anche_loro_se_aspettano(cliente, per_la_copia, finti,
                                                             monkeypatch):
    monkeypatch.setattr(comune, "coda_impronte", CodaVera(accesso.aperto(), []))
    assert cliente.get("/api/impronte").json()["aspetta_la_copia"] is False
    per_la_copia.giro(True)
    per_la_copia.sosta.aspetta(IMPRONTE)
    detto = cliente.get("/api/impronte").json()
    assert detto["aspetta_la_copia"] is True and detto["nomi"] == []
