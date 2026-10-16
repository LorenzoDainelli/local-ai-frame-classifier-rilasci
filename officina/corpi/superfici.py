from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from officina import registro
from officina.archivio.database import adesso, tutti, uno
from officina.corpi import corpo3d, figure
from officina.corpi import rilevatore as rilevatore_mod
from officina.descrittori import torcia
from officina.importazione import gruppi

VERSIONE = f"1-mhr-{figure.ASPETTO}"
CORPI_A_TURNO = 8
GRIGLIA = 1024
PASSO_DEI_CAMPIONI = 1.25
CAMPIONI_MASSIMI = 24
FACCE_A_TURNO = 4096
TOLLERANZA = 0.02
ALLARGA_LA_MASCHERA = 2
FILE_DELLE_FACCE = "facce.npy"


@dataclass
class Avanzamento:
    fatti: int = 0
    superfici: int = 0
    saltati: int = 0
    totale: int = 0

    def a_parole(self) -> str:
        return (f"corpi veri in 3D: {self.superfici} persone in {self.fatti} foto"
                + (f" · saltati {self.saltati}" if self.saltati else ""))


def cosa_manca(cartella_modelli: Path) -> str:
    return figure.cosa_manca(cartella_modelli)


class Pelle:

    def __init__(self, cartella_modelli: Path):
        from officina.descrittori import torcia

        self.percorso = corpo3d.dove_stanno(cartella_modelli) / corpo3d.FILE_MHR
        self.dispositivo = torcia.macchina().dispositivo
        self._mhr = None

    def _accesa(self):
        if self._mhr is None:
            from officina.corpi import mhr

            self._mhr = mhr.Mhr.da_file(self.percorso, self.dispositivo)
        return self._mhr

    def facce(self):
        return self._accesa().facce.detach().cpu().numpy()

    def vertici(self, forme, parametri):
        import numpy as np
        import torch

        modello = self._accesa()
        with torch.no_grad():
            identita = torch.as_tensor(np.asarray(forme), dtype=torch.float32, device=self.dispositivo)
            posa = torch.as_tensor(np.asarray(parametri), dtype=torch.float32, device=self.dispositivo)
            espressioni = torch.zeros(identita.shape[0], modello.quante_espressioni, device=self.dispositivo)
            vertici, _ = modello(identita, posa, espressioni)
        vertici = vertici.double().cpu().numpy() / 100.0
        vertici[..., [1, 2]] *= -1
        return vertici

    def spegni(self) -> None:
        if self._mhr is not None:
            from officina.descrittori import torcia

            self._mhr = None
            torcia.libera()


def normali(vertici, facce):
    import numpy as np

    a, b, c = (vertici[facce[:, i]] for i in range(3))
    di_faccia = np.cross(b - a, c - a)
    somma = np.zeros_like(vertici)
    for i in range(3):
        np.add.at(somma, facce[:, i], di_faccia)
    unite = somma / np.maximum(np.linalg.norm(somma, axis=1, keepdims=True), 1e-12)
    if np.einsum("vd,vd->", vertici - vertici.mean(axis=0), unite) < 0:
        unite = -unite
    return unite


def proietta(punti, fuoco: float, proporzione: float):
    import numpy as np

    z = np.maximum(punti[:, 2], 1e-6)
    u = fuoco * punti[:, 0] / z / proporzione + 0.5
    v = fuoco * punti[:, 1] / z + 0.5
    return np.stack([u, v], axis=1), z


def _campioni(ordine: int):
    import numpy as np

    pesi = [(i, j, ordine - i - j) for i in range(ordine + 1) for j in range(ordine + 1 - i)]
    return np.asarray(pesi, dtype=np.float64) / ordine


def profondita_davanti(tutti_i_vertici, tutte_le_facce, fuoco: float, proporzione: float,
                       alta: int, larga: int):
    import numpy as np

    profondita = np.full((alta, larga), np.inf)
    for vertici, facce in zip(tutti_i_vertici, tutte_le_facce, strict=True):
        uv, _ = proietta(vertici, fuoco, proporzione)
        angoli = (uv * np.array([larga, alta]))[facce]
        lati = np.linalg.norm(angoli - np.roll(angoli, 1, axis=1), axis=2).max(axis=1)
        ordini = np.clip(np.ceil(lati / PASSO_DEI_CAMPIONI), 1, CAMPIONI_MASSIMI).astype(np.int64)
        for ordine in np.unique(ordini):
            pesi = _campioni(int(ordine))
            scelte = facce[ordini == ordine]
            for inizio in range(0, len(scelte), FACCE_A_TURNO):
                pezzo = vertici[scelte[inizio:inizio + FACCE_A_TURNO]]
                sparsi = np.einsum("sk,fkd->fsd", pesi, pezzo).reshape(-1, 3)
                dove, z = proietta(sparsi, fuoco, proporzione)
                x = np.floor(dove[:, 0] * larga).astype(np.int64)
                y = np.floor(dove[:, 1] * alta).astype(np.int64)
                dentro = (x >= 0) & (x < larga) & (y >= 0) & (y < alta) & (sparsi[:, 2] > 0)
                np.minimum.at(profondita, (y[dentro], x[dentro]), z[dentro])
    return profondita


def visti_dalla_foto(vertici, facce, profondita, maschera, fuoco: float, proporzione: float):
    import numpy as np

    alta, larga = profondita.shape
    uv, z = proietta(vertici, fuoco, proporzione)
    x = np.clip(np.floor(uv[:, 0] * larga).astype(np.int64), 0, larga - 1)
    y = np.clip(np.floor(uv[:, 1] * alta).astype(np.int64), 0, alta - 1)
    nella_foto = (uv[:, 0] >= 0) & (uv[:, 0] < 1) & (uv[:, 1] >= 0) & (uv[:, 1] < 1) & (vertici[:, 2] > 0)
    davanti = np.einsum("vd,vd->v", normali(vertici, facce), vertici) < 0
    non_coperti = z <= profondita[y, x] + TOLLERANZA
    nella_maschera = np.asarray(maschera, dtype=bool)[y, x]
    return nella_foto & davanti & non_coperti & nella_maschera, uv


def allarga(maschera, quanto: int):
    import numpy as np
    from PIL import Image, ImageFilter

    if quanto <= 0:
        return np.asarray(maschera, dtype=bool)
    immagine = Image.fromarray(np.asarray(maschera, dtype=np.uint8) * 255, "L")
    return np.asarray(immagine.filter(ImageFilter.MaxFilter(2 * quanto + 1))) > 0


def salva(percorso: Path, vertici_locali, spostamento, visti, uv) -> None:
    import numpy as np

    percorso.parent.mkdir(parents=True, exist_ok=True)
    provvisorio = percorso.with_name(percorso.name + f".{os.getpid()}.{int(time.time() * 1000)}.tmp")
    with open(provvisorio, "wb") as f:
        np.savez_compressed(
            f, vertici=np.asarray(vertici_locali, dtype=np.float16),
            spostamento=np.asarray(spostamento, dtype=np.float32),
            visti=np.asarray(visti, dtype=bool),
            uv=np.round(np.clip(np.asarray(uv), 0, 1) * 65535).astype(np.uint16))
    os.replace(provvisorio, percorso)


def leggi(percorso: Path) -> dict:
    import numpy as np

    with np.load(percorso) as dati:
        locali = dati["vertici"].astype(np.float32)
        spostamento = dati["spostamento"].astype(np.float32)
        return {"vertici": locali + spostamento, "locali": locali, "spostamento": spostamento,
                "visti": dati["visti"].astype(bool),
                "uv": dati["uv"].astype(np.float32) / 65535.0}


def leggi_le_facce(cartella: Path):
    import numpy as np

    percorso = cartella / FILE_DELLE_FACCE
    return np.load(percorso) if percorso.is_file() else None


def _salva_le_facce(cartella: Path, facce) -> None:
    import numpy as np

    cartella.mkdir(parents=True, exist_ok=True)
    percorso = cartella / FILE_DELLE_FACCE
    tipo = np.uint16 if int(facce.max()) < 65536 else np.uint32
    provvisorio = cartella / f"{FILE_DELLE_FACCE}.{os.getpid()}.tmp"
    with open(provvisorio, "wb") as f:
        np.save(f, np.asarray(facce, dtype=tipo))
    os.replace(provvisorio, percorso)


def _da_fare(connessione, cosa: str) -> str:
    return f"""
        SELECT {cosa} FROM scatti s
        WHERE s.fuori_archivio = 0 AND s.genere IN ('foto','live'){gruppi.clausola(connessione, "intelligenza")}
          AND EXISTS (
              SELECT 1 FROM corpi c JOIN aspetti a ON a.corpo_id = c.id AND a.modello = ?
              WHERE c.scatto_id = s.id AND c.modello = ? AND c.fotogramma = 0
                AND NOT EXISTS (SELECT 1 FROM superfici f WHERE f.corpo_id = c.id AND f.versione = ?))
        ORDER BY s.id
    """


def quanti_mancano_senza_aprire(connessione) -> int:
    riga = uno(connessione, _da_fare(connessione, "count(*) AS q"), figure.ASPETTO, rilevatore_mod.NOME,
               VERSIONE)
    return int(riga["q"]) if riga else 0


def di_scatto(connessione, scatto_id: int) -> dict[int, dict]:
    return {riga["corpo_id"]: dict(riga) for riga in tutti(
        connessione,
        "SELECT f.* FROM superfici f JOIN corpi c ON c.id = f.corpo_id "
        "WHERE c.scatto_id = ? AND c.fotogramma = 0 AND f.vertici > 0", scatto_id)}


class Passata:

    def __init__(self, archivio, pelle: Pelle | None = None, fermato: Callable[[], bool] | None = None):
        self.archivio = archivio
        self.pelle = pelle
        self.avanzamento = Avanzamento()
        self._fermati = threading.Event()
        self._fuori = fermato

    def ferma(self) -> None:
        self._fermati.set()

    @property
    def fermata(self) -> bool:
        return self._fermati.is_set() or bool(self._fuori and self._fuori())

    @property
    def cartella(self) -> Path:
        return self.archivio.dove.superfici

    def quanti_mancano(self) -> int:
        with self.archivio.lettura() as connessione:
            return quanti_mancano_senza_aprire(connessione)

    def esegui(self, al_passo: Callable[[Avanzamento], None] | None = None) -> Avanzamento:
        with self.archivio.lettura() as connessione:
            da_fare = [riga["id"] for riga in tutti(connessione, _da_fare(connessione, "s.id"), figure.ASPETTO,
                                                    rilevatore_mod.NOME, VERSIONE)]
        self.avanzamento.totale = len(da_fare)
        if not da_fare:
            self._pulisci()
            return self.avanzamento
        if self.pelle is None:
            self.pelle = Pelle(self.archivio.dove.modelli)
        try:
            facce = self.pelle.facce()
            _salva_le_facce(self.cartella, facce)
            memoria = torcia.ContoDellaMemoria()
            for scatto_id in da_fare:
                if self.fermata:
                    break
                try:
                    self._fai_lo_scatto(scatto_id, facce)
                except Exception as guasto:              # noqa: BLE001
                    if torcia.memoria_finita(guasto):
                        memoria.finita(scatto_id, guasto)
                    else:
                        registro.avviso("superfici.non_fatte", **registro.dove_si_e_rotto(guasto))
                        self._segna_non_fatte(scatto_id)
                    self.avanzamento.saltati += 1
                else:
                    for pesante in memoria.riuscito():
                        self._segna_non_fatte(pesante)
                self.avanzamento.fatti += 1
                if al_passo:
                    al_passo(self.avanzamento)
        finally:
            self.pelle.spegni()
        self._pulisci()
        registro.evento("superfici.passata", foto=self.avanzamento.fatti, persone=self.avanzamento.superfici)
        return self.avanzamento

    def _corpi(self, connessione, scatto_id: int):
        return tutti(connessione,
                     "SELECT c.id, c.riquadro, c.maschera, a.vettore FROM corpi c "
                     "JOIN aspetti a ON a.corpo_id = c.id AND a.modello = ? "
                     "WHERE c.scatto_id = ? AND c.modello = ? AND c.fotogramma = 0 ORDER BY c.id",
                     figure.ASPETTO, scatto_id, rilevatore_mod.NOME)

    def _fai_lo_scatto(self, scatto_id: int, facce) -> None:
        import json

        import numpy as np

        from officina.modello import corpi as corpi_mod

        with self.archivio.lettura() as connessione:
            corpi = self._corpi(connessione, scatto_id)
            scatto = uno(connessione, "SELECT larghezza, altezza FROM scatti WHERE id = ?", scatto_id)
        if not corpi:
            return
        larga_foto = float(scatto["larghezza"] or 4) if scatto else 4.0
        alta_foto = float(scatto["altezza"] or 3) if scatto else 3.0
        proporzione = larga_foto / alta_foto
        figure_lette = [figure.numeri_a_figura(corpi_mod.vettore_da_byte(c["vettore"], 1).tolist())
                        for c in corpi]
        fuoco = float(np.median([f["fuoco"] for f in figure_lette]))
        locali = []
        for inizio in range(0, len(corpi), CORPI_A_TURNO):
            if self.fermata:
                return
            pezzo = figure_lette[inizio:inizio + CORPI_A_TURNO]
            locali.extend(self.pelle.vertici([f["forma"] for f in pezzo], [f["parametri"] for f in pezzo]))
        nella_camera = [v + np.asarray(f["spostamento"], dtype=np.float64)
                        for v, f in zip(locali, figure_lette, strict=True)]
        alta = GRIGLIA
        larga = max(1, int(round(GRIGLIA * proporzione)))
        profondita = profondita_davanti(nella_camera, [facce] * len(nella_camera), fuoco, proporzione,
                                        alta, larga)
        fatte = []
        for corpo, vertici, locale, figura in zip(corpi, nella_camera, locali, figure_lette, strict=True):
            maschera = allarga(figure.maschera_intera(corpo["maschera"], json.loads(corpo["riquadro"]),
                                                      larga, alta), ALLARGA_LA_MASCHERA)
            visti, uv = visti_dalla_foto(vertici, facce, profondita, maschera, figura["fuoco"], proporzione)
            nome = f"{corpo['id']}.npz"
            salva(self.cartella / nome, locale, figura["spostamento"], visti, uv)
            fatte.append((corpo["id"], nome, len(vertici), int(visti.sum())))
        with self.archivio.scrittura() as connessione:
            for corpo_id, nome, quanti, visti in fatte:
                connessione.execute(
                    "INSERT OR REPLACE INTO superfici (corpo_id, versione, file, vertici, visti, fatta_il) "
                    "SELECT id, ?, ?, ?, ?, ? FROM corpi WHERE id = ?",
                    (VERSIONE, nome, quanti, visti, adesso(), corpo_id))
        self.avanzamento.superfici += len(fatte)

    def _segna_non_fatte(self, scatto_id: int) -> None:
        with self.archivio.scrittura() as connessione:
            for corpo in self._corpi(connessione, scatto_id):
                connessione.execute(
                    "INSERT OR REPLACE INTO superfici (corpo_id, versione, file, vertici, visti, fatta_il) "
                    "VALUES (?, ?, '', 0, 0, ?)", (corpo["id"], VERSIONE, adesso()))

    def _pulisci(self) -> None:
        if not self.cartella.is_dir():
            return
        with self.archivio.lettura() as connessione:
            tenuti = {riga["file"] for riga in tutti(connessione, "SELECT file FROM superfici WHERE file != ''")}
        for percorso in self.cartella.glob("*.npz"):
            if percorso.name not in tenuti:
                percorso.unlink(missing_ok=True)
