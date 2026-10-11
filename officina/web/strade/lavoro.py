from __future__ import annotations

import shutil
from datetime import datetime

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from officina.archivio import accesso
from officina.archivio.database import tutti, uno
from officina.modello import scatti
from officina.volti import rilevatore as volti_rilevatore
from officina.corpi import rilevatore as corpi_rilevatore
from officina.modello.scatti import Filtro
from officina.web import vista

from officina.web.strade import base, comune, intelligenza

strada = APIRouter()


@strada.get("/lavoro", response_class=HTMLResponse)
def casa_del_lavoro(richiesta: Request):
    from officina import parole as parole_mod
    from officina.descrittori import pronti
    from officina.importazione import scansione
    from officina.miglioria import coda as miglioria_coda

    insieme = base.comune(richiesta, "lavoro")
    if insieme["aspetto"]["lavoro"] != "A":
        return RedirectResponse("/officina", status_code=303)
    archivio = accesso.aperto()
    conti_barra = _conti_della_barra_aperta(archivio)
    with archivio.lettura() as connessione:
        prossimi = scatti.pagina(
            connessione, Filtro(senza_etichetta=True, senza_evidenziati=True), 0, 16)
        conti = miglioria_coda.conteggi(connessione)
        cartelle = len(scansione.cartelle(connessione))
        ultima = uno(connessione,
                     "SELECT finita_il, nuovi_scatti FROM importazioni "
                     "WHERE stato = 'finita' ORDER BY id DESC LIMIT 1")
        ripartenza = None
        salvato = archivio.stato("ultimo_scatto")
        if salvato:
            quello = scatti.per_id(connessione, int(salvato))
            if quello is not None and quello["data_locale"]:
                ripartenza = scatti.giorno_a_parole(str(quello["data_locale"])[:10])

    totale = conti_barra["totale"]
    mancano = intelligenza.quanti_mancano_ia(archivio)
    in_casa = {"impronte": bool(pronti(archivio.dove.modelli)),
               "volti": not volti_rilevatore.cosa_manca(archivio.dove.modelli),
               "corpi": not corpi_rilevatore.cosa_manca(archivio.dove.modelli),
               "scritte": parole_mod.in_casa(archivio.dove.modelli)}
    ia_mancano = sum(mancano[k] for k in intelligenza.IA_IN_FILA if in_casa[k])
    ia_corre = comune.lavoro_ia.sta_lavorando or any(
        intelligenza.sotto_lavoro_ia(k).sta_lavorando for k in intelligenza.IA_IN_FILA)
    importa_corre = comune.lavoro is not None and comune.lavoro.sta_lavorando
    da_sistemare = conti_barra["da_guardare"] + conti_barra.get("doppioni", 0)
    senza_etichetta = conti_barra["senza_etichetta"]
    da_rivedere = conti[miglioria_coda.DA_RIVEDERE]

    def tappa(nome, dove, stato, detto, tasto, icona, tasto_dove=""):
        return {"nome": nome, "dove": dove, "stato": stato, "detto": detto,
                "tasto": tasto, "icona": icona, "tasto_dove": tasto_dove or dove}

    if importa_corre:
        aggiungi = tappa("Aggiungi scatti", "/importazione", "gira",
                         "Sto aggiungendo gli scatti nuovi.", "Guarda", "aggiungi")
    elif not totale:
        aggiungi = tappa("Aggiungi scatti", "/importazione", "tocca",
                         "Non ci sono ancora scatti. Si comincia da qui: scegli le cartelle dove stanno.",
                         "Aggiungi le cartelle", "aggiungi")
    else:
        quando = ""
        if ultima and ultima["finita_il"]:
            quando = f" L'ultima volta {scatti.giorno_a_parole(str(ultima['finita_il'])[:10])}"
            quando += (f": {ultima['nuovi_scatti']} nuovi." if ultima["nuovi_scatti"] else ".")
        aggiungi = tappa("Aggiungi scatti", "/importazione", "fatto",
                         f"{totale:,} scatti da {cartelle} {'cartella' if cartelle == 1 else 'cartelle'}.".replace(",", ".") + quando,
                         "Aggiungi", "aggiungi")

    if not totale:
        ia = tappa("Intelligenza artificiale", "/intelligenza", "dopo",
                   "Guarderà le foto appena ci sono.", "Apri", "chip")
    elif ia_corre:
        fila = intelligenza.come_va_la_fila_ia()
        adesso = fila["adesso"] or next((k for k in intelligenza.IA_IN_FILA
                                         if intelligenza.sotto_lavoro_ia(k).sta_lavorando), "")
        nomi = {"impronte": "calcola le impronte", "volti": "cerca i volti",
                "corpi": "separa le persone", "scritte": "legge le scritte"}
        pct = fila["lavori"].get(adesso, {}).get("percento")
        ia = tappa("Intelligenza artificiale", "/intelligenza", "gira",
                   f"Sta lavorando: {nomi.get(adesso, 'guarda le foto')}" + (f", {pct}%." if pct is not None else "."),
                   "Guarda", "chip")
    elif not all(in_casa.values()):
        senza = [n for k, n in (("impronte", "le impronte"), ("volti", "i volti"),
                                ("corpi", "i corpi"), ("scritte", "le scritte"))
                 if not in_casa[k]]
        ia = tappa("Intelligenza artificiale", "/intelligenza", "tocca",
                   "Mancano i modelli per " + " e ".join(senza) + ". Si scaricano una volta sola.",
                   "Scaricali", "chip", "/stato#salute")
    elif ia_mancano:
        quali = [n for k, n in (("impronte", "impronte"), ("volti", "volti"),
                                ("corpi", "corpi"), ("scritte", "scritte"))
                 if in_casa[k] and mancano[k]]
        ia = tappa("Intelligenza artificiale", "/intelligenza", "tocca",
                   "Da fare: " + ", ".join(quali) + ". Parte con un tasto e lavora da sola.",
                   "Avvia", "chip")
    else:
        ia = tappa("Intelligenza artificiale", "/intelligenza", "fatto",
                   "Tutti gli scatti guardati: impronte, volti, corpi e scritte.", "Apri", "chip")

    if not totale:
        sistema = tappa("Da sistemare", "/sistemare", "dopo", "Ancora niente.", "Apri", "controlla")
    elif da_sistemare:
        sistema = tappa("Da sistemare", "/sistemare", "tocca",
                        f"{da_sistemare} {'cosa aspetta' if da_sistemare == 1 else 'cose aspettano'} te: doppioni, date mancanti, file che non si aprono.",
                        "Sistema", "controlla")
    else:
        sistema = tappa("Da sistemare", "/sistemare", "fatto", "Niente da sistemare.", "Apri", "controlla")

    if not totale:
        etichetta = tappa("Etichetta", "/officina", "dopo", "Ancora niente da etichettare.", "Apri", "etichetta")
    elif senza_etichetta:
        etichetta = tappa("Etichetta", "/officina", "tocca",
                          f"{senza_etichetta:,} scatti senza etichetta.".replace(",", ".")
                          + (f" Ti eri fermato al {ripartenza}." if ripartenza else ""),
                          "Continua", "etichetta")
    else:
        etichetta = tappa("Etichetta", "/officina", "fatto", "Tutti gli scatti hanno un'etichetta.",
                          "Ripassa", "etichetta")

    if da_rivedere:
        migliora = tappa("Miglioramento", "/miglioramento", "tocca",
                         f"{da_rivedere} {'foto migliorata' if da_rivedere == 1 else 'foto migliorate'} da rivedere.",
                         "Rivedi", "migliora")
    elif conti[miglioria_coda.IN_LAVORO] or conti[miglioria_coda.IN_CODA]:
        migliora = tappa("Miglioramento", "/miglioramento", "gira",
                         f"{conti[miglioria_coda.IN_CODA]} in coda, ci sta lavorando.", "Guarda", "migliora")
    elif not totale:
        migliora = tappa("Miglioramento", "/miglioramento", "dopo", "Ancora niente da migliorare.", "Apri", "migliora")
    else:
        approvate = conti[miglioria_coda.APPROVATA]
        migliora = tappa("Miglioramento", "/miglioramento", "fatto",
                         "Niente da rivedere." + (f" {approvate} foto migliorate e approvate." if approvate else ""),
                         "Apri", "migliora")

    tappe = [aggiungi, ia, sistema, etichetta, migliora]
    prossimo = next((t for t in tappe if t["stato"] == "tocca"), None)
    if prossimo:
        prossimo["qui"] = True
    return base.pagine.TemplateResponse(richiesta, "lavoro.html", {
        **insieme,
        "tappe": tappe,
        "prossimo": prossimo,
        "prossimi": [s for s in prossimi if s.get("file_id")][:10] if senza_etichetta else [],
        "ripartenza": ripartenza,
    })


def _conti_della_barra_aperta(archivio) -> dict:
    with archivio.lettura() as connessione:
        return base.conti_della_barra(connessione)


def _saluto(ora: int) -> str:
    if 5 <= ora < 13:
        return "Buongiorno"
    if 13 <= ora < 18:
        return "Buon pomeriggio"
    return "Buonasera"


@strada.get("/casa", response_class=HTMLResponse)
def casa_della_fotina(richiesta: Request):
    archivio = accesso.aperto()
    with archivio.lettura() as connessione:
        prossimi = scatti.pagina(
            connessione, Filtro(senza_etichetta=True, senza_evidenziati=True), 0, 5)
        recenti = tutti(
            connessione,
            "SELECT s.id, (SELECT f.id FROM file_media f WHERE f.scatto_id = s.id "
            "AND f.ruolo = 'principale' LIMIT 1) AS file_id FROM scatti s "
            "WHERE s.fuori_archivio = 0 ORDER BY s.id DESC LIMIT 10")
    copie_fatte = archivio.copie_esistenti()
    try:
        libero = shutil.disk_usage(archivio.dove.radice).free
    except OSError:
        libero = None
    pochi_gb = libero is not None and libero < 5 * 1024 ** 3
    return base.pagine.TemplateResponse(richiesta, "casa.html", {
        **base.comune(richiesta, "casa"),
        "saluto": _saluto(datetime.now().hour),
        "prossimi": [s for s in prossimi if s.get("file_id")],
        "recenti": [dict(r) for r in recenti if r["file_id"]],
        "ultima_copia": copie_fatte[0] if copie_fatte else None,
        "libero": vista.peso_a_parole(libero) if libero is not None else "",
        "va_bene": bool(copie_fatte) and not pochi_gb,
    })
