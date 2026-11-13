from __future__ import annotations

import threading
import time

from officina import registro
from officina.errori import ErroreOfficina
from officina.programma import aggiornamenti, carta

OGNI_QUANTO_CONTROLLO = 300

class Aggiornarsi:

    def _guarda_gli_aggiornamenti(self) -> None:
        if self.canale == aggiornamenti.SVILUPPO or self._guarda_gia:
            return
        self._guarda_gia = True
        while not self._sta_chiudendo and not self._spento:
            self._guarda_una_volta()
            fine = time.monotonic() + OGNI_QUANTO_CONTROLLO
            while time.monotonic() < fine and not self._sta_chiudendo and not self._spento:
                time.sleep(1)

    _cercando = threading.Lock()

    def _guarda_una_volta(self) -> None:
        with self._cercando:
            self._guarda_adesso()

    def cerca_gli_aggiornamenti_adesso(self) -> dict:
        if self.canale == aggiornamenti.SVILUPPO:
            raise ErroreOfficina("Questa copia non cerca aggiornamenti.",
                                 codice="aggiornamento_sviluppo")
        if self._cercando.acquire(blocking=False):
            self.aggiornamento_stato["cerco"] = True

            def cerca() -> None:
                try:
                    self._guarda_adesso()
                finally:
                    self.aggiornamento_stato["cerco"] = False
                    self.aggiornamento_stato["cercato_alle"] = time.strftime("%H:%M")
                    self._cercando.release()

            threading.Thread(target=cerca, name="cerca-aggiornamenti", daemon=True).start()
        return self.come_va_l_aggiornamento()

    def _guarda_adesso(self) -> None:
        if self.aggiornamento_stato["fase"] in ("scarico", "installo"):
            return
        try:
            trovato = aggiornamenti.cerca()
            if trovato is None:
                return
            if self.canale != aggiornamenti.BETA:
                self.aggiornamento_trovato = trovato
                if self.aggiornamento_stato["fase"] != "rifiutato":
                    self.aggiornamento_stato["fase"] = "da_chiedere"
                return
            pronto = aggiornamenti.pronto_da_installare()
            if pronto is None or pronto[0].versione != trovato.versione:
                aggiornamenti.scarica(trovato)
            self.aggiornamento_trovato = trovato
            self.aggiornamento_stato["fase"] = "pronto_alla_prossima"
        except ErroreOfficina as errore:
            self.aggiornamento_stato.update(fase="guasto", guasto=errore.messaggio)
        except Exception as guasto:
            registro.errore("programma.aggiornamenti_rotti", **registro.dove_si_e_rotto(guasto))

    def come_va_l_aggiornamento(self) -> dict:
        trovato = self.aggiornamento_trovato
        sospeso = aggiornamenti.in_sospeso()
        return {
            "canale": self.canale,
            "versione_attuale": self.versione,
            "trovato": trovato.come_dati() if trovato else None,
            "in_sospeso": sospeso,
            **self.aggiornamento_stato,
        }

    def aggiorna_adesso(self) -> dict:
        registro.evento("aggiornamento.riavvia_ora",
                        modo=registro.Parola(str(carta.leggi().get("modo") or "nessuno")),
                        col_fisso=getattr(self, "ponte", None) is not None)
        trovato = self.aggiornamento_trovato
        if trovato is None:
            sospeso = aggiornamenti.in_sospeso()
            if not sospeso:
                raise ErroreOfficina("Non c'è nessun aggiornamento da installare.")
            trovato = aggiornamenti.Rilascio(
                **{k: sospeso.get(k) for k in aggiornamenti.Rilascio.__dataclass_fields__})
        pronto = aggiornamenti.pronto_da_installare()
        if pronto is not None and pronto[0].versione == trovato.versione:
            self.aggiornamento_stato["fase"] = "installo"
            self.da_installare_dopo = pronto[1]
            self._sta_chiudendo = True
            threading.Thread(target=self._chiudi_con_calma, kwargs={"senza_chiedere": True},
                             name="aggiornamento", daemon=True).start()
            return self.come_va_l_aggiornamento()
        self.aggiornamento_stato.update(fase="scarico", fatti=0, totale=trovato.peso)

        def al_passo(fatti: int, totale: int) -> None:
            self.aggiornamento_stato.update(fatti=fatti, totale=totale)

        def in_sottofondo() -> None:
            try:
                file = aggiornamenti.scarica(trovato, al_passo=al_passo)
            except ErroreOfficina as errore:
                self.aggiornamento_stato.update(fase="guasto", guasto=errore.messaggio)
                return
            self.aggiornamento_stato["fase"] = "installo"
            self.da_installare_dopo = file
            self._sta_chiudendo = True
            self._chiudi_con_calma(senza_chiedere=True)

        threading.Thread(target=in_sottofondo, name="aggiornamento", daemon=True).start()
        return self.come_va_l_aggiornamento()
