from __future__ import annotations

import errno
import json
import os
import random
import shutil
from pathlib import Path

import pytest

from officina.errori import ErroreOfficina
from officina.sicuro import chiavi, elenco, formato, metadati, via_libera
from officina.sicuro.chiavetta import CARTELLA, SEGNO, ChiavettaStaccata
from officina.sicuro.copia import CUSTODITO, Fermato
from officina.sicuro.elenco import Elenco
from officina.sicuro.sottofondo import ERRORE, FERMATO, FINITO
from officina.sicuro.via_libera import (GLOBALI, ORDINE, PAROLE, VALIDO_PER, ControlloFresco,
                                        Esame, Esaminatore, sincronizzato)
from prove.test_sicuro_chiavetta import (Prova, _danneggia, _scrivi_segno, _segno_finto,
                                         _sveglio, chiave, pezzi_piccoli)
from prove.test_sicuro_copia import _dati, _settori_rotti

ATTESA = 20.0
FOTO = {
    "s/a.jpg": _dati(100, 1),
    "s/b.jpg": _dati(3 * formato.BLOCCO + 7, 2),
    "s/vuoto.jpg": b"",
    "s/sotto/c.jpg": _dati(formato.BLOCCO, 3),
    "s/sotto/doppio.jpg": _dati(100, 1),
}
CARTELLE = ("s/vuota",)
VERO_OPEN = open

assert chiave and pezzi_piccoli


class Via:

    def __init__(self, cartella: Path, chiave, foto=FOTO, cartelle=CARTELLE,
                 pronta: bool = True):
        self.prova = Prova(cartella, chiave)
        self.banco = self.prova.banco
        self.chiave = chiave
        self.base = cartella
        for nome, dati in foto.items():
            self.banco.metti(nome, dati)
        for nome in cartelle:
            (self.banco.sorgente / nome).mkdir(parents=True, exist_ok=True)
        if foto or cartelle:
            self.banco.giro()
        if pronta:
            self.prova.pronta()

    @property
    def foto(self) -> Path:
        return self.banco.sorgente

    def qui(self, relativo: str) -> Path:
        return self.banco.sorgente / relativo

    def numero(self, relativo: str) -> str:
        return self.banco.posto(relativo).contenuto

    def pc(self, relativo: str) -> Path:
        return self.prova.pc(self.numero(relativo))

    def sopra(self, relativo: str) -> Path:
        return self.prova.sopra(self.numero(relativo))

    def copia(self) -> None:
        self.banco.giro()
        self.prova.chiavetta.aggiorna(self.prova.radice)

    def esaminatore(self, **opzioni) -> Esaminatore:
        opzioni.setdefault("apri", self.banco.apri)
        opzioni.setdefault("dischi", lambda: [self.prova.radice])
        opzioni.setdefault("speciali", lambda: [])
        opzioni.setdefault("nuvole", lambda: [])
        opzioni.setdefault("adesso", self.prova.orologio)
        chiavetta = opzioni.pop("chiavetta", self.prova.chiavetta)
        return Esaminatore(self.banco.archivio, self.banco.elenco, self.chiave, chiavetta,
                           **opzioni)

    def esamina(self, relativo="s", **opzioni) -> Esame:
        return self.esaminatore(**opzioni).esamina(self.qui(relativo))

    def rifiuta(self, percorso, **opzioni) -> str:
        with pytest.raises(ErroreOfficina) as preso:
            self.esaminatore(**opzioni).esamina(percorso)
        return preso.value.codice


def _scrivi_uguale(percorso: Path, dati: bytes) -> None:
    prima = os.lstat(percorso)
    with VERO_OPEN(percorso, "r+b") as file:
        file.write(dati)
    os.utime(percorso, ns=(prima.st_atime_ns, prima.st_mtime_ns))


def _in_chiaro(chiave, percorso: Path, numero: str) -> bytes | None:
    try:
        with VERO_OPEN(percorso, "rb") as file:
            return formato.Contenuto(file, chiave, numero=bytes.fromhex(numero)).tutto()
    except (OSError, ErroreOfficina):
        return None


def _gira_un_byte(percorso: Path, dove: int) -> int:
    with VERO_OPEN(percorso, "r+b") as file:
        file.seek(dove)
        vecchio = file.read(1)[0]
        file.seek(dove)
        file.write(bytes([vecchio ^ 0x5A]))
    return vecchio


def _rimetti_un_byte(percorso: Path, dove: int, vecchio: int) -> None:
    with VERO_OPEN(percorso, "r+b") as file:
        file.seek(dove)
        file.write(bytes([vecchio]))


class _Stato:

    def __init__(self, vero, **cambi):
        self._vero = vero
        self._cambi = cambi

    def __getattr__(self, nome):
        if nome in self._cambi:
            return self._cambi[nome]
        return getattr(self._vero, nome)


def test_una_cartella_copiata_e_sulla_chiavetta_e_verde(tmp_path, chiave):
    via = Via(tmp_path, chiave)
    esame = via.esamina()
    assert esame.verde, esame.istantanea()
    assert esame.file == 5 and esame.cartelle == 2
    assert esame.byte == sum(len(dati) for dati in FOTO.values())
    assert esame.frase() == ("Verde: tutti i 5 file sono uguali, byte per byte, "
                             "nell'archivio e sulla chiavetta.")
    assert not esame.solo_dentro and esame.radici == [("r1", "s")]
    attesi = {via.banco.posto(nome).chiave for nome in ("s", "s/sotto", "s/vuota", *(
        nome[2:] and nome for nome in FOTO))}
    assert esame.posti == attesi
    assert esame.dove_posti == {via.banco.posto(nome).chiave: nome[2:]
                                for nome in ("s", "s/sotto", "s/vuota", *FOTO)}
    assert esame.contenuti == {via.numero(nome) for nome in FOTO}
    assert len(esame.contenuti) == 4
    assert esame.avvisi == {} and esame.da_controllare == set()
    assert esame.chiavetta == via.prova.chiavetta.identita
    foto = esame.istantanea()
    assert foto["verde"] and foto["valido_fino"] == esame.fine + VALIDO_PER
    assert foto["primo"] is None and foto["rossi"] == {}
    json.dumps(foto)


def test_si_leggono_davvero_l_originale_la_copia_e_la_chiavetta(tmp_path, chiave):
    via = Via(tmp_path, chiave)
    via.banco.apri.aperti.clear()
    assert via.esamina().verde
    aperti = {nome for nome, _ in via.banco.apri.aperti}
    for nome in FOTO:
        assert os.fspath(via.qui(nome)) in aperti
        assert os.fspath(via.pc(nome)) in aperti
        assert os.fspath(via.sopra(nome)) in aperti
    assert all(senza for _, senza in via.banco.apri.aperti)


def test_un_file_solo_e_una_cartella_vuota_hanno_la_loro_frase(tmp_path, chiave):
    via = Via(tmp_path, chiave, foto={"uno/a.jpg": b"aaa"}, cartelle=("nulla",))
    assert via.esamina("uno").frase() == (
        "Verde: il file è uguale, byte per byte, nell'archivio e sulla chiavetta.")
    vuota = via.esamina("nulla")
    assert vuota.verde and vuota.file == 0
    assert vuota.frase().startswith("Verde: qui non ci sono file")


def test_la_cartella_delle_foto_intera_si_controlla_solo_dentro(tmp_path, chiave):
    via = Via(tmp_path, chiave)
    esame = via.esaminatore().esamina(via.foto)
    assert esame.verde and esame.solo_dentro
    assert esame.radici == [("r1", "")]
    assert "" in esame.impronta and esame.file == 5


def test_le_foto_doppie_si_controllano_tutte_e_due(tmp_path, chiave):
    via = Via(tmp_path, chiave)
    assert via.numero("s/a.jpg") == via.numero("s/sotto/doppio.jpg")
    via.banco.apri.aperti.clear()
    assert via.esamina().verde
    originali = [nome for nome, _ in via.banco.apri.aperti
                 if nome in (os.fspath(via.qui("s/a.jpg")),
                             os.fspath(via.qui("s/sotto/doppio.jpg")))]
    assert len(originali) == 2


def _sparita(via):
    return via.qui("non-c-e")


def _un_file(via):
    return via.qui("s/a.jpg")


def _collegamento(via):
    os.symlink(via.qui("s"), via.qui("scorciatoia"))
    return via.qui("scorciatoia")


def _disco_intero(via):
    return Path(os.path.abspath(os.sep))


def _nell_archivio(via):
    return via.banco.archivio / elenco.CONTENUTI


def _l_archivio_stesso(via):
    return via.banco.archivio


def _contiene_l_archivio(via):
    return via.base


def _sulla_chiavetta(via):
    sopra = Path(via.prova.radice) / "cartella"
    sopra.mkdir()
    return sopra


def _la_chiavetta(via):
    return Path(via.prova.radice)


def _fuori(via):
    altrove = via.base / "altrove"
    altrove.mkdir()
    return altrove


def _di_windows(via):
    via.qui("System Volume Information").mkdir()
    return via.qui("System Volume Information")


def _nome_strano(via):
    via.qui("a\\b").mkdir()
    return via.qui("a\\b")


@pytest.mark.parametrize("scegli, codice", [
    (_sparita, "cartella_sparita"),
    (_un_file, "non_una_cartella"),
    (_collegamento, "e_un_collegamento"),
    (_disco_intero, "radice_di_un_disco"),
    (_nell_archivio, "nell_archivio"),
    (_l_archivio_stesso, "nell_archivio"),
    (_contiene_l_archivio, "contiene_l_archivio"),
    (_sulla_chiavetta, "sulla_chiavetta"),
    (_la_chiavetta, "sulla_chiavetta"),
    (_fuori, "fuori_dalle_cartelle"),
    (_di_windows, "cartella_di_windows"),
    (_nome_strano, "nome_strano"),
], ids=lambda valore: getattr(valore, "__name__", valore))
def test_le_scelte_sbagliate_si_rifiutano(tmp_path, chiave, scegli, codice):
    via = Via(tmp_path, chiave)
    assert via.rifiuta(scegli(via)) == codice
    assert codice not in GLOBALI


def test_una_cartella_con_dentro_una_da_saltare_si_rifiuta(tmp_path, chiave):
    via = Via(tmp_path, chiave)
    assert via.rifiuta(via.qui("s"), salta=[via.qui("s/sotto")]) == "contiene_una_saltata"
    assert via.rifiuta(via.qui("s/sotto"), salta=[via.qui("s")]) == "contiene_una_saltata"
    assert via.rifiuta(via.qui("s"), salta=[via.qui("s")]) == "contiene_una_saltata"
    assert via.rifiuta(via.qui("s"), salta=[via.qui("s/a.jpg")]) == "contiene_una_saltata"
    assert via.esamina("s/sotto", salta=[via.qui("s/vuota")]).verde


def test_le_cartelle_speciali_di_windows(tmp_path, chiave):
    via = Via(tmp_path, chiave)
    uguale = via.esamina("s", speciali=lambda: [os.fspath(via.qui("s"))])
    assert uguale.verde and uguale.solo_dentro
    assert via.rifiuta(via.qui("s"), speciali=lambda: [os.fspath(via.qui("s/sotto"))]) == (
        "contiene_cartelle_di_windows")
    dentro = via.esamina("s/sotto", speciali=lambda: [os.fspath(via.foto)])
    assert dentro.verde and not dentro.solo_dentro


def test_una_cartella_tolta_dalle_copie_non_conta_piu(tmp_path, chiave):
    via = Via(tmp_path, chiave)
    via.banco.elenco.registra([elenco.fatto_radice("r1", os.fspath(via.foto), tolta=True,
                                                   quando=2000.0)])
    assert via.rifiuta(via.qui("s")) == "fuori_dalle_cartelle"


def test_la_strada_con_un_collegamento_porta_alla_cartella_vera(tmp_path, chiave):
    via = Via(tmp_path, chiave)
    os.symlink(via.foto, tmp_path / "scorciatoia")
    esaminatore = via.esaminatore()
    esame = esaminatore.esamina(tmp_path / "scorciatoia" / "s")
    assert esame.verde
    assert esame.vero == os.path.realpath(via.qui("s"))
    assert esaminatore.ancora_uguale(esame) == []
    os.unlink(tmp_path / "scorciatoia")
    os.symlink(via.qui("s/sotto"), tmp_path / "scorciatoia")
    assert esaminatore.ancora_uguale(esame) == [""]


def test_le_scelte_una_dentro_l_altra_e_doppie(tmp_path, chiave):
    via = Via(tmp_path, chiave)
    s = os.fspath(via.qui("s"))
    esami, errori = via.esaminatore().tutte([s, os.fspath(via.qui("s/sotto")), s,
                                             s + os.sep, os.fspath(via.qui("non-c-e"))])
    assert [esame.cartella for esame in esami] == [s]
    assert esami[0].verde
    assert {testo: errore.codice for testo, errore in errori.items()} == {
        os.fspath(via.qui("s/sotto")): "dentro_un_altra",
        s + os.sep: "gia_scelta",
        os.fspath(via.qui("non-c-e")): "cartella_sparita"}


def test_due_cartelle_vicine_si_controllano_una_per_una(tmp_path, chiave):
    via = Via(tmp_path, chiave, foto={**FOTO, "t/x.jpg": b"x" * 10})
    via.banco.metti("t/nuova.jpg", b"nuova")
    esami, errori = via.esaminatore().tutte([via.qui("s"), via.qui("t")])
    assert errori == {}
    assert [esame.verde for esame in esami] == [True, False]
    assert esami[1].primo == ("manca", "nuova.jpg")


def test_due_radici_una_dentro_l_altra_contano_tutte_e_due(tmp_path, chiave):
    via = Via(tmp_path, chiave)
    via.banco.elenco.registra([elenco.fatto_radice("r2", os.fspath(via.qui("s")),
                                                   quando=1001.0)])
    esame = via.esamina()
    assert esame.radici == [("r1", "s"), ("r2", "")] and esame.solo_dentro
    assert "manca" in esame.rossi
    via.banco.copiatore.copia_radice(via.banco.radice("r2"))
    via.prova.chiavetta.aggiorna(via.prova.radice)
    esame = via.esamina()
    assert esame.verde, esame.istantanea()
    assert len(esame.posti) == 2 * (5 + 2)


def test_un_file_nuovo_non_copiato_si_dice_per_nome(tmp_path, chiave):
    via = Via(tmp_path, chiave)
    via.banco.metti("s/sotto/nuovo.jpg", b"nuovo")
    esame = via.esamina()
    assert not esame.verde
    assert esame.rossi["manca"] == 1
    assert esame.primo == ("manca", "sotto/nuovo.jpg")
    assert esame.frase() == ("sotto/nuovo.jpg non è nell'archivio. E c'è un altro problema. "
                             "La rossa non si tocca.")
    assert esame.esempi["dettagli_diversi"] == ["sotto"]


def test_un_file_cambiato_con_la_stessa_data_si_scopre_dai_byte(tmp_path, chiave):
    via = Via(tmp_path, chiave)
    _scrivi_uguale(via.qui("s/b.jpg"), b"\x00")
    esame = via.esamina()
    assert esame.rossi == {"diverso": 1}
    assert esame.frase() == "b.jpg non torna con l'archivio. La rossa non si tocca."


@pytest.mark.parametrize("dove", [0, formato.BLOCCO - 1, formato.BLOCCO,
                                  3 * formato.BLOCCO + 6])
def test_un_byte_cambiato_in_ogni_punto_del_file(tmp_path, chiave, dove):
    via = Via(tmp_path, chiave)
    vecchio = FOTO["s/b.jpg"][dove]
    _scrivi_uguale_a(via.qui("s/b.jpg"), dove, bytes([vecchio ^ 1]))
    assert via.esamina().rossi == {"diverso": 1}


def _scrivi_uguale_a(percorso: Path, dove: int, dati: bytes) -> None:
    prima = os.lstat(percorso)
    with VERO_OPEN(percorso, "r+b") as file:
        file.seek(dove)
        file.write(dati)
    os.utime(percorso, ns=(prima.st_atime_ns, prima.st_mtime_ns))


def test_date_o_permessi_cambiati_dopo_la_copia(tmp_path, chiave):
    via = Via(tmp_path, chiave)
    prima = os.lstat(via.qui("s/a.jpg"))
    os.utime(via.qui("s/a.jpg"), ns=(prima.st_atime_ns, prima.st_mtime_ns + 10 ** 9))
    assert via.esamina().rossi == {"dettagli_diversi": 1}
    os.utime(via.qui("s/a.jpg"), ns=(prima.st_atime_ns, prima.st_mtime_ns))
    assert via.esamina().verde
    os.chmod(via.qui("s/a.jpg"), 0o600)
    assert via.esamina().rossi == {"dettagli_diversi": 1}
    via.copia()
    assert via.esamina().verde


def test_l_ora_dell_ultimo_accesso_non_conta(tmp_path, chiave):
    via = Via(tmp_path, chiave)
    prima = os.lstat(via.qui("s/a.jpg"))
    os.utime(via.qui("s/a.jpg"), ns=(prima.st_atime_ns + 10 ** 9, prima.st_mtime_ns))
    assert via.esamina().verde


def test_una_cartella_nuova_non_copiata(tmp_path, chiave):
    via = Via(tmp_path, chiave)
    via.qui("s/sotto/nuova").mkdir()
    esame = via.esamina()
    assert esame.rossi == {"cartella_mancante": 1, "dettagli_diversi": 1}
    assert esame.primo == ("cartella_mancante", "sotto/nuova")
    via.copia()
    assert via.esamina().verde


def test_la_cartella_scelta_cambiata_si_dice_col_suo_nome(tmp_path, chiave):
    via = Via(tmp_path, chiave)
    prima = os.lstat(via.qui("s"))
    os.utime(via.qui("s"), ns=(prima.st_atime_ns, prima.st_mtime_ns + 10 ** 9))
    esame = via.esamina()
    assert esame.rossi == {"dettagli_diversi": 1} and esame.primo == ("dettagli_diversi", "")
    assert esame.frase().startswith("s ha date, attributi o permessi cambiati")


def test_dopo_la_copia_senza_aggiornare_la_chiavetta_e_rosso(tmp_path, chiave):
    via = Via(tmp_path, chiave)
    via.qui("s/a.jpg").write_bytes(b"nuovo contenuto")
    via.banco.giro()
    esame = via.esamina()
    assert esame.rossi == {"non_sulla_chiavetta": 1}
    assert esame.frase() == ("a.jpg non è sulla chiavetta come nell'archivio. "
                             "La rossa non si tocca.")
    via.prova.chiavetta.aggiorna(via.prova.radice)
    assert via.esamina().verde


def test_una_cartella_nuova_copiata_ma_non_sulla_chiavetta(tmp_path, chiave):
    via = Via(tmp_path, chiave)
    via.qui("s/sotto/nuova").mkdir()
    via.banco.giro()
    assert set(via.esamina().rossi) == {"non_sulla_chiavetta"}


@pytest.mark.parametrize("danno, attesi", [
    ("tutto", {"rovinato"}),
    ("pezzo", {"da_riparare"}),
    ("via", {"rovinato"}),
    ("testa", {"da_riparare"}),
    ("taglio", {"da_riparare", "rovinato"}),
    ("meta", {"da_riparare"}),
])
def test_la_copia_sul_pc_rovinata_e_rossa(tmp_path, chiave, danno, attesi):
    via = Via(tmp_path, chiave)
    numero = via.numero("s/b.jpg")
    _danneggia(via.prova, via.pc("s/b.jpg"), numero, danno, random.Random(5))
    esame = via.esamina()
    assert not esame.verde
    assert set(esame.rossi) <= attesi and sum(esame.rossi.values()) == 1, esame.rossi
    assert esame.da_controllare == {numero}
    assert esame.da_rileggere == set()


@pytest.mark.parametrize("danno, attesi", [
    ("tutto", {"rovinato_sulla_chiavetta"}),
    ("pezzo", {"da_riparare_sulla_chiavetta"}),
    ("via", {"manca_sulla_chiavetta"}),
    ("testa", {"da_riparare_sulla_chiavetta"}),
    ("taglio", {"da_riparare_sulla_chiavetta", "rovinato_sulla_chiavetta"}),
    ("meta", {"da_riparare_sulla_chiavetta"}),
])
def test_la_copia_sulla_chiavetta_rovinata_e_rossa(tmp_path, chiave, danno, attesi):
    via = Via(tmp_path, chiave)
    numero = via.numero("s/b.jpg")
    _danneggia(via.prova, via.sopra("s/b.jpg"), numero, danno, random.Random(5))
    esame = via.esamina()
    assert not esame.verde
    assert set(esame.rossi) <= attesi and sum(esame.rossi.values()) == 1, esame.rossi
    assert esame.da_controllare == set()
    if danno != "via":
        assert esame.da_rileggere == {numero}


def test_le_doppie_rovinate_si_contano_tutte_e_due(tmp_path, chiave):
    via = Via(tmp_path, chiave)
    numero = via.numero("s/a.jpg")
    _danneggia(via.prova, via.pc("s/a.jpg"), numero, "tutto", random.Random(1))
    esame = via.esamina()
    assert esame.rossi == {"rovinato": 2}
    assert esame.esempi["rovinato"] == ["a.jpg", "sotto/doppio.jpg"]
    assert esame.frase().endswith("E c'è un altro problema. La rossa non si tocca.")


def test_la_chiavetta_con_lo_stesso_file_del_pc_non_vale(tmp_path, chiave):
    via = Via(tmp_path, chiave)
    os.unlink(via.sopra("s/a.jpg"))
    os.link(via.pc("s/a.jpg"), via.sopra("s/a.jpg"))
    assert set(via.esamina().rossi) == {"manca_sulla_chiavetta"}


def test_un_file_scambiato_con_un_altro_sulla_chiavetta(tmp_path, chiave):
    via = Via(tmp_path, chiave)
    shutil.copyfile(via.sopra("s/sotto/c.jpg"), via.sopra("s/b.jpg"))
    assert via.esamina().rossi == {"rovinato_sulla_chiavetta": 1}


def test_un_file_scambiato_con_un_altro_sul_pc(tmp_path, chiave):
    via = Via(tmp_path, chiave)
    shutil.copyfile(via.pc("s/sotto/c.jpg"), via.pc("s/b.jpg"))
    esame = via.esamina()
    assert esame.rossi == {"rovinato": 1}
    assert esame.da_controllare == {via.numero("s/b.jpg")}


def test_un_contenuto_segnato_rovinato_nell_elenco(tmp_path, chiave):
    via = Via(tmp_path, chiave)
    numero = via.numero("s/b.jpg")
    via.banco.elenco.registra([elenco.fatto_stato(numero, "rovinato", quando=3000.0)])
    esame = via.esamina()
    assert esame.rossi == {"rovinato": 1} and esame.da_controllare == {numero}


def test_un_file_copiato_a_meta_va_ricopiato(tmp_path, chiave):
    via = Via(tmp_path, chiave, foto={"s/a.jpg": b"a"}, cartelle=())
    dati = _dati(10 * 4096 + 11, 9)
    via.banco.metti("s/rotto.jpg", dati)
    _settori_rotti(via.banco, "s/rotto.jpg", [2 * 4096])
    via.copia()
    assert via.banco.posto("s/rotto.jpg").segni == ("incompleto",)
    assert via.esamina().rossi == {"da_ricopiare": 1}
    via.banco.apri.regole.clear()
    via.copia()
    assert via.esamina().verde


@pytest.mark.parametrize("guasto, categoria", [
    (lambda: OSError(errno.EIO, "settore rotto"), "illeggibile"),
    (lambda: FileNotFoundError(errno.ENOENT, "sparito"), "cambiato"),
    (lambda: _bloccato(), "in_uso"),
])
def test_un_originale_che_non_si_apre(tmp_path, chiave, guasto, categoria):
    via = Via(tmp_path, chiave)
    bersaglio = os.fspath(via.qui("s/a.jpg"))

    def regola(percorso, senza_cache, volta, lettore):
        if percorso == bersaglio:
            raise guasto()
        return lettore

    via.banco.apri.regole.append(regola)
    assert via.esamina().rossi == {categoria: 1}


def _bloccato() -> OSError:
    guasto = PermissionError(errno.EACCES, "aperto altrove")
    guasto.winerror = 32
    return guasto


def test_un_originale_con_un_settore_rotto_mentre_lo_leggo(tmp_path, chiave):
    via = Via(tmp_path, chiave)
    _settori_rotti(via.banco, "s/b.jpg", [4096])
    assert via.esamina().rossi == {"illeggibile": 1}


def test_un_file_che_cambia_mentre_lo_leggo(tmp_path, chiave):
    via = Via(tmp_path, chiave)
    bersaglio = os.fspath(via.qui("s/b.jpg"))

    def regola(percorso, senza_cache, volta, lettore):
        if percorso == bersaglio:
            prima = os.lstat(percorso)
            os.utime(percorso, ns=(prima.st_atime_ns, prima.st_mtime_ns + 1))
        return lettore

    via.banco.apri.regole.append(regola)
    assert via.esamina().rossi == {"cambiato": 1}


def test_un_file_accorciato_mentre_lo_leggo(tmp_path, chiave):
    via = Via(tmp_path, chiave)
    bersaglio = os.fspath(via.qui("s/b.jpg"))

    class Corto:

        def __init__(self, vero):
            self._vero = vero
            self.dimensione = vero.dimensione

        def seek(self, dove, da=os.SEEK_SET):
            return self._vero.seek(dove, da)

        def read(self, quanti=-1):
            dove = self._vero.tell()
            dati = self._vero.read(quanti)
            return dati[:max(0, formato.BLOCCO + 10 - dove)]

        def close(self):
            self._vero.close()

        def __enter__(self):
            return self

        def __exit__(self, *altro):
            self.close()

    def regola(percorso, senza_cache, volta, lettore):
        return Corto(lettore) if percorso == bersaglio else lettore

    via.banco.apri.regole.append(regola)
    assert via.esamina().rossi == {"cambiato": 1}


def test_un_file_con_la_misura_cambiata_prima_di_aprirlo(tmp_path, chiave):
    via = Via(tmp_path, chiave)
    bersaglio = os.fspath(via.qui("s/a.jpg"))

    def regola(percorso, senza_cache, volta, lettore):
        if percorso == bersaglio:
            lettore.dimensione += 1
        return lettore

    via.banco.apri.regole.append(regola)
    assert via.esamina().rossi == {"cambiato": 1}


def test_un_file_sparito_durante_il_controllo(tmp_path, chiave):
    via = Via(tmp_path, chiave)
    vero = metadati.leggi

    def leggi(percorso, stato=None):
        if os.fspath(percorso).endswith("c.jpg"):
            os.unlink(percorso)
            raise FileNotFoundError(errno.ENOENT, "sparito")
        return vero(percorso, stato)

    esame = via.esamina(leggi=leggi)
    assert esame.rossi == {"cambiato": 2}
    assert esame.esempi["cambiato"] == ["sotto/c.jpg", "sotto"]
    assert esame.frase().startswith("sotto/c.jpg è cambiato mentre lo controllavo.")


def test_un_file_speciale_non_si_tiene(tmp_path, chiave):
    via = Via(tmp_path, chiave)
    os.mkfifo(via.qui("s/tubo"))
    via.copia()
    esame = via.esamina()
    assert esame.rossi == {"speciale": 1}
    assert esame.frase() == ("tubo non è un file normale e l'archivio non lo tiene. "
                             "La rossa non si tocca.")


def test_un_nome_strano_non_si_tiene(tmp_path, chiave):
    via = Via(tmp_path, chiave)
    via.banco.metti("s/a\\b.jpg", b"strano")
    via.copia()
    assert via.esamina().rossi == {"nome_strano": 1}


@pytest.mark.parametrize("nome", ["$RECYCLE.BIN", "System Volume Information",
                                  "$recycle.bin"])
def test_le_cartelle_di_windows_dentro_non_si_copiano(tmp_path, chiave, nome):
    via = Via(tmp_path, chiave)
    via.qui(f"s/sotto/{nome}").mkdir()
    (via.qui(f"s/sotto/{nome}") / "dentro.txt").write_bytes(b"x")
    via.copia()
    esame = via.esamina()
    assert esame.rossi == {"cartella_di_windows": 1}
    assert esame.esempi["cartella_di_windows"] == [f"sotto/{nome}"]


def test_una_cartella_che_non_si_legge(tmp_path, chiave, monkeypatch):
    via = Via(tmp_path, chiave)
    vero = os.scandir
    rotta = os.fspath(via.qui("s/sotto"))

    def scandir(percorso="."):
        if os.fspath(percorso) == rotta:
            raise PermissionError(errno.EACCES, "vietato")
        return vero(percorso)

    monkeypatch.setattr(os, "scandir", scandir)
    esame = via.esamina()
    assert esame.rossi == {"cartella_illeggibile": 1}
    assert esame.esempi["cartella_illeggibile"] == ["sotto"]


def test_un_altro_disco_attaccato_dentro(tmp_path, chiave, monkeypatch):
    via = Via(tmp_path, chiave)
    vero = os.lstat
    altro = os.fspath(via.qui("s/sotto"))

    def lstat(percorso, *altri, **opzioni):
        stato = vero(percorso, *altri, **opzioni)
        if os.fspath(percorso) == altro:
            return _Stato(stato, st_dev=stato.st_dev + 1)
        return stato

    monkeypatch.setattr(os, "lstat", lstat)
    esame = via.esamina()
    assert esame.rossi == {"altro_disco": 1}


def test_la_cartella_dell_archivio_trovata_dentro(tmp_path, chiave):
    via = Via(tmp_path, chiave)
    esaminatore = via.esaminatore()
    esame = Esame(cartella=os.fspath(via.qui("s")), vero=os.fspath(via.qui("s")),
                  radici=[("r1", "s")], solo_dentro=False, chiavetta="x", disco="x",
                  inizio=0.0)
    stato = os.stat(via.qui("s/sotto"))
    saltare = ({(stato.st_dev, stato.st_ino)}, set())
    visti = [relativo for relativo, _, _ in esaminatore._cammina(
        esame, saltare, os.stat(via.qui("s")).st_dev)]
    assert "sotto" not in visti and "sotto/c.jpg" not in visti
    assert esame.rossi == {"c_e_l_archivio": 1}


def test_i_collegamenti_si_tengono_come_collegamenti(tmp_path, chiave):
    via = Via(tmp_path, chiave)
    os.symlink("../fuori/foto.jpg", via.qui("s/link"))
    via.copia()
    esame = via.esamina()
    assert esame.verde, esame.istantanea()
    assert esame.collegamenti == 1
    assert esame.bersagli == [{"percorso": "link", "genere": "simbolico",
                               "bersaglio": "../fuori/foto.jpg", "verso_cartella": False}]
    os.unlink(via.qui("s/link"))
    os.symlink("altrove.jpg", via.qui("s/link"))
    assert "collegamento_diverso" in via.esamina().rossi
    os.symlink("nuovo.jpg", via.qui("s/sotto/link2"))
    assert "collegamento_mancante" in via.esamina().rossi
    via.copia()
    assert via.esamina().verde


def test_un_collegamento_copiato_ma_non_sulla_chiavetta(tmp_path, chiave):
    via = Via(tmp_path, chiave)
    os.symlink("x.jpg", via.qui("s/sotto/link"))
    via.banco.giro()
    assert "non_sulla_chiavetta" in via.esamina().rossi


def test_un_collegamento_al_posto_di_un_file(tmp_path, chiave):
    via = Via(tmp_path, chiave)
    os.unlink(via.qui("s/sotto/c.jpg"))
    os.symlink("a.jpg", via.qui("s/sotto/c.jpg"))
    assert "collegamento_mancante" in via.esamina().rossi


def test_una_cartella_al_posto_di_un_file(tmp_path, chiave):
    via = Via(tmp_path, chiave)
    os.unlink(via.qui("s/sotto/c.jpg"))
    via.qui("s/sotto/c.jpg").mkdir()
    assert "cartella_mancante" in via.esamina().rossi


def test_un_file_al_posto_di_una_cartella(tmp_path, chiave):
    via = Via(tmp_path, chiave)
    via.qui("s/vuota").rmdir()
    via.qui("s/vuota").write_bytes(b"x")
    assert "manca" in via.esamina().rossi


class Nascosti:

    def __init__(self, via: Via, flussi: dict[str, dict[str, bytes]]):
        self.via = via
        self.flussi = flussi
        self.cartella = via.base / "flussi"
        self.cartella.mkdir(exist_ok=True)
        self.extra: dict[str, tuple] = {}
        for relativo, nomi in flussi.items():
            for nome, dati in nomi.items():
                self.dove(via.qui(relativo), nome).write_bytes(dati)

    def dove(self, percorso, nome: str) -> Path:
        return self.cartella / f"{Path(percorso).name}~{nome}"

    def leggi(self, percorso, stato=None):
        letto = metadati.leggi(percorso, stato)
        relativo = Path(percorso).relative_to(self.via.foto).as_posix()
        if relativo in self.extra:
            return metadati.Letto(letto.tipo, letto.metadati, letto.dimensione,
                                  letto.segno, flussi=self.extra[relativo])
        nomi = self.flussi.get(relativo)
        if not nomi:
            return letto
        flussi = tuple((nome, self.dove(percorso, nome).stat().st_size) for nome in nomi)
        return metadati.Letto(letto.tipo, letto.metadati, letto.dimensione, letto.segno,
                              flussi=flussi)

    def flusso(self, percorso, nome: str) -> str:
        if not metadati.nome_di_flusso_buono(nome):
            raise ErroreOfficina("strano", codice="flusso_strano")
        return os.fspath(self.dove(percorso, nome))


def _con_nascosti(tmp_path, chiave, dati=b"[ZoneTransfer]\r\nZoneId=3\r\n"):
    via = Via(tmp_path, chiave, pronta=False)
    altra = tmp_path / "altra"
    altra.mkdir()
    (altra / "zona.txt").write_bytes(dati)
    via.banco.elenco.registra([elenco.fatto_radice("r2", os.fspath(altra), quando=1001.0)])
    via.banco.copiatore.copia_radice(via.banco.radice("r2"))
    numero = via.banco.elenco.attuale("r2", "zona.txt").contenuto
    via.banco.elenco.registra([elenco.fatto_flusso(via.banco.posto("s/b.jpg").chiave,
                                                   "Zone.Identifier", numero)])
    via.prova.pronta()
    nascosti = Nascosti(via, {"s/b.jpg": {"Zone.Identifier": dati}})
    return via, nascosti, numero


def test_i_flussi_nascosti_si_controllano_byte_per_byte(tmp_path, chiave):
    via, nascosti, numero = _con_nascosti(tmp_path, chiave)
    via.banco.apri.aperti.clear()
    esame = via.esamina(leggi=nascosti.leggi, flusso=nascosti.flusso)
    assert esame.verde, esame.istantanea()
    assert numero in esame.contenuti
    aperti = {nome for nome, _ in via.banco.apri.aperti}
    assert os.fspath(nascosti.dove(via.qui("s/b.jpg"), "Zone.Identifier")) in aperti
    assert os.fspath(via.prova.sopra(numero)) in aperti


def test_un_flusso_nascosto_cambiato(tmp_path, chiave):
    via, nascosti, _ = _con_nascosti(tmp_path, chiave)
    nascosti.dove(via.qui("s/b.jpg"), "Zone.Identifier").write_bytes(
        b"[ZoneTransfer]\r\nZoneId=4\r\n")
    esame = via.esamina(leggi=nascosti.leggi, flusso=nascosti.flusso)
    assert esame.rossi == {"flussi_diversi": 1}
    assert esame.frase() == ("b.jpg ha dei flussi nascosti che non tornano con l'archivio. "
                             "La rossa non si tocca.")


def test_un_flusso_nascosto_di_misura_diversa(tmp_path, chiave):
    via, nascosti, _ = _con_nascosti(tmp_path, chiave)
    nascosti.dove(via.qui("s/b.jpg"), "Zone.Identifier").write_bytes(b"corto")
    assert via.esamina(leggi=nascosti.leggi, flusso=nascosti.flusso).rossi == {
        "flussi_diversi": 1}


@pytest.mark.parametrize("flussi", [
    (),
    (("Zone.Identifier", 26), ("altro", 3)),
    (("Zone.Identifier", 26), ("Zone.Identifier", 26)),
    (("Zone:Identifier", 26),),
    (("", 26),),
])
def test_i_flussi_nascosti_che_non_tornano(tmp_path, chiave, flussi):
    via, nascosti, _ = _con_nascosti(tmp_path, chiave)
    nascosti.extra["s/b.jpg"] = flussi
    assert via.esamina(leggi=nascosti.leggi, flusso=nascosti.flusso).rossi == {
        "flussi_diversi": 1}


def test_un_flusso_nascosto_nuovo_non_copiato(tmp_path, chiave):
    via, nascosti, _ = _con_nascosti(tmp_path, chiave)
    nascosti.extra["s/a.jpg"] = (("Zone.Identifier", 3),)
    assert via.esamina(leggi=nascosti.leggi, flusso=nascosti.flusso).rossi == {
        "flussi_diversi": 1}


def test_un_flusso_che_non_si_apre(tmp_path, chiave):
    via, nascosti, _ = _con_nascosti(tmp_path, chiave)

    def flusso(percorso, nome):
        raise ErroreOfficina("niente flussi", codice="flussi_solo_windows")

    assert via.esamina(leggi=nascosti.leggi, flusso=flusso).rossi == {"flussi_diversi": 1}


def test_il_flusso_sulla_chiavetta_rovinato(tmp_path, chiave):
    via, nascosti, numero = _con_nascosti(tmp_path, chiave)
    _danneggia(via.prova, via.prova.sopra(numero), numero, "tutto", random.Random(2))
    esame = via.esamina(leggi=nascosti.leggi, flusso=nascosti.flusso)
    assert esame.rossi == {"rovinato_sulla_chiavetta": 1}
    assert esame.da_rileggere == {numero}


def test_una_cartella_con_flussi_nascosti(tmp_path, chiave):
    via = Via(tmp_path, chiave)
    vero = metadati.leggi

    def leggi(percorso, stato=None):
        letto = vero(percorso, stato)
        if os.fspath(percorso).endswith("sotto"):
            return metadati.Letto(letto.tipo, letto.metadati, 0, letto.segno,
                                  flussi=(("nascosto", 3),))
        return letto

    assert via.esamina(leggi=leggi).rossi == {"flussi_diversi": 1}


@pytest.mark.parametrize("avviso, categoria", [
    ("flussi_illeggibili", "flussi_illeggibili"),
    ("bersaglio_illeggibile", "bersaglio_illeggibile"),
    ("file_speciale", "speciale"),
    ("qualcosa_di_nuovo", "qualcosa_di_nuovo"),
])
def test_gli_avvisi_della_lettura_fanno_rosso(tmp_path, chiave, avviso, categoria):
    via = Via(tmp_path, chiave)
    vero = metadati.leggi

    def leggi(percorso, stato=None):
        letto = vero(percorso, stato)
        if os.fspath(percorso).endswith("a.jpg"):
            return metadati.Letto(letto.tipo, letto.metadati, letto.dimensione,
                                  letto.segno, avvisi=(avviso,))
        return letto

    esame = via.esamina(leggi=leggi)
    assert esame.rossi == {categoria: 1}
    assert esame.frase().startswith(f"a.jpg {PAROLE.get(categoria, via_libera.ALTRO)}.")


@pytest.mark.parametrize("avviso", sorted(via_libera.AVVISI_BUONI))
def test_i_permessi_che_non_si_leggono_si_dicono_ma_non_fermano(tmp_path, chiave, avviso):
    via = Via(tmp_path, chiave)
    vero = metadati.leggi

    def leggi(percorso, stato=None):
        letto = vero(percorso, stato)
        return metadati.Letto(letto.tipo, letto.metadati, letto.dimensione, letto.segno,
                              avvisi=(avviso,))

    esame = via.esamina(leggi=leggi)
    assert esame.verde and esame.avvisi[avviso] == 5 + 3


def test_un_file_solo_nel_cloud(tmp_path, chiave):
    via = Via(tmp_path, chiave)
    vero = metadati.leggi

    def leggi(percorso, stato=None):
        letto = vero(percorso, stato)
        if os.fspath(percorso).endswith("c.jpg"):
            return metadati.Letto(letto.tipo, letto.metadati, letto.dimensione,
                                  letto.segno, cloud=True)
        return letto

    esame = via.esamina(leggi=leggi)
    assert esame.rossi == {"solo_nel_cloud": 1}


def test_una_cartella_sincronizzata_si_dice(tmp_path, chiave):
    via = Via(tmp_path, chiave)
    esame = via.esamina(nuvole=lambda: [os.fspath(via.foto)])
    assert esame.verde and esame.sincronizzata
    assert esame.avvisi == {"sincronizzato": 1}
    assert via.esamina(nuvole=lambda: [os.fspath(via.qui("t"))]).sincronizzata is False


@pytest.mark.parametrize("attributi, rimando, atteso", [
    (0, 0, False),
    (0x80000, 0, True),
    (0x100000, 0, True),
    (0x20, 0, False),
    (0x400, 0x9000001A, True),
    (0x400, 0x9000701A, True),
    (0x400, 0xA000000C, False),
])
def test_i_segni_della_sincronizzazione(attributi, rimando, atteso):
    stato = _Stato(None, st_file_attributes=attributi, st_reparse_tag=rimando)
    assert sincronizzato(stato) is atteso


def test_un_file_cambiato_dopo_la_copia_ma_uguale_a_prima_si_dice(tmp_path, chiave):
    via = Via(tmp_path, chiave)
    posto = via.banco.posto("s/a.jpg")
    via.banco.elenco.registra([elenco.fatto_posto(
        posto.radice, posto.percorso, posto.tipo, posto.contenuto, posto.metadati,
        segni=("diverso_da_prima",), chiave=posto.chiave, quando=posto.visto)])
    esame = via.esamina()
    assert esame.verde and esame.avvisi == {"diverso_da_prima": 1}


def test_senza_chiavetta_preparata_non_si_parte(tmp_path, chiave):
    via = Via(tmp_path, chiave, pronta=False)
    assert via.rifiuta(via.qui("s")) == "chiavetta_mai_fatta"
    via.prova.chiavetta.prepara(via.prova.radice)
    assert via.rifiuta(via.qui("s")) == "chiavetta_da_aggiornare"
    via.prova.chiavetta.aggiorna(via.prova.radice)
    assert via.esamina().verde


def _occupato(via):
    return {"occupato": lambda: True}


def _archivio_staccato(via):
    os.rename(via.banco.archivio / elenco.CONTENUTI, via.base / "contenuti-via")
    return {}


def _persa(via):
    via.prova.chiavetta.segna_persa()
    return {}


def _staccata(via):
    return {"dischi": lambda: []}


def _vecchia(via):
    altra = via.base / "F"
    _scrivi_segno(altra, _segno_finto(via.chiave, chiavetta="cd" * 16))
    return {"dischi": lambda: [altra]}


def _diversa(via):
    altra = via.base / "F"
    _scrivi_segno(altra, _segno_finto(chiavi.Chiave(bytes(32))))
    return {"dischi": lambda: [altra]}


def _piu_nuova(via):
    altra = via.base / "F"
    segno = _segno_finto(via.chiave, chiavetta=via.prova.chiavetta.identita, versione=99)
    _scrivi_segno(altra, segno)
    return {"dischi": lambda: [altra]}


def _rovinata(via):
    altra = via.base / "F"
    (altra / CARTELLA).mkdir(parents=True)
    (altra / CARTELLA / SEGNO).write_bytes(b"{rotto")
    return {"dischi": lambda: [altra]}


def _due(via):
    altra = via.base / "F"
    shutil.copytree(via.prova.radice, altra)
    return {"dischi": lambda: [via.prova.radice, altra]}


def _stesso_disco(via):
    return {"chiavetta": via.prova.nuova(stesso_disco=lambda uno, altro: True)}


def _chiave_cambiata(via):
    (via.prova.dove / chiavi.FILE).write_bytes(b"non una chiave")
    return {}


def _chiave_di_riserva_sparita(via):
    os.unlink(via.prova.dove / chiavi.RISERVA)
    return {}


def _elenco_rovinato(via):
    fotografie = sorted((via.prova.dove / elenco.ELENCO).glob("fotografia-*"))
    dati = bytearray(fotografie[-1].read_bytes())
    dati[len(dati) // 2] ^= 0xFF
    fotografie[-1].write_bytes(bytes(dati))
    return {}


def _elenco_tutto_rovinato(via):
    fotografie = sorted((via.prova.dove / elenco.ELENCO).glob("fotografia-*"))
    dati = bytearray(fotografie[-1].read_bytes())
    dati[formato.PEZZO:] = bytes(len(dati) - formato.PEZZO)
    fotografie[-1].write_bytes(bytes(dati))
    return {}


def _elenco_sparito(via):
    for fotografia in (via.prova.dove / elenco.ELENCO).glob("fotografia-*"):
        fotografia.unlink()
    return {}


def _elenco_che_non_si_apre(via, monkeypatch):
    def apri(*argomenti, **opzioni):
        raise OSError(errno.EIO, "rotto")

    monkeypatch.setattr(via_libera.Elenco, "apri", apri)
    return {}


@pytest.mark.parametrize("prepara, codice", [
    (_occupato, "occupato"),
    (_archivio_staccato, "archivio_sparito"),
    (_persa, "chiavetta_persa"),
    (_staccata, "chiavetta_da_attaccare"),
    (_vecchia, "chiavetta_vecchia"),
    (_diversa, "chiavetta_diversa"),
    (_piu_nuova, "chiavetta_diversa"),
    (_rovinata, "chiavetta_illeggibile"),
    (_due, "due_chiavette"),
    (_stesso_disco, "stesso_disco"),
    (_chiave_cambiata, "chiavetta_senza_chiave"),
    (_chiave_di_riserva_sparita, "chiavetta_senza_chiave"),
    (_elenco_rovinato, "chiavetta_elenco_rovinato"),
    (_elenco_tutto_rovinato, "chiavetta_elenco_rovinato"),
    (_elenco_sparito, "chiavetta_elenco_rovinato"),
], ids=lambda valore: getattr(valore, "__name__", valore))
def test_senza_la_chiavetta_giusta_non_c_e_via_libera(tmp_path, chiave, prepara, codice):
    via = Via(tmp_path, chiave)
    opzioni = prepara(via)
    assert codice in GLOBALI
    assert via.rifiuta(via.qui("s"), **opzioni) == codice
    with pytest.raises(ErroreOfficina) as preso:
        via.esaminatore(**opzioni).tutte([via.qui("s"), via.qui("s/sotto")])
    assert preso.value.codice == codice


def test_l_elenco_della_chiavetta_che_non_si_apre(tmp_path, chiave, monkeypatch):
    via = Via(tmp_path, chiave)
    _elenco_che_non_si_apre(via, monkeypatch)
    assert via.rifiuta(via.qui("s")) == "chiavetta_illeggibile"


def test_la_chiavetta_staccata_mentre_preparo_l_elenco(tmp_path, chiave, monkeypatch):
    via = Via(tmp_path, chiave)
    vero = via_libera.Elenco.apri

    def apri(*argomenti, **opzioni):
        via.prova.stacca()
        raise OSError(errno.EIO, "staccata")

    monkeypatch.setattr(via_libera.Elenco, "apri", apri)
    assert via.rifiuta(via.qui("s")) == ChiavettaStaccata.codice
    monkeypatch.setattr(via_libera.Elenco, "apri", vero)
    via.prova.riattacca()
    assert via.esamina().verde


def test_la_chiavetta_staccata_durante_il_controllo(tmp_path, chiave):
    via = Via(tmp_path, chiave)
    vero = metadati.leggi
    volte = []

    def leggi(percorso, stato=None):
        volte.append(percorso)
        if len(volte) == 3:
            via.prova.stacca()
        return vero(percorso, stato)

    esaminatore = via.esaminatore(leggi=leggi)
    with pytest.raises(ChiavettaStaccata) as preso:
        esaminatore.tutte([via.qui("s/sotto"), via.qui("s")])
    assert "non è successo niente" in preso.value.messaggio
    assert esaminatore.esami == [] and esaminatore.esame is None
    via.prova.riattacca()
    assert via.esamina().verde


def test_la_chiavetta_staccata_alla_fine_toglie_il_verde(tmp_path, chiave):
    via = Via(tmp_path, chiave)
    esaminatore = via.esaminatore()
    vero = esaminatore._ricontrolla_cartelle

    def ricontrolla(esame):
        vero(esame)
        via.prova.stacca()

    esaminatore._ricontrolla_cartelle = ricontrolla
    with pytest.raises(ChiavettaStaccata):
        esaminatore.esamina(via.qui("s"))


def test_l_archivio_staccato_durante_il_controllo(tmp_path, chiave):
    via = Via(tmp_path, chiave)
    vero = metadati.leggi

    def leggi(percorso, stato=None):
        if os.fspath(percorso).endswith("b.jpg"):
            os.rename(via.banco.archivio / elenco.CONTENUTI, via.base / "contenuti-via")
        return vero(percorso, stato)

    assert via.rifiuta(via.qui("s"), leggi=leggi) == "archivio_sparito"


def test_un_altra_chiavetta_attaccata_insieme_non_disturba(tmp_path, chiave):
    via = Via(tmp_path, chiave)
    altra = via.base / "F"
    _scrivi_segno(altra, _segno_finto(chiavi.Chiave(bytes(32))))
    vuota = via.base / "G"
    vuota.mkdir()
    assert via.esamina(dischi=lambda: [altra, via.prova.radice, vuota]).verde


def test_ancora_uguale_dopo_il_controllo(tmp_path, chiave):
    via = Via(tmp_path, chiave)
    esaminatore = via.esaminatore()
    esame = esaminatore.esamina(via.qui("s"))
    assert esaminatore.ancora_uguale(esame) == []
    for nome in FOTO:
        with VERO_OPEN(via.qui(nome), "rb") as file:
            file.read()
    assert esaminatore.esamina(via.qui("s")).verde
    assert esaminatore.ancora_uguale(esame) == []
    prima = os.lstat(via.qui("s/sotto/c.jpg"))
    os.utime(via.qui("s/sotto/c.jpg"), ns=(prima.st_atime_ns, prima.st_mtime_ns + 1))
    assert esaminatore.ancora_uguale(esame) == ["sotto/c.jpg"]
    os.utime(via.qui("s/sotto/c.jpg"), ns=(prima.st_atime_ns, prima.st_mtime_ns))
    assert esaminatore.ancora_uguale(esame) == ["sotto/c.jpg"]


def test_ancora_uguale_vede_i_file_nuovi_e_quelli_spariti(tmp_path, chiave):
    via = Via(tmp_path, chiave)
    esaminatore = via.esaminatore()
    esame = esaminatore.esamina(via.qui("s"))
    via.banco.metti("s/vuota/nuovo.jpg", b"x")
    assert esaminatore.ancora_uguale(esame) == ["vuota", "vuota/nuovo.jpg"]
    os.unlink(via.qui("s/vuota/nuovo.jpg"))
    os.unlink(via.qui("s/a.jpg"))
    assert "a.jpg" in esaminatore.ancora_uguale(esame)


def test_ancora_uguale_con_il_contenuto_riscritto_uguale(tmp_path, chiave):
    via = Via(tmp_path, chiave)
    esaminatore = via.esaminatore()
    esame = esaminatore.esamina(via.qui("s"))
    os.unlink(via.qui("s/sotto/c.jpg"))
    via.banco.metti("s/sotto/c.jpg", FOTO["s/sotto/c.jpg"])
    diversi = esaminatore.ancora_uguale(esame)
    assert "sotto/c.jpg" in diversi


def test_ancora_uguale_con_la_cartella_spostata(tmp_path, chiave):
    via = Via(tmp_path, chiave)
    esaminatore = via.esaminatore()
    esame = esaminatore.esamina(via.qui("s"))
    os.rename(via.qui("s"), via.qui("s2"))
    assert esaminatore.ancora_uguale(esame) == [""]
    via.qui("s").mkdir()
    assert "" in esaminatore.ancora_uguale(esame)
    via.qui("s").rmdir()
    via.qui("s").write_bytes(b"x")
    assert esaminatore.ancora_uguale(esame) == [""]


def test_ancora_uguale_con_qualcosa_di_nuovo_dentro_che_non_si_tiene(tmp_path, chiave):
    via = Via(tmp_path, chiave)
    esaminatore = via.esaminatore()
    esame = esaminatore.esamina(via.qui("s"))
    via.qui("s/sotto/System Volume Information").mkdir()
    diversi = esaminatore.ancora_uguale(esame)
    assert "sotto/System Volume Information" in diversi and "sotto" in diversi


def test_ancora_uguale_con_l_archivio_cambiato(tmp_path, chiave):
    via = Via(tmp_path, chiave)
    esaminatore = via.esaminatore()
    esame = esaminatore.esamina(via.qui("s"))
    via.banco.elenco.registra([elenco.fatto_sparito(via.banco.posto("s/a.jpg").chiave,
                                                    9000.0)])
    with pytest.raises(ErroreOfficina) as preso:
        esaminatore.ancora_uguale(esame)
    assert preso.value.codice == "archivio_cambiato"


@pytest.mark.parametrize("dove, codice", [
    ("pc", "archivio_cambiato"),
    ("sopra", "chiavetta_cambiata"),
])
def test_ancora_uguale_con_una_copia_sparita(tmp_path, chiave, dove, codice):
    via = Via(tmp_path, chiave)
    esaminatore = via.esaminatore()
    esame = esaminatore.esamina(via.qui("s"))
    os.unlink(getattr(via, dove)("s/b.jpg"))
    with pytest.raises(ErroreOfficina) as preso:
        esaminatore.ancora_uguale(esame)
    assert preso.value.codice == codice


def test_ancora_uguale_con_un_contenuto_segnato_rovinato(tmp_path, chiave):
    via = Via(tmp_path, chiave)
    esaminatore = via.esaminatore()
    esame = esaminatore.esamina(via.qui("s"))
    via.banco.elenco.registra([elenco.fatto_stato(via.numero("s/b.jpg"), "rovinato",
                                                  quando=9000.0)])
    with pytest.raises(ErroreOfficina) as preso:
        esaminatore.ancora_uguale(esame)
    assert preso.value.codice == "archivio_cambiato"


def test_ancora_uguale_senza_chiavetta_o_archivio(tmp_path, chiave):
    via = Via(tmp_path, chiave)
    esaminatore = via.esaminatore()
    esame = esaminatore.esamina(via.qui("s"))
    via.prova.stacca()
    with pytest.raises(ChiavettaStaccata):
        esaminatore.ancora_uguale(esame)
    via.prova.riattacca()
    os.rename(via.banco.archivio / elenco.CONTENUTI, via.base / "contenuti-via")
    with pytest.raises(ErroreOfficina) as preso:
        esaminatore.ancora_uguale(esame)
    assert preso.value.codice == "archivio_sparito"


def test_ancora_uguale_della_cartella_intera(tmp_path, chiave):
    via = Via(tmp_path, chiave)
    esaminatore = via.esaminatore()
    esame = esaminatore.esamina(via.foto)
    assert esaminatore.ancora_uguale(esame) == []
    via.banco.metti("nuovo.jpg", b"n")
    assert esaminatore.ancora_uguale(esame) == ["", "nuovo.jpg"]


def _esame(**cambi) -> Esame:
    esame = Esame(cartella=os.path.join("D:", "foto", "Gita"), vero="x", radici=[],
                  solo_dentro=False, chiavetta="c", disco="d", inizio=100.0)
    for nome, valore in cambi.items():
        setattr(esame, nome, valore)
    return esame


def test_il_verde_vale_solo_per_dieci_minuti():
    esame = _esame(fine=1000.0, file=3)
    assert esame.verde
    assert esame.fresco(1000.0) and esame.fresco(1000.0 + VALIDO_PER)
    assert not esame.fresco(1000.0 + VALIDO_PER + 0.001)
    assert not esame.fresco(999.0)
    assert VALIDO_PER == 600.0
    assert not _esame().fresco(100.0)


def test_un_rosso_non_e_mai_fresco():
    esame = _esame(fine=1000.0)
    esame.segna("manca", "x.jpg")
    assert not esame.verde and not esame.fresco(1000.0)


def test_le_frasi_del_rosso():
    esame = _esame(fine=1.0)
    assert esame.frase().startswith("Verde")
    esame.segna("dettagli_diversi", "")
    assert esame.frase() == ("Gita ha date, attributi o permessi cambiati dopo l'ultima "
                             "copia. La rossa non si tocca.")
    esame.segna("rovinato_sulla_chiavetta", "IMG_0412.jpg")
    assert esame.frase() == ("IMG_0412.jpg non torna con la chiavetta. E c'è un altro "
                             "problema. La rossa non si tocca.")
    for indice in range(1500):
        esame.segna("manca", f"f{indice}.jpg")
    assert esame.frase() == ("f0.jpg non è nell'archivio. E ci sono altri 1.501 problemi. "
                             "La rossa non si tocca.")
    assert len(esame.esempi["manca"]) == via_libera.ESEMPI
    assert esame.rossi == {"dettagli_diversi": 1, "rovinato_sulla_chiavetta": 1,
                           "manca": 1500}


def test_un_controllo_non_finito_e_rosso():
    esame = _esame()
    assert not esame.verde
    assert esame.frase() == "Il controllo non è finito: la cartella resta rossa."


def test_ogni_parola_ha_la_sua_frase_e_il_suo_posto():
    assert set(ORDINE) == set(PAROLE)
    assert len(ORDINE) == len(set(ORDINE))
    assert ORDINE[0] == "manca" and ORDINE[-1] == "dettagli_diversi"
    for parola in PAROLE.values():
        assert parola and not parola.endswith(".")


def test_una_categoria_sconosciuta_ha_la_frase_di_riserva():
    esame = _esame(fine=1.0)
    esame.segna("mai_vista", "x.jpg")
    assert esame.frase() == "x.jpg ha un problema che non conosco. La rossa non si tocca."
    esame.segna("dettagli_diversi", "y")
    assert esame.primo == ("dettagli_diversi", "y")


def test_il_controllo_si_ferma_e_va_in_pausa(tmp_path, chiave):
    via = Via(tmp_path, chiave)
    chiamate = []
    assert via.esamina(aspetta=lambda: chiamate.append(1)).verde
    assert len(chiamate) >= 5 + 3

    def ferma():
        raise Fermato

    esaminatore = via.esaminatore(aspetta=ferma)
    with pytest.raises(Fermato):
        esaminatore.tutte([via.qui("s")])
    assert esaminatore.esami == []


def test_un_file_grande_si_ferma_anche_a_meta(tmp_path, chiave, monkeypatch):
    monkeypatch.setattr(via_libera, "OGNI_QUANTI_PEZZI", 1)
    via = Via(tmp_path, chiave, foto={"s/grande.jpg": _dati(5 * formato.BLOCCO, 4)},
              cartelle=())
    volte = []

    def aspetta():
        volte.append(via.esaminatore)
        if len(volte) > 4:
            raise Fermato

    with pytest.raises(Fermato):
        via.esamina(aspetta=aspetta)


def test_l_avanzamento_conta_i_file_e_i_byte(tmp_path, chiave):
    via = Via(tmp_path, chiave)
    esaminatore = via.esaminatore()
    esaminatore.esamina(via.qui("s"))
    assert esaminatore.avanzamento.file == 5
    assert esaminatore.avanzamento.letti == sum(len(dati) for dati in FOTO.values())
    assert esaminatore.avanzamento.percorso is None


def test_il_controllo_in_sottofondo(tmp_path, chiave):
    via = Via(tmp_path, chiave)
    lavoro = ControlloFresco(via.banco.archivio, via.banco.elenco, via.chiave,
                             via.prova.chiavetta, sveglio=_sveglio, apri=via.banco.apri,
                             dischi=lambda: [via.prova.radice], speciali=lambda: [],
                             nuvole=lambda: [])
    assert lavoro.avvia([via.qui("s"), via.qui("non-c-e")])
    assert lavoro.aspetta_fine(ATTESA)
    foto = lavoro.istantanea()
    assert foto["stato"] == FINITO and foto["errore"] is None
    assert [esame["verde"] for esame in foto["esami"]] == [True]
    assert foto["errori"] == {os.fspath(via.qui("non-c-e")): {
        "codice": "cartella_sparita", "messaggio": "Questa cartella non c'è più."}}
    assert foto["in_corso"] is None
    json.dumps(foto)


def test_il_controllo_in_sottofondo_senza_chiavetta(tmp_path, chiave):
    via = Via(tmp_path, chiave)
    lavoro = ControlloFresco(via.banco.archivio, via.banco.elenco, via.chiave,
                             via.prova.chiavetta, sveglio=_sveglio, apri=via.banco.apri,
                             dischi=lambda: [], speciali=lambda: [], nuvole=lambda: [])
    assert lavoro.avvia([via.qui("s")])
    assert lavoro.aspetta_fine(ATTESA)
    foto = lavoro.istantanea()
    assert foto["stato"] == ERRORE and foto["codice"] == "chiavetta_da_attaccare"
    assert foto["esami"] == []


def test_il_controllo_in_sottofondo_fermato(tmp_path, chiave):
    via = Via(tmp_path, chiave)
    lavoro = ControlloFresco(via.banco.archivio, via.banco.elenco, via.chiave,
                             via.prova.chiavetta, sveglio=_sveglio, apri=via.banco.apri,
                             dischi=lambda: [via.prova.radice], speciali=lambda: [],
                             nuvole=lambda: [])
    lavoro.pausa()
    assert lavoro.avvia([via.qui("s")])
    lavoro.ferma(ATTESA)
    foto = lavoro.istantanea()
    assert foto["stato"] == FERMATO and foto["esami"] == []


def test_gli_spariti_custoditi_restano(tmp_path, chiave):
    via = Via(tmp_path, chiave)
    posto = via.banco.posto("s/a.jpg")
    via.banco.elenco.registra([elenco.fatto_posto(
        posto.radice, posto.percorso, posto.tipo, posto.contenuto, posto.metadati,
        segni=(CUSTODITO,), chiave=posto.chiave, quando=posto.visto)])
    os.unlink(via.qui("s/a.jpg"))
    os.unlink(via.qui("s/b.jpg"))
    via.banco.giro()
    assert via.banco.posto("s/a.jpg").chiave == posto.chiave
    assert CUSTODITO in via.banco.posto("s/a.jpg").segni
    assert via.banco.posto("s/b.jpg") is None


def test_il_file_custodito_rimesso_al_suo_posto_torna_normale(tmp_path, chiave):
    via = Via(tmp_path, chiave)
    posto = via.banco.posto("s/a.jpg")
    via.banco.elenco.registra([elenco.fatto_posto(
        posto.radice, posto.percorso, posto.tipo, posto.contenuto, posto.metadati,
        segni=(CUSTODITO,), chiave=posto.chiave, quando=posto.visto)])
    via.qui("s/a.jpg").write_bytes(b"rimesso diverso")
    via.banco.giro()
    nuovo = via.banco.posto("s/a.jpg")
    assert nuovo.chiave != posto.chiave and CUSTODITO not in nuovo.segni


def test_la_chiavetta_dice_chi_e_e_se_ha_la_chiave(tmp_path, chiave):
    via = Via(tmp_path, chiave)
    chiavetta = via.prova.chiavetta
    assert chiavetta.identita == json.loads(
        (via.prova.dove / SEGNO).read_text("utf-8"))["chiavetta"]
    assert chiavetta.posto_sbagliato(via.prova.radice) is None
    assert chiavetta.posto_sbagliato(via.banco.archivio)[0] == "dentro_l_archivio"
    assert chiavetta.posto_sbagliato(via.qui("s"))[0] == "dentro_gli_originali"
    stessa = via.prova.nuova(stesso_disco=lambda uno, altro: True)
    assert stessa.posto_sbagliato(via.prova.radice)[0] == "stesso_disco"
    assert chiavetta.chiave_uguale(via.prova.radice)
    os.unlink(via.banco.archivio / chiavi.FILE)
    assert chiavetta.chiave_uguale(via.prova.radice)
    os.unlink(via.banco.archivio / chiavi.RISERVA)
    assert not chiavetta.chiave_uguale(via.prova.radice)


def test_la_chiavetta_con_un_altra_chiave_non_e_uguale(tmp_path, chiave):
    via = Via(tmp_path, chiave)
    shutil.copyfile(via.prova.dove / chiavi.FILE, via.base / "copia")
    with VERO_OPEN(via.prova.dove / chiavi.RISERVA, "r+b") as file:
        dati = bytearray(file.read())
        dati[len(dati) // 2] ^= 1
        file.seek(0)
        file.write(dati)
    assert not via.prova.chiavetta.chiave_uguale(via.prova.radice)


def test_rileggi_presto_rimette_a_zero_e_si_ricorda(tmp_path, chiave):
    via = Via(tmp_path, chiave)
    numero = via.numero("s/b.jpg")
    chiavetta = via.prova.chiavetta
    assert chiavetta._stato.sopra[numero] > 0.0
    chiavetta.rileggi_presto([numero, "f" * 32])
    assert chiavetta._stato.sopra[numero] == 0.0
    assert "f" * 32 not in chiavetta._stato.sopra
    assert via.prova.nuova()._stato.sopra[numero] == 0.0


def test_dopo_rileggi_presto_la_chiavetta_si_ripara(tmp_path, chiave):
    via = Via(tmp_path, chiave)
    numero = via.numero("s/b.jpg")
    _danneggia(via.prova, via.sopra("s/b.jpg"), numero, "pezzo", random.Random(3))
    esame = via.esamina()
    assert esame.rossi == {"da_riparare_sulla_chiavetta": 1}
    via.prova.chiavetta.rileggi_presto(esame.da_rileggere)
    via.prova.chiavetta.aggiorna(via.prova.radice)
    assert via.esamina().verde


@pytest.mark.parametrize("dove", ["pc", "sopra"])
@pytest.mark.parametrize("seme", range(4))
def test_un_byte_girato_a_caso_non_da_mai_un_verde_falso(tmp_path, chiave, dove, seme):
    via = Via(tmp_path, chiave, foto={"s/b.jpg": FOTO["s/b.jpg"]}, cartelle=())
    numero = via.numero("s/b.jpg")
    blob = getattr(via, dove)("s/b.jpg")
    caso = random.Random(seme)
    peso = blob.stat().st_size
    esaminatore = via.esaminatore()
    verdi = 0
    for _ in range(40):
        punto = caso.randrange(peso)
        vecchio = _gira_un_byte(blob, punto)
        try:
            esame = esaminatore.esamina(via.qui("s"))
            if esame.verde:
                verdi += 1
                assert _in_chiaro(chiave, via.pc("s/b.jpg"), numero) == FOTO["s/b.jpg"]
                assert _in_chiaro(chiave, via.sopra("s/b.jpg"), numero) == FOTO["s/b.jpg"]
        finally:
            _rimetti_un_byte(blob, punto, vecchio)
    assert verdi == 0
    assert esaminatore.esamina(via.qui("s")).verde
