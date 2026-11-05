from __future__ import annotations

import argparse
import collections
import hashlib
import json
import os
import sys
from pathlib import Path

REPO = "facebook/sam3.1"
VOLUTI = ("sam3.1_multiplex.pt", "config.json")


def impronta(file: Path) -> str:
    calcolo = hashlib.sha256()
    with file.open("rb") as dentro:
        for pezzo in iter(lambda: dentro.read(1 << 22), b""):
            calcolo.update(pezzo)
    return calcolo.hexdigest()


def chiavi_del_seguire(pesi: dict) -> dict:
    from officina.ritocco import sam31

    return {k: v[0] for k, v in sam31.pesi_del_seguire(pesi).items()}


class _FilmatoFinto:

    def __init__(self, quanti: int, larghezza: int, altezza: int) -> None:
        self.quanti, self.larghezza, self.altezza = quanti, larghezza, altezza

    def quadro(self, indice: int):
        import numpy
        from PIL import Image

        tela = numpy.full((self.altezza, self.larghezza, 3), 30, dtype=numpy.uint8)
        x = 8 + indice * 4
        tela[20:44, x:x + 24] = (220, 40, 40)
        return Image.fromarray(tela)


def _sul_processore(torch) -> None:
    vero = torch.zeros

    def zeri(*parti, **scelte):
        if str(scelte.get("device", "")).startswith("cuda"):
            scelte["device"] = "cpu"
        return vero(*parti, **scelte)

    torch.zeros = zeri
    torch.Tensor.cuda = lambda tensore, *parti, **scelte: tensore
    torch.Tensor.pin_memory = lambda tensore, *parti, **scelte: tensore


def confronta(codice: Path, letto: Path, uscita: Path) -> None:
    import numpy
    import torch

    from officina.ritocco import sam31, segui

    _sul_processore(torch)
    sam31.carica_il_pacchetto(codice)
    fuori: dict = {"moduli_fuori": sam31.moduli_fuori(codice)}
    torch.manual_seed(0)
    modello = sam31.costruisci().eval()
    voluti = {k: list(v.shape) for k, v in modello.state_dict().items()}
    dati = json.loads(letto.read_text(encoding="utf-8"))
    nel_file = chiavi_del_seguire(dati["pesi"])
    fuori.update({
        "voluti": len(voluti),
        "nel_file": len(nel_file),
        "mancano": sorted(set(voluti) - set(nel_file)),
        "avanzano": sorted(set(nel_file) - set(voluti)),
        "forme_diverse": sorted(k for k in set(voluti) & set(nel_file)
                                if voluti[k] != nel_file[k]),
        "tipi": sorted({t for _f, t in dati["pesi"].values()}),
        "numeri_seguire": sum(int(torch.Size(f).numel()) for f in nel_file.values()),
    })
    filmato = _FilmatoFinto(4, 96, 64)
    scelta = numpy.zeros((64, 96), dtype=bool)
    scelta[20:44, 12:36] = True
    seguitore = segui.Seguitore(Path("modelli") / "corpi" / "sam3")
    seguitore._modello, seguitore._dispositivo = modello, "cpu"
    visti: list = []
    fatti = seguitore.segui(filmato, {1: scelta}, [segui.Tratto(1, 0, 3)],
                            lambda indice, da, maschera, sicurezza: visti.append(
                                [indice, da, len(maschera), round(sicurezza, 4)]))
    fuori["seguiti"] = {"fatti": fatti, "ordine": [v[0] for v in visti], "visti": visti}
    fuori["va"] = (not fuori["moduli_fuori"] and not fuori["mancano"]
                   and not fuori["avanzano"] and not fuori["forme_diverse"]
                   and fuori["seguiti"]["ordine"] == [1, 2, 3, 0])
    uscita.write_text(json.dumps(fuori, indent=1), encoding="utf-8")
    print(json.dumps(fuori, indent=1))
    if not fuori["va"]:
        raise SystemExit(1)


def main() -> None:
    parti = argparse.ArgumentParser()
    parti.add_argument("--uscita", default="sam31.json")
    parti.add_argument("--cartella", default="sam31")
    parti.add_argument("--confronta", default=None)
    parti.add_argument("--letto", default="sam31.json")
    scelte = parti.parse_args()
    if scelte.confronta:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        confronta(Path(scelte.confronta), Path(scelte.letto), Path(scelte.uscita))
        return

    from huggingface_hub import HfApi, hf_hub_download

    chiave = os.environ.get("HF_TOKEN") or None
    api = HfApi()
    fuori: dict = {"repo": REPO}
    informazioni = api.model_info(REPO, token=chiave, files_metadata=True)
    fuori["revisione"] = informazioni.sha
    fuori["licenza"] = getattr(informazioni.card_data, "license", None)
    fuori["file"] = [{"nome": s.rfilename, "byte": s.size,
                      "sha256": (s.lfs or {}).get("sha256") if isinstance(s.lfs, dict)
                      else getattr(s.lfs, "sha256", None)}
                     for s in informazioni.siblings]
    fuori["storia"] = [c.commit_id for c in api.list_repo_commits(REPO, token=chiave)][:10]
    cartella = Path(scelte.cartella)
    for nome in VOLUTI:
        hf_hub_download(REPO, nome, revision=fuori["revisione"], local_dir=str(cartella),
                        token=chiave)
    fuori["config"] = json.loads((cartella / "config.json").read_text(encoding="utf-8"))
    pesi = cartella / "sam3.1_multiplex.pt"
    fuori["sha256_calcolato"] = impronta(pesi)
    fuori["byte"] = pesi.stat().st_size

    import torch

    stato = torch.load(str(pesi), map_location="cpu", weights_only=True)
    fuori["chiavi_in_cima"] = sorted(stato) if isinstance(stato, dict) else str(type(stato))
    if isinstance(stato, dict) and isinstance(stato.get("model"), dict):
        stato = stato["model"]
    gruppi = collections.Counter(".".join(k.split(".")[:2]) for k in stato)
    fuori["gruppi"] = dict(sorted(gruppi.items()))
    fuori["pesi"] = {k: [list(v.shape), str(v.dtype)] for k, v in stato.items()
                     if hasattr(v, "shape")}
    fuori["numeri"] = sum(int(v.numel()) for v in stato.values() if hasattr(v, "numel"))
    Path(scelte.uscita).write_text(json.dumps(fuori, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in fuori.items() if k != "pesi"}, indent=1))


if __name__ == "__main__":
    main()
