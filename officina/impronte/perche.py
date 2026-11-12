from __future__ import annotations

from PIL import ImageStat

from officina import registro
from officina.archivio.database import tutti, uno
from officina.descrittori import TIPI, preparazione, pronti, scheda
from officina.errori import DaRifare, FileNonLeggibile
from officina.immagini import fotogrammi as estrattore
from officina.immagini import lettura
from officina.importazione import gruppi
from officina.impronte.motore import _il_file_da_guardare
from officina.modello import file_media, segnalazioni
from officina.sicuro import dall_archivio

QUANTI = 60
FOTOGRAMMI_DI_PROVA = 2
LAVORI = (
    ("volti", "SELECT 1 FROM volti_guardati WHERE scatto_id = ? LIMIT 1",
     segnalazioni.VOLTI_NON_LETTI),
    ("corpi", "SELECT 1 FROM corpi_guardati WHERE scatto_id = ? LIMIT 1",
     segnalazioni.CORPI_NON_LETTI),
    ("scritte", "SELECT 1 FROM scritte_lette WHERE scatto_id = ? LIMIT 1", None))


def _senza_impronta(connessione, nomi: list[str]) -> dict[int, list[str]]:
    trovati: dict[int, list[str]] = {}
    for nome in nomi:
        for riga in tutti(
                connessione,
                "SELECT s.id FROM scatti s WHERE s.fuori_archivio = 0 AND NOT EXISTS ("
                "SELECT 1 FROM impronte i WHERE i.scatto_id = s.id "
                "AND i.descrittore = ? AND i.versione = ?) ORDER BY s.id",
                nome, scheda(nome).versione):
            trovati.setdefault(riga["id"], []).append(nome)
    return trovati


def _c_e(connessione, domanda: str, *valori) -> bool:
    return uno(connessione, domanda, *valori) is not None


def _doppione(connessione, file_id: int | None) -> dict:
    if file_id is None:
        return {"e": False, "con": 0, "deciso": False}
    riga = uno(connessione,
               "SELECT g.firma, (SELECT count(*) FROM doppioni_gruppi a "
               "WHERE a.firma = g.firma) AS quanti, (SELECT 1 FROM doppioni_decisi d "
               "WHERE d.firma = g.firma) AS deciso FROM doppioni_gruppi g "
               "WHERE g.file_id = ? LIMIT 1", file_id)
    if riga is None:
        return {"e": False, "con": 0, "deciso": False}
    return {"e": True, "con": max(riga["quanti"] - 1, 0), "deciso": bool(riga["deciso"])}


def _uno(connessione, scatto_id: int, mancano: list[str], nel_gruppo: str) -> dict:
    scatto = uno(connessione, "SELECT * FROM scatti WHERE id = ?", scatto_id)
    principale = _il_file_da_guardare(file_media.di_scatto(connessione, scatto_id))
    file_id = principale["id"] if principale else None
    nome = uno(connessione, "SELECT nome, presente FROM percorsi WHERE file_id = ? "
               "ORDER BY presente DESC, id LIMIT 1", file_id) if file_id else None
    da_parte = uno(connessione, "SELECT dettaglio FROM segnalazioni WHERE tipo = ? "
                   "AND scatto_id = ? AND risolta = 0", segnalazioni.NON_SI_APRE, scatto_id)
    lavori = {}
    for chiave, domanda, avviso in LAVORI:
        fatto = _c_e(connessione, domanda, scatto_id)
        fermo = bool(avviso) and _c_e(
            connessione, "SELECT 1 FROM segnalazioni WHERE tipo = ? AND scatto_id = ? "
            "AND risolta = 0", avviso, scatto_id)
        lavori[chiave] = "fatto" if fatto else ("messo da parte" if fermo else "non fatto")
    dentro = not nel_gruppo or _c_e(
        connessione, "SELECT 1 FROM scatti s WHERE s.id = ?" + nel_gruppo, scatto_id)
    return {
        "scatto": scatto_id,
        "genere": scatto["genere"],
        "data": scatto["data_locale"],
        "nome": nome["nome"] if nome else None,
        "sul_disco": bool(nome and nome["presente"]),
        "formato": principale["formato"] if principale else None,
        "misura": ((principale["larghezza"], principale["altezza"]) if principale else None),
        "peso": principale["dimensione"] if principale else None,
        "durata_ms": principale["durata_ms"] if principale else None,
        "mancano": mancano,
        "vecchie": uno(connessione, "SELECT count(*) AS q FROM impronte "
                       "WHERE scatto_id = ?", scatto_id)["q"],
        "da_parte": (da_parte["dettaglio"] or "senza motivo") if da_parte else None,
        "nel_gruppo": dentro,
        "lavori": lavori,
        "doppione": _doppione(connessione, file_id),
    }


def prova(archivio, scatto_id: int, lato: int) -> dict:
    try:
        with archivio.lettura() as connessione:
            principale = _il_file_da_guardare(file_media.di_scatto(connessione, scatto_id))
            if principale is None:
                return {"esito": "saltato", "codice": "senza_file"}
            percorso = file_media.da_guardare(connessione, principale["id"])
        if percorso is None:
            return {"esito": "saltato", "codice": "file_non_trovato"}
        fuori = {"dall_archivio": isinstance(percorso, dall_archivio.DallArchivio)}
        with dall_archivio.attento(percorso):
            if principale["genere"] == "immagine":
                immagini = [lettura.copia_di_lavoro(percorso, lato * 4)]
            else:
                resa = estrattore.prendi(percorso, FOTOGRAMMI_DI_PROVA, lato * 4)
                if not resa:
                    return {**fuori, "esito": "saltato",
                            "codice": resa.codice or "video_non_apribile"}
                immagini = [f.immagine for f in resa.fotogrammi]
                fuori["strada"] = resa.strada
            ritagli = sum(len(preparazione.tre_inquadrature(i, lato)) for i in immagini)
            prima = immagini[0]
            luce = ImageStat.Stat(prima.convert("L")).mean[0]
        return {**fuori, "esito": "si_apre" if ritagli else "senza_ritagli",
                "ritagli": ritagli, "modo": prima.mode, "vista": list(prima.size),
                "luce": round(luce, 1)}
    except (DaRifare, FileNonLeggibile) as errore:
        return {"esito": "saltato", "codice": errore.codice}
    except Exception as errore:
        dove = registro.dove_si_e_rotto(errore)
        return {"esito": "rotto", "codice": "errore_imprevisto",
                "guasto": str(dove["guasto"]), "dove": str(dove.get("dove", "")),
                "riga": dove.get("riga"),
                "passi": " > ".join(r.strip() for r in
                                    registro.passi_del_guasto(errore).splitlines()[1:])}


def _peso(byte: int | None) -> str:
    return "?" if byte is None else f"{byte / 1_000_000:.1f} MB"


def _riga(voce: dict) -> str:
    misura = "x".join(str(m) for m in voce["misura"]) if voce["misura"] else "?"
    esito = voce["prova"]
    prova_a_parole = " ".join(f"{c}={v}" for c, v in esito.items())
    doppione = voce["doppione"]
    doppio = (f"si con {doppione['con']}{' deciso' if doppione['deciso'] else ''}"
              if doppione["e"] else "no")
    lavori = " ".join(f"{c}={v}" for c, v in voce["lavori"].items())
    return (f"scatto {voce['scatto']} | {voce['genere']} {voce['formato'] or '?'} "
            f"{misura} {_peso(voce['peso'])} durata_ms={voce['durata_ms'] or 0}"
            f" | nome={voce['nome'] or '?'} data={voce['data'] or '?'}"
            f" sul_disco={'si' if voce['sul_disco'] else 'no'}"
            f" | mancano={','.join(voce['mancano'])} impronte_in_tutto={voce['vecchie']}"
            f" | da_parte={voce['da_parte'] or 'no'}"
            f" nel_gruppo={'si' if voce['nel_gruppo'] else 'no'}"
            f" | {lavori} | doppione={doppio} | prova: {prova_a_parole}")


def guarda(archivio, quanti: int = QUANTI) -> dict:
    nomi = pronti(archivio.dove.modelli)
    if not nomi:
        return {"modelli": [], "in_tutto": 0, "scatti": [], "testo": ""}
    lato = max(scheda(nome).lato for nome in nomi)
    with archivio.lettura() as connessione:
        senza = _senza_impronta(connessione, nomi)
        nel_gruppo = gruppi.clausola(connessione, "intelligenza")
        voci = [_uno(connessione, scatto_id, senza[scatto_id], nel_gruppo)
                for scatto_id in sorted(senza)[:quanti]]
    for voce in voci:
        voce["prova"] = prova(archivio, voce["scatto"], lato)
        esito = voce["prova"]
        registro.evento(
            "impronte.perche_manca", scatto=voce["scatto"],
            esito=registro.Parola(esito["esito"]),
            motivo=registro.Parola(esito.get("codice") or "nessuno"),
            da_parte=registro.Parola(voce["da_parte"] or "no"),
            doppione=voce["doppione"]["e"])
    versioni = ", ".join(f"{nome} {scheda(nome).versione}" for nome in nomi)
    testa = (f"Impronte: {len(senza)} scatti senza impronta. Modelli: {versioni}. "
             f"Tre inquadrature: {tre_inquadrature_accese(archivio)}.")
    testo = "\n".join([testa, *(_riga(voce) for voce in voci)])
    return {"modelli": [t.scheda.nome for t in TIPI if t.scheda.nome in nomi],
            "in_tutto": len(senza), "scatti": voci, "testo": testo}


def tre_inquadrature_accese(archivio) -> str:
    try:
        return "si" if archivio.impostazione("impronte_a_piu_ingrandimenti") else "no"
    except Exception:
        return "?"
