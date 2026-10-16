from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path

CASA = Path(__file__).resolve().parent.parent
COSTRUZIONE = CASA / "costruzione"
SCARICATI = CASA / "costruzione-scaricati"

FTP_PYTHON = "https://www.python.org/ftp/python/"
WEBVIEW2 = "https://go.microsoft.com/fwlink/p/?LinkId=2124703"
LIBRERIE_BLOCCATE = CASA / "installatore" / "librerie-del-programma.txt"

PYTHON_INCORPORATA = "3.13.16"
IMPRONTE_DI_PYTHON: dict[str, str] = {
    "3.13.16": "97dae5274cc54867065e8d5a3226e48c35017ed332a0fdb0e27d5b5821961297",
}

FIRMATARIO_DI_WEBVIEW2 = "O=Microsoft Corporation"

LIBRERIE_DI_VISUAL_CPP = (
    "msvcp140.dll", "msvcp140_1.dll", "msvcp140_2.dll", "msvcp140_atomic_wait.dll",
    "msvcp140_codecvt_ids.dll", "vcruntime140.dll", "vcruntime140_1.dll",
    "concrt140.dll", "vcomp140.dll",
)

NON_SERVONO = ("__pycache__", "*.pyc")

SOLO_SORGENTE = {"proxy-tools": "proxy_tools"}


def scarica(indirizzo: str, dove: Path) -> Path:
    dove.parent.mkdir(parents=True, exist_ok=True)
    if dove.exists() and dove.stat().st_size > 0:
        return dove
    richiesta = urllib.request.Request(indirizzo, headers={"User-Agent": "prepara.py"})
    with urllib.request.urlopen(richiesta, timeout=120) as risposta, open(dove, "wb") as fuori:
        shutil.copyfileobj(risposta, fuori)
    return dove


def ultima_python(minore: str) -> str:
    with urllib.request.urlopen(FTP_PYTHON, timeout=60) as risposta:
        elenco = risposta.read().decode("utf-8", "replace")
    versioni = sorted({tuple(int(p) for p in v.split("."))
                       for v in re.findall(rf'href="({re.escape(minore)}\.\d+)/"', elenco)},
                      reverse=True)
    for versione in versioni:
        testo = ".".join(str(p) for p in versione)
        indirizzo = f"{FTP_PYTHON}{testo}/python-{testo}-embed-amd64.zip"
        try:
            with urllib.request.urlopen(urllib.request.Request(indirizzo, method="HEAD"),
                                        timeout=30) as risposta:
                if risposta.status == 200:
                    return testo
        except Exception:
            continue
    raise SystemExit(f"nessuna Python {minore}.x incorporabile trovata")


def controlla_python(archivio: Path, versione: str) -> None:
    attesa = IMPRONTE_DI_PYTHON.get(versione)
    trovata = impronta(archivio)
    if attesa is None:
        raise SystemExit(f"la Python {versione} non ha un'impronta fissata in prepara.py "
                         f"(quella scaricata è {trovata})")
    if trovata != attesa:
        archivio.unlink(missing_ok=True)
        raise SystemExit(f"la Python {versione} scaricata non è quella attesa: "
                         f"{trovata} invece di {attesa}")


def prepara_python(versione: str, dove: Path) -> None:
    archivio = scarica(f"{FTP_PYTHON}{versione}/python-{versione}-embed-amd64.zip",
                       SCARICATI / f"python-{versione}-embed-amd64.zip")
    controlla_python(archivio, versione)
    with zipfile.ZipFile(archivio) as zip_:
        zip_.extractall(dove)
    minore = "".join(versione.split(".")[:2])
    for vecchio in dove.glob("python*._pth"):
        vecchio.unlink()
    (dove / f"python{minore}._pth").write_text(
        f"python{minore}.zip\n.\nLib\\site-packages\n..\\app\n", encoding="utf-8")
    (dove / "Lib" / "site-packages").mkdir(parents=True, exist_ok=True)


def dividi_le_librerie(testo: str) -> tuple[str, dict[str, tuple[str, set[str]]]]:
    tenute: list[str] = []
    a_parte: dict[str, tuple[str, set[str]]] = {}
    blocco: list[str] = []
    for riga in testo.splitlines() + [""]:
        if blocco and (not riga.startswith((" ", "\t")) or not riga.strip()):
            nome, _, versione = blocco[0].split(" ")[0].partition("==")
            if nome.lower() in SOLO_SORGENTE:
                impronte = set(re.findall(r"--hash=sha256:([0-9a-f]{64})", " ".join(blocco)))
                a_parte[nome.lower()] = (versione, impronte)
            else:
                tenute.extend(blocco)
            blocco = []
        if riga and not riga.startswith(("#", " ", "\t")) and "==" in riga:
            blocco = [riga]
        elif blocco:
            blocco.append(riga)
        else:
            tenute.append(riga)
    return "\n".join(tenute).strip() + "\n", a_parte


def metti_dal_sorgente(nome: str, versione: str, impronte: set[str], sito: Path) -> None:
    with urllib.request.urlopen(f"https://pypi.org/pypi/{nome}/{versione}/json", timeout=60) as risposta:
        file = json.load(risposta)["urls"]
    giusto = next((f for f in file if f["packagetype"] == "sdist"
                   and f["digests"]["sha256"] in impronte), None)
    if giusto is None:
        raise SystemExit(f"{nome} {versione}: nessun sorgente con l'impronta fissata")
    with tempfile.TemporaryDirectory() as cartella:
        archivio = scarica(giusto["url"], Path(cartella) / giusto["filename"])
        if impronta(archivio) not in impronte:
            raise SystemExit(f"{nome} {versione}: l'impronta del sorgente non torna")
        modulo = SOLO_SORGENTE[nome]
        with tarfile.open(archivio) as tar:
            for membro in tar.getmembers():
                pezzi = Path(membro.name).parts
                if len(pezzi) < 3 or pezzi[1] != modulo or not membro.isfile():
                    continue
                if ".." in pezzi or not membro.name.endswith(".py"):
                    continue
                destinazione = sito.joinpath(*pezzi[1:])
                destinazione.parent.mkdir(parents=True, exist_ok=True)
                with tar.extractfile(membro) as dentro, open(destinazione, "wb") as fuori:
                    shutil.copyfileobj(dentro, fuori)
        if not (sito / modulo / "__init__.py").is_file():
            raise SystemExit(f"{nome} {versione}: nel sorgente non c'è {modulo}")


def installa_le_librerie(dove: Path) -> None:
    sito = dove / "Lib" / "site-packages"
    tenute, a_parte = dividi_le_librerie(LIBRERIE_BLOCCATE.read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory() as cartella:
        elenco = Path(cartella) / "librerie.txt"
        elenco.write_text(tenute, encoding="utf-8")
        subprocess.run([sys.executable, "-m", "pip", "install", "--no-cache-dir",
                        "--disable-pip-version-check", "--no-warn-script-location",
                        "--require-hashes", "--only-binary", ":all:", "--no-deps",
                        "--target", str(sito), "-r", str(elenco)],
                       check=True)
    for nome, (versione, impronte) in a_parte.items():
        metti_dal_sorgente(nome, versione, impronte, sito)
    for cartella in sito.rglob("__pycache__"):
        shutil.rmtree(cartella, ignore_errors=True)
    for inutile in ("bin", "Scripts"):
        shutil.rmtree(sito / inutile, ignore_errors=True)


def copia_le_librerie_di_visual_cpp(dove: Path) -> list[str]:
    sistema = Path(r"C:\Windows\System32")
    copiate = []
    for nome in LIBRERIE_DI_VISUAL_CPP:
        origine = sistema / nome
        if origine.is_file() and not (dove / nome).exists():
            shutil.copy2(origine, dove / nome)
            copiate.append(nome)
    return copiate


def copia_il_programma(dove: Path, versione: str, canale: str, commit: str,
                       rilasci: str = "") -> None:
    shutil.copytree(CASA / "officina", dove / "officina",
                    ignore=shutil.ignore_patterns(*NON_SERVONO))
    for nome in ("requirements.txt", "requirements-modelli.txt", "requirements-programma.txt",
                 "requirements-miglioria.txt"):
        shutil.copy2(CASA / nome, dove / nome)
    costruzione = {"versione": versione, "canale": canale, "commit": commit}
    if rilasci:
        costruzione["rilasci"] = rilasci
    (dove / "costruzione.json").write_text(json.dumps(costruzione, indent=2),
                                           encoding="utf-8")


def controlla_la_firma_di_microsoft(file: Path) -> None:
    if sys.platform != "win32":
        return
    powershell = Path(r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe")
    comando = ("$f = Get-AuthenticodeSignature -LiteralPath $env:FILE_DA_CONTROLLARE; "
               "Write-Output $f.Status; Write-Output $f.SignerCertificate.Subject")
    uscita = subprocess.run([str(powershell), "-NoProfile", "-NonInteractive", "-Command", comando],
                            capture_output=True, text=True, check=True,
                            env={**os.environ, "FILE_DA_CONTROLLARE": str(file)})
    righe = [r.strip() for r in uscita.stdout.splitlines() if r.strip()]
    if len(righe) < 2 or righe[0] != "Valid" or FIRMATARIO_DI_WEBVIEW2 not in righe[1]:
        file.unlink(missing_ok=True)
        raise SystemExit(f"{file.name} non porta una firma valida di Microsoft: {righe}")


def impronta(file: Path) -> str:
    calcolo = hashlib.sha256()
    with open(file, "rb") as dentro:
        for pezzo in iter(lambda: dentro.read(1024 * 1024), b""):
            calcolo.update(pezzo)
    return calcolo.hexdigest()


def principale() -> int:
    scelte = argparse.ArgumentParser()
    scelte.add_argument("--versione", required=True)
    scelte.add_argument("--canale", choices=("beta", "finale"), default="beta")
    scelte.add_argument("--commit", default="")
    scelte.add_argument("--python", default="")
    scelte.add_argument("--impronta", default="")
    scelte.add_argument("--rilasci", default="")
    argomenti = scelte.parse_args()

    if argomenti.impronta:
        file = Path(argomenti.impronta)
        Path(str(file) + ".sha256").write_text(f"{impronta(file)}  {file.name}\n",
                                               encoding="ascii")
        return 0

    minore = f"{sys.version_info.major}.{sys.version_info.minor}"
    versione_python = argomenti.python or PYTHON_INCORPORATA or ultima_python(minore)
    if not versione_python.startswith(minore + "."):
        raise SystemExit(f"la Python incorporata ({versione_python}) deve essere la "
                         f"stessa {minore} di chi costruisce")
    shutil.rmtree(COSTRUZIONE, ignore_errors=True)
    python = COSTRUZIONE / "python"
    prepara_python(versione_python, python)
    installa_le_librerie(python)
    copiate = copia_le_librerie_di_visual_cpp(python) if sys.platform == "win32" else []
    copia_il_programma(COSTRUZIONE / "app", argomenti.versione, argomenti.canale,
                       argomenti.commit, argomenti.rilasci)
    controlla_la_firma_di_microsoft(scarica(WEBVIEW2, COSTRUZIONE / "MicrosoftEdgeWebview2Setup.exe"))
    print(json.dumps({"python": versione_python, "visual_cpp": copiate,
                      "versione": argomenti.versione}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(principale())
