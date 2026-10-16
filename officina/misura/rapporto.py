from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

from officina.archivio.database import tutti
from officina.misura.banco import Rapporto, Riga

LARGHEZZA = 78

GIA_ANONIMO = re.compile(r"(?i)(nodo|categoria|scena|persona)[ _-]?\d+")


def conclusioni(rapporto: Rapporto) -> list[str]:
    frasi: list[str] = []
    semplici = [riga for riga in rapporto.righe
                if riga.forza == 1.0 and riga.azzecca is not None]
    if not semplici:
        return ["Nessun nodo ha abbastanza esempi per un voto (regola 244): "
                "servono almeno cinque gruppi da una parte e cinque dall'altra."]

    in_assoluto = rapporto.migliore()
    if in_assoluto is not None and in_assoluto.azzecca is not None:
        frasi.append(
            f"Il migliore è {in_assoluto.descrittore} · "
            f"{in_assoluto.inquadratura} (con il classificatore tenuto stretto a "
            f"{in_assoluto.forza:g}): {_quota(in_assoluto.azzecca)} su "
            f"{in_assoluto.nodi_giudicati} nodi.")

    migliore = max(semplici, key=lambda riga: riga.azzecca)

    disegnato = [riga for riga in semplici if riga.descrittore == "disegnato"]
    if disegnato and migliore.descrittore != "disegnato":
        gratis = max(disegnato, key=lambda riga: riga.azzecca)
        stacco = migliore.azzecca - gratis.azzecca
        frasi.append(
            f"Il descrittore disegnato a mano, che non costa niente, arriva a "
            f"{_quota(gratis.azzecca)}: lo stacco è di {stacco * 100:+.0f} punti."
            + ("  Se lo stacco fosse piccolo, la notte di calcolo dei modelli "
               "grandi sarebbe da rimettere in discussione (regola 343)."
               if stacco < 0.05 else "")
        )
    elif disegnato and migliore.descrittore == "disegnato":
        if len(rapporto.descrittori) > 1:
            frasi.append(
                "Il migliore è il descrittore disegnato a mano, cioè un conto "
                "sui colori. È il risultato più importante che questa misura "
                "possa dare, e va guardato bene prima di crederci: di solito "
                "vuol dire che i nodi si distinguono per il colore o per il "
                "posto, non per cosa c'è dentro.")
        else:
            frasi.append(
                "L'unico descrittore misurato è quello disegnato a mano, che "
                "non è un modello ma un conto sui colori e sui bordi: questa "
                "misura dice come si comporta lui, e non dice niente sui due "
                "modelli grandi. Per confrontarli davvero servono le loro "
                "impronte (regola 105).")

    for descrittore in sorted({riga.descrittore for riga in semplici}):
        suoi = {riga.inquadratura: riga for riga in semplici
                if riga.descrittore == descrittore}
        intera = suoi.get("intera")
        if intera is None:
            continue
        ritagli = [riga for nome, riga in suoi.items()
                   if nome in ("persona", "stretto") and riga.azzecca is not None]
        if not ritagli or intera.azzecca is None:
            continue
        campione = max(ritagli, key=lambda riga: riga.azzecca)
        differenza = campione.azzecca - intera.azzecca
        verso = "batte" if differenza > 0.01 else (
            "pareggia con" if abs(differenza) <= 0.01 else "perde contro")
        frasi.append(
            f"Su {descrittore}, il ritaglio «{campione.inquadratura}» {verso} la "
            f"foto intera ({_quota(campione.azzecca)} contro "
            f"{_quota(intera.azzecca)}) — regole 37, 38."
        )

        tre = suoi.get("tutte e tre")
        if tre is not None and tre.azzecca is not None:
            meglio_da_solo = max([intera] + ritagli, key=lambda riga: riga.azzecca)
            scarto = tre.azzecca - meglio_da_solo.azzecca
            frasi.append(
                f"Su {descrittore}, tenere le tre inquadrature insieme cambia il "
                f"risultato di {scarto * 100:+.0f} punti rispetto alla migliore "
                f"da sola: "
                + ("vale il triplo del tempo di calcolo."
                   if scarto > 0.02 else
                   "non vale il triplo del tempo di calcolo, e la scelta di "
                   "calcolarle tutte e tre va rimessa in discussione "
                   "(regole 37, 343)."))

    for descrittore in sorted({riga.descrittore for riga in semplici}):
        suoi = {riga.inquadratura: riga for riga in semplici
                if riga.descrittore == descrittore}
        col_massimo = suoi.get("caselle · massimo")
        con_la_media = suoi.get("caselle · media")
        if col_massimo is None or con_la_media is None:
            continue
        meglio = max((col_massimo, con_la_media), key=lambda riga: riga.azzecca)
        peggio = con_la_media if meglio is col_massimo else col_massimo
        differenza = meglio.azzecca - peggio.azzecca
        modo = meglio.inquadratura.rsplit(" ", 1)[1]
        intera = suoi.get("intera")
        frase = (
            f"Su {descrittore}, le caselle sommate col {modo} vanno meglio "
            f"({_quota(meglio.azzecca)} contro {_quota(peggio.azzecca)})"
            if differenza > 0.01 else
            f"Su {descrittore}, massimo e media delle caselle pareggiano "
            f"({_quota(col_massimo.azzecca)} e {_quota(con_la_media.azzecca)})")
        if intera is not None and intera.azzecca is not None:
            frase += (f"; la foto intera da sola fa {_quota(intera.azzecca)}"
                      + (", quindi le caselle valgono le notti in più"
                         if meglio.azzecca - intera.azzecca > 0.02 else
                         ", quindi le caselle non valgono le notti in più"))
        frasi.append(frase + " — regola 105.")

    insieme = [riga for riga in semplici if riga.descrittore == "insieme"]
    da_soli = [riga for riga in semplici if riga.descrittore not in ("insieme",)]
    if insieme and da_soli:
        meglio_insieme = max(insieme, key=lambda riga: riga.azzecca)
        meglio_da_solo = max(da_soli, key=lambda riga: riga.azzecca)
        differenza = meglio_insieme.azzecca - meglio_da_solo.azzecca
        frasi.append(
            f"Tenere più descrittori insieme cambia il risultato di "
            f"{differenza * 100:+.0f} punti rispetto al migliore da solo: "
            + ("vale il doppio del tempo di importazione (regola 101)."
               if differenza > 0.02 else
               "non vale il doppio del tempo di importazione, e la regola 101 "
               "va rimessa in discussione (regola 343)."))

    forze = {}
    for riga in rapporto.righe:
        if riga.azzecca is not None and riga.descrittore == migliore.descrittore \
                and riga.inquadratura == migliore.inquadratura:
            forze[riga.forza] = riga.azzecca
    if len(forze) > 1:
        meglio = max(forze, key=lambda f: forze[f])
        normale = forze.get(1.0)
        if normale is not None and forze[meglio] - normale < 0.01:
            frasi.append(
                "Quanto il classificatore si tiene stretto non cambia il "
                f"risultato: da {min(forze):g} a {max(forze):g} resta intorno a "
                f"{_quota(normale)}. Vuol dire che gli esempi bastano a se "
                "stessi, e non c'è niente da regolare.")
        else:
            frasi.append(
                f"Il classificatore va meglio tenendosi stretto a {meglio:g} "
                f"({_quota(forze[meglio])}) invece che a 1 "
                f"({_quota(normale)}).")

    con_vicini = [riga for riga in semplici if riga.vicini is not None]
    if con_vicini:
        campione = max(con_vicini, key=lambda riga: riga.vicini)
        frasi.append(
            f"Cercando per somiglianza, {_quota(campione.vicini)} dei cinque "
            f"scatti più vicini a un «si» sono anche loro «si» "
            f"({campione.chiave.rsplit('/', 1)[0]}). Rispondendo a caso sarebbe "
            f"{_quota(rapporto.caso)}.")

    if rapporto.gruppi < rapporto.scatti * 0.7:
        frasi.append(
            f"Attenzione al campione: {rapporto.scatti} scatti ma solo "
            f"{rapporto.gruppi} gruppi indipendenti (regole 107, 77). Molte di "
            "queste foto sono la stessa scena, e i numeri qui sopra valgono "
            "meno di quanto sembrino.")

    return frasi


def _quota(valore: float | None) -> str:
    return "—" if valore is None else f"{valore * 100:.0f}%"


def _titolo(testo: str) -> str:
    return f"\n{testo}\n{'-' * min(len(testo), LARGHEZZA)}"


def _tabella(righe: list[Riga]) -> list[str]:
    fuori = ["  descrittore   inquadratura   azzecca   vicini   nodi   secondi",
             "  " + "·" * 62]
    for riga in righe:
        fuori.append(
            f"  {riga.descrittore:<12} {riga.inquadratura:<14} "
            f"{_quota(riga.azzecca):>7} {_quota(riga.vicini):>8} "
            f"{riga.nodi_giudicati:>6} {riga.secondi:>9.1f}")
    return fuori


def come_testo(rapporto: Rapporto) -> str:
    fuori = [
        f"MISURA DELLE SCELTE — Officina {rapporto.versione_programma}",
        f"regole 105 e 336 · archivio «{rapporto.archivio}» · {rapporto.fatta_il}",
        "",
        "Questo rapporto contiene solo numeri. Nessun nome di nodo, nessun nome",
        "di file, nessun percorso: si può mostrare a chiunque (regole 106, 112).",
    ]

    fuori.append(_titolo("IL CAMPIONE"))
    fuori.append(f"  scatti decisi ................ {rapporto.scatti}")
    fuori.append(f"  gruppi indipendenti .......... {rapporto.gruppi}"
                 "     (regole 107, 77)")
    fuori.append(f"  nodi con esempi .............. {len(rapporto.nodi)}")
    fuori.append(f"  quota di «si» nel campione ... {_quota(rapporto.caso)}")
    fuori.append("")
    fuori.append("  Le due colonne dei numeri, e cosa vale «a caso» per ognuna:")
    fuori.append("  · «azzecca» conta i «si» e i «no» come due metà uguali, "
                 "quindi a caso è 50%;")
    fuori.append(f"  · «vicini» è quanti dei cinque scatti più simili a un "
                 f"«si» sono «si»: a caso è {_quota(rapporto.caso)}.")
    fuori.append("")
    fuori.append("  nodo        si     no   di cui regalati   gruppi")
    for voce in rapporto.nodi:
        fuori.append(f"  nodo_{voce['nodo']:<7} {voce['si']:>4} {voce['no']:>6} "
                     f"{voce['no_regalati']:>16} {voce['gruppi']:>8}")
    fuori.append("  («regalati» sono i «no» che vengono da un ramo «scegline "
                 "uno» — regola 129)")

    semplici = [riga for riga in rapporto.righe if riga.forza == 1.0]
    fuori.append(_titolo("1. I DESCRITTORI E LE INQUADRATURE (regole 101, 37, 38)"))
    fuori.extend(_tabella(semplici))
    if rapporto.non_confrontati:
        fuori.append("")
        fuori.append("  Non confrontati, perché le loro impronte non sono ancora")
        fuori.append(f"  state calcolate: {', '.join(rapporto.non_confrontati)}.")
        fuori.append("  Non hanno perso: non hanno gareggiato.")

    diverse = [riga for riga in rapporto.righe if riga.forza != 1.0]
    if diverse:
        fuori.append(_titolo("2. QUANTO CONVIENE CHE IL CLASSIFICATORE SI TENGA "
                             "STRETTO (regola 103)"))
        migliore = rapporto.migliore(semplici)
        if migliore is not None:
            fuori.append(f"  a parità di tutto il resto: {migliore.descrittore} · "
                         f"{migliore.inquadratura}")
        fuori.append("")
        fuori.append("  forza    azzecca   nodi")
        fuori.append("  " + "·" * 24)
        tutte = sorted([riga for riga in rapporto.righe
                        if migliore and riga.descrittore == migliore.descrittore
                        and riga.inquadratura == migliore.inquadratura],
                       key=lambda riga: riga.forza)
        for riga in tutte:
            fuori.append(f"  {riga.forza:<8g} {_quota(riga.azzecca):>7} "
                         f"{riga.nodi_giudicati:>6}")

    fuori.append(_titolo("3. NODO PER NODO, COL MIGLIORE (regole 49, 244, 245)"))
    migliore = rapporto.migliore()
    if migliore is None:
        fuori.append("  Nessun nodo ha ancora abbastanza esempi per un voto.")
    else:
        fuori.append(f"  con {migliore.descrittore} · {migliore.inquadratura} · "
                     f"forza {migliore.forza:g}")
        fuori.append("")
        fuori.append("  nodo        azzecca   trovati   a torto   mancati   esempi")
        fuori.append("  " + "·" * 60)
        for nodo_id, voto in sorted(migliore.voti.items()):
            numero = rapporto.numero_di_nodo.get(nodo_id, 0)
            if not voto.abbastanza:
                fuori.append(f"  nodo_{numero:<7} {'troppo pochi esempi per dirlo':>44}")
                continue
            fuori.append(
                f"  nodo_{numero:<7} {_quota(voto.azzecca):>7} "
                f"{voto.azzeccati_si:>9} {voto.proposti_a_torto:>9} "
                f"{voto.mancati:>9} {voto.esempi_si + voto.esempi_no:>8}")

    fuori.append(_titolo("COSA DICONO QUESTI NUMERI"))
    for frase in conclusioni(rapporto):
        fuori.extend("  " + riga for riga in _a_capo(frase, LARGHEZZA - 2))
        fuori.append("")

    fuori.append(f"  misura durata {rapporto.secondi:.0f} secondi.")
    fuori.append("")
    return "\n".join(fuori)


def _a_capo(testo: str, larghezza: int) -> list[str]:
    righe, corrente = [], ""
    for parola in testo.split():
        if len(corrente) + len(parola) + 1 > larghezza:
            righe.append(corrente)
            corrente = parola
        else:
            corrente = f"{corrente} {parola}".strip()
    if corrente:
        righe.append(corrente)
    return righe


def controlla(testo: str, connessione: sqlite3.Connection) -> list[str]:
    trovati: list[str] = []
    minuscolo = testo.lower()

    def guarda(valore: object, che_cos_e: str) -> None:
        if not isinstance(valore, str) or len(valore.strip()) < 3:
            return
        if GIA_ANONIMO.fullmatch(valore.strip()):
            return
        if re.search(rf"\b{re.escape(valore.strip().lower())}\b", minuscolo):
            trovati.append(f"{che_cos_e}: «{valore.strip()}»")

    for riga in tutti(connessione, "SELECT nome, criterio FROM nodi"):
        guarda(riga["nome"], "nome di nodo")
        guarda(riga["criterio"], "criterio di nodo")
    for riga in tutti(connessione, "SELECT percorso FROM cartelle_sorgente"):
        guarda(riga["percorso"], "cartella")
    for riga in tutti(connessione,
                      "SELECT nota FROM scatti WHERE nota IS NOT NULL "
                      "ORDER BY id LIMIT 500"):
        guarda(riga["nota"], "nota")

    for pezzo in re.findall(r"[A-Za-z]:\\[^\s]+|/[^\s]*/[^\s]*", testo):
        if not pezzo.startswith("/misura") and not pezzo.startswith("/statici"):
            trovati.append(f"sembra un percorso: «{pezzo}»")

    return trovati


def scrivi(rapporto: Rapporto, connessione: sqlite3.Connection,
           dove: Path) -> Path:
    testo = come_testo(rapporto)
    numeri = come_json(rapporto)
    sfuggiti = controlla(testo, connessione) + controlla(numeri, connessione)
    if sfuggiti:
        from officina.errori import OperazioneNonPermessa

        raise OperazioneNonPermessa(
            "Nel rapporto è finito qualcosa che non doveva uscire, e quindi "
            "non lo scrivo (regole 106, 110):\n  "
            + "\n  ".join(sfuggiti)
            + "\n  È un difetto del programma, non una tua distrazione.",
            codice="rapporto_sporco",
        )
    dove.parent.mkdir(parents=True, exist_ok=True)
    dove.write_text(testo, encoding="utf-8")
    dove.with_suffix(".json").write_text(numeri, encoding="utf-8")
    return dove


def modo_vincente(dati: dict) -> str | None:
    punti: dict[str, float] = {}
    for riga in dati.get("righe") or []:
        inquadratura = str(riga.get("inquadratura") or "")
        azzecca = riga.get("azzecca")
        if not inquadratura.startswith("caselle · ") or azzecca is None:
            continue
        modo = inquadratura.rsplit(" ", 1)[1]
        punti[modo] = max(punti.get(modo, 0.0), float(azzecca))
    if len(punti) < 2:
        return None
    ordinati = sorted(punti.items(), key=lambda voce: -voce[1])
    if ordinati[0][1] - ordinati[1][1] <= 0.01:
        return None
    return ordinati[0][0]


def come_json(rapporto: Rapporto) -> str:
    return json.dumps({
        "fatta_il": rapporto.fatta_il,
        "versione": rapporto.versione_programma,
        "scatti": rapporto.scatti,
        "gruppi": rapporto.gruppi,
        "caso": round(rapporto.caso, 4),
        "nodi": rapporto.nodi,
        "righe": [{
            "descrittore": riga.descrittore,
            "inquadratura": riga.inquadratura,
            "forza": riga.forza,
            "azzecca": None if riga.azzecca is None else round(riga.azzecca, 4),
            "vicini": None if riga.vicini is None else round(riga.vicini, 4),
            "nodi_giudicati": riga.nodi_giudicati,
            "secondi": round(riga.secondi, 2),
        } for riga in rapporto.righe],
        "conclusioni": conclusioni(rapporto),
    }, indent=2, ensure_ascii=False)
