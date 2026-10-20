from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

from officina.archivio.database import tutti, uno
from officina.miglioria import attesa, coda, da_guardare, fedelta, misura, ricomincia, sfida
from officina.modello import scatti
from officina.web.lavori import Lavoro

QUANTI_IN_CODA = 200
QUANTE_FALLITE = 100
QUANTE_DA_RIVEDERE = 5000
QUANTE_A_VISTA = 4
_UN_NOME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,60}$")

NOMI_DEI_MOTORI = {
    "seedvr2": "SeedVR2",
    "lucidflux": "LucidFlux",
    "codeformer": "CodeFormer",
    "faceme": "FaceMe",
    "finto": "finto",
}

FORMATI_CHE_SI_APRONO = {".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                         ".png": "image/png", ".webp": "image/webp"}

UNA_RIGA = ("SELECT m.*, f.genere, f.durata_ms FROM migliorie AS m "
            "JOIN file_media AS f ON f.id = m.file_id ")

copie = Lavoro("le copie da guardare")
_miglioratore = None


def il_miglioratore(archivio):
    global _miglioratore
    if archivio.di_prova:
        from officina.miglioria import lavoro

        if _miglioratore is not None:
            return _miglioratore
        return lavoro.Miglioratore(archivio)
    if _miglioratore is not None and _miglioratore.archivio is not archivio:
        _miglioratore.ferma()
        _miglioratore = None
    if _miglioratore is None:
        from officina.miglioria import lavoro

        _miglioratore = lavoro.Miglioratore(archivio)
    return _miglioratore


def miglioramento_di_la(archivio):
    miglioratore = il_miglioratore(archivio)
    miglioratore.parti()
    return miglioratore.lavoro


def ferma_di_la() -> None:
    if _miglioratore is not None:
        _miglioratore.ferma()


def racconta_di_la() -> dict | None:
    return None if _miglioratore is None else dict(_miglioratore.adesso)


def applica_di_qua(adesso: dict) -> None:
    from officina.archivio import accesso

    il_miglioratore(accesso.aperto()).adesso = dict(adesso)


def misura_a_parole(larghezza, altezza) -> str:
    if not larghezza or not altezza:
        return ""
    return f"{int(larghezza)} × {int(altezza)}"


def _dopo(riga: sqlite3.Row) -> tuple[int, int] | None:
    if riga["larghezza_dopo"] and riga["altezza_dopo"]:
        return int(riga["larghezza_dopo"]), int(riga["altezza_dopo"])
    if riga["larghezza_prima"] and riga["altezza_prima"]:
        return misura.di_arrivo(riga["larghezza_prima"], riga["altezza_prima"],
                                pari=riga["genere"] == "video")
    return None


def motori_a_parole(testo: str | None) -> str:
    try:
        usati = json.loads(testo or "[]")
    except ValueError:
        return ""
    nomi = [NOMI_DEI_MOTORI.get(str(usato.get("nome")), str(usato.get("nome")))
            for usato in usati if isinstance(usato, dict)]
    if not nomi:
        return ""
    if len(nomi) == 1:
        return nomi[0]
    return f"{nomi[0]} · volti: {', '.join(nomi[1:])}"


def a_parole(riga: sqlite3.Row) -> dict:
    from officina.miglioria import lavoro

    dopo = _dopo(riga)
    return {
        "id": riga["id"],
        "file_id": riga["file_id"],
        "scatto_id": riga["scatto_id"],
        "stato": riga["stato"],
        "nome": Path(riga["percorso_originale"]).name,
        "genere": riga["genere"],
        "prima": misura_a_parole(riga["larghezza_prima"], riga["altezza_prima"]),
        "dopo": misura_a_parole(*dopo) if dopo else "",
        "durata": scatti.durata_a_parole(riga["durata_ms"]),
        "guasto": lavoro.a_parole(riga["guasto"]),
        "motori": motori_a_parole(riga["motori"]),
    }


def righe(connessione: sqlite3.Connection, stato: str, quante: int) -> list[dict]:
    return [a_parole(riga) for riga in tutti(
        connessione, UNA_RIGA + "WHERE m.stato = ? ORDER BY m.id LIMIT ?",
        stato, quante)]


def la_coda(archivio) -> dict:
    with archivio.lettura() as connessione:
        al_lavoro = righe(connessione, coda.IN_LAVORO, 1)
        conti = coda.conteggi(connessione)
        aspettano = sfida.aspettano(connessione)
        conti["da_rivedere_ora"] = max(0, conti[coda.DA_RIVEDERE] - len(aspettano))
        return {
            "conti": conti,
            "al_lavoro": al_lavoro[0] if al_lavoro else None,
            "da_guardare": [riga for riga in righe(
                connessione, coda.DA_RIVEDERE, QUANTE_A_VISTA + len(aspettano))
                if riga["id"] not in aspettano][:QUANTE_A_VISTA],
            "in_coda": righe(connessione, coda.IN_CODA, QUANTI_IN_CODA),
            "fallite": righe(connessione, coda.FALLITA, QUANTE_FALLITE),
            "ferme": righe(connessione, coda.IN_SCAMBIO, QUANTE_FALLITE),
        }


def come_va(archivio) -> dict:
    stato = il_miglioratore(archivio).come_va()
    with archivio.lettura() as connessione:
        stato["conti"] = coda.conteggi(connessione)
    return stato


def rimetti(connessione: sqlite3.Connection, miglioria_id: int) -> bool:
    riga = coda.per_id(connessione, miglioria_id)
    if riga is None or riga["stato"] != coda.FALLITA:
        return False
    gia = uno(connessione,
              "SELECT id FROM migliorie WHERE file_id = ? AND stato IN "
              "('in_coda','in_lavoro','da_rivedere','in_scambio','approvata')",
              riga["file_id"])
    if gia is not None:
        return False
    coda.segna(connessione, miglioria_id, coda.IN_CODA, guasto=None,
               finita_il=None)
    return True


def dello_scatto(connessione: sqlite3.Connection, scatto_id: int) -> dict | None:
    riga = uno(connessione,
               "SELECT id, stato FROM migliorie WHERE scatto_id = ? AND stato IN "
               "('in_coda','in_lavoro','da_rivedere','in_scambio','approvata') "
               "ORDER BY id DESC LIMIT 1", scatto_id)
    return dict(riga) if riga is not None else None


def _lati(riga: sqlite3.Row) -> dict[str, Path]:
    return {da_guardare.PRIMA: Path(riga["percorso_originale"]),
            da_guardare.DOPO: Path(riga["in_revisione"] or "")}


def da_rivedere(archivio, saltate: set[int]) -> dict | None:
    with archivio.lettura() as connessione:
        aspettano = sfida.aspettano(connessione)
        tutte = [riga for riga in tutti(
            connessione, UNA_RIGA + "WHERE m.stato = ? ORDER BY m.id LIMIT ?",
            coda.DA_RIVEDERE, QUANTE_DA_RIVEDERE) if riga["id"] not in aspettano]
    if not tutte:
        return None
    restano = [riga for riga in tutte if riga["id"] not in saltate]
    ricominciato = not restano
    riga = (restano or tutte)[0]
    posizione = next(numero for numero, altra in enumerate(tutte, start=1)
                     if altra["id"] == riga["id"])
    originale = Path(riga["percorso_originale"])
    lati = _lati(riga)
    mancano = []
    if riga["genere"] == "video":
        mancano = [lato for lato in da_guardare.LATI
                   if da_guardare.da_mostrare(archivio.dove, riga["id"], lato,
                                              lati[lato]) is None]
    return {
        **a_parole(riga),
        "posizione": posizione,
        "quante": len(tutte),
        "ricominciato": ricominciato,
        "mancano_copie": mancano,
        "ci_sono": all(file.is_file() for file in lati.values()),
        "va_in": str(Path(originale.parent.name) / attesa.ORIGINALI / originale.name),
        "proporzione": _proporzione(riga),
        "fedelta": fedelta.in_parole(riga["fedelta"]),
    }


def _proporzione(riga: sqlite3.Row) -> float:
    dopo = _dopo(riga)
    if dopo and dopo[1]:
        return round(dopo[0] / dopo[1], 5)
    return round(4 / 3, 5)


def file_del_lato(archivio, miglioria_id: int, lato: str) -> tuple[str, Path] | None:
    if lato not in da_guardare.LATI:
        return None
    with archivio.lettura() as connessione:
        riga = uno(connessione, UNA_RIGA + "WHERE m.id = ?", miglioria_id)
    if riga is None or riga["stato"] != coda.DA_RIVEDERE:
        return None
    if lato == da_guardare.DOPO and not riga["in_revisione"]:
        return None
    file = _lati(riga)[lato]
    if not file.is_file():
        return None
    if riga["genere"] == "video":
        mostra = da_guardare.da_mostrare(archivio.dove, miglioria_id, lato, file)
        return ("video", mostra) if mostra is not None else None
    return "immagine", file


def fai_le_copie(archivio, miglioria_id: int) -> bool:
    with archivio.lettura() as connessione:
        riga = uno(connessione, UNA_RIGA + "WHERE m.id = ?", miglioria_id)
    if riga is None or riga["stato"] != coda.DA_RIVEDERE or riga["genere"] != "video":
        return False
    lati = _lati(riga)

    def fai() -> None:
        copie.di(f"preparo la copia da guardare di «{lati[da_guardare.PRIMA].name}»")
        da_guardare.fai(archivio.dove, miglioria_id, lati, al_passo=copie.a_che_punto)
        copie.di("pronta")

    return copie.parti(fai, nome="copie da guardare")


LATI_DELLA_SFIDA = ("sinistra", "destra")


def la_sfida(archivio, pronti: bool) -> dict | None:
    with archivio.lettura() as connessione:
        chiusa = sfida.chiusa(connessione)
        numeri = sfida.conti(connessione)
        in_coda_foto = int(uno(
            connessione,
            "SELECT count(*) AS q FROM migliorie AS m JOIN file_media AS f "
            "ON f.id = m.file_id WHERE m.stato IN (?, ?) AND f.genere = 'immagine'",
            coda.IN_CODA, coda.IN_LAVORO)["q"])
        chiudibile = sfida.si_puo_chiudere(connessione, in_coda_foto)
        salto = sfida.ultimo_salto(connessione)
        in_pausa = sfida.in_pausa(connessione)
        da_riprendere = len(sfida.da_riprendere(connessione)) if pronti else 0
        da_ricominciare = ricomincia.quante(connessione) if pronti else 0
    if chiusa is not None or not (pronti or numeri["fatte"]):
        return None
    return {**numeri, "si_puo_chiudere": chiudibile, "salto": il_salto(salto),
            "in_pausa": in_pausa, "da_riprendere": da_riprendere,
            "pausa_dopo": sfida.PAUSA_DOPO, "da_ricominciare": da_ricominciare,
            "si_riprende": bool(da_riprendere) and not in_pausa,
            "percento": round(100 * numeri["votate"] / sfida.QUANTE)}


def il_salto(salto: dict | None) -> dict | None:
    from officina.miglioria import lavoro

    if not salto:
        return None
    tipo, dove, riga = (str(salto.get(chiave) or "") for chiave in ("tipo", "dove", "riga"))
    tecnico = tipo if _UN_NOME.match(tipo) else ""
    if tecnico and _UN_NOME.match(dove):
        tecnico += f" in {dove}, riga {riga if riga.isdigit() else '?'}"
    return {
        "perche": lavoro.perche_saltata({"guasto": salto.get("codice"),
                                         "spiegazione": salto.get("spiegazione")}),
        "di_fila": max(1, int(salto.get("di_fila") or 1)),
        "tecnico": tecnico,
    }


def quante_da_votare(archivio) -> int:
    with archivio.lettura() as connessione:
        return len(sfida.da_votare(connessione))


def da_votare(archivio) -> dict | None:
    with archivio.lettura() as connessione:
        tutte = sfida.da_votare(connessione)
        numeri = sfida.conti(connessione)
    if not tutte:
        return None
    riga = tutte[0]
    larga, alta = (riga["larghezza_dopo"], riga["altezza_dopo"]) \
        if riga["larghezza_dopo"] and riga["altezza_dopo"] else (4, 3)
    dopo = (misura_a_parole(riga["larghezza_dopo"], riga["altezza_dopo"])
            or misura_a_parole(*misura.di_arrivo(riga["larghezza_prima"] or 1,
                                                 riga["altezza_prima"] or 1)))
    return {
        "id": riga["miglioria_id"],
        "scatto_id": riga["scatto_id"],
        "nome": Path(riga["percorso_originale"]).name,
        "prima": misura_a_parole(riga["larghezza_prima"], riga["altezza_prima"]),
        "dopo": dopo,
        "mancano": len(tutte),
        "votate": numeri["votate"],
        "quante": sfida.QUANTE,
        "lettere": {lato: sfida.lettera_del_lato(riga, lato) for lato in LATI_DELLA_SFIDA},
        "proporzione": round(larga / alta, 5),
        "ci_sono": all(Path(riga[f"percorso_{m}"] or "").is_file()
                       for m in sfida.SFIDANTI)
        and Path(riga["percorso_originale"]).is_file(),
    }


def file_della_sfida(archivio, miglioria_id: int, lato: str) -> Path | None:
    if lato not in LATI_DELLA_SFIDA:
        return None
    with archivio.lettura() as connessione:
        riga = sfida.per_miglioria(connessione, miglioria_id)
        migliorata = coda.per_id(connessione, miglioria_id)
    if riga is None or riga["voto"] is not None or migliorata is None \
            or migliorata["stato"] != coda.DA_RIVEDERE:
        return None
    file = sfida.file_della_lettera(riga, sfida.lettera_del_lato(riga, lato))
    return file if file.is_file() else None


def com_e_andata(archivio) -> dict:
    with archivio.lettura() as connessione:
        numeri = sfida.conti(connessione)
        chiusa = sfida.chiusa(connessione)
    vincitore = sfida.vincitore(numeri)
    return {**numeri, "vincitore": vincitore,
            "nome_vincitore": sfida.NOMI.get(vincitore, ""),
            "nomi": sfida.NOMI, "chiusa": chiusa,
            "barra": {chiave: round(100 * numeri[chiave] / max(1, numeri["votate"]), 1)
                      for chiave in (*sfida.SFIDANTI, "pari", "nessuna")}}
