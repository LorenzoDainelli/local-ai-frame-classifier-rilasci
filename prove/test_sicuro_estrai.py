from __future__ import annotations

import errno
import os
import random
import re
from contextlib import contextmanager
from pathlib import Path

import pytest

from officina.errori import ErroreOfficina
from officina.sicuro import chiavi, elenco, estrai, formato, sottofondo
from officina.sicuro.copia import Fermato
from officina.sicuro.diretto import ALLINEA
from officina.sicuro.estrai import Estrattore, Estrazione
from prove.test_sicuro_copia import Banco, Finto, _dati, _settori_rotti

su_linux = pytest.mark.skipif(os.name == "nt", reason="prove del lato Linux")

LIBERO = 10 ** 15
ESADECIMALE = re.compile(r"^[0-9a-f]{32}(\.ofs)?(\.nuovo|\.tenuto)?$")
ATTESA = 20.0


@pytest.fixture
def chiave():
    return chiavi.Chiave(bytes(range(32)))


class Orologio:

    def __init__(self, ora=2000.0):
        self.ora = ora

    def __call__(self):
        return self.ora


class Flussi:

    def __init__(self, cartella: Path, rompi=None):
        self.cartella = cartella
        self.cartella.mkdir(exist_ok=True)
        self.aperti: list[tuple[str, str, str]] = []
        self.rompi = rompi

    def dove(self, percorso, nome: str) -> Path:
        return self.cartella / f"{Path(percorso).name}~{nome}"

    def __call__(self, percorso, nome, modo="rb"):
        self.aperti.append((os.fspath(percorso), nome, modo))
        if self.rompi is not None:
            self.rompi(percorso, nome, modo)
        return open(self.dove(percorso, nome), modo)


@contextmanager
def _sveglio():
    yield True


def _uscita(banco: Banco, **opzioni) -> Estrattore:
    opzioni.setdefault("spazio", lambda dove: LIBERO)
    opzioni.setdefault("apri", banco.apri)
    return Estrattore(banco.archivio, banco.elenco, banco.chiave, **opzioni)


def _foto(cartella: Path) -> dict:
    trovato = {}
    for dove, cartelle, file in os.walk(cartella):
        base = Path(dove)
        for nome in [*cartelle, *file]:
            percorso = base / nome
            relativo = percorso.relative_to(cartella).as_posix()
            if percorso.is_symlink():
                trovato[relativo] = ("collegamento", os.readlink(percorso))
            elif percorso.is_dir():
                trovato[relativo] = ("cartella", None)
            else:
                trovato[relativo] = ("file", percorso.read_bytes())
    return trovato


def _date(cartella: Path) -> dict:
    return {relativo: os.lstat(cartella / relativo).st_mtime_ns
            for relativo, (tipo, _) in _foto(cartella).items()
            if tipo != "collegamento"}


def _nomi(cartella: Path) -> list[str]:
    return [parte for relativo in _foto(cartella) for parte in relativo.split("/")]


def _codici(resoconto) -> list[str]:
    return [codice for codice, _ in resoconto.problemi]


def _rovina_blocco(banco: Banco, numero: str, blocchi, tutto=True) -> None:
    blob = banco.blob(numero)
    with open(blob, "rb") as file:
        forma = formato.Contenuto(file, banco.chiave,
                                  numero=bytes.fromhex(numero)).forma
    guasto = bytearray(blob.read_bytes())
    for blocco in blocchi:
        inizio = forma.dove_blocco(blocco)
        fine = inizio + (forma.lunghezza(blocco) + formato.ETICHETTA if tutto else 40)
        for dove in range(inizio, fine):
            guasto[dove] ^= 0x5A
    blob.write_bytes(bytes(guasto))


def _albero_di_prova(banco: Banco) -> dict[str, bytes]:
    misure = {
        "2001/mare/IMG_0001.jpg": 0,
        "2001/mare/IMG_0002.jpg": 1,
        "2001/mare/IMG_0003.JPG": formato.BLOCCO - 1,
        "2001/montagna/neve.png": formato.BLOCCO,
        "2001/montagna/neve copia.png": formato.BLOCCO + 1,
        "2002/Natale è qui/video.mov": 3 * formato.BLOCCO + 17,
        "2002/Natale è qui/.nascosto": 12,
        "2002/senza estensione": 333,
        "cartella con spazi/foto ✨.heic": 4096,
        "a.jpg": 70_001,
    }
    fatti = {}
    for indice, (relativo, misura) in enumerate(misure.items()):
        fatti[relativo] = _dati(misura, indice + 1)
        banco.metti(relativo, fatti[relativo])
    for vuota in ("vuota", "2002/vuota anche lei/e dentro"):
        (banco.sorgente / vuota).mkdir(parents=True)
    for indice, percorso in enumerate(sorted(banco.sorgente.rglob("*"), reverse=True)):
        quando = (1_500_000_000 + indice * 7919) * 10 ** 9 + indice
        os.utime(percorso, ns=(quando, quando))
    return fatti


def test_una_cartella_esce_uguale_con_nomi_cartelle_e_date(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    _albero_di_prova(banco)
    assert banco.giro().verde
    uscita = _uscita(banco)
    resoconto = uscita.estrai("r1", tmp_path / "fuori")
    assert resoconto.verde, resoconto.problemi
    assert resoconto.cartella == str(tmp_path / "fuori" / "foto")
    fatta = Path(resoconto.cartella)
    assert _foto(fatta) == _foto(banco.sorgente)
    assert _date(fatta) == _date(banco.sorgente)
    assert resoconto.file == 10
    assert resoconto.cartelle == len([1 for tipo, _ in _foto(fatta).values()
                                      if tipo == "cartella"])
    assert resoconto.byte == sum(len(dati) for _, dati in
                                 (voce for voce in _foto(fatta).values()
                                  if voce[0] == "file"))
    assert uscita.avanzamento.file == len(_foto(fatta))
    assert uscita.avanzamento.byte == resoconto.byte
    assert uscita.avanzamento.byte_da_fare == resoconto.byte


def test_i_nomi_sono_sempre_quelli_veri_mai_esadecimali(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    _albero_di_prova(banco)
    banco.giro()
    resoconto = _uscita(banco).estrai("r1", tmp_path / "fuori")
    nomi = _nomi(Path(resoconto.cartella))
    assert nomi
    assert not [nome for nome in nomi if ESADECIMALE.match(nome.lower())]
    assert sorted(nomi) == sorted(_nomi(banco.sorgente))
    nell_archivio = [percorso.name for percorso
                     in (banco.archivio / elenco.CONTENUTI).rglob("*.ofs")]
    assert nell_archivio and all(ESADECIMALE.match(nome) for nome in nell_archivio)


def test_un_nome_esadecimale_vero_della_foto_resta_com_era(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    nome = "0123456789abcdef0123456789abcdef.jpg"
    banco.metti(nome, b"si chiamava proprio cosi")
    banco.giro()
    resoconto = _uscita(banco).estrai("r1", tmp_path / "fuori")
    assert (Path(resoconto.cartella) / nome).read_bytes() == b"si chiamava proprio cosi"


def test_le_cartelle_vuote_escono_anche_loro(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    (banco.sorgente / "vuota" / "anche" / "lei").mkdir(parents=True)
    banco.giro()
    resoconto = _uscita(banco).estrai("r1", tmp_path / "fuori")
    assert resoconto.verde
    assert _foto(Path(resoconto.cartella)) == {
        "vuota": ("cartella", None), "vuota/anche": ("cartella", None),
        "vuota/anche/lei": ("cartella", None)}


@su_linux
def test_le_date_delle_cartelle_si_rimettono_dopo_averle_riempite(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    banco.metti("vecchia/a.jpg", b"a")
    banco.metti("vecchia/b.jpg", b"b")
    os.utime(banco.sorgente / "vecchia", ns=(10 ** 18, 10 ** 18))
    banco.giro()
    resoconto = _uscita(banco).estrai("r1", tmp_path / "fuori")
    fatta = Path(resoconto.cartella) / "vecchia"
    assert fatta.stat().st_mtime_ns == 10 ** 18


def test_non_si_sovrascrive_mai_si_aggiunge_il_numero(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    banco.metti("a.jpg", b"dall'archivio")
    banco.giro()
    fuori = tmp_path / "fuori"
    (fuori / "foto").mkdir(parents=True)
    (fuori / "foto" / "a.jpg").write_bytes(b"mio, non toccare")
    uscita = _uscita(banco)
    primo = uscita.estrai("r1", fuori)
    secondo = uscita.estrai("r1", fuori)
    assert primo.cartella == str(fuori / "foto (2)")
    assert secondo.cartella == str(fuori / "foto (3)")
    assert (fuori / "foto" / "a.jpg").read_bytes() == b"mio, non toccare"
    assert (fuori / "foto (2)" / "a.jpg").read_bytes() == b"dall'archivio"
    assert (fuori / "foto (3)" / "a.jpg").read_bytes() == b"dall'archivio"
    assert ("rinominato", "") in primo.problemi
    assert primo.verde


def test_un_file_solo_accanto_a_uno_uguale_prende_il_numero(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    banco.metti("2001/IMG_0001.jpg", b"archivio")
    banco.giro()
    fuori = tmp_path / "fuori"
    fuori.mkdir()
    (fuori / "IMG_0001.jpg").write_bytes(b"mio")
    (fuori / "IMG_0001 (2).jpg").write_bytes(b"anche mio")
    resoconto = _uscita(banco).estrai("r1", fuori, "2001/IMG_0001.jpg")
    assert resoconto.cartella == str(fuori / "IMG_0001 (3).jpg")
    assert (fuori / "IMG_0001 (3).jpg").read_bytes() == b"archivio"
    assert (fuori / "IMG_0001.jpg").read_bytes() == b"mio"
    assert (fuori / "IMG_0001 (2).jpg").read_bytes() == b"anche mio"
    assert resoconto.problemi == [("rinominato", "2001/IMG_0001.jpg")]


def test_un_file_che_c_e_come_cartella_prende_il_numero(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    banco.metti("a.jpg", b"file")
    banco.giro()
    fuori = tmp_path / "fuori"
    (fuori / "a.jpg").mkdir(parents=True)
    resoconto = _uscita(banco).estrai("r1", fuori, "a.jpg")
    assert (fuori / "a (2).jpg").read_bytes() == b"file"
    assert (fuori / "a.jpg").is_dir()
    assert resoconto.verde


def test_si_estrae_solo_una_sottocartella(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    banco.metti("2001/mare/a.jpg", b"a")
    banco.metti("2001/b.jpg", b"b")
    banco.metti("2002/c.jpg", b"c")
    banco.giro()
    resoconto = _uscita(banco).estrai("r1", tmp_path / "fuori", "2001")
    assert resoconto.cartella == str(tmp_path / "fuori" / "2001")
    assert _foto(tmp_path / "fuori") == {
        "2001": ("cartella", None), "2001/mare": ("cartella", None),
        "2001/mare/a.jpg": ("file", b"a"), "2001/b.jpg": ("file", b"b")}


def test_la_sottocartella_si_scrive_in_tanti_modi(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    banco.metti("2001/mare/a.jpg", b"a")
    banco.giro()
    uscita = _uscita(banco)
    for indice, sotto in enumerate(["2001/mare", "2001\\mare", "/2001/mare/"[1:],
                                    "./2001//mare"]):
        resoconto = uscita.estrai("r1", tmp_path / f"fuori{indice}", sotto)
        assert _foto(Path(resoconto.cartella)) == {"a.jpg": ("file", b"a")}
    with pytest.raises(ValueError):
        uscita.estrai("r1", tmp_path / "fuori9", "../fuori")


def test_una_cartella_sconosciuta_o_vuota_non_si_estrae(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    banco.metti("a.jpg", b"a")
    banco.giro()
    uscita = _uscita(banco)
    with pytest.raises(ErroreOfficina) as errore:
        uscita.estrai("nessuna", tmp_path / "fuori")
    assert errore.value.codice == "radice_sconosciuta"
    with pytest.raises(ErroreOfficina) as errore:
        uscita.estrai("r1", tmp_path / "fuori", "non/ce")
    assert errore.value.codice == "niente_da_estrarre"
    assert not (tmp_path / "fuori").exists()


@su_linux
def test_i_collegamenti_si_rifanno_come_collegamenti_e_per_ultimi(tmp_path, chiave,
                                                                  monkeypatch):
    banco = Banco(tmp_path, chiave)
    fuori_vero = tmp_path / "altrove"
    fuori_vero.mkdir()
    banco.metti("a.jpg", b"a")
    banco.metti("album/b.jpg", b"b")
    os.symlink(fuori_vero, banco.sorgente / "verso_fuori")
    os.symlink("a.jpg", banco.sorgente / "verso_a")
    os.symlink("nessuno", banco.sorgente / "rotto")
    os.symlink("../a.jpg", banco.sorgente / "album" / "su")
    banco.giro()
    creati = []
    vero = estrai.metadati.crea_collegamento

    def crea(percorso, metadati_):
        creati.append(Path(percorso).name)
        assert (tmp_path / "fuori" / "foto" / "album" / "b.jpg").exists()
        return vero(percorso, metadati_)

    monkeypatch.setattr(estrai.metadati, "crea_collegamento", crea)
    resoconto = _uscita(banco).estrai("r1", tmp_path / "fuori")
    assert resoconto.verde
    assert sorted(creati) == ["rotto", "su", "verso_a", "verso_fuori"]
    assert _foto(Path(resoconto.cartella)) == _foto(banco.sorgente)
    assert sorted(resoconto.bersagli) == sorted([
        ("album/su", "../a.jpg"), ("rotto", "nessuno"), ("verso_a", "a.jpg"),
        ("verso_fuori", str(fuori_vero))])
    assert resoconto.collegamenti == 4
    assert list(fuori_vero.iterdir()) == []


@su_linux
def test_dentro_un_collegamento_non_si_scrive_mai(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    altrove = tmp_path / "altrove"
    altrove.mkdir()
    banco.metti("vero.jpg", b"v")
    banco.giro()
    numero = banco.posto("vero.jpg").contenuto
    banco.elenco.registra([
        elenco.fatto_posto("r1", "link", "collegamento", None,
                           {"bersaglio": str(altrove)}),
        elenco.fatto_posto("r1", "link/dentro.jpg", "file", numero, {})])
    resoconto = _uscita(banco).estrai("r1", tmp_path / "fuori")
    fatta = Path(resoconto.cartella)
    assert list(altrove.iterdir()) == []
    assert (fatta / "link").is_dir() and not (fatta / "link").is_symlink()
    assert (fatta / "link" / "dentro.jpg").read_bytes() == b"v"
    assert (fatta / "link (2)").is_symlink()
    assert ("rinominato", "link") in resoconto.problemi


@su_linux
def test_se_una_cartella_diventa_un_collegamento_mi_fermo(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    for indice in range(6):
        banco.metti(f"album/{indice}.jpg", _dati(100, indice))
    banco.giro()
    altrove = tmp_path / "altrove"
    altrove.mkdir()
    fatti = []

    def aspetta():
        percorso = uscita.avanzamento.percorso
        if percorso == "album/3.jpg":
            fatti.append(percorso)
            if len(fatti) == 2:
                vera = tmp_path / "fuori" / "foto" / "album"
                vera.rename(tmp_path / "spostata")
                os.symlink(altrove, vera)

    uscita = _uscita(banco, aspetta=aspetta)
    with pytest.raises(ErroreOfficina) as errore:
        uscita.estrai("r1", tmp_path / "fuori")
    assert errore.value.codice == "dove_cambiato"
    assert list(altrove.iterdir()) == []
    assert sorted(percorso.name for percorso in (tmp_path / "spostata").iterdir()) == [
        "0.jpg", "1.jpg", "2.jpg", "3.jpg"]


@su_linux
def test_se_la_cartella_cambia_a_meta_file_non_tocco_quelli_altrove(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    for indice in range(3):
        banco.metti(f"album/{indice}.jpg", _dati(100, indice))
    banco.giro()
    altrove = tmp_path / "altrove"
    altrove.mkdir()
    for indice in range(3):
        (altrove / f"{indice}.jpg").write_bytes(b"dell'utente")
        os.utime(altrove / f"{indice}.jpg", ns=(10 ** 17, 10 ** 17))
    fatti = []

    def aspetta():
        if uscita.avanzamento.percorso == "album/1.jpg" and not fatti:
            fatti.append(1)
            vera = tmp_path / "fuori" / "foto" / "album"
            vera.rename(tmp_path / "spostata")
            os.symlink(altrove, vera)

    uscita = _uscita(banco, aspetta=aspetta)
    with pytest.raises(ErroreOfficina) as errore:
        uscita.estrai("r1", tmp_path / "fuori")
    assert errore.value.codice == "dove_cambiato"
    for indice in range(3):
        assert (altrove / f"{indice}.jpg").read_bytes() == b"dell'utente"
        assert (altrove / f"{indice}.jpg").stat().st_mtime_ns == 10 ** 17
    assert sorted(os.listdir(altrove)) == ["0.jpg", "1.jpg", "2.jpg"]


def test_le_versioni_vecchie_escono_con_il_momento_giusto(tmp_path, chiave):
    orologio = Orologio(2000.0)
    banco = Banco(tmp_path, chiave, adesso=orologio)
    a = banco.metti("a.jpg", b"uno")
    banco.metti("b.jpg", b"bi")
    banco.giro()
    orologio.ora = 3000.0
    a.write_bytes(b"due, piu lungo")
    os.utime(a, ns=(10 ** 18, 10 ** 18))
    (banco.sorgente / "b.jpg").unlink()
    banco.metti("c.jpg", b"ci")
    banco.giro()
    uscita = _uscita(banco)
    vecchio = uscita.estrai("r1", tmp_path / "vecchio", quando=2500.0)
    assert _foto(Path(vecchio.cartella)) == {"a.jpg": ("file", b"uno"),
                                             "b.jpg": ("file", b"bi")}
    nuovo = uscita.estrai("r1", tmp_path / "nuovo")
    assert _foto(Path(nuovo.cartella)) == {"a.jpg": ("file", b"due, piu lungo"),
                                           "c.jpg": ("file", b"ci")}
    with pytest.raises(ErroreOfficina) as errore:
        uscita.estrai("r1", tmp_path / "prima", quando=1500.0)
    assert errore.value.codice == "niente_da_estrarre"


def test_si_estrae_una_versione_di_un_file(tmp_path, chiave):
    orologio = Orologio(2000.0)
    banco = Banco(tmp_path, chiave, adesso=orologio)
    a = banco.metti("2001/a.jpg", b"prima")
    banco.giro()
    orologio.ora = 3000.0
    a.write_bytes(b"dopo, diversa")
    os.utime(a, ns=(10 ** 18, 10 ** 18))
    banco.giro()
    storia = banco.elenco.storia("r1", "2001/a.jpg")
    assert len(storia) == 2
    uscita = _uscita(banco)
    resoconto = uscita.estrai_versione(storia[0].chiave, tmp_path / "fuori")
    assert resoconto.cartella == str(tmp_path / "fuori" / "a.jpg")
    assert (tmp_path / "fuori" / "a.jpg").read_bytes() == b"prima"
    uscita.estrai_versione(storia[1].chiave, tmp_path / "fuori")
    assert (tmp_path / "fuori" / "a (2).jpg").read_bytes() == b"dopo, diversa"
    with pytest.raises(ErroreOfficina) as errore:
        uscita.estrai_versione("nessuna", tmp_path / "fuori")
    assert errore.value.codice == "versione_sconosciuta"


def test_si_estrae_una_cartella_cancellata_com_era_l_ultima_volta(tmp_path, chiave):
    orologio = Orologio(2000.0)
    banco = Banco(tmp_path, chiave, adesso=orologio)
    banco.metti("vacanze/a.jpg", b"a")
    banco.metti("vacanze/dentro/b.jpg", b"b")
    (banco.sorgente / "vacanze" / "vuota").mkdir()
    banco.giro()
    orologio.ora = 2500.0
    banco.metti("vacanze/c.jpg", b"c")
    banco.giro()
    orologio.ora = 3000.0
    for percorso in sorted(banco.sorgente.rglob("*"), reverse=True):
        percorso.rmdir() if percorso.is_dir() else percorso.unlink()
    banco.metti("altro.jpg", b"x")
    banco.giro()
    assert banco.posto("vacanze") is None
    cartella = banco.elenco.storia("r1", "vacanze")[-1]
    resoconto = _uscita(banco).estrai_versione(cartella.chiave, tmp_path / "fuori")
    assert _foto(Path(resoconto.cartella)) == {
        "a.jpg": ("file", b"a"), "c.jpg": ("file", b"c"),
        "dentro": ("cartella", None), "dentro/b.jpg": ("file", b"b"),
        "vuota": ("cartella", None)}
    assert Path(resoconto.cartella).name == "vacanze"


def test_un_pezzo_perso_esce_con_gli_zeri_e_si_dice_rosso(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    dati = _dati(3 * formato.BLOCCO + 17)
    banco.metti("a.jpg", dati)
    banco.metti("b.jpg", b"sana")
    banco.giro()
    _rovina_blocco(banco, banco.posto("a.jpg").contenuto, [1])
    resoconto = _uscita(banco).estrai("r1", tmp_path / "fuori")
    fatta = Path(resoconto.cartella)
    atteso = bytearray(dati)
    atteso[formato.BLOCCO:2 * formato.BLOCCO] = bytes(formato.BLOCCO)
    assert (fatta / "a.jpg").read_bytes() == bytes(atteso)
    assert (fatta / "b.jpg").read_bytes() == b"sana"
    assert resoconto.rossi == [("rovinato", "a.jpg")]
    assert not resoconto.verde and resoconto.finito


def test_un_pezzo_rovinato_che_si_ripara_esce_uguale(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    dati = _dati(40 * formato.BLOCCO)
    banco.metti("a.jpg", dati)
    banco.giro()
    _rovina_blocco(banco, banco.posto("a.jpg").contenuto, [5], tutto=False)
    resoconto = _uscita(banco).estrai("r1", tmp_path / "fuori")
    assert (Path(resoconto.cartella) / "a.jpg").read_bytes() == dati
    assert resoconto.verde


def _con_gemello(banco: Banco, dati: bytes) -> tuple[str, str]:
    banco.metti("a.jpg", dati)
    banco.giro()
    primo = banco.posto("a.jpg").contenuto
    banco.elenco.registra([elenco.fatto_stato(primo, "rovinato")])
    banco.giro()
    secondo = banco.posto("a.jpg").contenuto
    assert secondo != primo
    banco.elenco.registra([elenco.fatto_posto("r1", "vecchio.jpg", "file", primo,
                                              {})])
    banco.apri.aperti.clear()
    return primo, secondo


def _blob_aperti(banco: Banco) -> list[str]:
    return [Path(nome).stem for nome, _ in banco.apri.aperti if nome.endswith(".ofs")]


def test_un_file_rovinato_si_salva_dal_suo_gemello(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    dati = _dati(3 * formato.BLOCCO + 17)
    primo, secondo = _con_gemello(banco, dati)
    _rovina_blocco(banco, primo, [1])
    resoconto = _uscita(banco).estrai("r1", tmp_path / "fuori", "vecchio.jpg")
    assert (tmp_path / "fuori" / "vecchio.jpg").read_bytes() == dati
    assert resoconto.verde
    assert _blob_aperti(banco) == [secondo]


def test_un_file_creduto_buono_ma_rotto_passa_al_gemello(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    dati = _dati(3 * formato.BLOCCO + 17)
    primo, secondo = _con_gemello(banco, dati)
    banco.elenco.registra([elenco.fatto_stato(primo, "buono")])
    _rovina_blocco(banco, primo, [2])
    resoconto = _uscita(banco).estrai("r1", tmp_path / "fuori", "vecchio.jpg")
    assert (tmp_path / "fuori" / "vecchio.jpg").read_bytes() == dati
    assert resoconto.verde
    assert _blob_aperti(banco) == [primo, secondo]


def test_due_gemelli_rotti_in_punti_diversi_fanno_un_file_intero(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    dati = _dati(3 * formato.BLOCCO + 17)
    primo, secondo = _con_gemello(banco, dati)
    _rovina_blocco(banco, primo, [1])
    _rovina_blocco(banco, secondo, [2])
    for nome in ("a.jpg", "vecchio.jpg"):
        resoconto = _uscita(banco).estrai("r1", tmp_path / nome, nome)
        assert (tmp_path / nome / nome).read_bytes() == dati
        assert resoconto.verde, resoconto.problemi


def test_due_gemelli_rotti_nello_stesso_punto_danno_le_parti_buone(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    dati = _dati(3 * formato.BLOCCO + 17)
    primo, secondo = _con_gemello(banco, dati)
    _rovina_blocco(banco, primo, [1, 3])
    _rovina_blocco(banco, secondo, [1])
    resoconto = _uscita(banco).estrai("r1", tmp_path / "fuori", "a.jpg")
    uscito = (tmp_path / "fuori" / "a.jpg").read_bytes()
    atteso = bytearray(dati)
    atteso[formato.BLOCCO:2 * formato.BLOCCO] = bytes(formato.BLOCCO)
    assert uscito == bytes(atteso)
    assert resoconto.rossi == [("rovinato", "a.jpg")]


def test_un_file_tutto_perso_non_esce_fatto_di_zeri(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    banco.metti("a.jpg", _dati(2 * formato.BLOCCO))
    banco.metti("b.jpg", b"b")
    banco.giro()
    _rovina_blocco(banco, banco.posto("a.jpg").contenuto, [0, 1])
    resoconto = _uscita(banco).estrai("r1", tmp_path / "fuori")
    assert _foto(Path(resoconto.cartella)) == {"b.jpg": ("file", b"b")}
    assert resoconto.rossi == [("contenuto_mancante", "a.jpg")]


def test_un_file_incompleto_esce_col_suo_buco_e_si_dice(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    dati = _dati(10 * ALLINEA + 123)
    banco.metti("vecchia.jpg", dati)
    _settori_rotti(banco, "vecchia.jpg", [2 * ALLINEA])
    banco.giro()
    banco.apri.regole.clear()
    resoconto = _uscita(banco).estrai("r1", tmp_path / "fuori")
    uscito = (Path(resoconto.cartella) / "vecchia.jpg").read_bytes()
    atteso = bytearray(dati)
    atteso[2 * ALLINEA:3 * ALLINEA] = bytes(ALLINEA)
    assert uscito == bytes(atteso)
    assert resoconto.rossi == [("incompleto", "vecchia.jpg")]


def test_un_contenuto_che_manca_si_dice_e_il_resto_esce(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    banco.metti("a.jpg", b"perso")
    banco.metti("b.jpg", b"buono")
    banco.giro()
    banco.blob(banco.posto("a.jpg").contenuto).unlink()
    resoconto = _uscita(banco).estrai("r1", tmp_path / "fuori")
    assert _foto(Path(resoconto.cartella)) == {"b.jpg": ("file", b"buono")}
    assert resoconto.rossi == [("contenuto_mancante", "a.jpg")]


def test_un_contenuto_scambiato_con_un_altro_non_esce(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    banco.metti("a.jpg", b"aaaa")
    banco.metti("b.jpg", b"bbbbbb")
    banco.giro()
    a = banco.blob(banco.posto("a.jpg").contenuto)
    b = banco.blob(banco.posto("b.jpg").contenuto)
    a.write_bytes(b.read_bytes())
    resoconto = _uscita(banco).estrai("r1", tmp_path / "fuori")
    assert _foto(Path(resoconto.cartella)) == {"b.jpg": ("file", b"bbbbbb")}
    assert resoconto.rossi == [("contenuto_mancante", "a.jpg")]


def test_un_file_senza_contenuto_nell_elenco_si_dice(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    banco.metti("b.jpg", b"b")
    banco.giro()
    banco.elenco.registra([elenco.fatto_posto("r1", "a.jpg", "file", "f" * 32, {},
                                              quando=2000.0)])
    resoconto = _uscita(banco).estrai("r1", tmp_path / "fuori")
    assert resoconto.rossi == [("contenuto_mancante", "a.jpg")]
    assert _foto(Path(resoconto.cartella)) == {"b.jpg": ("file", b"b")}


def _scrive_male(banco: Banco, fuori: Path, quante: int | None = None):
    fatte = []

    def regola(percorso, senza_cache, volta, lettore):
        if senza_cache and percorso.startswith(os.fspath(fuori)) and (
                quante is None or len(fatte) < quante):
            fatte.append(percorso)
            return Finto(lettore, sporca={5})
        return lettore

    banco.apri.regole.append(regola)
    return fatte


def test_il_disco_dove_estrai_che_scrive_male_ferma_tutto(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    banco.metti("a.jpg", _dati(5000))
    banco.giro()
    fatte = _scrive_male(banco, tmp_path / "fuori")
    uscita = _uscita(banco)
    with pytest.raises(ErroreOfficina) as errore:
        uscita.estrai("r1", tmp_path / "fuori")
    assert errore.value.codice == "scritto_male"
    assert len(fatte) == estrai.TENTATIVI
    assert _foto(tmp_path / "fuori") == {"foto": ("cartella", None)}
    assert uscita.resoconto is not None and not uscita.resoconto.finito


def test_il_disco_dove_estrai_che_sbaglia_una_volta_si_riprova(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    dati = _dati(5000)
    banco.metti("a.jpg", dati)
    banco.giro()
    fatte = _scrive_male(banco, tmp_path / "fuori", quante=1)
    resoconto = _uscita(banco).estrai("r1", tmp_path / "fuori")
    assert len(fatte) == 1
    assert (Path(resoconto.cartella) / "a.jpg").read_bytes() == dati
    assert resoconto.verde


def test_un_errore_mentre_rileggo_conta_come_scritto_male(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    banco.metti("a.jpg", _dati(5000))
    banco.giro()
    fuori = tmp_path / "fuori"

    def regola(percorso, senza_cache, volta, lettore):
        if senza_cache and percorso.startswith(os.fspath(fuori)):
            return Finto(lettore, rotti=[0])
        return lettore

    banco.apri.regole.append(regola)
    with pytest.raises(ErroreOfficina) as errore:
        _uscita(banco).estrai("r1", fuori)
    assert errore.value.codice == "scritto_male"
    assert not (fuori / "foto" / "a.jpg").exists()


def test_con_poco_spazio_non_si_comincia(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    banco.metti("a.jpg", _dati(10_000))
    banco.giro()
    chiesti = []

    def spazio(dove):
        chiesti.append(dove)
        return estrai.MARGINE + 9_999

    with pytest.raises(ErroreOfficina) as errore:
        _uscita(banco, spazio=spazio).estrai("r1", tmp_path / "fuori" / "nuova")
    assert errore.value.codice == "poco_spazio"
    assert not (tmp_path / "fuori").exists()
    resoconto = _uscita(banco, spazio=lambda dove: estrai.MARGINE + 10_000).estrai(
        "r1", tmp_path / "fuori")
    assert resoconto.verde


def test_lo_spazio_conta_anche_i_flussi(tmp_path, chiave):
    banco, _, numero = _con_flusso(tmp_path, chiave, b"z" * 5000)
    uscita = _uscita(banco)
    assert uscita._peso(banco.elenco.dentro("r1")) == 3 + 5000


def test_non_si_estrae_dentro_l_archivio(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    banco.metti("a.jpg", b"a")
    banco.giro()
    uscita = _uscita(banco)
    for dove in (banco.archivio, banco.archivio / "dentro", banco.archivio / "a" / ".."):
        with pytest.raises(ErroreOfficina) as errore:
            uscita.estrai("r1", dove)
        assert errore.value.codice == "estrai_nell_archivio"
    assert not (banco.archivio / "dentro").exists()


@su_linux
def test_non_si_estrae_nell_archivio_passando_da_un_collegamento(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    banco.metti("a.jpg", b"a")
    banco.giro()
    os.symlink(banco.archivio, tmp_path / "scorciatoia")
    with pytest.raises(ErroreOfficina) as errore:
        _uscita(banco).estrai("r1", tmp_path / "scorciatoia" / "x")
    assert errore.value.codice == "estrai_nell_archivio"


@su_linux
def test_una_cartella_scelta_che_e_un_collegamento_si_segue(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    banco.metti("a.jpg", b"a")
    banco.giro()
    vera = tmp_path / "vera"
    vera.mkdir()
    os.symlink(vera, tmp_path / "scelta")
    resoconto = _uscita(banco).estrai("r1", tmp_path / "scelta")
    assert (vera / "foto" / "a.jpg").read_bytes() == b"a"
    assert resoconto.cartella == str(vera / "foto")


def test_una_cartella_scelta_che_e_un_file_non_va(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    banco.metti("a.jpg", b"a")
    banco.giro()
    (tmp_path / "file").write_bytes(b"x")
    with pytest.raises(ErroreOfficina) as errore:
        _uscita(banco).estrai("r1", tmp_path / "file")
    assert errore.value.codice == "dove_non_creato"
    assert (tmp_path / "file").read_bytes() == b"x"


def test_fermato_a_meta_file_toglie_il_pezzo_e_lascia_il_resto(tmp_path, chiave,
                                                              monkeypatch):
    monkeypatch.setattr(estrai, "OGNI_QUANTI_BLOCCHI", 1)
    banco = Banco(tmp_path, chiave)
    banco.metti("a.jpg", b"intero")
    banco.metti("b.jpg", _dati(5 * formato.BLOCCO))
    banco.metti("c.jpg", b"mai")
    banco.giro()
    volte = []

    def aspetta():
        if uscita.avanzamento.percorso == "b.jpg":
            volte.append(1)
            if len(volte) == 4:
                raise Fermato

    uscita = _uscita(banco, aspetta=aspetta)
    with pytest.raises(Fermato):
        uscita.estrai("r1", tmp_path / "fuori")
    assert _foto(tmp_path / "fuori" / "foto") == {"a.jpg": ("file", b"intero")}


def test_disco_pieno_mentre_estraggo_si_ferma_e_toglie_il_pezzo(tmp_path, chiave,
                                                               monkeypatch):
    banco = Banco(tmp_path, chiave)
    banco.metti("a.jpg", b"intero")
    banco.metti("b.jpg", _dati(3 * formato.BLOCCO))
    banco.giro()
    uscita = _uscita(banco)
    vera = estrai._Conta.write

    def scrivi(self, dati):
        if uscita.avanzamento.percorso == "b.jpg":
            raise OSError(errno.ENOSPC, "disco pieno")
        return vera(self, dati)

    monkeypatch.setattr(estrai._Conta, "write", scrivi)
    with pytest.raises(ErroreOfficina) as errore:
        uscita.estrai("r1", tmp_path / "fuori")
    assert errore.value.codice == "spazio_finito"
    assert _foto(tmp_path / "fuori" / "foto") == {"a.jpg": ("file", b"intero")}


def test_disco_pieno_creando_una_cartella_si_ferma(tmp_path, chiave, monkeypatch):
    banco = Banco(tmp_path, chiave)
    banco.metti("album/a.jpg", b"a")
    banco.giro()
    vero = os.mkdir

    def mkdir(percorso, *altro, **chiavi_):
        if os.fspath(percorso).endswith("album"):
            raise OSError(errno.ENOSPC, "pieno")
        return vero(percorso, *altro, **chiavi_)

    monkeypatch.setattr(estrai.os, "mkdir", mkdir)
    with pytest.raises(ErroreOfficina) as errore:
        _uscita(banco).estrai("r1", tmp_path / "fuori")
    assert errore.value.codice == "spazio_finito"


def test_una_cartella_che_non_si_crea_salta_solo_lei(tmp_path, chiave, monkeypatch):
    banco = Banco(tmp_path, chiave)
    banco.metti("album/a.jpg", b"a")
    banco.metti("album/sotto/b.jpg", b"b")
    banco.metti("altro/c.jpg", b"c")
    banco.giro()
    vero = os.mkdir

    def mkdir(percorso, *altro, **chiavi_):
        if os.fspath(percorso).endswith("album"):
            raise OSError(errno.EACCES, "vietato")
        return vero(percorso, *altro, **chiavi_)

    monkeypatch.setattr(estrai.os, "mkdir", mkdir)
    resoconto = _uscita(banco).estrai("r1", tmp_path / "fuori")
    assert _foto(Path(resoconto.cartella)) == {"altro": ("cartella", None),
                                               "altro/c.jpg": ("file", b"c")}
    assert sorted(resoconto.rossi) == [
        ("cartella_non_creata", "album"), ("cartella_non_creata", "album/sotto"),
        ("file_non_creato", "album/a.jpg"), ("file_non_creato", "album/sotto/b.jpg")]


def test_un_file_che_non_si_crea_salta_solo_lui(tmp_path, chiave, monkeypatch):
    banco = Banco(tmp_path, chiave)
    banco.metti("a.jpg", b"a")
    banco.metti("b.jpg", b"b")
    banco.giro()
    vero = estrai._nuovo_file

    def nuovo(prova):
        if prova.name == "a.jpg":
            raise OSError(errno.ENAMETOOLONG, "nome troppo lungo")
        return vero(prova)

    monkeypatch.setattr(estrai, "_nuovo_file", nuovo)
    resoconto = _uscita(banco).estrai("r1", tmp_path / "fuori")
    assert _foto(Path(resoconto.cartella)) == {"b.jpg": ("file", b"b")}
    assert resoconto.rossi == [("file_non_creato", "a.jpg")]


def test_se_il_disco_dell_archivio_sparisce_mi_fermo(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    banco.metti("a.jpg", b"a")
    banco.metti("b.jpg", b"b")
    banco.giro()
    contenuti = banco.archivio / elenco.CONTENUTI

    def aspetta():
        if uscita.avanzamento.percorso == "a.jpg" and contenuti.exists():
            contenuti.rename(tmp_path / "staccato")

    uscita = _uscita(banco, aspetta=aspetta)
    with pytest.raises(ErroreOfficina) as errore:
        uscita.estrai("r1", tmp_path / "fuori")
    assert errore.value.codice == "archivio_sparito"
    assert _foto(tmp_path / "fuori" / "foto") == {"a.jpg": ("file", b"a")}
    (tmp_path / "staccato").rename(contenuti)


def _con_flusso(tmp_path: Path, chiave, dati: bytes, nome="Zone.Identifier"):
    banco = Banco(tmp_path, chiave)
    banco.metti("a.jpg", b"aaa")
    banco.giro()
    altra = tmp_path / "altra"
    altra.mkdir()
    (altra / "zona.txt").write_bytes(dati)
    banco.elenco.registra([elenco.fatto_radice("r2", str(altra), quando=1001.0)])
    banco.copiatore.copia_radice(banco.radice("r2"))
    numero = banco.elenco.attuale("r2", "zona.txt").contenuto
    banco.elenco.registra([elenco.fatto_flusso(banco.posto("a.jpg").chiave, nome,
                                               numero)])
    return banco, banco.posto("a.jpg"), numero


def test_i_flussi_nascosti_si_rimettono(tmp_path, chiave):
    dati = b"[ZoneTransfer]\r\nZoneId=3\r\n"
    banco, _, _ = _con_flusso(tmp_path, chiave, dati)
    flussi = Flussi(tmp_path / "flussi")
    resoconto = _uscita(banco, apri_flusso=flussi).estrai("r1", tmp_path / "fuori")
    fatto = Path(resoconto.cartella) / "a.jpg"
    assert fatto.read_bytes() == b"aaa"
    assert flussi.dove(fatto, "Zone.Identifier").read_bytes() == dati
    assert resoconto.verde and resoconto.problemi == []
    modi = [modo for _, _, modo in flussi.aperti]
    assert modi == ["wb", "rb"]


def test_senza_windows_i_flussi_si_dicono_non_rimessi(tmp_path, chiave):
    banco, _, _ = _con_flusso(tmp_path, chiave, b"zona")
    resoconto = _uscita(banco, windows=False).estrai("r1", tmp_path / "fuori")
    assert resoconto.problemi == [("flussi_non_rimessi", "a.jpg")]
    assert resoconto.verde
    assert (Path(resoconto.cartella) / "a.jpg").read_bytes() == b"aaa"


def test_un_disco_senza_flussi_non_ferma_il_file(tmp_path, chiave):
    banco, _, _ = _con_flusso(tmp_path, chiave, b"zona")

    def rompi(percorso, nome, modo):
        raise OSError(errno.EINVAL, "questo disco non ha flussi")

    resoconto = _uscita(banco, apri_flusso=Flussi(tmp_path / "flussi", rompi)).estrai(
        "r1", tmp_path / "fuori")
    assert resoconto.problemi == [("flussi_non_rimessi", "a.jpg")]
    assert (Path(resoconto.cartella) / "a.jpg").read_bytes() == b"aaa"


def test_un_flusso_che_si_rilegge_diverso_si_dice(tmp_path, chiave):
    banco, _, _ = _con_flusso(tmp_path, chiave, b"zona zona")
    flussi = Flussi(tmp_path / "flussi")
    vero = flussi.__call__

    class Sporco:

        def __init__(self, file):
            self._file = file

        def read(self, quanti=-1):
            dati = self._file.read(quanti)
            return dati[:-1] + b"!" if dati else dati

        def __enter__(self):
            return self

        def __exit__(self, *altro):
            self._file.close()

    def apri(percorso, nome, modo="rb"):
        file = vero(percorso, nome, modo)
        return Sporco(file) if modo == "rb" else file

    resoconto = _uscita(banco, apri_flusso=apri).estrai("r1", tmp_path / "fuori")
    assert resoconto.rossi == [("flusso_scritto_male", "a.jpg")]
    assert (Path(resoconto.cartella) / "a.jpg").read_bytes() == b"aaa"


def test_un_flusso_col_nome_strano_non_si_scrive(tmp_path, chiave):
    banco, _, _ = _con_flusso(tmp_path, chiave, b"zona", nome="cattivo:$DATA")
    flussi = Flussi(tmp_path / "flussi")
    resoconto = _uscita(banco, apri_flusso=flussi).estrai("r1", tmp_path / "fuori")
    assert resoconto.problemi == [("flusso_strano", "a.jpg")]
    assert flussi.aperti == []


def test_un_flusso_perso_si_dice_e_il_file_resta(tmp_path, chiave):
    banco, _, numero = _con_flusso(tmp_path, chiave, b"zona")
    banco.blob(numero).unlink()
    resoconto = _uscita(banco, apri_flusso=Flussi(tmp_path / "flussi")).estrai(
        "r1", tmp_path / "fuori")
    assert resoconto.rossi == [("flusso_mancante", "a.jpg")]
    assert (Path(resoconto.cartella) / "a.jpg").read_bytes() == b"aaa"


def test_su_windows_i_nomi_vietati_si_cambiano(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    banco.metti("a:b.jpg", b"due punti")
    banco.metti("dove?/con.jpg", b"riservato")
    banco.metti("fine. ", b"punto e spazio")
    banco.giro()
    resoconto = _uscita(banco, windows=True).estrai("r1", tmp_path / "fuori")
    assert _foto(Path(resoconto.cartella)) == {
        "a_b.jpg": ("file", b"due punti"), "dove_": ("cartella", None),
        "dove_/_con.jpg": ("file", b"riservato"),
        "fine_": ("file", b"punto e spazio")}
    assert sorted(resoconto.problemi) == [
        ("nome_cambiato", "a:b.jpg"), ("nome_cambiato", "dove?"),
        ("nome_cambiato", "dove?/con.jpg"), ("nome_cambiato", "fine. ")]
    assert resoconto.verde


def test_i_segni_in_uso_e_diverso_si_dicono(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    banco.metti("b.jpg", b"b")
    banco.giro()
    numero = banco.posto("b.jpg").contenuto
    banco.elenco.registra([elenco.fatto_posto("r1", "a.db", "file", numero, {},
                                              segni=["in_uso", "diverso_da_prima"],
                                              quando=2000.0)])
    resoconto = _uscita(banco).estrai("r1", tmp_path / "fuori")
    assert sorted(resoconto.problemi) == [("diverso_da_prima", "a.db"),
                                          ("in_uso", "a.db")]
    assert resoconto.verde


@pytest.mark.parametrize("nome, volta, cartella, atteso", [
    ("IMG.jpg", 1, False, "IMG.jpg"),
    ("IMG.jpg", 2, False, "IMG (2).jpg"),
    ("IMG.tar.gz", 3, False, "IMG.tar (3).gz"),
    (".nascosto", 2, False, ".nascosto (2)"),
    ("senza", 2, False, "senza (2)"),
    ("Foto.2020", 2, True, "Foto.2020 (2)"),
    ("Foto", 10, True, "Foto (10)"),
    ("a.", 2, False, "a (2)."),
])
def test_con_numero(nome, volta, cartella, atteso):
    assert estrai.con_numero(nome, volta, cartella) == atteso


@pytest.mark.parametrize("percorso, atteso", [
    ("C:\\Users\\Mario\\Pictures", "Pictures"),
    ("D:\\", "Disco D"),
    ("d:", "Disco D"),
    ("/home/mario/Foto/", "Foto"),
    ("", "Cartella"),
    ("\\\\server\\condivisa\\Album 2001", "Album 2001"),
])
def test_nome_della_radice(percorso, atteso):
    assert estrai.nome_della_radice(percorso) == atteso


@pytest.mark.parametrize("nome, atteso", [
    ("normale.jpg", "normale.jpg"),
    ("a:b.jpg", "a_b.jpg"),
    ('<>:"|?*', "_______"),
    ("CON", "_CON"),
    ("nul.txt", "_nul.txt"),
    ("com1", "_com1"),
    ("console.txt", "console.txt"),
    ("fine.", "fine_"),
    ("fine ", "fine_"),
    ("...", "_"),
    ("\x01x", "_x"),
])
def test_nome_per_windows(nome, atteso):
    assert estrai.nome_per_windows(nome) == atteso


def test_estrai_tutto_mette_ogni_cartella_accanto(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    banco.metti("a.jpg", b"primo")
    banco.giro()
    seconda = tmp_path / "altro" / "foto"
    seconda.mkdir(parents=True)
    (seconda / "b.jpg").write_bytes(b"secondo")
    banco.elenco.registra([elenco.fatto_radice("r2", str(seconda), quando=1001.0)])
    banco.copiatore.copia_radice(banco.radice("r2"))
    vuota = tmp_path / "vuota"
    vuota.mkdir()
    banco.elenco.registra([elenco.fatto_radice("r3", str(vuota), quando=1002.0)])
    uscita = _uscita(banco)
    richieste = uscita.richieste_per_tutto(tmp_path / "fuori")
    assert [richiesta["radice"] for richiesta in richieste] == ["r1", "r2"]
    for richiesta in richieste:
        uscita.estrai(richiesta["radice"], richiesta["dove"],
                      quando=richiesta["quando"])
    assert _foto(tmp_path / "fuori") == {
        "foto": ("cartella", None), "foto/a.jpg": ("file", b"primo"),
        "foto (2)": ("cartella", None), "foto (2)/b.jpg": ("file", b"secondo")}


def _aspetta_che(condizione, quanto=ATTESA):
    import time

    fine = time.monotonic() + quanto
    while time.monotonic() < fine:
        if condizione():
            return True
        time.sleep(0.01)
    return False


def test_l_estrazione_in_sottofondo_fa_tutte_le_richieste(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    banco.metti("2001/a.jpg", b"a")
    banco.metti("2002/b.jpg", b"b")
    banco.giro()
    lavoro = Estrazione(banco.archivio, banco.elenco, banco.chiave, sveglio=_sveglio,
                        spazio=lambda dove: LIBERO, apri=banco.apri)
    versione = banco.posto("2002/b.jpg").chiave
    assert lavoro.avvia([
        {"radice": "r1", "dove": tmp_path / "tutto"},
        {"radice": "r1", "dove": tmp_path / "solo", "sotto": "2001"},
        {"radice": "nessuna", "dove": tmp_path / "x"},
        {"chiave": versione, "dove": tmp_path / "versione"},
    ])
    assert lavoro.aspetta_fine(ATTESA)
    assert lavoro.stato == sottofondo.FINITO
    assert [resoconto.verde for resoconto in lavoro.resoconti] == [True] * 3
    assert lavoro.rifiutate == [({"radice": "nessuna", "dove": tmp_path / "x"},
                                 "radice_sconosciuta")]
    assert (tmp_path / "solo" / "2001" / "a.jpg").read_bytes() == b"a"
    assert (tmp_path / "versione" / "b.jpg").read_bytes() == b"b"
    istantanea = lavoro.istantanea()
    assert istantanea["stato"] == "finito"
    assert istantanea["rifiutate"] == ["radice_sconosciuta"]
    assert [fatta["verde"] for fatta in istantanea["fatte"]] == [True] * 3


def test_l_estrazione_in_sottofondo_si_ferma_su_un_guaio_grave(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    banco.metti("a.jpg", _dati(3000))
    banco.giro()
    _scrive_male(banco, tmp_path)
    lavoro = Estrazione(banco.archivio, banco.elenco, banco.chiave, sveglio=_sveglio,
                        spazio=lambda dove: LIBERO, apri=banco.apri)
    lavoro.avvia([{"radice": "r1", "dove": tmp_path / "uno"},
                  {"radice": "r1", "dove": tmp_path / "due"}])
    assert lavoro.aspetta_fine(ATTESA)
    assert lavoro.stato == sottofondo.ERRORE
    assert lavoro.codice == "scritto_male"
    assert len(lavoro.resoconti) == 1 and not lavoro.resoconti[0].finito
    assert not (tmp_path / "due").exists()


def test_l_estrazione_in_sottofondo_va_in_pausa_e_si_ferma(tmp_path, chiave,
                                                          monkeypatch):
    import threading

    monkeypatch.setattr(estrai, "OGNI_QUANTI_BLOCCHI", 1)
    banco = Banco(tmp_path, chiave)
    for indice in range(4):
        banco.metti(f"{indice}.jpg", _dati(4 * formato.BLOCCO, indice))
    banco.giro()
    porta = threading.Event()
    dentro = threading.Event()

    def rallenta():
        if lavoro.estrattore.avanzamento.percorso == "1.jpg":
            dentro.set()
            porta.wait(ATTESA)
        return False

    lavoro = Estrazione(banco.archivio, banco.elenco, banco.chiave, sveglio=_sveglio,
                        rallenta=rallenta, spazio=lambda dove: LIBERO, apri=banco.apri)
    lavoro.avvia([{"radice": "r1", "dove": tmp_path / "fuori"}])
    assert dentro.wait(ATTESA)
    lavoro.pausa()
    assert lavoro.stato == sottofondo.IN_PAUSA
    porta.set()
    assert not lavoro.aspetta_fine(0.2)
    lavoro.ferma()
    assert lavoro.aspetta_fine(ATTESA)
    assert lavoro.stato == sottofondo.FERMATO
    fatti = _foto(tmp_path / "fuori" / "foto")
    assert set(fatti) <= {"0.jpg", "1.jpg"}
    for nome, (_, dati) in fatti.items():
        assert dati == _dati(4 * formato.BLOCCO, int(nome[0]))
    assert len(lavoro.resoconti) == 1 and not lavoro.resoconti[0].finito


NOMI = ["IMG_0001.jpg", "IMG_0001.JPG", "foto.png", "video.mov", ".nascosto",
        "senza", "spazi e accenti è.heic", "✨.jpg", "a.b.c", "Natale",
        "0123456789abcdef0123456789abcdef", "(2)", "foto (2).png"]
MISURE = [0, 1, 17, 4096, formato.BLOCCO - 1, formato.BLOCCO, formato.BLOCCO + 1,
          2 * formato.BLOCCO + 5]


def _albero_a_caso(caso: random.Random, sorgente: Path) -> None:
    for _ in range(caso.randint(1, 14)):
        parti = [caso.choice(NOMI) for _ in range(caso.randint(1, 4))]
        percorso = sorgente.joinpath(*parti)
        if any(sopra.exists() and not sopra.is_dir()
               for sopra in list(percorso.parents)[:len(parti) - 1]):
            continue
        if percorso.exists():
            continue
        if caso.random() < 0.15:
            percorso.mkdir(parents=True)
            continue
        percorso.parent.mkdir(parents=True, exist_ok=True)
        misura = caso.choice(MISURE) if caso.random() < 0.7 else caso.randint(0, 150_000)
        dati = caso.randbytes(misura) if caso.random() < 0.8 else b"doppione" * 3
        percorso.write_bytes(dati)


def _sottoalbero(albero: dict, sotto: str) -> dict:
    if not sotto:
        return albero
    return {relativo[len(sotto) + 1:]: voce for relativo, voce in albero.items()
            if relativo.startswith(sotto + "/")}


@pytest.mark.parametrize("seme", range(40))
def test_a_caso_esce_sempre_uguale_e_mai_sopra_altro(tmp_path, chiave, seme):
    caso = random.Random(seme)
    banco = Banco(tmp_path, chiave)
    _albero_a_caso(caso, banco.sorgente)
    if not any(banco.sorgente.iterdir()):
        banco.metti("almeno.jpg", b"uno")
    assert banco.giro().verde
    sorgente = _foto(banco.sorgente)
    fuori = tmp_path / "fuori"
    fuori.mkdir()
    gia = {}
    for _ in range(caso.randint(0, 3)):
        nome = caso.choice(["foto", "foto (2)", *NOMI])
        percorso = fuori / nome
        if percorso.exists():
            continue
        if caso.random() < 0.5:
            percorso.mkdir()
            gia[nome] = ("cartella", None)
        else:
            percorso.write_bytes(nome.encode())
            gia[nome] = ("file", nome.encode())
    cartelle = [relativo for relativo, (tipo, _) in sorgente.items()
                if tipo == "cartella"]
    sotto = caso.choice(cartelle) if cartelle and caso.random() < 0.4 else ""
    uscita = _uscita(banco)
    resoconto = uscita.estrai("r1", fuori, sotto)
    assert resoconto.verde, resoconto.problemi
    fatta = Path(resoconto.cartella)
    assert fatta.parent == fuori
    assert _foto(fatta) == _sottoalbero(sorgente, sotto)
    for nome, voce in gia.items():
        percorso = fuori / nome
        if voce[0] == "file":
            assert percorso.read_bytes() == voce[1]
        else:
            assert percorso.is_dir()
            if fatta != percorso:
                assert list(percorso.iterdir()) == []
    vere = {parte for relativo in sorgente for parte in relativo.split("/")}
    for nome in _nomi(fatta):
        assert nome in vere
        if ESADECIMALE.match(nome):
            assert nome == "0123456789abcdef0123456789abcdef"


@pytest.mark.parametrize("seme", range(40))
def test_a_caso_fermato_lascia_solo_file_interi(tmp_path, chiave, seme, monkeypatch):
    monkeypatch.setattr(estrai, "OGNI_QUANTI_BLOCCHI", 1)
    caso = random.Random(1000 + seme)
    banco = Banco(tmp_path, chiave)
    _albero_a_caso(caso, banco.sorgente)
    banco.metti("grande.mov", caso.randbytes(3 * formato.BLOCCO))
    banco.giro()
    sorgente = _foto(banco.sorgente)
    limite = caso.randint(1, 30)
    chiamate = []

    def aspetta():
        chiamate.append(1)
        if len(chiamate) == limite:
            raise Fermato

    uscita = _uscita(banco, aspetta=aspetta)
    try:
        resoconto = uscita.estrai("r1", tmp_path / "fuori")
    except Fermato:
        resoconto = None
    fatta = tmp_path / "fuori" / "foto"
    uscito = _foto(fatta)
    for relativo, voce in uscito.items():
        if voce[0] == "file":
            assert sorgente[relativo] == voce
        else:
            assert sorgente[relativo][0] == voce[0]
    if resoconto is not None:
        assert uscito == sorgente
    di_nuovo = _uscita(banco).estrai("r1", tmp_path / "fuori")
    assert di_nuovo.cartella == str(tmp_path / "fuori" / "foto (2)")
    assert _foto(Path(di_nuovo.cartella)) == sorgente


@pytest.mark.parametrize("seme", range(25))
def test_a_caso_ogni_momento_esce_com_era(tmp_path, chiave, seme):
    caso = random.Random(5000 + seme)
    orologio = Orologio(2000.0)
    banco = Banco(tmp_path, chiave, adesso=orologio)
    momenti = []
    for giro in range(4):
        orologio.ora = 2000.0 + 1000 * giro
        file = sorted(percorso for percorso in banco.sorgente.rglob("*")
                      if percorso.is_file())
        for percorso in file:
            scelta = caso.random()
            if scelta < 0.25:
                percorso.unlink()
            elif scelta < 0.5:
                percorso.write_bytes(caso.randbytes(caso.choice(MISURE)))
                quando = (10 ** 18) + giro * 10 ** 9 + caso.randint(0, 10 ** 6)
                os.utime(percorso, ns=(quando, quando))
        _albero_a_caso(caso, banco.sorgente)
        banco.giro()
        momenti.append((orologio.ora, _foto(banco.sorgente)))
    uscita = _uscita(banco)
    for indice, (quando, atteso) in enumerate(momenti):
        if not atteso:
            continue
        resoconto = uscita.estrai("r1", tmp_path / f"fuori{indice}", quando=quando + 1)
        assert _foto(Path(resoconto.cartella)) == atteso, indice
        assert resoconto.verde
