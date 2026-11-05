from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from officina.miglioria import gara120_casi as g
from officina.miglioria import gara120_rovina as rovina
from officina.miglioria import gara120_scarica as sc
from officina.miglioria import gara120_voti as voti

PIANO = "piano.json"
RISULTATI = "risultati.jsonl"
DEPOSITO = "gimm"
GIMM, LDF, FUSIONE = "gimm", "ldf", "fusione"
CONCORRENTI = (GIMM, LDF, FUSIONE)
NOMI = {GIMM: "GIMM-VFI-F-P", LDF: "LDF-VFI", FUSIONE: "Fusione zona per zona"}
MISURE = ("somiglianza", "struttura", "zona_peggiore")
NON_RIUSCITO = {"somiglianza": 0.0, "struttura": 0.0, "zona_peggiore": 0.0}


@dataclass
class Piano:
    casi: list
    nomi: dict
    adobe: dict


def caso_da_lista(voce: list) -> g.Caso:
    nome, gruppo, scena, passo, volte, rovinato, tenuti, veri = voce
    return g.Caso(nome, gruppo, scena, int(passo), int(volte), rovinato,
                  tuple(int(t) for t in tenuti), tuple(int(v) for v in veri))


def scrivi_piano(cartella: Path, elenco: sc.Elenco, adobe: dict) -> Piano:
    casi = (list(elenco.casi) + g.casi_xtest(sorted(_clip_xtest()))
            + g.casi_adobe(sorted(adobe)))
    scelte = {c.scena[len(g.ADOBE):] for c in casi if c.scena.startswith(g.ADOBE)}
    nomi: dict = {}
    for caso in elenco.casi:
        for numero in caso.servono():
            nomi.setdefault(caso.scena, {})[str(numero)] = elenco.veri_nomi[
                (caso.scena, numero)]
    dati = {"casi": json.loads(g.testo_casi(casi)), "nomi": nomi,
            "adobe": {c: adobe[c] for c in sorted(scelte)}}
    posto = Path(cartella) / PIANO
    nuovo = posto.with_name(posto.name + sc.PARTE)
    nuovo.write_text(json.dumps(dati), encoding="utf-8")
    os.replace(nuovo, posto)
    return leggi_piano(cartella)


def _clip_xtest() -> list[str]:
    from officina.miglioria import gara120_fonti

    return list(gara120_fonti.XTEST_MP4)


def leggi_piano(cartella: Path) -> Piano:
    dati = json.loads((Path(cartella) / PIANO).read_text(encoding="utf-8"))
    return Piano([caso_da_lista(v) for v in dati["casi"]], dati["nomi"], dati["adobe"])


def prendi_per(cartella: Path, piano: Piano, caso: g.Caso) -> Callable:
    import numpy as np
    from PIL import Image

    if caso.scena.startswith(g.XTEST):
        quadri = sc.quadri_xtest(cartella, caso.scena[len(g.XTEST):], caso.servono())
        return quadri.__getitem__
    if caso.scena.startswith(g.ADOBE):
        return sc.prendi_adobe(cartella, piano.adobe[caso.scena[len(g.ADOBE):]])
    nomi = piano.nomi[caso.scena]
    casa = Path(cartella) / sc.SNU

    def prendi(numero: int):
        with Image.open(casa / nomi[str(numero)]) as immagine:
            return np.asarray(immagine.convert("RGB"))

    return prendi


def indice(caso: g.Caso, vero: int) -> tuple[int, int]:
    for posto in range(len(caso.tenuti) - 1):
        prima, dopo = caso.tenuti[posto], caso.tenuti[posto + 1]
        if prima < vero < dopo:
            salto = (vero - prima) * caso.volte
            if salto % (dopo - prima):
                raise ValueError((caso.nome, vero))
            return posto * caso.volte + salto // (dopo - prima), posto * caso.volte
    raise ValueError((caso.nome, vero))


class Risultati:

    def __init__(self, cartella: Path) -> None:
        self.file = Path(cartella) / RISULTATI
        self.righe: list[dict] = []
        try:
            testo = self.file.read_text(encoding="utf-8")
        except OSError:
            testo = ""
        buone = []
        for riga in testo.splitlines():
            try:
                self.righe.append(json.loads(riga))
            except ValueError:
                break
            buone.append(riga)
        if testo and testo != "".join(r + "\n" for r in buone):
            nuovo = self.file.with_name(self.file.name + sc.PARTE)
            nuovo.write_text("".join(r + "\n" for r in buone), encoding="utf-8")
            os.replace(nuovo, self.file)

    def firma(self) -> dict | None:
        for riga in self.righe:
            if riga.get("firma") is not None:
                return riga["firma"]
        return None

    def ricomincia(self, firma: dict) -> None:
        self.file.parent.mkdir(parents=True, exist_ok=True)
        self.file.write_text(json.dumps({"firma": firma}) + "\n", encoding="utf-8")
        self.righe = [{"firma": firma}]

    def fatti(self, fase: str) -> dict[str, dict]:
        return {r["nome"]: r for r in self.righe if r.get("fase") == fase}

    def aggiungi(self, riga: dict) -> None:
        with open(self.file, "a", encoding="utf-8") as uscita:
            uscita.write(json.dumps(riga) + "\n")
            uscita.flush()
            os.fsync(uscita.fileno())
        self.righe.append(riga)


def _deposito(risultati: Path, caso: g.Caso) -> Path:
    return Path(risultati) / DEPOSITO / (caso.nome.replace("/", "~") + ".npz")


def _salva_gimm(posto: Path, quadri: dict) -> None:
    import numpy as np

    posto.parent.mkdir(parents=True, exist_ok=True)
    nuovo = posto.with_name(posto.stem + ".parte.npz")
    np.savez_compressed(nuovo, **{str(k): v for k, v in quadri.items()})
    os.replace(nuovo, posto)


def _leggi_gimm(posto: Path) -> dict:
    import numpy as np

    with np.load(posto) as dentro:
        return {int(k): dentro[k] for k in dentro.files}


def _voti_lista(fatti: list, veri: list) -> list[dict]:
    return [voti.voti(f, v) for f, v in zip(fatti, veri)]


def _uscita(motore, entrate: list, volte: int) -> list:
    return list(motore.video(iter(entrate), volte))


def fase_gimm(caso, entrate, veri, gimm, risultati: Path) -> dict:
    partito = time.monotonic()
    uscita = _uscita(gimm, entrate, caso.volte)
    secondi = round(time.monotonic() - partito, 2)
    tenere = {}
    fatti = []
    for vero in caso.veri:
        dove, base = indice(caso, vero)
        fatti.append(uscita[dove])
        tenere[dove] = uscita[dove]
        tenere[base] = uscita[base]
        tenere[base + caso.volte] = uscita[base + caso.volte]
    _salva_gimm(_deposito(risultati, caso), tenere)
    return {"fase": GIMM, "nome": caso.nome, "secondi": secondi,
            "voti": _voti_lista(fatti, veri)}


def fase_ldf(caso, entrate, veri, ldf, risultati: Path, non_ci_sta=()) -> dict:
    from officina.miglioria.fusione120 import fondi

    da_gimm = _leggi_gimm(_deposito(risultati, caso))
    partito = time.monotonic()
    try:
        uscita = _uscita(ldf, entrate, caso.volte)
    except tuple(non_ci_sta) as errore:
        return {"fase": LDF, "nome": caso.nome, "non_riuscito": type(errore).__name__}
    secondi = round(time.monotonic() - partito, 2)
    fatti_ldf, fatti_fusi = [], []
    partito = time.monotonic()
    for vero in caso.veri:
        dove, base = indice(caso, vero)
        fatti_ldf.append(uscita[dove])
        fatti_fusi.append(fondi(da_gimm[dove], uscita[dove], da_gimm[base],
                                da_gimm[base + caso.volte]))
    fondere = round(time.monotonic() - partito, 2)
    return {"fase": LDF, "nome": caso.nome, "secondi": secondi, "fondere": fondere,
            "voti": _voti_lista(fatti_ldf, veri),
            "voti_fusione": _voti_lista(fatti_fusi, veri)}


def corri(cartella: Path, risultati: Path, gimm, ldf,
          al_caso: Callable[[str, int, int], None] | None = None,
          fermati: Callable[[], bool] | None = None, non_ci_sta=()) -> Risultati:
    piano = leggi_piano(cartella)
    registro = Risultati(risultati)
    firma = {GIMM: gimm.firma(), LDF: ldf.firma(), "casi": g.impronta(
        g.testo_casi(piano.casi))}
    if registro.firma() != firma:
        registro.ricomincia(firma)
    totale = 2 * len(piano.casi)
    for fase, motore in ((GIMM, gimm), (LDF, ldf)):
        fatti = registro.fatti(fase)
        for caso in piano.casi:
            if fermati is not None and fermati():
                return registro
            if caso.nome not in fatti:
                entrate, veri = rovina.prepara(caso, prendi_per(cartella, piano, caso))
                if fase == GIMM:
                    riga = fase_gimm(caso, entrate, veri, motore, risultati)
                else:
                    riga = fase_ldf(caso, entrate, veri, motore, risultati, non_ci_sta)
                registro.aggiungi(riga)
                fatti[caso.nome] = riga
            if al_caso is not None:
                gia = len(registro.fatti(GIMM)) + len(registro.fatti(LDF))
                al_caso(fase, gia, totale)
        motore.spegni()
    return registro


def per_concorrente(registro: Risultati, casi: list) -> dict[str, dict[str, dict]]:
    da_gimm, da_ldf = registro.fatti(GIMM), registro.fatti(LDF)
    tutti: dict[str, dict[str, dict]] = {c: {} for c in CONCORRENTI}
    for caso in casi:
        uno, due = da_gimm.get(caso.nome), da_ldf.get(caso.nome)
        if uno is None or due is None:
            continue
        quanti = len(caso.veri)
        tutti[GIMM][caso.nome] = {"voti": uno["voti"], "secondi": uno["secondi"]}
        if "non_riuscito" in due:
            for nome in (LDF, FUSIONE):
                tutti[nome][caso.nome] = {"voti": [NON_RIUSCITO] * quanti,
                                          "secondi": None, "non_riuscito": True}
            continue
        tutti[LDF][caso.nome] = {"voti": due["voti"], "secondi": due["secondi"]}
        tutti[FUSIONE][caso.nome] = {
            "voti": due["voti_fusione"],
            "secondi": round(uno["secondi"] + due["secondi"] + due["fondere"], 2)}
    return tutti


def classifica(registro: Risultati, casi: list) -> dict:
    tutti = per_concorrente(registro, casi)
    medie: dict[str, dict] = {}
    for nome, fatti in tutti.items():
        voti_tutti = [v for f in fatti.values() for v in f["voti"]]
        secondi = [f["secondi"] for f in fatti.values() if f.get("secondi") is not None]
        medie[nome] = {
            "casi": len(fatti),
            "non_riusciti": sum(1 for f in fatti.values() if f.get("non_riuscito")),
            "secondi": round(sum(secondi), 1),
            **{m: (round(sum(v[m] for v in voti_tutti) / len(voti_tutti), 5)
                   if voti_tutti else None) for m in MISURE}}
    vincitori = {}
    for misura in MISURE:
        valori = {n: d[misura] for n, d in medie.items() if d[misura] is not None}
        if valori:
            alto = max(valori.values())
            primi = [n for n, v in valori.items() if v == alto]
            vincitori[misura] = primi[0] if len(primi) == 1 else None
    conti: dict[str, int] = {}
    for nome in vincitori.values():
        if nome is not None:
            conti[nome] = conti.get(nome, 0) + 1
    primo = next((n for n, quante in conti.items() if quante >= 2), None)
    return {"medie": medie, "vincitori": vincitori, "primo": primo}


def classifiche(registro: Risultati, casi: list) -> dict:
    difficilissimi = [c for c in casi if c.gruppo == g.DIFFICILISSIMO]
    return {"tutto": classifica(registro, casi),
            "difficilissimi": classifica(registro, difficilissimi)}


__all__ = ["CONCORRENTI", "FUSIONE", "GIMM", "LDF", "MISURE", "NOMI", "Piano", "Risultati",
           "caso_da_lista", "classifica", "classifiche", "corri", "indice", "leggi_piano",
           "per_concorrente", "prendi_per", "scrivi_piano"]
