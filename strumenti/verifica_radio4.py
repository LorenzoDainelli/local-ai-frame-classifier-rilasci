from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from officina.descrittori import radio4, torcia

FRASI = [
    "a dog running on the beach", "Un cane che corre sulla spiaggia!",
    "two people, sitting at a table... at night", "una torta di compleanno con candele",
    "A RED CAR parked under_the_rain", "bambini che giocano nella neve",
    "", "x" * 400, "il gatto è sul divano, vicino alla finestra",
]
TESTO = radio4.REVISIONE_TESTO
LATI = ((512, 512), (384, 384), (768, 512), (432, 768))


def scrivi(uscita, *pezzi) -> None:
    riga = " ".join(str(p) for p in pezzi)
    print(riga, flush=True)
    uscita.write(riga + "\n")


def prendi(repo: str, nome: str, revisione: str, cartella: Path) -> Path:
    from huggingface_hub import hf_hub_download

    return Path(hf_hub_download(repo, nome, revision=revisione, local_dir=str(cartella)))


def prepara(uscita, casa: Path) -> None:
    casa.parent.mkdir(parents=True, exist_ok=True)
    liberati = radio4.porta_in_casa(casa, prendi, lambda riga: scrivi(uscita, "PASSO", riga))
    scrivi(uscita, "GREZZI_TOLTI", liberati)
    for nome in (radio4.VISIONE, radio4.TESTO):
        scrivi(uscita, "PESA", nome, (casa / nome).stat().st_size)
    scrivi(uscita, "CI_SONO", radio4.ci_sono(casa))


def foto_pubbliche() -> list[Path]:
    radice = Path.home() / ".cache" / "torch" / "hub"
    trovate = sorted(p for p in radice.rglob("*") if p.suffix.lower() in (".jpg", ".png"))
    return trovate[:12]


def coseno(a, b) -> float:
    import torch.nn.functional as F

    return float(F.cosine_similarity(a.double(), b.double(), dim=-1).min())


def ingressi(foto) -> list:
    from torch.nn import functional as F

    fuori = []
    for alta, larga in LATI:
        for inizio in range(0, len(foto), 4):
            x = radio4.tensore(foto[inizio:inizio + 4], max(alta, larga))
            if alta != larga:
                x = F.interpolate(x, (alta, larga), mode="bilinear", align_corners=False)
            fuori.append(x.contiguous())
    return fuori


def confronta(uscita, casa: Path) -> bool:
    import gc

    import torch
    from PIL import Image

    nvidia = torch.hub.load("NVlabs/RADIO:" + radio4.REVISIONE_CODICE, "radio_model",
                            version="c-radio_v4-h", progress=False, skip_validation=True,
                            trust_repo=True, adaptor_names=[radio4.ADATTATORE]).eval()
    foto = [Image.open(p).convert("RGB") for p in foto_pubbliche()]
    scrivi(uscita, "FOTO", len(foto))
    prove = ingressi(foto)
    with torch.inference_mode():
        loro = [nvidia(x)[radio4.ADATTATORE][0].clone() for x in prove]
        adattatore = nvidia.adaptors[radio4.ADATTATORE]
        suoi = adattatore.tokenizer(FRASI)
        loro_parole = adattatore.encode_text(suoi, normalize=True).clone()
    del nvidia, adattatore
    gc.collect()
    mia = radio4.costruisci_visione(casa)
    testo = radio4.costruisci_testo(casa)
    divisore = radio4.divisore(casa)
    bene = True
    with torch.inference_mode():
        for x, a in zip(prove, loro):
            b = mia(x)
            diff = float((a - b).abs().max())
            cos = coseno(a, b)
            scrivi(uscita, "IMMAGINI", list(x.shape), "diff", diff, "cos", cos)
            bene = bene and cos > 0.99999 and diff < 1e-3
        miei = radio4.gettoni(divisore, FRASI)
        uguali = (set(suoi.keys()) == set(miei.keys())
                  and all(torch.equal(suoi[k], miei[k]) for k in suoi.keys()))
        scrivi(uscita, "GETTONI_UGUALI", uguali, sorted(suoi.keys()), sorted(miei.keys()))
        bene = bene and uguali
        b = torch.nn.functional.normalize(testo(**miei).pooler_output, dim=-1)
        diff = float((loro_parole - b).abs().max())
        cos = coseno(loro_parole, b)
        scrivi(uscita, "PAROLE", "diff", diff, "cos", cos)
        bene = bene and cos > 0.99999
        immagini = torch.nn.functional.normalize(mia(radio4.tensore(foto)), dim=-1)
        scrivi(uscita, "PUNTEGGI", (immagini @ b.T)[:3, :4].tolist())
    scrivi(uscita, "ESITO", "UGUALI" if bene else "DIVERSI")
    return bene


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--uscita", required=True)
    parser.add_argument("--casa", default="lavoro-radio4/casa")
    a = parser.parse_args()
    import huggingface_hub.constants
    import transformers

    torcia.con_la_rete_accesa()
    print("RETE", huggingface_hub.constants.HF_HUB_OFFLINE, transformers.__version__, flush=True)
    with open(a.uscita, "w", encoding="utf-8") as uscita:
        prepara(uscita, Path(a.casa))
        return 0 if confronta(uscita, Path(a.casa)) else 1


if __name__ == "__main__":
    sys.exit(main())
