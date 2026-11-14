from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
import time
import urllib.request
from pathlib import Path

RADICE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RADICE))

from officina.miglioria import lucidflux_strisce  # noqa: E402

TERZI = RADICE / "officina" / "miglioria" / "terzi" / "lucidflux.json"
FILE = "src/flux/modules/autoencoder.py"
CASI = ((96, 64, None), (96, 64, 8), (97, 63, 13), (128, 72, 24), (160, 90, None),
        (90, 160, 16))
TOLLERANZA = 1e-5


def prendi_il_codice(cartella: Path):
    dati = json.loads(TERZI.read_text(encoding="utf-8"))
    indirizzo = (f"https://raw.githubusercontent.com/{dati['deposito']}/"
                 f"{dati['commit']}/{FILE}")
    with urllib.request.urlopen(indirizzo, timeout=60) as risposta:
        contenuto = risposta.read()
    if hashlib.sha256(contenuto).hexdigest() != dati["file"][FILE]:
        raise SystemExit("impronta del codice diversa")
    cartella.mkdir(parents=True, exist_ok=True)
    dove = cartella / "autoencoder_fissato.py"
    dove.write_bytes(contenuto)
    spec = importlib.util.spec_from_file_location("autoencoder_fissato", dove)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def costruisci(modulo, seme: int):
    import torch

    torch.manual_seed(seme)
    params = modulo.AutoEncoderParams(
        resolution=256, in_channels=3, ch=128, out_ch=3, ch_mult=[1, 2, 4, 4],
        num_res_blocks=2, z_channels=16, scale_factor=0.3611, shift_factor=0.1159)
    ae = modulo.AutoEncoder(params).eval()
    with torch.no_grad():
        for nome, parte in ae.decoder.named_parameters():
            if "norm" in nome and nome.endswith("weight"):
                parte.copy_(1.0 + 0.2 * torch.randn_like(parte))
            elif "norm" in nome and nome.endswith("bias"):
                parte.copy_(0.2 * torch.randn_like(parte))
    return ae


def main() -> int:
    import torch

    argomenti = argparse.ArgumentParser()
    argomenti.add_argument("--cartella", required=True)
    argomenti.add_argument("--uscita", required=True)
    scelti = argomenti.parse_args()
    torch.set_num_threads(4)
    modulo = prendi_il_codice(Path(scelti.cartella))
    esiti = []
    peggiore = 0.0
    for numero, (larga, alta, righe) in enumerate(CASI):
        ae = costruisci(modulo, 1000 + numero)
        torch.manual_seed(numero)
        z = torch.randn(1, 16, alta, larga) * 1.5
        with torch.no_grad():
            partito = time.perf_counter()
            vero = ae.decode(z)
            intero = time.perf_counter() - partito
            partito = time.perf_counter()
            mio = lucidflux_strisce.decodifica(ae, z, righe)
            strisce = time.perf_counter() - partito
        differenza = float((vero - mio).abs().max())
        scala = float(vero.abs().max())
        relativa = differenza / max(scala, 1e-12)
        peggiore = max(peggiore, relativa)
        esito = {"latente": [larga, alta], "foto": list(vero.shape[-2:][::-1]),
                 "righe": righe or lucidflux_strisce.righe_per(larga * 8),
                 "differenza_massima": differenza, "scala": scala, "relativa": relativa,
                 "pixel_a_8_bit_diversi": int(((vero.clamp(-1, 1) + 1) * 127.5).round()
                                              .ne(((mio.clamp(-1, 1) + 1) * 127.5).round())
                                              .sum()),
                 "secondi_intero": round(intero, 2), "secondi_strisce": round(strisce, 2),
                 "forma_uguale": list(vero.shape) == list(mio.shape)}
        print(json.dumps(esito), flush=True)
        esiti.append(esito)
    buono = peggiore <= TOLLERANZA and all(e["forma_uguale"] for e in esiti)
    riassunto = {"casi": esiti, "peggiore_relativa": peggiore, "tolleranza": TOLLERANZA,
                 "buono": buono}
    Path(scelti.uscita).write_text(json.dumps(riassunto, indent=1) + "\n", encoding="utf-8")
    print("BUONO" if buono else "DIVERSO", peggiore, flush=True)
    return 0 if buono else 1


if __name__ == "__main__":
    raise SystemExit(main())
