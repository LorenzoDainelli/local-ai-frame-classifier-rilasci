from __future__ import annotations

import errno
import multiprocessing
import pickle
import queue
import threading
import time
from contextlib import ExitStack
from types import SimpleNamespace

import pytest

from officina import registro
from officina.archivio import accesso
from officina.errori import DaRifare, ErroreOfficina
from officina.impostazioni import REALE
from officina.programma import archivio_sicuro
from officina.sicuro import dall_archivio, formato, prendi, sportello
from officina.sicuro import servizio as modulo
from officina.sicuro.dall_archivio import (CHIUSO, CHIUSO_ADESSO, PERSA, SENZA_ARCHIVIO,
                                           TROVATA, DallArchivio)
from prove import test_sicuro_servizio as servizio_di_prova
from prove.test_sicuro_copia import _dati
from prove.test_sicuro_dall_archivio import (_Situazione, _cerca, _impronta, _numero,
                                             _rovina, _stacca)
from prove.test_sicuro_servizio import ATTESA, PAROLA, Casa, _con_le_foto, _finche

costo_leggero = servizio_di_prova.costo_leggero
casa = servizio_di_prova.casa

PICCOLA = _dati(100, 1)
GRANDE = _dati(3 * formato.BLOCCO + 7, 2)


class _Fila(queue.Queue):

    def __init__(self):
        super().__init__()
        self.passate: list = []
        self.rotte: list = []

    def put(self, cosa, *argomenti, **opzioni):
        try:
            copia = pickle.loads(pickle.dumps(cosa))
        except Exception as errore:
            self.rotte.append(errore)
            raise
        self.passate.append(copia)
        super().put(copia, *argomenti, **opzioni)


class _Ponte:

    def __init__(self, nome: str):
        self.notizie, self.risposte = _Fila(), _Fila()
        self.giro = multiprocessing.RawValue("q", 0)
        self.sportello = sportello.Sportello(nome, self.risposte, self.giro)
        self.lontano = sportello.DaLontano(self.notizie, self.risposte, self.giro)
        self._filo = threading.Thread(target=self._gira, daemon=True)
        self._filo.start()

    def _gira(self) -> None:
        while True:
            notizia = self.notizie.get()
            if notizia is None:
                return
            tipo, _, dati = notizia
            if tipo == "archivio":
                self.sportello.ricevi(dati)

    def permessi(self) -> list[dict]:
        return [risposta[1] for _, risposta in self.risposte.passate
                if risposta[0] and isinstance(risposta[1], dict) and "giro" in risposta[1]]

    def chiudi(self) -> None:
        self.notizie.put(None)
        self._filo.join(5)
        self.sportello.chiudi()


def _trova(ponte, casa, dati: bytes, relativo: str, *, intero: bool = True,
           impronta: str | None = None):
    return ponte.lontano.cerca(impronta or _impronta(dati), len(dati),
                               [casa.foto / relativo], nome=relativo, intero=intero)


@pytest.fixture
def ponte(casa, archivio, monkeypatch):
    _con_le_foto(casa)
    situazione = _Situazione(casa)
    monkeypatch.setattr(archivio_sicuro, "per_le_foto", situazione.per_le_foto)
    fatto = _Ponte(archivio.dove.nome)
    fatto.situazione = situazione
    yield fatto
    fatto.chiudi()


class _Prendi:

    def __init__(self, errore: Exception | None = None):
        self.errore = errore

    def __call__(self, trovata):
        if self.errore is not None:
            raise self.errore
        return iter(())


def _una(prendi_finto=None) -> DallArchivio:
    return DallArchivio("00" * 16, "s/a.jpg", 3, "ab" * 32, True, False,
                        prendi_finto or _Prendi())


def test_un_guasto_conta_solo_se_arriva_dopo_il_segno():
    trovata = _una()
    assert trovata.guasto is None and trovata.segno() == 0
    trovata.segna_guasto("archivio_chiuso")
    segno = trovata.segno()
    assert segno == 1 and trovata.guasto == "archivio_chiuso"
    assert trovata.guasto_da(segno) is None
    trovata.segna_guasto(None)
    assert trovata.guasto_da(segno) == "guasto"
    trovata.segna_guasto(PERSA)
    trovata.segna_guasto("archivio_chiuso")
    assert trovata.guasto_da(segno) == PERSA and trovata.guasto == PERSA
    assert trovata.guasto_da(trovata.segno()) is None


def test_una_lettura_che_non_si_apre_lascia_il_suo_guasto():
    trovata = _una(_Prendi(ErroreOfficina("chiuso", codice="archivio_chiuso")))
    with pytest.raises(ErroreOfficina):
        trovata.apri()
    assert trovata.guasto == "archivio_chiuso"
    persa = _una(_Prendi(prendi.Persa(prendi.PERSA)))
    with pytest.raises(prendi.Persa):
        persa.apri()
    assert persa.guasto == PERSA


@pytest.mark.parametrize("codice, atteso", [
    ("archivio_chiuso", CHIUSO_ADESSO), (None, CHIUSO_ADESSO), (PERSA, PERSA),
    ("qualcosa_di_nuovo", CHIUSO_ADESSO)])
def test_attento_cambia_un_guasto_dell_archivio_in_da_rifare(codice, atteso):
    trovata = _una()
    with pytest.raises(DaRifare) as preso:
        with dall_archivio.attento(trovata):
            trovata.segna_guasto(codice)
            raise OSError("letto male")
    assert preso.value.codice == atteso
    assert isinstance(preso.value.__cause__, OSError)
    assert preso.value.messaggio[:1].isupper() and preso.value.messaggio.endswith(".")
    with pytest.raises(DaRifare) as zitto:
        with dall_archivio.attento(trovata):
            trovata.segna_guasto(codice)
    assert zitto.value.codice == atteso


def test_attento_lascia_passare_quello_che_non_viene_dall_archivio(tmp_path):
    trovata = _una()
    trovata.segna_guasto("archivio_chiuso")
    with dall_archivio.attento(trovata) as dentro:
        assert dentro is trovata
    with pytest.raises(ValueError):
        with dall_archivio.attento(trovata):
            raise ValueError("un file rovinato di suo")
    gia = DaRifare("già detto", codice=PERSA)
    with pytest.raises(DaRifare) as preso:
        with dall_archivio.attento(_una()):
            raise gia
    assert preso.value is gia
    with dall_archivio.attento(tmp_path) as dentro:
        assert dentro is tmp_path
    with pytest.raises(OSError):
        with dall_archivio.attento(tmp_path):
            raise OSError("disco")
    with dall_archivio.attento(None) as dentro:
        assert dentro is None


def test_un_flusso_che_si_rompe_lo_dice_alla_foto(casa):
    _con_le_foto(casa)
    trovata = _cerca(casa, GRANDE, intero=False).trovata
    flusso = trovata.apri()
    try:
        assert flusso.read(5) == GRANDE[:5]
        assert trovata.guasto is None
        assert casa.archivio.chiudi(ATTESA)
        flusso.seek(2 * formato.BLOCCO)
        with pytest.raises(DaRifare) as preso:
            with dall_archivio.attento(trovata):
                flusso.read(5)
    finally:
        flusso.close()
    assert preso.value.codice == CHIUSO_ADESSO
    assert trovata.guasto == "archivio_chiuso"


class _FontiRotte:

    def __init__(self, errore: BaseException):
        self.forma = SimpleNamespace(dimensione=10, blocco=4)
        self._errore = errore

    def blocco(self, numero: int):
        raise self._errore


def test_un_flusso_cambia_in_errore_di_lettura_solo_i_guasti_dell_archivio():
    guasti: list = []
    chiuso = ErroreOfficina("chiuso", codice="archivio_chiuso")
    with prendi.Flusso(_FontiRotte(chiuso), ExitStack(), guasti.append) as flusso:
        with pytest.raises(OSError) as preso:
            flusso.readinto(bytearray(4))
    assert preso.value.errno == errno.EIO and preso.value.__cause__ is chiuso
    memoria = MemoryError()
    with prendi.Flusso(_FontiRotte(memoria), ExitStack(), guasti.append) as flusso:
        with pytest.raises(MemoryError) as finita:
            flusso.readinto(bytearray(4))
    assert finita.value is memoria
    assert guasti == ["archivio_chiuso", None]


def test_un_flusso_senza_copie_buone_dice_persa(casa):
    _con_le_foto(casa)
    _stacca(casa)
    _rovina(casa, "s/b.jpg")
    trovata = _cerca(casa, GRANDE, intero=False).trovata
    with pytest.raises(DaRifare) as preso:
        with dall_archivio.attento(trovata), trovata.apri() as flusso:
            flusso.read()
    assert preso.value.codice == PERSA and trovata.guasto == PERSA


def test_i_file_dell_archivio_si_chiudono_sempre(tmp_path):
    aperti: list = []

    def apri(percorso, senza_cache):
        lettore = prendi.leggi(percorso, senza_cache)
        aperti.append(lettore)
        return lettore

    dentro = Casa(tmp_path, leggi={"apri": apri})
    try:
        _con_le_foto(dentro)
        assert _cerca(dentro, PICCOLA, "s/a.jpg").trovata.apri().read() == PICCOLA
        assert aperti and all(lettore.closed for lettore in aperti)
        with _cerca(dentro, GRANDE, intero=False).trovata.apri() as flusso:
            assert flusso.read() == GRANDE
            assert not all(lettore.closed for lettore in aperti)
        assert all(lettore.closed for lettore in aperti)
        _stacca(dentro)
        _rovina(dentro, "s/b.jpg")
        quanti = len(aperti)
        with pytest.raises(prendi.Persa):
            _cerca(dentro, GRANDE).trovata.apri()
        assert len(aperti) > quanti and all(lettore.closed for lettore in aperti)
    finally:
        dentro.chiudi()


def test_le_chiavi_dell_archivio_non_escono_dal_programma(casa):
    _con_le_foto(casa)
    with pytest.raises(TypeError, match="non esce"):
        pickle.dumps(casa.aperto.chiave)
    di_una = sportello._ChiaveDiUnaFoto({"ab" * 16: b"x" * 32})
    with pytest.raises(TypeError, match="non esce"):
        pickle.dumps(di_una)
    assert "x" not in repr(di_una)
    assert di_una.per_contenuto(bytes.fromhex("ab" * 16)) == b"x" * 32
    with pytest.raises(ErroreOfficina) as preso:
        di_una.per_contenuto(bytes.fromhex("cd" * 16))
    assert preso.value.codice == "archivio_chiuso"


def test_il_permesso_per_un_lavoro_a_parte_ha_solo_la_chiave_di_quella_foto(casa):
    _con_le_foto(casa)
    numero = _numero(casa, "s/b.jpg")
    permesso = casa.aperto.permesso(numero)
    assert set(permesso) == {"informazioni", "percorso", "chiavi"}
    assert set(permesso["informazioni"]) == set(modulo.PER_UN_FIGLIO)
    assert permesso["chiavi"] == {
        numero: casa.aperto.chiave.per_contenuto(bytes.fromhex(numero))}
    pickle.dumps(permesso)
    chiave = sportello._ChiaveDiUnaFoto(permesso["chiavi"])
    letto = prendi.lettore(numero, permesso["informazioni"], chiave, permesso["percorso"],
                           True)
    assert letto.read() == GRANDE
    altre = casa.aperto.altre_per_un_figlio(numero)
    assert altre["altre"]
    assert set(altre["chiavi"]) == {fonte[1] for fonte in altre["altre"]}
    pickle.dumps(altre)
    with pytest.raises(prendi.Persa):
        casa.aperto.permesso("cd" * 16)
    aperto = casa.aperto
    assert casa.archivio.chiudi(ATTESA)
    with pytest.raises(ErroreOfficina) as preso:
        aperto.permesso(numero)
    assert preso.value.codice == "archivio_chiuso"
    with pytest.raises(ErroreOfficina):
        aperto.altre_per_un_figlio(numero)


def test_chi_aspetta_la_chiusura_viene_avvisato_una_volta_sola(casa):
    _con_le_foto(casa)
    aperto = casa.aperto
    chiamate: list = []

    def rotta() -> None:
        chiamate.append("rotta")
        raise RuntimeError("si rompe")

    def tolta() -> None:
        chiamate.append("tolta")

    aperto.quando_si_spegne(rotta)
    aperto.quando_si_spegne(lambda: chiamate.append("buona"))
    aperto.quando_si_spegne(tolta)
    aperto.non_piu(tolta)
    assert casa.archivio.chiudi(ATTESA)
    assert chiamate == ["rotta", "buona"]
    aperto.quando_si_spegne(lambda: chiamate.append("dopo"))
    assert chiamate == ["rotta", "buona", "dopo"]
    assert aperto._spegnimenti == []


def test_un_lavoro_a_parte_legge_con_la_chiave_di_quella_foto_sola(ponte, casa):
    ricerca = _trova(ponte, casa, PICCOLA, "s/a.jpg")
    assert ricerca.perche == TROVATA and not ricerca.diversa
    trovata = ricerca.trovata
    assert isinstance(trovata, DallArchivio) and trovata.blake2b == _impronta(PICCOLA)
    assert trovata.apri().read() == PICCOLA
    with _trova(ponte, casa, GRANDE, "s/b.jpg", intero=False).trovata.apri() as flusso:
        flusso.seek(formato.BLOCCO + 1)
        assert flusso.read(9) == GRANDE[formato.BLOCCO + 1:formato.BLOCCO + 10]
        flusso.seek(0)
        assert flusso.read() == GRANDE
    primo, secondo = ponte.permessi()
    for permesso, relativo in ((primo, "s/a.jpg"), (secondo, "s/b.jpg")):
        numero = _numero(casa, relativo)
        assert set(permesso) == {"informazioni", "percorso", "chiavi", "giro"}
        assert permesso["chiavi"] == {
            numero: casa.aperto.chiave.per_contenuto(bytes.fromhex(numero))}
    assert not ponte.risposte.rotte and not ponte.notizie.rotte
    nessuna = ponte.lontano.cerca("0" * 64, 5, [], nome="x.jpg", intero=True)
    assert nessuna.perche == "non_c_e"


@pytest.mark.parametrize("cosa", ["apri", "altre", "segnala", "letta"])
def test_un_lavoro_a_parte_tocca_solo_quello_che_ha_trovato(ponte, casa, cosa):
    numero = _numero(casa, "s/a.jpg")
    argomenti = (numero, True) if cosa == "segnala" else (numero,)
    ponte.sportello.ricevi((41, cosa, *argomenti))
    assert ponte.risposte.get(timeout=5) == (41, (False, sportello.CHIUSO,
                                                  "archivio_chiuso"))
    assert not casa.archivio.persa(numero)
    ponte.sportello.ricevi((42, "apri", "ab" * 16))
    assert ponte.risposte.get(timeout=5)[1][0] is False
    assert _trova(ponte, casa, PICCOLA, "s/a.jpg").trovata.numero == numero
    altro = _numero(casa, "s/b.jpg")
    ponte.sportello.ricevi((43, cosa, *((altro, True) if cosa == "segnala" else (altro,))))
    assert ponte.risposte.get(timeout=5) == (43, (False, sportello.CHIUSO,
                                                  "archivio_chiuso"))
    assert not casa.archivio.persa(altro)
    ponte.sportello.ricevi((44, "apri", numero))
    arrivato, risposta = ponte.risposte.get(timeout=5)
    assert arrivato == 44 and risposta[0] is True


def test_una_versione_diversa_non_si_apre_da_un_lavoro_a_parte(ponte, casa):
    ricerca = _trova(ponte, casa, b"un'altra versione", "s/a.jpg")
    assert ricerca.perche == TROVATA and ricerca.diversa
    with pytest.raises(ErroreOfficina):
        ricerca.trovata.apri()
    assert ricerca.trovata.guasto == "archivio_chiuso"
    assert not ponte.permessi()
    assert _trova(ponte, casa, PICCOLA, "s/a.jpg").trovata.apri().read() == PICCOLA
    assert ricerca.trovata.apri().read() == PICCOLA
    assert _trova(ponte, casa, b"un'altra versione", "s/a.jpg").diversa
    assert ricerca.trovata.apri().read() == PICCOLA


def test_quando_l_archivio_si_chiude_un_lavoro_a_parte_non_legge_piu(ponte, casa):
    trovata = _trova(ponte, casa, GRANDE, "s/b.jpg", intero=False).trovata
    flusso = trovata.apri()
    try:
        assert flusso.read(5) == GRANDE[:5]
        giro = ponte.giro.value
        assert casa.archivio.chiudi(ATTESA)
        assert ponte.giro.value == giro + 1
        flusso.seek(2 * formato.BLOCCO)
        with pytest.raises(DaRifare) as preso:
            with dall_archivio.attento(trovata):
                flusso.read(5)
    finally:
        flusso.close()
    assert preso.value.codice == CHIUSO_ADESSO
    with pytest.raises(ErroreOfficina):
        trovata.apri()
    assert _trova(ponte, casa, GRANDE, "s/b.jpg").perche == CHIUSO
    casa.archivio.apri(PAROLA)
    with pytest.raises(ErroreOfficina):
        trovata.apri()
    di_nuovo = _trova(ponte, casa, GRANDE, "s/b.jpg").trovata
    assert di_nuovo.apri().read() == GRANDE


def test_se_l_archivio_cambia_sotto_lo_sportello_se_ne_accorge(ponte, casa):
    trovata = _trova(ponte, casa, PICCOLA, "s/a.jpg").trovata
    giro = ponte.giro.value
    ponte.sportello.controlla()
    assert ponte.giro.value == giro
    ponte.situazione.forzata = CHIUSO
    ponte.sportello.controlla()
    assert ponte.giro.value == giro + 1
    ponte.situazione.forzata = None
    with pytest.raises(ErroreOfficina):
        trovata.apri()
    assert casa.aperto._spegnimenti == []
    seconda = _trova(ponte, casa, PICCOLA, "s/a.jpg").trovata
    with seconda.apri() as flusso:
        assert flusso.read() == PICCOLA
    assert len(casa.aperto._spegnimenti) == 1
    prima = ponte.giro.value
    ponte.sportello.chiudi()
    assert casa.aperto._spegnimenti == []
    assert ponte.giro.value > prima
    with pytest.raises(ErroreOfficina):
        seconda.apri()


class _Finito:

    def is_alive(self) -> bool:
        return False

    def join(self, timeout=None) -> None:
        return None


def test_mentre_un_lavoro_a_parte_gira_si_guarda_se_l_archivio_cambia(ponte, casa):
    from officina.web import in_disparte

    trovata = _trova(ponte, casa, GRANDE, "s/b.jpg", intero=False).trovata
    notizie = queue.Queue()
    notizie.put(("fine", None, {}))
    letture = []

    def leggi(_) -> None:
        flusso.seek(2 * formato.BLOCCO)
        try:
            with dall_archivio.attento(trovata):
                letture.append(flusso.read(5))
        except DaRifare as guasto:
            letture.append(guasto.codice)

    with trovata.apri() as flusso:
        assert flusso.read(5) == GRANDE[:5]
        ponte.situazione.forzata = SENZA_ARCHIVIO
        in_disparte._ascolta(_Finito(), notizie, leggi, ponte.sportello)
    assert letture == [CHIUSO_ADESSO]
    assert casa.aperto._spegnimenti == []


def test_una_copia_rovinata_si_legge_dalla_chiavetta_anche_da_un_lavoro_a_parte(ponte, casa):
    numero = _numero(casa, "s/b.jpg")
    _rovina(casa, "s/b.jpg")
    assert _trova(ponte, casa, GRANDE, "s/b.jpg").trovata.apri().read() == GRANDE
    _finche(lambda: numero in casa.aperto.letti_male)
    altre = [risposta[1] for _, risposta in ponte.risposte.passate
             if risposta[0] and isinstance(risposta[1], dict) and "altre" in risposta[1]]
    assert altre and all(set(piu["chiavi"]) == {fonte[1] for fonte in piu["altre"]}
                         for piu in altre)
    assert not casa.archivio.persa(numero)


def test_una_foto_persa_in_un_lavoro_a_parte_si_dice_all_archivio(ponte, casa):
    numero = _numero(casa, "s/b.jpg")
    _stacca(casa)
    _rovina(casa, "s/b.jpg")
    trovata = _trova(ponte, casa, GRANDE, "s/b.jpg").trovata
    with pytest.raises(DaRifare) as preso:
        with dall_archivio.attento(trovata):
            trovata.apri()
    assert preso.value.codice == PERSA
    _finche(lambda: casa.archivio.persa(numero))


def test_una_domanda_storta_non_fa_cadere_lo_sportello(ponte, casa, monkeypatch):
    errori: list = []
    monkeypatch.setattr(registro, "errore", lambda nome, **campi: errori.append(nome))
    for storta in (None, ("solo",), 5):
        ponte.sportello.ricevi(storta)
    with pytest.raises(queue.Empty):
        ponte.risposte.get(timeout=0.2)
    ponte.sportello.ricevi((7, "boh"))
    assert ponte.risposte.get(timeout=5) == (7, (False, sportello.CHIUSO, "archivio_chiuso"))
    assert errori == ["sicuro.sportello_rotto"] * 4
    assert _trova(ponte, casa, PICCOLA, "s/a.jpg").trovata.apri().read() == PICCOLA


def test_un_altro_archivio_non_ha_lo_sportello(ponte, casa):
    altro = sportello.Sportello("un_altro", _Fila(), multiprocessing.RawValue("q", 0))
    altro.ricevi((1, "cerca", _impronta(PICCOLA), len(PICCOLA), [], "a.jpg", True))
    numero, risposta = altro._risposte.get(timeout=5)
    assert (numero, risposta) == (1, (True, (SENZA_ARCHIVIO, None)))


class _Rotta:

    def put(self, cosa):
        raise ValueError("chiusa")


def test_senza_risposta_un_lavoro_a_parte_non_aspetta_per_sempre(monkeypatch):
    monkeypatch.setattr(sportello, "ATTESA", 0.2)
    giro = multiprocessing.RawValue("q", 0)
    muto = sportello.DaLontano(queue.Queue(), queue.Queue(), giro)
    partito = time.monotonic()
    assert muto.cerca("ab" * 32, 3, [], nome="a.jpg", intero=True).perche == CHIUSO
    assert time.monotonic() - partito < 5
    trovata = DallArchivio("00" * 16, "a.jpg", 3, "ab" * 32, True, False, muto._prendi)
    with pytest.raises(ErroreOfficina) as preso:
        trovata.apri()
    assert preso.value.codice == "archivio_chiuso" and trovata.guasto == "archivio_chiuso"
    rotto = sportello.DaLontano(_Rotta(), queue.Queue(), giro)
    assert rotto.cerca("ab" * 32, 3, [], nome="a.jpg", intero=True).perche == CHIUSO
    rotto._avvisa("letta", "00" * 16)


def test_le_risposte_vecchie_si_buttano(ponte, casa):
    ponte.risposte.put((999, (True, "una risposta arrivata tardi")))
    ponte.risposte.put((0, (False, "un'altra", "archivio_chiuso")))
    assert _trova(ponte, casa, PICCOLA, "s/a.jpg").trovata.apri().read() == PICCOLA


def test_una_persa_arriva_come_persa_e_il_resto_come_errore():
    risposte = queue.Queue()
    lontano = sportello.DaLontano(_Eco(risposte), risposte, multiprocessing.RawValue("q", 0))
    _Eco.risposta = (False, "persa", prendi.Persa.codice)
    with pytest.raises(prendi.Persa):
        lontano._chiedi("apri", "00" * 16)
    _Eco.risposta = (False, "chiuso", "archivio_chiuso")
    with pytest.raises(ErroreOfficina) as preso:
        lontano._chiedi("apri", "00" * 16)
    assert not isinstance(preso.value, prendi.Persa)
    assert preso.value.codice == "archivio_chiuso"


class _Eco:

    risposta: tuple = ()

    def __init__(self, risposte):
        self._risposte = risposte

    def put(self, notizia):
        _, _, (numero, *_) = notizia
        if numero is not None:
            self._risposte.put((numero, self.risposta))


@pytest.fixture
def a_parte(casa, archivio, monkeypatch):
    from officina.web import in_disparte

    _con_le_foto(casa)
    monkeypatch.setattr(archivio_sicuro, "per_le_foto", _Situazione(casa).per_le_foto)
    monkeypatch.setattr(in_disparte, "A_PARTE", True)
    yield archivio.dove.nome
    in_disparte.chiudi(1.0)


def test_un_lavoro_a_parte_vero_legge_e_si_ferma_quando_l_archivio_si_chiude(
        a_parte, casa, tmp_path):
    from officina.web import in_disparte
    from officina.web.lavori import Lavoro

    segnale = tmp_path / "chiuso"
    foto = [(_impronta(dati), len(dati), str(casa.foto / relativo), relativo)
            for dati, relativo in ((PICCOLA, "s/a.jpg"), (GRANDE, "s/b.jpg"))]
    lavoro = Lavoro("finto")
    assert in_disparte.lancia(lavoro, "finto", a_parte, "prove.fila_finta:dall_archivio",
                              (foto, str(segnale)))
    _finche(lambda: any(riga.startswith("primo") for riga in lavoro.righe))
    assert casa.archivio.chiudi(ATTESA)
    segnale.touch()
    assert lavoro.aspetta_che_finisca(60)
    assert lavoro.guasto == ""
    assert list(lavoro.righe) == [f"letta {_impronta(PICCOLA)}", f"primo {formato.BLOCCO}",
                                  "fermata archivio_chiuso", "rifiutata archivio_chiuso"]
    assert not in_disparte.sta_girando("finto")


def test_la_fila_dell_ia_in_un_altro_processo_legge_dall_archivio(a_parte, casa,
                                                                  monkeypatch):
    from officina.web import in_disparte
    from officina.web.strade import comune, intelligenza

    for chiave, valore in (("adesso", ""), ("fermata", False), ("dove_guasto", ""),
                           ("scelti", [])):
        monkeypatch.setitem(comune.fila_ia, chiave, valore)
    relativo = "s/a.jpg"
    scelti = [_impronta(PICCOLA), str(len(PICCOLA)), str(casa.foto / relativo), relativo]
    in_disparte.ponte(a_parte, scelti, "prove.fila_finta:dalla_fila")
    sotto = intelligenza.sotto_lavoro_ia("scritte")
    assert sotto.guasto == ""
    assert list(sotto.righe)[-1] == f"letta {_impronta(PICCOLA)}"
    assert not in_disparte.sta_girando()
    assert casa.aperto._spegnimenti == []


def test_se_l_archivio_si_chiude_mentre_cerca_lo_sportello_dice_chiuso(ponte, casa,
                                                                       monkeypatch):
    cerca = casa.archivio.cerca

    def e_si_chiude(*argomenti, **opzioni):
        ricerca = cerca(*argomenti, **opzioni)
        assert casa.archivio.chiudi(ATTESA)
        casa.archivio.apri(PAROLA)
        return ricerca

    with monkeypatch.context() as stanza:
        stanza.setattr(casa.archivio, "cerca", e_si_chiude)
        assert _trova(ponte, casa, PICCOLA, "s/a.jpg").perche == CHIUSO
    assert _trova(ponte, casa, PICCOLA, "s/a.jpg").trovata.apri().read() == PICCOLA


def test_se_l_archivio_si_chiude_mentre_da_il_permesso_la_chiave_non_esce(ponte, casa,
                                                                          monkeypatch):
    trovata = _trova(ponte, casa, PICCOLA, "s/a.jpg").trovata
    aperto = casa.aperto
    permesso = aperto.permesso

    def e_si_chiude(numero):
        dato = permesso(numero)
        assert casa.archivio.chiudi(ATTESA)
        return dato

    with monkeypatch.context() as stanza:
        stanza.setattr(aperto, "permesso", e_si_chiude)
        with pytest.raises(ErroreOfficina):
            trovata.apri()
    assert not ponte.permessi()


def _archivio_di_nome(nome: str):
    return lambda: SimpleNamespace(dove=SimpleNamespace(nome=nome))


def test_in_un_lavoro_a_parte_le_foto_si_chiedono_allo_sportello(monkeypatch):
    lontano = object()
    monkeypatch.setattr(sportello, "_lontano", lontano)
    monkeypatch.setattr(modulo, "attuale", lambda: pytest.fail("qui il servizio non c'è"))
    monkeypatch.setattr(accesso, "aperto", _archivio_di_nome(REALE))
    assert archivio_sicuro.per_le_foto() == (TROVATA, lontano)
    monkeypatch.setattr(accesso, "aperto", _archivio_di_nome("finto"))
    assert archivio_sicuro.per_le_foto() == (SENZA_ARCHIVIO, None)
