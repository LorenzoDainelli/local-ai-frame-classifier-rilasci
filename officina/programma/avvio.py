from __future__ import annotations

import json
import os
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

from officina import registro
from officina.errori import ErroreOfficina
from officina.programma import (ID_APP, NOME, aggiornamenti, carta, istanza,
                                librerie, pagine, scheda, segreti)
from officina.programma.aggiornarsi import Aggiornarsi
from officina.programma.finestre import ICONA, Finestre
from officina.programma.ponti import PontePrincipale
from officina.programma.schermo_fisso import ColFisso
from officina.programma.servitore import PORTA_PREFERITA, Servitore, e_libera, porta_libera

ATTESA_DELLO_SPEGNIMENTO = 60.0

OGNI_QUANTO_LA_COPIA = 120.0
ATTESA_DELLA_FINESTRA_VUOTA = 5.0

GB = 2 ** 30


def numero(quanti: int) -> str:
    return f"{quanti:,}".replace(",", ".")


def peso(quanti: int) -> str:
    if quanti >= GB:
        return f"{quanti / GB:.1f} GB".replace(".", ",")
    return f"{max(1, round(quanti / 2 ** 20))} MB"


def archivio_a_parole(trovato: carta.ArchivioTrovato) -> dict:
    if trovato.scatti is not None:
        scatti = numero(trovato.scatti)
    elif trovato.nel_forziere:
        scatti = "chiusi nel forziere: li conto dopo la password"
    else:
        scatti = "non riesco a contarli adesso"
    return {
        "dove": str(trovato.dove),
        "scatti": scatti,
        "peso": peso(trovato.peso),
        "toccato": datetime.fromtimestamp(trovato.toccato_il).strftime("%d/%m/%Y"),
    }


def la_versione_vecchia_risponde(porta: int = PORTA_PREFERITA) -> bool:
    import urllib.request

    if e_libera(porta):
        return False
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{porta}/", timeout=1.5) as risposta:
            testo = risposta.read(64 * 1024).decode("utf-8", "replace")
    except OSError:
        return False
    return "Officina" in testo or "Local AI Frame Classifier" in testo


def descrivi_la_scheda(esame: scheda.Esame) -> str:
    migliore = esame.la_migliore
    if migliore is None:
        return ("Su questo computer non c'è una scheda video NVIDIA: i modelli "
                "gireranno sul processore. Funziona tutto, solo più lentamente.")
    return (f"Ho trovato una {migliore.nome} ({migliore.memoria_a_parole}): i "
            "modelli gireranno sulla scheda video. Prima di tenerla faccio una "
            "prova vera, e se non va uso il processore.")


def quanto_si_scarica(esame: scheda.Esame, manca: list[str]) -> str:
    totale = 0
    if "torch" in manca:
        totale += int(2.6 * GB) if esame.nvidia else int(0.3 * GB)
    if "modelli" in manca:
        totale += int(0.15 * GB)
    return f"circa {peso(totale)}" if totale else "niente"


class Programma(ColFisso, Finestre, Aggiornarsi):

    def __init__(self, webview=None, esamina=None):
        self._webview = webview
        self.versione = aggiornamenti.versione_attuale()
        self.canale = aggiornamenti.canale_attuale()
        self.installatore = librerie.Installatore(esamina=esamina)
        self.istanza = istanza.Istanza()
        self.servitore: Servitore | None = None
        self.finestrina = None
        self.principale = None
        self.scelto: carta.ArchivioTrovato | None = None
        self.guasto = ""
        self.apertura = {"titolo": "Apro il tuo archivio", "detto": ""}
        self.fase_apertura = 0
        self.aggiornamento_trovato: aggiornamenti.Rilascio | None = None
        self.aggiornamento_stato = {"fase": "fermo", "fatti": 0, "totale": 0, "guasto": ""}
        self.da_installare_dopo: Path | None = None
        self._chiusura_consentita = False
        self._sta_chiudendo = False
        self._guarda_gia = False
        self._spento = False
        self.guasto_dei_tasti = ""
        self._richieste_libere = False
        self._lucchetto = threading.RLock()
        self.ponte = None
        from officina import modelli_in_casa
        from officina.web import lavori

        self.scaricatore = modelli_in_casa.Scaricatore(lavori.Lavoro("i modelli all'avvio"))

    @property
    def webview(self):
        if self._webview is None:
            import webview

            self._webview = webview
        return self._webview

    def fai(self, azione) -> dict:
        try:
            with self._lucchetto:
                risposta = azione()
        except ErroreOfficina as errore:
            return {"errore": errore.messaggio}
        except Exception as guasto:
            registro.errore("programma.azione_rotta", **registro.dove_si_e_rotto(guasto))
            return {"errore": "Qualcosa è andato storto. Riprova."}
        if isinstance(risposta, dict):
            return risposta
        return {"stato": self.stato_per_la_finestrina()}

    def _forziere_chiuso(self) -> bool:
        from officina import forziere
        from officina.impostazioni import REALE, posizione

        cassa = forziere.per(posizione(REALE))
        return cassa.acceso and not cassa.aperto

    def _obblighi_sospesi(self) -> bool:
        return bool(carta.leggi().get("obblighi_sospesi"))

    def _servono_i_motori(self) -> bool:
        manca = librerie.cosa_manca()
        if not manca:
            return False
        if not self._obblighi_sospesi():
            return True
        scritto = carta.leggi()
        mai_installati = not librerie.stato_scritto()
        return not (scritto.get("motori_rimandati") and mai_installati)

    def _scheda_da_rivedere(self) -> bool:
        if self.servitore is not None:
            return False
        esame = self.installatore.esamina_la_scheda()
        if not librerie.scheda_cambiata(esame):
            return False
        rimandata = carta.leggi().get("motori_rimandati_per_la_scheda")
        return rimandata != esame.la_migliore.nome

    def _parti_da_preparare(self) -> list[str]:
        manca = librerie.cosa_manca()
        if not manca and librerie.scheda_cambiata(self.installatore.esamina_la_scheda()):
            return ["torch"]
        return manca

    def _serve_la_chiave(self) -> bool:
        if self._obblighi_sospesi() and carta.leggi().get("chiave_chiesta"):
            return False
        return not segreti.c_e_la_chiave_hf()

    def _servono_i_modelli(self) -> bool:
        from officina import modelli_in_casa

        if self.scaricatore.lavoro.sta_lavorando:
            return True
        if self._obblighi_sospesi():
            return False
        if self.scaricatore.lavoro.guasto:
            return True
        return bool(modelli_in_casa.mancano_gli_obbligatori())

    def _usa_l_archivio_della_versione_1(self) -> bool:
        dati = carta.cartella_dati()
        return dati is not None and dati == carta.cartella_della_versione_1().resolve()

    def fa_da_schermo(self) -> bool:
        return carta.leggi().get("modo") == "schermo"

    def passo(self) -> str:
        if self.guasto:
            return "guasto"
        if self.fa_da_schermo():
            from officina.schermo import collega

            return "schermo-entra" if collega.fisso_abbinato() else "schermo-cerca"
        if carta.cartella_dati() is None:
            return "scelto" if self.scelto is not None else "archivio"
        if not carta.cartella_dati().is_dir():
            return "scelto" if self.scelto is not None else "sparito"
        if (self.servitore is None and self._usa_l_archivio_della_versione_1()
                and la_versione_vecchia_risponde()):
            return "vecchia-aperta"
        if (self.installatore.sta_lavorando or self._servono_i_motori()
                or self._scheda_da_rivedere()):
            return "motori"
        if self._serve_la_chiave():
            return "chiave"
        if self._servono_i_modelli():
            return "modelli"
        if self._forziere_chiuso():
            return "password"
        return "pronto"

    def stato_per_la_finestrina(self) -> dict:
        passo = self.passo()
        dati: dict = {"passo": passo, "versione": self.versione}
        if passo == "pronto":
            self._vai_alla_principale_in_sottofondo()
            dati["passo"] = "apertura"
            dati.update(self.apertura)
        elif passo == "archivio":
            vecchio = carta.archivio_della_versione_1()
            dati["versione_1"] = archivio_a_parole(vecchio) if vecchio else None
        elif passo == "scelto":
            dati["scelto"] = archivio_a_parole(self.scelto)
        elif passo == "motori":
            esame = self.installatore.esamina_la_scheda()
            parti = self._parti_da_preparare()
            cambiata = not librerie.cosa_manca() and librerie.scheda_cambiata(esame)
            dati["scheda"] = (("La scheda video è cambiata dall'ultima volta. "
                               if cambiata else "") + descrivi_la_scheda(esame))
            dati["quanto"] = quanto_si_scarica(esame, parti)
            dati["motori"] = self.installatore.stato.come_dati()
        elif passo == "modelli":
            scelti = carta.leggi().get("miglioria_scelti_all_avvio")
            lavoro = self.scaricatore.lavoro
            if scelti is not None and not lavoro.sta_lavorando and not lavoro.finito:
                self.scarica_i_modelli(scelti)
            dati["modelli"] = self.i_modelli_per_la_finestrina()
        elif passo == "guasto":
            dati["guasto"] = self.guasto
        elif passo == "sparito":
            dati["dove"] = str(carta.cartella_dati())
        return dati

    def usa_la_versione_1(self) -> None:
        vecchio = carta.archivio_della_versione_1()
        if vecchio is None:
            raise ErroreOfficina("Non trovo più l'archivio della versione di prima.")
        carta.usa_questo_archivio(vecchio.dove)
        carta.aggiorna(migrato_dalla_versione_1=True)
        registro.evento("programma.archivio_ripreso")

    def comincia_da_zero(self) -> None:
        carta.comincia_da_zero()
        self.scelto = None
        registro.evento("programma.archivio_nuovo")

    def sfoglia_archivio(self) -> dict | None:
        scelta = self.scegli_cartella(str(carta.cartella_della_versione_1().parent))
        if not scelta:
            return {"stato": self.stato_per_la_finestrina()}
        self.scelto = carta.dalla_scelta(scelta)
        return None

    def usa_lo_scelto(self) -> None:
        if self.scelto is None:
            raise ErroreOfficina("Non hai ancora scelto una cartella.")
        carta.usa_questo_archivio(self.scelto.dove)
        self.scelto = None

    def torna_all_archivio(self) -> None:
        self.scelto = None

    def prepara_i_motori(self) -> dict:
        self.installatore.parti(self._parti_da_preparare())
        return {"stato": {"passo": "motori", "versione": self.versione,
                          "scheda": descrivi_la_scheda(self.installatore.esamina_la_scheda()),
                          "motori": self.installatore.stato.come_dati()}}

    def ferma_i_motori(self) -> None:
        self.installatore.ferma()

    def motori_piu_tardi(self) -> None:
        self.installatore.ferma()
        migliore = self.installatore.esamina_la_scheda().la_migliore
        carta.aggiorna(motori_rimandati=True,
                       motori_rimandati_per_la_scheda=migliore.nome if migliore else None)

    def salva_la_chiave(self, valore: str) -> None:
        from officina import modelli_in_casa

        pulita = (valore or "").strip()
        if not segreti.sembra_una_chiave_hf(pulita):
            raise ErroreOfficina(
                "Questa non sembra una chiave di Hugging Face: comincia con "
                "«hf_» ed è lunga. Copiala di nuovo dalla pagina delle chiavi.")
        modelli_in_casa.controlla_la_chiave(pulita)
        segreti.custodisci(segreti.CHIAVE_HF, pulita)
        carta.aggiorna(chiave_chiesta=True)

    def apri_il_sito(self, dove: str) -> None:
        import webbrowser

        if not str(dove).startswith("https://huggingface.co/"):
            raise ErroreOfficina("Questo indirizzo non si apre da qui.")
        webbrowser.open(dove)

    def i_modelli_per_la_finestrina(self) -> dict:
        import shutil

        from officina import modelli_in_casa

        dove = modelli_in_casa.cartella()
        esistente = dove
        while not esistente.exists() and esistente.parent != esistente:
            esistente = esistente.parent
        try:
            libero = shutil.disk_usage(esistente).free
        except OSError:
            libero = 0
        obbligatori = [{"quale": q, "nome": modelli_in_casa.nome(q),
                        "peso": modelli_in_casa.peso(q),
                        "in_casa": modelli_in_casa.in_casa(q, dove)}
                       for q in modelli_in_casa.OBBLIGATORI]
        facoltativi = [{"quale": q, "nome": modelli_in_casa.nome(q),
                        "peso": modelli_in_casa.peso(q),
                        "in_casa": modelli_in_casa.in_casa(q, dove),
                        "consigliato": q in modelli_in_casa.CONSIGLIATI}
                       for q in modelli_in_casa.FACOLTATIVI]
        return {"obbligatori": obbligatori, "facoltativi": facoltativi,
                "libero": libero, "disco": str(esistente.anchor or esistente),
                "lavoro": self.scaricatore.come_va()}

    def scarica_i_modelli(self, facoltativi) -> None:
        from officina import modelli_in_casa

        voluti = [q for q in modelli_in_casa.FACOLTATIVI if q in (facoltativi or [])]
        quali = modelli_in_casa.mancano(list(modelli_in_casa.OBBLIGATORI) + voluti)
        carta.aggiorna(miglioria_scelti_all_avvio=voluti)
        if not quali:
            return
        self.scaricatore.lavoro.guasto = ""
        self.scaricatore.parti(quali)

    def come_vanno_i_modelli(self) -> dict:
        lavoro = self.scaricatore.come_va()
        if not lavoro["sta_lavorando"] and not lavoro["guasto"] and lavoro["finito"]:
            lavoro["pronto"] = not self._servono_i_modelli()
        return lavoro

    def ferma_i_modelli(self) -> None:
        self.scaricatore.ferma()
        self.scaricatore.lavoro.aspetta_che_finisca(2.0)

    def salta_la_chiave(self) -> None:
        carta.aggiorna(chiave_chiesta=True)

    def apri_il_forziere(self, password: str) -> dict:
        from officina import forziere
        from officina.impostazioni import REALE, posizione

        cassa = forziere.per(posizione(REALE))
        if not password:
            raise ErroreOfficina("Scrivi la password.")
        if not cassa.la_password_e_giusta(password):
            registro.avviso("programma.password_sbagliata")
            raise ErroreOfficina("La password non è giusta.")
        self.apertura = {"titolo": "Apro il forziere",
                         "detto": "Con un archivio grande ci vuole qualche secondo."}
        self.fase_apertura = 0
        self._apri_subito_la_principale()
        threading.Thread(target=self._apri_e_mostra, args=(password,), name="apertura",
                         daemon=True).start()
        return {"stato": {"passo": "apertura", "versione": self.versione, **self.apertura}}

    def _apri_subito_la_principale(self) -> None:
        if self.principale is not None:
            return
        self.crea_la_principale()
        self.principale.events.loaded.wait(ATTESA_DELLA_FINESTRA_VUOTA)
        if self.finestrina is not None:
            vecchia, self.finestrina = self.finestrina, None
            vecchia.destroy()

    def riprova(self) -> None:
        self.guasto = ""

    def _vai_alla_principale_in_sottofondo(self) -> None:
        if getattr(self, "_partenza", None) is not None:
            return
        self._partenza = threading.Thread(target=self._apri_e_mostra, args=(None,),
                                          name="apertura", daemon=True)
        self._partenza.start()

    def _apri_e_mostra(self, password: str | None) -> None:
        try:
            indirizzo = self.accendi(password)
        except ErroreOfficina as errore:
            self._mostra_il_guasto(errore.messaggio)
            return
        except Exception as guasto:
            registro.errore("programma.apertura_rotta", **registro.dove_si_e_rotto(guasto))
            self._mostra_il_guasto(
                "L'archivio non si è aperto per un guasto che non avevo "
                "previsto. Chiudi il programma e riaprilo.")
            return
        self._mostra_la_principale(indirizzo)

    def accendi(self, password: str | None = None) -> str:
        from officina.archivio import accesso
        from officina.impostazioni import REALE

        partenza = time.monotonic()
        librerie.metti_nel_percorso()
        caricamento = threading.Thread(target=_carica_il_server, name="caricamento",
                                       daemon=True)
        caricamento.start()
        archivio = accesso.apri(REALE, password=password)
        self.fase_apertura = 1
        aperto_in = time.monotonic() - partenza
        in_rete = bool(archivio.impostazione("accesso_dalla_rete"))
        host = "0.0.0.0" if in_rete else "127.0.0.1"
        caricamento.join()
        self.fase_apertura = 2
        if self.servitore is None:
            self.servitore = Servitore(host=host, porta=porta_libera(PORTA_PREFERITA, host))
            self.servitore.parti()
        from officina.web.strade import schermo

        schermo.imposta_il_programma(PontePrincipale(self))
        if archivio.impostazione("porta_del_portatile"):
            try:
                schermo.apri_la_porta_del_portatile()
            except Exception as guasto:
                registro.errore("schermo.porta_non_riaperta", **registro.dove_si_e_rotto(guasto))
        self.fase_apertura = 3
        self._parti_le_copie_in_sottofondo()
        registro.evento("programma.acceso", in_rete=in_rete,
                        archivio_ms=round(aperto_in * 1000),
                        tutto_ms=round((time.monotonic() - partenza) * 1000))
        return self.servitore.indirizzo

    def _parti_le_copie_in_sottofondo(self) -> None:
        if getattr(self, "_copie", None) is not None:
            return
        self._copie = threading.Thread(target=self._copie_in_sottofondo, name="copie",
                                       daemon=True)
        self._copie.start()

    def _copie_in_sottofondo(self) -> None:
        from officina.archivio import accesso

        while not self._sta_chiudendo and not self._spento:
            time.sleep(OGNI_QUANTO_LA_COPIA)
            if self._sta_chiudendo or self._spento or self.lavori_in_corso():
                continue
            try:
                accesso.aperto().copia_se_fermo()
            except ErroreOfficina:
                continue
            except Exception as guasto:
                registro.errore("copie.in_sottofondo_fallita", **registro.dove_si_e_rotto(guasto))

    def _mostra_il_guasto(self, messaggio: str) -> None:
        self.guasto = messaggio
        if self.principale is not None:
            self.principale.load_html(pagine.attesa(
                "Non sono riuscito ad aprire l'archivio", messaggio, gira=False,
                versione=self.versione))
        elif self.finestrina is not None:
            self.finestrina.evaluate_js("window.location.reload()")

    def scegli_cartella(self, da_dove: str | None = None) -> str | None:
        finestra = self.principale or self.finestrina
        if finestra is None:
            return None
        cartella_iniziale = da_dove if da_dove and os.path.isdir(da_dove) else str(Path.home())
        scelta = finestra.create_file_dialog(self.webview.FileDialog.FOLDER,
                                             directory=cartella_iniziale)
        if not scelta:
            return None
        return scelta[0] if isinstance(scelta, (list, tuple)) else str(scelta)

    def lavori_in_corso(self) -> list[str]:
        generale = sys.modules.get("officina.web.strade.generale")
        if generale is None:
            return []
        try:
            return generale.lavori_in_corso()
        except Exception as guasto:
            registro.avviso("programma.lavori_non_contati", **registro.dove_si_e_rotto(guasto))
            return []

    def _quando_chiude(self) -> bool:
        if self._chiusura_consentita:
            return True
        if not self._sta_chiudendo:
            self._sta_chiudendo = True
            threading.Thread(target=self._chiudi_con_calma, name="chiusura",
                             daemon=True).start()
        return False

    def _chiede_la_pagina(self, domanda: str) -> bool:
        testo = domanda.replace("\n\nChiudo?", "").strip()
        try:
            return self.principale.evaluate_js(
                f"window.chiediDiChiudere ? window.chiediDiChiudere({json.dumps(testo)}) : false") is True
        except Exception as guasto:
            registro.avviso("programma.domanda_non_fatta", **registro.dove_si_e_rotto(guasto))
            return False

    def chiudi_comunque(self) -> dict:
        if not self._sta_chiudendo:
            self._sta_chiudendo = True
            threading.Thread(target=self._chiudi_con_calma, kwargs={"senza_chiedere": True},
                             name="chiusura", daemon=True).start()
        return {}

    def domanda_prima_di_chiudere(self) -> str | None:
        in_corso = self.lavori_in_corso()
        if not in_corso:
            return None
        return (f"Sta ancora lavorando: {', '.join(in_corso)}. Se chiudi adesso "
                "si ferma, e la prossima volta riprende da dove era.\n\nChiudo?")

    def _chiudi_con_calma(self, senza_chiedere: bool = False) -> None:
        if self.ponte is not None:
            self._ricorda_la_geometria()
            try:
                self._esci_dal_fisso()
            finally:
                self._chiusura_consentita = True
                self.principale.destroy()
            return
        domanda = None if senza_chiedere else self.domanda_prima_di_chiudere()
        if domanda and self._chiede_la_pagina(domanda):
            self._sta_chiudendo = False
            return
        if domanda and not self.principale.create_confirmation_dialog(NOME, domanda):
            self._sta_chiudendo = False
            return
        self._ricorda_la_geometria()
        from officina import forziere
        from officina.archivio import accesso

        aperto = accesso.aperto() if self._c_e_un_archivio_aperto() else None
        con_forziere = aperto is not None and forziere.per(aperto.dove).acceso
        passi = ["Fermo i lavori in corso"]
        if aperto is not None:
            passi.append("Faccio la copia, perché oggi è cambiato qualcosa"
                         if aperto._serve_la_copia() else "Salvo le ultime cose")
        if con_forziere:
            passi.append("Richiudo il forziere")
        porta = self._porta_per_l_aggiornamento()
        if porta is not None:
            porta.chiusura = {"passi": [*passi, "Installo l'aggiornamento", "Riparto"],
                              "fatti": 0}
        self.principale.load_html(pagine.attesa(
            "Metto al sicuro l'archivio",
            "Non spegnere il computer: si chiude da solo tra un momento."
            if con_forziere else "Si chiude da solo tra un momento.",
            versione=self.versione, passi=passi, fotina="addormenta"))

        def avanza(quanti: int) -> None:
            if porta is not None and porta.chiusura is not None:
                porta.chiusura["fatti"] = min(quanti, len(passi))
            try:
                self.principale.evaluate_js(f"window.segna && window.segna({quanti})")
            except Exception:
                pass

        try:
            self.spegni_entro(avanza)
        finally:
            self._chiusura_consentita = True
            self.principale.destroy()

    def _porta_per_l_aggiornamento(self):
        modulo = sys.modules.get("officina.schermo.porta")
        if self.da_installare_dopo is None or modulo is None:
            return None
        porta = modulo.porta
        return porta if porta.aperta and porta.collegato() is not None else None

    def _c_e_un_archivio_aperto(self) -> bool:
        from officina.archivio import accesso

        try:
            accesso.aperto()
        except ErroreOfficina:
            return False
        return True

    def _ricorda_la_geometria(self) -> None:
        finestra = self.principale
        if finestra is None:
            return
        try:
            massimizzata = bool(getattr(self, "_massimizzata", False))
            geometria = self._geometria()
            if massimizzata:
                geometria["massimizzata"] = True
            else:
                geometria = {"larga": int(finestra.width), "alta": int(finestra.height),
                             "x": int(finestra.x), "y": int(finestra.y),
                             "massimizzata": False}
            carta.aggiorna(finestra=geometria)
        except Exception as guasto:
            registro.avviso("programma.misura_non_ricordata", **registro.dove_si_e_rotto(guasto))

    def spegni_entro(self, avanza=None, secondi: float = ATTESA_DELLO_SPEGNIMENTO) -> bool:
        lavoro = threading.Thread(target=self.spegni, args=(avanza,),
                                  name="spegnimento", daemon=True)
        lavoro.start()
        lavoro.join(secondi)
        if lavoro.is_alive():
            registro.errore("programma.spegnimento_bloccato", secondi=secondi)
            return False
        return True

    def spegni(self, avanza=None) -> None:
        if self._spento:
            return
        self._spento = True
        avanza = avanza or (lambda quanti: None)
        partenza = time.monotonic()
        self.installatore.ferma(aspetta=10.0)
        self._esci_dal_fisso()
        sfoglia = sys.modules.get("officina.web.sfoglia")
        if sfoglia is not None:
            sfoglia.imposta_chi_sceglie(None)
        generale = sys.modules.get("officina.web.strade.generale")
        if generale is not None:
            try:
                generale.ferma_tutto()
            except Exception as guasto:
                registro.errore("programma.lavori_non_fermati", **registro.dove_si_e_rotto(guasto))
        if self.servitore is not None:
            self.servitore.ferma()
        avanza(1)
        try:
            from officina.archivio import accesso

            accesso.chiudi()
            avanza(3)
        except Exception as guasto:
            registro.errore("programma.archivio_non_chiuso", **registro.dove_si_e_rotto(guasto))
        modulo = sys.modules.get("officina.schermo.porta")
        if modulo is not None and modulo.porta.chiusura is not None:
            modulo.porta.chiudi()
        registro.evento("programma.spento",
                        tutto_ms=round((time.monotonic() - partenza) * 1000))

    def stato_del_programma(self) -> dict:
        scritto = librerie.stato_scritto()
        torcia = scritto.get("torch") or {}
        manca = librerie.cosa_manca()
        return {
            "versione": self.versione,
            "canale": self.canale,
            "aggiornamento": self.come_va_l_aggiornamento(),
            "motori": {
                "mancano": manca,
                "variante": torcia.get("variante"),
                "scheda": torcia.get("scheda"),
                "perche": torcia.get("perche"),
                "quanto": quanto_si_scarica(self.installatore.esamina_la_scheda(), manca)
                if manca else "",
                "lavora": self.installatore.sta_lavorando,
                "riavvio": bool(manca) and bool(scritto) and self._torch_gia_caricato(),
            },
            "chiave": segreti.c_e_la_chiave_hf(),
            "chiave_dall_ambiente": bool((os.environ.get("HF_TOKEN") or "").strip()),
        }

    def _torch_gia_caricato(self) -> bool:
        return "torch" in sys.modules

    def prepara_i_motori_da_dentro(self) -> dict:
        if self._torch_gia_caricato():
            raise ErroreOfficina(
                "I motori sono già in uso: chiudi il programma e riaprilo, e "
                "li preparo prima di aprire l'archivio.")
        self.installatore.parti()
        carta.aggiorna(motori_rimandati=None)
        return self.installatore.stato.come_dati()

    def salva_la_chiave_da_dentro(self, valore: str) -> dict:
        self.salva_la_chiave(valore)
        return {"chiave": True}

    def togli_la_chiave(self) -> dict:
        segreti.togli(segreti.CHIAVE_HF)
        return {"chiave": segreti.c_e_la_chiave_hf()}

    def rientra(self, password: str) -> dict:
        from officina.archivio import accesso
        from officina.web import blocco

        if not blocco.guardia.sblocca("qui", accesso.aperto().dove, password or ""):
            raise ErroreOfficina("La password non è giusta.")
        return {"vai": "/"}

    def spegni_il_forziere(self, password: str) -> dict:
        from officina import forziere
        from officina.archivio import accesso

        archivio = accesso.aperto()
        cassa = forziere.per(archivio.dove)
        if not cassa.acceso:
            raise ErroreOfficina("Su questo archivio non c'è un forziere da spegnere.")
        if not cassa.la_password_e_giusta(password or ""):
            raise ErroreOfficina("La password non è giusta.")
        cassa.spegni(password)
        archivio._parola = None
        registro.evento("programma.forziere_spento")
        return {"vai": "/impostazioni#c6"}

    def accendi_il_forziere(self, password: str, ancora: str, su_carta: bool,
                            dove_torno: str = "") -> dict:
        from officina.web.strade import impostazioni

        risposta = impostazioni.accendi_il_forziere(
            password=password or "", ancora=ancora or "",
            su_carta="1" if su_carta else "", dove_torno=dove_torno or "")
        return {"vai": risposta.headers.get("location", "/")}

    def rifiuta_aggiornamento(self) -> dict:
        if self.aggiornamento_trovato is not None:
            aggiornamenti.rifiuta(self.aggiornamento_trovato)
        self.aggiornamento_stato["fase"] = "rifiutato"
        return self.come_va_l_aggiornamento()

    def avvia(self) -> int:
        istanza.dai_un_nome_al_processo(ID_APP)
        if not self.istanza.prendi():
            istanza.porta_avanti(NOME)
            return 0
        try:
            if self.canale == aggiornamenti.BETA:
                pronto = aggiornamenti.pronto_da_installare()
                if pronto is not None:
                    self.istanza.lascia()
                    aggiornamenti.installa(pronto[1])
                    return 0
            aggiornamenti.pulisci_gli_scaricati()
            librerie.metti_nel_percorso()
            if self.passo() == "pronto":
                self.crea_la_principale()
                partenza = self._vai_alla_principale_in_sottofondo
            else:
                self.crea_la_finestrina()
                partenza = None
            try:
                self.webview.start(partenza, private_mode=False,
                                   storage_path=str(carta.casa() / "finestra"),
                                   icon=str(ICONA),
                                   gui="edgechromium" if sys.platform == "win32" else None)
            except Exception as guasto:
                registro.errore("programma.finestra_non_partita",
                                **registro.dove_si_e_rotto(guasto))
                avvisa(NOME, SENZA_FINESTRA)
                return 1
        finally:
            self.spegni_entro()
            self.istanza.lascia()
        if self.da_installare_dopo is not None:
            aggiornamenti.installa(self.da_installare_dopo)
        elif self.canale == aggiornamenti.BETA:
            pronto = aggiornamenti.pronto_da_installare()
            if pronto is not None:
                aggiornamenti.installa(pronto[1], riapri=False)
        return 0



SENZA_FINESTRA = (
    "La finestra del programma non si è aperta. Di solito vuol dire che su "
    "questo computer manca Microsoft Edge WebView2, che l'installazione "
    "mette da sola quando c'è internet.\n\n"
    "Riapri l'installazione del programma con internet acceso: rimette "
    "quello che manca, e il tuo archivio non si tocca.")


def _carica_il_server() -> None:
    try:
        import officina.web.server
    except Exception as guasto:
        registro.errore("programma.server_non_caricato", **registro.dove_si_e_rotto(guasto))


def avvisa(titolo: str, testo: str) -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.WinDLL("user32").MessageBoxW(None, testo, titolo, 0x40 | 0x10000)
    except (OSError, AttributeError):
        pass


def _senza_terminale() -> None:
    nulla = open(os.devnull, "w", encoding="utf-8")
    if sys.stdout is None:
        sys.stdout = nulla
    if sys.stderr is None:
        sys.stderr = nulla

    def racconta(tipo, errore, traccia) -> None:
        registro.errore("programma.rotto", **registro.dove_si_e_rotto(errore))

    def racconta_filo(argomenti) -> None:
        if argomenti.exc_value is not None:
            registro.errore("programma.filo_rotto",
                            **registro.dove_si_e_rotto(argomenti.exc_value))

    sys.excepthook = racconta
    threading.excepthook = racconta_filo


def principale(argomenti: list[str] | None = None) -> int:
    scelte = list(sys.argv[1:] if argomenti is None else argomenti)
    if scelte and scelte[0] == "--collaudo":
        from officina.programma import collaudo

        return collaudo.principale(scelte[1:])
    _senza_terminale()
    os.environ.setdefault("OFFICINA_NEL_PROGRAMMA", "1")
    registro.imposta(registro.Registro(carta.casa() / "registro"))
    return Programma().avvia()
