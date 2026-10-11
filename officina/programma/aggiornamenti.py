from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

from officina import VERSIONE
from officina.errori import ErroreOfficina
from officina.programma import DEPOSITO_DEI_RILASCI, carta

RADICE = Path(__file__).resolve().parent.parent.parent

FILE_COSTRUZIONE = RADICE / "costruzione.json"

BETA = "beta"
FINALE = "finale"
SVILUPPO = "sviluppo"

ATTESA_RETE = 8.0

NOME_INSTALLATORE = re.compile(r"(?i)^local-ai-frame-classifier-.*\.exe$")

UNA_VERSIONE = re.compile(
    r"^v?(?P<grande>\d+)\.(?P<media>\d+)\.(?P<piccola>\d+)"
    r"(?:-(?P<canale>beta|rc)\.?(?P<numero>\d+))?$")


def costruzione(file: Path | None = None) -> dict:
    try:
        dentro = json.loads((file or FILE_COSTRUZIONE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return dentro if isinstance(dentro, dict) else {}


def versione_attuale() -> str:
    return str(costruzione().get("versione") or VERSIONE)


def canale_attuale() -> str:
    canale = costruzione().get("canale")
    return canale if canale in (BETA, FINALE) else SVILUPPO


def chiave_di(versione: str) -> tuple | None:
    preso = UNA_VERSIONE.match((versione or "").strip())
    if not preso:
        return None
    finale = preso["canale"] is None
    return (int(preso["grande"]), int(preso["media"]), int(preso["piccola"]),
            1 if finale else 0, int(preso["numero"] or 0))


def e_piu_nuova(candidata: str, attuale: str) -> bool:
    nuova, vecchia = chiave_di(candidata), chiave_di(attuale)
    if nuova is None:
        return False
    if vecchia is None:
        return True
    return nuova > vecchia


def e_una_finale(versione: str) -> bool:
    chiave = chiave_di(versione)
    return chiave is not None and chiave[3] == 1


@dataclass(frozen=True)
class Rilascio:

    versione: str
    indirizzo: str
    nome_file: str
    peso: int
    sha256: str | None
    note: str
    pubblicato: str

    @property
    def finale(self) -> bool:
        return e_una_finale(self.versione)

    def come_dati(self) -> dict:
        return {**asdict(self), "finale": self.finale}


def _impronta_dell_asset(asset: dict, tutti: list[dict],
                         leggi_testo: Callable[[str], str | None]) -> str | None:
    digest = str(asset.get("digest") or "")
    if digest.lower().startswith("sha256:"):
        return digest.split(":", 1)[1].strip().lower()
    for altro in tutti:
        if altro.get("name") == f"{asset.get('name')}.sha256":
            testo = leggi_testo(altro.get("browser_download_url") or "") or ""
            pezzo = testo.strip().split()
            if pezzo and re.fullmatch(r"[0-9a-fA-F]{64}", pezzo[0]):
                return pezzo[0].lower()
    return None


def rilasci_da(dati: list, leggi_testo: Callable[[str], str | None]) -> list[Rilascio]:
    trovati = []
    for rilascio in dati if isinstance(dati, list) else []:
        if not isinstance(rilascio, dict) or rilascio.get("draft"):
            continue
        versione = str(rilascio.get("tag_name") or "").lstrip("v")
        if chiave_di(versione) is None:
            continue
        risorse = [a for a in rilascio.get("assets") or [] if isinstance(a, dict)]
        installatori = [a for a in risorse if NOME_INSTALLATORE.match(str(a.get("name") or ""))]
        if not installatori:
            continue
        asset = installatori[0]
        trovati.append(Rilascio(
            versione=versione,
            indirizzo=str(asset.get("browser_download_url") or ""),
            nome_file=str(asset.get("name")),
            peso=int(asset.get("size") or 0),
            sha256=_impronta_dell_asset(asset, risorse, leggi_testo),
            note=str(rilascio.get("body") or "")[:4000],
            pubblicato=str(rilascio.get("published_at") or ""),
        ))
    return trovati


def il_piu_nuovo(rilasci: list[Rilascio], canale: str, attuale: str) -> Rilascio | None:
    if canale == SVILUPPO:
        return None
    buoni = [r for r in rilasci
             if (canale == BETA or r.finale) and r.sha256 and r.indirizzo.startswith("https://")
             and e_piu_nuova(r.versione, attuale)]
    if not buoni:
        return None
    return max(buoni, key=lambda r: chiave_di(r.versione))


def _chiedi(indirizzo: str, entro: float = ATTESA_RETE) -> bytes | None:
    import urllib.request

    if not indirizzo.startswith("https://"):
        return None
    richiesta = urllib.request.Request(indirizzo, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "Local-AI-Frame-Classifier",
    })
    try:
        with urllib.request.urlopen(richiesta, timeout=entro) as risposta:
            return risposta.read(4 * 2 ** 20)
    except Exception:
        return None


def _testo(indirizzo: str) -> str | None:
    grezzo = _chiedi(indirizzo)
    return grezzo.decode("utf-8", "replace") if grezzo is not None else None


UN_DEPOSITO = re.compile(r"^[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}$")


def deposito_dei_rilasci() -> str:
    scritto = str(costruzione().get("rilasci") or "")
    return scritto if UN_DEPOSITO.match(scritto) else DEPOSITO_DEI_RILASCI


def indirizzo_dei_rilasci() -> str:
    return f"https://api.github.com/repos/{deposito_dei_rilasci()}/releases?per_page=15"


def cerca(chiedi: Callable[[str], bytes | None] | None = None,
          canale: str | None = None, attuale: str | None = None) -> Rilascio | None:
    domanda = chiedi if chiedi is not None else _chiedi
    grezzo = domanda(indirizzo_dei_rilasci())
    if grezzo is None:
        carta.aggiorna(aggiornamenti_ultimo_controllo={"esito": "irraggiungibile"})
        return None
    try:
        dati = json.loads(grezzo.decode("utf-8", "replace"))
    except ValueError:
        return None

    def leggi_testo(indirizzo: str) -> str | None:
        risposta = domanda(indirizzo)
        return risposta.decode("utf-8", "replace") if risposta is not None else None

    trovato = il_piu_nuovo(rilasci_da(dati, leggi_testo),
                           canale or canale_attuale(), attuale or versione_attuale())
    carta.aggiorna(aggiornamenti_ultimo_controllo={
        "esito": "trovato" if trovato else "niente",
        "versione": trovato.versione if trovato else None})
    return trovato


class ImprontaSbagliata(ErroreOfficina):
    codice = "aggiornamento_rovinato"


def _nome_sicuro(nome: str) -> str:
    pulito = re.sub(r"[^A-Za-z0-9._-]", "_", nome)
    return pulito if NOME_INSTALLATORE.match(pulito) else "local-ai-frame-classifier-aggiornamento.exe"


def scarica(rilascio: Rilascio, al_passo: Callable[[int, int], None] | None = None,
            fermati: threading.Event | None = None,
            apri: Callable[..., object] | None = None) -> Path:
    if not rilascio.sha256:
        raise ImprontaSbagliata(
            "Questo aggiornamento non dichiara la sua impronta, e senza non "
            "lo installo.")
    cartella = carta.cartella_scaricati()
    cartella.mkdir(parents=True, exist_ok=True)
    arrivo = cartella / _nome_sicuro(rilascio.nome_file)
    provvisorio = arrivo.with_name(arrivo.name + ".parziale")
    for vecchio in cartella.glob("*.parziale"):
        if vecchio != provvisorio:
            try:
                vecchio.unlink(missing_ok=True)
            except OSError:
                pass
    ripreso = provvisorio.is_file() and provvisorio.stat().st_size > 0
    try:
        _scarica_in(rilascio, provvisorio, al_passo, fermati, apri)
    except ImprontaSbagliata:
        if not ripreso:
            raise
        _scarica_in(rilascio, provvisorio, al_passo, fermati, apri)
    provvisorio.replace(arrivo)
    carta.aggiorna(aggiornamento_scaricato={**rilascio.come_dati(), "file": str(arrivo)})
    return arrivo


def _scarica_in(rilascio: Rilascio, provvisorio: Path,
                al_passo: Callable[[int, int], None] | None,
                fermati: threading.Event | None,
                apri: Callable[..., object] | None) -> None:
    import urllib.request

    calcolo = hashlib.sha256()
    fatti = 0
    if provvisorio.is_file():
        with open(provvisorio, "rb") as dentro:
            for pezzo in iter(lambda: dentro.read(1024 * 1024), b""):
                calcolo.update(pezzo)
                fatti += len(pezzo)
    intestazioni = {"User-Agent": "Local-AI-Frame-Classifier",
                    "Accept": "application/octet-stream"}
    if fatti:
        intestazioni["Range"] = f"bytes={fatti}-"
    apertura = apri if apri is not None else urllib.request.urlopen
    richiesta = urllib.request.Request(rilascio.indirizzo, headers=intestazioni)
    try:
        with apertura(richiesta, timeout=60) as risposta:
            if fatti and getattr(risposta, "status", 200) != 206:
                calcolo = hashlib.sha256()
                fatti = 0
            resto = int(risposta.headers.get("Content-Length") or 0)
            totale = fatti + resto if resto else int(rilascio.peso or 0)
            with open(provvisorio, "ab" if fatti else "wb") as fuori:
                while True:
                    if fermati is not None and fermati.is_set():
                        raise ErroreOfficina("Scaricamento fermato.", codice="fermato")
                    pezzo = risposta.read(256 * 1024)
                    if not pezzo:
                        break
                    fuori.write(pezzo)
                    calcolo.update(pezzo)
                    fatti += len(pezzo)
                    if al_passo is not None:
                        al_passo(fatti, totale)
    except ErroreOfficina:
        raise
    except Exception:
        raise ErroreOfficina(
            "Non sono riuscito a scaricare l'aggiornamento. Riprendo da dove "
            "sono arrivato la prossima volta.", codice="aggiornamento_non_scaricato") from None
    if calcolo.hexdigest().lower() != rilascio.sha256.lower():
        provvisorio.unlink(missing_ok=True)
        raise ImprontaSbagliata(
            "L'aggiornamento scaricato non corrisponde a quello pubblicato: "
            "l'ho buttato via senza installarlo.")


def _impronta_del_file(file: Path) -> str:
    calcolo = hashlib.sha256()
    with open(file, "rb") as dentro:
        for pezzo in iter(lambda: dentro.read(1024 * 1024), b""):
            calcolo.update(pezzo)
    return calcolo.hexdigest()


def pronto_da_installare(attuale: str | None = None) -> tuple[Rilascio, Path] | None:
    scritto = carta.leggi().get("aggiornamento_scaricato")
    if not isinstance(scritto, dict):
        return None
    try:
        rilascio = Rilascio(**{k: scritto.get(k) for k in Rilascio.__dataclass_fields__})
        file = Path(scritto["file"])
    except (TypeError, KeyError):
        dimentica_lo_scaricato()
        return None
    if not e_piu_nuova(rilascio.versione, attuale or versione_attuale()):
        dimentica_lo_scaricato()
        return None
    try:
        giusto = file.is_file() and rilascio.sha256 and \
            _impronta_del_file(file).lower() == rilascio.sha256.lower()
    except OSError:
        giusto = False
    if not giusto:
        dimentica_lo_scaricato()
        return None
    return rilascio, file


def dimentica_lo_scaricato() -> None:
    scritto = carta.leggi().get("aggiornamento_scaricato")
    if isinstance(scritto, dict) and scritto.get("file"):
        try:
            Path(scritto["file"]).unlink(missing_ok=True)
        except OSError:
            pass
    carta.aggiorna(aggiornamento_scaricato=None)


def comando_dell_installatore(file: Path, riapri: bool = True) -> list[str]:
    return [str(file), "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
            "/CLOSEAPPLICATIONS", f"/RIAPRI={1 if riapri else 0}"]


def installa(file: Path, lancia: Callable[..., object] | None = None,
             riapri: bool = True) -> None:
    esegui = lancia if lancia is not None else subprocess.Popen
    opzioni: dict = {"close_fds": True, "cwd": str(Path(file).parent)}
    if sys.platform == "win32":
        opzioni["creationflags"] = (getattr(subprocess, "DETACHED_PROCESS", 0)
                                    | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    carta.aggiorna(aggiornamento_scaricato=None, aggiornamento_in_sospeso=None)
    esegui(comando_dell_installatore(file, riapri), **opzioni)


def rifiuta(rilascio: Rilascio) -> None:
    carta.aggiorna(aggiornamento_in_sospeso=rilascio.come_dati())


def in_sospeso() -> dict | None:
    scritto = carta.leggi().get("aggiornamento_in_sospeso")
    if not isinstance(scritto, dict):
        return None
    if not e_piu_nuova(str(scritto.get("versione") or ""), versione_attuale()):
        carta.aggiorna(aggiornamento_in_sospeso=None)
        return None
    return scritto


def pulisci_gli_scaricati() -> int:
    cartella = carta.cartella_scaricati()
    if not cartella.is_dir():
        return 0
    scritto = carta.leggi().get("aggiornamento_scaricato")
    da_tenere = Path(scritto["file"]).name if isinstance(scritto, dict) and scritto.get("file") else None
    tolti = 0
    for file in cartella.iterdir():
        if file.is_file() and file.name != da_tenere and file.suffix != ".parziale":
            try:
                file.unlink()
                tolti += 1
            except OSError:
                pass
    return tolti
