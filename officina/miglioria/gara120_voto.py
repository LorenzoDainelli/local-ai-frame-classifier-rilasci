from __future__ import annotations

import json
import os
import random
import time
from pathlib import Path
from typing import Callable

from officina.miglioria import gara120_casi as g
from officina.miglioria import gara120_corsa as corsa
from officina.miglioria import gara120_rovina as rovina
from officina.miglioria import gara120_scarica as sc

QUANTI = 20
PER_SCENA = 2
SECONDI = 2.0
VELOCITA_VERA = 240
USCITA = 120
CARTELLA = "voto"
CLIP = "clip.json"
VOTI = "voti.json"
NOMI = "nomi.json"
VERO = "vero"
LETTERE = ("A", "B", "C")
MINIMO = 8
QUALITA = 12


def _e_snu(caso: g.Caso) -> bool:
    return not caso.scena.startswith((g.XTEST, g.ADOBE))


def distanza(fatti: dict[str, dict], nome: str) -> float:
    medie = {}
    for concorrente in corsa.CONCORRENTI:
        voti = fatti[concorrente][nome]["voti"]
        medie[concorrente] = (sum(v["somiglianza"] for v in voti) / len(voti),
                              sum(v["zona_peggiore"] for v in voti) / len(voti))
    uno = [m[0] for m in medie.values()]
    due = [m[1] for m in medie.values()]
    return (max(uno) - min(uno)) + (max(due) - min(due))


def scegli(registro: corsa.Risultati, casi: list, quanti: int = QUANTI,
           adatto: Callable[[g.Caso], bool] | None = None) -> list[g.Caso]:
    adatti = [c for c in casi if c.gruppo == g.DIFFICILISSIMO and _e_snu(c)]
    fatti = corsa.per_concorrente(registro, adatti)
    pronti = [c for c in adatti if all(c.nome in fatti[n] for n in corsa.CONCORRENTI)
              and not fatti[corsa.LDF][c.nome].get("non_riuscito")]
    ordine = sorted(pronti, key=lambda c: (-distanza(fatti, c.nome), c.nome))
    scelti: list[g.Caso] = []
    per_scena: dict[str, int] = {}
    for caso in ordine:
        if len(scelti) >= quanti:
            break
        if per_scena.get(caso.scena, 0) >= PER_SCENA:
            continue
        if adatto is not None and not adatto(caso):
            continue
        scelti.append(caso)
        per_scena[caso.scena] = per_scena.get(caso.scena, 0) + 1
    return scelti


def clip_di(caso: g.Caso, presenti: set[int]) -> g.Caso | None:
    passo = VELOCITA_VERA // USCITA * caso.volte
    centro = (caso.tenuti[1] + caso.tenuti[2]) // 2
    mezzo = int(SECONDI * VELOCITA_VERA / 2)
    margine = (-g.OTTURATORE[0], g.OTTURATORE[1]) if caso.rovina == g.MOSSO else (0, 0)
    primo = min(presenti) + margine[0]
    ultimo = max(presenti) - margine[1]
    inizio = caso.tenuti[1] - ((caso.tenuti[1] - centro + mezzo) // passo) * passo
    tenuti = [t for t in range(inizio, centro + mezzo + 1, passo) if primo <= t <= ultimo]
    while tenuti and any(n not in presenti for n in _servono(caso, tenuti)):
        tenuti = tenuti[1:-1]
    if len(tenuti) < MINIMO:
        return None
    veri = tuple(range(tenuti[0], tenuti[-1] + 1, VELOCITA_VERA // USCITA))
    return g.Caso(caso.nome, caso.gruppo, caso.scena, passo, caso.volte, caso.rovina,
                  tuple(tenuti), veri)


def _servono(caso: g.Caso, tenuti: list[int]) -> set[int]:
    if not tenuti:
        return set()
    tutti = set(range(tenuti[0], tenuti[-1] + 1, VELOCITA_VERA // USCITA))
    if caso.rovina == g.MOSSO:
        tutti = {n + d for n in tutti for d in range(g.OTTURATORE[0], g.OTTURATORE[1] + 1)}
    return tutti


def prepara_voto(risultati: Path, registro: corsa.Risultati, elenco: sc.Elenco,
                 piano: corsa.Piano) -> list[g.Caso]:
    def adatto(caso: g.Caso) -> bool:
        return clip_di(caso, elenco.presenti.get(caso.scena, set())) is not None

    clip = [clip_di(c, elenco.presenti[c.scena])
            for c in scegli(registro, piano.casi, adatto=adatto)]
    posto = Path(risultati) / CARTELLA / CLIP
    posto.parent.mkdir(parents=True, exist_ok=True)
    nomi: dict[str, dict[str, str]] = {}
    for uno in clip:
        for numero in _servono(uno, list(uno.tenuti)):
            nomi.setdefault(uno.scena, {})[str(numero)] = elenco.veri_nomi[
                (uno.scena, numero)]
    _scrivi(posto.with_name(NOMI), json.dumps(nomi, sort_keys=True))
    _scrivi(posto, g.testo_casi(clip))
    return clip


def _scrivi(posto: Path, testo: str) -> None:
    nuovo = posto.with_name(posto.name + sc.PARTE)
    nuovo.write_text(testo, encoding="utf-8")
    os.replace(nuovo, posto)


def prendi_del_voto(dati: Path, risultati: Path) -> Callable:
    import numpy as np
    from PIL import Image

    nomi = json.loads((Path(risultati) / CARTELLA / NOMI).read_text(encoding="utf-8"))
    casa = Path(dati) / sc.SNU

    def prendi_di(clip: g.Caso) -> Callable:
        della_scena = nomi[clip.scena]

        def prendi(numero: int):
            with Image.open(casa / della_scena[str(numero)]) as immagine:
                return np.asarray(immagine.convert("RGB"))

        return prendi

    return prendi_di


def leggi_clip(risultati: Path) -> list[g.Caso]:
    posto = Path(risultati) / CARTELLA / CLIP
    return [corsa.caso_da_lista(v) for v in json.loads(posto.read_text(encoding="utf-8"))]


def nomi_del_voto(clip: list[g.Caso], elenco: sc.Elenco) -> list[str]:
    return sorted({elenco.veri_nomi[(c.scena, n)] for c in clip
                   for n in _servono(c, list(c.tenuti))})


def prepara_clip(clip: g.Caso, prendi) -> tuple[list, list]:
    if clip.rovina == g.MOSSO:
        entrate = [rovina.mosso(prendi, n) for n in clip.tenuti]
        veri = [rovina.mosso(prendi, n) for n in clip.veri]
    else:
        entrate = [prendi(n) for n in clip.tenuti]
        veri = [prendi(n) for n in clip.veri]
    if clip.rovina == "buio":
        entrate = [rovina.buio(q, rovina.seme(clip.nome, n))
                   for q, n in zip(entrate, clip.tenuti)]
        veri = [rovina.buio(q, None) for q in veri]
    elif clip.rovina == "rumore":
        entrate = [rovina.rumore(q, rovina.seme(clip.nome, n))
                   for q, n in zip(entrate, clip.tenuti)]
    elif clip.rovina == "compresso":
        entrate = rovina.compresso(entrate)
        veri = rovina.compresso(veri)
    return entrate, veri


def velocita(clip: g.Caso) -> int:
    return VELOCITA_VERA * clip.volte // clip.passo


def scrivi_video(quadri: list, posto: Path, fps: int) -> None:
    import av
    import numpy as np

    alto, largo = np.asarray(quadri[0]).shape[:2]
    nuovo = posto.with_name(posto.stem + ".parte.mp4")
    posto.parent.mkdir(parents=True, exist_ok=True)
    with av.open(str(nuovo), mode="w") as uscita:
        flusso = uscita.add_stream("libx264", rate=fps)
        flusso.width, flusso.height = largo - largo % 2, alto - alto % 2
        flusso.pix_fmt = "yuv420p"
        flusso.options = {"crf": str(QUALITA), "preset": "slow"}
        for quadro in quadri:
            pezzo = np.ascontiguousarray(np.asarray(quadro)[:flusso.height, :flusso.width])
            uscita.mux(flusso.encode(av.VideoFrame.from_ndarray(pezzo, format="rgb24")))
        uscita.mux(flusso.encode(None))
    os.replace(nuovo, posto)


def _cartella_clip(risultati: Path, numero: int) -> Path:
    return Path(risultati) / CARTELLA / f"{numero:02d}"


def fai_clip(risultati: Path, clip: list[g.Caso], prendi_di: Callable, gimm, ldf,
             al_clip: Callable[[int, int], None] | None = None,
             fermati: Callable[[], bool] | None = None) -> None:
    from officina.miglioria.fusione120 import fondi

    for fase, motore in ((corsa.GIMM, gimm), (corsa.LDF, ldf)):
        for numero, uno in enumerate(clip):
            if fermati is not None and fermati():
                return
            casa = _cartella_clip(risultati, numero)
            secondi_file = casa / f"{fase}.json"
            if not secondi_file.is_file():
                entrate, veri = prepara_clip(uno, prendi_di(uno))
                quanti = (len(uno.tenuti) - 1) * uno.volte + 1
                partito = time.monotonic()
                uscita = list(motore.video(iter(entrate), uno.volte))[:quanti]
                secondi = round(time.monotonic() - partito, 2)
                if fase == corsa.GIMM:
                    scrivi_video(veri, casa / f"{VERO}.mp4", velocita(uno))
                    _salva_quadri(casa / "gimm.npz", uscita)
                    scrivi_video(uscita, casa / "gimm.mp4", velocita(uno))
                else:
                    da_gimm = _leggi_quadri(casa / "gimm.npz")
                    partito = time.monotonic()
                    fusi = [da_gimm[k] if k % uno.volte == 0 else fondi(
                        da_gimm[k], uscita[k], da_gimm[k - k % uno.volte],
                        da_gimm[k - k % uno.volte + uno.volte]) for k in range(quanti)]
                    fondere = round(time.monotonic() - partito, 2)
                    scrivi_video(uscita, casa / "ldf.mp4", velocita(uno))
                    scrivi_video(fusi, casa / "fusione.mp4", velocita(uno))
                    gimm_secondi = json.loads((casa / "gimm.json").read_text("utf-8"))
                    (casa / "fusione.json").write_text(json.dumps(
                        {"secondi": round(secondi + fondere + gimm_secondi["secondi"], 2)}),
                        encoding="utf-8")
                secondi_file.write_text(json.dumps({"secondi": secondi}), encoding="utf-8")
                if fase == corsa.LDF:
                    (casa / "gimm.npz").unlink(missing_ok=True)
            if al_clip is not None:
                al_clip(numero + 1 + (len(clip) if fase == corsa.LDF else 0), 2 * len(clip))
        motore.spegni()


def _salva_quadri(posto: Path, quadri: list) -> None:
    import numpy as np

    nuovo = posto.with_name(posto.stem + ".parte.npz")
    np.savez_compressed(nuovo, *quadri)
    os.replace(nuovo, posto)


def _leggi_quadri(posto: Path) -> list:
    import numpy as np

    with np.load(posto) as dentro:
        return [dentro[f"arr_{k}"] for k in range(len(dentro.files))]


def clip_pronte(risultati: Path) -> bool:
    try:
        clip = leggi_clip(risultati)
    except (OSError, ValueError):
        return False
    return bool(clip) and all(
        (_cartella_clip(risultati, n) / f"{nome}.mp4").is_file()
        for n in range(len(clip)) for nome in (*corsa.CONCORRENTI, VERO))


def _leggi_voti(risultati: Path) -> dict:
    try:
        return json.loads((Path(risultati) / CARTELLA / VOTI).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _scrivi_voti(risultati: Path, voti: dict) -> None:
    _scrivi(Path(risultati) / CARTELLA / VOTI, json.dumps(voti, ensure_ascii=False))


def lettere(risultati: Path, numero: int, caso: random.Random | None = None) -> dict:
    voti = _leggi_voti(risultati)
    chiave = str(numero)
    if chiave not in voti:
        caso = caso or random.SystemRandom()
        mescolati = list(corsa.CONCORRENTI)
        caso.shuffle(mescolati)
        voti[chiave] = {"lettere": dict(zip(LETTERE, mescolati)), "scelta": None}
        _scrivi_voti(risultati, voti)
    return voti[chiave]


def secondi_di(risultati: Path, numero: int, concorrente: str) -> float | None:
    try:
        dati = json.loads((_cartella_clip(risultati, numero) / f"{concorrente}.json")
                          .read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return dati.get("secondi")


def video_di(risultati: Path, numero: int, lettera: str | None) -> Path:
    voti = _leggi_voti(risultati)
    voce = voti.get(str(numero))
    if lettera is None:
        if voce is None or voce.get("scelta") is None:
            raise PermissionError("il vero si vede dopo il voto")
        return _cartella_clip(risultati, numero) / f"{VERO}.mp4"
    if voce is None or lettera not in voce["lettere"]:
        raise KeyError(lettera)
    return _cartella_clip(risultati, numero) / f"{voce['lettere'][lettera]}.mp4"


def vota(risultati: Path, numero: int, lettera: str, secondi: float | None = None) -> dict:
    voti = _leggi_voti(risultati)
    voce = voti.get(str(numero))
    if voce is None or lettera not in LETTERE:
        raise KeyError(lettera)
    if voce.get("scelta") is not None:
        return voce
    voce["scelta"] = lettera
    voce["secondi_per_votare"] = None if secondi is None else round(float(secondi), 1)
    _scrivi_voti(risultati, voti)
    return voce


def conto(risultati: Path, quanti: int) -> dict:
    voti = _leggi_voti(risultati)
    punti = {c: 0 for c in corsa.CONCORRENTI}
    votati = 0
    for numero in range(quanti):
        voce = voti.get(str(numero))
        if voce and voce.get("scelta"):
            punti[voce["lettere"][voce["scelta"]]] += 1
            votati += 1
    primo = None
    if votati == quanti and quanti:
        alto = max(punti.values())
        primi = [c for c, p in punti.items() if p == alto]
        primo = primi[0] if len(primi) == 1 else None
    return {"punti": punti, "votati": votati, "quanti": quanti, "primo": primo}


def vincitore(automatico: str | None, voto: str | None) -> str | None:
    if automatico is not None and automatico == voto:
        return automatico
    return None


__all__ = ["LETTERE", "QUANTI", "clip_di", "clip_pronte", "conto", "distanza", "fai_clip",
           "leggi_clip", "lettere", "nomi_del_voto", "prendi_del_voto", "prepara_clip",
           "prepara_voto", "scegli", "secondi_di", "velocita", "video_di", "vincitore", "vota"]
