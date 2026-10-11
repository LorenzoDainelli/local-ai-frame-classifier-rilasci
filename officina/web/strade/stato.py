from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from officina.archivio import accesso
from officina.archivio.database import tutti, uno
from officina.immagini import consegna
from officina.modello import etichette, impronte as magazzino_impronte
from officina.web import stato_a_parole, vista

from officina.web.strade import base, comune, generale, misura, modelli

strada = APIRouter()


def _dati_della_pagella() -> dict:
    archivio = accesso.aperto()
    with archivio.lettura() as connessione:
        senza = etichette.quanti_senza_etichetta(connessione)
        conto = comune.pagella_pronta.per(connessione, senza_etichetta=senza)
    return {"pagella": conto.a_dizionario()}


PAGINE_DELLO_STATO = {"A": "stato.html", "B": "stato-b.html", "C": "stato-c.html"}


def _la_macchina_in_breve(scheda_video: str | None, capacita: list) -> str:
    pezzi = [scheda_video] if scheda_video else []
    pezzi += [voce[0].lower() + voce[1:] for voce, valore, _ in capacita
              if valore and voce != "Scrive i WebP"]
    return " · ".join(pezzi) or "legge e scrive le foto con quello che trova"


@strada.get("/stato", response_class=HTMLResponse)
def stato(richiesta: Request):
    from officina.programma import librerie

    insieme = base.comune(richiesta, "stato")
    salute = _dati_della_salute()
    pagella = _dati_della_pagella()
    sistemare = stato_a_parole.da_sistemare(salute)
    lavori_adesso = generale.api_in_corso()["lavori"]
    scheda_video = librerie.nome_della_scheda_scritta()
    numeri = dict(salute["numeri"])
    dati = {
        **insieme, **pagella, **misura.dati_della_misura(), **salute,
        "sistemare": sistemare,
        "lavori_adesso": lavori_adesso,
        "stato_numeri": numeri,
        "scheda_video": scheda_video,
        "macchina_in_breve": _la_macchina_in_breve(scheda_video, salute["capacita"]),
    }
    quale = insieme["aspetto"]["stato"]
    if quale == "B":
        titolo, sotto = stato_a_parole.titolo(numeri.get("Scatti", 0), sistemare)
        quanti = len(lavori_adesso)
        dati["lettera"] = {
            "titolo": titolo, "sotto": sotto,
            "albero": stato_a_parole.l_albero(pagella["pagella"]),
            "resto": stato_a_parole.il_resto(numeri.get("Scatti", 0), salute),
            "quanti_lavori": "una cosa" if quanti == 1 else f"{stato_a_parole.in_lettere(quanti)} cose",
        }
    return base.pagine.TemplateResponse(richiesta, PAGINE_DELLO_STATO[quale], dati)


def _quante_scritte() -> dict:
    from officina import parole as parole_mod
    from officina.parole import magazzino as scritte

    archivio = accesso.aperto()
    try:
        with archivio.lettura() as connessione:
            quante = scritte.quante_ce_ne_sono(connessione)
            restano = scritte.quanti_da_leggere(
                connessione, parole_mod.SCHEDA.nome, parole_mod.SCHEDA.versione)
    except Exception:
        quante, restano = 0, 0
    return {
        "quante": quante,
        "restano": restano,
        "in_casa": parole_mod.in_casa(archivio.dove.modelli),
        "lavoro": comune.lavoro_parole.come_va(),
    }


@strada.post("/archivio/ricalcola-spazio")
def ricalcola_lo_spazio():
    from officina.archivio import spazio

    archivio = accesso.aperto()
    spazio.ricalcola(archivio.dove.miniature, archivio.dove.database)
    return RedirectResponse("/stato#archivio", status_code=303)


@strada.get("/api/periodo")
def api_periodo():
    with accesso.aperto().lettura() as connessione:
        mesi = {
            riga["mese"]: riga["quanti"] for riga in tutti(
                connessione,
                "SELECT substr(data_locale, 1, 7) AS mese, count(*) AS quanti "
                "FROM scatti WHERE fuori_archivio = 0 AND data_locale IS NOT NULL "
                "GROUP BY mese")
            if riga["mese"] and len(riga["mese"]) == 7}
    return {"mesi": mesi}


@strada.get("/api/spazio")
def api_spazio():
    return base.dati_dello_spazio(accesso.aperto())


def _dati_della_salute() -> dict:
    archivio = accesso.aperto()
    spazio_usato = base.dati_dello_spazio(archivio)
    with archivio.lettura() as connessione:
        def conto(sql: str) -> int:
            riga = uno(connessione, sql)
            return riga["q"] if riga else 0

        numeri = [
            ("Scatti", conto("SELECT count(*) AS q FROM scatti WHERE fuori_archivio = 0")),
            ("Fuori archivio", conto("SELECT count(*) AS q FROM scatti WHERE fuori_archivio = 1")),
            ("File", conto("SELECT count(*) AS q FROM file_media")),
            ("Percorsi", conto("SELECT count(*) AS q FROM percorsi")),
            ("File non trovati sul disco", conto("SELECT count(*) AS q FROM percorsi WHERE presente = 0")),
            ("Coppie live", conto("SELECT count(*) AS q FROM scatti WHERE genere = 'live'")),
            ("Video autonomi", conto("SELECT count(*) AS q FROM scatti WHERE genere = 'video'")),
            ("Senza data", conto("SELECT count(*) AS q FROM scatti WHERE data_locale IS NULL")),
            ("Nodi attivi", conto("SELECT count(*) AS q FROM nodi WHERE stato = 'attivo'")),
            ("Etichette messe da te", conto("SELECT count(*) AS q FROM etichette WHERE origine = 'utente'")),
            ("Non importati", conto("SELECT count(*) AS q FROM non_importati")),
            ("Miniature", (f"{vista.numero_a_parole(spazio_usato['quante'])} · {spazio_usato['miniature']}"
                           if spazio_usato["pronto"] else "le sto contando")),
            ("Impronte", conto("SELECT count(*) AS q FROM impronte")),
            ("Peso delle impronte",
             vista.peso_a_parole(magazzino_impronte.peso(connessione))),
            ("Misure fatte", conto("SELECT count(*) AS q FROM misure")),
        ]
        in_breve = {
            "foto": conto("SELECT count(*) AS q FROM scatti WHERE fuori_archivio = 0 AND genere != 'video'"),
            "video": conto("SELECT count(*) AS q FROM scatti WHERE fuori_archivio = 0 AND genere = 'video'"),
            "cartelle": conto("SELECT count(*) AS q FROM cartelle_sorgente WHERE attiva = 1"),
            "con_impronta": conto("SELECT count(DISTINCT i.scatto_id) AS q FROM impronte i "
                                  "JOIN scatti s ON s.id = i.scatto_id WHERE s.fuori_archivio = 0"),
        }
        modelli_usati = magazzino_impronte.avanzamento(connessione)

    capacita = consegna.capacita()
    tutti_gli_scatti = in_breve["foto"] + in_breve["video"]
    in_breve["senza_impronta"] = max(0, tutti_gli_scatti - in_breve["con_impronta"])
    in_breve["quota_impronta"] = (int(in_breve["con_impronta"] * 100 / tutti_gli_scatti)
                                  if tutti_gli_scatti else 0)
    return {
        "numeri": numeri,
        "in_breve": in_breve,
        "spazio": spazio_usato,
        "modelli_usati": modelli_usati,
        "modelli": modelli.come_stanno_i_modelli(archivio.dove.modelli),
        "dove_stanno_i_modelli": str(archivio.dove.modelli),
        "scaricamento": comune.lavoro_modelli.come_va(),
        "scritte": _quante_scritte(),
        "capacita": [
            ("Legge gli HEIC", capacita["heic"],
             "senza, le foto dell'iPhone non si aprono (regola 51)"),
            ("Scrive gli AVIF", capacita["avif"],
             "senza, le foto arrivano al browser in JPEG (regola 327)"),
            ("Scrive i WebP", capacita["webp"], "alternativa di riserva"),
        ],
        "copie": [
            {"quando": c.quando, "motivo": _PERCHE_LA_COPIA.get(c.motivo, c.motivo.replace("_", " ")),
             "peso": vista.peso_a_parole(c.byte)}
            for c in archivio.copie_esistenti()[:12]
        ],
    }


_PERCHE_LA_COPIA = {
    "chiusura": "alla chiusura",
    "in_sottofondo": "mentre lavoravi",
    "manuale": "fatta da te",
    "prima_aggiornamento": "prima di un aggiornamento",
    "prima_del_ripristino": "prima di rimettere una copia vecchia",
}
