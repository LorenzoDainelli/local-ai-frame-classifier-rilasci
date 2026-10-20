from __future__ import annotations

import multiprocessing
import os
import queue
import shutil
import threading
import time
from pathlib import Path

from officina import registro
from officina.archivio.database import adesso
from officina.descrittori import torcia
from officina.errori import ErroreOfficina
from officina.importazione import impronta
from officina.miglioria import attesa, date, video
from officina.modello import file_media
from officina.ritocco import coda, copia, elenco, pellicola, seguiti
from officina.ritocco.copia import RitoccoFermato
from officina.web import in_disparte
from officina.web.lavori import GUASTO_IMPREVISTO, Lavoro

A = "pellicola"
COSA = "ritocchi"
OGNI_QUANTO = 0.5
PER_CHIUDERSI = 5.0
ASPETTA_IL_SEGUITO = 5.0
MARGINE_DI_SPAZIO = 512 * 1024 * 1024
QUANTO_PUO_CRESCERE = 3

SPAZIO = ("Sul disco delle foto non c'è abbastanza spazio per la copia ritoccata del video. "
          "Il video non è stato toccato.")
SENZA_SEGUIRE = ("Per seguire la parte scelta nel video serve SAM 3, che adesso non è "
                 "pronto. Il video non è stato toccato.")
SI_E_CHIUSO = ("Il pixelato del video si è chiuso da solo. Il video non è stato toccato: "
               "rimettilo in coda.")


class _Rimanda(Exception):
    pass


class Ritoccatore:

    def __init__(self, archivio, seguitore=None, a_parte: bool | None = None):
        self.archivio = archivio
        self.seguitore = seguitore
        self._a_parte = a_parte
        self.lavoro = Lavoro(COSA)
        self._fermati = threading.Event()
        self.adesso: dict = {}

    @property
    def sta_lavorando(self) -> bool:
        return self.lavoro.sta_lavorando

    def parti(self) -> bool:
        if self.lavoro.sta_lavorando:
            return False
        self._fermati.clear()
        return self.lavoro.parti(self._gira, nome=COSA)

    def ferma(self, aspetta: float = 0.0) -> None:
        self._fermati.set()
        in_disparte.manda("ferma", a=A)
        if self.seguitore is not None:
            self.seguitore.ferma()
        if aspetta:
            self.lavoro.aspetta_che_finisca(aspetta)

    def come_va(self) -> dict:
        stato = self.lavoro.come_va()
        stato["adesso"] = dict(self.adesso)
        return stato

    def _gira(self) -> None:
        fatti = 0
        try:
            while not self._fermati.is_set():
                with self.archivio.scrittura() as connessione:
                    riga = coda.prossimo(connessione)
                    if riga is None:
                        break
                    coda.segna(connessione, riga["id"], coda.IN_LAVORO,
                               iniziato_il=adesso(), guasto=None)
                self._uno(riga)
                fatti += 1
        finally:
            self.adesso = {}
            registro.evento("ritocco.giro", fatti=fatti, fermato=self._fermati.is_set())

    def _uno(self, riga) -> None:
        lavoro_id, versione = riga["id"], riga["versione"]
        partito = time.monotonic()
        self.adesso = {"id": lavoro_id, "nome": "", "fatti": 0, "totale": 0}
        try:
            fatti = self._fai(lavoro_id)
        except (_Rimanda, pellicola.Fermato):
            self._rimetti(lavoro_id)
            return
        except ErroreOfficina as errore:
            coda.fallisci(self.archivio, lavoro_id, errore.messaggio)
            self.lavoro.di(f"non riuscito: {errore.messaggio}")
            return
        except Exception as errore:
            registro.errore("ritocco.lavoro_rotto", **registro.dove_si_e_rotto(errore))
            coda.fallisci(self.archivio, lavoro_id, GUASTO_IMPREVISTO)
            self.lavoro.di(f"non riuscito: {GUASTO_IMPREVISTO}")
            return
        with self.archivio.scrittura() as connessione:
            adesso_e = coda.per_id(connessione, lavoro_id)
            cambiato = (adesso_e is None or adesso_e["stato"] != coda.IN_LAVORO
                        or adesso_e["versione"] != versione)
            if not cambiato:
                coda.scrivi_i_pronti(connessione, lavoro_id, fatti)
                coda.segna(connessione, lavoro_id, coda.DA_RIVEDERE, finito_il=adesso(),
                           secondi=round(time.monotonic() - partito, 1))
                solo_tolti = not coda.nuovi(connessione, lavoro_id)
            elif adesso_e is not None and adesso_e["stato"] == coda.IN_LAVORO:
                coda.segna(connessione, lavoro_id, coda.IN_CODA, iniziato_il=None)
        if cambiato:
            for fatto in fatti:
                if fatto.get("pronta"):
                    copia.butta(Path(fatto["pronta"]))
            self.lavoro.di("i ritocchi sono cambiati mentre lavoravo: li rifaccio")
            return
        if not solo_tolti:
            self.lavoro.di("pronto da rivedere")
            return
        try:
            coda.approva(self.archivio, lavoro_id)
            self.lavoro.di("ritocco tolto")
        except (RitoccoFermato, OSError) as errore:
            self.lavoro.di(f"non sono riuscito a rimettere lo scatto: {errore}")

    def _rimetti(self, lavoro_id: int) -> None:
        with self.archivio.scrittura() as connessione:
            riga = coda.per_id(connessione, lavoro_id)
            if riga is not None and riga["stato"] == coda.IN_LAVORO:
                coda.segna(connessione, lavoro_id, coda.IN_CODA, iniziato_il=None)

    def _fai(self, lavoro_id: int) -> list[dict]:
        with self.archivio.lettura() as connessione:
            file_ids = coda.file_coinvolti(connessione, lavoro_id)
        self._segui_tutti(lavoro_id, file_ids)
        fatti: list[dict] = []
        try:
            for file_id in file_ids:
                if self._fermati.is_set():
                    raise pellicola.Fermato()
                fatti.append(self._un_file(lavoro_id, file_id))
        except BaseException:
            for fatto in fatti:
                if fatto.get("pronta"):
                    copia.butta(Path(fatto["pronta"]))
            raise
        return fatti

    def _segui_tutti(self, lavoro_id: int, file_ids: list[int]) -> None:
        with self.archivio.lettura() as connessione:
            da_seguire = list(dict.fromkeys(
                ritocco["seguito_id"] for file_id in file_ids
                for ritocco in coda.da_disegnare(connessione, file_id, lavoro_id)
                if ritocco["seguito_id"]))
        try:
            for seguito_id in da_seguire:
                self._segui_uno(seguito_id)
        finally:
            if da_seguire and self.seguitore is not None:
                self.seguitore.lascia(self.lavoro)

    def _segui_uno(self, seguito_id: int) -> None:
        if self._fermati.is_set():
            raise pellicola.Fermato()
        with self.archivio.lettura() as connessione:
            seguito = seguiti.per_id(connessione, seguito_id)
            tratti = seguiti.tratti_da_fare(connessione, seguito_id)
        if seguito is None:
            raise RitoccoFermato(coda.NON_SEGUITO)
        if not tratti:
            return
        if seguito["stato"] == seguiti.IN_LAVORO:
            self._fermati.wait(ASPETTA_IL_SEGUITO)
            raise _Rimanda()
        if self.seguitore is None:
            raise ErroreOfficina(SENZA_SEGUIRE, codice="ritocco_senza_seguire")
        self.adesso.update(nome="", fatti=0, totale=0)
        if not self.seguitore.segui(seguito_id, self.lavoro):
            if self._fermati.is_set():
                raise pellicola.Fermato()
            self._fermati.wait(ASPETTA_IL_SEGUITO)
            raise _Rimanda()
        with self.archivio.lettura() as connessione:
            if seguiti.tratti_da_fare(connessione, seguito_id):
                raise _Rimanda()

    def _un_file(self, lavoro_id: int, file_id: int) -> dict:
        da = copia.partenza(self.archivio, file_id)
        with self.archivio.lettura() as connessione:
            media = file_media.per_id(connessione, file_id)
            ritocchi = coda.da_disegnare(connessione, file_id, lavoro_id)
        if media is None:
            raise RitoccoFermato(coda.NON_C_E)
        fatto = {"file_id": file_id, "impronta_base": da.impronta_base}
        if not ritocchi:
            return fatto
        self.adesso.update(nome=da.copia.name, fatti=0, totale=0)
        self.lavoro.di(f"ritocco «{da.copia.name}»")
        if media["genere"] != "video":
            pronta = copia.prepara_per_la_coda(self.archivio, file_id, lavoro_id, ritocchi, da)
            return {**fatto, "pronta": str(pronta), "impronta_pronta": impronta.del_file(pronta)}

        if da.copia.suffix.casefold() not in video.CONTENITORI_TENUTI:
            raise RitoccoFermato(coda.FORMATO)
        if not da.sorgente.is_file() or impronta.del_file(da.sorgente) != da.impronta_base:
            raise RitoccoFermato(copia.CAMBIATO)
        strati = self._strati(ritocchi, da.impronta_base)
        with self.archivio.lettura() as connessione:
            dove = attesa.cartella(connessione, da.copia)
        attesa.prepara(dove)
        serve = da.sorgente.stat().st_size * QUANTO_PUO_CRESCERE + MARGINE_DI_SPAZIO
        if shutil.disk_usage(dove).free < serve:
            raise RitoccoFermato(SPAZIO)
        pronta = dove / copia.nome_in_attesa(file_id, da.copia, lavoro_id)
        parziale = pronta.with_name(pronta.name + attesa.PARZIALE)
        copia.butta(pronta)
        try:
            self._pellicola(da.sorgente, parziale, strati)
            os.replace(parziale, pronta)
            date.copia(da.sorgente, pronta)
            segno = impronta.del_file(pronta)
        except BaseException:
            copia.butta(pronta)
            raise
        return {**fatto, "pronta": str(pronta), "impronta_pronta": segno,
                "fotogrammi": strati[0].quanti}

    def _strati(self, ritocchi, impronta_base: str) -> list[pellicola.Strato]:
        strati = []
        with self.archivio.lettura() as connessione:
            for ritocco in ritocchi:
                if ritocco["genere"] != elenco.PIXELA:
                    raise RitoccoFermato(coda.SOLO_PIXELA)
                seguito = (seguiti.per_id(connessione, ritocco["seguito_id"])
                           if ritocco["seguito_id"] else None)
                if seguito is None:
                    raise RitoccoFermato(coda.NON_SEGUITO)
                if seguito["impronta"] != impronta_base:
                    raise RitoccoFermato(coda.SEGUITO_VECCHIO)
                origine = (None if ritocco["origine_x"] is None
                           else (ritocco["origine_x"], ritocco["origine_y"]))
                strati.append(pellicola.Strato(
                    seguito["larghezza"], seguito["altezza"], seguito["quanti"],
                    seguiti.tutte_le_maschere(connessione, seguito["id"]), ritocco["cosa"],
                    ritocco["quadretto"], origine))
        return strati

    def _al_passo(self, fatti: int, totale: int) -> None:
        self.adesso.update(fatti=fatti, totale=totale)
        self.lavoro.a_che_punto(fatti, totale, "fotogrammi")

    def _intensita(self) -> int:
        return int(self.archivio.impostazione("intensita_scheda") or 100)

    def _pellicola(self, sorgente: Path, verso: Path, strati: list[pellicola.Strato]) -> None:
        a_parte = in_disparte.A_PARTE if self._a_parte is None else self._a_parte
        if not a_parte:
            freno = torcia.Freno(self._intensita(), fermato=self._fermati.is_set)
            pellicola.pixela_il_video(sorgente, verso, strati, self._al_passo,
                                      self._fermati.is_set, freno)
            return
        dove_registro = registro.attivo().cartella
        processo, notizie = in_disparte._avvia(
            A, _figlio, (str(sorgente), str(verso), strati, self._intensita(),
                         str(dove_registro) if dove_registro else None))
        esito = self._ascolta(processo, notizie)
        if esito is None:
            registro.errore("ritocco.pellicola_chiusa", uscita=processo.exitcode)
            raise ErroreOfficina(SI_E_CHIUSO, codice="ritocco_pellicola_chiusa")
        if esito.get("fermato"):
            raise pellicola.Fermato()
        if esito.get("guasto"):
            guasto = ErroreOfficina(esito["guasto"], codice=esito.get("codice") or "ritocco")
            guasto.dettaglio = esito.get("dettaglio", "")
            raise guasto

    def _ascolta(self, processo, notizie) -> dict | None:
        mandato = False
        try:
            while True:
                if self._fermati.is_set() and not mandato:
                    in_disparte.manda("ferma", a=A)
                    mandato = True
                try:
                    tipo, _, dati = notizie.get(timeout=OGNI_QUANTO)
                except queue.Empty:
                    if not processo.is_alive():
                        return None
                    continue
                if tipo == "passo":
                    self._al_passo(dati["fatti"], dati["totale"])
                elif tipo == "fine":
                    return dati
        finally:
            processo.join(timeout=PER_CHIUDERSI)
            if processo.is_alive():
                processo.terminate()
                processo.join(timeout=2.0)


def _figlio(sorgente: str, verso: str, strati: list, intensita: int,
            dove_registro: str | None, comandi, notizie) -> None:
    if dove_registro:
        registro.imposta(registro.Registro(Path(dove_registro)))
    genitore = multiprocessing.parent_process()
    fermato = [False]
    ultimo = [0.0]

    def fermati() -> bool:
        while not fermato[0]:
            try:
                comando = comandi.get_nowait()
            except queue.Empty:
                break
            fermato[0] = comando[0] in ("ferma", "basta")
        if genitore is not None and not genitore.is_alive():
            fermato[0] = True
        return fermato[0]

    def al_passo(fatti: int, totale: int) -> None:
        adesso_e = time.monotonic()
        if adesso_e - ultimo[0] >= OGNI_QUANTO or fatti >= totale:
            ultimo[0] = adesso_e
            notizie.put(("passo", None, {"fatti": fatti, "totale": totale}))

    try:
        pellicola.pixela_il_video(Path(sorgente), Path(verso), strati, al_passo, fermati,
                                  torcia.Freno(intensita, fermato=fermati))
        esito: dict = {}
    except pellicola.Fermato:
        esito = {"fermato": True}
    except ErroreOfficina as errore:
        esito = {"guasto": errore.messaggio, "codice": errore.codice}
    except Exception as errore:
        registro.errore("ritocco.pellicola_rotta", **registro.dove_si_e_rotto(errore))
        esito = {"guasto": GUASTO_IMPREVISTO, "codice": "ritocco_rotto",
                 "dettaglio": registro.passi_del_guasto(errore)}
    notizie.put(("fine", None, esito))
