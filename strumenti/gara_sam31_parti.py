from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

RADICE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RADICE))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import collaudo_corpi as collaudo

REPO_SAM31 = "facebook/sam3.1"
PESI_SAM31 = "sam3.1_multiplex.pt"
REPO_SAM3 = "facebook/sam3"
PESI_SAM3 = "sam3.pt"
LATO = 1008
NOMI = {"sam3": "SAM 3 come nel programma",
        "sam31": "SAM 3.1 (codice di Meta)",
        "sam3meta": "SAM 3 (codice di Meta, controllo)"}
GRUPPI = ("tutti", "facili", "difficili", "coperte", "piccole", "molto difficili")


def impronta(file: Path) -> str:
    calcolo = hashlib.sha256()
    with file.open("rb") as dentro:
        for pezzo in iter(lambda: dentro.read(1 << 22), b""):
            calcolo.update(pezzo)
    return calcolo.hexdigest()


def prendi_i_pesi(cartella: Path) -> dict:
    from huggingface_hub import HfApi, hf_hub_download

    from officina.corpi import scaricamento
    from officina.miglioria import scaricamento as miglioria_scaricamento

    chiave = os.environ.get("HF_TOKEN") or None
    if not chiave:
        raise SystemExit("manca HF_TOKEN nei segreti del deposito")
    cartella.mkdir(parents=True, exist_ok=True)
    manifesto = miglioria_scaricamento.manifesto("sam31")
    attesa_31 = next(p["sha256"] for p in manifesto["pesi"] if p["nome"] == PESI_SAM31)
    info = HfApi().model_info(REPO_SAM3, revision=scaricamento.REVISIONE_SAM3, token=chiave,
                              files_metadata=True)
    attesa_3 = next(s.lfs.sha256 if hasattr(s.lfs, "sha256") else s.lfs["sha256"]
                    for s in info.siblings if s.rfilename == PESI_SAM3)
    fuori = {}
    for repo, nome, revisione, attesa in (
            (REPO_SAM31, PESI_SAM31, None, attesa_31),
            (REPO_SAM3, PESI_SAM3, scaricamento.REVISIONE_SAM3, attesa_3)):
        percorso = Path(hf_hub_download(repo, nome, revision=revisione, token=chiave,
                                        local_dir=str(cartella)))
        vera = impronta(percorso)
        if vera != attesa:
            raise SystemExit(f"{nome}: impronta diversa {vera} invece di {attesa}")
        fuori[nome] = {"sha256": vera, "byte": percorso.stat().st_size}
        print("PESI", nome, vera, flush=True)
    return fuori


FABBRICHE = ("arange", "zeros", "ones", "empty", "full", "tensor", "as_tensor", "linspace",
             "rand", "randn", "randint", "eye", "zeros_like", "ones_like", "empty_like",
             "full_like", "randn_like", "rand_like")


def _senza_scheda(valore):
    if isinstance(valore, str) and valore.startswith("cuda"):
        return "cpu"
    if getattr(valore, "type", None) == "cuda":
        return "cpu"
    return valore


def _sul_processore(torch) -> None:
    for nome in FABBRICHE:
        vera = getattr(torch, nome)

        def fabbrica(*parti, _vera=vera, **scelte):
            if "device" in scelte:
                scelte["device"] = _senza_scheda(scelte["device"])
            return _vera(*parti, **scelte)

        setattr(torch, nome, fabbrica)
    sposta = torch.Tensor.to

    def verso(tensore, *parti, **scelte):
        parti = tuple(_senza_scheda(p) for p in parti)
        if "device" in scelte:
            scelte["device"] = _senza_scheda(scelte["device"])
        return sposta(tensore, *parti, **scelte)

    torch.Tensor.to = verso
    sposta_modulo = torch.nn.Module.to

    def modulo_verso(modulo, *parti, **scelte):
        parti = tuple(_senza_scheda(p) for p in parti)
        if "device" in scelte:
            scelte["device"] = _senza_scheda(scelte["device"])
        return sposta_modulo(modulo, *parti, **scelte)

    torch.nn.Module.to = modulo_verso
    torch.nn.Module.cuda = lambda modulo, *parti, **scelte: modulo
    torch.Tensor.cuda = lambda tensore, *parti, **scelte: tensore
    torch.Tensor.pin_memory = lambda tensore, *parti, **scelte: tensore


def costruisci_sam31(codice: Path):
    from officina.ritocco import sam31

    sam31.carica_il_pacchetto(codice)
    from sam3 import model_builder as costruttore
    from sam3.model.sam3_multiplex_detector import Sam3MultiplexDetector
    from sam3.model.vl_combiner import SAM3VLBackboneTri

    parole = str(codice / "sam3" / "assets" / "bpe_simple_vocab_16e6.txt.gz")
    collo = costruttore._create_multiplex_tri_backbone(
        compile_mode=None, use_fa3=False, use_rope_real=False)
    tronco = SAM3VLBackboneTri(scalp=0, visual=collo,
                               text=costruttore._create_text_encoder(parole))
    return Sam3MultiplexDetector(
        num_feature_levels=1, backbone=tronco,
        transformer=costruttore._create_sam3_transformer(use_fa3=False),
        segmentation_head=costruttore._create_segmentation_head(use_fa3=False),
        semantic_segmentation_head=None,
        input_geometry_encoder=costruttore._create_geometry_encoder(),
        use_early_fusion=True, use_dot_prod_scoring=True,
        dot_prod_scoring=costruttore._create_dot_product_scoring(),
        supervise_joint_box_scores=True, is_multiplex=True)


def costruisci_sam3meta(codice: Path):
    from officina.ritocco import sam31

    sam31.carica_il_pacchetto(codice)
    from sam3 import model_builder as costruttore

    parole = str(codice / "sam3" / "assets" / "bpe_simple_vocab_16e6.txt.gz")
    return costruttore.build_sam3_image_model(
        bpe_path=parole, device="cpu", eval_mode=True, checkpoint_path=None,
        load_from_HF=False)


def carica_i_pesi(modello, pesi: Path) -> dict:
    import torch

    stato = torch.load(str(pesi), map_location="cpu", weights_only=True)
    if isinstance(stato.get("model"), dict):
        stato = stato["model"]
    dentro = {k[len("detector."):]: v for k, v in stato.items() if k.startswith("detector.")}
    voluti = set(modello.state_dict())
    mancano = sorted(voluti - set(dentro))
    avanzano = sorted(set(dentro) - voluti)
    modello.load_state_dict(dentro, strict=False)
    return {"voluti": len(voluti), "nel_file": len(dentro), "mancano": mancano[:40],
            "quanti_mancano": len(mancano), "avanzano": avanzano[:40],
            "quanti_avanzano": len(avanzano)}


class CercatoreMeta:

    def __init__(self, modello) -> None:
        self.modello = modello
        self._processore = None

    def accendi(self) -> None:
        if self._processore is not None:
            return
        from sam3.model.sam3_image_processor import Sam3Processor

        self.modello.eval()
        self._processore = Sam3Processor(self.modello, resolution=LATO, device="cpu",
                                         confidence_threshold=0.0)

    def spegni(self) -> None:
        self._processore = None

    def cerca(self, immagine, parole, sicurezza_minima: float = 0.0) -> dict:
        import torch

        self.accendi()
        intera = immagine.convert("RGB")
        larga, alta = intera.size
        fuori: dict = {}
        with torch.inference_mode():
            stato = self._processore.set_image(intera)
            for parola in parole:
                self._processore.reset_all_prompts(stato)
                stato = self._processore.set_text_prompt(parola, stato)
                riquadri = stato["boxes"].float().cpu().tolist()
                sicurezze = stato["scores"].float().cpu().tolist()
                fuori[parola] = [
                    ((x / larga, y / alta, (x2 - x) / larga, (y2 - y) / alta), float(s))
                    for (x, y, x2, y2), s in zip(riquadri, sicurezze, strict=True)
                    if s >= sicurezza_minima]
        return fuori


def corri(chi: str, cartella: Path, quante: int, codice: Path | None,
          pesi: Path | None) -> dict:
    from officina.descrittori import torcia

    torcia.con_la_rete_accesa()
    casa = cartella / "modelli" / "corpi"
    casa.mkdir(parents=True, exist_ok=True)
    esito: dict = {"chi": chi, "nome": NOMI[chi]}
    cercatore = None
    if chi == "sam3":
        chiave = os.environ.get("HF_TOKEN") or None
        if not chiave:
            raise SystemExit("manca HF_TOKEN nei segreti del deposito")
        esito["pesi"] = collaudo._sam3(casa, chiave)
    else:
        if os.environ.get("HF_TOKEN"):
            raise SystemExit("il codice di Meta non gira con la chiave HF (regola 576)")
        import torch

        _sul_processore(torch)
        torch.manual_seed(0)
        modello = (costruisci_sam31 if chi == "sam31" else costruisci_sam3meta)(codice)
        file = pesi / (PESI_SAM31 if chi == "sam31" else PESI_SAM3)
        esito["pesi"] = {"file": file.name, "sha256": impronta(file),
                         "caricati": carica_i_pesi(modello, file)}
        print(json.dumps(esito["pesi"], indent=1), flush=True)
        if esito["pesi"]["caricati"]["quanti_mancano"]:
            raise SystemExit("mancano dei pesi: la gara non sarebbe giusta")
        cercatore = CercatoreMeta(modello)
    partito = time.monotonic()
    esito["prova"] = collaudo.prova_delle_parti(casa, cartella, quante, cercatore)
    esito["minuti"] = round((time.monotonic() - partito) / 60, 1)
    return esito


def tabella(esiti: list[dict], soglia: str) -> list[str]:
    righe = [f"== soglia {soglia} =="]
    for parola in collaudo.PAROLE_DELLE_PARTI:
        righe.append(f"-- {parola}")
        for esito in esiti:
            voti = esito["prova"]["parti"][soglia].get(parola, {})
            pezzi = []
            for gruppo in GRUPPI:
                valore = voti.get(gruppo)
                if valore and valore[0] is not None:
                    pezzi.append(f"{gruppo} {100 * valore[0]:.1f}% ({valore[1]})")
            pezzi.append(f"falsi {voti.get('falsi ogni 100 foto')}")
            righe.append(f"   {esito['nome']:34s} " + " | ".join(pezzi))
    return righe


def confronta(file: list[Path], uscita: Path) -> None:
    esiti = [json.loads(f.read_text(encoding="utf-8")) for f in file if f.is_file()]
    righe = [f"{e['nome']}: {e['prova']['foto']} foto, "
             f"{e['prova']['secondi_per_foto']} s per foto" for e in esiti]
    for soglia in map(str, collaudo.SOGLIE_PARTI):
        righe += tabella(esiti, soglia)
    testo = "\n".join(righe)
    print(testo, flush=True)
    uscita.write_text(json.dumps(esiti, ensure_ascii=False, indent=1), encoding="utf-8")


def main() -> int:
    scelte = argparse.ArgumentParser()
    scelte.add_argument("--fai", choices=("pesi", "corri", "confronta"), required=True)
    scelte.add_argument("--chi", choices=tuple(NOMI), default="sam3")
    scelte.add_argument("--cartella", type=Path, default=Path("gara"))
    scelte.add_argument("--quante", type=int, default=200)
    scelte.add_argument("--codice", type=Path, default=None)
    scelte.add_argument("--pesi", type=Path, default=None)
    scelte.add_argument("--uscita", type=Path, required=True)
    scelte.add_argument("file", nargs="*", type=Path)
    argomenti = scelte.parse_args()
    if argomenti.fai == "pesi":
        fuori = prendi_i_pesi(argomenti.cartella)
    elif argomenti.fai == "corri":
        fuori = corri(argomenti.chi, argomenti.cartella, argomenti.quante, argomenti.codice,
                      argomenti.pesi)
    else:
        confronta(argomenti.file, argomenti.uscita)
        return 0
    argomenti.uscita.write_text(json.dumps(fuori, ensure_ascii=False, indent=1),
                                encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
