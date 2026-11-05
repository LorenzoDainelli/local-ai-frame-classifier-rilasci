from __future__ import annotations

import shutil
from pathlib import Path

from officina import registro

NOME = "pecore"
CHIAVE_IMPRONTE = "pecore_impronte_tolte"
CHIAVE_CARTA = "modelli_tolti"
CHIAVE_DA_COMPATTARE = "impronte_da_compattare"
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


def togli_le_superate(archivio, cartella_modelli) -> dict:
    from officina import descrittori
    from officina.modello import impronte as magazzino
    from officina.programma import carta

    tolte = {}
    for vecchio, nuovo in descrittori.SUPERATI.items():
        if descrittori.superato_da(vecchio, Path(cartella_modelli)) != nuovo:
            continue
        versione = descrittori.scheda(nuovo).versione
        with archivio.scrittura() as connessione:
            fatte = connessione.execute(
                "SELECT count(*) FROM impronte WHERE descrittore = ? AND versione = ?",
                (nuovo, versione)).fetchone()[0]
            if not fatte or magazzino.quanti_da_fare(connessione, nuovo, versione):
                continue
            byte = connessione.execute(
                "SELECT coalesce(sum(dimensione), 0) * 4 FROM impronte "
                "WHERE descrittore = ?", (vecchio,)).fetchone()[0]
            quante = magazzino.togli_di(connessione, vecchio)
        if not quante:
            continue
        tolte[vecchio] = {"impronte": quante, "byte": int(byte), "da": nuovo}
        registro.evento("impronte.superate_tolte", nome=registro.Parola(vecchio),
                        impronte=quante, byte=int(byte))
    if tolte:
        scritto = dict(carta.leggi().get(CHIAVE_CARTA) or {})
        for vecchio, voce in tolte.items():
            prima = dict(scritto.get(vecchio) or {})
            scritto[vecchio] = {
                "impronte": int(prima.get("impronte") or 0) + voce["impronte"],
                "byte_impronte": int(prima.get("byte_impronte") or 0) + voce["byte"],
                "da": voce["da"]}
        da_compattare = list(carta.leggi().get(CHIAVE_DA_COMPATTARE) or [])
        da_compattare += [nome for nome in tolte if nome not in da_compattare]
        carta.aggiorna(**{CHIAVE_CARTA: scritto, CHIAVE_DA_COMPATTARE: da_compattare})
    return tolte


def _peso_del_database(file: Path) -> int:
    totale = 0
    for dove in (file, file.with_name(file.name + "-wal")):
        try:
            totale += dove.stat().st_size
        except OSError:
            continue
    return totale


def _ram_libera() -> int | None:
    from officina.miglioria.seedvr2_blocchi import ram_libera

    return ram_libera()


def compatta_se_serve(archivio, ram=_ram_libera, disco=shutil.disk_usage) -> int:
    from officina.programma import carta

    nomi = [nome for nome in (carta.leggi().get(CHIAVE_DA_COMPATTARE) or [])
            if isinstance(nome, str)]
    if not nomi:
        return 0
    file = Path(archivio.dove.database)
    prima = _peso_del_database(file)
    libera = ram()
    try:
        libero = disco(file.parent).free
    except OSError:
        libero = 0
    if libera is None or libera < 2 * prima or libero < prima + GB:
        registro.avviso("impronte.compattare_rimandato", byte=prima)
        return 0
    archivio.compatta()
    liberati = max(0, prima - _peso_del_database(file))
    scritto = dict(carta.leggi().get(CHIAVE_CARTA) or {})
    voce = dict(scritto.get(nomi[0]) or {})
    voce["byte_liberati"] = int(voce.get("byte_liberati") or 0) + liberati
    scritto[nomi[0]] = voce
    carta.aggiorna(**{CHIAVE_CARTA: scritto, CHIAVE_DA_COMPATTARE: []})
    registro.evento("impronte.compattate", byte=liberati)
    return liberati


def _gb(byte: int) -> str:
    if byte >= GB / 10:
        return f"{byte / GB:.1f}".replace(".", ",") + " GB"
    return f"{max(1, round(byte / 2 ** 20))} MB"


def superate_a_parole(nome: str, voce: dict | None) -> str:
    from officina import descrittori

    voce = voce or {}
    impronte = int(voce.get("impronte") or 0)
    if not impronte:
        return ""
    vecchio = descrittori.SCHEDE[nome].titolo if nome in descrittori.SCHEDE else nome
    nuovo = voce.get("da") or ""
    if nuovo in descrittori.SCHEDE:
        nuovo = descrittori.SCHEDE[nuovo].titolo
    detto = (f"Le impronte nuove di {nuovo} sono finite, quindi ho cancellato da solo "
             + f"{impronte:,}".replace(",", ".")
             + (" impronta vecchia" if impronte == 1 else " impronte vecchie")
             + f" di {vecchio}")
    liberati = int(voce.get("byte_liberati") or 0)
    byte = int(voce.get("byte_impronte") or 0)
    if liberati:
        detto += f": sul disco hai {_gb(liberati)} liberi in più"
    elif byte:
        detto += f": occupavano {_gb(byte)}"
    return detto + f". {vecchio} resta per i vestiti."


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


def da_dire_superate(nome: str) -> str:
    from officina.programma import carta

    return superate_a_parole(nome, (carta.leggi().get(CHIAVE_CARTA) or {}).get(nome))


__all__ = ["CHIAVE_CARTA", "CHIAVE_DA_COMPATTARE", "CHIAVE_IMPRONTE", "NOME", "a_parole",
           "compatta_se_serve", "da_dire", "da_dire_superate", "peso", "sgombra",
           "superate_a_parole", "togli_le_superate"]
