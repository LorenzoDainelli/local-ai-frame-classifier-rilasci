from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

QUI = Path(__file__).resolve().parent
sys.path.insert(0, str(QUI.parent))
sys.path.insert(0, str(QUI))

QUANTE = 24
VARIANTI = ("pulita", "buio", "rumore", "compresso", "sfocato", "mosso", "piccola")
DIFFICILI = VARIANTI[1:]


def variante(foto, come: str, seme: int):
    import collaudo_volti_difficili as volti

    if come == "pulita":
        return foto
    if come == "piccola":
        from PIL import Image

        return foto.resize((max(1, foto.width // 3), max(1, foto.height // 3)),
                           Image.LANCZOS)
    return volti.rovina(foto, come, seme)


def somma(esiti: dict) -> dict:
    import gara_lettura as gara

    conti = {nome: [0, 0, 0, 0] for nome in (*VARIANTI, "solo difficili")}
    for chiave, voce in esiti.items():
        come = chiave.rsplit("|", 1)[1]
        for nome in (come, "solo difficili") if come in DIFFICILI else (come,):
            conti[nome][0] += voce["prese"]
            conti[nome][1] += voce["giuste"]
            conti[nome][2] += voce["dette"]
            conti[nome][3] += 1
    return {nome: {"foto": c[3], "prese": c[0], "giuste": c[1], "dette": c[2],
                   **gara._f1(c[0], c[1], c[2])}
            for nome, c in conti.items() if c[3]}


def main() -> int:
    import gara_lettura as gara
    from PIL import Image

    argomenti = argparse.ArgumentParser()
    argomenti.add_argument("--cartella", required=True)
    argomenti.add_argument("--parte", type=int, default=0)
    argomenti.add_argument("--parti", type=int, default=1)
    argomenti.add_argument("--minuti", type=float, default=300)
    scelti = argomenti.parse_args()
    partito = time.monotonic()
    cartella = Path(scelti.cartella)
    cartella.mkdir(parents=True, exist_ok=True)
    problemi: dict = {}
    foto = gara.foto_con_le_scritte(cartella, QUANTE, problemi)
    print("FOTO", len(foto), "PROBLEMI", len(problemi), flush=True)
    lavori = [(numero, voce, come) for numero, voce in enumerate(foto)
              for come in VARIANTI]
    lavori = [lavoro for indice, lavoro in enumerate(lavori)
              if indice % scelti.parti == scelti.parte]
    print("DA_FARE", len(lavori), flush=True)
    motore = gara.Qwen(True)
    esiti: dict = {}
    for numero, voce, come in lavori:
        if (time.monotonic() - partito) / 60 > scelti.minuti:
            print("tempo finito", flush=True)
            break
        inizio = time.monotonic()
        try:
            with Image.open(cartella / voce["file"]) as aperta:
                brutta = variante(aperta.convert("RGB"), come, numero)
            sguardo = motore.lettore.leggi_la_risposta(motore.guarda(brutta))
            lette = [s.testo for s in sguardo.scritte]
        except Exception as guasto:
            print("GUASTO", voce["id"], come, repr(guasto)[:300], flush=True)
            continue
        punti = gara.punteggio_scritte(voce["parole"], lette, False)
        esiti[f"{voce['id']}|{come}"] = punti
        print("FATTA", voce["id"], come, punti, round(time.monotonic() - inizio), "s",
              flush=True)
        print("SOMMA", json.dumps(somma(esiti), ensure_ascii=False), flush=True)
    print("ESITI", json.dumps(esiti, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
