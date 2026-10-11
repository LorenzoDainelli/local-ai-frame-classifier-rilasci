from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from officina.descrittori import torcia
from officina.errori import ErroreOfficina
from officina.parole import SCHEDA, in_casa
from officina import istruzioni

QUANTI_MODI = 3

LUNGHEZZA_MASSIMA = 120


class ModelloNonInCasa(ErroreOfficina):
    codice = "modello_lingua_non_scaricato"


@dataclass
class Riformulazione:

    modi: list[str] = field(default_factory=list)
    da_dove: str = "forme fisse"
    perche_no: str = ""

    @property
    def dal_modello(self) -> bool:
        return self.da_dove == "modello"


def forme_fisse(frase: str) -> Riformulazione:
    pulita = " ".join((frase or "").split())
    if not pulita:
        return Riformulazione()
    return Riformulazione(modi=[pulita, f"una foto di {pulita}"])


ISTRUZIONI = (
    "Sei dentro un programma di fotografie che cerca le immagini per "
    "somiglianza. Ricevi una richiesta in italiano e rispondi con tre righe, "
    "e nient'altro:\n"
    "1) la richiesta tradotta in inglese;\n"
    "2) un altro modo di dirla in inglese, come si descrive una fotografia;\n"
    "3) un terzo modo, più generico.\n"
    "Ogni riga è corta, minuscola, senza virgolette, senza numeri davanti e "
    "senza spiegazioni. Se la richiesta contiene un nome proprio, lascialo "
    "com'è."
)


class Riformulatore:

    scheda = SCHEDA

    def __init__(self, cartella_modelli: Path):
        self.cartella = Path(cartella_modelli) / SCHEDA.nome
        self._modello = None
        self._parolaio = None
        self._macchina = torcia.macchina()


    def apri(self) -> "Riformulatore":
        if self._modello is not None:
            return self
        if not in_casa(self.cartella.parent):
            raise ModelloNonInCasa(
                f"«{SCHEDA.titolo}» non è ancora in casa. Si scarica una "
                "volta sola (regola 74):\n"
                f"{istruzioni.modello(SCHEDA.nome)}\n"
                "Senza, la ricerca a parole funziona lo stesso: la frase va "
                "diritta al modello che capisce le parole."
            )

        from officina.parole.lettore import carica

        self._parolaio, self._modello = carica(self.cartella, self._macchina)
        return self

    def chiudi(self) -> None:
        self._modello = None
        self._parolaio = None
        torcia.libera()

    def __enter__(self) -> "Riformulatore":
        return self.apri()

    def __exit__(self, *_) -> None:
        self.chiudi()

    def dove_gira(self) -> str:
        return self._macchina.a_parole()


    def riformula(self, frase: str) -> Riformulazione:
        fisse = forme_fisse(frase)
        if not fisse.modi:
            return fisse
        try:
            grezzo = self._chiedi(fisse.modi[0])
        except Exception as errore:
            fisse.perche_no = _in_due_parole(errore)
            return fisse

        modi = _tieni_le_didascalie(grezzo, gia=fisse.modi[0])
        if not modi:
            fisse.perche_no = "il modello ha risposto qualcosa che non era una domanda"
            return fisse
        return Riformulazione(modi=[fisse.modi[0]] + modi, da_dove="modello")

    def _chiedi(self, frase: str) -> str:
        from officina.parole.lettore import chiedi

        self.apri()
        discorso = [{"role": "system", "content": ISTRUZIONI},
                    {"role": "user", "content": frase}]
        return chiedi(self._parolaio, self._modello, discorso, gettoni_nuovi=120)


VIA_LE_RIFLESSIONI = re.compile(r"<think>.*?</think>", re.DOTALL)
NUMERO_DAVANTI = re.compile(r"^\s*(?:[-*·]|\d+[.)])\s*")


def _tieni_le_didascalie(grezzo: str, gia: str) -> list[str]:
    testo = VIA_LE_RIFLESSIONI.sub(" ", grezzo or "")
    testo = testo.replace("</think>", " ")
    fuori: list[str] = []
    visti = {gia.casefold()}
    for riga in testo.splitlines():
        pulita = NUMERO_DAVANTI.sub("", riga).strip().strip('"«».')
        pulita = " ".join(pulita.split())
        if not pulita or len(pulita) > LUNGHEZZA_MASSIMA:
            continue
        if ":" in pulita or pulita.casefold().startswith(("ecco", "here", "sure")):
            continue
        if pulita.casefold() in visti:
            continue
        visti.add(pulita.casefold())
        fuori.append(pulita)
        if len(fuori) >= QUANTI_MODI:
            break
    return fuori


def _in_due_parole(errore: Exception) -> str:
    if isinstance(errore, ModelloNonInCasa):
        return "il modello linguistico non è in casa"
    if getattr(errore, "codice", "") == "parole_serve_la_scheda":
        return "il modello linguistico vuole una scheda video NVIDIA"
    if isinstance(errore, ImportError):
        return "mancano le librerie dei modelli"
    if "memory" in str(type(errore)).lower() or "OutOfMemory" in type(errore).__name__:
        return "non c'è abbastanza memoria per il modello linguistico"
    return "il modello linguistico non ha risposto"
