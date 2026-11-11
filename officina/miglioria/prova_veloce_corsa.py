from __future__ import annotations

import contextlib
import hashlib
import itertools
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
PRECARICO = "precarico"
VOLTI = "volti"
FILI = "fili"
DIETRO = "dietro"
QUANTE_PER_I_FILI = 60
IDEA_DEI_VOLTI = {motori.CODEFORMER: veloce.VOLTI_ACCESI,
                  motori.FACEME: veloce.FACEME_ACCESO}
QUADRI_FLUIDO = 24
VOLTE_FLUIDO = 4
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


def _una_foto(cartella_foto: Path, lavoro: dict, nome: str, mezzo: dict | None,
              idee: list[str] | None = None) -> tuple[str, float]:
    uscita = _uscita_foto(cartella_foto, nome, Path(lavoro["originale"]))
    _pulisci(uscita)
    uscita.parent.mkdir(parents=True, exist_ok=True)
    questo = {k: v for k, v in lavoro.items() if k not in ("veloce", "mezzo")}
    questo["uscita"] = str(uscita)
    if mezzo is not None:
        questo["mezzo"] = mezzo
    if idee:
        questo["veloce"] = list(idee)
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


def impronta_dei_quadri(quadri: Iterable) -> str:
    import numpy as np

    calcolo = hashlib.sha256()
    for quadro in quadri:
        dato = np.ascontiguousarray(quadro)
        calcolo.update(f"{dato.shape}|{dato.dtype}|".encode())
        calcolo.update(dato.tobytes())
    return calcolo.hexdigest()


def _idee(modo: str) -> dict:
    return {"veloce": [veloce.PRECARICO]} if modo == NUOVO else {}


def _riga(nome: str, numero: int, modo: str, firma_del_file: str, secondi: float) -> dict:
    return {"clip": nome, "giro": numero, "modo": modo, "impronta": firma_del_file,
            "secondi": round(secondi, 2)}


def _firma_letta(dove: Path) -> dict:
    return json.loads((dove / pezzi.FIRMA).read_text("utf-8"))


def scheda_col_precarico(cartella_clip: Path, clip: dict, lavoro: dict, numero: int,
                         modo: str) -> dict:
    uscita = _in_revisione(cartella_clip, f"precarico-{numero}")
    _pulisci(uscita)
    questo = {k: v for k, v in lavoro.items() if k not in ("veloce", "fps120")}
    questo.update(uscita=str(uscita), **_idee(modo))
    motori.spegni_tutti()
    try:
        partito = time.perf_counter()
        fatti = catena.solo_la_scheda(questo)
        secondi = time.perf_counter() - partito
        firma_del_file = impronta_dei_quadri(pezzi.Pezzi(fatti, _firma_letta(fatti))
                                             .rileggi())
    finally:
        motori.spegni_tutti()
        _pulisci(uscita)
    return _riga(f"scheda-{clip['nome']}", numero, modo, firma_del_file, secondi)


def fluido_col_precarico(cartella_clip: Path, clip: dict, lavoro: dict, numero: int,
                         modo: str) -> dict:
    fissi = cartella_clip / FISSI
    deposito = cartella_clip / attesa.NOME / f"fluido-precarico-{numero}"
    shutil.rmtree(deposito, ignore_errors=True)
    motori.spegni_tutti()
    motore = fluido.Motore(clip["fps120"], deposito=deposito, **lavoro.get("opzioni", {}))
    catena.precarica(motore, _idee(modo))
    try:
        firma = _firma_letta(fissi)

        def apri() -> Iterator:
            return itertools.islice(pezzi.Pezzi(fissi, firma).rileggi(), QUADRI_FLUIDO)

        partito = time.perf_counter()
        firma_del_file = impronta_dei_quadri(motore.uscite(apri, VOLTE_FLUIDO))
        secondi = time.perf_counter() - partito
    finally:
        motore.spegni()
        motori.spegni_tutti()
        shutil.rmtree(deposito, ignore_errors=True)
    return _riga(f"fluido-{clip['nome']}", numero, modo, firma_del_file, secondi)


def foto_col_precarico(cartella: Path, uno: dict, lavoro: dict, numero: int) -> dict:
    motori.spegni_tutti()
    try:
        firma_del_file, secondi = _una_foto(cartella / FOTO / uno["nome"], lavoro,
                                            f"precarico-{numero}", None,
                                            [veloce.PRECARICO])
    finally:
        motori.spegni_tutti()
    return _riga(f"foto-{uno['nome']}", numero, NUOVO, firma_del_file, secondi)


def con_lo_scambio(clip: list[dict]) -> list[dict]:
    return [uno for uno in clip if not uno.get("fps120")]


def con_ldf(clip: list[dict]) -> list[dict]:
    return [uno for uno in clip if uno.get("fps120") in (fluido.LDF, fluido.FUSIONE)]


def righe_del_precarico(clip: list[dict], foto: list[dict]) -> list[dict]:
    return ([dict(uno, nome=f"scheda-{uno['nome']}") for uno in con_lo_scambio(clip)]
            + [dict(uno, nome=f"fluido-{uno['nome']}") for uno in con_ldf(clip)]
            + [dict(uno, nome=f"foto-{uno['nome']}") for uno in foto])


def passi_del_precarico(clip: list[dict], foto: list[dict], volte: int = VOLTE) -> int:
    return (len(con_lo_scambio(clip)) + len(con_ldf(clip))) * 2 * volte + len(foto) * volte


def giri_del_precarico(cartella: Path) -> list[dict]:
    vecchi = [dict(giro, clip=f"foto-{giro['clip']}") for giro in giri_fatti(cartella / FOTO)
              if giro.get("modo") == VECCHIO]
    return giri_fatti(cartella / PRECARICO) + vecchi


def lavoro_dei_volti(cartella: Path, uno: dict, lavoro: dict, motore: str) -> dict:
    suo = lavoro_della_foto(cartella / VOLTI, uno, lavoro)
    suo.update(persone=list(uno.get("persone") or []) if motore == motori.FACEME else [],
               motori={"foto": motori.SEEDVR2, "volti": motore})
    return suo


def volti_vecchi(cartella: Path, uno: dict, lavoro: dict, motore: str,
                 numero: int) -> dict:
    motori.spegni_tutti()
    try:
        firma_del_file, secondi = _una_foto(
            cartella / VOLTI / FOTO / uno["nome"], lavoro, f"{motore}-{numero}", None)
    finally:
        motori.spegni_tutti()
    return _riga(f"{motore}-{uno['nome']}", numero, VECCHIO, firma_del_file, secondi)


def volti_nuovi(cartella: Path, volti: list[dict], lavori: dict[str, dict], motore: str,
                numero: int) -> list[dict]:
    motori.spegni_tutti()
    fatti = []
    try:
        for uno in volti:
            firma_del_file, secondi = _una_foto(
                cartella / VOLTI / FOTO / uno["nome"], lavori[uno["nome"]],
                f"{motore}-{numero}", None, [IDEA_DEI_VOLTI[motore]])
            fatti.append(_riga(f"{motore}-{uno['nome']}", numero, NUOVO, firma_del_file,
                               secondi))
    finally:
        motori.spegni_tutti()
    return fatti


def righe_dei_volti(volti: list[dict], motore: str) -> list[dict]:
    return [dict(uno, nome=f"{motore}-{uno['nome']}") for uno in volti]


def _i_volti(cartella: Path, volti: list[dict], lavoro: dict, quali: list[str],
             volte: int, avanti) -> None:
    dove = cartella / VOLTI
    dove.mkdir(parents=True, exist_ok=True)
    for motore in quali:
        lavori = {uno["nome"]: lavoro_dei_volti(cartella, uno, lavoro, motore)
                  for uno in volti}
        for numero, modo in ordine(volte):
            gia = {giro["clip"] for giro in giri_fatti(dove) if giro.get("giro") == numero}
            mancano = [uno for uno in volti if f"{motore}-{uno['nome']}" not in gia]
            if modo == VECCHIO:
                for uno in mancano:
                    _segna(dove, volti_vecchi(cartella, uno, lavori[uno["nome"]], motore,
                                              numero))
            elif mancano:
                for fatto in volti_nuovi(cartella, volti, lavori, motore, numero):
                    if fatto["clip"] not in gia:
                        _segna(dove, fatto)
            for _uno in volti:
                avanti()


def lati_delle_impronte() -> list[int]:
    from officina import descrittori

    return sorted({int(scheda.lato) for scheda in descrittori.SCHEDE.values()})


def _ritagli_di(percorso: str) -> list[bytes]:
    from officina.descrittori import preparazione
    from officina.immagini import lettura

    pezzi_suoi = []
    for lato in lati_delle_impronte():
        immagine = lettura.copia_di_lavoro(Path(percorso), lato * 4)
        for ritaglio in preparazione.tre_inquadrature(immagine, lato):
            pezzi_suoi.append(f"{lato}|{ritaglio.inquadratura}|{ritaglio.riquadro}|"
                              f"{ritaglio.immagine.size}|".encode())
            pezzi_suoi.append(ritaglio.immagine.tobytes())
    return pezzi_suoi


def un_giro_di_fili(file: list[str], numero: int, modo: str) -> dict:
    from concurrent.futures import ThreadPoolExecutor

    from officina.impronte import motore as impronte

    partito = time.perf_counter()
    if modo == NUOVO:
        with ThreadPoolExecutor(max_workers=impronte.FILI) as fili:
            tutti = list(fili.map(_ritagli_di, file))
    else:
        tutti = [_ritagli_di(uno) for uno in file]
    secondi = time.perf_counter() - partito
    calcolo = hashlib.sha256()
    for suoi in tutti:
        for pezzo in suoi:
            calcolo.update(pezzo)
    return _riga(FILI, numero, modo, calcolo.hexdigest(), secondi)


def file_per_i_fili(clip: list[dict], foto: list[dict], volti: list[dict]) -> list[str]:
    tutti = [nome for uno in list(volti) + list(foto) + list(clip) for nome in uno["file"]]
    buoni = [nome for nome in dict.fromkeys(tutti)
             if nome.lower().rsplit(".", 1)[-1] in ("jpg", "jpeg", "png")]
    return buoni[:QUANTE_PER_I_FILI]


def per_il_dietro(clip: list[dict]) -> list[dict]:
    senza = con_lo_scambio(clip)
    return senza[:2] if len(senza) >= 2 else []


def _coda_del_video(uscita: Path) -> list[str]:
    from officina.importazione import impronta as impronta_del_file
    from officina.miglioria import da_guardare

    copia = uscita.with_name("copia-da-guardare.mp4")
    da_guardare.ricodifica(uscita, copia)
    return [impronta(uscita), impronta(copia), impronta_del_file.del_file(uscita)]


def un_giro_dietro(cartella: Path, due: list[dict], lavori: dict[str, dict], numero: int,
                   modo: str) -> dict:
    from officina.miglioria import dietro

    uscite = []
    for uno in due:
        uscita = _in_revisione(cartella / uno["nome"], f"dietro-{numero}")
        _pulisci(uscita)
        shutil.copytree(cartella / uno["nome"] / FISSI, pezzi.cartella(uscita))
        uscite.append(uscita)
    fila = dietro.Dietro(disco=lambda _dove: shutil.disk_usage(cartella),
                         libera=lambda: None)
    firme: list[list[str]] = [[] for _uno in due]
    try:
        partito = time.perf_counter()
        for posto, (uno, uscita) in enumerate(zip(due, uscite, strict=True)):
            questo = {k: v for k, v in lavori[uno["nome"]].items() if k != "veloce"}
            catena.filmato(dict(questo, uscita=str(uscita)))
            if modo == NUOVO:
                fila.metti(lambda posto=posto, uscita=uscita:
                           firme[posto].extend(_coda_del_video(uscita)), 0)
            else:
                firme[posto].extend(_coda_del_video(uscita))
        fila.aspetta()
        secondi = time.perf_counter() - partito
    finally:
        fila.aspetta()
        for uscita in uscite:
            _pulisci(uscita)
    calcolo = hashlib.sha256()
    for suoi in firme:
        if len(suoi) != 3:
            raise pezzi.PezzoRotto("La prova dei lavori dietro non ha finito un video.")
        for firma in suoi:
            calcolo.update(firma.encode())
    return _riga(DIETRO, numero, modo, calcolo.hexdigest(), secondi)


def _il_dietro(cartella: Path, due: list[dict], lavoro: dict, volte: int, avanti) -> None:
    dove = cartella / DIETRO
    dove.mkdir(parents=True, exist_ok=True)
    lavori = {uno["nome"]: _lavoro_del_video(lavoro, cartella / uno["nome"] / ORIGINALE, uno)
              for uno in due}
    gia = {giro["giro"] for giro in giri_fatti(dove)}
    for numero, modo in ordine(volte):
        if numero not in gia:
            _segna(dove, un_giro_dietro(cartella, due, lavori, numero, modo))
        avanti()


def _i_fili(cartella: Path, file: list[str], volte: int, avanti) -> None:
    dove = cartella / FILI
    dove.mkdir(parents=True, exist_ok=True)
    gia = {giro["giro"] for giro in giri_fatti(dove)}
    for numero, modo in ordine(volte):
        if numero not in gia:
            _segna(dove, un_giro_di_fili(file, numero, modo))
        avanti()


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
          foto: list[dict] | None = None, giri_foto: list[dict] | None = None,
          giri_scheda: list[dict] | None = None, volti: list[dict] | None = None,
          giri_volti: list[dict] | None = None, quali_volti: list[str] | None = None,
          giri_fili: list[dict] | None = None,
          giri_dietro: list[dict] | None = None) -> dict:
    righe = [riassunto(uno, giri, volte) for uno in clip]
    righe_foto = [riassunto(uno, giri_foto or [], volte) for uno in foto or []]
    righe_scheda = ([riassunto(uno, giri_scheda, volte)
                     for uno in righe_del_precarico(clip, foto or [])]
                    if giri_scheda is not None else [])
    idee = []
    if righe and all(riga["uguale"] for riga in righe):
        idee.append(veloce.SCRITTURA)
    if righe_foto and all(riga["uguale"] for riga in righe_foto):
        idee.append(veloce.GIRO_LUCIDFLUX)
    if righe_scheda and all(riga["uguale"] for riga in righe_scheda):
        idee.append(veloce.PRECARICO)
    provate = int(bool(righe)) + int(bool(righe_foto)) + int(bool(righe_scheda))
    righe_volti = []
    for motore in quali_volti or []:
        sue = [riassunto(uno, giri_volti or [], volte)
               for uno in righe_dei_volti(volti or [], motore)]
        righe_volti.extend(sue)
        provate += int(bool(sue))
        if sue and all(riga["uguale"] for riga in sue):
            idee.append(IDEA_DEI_VOLTI[motore])
    righe_fili = ([riassunto({"nome": FILI}, giri_fili, volte)]
                  if giri_fili is not None else [])
    provate += int(bool(righe_fili))
    if righe_fili and all(riga["uguale"] for riga in righe_fili):
        idee.append(veloce.IMPRONTE_FILI)
    righe_dietro = ([riassunto({"nome": DIETRO}, giri_dietro, volte)]
                    if giri_dietro is not None else [])
    provate += int(bool(righe_dietro))
    if righe_dietro and all(riga["uguale"] for riga in righe_dietro):
        idee.append(veloce.LAVORI_DIETRO)
    return {"clip": righe, "foto": righe_foto, "scheda": righe_scheda,
            "volti": righe_volti, "fili": righe_fili, "dietro": righe_dietro, "idee": idee,
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


def _il_precarico(cartella: Path, clip: list[dict], lavoro: dict, foto: list[dict],
                  lavoro_foto: dict, volte: int, avanti) -> None:
    dove = cartella / PRECARICO
    dove.mkdir(parents=True, exist_ok=True)
    gia = {(giro["clip"], giro["giro"]) for giro in giri_fatti(dove)}
    lavori = []
    for uno in con_lo_scambio(clip):
        lavori.append((f"scheda-{uno['nome']}", scheda_col_precarico, uno))
    for uno in con_ldf(clip):
        lavori.append((f"fluido-{uno['nome']}", fluido_col_precarico, uno))
    for nome, fai, uno in lavori:
        cartella_clip = cartella / uno["nome"]
        suo = _lavoro_del_video(lavoro, cartella_clip / ORIGINALE, uno)
        for numero, modo in ordine(volte):
            if (nome, numero) not in gia:
                _segna(dove, fai(cartella_clip, uno, suo, numero, modo))
            avanti()
    for uno in foto:
        suo = lavoro_della_foto(cartella, uno, lavoro_foto)
        for numero in range(1, 2 * volte, 2):
            if (f"foto-{uno['nome']}", numero) not in gia:
                _segna(dove, foto_col_precarico(cartella, uno, suo, numero))
            avanti()


def _lavoro_del_video(lavoro: dict, originale: Path, uno: dict) -> dict:
    suo = {k: v for k, v in lavoro.items() if k not in ("fps120", "veloce")}
    suo.update(genere="video", originale=str(originale), misura=MISURA)
    if uno.get("fps120"):
        suo["fps120"] = uno["fps120"]
    return suo


def corri(cartella: Path, clip: list[dict], lavoro: dict,
          al_passo: Callable[[int, int], None] | None = None, freno=None,
          racconta=None, volte: int = VOLTE, foto: list[dict] | None = None,
          lavoro_foto: dict | None = None, volti: list[dict] | None = None,
          quali_volti: list[str] | None = None) -> dict:
    cartella = Path(cartella)
    foto = list(foto or [])
    volti = list(volti or [])
    quali_volti = [motore for motore in quali_volti or [] if motore in IDEA_DEI_VOLTI]
    per_i_fili = file_per_i_fili(clip, foto, volti)
    due = per_il_dietro(clip)
    totale = (2 * volte * bool(due) + passi(clip, volte) + len(foto) * 2 * volte
              + passi_del_precarico(clip, foto, volte)
              + len(quali_volti) * len(volti) * 2 * volte
              + (2 * volte if per_i_fili else 0))
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
        suo = _lavoro_del_video(lavoro, originale, uno)
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
    _il_precarico(cartella, clip, lavoro, foto, lavoro_foto or lavoro, volte, avanti)
    if volti and quali_volti:
        _i_volti(cartella, volti, lavoro_foto or lavoro, quali_volti, volte, avanti)
    if per_i_fili:
        _i_fili(cartella, per_i_fili, volte, avanti)
    if due:
        _il_dietro(cartella, due, lavoro, volte, avanti)
    dati = esito(clip, giri_fatti(cartella), volte, foto, giri_fatti(cartella / FOTO),
                 giri_del_precarico(cartella), volti, giri_fatti(cartella / VOLTI),
                 quali_volti, giri_fatti(cartella / FILI) if per_i_fili else None,
                 giri_fatti(cartella / DIETRO) if due else None)
    scrivi_esito(cartella, dati)
    return dati


__all__ = ["DIETRO", "ESITO",
           "FISSI", "FOTO", "GIRI", "MEZZI", "MISURA", "NUOVO", "ORIGINALE", "PIANO",
           "PRECARICO", "con_ldf", "con_lo_scambio", "fluido_col_precarico",
           "foto_col_precarico", "giri_del_precarico", "impronta_dei_quadri",
           "passi_del_precarico", "righe_del_precarico", "scheda_col_precarico",
           "REGISTRATI", "Registratore", "Riproduttore", "VECCHIO", "VOLTE", "con_il_fluido",
           "corri", "esito", "fai_l_originale", "foto_nuove", "foto_vecchia", "giri_fatti",
           "impronta", "la_scheda", "lavoro_della_foto", "leggi_esito", "misura_piccola",
           "ordine", "passi", "registra", "registrati_buoni", "riassunto", "scrivi_esito",
           "per_il_dietro", "un_giro", "un_giro_dietro"]
