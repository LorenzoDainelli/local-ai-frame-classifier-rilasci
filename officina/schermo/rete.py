from __future__ import annotations

import ipaddress
import socket
import subprocess
import sys

from officina import registro
from officina.programma import carta

NOME_DELLA_REGOLA = "Local AI Frame Classifier - portatile"
RETI_AMMESSE = "private,domain"
SENZA_FINESTRA = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def indirizzi_di_casa() -> list[str]:
    visti: list[str] = []

    def aggiungi(indirizzo: str) -> None:
        try:
            ip = ipaddress.IPv4Address(indirizzo)
        except ValueError:
            return
        if ip.is_loopback or ip.is_link_local or ip.is_unspecified:
            return
        if indirizzo not in visti:
            visti.append(indirizzo)

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as prova:
        try:
            prova.connect(("192.0.2.1", 9))
            aggiungi(prova.getsockname()[0])
        except OSError:
            pass
    try:
        for voce in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            aggiungi(voce[4][0])
    except OSError:
        pass
    privati = [indirizzo for indirizzo in visti if ipaddress.IPv4Address(indirizzo).is_private]
    return privati or visti


def reti_di_casa() -> list[ipaddress.IPv4Network]:
    reti: list[ipaddress.IPv4Network] = []
    for indirizzo in indirizzi_di_casa():
        rete = ipaddress.IPv4Network(f"{indirizzo}/24", strict=False)
        if rete not in reti:
            reti.append(rete)
    return reti


def _di_sistema(nome: str) -> str:
    from officina.finestra import cartella_di_sistema

    return str(cartella_di_sistema() / nome)


def _mostra_la_regola(*altro: str) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(
            [_di_sistema("netsh.exe"), "advfirewall", "firewall", "show", "rule",
             f"name={NOME_DELLA_REGOLA}",
             *altro], capture_output=True, text=True, timeout=10,
            creationflags=SENZA_FINESTRA)
    except (OSError, subprocess.SubprocessError):
        return None


def _la_regola_c_e(programma: str) -> bool:
    fatto = _mostra_la_regola("verbose")
    if fatto is None or fatto.returncode != 0 or programma.lower() not in fatto.stdout.lower():
        return False
    pubblica = _mostra_la_regola("profile=public")
    return pubblica is not None and pubblica.returncode != 0


def lascia_passare_il_portatile() -> bool:
    if sys.platform != "win32":
        return True
    programma = sys.executable
    segno = f"{programma}|{RETI_AMMESSE}"
    if _la_regola_c_e(programma):
        if carta.leggi().get("muro_aperto_per") != segno:
            carta.aggiorna(muro_aperto_per=segno)
        return True
    netsh = _di_sistema("netsh.exe")
    comandi = (
        f'"{netsh}" advfirewall firewall delete rule name="{NOME_DELLA_REGOLA}" & '
        f'"{netsh}" advfirewall firewall add rule name="{NOME_DELLA_REGOLA}" dir=in action=allow '
        f'program="{programma}" enable=yes profile={RETI_AMMESSE} remoteip=localsubnet')
    try:
        import ctypes

        esito = ctypes.windll.shell32.ShellExecuteW(None, "runas", _di_sistema("cmd.exe"),
                                                   f'/s /c "{comandi}"', None, 0)
    except Exception as guasto:
        registro.avviso("schermo.muro_non_aperto", **registro.dove_si_e_rotto(guasto))
        return False
    if esito <= 32:
        registro.avviso("schermo.muro_rifiutato", esito=int(esito))
        return False
    carta.aggiorna(muro_aperto_per=segno)
    registro.evento("schermo.muro_aperto")
    return True
