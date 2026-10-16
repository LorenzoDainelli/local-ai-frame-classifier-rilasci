from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from officina import registro
from officina.archivio.accesso import Archivio
from officina.archivio.database import tutti, uno
from officina.corpi import Interrotta, MancanoIModelli, NonSiAccende
from officina.corpi import rilevatore as rilevatore_mod
from officina.descrittori import torcia
from officina.errori import ErroreOfficina, FileNonLeggibile
from officina.immagini import lettura
from officina.importazione import gruppi
from officina.modello import corpi as corpi_mod
from officina.modello import file_media, segnalazioni

LATO_DI_LAVORO = 1280


@dataclass
class Avanzamento:
    fatti: int = 0
    saltati: int = 0
    corpi: int = 0
    scatti_con_corpi: int = 0
    volti_collegati: int = 0
    totale: int = 0
    motivi: dict[str, int] = field(default_factory=dict)

    def a_parole(self) -> str:
        return (f"fatti {self.fatti} · saltati {self.saltati} · "
                f"persone trovate {self.corpi} · in {self.scatti_con_corpi} scatti · "
                f"volti collegati {self.volti_collegati}")


class Passata:

    def __init__(self, archivio: Archivio, rilevatore=None,
                 intensita: int | None = None):
        self.archivio = archivio
        if rilevatore is None:
            from officina import corpi as corpi_pacchetto

            rilevatore = corpi_pacchetto.apri(archivio)
        self.rilevatore = rilevatore
        self.intensita = (intensita if intensita is not None
                          else int(archivio.impostazione("intensita_scheda") or 100))
        self.avanzamento = Avanzamento()
        self._fermati = threading.Event()
        self._memoria = torcia.ContoDellaMemoria()

    def ferma(self) -> None:
        self._fermati.set()

    @property
    def fermata(self) -> bool:
        return self._fermati.is_set()

    def _versione(self) -> str:
        return self.rilevatore.versione

    def quanti_mancano(self) -> int:
        with self.archivio.lettura() as connessione:
            riga = uno(connessione, _domanda_da_fare(
                "count(*) AS q", gruppi.clausola(connessione, "intelligenza")),
                rilevatore_mod.NOME, self._versione())
        return riga["q"] if riga else 0

    def esegui(self, al_passo: Callable[[Avanzamento], None] | None = None,
               quanti: int | None = None) -> Avanzamento:
        freno = torcia.Freno(self.intensita, fermato=lambda: self.fermata)
        with self.archivio.lettura() as connessione:
            da_fare = [riga["id"] for riga in tutti(
                connessione, _domanda_da_fare(
                    "s.id", gruppi.clausola(connessione, "intelligenza")),
                rilevatore_mod.NOME, self._versione())]
        if quanti:
            da_fare = da_fare[:quanti]
        self.avanzamento.totale = len(da_fare)
        self._memoria = torcia.ContoDellaMemoria()

        try:
            self._accendi(bool(da_fare))
            for gruppo in self._a_gruppi(da_fare):
                if self.fermata:
                    break
                partito = time.monotonic()
                try:
                    self._guarda_il_gruppo(gruppo)
                except Interrotta:
                    break
                if al_passo:
                    al_passo(self.avanzamento)
                freno.riposa(time.monotonic() - partito)
        finally:
            self.rilevatore.spegni()
        registro.evento("corpi.passata", fatti=self.avanzamento.fatti,
                        corpi=self.avanzamento.corpi)
        return self.avanzamento

    def rifai_i_punti(self, al_passo: Callable[[int, int], None] | None = None) -> int:
        freno = torcia.Freno(self.intensita, fermato=lambda: self.fermata)
        with self.archivio.lettura() as connessione:
            da_fare = [riga["id"] for riga in tutti(
                connessione, _domanda_da_ripuntare(
                    "DISTINCT s.id", gruppi.clausola(connessione, "intelligenza")),
                rilevatore_mod.SCALA_DEI_PUNTI)]
        rifatti = 0
        self._memoria = torcia.ContoDellaMemoria()
        try:
            for numero, scatto_id in enumerate(da_fare, start=1):
                if self.fermata:
                    break
                partito = time.monotonic()
                try:
                    rifatti += self._ripunta(scatto_id)
                    self._riuscito()
                except Interrotta:
                    break
                except ErroreOfficina as errore:
                    self._segnala(scatto_id, errore)
                except Exception as guasto:              # noqa: BLE001
                    if torcia.memoria_finita(guasto):
                        self._memoria.finita(scatto_id, guasto)
                    else:
                        registro.avviso("corpi.punti_non_rifatti", **registro.dove_si_e_rotto(guasto))
                        self._segnala(scatto_id, ErroreOfficina(
                            "Questo scatto non si è lasciato guardare."))
                if al_passo:
                    al_passo(numero, len(da_fare))
                freno.riposa(time.monotonic() - partito)
        finally:
            self.rilevatore.spegni()
        registro.evento("corpi.punti_rifatti", scatti=len(da_fare), corpi=rifatti)
        return rifatti

    def _ripunta(self, scatto_id: int) -> int:
        with self.archivio.lettura() as connessione:
            vecchi = corpi_mod.da_ripuntare(connessione, scatto_id)
        if not vecchi:
            return 0
        _, quadri = self._leggi(scatto_id)
        nuovi: dict[int, list] = {}
        for numero, lavoro, _intera in quadri:
            if self.fermata:
                raise Interrotta()
            qui = [corpo for corpo in vecchi if corpo["fotogramma"] == numero]
            if not qui:
                continue
            punti = self.rilevatore.punti_di(lavoro, [corpo["riquadro"] for corpo in qui])
            for corpo, suoi in zip(qui, punti, strict=True):
                nuovi[corpo["id"]] = suoi
        if nuovi:
            with self.archivio.scrittura() as connessione:
                corpi_mod.ripunta(connessione, scatto_id, nuovi)
        return len(nuovi)

    def _a_gruppi(self, da_fare: list[int]):
        insieme = max(1, int(getattr(self.rilevatore, "quanti_insieme", 1) or 1))
        for inizio in range(0, len(da_fare), insieme):
            yield da_fare[inizio:inizio + insieme]

    def _accendi(self, serve: bool) -> None:
        accendi = getattr(self.rilevatore, "accendi", None)
        if accendi is None or not serve:
            return
        try:
            accendi()
        except ErroreOfficina:
            raise
        except Exception as guasto:
            raise _non_si_accendono(guasto) from guasto

    def _guarda_il_gruppo(self, gruppo: list[int]) -> None:
        tetto = int(getattr(self.rilevatore, "quadri_insieme", 0) or 0)
        letti: list[tuple[int, int, list]] = []
        quadri_in_tutto = 0
        for scatto_id in gruppo:
            if self.fermata:
                raise Interrotta()
            if tetto and letti and quadri_in_tutto >= tetto:
                self._completa_e_salva(letti)
                letti, quadri_in_tutto = [], 0
            try:
                file_id, quadri = self._leggi(scatto_id)
                visti = []
                for numero, lavoro, intera in quadri:
                    if self.fermata:
                        raise Interrotta()
                    visti.append((numero, *self._trova(lavoro, intera)))
            except (Interrotta, MancanoIModelli):
                raise
            except NonSiAccende as guasto:
                raise _non_si_accendono(guasto.__cause__ or guasto) from guasto
            except ErroreOfficina as errore:
                self._segnala(scatto_id, errore)
                continue
            except Exception as guasto:          # noqa: BLE001
                if torcia.memoria_finita(guasto):
                    self._memoria.finita(scatto_id, guasto)
                else:
                    self._segnala(scatto_id, ErroreOfficina(
                        "Questo scatto non si è lasciato guardare."))
                continue
            letti.append((scatto_id, file_id, visti))
            quadri_in_tutto += len(visti)
        if letti:
            self._completa_e_salva(letti)

    def _trova(self, lavoro, intera):
        trova = getattr(self.rilevatore, "trova_e_prepara", None)
        if trova is None:
            return self.rilevatore.guarda(lavoro), None
        return trova(lavoro, intera)

    def _leggi(self, scatto_id: int):
        with self.archivio.lettura() as connessione:
            righe = file_media.di_scatto(connessione, scatto_id)
            principale = next((f for f in righe if f["ruolo"] == "principale"), None)
            if principale is None:
                raise ErroreOfficina("Questo scatto non ha un file principale.")
            percorso = file_media.percorso_migliore(connessione, principale["id"])
            fotogrammi = [(riga["fotogramma"], riga["istante_ms"]) for riga in tutti(
                connessione,
                "SELECT fotogramma, min(istante_ms) AS istante_ms FROM impronte "
                "WHERE scatto_id = ? AND inquadratura = 'intera' "
                "GROUP BY fotogramma ORDER BY fotogramma", scatto_id)]

        if percorso is None:
            raise ErroreOfficina("Il file non si trova sul disco.")

        def quadri():
            if principale["genere"] == "immagine":
                intera = lettura.copia_di_lavoro(Path(percorso))
                yield 0, _di_lavoro(intera), intera
                return
            from officina.immagini import fotogrammi as estrattore

            for numero, istante in (fotogrammi or [(0, None)]):
                intera = estrattore.uno(Path(percorso), numero, istante)
                if intera is not None:
                    yield numero, _di_lavoro(intera), intera

        return principale["id"], quadri()

    def _completa_e_salva(self, letti) -> None:
        completa = getattr(self.rilevatore, "completa", None)
        lotti = [(corpi, preparati) for _, _, visti in letti for _, corpi, preparati in visti]
        guasti: list = [None] * len(lotti)
        if completa is not None and lotti:
            try:
                guasti = completa(lotti, fermato=lambda: self.fermata)
            except (Interrotta, ErroreOfficina):
                raise
            except NonSiAccende as guasto:
                raise _non_si_accendono(guasto.__cause__ or guasto) from guasto
        posto = 0
        for scatto_id, file_id, visti in letti:
            suoi = guasti[posto:posto + len(visti)]
            posto += len(visti)
            guasto = next((g for g in suoi if g is not None), None)
            if torcia.memoria_finita(guasto):
                self._memoria.finita(scatto_id, guasto)
                continue
            if guasto is not None:
                self._segnala(scatto_id, guasto if isinstance(guasto, ErroreOfficina)
                              else ErroreOfficina("Questo scatto non si è lasciato guardare."))
                continue
            trovati = [(numero, corpo) for numero, corpi, _ in visti for corpo in corpi]
            self._salva(scatto_id, file_id, trovati)
            self.avanzamento.fatti += 1
            self._riuscito()

    def _riuscito(self) -> None:
        for pesante in self._memoria.riuscito():
            self._segnala(pesante, ErroreOfficina(torcia.TROPPO_PER_LA_MEMORIA))

    def _salva(self, scatto_id: int, file_id: int | None, trovati) -> None:
        with self.archivio.scrittura() as connessione:
            corpi_mod.salva(connessione, scatto_id, file_id, trovati,
                            rilevatore_mod.NOME, self._versione())
            collegati = uno(connessione,
                            "SELECT count(*) AS q FROM corpi WHERE scatto_id = ? "
                            "AND volto_id IS NOT NULL", scatto_id)
        if trovati:
            self.avanzamento.scatti_con_corpi += 1
        self.avanzamento.corpi += len(trovati)
        self.avanzamento.volti_collegati += collegati["q"] if collegati else 0

    def _segnala(self, scatto_id: int, errore: ErroreOfficina) -> None:
        self.avanzamento.saltati += 1
        codice = errore.codice or "non_letto"
        self.avanzamento.motivi[codice] = self.avanzamento.motivi.get(codice, 0) + 1
        quale = (segnalazioni.NON_SI_APRE
                 if isinstance(errore, FileNonLeggibile)
                 else segnalazioni.CORPI_NON_LETTI)
        dettaglio = (codice if quale == segnalazioni.NON_SI_APRE
                     else errore.messaggio)
        with self.archivio.scrittura() as connessione:
            segnalazioni.segna(connessione, quale, scatto_id,
                               dettaglio=dettaglio,
                               file_id=getattr(errore, "file_id", None))


def _di_lavoro(intera):
    from PIL import Image

    lavoro = intera.copy()
    if max(lavoro.size) > LATO_DI_LAVORO:
        lavoro.thumbnail((LATO_DI_LAVORO, LATO_DI_LAVORO), Image.Resampling.LANCZOS)
    return lavoro


def _non_si_accendono(guasto: BaseException) -> ErroreOfficina:
    if torcia.memoria_finita(guasto):
        return torcia.senza_memoria(guasto)
    registro.errore("corpi.non_si_accendono", **registro.dove_si_e_rotto(guasto))
    errore = ErroreOfficina(
        "I modelli del corpo non si sono accesi. Gli scatti restano da guardare: "
        "riprova dopo aver riavviato il programma.", codice="corpi_non_si_accendono")
    errore.dettaglio = registro.passi_del_guasto(guasto)
    return errore


def _domanda_da_fare(cosa: str, piu: str = "") -> str:
    return f"""
        SELECT {cosa} FROM scatti s
        WHERE s.fuori_archivio = 0{piu}
          AND NOT EXISTS (
              SELECT 1 FROM corpi_guardati g
              WHERE g.scatto_id = s.id AND g.modello = ? AND g.versione = ?)
          {segnalazioni.clausola(segnalazioni.CORPI_NON_LETTI)}
          {segnalazioni.clausola(segnalazioni.NON_SI_APRE)}
        ORDER BY s.id
    """


def _domanda_da_ripuntare(cosa: str, piu: str = "") -> str:
    return f"""
        SELECT {cosa} FROM scatti s
        JOIN corpi c ON c.scatto_id = s.id
        WHERE s.fuori_archivio = 0{piu} AND c.punti_scala < ?
          {segnalazioni.clausola(segnalazioni.CORPI_NON_LETTI)}
          {segnalazioni.clausola(segnalazioni.NON_SI_APRE)}
        ORDER BY s.id
    """


def quanti_da_ripuntare_senza_aprire(connessione) -> int:
    riga = uno(connessione, _domanda_da_ripuntare(
        "count(DISTINCT s.id) AS q", gruppi.clausola(connessione, "intelligenza")),
        rilevatore_mod.SCALA_DEI_PUNTI)
    return riga["q"] if riga else 0


def quanti_mancano_senza_aprire(connessione) -> int:
    riga = uno(connessione, _domanda_da_fare(
        "count(*) AS q", gruppi.clausola(connessione, "intelligenza")),
        rilevatore_mod.NOME, rilevatore_mod.VERSIONE)
    return riga["q"] if riga else 0
