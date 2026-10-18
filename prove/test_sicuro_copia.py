from __future__ import annotations

import errno
import os
import random
from collections import Counter
from pathlib import Path

import pytest

from officina.sicuro import chiavi, copia, elenco, formato, metadati
from officina.sicuro.copia import Copiatore, DiscoArchivioGuasto, Fermato
from officina.sicuro.diretto import ALLINEA, Lettore
from officina.sicuro.elenco import Elenco

su_linux = pytest.mark.skipif(os.name == "nt", reason="prove del lato Linux")


@pytest.fixture
def chiave():
    return chiavi.Chiave(bytes(range(32)))


@pytest.fixture(autouse=True)
def pezzi_piccoli(monkeypatch):
    monkeypatch.setattr(copia, "PEZZO_DI_LETTURA", 3 * ALLINEA)


def _dati(quanti, seme=1):
    return random.Random(seme).randbytes(quanti)


class Finto:

    def __init__(self, vero, rotti=(), volte=None, sporca=(), errore=None):
        self._vero = vero
        self.dimensione = vero.dimensione
        self.nome = vero.nome
        self._rotti = set(rotti)
        self._volte = volte
        self._colpi: Counter[int] = Counter()
        self._sporca = set(sporca)
        self._errore = errore or (lambda: OSError(errno.EIO, "settore rotto"))

    def _guarda(self, dove, quanti):
        for settore in sorted(self._rotti):
            if dove < settore + ALLINEA and settore < dove + quanti:
                if self._volte is None or self._colpi[settore] < self._volte:
                    self._colpi[settore] += 1
                    raise self._errore()

    def _sporco(self, dove, dati):
        if not self._sporca:
            return dati
        dati = bytearray(dati)
        for punto in self._sporca:
            if dove <= punto < dove + len(dati):
                dati[punto - dove] ^= 0xFF
        return bytes(dati)

    def _resto(self, dove, quanti):
        return min(quanti, max(0, self.dimensione - dove))

    def seek(self, dove, da=os.SEEK_SET):
        return self._vero.seek(dove, da)

    def tell(self):
        return self._vero.tell()

    def read(self, quanti=-1):
        dove = self._vero.tell()
        if quanti is None or quanti < 0:
            quanti = max(0, self.dimensione - dove)
        self._guarda(dove, self._resto(dove, quanti))
        return self._sporco(dove, self._vero.read(quanti))

    def pezzo(self, dove, quanti):
        self._guarda(dove, self._resto(dove, quanti))
        return self._sporco(dove, self._vero.pezzo(dove, quanti))

    def close(self):
        self._vero.close()

    def __enter__(self):
        return self

    def __exit__(self, *altro):
        self.close()


class Apri:

    def __init__(self):
        self.aperti: list[tuple[str, bool]] = []
        self.regole = []
        self._volte: Counter[str] = Counter()

    def __call__(self, percorso, senza_cache=True):
        nome = os.fspath(percorso)
        volta = self._volte[nome]
        self._volte[nome] += 1
        self.aperti.append((nome, senza_cache))
        lettore = Lettore(percorso, senza_cache=senza_cache)
        try:
            for regola in self.regole:
                lettore = regola(nome, senza_cache, volta, lettore)
        except BaseException:
            lettore.close()
            raise
        return lettore

    def originali(self, banco):
        sorgente = os.fspath(banco.sorgente)
        return [aperto for aperto in self.aperti if aperto[0].startswith(sorgente)]


class Banco:

    def __init__(self, cartella: Path, chiave, **opzioni):
        self.sorgente = cartella / "foto"
        self.sorgente.mkdir(exist_ok=True)
        self.archivio = cartella / "archivio"
        self.chiave = chiave
        self.elenco = Elenco.apri(self.archivio, chiave)
        if not self.elenco.radici():
            self.elenco.registra([elenco.fatto_radice("r1", str(self.sorgente),
                                                      quando=1000.0)])
        self.apri = Apri()
        self.dormite: list[float] = []
        opzioni.setdefault("dormi", self.dormite.append)
        opzioni.setdefault("apri", self.apri)
        self.copiatore = Copiatore(self.archivio, self.elenco, chiave, **opzioni)

    def radice(self, id="r1"):
        return next(radice for radice in self.elenco.radici() if radice["id"] == id)

    def metti(self, relativo: str, dati: bytes) -> Path:
        percorso = self.sorgente / relativo
        percorso.parent.mkdir(parents=True, exist_ok=True)
        percorso.write_bytes(dati)
        return percorso

    def giro(self, id="r1"):
        return self.copiatore.copia_radice(self.radice(id))

    def posto(self, relativo: str):
        return self.elenco.attuale("r1", relativo)

    def blob(self, numero: str) -> Path:
        return elenco.percorso_contenuto(self.archivio, numero)

    def dati(self, numero: str) -> bytes:
        with open(self.blob(numero), "rb") as file:
            return formato.Contenuto(file, self.chiave,
                                     numero=bytes.fromhex(numero)).tutto()

    def informazioni(self, numero: str) -> dict:
        with open(self.blob(numero), "rb") as file:
            return formato.Contenuto(file, self.chiave,
                                     numero=bytes.fromhex(numero)).dati

    def provvisori(self) -> list[Path]:
        return [percorso for percorso in self.archivio.rglob("*")
                if percorso.name.endswith(copia.PROVVISORI)]

    def file_cifrati(self) -> set[str]:
        return {percorso.name[:-4] for percorso
                in (self.archivio / elenco.CONTENUTI).rglob("*.ofs")}

    def contenuti(self) -> set[str]:
        return set(self.elenco.numeri())

    def chiudi(self) -> None:
        self.elenco.chiudi()

    def riapri(self, **opzioni) -> Banco:
        self.chiudi()
        return Banco(self.archivio.parent, self.chiave, **opzioni)


def _codici(giro) -> list[str]:
    return [codice for codice, _ in giro.problemi]


def _sotto_controllo(banco: Banco) -> None:
    assert banco.provvisori() == []
    numeri = banco.contenuti()
    note = set(banco.elenco.note())
    assert banco.file_cifrati() == numeri | note
    for numero in numeri:
        informazioni = banco.elenco.contenuto(numero)
        with open(banco.blob(numero), "rb") as file:
            controllo = formato.controlla(file, banco.chiave,
                                          numero=bytes.fromhex(numero),
                                          testa=informazioni["testa"])
        assert controllo.buono, numero
    for radice in banco.elenco.radici():
        for posto in banco.elenco.dentro(radice["id"]):
            if posto.tipo != "file":
                assert posto.contenuto is None
                continue
            assert posto.contenuto in numeri
            for _, numero in banco.elenco.flussi_di(posto.chiave):
                assert numero in numeri


def _stato(aperto: Elenco) -> dict:
    return {
        "contenuti": sorted((numero, aperto.contenuto(numero)["stato"],
                             aperto.contenuto(numero)["sha256"])
                            for numero in aperto.numeri()),
        "posti": sorted((posto.radice, posto.percorso, posto.tipo, posto.contenuto,
                         posto.sparito is None, posto.segni,
                         tuple(sorted(posto.metadati.items(), key=str)))
                        for radice in aperto.radici()
                        for posto in aperto.dentro(radice["id"], anche_spariti=True)),
        "radici": [(radice["id"], radice["percorso"], radice["tolta"])
                   for radice in aperto.radici()],
        "giri": {radice["id"]: aperto.giro(radice["id"]) for radice in aperto.radici()},
    }


def _rifatto(banco: Banco) -> Elenco:
    banco.chiudi()
    for percorso in (banco.archivio / elenco.ELENCO).iterdir():
        percorso.unlink()
    return Elenco.apri(banco.archivio, banco.chiave)


def test_una_cartella_si_copia_tutta_e_si_rilegge_uguale(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    misure = [0, 1, ALLINEA - 1, ALLINEA, ALLINEA + 1, formato.BLOCCO,
              formato.BLOCCO + 1, 3 * formato.BLOCCO + 17, 300_001]
    originali = {}
    for indice, misura in enumerate(misure):
        relativo = f"{2000 + indice % 3}/IMG_{indice:04d}.jpg"
        originali[relativo] = _dati(misura, indice)
        banco.metti(relativo, originali[relativo])
    giro = banco.giro()
    assert giro.verde and giro.problemi == []
    assert giro.contati["file"] == len(misure)
    assert giro.contati["byte"] == sum(misure)
    assert giro.contati["cartelle"] == 3
    for relativo, dati in originali.items():
        posto = banco.posto(relativo)
        assert posto is not None and posto.tipo == "file" and posto.segni == ()
        assert banco.dati(posto.contenuto) == dati
        assert banco.elenco.contenuto(posto.contenuto)["stato"] == "buono"
    assert banco.copiatore.avanzamento.copiati == len(misure)
    assert banco.copiatore.avanzamento.file == len(misure)
    _sotto_controllo(banco)


def test_ogni_file_si_legge_due_volte_la_seconda_senza_memoria(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    banco.metti("a.jpg", _dati(50_000))
    banco.giro()
    letture = banco.apri.originali(banco)
    assert letture == [(os.fspath(banco.sorgente / "a.jpg"), False),
                       (os.fspath(banco.sorgente / "a.jpg"), True)]
    cifrati = [aperto for aperto in banco.apri.aperti
               if aperto[0].endswith(".ofs.nuovo")]
    assert cifrati and all(senza for _, senza in cifrati)


def test_il_file_cifrato_porta_con_se_il_suo_posto(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    banco.metti("2001/mare.jpg", b"onde")
    banco.giro()
    posto = banco.posto("2001/mare.jpg")
    portati = banco.informazioni(posto.contenuto)["fatti"]
    tipi = [fatto["fatto"] for fatto in portati]
    assert tipi == ["radice", "posto"]
    assert portati[0]["id"] == "r1" and portati[0]["percorso"] == str(banco.sorgente)
    assert portati[1]["chiave"] == posto.chiave
    assert portati[1]["percorso"] == "2001/mare.jpg"


def test_la_seconda_volta_non_si_ricopia_niente(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    for indice in range(5):
        banco.metti(f"IMG_{indice}.jpg", _dati(10_000, indice))
    banco.giro()
    prima = banco.file_cifrati()
    chiavi_prima = {posto.chiave for posto in banco.elenco.dentro("r1")}
    banco.apri.aperti.clear()
    giro = banco.giro()
    assert giro.verde
    assert banco.apri.originali(banco) == []
    assert banco.contenuti() <= prima
    assert {posto.chiave for posto in banco.elenco.dentro("r1")} == chiavi_prima
    assert banco.copiatore.avanzamento.uguali == 5


def test_un_file_cambiato_tiene_tutte_e_due_le_versioni(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    percorso = banco.metti("a.jpg", b"prima versione")
    banco.giro()
    vecchio = banco.posto("a.jpg")
    percorso.write_bytes(b"seconda versione, piu lunga")
    os.utime(percorso, ns=(10 ** 18, 10 ** 18))
    banco.giro()
    nuovo = banco.posto("a.jpg")
    assert nuovo.contenuto != vecchio.contenuto
    assert banco.dati(nuovo.contenuto) == b"seconda versione, piu lunga"
    assert banco.dati(vecchio.contenuto) == b"prima versione"
    storia = banco.elenco.storia("r1", "a.jpg")
    assert [posto.contenuto for posto in storia] == [vecchio.contenuto, nuovo.contenuto]
    assert storia[0].sparito is not None and storia[1].sparito is None
    _sotto_controllo(banco)


def test_stessa_grandezza_e_stessa_data_ma_byte_diversi_si_ricopia(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    percorso = banco.metti("a.jpg", b"AAAA")
    os.utime(percorso, ns=(5 * 10 ** 17, 5 * 10 ** 17))
    banco.giro()
    vecchio = banco.posto("a.jpg")
    percorso.write_bytes(b"BBBB")
    os.utime(percorso, ns=(5 * 10 ** 17, 5 * 10 ** 17 + 1))
    banco.giro()
    assert banco.dati(banco.posto("a.jpg").contenuto) == b"BBBB"
    assert banco.posto("a.jpg").contenuto != vecchio.contenuto


@su_linux
def test_cambiano_solo_i_permessi_si_tiene_lo_stesso_contenuto(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    percorso = banco.metti("a.jpg", b"foto")
    os.chmod(percorso, 0o644)
    banco.giro()
    vecchio = banco.posto("a.jpg")
    os.chmod(percorso, 0o600)
    banco.apri.aperti.clear()
    banco.giro()
    nuovo = banco.posto("a.jpg")
    assert banco.apri.originali(banco) == []
    assert nuovo.chiave != vecchio.chiave
    assert nuovo.contenuto == vecchio.contenuto
    assert nuovo.metadati["permessi"]["modo"] == 0o600
    assert len(banco.elenco.storia("r1", "a.jpg")) == 2


def test_cambia_solo_la_data_di_accesso_e_non_succede_niente(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    percorso = banco.metti("a.jpg", b"foto")
    banco.giro()
    vecchio = banco.posto("a.jpg")
    stato = os.stat(percorso)
    os.utime(percorso, ns=(stato.st_atime_ns + 10 ** 12, stato.st_mtime_ns))
    banco.giro()
    assert banco.posto("a.jpg").chiave == vecchio.chiave


def test_i_doppioni_si_copiano_una_volta_sola(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    dati = _dati(70_000)
    for nome in ("a.jpg", "copia/a.jpg", "altra/b.jpg"):
        banco.metti(nome, dati)
    banco.metti("diverso.jpg", _dati(70_000, 2))
    giro = banco.giro()
    assert giro.verde
    numeri = {banco.posto(nome).contenuto for nome in ("a.jpg", "copia/a.jpg",
                                                       "altra/b.jpg")}
    assert len(numeri) == 1
    assert banco.posto("diverso.jpg").contenuto not in numeri
    assert len(banco.contenuti()) == 2
    assert banco.copiatore.avanzamento.doppioni == 2
    _sotto_controllo(banco)


def test_un_doppione_si_conferma_byte_per_byte(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    banco.metti("a.jpg", _dati(20_000))
    banco.giro()
    numero = banco.posto("a.jpg").contenuto
    banco.metti("b.jpg", _dati(20_000))
    banco.apri.aperti.clear()
    banco.giro()
    assert banco.posto("b.jpg").contenuto == numero
    letti = [nome for nome, senza in banco.apri.aperti if senza]
    assert os.fspath(banco.blob(numero)) in letti
    assert os.fspath(banco.sorgente / "b.jpg") in letti


def test_un_doppione_rovinato_nell_archivio_non_si_usa(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    banco.metti("a.jpg", _dati(20_000))
    banco.giro()
    vecchio = banco.posto("a.jpg").contenuto
    blob = banco.blob(vecchio)
    guasto = bytearray(blob.read_bytes())
    for dove in range(formato.PEZZO * 3, formato.PEZZO * 3 + 600):
        guasto[dove] ^= 0x55
    blob.write_bytes(bytes(guasto))
    banco.metti("b.jpg", _dati(20_000))
    banco.giro()
    nuovo = banco.posto("b.jpg").contenuto
    assert nuovo != vecchio
    assert banco.dati(nuovo) == _dati(20_000)


def test_un_doppione_segnato_rovinato_non_si_usa(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    banco.metti("a.jpg", b"stessi byte")
    banco.giro()
    vecchio = banco.posto("a.jpg").contenuto
    banco.elenco.registra([elenco.fatto_stato(vecchio, "rovinato")])
    banco.metti("b.jpg", b"stessi byte")
    banco.giro()
    assert banco.posto("b.jpg").contenuto != vecchio


def test_un_file_rovinato_nell_archivio_si_ricopia_dall_originale(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    banco.metti("a.jpg", b"foto delle vacanze")
    banco.giro()
    vecchio = banco.posto("a.jpg").contenuto
    banco.elenco.registra([elenco.fatto_stato(vecchio, "rovinato")])
    banco.giro()
    nuovo = banco.posto("a.jpg").contenuto
    assert nuovo != vecchio
    assert banco.elenco.contenuto(nuovo)["stato"] == "buono"
    assert banco.dati(nuovo) == b"foto delle vacanze"


def _cambia_mentre_copio(banco: Banco, nome: str, quante: int | None = None):
    bersaglio = os.fspath(banco.sorgente / nome)
    fatte = []

    def regola(percorso, senza_cache, volta, lettore):
        if percorso == bersaglio and not senza_cache and (
                quante is None or len(fatte) < quante):
            fatte.append(volta)
            dati = bytearray(Path(percorso).read_bytes())
            dati[0] = (dati[0] + 1) % 256
            Path(percorso).write_bytes(bytes(dati))
            stato = os.stat(percorso)
            os.utime(percorso, ns=(stato.st_atime_ns, stato.st_mtime_ns + 10 ** 9))
        return lettore

    banco.apri.regole.append(regola)
    return fatte


def test_un_file_che_cambia_sempre_si_tiene_l_ultima_versione_in_uso(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    percorso = banco.metti("posta.db", _dati(30_000))
    fatte = _cambia_mentre_copio(banco, "posta.db")
    giro = banco.giro()
    assert fatte == [0, 1, 2]
    assert _codici(giro) == ["in_uso"]
    assert not giro.verde
    posto = banco.posto("posta.db")
    assert posto.segni == ("in_uso",)
    assert banco.dati(posto.contenuto) == percorso.read_bytes()
    assert banco.dormite == [1.0, 3.0]
    _sotto_controllo(banco)


def test_un_file_che_cambia_una_volta_si_riprova_e_va_bene(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    percorso = banco.metti("posta.db", _dati(30_000))
    _cambia_mentre_copio(banco, "posta.db", quante=1)
    giro = banco.giro()
    assert giro.verde
    posto = banco.posto("posta.db")
    assert posto.segni == ()
    assert banco.dati(posto.contenuto) == percorso.read_bytes()
    assert banco.dormite == [1.0]


def test_un_file_in_uso_si_riprova_al_giro_dopo(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    percorso = banco.metti("posta.db", _dati(30_000))
    _cambia_mentre_copio(banco, "posta.db", quante=3)
    banco.giro()
    assert banco.posto("posta.db").segni == ("in_uso",)
    numero = banco.posto("posta.db").contenuto
    giro = banco.giro()
    assert giro.verde
    posto = banco.posto("posta.db")
    assert posto.segni == ()
    assert posto.contenuto == numero
    assert banco.dati(numero) == percorso.read_bytes()


def _settori_rotti(banco: Banco, nome: str, settori, volte=None, errore=None):
    bersaglio = os.fspath(banco.sorgente / nome)

    def regola(percorso, senza_cache, volta, lettore):
        if percorso == bersaglio:
            return Finto(lettore, rotti=settori, volte=volte, errore=errore)
        return lettore

    banco.apri.regole.append(regola)


def test_un_settore_che_non_si_legge_mai_diventa_un_buco_incompleto(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    dati = _dati(10 * ALLINEA + 123)
    banco.metti("vecchia.jpg", dati)
    _settori_rotti(banco, "vecchia.jpg", [2 * ALLINEA, 7 * ALLINEA])
    giro = banco.giro()
    assert _codici(giro) == ["incompleto"]
    posto = banco.posto("vecchia.jpg")
    assert posto.segni == ("incompleto",)
    informazioni = banco.elenco.contenuto(posto.contenuto)
    assert informazioni["stato"] == "incompleto"
    salvato = banco.dati(posto.contenuto)
    atteso = bytearray(dati)
    for settore in (2, 7):
        atteso[settore * ALLINEA:(settore + 1) * ALLINEA] = bytes(ALLINEA)
    assert salvato == bytes(atteso)
    _sotto_controllo(banco)


def test_un_buco_alla_fine_del_file_si_riempie_fino_alla_fine(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    dati = _dati(5 * ALLINEA + 100)
    banco.metti("a.jpg", dati)
    _settori_rotti(banco, "a.jpg", [5 * ALLINEA])
    banco.giro()
    salvato = banco.dati(banco.posto("a.jpg").contenuto)
    assert salvato == dati[:5 * ALLINEA] + bytes(100)


def test_un_settore_che_si_legge_alla_seconda_non_lascia_buchi(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    dati = _dati(9 * ALLINEA)
    banco.metti("a.jpg", dati)
    _settori_rotti(banco, "a.jpg", [3 * ALLINEA], volte=2)
    giro = banco.giro()
    assert giro.verde
    assert banco.dati(banco.posto("a.jpg").contenuto) == dati


def test_un_file_che_non_si_legge_per_niente_non_entra(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    banco.metti("rotto.jpg", _dati(3 * ALLINEA))
    banco.metti("buono.jpg", b"ok")
    _settori_rotti(banco, "rotto.jpg", [0, ALLINEA, 2 * ALLINEA])
    giro = banco.giro()
    assert _codici(giro) == ["illeggibile"]
    assert giro.problemi == [("illeggibile", "rotto.jpg")]
    assert banco.posto("rotto.jpg") is None
    assert banco.posto("buono.jpg") is not None
    _sotto_controllo(banco)


def test_un_buco_uguale_due_volte_non_fa_due_copie(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    banco.metti("a.jpg", _dati(6 * ALLINEA))
    _settori_rotti(banco, "a.jpg", [ALLINEA])
    banco.giro()
    prima = banco.posto("a.jpg")
    numeri = banco.contenuti()
    giro = banco.giro()
    assert _codici(giro) == ["incompleto"]
    assert banco.contenuti() == numeri
    assert banco.posto("a.jpg").chiave == prima.chiave
    assert len(banco.elenco.storia("r1", "a.jpg")) == 1
    _sotto_controllo(banco)


def test_un_buco_che_si_aggiusta_poi_da_la_copia_buona(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    dati = _dati(6 * ALLINEA)
    banco.metti("a.jpg", dati)
    _settori_rotti(banco, "a.jpg", [ALLINEA])
    banco.giro()
    banco.apri.regole.clear()
    giro = banco.giro()
    assert giro.verde
    posto = banco.posto("a.jpg")
    assert posto.segni == ()
    assert banco.dati(posto.contenuto) == dati
    assert banco.elenco.contenuto(posto.contenuto)["stato"] == "buono"


def test_due_file_con_lo_stesso_buco_non_sono_doppioni_di_copie_buone(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    dati = _dati(4 * ALLINEA)
    banco.metti("buono.jpg", dati)
    banco.giro()
    rotto = bytearray(dati)
    rotto[ALLINEA:2 * ALLINEA] = bytes(ALLINEA)
    banco.metti("zeri.jpg", bytes(rotto))
    banco.metti("rotto.jpg", dati)
    _settori_rotti(banco, "rotto.jpg", [ALLINEA])
    banco.giro()
    assert banco.posto("zeri.jpg").contenuto != banco.posto("rotto.jpg").contenuto
    assert banco.elenco.contenuto(banco.posto("zeri.jpg").contenuto)["stato"] == "buono"
    assert banco.elenco.contenuto(
        banco.posto("rotto.jpg").contenuto)["stato"] == "incompleto"


def _scrive_male(banco: Banco, quante: int | None = None):
    fatte = []

    def regola(percorso, senza_cache, volta, lettore):
        if percorso.endswith(".ofs.nuovo") and senza_cache and (
                quante is None or len(fatte) < quante):
            fatte.append(percorso)
            return Finto(lettore, sporca={formato.TESTA.size + 4096 + 10})
        return lettore

    banco.apri.regole.append(regola)
    return fatte


def test_il_disco_che_scrive_male_due_volte_ferma_tutto(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    banco.metti("a.jpg", _dati(200_000))
    _scrive_male(banco)
    with pytest.raises(DiscoArchivioGuasto) as errore:
        banco.giro()
    assert errore.value.codice == "disco_archivio_guasto"
    assert banco.provvisori() == []
    assert banco.posto("a.jpg") is None
    giro = banco.elenco.giro("r1")
    assert giro is not None and giro["fine"] is None


def test_il_disco_che_scrive_male_una_volta_si_riprova(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    dati = _dati(200_000)
    banco.metti("a.jpg", dati)
    fatte = _scrive_male(banco, quante=1)
    giro = banco.giro()
    assert len(fatte) == 1 and giro.verde
    assert banco.dati(banco.posto("a.jpg").contenuto) == dati
    _sotto_controllo(banco)


def _blocca(banco: Banco, nome: str, errore, quante=None, quando="apri"):
    bersaglio = os.fspath(banco.sorgente / nome)
    fatte = []

    def regola(percorso, senza_cache, volta, lettore):
        if percorso == bersaglio and (quante is None or len(fatte) < quante):
            fatte.append(volta)
            if quando == "apri":
                raise errore()
            return Finto(lettore, rotti=range(0, lettore.dimensione + 1, ALLINEA),
                         errore=errore)
        return lettore

    banco.apri.regole.append(regola)
    return fatte


def test_un_file_senza_permesso_si_dice_bloccato(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    banco.metti("segreto.jpg", b"x" * 100)
    _blocca(banco, "segreto.jpg", lambda: PermissionError(errno.EACCES, "no"))
    giro = banco.giro()
    assert giro.problemi == [("bloccato", "segreto.jpg")]
    assert banco.posto("segreto.jpg") is None
    assert banco.dormite == [1.0, 3.0]


def _bloccato_da_windows(numero):
    def errore():
        guasto = OSError(errno.EACCES, "usato da un altro programma")
        guasto.winerror = numero
        return guasto
    return errore


@pytest.mark.parametrize("numero", copia.BLOCCATO)
def test_un_file_chiuso_a_chiave_da_un_altro_programma_si_dice_bloccato(
        tmp_path, chiave, numero):
    banco = Banco(tmp_path, chiave)
    banco.metti("a.pst", _dati(20_000))
    _blocca(banco, "a.pst", _bloccato_da_windows(numero), quando="leggi")
    giro = banco.giro()
    assert giro.problemi == [("bloccato", "a.pst")]
    assert banco.posto("a.pst") is None
    assert banco.provvisori() == []


def test_un_file_bloccato_una_volta_entra_al_secondo_tentativo(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    banco.metti("a.pst", b"posta")
    _blocca(banco, "a.pst", lambda: PermissionError(errno.EACCES, "no"), quante=1)
    giro = banco.giro()
    assert giro.verde and banco.dati(banco.posto("a.pst").contenuto) == b"posta"


def test_un_file_solo_nel_cloud_non_si_scarica(tmp_path, chiave, monkeypatch):
    banco = Banco(tmp_path, chiave)
    banco.metti("nuvola.jpg", b"x" * 1000)
    banco.metti("qui.jpg", b"y")
    nuvola = os.lstat(banco.sorgente / "nuvola.jpg")
    vera = metadati.solo_nel_cloud
    monkeypatch.setattr(metadati, "solo_nel_cloud",
                        lambda stato: stato.st_ino == nuvola.st_ino or vera(stato))
    riepilogo = banco.copiatore.riepiloga()
    assert riepilogo.nel_cloud == 1 and riepilogo.da_copiare == 1
    giro = banco.giro()
    assert giro.problemi == [("solo_nel_cloud", "nuvola.jpg")]
    assert not giro.verde
    assert banco.posto("nuvola.jpg") is None
    assert banco.apri.originali(banco) == [
        (os.fspath(banco.sorgente / "qui.jpg"), False),
        (os.fspath(banco.sorgente / "qui.jpg"), True)]


def test_un_file_gia_copiato_e_poi_finito_nel_cloud_resta_buono(tmp_path, chiave,
                                                                monkeypatch):
    banco = Banco(tmp_path, chiave)
    banco.metti("nuvola.jpg", b"x" * 1000)
    banco.giro()
    prima = banco.posto("nuvola.jpg")
    monkeypatch.setattr(metadati, "solo_nel_cloud", lambda stato: True)
    giro = banco.giro()
    assert giro.verde
    assert banco.posto("nuvola.jpg").chiave == prima.chiave


def test_un_file_che_sparisce_mentre_lo_copio(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    banco.metti("via.jpg", b"ciao")
    banco.giro()
    bersaglio = os.fspath(banco.sorgente / "via.jpg")
    Path(bersaglio).write_bytes(b"ciao!")

    def regola(percorso, senza_cache, volta, lettore):
        if percorso == bersaglio:
            os.unlink(percorso)
            raise FileNotFoundError(errno.ENOENT, "sparito")
        return lettore

    banco.apri.regole.append(regola)
    giro = banco.giro()
    assert banco.posto("via.jpg") is None
    assert giro.contati.get("spariti") == 1
    assert "sparito" not in _codici(giro)
    assert banco.provvisori() == []


def test_un_file_tolto_si_segna_sparito_ma_resta_nell_archivio(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    banco.metti("a.jpg", b"resta")
    percorso = banco.metti("b.jpg", b"se ne va")
    banco.giro()
    numero = banco.posto("b.jpg").contenuto
    percorso.unlink()
    giro = banco.giro()
    assert giro.contati["spariti"] == 1
    assert banco.posto("b.jpg") is None
    assert banco.posto("a.jpg") is not None
    assert banco.dati(numero) == b"se ne va"
    storia = banco.elenco.storia("r1", "b.jpg")
    assert len(storia) == 1 and storia[0].sparito is not None


def test_una_cartella_tolta_segna_spariti_tutti_i_suoi_file(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    for indice in range(4):
        banco.metti(f"2010/estate/IMG_{indice}.jpg", _dati(100, indice))
    banco.metti("2011/IMG.jpg", b"resta")
    banco.giro()
    for percorso in sorted((banco.sorgente / "2010").rglob("*"), reverse=True):
        percorso.unlink() if percorso.is_file() else percorso.rmdir()
    (banco.sorgente / "2010").rmdir()
    giro = banco.giro()
    assert giro.contati["spariti"] == 6
    restano = [posto.percorso for posto in banco.elenco.dentro("r1")]
    assert restano == ["2011", "2011/IMG.jpg"]


def test_una_cartella_spostata_mostra_il_posto_nuovo_e_tiene_quello_vecchio(
        tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    banco.metti("vecchia/a.jpg", b"aaa")
    banco.giro()
    numero = banco.posto("vecchia/a.jpg").contenuto
    os.rename(banco.sorgente / "vecchia", banco.sorgente / "nuova")
    giro = banco.giro()
    assert giro.verde
    assert banco.posto("nuova/a.jpg").contenuto == numero
    assert banco.posto("vecchia/a.jpg") is None
    assert banco.elenco.storia("r1", "vecchia/a.jpg")[0].sparito is not None
    assert len(banco.contenuti()) == 1


def test_una_cartella_che_non_si_apre_non_fa_sparire_i_suoi_file(tmp_path, chiave,
                                                                monkeypatch):
    banco = Banco(tmp_path, chiave)
    banco.metti("chiusa/a.jpg", b"a")
    banco.metti("chiusa/dentro/b.jpg", b"b")
    banco.metti("aperta/c.jpg", b"c")
    banco.giro()
    chiusa = os.fspath(banco.sorgente / "chiusa")
    vera = os.scandir

    def guarda(percorso="."):
        if os.fspath(percorso) == chiusa:
            raise PermissionError(errno.EACCES, "chiusa")
        return vera(percorso)

    monkeypatch.setattr(copia.os, "scandir", guarda)
    giro = banco.giro()
    assert giro.problemi == [("cartella_illeggibile", "chiusa")]
    assert banco.posto("chiusa/a.jpg") is not None
    assert banco.posto("chiusa/dentro/b.jpg") is not None
    assert banco.posto("chiusa") is not None
    assert "spariti" not in giro.contati


def test_la_cartella_principale_che_non_si_apre(tmp_path, chiave, monkeypatch):
    banco = Banco(tmp_path, chiave)
    banco.metti("a.jpg", b"a")
    banco.giro()
    sorgente = os.fspath(banco.sorgente)
    vera = os.scandir

    def guarda(percorso="."):
        if os.fspath(percorso) == sorgente:
            raise PermissionError(errno.EACCES, "chiusa")
        return vera(percorso)

    monkeypatch.setattr(copia.os, "scandir", guarda)
    giro = banco.giro()
    assert giro.problemi == [("radice_illeggibile", None)]
    assert banco.posto("a.jpg") is not None


def test_una_cartella_scollegata_non_fa_sparire_niente(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    banco.metti("a.jpg", b"a")
    banco.giro()
    os.rename(banco.sorgente, tmp_path / "staccata")
    giro = banco.giro()
    assert giro.problemi == [("radice_mancante", None)]
    assert giro.fine is not None and not giro.verde
    assert banco.posto("a.jpg") is not None


@pytest.mark.parametrize("nome", ["$RECYCLE.BIN", "$Recycle.Bin",
                                  "System Volume Information",
                                  "system volume information"])
def test_cestino_e_cartelle_di_sistema_si_saltano_a_ogni_livello(tmp_path, chiave,
                                                                 nome):
    banco = Banco(tmp_path, chiave)
    banco.metti(f"{nome}/x.jpg", b"x")
    banco.metti(f"2001/{nome}/y.jpg", b"y")
    banco.metti("2001/buona.jpg", b"z")
    giro = banco.giro()
    assert giro.verde
    percorsi = [posto.percorso for posto in banco.elenco.dentro("r1")]
    assert percorsi == ["2001", "2001/buona.jpg"]


@su_linux
@pytest.mark.parametrize("nome", ["a\\b.jpg", "\\", "x\\..\\y"])
def test_un_nome_che_windows_non_capirebbe_si_segnala(tmp_path, chiave, nome):
    banco = Banco(tmp_path, chiave)
    (banco.sorgente / nome).write_bytes(b"x")
    banco.metti("buona.jpg", b"y")
    giro = banco.giro()
    assert giro.problemi == [("nome_strano", nome)]
    assert [posto.percorso for posto in banco.elenco.dentro("r1")] == ["buona.jpg"]


@su_linux
def test_un_nome_con_byte_strani_si_copia_e_si_ritrova(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    nome = os.fsencode(banco.sorgente) + b"/\xff\xfeIMG.jpg"
    with open(nome, "wb") as file:
        file.write(b"byte strani")
    giro = banco.giro()
    assert giro.verde
    relativo = os.fsdecode(b"\xff\xfeIMG.jpg")
    posto = banco.posto(relativo)
    assert banco.dati(posto.contenuto) == b"byte strani"
    prima = _stato(banco.elenco)
    rifatto = _rifatto(banco)
    assert _stato(rifatto) == prima


@su_linux
def test_i_collegamenti_non_si_seguono(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    fuori = tmp_path / "fuori"
    fuori.mkdir()
    (fuori / "segreto.jpg").write_bytes(b"non deve entrare")
    banco.metti("a.jpg", b"a")
    os.symlink(fuori, banco.sorgente / "verso_fuori")
    os.symlink("a.jpg", banco.sorgente / "verso_a")
    os.symlink("nessuno", banco.sorgente / "rotto")
    giro = banco.giro()
    assert giro.verde
    posti = {posto.percorso: posto for posto in banco.elenco.dentro("r1")}
    assert set(posti) == {"a.jpg", "verso_fuori", "verso_a", "rotto"}
    for nome, bersaglio in [("verso_fuori", str(fuori)), ("verso_a", "a.jpg"),
                            ("rotto", "nessuno")]:
        assert posti[nome].tipo == "collegamento"
        assert posti[nome].contenuto is None
        assert posti[nome].metadati["bersaglio"] == bersaglio
    assert len(banco.contenuti()) == 1
    assert giro.contati["collegamenti"] == 3


@su_linux
def test_un_collegamento_cambiato_si_ricorda_di_nuovo(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    os.symlink("prima", banco.sorgente / "link")
    banco.giro()
    vecchio = banco.posto("link")
    banco.giro()
    assert banco.posto("link").chiave == vecchio.chiave
    os.unlink(banco.sorgente / "link")
    os.symlink("dopo", banco.sorgente / "link")
    banco.giro()
    assert banco.posto("link").metadati["bersaglio"] == "dopo"
    assert len(banco.elenco.storia("r1", "link")) == 2


@su_linux
def test_un_file_diventato_cartella(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    percorso = banco.metti("cosa", b"file")
    banco.giro()
    percorso.unlink()
    banco.metti("cosa/dentro.jpg", b"ora cartella")
    banco.giro()
    assert banco.posto("cosa").tipo == "cartella"
    assert banco.posto("cosa/dentro.jpg") is not None
    assert [posto.tipo for posto in banco.elenco.storia("r1", "cosa")] == [
        "file", "cartella"]


def test_le_cartelle_vuote_si_ricordano(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    (banco.sorgente / "vuota" / "anche").mkdir(parents=True)
    giro = banco.giro()
    assert giro.verde
    posti = banco.elenco.dentro("r1")
    assert [(posto.percorso, posto.tipo) for posto in posti] == [
        ("vuota", "cartella"), ("vuota/anche", "cartella")]
    banco.giro()
    assert [posto.chiave for posto in banco.elenco.dentro("r1")] == [
        posto.chiave for posto in posti]


def test_un_file_vuoto_si_copia(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    banco.metti("vuoto.txt", b"")
    banco.metti("altro_vuoto.txt", b"")
    giro = banco.giro()
    assert giro.verde
    numero = banco.posto("vuoto.txt").contenuto
    assert banco.posto("altro_vuoto.txt").contenuto == numero
    assert banco.dati(numero) == b""


def test_le_note_bastano_a_rifare_tutto_l_elenco(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    banco.metti("2001/a.jpg", b"a")
    banco.metti("2001/b.jpg", b"a")
    percorso = banco.metti("2002/c.jpg", b"ccc")
    (banco.sorgente / "vuota").mkdir()
    banco.giro()
    percorso.write_bytes(b"cccc")
    banco.metti("2003/d.jpg", b"d")
    (banco.sorgente / "2001" / "b.jpg").unlink()
    banco.giro()
    assert banco.elenco.note()
    prima = _stato(banco.elenco)
    rifatto = _rifatto(banco)
    assert rifatto.ricostruito
    assert _stato(rifatto) == prima


def test_una_cartella_con_solo_cartelle_vuote_si_rifa_dalle_note(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    (banco.sorgente / "vuota").mkdir()
    banco.giro()
    prima = _stato(banco.elenco)
    rifatto = _rifatto(banco)
    assert _stato(rifatto) == prima
    assert rifatto.radici()[0]["percorso"] == str(banco.sorgente)


def test_si_rifa_anche_un_file_in_uso_con_il_suo_segno(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    banco.metti("posta.db", _dati(30_000))
    banco.metti("vecchia.jpg", _dati(6 * ALLINEA))
    _cambia_mentre_copio(banco, "posta.db")
    _settori_rotti(banco, "vecchia.jpg", [ALLINEA])
    banco.giro()
    prima = _stato(banco.elenco)
    rifatto = _rifatto(banco)
    assert _stato(rifatto) == prima
    segni = {posto.percorso: posto.segni for posto in rifatto.dentro("r1")}
    assert segni == {"posta.db": ("in_uso",), "vecchia.jpg": ("incompleto",)}


def test_molti_fatti_vanno_in_piu_note(tmp_path, chiave, monkeypatch):
    monkeypatch.setattr(copia, "FATTI_PER_NOTA", 5)
    banco = Banco(tmp_path, chiave)
    for indice in range(12):
        banco.metti(f"IMG_{indice}.jpg", _dati(50, indice))
    banco.giro()
    assert len(banco.elenco.note()) >= 3
    prima = _stato(banco.elenco)
    assert _stato(_rifatto(banco)) == prima


def test_le_note_si_scrivono_anche_col_tempo(tmp_path, chiave, monkeypatch):
    monkeypatch.setattr(copia, "SECONDI_PER_NOTA", 0.0)
    banco = Banco(tmp_path, chiave)
    for indice in range(3):
        banco.metti(f"IMG_{indice}.jpg", _dati(50, indice))
    banco.giro()
    assert len(banco.elenco.note()) >= 3


def test_il_giro_si_ricorda_con_i_suoi_problemi(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    banco.metti("rotto.jpg", _dati(ALLINEA))
    banco.metti("buono.jpg", b"x")
    _settori_rotti(banco, "rotto.jpg", [0])
    giro = banco.giro()
    salvato = banco.elenco.giro("r1")
    assert salvato["fine"] == giro.fine and salvato["inizio"] == giro.inizio
    assert salvato["problemi"] == [{"codice": "illeggibile", "percorso": "rotto.jpg"}]
    assert salvato["contati"]["file"] == 2


def test_un_problema_con_un_percorso_lunghissimo_si_ricorda(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    banco.radice()
    giro = copia.Giro("r1", 1.0, 2.0)
    giro.problema("illeggibile", "a/" * 3000 + "b.jpg")
    banco.elenco.registra([giro.fatto()])
    assert banco.elenco.giro("r1")["problemi"][0]["percorso"].endswith("b.jpg")


def test_tanti_problemi_si_contano_senza_riempire_l_elenco(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    giro = copia.Giro("r1", 1.0, 2.0)
    for indice in range(elenco.PROBLEMI_PER_GIRO + 7):
        giro.problema("illeggibile", f"{indice}.jpg")
    banco.elenco.registra([giro.fatto()])
    salvato = banco.elenco.giro("r1")
    assert len(salvato["problemi"]) == elenco.PROBLEMI_PER_GIRO
    assert salvato["contati"]["problemi_in_piu"] == 7


def test_fermarsi_a_meta_file_non_lascia_niente_a_meta(tmp_path, chiave):
    chiamate = []

    def aspetta():
        chiamate.append(1)
        if len(chiamate) == 6:
            raise Fermato

    banco = Banco(tmp_path, chiave, aspetta=aspetta)
    banco.metti("a.jpg", _dati(ALLINEA))
    banco.metti("grande.bin", _dati(40 * ALLINEA))
    with pytest.raises(Fermato):
        banco.giro()
    assert banco.provvisori() == []
    assert banco.posto("a.jpg") is not None
    assert banco.posto("grande.bin") is None
    salvato = banco.elenco.giro("r1")
    assert salvato["fine"] is None
    assert banco.file_cifrati() == banco.contenuti() | set(banco.elenco.note())
    rifatto = _rifatto(banco)
    assert rifatto.attuale("r1", "a.jpg") is not None


def test_dopo_lo_stop_si_riprende_da_dove_si_era(tmp_path, chiave):
    fermo = [True]

    def aspetta():
        if fermo[0] and banco.copiatore.avanzamento.percorso == "c.jpg":
            raise Fermato

    banco = Banco(tmp_path, chiave, aspetta=aspetta)
    for nome in ("a.jpg", "b.jpg", "c.jpg", "d.jpg"):
        banco.metti(nome, nome.encode() * 100)
    with pytest.raises(Fermato):
        banco.giro()
    fatti = {posto.percorso for posto in banco.elenco.dentro("r1")}
    assert fatti == {"a.jpg", "b.jpg"}
    fermo[0] = False
    banco.apri.aperti.clear()
    giro = banco.giro()
    assert giro.verde
    riletti = {Path(nome).name for nome, _ in banco.apri.originali(banco)}
    assert riletti == {"c.jpg", "d.jpg"}


def test_pulisci_provvisori_toglie_solo_i_provvisori(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    banco.metti("a.jpg", b"a")
    banco.giro()
    numero = banco.posto("a.jpg").contenuto
    cartella = banco.blob(numero).parent
    (cartella / (numero + ".ofs.nuovo")).write_bytes(b"x")
    (cartella / "ab" ).mkdir()
    (cartella.parent / "ff").mkdir(exist_ok=True)
    (cartella.parent / "ff" / ("ff" * 16 + ".ofs.tenuto")).write_bytes(b"y")
    assert banco.copiatore.pulisci_provvisori() == 2
    assert banco.provvisori() == []
    assert banco.blob(numero).exists()


def test_pulisci_provvisori_senza_archivio(tmp_path, chiave):
    copiatore = Copiatore(tmp_path / "manca", None, chiave)
    assert copiatore.pulisci_provvisori() == 0


def test_lo_spazio_si_chiede_prima_di_ogni_file(tmp_path, chiave):
    chiesti = []
    banco = Banco(tmp_path, chiave, spazio=chiesti.append)
    banco.metti("a.jpg", _dati(1000))
    banco.metti("b.jpg", _dati(300_000))
    banco.giro()
    assert sorted(chiesti) == sorted([formato.peso_previsto(1000),
                                      formato.peso_previsto(300_000)])


def test_se_lo_spazio_manca_ci_si_ferma_senza_lasciare_niente(tmp_path, chiave):
    class Pieno(Exception):
        pass

    def spazio(peso):
        if peso > 100_000:
            raise Pieno

    banco = Banco(tmp_path, chiave, spazio=spazio)
    banco.metti("a.jpg", _dati(1000))
    banco.metti("b.jpg", _dati(300_000))
    with pytest.raises(Pieno):
        banco.giro()
    assert banco.provvisori() == []
    assert banco.posto("a.jpg") is not None


def test_il_disco_pieno_mentre_scrivo_non_lascia_niente(tmp_path, chiave, monkeypatch):
    banco = Banco(tmp_path, chiave)
    banco.metti("a.jpg", _dati(300_000))
    vera = formato.Scrittore.write

    def scrivi(self, dati):
        if self._ricevuti > 100_000:
            raise OSError(errno.ENOSPC, "disco pieno")
        return vera(self, dati)

    monkeypatch.setattr(formato.Scrittore, "write", scrivi)
    with pytest.raises(OSError) as errore:
        banco.giro()
    assert errore.value.errno == errno.ENOSPC
    assert banco.provvisori() == []
    assert banco.posto("a.jpg") is None


def test_un_file_diverso_da_quando_l_hai_importato_si_segnala(tmp_path, chiave):
    attesi = {"a.jpg": {"dimensione": 3, "sha256": "0" * 64},
              "b.jpg": None}

    def atteso(radice, percorso):
        return attesi.get(percorso)

    banco = Banco(tmp_path, chiave, atteso=atteso)
    banco.metti("a.jpg", b"abc")
    banco.metti("b.jpg", b"b")
    banco.metti("c.jpg", b"c")
    giro = banco.giro()
    assert giro.problemi == [("diverso_da_prima", "a.jpg")]
    assert banco.posto("a.jpg").segni == ("diverso_da_prima",)
    assert banco.posto("b.jpg").segni == ()
    assert giro.verde


def test_un_file_uguale_a_quando_l_hai_importato_non_si_segnala(tmp_path, chiave):
    import hashlib

    def atteso(radice, percorso):
        return {"dimensione": 3, "sha256": hashlib.sha256(b"abc").hexdigest(),
                "blake2b": hashlib.blake2b(b"abc", digest_size=32).hexdigest()}

    banco = Banco(tmp_path, chiave, atteso=atteso)
    banco.metti("a.jpg", b"abc")
    banco.metti("b.jpg", b"abc")
    giro = banco.giro()
    assert giro.problemi == []


def test_se_chiedere_com_era_prima_si_rompe_si_va_avanti(tmp_path, chiave):
    def atteso(radice, percorso):
        raise RuntimeError("database chiuso")

    banco = Banco(tmp_path, chiave, atteso=atteso)
    banco.metti("a.jpg", b"abc")
    assert banco.giro().verde


def test_un_file_che_si_accorcia_mentre_lo_copio_si_riprende_com_e_adesso(
        tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    percorso = banco.metti("a.jpg", _dati(20_000))
    bersaglio = os.fspath(percorso)
    fatto = []

    def regola(nome, senza_cache, volta, lettore):
        if nome == bersaglio and not fatto:
            fatto.append(1)
            with open(nome, "r+b") as file:
                file.truncate(5000)
        return lettore

    banco.apri.regole.append(regola)
    giro = banco.giro()
    assert giro.verde
    assert banco.dati(banco.posto("a.jpg").contenuto) == _dati(20_000)[:5000]


def test_un_file_che_cresce_mentre_lo_copio_si_riprende_com_e_adesso(tmp_path,
                                                                    chiave):
    banco = Banco(tmp_path, chiave)
    percorso = banco.metti("a.jpg", b"corto")
    bersaglio = os.fspath(percorso)
    fatto = []

    def regola(nome, senza_cache, volta, lettore):
        if nome == bersaglio and not senza_cache and not fatto:
            fatto.append(1)
            with open(nome, "ab") as file:
                file.write(b" e poi lungo")
        return lettore

    banco.apri.regole.append(regola)
    giro = banco.giro()
    assert giro.verde
    assert banco.dati(banco.posto("a.jpg").contenuto) == b"corto e poi lungo"


def test_un_file_cambiato_e_poi_rotto_si_tiene_quello_coi_buchi(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    dati = _dati(8 * ALLINEA)
    percorso = banco.metti("a.jpg", dati)
    bersaglio = os.fspath(percorso)

    def regola(nome, senza_cache, volta, lettore):
        if nome != bersaglio:
            return lettore
        if not senza_cache and volta == 0:
            stato = os.stat(nome)
            os.utime(nome, ns=(stato.st_atime_ns, stato.st_mtime_ns + 10 ** 9))
            return lettore
        return Finto(lettore, rotti=[ALLINEA])

    banco.apri.regole.append(regola)
    giro = banco.giro()
    assert _codici(giro) == ["incompleto"]
    posto = banco.posto("a.jpg")
    assert posto.segni == ("incompleto",)
    atteso = bytearray(dati)
    atteso[ALLINEA:2 * ALLINEA] = bytes(ALLINEA)
    assert banco.dati(posto.contenuto) == bytes(atteso)


def test_fra_tre_tentativi_coi_buchi_si_tiene_quello_con_meno_buchi(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    dati = _dati(8 * ALLINEA)
    percorso = banco.metti("a.jpg", dati)
    bersaglio = os.fspath(percorso)
    rotti = {0: [ALLINEA, 3 * ALLINEA], 1: [ALLINEA], 2: [ALLINEA, 5 * ALLINEA]}

    def regola(nome, senza_cache, volta, lettore):
        if nome != bersaglio:
            return lettore
        return Finto(lettore, rotti=rotti[volta // 2])

    banco.apri.regole.append(regola)
    banco.giro()
    atteso = bytearray(dati)
    atteso[ALLINEA:2 * ALLINEA] = bytes(ALLINEA)
    assert banco.dati(banco.posto("a.jpg").contenuto) == bytes(atteso)


def test_buchi_diversi_fra_le_due_letture_vuol_dire_cambiato(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    dati = _dati(8 * ALLINEA)
    percorso = banco.metti("a.jpg", dati)
    bersaglio = os.fspath(percorso)

    def regola(nome, senza_cache, volta, lettore):
        if nome == bersaglio and not senza_cache:
            return Finto(lettore, rotti=[2 * ALLINEA])
        return lettore

    banco.apri.regole.append(regola)
    giro = banco.giro()
    assert _codici(giro) == ["cambia_sempre"]
    assert banco.posto("a.jpg") is None
    assert banco.provvisori() == []


def test_il_riepilogo_conta_quello_che_c_e_da_fare(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    banco.metti("2001/a.jpg", _dati(1000, 1))
    banco.metti("2001/b.jpg", _dati(1000, 1))
    banco.metti("2001/c.jpg", _dati(1000, 2))
    banco.metti("2002/d.jpg", _dati(5000, 3))
    banco.metti("2002/vuota/.keep", b"")
    riepilogo = banco.copiatore.riepiloga()
    assert riepilogo.cartelle == 3
    assert riepilogo.file == 5
    assert riepilogo.byte == 8000
    assert riepilogo.da_copiare == 5
    assert riepilogo.byte_da_copiare == 8000
    assert riepilogo.forse_doppioni == 2
    assert riepilogo.radici["r1"] == {"file": 5, "byte": 8000,
                                      "byte_da_copiare": 8000}
    peso = (3 * formato.peso_previsto(1000) + formato.peso_previsto(5000)
            + formato.peso_previsto(0))
    assert riepilogo.spazio_serve == int(peso * copia.SPAZIO_IN_PIU)
    assert riepilogo.spazio_libero > 0 and riepilogo.basta_lo_spazio
    assert riepilogo.secondi == pytest.approx(2 * 8000 / copia.VELOCITA)
    assert banco.contenuti() == set()
    banco.giro()
    dopo = banco.copiatore.riepiloga()
    assert dopo.da_copiare == 0 and dopo.byte_da_copiare == 0
    assert dopo.forse_doppioni == 0 and dopo.spazio_serve == 0
    assert dopo.file == 5


def test_il_riepilogo_sa_dei_doppioni_gia_nell_archivio(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    banco.metti("a.jpg", _dati(777))
    banco.giro()
    banco.metti("b.jpg", _dati(777))
    banco.metti("c.jpg", _dati(778))
    riepilogo = banco.copiatore.riepiloga()
    assert riepilogo.da_copiare == 2
    assert riepilogo.forse_doppioni == 1


def test_il_riepilogo_dice_delle_cartelle_scollegate(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    banco.elenco.registra([elenco.fatto_radice("r2", str(tmp_path / "manca"))])
    riepilogo = banco.copiatore.riepiloga()
    assert ("radice_mancante", "r2") in riepilogo.problemi


def test_il_riepilogo_salta_le_cartelle_tolte(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    altra = tmp_path / "altra"
    altra.mkdir()
    (altra / "x.jpg").write_bytes(b"x")
    banco.elenco.registra([elenco.fatto_radice("r2", str(altra), tolta=True)])
    banco.metti("a.jpg", b"a")
    riepilogo = banco.copiatore.riepiloga()
    assert set(riepilogo.radici) == {"r1"} and riepilogo.file == 1


def test_il_riepilogo_con_poco_spazio(tmp_path, chiave, monkeypatch):
    banco = Banco(tmp_path, chiave)
    banco.metti("a.jpg", _dati(10_000))
    monkeypatch.setattr(copia, "spazio_libero", lambda cartella: 10)
    riepilogo = banco.copiatore.riepiloga()
    assert not riepilogo.basta_lo_spazio


def test_lo_spazio_libero_di_una_cartella_che_non_c_e_ancora(tmp_path):
    assert copia.spazio_libero(tmp_path / "a" / "b" / "c") > 0


def test_due_cartelle_principali_restano_separate(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    altra = tmp_path / "telefono"
    altra.mkdir()
    (altra / "a.jpg").write_bytes(b"stessa")
    banco.metti("a.jpg", b"stessa")
    banco.elenco.registra([elenco.fatto_radice("r2", str(altra))])
    banco.giro("r1")
    banco.giro("r2")
    primo = banco.elenco.attuale("r1", "a.jpg")
    secondo = banco.elenco.attuale("r2", "a.jpg")
    assert primo.chiave != secondo.chiave
    assert primo.contenuto == secondo.contenuto
    (altra / "a.jpg").unlink()
    banco.giro("r2")
    assert banco.elenco.attuale("r1", "a.jpg") is not None
    assert banco.elenco.attuale("r2", "a.jpg") is None


def test_l_avanzamento_dice_dove_sono(tmp_path, chiave):
    visti = []

    def aspetta():
        avanzamento = banco.copiatore.avanzamento
        visti.append((avanzamento.radice, avanzamento.percorso))

    banco = Banco(tmp_path, chiave, aspetta=aspetta)
    banco.metti("a.jpg", b"a")
    banco.giro()
    assert ("r1", "a.jpg") in visti
    assert banco.copiatore.avanzamento.percorso is None
    assert banco.copiatore.avanzamento.letti >= 2


def test_un_giro_verde_e_rosso():
    giro = copia.Giro("r1", 1.0)
    assert not giro.verde
    giro.fine = 2.0
    assert giro.verde
    giro.problema("permessi_illeggibili", "a.jpg")
    assert giro.verde
    giro.problema("in_uso", "b.jpg")
    assert not giro.verde and giro.rossi == [("in_uso", "b.jpg")]
    giro.conta("file")
    giro.conta("file", 2)
    assert giro.contati == {"file": 3}


@pytest.mark.parametrize("percorso,cartelle,atteso", [
    ("a/b/c.jpg", {"a"}, True),
    ("a/b/c.jpg", {"a/b"}, True),
    ("a/b/c.jpg", {"a/b/c.jpg"}, True),
    ("a/b/c.jpg", {"a/bb"}, False),
    ("a/b/c.jpg", {"b"}, False),
    ("ab/c.jpg", {"a"}, False),
    ("a.jpg", {""}, True),
    ("a.jpg", set(), False),
])
def test_sotto_una_cartella(percorso, cartelle, atteso):
    assert copia._sotto(percorso, cartelle) is atteso


def test_l_archivio_dentro_la_cartella_non_si_copia_da_solo(tmp_path, chiave):
    sorgente = tmp_path / "foto"
    sorgente.mkdir()
    (sorgente / "a.jpg").write_bytes(b"a")
    archivio = sorgente / "programma" / "archivio"
    aperto = Elenco.apri(archivio, chiave)
    aperto.registra([elenco.fatto_radice("r1", str(sorgente))])
    copiatore = Copiatore(archivio, aperto, chiave, dormi=lambda s: None)
    radice = aperto.radici()[0]
    giro = copiatore.copia_radice(radice)
    giro = copiatore.copia_radice(radice)
    assert giro.verde and giro.contati["saltate"] == 1
    assert [posto.percorso for posto in aperto.dentro("r1")] == [
        "a.jpg", "programma"]


def test_altre_cartelle_da_saltare(tmp_path, chiave):
    banco = Banco(tmp_path, chiave, salta=[tmp_path / "foto" / "miniature"])
    banco.metti("miniature/x.jpg", b"x")
    banco.metti("a.jpg", b"a")
    giro = banco.giro()
    assert giro.verde
    assert [posto.percorso for posto in banco.elenco.dentro("r1")] == ["a.jpg"]


def test_una_cartella_principale_che_e_l_archivio_non_fa_sparire_niente(tmp_path,
                                                                       chiave):
    banco = Banco(tmp_path, chiave)
    banco.metti("a.jpg", b"a")
    banco.giro()
    banco.elenco.registra([elenco.fatto_radice("r2", str(banco.archivio))])
    giro = banco.giro("r2")
    assert giro.problemi == [("radice_nell_archivio", None)]
    assert not giro.verde
    assert banco.elenco.dentro("r2") == []


GUASTI = ("nessuno", "nessuno", "nessuno", "nessuno", "nessuno", "rotti",
          "passeggeri", "cambia", "cambia_una", "bloccato", "sparisce", "tutti_rotti")


def _albero_a_caso(banco: Banco, caso: random.Random) -> dict[str, bytes]:
    cartelle = [""] + [f"{2000 + caso.randrange(6)}"
                       + ("/" + caso.choice(["mare", "neve", "casa"])
                          if caso.random() < 0.5 else "")
                       for _ in range(caso.randrange(1, 5))]
    gruppi = [caso.randbytes(caso.choice([0, 1, 100, ALLINEA, 3 * ALLINEA + 5,
                                          caso.randrange(1, 40_000)]))
              for _ in range(caso.randrange(2, 8))]
    file = {}
    for indice in range(caso.randrange(3, 18)):
        cartella = caso.choice(cartelle)
        relativo = (f"{cartella}/IMG_{indice:03d}.jpg" if cartella
                    else f"IMG_{indice:03d}.jpg")
        dati = caso.choice(gruppi) if caso.random() < 0.4 else caso.randbytes(
            caso.randrange(0, 30_000))
        banco.metti(relativo, dati)
        file[relativo] = dati
    for _ in range(caso.randrange(0, 3)):
        (banco.sorgente / caso.choice(cartelle) / f"vuota{caso.randrange(9)}").mkdir(
            parents=True, exist_ok=True)
    return file


def _settori(dati: bytes) -> list[int]:
    return list(range(0, len(dati), ALLINEA))


def _metti_guasti(banco: Banco, file: dict[str, bytes], caso: random.Random):
    guasti = {}
    for relativo, dati in file.items():
        tipo = caso.choice(GUASTI)
        settori = _settori(dati)
        if tipo in ("rotti", "passeggeri", "cambia", "cambia_una",
                    "tutti_rotti") and not settori:
            tipo = "nessuno"
        if tipo == "rotti" and len(settori) < 2:
            tipo = "tutti_rotti"
        rotti = ()
        if tipo == "rotti":
            rotti = tuple(sorted(caso.sample(settori, caso.randrange(
                1, len(settori)))))
        elif tipo in ("passeggeri", "tutti_rotti"):
            rotti = tuple(settori)
        guasti[os.fspath(banco.sorgente / relativo)] = [tipo, rotti, 0]

    def regola(percorso, senza_cache, volta, lettore):
        guasto = guasti.get(percorso)
        if guasto is None:
            return lettore
        tipo, rotti, fatte = guasto
        if tipo in ("rotti", "tutti_rotti"):
            return Finto(lettore, rotti=rotti)
        if tipo == "passeggeri":
            return Finto(lettore, rotti=rotti, volte=2)
        if tipo == "bloccato":
            raise PermissionError(errno.EACCES, "bloccato")
        if tipo == "sparisce":
            os.unlink(percorso)
            raise FileNotFoundError(errno.ENOENT, "sparito")
        if tipo in ("cambia", "cambia_una") and not senza_cache and (
                tipo == "cambia" or fatte == 0):
            guasto[2] += 1
            dati = bytearray(Path(percorso).read_bytes())
            dati[0] = (dati[0] + 1) % 256
            Path(percorso).write_bytes(bytes(dati))
            stato = os.stat(percorso)
            os.utime(percorso, ns=(stato.st_atime_ns, stato.st_mtime_ns + 10 ** 9))
        return lettore

    banco.apri.regole.append(regola)
    return {relativo: guasti[os.fspath(banco.sorgente / relativo)]
            for relativo in file}


def _con_buchi(dati: bytes, rotti) -> bytes:
    pieno = bytearray(dati)
    for settore in rotti:
        fine = min(len(dati), settore + ALLINEA)
        pieno[settore:fine] = bytes(fine - settore)
    return bytes(pieno)


def _controlla_il_giro(banco: Banco, giro, file: dict[str, bytes], guasti: dict):
    rossi = set()
    for relativo, dati in file.items():
        tipo, rotti, _ = guasti[relativo]
        posto = banco.posto(relativo)
        sorgente = banco.sorgente / relativo
        if tipo in ("nessuno", "passeggeri", "cambia_una"):
            assert posto is not None and posto.segni == (), relativo
            assert banco.dati(posto.contenuto) == sorgente.read_bytes()
            assert banco.elenco.contenuto(posto.contenuto)["stato"] == "buono"
        elif tipo == "rotti":
            assert posto.segni == ("incompleto",)
            assert banco.dati(posto.contenuto) == _con_buchi(dati, rotti)
            assert banco.elenco.contenuto(posto.contenuto)["stato"] == "incompleto"
            rossi.add(("incompleto", relativo))
        elif tipo == "cambia":
            assert posto.segni == ("in_uso",)
            assert banco.dati(posto.contenuto) == sorgente.read_bytes()
            rossi.add(("in_uso", relativo))
        elif tipo == "bloccato":
            assert posto is None
            rossi.add(("bloccato", relativo))
        elif tipo == "tutti_rotti":
            assert posto is None
            rossi.add(("illeggibile", relativo))
        elif tipo == "sparisce":
            assert posto is None and not sorgente.exists()
    assert set(giro.rossi) == rossi
    assert len(giro.rossi) == len(rossi)
    assert giro.verde is (not rossi)
    _sotto_controllo(banco)


def _cambia_a_caso(banco: Banco, file: dict[str, bytes], caso: random.Random):
    for relativo in list(file):
        sorgente = banco.sorgente / relativo
        if not sorgente.exists():
            del file[relativo]
            continue
        scelta = caso.random()
        if scelta < 0.15:
            sorgente.unlink()
            del file[relativo]
        elif scelta < 0.3:
            dati = caso.randbytes(caso.randrange(0, 20_000))
            sorgente.write_bytes(dati)
            stato = os.stat(sorgente)
            os.utime(sorgente, ns=(stato.st_atime_ns, stato.st_mtime_ns + 10 ** 9))
            file[relativo] = dati
        else:
            file[relativo] = sorgente.read_bytes()
    for indice in range(caso.randrange(0, 4)):
        relativo = f"nuove/N_{indice}.jpg"
        dati = caso.randbytes(caso.randrange(0, 9000))
        banco.metti(relativo, dati)
        file[relativo] = dati


@pytest.mark.parametrize("seme", range(160))
def test_a_caso_con_guasti_e_poi_senza(tmp_path, chiave, seme):
    caso = random.Random(seme)
    banco = Banco(tmp_path, chiave)
    file = _albero_a_caso(banco, caso)
    riepilogo = banco.copiatore.riepiloga()
    assert riepilogo.file == len(file)
    assert riepilogo.byte == sum(len(dati) for dati in file.values())
    guasti = _metti_guasti(banco, file, caso)
    giro = banco.giro()
    _controlla_il_giro(banco, giro, file, guasti)
    prima = _stato(banco.elenco)
    rifatto = _rifatto(banco)
    assert _stato(rifatto) == prima
    rifatto.chiudi()
    banco = Banco(tmp_path, chiave)
    _cambia_a_caso(banco, file, caso)
    numeri = banco.contenuti()
    giro = banco.giro()
    assert giro.verde, giro.problemi
    for relativo, dati in file.items():
        posto = banco.posto(relativo)
        assert posto.segni == ()
        assert banco.dati(posto.contenuto) == dati
    presenti = {posto.percorso for posto in banco.elenco.dentro("r1")
                if posto.tipo == "file"}
    assert presenti == set(file)
    assert numeri <= banco.contenuti()
    _sotto_controllo(banco)
    dopo = banco.copiatore.riepiloga()
    assert dopo.da_copiare == 0
    numeri = banco.contenuti()
    chiavi_prima = {posto.chiave for posto in banco.elenco.dentro("r1")}
    banco.giro()
    assert banco.contenuti() == numeri
    assert {posto.chiave for posto in banco.elenco.dentro("r1")} == chiavi_prima
    prima = _stato(banco.elenco)
    assert _stato(_rifatto(banco)) == prima
