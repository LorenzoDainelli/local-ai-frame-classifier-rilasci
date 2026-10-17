from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from officina import registro
from officina.archivio.database import adesso, tutti
from officina.errori import ErroreOfficina

LATO_DEI_VOLTI = 1280
PREFISSO = "aiuto-"


@dataclass
class Avanzamento:
    totale: int = 0
    fatti: int = 0
    volti: int = 0
    corpi: int = 0
    figure: int = 0
    saltati: int = 0

    def a_parole(self) -> str:
        return (f"foto di aiuto delle persone: {self.fatti} guardate, {self.volti} volti, "
                f"{self.corpi} corpi e vestiti, {self.figure} figure in 3D")


def versione(volti, rilevatore) -> str:
    from officina.corpi.figure import ASPETTO

    return f"{getattr(volti, 'versione', '')}|{getattr(rilevatore, 'versione', '')}|{ASPETTO}"


def da_fare(connessione, quale: str) -> list[dict]:
    return [dict(r) for r in tutti(
        connessione,
        "SELECT a.* FROM aiuti a JOIN persone p ON p.id = a.persona_id "
        "WHERE p.stato != 'cestino' AND (a.guardato IS NULL OR a.guardato != ?) ORDER BY a.id", quale)]


def quanti_di_persona(connessione, persona_id: int) -> dict:
    righe = tutti(connessione,
                  "SELECT count(*) AS q, sum(guardato IS NOT NULL) AS g FROM aiuti WHERE persona_id = ?",
                  persona_id)
    corpi = tutti(connessione,
                  "SELECT count(DISTINCT d.aiuto_id) AS q FROM aspetti_di_aiuto d JOIN aiuti a ON a.id = d.aiuto_id "
                  "WHERE a.persona_id = ?", persona_id)
    return {"tutte": righe[0]["q"] or 0, "guardate": righe[0]["g"] or 0, "con_il_corpo": corpi[0]["q"] or 0}


def _dentro(riquadro, punto) -> bool:
    x, y, larga, alta = riquadro
    return x <= punto[0] <= x + larga and y <= punto[1] <= y + alta


def scegli_il_corpo(corpi: list, volto=None):
    if not corpi:
        return None
    if volto is not None:
        x, y, larga, alta = volto.riquadro
        centro = (x + larga / 2, y + alta / 2)
        suoi = [c for c in corpi if _dentro(c.riquadro, centro)]
        if suoi:
            return max(suoi, key=lambda c: c.area)
    return max(corpi, key=lambda c: c.area)


def dimentica(connessione, aiuto_id: int) -> None:
    connessione.execute("DELETE FROM volti_riferimento WHERE da_file = ?", (f"{PREFISSO}{aiuto_id}",))
    connessione.execute("DELETE FROM aspetti_di_aiuto WHERE aiuto_id = ?", (aiuto_id,))


class Passata:

    def __init__(self, archivio, volti=None, rilevatore=None, figure=None,
                 fermato: Callable[[], bool] | None = None):
        self.archivio = archivio
        self._volti = volti
        self._rilevatore = rilevatore
        self._figure = figure
        self._fuori = fermato
        self._fermati = threading.Event()
        self.avanzamento = Avanzamento()

    def ferma(self) -> None:
        self._fermati.set()

    @property
    def fermata(self) -> bool:
        return self._fermati.is_set() or bool(self._fuori and self._fuori())

    def _apri(self) -> None:
        if self._volti is None:
            from officina import volti as volti_mod

            self._volti = volti_mod.apri(self.archivio)
        if self._rilevatore is None:
            from officina import corpi as corpi_pacchetto

            self._rilevatore = corpi_pacchetto.apri(self.archivio)
        if self._figure is None:
            from officina.corpi.figure import Figure, cosa_manca

            if not cosa_manca(self.archivio.dove.modelli):
                self._figure = Figure(self.archivio.dove.modelli)

    def quanti_mancano(self) -> int:
        with self.archivio.lettura() as connessione:
            return len(tutti(connessione,
                             "SELECT a.id FROM aiuti a JOIN persone p ON p.id = a.persona_id "
                             "WHERE p.stato != 'cestino' AND a.guardato IS NULL"))

    def esegui(self, al_passo: Callable[[Avanzamento], None] | None = None) -> Avanzamento:
        with self.archivio.lettura() as connessione:
            if not tutti(connessione, "SELECT 1 FROM aiuti WHERE persona_id IS NOT NULL LIMIT 1"):
                return self.avanzamento
        self._apri()
        quale = versione(self._volti, self._rilevatore)
        with self.archivio.lettura() as connessione:
            lavoro = da_fare(connessione, quale)
        self.avanzamento.totale = len(lavoro)
        if not lavoro:
            return self.avanzamento
        try:
            accendi = getattr(self._rilevatore, "accendi", None)
            if accendi is not None:
                accendi()
            for voce in lavoro:
                if self.fermata:
                    break
                try:
                    self._guarda(voce, quale)
                except ErroreOfficina:
                    self.avanzamento.saltati += 1
                    self._segna(voce["id"], quale)
                except Exception as guasto:          # noqa: BLE001
                    registro.avviso("aiuti_persona.non_guardata", **registro.dove_si_e_rotto(guasto))
                    self.avanzamento.saltati += 1
                    self._segna(voce["id"], quale)
                if al_passo:
                    al_passo(self.avanzamento)
        finally:
            for pezzo in (self._volti, self._rilevatore, self._figure):
                spegni = getattr(pezzo, "spegni", None)
                if spegni is not None:
                    spegni()
        registro.evento("aiuti_persona.passata", fatti=self.avanzamento.fatti, corpi=self.avanzamento.corpi)
        return self.avanzamento

    def _segna(self, aiuto_id: int, quale: str) -> None:
        with self.archivio.scrittura() as connessione:
            connessione.execute("UPDATE aiuti SET guardato = ? WHERE id = ?", (quale, aiuto_id))

    def _guarda(self, voce: dict, quale: str) -> None:
        from officina.immagini import lettura
        from officina.modello import aiuti

        percorso = aiuti.percorso(self.archivio, voce)
        if not percorso.exists():
            raise ErroreOfficina("La foto di aiuto non c'è più sul disco.")
        intera = lettura.copia_di_lavoro(percorso).convert("RGB")
        facce = [f for f in self._volti.guarda(lettura.copia_di_lavoro(percorso, LATO_DEI_VOLTI)) if f.impronta is not None]
        volto = facce[0] if len(facce) == 1 else None
        corpo = scegli_il_corpo(self._trova_i_corpi(intera), volto)
        figura = self._figura(percorso, intera, corpo) if corpo is not None else None
        self._salva(voce, quale, volto, corpo, figura)
        self.avanzamento.fatti += 1

    def _trova_i_corpi(self, intera) -> list:
        from officina.corpi.motore import _di_lavoro

        lavoro = _di_lavoro(intera)
        trova = getattr(self._rilevatore, "trova_e_prepara", None)
        if trova is None:
            return list(self._rilevatore.guarda(lavoro))
        corpi, preparati = trova(lavoro, intera)
        completa = getattr(self._rilevatore, "completa", None)
        if completa is not None and corpi:
            guasti = completa([(corpi, preparati)], fermato=lambda: self.fermata)
            if guasti and guasti[0] is not None:
                raise guasti[0] if isinstance(guasti[0], ErroreOfficina) else ErroreOfficina(
                    "Il corpo di questa foto di aiuto non si è lasciato guardare.")
        return list(corpi)

    def _figura(self, percorso: Path, intera, corpo):
        import numpy

        from officina.corpi import figure as figure_mod

        if self._figure is None:
            return None
        ridotta = figure_mod._ridotta(intera)
        larga, alta = ridotta.size
        campo = figure_mod.campo_dall_exif(percorso, *intera.size) or figure_mod.campo_di_base(larga, alta)
        lente = figure_mod.Lente(figure_mod.EXIF, campo)
        r = list(corpo.riquadro)
        riquadri = numpy.array([[r[0] * larga, r[1] * alta, (r[0] + r[2]) * larga, (r[1] + r[3]) * alta]],
                               dtype=numpy.float64)
        intere = numpy.stack([figure_mod.maschera_intera(corpo.maschera or None, r, larga, alta)])
        accendi = getattr(self._figure, "accendi_il_corpo", None)
        if accendi is not None:
            accendi()
        fatte, mani = self._figure.ricostruisci(numpy.asarray(ridotta), riquadri, intere, lente.fuoco(alta))
        if not fatte:
            return None
        return figure_mod.figura_a_numeri(fatte[0], larga, alta), mani[0]

    def _salva(self, voce: dict, quale: str, volto, corpo, figura) -> None:
        import numpy

        from officina.corpi import VESTITI
        from officina.corpi.figure import ASPETTO
        from officina.descrittori import vettori
        from officina.modello.corpi import vettore_a_byte
        from officina.volti import rilevatore as rilevatore_volti

        with self.archivio.scrittura() as connessione:
            esiste = connessione.execute("SELECT 1 FROM aiuti WHERE id = ?", (voce["id"],)).fetchone()
            if esiste is None:
                return
            dimentica(connessione, voce["id"])
            if volto is not None:
                connessione.execute(
                    "INSERT OR IGNORE INTO volti_riferimento (persona_id, da_file, riquadro, area, nitidezza, "
                    "sicurezza, impronta, modello, versione, letto_il) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (voce["persona_id"], f"{PREFISSO}{voce['id']}", json.dumps(list(volto.riquadro)), volto.area,
                     volto.nitidezza, volto.sicurezza, vettori.a_byte(volto.impronta), rilevatore_volti.NOME,
                     getattr(self._volti, "versione", ""), adesso()))
                self.avanzamento.volti += 1
            if corpo is not None:
                for nome, (immersione, visibili) in sorted((getattr(corpo, "aspetto", None) or {}).items()):
                    immersione = numpy.asarray(immersione, dtype="<f4")
                    parti = int(immersione.shape[0]) if immersione.ndim > 1 else 1
                    connessione.execute(
                        "INSERT OR REPLACE INTO aspetti_di_aiuto (aiuto_id, modello, parti, vettore, visibili) "
                        "VALUES (?,?,?,?,?)",
                        (voce["id"], nome, parti, vettore_a_byte(immersione),
                         numpy.asarray(visibili).astype(numpy.uint8).reshape(-1).tobytes()))
                vestiti = getattr(corpo, "vestiti", None)
                if vestiti is not None and len(vestiti):
                    connessione.execute(
                        "INSERT OR REPLACE INTO aspetti_di_aiuto (aiuto_id, modello, parti, vettore, visibili) "
                        "VALUES (?,?,1,?,NULL)", (voce["id"], VESTITI, vettore_a_byte(vestiti)))
                self.avanzamento.corpi += 1
            if figura is not None:
                numeri, mani = figura
                connessione.execute(
                    "INSERT OR REPLACE INTO aspetti_di_aiuto (aiuto_id, modello, parti, vettore, visibili) "
                    "VALUES (?,?,1,?,?)",
                    (voce["id"], ASPETTO, vettore_a_byte(numeri), bytes(int(bool(m)) for m in mani)))
                self.avanzamento.figure += 1
            connessione.execute("UPDATE aiuti SET guardato = ? WHERE id = ?", (quale, voce["id"]))
