from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

QUI = Path(__file__).resolve().parent
sys.path.insert(0, str(QUI.parent))
sys.path.insert(0, str(QUI))


def main() -> int:
    import collaudo_corpi as corpi
    import collaudo_volti_difficili as volti
    from PIL import Image

    from officina.descrittori import torcia

    argomenti = argparse.ArgumentParser()
    argomenti.add_argument("--cartella", type=Path, required=True)
    argomenti.add_argument("--quante", type=int, default=40)
    argomenti.add_argument("--come", default="pulita",
                           choices=("pulita", *volti.ROVINE))
    scelti = argomenti.parse_args()
    torcia.con_la_rete_accesa()
    chiave = os.environ.get("HF_TOKEN") or None
    if not chiave:
        raise SystemExit("manca HF_TOKEN nei segreti del deposito")
    casa = scelti.cartella / "modelli" / "corpi"
    casa.mkdir(parents=True, exist_ok=True)
    esito: dict = {"sam3": corpi._sam3(casa, chiave),
                   "rtmw": corpi._rtmw(casa, scelti.cartella, chiave)}
    scarica = corpi._scarica
    contatore = [0]

    def rovinata(url: str, dove: Path) -> Path:
        presa = scarica(url, dove)
        if scelti.come == "pulita" or not url.startswith(corpi.FOTO):
            return presa
        contatore[0] += 1
        brutta = presa.with_name(f"{presa.stem}-{scelti.come}.png")
        with Image.open(presa) as aperta:
            volti.rovina(aperta.convert("RGB"), scelti.come, contatore[0]).save(brutta)
        return brutta

    corpi._scarica = rovinata
    esito["prova"] = corpi.prova(casa, scelti.cartella, scelti.quante)
    breve = corpi.riassunto(esito)
    print("COME", scelti.come, flush=True)
    print("RIASSUNTO", json.dumps(breve, ensure_ascii=False), flush=True)
    print("PERSONE", json.dumps(esito["prova"]["persone"], ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
