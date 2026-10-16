from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from officina.importazione import gruppi
from officina import registro
from officina.archivio.accesso import Archivio
from officina.archivio.database import adesso, tutti, uno
from officina.descrittori import torcia, vettori
from officina.errori import ErroreOfficina, FileNonLeggibile
from officina.immagini import lettura
from officina.modello import file_media, segnalazioni
from officina.volti import rilevatore as rilevatore_mod

LATO_DI_LAVORO = 1280


@dataclass
class Avanzamento:
    fatti: int = 0
    saltati: int = 0
    volti: int = 0
    scatti_con_volti: int = 0
    totale: int = 0
    motivi: dict[str, int] = field(default_factory=dict)

    def a_parole(self) -> str:
        return (f"fatti {self.fatti} · saltati {self.saltati} · "
                f"volti {self.volti} · scatti con qualcuno {self.scatti_con_volti}")


class Passata:

    def __init__(self, archivio: Archivio, rilevatore=None,
                 intensita: int | None = None):
        self.archivio = archivio
        from officina import volti as volti_mod

        self.rilevatore = rilevatore or volti_mod.apri(
            archivio, sicurezza_minima=_quanta_prudenza(archivio))
        self.intensita = (intensita if intensita is not None
                          else int(archivio.impostazione("intensita_scheda") or 100))
        self.avanzamento = Avanzamento()
        self._fermati = threading.Event()

    def ferma(self) -> None:
        self._fermati.set()

    @property
    def fermata(self) -> bool:
        return self._fermati.is_set()


    def quanti_mancano(self) -> int:
        with self.archivio.lettura() as connessione:
            riga = uno(connessione, self._domanda_da_fare("count(*) AS q", gruppi.clausola(connessione, "intelligenza")),
                       self._modello(), self._versione())
        return riga["q"] if riga else 0

    def _domanda_da_fare(self, cosa: str, piu: str = "") -> str:
        return _domanda_da_fare(cosa, piu)

    def _modello(self) -> str:
        return rilevatore_mod.NOME

    def _versione(self) -> str:
        return self.rilevatore.versione


    def esegui(self, al_passo: Callable[[Avanzamento], None] | None = None,
               quanti: int | None = None) -> Avanzamento:
        freno = torcia.Freno(self.intensita, fermato=lambda: self.fermata)
        with self.archivio.lettura() as connessione:
            da_fare = [riga["id"] for riga in tutti(
                connessione, self._domanda_da_fare("s.id", gruppi.clausola(connessione, "intelligenza")),
                self._modello(), self._versione())]
        if quanti:
            da_fare = da_fare[:quanti]
        self.avanzamento.totale = len(da_fare)

        import time

        memoria = torcia.ContoDellaMemoria()
        try:
            for scatto_id in da_fare:
                if self.fermata:
                    break
                partito = time.monotonic()
                try:
                    self._guarda_uno(scatto_id)
                    self.avanzamento.fatti += 1
                    for pesante in memoria.riuscito():
                        self._segnala(pesante, ErroreOfficina(torcia.TROPPO_PER_LA_MEMORIA))
                except ErroreOfficina as errore:
                    self._segnala(scatto_id, errore)
                except Exception as guasto:          # noqa: BLE001
                    if torcia.memoria_finita(guasto):
                        memoria.finita(scatto_id, guasto)
                    else:
                        self._segnala(scatto_id, ErroreOfficina(
                            "Questo scatto non si è lasciato guardare."))
                if al_passo:
                    al_passo(self.avanzamento)
                freno.riposa(time.monotonic() - partito)
        finally:
            self.rilevatore.spegni()
        registro.evento("volti.passata", fatti=self.avanzamento.fatti,
                        volti=self.avanzamento.volti)
        return self.avanzamento

    def _guarda_uno(self, scatto_id: int) -> None:
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

        trovati: list[tuple[int, object]] = []
        if principale["genere"] == "immagine":
            immagine = lettura.copia_di_lavoro(Path(percorso), LATO_DI_LAVORO)
            trovati = [(0, faccia) for faccia in self.rilevatore.guarda(immagine)]
        else:
            from officina.immagini import fotogrammi as estrattore

            for numero, istante in (fotogrammi or [(0, None)]):
                quadro = estrattore.uno(Path(percorso), numero, istante, LATO_DI_LAVORO)
                if quadro is None:
                    continue
                trovati.extend((numero, faccia)
                               for faccia in self.rilevatore.guarda(quadro))

        with self.archivio.scrittura() as connessione:
            connessione.execute(
                "DELETE FROM volti WHERE scatto_id = ? AND modello = ? "
                "AND versione = ? AND deciso_da = 'sistema'",
                (scatto_id, self._modello(), self._versione()))
            for numero, faccia in trovati:
                connessione.execute(
                    """
                    INSERT INTO volti (scatto_id, file_id, fotogramma, riquadro,
                                       area, nitidezza, sicurezza, impronta,
                                       modello, versione, trovato_il)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (scatto_id, principale["id"], numero,
                     json.dumps(list(faccia.riquadro)), faccia.area,
                     faccia.nitidezza, faccia.sicurezza,
                     vettori.a_byte(faccia.impronta) if faccia.impronta else None,
                     self._modello(), self._versione(), adesso()),
                )
            connessione.execute(
                "INSERT OR REPLACE INTO volti_guardati "
                "(scatto_id, modello, versione, quanti, guardato_il) VALUES (?,?,?,?,?)",
                (scatto_id, self._modello(), self._versione(), len(trovati), adesso()))
            from officina.modello import corpi as corpi_mod

            corpi_mod.ricollega(connessione, scatto_id)
            if trovati:
                self.avanzamento.scatti_con_volti += 1
            self.avanzamento.volti += len(trovati)

    def _segnala(self, scatto_id: int, errore: ErroreOfficina) -> None:
        self.avanzamento.saltati += 1
        codice = errore.codice or "non_letto"
        self.avanzamento.motivi[codice] = self.avanzamento.motivi.get(codice, 0) + 1
        quale = (segnalazioni.NON_SI_APRE
                 if isinstance(errore, FileNonLeggibile)
                 else segnalazioni.VOLTI_NON_LETTI)
        dettaglio = (codice if quale == segnalazioni.NON_SI_APRE
                     else errore.messaggio)
        with self.archivio.scrittura() as connessione:
            segnalazioni.segna(connessione, quale, scatto_id,
                               dettaglio=dettaglio,
                               file_id=getattr(errore, "file_id", None))


def _quanta_prudenza(archivio: Archivio) -> float:
    quale = str(archivio.impostazione("volti_prudenza") or "equilibrato")
    return {"prudente": 0.75, "equilibrato": 0.60, "generoso": 0.45}.get(
        quale, rilevatore_mod.SICUREZZA_MINIMA)


def _domanda_da_fare(cosa: str, piu: str = "") -> str:
    return f"""
        SELECT {cosa} FROM scatti s
        WHERE s.fuori_archivio = 0{piu}
          AND NOT EXISTS (
              SELECT 1 FROM volti_guardati g
              WHERE g.scatto_id = s.id AND g.modello = ? AND g.versione = ?)
          {segnalazioni.clausola(segnalazioni.VOLTI_NON_LETTI)}
          {segnalazioni.clausola(segnalazioni.NON_SI_APRE)}
        ORDER BY s.id
    """


def quanti_mancano_senza_aprire(connessione) -> int:
    from officina.volti.insight import VERSIONE

    riga = uno(connessione, _domanda_da_fare("count(*) AS q", gruppi.clausola(connessione, "intelligenza")),
               rilevatore_mod.NOME, VERSIONE)
    return riga["q"] if riga else 0
