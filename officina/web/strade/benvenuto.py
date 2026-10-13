from __future__ import annotations

from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from officina import forziere, prova, registro
from officina.archivio import accesso
from officina.archivio.database import uno
from officina.errori import ErroreOfficina
from officina.impostazioni import FINTO
from officina.modello import impronte as magazzino_impronte
from officina.web import giro
from officina.web import vista

from officina.web.strade import base, comune, importazione, misura, modelli

strada = APIRouter()

solo_qui = [Depends(base.solo_da_questo_computer)]


@strada.get("/benvenuto", response_class=HTMLResponse)
def benvenuto(richiesta: Request):
    archivio = accesso.aperto()
    return base.pagine.TemplateResponse(richiesta, "benvenuto.html", {
        **base.comune(richiesta, ""), "passo": 1,
        "prova": prova.controlla(archivio),
        "forziere_peso": vista.peso_a_parole(
            forziere.per(archivio.dove).stato().peso),
    })


@strada.get("/benvenuto/chiave", response_class=HTMLResponse)
def benvenuto_chiave(richiesta: Request):
    from officina import modelli_in_casa
    from officina.corpi import scaricamento as scarica_corpi
    from officina.miglioria import lucidflux_pesi

    return base.pagine.TemplateResponse(richiesta, "benvenuto-chiave.html", {
        **base.comune(richiesta, ""), "passo": 2,
        "pagina_del_cancello": lucidflux_pesi.PAGINA_DEL_CANCELLO,
        "pagina_dinov3": modelli_in_casa.PAGINA_DINOV3,
        "pagina_sam3": modelli_in_casa.PAGINA_SAM3,
        "pagina_corpo3d": scarica_corpi.PAGINA_CORPO3D,
        "pagina_vggt": scarica_corpi.vggt.PAGINA,
    })


@strada.get("/benvenuto/modelli", response_class=HTMLResponse)
def benvenuto_modelli(richiesta: Request):
    archivio = accesso.aperto()
    return base.pagine.TemplateResponse(richiesta, "benvenuto-modelli.html", {
        **base.comune(richiesta, ""), "passo": 3,
        "modelli": modelli.come_stanno_i_modelli(archivio.dove.modelli),
        "scaricamento": comune.lavoro_modelli.come_va(),
    })


@strada.post("/giro/parti", dependencies=solo_qui)
def giro_parti():

    if comune.lavoro is not None and comune.lavoro.sta_lavorando:
        raise ErroreOfficina(
            "C'è un'importazione in corso. Il giro guidato cambia archivio, e "
            "non lo fa mentre stai lavorando: aspetta che finisca, oppure "
            "fermala dall'Importazione.")
    if giro.stato.in_corso:
        return RedirectResponse(giro.PASSI[0]["dove"], status_code=303)

    giro.stato.lo_ha_fatto_il_giro = not giro.gia_c_era_un_archivio_finto()

    accesso.chiudi()
    accesso.apri(FINTO)
    comune.piano_pronto = None

    cartella = giro.costruisci()
    giro.stato.cartella_foto = cartella

    motore = importazione.motore_attuale()
    motore.prepara([cartella])
    comune.lavoro.parti()

    giro.stato.passo = 1
    registro.evento("giro.parte")
    return RedirectResponse(giro.PASSI[0]["dove"], status_code=303)


@strada.post("/giro/avanti")
def giro_avanti():
    if not giro.stato.in_corso:
        return RedirectResponse("/benvenuto/pronto", status_code=303)
    if giro.stato.passo >= len(giro.PASSI):
        return giro_esci()
    giro.stato.passo += 1
    return RedirectResponse(giro.stato.passo_adesso()["dove"], status_code=303)


@strada.post("/giro/indietro")
def giro_indietro():
    if not giro.stato.in_corso:
        return RedirectResponse("/benvenuto/pronto", status_code=303)
    giro.stato.passo = max(1, giro.stato.passo - 1)
    return RedirectResponse(giro.stato.passo_adesso()["dove"], status_code=303)


@strada.post("/giro/esci")
def giro_esci():

    if comune.lavoro is not None:
        comune.lavoro.ferma()
        comune.lavoro = None

    giro.stato.passo = None
    giro.torna_al_tuo()
    detto = giro.butta_via()
    registro.evento("giro.finito")

    dove = "/benvenuto/pronto?giro=finito"
    if detto:
        dove += "&" + urlencode({"detto": detto})
    return RedirectResponse(dove, status_code=303)


@strada.get("/benvenuto/cartella", response_class=HTMLResponse)
def benvenuto_cartella(richiesta: Request):
    from officina.importazione import scansione

    with accesso.aperto().lettura() as connessione:
        elenco_cartelle = scansione.cartelle(connessione)

    return base.pagine.TemplateResponse(richiesta, "benvenuto-cartella.html", {
        **base.comune(richiesta, ""), "passo": 4,
        "cartelle": elenco_cartelle,
        "piano": importazione.piano_a_parole(),
    })


@strada.get("/benvenuto/lavoro", response_class=HTMLResponse)
def benvenuto_lavoro(richiesta: Request):
    from officina.descrittori import SCHEDE, pronti

    archivio = accesso.aperto()
    motore = importazione.motore_attuale()
    stato = motore.stato()
    with archivio.lettura() as connessione:
        gia_fatte = uno(connessione, "SELECT count(*) AS q FROM impronte")["q"]
        avanzamento = magazzino_impronte.avanzamento(connessione)
        quanti_scatti = misura.quanti_scatti_in_archivio(connessione)

    return base.pagine.TemplateResponse(richiesta, "benvenuto-lavoro.html", {
        **base.comune(richiesta, ""), "passo": 5,
        "stato": stato,
        "mai_importato": motore.importazione_id is None,
        "impronte_fatte": gia_fatte,
        "descrittori_pronti": pronti(archivio.dove.modelli),
        "schede": SCHEDE,
        **misura.contesto_impronte(archivio, avanzamento, quanti_scatti),
    })


@strada.get("/benvenuto/pronto", response_class=HTMLResponse)
def benvenuto_pronto(richiesta: Request):
    archivio = accesso.aperto()
    with archivio.lettura() as connessione:
        quanti = uno(connessione,
                     "SELECT count(*) AS q FROM scatti WHERE fuori_archivio = 0")["q"]
        con_impronta = uno(connessione, "SELECT count(*) AS q FROM impronte")["q"]
        primo = uno(connessione,
                    "SELECT id FROM scatti WHERE fuori_archivio = 0 "
                    "ORDER BY id LIMIT 1")

    return base.pagine.TemplateResponse(richiesta, "benvenuto-pronto.html", {
        **base.comune(richiesta, ""), "passo": 6,
        "giro_gia_costruito": giro.gia_c_era_un_archivio_finto(),
        "quanti": quanti,
        "con_impronta": con_impronta,
        "primo": primo["id"] if primo else None,
    })
