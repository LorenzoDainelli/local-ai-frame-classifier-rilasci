from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Form, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response

from officina.archivio import accesso
from officina.archivio.database import tutti, uno
from officina.errori import ErroreOfficina, perche_saltato
from officina.immagini import compatibile, consegna
from officina.importazione import miniature, quicktime
from officina.modello import file_media, scatti, segnalazioni
from officina.miglioria import misura as miglioria_misura
from officina.ritocco import elenco as elenco_ritocchi
from officina.web import miglioramento as miglioramento_web
from officina.web import vista
from officina import istruzioni

from officina.web.strade import base, comune

strada = APIRouter()


COLORI_CORPI = ("#E8613C", "#2F9E8F", "#E0A526", "#5B7BE0", "#C2549E", "#6BAA3A",
                "#8A63D2", "#D2545E")


def _corpi_da_mostrare(connessione, scatto_id: int) -> list[dict]:
    import base64

    from officina import registro
    from officina.corpi import maschere
    from officina.modello import corpi as corpi_mod

    try:
        trovati = [c for c in corpi_mod.di_scatto(connessione, scatto_id) if c["fotogramma"] == 0]
    except Exception as guasto:
        registro.avviso("scatto.corpi_non_letti", **registro.dove_si_e_rotto(guasto))
        return []
    fuori = []
    for numero, corpo in enumerate(trovati):
        colore = COLORI_CORPI[numero % len(COLORI_CORPI)]
        rgb = tuple(int(colore[i:i + 2], 16) for i in (1, 3, 5))
        try:
            png = maschere.in_png(corpo["maschera"], rgb)
        except Exception:
            png = b""
        fuori.append({
            "riquadro": [round(v, 4) for v in corpo["riquadro"]],
            "colore": colore,
            "maschera": ("data:image/png;base64," + base64.b64encode(png).decode("ascii")
                         if png else ""),
            "punti": [[round(x, 4), round(y, 4), round(c, 2)] for x, y, c in corpo["punti"]],
            "volto": corpo["riquadro_volto"],
            "nome": corpo["persona"],
        })
    return fuori


def _c_e_in3d(connessione, scatto_id: int) -> bool:
    import sqlite3

    from officina import registro
    from officina.stanza import in3d

    try:
        return in3d.c_e(connessione, scatto_id)
    except sqlite3.Error as guasto:
        registro.avviso("scatto.in3d_non_letto", **registro.dove_si_e_rotto(guasto))
        return False


@strada.get("/scatto/{scatto_id}", response_class=HTMLResponse)
def uno_scatto(richiesta: Request, scatto_id: int):
    filtro = vista.filtro_da_parametri(richiesta.query_params)
    archivio = accesso.aperto()
    with archivio.lettura() as connessione:
        filtro = scatti.risolvi_simili(connessione, filtro)
        scatto = scatti.per_id(connessione, scatto_id)
        if scatto is None:
            raise ErroreOfficina("Questo scatto non c'è più.")

        file_righe = file_media.di_scatto(connessione, scatto_id)
        principale = next((f for f in file_righe if f["ruolo"] == "principale"), None)
        movimento = next((f for f in file_righe if f["ruolo"] == "movimento"), None)

        elenco_file = []
        percorsi_in_piu = 0
        for riga in file_righe:
            percorsi = file_media.percorsi_di(connessione, riga["id"])
            percorsi_in_piu += max(len(percorsi) - 1, 0)
            elenco_file.append({
                "nome": percorsi[0]["nome"] if percorsi else "?",
                "formato": riga["formato"],
                "peso": vista.peso_a_parole(riga["dimensione"]),
                "presente": any(p["presente"] for p in percorsi),
            })

        intorno = scatti.vicini(connessione, filtro, scatto_id)

        messo_da_parte = uno(
            connessione,
            "SELECT dettaglio FROM segnalazioni WHERE tipo = ? "
            "AND scatto_id = ? AND risolta = 0",
            segnalazioni.NON_SI_APRE, scatto_id)
        non_si_apre = (perche_saltato(messo_da_parte["dettaglio"] or "")
                       if messo_da_parte else None)

        da_leggere = None
        percorso_video = None
        if movimento is not None or (scatto["genere"] == "video" and principale):
            da_leggere = movimento or principale
            percorso_video = file_media.percorso_da_mostrare(connessione, da_leggere["id"])

        miglioria = miglioramento_web.dello_scatto(connessione, scatto_id)
        ritocchi = elenco_ritocchi.quanti_fatti(
            connessione, principale["id"] if principale else None)

        volti_visti = []
        if scatto["genere"] != "video" and principale is not None:
            for riga in tutti(
                    connessione,
                    "SELECT v.riquadro, p.nome FROM volti v "
                    "LEFT JOIN persone p ON p.id = v.persona_id AND p.stato = 'attiva' "
                    "WHERE v.scatto_id = ? AND v.fotogramma = 0 "
                    "AND (v.file_id IS NULL OR v.file_id = ?) ORDER BY v.id",
                    scatto_id, principale["id"]):
                try:
                    volti_visti.append({"riquadro": json.loads(riga["riquadro"]), "nome": riga["nome"]})
                except (TypeError, ValueError):
                    pass

        corpi_visti = (_corpi_da_mostrare(connessione, scatto_id)
                       if scatto["genere"] != "video" and principale is not None else [])
        in3d = (_c_e_in3d(connessione, scatto_id)
                if scatto["genere"] != "video" and principale is not None else False)

        striscia = []
        if scatto["genere"] == "video" and principale is not None:
            striscia = [
                {"numero": riga["fotogramma"], "istante": riga["istante_ms"] or 0,
                 "quando": scatti.durata_a_parole(riga["istante_ms"] or 0)}
                for riga in tutti(
                    connessione,
                    "SELECT DISTINCT fotogramma, istante_ms FROM impronte "
                    "WHERE scatto_id = ? AND inquadratura = 'intera' "
                    "ORDER BY fotogramma", scatto_id)
            ]

    base.ricorda(accesso.aperto(), "ultimo_scatto", scatto_id)
    codec = quicktime.codec_video(percorso_video) if percorso_video is not None else None

    return base.pagine.TemplateResponse(richiesta, "scatto.html", {
        **base.comune(richiesta, "scatto"),
        "scatto": scatto,
        "principale": principale,
        "movimento": movimento,
        "file_dello_scatto": elenco_file,
        "percorsi_in_piu": percorsi_in_piu,
        "vicini": intorno,
        "ritorno": vista.indirizzo(filtro),
        "quando": scatti.giorno_a_parole(scatto["giorno"]) + (
            f" · {scatto['data_locale'][11:16]}" if scatto["data_locale"] else ""),
        "fuso": vista.fuso_a_parole(scatto["fuso_minuti"]),
        "durata": scatti.durata_a_parole(scatto["durata_ms"]),
        "tipo_a_parole": vista.TIPI.get(scatto["genere"], scatto["genere"]),
        "codec": codec,
        "si_riproduce": quicktime.il_browser_lo_apre(codec),
        "copia_pronta": bool(
            da_leggere is not None
            and compatibile.gia_fatta(archivio, da_leggere["impronta"])),
        "copia_si_puo_fare": compatibile.si_puo_fare(),
        "striscia": striscia,
        "non_si_apre": non_si_apre,
        "miglioria": miglioria,
        "volti_visti": volti_visti,
        "corpi_visti": corpi_visti,
        "in3d": in3d,
        "ritocchi": ritocchi,
        "si_puo_migliorare": bool(
            miglioria is None and scatto["larghezza"] and scatto["altezza"]
            and not miglioria_misura.e_gia_grande(scatto["larghezza"],
                                                  scatto["altezza"])),
    })


@strada.get("/una-foto")
def una_foto():
    archivio = accesso.aperto()
    with archivio.lettura() as connessione:
        salvato = archivio.stato("ultimo_scatto")
        quello = scatti.per_id(connessione, int(salvato)) if salvato else None
        if quello is None:
            primo = uno(connessione, "SELECT min(id) AS id FROM scatti "
                                     "WHERE fuori_archivio = 0")
            quello = scatti.per_id(connessione, primo["id"]) if primo and primo["id"] else None
    if quello is None:
        return RedirectResponse("/", status_code=303)
    return RedirectResponse(f"/scatto/{quello['id']}", status_code=303)


@strada.post("/scatto/{scatto_id}/rimetti-in-coda")
def rimetti_in_coda_uno_scatto(scatto_id: int):
    with accesso.aperto().scrittura() as connessione:
        connessione.execute(
            "UPDATE segnalazioni SET risolta = 1 WHERE tipo = ? "
            "AND scatto_id = ? AND risolta = 0",
            (segnalazioni.NON_SI_APRE, scatto_id))
    return RedirectResponse(f"/scatto/{scatto_id}", status_code=303)


@strada.post("/scatto/{scatto_id}/nota")
def salva_nota(richiesta: Request, scatto_id: int, nota: str = Form("")):
    with accesso.aperto().scrittura() as connessione:
        scatti.scrivi_nota(connessione, scatto_id, nota.strip())
    if "application/json" in richiesta.headers.get("accept", ""):
        return {"salvata": True}
    return RedirectResponse(f"/scatto/{scatto_id}", status_code=303)


@strada.post("/elenchi/togli-messo-da-parte/{scatto_id}")
def togli_il_messo_da_parte(scatto_id: int):
    with accesso.aperto().scrittura() as connessione:
        scatti.fuori_archivio(connessione, scatto_id, True)
        connessione.execute(
            "UPDATE segnalazioni SET risolta = 1 WHERE scatto_id = ? AND tipo = ?",
            (scatto_id, segnalazioni.NON_SI_APRE))
    return RedirectResponse("/sistemare#messi-da-parte", status_code=303)


@strada.post("/scatto/{scatto_id}/fuori-archivio")
def metti_fuori(scatto_id: int, fuori: int = Form(1)):
    with accesso.aperto().scrittura() as connessione:
        scatti.fuori_archivio(connessione, scatto_id, bool(fuori))
    return RedirectResponse(f"/scatto/{scatto_id}", status_code=303)


DA_RICONTROLLARE = "private, no-cache"


def segno(*pezzi) -> str:
    import hashlib

    from officina import VERSIONE

    testo = "#".join(str(pezzo) for pezzo in (VERSIONE, *pezzi))
    return 'W/"' + hashlib.sha256(testo.encode("utf-8")).hexdigest()[:32] + '"'


def combacia(chiesto: str | None, atteso: str) -> bool:
    return any(pezzo.strip() in (atteso, atteso[2:], "*") for pezzo in (chiesto or "").split(","))


def gia_ce_l_ha(richiesta: Request, atteso: str) -> bool:
    return combacia(richiesta.headers.get("if-none-match"), atteso)


def non_e_cambiata(atteso: str) -> Response:
    return Response(status_code=304, headers={"ETag": atteso, "Cache-Control": DA_RICONTROLLARE})


def da_ricontrollare(dati: bytes, tipo: str, atteso: str) -> Response:
    return Response(dati, media_type=tipo,
                    headers={"ETag": atteso, "Cache-Control": DA_RICONTROLLARE})


def _cosa_mostrare(file_id: int, sotto: bool = False) -> tuple | None:
    with accesso.aperto().lettura() as connessione:
        riga = file_media.per_id(connessione, file_id)
        if riga is None:
            return None
        quale = file_media.da_mostrare_sotto if sotto else file_media.da_mostrare
        percorso, migliorata = quale(connessione, riga["id"])
    if percorso is None:
        return None
    return riga, percorso, migliorata or riga["impronta"]


def _miniatura_pronta(file_id: int, chiesto: str | None = None) -> tuple | None:
    archivio = accesso.aperto()
    with archivio.lettura() as connessione:
        riga = file_media.per_id(connessione, file_id)
    if riga is None:
        return None
    nome = riga["miniatura"]
    if not nome or combacia(chiesto, segno("miniatura", nome)):
        return riga, nome, None
    return riga, nome, archivio.leggi_miniatura(nome)


def _miniatura_nuova(riga) -> tuple | None:
    archivio = accesso.aperto()
    nome = miniature.per_file(archivio, riga)
    return (nome, archivio.leggi_miniatura(nome)) if nome else None


def _tipo_della_cache(nome: str) -> str:
    return "image/avif" if nome.endswith(".avif") else "image/jpeg"


@strada.get("/miniatura/{file_id}")
async def una_miniatura(richiesta: Request, file_id: int):
    pronta = await consegna.subito(_miniatura_pronta, file_id,
                                   richiesta.headers.get("if-none-match"))
    if pronta is None:
        return Response(status_code=404)
    riga, nome, dati = pronta
    if nome and gia_ce_l_ha(richiesta, segno("miniatura", nome)):
        return non_e_cambiata(segno("miniatura", nome))
    if dati is None:
        fatta = await consegna.a_parte(richiesta, _miniatura_nuova, riga,
                                       filmato=riga["genere"] == "video")
        if fatta is None:
            return Response(status_code=404)
        nome, dati = fatta
    if dati is None:
        return Response(status_code=404)
    return da_ricontrollare(dati, _tipo_della_cache(nome), segno("miniatura", nome))


def _foto_per_browser(percorso: Path, lato: int | None) -> tuple[bytes, str]:
    from officina import schermo

    if schermo.dal_portatile() and not lato:
        return consegna.a_piena_misura(percorso)
    return consegna.per_browser(percorso, consegna.lato_per_guardare(lato))


@strada.get("/immagine/{file_id}")
async def una_immagine(richiesta: Request, file_id: int, lato: int | None = None,
                       sotto: int = 0):
    trovato = await consegna.subito(_cosa_mostrare, file_id, bool(sotto))
    if trovato is None:
        return Response(status_code=404)
    riga, percorso, impronta = trovato

    if riga["genere"] == "video":
        return await _manda_un_fotogramma(richiesta, percorso, impronta, 0, None, lato)

    from officina import schermo

    atteso = segno("immagine", impronta, lato or 0, int(bool(schermo.dal_portatile())))
    if gia_ce_l_ha(richiesta, atteso):
        return non_e_cambiata(atteso)
    fatta = await consegna.a_parte(richiesta, _foto_per_browser, percorso, lato)
    if fatta is None:
        return Response(status_code=404)
    dati, tipo = fatta
    return da_ricontrollare(dati, tipo, atteso)


@strada.get("/fotogramma/{file_id}")
async def un_fotogramma(richiesta: Request, file_id: int, numero: int = 0,
                        istante: int | None = None, lato: int | None = None, sotto: int = 0):
    trovato = await consegna.subito(_cosa_mostrare, file_id, bool(sotto))
    if trovato is None:
        return Response(status_code=404)
    _, percorso, impronta = trovato
    return await _manda_un_fotogramma(richiesta, percorso, impronta, numero, istante, lato)


def _fotogramma_in_cache(percorso: Path, impronta: str, numero: int,
                         istante: int | None, lato: int | None) -> tuple | None:
    from officina.immagini import fotogrammi as estrattore

    misura = consegna.lato_per_guardare(lato)
    chiave = f"fotogramma#{impronta}#{numero}#{istante or 0}#{misura}"
    pronto = consegna.gia_pronte.prendi(chiave)
    if pronto is not None:
        return pronto
    immagine = estrattore.uno(percorso, numero, istante, misura)
    if immagine is None:
        return None
    dati, tipo = consegna.da_immagine(immagine)
    consegna.gia_pronte.metti(chiave, dati, tipo)
    return dati, tipo


async def _manda_un_fotogramma(richiesta: Request, percorso: Path, impronta: str,
                               numero: int, istante: int | None,
                               lato: int | None) -> Response:
    atteso = segno("fotogramma", impronta, numero, istante or 0,
                   consegna.lato_per_guardare(lato))
    if gia_ce_l_ha(richiesta, atteso):
        return non_e_cambiata(atteso)
    fatto = await consegna.a_parte(richiesta, _fotogramma_in_cache, percorso, impronta,
                                   numero, istante, lato, filmato=True)
    if fatto is None:
        return Response(status_code=404)
    dati, tipo = fatto
    return da_ricontrollare(dati, tipo, atteso)


@strada.get("/originale/{file_id}")
def un_originale(richiesta: Request, file_id: int, sotto: int = 0):
    archivio = accesso.aperto()
    with archivio.lettura() as connessione:
        riga = file_media.per_id(connessione, file_id)
        if riga is None:
            return Response(status_code=404)
        quale = file_media.da_mostrare_sotto if sotto else file_media.da_mostrare
        percorso, migliorata = quale(connessione, riga["id"])
    if percorso is None:
        return Response(status_code=404)

    impronta = migliorata or riga["impronta"]
    copia = compatibile.gia_fatta(archivio, impronta)
    tipi = {"mov": "video/mp4", "mp4": "video/mp4", "m4v": "video/mp4"}
    da_mandare = copia or percorso
    tipo = ("video/mp4" if copia is not None
            else tipi.get((riga["formato"] or "").lower(), "application/octet-stream"))
    try:
        stato = da_mandare.stat()
    except OSError:
        return Response(status_code=404)
    atteso = segno("originale", impronta, copia is not None, stato.st_size, stato.st_mtime_ns)
    if gia_ce_l_ha(richiesta, atteso):
        return non_e_cambiata(atteso)
    return FileResponse(da_mandare, media_type=tipo,
                        headers={"ETag": atteso, "Cache-Control": DA_RICONTROLLARE})


@strada.get("/live/{scatto_id}")
def la_live(richiesta: Request, scatto_id: int, sotto: int = 0):
    with accesso.aperto().lettura() as connessione:
        movimento = next((f for f in file_media.di_scatto(connessione, scatto_id)
                          if f["ruolo"] == "movimento"), None)
    if movimento is None:
        return Response(status_code=404)
    return un_originale(richiesta, movimento["id"], sotto)


@strada.post("/scatto/copia-video/{file_id}")
def prepara_la_copia_del_video(file_id: int):
    archivio = accesso.aperto()
    with archivio.lettura() as connessione:
        riga = file_media.per_id(connessione, file_id)
        if riga is None:
            raise ErroreOfficina("Questo file non c'è.")
        percorso, migliorata = file_media.da_mostrare(connessione, riga["id"])
        scatto_id = riga["scatto_id"]
    if percorso is None:
        raise ErroreOfficina(
            "Il file non si trova più dov'era: la copia non si può fare.")
    if not compatibile.si_puo_fare():
        raise ErroreOfficina(
            "Manca il decodificatore che sa scrivere questo formato. Si "
            f"installa {istruzioni.motori_in_una_riga()}.")
    if comune.lavoro_copia_video.sta_lavorando:
        return RedirectResponse(f"/scatto/{scatto_id}", status_code=303)

    durata = riga["durata_ms"] or 0
    comune.lavoro_copia_video.numeri = {"fatti": 0, "totale": durata}
    comune.lavoro_copia_video.parti(
        lambda: _fai_la_copia(archivio, migliorata or riga["impronta"], percorso,
                              durata),
        "copia-video")
    return RedirectResponse(f"/scatto/{scatto_id}", status_code=303)


def _fai_la_copia(archivio, impronta: str, percorso, durata: int) -> None:
    def al_passo(millisecondi: int) -> None:
        comune.lavoro_copia_video.numeri = {"fatti": millisecondi, "totale": durata}

    fatta = compatibile.fai(archivio, impronta, percorso, al_passo=al_passo)
    if fatta is None:
        raise ErroreOfficina(
            "Questo video non si è riuscito a ricodificare. L'originale non "
            "è stato toccato, e i momenti della striscia restano quelli.")
    comune.lavoro_copia_video.numeri = {"fatti": durata, "totale": durata}


@strada.get("/api/copia-video")
def come_va_la_copia_del_video():
    return comune.lavoro_copia_video.come_va()
