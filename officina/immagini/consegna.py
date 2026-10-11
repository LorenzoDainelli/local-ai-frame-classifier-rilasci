from __future__ import annotations

import asyncio
import contextvars
import io
import threading
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from pathlib import Path

from PIL import Image, features

from officina.immagini import lettura

QUALITA_AVIF = 82
VELOCITA_AVIF = 8
QUALITA_JPEG = 92
QUALITA_PIENA = 95

LATO_PER_GUARDARE = 2560
INSIEME_AL_MASSIMO = 3

FILMATI_INSIEME = 2
PESO_IN_MEMORIA = 96 * 1024 * 1024
ATTESA_FRA_I_CONTROLLI = 0.25

a_turno = threading.BoundedSemaphore(INSIEME_AL_MASSIMO)

cantiere = ThreadPoolExecutor(INSIEME_AL_MASSIMO, thread_name_prefix="immagini")
cantiere_dei_filmati = ThreadPoolExecutor(FILMATI_INSIEME, thread_name_prefix="fotogrammi")


class InMemoria:

    def __init__(self, quanto: int = PESO_IN_MEMORIA):
        self._quanto = quanto
        self._dati: OrderedDict[str, tuple[bytes, str]] = OrderedDict()
        self._peso = 0
        self._lucchetto = threading.Lock()

    def prendi(self, chiave: str) -> tuple[bytes, str] | None:
        with self._lucchetto:
            trovato = self._dati.get(chiave)
            if trovato is not None:
                self._dati.move_to_end(chiave)
            return trovato

    def metti(self, chiave: str, dati: bytes, tipo: str) -> None:
        if len(dati) > self._quanto:
            return
        with self._lucchetto:
            vecchio = self._dati.pop(chiave, None)
            if vecchio is not None:
                self._peso -= len(vecchio[0])
            self._dati[chiave] = (dati, tipo)
            self._peso += len(dati)
            while self._peso > self._quanto:
                _, (tolto, _) = self._dati.popitem(last=False)
                self._peso -= len(tolto)

    def svuota(self) -> None:
        with self._lucchetto:
            self._dati.clear()
            self._peso = 0


gia_pronte = InMemoria()


def _senza_rumore(futuro) -> None:
    if not futuro.cancelled():
        futuro.exception()


async def subito(funzione, *argomenti):
    return await asyncio.to_thread(funzione, *argomenti)


async def a_parte(richiesta, funzione, *argomenti, filmato: bool = False):
    abbandonata = threading.Event()
    contesto = contextvars.copy_context()

    def lavoro():
        if abbandonata.is_set():
            return None
        return contesto.run(funzione, *argomenti)

    futuro = asyncio.get_running_loop().run_in_executor(
        cantiere_dei_filmati if filmato else cantiere, lavoro)
    futuro.add_done_callback(_senza_rumore)
    while True:
        finiti, _ = await asyncio.wait({futuro}, timeout=ATTESA_FRA_I_CONTROLLI)
        if finiti:
            return futuro.result()
        if richiesta is not None and await richiesta.is_disconnected():
            abbandonata.set()
            return None


@lru_cache(maxsize=1)
def capacita() -> dict:
    return {
        "avif": bool(features.check("avif")),
        "webp": bool(features.check("webp")),
        "heic": lettura.SA_LEGGERE_HEIC,
    }


def formato_scelto() -> tuple[str, str]:
    if capacita()["avif"]:
        return "AVIF", "image/avif"
    return "JPEG", "image/jpeg"


def da_immagine(immagine: Image.Image, formato: str | None = None,
                qualita: int = QUALITA_JPEG) -> tuple[bytes, str]:
    formato_pillow, tipo = formato_scelto() if formato is None else (formato, "image/jpeg")
    appoggio = io.BytesIO()
    if immagine.mode not in ("RGB", "L"):
        immagine = immagine.convert("RGB")
    if formato_pillow == "AVIF":
        immagine.save(appoggio, "AVIF", quality=QUALITA_AVIF, speed=VELOCITA_AVIF)
    else:
        immagine.save(appoggio, "JPEG", quality=qualita, optimize=True,
                      progressive=True)
    return appoggio.getvalue(), tipo


def lato_per_guardare(lato: int | None) -> int:
    return min(lato or LATO_PER_GUARDARE, LATO_PER_GUARDARE)


def a_piena_misura(percorso: Path) -> tuple[bytes, str]:
    return da_immagine(lettura.copia_di_lavoro(percorso, None), "JPEG", QUALITA_PIENA)


def per_browser(percorso: Path, lato_massimo: int | None = None) -> tuple[bytes, str]:
    immagine = lettura.copia_di_lavoro(percorso, lato_massimo)
    return da_immagine(immagine)
