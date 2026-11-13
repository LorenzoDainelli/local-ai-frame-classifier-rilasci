from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
import time
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

DEPOSITO = "CUHK-CSE/wider_face"
REVISIONE = "db171f1b7fedf4d3453e81297ff02f9915356d19"
FOTO_ZIP = "data/WIDER_val.zip"
FOTO_SHA256 = "f9efbd09f28c5d2d884be8c0eaef3967158c866a593fc36ab0413e4b2a58a17a"
RILEVATORE = "det_10g.onnx"
OGNI = 3
OGNI_ROVINATE = 12
STESSO_VOLTO = 0.4
VICINO = 0.2
MINUSCOLO = 0.015
PICCOLO = 0.03
GRANDE = 0.10
PROVE = (
    ("oggi 640", 640, 0.03),
    ("960", 960, 0.03),
    ("1280", 1280, 0.03),
    ("1280 piccoli", 1280, 0.015),
    ("1920 piccoli", 1920, 0.015),
)
PROVE_ROVINATE = ("oggi 640", "1280 piccoli")
ROVINE = ("buio", "rumore", "compresso", "sfocato", "mosso")
GRUPPI = ("facili", "medi", "piccoli", "sfocati", "coperti", "di lato", "luce",
          "difficili", "molto difficili", "tutti")


def sha(percorso: Path) -> str:
    h = hashlib.sha256()
    with percorso.open("rb") as f:
        while pezzo := f.read(1 << 20):
            h.update(pezzo)
    return h.hexdigest()


def leggi_le_etichette(testo: str) -> dict[str, list[dict]]:
    righe = testo.splitlines()
    foto: dict[str, list[dict]] = {}
    indice = 0
    while indice < len(righe):
        nome = righe[indice].strip()
        quanti = int(righe[indice + 1])
        volti = []
        for riga in righe[indice + 2:indice + 2 + max(quanti, 1)]:
            n = [int(x) for x in riga.split()]
            if len(n) < 10 or not quanti:
                continue
            volti.append({"x": n[0], "y": n[1], "l": n[2], "a": n[3], "sfocato": n[4],
                          "espressione": n[5], "luce": n[6], "non_valido": n[7],
                          "coperto": n[8], "di_lato": n[9]})
        foto[nome] = volti
        indice += 2 + max(quanti, 1)
    return foto


def gruppi_di(volto: dict, larga: int, alta: int) -> set[str]:
    quanto = min(volto["l"] / larga, volto["a"] / alta)
    if volto["non_valido"] or volto["l"] <= 0 or volto["a"] <= 0 or quanto < MINUSCOLO:
        return set()
    pesi = [volto["sfocato"] == 2, volto["coperto"] == 2, volto["di_lato"] == 1,
            volto["luce"] == 1]
    lievi = volto["sfocato"] or volto["coperto"]
    gruppi = {"tutti"}
    if quanto < PICCOLO:
        gruppi.add("piccoli")
    elif quanto < GRANDE:
        gruppi.add("medi")
    if pesi[0]:
        gruppi.add("sfocati")
    if pesi[1]:
        gruppi.add("coperti")
    if pesi[2]:
        gruppi.add("di lato")
    if pesi[3]:
        gruppi.add("luce")
    if quanto >= GRANDE and not any(pesi) and not lievi:
        gruppi.add("facili")
    if any(pesi) or quanto < PICCOLO:
        gruppi.add("difficili")
    if sum(pesi) >= 2 or (quanto < PICCOLO and any(pesi)):
        gruppi.add("molto difficili")
    return gruppi


def sovrapposti(uno, altro) -> float:
    sinistra = max(uno[0], altro[0])
    sopra = max(uno[1], altro[1])
    destra = min(uno[0] + uno[2], altro[0] + altro[2])
    sotto = min(uno[1] + uno[3], altro[1] + altro[3])
    dentro = max(0.0, destra - sinistra) * max(0.0, sotto - sopra)
    insieme = uno[2] * uno[3] + altro[2] * altro[3] - dentro
    return dentro / insieme if insieme > 0 else 0.0


def conta(veri: list[tuple[tuple, set]], trovati: list[tuple[tuple, float]],
          conti: dict) -> None:
    presi: set[int] = set()
    for riquadro, _sicurezza in sorted(trovati, key=lambda v: -v[1]):
        migliore, quanto = -1, 0.0
        for numero, (vero, _gruppi) in enumerate(veri):
            if numero in presi:
                continue
            ora = sovrapposti(riquadro, vero)
            if ora > quanto:
                migliore, quanto = numero, ora
        if quanto >= STESSO_VOLTO:
            presi.add(migliore)
        elif not any(sovrapposti(riquadro, vero) >= VICINO for vero, _g in veri):
            conti["falsi"] += 1
    for numero, (_vero, gruppi) in enumerate(veri):
        for gruppo in gruppi:
            conti[gruppo][1] += 1
            if numero in presi:
                conti[gruppo][0] += 1
    conti["foto"] += 1


def rovina(immagine, come: str, seme: int):
    import numpy
    from PIL import Image, ImageFilter

    if come == "buio":
        pixel = numpy.asarray(immagine, dtype=numpy.float32) * 0.12
        return Image.fromarray(pixel.clip(0, 255).astype(numpy.uint8))
    if come == "rumore":
        caso = numpy.random.default_rng(seme)
        pixel = numpy.asarray(immagine, dtype=numpy.float32)
        pixel = pixel + caso.normal(0.0, 40.0, pixel.shape)
        return Image.fromarray(pixel.clip(0, 255).astype(numpy.uint8))
    if come == "compresso":
        dentro = io.BytesIO()
        immagine.save(dentro, "JPEG", quality=6)
        dentro.seek(0)
        return Image.open(dentro).convert("RGB")
    if come == "sfocato":
        return immagine.filter(ImageFilter.GaussianBlur(max(immagine.size) / 250))
    lungo = max(5, (max(immagine.size) // 60) | 1)
    lungo = min(lungo, 25)
    if lungo > 5:
        import cv2

        nucleo = numpy.zeros((lungo, lungo), dtype=numpy.float32)
        nucleo[lungo // 2, :] = 1.0 / lungo
        return Image.fromarray(cv2.filter2D(numpy.asarray(immagine), -1, nucleo))
    nucleo = [0.0] * 25
    nucleo[10:15] = [0.2] * 5
    return immagine.filter(ImageFilter.Kernel((5, 5), nucleo, scale=1.0))


def nuovi_conti() -> dict:
    conti = {gruppo: [0, 0] for gruppo in GRUPPI}
    conti["falsi"] = 0
    conti["foto"] = 0
    conti["secondi"] = 0.0
    return conti


def stampa(titolo: str, tabella: dict[str, dict]) -> None:
    print(f"\n== {titolo} ==", flush=True)
    for nome, conti in tabella.items():
        if not conti["foto"]:
            continue
        pezzi = []
        for gruppo in GRUPPI:
            presi, su = conti[gruppo]
            if su:
                pezzi.append(f"{gruppo} {presi}/{su} {100 * presi / su:.1f}%")
        falsi = 100 * conti["falsi"] / conti["foto"]
        tempo = conti["secondi"] / conti["foto"]
        print(f"{nome:14s} | " + " | ".join(pezzi)
              + f" | falsi ogni 100 foto {falsi:.1f} | {tempo:.2f} s a foto", flush=True)


def main() -> int:
    import onnxruntime
    from huggingface_hub import HfApi, hf_hub_download
    from PIL import Image

    from officina.immagini import lettura
    from officina.volti import insight
    from officina.volti.rilevatore import FILE_RILEVATORE
    from officina.volti.scaricamento import DA_DOVE, SHA256_RILEVATORE, revisione_di

    argomenti = argparse.ArgumentParser()
    argomenti.add_argument("--cartella", required=True)
    argomenti.add_argument("--uscita", required=True)
    argomenti.add_argument("--quante", type=int, default=0)
    scelti = argomenti.parse_args()
    casa = Path(scelti.cartella)
    casa.mkdir(parents=True, exist_ok=True)

    nomi = [f.rfilename for f in HfApi().repo_info(
        DEPOSITO, repo_type="dataset", revision=REVISIONE).siblings]
    parti = [n for n in nomi if n.endswith("wider_face_split.zip")][0]
    etichette = Path(hf_hub_download(DEPOSITO, parti, repo_type="dataset",
                                     revision=REVISIONE))
    print("ETICHETTE", parti, sha(etichette), flush=True)
    archivio = Path(hf_hub_download(DEPOSITO, FOTO_ZIP, repo_type="dataset",
                                    revision=REVISIONE))
    if sha(archivio) != FOTO_SHA256:
        print("le foto di WIDER FACE non sono quelle previste", flush=True)
        return 1
    pesi = None
    fonte = DA_DOVE[FILE_RILEVATORE]
    for deposito in (fonte.repo, *fonte.riserve):
        for genere in ("model", "dataset"):
            try:
                dentro = HfApi().list_repo_files(
                    deposito, repo_type=genere, revision=revisione_di(deposito) or None)
                adatti = [n for n in dentro if n.endswith("buffalo_l/" + RILEVATORE)]
                adatti = adatti or [n for n in dentro if n.endswith(RILEVATORE)]
                pesi = Path(hf_hub_download(deposito, adatti[0], repo_type=genere,
                                            revision=revisione_di(deposito) or None))
            except Exception as guasto:
                print("FONTE", deposito, genere, "NO", type(guasto).__name__, flush=True)
                continue
            print("FONTE", deposito, genere, adatti[0], sha(pesi), flush=True)
            if sha(pesi) == SHA256_RILEVATORE:
                break
            pesi = None
        if pesi is not None:
            break
    if pesi is None:
        print("il rilevatore non è quello del programma", flush=True)
        return 1

    with zipfile.ZipFile(etichette) as z:
        dentro = [n for n in z.namelist() if n.endswith("wider_face_val_bbx_gt.txt")]
        foto = leggi_le_etichette(z.read(dentro[0]).decode())
    print("FOTO_ETICHETTATE", len(foto), flush=True)

    rilevatore = insight.Rilevatore(casa)
    rilevatore._trova = onnxruntime.InferenceSession(
        str(pesi), providers=["CPUExecutionProvider"])
    rilevatore._riconosce = object()
    rilevatore._impronta_di = lambda dritta, numpy: None

    pulite = {nome: nuovi_conti() for nome, _lato, _minimo in PROVE}
    rovinate = {f"{rovina_} · {nome}": nuovi_conti()
                for rovina_ in ROVINE for nome in PROVE_ROVINATE}
    lavoro = casa / "foto.jpg"
    scelte = sorted(foto)[::OGNI]
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
            veri = []
            for volto in foto[nome]:
                if volto["l"] <= 0 or volto["a"] <= 0:
                    continue
                veri.append(((volto["x"] / larga, volto["y"] / alta, volto["l"] / larga,
                              volto["a"] / alta), gruppi_di(volto, larga, alta)))
            for prova, lato, minimo in PROVE:
                insight.LATO_DEL_QUADRATO = lato
                insight.LATO_MINIMO = minimo
                immagine = lettura.copia_di_lavoro(lavoro, max(1280, lato))
                da = time.monotonic()
                facce = rilevatore.guarda(immagine)
                pulite[prova]["secondi"] += time.monotonic() - da
                conta(veri, [(f.riquadro, f.sicurezza) for f in facce], pulite[prova])
                if numero % (OGNI_ROVINATE // OGNI) or prova not in PROVE_ROVINATE:
                    continue
                for come in ROVINE:
                    brutta = rovina(immagine.convert("RGB"), come, numero)
                    da = time.monotonic()
                    facce = rilevatore.guarda(brutta)
                    conti = rovinate[f"{come} · {prova}"]
                    conti["secondi"] += time.monotonic() - da
                    conta(veri, [(f.riquadro, f.sicurezza) for f in facce], conti)
            if numero % 50 == 49:
                print(f"fatte {numero + 1} di {len(scelte)} in "
                      f"{(time.monotonic() - inizio) / 60:.0f} min", flush=True)
                stampa("foto come sono, fin qui", pulite)

    stampa("FOTO COME SONO", pulite)
    stampa("FOTO ROVINATE APPOSTA", rovinate)
    Path(scelti.uscita).write_text(json.dumps(
        {"pulite": pulite, "rovinate": rovinate, "foto": len(scelte)},
        ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
