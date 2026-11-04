from __future__ import annotations

import argparse
import io
import json
import math
import os
import sys
import time
import urllib.request
from pathlib import Path

FOTO = "http://images.cocodataset.org/val2017/000000000139.jpg"
PASSO = 6
MINIMO_DB = 30.0


def _psnr(uno, altro) -> float:
    import numpy as np

    errore = np.mean((uno.astype(np.float64) - altro.astype(np.float64)) ** 2)
    return 99.0 if errore == 0 else round(10 * math.log10(255.0 ** 2 / errore), 2)


def _a_mano(entrata, flusso):
    import numpy as np

    numero, canali, alto, largo = entrata.shape
    uscita = np.zeros_like(entrata)
    for n in range(numero):
        for y in range(alto):
            for x in range(largo):
                fx = x + flusso[n, 0, y, x]
                fy = y + flusso[n, 1, y, x]
                if not (np.isfinite(fx) and np.isfinite(fy)):
                    continue
                x0, y0 = math.floor(fx), math.floor(fy)
                for dx, dy in ((0, 0), (1, 0), (0, 1), (1, 1)):
                    xi, yi = x0 + dx, y0 + dy
                    if 0 <= xi < largo and 0 <= yi < alto:
                        peso = (1 - abs(fx - xi)) * (1 - abs(fy - yi))
                        uscita[n, :, yi, xi] += entrata[n, :, y, x] * peso
    return uscita


def spinta() -> dict:
    import numpy as np
    import torch

    from officina.miglioria import gimm_spinta

    caso = np.random.default_rng(7)
    entrata = caso.normal(size=(2, 3, 9, 11)).astype(np.float32)
    flusso = (caso.normal(size=(2, 2, 9, 11)) * 3).astype(np.float32)
    flusso[0, 0, 2, 3] = np.inf
    flusso[1, 1, 4, 5] = np.nan
    atteso = _a_mano(entrata, flusso)
    fatto = gimm_spinta.spingi(torch.from_numpy(entrata), torch.from_numpy(flusso)).numpy()
    scarto = float(np.abs(fatto - atteso).max())
    metrica = np.abs(caso.normal(size=(2, 1, 9, 11))).astype(np.float32)
    normale = gimm_spinta.softsplat(torch.from_numpy(entrata), torch.from_numpy(flusso),
                                    torch.from_numpy(metrica), "linear-zeroeps").numpy()
    somma = _a_mano(np.concatenate([entrata * metrica, metrica], 1), flusso)
    peso = somma[:, -1:]
    peso[peso == 0] = 1
    scarto_lineare = float(np.abs(normale - somma[:, :-1] / peso).max())
    if scarto > 1e-4 or scarto_lineare > 1e-4:
        raise AssertionError(f"la spinta non torna: {scarto} {scarto_lineare}")
    return {"scarto": scarto, "scarto_lineare": scarto_lineare}


def _foto():
    import numpy as np
    from PIL import Image

    with urllib.request.urlopen(FOTO, timeout=60) as risposta:
        return np.asarray(Image.open(io.BytesIO(risposta.read())).convert("RGB"))


def _ritagli(foto, largo: int, alto: int, volte: int):
    quadri = []
    for numero in range(volte + 1):
        x = 20 + numero * PASSO
        quadri.append(foto[30:30 + alto, x:x + largo].copy())
    return quadri


def giro(casa: Path, volte: int, largo: int, alto: int, ridotto: float | None) -> dict:
    import numpy as np

    from officina.miglioria import gimmvfi

    motore = gimmvfi.GimmVFI(cartella_modelli=str(casa))
    motore.ridotto = ridotto
    foto = _foto()
    quadri = _ritagli(foto, largo, alto, volte)
    partito = time.monotonic()
    fatti = motore.coppia(quadri[0], quadri[-1], volte)
    secondi = round(time.monotonic() - partito, 1)
    misure, miscele = [], []
    for numero, fatto in enumerate(fatti, 1):
        t = numero / volte
        miscela = ((1 - t) * quadri[0] + t * quadri[-1]).round().astype(np.uint8)
        misure.append(_psnr(fatto, quadri[numero]))
        miscele.append(_psnr(miscela, quadri[numero]))
    esito = {"volte": volte, "misura": [largo, alto], "ridotto": motore.ridotto,
             "secondi": secondi, "psnr": misure, "psnr_miscela": miscele,
             "forma": list(fatti[0].shape), "tipo": str(fatti[0].dtype)}
    if len(fatti) != volte - 1 or fatti[0].shape != quadri[0].shape:
        raise AssertionError("escono quadri sbagliati: " + json.dumps(esito))
    if min(misure) < MINIMO_DB or any(m <= c for m, c in zip(misure, miscele, strict=True)):
        raise AssertionError("i quadri inventati sono brutti: " + json.dumps(esito))
    motore.spegni()
    return esito


def principale() -> int:
    scelte = argparse.ArgumentParser()
    scelte.add_argument("--uscita", type=Path, required=True)
    scelte.add_argument("--casa", type=Path, required=True)
    argomenti = scelte.parse_args()
    from officina.miglioria import scaricamento

    esito: dict = {"spinta": spinta()}
    partito = time.monotonic()
    scaricamento.scarica(argomenti.casa, nome="gimmvfi",
                         al_passo=lambda riga: print(riga, file=sys.stderr),
                         chiave=os.environ.get("HF_TOKEN") or None)
    esito["scaricato_in_secondi"] = round(time.monotonic() - partito)
    esito["giri"] = [giro(argomenti.casa, 2, 448, 256, None),
                     giro(argomenti.casa, 4, 448, 256, None),
                     giro(argomenti.casa, 4, 512, 288, 0.5)]
    testo = json.dumps(esito, indent=1)
    argomenti.uscita.write_text(testo, encoding="utf-8")
    print(testo)
    return 0


if __name__ == "__main__":
    sys.exit(principale())
