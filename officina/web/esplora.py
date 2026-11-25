from __future__ import annotations

import os
import shutil
import string
import sys
from pathlib import Path, PureWindowsPath

from officina.errori import ErroreOfficina

QUANTE_AL_MASSIMO = 400

NOMI_VIETATI = {"con", "prn", "aux", "nul", *(f"com{n}" for n in range(1, 10)),
                *(f"lpt{n}" for n in range(1, 10))}

SEGNI_VIETATI = set('<>:"/\\|?*')

DI_RETE = ("Le cartelle di rete non si sfogliano da qui: collega la cartella come un "
           "disco (per esempio Z:) e scegli quello.")


def _di_rete(scritto: str) -> bool:
    return scritto.strip()[:2] in ("\\\\", "//", "\\/", "/\\")


def _libero(dove: Path) -> int | None:
    try:
        return shutil.disk_usage(dove).free
    except OSError:
        return None


def _nascosta(voce: os.DirEntry) -> bool:
    if voce.name.startswith((".", "$")):
        return True
    attributi = getattr(voce.stat(follow_symlinks=False), "st_file_attributes", 0)
    return bool(attributi & 0x6)


def radici() -> list[dict]:
    if sys.platform == "win32":
        dischi = [Path(f"{lettera}:\\") for lettera in string.ascii_uppercase]
        dischi = [d for d in dischi if d.exists()]
    else:
        dischi = [Path("/"), Path.home()]
    return [{"nome": str(d), "percorso": str(d), "disco": True, "libero": _libero(d)}
            for d in dischi]


def dentro(scritto: str) -> dict:
    testo = (scritto or "").strip().strip('"')
    if not testo:
        return {"dove": "", "su": None, "voci": radici(), "libero": None, "troppe": False}
    if _di_rete(testo):
        raise ErroreOfficina(DI_RETE)
    if not (Path(testo).is_absolute() or PureWindowsPath(testo).is_absolute()):
        raise ErroreOfficina("La cartella va scritta per intero, "
                             "dalla lettera del disco in poi.")
    dove = Path(testo)
    if not dove.is_dir():
        raise ErroreOfficina("Questa cartella non c'è, o non si può aprire.")
    voci = []
    try:
        with os.scandir(dove) as elenco:
            for voce in elenco:
                try:
                    if voce.is_dir(follow_symlinks=False) and not _nascosta(voce):
                        voci.append({"nome": voce.name, "percorso": str(dove / voce.name),
                                     "disco": False})
                except OSError:
                    continue
    except OSError:
        raise ErroreOfficina("Questa cartella non si lascia aprire.") from None
    voci.sort(key=lambda v: v["nome"].casefold())
    su = dove.parent if dove.parent != dove else None
    return {"dove": str(dove), "su": "" if su is None else str(su),
            "voci": voci[:QUANTE_AL_MASSIMO], "troppe": len(voci) > QUANTE_AL_MASSIMO,
            "libero": _libero(dove)}


def nuova(dove: str, nome: str) -> str:
    pulito = (nome or "").strip()
    if (not pulito or pulito in (".", "..") or any(s in SEGNI_VIETATI for s in pulito)
            or any(ord(s) < 32 for s in pulito) or pulito.endswith((".", " "))
            or pulito.split(".")[0].lower() in NOMI_VIETATI or len(pulito) > 120):
        raise ErroreOfficina("Questo nome non va bene per una cartella.")
    sopra = dentro(dove)
    if not sopra["dove"]:
        raise ErroreOfficina("Prima entra in un disco.")
    fatta = Path(sopra["dove"]) / pulito
    try:
        fatta.mkdir()
    except FileExistsError:
        raise ErroreOfficina("C'è già una cartella con questo nome.") from None
    except OSError:
        raise ErroreOfficina("Qui non riesco a creare la cartella.") from None
    return str(fatta)
