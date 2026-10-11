from __future__ import annotations

import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path


VOCABOLARIO = frozenset({
    "ok", "fallito", "saltato", "annullato", "ripreso", "in_corso", "finito",
    "gia_presente", "nuovo", "aggiornato", "invariato", "assente",
    "immagine", "video", "foto", "live", "sconosciuto",
    "heic", "heif", "jpeg", "png", "tiff", "webp", "avif", "gif", "bmp", "dng",
    "mov", "mp4", "m4v", "avi", "mkv",
    "exif", "xmp", "quicktime", "manuale", "dedotta", "nessuna", "contenuto", "nome", "file",
    "istante", "identificatore",
    "corrotto", "troppo_piccolo", "estensione_bugiarda", "vuoto", "permesso_negato",
    "non_supportato", "fuori_archivio", "duplicato",
    "archivio", "importazione", "miniature", "web", "prove", "finto", "copie",
    "gpu", "processore",
})


class Parola(str):

    __slots__ = ()


_CASA_MIA = Path(__file__).resolve().parent

_FORMA_DI_UN_NOME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,60}$")


def tipo_di(errore: BaseException) -> Parola:
    return Parola(type(errore).__name__)


def dove_si_e_rotto(errore: BaseException) -> dict:
    nostro = _CASA_MIA
    scelto = None
    passo = errore.__traceback__
    while passo is not None:
        dove = Path(passo.tb_frame.f_code.co_filename)
        if nostro is None or nostro in dove.parents:
            scelto = passo
        elif scelto is None:
            scelto = passo
        passo = passo.tb_next
    if scelto is None:
        return {"guasto": tipo_di(errore)}
    return {
        "guasto": tipo_di(errore),
        "dove": Parola(Path(scelto.tb_frame.f_code.co_filename).stem),
        "riga": scelto.tb_lineno,
    }


def dettaglio_tecnico(errore: BaseException) -> str:
    dove = dove_si_e_rotto(errore)
    parti = [str(_pulisci(dove["guasto"]))]
    if "dove" in dove:
        parti.append(f"in {_pulisci(dove['dove'])}, riga {dove['riga']}")
    return "Dettaglio tecnico: " + " ".join(parti)


def passi_del_guasto(errore: BaseException) -> str:
    righe = [f"Guasto: {_pulisci(tipo_di(errore))}"]
    giro = errore
    visti = set()
    while giro is not None and id(giro) not in visti:
        visti.add(id(giro))
        if giro is not errore:
            righe.append(f"Causato da: {_pulisci(tipo_di(giro))}")
        passo = giro.__traceback__
        while passo is not None:
            codice = passo.tb_frame.f_code
            nostro = _CASA_MIA is not None and _CASA_MIA in Path(codice.co_filename).parents
            righe.append(f"  {'' if nostro else '(libreria) '}"
                         f"{_pulisci(Parola(Path(codice.co_filename).stem))}"
                         f" · {_pulisci(Parola(codice.co_name))} · riga {passo.tb_lineno}")
            passo = passo.tb_next
        giro = giro.__cause__ or giro.__context__
    return "\n".join(righe)


def _pulisci(valore: object) -> object:
    if isinstance(valore, bool):
        return "si" if valore else "no"
    if isinstance(valore, (int, float)):
        return valore
    if valore is None:
        return "-"
    if isinstance(valore, Parola):
        return valore if _FORMA_DI_UN_NOME.match(valore) else "<omesso>"
    if isinstance(valore, str) and valore in VOCABOLARIO:
        return valore
    return "<omesso>"


class Registro:

    GIORNI_CONSERVATI = 30

    def __init__(self, cartella: Path | None):
        self.cartella = cartella
        self._lucchetto = threading.Lock()
        self._sul_terminale = os.environ.get("OFFICINA_REGISTRO_A_SCHERMO") == "1"
        if self.cartella:
            self.cartella.mkdir(parents=True, exist_ok=True)
            self._pota()

    def _percorso_oggi(self) -> Path | None:
        if not self.cartella:
            return None
        giorno = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return self.cartella / f"{giorno}.registro"

    def _pota(self) -> None:
        try:
            file = sorted(self.cartella.glob("*.registro"))
            for vecchio in file[:-self.GIORNI_CONSERVATI]:
                vecchio.unlink(missing_ok=True)
        except OSError:
            pass

    def evento(self, codice: str, livello: str = "info", **dati: object) -> None:
        istante = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        coppie = " ".join(f"{c}={_pulisci(v)}" for c, v in sorted(dati.items()))
        riga = f"{istante} {livello.upper():<7} {codice} {coppie}".rstrip()

        if self._sul_terminale:
            print(riga, flush=True)

        percorso = self._percorso_oggi()
        if not percorso:
            return
        try:
            with self._lucchetto:
                with open(percorso, "a", encoding="utf-8") as f:
                    f.write(riga + "\n")
        except OSError:
            pass

    def avviso(self, codice: str, **dati: object) -> None:
        self.evento(codice, livello="avviso", **dati)

    def errore(self, codice: str, **dati: object) -> None:
        self.evento(codice, livello="errore", **dati)


MUTO = Registro(None)

_attivo: Registro = MUTO


def imposta(registro: Registro) -> None:
    global _attivo
    _attivo = registro


def attivo() -> Registro:
    return _attivo


def evento(codice: str, **dati: object) -> None:
    _attivo.evento(codice, **dati)


def avviso(codice: str, **dati: object) -> None:
    _attivo.avviso(codice, **dati)


def errore(codice: str, **dati: object) -> None:
    _attivo.errore(codice, **dati)
