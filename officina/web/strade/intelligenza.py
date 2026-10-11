from __future__ import annotations

import time

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from officina import registro
from officina.archivio import accesso
from officina.archivio.database import uno
from officina.errori import ErroreOfficina
from officina.modello import impronte as magazzino_impronte
from officina.volti import motore as volti_motore
from officina.volti import rilevatore as volti_rilevatore
from officina.corpi import motore as corpi_motore
from officina.corpi import rilevatore as corpi_rilevatore

from officina.web import in_disparte
from officina.web.strade import base, comune, misura, persone

strada = APIRouter()

@strada.post("/parole/leggi")
def leggi_le_scritte():
    from officina import parole as parole_mod

    archivio = accesso.aperto()
    if not in_disparte.A_PARTE:
        _parti_le_scritte(archivio)
        return RedirectResponse("/intelligenza", status_code=303)
    if not parole_mod.in_casa(archivio.dove.modelli):
        raise ErroreOfficina(
            "Il lettore delle scritte non è ancora in casa. Si scarica da "
            "Stato, nella carta «I modelli».")
    if in_disparte.lancia(comune.lavoro_parole, "scritte", archivio.dove.nome,
                          "officina.web.strade.intelligenza:scritte_di_la",
                          ferma_con="officina.web.strade.intelligenza:ferma_le_scritte_di_la"):
        comune.passata_parole = in_disparte.PassataRiflessa("scritte", a="scritte")
    return RedirectResponse("/intelligenza", status_code=303)


def scritte_di_la(archivio):
    _parti_le_scritte(archivio)
    return comune.lavoro_parole


def ferma_le_scritte_di_la() -> None:
    if comune.passata_parole is not None:
        comune.passata_parole.ferma()


def _parti_le_scritte(archivio) -> None:

    from officina import parole as parole_mod
    from officina.parole import motore as parole_motore

    if not parole_mod.in_casa(archivio.dove.modelli):
        raise ErroreOfficina(
            "Il lettore delle scritte non è ancora in casa. Si scarica da "
            "Stato, nella carta «I modelli».")
    if comune.lavoro_parole.sta_lavorando:
        return
    comune.passata_parole = parole_motore.Passata(archivio)
    passata = comune.passata_parole
    comune.lavoro_parole.numeri = {"fatti": 0, "totale": passata.quanti_mancano(),
                            "scritte": 0, "quanto_manca": "sto ancora misurando"}
    comune.lavoro_parole.parti(lambda: _leggi_le_scritte(passata), "parole")


def _leggi_le_scritte(passata) -> None:
    def al_passo(avanzamento) -> None:
        comune.lavoro_parole.numeri = {
            "fatti": avanzamento.letti + avanzamento.saltati,
            "totale": avanzamento.totale,
            "scritte": avanzamento.scritte,
            "quanto_manca": avanzamento.quanto_manca(),
        }

    passata.esegui(al_passo=al_passo)
    avanzamento = passata.avanzamento
    comune.lavoro_parole.di(
        f"Lette {avanzamento.letti} foto, trovate {avanzamento.scritte} "
        f"scritte in {avanzamento.con_qualcosa} di loro, "
        f"{avanzamento.descritte} descritte.")
    if avanzamento.saltati:
        comune.lavoro_parole.di(
            f"{avanzamento.saltati} non si sono lasciate leggere: "
            + ", ".join(f"{motivo} ({quante})"
                        for motivo, quante in avanzamento.motivi_saltati.items()))


@strada.post("/parole/ferma")
def ferma_le_scritte():
    if comune.passata_parole is not None:
        comune.passata_parole.ferma()
    comune.lavoro_parole.aspetta_che_finisca()
    return RedirectResponse("/intelligenza", status_code=303)


@strada.get("/api/parole")
def api_parole():
    return JSONResponse(comune.lavoro_parole.come_va())


def parti_i_corpi(archivio) -> None:
    manca = corpi_rilevatore.cosa_manca(archivio.dove.modelli)
    if manca:
        raise ErroreOfficina(manca)
    if comune.lavoro_corpi.sta_lavorando:
        return
    comune.passata_corpi = corpi_motore.Passata(archivio)
    passata = comune.passata_corpi
    quanti = passata.quanti_mancano()
    comune.lavoro_corpi.parti(lambda: _guarda_i_corpi(passata), "corpi")
    comune.lavoro_corpi.numeri.setdefault("totale", quanti)
    comune.lavoro_corpi.numeri.setdefault("fatti", 0)
    comune.lavoro_corpi.numeri.setdefault("quanto_manca", "sto ancora misurando")


def _guarda_i_corpi(passata) -> None:
    from officina.parole.motore import Avanzamento as Misuratore

    partito = time.monotonic()

    def al_passo(avanzamento) -> None:
        fatti = avanzamento.fatti + avanzamento.saltati
        misura = Misuratore(totale=avanzamento.totale)
        misura.letti = fatti
        if fatti >= 3:
            misura.ms_per_scatto = (time.monotonic() - partito) * 1000 / fatti
        comune.lavoro_corpi.numeri = {
            "fatti": fatti,
            "totale": avanzamento.totale,
            "corpi": avanzamento.corpi,
            "quanto_manca": misura.quanto_manca(),
        }

    passata.esegui(al_passo=al_passo)
    comune.lavoro_corpi.di(passata.avanzamento.a_parole())
    if not passata.fermata:
        _rifai_i_punti(passata)
    if not passata.fermata:
        _fai_le_figure(passata)
    if not passata.fermata:
        cerca_chi_e(passata.archivio, comune.lavoro_corpi, fermato=lambda: passata.fermata)


def _rifai_i_punti(passata) -> None:
    from officina.parole.motore import Avanzamento as Misuratore

    partito = time.monotonic()

    def al_passo(fatti: int, totale: int) -> None:
        misura = Misuratore(totale=totale)
        misura.letti = fatti
        if fatti >= 3:
            misura.ms_per_scatto = (time.monotonic() - partito) * 1000 / fatti
        comune.lavoro_corpi.numeri = {"fatti": fatti, "totale": totale, "corpi": 0,
                                      "quanto_manca": misura.quanto_manca()}

    rifatti = passata.rifai_i_punti(al_passo=al_passo)
    if rifatti:
        comune.lavoro_corpi.di(f"punti del corpo rifatti per {rifatti} persone")


def _fai_le_figure(passata_corpi) -> None:
    from officina.corpi import figure
    from officina.parole.motore import Avanzamento as Misuratore

    manca = figure.cosa_manca(passata_corpi.archivio.dove.modelli)
    if manca:
        comune.lavoro_corpi.di(manca.split("\n")[0])
        return
    passata = figure.Passata(passata_corpi.archivio, fermato=lambda: passata_corpi.fermata)
    partito = time.monotonic()

    def al_passo(avanzamento) -> None:
        fatti = avanzamento.fatti + avanzamento.saltati
        misura = Misuratore(totale=avanzamento.totale)
        misura.letti = fatti
        if fatti >= 3:
            misura.ms_per_scatto = (time.monotonic() - partito) * 1000 / fatti
        comune.lavoro_corpi.numeri = {
            "fatti": fatti,
            "totale": avanzamento.totale,
            "corpi": avanzamento.figure,
            "quanto_manca": misura.quanto_manca(),
        }

    passata.esegui(al_passo=al_passo)
    comune.lavoro_corpi.di(passata.avanzamento.a_parole())


def cerca_chi_e(archivio, lavoro, fermato=None) -> None:
    from officina.corpi import chi_e, vestiti_a_parole
    from officina.parole.motore import Avanzamento as Misuratore

    try:
        vestiti_a_parole.prepara(archivio)
    except ErroreOfficina as errore:
        lavoro.di("i nomi dei vestiti aspettano SigLIP 2: " + errore.messaggio.split("\n")[0])
    except Exception as guasto:
        registro.errore("chi_e.parole_dei_vestiti_rotte", **registro.dove_si_e_rotto(guasto))
    passata = chi_e.Passata(archivio, fermato=fermato)
    partito = time.monotonic()

    def al_passo(avanzamento) -> None:
        misura = Misuratore(totale=avanzamento.totale)
        misura.letti = avanzamento.fatti
        if avanzamento.fatti:
            misura.ms_per_scatto = (time.monotonic() - partito) * 1000 / avanzamento.fatti
        lavoro.numeri = {
            "fatti": avanzamento.fatti,
            "totale": avanzamento.totale,
            "corpi": avanzamento.proposte,
            "quanto_manca": misura.quanto_manca(),
        }

    passata.esegui(al_passo=al_passo)
    lavoro.di(passata.avanzamento.a_parole())


IA_IN_FILA = ("impronte", "volti", "corpi", "scritte")


def sotto_lavoro_ia(chiave: str):
    return {"impronte": comune.lavoro_impronte_passata, "volti": comune.lavoro_volti,
            "corpi": comune.lavoro_corpi, "scritte": comune.lavoro_parole}[chiave]


def _ferma_il_sotto_lavoro(chiave: str) -> None:
    passata = {"impronte": comune.coda_impronte, "volti": comune.passata_volti,
               "corpi": comune.passata_corpi, "scritte": comune.passata_parole}[chiave]
    if passata is not None:
        passata.ferma()


def _la_fila_ia(archivio) -> None:
    partenze = {"impronte": misura.parti_le_impronte, "volti": persone.parti_i_volti,
                "corpi": parti_i_corpi, "scritte": _parti_le_scritte}
    for chiave in IA_IN_FILA:
        if comune.fila_ia["fermata"]:
            break
        if chiave not in comune.fila_ia["scelti"]:
            continue
        comune.fila_ia["adesso"] = chiave
        sotto = sotto_lavoro_ia(chiave)
        try:
            partenze[chiave](archivio)
        except ErroreOfficina:
            comune.fila_ia["dove_guasto"] = chiave
            raise
        while sotto.sta_lavorando:
            if comune.fila_ia["fermata"]:
                _ferma_il_sotto_lavoro(chiave)
            time.sleep(0.5)
        if sotto.guasto:
            comune.fila_ia["dove_guasto"] = chiave
            guasto = ErroreOfficina(sotto.guasto, codice="ia_" + chiave)
            guasto.dettaglio = sotto.dettaglio
            raise guasto
    comune.fila_ia["adesso"] = ""


def quanti_mancano_ia(archivio) -> dict:
    from officina.descrittori import pronti
    from officina.parole import magazzino as scritte
    from officina import parole as parole_mod

    from officina.descrittori import TIPI
    from officina.importazione import gruppi

    with archivio.lettura() as connessione:
        quanti_scatti = misura.quanti_scatti_in_archivio(connessione)
        avanzamento = magazzino_impronte.avanzamento(connessione)
        nel_gruppo = gruppi.clausola(connessione, "intelligenza")
        if nel_gruppo:
            riga = uno(connessione, "SELECT count(*) AS q FROM scatti s "
                       "WHERE s.fuori_archivio = 0" + nel_gruppo)
            quanti_scatti = riga["q"] if riga else 0
        impronte_per_tipo = {
            t.scheda.nome: magazzino_impronte.quanti_da_fare(
                connessione, t.scheda.nome, t.scheda.versione)
            for t in TIPI if t.scheda.nome in pronti(archivio.dove.modelli)} if nel_gruppo else {}
        try:
            volti_mancano = volti_motore.quanti_mancano_senza_aprire(connessione)
        except Exception:
            volti_mancano = 0
        try:
            corpi_mancano = (corpi_motore.quanti_mancano_senza_aprire(connessione)
                             + corpi_motore.quanti_da_ripuntare_senza_aprire(connessione))
        except Exception:
            corpi_mancano = 0
        try:
            from officina.corpi import figure

            if not figure.cosa_manca(archivio.dove.modelli):
                corpi_mancano += figure.quanti_mancano_senza_aprire(connessione)
        except Exception:
            pass
        try:
            scritte_mancano = scritte.quanti_da_leggere(
                connessione, parole_mod.SCHEDA.nome, parole_mod.SCHEDA.versione)
        except Exception:
            scritte_mancano = 0
    righe = [r for r in misura.righe_impronte(avanzamento, quanti_scatti, archivio.dove.modelli)
             if r["nome"] in pronti(archivio.dove.modelli)]
    impronte_mancano = max((impronte_per_tipo.get(r["nome"], r["totale"] - r["scatti"])
                            for r in righe), default=quanti_scatti)
    if nel_gruppo:
        impronte_mancano = min(impronte_mancano, quanti_scatti)
    return {"totale": quanti_scatti,
            "impronte": max(0, impronte_mancano),
            "volti": volti_mancano,
            "corpi": corpi_mancano,
            "scritte": scritte_mancano,
            "modelli_impronte": [r["titolo"] for r in righe]}


def come_va_la_fila_ia() -> dict:
    corre = comune.lavoro_ia.sta_lavorando
    lavori_qui = {}
    for chiave in IA_IN_FILA:
        sotto = sotto_lavoro_ia(chiave)
        numeri = dict(sotto.numeri)
        if chiave == "impronte" and comune.coda_impronte is not None and (
                sotto.sta_lavorando or comune.fila_ia["adesso"] == "impronte"):
            from officina.descrittori import SCHEDE

            scatti_fatti, scatti_totale = comune.coda_impronte.scatti
            numeri = {"fatti": scatti_fatti, "totale": scatti_totale,
                      "percento": int(comune.coda_impronte.percentuale or 0),
                      "quanto_manca": comune.coda_impronte.quanto_manca(),
                      "modelli": [{**riga, "titolo": SCHEDE[riga["nome"]].titolo.split(" (")[0]}
                                  for riga in comune.coda_impronte.per_modello()]}
        elif numeri.get("totale"):
            numeri["percento"] = min(99, int(numeri.get("fatti", 0) * 100 / numeri["totale"]))
        lavori_qui[chiave] = {"sta_lavorando": sotto.sta_lavorando, **numeri}
    return {
        "sta_lavorando": corre,
        "scelti": list(comune.fila_ia["scelti"]),
        "adesso": comune.fila_ia["adesso"] if corre else "",
        "sta_fermando": corre and comune.fila_ia["fermata"],
        "guasto": "" if corre else comune.lavoro_ia.guasto,
        "dettaglio": "" if corre else comune.lavoro_ia.dettaglio,
        "dove_guasto": "" if corre else comune.fila_ia["dove_guasto"],
        "lavori": lavori_qui,
    }


@strada.get("/intelligenza", response_class=HTMLResponse)
def pagina_intelligenza(richiesta: Request):
    from officina import parole as parole_mod
    from officina.descrittori import pronti

    archivio = accesso.aperto()
    mancano = quanti_mancano_ia(archivio)
    in_casa = {
        "impronte": bool(pronti(archivio.dove.modelli)),
        "volti": not volti_rilevatore.cosa_manca(archivio.dove.modelli),
        "corpi": not corpi_rilevatore.cosa_manca(archivio.dove.modelli),
        "scritte": parole_mod.in_casa(archivio.dove.modelli),
    }
    return base.pagine.TemplateResponse(richiesta, "intelligenza.html", {
        **base.comune(richiesta, "intelligenza"),
        "mancano": mancano,
        "in_casa": in_casa,
        "fila": come_va_la_fila_ia(),
        "avviso_scritte": _avviso_scritte(archivio),
        **base.ambito_della_pagina(archivio, "intelligenza"),
    })


AVVISO_SCRITTE = "avviso_scritte_visto"


def _avviso_scritte(archivio) -> bool:
    from officina import parole as parole_mod
    from officina.parole import magazzino as scritte

    if archivio.impostazione(AVVISO_SCRITTE) == parole_mod.SCHEDA.versione:
        return False
    try:
        with archivio.lettura() as connessione:
            return scritte.ci_sono_letture_vecchie(
                connessione, parole_mod.SCHEDA.nome, parole_mod.SCHEDA.versione)
    except Exception:
        return False


@strada.post("/api/intelligenza/avviso-scritte")
def avviso_scritte_visto():
    from officina import parole as parole_mod

    accesso.aperto().imposta(AVVISO_SCRITTE, parole_mod.SCHEDA.versione)
    return JSONResponse({"fatto": True})


@strada.post("/intelligenza/avvia")
def avvia_l_intelligenza(scelti: list[str] = Form([])):
    archivio = accesso.aperto()
    voluti = [chiave for chiave in IA_IN_FILA if chiave in scelti]
    if not voluti or comune.lavoro_ia.sta_lavorando:
        return RedirectResponse("/intelligenza", status_code=303)
    comune.fila_ia.update({"scelti": voluti, "adesso": "", "fermata": False,
                    "dove_guasto": ""})
    if in_disparte.A_PARTE:
        nome = archivio.dove.nome
        comune.lavoro_ia.parti(lambda: in_disparte.ponte(nome, voluti), "intelligenza")
    else:
        comune.lavoro_ia.parti(lambda: _la_fila_ia(archivio), "intelligenza")
    return RedirectResponse("/intelligenza", status_code=303)


@strada.post("/api/intelligenza/scelta")
def scelta_dell_intelligenza(chiave: str = Form(...), acceso: bool = Form(...)):
    if chiave in IA_IN_FILA and comune.lavoro_ia.sta_lavorando:
        adesso = comune.fila_ia["adesso"]
        gia = IA_IN_FILA.index(adesso) if adesso in IA_IN_FILA else -1
        if IA_IN_FILA.index(chiave) > gia:
            scelti = set(comune.fila_ia["scelti"])
            (scelti.add if acceso else scelti.discard)(chiave)
            comune.fila_ia["scelti"] = [k for k in IA_IN_FILA if k in scelti]
            in_disparte.manda("scelti", comune.fila_ia["scelti"])
    return JSONResponse(come_va_la_fila_ia())


@strada.post("/intelligenza/ferma")
def ferma_l_intelligenza():
    comune.fila_ia["fermata"] = True
    in_disparte.ferma()
    if comune.fila_ia["adesso"]:
        _ferma_il_sotto_lavoro(comune.fila_ia["adesso"])
    comune.lavoro_ia.aspetta_che_finisca(2.0)
    return RedirectResponse("/intelligenza", status_code=303)


@strada.get("/api/intelligenza")
def api_intelligenza():
    return JSONResponse({**come_va_la_fila_ia(),
                         "mancano": quanti_mancano_ia(accesso.aperto())})
