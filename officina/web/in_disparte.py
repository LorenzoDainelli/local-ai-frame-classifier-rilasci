from __future__ import annotations

import importlib
import multiprocessing
import queue
import threading
import time

from officina import registro
from officina.errori import ErroreOfficina

OGNI_QUANTO = 0.5
TEMPO_PER_CHIUDERSI = 5.0

A_PARTE = True
FILA = "intelligenza"

FILA_VERA = "officina.web.strade.intelligenza:_la_fila_ia"

SI_E_CHIUSA = (
    "L'intelligenza si è chiusa da sola mentre lavorava. Il resto del "
    "programma è a posto: puoi farla ripartire da qui.")


class _Cosa:

    def __init__(self, **dati) -> None:
        self.__dict__.update(dati)


class CodaRiflessa:

    def __init__(self, dati: dict, a: str = FILA) -> None:
        self._dati = dati
        self._a = a
        passata = dati.get("passata")
        self.passata = None if passata is None else _Cosa(
            avanzamento=_Cosa(resta=passata["resta"], impronte=passata["impronte"],
                              quanto_manca=lambda: passata["quanto_manca"]))
        self.finite = [_Cosa(descrittore=nome) for nome in dati.get("finite", [])]

    def __getattr__(self, nome: str):
        dati = self.__dict__.get("_dati", {})
        if nome in dati:
            return dati[nome]
        raise AttributeError(nome)

    @property
    def scatti(self) -> tuple[int, int]:
        fatti, totale = self._dati.get("scatti", (0, 0))
        return fatti, totale

    @property
    def scatti_saltati(self) -> list[tuple[int, str]]:
        return [tuple(coppia) for coppia in self._dati.get("scatti_saltati", [])]

    def quanto_manca(self) -> str:
        return self._dati.get("quanto_manca", "")

    def per_modello(self) -> list[dict]:
        return list(self._dati.get("per_modello", []))

    def perche_ci_mette(self) -> str:
        return self._dati.get("perche_ci_mette", "")

    def ferma(self) -> None:
        _ferma_un_pezzo(self._a, "impronte")


class PassataRiflessa:

    def __init__(self, chiave: str, a: str = FILA) -> None:
        self.chiave = chiave
        self._a = a

    def ferma(self) -> None:
        _ferma_un_pezzo(self._a, self.chiave)


def _ferma_un_pezzo(a: str, chiave: str) -> None:
    if a == FILA:
        manda("ferma_sotto", chiave)
    else:
        ferma(a)


_processi: dict[str, dict] = {}
_lucchetto = threading.Lock()


def sta_girando(a: str = FILA) -> bool:
    processo = _processi.get(a, {}).get("processo")
    return processo is not None and processo.is_alive()


def manda(*comando, a: str = FILA) -> None:
    comandi = _processi.get(a, {}).get("comandi")
    if comandi is None or not sta_girando(a):
        return
    try:
        comandi.put(comando)
    except (OSError, ValueError):
        registro.avviso("intelligenza.comando_perso", lavoro=registro.Parola(a))


def ferma(a: str = FILA) -> None:
    manda("ferma", a=a)


def ferma_tutti() -> None:
    for a in list(_processi):
        ferma(a)


def chiudi(entro: float = TEMPO_PER_CHIUDERSI) -> None:
    ferma_tutti()
    scadenza = time.monotonic() + max(0.0, entro)
    for a, dati in list(_processi.items()):
        processo = dati.get("processo")
        if processo is None:
            continue
        processo.join(timeout=max(0.0, scadenza - time.monotonic()))
        if processo.is_alive():
            registro.avviso("intelligenza.chiusa_per_forza", lavoro=registro.Parola(a))
            processo.terminate()
            processo.join(timeout=2.0)


def _avvia(a: str, bersaglio, argomenti: tuple):
    contesto = multiprocessing.get_context("spawn")
    comandi, notizie = contesto.Queue(), contesto.Queue()
    processo = contesto.Process(target=bersaglio, args=(*argomenti, comandi, notizie),
                                name=a, daemon=True)
    with _lucchetto:
        processo.start()
        _processi[a] = {"processo": processo, "comandi": comandi}
    return processo, notizie


def _ascolta(processo, notizie, ogni_foto) -> dict | None:
    esito = None
    try:
        while True:
            try:
                tipo, foto, dati = notizie.get(timeout=OGNI_QUANTO)
            except queue.Empty:
                if not processo.is_alive():
                    break
                continue
            ogni_foto(foto)
            if tipo == "fine":
                esito = dati or {}
                break
    finally:
        processo.join(timeout=TEMPO_PER_CHIUDERSI)
        if processo.is_alive():
            processo.terminate()
            processo.join(timeout=2.0)
    return esito


def _esito_o_guasto(esito: dict | None, processo) -> None:
    if esito is None:
        registro.errore("intelligenza.chiusa_da_sola", uscita=processo.exitcode)
        raise ErroreOfficina(SI_E_CHIUSA, codice="ia_chiusa")
    if esito.get("guasto"):
        guasto = ErroreOfficina(esito["guasto"], codice=esito.get("codice") or "ia_guasto")
        guasto.dettaglio = esito.get("dettaglio", "")
        raise guasto


def _trova(dove: str):
    modulo, nome = dove.split(":")
    return getattr(importlib.import_module(modulo), nome)


def _della_coda(coda) -> dict | None:
    if coda is None:
        return None
    from officina.descrittori import SCHEDE

    passata = coda.passata
    avanzamento = passata.avanzamento if passata else None
    fatti, totale = coda.scatti
    return {
        "adesso": coda.adesso, "nomi": list(coda.nomi), "passo": coda.passo,
        "totale": coda.totale, "fatti": coda.fatti, "impronte": coda.impronte,
        "percentuale": coda.percentuale, "quanto_manca": coda.quanto_manca(),
        "saltati": coda.saltati, "motivi_saltati": dict(coda.motivi_saltati),
        "scatti_saltati": [list(coppia) for coppia in coda.scatti_saltati],
        "dove_gira": coda.dove_gira, "sta_aprendo": coda.sta_aprendo,
        "fermata": coda.fermata, "perche_ci_mette": coda.perche_ci_mette(),
        "finite": [fatta.descrittore for fatta in coda.finite],
        "scatti": (fatti, totale),
        "per_modello": [{**riga, "titolo": SCHEDE[riga["nome"]].titolo.split(" (")[0]}
                        if riga.get("nome") in SCHEDE else dict(riga)
                        for riga in coda.per_modello()],
        "passata": None if avanzamento is None else {
            "resta": avanzamento.resta, "impronte": avanzamento.impronte,
            "quanto_manca": avanzamento.quanto_manca()},
    }


def _fotografia() -> dict:
    from officina.web.strade import comune, intelligenza

    try:
        coda = _della_coda(comune.coda_impronte)
    except Exception as guasto:
        registro.avviso("intelligenza.coda_non_letta", **registro.dove_si_e_rotto(guasto))
        coda = None
    return {
        "fila": dict(comune.fila_ia),
        "lavori": {chiave: intelligenza.sotto_lavoro_ia(chiave).fotografia()
                   for chiave in intelligenza.IA_IN_FILA},
        "coda": coda,
    }


def _ubbidisci(comandi) -> None:
    from officina.web.strade import comune, intelligenza

    while True:
        try:
            comando = comandi.get_nowait()
        except queue.Empty:
            return
        if comando[0] == "ferma":
            comune.fila_ia["fermata"] = True
            if comune.fila_ia["adesso"]:
                intelligenza._ferma_il_sotto_lavoro(comune.fila_ia["adesso"])
        elif comando[0] == "ferma_sotto":
            intelligenza._ferma_il_sotto_lavoro(comando[1])
        elif comando[0] == "scelti":
            comune.fila_ia["scelti"] = list(comando[1])


def _figlio(nome: str, come: str, scelti: list[str], comandi, notizie) -> None:
    from officina.archivio import accesso

    esito: dict = {}
    try:
        archivio = accesso.apri(nome)
        from officina.web.strade import comune

        comune.fila_ia.update({"scelti": list(scelti), "adesso": "", "fermata": False,
                               "dove_guasto": ""})
        fai = _trova(come)
    except Exception as guasto:
        notizie.put(("fine", None, {"guasto": GUASTO_ALL_AVVIO,
                                    "dettaglio": registro.passi_del_guasto(guasto)}))
        return

    def gira() -> None:
        try:
            fai(archivio)
        except ErroreOfficina as errore:
            esito.update(guasto=errore.messaggio,
                         dettaglio=getattr(errore, "dettaglio", "") or "",
                         codice=errore.codice)
        except Exception as errore:
            from officina.web.lavori import GUASTO_IMPREVISTO

            esito.update(guasto=GUASTO_IMPREVISTO,
                         dettaglio=registro.passi_del_guasto(errore))
            registro.errore("lavoro.rotto", **registro.dove_si_e_rotto(errore))

    filo = threading.Thread(target=gira, name="fila", daemon=True)
    filo.start()
    genitore = multiprocessing.parent_process()
    while filo.is_alive():
        _ubbidisci(comandi)
        if genitore is not None and not genitore.is_alive():
            comune.fila_ia["fermata"] = True
            comandi.put(("ferma",))
        notizie.put(("passo", _fotografia(), None))
        filo.join(OGNI_QUANTO)
    notizie.put(("fine", _fotografia(), esito))
    try:
        accesso.chiudi(con_copia=False)
    except Exception as guasto:
        registro.avviso("intelligenza.archivio_non_chiuso", **registro.dove_si_e_rotto(guasto))


GUASTO_ALL_AVVIO = (
    "L'intelligenza non è riuscita a partire. Il resto del programma è a "
    "posto: riprova tra poco.")


def _applica(foto: dict | None) -> None:
    from officina.web.strade import comune, intelligenza

    if not foto:
        return
    for chiave, valore in foto["fila"].items():
        if chiave != "fermata" or valore:
            comune.fila_ia[chiave] = valore
    for chiave in intelligenza.IA_IN_FILA:
        intelligenza.sotto_lavoro_ia(chiave).rifletti(foto["lavori"][chiave])
    if foto["coda"] is not None:
        comune.coda_impronte = CodaRiflessa(foto["coda"])
    comune.passata_volti = PassataRiflessa("volti")
    comune.passata_corpi = PassataRiflessa("corpi")
    comune.passata_parole = PassataRiflessa("scritte")


def _smetti() -> None:
    from officina.web.strade import comune, intelligenza

    for chiave in intelligenza.IA_IN_FILA:
        intelligenza.sotto_lavoro_ia(chiave).smetti_di_riflettere()
    comune.fila_ia["adesso"] = ""


def ponte(nome: str, scelti: list[str], come: str = FILA_VERA) -> None:
    processo, notizie = _avvia(FILA, _figlio, (nome, come, list(scelti)))
    try:
        esito = _ascolta(processo, notizie, _applica)
    finally:
        _smetti()
    _esito_o_guasto(esito, processo)


def lancia(lavoro, a: str, nome: str, avvio: str, argomenti: tuple = (),
           ferma_con: str = "", racconta: str = "", applica: str = "") -> bool:
    def fai() -> None:
        _ponte_di(lavoro, a, nome, avvio, list(argomenti), ferma_con, racconta, applica)
    return lavoro.parti(fai, a)


def _ponte_di(lavoro, a: str, nome: str, avvio: str, argomenti: list,
              ferma_con: str, racconta: str, applica: str) -> None:
    processo, notizie = _avvia(a, _figlio_di, (nome, avvio, argomenti, ferma_con, racconta))
    metti = _trova(applica) if applica else None

    def ogni_foto(foto: dict | None) -> None:
        if not foto:
            return
        lavoro.rifletti(foto["lavoro"])
        if metti is not None and foto.get("racconto") is not None:
            metti(foto["racconto"])

    try:
        esito = _ascolta(processo, notizie, ogni_foto)
    finally:
        lavoro.smetti_di_riflettere()
    _esito_o_guasto(esito, processo)


def _figlio_di(nome: str, avvio: str, argomenti: list, ferma_con: str, racconta: str,
               comandi, notizie) -> None:
    from officina.archivio import accesso

    try:
        archivio = accesso.apri(nome)
        lavoro = _trova(avvio)(archivio, *argomenti)
        ferma_qui = _trova(ferma_con) if ferma_con else None
        dimmi = _trova(racconta) if racconta else None
    except ErroreOfficina as errore:
        notizie.put(("fine", None, {"guasto": errore.messaggio, "codice": errore.codice,
                                    "dettaglio": getattr(errore, "dettaglio", "") or ""}))
        return
    except Exception as guasto:
        notizie.put(("fine", None, {"guasto": GUASTO_ALL_AVVIO,
                                    "dettaglio": registro.passi_del_guasto(guasto)}))
        return

    def foto() -> dict | None:
        if lavoro is None:
            return None
        racconto = None
        if dimmi is not None:
            try:
                racconto = dimmi()
            except Exception as guasto:
                registro.avviso("intelligenza.racconto_non_letto",
                                **registro.dove_si_e_rotto(guasto))
        return {"lavoro": lavoro.fotografia(), "racconto": racconto}

    genitore = multiprocessing.parent_process()
    fermato = False
    while lavoro is not None and lavoro.sta_lavorando:
        try:
            comando = comandi.get(timeout=OGNI_QUANTO)
        except queue.Empty:
            comando = None
        orfano = genitore is not None and not genitore.is_alive()
        if ferma_qui is not None and not fermato and (orfano or (comando and comando[0] == "ferma")):
            fermato = orfano
            try:
                ferma_qui()
            except Exception as guasto:
                registro.avviso("intelligenza.non_fermata", **registro.dove_si_e_rotto(guasto))
        notizie.put(("passo", foto(), None))
    ultima = foto()
    notizie.put(("fine", ultima, {} if lavoro is None else {
        "guasto": lavoro.guasto, "dettaglio": lavoro.dettaglio}))
    try:
        accesso.chiudi(con_copia=False)
    except Exception as guasto:
        registro.avviso("intelligenza.archivio_non_chiuso", **registro.dove_si_e_rotto(guasto))


def racconta_la_coda() -> dict | None:
    from officina.web.strade import comune

    return _della_coda(comune.coda_impronte)


def applica_la_coda(dati: dict) -> None:
    from officina.web.strade import comune

    comune.coda_impronte = CodaRiflessa(dati, a="impronte")
