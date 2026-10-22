from __future__ import annotations

import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from officina import forziere
from officina.errori import ErroreOfficina, PasswordSbagliata
from officina.impostazioni import Posizione
from officina.programma import archivio_sicuro, carta
from officina.programma.archivio_sicuro import (APERTO, ASSENTE, CHIUSO, GUASTO,
                                                PASSWORD_DIVERSA, SENZA_CHIAVE, SI_APRE,
                                                Collegamento)
from officina.sicuro import chiavi
from officina.sicuro import servizio as modulo
from officina.sicuro.servizio import ArchivioSicuro
from prove import test_sicuro_servizio as servizio_di_prova
from prove.test_sicuro_copia import _dati
from prove.test_sicuro_servizio import ATTESA, Casa, _finche

costo_leggero = servizio_di_prova.costo_leggero

PAROLA = "tre parole che ricordo"
NUOVA = "quattro parole nuove davvero"
DEL_FORZIERE = "la password del forziere"
CORTA = "otto cara"


@pytest.fixture(autouse=True)
def forziere_leggero(monkeypatch):
    monkeypatch.setattr(forziere, "COSTO", 2 ** 10)


def _leggero(base: Path):
    attorno = base / "attorno"
    attorno.mkdir(parents=True)
    finta = Casa(attorno)

    def fabbrica(dove, salta, programmino):
        return ArchivioSicuro(dove, salta=salta, cestino=finta.cestino,
                              programmino=programmino, opzioni=finta._opzioni())

    return finta, fabbrica


class Posto:

    def __init__(self, base: Path):
        self.base = base
        self.posizione = Posizione(base / "dati" / "reale", "reale")
        self.radice = Path(self.posizione.radice)
        self.radice.mkdir(parents=True)
        (self.radice / "archivio.sqlite").write_bytes(b"un archivio finto")
        self.finta, self.fabbrica = _leggero(base)
        self.cassa = forziere.per(self.posizione)
        self.cartella = archivio_sicuro.cartella(self.posizione)
        self.collegamenti: list[Collegamento] = []
        self.collegamento = self.nuovo()
        self.richiusi: list[str] = []
        self.rimessi: list[str] = []
        self.sigillati: list[str] = []

    def nuovo(self) -> Collegamento:
        collegamento = Collegamento(self.posizione, fabbrica=self.fabbrica)
        self.collegamenti.append(collegamento)
        return collegamento

    def accendi(self, parola: str = PAROLA) -> None:
        self.cassa.accendi(parola)
        self.cassa.apri(parola)

    def crea(self, parola: str = PAROLA) -> None:
        if not self.cassa.acceso:
            self.accendi(parola)
        self.collegamento.crea(parola, parola, True, accendi_il_forziere=self._non_serve)

    @staticmethod
    def _non_serve(parola: str) -> None:
        raise AssertionError("il forziere era già acceso")

    def riparti(self) -> Collegamento:
        vecchio = self.collegamento
        vecchio.chiudi(ATTESA)
        self.collegamento = self.nuovo()
        return self.collegamento

    def richiudi(self, nuova: str) -> None:
        self.richiusi.append(nuova)
        self.cassa.chiudi(nuova)
        self.cassa.apri(nuova)

    def rimetti(self, vecchia: str) -> None:
        self.rimessi.append(vecchia)

    def sigilla(self, nuova: str) -> None:
        self.sigillati.append(nuova)

    def cambia(self, vecchia: str = PAROLA, nuova: str = NUOVA, ancora: str | None = None,
               **cambi) -> list[str]:
        fare = {"richiudi": self.richiudi, "rimetti": self.rimetti,
                "sigilla": self.sigilla, **cambi}
        return self.collegamento.cambia_la_password(
            vecchia, nuova, nuova if ancora is None else ancora, **fare)

    def si_apre_con(self, parola: str) -> bool:
        try:
            chiavi.apri(self.cartella, parola, ripara=False)
        except PasswordSbagliata:
            return False
        return True

    def chiudi(self) -> None:
        for collegamento in self.collegamenti:
            collegamento.chiudi(ATTESA)
            collegamento._aspetta_l_apertura(ATTESA)
            assert not collegamento._apre()
            servizio = collegamento._servizio
            assert servizio is None or not servizio.aperto
        modulo.imposta(None)


@pytest.fixture
def posto(tmp_path, monkeypatch):
    monkeypatch.setenv("OFFICINA_CASA_PROGRAMMA", str(tmp_path / "casa"))
    posto = Posto(tmp_path)
    yield posto
    posto.chiudi()


def _codice(fare) -> str:
    with pytest.raises(ErroreOfficina) as preso:
        fare()
    return preso.value.codice


def _aspetta(collegamento: Collegamento) -> str:
    collegamento._aspetta_l_apertura(ATTESA)
    assert not collegamento._apre()
    return collegamento.guarda()


def test_senza_archivio_lo_stato_e_assente_e_hello_va_bene(posto):
    assert posto.collegamento.guarda() == ASSENTE
    assert not archivio_sicuro.c_e(posto.posizione)
    assert not archivio_sicuro.serve_la_password_scritta(posto.posizione)
    assert posto.collegamento.apri_in_sottofondo(PAROLA) == ASSENTE
    assert not posto.collegamento._apre()
    assert posto.collegamento.messaggio == archivio_sicuro.ASSENTE_A_PAROLE


def test_la_cartella_dell_archivio_sta_accanto_al_forziere(posto):
    assert posto.cartella == posto.base / "dati" / "reale.sicuro"
    assert posto.cassa.file.parent == posto.cartella.parent


def test_si_crea_con_la_password_del_forziere(posto):
    posto.crea()
    assert posto.collegamento.guarda() == APERTO
    assert posto.si_apre_con(PAROLA)
    assert chiavi.porte(posto.cartella) == 1
    assert archivio_sicuro.c_e(posto.posizione)
    assert not archivio_sicuro.serve_la_password_scritta(posto.posizione)
    assert modulo.attuale() is posto.collegamento.servizio


@pytest.mark.parametrize("ho_capito, ancora, codice", [
    (False, PAROLA, "manca_ho_capito"),
    (True, PAROLA + " ", "non_coincidono"),
])
def test_senza_ho_capito_o_con_due_password_diverse_non_si_crea(posto, ho_capito, ancora,
                                                                 codice):
    posto.accendi()
    assert _codice(lambda: posto.collegamento.crea(
        PAROLA, ancora, ho_capito, accendi_il_forziere=posto._non_serve)) == codice
    assert not posto.cartella.exists()


def test_con_il_forziere_acceso_serve_la_sua_password(posto):
    posto.accendi()
    assert _codice(lambda: posto.collegamento.crea(
        NUOVA, NUOVA, True, accendi_il_forziere=posto._non_serve)) == \
        "non_e_quella_del_forziere"
    assert not posto.cartella.exists()


def test_se_la_password_del_forziere_e_corta_prima_si_cambia(posto, monkeypatch):
    monkeypatch.setattr(forziere, "MINIMO_NUOVA", 8)
    posto.accendi(CORTA)
    with pytest.raises(ErroreOfficina) as preso:
        posto.collegamento.crea(CORTA, CORTA, True, accendi_il_forziere=posto._non_serve)
    assert preso.value.codice == "forziere_corta"
    assert preso.value.messaggio == archivio_sicuro.FORZIERE_CORTA
    assert not posto.cartella.exists()


def test_col_forziere_spento_prima_si_accende_il_forziere_e_poi_l_archivio(posto):
    accesi = []

    def accendi(parola):
        accesi.append(parola)
        posto.accendi(parola)

    posto.collegamento.crea(PAROLA, PAROLA, True, accendi_il_forziere=accendi)
    assert accesi == [PAROLA]
    assert posto.cassa.la_password_e_giusta(PAROLA)
    assert posto.si_apre_con(PAROLA)
    assert posto.collegamento.guarda() == APERTO


def test_col_forziere_spento_e_la_password_corta_non_si_accende_niente(posto):
    accesi = []
    assert _codice(lambda: posto.collegamento.crea(
        CORTA, CORTA, True, accendi_il_forziere=accesi.append)) == "password_corta"
    assert accesi == []
    assert not posto.cassa.acceso and not posto.cartella.exists()


def test_se_il_forziere_non_si_accende_l_archivio_non_si_crea(posto):
    assert _codice(lambda: posto.collegamento.crea(
        PAROLA, PAROLA, True, accendi_il_forziere=lambda parola: None)) == \
        "forziere_non_acceso"
    assert not posto.cartella.exists()


def test_se_l_accensione_del_forziere_si_rompe_l_archivio_non_si_crea(posto):
    def rotta(parola):
        raise ErroreOfficina("Windows Hello annullato.", codice="annullato")

    assert _codice(lambda: posto.collegamento.crea(
        PAROLA, PAROLA, True, accendi_il_forziere=rotta)) == "annullato"
    assert not posto.cartella.exists()


def test_non_si_crea_due_volte(posto):
    posto.crea()
    assert _codice(lambda: posto.collegamento.crea(
        PAROLA, PAROLA, True, accendi_il_forziere=posto._non_serve)) == "chiave_esiste"
    posto.riparti()
    assert _codice(lambda: posto.collegamento.crea(
        PAROLA, PAROLA, True, accendi_il_forziere=posto._non_serve)) == "chiave_esiste"
    assert chiavi.porte(posto.cartella) == 1


def test_se_la_creazione_si_rompe_lo_stato_torna_dal_disco(posto, monkeypatch):
    posto.accendi()

    def rotta(parola, costo=None):
        raise OSError("disco pieno")

    monkeypatch.setattr(posto.collegamento.servizio, "crea", rotta)
    with pytest.raises(OSError):
        posto.collegamento.crea(PAROLA, PAROLA, True, accendi_il_forziere=posto._non_serve)
    assert posto.collegamento.stato == ASSENTE


def test_all_avvio_si_apre_da_solo_con_la_password_del_forziere(posto):
    posto.crea()
    collegamento = posto.riparti()
    assert collegamento.guarda() == CHIUSO
    assert collegamento.apri_in_sottofondo(PAROLA) == SI_APRE
    assert _aspetta(collegamento) == APERTO
    assert collegamento.servizio.aperto


def test_senza_password_all_avvio_resta_chiuso_e_lo_dice(posto):
    posto.crea()
    collegamento = posto.riparti()
    assert collegamento.apri_in_sottofondo(None) == CHIUSO
    assert not collegamento._apre()
    assert collegamento.messaggio == archivio_sicuro.CHIUSO_A_PAROLE


def test_aprire_in_sottofondo_due_volte_parte_una_volta(posto):
    posto.crea()
    collegamento = posto.riparti()
    collegamento.apri_in_sottofondo(PAROLA)
    filo = collegamento._filo
    collegamento.apri_in_sottofondo(PAROLA)
    assert collegamento._filo is filo
    assert _aspetta(collegamento) == APERTO
    assert collegamento.apri_in_sottofondo(PAROLA) == APERTO
    assert collegamento._filo is filo


def test_se_la_password_del_forziere_non_apre_si_vede_la_striscia_rossa(posto):
    posto.crea()
    collegamento = posto.riparti()
    collegamento.apri_in_sottofondo(DEL_FORZIERE)
    assert _aspetta(collegamento) == PASSWORD_DIVERSA
    assert collegamento.messaggio == archivio_sicuro.PASSWORD_DIVERSA_A_PAROLE
    assert collegamento.codice == "password_diversa"
    assert collegamento.guarda() == PASSWORD_DIVERSA
    assert collegamento.apri_in_sottofondo(DEL_FORZIERE) == PASSWORD_DIVERSA
    assert not collegamento._apre()
    assert not collegamento.servizio.aperto
    assert collegamento.lavori_tuoi() == []
    assert posto.si_apre_con(PAROLA) and chiavi.porte(posto.cartella) == 1


def test_scritta_la_password_dell_archivio_le_due_tornano_uguali(posto):
    posto.crea()
    collegamento = posto.riparti()
    collegamento.apri_in_sottofondo(DEL_FORZIERE)
    _aspetta(collegamento)
    assert collegamento.apri_con_la_password(PAROLA, DEL_FORZIERE) == []
    assert collegamento.guarda() == APERTO
    assert posto.si_apre_con(DEL_FORZIERE)
    assert not posto.si_apre_con(PAROLA)
    assert chiavi.porte(posto.cartella) == 1


def test_se_la_password_del_forziere_e_corta_l_archivio_si_apre_e_lo_dice(posto):
    posto.crea()
    collegamento = posto.riparti()
    assert collegamento.apri_con_la_password(PAROLA, CORTA) == ["forziere_corta"]
    assert collegamento.guarda() == APERTO
    assert posto.si_apre_con(PAROLA) and chiavi.porte(posto.cartella) == 1


def test_se_non_riesco_a_togliere_la_vecchia_restano_buone_tutte_e_due(posto, monkeypatch):
    posto.crea()
    collegamento = posto.riparti()

    def rotta(password):
        raise OSError("disco staccato")

    monkeypatch.setattr(collegamento.servizio, "tieni_solo", rotta)
    assert collegamento.apri_con_la_password(PAROLA, DEL_FORZIERE) == [
        "password_vecchia_ancora_buona"]
    assert posto.si_apre_con(PAROLA) and posto.si_apre_con(DEL_FORZIERE)


def test_se_non_riesco_ad_aggiungere_quella_del_forziere_resta_la_sua(posto, monkeypatch):
    posto.crea()
    collegamento = posto.riparti()

    def rotta(nuova):
        raise OSError("disco staccato")

    monkeypatch.setattr(collegamento.servizio, "aggiungi_password", rotta)
    assert collegamento.apri_con_la_password(PAROLA, DEL_FORZIERE) == [
        "password_non_riallineata"]
    assert collegamento.guarda() == APERTO
    assert posto.si_apre_con(PAROLA) and not posto.si_apre_con(DEL_FORZIERE)


def test_se_il_riallineo_si_ferma_non_si_perde_nessuna_password(posto, monkeypatch):
    posto.crea()

    def rotta(password):
        raise OSError("disco staccato")

    with monkeypatch.context() as rotto:
        rotto.setattr(posto.collegamento.servizio, "tieni_solo", rotta)
        assert posto.cambia() == ["password_vecchia_ancora_buona"]
    posto.cassa.chiudi(DEL_FORZIERE)
    collegamento = posto.riparti()
    collegamento.apri_in_sottofondo(DEL_FORZIERE)
    assert _aspetta(collegamento) == PASSWORD_DIVERSA
    with monkeypatch.context() as rotto:
        rotto.setattr(collegamento.servizio, "aggiungi_password", rotta)
        assert collegamento.apri_con_la_password(PAROLA, DEL_FORZIERE) == [
            "password_non_riallineata"]
    assert chiavi.porte(posto.cartella) == 2
    assert posto.si_apre_con(PAROLA) and posto.si_apre_con(NUOVA)


def test_con_la_stessa_password_del_forziere_non_c_e_niente_da_riallineare(posto):
    posto.crea()
    collegamento = posto.riparti()
    assert collegamento.apri_con_la_password(PAROLA, PAROLA) == []
    assert collegamento.apri_con_la_password(PAROLA, PAROLA) == []
    assert chiavi.porte(posto.cartella) == 1


def test_la_password_sbagliata_non_cambia_niente(posto):
    posto.crea()
    collegamento = posto.riparti()
    collegamento.apri_in_sottofondo(DEL_FORZIERE)
    _aspetta(collegamento)
    with pytest.raises(PasswordSbagliata):
        collegamento.apri_con_la_password(NUOVA, DEL_FORZIERE)
    with pytest.raises(PasswordSbagliata):
        collegamento.apri_con_la_password("", DEL_FORZIERE)
    assert collegamento.guarda() == PASSWORD_DIVERSA
    assert posto.si_apre_con(PAROLA) and chiavi.porte(posto.cartella) == 1


def test_senza_archivio_non_si_apre_niente_a_mano(posto):
    assert _codice(lambda: posto.collegamento.apri_con_la_password(PAROLA, None)) == \
        "sicuro_mancante"
    assert not posto.cartella.exists()


def test_una_cartella_con_dei_file_ma_senza_chiave_non_si_tocca(posto):
    posto.cartella.mkdir()
    (posto.cartella / "contenuti").mkdir()
    collegamento = posto.collegamento
    assert collegamento.guarda() == SENZA_CHIAVE
    assert collegamento.messaggio == archivio_sicuro.SENZA_CHIAVE_A_PAROLE
    assert archivio_sicuro.c_e(posto.posizione)
    assert collegamento.apri_in_sottofondo(PAROLA) == SENZA_CHIAVE
    assert _codice(lambda: collegamento.apri_con_la_password(PAROLA, None)) == "senza_chiave"
    posto.accendi()
    assert _codice(lambda: collegamento.crea(
        PAROLA, PAROLA, True, accendi_il_forziere=posto._non_serve)) == "senza_chiave"
    assert sorted(voce.name for voce in posto.cartella.iterdir()) == ["contenuti"]


@pytest.mark.parametrize("nome", [chiavi.FILE + ".nuovo", chiavi.RISERVA + ".nuovo"])
def test_gli_avanzi_di_una_prima_creazione_non_contano_come_archivio(posto, nome):
    posto.cartella.mkdir()
    (posto.cartella / nome).write_bytes(b"{mezzo")
    assert not archivio_sicuro.c_e(posto.posizione)
    assert posto.collegamento.guarda() == ASSENTE


def test_se_la_cartella_non_si_legge_conta_come_archivio(posto):
    posto.cartella.parent.mkdir(parents=True, exist_ok=True)
    posto.cartella.write_bytes(b"un file al posto della cartella")
    assert archivio_sicuro.c_e(posto.posizione)
    assert posto.collegamento.guarda() == GUASTO
    assert posto.collegamento.messaggio == archivio_sicuro.CARTELLA_NON_SI_LEGGE
    assert archivio_sicuro.serve_la_password_scritta(posto.posizione)


def test_una_chiave_rovinata_si_dice_e_si_riprova(posto):
    posto.crea()
    collegamento = posto.riparti()
    for nome in (chiavi.FILE, chiavi.RISERVA):
        (posto.cartella / nome).write_bytes(b"rovinata")
    collegamento.apri_in_sottofondo(PAROLA)
    assert _aspetta(collegamento) == GUASTO
    assert collegamento.codice == "chiave_rovinata"
    assert collegamento.guarda() == GUASTO
    assert collegamento.apri_in_sottofondo(PAROLA) == GUASTO
    assert collegamento.riprova(PAROLA) == SI_APRE
    assert _aspetta(collegamento) == GUASTO


def test_un_guasto_che_non_avevo_previsto_lascia_l_archivio_chiuso(posto, monkeypatch):
    posto.crea()
    collegamento = posto.riparti()
    giri = []

    def rotta(password, **parole):
        giri.append(password)
        if len(giri) == 1:
            raise RuntimeError("non previsto")
        return vera(password, **parole)

    vera = collegamento.servizio.apri
    monkeypatch.setattr(collegamento.servizio, "apri", rotta)
    collegamento.apri_in_sottofondo(PAROLA)
    assert _aspetta(collegamento) == GUASTO
    assert collegamento.messaggio == archivio_sicuro.NON_SI_APRE
    assert collegamento.riprova(PAROLA) == SI_APRE
    assert _aspetta(collegamento) == APERTO
    assert giri == [PAROLA, PAROLA]


def test_se_il_disco_non_risponde_mentre_si_apre_lo_dice(posto, monkeypatch):
    posto.crea()
    collegamento = posto.riparti()

    def rotta(password, **parole):
        raise OSError("disco staccato")

    monkeypatch.setattr(collegamento.servizio, "apri", rotta)
    collegamento.apri_in_sottofondo(PAROLA)
    assert _aspetta(collegamento) == GUASTO
    assert collegamento.messaggio == archivio_sicuro.CARTELLA_NON_SI_LEGGE
    with pytest.raises(ErroreOfficina) as preso:
        collegamento.apri_con_la_password(PAROLA, None)
    assert preso.value.codice == "cartella_non_si_legge"
    assert collegamento.guarda() == GUASTO


def test_riprova_dopo_la_striscia_rossa_riparte_dal_disco(posto):
    posto.crea()
    collegamento = posto.riparti()
    collegamento.apri_in_sottofondo(DEL_FORZIERE)
    _aspetta(collegamento)
    assert collegamento.riprova(PAROLA) == SI_APRE
    assert _aspetta(collegamento) == APERTO


def test_se_si_chiude_mentre_si_apre_l_archivio_non_resta_aperto(posto, monkeypatch):
    posto.crea()
    collegamento = posto.riparti()
    entrato, via = threading.Event(), threading.Event()
    vera = collegamento.servizio.apri

    def lenta(password, **parole):
        entrato.set()
        assert via.wait(ATTESA)
        return vera(password, **parole)

    monkeypatch.setattr(collegamento.servizio, "apri", lenta)
    collegamento.apri_in_sottofondo(PAROLA)
    assert entrato.wait(ATTESA)
    assert collegamento.chiudi(0.05)
    via.set()
    collegamento._aspetta_l_apertura(ATTESA)
    assert not collegamento._apre()
    assert not collegamento.servizio.aperto
    assert collegamento.guarda() == CHIUSO


def test_dopo_la_chiusura_non_si_apre_e_non_si_crea_piu_niente(posto):
    posto.crea()
    collegamento = posto.collegamento
    assert collegamento.chiudi(ATTESA)
    assert not collegamento.servizio.aperto
    assert modulo.attuale() is None
    assert collegamento.guarda() == CHIUSO
    assert collegamento.apri_in_sottofondo(PAROLA) == CHIUSO
    assert not collegamento._apre()
    assert _codice(lambda: collegamento.apri_con_la_password(PAROLA, None)) == "si_chiude"
    assert _codice(lambda: posto.cambia()) == "si_chiude"
    assert collegamento.chiudi(ATTESA)


def test_chiudere_senza_aver_mai_aperto_va_bene(posto):
    assert posto.collegamento.chiudi(ATTESA)
    assert posto.collegamento._servizio is None


def test_una_volta_al_mese_la_password_si_scrive_a_mano(posto):
    adesso = 1_800_000_000.0
    assert not archivio_sicuro.serve_la_password_scritta(posto.posizione, adesso)
    posto.cartella.mkdir()
    (posto.cartella / chiavi.FILE).write_bytes(b"{}")
    assert archivio_sicuro.serve_la_password_scritta(posto.posizione, adesso)
    archivio_sicuro.password_scritta(adesso)
    assert not archivio_sicuro.serve_la_password_scritta(posto.posizione, adesso)
    quasi = adesso + archivio_sicuro.MESE - 1
    assert not archivio_sicuro.serve_la_password_scritta(posto.posizione, quasi)
    passato = adesso + archivio_sicuro.MESE
    assert archivio_sicuro.serve_la_password_scritta(posto.posizione, passato)
    assert archivio_sicuro.serve_la_password_scritta(posto.posizione, adesso - 1)


@pytest.mark.parametrize("scritto", [True, "ieri", None, [1], float("nan")])
def test_una_data_strana_vuol_dire_scrivila(posto, scritto):
    posto.cartella.mkdir()
    (posto.cartella / chiavi.FILE).write_bytes(b"{}")
    carta.aggiorna(**{archivio_sicuro.SCRITTA_IL: scritto})
    assert archivio_sicuro.serve_la_password_scritta(posto.posizione, 1_800_000_000.0)


def test_aprire_e_creare_a_mano_contano_come_password_scritta(posto):
    posto.crea()
    assert carta.leggi()[archivio_sicuro.SCRITTA_IL] <= time.time()
    carta.aggiorna(**{archivio_sicuro.SCRITTA_IL: None})
    collegamento = posto.riparti()
    collegamento.apri_in_sottofondo(PAROLA)
    _aspetta(collegamento)
    assert archivio_sicuro.SCRITTA_IL not in carta.leggi()
    collegamento = posto.riparti()
    collegamento.apri_con_la_password(PAROLA, PAROLA)
    assert archivio_sicuro.SCRITTA_IL in carta.leggi()


def test_se_la_carta_non_si_scrive_l_archivio_si_apre_lo_stesso(posto, monkeypatch):
    posto.crea()
    collegamento = posto.riparti()

    def rotta(**campi):
        raise OSError("carta in sola lettura")

    monkeypatch.setattr(carta, "aggiorna", rotta)
    assert collegamento.apri_con_la_password(PAROLA, None) == []
    assert collegamento.guarda() == APERTO


def _cartella_con_le_foto(posto) -> Path:
    cartella = posto.finta.metti("vacanze/a.jpg", _dati(100, 1)).parent
    posto.finta.metti("vacanze/b.jpg", _dati(200, 2))
    return cartella


def test_la_prima_copia_si_ricorda_finche_non_e_finita(posto):
    posto.crea()
    collegamento = posto.collegamento
    servizio = collegamento.servizio
    assert not collegamento.prima_copia_in_corso()
    servizio.pausa("copia")
    nuove = collegamento.copia_tutto([_cartella_con_le_foto(posto)])
    assert carta.leggi()[archivio_sicuro.PRIMA_COPIA] == [nuove[0]["id"]]
    assert collegamento.prima_copia_in_corso()
    assert collegamento.lavori_tuoi() == [archivio_sicuro.PRIMA_COPIA_A_PAROLE]
    assert collegamento.istantanea()["prima_copia"] is True
    servizio.riprendi("copia")
    _finche(lambda: not collegamento.prima_copia_in_corso())
    assert archivio_sicuro.PRIMA_COPIA not in carta.leggi()
    assert collegamento.lavori_tuoi() == []


def test_la_prima_copia_interrotta_si_ricorda_anche_alla_riapertura(posto):
    posto.crea()
    posto.collegamento.servizio.pausa("copia")
    posto.collegamento.copia_tutto([_cartella_con_le_foto(posto)])
    collegamento = posto.riparti()
    assert not collegamento.prima_copia_in_corso()
    assert archivio_sicuro.PRIMA_COPIA in carta.leggi()
    collegamento.apri_in_sottofondo(PAROLA)
    _aspetta(collegamento)
    _finche(lambda: not collegamento.prima_copia_in_corso())
    assert archivio_sicuro.PRIMA_COPIA not in carta.leggi()


def test_le_cartelle_che_arrivano_dopo_non_sono_la_prima_copia(posto):
    posto.crea()
    collegamento = posto.collegamento
    collegamento.copia_tutto([_cartella_con_le_foto(posto)])
    _finche(lambda: not collegamento.prima_copia_in_corso())
    altra = posto.finta.metti("altro/c.jpg", _dati(300, 3)).parent
    collegamento.servizio.pausa("copia")
    assert collegamento.servizio.metti_le_cartelle([altra])
    assert not collegamento.prima_copia_in_corso()
    assert archivio_sicuro.PRIMA_COPIA not in carta.leggi()


def test_se_la_carta_non_si_scrive_la_copia_parte_lo_stesso(posto, monkeypatch):
    posto.crea()

    def rotta(**campi):
        raise OSError("carta in sola lettura")

    with monkeypatch.context() as rotto:
        rotto.setattr(carta, "aggiorna", rotta)
        assert posto.collegamento.copia_tutto([_cartella_con_le_foto(posto)])
    assert archivio_sicuro.PRIMA_COPIA not in carta.leggi()
    _finche(lambda: posto.collegamento.servizio.da_finire() == set())


def test_un_id_della_prima_copia_che_non_c_e_piu_si_dimentica(posto):
    posto.crea()
    carta.aggiorna(**{archivio_sicuro.PRIMA_COPIA: ["non-c-e", 7]})
    assert not posto.collegamento.prima_copia_in_corso()
    assert archivio_sicuro.PRIMA_COPIA not in carta.leggi()


def test_i_tuoi_lavori_hanno_un_nome_da_dire(posto, monkeypatch):
    posto.crea()
    servizio = posto.collegamento.servizio
    monkeypatch.setattr(servizio, "tuoi_accesi", lambda: ["verifica", "estrai", "nuovo"])
    assert posto.collegamento.lavori_tuoi() == [
        "il controllo «È già tutto dentro?»", "un'estrazione", "nuovo"]


def test_il_servizio_dice_quali_dei_tuoi_lavori_sono_accesi(posto, monkeypatch):
    posto.crea()
    servizio = posto.collegamento.servizio
    accesi = {"verifica": SimpleNamespace(acceso=True),
              "estrai": SimpleNamespace(acceso=False),
              "ripara": SimpleNamespace(acceso=True)}
    with monkeypatch.context() as finto:
        finto.setattr(servizio._aperto, "tuoi", lambda: accesi)
        assert servizio.tuoi_accesi() == ["verifica", "ripara"]
    servizio.chiudi(ATTESA)
    assert servizio.tuoi_accesi() == []
    assert servizio.da_finire() is None


def test_ad_elenco_chiuso_non_si_sa_cosa_resta_da_finire(posto):
    posto.crea()
    servizio = posto.collegamento.servizio
    assert servizio.da_finire() == set()
    servizio._aperto.chiudi_elenco()
    assert servizio.da_finire() is None
    carta.aggiorna(**{archivio_sicuro.PRIMA_COPIA: ["qualcosa"]})
    assert not posto.collegamento.prima_copia_in_corso()
    assert carta.leggi()[archivio_sicuro.PRIMA_COPIA] == ["qualcosa"]


def test_la_fotografia_del_collegamento(posto):
    fotografia = posto.collegamento.istantanea()
    assert fotografia["stato"] == ASSENTE and "archivio" in fotografia
    assert fotografia["password_del_mese"] is False
    assert fotografia["cambio_lasciato"] is None
    posto.crea()
    fotografia = posto.collegamento.istantanea()
    assert fotografia["stato"] == APERTO and fotografia["archivio"]["aperto"]


def test_il_cambio_in_quattro_passi(posto):
    posto.crea()
    assert posto.cambia() == []
    assert posto.richiusi == [NUOVA] and posto.sigillati == [NUOVA]
    assert posto.rimessi == []
    assert posto.cassa.la_password_e_giusta(NUOVA)
    assert not posto.cassa.la_password_e_giusta(PAROLA)
    assert posto.si_apre_con(NUOVA) and not posto.si_apre_con(PAROLA)
    assert chiavi.porte(posto.cartella) == 1
    assert archivio_sicuro.cambio_lasciato() is None
    assert not archivio_sicuro.serve_la_password_scritta(posto.posizione)
    collegamento = posto.riparti()
    collegamento.apri_in_sottofondo(NUOVA)
    assert _aspetta(collegamento) == APERTO


def test_il_cambio_rispetta_l_ordine_dei_passi(posto, monkeypatch):
    posto.crea()
    servizio = posto.collegamento.servizio
    passi = []
    aggiungi, tieni = servizio.aggiungi_password, servizio.tieni_solo

    def aggiungi_e_segna(nuova):
        passi.append(("aggiungi", nuova, archivio_sicuro.cambio_lasciato()))
        aggiungi(nuova)

    def tieni_e_segna(password):
        passi.append(("tieni", password, archivio_sicuro.cambio_lasciato()))
        tieni(password)

    monkeypatch.setattr(servizio, "aggiungi_password", aggiungi_e_segna)
    monkeypatch.setattr(servizio, "tieni_solo", tieni_e_segna)
    posto.cambia(
        richiudi=lambda nuova: passi.append(("richiudi", nuova,
                                             archivio_sicuro.cambio_lasciato()))
        or posto.richiudi(nuova),
        sigilla=lambda nuova: passi.append(("sigilla", nuova,
                                            archivio_sicuro.cambio_lasciato())))
    assert passi == [("aggiungi", NUOVA, "vecchia"), ("richiudi", NUOVA, "a_meta"),
                     ("sigilla", NUOVA, "nuova"), ("tieni", NUOVA, "nuova")]


def test_il_cambio_senza_archivio_cambia_solo_il_forziere(posto):
    posto.accendi()
    assert posto.cambia() == []
    assert posto.cassa.la_password_e_giusta(NUOVA)
    assert posto.sigillati == [NUOVA]
    assert not posto.cartella.exists()
    assert archivio_sicuro.cambio_lasciato() is None


@pytest.mark.parametrize("vecchia, nuova, ancora, codice", [
    (PAROLA, NUOVA, NUOVA + "!", "non_coincidono"),
    (PAROLA, PAROLA, PAROLA, "uguale"),
    (PAROLA, "corta", "corta", "password_corta"),
    (NUOVA + " sbagliata", NUOVA, NUOVA, "password_sbagliata"),
])
def test_un_cambio_sbagliato_non_tocca_niente(posto, vecchia, nuova, ancora, codice):
    posto.crea()
    assert _codice(lambda: posto.cambia(vecchia, nuova, ancora)) == codice
    assert posto.richiusi == [] and posto.sigillati == []
    assert posto.cassa.la_password_e_giusta(PAROLA)
    assert posto.si_apre_con(PAROLA) and chiavi.porte(posto.cartella) == 1
    assert archivio_sicuro.CAMBIO not in carta.leggi()


def test_col_forziere_spento_non_c_e_niente_da_cambiare(posto):
    assert _codice(lambda: posto.cambia()) == "forziere_spento"
    assert archivio_sicuro.CAMBIO not in carta.leggi()


def test_ad_archivio_chiuso_la_password_non_si_cambia(posto):
    posto.crea()
    collegamento = posto.riparti()
    assert _codice(lambda: posto.cambia()) == "sicuro_chiuso"
    collegamento.apri_in_sottofondo(DEL_FORZIERE)
    _aspetta(collegamento)
    assert _codice(lambda: posto.cambia()) == "sicuro_chiuso"
    assert posto.richiusi == []
    assert posto.cassa.la_password_e_giusta(PAROLA)
    assert posto.si_apre_con(PAROLA) and chiavi.porte(posto.cartella) == 1


def test_con_una_cartella_senza_chiave_la_password_non_si_cambia(posto):
    posto.accendi()
    posto.cartella.mkdir()
    (posto.cartella / "contenuti").mkdir()
    assert _codice(lambda: posto.cambia()) == "sicuro_chiuso"
    assert posto.cassa.la_password_e_giusta(PAROLA)


def test_se_la_carta_non_si_scrive_il_cambio_non_comincia(posto, monkeypatch):
    posto.crea()

    def rotta(**campi):
        raise OSError("carta in sola lettura")

    monkeypatch.setattr(carta, "aggiorna", rotta)
    with pytest.raises(OSError):
        posto.cambia()
    assert posto.richiusi == []
    assert posto.si_apre_con(PAROLA) and chiavi.porte(posto.cartella) == 1


def test_se_il_primo_passo_si_rompe_a_meta_la_nuova_si_toglie(posto, monkeypatch):
    posto.crea()
    servizio = posto.collegamento.servizio
    aggiungi = servizio.aggiungi_password

    def a_meta(nuova):
        aggiungi(nuova)
        raise OSError("disco staccato dopo la scrittura")

    monkeypatch.setattr(servizio, "aggiungi_password", a_meta)
    with pytest.raises(OSError):
        posto.cambia()
    assert posto.richiusi == []
    assert posto.si_apre_con(PAROLA) and not posto.si_apre_con(NUOVA)
    assert chiavi.porte(posto.cartella) == 1
    assert archivio_sicuro.cambio_lasciato() is None
    assert posto.cassa.la_password_e_giusta(PAROLA)


def test_se_il_primo_passo_non_scrive_niente_non_si_toglie_niente(posto, monkeypatch):
    posto.crea()
    servizio = posto.collegamento.servizio
    tolte = []

    def rotta(nuova):
        raise ErroreOfficina("La chiave non torna.", codice="chiave_rovinata")

    monkeypatch.setattr(servizio, "aggiungi_password", rotta)
    monkeypatch.setattr(servizio, "tieni_solo", tolte.append)
    assert _codice(lambda: posto.cambia()) == "chiave_rovinata"
    assert tolte == []
    assert servizio.problemi == []


def test_se_la_nuova_non_si_toglie_si_dice(posto, monkeypatch):
    posto.crea()
    servizio = posto.collegamento.servizio
    aggiungi = servizio.aggiungi_password

    def a_meta(nuova):
        aggiungi(nuova)
        raise OSError("disco staccato")

    def rotta(password):
        raise OSError("disco staccato")

    monkeypatch.setattr(servizio, "aggiungi_password", a_meta)
    monkeypatch.setattr(servizio, "tieni_solo", rotta)
    with pytest.raises(OSError):
        posto.cambia()
    assert servizio.problemi == ["password_nuova_ancora_buona"]
    assert posto.si_apre_con(PAROLA) and posto.si_apre_con(NUOVA)
    assert posto.cassa.la_password_e_giusta(PAROLA)


def test_se_il_forziere_non_si_richiude_vale_ancora_la_vecchia(posto):
    posto.crea()

    def rotto(nuova):
        raise OSError("disco pieno")

    with pytest.raises(ErroreOfficina) as preso:
        posto.cambia(richiudi=rotto)
    assert preso.value.codice == "forziere_non_richiuso"
    assert preso.value.messaggio == archivio_sicuro.NON_CAMBIATA
    assert posto.rimessi == [PAROLA] and posto.sigillati == []
    assert posto.cassa.la_password_e_giusta(PAROLA)
    assert posto.si_apre_con(PAROLA) and not posto.si_apre_con(NUOVA)
    assert archivio_sicuro.cambio_lasciato() is None


def test_se_il_forziere_non_si_riapre_con_la_vecchia_lo_dice(posto):
    posto.crea()

    def rotto(parola):
        raise OSError("disco pieno")

    assert _codice(lambda: posto.cambia(richiudi=rotto, rimetti=rotto)) == \
        "forziere_non_riaperto"
    assert posto.cassa.la_password_e_giusta(PAROLA)
    assert posto.si_apre_con(PAROLA) and not posto.si_apre_con(NUOVA)
    assert archivio_sicuro.cambio_lasciato() is None


def test_se_il_forziere_si_richiude_ma_non_si_riapre_vale_la_nuova(posto):
    posto.crea()

    def a_meta(nuova):
        posto.cassa.chiudi(nuova)
        raise OSError("non si riapre")

    with pytest.raises(ErroreOfficina) as preso:
        posto.cambia(richiudi=a_meta)
    assert preso.value.messaggio == archivio_sicuro.RIAPRI_CON_LA_NUOVA
    assert posto.sigillati == [NUOVA] and posto.rimessi == []
    assert posto.cassa.la_password_e_giusta(NUOVA)
    assert posto.si_apre_con(NUOVA) and not posto.si_apre_con(PAROLA)
    assert archivio_sicuro.cambio_lasciato() == archivio_sicuro.VALE_LA_NUOVA


def test_se_non_si_capisce_quale_vale_l_archivio_si_apre_con_tutte_e_due(posto, monkeypatch):
    posto.crea()

    with monkeypatch.context() as cieco:

        def illeggibile(nuova):
            cieco.setattr(type(posto.cassa), "la_password_e_giusta",
                          lambda self, password: False)

        assert _codice(lambda: posto.cambia(richiudi=illeggibile)) == "cambio_a_meta"
    assert posto.si_apre_con(PAROLA) and posto.si_apre_con(NUOVA)
    assert archivio_sicuro.cambio_lasciato() == archivio_sicuro.NON_SI_SA
    assert posto.rimessi == [] and posto.sigillati == []


def test_se_windows_non_si_rilega_il_cambio_finisce_e_lo_dice(posto):
    posto.crea()

    def rotto(nuova):
        raise ErroreOfficina("Windows Hello annullato.", codice="annullato")

    assert posto.cambia(sigilla=rotto) == ["windows_da_rifare"]
    assert posto.cassa.la_password_e_giusta(NUOVA)
    assert posto.si_apre_con(NUOVA) and not posto.si_apre_con(PAROLA)
    assert archivio_sicuro.cambio_lasciato() is None


def test_se_la_vecchia_non_si_toglie_il_cambio_finisce_e_lo_dice(posto, monkeypatch):
    posto.crea()

    def rotta(password):
        raise OSError("disco staccato")

    with monkeypatch.context() as rotto:
        rotto.setattr(posto.collegamento.servizio, "tieni_solo", rotta)
        assert posto.cambia() == ["password_vecchia_ancora_buona"]
    assert posto.cassa.la_password_e_giusta(NUOVA)
    assert posto.si_apre_con(NUOVA) and posto.si_apre_con(PAROLA)
    collegamento = posto.riparti()
    collegamento.apri_in_sottofondo(NUOVA)
    assert _aspetta(collegamento) == APERTO
    assert posto.si_apre_con(NUOVA) and not posto.si_apre_con(PAROLA)


class Spento(BaseException):
    pass


@pytest.mark.parametrize("dopo_il_forziere", [False, True])
def test_un_cambio_interrotto_di_colpo_non_chiude_fuori_nessuno(posto, dopo_il_forziere):
    posto.crea()

    def spento(nuova):
        if dopo_il_forziere:
            posto.cassa.chiudi(nuova)
        raise Spento

    with pytest.raises(Spento):
        posto.cambia(richiudi=spento)
    assert archivio_sicuro.cambio_lasciato() == archivio_sicuro.NON_SI_SA
    assert posto.si_apre_con(PAROLA) and posto.si_apre_con(NUOVA)
    vale = NUOVA if dopo_il_forziere else PAROLA
    assert posto.cassa.la_password_e_giusta(vale)
    posto.collegamento.servizio.chiudi(ATTESA)
    collegamento = posto.riparti()
    collegamento.apri_in_sottofondo(vale)
    assert _aspetta(collegamento) == APERTO
    assert posto.si_apre_con(vale)
    assert not posto.si_apre_con(PAROLA if dopo_il_forziere else NUOVA)


def test_un_cambio_dopo_un_cambio_lasciato_a_meta(posto, monkeypatch):
    posto.crea()

    def rotta(password):
        raise OSError("disco staccato")

    with monkeypatch.context() as rotto:
        rotto.setattr(posto.collegamento.servizio, "tieni_solo", rotta)
        posto.cambia()
    assert chiavi.porte(posto.cartella) == 2
    terza = "cinque parole tutte nuove"
    assert posto.cambia(NUOVA, terza) == []
    assert chiavi.porte(posto.cartella) == 1
    assert posto.si_apre_con(terza)
    assert not posto.si_apre_con(NUOVA) and not posto.si_apre_con(PAROLA)


def test_dimenticare_il_cambio(posto):
    archivio_sicuro.dimentica_il_cambio()
    assert archivio_sicuro.CAMBIO not in carta.leggi()
    carta.aggiorna(**{archivio_sicuro.CAMBIO: archivio_sicuro.NON_SI_SA})
    assert archivio_sicuro.cambio_lasciato() == archivio_sicuro.NON_SI_SA
    archivio_sicuro.dimentica_il_cambio()
    assert archivio_sicuro.cambio_lasciato() is None
    carta.aggiorna(**{archivio_sicuro.CAMBIO: "boh"})
    assert archivio_sicuro.cambio_lasciato() is None


def test_il_programmino_c_e_solo_se_c_e_o_se_e_installato(monkeypatch, tmp_path):
    from officina.programma import librerie

    monkeypatch.setattr(librerie, "e_il_programma_installato", lambda: False)
    trovato = archivio_sicuro.programmino()
    assert trovato is None or trovato.is_file()
    monkeypatch.setattr(librerie, "e_il_programma_installato", lambda: True)
    percorso = archivio_sicuro.programmino()
    assert percorso is not None and percorso.parent.name == "strumenti"
