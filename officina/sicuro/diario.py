from __future__ import annotations

import json
import os
import secrets
import struct
import zlib
from dataclasses import dataclass, field
from pathlib import Path

from officina.errori import ErroreOfficina
from officina.sicuro.chiavi import _aead
from officina.sicuro.disco import scrivi_tutto


MAGIA = b"OFDIARIO"
VERSIONE = 1
TESTA = struct.Struct(">8sHH16sQ16s8sI")
RIGA = struct.Struct(">II")
NONCE = 12
ETICHETTA = 16
MASSIMO = 16 * 1024 * 1024


class DiarioRovinato(ErroreOfficina):
    codice = "diario_rovinato"


def _prova(cifratore, numero: bytes, generazione: int) -> bytes:
    return cifratore.encrypt(numero[:NONCE], b"",
                             MAGIA + numero + generazione.to_bytes(8, "big"))


def _testa(cifratore, numero: bytes, generazione: int) -> bytes:
    corpo = TESTA.pack(MAGIA, VERSIONE, 0, numero, generazione,
                       _prova(cifratore, numero, generazione), bytes(8), 0)[:-4]
    return corpo + zlib.crc32(corpo).to_bytes(4, "big")


def _leggi_testa(dati: bytes, cifratore) -> tuple[bytes, int] | None:
    if len(dati) < TESTA.size or dati[:len(MAGIA)] != MAGIA:
        return None
    testa = dati[:TESTA.size]
    if zlib.crc32(testa[:-4]) != int.from_bytes(testa[-4:], "big"):
        return None
    _, versione, _, numero, generazione, prova, _, _ = TESTA.unpack(testa)
    if versione > VERSIONE:
        raise ErroreOfficina(
            "L'elenco dell'Archivio sicuro è stato scritto da una versione più "
            "nuova del programma. Aggiorna il programma.",
            codice="versione_piu_nuova")
    if versione != VERSIONE:
        return None
    if not secrets.compare_digest(prova, _prova(cifratore, numero, generazione)):
        return None
    return numero, generazione


def _accompagnamento(numero: bytes, generazione: int, posto: int) -> bytes:
    return (MAGIA + numero + generazione.to_bytes(8, "big")
            + posto.to_bytes(8, "big"))


@dataclass
class _Copia:
    righe: list[tuple[bytes, dict] | None] = field(default_factory=list)
    pulita: bool = False


def _leggi_copia(percorso: Path, cifratore, numero: bytes | None,
                 generazione: int) -> tuple[_Copia, bytes | None]:
    from cryptography.exceptions import InvalidTag

    copia = _Copia()
    try:
        dati = percorso.read_bytes()
    except OSError:
        return copia, None
    testa = _leggi_testa(dati, cifratore)
    if testa is None or testa[1] != generazione:
        return copia, None
    if numero is not None and testa[0] != numero:
        return copia, None
    numero = testa[0]
    dove = TESTA.size
    pulita = True
    while dove < len(dati):
        if len(dati) - dove < RIGA.size:
            pulita = False
            break
        lungo, crc = RIGA.unpack_from(dati, dove)
        corpo = dati[dove + RIGA.size:dove + RIGA.size + lungo]
        if (lungo < NONCE + ETICHETTA or lungo > MASSIMO
                or len(corpo) != lungo):
            pulita = False
            break
        intera = dati[dove:dove + RIGA.size + lungo]
        fatto = None
        if zlib.crc32(dati[dove:dove + 4] + corpo) == crc:
            try:
                chiaro = cifratore.decrypt(
                    corpo[:NONCE], corpo[NONCE:],
                    _accompagnamento(numero, generazione, len(copia.righe)))
                fatto = json.loads(chiaro.decode("utf-8", "surrogatepass"))
            except (InvalidTag, ValueError, UnicodeDecodeError):
                fatto = None
        if not isinstance(fatto, dict):
            copia.righe.append(None)
            pulita = False
        else:
            copia.righe.append((intera, fatto))
        dove += RIGA.size + lungo
    copia.pulita = pulita
    return copia, numero


class Diario:

    def __init__(self, principale: Path, riserva: Path, chiave,
                 generazione: int):
        self.principale = principale
        self.riserva = riserva
        self.generazione = generazione
        self._cifratore = _aead()(chiave.per("diario"))
        self.numero: bytes = b""
        self.righe = 0
        self._fine = TESTA.size
        self.buchi = 0
        self.riparato = False
        self.rotto = False

    @classmethod
    def nuovo(cls, principale: Path, riserva: Path, chiave,
              generazione: int) -> Diario:
        diario = cls(principale, riserva, chiave, generazione)
        if principale.exists() or riserva.exists():
            raise ErroreOfficina("Questo diario c'è già.", codice="diario_esiste")
        diario.numero = secrets.token_bytes(16)
        testa = _testa(diario._cifratore, diario.numero, generazione)
        principale.parent.mkdir(parents=True, exist_ok=True)
        scrivi_tutto(principale, testa)
        scrivi_tutto(riserva, testa)
        return diario

    @classmethod
    def apri(cls, principale: Path, riserva: Path, chiave,
             generazione: int) -> tuple[Diario, list[dict]]:
        diario = cls(principale, riserva, chiave, generazione)
        prima, numero = _leggi_copia(principale, diario._cifratore, None,
                                     generazione)
        seconda, altro = _leggi_copia(riserva, diario._cifratore, numero,
                                      generazione)
        numero = numero or altro
        if numero is None:
            raise DiarioRovinato(
                "Tutte e due le copie del diario dell'elenco sono rovinate.")
        diario.numero = numero
        righe: list[tuple[bytes, dict] | None] = []
        for posto in range(max(len(prima.righe), len(seconda.righe))):
            buona = None
            for copia in (prima, seconda):
                if posto < len(copia.righe) and copia.righe[posto] is not None:
                    buona = copia.righe[posto]
                    break
            righe.append(buona)
        while righe and righe[-1] is None:
            righe.pop()
        diario.buchi = sum(1 for riga in righe if riga is None)
        diario.righe = len(righe)
        fatti = [riga[1] for riga in righe if riga is not None]
        if diario.buchi:
            diario.rotto = True
            return diario, fatti
        tutto = (_testa(diario._cifratore, numero, generazione)
                 + b"".join(riga[0] for riga in righe))
        diario._fine = len(tutto)
        if not (prima.pulita and seconda.pulita
                and len(prima.righe) == len(seconda.righe) == len(righe)):
            diario.riparato = True
            try:
                scrivi_tutto(principale, tutto)
                scrivi_tutto(riserva, tutto)
            except OSError:
                diario.rotto = True
        return diario, fatti

    def _riga(self, fatto: dict) -> bytes:
        chiaro = json.dumps(fatto, ensure_ascii=False, sort_keys=True,
                            separators=(",", ":")).encode("utf-8", "surrogatepass")
        nonce = secrets.token_bytes(NONCE)
        corpo = nonce + self._cifratore.encrypt(
            nonce, chiaro, _accompagnamento(self.numero, self.generazione,
                                            self.righe))
        if len(corpo) > MASSIMO:
            raise ErroreOfficina("Una riga dell'elenco è troppo lunga.")
        self.righe += 1
        lungo = len(corpo).to_bytes(4, "big")
        return lungo + zlib.crc32(lungo + corpo).to_bytes(4, "big") + corpo

    def aggiungi(self, fatti: list[dict]) -> None:
        if self.rotto:
            raise DiarioRovinato("Il diario dell'elenco non si può allungare.")
        if not fatti:
            return
        righe_prima = self.righe
        try:
            pezzo = b"".join(self._riga(fatto) for fatto in fatti)
        except BaseException:
            self.righe = righe_prima
            raise
        try:
            for percorso in (self.principale, self.riserva):
                with open(percorso, "r+b") as file:
                    file.seek(self._fine)
                    file.write(pezzo)
                    file.truncate()
                    file.flush()
                    os.fsync(file.fileno())
        except OSError:
            self.rotto = True
            raise
        self._fine += len(pezzo)
