from __future__ import annotations

import threading

from officina import registro
from officina.errori import ErroreOfficina
from officina.programma import (carta)

SIGILLO_DEL_FISSO = "fisso"


class ColFisso:

    def scegli_lo_schermo(self) -> None:
        carta.aggiorna(modo="schermo")
        registro.evento("programma.fa_da_schermo")

    def lascia_lo_schermo(self) -> None:
        carta.aggiorna(modo=None)
        registro.evento("programma.lascia_lo_schermo")

    def riabbina(self) -> None:
        from officina.schermo import collega

        collega.dimentica_il_fisso()

    def cerca_il_fisso(self) -> dict:
        from officina.schermo import collega

        trovati = []
        for voce in collega.cerca():
            try:
                chi = collega.com_e(voce["indirizzo"], voce["porta"], voce["impronta"])
            except ErroreOfficina:
                continue
            trovati.append({**voce, "password": bool(chi.get("password")),
                            "aperta": bool(chi.get("aperta"))})
        return {"fissi": trovati}

    def com_e_il_fisso(self) -> dict:
        from officina.schermo import collega

        fisso = collega.fisso_abbinato()
        if fisso is None:
            return {"trovato": False}
        try:
            fisso = collega.ritrova(fisso)
            from officina.programma import sigillo

            return {"trovato": True, "nome": fisso.nome,
                    "password": collega.serve_la_password(fisso),
                    "sigillo": sigillo.modo(SIGILLO_DEL_FISSO)}
        except ErroreOfficina as errore:
            return {"trovato": False, "nome": fisso.nome, "perche": errore.messaggio}

    def abbina_il_fisso(self, indirizzo: str, porta, codice: str, password: str) -> dict:
        from officina.schermo import collega

        if str(porta or "").strip():
            try:
                numero = int(porta)
            except (TypeError, ValueError):
                raise ErroreOfficina("Il fisso scelto non ha una porta valida.") from None
            indirizzo = str(indirizzo).strip()
        else:
            indirizzo, numero = collega.leggi_l_indirizzo(indirizzo)
        fisso = collega.abbina(indirizzo, numero, codice)
        return self._collegati(fisso, password)

    def entra_nel_fisso(self, password: str) -> dict:
        from officina.schermo import collega

        fisso = collega.fisso_abbinato()
        if fisso is None:
            raise ErroreOfficina("Questo portatile non è ancora abbinato al fisso.")
        return self._collegati(collega.ritrova(fisso), password)

    def entra_nel_fisso_con_windows(self) -> dict:
        from officina.programma import sigillo

        password = sigillo.apri(SIGILLO_DEL_FISSO)
        self._entrato_con_windows = True
        try:
            return self.entra_nel_fisso(password)
        except ErroreOfficina as errore:
            from officina.schermo.porta import NON_TI_FA_ENTRARE

            if errore.messaggio == NON_TI_FA_ENTRARE:
                sigillo.togli(SIGILLO_DEL_FISSO)
            raise
        finally:
            self._entrato_con_windows = False

    def _lega_il_fisso_a_windows(self, password: str) -> None:
        from officina.programma import sigillo

        try:
            if sigillo.come_si_puo() is None:
                return
            if getattr(self, "_entrato_con_windows", False):
                return
            sigillo.sigilla(SIGILLO_DEL_FISSO, password)
        except ErroreOfficina as errore:
            registro.avviso("schermo.sigillo_non_fatto", codice=registro.Parola(errore.codice))
        except Exception as guasto:
            registro.errore("schermo.sigillo_rotto", **registro.dove_si_e_rotto(guasto))

    def _collegati(self, fisso, password: str) -> dict:
        from officina.schermo import collega

        sessione = collega.entra(fisso, password or "")
        if password:
            self._lega_il_fisso_a_windows(password)
        if self.ponte is not None:
            self.ponte.ferma()
        self.ponte = collega.Ponte(fisso, sessione, password=password or "",
                                   quando_aggiorna=self._mostra_l_aggiornamento_del_fisso)
        self.ponte.parti()
        self.apertura = {"titolo": f"Mi collego a {fisso.nome}",
                         "detto": "Tutto quello che passa è cifrato."}
        self.fase_apertura = 2
        indirizzo = self.ponte.indirizzo
        threading.Thread(target=self._mostra_la_principale, args=(indirizzo,),
                         name="schermo", daemon=True).start()
        return {"stato": {"passo": "apertura", "versione": self.versione, **self.apertura}}

    def _mostra_l_aggiornamento_del_fisso(self) -> None:
        ponte, finestra = self.ponte, self.principale
        if ponte is None or finestra is None:
            return
        try:
            finestra.load_url(ponte.indirizzo + "__schermo/aggiorna")
        except Exception as guasto:
            registro.avviso("schermo.attesa_non_mostrata", **registro.dove_si_e_rotto(guasto))

    def _esci_dal_fisso(self) -> None:
        ponte, self.ponte = self.ponte, None
        if ponte is None:
            return
        try:
            from officina.schermo import collega

            collega.esci(ponte)
        except Exception as guasto:
            registro.errore("schermo.uscita_non_detta", **registro.dove_si_e_rotto(guasto))
        ponte.ferma()

    def ricollegati(self) -> None:
        self._esci_dal_fisso()
        vecchia = self.principale
        self.principale = None
        self.crea_la_finestrina()
        if vecchia is not None:
            self._chiusura_consentita = True
            vecchia.destroy()
            self._chiusura_consentita = False
