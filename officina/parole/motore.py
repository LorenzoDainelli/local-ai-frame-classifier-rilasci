from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Callable

from officina import registro
from officina.archivio.accesso import Archivio
from officina.descrittori import torcia
from officina.errori import ErroreOfficina, FileNonLeggibile
from officina.immagini import fotogrammi as estrattore
from officina.immagini import lettura
from officina.modello import file_media, segnalazioni
from officina.parole import SCHEDA
from officina.parole import magazzino

QUANTI_ALLA_VOLTA = 32

LATO_MASSIMO = 1600


GUASTI_PRIMA_DI_FERMARSI = 3


@dataclass
class Avanzamento:
    modello: str = SCHEDA.nome
    versione: str = SCHEDA.versione
    totale: int = 0
    letti: int = 0
    saltati: int = 0
    scritte: int = 0
    con_qualcosa: int = 0
    descritte: int = 0
    ms_per_scatto: float | None = None
    dove_gira: str = ""
    riposo_secondi: float = 0.0
    pause_per_calore: int = 0
    motivi_saltati: dict[str, int] = field(default_factory=dict)

    @property
    def resta(self) -> int:
        return max(self.totale - self.letti - self.saltati, 0)

    @property
    def percentuale(self) -> float:
        if not self.totale:
            return 100.0
        return round((self.letti + self.saltati) * 100 / self.totale, 1)

    def quanto_manca(self) -> str:
        if self.resta == 0:
            return "finito"
        if not self.ms_per_scatto:
            return "sto ancora misurando"
        secondi = int(self.resta * self.ms_per_scatto / 1000)
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


class Passata:

    def __init__(self, archivio: Archivio, lettore=None,
                 intensita: int | None = None):
        self.archivio = archivio
        self._lettore = lettore
        self.intensita = (intensita if intensita is not None
                          else int(archivio.impostazione("intensita_scheda") or 100))
        self.avanzamento = Avanzamento()
        self._fermati = threading.Event()
        self._misure: list[float] = []
        self._saltati_qui: set[int] = set()
        self._guasti_di_fila = 0
        self.per_video = int(archivio.impostazione("fotogrammi_per_video") or 40)


    def ferma(self) -> None:
        self._fermati.set()

    @property
    def fermata(self) -> bool:
        return self._fermati.is_set()

    def quanti_mancano(self) -> int:
        with self.archivio.lettura() as connessione:
            return magazzino.quanti_da_leggere(
                connessione, SCHEDA.nome, SCHEDA.versione)


    def esegui(self, al_passo: Callable[[Avanzamento], None] | None = None,
               quanti_al_massimo: int | None = None) -> Avanzamento:
        self._fermati.clear()
        self.avanzamento.totale = min(self.quanti_mancano(),
                                      quanti_al_massimo or 10 ** 9)

        lettore = self._lettore
        if lettore is None:
            from officina import parole

            lettore = parole.apri(self.archivio.dove.modelli)

        freno = torcia.Freno(self.intensita, fermato=lambda: self.fermata)
        registro.evento("parole.passata_inizio")
        try:
            lettore.apri()
            self.avanzamento.dove_gira = lettore.dove_gira()
            if al_passo:
                al_passo(self.avanzamento)
            self._gira(lettore, freno, al_passo, quanti_al_massimo)
        finally:
            lettore.chiudi()
            torcia.libera()
            self.avanzamento.riposo_secondi = freno.secondi_di_riposo
            self.avanzamento.pause_per_calore = freno.pause_per_calore
            registro.evento("parole.passata_fine", letti=self.avanzamento.letti,
                            scritte=self.avanzamento.scritte)
        return self.avanzamento

    def _gira(self, lettore, freno, al_passo, quanti_al_massimo) -> None:
        fatti = 0
        while not self.fermata:
            with self.archivio.lettura() as connessione:
                righe = magazzino.da_leggere(
                    connessione, SCHEDA.nome, SCHEDA.versione,
                    quanti=QUANTI_ALLA_VOLTA, escludi=sorted(self._saltati_qui))
            if not righe:
                break

            for riga in righe:
                if self.fermata:
                    return
                if quanti_al_massimo and fatti >= quanti_al_massimo:
                    return
                cominciato = time.perf_counter()
                if self._uno(lettore, riga["id"]):
                    fatti += 1
                durata = time.perf_counter() - cominciato
                self._segna_tempo(durata)
                if al_passo:
                    al_passo(self.avanzamento)
                freno.riposa(durata)


    def _uno(self, lettore, scatto_id: int) -> bool:
        try:
            immagini, file_id = self._immagini_di(scatto_id)
        except estrattore.Fermato:
            return False
        except FileNonLeggibile as errore:
            self._salta(scatto_id, errore.codice)
            self._metti_da_parte(scatto_id, errore.codice, errore.file_id)
            return False
        except Exception:
            self._salta(scatto_id, "errore_imprevisto")
            return False

        sguardi = []
        for numero, immagine in immagini:
            if self.fermata:
                return False
            try:
                sguardi.append((numero, _guarda(lettore, immagine)))
            except ErroreOfficina:
                raise
            except Exception:
                self._guasti_di_fila += 1
                if self.avanzamento.letti == 0 and self._guasti_di_fila >= GUASTI_PRIMA_DI_FERMARSI:
                    raise
                self._salta(scatto_id, "lettura_fallita")
                return False
        self._guasti_di_fila = 0

        with self.archivio.scrittura() as connessione:
            magazzino.dimentica_le_vecchie(connessione, scatto_id)
            quante = 0
            viste: set[str] = set()
            for numero, sguardo in sguardi:
                for scritta in sguardo.scritte:
                    chiave = magazzino.normalizza(scritta.testo)
                    if not chiave or chiave in viste:
                        continue
                    viste.add(chiave)
                    if magazzino.scrivi(connessione, scatto_id, file_id,
                                        scritta.testo, SCHEDA.nome, SCHEDA.versione,
                                        riquadro=scritta.riquadro,
                                        fotogramma=numero) is not None:
                        quante += 1
            descrizione = _la_descrizione(sguardi)
            if descrizione and magazzino.scrivi_descrizione(
                    connessione, scatto_id, file_id, descrizione,
                    SCHEDA.nome, SCHEDA.versione):
                self.avanzamento.descritte += 1
            magazzino.segna_letto(connessione, scatto_id, SCHEDA.nome,
                                  SCHEDA.versione, quante)
        self.avanzamento.letti += 1
        self.avanzamento.scritte += quante
        if quante:
            self.avanzamento.con_qualcosa += 1
        return True

    def _immagini_di(self, scatto_id: int):
        with self.archivio.lettura() as connessione:
            file_righe = file_media.di_scatto(connessione, scatto_id)
            principale = next(
                (r for r in file_righe
                 if r["ruolo"] == "principale" and r["genere"] == "immagine"),
                None)
            video = None
            if principale is None:
                video = next((r for r in file_righe if r["genere"] == "video"), None)
                principale = video
            if principale is None:
                raise FileNonLeggibile("Nessuna immagine da leggere.",
                                       codice="senza_file")
            percorso = file_media.percorso_migliore(connessione, principale["id"])
        if percorso is None:
            raise FileNonLeggibile("Il file non si trova sul disco.",
                                   codice="file_non_trovato",
                                   file_id=principale["id"])
        if video is not None:
            resa = estrattore.prendi(percorso, self.per_video, LATO_MASSIMO,
                                     basta=lambda: self.fermata)
            if not resa:
                raise FileNonLeggibile(resa.motivo or "Il video non si apre.",
                                       codice=resa.codice or "video_non_apribile",
                                       file_id=principale["id"])
            return [(f.numero, f.immagine) for f in resa.fotogrammi], principale["id"]
        try:
            immagine = lettura.copia_di_lavoro(percorso, LATO_MASSIMO)
        except FileNonLeggibile as errore:
            errore.file_id = principale["id"]
            raise
        return [(0, immagine)], principale["id"]

    def _salta(self, scatto_id: int, motivo: str) -> None:
        self.avanzamento.saltati += 1
        self.avanzamento.motivi_saltati[motivo] = \
            self.avanzamento.motivi_saltati.get(motivo, 0) + 1
        self._saltati_qui.add(scatto_id)

    def _metti_da_parte(self, scatto_id: int, codice: str,
                        file_id: int | None) -> None:
        with self.archivio.scrittura() as connessione:
            segnalazioni.segna(connessione, segnalazioni.NON_SI_APRE, scatto_id,
                               dettaglio=codice, file_id=file_id)

    def _segna_tempo(self, secondi: float) -> None:
        self._misure.append(secondi * 1000)
        if len(self._misure) >= 2:
            recenti = self._misure[-30:]
            self.avanzamento.ms_per_scatto = sum(recenti) / len(recenti)


def _guarda(lettore, immagine):
    from officina.parole.lettore import Sguardo

    if hasattr(lettore, "guarda"):
        return lettore.guarda(immagine)
    return Sguardo(scritte=list(lettore.leggi(immagine)))


def _la_descrizione(sguardi) -> str:
    descritti = [sguardo.descrizione for _, sguardo in sguardi if sguardo.descrizione]
    if not descritti:
        return ""
    return descritti[len(descritti) // 2]
