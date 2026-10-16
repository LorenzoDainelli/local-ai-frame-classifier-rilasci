from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from officina import registro
from officina.archivio.database import adesso, tutti
from officina.errori import ErroreOfficina

CARTELLA = "Local AI Frame Classifier"
ELENCO = "elenco.json"
ULTIMA = "ultima.json"
IN_ARRIVO = ".in-arrivo"
PEZZO = 1024 * 1024
SALVA_OGNI = 200
QUANTI_ERRORI = 20

NON_C_E = ("Il disco della copia non si trova. Collegalo, oppure scegli di nuovo "
           "la cartella.")
GIA_IN_CORSO = "Una copia è già in corso: aspetta che finisca."
DENTRO_GLI_ORIGINALI = ("Questa cartella è dentro una cartella degli originali. Scegline una su "
                        "un altro disco: dentro gli originali il programma non scrive mai.")
DENTRO_L_ARCHIVIO = "Questa cartella è dentro l'archivio stesso: scegline una su un altro disco."


@dataclass
class Lavoro:
    fase: str = "inizio"
    fatti: int = 0
    totale: int = 0
    copiati: int = 0
    uguali: int = 0
    mancanti: int = 0
    diversi: int = 0
    rovinati_nella_copia: int = 0
    errori: list[str] = field(default_factory=list)
    finito: bool = False
    fermato: bool = False
    iniziato: float = field(default_factory=time.time)

    def a_parole(self) -> dict:
        return {chiave: valore for chiave, valore in self.__dict__.items()}

    def sbaglio(self, testo: str) -> None:
        if len(self.errori) < QUANTI_ERRORI:
            self.errori.append(testo)


_lavoro: Lavoro | None = None
_filo: threading.Thread | None = None
_ferma = threading.Event()
_lucchetto = threading.Lock()


def a_che_punto() -> dict | None:
    return _lavoro.a_parole() if _lavoro is not None else None


def ferma() -> None:
    _ferma.set()


def ferma_e_aspetta(secondi: float = 120) -> None:
    filo = _filo
    if filo is None or not filo.is_alive() or filo is threading.current_thread():
        return
    _ferma.set()
    filo.join(secondi)


def dove_va(destinazione: Path, nome_archivio: str) -> Path:
    return destinazione / CARTELLA / re.sub(r"[^\w.-]", "_", nome_archivio)


def ultima(destinazione: Path, nome_archivio: str) -> dict | None:
    try:
        return json.loads((dove_va(destinazione, nome_archivio) / ULTIMA).read_text("utf-8"))
    except (OSError, ValueError):
        return None


def controlla_la_cartella(scritta: str, originali: list[str], radice: Path) -> Path:
    if not (scritta or "").strip():
        raise ErroreOfficina("Scegli la cartella dove fare la copia.")
    destinazione = Path(scritta.strip()).expanduser()
    if not destinazione.is_absolute():
        raise ErroreOfficina("Serve il percorso intero della cartella, per esempio E:\\Copie.")
    if not destinazione.is_dir():
        raise ErroreOfficina(NON_C_E)
    vera = destinazione.resolve()
    for cartella in originali:
        try:
            originale = Path(cartella).resolve()
        except OSError:
            continue
        if vera == originale or originale in vera.parents:
            raise ErroreOfficina(DENTRO_GLI_ORIGINALI)
    radice = Path(radice).resolve()
    if vera == radice or radice in vera.parents:
        raise ErroreOfficina(DENTRO_L_ARCHIVIO)
    return destinazione


def relativo(percorso: str) -> Path:
    assoluto = Path(percorso)
    pezzi = [parte for parte in assoluto.parts[1:] if parte not in ("", ".", "..")]
    disco = assoluto.drive.rstrip(":\\/").replace(":", "") or "radice"
    return Path(re.sub(r"[^\w.-]", "_", disco), *pezzi)


def _impronta(percorso: Path) -> str:
    calcolo = hashlib.blake2b(digest_size=32)
    with open(percorso, "rb") as dentro:
        while pezzo := dentro.read(PEZZO):
            if _ferma.is_set():
                raise _Fermato()
            calcolo.update(pezzo)
    return calcolo.hexdigest()


class _Fermato(Exception):
    pass


def _copia_controllata(da: Path, verso: Path) -> str:
    verso.parent.mkdir(parents=True, exist_ok=True)
    provvisorio = verso.with_name(verso.name + IN_ARRIVO)
    calcolo = hashlib.blake2b(digest_size=32)
    try:
        with open(da, "rb") as dentro, open(provvisorio, "wb") as fuori:
            while pezzo := dentro.read(PEZZO):
                if _ferma.is_set():
                    raise _Fermato()
                calcolo.update(pezzo)
                fuori.write(pezzo)
            fuori.flush()
            os.fsync(fuori.fileno())
        letto = calcolo.hexdigest()
        if _impronta(provvisorio) != letto:
            raise ErroreOfficina(f"La copia di «{da.name}» non è uguale all'originale: "
                                 "il disco della copia potrebbe avere un problema.")
        return letto
    except BaseException:
        provvisorio.unlink(missing_ok=True)
        raise


def _metti_al_posto(verso: Path) -> None:
    os.replace(verso.with_name(verso.name + IN_ARRIVO), verso)


def _scarta(verso: Path) -> None:
    verso.with_name(verso.name + IN_ARRIVO).unlink(missing_ok=True)


def _leggi_l_elenco(casa: Path) -> dict:
    try:
        letto = json.loads((casa / ELENCO).read_text("utf-8"))
    except (OSError, ValueError):
        return {}
    return letto if isinstance(letto, dict) else {}


def _scrivi_json(file: Path, contenuto) -> None:
    provvisorio = file.with_name(file.name + IN_ARRIVO)
    provvisorio.write_text(json.dumps(contenuto, ensure_ascii=False), "utf-8")
    os.replace(provvisorio, file)


def _copia_l_archivio(archivio, casa: Path, lavoro: Lavoro) -> None:
    from officina import forziere

    lavoro.fase = "archivio"
    cassa = forziere.per(archivio.dove)
    if cassa.acceso:
        verso = casa / "archivio" / cassa.file.name
        _copia_controllata(cassa.file, verso)
        _metti_al_posto(verso)
        (casa / "archivio" / f"{archivio.dove.nome}.sqlite").unlink(missing_ok=True)
        return
    fatta = archivio.copia_adesso("esterna")
    verso = casa / "archivio" / f"{archivio.dove.nome}.sqlite"
    _copia_controllata(fatta.percorso, verso)
    _metti_al_posto(verso)


def _i_file(archivio) -> list[tuple[str, str]]:
    with archivio.lettura() as connessione:
        righe = tutti(connessione, """
            SELECT p.percorso, f.impronta
              FROM percorsi AS p JOIN file_media AS f ON f.id = p.file_id
             WHERE p.presente = 1
             ORDER BY p.id
        """)
    return [(riga["percorso"], riga["impronta"]) for riga in righe]


def _una_foto(sorgente: Path, attesa: str, verso: Path, voce: dict | None,
              lavoro: Lavoro) -> dict | None:
    try:
        stato = os.stat(sorgente)
    except OSError:
        lavoro.mancanti += 1
        return voce
    if (voce and voce.get("dimensione") == stato.st_size and voce.get("ns") == stato.st_mtime_ns
            and voce.get("impronta") == attesa and verso.is_file()
            and verso.stat().st_size == stato.st_size):
        lavoro.uguali += 1
        return voce
    letto = _copia_controllata(sorgente, verso)
    if letto != attesa and verso.is_file() and voce and voce.get("impronta") == attesa:
        _scarta(verso)
        lavoro.diversi += 1
        lavoro.sbaglio(f"«{sorgente.name}» è diverso da come era quando l'hai importato: "
                       "tengo la copia vecchia, che è quella giusta.")
        return voce
    _metti_al_posto(verso)
    if letto != attesa:
        lavoro.diversi += 1
        lavoro.sbaglio(f"«{sorgente.name}» è diverso da come era quando l'hai importato.")
    lavoro.copiati += 1
    return {"dimensione": stato.st_size, "ns": stato.st_mtime_ns, "impronta": letto}


def _copia_le_foto(archivio, casa: Path, lavoro: Lavoro) -> None:
    lavoro.fase = "foto"
    elenco = _leggi_l_elenco(casa)
    file = _i_file(archivio)
    lavoro.totale = len(file)
    foto = casa / "foto"
    for numero, (percorso, attesa) in enumerate(file, start=1):
        chiave = relativo(percorso).as_posix()
        try:
            nuova = _una_foto(Path(percorso), attesa, foto / chiave, elenco.get(chiave), lavoro)
        except ErroreOfficina as errore:
            lavoro.sbaglio(errore.messaggio)
            nuova = elenco.get(chiave)
        except OSError as guasto:
            lavoro.sbaglio(f"«{Path(percorso).name}»: {guasto.strerror or guasto}")
            nuova = elenco.get(chiave)
        if nuova is not None:
            elenco[chiave] = nuova
        lavoro.fatti = numero
        if numero % SALVA_OGNI == 0:
            _scrivi_json(casa / ELENCO, elenco)
    _scrivi_json(casa / ELENCO, elenco)


def _ricontrolla(casa: Path, lavoro: Lavoro) -> None:
    lavoro.fase = "ricontrollo"
    elenco = _leggi_l_elenco(casa)
    lavoro.totale, lavoro.fatti = len(elenco), 0
    for chiave, voce in list(elenco.items()):
        file = casa / "foto" / chiave
        try:
            giusto = file.is_file() and _impronta(file) == voce.get("impronta")
        except OSError:
            giusto = False
        if not giusto:
            lavoro.rovinati_nella_copia += 1
            lavoro.sbaglio(f"Nella copia «{Path(chiave).name}» non è più uguale: la rifaccio "
                           "la prossima volta.")
            elenco.pop(chiave)
        lavoro.fatti += 1
    _scrivi_json(casa / ELENCO, elenco)


def _fai(archivio, destinazione: Path, anche_il_ricontrollo: bool, lavoro: Lavoro) -> None:
    casa = dove_va(destinazione, archivio.dove.nome)
    try:
        casa.mkdir(parents=True, exist_ok=True)
        _copia_l_archivio(archivio, casa, lavoro)
        _copia_le_foto(archivio, casa, lavoro)
        if anche_il_ricontrollo:
            _ricontrolla(casa, lavoro)
        lavoro.fase = "fatto"
        _scrivi_json(casa / ULTIMA, {
            "quando": adesso(), "copiati": lavoro.copiati, "uguali": lavoro.uguali,
            "mancanti": lavoro.mancanti, "diversi": lavoro.diversi,
            "rovinati_nella_copia": lavoro.rovinati_nella_copia,
            "errori": len(lavoro.errori), "ricontrollata": anche_il_ricontrollo})
        registro.evento("riserva.fatta", copiati=lavoro.copiati, uguali=lavoro.uguali,
                        errori=len(lavoro.errori))
    except _Fermato:
        lavoro.fermato = True
        lavoro.fase = "fermata"
    except ErroreOfficina as errore:
        lavoro.sbaglio(errore.messaggio)
        lavoro.fase = "rotta"
    except OSError as guasto:
        lavoro.sbaglio(f"Il disco della copia non risponde: {guasto.strerror or guasto}")
        lavoro.fase = "rotta"
    except Exception as guasto:
        registro.errore("riserva.rotta", **registro.dove_si_e_rotto(guasto))
        lavoro.sbaglio("Qualcosa non ha funzionato: quello già copiato resta copiato.")
        lavoro.fase = "rotta"
    finally:
        lavoro.finito = True


def parti(archivio, destinazione: Path, anche_il_ricontrollo: bool = False,
          in_sottofondo: bool = True) -> dict:
    global _lavoro, _filo
    with _lucchetto:
        if _lavoro is not None and not _lavoro.finito:
            raise ErroreOfficina(GIA_IN_CORSO)
        _ferma.clear()
        _lavoro = Lavoro()
        lavoro = _lavoro
    if in_sottofondo:
        _filo = threading.Thread(target=_fai, name="copia-esterna", daemon=True,
                                 args=(archivio, destinazione, anche_il_ricontrollo, lavoro))
        _filo.start()
    else:
        _fai(archivio, destinazione, anche_il_ricontrollo, lavoro)
    return lavoro.a_parole()
