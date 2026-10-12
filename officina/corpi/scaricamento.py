from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from officina import istruzioni, registro
from officina.corpi import corpo3d, obiettivo
from officina.corpi import rilevatore as rilevatore_mod
from officina.descrittori import torcia
from officina.descrittori.base import VISIVO, Scheda
from officina.descrittori.scaricamento import (ScaricamentoFallito, Sorvegliante,
                                               _che_genere, _dettaglio_tecnico,
                                               _perche_e_andata_male, quanto_pesa)
from officina.errori import ErroreOfficina
from officina.stanza import costruzione, da3, vggt

SCHEDA_SUL_DISCO = "scheda.json"

SAM3 = Scheda(
    nome="corpi",
    titolo="SAM 3",
    versione=rilevatore_mod.VERSIONE,
    famiglia=VISIVO,
    dimensione=0,
    licenza="SAM License (Meta) — uso consentito, da accettare su Hugging Face",
    identificatore="facebook/sam3",
    byte_attesi=3_450_000_000,
    lato=1008,
    nota="Disegna il contorno di ogni persona, anche quando si coprono.",
    cosa_serve=("*.json", "*.safetensors", "*.txt"),
)
PAGINA_SAM3 = "https://huggingface.co/facebook/sam3"
REVISIONE_SAM3 = "3c879f39826c281e95690f02c7821c4de09afae7"
SHA256_SAM3 = {
    "config.json": "4616385e4b21f2e5e22c875b65679185cbccfa95de42542b9166f7dc3d57160f",
    "merges.txt": "9fd691f7c8039210e0fced15865466c65820d09b63988b0174bfe25de299051a",
    "model.safetensors": "6d06f0a5f84e435071fe6603e61d0b4cc7b40e0d39d487cfd4d67d8cc11cc14a",
    "processor_config.json": "6420cf2671fa9309ea95bc0144a8b9861666d1c5f43c8db09e410dacda974fce",
    "special_tokens_map.json": "2cdb3b8331a60c92fc1e55a13e9fd61fd2293c5a51275fdcccd62b780052530e",
    "tokenizer.json": "6d9109cc838977f3ca94a379eec36aecc7c807e1785cd729660ca2fc0171fb35",
    "tokenizer_config.json": "39670ad98457fe8f14ca59f6bb74591e9fc850974380a63993e5b8ffc865baa2",
    "vocab.json": "5047b556ce86ccaf6aa22b3ffccfc52d391ea4accdab9c2f2407da5b742d4363",
}


@dataclass(frozen=True)
class Indirizzo:

    url: str
    dentro: str = ""
    sha256: str = ""


@dataclass(frozen=True)
class Riserva:

    repo: str
    file: str
    sha256: str = ""


POSE = Indirizzo(
    "https://download.openmmlab.com/mmpose/v1/projects/rtmw/onnx_sdk/"
    "rtmw-dw-x-l_simcc-cocktail14_270e-384x288_20231122.zip",
    dentro="end2end.onnx")
POSE_RISERVA = Riserva(
    "SceneWorks/dwpose-onnx",
    "rtmw-dw-x-l_simcc-cocktail14_270e-384x288_20231122.onnx")
POSE_SHA256 = "bd033156e5104c4f5d2edfe0453e02661e30a2f3da453ec93c8764d561b83054"
POSE_BYTE = 229_320_930
LICENZA_POSE = "Apache 2.0 (OpenMMLab) — libera"
LICENZA_KPR = "Hippocratic 3.0 (KPR) e Apache 2.0 (SOLIDER) — uso personale consentito"

BYTE_KPR = 1_179_290_822


@dataclass(frozen=True)
class DaHuggingFace:

    titolo: str
    repo: str
    revisione: str
    file: str
    dove: str
    sha256: str
    byte: int
    serve: str = "che serve per la figura in 3D delle persone"


PER_LA_STANZA = "che serve per la stanza in 3D dei luoghi"
REPO_CORPO3D = "facebook/sam-3d-body-dinov3"
PAGINA_CORPO3D = f"https://huggingface.co/{REPO_CORPO3D}"
REVISIONE_CORPO3D = "11aaa346c7204874a1cbafe3d39a979080b2c55a"
LICENZA_CORPO3D = "SAM License (Meta) — uso consentito, da accettare su Hugging Face"
FIGURE = (
    DaHuggingFace("SAM 3D Body", REPO_CORPO3D, REVISIONE_CORPO3D, "model.ckpt",
                  f"{corpo3d.NOME}/{corpo3d.FILE_PESI}",
                  "b5a2f9d305dd02626b967aa2e86021fba07065df66ce7a7e00ffb9664f150abf", 2_109_129_346),
    DaHuggingFace("SAM 3D Body", REPO_CORPO3D, REVISIONE_CORPO3D, "model_config.yaml",
                  f"{corpo3d.NOME}/{corpo3d.FILE_MISURE}",
                  "1012fc3f39cb5e90e3f8fbadf7bded31604bfafdce0321d17a7c1a2d3f08b88d", 1_488),
    DaHuggingFace("SAM 3D Body", REPO_CORPO3D, REVISIONE_CORPO3D, "assets/mhr_model.pt",
                  f"{corpo3d.NOME}/{corpo3d.FILE_MHR}",
                  "352e271a6c42729c68554ceaea0c955e866970160c31e35506d782dc0f7377bc", 696_110_248),
    DaHuggingFace("Puffin", obiettivo.REPO_PUFFIN, obiettivo.REVISIONE_PUFFIN, obiettivo.FILE_PESI,
                  f"{obiettivo.NOME}/{obiettivo.FILE_PESI}", obiettivo.SHA256_PESI, obiettivo.BYTE_PESI),
) + tuple(
    DaHuggingFace("Puffin", obiettivo.REPO_LINGUA, obiettivo.REVISIONE_LINGUA, nome,
                  f"{obiettivo.NOME}/{obiettivo.CARTELLA_LINGUA}/{nome}", impronta, 0)
    for nome, impronta in obiettivo.SHA256_LINGUA.items()) + (
    DaHuggingFace("VGGT-Omega", vggt.REPO, vggt.REVISIONE, vggt.FILE_PESI,
                  f"{costruzione.NOME}/{costruzione.FILE_VGGT}", vggt.SHA256, vggt.BYTE, PER_LA_STANZA),
    DaHuggingFace("Depth Anything 3", da3.REPO, da3.REVISIONE, da3.FILE_PESI,
                  f"{costruzione.NOME}/{costruzione.FILE_DA3}", da3.SHA256, da3.BYTE, PER_LA_STANZA),
)
BYTE_FIGURE = sum(f.byte for f in FIGURE) + 20_000_000
BYTE_IN_TUTTO = SAM3.byte_attesi + POSE_BYTE + BYTE_KPR + BYTE_FIGURE


@dataclass
class Rapporto:
    dove: Path
    file: int = 0
    byte: int = 0
    gia_c_erano: bool = False


def gia_in_casa(cartella_modelli: Path) -> bool:
    return (rilevatore_mod.ci_sono_i_modelli(cartella_modelli)
            and corpo3d.ci_sono(cartella_modelli) and obiettivo.ci_sono(cartella_modelli)
            and costruzione.ci_sono(cartella_modelli))


def scarica(cartella_modelli: Path, al_passo: Callable[[str], None] | None = None,
            rifai: bool = False, chiave: str | None = None,
            a_che_punto: Callable[[int, int], None] | None = None) -> Rapporto:
    casa = rilevatore_mod.dove_stanno(cartella_modelli)
    if gia_in_casa(cartella_modelli) and not rifai:
        return _conta(casa, gia_c_erano=True)
    casa.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

    prima = torcia.con_la_rete_accesa()
    try:
        cartella_sam3 = casa / rilevatore_mod.CARTELLA_SAM3
        if rifai or not (cartella_sam3 / rilevatore_mod.PROVA_SAM3).exists():
            _scarica_sam3(cartella_sam3, chiave, al_passo, a_che_punto)
        file_pose = casa / rilevatore_mod.FILE_POSE
        if rifai or not file_pose.exists():
            _scarica_la_pose(file_pose, chiave, al_passo, a_che_punto)
        _scarica_kpr(cartella_modelli, rifai, al_passo, a_che_punto)
        _scarica_le_figure(casa, chiave, rifai, al_passo, a_che_punto)
    finally:
        torcia.rimetti_la_rete_com_era(prima)

    _annota(casa)
    rapporto = _conta(casa)
    registro.evento("corpi.scaricati", file=rapporto.file)
    if al_passo:
        al_passo(f"corpi: {rapporto.file} file, {rapporto.byte / 1e9:.1f} GB")
    return rapporto


def _scarica_sam3(dove: Path, chiave: str | None,
                  al_passo: Callable[[str], None] | None,
                  a_che_punto: Callable[[int, int], None] | None) -> None:
    try:
        from huggingface_hub import snapshot_download
    except ImportError as errore:
        raise ScaricamentoFallito(
            "Per scaricare i modelli serve la libreria «huggingface-hub», che "
            "si installa insieme alle altre dei modelli:\n"
            f"{istruzioni.motori()}") from errore
    if al_passo:
        al_passo(f"scarico SAM 3 — circa {SAM3.byte_attesi / 1e9:.1f} GB")
    dove.mkdir(parents=True, exist_ok=True)

    def davvero() -> None:
        snapshot_download(repo_id=SAM3.identificatore, local_dir=str(dove),
                          revision=REVISIONE_SAM3, allow_patterns=list(SAM3.cosa_serve),
                          token=chiave or None)

    try:
        if a_che_punto is None:
            davvero()
        else:
            with Sorvegliante(dove, BYTE_IN_TUTTO, a_che_punto):
                davvero()
    except Exception as errore:
        registro.errore("corpi.scaricamento_fallito",
                        ragione=registro.Parola(_che_genere(errore)))
        raise ScaricamentoFallito(
            "Non sono riuscito a scaricare SAM 3, il modello che separa le "
            "persone.\n" + _perche_sam3(errore, chiave)
            + "\n  Il resto del programma funziona lo stesso.") from errore
    diversi = [nome for nome, impronta in SHA256_SAM3.items()
               if not (dove / nome).is_file() or _sha256(dove / nome) != impronta]
    if diversi:
        for nome in {*diversi, rilevatore_mod.PROVA_SAM3}:
            (dove / nome).unlink(missing_ok=True)
        registro.errore("corpi.sam3_diverso", quanti=len(diversi))
        raise ScaricamentoFallito(
            "SAM 3 è arrivato, ma non è identico a quello provato: per sicurezza "
            "non lo tengo. Riprova più tardi; se succede ancora, il file "
            "pubblicato è cambiato e va controllato in un aggiornamento.")


def _perche_sam3(errore: Exception, chiave: str | None) -> str:
    if _che_genere(errore) == "permesso" and chiave:
        return ("  La chiave funziona, ma Hugging Face dice che non hai ancora il "
                "permesso per SAM 3. Apri la sua pagina,\n"
                f"      {PAGINA_SAM3}\n"
                "  compila il modulo per accettare la licenza, aspetta la "
                "conferma di Meta e poi riprova.")
    return _perche_e_andata_male(errore, SAM3, chiave)


def _scarica_la_pose(dove: Path, chiave: str | None,
                     al_passo: Callable[[str], None] | None,
                     a_che_punto: Callable[[int, int], None] | None) -> None:
    if al_passo:
        al_passo(f"scarico RTMW — circa {POSE_BYTE / 1e6:.0f} MB")
    gia = quanto_pesa(dove.parent)
    try:
        preso = _da_indirizzo(POSE, dove.parent,
                              None if a_che_punto is None else
                              (lambda fatti, _: a_che_punto(gia + fatti, BYTE_IN_TUTTO)))
    except Exception as primo:
        registro.avviso("corpi.pose_dalla_riserva",
                        ragione=registro.Parola(type(primo).__name__))
        if al_passo:
            al_passo("il sito di OpenMMLab non risponde: prendo RTMW dalla copia "
                     "su Hugging Face")
        try:
            preso = _da_hugging_face(POSE_RISERVA, chiave)
        except Exception as secondo:
            registro.errore("corpi.pose_non_scaricata")
            raise ScaricamentoFallito(
                "Non sono riuscito a scaricare RTMW, il modello che trova i "
                "punti del corpo, né dal sito di OpenMMLab né dalla copia su "
                "Hugging Face.\n" + _dettaglio_tecnico(primo, chiave) + "\n"
                + _dettaglio_tecnico(secondo, chiave)
                + "\n  Il resto del programma funziona lo stesso.") from secondo
    atteso = POSE_SHA256
    if atteso and _sha256(preso) != atteso:
        Path(preso).unlink(missing_ok=True)
        raise ScaricamentoFallito(
            "RTMW è arrivato, ma non è identico a quello provato: per sicurezza "
            "non lo tengo. Riprova più tardi; se succede ancora, il file "
            "pubblicato è cambiato e va controllato in un aggiornamento.")
    shutil.move(str(preso), str(dove))


def _scarica_kpr(cartella_modelli: Path, rifai: bool,
                 al_passo: Callable[[str], None] | None,
                 a_che_punto: Callable[[int, int], None] | None) -> None:
    from officina.corpi import kpr_pesi

    if kpr_pesi.tutti_in_casa(cartella_modelli) and not rifai:
        return
    gia = quanto_pesa(rilevatore_mod.dove_stanno(cartella_modelli))
    contati = {"finiti": 0, "ultimo": 0}

    def avanti(arrivati: int, _totale: int) -> None:
        if arrivati < contati["ultimo"]:
            contati["finiti"] += contati["ultimo"]
        contati["ultimo"] = arrivati
        a_che_punto(min(BYTE_IN_TUTTO, gia + contati["finiti"] + arrivati), BYTE_IN_TUTTO)

    try:
        kpr_pesi.scarica(cartella_modelli, al_passo=al_passo,
                         a_che_punto=avanti if a_che_punto else None, rifai=rifai)
    except ErroreOfficina as errore:
        registro.errore("corpi.kpr_non_scaricato", perche=registro.Parola(errore.codice or "-"))
        raise ScaricamentoFallito(
            "Non sono riuscito a scaricare KPR, il modello che riconosce la "
            "corporatura e i vestiti.\n  " + errore.messaggio
            + "\n  Il resto del programma funziona lo stesso.") from errore
    except Exception as errore:
        registro.errore("corpi.kpr_non_scaricato",
                        ragione=registro.Parola(_che_genere(errore)))
        raise ScaricamentoFallito(
            "Non sono riuscito a scaricare KPR da Google Drive, il modello che "
            "riconosce la corporatura e i vestiti.\n"
            + _dettaglio_tecnico(errore, None)
            + "\n  Il resto del programma funziona lo stesso.") from errore


def _scarica_le_figure(casa: Path, chiave: str | None, rifai: bool,
                       al_passo: Callable[[str], None] | None,
                       a_che_punto: Callable[[int, int], None] | None) -> None:
    da_fare = [f for f in FIGURE if rifai or not (casa / f.dove).exists()]
    if not da_fare:
        return
    detti: set[str] = set()
    for pezzo in da_fare:
        if al_passo and pezzo.titolo not in detti:
            detti.add(pezzo.titolo)
            byte = sum(f.byte for f in da_fare if f.titolo == pezzo.titolo)
            al_passo(f"scarico {pezzo.titolo} — circa {byte / 1e9:.1f} GB")
        finale = casa / pezzo.dove
        finale.parent.mkdir(parents=True, exist_ok=True)
        arrivo = Path(tempfile.mkdtemp(prefix="arriva-", dir=finale.parent))
        try:
            if a_che_punto is None:
                preso = _prendi(pezzo, arrivo, chiave)
            else:
                with Sorvegliante(casa, BYTE_IN_TUTTO, a_che_punto):
                    preso = _prendi(pezzo, arrivo, chiave)
            if _sha256(preso) != pezzo.sha256:
                raise ScaricamentoFallito(
                    f"{pezzo.titolo} è arrivato, ma il file «{pezzo.file}» non è identico a "
                    "quello provato: per sicurezza non lo tengo. Riprova più tardi; se "
                    "succede ancora, il file pubblicato è cambiato e va controllato in un "
                    "aggiornamento.")
            os.replace(preso, finale)
        except ScaricamentoFallito:
            raise
        except ImportError as errore:
            raise ScaricamentoFallito(
                "Per scaricare i modelli serve la libreria «huggingface-hub», che "
                "si installa insieme alle altre dei modelli:\n"
                f"{istruzioni.motori()}") from errore
        except Exception as errore:
            registro.errore("corpi.figure_non_scaricate",
                            ragione=registro.Parola(_che_genere(errore)))
            raise ScaricamentoFallito(
                f"Non sono riuscito a scaricare {pezzo.titolo}, {pezzo.serve}.\n"
                + _perche_figure(errore, pezzo, chiave)
                + "\n  Il resto del programma funziona lo stesso.") from errore
        finally:
            shutil.rmtree(arrivo, ignore_errors=True)


def _prendi(pezzo: DaHuggingFace, arrivo: Path, chiave: str | None) -> Path:
    from huggingface_hub import hf_hub_download

    return Path(hf_hub_download(repo_id=pezzo.repo, filename=pezzo.file, revision=pezzo.revisione,
                                local_dir=str(arrivo), token=chiave or None))


def _perche_figure(errore: Exception, pezzo: DaHuggingFace, chiave: str | None) -> str:
    if _che_genere(errore) == "permesso" and pezzo.repo == REPO_CORPO3D:
        return ("  Hugging Face dice che questa chiave non ha ancora il permesso per "
                "SAM 3D Body. Apri la sua pagina,\n"
                f"      {PAGINA_CORPO3D}\n"
                "  compila il modulo per accettare la licenza, aspetta la conferma di "
                "Meta e poi riprova.")
    if _che_genere(errore) == "permesso" and pezzo.repo == vggt.REPO:
        return ("  Hugging Face dice che questa chiave non ha ancora il permesso per "
                "VGGT-Omega. Apri la sua pagina,\n"
                f"      {vggt.PAGINA}\n"
                "  accetta la licenza e poi riprova.")
    return _dettaglio_tecnico(errore, chiave)


def _da_indirizzo(indirizzo: Indirizzo, vicino: Path,
                  a_che_punto: Callable[[int, int], None] | None) -> Path:
    import urllib.request

    cartella = Path(tempfile.mkdtemp(prefix="arriva-", dir=vicino))
    try:
        archivio = cartella / "scaricato"
        with urllib.request.urlopen(indirizzo.url, timeout=60) as risposta, \
                open(archivio, "wb") as fuori:
            totale = int(risposta.headers.get("Content-Length") or 0)
            fatti = 0
            while True:
                pezzo = risposta.read(1024 * 1024)
                if not pezzo:
                    break
                fuori.write(pezzo)
                fatti += len(pezzo)
                if a_che_punto:
                    a_che_punto(fatti, totale)
        if indirizzo.sha256 and _sha256(archivio) != indirizzo.sha256:
            raise ErroreOfficina("il file scaricato non è quello atteso")
        if not indirizzo.dentro:
            finale = vicino / (archivio.name + ".preso")
            shutil.move(str(archivio), str(finale))
            return finale
        with zipfile.ZipFile(archivio) as compresso:
            nomi = [nome for nome in compresso.namelist()
                    if Path(nome).name == indirizzo.dentro]
            if not nomi:
                raise ErroreOfficina(f"dentro lo zip non c'è «{indirizzo.dentro}»")
            finale = vicino / (Path(indirizzo.dentro).stem + ".preso")
            with compresso.open(nomi[0]) as dentro, open(finale, "wb") as fuori:
                shutil.copyfileobj(dentro, fuori, 1024 * 1024)
        return finale
    finally:
        shutil.rmtree(cartella, ignore_errors=True)


def _da_hugging_face(riserva: Riserva, chiave: str | None) -> Path:
    from huggingface_hub import hf_hub_download

    preso = Path(hf_hub_download(repo_id=riserva.repo, filename=riserva.file,
                                 token=chiave or None))
    if riserva.sha256 and _sha256(preso) != riserva.sha256:
        raise ErroreOfficina("la copia su Hugging Face non è quella attesa")
    maniglia, nome = tempfile.mkstemp(suffix=".preso")
    os.close(maniglia)
    shutil.copyfile(preso, nome)
    return Path(nome)


def _sha256(percorso: Path) -> str:
    digestore = hashlib.sha256()
    with open(percorso, "rb") as dentro:
        for pezzo in iter(lambda: dentro.read(1024 * 1024), b""):
            digestore.update(pezzo)
    return digestore.hexdigest()


def _impronta(percorso: Path) -> str:
    digestore = hashlib.blake2b(digest_size=16)
    with open(percorso, "rb") as dentro:
        for pezzo in iter(lambda: dentro.read(1024 * 1024), b""):
            digestore.update(pezzo)
    return digestore.hexdigest()


def _i_file(casa: Path) -> list[Path]:
    return sorted(p for p in casa.rglob("*")
                  if p.is_file() and p.name != SCHEDA_SUL_DISCO
                  and ".cache" not in p.parts and not p.name.endswith((".preso", ".parziale"))
                  and not any(parte.startswith("arriva-") for parte in p.parts))


def impronte_sha256(cartella_modelli: Path) -> dict[str, str]:
    casa = rilevatore_mod.dove_stanno(cartella_modelli)
    return {str(p.relative_to(casa)).replace("\\", "/"): _sha256(p)
            for p in _i_file(casa) if p.suffix in (".onnx", ".safetensors")}


def _annota(casa: Path) -> None:
    from officina.corpi import kpr_pesi

    (casa / SCHEDA_SUL_DISCO).write_text(json.dumps({
        "che_cosa": "i modelli del corpo: SAM 3 separa le persone, RTMW trova i punti, "
                    "KPR riconosce corporatura e vestiti, SAM 3D Body fa la figura in 3D, "
                    "Puffin capisce l'obiettivo della foto, VGGT-Omega trova da dove è stata "
                    "fatta ogni foto e Depth Anything 3 dà la forma e i metri della stanza",
        "versione": rilevatore_mod.VERSIONE,
        "da_dove": {
            rilevatore_mod.CARTELLA_SAM3: {"repo": SAM3.identificatore,
                                           "licenza": SAM3.licenza},
            rilevatore_mod.FILE_POSE: {"indirizzo": POSE.url,
                                       "riserva": f"{POSE_RISERVA.repo}/{POSE_RISERVA.file}",
                                       "licenza": LICENZA_POSE},
            corpo3d.NOME: {"repo": REPO_CORPO3D, "revisione": REVISIONE_CORPO3D,
                           "licenza": LICENZA_CORPO3D},
            obiettivo.NOME: {"repo": obiettivo.REPO_PUFFIN, "revisione": obiettivo.REVISIONE_PUFFIN,
                             "lingua": f"{obiettivo.REPO_LINGUA}@{obiettivo.REVISIONE_LINGUA}",
                             "licenza": obiettivo.LICENZA},
            costruzione.NOME: {"vggt_omega": {"repo": vggt.REPO, "revisione": vggt.REVISIONE,
                                              "licenza": vggt.LICENZA},
                               "depth_anything_3": {"repo": da3.REPO, "revisione": da3.REVISIONE,
                                                    "licenza": da3.LICENZA}},
            "kpr": {"cartella": kpr_pesi.PAGINA_DRIVE, "codice": kpr_pesi.RIPOSTIGLIO,
                    "licenza": kpr_pesi.LICENZA,
                    "file": {p.versione: {"nome": p.file, "sha256": p.sha256}
                             for p in kpr_pesi.PESI}},
        },
        "impronte": {str(p.relative_to(casa)).replace("\\", "/"): _impronta(p)
                     for p in _i_file(casa)},
    }, ensure_ascii=False, indent=2), encoding="utf-8")


def _conta(casa: Path, gia_c_erano: bool = False) -> Rapporto:
    if not casa.is_dir():
        return Rapporto(casa, gia_c_erano=gia_c_erano)
    file = _i_file(casa)
    return Rapporto(casa, len(file), sum(p.stat().st_size for p in file), gia_c_erano)


def verifica(cartella_modelli: Path) -> dict:
    casa = rilevatore_mod.dove_stanno(cartella_modelli)
    scheda = casa / SCHEDA_SUL_DISCO
    if not scheda.exists():
        return {"stato": "non_scaricato",
                "dettaglio": "I modelli del corpo non ci sono."}
    try:
        dati = json.loads(scheda.read_text(encoding="utf-8"))
    except (ValueError, OSError) as errore:
        raise ErroreOfficina("La scheda dei modelli del corpo non si legge.") from errore
    rovinati = [nome for nome, attesa in (dati.get("impronte") or {}).items()
                if not (casa / nome).exists() or _impronta(casa / nome) != attesa]
    if rovinati:
        return {"stato": "rovinato", "dettaglio":
                "Non corrispondono più: " + ", ".join(rovinati)
                + ". Riscaricali con --scarica corpi --rifai."}
    quanti = len(dati.get("impronte") or {})
    return {"stato": "intatto",
            "dettaglio": f"corpi: intatti ({quanti} file controllati) — "
                         f"{SAM3.licenza}, {LICENZA_POSE}, {LICENZA_KPR}, "
                         f"{LICENZA_CORPO3D}, {obiettivo.LICENZA}, {vggt.LICENZA}, {da3.LICENZA}"}


def togli(cartella_modelli: Path) -> bool:
    casa = rilevatore_mod.dove_stanno(cartella_modelli)
    if not casa.is_dir():
        return False
    shutil.rmtree(casa)
    return True
