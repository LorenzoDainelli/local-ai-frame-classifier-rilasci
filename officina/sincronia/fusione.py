from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from officina.archivio.database import adesso, inserisci, tutti, uno
from officina.errori import ErroreOfficina
from officina.impostazioni import PREDEFINITE, VIAGGIANO, valore_ammesso
from officina.modello import cambiamenti, persone as modello_persone, telefoni
from officina.modello.nodi import SEPARATORE
from officina.sincronia import formato, lettore

TOLLERANZA_MINUTI = 5

MISURA_MINIATURA = 640


@dataclass
class Esito:
    mittente: str = ""
    dal_seriale: int = 0
    al_seriale: int = 0
    gesti_applicati: int = 0
    gesti_gia_visti: int = 0
    nodi_creati: int = 0
    nodi_rinominati: int = 0
    nodi_spostati: int = 0
    nodi_cestinati: int = 0
    nodi_risorti: int = 0
    etichette_messe: int = 0
    etichette_tolte: int = 0
    etichette_perse: int = 0
    scatti_nuovi: int = 0
    file_nuovi: int = 0
    originali_copiati: int = 0
    miniature_copiate: int = 0
    impronte_prese: int = 0
    persone_nominate: int = 0
    persone_da_guardare: int = 0
    cuori_arrivati: int = 0
    telefoni_nuovi: int = 0
    impostazioni_arrivate: int = 0
    impostazioni_contese: int = 0
    note: list = field(default_factory=list)

    @property
    def qualcosa_e_cambiato(self) -> bool:
        return bool(self.gesti_applicati or self.nodi_creati or self.file_nuovi
                    or self.impronte_prese or self.persone_nominate
                    or self.persone_da_guardare or self.cuori_arrivati
                    or self.impostazioni_arrivate or self.impostazioni_contese)


def controlla_gli_orologi(carta: formato.Carta,
                          tolleranza_minuti: int = TOLLERANZA_MINUTI) -> None:
    try:
        fatto = datetime.strptime(carta.fatto_il, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc)
    except (TypeError, ValueError):
        raise ErroreOfficina(
            "Il pacchetto non dice quando è stato fatto: senza quella data "
            "non posso decidere niente sulle cose che si contraddicono.",
            codice="ora_illeggibile") from None

    avanti = fatto - datetime.now(timezone.utc)
    if avanti > timedelta(minutes=tolleranza_minuti):
        minuti = int(avanti.total_seconds() // 60)
        raise ErroreOfficina(
            f"Questo pacchetto risulta fatto fra {minuti} minuti, cioè nel "
            "futuro: i due computer non hanno lo stesso orario. Non fondo "
            "niente, perché quando due etichette si contraddicono decido in "
            "base all'ora e sceglierei a caso. Sistema l'orologio di uno dei "
            "due computer e rifai il pacchetto.",
            codice="orologi_lontani")


def controlla_che_non_manchi_niente(carta: formato.Carta,
                                    gia_visto: int) -> None:
    if carta.dal_seriale > gia_visto:
        mancano = carta.dal_seriale - gia_visto
        raise ErroreOfficina(
            f"Questo pacchetto comincia dal cambiamento numero "
            f"{carta.dal_seriale + 1}, ma di «{carta.mittente_nome}» io sono "
            f"arrivato solo al {gia_visto}: in mezzo ne mancano {mancano}, e "
            "non sono in nessun pacchetto che ho qui. Non fondo niente, "
            "perché andrei avanti lasciandomi indietro quei cambiamenti "
            "per sempre. Rifai il pacchetto sull'altro computer: quello nuovo "
            "ripartirà da dove sono io davvero.",
            codice="buco_nei_cambiamenti")


def _figlio(connessione: sqlite3.Connection, genitore_id: int | None,
            nome: str) -> sqlite3.Row | None:
    return uno(
        connessione,
        "SELECT * FROM nodi WHERE nome = ? AND ifnull(genitore_id, -1) = ifnull(?, -1) "
        "ORDER BY stato = 'attivo' DESC, id LIMIT 1",
        nome, genitore_id)


def nodo_al_sentiero(connessione: sqlite3.Connection,
                     sentiero: str | None) -> int | None:
    if not sentiero:
        return None
    genitore = None
    for nome in sentiero.split(SEPARATORE):
        riga = _figlio(connessione, genitore, nome.strip())
        if riga is None:
            return None
        genitore = riga["id"]
    return genitore


def _crea_il_sentiero(connessione: sqlite3.Connection, sentiero: str,
                      esito: Esito) -> int:
    genitore = None
    for nome in sentiero.split(SEPARATORE):
        nome = nome.strip()
        riga = _figlio(connessione, genitore, nome)
        if riga is None:
            genitore = inserisci(
                connessione,
                "INSERT INTO nodi (genitore_id, nome, creato_il) VALUES (?, ?, ?)",
                genitore, nome, adesso())
            esito.nodi_creati += 1
        else:
            genitore = riga["id"]
    return genitore


def _ultimo_gesto_mio(connessione: sqlite3.Connection, scatto_id: int,
                      nodo_id: int) -> sqlite3.Row | None:
    macchina = cambiamenti.questa_macchina(connessione)
    return uno(
        connessione,
        "SELECT * FROM cambiamenti WHERE macchina_id = ? AND cosa = 'etichetta' "
        "AND scatto_id = ? AND nodo_id = ? ORDER BY seriale DESC LIMIT 1",
        macchina["id"], scatto_id, nodo_id)


def _a_parita_resto_io(chi_sono: str, chi_arriva: str) -> bool:
    return chi_sono < chi_arriva


def _cede_il_posto(connessione: sqlite3.Connection, scatto_id: int, nodo_id: int,
                   quando: str, chi_sono: str = "", chi_arriva: str = "") -> bool:
    mio = _ultimo_gesto_mio(connessione, scatto_id, nodo_id)
    if mio is not None:
        if mio["avvenuto_il"] == quando:
            return _a_parita_resto_io(chi_sono, chi_arriva)
        return mio["avvenuto_il"] > quando

    riga = uno(connessione,
               "SELECT origine, creata_il FROM etichette "
               "WHERE scatto_id = ? AND nodo_id = ?", scatto_id, nodo_id)
    if riga is None:
        return False
    if riga["origine"] == "sistema":
        return False
    if riga["creata_il"] == quando:
        return _a_parita_resto_io(chi_sono, chi_arriva)
    return riga["creata_il"] > quando


def _etichetta(connessione: sqlite3.Connection, gesto: sqlite3.Row,
               scatto_id: int, esito: Esito, chi_sono: str = "",
               chi_arriva: str = "") -> None:
    sentiero = gesto["sentiero"]
    azione = gesto["azione"]
    if not sentiero:
        esito.note.append("un'etichetta arriva senza il nodo a cui appartiene")
        return

    nodo_id = nodo_al_sentiero(connessione, sentiero)
    if nodo_id is None:
        if azione == "tolta":
            return
        nodo_id = _crea_il_sentiero(connessione, sentiero, esito)

    if _cede_il_posto(connessione, scatto_id, nodo_id, gesto["avvenuto_il"],
                      chi_sono, chi_arriva):
        esito.etichette_perse += 1
        return

    riga_nodo = uno(connessione, "SELECT stato FROM nodi WHERE id = ?", nodo_id)
    if azione != "tolta" and riga_nodo is not None and riga_nodo["stato"] == "cestino":
        connessione.execute(
            "UPDATE nodi SET stato = 'attivo', cestinato_il = NULL WHERE id = ?",
            (nodo_id,))
        esito.nodi_risorti += 1

    if azione == "tolta":
        connessione.execute(
            "DELETE FROM etichette WHERE scatto_id = ? AND nodo_id = ?",
            (scatto_id, nodo_id))
        esito.etichette_tolte += 1
        return

    connessione.execute(
        """
        INSERT INTO etichette (scatto_id, nodo_id, stato, origine, creata_il)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(scatto_id, nodo_id) DO UPDATE SET
            stato = excluded.stato, origine = excluded.origine,
            sicurezza = NULL, creata_il = excluded.creata_il
        """,
        (scatto_id, nodo_id, gesto["stato"] or "si", gesto["origine"] or "utente",
         gesto["avvenuto_il"]))
    esito.etichette_messe += 1


def _nodo(connessione: sqlite3.Connection, gesto: sqlite3.Row,
          esito: Esito) -> None:
    sentiero = gesto["sentiero"]
    azione = gesto["azione"]
    if not sentiero:
        return

    if azione in ("rinominato", "spostato"):
        prima = _chiave_di_riga(gesto, "valore_prima")
        vecchio = nodo_al_sentiero(connessione, prima) if prima else None
        if vecchio is not None and nodo_al_sentiero(connessione, sentiero) is None:
            pezzi = sentiero.split(SEPARATORE)
            padre = (_crea_il_sentiero(connessione, SEPARATORE.join(pezzi[:-1]), esito)
                     if len(pezzi) > 1 else None)
            connessione.execute(
                "UPDATE nodi SET nome = ?, genitore_id = ? WHERE id = ?",
                (pezzi[-1].strip(), padre, vecchio))
            if azione == "rinominato":
                esito.nodi_rinominati += 1
            else:
                esito.nodi_spostati += 1
            return

    if azione == "stato" and gesto["valore"] in ("cestino", "congelato", "attivo"):
        nodo_id = nodo_al_sentiero(connessione, sentiero)
        if nodo_id is None:
            return
        if gesto["valore"] == "cestino" and _usato_dopo(connessione, nodo_id,
                                                        gesto["avvenuto_il"]):
            esito.nodi_risorti += 1
            esito.note.append(
                f"«{sentiero}» era stato cestinato sull'altro computer, ma qui "
                "l'hai usato dopo: l'ho lasciato al suo posto.")
            return
        connessione.execute(
            "UPDATE nodi SET stato = ?, cestinato_il = ? WHERE id = ?",
            (gesto["valore"], adesso() if gesto["valore"] == "cestino" else None,
             nodo_id))
        if gesto["valore"] == "cestino":
            esito.nodi_cestinati += 1
        return

    _crea_il_sentiero(connessione, sentiero, esito)


def _usato_dopo(connessione: sqlite3.Connection, nodo_id: int, quando: str) -> bool:
    macchina = cambiamenti.questa_macchina(connessione)
    riga = uno(
        connessione,
        "SELECT 1 AS c FROM cambiamenti WHERE macchina_id = ? AND cosa = 'etichetta' "
        "AND nodo_id = ? AND azione IN ('messa','cambiata') AND avvenuto_il > ? "
        "LIMIT 1",
        macchina["id"], nodo_id, quando)
    return riga is not None


def _chiave_di_riga(riga: sqlite3.Row, nome: str):
    try:
        return riga[nome]
    except (IndexError, KeyError):
        return None


IMPRONTA_VALIDA = re.compile(r"[0-9a-f]{64}")
FORMATO_VALIDO = re.compile(r"[a-z0-9]{1,8}")


def _impronta_valida(impronta) -> bool:
    return isinstance(impronta, str) and IMPRONTA_VALIDA.fullmatch(impronta) is not None


def _formato_valido(formato) -> bool:
    return formato is None or (isinstance(formato, str)
                               and FORMATO_VALIDO.fullmatch(formato) is not None)


def _dove_va(archivio, impronta: str, formato_file) -> Path:
    coda = formato_file if _formato_valido(formato_file) else "dat"
    return archivio.dove.ricevute / impronta[:2] / f"{impronta}.{coda}"


def _metti_la_miniatura(archivio, pacchetto: lettore.Aperto, riga) -> str:
    coda = riga["mini_formato"] if _formato_valido(riga["mini_formato"]) else "jpg"
    nome = archivio.nome_miniatura(riga["impronta"], MISURA_MINIATURA, coda)
    archivio.scrivi_miniatura(nome, pacchetto.contenuto(riga["mini_posto"]))
    return nome


def _tira_fuori_l_originale(archivio, pacchetto: lettore.Aperto, riga,
                            esito: Esito) -> bool:
    impronta = riga["impronta"]
    dove = _dove_va(archivio, impronta, riga["formato"])
    if dove.is_file() and (not riga["dimensione"]
                           or dove.stat().st_size == riga["dimensione"]):
        return True
    if pacchetto.tira_fuori(riga["posto"], dove, atteso=impronta) != impronta:
        esito.note.append(
            f"un file del pacchetto non corrisponde alla sua "
            f"impronta e non l'ho tenuto: {impronta[:12]}")
        return False
    esito.originali_copiati += 1
    return True


def _metti_al_sicuro_i_file(archivio, pacchetto: lettore.Aperto, esito: Esito,
                            avanzamento: Callable[[int, int], None] | None
                            ) -> tuple[set[str], dict[str, str]]:
    with archivio.lettura() as connessione:
        con_miniatura = {r["impronta"] for r in connessione.execute(
            "SELECT impronta FROM file_media WHERE miniatura IS NOT NULL")}
    pronti: set[str] = set()
    miniature: dict[str, str] = {}
    quanti = pacchetto.quanti_file()
    for numero, riga in enumerate(pacchetto.ogni_file(), start=1):
        impronta = riga["impronta"]
        if _impronta_valida(impronta):
            if riga["posto"] and _tira_fuori_l_originale(archivio, pacchetto,
                                                         riga, esito):
                pronti.add(impronta)
            if riga["mini_posto"] and impronta not in con_miniatura:
                miniature[impronta] = _metti_la_miniatura(archivio, pacchetto, riga)
        if avanzamento is not None:
            avanzamento(numero, quanti)
    return pronti, miniature


def _porta_dentro_le_cose(archivio, pacchetto: lettore.Aperto,
                          esito: Esito, pronti: set[str],
                          miniature: dict[str, str]) -> dict:
    connessione = archivio.connessione
    capi: dict[str, int] = {}

    def scatto_per(capo: str) -> int | None:
        if capo in capi:
            return capi[capo]
        riga = uno(connessione,
                   "SELECT scatto_id FROM file_media WHERE impronta = ?", capo)
        if riga is not None and riga["scatto_id"]:
            capi[capo] = riga["scatto_id"]
            return capi[capo]
        descrizione = pacchetto.scatto(capo)
        if descrizione is None:
            return None
        capi[capo] = inserisci(
            connessione,
            "INSERT INTO scatti (genere, data_locale, fuso_minuti, istante_utc, "
            "giorno, origine_data, latitudine, longitudine, larghezza, altezza, "
            "durata_ms, sembra_schermata, nota, creato_il) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            descrizione["genere"] or "foto", descrizione["data_locale"],
            descrizione["fuso_minuti"], descrizione["istante_utc"],
            descrizione["giorno"], descrizione["origine_data"] or "assente",
            descrizione["latitudine"], descrizione["longitudine"],
            descrizione["larghezza"], descrizione["altezza"],
            descrizione["durata_ms"], descrizione["sembra_schermata"] or 0,
            descrizione["nota"], adesso())
        esito.scatti_nuovi += 1
        return capi[capo]

    for riga in pacchetto.ogni_file():
        impronta = riga["impronta"]
        if not _impronta_valida(impronta):
            esito.note.append("un file del pacchetto ha un'impronta che non torna e "
                              "non l'ho preso")
            continue
        if not _formato_valido(riga["formato"]):
            riga = {**dict(riga), "formato": None}
        scatto_id = scatto_per(riga["capo"]) if riga["capo"] else None
        gia = uno(connessione, "SELECT * FROM file_media WHERE impronta = ?", impronta)

        if gia is None:
            file_id = inserisci(
                connessione,
                "INSERT INTO file_media (impronta, dimensione, genere, formato, "
                "larghezza, altezza, orientamento, durata_ms, identificatore_ios, "
                "data_locale, fuso_minuti, istante_utc, origine_data, latitudine, "
                "longitudine, sembra_schermata, scatto_id, ruolo, aggiunto_il) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                impronta, riga["dimensione"] or 0, riga["genere"] or "immagine",
                riga["formato"], riga["larghezza"], riga["altezza"],
                riga["orientamento"], riga["durata_ms"], riga["identificatore_ios"],
                riga["data_locale"], riga["fuso_minuti"], riga["istante_utc"],
                riga["origine_data"] or "assente", riga["latitudine"],
                riga["longitudine"], riga["sembra_schermata"] or 0,
                scatto_id, riga["ruolo"], adesso())
            esito.file_nuovi += 1
        else:
            file_id = gia["id"]

        if riga["posto"] and impronta in pronti:
            dove = _dove_va(archivio, impronta, riga["formato"])
            _registra_percorso(connessione, file_id, dove, riga["nome"] or dove.name)

        if riga["mini_posto"] and not (gia and gia["miniatura"]):
            nome = miniature.get(impronta) or _metti_la_miniatura(archivio, pacchetto, riga)
            connessione.execute("UPDATE file_media SET miniatura = ? WHERE id = ?",
                                (nome, file_id))
            esito.miniature_copiate += 1

    for riga in pacchetto.impronte():
        scatto_id = capi.get(riga["capo"])
        if scatto_id is None:
            scatto_id = scatto_per(riga["capo"])
        if scatto_id is None:
            continue
        prima = uno(connessione,
                    "SELECT id FROM impronte WHERE scatto_id = ? AND descrittore = ? "
                    "AND versione = ? AND inquadratura = ? AND fotogramma = ?",
                    scatto_id, riga["descrittore"], riga["versione"],
                    riga["inquadratura"], riga["fotogramma"])
        if prima is not None:
            continue
        connessione.execute(
            "INSERT INTO impronte (scatto_id, descrittore, versione, inquadratura, "
            "metodo, riquadro, fotogramma, istante_ms, dimensione, valori, "
            "calcolata_il) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (scatto_id, riga["descrittore"], riga["versione"], riga["inquadratura"],
             riga["metodo"], riga["riquadro"], riga["fotogramma"], riga["istante_ms"],
             riga["dimensione"], riga["valori"], riga["calcolata_il"]))
        esito.impronte_prese += 1

    return capi


def _registra_percorso(connessione: sqlite3.Connection, file_id: int,
                       dove: Path, nome: str) -> None:
    testo = str(dove)
    if uno(connessione, "SELECT id FROM percorsi WHERE percorso = ?", testo):
        connessione.execute(
            "UPDATE percorsi SET presente = 1, visto_il = ?, file_id = ? "
            "WHERE percorso = ?", (adesso(), file_id, testo))
        return
    inserisci(connessione,
              "INSERT INTO percorsi (file_id, percorso, nome, visto_il) "
              "VALUES (?, ?, ?, ?)", file_id, testo, nome, adesso())


def _porta_dentro_le_persone(connessione: sqlite3.Connection,
                             pacchetto: lettore.Aperto, esito: Esito) -> None:
    dove_sta: dict[str, list[dict]] = {}
    for riga in pacchetto.persone_scatti():
        dove_sta.setdefault(riga["nome"], []).append(
            {"impronta": riga["impronta"], "a_mano": riga["a_mano"]})

    for persona in pacchetto.persone():
        nome = persona["nome"]
        righe = dove_sta.get(nome, [])
        scatti, a_mano = [], []
        for voce in righe:
            trovato = uno(connessione,
                          "SELECT scatto_id FROM file_media WHERE impronta = ?",
                          voce["impronta"])
            if trovato is None or trovato["scatto_id"] is None:
                continue
            scatti.append(trovato["scatto_id"])
            if voce["a_mano"]:
                a_mano.append(trovato["scatto_id"])

        omonima = modello_persone.omonimi(connessione, nome)
        if omonima:
            qui_e = omonima[0]["id"]
        else:
            mucchi = _mucchi_di(connessione, scatti)
            if not mucchi:
                esito.note.append(
                    f"«{nome}» c'è sull'altro computer, ma qui i volti di "
                    "quelle fotografie non sono ancora stati cercati: passa i "
                    "volti e al prossimo pacchetto le do il nome.")
                continue
            if len(mucchi) > 1:
                for prima in range(len(mucchi)):
                    for dopo in range(prima + 1, len(mucchi)):
                        modello_persone.segna_forse(
                            connessione, mucchi[prima], mucchi[dopo], 0.0)
                        esito.persone_da_guardare += 1
                esito.note.append(
                    f"sull'altro computer «{nome}» è una persona sola, qui è "
                    f"divisa in {len(mucchi)}. Non le unisco io (regola 408): "
                    "te le ho messe affiancate nel cassetto dei «forse».")
                continue
            qui_e = mucchi[0]
            gia = uno(connessione, "SELECT nome FROM persone WHERE id = ?", qui_e)
            if gia is not None and gia["nome"]:
                continue
            modello_persone.chiama(connessione, qui_e, nome)
            esito.persone_nominate += 1

        for scatto_id in a_mano:
            modello_persone.metti_a_mano(connessione, scatto_id, qui_e)


def _mucchi_di(connessione: sqlite3.Connection,
               scatti: list[int]) -> list[int]:
    if not scatti:
        return []
    segni = ",".join("?" for _ in scatti)
    righe = tutti(
        connessione,
        f"SELECT DISTINCT v.persona_id AS id FROM volti v "
        f"JOIN persone p ON p.id = v.persona_id "
        f"WHERE v.scatto_id IN ({segni}) AND v.persona_id IS NOT NULL "
        f"AND p.stato <> 'cestino'", *scatti)
    return sorted(riga["id"] for riga in righe)


def _porta_dentro_i_cuori(connessione: sqlite3.Connection,
                          pacchetto: lettore.Aperto, esito: Esito) -> None:
    conosciuti: dict[str, int] = {}
    for riga in pacchetto.cuori():
        nome = (riga["telefono"] or "").strip()
        if not nome:
            continue
        telefono_id = conosciuti.get(nome)
        if telefono_id is None:
            gia = telefoni.per_nome(connessione, nome)
            if gia is not None:
                telefono_id = gia["id"]
            else:
                telefono_id = telefoni.crea(connessione, nome,
                                            riga["sistema"] or "android")
                esito.telefoni_nuovi += 1
            conosciuti[nome] = telefono_id

        trovato = uno(connessione,
                      "SELECT scatto_id FROM file_media WHERE impronta = ?",
                      riga["impronta"])
        scatto_id = trovato["scatto_id"] if trovato else None
        prima = uno(connessione,
                    "SELECT id FROM cuori WHERE telefono_id = ? AND impronta = ?",
                    telefono_id, riga["impronta"])
        if prima is not None:
            connessione.execute(
                "UPDATE cuori SET scatto_id = coalesce(?, scatto_id) WHERE id = ?",
                (scatto_id, prima["id"]))
            continue
        inserisci(
            connessione,
            "INSERT INTO cuori (telefono_id, impronta, scatto_id, messo_il, "
            "tolto_il, tornato_il) VALUES (?, ?, ?, ?, ?, ?)",
            telefono_id, riga["impronta"], scatto_id, riga["messo_il"],
            riga["tolto_il"], adesso())
        esito.cuori_arrivati += 1


def _si_puo_tenere(chiave: str, scritto) -> bool:
    try:
        letto = json.loads(scritto)
        return valore_ammesso(chiave, letto) == letto
    except (TypeError, ValueError):
        return False


def _porta_dentro_le_impostazioni(connessione: sqlite3.Connection,
                                  pacchetto: lettore.Aperto,
                                  esito: Esito) -> None:
    for riga in pacchetto.impostazioni():
        chiave = riga["chiave"]
        if chiave not in VIAGGIANO:
            continue
        loro, loro_quando = riga["valore"], riga["cambiata_il"] or ""
        if not _si_puo_tenere(chiave, loro):
            esito.note.append(
                f"l'impostazione «{chiave}» arrivata dall'altro computer ha un "
                "valore che questo programma non conosce: ho tenuto quella di qui")
            continue
        mia = uno(connessione,
                  "SELECT valore, cambiata_il FROM impostazioni WHERE chiave = ?",
                  chiave)
        if mia is not None and mia["valore"] == loro:
            continue

        if mia is None:
            vince_chi_arriva = True
        elif loro_quando and (mia["cambiata_il"] or ""):
            vince_chi_arriva = loro_quando > mia["cambiata_il"]
        else:
            partenza = json.dumps(PREDEFINITE.get(chiave), ensure_ascii=False)
            ho_deciso_io = mia["valore"] != partenza
            hanno_deciso_loro = loro != partenza
            if ho_deciso_io and hanno_deciso_loro:
                esito.impostazioni_contese += 1
                esito.note.append(
                    f"l'impostazione «{chiave}» è stata cambiata su tutti e "
                    "due i computer e nessuna delle due porta una data: ho "
                    "tenuto quella di qui, la decidi tu (regola 69)")
                continue
            vince_chi_arriva = hanno_deciso_loro and not ho_deciso_io

        if not vince_chi_arriva:
            continue
        connessione.execute(
            "INSERT INTO impostazioni (chiave, valore, cambiata_il) "
            "VALUES (?, ?, ?) ON CONFLICT(chiave) DO UPDATE SET "
            "valore = excluded.valore, cambiata_il = excluded.cambiata_il",
            (chiave, loro, loro_quando or None))
        esito.impostazioni_arrivate += 1


def fondi(archivio, cartella: Path, password: str,
          avanzamento: Callable[[int, int], None] | None = None) -> Esito:
    esito = Esito()
    with lettore.apri(cartella, password, archivio_atteso=archivio.dove.nome,
                      lavoro=Path(archivio.dove.radice) / "lavoro") as pacchetto:
        controlla_gli_orologi(pacchetto.carta)
        carta = pacchetto.carta
        esito.mittente = carta.mittente_nome
        esito.dal_seriale = carta.dal_seriale
        esito.al_seriale = carta.al_seriale

        with archivio.lettura() as connessione:
            noto = uno(connessione, "SELECT visto_fino_a FROM macchine WHERE codice = ?",
                       carta.mittente_codice)
        controlla_che_non_manchi_niente(carta, noto["visto_fino_a"] if noto else 0)
        pronti, miniature = _metti_al_sicuro_i_file(archivio, pacchetto, esito,
                                                    avanzamento)

        with archivio.scrittura() as connessione:
            mittente_id = cambiamenti.impara_dal_pacchetto(
                connessione, codice=carta.mittente_codice,
                nome=carta.mittente_nome, visto_di_me=carta.visto_di_te,
                inventario=pacchetto.inventario())
            mittente = uno(connessione, "SELECT * FROM macchine WHERE id = ?",
                           mittente_id)
            gia_visto = mittente["visto_fino_a"]
            controlla_che_non_manchi_niente(carta, gia_visto)
            io = cambiamenti.questa_macchina(connessione)

            capi = _porta_dentro_le_cose(archivio, pacchetto, esito, pronti, miniature)

            for gesto in pacchetto.cambiamenti():
                if gesto["seriale"] <= gia_visto:
                    esito.gesti_gia_visti += 1
                    continue

                if gesto["cosa"] == "nodo":
                    _nodo(connessione, gesto, esito)
                elif gesto["cosa"] == "etichetta":
                    scatto_id = capi.get(gesto["impronta"])
                    if scatto_id is None and gesto["impronta"]:
                        riga = uno(connessione,
                                   "SELECT scatto_id FROM file_media WHERE impronta = ?",
                                   gesto["impronta"])
                        scatto_id = riga["scatto_id"] if riga else None
                    if scatto_id is None:
                        esito.note.append(
                            "un'etichetta arriva per una fotografia che qui non "
                            "c'è e che il pacchetto non porta")
                        continue
                    _etichetta(connessione, gesto, scatto_id, esito,
                               chi_sono=io["codice"],
                               chi_arriva=carta.mittente_codice)
                else:
                    esito.note.append(
                        f"un cambiamento di tipo «{gesto['cosa']}» non lo so "
                        "ancora applicare: l'ho saltato.")
                    continue
                esito.gesti_applicati += 1

            _porta_dentro_le_persone(connessione, pacchetto, esito)
            _porta_dentro_i_cuori(connessione, pacchetto, esito)
            _porta_dentro_le_impostazioni(connessione, pacchetto, esito)

            connessione.execute(
                "UPDATE macchine SET visto_fino_a = max(visto_fino_a, ?), "
                "vista_il = ? WHERE id = ?",
                (carta.al_seriale, adesso(), mittente_id))

    return esito
