from __future__ import annotations

import json
import shutil
import threading
import time
from pathlib import Path
from typing import Callable

from PIL import Image

from officina import registro
from officina.descrittori import vettori
from officina.errori import ErroreOfficina
from officina.ritocco import elenco, maschere, pellicola, ricontrollo, togliere, togliere_video

COSA = "gara_video"
CARTELLA = "gara-video"
VOTI = "voti.json"
SCELTI = "togli_video_motori"
PRIMI = 2
ASPETTA_LA_SCHEDA = 30.0
CANDIDATI = ("effecterase", "rose", "undereraser", "void", "minimax-remover", "svor")
INSIEMI = ("camera-bench", "rord-50", "vor-eval")
CON, SENZA, BUCO = "con.mp4", "senza.mp4", "buco.mp4"
NON_PRONTO = "non è installato"
SENZA_PROVE = "Non ci sono video di prova: la gara non può partire."


def _psnr(a, b, dove) -> float | None:
    numpy = vettori.numpy_o_spiega()
    if not dove.any():
        return None
    errore = float(((a.astype(numpy.float32) - b.astype(numpy.float32))[dove] ** 2).mean())
    return 99.0 if errore <= 1e-9 else 10.0 * float(numpy.log10(255.0 ** 2 / errore))


def _media(valori) -> float | None:
    valori = [valore for valore in valori if valore is not None]
    return round(sum(valori) / len(valori), 3) if valori else None


def prove(cartella: Path) -> list[Path]:
    dove = Path(cartella) / "prove"
    if not dove.is_dir():
        return []
    return sorted(clip for clip in dove.iterdir()
                  if all((clip / nome).is_file() for nome in (CON, SENZA, BUCO)))


def strato_del_buco(percorso: Path) -> pellicola.Strato:
    numpy = vettori.numpy_o_spiega()
    tutte: dict[int, bytes] = {}
    larga = alta = 0
    for numero, quadro in enumerate(togliere_video.leggi(percorso)):
        alta, larga = quadro.shape[:2]
        piena = numpy.asarray(quadro).max(axis=2) > 127
        if piena.any():
            tutte[numero] = maschere.comprimi(piena, (0, 0), larga, alta)
        quanti = numero + 1
    if not tutte:
        raise togliere.NienteDaTogliere("Nel video di prova non c'è niente da togliere.")
    return pellicola.Strato(larga, alta, quanti, tutte, elenco.OGGETTO)


def _buco_intero(strato: pellicola.Strato, numero: int):
    numpy = vettori.numpy_o_spiega()
    dati = strato.maschere.get(numero)
    if dati is None:
        return numpy.zeros((strato.altezza, strato.larghezza), dtype=bool)
    return maschere.intera(maschere.per_misura(maschere.apri(dati), strato.larghezza,
                                               strato.altezza))


def vota(clip: Path, toppa: Path, fatto: dict, strato: pellicola.Strato,
         cerca: ricontrollo.Cerca | None = None, dove_guardare: Path | None = None) -> dict:
    numpy = vettori.numpy_o_spiega()
    x, y, larga, alta = fatto["x"], fatto["y"], fatto["larghezza"], fatto["altezza"]
    uguale, resto, bordi = [], [], []
    mezzo = strato.quanti // 2
    resta = False
    for numero, (rifatto, vero, con) in enumerate(zip(
            togliere_video.leggi(toppa), togliere_video.leggi(clip / SENZA),
            togliere_video.leggi(clip / CON), strict=False)):
        buco = _buco_intero(strato, numero)[y:y + alta, x:x + larga]
        peso = togliere_video.alfa(buco)[..., None]
        zona = con[y:y + alta, x:x + larga].astype(numpy.float32)
        messo = (zona * (1.0 - peso) + rifatto.astype(numpy.float32) * peso).astype(numpy.uint8)
        vero_qui = vero[y:y + alta, x:x + larga]
        uguale.append(_psnr(messo, vero_qui, buco))
        resto.append(_psnr(messo, zona.astype(numpy.uint8), ~(peso[..., 0] > 0)))
        if not buco.any():
            continue
        alfa = Image.fromarray((peso[..., 0] * 255).astype(numpy.uint8), "L")
        immagine = Image.fromarray(rifatto, "RGB").convert("RGBA")
        immagine.putalpha(alfa)
        intera = Image.fromarray(con, "RGB")
        toppa_qui = togliere.Toppa(x, y, immagine, False)
        dopo = toppa_qui.metti(intera)
        bordi.append(ricontrollo.bordo_visibile(dopo, toppa_qui))
        if numero == mezzo and cerca is not None and dove_guardare is not None:
            intero = numpy.zeros((strato.altezza, strato.larghezza), dtype=bool)
            intero[y:y + alta, x:x + larga] = buco
            dopo.save(dove_guardare)
            try:
                resta = ricontrollo.controlla(dopo, toppa_qui, intero, cerca,
                                              dove_guardare).resta
            finally:
                dove_guardare.unlink(missing_ok=True)
    return {"resta": resta, "tremola": bool(fatto.get("tremola")), "uguale": _media(uguale),
            "resto": _media(resto), "bordo": bool(bordi) and sum(bordi) * 2 > len(bordi)}


def riassumi(voti: dict) -> dict:
    righe = []
    for chi, suoi in voti.items():
        if not isinstance(suoi, dict) or suoi.get("non_pronto"):
            continue
        fatte = [voto for voto in suoi.get("clip", {}).values() if isinstance(voto, dict)]
        if not fatte:
            continue
        quante = len(fatte)
        righe.append({
            "chi": chi, "quante": quante,
            "resta": round(sum(voto["resta"] for voto in fatte) / quante, 3),
            "tremola": round(sum(voto["tremola"] for voto in fatte) / quante, 3),
            "uguale": _media(voto["uguale"] for voto in fatte),
            "resto": _media(voto["resto"] for voto in fatte),
            "bordo": round(sum(voto["bordo"] for voto in fatte) / quante, 3)})
    return {"classifica": sorted(righe, key=ordine)}


def ordine(riga: dict) -> tuple:
    return (riga["resta"], riga["tremola"], -(riga["uguale"] or 0.0), -(riga["resto"] or 0.0),
            riga["bordo"], riga["chi"])


def _leggi_i_voti(cartella: Path) -> dict:
    percorso = Path(cartella) / VOTI
    if not percorso.is_file():
        return {}
    try:
        dati = json.loads(percorso.read_text(encoding="utf-8"))
    except ValueError:
        return {}
    return dati if isinstance(dati, dict) else {}


def _scrivi_i_voti(cartella: Path, voti: dict) -> None:
    percorso = Path(cartella) / VOTI
    parziale = percorso.with_name(percorso.name + ".parziale")
    parziale.write_text(json.dumps(voti, ensure_ascii=False, indent=1), encoding="utf-8")
    parziale.replace(percorso)


class Gara:

    def __init__(self, archivio, cartella: Path | None = None,
                 candidati: tuple[str, ...] = CANDIDATI,
                 apri: Callable[..., object] = togliere.apri,
                 scarica: Callable[[Path], None] | None = None,
                 cerca: ricontrollo.Cerca | None = None, turno=None):
        from officina.web.lavori import Lavoro

        self.archivio = archivio
        self.cartella = Path(cartella) if cartella else Path(archivio.dove.modelli) / CARTELLA
        self.candidati = tuple(candidati)
        self._apri = apri
        self._scarica = scarica
        self.cerca = cerca
        self._turno = turno
        self.lavoro = Lavoro(COSA, scheda=True)
        self._fermati = threading.Event()

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
        if aspetta:
            self.lavoro.aspetta_che_finisca(aspetta)

    def come_va(self) -> dict:
        stato = self.lavoro.come_va()
        voti = _leggi_i_voti(self.cartella)
        stato["classifica"] = riassumi(voti.get("candidati", {}))["classifica"]
        stato["finita"] = voti.get("finita")
        return stato

    def _intensita(self) -> int:
        return int(self.archivio.impostazione("intensita_scheda") or 100)

    def _prendi_la_scheda(self) -> None:
        while not self.turno.prendi_se_libera(self.lavoro):
            if self.turno.chi is self.lavoro:
                return
            self.lavoro.di("aspetto che la scheda si liberi")
            if self._fermati.wait(ASPETTA_LA_SCHEDA):
                raise pellicola.Fermato()

    def _gira(self) -> None:
        try:
            self._prendi_la_scheda()
            self._corri()
        except pellicola.Fermato:
            self.lavoro.di("gara fermata: riprende da qui")
        finally:
            self.turno.lascia(self.lavoro)

    def _corri(self) -> None:
        from officina.descrittori import torcia

        self.cartella.mkdir(parents=True, exist_ok=True)
        if not prove(self.cartella) and self._scarica is not None:
            self.lavoro.di("scarico i video pubblici di prova")
            self._scarica(self.cartella)
        clip = prove(self.cartella)
        if not clip:
            raise ErroreOfficina(SENZA_PROVE, codice="gara_video_senza_prove")
        voti = _leggi_i_voti(self.cartella)
        candidati = voti.setdefault("candidati", {})
        freno = torcia.Freno(self._intensita(), fermato=self._fermati.is_set)
        fatti_dove = self.cartella / "fatti"
        fatti_dove.mkdir(exist_ok=True)
        totale = len(self.candidati) * len(clip)
        for indice, chi in enumerate(self.candidati):
            suoi = candidati.setdefault(chi, {"clip": {}})
            if suoi.get("non_pronto"):
                continue
            if all(prova.name in suoi["clip"] for prova in clip):
                continue
            try:
                motore = self._apri(chi, cartella_modelli=str(self.archivio.dove.modelli))
            except togliere.MotoreSconosciuto:
                suoi["non_pronto"] = NON_PRONTO
                _scrivi_i_voti(self.cartella, voti)
                registro.avviso("gara_video.non_pronto", chi=chi)
                continue
            try:
                for numero, prova in enumerate(clip):
                    if prova.name in suoi["clip"]:
                        continue
                    if self._fermati.is_set():
                        raise pellicola.Fermato()
                    self.lavoro.di(f"provo «{chi}» sul video {numero + 1} di {len(clip)}")
                    self.lavoro.a_che_punto(indice * len(clip) + numero, totale, "video")
                    suoi["clip"][prova.name] = self._una(motore, prova, fatti_dove, freno)
                    _scrivi_i_voti(self.cartella, voti)
            finally:
                motore.spegni()
        self._chiudi(voti, clip)

    def _una(self, motore, prova: Path, fatti_dove: Path, freno) -> dict:
        strato = strato_del_buco(prova / BUCO)
        toppa = fatti_dove / f"{prova.name}.mkv"
        partito = time.monotonic()
        try:
            fatto = togliere_video.togli_nel_video(prova / CON, strato, motore, toppa,
                                                   fermati=self._fermati.is_set, freno=freno)
            voto = vota(prova, toppa, fatto, strato, self.cerca,
                        fatti_dove / f"{prova.name}-dopo.png")
        finally:
            toppa.unlink(missing_ok=True)
        voto["secondi"] = round(time.monotonic() - partito, 1)
        return voto

    def _chiudi(self, voti: dict, clip: list[Path]) -> None:
        classifica = riassumi(voti["candidati"])["classifica"]
        primi = [riga["chi"] for riga in classifica if riga["quante"] == len(clip)][:PRIMI]
        voti["finita"] = {"primi": primi, "classifica": classifica}
        _scrivi_i_voti(self.cartella, voti)
        if primi:
            self.archivio.imposta(SCELTI, json.dumps(primi))
        for dove in (self.cartella / "prove", self.cartella / "fatti"):
            shutil.rmtree(dove, ignore_errors=True)
        registro.evento("gara_video.finita", primi=primi, quanti=len(classifica))
        self.lavoro.di("gara finita: " + (", ".join(primi) if primi else "nessuno ha finito"))
