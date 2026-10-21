from __future__ import annotations

import sqlite3
from pathlib import Path

from officina.archivio.database import tutti, uno
from officina.miglioria import da_guardare
from officina.modello import file_media, scatti
from officina.ritocco import coda, elenco, racconto, sfida_togli
from officina.web import coda_ritocco, lavori
from officina.web.lavori import Lavoro

QUANTI_IN_CODA = 200
QUANTI_NON_RIUSCITI = 100
QUANTI_DA_RIVEDERE = 5000
QUANTI_A_VISTA = 4
CARTELLA = "revisione-ritocco"
PRIMA = da_guardare.PRIMA
DOPO = da_guardare.DOPO
B = "b"
LATI = (*da_guardare.LATI, B)
PARZIALE = ".parziale.mp4"

copie = Lavoro("le copie da guardare del ritocco")


def quanto(secondi) -> str:
    if not secondi:
        return ""
    minuti = round(float(secondi) / 60)
    if minuti < 1:
        return "meno di un minuto"
    if minuti == 1:
        return "circa un minuto"
    if minuti < 90:
        return f"circa {minuti} minuti"
    ore = round(float(secondi) / 3600)
    return "circa un'ora" if ore == 1 else f"circa {ore} ore"


def volte(quante: int) -> str:
    return "1 volta" if quante == 1 else f"{quante} volte"


def _i_file(connessione: sqlite3.Connection, lavoro_id: int) -> list[dict]:
    fuori = []
    for riga in tutti(connessione,
                      "SELECT DISTINCT file_id FROM ritocchi WHERE lavoro_id = ? ORDER BY file_id",
                      lavoro_id):
        media = file_media.per_id(connessione, riga["file_id"])
        if media is None:
            continue
        percorso = file_media.percorso_migliore(connessione, media["id"])
        fuori.append({"id": media["id"], "genere": media["genere"], "ruolo": media["ruolo"],
                      "nome": percorso.name if percorso is not None else "",
                      "durata": scatti.durata_a_parole(media["durata_ms"])})
    fuori.sort(key=lambda file: (file["genere"] == "video", file["id"]))
    return fuori


def finale(file: list[dict]) -> str:
    generi = {voce["genere"] == "video" for voce in file}
    if generi == {True, False}:
        return "i"
    return "o" if generi == {True} else "a"


def _nome(file: list[dict]) -> str:
    if not file:
        return ""
    if finale(file) == "i":
        return f"{file[0]['nome']} con il suo video"
    return file[0]["nome"]


def _quanti_per_file(connessione: sqlite3.Connection, lavoro_id: int, stato: str,
                     genere: str | None = None) -> int:
    riga = uno(connessione,
               "SELECT max(quanti) AS quanti FROM (SELECT count(*) AS quanti FROM ritocchi "
               "WHERE lavoro_id = ? AND stato = ? AND (? IS NULL OR genere = ?) "
               "GROUP BY file_id)", lavoro_id, stato, genere, genere)
    return int(riga["quanti"] or 0) if riga is not None else 0


def _dettaglio(connessione: sqlite3.Connection, riga: sqlite3.Row) -> str:
    pezzi = []
    nuovi = _quanti_per_file(connessione, riga["id"], elenco.IN_CODA, elenco.PIXELA)
    via = _quanti_per_file(connessione, riga["id"], elenco.IN_CODA, elenco.TOGLI)
    tolti = _quanti_per_file(connessione, riga["id"], elenco.TOLTO)
    if nuovi:
        pezzi.append("1 parte da pixelare" if nuovi == 1 else f"{nuovi} parti da pixelare")
    if via:
        pezzi.append("1 cosa da togliere" if via == 1 else f"{via} cose da togliere")
    if tolti:
        pezzi.append("1 ritocco da togliere" if tolti == 1 else f"{tolti} ritocchi da togliere")
    if riga["stato"] in (coda.IN_CODA, coda.IN_LAVORO) and quanto(riga["stima"]):
        pezzi.append(quanto(riga["stima"]))
    if riga["rifatto"]:
        pezzi.append(f"rifatto {volte(riga['rifatto'])}")
    return " · ".join(pezzi)


def _riga(connessione: sqlite3.Connection, riga: sqlite3.Row) -> dict:
    file = _i_file(connessione, riga["id"])
    return {
        "id": riga["id"],
        "scatto_id": riga["scatto_id"],
        "stato": riga["stato"],
        "nome": _nome(file),
        "file_id": file[0]["id"] if file else None,
        "dettaglio": _dettaglio(connessione, riga),
        "guasto": riga["guasto"] or "",
    }


def _righe(connessione: sqlite3.Connection, sql: str, *valori) -> list[dict]:
    return [_riga(connessione, riga) for riga in tutti(connessione, sql, *valori)]


def _cosa_fa(stato: dict, conti: dict, al_lavoro: dict | None) -> dict:
    aspetta = stato.get("in_attesa_della_scheda")
    adesso = stato.get("adesso") or {}
    if stato["sta_lavorando"] and aspetta:
        chi = lavori.NOMI_NEL_TURNO.get(aspetta, aspetta)
        return {"nome": "", "detto": f"Aspetto la scheda video: la sta usando {chi}."}
    if stato["sta_lavorando"] and (adesso.get("nome") or al_lavoro):
        return {"nome": adesso.get("nome") or (al_lavoro or {}).get("nome", ""), "detto": ""}
    if stato["sta_lavorando"]:
        return {"nome": "", "detto": "Sto cominciando."}
    if conti[coda.IN_CODA]:
        return {"nome": "", "detto": "Fermo: premi Avvia. Si ferma quando vuoi, e un video "
                                     "lasciato a metà ricomincia da capo."}
    return {"nome": "", "detto": "Niente in coda. Nei video e nelle foto live si sceglie "
                                 "cosa pixelare con «Ritocca», poi «Metti in coda»."}


def la_pagina(archivio) -> dict:
    stato = coda_ritocco.il_ritoccatore(archivio).come_va()
    with archivio.lettura() as connessione:
        conti = coda.conteggi(connessione)
        in_coda = _righe(connessione,
                         "SELECT * FROM ritocchi_lavori WHERE stato IN (?, ?) "
                         "ORDER BY stato = ? DESC, id LIMIT ?",
                         coda.IN_LAVORO, coda.IN_CODA, coda.IN_LAVORO, QUANTI_IN_CODA)
        da_rivedere = _righe(connessione,
                             "SELECT * FROM ritocchi_lavori WHERE stato = ? ORDER BY id LIMIT ?",
                             coda.DA_RIVEDERE, QUANTI_A_VISTA)
        non_riusciti = _righe(connessione,
                              "SELECT * FROM ritocchi_lavori WHERE stato = ? AND deciso_il IS NULL "
                              "ORDER BY id DESC LIMIT ?", coda.FALLITO, QUANTI_NON_RIUSCITI)
        quanti_non_riusciti = uno(connessione,
                                  "SELECT count(*) AS q FROM ritocchi_lavori "
                                  "WHERE stato = ? AND deciso_il IS NULL", coda.FALLITO)["q"]
        fermi = _righe(connessione,
                       "SELECT * FROM ritocchi_lavori WHERE stato = ? ORDER BY id LIMIT ?",
                       coda.IN_SCAMBIO, QUANTI_NON_RIUSCITI)
    al_lavoro = next((riga for riga in in_coda if riga["stato"] == coda.IN_LAVORO), None)
    return {
        "lavoro": stato,
        "conti": conti,
        "in_coda": in_coda,
        "al_lavoro": al_lavoro,
        "da_rivedere": da_rivedere,
        "non_riusciti": non_riusciti,
        "quanti_non_riusciti": quanti_non_riusciti,
        "fermi": fermi,
        "cosa_fa": _cosa_fa(stato, conti, al_lavoro),
    }


def _cartella(archivio) -> Path:
    return Path(archivio.dove.miniature) / CARTELLA


def _copia(archivio, lavoro: sqlite3.Row, file_id: int, lato: str) -> Path:
    if lato not in LATI:
        raise ValueError(f"lato sconosciuto: {lato!r}")
    return _cartella(archivio) / (f"{int(lavoro['id'])}-{int(lavoro['versione'])}-"
                                  f"{int(file_id)}-{lato}.mp4")


def _lati(connessione: sqlite3.Connection, file_id: int,
          pronto: sqlite3.Row | None) -> dict[str, Path | None]:
    lati = _prima_e_dopo(connessione, file_id, pronto)
    sfida = (sfida_togli.del_file(connessione, pronto["lavoro_id"], file_id)
             if pronto is not None else None)
    if sfida is not None and sfida["voto"] is None:
        lati[B] = Path(sfida["pronta_b"]) if sfida["pronta_b"] else None
    return lati


def _prima_e_dopo(connessione: sqlite3.Connection, file_id: int,
                  pronto: sqlite3.Row | None) -> dict[str, Path | None]:
    prima, _ = file_media.da_mostrare(connessione, file_id)
    if prima is None:
        prima = file_media.percorso_migliore(connessione, file_id)
    if pronto is None:
        dopo = None
    elif pronto["pronta"]:
        dopo = Path(pronto["pronta"])
    else:
        dopo, _ = file_media.da_mostrare_sotto(connessione, file_id)
    return {PRIMA: Path(prima) if prima else None, DOPO: Path(dopo) if dopo else None}


def _da_vedere(archivio, lavoro: sqlite3.Row, file_id: int, lato: str,
               file: Path | None) -> Path | None:
    if file is None or not file.is_file():
        return None
    if da_guardare.si_apre(file):
        return file
    copia = _copia(archivio, lavoro, file_id, lato)
    return copia if copia.is_file() else None


def _proporzione(connessione: sqlite3.Connection, lavoro_id: int, file_id: int) -> float:
    riga = uno(connessione,
               "SELECT larghezza, altezza FROM ritocchi WHERE lavoro_id = ? AND file_id = ? "
               "AND larghezza > 0 AND altezza > 0 ORDER BY id LIMIT 1", lavoro_id, file_id)
    if riga is None:
        riga = uno(connessione,
                   "SELECT larghezza, altezza FROM file_media WHERE id = ? "
                   "AND larghezza > 0 AND altezza > 0", file_id)
    if riga is None:
        return round(4 / 3, 5)
    return round(riga["larghezza"] / riga["altezza"], 5)


def _aperto(connessione: sqlite3.Connection, lavoro_id: int) -> tuple:
    lavoro = coda.per_id(connessione, lavoro_id)
    if lavoro is None or lavoro["stato"] != coda.DA_RIVEDERE:
        return None, []
    return lavoro, _i_file(connessione, lavoro_id)


def da_rivedere(archivio, lavoro_id: int | None, file_id: int | None) -> dict | None:
    with archivio.lettura() as connessione:
        tutte = [riga["id"] for riga in tutti(
            connessione, "SELECT id FROM ritocchi_lavori WHERE stato = ? ORDER BY id LIMIT ?",
            coda.DA_RIVEDERE, QUANTI_DA_RIVEDERE)]
        if not tutte:
            return None
        if lavoro_id in tutte:
            scelto = lavoro_id
        elif lavoro_id is not None:
            scelto = next((numero for numero in tutte if numero > lavoro_id), tutte[0])
        else:
            scelto = tutte[0]
        lavoro, file = _aperto(connessione, scelto)
        if lavoro is None or not file:
            return None
        quale = next((voce for voce in file if voce["id"] == file_id), file[0])
        pronti = {riga["file_id"]: riga for riga in coda.pronti(connessione, scelto)}
        lati = _lati(connessione, quale["id"], pronti.get(quale["id"]))
        sfida = sfida_togli.del_file(connessione, scelto, quale["id"])
        da_votare = len(sfida_togli.da_votare(connessione, scelto))
        votate = (sfida_togli.votate(connessione, sfida["genere"]) if sfida is not None else 0)
        parti = racconto.del_lavoro(connessione, scelto, quale["id"])
        proporzione = _proporzione(connessione, scelto, quale["id"])
    posizione = tutte.index(scelto)
    ci_sono = all(file_lato is not None and file_lato.is_file() for file_lato in lati.values())
    mancano = []
    if ci_sono and quale["genere"] == "video":
        mancano = [lato for lato in lati
                   if _da_vedere(archivio, lavoro, quale["id"], lato, lati[lato]) is None]
    return {
        "id": scelto,
        "scatto_id": lavoro["scatto_id"],
        "nome": quale["nome"],
        "posizione": posizione + 1,
        "quante": len(tutte),
        "precedente": tutte[posizione - 1] if posizione > 0 else None,
        "successiva": tutte[posizione + 1] if posizione + 1 < len(tutte) else None,
        "rifatto": lavoro["rifatto"],
        "guasto": lavoro["guasto"] or "",
        "file": [{**voce, "qui": voce["id"] == quale["id"]} for voce in file],
        "file_id": quale["id"],
        "genere": quale["genere"],
        "proporzione": proporzione,
        "ci_sono": ci_sono,
        "mancano_copie": mancano,
        "parti": parti,
        "finale": finale(file),
        "sfida": (_la_sfida(sfida, votate) if sfida is not None and B in lati else None),
        "da_votare": da_votare,
    }


def _la_sfida(sfida, votate: int) -> dict:
    sinistra = sfida_togli.lettera_del_lato(sfida, "sinistra")
    destra = sfida_togli.lettera_del_lato(sfida, "destra")
    lato = {"A": DOPO, "B": B}
    quante = sfida_togli.QUANTE[sfida["genere"]]
    return {"sinistra": {"lettera": sinistra, "lato": lato[sinistra]},
            "destra": {"lettera": destra, "lato": lato[destra]},
            "quante": quante, "mancano": max(0, quante - votate)}


def file_del_lato(archivio, lavoro_id: int, file_id: int, lato: str) -> tuple[str, Path] | None:
    if lato not in LATI:
        return None
    with archivio.lettura() as connessione:
        lavoro, file = _aperto(connessione, lavoro_id)
        voce = next((voce for voce in file if voce["id"] == file_id), None)
        if lavoro is None or voce is None:
            return None
        pronti = {riga["file_id"]: riga for riga in coda.pronti(connessione, lavoro_id)}
        lati = _lati(connessione, file_id, pronti.get(file_id))
    scelto = lati.get(lato)
    if scelto is None or not scelto.is_file():
        return None
    if voce["genere"] == "video":
        mostra = _da_vedere(archivio, lavoro, file_id, lato, scelto)
        return ("video", mostra) if mostra is not None else None
    return "immagine", scelto


def fai_le_copie(archivio, lavoro_id: int) -> bool:
    with archivio.lettura() as connessione:
        lavoro, file = _aperto(connessione, lavoro_id)
        if lavoro is None:
            return False
        pronti = {riga["file_id"]: riga for riga in coda.pronti(connessione, lavoro_id)}
        da_fare = []
        for voce in file:
            if voce["genere"] != "video":
                continue
            lati = _lati(connessione, voce["id"], pronti.get(voce["id"]))
            for lato in lati:
                sorgente = lati[lato]
                if (sorgente is not None and sorgente.is_file()
                        and _da_vedere(archivio, lavoro, voce["id"], lato, sorgente) is None):
                    da_fare.append((voce, lato, sorgente, _copia(archivio, lavoro, voce["id"],
                                                                 lato)))
    if not da_fare:
        return False

    def fai() -> None:
        for voce, lato, sorgente, arrivo in da_fare:
            copie.di(f"preparo la copia da guardare di «{voce['nome']}»")
            arrivo.parent.mkdir(parents=True, exist_ok=True)
            parziale = arrivo.with_name(arrivo.stem + PARZIALE)
            try:
                da_guardare.ricodifica(sorgente, parziale, al_passo=copie.a_che_punto)
            except BaseException:
                parziale.unlink(missing_ok=True)
                raise
            parziale.replace(arrivo)
        copie.di("pronta")

    return copie.parti(fai, nome="copie da guardare del ritocco")


def togli_le_copie(archivio, lavoro_id: int) -> int:
    cartella = _cartella(archivio)
    if not cartella.is_dir():
        return 0
    tolte = 0
    for file in cartella.iterdir():
        if file.is_file() and file.name.split("-", 1)[0] == str(int(lavoro_id)):
            file.unlink(missing_ok=True)
            tolte += 1
    return tolte


def pulisci(archivio) -> int:
    cartella = _cartella(archivio)
    if not cartella.is_dir():
        return 0
    with archivio.lettura() as connessione:
        tenute = {f"{riga['id']}-{riga['versione']}" for riga in tutti(
            connessione, "SELECT id, versione FROM ritocchi_lavori WHERE stato = ?",
            coda.DA_RIVEDERE)}
    tolte = 0
    for file in cartella.iterdir():
        if not file.is_file() or "-".join(file.name.split("-", 2)[:2]) in tenute:
            continue
        file.unlink(missing_ok=True)
        tolte += 1
    return tolte


def finale_del_lavoro(archivio, lavoro_id: int) -> str:
    with archivio.lettura() as connessione:
        return finale(_i_file(connessione, lavoro_id))
