from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from officina import lingua, registro, ricerca
from officina.archivio import accesso
from officina.archivio.database import uno
from officina.errori import ErroreOfficina
from officina.importazione import miniature
from officina.modello import etichette, nodi, scatti
from officina.web import conteggi
from officina.web import vista

from officina.web.strade import base, comune, doppioni, importazione

strada = APIRouter()


@strada.get("/", response_class=HTMLResponse)
def galleria(richiesta: Request):
    archivio = accesso.aperto()

    if not comune.gia_ripreso:
        comune.gia_ripreso = True
        importazione.raddrizza_i_video_in_sottofondo(archivio)
        importazione.rileggi_le_date_in_sottofondo(archivio)
        importazione.rileggi_le_macchine_in_sottofondo(archivio)
        if not archivio.stato("guida_fatta"):
            with archivio.lettura() as connessione:
                vuoto = uno(connessione, "SELECT count(*) AS q FROM scatti")["q"] == 0
                senza_cartelle = uno(connessione,
                                     "SELECT count(*) AS q FROM cartelle_sorgente")["q"] == 0
            if vuoto and senza_cartelle:
                archivio.salva_stato("guida_fatta", True)
                return RedirectResponse("/benvenuto", status_code=303)
        salvato = archivio.stato("ultimo_filtro")
        if salvato and not richiesta.query_params:
            return RedirectResponse(
                vista.indirizzo(vista.filtro_da_parametri(salvato)), status_code=303
            )

    filtro = vista.filtro_da_parametri(richiesta.query_params)
    base.ricorda_il_filtro(archivio, vista.parametri_da_filtro(
        filtro.copia_con(parole=None, ordine="data_giu") if filtro.parole else filtro))

    with archivio.lettura() as connessione:
        filtro = scatti.risolvi_simili(connessione, filtro)
        quanti = scatti.conta(connessione, filtro)
        primi = doppioni.segna_i_doppioni(connessione, [
            vista.scatto_per_griglia(s)
            for s in scatti.pagina(connessione, filtro, 0, 120)])
        _colora_quelle_senza(primi)

        elenco_nodi = conteggi.voci_dei_nodi(connessione, filtro, vista.indirizzo)
        elenco_persone = conteggi.voci_delle_persone(connessione, filtro,
                                                     vista.indirizzo)
        elenco_luoghi = conteggi.voci_dei_luoghi(connessione, filtro,
                                                 vista.indirizzo)

        elenco_gruppi_archivio = _voci_dei_gruppi(connessione, filtro)

        generi = [
            {"chiave": genere, "nome": nome,
             "collegamento": vista.indirizzo(filtro.copia_con(
                 genere=None if filtro.genere == genere else genere))}
            for genere, nome in (("foto", "Foto"), ("live", "Live"),
                                 ("video", "Video"))]

        pillole = vista.pillole_attive(connessione, filtro)
        frase = vista.frase(connessione, filtro, quanti)

        oltre_la_soglia = None
        if filtro.simili_a is not None:
            oltre_la_soglia = {
                "larghi": filtro.simili_larghi,
                "vuoto": quanti == 0,
                "dove": vista.indirizzo(filtro.copia_con(
                    simili_larghi=not filtro.simili_larghi, simili_ids=None)),
            }

    return base.pagine.TemplateResponse(richiesta, "galleria.html", {
        **base.comune(richiesta, "galleria"),
        "filtro": filtro,
        "gruppi_filtro": [
            _gruppo_di_filtri("nodi", "Nodi", elenco_nodi),
            _gruppo_di_filtri("persone", "Persone", elenco_persone),
            _gruppo_di_filtri("luoghi", "Luoghi", elenco_luoghi),
        ],
        "gruppi_archivio": elenco_gruppi_archivio,
        "conteggio": f"{vista.numero_a_parole(quanti)} scatti",
        "quanti": quanti,
        "nodi_filtro": elenco_nodi,
        "generi": generi,
        "pillole_attive": pillole,
        "frase_filtri": frase,
        "oltre_la_soglia": oltre_la_soglia,
        "campi_nascosti": list(vista.parametri_da_filtro(
            filtro.copia_con(dal=None, al=None)).items()),
        "collegamenti": {
            "tutti": vista.indirizzo(filtro.copia_con(senza_etichetta=False)),
            "senza_etichetta": vista.indirizzo(filtro.copia_con(senza_etichetta=True)),
            "senza_data": vista.indirizzo(filtro.copia_con(senza_data=not filtro.senza_data)),
            "schermate": vista.indirizzo(filtro.copia_con(solo_schermate=not filtro.solo_schermate)),
            "fuori_archivio": vista.indirizzo(filtro.copia_con(fuori_archivio=not filtro.fuori_archivio)),
            "cuore": vista.indirizzo(filtro.copia_con(col_cuore=not filtro.col_cuore)),
            "evidenziati": vista.indirizzo(filtro.copia_con(evidenziati=not filtro.evidenziati)),
        },
        "dati_griglia": vista.json_per_la_pagina({
            "scatti": primi,
            "opzioni": {
                "altezzaRiga": archivio.impostazione("griglia_altezza_riga"),
                "mosaico": bool(archivio.impostazione("griglia_mosaico")),
            },
        }),
    })


QUANTE_VOCI_SUBITO = 6


def _voci_dei_gruppi(connessione, filtro) -> list[dict]:
    from officina.importazione import gruppi

    elenco = gruppi.elenco(connessione)
    if not elenco:
        return []
    dove, parametri = scatti._condizioni(connessione, filtro.copia_con(gruppo=None))
    quanti = gruppi.conteggi(connessione, dove, parametri)
    return [{"id": riga["id"], "nome": riga["nome"], "quanti": quanti.get(riga["id"], 0),
             "attivo": filtro.gruppo == riga["id"],
             "collegamento": vista.indirizzo(filtro.copia_con(
                 gruppo=None if filtro.gruppo == riga["id"] else riga["id"]))}
            for riga in elenco]


def _gruppo_di_filtri(chiave: str, nome: str, voci: list[dict]) -> dict:
    accese = [v for v in voci if v["attivo"]]
    spente = sorted((v for v in voci if not v["attivo"]),
                    key=lambda v: (-v["peso"], v["nome"].lower()))
    quante_restano = max(0, QUANTE_VOCI_SUBITO - len(accese))
    return {
        "chiave": chiave,
        "nome": nome,
        "subito": accese + spente[:quante_restano],
        "dopo": spente[quante_restano:],
        "quante": len(voci),
        "quante_accese": len(accese),
    }


@strada.get("/api/conteggi")
def api_conteggi(richiesta: Request):
    filtro = vista.filtro_da_parametri(richiesta.query_params)
    with accesso.aperto().lettura() as connessione:
        filtro = scatti.risolvi_simili(connessione, filtro)
        return conteggi.della_colonna(connessione, filtro)


@strada.get("/api/griglia")
def api_griglia(richiesta: Request, da: int = 0, quanti: int = 120):
    filtro = vista.filtro_da_parametri(richiesta.query_params)
    with accesso.aperto().lettura() as connessione:
        filtro = scatti.risolvi_simili(connessione, filtro)
        pezzo = doppioni.segna_i_doppioni(connessione, [
            vista.scatto_per_griglia(s)
            for s in scatti.pagina(connessione, filtro, da, min(quanti, 300))])
    _colora_quelle_senza(pezzo)
    return {"scatti": pezzo}


def _colora_quelle_senza(voci: list[dict]) -> None:
    mancano = [v["file_id"] for v in voci if not v.get("colore") and v.get("miniatura")]
    if not mancano:
        return
    try:
        fatti = miniature.colora(accesso.aperto(), mancano)
    except Exception:
        return
    for voce in voci:
        if voce.get("file_id") in fatti:
            voce["colore"] = fatti[voce["file_id"]]


@strada.get("/api/cerca")
def api_cerca(frase: str = "", riformula: bool = False):
    from dataclasses import asdict

    archivio = accesso.aperto()
    frase = (frase or "").strip()
    if not frase:
        return {"frase": "", "vuota": True}
    with archivio.lettura() as connessione:
        risposta = ricerca.cerca(connessione, archivio.dove.modelli, frase,
                                 riformula=riformula)
    return {"frase": frase, "vuota": False,
            "c_e_da_riscrivere": lingua.in_casa(archivio.dove.modelli),
            **asdict(risposta)}


@strada.post("/scatti/in-blocco")
async def in_blocco(richiesta: Request):
    dati = await richiesta.json()
    azione = dati.get("azione")
    numeri = [int(x) for x in dati.get("scatti", [])]

    if dati.get("tutti_i_risultati"):
        filtro = vista.filtro_da_parametri(dati.get("filtro") or {})
        with accesso.aperto().lettura() as connessione:
            filtro = scatti.risolvi_simili(connessione, filtro)
            numeri = [s["id"] for s in scatti.pagina(connessione, filtro, 0, 100000)]

    if not numeri:
        raise ErroreOfficina("Non hai selezionato niente.")

    with accesso.aperto().scrittura() as connessione:
        if azione == "fuori_archivio":
            for numero in numeri:
                scatti.fuori_archivio(connessione, numero, True)
        elif azione == "rimetti_in_archivio":
            for numero in numeri:
                scatti.fuori_archivio(connessione, numero, False)
        elif azione == "non_schermata":
            for numero in numeri:
                connessione.execute(
                    "UPDATE scatti SET sembra_schermata = 0 WHERE id = ?", (numero,))
                connessione.execute(
                    "UPDATE segnalazioni SET risolta = 1 WHERE tipo = 'schermata' "
                    "AND scatto_id = ?", (numero,))
        elif azione == "data_giusta":
            for numero in numeri:
                connessione.execute(
                    "UPDATE scatti SET origine_data = origine_data || '_vista' "
                    "WHERE id = ? AND origine_data IN ('nome', 'file')", (numero,))
        elif azione == "lascia_senza_data":
            for numero in numeri:
                scatti.marca_senza_data(connessione, numero)
        elif azione == "data":
            giorno = dati.get("giorno")
            if not giorno:
                raise ErroreOfficina("Serve una data.")
            for numero in numeri:
                scatti.imposta_data(connessione, numero, f"{giorno}T12:00:00",
                                    fuso_minuti=None, origine="manuale")
                scatti.marca_senza_data(connessione, numero)
        elif azione in ("nodo", "togli_nodo"):
            nodo_id = dati.get("nodo_id")
            if not nodo_id:
                raise ErroreOfficina("Serve un nodo.")
            nodo_id = int(nodo_id)
            if nodi.per_id(connessione, nodo_id) is None:
                raise ErroreOfficina("Quel nodo non c'è più.")
            for numero in numeri:
                if azione == "nodo":
                    etichette.metti(connessione, numero, nodo_id, "si", "utente")
                else:
                    etichette.togli(connessione, numero, nodo_id)
        elif azione in ("cuore", "togli_cuore"):
            for numero in numeri:
                scatti.metti_cuore(connessione, numero, azione == "cuore")
        elif azione in ("stella", "togli_stella"):
            for numero in numeri:
                scatti.metti_stella(connessione, numero, azione == "stella")
        else:
            raise ErroreOfficina(f"Non so fare «{azione}».")

    registro.evento("web.blocco", quanti=len(numeri))
    return {"fatti": len(numeri)}
