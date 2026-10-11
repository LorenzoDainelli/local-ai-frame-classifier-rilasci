from __future__ import annotations

import ipaddress
import re
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import Request
from fastapi.templating import Jinja2Templates
from markupsafe import Markup

from officina import forziere, registro
from officina.archivio import accesso, memoria
from officina.archivio.database import uno
from officina.doppioni import decisioni as doppioni_decisioni
from officina.modello import etichette, scatti, segnalazioni
from officina.web import giro, sfoglia
from officina.web import telefono as telefono_web
from officina.modello.scatti import Filtro
from officina.web import in_prova, vista
from officina import istruzioni
from officina.programma import aspetto, novita


CARTELLA = Path(__file__).parent.parent
pagine = Jinja2Templates(directory=str(CARTELLA / "templates"))

pagine.env.filters["numero"] = vista.numero_a_parole
pagine.env.filters["senza_regole"] = vista.senza_regole
pagine.env.filters["maiuscola"] = lambda testo: (testo[:1].upper() + testo[1:]) if testo else testo
pagine.env.filters["righe_del_pannello"] = lambda dentro: Markup(
    re.sub(r"<p(?:\s[^>]*)?>", '<span class="pannello-riga">', str(dentro)).replace("</p>", "</span>"))
FOGLI_DELLE_SCHERMATE = (
    "comune",
    "benvenuto",
    "miglioramento",
    "galleria",
    "scatto",
    "importazione",
    "telefono",
    "misura",
    "stato",
    "etichetta",
    "impostazioni",
    "albero",
    "persone",
    "luoghi",
    "schermo",
    "doppioni",
    "aspetto",
    "lavoro",
    "sistemare",
    "senza_data",
    "intelligenza",
)
pagine.env.globals["fogli_delle_schermate"] = FOGLI_DELLE_SCHERMATE
pagine.env.globals["istruzioni_motori"] = istruzioni.motori_in_una_riga
_novita_aperte = threading.Event()


def comune(richiesta: Request, qui: str = "") -> dict:
    archivio = accesso.aperto()
    with archivio.lettura() as connessione:
        conti_barra = conti_della_barra(connessione)
    quanti_scatti = conti_barra["totale"]
    prova = in_prova.adesso() if archivio.di_prova else None
    vere = aspetto.leggi()
    scelte = {**vere, **prova.scelte} if prova else vere
    da_leggere = novita.da_leggere()
    apri_le_novita = bool(da_leggere) and not prova and not _novita_aperte.is_set()
    if apri_le_novita:
        _novita_aperte.set()
    return {
        "request": richiesta,
        "qui": qui,
        "aspetto": scelte,
        "aspetto_vero": vere,
        "sto_provando": prova,
        "attributi_aspetto": aspetto.attributi_html(scelte),
        "novita_da_leggere": len(da_leggere),
        "novita_voci": novita.per_la_pagina(da_leggere),
        "novita_apri": apri_le_novita,
        "impostazioni": archivio.tutte_le_impostazioni(),
        "archivio_nome": archivio.dove.nome,
        "totale_scatti": quanti_scatti,
        "barra": barra_di_navigazione(qui, quanti_scatti, conti_barra),
        "voce_attiva": _DOVE_STA.get(qui, ""),
        "da_guardare": conti_barra["da_guardare"],
        "giro": giro.stato,
        "giro_passo": giro.stato.passo_adesso(),
        "giro_quanti": len(giro.PASSI),
        "giro_tasti": giro.TASTI_DA_RICORDARE,
        "forziere_acceso": forziere.per(archivio.dove).acceso,
        "travaso": (telefono_web.in_corso.come_va()
                    if telefono_web.in_corso.lavoro.sta_lavorando else None),
        "si_puo_sfogliare": (
            bool(richiesta.client)
            and ipaddress.ip_address(richiesta.client.host).is_loopback
            and not dal_portatile()
            and sfoglia.si_puo()),
        "aspetta_il_portatile": (
            bool(richiesta.client)
            and ipaddress.ip_address(richiesta.client.host).is_loopback
            and not dal_portatile()
            and la_porta().aperta),
    }


_DOVE_STA = {
    "galleria": "foto",
    "persone": "foto",
    "luoghi": "foto",
    "scatto": "foto",
    "lavoro": "officina",
    "officina": "officina",
    "importazione": "officina",
    "intelligenza": "officina",
    "sistemare": "officina",
    "elenchi": "officina",
    "doppioni": "officina",
    "miglioramento": "officina",
    "senza-data": "officina",
    "albero": "archivio",
    "stato": "archivio",
    "banco": "archivio",
    "impostazioni": "impostazioni",
    "telefono": "collegamenti",
    "sincronia": "collegamenti",
    "fuori": "collegamenti",
}


_conti_tenuti = memoria.Ricordo("i conti della barra")


def conti_della_barra(connessione) -> dict:
    return _conti_tenuti.prendi(connessione, lambda: _conta_la_barra(connessione))


def _conta_la_barra(connessione) -> dict:
    def quanti(sql: str) -> int:
        riga = uno(connessione, sql)
        return riga["q"] if riga else 0

    non_importati = quanti("SELECT count(*) AS q FROM non_importati")
    coppie = quanti("SELECT count(*) AS q FROM segnalazioni "
                    "WHERE tipo = 'coppia_incerta' AND risolta = 0")
    spariti = quanti(
        "SELECT count(DISTINCT p.file_id) AS q FROM percorsi p "
        "WHERE p.presente = 0 AND NOT EXISTS (SELECT 1 FROM percorsi q "
        "WHERE q.file_id = p.file_id AND q.presente = 1)")

    messi_da_parte = segnalazioni.quante(connessione, segnalazioni.NON_SI_APRE)

    return {
        "totale": quanti("SELECT count(*) AS q FROM scatti WHERE fuori_archivio = 0"),
        "persone": quanti("SELECT count(*) AS q FROM persone WHERE stato = 'attiva'"),
        "luoghi": quanti("SELECT count(*) AS q FROM posti WHERE stato = 'attivo'"),
        "senza_etichetta": etichette.quanti_senza_etichetta(connessione),
        "da_rivedere": quanti("SELECT count(*) AS q FROM migliorie "
                              "WHERE stato = 'da_rivedere'"),
        "da_guardare": (non_importati + coppie + spariti + messi_da_parte
                        + scatti.conta(connessione, Filtro(senza_data=True))),
        "doppioni": doppioni_decisioni.il_conto(connessione)["restano"],
    }


def barra_di_navigazione(qui: str, totale_scatti: int, conti: dict) -> list[dict]:
    voce_attiva = _DOVE_STA.get(qui, "")

    def stanza(dove: str, nome: str, icona: str, conto: int | None = None,
               chiama: bool = False, tasto: str = "") -> dict:
        return {"dove": dove, "nome": nome, "icona": icona, "conto": conto,
                "chiama": bool(chiama and conto), "tasto": tasto,
                "qui": (dove == qui or dove.lstrip("/") == qui
                        or (dove == "/" and qui == "galleria")
                        or (dove == "/sistemare" and qui in ("doppioni", "elenchi", "senza-data")))}

    def sezione(chiave: str, nome: str, icona: str, dove: str, stanze: list[dict]) -> dict:
        return {"chiave": chiave, "nome": nome, "icona": icona, "dove": dove,
                "qui": voce_attiva == chiave, "stanze": stanze,
                "chiama": any(s["chiama"] for s in stanze)}

    foto = [
        stanza("/", "Galleria", "foto", totale_scatti),
        stanza("/persone", "Persone", "persone", conti["persone"]),
        stanza("/luoghi", "Luoghi", "luoghi", conti["luoghi"]),
    ]
    da_sistemare = conti["da_guardare"] + conti.get("doppioni", 0)
    lavoro_stanze = [
        stanza("/importazione", "Aggiungi scatti", "aggiungi"),
        stanza("/intelligenza", "Intelligenza artificiale", "chip"),
        stanza("/sistemare", "Da sistemare", "controlla", da_sistemare or None,
               chiama=True),
        stanza("/officina", "Etichetta", "etichetta", conti["senza_etichetta"]),
        stanza("/miglioramento", "Miglioramento", "migliora", conti["da_rivedere"] or None,
               chiama=True),
    ]
    archivio_stanze = [
        stanza("/albero", "Albero dei nodi", "albero", tasto="A"),
        stanza("/stato", "Stato", "stato"),
    ]
    collegamenti = [
        stanza("/fuori", "Dispositivi", "telefono"),
    ]
    return [
        sezione("foto", "Foto", "foto", "/", foto),
        sezione("officina", "Lavoro", "etichetta", "/lavoro", lavoro_stanze),
        sezione("archivio", "Archivio", "albero", "/stato", archivio_stanze),
        sezione("collegamenti", "Collegamenti", "collega", "/fuori", collegamenti),
        sezione("impostazioni", "Impostazioni", "impostazioni", "/impostazioni", []),
    ]


_da_ricordare: dict[str, object] = {}
_da_ricordare_lucchetto = threading.Lock()


def ricorda(archivio, chiave: str, valore) -> None:
    if archivio.di_prova:
        archivio.salva_stato(chiave, valore)
        return
    with _da_ricordare_lucchetto:
        _da_ricordare[chiave] = valore

    def salva() -> None:
        try:
            with archivio.scrittura():
                with _da_ricordare_lucchetto:
                    if chiave not in _da_ricordare:
                        return
                    ultimo = _da_ricordare.pop(chiave)
                archivio.salva_stato(chiave, ultimo)
        except Exception as guasto:
            registro.errore("pagine.ricordo_non_scritto", chiave=chiave,
                            **registro.dove_si_e_rotto(guasto))

    threading.Thread(target=salva, daemon=True).start()


def ricorda_il_filtro(archivio, parametri) -> None:
    ricorda(archivio, "ultimo_filtro", parametri)


DOVE_SI_PUO_TORNARE = (
    "/officina",
    "/benvenuto", "/benvenuto/chiave", "/benvenuto/modelli", "/benvenuto/cartella",
    "/benvenuto/lavoro", "/benvenuto/pronto",
    "/impostazioni", "/impostazioni#c6", "/impostazioni#tasti",
    "/persone", "/stato", "/stato#salute", "/stato#misura",
    "/sistemare", "/sistemare#doppioni", "/intelligenza", "/miglioramento", "/lavoro",
)


def torna_a(dove_torno: str, altrimenti: str) -> str:
    return dove_torno if dove_torno in DOVE_SI_PUO_TORNARE else altrimenti


def dove_torna(richiesta: Request, altrimenti: str) -> str:
    da = urlsplit(richiesta.headers.get("referer", ""))
    if not da.path or da.path.startswith("/prova/"):
        return altrimenti
    return da.path + (f"?{da.query}" if da.query else "")


def dal_portatile() -> bool:
    from officina import schermo

    return schermo.dal_portatile()


def la_porta():
    from officina.schermo.porta import porta

    return porta


def dati_dello_spazio(archivio) -> dict:
    from officina.archivio import spazio

    contato = spazio.ricordato(archivio.dove.miniature, archivio.dove.database)
    if contato is None:
        return {"pronto": False, "sta_contando": True}
    minuti = int((time.time() - contato.contato_il) // 60)
    tutti = max(1, contato.byte_tutti)
    return {
        "pronto": True,
        "sta_contando": spazio.sta_contando(archivio.dove.miniature),
        "quante": contato.quante,
        "miniature": vista.peso_a_parole(contato.byte_miniature),
        "video": vista.peso_a_parole(contato.byte_video),
        "archivio": vista.peso_a_parole(contato.byte_archivio),
        "tutti": vista.peso_a_parole(contato.byte_tutti),
        "quota_miniature": round(contato.byte_miniature * 100 / tutti, 1),
        "quota_video": round(contato.byte_video * 100 / tutti, 1),
        "quota_archivio": round(contato.byte_archivio * 100 / tutti, 1),
        "quando": ("adesso" if minuti < 1 else
                   "un minuto fa" if minuti == 1 else f"{minuti} minuti fa"),
    }


def ambito_della_pagina(archivio, zona: str) -> dict:
    from officina.importazione import gruppi

    with archivio.lettura() as connessione:
        return {"gruppi_ambito": [dict(g) for g in gruppi.elenco(connessione)],
                "gruppo_ambito": gruppi.scelto(connessione, zona)}
