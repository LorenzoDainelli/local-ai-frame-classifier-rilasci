from __future__ import annotations

import json
import sqlite3

from officina.archivio.database import tutti, uno
from officina.corpi import VESTITI, chi_e, vestiti_a_parole
from officina.corpi.kpr import VERSIONI
from officina.descrittori import vettori
from officina.importazione.storico import MESI
from officina.modello import persone

CORPI_DA_MOSTRARE = 8
VESTITI_DA_MOSTRARE = 4
VESTITI_DA_GUARDARE = 4000
LUOGHI_DA_MOSTRARE = 5
COMPAGNI_DA_MOSTRARE = 5
NOMI_DI_KPR = {chi_e.KPR[i]: nome for i, nome in enumerate(VERSIONI)}
A_PAROLE_DI_KPR = {"posetrack": "PoseTrack", "market": "Market", "duke": "Duke"}

SQL_DEI_SUOI_CORPI = (
    "SELECT c.id, c.scatto_id, c.file_id, c.area, c.sicurezza, "
    "COALESCE(s.data_locale, s.istante_utc) AS quando "
    "FROM corpi c JOIN scatti s ON s.id = c.scatto_id "
    "LEFT JOIN corpi_delle_persone d ON d.corpo_id = c.id AND d.risposta = 'si' "
    "LEFT JOIN volti v ON v.id = c.volto_id "
    "WHERE COALESCE(d.persona_id, v.persona_id) = ? "
    "ORDER BY quando IS NULL, quando, c.id")

SQL_DEI_SUOI_SCATTI = (
    "SELECT count(*) FROM (SELECT scatto_id FROM volti WHERE persona_id = ? "
    "UNION SELECT scatto_id FROM persone_negli_scatti WHERE persona_id = ?)")

SQL_DEI_LUOGHI = (
    "SELECT p.id, p.nome, count(DISTINCT n.scatto_id) AS volte FROM posti_negli_scatti n "
    "JOIN posti p ON p.id = n.posto_id AND p.stato = 'attivo' "
    "WHERE n.scatto_id IN (SELECT scatto_id FROM volti WHERE persona_id = ? "
    "UNION SELECT scatto_id FROM persone_negli_scatti WHERE persona_id = ?) "
    "GROUP BY p.id ORDER BY volte DESC, p.nome, p.id LIMIT ?")

SQL_DEI_COMPAGNI = (
    "SELECT a.persona_id AS id, p.nome, count(DISTINCT a.scatto_id) AS volte FROM ("
    "SELECT scatto_id, persona_id FROM volti WHERE persona_id IS NOT NULL AND scatto_id IN ("
    "SELECT scatto_id FROM volti WHERE persona_id = ? "
    "UNION SELECT scatto_id FROM persone_negli_scatti WHERE persona_id = ?) "
    "UNION SELECT scatto_id, persona_id FROM persone_negli_scatti WHERE scatto_id IN ("
    "SELECT scatto_id FROM volti WHERE persona_id = ? "
    "UNION SELECT scatto_id FROM persone_negli_scatti WHERE persona_id = ?)) a "
    "JOIN persone p ON p.id = a.persona_id AND p.stato = 'attiva' AND p.nome IS NOT NULL "
    "WHERE a.persona_id != ? GROUP BY a.persona_id "
    "ORDER BY volte DESC, p.nome, p.id LIMIT ?")


def _mese(quando: str | None) -> tuple[int, int] | None:
    if not quando or len(quando) < 7:
        return None
    try:
        anno, mese = int(quando[:4]), int(quando[5:7])
    except ValueError:
        return None
    return (anno, mese) if 1 <= mese <= 12 else None


def mese_a_parole(quando: str | None) -> str:
    trovato = _mese(quando)
    return f"{MESI[trovato[1] - 1]} {trovato[0]}" if trovato else ""


def periodo(primo: str | None, ultimo: str | None) -> str:
    da, a = _mese(primo), _mese(ultimo)
    if da is None or a is None:
        return ""
    if da == a:
        return f"{MESI[da[1] - 1]} {da[0]}"
    if da[0] == a[0]:
        return f"da {MESI[da[1] - 1]} a {MESI[a[1] - 1]} {a[0]}"
    return f"da {MESI[da[1] - 1]} {da[0]} a {MESI[a[1] - 1]} {a[0]}"


def durata(giorni: float) -> str:
    giorni = float(giorni)
    if giorni < 7:
        quanti, uno_solo, tanti = round(giorni), "giorno", "giorni"
    elif giorni < 30:
        quanti, uno_solo, tanti = round(giorni / 7), "settimana", "settimane"
    elif giorni < 365:
        quanti, uno_solo, tanti = round(giorni / 30), "mese", "mesi"
    else:
        quanti, uno_solo, tanti = round(giorni / 365), "anno", "anni"
    quanti = max(int(quanti), 1)
    return f"{quanti} {uno_solo if quanti == 1 else tanti}"


def suoi_corpi(connessione: sqlite3.Connection, persona_id: int) -> list[dict]:
    return [dict(riga) for riga in tutti(connessione, SQL_DEI_SUOI_CORPI, persona_id)]


def sparsi_negli_anni(righe: list[dict], quanti: int = CORPI_DA_MOSTRARE) -> list[dict]:
    numpy = vettori.numpy_o_spiega()
    per_anno: dict[str, list[dict]] = {}
    for riga in righe:
        per_anno.setdefault((riga["quando"] or "")[:4], []).append(riga)
    for elenco in per_anno.values():
        elenco.sort(key=lambda riga: (-(riga["area"] or 0) * (riga["sicurezza"] or 0), riga["id"]))
    anni = sorted(per_anno)
    if len(anni) > quanti:
        anni = [anni[int(round(x))] for x in numpy.linspace(0, len(anni) - 1, quanti)]
    restano = {anno: list(per_anno[anno]) for anno in anni}
    scelti: list[dict] = []
    visti: set[int] = set()
    while len(scelti) < quanti and any(restano[anno] for anno in anni):
        for anno in anni:
            if len(scelti) >= quanti or not restano[anno]:
                continue
            presa = next((riga for riga in restano[anno] if riga["scatto_id"] not in visti),
                         restano[anno][0])
            restano[anno].remove(presa)
            scelti.append(presa)
            visti.add(presa["scatto_id"])
    return sorted(scelti, key=lambda riga: (riga["quando"] or "", riga["id"]))


def _vettori_dei_vestiti(connessione: sqlite3.Connection, corpi: list[int]) -> dict[int, object]:
    numpy = vettori.numpy_o_spiega()
    fuori = {}
    for inizio in range(0, len(corpi), 500):
        for riga in tutti(connessione,
                          "SELECT corpo_id, vettore FROM aspetti WHERE modello = ? "
                          "AND corpo_id IN (SELECT value FROM json_each(?))",
                          VESTITI, json.dumps(corpi[inizio:inizio + 500])):
            fuori[riga["corpo_id"]] = numpy.frombuffer(riga["vettore"], dtype="<f4")
    return fuori


def vestiti_visti(connessione: sqlite3.Connection, righe: list[dict],
                  quanti: int = VESTITI_DA_MOSTRARE) -> dict:
    numpy = vettori.numpy_o_spiega()
    chiavi, matrice = vestiti_a_parole.parole(connessione)
    if not chiavi:
        return {"pronti": False, "capi": []}
    righe = chi_e._a_distanza(righe, VESTITI_DA_GUARDARE)
    numeri = _vettori_dei_vestiti(connessione, [riga["id"] for riga in righe])
    con_vettore = [riga for riga in righe
                   if riga["id"] in numeri and len(numeri[riga["id"]]) == matrice.shape[1]]
    if not con_vettore:
        return {"pronti": True, "capi": []}
    tabella = numpy.stack([numeri[riga["id"]] for riga in con_vettore]).astype(numpy.float32)
    tabella = tabella / numpy.maximum(numpy.linalg.norm(tabella, axis=1, keepdims=True), 1e-8)
    gruppi: dict[tuple[str, ...], list[int]] = {}
    for indice, parti in enumerate(vestiti_a_parole.parti_di_tanti(tabella, chiavi, matrice)):
        if parti:
            gruppi.setdefault(parti, []).append(indice)
    capi = []
    for parti, indici in gruppi.items():
        scatti = {con_vettore[i]["scatto_id"] for i in indici}
        if len(scatti) < 2:
            continue
        centro = tabella[indici].mean(axis=0)
        con_file = [i for i in indici if con_vettore[i]["file_id"] is not None]
        tipico = (con_file[int(numpy.argmax(tabella[con_file] @ centro))] if con_file else None)
        date = sorted(con_vettore[i]["quando"] for i in indici if con_vettore[i]["quando"])
        capi.append({
            "nome": vestiti_a_parole.a_parole(parti),
            "volte": len(scatti),
            "visti": vestiti_a_parole.visti(parti, len(scatti)),
            "quando": periodo(date[0], date[-1]) if date else "",
            "corpo_id": con_vettore[tipico]["id"] if tipico is not None else None,
        })
    capi.sort(key=lambda capo: (-capo["volte"], capo["nome"]))
    return {"pronti": True, "capi": capi[:quanti]}


def luoghi(connessione: sqlite3.Connection, persona_id: int,
           quanti: int = LUOGHI_DA_MOSTRARE) -> list[dict]:
    righe = [dict(riga) for riga in tutti(connessione, SQL_DEI_LUOGHI,
                                          persona_id, persona_id, quanti)]
    massimo = max((riga["volte"] for riga in righe), default=1)
    for riga in righe:
        riga["parte"] = round(100.0 * riga["volte"] / massimo, 1)
    return righe


def compagni(connessione: sqlite3.Connection, persona_id: int,
             quanti: int = COMPAGNI_DA_MOSTRARE) -> list[dict]:
    righe = [dict(riga) for riga in tutti(connessione, SQL_DEI_COMPAGNI, *(persona_id,) * 5,
                                          quanti)]
    for riga in righe:
        copertina = persone.copertina(connessione, riga["id"])
        riga["volto_id"] = copertina["id"] if copertina else None
    return righe


def _risposte(connessione: sqlite3.Connection, persona_id: int) -> tuple[int, int]:
    conte = {riga["risposta"]: riga["quante"] for riga in tutti(
        connessione,
        "SELECT risposta, count(*) AS quante FROM corpi_delle_persone WHERE persona_id = ? "
        "GROUP BY risposta", persona_id)}
    return conte.get("si", 0), conte.get("no", 0)


def _peso_degli_indizi(pesi: dict) -> dict[str, float]:
    return {"la corporatura": sum(pesi[nome] for nome in chi_e.KPR),
            "i vestiti": pesi["vestiti"],
            "le proporzioni del corpo": pesi["corporatura"],
            "il momento, il luogo e chi c'è intorno": pesi["contesto"]}


def _volte(quante: int, una: str, tante: str) -> str:
    return f"{quante} {una if quante == 1 else tante}"


def come_la_riconosce(connessione: sqlite3.Connection, persona_id: int, nome: str | None,
                      corpi: int) -> list[str]:
    if not nome:
        return ["Il volto, quando si vede.",
                "Dal corpo la cerco solo quando ha un nome: dagliene uno e comincio."]
    if not corpi:
        return ["Il volto, quando si vede.",
                "Il suo corpo non l'ho ancora visto: arriva con la prossima passata "
                "dell'intelligenza artificiale."]
    si, no = _risposte(connessione, persona_id)
    dette = [testo for quante, testo in ((si, _volte(si, "conferma", "conferme")), (no, f"{no} no"))
             if quante]
    risposte = ("Imparato da " + " e ".join(dette) + "." if dette
                else "Ancora nessuna tua conferma e nessun no.")
    riga = uno(connessione, "SELECT * FROM pesi_delle_persone WHERE persona_id = ?", persona_id)
    di_tutti, _ = chi_e.pesi_di_tutti(connessione)
    try:
        suoi = json.loads(riga["pesi"]) if riga else None
    except (TypeError, ValueError):
        suoi = None
    if not isinstance(suoi, dict) or set(suoi) != set(chi_e.PESI_DI_BASE):
        suoi = None
    personali = suoi is not None and (
        any(abs(suoi[k] - di_tutti.pesi[k]) > 1e-4 for k in suoi)
        or riga["vestiti_giorni"] != chi_e.GIORNI_DEI_VESTITI
        or riga["corporatura_giorni"] != chi_e.GIORNI_DELLA_CORPORATURA)
    pesi = suoi if personali else di_tutti.pesi
    ordine = sorted(_peso_degli_indizi(pesi).items(), key=lambda voce: -voce[1])
    forti = [nome_indizio for nome_indizio, peso in ordine if peso > 0][:2]
    frasi = ["Il volto, quando si vede."]
    if forti:
        frasi.append("Senza volto conta soprattutto " + forti[0]
                     + (f", poi {forti[1]}." if len(forti) > 1 else "."))
    if not personali:
        frasi.append("Per ora con le regole uguali per tutti: le sue diventano sue dopo "
                     "qualche conferma e qualche no.")
        frasi.append(risposte)
        return frasi
    valori_kpr = {nome_kpr: pesi[nome_kpr] for nome_kpr in chi_e.KPR}
    if max(valori_kpr.values()) - min(valori_kpr.values()) > 0.05:
        migliore = max(valori_kpr, key=valori_kpr.get)
        frasi.append("Per la corporatura qui funziona meglio la versione «"
                     + A_PAROLE_DI_KPR.get(NOMI_DI_KPR[migliore], migliore) + "» di KPR.")
    giorni = float(riga["vestiti_giorni"])
    if giorni > chi_e.GIORNI_DEI_VESTITI:
        frasi.append(f"Rimette spesso gli stessi capi, quindi i vestiti contano per circa "
                     f"{durata(giorni)} invece di {durata(chi_e.GIORNI_DEI_VESTITI)}.")
    elif giorni < chi_e.GIORNI_DEI_VESTITI:
        frasi.append(f"Cambia spesso vestiti, quindi contano solo per circa {durata(giorni)} "
                     f"invece di {durata(chi_e.GIORNI_DEI_VESTITI)}.")
    corporatura = float(riga["corporatura_giorni"])
    if corporatura < chi_e.GIORNI_DELLA_CORPORATURA:
        frasi.append(f"Il corpo è cambiato col tempo: le proporzioni contano per circa "
                     f"{durata(corporatura)} invece di {durata(chi_e.GIORNI_DELLA_CORPORATURA)}.")
    frasi.append(risposte)
    return frasi


def di(connessione: sqlite3.Connection, persona_id: int, nome: str | None) -> dict:
    corpi = suoi_corpi(connessione, persona_id)
    scelti = sparsi_negli_anni([riga for riga in corpi if riga["file_id"] is not None])
    return {
        "scatti": uno(connessione, SQL_DEI_SUOI_SCATTI, persona_id, persona_id)[0],
        "dal_corpo": uno(connessione,
                         "SELECT count(DISTINCT c.scatto_id) AS q FROM corpi_delle_persone d "
                         "JOIN corpi c ON c.id = d.corpo_id "
                         "WHERE d.persona_id = ? AND d.risposta = 'si'", persona_id)["q"],
        "corpi": [{"id": riga["id"], "quando": mese_a_parole(riga["quando"])} for riga in scelti],
        "anni": len({(riga["quando"] or "")[:4] for riga in scelti}),
        "quanti_corpi": len(corpi),
        "vestiti": vestiti_visti(connessione, corpi),
        "luoghi": luoghi(connessione, persona_id),
        "compagni": compagni(connessione, persona_id),
        "come": come_la_riconosce(connessione, persona_id, nome, len(corpi)),
    }
