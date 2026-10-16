from __future__ import annotations

import contextlib
import hashlib
import importlib
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Callable, Iterable, Iterator

from officina import cartelle, registro
from officina.descrittori import torcia
from officina.descrittori.scaricamento import (ScaricamentoFallito, Sorvegliante,
                                               _dettaglio_tecnico, quanto_pesa)

TERZI = Path(__file__).resolve().parent / "terzi"
PRONTO = "pronto.json"
CODICE = "codice"
PESI = "pesi"
GREZZO = "https://raw.githubusercontent.com"
MARGINE = 1 * 2 ** 30
PUO_ESSERE_IMPORTATO = (".py", ".pyw", ".pyc", ".pyo", ".pyd", ".so", ".dll", ".dylib",
                        ".zip", ".egg", ".pth")
_GIA_CONTROLLATI: dict[tuple[str, int, int], str] = {}


def manifesto(nome: str = "seedvr2") -> dict:
    return json.loads((TERZI / f"{nome}.json").read_text(encoding="utf-8"))


def dove(cartella_modelli: Path, nome: str = "seedvr2") -> Path:
    return Path(cartella_modelli) / "miglioria" / nome


def e_in_casa(cartella_modelli: Path, nome: str = "seedvr2") -> bool:
    casa = dove(cartella_modelli, nome)
    try:
        scritto = json.loads((casa / PRONTO).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    atteso = manifesto(nome)
    if scritto.get("commit") != atteso["commit"]:
        return False
    if motivo_del_codice_diverso(casa, atteso) is not None:
        return False
    pesi = scritto.get("pesi") or {}
    grandi = scritto.get("byte") or {}
    return all(pesi.get(p["nome"]) == p["sha256"] and (casa / PESI / p["nome"]).is_file()
               and _pesa_come_prima(casa / PESI / p["nome"], grandi.get(p["nome"]))
               for p in atteso["pesi"])


def _pesa_come_prima(file: Path, scritto: int | None) -> bool:
    if scritto is None:
        return True
    try:
        return file.stat().st_size == int(scritto)
    except (OSError, ValueError, TypeError):
        return False


def _impronta_ricordata(file: Path, ricorda: bool) -> str:
    info = file.stat()
    chiave = (str(file), info.st_size, info.st_mtime_ns)
    if ricorda and chiave in _GIA_CONTROLLATI:
        return _GIA_CONTROLLATI[chiave]
    calcolata = impronta(file)
    _GIA_CONTROLLATI[chiave] = calcolata
    return calcolata


def motivo_del_codice_diverso(casa: Path, atteso: dict, ricorda: bool = True) -> str | None:
    radice = casa / CODICE
    voluti = atteso["file"]
    if not radice.is_dir() or radice.is_symlink():
        return "la cartella del codice non c'è più"
    visti: set[str] = set()
    try:
        for cartella, sotto, nomi in os.walk(radice, followlinks=False):
            for nome_sotto in list(sotto):
                percorso = Path(cartella) / nome_sotto
                if nome_sotto == "__pycache__":
                    shutil.rmtree(percorso, ignore_errors=True)
                    sotto.remove(nome_sotto)
                elif percorso.is_symlink():
                    return f"«{percorso.relative_to(radice).as_posix()}» è un collegamento"
            for nome in nomi:
                percorso = Path(cartella) / nome
                relativo = percorso.relative_to(radice).as_posix()
                if percorso.is_symlink():
                    return f"«{relativo}» è un collegamento"
                if relativo in voluti:
                    visti.add(relativo)
                    if _impronta_ricordata(percorso, ricorda) != voluti[relativo]:
                        return f"«{relativo}» è diverso da quello scaricato"
                elif nome.lower().endswith(PUO_ESSERE_IMPORTATO):
                    return f"«{relativo}» non doveva esserci"
    except OSError:
        return "il codice non si lascia leggere"
    mancanti = sorted(set(voluti) - visti)
    if mancanti:
        return f"manca «{mancanti[0]}»"
    return None


def spiega_il_codice_diverso(motivo: str, di_cosa: str) -> str:
    return (f"Il codice scaricato per {di_cosa} non è più quello previsto ({motivo}): "
            "per sicurezza non lo uso. Riscarica il modello dalle impostazioni e riprova.")


def metti_il_codice_in_fondo(casa: Path) -> str:
    codice = str(casa / CODICE)
    if codice not in sys.path:
        sys.path.append(codice)
        importlib.invalidate_caches()
    return codice


@contextlib.contextmanager
def senza_scrivere_bytecode() -> Iterator[None]:
    prima = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        yield
    finally:
        sys.dont_write_bytecode = prima


def moduli_fuori_dal_codice(moduli: Iterable, casa: Path) -> list[str]:
    radice = (casa / CODICE).resolve()
    fuori = []
    for modulo in moduli:
        dove_sta = getattr(modulo, "__file__", None)
        if not dove_sta or not Path(dove_sta).resolve().is_relative_to(radice):
            fuori.append(getattr(modulo, "__name__", "?"))
    return fuori


def butta_i_moduli_di_un_altro_posto(prefisso: str = "src") -> None:
    for nome in [n for n in sys.modules if n == prefisso or n.startswith(prefisso + ".")]:
        sys.modules.pop(nome, None)


def impronta(file: Path) -> str:
    calcolo = hashlib.sha256()
    with open(file, "rb") as dentro:
        for pezzo in iter(lambda: dentro.read(4 * 1024 * 1024), b""):
            calcolo.update(pezzo)
    return calcolo.hexdigest()


def byte_circa(nome: str = "seedvr2") -> int:
    return sum(int(p.get("byte_circa") or 0) for p in manifesto(nome)["pesi"])


def controlla_lo_spazio(cartella_modelli: Path, nome: str = "seedvr2") -> None:
    posto = Path(cartella_modelli)
    while not posto.exists() and posto.parent != posto:
        posto = posto.parent
    try:
        libero = shutil.disk_usage(posto).free
    except OSError:
        return
    casa = dove(cartella_modelli, nome) / PESI
    manca = sum(int(p.get("byte_circa") or 0) for p in manifesto(nome)["pesi"]
                if not (casa / p["nome"]).is_file())
    arrivati = quanto_pesa(dove(cartella_modelli, nome).with_name(nome + ".nuova") / PESI)
    serve = MARGINE + max(0, manca - arrivati)
    if libero < serve:
        raise ScaricamentoFallito(
            f"Sul disco dei modelli servono circa {serve / 2 ** 30:.0f} GB liberi e "
            f"ce ne sono {libero / 2 ** 30:.1f}. Libera spazio e riprova.")


def _leggi_dalla_rete(indirizzo: str) -> bytes:
    import urllib.request

    with urllib.request.urlopen(indirizzo, timeout=60) as risposta:
        return risposta.read()


def _peso_da_hf(repo: str, nome: str, cartella: Path, chiave: str | None,
                revisione: str | None = None) -> Path:
    from huggingface_hub import hf_hub_download

    return Path(hf_hub_download(repo_id=repo, filename=nome, revision=revisione,
                                local_dir=str(cartella), token=chiave or None))


def _impronta_su_hf(voce) -> str | None:
    lfs = getattr(voce, "lfs", None)
    if not lfs:
        return None
    return lfs.get("sha256") if isinstance(lfs, dict) else getattr(lfs, "sha256", None)


def revisione_con_l_impronta(repo: str, nome: str, voluta: str, chiave: str | None,
                             quante: int = 40) -> str | None:
    from huggingface_hub import HfApi

    api = HfApi()
    try:
        storia = [c.commit_id for c in api.list_repo_commits(repo, token=chiave or None)][:quante]
    except Exception:
        registro.avviso("miglioria.storia_non_letta")
        return None
    for revisione in storia:
        try:
            voci = api.get_paths_info(repo, [nome], revision=revisione, token=chiave or None)
        except Exception:
            registro.avviso("miglioria.storia_non_letta")
            return None
        if any(getattr(v, "path", "") == nome and _impronta_su_hf(v) == voluta for v in voci):
            return revisione
    raise ScaricamentoFallito(
        f"Su Hugging Face «{nome}» non è più quello controllato e non trovo la versione "
        "giusta: non lo scarico, così non aspetti per niente. Riprova più tardi o "
        "aggiorna il programma.")


def _pesi_fissati(atteso: dict, gia: Iterable[Path],
                  chiave: str | None) -> Callable[[str, str, Path, str | None], Path]:
    gia = tuple(gia)
    impronte = {(p["repo"], p["nome"]): p["sha256"] for p in atteso["pesi"]}
    revisioni: dict[tuple[str, str], str | None] = {}
    for (repo, nome), voluta in impronte.items():
        if not any((cartella / nome).is_file() for cartella in gia):
            revisioni[repo, nome] = revisione_con_l_impronta(repo, nome, voluta, chiave)

    def prendi(repo: str, nome: str, cartella: Path, chiave: str | None) -> Path:
        if (repo, nome) not in revisioni:
            revisioni[repo, nome] = revisione_con_l_impronta(repo, nome, impronte[repo, nome],
                                                             chiave)
        return _peso_da_hf(repo, nome, cartella, chiave, revisioni[repo, nome])

    return prendi


def scarica(cartella_modelli: Path, nome: str = "seedvr2",
            al_passo: Callable[[str], None] | None = None,
            chiave: str | None = None,
            prendi_testo: Callable[[str], bytes] | None = None,
            prendi_peso: Callable[[str, str, Path, str | None], Path] | None = None,
            a_che_punto: Callable[[int, int], None] | None = None) -> Path:
    atteso = manifesto(nome)
    arrivo = dove(cartella_modelli, nome)
    if e_in_casa(cartella_modelli, nome):
        return arrivo
    controlla_lo_spazio(cartella_modelli, nome)
    prendi_testo = prendi_testo or _leggi_dalla_rete
    di_passo = al_passo or (lambda _testo: None)

    nuova = arrivo.with_name(nome + ".nuova")
    tenere = {f"{PESI}/{p['nome']}" for p in atteso["pesi"]} | {f"{PESI}/.cache"}
    tieni_solo(nuova, tenere)
    (nuova / PESI).mkdir(parents=True, exist_ok=True)
    prima = torcia.con_la_rete_accesa()
    spostati: list[tuple[Path, Path]] = []
    try:
        prendi_peso = prendi_peso or _pesi_fissati(atteso, (arrivo / PESI, nuova / PESI), chiave)
        base = f"{GREZZO}/{atteso['deposito']}/{atteso['commit']}/"
        for numero, (file, voluta) in enumerate(sorted(atteso["file"].items()), 1):
            di_passo(f"codice {numero} di {len(atteso['file'])}")
            try:
                contenuto = prendi_testo(base + file)
            except Exception as errore:
                registro.errore("miglioria.codice_non_scaricato")
                raise ScaricamentoFallito(
                    "Non sono riuscito a scaricare il codice del modello che "
                    "migliora foto e video. Controlla la connessione e riprova.\n"
                    + _dettaglio_tecnico(errore, chiave)) from errore
            if hashlib.sha256(contenuto).hexdigest() != voluta:
                raise ScaricamentoFallito(
                    f"Il file «{file}» scaricato non è quello previsto: non lo "
                    "uso. Riprova più tardi.")
            posto = nuova / CODICE / file
            posto.parent.mkdir(parents=True, exist_ok=True)
            posto.write_bytes(contenuto)

        verificati = _porta_i_pesi(atteso, arrivo, nuova, di_passo, chiave, prendi_peso,
                                   a_che_punto, spostati)
        shutil.rmtree(nuova / PESI / ".cache", ignore_errors=True)
        grandezze = {nome_peso: (nuova / PESI / nome_peso).stat().st_size
                     for nome_peso in verificati}
        (nuova / PRONTO).write_text(json.dumps(
            {"commit": atteso["commit"], "pesi": verificati, "byte": grandezze},
            indent=1), encoding="utf-8")
        _metti_al_posto(nuova, arrivo)
    finally:
        torcia.rimetti_la_rete_com_era(prima)
        if nuova.exists():
            rimetti_i_vecchi(spostati)
            tieni_solo(nuova, tenere)
    registro.evento("miglioria.scaricato", modello=nome)
    return arrivo


def tieni_solo(cartella: Path, voluti: Iterable[str]) -> None:
    if not cartella.is_dir():
        return
    voluti = {v.strip("/") for v in voluti if v.strip("/")}
    for voce in sorted(cartella.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        relativo = voce.relative_to(cartella).as_posix()
        if relativo in voluti or any(relativo.startswith(v + "/") for v in voluti):
            continue
        try:
            if voce.is_dir() and not voce.is_symlink():
                voce.rmdir()
            else:
                voce.unlink()
        except OSError:
            continue
    if not any(f.is_file() for f in cartella.rglob("*")):
        shutil.rmtree(cartella, ignore_errors=True)


def gia_arrivato(posto: Path, *impronte: str | None) -> bool:
    voluti = [i for i in impronte if i]
    if not voluti or not posto.is_file():
        return False
    trovata = impronta(posto)
    return all(trovata == voluta for voluta in voluti)


def _porta_i_pesi(atteso: dict, arrivo: Path, nuova: Path, di_passo, chiave, prendi_peso,
                  a_che_punto, spostati: list | None = None) -> dict[str, str]:
    if a_che_punto is None:
        return _i_pesi(atteso, arrivo, nuova, di_passo, chiave, prendi_peso, spostati)
    totale = sum(int(p.get("byte_circa") or 0) for p in atteso["pesi"])
    with Sorvegliante(nuova / PESI, totale, a_che_punto):
        return _i_pesi(atteso, arrivo, nuova, di_passo, chiave, prendi_peso, spostati)


def _i_pesi(atteso: dict, arrivo: Path, nuova: Path, di_passo, chiave,
            prendi_peso, spostati: list | None = None) -> dict[str, str]:
    spostati = [] if spostati is None else spostati
    verificati: dict[str, str] = {}
    for peso in atteso["pesi"]:
        vecchio = arrivo / PESI / peso["nome"]
        nuovo = nuova / PESI / peso["nome"]
        if vecchio.is_file() and impronta(vecchio) == peso["sha256"]:
            di_passo(f"«{peso['nome']}» c'era già")
            nuovo.unlink(missing_ok=True)
            shutil.move(str(vecchio), str(nuovo))
            spostati.append((vecchio, nuovo))
        elif nuovo.is_file() and impronta(nuovo) == peso["sha256"]:
            di_passo(f"«{peso['nome']}» era già arrivato")
        else:
            di_passo(f"scarico «{peso['nome']}»")
            nuovo.unlink(missing_ok=True)
            try:
                preso = prendi_peso(peso["repo"], peso["nome"], nuova / PESI, chiave)
            except ScaricamentoFallito:
                raise
            except Exception as errore:
                registro.errore("miglioria.peso_non_scaricato")
                raise ScaricamentoFallito(
                    "Non sono riuscito a scaricare i pesi del modello che "
                    "migliora foto e video. Controlla la connessione e riprova.\n"
                    + _dettaglio_tecnico(errore, chiave)) from errore
            if not _e_lo_stesso(Path(preso), nuovo):
                shutil.move(str(preso), str(nuovo))
            di_passo(f"controllo «{peso['nome']}»")
            if impronta(nuovo) != peso["sha256"]:
                nuovo.unlink(missing_ok=True)
                raise ScaricamentoFallito(
                    f"«{peso['nome']}» scaricato non corrisponde all'impronta "
                    "prevista: non lo uso. Riprova più tardi.")
        verificati[peso["nome"]] = peso["sha256"]
    return verificati


def _e_lo_stesso(uno: Path, altro: Path) -> bool:
    try:
        return uno.samefile(altro)
    except OSError:
        return False


def rimetti_i_vecchi(spostati: list[tuple[Path, Path]]) -> None:
    for vecchio, nuovo in reversed(spostati):
        try:
            if nuovo.is_file() and not vecchio.exists():
                vecchio.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(nuovo), str(vecchio))
        except OSError:
            registro.avviso("miglioria.peso_non_rimesso")


def _metti_al_posto(nuova: Path, arrivo: Path) -> None:
    cartelle.metti_al_posto(nuova, arrivo)
