from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

from officina import registro
from officina.archivio.database import ora_di_qui, tutti, uno
from officina.errori import ErroreOfficina, PasswordSbagliata
from officina.modello import luoghi, nodi, persone, scatti, telefoni
from officina.telefono import costruzione, formato, selezione
from officina.web import lavori

QUANTE_RIGHE_DI_DIARIO = 12

VICINO_METRI = 200

QUANTE_VOCI_SUBITO = 6


def scelta_di(telefono: sqlite3.Row) -> selezione.Selezione:
    return selezione.Selezione.da_json(telefono["selezione"])


def leggi_la_scelta(campi) -> selezione.Selezione:
    def numeri(chiave: str) -> list[int]:
        grezzo = campi.get(chiave) or ""
        return sorted({int(x) for x in str(grezzo).split(",") if x.strip().isdecimal()})

    def giorno(chiave: str) -> str | None:
        valore = (campi.get(chiave) or "").strip()
        try:
            date.fromisoformat(valore)
        except (TypeError, ValueError):
            return None
        return valore

    def acceso(chiave: str) -> bool:
        return str(campi.get(chiave, "")).lower() in ("1", "si", "true", "on")

    return selezione.Selezione(
        nodi=numeri("nodi"),
        nodi_esclusi=numeri("nodi_esclusi"),
        dal_giorno=giorno("dal"),
        al_giorno=giorno("al"),
        persone=numeri("persone"),
        persone_escluse=numeri("persone_escluse"),
        senza_data=acceso("senza_data"),
    )


def salva_la_scelta(archivio, telefono_id: int,
                    scelta: selezione.Selezione) -> None:
    with archivio.scrittura() as connessione:
        telefoni.salva_selezione(connessione, telefono_id, scelta.a_json())


def voci_dei_nodi(connessione, scelta: selezione.Selezione) -> list[dict]:
    presi = set(scelta.nodi)
    esclusi = set(scelta.nodi_esclusi)
    voci: list[dict] = []

    def scendi(elenco, livello: int, sotto_preso: bool,
               sotto_escluso: bool) -> None:
        for nodo in elenco:
            preso = nodo.id in presi
            escluso = nodo.id in esclusi
            voci.append({
                "id": nodo.id,
                "genitore": nodo.genitore_id,
                "nome": nodo.nome,
                "livello": livello,
                "esempi": nodo.esempi,
                "preso": preso,
                "escluso": escluso,
                "dentro_un_ramo_gia_preso": sotto_preso,
                "dentro_un_ramo_escluso": sotto_escluso,
            })
            scendi(nodo.figli, livello + 1, sotto_preso or preso,
                   sotto_escluso or escluso)

    scendi(nodi.albero(connessione), 0, False, False)
    return voci


def voci_delle_persone(connessione, scelta: selezione.Selezione) -> list[dict]:
    prese = set(scelta.persone)
    escluse = set(scelta.persone_escluse)
    voci = []
    for riga in persone.elenco(connessione):
        if not (riga.get("nome") or "").strip():
            continue
        voci.append({
            "id": riga["id"],
            "nome": riga["nome"],
            "scatti": riga.get("scatti") or 0,
            "presa": riga["id"] in prese,
            "esclusa": riga["id"] in escluse,
        })
    return voci


def quante_se_ne_vanno(connessione, telefono_id: int,
                       scelta: selezione.Selezione,
                       ia: tuple[str, ...] = ()) -> int:
    dove, parametri = selezione.condizioni(connessione, scelta, ia)
    riga = uno(
        connessione,
        f"SELECT count(*) AS quanti FROM pacchetto_file p "
        f"WHERE p.telefono_id = ? AND p.genere = 'originale' "
        f"AND (p.scatto_id IS NULL OR p.scatto_id NOT IN "
        f"     (SELECT s.id FROM scatti s WHERE {dove}))",
        telefono_id, *parametri)
    return riga["quanti"] if riga else 0


_verdetti: dict[str, list] = {}


def dimentica_la_cartella(cartella) -> None:
    _verdetti.pop(str(cartella or ""), None)


def dimentica_le_cartelle() -> None:
    _verdetti.clear()


SCONOSCIUTA = ("La carta d'identità del pacchetto in questa cartella chiede di "
               "calcolare la password in un modo che il programma non usa: forse "
               "qualcuno l'ha modificata. Non lo tocco: svuota la cartella e il "
               "pacchetto si rifà da zero.")


def _verdetto_sulla_cartella(cartella, password: str | None,
                             identificativo: str | None) -> list[dict]:
    dove = Path(cartella) if cartella else None
    if dove is None or not (dove / formato.CARTA).is_file():
        return []
    if str(cartella) in _verdetti:
        return _verdetti[str(cartella)]

    detti: list[dict] = []
    try:
        carta = formato.Carta.leggi(dove)
    except ErroreOfficina as guaio:
        detti.append({"testo": guaio.messaggio, "forte": True})
        _verdetti[str(cartella)] = detti
        return detti

    if carta.archivio and carta.archivio != identificativo:
        detti.append({
            "testo": "In questa cartella c'è già il pacchetto di un altro "
                     "archivio. Non lo tocco: scegli un'altra cartella, "
                     "oppure svuota questa a mano (regola 372).",
            "forte": True})
    elif password:
        try:
            carta.chiave(password)
        except PasswordSbagliata:
            detti.append({
                "testo": "Il pacchetto che c'è in questa cartella ha ancora "
                         "la password precedente. I file già scritti non si "
                         "aprono più con quella di adesso: si rifà da zero, "
                         "e ci vorrà quanto la prima volta.",
                "forte": True})
        except ErroreOfficina as guaio:
            detti.append({"testo": SCONOSCIUTA if guaio.codice == "parametri_sconosciuti"
                          else guaio.messaggio, "forte": True})

    if not carta.completa:
        detti.append({
            "testo": "Il pacchetto là dentro è dichiarato incompleto: "
                     "l'ultimo travaso non è arrivato in fondo. Ripartendo "
                     "si riprende da dov'era (regola 370).",
            "forte": False})
    if carta.piu_vecchio_del_programma():
        detti.append({
            "testo": "Quel pacchetto è in un formato più vecchio di questo "
                     "programma. Si rifà da zero, e ci vorrà quanto la "
                     "prima volta (regola 372).",
            "forte": True})

    _verdetti[str(cartella)] = detti
    return detti


def avvisi(connessione, telefono, stima: selezione.Stima, se_ne_vanno: int,
           password: str | None, identificativo: str | None) -> list[dict]:
    detti: list[dict] = []

    ci_sta = stima.ci_sta_in(telefono["spazio"])
    if ci_sta is False:
        manca = stima.peso - telefono["spazio"]
        detti.append({
            "testo": f"Non ci sta per {selezione.a_misura(manca)}. Stringi la "
                     f"selezione, oppure fai spazio sul telefono: il pacchetto "
                     f"lo preparo lo stesso.",
            "forte": True})
    elif ci_sta is None:
        detti.append({
            "testo": "Quanto spazio ha questo telefono non lo so, quindi non "
                     "posso dirti se ci sta. Se lo scrivi qui sopra, te lo dico.",
            "forte": False})

    if se_ne_vanno:
        detti.append({
            "testo": f"Tolgo {selezione.a_numero(se_ne_vanno)} foto che nel "
                     f"pacchetto ci sono e che questa selezione non prende "
                     f"più. Restano tutte sul computer.",
            "forte": True})

    if not stima.quanti_scatti:
        detti.append({
            "testo": "Questa selezione non prende nessuno scatto. Il pacchetto "
                     "si può fare lo stesso, e sarà vuoto.",
            "forte": True})

    if stima.da_cercare:
        detti.append({
            "testo": (("1 file non è sul disco" if stima.da_cercare == 1 else
                       f"{selezione.a_numero(stima.da_cercare)} file non sono sul disco")
                      + " e l'Archivio sicuro è chiuso: aprilo, se no il pacchetto "
                        "non parte."),
            "forte": True})

    if stima.file_mancanti:
        detti.append({
            "testo": f"{selezione.a_numero(stima.file_mancanti)} file non si "
                     f"trovano più sul disco: non entrano, e il travaso non "
                     f"si ferma per loro (regole 96, 156).",
            "forte": False})

    if stima.versioni_diverse:
        detti.append({
            "testo": (("1 file resta fuori" if stima.versioni_diverse == 1 else
                       f"{selezione.a_numero(stima.versioni_diverse)} file restano fuori")
                      + ": nell'Archivio sicuro c'è solo una versione cambiata dopo "
                        "l'importazione."),
            "forte": False})

    if stima.senza_miniatura:
        detti.append({
            "testo": f"{selezione.a_numero(stima.senza_miniatura)} scatti non "
                     f"hanno ancora una miniatura: la faccio io durante il "
                     f"travaso, e ci metterà un po' di più.",
            "forte": False})

    detti.extend(_verdetto_sulla_cartella(
        telefono["cartella"], password, identificativo))
    return detti


def conto(archivio, telefono_id: int) -> dict:
    ia = selezione.ia_in_casa(archivio.dove.modelli)
    with archivio.lettura() as connessione:
        telefono = telefoni.per_id(connessione, telefono_id)
        if telefono is None:
            raise ErroreOfficina("Questo telefono non c'è più.")
        scelta = scelta_di(telefono)
        stima = selezione.stima(connessione, scelta, ia)
        se_ne_vanno = quante_se_ne_vanno(connessione, telefono_id, scelta, ia)
        identificativo = telefoni.identificativo_se_c_e(connessione)
        detti = avvisi(connessione, telefono, stima, se_ne_vanno,
                       archivio.parola_del_forziere, identificativo)

    return {
        "scelta_a_parole": scelta.a_parole(),
        "quanti_scatti": stima.quanti_scatti,
        "scatti": selezione.a_numero(stima.quanti_scatti),
        "peso": selezione.a_misura(stima.peso),
        "video": selezione.a_numero(stima.quanti_video),
        "peso_video": selezione.a_misura(stima.peso_video),
        "dal": scatti.giorno_a_parole(stima.dal_giorno) if stima.dal_giorno else "",
        "al": scatti.giorno_a_parole(stima.al_giorno) if stima.al_giorno else "",
        "a_parole": stima.a_parole(),
        "tasto": stima.sul_tasto(telefono["nome"]),
        "se_ne_vanno": se_ne_vanno,
        "avvisi": detti,
    }


class InCorso:

    def __init__(self) -> None:
        self.lavoro = lavori.Lavoro("il travaso")
        self.travaso: costruzione.Travaso | None = None
        self.telefono_id: int | None = None
        self.nome = ""
        self.cartella = ""
        self.fase = ""
        self.fatti = 0
        self.quanti = 0
        self.esito: costruzione.Esito | None = None


    def parti(self, archivio, telefono_id: int, cartella: Path,
              password: str) -> bool:
        if self.lavoro.sta_lavorando:
            return False

        with archivio.lettura() as connessione:
            riga = telefoni.per_id(connessione, telefono_id)
            if riga is None:
                raise ErroreOfficina("Questo telefono non c'è più.")

        self.telefono_id = telefono_id
        self.nome = riga["nome"]
        self.cartella = str(cartella)
        self.fase = "preparo"
        self.fatti = 0
        self.quanti = 0
        self.esito = None
        dimentica_la_cartella(cartella)

        travaso = costruzione.Travaso(archivio, telefono_id, cartella, password,
                                      quando_cambia=self._a_che_punto)
        self.travaso = travaso

        def fallo() -> None:
            piano = travaso.prepara()
            self.lavoro.di(f"Selezione: {piano.scelta.a_parole()}")
            self.lavoro.di(piano.stima.a_parole())
            if piano.ripresa:
                self.lavoro.di("C'era un travaso lasciato a metà: riprendo "
                               "da lì.")
            self.lavoro.di(piano.a_parole())
            esito = travaso.esegui(piano)
            self.esito = esito
            self.fase = "finito" if esito.completo else "interrotto"
            self.lavoro.di(
                f"Scritti {esito.scritti} file "
                f"({selezione.a_misura(esito.peso)}), tolti {esito.tolti}, "
                f"riletti e verificati {esito.verificati}.")
            if esito.tornato.c_era:
                self.lavoro.di("Dal telefono è tornato: "
                               + esito.tornato.a_parole())
            for saltato in esito.saltati[:20]:
                self.lavoro.di(f"Non entrato — {saltato.posto}: {saltato.perche}")
            for guasto in esito.guasti[:20]:
                self.lavoro.di(f"NON TORNA — {guasto}")
            dimentica_la_cartella(cartella)
            registro.evento("visore.travaso_da_pagina",
                            scritti=esito.scritti, tolti=esito.tolti,
                            completo=esito.completo)

        return self.lavoro.parti(fallo, nome="travaso")

    def ferma(self) -> None:
        if self.travaso is not None:
            self.travaso.ferma()


    def _a_che_punto(self, fase: str, fatti: int, quanti: int) -> None:
        self.fase = fase
        self.fatti = fatti
        self.quanti = quanti

    @property
    def percentuale(self) -> int:
        if not self.quanti:
            return 0
        return min(100, int(self.fatti * 100 / self.quanti))

    def come_va(self) -> dict:
        detto = self.lavoro.come_va()
        esito = self.esito
        return {
            **detto,
            "telefono_id": self.telefono_id,
            "nome": self.nome,
            "cartella": self.cartella,
            "fase": self.fase,
            "fatti": self.fatti,
            "quanti": self.quanti,
            "percentuale": self.percentuale,
            "scritti": esito.scritti if esito else 0,
            "tolti": esito.tolti if esito else 0,
            "verificati": esito.verificati if esito else 0,
            "peso": selezione.a_misura(esito.peso) if esito else "",
            "completo": bool(esito and esito.completo),
            "interrotto": bool(esito and esito.interrotto),
            "guasti": list(esito.guasti[:20]) if esito else [],
            "saltati": [{"posto": s.posto, "perche": s.perche}
                        for s in (esito.saltati[:20] if esito else [])],
            "quanti_saltati": len(esito.saltati) if esito else 0,
            "tornato": esito.tornato.a_parole() if esito else "",
            "riepilogo": esito.a_parole() if esito else "",
        }


in_corso = InCorso()


def quello_che_e_tornato(connessione, telefono_id: int) -> dict:
    def quanti(sql: str, *parametri) -> int:
        riga = uno(connessione, sql, *parametri)
        return riga["q"] if riga else 0

    cuori = quanti("SELECT count(*) AS q FROM cuori WHERE telefono_id = ? "
                   "AND tolto_il IS NULL", telefono_id)
    tolti = quanti("SELECT count(*) AS q FROM cuori WHERE telefono_id = ? "
                   "AND tolto_il IS NOT NULL", telefono_id)
    raccolte = tutti(
        connessione,
        "SELECT r.id, r.nome, r.creata_il, "
        "       (SELECT count(*) FROM raccolte_scatti x "
        "         WHERE x.raccolta_id = r.id) AS quante "
        "FROM raccolte r WHERE r.telefono_id = ? ORDER BY r.numero",
        telefono_id)
    return {
        "cuori": cuori,
        "tolti_da_applicare": tolti,
        "raccolte": [dict(r) for r in raccolte],
    }


def _quando_a_parole(istante: str | None) -> str:
    if not istante:
        return ""
    qui = ora_di_qui(istante)
    if qui is None:
        giorno, _, ora = str(istante).partition("T")
        detto = scatti.giorno_a_parole(giorno)
        return f"{detto}, {ora[:5]}" if ora[:5] else detto
    return f"{scatti.giorno_a_parole(qui.date().isoformat())}, {qui:%H:%M}"


def _durata_a_parole(secondi: int | None) -> str:
    if not secondi:
        return ""
    if secondi < 60:
        return selezione.conta(int(secondi), "secondo", "secondi")
    minuti = int(round(secondi / 60))
    if minuti < 60:
        return selezione.conta(minuti, "minuto", "minuti")
    ore, restanti = divmod(minuti, 60)
    detto = selezione.conta(ore, "ora", "ore")
    if not restanti:
        return detto
    return detto + " e " + selezione.conta(restanti, "minuto", "minuti")


def _dove_a_parole(posti: list[dict], lat, lon) -> tuple[str, bool]:
    if lat is None or lon is None:
        return "", False
    vicino, quanto = None, None
    for posto in posti:
        distanza = luoghi.distanza_metri(lat, lon, posto["centro_lat"],
                                         posto["centro_lon"])
        if distanza > (posto["raggio_metri"] or 0) + VICINO_METRI:
            continue
        if quanto is None or distanza < quanto:
            vicino, quanto = posto, distanza
    if vicino and (vicino.get("nome") or "").strip():
        return vicino["nome"], True
    numeri = f"{lat:.4f} · {lon:.4f}".replace(".", ",")
    return numeri, False


def diario(connessione, telefono_id: int,
           quante: int = QUANTE_RIGHE_DI_DIARIO) -> dict:
    riga = uno(connessione,
               "SELECT count(*) AS quante, sum(durata_s) AS durata, "
               "       sum(quante_foto) AS foto, min(aperto_il) AS dal "
               "FROM diario_visore WHERE telefono_id = ?", telefono_id)
    righe = tutti(
        connessione,
        "SELECT * FROM diario_visore WHERE telefono_id = ? "
        "ORDER BY aperto_il DESC LIMIT ?", telefono_id, quante)

    posti = luoghi.elenco(connessione) if righe else []
    fuori = []
    for una in righe:
        dove, e_un_luogo = _dove_a_parole(posti, una["latitudine"],
                                          una["longitudine"])
        fuori.append({
            "quando": _quando_a_parole(una["aperto_il"]),
            "durata": _durata_a_parole(una["durata_s"]),
            "quante_foto": una["quante_foto"] or 0,
            "dove": dove,
            "e_un_luogo": e_un_luogo,
        })

    quante_in_tutto = (riga["quante"] if riga else 0) or 0
    return {
        "righe": fuori,
        "quante_in_tutto": quante_in_tutto,
        "non_mostrate": max(0, quante_in_tutto - len(fuori)),
        "durata_in_tutto": _durata_a_parole(riga["durata"] if riga else 0),
        "foto_in_tutto": (riga["foto"] if riga else 0) or 0,
        "dal": _quando_a_parole(riga["dal"] if riga else ""),
    }


def travasi_passati(connessione, telefono_id: int,
                    quanti: int = 8) -> list[dict]:
    fuori = []
    for riga in telefoni.ultimi_travasi(connessione, telefono_id, quanti):
        fuori.append({
            "quando": _quando_a_parole(riga["iniziato_il"]),
            "stato": riga["stato"],
            "scritti": riga["scritti"],
            "tolti": riga["tolti"],
            "saltati": riga["saltati"],
            "peso": selezione.a_misura(riga["peso"] or 0),
            "verificato": riga["verificato"],
            "cartella": riga["cartella"],
        })
    return fuori


def cartella_di(telefono: sqlite3.Row) -> str:
    return telefono["cartella"] or formato.nome_cartella(telefono["nome"])


def spazio_in_gb(byte: int | None) -> str:
    if not byte:
        return ""
    quanti = byte / 1_000_000_000
    for cifre in (0, 1, 2, 3):
        detto = f"{quanti:.{cifre}f}"
        if float(detto) == quanti or cifre == 3:
            break
    if "." in detto:
        detto = detto.rstrip("0").rstrip(".")
    return detto.replace(".", ",")


def gb_dal_campo(testo: str) -> int | None:
    pulito = (testo or "").strip().replace(",", ".")
    if not pulito:
        return None
    try:
        quanti = float(pulito)
    except ValueError:
        raise ErroreOfficina(
            "Lo spazio si scrive in gigabyte, come «128» o «127,5». "
            "Lasciandolo vuoto non te lo chiedo più.") from None
    if quanti <= 0:
        return None
    return int(quanti * 1_000_000_000)
