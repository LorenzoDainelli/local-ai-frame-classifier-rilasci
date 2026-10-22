from __future__ import annotations

import contextlib
import dataclasses
import errno
import json
import os
import random
import shutil
import string
import struct
import sys
import time
import types
from pathlib import Path

import pytest

from officina.errori import ErroreOfficina
from officina.sicuro import chiavi
from officina.sicuro import cestino as modulo
from officina.sicuro.cestino import (A_META, ASPETTA, ATTESA, ATTIVO, AVVISO, CESTINO,
                                     CHIAVETTA, DA_FARE, DA_GUARDARE, DIVERSA, FATTO,
                                     FINITA, FISSO, IN_PARTE, IN_PARTENZA, LASCIATO, LISTE,
                                     NEL_CESTINO, NON_PARTITA, NON_TOCCATA, PERSA, PERSO,
                                     QUADERNO, RETE, RIMESSO, RISERVA, STRANO, SVUOTABILE,
                                     SVUOTATA, TIPO_QUADERNO, TORNATA, Capienza, Cestino,
                                     CestinoAssente, Mandata, Mossa, Quaderno, Ricontrollo,
                                     Ronda, Spedizioniere, Vedetta, cestino_di_sistema,
                                     leggi_info, permesso, scrivi_info, stato_di)
from officina.sicuro.chiavetta import ChiavettaStaccata
from officina.sicuro.copia import CUSTODITO, Fermato
from officina.sicuro.dentro import _resto, _uguali
from officina.sicuro.elenco import CONTENUTI, fatto_radice
from officina.sicuro.sottofondo import FERMATO, FINITO
from officina.sicuro.via_libera import VALIDO_PER
from prove.test_sicuro_chiavetta import _danneggia, _sveglio, chiave, pezzi_piccoli
from prove.test_sicuro_via_libera import CARTELLE, FOTO, Via, _scrivi_uguale

SID = "S-1-5-21-1000-2000-3000-1001"
ATTESA_FILO = 20.0
PESO = sum(len(dati) for dati in FOTO.values())
DENTRO_S = {**{nome[2:]: dati for nome, dati in FOTO.items()}, "sotto": None, "vuota": None}
DUE = {**FOTO, **{"t" + nome[1:]: dati for nome, dati in FOTO.items()}}
DUE_VUOTE = ("s/vuota", "t/vuota")
su_linux = pytest.mark.skipif(os.name == "nt", reason="prove del lato Linux")

assert chiave and pezzi_piccoli


class Crollo(BaseException):
    pass


def _peso(percorso: str) -> int:
    if not os.path.isdir(percorso) or os.path.islink(percorso):
        return os.lstat(percorso).st_size
    return sum(os.lstat(os.path.join(cartella, nome)).st_size
               for cartella, _, nomi in os.walk(percorso) for nome in nomi)


def _via(percorso: str) -> None:
    if os.path.isdir(percorso) and not os.path.islink(percorso):
        shutil.rmtree(percorso)
    else:
        os.unlink(percorso)


class CestinoFinto(Cestino):

    def __init__(self, disco, *, genere=FISSO, sistema="NTFS", massimo=10 * modulo.GB,
                 spento=False, in_piu=0, giorni=None, modo="bene", seme=7):
        self.disco = os.fspath(disco)
        self.dischi = {self.disco: [genere, sistema]}
        self.massimo = massimo
        self.spento = spento
        self.in_piu = in_piu
        self.giorni = giorni
        self.modo = modo
        self.ricicla = True
        self.prima = None
        self.dopo = None
        self.dice = None
        self.guasto = None
        self.mosse: list[str] = []
        self.dentro = os.path.join(self.disco, CESTINO, SID)
        self._caso = random.Random(seme)

    def volume(self, percorso):
        if self.guasto == "volume":
            raise OSError(errno.EIO, "volume")
        percorso = os.fspath(percorso)
        trovati = [disco for disco in self.dischi if _resto(disco, percorso) is not None]
        return max(trovati, key=len) if trovati else None

    def tipo(self, volume):
        return self.dischi[volume][0]

    def sistema(self, volume):
        return self.dischi[volume][1]

    def capienza(self, volume):
        if self.guasto == "capienza":
            raise OSError(errno.EIO, "capienza")
        return Capienza(self.massimo, self.spento)

    def usato(self, volume):
        if self.guasto == "usato":
            return None
        return self.in_piu + sum(
            os.lstat(os.path.join(cartella, nome)).st_size
            for cartella, _, nomi in os.walk(self.dentro) for nome in nomi)

    def pulizia(self):
        if self.guasto == "pulizia":
            raise OSError(errno.EIO, "pulizia")
        return self.giorni

    def cartella(self, volume):
        if self.guasto == "cartella" or not _uguali(volume, self.disco):
            return None
        return self.dentro

    def _coda(self, percorso: str) -> str:
        estensione = os.path.splitext(os.path.basename(percorso))[1]
        lettere = string.ascii_uppercase + string.digits
        while True:
            coda = "".join(self._caso.choice(lettere) for _ in range(6)) + estensione
            if not os.path.lexists(os.path.join(self.dentro, "$R" + coda)):
                return coda

    def a_mano(self, percorso, *, info=True, quando=None) -> str:
        percorso = os.path.abspath(os.fspath(percorso))
        os.makedirs(self.dentro, exist_ok=True)
        coda = self._coda(percorso)
        dati = os.path.join(self.dentro, "$R" + coda)
        peso = _peso(percorso)
        os.rename(percorso, dati)
        if info:
            Path(self.dentro, "$I" + coda).write_bytes(scrivi_info(
                percorso, time.time() if quando is None else quando, peso))
        return dati

    def _sposta(self, percorso):
        self.mosse.append(percorso)
        if self.prima is not None:
            self.prima(percorso)
        if permesso(modulo.RICICLA_SE_PUOI if self.ricicla else 0, percorso, percorso):
            return Mossa(False, None, "rifiutata")
        modo = self.modo
        if modo == "rifiuta":
            return Mossa(False, None, "rifiutata")
        if modo == "crollo_prima":
            raise Crollo
        if modo == "eccezione_prima":
            raise RuntimeError("prima")
        if modo == "per_sempre":
            _via(percorso)
            return Mossa(True, os.path.join(self.dentro, "$RFINTO"), None)
        if modo == "a_meta":
            self.a_mano(os.path.join(percorso, sorted(os.listdir(percorso))[0]))
            return Mossa(False, None, "rifiutata")
        if modo == "altrove":
            altrove = os.path.join(self.disco, "altrove")
            os.makedirs(altrove, exist_ok=True)
            os.rename(percorso, os.path.join(altrove, os.path.basename(percorso)))
            return Mossa(True, None, None)
        dati = self.a_mano(percorso, info=modo != "senza_info")
        if self.dopo is not None:
            self.dopo(dati)
        if modo == "crollo_dopo":
            raise Crollo
        if modo == "bugiardo":
            return Mossa(False, None, "rifiutata")
        if modo == "eccezione":
            raise RuntimeError("dopo")
        return Mossa(True, self.dice or dati, None)

    def roba(self) -> list[str]:
        if not os.path.isdir(self.dentro):
            return []
        return sorted(os.listdir(self.dentro))


class Scena:

    def __init__(self, cartella: Path, chiave, *, prova_fatta: bool = True, foto=FOTO,
                 cartelle=CARTELLE, cestino=None, **opzioni):
        self.base = cartella
        self.via = Via(cartella, chiave, foto=foto, cartelle=cartelle)
        self.chiave = chiave
        self.cestino = cestino or CestinoFinto(cartella)
        self.quaderno = Quaderno(self.via.banco.archivio, chiave)
        if prova_fatta:
            self.quaderno.metti_collaudo(FATTO)
        self.opzioni = opzioni
        self.spedizioniere = self.nuovo()

    def nuovo(self, quaderno=None, **opzioni) -> Spedizioniere:
        via = self.via
        opzioni = {**self.opzioni, **opzioni}
        opzioni.setdefault("apri", via.banco.apri)
        opzioni.setdefault("dischi", lambda: [via.prova.radice])
        opzioni.setdefault("speciali", lambda: [])
        opzioni.setdefault("nuvole", lambda: [])
        opzioni.setdefault("adesso", via.prova.orologio)
        cestino = opzioni.pop("cestino", self.cestino)
        return Spedizioniere(via.banco.archivio, via.banco.elenco, self.chiave,
                             via.prova.chiavetta, cestino, quaderno or self.quaderno,
                             **opzioni)

    def riapri(self) -> Spedizioniere:
        self.quaderno = Quaderno(self.via.banco.archivio, self.chiave)
        self.spedizioniere = self.nuovo()
        return self.spedizioniere

    def esame(self, relativo: str = "s"):
        return self.spedizioniere.esaminatore.esamina(self.via.qui(relativo))

    def manda(self, *relativi, parola: str = "CANCELLA") -> list[dict]:
        esami = [self.esame(relativo) for relativo in relativi or ("s",)]
        return self.spedizioniere.manda(esami, parola)

    def vedetta(self, **opzioni) -> Vedetta:
        opzioni.setdefault("apri", self.via.banco.apri)
        classe = opzioni.pop("classe", Vedetta)
        return classe(self.via.banco.elenco, self.cestino, self.quaderno, **opzioni)

    def custoditi(self, chiavi_posti) -> list[bool]:
        return [CUSTODITO in self.via.banco.elenco.posto(chiave).segni
                for chiave in chiavi_posti]


def _albero(percorso) -> dict[str, bytes | None]:
    albero: dict[str, bytes | None] = {}
    for cartella, sotto, nomi in os.walk(percorso):
        relativa = Path(cartella).relative_to(percorso).as_posix()
        prefisso = "" if relativa == "." else relativa + "/"
        for nome in sotto:
            albero[prefisso + nome] = None
        for nome in nomi:
            albero[prefisso + nome] = Path(cartella, nome).read_bytes()
    return albero


def _codice(fare) -> str:
    with pytest.raises(ErroreOfficina) as preso:
        fare()
    return preso.value.codice


def _aspetta_che(condizione, quanto: float = ATTESA_FILO) -> None:
    fine = time.monotonic() + quanto
    while not condizione():
        assert time.monotonic() < fine
        time.sleep(0.005)


def _voce(scena: Scena, risultato: dict) -> dict:
    return scena.quaderno.spedizione(risultato["spedizione"])["voci"][0]


def test_le_info_del_cestino_si_scrivono_e_si_rileggono():
    for originale in ("C:\\Foto\\estate", "C:\\Foto\\è più bello.jpg", "x",
                      "D:\\" + "lungo\\" * 50 + "fine.jpg"):
        letto = leggi_info(scrivi_info(originale, 1_700_000_000.5, 12345))
        assert letto[0] == originale and letto[2] == 12345
        assert abs(letto[1] - 1_700_000_000.5) < 1e-5


def test_le_info_della_versione_vecchia_si_leggono():
    testo = "C:\\Foto\\vecchia".encode("utf-16-le").ljust(520, b"\x00")
    tempo = round((1_600_000_000 + modulo.SECONDI_WINDOWS) * 1e7)
    letto = leggi_info(struct.pack("<qqQ", 1, 77, tempo) + testo)
    assert letto[0] == "C:\\Foto\\vecchia" and letto[2] == 77
    assert abs(letto[1] - 1_600_000_000) < 1e-5


@pytest.mark.parametrize("grezzi", [
    b"",
    b"\x02" + b"\x00" * 10,
    struct.pack("<qqQ", 3, 1, 1) + "a\x00".encode("utf-16-le") * 300,
    struct.pack("<qqQ", 1, 1, 1) + b"a\x00" * 10,
    struct.pack("<qqQ", 2, 1, 1),
    struct.pack("<qqQi", 2, 1, 1, 0),
    struct.pack("<qqQi", 2, 1, 1, -4),
    struct.pack("<qqQi", 2, 1, 1, 40000) + b"a\x00" * 40000,
    struct.pack("<qqQi", 2, 1, 1, 5) + b"a\x00",
    struct.pack("<qqQi", 2, -1, 1, 2) + "a\x00".encode("utf-16-le"),
    struct.pack("<qqQi", 2, 1, 1, 1) + "\x00".encode("utf-16-le"),
    struct.pack("<qqQ", 1, 5, 1) + b"\x00" * 520,
])
def test_le_info_strane_non_si_leggono(grezzi):
    assert leggi_info(grezzi) is None


def test_le_info_a_caso_non_fanno_mai_danni():
    caso = random.Random(11)
    buona = scrivi_info("C:\\Foto\\a.jpg", 1_700_000_000.0, 10)
    for _ in range(3000):
        grezzi = bytearray(buona)
        for _ in range(caso.randint(1, 6)):
            grezzi[caso.randrange(len(grezzi))] = caso.randrange(256)
        if caso.random() < 0.3:
            grezzi = grezzi[:caso.randrange(len(grezzi) + 1)]
        letto = leggi_info(bytes(grezzi))
        assert letto is None or (isinstance(letto[0], str) and letto[0] and letto[2] >= 0)


def test_le_info_tutte_a_caso_non_fanno_mai_danni():
    caso = random.Random(12)
    for _ in range(3000):
        grezzi = caso.randbytes(caso.randrange(80))
        if caso.random() < 0.5:
            grezzi = struct.pack("<q", caso.choice((1, 2))) + grezzi
        letto = leggi_info(grezzi)
        assert letto is None or letto[0]


@pytest.mark.parametrize("flags, elemento, esito", [
    (0x80, "C:\\Foto\\s", modulo.S_OK),
    (0x80 | 0x4 | 0x40, "C:\\Foto\\s", modulo.S_OK),
    (0x80, "c:\\foto\\s", modulo.S_OK if os.name == "nt" else modulo.E_ABORT),
    (0x0, "C:\\Foto\\s", modulo.E_ABORT),
    (0x40, "C:\\Foto\\s", modulo.E_ABORT),
    (0x7F, "C:\\Foto\\s", modulo.E_ABORT),
    (0x80, "C:\\Foto\\altra", modulo.E_ABORT),
    (0x80, "C:\\Foto", modulo.E_ABORT),
    (0x80, "C:\\Foto\\s\\a.jpg", modulo.E_ABORT),
    (0x80, None, modulo.E_ABORT),
    ("strano", "C:\\Foto\\s", modulo.E_ABORT),
    (None, "C:\\Foto\\s", modulo.E_ABORT),
    (0x80, 12, modulo.E_ABORT),
])
def test_windows_puo_cancellare_solo_nel_cestino_e_solo_quella(flags, elemento, esito):
    assert permesso(flags, elemento, "C:\\Foto\\s") == esito


@pytest.mark.parametrize("byte, testo", [
    (0, "0 MB"), (1, "meno di 1 MB"), (modulo.MB - 1, "meno di 1 MB"), (modulo.MB, "1 MB"),
    (1536 * 1024, "2 MB"), (500 * modulo.MB, "500 MB"), (modulo.GB, "1,0 GB"),
    (int(2.5 * modulo.GB), "2,5 GB"), (300 * modulo.GB, "300,0 GB"),
    (modulo.GB - 1, "1,0 GB"), (1023 * modulo.MB, "1023 MB"),
])
def test_le_misure_si_dicono_semplici(byte, testo):
    assert modulo._quanto(byte) == testo


@pytest.mark.parametrize("esiti, stato", [
    ([NEL_CESTINO], NEL_CESTINO),
    ([NEL_CESTINO, NEL_CESTINO], NEL_CESTINO),
    ([NON_PARTITA], NON_PARTITA),
    ([NON_PARTITA, NON_PARTITA], NON_PARTITA),
    ([NEL_CESTINO, NON_PARTITA], IN_PARTE),
    ([IN_PARTENZA, NEL_CESTINO], IN_PARTENZA),
    ([IN_PARTENZA, PERSA], IN_PARTENZA),
    ([A_META], DA_GUARDARE),
    ([DIVERSA, NEL_CESTINO], DA_GUARDARE),
    ([PERSA, NON_PARTITA], DA_GUARDARE),
    ([NEL_CESTINO, NON_PARTITA, PERSA], DA_GUARDARE),
])
def test_lo_stato_di_una_spedizione(esiti, stato):
    assert stato_di({"voci": [{"esito": esito} for esito in esiti]}) == stato


def test_una_cartella_verde_va_nel_cestino_tutta(tmp_path, chiave):
    scena = Scena(tmp_path, chiave)
    via = scena.via
    contenuti = via.banco.contenuti()
    esame = scena.esame()
    posti = dict(esame.dove_posti)
    assert len(posti) == 8
    risultato, = scena.spedizioniere.manda([esame], "CANCELLA")
    assert risultato["esito"] == NEL_CESTINO and risultato["codice"] is None
    assert risultato["file"] == 5 and risultato["byte"] == PESO
    assert risultato["nel_cestino"] == 1
    assert risultato["messaggio"] == (
        "È nel Cestino di Windows, e ho controllato che c'è tutta.")
    assert not via.qui("s").exists() and via.foto.exists()
    assert scena.cestino.mosse == [esame.vero]
    spedizione = scena.quaderno.spedizione(risultato["spedizione"])
    voce, = spedizione["voci"]
    assert voce["esito"] == NEL_CESTINO and spedizione["custodita"]
    assert spedizione["file"] == 5 and spedizione["byte"] == PESO
    assert _albero(voce["dove"]) == DENTRO_S
    buttato = scena.cestino.leggi(voce["info"])
    assert buttato.originale == esame.vero and buttato.dati == voce["dove"]
    assert voce["nome"] == buttato.nome
    assert all(scena.custoditi(posti))
    via.banco.giro()
    for chiave_posto in posti:
        assert via.banco.elenco.posto(chiave_posto).sparito is None
    assert via.banco.contenuti() == contenuti
    json.dumps(risultato)


def test_dopo_il_cestino_le_foto_si_ritrovano_nell_archivio(tmp_path, chiave):
    scena = Scena(tmp_path, chiave)
    scena.manda()
    scena.via.banco.giro()
    for nome, dati in FOTO.items():
        posto = scena.via.banco.posto(nome)
        assert posto is not None and posto.sparito is None
        assert scena.via.banco.dati(posto.contenuto) == dati


def test_la_lista_tiene_le_impronte_e_i_posti(tmp_path, chiave):
    scena = Scena(tmp_path, chiave)
    esame = scena.esame()
    risultato, = scena.spedizioniere.manda([esame], "CANCELLA")
    lista = scena.quaderno.leggi_lista(risultato["spedizione"])
    voce, = lista["voci"]
    assert voce["posti"] == dict(sorted(esame.dove_posti.items()))
    assert voce["impronte"] == {relativo: list(impronta)
                                for relativo, impronta in esame.impronta.items()}


@pytest.mark.parametrize("parola", ["CANCELLA", " CANCELLA ", "CANCELLA\n", "\tCANCELLA"])
def test_la_parola_giusta(tmp_path, chiave, parola):
    scena = Scena(tmp_path, chiave)
    assert scena.manda(parola=parola)[0]["esito"] == NEL_CESTINO


@pytest.mark.parametrize("parola", ["", " ", "CANCELL", "cancellare", "CANCELLA!", "sì",
                                    "ok", "C A N C E L L A", None, 1, b"CANCELLA",
                                    "cancella", "Cancella", " cancella ", "cAnCeLlA",
                                    "CANCELLa", "CANCELLARE", "\uff23\uff21\uff2e\uff23"
                                    "\uff25\uff2c\uff2c\uff21", "CANCELL\u0410",
                                    "CANCE\u200bLLA"])
def test_la_parola_sbagliata_non_tocca_niente(tmp_path, chiave, parola):
    scena = Scena(tmp_path, chiave)
    esame = scena.esame()
    assert _codice(lambda: scena.spedizioniere.manda([esame], parola)) == "parola_sbagliata"
    assert scena.cestino.mosse == [] and scena.via.qui("s/a.jpg").exists()
    assert scena.quaderno.spedizioni() == []


def test_il_riepilogo_dice_quante_e_quanto(tmp_path, chiave):
    scena = Scena(tmp_path, chiave)
    riepilogo = scena.spedizioniere.riepilogo([scena.esame()])
    assert riepilogo["cartelle"] == 1 and riepilogo["file"] == 5
    assert riepilogo["byte"] == PESO and riepilogo["si_puo"]
    assert riepilogo["fuori"] == [] and riepilogo["collaudo"] == FATTO
    assert riepilogo["frasi"] == [
        f"Vanno nel Cestino di Windows: 1 cartella, 5 file, {modulo._quanto(PESO)}.",
        "Fra 30 giorni ricontrollo archivio e chiavetta e ti dico se puoi svuotare il "
        "Cestino."]
    assert scena.cestino.mosse == []
    json.dumps(riepilogo)


@pytest.mark.parametrize("giorni", [31, 60, 365])
def test_il_riepilogo_avvisa_del_sensore_memoria(tmp_path, chiave, giorni):
    scena = Scena(tmp_path, chiave)
    scena.cestino.giorni = giorni
    riepilogo = scena.spedizioniere.riepilogo([scena.esame()])
    assert riepilogo["si_puo"] and riepilogo["fuori"] == []
    assert any(f"dopo {giorni} giorni (Sensore memoria)" in frase
               for frase in riepilogo["frasi"])
    assert scena.manda()[0]["esito"] == NEL_CESTINO


@pytest.mark.parametrize("giorni", [1, 14, 29, 30])
def test_se_il_sensore_memoria_svuota_prima_del_ricontrollo_non_si_manda(tmp_path, chiave,
                                                                          giorni):
    scena = Scena(tmp_path, chiave)
    scena.cestino.giorni = giorni
    riepilogo = scena.spedizioniere.riepilogo([scena.esame()])
    assert not riepilogo["si_puo"]
    assert [fuori["codice"] for fuori in riepilogo["fuori"]] == ["sensore_memoria"]
    assert not any("Sensore memoria)" in frase for frase in riepilogo["frasi"])
    risultato, = scena.manda()
    assert risultato["esito"] == NON_TOCCATA and risultato["codice"] == "sensore_memoria"
    assert "Impostazioni, Sistema, Archiviazione" in risultato["messaggio"]
    assert scena.cestino.mosse == [] and scena.via.qui("s/a.jpg").exists()
    assert scena.quaderno.spedizioni() == []


def test_il_sensore_acceso_dopo_il_riepilogo_ferma_lo_stesso(tmp_path, chiave):
    scena = Scena(tmp_path, chiave, foto=DUE, cartelle=DUE_VUOTE)
    esami = [scena.esame("s"), scena.esame("t")]
    assert scena.spedizioniere.riepilogo(esami)["si_puo"]
    scena.cestino.giorni = 14
    risultati = scena.spedizioniere.manda(esami, "CANCELLA")
    assert [risultato["codice"] for risultato in risultati] == ["sensore_memoria"] * 2
    assert scena.cestino.mosse == []


UTENTE = ("utente", modulo.SENSORE)
REGOLA = ("macchina", modulo.REGOLA_SENSORE)
DWORD = 4


def _registro_finto(valori: dict):
    chiavi = {(radice, percorso) for radice, percorso, _ in valori}

    @contextlib.contextmanager
    def apri(radice, percorso):
        if (radice, percorso) not in chiavi:
            raise FileNotFoundError(errno.ENOENT, percorso)
        yield radice, percorso

    def leggi(chiave, nome):
        if (*chiave, nome) not in valori:
            raise FileNotFoundError(errno.ENOENT, nome)
        return valori[(*chiave, nome)]

    return types.SimpleNamespace(HKEY_CURRENT_USER="utente", HKEY_LOCAL_MACHINE="macchina",
                                 REG_DWORD=DWORD, REG_QWORD=11, OpenKey=apri,
                                 QueryValueEx=leggi)


@pytest.mark.parametrize("valori, giorni", [
    ({}, None),
    ({(*UTENTE, "01"): (0, DWORD), (*UTENTE, "256"): (1, DWORD)}, None),
    ({(*UTENTE, "01"): (1, DWORD), (*UTENTE, "256"): (14, DWORD)}, 14),
    ({(*UTENTE, "01"): (1, DWORD), (*UTENTE, "256"): (60, DWORD)}, 60),
    ({(*UTENTE, "01"): (1, DWORD), (*UTENTE, "256"): (0, DWORD)}, None),
    ({(*UTENTE, "01"): (1, DWORD)}, 30),
    ({(*UTENTE, "01"): (1, DWORD), (*UTENTE, "256"): ("14", 1)}, 30),
    ({(*REGOLA, "AllowStorageSenseGlobal"): (0, DWORD), (*UTENTE, "01"): (1, DWORD),
      (*UTENTE, "256"): (1, DWORD)}, None),
    ({(*REGOLA, "AllowStorageSenseGlobal"): (1, DWORD)}, 30),
    ({(*REGOLA, "AllowStorageSenseGlobal"): (1, DWORD), (*UTENTE, "256"): (60, DWORD)}, 60),
    ({(*REGOLA, "AllowStorageSenseGlobal"): (1, DWORD),
      (*REGOLA, "ConfigStorageSenseRecycleBinCleanupThreshold"): (0, DWORD)}, None),
    ({(*REGOLA, "ConfigStorageSenseRecycleBinCleanupThreshold"): (7, DWORD),
      (*UTENTE, "01"): (1, DWORD), (*UTENTE, "256"): (60, DWORD)}, 7),
    ({(*REGOLA, "ConfigStorageSenseRecycleBinCleanupThreshold"): (90, DWORD),
      (*UTENTE, "01"): (1, DWORD), (*UTENTE, "256"): (1, DWORD)}, 90),
    ({(*REGOLA, "ConfigStorageSenseRecycleBinCleanupThreshold"): (7, DWORD)}, None),
])
def test_il_sensore_memoria_si_legge_dal_registro(monkeypatch, valori, giorni):
    monkeypatch.setitem(sys.modules, "winreg", _registro_finto(valori))
    assert modulo.CestinoWindows().pulizia() == giorni


def test_il_sensore_spento_lascia_mandare(tmp_path, chiave):
    scena = Scena(tmp_path, chiave)
    riepilogo = scena.spedizioniere.riepilogo([scena.esame()])
    assert riepilogo["si_puo"]
    assert not any("Sensore memoria" in frase for frase in riepilogo["frasi"])


def test_il_riepilogo_con_due_cartelle_e_una_rossa(tmp_path, chiave):
    scena = Scena(tmp_path, chiave, foto=DUE, cartelle=DUE_VUOTE)
    esami = [scena.esame("s"), scena.esame("t")]
    scena.via.banco.metti("t/nuova.jpg", b"nuova")
    esami.append(scena.esame("t"))
    riepilogo = scena.spedizioniere.riepilogo(esami)
    assert riepilogo["cartelle"] == 2 and riepilogo["file"] == 10
    assert riepilogo["frasi"][0].startswith(
        "Vanno nel Cestino di Windows: 2 cartelle, 10 file")
    assert [fuori["codice"] for fuori in riepilogo["fuori"]] == ["rossa"]


def test_il_riepilogo_conta_il_posto_per_tutte_insieme(tmp_path, chiave):
    scena = Scena(tmp_path, chiave, foto=DUE, cartelle=DUE_VUOTE)
    scena.cestino.massimo = int(PESO * 1.5 / modulo.MARGINE)
    riepilogo = scena.spedizioniere.riepilogo([scena.esame("s"), scena.esame("t")])
    assert riepilogo["cartelle"] == 1
    assert [fuori["codice"] for fuori in riepilogo["fuori"]] == ["cestino_pieno"]


def test_il_riepilogo_senza_buone_non_si_puo(tmp_path, chiave):
    scena = Scena(tmp_path, chiave)
    scena.via.banco.metti("s/nuova.jpg", b"nuova")
    riepilogo = scena.spedizioniere.riepilogo([scena.esame()])
    assert not riepilogo["si_puo"] and riepilogo["cartelle"] == 0
    assert riepilogo["frasi"] == []
    assert scena.spedizioniere.riepilogo([])["si_puo"] is False


def test_la_prima_volta_una_cartella_piccola_e_poi_si_guarda(tmp_path, chiave):
    scena = Scena(tmp_path, chiave, prova_fatta=False, foto=DUE, cartelle=DUE_VUOTE)
    spedizioniere = scena.spedizioniere
    assert scena.quaderno.collaudo == DA_FARE
    riepilogo = spedizioniere.riepilogo([scena.esame("s"), scena.esame("t")])
    assert not riepilogo["si_puo"]
    assert "una cartella sola e piccola" in riepilogo["frasi"][-1]
    assert _codice(lambda: scena.manda("s", "t")) == "prima_una_piccola"
    assert scena.cestino.mosse == []
    riepilogo = spedizioniere.riepilogo([scena.esame("s")])
    assert riepilogo["si_puo"] and any("È la prima volta" in frase
                                       for frase in riepilogo["frasi"])
    risultato, = scena.manda("s")
    assert risultato["esito"] == NEL_CESTINO
    assert scena.quaderno.collaudo == DA_GUARDARE
    assert scena.quaderno.prova == risultato["spedizione"]
    assert not spedizioniere.riepilogo([scena.esame("t")])["si_puo"]
    assert _codice(lambda: scena.manda("t")) == "prima_guarda"
    assert scena.via.qui("t").exists()
    spedizioniere.ho_controllato()
    assert scena.quaderno.collaudo == FATTO
    assert _codice(spedizioniere.ho_controllato) == "niente_da_guardare"
    assert scena.manda("t")[0]["esito"] == NEL_CESTINO
    assert scena.quaderno.collaudo == FATTO


@pytest.mark.parametrize("cosa", ["file", "byte"])
def test_la_prima_volta_una_grande_non_va(tmp_path, chiave, monkeypatch, cosa):
    monkeypatch.setattr(modulo, "PROVA_FILE" if cosa == "file" else "PROVA_BYTE", 4)
    scena = Scena(tmp_path, chiave, prova_fatta=False)
    assert _codice(scena.manda) == "prima_una_piccola"
    assert scena.cestino.mosse == [] and scena.quaderno.collaudo == DA_FARE


def test_la_prima_volta_al_limite_va(tmp_path, chiave, monkeypatch):
    monkeypatch.setattr(modulo, "PROVA_FILE", 5)
    monkeypatch.setattr(modulo, "PROVA_BYTE", PESO)
    scena = Scena(tmp_path, chiave, prova_fatta=False)
    assert scena.manda()[0]["esito"] == NEL_CESTINO


def test_la_prima_volta_se_non_parte_resta_da_fare(tmp_path, chiave):
    scena = Scena(tmp_path, chiave, prova_fatta=False)
    scena.cestino.modo = "rifiuta"
    assert scena.manda()[0]["esito"] == NON_PARTITA
    assert scena.quaderno.collaudo == DA_FARE


def test_la_prima_volta_si_ricorda_anche_dopo_un_crollo(tmp_path, chiave):
    scena = Scena(tmp_path, chiave, prova_fatta=False)
    scena.cestino.modo = "crollo_dopo"
    with pytest.raises(Crollo):
        scena.manda()
    spedizioniere = scena.riapri()
    assert scena.quaderno.collaudo == DA_FARE
    ripresa, = spedizioniere.riprendi()
    assert scena.quaderno.collaudo == DA_GUARDARE and scena.quaderno.prova == ripresa


def test_la_rossa_non_si_tocca(tmp_path, chiave):
    scena = Scena(tmp_path, chiave)
    scena.via.banco.metti("s/nuova.jpg", b"nuova")
    risultato, = scena.manda()
    assert risultato["esito"] == NON_TOCCATA and risultato["codice"] == "rossa"
    assert risultato["spedizione"] is None and risultato["file"] == 0
    assert scena.via.qui("s/a.jpg").exists() and scena.cestino.mosse == []
    assert scena.quaderno.spedizioni() == []


@pytest.mark.parametrize("salto", [VALIDO_PER + 1, -1])
def test_un_controllo_vecchio_o_del_futuro_si_rifa(tmp_path, chiave, salto):
    scena = Scena(tmp_path, chiave)
    esame = scena.esame()
    scena.via.prova.orologio.ora += salto
    risultato, = scena.spedizioniere.manda([esame], "CANCELLA")
    assert risultato["codice"] == "da_ricontrollare" and scena.cestino.mosse == []


def test_un_controllo_di_dieci_minuti_fa_va_ancora(tmp_path, chiave):
    scena = Scena(tmp_path, chiave)
    esame = scena.esame()
    scena.via.prova.orologio.ora += VALIDO_PER
    assert scena.spedizioniere.manda([esame], "CANCELLA")[0]["esito"] == NEL_CESTINO


def test_una_cartella_di_onedrive_non_si_tocca(tmp_path, chiave):
    scena = Scena(tmp_path, chiave)
    nuvole = lambda: [os.fspath(scena.via.foto)]
    scena.spedizioniere = scena.nuovo(nuvole=nuvole)
    esame = scena.esame()
    assert esame.sincronizzata
    risultato, = scena.spedizioniere.manda([esame], "CANCELLA")
    assert risultato["codice"] == "sincronizzata" and scena.cestino.mosse == []
    scena.spedizioniere = scena.nuovo(nuvole=nuvole, nuvola=True)
    assert scena.manda()[0]["esito"] == NEL_CESTINO


def _cambia_un_byte(via):
    _scrivi_uguale(via.qui("s/b.jpg"), b"\x00")


def _un_file_nuovo(via):
    via.qui("s/arrivata.jpg").write_bytes(b"arrivata")


def _una_cartella_nuova(via):
    via.qui("s/sotto/nuova").mkdir()


def _un_file_tolto(via):
    via.qui("s/sotto/c.jpg").unlink()


def _una_cartella_tolta(via):
    via.qui("s/vuota").rmdir()


def _un_nome_cambiato(via):
    via.qui("s/a.jpg").rename(via.qui("s/z.jpg"))


def _una_data_cambiata(via):
    prima = os.lstat(via.qui("s/a.jpg"))
    os.utime(via.qui("s/a.jpg"), ns=(prima.st_atime_ns, prima.st_mtime_ns + 10 ** 9))


def _rifatto_uguale(via):
    dati = via.qui("s/a.jpg").read_bytes()
    prima = os.lstat(via.qui("s/a.jpg"))
    via.qui("s/a.jpg").unlink()
    via.qui("s/a.jpg").write_bytes(dati)
    os.utime(via.qui("s/a.jpg"), ns=(prima.st_atime_ns, prima.st_mtime_ns))


def _cartella_rifatta(via):
    via.qui("s").rename(via.qui("vecchia"))
    shutil.copytree(via.qui("vecchia"), via.qui("s"), copy_function=shutil.copy2)


@pytest.mark.parametrize("cambio", [_cambia_un_byte, _un_file_nuovo, _una_cartella_nuova,
                                    _un_file_tolto, _una_cartella_tolta, _un_nome_cambiato,
                                    _una_data_cambiata, _rifatto_uguale, _cartella_rifatta])
def test_se_dopo_il_controllo_cambia_qualcosa_non_si_tocca(tmp_path, chiave, cambio):
    scena = Scena(tmp_path, chiave)
    esame = scena.esame()
    prima = _albero(scena.via.qui("s"))
    cambio(scena.via)
    dopo = _albero(scena.via.qui("s"))
    risultato, = scena.spedizioniere.manda([esame], "CANCELLA")
    assert risultato["esito"] == NON_TOCCATA and risultato["codice"] == "cambiata"
    assert scena.cestino.mosse == [] and scena.quaderno.spedizioni() == []
    assert _albero(scena.via.qui("s")) == dopo
    assert prima or dopo


def test_se_sparisce_la_cartella_non_si_tocca_niente(tmp_path, chiave):
    scena = Scena(tmp_path, chiave)
    esame = scena.esame()
    shutil.rmtree(scena.via.qui("s"))
    risultato, = scena.spedizioniere.manda([esame], "CANCELLA")
    assert risultato["codice"] == "cambiata" and scena.cestino.mosse == []


@su_linux
def test_se_la_cartella_diventa_un_collegamento_non_si_tocca(tmp_path, chiave):
    scena = Scena(tmp_path, chiave)
    esame = scena.esame()
    scena.via.qui("s").rename(scena.via.qui("vera"))
    os.symlink(scena.via.qui("vera"), scena.via.qui("s"))
    risultato, = scena.spedizioniere.manda([esame], "CANCELLA")
    assert risultato["codice"] == "cambiata" and scena.cestino.mosse == []
    assert scena.via.qui("vera/a.jpg").exists()


def test_se_nell_archivio_sparisce_una_copia_non_si_tocca(tmp_path, chiave):
    scena = Scena(tmp_path, chiave)
    esame = scena.esame()
    scena.via.pc("s/b.jpg").unlink()
    risultato, = scena.spedizioniere.manda([esame], "CANCELLA")
    assert risultato["codice"] == "archivio_cambiato" and scena.cestino.mosse == []


def test_se_sulla_chiavetta_sparisce_una_copia_non_si_tocca(tmp_path, chiave):
    scena = Scena(tmp_path, chiave)
    esame = scena.esame()
    scena.via.sopra("s/b.jpg").unlink()
    risultato, = scena.spedizioniere.manda([esame], "CANCELLA")
    assert risultato["codice"] == "chiavetta_cambiata" and scena.cestino.mosse == []


def test_se_la_chiavetta_si_stacca_non_si_tocca_nessuna(tmp_path, chiave):
    scena = Scena(tmp_path, chiave, foto=DUE, cartelle=DUE_VUOTE)
    esami = [scena.esame("s"), scena.esame("t")]
    scena.via.prova.stacca()
    risultati = scena.spedizioniere.manda(esami, "CANCELLA")
    assert [risultato["codice"] for risultato in risultati] == [ChiavettaStaccata.codice] * 2
    assert scena.cestino.mosse == []


def test_se_la_chiavetta_si_stacca_a_meta_le_altre_non_si_toccano(tmp_path, chiave):
    scena = Scena(tmp_path, chiave, foto=DUE, cartelle=DUE_VUOTE)
    esami = [scena.esame("s"), scena.esame("t")]
    scena.cestino.dopo = lambda dati: scena.via.prova.stacca()
    primo, secondo = scena.spedizioniere.manda(esami, "CANCELLA")
    assert primo["esito"] == NEL_CESTINO
    assert secondo["esito"] == NON_TOCCATA
    assert secondo["codice"] == ChiavettaStaccata.codice
    assert scena.via.qui("t/a.jpg").exists()


def test_se_l_archivio_si_stacca_non_si_tocca_nessuna(tmp_path, chiave):
    scena = Scena(tmp_path, chiave, foto=DUE, cartelle=DUE_VUOTE)
    esami = [scena.esame("s"), scena.esame("t")]
    contenuti = scena.via.banco.archivio / CONTENUTI
    contenuti.rename(contenuti.with_name("altrove"))
    risultati = scena.spedizioniere.manda(esami, "CANCELLA")
    assert [risultato["codice"] for risultato in risultati] == ["archivio_sparito"] * 2
    assert scena.cestino.mosse == []


def test_due_cartelle_vanno_una_alla_volta(tmp_path, chiave):
    scena = Scena(tmp_path, chiave, foto=DUE, cartelle=DUE_VUOTE)
    primo, secondo = scena.manda("s", "t")
    assert primo["esito"] == secondo["esito"] == NEL_CESTINO
    assert primo["spedizione"] != secondo["spedizione"]
    assert len(scena.cestino.mosse) == 2 and len(scena.cestino.roba()) == 4
    assert len(scena.quaderno.spedizioni()) == 2


def test_una_rossa_in_mezzo_non_ferma_le_altre(tmp_path, chiave):
    scena = Scena(tmp_path, chiave, foto=DUE, cartelle=DUE_VUOTE)
    esami = [scena.esame("s"), scena.esame("t")]
    scena.via.qui("s/a.jpg").write_bytes(b"cambiata")
    primo, secondo = scena.spedizioniere.manda(esami, "CANCELLA")
    assert primo["codice"] == "cambiata" and secondo["esito"] == NEL_CESTINO


def test_il_cestino_si_riempie_mentre_si_manda(tmp_path, chiave):
    scena = Scena(tmp_path, chiave, foto=DUE, cartelle=DUE_VUOTE)
    scena.cestino.massimo = int(PESO * 1.5 / modulo.MARGINE)
    primo, secondo = scena.manda("s", "t")
    assert primo["esito"] == NEL_CESTINO
    assert secondo["codice"] == "cestino_pieno" and scena.via.qui("t/a.jpg").exists()
    assert secondo["messaggio"] == modulo.PROBLEMI["cestino_pieno"]


def _chiavetta(cestino, scena):
    cestino.dischi[cestino.disco][0] = CHIAVETTA


def _rete(cestino, scena):
    cestino.dischi[cestino.disco][0] = RETE


def _strano(cestino, scena):
    cestino.dischi[cestino.disco][0] = STRANO


def _fat(cestino, scena):
    cestino.dischi[cestino.disco][1] = "FAT32"


def _exfat(cestino, scena):
    cestino.dischi[cestino.disco][1] = "exFAT"


def _senza_sistema(cestino, scena):
    cestino.dischi[cestino.disco][1] = None


def _spento(cestino, scena):
    cestino.spento = True


def _senza_massimo(cestino, scena):
    cestino.massimo = None


def _piccolo(cestino, scena):
    cestino.massimo = int(PESO / modulo.MARGINE) - 1


def _pieno(cestino, scena):
    cestino.in_piu = int(cestino.massimo * modulo.MARGINE) - PESO + 1


def _sensore(giorni):
    def accendi(cestino, scena):
        cestino.giorni = giorni
    accendi.__name__ = f"_sensore_{giorni}"
    return accendi


def _guasto(quale):
    def guasta(cestino, scena):
        cestino.guasto = quale
    guasta.__name__ = f"_guasto_{quale}"
    return guasta


def _fuori_dal_disco(cestino, scena):
    cestino.dischi = {os.fspath(scena.base / "altro"): [FISSO, "NTFS"]}
    cestino.disco = os.fspath(scena.base / "altro")


def _percorso_lungo(cestino, scena):
    modulo.LUNGO = len(os.fspath(scena.via.qui("s/sotto/doppio.jpg"))) - 1


@pytest.mark.parametrize("guaio, codice", [
    (_chiavetta, "non_nel_cestino_chiavetta"),
    (_rete, "disco_di_rete"),
    (_strano, "disco_strano"),
    (_fat, "sistema_strano"),
    (_exfat, "sistema_strano"),
    (_senza_sistema, "sistema_strano"),
    (_spento, "cestino_spento"),
    (_senza_massimo, "cestino_sconosciuto"),
    (_piccolo, "troppo_grande"),
    (_pieno, "cestino_pieno"),
    (_sensore(1), "sensore_memoria"),
    (_sensore(30), "sensore_memoria"),
    (_guasto("pulizia"), "cestino_sconosciuto"),
    (_guasto("usato"), "cestino_sconosciuto"),
    (_guasto("cartella"), "cestino_sconosciuto"),
    (_guasto("capienza"), "cestino_sconosciuto"),
    (_guasto("volume"), "cestino_sconosciuto"),
    (_fuori_dal_disco, "disco_strano"),
    (_percorso_lungo, "percorso_lungo"),
])
def test_dove_il_cestino_non_e_sicuro_non_si_tocca(tmp_path, chiave, monkeypatch, guaio,
                                                    codice):
    monkeypatch.setattr(modulo, "LUNGO", modulo.LUNGO)
    scena = Scena(tmp_path, chiave)
    esame = scena.esame()
    guaio(scena.cestino, scena)
    riepilogo = scena.spedizioniere.riepilogo([esame])
    assert [fuori["codice"] for fuori in riepilogo["fuori"]] == [codice]
    assert not riepilogo["si_puo"]
    risultato, = scena.spedizioniere.manda([esame], "CANCELLA")
    assert risultato["esito"] == NON_TOCCATA and risultato["codice"] == codice
    assert risultato["messaggio"] == modulo.PROBLEMI[codice]
    assert scena.cestino.mosse == [] and scena.via.qui("s/a.jpg").exists()
    assert scena.quaderno.spedizioni() == []


@pytest.mark.parametrize("sistema", ["NTFS", "ntfs", "ReFS", "REFS"])
def test_ntfs_e_refs_vanno_bene(tmp_path, chiave, sistema):
    scena = Scena(tmp_path, chiave)
    scena.cestino.dischi[scena.cestino.disco][1] = sistema
    assert scena.manda()[0]["esito"] == NEL_CESTINO


@pytest.mark.parametrize("in_piu, esito", [(7 * PESO - 10, NEL_CESTINO),
                                           (7 * PESO + 10, NON_TOCCATA)])
def test_il_cestino_si_riempie_solo_fino_all_ottanta_per_cento(tmp_path, chiave, in_piu,
                                                              esito):
    scena = Scena(tmp_path, chiave)
    scena.cestino.massimo = 10 * PESO
    scena.cestino.in_piu = in_piu
    assert scena.manda()[0]["esito"] == esito


@pytest.mark.parametrize("massimo, esito", [(PESO * 5 // 4 + 10, NEL_CESTINO),
                                            (PESO * 5 // 4 - 10, NON_TOCCATA)])
def test_una_cartella_sola_non_supera_l_ottanta_per_cento(tmp_path, chiave, massimo, esito):
    scena = Scena(tmp_path, chiave)
    scena.cestino.massimo = massimo
    assert scena.manda()[0]["esito"] == esito


def test_al_limite_del_margine_va_ancora(tmp_path, chiave):
    scena = Scena(tmp_path, chiave)
    scena.cestino.massimo = 1000 * PESO
    scena.cestino.in_piu = int(scena.cestino.massimo * modulo.MARGINE) - PESO
    assert scena.manda()[0]["esito"] == NEL_CESTINO


def test_un_pezzo_su_un_altro_disco_non_si_tocca(tmp_path, chiave):
    scena = Scena(tmp_path, chiave, foto={"s/a.jpg": b"a", "t/b.jpg": b"b"}, cartelle=())
    scena.cestino.dischi[os.fspath(scena.via.qui("t"))] = [FISSO, "NTFS"]
    esame = scena.spedizioniere.esaminatore.esamina(scena.via.foto)
    assert esame.solo_dentro
    risultato, = scena.spedizioniere.manda([esame], "CANCELLA")
    assert risultato["codice"] == "disco_strano" and scena.cestino.mosse == []


@su_linux
def test_un_nome_che_finisce_col_punto_non_si_tocca(tmp_path, chiave):
    scena = Scena(tmp_path, chiave, foto={"punto./a.jpg": b"a"}, cartelle=())
    risultato, = scena.manda("punto.")
    assert risultato["codice"] == "percorso_strano" and scena.cestino.mosse == []


@su_linux
@pytest.mark.parametrize("strano", ["s/sotto /a.jpg", "s/sotto./a.jpg", "s/a.jpg ",
                                    "s/a.", "s/x/y /z.jpg"])
@pytest.mark.parametrize("tutta", [False, True])
def test_un_nome_dentro_che_finisce_con_lo_spazio_non_si_tocca(tmp_path, chiave, strano,
                                                               tutta):
    scena = Scena(tmp_path, chiave, foto={strano: b"a", "s/b.jpg": b"b"}, cartelle=())
    cartella = scena.via.foto if tutta else scena.via.qui("s")
    esame = scena.spedizioniere.esaminatore.esamina(cartella)
    assert esame.verde
    assert scena.spedizioniere.riepilogo([esame])["fuori"][0]["codice"] == "percorso_strano"
    risultato, = scena.spedizioniere.manda([esame], "CANCELLA")
    assert risultato["codice"] == "percorso_strano"
    assert scena.cestino.mosse == [] and scena.via.qui(strano).exists()


def test_senza_cestino_di_windows_non_si_tocca(tmp_path, chiave):
    scena = Scena(tmp_path, chiave, cestino=CestinoAssente())
    risultato, = scena.manda()
    assert risultato["codice"] == "senza_cestino"
    assert scena.via.qui("s/a.jpg").exists()
    assert CestinoAssente().butta(os.fspath(scena.via.qui("s"))) == Mossa(
        False, None, "senza_cestino")
    assert scena.via.qui("s/a.jpg").exists()


@su_linux
def test_fuori_da_windows_il_cestino_non_c_e():
    assert isinstance(cestino_di_sistema(), CestinoAssente)


def test_se_windows_dice_di_no_resta_tutto_al_suo_posto(tmp_path, chiave):
    scena = Scena(tmp_path, chiave)
    esame = scena.esame()
    scena.cestino.ricicla = False
    risultato, = scena.spedizioniere.manda([esame], "CANCELLA")
    assert risultato["esito"] == NON_PARTITA and risultato["codice"] == NON_PARTITA
    assert risultato["messaggio"] == ("Windows non l'ha mandata nel Cestino: è rimasta al "
                                      "suo posto.")
    assert _albero(scena.via.qui("s")) == DENTRO_S and scena.cestino.roba() == []
    spedizione = scena.quaderno.spedizione(risultato["spedizione"])
    assert spedizione["voci"][0]["esito"] == NON_PARTITA and spedizione["custodita"]
    assert not any(scena.custoditi(esame.dove_posti))


@pytest.mark.parametrize("modo", ["rifiuta", "eccezione_prima"])
def test_se_non_parte_resta_tutto(tmp_path, chiave, modo):
    scena = Scena(tmp_path, chiave)
    scena.cestino.modo = modo
    esame = scena.esame()
    assert scena.spedizioniere.manda([esame], "CANCELLA")[0]["esito"] == NON_PARTITA
    assert _albero(scena.via.qui("s")) == DENTRO_S
    assert not any(scena.custoditi(esame.dove_posti))
    scena.cestino.modo = "bene"
    assert scena.spedizioniere.manda([esame], "CANCELLA")[0]["esito"] == NEL_CESTINO


@pytest.mark.parametrize("modo", ["per_sempre", "senza_info", "altrove"])
def test_se_non_si_ritrova_nel_cestino_e_da_guardare(tmp_path, chiave, modo):
    scena = Scena(tmp_path, chiave)
    scena.cestino.modo = modo
    esame = scena.esame()
    risultato, = scena.spedizioniere.manda([esame], "CANCELLA")
    assert risultato["esito"] == DA_GUARDARE and risultato["codice"] == DA_GUARDARE
    assert risultato["file"] == 0 and risultato["nel_cestino"] == 0
    assert _voce(scena, risultato)["esito"] == PERSA
    assert not any(scena.custoditi(esame.dove_posti))
    scena.via.banco.giro()
    for nome, dati in FOTO.items():
        numero = scena.via.banco.elenco.posto(esame_chiave(esame, nome)).contenuto
        assert scena.via.banco.dati(numero) == dati


def esame_chiave(esame, nome: str) -> str:
    relativo = nome[2:]
    return next(chiave for chiave, dove in esame.dove_posti.items() if dove == relativo)


def test_se_ne_va_solo_un_pezzo_e_da_guardare(tmp_path, chiave):
    scena = Scena(tmp_path, chiave)
    scena.cestino.modo = "a_meta"
    esame = scena.esame()
    risultato, = scena.spedizioniere.manda([esame], "CANCELLA")
    assert risultato["esito"] == DA_GUARDARE
    assert _voce(scena, risultato)["esito"] == A_META
    assert not scena.via.qui("s/a.jpg").exists() and scena.via.qui("s/b.jpg").exists()
    assert not any(scena.custoditi(esame.dove_posti))


@pytest.mark.parametrize("modo", ["bugiardo", "eccezione"])
def test_se_windows_si_sbaglia_a_dire_si_guarda_lo_stesso(tmp_path, chiave, modo):
    scena = Scena(tmp_path, chiave)
    scena.cestino.modo = modo
    esame = scena.esame()
    risultato, = scena.spedizioniere.manda([esame], "CANCELLA")
    assert risultato["esito"] == NEL_CESTINO
    assert _albero(_voce(scena, risultato)["dove"]) == DENTRO_S
    assert all(scena.custoditi(esame.dove_posti))


def test_se_windows_dice_il_posto_sbagliato_si_cerca(tmp_path, chiave):
    scena = Scena(tmp_path, chiave)
    scena.cestino.dice = os.path.join(scena.cestino.dentro, "$RSBAGLI")
    risultato, = scena.manda()
    assert risultato["esito"] == NEL_CESTINO
    assert _voce(scena, risultato)["dove"] != scena.cestino.dice


def test_se_windows_dice_un_altro_buttato_si_cerca_il_nostro(tmp_path, chiave):
    scena = Scena(tmp_path, chiave)
    scena.via.base.joinpath("altra").mkdir()
    altro = scena.cestino.a_mano(scena.via.base / "altra")
    scena.cestino.dice = altro
    risultato, = scena.manda()
    assert risultato["esito"] == NEL_CESTINO
    assert _voce(scena, risultato)["dove"] != altro


def _cambia_nel_cestino(dati):
    Path(dati, "a.jpg").write_bytes(b"cambiata")


def _aggiunge_nel_cestino(dati):
    Path(dati, "intrusa.jpg").write_bytes(b"intrusa")


def _toglie_nel_cestino(dati):
    Path(dati, "sotto", "c.jpg").unlink()


def _uguale_nel_cestino(dati):
    _scrivi_uguale(Path(dati, "b.jpg"), b"\xff")


def _di_nascosto(cartella, fare) -> None:
    stato = os.stat(cartella)
    fare()
    os.utime(cartella, ns=(stato.st_atime_ns, stato.st_mtime_ns))


def _aggiunge_di_nascosto(dati):
    _di_nascosto(dati, lambda: _aggiunge_nel_cestino(dati))


def _toglie_di_nascosto(dati):
    _di_nascosto(Path(dati, "sotto"), lambda: _toglie_nel_cestino(dati))


@pytest.mark.parametrize("dopo", [_cambia_nel_cestino, _aggiunge_nel_cestino,
                                  _toglie_nel_cestino, _uguale_nel_cestino,
                                  _aggiunge_di_nascosto, _toglie_di_nascosto])
def test_se_nel_cestino_non_e_uguale_e_da_guardare(tmp_path, chiave, dopo):
    scena = Scena(tmp_path, chiave)
    scena.cestino.dopo = dopo
    esame = scena.esame()
    risultato, = scena.spedizioniere.manda([esame], "CANCELLA")
    assert risultato["esito"] == DA_GUARDARE
    assert _voce(scena, risultato)["esito"] == DIVERSA
    assert not any(scena.custoditi(esame.dove_posti))


def test_un_file_in_cima_cambiato_nel_cestino_e_diverso(tmp_path, chiave):
    scena = Scena(tmp_path, chiave, foto={"c.jpg": b"ccc"}, cartelle=())

    def dopo(dati):
        if os.fspath(dati).endswith(".jpg"):
            Path(dati).write_bytes(b"zzzz")

    scena.cestino.dopo = dopo
    esame = scena.spedizioniere.esaminatore.esamina(scena.via.foto)
    risultato, = scena.spedizioniere.manda([esame], "CANCELLA")
    assert risultato["esito"] == DA_GUARDARE
    assert _voce(scena, risultato)["esito"] == DIVERSA


def test_una_cartella_toccata_nel_cestino_e_diversa(tmp_path, chiave):
    scena = Scena(tmp_path, chiave)
    scena.cestino.dopo = lambda dati: os.utime(dati, ns=(0, 12345))
    risultato, = scena.manda()
    assert risultato["esito"] == DA_GUARDARE
    assert _voce(scena, risultato)["esito"] == DIVERSA


def test_il_confronto_vuole_tutto_e_solo_quello_della_lista(tmp_path, chiave):
    scena = Scena(tmp_path, chiave)
    esame = scena.esame()
    cartella = os.fspath(scena.via.qui("s"))
    uguale = scena.spedizioniere._uguale
    impronte = modulo._della_voce(esame.impronta, "")
    assert uguale(cartella, impronte)
    assert not uguale(cartella, {**impronte, "fantasma.jpg": list(impronte["a.jpg"])})
    assert not uguale(cartella, {**impronte, "sotto/fantasma": list(impronte["sotto"])})
    assert not uguale(cartella, {chiave: valore for chiave, valore in impronte.items()
                                 if chiave != "sotto/c.jpg"})
    assert not uguale(cartella, {chiave: valore for chiave, valore in impronte.items()
                                 if chiave != ""})
    assert not uguale(os.fspath(scena.via.qui("non_c_e")), impronte)


def test_un_file_arrivato_all_ultimo_momento_fa_diversa(tmp_path, chiave):
    scena = Scena(tmp_path, chiave)
    scena.cestino.prima = lambda percorso: Path(percorso, "ultima.jpg").write_bytes(b"u")
    esame = scena.esame()
    risultato, = scena.spedizioniere.manda([esame], "CANCELLA")
    assert risultato["esito"] == DA_GUARDARE
    assert _voce(scena, risultato)["esito"] == DIVERSA
    assert not any(scena.custoditi(esame.dove_posti))


def test_un_crollo_prima_di_spostare_si_riprende(tmp_path, chiave):
    scena = Scena(tmp_path, chiave)
    scena.cestino.modo = "crollo_prima"
    esame = scena.esame()
    with pytest.raises(Crollo):
        scena.spedizioniere.manda([esame], "CANCELLA")
    spedizione, = Quaderno(scena.via.banco.archivio, chiave).spedizioni()
    assert spedizione["voci"][0]["esito"] == IN_PARTENZA
    spedizioniere = scena.riapri()
    assert spedizioniere.riprendi() == [spedizione["id"]]
    ripresa = scena.quaderno.spedizione(spedizione["id"])
    assert ripresa["voci"][0]["esito"] == NON_PARTITA and ripresa["custodita"]
    assert _albero(scena.via.qui("s")) == DENTRO_S
    assert not any(scena.custoditi(esame.dove_posti))
    assert spedizioniere.riprendi() == []


def test_un_crollo_dopo_lo_spostamento_si_riprende(tmp_path, chiave):
    scena = Scena(tmp_path, chiave)
    scena.cestino.modo = "crollo_dopo"
    esame = scena.esame()
    with pytest.raises(Crollo):
        scena.spedizioniere.manda([esame], "CANCELLA")
    assert not any(scena.custoditi(esame.dove_posti))
    spedizioniere = scena.riapri()
    id, = spedizioniere.riprendi()
    spedizione = scena.quaderno.spedizione(id)
    assert spedizione["voci"][0]["esito"] == NEL_CESTINO and spedizione["custodita"]
    assert _albero(spedizione["voci"][0]["dove"]) == DENTRO_S
    assert all(scena.custoditi(esame.dove_posti))


def test_la_mandata_dopo_un_crollo_prima_riprende(tmp_path, chiave):
    scena = Scena(tmp_path, chiave, foto=DUE, cartelle=DUE_VUOTE)
    scena.cestino.modo = "crollo_dopo"
    esame = scena.esame("s")
    with pytest.raises(Crollo):
        scena.spedizioniere.manda([esame], "CANCELLA")
    scena.riapri()
    scena.cestino.modo = "bene"
    assert scena.manda("t")[0]["esito"] == NEL_CESTINO
    assert all(scena.custoditi(esame.dove_posti))
    assert all(voce["esito"] == NEL_CESTINO for spedizione in scena.quaderno.spedizioni()
               for voce in spedizione["voci"])


def test_un_crollo_mentre_si_segna_custodito_si_riprende(tmp_path, chiave, monkeypatch):
    scena = Scena(tmp_path, chiave)
    esame = scena.esame()
    vero = scena.via.banco.elenco.registra

    def crolla(fatti):
        raise Crollo

    monkeypatch.setattr(scena.via.banco.elenco, "registra", crolla)
    with pytest.raises(Crollo):
        scena.spedizioniere.manda([esame], "CANCELLA")
    monkeypatch.setattr(scena.via.banco.elenco, "registra", vero)
    spedizione, = scena.quaderno.spedizioni()
    assert spedizione["voci"][0]["esito"] == NEL_CESTINO and not spedizione["custodita"]
    scena.riapri().riprendi()
    assert scena.quaderno.spedizione(spedizione["id"])["custodita"]
    assert all(scena.custoditi(esame.dove_posti))


def test_senza_lista_dopo_un_crollo_e_da_guardare(tmp_path, chiave):
    scena = Scena(tmp_path, chiave)
    scena.cestino.modo = "crollo_dopo"
    esame = scena.esame()
    with pytest.raises(Crollo):
        scena.spedizioniere.manda([esame], "CANCELLA")
    shutil.rmtree(scena.via.banco.archivio / LISTE)
    spedizioniere = scena.riapri()
    id, = spedizioniere.riprendi()
    spedizione = scena.quaderno.spedizione(id)
    assert spedizione["voci"][0]["esito"] == DIVERSA and not spedizione["custodita"]
    assert not any(scena.custoditi(esame.dove_posti))


def test_se_non_si_capisce_dove_e_finita_si_riprova_dopo(tmp_path, chiave, monkeypatch):
    scena = Scena(tmp_path, chiave)
    esame = scena.esame()
    vero = scena.cestino.trova

    def guasto(*argomenti, **opzioni):
        raise OSError(errno.EIO, "cestino")

    monkeypatch.setattr(scena.cestino, "trova", guasto)
    risultato, = scena.spedizioniere.manda([esame], "CANCELLA")
    assert risultato["esito"] == IN_PARTENZA
    assert not any(scena.custoditi(esame.dove_posti))
    monkeypatch.setattr(scena.cestino, "trova", vero)
    id, = scena.spedizioniere.riprendi()
    assert scena.quaderno.spedizione(id)["voci"][0]["esito"] == NEL_CESTINO
    assert all(scena.custoditi(esame.dove_posti))


def _scrittura_che_si_rompe(monkeypatch):
    rotto = {"si": False}
    vero = modulo.scrivi_tutto

    def scrivi(percorso, dati):
        if rotto["si"]:
            raise OSError(errno.EIO, "disco")
        return vero(percorso, dati)

    monkeypatch.setattr(modulo, "scrivi_tutto", scrivi)
    return rotto


def test_se_il_quaderno_non_si_scrive_dopo_lo_spostamento_si_dice_il_vero(
        tmp_path, chiave, monkeypatch):
    scena = Scena(tmp_path, chiave, foto=DUE, cartelle=DUE_VUOTE)
    rotto = _scrittura_che_si_rompe(monkeypatch)
    scena.cestino.dopo = lambda dati: rotto.update(si=True)
    esami = [scena.esame("s"), scena.esame("t")]
    primo, secondo = scena.spedizioniere.manda(esami, "CANCELLA")
    assert primo["esito"] == NEL_CESTINO and primo["codice"] == "quaderno_non_salvato"
    assert primo["messaggio"].startswith("È nel Cestino di Windows")
    assert "le altre cartelle non le tocco" in primo["messaggio"]
    assert "non tocco niente" not in primo["messaggio"]
    assert secondo["esito"] == NON_TOCCATA and secondo["codice"] == "quaderno_non_salvato"
    assert scena.via.qui("t/a.jpg").exists() and len(scena.cestino.mosse) == 1
    assert not any(scena.custoditi(esami[0].dove_posti))
    rotto["si"] = False
    id, = scena.riapri().riprendi()
    assert scena.quaderno.spedizione(id)["voci"][0]["esito"] == NEL_CESTINO
    assert all(scena.custoditi(esami[0].dove_posti))


def test_se_il_quaderno_non_si_scrive_prima_non_parte_niente(tmp_path, chiave, monkeypatch):
    scena = Scena(tmp_path, chiave)
    rotto = _scrittura_che_si_rompe(monkeypatch)
    esame = scena.esame()
    rotto["si"] = True
    risultato, = scena.spedizioniere.manda([esame], "CANCELLA")
    assert risultato["esito"] == NON_TOCCATA
    assert risultato["codice"] == "quaderno_non_salvato"
    assert scena.cestino.mosse == [] and scena.quaderno.spedizioni() == []


def test_dopo_un_errore_di_tutto_ci_si_ferma_anche_se_poi_passa(tmp_path, chiave,
                                                                monkeypatch):
    scena = Scena(tmp_path, chiave, foto=DUE, cartelle=DUE_VUOTE)
    esami = [scena.esame("s"), scena.esame("t")]
    vera = scena.quaderno.scrivi_lista
    volte = []

    def una_volta(id, lista):
        volte.append(id)
        if len(volte) == 1:
            raise ErroreOfficina("disco", codice="quaderno_non_salvato")
        return vera(id, lista)

    monkeypatch.setattr(scena.quaderno, "scrivi_lista", una_volta)
    primo, secondo = scena.spedizioniere.manda(esami, "CANCELLA")
    assert primo["codice"] == secondo["codice"] == "quaderno_non_salvato"
    assert primo["esito"] == secondo["esito"] == NON_TOCCATA
    assert scena.cestino.mosse == [] and len(volte) == 1


def test_se_l_elenco_non_si_scrive_si_riprende(tmp_path, chiave, monkeypatch):
    scena = Scena(tmp_path, chiave, foto=DUE, cartelle=DUE_VUOTE)
    esami = [scena.esame("s"), scena.esame("t")]
    vero = scena.via.banco.elenco.registra

    def guasto(fatti):
        raise OSError(errno.EIO, "elenco")

    monkeypatch.setattr(scena.via.banco.elenco, "registra", guasto)
    primo, secondo = scena.spedizioniere.manda(esami, "CANCELLA")
    assert primo["esito"] == NEL_CESTINO and primo["codice"] == "quaderno_non_salvato"
    assert secondo["esito"] == NON_TOCCATA
    monkeypatch.setattr(scena.via.banco.elenco, "registra", vero)
    scena.spedizioniere.riprendi()
    assert all(scena.custoditi(esami[0].dove_posti))


def test_mentre_si_manda_non_si_fa_altro_sul_cestino(tmp_path, chiave):
    scena = Scena(tmp_path, chiave)
    spedizioniere = scena.spedizioniere
    codici = []

    def prima(percorso):
        codici.append(_codice(spedizioniere.riprendi))
        codici.append(_codice(lambda: spedizioniere.manda([], "CANCELLA")))
        codici.append(_codice(lambda: spedizioniere.ricontrolla("0" * 16)))

    scena.cestino.prima = prima
    assert scena.manda()[0]["esito"] == NEL_CESTINO
    assert codici == ["occupato"] * 3


def test_se_l_archivio_lavora_non_si_manda(tmp_path, chiave):
    scena = Scena(tmp_path, chiave, occupato=lambda: True)
    assert _codice(scena.manda) == "occupato"
    assert scena.cestino.mosse == []


def test_se_l_archivio_si_mette_a_lavorare_le_altre_aspettano(tmp_path, chiave):
    occupato = [False]
    scena = Scena(tmp_path, chiave, foto=DUE, cartelle=DUE_VUOTE,
                  occupato=lambda: occupato[0])
    scena.cestino.dopo = lambda dati: occupato.__setitem__(0, True)
    primo, secondo = scena.manda("s", "t")
    assert primo["esito"] == NEL_CESTINO
    assert secondo["esito"] == NON_TOCCATA and secondo["codice"] == "occupato"
    assert scena.via.qui("t/a.jpg").exists()


def test_il_turno_tiene_fermi_gli_altri_lavori(tmp_path, chiave):
    fatti = []

    @contextlib.contextmanager
    def turno():
        fatti.append("entra")
        yield
        fatti.append("esce")

    scena = Scena(tmp_path, chiave, turno=turno)
    scena.cestino.prima = lambda percorso: fatti.append("sposta")
    scena.manda()
    assert fatti == ["entra", "sposta", "esce"]
    scena.via.prova.orologio.ora += ATTESA
    id = scena.quaderno.spedizioni()[0]["id"]
    fatti.clear()
    scena.spedizioniere.ricontrolla(id)
    assert fatti == ["entra", "esce"]


def test_tutta_la_cartella_delle_foto_va_un_pezzo_alla_volta(tmp_path, chiave):
    foto = {"s/a.jpg": b"a", "t/b.jpg": b"bb", "c.jpg": b"ccc", "desktop.ini": b"ini"}
    scena = Scena(tmp_path, chiave, foto=foto, cartelle=())
    collegamento = scena.via.foto / "scorciatoia"
    if os.name != "nt":
        collegamento.symlink_to("c.jpg")
    scena.via.copia()
    esame = scena.spedizioniere.esaminatore.esamina(scena.via.foto)
    assert esame.solo_dentro and esame.verde
    riepilogo = scena.spedizioniere.riepilogo([esame])
    assert riepilogo["file"] == 3 and riepilogo["byte"] == 6
    risultato, = scena.spedizioniere.manda([esame], "CANCELLA")
    assert risultato["esito"] == NEL_CESTINO and risultato["nel_cestino"] == 3
    assert risultato["file"] == 3 and risultato["byte"] == 6
    rimasti = sorted(os.listdir(scena.via.foto))
    attesi = ["desktop.ini"] if os.name == "nt" else ["desktop.ini", "scorciatoia"]
    assert rimasti == attesi
    spedizione = scena.quaderno.spedizione(risultato["spedizione"])
    assert [voce["relativo"] for voce in spedizione["voci"]] == ["c.jpg", "s", "t"]
    assert len(scena.cestino.mosse) == 3
    elenco = scena.via.banco.elenco
    for relativo in ("c.jpg", "s", "s/a.jpg", "t", "t/b.jpg"):
        assert CUSTODITO in elenco.attuale("r1", relativo).segni
    assert CUSTODITO not in elenco.attuale("r1", "desktop.ini").segni
    radice = elenco.attuale("r1", "")
    assert radice is None or CUSTODITO not in radice.segni


def test_una_cartella_delle_foto_con_solo_desktop_ini_e_vuota(tmp_path, chiave):
    scena = Scena(tmp_path, chiave, foto={"desktop.ini": b"ini"}, cartelle=())
    esame = scena.spedizioniere.esaminatore.esamina(scena.via.foto)
    risultato, = scena.spedizioniere.manda([esame], "CANCELLA")
    assert risultato["codice"] == "vuota" and scena.cestino.mosse == []


def test_il_quaderno_e_cifrato_e_non_ha_nomi(tmp_path, chiave):
    scena = Scena(tmp_path, chiave)
    scena.manda()
    archivio = scena.via.banco.archivio
    file = [archivio / QUADERNO, archivio / RISERVA, *(archivio / LISTE).iterdir()]
    assert len(file) == 4
    for percorso in file:
        grezzi = percorso.read_bytes()
        for nome in ("foto", "a.jpg", "sotto", "vuota", os.fspath(tmp_path)):
            for forma in (nome.encode(), nome.encode("utf-16-le")):
                assert forma not in grezzi


def test_il_quaderno_si_rilegge_uguale(tmp_path, chiave):
    scena = Scena(tmp_path, chiave)
    scena.manda()
    altro = Quaderno(scena.via.banco.archivio, chiave)
    assert altro.problemi == []
    assert altro.spedizioni() == scena.quaderno.spedizioni()
    assert altro.numero == scena.quaderno.numero and altro.collaudo == FATTO


@pytest.mark.parametrize("quale", [QUADERNO, RISERVA])
def test_un_quaderno_rovinato_si_riprende_dall_altro(tmp_path, chiave, quale):
    scena = Scena(tmp_path, chiave)
    scena.manda()
    percorso = scena.via.banco.archivio / quale
    grezzi = bytearray(percorso.read_bytes())
    grezzi[len(grezzi) // 2] ^= 0x01
    percorso.write_bytes(bytes(grezzi))
    altro = Quaderno(scena.via.banco.archivio, chiave)
    assert altro.problemi == [] and altro.spedizioni() == scena.quaderno.spedizioni()


@pytest.mark.parametrize("quale", [QUADERNO, RISERVA])
def test_un_quaderno_che_manca_si_riprende_dall_altro(tmp_path, chiave, quale):
    scena = Scena(tmp_path, chiave)
    scena.manda()
    (scena.via.banco.archivio / quale).unlink()
    altro = Quaderno(scena.via.banco.archivio, chiave)
    assert altro.problemi == [] and altro.spedizioni() == scena.quaderno.spedizioni()


def test_dei_due_quaderni_vince_il_piu_nuovo(tmp_path, chiave):
    scena = Scena(tmp_path, chiave)
    archivio = scena.via.banco.archivio
    vecchio = (archivio / QUADERNO).read_bytes()
    scena.manda()
    (archivio / RISERVA).write_bytes(vecchio)
    altro = Quaderno(archivio, chiave)
    assert altro.spedizioni() == scena.quaderno.spedizioni() != []
    (archivio / QUADERNO).write_bytes(vecchio)
    (archivio / RISERVA).write_bytes(vecchio)
    assert Quaderno(archivio, chiave).spedizioni() == []


def test_senza_quaderno_si_comincia_da_zero(tmp_path, chiave):
    scena = Scena(tmp_path, chiave, prova_fatta=False)
    assert scena.quaderno.problemi == [] and scena.quaderno.numero == 0
    assert scena.quaderno.collaudo == DA_FARE and scena.quaderno.spedizioni() == []
    assert not (scena.via.banco.archivio / QUADERNO).exists()


def _rovina_tutti_e_due(archivio: Path) -> None:
    for nome in (QUADERNO, RISERVA):
        grezzi = bytearray((archivio / nome).read_bytes())
        grezzi[-1] ^= 0x01
        (archivio / nome).write_bytes(bytes(grezzi))


def test_due_quaderni_rovinati_fermano_tutto_finche_non_si_ricomincia(tmp_path, chiave):
    scena = Scena(tmp_path, chiave, foto=DUE, cartelle=DUE_VUOTE)
    scena.manda("s")
    _rovina_tutti_e_due(scena.via.banco.archivio)
    spedizioniere = scena.riapri()
    assert scena.quaderno.problemi == ["quaderno_rovinato"]
    esame = scena.esame("t")
    assert not spedizioniere.riepilogo([esame])["si_puo"]
    assert _codice(lambda: spedizioniere.manda([esame], "CANCELLA")) == "quaderno_rovinato"
    assert spedizioniere.riprendi() == []
    assert scena.via.qui("t/a.jpg").exists() and len(scena.cestino.mosse) == 1
    scena.quaderno.ricomincia()
    assert scena.quaderno.problemi == [] and scena.quaderno.spedizioni() == []
    assert Quaderno(scena.via.banco.archivio, chiave).problemi == []
    assert scena.quaderno.collaudo == DA_FARE


def test_un_quaderno_sparito_con_le_liste_ferma_tutto(tmp_path, chiave):
    scena = Scena(tmp_path, chiave)
    scena.manda()
    archivio = scena.via.banco.archivio
    (archivio / QUADERNO).unlink()
    (archivio / RISERVA).unlink()
    spedizioniere = scena.riapri()
    assert scena.quaderno.problemi == ["quaderno_rovinato"]
    assert _codice(lambda: spedizioniere.manda([], "CANCELLA")) == "quaderno_rovinato"
    scena.quaderno.ricomincia()
    assert Quaderno(archivio, chiave).problemi == []


def test_un_quaderno_mai_scritto_senza_liste_va_bene(tmp_path, chiave):
    scena = Scena(tmp_path, chiave, prova_fatta=False)
    archivio = scena.via.banco.archivio
    (archivio / LISTE).mkdir()
    (archivio / LISTE / "altro.txt").write_bytes(b"x")
    assert Quaderno(archivio, chiave).problemi == []


def test_se_le_liste_non_si_leggono_il_quaderno_e_illeggibile(tmp_path, chiave, monkeypatch):
    scena = Scena(tmp_path, chiave, prova_fatta=False)
    archivio = scena.via.banco.archivio
    (archivio / LISTE).mkdir()
    vero = modulo.os.scandir

    def scandir(percorso):
        if os.fspath(percorso).endswith(LISTE):
            raise PermissionError(errno.EACCES, "liste")
        return vero(percorso)

    monkeypatch.setattr(modulo.os, "scandir", scandir)
    assert Quaderno(archivio, chiave).problemi == ["quaderno_illeggibile"]


def test_un_quaderno_illeggibile_non_si_ricomincia(tmp_path, chiave):
    scena = Scena(tmp_path, chiave)
    scena.manda()
    archivio = scena.via.banco.archivio
    (archivio / RISERVA).unlink()
    salvato = (archivio / QUADERNO).read_bytes()
    (archivio / QUADERNO).unlink()
    (archivio / QUADERNO).mkdir()
    quaderno = Quaderno(archivio, chiave)
    assert quaderno.problemi == ["quaderno_illeggibile"]
    assert _codice(quaderno.ricomincia) == "quaderno_illeggibile"
    assert _codice(lambda: quaderno.metti_collaudo(FATTO)) == "quaderno_illeggibile"
    assert (archivio / QUADERNO).is_dir() and not (archivio / RISERVA).exists()
    (archivio / QUADERNO).rmdir()
    (archivio / QUADERNO).write_bytes(salvato)
    quaderno.ricomincia()
    assert quaderno.problemi == [] and len(quaderno.spedizioni()) == 1


def test_un_quaderno_piu_nuovo_non_si_tocca(tmp_path, chiave):
    scena = Scena(tmp_path, chiave)
    archivio = scena.via.banco.archivio
    testa = modulo._accompagnamento(TIPO_QUADERNO)
    for nome in (QUADERNO, RISERVA):
        grezzi = (archivio / nome).read_bytes()
        (archivio / nome).write_bytes(testa[:-1] + bytes([modulo.VERSIONE + 1])
                                      + grezzi[len(testa):])
    prima = {nome: (archivio / nome).read_bytes() for nome in (QUADERNO, RISERVA)}
    quaderno = Quaderno(archivio, chiave)
    assert quaderno.problemi == ["quaderno_piu_nuovo"]
    assert _codice(quaderno.ricomincia) == "quaderno_piu_nuovo"
    assert {nome: (archivio / nome).read_bytes() for nome in (QUADERNO, RISERVA)} == prima
    spedizioniere = scena.nuovo(quaderno=quaderno)
    assert _codice(lambda: spedizioniere.manda([scena.esame()], "CANCELLA")) == (
        "quaderno_piu_nuovo")


def test_un_quaderno_piu_nuovo_e_uno_buono_non_si_usa(tmp_path, chiave):
    scena = Scena(tmp_path, chiave)
    archivio = scena.via.banco.archivio
    testa = modulo._accompagnamento(TIPO_QUADERNO)
    grezzi = (archivio / QUADERNO).read_bytes()
    (archivio / QUADERNO).write_bytes(testa[:-1] + bytes([modulo.VERSIONE + 1])
                                      + grezzi[len(testa):])
    assert Quaderno(archivio, chiave).problemi == ["quaderno_piu_nuovo"]


def test_senza_archivio_il_quaderno_non_scrive(tmp_path, chiave):
    quaderno = Quaderno(tmp_path / "nessuno", chiave)
    assert quaderno.problemi == ["archivio_sparito"]
    assert _codice(lambda: quaderno.metti_collaudo(FATTO)) == "archivio_sparito"
    assert _codice(quaderno.ricomincia) == "archivio_sparito"
    assert not (tmp_path / "nessuno").exists()


def test_l_archivio_sparito_ferma_la_mandata(tmp_path, chiave):
    scena = Scena(tmp_path, chiave)
    esame = scena.esame()
    contenuti = scena.via.banco.archivio / CONTENUTI
    contenuti.rename(contenuti.with_name("via"))
    spedizioniere = scena.riapri()
    contenuti.with_name("via").rename(contenuti)
    assert _codice(lambda: spedizioniere.manda([esame], "CANCELLA")) == "archivio_sparito"
    assert scena.cestino.mosse == []


def test_con_un_altra_chiave_il_quaderno_e_rovinato(tmp_path, chiave):
    scena = Scena(tmp_path, chiave)
    altra = chiavi.Chiave(bytes(range(1, 33)))
    assert Quaderno(scena.via.banco.archivio, altra).problemi == ["quaderno_rovinato"]


def test_se_il_quaderno_non_si_scrive_resta_come_prima(tmp_path, chiave, monkeypatch):
    scena = Scena(tmp_path, chiave)
    numero = scena.quaderno.numero
    rotto = _scrittura_che_si_rompe(monkeypatch)
    rotto["si"] = True
    assert _codice(lambda: scena.quaderno.metti_collaudo(DA_FARE)) == "quaderno_non_salvato"
    assert scena.quaderno.numero == numero and scena.quaderno.collaudo == FATTO
    assert _codice(lambda: scena.quaderno.scrivi_lista("0" * 16, {"id": "0" * 16,
                                                                   "voci": []})) == (
        "quaderno_non_salvato")


@pytest.mark.parametrize("dati", [
    None, [], "x", {"numero": -1, "spedizioni": [], "collaudo": DA_FARE, "visti": {},
                    "allarmi": []},
    {"numero": 1, "spedizioni": [{"id": 1, "voci": []}], "collaudo": DA_FARE, "visti": {},
     "allarmi": []},
    {"numero": 1, "spedizioni": [], "collaudo": "boh", "visti": {}, "allarmi": []},
    {"numero": 1, "spedizioni": [], "collaudo": DA_FARE, "visti": {"c:": "x"},
     "allarmi": []},
    {"numero": 1, "spedizioni": [], "collaudo": DA_FARE, "visti": {},
     "allarmi": [{"stato": "boh"}]},
    {"numero": True, "spedizioni": [], "collaudo": DA_FARE, "visti": {}, "allarmi": []},
    {"numero": 1.5, "spedizioni": [], "collaudo": DA_FARE, "visti": {}, "allarmi": []},
])
def test_un_quaderno_strano_non_si_usa(tmp_path, chiave, dati):
    scena = Scena(tmp_path, chiave, prova_fatta=False)
    archivio = scena.via.banco.archivio
    for nome in (QUADERNO, RISERVA):
        (archivio / nome).write_bytes(modulo._cifra(chiave, TIPO_QUADERNO, dati))
    assert Quaderno(archivio, chiave).problemi == ["quaderno_rovinato"]


def test_una_lista_con_un_altro_numero_non_si_usa(tmp_path, chiave):
    scena = Scena(tmp_path, chiave)
    id = scena.manda()[0]["spedizione"]
    altro = "f" * 16 if id != "f" * 16 else "e" * 16
    cartella = scena.via.banco.archivio / LISTE
    shutil.copy(cartella / f"{id}.lista", cartella / f"{altro}.lista")
    assert scena.quaderno.leggi_lista(altro) is None
    assert scena.quaderno.leggi_lista(id) is not None


@pytest.mark.parametrize("id", ["", "x", "../" + "0" * 13, "0" * 15, "0" * 17, "A" * 16,
                                "0" * 15 + "/"])
def test_i_nomi_delle_liste_strani_non_si_usano(tmp_path, chiave, id):
    quaderno = Quaderno(tmp_path, chiave)
    with pytest.raises(ValueError):
        quaderno.leggi_lista(id)


def test_una_lista_rovinata_si_riprende_dalla_riserva(tmp_path, chiave):
    scena = Scena(tmp_path, chiave)
    id = scena.manda()[0]["spedizione"]
    lista = scena.quaderno.leggi_lista(id)
    percorso = scena.via.banco.archivio / LISTE / f"{id}.lista"
    grezzi = bytearray(percorso.read_bytes())
    grezzi[-3] ^= 0x10
    percorso.write_bytes(bytes(grezzi))
    assert scena.quaderno.leggi_lista(id) == lista


def _dopo_un_mese(scena: Scena, piu: float = 0.0) -> None:
    scena.via.prova.orologio.ora += ATTESA + piu


def test_il_ricontrollo_arriva_dopo_trenta_giorni(tmp_path, chiave):
    scena = Scena(tmp_path, chiave)
    id = scena.manda()[0]["spedizione"]
    spedizioniere = scena.spedizioniere
    assert spedizioniere.da_ricontrollare() == []
    _dopo_un_mese(scena, -1)
    assert spedizioniere.da_ricontrollare() == []
    scena.via.prova.orologio.ora += 1
    dovuta, = spedizioniere.da_ricontrollare()
    assert dovuta["id"] == id
    scena.via.banco.apri.aperti.clear()
    esito = spedizioniere.ricontrolla(id)
    assert esito["esito"] == SVUOTABILE and esito["codice"] is None
    assert esito["messaggio"].endswith("Puoi svuotare il Cestino.")
    aperti = {nome for nome, _ in scena.via.banco.apri.aperti}
    for nome in FOTO:
        assert os.fspath(scena.via.pc(nome)) in aperti
        assert os.fspath(scena.via.sopra(nome)) in aperti
    assert spedizioniere.da_ricontrollare() == []
    salvato = scena.quaderno.spedizione(id)["ricontrollo"]
    assert salvato["esito"] == SVUOTABILE and salvato["quando"] == scena.via.prova.orologio()
    json.dumps(esito)


def test_le_non_partite_non_si_ricontrollano(tmp_path, chiave):
    scena = Scena(tmp_path, chiave)
    scena.cestino.modo = "rifiuta"
    id = scena.manda()[0]["spedizione"]
    _dopo_un_mese(scena)
    assert scena.spedizioniere.da_ricontrollare() == []
    esito = scena.spedizioniere.ricontrolla(id)
    assert esito["esito"] == FINITA


@pytest.mark.parametrize("danno", ["pezzo", "tutto", "via"])
def test_una_copia_rovinata_nell_archivio_non_fa_svuotare(tmp_path, chiave, danno):
    scena = Scena(tmp_path, chiave)
    id = scena.manda()[0]["spedizione"]
    _dopo_un_mese(scena)
    numero = scena.via.numero("s/b.jpg")
    _danneggia(scena.via.prova, scena.via.pc("s/b.jpg"), numero, danno, random.Random(5))
    esito = scena.spedizioniere.ricontrolla(id)
    assert esito["esito"] == ASPETTA and esito["codice"] == "archivio_rovinato"
    assert esito["da_controllare"] == [numero]
    assert "Non svuotare il Cestino" in esito["messaggio"]
    assert [dovuta["id"] for dovuta in scena.spedizioniere.da_ricontrollare()] == [id]


@pytest.mark.parametrize("danno", ["pezzo", "tutto", "via"])
def test_una_copia_rovinata_sulla_chiavetta_non_fa_svuotare(tmp_path, chiave, danno):
    scena = Scena(tmp_path, chiave)
    id = scena.manda()[0]["spedizione"]
    _dopo_un_mese(scena)
    numero = scena.via.numero("s/b.jpg")
    _danneggia(scena.via.prova, scena.via.sopra("s/b.jpg"), numero, danno,
               random.Random(5))
    esito = scena.spedizioniere.ricontrolla(id)
    assert esito["esito"] == ASPETTA and esito["codice"] == "chiavetta_rovinata"
    assert esito["da_rileggere"] == [numero] and esito["da_controllare"] == []


def test_un_contenuto_segnato_rovinato_non_fa_svuotare(tmp_path, chiave, monkeypatch):
    scena = Scena(tmp_path, chiave)
    id = scena.manda()[0]["spedizione"]
    _dopo_un_mese(scena)
    numero = scena.via.numero("s/a.jpg")
    elenco = scena.via.banco.elenco
    vero = elenco.contenuto

    def contenuto(quale):
        informazioni = vero(quale)
        if quale == numero and informazioni is not None:
            informazioni = {**informazioni, "stato": "rovinato"}
        return informazioni

    monkeypatch.setattr(elenco, "contenuto", contenuto)
    esito = scena.spedizioniere.ricontrolla(id)
    assert esito["codice"] == "archivio_rovinato" and esito["da_controllare"] == [numero]


def test_senza_chiavetta_il_ricontrollo_aspetta(tmp_path, chiave):
    scena = Scena(tmp_path, chiave)
    id = scena.manda()[0]["spedizione"]
    _dopo_un_mese(scena)
    scena.via.prova.stacca()
    esito = scena.spedizioniere.ricontrolla(id)
    assert esito["esito"] == ASPETTA and esito["codice"] == "chiavetta_da_attaccare"
    scena.via.prova.riattacca()
    assert scena.spedizioniere.ricontrolla(id)["esito"] == SVUOTABILE


def test_se_la_chiavetta_si_stacca_durante_il_ricontrollo_aspetta(tmp_path, chiave):
    scena = Scena(tmp_path, chiave)
    id = scena.manda()[0]["spedizione"]
    _dopo_un_mese(scena)
    spedizioniere = scena.spedizioniere
    volte = []

    def aspetta():
        volte.append(1)
        if len(volte) == 3:
            scena.via.prova.stacca()

    spedizioniere.aspetta = aspetta
    esito = spedizioniere.ricontrolla(id)
    assert esito["esito"] == ASPETTA and esito["codice"] == ChiavettaStaccata.codice


def test_se_l_archivio_si_stacca_durante_il_ricontrollo_aspetta(tmp_path, chiave):
    scena = Scena(tmp_path, chiave)
    id = scena.manda()[0]["spedizione"]
    _dopo_un_mese(scena)
    contenuti = scena.via.banco.archivio / CONTENUTI
    volte = []

    def aspetta():
        volte.append(1)
        if len(volte) == 3:
            contenuti.rename(contenuti.with_name("via"))

    scena.spedizioniere.aspetta = aspetta
    esito = scena.spedizioniere.ricontrolla(id)
    assert esito["esito"] == ASPETTA and esito["codice"] == "archivio_sparito"


def _manca_sulla_chiavetta(riserva, tolto, monkeypatch):
    posto = riserva.elenco.posto
    monkeypatch.setattr(riserva.elenco, "posto",
                        lambda chiave: None if chiave == tolto else posto(chiave))


def _altro_sulla_chiavetta(riserva, tolto, monkeypatch):
    posto = riserva.elenco.posto

    def altro(chiave):
        trovato = posto(chiave)
        if chiave == tolto:
            return dataclasses.replace(trovato, contenuto="0" * len(trovato.contenuto))
        return trovato

    monkeypatch.setattr(riserva.elenco, "posto", altro)


def _flusso_sulla_chiavetta(riserva, tolto, monkeypatch):
    flussi = riserva.elenco.flussi_di

    def altri(chiave):
        trovati = list(flussi(chiave))
        if chiave == tolto:
            trovati.append(("nascosto", "0" * 32))
        return trovati

    monkeypatch.setattr(riserva.elenco, "flussi_di", altri)


@pytest.mark.parametrize("cambia", [_manca_sulla_chiavetta, _altro_sulla_chiavetta,
                                    _flusso_sulla_chiavetta])
def test_se_la_chiavetta_non_torna_con_l_archivio_il_ricontrollo_aspetta(
        tmp_path, chiave, monkeypatch, cambia):
    scena = Scena(tmp_path, chiave)
    esame = scena.esame()
    id = scena.spedizioniere.manda([esame], "CANCELLA")[0]["spedizione"]
    _dopo_un_mese(scena)
    esaminatore = scena.spedizioniere.esaminatore
    vera = esaminatore._prima
    tolto = esame_chiave(esame, "s/a.jpg")

    def prima():
        riserva = vera()
        cambia(riserva, tolto, monkeypatch)
        return riserva

    monkeypatch.setattr(esaminatore, "_prima", prima)
    esito = scena.spedizioniere.ricontrolla(id)
    assert esito["esito"] == ASPETTA and esito["codice"] == "chiavetta_da_aggiornare"
    monkeypatch.undo()
    assert scena.spedizioniere.ricontrolla(id)["esito"] == SVUOTABILE


def test_se_nell_archivio_manca_un_posto_il_ricontrollo_aspetta(tmp_path, chiave,
                                                               monkeypatch):
    scena = Scena(tmp_path, chiave)
    esame = scena.esame()
    id = scena.spedizioniere.manda([esame], "CANCELLA")[0]["spedizione"]
    _dopo_un_mese(scena)
    elenco = scena.via.banco.elenco
    posto = elenco.posto
    tolto = esame_chiave(esame, "s/a.jpg")
    monkeypatch.setattr(elenco, "posto",
                        lambda chiave: None if chiave == tolto else posto(chiave))
    esito = scena.spedizioniere.ricontrolla(id)
    assert esito["esito"] == ASPETTA and esito["codice"] == "archivio_cambiato"


def test_il_cestino_svuotato_finisce_il_ricontrollo(tmp_path, chiave):
    scena = Scena(tmp_path, chiave)
    risultato, = scena.manda()
    voce = _voce(scena, risultato)
    shutil.rmtree(voce["dove"])
    os.unlink(voce["info"])
    _dopo_un_mese(scena)
    esito = scena.spedizioniere.ricontrolla(risultato["spedizione"])
    assert esito["esito"] == FINITA
    assert _voce(scena, risultato)["esito"] == SVUOTATA
    assert scena.spedizioniere.da_ricontrollare() == []


def test_rimessa_al_suo_posto_finisce_il_ricontrollo(tmp_path, chiave):
    scena = Scena(tmp_path, chiave)
    esame = scena.esame()
    risultato, = scena.spedizioniere.manda([esame], "CANCELLA")
    voce = _voce(scena, risultato)
    os.rename(voce["dove"], esame.vero)
    os.unlink(voce["info"])
    esito = scena.spedizioniere.ricontrolla(risultato["spedizione"])
    assert esito["esito"] == FINITA and _voce(scena, risultato)["esito"] == TORNATA
    assert _albero(scena.via.qui("s")) == DENTRO_S


def test_spostata_dentro_il_cestino_si_ritrova(tmp_path, chiave):
    scena = Scena(tmp_path, chiave)
    risultato, = scena.manda()
    voce = _voce(scena, risultato)
    nuovo = os.path.join(scena.cestino.dentro, "$RNUOVO1")
    os.rename(voce["dove"], nuovo)
    os.rename(voce["info"], os.path.join(scena.cestino.dentro, "$INUOVO1"))
    _dopo_un_mese(scena)
    esito = scena.spedizioniere.ricontrolla(risultato["spedizione"])
    assert esito["esito"] == SVUOTABILE
    assert _voce(scena, risultato)["dove"] == nuovo


def _mezza_diversa(tmp_path, chiave):
    scena = Scena(tmp_path, chiave, foto={"s/a.jpg": b"a", "t/b.jpg": b"bb"}, cartelle=())

    def dopo(dati):
        if Path(dati, "b.jpg").exists():
            Path(dati, "intrusa.jpg").write_bytes(b"intrusa")

    scena.cestino.dopo = dopo
    esame = scena.spedizioniere.esaminatore.esamina(scena.via.foto)
    risultato, = scena.spedizioniere.manda([esame], "CANCELLA")
    spedizione = scena.quaderno.spedizione(risultato["spedizione"])
    assert [voce["esito"] for voce in spedizione["voci"]] == [NEL_CESTINO, DIVERSA]
    return scena, risultato["spedizione"], spedizione["voci"][1]


def test_una_parte_diversa_nel_cestino_non_lascia_svuotare(tmp_path, chiave):
    scena, id, diversa = _mezza_diversa(tmp_path, chiave)
    _dopo_un_mese(scena)
    dovuta, = scena.spedizioniere.da_ricontrollare()
    assert dovuta["id"] == id
    esito = scena.spedizioniere.ricontrolla(id)
    assert esito["esito"] == ASPETTA and esito["codice"] == "da_guardare"
    assert "non svuotare il Cestino" in esito["messaggio"]
    assert [dovuta["id"] for dovuta in scena.spedizioniere.da_ricontrollare()] == [id]
    os.rename(diversa["dove"], diversa["origine"])
    os.unlink(diversa["info"])
    esito = scena.spedizioniere.ricontrolla(id)
    assert esito["esito"] == SVUOTABILE
    assert scena.via.qui("t/intrusa.jpg").read_bytes() == b"intrusa"


def test_una_parte_diversa_spostata_nel_cestino_si_trova_lo_stesso(tmp_path, chiave):
    scena, id, diversa = _mezza_diversa(tmp_path, chiave)
    os.rename(diversa["dove"], os.path.join(scena.cestino.dentro, "$RALTRO1"))
    os.rename(diversa["info"], os.path.join(scena.cestino.dentro, "$IALTRO1"))
    _dopo_un_mese(scena)
    assert scena.spedizioniere.ricontrolla(id)["codice"] == "da_guardare"


def test_una_parte_diversa_svuotata_non_ferma_piu(tmp_path, chiave):
    scena, id, diversa = _mezza_diversa(tmp_path, chiave)
    shutil.rmtree(diversa["dove"])
    os.unlink(diversa["info"])
    _dopo_un_mese(scena)
    assert scena.spedizioniere.ricontrolla(id)["esito"] == SVUOTABILE


def test_se_il_cestino_non_si_legge_la_parte_diversa_ferma(tmp_path, chiave):
    scena, id, _ = _mezza_diversa(tmp_path, chiave)
    _dopo_un_mese(scena)
    scena.cestino.guasto = "cartella"
    esito = scena.spedizioniere.ricontrolla(id)
    assert esito["esito"] == ASPETTA and esito["codice"] == "da_guardare"


def test_una_cartella_tutta_diversa_non_dice_che_non_c_e_piu(tmp_path, chiave):
    scena = Scena(tmp_path, chiave)
    scena.cestino.dopo = _aggiunge_nel_cestino
    risultato, = scena.manda()
    assert _voce(scena, risultato)["esito"] == DIVERSA
    _dopo_un_mese(scena)
    assert scena.spedizioniere.da_ricontrollare() == []
    esito = scena.spedizioniere.ricontrolla(risultato["spedizione"])
    assert esito["esito"] == ASPETTA and esito["codice"] == "da_guardare"


def test_i_pezzi_nel_cestino_fermano_finche_ci_sono(tmp_path, chiave):
    scena = Scena(tmp_path, chiave)
    scena.cestino.modo = "a_meta"
    risultato, = scena.manda()
    assert _voce(scena, risultato)["esito"] == A_META
    id = risultato["spedizione"]
    esito = scena.spedizioniere.ricontrolla(id)
    assert esito["esito"] == ASPETTA and esito["codice"] == "da_guardare"
    for buttato in scena.cestino.elenca(os.fspath(scena.cestino.disco)):
        os.rename(buttato.dati, buttato.originale)
        os.unlink(buttato.info)
    esito = scena.spedizioniere.ricontrolla(id)
    assert esito["esito"] == FINITA
    assert scena.via.qui("s/a.jpg").exists()


def test_una_persa_che_non_c_e_nel_cestino_non_ferma(tmp_path, chiave):
    scena = Scena(tmp_path, chiave)
    scena.cestino.modo = "per_sempre"
    risultato, = scena.manda()
    assert _voce(scena, risultato)["esito"] == PERSA
    esito = scena.spedizioniere.ricontrolla(risultato["spedizione"])
    assert esito["esito"] == FINITA


def test_una_spedizione_che_non_c_e(tmp_path, chiave):
    scena = Scena(tmp_path, chiave)
    assert _codice(lambda: scena.spedizioniere.ricontrolla("0" * 16)) == (
        "spedizione_sconosciuta")


def test_senza_lista_il_ricontrollo_aspetta(tmp_path, chiave):
    scena = Scena(tmp_path, chiave)
    id = scena.manda()[0]["spedizione"]
    shutil.rmtree(scena.via.banco.archivio / LISTE)
    _dopo_un_mese(scena)
    esito = scena.spedizioniere.ricontrolla(id)
    assert esito["esito"] == ASPETTA and esito["codice"] == "lista_rovinata"


def test_se_l_archivio_lavora_il_ricontrollo_non_parte(tmp_path, chiave):
    occupato = [False]
    scena = Scena(tmp_path, chiave, occupato=lambda: occupato[0])
    id = scena.manda()[0]["spedizione"]
    occupato[0] = True
    assert _codice(lambda: scena.spedizioniere.ricontrolla(id)) == "occupato"


def test_il_ricontrollo_in_sottofondo(tmp_path, chiave):
    scena = Scena(tmp_path, chiave, foto=DUE, cartelle=DUE_VUOTE)
    primo, secondo = scena.manda("s", "t")
    _dopo_un_mese(scena)
    ricontrollo = Ricontrollo(scena.spedizioniere, sveglio=_sveglio)
    assert ricontrollo.avvia()
    assert ricontrollo.aspetta_fine(ATTESA_FILO)
    foto = ricontrollo.istantanea()
    assert foto["stato"] == FINITO
    assert {id: esito["esito"] for id, esito in foto["esiti"].items()} == {
        primo["spedizione"]: SVUOTABILE, secondo["spedizione"]: SVUOTABILE}
    assert scena.spedizioniere.aspetta is None
    json.dumps(foto)


def test_il_ricontrollo_in_sottofondo_si_ferma(tmp_path, chiave):
    scena = Scena(tmp_path, chiave)
    id = scena.manda()[0]["spedizione"]
    _dopo_un_mese(scena)
    ricontrollo = Ricontrollo(scena.spedizioniere, sveglio=_sveglio)
    ricontrollo._rallenta = lambda: ricontrollo.ferma()
    ricontrollo.avvia([id])
    assert ricontrollo.aspetta_fine(ATTESA_FILO)
    assert ricontrollo.stato == FERMATO
    assert scena.quaderno.spedizione(id)["ricontrollo"] is None


def test_la_mandata_in_sottofondo(tmp_path, chiave):
    scena = Scena(tmp_path, chiave)
    mandata = Mandata(scena.spedizioniere, sveglio=_sveglio)
    assert mandata.avvia([scena.esame()], "CANCELLA")
    assert mandata.aspetta_fine(ATTESA_FILO)
    foto = mandata.istantanea()
    assert foto["stato"] == FINITO and foto["errore"] is None
    assert [risultato["esito"] for risultato in foto["risultati"]] == [NEL_CESTINO]
    assert scena.spedizioniere.aspetta is None
    json.dumps(foto)


@pytest.mark.parametrize("parola", ["si", "cancella", "Cancella", None])
def test_la_mandata_con_la_parola_sbagliata_non_parte(tmp_path, chiave, parola):
    scena = Scena(tmp_path, chiave)
    mandata = Mandata(scena.spedizioniere, sveglio=_sveglio)
    assert _codice(lambda: mandata.avvia([scena.esame()], parola)) == "parola_sbagliata"
    assert not mandata.acceso and scena.cestino.mosse == []


def test_la_mandata_fermata_subito_non_tocca_niente(tmp_path, chiave):
    scena = Scena(tmp_path, chiave)
    mandata = Mandata(scena.spedizioniere, sveglio=_sveglio)
    mandata._rallenta = lambda: mandata.ferma()
    mandata.avvia([scena.esame()], "CANCELLA")
    assert mandata.aspetta_fine(ATTESA_FILO)
    assert mandata.stato == FERMATO and scena.cestino.mosse == []
    assert _albero(scena.via.qui("s")) == DENTRO_S


def test_la_mandata_fermata_a_meta_finisce_quella_che_ha_spostato(tmp_path, chiave):
    scena = Scena(tmp_path, chiave, foto=DUE, cartelle=DUE_VUOTE)
    mandata = Mandata(scena.spedizioniere, sveglio=_sveglio)
    scena.cestino.dopo = lambda dati: mandata.ferma()
    mandata.avvia([scena.esame("s"), scena.esame("t")], "CANCELLA")
    assert mandata.aspetta_fine(ATTESA_FILO)
    foto = mandata.istantanea()
    assert foto["stato"] == FERMATO
    assert [risultato["esito"] for risultato in foto["risultati"]] == [NEL_CESTINO]
    assert scena.via.qui("t/a.jpg").exists() and not scena.via.qui("s").exists()
    spedizione, = scena.quaderno.spedizioni()
    assert spedizione["custodita"] and spedizione["voci"][0]["esito"] == NEL_CESTINO


def test_la_mandata_con_un_errore_lo_dice(tmp_path, chiave):
    scena = Scena(tmp_path, chiave, occupato=lambda: True)
    mandata = Mandata(scena.spedizioniere, sveglio=_sveglio)
    mandata.avvia([scena.esame()], "CANCELLA")
    assert mandata.aspetta_fine(ATTESA_FILO)
    assert mandata.istantanea()["codice"] == "occupato"


def _avvisi():
    avvisi: list[str] = []
    return avvisi, avvisi.append


def test_un_file_non_archiviato_buttato_a_mano_suona(tmp_path, chiave):
    scena = Scena(tmp_path, chiave)
    avvisi, avvisa = _avvisi()
    vedetta = scena.vedetta(avvisa=avvisa)
    assert vedetta.guarda() == []
    scena.via.banco.metti("s/nuova.jpg", b"nuova")
    dati = scena.cestino.a_mano(scena.via.qui("s/nuova.jpg"))
    allarme, = vedetta.guarda()
    assert allarme["stato"] == ATTIVO and allarme["dati"] == dati
    assert allarme["file"] == 1 and allarme["mancanti"] == 1 and allarme["byte"] == 5
    assert avvisi == [AVVISO]
    assert "nuova" not in AVVISO and "jpg" not in AVVISO and "foto" not in AVVISO
    assert vedetta.allarmi() == [allarme]
    assert vedetta.guarda() == [] and avvisi == [AVVISO]
    assert Quaderno(scena.via.banco.archivio, chiave).allarmi() == [allarme]
    assert scena.vedetta(avvisa=avvisa).guarda() == []
    assert avvisi == [AVVISO]


def test_una_cartella_buttata_a_mano_conta_solo_quelli_che_mancano(tmp_path, chiave):
    scena = Scena(tmp_path, chiave)
    scena.via.banco.metti("s/sotto/nuova.jpg", b"nuova")
    scena.via.banco.metti("s/sotto/altra.jpg", b"altra!")
    scena.cestino.a_mano(scena.via.qui("s/sotto"))
    allarme, = scena.vedetta().guarda()
    assert allarme["file"] == 4 and allarme["mancanti"] == 2 and allarme["byte"] == 11


@pytest.mark.parametrize("relativo", ["s/a.jpg", "s/sotto", "s", "s/vuoto.jpg"])
def test_buttare_a_mano_cose_archiviate_non_suona(tmp_path, chiave, relativo):
    scena = Scena(tmp_path, chiave)
    avvisi, avvisa = _avvisi()
    scena.cestino.a_mano(scena.via.qui(relativo))
    assert scena.vedetta(avvisa=avvisa).guarda() == [] and avvisi == []


def test_un_file_cambiato_dopo_la_copia_suona(tmp_path, chiave):
    scena = Scena(tmp_path, chiave)
    scena.via.qui("s/a.jpg").write_bytes(b"cambiata dopo la copia")
    scena.cestino.a_mano(scena.via.qui("s/a.jpg"))
    allarme, = scena.vedetta().guarda()
    assert allarme["mancanti"] == 1


def test_un_file_cambiato_con_la_stessa_grandezza_suona(tmp_path, chiave):
    scena = Scena(tmp_path, chiave)
    percorso = scena.via.qui("s/a.jpg")
    prima = os.lstat(percorso)
    nuovo = bytes(byte ^ 0xFF for byte in FOTO["s/a.jpg"])
    assert nuovo not in FOTO.values()
    percorso.write_bytes(nuovo)
    os.utime(percorso, ns=(prima.st_atime_ns, prima.st_mtime_ns + 7 * 10 ** 9))
    scena.cestino.a_mano(percorso)
    allarme, = scena.vedetta().guarda()
    assert allarme["mancanti"] == 1


def test_un_file_uguale_a_uno_archiviato_non_suona(tmp_path, chiave):
    scena = Scena(tmp_path, chiave)
    scena.via.banco.metti("s/copia.jpg", FOTO["s/b.jpg"])
    scena.cestino.a_mano(scena.via.qui("s/copia.jpg"))
    assert scena.vedetta().guarda() == []


def test_un_file_rifatto_uguale_con_altra_data_non_suona(tmp_path, chiave):
    scena = Scena(tmp_path, chiave)
    percorso = scena.via.qui("s/a.jpg")
    prima = os.lstat(percorso)
    os.utime(percorso, ns=(prima.st_atime_ns, prima.st_mtime_ns + 5 * 10 ** 9))
    scena.cestino.a_mano(percorso)
    assert scena.vedetta().guarda() == []


def test_le_nostre_spedizioni_non_suonano(tmp_path, chiave):
    scena = Scena(tmp_path, chiave)
    scena.manda()
    avvisi, avvisa = _avvisi()
    assert scena.vedetta(avvisa=avvisa).guarda() == [] and avvisi == []


def test_una_spedizione_diversa_suona_per_quello_che_manca(tmp_path, chiave):
    scena = Scena(tmp_path, chiave)
    scena.cestino.dopo = lambda dati: Path(dati, "intrusa.jpg").write_bytes(b"intrusa")
    scena.manda()
    allarme, = scena.vedetta().guarda()
    assert allarme["mancanti"] == 1 and allarme["file"] == 6


def test_fuori_dalle_cartelle_dell_archivio_non_suona(tmp_path, chiave):
    scena = Scena(tmp_path, chiave)
    fuori = tmp_path / "altrove" / "fuori.jpg"
    fuori.parent.mkdir()
    fuori.write_bytes(b"fuori")
    scena.cestino.a_mano(fuori)
    assert scena.vedetta().guarda() == []


def test_buttato_prima_di_aggiungere_la_cartella_non_suona(tmp_path, chiave):
    scena = Scena(tmp_path, chiave)
    scena.via.banco.metti("s/nuova.jpg", b"nuova")
    scena.cestino.a_mano(scena.via.qui("s/nuova.jpg"), quando=500.0)
    assert scena.vedetta().guarda() == []


def test_le_cartelle_da_saltare_non_suonano_ma_le_vicine_si(tmp_path, chiave):
    scena = Scena(tmp_path, chiave)
    scena.via.banco.metti("s/nuova.jpg", b"nuova")
    scena.via.banco.metti("t/vicina.jpg", b"vicina")
    vedetta = scena.vedetta(salta=[scena.via.qui("s")])
    scena.cestino.a_mano(scena.via.qui("s/nuova.jpg"))
    assert vedetta.guarda() == []
    scena.cestino.a_mano(scena.via.qui("t/vicina.jpg"))
    allarme, = vedetta.guarda()
    assert allarme["mancanti"] == 1


def test_una_cartella_sopra_quelle_dell_archivio_conta_solo_quelli_dentro(tmp_path, chiave):
    scena = Scena(tmp_path, chiave)
    sopra = tmp_path / "altre"
    (sopra / "r2").mkdir(parents=True)
    (sopra / "r2" / "nuova.jpg").write_bytes(b"nuova")
    (sopra / "fuori.jpg").write_bytes(b"fuori")
    scena.via.banco.elenco.registra([fatto_radice("r2", os.fspath(sopra / "r2"),
                                                  quando=1000.0)])
    scena.cestino.a_mano(sopra)
    allarme, = scena.vedetta().guarda()
    assert allarme["file"] == 1 and allarme["mancanti"] == 1 and allarme["byte"] == 5


def test_una_cartella_tolta_dall_archivio_non_suona(tmp_path, chiave):
    scena = Scena(tmp_path, chiave)
    scena.via.banco.metti("s/nuova.jpg", b"nuova")
    scena.via.banco.elenco.registra([fatto_radice("r1", os.fspath(scena.via.foto),
                                                  tolta=True)])
    scena.cestino.a_mano(scena.via.qui("s/nuova.jpg"))
    assert scena.vedetta().guarda() == []


@su_linux
def test_un_nome_con_la_barra_rovescia_suona(tmp_path, chiave):
    scena = Scena(tmp_path, chiave)
    scena.via.banco.metti("s/a\\b.jpg", b"strana")
    scena.cestino.a_mano(scena.via.qui("s/a\\b.jpg"))
    allarme, = scena.vedetta().guarda()
    assert allarme["mancanti"] == 1


@su_linux
def test_un_nome_con_la_barra_rovescia_uguale_a_uno_archiviato_non_suona(tmp_path, chiave):
    scena = Scena(tmp_path, chiave)
    scena.via.banco.metti("s/a\\b.jpg", FOTO["s/a.jpg"])
    scena.cestino.a_mano(scena.via.qui("s/a\\b.jpg"))
    assert scena.vedetta().guarda() == []


def test_le_cartelle_di_windows_non_contano(tmp_path, chiave):
    scena = Scena(tmp_path, chiave)
    scena.via.banco.metti("s/System Volume Information/x.dat", b"sistema")
    scena.cestino.a_mano(scena.via.qui("s/System Volume Information"))
    assert scena.vedetta().guarda() == []


class _VedettaCieca(Vedetta):

    def _voci(self, dati):
        raise PermissionError(errno.EACCES, "non si legge")


def test_se_non_si_legge_si_riprova_e_poi_suona(tmp_path, chiave):
    scena = Scena(tmp_path, chiave)
    avvisi, avvisa = _avvisi()
    vedetta = scena.vedetta(classe=_VedettaCieca, avvisa=avvisa)
    scena.cestino.a_mano(scena.via.qui("s/a.jpg"))
    for _ in range(modulo.TENTATIVI - 1):
        assert vedetta.guarda() == []
    allarme, = vedetta.guarda()
    assert allarme["mancanti"] is None and allarme["file"] is None
    assert avvisi == [AVVISO] and vedetta.guarda() == []


def test_se_sparisce_prima_di_guardarlo_non_suona(tmp_path, chiave):
    scena = Scena(tmp_path, chiave)
    scena.via.banco.metti("s/nuova.jpg", b"nuova")
    dati = scena.cestino.a_mano(scena.via.qui("s/nuova.jpg"))
    os.unlink(dati)
    assert scena.vedetta().guarda() == []


def test_rimesso_al_suo_posto_si_spegne(tmp_path, chiave):
    scena = Scena(tmp_path, chiave)
    scena.via.banco.metti("s/nuova.jpg", b"nuova")
    dati = scena.cestino.a_mano(scena.via.qui("s/nuova.jpg"))
    vedetta = scena.vedetta()
    allarme, = vedetta.guarda()
    os.rename(dati, scena.via.qui("s/nuova.jpg"))
    assert vedetta.guarda() == [] and vedetta.allarmi() == []
    salvato, = scena.quaderno.allarmi()
    assert salvato["id"] == allarme["id"] and salvato["stato"] == RIMESSO


def test_svuotato_resta_da_mostrare_finche_non_si_capisce(tmp_path, chiave):
    scena = Scena(tmp_path, chiave)
    scena.via.banco.metti("s/nuova.jpg", b"nuova")
    dati = scena.cestino.a_mano(scena.via.qui("s/nuova.jpg"))
    vedetta = scena.vedetta()
    allarme, = vedetta.guarda()
    os.unlink(dati)
    vedetta.guarda()
    mostrato, = vedetta.allarmi()
    assert mostrato["stato"] == PERSO
    assert not vedetta.ho_capito("0" * 16)
    assert vedetta.ho_capito(allarme["id"])
    assert vedetta.allarmi() == [] and not vedetta.ho_capito(allarme["id"])
    assert scena.quaderno.allarmi()[0]["stato"] == LASCIATO
    assert scena.vedetta().allarmi() == []


def test_se_l_avviso_di_windows_non_parte_si_segna(tmp_path, chiave):
    scena = Scena(tmp_path, chiave)

    def avvisa(testo):
        raise OSError("notifiche spente")

    vedetta = scena.vedetta(avvisa=avvisa)
    scena.via.banco.metti("s/nuova.jpg", b"nuova")
    scena.cestino.a_mano(scena.via.qui("s/nuova.jpg"))
    assert len(vedetta.guarda()) == 1
    assert "avviso_non_mandato" in vedetta.problemi
    assert len(vedetta.allarmi()) == 1


def test_se_il_quaderno_non_si_scrive_l_allarme_resta_in_memoria(tmp_path, chiave,
                                                                  monkeypatch):
    scena = Scena(tmp_path, chiave)
    rotto = _scrittura_che_si_rompe(monkeypatch)
    vedetta = scena.vedetta()
    scena.via.banco.metti("s/nuova.jpg", b"nuova")
    scena.cestino.a_mano(scena.via.qui("s/nuova.jpg"))
    rotto["si"] = True
    assert len(vedetta.guarda()) == 1
    assert "quaderno_non_salvato" in vedetta.problemi and len(vedetta.allarmi()) == 1
    rotto["si"] = False
    scena.via.banco.metti("s/altra.jpg", b"altra")
    scena.cestino.a_mano(scena.via.qui("s/altra.jpg"))
    assert len(vedetta.guarda()) == 1
    assert "quaderno_non_salvato" not in vedetta.problemi


def test_se_il_cestino_non_si_legge_si_dice(tmp_path, chiave, monkeypatch):
    scena = Scena(tmp_path, chiave)
    vedetta = scena.vedetta()

    def guasto(volume):
        raise OSError(errno.EIO, "cestino")

    monkeypatch.setattr(scena.cestino, "elenca", guasto)
    assert vedetta.guarda() == [] and "cestino_illeggibile" in vedetta.problemi
    monkeypatch.undo()
    vedetta.guarda()
    assert "cestino_illeggibile" not in vedetta.problemi


def test_quelli_gia_visti_non_si_riguardano(tmp_path, chiave, monkeypatch):
    scena = Scena(tmp_path, chiave)
    scena.cestino.a_mano(scena.via.qui("s/a.jpg"))
    assert scena.vedetta().guarda() == []
    vedetta = scena.vedetta()
    guardati = []
    vero = vedetta._esamina
    monkeypatch.setattr(vedetta, "_esamina",
                        lambda *argomenti: guardati.append(1) or vero(*argomenti))
    assert vedetta.guarda() == [] and guardati == []


def test_la_ronda_gira_finche_non_si_ferma(tmp_path, chiave):
    scena = Scena(tmp_path, chiave)
    vedetta = scena.vedetta()
    ronda = Ronda(vedetta, ogni=0.01)
    assert ronda.avvia() and not ronda.avvia()
    _aspetta_che(lambda: ronda.giri >= 3)
    ronda.ferma(ATTESA_FILO)
    assert ronda.stato == FERMATO and vedetta.aspetta is None
    foto = ronda.istantanea()
    assert foto["giri"] >= 3 and foto["ultimo"] is None and foto["allarmi"] == []
    json.dumps(foto)


def test_la_ronda_trova_un_allarme(tmp_path, chiave):
    scena = Scena(tmp_path, chiave)
    avvisi, avvisa = _avvisi()
    ronda = Ronda(scena.vedetta(avvisa=avvisa), ogni=0.01)
    ronda.avvia()
    scena.via.banco.metti("s/nuova.jpg", b"nuova")
    scena.cestino.a_mano(scena.via.qui("s/nuova.jpg"))
    _aspetta_che(lambda: ronda.istantanea()["allarmi"])
    ronda.ferma(ATTESA_FILO)
    assert avvisi == [AVVISO]


@pytest.mark.parametrize("guasto, codice", [
    (RuntimeError("boh"), "vedetta_guasta"),
    (ErroreOfficina("rotto", codice="qualcosa"), "qualcosa"),
    (OSError(errno.EIO, "disco"), "vedetta_guasta"),
])
def test_la_ronda_non_muore_se_la_vedetta_si_guasta(tmp_path, chiave, guasto, codice):
    scena = Scena(tmp_path, chiave)
    vedetta = scena.vedetta()
    volte = []

    def guarda():
        volte.append(1)
        raise guasto

    vedetta.guarda = guarda
    ronda = Ronda(vedetta, ogni=0.01)
    ronda.avvia()
    _aspetta_che(lambda: len(volte) >= 3)
    assert ronda.ultimo == codice and ronda.acceso
    ronda.ferma(ATTESA_FILO)
    assert ronda.stato == FERMATO


def test_la_ronda_fermata_da_dentro_si_ferma(tmp_path, chiave):
    scena = Scena(tmp_path, chiave)
    vedetta = scena.vedetta()

    def guarda():
        raise Fermato

    vedetta.guarda = guarda
    ronda = Ronda(vedetta, ogni=0.01)
    ronda.avvia()
    assert ronda.aspetta_fine(ATTESA_FILO)
    assert ronda.stato == FERMATO and ronda.giri == 0
