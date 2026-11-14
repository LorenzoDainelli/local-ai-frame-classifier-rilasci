from __future__ import annotations

import contextlib
import hashlib
import os
import shutil
import time
from pathlib import Path
from typing import Callable

from officina import registro
from officina.descrittori import torcia
from officina.descrittori.scaricamento import ScaricamentoFallito
from officina.errori import ErroreOfficina
from officina.miglioria import gara120
from officina.miglioria import pelle_casi as pc
from officina.miglioria import pelle_corsa as corsa
from officina.miglioria import pelle_fonti as fonti
from officina.miglioria import pelle_voto as voto

COSA = "gara_pelle"
CARTELLA = "gara-pelle"
MODULO = "officina.miglioria.pelle_stanza"
CHI_SONO = "officina-gara-pelle/1.0 (confronto di ingrandimento dei ritratti)"
PARTE = ".parte"
PEZZO = 4 * 2 ** 20
PAUSA = 1.0
PRIMO_GIRO = 8
GIRO = 24
MARGINE = 2 * 2 ** 30
SCARICO, CORSA, VOTO, VOTATA = "scarico", "corsa", "voto", "votata"
SENZA_RETE = ("Non riesco a scaricare i ritratti pubblici o i pesi della gara: controlla "
              "che internet funzioni e premi di nuovo «Avvia la gara». Riprende da dove "
              "era.")


def posto_di(dati: Path, ritratto: fonti.Ritratto) -> Path:
    return Path(dati) / f"{ritratto.sha256[:32]}.jpg"


def _impronta(posto: Path) -> str:
    calcolo = hashlib.sha256()
    with open(posto, "rb") as entrata:
        while pezzo := entrata.read(PEZZO):
            calcolo.update(pezzo)
    return calcolo.hexdigest()


def dalla_rete(indirizzo: str, posto: Path) -> None:
    import urllib.request

    richiesta = urllib.request.Request(indirizzo, headers={"User-Agent": CHI_SONO})
    with urllib.request.urlopen(richiesta, timeout=300) as risposta, \
            open(posto, "wb") as uscita:
        while pezzo := risposta.read(PEZZO):
            uscita.write(pezzo)


def scarica_ritratti(dati: Path, al_pezzo=None, rete=None) -> None:
    dati.mkdir(parents=True, exist_ok=True)
    mancano = [r for r in fonti.RITRATTI if not posto_di(dati, r).is_file()]
    serve = sum(r.byte for r in mancano) + MARGINE
    if mancano and shutil.disk_usage(dati).free < serve:
        raise ErroreOfficina("Non c'è abbastanza spazio sul disco per i ritratti della "
                             "gara.", codice="gara_pelle_spazio")
    for numero, ritratto in enumerate(fonti.RITRATTI):
        posto = posto_di(dati, ritratto)
        if not posto.is_file():
            parte = posto.with_name(posto.name + PARTE)
            for prova in range(4):
                try:
                    (rete or dalla_rete)(ritratto.indirizzo, parte)
                    break
                except OSError:
                    if prova == 3:
                        raise
                    time.sleep(10 * (prova + 1))
            if _impronta(parte) != ritratto.sha256:
                parte.unlink(missing_ok=True)
                raise ScaricamentoFallito("Un ritratto scaricato non è quello giusto "
                                          "(impronta diversa): riprova più tardi.")
            os.replace(parte, posto)
            time.sleep(PAUSA)
        if al_pezzo is not None:
            al_pezzo(numero + 1, len(fonti.RITRATTI))


def pesi_nitidi(cartella_modelli: Path) -> Path:
    from officina.miglioria import scaricamento

    return scaricamento.dove(Path(cartella_modelli)) / scaricamento.PESI / fonti.NITIDO


def scarica_i_pesi_nitidi(cartella_modelli: Path, al_byte=None, da_hf=None) -> None:
    posto = pesi_nitidi(cartella_modelli)
    controllo = posto.with_name(posto.name + ".controllato")
    if posto.is_file() and controllo.is_file():
        return
    if not posto.is_file():
        if shutil.disk_usage(posto.parent).free < fonti.NITIDO_BYTE + MARGINE:
            raise ErroreOfficina("Non c'è abbastanza spazio sul disco per i pesi di "
                                 "SeedVR2 sharp (16,5 GB).", codice="gara_pelle_spazio")
        (da_hf or _da_hf)(posto.parent)
    if _impronta(posto) != fonti.NITIDO_SHA256:
        posto.unlink(missing_ok=True)
        raise ScaricamentoFallito("I pesi di SeedVR2 sharp scaricati non sono quelli "
                                  "giusti (impronta diversa): riprova più tardi.")
    controllo.write_text(fonti.NITIDO_SHA256, encoding="utf-8")


def _da_hf(cartella: Path) -> None:
    from huggingface_hub import hf_hub_download

    hf_hub_download(fonti.PESI_REPO, fonti.NITIDO, revision=fonti.PESI_REVISIONE,
                    local_dir=str(cartella), token=False)


def ordine() -> list[pc.Caso]:
    casi = pc.piano(r.titolo for r in fonti.RITRATTI)
    posto = {pc.MOLTO_DIFFICILE: 0, pc.DIFFICILE: 1, pc.FACILE: 2}
    return sorted(casi, key=lambda c: (posto[c.gruppo], pc.seme(c.chiave, "ordine")))


def giri(casi: list) -> list[list]:
    fuori = [casi[:PRIMO_GIRO]]
    resto = casi[PRIMO_GIRO:]
    fuori += [resto[i:i + GIRO] for i in range(0, len(resto), GIRO)]
    return [g for g in fuori if g]


class GaraPelle(gara120.Gara120):

    def __init__(self, archivio, cartella: Path | None = None,
                 lancia: Callable[[dict, Callable], dict] | None = None, turno=None,
                 rete=None, da_hf=None) -> None:
        from officina.web.lavori import Lavoro

        super().__init__(archivio, cartella or Path(archivio.dove.modelli) / CARTELLA,
                         lancia=lancia, turno=turno)
        self.lavoro = Lavoro(COSA)
        self._rete_ritratti = rete
        self._da_hf = da_hf

    def parti(self) -> bool:
        if self.lavoro.sta_lavorando:
            return False
        self._fermati.clear()
        return self.lavoro.parti(self._gira, nome=COSA)

    def _lancia_la_stanza(self, lavoro: dict, al_passo) -> dict:
        from officina.miglioria.lavoro import lancia_la_stanza

        return lancia_la_stanza(lavoro, al_passo, self._ricorda, MODULO)

    @contextlib.contextmanager
    def _in_rete(self):
        prima = torcia.con_la_rete_accesa()
        try:
            yield
        except (gara120.Fermata, ErroreOfficina):
            raise
        except Exception as errore:
            registro.errore("gara_pelle.scaricamento_fallito",
                            **registro.dove_si_e_rotto(errore))
            raise ScaricamentoFallito(SENZA_RETE) from errore
        finally:
            torcia.rimetti_la_rete_com_era(prima)

    def _corri(self) -> None:
        self.lavoro.fasi(ritratti=2, pesi=8, corsa=90)
        with self._in_rete():
            self.lavoro.di(f"scarico e controllo i {len(fonti.RITRATTI)} ritratti pubblici")
            scarica_ritratti(self.dati, self._al_pezzo, self._rete_ritratti)
            self.lavoro.senza_numeri()
            self.lavoro.fase("pesi")
            self.lavoro.di("scarico e controllo i pesi di SeedVR2 sharp (16,5 GB)")
            scarica_i_pesi_nitidi(Path(self.archivio.dove.modelli), da_hf=self._da_hf)
        self.lavoro.senza_numeri()
        self._controlla()
        self.lavoro.fase("corsa")
        tutti = giri(ordine())
        for numero, giro in enumerate(tutti):
            registro_r = voto.leggi_risultati(self.risultati)
            if len(voto.fatti_del_tutto(registro_r, giro)) == len(giro):
                continue
            prima = "i primi casi molto difficili, per votare presto" if numero == 0 else \
                f"giro {numero + 1} di {len(tutti)}"
            self.lavoro.di(f"la corsa: {prima} ({len(giro)} casi, 5 concorrenti)")
            self._nella_stanza_con({"casi": [c.chiave for c in giro]})
            if numero == 0:
                self.lavoro.di("le prime foto del voto sono pronte: puoi votare mentre "
                               "la gara continua")
        registro.evento("gara_pelle.finita")
        self.lavoro.di("la gara è finita")

    def _nella_stanza_con(self, in_piu: dict) -> dict:
        from officina.miglioria.lavoro import a_parole, percorsi_della_stanza

        self._prendi_la_scheda()
        try:
            lavoro = {"azione": "corsa", "dati": str(self.dati),
                      "risultati": str(self.risultati),
                      "cartella_modelli": str(self.archivio.dove.modelli),
                      "percorsi": percorsi_della_stanza(), **in_piu}
            esito = self._lancia(lavoro, self.lavoro.a_che_punto_a_pezzi)
        finally:
            self._processo = None
            self.turno.lascia(self.lavoro)
            self.lavoro.senza_numeri()
        if self._fermati.is_set():
            raise gara120.Fermata()
        if "guasto" in esito:
            detto = str(esito.get("spiegazione") or "") or a_parole(str(esito["guasto"]))
            guasto = ErroreOfficina(detto or "La gara si è fermata per un guasto.",
                                    codice=str(esito["guasto"]))
            guasto.dettaglio = str(esito.get("passi") or "")
            raise guasto
        return esito.get("fatto") or {}

    def fase(self) -> str:
        dati = voto.leggi(self.risultati)
        if dati.get("casi"):
            fatti = len(voto.fatti_del_tutto(voto.leggi_risultati(self.risultati), ordine()))
            if fatti < len(ordine()):
                return VOTO
            return VOTATA if len(dati.get("voti", {})) >= len(dati["casi"]) else VOTO
        if all(posto_di(self.dati, r).is_file() for r in fonti.RITRATTI):
            return CORSA
        return SCARICO

    def classifiche(self) -> dict | None:
        registro_r = voto.leggi_risultati(self.risultati)
        pronti = voto.fatti_del_tutto(registro_r, ordine())
        if not pronti:
            return None
        return corsa.classifiche(registro_r, pronti)

    def esito(self) -> dict:
        dati = voto.leggi(self.risultati)
        classifiche = self.classifiche()
        pronti = len(voto.fatti_del_tutto(voto.leggi_risultati(self.risultati), ordine()))
        return {"classifiche": classifiche, "conto": voto.conto(dati) if dati else None,
                "pronti": pronti, "casi": len(ordine())}

    def occupa(self) -> int:
        if not self.dati.is_dir():
            return 0
        return sum(f.stat().st_size for f in self.dati.rglob("*") if f.is_file())

    def cancella_i_dati(self) -> int:
        if self.lavoro.sta_lavorando:
            raise ErroreOfficina("Ferma la gara prima di cancellare i dati scaricati.",
                                 codice="gara_pelle_in_corso")
        tolti = self.occupa()
        if self.dati.is_dir():
            shutil.rmtree(self.dati)
        registro.evento("gara_pelle.dati_cancellati", byte=tolti)
        return tolti


__all__ = ["CARTELLA", "COSA", "GaraPelle", "giri", "ordine", "posto_di",
           "scarica_ritratti"]
