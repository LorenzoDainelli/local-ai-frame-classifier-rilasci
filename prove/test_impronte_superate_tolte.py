from __future__ import annotations

import contextlib
import sqlite3

import pytest

from officina import descrittori
from officina.descrittori import sgombero
from officina.descrittori.grandi import Radio4
from officina.modello import impronte as magazzino
from officina.programma import novita


class ArchivioFinto:

    def __init__(self):
        self.connessione = sqlite3.connect(":memory:")
        self.connessione.execute(
            "CREATE TABLE impronte (id INTEGER PRIMARY KEY, descrittore TEXT, "
            "versione TEXT, dimensione INTEGER)")

    @contextlib.contextmanager
    def scrittura(self):
        with self.connessione:
            yield self.connessione

    def metti(self, descrittore, versione, quante, dimensione):
        for _ in range(quante):
            self.connessione.execute(
                "INSERT INTO impronte (descrittore, versione, dimensione) VALUES (?, ?, ?)",
                (descrittore, versione, dimensione))

    def quante(self, descrittore):
        riga = self.connessione.execute(
            "SELECT count(*) FROM impronte WHERE descrittore = ?", (descrittore,)).fetchone()
        return riga[0]


@pytest.fixture
def mondo(monkeypatch):
    from officina.programma import carta

    prima = carta.leggi()
    tutta = dict(prima)
    tutta.pop(sgombero.CHIAVE_CARTA, None)
    tutta.pop(sgombero.CHIAVE_DA_COMPATTARE, None)
    carta.scrivi(tutta)
    stato = {"superato": True, "da_fare": 0}
    monkeypatch.setitem(descrittori.SCHEDE, "radio4", Radio4.scheda)
    monkeypatch.setattr(descrittori, "superato_da", lambda nome, _: (
        "radio4" if nome == "siglip2" and stato["superato"] else None))
    monkeypatch.setattr(magazzino, "quanti_da_fare", lambda _c, _n, _v: stato["da_fare"])
    archivio = ArchivioFinto()
    archivio.metti("siglip2", "1", 3, 1152)
    archivio.metti("dinov3", "1", 2, 1024)
    archivio.metti("radio4", Radio4.scheda.versione, 3, 1536)
    yield archivio, stato
    carta.scrivi(prima)


def test_finite_le_nuove_si_tolgono_le_vecchie_e_si_dice(mondo, tmp_path):
    archivio, _ = mondo
    tolte = sgombero.togli_le_superate(archivio, tmp_path)
    assert tolte == {"siglip2": {"impronte": 3, "byte": 3 * 1152 * 4, "da": "radio4"}}
    assert archivio.quante("siglip2") == 0
    assert archivio.quante("dinov3") == 2 and archivio.quante("radio4") == 3
    detto = sgombero.da_dire_superate("siglip2")
    assert "3 impronte vecchie di SigLIP 2 so400m" in detto
    assert "C-RADIOv4-H" in detto and "occupavano 1 MB" in detto and "vestiti" in detto
    righe = novita._con_le_pulizie({"semplice": [], "tolti": ["siglip2"]})
    assert righe == [["disco", detto]]


def test_durante_il_rifacimento_non_si_tocca_niente(mondo, tmp_path):
    archivio, stato = mondo
    stato["da_fare"] = 40
    assert sgombero.togli_le_superate(archivio, tmp_path) == {}
    assert archivio.quante("siglip2") == 3
    assert sgombero.da_dire_superate("siglip2") == ""


def test_senza_radio4_in_casa_non_si_tocca_niente(mondo, tmp_path):
    archivio, stato = mondo
    stato["superato"] = False
    assert sgombero.togli_le_superate(archivio, tmp_path) == {}
    assert archivio.quante("siglip2") == 3


def test_senza_impronte_nuove_non_si_tocca_niente(mondo, tmp_path):
    archivio, _ = mondo
    archivio.connessione.execute("DELETE FROM impronte WHERE descrittore = 'radio4'")
    assert sgombero.togli_le_superate(archivio, tmp_path) == {}
    assert archivio.quante("siglip2") == 3


def test_impronte_nuove_di_versione_vecchia_non_bastano(mondo, tmp_path):
    archivio, _ = mondo
    archivio.connessione.execute("UPDATE impronte SET versione = 'vecchia' "
                                 "WHERE descrittore = 'radio4'")
    assert sgombero.togli_le_superate(archivio, tmp_path) == {}
    assert archivio.quante("siglip2") == 3


def test_la_seconda_volta_non_dice_di_piu(mondo, tmp_path):
    archivio, _ = mondo
    sgombero.togli_le_superate(archivio, tmp_path)
    assert sgombero.togli_le_superate(archivio, tmp_path) == {}
    assert "3 impronte" in sgombero.da_dire_superate("siglip2")


class ArchivioSulDisco:

    def __init__(self, cartella):
        from types import SimpleNamespace

        self.dove = SimpleNamespace(database=cartella / "archivio.db")
        self.connessione = sqlite3.connect(self.dove.database, isolation_level=None)
        self.connessione.execute("PRAGMA journal_mode = WAL")
        self.connessione.execute("CREATE TABLE impronte (dati BLOB)")
        for _ in range(400):
            self.connessione.execute("INSERT INTO impronte VALUES (?)", (b"x" * 4096,))
        self.connessione.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        self.connessione.execute("DELETE FROM impronte")
        self.compattato = 0

    def compatta(self):
        self.compattato += 1
        self.connessione.execute("VACUUM")
        self.connessione.execute("PRAGMA wal_checkpoint(TRUNCATE)")


def _spazio(libero):
    return lambda _: type("U", (), {"free": libero})()


def test_al_riavvio_compatta_una_volta_e_dice_i_gb_veri(mondo, tmp_path):
    archivio, _ = mondo
    sgombero.togli_le_superate(archivio, tmp_path)
    sul_disco = ArchivioSulDisco(tmp_path)
    liberati = sgombero.compatta_se_serve(sul_disco, ram=lambda: 10 ** 12,
                                          disco=_spazio(10 ** 12))
    assert liberati > 1_000_000 and sul_disco.compattato == 1
    voluto = f"sul disco hai {round(liberati / 2 ** 20)} MB liberi in più"
    assert voluto in sgombero.da_dire_superate("siglip2")
    assert sgombero.compatta_se_serve(sul_disco, ram=lambda: 10 ** 12,
                                      disco=_spazio(10 ** 12)) == 0
    assert sul_disco.compattato == 1


@pytest.mark.parametrize("ram, libero", [(None, 10 ** 12), (1000, 10 ** 12),
                                         (10 ** 12, 10 ** 6)])
def test_con_poca_ram_o_poco_disco_rimanda(mondo, tmp_path, ram, libero):
    archivio, _ = mondo
    sgombero.togli_le_superate(archivio, tmp_path)
    sul_disco = ArchivioSulDisco(tmp_path)
    assert sgombero.compatta_se_serve(sul_disco, ram=lambda: ram, disco=_spazio(libero)) == 0
    assert sul_disco.compattato == 0
    assert "occupavano" in sgombero.da_dire_superate("siglip2")
    assert sgombero.compatta_se_serve(sul_disco, ram=lambda: 10 ** 12,
                                      disco=_spazio(10 ** 12)) > 0


def test_senza_niente_di_cancellato_non_compatta(mondo, tmp_path):
    sul_disco = ArchivioSulDisco(tmp_path)
    assert sgombero.compatta_se_serve(sul_disco, ram=lambda: 10 ** 12,
                                      disco=_spazio(10 ** 12)) == 0
    assert sul_disco.compattato == 0


def test_l_archivio_vero_si_compatta(tmp_path):
    from officina.archivio import accesso

    assert callable(getattr(accesso.Archivio, "compatta", None))
