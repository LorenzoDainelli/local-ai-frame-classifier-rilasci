from __future__ import annotations

import base64
import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path
from typing import Callable, Sequence

RADICE = Path(__file__).resolve().parent.parent
ICONA = Path(__file__).resolve().parent / "web" / "statici" / "officina.ico"
NOME_VISIBILE = "Officina"
A_COSA_SERVE = "Le tue foto, sul tuo computer"


def candidati(piattaforma: str | None = None) -> list[Path]:
    quale = piattaforma or sys.platform

    if quale == "win32":
        basi = [os.environ.get("PROGRAMFILES", r"C:\Program Files"),
                os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"),
                os.environ.get("LOCALAPPDATA")
                or str(Path.home() / "AppData" / "Local")]
        code = [r"Google\Chrome\Application\chrome.exe",
                r"Microsoft\Edge\Application\msedge.exe"]
        return [Path(base) / coda for base in basi if base for coda in code]

    if quale == "darwin":
        return [Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
                Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge")]

    return [Path(p) for p in (
        "/usr/bin/google-chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser",
        "/usr/bin/microsoft-edge", "/snap/bin/chromium",
    )]


def dove_sta_un_browser(
        elenco: Sequence[Path] | None = None,
        c_e: Callable[[Path], bool] | None = None,
        nel_percorso: Callable[[str], str | None] | None = None) -> Path | None:
    guarda = c_e if c_e is not None else (lambda p: p.is_file())
    for posto in (elenco if elenco is not None else candidati()):
        if guarda(posto):
            return posto

    cerca = nel_percorso if nel_percorso is not None else shutil.which
    for nome in ("chrome", "google-chrome", "chromium", "chromium-browser",
                 "msedge", "microsoft-edge"):
        trovato = cerca(nome)
        if trovato:
            return Path(trovato)
    return None


def comando_per_la_finestra(browser: Path, indirizzo: str) -> list[str]:
    return [str(browser), f"--app={indirizzo}", "--new-window"]


def risponde(porta: int, host: str = "127.0.0.1", entro: float = 0.4) -> bool:
    try:
        with socket.create_connection((host, porta), timeout=entro):
            return True
    except OSError:
        return False


def aspetta_che_risponda(porta: int, host: str = "127.0.0.1",
                         entro: float = 30.0,
                         bussa: Callable[[int, str], bool] | None = None,
                         riposa: Callable[[float], None] | None = None,
                         adesso: Callable[[], float] | None = None) -> bool:
    import time

    prova = bussa if bussa is not None else risponde
    dormi = riposa if riposa is not None else time.sleep
    orologio = adesso if adesso is not None else time.monotonic

    scade = orologio() + entro
    while orologio() < scade:
        if prova(porta, host):
            return True
        dormi(0.15)
    return False


def apri(indirizzo: str,
         cerca: Callable[[], Path | None] | None = None,
         lancia: Callable[[list[str]], object] | None = None,
         ripiego: Callable[[str], bool] | None = None) -> str:
    trova = cerca if cerca is not None else dove_sta_un_browser
    esegui = lancia if lancia is not None else _in_sottofondo

    try:
        browser = trova()
    except OSError:
        browser = None

    if browser is not None:
        try:
            esegui(comando_per_la_finestra(browser, indirizzo))
            return "finestra"
        except OSError:
            pass

    try:
        import webbrowser

        aprilo = ripiego if ripiego is not None else webbrowser.open
        if aprilo(indirizzo):
            return "browser"
    except Exception:
        pass
    return "niente"


def _in_sottofondo(comando: list[str]) -> None:
    da_passare: dict = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if sys.platform == "win32":
        da_passare["creationflags"] = getattr(subprocess, "DETACHED_PROCESS", 0)
    else:
        da_passare["start_new_session"] = True
    subprocess.Popen(comando, **da_passare)


def apri_quando_e_pronto(porta: int, indirizzo: str | None = None,
                         host: str = "127.0.0.1") -> str:
    dove = indirizzo or f"http://localhost:{porta}"
    if not aspetta_che_risponda(porta, host):
        return "niente"
    return apri(dove)


def _con_gli_apici(percorso) -> str:
    return str(percorso).replace("'", "''")


def righe_di_powershell(bersaglio: Path, cartella: Path, icona: Path,
                        anche_nel_menu: bool = True) -> str:
    righe = [
        "$guscio = New-Object -ComObject WScript.Shell",
        "$posti = @([Environment]::GetFolderPath('Desktop'))",
    ]
    if anche_nel_menu:
        righe.append("$posti += [Environment]::GetFolderPath('Programs')")
    righe += [
        "foreach ($posto in $posti) {",
        "  if (-not $posto) { continue }",
        f"  $c = $guscio.CreateShortcut((Join-Path $posto '{NOME_VISIBILE}.lnk'))",
        f"  $c.TargetPath = '{_con_gli_apici(bersaglio)}'",
        f"  $c.WorkingDirectory = '{_con_gli_apici(cartella)}'",
        f"  $c.IconLocation = '{_con_gli_apici(icona)}'",
        f"  $c.Description = '{A_COSA_SERVE}'",
        "  $c.WindowStyle = 7",
        "  $c.Save()",
        "  if (Test-Path -LiteralPath $c.FullName) { Write-Output $c.FullName }",
        "}",
    ]
    return "\n".join(righe)


def testo_del_desktop_file(comando: str, cartella: Path, icona: Path) -> str:
    return "\n".join([
        "[Desktop Entry]",
        "Type=Application",
        f"Name={NOME_VISIBILE}",
        f"Comment={A_COSA_SERVE}",
        f"Exec={comando}",
        f"Path={cartella}",
        f"Icon={icona}",
        "Terminal=false",
        "Categories=Graphics;Photography;",
        "",
    ])


def crea_scorciatoia(radice: Path | None = None,
                     piattaforma: str | None = None,
                     esegui: Callable[[str], str] | None = None,
                     scrivi: Callable[[Path, str], None] | None = None) -> list[str]:
    from officina.errori import ErroreOfficina

    casa = radice or RADICE
    quale = piattaforma or sys.platform

    if quale == "win32":
        bersaglio = casa / f"{NOME_VISIBILE}.cmd"
        if not bersaglio.exists():
            raise ErroreOfficina(
                f"Non trovo «{bersaglio.name}» in {casa}. È il file che il "
                "collegamento deve lanciare: se manca, il collegamento "
                "punterebbe al vuoto.")
        lancia = esegui if esegui is not None else _powershell
        uscita = lancia(righe_di_powershell(bersaglio, casa, ICONA))
        fatti = [r.strip() for r in uscita.splitlines() if r.strip()]
        if not fatti:
            raise ErroreOfficina(a_mano(casa, bersaglio))
        return fatti

    if quale == "darwin":
        raise ErroreOfficina(
            "Su macOS un'icona nel Dock si fa trascinandoci dentro un "
            "programma, e questo è un comando. Per adesso si apre così: "
            "python -m officina avvia")

    metti = scrivi if scrivi is not None else _scrivi_file
    testo = testo_del_desktop_file(f"{sys.executable} -m officina avvia",
                                   casa, ICONA)
    fatti = []
    for dove in (Path.home() / ".local/share/applications" / "officina.desktop",
                 Path.home() / "Desktop" / "officina.desktop"):
        if dove.parent.is_dir() or dove.parent.name == "applications":
            metti(dove, testo)
            fatti.append(str(dove))
    return fatti


def a_mano(casa: Path, bersaglio: Path, perche: str = "") -> str:
    coda = f"\n\n  Windows ha detto: {perche}" if perche else ""
    return (
        "Non sono riuscito a creare il collegamento da solo, ma si fa a mano "
        "in cinque secondi e viene identico:\n\n"
        f"  1. apri la cartella {casa}\n"
        f"  2. clic destro su «{bersaglio.name}» (su Windows 11, prima "
        "«Mostra altre opzioni»)\n"
        "  3. «Invia a» -> «Desktop (crea collegamento)»\n\n"
        "  L'icona la trovi in officina/web/statici/officina.ico: si mette "
        "dalle proprietà del collegamento, ma è un vezzo — funziona anche "
        "senza." + coda)


def dov_e_powershell(cerca: Callable[[str], str | None] | None = None,
                     c_e: Callable[[Path], bool] | None = None) -> str | None:
    dove = cerca if cerca is not None else shutil.which
    guarda = c_e if c_e is not None else (lambda p: p.is_file())

    for nome in ("powershell", "pwsh"):
        trovato = dove(nome)
        if trovato:
            return trovato

    fisso = (Path(os.environ.get("SystemRoot", r"C:\Windows"))
             / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe")
    return str(fisso) if guarda(fisso) else None


def comando_di_powershell(dove: str, script: str) -> list[str]:
    codificato = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    return [dove, "-NoProfile", "-NonInteractive", "-EncodedCommand", codificato]


def _powershell(script: str) -> str:
    from officina.errori import ErroreOfficina

    dove = dov_e_powershell()
    if dove is None:
        raise ErroreOfficina(
            a_mano(RADICE, RADICE / f"{NOME_VISIBILE}.cmd",
                   "PowerShell non si trova su questo computer"))

    fatto = subprocess.run(comando_di_powershell(dove, script),
                           capture_output=True, text=True, check=False)
    if fatto.returncode != 0 or not fatto.stdout.strip():
        raise ErroreOfficina(
            a_mano(RADICE, RADICE / f"{NOME_VISIBILE}.cmd",
                   (fatto.stderr.strip().splitlines() or ["niente"])[0]))
    return fatto.stdout


def _scrivi_file(dove: Path, testo: str) -> None:
    dove.parent.mkdir(parents=True, exist_ok=True)
    dove.write_text(testo, encoding="utf-8")
    dove.chmod(0o755)
