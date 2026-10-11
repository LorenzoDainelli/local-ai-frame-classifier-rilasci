from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from officina import registro
from officina.archivio import accesso
from officina.archivio.database import tutti, uno
from officina.errori import ErroreOfficina, perche_saltato
from officina.doppioni import decisioni as doppioni_decisioni
from officina.modello import file_media, scatti, segnalazioni
from officina.modello.scatti import Filtro

from officina.web.strade import base, comune, importazione

strada = APIRouter()


def _cartella_di(percorso: str) -> str:
    pezzi = Path(percorso).parent.parts
    return "/".join(pezzi[-2:]) if pezzi else ""


@strada.get("/elenchi")
def elenchi():
    return RedirectResponse("/sistemare", status_code=303)


@strada.get("/sistemare", response_class=HTMLResponse)
def da_sistemare(richiesta: Request):
    with accesso.aperto().lettura() as connessione:
        conto_doppioni = doppioni_decisioni.il_conto(connessione)
        gruppi_doppioni = doppioni_decisioni.da_decidere(connessione, 0, 3)
        mai_contato = doppioni_decisioni.mai_contato(connessione)
        doppioni_da_guardare = uno(
            connessione,
            "SELECT count(*) AS q FROM file_media "
            "WHERE genere = 'immagine' AND impronta_occhio IS NULL")["q"]
        non_importati = [
            {"id": r["id"], "nome": Path(r["percorso"]).name, "dettaglio": r["dettaglio"]}
            for r in tutti(connessione,
                           "SELECT * FROM non_importati ORDER BY tentato_il DESC LIMIT 200")
        ]
        coppie = tutti(
            connessione,
            "SELECT * FROM segnalazioni WHERE tipo = 'coppia_incerta' AND risolta = 0 LIMIT 50"
        )
        spariti = file_media.non_trovati(connessione)
        messi_da_parte = [
            {"scatto_id": r["scatto_id"],
             "nome": r["nome"] or f"scatto {r['scatto_id']}",
             "perche": perche_saltato(r["dettaglio"] or "")}
            for r in segnalazioni.non_si_aprono(connessione)
        ]
        doppioni = [dict(r) for r in tutti(
            connessione,
            """
            SELECT d.file_id, f.scatto_id, d.quanti,
                   (SELECT nome FROM percorsi q WHERE q.file_id = d.file_id
                    ORDER BY q.id LIMIT 1) AS nome
            FROM (SELECT file_id, count(*) AS quanti FROM percorsi
                  GROUP BY file_id HAVING count(*) > 1) AS d
            JOIN file_media f ON f.id = d.file_id
            ORDER BY d.quanti DESC LIMIT 200
            """,
        )]
        senza_data_voci = [
            {"id": v["id"], "file_id": v.get("file_id"), "nome": v.get("nome") or ""}
            for v in scatti.pagina(connessione, Filtro(senza_data=True), 0, 300)]
        indovinata_voci = [
            {"id": v["id"], "file_id": v.get("file_id"), "nome": v.get("nome") or ""}
            for v in scatti.pagina(connessione, Filtro(data_indovinata=True), 0, 300)]
        schermate_voci = [
            {"id": v["id"], "file_id": v.get("file_id"), "nome": v.get("nome") or ""}
            for v in scatti.pagina(connessione, Filtro(solo_schermate=True), 0, 300)]
        for voce in messi_da_parte:
            riga = uno(connessione,
                       "SELECT id FROM file_media WHERE scatto_id = ? AND ruolo = 'principale' "
                       "LIMIT 1", voce["scatto_id"])
            voce["file_id"] = riga["id"] if riga else None
        conti = {
            "senza_data": scatti.conta(connessione, Filtro(senza_data=True)),
            "data_indovinata": scatti.conta(connessione, Filtro(data_indovinata=True)),
            "schermate": scatti.conta(connessione, Filtro(solo_schermate=True)),
            "doppioni": uno(connessione,
                            "SELECT count(*) AS q FROM segnalazioni "
                            "WHERE tipo = 'doppione_percorso'")["q"],
        }

        for riga in doppioni:
            riga["cartelle"] = [
                _cartella_di(q["percorso"])
                for q in tutti(connessione,
                               "SELECT percorso FROM percorsi WHERE file_id = ? ORDER BY id",
                               riga["file_id"])]

    pila_doppioni = [copia["file_id"] for gruppo in gruppi_doppioni
                     for copia in gruppo["copie"][:1]]
    return base.pagine.TemplateResponse(richiesta, "sistemare.html", {
        **base.comune(richiesta, "sistemare"),
        "conto_doppioni": conto_doppioni,
        "pila_doppioni": pila_doppioni,
        "doppioni_mai_contati": mai_contato,
        "doppioni_da_guardare": doppioni_da_guardare,
        "lavoro_doppioni": comune.lavoro_doppioni.come_va(),
        "non_importati": non_importati,
        "coppie_incerte": coppie,
        "conti": conti,
        "spariti": [{"nome": r["nome"], "genere": r["genere"]} for r in spariti],
        "messi_da_parte": messi_da_parte,
        "doppioni": doppioni,
        "senza_data_voci": senza_data_voci,
        "indovinata_voci": indovinata_voci,
        "schermate_voci": schermate_voci,
    })


def _riprova_una(riga_id: int) -> None:
    motore = importazione.motore_attuale()
    with accesso.aperto().lettura() as connessione:
        riga = uno(connessione, "SELECT * FROM non_importati WHERE id = ?", riga_id)
    if riga is None:
        raise ErroreOfficina("Questa riga non c'è più.")
    percorso = Path(riga["percorso"])
    try:
        motore._importa(percorso)
    except ErroreOfficina as errore:
        motore._segna_non_importato(percorso, errore.codice, errore.messaggio)
        return
    except Exception as errore:                         # noqa: BLE001
        registro.errore("elenchi.riprova_fallita",
                        **registro.dove_si_e_rotto(errore))
        motore._segna_non_importato(
            percorso, "corrotto",
            f"Con «{percorso.name}» è andato storto di nuovo qualcosa che non "
            "avevo previsto. Il file non è stato toccato: resta qui.",
        )
        return
    with accesso.aperto().scrittura() as connessione:
        connessione.execute("DELETE FROM non_importati WHERE id = ?", (riga_id,))


@strada.post("/elenchi/riprova/{riga_id}")
def riprova(riga_id: int):
    _riprova_una(riga_id)
    return RedirectResponse("/sistemare", status_code=303)


@strada.post("/elenchi/riprova-tutti")
def riprova_tutti():
    with accesso.aperto().lettura() as connessione:
        righe = tutti(connessione, "SELECT id FROM non_importati")
    for riga in righe:
        try:
            _riprova_una(riga["id"])
        except ErroreOfficina:
            continue
    return RedirectResponse("/sistemare", status_code=303)


@strada.post("/elenchi/schermate-tienile")
def schermate_tienile():
    with accesso.aperto().scrittura() as connessione:
        connessione.execute(
            "UPDATE segnalazioni SET risolta = 1 WHERE tipo = 'schermata'"
        )
    return RedirectResponse("/sistemare", status_code=303)


@strada.post("/elenchi/schermate-fuori-archivio")
def schermate_fuori():
    with accesso.aperto().scrittura() as connessione:
        connessione.execute(
            "UPDATE scatti SET fuori_archivio = 1 WHERE sembra_schermata = 1"
        )
        connessione.execute(
            "UPDATE segnalazioni SET risolta = 1 WHERE tipo = 'schermata'"
        )
    return RedirectResponse("/sistemare", status_code=303)


@strada.post("/elenchi/controlla-i-file")
def controlla_i_file():
    with accesso.aperto().scrittura() as connessione:
        esito = file_media.controlla_presenza(connessione)
    registro.evento("archivio.controllo_file", spariti=esito["spariti"],
                    tornati=esito["tornati"],
                    rimessi_in_coda=esito["rimessi_in_coda"])
    return RedirectResponse("/sistemare", status_code=303)


@strada.post("/elenchi/riprova-i-messi-da-parte")
def riprova_i_messi_da_parte():
    with accesso.aperto().scrittura() as connessione:
        quanti = segnalazioni.riprova(connessione, segnalazioni.NON_SI_APRE)
    registro.evento("archivio.rimessi_in_coda", quanti=quanti)
    return RedirectResponse("/sistemare", status_code=303)
