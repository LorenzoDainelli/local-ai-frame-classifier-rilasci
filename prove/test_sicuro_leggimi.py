from __future__ import annotations

import hashlib
import json
import os
import random
import re
import sqlite3
import sys
import zlib
from pathlib import Path

import pytest
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from officina.sicuro import chiavetta, chiavi, diario, elenco as registro, estrai, formato
from officina.sicuro import leggimi, recupera
from officina.sicuro.chiavetta import CARTELLA, PROGRAMMINO, Chiavetta
from officina.sicuro.copia import Copiatore
from officina.sicuro.elenco import Elenco

PASSWORD = "spiegazione con parole finte"
QUANDO = 1_600_000_000
SEGRETO = bytes(range(32))
NOMI_STRANI = sys.platform.startswith("linux")

FILE = {
    "vuoto.bin": 0,
    "uno.bin": 1,
    "quasi un blocco.bin": formato.BLOCCO - 1,
    "un blocco.bin": formato.BLOCCO,
    "un blocco e uno.bin": formato.BLOCCO + 1,
    "estate/città è più.jpg": 3 * formato.BLOCCO + 7,
    "estate/mare/onda.mov": 700_001,
    "inverno/neve ❄.png": 4096,
}
VUOTE = ("inverno/niente", "estate/mare/sabbia")


def _hkdf(segreto: bytes, uso: bytes, quanto: int = 32) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=quanto, salt=bytes(32),
                info=b"officina-sicuro\x00" + uso).derive(segreto)


def _intero(dati: bytes, da: int, a: int) -> int:
    return int.from_bytes(dati[da:a + 1], "big")


def _su(quanto: int, per: int) -> int:
    return -(-quanto // per)


def _nonce(tipo: int, indice: int) -> bytes:
    return tipo.to_bytes(4, "big") + indice.to_bytes(8, "big")


def _segreto(cartella: Path, password: str) -> bytes:
    chiave = json.loads((cartella / "chiave.json").read_text("utf-8"))
    assert chiave["tipo"] == "officina-archivio-sicuro-chiave"
    assert chiave["versione"] == 1
    assert re.fullmatch(r"[0-9a-f]{32}", chiave["nome"])
    for porta in chiave["porte"]:
        assert porta["kdf"] == "scrypt"
        assert re.fullmatch(r"[0-9a-f]{16}", porta["numero"])
        assert re.fullmatch(r"[0-9a-f]{32}", porta["sale"])
        assert re.fullmatch(r"[0-9a-f]{24}", porta["nonce"])
        assert re.fullmatch(r"[0-9a-f]{96}", porta["chiusa"])
        n, r, p = porta["n"], porta["r"], porta["p"]
        k = hashlib.scrypt(password.encode("utf-8"), salt=bytes.fromhex(porta["sale"]),
                           n=n, r=r, p=p, dklen=32, maxmem=256 * n * r)
        a = b"\x00".join(str(parte).encode("ascii") for parte in (
            "officina-archivio-sicuro-chiave", 1, porta["numero"], n, r, p))
        try:
            s = AESGCM(k).decrypt(bytes.fromhex(porta["nonce"]),
                                  bytes.fromhex(porta["chiusa"]), a)
        except InvalidTag:
            continue
        assert len(s) == 32
        assert _hkdf(s, b"nome", 16).hex() == chiave["nome"]
        return s
    raise LookupError("nessuna porta si apre con questa password")


def _intestazione(dati: bytes) -> dict:
    assert len(dati) == 64
    assert dati[0:8] == b"OFSICURO"
    assert zlib.crc32(dati[0:60]) == _intero(dati, 60, 63)
    assert _intero(dati, 8, 9) == 1
    assert _intero(dati, 10, 11) == 0
    assert dati[52:60] == bytes(8)
    return {"numero": dati[12:28], "blocco": _intero(dati, 28, 31),
            "pezzo": _intero(dati, 32, 35), "gruppo": _intero(dati, 36, 37),
            "passo": _intero(dati, 38, 39), "dimensione": _intero(dati, 40, 47),
            "meta": _intero(dati, 48, 51)}


class Ofs:

    def __init__(self, dati: bytes, k_contenuti: bytes):
        self.dati = dati
        self.testa = dati[:64]
        assert dati[-64:] == self.testa
        t = _intestazione(self.testa)
        self.numero = t["numero"]
        self.blocco, self.pezzo = t["blocco"], t["pezzo"]
        self.gruppo, self.passo = t["gruppo"], t["passo"]
        self.dimensione, self.meta = t["dimensione"], t["meta"]
        self.aes = AESGCM(_hkdf(k_contenuti, b"contenuto\x00" + self.numero))
        self.inizio = 64 + self.meta
        self.blocchi = max(1, _su(self.dimensione, self.blocco))
        self.nastro = self.dimensione + 16 * self.blocchi
        self.pezzi = _su(self.nastro, self.pezzo)
        self.fascia = self.gruppo * self.passo
        self.fasce = _su(self.pezzi, self.fascia)
        riserve = sum(min(self.passo, self.in_fascia(f)) for f in range(self.fasce))
        assert len(dati) == 2 * self.inizio + (self.pezzi + riserve) * self.pezzo
        self.rifatti = 0

    def in_fascia(self, f: int) -> int:
        return min(self.fascia, self.pezzi - f * self.fascia)

    def _inizio_fascia(self, f: int) -> int:
        return self.inizio + f * (self.fascia + self.passo) * self.pezzo

    def _pezzo(self, k: int) -> bytes:
        f, dentro = divmod(k, self.fascia)
        dove = self._inizio_fascia(f) + dentro * self.pezzo
        return self.dati[dove:dove + self.pezzo]

    def _rifatto(self, k: int) -> bytes:
        f, dentro = divmod(k, self.fascia)
        colonna = dentro % self.passo
        dove = self._inizio_fascia(f) + (self.in_fascia(f) + colonna) * self.pezzo
        uscita = int.from_bytes(self.dati[dove:dove + self.pezzo], "big")
        for altro in range(colonna, self.in_fascia(f), self.passo):
            if altro != dentro:
                uscita ^= int.from_bytes(self._pezzo(f * self.fascia + altro), "big")
        return uscita.to_bytes(self.pezzo, "big")

    def informazioni(self) -> dict | None:
        for dove in (64, len(self.dati) - 64 - self.meta):
            try:
                chiaro = self.aes.decrypt(_nonce(1, 0), self.dati[dove:dove + self.meta],
                                          self.testa[:60])
            except InvalidTag:
                continue
            lungo = _intero(chiaro, 0, 3)
            assert chiaro[4 + lungo:] == bytes(len(chiaro) - 4 - lungo)
            return json.loads(chiaro[4:4 + lungo].decode("utf-8", "surrogatepass"))
        return None

    def _blocco(self, i: int) -> bytes:
        lungo = (self.blocco if i < self.blocchi - 1
                 else self.dimensione - (self.blocchi - 1) * self.blocco) + 16
        da = i * (self.blocco + 16)
        primo, ultimo = da // self.pezzo, (da + lungo - 1) // self.pezzo
        pezzi = {k: self._pezzo(k) for k in range(primo, ultimo + 1)}

        def apri(pezzi):
            tutto = b"".join(pezzi[k] for k in range(primo, ultimo + 1))
            inizio = da - primo * self.pezzo
            return self.aes.decrypt(_nonce(0, i), tutto[inizio:inizio + lungo],
                                    self.testa[:60])
        try:
            return apri(pezzi)
        except InvalidTag:
            pass
        for k in pezzi:
            try:
                chiaro = apri({**pezzi, k: self._rifatto(k)})
            except InvalidTag:
                continue
            self.rifatti += 1
            return chiaro
        raise InvalidTag

    def foto(self) -> bytes:
        dati = b"".join(self._blocco(i) for i in range(self.blocchi))
        assert len(dati) == self.dimensione
        informazioni = self.informazioni()
        if informazioni is not None:
            impronte = informazioni["impronte"]
            assert hashlib.blake2b(dati, digest_size=32).hexdigest() == impronte["blake2b"]
            assert hashlib.sha256(dati).hexdigest() == impronte["sha256"]
        return dati


def _diario(dati: bytes, k_diario: bytes) -> list[dict]:
    testa = dati[:64]
    assert testa[0:8] == b"OFDIARIO"
    assert zlib.crc32(testa[0:60]) == _intero(testa, 60, 63)
    assert _intero(testa, 8, 9) == 1 and _intero(testa, 10, 11) == 0
    assert testa[52:60] == bytes(8)
    numero, generazione = testa[12:28], testa[28:36]
    aes = AESGCM(k_diario)
    assert aes.decrypt(numero[:12], testa[36:52], b"OFDIARIO" + numero + generazione) == b""
    righe: list[dict | None] = []
    dove = 64
    while dove + 8 <= len(dati):
        lungo = _intero(dati, dove, dove + 3)
        corpo = dati[dove + 8:dove + 8 + lungo]
        posto = len(righe).to_bytes(8, "big")
        riga = None
        if (len(corpo) == lungo
                and zlib.crc32(dati[dove:dove + 4] + corpo) == _intero(dati, dove + 4, dove + 7)):
            chiaro = aes.decrypt(corpo[:12], corpo[12:],
                                 b"OFDIARIO" + numero + generazione + posto)
            riga = json.loads(chiaro.decode("utf-8", "surrogatepass"))
        righe.append(riga)
        dove += 8 + lungo
    return righe


def _testo(valore):
    return valore.decode("utf-8", "surrogatepass") if isinstance(valore, bytes) else valore


def _cartelle(db: sqlite3.Connection) -> dict[str, dict[str, tuple]]:
    uscita = {}
    for id_, percorso in db.execute("SELECT id, percorso FROM radici"):
        scelti: dict[str, tuple] = {}
        for _, posto, tipo, contenuto, metadati, visto in db.execute(
                "SELECT rowid, percorso, tipo, contenuto, metadati, visto FROM posti "
                "WHERE radice = ? AND sparito IS NULL ORDER BY visto, rowid", (id_,)):
            scelti[_testo(posto)] = (_testo(tipo), _testo(contenuto), json.loads(metadati))
        nome = _testo(percorso).replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
        uscita[nome] = scelti
    return uscita


def _metti_le_foto(sorgente: Path) -> dict[str, bytes]:
    caso = random.Random(5)
    messi = {}
    nomi = dict(FILE)
    if NOMI_STRANI:
        nomi[os.fsdecode(b"strano \xff\xfe.bin")] = 33
    for numero, (relativo, peso) in enumerate(nomi.items()):
        percorso = sorgente / relativo
        percorso.parent.mkdir(parents=True, exist_ok=True)
        dati = caso.randbytes(peso)
        percorso.write_bytes(dati)
        os.utime(percorso, ns=((QUANDO + numero * 3601) * 10 ** 9 + 7,) * 2)
        messi[relativo] = dati
    for relativo in VUOTE:
        (sorgente / relativo).mkdir(parents=True, exist_ok=True)
    return messi


@pytest.fixture(scope="module")
def archivio_finto(tmp_path_factory):
    base = tmp_path_factory.mktemp("leggimi")
    sorgente = base / "Le mie foto"
    archivio = base / "archivio"
    sopra = base / "chiavetta"
    sorgente.mkdir()
    sopra.mkdir()
    messi = _metti_le_foto(sorgente)
    programmino = base / "finto.exe"
    programmino.write_bytes(b"MZ finto")
    chiave = chiavi.crea(archivio, PASSWORD, costo=chiavi.COSTO)
    elenco = Elenco.apri(archivio, chiave)
    try:
        elenco.registra([registro.fatto_radice("r1", str(sorgente), quando=float(QUANDO))])
        radice = next(radice for radice in elenco.radici() if radice["id"] == "r1")
        assert Copiatore(archivio, elenco, chiave).copia_radice(radice).verde
        lavoro = Chiavetta(archivio, elenco, chiave, programmino=programmino,
                           stesso_disco=lambda uno, altro: False,
                           leggimi=leggimi.per_la_chiavetta())
        assert lavoro.prepara(sopra).va_bene
        resoconto = lavoro.aggiorna(sopra)
        assert resoconto.finito and not resoconto.guai and not resoconto.problemi
    finally:
        elenco.chiudi()
    return {"sorgente": sorgente, "messi": messi, "chiavetta": sopra,
            "archivio": archivio}


def _leggi_tutto(cartella: Path, password: str) -> dict:
    s = _segreto(cartella, password)
    k_contenuti = _hkdf(s, b"contenuti")
    contenuti = {}
    for percorso in sorted((cartella / "contenuti").glob("*/*.ofs")):
        numero = percorso.stem
        assert re.fullmatch(r"[0-9a-f]{32}", numero) and percorso.parent.name == numero[:2]
        ofs = Ofs(percorso.read_bytes(), k_contenuti)
        assert ofs.numero.hex() == numero
        contenuti[numero] = ofs
    fotografie = sorted((cartella / "elenco").glob("fotografia-*.ofs"))
    assert fotografie and all(re.fullmatch(r"fotografia-\d{8}\.ofs", p.name)
                              for p in fotografie)
    ultima = fotografie[-1]
    ofs = Ofs(ultima.read_bytes(), k_contenuti)
    dati = ofs.informazioni()["dati"]
    assert set(dati) == {"tipo", "generazione", "schema", "scritto"}
    assert dati["tipo"] == "fotografia" and dati["schema"] == 1
    assert dati["generazione"] == int(ultima.stem.split("-")[1])
    return {"s": s, "contenuti": contenuti, "database": ofs.foto()}


def test_la_chiavetta_si_legge_seguendo_solo_la_spiegazione(archivio_finto, tmp_path):
    sopra = archivio_finto["chiavetta"]
    testo = (sopra / chiavetta.LEGGIMI).read_bytes().decode("utf-8")
    assert testo == leggimi.per_la_chiavetta()
    assert (sopra / PROGRAMMINO).is_file()
    cartella = sopra / CARTELLA
    letto = _leggi_tutto(cartella, PASSWORD)
    with pytest.raises(LookupError):
        _segreto(cartella, "un'altra password finta")
    percorso_db = tmp_path / "fotografia.sqlite"
    percorso_db.write_bytes(letto["database"])
    db = sqlite3.connect(percorso_db)
    try:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 1
        for numero, dimensione, blake2b, sha256, peso, testa, stato in db.execute(
                "SELECT numero, dimensione, blake2b, sha256, peso, testa, stato "
                "FROM contenuti"):
            ofs = letto["contenuti"][numero]
            assert testa == ofs.testa and dimensione == ofs.dimensione
            assert peso == len(ofs.dati) and stato == "buono"
            impronte = ofs.informazioni()["impronte"]
            assert impronte == {"blake2b": blake2b, "sha256": sha256}
        cartelle = _cartelle(db)
    finally:
        db.close()
    assert set(cartelle) == {"Le mie foto"}
    posti = cartelle["Le mie foto"]
    sorgente = archivio_finto["sorgente"]
    attesi = {p.relative_to(sorgente).as_posix() for p in sorgente.rglob("*")}
    assert set(posti) - {""} == attesi
    for relativo, (tipo, numero, metadati) in posti.items():
        vero = sorgente / relativo
        if relativo in archivio_finto["messi"]:
            assert tipo == "file"
            ofs = letto["contenuti"][numero]
            assert ofs.foto() == archivio_finto["messi"][relativo]
            informazioni = ofs.informazioni()["dati"]
            assert set(informazioni) == {"fatti", "scritto"}
            assert any(fatto.get("fatto") == "posto" and fatto.get("percorso") == relativo
                       for fatto in informazioni["fatti"])
            assert metadati["modifica"] == os.stat(vero).st_mtime_ns
        else:
            assert tipo == "cartella" and vero.is_dir()
    usati = {numero for _, numero, _ in posti.values() if numero}
    assert usati <= set(letto["contenuti"])
    if NOMI_STRANI:
        assert os.fsdecode(b"strano \xff\xfe.bin") in posti


def test_anche_il_computer_si_legge_cosi(archivio_finto):
    letto = _leggi_tutto(archivio_finto["archivio"], PASSWORD)
    sopra = _leggi_tutto(archivio_finto["chiavetta"] / CARTELLA, PASSWORD)
    assert letto["s"] == sopra["s"]
    assert set(letto["contenuti"]) == set(sopra["contenuti"])


def test_la_chiave_di_riserva_e_uguale(archivio_finto):
    cartella = archivio_finto["chiavetta"] / CARTELLA
    prima = json.loads((cartella / chiavi.FILE).read_text("utf-8"))
    riserva = json.loads((cartella / chiavi.RISERVA).read_text("utf-8"))
    assert prima == riserva


def _scritto(tmp_path, monkeypatch, quanto: int, seme: int, passo_massimo: int = 16):
    monkeypatch.setattr(formato, "PASSO_MASSIMO", passo_massimo)
    dati = random.Random(seme).randbytes(quanto)
    percorso = tmp_path / f"{seme}.ofs"
    with open(percorso, "wb") as fuori:
        formato.scrivi_byte(fuori, chiavi.Chiave(SEGRETO), dati,
                            {"fatti": [], "scritto": 1.5})
    return percorso, dati


def _rovina(dati: bytearray, dove: int) -> None:
    for spostamento in range(9, 41):
        dati[dove + spostamento] ^= 0x5A


@pytest.mark.parametrize("seme", range(4))
def test_le_fasce_e_le_riserve_sono_come_dice_il_testo(tmp_path, monkeypatch, seme):
    quanto = 3 * 1024 * 1024 + seme * 70_001
    percorso, dati = _scritto(tmp_path, monkeypatch, quanto, seme)
    k_contenuti = _hkdf(SEGRETO, b"contenuti")
    ofs = Ofs(percorso.read_bytes(), k_contenuti)
    assert ofs.fasce > 1
    assert ofs.foto() == dati and ofs.rifatti == 0
    caso = random.Random(seme)
    rotto = bytearray(ofs.dati)
    for f in range(ofs.fasce):
        k = f * ofs.fascia + caso.randrange(ofs.in_fascia(f))
        dentro = k - f * ofs.fascia
        _rovina(rotto, ofs._inizio_fascia(f) + dentro * ofs.pezzo)
    riparato = Ofs(bytes(rotto), k_contenuti)
    assert riparato.foto() == dati
    assert riparato.rifatti == ofs.fasce


def test_una_riserva_rovinata_non_fa_niente(tmp_path, monkeypatch):
    percorso, dati = _scritto(tmp_path, monkeypatch, 2 * 1024 * 1024 + 3, 9)
    k_contenuti = _hkdf(SEGRETO, b"contenuti")
    ofs = Ofs(percorso.read_bytes(), k_contenuti)
    rotto = bytearray(ofs.dati)
    for f in range(ofs.fasce):
        _rovina(rotto, ofs._inizio_fascia(f) + ofs.in_fascia(f) * ofs.pezzo)
    assert Ofs(bytes(rotto), k_contenuti).foto() == dati


@pytest.mark.parametrize("quanto", [0, 1, 100, formato.BLOCCO - 1, formato.BLOCCO,
                                    formato.BLOCCO + 1, 5 * formato.BLOCCO + 17])
def test_piccoli_e_al_bordo(tmp_path, monkeypatch, quanto):
    percorso, dati = _scritto(tmp_path, monkeypatch, quanto, quanto,
                              formato.PASSO_MASSIMO)
    k_contenuti = _hkdf(SEGRETO, b"contenuti")
    ofs = Ofs(percorso.read_bytes(), k_contenuti)
    assert ofs.foto() == dati
    assert ofs.informazioni()["dati"] == {"fatti": [], "scritto": 1.5}
    rotto = bytearray(ofs.dati)
    _rovina(rotto, ofs.inizio + (ofs.pezzi - 1) * ofs.pezzo)
    assert Ofs(bytes(rotto), k_contenuti).foto() == dati


def test_le_informazioni_hanno_due_copie(tmp_path, monkeypatch):
    percorso, dati = _scritto(tmp_path, monkeypatch, 3 * formato.BLOCCO, 21)
    k_contenuti = _hkdf(SEGRETO, b"contenuti")
    ofs = Ofs(percorso.read_bytes(), k_contenuti)
    prima = bytearray(ofs.dati)
    prima[64 + 30] ^= 1
    assert Ofs(bytes(prima), k_contenuti).informazioni() == ofs.informazioni()
    seconda = bytearray(ofs.dati)
    seconda[len(seconda) - 64 - ofs.meta + 30] ^= 1
    assert Ofs(bytes(seconda), k_contenuti).informazioni() == ofs.informazioni()
    tutte = bytearray(prima)
    tutte[len(tutte) - 64 - ofs.meta + 30] ^= 1
    senza = Ofs(bytes(tutte), k_contenuti)
    assert senza.informazioni() is None
    assert senza.foto() == dati


def test_il_diario_si_legge_seguendo_la_spiegazione(tmp_path):
    archivio = tmp_path / "archivio"
    chiave = chiavi.Chiave(SEGRETO)
    elenco = Elenco.apri(archivio, chiave)
    fatti = [registro.fatto_radice("r1", "/finta/cartella è", quando=10.0),
             registro.fatto_radice("r2", "/finta/altra", quando=11.0)]
    altri = [registro.fatto_sparito("ab" * 16, quando=12.0),
             registro.fatto_radice("r1", "/finta/spostata", quando=13.0)]
    try:
        elenco.registra(fatti)
        elenco.salva()
        elenco.registra(altri)
        elenco.salva()
        principale = archivio / "elenco" / "diario-00000000.ofd"
        riserva = archivio / "elenco" / "diario-00000000.riserva.ofd"
        k_diario = _hkdf(SEGRETO, b"diario")
        righe = _diario(principale.read_bytes(), k_diario)
        assert righe == _diario(riserva.read_bytes(), k_diario)
        assert [fatto for riga in righe for fatto in riga["fatti"]] == fatti + altri
        rotto = bytearray(principale.read_bytes())
        rotto[64 + 20] ^= 1
        dalla_principale = _diario(bytes(rotto), k_diario)
        assert dalla_principale[0] is None
        dalla_riserva = _diario(riserva.read_bytes(), k_diario)
        unite = [uno if uno is not None else altro
                 for uno, altro in zip(dalla_principale, dalla_riserva)]
        assert unite == righe
    finally:
        elenco.chiudi()


def test_le_chiavi_nascono_come_dice_il_testo():
    chiave = chiavi.Chiave(SEGRETO)
    numero = bytes(range(100, 116))
    k_contenuti = _hkdf(SEGRETO, b"contenuti")
    assert chiave.per_contenuto(numero) == _hkdf(k_contenuti, b"contenuto\x00" + numero)
    assert chiave.per("diario") == _hkdf(SEGRETO, b"diario")
    assert chiave.nome == _hkdf(SEGRETO, b"nome", 16).hex()
    senza = HKDF(algorithm=hashes.SHA256(), length=32, salt=None,
                 info=b"officina-sicuro\x00diario").derive(SEGRETO)
    assert senza == chiave.per("diario")


def test_la_porta_con_il_costo_lento_si_apre(tmp_path):
    chiavi.crea(tmp_path, PASSWORD, costo=chiavi.COSTO_LENTO)
    porta = json.loads((tmp_path / chiavi.FILE).read_text("utf-8"))["porte"][0]
    assert porta["n"] == chiavi.COSTO_LENTO
    assert len(_segreto(tmp_path, PASSWORD)) == 32


def _colonne(testo: str, tabella: str) -> list[str]:
    trovato = re.search(rf"(?:^  |\be ){tabella}\(([^)]*)\)", testo, re.MULTILINE)
    assert trovato, tabella
    return [parte.strip() for parte in trovato.group(1).replace("\n", " ").split(",")]


def test_il_testo_dice_le_tabelle_vere(tmp_path):
    db = sqlite3.connect(":memory:")
    db.executescript(registro._SCHEMA_SQL)
    for tabella in ("contenuti", "radici", "posti", "flussi", "note", "giri"):
        vere = [riga[1] for riga in db.execute(f"PRAGMA table_info({tabella})")]
        assert _colonne(leggimi.TESTO, tabella) == vere, tabella
    db.close()
    for stato in registro.STATI:
        assert stato in leggimi.TESTO
    assert "tipo è file, cartella o\n      collegamento" in leggimi.TESTO
    assert registro.TIPI == ("file", "cartella", "collegamento")


def test_il_testo_dice_i_numeri_e_i_nomi_veri():
    testo = leggimi.TESTO
    assert f'"n": {chiavi.COSTO}, "r": {chiavi.BLOCCO_SCRYPT}, "p": {chiavi.PARALLELO}' in testo
    assert f"con\n{chiavi.COSTO_LENTO} il doppio" in testo
    assert chiavi.COSTO_LENTO == 2 * chiavi.COSTO
    assert f'"tipo": "{chiavi.TIPO}", "versione": {chiavi.VERSIONE}' in testo
    assert chiavi.LUNGHEZZA == 32 and chiavi.SALE == 16 and chiavi.NONCE == 12
    assert chiavi.NOME == 16
    assert f"({formato.BLOCCO})" in testo and f"({formato.PEZZO})" in testo
    assert f"gruppo ({formato.GRUPPO})" in testo
    assert formato.MAGIA.decode() in testo and diario.MAGIA.decode() in testo
    assert formato.TESTA.size == 64 and diario.TESTA.size == 64
    assert formato.VERSIONE == 1 and diario.VERSIONE == 1
    assert formato.ETICHETTA == 16 and formato.IMPRONTA == 32
    assert formato.DATI == 0 and formato.META == 1
    for nome in (CARTELLA, chiavi.FILE, chiavi.RISERVA, chiavetta.SEGNO, PROGRAMMINO,
                 recupera.RAPPORTO, recupera.ARRIVO):
        assert nome in testo, nome
    assert f"{registro.CONTENUTI}/ab/<numero>{registro.ESTENSIONE}" in testo
    assert f"{registro.ELENCO}/fotografia-NNNNNNNN{registro.ESTENSIONE}" in testo
    assert f"diario-NNNNNNNN{registro.DIARIO}" in testo
    assert f"diario-NNNNNNNN.riserva{registro.DIARIO}" in testo
    assert f"PRAGMA user_version = {registro.SCHEMA}" in testo
    assert '"schema": 1' in testo and registro.SCHEMA == 1
    assert estrai.nome_della_radice("C:\\") == "Disco C"
    for vietato in '<>:"/\\|?*':
        assert estrai.nome_per_windows(f"a{vietato}b") == "a_b"
        assert vietato in testo
    assert estrai.nome_per_windows("a\x01b") == "a_b"
    assert estrai.nome_per_windows("fine. ") == "fine_"
    assert estrai.nome_per_windows("NUL.txt") == "_NUL.txt"
    assert estrai.nome_per_windows("lpt1") == "_lpt1"
    assert estrai.con_numero("foto.jpg", 2) == "foto (2).jpg"
    assert estrai.con_numero("viaggio.2020", 3, cartella=True) == "viaggio.2020 (3)"
    for fatto in ("radice", "contenuto", "stato", "posto", "sparito", "flusso", "nota",
                  "ricordo", "giro"):
        assert re.search(rf"^  {fatto}\b|\"{fatto}\"", testo, re.MULTILINE), fatto


def test_i_fatti_hanno_i_campi_del_testo():
    scritto = formato.Scritto(numero="ab" * 16, dimensione=3, blake2b="0" * 64,
                              sha256="1" * 64, peso=8192, testa=bytes(64))
    fatti = {
        "radice": registro.fatto_radice("r", "/x", quando=1.0),
        "contenuto": registro.fatto_contenuto(scritto, quando=1.0),
        "stato": registro.fatto_stato("ab" * 16, "rovinato", "finto", quando=1.0),
        "posto": registro.fatto_posto("r", "a", "file", "ab" * 16, {}, quando=1.0),
        "sparito": registro.fatto_sparito("k", quando=1.0),
        "flusso": registro.fatto_flusso("k", "nome", "ab" * 16),
        "nota": registro.fatto_nota("ab" * 16, quando=1.0),
    }
    for tipo, fatto in fatti.items():
        trovato = re.search(rf"^  {tipo}\s+\{{([^}}]*)\}}", leggimi.TESTO, re.MULTILINE)
        assert trovato, tipo
        campi = {parte.strip() for parte in trovato.group(1).replace("\n", " ").split(",")}
        assert campi == set(fatto) - {"fatto"}, tipo
        assert fatto["fatto"] == tipo
    assert fatti["contenuto"]["testa"] == bytes(64).hex()


def test_per_la_chiavetta_e_un_testo_per_windows():
    uscita = leggimi.per_la_chiavetta()
    assert uscita.startswith("\ufeff")
    assert "\r\n" in uscita
    assert uscita.count("\n") == uscita.count("\r\n") == uscita.count("\r")
    assert uscita[1:].replace("\r\n", "\n") == leggimi.TESTO
    uscita.encode("utf-8")
    assert all(len(riga) <= 80 for riga in leggimi.TESTO.splitlines())
    assert "\t" not in leggimi.TESTO
