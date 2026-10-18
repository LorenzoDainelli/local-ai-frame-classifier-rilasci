from __future__ import annotations

import errno
import io
import json
import os
import random
import shutil
import threading
import time
from contextlib import contextmanager
from pathlib import Path

import pytest

from officina.errori import ErroreOfficina
from officina.sicuro import chiavi, controllo, elenco, formato, sottofondo
from officina.sicuro.controllo import (GIORNO, MESE, Controllore, ControlloMensile,
                                       Esito, Rapporto, buchi_di, intervalli)
from officina.sicuro.copia import STATI_BUONI, DiscoArchivioGuasto, Fermato
from officina.sicuro.diretto import ALLINEA
from officina.sicuro.elenco import Elenco
from prove.test_sicuro_copia import Banco, _dati
from prove.test_sicuro_estrai import _foto, _rovina_blocco, _uscita

ATTESA = 20.0
VERO_OPEN = open


@pytest.fixture
def chiave():
    return chiavi.Chiave(bytes(range(32)))


@pytest.fixture(autouse=True)
def pezzi_piccoli(monkeypatch):
    monkeypatch.setattr(controllo, "PEZZO_DI_LETTURA", 3 * ALLINEA)


class Orologio:

    def __init__(self, ora: float | None = None):
        self.ora = time.time() + 2 * MESE if ora is None else ora

    def __call__(self) -> float:
        return self.ora


class Chiavetta:

    def __init__(self, cartella: Path):
        self.cartella = cartella
        self.cartella.mkdir(parents=True, exist_ok=True)
        self.chieste: list[str] = []

    def dove(self, numero: str) -> Path:
        return self.cartella / f"{numero}.ofs"

    def metti(self, banco: Banco, numero: str) -> Path:
        shutil.copyfile(banco.blob(numero), self.dove(numero))
        return self.dove(numero)

    def __call__(self, numero: str):
        self.chieste.append(numero)
        return self.dove(numero) if self.dove(numero).exists() else None


@contextmanager
def _sveglio():
    yield True


def _controllore(banco: Banco, **opzioni) -> Controllore:
    opzioni.setdefault("apri", banco.apri)
    opzioni.setdefault("adesso", Orologio())
    opzioni.setdefault("luoghi", lambda: [])
    return Controllore(banco.archivio, banco.elenco, banco.chiave, **opzioni)


def _un_file(banco: Banco, nome: str, misura: int, seme: int = 1) -> tuple[str, bytes]:
    dati = _dati(misura, seme)
    banco.metti(nome, dati)
    banco.giro()
    return banco.posto(nome).contenuto, dati


def _impronte(informazioni: dict) -> dict:
    return {"blake2b": informazioni["blake2b"], "sha256": informazioni["sha256"]}


def _intero(banco: Banco, numero: str) -> bool:
    informazioni = banco.elenco.contenuto(numero)
    try:
        with VERO_OPEN(banco.blob(numero), "rb") as file:
            return formato.controlla(file, banco.chiave, numero=bytes.fromhex(numero),
                                     testa=informazioni["testa"],
                                     impronte=_impronte(informazioni)).buono
    except FileNotFoundError:
        return False


def _leggibile(chiave, percorso: Path, informazioni: dict) -> bool:
    try:
        with VERO_OPEN(percorso, "rb") as file:
            return formato.controlla(file, chiave,
                                     numero=bytes.fromhex(informazioni["numero"]),
                                     testa=informazioni["testa"],
                                     impronte=_impronte(informazioni)).leggibile
    except FileNotFoundError:
        return False


def _forma(banco: Banco, numero: str) -> formato.Forma:
    informazioni = banco.elenco.contenuto(numero)
    if informazioni is not None:
        return formato.Forma.da_testa(informazioni["testa"])
    with VERO_OPEN(banco.blob(numero), "rb") as file:
        return formato.Contenuto(file, banco.chiave, numero=bytes.fromhex(numero)).forma


def _rovina(percorso: Path, punti, maschera: int = 0x5A) -> None:
    guasto = bytearray(percorso.read_bytes())
    for punto in punti:
        guasto[punto] ^= maschera
    percorso.write_bytes(bytes(guasto))


def _rovina_pezzo(banco: Banco, numero: str, pezzo: int = 0) -> None:
    forma = _forma(banco, numero)
    inizio = forma.inizio + pezzo * forma.pezzo
    _rovina(banco.blob(numero), range(inizio + 5, inizio + 45))


def _rovina_meta(banco: Banco, numero: str, quali=(0, 1)) -> None:
    forma = _forma(banco, numero)
    posti = (formato.TESTA.size, forma.peso - forma.inizio)
    _rovina(banco.blob(numero), [posti[quale] + 30 for quale in quali])


def _rovina_testa(banco: Banco, numero: str) -> None:
    _rovina(banco.blob(numero), [0, 1, 2])


def _rovina_tutto(banco: Banco, numero: str) -> None:
    forma = _forma(banco, numero)
    _rovina(banco.blob(numero), range(forma.inizio, forma.peso - forma.inizio), 0xA5)


def _meta_diversa(banco: Banco, numero: str, cambia) -> None:
    blob = banco.blob(numero)
    with VERO_OPEN(blob, "rb") as file:
        contenuto = formato.Contenuto(file, banco.chiave, numero=bytes.fromhex(numero))
        forma = contenuto.forma
        chiaro = formato._imbottisci(
            formato._meta_in_byte(contenuto.impronte, contenuto.dati),
            forma.meta - formato.ETICHETTA)
        cifrata = contenuto._cifratore.encrypt(formato._nonce(formato.META, 0),
                                               cambia(chiaro, contenuto),
                                               contenuto._accompagnamento)
    guasto = bytearray(blob.read_bytes())
    for dove in (formato.TESTA.size, forma.peso - forma.inizio):
        guasto[dove:dove + forma.meta] = cifrata
    blob.write_bytes(bytes(guasto))


def _imbottitura_sporca(chiaro: bytes, contenuto) -> bytes:
    return chiaro[:-1] + b"\x01"


def _scritta_larga(chiaro: bytes, contenuto) -> bytes:
    corpo = json.dumps({"impronte": contenuto.impronte, "dati": contenuto.dati},
                       indent=1).encode()
    return formato._imbottisci(corpo, len(chiaro))


def _gemello(banco: Banco, nome: str, buono: bool = True) -> tuple[str, str]:
    primo = banco.posto(nome).contenuto
    _scrivi_anche_nota(banco, [elenco.fatto_stato(primo, "rovinato")])
    banco.giro()
    secondo = banco.posto(nome).contenuto
    assert secondo != primo
    fatti = [elenco.fatto_posto("r1", "vecchio " + nome, "file", primo, {})]
    if buono:
        fatti.append(elenco.fatto_stato(primo, "buono"))
    _scrivi_anche_nota(banco, fatti)
    return primo, secondo


def _scrivi_anche_nota(banco: Banco, fatti: list[dict]) -> None:
    banco.elenco.registra(fatti)
    banco.elenco.scrivi_nota(fatti)


def _aperti(banco: Banco) -> list[str]:
    return [Path(nome).stem for nome, _ in banco.apri.aperti if nome.endswith(".ofs")]


def _nuovi(banco: Banco, prima: set[str]) -> list[str]:
    return sorted(set(banco.elenco.numeri()) - prima)


def _dati_del_blob(banco: Banco, numero: str) -> dict:
    with VERO_OPEN(banco.blob(numero), "rb") as file:
        return formato.Contenuto(file, banco.chiave, numero=bytes.fromhex(numero)).dati


def _tutto_del_blob(banco: Banco, numero: str) -> bytes:
    with VERO_OPEN(banco.blob(numero), "rb") as file:
        return formato.Contenuto(file, banco.chiave,
                                 numero=bytes.fromhex(numero)).tutto()


def _con_buchi(dati: bytes, blocchi) -> bytes:
    fatto = bytearray(dati)
    for blocco in blocchi:
        inizio = blocco * formato.BLOCCO
        fine = min(len(dati), inizio + formato.BLOCCO)
        fatto[inizio:fine] = bytes(fine - inizio)
    return bytes(fatto)


def _niente_provvisori(banco: Banco) -> None:
    assert [percorso for percorso in banco.archivio.rglob("*")
            if percorso.name.endswith((".nuovo", ".tenuto"))] == []


def _disco_pieno(monkeypatch) -> None:
    def finto(percorso, modo="r", *altro, **chiavi_):
        if os.fspath(percorso).endswith(".nuovo"):
            raise OSError(errno.ENOSPC, "disco pieno")
        return VERO_OPEN(percorso, modo, *altro, **chiavi_)

    monkeypatch.setattr(controllo, "open", finto, raising=False)


class _Storto:

    def __init__(self, file):
        self._file = file

    def write(self, dati) -> int:
        dati = bytearray(dati)
        if len(dati) > 200:
            dati[100] ^= 0x01
        return self._file.write(bytes(dati))

    def __getattr__(self, nome):
        return getattr(self._file, nome)

    def __enter__(self):
        return self

    def __exit__(self, *altro):
        self._file.close()


def _disco_storto(monkeypatch) -> None:
    def finto(percorso, modo="r", *altro, **chiavi_):
        file = VERO_OPEN(percorso, modo, *altro, **chiavi_)
        return _Storto(file) if os.fspath(percorso).endswith(".nuovo") else file

    monkeypatch.setattr(controllo, "open", finto, raising=False)


@pytest.mark.parametrize("numeri, attesi", [
    ([], []),
    ([3], [[3, 3]]),
    ([1, 2, 3, 5], [[1, 3], [5, 5]]),
    ([5, 1, 2, 2, 3], [[1, 3], [5, 5]]),
    ([0, 2, 4], [[0, 0], [2, 2], [4, 4]]),
    (range(10), [[0, 9]]),
])
def test_i_buchi_si_scrivono_a_intervalli(numeri, attesi):
    assert intervalli(numeri) == attesi


@pytest.mark.parametrize("seme", range(60))
def test_intervalli_e_buchi_tornano_uguali(seme):
    caso = random.Random(seme)
    blocchi = caso.randint(1, 300)
    buchi = {caso.randrange(blocchi) for _ in range(caso.randint(0, blocchi))}
    assert buchi_di({"buchi": intervalli(buchi)}, blocchi) == frozenset(buchi)


@pytest.mark.parametrize("dati", [
    None, [], "buchi", {}, {"buchi": None}, {"buchi": "1-2"}, {"buchi": [[1]]},
    {"buchi": [[1, 2, 3]]}, {"buchi": [[2, 1]]}, {"buchi": [[-1, 2]]},
    {"buchi": [[True, 2]]}, {"buchi": [[1.0, 2]]}, {"buchi": [(1, 2)]},
    {"buchi": [["1", "2"]]}, {"buchi": [[1, 2], None]}, {"buchi": [[0, None]]},
])
def test_buchi_scritti_male_non_si_accettano(dati):
    assert buchi_di(dati, 10) is None


def test_i_buchi_non_vanno_oltre_il_file():
    assert buchi_di({"buchi": [[3, 10 ** 15]]}, 5) == frozenset({3, 4})
    assert buchi_di({"buchi": [[10 ** 15, 10 ** 15 + 5]]}, 5) == frozenset()
    assert buchi_di({"buchi": []}, 5) == frozenset()


@pytest.mark.parametrize("rapporto, frase", [
    (Rapporto(finito=True, controllati=3), "Tutto a posto: 3 file riletti."),
    (Rapporto(finito=True, controllati=1234, riparati=["a", "b"]),
     "Tutto a posto: 1.234 file riletti, 2 riparati."),
    (Rapporto(finito=True), "Non c'era niente da rileggere."),
    (Rapporto(finito=False, controllati=2), "Il controllo non è finito."),
    (Rapporto(finito=True, controllati=2, rimandati=["a"]),
     "Il disco dell'archivio è pieno: 1 file da riparare aspetta un po' di "
     "spazio."),
    (Rapporto(finito=True, controllati=2, rimandati=["a", "b"]),
     "Il disco dell'archivio è pieno: 2 file da riparare aspettano un po' di "
     "spazio."),
    (Rapporto(finito=True, controllati=2, persi=["a"]),
     "Attenzione: 1 file è rovinato e non si ripara."),
    (Rapporto(finito=False, controllati=2, persi=["a", "b"], salvati={"a": "c"}),
     "Attenzione: 2 file sono rovinati e non si riparano. Ho messo da parte i "
     "pezzi buoni."),
    (Rapporto(finito=True, controllati=5000, persi=["a"] * 1500),
     "Attenzione: 1.500 file sono rovinati e non si riparano."),
])
def test_la_frase_del_controllo(rapporto, frase):
    assert rapporto.frase() == frase


def test_verde_e_allarme():
    assert Rapporto(finito=True, controllati=1).verde
    assert not Rapporto(finito=False, controllati=1).verde
    assert not Rapporto(finito=True, persi=["a"]).verde
    assert Rapporto(finito=True, persi=["a"]).allarme
    assert not Rapporto(finito=True, rimandati=["a"]).verde
    assert not Rapporto(finito=True, problemi=["nota_non_scritta"]).verde
    assert not Rapporto(finito=True, rimandati=["a"]).allarme


def test_un_file_ritrovato_esce_dai_persi():
    rapporto = Rapporto()
    rapporto.segna(Esito("a", "perso", "buono", "rovinato"))
    rapporto.segna(Esito("b", "perso", "incompleto", "rovinato", salvataggio=True))
    assert rapporto.persi == ["a"] and rapporto.come["perso"] == 2
    rapporto.ritrovato(Esito("a", "trovato", "rovinato", "riparato", riparato=True))
    assert rapporto.persi == [] and rapporto.riparati == ["a"]
    assert rapporto.come == {"perso": 1, "trovato": 1}
    rapporto.problema("x")
    rapporto.problema("x")
    assert rapporto.problemi == ["x"]


def test_un_file_appena_scritto_si_puo_riscrivere_uguale(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    numero, _ = _un_file(banco, "a.jpg", 3 * formato.BLOCCO + 5)
    with VERO_OPEN(banco.blob(numero), "rb") as file:
        assert formato.Contenuto(file, chiave, numero=bytes.fromhex(numero)).riscrivibile()


@pytest.mark.parametrize("cambia", [_imbottitura_sporca, _scritta_larga])
def test_informazioni_scritte_in_un_altro_modo_non_si_riscrivono(tmp_path, chiave,
                                                                 cambia):
    banco = Banco(tmp_path, chiave)
    numero, _ = _un_file(banco, "a.jpg", formato.BLOCCO + 5)
    _meta_diversa(banco, numero, cambia)
    with VERO_OPEN(banco.blob(numero), "rb") as file:
        contenuto = formato.Contenuto(file, chiave, numero=bytes.fromhex(numero))
        assert contenuto.dati is not None
        assert not contenuto.riscrivibile()


def test_senza_informazioni_non_si_riscrive(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    numero, _ = _un_file(banco, "a.jpg", formato.BLOCCO + 5)
    _rovina_meta(banco, numero)
    with VERO_OPEN(banco.blob(numero), "rb") as file:
        contenuto = formato.Contenuto(file, chiave, numero=bytes.fromhex(numero),
                                      testa=banco.elenco.contenuto(numero)["testa"])
        assert contenuto.dati is None and not contenuto.riscrivibile()


def test_tutto_sano_si_rilegge_e_dice_tutto_a_posto(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    for indice, misura in enumerate((0, 1, 3 * formato.BLOCCO + 17)):
        banco.metti(f"{indice}.jpg", _dati(misura, indice))
    banco.giro()
    prima = {numero: banco.blob(numero).read_bytes() for numero in banco.elenco.numeri()}
    orologio = Orologio()
    controllore = _controllore(banco, adesso=orologio)
    assert len(controllore.da_fare()) == 3
    rapporto = controllore.controlla()
    assert rapporto.controllati == 3 and rapporto.come == {"intatto": 3}
    assert rapporto.verde and not rapporto.allarme and rapporto.finito
    assert rapporto.frase() == "Tutto a posto: 3 file riletti."
    assert rapporto.byte == sum(banco.elenco.contenuto(numero)["dimensione"]
                                for numero in prima)
    for numero, blob in prima.items():
        informazioni = banco.elenco.contenuto(numero)
        assert informazioni["stato"] == "buono" and informazioni["perche"] is None
        assert informazioni["controllato"] == orologio.ora
        assert banco.blob(numero).read_bytes() == blob
    assert controllore.da_fare() == []
    assert rapporto.note >= 1 and rapporto.note_rifatte == 0
    _niente_provvisori(banco)


def test_un_file_sano_si_rilegge_ogni_mese(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    _un_file(banco, "a.jpg", 100)
    orologio = Orologio()
    controllore = _controllore(banco, adesso=orologio)
    controllore.controlla()
    orologio.ora += MESE - 1
    assert controllore.da_fare() == []
    orologio.ora += 1
    assert len(controllore.da_fare()) == 1


def test_un_file_appena_copiato_aspetta_un_mese(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    _un_file(banco, "a.jpg", 100)
    assert _controllore(banco, adesso=Orologio(time.time())).da_fare() == []
    assert _controllore(banco, adesso=Orologio(time.time())).controlla().frase() == (
        "Non c'era niente da rileggere.")


def test_un_file_rovinato_si_riguarda_ogni_giorno(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    numero, _ = _un_file(banco, "a.jpg", 2 * formato.BLOCCO)
    _rovina_tutto(banco, numero)
    (banco.sorgente / "a.jpg").unlink()
    orologio = Orologio()
    controllore = _controllore(banco, adesso=orologio)
    assert controllore.controlla().persi == [numero]
    orologio.ora += GIORNO - 1
    assert controllore.da_fare() == []
    orologio.ora += 1
    assert controllore.da_fare() == [numero]


def test_prima_si_rileggono_i_piu_vecchi(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    for indice in range(4):
        banco.metti(f"{indice}.jpg", _dati(10, indice))
    banco.giro()
    numeri = [banco.posto(f"{indice}.jpg").contenuto for indice in range(4)]
    adesso = time.time()
    banco.elenco.registra([elenco.fatto_stato(numero, "buono", quando=adesso - 40 * GIORNO
                                              + indice * GIORNO)
                           for indice, numero in enumerate(reversed(numeri))])
    assert _controllore(banco, adesso=Orologio(adesso)).da_fare() == list(reversed(numeri))


def test_si_possono_controllare_solo_alcuni(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    banco.metti("a.jpg", b"a")
    banco.metti("b.jpg", b"b")
    banco.giro()
    uno = banco.posto("a.jpg").contenuto
    rapporto = _controllore(banco).controlla([uno, uno, "0" * 32])
    assert rapporto.totale == 2 and rapporto.controllati == 1
    assert banco.elenco.contenuto(banco.posto("b.jpg").contenuto)["controllato"] is None


@pytest.mark.parametrize("rompi", ["pezzo", "testa", "meta", "meta_in_fondo",
                                   "riserva", "taglio", "ultimo_pezzo"])
def test_un_danno_piccolo_si_ripara_coi_pezzetti_e_torna_identico(tmp_path, chiave,
                                                                    rompi):
    banco = Banco(tmp_path, chiave)
    numero, dati = _un_file(banco, "a.jpg", 5 * formato.BLOCCO + 99)
    originale = banco.blob(numero).read_bytes()
    forma = _forma(banco, numero)
    if rompi == "pezzo":
        _rovina_pezzo(banco, numero, 17)
    elif rompi == "testa":
        _rovina_testa(banco, numero)
    elif rompi == "meta":
        _rovina_meta(banco, numero, (0,))
    elif rompi == "meta_in_fondo":
        _rovina_meta(banco, numero, (1,))
    elif rompi == "riserva":
        _rovina(banco.blob(numero), [forma.inizio + forma.pezzi * forma.pezzo + 9])
    elif rompi == "taglio":
        banco.blob(numero).write_bytes(originale[:-7])
    else:
        _rovina_pezzo(banco, numero, forma.pezzi - 1)
    assert banco.blob(numero).read_bytes() != originale
    chiavetta = Chiavetta(tmp_path / "chiavetta")
    rapporto = _controllore(banco, copie=[chiavetta]).controlla()
    assert rapporto.come == {"pezzetti": 1} and rapporto.riparati == [numero]
    assert rapporto.verde
    assert rapporto.frase() == "Tutto a posto: 1 file riletti, 1 riparati."
    assert banco.blob(numero).read_bytes() == originale
    informazioni = banco.elenco.contenuto(numero)
    assert (informazioni["stato"], informazioni["perche"]) == ("riparato", "pezzetti")
    assert chiavetta.chieste == []
    _niente_provvisori(banco)


def test_un_file_riparato_il_mese_dopo_e_intatto_e_resta_riparato(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    numero, _ = _un_file(banco, "a.jpg", 2 * formato.BLOCCO)
    _rovina_pezzo(banco, numero, 3)
    orologio = Orologio()
    _controllore(banco, adesso=orologio).controlla()
    orologio.ora += MESE
    rapporto = _controllore(banco, adesso=orologio).controlla()
    assert rapporto.come == {"intatto": 1} and rapporto.riparati == []
    informazioni = banco.elenco.contenuto(numero)
    assert (informazioni["stato"], informazioni["perche"]) == ("riparato", "pezzetti")


def test_un_file_segnato_rovinato_ma_sano_torna_riparato(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    numero, _ = _un_file(banco, "a.jpg", 50)
    banco.elenco.registra([elenco.fatto_stato(numero, "rovinato", "non_riparato")])
    rapporto = _controllore(banco).controlla()
    assert rapporto.come == {"intatto": 1}
    informazioni = banco.elenco.contenuto(numero)
    assert (informazioni["stato"], informazioni["perche"]) == ("riparato", "riletto")


def test_un_file_incompleto_resta_incompleto(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    numero, _ = _un_file(banco, "a.jpg", 2 * formato.BLOCCO)
    banco.elenco.registra([elenco.fatto_stato(numero, "incompleto", "buchi")])
    _rovina_pezzo(banco, numero, 2)
    rapporto = _controllore(banco).controlla()
    assert rapporto.riparati == [numero]
    informazioni = banco.elenco.contenuto(numero)
    assert (informazioni["stato"], informazioni["perche"]) == ("incompleto", "pezzetti")


def test_un_file_sparito_si_riprende_dalla_chiavetta(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    numero, _ = _un_file(banco, "a.jpg", 3 * formato.BLOCCO + 1)
    originale = banco.blob(numero).read_bytes()
    chiavetta = Chiavetta(tmp_path / "chiavetta")
    chiavetta.metti(banco, numero)
    banco.blob(numero).unlink()
    (banco.sorgente / "a.jpg").unlink()
    rapporto = _controllore(banco, copie=[chiavetta]).controlla()
    assert rapporto.come == {"copia": 1} and rapporto.riparati == [numero]
    assert banco.blob(numero).read_bytes() == originale
    assert banco.elenco.contenuto(numero)["perche"] == "copia"
    assert chiavetta.chieste == [numero]


def test_un_file_rovinato_si_ripara_da_una_chiavetta_un_po_rovinata(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    numero, _ = _un_file(banco, "a.jpg", 3 * formato.BLOCCO + 1)
    originale = banco.blob(numero).read_bytes()
    chiavetta = Chiavetta(tmp_path / "chiavetta")
    copia = chiavetta.metti(banco, numero)
    _rovina(copia, range(_forma(banco, numero).inizio + 10,
                         _forma(banco, numero).inizio + 30))
    _rovina_blocco(banco, numero, [1])
    (banco.sorgente / "a.jpg").unlink()
    rapporto = _controllore(banco, copie=[chiavetta]).controlla()
    assert rapporto.come == {"copia": 1}
    assert banco.blob(numero).read_bytes() == originale


def test_si_prova_una_chiavetta_dopo_l_altra(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    numero, _ = _un_file(banco, "a.jpg", 2 * formato.BLOCCO)
    originale = banco.blob(numero).read_bytes()
    rotta = Chiavetta(tmp_path / "rotta")
    _rovina_tutto(banco, numero)
    rotta.metti(banco, numero)
    buona = Chiavetta(tmp_path / "buona")
    buona.dove(numero).write_bytes(originale)
    (banco.sorgente / "a.jpg").unlink()

    def guasta(numero_):
        raise OSError(errno.EIO, "chiavetta staccata")

    rapporto = _controllore(banco, copie=[guasta, rotta, lambda n: None,
                                          buona]).controlla()
    assert rapporto.come == {"copia": 1}
    assert banco.blob(numero).read_bytes() == originale


def test_la_copia_di_un_altro_file_non_si_usa(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    banco.metti("a.jpg", _dati(2 * formato.BLOCCO, 1))
    banco.metti("b.jpg", _dati(2 * formato.BLOCCO, 2))
    banco.giro()
    uno, due = banco.posto("a.jpg").contenuto, banco.posto("b.jpg").contenuto
    chiavetta = Chiavetta(tmp_path / "chiavetta")
    shutil.copyfile(banco.blob(due), chiavetta.dove(uno))
    rovinato = None
    _rovina_tutto(banco, uno)
    rovinato = banco.blob(uno).read_bytes()
    (banco.sorgente / "a.jpg").unlink()
    rapporto = _controllore(banco, copie=[chiavetta]).controlla([uno])
    assert rapporto.persi == [uno]
    assert banco.blob(uno).read_bytes() == rovinato


def test_la_chiavetta_che_manca_non_ferma_niente(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    numero, _ = _un_file(banco, "a.jpg", 2 * formato.BLOCCO)
    _rovina_tutto(banco, numero)
    rapporto = _controllore(banco, copie=[lambda n: tmp_path / "non c'è.ofs"]).controlla()
    assert rapporto.come == {"originale": 1} and rapporto.riparati == [numero]


def test_due_gemelli_rotti_in_punti_diversi_si_rifanno_al_loro_posto(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    banco.metti("a.jpg", _dati(4 * formato.BLOCCO + 3))
    banco.giro()
    primo, secondo = _gemello(banco, "a.jpg")
    originali = {numero: banco.blob(numero).read_bytes() for numero in (primo, secondo)}
    _rovina_blocco(banco, primo, [1])
    _rovina_blocco(banco, secondo, [3])
    (banco.sorgente / "a.jpg").unlink()
    prima = set(banco.elenco.numeri())
    rapporto = _controllore(banco).controlla([primo, secondo])
    assert rapporto.come == {"pezzi": 2}
    assert sorted(rapporto.riparati) == sorted([primo, secondo])
    for numero, blob in originali.items():
        assert banco.blob(numero).read_bytes() == blob
        assert banco.elenco.contenuto(numero)["perche"] == "pezzi"
    assert _nuovi(banco, prima) == []


def test_un_gemello_sano_e_le_informazioni_perse_fanno_rileggere_il_gemello(tmp_path,
                                                                            chiave):
    banco = Banco(tmp_path, chiave)
    banco.metti("a.jpg", _dati(4 * formato.BLOCCO + 3))
    banco.giro()
    primo, secondo = _gemello(banco, "a.jpg")
    _rovina_meta(banco, primo)
    rovinato = banco.blob(primo).read_bytes()
    banco.apri.aperti.clear()
    prima = set(banco.elenco.numeri())
    rapporto = _controllore(banco).controlla([primo])
    assert rapporto.come == {"pezzi": 1} and rapporto.riparati == []
    assert secondo in _aperti(banco)
    assert banco.blob(primo).read_bytes() == rovinato
    informazioni = banco.elenco.contenuto(primo)
    assert (informazioni["stato"], informazioni["perche"]) == ("rovinato", "nel_gemello")
    assert _nuovi(banco, prima) == [] and rapporto.verde
    assert banco.elenco.allarmi() == []


def test_senza_informazioni_e_senza_gemelli_nasce_un_gemello(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    numero, dati = _un_file(banco, "a.jpg", 3 * formato.BLOCCO + 3)
    _rovina_meta(banco, numero)
    (banco.sorgente / "a.jpg").unlink()
    prima = set(banco.elenco.numeri())
    rapporto = _controllore(banco).controlla()
    nuovo = _nuovi(banco, prima)
    assert len(nuovo) == 1 and rapporto.gemelli == {numero: nuovo[0]}
    assert _tutto_del_blob(banco, nuovo[0]) == dati
    assert _intero(banco, nuovo[0])
    gemello = banco.elenco.contenuto(nuovo[0])
    assert gemello["stato"] == "buono" and _impronte(gemello) == _impronte(
        banco.elenco.contenuto(numero))
    fatti = _dati_del_blob(banco, nuovo[0])["fatti"]
    assert [fatto["percorso"] for fatto in fatti if fatto["fatto"] == "posto"] == [
        "a.jpg"]
    assert all(fatto["contenuto"] == nuovo[0] for fatto in fatti
               if fatto["fatto"] == "posto")
    assert banco.elenco.contenuto(numero)["perche"] == "nel_gemello"
    assert rapporto.verde
    resoconto = _uscita(banco).estrai("r1", tmp_path / "fuori")
    assert (Path(resoconto.cartella) / "a.jpg").read_bytes() == dati
    assert resoconto.verde


@pytest.mark.parametrize("cambia", [_imbottitura_sporca, _scritta_larga])
def test_informazioni_diverse_non_si_riscrivono_mai_al_loro_posto(tmp_path, chiave,
                                                                   cambia):
    banco = Banco(tmp_path, chiave)
    banco.metti("a.jpg", _dati(4 * formato.BLOCCO + 3))
    banco.giro()
    primo, secondo = _gemello(banco, "a.jpg")
    _meta_diversa(banco, primo, cambia)
    _rovina_blocco(banco, primo, [2])
    rovinato = banco.blob(primo).read_bytes()
    rapporto = _controllore(banco).controlla([primo])
    assert banco.blob(primo).read_bytes() == rovinato
    assert rapporto.riparati == []
    assert banco.elenco.contenuto(primo)["perche"] == "nel_gemello"


@pytest.mark.parametrize("volta", range(8))
def test_rifacendo_l_elenco_i_posti_restano_sull_originale(tmp_path, chiave, volta):
    banco = Banco(tmp_path, chiave)
    numero, _ = _un_file(banco, "a.jpg", 4 * formato.BLOCCO + 3)
    _rovina_blocco(banco, numero, [0, 1, 2, 3, 4])
    gemello = _controllore(banco).controlla().gemelli[numero]
    assert _dati_del_blob(banco, gemello)["gemello_di"] == [numero]
    prima = _stato_rifatto(banco.elenco)
    rifatto = _rifai_l_elenco(banco)
    assert _stato_rifatto(rifatto)["posti"] == prima["posti"]
    assert rifatto.attuale("r1", "a.jpg").contenuto == numero
    rifatto.chiudi()


def _via_le_note_nuove(banco: Banco, prima: set[str]) -> None:
    for nota in set(banco.elenco.note()) - prima:
        banco.blob(nota).unlink()


@pytest.mark.parametrize("sparito", [False, True])
def test_rifacendo_l_elenco_un_originale_perso_si_ricorda(tmp_path, chiave, sparito):
    banco = Banco(tmp_path, chiave)
    numero, dati = _un_file(banco, "a.jpg", 3 * formato.BLOCCO + 3)
    _rovina_meta(banco, numero)
    (banco.sorgente / "a.jpg").unlink()
    gemello = _controllore(banco).controlla().gemelli[numero]
    if sparito:
        banco.blob(numero).unlink()
    rifatto = _rifai_l_elenco(banco)
    assert rifatto.illeggibili == []
    informazioni = rifatto.contenuto(numero)
    assert (informazioni["stato"], informazioni["perche"]) == ("rovinato", "nel_gemello")
    assert _impronte(informazioni) == _impronte(rifatto.contenuto(gemello))
    assert rifatto.attuale("r1", "a.jpg").contenuto == numero
    assert rifatto.allarmi() == []
    banco.elenco = rifatto
    resoconto = _uscita(banco).estrai("r1", tmp_path / "fuori")
    assert (Path(resoconto.cartella) / "a.jpg").read_bytes() == dati
    assert resoconto.verde
    rifatto.chiudi()


def test_rifacendo_l_elenco_senza_ricordo_il_posto_passa_al_gemello(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    numero, dati = _un_file(banco, "a.jpg", 3 * formato.BLOCCO + 3)
    _rovina_meta(banco, numero)
    (banco.sorgente / "a.jpg").unlink()
    note = set(banco.elenco.note())
    gemello = _controllore(banco).controlla().gemelli[numero]
    _via_le_note_nuove(banco, note)
    banco.blob(numero).unlink()
    rifatto = _rifai_l_elenco(banco)
    assert rifatto.contenuto(numero) is None
    assert rifatto.attuale("r1", "a.jpg").contenuto == gemello
    assert "nomi_ritrovati" in rifatto.problemi
    assert rifatto.allarmi() == []
    banco.elenco = rifatto
    resoconto = _uscita(banco).estrai("r1", tmp_path / "fuori")
    assert (Path(resoconto.cartella) / "a.jpg").read_bytes() == dati
    assert resoconto.verde
    rifatto.chiudi()


def test_rifacendo_l_elenco_i_pezzi_salvati_prendono_il_posto_dell_originale(tmp_path,
                                                                            chiave):
    banco = Banco(tmp_path, chiave)
    numero, dati = _un_file(banco, "a.jpg", 4 * formato.BLOCCO + 3)
    _rovina_blocco(banco, numero, [2])
    (banco.sorgente / "a.jpg").unlink()
    note = set(banco.elenco.note())
    salvato = _controllore(banco).controlla().salvati[numero]
    _via_le_note_nuove(banco, note)
    banco.blob(numero).unlink()
    rifatto = _rifai_l_elenco(banco)
    assert rifatto.contenuto(numero) is None
    assert rifatto.attuale("r1", "a.jpg").contenuto == salvato
    assert rifatto.allarmi() == [salvato]
    banco.elenco = rifatto
    resoconto = _uscita(banco).estrai("r1", tmp_path / "fuori")
    assert (Path(resoconto.cartella) / "a.jpg").read_bytes() == _con_buchi(dati, [2])
    assert resoconto.rossi == [("rovinato", "a.jpg")]
    rifatto.chiudi()


def test_rifacendo_l_elenco_l_originale_sparito_resta_in_allarme(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    numero, dati = _un_file(banco, "a.jpg", 4 * formato.BLOCCO + 3)
    _rovina_blocco(banco, numero, [2])
    (banco.sorgente / "a.jpg").unlink()
    _controllore(banco).controlla()
    banco.blob(numero).unlink()
    rifatto = _rifai_l_elenco(banco)
    informazioni = rifatto.contenuto(numero)
    assert (informazioni["stato"], informazioni["perche"]) == ("rovinato", "non_riparato")
    assert rifatto.attuale("r1", "a.jpg").contenuto == numero
    assert rifatto.allarmi() == [numero]
    banco.elenco = rifatto
    resoconto = _uscita(banco).estrai("r1", tmp_path / "fuori")
    assert (Path(resoconto.cartella) / "a.jpg").read_bytes() == _con_buchi(dati, [2])
    assert resoconto.rossi == [("rovinato", "a.jpg")]
    rifatto.chiudi()


def test_il_gemello_si_ricorda_di_tutti_i_suoi_uguali(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    banco.metti("a.jpg", _dati(4 * formato.BLOCCO + 3))
    banco.giro()
    primo, secondo = _gemello(banco, "a.jpg", buono=False)
    _rovina_blocco(banco, primo, [1])
    _rovina_meta(banco, secondo)
    (banco.sorgente / "a.jpg").unlink()
    nuovo = _controllore(banco).controlla([secondo]).gemelli[secondo]
    dati = _dati_del_blob(banco, nuovo)
    assert dati["gemello_di"] == [secondo, primo]
    assert sorted(fatto["percorso"] for fatto in dati["fatti"]
                  if fatto["fatto"] == "posto") == ["a.jpg", "a.jpg", "vecchio a.jpg"]
    assert all(fatto["contenuto"] == nuovo for fatto in dati["fatti"]
               if fatto["fatto"] == "posto")


def test_il_ricordo_di_un_contenuto_si_controlla_bene():
    scritto = _scritto(b"ricordo")
    giusto = elenco.fatto_ricordo({
        "numero": scritto.numero, "dimensione": scritto.dimensione,
        "blake2b": scritto.blake2b, "sha256": scritto.sha256, "peso": scritto.peso,
        "testa": scritto.testa, "scritto": 5.0})
    assert elenco.valido(giusto) and giusto["testa"] == scritto.testa.hex()
    for chiave, valore in (("numero", "x"), ("dimensione", -1), ("blake2b", "zz"),
                           ("sha256", None), ("peso", 1.5), ("testa", "00"),
                           ("testa", "zz" * formato.TESTA.size), ("quando", -1)):
        assert not elenco.valido({**giusto, chiave: valore}), chiave


def test_un_file_rovinato_si_rifa_dall_originale_ancora_sul_disco(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    numero, dati = _un_file(banco, "a.jpg", 3 * formato.BLOCCO + 3)
    originale = banco.blob(numero).read_bytes()
    _rovina_blocco(banco, numero, [0, 1, 2, 3])
    prima = set(banco.elenco.numeri())
    rapporto = _controllore(banco).controlla()
    assert rapporto.come == {"originale": 1} and rapporto.riparati == [numero]
    assert banco.blob(numero).read_bytes() == originale
    nuovo = _nuovi(banco, prima)
    assert len(nuovo) == 1 and rapporto.gemelli == {numero: nuovo[0]}
    assert _tutto_del_blob(banco, nuovo[0]) == dati
    assert banco.elenco.contenuto(numero)["perche"] == "originale"


def test_un_originale_cambiato_non_si_usa(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    numero, dati = _un_file(banco, "a.jpg", 3 * formato.BLOCCO + 3)
    _rovina_tutto(banco, numero)
    rovinato = banco.blob(numero).read_bytes()
    banco.metti("a.jpg", bytes(len(dati)))
    prima = set(banco.elenco.numeri())
    rapporto = _controllore(banco).controlla()
    assert rapporto.persi == [numero]
    assert banco.blob(numero).read_bytes() == rovinato
    assert _nuovi(banco, prima) == []


def test_un_originale_che_cambia_mentre_lo_leggo_non_fa_danni(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    numero, dati = _un_file(banco, "a.jpg", 3 * formato.BLOCCO + 3)
    _rovina_tutto(banco, numero)
    rovinato = banco.blob(numero).read_bytes()
    originale = os.fspath(banco.sorgente / "a.jpg")

    def cambia(nome, senza_cache, volta, lettore):
        if nome == originale and volta >= 1:
            banco.metti("a.jpg", bytes(len(dati)))
        return lettore

    banco.apri.regole.append(cambia)
    rapporto = _controllore(banco).controlla()
    assert rapporto.persi == [numero]
    assert banco.blob(numero).read_bytes() == rovinato
    _niente_provvisori(banco)


def test_un_file_perso_si_cerca_ovunque_e_si_ritrova(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    numero, dati = _un_file(banco, "a.jpg", 3 * formato.BLOCCO + 3)
    originale = banco.blob(numero).read_bytes()
    _rovina_tutto(banco, numero)
    (banco.sorgente / "a.jpg").unlink()
    altrove = tmp_path / "altrove" / "vecchio disco" / "2001"
    altrove.mkdir(parents=True)
    (altrove / "simile.jpg").write_bytes(dati[:-1] + bytes([dati[-1] ^ 1]))
    (altrove / "copia di a.jpg").write_bytes(dati)
    rapporto = _controllore(banco, luoghi=lambda: [tmp_path / "altrove"]).controlla()
    assert rapporto.come == {"trovato": 1} and rapporto.persi == []
    assert rapporto.riparati == [numero] and not rapporto.allarme
    assert banco.blob(numero).read_bytes() == originale
    assert numero in rapporto.gemelli
    assert banco.elenco.contenuto(numero)["perche"] == "trovato"


def test_la_ricerca_trova_piu_file_nello_stesso_giro(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    tutti = {}
    for indice in range(3):
        numero, dati = _un_file(banco, f"{indice}.jpg", 2 * formato.BLOCCO, indice)
        tutti[numero] = dati
        _rovina_tutto(banco, numero)
        (banco.sorgente / f"{indice}.jpg").unlink()
    altrove = tmp_path / "altrove"
    altrove.mkdir()
    for indice, dati in enumerate(list(tutti.values())[:2]):
        (altrove / f"x{indice}").write_bytes(dati)
    rapporto = _controllore(banco, luoghi=lambda: [altrove]).controlla()
    assert rapporto.come == {"trovato": 2, "perso": 1}
    assert rapporto.persi == [list(tutti)[2]]


def test_la_ricerca_salta_la_cartella_dell_archivio(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    numero, dati = _un_file(banco, "a.jpg", 2 * formato.BLOCCO)
    _rovina_tutto(banco, numero)
    (banco.sorgente / "a.jpg").unlink()
    nascosto = banco.archivio / "strano"
    nascosto.mkdir()
    (nascosto / "a.jpg").write_bytes(dati)
    cestino = tmp_path / "$RECYCLE.BIN"
    cestino.mkdir()
    (cestino / "a.jpg").write_bytes(dati)
    rapporto = _controllore(banco, luoghi=lambda: [tmp_path]).controlla()
    assert rapporto.persi == [numero]


def test_la_ricerca_guarda_anche_le_cartelle_delle_foto(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    numero, dati = _un_file(banco, "a.jpg", 2 * formato.BLOCCO)
    _rovina_tutto(banco, numero)
    (banco.sorgente / "a.jpg").unlink()
    banco.metti("spostata/a.jpg", dati)
    rapporto = _controllore(banco, luoghi=None).controlla()
    assert rapporto.come == {"trovato": 1}


def test_la_ricerca_non_segue_i_collegamenti(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    numero, dati = _un_file(banco, "a.jpg", 2 * formato.BLOCCO)
    _rovina_tutto(banco, numero)
    (banco.sorgente / "a.jpg").unlink()
    fuori = tmp_path / "fuori di qui"
    fuori.mkdir()
    (fuori / "a.jpg").write_bytes(dati)
    altrove = tmp_path / "altrove"
    altrove.mkdir()
    try:
        (altrove / "collegamento").symlink_to(fuori, target_is_directory=True)
        (altrove / "file.jpg").symlink_to(fuori / "a.jpg")
    except OSError:
        pytest.skip("collegamenti non permessi")
    rapporto = _controllore(banco, luoghi=lambda: [altrove]).controlla()
    assert rapporto.persi == [numero]


def test_un_file_perso_davvero_fa_scattare_l_allarme(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    banco.metti("b.jpg", b"sano")
    numero, _ = _un_file(banco, "a.jpg", 2 * formato.BLOCCO)
    _rovina_tutto(banco, numero)
    (banco.sorgente / "a.jpg").unlink()
    rapporto = _controllore(banco).controlla()
    assert rapporto.persi == [numero] and rapporto.allarme and not rapporto.verde
    assert rapporto.frase() == "Attenzione: 1 file è rovinato e non si ripara."
    assert rapporto.salvati == {}
    informazioni = banco.elenco.contenuto(numero)
    assert (informazioni["stato"], informazioni["perche"]) == ("rovinato", "non_riparato")
    assert banco.elenco.allarmi() == [numero]


def test_un_file_sparito_senza_niente_e_perso(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    numero, _ = _un_file(banco, "a.jpg", 10)
    banco.blob(numero).unlink()
    (banco.sorgente / "a.jpg").unlink()
    rapporto = _controllore(banco).controlla()
    assert rapporto.persi == [numero]
    assert not banco.blob(numero).exists()


def test_i_pezzi_buoni_di_un_file_perso_si_mettono_da_parte(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    numero, dati = _un_file(banco, "a.jpg", 4 * formato.BLOCCO + 3)
    _rovina_blocco(banco, numero, [1, 3])
    (banco.sorgente / "a.jpg").unlink()
    prima = set(banco.elenco.numeri())
    orologio = Orologio()
    rapporto = _controllore(banco, adesso=orologio).controlla()
    assert rapporto.persi == [numero]
    salvato = rapporto.salvati[numero]
    assert _nuovi(banco, prima) == [salvato]
    assert rapporto.frase() == ("Attenzione: 1 file è rovinato e non si ripara. Ho "
                                "messo da parte i pezzi buoni.")
    informazioni = banco.elenco.contenuto(salvato)
    assert informazioni["stato"] == "incompleto"
    assert informazioni["perche"] == elenco.SALVATO + numero
    assert banco.elenco.salvati(numero) == [salvato]
    assert _intero(banco, salvato)
    assert _tutto_del_blob(banco, salvato) == _con_buchi(dati, [1, 3])
    dentro = _dati_del_blob(banco, salvato)
    assert dentro["salvato_da"] == numero and dentro["buchi"] == [[1, 1], [3, 3]]
    assert dentro["scritto"] == orologio.ora
    assert banco.elenco.allarmi() == [numero]
    assert banco.elenco.uguali(informazioni["dimensione"], informazioni["blake2b"],
                               informazioni["sha256"]) == [salvato]


def test_i_pezzi_salvati_non_si_rifanno_ogni_volta(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    numero, _ = _un_file(banco, "a.jpg", 4 * formato.BLOCCO + 3)
    _rovina_blocco(banco, numero, [1, 3])
    (banco.sorgente / "a.jpg").unlink()
    orologio = Orologio()
    primo = _controllore(banco, adesso=orologio).controlla()
    prima = set(banco.elenco.numeri())
    orologio.ora += GIORNO
    secondo = _controllore(banco, adesso=orologio).controlla()
    assert secondo.salvati == primo.salvati
    assert _nuovi(banco, prima) == []


def test_pezzi_salvati_migliori_si_aggiungono(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    numero, dati = _un_file(banco, "a.jpg", 4 * formato.BLOCCO + 3)
    sano = banco.blob(numero).read_bytes()
    _rovina_blocco(banco, numero, [1, 3])
    (banco.sorgente / "a.jpg").unlink()
    orologio = Orologio()
    vecchio = _controllore(banco, adesso=orologio).controlla().salvati[numero]
    banco.blob(numero).write_bytes(sano)
    _rovina_blocco(banco, numero, [1])
    orologio.ora += GIORNO
    nuovo = _controllore(banco, adesso=orologio).controlla().salvati[numero]
    assert nuovo != vecchio
    assert banco.elenco.salvati(numero) == [vecchio, nuovo]
    assert _tutto_del_blob(banco, nuovo) == _con_buchi(dati, [1])
    _rovina_tutto(banco, numero)
    resoconto = _uscita(banco).estrai("r1", tmp_path / "fuori")
    assert (Path(resoconto.cartella) / "a.jpg").read_bytes() == _con_buchi(dati, [1])
    assert resoconto.rossi == [("rovinato", "a.jpg")]


def test_pezzi_salvati_in_due_volte_si_completano(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    numero, dati = _un_file(banco, "a.jpg", 4 * formato.BLOCCO + 3)
    sano = banco.blob(numero).read_bytes()
    _rovina_blocco(banco, numero, [1, 3])
    (banco.sorgente / "a.jpg").unlink()
    orologio = Orologio()
    _controllore(banco, adesso=orologio).controlla()
    banco.blob(numero).write_bytes(sano)
    _rovina_blocco(banco, numero, [0, 2, 3, 4])
    resoconto = _uscita(banco).estrai("r1", tmp_path / "fuori")
    assert (Path(resoconto.cartella) / "a.jpg").read_bytes() == _con_buchi(dati, [3])
    assert resoconto.rossi == [("rovinato", "a.jpg")]


def test_estrarre_un_file_perso_usa_i_pezzi_salvati(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    banco.metti("b.jpg", b"sano")
    numero, dati = _un_file(banco, "a.jpg", 4 * formato.BLOCCO + 3)
    _rovina_blocco(banco, numero, [2])
    (banco.sorgente / "a.jpg").unlink()
    _controllore(banco).controlla()
    _rovina_tutto(banco, numero)
    resoconto = _uscita(banco).estrai("r1", tmp_path / "fuori")
    fatta = Path(resoconto.cartella)
    assert (fatta / "a.jpg").read_bytes() == _con_buchi(dati, [2])
    assert (fatta / "b.jpg").read_bytes() == b"sano"
    assert resoconto.rossi == [("rovinato", "a.jpg")]


def test_estrarre_con_i_pezzi_salvati_e_il_buco_ancora_leggibile(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    numero, dati = _un_file(banco, "a.jpg", 4 * formato.BLOCCO + 3)
    sano = banco.blob(numero).read_bytes()
    _rovina_blocco(banco, numero, [2])
    (banco.sorgente / "a.jpg").unlink()
    _controllore(banco).controlla()
    banco.blob(numero).write_bytes(sano)
    _rovina_blocco(banco, numero, [0, 1, 3])
    resoconto = _uscita(banco).estrai("r1", tmp_path / "fuori")
    assert (Path(resoconto.cartella) / "a.jpg").read_bytes() == dati
    assert resoconto.verde


def test_i_pezzi_salvati_rovinati_non_si_usano(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    numero, dati = _un_file(banco, "a.jpg", 4 * formato.BLOCCO + 3)
    _rovina_blocco(banco, numero, [2])
    (banco.sorgente / "a.jpg").unlink()
    salvato = _controllore(banco).controlla().salvati[numero]
    _rovina_meta(banco, salvato)
    resoconto = _uscita(banco).estrai("r1", tmp_path / "fuori")
    assert (Path(resoconto.cartella) / "a.jpg").read_bytes() == _con_buchi(dati, [2])
    assert resoconto.rossi == [("rovinato", "a.jpg")]


def test_un_file_tutto_perso_non_lascia_pezzi_salvati(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    numero, _ = _un_file(banco, "a.jpg", 2 * formato.BLOCCO)
    _rovina_blocco(banco, numero, [0, 1])
    (banco.sorgente / "a.jpg").unlink()
    prima = set(banco.elenco.numeri())
    rapporto = _controllore(banco).controlla()
    assert rapporto.persi == [numero] and rapporto.salvati == {}
    assert _nuovi(banco, prima) == []


def test_i_pezzi_salvati_persi_non_fanno_allarme(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    numero, _ = _un_file(banco, "a.jpg", 4 * formato.BLOCCO + 3)
    _rovina_blocco(banco, numero, [2])
    (banco.sorgente / "a.jpg").unlink()
    orologio = Orologio()
    salvato = _controllore(banco, adesso=orologio).controlla().salvati[numero]
    _rovina_tutto(banco, salvato)
    orologio.ora += MESE
    prima = set(banco.elenco.numeri())
    rapporto = _controllore(banco, adesso=orologio).controlla([salvato])
    assert rapporto.persi == [] and rapporto.come == {"perso": 1}
    informazioni = banco.elenco.contenuto(salvato)
    assert informazioni["stato"] == "rovinato"
    assert informazioni["perche"] == elenco.SALVATO + numero
    assert _nuovi(banco, prima) == []
    assert banco.elenco.allarmi() == [numero]


def test_i_pezzi_salvati_si_riparano_coi_loro_pezzetti(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    numero, _ = _un_file(banco, "a.jpg", 4 * formato.BLOCCO + 3)
    _rovina_blocco(banco, numero, [2])
    (banco.sorgente / "a.jpg").unlink()
    orologio = Orologio()
    salvato = _controllore(banco, adesso=orologio).controlla().salvati[numero]
    buono = banco.blob(salvato).read_bytes()
    _rovina_pezzo(banco, salvato, 5)
    orologio.ora += MESE
    rapporto = _controllore(banco, adesso=orologio).controlla([salvato])
    assert rapporto.riparati == [salvato]
    assert banco.blob(salvato).read_bytes() == buono
    informazioni = banco.elenco.contenuto(salvato)
    assert informazioni["stato"] == "incompleto"
    assert informazioni["perche"] == elenco.SALVATO + numero


def test_l_elenco_rifatto_ritrova_i_pezzi_salvati(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    numero, dati = _un_file(banco, "a.jpg", 4 * formato.BLOCCO + 3)
    _rovina_blocco(banco, numero, [2])
    (banco.sorgente / "a.jpg").unlink()
    salvato = _controllore(banco).controlla().salvati[numero]
    banco.chiudi()
    for percorso in (banco.archivio / elenco.ELENCO).iterdir():
        percorso.unlink()
    rifatto = Elenco.apri(banco.archivio, chiave)
    informazioni = rifatto.contenuto(salvato)
    assert informazioni["stato"] == "incompleto"
    assert informazioni["perche"] == elenco.SALVATO + numero
    assert rifatto.salvati(numero) == [salvato]
    assert rifatto.contenuto(numero)["stato"] == "rovinato"
    rifatto.chiudi()


def test_le_note_si_rileggono(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    banco.metti("a.jpg", b"a")
    banco.giro()
    banco.metti("b.jpg", b"b")
    banco.giro()
    note = banco.elenco.note()
    rapporto = _controllore(banco).controlla()
    assert rapporto.note == len(note) >= 2
    assert rapporto.note_rovinate == [] and rapporto.note_riparate == 0
    assert rapporto.note_rifatte == 0


def test_una_nota_rovinata_si_ripara(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    banco.metti("a.jpg", b"a")
    banco.giro()
    nota = banco.elenco.note()[0]
    sana = banco.blob(nota).read_bytes()
    _rovina(banco.blob(nota), [formato.TESTA.size + 2000])
    rapporto = _controllore(banco).controlla()
    assert rapporto.note_riparate == 1 and rapporto.note_rifatte == 0
    assert banco.blob(nota).read_bytes() == sana


def test_una_nota_persa_si_prende_dalla_chiavetta(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    banco.metti("a.jpg", b"a")
    banco.giro()
    nota = banco.elenco.note()[0]
    sana = banco.blob(nota).read_bytes()
    chiavetta = Chiavetta(tmp_path / "chiavetta")
    chiavetta.metti(banco, nota)
    banco.blob(nota).unlink()
    rapporto = _controllore(banco, copie=[chiavetta]).controlla()
    assert rapporto.note_riparate == 1 and rapporto.note_rifatte == 0
    assert banco.blob(nota).read_bytes() == sana


def _stato_rifatto(aperto: Elenco) -> dict:
    return {
        "posti": sorted((posto.chiave, posto.radice, posto.percorso, posto.tipo,
                         posto.contenuto, posto.sparito, posto.segni,
                         json.dumps(posto.metadati, sort_keys=True))
                        for radice in aperto.radici()
                        for posto in aperto.dentro(radice["id"], anche_spariti=True)),
        "radici": [(radice["id"], radice["percorso"], radice["tolta"])
                   for radice in aperto.radici()],
        "stati": {numero: (aperto.contenuto(numero)["stato"],
                           aperto.contenuto(numero)["perche"])
                  for numero in aperto.numeri()},
        "giri": {radice["id"]: aperto.giro(radice["id"]) for radice in aperto.radici()},
    }


def _rifai_l_elenco(banco: Banco) -> Elenco:
    banco.chiudi()
    for percorso in (banco.archivio / elenco.ELENCO).iterdir():
        percorso.unlink()
    return Elenco.apri(banco.archivio, banco.chiave)


def test_una_nota_persa_fa_riscrivere_tutto_e_l_elenco_si_rifa_uguale(tmp_path,
                                                                     chiave):
    banco = Banco(tmp_path, chiave)
    for indice in range(5):
        banco.metti(f"cartella {indice % 2}/{indice}.jpg", _dati(100 + indice, indice))
    banco.giro()
    (banco.sorgente / "cartella 0" / "0.jpg").unlink()
    banco.metti("cartella 1/1.jpg", b"cambiata")
    banco.giro()
    numero = banco.posto("cartella 0/2.jpg").contenuto
    banco.elenco.registra([elenco.fatto_stato(numero, "incompleto", "buchi")])
    note = banco.elenco.note()
    assert len(note) >= 2
    for nota in note:
        _rovina_tutto(banco, nota)
    orologio = Orologio()
    rapporto = _controllore(banco, adesso=orologio).controlla()
    assert sorted(rapporto.note_rovinate) == sorted(note)
    assert rapporto.note_rifatte >= 1
    nuove = [nota for nota in banco.elenco.note() if nota not in note]
    assert any(_dati_del_blob(banco, nota).get("riassunto") is True for nota in nuove)
    prima = _stato_rifatto(banco.elenco)
    rifatto = _rifai_l_elenco(banco)
    assert _stato_rifatto(rifatto) == prima
    rifatto.chiudi()


def test_dopo_il_riassunto_le_note_vecchie_perse_non_fanno_riscrivere(tmp_path,
                                                                     chiave):
    banco = Banco(tmp_path, chiave)
    banco.metti("a.jpg", b"a")
    banco.giro()
    nota = banco.elenco.note()[0]
    _rovina_tutto(banco, nota)
    orologio = Orologio()
    assert _controllore(banco, adesso=orologio).controlla().note_rifatte == 1
    orologio.ora += MESE
    rapporto = _controllore(banco, adesso=orologio).controlla()
    assert rapporto.note_rovinate == [nota] and rapporto.note_rifatte == 0


def test_un_riassunto_rotto_a_meta_fa_riscrivere(tmp_path, chiave, monkeypatch):
    banco = Banco(tmp_path, chiave)
    for indice in range(6):
        banco.metti(f"{indice}.jpg", bytes([indice]))
    banco.giro()
    monkeypatch.setattr(controllo, "FATTI_PER_NOTA", 3)
    nota = banco.elenco.note()[0]
    _rovina_tutto(banco, nota)
    orologio = Orologio()
    primo = _controllore(banco, adesso=orologio).controlla()
    assert primo.note_rifatte >= 3
    riassunto = [numero for numero, quando in banco.elenco.note_scritte()
                 if quando == orologio.ora]
    _rovina_tutto(banco, riassunto[0])
    orologio.ora += MESE
    secondo = _controllore(banco, adesso=orologio).controlla()
    assert secondo.note_rifatte == primo.note_rifatte


def test_le_note_si_riscrivono_a_pezzi(tmp_path, chiave, monkeypatch):
    banco = Banco(tmp_path, chiave)
    for indice in range(7):
        banco.metti(f"{indice}.jpg", bytes([indice]))
    banco.giro()
    monkeypatch.setattr(controllo, "FATTI_PER_NOTA", 4)
    monkeypatch.setattr(elenco, "PAGINA", 3)
    nota = banco.elenco.note()[0]
    _rovina_tutto(banco, nota)
    orologio = Orologio()
    rapporto = _controllore(banco, adesso=orologio).controlla()
    nuove = [numero for numero, quando in banco.elenco.note_scritte()
             if quando == orologio.ora]
    fatti = sum(len(json.loads(_tutto_del_blob(banco, numero))) for numero in nuove)
    assert fatti == len(list(banco.elenco.fatti_completi()))
    assert rapporto.note_rifatte == len(nuove) == -(-fatti // 4)
    segnate = [_dati_del_blob(banco, numero).get("riassunto") for numero in nuove]
    assert segnate.count(True) == 1


def test_il_disco_pieno_rimanda_le_riparazioni(tmp_path, chiave, monkeypatch):
    banco = Banco(tmp_path, chiave)
    banco.metti("a.jpg", _dati(2 * formato.BLOCCO, 1))
    banco.metti("b.jpg", _dati(2 * formato.BLOCCO, 2))
    banco.metti("c.jpg", b"sano")
    banco.giro()
    uno, due = banco.posto("a.jpg").contenuto, banco.posto("b.jpg").contenuto
    _rovina_pezzo(banco, uno, 3)
    _rovina_tutto(banco, due)
    rovinati = {numero: banco.blob(numero).read_bytes() for numero in (uno, due)}
    _disco_pieno(monkeypatch)
    prima = set(banco.elenco.numeri())
    rapporto = _controllore(banco).controlla()
    assert sorted(rapporto.rimandati) == sorted([uno, due])
    assert rapporto.persi == [] and "spazio_finito" in rapporto.problemi
    assert rapporto.frase() == ("Il disco dell'archivio è pieno: 2 file da riparare "
                                "aspettano un po' di spazio.")
    assert not rapporto.verde and rapporto.finito
    for numero, blob in rovinati.items():
        assert banco.blob(numero).read_bytes() == blob
        assert banco.elenco.contenuto(numero)["controllato"] is None
    assert _nuovi(banco, prima) == []
    _niente_provvisori(banco)
    monkeypatch.undo()
    rapporto = _controllore(banco).controlla(rapporto.rimandati)
    assert rapporto.persi == [] and len(rapporto.riparati) == 2


def test_il_disco_pieno_non_ferma_le_riletture(tmp_path, chiave, monkeypatch):
    banco = Banco(tmp_path, chiave)
    banco.metti("a.jpg", _dati(2 * formato.BLOCCO, 1))
    banco.metti("b.jpg", b"sano")
    banco.giro()
    _rovina_pezzo(banco, banco.posto("a.jpg").contenuto, 3)
    _disco_pieno(monkeypatch)
    rapporto = _controllore(banco).controlla()
    assert rapporto.controllati == 2 and rapporto.come == {"intatto": 1}


def test_due_scritture_sbagliate_fermano_tutto(tmp_path, chiave, monkeypatch):
    banco = Banco(tmp_path, chiave)
    banco.metti("a.jpg", _dati(3 * formato.BLOCCO, 1))
    banco.metti("b.jpg", _dati(3 * formato.BLOCCO, 2))
    banco.giro()
    gemelli = [_gemello(banco, nome) for nome in ("a.jpg", "b.jpg")]
    for primo, _ in gemelli:
        _rovina_blocco(banco, primo, [1])
    rovinati = {primo: banco.blob(primo).read_bytes() for primo, _ in gemelli}
    _disco_storto(monkeypatch)
    with pytest.raises(DiscoArchivioGuasto):
        _controllore(banco).controlla([primo for primo, _ in gemelli])
    for primo, blob in rovinati.items():
        assert banco.blob(primo).read_bytes() == blob
    _niente_provvisori(banco)


def test_una_scrittura_sbagliata_sola_non_ferma_niente(tmp_path, chiave, monkeypatch):
    banco = Banco(tmp_path, chiave)
    banco.metti("a.jpg", _dati(3 * formato.BLOCCO, 1))
    banco.giro()
    primo, secondo = _gemello(banco, "a.jpg")
    _rovina_blocco(banco, primo, [1])
    rovinato = banco.blob(primo).read_bytes()
    _disco_storto(monkeypatch)
    rapporto = _controllore(banco).controlla([primo])
    assert banco.blob(primo).read_bytes() == rovinato
    assert banco.elenco.contenuto(primo)["perche"] == "nel_gemello"
    assert rapporto.persi == []


def test_se_l_archivio_sparisce_si_ferma_senza_segnare_niente(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    for indice in range(3):
        banco.metti(f"{indice}.jpg", _dati(100, indice))
    banco.giro()
    contenuti = banco.archivio / elenco.CONTENUTI

    def stacca(nome, senza_cache, volta, lettore):
        if nome.endswith(".ofs") and len(banco.apri.aperti) >= 2:
            lettore.close()
            contenuti.rename(banco.archivio / "staccato")
            raise FileNotFoundError(errno.ENOENT, "sparito", nome)
        return lettore

    banco.apri.regole.append(stacca)
    with pytest.raises(ErroreOfficina) as preso:
        _controllore(banco).controlla()
    assert preso.value.codice == "archivio_sparito"
    stati = [banco.elenco.contenuto(numero)["stato"] for numero in banco.elenco.numeri()]
    assert stati == ["buono"] * 3


def test_un_archivio_staccato_non_si_controlla(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    _un_file(banco, "a.jpg", 10)
    shutil.rmtree(banco.archivio / elenco.CONTENUTI)
    with pytest.raises(ErroreOfficina) as preso:
        _controllore(banco).controlla()
    assert preso.value.codice == "archivio_sparito"


def test_fermato_a_meta_riprende_da_dove_era(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    for indice in range(5):
        banco.metti(f"{indice}.jpg", _dati(100, indice))
    banco.giro()
    volte = [0]

    def aspetta():
        volte[0] += 1
        if volte[0] == 3:
            raise Fermato

    orologio = Orologio()
    with pytest.raises(Fermato):
        _controllore(banco, adesso=orologio, aspetta=aspetta).controlla()
    banco = banco.riapri()
    fatti = [numero for numero in banco.elenco.numeri()
             if banco.elenco.contenuto(numero)["controllato"] == orologio.ora]
    assert len(fatti) == 2
    controllore = _controllore(banco, adesso=orologio)
    assert len(controllore.da_fare()) == 3
    assert controllore.controlla().controllati == 3
    assert controllore.da_fare() == []


def test_fermato_dopo_una_riparazione_la_ricorda(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    banco.metti("a.jpg", _dati(2 * formato.BLOCCO, 1))
    banco.metti("b.jpg", _dati(2 * formato.BLOCCO, 2))
    banco.giro()
    numeri = banco.elenco.da_controllare(time.time() + 1)
    _rovina_pezzo(banco, numeri[0], 2)
    volte = [0]

    def aspetta():
        volte[0] += 1
        if banco.elenco.contenuto(numeri[0])["stato"] == "riparato":
            raise Fermato

    with pytest.raises(Fermato):
        _controllore(banco, aspetta=aspetta).controlla()
    banco = banco.riapri()
    informazioni = banco.elenco.contenuto(numeri[0])
    assert (informazioni["stato"], informazioni["perche"]) == ("riparato", "pezzetti")
    nota = banco.elenco.note()[-1]
    fatti = json.loads(_tutto_del_blob(banco, nota))
    assert any(fatto["fatto"] == "stato" and fatto["numero"] == numeri[0]
               for fatto in fatti)


def test_il_controllo_in_sottofondo_finisce_e_racconta(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    banco.metti("a.jpg", _dati(2 * formato.BLOCCO, 1))
    banco.metti("b.jpg", b"b")
    banco.giro()
    _rovina_pezzo(banco, banco.posto("a.jpg").contenuto, 1)
    lavoro = ControlloMensile(banco.archivio, banco.elenco, chiave, sveglio=_sveglio,
                              apri=banco.apri, adesso=Orologio(), luoghi=lambda: [])
    assert lavoro.istantanea()["frase"] == "Il controllo non è finito."
    assert lavoro.avvia()
    assert lavoro.aspetta_fine(ATTESA)
    istantanea = lavoro.istantanea()
    assert istantanea["stato"] == sottofondo.FINITO
    assert istantanea["verde"] and istantanea["finito"] and not istantanea["allarme"]
    assert istantanea["controllati"] == 2 and istantanea["riparati"] == 1
    assert istantanea["come"] == {"intatto": 1, "pezzetti": 1}
    assert istantanea["frase"] == "Tutto a posto: 2 file riletti, 1 riparati."
    assert istantanea["fase"] is None and istantanea["errore"] is None
    assert istantanea["fatti"] == istantanea["totale"] == 2
    assert istantanea["letti"] > 0 and istantanea["note"] >= 1
    assert set(istantanea) == {
        "stato", "fase", "numero", "fatti", "totale", "letti", "controllati", "byte",
        "come", "riparati", "gemelli", "persi", "salvati", "rimandati", "note",
        "note_riparate", "note_rovinate", "note_rifatte", "problemi", "allarme",
        "verde", "finito", "frase", "errore", "codice"}
    json.dumps(istantanea)


def test_il_controllo_in_sottofondo_solo_su_alcuni(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    banco.metti("a.jpg", b"a")
    banco.metti("b.jpg", b"b")
    banco.giro()
    uno = banco.posto("a.jpg").contenuto
    lavoro = ControlloMensile(banco.archivio, banco.elenco, chiave, sveglio=_sveglio,
                              apri=banco.apri, adesso=Orologio(), luoghi=lambda: [])
    assert lavoro.avvia([uno])
    assert lavoro.aspetta_fine(ATTESA)
    assert lavoro.istantanea()["controllati"] == 1
    assert lavoro.istantanea()["note"] == 0


def test_il_controllo_in_sottofondo_dice_l_allarme(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    numero, _ = _un_file(banco, "a.jpg", 4 * formato.BLOCCO)
    _rovina_blocco(banco, numero, [1])
    (banco.sorgente / "a.jpg").unlink()
    lavoro = ControlloMensile(banco.archivio, banco.elenco, chiave, sveglio=_sveglio,
                              apri=banco.apri, adesso=Orologio(), luoghi=lambda: [])
    lavoro.avvia()
    assert lavoro.aspetta_fine(ATTESA)
    istantanea = lavoro.istantanea()
    assert istantanea["allarme"] and istantanea["persi"] == [numero]
    assert list(istantanea["salvati"]) == [numero]
    assert istantanea["frase"].startswith("Attenzione: 1 file è rovinato")


def test_il_controllo_in_sottofondo_va_in_pausa_e_si_ferma(tmp_path, chiave,
                                                          monkeypatch):
    monkeypatch.setattr(controllo, "OGNI_QUANTI_BLOCCHI", 1)
    banco = Banco(tmp_path, chiave)
    for indice in range(4):
        banco.metti(f"{indice}.jpg", _dati(4 * formato.BLOCCO, indice))
    banco.giro()
    porta = threading.Event()
    dentro = threading.Event()

    def rallenta():
        if lavoro.controllore.avanzamento.fatti == 1:
            dentro.set()
            porta.wait(ATTESA)
        return False

    lavoro = ControlloMensile(banco.archivio, banco.elenco, chiave, sveglio=_sveglio,
                              rallenta=rallenta, apri=banco.apri, adesso=Orologio(),
                              luoghi=lambda: [])
    assert lavoro.avvia()
    assert dentro.wait(ATTESA)
    assert not lavoro.avvia()
    lavoro.pausa()
    assert lavoro.stato == sottofondo.IN_PAUSA
    porta.set()
    assert not lavoro.aspetta_fine(0.2)
    lavoro.ferma()
    assert lavoro.aspetta_fine(ATTESA)
    istantanea = lavoro.istantanea()
    assert istantanea["stato"] == sottofondo.FERMATO
    assert not istantanea["finito"] and istantanea["frase"] == "Il controllo non è finito."
    assert 1 <= istantanea["controllati"] < 4
    assert lavoro.avvia()
    assert lavoro.aspetta_fine(ATTESA)
    assert lavoro.istantanea()["controllati"] == 4 - istantanea["controllati"]


def test_il_controllo_in_sottofondo_col_disco_guasto(tmp_path, chiave, monkeypatch):
    banco = Banco(tmp_path, chiave)
    banco.metti("a.jpg", _dati(3 * formato.BLOCCO, 1))
    banco.metti("b.jpg", _dati(3 * formato.BLOCCO, 2))
    banco.giro()
    gemelli = [_gemello(banco, nome) for nome in ("a.jpg", "b.jpg")]
    for primo, _ in gemelli:
        _rovina_blocco(banco, primo, [1])
    _disco_storto(monkeypatch)
    lavoro = ControlloMensile(banco.archivio, banco.elenco, chiave, sveglio=_sveglio,
                              apri=banco.apri, adesso=Orologio(), luoghi=lambda: [])
    lavoro.avvia([primo for primo, _ in gemelli])
    assert lavoro.aspetta_fine(ATTESA)
    assert lavoro.stato == sottofondo.GUASTO
    assert lavoro.istantanea()["codice"] == "disco_archivio_guasto"


def test_il_controllo_in_sottofondo_con_l_archivio_staccato(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    _un_file(banco, "a.jpg", 10)
    shutil.rmtree(banco.archivio / elenco.CONTENUTI)
    lavoro = ControlloMensile(banco.archivio, banco.elenco, chiave, sveglio=_sveglio,
                              apri=banco.apri, adesso=Orologio(), luoghi=lambda: [])
    lavoro.avvia()
    assert lavoro.aspetta_fine(ATTESA)
    assert lavoro.stato == sottofondo.ERRORE
    assert lavoro.codice == "archivio_sparito"


def _scritto(dati: bytes) -> formato.Scritto:
    return formato.scrivi_byte(io.BytesIO(), chiavi.Chiave(bytes(range(32))), dati,
                               {"nome": "x"})


def _elenco_finto(tmp_path, chiave) -> Elenco:
    return Elenco.apri(tmp_path / "archivio", chiave)


def test_l_elenco_sa_cosa_rileggere(tmp_path, chiave):
    registro = _elenco_finto(tmp_path, chiave)
    scritti = [_scritto(bytes([indice])) for indice in range(5)]
    registro.registra([elenco.fatto_contenuto(scritto, quando=100.0 + indice)
                       for indice, scritto in enumerate(scritti)])
    numeri = [scritto.numero for scritto in scritti]
    registro.registra([elenco.fatto_stato(numeri[0], "buono", quando=500.0),
                       elenco.fatto_stato(numeri[1], "rovinato", quando=400.0),
                       elenco.fatto_stato(numeri[2], "rovinato", quando=450.0)])
    assert registro.da_controllare(102.0) == []
    assert registro.da_controllare(103.0) == [numeri[3]]
    assert registro.da_controllare(104.0) == [numeri[3], numeri[4]]
    assert registro.da_controllare(104.0, 420.0) == [numeri[3], numeri[4], numeri[1]]
    assert registro.da_controllare(500.0) == [numeri[3], numeri[4], numeri[1],
                                              numeri[2], numeri[0]]
    assert registro.con_stato("rovinato") == sorted(numeri[1:3])
    registro.chiudi()


def test_l_elenco_sa_quali_sono_gli_allarmi(tmp_path, chiave):
    registro = _elenco_finto(tmp_path, chiave)
    solo, coperto, doppio, salvato, rotto_sano = (
        _scritto(b"solo"), _scritto(b"coperto"), _scritto(b"doppio"),
        _scritto(b"salvato"), _scritto(b"rotto e riparato"))
    gemello_coperto = _scritto(b"coperto")
    gemello_doppio = _scritto(b"doppio")
    gemello_riparato = _scritto(b"rotto e riparato")
    registro.registra([
        elenco.fatto_contenuto(solo, "rovinato", "non_riparato"),
        elenco.fatto_contenuto(coperto, "rovinato", "nel_gemello"),
        elenco.fatto_contenuto(gemello_coperto, "buono"),
        elenco.fatto_contenuto(doppio, "rovinato", "non_riparato"),
        elenco.fatto_contenuto(gemello_doppio, "rovinato", "non_riparato"),
        elenco.fatto_contenuto(salvato, "rovinato", elenco.SALVATO + solo.numero),
        elenco.fatto_contenuto(rotto_sano, "rovinato", "non_riparato"),
        elenco.fatto_contenuto(gemello_riparato, "riparato", "pezzi"),
        elenco.fatto_contenuto(_scritto(b"incompleto"), "incompleto", "buchi"),
    ])
    assert registro.allarmi() == sorted([solo.numero, doppio.numero,
                                         gemello_doppio.numero])
    assert registro.salvati(solo.numero) == [salvato.numero]
    assert registro.salvati(coperto.numero) == []
    registro.chiudi()


def test_le_note_scritte_hanno_la_loro_ora(tmp_path, chiave):
    registro = _elenco_finto(tmp_path, chiave)
    fatto = elenco.fatto_radice("r1", "/foto", quando=1.0)
    secondo = registro.scrivi_nota([fatto], 200.0)
    primo = registro.scrivi_nota([fatto], 100.0, riassunto=True)
    assert registro.note_scritte() == [(primo, 100.0), (secondo, 200.0)]
    with VERO_OPEN(elenco.percorso_contenuto(registro.cartella, primo), "rb") as file:
        dati = formato.Contenuto(file, chiave, numero=bytes.fromhex(primo)).dati
    assert dati == {"tipo": "nota", "scritto": 100.0, "riassunto": True}
    registro.chiudi()


def test_i_fatti_completi_sono_tutti_buoni_e_a_pagine(tmp_path, chiave, monkeypatch):
    monkeypatch.setattr(elenco, "PAGINA", 2)
    banco = Banco(tmp_path, chiave)
    for indice in range(5):
        banco.metti(f"{indice}/{indice}.jpg", bytes([indice]))
    banco.giro()
    (banco.sorgente / "0" / "0.jpg").unlink()
    banco.giro()
    numero = banco.posto("1/1.jpg").contenuto
    banco.elenco.registra([elenco.fatto_stato(numero, "rovinato", "non_riparato",
                                              quando=777.0)])
    fatti = list(banco.elenco.fatti_completi())
    assert all(elenco.valido(fatto) for fatto in fatti)
    tipi = [fatto["fatto"] for fatto in fatti]
    assert tipi.count("radice") == 1 and tipi.count("giro") == 1
    assert tipi.count("posto") == len([posto for posto in banco.elenco.dentro(
        "r1", anche_spariti=True)])
    assert tipi.count("sparito") == len([posto for posto in banco.elenco.dentro(
        "r1", anche_spariti=True) if posto.sparito is not None]) == 2
    stati = [fatto for fatto in fatti if fatto["fatto"] == "stato"]
    assert stati == [elenco.fatto_stato(numero, "rovinato", "non_riparato",
                                        quando=777.0)]
    assert [fatto for fatto in fatti if fatto["fatto"] == "ricordo"] == [
        elenco.fatto_ricordo(banco.elenco.contenuto(numero))]
    assert tipi.index("ricordo") < tipi.index("stato")
    assert len({json.dumps(fatto, sort_keys=True) for fatto in fatti}) == len(fatti)


DANNI = ("niente", "pezzo", "testa", "meta", "meta_tutte", "blocco", "tutto", "via",
         "taglio")
MISURE = (0, 1, 100, formato.BLOCCO - 1, formato.BLOCCO, formato.BLOCCO + 1,
          2 * formato.BLOCCO + 7, 4 * formato.BLOCCO + 3)


def _danneggia(banco: Banco, numero: str, danno: str, caso: random.Random) -> None:
    forma = _forma(banco, numero)
    if danno == "pezzo":
        _rovina_pezzo(banco, numero, caso.randrange(forma.pezzi))
    elif danno == "testa":
        _rovina_testa(banco, numero)
    elif danno == "meta":
        _rovina_meta(banco, numero, (caso.randrange(2),))
    elif danno == "meta_tutte":
        _rovina_meta(banco, numero)
    elif danno == "blocco":
        _rovina_blocco(banco, numero, caso.sample(range(forma.blocchi),
                                                  caso.randint(1, forma.blocchi)))
    elif danno == "tutto":
        _rovina_tutto(banco, numero)
    elif danno == "via":
        banco.blob(numero).unlink()
    elif danno == "taglio":
        blob = banco.blob(numero).read_bytes()
        banco.blob(numero).write_bytes(blob[:-caso.randint(1, formato.TESTA.size)])


def _senza_contenuto(posto: tuple) -> tuple:
    return posto[:4] + posto[5:]


def _foto_uguali(cartella: Path) -> dict:
    return {nome: dati for nome, (tipo, dati) in _foto(cartella).items()
            if tipo == "file"}


@pytest.mark.parametrize("seme", range(150))
def test_danni_a_caso_non_rovinano_mai_niente(tmp_path, chiave, seme):
    caso = random.Random(seme)
    banco = Banco(tmp_path, chiave)
    file = {}
    for indice in range(caso.randint(1, 4)):
        nome = f"f{indice}.jpg"
        file[nome] = _dati(caso.choice(MISURE), seme * 10 + indice)
        banco.metti(nome, file[nome])
    banco.giro()
    gemelli = {}
    if caso.random() < 0.35:
        nome = caso.choice(sorted(file))
        primo, secondo = _gemello(banco, nome, buono=caso.random() < 0.7)
        gemelli[primo] = secondo
        file["vecchio " + nome] = file[nome]
    posti = {nome: banco.posto(nome).contenuto for nome in file}
    originali = {numero: banco.blob(numero).read_bytes()
                 for numero in banco.elenco.numeri()}
    chiavetta = Chiavetta(tmp_path / "chiavetta")
    pulite = set()
    for numero in originali:
        tiro = caso.random()
        if tiro < 0.2:
            chiavetta.metti(banco, numero)
            pulite.add(numero)
        elif tiro < 0.3:
            _rovina(chiavetta.metti(banco, numero),
                    [caso.randrange(len(originali[numero])) for _ in range(3)])
    note = banco.elenco.note()
    note_rotte = [nota for nota in note if caso.random() < 0.15]
    for nota in note_rotte:
        _rovina_tutto(banco, nota)
    danni = {numero: caso.choice(DANNI) for numero in originali}
    for numero, danno in danni.items():
        _danneggia(banco, numero, danno, caso)
    rovinati = {numero: (banco.blob(numero).read_bytes()
                         if banco.blob(numero).exists() else None)
                for numero in originali}
    leggibili = {numero for numero in originali
                 if _leggibile(chiave, banco.blob(numero), banco.elenco.contenuto(numero))}
    sul_disco = set()
    altrove = tmp_path / "altrove"
    altrove.mkdir()
    for nome, dati in file.items():
        percorso = banco.sorgente / nome
        tiro = caso.random()
        if not percorso.exists():
            continue
        if tiro < 0.4:
            percorso.unlink()
        elif tiro < 0.5 and dati:
            banco.metti(nome, bytes(len(dati)) if any(dati) else b"\x01" * len(dati))
        else:
            sul_disco.add(posti[nome])
        if caso.random() < 0.15:
            (altrove / f"copia {nome}").write_bytes(dati)
            sul_disco.add(posti[nome])
    orologio = Orologio()
    rapporto = _controllore(banco, adesso=orologio, copie=[chiavetta],
                            luoghi=lambda: [altrove]).controlla()
    _niente_provvisori(banco)
    assert rapporto.finito and rapporto.controllati == len(originali)
    impronte = {numero: _impronte(banco.elenco.contenuto(numero))
                for numero in originali}
    for numero in originali:
        attuale = banco.blob(numero).read_bytes() if banco.blob(numero).exists() else None
        assert attuale in (originali[numero], rovinati[numero]), (numero, danni[numero])
        informazioni = banco.elenco.contenuto(numero)
        if informazioni["stato"] in STATI_BUONI:
            assert attuale == originali[numero]
        if attuale != rovinati[numero]:
            assert numero in rapporto.riparati
        if informazioni["perche"] == "nel_gemello":
            assert any(_intero(banco, altro) for altro in banco.elenco.uguali(
                informazioni["dimensione"], informazioni["blake2b"],
                informazioni["sha256"]) if altro != numero)
        salvo = (numero in leggibili or numero in pulite or numero in sul_disco
                 or any(altro in leggibili for altro in banco.elenco.uguali(
                     informazioni["dimensione"], informazioni["blake2b"],
                     informazioni["sha256"]) if altro in originali))
        if salvo:
            assert numero not in rapporto.persi, (numero, danni[numero])
        if numero in rapporto.persi:
            assert (informazioni["stato"], informazioni["perche"]) == (
                "rovinato", "non_riparato")
            assert numero in banco.elenco.allarmi()
    for numero in banco.elenco.numeri():
        if numero in originali:
            continue
        informazioni = banco.elenco.contenuto(numero)
        assert _intero(banco, numero)
        if (informazioni["perche"] or "").startswith(elenco.SALVATO):
            assert informazioni["stato"] == "incompleto"
            origine = informazioni["perche"][len(elenco.SALVATO):]
            assert origine in rapporto.persi and rapporto.salvati[origine] == numero
        else:
            assert informazioni["stato"] == "buono"
            assert _impronte(informazioni) in impronte.values()
    resoconto = _uscita(banco).estrai("r1", tmp_path / "fuori")
    uscite = _foto_uguali(Path(resoconto.cartella))
    rossi = {percorso for _, percorso in resoconto.rossi}
    for nome, dati in file.items():
        if posti[nome] not in rapporto.persi:
            assert uscite.get(nome) == dati, nome
            assert nome not in rossi
        else:
            assert nome in rossi
            if nome in uscite:
                assert len(uscite[nome]) == len(dati)
    numeri = set(banco.elenco.numeri())
    orologio.ora += GIORNO
    secondo = _controllore(banco, adesso=orologio, copie=[chiavetta],
                           luoghi=lambda: [altrove]).controlla()
    assert set(banco.elenco.numeri()) == numeri
    assert secondo.gemelli == {} and secondo.riparati == []
    assert set(secondo.persi) <= set(rapporto.persi)
    prima = _stato_rifatto(banco.elenco)
    rifatto = _rifai_l_elenco(banco)
    dopo = _stato_rifatto(rifatto)
    assert dopo["radici"] == prima["radici"]
    assert {_senza_contenuto(posto) for posto in dopo["posti"]} >= {
        _senza_contenuto(posto) for posto in prima["posti"]
        if posto[4] not in rapporto.persi}
    for posto in dopo["posti"]:
        if posto[4] is not None and posto[4] not in originali:
            assert rifatto.contenuto(posto[4]) is not None
    banco.elenco = rifatto
    di_nuovo = _uscita(banco).estrai("r1", tmp_path / "fuori di nuovo")
    rifatte = _foto_uguali(Path(di_nuovo.cartella))
    for nome, dati in file.items():
        if posti[nome] not in rapporto.persi:
            assert rifatte.get(nome) == dati, nome
    for numero, stato in dopo["stati"].items():
        if numero in prima["stati"] and numero not in note_rotte:
            assert stato[0] == prima["stati"][numero][0] or (
                prima["stati"][numero][0] == "senza_informazioni"), numero
    rifatto.chiudi()


@pytest.mark.parametrize("danno", ["via", "tutto", "meta_tutte"])
@pytest.mark.parametrize("al_gemello", ["tutto", "blocco", "via"])
def test_un_gemello_rovinato_ma_segnato_buono_non_basta(tmp_path, chiave, danno,
                                                        al_gemello):
    banco = Banco(tmp_path, chiave)
    banco.metti("a.jpg", _dati(4 * formato.BLOCCO + 3))
    banco.giro()
    primo, secondo = _gemello(banco, "a.jpg")
    (banco.sorgente / "a.jpg").unlink()
    _danneggia(banco, primo, al_gemello, random.Random(1))
    _danneggia(banco, secondo, danno, random.Random(2))
    rapporto = _controllore(banco).controlla([secondo])
    informazioni = banco.elenco.contenuto(secondo)
    if danno == "meta_tutte":
        nuovo = rapporto.gemelli[secondo]
        assert nuovo != primo and _intero(banco, nuovo)
        assert informazioni["perche"] == "nel_gemello" and rapporto.persi == []
    else:
        assert rapporto.persi == [secondo] and rapporto.gemelli == {}
        assert (informazioni["stato"], informazioni["perche"]) == ("rovinato",
                                                                   "non_riparato")


@pytest.mark.parametrize(("danno", "atteso"), [("via", ("rovinato", "nel_gemello")),
                                               ("tutto", ("riparato", "pezzi"))])
def test_un_gemello_riparato_dopo_salva_anche_chi_e_stato_controllato_prima(
        tmp_path, chiave, danno, atteso):
    banco = Banco(tmp_path, chiave)
    banco.metti("a.jpg", _dati(4 * formato.BLOCCO + 3))
    banco.giro()
    primo, secondo = _gemello(banco, "a.jpg")
    (banco.sorgente / "a.jpg").unlink()
    _rovina_pezzo(banco, primo)
    _danneggia(banco, secondo, danno, random.Random(3))
    rapporto = _controllore(banco).controlla([secondo, primo])
    assert rapporto.persi == [] and primo in rapporto.riparati
    assert _intero(banco, primo)
    informazioni = banco.elenco.contenuto(secondo)
    assert (informazioni["stato"], informazioni["perche"]) == atteso
    assert banco.elenco.allarmi() == [] and rapporto.verde
    assert rapporto.come == {"pezzetti": 1, "pezzi": 1}
