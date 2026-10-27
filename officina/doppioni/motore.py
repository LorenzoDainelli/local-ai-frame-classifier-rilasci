from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path
from dataclasses import dataclass, field
from typing import Callable

from officina import registro
from officina.insiemi import InsiemiUniti
from officina.archivio.accesso import Archivio
from officina.doppioni import occhio
from officina.errori import DaRifare, ErroreOfficina, FileNonLeggibile
from officina.modello import file_media
from officina.sicuro import dall_archivio

QUANTE_ALLA_VOLTA = 200

NON_SI_E_POTUTA = ""

QUANTI_PEZZI = occhio.QUASI_UGUALI + 1


@dataclass
class Avanzamento:
    totale: int = 0
    guardate: int = 0
    saltate: int = 0
    ms_per_immagine: float | None = None
    motivi_saltate: dict[str, int] = field(default_factory=dict)

    @property
    def resta(self) -> int:
        return max(self.totale - self.guardate - self.saltate, 0)

    @property
    def percentuale(self) -> float:
        if not self.totale:
            return 100.0
        fatte = self.guardate + self.saltate
        return min(99.0, fatte * 100.0 / self.totale) if self.resta else 100.0

    @property
    def secondi_rimasti(self) -> float | None:
        if self.ms_per_immagine is None:
            return None
        return self.resta * self.ms_per_immagine / 1000.0


class Passata:

    def __init__(self, archivio: Archivio):
        self.archivio = archivio
        self._fermare = threading.Event()
        self._misure: list[float] = []

    def ferma(self) -> None:
        self._fermare.set()

    def fermata(self) -> bool:
        return self._fermare.is_set()

    def quante_mancano(self) -> int:
        with self.archivio.lettura() as connessione:
            riga = connessione.execute(
                "SELECT COUNT(*) AS quante FROM file_media "
                "WHERE genere = 'immagine' AND impronta_occhio IS NULL"
            ).fetchone()
        return int(riga["quante"])

    def esegui(self, al_passo: Callable[[Avanzamento], None] | None = None,
               quante_al_massimo: int | None = None) -> Avanzamento:
        avanzamento = Avanzamento(totale=self.quante_mancano())
        if quante_al_massimo is not None:
            avanzamento.totale = min(avanzamento.totale, quante_al_massimo)

        dopo = 0
        while not self.fermata() and avanzamento.resta > 0:
            righe = self._prossime(min(QUANTE_ALLA_VOLTA, avanzamento.resta), dopo)
            if not righe:
                break
            dopo = righe[-1]["id"]
            for riga in righe:
                if self.fermata():
                    break
                self._una(riga, avanzamento)
                if al_passo is not None:
                    al_passo(avanzamento)
        return avanzamento

    def _prossime(self, quante: int, dopo: int = 0) -> list[sqlite3.Row]:
        with self.archivio.lettura() as connessione:
            return list(connessione.execute(
                "SELECT f.id, f.impronta, (SELECT MIN(p.percorso) FROM percorsi AS p "
                "WHERE p.file_id = f.id AND p.presente = 1) AS percorso "
                "FROM file_media AS f "
                "WHERE f.genere = 'immagine' AND f.impronta_occhio IS NULL AND f.id > ? "
                "ORDER BY f.id LIMIT ?",
                (dopo, quante),
            ))

    def _rimanda(self, codice: str, avanzamento: Avanzamento) -> None:
        avanzamento.saltate += 1
        avanzamento.motivi_saltate[codice] = avanzamento.motivi_saltate.get(codice, 0) + 1

    def _una(self, riga: sqlite3.Row, avanzamento: Avanzamento) -> None:
        principio = time.monotonic()
        try:
            with self.archivio.lettura() as connessione:
                percorso = file_media.da_guardare(connessione, riga["id"])
        except DaRifare as errore:
            self._rimanda(errore.codice, avanzamento)
            return
        except FileNonLeggibile as errore:
            self._non_si_e_potuta(riga["id"], registro.Parola(errore.codice), avanzamento)
            return
        if percorso is None:
            if riga["percorso"] is None:
                return
            percorso = Path(riga["percorso"])
        try:
            with dall_archivio.attento(percorso):
                segno = occhio.del_percorso(percorso)
        except DaRifare as errore:
            self._rimanda(errore.codice, avanzamento)
            return
        except (FileNonLeggibile, ErroreOfficina, OSError, ValueError) as errore:
            self._non_si_e_potuta(riga["id"], registro.tipo_di(errore), avanzamento)
            return
        self._scrivi(riga["id"], segno)
        avanzamento.guardate += 1
        self._segna_tempo(time.monotonic() - principio)
        avanzamento.ms_per_immagine = self._media_misurata()

    def _non_si_e_potuta(self, file_id: int, motivo, avanzamento: Avanzamento) -> None:
        self._scrivi(file_id, NON_SI_E_POTUTA)
        avanzamento.saltate += 1
        avanzamento.motivi_saltate[motivo] = avanzamento.motivi_saltate.get(motivo, 0) + 1
        registro.avviso("doppioni_immagine_non_guardata", file_id=file_id, motivo=motivo)

    def _scrivi(self, file_id: int, segno: str) -> None:
        with self.archivio.scrittura() as connessione:
            connessione.execute(
                "UPDATE file_media SET impronta_occhio = ? WHERE id = ?",
                (segno, file_id))

    def _segna_tempo(self, secondi: float) -> None:
        self._misure.append(secondi)
        self._misure = self._misure[-50:]

    def _media_misurata(self) -> float | None:
        if not self._misure:
            return None
        return sum(self._misure) / len(self._misure) * 1000.0


@dataclass
class Gruppo:

    file_id: list[int]
    distanza_massima: int

    @property
    def quante(self) -> int:
        return len(self.file_id)

    @property
    def identiche(self) -> bool:
        return self.distanza_massima == 0


def gruppi(archivio: Archivio, quanto_lontano: int = occhio.QUASI_UGUALI
           ) -> list[Gruppo]:
    with archivio.lettura() as connessione:
        righe = list(connessione.execute(
            "SELECT id, impronta_occhio, dimensione FROM file_media "
            "WHERE impronta_occhio IS NOT NULL AND impronta_occhio != ''"
        ))

    numeri = {int(r["id"]): occhio.a_numero(str(r["impronta_occhio"]))
              for r in righe}
    pesi = {int(r["id"]): int(r["dimensione"] or 0) for r in righe}

    vicini = _coppie_possibili(numeri)

    insieme = InsiemiUniti()
    distanze: dict[int, int] = {}
    for uno, altro in vicini:
        quanto = occhio.distanza_fra_numeri(numeri[uno], numeri[altro])
        if quanto > quanto_lontano:
            continue
        insieme.unisci(uno, altro)
        distanze[uno] = max(distanze.get(uno, 0), quanto)
        distanze[altro] = max(distanze.get(altro, 0), quanto)

    fatti: list[Gruppo] = []
    for membri in insieme.gruppi():
        ordinati = sorted(membri, key=lambda quale: (-pesi[quale], quale))
        fatti.append(Gruppo(
            file_id=ordinati,
            distanza_massima=max(distanze.get(quale, 0) for quale in membri),
        ))
    fatti.sort(key=lambda g: (-g.quante, g.distanza_massima, g.file_id[0]))
    return fatti


def _tagli() -> list[tuple[int, int]]:
    fatti: list[tuple[int, int]] = []
    principio = 0
    for quanti_ne_restano in range(QUANTI_PEZZI, 0, -1):
        lungo = (occhio.QUANTI_BIT - principio) // quanti_ne_restano
        fatti.append((principio, lungo))
        principio += lungo
    return fatti


def _coppie_possibili(segni: dict[int, str] | dict[int, int]
                      ) -> set[tuple[int, int]]:
    per_pezzo: dict[tuple[int, int], list[int]] = {}
    tagli = [(occhio.QUANTI_BIT - da - lungo, (1 << lungo) - 1)
             for da, lungo in _tagli()]
    for quale, segno in segni.items():
        numero = segno if isinstance(segno, int) else occhio.a_numero(segno)
        for pezzo, (scorri, maschera) in enumerate(tagli):
            chiave = (pezzo, (numero >> scorri) & maschera)
            per_pezzo.setdefault(chiave, []).append(quale)

    coppie: set[tuple[int, int]] = set()
    for insieme in per_pezzo.values():
        if len(insieme) < 2:
            continue
        if len(insieme) > 2000:
            continue
        for posto, uno in enumerate(insieme):
            for altro in insieme[posto + 1:]:
                coppie.add((uno, altro) if uno < altro else (altro, uno))
    return coppie
