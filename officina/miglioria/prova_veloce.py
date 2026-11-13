from __future__ import annotations

import contextlib
import json
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Callable

from officina import registro
from officina.descrittori import torcia
from officina.descrittori.scaricamento import ScaricamentoFallito
from officina.errori import ErroreOfficina
from officina.miglioria import gara120_casi as casi_mod
from officina.miglioria import gara120_scarica as sc
from officina.miglioria import prova_veloce_corsa as corsa
from officina.miglioria import motori, prova_volti, veloce, video

COSA = "prova_veloce"
CARTELLA = "prova-veloce"
GARA = "gara-120"
DATI = "dati"
ASPETTA_LA_SCHEDA = 30.0
MODULO = "officina.miglioria.prova_veloce_stanza"
PASSI = (4, 2, 1)
MINIMO = 30
QUANTE_FOTO = 6
GRUPPI_FOTO = (casi_mod.DIFFICILISSIMO, casi_mod.DIFFICILE)
PIANO_FOTO = "piano-foto.json"
SENZA_LUCIDFLUX = ("LucidFlux non è pronto: la parte delle foto si salta e l'idea "
                   "delle foto resta spenta.")
SCHEMA = ((casi_mod.FACILE, video.H264, 60, False),
          (casi_mod.DIFFICILISSIMO, video.H264, 180, True),
          (casi_mod.DIFFICILISSIMO, video.HEVC, 60, False),
          (casi_mod.FACILE, video.HEVC, 180, True))
PREPARA = {"gimm": (("gimmvfi", "GIMM-VFI"),), "ldf": (("ldfvfi", "LDF-VFI"),),
           "fusione": (("gimmvfi", "GIMM-VFI"), ("ldfvfi", "LDF-VFI"))}
SENZA_VOLTI = ("CodeFormer non è pronto: la parte dei volti si salta e la sua idea "
               "resta spenta.")
SENZA_RETE = ("Non riesco a scaricare i fotogrammi pubblici della prova: controlla che "
              "internet funzioni e premi di nuovo «Avvia la prova». Riprende da dove era.")
SENZA_SEEDVR2 = ("Per la prova serve SeedVR2 pronto: prima prepara il miglioramento "
                 "nelle Impostazioni, poi premi di nuovo «Avvia la prova».")
NON_PASSATA = ("La prova non è passata, quindi l'idea non si può accendere: "
               "il video uscirebbe diverso.")


class Fermata(Exception):
    pass


def di_fila(numeri: set[int], quanti: int, passo: int) -> list[int] | None:
    for primo in sorted(numeri):
        voluti = [primo + passo * volta for volta in range(quanti)]
        if all(numero in numeri for numero in voluti):
            return voluti
    return None


def piu_lunga(numeri: set[int]) -> list[int]:
    migliore: list[int] = []
    for primo in sorted(numeri):
        if primo - 1 in numeri:
            continue
        fila = [primo]
        while fila[-1] + 1 in numeri:
            fila.append(fila[-1] + 1)
        if len(fila) > len(migliore):
            migliore = fila
    return migliore


def _la_migliore(elenco, scene: list[str], quanti: int) -> tuple[str, list[int]] | None:
    for passo in PASSI:
        for scena in scene:
            numeri = di_fila(set(elenco.presenti.get(scena, ())), quanti, passo)
            if numeri is not None:
                return scena, numeri
    lunghe = [(len(fila), scena, fila) for scena in scene
              if len(fila := piu_lunga(set(elenco.presenti.get(scena, ())))) >= MINIMO]
    if not lunghe:
        return None
    lunghezza = max(voce[0] for voce in lunghe)
    _quanti, scena, fila = min(voce for voce in lunghe if voce[0] == lunghezza)
    return scena, fila[:quanti]


def scegli_clip(elenco) -> list[dict]:
    scelte, usate = [], set()
    for numero, (gruppo, codec, quanti, a_120) in enumerate(SCHEMA):
        scene = sorted({caso.scena for caso in elenco.casi
                        if caso.gruppo == gruppo and caso.scena not in usate})
        trovata = _la_migliore(elenco, scene, quanti)
        if trovata is None:
            raise ErroreOfficina("Non trovo fotogrammi di fila adatti alla prova.",
                                 codice="prova_veloce_senza_clip")
        scena, numeri = trovata
        usate.add(scena)
        sigla = "h264" if codec == video.H264 else "hevc"
        scelte.append({"nome": f"{numero + 1}-{gruppo}-{sigla}-{quanti}", "gruppo": gruppo,
                       "codec": codec, "a_120": a_120, "scena": scena,
                       "nomi": [elenco.veri_nomi[(scena, n)] for n in numeri]})
    return scelte


def nomi_di(clip: list[dict]) -> list[str]:
    return sorted({nome for uno in clip for nome in uno["nomi"]})


def scegli_foto(elenco, quante: int = QUANTE_FOTO) -> list[dict]:
    scelte, usate = [], set()
    for gruppo in GRUPPI_FOTO:
        for scena in sorted({caso.scena for caso in elenco.casi if caso.gruppo == gruppo}):
            if len(scelte) >= quante:
                return scelte
            numeri = sorted(elenco.presenti.get(scena, ()))
            if scena in usate or not numeri:
                continue
            usate.add(scena)
            numero = numeri[len(numeri) // 2]
            scelte.append({"nome": f"foto-{len(scelte) + 1}-{gruppo}", "gruppo": gruppo,
                           "scena": scena, "nomi": [elenco.veri_nomi[(scena, numero)]]})
    return scelte


class ProvaVeloce:

    def __init__(self, archivio, cartella: Path | None = None,
                 lancia: Callable[[dict, Callable], dict] | None = None, turno=None,
                 scarica_da_hf=None, api=None, prepara=None, pronta=None, lucidflux=None,
                 volti=None, wider=None):
        from officina.web.lavori import Lavoro

        modelli = Path(archivio.dove.modelli)
        self.archivio = archivio
        self.cartella = Path(cartella or modelli / CARTELLA)
        self.dati = modelli / GARA / DATI if cartella is None else self.cartella / DATI
        self.corse = self.cartella / "corsa"
        self._lancia = lancia or self._lancia_la_stanza
        self._turno = turno
        self._hf = scarica_da_hf
        self._api = api
        self._prepara = prepara or self._prepara_il_120
        self._pronta = pronta or self._seedvr2_pronto
        self._lucidflux = lucidflux or self._lucidflux_pronto
        self._volti = volti
        self._wider = wider
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

    def _gira(self) -> None:
        try:
            self._corri()
        except Fermata:
            self.lavoro.di("prova fermata: riprende da qui")
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
            registro.errore("prova_veloce.scaricamento_fallito",
                            **registro.dove_si_e_rotto(errore))
            raise ScaricamentoFallito(SENZA_RETE) from errore
        finally:
            torcia.rimetti_la_rete_com_era(prima)

    def _motori(self) -> dict:
        from officina.miglioria import centoventi, motori

        scelto = self.archivio.impostazione("miglioria_video") or motori.SEEDVR2
        return {"video": str(scelto),
                "fps120": centoventi.motore_scelto(self.archivio) or "gimm"}

    def _seedvr2_pronto(self) -> bool:
        from officina.miglioria import preparazione

        return preparazione.e_pronto(Path(self.archivio.dove.modelli))

    def _lucidflux_pronto(self) -> bool:
        from officina.miglioria import motori, preparazione

        return preparazione.e_pronto(Path(self.archivio.dove.modelli), motori.LUCIDFLUX)

    def _tetto(self) -> str:
        from officina.miglioria import misura

        return misura.tetto_vero(self.archivio.impostazione(misura.CHIAVE))

    def _piano_foto(self, foto: list[dict], misura: str) -> None:
        piano = {"foto": [dict(uno) for uno in foto],
                 "misura": misura, "volte": corsa.VOLTE}
        posto = self.cartella / PIANO_FOTO
        try:
            vecchio = json.loads(posto.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            vecchio = None
        if vecchio != piano:
            shutil.rmtree(self.corse / corsa.FOTO, ignore_errors=True)
            self.cartella.mkdir(parents=True, exist_ok=True)
            posto.write_text(json.dumps(piano), encoding="utf-8")

    def _prepara_il_120(self, nome: str) -> None:
        from officina.miglioria import preparazione

        cartella_modelli = Path(self.archivio.dove.modelli)
        for chi, titolo in PREPARA.get(nome, ()):
            if preparazione.e_pronto(cartella_modelli, chi):
                continue
            self._controlla()
            self.lavoro.di(f"scarico e controllo {titolo}, che serve alla prova")
            preparazione.prepara(cartella_modelli, di=self.lavoro.di,
                                 a_che_punto=self._al_pezzo, nome=chi, titolo=titolo)
            self.lavoro.senza_numeri()

    def _piano(self, clip: list[dict], scelti: dict) -> dict:
        piano = {"clip": [{k: v for k, v in uno.items() if k != "nomi"} for uno in clip],
                 "motori": scelti, "volte": corsa.VOLTE}
        posto = self.cartella / corsa.PIANO
        try:
            vecchio = json.loads(posto.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            vecchio = None
        if vecchio != piano:
            shutil.rmtree(self.corse, ignore_errors=True)
            self.cartella.mkdir(parents=True, exist_ok=True)
            posto.write_text(json.dumps(piano), encoding="utf-8")
        return piano

    def _corri(self) -> None:
        if not self._pronta():
            raise ErroreOfficina(SENZA_SEEDVR2, codice="prova_veloce_senza_seedvr2")
        scelti = self._motori()
        con_le_foto = bool(self._lucidflux())
        if not con_le_foto:
            self.lavoro.di(SENZA_LUCIDFLUX)
        self.lavoro.fasi(scarico=3, motori=1, volti=1, prova=95)
        with self._in_rete():
            self.lavoro.di("controllo l'elenco di SNU-FILM")
            elenco = sc.elenco_snu(self.dati, api=self._api, scarica_da_hf=self._hf)
            self._controlla()
            clip = scegli_clip(elenco)
            foto = scegli_foto(elenco) if con_le_foto else []
            self.lavoro.fase("scarico")
            self.lavoro.di("scarico e controllo i fotogrammi della prova")
            sc.scarica_snu(self.dati, elenco, nomi_di(clip + foto), self._al_pezzo,
                           self._hf)
            self.lavoro.senza_numeri()
            self.lavoro.fase("motori")
            self._prepara(scelti["fps120"])
            quali_volti = self._volti_pronti()
            volti = []
            if quali_volti:
                self.lavoro.fase("volti")
                self.lavoro.di("scarico e controllo le foto con i volti (WIDER FACE)")
                volti = prova_volti.scarica(self.dati, self._al_pezzo, self._wider)
                self.lavoro.senza_numeri()
            else:
                self.lavoro.di(SENZA_VOLTI)
        self._controlla()
        self._piano(clip, scelti)
        tetto = self._tetto()
        self._piano_foto(foto, tetto)
        casa = self.dati / sc.SNU
        da_fare = [{"nome": uno["nome"], "codec": uno["codec"], "gruppo": uno["gruppo"],
                    "fps120": scelti["fps120"] if uno["a_120"] else None,
                    "file": [str(casa / nome) for nome in uno["nomi"]]} for uno in clip]
        foto_da_fare = [{"nome": uno["nome"], "gruppo": uno["gruppo"],
                         "file": [str(casa / nome) for nome in uno["nomi"]]} for uno in foto]
        self.lavoro.di(f"la prova: {len(clip)} video e {len(foto)} foto, {corsa.VOLTE} "
                       f"volte vecchio e {corsa.VOLTE} volte nuovo")
        self.lavoro.fase("prova")
        esito = self._nella_stanza(da_fare, scelti, foto_da_fare, tetto, volti,
                                   quali_volti)
        idee = [idea for idea in esito.get("idee") or [] if idea in veloce.IDEE]
        if idee:
            self.accendi(True)
            registro.evento("prova_veloce.passata", idee=len(idee))
        if esito.get("passata"):
            self.lavoro.di("prova passata: tutto esce identico, idee accese")
        elif idee:
            self.lavoro.di("prova passata solo in parte: si accende solo quello che esce "
                           "identico")
        else:
            registro.evento("prova_veloce.non_passata")
            self.lavoro.di("prova non passata: l'idea resta spenta")

    def _prendi_la_scheda(self) -> None:
        try:
            self._aspetta_la_scheda()
        finally:
            self.lavoro.in_pausa(False)

    def _aspetta_la_scheda(self) -> None:
        detto = False
        while not self.turno.prendi_se_libera(self.lavoro):
            if self.turno.chi is self.lavoro:
                return
            if not detto:
                self.lavoro.di("aspetto che la scheda si liberi")
                self.lavoro.in_pausa(True)
                detto = True
            if self._fermati.wait(ASPETTA_LA_SCHEDA):
                raise Fermata()

    def _volti_pronti(self) -> list[str]:
        if self._volti is not None:
            return list(self._volti())
        from officina.miglioria.lavoro import volti_da_soli

        modelli = Path(self.archivio.dove.modelli)
        if volti_da_soli(modelli, senza_faceme=True) is None:
            return []
        if volti_da_soli(modelli) == motori.FACEME:
            return [motori.CODEFORMER, motori.FACEME]
        return [motori.CODEFORMER]

    def _nella_stanza(self, clip: list[dict], scelti: dict, foto: list[dict] | None = None,
                      tetto: str | None = None, volti: list[dict] | None = None,
                      quali_volti: list[str] | None = None) -> dict:
        from officina.miglioria.lavoro import (RAM_POCA, _byte, a_parole, in_giga,
                                               percorsi_della_stanza, ram_a_parole)

        self._prendi_la_scheda()
        try:
            lavoro = {"cartella": str(self.corse), "clip": clip, "volte": corsa.VOLTE,
                      "lavoro": {"motori": {"video": scelti["video"]},
                                 "intensita": int(self.archivio.impostazione(
                                     "intensita_scheda") or 100),
                                 "opzioni": {"cartella_modelli":
                                             str(self.archivio.dove.modelli)}},
                      "percorsi": percorsi_della_stanza()}
            if foto or volti:
                lavoro["foto"] = foto or []
                lavoro["lavoro_foto"] = dict(lavoro["lavoro"], misura=tetto)
            if volti and quali_volti:
                lavoro["volti"] = volti
                lavoro["quali_volti"] = quali_volti
            esito = self._lancia(lavoro, self.lavoro.a_che_punto_a_pezzi)
            if esito.get("guasto") == RAM_POCA and not self._fermati.is_set():
                registro.avviso("prova_veloce.ram_col_disco",
                                serve_gb=in_giga(_byte(esito.get("serve"))),
                                libera_gb=in_giga(_byte(esito.get("libera"))),
                                totale_gb=in_giga(_byte(esito.get("ram_totale"))),
                                in_uso_gb=in_giga(_byte(esito.get("ram_in_uso"))),
                                stanza_gb=in_giga(_byte(esito.get("ram_della_stanza"))))
                self.lavoro.di("la RAM libera non basta per tenere tutto SeedVR2: riparto "
                               "con una parte dei pesi sul disco, ci vuole di più")
                self.lavoro.di(ram_a_parole(esito))
                lavoro["lavoro"]["opzioni"]["disco"] = True
                esito = self._lancia(lavoro, self.lavoro.a_che_punto_a_pezzi)
        finally:
            self._processo = None
            self.turno.lascia(self.lavoro)
            self.lavoro.senza_numeri()
        if self._fermati.is_set():
            raise Fermata()
        if "guasto" in esito:
            detto = str(esito.get("spiegazione") or "") or a_parole(str(esito["guasto"]))
            guasto = ErroreOfficina(detto or "La prova si è fermata per un guasto.",
                                    codice=str(esito["guasto"]))
            guasto.dettaglio = str(esito.get("passi") or "")
            raise guasto
        return esito.get("fatto") or {}

    def esito(self) -> dict | None:
        return corsa.leggi_esito(self.corse)

    def passate(self) -> list[str]:
        esito = self.esito() or {}
        if "foto" not in esito:
            return [veloce.SCRITTURA] if esito.get("passata") else []
        idee = esito.get("idee")
        if not isinstance(idee, list):
            return []
        return [idea for idea in veloce.IDEE if idea in idee]

    def accesa(self) -> bool:
        accese = veloce.accese(self.archivio.impostazione(veloce.CHIAVE))
        return any(idea in accese for idea in veloce.IDEE)

    def accendi(self, acceso: bool) -> None:
        passate = self.passate()
        if acceso and not passate:
            raise ErroreOfficina(NON_PASSATA, codice="prova_veloce_non_passata")
        valore = self.archivio.impostazione(veloce.CHIAVE)
        valore = dict(valore) if isinstance(valore, dict) else {}
        for idea in veloce.IDEE:
            valore[idea] = bool(acceso) and idea in passate
        self.archivio.imposta(veloce.CHIAVE, valore)


__all__ = ["CARTELLA", "COSA", "Fermata", "ProvaVeloce", "di_fila", "nomi_di",
           "piu_lunga", "scegli_clip", "scegli_foto"]
