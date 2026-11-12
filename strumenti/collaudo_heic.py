from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import urllib.request
from pathlib import Path

from PIL import Image

from officina.miglioria import fedelta, heif_scatole, metadati

KODAK = "https://r0k.us/graphics/kodak/kodak/kodim{:02d}.png"
FOTO = (3, 5, 13, 15, 20, 23)
VARIANTI = ("normale", "buio", "rumore", "compresso", "girata", "senza_profondita")
DIFFICILI = ("buio", "rumore", "compresso", "girata")
LATO = 2
PROFONDE = ("disparita", "profondita")


def scarica(cartella: Path) -> list[dict]:
    cartella.mkdir(parents=True, exist_ok=True)
    prese = []
    for numero in FOTO:
        dove = cartella / f"kodim{numero:02d}.png"
        if not dove.exists():
            with urllib.request.urlopen(KODAK.format(numero), timeout=120) as risposta:
                dove.write_bytes(risposta.read())
        with Image.open(dove) as foto:
            foto.verify()
        prese.append({"file": dove, "sha256": hashlib.sha256(dove.read_bytes()).hexdigest()})
    return prese


def migliora(originale: Path, uscita: Path) -> dict:
    aperta = metadati.apri(originale)
    larga, alta = aperta.immagine.size
    grande = aperta.immagine.resize((larga * LATO, alta * LATO), Image.Resampling.LANCZOS)
    metadati.salva(grande, aperta.metadati, uscita, "HEIF", aperta.alfa)
    tipi = heif_scatole.rimetti(originale, uscita)
    return {"copiate": tipi, "perde": fedelta.cosa_perde(originale, uscita),
            "misura": [larga, alta]}


def giudica(riga: dict) -> list[str]:
    guasti = []
    occhi = riga["mac"]
    if "errore" in occhi:
        return [occhi["errore"]]
    prima, dopo = occhi["prima"], occhi["dopo"]
    if prima["larghezza"] * dopo["altezza"] != prima["altezza"] * dopo["larghezza"]:
        guasti.append("girata male")
    for nome in ("mappa_hdr", "mappa_iso", *PROFONDE):
        stato = occhi[nome]
        if stato["prima"] and not stato["dopo"]:
            guasti.append(f"{nome} persa")
        if stato["prima"] and stato["dopo"] and not stato.get("dati_uguali"):
            guasti.append(f"{nome} cambiata")
        if stato["prima"] and stato["dopo"] and not stato.get("meta_uguali"):
            guasti.append(f"{nome}: descrizione cambiata")
    if occhi["mappa_hdr"]["prima"]:
        if occhi["massimo_prima"] > 1.05 and occhi["massimo_dopo"] <= 1.05:
            guasti.append("macOS non la mostra più in HDR")
    return guasti


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cartella", type=Path, required=True)
    parser.add_argument("--programma", type=Path, required=True)
    parser.add_argument("--uscita", type=Path, required=True)
    argomenti = parser.parse_args()
    cartella = argomenti.cartella
    foto = scarica(cartella / "kodak")
    righe = []
    for presa in foto:
        for variante in VARIANTI:
            nome = f"{presa['file'].stem}-{variante}"
            originale = cartella / f"{nome}.heic"
            migliorata = cartella / f"{nome}-migliorata.heic"
            subprocess.run([str(argomenti.programma), "fai", str(presa["file"]),
                            str(originale), variante], check=True)
            riga = {"foto": presa["file"].name, "sha256": presa["sha256"],
                    "variante": variante, "difficile": variante in DIFFICILI}
            try:
                riga.update(migliora(originale, migliorata))
                occhi = subprocess.run([str(argomenti.programma), "guarda", str(originale),
                                        str(migliorata)], check=True, capture_output=True,
                                       text=True)
                riga["mac"] = json.loads(occhi.stdout)
                riga["guasti"] = giudica(riga)
            except Exception as errore:
                riga["guasti"] = [f"{type(errore).__name__}: {errore}"]
            righe.append(riga)
            print(nome, riga["guasti"] or "ok", flush=True)
    difficili = [r for r in righe if r["difficile"]]
    conti = {"tutte": len(righe), "giuste": sum(not r["guasti"] for r in righe),
             "difficili": len(difficili),
             "difficili_giuste": sum(not r["guasti"] for r in difficili)}
    argomenti.uscita.write_text(json.dumps({"conti": conti, "righe": righe}, indent=1,
                                           ensure_ascii=False, default=str),
                                encoding="utf-8")
    print(json.dumps(conti))
    return 0 if conti["giuste"] == conti["tutte"] else 1


if __name__ == "__main__":
    sys.exit(main())
