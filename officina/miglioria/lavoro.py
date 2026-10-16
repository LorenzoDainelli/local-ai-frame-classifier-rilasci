from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Callable

from officina import registro
from officina.archivio.database import adesso
from officina.errori import ErroreOfficina
from officina.importazione import impronta
from officina.miglioria import (attesa, catena, coda, da_guardare, fedelta, motori, persone,
                                scambio, sfida, video)
from officina.modello import file_media
from officina.web.lavori import Lavoro

MARGINE_DI_SPAZIO = 512 * 1024 * 1024
QUANTO_PUO_CRESCERE = 12
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
    "gia_grande": "è già FHD o più",
    "memoria_finita": "è finita la memoria del computer",
    "memoria_scheda_finita": "è finita la memoria della scheda video",
    "motore_mancante": "il modello che serve non è ancora stato preparato",
    "stanza_caduta": "il modello si è fermato di colpo",
    "stanza_muta": "il modello non ha detto com'è andata",
    "solo_foto": "questo modello migliora solo le foto",
    "lavoro_illeggibile": "difetto del programma nel preparare il lavoro",
    "rotto": "difetto imprevisto: il dettaglio tecnico è nel registro",
    "torch_troppo_vecchio": ("il motore delle reti neurali è troppo vecchio per aprire "
                             "i pesi in sicurezza: aggiorna i motori"),
}


def a_parole(codice: str | None) -> str:
    if not codice:
        return ""
    return MESSAGGI.get(codice, codice)


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


def lancia_la_stanza(lavoro: dict, al_passo: Callable[[int, int], None],
                     ricorda: Callable[[subprocess.Popen], None]) -> dict:
    from officina.programma import librerie, scheda

    comando = [librerie.python_per_i_comandi(), "-m", "officina.miglioria.stanza"]
    processo = subprocess.Popen(
        comando, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, cwd=str(librerie.RADICE), text=True,
        encoding="utf-8", creationflags=scheda.SENZA_FINESTRA)
    ricorda(processo)
    esito: dict | None = None
    try:
        processo.stdin.write(json.dumps(lavoro))
        processo.stdin.close()
        for riga in processo.stdout:
            try:
                messaggio = json.loads(riga)
            except ValueError:
                continue
            if "fatti" in messaggio:
                al_passo(int(messaggio["fatti"]), int(messaggio.get("totale") or 0))
            elif "fatto" in messaggio or "guasto" in messaggio:
                esito = messaggio
    finally:
        codice_di_uscita = processo.wait()
    if esito is None:
        esito = {"guasto": "stanza_muta" if codice_di_uscita == 0 else "stanza_caduta"}
    return esito


class Miglioratore:

    def __init__(self, archivio, lancia: Callable[..., dict] | None = None,
                 motori_scelti: dict | None = None,
                 sfidanti_pronti: Callable[[], bool] | None = None):
        self.archivio = archivio
        self._lancia = lancia or lancia_la_stanza
        self.motori_scelti = motori_scelti
        self._sfidanti_pronti = sfidanti_pronti or self._ci_sono_tutti_e_due
        self.lavoro = Lavoro("miglioramento", scheda=True)
        self._fermati = threading.Event()
        self._processo: subprocess.Popen | None = None
        self.adesso: dict = {}

    @property
    def sta_lavorando(self) -> bool:
        return self.lavoro.sta_lavorando

    def parti(self) -> bool:
        self._fermati.clear()
        return self.lavoro.parti(self._gira, nome="miglioramento")

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
            if not sfida.si_fa(connessione, True):
                return False
        return bool(self._sfidanti_pronti())

    def _gira(self) -> None:
        riparato = scambio.ripara(self.archivio)
        with self.archivio.lettura() as connessione:
            tenute = {riga["id"] for riga in coda.in_stato(connessione, coda.DA_RIVEDERE)}
        da_guardare.pulisci(self.archivio.dove, tenute)
        if riparato["riprese"]:
            self.lavoro.di(f"riprendo {riparato['riprese']} file lasciati a metà")
        fatti = 0
        senza_memoria: list[int] = []
        try:
            while not self._fermati.is_set():
                with self.archivio.scrittura() as connessione:
                    riga = coda.prossima(connessione)
                    if riga is None:
                        break
                    coda.segna(connessione, riga["id"], coda.IN_LAVORO, guasto=None)
                self._uno(riga)
                fatti += 1
                senza_memoria = self._conta_la_memoria(riga["id"], senza_memoria)
        finally:
            self.adesso = {}
            registro.evento("miglioria.giro", fatti=fatti,
                            fermato=self._fermati.is_set())

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
            dove = attesa.cartella(connessione, originale)
        self.adesso = {"id": miglioria_id, "nome": originale.name,
                       "fatti": 0, "totale": 0}
        self.lavoro.di(f"lavoro «{originale.name}»")

        if file is None or not originale.is_file():
            self._fallita(miglioria_id, "originale_assente")
            return
        if impronta.del_file(originale) != riga["impronta_originale"]:
            self._fallita(miglioria_id, "originale_cambiato")
            return

        attesa.prepara(dove)
        serve = originale.stat().st_size * QUANTO_PUO_CRESCERE + MARGINE_DI_SPAZIO
        if shutil.disk_usage(dove).free < serve:
            self._fallita(miglioria_id, "spazio")
            return

        genere = file["genere"]
        suffisso = (originale.suffix if genere == "immagine"
                    else video.suffisso_di_arrivo(originale))
        finale = dove / attesa.nome_in_attesa(miglioria_id, originale, suffisso)
        parziale = finale.with_name(finale.name + attesa.PARZIALE)

        scelti = self._scelti()
        chi = []
        if genere == "immagine" and scelti.get("volti") == motori.FACEME:
            with self.archivio.lettura() as connessione:
                chi = persone.nella_foto(connessione, riga["file_id"])
        lavoro = {
            "genere": genere,
            "originale": str(originale),
            "motori": scelti,
            "persone": chi,
            "intensita": int(self.archivio.impostazione("intensita_scheda") or 100),
            "percorsi": percorsi_della_stanza(),
            "opzioni": {"cartella_modelli": str(self.archivio.dove.modelli)},
        }

        def al_passo(fatti: int, totale: int) -> None:
            self.adesso.update(fatti=fatti, totale=totale)
            self.lavoro.a_che_punto(fatti, totale)

        if self._in_sfida(genere):
            self._due_versioni(miglioria_id, originale, lavoro, finale, al_passo)
            return

        esito = self._una_versione(lavoro, parziale, al_passo)
        if esito is None:
            self._rimetti_in_coda(miglioria_id)
            return
        if "guasto" in esito:
            self._non_riuscita(miglioria_id, esito)
            return

        os.replace(parziale, finale)
        if genere == "video":
            self._copie_da_guardare(miglioria_id, originale, finale)
        fatto = esito["fatto"]
        fedele = self._fedelta(genere, originale, finale)
        sua_impronta = impronta.del_file(finale)
        with self.archivio.scrittura() as connessione:
            coda.segna(connessione, miglioria_id, coda.DA_RIVEDERE,
                       in_revisione=str(finale), fedelta=json.dumps(fedele),
                       impronta_migliorata=sua_impronta,
                       larghezza_dopo=int(fatto.get("larghezza") or 0) or None,
                       altezza_dopo=int(fatto.get("altezza") or 0) or None,
                       motori=json.dumps(fatto.get("motori") or []),
                       finita_il=adesso())
        self.lavoro.di(f"pronto da rivedere: «{originale.name}»")

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
        if "guasto" in esito or not parziale.is_file():
            parziale.unlink(missing_ok=True)
            return {"guasto": str(esito.get("guasto") or "stanza_muta"),
                    "dove": esito.get("dove", ""), "riga": esito.get("riga", ""),
                    "tipo": esito.get("tipo", "")}
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
        for motore in sfida.SFIDANTI:
            arrivo = finale.with_name(f"{finale.stem}.{motore}{finale.suffix}")
            parziale = arrivo.with_name(arrivo.name + attesa.PARZIALE)
            self.lavoro.di(f"lavoro «{originale.name}» per la sfida alla cieca")
            scelti = dict(lavoro["motori"], foto=motore)
            esito = self._una_versione(dict(lavoro, motori=scelti), parziale, al_passo)
            if esito is None:
                sfida.butta([dati[0] for dati in fatte.values()])
                self._rimetti_in_coda(miglioria_id)
                return
            if "guasto" in esito:
                if motore == motori.SEEDVR2:
                    self._non_riuscita(miglioria_id, esito)
                    return
                registro.avviso("miglioria.sfida_saltata",
                                motivo=registro.Parola(esito["guasto"]))
                break
            os.replace(parziale, arrivo)
            fatte[motore] = (arrivo, impronta.del_file(arrivo), esito["fatto"])

        base = fatte[motori.SEEDVR2][2]
        with self.archivio.scrittura() as connessione:
            if len(fatte) == len(sfida.SFIDANTI):
                coda.segna(connessione, miglioria_id, coda.DA_RIVEDERE, in_revisione=None,
                           larghezza_dopo=int(base.get("larghezza") or 0) or None,
                           altezza_dopo=int(base.get("altezza") or 0) or None,
                           finita_il=adesso())
                sfida.registra(connessione, miglioria_id, {
                    motore: (dati[0], dati[1], dati[2].get("motori"))
                    for motore, dati in fatte.items()})
                self.lavoro.di(f"pronto da votare: «{originale.name}»")
                return
            arrivo, sua_impronta, _fatto = fatte[motori.SEEDVR2]
            coda.segna(connessione, miglioria_id, coda.DA_RIVEDERE,
                       in_revisione=str(arrivo), impronta_migliorata=sua_impronta,
                       larghezza_dopo=int(base.get("larghezza") or 0) or None,
                       altezza_dopo=int(base.get("altezza") or 0) or None,
                       motori=json.dumps(base.get("motori") or []),
                       finita_il=adesso())
        self.lavoro.di(f"pronto da rivedere: «{originale.name}», senza sfida")

    def _copie_da_guardare(self, miglioria_id: int, originale: Path,
                           finale: Path) -> None:
        lati = {da_guardare.PRIMA: originale, da_guardare.DOPO: finale}
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
            coda.segna(connessione, miglioria_id, coda.FALLITA, guasto=codice,
                       finita_il=adesso())
        self.lavoro.di(f"non riuscito: {a_parole(codice)}")

