from __future__ import annotations

import errno
import json
import os
import random
import shutil
import time
from contextlib import contextmanager
from pathlib import Path

import pytest

from officina.errori import ErroreOfficina, PasswordSbagliata
from officina.sicuro import chiavetta, chiavi, controllo, elenco, formato
from officina.sicuro.chiavetta import (CARTELLA, LEGGIMI, PROGRAMMINO, RISERVA,
                                       SEGNO, STATO, AggiornaChiavetta, Chiavetta,
                                       ChiavettaStaccata, Guardiano, Resoconto,
                                       leggi_segno)
from officina.sicuro.controllo import MESE, Controllore
from officina.sicuro.copia import Fermato
from officina.sicuro.diretto import ALLINEA
from officina.sicuro.elenco import Elenco
from officina.sicuro.sottofondo import ERRORE, FERMATO, FINITO
from prove.test_sicuro_controllo import _rovina
from prove.test_sicuro_copia import Banco, _dati

LIBERO = 10 ** 15
ATTESA = 20.0
PASSWORD = "tre parole lunghe finte"
TESTO = "Spiegazione finta del formato.\n"
MISURE = (0, 1, 100, formato.BLOCCO - 1, formato.BLOCCO + 1, 2 * formato.BLOCCO + 7)
VERO_OPEN = open
_PORTA: dict = {}


@pytest.fixture
def chiave():
    return chiavi.Chiave(bytes(range(32)))


@pytest.fixture(autouse=True)
def pezzi_piccoli(monkeypatch):
    monkeypatch.setattr(chiavetta, "PEZZO", 3 * ALLINEA)
    monkeypatch.setattr(controllo, "PEZZO_DI_LETTURA", 3 * ALLINEA)


@contextmanager
def _sveglio():
    yield True


class Orologio:

    def __init__(self):
        self.ora = time.time() + 2 * MESE

    def __call__(self) -> float:
        return self.ora


def _metti_la_chiave(cartella: Path, chiave) -> None:
    if "porta" not in _PORTA:
        _PORTA["porta"] = chiavi._porta(chiave, PASSWORD, chiavi.COSTO)
    cartella.mkdir(parents=True, exist_ok=True)
    chiavi._scrivi(cartella, chiavi._documento(chiave, [_PORTA["porta"]]))


class Prova:

    def __init__(self, cartella: Path, chiave, **opzioni):
        self.base = cartella
        self.banco = Banco(cartella, chiave)
        self.chiave = chiave
        _metti_la_chiave(self.banco.archivio, chiave)
        self.radice = cartella / "E"
        self.radice.mkdir(exist_ok=True)
        self.orologio = Orologio()
        self.file: dict[str, bytes] = {}
        self.chiavetta = self.nuova(**opzioni)

    def nuova(self, **opzioni) -> Chiavetta:
        opzioni.setdefault("apri", self.banco.apri)
        opzioni.setdefault("spazio", lambda radice: LIBERO)
        opzioni.setdefault("stesso_disco", lambda uno, altro: False)
        opzioni.setdefault("sistema", lambda radice: "exFAT")
        opzioni.setdefault("adesso", self.orologio)
        opzioni.setdefault("leggimi", TESTO)
        return Chiavetta(self.banco.archivio, self.banco.elenco, self.chiave,
                         **opzioni)

    @property
    def dove(self) -> Path:
        return self.radice / CARTELLA

    def foto(self, quante: int = 3, seme: int = 1, misure=None) -> list[str]:
        caso = random.Random(seme)
        for indice in range(quante):
            nome = f"s{seme}/f{indice}.jpg"
            self.file[nome] = _dati(caso.choice(misure or MISURE) + indice, seme * 100 + indice)
            self.banco.metti(nome, self.file[nome])
        self.banco.giro()
        return [self.banco.posto(nome).contenuto for nome in self.file]

    def tutti(self) -> list[str]:
        return [*self.banco.elenco.numeri(), *self.banco.elenco.note()]

    def sopra(self, numero: str) -> Path:
        return elenco.percorso_contenuto(self.dove, numero)

    def pc(self, numero: str) -> Path:
        return self.banco.blob(numero)

    def pronta(self, **opzioni) -> Resoconto:
        self.chiavetta.prepara(self.radice, **opzioni)
        return self.chiavetta.aggiorna(self.radice)

    def stacca(self) -> Path:
        altrove = self.base / "staccata"
        os.rename(self.radice, altrove)
        return altrove

    def riattacca(self) -> None:
        os.rename(self.base / "staccata", self.radice)

    def provvisori(self) -> list[Path]:
        return [percorso for base in (self.base,) for percorso in base.rglob("*")
                if percorso.name.endswith((".nuovo", ".tenuto"))]


def _attese(banco: Banco, numero: str):
    informazioni = banco.elenco.contenuto(numero)
    if informazioni is None:
        return None, None
    return informazioni["testa"], {"blake2b": informazioni["blake2b"],
                                   "sha256": informazioni["sha256"]}


def _controllo(prova: Prova, percorso: Path, numero: str) -> formato.Controllo | None:
    testa, impronte = _attese(prova.banco, numero)
    try:
        with VERO_OPEN(percorso, "rb") as file:
            return formato.controlla(file, prova.chiave, numero=bytes.fromhex(numero),
                                     testa=testa, impronte=impronte)
    except (OSError, ErroreOfficina):
        return None


def _intatto(prova: Prova, percorso: Path, numero: str) -> bool:
    risultato = _controllo(prova, percorso, numero)
    return risultato is not None and risultato.buono


def _leggibile(prova: Prova, percorso: Path, numero: str) -> bool:
    risultato = _controllo(prova, percorso, numero)
    return risultato is not None and risultato.leggibile


def _forma_di(prova: Prova, percorso: Path, numero: str) -> formato.Forma:
    informazioni = prova.banco.elenco.contenuto(numero)
    if informazioni is not None:
        return formato.Forma.da_testa(informazioni["testa"])
    with VERO_OPEN(percorso, "rb") as file:
        return formato.Contenuto(file, prova.chiave, numero=bytes.fromhex(numero)).forma


def _danneggia(prova: Prova, percorso: Path, numero: str, danno: str,
               caso: random.Random) -> None:
    forma = _forma_di(prova, percorso, numero)
    if danno == "pezzo":
        inizio = forma.inizio + caso.randrange(forma.pezzi) * forma.pezzo
        _rovina(percorso, range(inizio + 5, inizio + 45))
    elif danno == "testa":
        _rovina(percorso, [0, 1, 2])
    elif danno == "meta":
        _rovina(percorso, [(formato.TESTA.size, forma.peso - forma.inizio)[caso.randrange(2)]
                           + 30])
    elif danno == "tutto":
        _rovina(percorso, range(forma.inizio, forma.peso - forma.inizio), 0xA5)
    elif danno == "via":
        percorso.unlink()
    elif danno == "taglio":
        dati = percorso.read_bytes()
        percorso.write_bytes(dati[:-caso.randint(1, formato.TESTA.size)])


def _byte(percorso: Path) -> bytes:
    with VERO_OPEN(percorso, "rb") as file:
        return file.read()


def _tutto_a_posto(prova: Prova) -> None:
    assert prova.provvisori() == []
    for numero in prova.tutti():
        assert prova.sopra(numero).is_file(), numero
        assert _byte(prova.sopra(numero)) == _byte(prova.pc(numero)), numero
        assert _intatto(prova, prova.sopra(numero), numero), numero
    for nome in (chiavi.FILE, chiavi.RISERVA):
        assert _byte(prova.dove / nome) == _byte(prova.banco.archivio / nome)
    assert (prova.radice / LEGGIMI).read_text("utf-8") == TESTO
    letto = Elenco.apri(prova.dove, prova.chiave, sola_lettura=True)
    try:
        assert set(letto.numeri()) == set(prova.banco.elenco.numeri())
        assert set(letto.note()) <= set(prova.banco.elenco.note())
        assert [radice["id"] for radice in letto.radici()] == [
            radice["id"] for radice in prova.banco.elenco.radici()]
    finally:
        letto.chiudi()
    assert prova.chiavetta.completa()


def _foto_sulla_chiavetta(prova: Prova) -> dict[str, bytes]:
    letto = Elenco.apri(prova.dove, prova.chiave, sola_lettura=True)
    trovate = {}
    try:
        for nome in prova.file:
            posto = letto.attuale("r1", nome)
            assert posto is not None, nome
            percorso = elenco.percorso_contenuto(prova.dove, posto.contenuto)
            with VERO_OPEN(percorso, "rb") as file:
                trovate[nome] = formato.Contenuto(
                    file, prova.chiave, numero=bytes.fromhex(posto.contenuto)).tutto()
    finally:
        letto.chiudi()
    return trovate


def _niente_scritto(radice: Path) -> list[str]:
    return sorted(percorso.relative_to(radice).as_posix() for percorso in radice.rglob("*"))


def _segno_finto(chiave, **cambi) -> dict:
    segno = {"tipo": chiavetta.TIPO, "versione": chiavetta.VERSIONE,
             "archivio": chiave.nome, "chiavetta": "ab" * 16, "creata": 1000.0}
    segno.update(cambi)
    segno["firma"] = chiavetta._firma(chiave, segno)
    return segno


def _scrivi_segno(radice: Path, segno: dict) -> None:
    (radice / CARTELLA).mkdir(parents=True, exist_ok=True)
    (radice / CARTELLA / SEGNO).write_text(json.dumps(segno), "utf-8")


def test_prepara_scrive_il_segno_firmato_e_lo_stato_cifrato(tmp_path, chiave):
    prova = Prova(tmp_path, chiave)
    prova.foto()
    esame = prova.chiavetta.prepara(prova.radice)
    assert esame.va_bene and esame.chi == "nostra"
    segno = leggi_segno(prova.radice)
    assert segno["archivio"] == chiave.nome
    assert chiavetta._segno_firmato(segno, chiave)
    assert prova.chiavetta.chi_e(prova.radice) == "nostra"
    for nome in (STATO, RISERVA):
        dati = (prova.banco.archivio / nome).read_bytes()
        assert segno["chiavetta"].encode() not in dati
        assert b"sopra" not in dati
    assert prova.chiavetta.preparata and not prova.chiavetta.persa


def test_preparare_due_volte_la_stessa_chiavetta_non_cambia_niente(tmp_path, chiave):
    prova = Prova(tmp_path, chiave)
    prova.chiavetta.prepara(prova.radice)
    primo = leggi_segno(prova.radice)
    prova.chiavetta.prepara(prova.radice)
    assert leggi_segno(prova.radice) == primo


def test_dopo_l_aggiornamento_c_e_tutto_e_le_foto_si_riprendono(tmp_path, chiave):
    prova = Prova(tmp_path, chiave)
    prova.foto(5)
    resoconto = prova.pronta()
    assert resoconto.finito and resoconto.copiati == len(prova.tutti())
    assert resoconto.frase().startswith("Puoi staccarla.")
    _tutto_a_posto(prova)
    assert _foto_sulla_chiavetta(prova) == prova.file


def test_la_seconda_volta_non_copia_niente(tmp_path, chiave):
    prova = Prova(tmp_path, chiave)
    prova.foto(4)
    prova.pronta()
    prova.banco.apri.aperti.clear()
    resoconto = prova.chiavetta.aggiorna(prova.radice)
    assert resoconto.copiati == 0 and resoconto.riletti == 0
    assert resoconto.frase() == "Puoi staccarla: era già tutto aggiornato."
    letti = {aperto[0] for aperto in prova.banco.apri.aperti}
    assert not any(percorso.startswith(os.fspath(prova.dove / elenco.CONTENUTI))
                   for percorso in letti)


def test_le_novita_si_aggiungono_e_il_resto_non_si_rilegge(tmp_path, chiave):
    prova = Prova(tmp_path, chiave)
    vecchi = set(prova.foto(3, seme=1))
    prova.pronta()
    prima = set(prova.tutti())
    prova.foto(2, seme=2)
    nuovi = set(prova.tutti()) - prima
    prova.banco.apri.aperti.clear()
    resoconto = prova.chiavetta.aggiorna(prova.radice)
    assert resoconto.copiati == len(nuovi) and resoconto.riletti == 0
    letti = {aperto[0] for aperto in prova.banco.apri.aperti}
    for numero in vecchi:
        assert os.fspath(prova.pc(numero)) not in letti
        assert os.fspath(prova.sopra(numero)) not in letti
    _tutto_a_posto(prova)


def test_dopo_un_mese_si_rilegge_solo_il_vecchio(tmp_path, chiave):
    prova = Prova(tmp_path, chiave)
    prova.foto(3, seme=1)
    prova.pronta()
    primi = set(prova.tutti())
    prova.orologio.ora += 20 * 24 * 3600
    prova.foto(2, seme=2)
    prova.chiavetta.aggiorna(prova.radice)
    secondi = set(prova.tutti()) - primi
    prova.orologio.ora += 11 * 24 * 3600
    resoconto = prova.chiavetta.aggiorna(prova.radice)
    rilette = set(prova.chiavetta._stato.sopra)
    assert resoconto.riletti == len(primi)
    assert all(prova.chiavetta._stato.sopra[numero] == prova.orologio.ora
               for numero in primi)
    assert all(prova.chiavetta._stato.sopra[numero] < prova.orologio.ora
               for numero in secondi)
    assert rilette >= primi | secondi
    assert prova.chiavetta.aggiorna(prova.radice).riletti == 0


@pytest.mark.parametrize("giorni", [29, 30, 31, 60])
def test_il_confine_del_mese(tmp_path, chiave, giorni):
    prova = Prova(tmp_path, chiave)
    prova.foto(2)
    prova.pronta()
    prova.orologio.ora += giorni * 24 * 3600
    resoconto = prova.chiavetta.aggiorna(prova.radice)
    assert resoconto.riletti == (len(prova.tutti()) if giorni >= 30 else 0)


def test_un_elenco_della_chiavetta_resta_con_due_fotografie(tmp_path, chiave):
    prova = Prova(tmp_path, chiave)
    prova.foto(2)
    prova.pronta()
    for seme in range(2, 6):
        prova.foto(1, seme=seme)
        prova.chiavetta.aggiorna(prova.radice)
    fotografie = sorted(percorso.name for percorso in (prova.dove / elenco.ELENCO).iterdir())
    assert len(fotografie) == chiavetta.FOTOGRAFIE_DA_TENERE
    assert fotografie[-1] == prova.banco.elenco.fotografia_attuale().name
    _tutto_a_posto(prova)


def test_i_file_provvisori_lasciati_a_meta_si_tolgono(tmp_path, chiave):
    prova = Prova(tmp_path, chiave)
    numeri = prova.foto(2)
    prova.pronta()
    resti = [prova.sopra(numeri[0]).with_name(prova.sopra(numeri[0]).name + ".nuovo"),
             prova.dove / elenco.ELENCO / "fotografia-00000099.ofs.nuovo",
             prova.dove / "chiave.json.nuovo"]
    for resto in resti:
        resto.write_bytes(b"mezzo")
    prova.chiavetta.aggiorna(prova.radice)
    assert not any(resto.exists() for resto in resti)
    _tutto_a_posto(prova)


def test_il_programmino_si_copia_e_si_ricopia_solo_se_cambia(tmp_path, chiave):
    exe = tmp_path / "Recupera.exe"
    exe.write_bytes(b"MZ finto" * 5000)
    scritti: list[str] = []

    def scrivi(percorso):
        scritti.append(Path(percorso).name)
        return VERO_OPEN(percorso, "w+b")

    prova = Prova(tmp_path, chiave, programmino=exe, scrivi=scrivi)
    prova.foto(1)
    prova.pronta()
    assert (prova.radice / PROGRAMMINO).read_bytes() == exe.read_bytes()
    assert scritti.count(PROGRAMMINO + ".nuovo") == 1
    prova.chiavetta.aggiorna(prova.radice)
    assert scritti.count(PROGRAMMINO + ".nuovo") == 1
    exe.write_bytes(b"MZ nuovo" * 7000)
    prova.chiavetta.aggiorna(prova.radice)
    assert scritti.count(PROGRAMMINO + ".nuovo") == 2
    assert (prova.radice / PROGRAMMINO).read_bytes() == exe.read_bytes()


def test_senza_programmino_si_dice_ma_si_copia_il_resto(tmp_path, chiave):
    prova = Prova(tmp_path, chiave, programmino=tmp_path / "manca.exe")
    prova.foto(2)
    resoconto = prova.pronta()
    assert "programmino_mancante" in resoconto.problemi
    _tutto_a_posto(prova)


def test_la_spiegazione_si_aggiorna_se_cambia(tmp_path, chiave):
    prova = Prova(tmp_path, chiave)
    prova.foto(1)
    prova.pronta()
    (prova.radice / LEGGIMI).write_text("cambiata a mano", "utf-8")
    prova.chiavetta.aggiorna(prova.radice)
    assert (prova.radice / LEGGIMI).read_text("utf-8") == TESTO


@pytest.mark.parametrize("quale", ["principale", "riserva", "tutte", "rovinate"])
def test_la_chiave_sulla_chiavetta_si_rimette(tmp_path, chiave, quale):
    prova = Prova(tmp_path, chiave)
    prova.foto(1)
    prova.pronta()
    nomi = {"principale": [chiavi.FILE], "riserva": [chiavi.RISERVA],
            "tutte": [chiavi.FILE, chiavi.RISERVA],
            "rovinate": [chiavi.FILE, chiavi.RISERVA]}[quale]
    for nome in nomi:
        if quale == "rovinate":
            (prova.dove / nome).write_bytes(b"{rotto")
        else:
            (prova.dove / nome).unlink()
    prova.chiavetta.aggiorna(prova.radice)
    _tutto_a_posto(prova)


@pytest.mark.parametrize("quale", ["tutte", "rovinate"])
def test_la_chiave_del_pc_si_rimette_dalla_chiavetta(tmp_path, chiave, quale):
    prova = Prova(tmp_path, chiave)
    prova.foto(1)
    prova.pronta()
    for nome in (chiavi.FILE, chiavi.RISERVA):
        if quale == "rovinate":
            (prova.banco.archivio / nome).write_bytes(b"[]")
        else:
            (prova.banco.archivio / nome).unlink()
    resoconto = prova.chiavetta.aggiorna(prova.radice)
    assert resoconto.chiave_rimessa_sul_pc
    assert chiavi.apri(prova.banco.archivio, PASSWORD).nome == chiave.nome


def test_una_chiave_del_pc_di_un_altro_archivio_non_si_tocca(tmp_path, chiave):
    prova = Prova(tmp_path, chiave)
    prova.foto(1)
    prova.pronta()
    altra = chiavi.Chiave(bytes(range(1, 33)))
    estranea = chiavi._in_byte(chiavi._documento(altra, [_PORTA["porta"]]))
    for nome in (chiavi.FILE, chiavi.RISERVA):
        (prova.banco.archivio / nome).write_bytes(estranea)
    resoconto = prova.chiavetta.aggiorna(prova.radice)
    assert not resoconto.chiave_rimessa_sul_pc
    assert (prova.banco.archivio / chiavi.FILE).read_bytes() == estranea


def test_la_password_cambiata_arriva_sulla_chiavetta(tmp_path, chiave):
    prova = Prova(tmp_path, chiave)
    prova.foto(1)
    prova.pronta()
    nuova = "un'altra password finta"
    chiavi.cambia_password(prova.banco.archivio, chiave, nuova)
    prova.chiavetta.aggiorna(prova.radice)
    assert chiavi.apri(prova.dove, nuova).nome == chiave.nome
    with pytest.raises(PasswordSbagliata):
        chiavi.apri(prova.dove, PASSWORD)


def _chiave_storta(percorso: Path) -> bytes:
    documento = json.loads(_byte(percorso).decode("utf-8"))
    porta = documento["porte"][0]
    porta["numero"] = "00" * 8 if porta["numero"] != "00" * 8 else "11" * 8
    return chiavi._in_byte(documento)


def _chiavi_in(cartella: Path) -> list[bytes]:
    return [_byte(cartella / nome) for nome in (chiavi.FILE, chiavi.RISERVA)]


@pytest.mark.parametrize("storta", [chiavi.FILE, chiavi.RISERVA])
def test_se_le_chiavi_del_pc_non_sono_uguali_quella_della_chiavetta_non_si_tocca(
        tmp_path, chiave, storta):
    prova = Prova(tmp_path, chiave)
    prova.foto(1)
    prova.pronta()
    prima = _chiavi_in(prova.dove)
    percorso = prova.banco.archivio / storta
    percorso.write_bytes(_chiave_storta(percorso))
    resoconto = prova.chiavetta.aggiorna(prova.radice)
    assert "chiave_diversa_sul_pc" in resoconto.problemi
    assert _chiavi_in(prova.dove) == prima
    assert chiavi.apri(prova.dove, PASSWORD).nome == chiave.nome
    assert not prova.chiavetta.chiave_del_pc_a_posto()
    assert not prova.chiavetta.chiave_uguale(prova.radice)


def test_se_sul_pc_c_e_una_chiave_sola_e_diversa_la_chiavetta_tiene_la_sua(tmp_path,
                                                                          chiave):
    prova = Prova(tmp_path, chiave)
    prova.foto(1)
    prova.pronta()
    prima = _chiavi_in(prova.dove)
    archivio = prova.banco.archivio
    (archivio / chiavi.RISERVA).write_bytes(_chiave_storta(archivio / chiavi.RISERVA))
    os.unlink(archivio / chiavi.FILE)
    resoconto = prova.chiavetta.aggiorna(prova.radice)
    assert "chiave_diversa_sul_pc" in resoconto.problemi
    assert _chiavi_in(prova.dove) == prima
    assert not (archivio / chiavi.FILE).exists()


def test_se_sul_pc_manca_una_chiave_quella_uguale_della_chiavetta_resta(tmp_path, chiave):
    prova = Prova(tmp_path, chiave)
    prova.foto(1)
    prova.pronta()
    os.unlink(prova.dove / chiavi.FILE)
    os.unlink(prova.banco.archivio / chiavi.RISERVA)
    resoconto = prova.chiavetta.aggiorna(prova.radice)
    assert "chiave_diversa_sul_pc" in resoconto.problemi
    buona = _byte(prova.banco.archivio / chiavi.FILE)
    assert _chiavi_in(prova.dove) == [buona, buona]


def test_se_le_chiavi_del_pc_non_sono_uguali_e_la_chiavetta_non_ne_ha_si_copia(tmp_path,
                                                                              chiave):
    prova = Prova(tmp_path, chiave)
    prova.foto(1)
    prova.pronta()
    for nome in (chiavi.FILE, chiavi.RISERVA):
        os.unlink(prova.dove / nome)
    archivio = prova.banco.archivio
    (archivio / chiavi.RISERVA).write_bytes(_chiave_storta(archivio / chiavi.RISERVA))
    resoconto = prova.chiavetta.aggiorna(prova.radice)
    assert "chiave_diversa_sul_pc" in resoconto.problemi
    buona = _byte(archivio / chiavi.FILE)
    assert _chiavi_in(prova.dove) == [buona, buona]
    assert chiavi.apri(prova.dove, PASSWORD).nome == chiave.nome


def test_con_le_chiavi_del_pc_uguali_la_chiavetta_storta_si_rimette(tmp_path, chiave):
    prova = Prova(tmp_path, chiave)
    prova.foto(1)
    prova.pronta()
    (prova.dove / chiavi.FILE).write_bytes(_chiave_storta(prova.dove / chiavi.FILE))
    resoconto = prova.chiavetta.aggiorna(prova.radice)
    assert "chiave_diversa_sul_pc" not in resoconto.problemi
    assert _chiavi_in(prova.dove) == _chiavi_in(prova.banco.archivio)
    assert prova.chiavetta.chiave_uguale(prova.radice)


@pytest.mark.parametrize("storta", [chiavi.FILE, chiavi.RISERVA])
def test_la_chiave_del_pc_si_rimette_copia_per_copia(tmp_path, chiave, storta):
    prova = Prova(tmp_path, chiave)
    prova.foto(1)
    prova.pronta()
    (prova.dove / storta).write_bytes(_chiave_storta(prova.dove / storta))
    sopra = _chiavi_in(prova.dove)
    archivio = prova.banco.archivio
    for nome in (chiavi.FILE, chiavi.RISERVA):
        os.unlink(archivio / nome)
    resoconto = prova.chiavetta.aggiorna(prova.radice)
    assert resoconto.chiave_rimessa_sul_pc
    assert _chiavi_in(archivio) == sopra
    assert chiavi.apri(archivio, PASSWORD).nome == chiave.nome
    assert _chiavi_in(archivio)[0] == _chiavi_in(archivio)[1]
    resoconto = prova.chiavetta.aggiorna(prova.radice)
    assert resoconto.problemi == []
    assert prova.chiavetta.chiave_uguale(prova.radice)
    assert chiavi.apri(prova.dove, PASSWORD).nome == chiave.nome


def test_se_la_chiavetta_ha_una_chiave_sola_la_rimette_in_tutte_e_due(tmp_path, chiave):
    prova = Prova(tmp_path, chiave)
    prova.foto(1)
    prova.pronta()
    buona = _byte(prova.dove / chiavi.RISERVA)
    os.unlink(prova.dove / chiavi.FILE)
    for nome in (chiavi.FILE, chiavi.RISERVA):
        os.unlink(prova.banco.archivio / nome)
    assert prova.chiavetta.aggiorna(prova.radice).chiave_rimessa_sul_pc
    assert _chiavi_in(prova.banco.archivio) == [buona, buona]


@pytest.mark.parametrize("sistema", ["FAT32", "fat32", "FAT", "FAT16", "FAT12"])
def test_la_fat32_non_si_usa_e_si_spiega_come_formattare(tmp_path, chiave, sistema):
    prova = Prova(tmp_path, chiave, sistema=lambda radice: sistema)
    prova.foto(1)
    esame = prova.chiavetta.esamina(prova.radice)
    assert esame.problema == "fat32"
    assert "exFAT" in esame.messaggio and "non formatta mai" in esame.messaggio
    with pytest.raises(ErroreOfficina) as errore:
        prova.chiavetta.prepara(prova.radice)
    assert errore.value.codice == "fat32"
    assert _niente_scritto(prova.radice) == []


@pytest.mark.parametrize("sistema", ["exFAT", "NTFS", None, "ReFS"])
def test_gli_altri_sistemi_vanno_bene(tmp_path, chiave, sistema):
    prova = Prova(tmp_path, chiave, sistema=lambda radice: sistema)
    prova.foto(1)
    assert prova.chiavetta.esamina(prova.radice).va_bene


def test_se_lo_spazio_non_basta_non_parte_e_dice_quanto_serve(tmp_path, chiave):
    libero = [LIBERO]
    prova = Prova(tmp_path, chiave, spazio=lambda radice: libero[0])
    prova.foto(3)
    prova.chiavetta.prepara(prova.radice)
    serve = prova.chiavetta.esamina(prova.radice).serve
    libero[0] = serve - 1
    esame = prova.chiavetta.esamina(prova.radice)
    assert esame.problema == "poco_spazio"
    assert "GB" in esame.messaggio and "mancano" in esame.messaggio
    with pytest.raises(ErroreOfficina) as errore:
        prova.chiavetta.aggiorna(prova.radice)
    assert errore.value.codice == "poco_spazio"
    assert not (prova.dove / elenco.CONTENUTI).exists()
    libero[0] = serve
    prova.chiavetta.aggiorna(prova.radice)
    _tutto_a_posto(prova)


def test_lo_spazio_che_serve_cala_con_quello_che_c_e_gia(tmp_path, chiave):
    prova = Prova(tmp_path, chiave)
    prova.foto(4)
    prova.banco.elenco.fissa()

    def altro():
        fotografia = prova.banco.elenco.fotografia_attuale()
        return (2 * fotografia.stat().st_size + 64 * 1024
                + len(TESTO.encode("utf-8")) + chiavetta.MARGINE)

    prima = prova.chiavetta.esamina(prova.radice)
    altro_prima = altro()
    prova.pronta()
    dopo = prova.chiavetta.esamina(prova.radice)
    pesi = sum(peso for _, peso in prova.banco.elenco.pesi())
    assert pesi > 0
    assert prima.serve - altro_prima >= pesi
    assert dopo.serve == altro()
    assert dopo.totale >= pesi


def test_sopra_i_256_gb_consiglia_un_disco(tmp_path, chiave, monkeypatch):
    prova = Prova(tmp_path, chiave)
    prova.foto(2)
    totale = prova.chiavetta.esamina(prova.radice).totale
    monkeypatch.setattr(chiavetta, "TROPPO_PER_UNA_CHIAVETTA", totale)
    assert not prova.chiavetta.esamina(prova.radice).consiglia_disco
    monkeypatch.setattr(chiavetta, "TROPPO_PER_UNA_CHIAVETTA", totale - 1)
    esame = prova.chiavetta.esamina(prova.radice)
    assert esame.consiglia_disco and esame.va_bene


def test_lo_stesso_disco_dell_archivio_non_va(tmp_path, chiave):
    prova = Prova(tmp_path, chiave, stesso_disco=lambda uno, altro: True)
    prova.foto(1)
    assert prova.chiavetta.esamina(prova.radice).problema == "stesso_disco"
    with pytest.raises(ErroreOfficina):
        prova.chiavetta.prepara(prova.radice)
    assert _niente_scritto(prova.radice) == []


def test_il_vero_controllo_dello_stesso_disco(tmp_path, chiave):
    prova = Prova(tmp_path, chiave, stesso_disco=None)
    assert prova.chiavetta.esamina(prova.radice).problema == "stesso_disco"


def test_dentro_l_archivio_non_va(tmp_path, chiave):
    prova = Prova(tmp_path, chiave)
    dentro = prova.banco.archivio / "qui"
    dentro.mkdir()
    assert prova.chiavetta.esamina(dentro).problema == "dentro_l_archivio"
    assert prova.chiavetta.esamina(prova.banco.archivio).problema == "dentro_l_archivio"


def test_dentro_gli_originali_non_va(tmp_path, chiave):
    prova = Prova(tmp_path, chiave)
    prova.foto(1)
    assert prova.chiavetta.esamina(prova.banco.sorgente).problema == "dentro_gli_originali"
    sotto = prova.banco.sorgente / "s1"
    assert prova.chiavetta.esamina(sotto).problema == "dentro_gli_originali"


def test_una_cartella_tolta_non_conta_piu(tmp_path, chiave):
    prova = Prova(tmp_path, chiave)
    prova.foto(1)
    prova.banco.elenco.registra([elenco.fatto_radice(
        "r1", str(prova.banco.sorgente), tolta=True, quando=2000.0)])
    assert prova.chiavetta.esamina(prova.banco.sorgente).problema is None


def test_una_chiavetta_che_non_c_e(tmp_path, chiave):
    prova = Prova(tmp_path, chiave)
    esame = prova.chiavetta.esamina(tmp_path / "nessuna")
    assert esame.problema == "non_trovata"


def test_lo_spazio_che_non_si_legge(tmp_path, chiave):
    def spazio(radice):
        raise OSError(errno.EIO, "rotta")

    prova = Prova(tmp_path, chiave, spazio=spazio)
    assert prova.chiavetta.esamina(prova.radice).problema == "non_trovata"


def test_la_chiavetta_di_un_altro_archivio_non_si_tocca(tmp_path, chiave):
    prova = Prova(tmp_path, chiave)
    prova.foto(1)
    altra = chiavi.Chiave(bytes(range(5, 37)))
    _scrivi_segno(prova.radice, _segno_finto(altra))
    (prova.dove / "foto.ofs").write_bytes(b"altrui")
    prima = _niente_scritto(prova.radice)
    assert prova.chiavetta.chi_e(prova.radice) == "diversa"
    for azione in (prova.chiavetta.prepara, prova.chiavetta.aggiorna):
        with pytest.raises(ErroreOfficina) as errore:
            azione(prova.radice)
        assert errore.value.codice == "chiavetta_diversa"
    assert _niente_scritto(prova.radice) == prima
    assert (prova.dove / "foto.ofs").read_bytes() == b"altrui"


@pytest.mark.parametrize("cambio", [
    {"chiavetta": "cd" * 16}, {"creata": 5.0}, {"archivio": "00" * 16},
    {"firma": "00" * 32}])
def test_un_segno_ritoccato_non_e_nostro(tmp_path, chiave, cambio):
    prova = Prova(tmp_path, chiave)
    segno = _segno_finto(chiave)
    segno.update(cambio)
    _scrivi_segno(prova.radice, segno)
    assert prova.chiavetta.chi_e(prova.radice) == "diversa"


def test_un_segno_di_una_versione_piu_nuova(tmp_path, chiave):
    prova = Prova(tmp_path, chiave)
    _scrivi_segno(prova.radice, _segno_finto(chiave, versione=chiavetta.VERSIONE + 1))
    assert prova.chiavetta.chi_e(prova.radice) == "piu_nuova"
    with pytest.raises(ErroreOfficina) as errore:
        prova.chiavetta.prepara(prova.radice)
    assert errore.value.codice == "versione_piu_nuova"


@pytest.mark.parametrize("testo", [
    b"", b"{", b"[]", b"null", b'{"tipo": "altro"}', b"\xff\xfe",
    json.dumps({"tipo": chiavetta.TIPO}).encode(),
    b" " * (chiavetta.SEGNO_MASSIMO + 10)])
def test_un_segno_rovinato_non_si_riconosce(tmp_path, chiave, testo):
    prova = Prova(tmp_path, chiave)
    (prova.dove).mkdir()
    (prova.dove / SEGNO).write_bytes(testo)
    assert leggi_segno(prova.radice) is None
    assert prova.chiavetta.chi_e(prova.radice) == "rovinata"
    assert prova.chiavetta.esamina(prova.radice).problema == "cartella_occupata"


@pytest.mark.parametrize("campo,valore", [
    ("versione", "1"), ("versione", True), ("archivio", "AB" * 16),
    ("chiavetta", "ab" * 15), ("chiavetta", 7), ("firma", "zz" * 32),
    ("creata", "ieri"), ("creata", -1), ("creata", float("nan")), ("creata", True)])
def test_un_segno_con_campi_strani(tmp_path, chiave, campo, valore):
    prova = Prova(tmp_path, chiave)
    segno = _segno_finto(chiave)
    segno[campo] = valore
    _scrivi_segno(prova.radice, segno)
    assert leggi_segno(prova.radice) is None


def test_un_segno_rovinato_sulla_nostra_chiavetta_si_rifa(tmp_path, chiave):
    prova = Prova(tmp_path, chiave)
    prova.foto(2)
    prova.pronta()
    (prova.dove / SEGNO).write_bytes(b"{rotto")
    esame = prova.chiavetta.esamina(prova.radice)
    assert esame.chi == "senza_segno" and esame.va_bene
    prova.chiavetta.prepara(prova.radice, al_posto=True)
    prova.chiavetta.aggiorna(prova.radice)
    _tutto_a_posto(prova)


def test_una_cartella_con_lo_stesso_nome_non_si_tocca(tmp_path, chiave):
    prova = Prova(tmp_path, chiave)
    prova.dove.mkdir()
    (prova.dove / "mie.txt").write_text("mie", "utf-8")
    assert prova.chiavetta.chi_e(prova.radice) == "occupata"
    with pytest.raises(ErroreOfficina) as errore:
        prova.chiavetta.prepara(prova.radice)
    assert errore.value.codice == "cartella_occupata"
    assert _niente_scritto(prova.radice) == [CARTELLA, f"{CARTELLA}/mie.txt"]


def test_una_cartella_vuota_con_lo_stesso_nome_va_bene(tmp_path, chiave):
    prova = Prova(tmp_path, chiave)
    prova.dove.mkdir()
    prova.foto(1)
    prova.pronta()
    _tutto_a_posto(prova)


def test_una_seconda_chiavetta_chiede_conferma(tmp_path, chiave):
    prova = Prova(tmp_path, chiave)
    prova.foto(2)
    prova.pronta()
    seconda = tmp_path / "F"
    seconda.mkdir()
    with pytest.raises(ErroreOfficina) as errore:
        prova.chiavetta.prepara(seconda)
    assert errore.value.codice == "c_e_gia_una_chiavetta"
    assert _niente_scritto(seconda) == []
    prova.chiavetta.prepara(seconda, al_posto=True)
    assert prova.chiavetta.chi_e(seconda) == "nostra"
    assert prova.chiavetta.chi_e(prova.radice) == "vecchia"
    with pytest.raises(ErroreOfficina) as errore:
        prova.chiavetta.aggiorna(prova.radice)
    assert errore.value.codice == "chiavetta_vecchia"
    assert not prova.chiavetta.completa()
    resoconto = prova.chiavetta.aggiorna(seconda)
    assert resoconto.copiati == len(prova.tutti())


def test_una_vecchia_chiavetta_si_puo_rifare_e_rilegge_tutto(tmp_path, chiave):
    prova = Prova(tmp_path, chiave)
    prova.foto(2)
    prova.pronta()
    seconda = tmp_path / "F"
    seconda.mkdir()
    prova.chiavetta.prepara(seconda, al_posto=True)
    prova.chiavetta.aggiorna(seconda)
    prova.chiavetta.prepara(prova.radice, al_posto=True)
    resoconto = prova.chiavetta.aggiorna(prova.radice)
    assert resoconto.copiati == 0
    assert resoconto.riletti == len(prova.tutti())
    _tutto_a_posto(prova)


def test_persa_si_rifa_da_zero_senza_conferma(tmp_path, chiave):
    prova = Prova(tmp_path, chiave)
    prova.foto(2)
    prova.pronta()
    prova.chiavetta.segna_persa()
    assert prova.chiavetta.persa and not prova.chiavetta.completa()
    assert prova.chiavetta.promemoria() == "persa"
    nuova = tmp_path / "G"
    nuova.mkdir()
    prova.chiavetta.prepara(nuova)
    assert not prova.chiavetta.persa
    assert not prova.chiavetta.completa()
    assert prova.chiavetta.aggiorna(nuova).copiati == len(prova.tutti())
    assert prova.chiavetta.completa()


def test_ritrovata_dopo_persa_torna_buona(tmp_path, chiave):
    prova = Prova(tmp_path, chiave)
    prova.foto(2)
    prova.pronta()
    prova.chiavetta.segna_persa()
    prova.chiavetta.aggiorna(prova.radice)
    assert not prova.chiavetta.persa and prova.chiavetta.completa()


def test_segnare_persa_senza_chiavetta_non_fa_niente(tmp_path, chiave):
    prova = Prova(tmp_path, chiave)
    prova.chiavetta.segna_persa()
    assert not prova.chiavetta.persa
    assert not (prova.banco.archivio / STATO).exists()


@pytest.mark.parametrize("guasto", ["via", "rovinato", "estraneo"])
def test_se_si_perde_lo_stato_la_chiavetta_si_riprende(tmp_path, chiave, guasto):
    prova = Prova(tmp_path, chiave)
    prova.foto(3)
    prova.pronta()
    for nome in (STATO, RISERVA):
        if guasto == "via":
            (prova.banco.archivio / nome).unlink()
        elif guasto == "rovinato":
            (prova.banco.archivio / nome).write_bytes(os.urandom(200))
        else:
            altra = chiavi.Chiave(bytes(range(9, 41)))
            (prova.banco.archivio / nome).write_bytes(
                chiavetta._cifra_stato(altra, chiavetta._Stato(chiavetta="ef" * 16)))
    nuova = prova.nuova()
    assert ("stato_rovinato" in nuova.problemi) == (guasto != "via")
    assert not nuova.preparata
    assert nuova.chi_e(prova.radice) == "da_adottare"
    prova.chiavetta = nuova
    resoconto = nuova.aggiorna(prova.radice)
    assert resoconto.copiati == 0 and resoconto.riletti == len(prova.tutti())
    _tutto_a_posto(prova)


def test_lo_stato_si_legge_dalla_copia_piu_nuova(tmp_path, chiave):
    prova = Prova(tmp_path, chiave)
    prova.foto(2)
    prova.pronta()
    principale = (prova.banco.archivio / STATO).read_bytes()
    prova.foto(1, seme=7)
    prova.chiavetta.aggiorna(prova.radice)
    (prova.banco.archivio / STATO).write_bytes(principale)
    nuova = prova.nuova()
    assert set(nuova._stato.sopra) == set(prova.tutti())
    (prova.banco.archivio / RISERVA).write_bytes(b"rotto")
    nuova = prova.nuova()
    assert set(nuova._stato.sopra) < set(prova.tutti())
    assert nuova.mancanti()[0] > 0


def test_lo_stato_ritoccato_non_si_usa(tmp_path, chiave):
    prova = Prova(tmp_path, chiave)
    prova.chiavetta.prepara(prova.radice)
    for nome in (STATO, RISERVA):
        dati = bytearray((prova.banco.archivio / nome).read_bytes())
        dati[-3] ^= 1
        (prova.banco.archivio / nome).write_bytes(bytes(dati))
    assert not prova.nuova().preparata


@pytest.mark.parametrize("dati", [
    None, [], {"numero": 1}, {"numero": -1, "sopra": {}, "persa": False},
    {"numero": 1, "sopra": [], "persa": False},
    {"numero": 1, "sopra": {}, "persa": 0},
    {"numero": "1", "sopra": {}, "persa": False},
    {"numero": 1, "sopra": {}, "persa": False, "chiavetta": "XY" * 16}])
def test_uno_stato_strano_non_si_usa(dati):
    assert chiavetta._Stato.da(dati) is None


def test_uno_stato_tiene_solo_le_righe_buone():
    stato = chiavetta._Stato.da({
        "numero": 3, "persa": False, "chiavetta": None, "finito": "ieri",
        "sopra": {"ab" * 16: 5.0, "AB" * 16: 5.0, "zz": 1.0, "cd" * 16: "x",
                  "ef" * 16: float("inf")}})
    assert stato.sopra == {"ab" * 16: 5.0} and stato.finito is None


def test_i_promemoria(tmp_path, chiave, monkeypatch):
    prova = Prova(tmp_path, chiave)
    prova.foto(2)
    assert prova.chiavetta.promemoria() == "mai_fatta"
    prova.pronta()
    assert prova.chiavetta.promemoria() is None
    prova.orologio.ora += MESE - 1
    assert prova.chiavetta.promemoria() is None
    prova.orologio.ora += 1
    assert prova.chiavetta.promemoria() == "mese"
    prova.chiavetta.aggiorna(prova.radice)
    assert prova.chiavetta.promemoria() is None
    prova.chiavetta.segna_persa()
    assert prova.chiavetta.promemoria() == "persa"


@pytest.mark.parametrize("quanti,atteso", [(2, None), (3, "copia_grossa")])
def test_il_promemoria_dopo_tanti_file(tmp_path, chiave, monkeypatch, quanti, atteso):
    monkeypatch.setattr(chiavetta, "FILE_GROSSI", 2)
    prova = Prova(tmp_path, chiave)
    prova.foto(1)
    prova.pronta()
    prima = len(prova.tutti())
    seme = 10
    while len(prova.tutti()) - prima < quanti:
        prova.foto(1, seme=seme)
        seme += 1
    nuovi = len(prova.tutti()) - prima
    assert prova.chiavetta.mancanti()[0] == nuovi
    assert prova.chiavetta.promemoria() == ("copia_grossa" if nuovi > 2 else atteso)


def test_il_promemoria_dopo_tanti_byte(tmp_path, chiave, monkeypatch):
    prova = Prova(tmp_path, chiave)
    prova.foto(1)
    prova.pronta()
    prova.foto(1, seme=5, misure=[3 * formato.BLOCCO])
    file, byte = prova.chiavetta.mancanti()
    monkeypatch.setattr(chiavetta, "BYTE_GROSSI", byte)
    assert prova.chiavetta.promemoria() is None
    monkeypatch.setattr(chiavetta, "BYTE_GROSSI", byte - 1)
    assert prova.chiavetta.promemoria() == "copia_grossa"


def test_il_riassunto(tmp_path, chiave):
    prova = Prova(tmp_path, chiave)
    prova.foto(2)
    riassunto = prova.chiavetta.riassunto()
    assert not riassunto["preparata"] and riassunto["promemoria"] == "mai_fatta"
    assert riassunto["mancanti_file"] == len(prova.tutti())
    prova.pronta()
    riassunto = prova.chiavetta.riassunto()
    assert riassunto["preparata"] and riassunto["mancanti_file"] == 0
    assert riassunto["ultima"] == prova.orologio.ora


def test_la_copia_per_il_controllo_mensile(tmp_path, chiave):
    prova = Prova(tmp_path, chiave)
    numeri = prova.foto(2, misure=[3 * formato.BLOCCO])
    prova.pronta()
    copia = prova.chiavetta.copia_di(prova.radice)
    assert copia(numeri[0]) == prova.sopra(numeri[0])
    assert copia("00" * 16) is None
    _rovina(prova.pc(numeri[0]), range(0, prova.pc(numeri[0]).stat().st_size, 7), 0xA5)
    controllore = Controllore(prova.banco.archivio, prova.banco.elenco, chiave,
                              apri=prova.banco.apri, copie=[copia], luoghi=lambda: [],
                              adesso=prova.orologio)
    rapporto = controllore.controlla([numeri[0]])
    assert rapporto.come["copia"] == 1 and not rapporto.persi
    assert _byte(prova.pc(numeri[0])) == _byte(prova.sopra(numeri[0]))
    prova.stacca()
    assert copia(numeri[0]) is None
    prova.riattacca()
    altra = tmp_path / "F"
    altra.mkdir()
    prova.chiavetta.prepara(altra, al_posto=True)
    assert copia(numeri[0]) is None


def test_un_file_rovinato_sul_pc_si_ripara_dalla_chiavetta(tmp_path, chiave):
    prova = Prova(tmp_path, chiave)
    numeri = prova.foto(3, misure=[2 * formato.BLOCCO + 7])
    prova.pronta()
    guasto = numeri[1]
    _danneggia(prova, prova.pc(guasto), guasto, "tutto", random.Random(1))
    for posto in prova.file:
        (prova.banco.sorgente / posto).unlink()
    mensile = Controllore(prova.banco.archivio, prova.banco.elenco, chiave,
                          apri=prova.banco.apri, luoghi=lambda: [], adesso=prova.orologio)
    assert mensile.controlla([guasto]).persi == [guasto]
    assert prova.banco.elenco.contenuto(guasto)["stato"] == "rovinato"
    resoconto = prova.chiavetta.aggiorna(prova.radice)
    assert resoconto.riparati_sul_pc == [guasto] and not resoconto.guai
    assert prova.banco.elenco.contenuto(guasto)["stato"] == "riparato"
    _tutto_a_posto(prova)


@pytest.mark.parametrize("danno", ["via", "taglio"])
def test_un_file_sparito_dal_pc_torna_dalla_chiavetta(tmp_path, chiave, danno):
    prova = Prova(tmp_path, chiave)
    numeri = prova.foto(3, misure=[formato.BLOCCO + 1])
    prova.pronta()
    _danneggia(prova, prova.pc(numeri[0]), numeri[0], danno, random.Random(2))
    resoconto = prova.chiavetta.aggiorna(prova.radice)
    assert numeri[0] in resoconto.rovinati_sul_pc
    assert numeri[0] in resoconto.riparati_sul_pc
    _tutto_a_posto(prova)


def test_una_nota_sparita_dal_pc_torna_dalla_chiavetta(tmp_path, chiave):
    prova = Prova(tmp_path, chiave)
    prova.foto(2)
    prova.pronta()
    nota = prova.banco.elenco.note()[0]
    prova.pc(nota).unlink()
    resoconto = prova.chiavetta.aggiorna(prova.radice)
    assert resoconto.note_rimesse == 1
    _tutto_a_posto(prova)


def test_un_file_rovinato_sul_pc_prima_della_copia_arriva_pulito(tmp_path, chiave):
    prova = Prova(tmp_path, chiave)
    numeri = prova.foto(3, misure=[3 * formato.BLOCCO])
    _danneggia(prova, prova.pc(numeri[2]), numeri[2], "pezzo", random.Random(3))
    resoconto = prova.pronta()
    assert numeri[2] in resoconto.riparati_sul_pc
    assert _intatto(prova, prova.sopra(numeri[2]), numeri[2])
    _tutto_a_posto(prova)


def test_un_file_perso_sul_pc_e_non_sulla_chiavetta_e_un_allarme(tmp_path, chiave):
    prova = Prova(tmp_path, chiave)
    numeri = prova.foto(2, misure=[2 * formato.BLOCCO])
    _danneggia(prova, prova.pc(numeri[0]), numeri[0], "tutto", random.Random(1))
    for posto in prova.file:
        (prova.banco.sorgente / posto).unlink()
    resoconto = prova.pronta()
    assert numeri[0] in resoconto.rovinati_sul_pc
    assert resoconto.persi_sul_pc == [numeri[0]]
    assert resoconto.guai == [numeri[0]]
    assert resoconto.frase().startswith("Puoi staccarla, ma attenzione")
    assert not prova.sopra(numeri[0]).exists()


@pytest.mark.parametrize("danno", ["pezzo", "testa", "meta", "tutto", "via", "taglio"])
def test_un_file_rovinato_sulla_chiavetta_si_ricopia(tmp_path, chiave, danno):
    prova = Prova(tmp_path, chiave)
    numeri = prova.foto(3, misure=[2 * formato.BLOCCO + 7])
    prova.pronta()
    _danneggia(prova, prova.sopra(numeri[1]), numeri[1], danno, random.Random(4))
    prova.orologio.ora += MESE
    resoconto = prova.chiavetta.aggiorna(prova.radice)
    assert not resoconto.guai
    if danno in ("via", "taglio"):
        assert resoconto.copiati == 1
    else:
        assert resoconto.ricopiati == [numeri[1]]
    _tutto_a_posto(prova)


def test_un_file_tagliato_sulla_chiavetta_si_ricopia_subito(tmp_path, chiave):
    prova = Prova(tmp_path, chiave)
    numeri = prova.foto(2, misure=[formato.BLOCCO + 1])
    prova.pronta()
    _danneggia(prova, prova.sopra(numeri[0]), numeri[0], "taglio", random.Random(5))
    resoconto = prova.chiavetta.aggiorna(prova.radice)
    assert resoconto.copiati == 1 and resoconto.riletti == 0
    _tutto_a_posto(prova)


@pytest.mark.parametrize("danno", ["pezzo", "testa", "meta"])
def test_rovinato_su_tutti_e_due_ma_riparabile_sulla_chiavetta(tmp_path, chiave, danno):
    prova = Prova(tmp_path, chiave)
    numeri = prova.foto(2, misure=[3 * formato.BLOCCO])
    prova.pronta()
    _danneggia(prova, prova.sopra(numeri[0]), numeri[0], danno, random.Random(6))
    _danneggia(prova, prova.pc(numeri[0]), numeri[0], "tutto", random.Random(6))
    prova.orologio.ora += MESE
    resoconto = prova.chiavetta.aggiorna(prova.radice)
    assert resoconto.riparati_sulla_chiavetta == [numeri[0]]
    assert _intatto(prova, prova.sopra(numeri[0]), numeri[0])


def test_rovinato_su_tutti_e_due_e_un_allarme(tmp_path, chiave):
    prova = Prova(tmp_path, chiave)
    numeri = prova.foto(2, misure=[3 * formato.BLOCCO])
    prova.pronta()
    for percorso in (prova.sopra(numeri[0]), prova.pc(numeri[0])):
        _danneggia(prova, percorso, numeri[0], "tutto", random.Random(7))
    prova.orologio.ora += MESE
    resoconto = prova.chiavetta.aggiorna(prova.radice)
    assert resoconto.rovinati_sulla_chiavetta == [numeri[0]]
    assert numeri[0] in resoconto.guai
    assert prova.sopra(numeri[0]).exists()


def test_i_file_sconosciuti_sulla_chiavetta_restano(tmp_path, chiave):
    prova = Prova(tmp_path, chiave)
    numeri = prova.foto(2)
    prova.pronta()
    estraneo = elenco.percorso_contenuto(prova.dove, "12" * 16)
    estraneo.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(prova.sopra(numeri[0]), estraneo)
    prova.orologio.ora += MESE
    resoconto = prova.chiavetta.aggiorna(prova.radice)
    assert estraneo.exists()
    assert "sconosciuti_rovinati" in resoconto.problemi


def test_l_elenco_della_chiavetta_si_ricostruisce_se_rovinato(tmp_path, chiave):
    prova = Prova(tmp_path, chiave)
    prova.foto(4)
    prova.pronta()
    for fotografia in (prova.dove / elenco.ELENCO).iterdir():
        fotografia.write_bytes(b"rovinata")
    assert _foto_sulla_chiavetta(prova) == prova.file


def test_un_elenco_sulla_chiavetta_senza_fotografia(tmp_path, chiave):
    prova = Prova(tmp_path, chiave)
    prova.foto(3)
    prova.pronta()
    shutil.rmtree(prova.dove / elenco.ELENCO)
    assert _foto_sulla_chiavetta(prova) == prova.file


class Stacca:

    def __init__(self, prova: Prova, quando: int):
        self.prova = prova
        self.quando = quando
        self.volte = 0
        self.staccata = False

    def __call__(self, nome, senza_cache, volta, lettore):
        self.volte += 1
        if self.volte == self.quando and not self.staccata:
            self.staccata = True
            self.prova.stacca()
        return lettore


def _aperture(tmp_path, chiave) -> int:
    (tmp_path / "conta").mkdir()
    prova = Prova(tmp_path / "conta", chiave)
    prova.foto(3, seme=11)
    prova.chiavetta.prepara(prova.radice)
    prova.banco.apri.aperti.clear()
    prova.chiavetta.aggiorna(prova.radice)
    return len(prova.banco.apri.aperti)


@pytest.mark.parametrize("quando", range(1, 21))
def test_staccata_a_meta_non_rovina_niente_e_riprende(tmp_path, chiave, quando):
    prova = Prova(tmp_path, chiave)
    prova.foto(3, seme=11)
    prova.chiavetta.prepara(prova.radice)
    stacca = Stacca(prova, quando)
    prova.banco.apri.regole.append(stacca)
    try:
        prova.chiavetta.aggiorna(prova.radice)
    except ChiavettaStaccata:
        assert stacca.staccata
    else:
        assert not stacca.staccata
    prova.banco.apri.regole.clear()
    if stacca.staccata:
        assert not prova.radice.exists()
        prova.riattacca()
    prova.chiavetta = prova.nuova()
    prova.chiavetta.aggiorna(prova.radice)
    _tutto_a_posto(prova)
    assert _foto_sulla_chiavetta(prova) == prova.file


def test_le_cartelle_si_creano_solo_dentro_la_chiavetta(tmp_path):
    base = tmp_path / "E"
    with pytest.raises(FileNotFoundError):
        chiavetta._crea_sotto(base, base / CARTELLA / "contenuti" / "ab")
    assert not base.exists()
    base.mkdir()
    chiavetta._crea_sotto(base, base / CARTELLA / "contenuti" / "ab")
    assert (base / CARTELLA / "contenuti" / "ab").is_dir()
    chiavetta._crea_sotto(base, base / CARTELLA / "contenuti" / "ab")
    chiavetta._crea_sotto(base, base)
    with pytest.raises(FileNotFoundError):
        chiavetta._crea_sotto(base, tmp_path / "altrove" / "x")
    assert not (tmp_path / "altrove").exists()
    (base / CARTELLA / "file").write_bytes(b"x")
    with pytest.raises(OSError):
        chiavetta._crea_sotto(base, base / CARTELLA / "file" / "sotto")


def test_le_prove_dello_stacco_coprono_tutto(tmp_path, chiave):
    assert 10 < _aperture(tmp_path, chiave) < 21


class Ferma:

    def __init__(self, quando: int):
        self.quando = quando
        self.volte = 0

    def __call__(self):
        self.volte += 1
        if self.volte == self.quando:
            raise Fermato


@pytest.mark.parametrize("quando", [1, 2, 3, 5, 8, 13, 21, 34, 55, 89, 144, 233])
def test_fermata_a_meta_riprende_da_dove_era(tmp_path, chiave, quando):
    prova = Prova(tmp_path, chiave)
    prova.foto(4, seme=12)
    ferma = Ferma(quando)
    prova.chiavetta = prova.nuova(aspetta=ferma)
    prova.chiavetta.prepara(prova.radice)
    try:
        prova.chiavetta.aggiorna(prova.radice)
    except Fermato:
        assert ferma.volte == quando
    assert prova.provvisori() == []
    prova.chiavetta = prova.nuova()
    prova.chiavetta.aggiorna(prova.radice)
    _tutto_a_posto(prova)


def test_lo_stato_si_salva_anche_se_si_ferma(tmp_path, chiave, monkeypatch):
    monkeypatch.setattr(chiavetta, "SALVA_OGNI", 0.0)
    prova = Prova(tmp_path, chiave)
    prova.foto(4, seme=13)
    prova.chiavetta.prepara(prova.radice)
    copiati = []

    def aspetta():
        copiati.append(len(prova.chiavetta._stato.sopra))
        if len(prova.chiavetta._stato.sopra) >= 2:
            raise Fermato

    prova.chiavetta._aspetta = aspetta
    with pytest.raises(Fermato):
        prova.chiavetta.aggiorna(prova.radice)
    rimasto = prova.nuova()
    assert len(rimasto._stato.sopra) >= 2
    assert rimasto._stato.finito is None


class Rotto:

    def __init__(self, file, errore: int, dopo: int = 0):
        self._file = file
        self._errore = errore
        self._dopo = dopo

    def write(self, dati):
        if self._dopo <= 0:
            raise OSError(self._errore, os.strerror(self._errore))
        self._dopo -= len(dati)
        return self._file.write(dati)

    def __getattr__(self, nome):
        return getattr(self._file, nome)

    def __enter__(self):
        return self

    def __exit__(self, *altro):
        self._file.close()


class Scrivi:

    def __init__(self, quando: int, errore: int, dopo: int = 0):
        self.quando = quando
        self.errore = errore
        self.dopo = dopo
        self.volte = 0

    def __call__(self, percorso):
        self.volte += 1
        file = VERO_OPEN(percorso, "w+b")
        if self.volte >= self.quando:
            return Rotto(file, self.errore, self.dopo)
        return file


@pytest.mark.parametrize("errore,codice", [
    (errno.ENOSPC, "chiavetta_piena"), (errno.EFBIG, "fat32"),
    (errno.EIO, "chiavetta_guasta"), (errno.EACCES, "chiavetta_guasta")])
@pytest.mark.parametrize("quando", [1, 2, 4])
def test_gli_errori_della_chiavetta_fermano_senza_rovinare(tmp_path, chiave, errore,
                                                           codice, quando):
    prova = Prova(tmp_path, chiave)
    prova.foto(4, seme=14, misure=[2 * formato.BLOCCO])
    prova.chiavetta = prova.nuova(scrivi=Scrivi(quando, errore, dopo=ALLINEA))
    prova.chiavetta.prepara(prova.radice)
    with pytest.raises(ErroreOfficina) as preso:
        prova.chiavetta.aggiorna(prova.radice)
    assert preso.value.codice == codice
    assert prova.provvisori() == []
    for numero, quando_ in prova.chiavetta._stato.sopra.items():
        assert _intatto(prova, prova.sopra(numero), numero)
    prova.chiavetta = prova.nuova()
    prova.chiavetta.aggiorna(prova.radice)
    _tutto_a_posto(prova)


class StaccaScrivendo:

    def __init__(self, prova: Prova, quando: int, errore: int):
        self.prova = prova
        self.quando = quando
        self.errore = errore
        self.volte = 0
        self.staccata = False

    def __call__(self, percorso):
        self.volte += 1
        file = VERO_OPEN(percorso, "w+b")
        if self.volte == self.quando and not self.staccata:
            self.staccata = True
            self.prova.stacca()
            return Rotto(file, self.errore, ALLINEA)
        return file


@pytest.mark.parametrize("errore", [errno.EIO, errno.ENOENT, errno.EINVAL, errno.ENOSPC])
@pytest.mark.parametrize("quando", [1, 2, 3, 5, 6])
def test_staccata_mentre_scrive(tmp_path, chiave, errore, quando):
    prova = Prova(tmp_path, chiave)
    prova.foto(4, seme=15, misure=[2 * formato.BLOCCO])
    stacca = StaccaScrivendo(prova, quando, errore)
    prova.chiavetta = prova.nuova(scrivi=stacca)
    prova.chiavetta.prepara(prova.radice)
    with pytest.raises(ChiavettaStaccata):
        prova.chiavetta.aggiorna(prova.radice)
    assert stacca.staccata
    assert not prova.radice.exists()
    assert prova.chiavetta.resoconto.frase().endswith("non staccarla.")
    prova.riattacca()
    prova.chiavetta = prova.nuova()
    resoconto = prova.chiavetta.aggiorna(prova.radice)
    assert resoconto.finito and not resoconto.guai
    _tutto_a_posto(prova)
    assert _foto_sulla_chiavetta(prova) == prova.file


class Sporca:

    def __init__(self, prova: Prova, volte: int | None):
        self.prova = prova
        self.volte = volte
        self.sporcati = 0

    def __call__(self, nome, senza_cache, volta, lettore):
        if not nome.endswith(".nuovo") or not nome.startswith(os.fspath(self.prova.dove)):
            return lettore
        if self.volte is not None and self.sporcati >= self.volte:
            return lettore
        if lettore.dimensione == 0:
            return lettore
        self.sporcati += 1
        from prove.test_sicuro_copia import Finto

        return Finto(lettore, sporca={lettore.dimensione // 2})


def test_una_scrittura_sbagliata_si_rifà(tmp_path, chiave):
    prova = Prova(tmp_path, chiave)
    prova.foto(3, misure=[formato.BLOCCO + 1])
    prova.banco.apri.regole.append(Sporca(prova, 1))
    prova.pronta()
    prova.banco.apri.regole.clear()
    _tutto_a_posto(prova)


def test_una_chiavetta_che_scrive_sempre_male_si_ferma(tmp_path, chiave):
    prova = Prova(tmp_path, chiave)
    numeri = prova.foto(3, misure=[formato.BLOCCO + 1])
    prova.banco.apri.regole.append(Sporca(prova, None))
    prova.chiavetta.prepara(prova.radice)
    with pytest.raises(ErroreOfficina) as preso:
        prova.chiavetta.aggiorna(prova.radice)
    assert preso.value.codice == "scrive_male"
    assert prova.provvisori() == []
    assert not any(prova.sopra(numero).exists() for numero in numeri)


def test_se_sparisce_l_archivio_si_ferma(tmp_path, chiave):
    prova = Prova(tmp_path, chiave)
    prova.foto(2)
    prova.chiavetta.prepara(prova.radice)
    contenuti = prova.banco.archivio / elenco.CONTENUTI
    os.rename(contenuti, tmp_path / "via")
    with pytest.raises(ErroreOfficina) as preso:
        prova.chiavetta.aggiorna(prova.radice)
    assert preso.value.codice == "archivio_sparito"


def test_non_preparata_non_si_aggiorna(tmp_path, chiave):
    prova = Prova(tmp_path, chiave)
    prova.foto(1)
    with pytest.raises(ErroreOfficina) as preso:
        prova.chiavetta.aggiorna(prova.radice)
    assert preso.value.codice == "non_preparata"
    assert _niente_scritto(prova.radice) == []


DANNI = ("pezzo", "testa", "meta", "tutto", "via", "taglio", None, None)


@pytest.mark.parametrize("seme", range(60))
def test_danni_a_caso_su_pc_e_chiavetta(tmp_path, chiave, seme):
    caso = random.Random(seme)
    prova = Prova(tmp_path, chiave)
    numeri = prova.foto(caso.randint(1, 4), seme=seme + 50,
                        misure=[caso.choice(MISURE[1:])])
    prova.pronta()
    leggibili = {}
    for numero in numeri:
        for dove, percorso in (("pc", prova.pc(numero)), ("chiavetta", prova.sopra(numero))):
            danno = caso.choice(DANNI)
            if danno is not None:
                _danneggia(prova, percorso, numero, danno, caso)
        leggibili[numero] = (_leggibile(prova, prova.pc(numero), numero)
                             or _leggibile(prova, prova.sopra(numero), numero))
    for posto in prova.file:
        (prova.banco.sorgente / posto).unlink()
    mensile = Controllore(prova.banco.archivio, prova.banco.elenco, chiave,
                          apri=prova.banco.apri, luoghi=lambda: [], adesso=prova.orologio)
    mensile.controlla()
    prova.orologio.ora += MESE
    resoconto = prova.chiavetta.aggiorna(prova.radice)
    assert prova.provvisori() == []
    for numero in numeri:
        if leggibili[numero]:
            assert _intatto(prova, prova.pc(numero), numero), numero
            assert _intatto(prova, prova.sopra(numero), numero), numero
            assert numero not in resoconto.guai
        else:
            assert numero in resoconto.guai or numero in prova.banco.elenco.allarmi()


@pytest.mark.parametrize("seme", range(40))
def test_stacchi_a_caso_finiscono_sempre_bene(tmp_path, chiave, seme):
    caso = random.Random(seme)
    prova = Prova(tmp_path, chiave)
    prova.foto(caso.randint(1, 4), seme=seme + 200)
    prova.chiavetta.prepara(prova.radice)
    for giro in range(caso.randint(1, 3)):
        stacca = Stacca(prova, caso.randint(1, 30))
        prova.banco.apri.regole[:] = [stacca]
        try:
            prova.chiavetta.aggiorna(prova.radice)
        except ChiavettaStaccata:
            pass
        prova.banco.apri.regole.clear()
        if stacca.staccata:
            prova.riattacca()
        if caso.random() < 0.5:
            prova.foto(1, seme=seme * 10 + giro + 300)
        prova.chiavetta = prova.nuova()
    prova.chiavetta.aggiorna(prova.radice)
    _tutto_a_posto(prova)
    assert _foto_sulla_chiavetta(prova) == prova.file


def _aspetta(lavoro, quanto: float = ATTESA) -> None:
    assert lavoro.aspetta_fine(quanto)


def _lavoro(prova: Prova, **opzioni) -> AggiornaChiavetta:
    opzioni.setdefault("apri", prova.banco.apri)
    opzioni.setdefault("spazio", lambda radice: LIBERO)
    opzioni.setdefault("stesso_disco", lambda uno, altro: False)
    opzioni.setdefault("sistema", lambda radice: "exFAT")
    opzioni.setdefault("adesso", prova.orologio)
    opzioni.setdefault("leggimi", TESTO)
    lavoro = AggiornaChiavetta(prova.banco.archivio, prova.banco.elenco, prova.chiave,
                               sveglio=_sveglio, **opzioni)
    prova.chiavetta = lavoro.chiavetta
    return lavoro


def test_il_lavoro_in_sottofondo(tmp_path, chiave):
    prova = Prova(tmp_path, chiave)
    prova.foto(3)
    lavoro = _lavoro(prova)
    lavoro.chiavetta.prepara(prova.radice)
    assert lavoro.avvia(prova.radice)
    _aspetta(lavoro)
    foto = lavoro.istantanea()
    assert foto["stato"] == FINITO and foto["finito"]
    assert foto["copiati"] == len(prova.tutti())
    assert foto["frase"].startswith("Puoi staccarla")
    assert not foto["allarme"]
    _tutto_a_posto(prova)


def test_il_lavoro_staccato(tmp_path, chiave):
    prova = Prova(tmp_path, chiave)
    prova.foto(3)
    lavoro = _lavoro(prova)
    lavoro.chiavetta.prepara(prova.radice)
    prova.banco.apri.regole.append(Stacca(prova, 3))
    lavoro.avvia(prova.radice)
    _aspetta(lavoro)
    assert lavoro.stato == ERRORE and lavoro.codice == "chiavetta_staccata"
    assert lavoro.istantanea()["frase"].startswith("La chiavetta non è ancora")


def test_il_lavoro_fermato(tmp_path, chiave):
    prova = Prova(tmp_path, chiave)
    prova.foto(3)
    lavoro = _lavoro(prova)
    lavoro.chiavetta.prepara(prova.radice)
    lavoro.pausa()
    lavoro.avvia(prova.radice)
    lavoro.ferma(ATTESA)
    assert lavoro.stato == FERMATO
    assert lavoro.istantanea()["copiati"] == 0


def test_il_lavoro_senza_spazio(tmp_path, chiave):
    prova = Prova(tmp_path, chiave)
    prova.foto(1)
    libero = [LIBERO]
    lavoro = _lavoro(prova, spazio=lambda radice: libero[0])
    lavoro.chiavetta.prepara(prova.radice)
    libero[0] = 10
    lavoro.avvia(prova.radice)
    _aspetta(lavoro)
    assert lavoro.codice == "poco_spazio"


class Dischi:

    def __init__(self, *dischi):
        self.dischi = list(dischi)

    def __call__(self):
        return list(self.dischi)


class Tempo:

    def __init__(self):
        self.ora = 1000.0

    def __call__(self):
        return self.ora


def _giri(guardiano: Guardiano, quanti: int = 50) -> str:
    for _ in range(quanti):
        stato = guardiano.giro()
        if stato != chiavetta.NON_STACCARLA:
            return stato
        guardiano.lavoro.aspetta_fine(ATTESA)
    return guardiano.giro()


def test_il_guardiano_senza_chiavetta(tmp_path, chiave):
    prova = Prova(tmp_path, chiave)
    guardiano = Guardiano(_lavoro(prova), dischi=Dischi())
    assert guardiano.giro() == chiavetta.DA_ATTACCARE


def test_il_guardiano_aggiorna_e_dice_puoi_staccarla(tmp_path, chiave):
    prova = Prova(tmp_path, chiave)
    prova.foto(2)
    lavoro = _lavoro(prova)
    lavoro.chiavetta.prepara(prova.radice)
    dischi = Dischi(tmp_path / "vuoto", prova.radice)
    (tmp_path / "vuoto").mkdir()
    guardiano = Guardiano(lavoro, dischi=dischi)
    assert guardiano.giro() == chiavetta.NON_STACCARLA
    assert _giri(guardiano) == chiavetta.PUOI_STACCARLA
    assert guardiano.giro() == chiavetta.PUOI_STACCARLA
    _tutto_a_posto(prova)
    dischi.dischi = []
    assert guardiano.giro() == chiavetta.DA_ATTACCARE
    foto = guardiano.istantanea()
    assert foto["stato"] == chiavetta.DA_ATTACCARE and foto["chiavetta"]["preparata"]


def test_il_guardiano_non_tocca_le_chiavette_degli_altri(tmp_path, chiave):
    prova = Prova(tmp_path, chiave)
    _scrivi_segno(prova.radice, _segno_finto(chiavi.Chiave(bytes(range(3, 35)))))
    lavoro = _lavoro(prova)
    guardiano = Guardiano(lavoro, dischi=Dischi(prova.radice))
    assert guardiano.giro() == chiavetta.DIVERSA
    assert guardiano.codice == "chiavetta_diversa"
    assert lavoro.stato == "fermo"


def test_il_guardiano_e_la_vecchia_chiavetta(tmp_path, chiave):
    prova = Prova(tmp_path, chiave)
    prova.foto(1)
    lavoro = _lavoro(prova)
    lavoro.chiavetta.prepara(prova.radice)
    nuova = tmp_path / "F"
    nuova.mkdir()
    lavoro.chiavetta.prepara(nuova, al_posto=True)
    guardiano = Guardiano(lavoro, dischi=Dischi(prova.radice))
    assert guardiano.giro() == chiavetta.DIVERSA
    assert guardiano.codice == "chiavetta_vecchia"
    guardiano._dischi = Dischi(prova.radice, nuova)
    assert _giri(guardiano) == chiavetta.PUOI_STACCARLA


def test_il_guardiano_riprende_dopo_lo_stacco(tmp_path, chiave):
    prova = Prova(tmp_path, chiave)
    prova.foto(3)
    lavoro = _lavoro(prova)
    lavoro.chiavetta.prepara(prova.radice)
    dischi = Dischi(prova.radice)
    guardiano = Guardiano(lavoro, dischi=dischi)
    prova.banco.apri.regole.append(Stacca(prova, 4))
    guardiano.giro()
    lavoro.aspetta_fine(ATTESA)
    assert guardiano.giro() == chiavetta.DA_ATTACCARE
    prova.banco.apri.regole.clear()
    prova.riattacca()
    assert _giri(guardiano) == chiavetta.PUOI_STACCARLA
    _tutto_a_posto(prova)


def test_il_guardiano_riparte_se_la_ritrova_subito(tmp_path, chiave):
    prova = Prova(tmp_path, chiave)
    prova.foto(3)
    lavoro = _lavoro(prova)
    lavoro.chiavetta.prepara(prova.radice)
    guardiano = Guardiano(lavoro, dischi=Dischi(prova.radice))
    stacca = Stacca(prova, 4)
    prova.banco.apri.regole.append(stacca)
    guardiano.giro()
    lavoro.aspetta_fine(ATTESA)
    prova.banco.apri.regole.clear()
    prova.riattacca()
    assert _giri(guardiano) == chiavetta.PUOI_STACCARLA


def test_il_guardiano_ripassa_se_restano_novita(tmp_path, chiave):
    prova = Prova(tmp_path, chiave)
    prova.foto(1)
    lavoro = _lavoro(prova)
    lavoro.chiavetta.prepara(prova.radice)
    tempo = Tempo()
    guardiano = Guardiano(lavoro, dischi=Dischi(prova.radice), adesso=tempo)
    assert _giri(guardiano) == chiavetta.PUOI_STACCARLA
    prova.foto(1, seme=8)
    tempo.ora += chiavetta.RIPASSA - 1
    assert guardiano.giro() == chiavetta.PUOI_STACCARLA
    tempo.ora += 1
    assert guardiano.giro() == chiavetta.NON_STACCARLA
    assert _giri(guardiano) == chiavetta.PUOI_STACCARLA
    _tutto_a_posto(prova)
    tempo.ora += chiavetta.RIPASSA
    assert guardiano.giro() == chiavetta.PUOI_STACCARLA


def test_il_guardiano_non_gira_in_tondo_sui_problemi(tmp_path, chiave):
    prova = Prova(tmp_path, chiave)
    prova.foto(1)
    libero = [LIBERO]
    lavoro = _lavoro(prova, spazio=lambda radice: libero[0])
    lavoro.chiavetta.prepara(prova.radice)
    libero[0] = 10
    partenze = []
    avvia = lavoro.avvia

    def conta(radice):
        partenze.append(radice)
        return avvia(radice)

    lavoro.avvia = conta
    tempo = Tempo()
    guardiano = Guardiano(lavoro, dischi=Dischi(prova.radice), adesso=tempo)
    assert _giri(guardiano) == chiavetta.PROBLEMA
    assert guardiano.codice == "poco_spazio" and "GB" in guardiano.messaggio
    for _ in range(5):
        tempo.ora += chiavetta.RIPASSA
        assert guardiano.giro() == chiavetta.PROBLEMA
    assert len(partenze) == 1


def test_il_guardiano_dopo_una_pausa(tmp_path, chiave):
    prova = Prova(tmp_path, chiave)
    prova.foto(1)
    lavoro = _lavoro(prova)
    lavoro.chiavetta.prepara(prova.radice)
    guardiano = Guardiano(lavoro, dischi=Dischi(prova.radice))
    lavoro.pausa()
    guardiano.giro()
    lavoro.ferma(ATTESA)
    assert guardiano.giro() == chiavetta.FERMATA


def test_il_guardiano_adotta_una_chiavetta_dopo_aver_perso_lo_stato(tmp_path, chiave):
    prova = Prova(tmp_path, chiave)
    prova.foto(2)
    prova.pronta()
    for nome in (STATO, RISERVA):
        (prova.banco.archivio / nome).unlink()
    lavoro = _lavoro(prova)
    guardiano = Guardiano(lavoro, dischi=Dischi(prova.radice))
    assert _giri(guardiano) == chiavetta.PUOI_STACCARLA
    _tutto_a_posto(prova)


def test_il_guardiano_gira_da_solo(tmp_path, chiave):
    prova = Prova(tmp_path, chiave)
    prova.foto(1)
    lavoro = _lavoro(prova)
    lavoro.chiavetta.prepara(prova.radice)
    guardiano = Guardiano(lavoro, dischi=Dischi(prova.radice), ogni=0.01)
    guardiano.avvia()
    guardiano.avvia()
    fine = time.monotonic() + ATTESA
    while guardiano.stato != chiavetta.PUOI_STACCARLA and time.monotonic() < fine:
        time.sleep(0.01)
    guardiano.ferma(ATTESA)
    assert guardiano.stato == chiavetta.PUOI_STACCARLA


def test_il_guardiano_sopravvive_agli_errori(tmp_path, chiave):
    prova = Prova(tmp_path, chiave)

    def dischi():
        raise RuntimeError("rotto")

    guardiano = Guardiano(_lavoro(prova), dischi=dischi, ogni=0.01)
    guardiano.avvia()
    fine = time.monotonic() + ATTESA
    while guardiano.codice != "guardiano" and time.monotonic() < fine:
        time.sleep(0.01)
    guardiano.ferma(ATTESA)
    assert guardiano.stato == chiavetta.PROBLEMA


def test_i_dischi_attaccati_fuori_da_windows(tmp_path, monkeypatch):
    assert isinstance(chiavetta.dischi_attaccati(), list)
    assert chiavetta.sistema_dei_file(tmp_path) is None


@pytest.mark.parametrize("byte,testo", [(0, "0,0 GB"), (1024 ** 3, "1,0 GB"),
                                        (int(2.55 * 1024 ** 3), "2,5 GB"), (-5, "0,0 GB")])
def test_i_gb_all_italiana(byte, testo):
    assert chiavetta._gb(byte) == testo


@pytest.mark.parametrize("resoconto,frase", [
    (Resoconto(), "La chiavetta non è ancora aggiornata: non staccarla."),
    (Resoconto(finito=True), "Puoi staccarla: era già tutto aggiornato."),
    (Resoconto(finito=True, copiati=1200), "Puoi staccarla. 1.200 file nuovi copiati."),
    (Resoconto(finito=True, riletti=3), "Puoi staccarla. 3 file riletti."),
    (Resoconto(finito=True, copiati=2, riletti=3, ricopiati=["a"]),
     "Puoi staccarla. 2 file nuovi copiati, 3 riletti, 1 riparati."),
    (Resoconto(finito=True, persi_sul_pc=["a"]),
     "Puoi staccarla, ma attenzione: 1 file è rovinato e non si ripara."),
    (Resoconto(finito=True, persi_sul_pc=["a"], rovinati_sulla_chiavetta=["a", "b"]),
     "Puoi staccarla, ma attenzione: 2 file sono rovinati e non si riparano.")])
def test_le_frasi(resoconto, frase):
    assert resoconto.frase() == frase
