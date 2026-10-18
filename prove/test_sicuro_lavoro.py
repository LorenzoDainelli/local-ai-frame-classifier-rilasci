from __future__ import annotations

import errno
import os
import random
import threading
import time
from contextlib import contextmanager
from pathlib import Path

import pytest

from officina.sicuro import chiavi, copia, disco, elenco, formato, lavoro, sveglia
from officina.sicuro.elenco import Elenco
from officina.sicuro.lavoro import Lavoro
from prove.test_sicuro_copia import Apri

PIENO = 10 ** 15
ATTESA = 20.0


@pytest.fixture
def chiave():
    return chiavi.Chiave(bytes(range(32)))


class Disco:

    def __init__(self, libero=PIENO, totale=PIENO):
        self.libero = libero
        self.totale = totale
        self.chiesto = 0
        self.porta = None

    def __call__(self, cartella):
        self.chiesto += 1
        if self.porta is not None:
            self.porta.wait(ATTESA)
        return self.libero, self.totale


class Sveglio:

    def __init__(self):
        self.entrate = 0
        self.uscite = 0

    @contextmanager
    def __call__(self):
        self.entrate += 1
        try:
            yield True
        finally:
            self.uscite += 1


class Banco:

    def __init__(self, cartella: Path, chiave, radici=("r1",), **opzioni):
        self.cartella = cartella
        self.archivio = cartella / "archivio"
        self.chiave = chiave
        self.elenco = Elenco.apri(self.archivio, chiave)
        self.sorgenti = {}
        for indice, id in enumerate(radici):
            self.sorgenti[id] = cartella / id
            self.sorgenti[id].mkdir(exist_ok=True)
            if not any(radice["id"] == id for radice in self.elenco.radici()):
                self.elenco.registra([elenco.fatto_radice(
                    id, str(self.sorgenti[id]), quando=1000.0 + indice)])
        self.disco = opzioni.pop("disco", Disco())
        self.sveglio = Sveglio()
        self.apri = Apri()
        opzioni.setdefault("apri", self.apri)
        self.lavoro = Lavoro(self.archivio, self.elenco, chiave, disco=self.disco,
                             sveglio=self.sveglio, **opzioni)
        self.ordine: list[str] = []
        vera = self.lavoro.copiatore.copia_radice

        def copia_radice(radice):
            self.ordine.append(radice["id"])
            return vera(radice)

        self.lavoro.copiatore.copia_radice = copia_radice

    def metti(self, id: str, relativo: str, dati: bytes) -> Path:
        percorso = self.sorgenti[id] / relativo
        percorso.parent.mkdir(parents=True, exist_ok=True)
        percorso.write_bytes(dati)
        return percorso

    def fino_alla_fine(self, **avvia):
        assert self.lavoro.avvia(**avvia)
        assert self.lavoro.aspetta_fine(ATTESA)
        return self.lavoro.istantanea()

    def provvisori(self):
        return [percorso for percorso in self.archivio.rglob("*")
                if percorso.name.endswith(copia.PROVVISORI)]

    def dati(self, numero: str) -> bytes:
        with open(elenco.percorso_contenuto(self.archivio, numero), "rb") as file:
            return formato.Contenuto(file, self.chiave,
                                     numero=bytes.fromhex(numero)).tutto()


def _finche(condizione, quanto=ATTESA):
    fine = time.monotonic() + quanto
    while time.monotonic() < fine:
        if condizione():
            return True
        time.sleep(0.005)
    return condizione()


def test_si_copia_tutto_e_il_pc_resta_sveglio(tmp_path, chiave):
    banco = Banco(tmp_path, chiave, radici=("r1", "r2"))
    banco.metti("r1", "a.jpg", b"aaa")
    banco.metti("r2", "b/c.jpg", b"ccc")
    vecchio = banco.archivio / elenco.CONTENUTI / "ab" / ("ab" * 16 + ".ofs.nuovo")
    vecchio.parent.mkdir(parents=True)
    vecchio.write_bytes(b"avanzo")
    fine = banco.fino_alla_fine()
    assert fine["stato"] == lavoro.FINITO
    assert fine["fatte"] == ["r1", "r2"] and fine["verdi"] == ["r1", "r2"]
    assert fine["rosse"] == {} and fine["errore"] is None
    assert banco.sveglio.entrate == banco.sveglio.uscite == 1
    assert not vecchio.exists() and banco.provvisori() == []
    assert banco.elenco.attuale("r1", "a.jpg") is not None
    assert banco.elenco.attuale("r2", "b/c.jpg") is not None
    assert fine["copiati"] == 2


def test_si_comincia_dalle_cartelle_piu_piccole(tmp_path, chiave):
    banco = Banco(tmp_path, chiave, radici=("grande", "piccola", "media"))
    banco.fino_alla_fine(grandezze={"grande": 900, "piccola": 1, "media": 50})
    assert banco.ordine == ["piccola", "media", "grande"]


def test_senza_grandezze_si_usa_l_ultimo_giro(tmp_path, chiave):
    banco = Banco(tmp_path, chiave, radici=("r1", "r2", "r3"))
    banco.metti("r1", "a.jpg", b"x" * 5000)
    banco.metti("r2", "a.jpg", b"x" * 10)
    banco.metti("r3", "a.jpg", b"x" * 300)
    banco.fino_alla_fine()
    banco.ordine.clear()
    banco.fino_alla_fine()
    assert banco.ordine == ["r2", "r3", "r1"]


def test_solo_le_cartelle_chieste(tmp_path, chiave):
    banco = Banco(tmp_path, chiave, radici=("r1", "r2"))
    fine = banco.fino_alla_fine(radici=[banco.elenco.radici()[1]])
    assert banco.ordine == ["r2"] and fine["fatte"] == ["r2"]


def test_con_le_cartelle_chieste_si_prendono_anche_quelle_nuove(tmp_path, chiave):
    banco = Banco(tmp_path, chiave, radici=("r1", "r2"))
    nuova = tmp_path / "nuova"
    nuova.mkdir()
    (nuova / "n.jpg").write_bytes(b"nuova")
    vera = banco.lavoro.copiatore.copia_radice

    def copia_radice(radice):
        if radice["id"] == "r2":
            banco.elenco.registra([elenco.fatto_radice("r9", str(nuova))])
        return vera(radice)

    banco.lavoro.copiatore.copia_radice = copia_radice
    fine = banco.fino_alla_fine(radici=[banco.elenco.radici()[1]])
    assert banco.ordine == ["r2", "r9"] and fine["fatte"] == ["r2", "r9"]


def test_le_cartelle_aggiunte_durante_la_copia_si_mettono_in_fila(tmp_path, chiave):
    banco = Banco(tmp_path, chiave, radici=("r1",))
    nuova = tmp_path / "nuova"
    nuova.mkdir()
    (nuova / "n.jpg").write_bytes(b"nuova")
    vera = banco.lavoro.copiatore.copia_radice

    def copia_radice(radice):
        if radice["id"] == "r1":
            banco.elenco.registra([elenco.fatto_radice("r9", str(nuova))])
        return vera(radice)

    banco.lavoro.copiatore.copia_radice = copia_radice
    fine = banco.fino_alla_fine()
    assert banco.ordine == ["r1", "r9"]
    assert fine["fatte"] == ["r1", "r9"]
    assert banco.elenco.attuale("r9", "n.jpg") is not None


def test_una_cartella_tolta_durante_la_copia_si_salta(tmp_path, chiave):
    banco = Banco(tmp_path, chiave, radici=("r1", "r2"))
    vera = banco.lavoro.copiatore.copia_radice

    def copia_radice(radice):
        if radice["id"] == "r1":
            banco.elenco.registra([elenco.fatto_radice(
                "r2", str(banco.sorgenti["r2"]), tolta=True)])
        return vera(radice)

    banco.lavoro.copiatore.copia_radice = copia_radice
    fine = banco.fino_alla_fine()
    assert banco.ordine == ["r1"] and fine["fatte"] == ["r1"]


def test_le_cartelle_tolte_non_si_copiano(tmp_path, chiave):
    banco = Banco(tmp_path, chiave, radici=("r1", "r2"))
    banco.elenco.registra([elenco.fatto_radice("r2", str(banco.sorgenti["r2"]),
                                               tolta=True)])
    banco.fino_alla_fine()
    assert banco.ordine == ["r1"]
    banco.ordine.clear()
    banco.fino_alla_fine(radici=banco.elenco.radici())
    assert banco.ordine == ["r1"]


def test_pausa_e_ripresa(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    for indice in range(5):
        banco.metti("r1", f"{indice}.jpg", bytes([indice]) * 1000)
    banco.disco.porta = threading.Event()
    assert banco.lavoro.avvia()
    assert _finche(lambda: banco.disco.chiesto >= 1)
    banco.lavoro.pausa()
    assert banco.lavoro.istantanea()["stato"] == lavoro.IN_PAUSA
    banco.disco.porta.set()
    banco.disco.porta = None
    time.sleep(0.1)
    assert banco.lavoro.acceso
    assert banco.lavoro.istantanea()["copiati"] == 0
    assert banco.lavoro.istantanea()["stato"] == lavoro.IN_PAUSA
    banco.lavoro.riprendi()
    assert banco.lavoro.aspetta_fine(ATTESA)
    fine = banco.lavoro.istantanea()
    assert fine["stato"] == lavoro.FINITO and fine["copiati"] == 5


def test_fermare_durante_la_pausa(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    banco.metti("r1", "a.jpg", b"a" * 100)
    banco.disco.porta = threading.Event()
    banco.lavoro.avvia()
    assert _finche(lambda: banco.disco.chiesto >= 1)
    banco.lavoro.pausa()
    banco.disco.porta.set()
    banco.lavoro.ferma(aspetta=ATTESA)
    fine = banco.lavoro.istantanea()
    assert fine["stato"] == lavoro.FERMATO
    assert banco.sveglio.uscite == 1
    assert banco.provvisori() == []
    assert banco.elenco.giro("r1")["fine"] is None
    assert [radice["id"] for radice in lavoro.da_riprendere(banco.elenco)] == ["r1"]


def test_fermare_mentre_aspetta_di_riprovare_un_file_bloccato(tmp_path, chiave):
    banco = Banco(tmp_path, chiave, attese=(30.0, 30.0))
    bersaglio = os.fspath(banco.metti("r1", "a.pst", b"posta"))

    def regola(percorso, senza_cache, volta, lettore):
        if percorso == bersaglio:
            raise PermissionError(errno.EACCES, "bloccato")
        return lettore

    banco.apri.regole.append(regola)
    banco.lavoro.avvia()
    assert _finche(lambda: len(banco.apri.aperti) >= 1)
    partito = time.monotonic()
    banco.lavoro.ferma(aspetta=ATTESA)
    assert time.monotonic() - partito < 5
    assert banco.lavoro.istantanea()["stato"] == lavoro.FERMATO


def test_dopo_uno_spegnimento_si_riprende_da_sola(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    for indice in range(6):
        banco.metti("r1", f"{indice}.jpg", bytes([indice]) * 500)
    copiati = []
    vera = banco.lavoro.copiatore._fissa

    def fissa(risultato):
        vera(risultato)
        copiati.append(1)
        if len(copiati) == 3:
            banco.lavoro.ferma()

    banco.lavoro.copiatore._fissa = fissa
    banco.lavoro.avvia()
    assert banco.lavoro.aspetta_fine(ATTESA)
    assert banco.lavoro.istantanea()["stato"] == lavoro.FERMATO
    banco.elenco.chiudi()
    riaperto = Elenco.apri(banco.archivio, chiave)
    da_fare = lavoro.da_riprendere(riaperto)
    assert [radice["id"] for radice in da_fare] == ["r1"]
    dopo = Lavoro(banco.archivio, riaperto, chiave, disco=Disco(), sveglio=Sveglio())
    assert dopo.avvia(radici=da_fare)
    assert dopo.aspetta_fine(ATTESA)
    assert dopo.istantanea()["stato"] == lavoro.FINITO
    assert len([posto for posto in riaperto.dentro("r1")]) == 6
    assert len(riaperto.numeri()) == 6
    assert lavoro.da_riprendere(riaperto) == []


def test_da_riprendere(tmp_path, chiave):
    aperto = Elenco.apri(tmp_path / "archivio", chiave)
    aperto.registra([elenco.fatto_radice(id, f"C:\\{id}") for id in
                     ("mai", "a_meta", "finita", "tolta")])
    aperto.registra([elenco.fatto_radice("tolta", "C:\\tolta", tolta=True),
                     elenco.fatto_giro("a_meta", 1.0, None),
                     elenco.fatto_giro("finita", 1.0, 2.0),
                     elenco.fatto_giro("tolta", 1.0, None)])
    assert sorted(radice["id"] for radice in lavoro.da_riprendere(aperto)) == [
        "a_meta", "mai"]


def test_non_si_parte_due_volte(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    banco.disco.porta = threading.Event()
    banco.metti("r1", "a.jpg", b"a")
    assert banco.lavoro.avvia()
    assert not banco.lavoro.avvia()
    banco.disco.porta.set()
    assert banco.lavoro.aspetta_fine(ATTESA)
    assert banco.lavoro.avvia()
    assert banco.lavoro.aspetta_fine(ATTESA)


def test_senza_spazio_si_ferma_prima_di_riempire_il_disco(tmp_path, chiave):
    totale = 1000 * 1024 ** 3
    banco = Banco(tmp_path, chiave, disco=Disco(libero=2 * 1024 ** 3, totale=totale),
                  ricontrolla=0.01)
    banco.metti("r1", "a.jpg", b"a" * 1000)
    banco.lavoro.avvia()
    assert _finche(lambda: banco.lavoro.istantanea()["stato"] == lavoro.SPAZIO_FINITO)
    time.sleep(0.05)
    assert banco.lavoro.istantanea()["copiati"] == 0
    banco.disco.libero = lavoro.margine(totale) + 10 ** 6
    assert banco.lavoro.aspetta_fine(ATTESA)
    assert banco.lavoro.istantanea()["stato"] == lavoro.FINITO


def test_senza_spazio_riprende_subito_quando_lo_dici(tmp_path, chiave):
    banco = Banco(tmp_path, chiave, disco=Disco(libero=0), ricontrolla=3600.0)
    banco.metti("r1", "a.jpg", b"a")
    banco.lavoro.avvia()
    assert _finche(lambda: banco.lavoro.istantanea()["stato"] == lavoro.SPAZIO_FINITO)
    banco.disco.libero = PIENO
    banco.lavoro.riprendi()
    assert banco.lavoro.aspetta_fine(ATTESA)
    assert banco.lavoro.istantanea()["stato"] == lavoro.FINITO


def test_senza_spazio_si_puo_fermare(tmp_path, chiave):
    banco = Banco(tmp_path, chiave, disco=Disco(libero=0), ricontrolla=3600.0)
    banco.metti("r1", "a.jpg", b"a")
    banco.lavoro.avvia()
    assert _finche(lambda: banco.lavoro.istantanea()["stato"] == lavoro.SPAZIO_FINITO)
    banco.lavoro.ferma(aspetta=ATTESA)
    assert banco.lavoro.istantanea()["stato"] == lavoro.FERMATO


def test_in_pausa_mentre_manca_lo_spazio_resta_in_pausa_dopo(tmp_path, chiave):
    banco = Banco(tmp_path, chiave, disco=Disco(libero=0), ricontrolla=0.01)
    banco.metti("r1", "a.jpg", b"a")
    banco.lavoro.avvia()
    assert _finche(lambda: banco.lavoro.istantanea()["stato"] == lavoro.SPAZIO_FINITO)
    banco.lavoro.pausa()
    banco.disco.libero = PIENO
    assert _finche(lambda: banco.lavoro.istantanea()["stato"] == lavoro.IN_PAUSA)
    time.sleep(0.05)
    assert banco.lavoro.istantanea()["copiati"] == 0
    banco.lavoro.riprendi()
    assert banco.lavoro.aspetta_fine(ATTESA)
    assert banco.lavoro.istantanea()["copiati"] == 1


@pytest.mark.parametrize("numero", [errno.ENOSPC, getattr(errno, "EDQUOT", errno.ENOSPC)])
def test_il_disco_pieno_mentre_scrivo_aspetta_e_poi_riprende(tmp_path, chiave,
                                                            monkeypatch, numero):
    banco = Banco(tmp_path, chiave, ricontrolla=0.01)
    for indice in range(3):
        banco.metti("r1", f"{indice}.jpg", bytes([indice]) * 5000)
    vera = formato.Scrittore.write
    rotture = []

    def scrivi(self, dati):
        if not rotture:
            rotture.append(1)
            raise OSError(numero, "disco pieno")
        return vera(self, dati)

    monkeypatch.setattr(formato.Scrittore, "write", scrivi)
    fine = banco.fino_alla_fine()
    assert fine["stato"] == lavoro.FINITO
    assert len(banco.elenco.dentro("r1")) == 3
    assert banco.provvisori() == []
    assert banco.ordine == ["r1", "r1"]


def test_il_disco_dell_archivio_guasto_ferma_tutto(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    banco.metti("r1", "a.jpg", b"a")

    def guasto(radice):
        raise copia.DiscoArchivioGuasto("scrive male")

    banco.lavoro.copiatore.copia_radice = guasto
    fine = banco.fino_alla_fine()
    assert fine["stato"] == lavoro.GUASTO
    assert fine["codice"] == "disco_archivio_guasto"
    assert fine["errore"] == "scrive male"
    assert banco.sveglio.uscite == 1


def test_un_errore_qualsiasi_non_resta_nascosto(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)

    def guasto(radice):
        raise RuntimeError("imprevisto")

    banco.lavoro.copiatore.copia_radice = guasto
    fine = banco.fino_alla_fine()
    assert fine["stato"] == lavoro.ERRORE
    assert fine["codice"] == "RuntimeError" and fine["errore"] == "imprevisto"


def test_un_altro_errore_del_disco_non_si_scambia_per_spazio(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)

    def guasto(radice):
        raise OSError(errno.EIO, "disco rotto")

    banco.lavoro.copiatore.copia_radice = guasto
    fine = banco.fino_alla_fine()
    assert fine["stato"] == lavoro.ERRORE and fine["codice"] == "OSError"


def test_se_il_salvataggio_finale_si_rompe_lo_si_dice(tmp_path, chiave, monkeypatch):
    banco = Banco(tmp_path, chiave)

    def salva():
        raise OSError(errno.EIO, "non salva")

    monkeypatch.setattr(banco.elenco, "salva", salva)
    fine = banco.fino_alla_fine()
    assert fine["stato"] == lavoro.ERRORE


def test_si_rallenta_se_stai_usando_il_programma(tmp_path, chiave):
    chiesti = []

    def rallenta():
        chiesti.append(1)
        return True

    banco = Banco(tmp_path, chiave, rallenta=rallenta, pausa_se_usi=0.001)
    banco.metti("r1", "a.jpg", b"a" * 20_000)
    partito = time.monotonic()
    fine = banco.fino_alla_fine()
    assert fine["stato"] == lavoro.FINITO
    assert chiesti
    assert time.monotonic() - partito >= 0.001 * len(chiesti)


def test_se_rallenta_si_rompe_si_va_avanti(tmp_path, chiave):
    def rallenta():
        raise RuntimeError("no")

    banco = Banco(tmp_path, chiave, rallenta=rallenta)
    banco.metti("r1", "a.jpg", b"a")
    assert banco.fino_alla_fine()["stato"] == lavoro.FINITO


def test_si_ferma_subito_anche_se_sta_rallentando(tmp_path, chiave):
    dentro = threading.Event()

    def rallenta():
        dentro.set()
        return True

    banco = Banco(tmp_path, chiave, rallenta=rallenta, pausa_se_usi=60.0)
    banco.metti("r1", "a.jpg", b"a" * 1000)
    banco.lavoro.avvia()
    assert dentro.wait(ATTESA)
    partito = time.monotonic()
    banco.lavoro.ferma(aspetta=ATTESA)
    assert time.monotonic() - partito < 5
    assert banco.lavoro.istantanea()["stato"] == lavoro.FERMATO
    assert banco.provvisori() == []


def test_tanti_tasti_insieme_non_rompono_niente(tmp_path, chiave):
    banco = Banco(tmp_path, chiave, rallenta=lambda: True, pausa_se_usi=0.0005)
    attesi = {}
    for indice in range(12):
        attesi[f"{indice}.jpg"] = bytes([indice]) * (500 + 300 * indice)
        banco.metti("r1", f"{indice}.jpg", attesi[f"{indice}.jpg"])
    assert banco.lavoro.avvia()
    basta = threading.Event()

    def premi(seme):
        caso = random.Random(seme)
        while not basta.is_set():
            caso.choice([banco.lavoro.pausa, banco.lavoro.riprendi,
                         banco.lavoro.istantanea])()
            time.sleep(caso.random() * 0.002)

    fili = [threading.Thread(target=premi, args=(seme,)) for seme in range(6)]
    for filo in fili:
        filo.start()
    time.sleep(0.2)
    basta.set()
    for filo in fili:
        filo.join(ATTESA)
    banco.lavoro.riprendi()
    assert banco.lavoro.aspetta_fine(ATTESA)
    assert banco.lavoro.istantanea()["stato"] == lavoro.FINITO
    for relativo, dati in attesi.items():
        assert banco.dati(banco.elenco.attuale("r1", relativo).contenuto) == dati
    assert banco.provvisori() == []
    assert banco.sveglio.entrate == banco.sveglio.uscite == 1


def _tasti_a_caso(banco: Banco, caso: random.Random) -> list[str]:
    fatti = []
    for _ in range(caso.randrange(0, 6)):
        if not banco.lavoro.acceso:
            break
        time.sleep(caso.choice([0, 0.001, 0.003, 0.01]))
        tasto = caso.choice(["pausa", "riprendi", "riprendi", "ferma"])
        fatti.append(tasto)
        if tasto == "ferma":
            banco.lavoro.ferma(aspetta=ATTESA)
            break
        getattr(banco.lavoro, tasto)()
    return fatti


@pytest.mark.parametrize("seme", range(60))
def test_a_caso_pausa_fermo_spegnimento_e_poi_tutto_dentro(tmp_path, chiave, seme):
    caso = random.Random(seme)
    radici = tuple(f"r{indice}" for indice in range(caso.randrange(1, 4)))
    opzioni = dict(rallenta=lambda: True, pausa_se_usi=caso.choice([0, 0.0005, 0.001]))
    banco = Banco(tmp_path, chiave, radici=radici, **opzioni)
    comuni = [caso.randbytes(caso.randrange(0, 5000)) for _ in range(3)]
    attesi = {}
    for id in radici:
        for indice in range(caso.randrange(0, 9)):
            relativo = f"{caso.choice(['', '2019/', '2020/mare/'])}IMG_{indice}.jpg"
            dati = (caso.choice(comuni) if caso.random() < 0.3
                    else caso.randbytes(caso.randrange(0, 20_000)))
            attesi[(id, relativo)] = dati
            banco.metti(id, relativo, dati)
    sveglio = banco.sveglio
    giri = 0
    while True:
        giri += 1
        assert giri < 30
        da_fare = lavoro.da_riprendere(banco.elenco)
        if not da_fare:
            break
        assert banco.lavoro.avvia(radici=da_fare if caso.random() < 0.5 else None)
        _tasti_a_caso(banco, caso)
        banco.lavoro.riprendi()
        assert banco.lavoro.aspetta_fine(ATTESA)
        assert banco.lavoro.istantanea()["stato"] in (lavoro.FINITO, lavoro.FERMATO)
        assert banco.provvisori() == []
        if caso.random() < 0.3:
            banco.elenco.chiudi()
            banco.elenco = Elenco.apri(banco.archivio, chiave)
            banco.lavoro = Lavoro(banco.archivio, banco.elenco, chiave,
                                  disco=Disco(), sveglio=sveglio,
                                  apri=banco.apri, **opzioni)
    assert sveglio.entrate == sveglio.uscite == giri - 1
    contenuti = {}
    for (id, relativo), dati in attesi.items():
        posto = banco.elenco.attuale(id, relativo)
        assert posto is not None and posto.segni == ()
        assert banco.dati(posto.contenuto) == dati
        contenuti[(id, relativo)] = posto.contenuto
    assert len(banco.elenco.numeri()) == len(set(attesi.values()))
    for id in radici:
        giro = banco.elenco.giro(id)
        assert giro["fine"] is not None and giro["problemi"] == []
    banco.elenco.chiudi()
    riaperto = Elenco.apri(banco.archivio, chiave)
    assert {chiave_: riaperto.attuale(*chiave_).contenuto
            for chiave_ in contenuti} == contenuti


def test_le_cartelle_rosse_si_dicono_con_i_loro_problemi(tmp_path, chiave):
    banco = Banco(tmp_path, chiave, radici=("r1", "r2"))
    bersaglio = os.fspath(banco.metti("r1", "a.pst", b"posta"))
    banco.metti("r2", "b.jpg", b"b")

    def regola(percorso, senza_cache, volta, lettore):
        if percorso == bersaglio:
            raise PermissionError(errno.EACCES, "bloccato")
        return lettore

    banco.apri.regole.append(regola)
    banco.lavoro.copiatore._dormi = lambda secondi: None
    fine = banco.fino_alla_fine()
    assert fine["verdi"] == ["r2"]
    assert fine["rosse"] == {"r1": [["bloccato", "a.pst"]]}


def test_lo_stato_prima_di_partire(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    istantanea = banco.lavoro.istantanea()
    assert istantanea["stato"] == lavoro.FERMO and istantanea["fatte"] == []
    assert not banco.lavoro.acceso
    assert banco.lavoro.aspetta_fine(0.01)
    banco.lavoro.pausa()
    banco.lavoro.riprendi()
    assert banco.lavoro.istantanea()["stato"] == lavoro.FERMO


@pytest.mark.parametrize("totale,atteso", [
    (0, lavoro.MARGINE_MINIMO),
    (100 * 1024 ** 3, lavoro.MARGINE_MINIMO),
    (1000 * 1024 ** 3, 10 * 1024 ** 3),
    (8 * 1024 ** 4, int(8 * 1024 ** 4 * 0.01)),
])
def test_il_margine_e_il_piu_grande_fra_2_gb_e_l_1_per_cento(totale, atteso):
    assert lavoro.margine(totale) == atteso


def test_l_uso_del_disco_vero(tmp_path):
    libero, totale = lavoro.uso_del_disco(tmp_path / "non" / "ancora")
    assert 0 < libero <= totale


def test_sveglio_fuori_da_windows_non_fa_niente(monkeypatch):
    chiamate = []
    monkeypatch.setattr(disco, "WINDOWS", False)
    monkeypatch.setattr(sveglia, "_imposta", lambda stato: chiamate.append(stato))
    with sveglia.sveglio() as acceso:
        assert acceso is False
    assert chiamate == []


def test_sveglio_su_windows_tiene_acceso_e_poi_lascia(monkeypatch):
    chiamate = []
    monkeypatch.setattr(disco, "WINDOWS", True)
    monkeypatch.setattr(sveglia, "_imposta",
                        lambda stato: chiamate.append(stato) or True)
    with sveglia.sveglio() as acceso:
        assert acceso is True
        assert chiamate == [sveglia.SEMPRE | sveglia.SISTEMA]
    assert chiamate == [sveglia.SEMPRE | sveglia.SISTEMA, sveglia.SEMPRE]


def test_sveglio_lascia_anche_se_qualcosa_si_rompe(monkeypatch):
    chiamate = []
    monkeypatch.setattr(disco, "WINDOWS", True)
    monkeypatch.setattr(sveglia, "_imposta",
                        lambda stato: chiamate.append(stato) or True)
    with pytest.raises(RuntimeError):
        with sveglia.sveglio():
            raise RuntimeError("guasto")
    assert chiamate[-1] == sveglia.SEMPRE


def test_sveglio_se_windows_dice_di_no(monkeypatch):
    def imposta(stato):
        raise OSError("no")

    monkeypatch.setattr(disco, "WINDOWS", True)
    monkeypatch.setattr(sveglia, "_imposta", imposta)
    with sveglia.sveglio() as acceso:
        assert acceso is False


def test_sveglio_se_windows_risponde_zero(monkeypatch):
    chiamate = []
    monkeypatch.setattr(disco, "WINDOWS", True)
    monkeypatch.setattr(sveglia, "_imposta",
                        lambda stato: (chiamate.append(stato), False)[1])
    with sveglia.sveglio() as acceso:
        assert acceso is False
    assert chiamate == [sveglia.SEMPRE | sveglia.SISTEMA]


@pytest.mark.skipif(os.name != "nt", reason="prove con Windows vero")
def test_sveglio_con_windows_vero():
    with sveglia.sveglio() as acceso:
        assert acceso is True
