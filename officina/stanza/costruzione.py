from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from officina import istruzioni, registro
from officina.archivio.database import tutti
from officina.descrittori import torcia
from officina.errori import ErroreOfficina
from officina.importazione import gruppi
from officina.stanza import da3, vggt

VERSIONE = "1-vggt-omega-da3"
NOME = "stanza"
FILE_VGGT = f"vggt-omega/{vggt.FILE_PESI}"
FILE_DA3 = f"depth-anything-3/{da3.FILE_PESI}"
FOTO_MINIME = 5
FOTO_MASSIME = 50
AGGANCI = 16
NUOVE_A_TURNO = 24
DA3_A_TURNO = 24
LATO_DI_LETTURA = 1024
STANZE_DI_FILA_SENZA_MEMORIA = 3
TROPPO_GRANDE = "La scheda video non ha abbastanza memoria per questa stanza."
STANZA_SENZA_MEMORIA = "stanza_senza_memoria"
VOXEL = 0.015
PUNTI_MASSIMI = 1_500_000
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
    scatto_id: int
    immagine: object
    persone: object = None


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


def punti_di_una_foto(esito: dict, numero: int, persone=None):
    import numpy as np

    from officina.stanza.da3 import DEVIAZIONE, MEDIA

    profondita = np.asarray(esito["profondita"][numero])
    fiducia = np.asarray(esito["fiducia"][numero])
    alto, largo = profondita.shape
    buoni = np.isfinite(profondita) & (profondita > 0) & ~np.asarray(esito["cielo"][numero])
    buoni &= fiducia >= np.percentile(fiducia, PERCENTILE_DI_FIDUCIA)
    if persone is not None and np.asarray(persone).any():
        buoni &= ~persone_allargate(persone, largo, alto)
    righe, colonne = np.nonzero(buoni)
    z = profondita[righe, colonne].astype(np.float64)
    matrice = np.asarray(esito["intrinseci"][numero], dtype=np.float64)
    x = (colonne - matrice[0, 2]) / matrice[0, 0] * z
    y = (righe - matrice[1, 2]) / matrice[1, 1] * z
    camera = np.stack([x, y, z], axis=1)
    estrinseci = np.asarray(esito["estrinseci"][numero], dtype=np.float64)
    mondo = (camera - estrinseci[:3, 3]) @ estrinseci[:3, :3]
    immagine = np.asarray(esito["immagini"][numero], dtype=np.float64).transpose(1, 2, 0)
    immagine = np.clip(immagine * np.asarray(DEVIAZIONE) + np.asarray(MEDIA), 0, 1)
    colori = (immagine[righe, colonne] * 255).round().astype(np.uint8)
    return mondo, colori


def a_cubetti(punti, colori, lato: float = VOXEL, massimi: int = PUNTI_MASSIMI, seme: int = 0):
    import numpy as np

    if not len(punti):
        return punti, colori
    chiavi = np.floor(punti / lato).astype(np.int64)
    _, primi = np.unique(chiavi, axis=0, return_index=True)
    primi.sort()
    punti, colori = punti[primi], colori[primi]
    if len(punti) > massimi:
        scelti = np.sort(np.random.default_rng(seme).choice(len(punti), size=massimi, replace=False))
        punti, colori = punti[scelti], colori[scelti]
    return punti, colori


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
        from officina.modello import stanze

        self.avanzamento.non_riuscite += 1
        with self.archivio.scrittura() as connessione:
            stanze.non_riuscita(connessione, posto_id, VERSIONE, len(foto_del_posto(connessione, posto_id)),
                                perche)

    def _leggi(self, scatto_id: int) -> Foto | None:
        from officina.corpi import figure
        from officina.corpi import rilevatore as rilevatore_mod
        from officina.immagini import lettura
        from officina.modello import file_media

        with self.archivio.lettura() as connessione:
            principale = next((f for f in file_media.di_scatto(connessione, scatto_id)
                               if f["ruolo"] == "principale"), None)
            if principale is None or principale["genere"] != "immagine":
                return None
            percorso = file_media.percorso_migliore(connessione, principale["id"])
            corpi = tutti(connessione, "SELECT riquadro, maschera FROM corpi WHERE scatto_id = ? "
                          "AND fotogramma = 0 AND modello = ?", scatto_id, rilevatore_mod.NOME)
        if percorso is None:
            return None
        try:
            immagine = lettura.copia_di_lavoro(Path(percorso), LATO_DI_LETTURA).convert("RGB")
        except Exception:                                # noqa: BLE001
            return None
        persone = None
        if corpi:
            import json

            import numpy as np

            larga, alta = immagine.size
            persone = np.zeros((alta, larga), dtype=bool)
            for corpo in corpi:
                persone |= figure.maschera_intera(corpo["maschera"], json.loads(corpo["riquadro"]),
                                                  larga, alta).astype(bool)
        return Foto(scatto_id, immagine, persone)

    def _scegli(self, scatti: list[int]) -> list[int]:
        with self.archivio.lettura() as connessione:
            vettori = impronte_di(connessione, scatti)
        con = [s for s in scatti if s in vettori]
        senza = [s for s in scatti if s not in vettori]
        if not con:
            return scatti[:FOTO_MASSIME]
        scelti = [con[i] for i in le_piu_diverse([vettori[s] for s in con], FOTO_MASSIME)]
        return (scelti + senza)[:FOTO_MASSIME]

    def _costruisci(self, posto_id: int) -> None:
        import numpy as np

        from officina.modello import stanze

        with self.archivio.lettura() as connessione:
            tutte = foto_del_posto(connessione, posto_id)
        foto = []
        for scatto_id in self._scegli(tutte):
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
        nuvole, colori, scale = [], [], []
        for pezzo in _a_gruppi(foto):
            if self.fermata:
                return
            esito = self.modelli.forma([foto[i].immagine for i in pezzo], omogenee(estrinseci[pezzo]),
                                       np.asarray([sulla_foto[i] for i in pezzo], dtype=np.float32))
            scale.append(float(esito["allineamento"][2]))
            for posto, i in enumerate(pezzo):
                punti, tinte = punti_di_una_foto(esito, posto, foto[i].persone)
                nuvole.append(punti)
                colori.append(tinte)
        metri = float(np.median(scale))
        punti = np.concatenate(nuvole) if nuvole else np.zeros((0, 3))
        tinte = np.concatenate(colori) if colori else np.zeros((0, 3), dtype=np.uint8)
        sistemazione, misure = sistema(estrinseci, punti, metri)
        punti, tinte = a_cubetti(sistemazione.punti(punti), tinte)
        nome = f"{posto_id}.npz"
        _salva_la_nuvola(self.archivio.dove.stanze / nome, punti, tinte)
        centri, rotazioni = sistemazione.macchine(*centri_e_rotazioni(estrinseci))
        with self.archivio.scrittura() as connessione:
            stanze.salva(connessione, posto_id, nome, VERSIONE, len(foto), len(tutte), len(punti), misure, metri)
            insieme = zip(foto, centri, rotazioni, sulla_foto, strict=True)
            for ordine, (letta, centro, rotazione, matrice) in enumerate(insieme):
                larga, alta = letta.immagine.size
                campo, cx, cy, proporzione, allungo = _campo_e_centro(matrice, larga, alta)
                stanze.metti_foto(connessione, posto_id, letta.scatto_id, usata=True, ordine=ordine,
                                  centro=centro, rotazione=rotazione, campo=campo, centro_x=cx, centro_y=cy,
                                  proporzione=proporzione, allungo=allungo)
        self.avanzamento.stanze += 1
        self.avanzamento.foto_messe += len(foto)
        registro.evento("stanza.costruita", foto=len(foto), punti=len(punti))
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
        lette_agganci = [(a, self._leggi(a["scatto_id"])) for a in agganci]
        lette_agganci = [(a, f) for a, f in lette_agganci if f is not None]
        if len(lette_agganci) < 3:
            return self._segna_viste(posto_id)
        centri_veri = np.asarray([a["centro"] for a, _ in lette_agganci], dtype=np.float64)
        for inizio in range(0, len(nuove), NUOVE_A_TURNO):
            if self.fermata:
                return
            lette = [f for f in (self._leggi(s) for s in nuove[inizio:inizio + NUOVE_A_TURNO]) if f is not None]
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


def _salva_la_nuvola(percorso: Path, punti, colori) -> None:
    import numpy as np

    percorso.parent.mkdir(parents=True, exist_ok=True)
    provvisorio = percorso.with_name(percorso.name + f".{os.getpid()}.{int(time.time() * 1000)}.tmp")
    with open(provvisorio, "wb") as f:
        np.savez_compressed(f, punti=np.asarray(punti, dtype=np.float16), colori=np.asarray(colori, dtype=np.uint8))
    os.replace(provvisorio, percorso)


def leggi_la_nuvola(percorso: Path):
    import numpy as np

    with np.load(percorso) as dati:
        return dati["punti"].astype(np.float32), dati["colori"].astype(np.uint8)


def foto_del_posto(connessione, posto_id: int) -> list[int]:
    return [riga["id"] for riga in tutti(
        connessione,
        f"SELECT DISTINCT s.id FROM scatti s JOIN posti_negli_scatti n ON n.scatto_id = s.id "
        f"WHERE n.posto_id = ? AND s.fuori_archivio = 0 AND s.genere IN ('foto','live')"
        f"{gruppi.clausola(connessione, 'intelligenza')} ORDER BY coalesce(s.istante_utc, ''), s.id",
        posto_id)]


def da_fare(connessione) -> list[tuple[int, str]]:
    righe = tutti(
        connessione,
        f"SELECT p.id, count(DISTINCT s.id) AS quante FROM posti p "
        f"JOIN posti_negli_scatti n ON n.posto_id = p.id JOIN scatti s ON s.id = n.scatto_id "
        f"WHERE p.stato = 'attivo' AND s.fuori_archivio = 0 AND s.genere IN ('foto','live')"
        f"{gruppi.clausola(connessione, 'intelligenza')} GROUP BY p.id HAVING quante >= ? ORDER BY p.id",
        FOTO_MINIME)
    fatte = {riga["posto_id"]: riga for riga in tutti(connessione, "SELECT * FROM stanze")}
    lavoro = []
    for riga in righe:
        stanza = fatte.get(riga["id"])
        if stanza is None or stanza["versione"] != VERSIONE:
            lavoro.append((riga["id"], "costruisci"))
        elif stanza["stato"] != "fatta":
            if stanza["foto_viste"] != riga["quante"]:
                lavoro.append((riga["id"], "costruisci"))
        else:
            messe = tutti(connessione, "SELECT count(*) AS q FROM stanze_foto f JOIN posti_negli_scatti n "
                          "ON n.scatto_id = f.scatto_id AND n.posto_id = f.posto_id WHERE f.posto_id = ?",
                          riga["id"])[0]["q"]
            if messe < riga["quante"] and riga["quante"] != stanza["foto_viste"]:
                lavoro.append((riga["id"], "metti"))
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
