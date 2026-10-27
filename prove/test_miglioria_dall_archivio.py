from __future__ import annotations

import io
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from officina import registro
from officina.errori import ErroreOfficina
from officina.miglioria import catena, date, lavoro, metadati, motori, stanza
from officina.programma import archivio_sicuro
from officina.sicuro import sportello, tubo
from officina.sicuro.dall_archivio import (CHIUSO, CHIUSO_ADESSO, DIVERSA, SENZA_ARCHIVIO,
                                           SI_APRE, TROVATA, DallArchivio, Ricerca)
from prove import test_sicuro_servizio as servizio_di_prova
from prove.test_sicuro_dall_archivio import _Situazione, _impronta, _jpeg, _numero, _video
from prove.test_sicuro_servizio import ATTESA, LEGGERO, PAROLA, _finche

costo_leggero = servizio_di_prova.costo_leggero
casa = servizio_di_prova.casa

SCELTI = {"foto": motori.FINTO, "video": motori.FINTO, "volti": None}
DATE = {"modifica": 1_500_000_000_123_456_789, "accesso": 1_600_000_000_987_654_321,
        "creazione": 1_400_000_000_000_000_000}
FOTO = "s/mare.jpg"
FILMATO = "s/onde.mp4"


@pytest.fixture
def nell_archivio(casa, archivio, monkeypatch, tmp_path):
    foto, filmato = _jpeg(), _video("libx264")
    casa.metti(FOTO, foto)
    casa.metti(FILMATO, filmato)
    casa.archivio.crea(PAROLA, costo=LEGGERO)
    casa.archivio.copia_tutto([casa.foto])
    _finche(casa.copiato)
    casa.con_la_chiavetta()
    situazione = _Situazione(casa)
    monkeypatch.setattr(archivio_sicuro, "per_le_foto", situazione.per_le_foto)
    attesa = tmp_path / "attesa"
    attesa.mkdir()
    return SimpleNamespace(dati={FOTO: foto, FILMATO: filmato}, situazione=situazione,
                           attesa=attesa)


def _lavoro(genere: str, originale: Path, uscita: Path, **piu) -> dict:
    return {"genere": genere, "originale": str(originale), "motori": SCELTI, "persone": [],
            "intensita": 100, "percorsi": [], "opzioni": {}, "uscita": str(uscita), **piu}


def _cercata(dati: bytes, percorsi: list, nome: str) -> dict:
    return {"impronta": _impronta(dati), "dimensione": len(dati),
            "percorsi": [str(percorso) for percorso in percorsi], "nome": nome}


def _lancia(da_fare: dict, ricorda=lambda processo: None) -> dict:
    return lavoro.lancia_la_stanza(da_fare, lambda fatti, totale: None, ricorda)


def _la_foto_dall_archivio(nell_archivio, casa) -> dict:
    originale = casa.foto / FOTO
    return _lavoro("immagine", originale, nell_archivio.attesa / "1-mare.jpg", date=DATE,
                   dall_archivio=_cercata(nell_archivio.dati[FOTO], [originale], FOTO))


def _spia(monkeypatch) -> list:
    mandate: list = []
    vero = tubo.Verso.put

    def put(verso, risposta) -> None:
        mandate.append(tubo.da_testo(tubo.in_testo(list(risposta))))
        vero(verso, risposta)

    monkeypatch.setattr(tubo.Verso, "put", put)
    return mandate


def _mai_in_chiaro(cartella: Path, dati: bytes) -> None:
    for percorso in cartella.rglob("*"):
        if percorso.is_file() and not percorso.is_symlink():
            assert dati not in percorso.read_bytes(), percorso


@pytest.mark.parametrize("genere, relativo, intero", [("immagine", FOTO, True),
                                                       ("video", FILMATO, False)])
def test_la_stanza_vera_migliora_un_originale_che_sta_solo_nell_archivio(
        nell_archivio, casa, tmp_path, monkeypatch, genere, relativo, intero):
    dati = nell_archivio.dati[relativo]
    originale = casa.foto / relativo
    nome = originale.name
    dal_disco = nell_archivio.attesa / f"1-{nome}"
    fatto = _lancia(_lavoro(genere, originale, dal_disco))
    assert "fatto" in fatto, fatto
    numero = _numero(casa, relativo)
    originale.unlink()
    mandate = _spia(monkeypatch)
    dall_archivio = nell_archivio.attesa / f"2-{nome}"
    esito = _lancia(_lavoro(genere, originale, dall_archivio, date=DATE,
                            dall_archivio=_cercata(dati, [originale], relativo)))
    assert esito == fatto
    misure = os.stat(dall_archivio)
    assert (misure.st_mtime_ns, misure.st_atime_ns) == (DATE["modifica"], DATE["accesso"])
    assert dall_archivio.read_bytes() == dal_disco.read_bytes()
    assert not originale.exists()
    _mai_in_chiaro(tmp_path, dati)
    trovate = [risposta[1][1] for _, risposta in mandate
               if risposta[0] and isinstance(risposta[1], list)
               and risposta[1][0] == TROVATA]
    assert trovate and all(trovata == [numero, relativo, len(dati), _impronta(dati), intero,
                                       False] for trovata in trovate)
    permessi = [risposta[1] for _, risposta in mandate
                if risposta[0] and isinstance(risposta[1], dict)]
    assert permessi and all(permesso["chiavi"] == {numero: casa.aperto.chiave.per_contenuto(
        bytes.fromhex(numero))} for permesso in permessi)


@pytest.mark.parametrize("forzata, guasto", [(CHIUSO, CHIUSO_ADESSO),
                                             (SI_APRE, CHIUSO_ADESSO),
                                             (SENZA_ARCHIVIO, "originale_assente")])
def test_la_stanza_non_parte_se_l_archivio_non_c_e(nell_archivio, casa, forzata, guasto):
    nell_archivio.situazione.forzata = forzata
    uscita = nell_archivio.attesa / "1-mare.jpg"
    esito = _lancia(_lavoro("immagine", casa.foto / FOTO, uscita,
                            dall_archivio=_cercata(nell_archivio.dati[FOTO],
                                                   [casa.foto / FOTO], FOTO)))
    assert esito == {"guasto": guasto}
    assert list(nell_archivio.attesa.iterdir()) == []


def test_con_l_archivio_chiuso_la_stanza_non_parte(nell_archivio, casa):
    assert casa.archivio.chiudi(ATTESA)
    uscita = nell_archivio.attesa / "1-mare.jpg"
    esito = _lancia(_lavoro("immagine", casa.foto / FOTO, uscita,
                            dall_archivio=_cercata(nell_archivio.dati[FOTO],
                                                   [casa.foto / FOTO], FOTO)))
    assert esito == {"guasto": CHIUSO_ADESSO}
    assert list(nell_archivio.attesa.iterdir()) == []


@pytest.mark.parametrize("percorsi, guasto", [(True, DIVERSA), (False, "originale_assente")])
def test_una_versione_diversa_o_che_non_c_e_non_si_migliora(nell_archivio, casa, percorsi,
                                                            guasto):
    originale = casa.foto / FOTO
    uscita = nell_archivio.attesa / "1-mare.jpg"
    esito = _lancia(_lavoro("immagine", originale, uscita, dall_archivio=_cercata(
        b"un'altra versione", [originale] if percorsi else [], FOTO)))
    assert esito == {"guasto": guasto}
    assert list(nell_archivio.attesa.iterdir()) == []


def test_se_l_archivio_si_chiude_mentre_lavora_il_video_resta_da_rifare(nell_archivio, casa,
                                                                        monkeypatch):
    aperto = casa.aperto
    vero = aperto.permesso
    dati: list = []

    def e_poi_si_chiude(numero):
        dati.append(numero)
        if len(dati) == 2:
            assert casa.archivio.chiudi(ATTESA)
        return vero(numero)

    monkeypatch.setattr(aperto, "permesso", e_poi_si_chiude)
    originale = casa.foto / FILMATO
    originale.unlink()
    uscita = nell_archivio.attesa / "1-onde.mp4"
    esito = _lancia(_lavoro("video", originale, uscita, dall_archivio=_cercata(
        nell_archivio.dati[FILMATO], [originale], FILMATO)))
    assert esito == {"guasto": CHIUSO_ADESSO}
    assert len(dati) == 2 and not uscita.exists()


def test_prima_di_ogni_domanda_lo_sportello_ricontrolla_l_archivio(nell_archivio, casa,
                                                                  monkeypatch):
    fatti: list = []
    for nome in ("controlla", "ricevi", "chiudi"):
        vero = getattr(sportello.Sportello, nome)

        def spia(allo_sportello, *argomenti, nome=nome, vero=vero):
            fatti.append(nome)
            return vero(allo_sportello, *argomenti)

        monkeypatch.setattr(sportello.Sportello, nome, spia)
    assert "fatto" in _lancia(_la_foto_dall_archivio(nell_archivio, casa))
    assert fatti.count("ricevi") >= 2 and fatti.count("chiudi") == 1
    assert fatti[-1] == "chiudi" and fatti.count("controlla") > fatti.count("ricevi")
    assert all(fatti[quale - 1] == "controlla" for quale, fatto in enumerate(fatti)
               if fatto == "ricevi")


def test_finita_la_stanza_lo_sportello_lascia_l_archivio_e_il_tubo(nell_archivio, casa,
                                                                   monkeypatch):
    scritte: list = []
    vero = tubo.Verso._scrivi

    def scrivi(verso, messaggio):
        scritte.append(messaggio)
        vero(verso, messaggio)

    monkeypatch.setattr(tubo.Verso, "_scrivi", scrivi)
    presi: list = []
    assert "fatto" in _lancia(_la_foto_dall_archivio(nell_archivio, casa), presi.append)
    assert presi[0].stdin.closed and "giro" in scritte[-1]
    quante = len(scritte)
    assert casa.archivio.chiudi(ATTESA)
    assert len(scritte) == quante


def test_senza_archivio_la_stanza_non_ha_sportello(nell_archivio, casa, monkeypatch):
    monkeypatch.setattr(lavoro, "_sportello",
                        lambda processo: pytest.fail("niente sportello"))
    presi: list = []
    uscita = nell_archivio.attesa / "1-mare.jpg"
    esito = _lancia(_lavoro("immagine", casa.foto / FOTO, uscita), presi.append)
    assert "fatto" in esito and presi[0].stdin.closed


FINTA = """import json
import sys

lavoro = json.loads(sys.stdin.readline())
for messaggio in lavoro["manda"]:
    print(json.dumps(messaggio), flush=True)
"""
ROTTO = {"guasto": "RecursionError", "dove": "tubo", "riga": "7"}


@pytest.mark.parametrize("manda, dall_archivio, esito", [
    ([{"tubo_rotto": ROTTO}, {"guasto": CHIUSO_ADESSO}], True,
     {"guasto": "rotto", "tipo": "RecursionError", "dove": "tubo", "riga": "7"}),
    ([{"tubo_rotto": ROTTO}, {"fatto": {"larghezza": 2}}], True,
     {"fatto": {"larghezza": 2}}),
    ([{"tubo_rotto": ROTTO}], True,
     {"guasto": "rotto", "tipo": "RecursionError", "dove": "tubo", "riga": "7"}),
    ([{"tubo_rotto": "tubo"}, {"guasto": CHIUSO_ADESSO}], True, {"guasto": CHIUSO_ADESSO}),
    ([{"tubo_rotto": ROTTO}, {"guasto": CHIUSO_ADESSO}], False, {"guasto": CHIUSO_ADESSO}),
])
def test_se_il_tubo_si_rompe_nella_stanza_si_scrive_e_non_sembra_chiuso(
        tmp_path, monkeypatch, manda, dall_archivio, esito):
    (tmp_path / "stanza_finta_del_tubo.py").write_text(FINTA, encoding="utf-8")
    monkeypatch.setenv("PYTHONPATH", str(tmp_path))
    scritti: list = []
    monkeypatch.setattr(registro, "errore",
                        lambda nome, **campi: scritti.append((nome, campi)))
    da_fare = {"manda": manda,
               "dall_archivio": {"impronta": "ab"} if dall_archivio else None}
    assert lavoro.lancia_la_stanza(da_fare, lambda fatti, totale: None,
                                   lambda processo: None, "stanza_finta_del_tubo") == esito
    rotti = [campi for nome, campi in scritti if nome == "sicuro.tubo_rotto"]
    if dall_archivio and isinstance(manda[0]["tubo_rotto"], dict):
        assert rotti == [{"tipo": "RecursionError", "dove": "tubo", "riga": "7"}]
    else:
        assert rotti == []


class _Rotto:

    def write(self, testo: str) -> None:
        raise BrokenPipeError

    def flush(self) -> None:
        pass


def test_se_il_tubo_verso_la_stanza_si_rompe_la_stanza_si_ferma():
    fermate: list = []
    allo_sportello = lavoro._sportello(SimpleNamespace(stdin=_Rotto(),
                                                       kill=lambda: fermate.append(1)))
    allo_sportello.chiudi()
    assert fermate == [1]


def test_allo_sportello_le_domande_arrivano_come_sono_partite():
    ricevute: list = []
    finto = SimpleNamespace(ricevi=ricevute.append)
    domanda = [4, "letta", b"\x00\xff", {"a": b"x"}]
    lavoro._allo_sportello(finto, tubo.in_testo(domanda))
    lavoro._allo_sportello(finto, {"b": "zz"})
    assert ricevute == [domanda]


@pytest.mark.parametrize("errore", [BrokenPipeError(), ValueError("chiuso")])
def test_chiudere_il_tubo_della_stanza_non_fa_cadere_niente(errore):
    chiuse: list = []

    def chiudi() -> None:
        chiuse.append(1)
        raise errore

    lavoro._chiudi(SimpleNamespace(close=chiudi))
    assert chiuse == [1]


def test_senza_archivio_la_stanza_fa_come_prima(monkeypatch):
    monkeypatch.setattr(sportello, "DaLontano", lambda *_: pytest.fail("niente sportello"))
    lavoro_da_fare = {"genere": "immagine", "originale": "a.jpg"}
    assert stanza._dall_archivio(lavoro_da_fare, print) is lavoro_da_fare
    assert stanza._dall_archivio(dict(lavoro_da_fare, dall_archivio={}),
                                 print)["originale"] == "a.jpg"


class _Lontano:

    chiesto: tuple = ()
    ricerca: Ricerca | None = None

    def __init__(self, notizie, risposte, giro):
        assert notizie is risposte is giro
        assert isinstance(notizie, tubo.DaVerso)

    def cerca(self, impronta, dimensione, percorsi, *, nome, intero):
        _Lontano.chiesto = (impronta, dimensione, percorsi, nome, intero)
        return _Lontano.ricerca


def _una(blake2b: str, diversa: bool = False) -> DallArchivio:
    return DallArchivio("00" * 16, "s/a.mov", 3, blake2b, False, diversa, lambda t: None)


def test_la_stanza_prende_solo_l_originale_con_la_sua_impronta(monkeypatch):
    monkeypatch.setattr(sportello, "DaLontano", _Lontano)
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    cercata = {"impronta": "ab" * 32, "dimensione": 3, "percorsi": ["C:/s/a.mov"],
               "nome": "s/a.mov"}
    da_fare = {"genere": "video", "originale": "C:/s/a.mov", "dall_archivio": cercata}
    for trovata in (_una("cd" * 32), _una("ab" * 32, diversa=True)):
        _Lontano.ricerca = Ricerca(TROVATA, trovata)
        with pytest.raises(ErroreOfficina) as preso:
            stanza._dall_archivio(da_fare, print)
        assert preso.value.codice == DIVERSA
    giusta = _una("ab" * 32)
    _Lontano.ricerca = Ricerca(TROVATA, giusta)
    fatto = stanza._dall_archivio(da_fare, print)
    assert fatto == dict(da_fare, originale=giusta) and da_fare["originale"] == "C:/s/a.mov"
    assert _Lontano.chiesto == ("ab" * 32, 3, ["C:/s/a.mov"], "s/a.mov", False)
    stanza._dall_archivio(dict(da_fare, genere="immagine"), print)
    assert _Lontano.chiesto[-1] is True


def test_dall_archivio_la_catena_usa_il_nome_e_l_impronta(tmp_path):
    trovata = DallArchivio("00" * 16, "s/Mare.JPG", 3, "ab" * 32, True, False,
                           lambda t: None)
    assert catena._originale({"originale": trovata}) is trovata
    assert catena._originale({"originale": str(tmp_path)}) == tmp_path
    assert metadati.formato_di(trovata) == "JPEG"
    assert metadati.formato_di(tmp_path / "a.webp") == "WEBP"
    with pytest.raises(ValueError):
        metadati.formato_di(DallArchivio("00" * 16, "s/a.txt", 3, "ab" * 32, True, False,
                                         lambda t: None))
    firma = catena._firma(trovata, motori.Finto(), 10, 20)
    assert firma == {"originale": "ab" * 32, "byte": 3, "larghezza": 10, "altezza": 20,
                     "motore": {"nome": motori.FINTO, "versione": "1"}}
    disco = tmp_path / "a.mov"
    disco.write_bytes(b"12345")
    assert catena._firma(disco, motori.Finto(), 10, 20)["originale"] == str(disco)


def _segnato(percorso: Path) -> Path:
    percorso.write_bytes(b"x")
    os.utime(percorso, ns=(7, 9))
    return percorso


def test_le_date_dall_archivio_si_rimettono_sulla_copia_nuova(tmp_path, monkeypatch):
    nuova = _segnato(tmp_path / "nuova.jpg")
    for strane in ({}, {"modifica": "5"}, {"modifica": True}, {"modifica": 5.0},
                   {"accesso": 10, "creazione": 11}):
        date.rimetti(nuova, strane)
        assert (os.stat(nuova).st_atime_ns, os.stat(nuova).st_mtime_ns) == (7, 9)
    date.rimetti(nuova, {"modifica": 50, "accesso": False})
    assert (os.stat(nuova).st_atime_ns, os.stat(nuova).st_mtime_ns) == (50, 50)
    date.rimetti(nuova, {"modifica": 60, "accesso": 70})
    assert (os.stat(nuova).st_atime_ns, os.stat(nuova).st_mtime_ns) == (70, 60)
    messe = []
    monkeypatch.setattr(date, "_creazione_su_windows",
                        lambda percorso, quando: messe.append((percorso, quando)))
    date.rimetti(nuova, {"modifica": 60, "creazione": 80})
    assert messe == ([(nuova, 80)] if os.name == "nt" else [])
    monkeypatch.setattr(date, "os", SimpleNamespace(name="nt", utime=os.utime))
    date.rimetti(nuova, {"modifica": 60, "creazione": 90})
    date.rimetti(nuova, {"modifica": 60, "creazione": "90"})
    date.rimetti(nuova, {"modifica": 60})
    assert messe[-1] == (nuova, 90) and len([1 for _, quando in messe if quando == 90]) == 1


def test_la_catena_prende_le_date_dal_disco_o_dall_archivio(tmp_path):
    vecchia = _segnato(tmp_path / "vecchia.jpg")
    nuova = tmp_path / "nuova.jpg"
    nuova.write_bytes(b"y")
    catena._date(vecchia, nuova, {"date": {"modifica": 99}})
    assert os.stat(nuova).st_mtime_ns == 9
    trovata = DallArchivio("00" * 16, "s/a.jpg", 3, "ab" * 32, True, False, lambda t: None)
    catena._date(trovata, nuova, {"date": {"modifica": 99}})
    assert os.stat(nuova).st_mtime_ns == 99
    catena._date(trovata, nuova, {})
    catena._date(trovata, nuova, {"date": None})
    assert os.stat(nuova).st_mtime_ns == 99
