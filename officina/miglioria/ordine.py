from __future__ import annotations

import json
import math
import sqlite3
import time
from typing import Callable

from officina import registro
from officina.archivio.database import tutti
from officina.importazione import gruppi
from officina.miglioria import coda, previsione

ATTESA_MASSIMA = 2 * 3600.0


def in_coda(connessione: sqlite3.Connection, salta=()) -> list:
    return tutti(connessione,
                 "SELECT m.*, f.genere AS genere_del_file, f.genere, f.formato, "
                 "f.dimensione, f.larghezza, f.altezza, f.durata_ms, f.fps "
                 "FROM migliorie m JOIN file_media f ON f.id = m.file_id "
                 "JOIN scatti s ON s.id = f.scatto_id WHERE m.stato = ? "
                 "AND m.id NOT IN (SELECT value FROM json_each(?))"
                 + gruppi.clausola(connessione, "miglioramento")
                 + " ORDER BY m.id",
                 coda.IN_CODA, json.dumps(sorted({int(numero) for numero in salta})))


def peso(dati: dict) -> float:
    arrivo = dati.get("arrivo") or dati.get("megapixel") or dati.get("mb") or 1.0
    quadri = (dati.get("fotogrammi") or 1.0) + (dati.get("fluidi") or 0.0)
    return float(arrivo) * float(quadri)


class Ordine:

    def __init__(self, orologio: Callable[[], float] = time.monotonic,
                 attesa_massima: float = ATTESA_MASSIMA) -> None:
        self._orologio = orologio
        self.attesa_massima = float(attesa_massima)
        self._vista: dict[int, float] = {}
        self.ultimo: str | None = None

    def _da_quanto(self, righe: list, ora: float) -> dict[int, float]:
        ci_sono = {int(riga["id"]) for riga in righe}
        self._vista = {numero: quando for numero, quando in self._vista.items()
                       if numero in ci_sono}
        for numero in ci_sono:
            self._vista.setdefault(numero, ora)
        return {numero: ora - quando for numero, quando in self._vista.items()}

    def in_fila(self, righe: list, modello_di: Callable[[object], str],
                stima_di: Callable[[object], tuple[float | None, float]]) -> list:
        if len(righe) <= 1:
            self._da_quanto(righe, self._orologio())
            return list(righe)
        attese = self._da_quanto(righe, self._orologio())
        vecchie = sorted((riga for riga in righe
                          if attese[int(riga["id"])] >= self.attesa_massima),
                         key=lambda riga: int(riga["id"]))
        resto = [riga for riga in righe if attese[int(riga["id"])] < self.attesa_massima]
        stime = {int(riga["id"]): stima_di(riga) for riga in resto}
        modelli = {int(riga["id"]): modello_di(riga) for riga in resto}
        tutte_note = {modello: all(stime[numero][0] is not None
                                   for numero, suo in modelli.items() if suo == modello)
                      for modello in set(modelli.values())}

        def misura(riga) -> float:
            numero = int(riga["id"])
            secondi, suo_peso = stime[numero]
            return float(secondi) if tutte_note[modelli[numero]] else suo_peso

        gruppi_: dict[str, list] = {}
        for riga in resto:
            gruppi_.setdefault(modelli[int(riga["id"])], []).append(riga)
        for gruppo in gruppi_.values():
            gruppo.sort(key=lambda riga: (misura(riga), int(riga["id"])))

        def costo(modello: str) -> tuple:
            primo = gruppi_[modello][0]
            return (modello != self.ultimo, misura(primo) if tutte_note[modello]
                    else math.inf, int(primo["id"]))

        fuori = list(vecchie)
        for modello in sorted(gruppi_, key=costo):
            fuori.extend(gruppi_[modello])
        return fuori


def stimatore(connessione: sqlite3.Connection, versione: str, **fattori):
    imparati: dict = {}

    def stima_di(riga, **altri) -> tuple[float | None, float]:
        dati = previsione.fattori(riga, **fattori, **altri)
        genere = str(dati.get("genere"))
        if genere not in imparati:
            try:
                imparati[genere] = previsione.imparato(connessione, genere, versione)
            except Exception as guasto:
                registro.avviso("miglioria.ordine_senza_stima",
                                **registro.dove_si_e_rotto(guasto))
                imparati[genere] = None
        quale = imparati[genere]
        return (None if quale is None else quale.secondi(dati)), peso(dati)

    return stima_di


__all__ = ["ATTESA_MASSIMA", "Ordine", "in_coda", "peso", "stimatore"]
