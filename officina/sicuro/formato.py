from __future__ import annotations

import hashlib
import io
import itertools
import json
import secrets
import struct
import zlib
from dataclasses import dataclass, field

import numpy as np

from officina.errori import ErroreOfficina
from officina.sicuro.chiavi import _aead


MAGIA = b"OFSICURO"
VERSIONE = 1
TESTA = struct.Struct(">8sHH16sIIHHQI8sI")
NUMERO = 16
ETICHETTA = 16
PEZZO = 4096
BLOCCO = 16 * PEZZO - ETICHETTA
GRUPPO = 20
PASSO_MINIMO = 4
PASSO_MASSIMO = 1024
TENTATIVI = 4096
IMPRONTA = 32
VUOTA = "0" * (2 * IMPRONTA)
DATI = 0
META = 1


class ContenutoRovinato(ErroreOfficina):
    codice = "contenuto_rovinato"


class FileCambiato(ErroreOfficina):
    codice = "file_cambiato"


def _su(numero: int, passo: int) -> int:
    return -(-numero // passo)


def _nonce(tipo: int, numero: int) -> bytes:
    return tipo.to_bytes(4, "big") + numero.to_bytes(8, "big")


@dataclass(frozen=True)
class Forma:
    numero: bytes
    dimensione: int
    meta: int
    blocco: int
    pezzo: int
    gruppo: int
    passo: int

    @classmethod
    def nuova(cls, numero: bytes, dimensione: int, chiaro_meta: int) -> Forma:
        per_blocco = (BLOCCO + ETICHETTA) // PEZZO
        blocchi = max(1, _su(dimensione, BLOCCO))
        pezzi = _su(dimensione + ETICHETTA * blocchi, PEZZO)
        passo = max(_su(pezzi, GRUPPO), min(PASSO_MINIMO, pezzi))
        if passo >= per_blocco:
            passo = _su(passo, per_blocco) * per_blocco
        passo = max(1, min(passo, PASSO_MASSIMO))
        meta = (_su(TESTA.size + ETICHETTA + 4 + chiaro_meta, PEZZO) * PEZZO
                - TESTA.size)
        forma = cls(numero, dimensione, meta, BLOCCO, PEZZO, GRUPPO, passo)
        if not forma.sensata():
            raise ErroreOfficina("Le misure del formato non stanno insieme.")
        return forma

    @classmethod
    def da_testa(cls, dati: bytes) -> Forma:
        if len(dati) != TESTA.size or dati[:len(MAGIA)] != MAGIA:
            raise ContenutoRovinato(
                "Questo non è un file dell'Archivio sicuro, o ha l'inizio "
                "rovinato.")
        if zlib.crc32(dati[:-4]) != int.from_bytes(dati[-4:], "big"):
            raise ContenutoRovinato("L'intestazione di questo file è rovinata.")
        (_, versione, _, numero, blocco, pezzo, gruppo, passo, dimensione,
         meta, _, _) = TESTA.unpack(dati)
        if versione > VERSIONE:
            raise ErroreOfficina(
                "Questo file dell'Archivio sicuro è stato scritto da una "
                "versione più nuova del programma. Aggiorna il programma.",
                codice="versione_piu_nuova")
        forma = cls(numero, dimensione, meta, blocco, pezzo, gruppo, passo)
        if versione != VERSIONE or not forma.sensata():
            raise ContenutoRovinato("L'intestazione di questo file non torna.")
        return forma

    def sensata(self) -> bool:
        return (self.pezzo in tuple(2 ** esponente for esponente in range(6, 21))
                and 0 < self.blocco <= 64 * 1024 * 1024
                and (self.blocco + ETICHETTA) % self.pezzo == 0
                and 2 <= self.gruppo <= 255
                and self.passo >= 1
                and self.gruppo * self.passo * self.pezzo <= 2 ** 28
                and self.meta >= ETICHETTA + 4
                and (TESTA.size + self.meta) % self.pezzo == 0
                and 0 <= self.dimensione < 2 ** 50
                and (self.fasce == 1 or self.passo % self.per_blocco == 0))

    def testa(self) -> bytes:
        corpo = TESTA.pack(MAGIA, VERSIONE, 0, self.numero, self.blocco,
                           self.pezzo, self.gruppo, self.passo, self.dimensione,
                           self.meta, bytes(8), 0)[:-4]
        return corpo + zlib.crc32(corpo).to_bytes(4, "big")

    @property
    def per_blocco(self) -> int:
        return (self.blocco + ETICHETTA) // self.pezzo

    @property
    def blocchi(self) -> int:
        return max(1, _su(self.dimensione, self.blocco))

    @property
    def cifrato(self) -> int:
        return self.dimensione + ETICHETTA * self.blocchi

    @property
    def pezzi(self) -> int:
        return _su(self.cifrato, self.pezzo)

    @property
    def fascia(self) -> int:
        return self.gruppo * self.passo

    @property
    def fasce(self) -> int:
        return _su(self.pezzi, self.fascia)

    def pezzi_in(self, fascia: int) -> int:
        return min(self.fascia, self.pezzi - fascia * self.fascia)

    def riserve_in(self, fascia: int) -> int:
        return min(self.passo, self.pezzi_in(fascia))

    @property
    def riserve(self) -> int:
        return (self.fasce - 1) * self.passo + self.riserve_in(self.fasce - 1)

    @property
    def inizio(self) -> int:
        return TESTA.size + self.meta

    @property
    def peso(self) -> int:
        return 2 * self.inizio + (self.pezzi + self.riserve) * self.pezzo

    def lunghezza(self, blocco: int) -> int:
        if blocco < self.blocchi - 1:
            return self.blocco
        return self.dimensione - (self.blocchi - 1) * self.blocco

    def dove_fascia(self, fascia: int) -> int:
        return self.inizio + fascia * (self.fascia + self.passo) * self.pezzo

    def dove_blocco(self, blocco: int) -> int:
        logico = blocco * self.per_blocco * self.pezzo
        fascia = logico // (self.fascia * self.pezzo)
        return (self.dove_fascia(fascia) + logico
                - fascia * self.fascia * self.pezzo)

    def fascia_di(self, blocco: int) -> int:
        return blocco * self.per_blocco // self.fascia

    def blocchi_in(self, fascia: int) -> range:
        if self.fasce == 1:
            return range(self.blocchi)
        quanti = self.fascia // self.per_blocco
        return range(fascia * quanti, min(self.blocchi, (fascia + 1) * quanti))


def _meta_in_byte(impronte: dict, dati: dict) -> bytes:
    return json.dumps({"impronte": impronte, "dati": dati}, ensure_ascii=False,
                      sort_keys=True, separators=(",", ":")).encode("utf-8", "surrogatepass")


def _imbottisci(corpo: bytes, spazio: int) -> bytes:
    if len(corpo) + 4 > spazio:
        raise ErroreOfficina("Le informazioni del file non ci stanno.")
    return len(corpo).to_bytes(4, "big") + corpo + bytes(spazio - 4 - len(corpo))


def _sbottisci(chiaro: bytes) -> dict:
    quanto = int.from_bytes(chiaro[:4], "big")
    meta = json.loads(chiaro[4:4 + quanto].decode("utf-8", "surrogatepass"))
    if (not isinstance(meta, dict) or not isinstance(meta.get("impronte"), dict)
            or not isinstance(meta.get("dati"), dict)):
        raise ValueError("meta senza le sue parti")
    return meta


@dataclass(frozen=True)
class Scritto:
    numero: str
    dimensione: int
    blake2b: str
    sha256: str
    peso: int
    testa: bytes


class Scrittore:

    def __init__(self, fuori, chiave, dimensione: int, dati: dict,
                 numero: bytes | None = None):
        self._fuori = fuori
        self._dati = dict(dati)
        numero = secrets.token_bytes(NUMERO) if numero is None else bytes(numero)
        if len(numero) != NUMERO:
            raise ValueError("il numero di un contenuto è lungo 16 byte")
        prova = _meta_in_byte({"blake2b": VUOTA, "sha256": VUOTA}, self._dati)
        self.forma = Forma.nuova(numero, dimensione, len(prova))
        self._cifratore = _aead()(chiave.per_contenuto(numero))
        self._testa = self.forma.testa()
        self._accompagnamento = self._testa[:-4]
        if fuori.tell() != 0:
            raise ValueError("un contenuto si scrive dall'inizio del file")
        fuori.write(self._testa)
        fuori.write(bytes(self.forma.meta))
        self._attesa = bytearray()
        self._fatti = 0
        self._riga = bytearray()
        self._parita = np.zeros(self.forma.passo * self.forma.pezzo,
                                dtype=np.uint8)
        self._righe = 0
        self._ricevuti = 0
        self._blake = hashlib.blake2b(digest_size=IMPRONTA)
        self._sha = hashlib.sha256()

    def write(self, dati) -> int:
        vista = memoryview(dati).cast("B")
        quanti = len(vista)
        self._ricevuti += quanti
        if self._ricevuti > self.forma.dimensione:
            raise FileCambiato("Il file è cresciuto mentre lo copiavo.")
        self._blake.update(vista)
        self._sha.update(vista)
        self._attesa += vista
        blocco = self.forma.blocco
        fatto = 0
        with memoryview(self._attesa) as attesa:
            while (len(attesa) - fatto >= blocco
                   and self._fatti < self.forma.blocchi - 1):
                self._cifra(attesa[fatto:fatto + blocco])
                fatto += blocco
        del self._attesa[:fatto]
        return quanti

    def _cifra(self, chiaro: bytes) -> None:
        self._metti(self._cifratore.encrypt(_nonce(DATI, self._fatti), chiaro,
                                            self._accompagnamento))
        self._fatti += 1

    def _metti(self, cifrato: bytes) -> None:
        self._riga += cifrato
        larga = len(self._parita)
        while len(self._riga) >= larga:
            self._chiudi_riga(bytes(self._riga[:larga]))
            del self._riga[:larga]

    def _chiudi_riga(self, riga: bytes) -> None:
        self._fuori.write(riga)
        parte = self._parita[:len(riga)]
        np.bitwise_xor(parte, np.frombuffer(riga, dtype=np.uint8), out=parte)
        self._righe += 1
        if self._righe == self.forma.gruppo:
            self._chiudi_fascia(self.forma.passo)

    def _chiudi_fascia(self, riserve: int) -> None:
        self._fuori.write(self._parita[:riserve * self.forma.pezzo].tobytes())
        self._parita[:] = 0
        self._righe = 0

    def finisci(self) -> Scritto:
        forma = self.forma
        if self._ricevuti != forma.dimensione:
            raise FileCambiato("Il file è diventato più corto mentre lo "
                               "copiavo.")
        self._cifra(bytes(self._attesa))
        self._attesa.clear()
        if self._fatti != forma.blocchi:
            raise ErroreOfficina("I pezzi cifrati non tornano col file.")
        if self._riga:
            resto = len(self._riga) % forma.pezzo
            if resto:
                self._riga += bytes(forma.pezzo - resto)
            prima = self._righe
            ultimi = len(self._riga) // forma.pezzo
            self._chiudi_riga(bytes(self._riga))
            self._riga.clear()
            if self._righe:
                self._chiudi_fascia(min(forma.passo,
                                        prima * forma.passo + ultimi))
        elif self._righe:
            self._chiudi_fascia(forma.passo)
        impronte = {"blake2b": self._blake.hexdigest(),
                    "sha256": self._sha.hexdigest()}
        meta = self._cifratore.encrypt(
            _nonce(META, 0),
            _imbottisci(_meta_in_byte(impronte, self._dati),
                        forma.meta - ETICHETTA),
            self._accompagnamento)
        self._fuori.write(meta)
        self._fuori.write(self._testa)
        fine = self._fuori.tell()
        if fine != forma.peso:
            raise ErroreOfficina("Il file cifrato non ha la lunghezza giusta.")
        self._fuori.seek(TESTA.size)
        self._fuori.write(meta)
        self._fuori.seek(fine)
        return Scritto(numero=forma.numero.hex(), dimensione=forma.dimensione,
                       blake2b=impronte["blake2b"], sha256=impronte["sha256"],
                       peso=forma.peso, testa=self._testa)


def peso_previsto(dimensione: int, meta: int = 4096) -> int:
    return Forma.nuova(bytes(NUMERO), dimensione, meta).peso


def nuovo_numero() -> bytes:
    return secrets.token_bytes(NUMERO)


def scrivi_byte(fuori, chiave, dati: bytes, informazioni: dict,
                numero: bytes | None = None) -> Scritto:
    scrittore = Scrittore(fuori, chiave, len(dati), informazioni, numero)
    scrittore.write(dati)
    return scrittore.finisci()


def _leggi_esatto(file, dove: int, quanti: int) -> bytes | None:
    try:
        file.seek(dove)
        dati = file.read(quanti)
    except OSError:
        return None
    return dati if len(dati) == quanti else None


def _leggi_pezzi(file, dove: int, quanti: int,
                 pezzo: int) -> tuple[bytearray, set[int]]:
    tutto = _leggi_esatto(file, dove, quanti * pezzo)
    if tutto is not None:
        return bytearray(tutto), set()
    dati = bytearray(quanti * pezzo)
    cattivi = set()
    for numero in range(quanti):
        letto = _leggi_esatto(file, dove + numero * pezzo, pezzo)
        if letto is None:
            cattivi.add(numero)
        else:
            dati[numero * pezzo:(numero + 1) * pezzo] = letto
    return dati, cattivi


@dataclass
class _Fascia:
    numero: int
    dati: bytearray
    cattivi: set[int]
    parita: bytearray
    parita_cattive: set[int]


@dataclass
class _Esito:
    chiari: dict[int, bytes]
    rovinati: list[int]
    persi: list[int]
    parita_giusta: bool


class Contenuto:

    def __init__(self, file, chiave, numero: bytes | None = None,
                 testa: bytes | None = None):
        self._file = file
        self._chiave = chiave
        self.peso_sul_disco = file.seek(0, io.SEEK_END)
        lette, candidate = self._trova_le_forme(testa, numero)
        scelta = None
        for forma in candidate:
            self._usa(forma)
            self.meta, self.meta_cifrata, self.meta_rovinata = (
                self._trova_la_meta())
            if self.meta is not None:
                scelta = forma
                break
        if scelta is None:
            dall_elenco = Forma.da_testa(testa) if testa is not None else None
            scelta = dall_elenco if dall_elenco in candidate else candidate[0]
            self._usa(scelta)
            self.meta, self.meta_cifrata, self.meta_rovinata = None, None, True
        self.testa_rovinata = not (lette[0] is not None
                                   and lette[0] == lette[1] == scelta)
        self.tagliato = self.peso_sul_disco != self.forma.peso
        self._ultimo: tuple[int, bytes] = (-1, b"")
        self._riparati: dict[int, bytes] = {}
        self._fasce_provate: set[int] = set()
        self.da_riparare = (self.testa_rovinata or self.meta_rovinata
                            or self.tagliato)

    @property
    def dimensione(self) -> int:
        return self.forma.dimensione

    @property
    def impronte(self) -> dict | None:
        return None if self.meta is None else self.meta["impronte"]

    @property
    def dati(self) -> dict | None:
        return None if self.meta is None else self.meta["dati"]

    def riscrivibile(self) -> bool:
        if self.meta is None or self.meta_cifrata is None:
            return False
        prova = _meta_in_byte({"blake2b": VUOTA, "sha256": VUOTA}, self.dati)
        try:
            forma = Forma.nuova(self.forma.numero, self.forma.dimensione, len(prova))
            chiaro = _imbottisci(_meta_in_byte(self.impronte, self.dati),
                                 forma.meta - ETICHETTA)
        except (ErroreOfficina, TypeError, ValueError):
            return False
        if forma != self.forma:
            return False
        return self._cifratore.encrypt(_nonce(META, 0), chiaro,
                                       self._accompagnamento) == self.meta_cifrata

    def _usa(self, forma: Forma) -> None:
        self.forma = forma
        self._cifratore = _aead()(self._chiave.per_contenuto(forma.numero))
        self._accompagnamento = forma.testa()[:-4]

    def _trova_le_forme(self, testa: bytes | None, numero: bytes | None
                        ) -> tuple[list[Forma | None], list[Forma]]:
        lette: list[Forma | None] = []
        for dove in (0, self.peso_sul_disco - TESTA.size):
            letta = _leggi_esatto(self._file, dove, TESTA.size) if dove >= 0 else None
            try:
                lette.append(Forma.da_testa(letta) if letta else None)
            except ContenutoRovinato:
                lette.append(None)
        candidate: list[Forma] = []
        dall_elenco = Forma.da_testa(testa) if testa is not None else None
        for forma in (*lette, dall_elenco):
            if forma is not None and forma not in candidate:
                candidate.append(forma)
        if numero is not None:
            candidate = [forma for forma in candidate
                         if forma.numero == bytes(numero)]
            if not candidate and any(forma is not None
                                     for forma in (*lette, dall_elenco)):
                raise ContenutoRovinato(
                    "Questo file cifrato è un altro contenuto.")
        if not candidate:
            raise ContenutoRovinato(
                "Questo file dell'Archivio sicuro ha rovinato l'inizio e la "
                "fine, dove dice com'è fatto.")
        return lette, candidate

    def _apri_meta(self, cifrata: bytes | None) -> dict | None:
        from cryptography.exceptions import InvalidTag

        if cifrata is None:
            return None
        try:
            return _sbottisci(self._cifratore.decrypt(
                _nonce(META, 0), cifrata, self._accompagnamento))
        except (InvalidTag, ValueError, UnicodeDecodeError):
            return None

    def _trova_la_meta(self) -> tuple[dict | None, bytes | None, bool]:
        forma = self.forma
        prese = []
        for dove in (TESTA.size, forma.peso - forma.inizio):
            cifrata = _leggi_esatto(self._file, dove, forma.meta)
            meta = self._apri_meta(cifrata)
            prese.append((meta, cifrata if meta is not None else None))
        buone = [presa for presa in prese if presa[0] is not None]
        if not buone:
            return None, None, True
        return buone[0][0], buone[0][1], len(buone) < 2

    def _apri(self, blocco: int, cifrato: bytes | None) -> bytes | None:
        from cryptography.exceptions import InvalidTag

        if cifrato is None:
            return None
        try:
            return self._cifratore.decrypt(_nonce(DATI, blocco), cifrato,
                                           self._accompagnamento)
        except InvalidTag:
            return None

    def blocco(self, numero: int) -> bytes:
        if self._ultimo[0] == numero:
            return self._ultimo[1]
        if not 0 <= numero < self.forma.blocchi:
            raise IndexError(numero)
        chiaro = self._riparati.get(numero)
        if chiaro is None:
            chiaro = self._apri(numero, _leggi_esatto(
                self._file, self.forma.dove_blocco(numero),
                self.forma.lunghezza(numero) + ETICHETTA))
        if chiaro is None:
            self.da_riparare = True
            fascia = self.forma.fascia_di(numero)
            if fascia not in self._fasce_provate:
                self._fasce_provate.add(fascia)
                esito = self._sistema(self._leggi_fascia(fascia))
                for rotto in esito.rovinati:
                    if rotto in esito.chiari:
                        self._riparati[rotto] = esito.chiari[rotto]
            chiaro = self._riparati.get(numero)
            if chiaro is None:
                raise ContenutoRovinato(
                    f"Un pezzo di questo file (il numero {numero + 1} di "
                    f"{self.forma.blocchi}) è rovinato e i pezzetti di "
                    "riserva non bastano a ripararlo.",
                    codice="pezzo_perso")
        self._ultimo = (numero, chiaro)
        return chiaro

    def pezzi(self):
        for numero in range(self.forma.blocchi):
            yield self.blocco(numero)

    def tutto(self) -> bytes:
        return b"".join(self.pezzi())

    def apri(self) -> io.BufferedReader:
        return io.BufferedReader(Lettore(self), buffer_size=self.forma.blocco)

    def _leggi_fascia(self, numero: int) -> _Fascia:
        forma = self.forma
        dove = forma.dove_fascia(numero)
        pezzi = forma.pezzi_in(numero)
        dati, cattivi = _leggi_pezzi(self._file, dove, pezzi, forma.pezzo)
        parita, parita_cattive = _leggi_pezzi(
            self._file, dove + pezzi * forma.pezzo, forma.riserve_in(numero),
            forma.pezzo)
        return _Fascia(numero, dati, cattivi, parita, parita_cattive)

    def _sistema(self, fascia: _Fascia) -> _Esito:
        return _Sistemazione(self.forma, self._apri, fascia).fai()


class _Sistemazione:

    def __init__(self, forma: Forma, apri, fascia: _Fascia):
        self.forma = forma
        self.apri = apri
        self.fascia = fascia
        gruppo, passo, pezzo = forma.gruppo, forma.passo, forma.pezzo
        self.quanti = len(fascia.dati) // pezzo
        if len(fascia.dati) == gruppo * passo * pezzo:
            self.piatta = np.frombuffer(fascia.dati, dtype=np.uint8)
        else:
            self.piatta = np.zeros(gruppo * passo * pezzo, dtype=np.uint8)
            self.piatta[:len(fascia.dati)] = np.frombuffer(fascia.dati,
                                                           dtype=np.uint8)
        self.piena = self.piatta.reshape(gruppo, passo, pezzo)
        self.riserve = len(fascia.parita) // pezzo
        self.parita = np.zeros((passo, pezzo), dtype=np.uint8)
        self.parita.reshape(-1)[:len(fascia.parita)] = np.frombuffer(
            fascia.parita, dtype=np.uint8)
        self.primo = fascia.numero * forma.fascia
        self.scorta = TENTATIVI * 4
        fine = max(0, forma.cifrato - self.primo * pezzo)
        coda = self.piatta[fine:len(fascia.dati)]
        self.sporca = bool(coda.any())
        coda[:] = 0

    def _pezzi_del_blocco(self, blocco: int) -> range:
        forma = self.forma
        inizio = blocco * forma.per_blocco - self.primo
        return range(inizio, inizio + _su(forma.lunghezza(blocco) + ETICHETTA,
                                          forma.pezzo))

    def _cifrato(self, blocco: int, cambi: dict[int, np.ndarray]) -> bytes:
        forma = self.forma
        pezzi = self._pezzi_del_blocco(blocco)
        lungo = forma.lunghezza(blocco) + ETICHETTA
        da = pezzi.start * forma.pezzo
        if not cambi:
            return self.piatta[da:da + lungo].tobytes()
        prova = self.piatta[da:da + len(pezzi) * forma.pezzo].copy()
        for numero, nuovo in cambi.items():
            dentro = (numero - pezzi.start) * forma.pezzo
            prova[dentro:dentro + forma.pezzo] = nuovo
        return prova[:lungo].tobytes()

    def _somma(self, colonna: int) -> np.ndarray:
        return np.bitwise_xor.reduce(self.piena[:, colonna, :], axis=0)

    def _storta(self, colonna: int) -> bool:
        if colonna >= self.riserve:
            return False
        if any(riga * self.forma.passo + colonna in self.fascia.cattivi
               for riga in range(self.forma.gruppo)):
            return True
        return bool(np.any(self._somma(colonna) != self.parita[colonna]))

    def _usabile(self, colonna: int) -> bool:
        return (colonna < self.riserve
                and colonna not in self.fascia.parita_cattive)

    def _rifatto(self, numero: int) -> np.ndarray:
        riga, colonna = divmod(numero, self.forma.passo)
        return (self.parita[colonna] ^ self._somma(colonna)
                ^ self.piena[riga, colonna])

    def _colonne_storte(self) -> set[int]:
        somma = np.bitwise_xor.reduce(self.piena, axis=0)
        diverse = np.any(somma != self.parita, axis=1)
        storte = {colonna for colonna in np.flatnonzero(diverse).tolist()
                  if colonna < self.riserve}
        storte |= {numero % self.forma.passo for numero in self.fascia.cattivi
                   if numero % self.forma.passo < self.riserve}
        return storte

    def _prova_a_rifare(self, blocco: int, storte: set[int]) -> bytes | None:
        passo = self.forma.passo
        pezzi = list(self._pezzi_del_blocco(blocco))
        per_colonna: dict[int, list[int]] = {}
        for numero in pezzi:
            colonna = numero % passo
            if colonna in storte and self._usabile(colonna):
                per_colonna.setdefault(colonna, []).append(numero)
        scelte = []
        for numeri in per_colonna.values():
            illeggibili = [n for n in numeri if n in self.fascia.cattivi]
            scelte.append(illeggibili if len(illeggibili) == 1 else numeri)
        illeggibili = {n for n in pezzi if n in self.fascia.cattivi}
        provate: set[frozenset[int]] = set()
        rifatti: dict[int, np.ndarray] = {}
        for buco in _buchi(pezzi, per_colonna, illeggibili, passo):
            chiaro = self._prova_scelta(blocco, buco, provate, rifatti)
            if chiaro is not None:
                return chiaro
        quanti = max(0, min(TENTATIVI, self.scorta))
        for scelta in itertools.islice(_dalla_piu_piena(scelte), quanti):
            self.scorta -= 1
            chiaro = self._prova_scelta(blocco, scelta, provate, rifatti)
            if chiaro is not None:
                return chiaro
        return None

    def _prova_scelta(self, blocco: int, scelta, provate: set[frozenset[int]],
                      rifatti: dict[int, np.ndarray]) -> bytes | None:
        scelta = frozenset(scelta)
        if scelta in provate:
            return None
        provate.add(scelta)
        for numero in scelta:
            if numero not in rifatti:
                rifatti[numero] = self._rifatto(numero)
        cambi = {numero: rifatti[numero] for numero in scelta}
        chiaro = self.apri(blocco, self._cifrato(blocco, cambi))
        if chiaro is not None:
            for numero, nuovo in cambi.items():
                self.piatta[numero * self.forma.pezzo:
                            (numero + 1) * self.forma.pezzo] = nuovo
                self.fascia.cattivi.discard(numero)
        return chiaro

    def fai(self) -> _Esito:
        chiari: dict[int, bytes] = {}
        rotti = []
        blocchi = self.forma.blocchi_in(self.fascia.numero)
        for blocco in blocchi:
            chiaro = self.apri(blocco, self._cifrato(blocco, {}))
            if chiaro is None:
                rotti.append(blocco)
            else:
                chiari[blocco] = chiaro
        rovinati = list(rotti)
        storte = self._colonne_storte()
        cambi = 0
        cambiata: dict[int, int] = {}
        provato: dict[int, int] = {}
        andato = True
        while rotti and andato:
            andato = False
            for blocco in list(rotti):
                colonne = {numero % self.forma.passo
                           for numero in self._pezzi_del_blocco(blocco)}
                if blocco in provato and all(
                        cambiata.get(colonna, -1) <= provato[blocco]
                        for colonna in colonne):
                    continue
                chiaro = self._prova_a_rifare(blocco, storte)
                if chiaro is None:
                    provato[blocco] = cambi
                    continue
                cambi += 1
                for colonna in colonne:
                    cambiata[colonna] = cambi
                chiari[blocco] = chiaro
                rotti.remove(blocco)
                andato = True
                storte = {colonna for colonna in storte
                          if colonna not in colonne or self._storta(colonna)}
        return _Esito(chiari=chiari, rovinati=rovinati, persi=rotti,
                      parita_giusta=not storte and not self.sporca
                      and not self.fascia.parita_cattive)

    def pulita(self) -> tuple[bytes, bytes]:
        forma = self.forma
        parita = np.bitwise_xor.reduce(self.piena, axis=0).reshape(-1)
        return (self.piatta[:self.quanti * forma.pezzo].tobytes(),
                parita[:self.riserve * forma.pezzo].tobytes())


def _buchi(pezzi: list[int], per_colonna: dict[int, list[int]],
           illeggibili: set[int], passo: int):
    ammessi = {numero for numeri in per_colonna.values() for numero in numeri}
    for lungo in range(min(len(pezzi), passo), 0, -1):
        for inizio in range(len(pezzi) - lungo + 1):
            buco = set(pezzi[inizio:inizio + lungo]) | illeggibili
            colonne = [numero % passo for numero in buco]
            if buco <= ammessi and len(set(colonne)) == len(colonne):
                yield buco


def _dalla_piu_piena(scelte: list[list[int]]):
    colonne = range(len(scelte))
    for lasciate in range(len(scelte)):
        for via in itertools.combinations(colonne, lasciate):
            restano = [scelte[colonna] for colonna in colonne
                       if colonna not in via]
            yield from itertools.product(*restano)


class Lettore(io.RawIOBase):

    def __init__(self, contenuto: Contenuto):
        super().__init__()
        self._contenuto = contenuto
        self._dove = 0

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self._dove

    def seek(self, dove: int, da: int = io.SEEK_SET) -> int:
        if da == io.SEEK_CUR:
            dove += self._dove
        elif da == io.SEEK_END:
            dove += self._contenuto.dimensione
        elif da != io.SEEK_SET:
            raise ValueError(f"da dove? {da}")
        if dove < 0:
            raise ValueError("posizione prima dell'inizio")
        self._dove = dove
        return dove

    def readinto(self, spazio) -> int:
        forma = self._contenuto.forma
        if self._dove >= forma.dimensione or not len(spazio):
            return 0
        numero = self._dove // forma.blocco
        chiaro = self._contenuto.blocco(numero)
        da = self._dove - numero * forma.blocco
        quanti = min(len(spazio), len(chiaro) - da)
        spazio[:quanti] = chiaro[da:da + quanti]
        self._dove += quanti
        return quanti


@dataclass
class Controllo:
    buono: bool
    leggibile: bool
    blocchi_rovinati: list[int] = field(default_factory=list)
    blocchi_persi: list[int] = field(default_factory=list)
    riserve_rovinate: bool = False
    testa_rovinata: bool = False
    meta_rovinata: bool = False
    tagliato: bool = False
    impronte_tornano: bool = False

    @property
    def riparabile(self) -> bool:
        return self.leggibile and not self.buono


def _confronta(impronte: dict | None, blake: str, sha: str) -> bool:
    return (impronte is not None and impronte.get("blake2b") == blake
            and impronte.get("sha256") == sha)


class Rilettura:

    def __init__(self, file, chiave, numero: bytes | None = None,
                 testa: bytes | None = None, impronte: dict | None = None):
        self.controllo: Controllo | None = None
        self._impronte = impronte
        try:
            self._contenuto: Contenuto | None = Contenuto(file, chiave, numero=numero,
                                                          testa=testa)
        except ContenutoRovinato:
            self._contenuto = None
            self.controllo = Controllo(buono=False, leggibile=False,
                                       testa_rovinata=True)

    def __iter__(self):
        contenuto, self._contenuto = self._contenuto, None
        if contenuto is None:
            return
        impronte = self._impronte
        attese = impronte or contenuto.impronte
        blake = hashlib.blake2b(digest_size=IMPRONTA)
        sha = hashlib.sha256()
        rovinati: list[int] = []
        persi: list[int] = []
        riserve_rovinate = False
        for numero_fascia in range(contenuto.forma.fasce):
            esito = contenuto._sistema(contenuto._leggi_fascia(numero_fascia))
            rovinati += esito.rovinati
            persi += esito.persi
            riserve_rovinate |= not esito.parita_giusta
            if not persi:
                for blocco in contenuto.forma.blocchi_in(numero_fascia):
                    pezzo = esito.chiari[blocco]
                    blake.update(pezzo)
                    sha.update(pezzo)
                    yield pezzo
        tornano = not persi and _confronta(attese, blake.hexdigest(),
                                           sha.hexdigest())
        if impronte is not None and contenuto.impronte is not None:
            tornano = tornano and _confronta(contenuto.impronte, impronte["blake2b"],
                                             impronte["sha256"])
        buono = (tornano and not rovinati and not riserve_rovinate
                 and not contenuto.testa_rovinata and not contenuto.meta_rovinata
                 and not contenuto.tagliato)
        self.controllo = Controllo(
            buono=buono, leggibile=tornano, blocchi_rovinati=rovinati,
            blocchi_persi=persi, riserve_rovinate=riserve_rovinate,
            testa_rovinata=contenuto.testa_rovinata,
            meta_rovinata=contenuto.meta_rovinata,
            tagliato=contenuto.tagliato, impronte_tornano=tornano)


def controlla(file, chiave, numero: bytes | None = None,
              testa: bytes | None = None,
              impronte: dict | None = None, ogni_pezzo=None) -> Controllo:
    rilettura = Rilettura(file, chiave, numero=numero, testa=testa,
                          impronte=impronte)
    for pezzo in rilettura:
        if ogni_pezzo is not None:
            ogni_pezzo(pezzo)
    return rilettura.controllo


def ripara(file, fuori, chiave, numero: bytes | None = None,
           testa: bytes | None = None, impronte: dict | None = None,
           dati: dict | None = None) -> Controllo:
    contenuto = Contenuto(file, chiave, numero=numero, testa=testa)
    forma = contenuto.forma
    if (impronte is not None and contenuto.impronte is not None
            and not _confronta(contenuto.impronte, impronte.get("blake2b"),
                               impronte.get("sha256"))):
        raise ContenutoRovinato(
            "Le impronte scritte nel file e quelle dell'elenco non sono "
            "uguali: non riparo niente finché non si capisce perché.",
            codice="impronte_diverse")
    attese = contenuto.impronte or impronte
    if attese is None:
        raise ContenutoRovinato(
            "Non so più quali erano le impronte di questo file, quindi non "
            "posso essere sicuro di ripararlo bene.", codice="senza_impronte")
    meta_cifrata = contenuto.meta_cifrata
    if meta_cifrata is None:
        if dati is None:
            raise ContenutoRovinato(
                "Le informazioni dentro il file sono rovinate in tutte e due "
                "le copie.", codice="senza_informazioni")
        meta_cifrata = contenuto._cifratore.encrypt(
            _nonce(META, 0),
            _imbottisci(_meta_in_byte(attese, dati), forma.meta - ETICHETTA),
            contenuto._accompagnamento)
    if fuori.tell() != 0:
        raise ValueError("un contenuto si ripara dall'inizio del file")
    testa_buona = forma.testa()
    fuori.write(testa_buona)
    fuori.write(meta_cifrata)
    blake = hashlib.blake2b(digest_size=IMPRONTA)
    sha = hashlib.sha256()
    for numero_fascia in range(forma.fasce):
        sistemazione = _Sistemazione(forma, contenuto._apri,
                                     contenuto._leggi_fascia(numero_fascia))
        esito = sistemazione.fai()
        if esito.persi:
            raise ContenutoRovinato(
                f"{len(esito.persi)} pezzi di questo file sono rovinati e i "
                "pezzetti di riserva non bastano.", codice="pezzo_perso")
        for blocco in forma.blocchi_in(numero_fascia):
            blake.update(esito.chiari[blocco])
            sha.update(esito.chiari[blocco])
        dati_fascia, parita = sistemazione.pulita()
        fuori.write(dati_fascia)
        fuori.write(parita)
    if not _confronta(attese, blake.hexdigest(), sha.hexdigest()):
        raise ContenutoRovinato(
            "Dopo la riparazione le impronte non tornano: la riparazione non "
            "si usa.", codice="riparazione_sbagliata")
    fuori.write(meta_cifrata)
    fuori.write(testa_buona)
    if fuori.tell() != forma.peso:
        raise ContenutoRovinato("Il file riparato non ha la lunghezza giusta.")
    fuori.flush()
    controllo = controlla(fuori, chiave, numero=forma.numero, impronte=attese)
    if not controllo.buono:
        raise ContenutoRovinato(
            "Il file riparato, riletto, non è perfetto: la riparazione non si "
            "usa.", codice="riparazione_sbagliata")
    return controllo

