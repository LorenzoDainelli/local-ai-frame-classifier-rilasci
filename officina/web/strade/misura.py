from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from officina.archivio import accesso, memoria
from officina.archivio.database import tutti, uno
from officina.errori import (ErroreOfficina, PERCHE_SALTATO,
                             MOTIVO_SENZA_FRASE as _MOTIVO_SENZA_FRASE)
from officina.modello import etichette, impronte as magazzino_impronte, nodi, scatti
from officina.modello.scatti import Filtro
from officina.web import vista

from officina.web import in_disparte
from officina.web.strade import base, comune

strada = APIRouter()


def _quanto_manca_per_un_voto(connessione, con_esempi=None) -> list[dict]:
    from officina.apprendimento import esempi as raccolta
    from officina.apprendimento import gruppi as divisione
    from officina.apprendimento.pagella import MINIMO_NO, MINIMO_SI

    if con_esempi is None:
        con_esempi = raccolta.nodi_con_esempi(connessione, minimo=1)

    come_si_chiama = {riga["id"]: riga["nome"] for riga in tutti(
        connessione, "SELECT id, nome FROM nodi")}

    quando = divisione.quando_sono_stati_fatti(
        connessione, sorted({s for _, suoi in con_esempi for s in suoi.scatti}))

    fuori = []
    for nodo_id, suoi in con_esempi:
        gruppo_di = divisione.per_divisione(connessione, suoi.scatti, quando)
        gruppi_si = len({gruppo_di.get(s, s) for s in suoi.si})
        gruppi_no = len({gruppo_di.get(s, s) for s in suoi.no})
        fuori.append({
            "nome": come_si_chiama.get(nodo_id, "?"),
            "gruppi_si": gruppi_si,
            "gruppi_no": gruppi_no,
            "manca_si": max(0, MINIMO_SI - gruppi_si),
            "manca_no": max(0, MINIMO_NO - gruppi_no),
            "pronto": gruppi_si >= MINIMO_SI and gruppi_no >= MINIMO_NO,
        })
    return fuori


_misura_tenuta = memoria.Ricordo("i conti della misura")


def _vincente_di(ultima: dict | None) -> str | None:
    import json

    from officina.misura import rapporto as resoconto

    if not ultima or not ultima.get("rapporto"):
        return None
    try:
        return resoconto.modo_vincente(json.loads(ultima["rapporto"]))
    except (ValueError, TypeError, AttributeError):
        return None


def _stato_della_misura() -> dict:
    archivio = accesso.aperto()
    from officina.descrittori import SCHEDE, pronti

    with archivio.lettura() as connessione:
        letti = _misura_tenuta.prendi(
            connessione, lambda: _leggi_la_misura(connessione))
    avanzamento = letti["avanzamento"]
    impronte_qui = contesto_impronte(archivio, avanzamento, letti["quanti_scatti"])
    peso = letti["peso"]
    con_esempi = letti["con_esempi"]
    decisi = letti["decisi"]
    quanto_manca = letti["quanto_manca"]
    ultima = dict(letti["ultima"]) if letti["ultima"] else None
    vincente = _vincente_di(ultima)
    if ultima:
        ultima.pop("rapporto", None)
    return {
        "modo_vincente": vincente,
        "modo_in_uso": archivio.impostazione("griglia_come_si_somma"),
        "avanzamento": avanzamento,
        "peso_impronte": vista.peso_a_parole(peso),
        "nodi_con_esempi": len(con_esempi),
        "scatti_decisi": decisi,
        "descrittori_pronti": pronti(archivio.dove.modelli),
        "schede": SCHEDE,
        "ultima_misura": ultima,
        "sta_calcolando": comune.lavoro_impronte_passata.sta_lavorando,
        "quanto_manca": quanto_manca,
        "nodi_pronti": sum(1 for voce in quanto_manca if voce["pronto"]),
        **impronte_qui,
    }


def contesto_impronte(archivio, avanzamento: list[dict], quanti_scatti: int) -> dict:
    sta_lavorando = comune.lavoro_impronte_passata.sta_lavorando
    return {
        "righe_impronte": righe_impronte(avanzamento, quanti_scatti,
                                          archivio.dove.modelli),
        "sta_calcolando": sta_lavorando,
        "guasto_impronte": "" if sta_lavorando else (comune.lavoro_impronte_passata.guasto or ""),
    }


def righe_impronte(avanzamento: list[dict], quanti_scatti: int,
                    cartella_modelli) -> list[dict]:
    from officina.descrittori import SENZA_MODELLO, TIPI, VISIVO, in_casa

    per_versione = {(riga["descrittore"], riga["versione"]): riga for riga in avanzamento}
    righe = []
    for tipo in TIPI:
        carta = tipo.scheda
        letta = per_versione.get((carta.nome, carta.versione))
        fatti = min(letta["scatti"], quanti_scatti) if letta else 0
        pronto = in_casa(carta.nome, cartella_modelli)
        if not pronto:
            stato = "da_scaricare"
        elif quanti_scatti and fatti >= quanti_scatti:
            stato = "fatte"
        elif fatti:
            stato = "a_meta"
        else:
            stato = "nessuna"
        if carta.famiglia == SENZA_MODELLO:
            sotto = "colori e bordi, senza IA"
        elif carta.famiglia == VISIVO:
            sotto = "sola visione"
        else:
            sotto = "immagini e parole"
        righe.append({
            "nome": carta.nome,
            "titolo": _titolo_corto(carta.titolo),
            "sotto": sotto,
            "pronto": pronto,
            "scatti": fatti,
            "totale": quanti_scatti,
            "impronte": letta["impronte"] if letta else 0,
            "percentuale": round(fatti * 100 / quanti_scatti, 1) if quanti_scatti else 0,
            "stato": stato,
        })
    return righe


def _leggi_la_misura(connessione) -> dict:
    from officina.apprendimento import esempi as raccolta

    con_esempi = raccolta.nodi_con_esempi(connessione, minimo=1)
    return {
        "avanzamento": magazzino_impronte.avanzamento(connessione),
        "quanti_scatti": quanti_scatti_in_archivio(connessione),
        "peso": magazzino_impronte.peso(connessione),
        "con_esempi": con_esempi,
        "decisi": raccolta.quanti_decisi(connessione),
        "quanto_manca": _quanto_manca_per_un_voto(connessione, con_esempi),
        "ultima": uno(connessione,
                      "SELECT fatta_il, scatti, gruppi, nodi, rapporto FROM misure "
                      "ORDER BY id DESC LIMIT 1"),
    }


def _nodi_di_prova() -> list[dict]:
    with accesso.aperto().lettura() as connessione:
        albero = nodi.albero(connessione, con_esempi=True)
        fuori = []
        for radice in albero:
            if radice.figli:
                for figlio in radice.figli:
                    fuori.append({"id": figlio.id, "nome": figlio.nome,
                                  "ramo": radice.nome, "esempi": figlio.esempi,
                                  "esclusivo": radice.scegline_uno})
            else:
                fuori.append({"id": radice.id, "nome": radice.nome, "ramo": "",
                              "esempi": radice.esempi, "esclusivo": False})
    return fuori[:10]


def dati_della_misura() -> dict:
    with accesso.aperto().lettura() as connessione:
        rami = [{"id": riga["id"], "nome": riga["nome"]} for riga in tutti(
            connessione,
            "SELECT id, nome FROM nodi WHERE genitore_id IS NULL "
            "AND stato = 'attivo' ORDER BY id")]
    return {
        **_stato_della_misura(),
        "nodi_di_prova": _nodi_di_prova(),
        "rami": rami,
        "rapporto": comune.ultima_misura,
        "misura_lavoro": comune.lavoro_misura.come_va(),
    }


@strada.post("/misura/nodo")
def crea_nodo_di_prova(nome: str = Form(...), ramo_id: str = Form("")):
    with accesso.aperto().scrittura() as connessione:
        genitore = int(ramo_id) if ramo_id.strip().isdecimal() else None
        nodi.crea(connessione, nome.strip(), genitore)
    return RedirectResponse("/stato#misura", status_code=303)


@strada.post("/misura/ramo")
def crea_ramo_esclusivo(nome: str = Form(...)):
    with accesso.aperto().scrittura() as connessione:
        nuovo = nodi.crea(connessione, nome.strip(), None)
        connessione.execute("UPDATE nodi SET scegline_uno = 1 WHERE id = ?", (nuovo,))
    return RedirectResponse("/stato#misura", status_code=303)


QUANTI_AL_BANCO = 300


@strada.get("/misura/banco", response_class=HTMLResponse)
def banco(richiesta: Request, da: int = 0):
    from officina.apprendimento import esempi as raccolta

    filtro = Filtro(ordine="data_giu")
    with accesso.aperto().lettura() as connessione:
        campione = scatti.campione_sparso(connessione, filtro, QUANTI_AL_BANCO)
        posizione = max(0, min(da, len(campione) - 1)) if campione else 0
        scatto = None
        gia = {}
        if campione:
            riga = scatti.per_id(connessione, campione[posizione])
            file_riga = uno(connessione, "SELECT id FROM file_media "
                                         "WHERE scatto_id = ? AND ruolo = 'principale'",
                            campione[posizione])
            if riga is not None:
                scatto = {"id": riga["id"], "genere": riga["genere"],
                          "file_id": file_riga["id"] if file_riga else None,
                          "quando": scatti.giorno_a_parole(riga["giorno"])}
                for voce in etichette.di_scatto(connessione, riga["id"], solo_si=False):
                    gia[voce["nodo_id"]] = voce["stato"]
        decisi = raccolta.quanti_decisi(connessione)
    return base.pagine.TemplateResponse(richiesta, "banco.html", {
        **base.comune(richiesta, "banco"),
        "scatto": scatto,
        "posizione": posizione,
        "quanti": len(campione),
        "decisi": decisi,
        "nodi_di_prova": _nodi_di_prova(),
        "gia_deciso": gia,
    })


@strada.post("/misura/segna")
def segna(scatto_id: int = Form(...), nodo_id: int = Form(...),
          stato: str = Form("si")):
    with accesso.aperto().scrittura() as connessione:
        if stato == "niente":
            etichette.togli(connessione, scatto_id, nodo_id)
        else:
            etichette.metti(connessione, scatto_id, nodo_id, stato, "utente")
    return JSONResponse({"fatto": True})


@strada.post("/misura/nessuno")
def nessuno_di_questi(scatto_id: int = Form(...)):
    with accesso.aperto().scrittura() as connessione:
        for voce in _nodi_di_prova():
            etichette.metti(connessione, scatto_id, voce["id"], "no", "utente")
    return JSONResponse({"fatto": True})


def quanti_scatti_in_archivio(connessione) -> int:
    riga = uno(connessione, "SELECT count(*) AS q FROM scatti WHERE fuori_archivio = 0")
    return riga["q"] if riga else 0


def _quali_in_coda(descrittore: str, archivio) -> list[str]:
    from officina.descrittori import PREDEFINITO, SCHEDE, TIPI, pronti

    disponibili = pronti(archivio.dove.modelli)
    voluto = descrittore or "tutti"
    if voluto in SCHEDE:
        if voluto not in disponibili:
            raise ErroreOfficina(
                f"{_titolo_corto(SCHEDE[voluto].titolo)} non è ancora scaricato. "
                "Si scarica da Stato con «Scarica quello che manca», oppure in "
                "Impostazioni › Elaborazione si sceglie «tutti, uno dopo l'altro».")
        return [voluto]
    in_ordine = [tipo.scheda.nome for tipo in TIPI if tipo.scheda.nome in disponibili]
    return in_ordine or [PREDEFINITO]


@strada.post("/misura/impronte")
def parti_impronte(descrittore: str = Form(""), dove_torno: str = Form("")):

    from officina.impronte.motore import Coda

    dove_dopo = base.torna_a(dove_torno, "/intelligenza")
    if comune.lavoro_impronte_passata.sta_lavorando:
        return RedirectResponse(dove_dopo, status_code=303)

    archivio = accesso.aperto()
    quali = _quali_in_coda(descrittore, archivio)
    if not quali:
        return RedirectResponse(dove_dopo, status_code=303)
    if in_disparte.A_PARTE:
        in_disparte.lancia(comune.lavoro_impronte_passata, "impronte", archivio.dove.nome,
                           "officina.web.strade.misura:impronte_di_la", (quali,),
                           ferma_con="officina.web.strade.misura:ferma_di_la",
                           racconta="officina.web.in_disparte:racconta_la_coda",
                           applica="officina.web.in_disparte:applica_la_coda")
        return RedirectResponse(dove_dopo, status_code=303)
    comune.coda_impronte = Coda(archivio, quali)
    comune.lavoro_impronte_passata.parti(comune.coda_impronte.esegui, "impronte")
    return RedirectResponse(dove_dopo, status_code=303)


def impronte_di_la(archivio, quali: list[str]):
    from officina.impronte.motore import Coda

    comune.coda_impronte = Coda(archivio, quali)
    comune.lavoro_impronte_passata.parti(comune.coda_impronte.esegui, "impronte")
    return comune.lavoro_impronte_passata


def ferma_di_la() -> None:
    if comune.coda_impronte is not None:
        comune.coda_impronte.ferma()


def parti_le_impronte(archivio) -> None:

    from officina.impronte.motore import Coda

    if comune.lavoro_impronte_passata.sta_lavorando:
        return
    comune.coda_impronte = Coda(archivio, _quali_in_coda("", archivio))
    comune.lavoro_impronte_passata.parti(comune.coda_impronte.esegui, "impronte")


@strada.post("/misura/impronte/ferma")
def ferma_impronte():
    if comune.coda_impronte is not None:
        comune.coda_impronte.ferma()
    comune.lavoro_impronte_passata.aspetta_che_finisca()
    return RedirectResponse("/intelligenza", status_code=303)


def _perche_saltati(motivi: dict[str, int]) -> str:
    if not motivi:
        return ""
    pezzi = [f"{PERCHE_SALTATO.get(motivo, _MOTIVO_SENZA_FRASE)} ({quante})"
             for motivo, quante in sorted(motivi.items())]
    return ", ".join(pezzi)


@strada.get("/api/impronte")
def api_impronte():
    if comune.coda_impronte is None:
        return JSONResponse({"sta_lavorando": False,
                             "guasto": comune.lavoro_impronte_passata.guasto})
    from officina.descrittori import SCHEDE

    adesso = comune.coda_impronte.adesso
    passata = comune.coda_impronte.passata
    di_adesso = passata.avanzamento if passata else None
    return JSONResponse({
        "sta_lavorando": comune.lavoro_impronte_passata.sta_lavorando,
        "guasto": comune.lavoro_impronte_passata.guasto,
        "descrittore": adesso,
        "titolo": SCHEDE[adesso].titolo if adesso else "",
        "in_coda": [SCHEDE[nome].titolo for nome in comune.coda_impronte.nomi],
        "passo": comune.coda_impronte.passo,
        "quanti_modelli": len(comune.coda_impronte.nomi),
        "totale": comune.coda_impronte.totale,
        "fatti": comune.coda_impronte.fatti,
        "impronte": comune.coda_impronte.impronte,
        "percentuale": comune.coda_impronte.percentuale,
        "quanto_manca": comune.coda_impronte.quanto_manca(),
        "saltati": comune.coda_impronte.saltati,
        "perche_saltati": _perche_saltati(comune.coda_impronte.motivi_saltati),
        "quali_saltati": [{"id": scatto_id,
                           "perche": PERCHE_SALTATO.get(motivo, _MOTIVO_SENZA_FRASE)}
                          for scatto_id, motivo in comune.coda_impronte.scatti_saltati],
        "dove_gira": comune.coda_impronte.dove_gira,
        "sta_aprendo": comune.coda_impronte.sta_aprendo,
        "sta_fermando": (comune.coda_impronte.fermata
                         and comune.lavoro_impronte_passata.sta_lavorando),
        "perche_ci_mette": comune.coda_impronte.perche_ci_mette(),
        "nomi": list(comune.coda_impronte.nomi),
        "finiti": [fatta.descrittore for fatta in comune.coda_impronte.finite],
        "adesso_resta": di_adesso.resta if di_adesso else 0,
        "adesso_impronte": di_adesso.impronte if di_adesso else 0,
        "adesso_quanto_manca": di_adesso.quanto_manca() if di_adesso else "",
    })


@strada.post("/misura/usa-il-migliore", dependencies=[Depends(base.solo_da_questo_computer)])
def usa_il_migliore():
    from officina.descrittori import griglia

    archivio = accesso.aperto()
    with archivio.lettura() as connessione:
        ultima = uno(connessione, "SELECT rapporto FROM misure ORDER BY id DESC LIMIT 1")
    vincente = _vincente_di(dict(ultima) if ultima else None)
    if vincente in griglia.MODI:
        archivio.imposta("griglia_come_si_somma", vincente)
    return RedirectResponse("/stato#misura", status_code=303)


@strada.post("/misura/esegui")
def esegui_misura():
    archivio = accesso.aperto()
    comune.lavoro_misura.parti(lambda: _misura_in_sottofondo(archivio), "misura")
    return RedirectResponse("/stato#misura", status_code=303)


def _misura_in_sottofondo(archivio) -> None:
    from officina.misura import banco as officina_banco
    from officina.misura import rapporto as resoconto

    comune.lavoro_misura.di("Preparo gli esempi.")
    misurato = officina_banco.misura(archivio, al_passo=comune.lavoro_misura.di)
    testo = resoconto.come_testo(misurato)
    with archivio.lettura() as connessione:
        sfuggiti = resoconto.fuori_posto(misurato, connessione)
    if sfuggiti:
        guasto = ErroreOfficina(
            "Nel rapporto è finito qualcosa che non doveva uscire, quindi non "
            "te lo mostro. È un difetto del programma.", codice="rapporto_sporco")
        guasto.dettaglio = "\n".join(sfuggiti)
        raise guasto
    with archivio.scrittura() as connessione:
        connessione.execute(
            "INSERT INTO misure (fatta_il, archivio, scatti, gruppi, nodi, "
            "rapporto) VALUES (?, ?, ?, ?, ?, ?)",
            (misurato.fatta_il, archivio.dove.nome, misurato.scatti,
             misurato.gruppi, len(misurato.nodi), resoconto.come_json(misurato)),
        )
    comune.ultima_misura = {"testo": testo, "fatta_il": misurato.fatta_il}
    comune.lavoro_misura.di("Fatto.")


@strada.get("/api/misura")
def api_misura():
    return comune.lavoro_misura.come_va()


def _titolo_corto(titolo: str) -> str:
    return titolo.split(" (")[0]
