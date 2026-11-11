from __future__ import annotations

import argparse
import hashlib
import io
import zipfile
from pathlib import Path

DEPOSITI = ("CUHK-CSE/wider_face", "wider_face", "yifanzhang114/WIDER_FACE")
QUANTE = 6
LATO_MINIMO = 48
DIFETTI = ("sfocato", "coperto", "di_lato", "luce", "espressione", "piccolo")


def scrivi(uscita, *pezzi) -> None:
    riga = " ".join(str(p) for p in pezzi)
    print(riga, flush=True)
    uscita.write(riga + "\n")


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
            if len(n) < 10:
                continue
            volti.append({"x": n[0], "y": n[1], "l": n[2], "a": n[3], "sfocato": n[4],
                          "espressione": n[5], "luce": n[6], "non_valido": n[7],
                          "coperto": n[8], "di_lato": n[9]})
        foto[nome] = volti if quanti else []
        indice += 2 + max(quanti, 1)
    return foto


def difetti_di(volti: list[dict]) -> set[str]:
    trovati = set()
    for v in volti:
        if v["sfocato"] == 2:
            trovati.add("sfocato")
        if v["coperto"] == 2:
            trovati.add("coperto")
        if v["di_lato"] == 1:
            trovati.add("di_lato")
        if v["luce"] == 1:
            trovati.add("luce")
        if v["espressione"] == 1:
            trovati.add("espressione")
        if min(v["l"], v["a"]) < 2 * LATO_MINIMO:
            trovati.add("piccolo")
    return trovati


def scegli(foto: dict[str, list[dict]]) -> list[tuple[str, str, list[dict]]]:
    buone = []
    for nome in sorted(foto):
        volti = foto[nome]
        if not 1 <= len(volti) <= 6:
            continue
        if any(v["non_valido"] or min(v["l"], v["a"]) < LATO_MINIMO for v in volti):
            continue
        buone.append((nome, volti, difetti_di(volti)))
    scelte: list[tuple[str, str, list[dict]]] = []
    scene: set[str] = set()
    for difetto in DIFETTI:
        for nome, volti, difetti in buone:
            scena = nome.split("/")[0]
            if difetto in difetti and len(difetti) >= 2 and scena not in scene:
                scelte.append((nome, difetto, volti))
                scene.add(scena)
                break
    return scelte[:QUANTE]


def main() -> int:
    from huggingface_hub import HfApi, hf_hub_download

    argomenti = argparse.ArgumentParser()
    argomenti.add_argument("--uscita", required=True)
    scelti = argomenti.parse_args()
    api = HfApi()
    with open(scelti.uscita, "w", encoding="utf-8") as uscita:
        for deposito in DEPOSITI:
            try:
                info = api.repo_info(deposito, repo_type="dataset", files_metadata=True)
            except Exception as errore:
                scrivi(uscita, "DEPOSITO", deposito, "NO", type(errore).__name__)
                continue
            scrivi(uscita, "DEPOSITO", deposito, "REVISIONE", info.sha, "LICENZA",
                   (info.card_data or {}).get("license"))
            for file in info.siblings:
                impronta = file.lfs.sha256 if file.lfs else ""
                scrivi(uscita, "FILE", file.rfilename, file.size, impronta)
            nomi = [f.rfilename for f in info.siblings]
            parti = [n for n in nomi if n.endswith("wider_face_split.zip")]
            foto_zip = [n for n in nomi if n.endswith("WIDER_val.zip")]
            if not parti or not foto_zip:
                continue
            etichette = Path(hf_hub_download(deposito, parti[0], repo_type="dataset",
                                             revision=info.sha))
            scrivi(uscita, "ETICHETTE_SHA256", sha(etichette))
            with zipfile.ZipFile(etichette) as z:
                dentro = [n for n in z.namelist() if n.endswith("wider_face_val_bbx_gt.txt")]
                foto = leggi_le_etichette(z.read(dentro[0]).decode())
            scrivi(uscita, "FOTO_ETICHETTATE", len(foto))
            archivio = Path(hf_hub_download(deposito, foto_zip[0], repo_type="dataset",
                                            revision=info.sha))
            scrivi(uscita, "FOTO_ZIP", foto_zip[0], archivio.stat().st_size, sha(archivio))
            with zipfile.ZipFile(archivio) as z:
                voci = {n.split("images/", 1)[-1]: n for n in z.namelist()
                        if n.endswith(".jpg")}
                for nome, difetto, volti in scegli(foto):
                    voce = z.getinfo(voci[nome])
                    dati = z.read(voce)
                    from PIL import Image

                    with Image.open(io.BytesIO(dati)) as immagine:
                        misura = immagine.size
                    scrivi(uscita, "SCELTA", voci[nome], "DIFETTO", difetto, "BYTE",
                           len(dati), "SHA256", hashlib.sha256(dati).hexdigest(),
                           "MISURA", misura, "INIZIO", voce.header_offset, "COMPRESSI",
                           voce.compress_size, "MODO", voce.compress_type, "VOLTI",
                           [(v["x"], v["y"], v["l"], v["a"], v["sfocato"], v["coperto"],
                             v["di_lato"], v["luce"]) for v in volti])
            scrivi(uscita, "FINE", deposito)
            return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
