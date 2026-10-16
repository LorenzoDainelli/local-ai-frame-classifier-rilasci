from __future__ import annotations

import sqlite3
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath

from officina import registro
from officina.archivio import database
from officina.archivio.accesso import Archivio
from officina.archivio.database import adesso, inserisci, tutti, uno
from officina.doppioni import motore as doppioni_motore, occhio
from officina.errori import ErroreOfficina, FileNonLeggibile
from officina.importazione import abbinamento, impronta as impronta_file, metadati, miniature, scansione
from officina.miglioria import coda as miglioria_coda
from officina.modello import file_media, luoghi, salute_file, scatti

CAMPIONE_PER_LA_STIMA = 50

IN_ANTICIPO = 4


@dataclass
class Preparato:
    segno: str
    gia_noto: bool
    dati: metadati.Metadati | None = None
    occhio: str | None = None
    guasto: BaseException | None = None


@dataclass
class Avanzamento:
    stato: str
    totale: int
    fatti: int
    saltati: int
    nuovi_scatti: int
    coppie_live: int
    gia_presenti: int
    ms_per_file: float | None

    @property
    def resta(self) -> int:
        return max(self.totale - self.fatti - self.saltati, 0)

    @property
    def percentuale(self) -> float:
        if not self.totale:
            return 0.0
        return round((self.fatti + self.saltati) * 100 / self.totale, 1)

    @property
    def secondi_rimasti(self) -> int | None:
        if not self.ms_per_file or self.resta == 0:
            return None
        return int(self.resta * self.ms_per_file / 1000)

    def quanto_manca(self) -> str:
        if self.resta == 0:
            return "finito"
        secondi = self.secondi_rimasti
        if secondi is None:
            return "sto ancora misurando"
        if secondi < 15:
            return "un istante"
        if secondi < 90:
            return f"circa {secondi} secondi"
        if secondi < 5400:
            minuti = round(secondi / 60)
            return f"circa {minuti} minut{'o' if minuti == 1 else 'i'}"
        ore = secondi / 3600
        if ore < 10:
            return f"circa {ore:.1f} ore"
        notti = max(round(ore / 8), 1)
        return f"circa {notti} nott{'e' if notti == 1 else 'i'}"


class Motore:

    def __init__(self, archivio: Archivio):
        self.archivio = archivio
        self.importazione_id: int | None = None
        self._fermati = threading.Event()
        self._misure: list[float] = []


    def prepara(self, cartelle: list[Path]) -> dict:
        trovati = scansione.elenca(cartelle)
        spazio = scansione.controlla_spazio(trovati.byte, self.archivio.dove.radice)

        with self.archivio.scrittura() as connessione:
            for cartella in cartelle:
                scansione.aggiungi_cartella(connessione, Path(cartella))

            connessione.execute(
                "UPDATE importazioni SET stato = 'interrotta' WHERE stato = 'in_corso'")

            nome = ", ".join(dict.fromkeys(
                Path(c).name or str(c) for c in cartelle)) or None
            self.importazione_id = inserisci(
                connessione,
                "INSERT INTO importazioni (nome, iniziata_il, stato, totale) "
                "VALUES (?, ?, 'in_corso', ?)",
                nome, adesso(), trovati.quanti,
            )
            connessione.executemany(
                "INSERT OR IGNORE INTO coda_importazione "
                "(importazione_id, percorso, dimensione) VALUES (?, ?, ?)",
                [(self.importazione_id, str(p), trovati.dimensioni.get(str(p), 0))
                 for p in trovati.file],
            )

        self._misure = []

        registro.evento("importazione.preparata", file=trovati.quanti,
                        byte=trovati.byte, spazio_ok=spazio.basta,
                        collegamenti=trovati.collegamenti)
        return {
            "importazione_id": self.importazione_id,
            "file": trovati.quanti,
            "byte": trovati.byte,
            "saltati_per_estensione": trovati.saltati,
            "spazio": spazio,
        }

    def riprendi(self) -> int | None:
        with self.archivio.lettura() as connessione:
            riga = uno(
                connessione,
                "SELECT * FROM importazioni WHERE stato = 'in_corso' ORDER BY id DESC LIMIT 1",
            )
        if riga is None:
            return None
        self.importazione_id = riga["id"]
        registro.evento("importazione.ripresa", fatti=riga["fatti"], totale=riga["totale"])
        return self.importazione_id

    def aggancia_ultima(self) -> int | None:
        if self.riprendi() is not None:
            return self.importazione_id
        with self.archivio.lettura() as connessione:
            riga = uno(connessione, "SELECT * FROM importazioni ORDER BY id DESC LIMIT 1")
        if riga is None:
            return None
        self.importazione_id = riga["id"]
        return self.importazione_id


    def prossimi(self, quanti: int = 1) -> list[sqlite3.Row]:
        with self.archivio.lettura() as connessione:
            return tutti(
                connessione,
                "SELECT * FROM coda_importazione WHERE importazione_id = ? "
                "AND stato = 'in_attesa' ORDER BY id LIMIT ?",
                self.importazione_id, quanti,
            )

    def esegui(self, limite: int | None = None, al_passo=None) -> Avanzamento:
        self._fermati.clear()
        fatti = 0
        avviati: dict[int, Future] = {}
        with ThreadPoolExecutor(max_workers=IN_ANTICIPO,
                                thread_name_prefix="importazione") as aiutanti:
            while not self._fermati.is_set():
                righe = self.prossimi(IN_ANTICIPO * 2)
                if not righe:
                    break
                for riga in righe:
                    if riga["id"] not in avviati:
                        avviati[riga["id"]] = aiutanti.submit(
                            self._prepara, Path(riga["percorso"]))
                riga = righe[0]
                inizio = time.perf_counter()
                self._lavora_una(riga, avviati.pop(riga["id"]).result())
                self._misure.append((time.perf_counter() - inizio) * 1000)
                fatti += 1
                if al_passo is not None:
                    al_passo(self.stato())
                if limite is not None and fatti >= limite:
                    break
            for futuro in avviati.values():
                futuro.cancel()

        stato = self.stato()
        if stato.resta == 0:
            self._chiudi("finita")
        elif self._fermati.is_set():
            self._chiudi("interrotta")
        return self.stato()

    def ferma(self) -> None:
        self._fermati.set()

    @property
    def fermato(self) -> bool:
        return self._fermati.is_set()

    def _chiudi(self, stato: str) -> None:
        if self.importazione_id is None:
            return
        with self.archivio.scrittura() as connessione:
            connessione.execute(
                "UPDATE importazioni SET stato = ?, finita_il = ?, ms_per_file = ? WHERE id = ?",
                (stato, adesso() if stato == "finita" else None,
                 self._media_misurata(), self.importazione_id),
            )
        with self.archivio.scrittura() as connessione:
            esito = luoghi.raggruppa(connessione)
        if esito["sistemati"]:
            registro.evento("luoghi.raggruppati", sistemati=esito["sistemati"],
                            nuovi=esito["nuovi"])
        try:
            with self.archivio.scrittura() as connessione:
                database.impara_com_e_fatto(connessione)
        except Exception:
            registro.errore("archivio.statistiche_non_aggiornate")
        registro.evento("importazione.chiusa", esito=stato)

    def _media_misurata(self) -> float | None:
        if len(self._misure) < 3:
            return None
        campione = self._misure[-CAMPIONE_PER_LA_STIMA:]
        return round(sum(campione) / len(campione), 1)


    def _prepara(self, percorso: Path) -> Preparato | None:
        try:
            segno = impronta_file.del_file(percorso)
            with self.archivio.lettura() as connessione:
                gia_noto = bool(
                    miglioria_coda.di_impronta_migliorata(connessione, segno)
                    or file_media.per_impronta(connessione, segno))
            pronto = Preparato(segno=segno, gia_noto=gia_noto)
            if gia_noto:
                return pronto
            pronto.dati = metadati.leggi(percorso)
            if pronto.dati.genere == "immagine":
                try:
                    pronto.occhio = occhio.del_percorso(percorso)
                except Exception as errore:             # noqa: BLE001
                    pronto.guasto = errore
            return pronto
        except Exception:                               # noqa: BLE001
            return None

    def _lavora_una(self, riga_coda: sqlite3.Row,
                    pronto: Preparato | None = None) -> None:
        percorso = Path(riga_coda["percorso"])
        try:
            self._importa(percorso, pronto)
            esito = "fatto"
        except FileNonLeggibile as errore:
            self._segna_non_importato(percorso, errore.codice, errore.messaggio)
            esito = "saltato"
        except Exception as errore:                     # noqa: BLE001
            self._segna_non_importato(
                percorso, "corrotto",
                f"Con «{percorso.name}» è andato storto qualcosa che non avevo "
                "previsto. Il file non è stato toccato: puoi riprovare.",
            )
            registro.errore("importazione.errore_inatteso",
                            **registro.dove_si_e_rotto(errore))
            esito = "saltato"

        with self.archivio.scrittura() as connessione:
            connessione.execute(
                "UPDATE coda_importazione SET stato = ? WHERE id = ?",
                (esito, riga_coda["id"]),
            )
            if esito == "fatto":
                connessione.execute(
                    "DELETE FROM non_importati WHERE percorso = ?", (str(percorso),))
            colonna = "fatti" if esito == "fatto" else "saltati"
            connessione.execute(
                f"UPDATE importazioni SET {colonna} = {colonna} + 1 WHERE id = ?",
                (self.importazione_id,),
            )

    def _segna_non_importato(self, percorso: Path, motivo: str, dettaglio: str) -> None:
        with self.archivio.scrittura() as connessione:
            connessione.execute(
                "INSERT INTO non_importati (percorso, motivo, dettaglio, tentato_il) "
                "VALUES (?,?,?,?) ON CONFLICT(percorso) DO UPDATE SET "
                "motivo = excluded.motivo, dettaglio = excluded.dettaglio, "
                "tentato_il = excluded.tentato_il",
                (str(percorso), motivo, dettaglio, adesso()),
            )
        registro.avviso("importazione.file_saltato",
                        motivo=registro.Parola(motivo))

    def _importa(self, percorso: Path, pronto: Preparato | None = None) -> None:
        segno = pronto.segno if pronto else impronta_file.del_file(percorso)

        with self.archivio.scrittura() as connessione:
            if miglioria_coda.di_impronta_migliorata(connessione, segno):
                connessione.execute(
                    "UPDATE importazioni SET gia_presenti = gia_presenti + 1 WHERE id = ?",
                    (self.importazione_id,),
                )
                return
            gia = file_media.per_impronta(connessione, segno)
            if gia is not None:
                _, nuovo = file_media.aggiungi_percorso(
                    connessione, gia["id"], percorso,
                    scansione.cartella_di(connessione, percorso),
                )
                if nuovo:
                    connessione.execute(
                        "INSERT INTO segnalazioni (tipo, file_id, scatto_id, dettaglio, creata_il) "
                        "VALUES ('doppione_percorso', ?, ?, ?, ?)",
                        (gia["id"], gia["scatto_id"],
                         "Lo stesso file si trova in due cartelle: è un solo scatto "
                         "con due percorsi.", adesso()),
                    )
                connessione.execute(
                    "UPDATE importazioni SET gia_presenti = gia_presenti + 1 WHERE id = ?",
                    (self.importazione_id,),
                )
                return
            if salute_file.si_e_rovinato(connessione, percorso, segno):
                connessione.execute(
                    "UPDATE importazioni SET gia_presenti = gia_presenti + 1 WHERE id = ?",
                    (self.importazione_id,),
                )
                return

        dati = pronto.dati if pronto and pronto.dati else metadati.leggi(percorso)
        dimensione = percorso.stat().st_size

        with self.archivio.scrittura() as connessione:
            file_id = file_media.crea(connessione, segno, dimensione, dati.genere, dati)
            file_media.aggiungi_percorso(
                connessione, file_id, percorso,
                scansione.cartella_di(connessione, percorso),
            )
            riga_file = file_media.per_id(connessione, file_id)
            self._sistema_lo_scatto(connessione, riga_file, dati, percorso)

        with self.archivio.lettura() as connessione:
            riga_file = file_media.per_id(connessione, file_id)
        try:
            miniature.per_file(self.archivio, riga_file,
                               int(self.archivio.impostazione("miniatura_lato") or 640))
        except Exception as errore:                     # noqa: BLE001
            registro.avviso("importazione.miniatura_non_fatta",
                            **registro.dove_si_e_rotto(errore))

        self._impronta_dell_occhio(file_id, dati.genere, percorso,
                                   pronto if pronto and pronto.dati else None)

    def _impronta_dell_occhio(self, file_id: int, genere: str, percorso: Path,
                              pronto: Preparato | None = None) -> None:
        if genere != "immagine":
            return
        try:
            if pronto is not None and pronto.guasto is not None:
                raise pronto.guasto
            segno = (pronto.occhio if pronto is not None and pronto.occhio
                     else occhio.del_percorso(percorso))
        except Exception as errore:                     # noqa: BLE001
            segno = doppioni_motore.NON_SI_E_POTUTA
            registro.avviso("doppioni_immagine_non_guardata",
                            file_id=file_id, motivo=registro.tipo_di(errore))
        with self.archivio.scrittura() as connessione:
            connessione.execute(
                "UPDATE file_media SET impronta_occhio = ? WHERE id = ?",
                (segno, file_id))


    def _sistema_lo_scatto(self, connessione: sqlite3.Connection, riga_file: sqlite3.Row,
                           dati: metadati.Metadati, percorso: Path) -> None:
        candidato = self._candidato(connessione, riga_file, percorso.name, str(percorso.parent))

        if dati.genere == "video":
            esito = abbinamento.cerca_gemella(
                candidato, self._foto_possibili(connessione, candidato)
            )
            if esito.e_live and esito.foto is not None:
                self._unisci(connessione, foto_file_id=esito.foto.id,
                             video_file_id=riga_file["id"], durata_ms=dati.durata_ms)
                return
            if esito.da_chiedere and esito.foto is not None and esito.indizi is not None:
                connessione.execute(
                    "INSERT INTO segnalazioni (tipo, file_id, dettaglio, creata_il) "
                    "VALUES ('coppia_incerta', ?, ?, ?)",
                    (riga_file["id"],
                     f"Questo video e una foto hanno {esito.indizi.a_parole()}: "
                     "sono lo stesso scatto?", adesso()),
                )

        scatto_id = scatti.crea(
            connessione,
            abbinamento.genere_dello_scatto(dati.durata_ms, ha_gemella=False,
                                            e_un_video=dati.genere == "video"),
            dati,
            self.importazione_id,
        )
        file_media.collega_a_scatto(connessione, riga_file["id"], scatto_id, "principale")
        connessione.execute(
            "UPDATE importazioni SET nuovi_scatti = nuovi_scatti + 1 WHERE id = ?",
            (self.importazione_id,),
        )

        if dati.sembra_schermata:
            connessione.execute(
                "INSERT INTO segnalazioni (tipo, scatto_id, file_id, dettaglio, creata_il) "
                "VALUES ('schermata', ?, ?, ?, ?)",
                (scatto_id, riga_file["id"],
                 "Ha la misura esatta di uno schermo e nessun dato di scatto.", adesso()),
            )
        if not dati.ha_data:
            connessione.execute(
                "INSERT INTO segnalazioni (tipo, scatto_id, file_id, dettaglio, creata_il) "
                "VALUES ('senza_data', ?, ?, ?, ?)",
                (scatto_id, riga_file["id"],
                 "Nei metadati non c'è nessuna data di scatto.", adesso()),
            )

        if dati.genere == "immagine":
            self._cerca_video_orfano(connessione, candidato)

    def _candidato(self, connessione: sqlite3.Connection, riga_file: sqlite3.Row,
                   nome: str, cartella: str | None = None) -> abbinamento.Candidato:
        return abbinamento.Candidato(
            id=riga_file["id"], nome=nome,
            istante_utc=riga_file["istante_utc"], data_locale=riga_file["data_locale"],
            identificatore_ios=riga_file["identificatore_ios"],
            durata_ms=riga_file["durata_ms"], cartella=cartella,
        )

    def _foto_possibili(self, connessione: sqlite3.Connection,
                        video: abbinamento.Candidato) -> list[abbinamento.Candidato]:
        trovate: dict[int, sqlite3.Row] = {}

        if video.identificatore_ios:
            for riga in tutti(
                connessione,
                "SELECT * FROM file_media WHERE genere = 'immagine' AND identificatore_ios = ?",
                video.identificatore_ios,
            ):
                trovate[riga["id"]] = riga

        for colonna, momento, coda in (("istante_utc", video.momento_utc or video.momento, "Z"),
                                       ("data_locale", video.momento_locale, "")):
            if momento is None:
                continue
            for riga in tutti(
                connessione,
                f"SELECT * FROM file_media WHERE genere = 'immagine' "
                f"AND {colonna} >= ? AND {colonna} <= ?",
                _attorno(momento, -abbinamento.TOLLERANZA_SECONDI, coda),
                _attorno(momento, abbinamento.TOLLERANZA_SECONDI, coda),
            ):
                trovate[riga["id"]] = riga

        radice = video.radice
        if radice:
            for riga in tutti(
                connessione,
                "SELECT f.* FROM file_media f JOIN percorsi p ON p.file_id = f.id "
                "WHERE f.genere = 'immagine' AND p.nome LIKE ? ESCAPE '\\'",
                _come(radice) + ".%",
            ):
                trovate[riga["id"]] = riga

        candidati = []
        for riga in trovate.values():
            for posto in tutti(connessione,
                               "SELECT nome, percorso FROM percorsi WHERE file_id = ? ORDER BY id",
                               riga["id"]) or [{"nome": "", "percorso": ""}]:
                candidati.append(abbinamento.Candidato(
                    id=riga["id"], nome=posto["nome"] or "",
                    istante_utc=riga["istante_utc"], data_locale=riga["data_locale"],
                    identificatore_ios=riga["identificatore_ios"],
                    cartella=_cartella_di(posto["percorso"]),
                ))
        return candidati

    def _cerca_video_orfano(self, connessione: sqlite3.Connection,
                            foto: abbinamento.Candidato) -> None:
        possibili = tutti(
            connessione,
            "SELECT f.*, (SELECT nome FROM percorsi p WHERE p.file_id = f.id "
            "            ORDER BY p.id LIMIT 1) AS nome, "
            "(SELECT percorso FROM percorsi p WHERE p.file_id = f.id "
            " ORDER BY p.id LIMIT 1) AS percorso "
            "FROM file_media f JOIN scatti s ON s.id = f.scatto_id "
            "WHERE f.genere = 'video' AND f.ruolo = 'principale' AND s.genere <> 'live' "
            "  AND (f.durata_ms IS NULL OR f.durata_ms <= ?) "
            "  AND f.id IN (SELECT id FROM file_media WHERE identificatore_ios = ? "
            "               UNION SELECT id FROM file_media WHERE istante_utc BETWEEN ? AND ? "
            "               UNION SELECT id FROM file_media WHERE data_locale BETWEEN ? AND ? "
            "               UNION SELECT file_id FROM percorsi WHERE nome LIKE ? ESCAPE '\\') "
            "ORDER BY f.id",
            abbinamento.DURATA_MASSIMA_LIVE_MS,
            foto.identificatore_ios or "\x00",
            _istante_meno(foto.istante_utc, abbinamento.TOLLERANZA_SECONDI),
            _istante_piu(foto.istante_utc, abbinamento.TOLLERANZA_SECONDI),
            *(_attorno(foto.momento_locale, segno * abbinamento.TOLLERANZA_SECONDI, "")
              if foto.momento_locale else "\x00" for segno in (-1, 1)),
            (_come(foto.radice) + ".%") if foto.radice else "\x00",
        )
        for riga in possibili:
            video = abbinamento.Candidato(
                id=riga["id"], nome=riga["nome"] or "",
                istante_utc=riga["istante_utc"], data_locale=riga["data_locale"],
                identificatore_ios=riga["identificatore_ios"],
                durata_ms=riga["durata_ms"], cartella=_cartella_di(riga["percorso"]),
            )
            indizi = abbinamento.confronta(video, foto)
            if indizi.certo:
                self._unisci(connessione, foto_file_id=foto.id,
                             video_file_id=riga["id"], durata_ms=riga["durata_ms"])
                return

    def _unisci(self, connessione: sqlite3.Connection, foto_file_id: int,
                video_file_id: int, durata_ms: int | None) -> None:
        unisci_live(connessione, foto_file_id, video_file_id, durata_ms, self.importazione_id)

    def stato(self) -> Avanzamento:
        with self.archivio.lettura() as connessione:
            riga = uno(connessione, "SELECT * FROM importazioni WHERE id = ?",
                       self.importazione_id)
        if riga is None:
            return Avanzamento("assente", 0, 0, 0, 0, 0, 0, None)
        return Avanzamento(
            stato=riga["stato"], totale=riga["totale"], fatti=riga["fatti"],
            saltati=riga["saltati"], nuovi_scatti=riga["nuovi_scatti"],
            coppie_live=riga["coppie_live"], gia_presenti=riga["gia_presenti"],
            ms_per_file=self._media_misurata() or riga["ms_per_file"],
        )


def _istante_meno(istante: str | None, secondi: int) -> str:
    return _sposta(istante, -secondi)


def _istante_piu(istante: str | None, secondi: int) -> str:
    return _sposta(istante, secondi)


def _sposta(istante: str | None, secondi: int) -> str:
    from datetime import datetime

    if not istante:
        return "\x00"
    try:
        momento = datetime.strptime(istante.rstrip("Z"), "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return "\x00"
    return _attorno(momento, secondi)


def _attorno(momento, secondi: int, coda: str = "Z") -> str:
    from datetime import datetime, timedelta

    try:
        spostato = momento + timedelta(seconds=secondi)
    except OverflowError:
        spostato = datetime.min if secondi < 0 else datetime.max
    return spostato.isoformat(timespec="seconds") + coda


def _come(testo: str) -> str:
    for carattere in ("\\", "%", "_"):
        testo = testo.replace(carattere, "\\" + carattere)
    return testo


class InSottofondo:

    def __init__(self, motore: Motore, dopo=None):
        self.motore = motore
        self.dopo = dopo
        self._filo: threading.Thread | None = None
        self.guasto = ""
        self._lucchetto = threading.Lock()

    @property
    def sta_lavorando(self) -> bool:
        return self._filo is not None and self._filo.is_alive()

    def parti(self) -> None:
        with self._lucchetto:
            if self.sta_lavorando:
                return
            self.guasto = ""
            self._filo = threading.Thread(target=self._dentro, name="importazione",
                                          daemon=True)
            self._filo.start()

    def _dentro(self) -> None:
        try:
            self.motore.esegui()
            if self.dopo is not None and not self.motore.fermato:
                self.dopo()
        except ErroreOfficina as errore:
            self.guasto = errore.messaggio
            registro.errore("importazione.fermata_da_un_guasto",
                            motivo=registro.Parola(errore.codice))
        except Exception as errore:                      # noqa: BLE001
            self.guasto = (
                "L'importazione si è fermata per qualcosa che non avevo "
                "previsto. Nessun file è stato toccato, e quelli già entrati "
                "restano: si può riprendere da dove era.\n"
                + registro.dettaglio_tecnico(errore))
            registro.errore("importazione.rotta",
                            **registro.dove_si_e_rotto(errore))

    def ferma(self, aspetta: float = 5.0) -> None:
        self.motore.ferma()
        if self._filo is not None:
            self._filo.join(timeout=aspetta)


def unisci_live(connessione: sqlite3.Connection, foto_file_id: int, video_file_id: int,
                durata_ms: int | None, importazione_id: int | None = None) -> bool:
    foto = file_media.per_id(connessione, foto_file_id)
    video = file_media.per_id(connessione, video_file_id)
    if foto is None or video is None or foto["scatto_id"] is None:
        return False

    scatto_id = foto["scatto_id"]
    scatto_del_video = video["scatto_id"]

    file_media.collega_a_scatto(connessione, video_file_id, scatto_id, "movimento")
    connessione.execute(
        "UPDATE scatti SET genere = 'live', durata_ms = ? WHERE id = ?",
        (durata_ms, scatto_id),
    )

    if scatto_del_video and scatto_del_video != scatto_id:
        _sposta_quello_che_resta(connessione, scatto_del_video, scatto_id)
        connessione.execute("DELETE FROM scatti WHERE id = ?", (scatto_del_video,))
        if importazione_id is not None:
            connessione.execute(
                "UPDATE importazioni SET nuovi_scatti = max(nuovi_scatti - 1, 0) WHERE id = ?",
                (importazione_id,),
            )

    if importazione_id is not None:
        connessione.execute(
            "UPDATE importazioni SET coppie_live = coppie_live + 1 WHERE id = ?",
            (importazione_id,),
        )
    connessione.execute(
        "UPDATE segnalazioni SET risolta = 1 WHERE tipo = 'coppia_incerta' "
        "AND file_id = ? AND risolta = 0", (video_file_id,))
    return True


def _sposta_quello_che_resta(connessione: sqlite3.Connection, da: int, a: int) -> None:
    connessione.execute("UPDATE OR IGNORE etichette SET scatto_id = ? WHERE scatto_id = ?",
                        (a, da))


def _cartella_di(percorso: str | None) -> str | None:
    if not percorso:
        return None
    return str(PureWindowsPath(percorso).parent) if "\\" in percorso else str(PurePosixPath(percorso).parent)


def riattacca_i_live(connessione: sqlite3.Connection) -> int:
    rimessi = 0
    video_soli = tutti(
        connessione,
        "SELECT f.*, (SELECT nome FROM percorsi p WHERE p.file_id = f.id "
        "            ORDER BY p.id LIMIT 1) AS nome, "
        "(SELECT percorso FROM percorsi p WHERE p.file_id = f.id "
        " ORDER BY p.id LIMIT 1) AS percorso "
        "FROM file_media f JOIN scatti s ON s.id = f.scatto_id "
        "WHERE f.genere = 'video' AND f.ruolo = 'principale' AND s.genere IN ('video', 'foto') "
        "  AND (f.durata_ms IS NULL OR f.durata_ms <= ?)",
        abbinamento.DURATA_MASSIMA_LIVE_MS)
    for riga in video_soli:
        video = abbinamento.Candidato(
            id=riga["id"], nome=riga["nome"] or "",
            istante_utc=riga["istante_utc"], data_locale=riga["data_locale"],
            identificatore_ios=riga["identificatore_ios"], durata_ms=riga["durata_ms"],
            cartella=_cartella_di(riga["percorso"]))
        foto_vicine = []
        radice = video.radice
        if radice:
            foto_vicine = tutti(
                connessione,
                "SELECT f.*, p.nome AS nome, p.percorso AS percorso FROM file_media f "
                "JOIN percorsi p ON p.file_id = f.id "
                "JOIN scatti s ON s.id = f.scatto_id "
                "WHERE f.genere = 'immagine' AND f.ruolo = 'principale' "
                "  AND s.genere = 'foto' AND p.nome LIKE ? ESCAPE '\\'",
                _come(radice) + ".%")
        if video.identificatore_ios:
            foto_vicine += tutti(
                connessione,
                "SELECT f.*, (SELECT nome FROM percorsi p WHERE p.file_id = f.id "
                "            ORDER BY p.id LIMIT 1) AS nome, "
                "(SELECT percorso FROM percorsi p WHERE p.file_id = f.id "
                " ORDER BY p.id LIMIT 1) AS percorso "
                "FROM file_media f JOIN scatti s ON s.id = f.scatto_id "
                "WHERE f.genere = 'immagine' AND f.ruolo = 'principale' "
                "  AND s.genere = 'foto' AND f.identificatore_ios = ?",
                video.identificatore_ios)
        esito = abbinamento.cerca_gemella(video, [
            abbinamento.Candidato(
                id=foto["id"], nome=foto["nome"] or "",
                istante_utc=foto["istante_utc"], data_locale=foto["data_locale"],
                identificatore_ios=foto["identificatore_ios"],
                cartella=_cartella_di(foto["percorso"]))
            for foto in foto_vicine])
        if esito.e_live and esito.foto is not None:
            if unisci_live(connessione, esito.foto.id, riga["id"], riga["durata_ms"]):
                rimessi += 1
    return rimessi
