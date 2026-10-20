from __future__ import annotations

import threading
import time
from collections import deque
from typing import Callable

from officina import registro
from officina.archivio import accesso
from officina.errori import ErroreOfficina

QUANTE_RIGHE = 60

ATTESA_DOPO_FERMA = 0.5

GUASTO_IMPREVISTO = (
    "Qualcosa è andato storto e non è un caso che avessi "
    "previsto. È un difetto del programma.")


NOMI_NEL_TURNO = {"miglioramento": "il miglioramento", "ritocco": "lo strumento Ritocca",
                  "ritocchi": "la coda del ritocco"}


class TurnoDellaScheda:

    def __init__(self):
        self._cambiato = threading.Condition()
        self._chi: Lavoro | None = None
        self._rinunce: set[str] = set()
        self._in_attesa: set[str] = set()

    @property
    def chi(self) -> Lavoro | None:
        return self._chi

    def prendi(self, lavoro: Lavoro, nome: str) -> bool:
        with self._cambiato:
            self._rinunce.discard(nome)
            if self._chi is not None and lavoro in self._chi.figli:
                return True
            self._in_attesa.add(nome)
            try:
                return self._aspetta(lavoro, nome)
            finally:
                self._in_attesa.discard(nome)

    def _aspetta(self, lavoro: Lavoro, nome: str) -> bool:
        avvisato = False
        while self._chi is not None and self._chi is not lavoro:
            if nome in self._rinunce:
                self._rinunce.discard(nome)
                lavoro.numeri.pop("in_attesa_della_scheda", None)
                return False
            if not avvisato:
                lavoro.numeri["in_attesa_della_scheda"] = self._chi.cosa
                lavoro.di("in attesa della scheda: la sta usando "
                          + NOMI_NEL_TURNO.get(self._chi.cosa, self._chi.cosa))
                avvisato = True
            self._cambiato.wait(0.5)
        self._chi = lavoro
        lavoro.numeri.pop("in_attesa_della_scheda", None)
        if avvisato:
            lavoro.di("la scheda è libera: parto")
        return True

    def prendi_se_libera(self, lavoro: Lavoro) -> bool:
        with self._cambiato:
            if self._chi is lavoro:
                return True
            if self._chi is not None or self._in_attesa:
                return False
            self._chi = lavoro
            return True

    def lascia(self, lavoro: Lavoro) -> None:
        with self._cambiato:
            if self._chi is lavoro:
                self._chi = None
            self._cambiato.notify_all()

    def passa(self, da: Lavoro, a: Lavoro) -> bool:
        with self._cambiato:
            if self._chi is not da:
                return False
            self._chi = a
            self._cambiato.notify_all()
            return True

    def rinuncia(self, nome: str) -> None:
        with self._cambiato:
            self._rinunce.add(nome)
            self._cambiato.notify_all()

    def rinunciano_tutti(self) -> None:
        with self._cambiato:
            self._rinunce.update(self._in_attesa)
            self._cambiato.notify_all()


turno = TurnoDellaScheda()


class Lavoro:

    def __init__(self, cosa: str, quante_righe: int = QUANTE_RIGHE, scheda: bool = False):
        self.cosa = cosa
        self.scheda = scheda
        self.figli: tuple[Lavoro, ...] = ()
        self.righe: deque[str] = deque(maxlen=quante_righe)
        self.numeri: dict = {}
        self.guasto = ""
        self.dettaglio = ""
        self.finito = False
        self._filo: threading.Thread | None = None
        self._lucchetto = threading.Lock()
        self.riflesso: dict | None = None

    @property
    def sta_lavorando(self) -> bool:
        filo_vivo = self._filo is not None and self._filo.is_alive()
        if self.riflesso is not None:
            return bool(self.riflesso.get("sta_lavorando")) or filo_vivo
        return filo_vivo

    def fotografia(self) -> dict:
        return {"sta_lavorando": self.sta_lavorando, "righe": list(self.righe),
                "numeri": dict(self.numeri), "guasto": self.guasto,
                "dettaglio": self.dettaglio, "finito": self.finito}

    def rifletti(self, dati: dict) -> None:
        self.righe.clear()
        self.righe.extend(dati.get("righe", []))
        self.numeri = dict(dati.get("numeri", {}))
        self.guasto = dati.get("guasto", "")
        self.dettaglio = dati.get("dettaglio", "")
        self.finito = bool(dati.get("finito"))
        self.riflesso = dati

    def smetti_di_riflettere(self) -> None:
        if self.riflesso is not None and self.riflesso.get("sta_lavorando"):
            self.finito = True
        self.riflesso = None

    def di(self, riga: str) -> None:
        testo = str(riga).strip()
        if testo:
            self.righe.append(testo)

    def a_che_punto(self, fatti: int, attesi: int, unita: str = "byte") -> None:
        quota = 0
        if attesi > 0:
            quota = min(99, int(fatti * 100 / attesi))
        self.numeri["scaricati"] = fatti
        self.numeri["da_scaricare"] = attesi
        self.numeri["percento"] = quota
        self.numeri["unita"] = unita

    def a_che_punto_a_pezzi(self, fatti: int, attesi: int) -> None:
        self.a_che_punto(fatti, attesi, "pezzi")

    def senza_numeri(self) -> None:
        for chiave in ("scaricati", "da_scaricare", "percento", "unita"):
            self.numeri.pop(chiave, None)

    def parti(self, funzione: Callable[[], None], nome: str = "lavoro") -> bool:
        if accesso.in_prova():
            raise ErroreOfficina(accesso.NELLA_PROVA_NO, codice="nella_prova")
        with self._lucchetto:
            if self.sta_lavorando:
                return False
            self.righe.clear()
            self.numeri.clear()
            self.guasto = ""
            self.dettaglio = ""
            self.finito = False
            self._filo = threading.Thread(target=self._dentro, args=(funzione, nome),
                                          name=nome, daemon=True)
            self._filo.start()
        return True

    def _dentro(self, funzione: Callable[[], None], nome: str = "lavoro") -> None:
        preso = False
        try:
            if self.scheda:
                preso = turno.prendi(self, nome)
                if not preso:
                    self.di("fermato prima di partire: la scheda era occupata")
                    return
            funzione()
        except ErroreOfficina as errore:
            self.guasto = errore.messaggio
            self.dettaglio = getattr(errore, "dettaglio", "") or ""
            registro.errore("lavoro.fallito", motivo=registro.Parola(errore.codice))
        except Exception as errore:
            self.guasto = GUASTO_IMPREVISTO
            self.dettaglio = registro.passi_del_guasto(errore)
            registro.errore("lavoro.rotto", **registro.dove_si_e_rotto(errore))
        finally:
            if preso:
                turno.lascia(self)
            self.finito = True

    def aspetta_che_finisca(self, secondi: float = ATTESA_DOPO_FERMA) -> bool:
        if self.riflesso is not None:
            scadenza = time.monotonic() + secondi
            while self.sta_lavorando and time.monotonic() < scadenza:
                time.sleep(0.05)
            return not self.sta_lavorando
        filo = self._filo
        if filo is None:
            return True
        filo.join(timeout=secondi)
        return not filo.is_alive()

    def come_va(self) -> dict:
        return {
            "cosa": self.cosa,
            "righe": list(self.righe),
            "sta_lavorando": self.sta_lavorando,
            "finito": self.finito and not self.sta_lavorando,
            "guasto": self.guasto,
            "dettaglio": self.dettaglio,
            **self.numeri,
        }


FERMO = {"cosa": "", "righe": [], "sta_lavorando": False, "finito": False,
         "guasto": "", "dettaglio": ""}
