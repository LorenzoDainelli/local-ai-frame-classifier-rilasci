from __future__ import annotations

import itertools
import threading
import time
from pathlib import Path
from typing import Callable, Iterable, Iterator

from officina.errori import ErroreOfficina
from officina.miglioria import (centoventi, date, fluido, metadati, misura, motori, pezzi,
                                veloce, video)
from officina.sicuro.dall_archivio import DallArchivio

GIA_GRANDE = "gia_grande"
PER_VOLTA = 41


class TroppoGrande(ErroreOfficina):
    codice = GIA_GRANDE


class Frenato:

    def __init__(self, freno, ogni: float = 1.0):
        self.freno = freno
        self.ogni = ogni
        self._accumulato = 0.0

    def conta(self, secondi: float) -> None:
        if self.freno is None:
            return
        self._accumulato += secondi
        if self._accumulato >= self.ogni:
            self.freno.riposa(self._accumulato)
            self._accumulato = 0.0


def _col_freno(quadri: Iterator, frenato: Frenato) -> Iterator:
    partito = time.monotonic()
    for quadro in quadri:
        frenato.conta(time.monotonic() - partito)
        yield quadro
        partito = time.monotonic()


def _originale(lavoro: dict):
    originale = lavoro["originale"]
    return originale if isinstance(originale, DallArchivio) else Path(originale)


def _date(originale, uscita: Path, lavoro: dict) -> None:
    if isinstance(originale, DallArchivio):
        date.rimetti(uscita, lavoro.get("date") or {})
    else:
        date.copia(originale, uscita)


def esegui(lavoro: dict, al_passo: Callable[[int, int], None] | None = None,
           freno=None, racconta: Callable[[dict], None] | None = None) -> dict:
    if lavoro["genere"] == "immagine":
        return foto(lavoro, al_passo, freno)
    return filmato(lavoro, al_passo, freno, racconta)


def tetto(lavoro: dict) -> str:
    return misura.tetto_vero(lavoro.get("misura"))


def _passaggi(nome: str, larghezza: int, altezza: int, quale: str) -> list:
    arrivo = misura.di_arrivo(larghezza, altezza, tetto=quale)
    if nome != motori.LUCIDFLUX:
        return [(nome, arrivo)]
    prima = misura.di_lucidflux(larghezza, altezza, quale)
    if prima == arrivo:
        return [(nome, arrivo)]
    if prima == (int(larghezza), int(altezza)):
        return [(motori.SEEDVR2, arrivo)]
    return [(nome, prima), (motori.SEEDVR2, arrivo)]


def _un_passaggio(lavoro: dict, nome: str, immagine, larghezza: int, altezza: int,
                  freno, misura_del_motore: dict):
    motore = motori.apri(motori.FOTO, nome, **lavoro.get("opzioni", {}))
    try:
        partito = time.monotonic()
        grande = motore.foto(immagine, larghezza, altezza)
        durata = time.monotonic() - partito
        dove = misura_del_motore if not misura_del_motore else {}
        dove["secondi"] = round(durata, 1)
        if getattr(motore, "dove_stanno", None):
            dove["dove_stanno"] = dict(motore.dove_stanno)
        if dove is not misura_del_motore:
            misura_del_motore["dopo"] = dove
        _riposa(freno, durata)
        usato = {"nome": motore.nome, "versione": motore.versione,
                 "larghezza": larghezza, "altezza": altezza}
    finally:
        motore.spegni()
    if grande.size != (larghezza, altezza):
        from PIL import Image

        grande = grande.resize((larghezza, altezza), Image.Resampling.LANCZOS)
    return grande, usato


def foto(lavoro: dict, al_passo=None, freno=None) -> dict:
    originale = _originale(lavoro)
    uscita = Path(lavoro["uscita"])
    aperta = metadati.apri(originale)
    larghezza, altezza = aperta.immagine.size
    quale = tetto(lavoro)
    if misura.e_gia_grande(larghezza, altezza, quale):
        raise TroppoGrande(f"La foto è già {misura.nome(quale)} o più.")
    passaggi = _passaggi(lavoro["motori"]["foto"], larghezza, altezza, quale)
    nuova_larghezza, nuova_altezza = passaggi[-1][1]
    passi = 2 + len(passaggi)
    _passo(al_passo, 0, passi)

    usati = []
    misura_del_motore = {}
    grande = aperta.immagine
    for numero, (nome, (fino_larghezza, fino_altezza)) in enumerate(passaggi, 1):
        grande, usato = _un_passaggio(lavoro, nome, grande, fino_larghezza,
                                      fino_altezza, freno, misura_del_motore)
        usati.append(usato)
        _passo(al_passo, numero, passi)
    if len(usati) == 1:
        usati[0] = {"nome": usati[0]["nome"], "versione": usati[0]["versione"]}

    volti = lavoro["motori"].get("volti")
    if volti:
        motore_volti = motori.apri(motori.VOLTI, volti, **lavoro.get("opzioni", {}))
        try:
            partito = time.monotonic()
            grande = motore_volti.sistema(grande, lavoro.get("persone", []))
            usati.append({"nome": motore_volti.nome,
                          "versione": motore_volti.versione})
            _riposa(freno, time.monotonic() - partito)
        finally:
            motore_volti.spegni()
    _passo(al_passo, passi - 1, passi)

    metadati.salva(grande, aperta.metadati, uscita,
                   metadati.formato_di(originale), aperta.alfa)
    _date(originale, uscita, lavoro)
    _passo(al_passo, passi, passi)
    return {"larghezza": nuova_larghezza, "altezza": nuova_altezza,
            "motori": usati, **misura_del_motore}


def filmato(lavoro: dict, al_passo=None, freno=None, racconta=None) -> dict:
    originale = _originale(lavoro)
    uscita = Path(lavoro["uscita"])
    piano = video.guarda(originale)
    quale = tetto(lavoro)
    verso = centoventi.arrivo(piano.fps) if lavoro.get("fps120") else None
    grande = misura.e_gia_grande(piano.larghezza, piano.altezza, quale)
    if grande and verso is None:
        raise TroppoGrande(f"Il video è già {misura.nome(quale)} o più.")
    usati: list[dict] = []
    stanno = None
    fatti = None
    scrittore = None
    if grande:
        larghezza = max(2, piano.larghezza - piano.larghezza % 2)
        altezza = max(2, piano.altezza - piano.altezza % 2)
    else:
        larghezza, altezza = misura.di_arrivo(piano.larghezza, piano.altezza, pari=True,
                                              tetto=quale)
        insieme = (verso is None and not isinstance(originale, DallArchivio)
                   and veloce.acceso(lavoro, veloce.SCRITTURA))
        scrittore = _Scrittore(originale, uscita, larghezza, altezza) if insieme else None
        try:
            fatti, usati, stanno = _ingrandisci(
                originale, piano, lavoro, larghezza, altezza, freno, al_passo, racconta,
                al_via=None if scrittore is None else scrittore.parti)
        except BaseException:
            if scrittore is not None:
                scrittore.butta()
            raise
    if verso is None:
        if scrittore is not None and scrittore.partito:
            scrittore.aspetta()
        else:
            _lavora(originale, uscita, larghezza, altezza, fatti.rileggi())
        piu = {}
        if lavoro.get("fps120"):
            usati.append({"nome": centoventi.NOME, "da": str(centoventi.ritmo(piano.fps)),
                          "a": None, "motore": None})
    else:
        piu, del_fluido = _a_centoventi(originale, piano, lavoro, fatti, verso, uscita,
                                        freno, al_passo)
        usati.append({"nome": centoventi.NOME, **piu["fps"], "usati": piu.pop("usati")})
        stanno = stanno or del_fluido
    _date(originale, uscita, lavoro)
    if fatti is not None:
        pezzi.butta(fatti.dove)
    return {"larghezza": larghezza, "altezza": altezza, "motori": usati, **piu,
            **({"dove_stanno": dict(stanno)} if stanno else {})}


def solo_la_scheda(lavoro: dict, al_passo=None, freno=None, racconta=None) -> Path:
    originale = _originale(lavoro)
    piano = video.guarda(originale)
    quale = tetto(lavoro)
    if misura.e_gia_grande(piano.larghezza, piano.altezza, quale):
        raise TroppoGrande(f"Il video è già {misura.nome(quale)} o più.")
    larghezza, altezza = misura.di_arrivo(piano.larghezza, piano.altezza, pari=True,
                                          tetto=quale)
    fatti, _usati, _stanno = _ingrandisci(originale, piano, lavoro, larghezza, altezza,
                                          freno, al_passo, racconta)
    return fatti.dove


def _lavora(originale, uscita: Path, larghezza: int, altezza: int,
            migliorati: Iterator) -> None:
    def rifatti(quadri: Iterable) -> Iterator:
        for _quadro, fatto in zip(quadri, migliorati, strict=True):
            yield fatto

    video.lavora(originale, uscita, larghezza, altezza, rifatti)


class _Scrittore:

    def __init__(self, originale, uscita: Path, larghezza: int, altezza: int) -> None:
        self.originale = originale
        self.uscita = uscita
        self.misura = (larghezza, altezza)
        self.segnale = veloce.Segnale()
        self.partito = False
        self._filo: threading.Thread | None = None
        self._errore: BaseException | None = None

    def parti(self, fatti: pezzi.Pezzi) -> None:
        fatti.segnale = self.segnale
        self.partito = True
        self._filo = threading.Thread(target=self._scrivi, args=(fatti,), daemon=True,
                                      name="miglioria-scrive-il-video")
        self._filo.start()

    def _scrivi(self, fatti: pezzi.Pezzi) -> None:
        try:
            _lavora(self.originale, self.uscita, *self.misura, fatti.segui())
        except BaseException as errore:
            self._errore = errore

    def aspetta(self) -> None:
        self.segnale.avvisa()
        if self._filo is not None:
            self._filo.join()
        if self._errore is not None:
            raise self._errore

    def butta(self) -> None:
        self.segnale.ferma()
        if self._filo is not None:
            self._filo.join()
        if self.partito:
            self.uscita.unlink(missing_ok=True)


def _ingrandisci(originale, piano, lavoro: dict, larghezza: int, altezza: int, freno,
                 al_passo, racconta, al_via=None):
    motore = motori.apri(motori.VIDEO, lavoro["motori"]["video"],
                         **lavoro.get("opzioni", {}))
    stanno = None
    try:
        fatti = pezzi.Pezzi(pezzi.cartella(Path(lavoro["uscita"])),
                            _firma(originale, motore, larghezza, altezza))
        if al_via is not None:
            al_via(fatti)
        if not fatti.finito:
            _fai_i_pezzi(originale, piano, motore, fatti, larghezza, altezza,
                         Frenato(freno), al_passo, racconta,
                         veloce.acceso(lavoro, veloce.SCRITTURA))
            stanno = getattr(motore, "dove_stanno", None)
    finally:
        motore.spegni()
    return fatti, [{"nome": motore.nome, "versione": motore.versione}], stanno


def _a_centoventi(originale, piano, lavoro: dict, fatti, verso, uscita: Path, freno,
                  al_passo) -> tuple[dict, dict | None]:
    nome = str(lavoro["fps120"])
    codec = video.codec_di_arrivo(piano.codec)
    opzioni = dict(video.OPZIONI[codec])
    motore = fluido.Motore(nome, deposito=uscita.parent, **lavoro.get("opzioni", {}))
    stanno = None
    try:
        sorgente = (dict(fatti.firma) if fatti is not None
                    else _firma(originale, motore, piano.larghezza, piano.altezza))
        tratti = fluido.Tratti(
            fluido.cartella(uscita),
            {"sorgente": sorgente, "fluido": motore.firma(), "verso": str(verso),
             "codec": codec, "opzioni": opzioni},
            codec, opzioni, verso)
        entrati = fatti.fatti() if fatti is not None else piano.fotogrammi

        def apri(da: int) -> Iterator:
            quadri = fatti.rileggi() if fatti is not None else video.dritti(originale)
            return itertools.islice(quadri, int(da), None)

        frenato = Frenato(freno)
        fluido.fai(motore, apri, piano.fps, verso, tratti, entrati, al_passo,
                   filtro=lambda quadri: _col_freno(quadri, frenato),
                   dietro=veloce.acceso(lavoro, veloce.SCRITTURA))
        stanno = motore.dove_stanno()
        foglio = motore.foglio()
        usati = motore.usati()
    finally:
        motore.spegni()
    video.unisci_tratti(originale, uscita, tratti.file())
    pezzi.butta(tratti.dove)
    return {"usati": usati,
            "fps": {"da": str(centoventi.ritmo(piano.fps)), "a": str(verso),
                    "motore": nome, **({"foglio": foglio} if foglio else {})}}, stanno


def _firma(originale, motore, larghezza: int, altezza: int) -> dict:
    stato = originale.stat()
    proprie = getattr(motore, "firma", None)
    nome = originale.blake2b if isinstance(originale, DallArchivio) else str(originale)
    return {"originale": nome, "byte": stato.st_size, "larghezza": larghezza,
            "altezza": altezza,
            "motore": proprie() if callable(proprie) else
            {"nome": motore.nome, "versione": motore.versione}}


def _fai_i_pezzi(originale: Path, piano, motore, fatti: pezzi.Pezzi, larghezza: int,
                 altezza: int, frenato: Frenato, al_passo, racconta,
                 dietro: bool = False) -> None:
    per_volta = int(getattr(motore, "quadri_per_volta", PER_VOLTA))
    gia = fatti.fatti()
    if gia % per_volta:
        fatti.segna_finito()
        return
    totale = max(piano.fotogrammi, gia)
    _passo(al_passo, gia, totale)
    inizio = [gia]

    def al_pezzo(frazione: float, quanti: int) -> None:
        _passo(al_passo, inizio[0] + min(quanti - 1, int(frazione * quanti)),
               max(totale, inizio[0] + quanti))

    mucchio: list = []
    fondo = veloce.Fondo(1, acceso=dietro)

    def metti_via() -> None:
        fondo.metti(fatti.salva, veloce.peso_di(mucchio), inizio[0], list(mucchio))
        inizio[0] += len(mucchio)
        mucchio.clear()
        _passo(al_passo, inizio[0], max(totale, inizio[0]))
        tempi = getattr(motore, "tempi", None)
        if racconta is not None and tempi:
            racconta({"tempi": tempi[-1], "fatti": inizio[0], "totale": totale})

    usciti = motore.video(video.dritti(originale), larghezza, altezza, salta=gia,
                          al_pezzo=al_pezzo)
    try:
        for quadro in _col_freno(usciti, frenato):
            mucchio.append(quadro)
            if len(mucchio) >= per_volta:
                metti_via()
        if mucchio:
            metti_via()
        fondo.fine()
    finally:
        fondo.butta()
    fatti.segna_finito()


def _passo(al_passo, fatti: int, totale: int) -> None:
    if al_passo is not None:
        al_passo(fatti, totale)


def _riposa(freno, secondi: float) -> None:
    if freno is not None:
        freno.riposa(secondi)
