from __future__ import annotations

import shutil
from pathlib import Path

from officina import registro

NOME = "pecore"
CHIAVE_IMPRONTE = "pecore_impronte_tolte"
CHIAVE_CARTA = "modelli_tolti"
GB = 1024 ** 3


def peso(cartella: Path) -> int:
    totale = 0
    for file in Path(cartella).rglob("*"):
        try:
            if file.is_file() and not file.is_symlink():
                totale += file.stat().st_size
        except OSError:
            continue
    return totale


def _togli_la_cartella(dove: Path) -> int:
    if dove.is_symlink():
        registro.avviso("modelli.tolto_collegamento", nome=registro.Parola(NOME))
        return 0
    if not dove.is_dir():
        return 0
    quanto = peso(dove)
    shutil.rmtree(dove, ignore_errors=True)
    rimasto = peso(dove) if dove.exists() else 0
    if rimasto:
        registro.avviso("modelli.tolto_a_meta", nome=registro.Parola(NOME), rimasti=rimasto)
    return max(0, quanto - rimasto)


def _impronte_tolte(archivio) -> int:
    if archivio is None:
        return 0
    quante = archivio.stato(CHIAVE_IMPRONTE, 0)
    if not isinstance(quante, int) or isinstance(quante, bool) or quante <= 0:
        return 0
    archivio.salva_stato(CHIAVE_IMPRONTE, 0)
    return quante


def sgombra(cartella_modelli, archivio=None) -> dict:
    from officina.programma import carta

    liberati = _togli_la_cartella(Path(cartella_modelli) / NOME)
    impronte = _impronte_tolte(archivio)
    scritto = dict(carta.leggi().get(CHIAVE_CARTA) or {})
    voce = dict(scritto.get(NOME) or {})
    if liberati or impronte:
        voce["byte"] = int(voce.get("byte") or 0) + liberati
        voce["impronte"] = int(voce.get("impronte") or 0) + impronte
        scritto[NOME] = voce
        carta.aggiorna(**{CHIAVE_CARTA: scritto})
        registro.evento("modelli.tolto", nome=registro.Parola(NOME), byte=liberati,
                        impronte=impronte)
    return voce


def a_parole(voce: dict | None) -> str:
    voce = voce or {}
    byte = int(voce.get("byte") or 0)
    impronte = int(voce.get("impronte") or 0)
    if not byte and not impronte:
        return ""
    pezzi = []
    if impronte:
        pezzi.append(f"{impronte:,}".replace(",", ".")
                     + (" impronta" if impronte == 1 else " impronte"))
    if byte:
        pezzi.append("la sua cartella dei modelli")
    detto = "Ho cancellato da solo " + " e ".join(pezzi) + " di PE-Core"
    if byte:
        gb = f"{byte / GB:.1f}".replace(".", ",")
        detto += f": sul disco hai {gb} GB liberi in più" if byte >= GB / 10 else (
            f": sul disco hai {max(1, round(byte / 2 ** 20))} MB liberi in più")
    return detto


def da_dire() -> str:
    from officina.programma import carta

    return a_parole((carta.leggi().get(CHIAVE_CARTA) or {}).get(NOME))


__all__ = ["CHIAVE_CARTA", "CHIAVE_IMPRONTE", "NOME", "a_parole", "da_dire", "peso",
           "sgombra"]
