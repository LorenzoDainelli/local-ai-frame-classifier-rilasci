from __future__ import annotations

import contextlib
import subprocess
import threading
from pathlib import Path
from typing import Callable

from officina import registro
from officina.descrittori import torcia
from officina.descrittori.scaricamento import ScaricamentoFallito
from officina.errori import ErroreOfficina
from officina.miglioria import gara120_corsa as corsa
from officina.miglioria import gara120_scarica as sc
from officina.miglioria import gara120_stanza as stanza
from officina.miglioria import gara120_voto as voto

COSA = "gara_120"
CARTELLA = "gara-120"
DATI = "dati"
RISULTATI = "risultati"
ASPETTA_LA_SCHEDA = 30.0
MODULO = "officina.miglioria.gara120_stanza"
SCARICO, CORSA, CLIP, VOTO, VOTATA = "scarico", "corsa", "clip", "voto", "votata"
MOTORI = (("gimmvfi", "GIMM-VFI"), ("ldfvfi", "LDF-VFI"))
SENZA_RETE = ("Non riesco a scaricare i video pubblici della gara: controlla che "
              "internet funzioni e premi di nuovo «Avvia gara». Riprende da dove era.")


class Fermata(Exception):
    pass


class Gara120:

    def __init__(self, archivio, cartella: Path | None = None,
                 lancia: Callable[[dict, Callable], dict] | None = None, turno=None,
                 scarica_da_hf=None, dalla_rete=None, api=None, prepara=None):
        from officina.web.lavori import Lavoro

        self.archivio = archivio
        self.cartella = Path(cartella or Path(archivio.dove.modelli) / CARTELLA)
        self.dati = self.cartella / DATI
        self.risultati = self.cartella / RISULTATI
        self._lancia = lancia or self._lancia_la_stanza
        self._turno = turno
        self._hf = scarica_da_hf
        self._rete = dalla_rete
        self._api = api
        self._prepara = prepara or self._prepara_i_motori
        self.lavoro = Lavoro(COSA)
        self._fermati = threading.Event()
        self._processo: subprocess.Popen | None = None

    @property
    def turno(self):
        if self._turno is None:
            from officina.web import lavori

            return lavori.turno
        return self._turno

    def parti(self) -> bool:
        if self.lavoro.sta_lavorando:
            return False
        self._fermati.clear()
        return self.lavoro.parti(self._gira, nome=COSA)

    def ferma(self, aspetta: float = 0.0) -> None:
        self._fermati.set()
        processo = self._processo
        if processo is not None and processo.poll() is None:
            try:
                processo.terminate()
            except OSError:
                pass
        if aspetta:
            self.lavoro.aspetta_che_finisca(aspetta)

    def _ricorda(self, processo: subprocess.Popen) -> None:
        self._processo = processo
        if self._fermati.is_set():
            try:
                processo.terminate()
            except OSError:
                pass

    def _lancia_la_stanza(self, lavoro: dict, al_passo: Callable[[int, int], None]) -> dict:
        from officina.miglioria.lavoro import lancia_la_stanza

        return lancia_la_stanza(lavoro, al_passo, self._ricorda, MODULO)

    def _controlla(self) -> None:
        if self._fermati.is_set():
            raise Fermata()

    def _al_pezzo(self, fatti: int, totale: int) -> None:
        self._controlla()
        self.lavoro.a_che_punto_a_pezzi(fatti, totale)

    def _al_byte(self, fatti: int, totale: int) -> None:
        self._controlla()
        self.lavoro.a_che_punto(fatti, totale)

    def _gira(self) -> None:
        try:
            self._corri()
        except Fermata:
            self.lavoro.di("gara fermata: riprende da qui")
        finally:
            self.turno.lascia(self.lavoro)
            self.lavoro.senza_numeri()

    @contextlib.contextmanager
    def _in_rete(self):
        prima = torcia.con_la_rete_accesa()
        try:
            yield
        except (Fermata, ErroreOfficina):
            raise
        except Exception as errore:
            registro.errore("gara_120.scaricamento_fallito",
                            **registro.dove_si_e_rotto(errore))
            raise ScaricamentoFallito(SENZA_RETE) from errore
        finally:
            torcia.rimetti_la_rete_com_era(prima)

    def _corri(self) -> None:
        with self._in_rete():
            self.lavoro.di("controllo l'elenco di SNU-FILM")
            elenco = sc.elenco_snu(self.dati, api=self._api, scarica_da_hf=self._hf)
            self._controlla()
            self.lavoro.di("scarico e controllo i fotogrammi di SNU-FILM")
            sc.scarica_snu(self.dati, elenco, sc.nomi_che_servono(elenco), self._al_pezzo,
                           self._hf)
            self.lavoro.di("scarico e controllo X-TEST e Adobe240 (l'archivio di XVFI)")
            sc.scarica_xvfi(self.dati, self._al_byte, self._rete)
            self.lavoro.senza_numeri()
            self._prepara()
        self.lavoro.senza_numeri()
        self._controlla()
        piano = corsa.scrivi_piano(self.dati, elenco, sc.cartelle_adobe(self.dati))
        self.lavoro.di(f"la corsa: {len(piano.casi)} casi, prima GIMM-VFI e poi LDF-VFI")
        esito = self._nella_stanza(stanza.CORSA)
        if min(esito.get("gimm", 0), esito.get("ldf", 0)) < len(piano.casi):
            raise Fermata()
        registro_r = corsa.Risultati(self.risultati)
        try:
            clip = voto.leggi_clip(self.risultati)
        except (OSError, ValueError):
            clip = voto.prepara_voto(self.risultati, registro_r, elenco, piano)
        if not clip:
            raise ErroreOfficina("Non trovo casi adatti per il voto alla cieca.",
                                 codice="gara_120_senza_voto")
        self.lavoro.di(f"scarico i fotogrammi delle {len(clip)} clip del voto")
        with self._in_rete():
            sc.scarica_snu(self.dati, elenco, voto.nomi_del_voto(clip, elenco),
                           self._al_pezzo, self._hf)
        self.lavoro.senza_numeri()
        self.lavoro.di("preparo i video del voto alla cieca")
        esito = self._nella_stanza(stanza.CLIP)
        if not esito.get("pronte"):
            raise Fermata()
        registro.evento("gara_120.clip_pronte", quante=len(clip))
        self.lavoro.di("i video del voto sono pronti: tocca a te")

    def _prepara_i_motori(self) -> None:
        from officina.miglioria import preparazione

        cartella_modelli = Path(self.archivio.dove.modelli)
        for nome, titolo in MOTORI:
            if preparazione.e_pronto(cartella_modelli, nome):
                continue
            self._controlla()
            self.lavoro.di(f"scarico e controllo {titolo}, che corre nella gara")
            preparazione.prepara(cartella_modelli, di=self.lavoro.di,
                                 a_che_punto=self._al_byte, nome=nome, titolo=titolo)
            self.lavoro.senza_numeri()

    def _prendi_la_scheda(self) -> None:
        detto = False
        while not self.turno.prendi_se_libera(self.lavoro):
            if self.turno.chi is self.lavoro:
                return
            if not detto:
                self.lavoro.di("aspetto che la scheda si liberi")
                detto = True
            if self._fermati.wait(ASPETTA_LA_SCHEDA):
                raise Fermata()

    def _nella_stanza(self, azione: str) -> dict:
        from officina.miglioria.lavoro import a_parole, percorsi_della_stanza

        self._prendi_la_scheda()
        try:
            lavoro = {"azione": azione, "dati": str(self.dati),
                      "risultati": str(self.risultati),
                      "cartella_modelli": str(self.archivio.dove.modelli),
                      "percorsi": percorsi_della_stanza()}
            esito = self._lancia(lavoro, self.lavoro.a_che_punto_a_pezzi)
        finally:
            self._processo = None
            self.turno.lascia(self.lavoro)
            self.lavoro.senza_numeri()
        if self._fermati.is_set():
            raise Fermata()
        if "guasto" in esito:
            detto = str(esito.get("spiegazione") or "") or a_parole(str(esito["guasto"]))
            raise ErroreOfficina(detto or "La gara si è fermata per un guasto.",
                                 codice=str(esito["guasto"]))
        return esito.get("fatto") or {}

    def fase(self) -> str:
        if voto.clip_pronte(self.risultati):
            quante = len(voto.leggi_clip(self.risultati))
            return VOTATA if voto.conto(self.risultati, quante)["votati"] == quante else VOTO
        try:
            piano = corsa.leggi_piano(self.dati)
        except (OSError, ValueError, KeyError):
            return SCARICO
        registro_r = corsa.Risultati(self.risultati)
        fatti = min(len(registro_r.fatti(corsa.GIMM)), len(registro_r.fatti(corsa.LDF)))
        return CLIP if fatti >= len(piano.casi) else CORSA

    def classifiche(self) -> dict | None:
        try:
            piano = corsa.leggi_piano(self.dati)
        except (OSError, ValueError, KeyError):
            return None
        registro_r = corsa.Risultati(self.risultati)
        if not registro_r.fatti(corsa.LDF):
            return None
        return corsa.classifiche(registro_r, piano.casi)

    def occupa(self) -> int:
        if not self.dati.is_dir():
            return 0
        return sum(f.stat().st_size for f in self.dati.rglob("*") if f.is_file())

    def cancella_i_dati(self) -> int:
        if self.lavoro.sta_lavorando:
            raise ErroreOfficina("Ferma la gara prima di cancellare i dati scaricati.",
                                 codice="gara_120_in_corso")
        tolti = sc.cancella(self.dati)
        registro.evento("gara_120.dati_cancellati", byte=tolti)
        return tolti

    def esito(self) -> dict:
        classifiche = self.classifiche()
        conto = None
        if voto.clip_pronte(self.risultati):
            conto = voto.conto(self.risultati, len(voto.leggi_clip(self.risultati)))
        automatico = (classifiche or {}).get("difficilissimi", {}).get("primo")
        su_tutto = (classifiche or {}).get("tutto", {}).get("primo")
        dal_voto = conto["primo"] if conto else None
        finito = bool(conto) and conto["votati"] == conto["quanti"]
        return {"classifiche": classifiche, "conto": conto, "automatico": automatico,
                "su_tutto_un_altro": bool(automatico and su_tutto
                                          and su_tutto != automatico),
                "vincitore": voto.vincitore(automatico, dal_voto) if finito else None,
                "decidiamo_insieme": finito and voto.vincitore(automatico, dal_voto) is None}


__all__ = ["CARTELLA", "COSA", "Fermata", "Gara120"]
