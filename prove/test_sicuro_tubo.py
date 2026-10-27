from __future__ import annotations

import io
import json
import os
import queue
import threading
import time

import pytest

from officina import registro
from officina.errori import DaRifare, ErroreOfficina
from officina.miglioria import lavoro
from officina.programma import archivio_sicuro
from officina.sicuro import dall_archivio, formato, sportello, tubo
from officina.sicuro.dall_archivio import CHIUSO, CHIUSO_ADESSO, TROVATA
from prove import test_sicuro_servizio as servizio_di_prova
from prove.test_sicuro_dall_archivio import _Situazione, _impronta, _numero
from prove.test_sicuro_servizio import ATTESA, PAROLA, _con_le_foto, _finche
from prove.test_sicuro_sportello import GRANDE, PICCOLA

costo_leggero = servizio_di_prova.costo_leggero
casa = servizio_di_prova.casa

DENTRO = {"informazioni": {"testa": b"\x00\xff\x10", "dimensione": 5, "blake2b": "ab"},
          "percorso": "C:/Foto/è qui.jpg", "chiavi": {"00" * 16: bytes(range(32))},
          "altre": [("p", "n", b"t", False), ["q", "m", None, True]], "giro": 3,
          "niente": None, "mezzo": 0.5, "vuoti": [b"", {}, []]}


def _rigirato(valore):
    return tubo.da_testo(json.loads(json.dumps(tubo.in_testo(valore))))


def test_nel_tubo_passano_parole_numeri_byte_e_liste():
    tornato = _rigirato(DENTRO)
    assert tornato == {**DENTRO, "altre": [["p", "n", b"t", False], ["q", "m", None, True]]}
    assert type(tornato["chiavi"]["00" * 16]) is bytes
    assert _rigirato(bytearray(b"\x01")) == b"\x01"
    assert _rigirato((1, (2, "tre"))) == [1, [2, "tre"]]
    assert _rigirato({"b": "00"}) == {"b": "00"}
    assert _rigirato({"d": {"b": b"x"}}) == {"d": {"b": b"x"}}


@pytest.mark.parametrize("valore", [{1: "a"}, {"a": {3}}, object(), [frozenset()],
                                    {"chiave": io.BytesIO()}])
def test_nel_tubo_non_passa_quello_che_non_si_rilegge(valore):
    with pytest.raises(ValueError):
        tubo.in_testo(valore)


@pytest.mark.parametrize("pezzo", [{"x": 1}, {"b": 5}, {"b": "zz"}, {"d": []},
                                   {"b": "00", "d": {}}, [1, {"q": 2}], {},
                                   {"d": {"a": {"b": "0"}}}])
def test_un_pezzo_strano_nel_tubo_si_rifiuta(pezzo):
    with pytest.raises(ValueError):
        tubo.da_testo(pezzo)


def test_verso_la_stanza_va_una_riga_per_messaggio():
    uscita = io.StringIO()
    verso = tubo.Verso(uscita)
    verso.put((7, (True, {"chiavi": {"ab": b"\x01\x02"}})))
    assert verso.value == 0
    verso.value += 1
    righe = uscita.getvalue().splitlines(keepends=True)
    assert all(riga.endswith("\n") for riga in righe)
    assert [json.loads(riga) for riga in righe] == [
        {"risposta": [7, [True, {"d": {"chiavi": {"d": {"ab": {"b": "0102"}}}}}]]},
        {"giro": 1}]
    assert verso.value == 1


class _Rotta(io.StringIO):

    def __init__(self, errore: Exception):
        super().__init__()
        self.errore = errore

    def write(self, testo):
        raise self.errore


@pytest.mark.parametrize("errore", [BrokenPipeError(), ValueError("chiusa")])
def test_se_il_giro_non_arriva_alla_stanza_la_stanza_si_ferma(errore):
    fermate = []
    verso = tubo.Verso(_Rotta(errore), lambda: fermate.append(1))
    verso.value = 5
    assert fermate == [1] and verso.value == 5
    tubo.Verso(_Rotta(errore)).value = 2

    def non_si_ferma():
        raise ProcessLookupError

    tubo.Verso(_Rotta(errore), non_si_ferma).value = 3
    with pytest.raises(type(errore)):
        tubo.Verso(_Rotta(errore)).put((1, (True, None)))


class _Tubetto:

    def __init__(self):
        leggi, scrivi = os.pipe()
        self.entrata = open(leggi, encoding="utf-8")
        self.uscita = open(scrivi, "w", encoding="utf-8")
        self.mandati: list = []
        self.filo = tubo.DaVerso(self.entrata, self.mandati.append)

    def scrivi(self, *righe: str) -> None:
        for riga in righe:
            self.uscita.write(riga + "\n")
        self.uscita.flush()

    def chiudi(self) -> None:
        self.uscita.close()


def test_dalla_parte_della_stanza_si_tengono_solo_le_risposte_giuste():
    tubetto = _Tubetto()
    try:
        assert tubetto.filo.value == 0
        tubetto.scrivi("non è una riga buona", "[1, 2]", '{"risposta": {"x": 1}}',
                       '{"risposta": [1]}', '{"risposta": [1, 2, 3]}', '{"altro": 1}',
                       '{"giro": 4}', '{"giro": true}', '{"giro": "5"}', '{"giro": 5.0}',
                       '{"risposta": "ab"}', '{"risposta": {"d": {"a": 1, "b": 2}}}',
                       '{"risposta": [9, [true, {"b": "0aff"}]]}')
        assert tubetto.filo.get(timeout=5) == (9, [True, b"\x0a\xff"])
        assert tubetto.filo.value == 4
        with pytest.raises(queue.Empty):
            tubetto.filo.get(timeout=0.05)
        tubetto.scrivi('{"giro": 6}')
        _finche(lambda: tubetto.filo.value == 6)
    finally:
        tubetto.chiudi()
    _finche(lambda: tubetto.filo.value == tubo.FINITO)
    for _ in range(2):
        with pytest.raises(EOFError):
            tubetto.filo.get(timeout=5)


@pytest.mark.parametrize("errore", [OSError("rotto"), ValueError("chiuso")])
def test_se_il_tubo_si_rompe_la_stanza_non_aspetta_piu(errore, monkeypatch):
    class Rotto:

        def __iter__(self):
            raise errore

    mandati: list = []
    _senza_scappati(monkeypatch, Rotto(), mandati.append)
    assert mandati == []


def _senza_scappati(monkeypatch, entrata, manda) -> None:
    scappati: list = []
    monkeypatch.setattr(threading, "excepthook", scappati.append)
    prima = set(threading.enumerate())
    filo = tubo.DaVerso(entrata, manda)
    nuovi = set(threading.enumerate()) - prima
    with pytest.raises(EOFError):
        filo.get(timeout=5)
    assert filo.value == tubo.FINITO
    _finche(lambda: not any(uno.is_alive() for uno in nuovi))
    assert scappati == []


@pytest.mark.parametrize("errore", [RecursionError, MemoryError, KeyError])
def test_un_guasto_inatteso_nel_tubo_arriva_al_programma(errore, monkeypatch):
    class Rotto:

        def __iter__(self):
            raise errore("dentro")

    mandati: list = []
    _senza_scappati(monkeypatch, Rotto(), mandati.append)
    rotto, = mandati
    assert set(rotto) == {"tubo_rotto"}
    assert rotto["tubo_rotto"]["guasto"] == errore.__name__
    assert rotto["tubo_rotto"]["dove"] == "tubo"
    assert rotto["tubo_rotto"]["riga"].isdigit()
    for non_arriva in (BrokenPipeError, ValueError, TypeError):
        _senza_scappati(monkeypatch, Rotto(), _non_arriva(non_arriva))


def _non_arriva(errore: type):
    def manda(messaggio) -> None:
        raise errore

    return manda


class _Lenta:

    def __init__(self):
        self.lettere: list = []

    def write(self, testo: str) -> None:
        for lettera in testo:
            self.lettere.append(lettera)
            time.sleep(0)

    def flush(self) -> None:
        pass


def test_da_piu_fili_le_righe_verso_la_stanza_non_si_mischiano():
    uscita = _Lenta()
    verso = tubo.Verso(uscita)

    def manda(quale: int) -> None:
        for volta in range(30):
            verso.put((quale, (True, {"volta": volta})))
            verso.value = quale

    fili = [threading.Thread(target=manda, args=(quale,)) for quale in range(4)]
    for filo in fili:
        filo.start()
    for filo in fili:
        filo.join(30)
    lette = [json.loads(riga) for riga in "".join(uscita.lettere).splitlines()]
    assert len(lette) == 4 * 30 * 2
    assert sorted(letta["risposta"][0] for letta in lette
                  if "risposta" in letta) == sorted(list(range(4)) * 30)


def test_dalla_stanza_le_domande_vanno_al_programma():
    mandati = []
    filo = tubo.DaVerso(io.StringIO(""), mandati.append)
    filo.put(("archivio", None, (3, "segnala", "ab" * 16, True)))
    filo.put(("archivio", None, (None, "letta", b"\x01")))
    assert mandati == [{"archivio": [3, "segnala", "ab" * 16, True]},
                       {"archivio": [None, "letta", {"b": "01"}]}]


class _Stanza:

    def __init__(self, nome: str):
        alla_stanza, dal_programma = os.pipe()
        al_programma, dalla_stanza = os.pipe()
        self._verso_la_stanza = open(dal_programma, "w", encoding="utf-8")
        self._entrata = open(alla_stanza, encoding="utf-8")
        self._dalla_stanza = open(al_programma, encoding="utf-8")
        self._uscita = open(dalla_stanza, "w", encoding="utf-8")
        self._serratura = threading.Lock()
        self.risposte: list = []
        self.fermata = threading.Event()
        verso = tubo.Verso(self._verso_la_stanza, self.fermata.set)
        vero = verso.put

        def put(risposta) -> None:
            self.risposte.append(risposta)
            vero(risposta)

        verso.put = put
        self.sportello = sportello.Sportello(nome, verso, verso)
        self.filo = tubo.DaVerso(self._entrata, self._manda)
        self.lontano = sportello.DaLontano(self.filo, self.filo, self.filo)
        self._ascolto = threading.Thread(target=self._ascolta, daemon=True)
        self._ascolto.start()

    def _manda(self, messaggio: dict) -> None:
        with self._serratura:
            self._uscita.write(json.dumps(messaggio) + "\n")
            self._uscita.flush()

    def _ascolta(self) -> None:
        for riga in self._dalla_stanza:
            lavoro._allo_sportello(self.sportello, json.loads(riga)["archivio"])

    def permessi(self) -> list[dict]:
        return [risposta[1] for _, risposta in self.risposte
                if risposta[0] and isinstance(risposta[1], dict) and "giro" in risposta[1]]

    def stacca(self) -> None:
        self._verso_la_stanza.close()

    def chiudi(self) -> None:
        self._uscita.close()
        self._ascolto.join(5)
        self.sportello.chiudi()
        self._verso_la_stanza.close()
        _finche(lambda: self.filo.value == tubo.FINITO)
        self._entrata.close()
        self._dalla_stanza.close()


@pytest.fixture
def stanza(casa, archivio, monkeypatch):
    _con_le_foto(casa)
    monkeypatch.setattr(archivio_sicuro, "per_le_foto", _Situazione(casa).per_le_foto)
    fatta = _Stanza(archivio.dove.nome)
    yield fatta
    fatta.chiudi()


def _trova(stanza, casa, dati: bytes, relativo: str, *, intero: bool = True):
    return stanza.lontano.cerca(_impronta(dati), len(dati), [casa.foto / relativo],
                                nome=relativo, intero=intero)


def test_nel_tubo_passa_solo_la_chiave_di_quella_foto(stanza, casa):
    ricerca = _trova(stanza, casa, PICCOLA, "s/a.jpg")
    assert ricerca.perche == TROVATA and not ricerca.diversa
    assert ricerca.trovata.apri().read() == PICCOLA
    with _trova(stanza, casa, GRANDE, "s/b.jpg", intero=False).trovata.apri() as flusso:
        flusso.seek(formato.BLOCCO + 1)
        assert flusso.read(9) == GRANDE[formato.BLOCCO + 1:formato.BLOCCO + 10]
        flusso.seek(0)
        assert flusso.read() == GRANDE
    primo, secondo = stanza.permessi()
    for permesso, relativo in ((primo, "s/a.jpg"), (secondo, "s/b.jpg")):
        numero = _numero(casa, relativo)
        assert set(permesso) == {"informazioni", "percorso", "chiavi", "giro"}
        assert permesso["chiavi"] == {
            numero: casa.aperto.chiave.per_contenuto(bytes.fromhex(numero))}
    assert _trova(stanza, casa, b"un'altra versione", "s/a.jpg").diversa
    assert stanza.lontano.cerca("0" * 64, 5, [], nome="x.jpg",
                                intero=True).perche == "non_c_e"
    assert not stanza.fermata.is_set()


def test_quando_l_archivio_si_chiude_la_stanza_non_legge_piu(stanza, casa):
    trovata = _trova(stanza, casa, GRANDE, "s/b.jpg", intero=False).trovata
    flusso = trovata.apri()
    try:
        assert flusso.read(5) == GRANDE[:5]
        giro = stanza.filo.value
        assert casa.archivio.chiudi(ATTESA)
        _finche(lambda: stanza.filo.value == giro + 1)
        flusso.seek(2 * formato.BLOCCO)
        with pytest.raises(DaRifare) as preso:
            with dall_archivio.attento(trovata):
                flusso.read(5)
    finally:
        flusso.close()
    assert preso.value.codice == CHIUSO_ADESSO
    assert _trova(stanza, casa, GRANDE, "s/b.jpg").perche == CHIUSO
    casa.archivio.apri(PAROLA)
    with pytest.raises(ErroreOfficina):
        trovata.apri()
    assert _trova(stanza, casa, GRANDE, "s/b.jpg").trovata.apri().read() == GRANDE


def test_se_il_programma_non_risponde_piu_la_stanza_non_legge_piu(stanza, casa):
    trovata = _trova(stanza, casa, GRANDE, "s/b.jpg", intero=False).trovata
    flusso = trovata.apri()
    try:
        assert flusso.read(5) == GRANDE[:5]
        stanza.stacca()
        _finche(lambda: stanza.filo.value == tubo.FINITO)
        flusso.seek(2 * formato.BLOCCO)
        with pytest.raises(DaRifare) as preso:
            with dall_archivio.attento(trovata):
                flusso.read(5)
    finally:
        flusso.close()
    assert preso.value.codice == CHIUSO_ADESSO
    assert _trova(stanza, casa, GRANDE, "s/b.jpg").perche == CHIUSO
    assert casa.archivio.aperto


def test_una_domanda_storta_dalla_stanza_non_fa_cadere_niente(stanza, casa, monkeypatch):
    errori: list = []
    monkeypatch.setattr(registro, "errore", lambda nome, **campi: errori.append(nome))
    lavoro._allo_sportello(stanza.sportello, {"x": 1})
    lavoro._allo_sportello(stanza.sportello, [{"b": "zz"}])
    assert not stanza.risposte and not errori
    lavoro._allo_sportello(stanza.sportello, [5, "chissà"])
    assert stanza.risposte == [(5, (False, sportello.CHIUSO, "archivio_chiuso"))]
    assert errori == ["sicuro.sportello_rotto"]
    assert _trova(stanza, casa, PICCOLA, "s/a.jpg").trovata.apri().read() == PICCOLA
