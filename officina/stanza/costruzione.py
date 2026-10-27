from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from officina import istruzioni, registro
from officina.archivio.database import tutti, uno
from officina.descrittori import torcia
from officina.errori import DaRifare, ErroreOfficina, FileNonLeggibile
from officina.importazione import gruppi
from officina.sicuro import dall_archivio
from officina.stanza import da3, dettaglio, versioni, vggt

VERSIONE = "2-4k-versioni"
NOME = "stanza"
FILE_VGGT = f"vggt-omega/{vggt.FILE_PESI}"
FILE_DA3 = f"depth-anything-3/{da3.FILE_PESI}"
FOTO_MINIME = 5
FOTO_MASSIME = 50
AGGANCI = 16
NUOVE_A_TURNO = 24
DA3_A_TURNO = 24
LATO_DI_LETTURA = 3840
LATO_PER_METTERE = 1024
LATO_DELLE_PERSONE = 1024
STANZE_DI_FILA_SENZA_MEMORIA = 3
TROPPO_GRANDE = "La scheda video non ha abbastanza memoria per questa stanza."
STANZA_SENZA_MEMORIA = "stanza_senza_memoria"
VOXEL = 0.005
PUNTI_MASSIMI = 6_000_000
DETTAGLIO_PIENO = "4k"
DETTAGLIO_RIDOTTO = "ridotto"
PERCENTILE_DI_FIDUCIA = 40.0
ALLARGA_LE_PERSONE = 0.015
SCARTO_DEGLI_AGGANCI = 0.35


def dove_stanno(cartella_modelli: Path) -> Path:
    return Path(cartella_modelli) / "corpi" / NOME


def ci_sono(cartella_modelli: Path) -> bool:
    casa = dove_stanno(cartella_modelli)
    return (casa / FILE_VGGT).is_file() and (casa / FILE_DA3).is_file()


def cosa_manca(cartella_modelli: Path) -> str:
    if ci_sono(cartella_modelli):
        return ""
    return ("Per le stanze in 3D mancano VGGT-Omega e Depth Anything 3. Si scaricano\n\n"
            f"{istruzioni.modello('corpi')}\n\n"
            "VGGT-Omega chiede di accettare la sua licenza su Hugging Face.")


@dataclass
class Avanzamento:
    stanze: int = 0
    foto_messe: int = 0
    non_riuscite: int = 0
    fatti: int = 0
    totale: int = 0
    motivi: dict[str, int] = field(default_factory=dict)

    def a_parole(self) -> str:
        return (f"stanze in 3D: {self.stanze} costruite, {self.foto_messe} foto messe al loro posto"
                + (f" · non riuscite {self.non_riuscite}" if self.non_riuscite else ""))


@dataclass
class Foto:
    scatto_id: int | None
    immagine: object
    persone: object = None
    aiuto_id: int | None = None
    quando: str | None = None


class Modelli:

    def __init__(self, cartella_modelli: Path):
        self.casa = dove_stanno(cartella_modelli)
        self.dispositivo = torcia.macchina().dispositivo
        self._vggt = None
        self._da3 = None
        self._lucchetto = threading.Lock()

    def _mezza(self):
        import torch

        if self.dispositivo != "cuda":
            return None
        return torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16

    def posizioni(self, immagini) -> dict:
        with self._lucchetto:
            self._via_da3()
            if self._vggt is None:
                self._vggt = vggt.costruisci(self.casa / FILE_VGGT, self.dispositivo)
            return vggt.stima(self._vggt, immagini, in_mezza=self._mezza())

    def forma(self, immagini, estrinseci, intrinseci) -> dict:
        with self._lucchetto:
            self._via_vggt()
            if self._da3 is None:
                self._da3 = da3.costruisci(self.casa / FILE_DA3, self.dispositivo)
            return da3.stima(self._da3, immagini, estrinseci, intrinseci, in_mezza=self._mezza())

    def dettaglio(self, immagine):
        with self._lucchetto:
            self._via_vggt()
            if self._da3 is None:
                self._da3 = da3.costruisci(self.casa / FILE_DA3, self.dispositivo)
            return da3.stima(self._da3, [immagine], in_mezza=self._mezza())["profondita"][0]

    def _via_vggt(self) -> None:
        if self._vggt is not None:
            self._vggt = None
            torcia.libera()

    def _via_da3(self) -> None:
        if self._da3 is not None:
            self._da3 = None
            torcia.libera()

    def spegni(self) -> None:
        with self._lucchetto:
            self._via_vggt()
            self._via_da3()


def le_piu_diverse(vettori, quante: int) -> list[int]:
    import numpy as np

    vettori = np.asarray(vettori, dtype=np.float64)
    if len(vettori) <= quante:
        return list(range(len(vettori)))
    vettori = vettori / np.maximum(np.linalg.norm(vettori, axis=1, keepdims=True), 1e-12)
    primo = int(np.argmax(vettori @ vettori.mean(axis=0)))
    scelti = [primo]
    lontane = 1.0 - vettori @ vettori[primo]
    lontane[primo] = -np.inf
    while len(scelti) < quante:
        nuova = int(np.argmax(lontane))
        scelti.append(nuova)
        lontane = np.minimum(lontane, 1.0 - vettori @ vettori[nuova])
        lontane[scelti] = -np.inf
    return scelti


def raddrizza(estrinseci):
    import numpy as np

    rotazioni = np.asarray(estrinseci, dtype=np.float64)[:, :3, :3]
    su = -rotazioni[:, 1, :].mean(axis=0)
    su /= max(np.linalg.norm(su), 1e-12)
    avanti = rotazioni[0, 2, :] - np.dot(rotazioni[0, 2, :], su) * su
    if np.linalg.norm(avanti) < 1e-6:
        avanti = np.cross(su, [1.0, 0.0, 0.0])
    avanti /= np.linalg.norm(avanti)
    dietro = -avanti
    destra = np.cross(su, dietro)
    return np.stack([destra, su, dietro])


def persone_allargate(persone, largo: int, alto: int):
    import numpy as np
    from PIL import Image, ImageFilter

    lato = max(1, int(round(ALLARGA_LE_PERSONE * max(largo, alto))))
    piccola = Image.fromarray(np.asarray(persone, dtype=np.uint8) * 255, "L").resize((largo, alto),
                                                                                    Image.Resampling.NEAREST)
    return np.asarray(piccola.filter(ImageFilter.MaxFilter(2 * lato + 1))) > 0


def buoni_di(esito: dict, numero: int, persone=None):
    import numpy as np

    profondita = np.asarray(esito["profondita"][numero])
    fiducia = np.asarray(esito["fiducia"][numero])
    alto, largo = profondita.shape
    buoni = np.isfinite(profondita) & (profondita > 0) & ~np.asarray(esito["cielo"][numero])
    buoni &= fiducia >= np.percentile(fiducia, PERCENTILE_DI_FIDUCIA)
    if persone is not None and np.asarray(persone).any():
        buoni &= ~persone_allargate(persone, largo, alto)
    return buoni


def dalla_profondita(profondita, buoni, matrice, estrinseci, colori):
    import numpy as np

    profondita = np.asarray(profondita)
    righe, colonne = np.nonzero(buoni)
    z = profondita[righe, colonne].astype(np.float64)
    matrice = np.asarray(matrice, dtype=np.float64)
    x = (colonne - matrice[0, 2]) / matrice[0, 0] * z
    y = (righe - matrice[1, 2]) / matrice[1, 1] * z
    camera = np.stack([x, y, z], axis=1)
    estrinseci = np.asarray(estrinseci, dtype=np.float64)
    mondo = (camera - estrinseci[:3, 3]) @ estrinseci[:3, :3]
    return mondo, np.asarray(colori)[righe, colonne], z / max(float(matrice[0, 0]), 1e-9)


def colori_di(esito: dict, numero: int):
    import numpy as np

    from officina.stanza.da3 import DEVIAZIONE, MEDIA

    immagine = np.asarray(esito["immagini"][numero], dtype=np.float64).transpose(1, 2, 0)
    immagine = np.clip(immagine * np.asarray(DEVIAZIONE) + np.asarray(MEDIA), 0, 1)
    return (immagine * 255).round().astype(np.uint8)


def punti_di_una_foto(esito: dict, numero: int, persone=None):
    mondo, colori, _ = dalla_profondita(esito["profondita"][numero], buoni_di(esito, numero, persone),
                                        esito["intrinseci"][numero], esito["estrinseci"][numero],
                                        colori_di(esito, numero))
    return mondo, colori


def a_cubetti(punti, colori, lato: float = VOXEL, massimi: int = PUNTI_MASSIMI, seme: int = 0,
              passi=None, gruppi=None):
    import numpy as np

    if not len(punti):
        return (punti, colori) if passi is None and gruppi is None else (punti, colori, passi, gruppi)
    ordine = np.argsort(passi, kind="stable") if passi is not None else np.arange(len(punti))
    interi = np.floor(np.asarray(punti, dtype=np.float64)[ordine] / lato).astype(np.int64) + (1 << 18)
    interi = np.clip(interi, 0, (1 << 19) - 1)
    chiavi = (((interi[:, 0] << 38) | (interi[:, 1] << 19) | interi[:, 2]) << 4)
    if gruppi is not None:
        chiavi |= np.asarray(gruppi, dtype=np.int64)[ordine] & 15
    _, primi = np.unique(chiavi, return_index=True)
    scelti = np.sort(ordine[primi])
    if len(scelti) > massimi:
        scelti = np.sort(np.random.default_rng(seme).choice(scelti, size=massimi, replace=False))
    fuori = (np.asarray(punti)[scelti], np.asarray(colori)[scelti])
    if passi is None and gruppi is None:
        return fuori
    return (*fuori, None if passi is None else np.asarray(passi)[scelti],
            None if gruppi is None else np.asarray(gruppi)[scelti])


def centri_e_rotazioni(estrinseci):
    import numpy as np

    estrinseci = np.asarray(estrinseci, dtype=np.float64)
    rotazioni = np.transpose(estrinseci[:, :3, :3], (0, 2, 1))
    centri = -np.einsum("nij,nj->ni", rotazioni, estrinseci[:, :3, 3])
    return centri, rotazioni


def omogenee(estrinseci):
    import numpy as np

    estrinseci = np.asarray(estrinseci, dtype=np.float32)
    piene = np.repeat(np.eye(4, dtype=np.float32)[None], len(estrinseci), 0)
    piene[:, :3, :4] = estrinseci[:, :3, :4]
    return piene


@dataclass
class Sistemazione:
    rotazione: object
    spostamento: object
    metri: float

    def punti(self, punti):
        import numpy as np

        return self.metri * (np.asarray(punti, dtype=np.float64) @ self.rotazione.T) + self.spostamento

    def macchine(self, centri, rotazioni):
        import numpy as np

        return self.punti(centri), np.einsum("ij,njk->nik", self.rotazione, rotazioni)


def sistema(estrinseci, punti, metri: float) -> tuple[Sistemazione, tuple[float, float, float]]:
    import numpy as np

    rotazione = raddrizza(estrinseci)
    girati = metri * (np.asarray(punti, dtype=np.float64) @ rotazione.T)
    if len(girati):
        basso, alto = np.percentile(girati, [2, 98], axis=0)
    else:
        basso = alto = np.zeros(3)
    spostamento = -np.array([(basso[0] + alto[0]) / 2, basso[1], (basso[2] + alto[2]) / 2])
    misure = (float(alto[0] - basso[0]), float(alto[2] - basso[2]), float(alto[1] - basso[1]))
    return Sistemazione(rotazione, spostamento, float(metri)), misure


def _campo_e_centro(intrinseci, larga: int, alta: int):
    import math

    return (2.0 * math.atan(alta / (2.0 * float(intrinseci[1][1]))), float(intrinseci[0][2]) / larga,
            float(intrinseci[1][2]) / alta, larga / alta, float(intrinseci[0][0]) / float(intrinseci[1][1]))


class Passata:

    def __init__(self, archivio, modelli: Modelli | None = None, fermato: Callable[[], bool] | None = None):
        self.archivio = archivio
        self.modelli = modelli
        self._fermato = fermato or (lambda: False)
        self._ferma = threading.Event()
        self.avanzamento = Avanzamento()
        self._dettaglio_pieno = True

    def ferma(self) -> None:
        self._ferma.set()

    @property
    def fermata(self) -> bool:
        return self._ferma.is_set() or self._fermato()

    def quanti_mancano(self) -> int:
        with self.archivio.lettura() as connessione:
            return len(da_fare(connessione))

    def esegui(self, al_passo: Callable[[Avanzamento], None] | None = None) -> Avanzamento:
        with self.archivio.lettura() as connessione:
            lavoro = da_fare(connessione)
        self.avanzamento.totale = len(lavoro)
        if not lavoro:
            return self.avanzamento
        if self.modelli is None:
            self.modelli = Modelli(self.archivio.dove.modelli)
        memoria = torcia.ContoDellaMemoria(di_fila=STANZE_DI_FILA_SENZA_MEMORIA)
        try:
            for posto_id, cosa in lavoro:
                if self.fermata:
                    break
                try:
                    if cosa == "costruisci":
                        self._costruisci(posto_id)
                    else:
                        self._metti_le_nuove(posto_id)
                except DaRifare as errore:
                    self.avanzamento.motivi[errore.codice] = (
                        self.avanzamento.motivi.get(errore.codice, 0) + 1)
                except ErroreOfficina as errore:
                    if errore.codice == STANZA_SENZA_MEMORIA:
                        memoria.finita(posto_id, errore)
                    else:
                        self._non_riuscita(posto_id, errore.messaggio)
                except Exception as guasto:              # noqa: BLE001
                    if torcia.memoria_finita(guasto):
                        memoria.finita(posto_id, guasto)
                    else:
                        registro.avviso("stanza.non_riuscita", **registro.dove_si_e_rotto(guasto))
                        self._non_riuscita(posto_id, "La stanza non si è lasciata costruire.")
                else:
                    for pesante in memoria.riuscito():
                        self._non_riuscita(pesante, TROPPO_GRANDE)
                self.avanzamento.fatti += 1
                if al_passo:
                    al_passo(self.avanzamento)
        finally:
            self.modelli.spegni()
        registro.evento("stanza.passata", stanze=self.avanzamento.stanze, foto=self.avanzamento.foto_messe)
        return self.avanzamento

    def _non_riuscita(self, posto_id: int, perche: str) -> None:
        from officina.modello import aiuti, stanze

        self.avanzamento.non_riuscite += 1
        with self.archivio.scrittura() as connessione:
            stanze.non_riuscita(connessione, posto_id, VERSIONE, len(foto_del_posto(connessione, posto_id)),
                                perche, aiuti.quanti_di_posto(connessione, posto_id))

    def _persone(self, connessione, scatto_id: int, larga: int, alta: int):
        import json

        import numpy as np

        from officina.corpi import figure
        from officina.corpi import rilevatore as rilevatore_mod

        corpi = tutti(connessione, "SELECT riquadro, maschera FROM corpi WHERE scatto_id = ? "
                      "AND fotogramma = 0 AND modello = ?", scatto_id, rilevatore_mod.NOME)
        if not corpi:
            return None
        scala = min(1.0, LATO_DELLE_PERSONE / max(larga, alta))
        larga, alta = max(1, round(larga * scala)), max(1, round(alta * scala))
        persone = np.zeros((alta, larga), dtype=bool)
        for corpo in corpi:
            persone |= figure.maschera_intera(corpo["maschera"], json.loads(corpo["riquadro"]),
                                              larga, alta).astype(bool)
        return persone

    def _leggi(self, scatto_id: int, lato: int = LATO_DI_LETTURA) -> Foto | None:
        from officina.immagini import lettura
        from officina.modello import file_media

        with self.archivio.lettura() as connessione:
            principale = next((f for f in file_media.di_scatto(connessione, scatto_id)
                               if f["ruolo"] == "principale"), None)
            if principale is None or principale["genere"] != "immagine":
                return None
            try:
                percorso = file_media.da_guardare(connessione, principale["id"])
            except FileNonLeggibile:
                return None
            quando = uno(connessione, "SELECT data_locale FROM scatti WHERE id = ?", scatto_id)
        if percorso is None:
            return None
        try:
            with dall_archivio.attento(percorso):
                immagine = lettura.copia_di_lavoro(percorso, lato).convert("RGB")
        except DaRifare:
            raise
        except Exception:                                # noqa: BLE001
            return None
        with self.archivio.lettura() as connessione:
            persone = self._persone(connessione, scatto_id, *immagine.size)
        return Foto(scatto_id, immagine, persone, quando=quando["data_locale"] if quando else None)

    def _leggi_aiuto(self, voce: dict, lato: int = LATO_DI_LETTURA) -> Foto | None:
        from officina.immagini import lettura
        from officina.modello import aiuti

        try:
            immagine = lettura.copia_di_lavoro(aiuti.percorso(self.archivio, voce), lato).convert("RGB")
        except Exception:                                # noqa: BLE001
            return None
        return Foto(None, immagine, None, aiuto_id=voce["aiuto_id"], quando=voce["quando"])

    def _scegli(self, scatti: list[int], quante: int = FOTO_MASSIME) -> list[int]:
        if quante <= 0:
            return []
        with self.archivio.lettura() as connessione:
            vettori = impronte_di(connessione, scatti)
        con = [s for s in scatti if s in vettori]
        senza = [s for s in scatti if s not in vettori]
        if not con:
            return scatti[:quante]
        scelti = [con[i] for i in le_piu_diverse([vettori[s] for s in con], quante)]
        return (scelti + senza)[:quante]

    def _forma_grezza(self, foto: list[Foto], estrinseci, sulla_foto) -> tuple[list, list[float]]:
        import numpy as np

        grezze: list = [None] * len(foto)
        scale = []
        for pezzo in _a_gruppi(foto):
            if self.fermata:
                return [], []
            esito = self.modelli.forma([foto[i].immagine for i in pezzo], omogenee(estrinseci[pezzo]),
                                       np.asarray([sulla_foto[i] for i in pezzo], dtype=np.float32))
            scale.append(float(esito["allineamento"][2]))
            for posto, i in enumerate(pezzo):
                grezze[i] = {"profondita": np.asarray(esito["profondita"][posto], dtype=np.float32),
                             "buoni": buoni_di(esito, posto, foto[i].persone),
                             "intrinseci": np.asarray(esito["intrinseci"][posto], dtype=np.float64),
                             "estrinseci": np.asarray(esito["estrinseci"][posto], dtype=np.float64),
                             "colori": colori_di(esito, posto)}
        return grezze, scale

    def _fine(self, foto: Foto, grezza: dict):
        stima = getattr(self.modelli, "dettaglio", None)
        if stima is None or not self._dettaglio_pieno:
            return None
        import cv2
        import numpy as np

        try:
            profondita = dettaglio.profondita_fine(stima, foto.immagine, grezza["profondita"],
                                                   lambda: self.fermata)
        except Exception as guasto:
            if not torcia.memoria_finita(guasto):
                raise
            torcia.libera()
            self._dettaglio_pieno = False
            registro.avviso("stanza.dettaglio_ridotto")
            return None
        if profondita is None:
            return None
        alta, larga = profondita.shape
        grezza_alta, grezza_larga = grezza["profondita"].shape
        buoni = dettaglio.allarga(grezza["buoni"], larga, alta) & np.isfinite(profondita) & (profondita > 0)
        if foto.persone is not None and np.asarray(foto.persone).any():
            buoni &= ~persone_allargate(foto.persone, larga, alta)
        colori = cv2.resize(np.asarray(foto.immagine), (larga, alta), interpolation=cv2.INTER_AREA)
        matrice = dettaglio.matrice_a_misura(grezza["intrinseci"], grezza_larga, grezza_alta, larga, alta)
        return profondita, buoni, matrice, colori

    def _costruisci(self, posto_id: int) -> None:
        import numpy as np

        from officina.modello import aiuti, stanze

        with self.archivio.lettura() as connessione:
            tutte = foto_del_posto(connessione, posto_id)
            di_aiuto = aiuti.di_posto(connessione, posto_id)
        foto = []
        for voce in di_aiuto[:FOTO_MASSIME]:
            if self.fermata:
                return
            letta = self._leggi_aiuto(voce)
            if letta is not None:
                foto.append(letta)
        for scatto_id in self._scegli(tutte, FOTO_MASSIME - len(foto)):
            if self.fermata:
                return
            letta = self._leggi(scatto_id)
            if letta is not None:
                foto.append(letta)
        if len(foto) < FOTO_MINIME:
            raise ErroreOfficina(f"Servono almeno {FOTO_MINIME} foto che si aprono, qui ce ne sono {len(foto)}.")
        posizioni = self._posizioni_robuste(foto)
        foto = foto[:len(posizioni["estrinseci"])]
        estrinseci = posizioni["estrinseci"]
        sulla_foto = [vggt.intrinseci_sulla_foto(k, v)
                      for k, v in zip(posizioni["intrinseci"], posizioni["viaggi"], strict=True)]
        grezze, scale = self._forma_grezza(foto, estrinseci, sulla_foto)
        if not grezze:
            return
        metri = float(np.median(scale))
        nuvole_grezze = [dalla_profondita(g["profondita"], g["buoni"], g["intrinseci"], g["estrinseci"],
                                          g["colori"])[0] for g in grezze]
        tutti_i_grezzi = np.concatenate(nuvole_grezze) if nuvole_grezze else np.zeros((0, 3))
        sistemazione, misure = sistema(estrinseci, tutti_i_grezzi, metri)
        del tutti_i_grezzi
        viste = [versioni.Vista(g["profondita"], g["intrinseci"], g["estrinseci"], g["buoni"], f.quando)
                 for f, g in zip(foto, grezze, strict=True)]
        cambi = versioni.trova([sistemazione.punti(n) for n in nuvole_grezze], viste, sistemazione)
        del nuvole_grezze, viste
        self._dettaglio_pieno = True
        punti = np.zeros((0, 3))
        tinte = np.zeros((0, 3), dtype=np.uint8)
        passi = np.zeros(0)
        gruppi = np.zeros(0, dtype=np.uint8)
        for numero, (letta, grezza) in enumerate(zip(foto, grezze, strict=True)):
            if self.fermata:
                return
            fine = self._fine(letta, grezza)
            if fine is None:
                fine = (grezza["profondita"], grezza["buoni"], grezza["intrinseci"], grezza["colori"])
            nuovi, colori, passo = dalla_profondita(*fine[:3], grezza["estrinseci"], fine[3])
            nuovi = sistemazione.punti(nuovi)
            passo = passo * metri
            gruppo = versioni.gruppi_dei_punti(nuovi, cambi.gruppo_della_foto[numero], cambi)
            punti, tinte, passi, gruppi = a_cubetti(np.concatenate([punti, nuovi]), np.concatenate([tinte, colori]),
                                                    massimi=PUNTI_MASSIMI * 2, passi=np.concatenate([passi, passo]),
                                                    gruppi=np.concatenate([gruppi, gruppo]))
            grezze[numero] = None
        punti, tinte, passi, gruppi = a_cubetti(punti, tinte, passi=passi, gruppi=gruppi)
        nome = f"{posto_id}.npz"
        _salva_la_nuvola(self.archivio.dove.stanze / nome, punti, tinte, gruppi)
        centri, rotazioni = sistemazione.macchine(*centri_e_rotazioni(estrinseci))
        elenco = _elenco_delle_versioni(cambi, foto, gruppi)
        livello = DETTAGLIO_PIENO if self._dettaglio_pieno else DETTAGLIO_RIDOTTO
        with self.archivio.scrittura() as connessione:
            stanze.salva(connessione, posto_id, nome, VERSIONE, len(foto), len(tutte), len(punti), misure, metri,
                         aiuti_visti=len(di_aiuto), versioni=elenco, dettaglio=livello)
            insieme = zip(foto, centri, rotazioni, sulla_foto, strict=True)
            ordine = 0
            for letta, centro, rotazione, matrice in insieme:
                if letta.scatto_id is None:
                    continue
                larga, alta = letta.immagine.size
                campo, cx, cy, proporzione, allungo = _campo_e_centro(matrice, larga, alta)
                stanze.metti_foto(connessione, posto_id, letta.scatto_id, usata=True, ordine=ordine,
                                  centro=centro, rotazione=rotazione, campo=campo, centro_x=cx, centro_y=cy,
                                  proporzione=proporzione, allungo=allungo)
                ordine += 1
        self.avanzamento.stanze += 1
        self.avanzamento.foto_messe += sum(1 for f in foto if f.scatto_id is not None)
        registro.evento("stanza.costruita", foto=len(foto), punti=len(punti), versioni=len(elenco),
                        dettaglio=livello)
        self._metti_le_nuove(posto_id)

    def _posizioni_robuste(self, foto: list[Foto]) -> dict:
        quante = len(foto)
        while True:
            try:
                return self.modelli.posizioni([f.immagine for f in foto[:quante]])
            except Exception as guasto:
                if not torcia.memoria_finita(guasto):
                    raise
                torcia.libera()
                if quante <= FOTO_MINIME * 2:
                    raise ErroreOfficina(TROPPO_GRANDE, codice=STANZA_SENZA_MEMORIA) from None
                quante = max(FOTO_MINIME * 2, quante * 2 // 3)
                registro.avviso("stanza.meno_foto", foto=quante)

    def _segna_viste(self, posto_id: int) -> None:
        from officina.modello import stanze

        with self.archivio.scrittura() as connessione:
            stanze.viste(connessione, posto_id, len(foto_del_posto(connessione, posto_id)))

    def _metti_le_nuove(self, posto_id: int) -> None:
        import numpy as np

        from officina.modello import stanze
        from officina.stanza.allineamento import umeyama

        with self.archivio.lettura() as connessione:
            nuove = [s for s in foto_del_posto(connessione, posto_id)
                     if s not in stanze.gia_messi(connessione, posto_id)]
            agganci = stanze.agganci(connessione, posto_id, AGGANCI)
        if not nuove or len(agganci) < 3:
            return self._segna_viste(posto_id)
        lette_agganci = [(a, self._leggi(a["scatto_id"], LATO_PER_METTERE)) for a in agganci]
        lette_agganci = [(a, f) for a, f in lette_agganci if f is not None]
        if len(lette_agganci) < 3:
            return self._segna_viste(posto_id)
        centri_veri = np.asarray([a["centro"] for a, _ in lette_agganci], dtype=np.float64)
        for inizio in range(0, len(nuove), NUOVE_A_TURNO):
            if self.fermata:
                return
            lette = [f for f in (self._leggi(s, LATO_PER_METTERE) for s in nuove[inizio:inizio + NUOVE_A_TURNO])
                     if f is not None]
            if not lette:
                continue
            immagini = [f.immagine for _, f in lette_agganci] + [f.immagine for f in lette]
            posizioni = self.modelli.posizioni(immagini)
            centri, rotazioni = centri_e_rotazioni(posizioni["estrinseci"])
            quanti = len(lette_agganci)
            try:
                r, t, s = umeyama(centri[:quanti].T, centri_veri.T)
            except ValueError:
                continue
            spostati = (s * (centri[:quanti] @ r.T)) + t
            ampiezza = max(float(np.linalg.norm(centri_veri - centri_veri.mean(0), axis=1).max()), 0.3)
            if float(np.median(np.linalg.norm(spostati - centri_veri, axis=1))) > SCARTO_DEGLI_AGGANCI * ampiezza:
                registro.avviso("stanza.agganci_lontani", foto=len(lette))
                continue
            with self.archivio.scrittura() as connessione:
                for posto, letta in enumerate(lette, start=quanti):
                    larga, alta = letta.immagine.size
                    matrice = vggt.intrinseci_sulla_foto(posizioni["intrinseci"][posto], posizioni["viaggi"][posto])
                    campo, cx, cy, proporzione, allungo = _campo_e_centro(matrice, larga, alta)
                    stanze.metti_foto(connessione, posto_id, letta.scatto_id, usata=False, ordine=None,
                                      centro=s * (r @ centri[posto]) + t, rotazione=r @ rotazioni[posto],
                                      campo=campo, centro_x=cx, centro_y=cy, proporzione=proporzione,
                                      allungo=allungo)
            self.avanzamento.foto_messe += len(lette)
        with self.archivio.scrittura() as connessione:
            stanze.viste(connessione, posto_id, len(foto_del_posto(connessione, posto_id)))


def _a_gruppi(foto: list[Foto]) -> list[list[int]]:
    per_misura: dict[tuple[int, int], list[int]] = {}
    for numero, letta in enumerate(foto):
        per_misura.setdefault(letta.immagine.size, []).append(numero)
    pezzi = []
    for numeri in per_misura.values():
        quanti = -(-len(numeri) // DA3_A_TURNO)
        passo = -(-len(numeri) // quanti)
        pezzi.extend(numeri[i:i + passo] for i in range(0, len(numeri), passo))
    return pezzi


def _salva_la_nuvola(percorso: Path, punti, colori, gruppi=None) -> None:
    import numpy as np

    percorso.parent.mkdir(parents=True, exist_ok=True)
    gruppi = np.zeros(len(punti), dtype=np.uint8) if gruppi is None else np.asarray(gruppi, dtype=np.uint8)
    provvisorio = percorso.with_name(percorso.name + f".{os.getpid()}.{int(time.time() * 1000)}.tmp")
    with open(provvisorio, "wb") as f:
        np.savez_compressed(f, punti=np.asarray(punti, dtype=np.float32), colori=np.asarray(colori, dtype=np.uint8),
                            gruppi=gruppi)
    os.replace(provvisorio, percorso)


def leggi_la_nuvola(percorso: Path):
    punti, colori, _ = leggi_tutta_la_nuvola(percorso)
    return punti, colori


def leggi_tutta_la_nuvola(percorso: Path):
    import numpy as np

    with np.load(percorso) as dati:
        punti = dati["punti"].astype(np.float32)
        gruppi = dati["gruppi"].astype(np.uint8) if "gruppi" in dati.files else np.zeros(len(punti), dtype=np.uint8)
        return punti, dati["colori"].astype(np.uint8), gruppi


def _elenco_delle_versioni(cambi, foto: list[Foto], gruppi) -> list[dict]:
    import numpy as np

    if not cambi.ci_sono:
        return []
    conti = np.bincount(np.asarray(gruppi, dtype=np.int64), minlength=len(cambi.versioni) + 1)
    elenco = []
    for versione in cambi.versioni:
        dentro = [foto[i] for i in versione["foto"]]
        elenco.append({"numero": versione["numero"], "dal": versione["dal"], "al": versione["al"],
                       "punti": int(conti[versione["numero"]]),
                       "scatti": [f.scatto_id for f in dentro if f.scatto_id is not None],
                       "aiuti": [f.aiuto_id for f in dentro if f.aiuto_id is not None]})
    return elenco


def foto_del_posto(connessione, posto_id: int) -> list[int]:
    return [riga["id"] for riga in tutti(
        connessione,
        f"SELECT DISTINCT s.id FROM scatti s JOIN posti_negli_scatti n ON n.scatto_id = s.id "
        f"WHERE n.posto_id = ? AND s.fuori_archivio = 0 AND s.genere IN ('foto','live')"
        f"{gruppi.clausola(connessione, 'intelligenza')} ORDER BY coalesce(s.istante_utc, ''), s.id",
        posto_id)]


def da_fare(connessione) -> list[tuple[int, str]]:
    quante = {riga["id"]: riga["quante"] for riga in tutti(
        connessione,
        f"SELECT p.id, count(DISTINCT s.id) AS quante FROM posti p "
        f"JOIN posti_negli_scatti n ON n.posto_id = p.id JOIN scatti s ON s.id = n.scatto_id "
        f"WHERE p.stato = 'attivo' AND s.fuori_archivio = 0 AND s.genere IN ('foto','live')"
        f"{gruppi.clausola(connessione, 'intelligenza')} GROUP BY p.id")}
    di_aiuto = {riga["posto_id"]: riga["quanti"] for riga in tutti(
        connessione,
        "SELECT a.posto_id, count(*) AS quanti FROM aiuti a JOIN posti p ON p.id = a.posto_id "
        "WHERE p.stato = 'attivo' GROUP BY a.posto_id")}
    fatte = {riga["posto_id"]: riga for riga in tutti(connessione, "SELECT * FROM stanze")}
    lavoro = []
    for posto_id in sorted(set(quante) | set(di_aiuto)):
        scatti, aiuti_qui = quante.get(posto_id, 0), di_aiuto.get(posto_id, 0)
        if scatti + aiuti_qui < FOTO_MINIME:
            continue
        stanza = fatte.get(posto_id)
        if stanza is None or stanza["versione"] != VERSIONE:
            lavoro.append((posto_id, "costruisci"))
        elif stanza["aiuti_visti"] != aiuti_qui:
            lavoro.append((posto_id, "costruisci"))
        elif stanza["stato"] != "fatta":
            if stanza["foto_viste"] != scatti:
                lavoro.append((posto_id, "costruisci"))
        else:
            messe = tutti(connessione, "SELECT count(*) AS q FROM stanze_foto f JOIN posti_negli_scatti n "
                          "ON n.scatto_id = f.scatto_id AND n.posto_id = f.posto_id WHERE f.posto_id = ?",
                          posto_id)[0]["q"]
            if messe < scatti and scatti != stanza["foto_viste"]:
                lavoro.append((posto_id, "metti"))
    return lavoro


def impronte_di(connessione, scatti: list[int]) -> dict[int, object]:
    import numpy as np

    from officina.modello import impronte as impronte_mod

    migliore, quante = None, 0
    for descrittore, versione in impronte_mod.modelli_presenti(connessione):
        elenco, _ = impronte_mod.passata(connessione, descrittore, versione, "intera", solo_scatti=scatti)
        if len(elenco) > quante:
            migliore, quante = (descrittore, versione), len(elenco)
    if migliore is None:
        return {}
    elenco, dati = impronte_mod.passata(connessione, *migliore, "intera", solo_scatti=scatti)
    return {scatto_id: np.frombuffer(valori, dtype="<f4")
            for scatto_id, valori in zip(elenco, dati, strict=True)}
