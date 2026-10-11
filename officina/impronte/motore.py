from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Sequence

from PIL import Image

from officina import registro
from officina.archivio.accesso import Archivio
from officina.descrittori import apri as apri_descrittore
from officina.descrittori import griglia, preparazione, scheda, torcia
from officina.descrittori.base import Descrittore, Scheda
from officina.errori import FileNonLeggibile
from officina.immagini import fotogrammi as estrattore
from officina.immagini import lettura
from officina.modello import file_media, impronte as magazzino, segnalazioni

IMMAGINI_PER_GRUPPO = 24

PRIMA_DI_STIMARE = 12

QUANTI_SALTATI_SI_RICORDANO = 100


@dataclass
class Avanzamento:
    descrittore: str
    versione: str
    totale: int = 0
    fatti: int = 0
    saltati: int = 0
    impronte: int = 0
    fotogrammi: int = 0
    ms_per_scatto: float | None = None
    dove_gira: str = ""
    sta_aprendo: bool = False
    sta_chiudendo: bool = False
    riposo_secondi: float = 0.0
    pause_per_calore: int = 0
    motivi_saltati: dict[str, int] = field(default_factory=dict)
    scatti_saltati: list[tuple[int, str]] = field(default_factory=list)
    messi_da_parte: int = 0

    @property
    def resta(self) -> int:
        return max(self.totale - self.fatti - self.saltati, 0)

    @property
    def percentuale(self) -> float:
        if not self.totale:
            return 100.0
        return round((self.fatti + self.saltati) * 100 / self.totale, 1)

    @property
    def secondi_rimasti(self) -> int | None:
        if not self.ms_per_scatto or self.resta == 0:
            return None
        return int(self.resta * self.ms_per_scatto / 1000)

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


@dataclass
class _Lavoro:

    scatto_id: int
    file_id: int | None
    inquadratura: str
    metodo: str
    riquadro: tuple[float, float, float, float]
    fotogramma: int
    istante_ms: int | None
    immagine: Image.Image


@dataclass
class _Pronto:

    righe: Sequence
    lavori: list[_Lavoro]
    saltati: list[tuple[int, str]]
    non_si_aprono: list[tuple[int, str, int | None]]
    fotogrammi: int


class Passata:

    def __init__(self, archivio: Archivio, nome: str,
                 intensita: int | None = None,
                 fotogrammi_per_video: int | None = None):
        self.archivio = archivio
        self.carta: Scheda = scheda(nome)
        self._intensita_fissata = intensita is not None
        self.intensita = (intensita if intensita is not None
                          else self._intensita_ora())
        self.per_video = (fotogrammi_per_video if fotogrammi_per_video is not None
                          else int(archivio.impostazione("fotogrammi_per_video") or 40))
        self.tre_inquadrature = bool(
            archivio.impostazione("impronte_a_piu_ingrandimenti"))
        self.a_griglia = bool(archivio.impostazione("impronte_a_griglia"))
        self.avanzamento = Avanzamento(self.carta.nome, self.carta.versione)
        self._fermati = threading.Event()
        self._misure: list[float] = []
        self._saltati_in_questa_passata: set[int] = set()


    def ferma(self) -> None:
        self._fermati.set()

    @property
    def fermata(self) -> bool:
        return self._fermati.is_set()

    def _intensita_ora(self) -> int:
        if self._intensita_fissata:
            return self.intensita
        return int(self.archivio.impostazione("intensita_scheda") or 100)

    def quanti_mancano(self) -> int:
        with self.archivio.lettura() as connessione:
            return magazzino.quanti_da_fare(connessione, self.carta.nome,
                                            self.carta.versione)


    def esegui(self, al_passo: Callable[[Avanzamento], None] | None = None,
               quanti_al_massimo: int | None = None) -> Avanzamento:
        self._fermati.clear()
        self.avanzamento.totale = min(
            self.quanti_mancano(), quanti_al_massimo or 10 ** 9)

        descrittore = apri_descrittore(self.carta.nome, self.archivio.dove.modelli)
        freno = torcia.Freno(self.intensita, fermato=lambda: self.fermata)
        registro.evento("impronte.passata_inizio", descrittore_noto=True)

        try:
            self.avanzamento.sta_aprendo = True
            if al_passo:
                al_passo(self.avanzamento)
            descrittore.apri()
            self.avanzamento.sta_aprendo = False
            self.avanzamento.dove_gira = descrittore.dove_gira()
            if al_passo:
                al_passo(self.avanzamento)
            self._gira(descrittore, freno, al_passo, quanti_al_massimo)
        finally:
            self.avanzamento.sta_aprendo = False
            self.avanzamento.sta_chiudendo = True
            try:
                descrittore.chiudi()
                torcia.libera()
            finally:
                self.avanzamento.sta_chiudendo = False
            self.avanzamento.riposo_secondi = freno.secondi_di_riposo
            self.avanzamento.pause_per_calore = freno.pause_per_calore
            registro.evento("impronte.passata_fine", fatti=self.avanzamento.fatti,
                            saltati=self.avanzamento.saltati)
        return self.avanzamento

    def _gira(self, descrittore: Descrittore, freno: torcia.Freno,
              al_passo, quanti_al_massimo: int | None) -> None:
        fatti_in_tutto = 0
        with ThreadPoolExecutor(max_workers=1,
                                thread_name_prefix="impronte-prepara") as cucina:
            while not self.fermata:
                with self.archivio.lettura() as connessione:
                    righe = magazzino.scatti_da_fare(
                        connessione, self.carta.nome, self.carta.versione, quanti=64,
                        escludi=sorted(self._saltati_in_questa_passata),
                    )
                if not righe:
                    break

                gruppi = self._a_gruppi(righe)
                in_arrivo = cucina.submit(self._prepara_gruppo, gruppi[0])
                for indice, gruppo in enumerate(gruppi):
                    if self.fermata:
                        if in_arrivo is not None:
                            in_arrivo.cancel()
                        return
                    if quanti_al_massimo and fatti_in_tutto >= quanti_al_massimo:
                        if in_arrivo is not None:
                            in_arrivo.cancel()
                        return
                    cominciato = time.perf_counter()
                    pronto = in_arrivo.result()
                    in_arrivo = (
                        cucina.submit(self._prepara_gruppo, gruppi[indice + 1])
                        if indice + 1 < len(gruppi) else None
                    )
                    fatti_in_tutto += self._fai_un_gruppo(descrittore, pronto)
                    durata = time.perf_counter() - cominciato
                    self._segna_tempo(durata, len(gruppo))
                    if al_passo:
                        al_passo(self.avanzamento)
                    freno.cambia(self._intensita_ora())
                    freno.riposa(durata)

    def _a_gruppi(self, righe) -> list[list]:
        gruppi, corrente, quante = [], [], 0
        for riga in righe:
            corrente.append(riga)
            quante += (self.per_video * self._per_scatto()
                       if riga["genere"] == "video" else self._per_scatto())
            if quante >= IMMAGINI_PER_GRUPPO:
                gruppi.append(corrente)
                corrente, quante = [], 0
        if corrente:
            gruppi.append(corrente)
        return gruppi

    def _per_scatto(self) -> int:
        quante = 3 if self.tre_inquadrature else 1
        if self.a_griglia:
            quante += griglia.CASELLE_SUL_LATO_LUNGO * 5
        return quante

    def _prepara_gruppo(self, righe) -> _Pronto:
        lavori: list[_Lavoro] = []
        saltati: list[tuple[int, str]] = []
        non_si_aprono: list[tuple[int, str, int | None]] = []
        fotogrammi = 0
        fatte: list = []

        for riga in righe:
            if self.fermata:
                break
            try:
                ritagli, quanti_fotogrammi = self._ritagli_di(riga)
            except estrattore.Fermato:
                break
            except FileNonLeggibile as errore:
                saltati.append((riga["id"], errore.codice))
                non_si_aprono.append(
                    (riga["id"], errore.codice, errore.file_id))
            except Exception as errore:
                saltati.append((riga["id"], "errore_imprevisto"))
                non_si_aprono.append((riga["id"], "errore_imprevisto", None))
                registro.errore("impronte.scatto_rotto", **registro.dove_si_e_rotto(errore))
            else:
                fotogrammi += quanti_fotogrammi
                lavori.extend(ritagli)
            fatte.append(riga)

        return _Pronto(righe=fatte, lavori=lavori, saltati=saltati,
                       non_si_aprono=non_si_aprono, fotogrammi=fotogrammi)

    def _fai_un_gruppo(self, descrittore: Descrittore, pronto: _Pronto) -> int:
        righe, lavori = pronto.righe, pronto.lavori

        self.avanzamento.fotogrammi += pronto.fotogrammi
        for scatto_id, motivo in pronto.saltati:
            self.avanzamento.saltati += 1
            self.avanzamento.motivi_saltati[motivo] = \
                self.avanzamento.motivi_saltati.get(motivo, 0) + 1
            if len(self.avanzamento.scatti_saltati) < QUANTI_SALTATI_SI_RICORDANO:
                self.avanzamento.scatti_saltati.append((scatto_id, motivo))
        self._segna_che_non_si_aprono(pronto.non_si_aprono)

        if not lavori:
            self._non_ripescarli([riga["id"] for riga in righe])
            return 0

        valori = descrittore.descrivi([lavoro.immagine for lavoro in lavori])

        fatti = 0
        with self.archivio.scrittura() as connessione:
            for lavoro, impronta in zip(lavori, valori, strict=True):
                magazzino.scrivi(
                    connessione, lavoro.scatto_id, lavoro.file_id,
                    self.carta.nome, self.carta.versione, lavoro.inquadratura,
                    lavoro.metodo, lavoro.riquadro, impronta,
                    fotogramma=lavoro.fotogramma, istante_ms=lavoro.istante_ms,
                )
                self.avanzamento.impronte += 1
            visti = {lavoro.scatto_id for lavoro in lavori}
            fatti = len(visti)
            self.avanzamento.fatti += fatti
        self._non_ripescarli([riga["id"] for riga in righe if riga["id"] not in visti])
        return fatti


    def _ritagli_di(self, riga) -> tuple[list[_Lavoro], int]:
        with self.archivio.lettura() as connessione:
            file_righe = file_media.di_scatto(connessione, riga["id"])
            principale = _il_file_da_guardare(file_righe)
            if principale is None:
                raise FileNonLeggibile("Nessun file da guardare.", codice="senza_file")
            percorso = file_media.percorso_migliore(connessione, principale["id"])

        if percorso is None:
            raise FileNonLeggibile("Il file non si trova sul disco.",
                                   codice="file_non_trovato",
                                   file_id=principale["id"])

        if principale["genere"] == "immagine":
            try:
                immagine = lettura.copia_di_lavoro(percorso, self.carta.lato * 4)
            except FileNonLeggibile as errore:
                errore.file_id = principale["id"]
                raise
            return [
                _Lavoro(riga["id"], principale["id"], ritaglio.inquadratura,
                        ritaglio.metodo, ritaglio.riquadro, 0, None, ritaglio.immagine)
                for ritaglio in self._inquadrature(immagine)
            ], 0
        return self._ritagli_di_un_video(riga, principale, percorso)

    def _ritagli_di_un_video(self, riga, principale,
                             percorso: Path) -> tuple[list[_Lavoro], int]:
        resa = estrattore.prendi(percorso, self.per_video, self.carta.lato * 4,
                                 basta=lambda: self.fermata)
        if not resa:
            raise FileNonLeggibile(resa.motivo or "Il video non si apre.",
                                   codice=resa.codice or "video_non_apribile",
                                   file_id=principale["id"])
        lavori = []
        for fotogramma in resa.fotogrammi:
            for ritaglio in self._inquadrature(fotogramma.immagine):
                lavori.append(_Lavoro(
                    riga["id"], principale["id"], ritaglio.inquadratura,
                    ritaglio.metodo, ritaglio.riquadro, fotogramma.numero,
                    fotogramma.istante_ms, ritaglio.immagine,
                ))
        return lavori, len(resa.fotogrammi)

    def _inquadrature(self, immagine):
        tutti = preparazione.tre_inquadrature(immagine, self.carta.lato)
        if not self.tre_inquadrature:
            tutti = [r for r in tutti if r.inquadratura == preparazione.INTERA]
        if self.a_griglia:
            tutti = tutti + griglia.ritagli(immagine)
        return tutti


    def _non_ripescarli(self, scatti: Sequence[int]) -> None:
        self._saltati_in_questa_passata.update(scatti)

    def _segna_che_non_si_aprono(
            self, elenco: Sequence[tuple[int, str, int | None]]) -> None:
        if not elenco:
            return
        with self.archivio.scrittura() as connessione:
            for scatto_id, codice, file_id in elenco:
                if file_id is None:
                    principale = connessione.execute(
                        "SELECT id FROM file_media WHERE scatto_id = ? "
                        "AND ruolo = 'principale' LIMIT 1", (scatto_id,)).fetchone()
                    file_id = principale[0] if principale else None
                segnalazioni.segna(connessione, segnalazioni.NON_SI_APRE,
                                   scatto_id, dettaglio=codice, file_id=file_id)
        self.avanzamento.messi_da_parte += len(elenco)

    def _segna_tempo(self, secondi: float, quanti_scatti: int) -> None:
        if quanti_scatti:
            self._misure.append(secondi * 1000 / quanti_scatti)
        if len(self._misure) >= 2:
            recenti = self._misure[-30:]
            self.avanzamento.ms_per_scatto = sum(recenti) / len(recenti)


def _il_file_da_guardare(file_righe) -> object | None:
    for riga in file_righe:
        if riga["ruolo"] == "principale":
            return riga
    for riga in file_righe:
        if riga["genere"] == "immagine":
            return riga
    return file_righe[0] if file_righe else None


class Coda:

    def __init__(self, archivio: Archivio, nomi: Sequence[str],
                 intensita: int | None = None,
                 fotogrammi_per_video: int | None = None):
        self.archivio = archivio
        self.nomi = list(nomi)
        self.intensita = intensita
        self.per_video = fotogrammi_per_video
        self.passata: Passata | None = None
        self.finite: list[Avanzamento] = []
        self._fermati = threading.Event()
        self.totali = [self._quanti_mancano(nome) for nome in self.nomi]
        self.totale = sum(self.totali)

    def _quanti_mancano(self, nome: str) -> int:
        carta = scheda(nome)
        with self.archivio.lettura() as connessione:
            return magazzino.quanti_da_fare(connessione, carta.nome, carta.versione)


    def ferma(self) -> None:
        self._fermati.set()
        if self.passata is not None:
            self.passata.ferma()

    @property
    def fermata(self) -> bool:
        return self._fermati.is_set()

    def esegui(self, al_passo: Callable[["Coda"], None] | None = None) -> "Coda":
        for nome in self.nomi:
            if self.fermata:
                break
            self.passata = Passata(self.archivio, nome, intensita=self.intensita,
                                   fotogrammi_per_video=self.per_video)
            try:
                self.passata.esegui(lambda _: al_passo(self) if al_passo else None)
            finally:
                self.finite.append(self.passata.avanzamento)
                self.passata = None
        return self


    @property
    def adesso(self) -> str:
        return self.passata.carta.nome if self.passata else ""

    @property
    def passo(self) -> int:
        return min(len(self.finite) + 1, len(self.nomi)) if self.nomi else 0

    @property
    def fatti(self) -> int:
        conto = sum(a.fatti + a.saltati for a in self.finite)
        if self.passata:
            conto += self.passata.avanzamento.fatti + self.passata.avanzamento.saltati
        return conto

    def per_modello(self) -> list[dict]:
        righe = []
        for posto, nome in enumerate(self.nomi):
            totale = self.totali[posto]
            if posto < len(self.finite):
                fatti = self.finite[posto].fatti + self.finite[posto].saltati
            elif posto == len(self.finite) and self.passata:
                fatti = self.passata.avanzamento.fatti + self.passata.avanzamento.saltati
            else:
                fatti = 0
            fatti = min(fatti, totale)
            righe.append({"nome": nome, "fatti": fatti, "totale": totale,
                          "percento": round(fatti * 100 / totale) if totale else 100,
                          "adesso": posto == len(self.finite) and self.passata is not None})
        return righe

    @property
    def scatti(self) -> tuple[int, int]:
        totale = max(self.totali, default=0)
        if not self.totale:
            return 0, totale
        return min(totale, self.fatti * totale // self.totale), totale

    @property
    def impronte(self) -> int:
        conto = sum(a.impronte for a in self.finite)
        if self.passata:
            conto += self.passata.avanzamento.impronte
        return conto

    @property
    def saltati(self) -> int:
        return sum(self.motivi_saltati.values())

    @property
    def motivi_saltati(self) -> dict[str, int]:
        insieme: dict[str, int] = {}
        pezzi = [a.motivi_saltati for a in self.finite]
        if self.passata:
            pezzi.append(self.passata.avanzamento.motivi_saltati)
        for pezzo in pezzi:
            for motivo, quante in pezzo.items():
                insieme[motivo] = max(insieme.get(motivo, 0), quante)
        return insieme

    @property
    def scatti_saltati(self) -> list[tuple[int, str]]:
        visti: dict[int, str] = {}
        pezzi = [a.scatti_saltati for a in self.finite]
        if self.passata:
            pezzi.append(self.passata.avanzamento.scatti_saltati)
        for pezzo in pezzi:
            for scatto_id, motivo in pezzo:
                visti.setdefault(scatto_id, motivo)
        return sorted(visti.items())[:QUANTI_SALTATI_SI_RICORDANO]

    @property
    def percentuale(self) -> float:
        if not self.totale:
            return 100.0
        return round(min(self.fatti, self.totale) * 100 / self.totale, 1)

    @property
    def dove_gira(self) -> str:
        return self.passata.avanzamento.dove_gira if self.passata else ""

    @property
    def sta_aprendo(self) -> bool:
        return bool(self.passata and self.passata.avanzamento.sta_aprendo)

    @property
    def sta_chiudendo(self) -> bool:
        return bool(self.passata and self.passata.avanzamento.sta_chiudendo)

    def perche_ci_mette(self) -> str:
        if not self.fermata:
            return ""
        if self.sta_aprendo:
            return ("sto finendo di aprire il modello: è l'unico pezzo che "
                    "non si può interrompere a metà")
        if self.sta_chiudendo:
            return "sto chiudendo il modello e liberando la scheda video"
        if self.passata is not None:
            return ("sto finendo il gruppo di scatti che la scheda video ha "
                    "già in mano, poi mi fermo")
        return "mi sto fermando"

    def quanto_manca(self) -> str:
        resta = max(self.totale - self.fatti, 0)
        if resta == 0:
            return "finito"
        ritmo = self.passata.avanzamento.ms_per_scatto if self.passata else None
        if not ritmo:
            return "sto ancora misurando"
        finto = Avanzamento("", "", totale=resta, ms_per_scatto=ritmo)
        return finto.quanto_manca()
