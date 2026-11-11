from __future__ import annotations

import contextlib
import hashlib
import json
import os
import shutil
import time
from fractions import Fraction
from pathlib import Path
from typing import Callable, Iterable, Iterator

from officina.miglioria import attesa, catena, fluido, mezzi, motori, pezzi, veloce, video

PIANO = "piano.json"
GIRI = "giri.jsonl"
ESITO = "esito.json"
ORIGINALE = "originale.mp4"
FISSI = "pezzi-fissi"
REGISTRATI = "fluidi-registrati"
INFO = "info.json"
VECCHIO, NUOVO = "vecchio", "nuovo"
VOLTE = 3
FPS = 30
LATO = (1280, 720)
SUONO = 48000
CAMPIONI = 1024
PER_PEZZO = 30
MISURA = "fhd"
FOTO = "foto"
MEZZI = "mezzi"
ORIGINALE_OPZIONI = {
    video.H264: {"crf": "16", "preset": "medium"},
    video.HEVC: {"crf": "18", "preset": "medium", "x265-params": "log-level=error"},
}


def impronta(file: Path) -> str:
    calcolo = hashlib.sha256()
    with open(file, "rb") as dentro:
        for pezzo in iter(lambda: dentro.read(1 << 20), b""):
            calcolo.update(pezzo)
    return calcolo.hexdigest()


def ordine(volte: int = VOLTE) -> list[tuple[int, str]]:
    return [(numero, VECCHIO if numero % 2 == 0 else NUOVO) for numero in range(2 * volte)]


def passi(clip: list[dict], volte: int = VOLTE) -> int:
    return sum(1 + int(bool(uno.get("fps120"))) + 2 * volte for uno in clip)


def misura_piccola(larghezza: int, altezza: int, lato: tuple[int, int] = LATO
                   ) -> tuple[int, int]:
    scala = min(1.0, lato[0] / larghezza, lato[1] / altezza)
    nuova_l = max(2, int(larghezza * scala) // 2 * 2)
    nuova_a = max(2, int(altezza * scala) // 2 * 2)
    return nuova_l, nuova_a


def _quadri_da(file: list[str]) -> Iterator:
    import numpy as np
    from PIL import Image

    misura = None
    for uno in file:
        with Image.open(uno) as immagine:
            rgb = immagine.convert("RGB")
            if misura is None:
                misura = misura_piccola(*rgb.size)
            if rgb.size != misura:
                rgb = rgb.resize(misura, Image.Resampling.LANCZOS)
            yield np.asarray(rgb)


def fai_l_originale(posto: Path, quadri: Iterable, codec: str, quanti: int) -> None:
    import numpy as np

    from officina.immagini import fotogrammi

    av = fotogrammi.decodificatore()
    posto.parent.mkdir(parents=True, exist_ok=True)
    provvisorio = posto.with_name(posto.name + ".in-corso")
    base = Fraction(1, FPS)
    with av.open(str(provvisorio), "w", format="mp4") as fuori:
        immagini = None
        suono = fuori.add_stream("aac", rate=SUONO)
        suono.layout = "stereo"
        uscito = 0
        for numero, quadro in enumerate(quadri):
            if immagini is None:
                immagini = fuori.add_stream(codec, rate=FPS)
                immagini.height, immagini.width = quadro.shape[:2]
                immagini.pix_fmt = "yuv420p"
                immagini.time_base = base
                immagini.options = dict(ORIGINALE_OPZIONI[codec])
                if codec == video.HEVC:
                    immagini.codec_tag = "hvc1"
            nuovo = av.VideoFrame.from_ndarray(np.ascontiguousarray(quadro), format="rgb24")
            nuovo.pts = numero
            nuovo.time_base = base
            for pacchetto in immagini.encode(nuovo):
                fuori.mux(pacchetto)
        for pacchetto in immagini.encode():
            fuori.mux(pacchetto)
        totale = quanti * SUONO // FPS
        while uscito < totale:
            lungo = min(CAMPIONI, totale - uscito)
            tempo = (np.arange(uscito, uscito + lungo) / SUONO).astype(np.float32)
            onda = 0.2 * np.sin(2 * np.pi * 440.0 * tempo)
            pezzo = av.AudioFrame.from_ndarray(np.stack([onda, onda]).astype(np.float32),
                                               format="fltp", layout="stereo")
            pezzo.sample_rate = SUONO
            pezzo.pts = uscito
            for pacchetto in suono.encode(pezzo):
                fuori.mux(pacchetto)
            uscito += lungo
        for pacchetto in suono.encode():
            fuori.mux(pacchetto)
    os.replace(provvisorio, posto)


@contextlib.contextmanager
def con_il_fluido(fabbrica: Callable):
    vero = fluido.Motore
    fluido.Motore = fabbrica
    try:
        yield
    finally:
        fluido.Motore = vero


class Registratore:

    def __init__(self, vero, dove: Path, firma: dict) -> None:
        self.vero = vero
        self.dove = dove
        self.firma_dei_pezzi = firma
        self.nome = vero.nome
        shutil.rmtree(dove, ignore_errors=True)
        self.posto = pezzi.Pezzi(dove, firma)

    @property
    def a_coppie(self) -> bool:
        return self.vero.a_coppie

    def firma(self) -> dict:
        return self.vero.firma()

    def usati(self) -> list[dict]:
        return self.vero.usati()

    def dove_stanno(self):
        return self.vero.dove_stanno()

    def foglio(self):
        return self.vero.foglio()

    def uscite(self, apri, volte: int) -> Iterator:
        self._mucchio: list = []
        self._gia = 0
        for quadro in self.vero.uscite(apri, volte):
            self._mucchio.append(quadro)
            if len(self._mucchio) >= PER_PEZZO:
                self.posto.salva(self._gia, self._mucchio)
                self._gia += len(self._mucchio)
                self._mucchio = []
            yield quadro

    def chiudi(self) -> None:
        if getattr(self, "_mucchio", None):
            self.posto.salva(self._gia, self._mucchio)
            self._mucchio = []
        self.posto.segna_finito()
        info = {"firma": self.vero.firma(), "usati": self.vero.usati(),
                "dove_stanno": self.vero.dove_stanno(), "foglio": self.vero.foglio(),
                "a_coppie": bool(self.vero.a_coppie)}
        (self.dove / INFO).write_text(json.dumps(info), encoding="utf-8")

    def spegni(self) -> None:
        self.vero.spegni()


class Riproduttore:

    def __init__(self, dove: Path, firma: dict) -> None:
        if not registrati_buoni(dove, firma):
            raise pezzi.PezzoRotto("I fotogrammi registrati della prova non ci sono.")
        self.dove = dove
        self.posto = pezzi.Pezzi(dove, firma)
        self.info = json.loads((dove / INFO).read_text(encoding="utf-8"))
        self.nome = self.info["firma"].get("motore", "")

    @property
    def a_coppie(self) -> bool:
        return bool(self.info["a_coppie"])

    def firma(self) -> dict:
        return self.info["firma"]

    def usati(self) -> list[dict]:
        return self.info["usati"]

    def dove_stanno(self):
        return self.info["dove_stanno"]

    def foglio(self):
        return self.info["foglio"]

    def uscite(self, apri, volte: int) -> Iterator:
        return self.posto.rileggi()

    def spegni(self) -> None:
        return None


def _in_revisione(cartella_clip: Path, nome: str) -> Path:
    return cartella_clip / attesa.NOME / nome / "1-uscita.mp4.parziale"


def _pulisci(uscita: Path) -> None:
    shutil.rmtree(uscita.parent, ignore_errors=True)


def _firma_dei_registrati(clip: dict) -> dict:
    return {"prova": clip["nome"], "fluido": clip.get("fps120")}


def registrati_buoni(dove: Path, firma: dict) -> bool:
    try:
        letta = json.loads((dove / pezzi.FIRMA).read_text("utf-8"))
    except (OSError, ValueError):
        return False
    return (letta == json.loads(json.dumps(firma)) and (dove / pezzi.FINITO).is_file()
            and (dove / INFO).is_file())


def la_scheda(cartella_clip: Path, lavoro: dict, al_passo=None, freno=None,
              racconta=None) -> Path:
    fissi = cartella_clip / FISSI
    if fissi.is_dir():
        return fissi
    shutil.rmtree(cartella_clip / REGISTRATI, ignore_errors=True)
    uscita = _in_revisione(cartella_clip, "scheda")
    _pulisci(uscita)
    fatti = catena.solo_la_scheda(dict(lavoro, uscita=str(uscita)), al_passo, freno,
                                  racconta)
    provvisoria = fissi.with_name(fissi.name + ".in-corso")
    shutil.rmtree(provvisoria, ignore_errors=True)
    shutil.copytree(fatti, provvisoria)
    os.replace(provvisoria, fissi)
    _pulisci(uscita)
    return fissi


def registra(cartella_clip: Path, clip: dict, lavoro: dict, al_passo=None,
             freno=None) -> Path:
    dove = cartella_clip / REGISTRATI
    firma = _firma_dei_registrati(clip)
    if registrati_buoni(dove, firma):
        return dove
    uscita = _in_revisione(cartella_clip, "registra")
    _pulisci(uscita)
    shutil.copytree(cartella_clip / FISSI, pezzi.cartella(uscita))
    vero = fluido.Motore
    fatti: list[Registratore] = []

    def fabbrica(nome, **opzioni):
        fatti.append(Registratore(vero(nome, **opzioni), dove, firma))
        return fatti[-1]

    with con_il_fluido(fabbrica):
        catena.filmato(dict(lavoro, uscita=str(uscita)), al_passo, freno)
    if len(fatti) != 1:
        raise pezzi.PezzoRotto("La prova non ha registrato i fotogrammi a 120.")
    fatti[0].chiudi()
    _pulisci(uscita)
    return dove


def un_giro(cartella_clip: Path, clip: dict, lavoro: dict, numero: int, modo: str) -> dict:
    uscita = _in_revisione(cartella_clip, f"giro-{numero}")
    _pulisci(uscita)
    shutil.copytree(cartella_clip / FISSI, pezzi.cartella(uscita))
    questo = dict(lavoro, uscita=str(uscita))
    questo.pop("veloce", None)
    if modo == NUOVO:
        questo["veloce"] = [veloce.SCRITTURA]
    contesto = contextlib.nullcontext()
    if clip.get("fps120"):
        dove, firma = cartella_clip / REGISTRATI, _firma_dei_registrati(clip)
        contesto = con_il_fluido(lambda _nome, **_opzioni: Riproduttore(dove, firma))
    partito = time.perf_counter()
    with contesto:
        catena.filmato(questo)
    secondi = time.perf_counter() - partito
    firma_del_file = impronta(uscita)
    _pulisci(uscita)
    return {"clip": clip["nome"], "giro": numero, "modo": modo, "impronta": firma_del_file,
            "secondi": round(secondi, 2)}


def giri_fatti(cartella: Path) -> list[dict]:
    try:
        righe = (cartella / GIRI).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    fatti = []
    for riga in righe:
        try:
            fatti.append(json.loads(riga))
        except ValueError:
            continue
    return fatti


def _segna(cartella: Path, giro: dict) -> None:
    with open(cartella / GIRI, "a", encoding="utf-8") as fuori:
        fuori.write(json.dumps(giro) + "\n")
        fuori.flush()
        os.fsync(fuori.fileno())


def _uscita_foto(cartella_foto: Path, nome: str, originale: Path) -> Path:
    return cartella_foto / attesa.NOME / nome / f"1-uscita{originale.suffix}.parziale"


def _una_foto(cartella_foto: Path, lavoro: dict, nome: str, mezzo: dict | None
              ) -> tuple[str, float]:
    uscita = _uscita_foto(cartella_foto, nome, Path(lavoro["originale"]))
    _pulisci(uscita)
    uscita.parent.mkdir(parents=True, exist_ok=True)
    questo = {k: v for k, v in lavoro.items() if k not in ("veloce", "mezzo")}
    questo["uscita"] = str(uscita)
    if mezzo is not None:
        questo["mezzo"] = mezzo
    partito = time.perf_counter()
    catena.foto(questo)
    secondi = time.perf_counter() - partito
    firma_del_file = impronta(uscita)
    _pulisci(uscita)
    return firma_del_file, secondi


def foto_vecchia(cartella: Path, uno: dict, lavoro: dict, numero: int) -> dict:
    motori.spegni_tutti()
    try:
        firma_del_file, secondi = _una_foto(cartella / FOTO / uno["nome"], lavoro,
                                            f"giro-{numero}", None)
    finally:
        motori.spegni_tutti()
    return {"clip": uno["nome"], "giro": numero, "modo": VECCHIO,
            "impronta": firma_del_file, "secondi": round(secondi, 2)}


def foto_nuove(cartella: Path, foto: list[dict], lavori: dict[str, dict], numero: int,
               freno=None) -> list[dict]:
    if not foto:
        return []
    motori.spegni_tutti()
    base = cartella / FOTO / MEZZI
    shutil.rmtree(base, ignore_errors=True)
    opzioni = lavori[foto[0]["nome"]].get("opzioni", {})
    partito = time.perf_counter()
    acceso = motori.classe(motori.FOTO, motori.LUCIDFLUX)(**opzioni, tieni=True)
    try:
        for indice, uno in enumerate(foto, 1):
            esito_del_mezzo = catena.solo_lucidflux(lavori[uno["nome"]], acceso, base,
                                                    indice, freno)
            if esito_del_mezzo not in ("fatto", "gia_fatto"):
                raise mezzi.MezzoRotto(f"La prova non ha messo da parte LucidFlux "
                                       f"({esito_del_mezzo}).")
    finally:
        acceso.spegni()
    quota = (time.perf_counter() - partito) / len(foto)
    fatti = []
    try:
        for indice, uno in enumerate(foto, 1):
            firma_del_file, secondi = _una_foto(
                cartella / FOTO / uno["nome"], lavori[uno["nome"]], f"giro-{numero}",
                {"cartella": str(base), "id": indice})
            fatti.append({"clip": uno["nome"], "giro": numero, "modo": NUOVO,
                          "impronta": firma_del_file, "secondi": round(quota + secondi, 2)})
    finally:
        motori.spegni_tutti()
        shutil.rmtree(base, ignore_errors=True)
    return fatti


def lavoro_della_foto(cartella: Path, uno: dict, lavoro: dict) -> dict:
    sorgente = Path(uno["file"][0])
    originale = cartella / FOTO / uno["nome"] / f"originale{sorgente.suffix.lower()}"
    if not originale.is_file():
        originale.parent.mkdir(parents=True, exist_ok=True)
        provvisorio = originale.with_name(originale.name + ".in-corso")
        shutil.copyfile(sorgente, provvisorio)
        os.replace(provvisorio, originale)
    suo = {k: v for k, v in lavoro.items() if k not in ("fps120", "veloce", "mezzo")}
    suo.update(genere="immagine", originale=str(originale), persone=[],
               motori={"foto": motori.LUCIDFLUX, "volti": None})
    return suo


def riassunto(clip: dict, giri: list[dict], volte: int = VOLTE) -> dict:
    suoi = [giro for giro in giri if giro.get("clip") == clip["nome"]]
    vecchi = [giro["impronta"] for giro in suoi if giro["modo"] == VECCHIO]
    nuovi = [giro["impronta"] for giro in suoi if giro["modo"] == NUOVO]
    stabile = len(vecchi) == volte and len(set(vecchi)) == 1
    uguale = stabile and len(nuovi) == volte and set(nuovi) == set(vecchi)

    def media(modo: str) -> float | None:
        secondi = [giro["secondi"] for giro in suoi if giro["modo"] == modo]
        return round(sum(secondi) / len(secondi), 2) if secondi else None

    return {"nome": clip["nome"], "codec": clip.get("codec"), "fps120": clip.get("fps120"),
            "gruppo": clip.get("gruppo"), "vecchi": vecchi, "nuovi": nuovi,
            "stabile": stabile, "uguale": uguale, "secondi_vecchio": media(VECCHIO),
            "secondi_nuovo": media(NUOVO)}


def esito(clip: list[dict], giri: list[dict], volte: int = VOLTE,
          foto: list[dict] | None = None, giri_foto: list[dict] | None = None) -> dict:
    righe = [riassunto(uno, giri, volte) for uno in clip]
    righe_foto = [riassunto(uno, giri_foto or [], volte) for uno in foto or []]
    idee = []
    if righe and all(riga["uguale"] for riga in righe):
        idee.append(veloce.SCRITTURA)
    if righe_foto and all(riga["uguale"] for riga in righe_foto):
        idee.append(veloce.GIRO_LUCIDFLUX)
    provate = int(bool(righe)) + int(bool(righe_foto))
    return {"clip": righe, "foto": righe_foto, "idee": idee,
            "passata": provate > 0 and len(idee) == provate}


def leggi_esito(cartella: Path) -> dict | None:
    try:
        return json.loads((Path(cartella) / ESITO).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def scrivi_esito(cartella: Path, dati: dict) -> None:
    provvisorio = Path(cartella) / (ESITO + ".in-corso")
    provvisorio.write_text(json.dumps(dati), encoding="utf-8")
    os.replace(provvisorio, Path(cartella) / ESITO)


def _le_foto(cartella: Path, foto: list[dict], lavoro: dict, volte: int, avanti,
             freno=None) -> None:
    dove = cartella / FOTO
    dove.mkdir(parents=True, exist_ok=True)
    lavori = {uno["nome"]: lavoro_della_foto(cartella, uno, lavoro) for uno in foto}
    for numero, modo in ordine(volte):
        gia = {giro["clip"] for giro in giri_fatti(dove) if giro.get("giro") == numero}
        mancano = [uno for uno in foto if uno["nome"] not in gia]
        if modo == VECCHIO:
            for uno in mancano:
                _segna(dove, foto_vecchia(cartella, uno, lavori[uno["nome"]], numero))
        else:
            for fatto in foto_nuove(cartella, mancano, lavori, numero, freno):
                _segna(dove, fatto)
        for _uno in foto:
            avanti()


def corri(cartella: Path, clip: list[dict], lavoro: dict,
          al_passo: Callable[[int, int], None] | None = None, freno=None,
          racconta=None, volte: int = VOLTE, foto: list[dict] | None = None,
          lavoro_foto: dict | None = None) -> dict:
    cartella = Path(cartella)
    foto = list(foto or [])
    totale = passi(clip, volte) + len(foto) * 2 * volte
    fatti = [0]

    def avanti() -> None:
        fatti[0] += 1
        if al_passo is not None:
            al_passo(fatti[0], totale)

    for uno in clip:
        cartella_clip = cartella / uno["nome"]
        originale = cartella_clip / ORIGINALE
        if not originale.is_file():
            fai_l_originale(originale, _quadri_da(uno["file"]), uno["codec"],
                            len(uno["file"]))
        suo = {k: v for k, v in lavoro.items() if k not in ("fps120", "veloce")}
        suo.update(genere="video", originale=str(originale), misura=MISURA)
        if uno.get("fps120"):
            suo["fps120"] = uno["fps120"]
        la_scheda(cartella_clip, suo, None, freno, racconta)
        avanti()
        if uno.get("fps120"):
            registra(cartella_clip, uno, suo, None, freno)
            avanti()
        gia = {giro["giro"] for giro in giri_fatti(cartella)
               if giro.get("clip") == uno["nome"]}
        for numero, modo in ordine(volte):
            if numero not in gia:
                _segna(cartella, un_giro(cartella_clip, uno, suo, numero, modo))
            avanti()
    if foto:
        _le_foto(cartella, foto, lavoro_foto or lavoro, volte, avanti, freno)
    dati = esito(clip, giri_fatti(cartella), volte, foto, giri_fatti(cartella / FOTO))
    scrivi_esito(cartella, dati)
    return dati


__all__ = ["ESITO", "FISSI", "FOTO", "GIRI", "MEZZI", "MISURA", "NUOVO", "ORIGINALE", "PIANO",
           "REGISTRATI", "Registratore", "Riproduttore", "VECCHIO", "VOLTE", "con_il_fluido",
           "corri", "esito", "fai_l_originale", "foto_nuove", "foto_vecchia", "giri_fatti",
           "impronta", "la_scheda", "lavoro_della_foto", "leggi_esito", "misura_piccola",
           "ordine", "passi", "registra", "registrati_buoni", "riassunto", "scrivi_esito",
           "un_giro"]
