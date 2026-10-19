from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from officina import forziere, registro
from officina.archivio import accesso
from officina.archivio.database import tutti, uno
from officina.errori import ErroreOfficina
from officina.impostazioni import (PAROLE_AMMESSE, PREDEFINITE, SOLO_QUESTA_MACCHINA,
                                   questa_macchina, valore_ammesso)
from officina.apprendimento import proposte
from officina.modello import dispositivi, fotografie, nodi, persone
from officina.web import blocco
from officina.web import telefono as telefono_web
from officina.web import vista
from officina.programma import aspetto

from officina.web.strade import base, comune, copia_esterna, schermo, tentativi

strada = APIRouter()

solo_qui = [Depends(base.solo_da_questo_computer)]

IMPOSTAZIONI_DEL_COMPUTER = frozenset({
    "accesso_dalla_rete", "porta_del_portatile", "blocco_dopo_minuti",
    "cartella_raccolta"})


@strada.get("/impostazioni", response_class=HTMLResponse)
def impostazioni(richiesta: Request):
    archivio = accesso.aperto()
    spazio_usato = base.dati_dello_spazio(archivio)
    with archivio.lettura() as connessione:
        elenco_dispositivi = dispositivi.elenco(connessione)
        istantanee = fotografie.elenco(connessione, quante=10)
        archiviati = [
            {"nodo_id": riga["id"], "nome": riga["nome"],
             "percorso": (nodi.percorso(connessione, riga["genitore_id"])
                          if riga["genitore_id"] else "radice"),
             "scatti": uno(connessione,
                           "SELECT count(*) AS q FROM etichette "
                           "WHERE nodo_id = ? AND stato = 'si'", riga["id"])["q"]}
            for riga in tutti(connessione,
                              "SELECT id, nome, genitore_id FROM nodi "
                              "WHERE stato = 'congelato' ORDER BY nome")
        ]
        nel_cestino = [
            {"nodo_id": riga["id"], "nome": riga["nome"],
             "percorso": (nodi.percorso(connessione, riga["genitore_id"])
                          if riga["genitore_id"] else "radice"),
             "sotto": len(nodi.discendenti(connessione, riga["id"])) - 1,
             "scatti": nodi.conseguenze_della_cancellazione(
                 connessione, riga["id"])["scatti"]}
            for riga in tutti(connessione,
                              "SELECT n.id, n.nome, n.genitore_id FROM nodi n "
                              "LEFT JOIN nodi p ON p.id = n.genitore_id "
                              "WHERE n.stato = 'cestino' AND (p.id IS NULL "
                              "OR p.stato != 'cestino' "
                              "OR p.cestinato_il != n.cestinato_il) ORDER BY n.nome")
        ]
        cartelle = tutti(connessione,
                         "SELECT percorso, attiva FROM cartelle_sorgente "
                         "ORDER BY percorso")
    return base.pagine.TemplateResponse(richiesta, "impostazioni.html", {
        **base.comune(richiesta, "impostazioni"),
        "voci_aspetto": aspetto.VOCI,
        "versioni_pronte": aspetto.PRONTE,
        "scorciatoie": SCORCIATOIE,
        "quante_miniature": spazio_usato.get("quante", 0),
        "peso_miniature": spazio_usato.get("miniature", "le sto contando"),
        "dispositivi": elenco_dispositivi,
        "porta_aperta": base.la_porta().aperta,
        "portatili": schermo.i_portatili(),
        "portatile_collegato": base.la_porta().collegato(),
        "macchina": questa_macchina(),
        "persone_vive": persone.elenco(connessione),
        "forziere_acceso": forziere.per(archivio.dove).acceso,
        "forziere_peso": vista.peso_a_parole(
            forziere.per(archivio.dove).stato().peso),
        "solo_qui": sorted(SOLO_QUESTA_MACCHINA),
        "fotografie_albero": istantanee,
        "nodi_archiviati": archiviati,
        "nodi_nel_cestino": nel_cestino,
        "quante_cartelle": len(cartelle),
        "copie": copie_esistenti(),
        "copia_esterna": copia_esterna.com_e(),
        "versione_tenuta": _versione_tenuta(richiesta.query_params.get("tenuta")),
        "nodi_rimessi": _nodi_rimessi(richiesta.query_params.get("rimesso")),
    })


def _versione_tenuta(chiesta: str | None) -> str | None:
    nomi = {versione[0] for voce in aspetto.VOCI.values()
            for versione in voce["versioni"].values()}
    return chiesta if chiesta in nomi else None


def _nodi_rimessi(chiesto: str | None) -> int | None:
    if not chiesto or not chiesto.isdecimal() or len(chiesto) > 9:
        return None
    return int(chiesto)


def copie_esistenti() -> list[dict]:
    from officina.archivio import copie as magazzino_copie

    archivio = accesso.aperto()
    return [{"nome": c.nome, "quando": c.quando, "peso": vista.peso_a_parole(c.byte)}
            for c in magazzino_copie.elenco(archivio.dove)[:6]]


@strada.post("/impostazioni/albero/ripristina")
def ripristina_fotografia(numero: int = Form(...)):
    with accesso.aperto().scrittura() as connessione:
        fatto = fotografie.ripristina(connessione, numero)
    comune.pagella_pronta.dimentica()
    return RedirectResponse(
        f"/impostazioni?rimesso={fatto['tornano_al_posto']}", status_code=303)


@strada.post("/impostazioni/azzera-addestramento", dependencies=solo_qui)
def azzera_addestramento():
    comune.bottega = proposte.Bottega()
    comune.pagella_pronta.dimentica()
    quanti = 0
    imparato = accesso.aperto().dove.imparato
    if imparato.is_dir():
        for roba in imparato.iterdir():
            if roba.is_file():
                roba.unlink()
                quanti += 1
    registro.evento("web.azzerato_addestramento", file=quanti)
    return RedirectResponse("/impostazioni?azzerato=1", status_code=303)


@strada.post("/impostazioni/riporta-i-valori", dependencies=solo_qui)
def riporta_i_valori():
    archivio = accesso.aperto()
    with archivio.scrittura() as connessione:
        connessione.execute("DELETE FROM impostazioni")
    archivio._scrivi_valori_di_partenza()
    return RedirectResponse("/impostazioni?rimesse=1", status_code=303)


@strada.post("/impostazioni/dispositivo/{dispositivo_id}", dependencies=solo_qui)
def decidi_dispositivo(dispositivo_id: int, stato: str = Form(...),
                       nome: str = Form("")):
    with accesso.aperto().scrittura() as connessione:
        if stato == "dimentica":
            dispositivi.dimentica(connessione, dispositivo_id)
        else:
            dispositivi.decidi(connessione, dispositivo_id, stato, nome)
    return RedirectResponse("/impostazioni", status_code=303)


def _numero(valore, predefinito: int, minimo: int, massimo: int) -> int:
    try:
        numero = int(valore)
    except (TypeError, ValueError):
        return predefinito
    return min(max(numero, minimo), massimo)


@strada.post("/impostazioni", dependencies=solo_qui)
async def salva_impostazioni(richiesta: Request):
    modulo = await richiesta.form()
    archivio = accesso.aperto()
    forma = modulo.get("filtri_forma")
    archivio.imposta("filtri_forma",
                     forma if forma in PAROLE_AMMESSE["filtri_forma"] else "pillole")
    archivio.imposta("griglia_altezza_riga", _numero(modulo.get("griglia_altezza_riga"), 150, 60, 600))
    archivio.imposta("griglia_mosaico", "griglia_mosaico" in modulo)
    archivio.imposta("movimento", "movimento" in modulo)
    archivio.imposta("miniatura_lato", _numero(modulo.get("miniatura_lato"), 640, 128, 2048))
    archivio.imposta("accesso_dalla_rete", "accesso_dalla_rete" in modulo)
    return RedirectResponse("/impostazioni", status_code=303)


@strada.post("/api/impostazione")
def api_una_impostazione(richiesta: Request, chiave: str = Form(...),
                         valore: str = Form("")):
    if chiave not in PREDEFINITE:
        raise ErroreOfficina(f"«{chiave}» non è un'impostazione di questo programma.")
    if chiave in IMPOSTAZIONI_DEL_COMPUTER:
        base.solo_da_questo_computer(richiesta)

    predefinito = PREDEFINITE[chiave]
    if isinstance(predefinito, bool):
        pulito = valore.strip().lower() in ("1", "si", "true", "on")
    elif isinstance(predefinito, int):
        try:
            pulito = int(valore)
        except (TypeError, ValueError) as errore:
            raise ErroreOfficina(f"«{valore[:40]}» non è un numero.") from errore
    else:
        pulito = valore

    try:
        pulito = valore_ammesso(chiave, pulito)
    except ValueError as errore:
        raise ErroreOfficina(
            f"Per «{chiave}» questa scelta il programma non la conosce.") from errore
    accesso.aperto().imposta(chiave, pulito)
    return {"chiave": chiave, "valore": pulito}


@strada.post("/impostazioni/svuota-miniature")
def svuota_miniature():
    from officina.archivio import spazio

    archivio = accesso.aperto()
    archivio.svuota_miniature()
    spazio.ricalcola(archivio.dove.miniature, archivio.dove.database)
    return RedirectResponse("/impostazioni", status_code=303)


@strada.post("/impostazioni/copia")
def copia_adesso():
    accesso.aperto().copia_adesso("manuale")
    return RedirectResponse("/stato#salute", status_code=303)


@strada.post("/impostazioni/copia/rimetti", dependencies=solo_qui)
def rimetti_copia(nome: str = Form(...)):
    from officina.archivio import copie
    copie.prenota(accesso.aperto().dove, nome)
    return RedirectResponse("/stato#archivio", status_code=303)


@strada.post("/impostazioni/copia/disdici", dependencies=solo_qui)
def disdici_copia():
    from officina.archivio import copie
    copie.disdici(accesso.aperto().dove)
    return RedirectResponse("/stato#archivio", status_code=303)


@strada.get("/blocco", response_class=HTMLResponse)
def pagina_blocco(richiesta: Request):
    archivio = accesso.aperto()
    chi = blocco.chi_e(richiesta)
    if not blocco.guardia.e_bloccato(chi):
        return RedirectResponse("/", status_code=303)
    attesa = tentativi.freno.da_aspettare(chi)
    return base.pagine.TemplateResponse(richiesta, "blocco.html", {
        "request": richiesta,
        "attributi_aspetto": aspetto.attributi_html(aspetto.leggi()),
        "impostazioni": archivio.tutte_le_impostazioni(),
        "sbagliata": bool(richiesta.query_params.get("sbagliata")),
        "occupato": tentativi.MESSAGGIO_OCCUPATO if richiesta.query_params.get("occupato") else "",
        "aspetta": tentativi.messaggio_di_attesa(attesa) if attesa else "",
        "con_windows": chi == "qui" and _c_e_il_sigillo(),
    })


def _c_e_il_sigillo() -> bool:
    from officina.impostazioni import REALE
    from officina.programma import sigillo

    return sigillo.c_e(REALE)


@strada.post("/blocco/apri")
def apri_il_blocco(richiesta: Request, password: str = Form("")):
    chi = blocco.chi_e(richiesta)
    dove = accesso.aperto().dove
    giusta, _, occupato = tentativi.freno.prova(
        chi, lambda: blocco.guardia.sblocca(chi, dove, password))
    if occupato:
        return RedirectResponse("/blocco?sbagliata=1&occupato=1", status_code=303)
    if not giusta:
        return RedirectResponse("/blocco?sbagliata=1", status_code=303)
    return RedirectResponse("/", status_code=303)


@strada.post("/blocco/adesso")
def blocca_adesso(richiesta: Request):
    archivio = accesso.aperto()
    if not forziere.per(archivio.dove).acceso:
        raise ErroreOfficina(
            "Non c'è un forziere su questo archivio: senza password non ci "
            "sarebbe modo di rientrare. Si accende da Impostazioni.")
    blocco.guardia.blocca_adesso(blocco.chi_e(richiesta))
    return {"bloccato": True}


def _lega_a_windows(nome: str, password: str) -> bool:
    from officina.programma import sigillo

    if sigillo.come_si_puo() is None:
        return False
    sigillo.sigilla(nome, password)
    return True


def _slega_da_windows(nome: str) -> None:
    from officina.programma import sigillo

    try:
        sigillo.togli(nome)
    except Exception as guasto:
        registro.errore("forziere.sigillo_non_tolto", **registro.dove_si_e_rotto(guasto))


_DA_MOSTRARE: dict[str, tuple[str, str]] = {}
LETTERE_CHIARE = "abcdefghjkmnpqrstuvwxyz23456789"
SENZA_WINDOWS = ("Su questo computer non trovo né Windows Hello né la password di Windows, "
                 "quindi non posso tenerla io: scrivi tu una password.")


@strada.post("/forziere/accendi", dependencies=solo_qui)
def accendi_il_forziere(password: str = Form(""), ancora: str = Form(""),
                        su_carta: str = Form(""), dove_torno: str = Form("")):
    archivio = accesso.aperto()
    nome = archivio.dove.nome
    dove = base.torna_a(dove_torno, "/impostazioni#c6")

    if not su_carta:
        raise ErroreOfficina(
            "Metti la spunta: senza quella password l'archivio non si apre "
            "più, e non esiste un modo per recuperarla. Scrivila da qualche "
            "parte prima di continuare.")
    if password != ancora:
        raise ErroreOfficina(
            "Le due password non coincidono. Non ho toccato niente.")
    creata = not password
    if creata:
        password = _password_a_caso()

    cassa = forziere.per(archivio.dove)
    if cassa.acceso:
        raise ErroreOfficina(
            "Questo archivio ha già un forziere. Per cambiare la password si "
            "apre e si richiude con quella nuova.")

    forziere._password_utile(password)
    legata = _lega_a_windows(nome, password)
    if creata and not legata:
        raise ErroreOfficina(SENZA_WINDOWS)

    accesso.chiudi(con_copia=False)
    try:
        cassa.accendi(password)
    except Exception:
        if legata:
            _slega_da_windows(nome)
        accesso.apri(nome)
        raise
    accesso.apri(nome, password)
    telefono_web.dimentica_le_cartelle()
    if creata:
        gettone = secrets.token_urlsafe(24)
        _DA_MOSTRARE.clear()
        _DA_MOSTRARE[gettone] = (password, dove)
        return RedirectResponse(f"/forziere/creata?g={gettone}", status_code=303)
    return RedirectResponse(dove, status_code=303)


def _password_a_caso() -> str:
    return "-".join("".join(secrets.choice(LETTERE_CHIARE) for _ in range(5)) for _ in range(6))


@strada.get("/forziere/creata", response_class=HTMLResponse, dependencies=solo_qui)
def mostra_la_password_creata(richiesta: Request, g: str = ""):
    trovata = _DA_MOSTRARE.pop(g, None) if g else None
    if trovata is None:
        return RedirectResponse("/impostazioni#c6", status_code=303)
    password, dove = trovata
    risposta = base.pagine.TemplateResponse(richiesta, "forziere-creato.html", {
        "request": richiesta,
        "attributi_aspetto": aspetto.attributi_html(aspetto.leggi()),
        "impostazioni": accesso.aperto().tutte_le_impostazioni(),
        "password": password,
        "dove": dove,
    })
    risposta.headers["Cache-Control"] = "no-store"
    return risposta


SCORCIATOIE = [
    {"nome": "Nella galleria", "voci": [
        ("clic", "apre lo scatto"),
        ("Maiusc + clic", "seleziona un intervallo (regola 121)"),
        ("Ctrl + clic", "aggiunge o toglie uno scatto dalla selezione"),
        ("Ctrl + A", "seleziona tutti quelli caricati"),
        ("Esc", "lascia la selezione"),
        ("barra spaziatrice", "ingrandisce senza perdere il posto (regola 161)"),
        ("frecce", "si sposta fra gli scatti"),
        ("/", "apre la ricerca a parole (regola 350)"),
        ("A", "apre l'albero, e Esc riporta qui"),
    ]},
    {"nome": "Mentre etichetti", "voci": [
        ("da 0 a 9", "applica il nodo con quel numero"),
        ("frecce", "scatto precedente e successivo"),
        ("barra spaziatrice", "fa partire o ferma il video"),
        ("barra spaziatrice tenuta", "su uno scatto ritoccato mostra lo scatto vero, finché la tieni "
                                     "(regola 562)"),
        ("L", "accende la live photo accanto allo scatto (regola 192)"),
        ("C", "cuore: lo mette fra i preferiti (regola 424)"),
        ("M", "lo mette da parte: esce dalla coda e va negli evidenziati"),
        ("/", "va al campo dove si cerca o si crea un nodo"),
        ("A", "apre l'albero, e Esc riporta all'etichettatura"),
        ("Ctrl+Z", "annulla l'ultima etichetta"),
        ("Esc", "chiude quello che è aperto"),
    ]},
    {"nome": "Nel banco della misura", "voci": [
        ("da 1 a 9", "mette lo scatto nel mucchio con quel numero"),
        ("0", "«nessuno di questi»: un «no» detto, che vale quanto un "
              "«si» (regola 56)"),
        ("S", "salta: resta indeciso, che non è un «no» (regole 55, 75)"),
        ("frecce", "avanti e indietro fra gli scatti"),
        ("Esc", "torna alla misura"),
    ]},
    {"nome": "Nella revisione del miglioramento", "voci": [
        ("A", "approva: la migliorata prende il posto dell'originale"),
        ("R", "rifiuta: la copia si cancella"),
        ("freccia a destra", "decidi dopo, e passa alla prossima"),
        ("barra spaziatrice", "fa partire e ferma i due video insieme"),
        ("+ − 0", "ingrandisce, rimpicciolisce, torna intera"),
    ]},
    {"nome": "Nella sfida alla cieca", "voci": [
        ("1 o A", "vince la versione A"),
        ("2 o B", "vince la versione B"),
        ("3", "pari"),
        ("4", "nessuna delle due: si cancellano tutte e due"),
        ("L", "mostra e nasconde la lente sotto i tre riquadri"),
        ("+ − 0", "ingrandisce, rimpicciolisce, torna intera"),
    ]},
    {"nome": "Dappertutto", "voci": [
        ("Esc", "chiude quello che è aperto"),
    ]},
]
