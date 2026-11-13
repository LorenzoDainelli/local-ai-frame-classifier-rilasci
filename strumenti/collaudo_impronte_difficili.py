from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from pathlib import Path

QUI = Path(__file__).resolve().parent
sys.path.insert(0, str(QUI.parent))
sys.path.insert(0, str(QUI))

MODELLO = "dinov3"
VARIANTI = ("pulita", "buio", "rumore", "compresso", "sfocato", "mosso", "piccola",
            "ritagliata", "girata", "specchiata")
DIFFICILI = ("buio", "rumore", "compresso", "sfocato", "mosso", "piccola", "ritagliata")


def variante(foto, come: str, seme: int):
    import collaudo_volti_difficili as volti
    from PIL import Image, ImageOps

    if come == "pulita":
        return foto
    if come == "piccola":
        return foto.resize((max(1, foto.width // 6), max(1, foto.height // 6)),
                           Image.LANCZOS)
    if come == "ritagliata":
        larga, alta = foto.size
        return foto.crop((int(larga * 0.25), int(alta * 0.25), int(larga * 0.85),
                          int(alta * 0.85)))
    if come == "girata":
        return foto.rotate(90, expand=True)
    if come == "specchiata":
        return ImageOps.mirror(foto)
    return volti.rovina(foto, come, seme)


def voti(archivio, scene, domande, vettori) -> dict:
    import numpy

    medie, primi = [], []
    for indice, vettore in zip(domande, vettori, strict=True):
        punti = archivio @ vettore
        punti[indice] = -numpy.inf
        ordine = numpy.argsort(-punti)[:-1]
        giusti = scene[ordine] == scene[indice]
        if not giusti.any():
            continue
        presi = numpy.cumsum(giusti)
        medie.append(float((presi[giusti] / (numpy.flatnonzero(giusti) + 1)).mean()))
        primi.append(bool(giusti[0]))
    return {"mAP": round(100 * statistics.fmean(medie), 1),
            "primo_giusto": round(100 * statistics.fmean(primi), 1),
            "domande": len(medie)}


def main() -> int:
    import gara_impronte as gara
    import numpy

    from officina import descrittori
    from officina.descrittori import preparazione, scaricamento, torcia
    from officina.immagini import lettura

    argomenti = argparse.ArgumentParser()
    argomenti.add_argument("--cartella", type=Path, required=True)
    argomenti.add_argument("--domande", type=int, default=0)
    scelti = argomenti.parse_args()
    torcia.con_la_rete_accesa()
    casa = scelti.cartella / "modelli"
    casa.mkdir(parents=True, exist_ok=True)
    carta = descrittori.scheda(MODELLO)
    scaricamento.scarica(carta, casa, chiave=os.environ.get("HF_TOKEN") or None)
    problemi: dict = {}
    foto = gara.foto_simili(scelti.cartella, problemi)
    print("FOTO", len(foto), "PROBLEMI", len(problemi), flush=True)
    scene = numpy.array([voce["scena"] for voce in foto])
    domande = [numero for numero, voce in enumerate(foto) if voce["domanda"]]
    if scelti.domande:
        domande = domande[:scelti.domande]

    def pronta(immagine):
        return preparazione.tre_inquadrature(immagine, carta.lato)[0].immagine

    partito = time.monotonic()
    with descrittori.apri(MODELLO, casa) as modello:
        print("GIRA_SU", modello.dove_gira(), "LATO", carta.lato, flush=True)
        archivio = []
        for numero, voce in enumerate(foto):
            immagine = lettura.copia_di_lavoro(scelti.cartella / voce["file"],
                                               carta.lato * 4)
            archivio.append(modello.descrivi_una(pronta(immagine)))
            if numero % 100 == 99:
                print("archivio", numero + 1, "di", len(foto),
                      round((time.monotonic() - partito) / 60), "min", flush=True)
        archivio = numpy.asarray(archivio, dtype=numpy.float32)
        archivio /= numpy.linalg.norm(archivio, axis=1, keepdims=True).clip(1e-8)
        esiti = {}
        for come in VARIANTI:
            vettori = []
            for numero in domande:
                immagine = lettura.copia_di_lavoro(
                    scelti.cartella / foto[numero]["file"], carta.lato * 4)
                brutta = variante(immagine.convert("RGB"), come, numero)
                vettori.append(modello.descrivi_una(pronta(brutta)))
            vettori = numpy.asarray(vettori, dtype=numpy.float32)
            vettori /= numpy.linalg.norm(vettori, axis=1, keepdims=True).clip(1e-8)
            esiti[come] = voti(archivio, scene, domande, vettori)
            uguale = float(numpy.mean(numpy.sum(vettori * archivio[domande], axis=1)))
            esiti[come]["somiglia_alla_pulita"] = round(uguale, 3)
            print("VOTO", come, json.dumps(esiti[come]),
                  round((time.monotonic() - partito) / 60), "min", flush=True)
    difficili = [esiti[come]["mAP"] for come in DIFFICILI]
    print("SOLO_DIFFICILI mAP medio", round(statistics.fmean(difficili), 1),
          "peggiore", min(difficili), flush=True)
    print("ESITI", json.dumps(esiti, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
