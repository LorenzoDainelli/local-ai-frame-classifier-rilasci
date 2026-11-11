from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable

from officina import registro
from officina.archivio.database import adesso
from officina.errori import ErroreOfficina
from officina.importazione import impronta
from officina.miglioria import (attesa, catena, centoventi, coda, da_guardare, fedelta,
                                fluido, motori, persone, pezzi, previsione, scambio, sfida,
                                video)
from officina.modello import file_media
from officina.sicuro.dall_archivio import CHIUSO, CHIUSO_ADESSO, DIVERSA, PERSA, SI_APRE
from officina.web.lavori import Lavoro

MARGINE_DI_SPAZIO = 512 * 1024 * 1024
QUANTO_PUO_CRESCERE = 12
BYTE_PER_PIXEL_DEI_PEZZI = 2
DA_RIFARE_DOPO = {CHIUSO_ADESSO, PERSA}
RAM_POCA = "ram_poca"
RAM_POCA_COL_DISCO = "ram_poca_anche_col_disco"
RAM_POCHE = {RAM_POCA, RAM_POCA_COL_DISCO}
RISPOSTE_PER_LA_RAM = ("aspetto", "disco")
OGNI_QUANTO_LA_RAM = 10.0
DA_RIPRENDERE = ({"memoria_scheda_finita", "memoria_finita", "stanza_caduta"} | DA_RIFARE_DOPO
                 | RAM_POCHE)
SCHEDA_FINITA = "memoria_scheda_finita"
DI_FILA_SENZA_MEMORIA = 3
SCHEDA_OCCUPATA = ("La scheda video ha finito la memoria su tre file di fila: di solito vuol dire "
                   "che la sta usando qualcos'altro, per esempio l'intelligenza artificiale. "
                   "Il miglioramento si è fermato e quei file sono tornati in coda: fallo "
                   "ripartire quando la scheda è libera.")

MESSAGGI = {
    "originale_assente": "l'originale non è più dov'era",
    "originale_cambiato": "l'originale è cambiato da quando è entrato in coda",
    "spazio": "sul disco delle foto non c'è abbastanza spazio",
    "gia_grande": "è già grande quanto la misura di arrivo o più",
    "memoria_finita": "è finita la memoria del computer",
    "memoria_scheda_finita": "è finita la memoria della scheda video",
    RAM_POCA: "per SeedVR2 la RAM libera non basta",
    RAM_POCA_COL_DISCO: ("per SeedVR2 la RAM libera non basta, anche tenendo una parte dei "
                         "pesi sul disco"),
    "motore_mancante": "il modello che serve non è ancora stato preparato",
    "spazio_modelli": ("LDF-VFI non sta nella scheda video e sul disco dei modelli non c'è "
                       "spazio per appoggiare i calcoli"),
    "stanza_caduta": "il modello si è fermato di colpo",
    "stanza_muta": "il modello non ha detto com'è andata",
    "solo_foto": "questo modello migliora solo le foto",
    "lavoro_illeggibile": "difetto del programma nel preparare il lavoro",
    "rotto": "difetto imprevisto: il dettaglio tecnico è nel registro",
    "pezzi_rotti": "un pezzo già migliorato non si legge più: si rifà da capo",
    "torch_troppo_vecchio": ("il motore delle reti neurali è troppo vecchio per aprire "
                             "i pesi in sicurezza: aggiorna i motori"),
    DIVERSA: "nell'Archivio sicuro c'è solo una versione diversa dell'originale",
    CHIUSO_ADESSO: ("l'originale è solo nell'Archivio sicuro, che è chiuso: resta in coda "
                    "finché lo apri"),
    PERSA: ("nell'Archivio sicuro l'originale è rovinato: resta in coda finché "
            "l'archivio l'ha riparato"),
}
NON_RIPRESA = {
    "originale_assente": ("assente", "non trovo la foto o la versione di SeedVR2"),
    "originale_cambiato": ("cambiata", "la foto è cambiata da quando SeedVR2 l'ha fatta"),
}


def a_parole(codice: str | None) -> str:
    if not codice:
        return ""
    return MESSAGGI.get(codice, codice)


def perche_saltata(esito: dict | None) -> str:
    if not esito:
        return ""
    detto = str(esito.get("spiegazione") or "") or a_parole(str(esito.get("guasto") or ""))
    return detto.strip().rstrip(".")


GIGA = 2 ** 30


def _byte(valore) -> int:
    if isinstance(valore, bool) or not isinstance(valore, (int, float)):
        return 0
    return max(int(valore), 0)


def in_giga(quanti: int) -> float:
    return round(quanti / GIGA, 1)


def giga_in_su(quanti: int) -> int:
    return -(-quanti // GIGA)


def tempo_a_parole(secondi: float) -> str:
    tondi = max(0, round(secondi))
    ore, resto = divmod(tondi, 3600)
    minuti, secondi = divmod(resto, 60)
    if ore:
        return f"{ore} h {minuti} min"
    if minuti:
        return f"{minuti} min {secondi} s"
    return f"{secondi} s"


def misura_di_lucidflux(fatto: dict) -> str:
    stanno = fatto.get("dove_stanno")
    secondi = fatto.get("secondi")
    if not isinstance(stanno, dict) or not isinstance(secondi, (int, float)):
        return ""
    giga = {dove: float(stanno.get(dove) or 0) for dove in ("scheda", "ram", "disco")}
    registro.evento("miglioria.lucidflux_misura", secondi=float(secondi), **giga)
    detto = f"LucidFlux ci ha messo {tempo_a_parole(secondi)}"
    if giga["disco"]:
        detto += ", " + f"{giga['disco']:.1f}".replace(".", ",") + " GB letti dal disco"
    return f" ({detto})"


def _giga_a_parole(giga: float) -> str:
    return f"{giga:.1f}".removesuffix(".0").replace(".", ",") + " GB"


def misura_di_seedvr2(fatto: dict) -> str:
    stanno = fatto.get("dove_stanno")
    if not isinstance(stanno, dict):
        return ""
    giga = {dove: float(stanno.get(dove) or 0) for dove in ("scheda", "ram", "disco")}
    registro.evento("miglioria.seedvr2_pesi", **giga)
    return (f" (SeedVR2: scheda {_giga_a_parole(giga['scheda'])} · RAM "
            f"{_giga_a_parole(giga['ram'])} · disco {_giga_a_parole(giga['disco'])})")


def misura_del_motore(fatto: dict) -> str:
    piu = centoventi.con_chi(fatto.get("motori"))
    return misura_dei_motori(fatto) + (f" · {piu}" if piu else "")


def misura_dei_motori(fatto: dict) -> str:
    nomi = [motore.get("nome") for motore in fatto.get("motori") or []
            if isinstance(motore, dict) and motore.get("nome") != centoventi.NOME]
    if nomi[:1] == ["seedvr2"]:
        return misura_di_seedvr2(fatto)
    detto = misura_di_lucidflux(fatto)
    dopo = fatto.get("dopo")
    if "seedvr2" in nomi[1:] and isinstance(dopo, dict):
        detto += misura_di_seedvr2(dopo)
    return detto


def percorsi_della_stanza() -> list[str]:
    from officina.programma import librerie

    fuori = []
    for parte in librerie.PARTI:
        dove = librerie.cartella(parte)
        if dove.is_dir():
            fuori.append(str(dove))
    return fuori


def volti_da_soli(cartella_modelli: Path, senza_faceme: bool = False) -> str | None:
    from officina.miglioria import codeformer_pesi, preparazione
    from officina.volti import rilevatore

    if not (codeformer_pesi.e_in_casa(cartella_modelli)
            and rilevatore.ci_sono_i_modelli(cartella_modelli)):
        return None
    if not senza_faceme and preparazione.e_pronto(cartella_modelli, motori.FACEME):
        return motori.FACEME
    return motori.CODEFORMER


def quanto_puo_crescere(tetto: str | None = None) -> float:
    from officina.miglioria import misura

    return QUANTO_PUO_CRESCERE * max(1.0, misura.pixel_del_tetto(tetto) / misura.PIXEL_FHD)


def spazio_dei_pezzi(originale: Path, tetto: str | None = None) -> int:
    from officina.miglioria import misura

    try:
        piano = video.guarda(originale)
    except Exception:                                    # noqa: BLE001
        return 0
    larghezza, altezza = misura.di_arrivo(piano.larghezza, piano.altezza, pari=True,
                                          tetto=tetto)
    return larghezza * altezza * BYTE_PER_PIXEL_DEI_PEZZI * max(piano.fotogrammi, 0)


def spazio_dei_120(originale: Path, tetto: str | None, motore: str | None) -> int:
    from officina.miglioria import centoventi, misura

    if motore is None:
        return 0
    try:
        piano = video.guarda(originale)
    except Exception:                                    # noqa: BLE001
        return 0
    verso = centoventi.arrivo(piano.fps)
    if verso is None:
        return 0
    if misura.e_gia_grande(piano.larghezza, piano.altezza, tetto):
        larghezza, altezza = piano.larghezza, piano.altezza
    else:
        larghezza, altezza = misura.di_arrivo(piano.larghezza, piano.altezza, pari=True,
                                              tetto=tetto)
    serve = int(originale.stat().st_size * quanto_puo_crescere(tetto)
                * float(verso / centoventi.ritmo(piano.fps)))
    if motore == "fusione":
        dentro = max(piano.fotogrammi, 0) * centoventi.volte(piano.fps, verso)
        serve += larghezza * altezza * 3 * dentro
    return serve


def _sportello(processo: subprocess.Popen):
    from officina.archivio import accesso
    from officina.sicuro import sportello, tubo

    try:
        nome = accesso.aperto().dove.nome
    except ErroreOfficina:
        nome = None
    verso = tubo.Verso(processo.stdin, processo.kill)
    return sportello.Sportello(nome, verso, verso)


def _allo_sportello(allo_sportello, domanda) -> None:
    from officina.sicuro import tubo

    try:
        domanda = tubo.da_testo(domanda)
    except ValueError:
        return
    allo_sportello.ricevi(domanda)


def _tubo_rotto(dove: dict) -> dict:
    tipo, posto, riga = (str(dove.get(chiave, "")) for chiave in ("guasto", "dove", "riga"))
    registro.errore("sicuro.tubo_rotto", tipo=registro.Parola(tipo),
                    dove=registro.Parola(posto), riga=riga)
    return {"guasto": "rotto", "tipo": tipo, "dove": posto, "riga": riga}


def _chiudi(entrata) -> None:
    try:
        entrata.close()
    except (OSError, ValueError):
        pass


def apri_la_stanza(modulo: str) -> subprocess.Popen:
    from officina.programma import librerie, scheda

    comando = [librerie.python_per_i_comandi(), "-m", modulo]
    return subprocess.Popen(
        comando, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, cwd=str(librerie.RADICE), text=True,
        encoding="utf-8", creationflags=scheda.SENZA_FINESTRA)


def ascolta_la_stanza(processo: subprocess.Popen, allo_sportello,
                      al_passo: Callable[[int, int], None]) -> tuple:
    esito: dict | None = None
    rotto = None
    for riga in processo.stdout:
        try:
            messaggio = json.loads(riga)
        except ValueError:
            continue
        if not isinstance(messaggio, dict):
            continue
        if allo_sportello is not None:
            allo_sportello.controlla()
            if "archivio" in messaggio:
                _allo_sportello(allo_sportello, messaggio["archivio"])
                continue
            if isinstance(messaggio.get("tubo_rotto"), dict):
                rotto = _tubo_rotto(messaggio["tubo_rotto"])
                continue
        if isinstance(messaggio.get("tempi"), dict):
            registro.evento("miglioria.tempi", **{
                chiave: valore for chiave, valore in messaggio["tempi"].items()
                if isinstance(valore, (int, float))})
        if "fatti" in messaggio:
            al_passo(int(messaggio["fatti"]), int(messaggio.get("totale") or 0))
        elif "fatto" in messaggio or "guasto" in messaggio:
            esito = messaggio
        elif messaggio.get("accesa") is True and esito is not None and "fatto" in esito:
            return esito, rotto, messaggio
    return esito, rotto, None


def esito_della_stanza(esito: dict | None, rotto: dict | None,
                       codice_di_uscita: int) -> dict:
    if esito is None:
        esito = {"guasto": "stanza_muta" if codice_di_uscita == 0 else "stanza_caduta"}
    if rotto is not None and "guasto" in esito:
        esito = rotto
    return esito


def lancia_la_stanza(lavoro: dict, al_passo: Callable[[int, int], None],
                     ricorda: Callable[[subprocess.Popen], None],
                     modulo: str = "officina.miglioria.stanza") -> dict:
    processo = apri_la_stanza(modulo)
    ricorda(processo)
    esito: dict | None = None
    allo_sportello = None
    rotto = None
    try:
        processo.stdin.write(json.dumps(lavoro) + "\n")
        processo.stdin.flush()
        if lavoro.get("dall_archivio"):
            allo_sportello = _sportello(processo)
        else:
            processo.stdin.close()
        esito, rotto, _accesa = ascolta_la_stanza(processo, allo_sportello, al_passo)
    finally:
        if allo_sportello is not None:
            allo_sportello.chiudi()
        _chiudi(processo.stdin)
        codice_di_uscita = processo.wait()
    return esito_della_stanza(esito, rotto, codice_di_uscita)


def _versione_di_seedvr2() -> str:
    from officina.miglioria.rifai import versione_di_adesso

    return versione_di_adesso()


class Miglioratore:

    def __init__(self, archivio, lancia: Callable[..., dict] | None = None,
                 motori_scelti: dict | None = None,
                 sfidanti_pronti: Callable[[], bool] | None = None):
        from officina.miglioria import accesa

        self.archivio = archivio
        self._accesa = accesa.StanzaAccesa()
        self._lancia = lancia or self._accesa.lancia
        self.motori_scelti = motori_scelti
        self._sfidanti_pronti = sfidanti_pronti or self._ci_sono_tutti_e_due
        self.lavoro = Lavoro("miglioramento", scheda=True)
        self._fermati = threading.Event()
        self._processo: subprocess.Popen | None = None
        self.adesso: dict = {}
        self._saltate_in_sfida: set[int] = set()
        self._salta: set[int] = set()
        self._disco = False
        self._misura: dict | None = None
        self._scelta: str | None = None
        self._risposta = threading.Event()

    @property
    def sta_lavorando(self) -> bool:
        return self.lavoro.sta_lavorando

    def parti(self) -> bool:
        self._fermati.clear()
        return self.lavoro.parti(self._gira, nome="miglioramento")

    def ferma(self, aspetta: float = 0.0) -> None:
        self._fermati.set()
        self._risposta.set()
        processo = self._processo
        if processo is not None and processo.poll() is None:
            try:
                processo.terminate()
            except OSError:
                pass
        if aspetta:
            self.lavoro.aspetta_che_finisca(aspetta)

    def come_va(self) -> dict:
        stato = self.lavoro.come_va()
        stato["adesso"] = dict(self.adesso)
        return stato

    def _ricorda(self, processo: subprocess.Popen) -> None:
        self._processo = processo
        if self._fermati.is_set():
            try:
                processo.terminate()
            except OSError:
                pass

    def _scelti(self) -> dict:
        if self.motori_scelti is not None:
            return dict(self.motori_scelti)
        scelto = str(self.archivio.impostazione("miglioria_volti") or motori.DA_SOLI)
        volti = None
        if scelto != motori.NESSUNO:
            volti = volti_da_soli(self.archivio.dove.modelli,
                                  senza_faceme=scelto == motori.CODEFORMER)
        return {
            "foto": str(self.archivio.impostazione("miglioria_foto") or motori.SEEDVR2),
            "video": str(self.archivio.impostazione("miglioria_video") or motori.SEEDVR2),
            "volti": volti,
        }

    def _ci_sono_tutti_e_due(self) -> bool:
        from officina.miglioria import preparazione

        modelli = self.archivio.dove.modelli
        return (preparazione.e_pronto(modelli)
                and preparazione.e_pronto(modelli, motori.LUCIDFLUX))

    def _in_sfida(self, genere: str) -> bool:
        if genere != "immagine":
            return False
        with self.archivio.lettura() as connessione:
            if not sfida.si_fa(connessione, True) or sfida.in_pausa(connessione):
                return False
        return bool(self._sfidanti_pronti())

    def _gira(self) -> None:
        riparato = scambio.ripara(self.archivio)
        self._rifai_con_la_nuova()
        with self.archivio.lettura() as connessione:
            tenute = {riga["id"] for riga in coda.in_stato(connessione, coda.DA_RIVEDERE)}
        da_guardare.pulisci(self.archivio.dove, tenute)
        if riparato["riprese"]:
            self.lavoro.di(f"riprendo {riparato['riprese']} file lasciati a metà")
        fatti = 0
        senza_memoria: list[int] = []
        self._saltate_in_sfida = set()
        self._salta = set()
        self._disco = False
        try:
            while not self._fermati.is_set():
                with self.archivio.scrittura() as connessione:
                    riga = coda.prossima(connessione, self._salta)
                    if riga is None:
                        break
                    coda.segna(connessione, riga["id"], coda.IN_LAVORO, guasto=None)
                self._uno(riga)
                fatti += 1
                senza_memoria = self._conta_la_memoria(riga["id"], senza_memoria)
            fatti += self._riprendi_la_sfida()
        finally:
            self._accesa.spegni()
            self.adesso = {}
            registro.evento("miglioria.giro", fatti=fatti,
                            fermato=self._fermati.is_set())

    def _rifai_in_grande(self) -> None:
        from officina.miglioria import rifai

        esito = rifai.in_grande(self.archivio)
        if esito is not None and esito.rimesse:
            self.lavoro.di(f"rimetto in coda {esito.rimesse} file fatti in FHD, per "
                           "rifarli nella misura nuova")
        self._rifai_a_120()

    def _rifai_a_120(self) -> None:
        from officina.miglioria import rifai

        esito = rifai.a_centoventi(self.archivio)
        if esito is not None and esito.rimesse:
            quanti = esito.rimesse
            self.lavoro.di(f"rimetto in coda {quanti} video "
                           "sotto i 120 FPS, per rifarli a 120 FPS")

    def _rifai_con_la_nuova(self) -> None:
        from officina.miglioria import preparazione, rifai

        self._rifai_in_grande()
        if not preparazione.e_pronto(self.archivio.dove.modelli):
            return
        esito = rifai.tutto(self.archivio)
        if esito.rimesse:
            self.lavoro.di(f"rimetto in coda {esito.rimesse} file fatti con la versione "
                           "vecchia di SeedVR2, per rifarli con quella nuova")
        if esito.saltate:
            quanti = len(esito.saltate)
            self.lavoro.di(f"{quanti} file fatti con la versione vecchia restano come sono: "
                           "l'elenco è nella pagina")

    def _conta_la_memoria(self, miglioria_id: int, senza_memoria: list[int]) -> list[int]:
        with self.archivio.lettura() as connessione:
            dopo = coda.per_id(connessione, miglioria_id)
        if dopo is None:
            return senza_memoria
        if dopo["stato"] != coda.FALLITA:
            return []
        if dopo["guasto"] != SCHEDA_FINITA:
            return senza_memoria
        senza_memoria = [*senza_memoria, miglioria_id]
        if len(senza_memoria) < DI_FILA_SENZA_MEMORIA:
            return senza_memoria
        with self.archivio.scrittura() as connessione:
            for chi in senza_memoria:
                coda.segna(connessione, chi, coda.IN_CODA, guasto=None, finita_il=None)
        self.lavoro.di(f"rimessi in coda {len(senza_memoria)} file: la scheda video era piena")
        raise ErroreOfficina(SCHEDA_OCCUPATA, codice=SCHEDA_FINITA)

    def _uno(self, riga) -> None:
        miglioria_id = riga["id"]
        originale = Path(riga["percorso_originale"])
        with self.archivio.lettura() as connessione:
            file = file_media.per_id(connessione, riga["file_id"])
            dove = attesa.cartella(connessione, originale, self.archivio.dove.radice)
        partito = time.monotonic()
        self.adesso = {"id": miglioria_id, "nome": originale.name,
                       "fatti": 0, "totale": 0, "partito_il": time.time(),
                       "disco": self._disco}
        self.lavoro.di(f"lavoro «{originale.name}»")

        if file is None:
            self._fallita(miglioria_id, "originale_assente")
            return
        letto, piu, codice = self._originale(riga, originale)
        if codice in DA_RIFARE_DOPO:
            self._aspetta_l_archivio(miglioria_id, originale, codice)
            return
        if codice is not None:
            self._fallita(miglioria_id, codice)
            return
        if piu is not None:
            self.adesso["dall_archivio"] = True

        attesa.prepara(dove)
        genere = file["genere"]
        if genere == "video":
            self._guarda_il_120()
        tetto = self._tetto()
        serve = int(letto.stat().st_size * quanto_puo_crescere(tetto)) + MARGINE_DI_SPAZIO
        if genere == "video":
            serve += spazio_dei_pezzi(letto, tetto)
            serve += spazio_dei_120(letto, tetto, self._fps120())
        if shutil.disk_usage(dove).free < serve:
            self._fallita(miglioria_id, "spazio")
            return

        suffisso = (originale.suffix if genere == "immagine"
                    else video.suffisso_di_arrivo(originale))
        finale = dove / attesa.nome_in_attesa(miglioria_id, originale, suffisso)
        parziale = finale.with_name(finale.name + attesa.PARZIALE)

        lavoro = self._il_lavoro(genere, originale, riga["file_id"], piu)
        al_passo = self._al_passo
        in_sfida = self._in_sfida(genere)
        self._prevedi(partito, file, lavoro, in_sfida)

        if in_sfida:
            self._due_versioni(miglioria_id, originale, lavoro, finale, al_passo)
            return

        esito = self._una_versione(lavoro, parziale, al_passo)
        if esito is None:
            self._rimetti_in_coda(miglioria_id)
            return
        if esito.get("guasto") in RAM_POCHE:
            self._ram_poca(miglioria_id, originale, esito)
            return
        if esito.get("guasto") in DA_RIFARE_DOPO:
            self._aspetta_l_archivio(miglioria_id, originale, esito["guasto"])
            return
        if "guasto" in esito:
            self._non_riuscita(miglioria_id, esito)
            return

        os.replace(parziale, finale)
        if genere == "video":
            self._copie_da_guardare(miglioria_id, originale, finale, dal_disco=piu is None)
        fatto = esito["fatto"]
        fedele = self._fedelta(genere, letto, finale)
        sua_impronta = impronta.del_file(finale)
        with self.archivio.scrittura() as connessione:
            coda.segna(connessione, miglioria_id, coda.DA_RIVEDERE,
                       in_revisione=str(finale), fedelta=json.dumps(fedele),
                       impronta_migliorata=sua_impronta,
                       larghezza_dopo=int(fatto.get("larghezza") or 0) or None,
                       altezza_dopo=int(fatto.get("altezza") or 0) or None,
                       motori=json.dumps(fatto.get("motori") or []),
                       finita_il=adesso())
            self._misurato(connessione, miglioria_id, fatto)
        self.lavoro.di(f"pronto da rivedere: «{originale.name}»{misura_del_motore(fatto)}")

    def _originale(self, riga, originale: Path):
        if originale.is_file():
            if impronta.del_file(originale) != riga["impronta_originale"]:
                return None, None, "originale_cambiato"
            return originale, None, None
        file_id = riga["file_id"]
        try:
            with self.archivio.lettura() as connessione:
                file = file_media.per_id(connessione, file_id)
                if file is None:
                    return None, None, "originale_assente"
                if file["impronta"] != riga["impronta_originale"]:
                    return None, None, "originale_cambiato"
                ricerca = file_media.cerca_nell_archivio(connessione, file_id)
                percorsi = [r["percorso"] for r in file_media.percorsi_di(connessione,
                                                                          file_id)]
                date = (None if ricerca.trovata is None else
                        file_media.date_nell_archivio(connessione, file_id, originale))
        except ErroreOfficina as errore:
            registro.avviso("miglioria.archivio_non_risponde",
                            motivo=registro.Parola(errore.codice))
            return None, None, CHIUSO_ADESSO
        trovata = ricerca.trovata
        if ricerca.perche in (CHIUSO, SI_APRE):
            return None, None, CHIUSO_ADESSO
        if trovata is None:
            return None, None, "originale_assente"
        if trovata.diversa or trovata.blake2b != riga["impronta_originale"]:
            return None, None, DIVERSA
        if date is None:
            return None, None, CHIUSO_ADESSO
        cercata = {"impronta": riga["impronta_originale"], "dimensione": file["dimensione"],
                   "percorsi": percorsi, "nome": originale.name}
        return trovata, {"dall_archivio": cercata, "date": date}, None

    def rispondi_per_la_ram(self, scelta: str) -> bool:
        if scelta not in RISPOSTE_PER_LA_RAM:
            return False
        self._scelta = scelta
        self._risposta.set()
        return True

    def _ram_poca(self, miglioria_id: int, originale: Path, esito: dict) -> None:
        codice = esito["guasto"]
        serve, libera = _byte(esito.get("serve")), _byte(esito.get("libera"))
        with self.archivio.scrittura() as connessione:
            coda.segna(connessione, miglioria_id, coda.IN_CODA, guasto=codice)
        registro.avviso("miglioria.ram_poca", motivo=registro.Parola(codice),
                        serve_gb=in_giga(serve), libera_gb=in_giga(libera))
        anche = codice == RAM_POCA_COL_DISCO
        self._scelta = None
        self._risposta.clear()
        self.adesso = {"id": miglioria_id, "nome": originale.name, "fatti": 0, "totale": 0,
                       "ram": {"serve": giga_in_su(serve), "libera": libera // GIGA,
                               "anche_col_disco": anche, "disco": self._disco,
                               "aspetto": False}}
        self.lavoro.di(f"«{originale.name}»: {a_parole(codice)}. Aspetto che si liberi"
                       + ("" if anche else ", o che tu scelga di usare il disco"))
        self._aspetta_la_ram(serve, anche)
        self.adesso = {}

    def _aspetta_la_ram(self, serve: int, anche: bool) -> None:
        from officina.miglioria import ram

        while not self._fermati.is_set():
            self._risposta.wait(OGNI_QUANTO_LA_RAM)
            self._risposta.clear()
            if self._fermati.is_set():
                return
            if self._scelta == "disco" and not anche:
                self._disco = True
                registro.evento("miglioria.ram_col_disco")
                self.lavoro.di("una parte dei pesi di SeedVR2 resta sul disco, fino alla "
                               "fine del giro")
                return
            if self._scelta == "aspetto" and not self.adesso["ram"]["aspetto"]:
                self.adesso = {**self.adesso, "ram": {**self.adesso["ram"], "aspetto": True}}
            libera = ram.libera()
            if serve and libera is not None and libera >= serve:
                self.lavoro.di("la RAM si è liberata: riprendo")
                return

    def _aspetta_l_archivio(self, miglioria_id: int, originale: Path, codice: str) -> None:
        with self.archivio.scrittura() as connessione:
            coda.segna(connessione, miglioria_id, coda.IN_CODA, guasto=codice)
        self._salta.add(miglioria_id)
        registro.avviso("miglioria.aspetta_l_archivio", motivo=registro.Parola(codice))
        self.lavoro.di(f"«{originale.name}»: {a_parole(codice)}")

    def _il_lavoro(self, genere: str, originale: Path, file_id: int,
                   piu: dict | None = None) -> dict:
        scelti = self._scelti()
        chi = []
        if genere == "immagine" and scelti.get("volti") == motori.FACEME:
            with self.archivio.lettura() as connessione:
                chi = persone.nella_foto(connessione, file_id)
        return {
            "genere": genere,
            "originale": str(originale),
            "motori": scelti,
            "persone": chi,
            "intensita": int(self.archivio.impostazione("intensita_scheda") or 100),
            "misura": self._tetto(),
            **({"fps120": self._fps120()} if genere == "video" and self._fps120() else {}),
            **({"veloce": accese} if (accese := self._veloce()) else {}),
            "percorsi": percorsi_della_stanza(),
            "opzioni": {"cartella_modelli": str(self.archivio.dove.modelli),
                        **({"disco": True} if self._disco else {})},
            **(piu or {}),
        }

    def _veloce(self) -> list[str]:
        from officina.miglioria import veloce

        return veloce.accese(self.archivio.impostazione(veloce.CHIAVE))

    def _fps120(self) -> str | None:
        return getattr(self, "_motore_120", None)

    def _guarda_il_120(self) -> None:
        from officina.miglioria import centoventi

        self._motore_120 = centoventi.motore_da_usare(self.archivio)

    def _tetto(self) -> str:
        from officina.miglioria import misura

        return misura.tetto_vero(self.archivio.impostazione(misura.CHIAVE))

    def _prevedi(self, partito: float, file, lavoro: dict, in_sfida: bool) -> None:
        dati = previsione.fattori(
            file, volti=len(lavoro["persone"]), dall_archivio="dall_archivio" in lavoro,
            sfida=in_sfida, disco=bool(lavoro["opzioni"].get("disco")),
            a_freddo=not self._accesa.accesa, intensita=lavoro["intensita"],
            tetto=lavoro.get("misura"),
            lucidflux=lavoro["motori"].get("foto") == motori.LUCIDFLUX,
            fluido=lavoro.get("fps120"))
        versione = _versione_di_seedvr2()
        try:
            with self.archivio.lettura() as connessione:
                prevista = previsione.prevedi(connessione, versione, dati)
        except Exception as guasto:
            registro.avviso("miglioria.previsione", **registro.dove_si_e_rotto(guasto))
            prevista = None
        self._misura = {"partito": partito, "fattori": dati, "prevista": prevista,
                        "versione": versione}
        if prevista is not None:
            self.adesso["prevista"] = prevista

    def _misurato(self, connessione, miglioria_id: int, fatto: dict) -> None:
        misura, self._misura = self._misura, None
        if misura is None or not any(
                isinstance(motore, dict) and (
                    motore.get("nome") == centoventi.NOME
                    or (motore.get("nome") == motori.SEEDVR2
                        and motore.get("versione") == misura["versione"]))
                for motore in fatto.get("motori") or []):
            return
        secondi = time.monotonic() - misura["partito"]
        previsione.registra(connessione, miglioria_id, misura["versione"], secondi,
                            misura["prevista"], misura["fattori"])
        registro.evento("miglioria.secondi", secondi=round(secondi, 1),
                        prevista=round(misura["prevista"] or 0, 1))

    def _al_passo(self, fatti: int, totale: int) -> None:
        self.adesso.update(fatti=fatti, totale=totale)
        self.lavoro.a_che_punto(fatti, totale)

    def _una_versione(self, lavoro: dict, parziale: Path, al_passo) -> dict | None:
        parziale.unlink(missing_ok=True)
        try:
            esito = self._lancia(dict(lavoro, uscita=str(parziale)), al_passo,
                                 self._ricorda)
        finally:
            self._processo = None
        if self._fermati.is_set():
            parziale.unlink(missing_ok=True)
            return None
        if "guasto" in esito and esito["guasto"] not in DA_RIPRENDERE:
            pezzi.butta(pezzi.cartella(parziale))
            pezzi.butta(fluido.cartella(parziale))
        if "guasto" in esito or not parziale.is_file():
            parziale.unlink(missing_ok=True)
            return {"guasto": str(esito.get("guasto") or "stanza_muta"),
                    "dove": esito.get("dove", ""), "riga": esito.get("riga", ""),
                    "tipo": esito.get("tipo", ""),
                    "spiegazione": esito.get("spiegazione", ""),
                    **{chiave: esito[chiave] for chiave in ("serve", "libera")
                       if chiave in esito}}
        return esito

    def _fedelta(self, genere: str, originale: Path, finale: Path) -> dict:
        self.lavoro.di(f"controllo di fedeltà «{originale.name}»")
        rilevatore = None
        try:
            from officina import volti as volti_mod
            rilevatore = volti_mod.apri(self.archivio)
        except Exception as errore:                      # noqa: BLE001
            registro.avviso("miglioria.fedelta_senza_volti",
                            motivo=registro.tipo_di(errore))
        try:
            return fedelta.controlla(genere, originale, finale, rilevatore)
        finally:
            if rilevatore is not None:
                try:
                    rilevatore.spegni()
                except Exception:                        # noqa: BLE001
                    pass

    def _rimetti_in_coda(self, miglioria_id: int) -> None:
        with self.archivio.scrittura() as connessione:
            coda.segna(connessione, miglioria_id, coda.IN_CODA, guasto=None)

    def _non_riuscita(self, miglioria_id: int, esito: dict) -> None:
        codice = esito["guasto"]
        if codice != catena.GIA_GRANDE:
            registro.errore("miglioria.fallita", motivo=registro.Parola(codice),
                            tipo=registro.Parola(str(esito.get("tipo", ""))),
                            dove=registro.Parola(str(esito.get("dove", ""))),
                            riga=str(esito.get("riga", "")))
        self._fallita(miglioria_id, codice)

    def _due_versioni(self, miglioria_id: int, originale: Path, lavoro: dict,
                      finale: Path, al_passo) -> None:
        fatte: dict = {}
        saltata: dict | None = None
        for passo, motore in enumerate(sfida.SFIDANTI, start=1):
            arrivo = finale.with_name(f"{finale.stem}.{motore}{finale.suffix}")
            parziale = arrivo.with_name(arrivo.name + attesa.PARZIALE)
            self.adesso.update(sfidante=sfida.NOMI[motore], versione=passo,
                               versioni=len(sfida.SFIDANTI), fatti=0, totale=0)
            self.lavoro.di(f"lavoro «{originale.name}» per la sfida alla cieca: "
                           f"{sfida.NOMI[motore]}, versione {passo} di {len(sfida.SFIDANTI)}")
            scelti = dict(lavoro["motori"], foto=motore)
            inizio = time.monotonic()
            esito = self._una_versione(dict(lavoro, motori=scelti), parziale, al_passo)
            durata = time.monotonic() - inizio
            if esito is None or esito.get("guasto") in DA_RIFARE_DOPO | RAM_POCHE:
                sfida.butta([dati[0] for dati in fatte.values()])
                if esito is None:
                    self._rimetti_in_coda(miglioria_id)
                elif esito["guasto"] in RAM_POCHE:
                    self._ram_poca(miglioria_id, originale, esito)
                else:
                    self._aspetta_l_archivio(miglioria_id, originale, esito["guasto"])
                return
            if "guasto" in esito:
                if motore == motori.SEEDVR2:
                    self._non_riuscita(miglioria_id, esito)
                    return
                saltata = esito
                break
            os.replace(parziale, arrivo)
            fatte[motore] = (arrivo, impronta.del_file(arrivo), esito["fatto"], durata)

        base = fatte[motori.SEEDVR2][2]
        with self.archivio.scrittura() as connessione:
            if len(fatte) == len(sfida.SFIDANTI):
                coda.segna(connessione, miglioria_id, coda.DA_RIVEDERE, in_revisione=None,
                           larghezza_dopo=int(base.get("larghezza") or 0) or None,
                           altezza_dopo=int(base.get("altezza") or 0) or None,
                           finita_il=adesso())
                sfida.registra(connessione, miglioria_id, {
                    motore: (dati[0], dati[1], dati[2].get("motori"), dati[3])
                    for motore, dati in fatte.items()})
                sfida.segna_il_salto(connessione, None)
                self._misurato(connessione, miglioria_id, base)
                misura = misura_di_lucidflux(fatte[motori.LUCIDFLUX][2])
                self.lavoro.di(f"pronto da votare: «{originale.name}»{misura}")
                return
            arrivo, sua_impronta, _fatto, _durata = fatte[motori.SEEDVR2]
            coda.segna(connessione, miglioria_id, coda.DA_RIVEDERE,
                       in_revisione=str(arrivo), impronta_migliorata=sua_impronta,
                       larghezza_dopo=int(base.get("larghezza") or 0) or None,
                       altezza_dopo=int(base.get("altezza") or 0) or None,
                       motori=json.dumps(base.get("motori") or []),
                       finita_il=adesso())
            self._lucidflux_saltato(connessione, miglioria_id, saltata)
            self._misurato(connessione, miglioria_id, base)
        self.lavoro.di(f"pronto da rivedere: «{originale.name}», senza sfida: "
                       f"LucidFlux non è riuscito ({perche_saltata(saltata)})")
        self._se_in_pausa()

    def _lucidflux_saltato(self, connessione, miglioria_id: int, esito: dict) -> None:
        registro.avviso("miglioria.sfida_saltata",
                        motivo=registro.Parola(esito["guasto"]),
                        tipo=registro.Parola(str(esito.get("tipo", ""))),
                        dove=registro.Parola(str(esito.get("dove", ""))),
                        riga=str(esito.get("riga", "")))
        sfida.segna_il_salto(connessione, esito)
        self._saltate_in_sfida.add(miglioria_id)

    def _se_in_pausa(self) -> None:
        with self.archivio.lettura() as connessione:
            ferma = sfida.in_pausa(connessione)
        if ferma:
            self.lavoro.di(f"sfida in pausa: LucidFlux non è riuscito su {sfida.PAUSA_DOPO} "
                           "foto di fila, le prossime le fa solo SeedVR2")

    def _riprendi_la_sfida(self) -> int:
        with self.archivio.lettura() as connessione:
            if not sfida.si_fa(connessione, True) or sfida.in_pausa(connessione):
                return 0
            da_fare = [riga for riga in sfida.da_riprendere(connessione)
                       if riga["id"] not in self._saltate_in_sfida]
        if not da_fare or not self._sfidanti_pronti():
            return 0
        self.lavoro.di(f"LucidFlux riprende {len(da_fare)} foto già fatte da SeedVR2, "
                       "per la sfida alla cieca")
        fatte = 0
        for riga in da_fare:
            if self._fermati.is_set():
                break
            with self.archivio.lettura() as connessione:
                if not sfida.si_fa(connessione, True) or sfida.in_pausa(connessione):
                    break
            self._riprendi_una(riga)
            fatte += 1
        return fatte

    def _riprendi_una(self, riga) -> None:
        miglioria_id = riga["id"]
        originale = Path(riga["percorso_originale"])
        tenuta = Path(riga["in_revisione"])
        self.adesso = {"id": miglioria_id, "nome": originale.name, "fatti": 0,
                       "totale": 0, "ripresa": True}
        self.lavoro.di(f"LucidFlux riprende «{originale.name}» per la sfida alla cieca")
        if not (tenuta.is_file() and attesa.e_dentro(tenuta)):
            self._non_ripresa(originale, *NON_RIPRESA["originale_assente"])
            return
        if impronta.del_file(tenuta) != riga["impronta_migliorata"]:
            self._non_ripresa(originale, *NON_RIPRESA["originale_cambiato"])
            return
        letto, piu, codice = self._originale(riga, originale)
        if codice is not None:
            perche = NON_RIPRESA.get(codice, (codice, a_parole(codice)))
            self._non_ripresa(originale, *perche)
            return
        serve = (int(letto.stat().st_size * quanto_puo_crescere(self._tetto()))
                 + MARGINE_DI_SPAZIO)
        if shutil.disk_usage(tenuta.parent).free < serve:
            self._non_ripresa(originale, "spazio", "manca spazio sul disco")
            return
        finale = tenuta.parent / attesa.nome_in_attesa(miglioria_id, originale,
                                                       originale.suffix)
        arrivo = finale.with_name(f"{finale.stem}.{motori.LUCIDFLUX}{finale.suffix}")
        parziale = arrivo.with_name(arrivo.name + attesa.PARZIALE)
        lavoro = self._il_lavoro("immagine", originale, riga["file_id"], piu)
        lavoro["motori"] = dict(lavoro["motori"], foto=motori.LUCIDFLUX)
        inizio = time.monotonic()
        esito = self._una_versione(lavoro, parziale, self._al_passo)
        durata = time.monotonic() - inizio
        if esito is None:
            return
        if esito.get("guasto") in DA_RIFARE_DOPO:
            self._non_ripresa(originale, esito["guasto"], a_parole(esito["guasto"]))
            return
        if "guasto" in esito:
            with self.archivio.scrittura() as connessione:
                self._lucidflux_saltato(connessione, miglioria_id, esito)
            self.lavoro.di(f"«{originale.name}» resta solo di SeedVR2: LucidFlux non è "
                           f"riuscito ({perche_saltata(esito)})")
            self._se_in_pausa()
            return
        os.replace(parziale, arrivo)
        sua_impronta = impronta.del_file(arrivo)
        with self.archivio.scrittura() as connessione:
            adesso_e = coda.per_id(connessione, miglioria_id)
            entra = (adesso_e is not None and adesso_e["stato"] == coda.DA_RIVEDERE
                     and adesso_e["in_revisione"] == riga["in_revisione"]
                     and adesso_e["impronta_migliorata"] == riga["impronta_migliorata"]
                     and sfida.per_miglioria(connessione, miglioria_id) is None
                     and sfida.si_fa(connessione, True))
            if entra:
                coda.segna(connessione, miglioria_id, coda.DA_RIVEDERE, in_revisione=None,
                           impronta_migliorata=None, motori=None, fedelta=None)
                sfida.registra(connessione, miglioria_id, {
                    motori.SEEDVR2: (tenuta, riga["impronta_migliorata"],
                                     json.loads(riga["motori"] or "[]"),
                                     previsione.secondi_veri(connessione, miglioria_id)),
                    motori.LUCIDFLUX: (arrivo, sua_impronta, esito["fatto"].get("motori"),
                                       durata)})
                sfida.segna_il_salto(connessione, None)
        if not entra:
            sfida.butta([arrivo])
            self.lavoro.di(f"«{originale.name}» era già stata decisa: la versione di "
                           "LucidFlux non serve più")
            return
        misura = misura_di_lucidflux(esito["fatto"])
        self.lavoro.di(f"pronto da votare: «{originale.name}»{misura}")

    def _non_ripresa(self, originale: Path, codice: str, perche: str) -> None:
        registro.avviso("miglioria.sfida_non_ripresa", motivo=registro.Parola(codice))
        self.lavoro.di(f"«{originale.name}» resta solo di SeedVR2: {perche}")

    def _copie_da_guardare(self, miglioria_id: int, originale: Path,
                           finale: Path, dal_disco: bool = True) -> None:
        lati = {da_guardare.DOPO: finale}
        if dal_disco:
            lati[da_guardare.PRIMA] = originale
        if not da_guardare.mancano(self.archivio.dove, miglioria_id, lati):
            return
        self.lavoro.di(f"preparo la copia da guardare di «{originale.name}»")
        try:
            da_guardare.fai(self.archivio.dove, miglioria_id, lati,
                            fermati=self._fermati, al_passo=self.lavoro.a_che_punto)
        except da_guardare.Fermato:
            return
        except Exception as errore:
            registro.avviso("miglioria.copia_da_guardare",
                            **registro.dove_si_e_rotto(errore))

    def _fallita(self, miglioria_id: int, codice: str) -> None:
        with self.archivio.scrittura() as connessione:
            riga = coda.per_id(connessione, miglioria_id)
            if riga is not None and codice not in DA_RIPRENDERE:
                pezzi.butta_quelli_di(attesa.cartella(connessione,
                                                      Path(riga["percorso_originale"]),
                                                      self.archivio.dove.radice),
                                      miglioria_id)
            coda.segna(connessione, miglioria_id, coda.FALLITA, guasto=codice,
                       finita_il=adesso())
        self.lavoro.di(f"non riuscito: {a_parole(codice)}")

