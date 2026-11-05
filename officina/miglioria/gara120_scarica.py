from __future__ import annotations

import hashlib
import json
import os
import shutil
import tarfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from officina.descrittori.scaricamento import ScaricamentoFallito
from officina.miglioria import gara120_casi as casi_mod
from officina.miglioria import gara120_fonti as fonti

SNU = "snu"
XTEST = "xtest"
ADOBE = "adobe.zip"
CONTROLLATI = "controllati.json"
PARTE = ".parte"
MARGINE = 2 * 2 ** 30
PEZZO = 8 * 2 ** 20
CHI_SONO = "officina-gara120"


@dataclass
class Elenco:
    casi: list
    voci: dict
    veri_nomi: dict
    presenti: dict


def _impronta_di(file: Path) -> str:
    calcolo = hashlib.sha256()
    with open(file, "rb") as dentro:
        for pezzo in iter(lambda: dentro.read(PEZZO), b""):
            calcolo.update(pezzo)
    return calcolo.hexdigest()


def _sbagliato(cosa: str) -> ScaricamentoFallito:
    return ScaricamentoFallito(
        f"{cosa} non è uguale a quello controllato: non lo uso, così la gara resta "
        "pulita. Riprova più tardi o aggiorna il programma.")


def libero(cartella: Path) -> int:
    posto = Path(cartella)
    while not posto.exists() and posto.parent != posto:
        posto = posto.parent
    try:
        return shutil.disk_usage(posto).free
    except OSError:
        return -1


def controlla_lo_spazio(cartella: Path, serve: int) -> None:
    ce = libero(cartella)
    if 0 <= ce < serve + MARGINE:
        raise ScaricamentoFallito(
            f"Per la gara dei 120 FPS servono circa {(serve + MARGINE) / 2 ** 30:.0f} GB "
            f"liberi e ce ne sono {ce / 2 ** 30:.1f}. Libera spazio e riprova.")


class Controllati:

    def __init__(self, cartella: Path) -> None:
        self.file = Path(cartella) / CONTROLLATI
        try:
            self.dati = json.loads(self.file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.dati = {}

    def _segno(self, posto: Path) -> list[int] | None:
        try:
            stato = posto.stat()
        except OSError:
            return None
        return [stato.st_size, stato.st_mtime_ns]

    def buono(self, posto: Path, voluta: str) -> bool:
        segno = self._segno(posto)
        if segno is None:
            return False
        if self.dati.get(str(posto)) == [voluta] + segno:
            return True
        if _impronta_di(posto) != voluta:
            return False
        self.segna(posto, voluta)
        return True

    def segna(self, posto: Path, voluta: str) -> None:
        segno = self._segno(posto)
        if segno is not None:
            self.dati[str(posto)] = [voluta] + segno

    def salva(self) -> None:
        self.file.parent.mkdir(parents=True, exist_ok=True)
        nuovo = self.file.with_name(self.file.name + PARTE)
        nuovo.write_text(json.dumps(self.dati), encoding="utf-8")
        os.replace(nuovo, self.file)


def _api():
    from huggingface_hub import HfApi

    return HfApi()


def _scarica_da_hf(nome: str, cartella: Path) -> Path:
    from huggingface_hub import hf_hub_download

    return Path(hf_hub_download(fonti.SNU_REPO, nome, repo_type="dataset",
                                revision=fonti.SNU_REVISIONE, local_dir=str(cartella),
                                token=False))


def elenco_snu(cartella: Path, api=None, scarica_da_hf=None) -> Elenco:
    api = api or _api()
    scarica_da_hf = scarica_da_hf or _scarica_da_hf
    info = api.dataset_info(fonti.SNU_REPO, revision=fonti.SNU_REVISIONE,
                            files_metadata=True, token=False)
    voci = {}
    for voce in info.siblings or []:
        lfs = getattr(voce, "lfs", None)
        sha = lfs.get("sha256") if isinstance(lfs, dict) else getattr(lfs, "sha256", None)
        if sha:
            voci[voce.rfilename] = (sha, int(voce.size))
    presenti, veri_nomi = casi_mod.presenti_da_nomi(voci)
    tutte = casi_mod.righe_tutte(veri_nomi, voci.__getitem__)
    if casi_mod.impronta("\n".join(tutte)) != fonti.IMPRONTA_TUTTI:
        raise _sbagliato("L'elenco dei fotogrammi di SNU-FILM")
    lista = scarica_da_hf("test-extreme.txt", Path(cartella) / "liste")
    centri = casi_mod.centri_dalla_lista(lista.read_text(encoding="utf-8"))
    casi = casi_mod.piano(sorted(set(centri)), presenti)
    if casi_mod.impronta(casi_mod.testo_casi(casi)) != fonti.IMPRONTA_CASI:
        raise _sbagliato("La scelta dei casi di SNU-FILM")
    righe = casi_mod.righe_file(casi, veri_nomi, voci.__getitem__)
    if casi_mod.impronta("\n".join(righe)) != fonti.IMPRONTA_FILE:
        raise _sbagliato("L'elenco dei fotogrammi della gara")
    return Elenco(casi, voci, veri_nomi, presenti)


def nomi_che_servono(elenco: Elenco, casi: list | None = None) -> list[str]:
    casi = elenco.casi if casi is None else casi
    return sorted({elenco.veri_nomi[(c.scena, n)] for c in casi for n in c.servono()})


def scarica_snu(cartella: Path, elenco: Elenco, nomi: list[str],
                al_file: Callable[[int, int], None] | None = None,
                scarica_da_hf=None) -> None:
    scarica_da_hf = scarica_da_hf or _scarica_da_hf
    casa = Path(cartella) / SNU
    controllati = Controllati(cartella)
    mancano = [n for n in nomi if not controllati.buono(casa / n, elenco.voci[n][0])]
    controlla_lo_spazio(cartella, sum(elenco.voci[n][1] for n in mancano))
    try:
        for fatti, nome in enumerate(mancano, 1):
            posto = scarica_da_hf(nome, casa)
            if _impronta_di(posto) != elenco.voci[nome][0]:
                posto.unlink(missing_ok=True)
                raise _sbagliato(f"Il fotogramma «{nome}»")
            controllati.segna(posto, elenco.voci[nome][0])
            if fatti % 50 == 0:
                controllati.salva()
            if al_file is not None:
                al_file(fatti, len(mancano))
    finally:
        controllati.salva()


def prendi_snu(cartella: Path, elenco: Elenco, scena: str):
    import numpy as np
    from PIL import Image

    casa = Path(cartella) / SNU

    def prendi(numero: int):
        with Image.open(casa / elenco.veri_nomi[(scena, numero)]) as immagine:
            return np.asarray(immagine.convert("RGB"))

    return prendi


def _xvfi_pronto(cartella: Path, controllati: Controllati) -> bool:
    adobe = controllati.buono(Path(cartella) / ADOBE,
                              fonti.DENTRO["Adobe240fps_test_spilt_XVFI.zip"][0])
    return adobe and all(controllati.buono(_mp4(cartella, nome), sha)
                         for nome, sha in fonti.XTEST_MP4.items())


def _mp4(cartella: Path, nome: str) -> Path:
    return Path(cartella) / XTEST / (nome + ".mp4")


def _dalla_rete(indirizzo: str, posto: Path, al_byte=None) -> None:
    import urllib.request

    richiesta = urllib.request.Request(indirizzo, headers={"User-Agent": CHI_SONO})
    letti = 0
    with urllib.request.urlopen(richiesta, timeout=600) as risposta, \
            open(posto, "wb") as uscita:
        while pezzo := risposta.read(PEZZO):
            uscita.write(pezzo)
            letti += len(pezzo)
            if al_byte is not None:
                al_byte(letti, fonti.XVFI_BYTE)


def _copia_controllata(sorgente, posto: Path, voluta: str, cosa: str) -> None:
    calcolo = hashlib.sha256()
    nuovo = posto.with_name(posto.name + PARTE)
    posto.parent.mkdir(parents=True, exist_ok=True)
    with open(nuovo, "wb") as uscita:
        while pezzo := sorgente.read(PEZZO):
            calcolo.update(pezzo)
            uscita.write(pezzo)
    if calcolo.hexdigest() != voluta:
        nuovo.unlink(missing_ok=True)
        raise _sbagliato(cosa)
    os.replace(nuovo, posto)


def scarica_xvfi(cartella: Path, al_byte=None, dalla_rete=None) -> None:
    dalla_rete = dalla_rete or _dalla_rete
    cartella = Path(cartella)
    controllati = Controllati(cartella)
    if _xvfi_pronto(cartella, controllati):
        controllati.salva()
        return
    serve = fonti.XVFI_BYTE + sum(peso for _, peso in fonti.DENTRO.values())
    controlla_lo_spazio(cartella, serve)
    cartella.mkdir(parents=True, exist_ok=True)
    grande = cartella / ("xvfi.zip" + PARTE)
    tar = cartella / ("encoded_test.tar.gz" + PARTE)
    try:
        dalla_rete(fonti.XVFI_INDIRIZZO, grande, al_byte)
        with zipfile.ZipFile(grande) as dentro:
            sha, _ = fonti.DENTRO["Adobe240fps_test_spilt_XVFI.zip"]
            with dentro.open("Adobe240fps_test_spilt_XVFI.zip") as letto:
                _copia_controllata(letto, cartella / ADOBE, sha, "L'archivio di Adobe240")
            controllati.segna(cartella / ADOBE, sha)
            sha, _ = fonti.DENTRO["encoded_test.tar.gz"]
            with dentro.open("encoded_test.tar.gz") as letto:
                _copia_controllata(letto, tar, sha, "L'archivio di X-TEST")
        grande.unlink(missing_ok=True)
        with tarfile.open(tar, mode="r:gz") as pacco:
            for nome, sha in fonti.XTEST_MP4.items():
                voce = pacco.getmember(fonti.XTEST_CARTELLA + nome + ".mp4")
                if not voce.isfile():
                    raise _sbagliato(f"Lo spezzone «{nome}» di X-TEST")
                letto = pacco.extractfile(voce)
                _copia_controllata(letto, _mp4(cartella, nome), sha,
                                   f"Lo spezzone «{nome}» di X-TEST")
                controllati.segna(_mp4(cartella, nome), sha)
    finally:
        grande.unlink(missing_ok=True)
        tar.unlink(missing_ok=True)
        controllati.salva()


def quadri_xtest(cartella: Path, nome: str, numeri) -> dict:
    import av

    voluti = set(numeri)
    presi = {}
    contati = 0
    with av.open(str(_mp4(cartella, nome))) as entrata:
        for numero, quadro in enumerate(entrata.decode(video=0)):
            contati = numero + 1
            if numero in voluti:
                presi[numero] = quadro.to_ndarray(format="rgb24")
    if contati != casi_mod.XTEST_QUADRI or set(presi) != voluti:
        raise _sbagliato(f"Lo spezzone «{nome}» di X-TEST ({contati} fotogrammi)")
    return presi


def cartelle_adobe(cartella: Path) -> dict[str, list[str]]:
    gruppi: dict[str, list[str]] = {}
    with zipfile.ZipFile(Path(cartella) / ADOBE) as dentro:
        for voce in dentro.infolist():
            if not voce.is_dir() and voce.filename.lower().endswith(".png"):
                sopra, _ = voce.filename.rsplit("/", 1)
                gruppi.setdefault(sopra, []).append(voce.filename)
    giusti = {c: sorted(n) for c, n in gruppi.items()
              if len(n) == casi_mod.ADOBE_QUADRI}
    if len(giusti) < casi_mod.QUANTI["adobe"]:
        raise _sbagliato("L'archivio di Adobe240")
    return giusti


def prendi_adobe(cartella: Path, nomi: list[str]):
    import io

    import numpy as np
    from PIL import Image

    def prendi(numero: int):
        with zipfile.ZipFile(Path(cartella) / ADOBE) as dentro:
            dati = dentro.read(nomi[numero])
        with Image.open(io.BytesIO(dati)) as immagine:
            return np.asarray(immagine.convert("RGB"))

    return prendi


def cancella(cartella: Path) -> int:
    cartella = Path(cartella)
    peso = 0
    if cartella.is_dir():
        peso = sum(f.stat().st_size for f in cartella.rglob("*") if f.is_file())
        shutil.rmtree(cartella)
    return peso


__all__ = ["Controllati", "Elenco", "cancella", "cartelle_adobe", "elenco_snu",
           "nomi_che_servono", "prendi_adobe", "prendi_snu", "quadri_xtest",
           "scarica_snu", "scarica_xvfi"]
