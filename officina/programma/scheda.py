from __future__ import annotations

import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Mapping

from officina.errori import ErroreOfficina

INDICE_PYTORCH = "https://download.pytorch.org/whl"

TORCH_MINIMO = (2, 6)
PRIMA_CUDA_RECENTE = (12, 4)

SENZA_FINESTRA = getattr(subprocess, "CREATE_NO_WINDOW", 0)


@dataclass(frozen=True)
class Scheda:

    nome: str
    memoria: int
    capacita: tuple[int, int] | None

    @property
    def memoria_a_parole(self) -> str:
        if not self.memoria:
            return "memoria sconosciuta"
        giga = self.memoria / 2 ** 30
        return f"{giga:.0f} GB" if giga >= 1.95 else f"{giga:.1f} GB"


@dataclass(frozen=True)
class Esame:

    schede: tuple[Scheda, ...] = ()
    driver: str | None = None
    cuda_del_driver: tuple[int, int] | None = None
    fonte: str = "nessuna"

    @property
    def nvidia(self) -> bool:
        return bool(self.schede)

    @property
    def la_migliore(self) -> Scheda | None:
        if not self.schede:
            return None
        return max(self.schede, key=lambda s: (s.memoria, s.capacita or (0, 0)))

    def come_dati(self) -> dict:
        return {
            "schede": [{"nome": s.nome, "memoria": s.memoria,
                        "capacita": list(s.capacita) if s.capacita else None}
                       for s in self.schede],
            "driver": self.driver,
            "cuda_del_driver": list(self.cuda_del_driver) if self.cuda_del_driver else None,
            "fonte": self.fonte,
        }


def _testo(valore) -> str:
    if isinstance(valore, bytes):
        return valore.decode("utf-8", "replace")
    return str(valore)


def _cuda_da_numero(numero: int) -> tuple[int, int] | None:
    if not numero or numero < 1000:
        return None
    return (numero // 1000, (numero % 1000) // 10)


def con_nvml(libreria=None) -> Esame | None:
    try:
        nv = libreria
        if nv is None:
            import pynvml as nv
        nv.nvmlInit()
    except Exception:
        return None
    try:
        try:
            driver = _testo(nv.nvmlSystemGetDriverVersion())
        except Exception:
            driver = None
        try:
            cuda = _cuda_da_numero(int(nv.nvmlSystemGetCudaDriverVersion_v2()))
        except Exception:
            try:
                cuda = _cuda_da_numero(int(nv.nvmlSystemGetCudaDriverVersion()))
            except Exception:
                cuda = None
        schede = []
        for numero in range(int(nv.nvmlDeviceGetCount())):
            maniglia = nv.nvmlDeviceGetHandleByIndex(numero)
            nome = _testo(nv.nvmlDeviceGetName(maniglia))
            try:
                memoria = int(nv.nvmlDeviceGetMemoryInfo(maniglia).total)
            except Exception:
                memoria = 0
            try:
                grande, piccola = nv.nvmlDeviceGetCudaComputeCapability(maniglia)
                capacita = (int(grande), int(piccola))
            except Exception:
                capacita = None
            schede.append(Scheda(nome=nome, memoria=memoria, capacita=capacita))
        return Esame(schede=tuple(schede), driver=driver,
                     cuda_del_driver=cuda, fonte="nvml")
    except Exception:
        return None
    finally:
        try:
            nv.nvmlShutdown()
        except Exception:
            pass


def i_posti_di_nvidia_smi(sistema: str | None = None,
                          ambiente: Mapping[str, str] | None = None) -> list[Path]:
    quale = sistema if sistema is not None else sys.platform
    variabili = ambiente if ambiente is not None else os.environ
    if quale == "win32":
        sistema_windows = variabili.get("SystemRoot") or r"C:\Windows"
        programmi = variabili.get("ProgramFiles") or r"C:\Program Files"
        return [Path(sistema_windows) / "System32" / "nvidia-smi.exe",
                Path(programmi) / "NVIDIA Corporation" / "NVSMI" / "nvidia-smi.exe"]
    return [Path("/usr/bin/nvidia-smi"), Path("/usr/local/bin/nvidia-smi"),
            Path("/usr/local/nvidia/bin/nvidia-smi"), Path("/usr/lib/wsl/lib/nvidia-smi")]


def dov_e_nvidia_smi(c_e: Callable[[Path], bool] | None = None,
                     sistema: str | None = None,
                     ambiente: Mapping[str, str] | None = None) -> str | None:
    guarda = c_e if c_e is not None else (lambda p: p.is_file())
    for posto in i_posti_di_nvidia_smi(sistema, ambiente):
        if os.path.isabs(posto) and guarda(posto):
            return str(posto)
    return None


def _esegui(comando: list[str]) -> str | None:
    try:
        fatto = subprocess.run(comando, capture_output=True, text=True,
                               timeout=20, check=False,
                               creationflags=SENZA_FINESTRA)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if fatto.returncode != 0:
        return None
    return fatto.stdout


UNA_RIGA = re.compile(r"^\s*(?P<nome>[^,]+),\s*(?P<memoria>\d+)\s*,\s*"
                      r"(?P<capacita>\d+\.\d+|\[N/A\]|N/A)?\s*,\s*(?P<driver>[\w.]+)\s*$")

VERSIONE_CUDA = re.compile(r"CUDA Version:\s*(\d+)\.(\d+)")


def leggi_nvidia_smi(elenco: str, intestazione: str) -> Esame | None:
    schede = []
    driver = None
    for riga in (elenco or "").splitlines():
        preso = UNA_RIGA.match(riga)
        if not preso:
            continue
        capacita = None
        if preso["capacita"] and preso["capacita"][0].isdecimal():
            grande, piccola = preso["capacita"].split(".")
            capacita = (int(grande), int(piccola))
        schede.append(Scheda(nome=preso["nome"].strip(),
                             memoria=int(preso["memoria"]) * 2 ** 20,
                             capacita=capacita))
        driver = driver or preso["driver"]
    if not schede:
        return None
    cuda = VERSIONE_CUDA.search(intestazione or "")
    return Esame(schede=tuple(schede), driver=driver,
                 cuda_del_driver=(int(cuda[1]), int(cuda[2])) if cuda else None,
                 fonte="nvidia-smi")


def con_nvidia_smi(esegui: Callable[[list[str]], str | None] | None = None) -> Esame | None:
    dove = dov_e_nvidia_smi()
    if dove is None:
        return None
    lancia = esegui if esegui is not None else _esegui
    elenco = lancia([dove, "--query-gpu=name,memory.total,compute_cap,driver_version",
                     "--format=csv,noheader,nounits"])
    if elenco is None:
        return None
    return leggi_nvidia_smi(elenco, lancia([dove]) or "")


def _prova(chi) -> Esame | None:
    try:
        return chi()
    except Exception:
        return None


def esamina(nvml: Callable[[], Esame | None] | None = None,
            smi: Callable[[], Esame | None] | None = None) -> Esame:
    chiedi_a_smi = smi or con_nvidia_smi
    prima = _prova(nvml or con_nvml)
    if prima is not None and prima.schede:
        if prima.cuda_del_driver is None or any(s.capacita is None for s in prima.schede):
            return _completa(prima, chiedi_a_smi)
        return prima
    seconda = _prova(chiedi_a_smi)
    if seconda is not None and seconda.schede:
        return seconda
    return Esame()


def _completa(esito: Esame, smi) -> Esame:
    altro = _prova(smi)
    if altro is None or not altro.schede:
        return esito
    per_nome = {s.nome: s for s in altro.schede}
    schede = tuple(
        Scheda(nome=s.nome, memoria=s.memoria or getattr(per_nome.get(s.nome), "memoria", 0),
               capacita=s.capacita or getattr(per_nome.get(s.nome), "capacita", None))
        for s in esito.schede)
    return Esame(schede=schede, driver=esito.driver or altro.driver,
                 cuda_del_driver=esito.cuda_del_driver or altro.cuda_del_driver,
                 fonte=esito.fonte)


@dataclass(frozen=True)
class Variante:

    etichetta: str
    cuda: tuple[int, int] | None
    capacita_minima: tuple[int, int] = (0, 0)
    capacita_massima: tuple[int, int] = (99, 99)

    def va_con(self, capacita: tuple[int, int] | None) -> bool:
        if capacita is None:
            return self.capacita_minima <= (7, 5)
        return self.capacita_minima <= capacita <= self.capacita_massima


CPU = Variante("cpu", None)

CONOSCIUTE = (
    Variante("cu118", (11, 8), (3, 7), (9, 0)),
    Variante("cu121", (12, 1), (5, 0), (9, 0)),
    Variante("cu124", (12, 4), (5, 0), (9, 0)),
    Variante("cu126", (12, 6), (5, 0), (9, 0)),
    Variante("cu128", (12, 8), (7, 0), (12, 9)),
    Variante("cu129", (12, 9), (7, 0), (12, 9)),
    Variante("cu130", (13, 0), (7, 5), (13, 9)),
)


def varianti_future(fino_a_minore: int = 9) -> tuple[Variante, ...]:
    return tuple(Variante(f"cu13{minore}", (13, minore), (7, 5), (13, 9))
                 for minore in range(1, fino_a_minore + 1))


def candidate(esame: Esame, tutte: Iterable[Variante] | None = None) -> list[Variante]:
    scheda = esame.la_migliore
    if scheda is None:
        return [CPU]
    elenco = list(tutte) if tutte is not None else [*CONOSCIUTE, *varianti_future()]
    tetto = esame.cuda_del_driver
    buone = [v for v in elenco
             if v.cuda is not None
             and (tetto is None or v.cuda <= tetto)
             and v.va_con(scheda.capacita)]
    if tetto is None:
        buone = [v for v in buone if v.cuda <= (12, 6)]
    buone.sort(key=lambda v: v.cuda, reverse=True)
    return [*buone, CPU]


@dataclass(frozen=True)
class Piano:

    variante: Variante
    indice: str
    torch: str
    torchvision: str
    perche: str
    avvisi: tuple[str, ...] = field(default_factory=tuple)

    def come_dati(self) -> dict:
        return {"variante": self.variante.etichetta, "indice": self.indice,
                "torch": self.torch, "torchvision": self.torchvision,
                "perche": self.perche, "avvisi": list(self.avvisi)}


def etichetta_di_python() -> str:
    return f"cp{sys.version_info.major}{sys.version_info.minor}"


def piattaforma() -> str:
    if sys.platform == "win32":
        return "win_amd64"
    if sys.platform == "darwin":
        return "macosx"
    return "linux_x86_64"


UN_PACCHETTO = re.compile(
    r"(?P<nome>torch|torchvision)-(?P<versione>\d+(?:\.\d+)+)(?:%2B|\+)(?P<variante>[a-z0-9]+)"
    r"-(?P<py>cp\d+)-(?P<abi>cp\d+t?)-(?P<dove>[a-z0-9_]+)\.whl")


UNA_VERSIONE_DI_TORCH = re.compile(r"^\s*(\d+)\.(\d+)")


def _versione(testo: str) -> tuple[int, ...]:
    return tuple(int(p) for p in testo.split("."))


def _stessa_piattaforma(scritta: str, cercata: str) -> bool:
    if cercata == "win_amd64":
        return scritta == "win_amd64"
    if cercata == "macosx":
        return scritta.startswith("macosx")
    return "linux" in scritta and scritta.endswith("x86_64")


def versioni_nell_indice(pagina: str, nome: str, variante: str,
                         python: str | None = None,
                         dove: str | None = None) -> list[str]:
    python = python or etichetta_di_python()
    dove = dove or piattaforma()
    trovate = set()
    for preso in UN_PACCHETTO.finditer(pagina or ""):
        if preso["nome"] != nome or preso["variante"] != variante:
            continue
        if preso["py"] != python or preso["abi"] != python:
            continue
        if not _stessa_piattaforma(preso["dove"], dove):
            continue
        trovate.add(preso["versione"])
    return sorted(trovate, key=_versione, reverse=True)


def torch_legge_in_sicurezza(versione: str | None) -> bool:
    preso = UNA_VERSIONE_DI_TORCH.match(str(versione or ""))
    if not preso:
        return False
    return (int(preso[1]), int(preso[2])) >= TORCH_MINIMO


class TorchTroppoVecchio(ErroreOfficina):
    codice = "torch_troppo_vecchio"


def controlla_che_torch_legga_in_sicurezza(torch) -> None:
    versione = str(getattr(torch, "__version__", "") or "")
    if torch_legge_in_sicurezza(versione):
        return
    minima = ".".join(str(n) for n in TORCH_MINIMO)
    raise TorchTroppoVecchio(
        f"Il motore delle reti neurali che hai in casa (torch {versione or 'sconosciuto'}) "
        f"è troppo vecchio per aprire questo file in sicurezza: prima della versione "
        f"{minima} un file di pesi costruito apposta può far eseguire codice sul "
        "computer. Per questo non lo apro. Aggiorna i motori all'ultima versione "
        "e riprova; il resto del programma funziona lo stesso.")


def torchvision_per(torch: str, disponibili: list[str]) -> str | None:
    pezzi = _versione(torch)
    if len(pezzi) >= 2 and pezzi[0] == 2:
        attesa = (0, pezzi[1] + 15)
        for versione in disponibili:
            if _versione(versione)[:2] == attesa:
                return versione
        return None
    return disponibili[0] if disponibili else None


def leggi_pagina(indirizzo: str, entro: float = 30.0) -> str | None:
    import urllib.request

    try:
        richiesta = urllib.request.Request(indirizzo, headers={"User-Agent": "pip/25"})
        with urllib.request.urlopen(richiesta, timeout=entro) as risposta:
            if risposta.status != 200:
                return None
            return risposta.read(8 * 2 ** 20).decode("utf-8", "replace")
    except Exception:
        return None


def perche_a_parole(esame: Esame, variante: Variante) -> str:
    scheda = esame.la_migliore
    if scheda is None:
        return ("Su questo computer non c'è una scheda video NVIDIA: il "
                "programma lavorerà con il processore. Funziona tutto, solo "
                "più lentamente quando calcola le impronte.")
    if variante.etichetta == "cpu":
        driver = esame.cuda_del_driver
        if driver and driver < (11, 8):
            motivo = "il driver NVIDIA è troppo vecchio per le versioni di oggi"
        elif driver and driver < PRIMA_CUDA_RECENTE:
            motivo = ("il driver NVIDIA è troppo vecchio per una versione "
                      "abbastanza recente da essere sicura")
        else:
            motivo = "nessuna versione con CUDA va bene per questa scheda"
        consiglio = (" Aggiornando il driver NVIDIA dal sito di NVIDIA potrai "
                     "usare anche la scheda." if driver and driver < PRIMA_CUDA_RECENTE
                     else "")
        return (f"Ho trovato una {scheda.nome} ({scheda.memoria_a_parole}), ma "
                f"{motivo}: per sicurezza lavorerò con il processore.{consiglio}")
    cuda = ".".join(str(n) for n in variante.cuda)
    return (f"Ho trovato una {scheda.nome} ({scheda.memoria_a_parole}). "
            f"Prendo la versione per CUDA {cuda}, che il suo driver regge.")


def prepara_il_piano(esame: Esame,
                     leggi: Callable[[str], str | None] | None = None,
                     python: str | None = None,
                     dove: str | None = None) -> Piano:
    guarda = leggi if leggi is not None else leggi_pagina
    avvisi = []
    for variante in candidate(esame):
        indice = f"{INDICE_PYTORCH}/{variante.etichetta}"
        torce = [v for v in versioni_nell_indice(
                     guarda(f"{indice}/torch/") or "", "torch",
                     variante.etichetta, python, dove)
                 if _versione(v)[:2] >= TORCH_MINIMO]
        if not torce:
            continue
        visioni = versioni_nell_indice(guarda(f"{indice}/torchvision/") or "",
                                       "torchvision", variante.etichetta, python, dove)
        for torch in torce:
            visione = torchvision_per(torch, visioni)
            if visione is None:
                continue
            if variante.etichetta == "cpu" and esame.nvidia:
                avvisi.append("scheda_senza_variante")
            return Piano(variante=variante, indice=indice,
                         torch=f"{torch}+{variante.etichetta}",
                         torchvision=f"{visione}+{variante.etichetta}",
                         perche=perche_a_parole(esame, variante),
                         avvisi=tuple(avvisi))
    return Piano(variante=CPU, indice="", torch="", torchvision="",
                 perche=perche_a_parole(esame, CPU),
                 avvisi=("indice_irraggiungibile",))


PROVA_DELLA_SCHEDA = r"""
import json, sys
sys.path.append(sys.argv[1])
esito = {"ok": False}
try:
    import torch
    esito["torch"] = torch.__version__
    esito["cuda"] = torch.version.cuda
    esito["disponibile"] = bool(torch.cuda.is_available())
    if esito["disponibile"]:
        uno = torch.ones((256, 256), device="cuda")
        conto = float((uno @ uno).sum().item())
        torch.cuda.synchronize()
        esito["conto_giusto"] = conto == 256.0 ** 3
        esito["nome"] = torch.cuda.get_device_name(0)
    else:
        uno = torch.ones((64, 64))
        esito["conto_giusto"] = float((uno @ uno).sum().item()) == 64.0 ** 3
    esito["ok"] = True
except Exception as guasto:
    esito["guasto"] = type(guasto).__name__
sys.stdout.write(json.dumps(esito))
"""


def prova_davvero(eseguibile: str, librerie: Path,
                  esegui: Callable[..., subprocess.CompletedProcess] | None = None,
                  entro: float = 300.0) -> dict:
    import json

    lancia = esegui if esegui is not None else subprocess.run
    try:
        fatto = lancia([eseguibile, "-c", PROVA_DELLA_SCHEDA, str(librerie)],
                       capture_output=True, text=True, timeout=entro,
                       check=False, creationflags=SENZA_FINESTRA)
    except (OSError, subprocess.TimeoutExpired):
        return {"ok": False, "guasto": "non_partito"}
    righe = (fatto.stdout or "").strip().splitlines()
    try:
        return json.loads(righe[-1]) if righe else {"ok": False, "guasto": "muto"}
    except ValueError:
        return {"ok": False, "guasto": "illeggibile"}


def la_scheda_lavora(esito: dict, variante: Variante) -> bool:
    if not esito.get("ok") or not esito.get("conto_giusto"):
        return False
    if variante.etichetta == "cpu":
        return True
    return bool(esito.get("disponibile"))
