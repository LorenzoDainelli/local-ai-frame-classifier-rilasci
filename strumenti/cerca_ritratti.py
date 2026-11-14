from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

API = "https://commons.wikimedia.org/w/api.php"
CHI = "officina-collaudo/1.0 (collaudo di ingrandimento dei ritratti)"
CATEGORIE = ("Quality images of people", "Featured pictures of people",
             "Quality images of portraits", "Featured portraits",
             "Valued images of people")
PROFONDITA = 2
LICENZE = ("cc0", "cc by", "cc-by", "public domain", "pd")
LATO_CORTO = 2800
LATO_LUNGO = 4000
VOLTO_MINIMO = 500
VOLTO_SICURO = 0.80
COLORE_MINIMO = 18.0
PER_AUTORE = 2
QUANTI = 80
RISERVE = 20
MASSIMO_DA_GUARDARE = 900


def chiedi(**parametri) -> dict:
    parametri = {"format": "json", "formatversion": "2", "maxlag": "5", **parametri}
    indirizzo = API + "?" + urllib.parse.urlencode(parametri)
    for prova in range(8):
        time.sleep(1.0)
        try:
            richiesta = urllib.request.Request(indirizzo, headers={
                "User-Agent": CHI, "Accept-Encoding": "identity"})
            with urllib.request.urlopen(richiesta, timeout=60) as risposta:
                dati = json.loads(risposta.read())
            if (dati.get("error") or {}).get("code") == "maxlag":
                raise RuntimeError("maxlag")
            return dati
        except urllib.error.HTTPError as guasto:
            attesa = guasto.headers.get("Retry-After") or ""
            corpo = guasto.read()[:200].decode("utf-8", "replace").replace("\n", " ")
            print("API riprovo", prova, guasto.code, attesa, corpo, flush=True)
            pausa = int(attesa) if attesa.isdigit() else 15 * (prova + 1)
            time.sleep(min(pausa, 120))
        except Exception as guasto:
            print("API riprovo", prova, type(guasto).__name__, guasto, flush=True)
            time.sleep(15 * (prova + 1))
    raise RuntimeError("Commons non risponde")


def membri(categoria: str, tipo: str) -> list[str]:
    fuori: list[str] = []
    seguito: dict = {}
    while True:
        dati = chiedi(action="query", list="categorymembers",
                      cmtitle="Category:" + categoria, cmtype=tipo, cmlimit="500",
                      **seguito)
        fuori += [m["title"] for m in dati.get("query", {}).get("categorymembers", [])]
        if "continue" not in dati:
            return fuori
        seguito = {"cmcontinue": dati["continue"]["cmcontinue"]}


def tutti_i_file() -> list[str]:
    visti: set[str] = set()
    file: list[str] = []
    for radice in CATEGORIE:
        coda = [(radice, 0)]
        while coda:
            categoria, livello = coda.pop(0)
            if categoria in visti:
                continue
            visti.add(categoria)
            nuovi = membri(categoria, "file")
            print("CATEGORIA", categoria, len(nuovi), flush=True)
            file += nuovi
            if livello < PROFONDITA:
                coda += [(s.split(":", 1)[1], livello + 1)
                         for s in membri(categoria, "subcat")]
    return sorted(set(file))


def informazioni(titoli: list[str]) -> list[dict]:
    fuori = []
    for inizio in range(0, len(titoli), 50):
        dati = chiedi(action="query", prop="imageinfo", titles="|".join(
            titoli[inizio:inizio + 50]), iiprop="url|size|sha1|mime|extmetadata")
        for pagina in dati.get("query", {}).get("pages", []):
            info = (pagina.get("imageinfo") or [{}])[0]
            meta = info.get("extmetadata") or {}
            fuori.append({
                "titolo": pagina["title"], "indirizzo": info.get("url"),
                "larghezza": info.get("width") or 0, "altezza": info.get("height") or 0,
                "sha1": info.get("sha1"), "tipo": info.get("mime"),
                "licenza": (meta.get("LicenseShortName") or {}).get("value", ""),
                "autore": (meta.get("Artist") or {}).get("value", ""),
                "pagina": info.get("descriptionurl")})
    return fuori


def adatta(voce: dict) -> bool:
    corto = min(voce["larghezza"], voce["altezza"])
    lungo = max(voce["larghezza"], voce["altezza"])
    licenza = voce["licenza"].lower()
    return (voce["tipo"] == "image/jpeg" and corto >= LATO_CORTO and lungo >= LATO_LUNGO
            and any(licenza.startswith(lic) for lic in LICENZE) and "nc" not in licenza
            and "nd" not in licenza)


def scarica(indirizzo: str) -> bytes:
    for prova in range(4):
        try:
            richiesta = urllib.request.Request(indirizzo, headers={"User-Agent": CHI})
            with urllib.request.urlopen(richiesta, timeout=180) as risposta:
                return risposta.read()
        except Exception as guasto:
            print("FILE riprovo", prova, type(guasto).__name__, flush=True)
            time.sleep(10 * (prova + 1))
    raise RuntimeError("file non scaricato")


def nitidezza(pixel) -> float:
    import cv2

    grigio = cv2.cvtColor(pixel, cv2.COLOR_RGB2GRAY)
    grigio = cv2.resize(grigio, (512, 512), interpolation=cv2.INTER_AREA)
    return float(cv2.Laplacian(grigio, cv2.CV_64F).var())


def rumore(pixel) -> float:
    import cv2
    import numpy

    grigio = cv2.cvtColor(pixel, cv2.COLOR_RGB2GRAY).astype(numpy.float32)
    alto = grigio - cv2.GaussianBlur(grigio, (0, 0), 1.0)
    return float(numpy.median(numpy.abs(alto)) * 1.4826)


def guarda(voce: dict, dati: bytes, rilevatore) -> dict | None:
    import numpy
    from PIL import Image, ImageOps

    if hashlib.sha1(dati).hexdigest() != voce["sha1"]:
        print("SCARTO impronta diversa", voce["titolo"], flush=True)
        return None
    with Image.open(io.BytesIO(dati)) as aperta:
        intera = ImageOps.exif_transpose(aperta).convert("RGB")
    larga, alta = intera.size
    facce = [f for f in rilevatore.guarda(intera) if f.sicurezza >= VOLTO_SICURO]
    grandi = [f for f in facce if f.riquadro[2] * larga >= VOLTO_MINIMO]
    if len(grandi) != 1:
        print("SCARTO volti grandi", len(grandi), voce["titolo"], flush=True)
        return None
    volto = grandi[0]
    x, y, lv, a = volto.riquadro
    ritaglio = numpy.asarray(intera.crop((int(x * larga), int(y * alta),
                                          int((x + lv) * larga), int((y + a) * alta))))
    hsv = numpy.asarray(Image.fromarray(ritaglio).convert("HSV"), dtype=numpy.float32)
    colore = float(hsv[..., 1].mean())
    if colore < COLORE_MINIMO:
        print("SCARTO bianco e nero", voce["titolo"], flush=True)
        return None
    return {**voce, "sha256": hashlib.sha256(dati).hexdigest(), "byte": len(dati),
            "volto": [round(v, 5) for v in volto.riquadro],
            "volto_px": int(lv * larga), "sicurezza": round(volto.sicurezza, 3),
            "nitidezza_volto": round(nitidezza(ritaglio), 1),
            "rumore_volto": round(rumore(ritaglio), 2), "colore": round(colore, 1)}


def main() -> int:
    import onnxruntime

    import collaudo_volti_difficili as base
    from officina.volti import insight

    argomenti = argparse.ArgumentParser()
    argomenti.add_argument("--uscita", required=True)
    argomenti.add_argument("--cartella", required=True)
    scelti = argomenti.parse_args()
    casa = Path(scelti.cartella)
    casa.mkdir(parents=True, exist_ok=True)
    pesi = base.prendi_il_rilevatore()
    if pesi is None:
        return 1
    rilevatore = insight.Rilevatore(casa)
    rilevatore._trova = onnxruntime.InferenceSession(
        str(pesi), providers=["CPUExecutionProvider"])
    rilevatore._riconosce = object()
    rilevatore._impronta_di = lambda dritta, numpy: None

    titoli = tutti_i_file()
    print("FILE_TROVATI", len(titoli), flush=True)
    voci = [v for v in informazioni(titoli) if adatta(v)]
    print("FILE_ADATTI", len(voci), flush=True)
    voci.sort(key=lambda v: hashlib.sha256(v["titolo"].encode()).hexdigest())
    buoni = []
    for numero, voce in enumerate(voci[:MASSIMO_DA_GUARDARE]):
        try:
            esito = guarda(voce, scarica(voce["indirizzo"]), rilevatore)
        except Exception as guasto:
            print("SCARTO guasto", type(guasto).__name__, voce["titolo"], flush=True)
            continue
        if esito:
            buoni.append(esito)
        if numero % 25 == 24:
            print(f"guardati {numero + 1}, buoni {len(buoni)}", flush=True)
    soglia_rumore = sorted(b["rumore_volto"] for b in buoni)[int(len(buoni) * 0.8)] \
        if buoni else 0
    puliti = [b for b in buoni if b["rumore_volto"] <= soglia_rumore]
    puliti.sort(key=lambda b: -b["nitidezza_volto"])
    scelti_ritratti, per_autore = [], {}
    for voce in puliti:
        chi = voce["autore"]
        if per_autore.get(chi, 0) >= PER_AUTORE:
            continue
        per_autore[chi] = per_autore.get(chi, 0) + 1
        scelti_ritratti.append(voce)
        if len(scelti_ritratti) >= QUANTI + RISERVE:
            break
    print("SCELTI", len(scelti_ritratti), "su buoni", len(buoni), flush=True)
    for voce in scelti_ritratti:
        print("RITRATTO", voce["titolo"], voce["larghezza"], voce["altezza"],
              voce["volto_px"], voce["nitidezza_volto"], voce["rumore_volto"],
              voce["licenza"], flush=True)
    Path(scelti.uscita).write_text(json.dumps(
        {"scelti": scelti_ritratti, "buoni": len(buoni), "adatti": len(voci),
         "trovati": len(titoli)}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
