from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable

from officina import registro
from officina.miglioria import scaricamento
from officina.programma import librerie

OGNI_QUANTO = 0.5


def librerie_che_mancano() -> list[str]:
    parti = list(librerie.cosa_manca())
    if librerie.manca_la_miglioria():
        parti.append("miglioria")
    return parti


def e_pronto(cartella_modelli: Path, nome: str = "seedvr2") -> bool:
    if librerie.manca_la_miglioria():
        return False
    if nome == "faceme":
        from officina.miglioria import faceme_pesi

        return faceme_pesi.e_in_casa(Path(cartella_modelli))
    if nome == "lucidflux":
        from officina.miglioria import lucidflux_pesi

        return lucidflux_pesi.e_in_casa(Path(cartella_modelli))
    return scaricamento.e_in_casa(Path(cartella_modelli), nome)


def prepara(cartella_modelli: Path, di: Callable[[str], None],
            a_che_punto: Callable[[int, int], None] | None = None,
            chiave: str | None = None, installatore=None,
            scarica: Callable[..., Path] | None = None,
            nome: str = "seedvr2", titolo: str = "SeedVR2") -> Path:
    parti = librerie_che_mancano()
    if parti:
        installatore = installatore or librerie.Installatore()
        di("Prima scarico le librerie che servono.")
        _col_resoconto(installatore, di, a_che_punto, lambda: installatore.installa(parti))
        di("Le librerie sono pronte.")
    arrivo = (scarica or scaricamento.scarica)(
        Path(cartella_modelli), nome=nome, al_passo=di, chiave=chiave,
        a_che_punto=a_che_punto)
    di(f"{titolo} è in casa, controllato file per file.")
    return arrivo


def _col_resoconto(installatore, di: Callable[[str], None],
                   a_che_punto: Callable[[int, int], None] | None,
                   fai: Callable[[], None]) -> None:
    basta = threading.Event()
    detto = {"ultimo": ""}

    def riporta() -> None:
        stato = installatore.stato
        if stato.detto and stato.detto != detto["ultimo"] and stato.fase != "finito":
            detto["ultimo"] = stato.detto
            di(stato.detto)
        if a_che_punto is not None and stato.totale:
            a_pezzi = getattr(getattr(a_che_punto, "__self__", None), "a_che_punto_a_pezzi", None)
            (a_pezzi or a_che_punto)(stato.fatti, stato.totale)

    def guarda() -> None:
        while not basta.wait(OGNI_QUANTO):
            try:
                riporta()
            except Exception:
                registro.errore("miglioria.resoconto_rotto")

    filo = threading.Thread(target=guarda, name="resoconto", daemon=True)
    filo.start()
    try:
        fai()
    finally:
        basta.set()
        filo.join(timeout=2)
        pulisci = getattr(getattr(a_che_punto, "__self__", None), "senza_numeri", None)
        if pulisci is not None:
            pulisci()
