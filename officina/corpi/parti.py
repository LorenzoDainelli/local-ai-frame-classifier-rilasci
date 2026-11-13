from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from officina import registro
from officina.archivio.database import tutti
from officina.corpi import rilevatore as rilevatore_mod
from officina.descrittori import torcia
from officina.errori import DaRifare, ErroreOfficina
from officina.immagini import lettura
from officina.modello import file_media
from officina.modello import parti as elenco
from officina.sicuro import dall_archivio

MODELLO = "sam3"
VERSIONE = "1"
SICUREZZA_MINIMA = 0.5
SCATTI_A_TURNO = 16
LATO_DI_LAVORO = 2048
NON_LETTO = -1


@dataclass
class Avanzamento:
    fatti: int = 0
    saltati: int = 0
    parti: int = 0
    totale: int = 0
    motivi: dict[str, int] = field(default_factory=dict)

    def a_parole(self) -> str:
        return (f"parti del corpo: {self.parti} in {self.fatti} scatti · "
                f"saltati {self.saltati}")


def cosa_manca(cartella_modelli: Path) -> str:
    casa = Path(cartella_modelli) / rilevatore_mod.NOME / rilevatore_mod.CARTELLA_SAM3
    if not (casa / rilevatore_mod.PROVA_SAM3).exists():
        return "Per le parti del corpo serve SAM 3, che arriva con i modelli del corpo."
    return ""


def apri_il_cercatore(cartella_modelli: Path):
    from officina.corpi.sam3 import Separatore

    casa = Path(cartella_modelli) / rilevatore_mod.NOME / rilevatore_mod.CARTELLA_SAM3
    return Separatore(casa, SICUREZZA_MINIMA)


def _di_lavoro(intera):
    from PIL import Image

    lavoro = intera.copy()
    if max(lavoro.size) > LATO_DI_LAVORO:
        lavoro.thumbnail((LATO_DI_LAVORO, LATO_DI_LAVORO), Image.Resampling.LANCZOS)
    return lavoro


def quadri_di(archivio, scatto_id: int):
    with archivio.lettura() as connessione:
        righe = file_media.di_scatto(connessione, scatto_id)
        principale = file_media.quello_da_guardare(righe)
        if principale is None:
            raise ErroreOfficina("Questo scatto non ha un file principale.",
                                 codice="senza_file")
        percorso = file_media.da_guardare(connessione, principale["id"])
        fotogrammi = [(riga["fotogramma"], riga["istante_ms"]) for riga in tutti(
            connessione,
            "SELECT i.fotogramma, min(i.istante_ms) AS istante_ms FROM impronte i "
            "WHERE i.scatto_id = ? AND i.inquadratura = 'intera' AND i.fotogramma IN "
            "(SELECT c.fotogramma FROM corpi c WHERE c.scatto_id = i.scatto_id) "
            "GROUP BY i.fotogramma ORDER BY i.fotogramma", scatto_id)]
    if percorso is None:
        raise ErroreOfficina("Il file non si trova sul disco.", codice="file_non_trovato")

    def quadri():
        with dall_archivio.attento(percorso):
            if principale["genere"] == "immagine":
                yield 0, _di_lavoro(lettura.copia_di_lavoro(percorso))
                return
            from officina.immagini import fotogrammi as estrattore

            for numero, istante in fotogrammi:
                intera = estrattore.uno(percorso, numero, istante)
                if intera is not None:
                    yield numero, _di_lavoro(intera)

    return principale["id"], quadri()


class Passata:

    def __init__(self, archivio, cercatore=None,
                 fermato: Callable[[], bool] | None = None):
        self.archivio = archivio
        self.cercatore = (cercatore if cercatore is not None
                          else apri_il_cercatore(archivio.dove.modelli))
        self.avanzamento = Avanzamento()
        self._fermati = threading.Event()
        self._fuori = fermato
        self._saltati: set[int] = set()

    def ferma(self) -> None:
        self._fermati.set()

    @property
    def fermata(self) -> bool:
        return self._fermati.is_set() or bool(self._fuori and self._fuori())

    def quanti_mancano(self) -> int:
        with self.archivio.lettura() as connessione:
            return elenco.quanti_mancano(connessione)

    def esegui(self, al_passo: Callable[[Avanzamento], None] | None = None,
               quanti: int | None = None) -> Avanzamento:
        self.avanzamento.totale = self.quanti_mancano()
        if quanti:
            self.avanzamento.totale = min(self.avanzamento.totale, quanti)
        try:
            while not self.fermata:
                resta = SCATTI_A_TURNO
                if quanti:
                    resta = min(resta, quanti - self.avanzamento.fatti
                                - self.avanzamento.saltati)
                if resta <= 0:
                    break
                with self.archivio.lettura() as connessione:
                    gruppo = elenco.da_fare(connessione, resta, tranne=self._saltati)
                    parole = {parte["id"]: parte["parola"]
                              for parte in elenco.elenco(connessione)}
                if not gruppo:
                    break
                for scatto_id, parte_id in gruppo:
                    if self.fermata:
                        break
                    self._fai(scatto_id, [p for p in parte_id if p in parole], parole)
                if al_passo:
                    al_passo(self.avanzamento)
        finally:
            self.cercatore.spegni()
        registro.evento("parti.passata", fatti=self.avanzamento.fatti,
                        parti=self.avanzamento.parti, saltati=self.avanzamento.saltati)
        return self.avanzamento

    def _fai(self, scatto_id: int, da_cercare: list[int], parole: dict[int, str]) -> None:
        try:
            file_id, trovate = self._cerca(scatto_id, da_cercare, parole)
        except DaRifare as errore:
            self._salta(scatto_id, errore.codice)
            return
        except ErroreOfficina as errore:
            self._salta(scatto_id, errore.codice or "non_letto")
            self._segna_non_letto(scatto_id, da_cercare)
            return
        except Exception as guasto:          # noqa: BLE001
            if torcia.memoria_finita(guasto):
                self._salta(scatto_id, "memoria_finita")
                torcia.libera()
                return
            registro.errore("parti.non_cercate", scatto=scatto_id,
                            **registro.dove_si_e_rotto(guasto))
            self._salta(scatto_id, "non_letto")
            self._segna_non_letto(scatto_id, da_cercare)
            return
        with self.archivio.scrittura() as connessione:
            for parte_id in da_cercare:
                if elenco.una(connessione, parte_id) is None:
                    continue
                self.avanzamento.parti += elenco.salva(
                    connessione, scatto_id, file_id, parte_id, trovate[parte_id],
                    MODELLO, VERSIONE)
        self.avanzamento.fatti += 1

    def _cerca(self, scatto_id: int, da_cercare: list[int], parole: dict[int, str]):
        file_id, quadri = quadri_di(self.archivio, scatto_id)
        trovate: dict[int, list] = {parte_id: [] for parte_id in da_cercare}
        for numero, immagine in quadri:
            if self.fermata:
                raise DaRifare("Fermato a metà.", codice="fermato")
            esito = self.cercatore.cerca(immagine, [parole[p] for p in da_cercare])
            for parte_id in da_cercare:
                for riquadro, sicurezza in esito.get(parole[parte_id], []):
                    trovate[parte_id].append((numero, riquadro, sicurezza))
        return file_id, trovate

    def _salta(self, scatto_id: int, codice: str) -> None:
        self._saltati.add(scatto_id)
        self.avanzamento.saltati += 1
        self.avanzamento.motivi[codice] = self.avanzamento.motivi.get(codice, 0) + 1

    def _segna_non_letto(self, scatto_id: int, da_cercare: list[int]) -> None:
        from officina.archivio.database import adesso

        with self.archivio.scrittura() as connessione:
            for parte_id in da_cercare:
                if elenco.una(connessione, parte_id) is None:
                    continue
                connessione.execute(
                    "INSERT OR REPLACE INTO parti_guardate (scatto_id, parte_id, modello, "
                    "versione, quante, guardata_il) VALUES (?,?,?,?,?,?)",
                    (scatto_id, parte_id, MODELLO, VERSIONE, NON_LETTO, adesso()))


def prova(archivio, parola: str, quanti: int = 12, cercatore=None) -> list[dict]:
    _nome, parola = elenco.controlla("prova", parola)
    with archivio.lettura() as connessione:
        scatti = [riga["scatto_id"] for riga in tutti(
            connessione,
            "SELECT c.scatto_id FROM corpi c JOIN scatti s ON s.id = c.scatto_id "
            "WHERE s.genere != 'video' GROUP BY c.scatto_id "
            "ORDER BY max(c.area) DESC, c.scatto_id DESC LIMIT ?", quanti)]
    mio = cercatore is None
    cercatore = cercatore if cercatore is not None else apri_il_cercatore(
        archivio.dove.modelli)
    fuori = []
    try:
        for scatto_id in scatti:
            try:
                file_id, quadri = quadri_di(archivio, scatto_id)
                for _numero, immagine in quadri:
                    esito = cercatore.cerca(immagine, [parola])
                    fuori.append({"scatto_id": scatto_id, "file_id": file_id, "trovate": [
                        {"riquadro": list(riquadro), "sicurezza": round(sicurezza, 3)}
                        for riquadro, sicurezza in esito.get(parola, [])]})
                    break
            except ErroreOfficina:
                continue
    finally:
        if mio:
            cercatore.spegni()
    return fuori
