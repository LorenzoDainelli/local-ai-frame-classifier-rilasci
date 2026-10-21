from __future__ import annotations

import json
import multiprocessing
import os
import queue
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable

from PIL import Image

from officina import registro
from officina.archivio.database import adesso
from officina.descrittori import torcia
from officina.errori import ErroreOfficina
from officina.importazione import impronta
from officina.miglioria import attesa, date, video
from officina.modello import file_media
from officina.ritocco import (coda, copia, elenco, maschere, pellicola, ricontrollo, seguiti,
                              sfida_togli, togliere)
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
NON_TOLTO = "Il modello per togliere non è riuscito: {perche}. Lo scatto non è stato toccato."
TOGLI_A_PAROLE = {
    "togli_motore_sconosciuto": "non è installato",
    "togli_niente": "la parte scelta è vuota",
    "memoria_scheda_finita": "la memoria della scheda video è finita",
    "memoria_finita": "la memoria del computer è finita",
    "stanza_caduta": "si è fermato di colpo",
    "stanza_muta": "non ha detto com'è andata",
}
DA_RIPRENDERE = {"memoria_scheda_finita", "memoria_finita", "stanza_caduta"}
SI_E_CHIUSO = ("Il pixelato del video si è chiuso da solo. Il video non è stato toccato: "
               "rimettilo in coda.")


class _Rimanda(Exception):
    pass


class Ritoccatore:

    def __init__(self, archivio, seguitore=None, a_parte: bool | None = None,
                 toglie: Callable[..., dict] | None = None,
                 cerca: ricontrollo.Cerca | None = None):
        self.archivio = archivio
        self.seguitore = seguitore
        self._a_parte = a_parte
        self._toglie = toglie or _lancia_togli
        self._cerca = cerca
        self._processo: subprocess.Popen | None = None
        self.lavoro = Lavoro(COSA)
        self._fermati = threading.Event()
        self.adesso: dict = {}
        self._motore_ora: str | None = None

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
        processo = self._processo
        if processo is not None and processo.poll() is None:
            processo.kill()
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
                for fatto in fatti:
                    if fatto.get("sfida"):
                        sfida_togli.registra(connessione, lavoro_id, fatto["file_id"],
                                             fatto["sfida"]["genere"], fatto["sfida"])
                coda.segna(connessione, lavoro_id, coda.DA_RIVEDERE, finito_il=adesso(),
                           secondi=round(time.monotonic() - partito, 1))
                solo_tolti = not coda.nuovi(connessione, lavoro_id)
            elif adesso_e is not None and adesso_e["stato"] == coda.IN_LAVORO:
                coda.segna(connessione, lavoro_id, coda.IN_CODA, iniziato_il=None)
        if cambiato:
            for fatto in fatti:
                if fatto.get("pronta"):
                    copia.butta(Path(fatto["pronta"]))
                if fatto.get("sfida"):
                    sfida_togli.butta(sfida_togli.file_della_b(fatto["sfida"]))
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
        sfida = self._la_sfida(media["genere"], ritocchi)
        if media["genere"] != "video":
            ritocchi_b = None
            if any(ritocco["genere"] == elenco.TOGLI for ritocco in ritocchi):
                try:
                    ritocchi, ritocchi_b = self._a_e_b(
                        self._togli_le_cose, lavoro_id, file_id, ritocchi, da, sfida)
                finally:
                    self._motore_ora = None
                    if self.seguitore is not None:
                        self.seguitore.lascia(self.lavoro)
            pronta = copia.prepara_per_la_coda(self.archivio, file_id, lavoro_id, ritocchi, da)
            fatto = {**fatto, "pronta": str(pronta), "impronta_pronta": impronta.del_file(pronta)}
            if ritocchi_b is not None:
                pronta_b = copia.prepara_per_la_coda(self.archivio, file_id, lavoro_id,
                                                     ritocchi_b, da, variante="b")
                fatto["sfida"] = self._sfida_fatta(sfida, ritocchi_b, pronta_b)
            return fatto

        if da.copia.suffix.casefold() not in video.CONTENITORI_TENUTI:
            raise RitoccoFermato(coda.FORMATO)
        if not da.sorgente.is_file() or impronta.del_file(da.sorgente) != da.impronta_base:
            raise RitoccoFermato(copia.CAMBIATO)
        ritocchi_b = None
        if any(ritocco["genere"] == elenco.TOGLI for ritocco in ritocchi):
            try:
                ritocchi, ritocchi_b = self._a_e_b(
                    self._togli_nel_video, lavoro_id, file_id, ritocchi, da, sfida)
            finally:
                self._motore_ora = None
                if self.seguitore is not None:
                    self.seguitore.lascia(self.lavoro)
        strati = self._strati(ritocchi, da.impronta_base)
        with self.archivio.lettura() as connessione:
            dove = attesa.cartella(connessione, da.copia)
        attesa.prepara(dove)
        serve = da.sorgente.stat().st_size * QUANTO_PUO_CRESCERE + MARGINE_DI_SPAZIO
        if shutil.disk_usage(dove).free < serve:
            raise RitoccoFermato(SPAZIO)
        pronta = self._fai_il_video(dove, file_id, lavoro_id, da, strati, "")
        fatto = {**fatto, "pronta": str(pronta), "impronta_pronta": impronta.del_file(pronta),
                 "fotogrammi": strati[0].quanti}
        if ritocchi_b is not None:
            try:
                pronta_b = self._fai_il_video(dove, file_id, lavoro_id, da,
                                              self._strati(ritocchi_b, da.impronta_base), "b")
            except BaseException:
                copia.butta(pronta)
                raise
            fatto["sfida"] = self._sfida_fatta(sfida, ritocchi_b, pronta_b)
        return fatto

    def _fai_il_video(self, dove: Path, file_id: int, lavoro_id: int, da, strati,
                      variante: str) -> Path:
        pronta = dove / copia.nome_in_attesa(file_id, da.copia, lavoro_id, variante)
        parziale = pronta.with_name(pronta.name + attesa.PARZIALE)
        copia.butta(pronta)
        try:
            self._pellicola(da.sorgente, parziale, strati)
            os.replace(parziale, pronta)
            date.copia(da.sorgente, pronta)
        except BaseException:
            copia.butta(pronta)
            raise
        return pronta

    def _la_sfida(self, genere_media: str, ritocchi) -> dict | None:
        if not any(ritocco["genere"] == elenco.TOGLI and ritocco["stato"] == elenco.IN_CODA
                   for ritocco in ritocchi):
            return None
        genere = sfida_togli.genere_del_file(genere_media)
        due = sfida_togli.si_fa(self.archivio, genere)
        if due is None:
            return None
        return {**sfida_togli.sorteggia(due), "genere": genere}

    def _a_e_b(self, togli, lavoro_id: int, file_id: int, ritocchi, da, sfida):
        self._motore_ora = sfida["motore_a"] if sfida else None
        togli(lavoro_id, file_id, ritocchi, da)
        with self.archivio.lettura() as connessione:
            ritocchi = coda.da_disegnare(connessione, file_id, lavoro_id)
        if sfida is None:
            return ritocchi, None
        self._motore_ora = sfida["motore_b"]
        ritocchi_b = [dict(ritocco) for ritocco in ritocchi]
        togli(lavoro_id, file_id, ritocchi_b, da, lato_b=True)
        return ritocchi, ritocchi_b

    def _sfida_fatta(self, sfida: dict, ritocchi_b, pronta_b: Path) -> dict:
        toppe = {str(ritocco["id"]): {chiave: ritocco[chiave] for chiave in (
            "risultato", "impronta_risultato", "origine_x", "origine_y", "traccia")}
            for ritocco in ritocchi_b if ritocco.get("lato_b")}
        return {**sfida, "pronta_b": str(pronta_b), "impronta_b": impronta.del_file(pronta_b),
                "toppe_b": toppe}

    def _togli_le_cose(self, lavoro_id: int, file_id: int, ritocchi, da,
                       lato_b: bool = False) -> None:
        from officina.miglioria import metadati

        with self.archivio.lettura() as connessione:
            dove = attesa.cartella(connessione, da.copia)
        attesa.prepara(dove)
        toppe = copia.dove_le_toppe(da.copia)
        for indice, ritocco in enumerate(ritocchi):
            if (ritocco["genere"] != elenco.TOGLI or ritocco["stato"] != elenco.IN_CODA
                    or (not lato_b and copia.toppa_pronta(ritocco))):
                continue
            if self._fermati.is_set():
                raise pellicola.Fermato()
            if not da.sorgente.is_file() or impronta.del_file(da.sorgente) != da.impronta_base:
                raise RitoccoFermato(copia.CAMBIATO)
            sotto = copia.disegna(metadati.apri(da.sorgente).immagine, ritocchi[:indice])
            pezzo = maschere.apri(ritocco["maschera"])
            if pezzo is None:
                raise RitoccoFermato(coda.NIENTE)
            buco = maschere.intera(maschere.per_misura(pezzo, *sotto.size))
            base = dove / f"{copia.PREFISSO}-{int(file_id)}-{int(lavoro_id)}-sotto.png"
            forma = base.with_name(base.name.replace("-sotto", "-buco"))
            toppe.mkdir(parents=True, exist_ok=True)
            uscita = toppe / self._nome_della_toppa(copia.nome_della_toppa(ritocco["id"]), lato_b)
            sotto.convert("RGB").save(base)
            Image.fromarray(buco.astype("uint8") * 255, "L").save(forma)
            self.adesso.update(nome=da.copia.name, fatti=indice, totale=len(ritocchi))
            self.lavoro.di(f"tolgo una cosa da «{da.copia.name}»")
            try:
                esito, traccia = self._togli_e_ricontrolla(base, forma, uscita, sotto, buco)
            finally:
                self._processo = None
                base.unlink(missing_ok=True)
                forma.unlink(missing_ok=True)
            if self._fermati.is_set():
                uscita.unlink(missing_ok=True)
                raise pellicola.Fermato()
            if "guasto" in esito or not uscita.is_file():
                uscita.unlink(missing_ok=True)
                codice = str(esito.get("guasto") or "stanza_muta")
                registro.errore("ritocco.togli_non_riuscito", guasto=codice,
                                **{chiave: esito[chiave] for chiave in ("dove", "riga", "tipo")
                                   if chiave in esito})
                if codice in DA_RIPRENDERE:
                    self._fermati.wait(ASPETTA_IL_SEGUITO)
                    raise _Rimanda()
                raise ErroreOfficina(NON_TOLTO.format(
                    perche=TOGLI_A_PAROLE.get(codice, "difetto imprevisto")),
                    codice="ritocco_togli_non_riuscito")
            fatto = esito["fatto"]
            ritocchi[indice] = self._segna_la_toppa(
                ritocco, lato_b, risultato=str(uscita), impronta_risultato=impronta.del_file(uscita),
                origine_x=int(fatto["x"]), origine_y=int(fatto["y"]), larghezza=sotto.width,
                altezza=sotto.height, traccia=json.dumps(traccia))

    def _togli_nel_video(self, lavoro_id: int, file_id: int, ritocchi, da,
                         lato_b: bool = False) -> None:
        from officina.ritocco.togli_stanza import strato_in_json

        with self.archivio.lettura() as connessione:
            dove = attesa.cartella(connessione, da.copia)
        attesa.prepara(dove)
        toppe = copia.dove_le_toppe(da.copia)
        for indice, ritocco in enumerate(ritocchi):
            if (ritocco["genere"] != elenco.TOGLI or ritocco["stato"] != elenco.IN_CODA
                    or (not lato_b and copia.toppa_pronta(ritocco))):
                continue
            if self._fermati.is_set():
                raise pellicola.Fermato()
            if not da.sorgente.is_file() or impronta.del_file(da.sorgente) != da.impronta_base:
                raise RitoccoFermato(copia.CAMBIATO)
            with self.archivio.lettura() as connessione:
                strato = self._strato(connessione, ritocco, da.impronta_base)
            base = dove / f"{copia.PREFISSO}-{int(file_id)}-{int(lavoro_id)}-strato.json"
            base.write_text(json.dumps(strato_in_json(strato)), encoding="utf-8")
            toppe.mkdir(parents=True, exist_ok=True)
            uscita = toppe / self._nome_della_toppa(copia.nome_della_toppa_video(ritocco["id"]),
                                                    lato_b)
            self.adesso.update(nome=da.copia.name, fatti=0, totale=strato.quanti)
            self.lavoro.di(f"tolgo una cosa dal video «{da.copia.name}»")
            esito: dict = {}
            traccia: dict = {"rifatto": 0}
            try:
                for volta, margine in enumerate(togliere.MARGINI):
                    if volta:
                        self.lavoro.di("la toppa tremola, riprovo più largo")
                    self._prendi_la_scheda()
                    lavoro = {**self._lavoro_togli(base, base, uscita, margine),
                              "video": str(da.sorgente), "strato": str(base)}
                    lavoro["motore"] = (self._motore_ora or self._motore_per_i_video()
                                        or lavoro["motore"])
                    esito = self._toglie(lavoro, self._ricorda)
                    if self._fermati.is_set() or "guasto" in esito or not uscita.is_file():
                        break
                    traccia = {"rifatto": volta, "tremola": bool(esito["fatto"].get("tremola"))}
                    if not traccia["tremola"]:
                        break
            finally:
                self._processo = None
                base.unlink(missing_ok=True)
            if self._fermati.is_set():
                uscita.unlink(missing_ok=True)
                raise pellicola.Fermato()
            if "guasto" in esito or not uscita.is_file():
                uscita.unlink(missing_ok=True)
                codice = str(esito.get("guasto") or "stanza_muta")
                registro.errore("ritocco.togli_non_riuscito", guasto=codice,
                                **{chiave: esito[chiave] for chiave in ("dove", "riga", "tipo")
                                   if chiave in esito})
                if codice in DA_RIPRENDERE:
                    self._fermati.wait(ASPETTA_IL_SEGUITO)
                    raise _Rimanda()
                raise ErroreOfficina(NON_TOLTO.format(
                    perche=TOGLI_A_PAROLE.get(codice, "difetto imprevisto")),
                    codice="ritocco_togli_non_riuscito")
            fatto = esito["fatto"]
            ritocchi[indice] = self._segna_la_toppa(
                ritocco, lato_b, risultato=str(uscita), impronta_risultato=impronta.del_file(uscita),
                origine_x=int(fatto["x"]), origine_y=int(fatto["y"]),
                traccia=json.dumps({**traccia, "zona": [int(fatto["x"]), int(fatto["y"]),
                                                        int(fatto["larghezza"]),
                                                        int(fatto["altezza"])]}))

    @staticmethod
    def _nome_della_toppa(nome: str, lato_b: bool) -> str:
        return copia.della_b(nome) if lato_b else nome

    def _segna_la_toppa(self, ritocco, lato_b: bool, **campi):
        if lato_b:
            return {**dict(ritocco), **campi, "lato_b": True}
        colonne = ", ".join(f"{chiave} = ?" for chiave in campi)
        with self.archivio.scrittura() as connessione:
            connessione.execute(f"UPDATE ritocchi SET {colonne} WHERE id = ?",
                                (*campi.values(), ritocco["id"]))
        with self.archivio.lettura() as connessione:
            return elenco.per_id(connessione, ritocco["id"])

    def _togli_e_ricontrolla(self, base: Path, forma: Path, uscita: Path, sotto, buco):
        traccia: dict = {"rifatto": 0}
        esito: dict = {}
        for volta, margine in enumerate(togliere.MARGINI):
            if volta:
                self.lavoro.di("la cosa si vede ancora, riprovo più largo")
            self._prendi_la_scheda()
            esito = self._toglie(self._lavoro_togli(base, forma, uscita, margine),
                                 self._ricorda)
            if self._fermati.is_set() or "guasto" in esito or not uscita.is_file():
                return esito, traccia
            fatto = esito["fatto"]
            toppa = togliere.Toppa.da_png(uscita.read_bytes(), int(fatto["x"]), int(fatto["y"]))
            dopo = toppa.metti(sotto.convert("RGB"))
            guardata = base.with_name(base.name.replace("-sotto", "-dopo"))
            try:
                dopo.save(guardata)
                visto = ricontrollo.controlla(dopo, toppa, buco, self._chi_cerca(), guardata)
            finally:
                guardata.unlink(missing_ok=True)
            traccia = {"rifatto": volta, "resta": visto.resta, "bordo": visto.bordo,
                       "dove": visto.dove}
            if visto.pulito:
                break
        return esito, traccia

    def _motore_per_i_video(self) -> str | None:
        from officina.ritocco import gara_video

        try:
            primi = json.loads(self.archivio.impostazione(gara_video.SCELTI) or "[]")
        except ValueError:
            return None
        return next((nome for nome in primi if nome in togliere.MOTORI), None)

    def _chi_cerca(self):
        if self._cerca is not None:
            return self._cerca
        if self.seguitore is not None and hasattr(self.seguitore, "cerca"):
            return self.seguitore.cerca(self.lavoro)
        return None

    def _prendi_la_scheda(self) -> None:
        if self.seguitore is None or not hasattr(self.seguitore, "prendi_la_scheda"):
            return
        if not self.seguitore.prendi_la_scheda(self.lavoro):
            self._fermati.wait(ASPETTA_IL_SEGUITO)
            raise _Rimanda()

    def _lavoro_togli(self, base: Path, forma: Path, uscita: Path,
                      margine: float = togliere.MARGINI[0]) -> dict:
        from officina.miglioria import motori, preparazione
        from officina.miglioria.lavoro import percorsi_della_stanza

        modelli = self.archivio.dove.modelli
        return {
            "immagine": str(base), "maschera": str(forma), "uscita": str(uscita),
            "margine": margine,
            "motore": (self._motore_ora or self.archivio.impostazione("togli_motore")
                       or togliere.FINTO),
            "ingrandisci": (motori.SEEDVR2 if preparazione.e_pronto(modelli, motori.SEEDVR2)
                            else None),
            "intensita": self._intensita(),
            "percorsi": percorsi_della_stanza(),
            "opzioni": {"cartella_modelli": str(modelli)},
        }

    def _ricorda(self, processo: subprocess.Popen) -> None:
        self._processo = processo
        if self._fermati.is_set():
            processo.kill()

    def _strati(self, ritocchi, impronta_base: str) -> list[pellicola.Strato]:
        strati = []
        with self.archivio.lettura() as connessione:
            for ritocco in ritocchi:
                if ritocco["genere"] not in (elenco.PIXELA, elenco.TOGLI):
                    raise RitoccoFermato(coda.SOLO_PIXELA)
                strato = self._strato(connessione, ritocco, impronta_base)
                if ritocco["genere"] == elenco.TOGLI:
                    if not copia.toppa_pronta(ritocco):
                        raise RitoccoFermato(coda.NIENTE)
                    zona = json.loads(ritocco["traccia"] or "{}").get("zona")
                    if not zona:
                        raise RitoccoFermato(coda.NIENTE)
                    strato.toppa, strato.zona = ritocco["risultato"], tuple(zona)
                strati.append(strato)
        return strati

    def _strato(self, connessione, ritocco, impronta_base: str) -> pellicola.Strato:
        seguito = (seguiti.per_id(connessione, ritocco["seguito_id"])
                   if ritocco["seguito_id"] else None)
        if seguito is None:
            raise RitoccoFermato(coda.NON_SEGUITO)
        if seguito["impronta"] != impronta_base:
            raise RitoccoFermato(coda.SEGUITO_VECCHIO)
        origine = (None if ritocco["origine_x"] is None or ritocco["genere"] != elenco.PIXELA
                   else (ritocco["origine_x"], ritocco["origine_y"]))
        return pellicola.Strato(
            seguito["larghezza"], seguito["altezza"], seguito["quanti"],
            seguiti.tutte_le_maschere(connessione, seguito["id"]), ritocco["cosa"],
            ritocco["quadretto"], origine)

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


def _lancia_togli(lavoro: dict, ricorda) -> dict:
    from officina.miglioria.lavoro import lancia_la_stanza

    return lancia_la_stanza(lavoro, lambda *_: None, ricorda, "officina.ritocco.togli_stanza")


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
