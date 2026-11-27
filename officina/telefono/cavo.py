from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import sys
import threading
import time
import types
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from officina.errori import ErroreOfficina
from officina.telefono import formato
from officina.telefono.orologio import unita

APP = "local.visore.app"
PACCHETTO = "Pacchetto"
RITORNO_SUL_TELEFONO = "Ritorno/" + formato.RITORNO
MANIFESTO = ".cavo.json"
LOCALE = ".cavo-locale.json"
PARZIALE = ".parziale"
PEZZO = 4 * 1024 * 1024
OGNI = 200
OGNI_SECONDI = 60.0
NOSTRI = re.compile(r"(?:(?:foto|mini)/[0-9a-f]{2}|volti)/[0-9a-f]{32}(?:\.parziale)?"
                    r"|(?:dati\.db|visore\.json|\.cavo\.json)\.parziale")

NESSUNO = ("Non vedo nessun iPhone attaccato col cavo. Attaccalo, sbloccalo e riprova. "
           "Su Windows serve anche l'app «Dispositivi Apple» (o iTunes), la stessa "
           "che usa AltStore.")
FIDATI = ("Sull'iPhone è comparso «Vuoi autorizzare questo computer?»: sbloccalo, premi "
          "«Autorizza», scrivi il codice dell'iPhone e poi riprova.")
SENZA_APP = ("Sull'iPhone attaccato non trovo il Visore. Installalo con AltStore, aprilo "
             "una volta e poi riprova.")
DUE_APP = ("Sull'iPhone attaccato ci sono due Visore. Tienine uno solo, così so dove "
           "copiare, e poi riprova.")
APRILO = ("Apri il Visore una volta sull'iPhone e poi riprova: è lui che prepara la "
          "cartella dove copio.")
STACCATO = ("L'iPhone si è staccato o si è bloccato a metà copia. Il Visore resta chiuso "
            "finché non finisco: riattacca l'iPhone, tienilo sbloccato e riparti. "
            "Copio solo quello che manca.")
MANCA_IL_PEZZO = ("Manca il pezzo del programma che parla con l'iPhone. Rifai "
                  "l'installazione e riprova.")


class Telefono(Protocol):

    nome: str

    def esiste(self, posto: str) -> bool: ...

    def elenco(self, cartella: str) -> dict[str, int]: ...

    def scarica(self, posto: str, dove: Path) -> None: ...

    def carica(self, sorgente: Path, posto: str) -> None: ...

    def leggi(self, posto: str) -> bytes: ...

    def scrivi(self, posto: str, dati: bytes) -> None: ...

    def impronta(self, posto: str) -> str: ...

    def sposta(self, da: str, a: str) -> None: ...

    def togli(self, posto: str) -> None: ...

    def chiudi(self) -> None: ...


class GuastoDelCavo(ErroreOfficina):

    def __init__(self, dove: str = "", causa: str = ""):
        super().__init__(STACCATO, codice="cavo_staccato")
        self.dove = dove
        self.causa = causa


def causa_tecnica(guaio: BaseException) -> str:
    gia = getattr(guaio, "causa", "")
    if isinstance(gia, str) and gia:
        return gia[:120]
    parti = [type(guaio).__name__]
    stato = getattr(guaio, "status", None)
    nome = getattr(stato, "name", None)
    if isinstance(nome, str):
        parti.append(nome)
    elif isinstance(stato, int):
        parti.append(f"stato {stato}")
    numero = getattr(guaio, "errno", None)
    if isinstance(numero, int):
        parti.append(f"errno {numero}")
    if isinstance(guaio, ErroreOfficina):
        parti.append(guaio.codice)
    return " ".join(p for p in parti if p)[:120]


@dataclass
class EsitoCavo:

    mandati: int = 0
    peso: int = 0
    uguali: int = 0
    ritrovati: int = 0
    tolti: int = 0
    ritorno: bool = False
    interrotto: bool = False
    guasti: list[str] = field(default_factory=list)

    @property
    def completo(self) -> bool:
        return not self.interrotto and not self.guasti

    def a_parole(self) -> str:
        if self.interrotto:
            return ("Copia col cavo fermata a metà: il Visore resta chiuso finché non "
                    "la finisci. Ripartendo copio solo quello che manca.")
        if self.guasti:
            return (f"Copia col cavo NON finita: {len(self.guasti)} file non tornano "
                    "uguali dopo la copia. Il Visore resta chiuso: riprova.")
        if not self.mandati and not self.tolti:
            return "Sull'iPhone era già tutto uguale: non ho copiato niente."
        return (f"Copiati sull'iPhone {self.mandati} file ({_misura(self.peso)}), "
                f"riletti uno per uno e uguali. Tolti {self.tolti} vecchi, "
                f"{self.uguali} erano già lì"
                + (f" (di cui {self.ritrovati} rimasti dalla copia interrotta "
                   "e ricontrollati)" if self.ritrovati else "") + ".")


def collega() -> Telefono:
    return IPhone()


def controlla(telefono: Telefono, cartella: Path) -> formato.Carta | None:
    if not telefono.esiste(PACCHETTO):
        raise ErroreOfficina(APRILO, codice="cavo_aprilo")
    lassu = _carta_del_telefono(telefono)
    if lassu is None or not (Path(cartella) / formato.CARTA).is_file():
        return lassu
    qui = formato.Carta.leggi(Path(cartella))
    if lassu.get("archivio") != qui.archivio:
        raise ErroreOfficina(
            "Sull'iPhone c'è il pacchetto di **un altro archivio**: non lo copro. "
            "Se vuoi davvero cambiarlo, prima cancella il Visore dall'iPhone e "
            "reinstallalo.", codice="cavo_altro_archivio")
    if lassu.get("telefono") != qui.telefono:
        raise ErroreOfficina(
            f"Sull'iPhone c'è il pacchetto di «{lassu.get('telefono')}», e questo è "
            f"quello di «{qui.telefono}». Ogni telefono ha il suo (regola 368).",
            codice="cavo_altro_telefono")
    return lassu


def prendi_il_ritorno(telefono: Telefono, cartella: Path) -> str:
    cartella = Path(cartella)
    if not telefono.esiste(RITORNO_SUL_TELEFONO):
        return "nessuno"
    lassu = _carta_del_telefono(telefono)
    if lassu is None or not (cartella / formato.CARTA).is_file():
        return "senza_pacchetto"
    qui = formato.Carta.leggi(cartella)
    if lassu.get("sale") != qui.sale or lassu.get("archivio") != qui.archivio:
        return "altra_chiave"
    dove = formato.dentro(cartella, formato.RITORNO)
    provvisorio = dove.with_name(dove.name + PARZIALE)
    try:
        telefono.scarica(RITORNO_SUL_TELEFONO, provvisorio)
        if _sha_locale(provvisorio) != telefono.impronta(RITORNO_SUL_TELEFONO):
            provvisorio.unlink(missing_ok=True)
            raise GuastoDelCavo("ritorno")
        os.replace(provvisorio, dove)
    finally:
        provvisorio.unlink(missing_ok=True)
    return "preso"


def manda(telefono: Telefono, cartella: Path, quando_cambia=None,
          fermati: threading.Event | None = None, aiuto=None,
          quanto_pesa=None) -> EsitoCavo:
    cartella = Path(cartella)
    avanti = quando_cambia or (lambda *_: None)
    pesa = quanto_pesa or (lambda *_: None)
    fermati = fermati or threading.Event()
    esito = EsitoCavo()

    carta = formato.Carta.leggi(cartella)
    if carta.stato != formato.COMPLETO:
        raise ErroreOfficina("Il pacchetto sul computer non è finito: non lo copio. "
                             "Prima finisci il travaso.", codice="cavo_non_finito")
    controlla(telefono, cartella)

    avanti("conto", 0, 0)
    locali = _locali(cartella, avanti, fermati, pesa)
    if fermati.is_set():
        esito.interrotto = True
        return esito
    sul_telefono = telefono.elenco(PACCHETTO)
    manifesto = _manifesto(telefono)

    da_mandare = [p for p, (misura, sha) in locali.items()
                  if manifesto.get(p) != [misura, sha] or sul_telefono.get(p) != misura]
    ritrovati = _ritrova(telefono, da_mandare, locali, sul_telefono, manifesto,
                         avanti, fermati)
    if fermati.is_set():
        esito.interrotto = True
        return esito
    if ritrovati:
        da_mandare = [p for p in da_mandare if p not in ritrovati]
        esito.ritrovati = len(ritrovati)
    esito.uguali = len(locali) - len(da_mandare)
    da_mandare.sort(key=_ordine)

    if da_mandare and formato.CARTA in sul_telefono:
        chiusa = json.loads((cartella / formato.CARTA).read_text(encoding="utf-8"))
        chiusa["stato"] = formato.INTERROTTO
        _scrivi_sicuro(telefono, f"{PACCHETTO}/{formato.CARTA}",
                       json.dumps(chiusa, ensure_ascii=False, indent=2).encode("utf-8"))
        manifesto.pop(formato.CARTA, None)
        _salva_il_manifesto(telefono, manifesto)
        if formato.CARTA not in da_mandare:
            da_mandare.append(formato.CARTA)
            esito.uguali -= 1

    try:
        _copia(telefono, cartella, da_mandare, locali, manifesto, esito, avanti, fermati,
               aiuto, pesa)
    except BaseException:
        try:
            _salva_il_manifesto(telefono, manifesto)
        except Exception:
            pass
        raise
    for posto in list(manifesto):
        if posto not in locali:
            manifesto.pop(posto)
    _salva_il_manifesto(telefono, manifesto)
    if not esito.completo:
        return esito

    avanti("controllo", 0, 1)
    dopo = telefono.elenco(PACCHETTO)
    for posto, (dimensione, _) in locali.items():
        if dopo.get(posto) != dimensione:
            esito.guasti.append(f"{posto}: sull'iPhone manca o ha un'altra misura")
    if esito.guasti:
        return esito

    vecchi = sorted(p for p in dopo if p not in locali and NOSTRI.fullmatch(p))
    for numero, posto in enumerate(vecchi, start=1):
        avanti("tolgo", numero, len(vecchi))
        telefono.togli(f"{PACCHETTO}/{posto}")
        esito.tolti += 1
    avanti("controllo", 1, 1)
    return esito


class _Insieme:

    def __init__(self, cartella: Path, da_mandare: list[str], locali: dict,
                 manifesto: dict, esito: EsitoCavo, avanti, fermati: threading.Event,
                 pesa=None):
        self.cartella = cartella
        self.quanti = len(da_mandare)
        self.pesa = pesa or (lambda *_: None)
        self.da_pesare = sum(unita(locali[p][0]) for p in da_mandare)
        self.pesato = 0
        self.in_fila = [p for p in da_mandare if _ordine(p)[0] == 0]
        self.in_coda = [p for p in da_mandare if _ordine(p)[0] != 0]
        self.locali = locali
        self.manifesto = manifesto
        self.esito = esito
        self.avanti = avanti
        self.fermati = fermati
        self.lucchetto = threading.Lock()
        self.rotto = threading.Event()
        self.fatti = 0
        self.dal_salvataggio = 0
        self.salvato_il = time.monotonic()

    def prendi(self) -> str | None:
        with self.lucchetto:
            if self.fermati.is_set() or self.rotto.is_set() or not self.in_fila:
                return None
            return self.in_fila.pop(0)

    def rimetti(self, posto: str) -> None:
        with self.lucchetto:
            self.in_fila.insert(0, posto)

    def manda(self, telefono: Telefono, posto: str) -> None:
        dimensione, sha = self.locali[posto]
        lassu = f"{PACCHETTO}/{posto}"
        provvisorio = lassu + PARZIALE
        telefono.carica(formato.dentro(self.cartella, posto), provvisorio)
        uguale = telefono.impronta(provvisorio) == sha
        if uguale:
            telefono.sposta(provvisorio, lassu)
        else:
            telefono.togli(provvisorio)
        with self.lucchetto:
            self.fatti += 1
            if not uguale:
                self.esito.guasti.append(f"{posto}: sull'iPhone non è uguale")
            else:
                self.manifesto[posto] = [dimensione, sha]
                self.esito.mandati += 1
                self.esito.peso += dimensione
                self.dal_salvataggio += 1
                if (self.dal_salvataggio >= OGNI
                        or time.monotonic() - self.salvato_il >= OGNI_SECONDI):
                    _salva_il_manifesto(telefono, self.manifesto)
                    self.dal_salvataggio = 0
                    self.salvato_il = time.monotonic()
            self.pesato += unita(dimensione)
            self.avanti("copio", self.fatti, self.quanti)
            self.pesa("copio", self.pesato, self.da_pesare)

    def lavora(self, telefono: Telefono) -> None:
        try:
            while (posto := self.prendi()) is not None:
                self.manda(telefono, posto)
        except BaseException:
            self.rotto.set()
            raise

    def aiuta(self, aiuto) -> None:
        try:
            secondo = aiuto()
        except Exception:
            return
        try:
            while (posto := self.prendi()) is not None:
                try:
                    self.manda(secondo, posto)
                except Exception:
                    dimensione, sha = self.locali[posto]
                    if self.manifesto.get(posto) != [dimensione, sha]:
                        self.rimetti(posto)
                    return
        finally:
            try:
                secondo.chiudi()
            except Exception:
                pass


def _copia(telefono: Telefono, cartella: Path, da_mandare: list[str],
           locali: dict[str, tuple[int, str]], manifesto: dict, esito: EsitoCavo,
           avanti, fermati: threading.Event, aiuto=None, pesa=None) -> None:
    insieme = _Insieme(cartella, da_mandare, locali, manifesto, esito, avanti, fermati,
                       pesa)
    avanti("copio", 0, insieme.quanti)
    insieme.pesa("copio", 0, insieme.da_pesare)
    filo = None
    if aiuto is not None and len(insieme.in_fila) > 1:
        filo = threading.Thread(target=insieme.aiuta, args=(aiuto,),
                                name="cavo-aiuto", daemon=True)
        filo.start()
    try:
        insieme.lavora(telefono)
    finally:
        if filo is not None:
            filo.join()
    if insieme.in_fila and not fermati.is_set():
        insieme.lavora(telefono)
    for posto in insieme.in_coda:
        if fermati.is_set():
            break
        if posto == formato.CARTA and esito.guasti:
            return
        insieme.manda(telefono, posto)
    if fermati.is_set() and (insieme.in_fila or insieme.fatti < insieme.quanti):
        esito.interrotto = True
        return
    avanti("copio", insieme.quanti, insieme.quanti)


def _ritrova(telefono: Telefono, da_mandare: list[str], locali: dict,
             sul_telefono: dict, manifesto: dict, avanti,
             fermati: threading.Event) -> set[str]:
    forse = [p for p in da_mandare
             if p != formato.CARTA and sul_telefono.get(p) == locali[p][0]]
    ritrovati: set[str] = set()
    for numero, posto in enumerate(forse, start=1):
        if fermati.is_set():
            break
        avanti("ricontrollo", numero, len(forse))
        dimensione, sha = locali[posto]
        if telefono.impronta(f"{PACCHETTO}/{posto}") == sha:
            manifesto[posto] = [dimensione, sha]
            ritrovati.add(posto)
    if ritrovati:
        _salva_il_manifesto(telefono, manifesto)
    return ritrovati


def _ordine(posto: str) -> tuple[int, str]:
    if posto == formato.CARTA:
        return (2, posto)
    if posto == formato.DATI:
        return (1, posto)
    return (0, posto)


def _carta_del_telefono(telefono: Telefono) -> dict | None:
    posto = f"{PACCHETTO}/{formato.CARTA}"
    if not telefono.esiste(posto):
        return None
    try:
        carta = json.loads(telefono.leggi(posto).decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    return carta if isinstance(carta, dict) else None


def misure_lassu(telefono: Telefono) -> dict[str, int]:
    try:
        return {p: v[0] for p, v in _manifesto(telefono).items()
                if isinstance(v[0], int)}
    except Exception:
        return {}


def _manifesto(telefono: Telefono) -> dict[str, list]:
    posto = f"{PACCHETTO}/{MANIFESTO}"
    if not telefono.esiste(posto):
        return {}
    try:
        letto = json.loads(telefono.leggi(posto).decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return {}
    if not isinstance(letto, dict):
        return {}
    return {k: v for k, v in letto.items()
            if isinstance(k, str) and isinstance(v, list) and len(v) == 2}


def _salva_il_manifesto(telefono: Telefono, manifesto: dict) -> None:
    _scrivi_sicuro(telefono, f"{PACCHETTO}/{MANIFESTO}",
                   json.dumps(manifesto, sort_keys=True).encode("utf-8"))


def _scrivi_sicuro(telefono: Telefono, posto: str, dati: bytes) -> None:
    provvisorio = posto + PARZIALE
    telefono.scrivi(provvisorio, dati)
    if telefono.impronta(provvisorio) != hashlib.sha256(dati).hexdigest():
        telefono.togli(provvisorio)
        raise GuastoDelCavo(posto, causa="impronta diversa dopo la scrittura")
    telefono.sposta(provvisorio, posto)


def _locali(cartella: Path, avanti, fermati: threading.Event,
            pesa=None) -> dict[str, tuple[int, str]]:
    pesa = pesa or (lambda *_: None)
    ricordo = _ricordo_locale(cartella)
    nuovo: dict[str, list] = {}
    trovati: list[tuple[str, Path]] = []
    for dove in sorted(cartella.rglob("*")):
        if not dove.is_file():
            continue
        posto = dove.relative_to(cartella).as_posix()
        if posto in (formato.RITORNO, LOCALE) or posto.endswith(PARZIALE):
            continue
        nostro = posto in (formato.CARTA, formato.DATI) or formato.A_CASO.fullmatch(posto)
        if not nostro:
            continue
        trovati.append((posto, dove))
    locali: dict[str, tuple[int, str]] = {}
    stati = {}
    da_pesare = 0
    for posto, dove in trovati:
        stato = dove.stat()
        vecchio = ricordo.get(posto)
        gia = bool(vecchio and vecchio[0] == stato.st_size
                   and vecchio[1] == stato.st_mtime_ns)
        stati[posto] = (stato, gia)
        if not gia:
            da_pesare += unita(stato.st_size)
    pesato = 0
    pesa("conto", 0, da_pesare)
    for numero, (posto, dove) in enumerate(trovati, start=1):
        if fermati.is_set():
            break
        avanti("conto", numero, len(trovati))
        stato, gia = stati[posto]
        vecchio = ricordo.get(posto)
        if gia:
            sha = vecchio[2]
        else:
            sha = _sha_locale(dove)
            pesato += unita(stato.st_size)
            pesa("conto", pesato, da_pesare)
        nuovo[posto] = [stato.st_size, stato.st_mtime_ns, sha]
        locali[posto] = (stato.st_size, sha)
    _salva_il_ricordo(cartella, nuovo)
    return locali


def _ricordo_locale(cartella: Path) -> dict[str, list]:
    try:
        letto = json.loads((cartella / LOCALE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(letto, dict):
        return {}
    return {k: v for k, v in letto.items() if isinstance(v, list) and len(v) == 3}


def _salva_il_ricordo(cartella: Path, ricordo: dict) -> None:
    dove = cartella / LOCALE
    provvisorio = dove.with_name(dove.name + PARZIALE)
    try:
        provvisorio.write_text(json.dumps(ricordo, sort_keys=True), encoding="utf-8")
        os.replace(provvisorio, dove)
    except OSError:
        provvisorio.unlink(missing_ok=True)


def _sha_locale(dove: Path) -> str:
    calcolo = hashlib.sha256()
    with open(dove, "rb") as f:
        while pezzo := f.read(PEZZO):
            calcolo.update(pezzo)
    return calcolo.hexdigest()


def _misura(byte: int) -> str:
    from officina.telefono.selezione import a_misura
    return a_misura(byte)


class FintoTelefono:

    def __init__(self, radice: Path, nome: str = "iPhone finto",
                 rovina: set[str] | None = None, stacca_dopo: int | None = None):
        self.radice = Path(radice)
        self.nome = nome
        self.rovina = set(rovina or ())
        self.stacca_dopo = stacca_dopo
        self.caricati: list[str] = []
        self.chiuso = False

    def _dove(self, posto: str) -> Path:
        return formato.dentro(self.radice, posto)

    def esiste(self, posto: str) -> bool:
        return self._dove(posto).exists()

    def elenco(self, cartella: str) -> dict[str, int]:
        base = self._dove(cartella)
        if not base.is_dir():
            return {}
        return {p.relative_to(base).as_posix(): p.stat().st_size
                for p in base.rglob("*") if p.is_file()}

    def scarica(self, posto: str, dove: Path) -> None:
        Path(dove).write_bytes(self._dove(posto).read_bytes())

    def carica(self, sorgente: Path, posto: str) -> None:
        if self.stacca_dopo is not None and len(self.caricati) >= self.stacca_dopo:
            raise GuastoDelCavo("staccato")
        dati = Path(sorgente).read_bytes()
        if any(posto.startswith(f"{PACCHETTO}/{r}") for r in self.rovina) and dati:
            dati = bytes([dati[0] ^ 1]) + dati[1:]
        self.scrivi(posto, dati)
        self.caricati.append(posto)

    def leggi(self, posto: str) -> bytes:
        return self._dove(posto).read_bytes()

    def scrivi(self, posto: str, dati: bytes) -> None:
        dove = self._dove(posto)
        dove.parent.mkdir(parents=True, exist_ok=True)
        dove.write_bytes(dati)

    def impronta(self, posto: str) -> str:
        return _sha_locale(self._dove(posto))

    def sposta(self, da: str, a: str) -> None:
        os.replace(self._dove(da), self._dove(a))

    def togli(self, posto: str) -> None:
        self._dove(posto).unlink(missing_ok=True)

    def chiudi(self) -> None:
        self.chiuso = True


class IPhone:

    def __init__(self) -> None:
        self._ciclo = (asyncio.SelectorEventLoop() if sys.platform == "win32"
                       else asyncio.new_event_loop())
        self._afc = None
        self._lockdown = None
        self._base = "/Documents"
        self.nome = "iPhone"
        try:
            self._fai(self._apri())
        except BaseException:
            self.chiudi()
            raise

    def _fai(self, lavoro):
        try:
            return self._ciclo.run_until_complete(lavoro)
        except ErroreOfficina:
            raise
        except Exception as guaio:
            if _staccato(guaio):
                raise GuastoDelCavo(causa=causa_tecnica(guaio)) from None
            raise

    async def _apri(self) -> None:
        _senza_pywin32()
        try:
            from pymobiledevice3 import exceptions as e
            from pymobiledevice3.lockdown import create_using_usbmux
            from pymobiledevice3.services.house_arrest import HouseArrestService
            from pymobiledevice3.services.installation_proxy import (
                InstallationProxyService)
        except ImportError:
            raise ErroreOfficina(MANCA_IL_PEZZO, codice="cavo_manca") from None
        try:
            self._lockdown = await create_using_usbmux(connection_type="USB")
        except (e.NoDeviceConnectedError, e.ConnectionFailedError, e.DeviceNotFoundError,
                e.MuxException, ConnectionError):
            raise ErroreOfficina(NESSUNO, codice="cavo_nessuno") from None
        except (e.PairingDialogResponsePendingError, e.PasswordRequiredError,
                e.NotTrustedError, e.NotPairedError):
            raise ErroreOfficina(FIDATI, codice="cavo_fidati") from None
        except e.UserDeniedPairingError:
            raise ErroreOfficina(
                "Sull'iPhone hai premuto «Non autorizzare». Stacca e riattacca il cavo, "
                "poi premi «Autorizza».", codice="cavo_negato") from None
        self.nome = str(self._lockdown.all_values.get("DeviceName") or "iPhone")
        async with InstallationProxyService(lockdown=self._lockdown) as installate:
            app = await installate.get_apps(application_type="User")
        trovate = sorted(b for b in app if b == APP or b.startswith(APP + "."))
        if not trovate:
            raise ErroreOfficina(SENZA_APP, codice="cavo_senza_app")
        if len(trovate) > 1:
            raise ErroreOfficina(DUE_APP, codice="cavo_due_app")
        try:
            self._afc = await HouseArrestService.create(self._lockdown, trovate[0],
                                                         documents_only=True)
        except e.PyMobileDevice3Exception:
            raise ErroreOfficina(
                "L'iPhone non mi lascia entrare nella cartella del Visore. Aggiorna il "
                "Visore con AltStore e riprova.", codice="cavo_chiuso") from None
        await self._afc.__aenter__()
        if not await self._afc.exists(self._base):
            self._base = ""

    def _p(self, posto: str) -> str:
        return f"{self._base}/{posto}"

    def esiste(self, posto: str) -> bool:
        return self._fai(self._afc.exists(self._p(posto)))

    def elenco(self, cartella: str) -> dict[str, int]:
        return self._fai(self._elenco(cartella))

    async def _elenco(self, cartella: str) -> dict[str, int]:
        base = self._p(cartella)
        if not await self._afc.exists(base):
            return {}
        trovati: dict[str, int] = {}
        async for dove, _, file in self._afc.walk(base):
            for nome in file:
                pieno = f"{dove.rstrip('/')}/{nome}"
                stato = await self._afc.stat(pieno)
                trovati[pieno[len(base) + 1:]] = int(stato["st_size"])
        return trovati

    def scarica(self, posto: str, dove: Path) -> None:
        self._fai(self._scarica(posto, Path(dove)))

    async def _scarica(self, posto: str, dove: Path) -> None:
        quanto = int((await self._afc.stat(self._p(posto)))["st_size"])
        maniglia = await self._afc.fopen(self._p(posto), "r")
        try:
            with open(dove, "wb") as f:
                while quanto > 0:
                    pezzo = await self._afc.fread(maniglia, min(PEZZO, quanto))
                    if not pezzo:
                        raise GuastoDelCavo(posto, causa="lettura finita prima del tempo")
                    f.write(pezzo)
                    quanto -= len(pezzo)
        finally:
            await self._afc.fclose(maniglia)

    def carica(self, sorgente: Path, posto: str) -> None:
        self._fai(self._carica(Path(sorgente), posto))

    async def _carica(self, sorgente: Path, posto: str) -> None:
        sopra = self._p(posto).rsplit("/", 1)[0]
        if sopra and not await self._afc.exists(sopra):
            await self._afc.makedirs(sopra)
        maniglia = await self._afc.fopen(self._p(posto), "w")
        try:
            with open(sorgente, "rb") as f:
                while pezzo := f.read(PEZZO):
                    await self._afc.fwrite(maniglia, pezzo)
        finally:
            await self._afc.fclose(maniglia)

    def leggi(self, posto: str) -> bytes:
        return self._fai(self._afc.get_file_contents(self._p(posto)))

    def scrivi(self, posto: str, dati: bytes) -> None:
        self._fai(self._afc.set_file_contents(self._p(posto), dati))

    def impronta(self, posto: str) -> str:
        return self._fai(self._impronta(posto))

    async def _impronta(self, posto: str) -> str:
        quanto = int((await self._afc.stat(self._p(posto)))["st_size"])
        calcolo = hashlib.sha256()
        maniglia = await self._afc.fopen(self._p(posto), "r")
        try:
            while quanto > 0:
                pezzo = await self._afc.fread(maniglia, min(PEZZO, quanto))
                if not pezzo:
                    break
                calcolo.update(pezzo)
                quanto -= len(pezzo)
        finally:
            await self._afc.fclose(maniglia)
        return calcolo.hexdigest()

    def sposta(self, da: str, a: str) -> None:
        self._fai(self._sposta(da, a))

    async def _sposta(self, da: str, a: str) -> None:
        from pymobiledevice3.exceptions import AfcException
        try:
            await self._afc.rename(self._p(da), self._p(a))
        except AfcException:
            await self._afc.rm_single(self._p(a), force=True)
            await self._afc.rename(self._p(da), self._p(a))

    def togli(self, posto: str) -> None:
        self._fai(self._afc.rm_single(self._p(posto), force=True))

    def chiudi(self) -> None:
        try:
            if self._afc is not None:
                self._ciclo.run_until_complete(self._afc.aclose())
            if self._lockdown is not None:
                self._ciclo.run_until_complete(self._lockdown.close())
        except Exception:
            pass
        finally:
            self._afc = None
            self._lockdown = None
            if not self._ciclo.is_closed():
                self._ciclo.close()


def _senza_pywin32() -> None:
    if sys.platform != "win32" or "win32security" in sys.modules:
        return
    try:
        import win32security
    except ImportError:
        sys.modules["win32security"] = types.ModuleType("win32security")
    else:
        sys.modules["win32security"] = win32security


def _staccato(guaio: Exception) -> bool:
    nomi = {c.__name__ for c in type(guaio).__mro__}
    return bool(nomi & {"ConnectionTerminatedError", "ConnectionAbortedError",
                        "BrokenPipeError", "ConnectionResetError", "NotConnectedError",
                        "StreamClosedError", "AfcException", "GuastoDelCavo"})
