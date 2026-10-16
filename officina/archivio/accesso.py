from __future__ import annotations

import contextlib
import contextvars
import hashlib
import json
import sqlite3
import threading
from pathlib import Path
from typing import Iterator

from officina import registro
from officina import forziere
from officina.archivio import copie, database, migrazioni
from officina.errori import ArchivioChiuso, ErroreOfficina
from officina.impostazioni import (PREDEFINITE, REALE, SOLO_QUESTA_MACCHINA,
                                   Posizione, chiave_locale, posizione,
                                   questa_macchina, valore_ammesso)

RICORDI_DELLA_VISTA = ("ultimo_filtro", "ultimo_scatto")
_MANCANTE = object()


def _metti_se_si_legge(valori: dict, chiave: str, scritto: str) -> None:
    try:
        letto = json.loads(scritto)
    except (TypeError, ValueError):
        return
    if chiave in PREDEFINITE:
        try:
            letto = valore_ammesso(chiave, letto)
        except ValueError:
            return
    valori[chiave] = letto


class Archivio:

    di_prova = False

    def __init__(self, dove: Posizione, tiene_il_registro: bool = True):
        self.dove = dove
        self._tiene_il_registro = tiene_il_registro
        self._connessione: sqlite3.Connection | None = None
        self._lucchetto = threading.RLock()
        self._lucchetto_dei_lettori = threading.Lock()
        self._lucchetto_delle_copie = threading.Lock()
        self._registro: registro.Registro | None = None
        self._parola: str | None = None
        self._modifiche_all_apertura = 0
        self._solo_ricordi = 0
        self._di_servizio = 0
        self._cambiato_all_apertura = False
        self._copia_in_sottofondo: Path | None = None
        self._conteggio_visto = -1
        self._lettori = threading.local()
        self._tutti_i_lettori: list[sqlite3.Connection] = []

    def apri(self, password: str | None = None) -> "Archivio":
        with self._lucchetto_delle_copie, self._lucchetto:
            return self._apri(password)

    def _apri(self, password: str | None) -> "Archivio":
        if self._connessione is not None:
            return self

        cassa = forziere.per(self.dove)
        if cassa.acceso and not cassa.aperto:
            if not password:
                raise forziere.ForziereChiuso(
                    "Questo archivio è dentro un forziere: serve la password. "
                    "Il programma la chiede all'avvio; se stai chiamando "
                    "qualcosa a mano, passala tu.")
            cassa.apri(password)
        if cassa.acceso:
            self._parola = password

        self.dove.prepara()
        self._registro = registro.Registro(self.dove.registro)
        if self._tiene_il_registro:
            registro.imposta(self._registro)

        if not self.di_prova:
            try:
                copie.pulisci_i_resti(self.dove)
            except Exception:
                registro.errore("copie.resti_non_tolti")
            try:
                copie.rimetti_se_prenotata(self.dove)
            except Exception:
                registro.errore("copie.ripristino_fallito")

        nuovo = not self.dove.database.exists()
        self._connessione = database.connetti(self.dove.database)

        if not nuovo and migrazioni.da_applicare(self._connessione):
            copie.fai_copia(self._connessione, self.dove, "prima_aggiornamento")

        cambiato = bool(migrazioni.aggiorna(self._connessione))
        if not nuovo and (cambiato
                          or database.non_ha_mai_guardato(self._connessione)):
            database.impara_com_e_fatto(self._connessione)
        if nuovo:
            self._scrivi_valori_di_partenza()
        self._cambiato_all_apertura = nuovo or cambiato
        self._modifiche_all_apertura = self._connessione.total_changes
        self._solo_ricordi = 0
        self._di_servizio = 0

        registro.evento("archivio.aperto", nuovo=nuovo)
        return self

    def chiudi(self, con_copia: bool = True) -> None:
        from officina.archivio import riserva

        riserva.ferma_e_aspetta()
        with self._lucchetto_delle_copie:
            self._chiudi(con_copia)

    def _chiudi(self, con_copia: bool) -> None:
        if self._connessione is None:
            return
        self._chiudi_i_lettori()
        try:
            with self._lucchetto:
                database.ripassa_com_e_fatto(self._connessione)
        except Exception:
            registro.errore("archivio.statistiche_non_aggiornate")
        try:
            if con_copia and self._serve_la_copia():
                with self._lucchetto:
                    self._connessione.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                    copie.fai_copia(self._connessione, self.dove, "chiusura")
        except Exception:
            registro.errore("copie.fallita")
        finally:
            with self._lucchetto:
                self._connessione.close()
                self._connessione = None
            registro.evento("archivio.chiuso")
            self._rimetti_nel_forziere()

    def _serve_la_copia(self) -> bool:
        if self._cambiato_all_apertura or not copie.elenco(self.dove):
            return True
        fatte = (self._connessione.total_changes - self._modifiche_all_apertura
                 - self._solo_ricordi)
        return fatte > 0

    def copia_se_fermo(self) -> bool:
        if self.di_prova:
            return False
        with self._lucchetto_delle_copie:
            with self._lucchetto:
                if self._connessione is None:
                    return False
                conteggio = self._connessione.total_changes - self._di_servizio
                fermo = conteggio == self._conteggio_visto
                self._conteggio_visto = conteggio
                if not fermo or not self._serve_la_copia():
                    return False
                self._connessione.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                sorgente = self._fotografia()
                modifiche = self._connessione.total_changes
                ricordi = self._solo_ricordi
            try:
                copia = copie.fai_copia(sorgente, self.dove, "in_sottofondo")
            finally:
                sorgente.close()
            with self._lucchetto:
                if self._copia_in_sottofondo is not None:
                    self._copia_in_sottofondo.unlink(missing_ok=True)
                self._copia_in_sottofondo = copia.percorso
                self._cambiato_all_apertura = False
                self._modifiche_all_apertura = modifiche
                self._solo_ricordi -= ricordi
            return True

    def _fotografia(self) -> sqlite3.Connection:
        if not self.e_aperto:
            raise ArchivioChiuso("L'archivio è chiuso: non c'è niente da copiare.")
        sorgente = database.connetti(self.dove.database)
        try:
            sorgente.execute("BEGIN")
            sorgente.execute("SELECT count(*) FROM sqlite_master").fetchone()
        except BaseException:
            sorgente.close()
            raise
        return sorgente

    def _rimetti_nel_forziere(self) -> None:
        cassa = forziere.per(self.dove)
        if not cassa.acceso or not cassa.aperto or not self._parola:
            return
        try:
            cassa.chiudi(self._parola)
        except Exception:
            registro.errore("forziere.non_richiuso")

    def __enter__(self) -> "Archivio":
        return self.apri()

    def __exit__(self, *_) -> None:
        self.chiudi()

    @property
    def e_aperto(self) -> bool:
        return self._connessione is not None


    @property
    def connessione(self) -> sqlite3.Connection:
        if self._connessione is None:
            raise ArchivioChiuso(
                "L'archivio non è aperto. Nessuna parte del programma legge i "
                "dati da sola (regola 8)."
            )
        return self._connessione

    @contextlib.contextmanager
    def scrittura(self) -> Iterator[sqlite3.Connection]:
        with self._lucchetto:
            connessione = self.connessione
            connessione.execute("BEGIN IMMEDIATE")
            try:
                yield connessione
            except Exception:
                connessione.execute("ROLLBACK")
                raise
            else:
                connessione.execute("COMMIT")

    @contextlib.contextmanager
    def scrittura_di_servizio(self) -> Iterator[sqlite3.Connection]:
        with self._lucchetto:
            prima = self.connessione.total_changes
            try:
                with self.scrittura() as connessione:
                    yield connessione
            finally:
                if self._connessione is not None:
                    fatte = self._connessione.total_changes - prima
                    self._solo_ricordi += fatte
                    self._di_servizio += fatte

    @contextlib.contextmanager
    def lettura(self) -> Iterator[sqlite3.Connection]:
        lettore = self._lettore_a_parte()
        if lettore is not None:
            connessione, suo_lucchetto = lettore
            with suo_lucchetto:
                if lettore in self._tutti_i_lettori:
                    yield connessione
                    return
        with self._lucchetto:
            yield self.connessione

    def _lettore_a_parte(self) -> tuple[sqlite3.Connection, threading.RLock] | None:
        if self.di_prova or self._connessione is None or self._lucchetto._is_owned():
            return None
        lettori = self._lettori
        lettore = getattr(lettori, "coppia", None)
        if lettore is not None:
            return lettore
        try:
            connessione = database.connetti(self.dove.database)
        except sqlite3.Error:
            return None
        lettore = (connessione, threading.RLock())
        with self._lucchetto_dei_lettori:
            if self._connessione is None or lettori is not self._lettori:
                connessione.close()
                return None
            self._tutti_i_lettori.append(lettore)
        lettori.coppia = lettore
        return lettore

    def _chiudi_i_lettori(self) -> None:
        with self._lucchetto_dei_lettori:
            lettori, self._tutti_i_lettori = self._tutti_i_lettori, []
            self._lettori = threading.local()
        for connessione, suo_lucchetto in lettori:
            with suo_lucchetto, contextlib.suppress(sqlite3.Error):
                connessione.close()


    def _scrivi_valori_di_partenza(self) -> None:
        with self._lucchetto:
            for chiave, valore in PREDEFINITE.items():
                database.scrivi_valore_di_partenza(self.connessione, chiave, valore)

    def impostazione(self, chiave: str):
        dove = [chiave_locale(chiave)] if chiave in SOLO_QUESTA_MACCHINA else []
        with self.lettura() as connessione:
            for una in [*dove, chiave]:
                letto = database.leggi_impostazione(connessione, una, _MANCANTE)
                if letto is _MANCANTE:
                    continue
                if chiave not in PREDEFINITE:
                    return letto
                try:
                    return valore_ammesso(chiave, letto)
                except ValueError:
                    continue
        return PREDEFINITE.get(chiave)

    def imposta(self, chiave: str, valore) -> None:
        valore = valore_ammesso(chiave, valore)
        with self._lucchetto:
            dove = chiave_locale(chiave) if chiave in SOLO_QUESTA_MACCHINA else chiave
            database.scrivi_impostazione(self.connessione, dove, valore)

    def tutte_le_impostazioni(self) -> dict:
        valori = dict(PREDEFINITE)
        macchina = f"@{questa_macchina()}"
        with self.lettura() as connessione:
            righe = database.tutti(connessione,
                                   "SELECT chiave, valore FROM impostazioni")
        for riga in righe:
            if "@" not in riga["chiave"]:
                _metti_se_si_legge(valori, riga["chiave"], riga["valore"])
        for riga in righe:
            if riga["chiave"].endswith(macchina):
                _metti_se_si_legge(valori, riga["chiave"][: -len(macchina)],
                                   riga["valore"])
        return valori

    def stato(self, chiave: str, predefinito=None):
        with self.lettura() as connessione:
            return database.leggi_stato(connessione, chiave, predefinito)

    def salva_stato(self, chiave: str, valore) -> None:
        with self._lucchetto:
            prima = self.connessione.total_changes
            database.scrivi_stato(self.connessione, chiave, valore)
            if chiave in RICORDI_DELLA_VISTA:
                self._solo_ricordi += self.connessione.total_changes - prima

    @property
    def parola_del_forziere(self) -> str | None:
        return self._parola


    def nome_miniatura(self, impronta: str, misura: int, formato: str = "avif") -> str:
        chiave = hashlib.blake2b(
            f"{impronta}:{misura}".encode(), digest_size=16
        ).hexdigest()
        return f"{chiave[:2]}/{chiave}.{formato}"

    def percorso_miniatura(self, nome: str) -> Path:
        return self.dove.miniature / nome

    def nome_copia_video(self, impronta: str) -> str:
        chiave = hashlib.blake2b(
            f"{impronta}:video:dritta".encode(), digest_size=16).hexdigest()
        return f"{chiave[:2]}/{chiave}.mp4"

    def percorso_copia_video(self, nome: str) -> Path:
        return self.dove.miniature / nome

    def scrivi_miniatura(self, nome: str, dati: bytes) -> Path:
        percorso = self.percorso_miniatura(nome)
        percorso.parent.mkdir(parents=True, exist_ok=True)
        temporaneo = percorso.with_suffix(percorso.suffix + ".parziale")
        temporaneo.write_bytes(dati)
        temporaneo.replace(percorso)
        return percorso

    def leggi_miniatura(self, nome: str) -> bytes | None:
        percorso = self.percorso_miniatura(nome)
        try:
            return percorso.read_bytes()
        except OSError:
            return None

    def peso_miniature(self) -> tuple[int, int]:
        quante = 0
        byte = 0
        for percorso in self.dove.miniature.rglob("*"):
            try:
                if percorso.is_file():
                    byte += percorso.stat().st_size
                    quante += 1
            except OSError:
                continue
        return quante, byte

    def svuota_miniature(self) -> int:
        quante = 0
        for percorso in sorted(self.dove.miniature.rglob("*"), reverse=True):
            if percorso.is_file():
                percorso.unlink(missing_ok=True)
                quante += 1
            elif percorso.is_dir():
                with contextlib.suppress(OSError):
                    percorso.rmdir()
        with self._lucchetto:
            self.connessione.execute("UPDATE file_media SET miniatura = NULL")
        registro.evento("miniature.svuotate", quante=quante)
        return quante


    def copia_adesso(self, motivo: str = "manuale") -> copie.Copia:
        with self._lucchetto_delle_copie:
            with self._lucchetto:
                sorgente = self._fotografia()
            try:
                return copie.fai_copia(sorgente, self.dove, motivo)
            finally:
                sorgente.close()

    def copie_esistenti(self) -> list[copie.Copia]:
        return copie.elenco(self.dove)


class ArchivioDiProva(Archivio):

    di_prova = True

    def __init__(self, dove: Posizione, da: "Archivio | Path"):
        super().__init__(dove, tiene_il_registro=False)
        self._da = da

    def apri(self, password: str | None = None) -> "Archivio":
        if self._connessione is not None:
            return self
        copia = sqlite3.connect(":memory:", check_same_thread=False,
                                isolation_level=None)
        if isinstance(self._da, Archivio):
            with self._da._lucchetto:
                self._da.connessione.backup(copia)
        else:
            sorgente = database.connetti(Path(self._da))
            try:
                sorgente.backup(copia)
            finally:
                sorgente.close()
        copia.row_factory = sqlite3.Row
        copia.execute("PRAGMA foreign_keys = ON")
        copia.execute("PRAGMA temp_store = MEMORY")
        migrazioni.aggiorna(copia)
        self._connessione = copia
        self._modifiche_all_apertura = copia.total_changes
        return self

    def chiudi(self, con_copia: bool = True) -> None:
        with self._lucchetto:
            if self._connessione is not None:
                self._connessione.close()
                self._connessione = None

    def copia_adesso(self, motivo: str = "manuale") -> copie.Copia:
        raise ErroreOfficina(NELLA_PROVA_NO)

    def svuota_miniature(self) -> int:
        raise ErroreOfficina(NELLA_PROVA_NO)


NELLA_PROVA_NO = (
    "Questo, nella prova, non si fa: tocca i file veri o fa partire un lavoro "
    "lungo. Esci dalla prova e rifallo sul programma vero.")

_aperto: Archivio | None = None
_al_posto = contextvars.ContextVar("archivio_al_posto_del_vero", default=None)


@contextlib.contextmanager
def al_posto_del_vero(archivio: Archivio) -> Iterator[Archivio]:
    segno = _al_posto.set(archivio)
    try:
        yield archivio
    finally:
        _al_posto.reset(segno)


def in_prova() -> bool:
    sostituto = _al_posto.get()
    return sostituto is not None and sostituto.di_prova


def vero() -> Archivio:
    if _aperto is None or not _aperto.e_aperto:
        raise ArchivioChiuso("L'archivio non è aperto.")
    return _aperto


def apri(nome: str = REALE, password: str | None = None) -> Archivio:
    global _aperto
    if _aperto is not None and _aperto.dove.nome != nome:
        _aperto.chiudi()
        _aperto = None
    if _aperto is None:
        _aperto = Archivio(posizione(nome))
    return _aperto.apri(password)


def aperto() -> Archivio:
    sostituto = _al_posto.get()
    if sostituto is not None:
        if not sostituto.e_aperto:
            raise ArchivioChiuso("La prova è finita: ricarica la pagina.")
        return sostituto
    return vero()


def chiudi(con_copia: bool = True) -> None:
    global _aperto
    if _aperto is not None:
        _aperto.chiudi(con_copia)
        _aperto = None
