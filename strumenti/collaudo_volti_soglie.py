from __future__ import annotations

import argparse
import io
import itertools
import json
import sys
import time
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import collaudo_volti_difficili as base

SICUREZZA_RACCOLTA = 0.30
SOGLIE = (0.50, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85)
SOGLIE_PICCOLI = (None, 0.70, 0.75, 0.80, 0.85, 0.90)
CONFERME = (False, True)
SOGLIE_SENZA_CONFERMA = (None, 0.70, 0.80, 0.90)
OGGI = (0.60, None, False, None)
MOLTI_FALSI = 1.25


def tieni(faccia: dict, regola) -> bool:
    soglia, piccoli, conferma, senza = regola
    if faccia["sicurezza"] < soglia:
        return False
    piccola = faccia["lato"] < base.PICCOLO
    if piccoli is not None and piccola and faccia["sicurezza"] < piccoli:
        return False
    if conferma and not faccia["confermata"] and senza is not None \
            and faccia["sicurezza"] < senza:
        return False
    return True


def regole() -> list:
    tutte = []
    for soglia, piccoli, conferma in itertools.product(SOGLIE, SOGLIE_PICCOLI, CONFERME):
        if piccoli is not None and piccoli <= soglia:
            continue
        for senza in (SOGLIE_SENZA_CONFERMA if conferma else (None,)):
            if conferma and (senza is None or senza <= soglia):
                continue
            tutte.append((soglia, piccoli, conferma, senza))
    if OGGI not in tutte:
        tutte.append(OGGI)
    return tutte


def nome_di(regola) -> str:
    soglia, piccoli, conferma, senza = regola
    pezzi = [f"sicurezza {soglia:.2f}"]
    if piccoli is not None:
        pezzi.append(f"piccoli {piccoli:.2f}")
    if conferma:
        pezzi.append(f"solo a 1280 {senza:.2f}")
    return ", ".join(pezzi)


def valuta(raccolta: list, regola) -> dict:
    conti: dict = {}
    for voce in raccolta:
        uno = conti.setdefault(voce["gruppo"], base.nuovi_conti())
        trovati = [(f["riquadro"], f["sicurezza"])
                   for f in voce["facce"] if tieni(f, regola)]
        base.conta(voce["veri"], trovati, uno)
    return conti


def percento(conti: dict, gruppo: str) -> float:
    presi, su = conti[gruppo]
    return 100 * presi / su if su else 0.0


def falsi(conti: dict) -> float:
    return 100 * conti["falsi"] / conti["foto"] if conti["foto"] else 0.0


def riassunto(conti: dict) -> dict:
    fuori = {}
    for gruppo, uno in conti.items():
        fuori[gruppo] = {"difficili": round(percento(uno, "difficili"), 1),
                         "molto difficili": round(percento(uno, "molto difficili"), 1),
                         "tutti": round(percento(uno, "tutti"), 1),
                         "falsi ogni 100 foto": round(falsi(uno), 1)}
    return fuori


def media_falsi(conti: dict) -> float:
    return sum(falsi(uno) for uno in conti.values()) / len(conti)


def media_difficili(conti: dict) -> float:
    return sum(percento(uno, "difficili") for uno in conti.values()) / len(conti)


def main() -> int:
    import onnxruntime
    from PIL import Image

    from officina.immagini import lettura
    from officina.volti import insight

    argomenti = argparse.ArgumentParser()
    argomenti.add_argument("--cartella", required=True)
    argomenti.add_argument("--uscita", required=True)
    argomenti.add_argument("--quante", type=int, default=0)
    scelti = argomenti.parse_args()
    casa = Path(scelti.cartella)
    casa.mkdir(parents=True, exist_ok=True)

    archivio, foto, pesi = base.prendi_tutto(casa)
    if archivio is None:
        return 1

    rilevatore = insight.Rilevatore(casa, sicurezza_minima=SICUREZZA_RACCOLTA)
    rilevatore._trova = onnxruntime.InferenceSession(
        str(pesi), providers=["CPUExecutionProvider"])
    rilevatore._riconosce = object()
    rilevatore._impronta_di = lambda dritta, numpy: None
    insight.LATO_MINIMO = 0.015
    insight.SICUREZZA_SOLO_GRANDE = 0.0

    def cerca(immagine, lati) -> list:
        insight.LATI_DEL_QUADRATO = lati
        return rilevatore.guarda(immagine)

    raccolta: list = []
    lavoro = casa / "foto.jpg"
    scelte = sorted(foto)[::base.OGNI]
    if scelti.quante:
        scelte = scelte[:scelti.quante]
    print("FOTO_SCELTE", len(scelte), flush=True)
    inizio = time.monotonic()
    with zipfile.ZipFile(archivio) as z:
        voci = {n.split("images/", 1)[-1]: n for n in z.namelist() if n.endswith(".jpg")}
        for numero, nome in enumerate(scelte):
            dati = z.read(voci[nome])
            lavoro.write_bytes(dati)
            with Image.open(io.BytesIO(dati)) as prima:
                larga, alta = prima.size
            veri = base.veri_di(foto[nome], larga, alta)
            immagine = lettura.copia_di_lavoro(lavoro, 1280).convert("RGB")
            casi = [("pulite", immagine)]
            if not numero % (base.OGNI_ROVINATE // base.OGNI):
                casi += [(come, base.rovina(immagine, come, numero)) for come in base.ROVINE]
            for gruppo, quale in casi:
                piccole = cerca(quale, (640,))
                facce = []
                for faccia in cerca(quale, (640, 1280)):
                    confermata = any(base.sovrapposti(faccia.riquadro, altra.riquadro)
                                     >= base.STESSO_VOLTO for altra in piccole)
                    facce.append({"riquadro": faccia.riquadro,
                                  "sicurezza": faccia.sicurezza,
                                  "lato": min(faccia.riquadro[2], faccia.riquadro[3]),
                                  "confermata": confermata})
                raccolta.append({"gruppo": gruppo, "veri": veri, "facce": facce})
            if numero % 50 == 49:
                print(f"fatte {numero + 1} di {len(scelte)} in "
                      f"{(time.monotonic() - inizio) / 60:.0f} min", flush=True)

    oggi = valuta(raccolta, OGGI)
    tetto = media_difficili(oggi) - MOLTI_FALSI
    tabella = []
    for regola in regole():
        conti = valuta(raccolta, regola)
        tabella.append({"regola": nome_di(regola), "valori": list(regola),
                        "media difficili": round(media_difficili(conti), 2),
                        "media falsi": round(media_falsi(conti), 2),
                        "dettagli": riassunto(conti)})
    buone = [r for r in tabella if r["media difficili"] >= tetto]
    buone.sort(key=lambda r: (r["media falsi"], -r["media difficili"]))
    print("\n== OGGI ==", flush=True)
    print(json.dumps(riassunto(oggi), ensure_ascii=False), flush=True)
    print(f"\n== LE MIGLIORI che perdono al massimo {MOLTI_FALSI} punti sui difficili ==",
          flush=True)
    for riga in buone[:15]:
        print(f"{riga['regola']:50s} | difficili {riga['media difficili']:.1f} | "
              f"falsi {riga['media falsi']:.1f}", flush=True)
        for gruppo, valori in riga["dettagli"].items():
            print(f"    {gruppo:10s} {valori}", flush=True)
    Path(scelti.uscita).write_text(json.dumps(
        {"oggi": riassunto(oggi), "migliori": buone[:15],
         "tutte": sorted(tabella, key=lambda r: r["media falsi"]), "foto": len(scelte)},
        ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
