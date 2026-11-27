from __future__ import annotations

import base64
import http.client
import json
import secrets
import shutil
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from officina.errori import ErroreOfficina
from officina.telefono import cavo

PRENDI = "/api/telefono/cavo/prendi"
RISPONDI = "/api/telefono/cavo/rispondi"
FILE = "/api/telefono/cavo/file/"
ATTESA_DEL_PORTATILE = 90.0
ATTESA_DI_UN_COMANDO = 120.0
ATTESA_DELLA_DOMANDA = 20.0
ATTESA_DEL_SALUTO = 15.0
VELOCITA_MINIMA = 1024 * 1024
TENTATIVI = 5
AVANZI = "officina-cavo-"
MANI = 2

PORTATILE_ZITTO = ("Il portatile non risponde. Tieni aperto il programma sul portatile, "
                   "collegato al fisso, con l'iPhone attaccato al portatile, e riprova.")
PORTATILE_PERSO = ("Il portatile ha smesso di rispondere a metà copia. Il Visore resta "
                   "chiuso finché non finisco: ricollega il portatile, riattacca l'iPhone "
                   "e riparti. Copio solo quello che manca.")
NON_CAPITO = "Il portatile ha ricevuto un comando che non conosce: aggiorna il programma."


@dataclass
class _Attesa:
    evento: threading.Event
    esito: dict | None = None
    dati: bytes | None = None


class Banco:

    def __init__(self) -> None:
        self._condizione = threading.Condition()
        self._coda: list[dict] = []
        self._attese: dict[str, _Attesa] = {}
        self._file: dict[str, Path] = {}
        self.aperto = False
        self.perso = False

    def apri(self) -> None:
        with self._condizione:
            self._coda.clear()
            self._attese.clear()
            self._file.clear()
            self.aperto = True
            self.perso = False
            self._condizione.notify_all()

    def chiudi(self) -> None:
        with self._condizione:
            self.aperto = False
            self._coda.clear()
            self._file.clear()
            for attesa in self._attese.values():
                attesa.evento.set()
            self._attese.clear()
            self._condizione.notify_all()

    def chiedi(self, op: str, attesa: float, **argomenti) -> tuple[dict, bytes | None]:
        numero = secrets.token_hex(8)
        aspetto = _Attesa(threading.Event())
        with self._condizione:
            if not self.aperto or self.perso:
                raise ErroreOfficina(PORTATILE_PERSO, codice="cavo_portatile_perso")
            self._attese[numero] = aspetto
            self._coda.append({"id": numero, "op": op, **argomenti})
            self._condizione.notify_all()
        arrivato = aspetto.evento.wait(attesa)
        with self._condizione:
            self._attese.pop(numero, None)
            if not arrivato or aspetto.esito is None:
                self._coda = [c for c in self._coda if c["id"] != numero]
                self.perso = True
                raise ErroreOfficina(PORTATILE_PERSO, codice="cavo_portatile_perso")
        esito = aspetto.esito
        if "errore" in esito:
            codice = str(esito.get("codice") or "cavo_staccato")
            if codice == "cavo_staccato":
                raise cavo.GuastoDelCavo(op)
            raise ErroreOfficina(str(esito["errore"]), codice=codice)
        return esito, aspetto.dati

    def prossimo(self, attesa: float | None = None) -> dict:
        fine = time.monotonic() + (attesa or ATTESA_DELLA_DOMANDA)
        with self._condizione:
            while self.aperto and not self._coda:
                resta = fine - time.monotonic()
                if resta <= 0:
                    return {"op": "niente"}
                self._condizione.wait(resta)
            if not self.aperto:
                return {"op": "fine"}
            return self._coda.pop(0)

    def rispondi(self, numero: str, esito: dict, dati: bytes | None) -> bool:
        with self._condizione:
            aspetto = self._attese.get(numero)
            if aspetto is None:
                return False
            aspetto.esito = esito if isinstance(esito, dict) else {"errore": cavo.STACCATO}
            aspetto.dati = dati
            aspetto.evento.set()
            return True

    def offri(self, sorgente: Path) -> str:
        chiave = secrets.token_urlsafe(16)
        with self._condizione:
            self._file[chiave] = Path(sorgente)
        return chiave

    def file(self, chiave: str) -> Path | None:
        with self._condizione:
            return self._file.pop(chiave, None)


banco = Banco()


class Lontano:

    def __init__(self, sul_banco: Banco, nome: str, mani: int = 1):
        self.banco = sul_banco
        self.nome = nome
        self.mani = mani

    def aiuto(self):
        if self.mani < 2:
            return None
        return lambda: _Aiuto(self.banco, self.nome)

    def _chiedi(self, op: str, attesa: float | None = None,
                **argomenti) -> tuple[dict, bytes | None]:
        return self.banco.chiedi(op, attesa or ATTESA_DI_UN_COMANDO, **argomenti)

    def esiste(self, posto: str) -> bool:
        return bool(self._chiedi("esiste", posto=posto)[0].get("si"))

    def elenco(self, cartella: str) -> dict[str, int]:
        letto = self._chiedi("elenco", cartella=cartella)[0].get("elenco") or {}
        return {str(posto): int(misura) for posto, misura in letto.items()}

    def scarica(self, posto: str, dove: Path) -> None:
        _, dati = self._chiedi("scarica", posto=posto)
        if dati is None:
            raise cavo.GuastoDelCavo(posto)
        Path(dove).write_bytes(dati)

    def carica(self, sorgente: Path, posto: str) -> None:
        misura = Path(sorgente).stat().st_size
        chiave = self.banco.offri(sorgente)
        self._chiedi("carica", ATTESA_DI_UN_COMANDO + misura / VELOCITA_MINIMA,
                     posto=posto, file=chiave, misura=misura)

    def leggi(self, posto: str) -> bytes:
        _, dati = self._chiedi("leggi", posto=posto)
        if dati is None:
            raise cavo.GuastoDelCavo(posto)
        return dati

    def scrivi(self, posto: str, dati: bytes) -> None:
        self._chiedi("scrivi", ATTESA_DI_UN_COMANDO + len(dati) / VELOCITA_MINIMA,
                     posto=posto, dati=base64.b64encode(dati).decode("ascii"))

    def impronta(self, posto: str) -> str:
        return str(self._chiedi("impronta", posto=posto)[0].get("sha") or "")

    def sposta(self, da: str, a: str) -> None:
        self._chiedi("sposta", da=da, a=a)

    def togli(self, posto: str) -> None:
        self._chiedi("togli", posto=posto)

    def chiudi(self) -> None:
        try:
            if self.banco.aperto and not self.banco.perso:
                self._chiedi("chiudi", ATTESA_DEL_SALUTO)
        except ErroreOfficina:
            pass
        finally:
            self.banco.chiudi()


class _Aiuto(Lontano):

    def chiudi(self) -> None:
        pass


def prepara() -> None:
    banco.apri()


def collega(attesa: float | None = None) -> Lontano:
    if not banco.aperto:
        banco.apri()
    try:
        return _saluta(attesa)
    except ErroreOfficina:
        banco.chiudi()
        raise


def ricollega(attesa: float | None = None) -> Lontano:
    banco.apri()
    return _saluta(attesa)


def _saluta(attesa: float | None) -> Lontano:
    try:
        esito, _ = banco.chiedi("collega", attesa or ATTESA_DEL_PORTATILE)
    except ErroreOfficina as errore:
        if errore.codice == "cavo_portatile_perso":
            raise ErroreOfficina(PORTATILE_ZITTO, codice="cavo_portatile_zitto") from None
        raise
    try:
        mani = max(1, int(esito.get("mani") or 1))
    except (TypeError, ValueError):
        mani = 1
    return Lontano(banco, str(esito.get("nome") or "l'iPhone"), mani)


def pulisci_gli_avanzi(dove: Path | None = None) -> int:
    tolti = 0
    for vecchia in Path(dove or tempfile.gettempdir()).glob(AVANZI + "*"):
        if vecchia.is_dir():
            shutil.rmtree(vecchia, ignore_errors=True)
            tolti += 1
    return tolti


def _a_pezzi(numero: str, esito: dict, dati: bytes | None) -> tuple[bytes, str]:
    confine = secrets.token_hex(16)
    pezzi = [(f'--{confine}\r\nContent-Disposition: form-data; name="numero"\r\n\r\n'
              f"{numero}\r\n").encode("ascii")]
    allegati = [("esito", json.dumps(esito).encode("utf-8"))]
    if dati is not None:
        allegati.append(("dati", dati))
    for nome, contenuto in allegati:
        pezzi.append((f"--{confine}\r\nContent-Disposition: form-data; name=\"{nome}\"; "
                      f"filename=\"{nome}\"\r\nContent-Type: application/octet-stream"
                      "\r\n\r\n").encode("ascii") + contenuto + b"\r\n")
    pezzi.append(f"--{confine}--\r\n".encode("ascii"))
    return b"".join(pezzi), f"multipart/form-data; boundary={confine}"


class Mani:

    def __init__(self, al_fisso, collega_qui=None, quante: int = MANI):
        self.al_fisso = al_fisso
        self._collega_qui = collega_qui
        self.quante = max(1, quante)
        self.fatti = 0
        self._qui = Path(tempfile.gettempdir())
        self._lucchetto = threading.Lock()
        self._mia = threading.local()
        self._aperti: list = []

    @property
    def telefono(self) -> cavo.Telefono | None:
        return getattr(self._mia, "telefono", None)

    @telefono.setter
    def telefono(self, telefono: cavo.Telefono | None) -> None:
        self._mia.telefono = telefono

    def lavora(self, fermo: threading.Event | None = None) -> None:
        fermo = fermo or threading.Event()
        basta = threading.Event()
        pulisci_gli_avanzi()
        with tempfile.TemporaryDirectory(prefix=AVANZI) as cartella:
            self._qui = Path(cartella)
            altre = [threading.Thread(target=self._giro, args=(fermo, basta, numero),
                                      name=f"mani-{numero}", daemon=True)
                     for numero in range(1, self.quante)]
            for filo in altre:
                filo.start()
            try:
                self._giro(fermo, basta, 0)
            finally:
                basta.set()
                for filo in altre:
                    filo.join(ATTESA_DELLA_DOMANDA * 3)
                with self._lucchetto:
                    aperti, self._aperti = self._aperti, []
                for telefono in aperti:
                    try:
                        telefono.chiudi()
                    except Exception:
                        pass

    def _giro(self, fermo: threading.Event, basta: threading.Event, numero: int) -> None:
        self._mia.numero = numero
        self._mia.telefono = None
        sbagli = 0
        try:
            while not fermo.is_set() and not basta.is_set():
                comando = self._prendi()
                if comando is None:
                    sbagli += 1
                    if sbagli >= TENTATIVI:
                        return
                    fermo.wait(1.0)
                    continue
                sbagli = 0
                op = comando.get("op")
                if op == "fine":
                    return
                if op == "niente":
                    continue
                esito, dati = self._fai(comando)
                self._rispondi(str(comando.get("id") or ""), esito, dati)
                with self._lucchetto:
                    self.fatti += 1
        finally:
            basta.set()
            self._chiudi()

    def _prendi(self) -> dict | None:
        try:
            stato, corpo = self.al_fisso("GET", PRENDI)
            comando = json.loads(corpo) if stato == 200 else None
        except (OSError, ValueError, ErroreOfficina, http.client.HTTPException):
            return None
        return comando if isinstance(comando, dict) else None

    def _rispondi(self, numero: str, esito: dict, dati: bytes | None) -> None:
        corpo, tipo = _a_pezzi(numero, esito, dati)
        for _prova in range(2):
            try:
                stato, _ = self.al_fisso("POST", RISPONDI, corpo, tipo)
            except (OSError, ErroreOfficina, http.client.HTTPException):
                continue
            if stato == 200:
                return

    def _chiudi(self) -> None:
        telefono, self.telefono = self.telefono, None
        if telefono is None:
            return
        with self._lucchetto:
            if telefono in self._aperti:
                self._aperti.remove(telefono)
        try:
            telefono.chiudi()
        except Exception:
            pass

    def _apri(self) -> cavo.Telefono:
        self._chiudi()
        telefono = (self._collega_qui or cavo.collega)()
        with self._lucchetto:
            self._aperti.append(telefono)
        self.telefono = telefono
        return telefono

    def _fai(self, comando: dict) -> tuple[dict, bytes | None]:
        op = comando.get("op")
        try:
            if op == "collega":
                return {"nome": self._apri().nome, "mani": self.quante}, None
            if op == "chiudi":
                self._chiudi()
                return {}, None
            telefono = self.telefono or self._apri()
            posto = str(comando.get("posto") or "")
            if op == "esiste":
                return {"si": telefono.esiste(posto)}, None
            if op == "elenco":
                return {"elenco": telefono.elenco(str(comando.get("cartella") or ""))}, None
            if op == "impronta":
                return {"sha": telefono.impronta(posto)}, None
            if op == "leggi":
                return {}, telefono.leggi(posto)
            if op == "scrivi":
                telefono.scrivi(posto, base64.b64decode(str(comando.get("dati") or "")))
                return {}, None
            if op == "sposta":
                telefono.sposta(str(comando["da"]), str(comando["a"]))
                return {}, None
            if op == "togli":
                telefono.togli(posto)
                return {}, None
            if op == "carica":
                self._carica(telefono, posto, str(comando.get("file") or ""),
                             int(comando.get("misura") or 0))
                return {}, None
            if op == "scarica":
                return {}, self._scarica(telefono, posto)
            return {"errore": NON_CAPITO, "codice": "cavo_non_capito"}, None
        except ErroreOfficina as errore:
            return {"errore": errore.messaggio, "codice": errore.codice}, None
        except Exception:
            return {"errore": cavo.STACCATO, "codice": "cavo_staccato"}, None

    def _carica(self, telefono, posto: str, chiave: str, misura: int) -> None:
        dove = self._qui / f"su-{getattr(self._mia, 'numero', 0)}"
        try:
            stato, _ = self.al_fisso("GET", FILE + chiave, in_file=dove)
            if stato != 200 or not dove.is_file() or dove.stat().st_size != misura:
                raise cavo.GuastoDelCavo(posto)
            telefono.carica(dove, posto)
        finally:
            dove.unlink(missing_ok=True)

    def _scarica(self, telefono, posto: str) -> bytes:
        dove = self._qui / f"giu-{getattr(self._mia, 'numero', 0)}"
        try:
            telefono.scarica(posto, dove)
            return dove.read_bytes()
        finally:
            dove.unlink(missing_ok=True)
