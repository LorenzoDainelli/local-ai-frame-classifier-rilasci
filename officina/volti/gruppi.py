from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from officina.archivio.database import tutti
from officina.descrittori import vettori
from officina.insiemi import InsiemiUniti
from officina.modello import persone

INSIEME = 0.62

FORSE = 0.48

SICURO = 0.70

MINIMO_PER_UN_GRUPPO = 2


@dataclass
class Raccolto:
    gruppi_nuovi: int = 0
    volti_raggruppati: int = 0
    assegnati_in_silenzio: int = 0
    volti_soli: int = 0
    forse: int = 0

    def a_parole(self) -> str:
        pezzi = []
        if self.assegnati_in_silenzio:
            pezzi.append(f"{self.assegnati_in_silenzio} volti assegnati a "
                         "persone che conosci già")
        if self.gruppi_nuovi:
            pezzi.append(f"{self.gruppi_nuovi} gruppi nuovi da guardare")
        if self.forse:
            pezzi.append(f"{self.forse} forse-doppioni messi da parte")
        if self.volti_soli:
            pezzi.append(f"{self.volti_soli} volti che non somigliano a nessuno")
        return " · ".join(pezzi) if pezzi else "niente di nuovo"


def raggruppa(connessione: sqlite3.Connection, insieme: float = INSIEME,
              sicuro: float = SICURO) -> Raccolto:
    fuori = Raccolto()

    liberi = [dict(riga) for riga in tutti(
        connessione,
        "SELECT id, impronta FROM volti "
        "WHERE persona_id IS NULL AND impronta IS NOT NULL "
        "AND id NOT IN (SELECT riga_id FROM persone_tolte WHERE dove = 'volto') ORDER BY id")]
    if not liberi:
        return fuori

    liberi = _attacca_ai_conosciuti(connessione, liberi, sicuro, fuori)
    if not liberi:
        _cerca_i_forse(connessione, fuori)
        return fuori

    tabella = vettori.matrice([v["impronta"] for v in liberi])
    for insieme_di_indici in _amici_degli_amici(tabella, insieme):
        volti = [liberi[i]["id"] for i in insieme_di_indici]
        if len(volti) < MINIMO_PER_UN_GRUPPO:
            fuori.volti_soli += len(volti)
            continue
        persona = persone.crea(connessione)
        segnaposti = ",".join("?" * len(volti))
        connessione.execute(
            f"UPDATE volti SET persona_id = ? WHERE id IN ({segnaposti})",
            (persona, *volti))
        fuori.gruppi_nuovi += 1
        fuori.volti_raggruppati += len(volti)

    _cerca_i_forse(connessione, fuori)
    return fuori


def _attacca_ai_conosciuti(connessione: sqlite3.Connection, liberi: list[dict],
                           sicuro: float, fuori: Raccolto) -> list[dict]:
    conosciuti = Conosciuti(connessione, sicuro)
    if not conosciuti:
        return liberi
    restano = []
    for volto in liberi:
        persona = conosciuti.chi_e(volto["impronta"])
        if persona is not None:
            connessione.execute(
                "UPDATE volti SET persona_id = ? WHERE id = ?", (persona, volto["id"]))
            fuori.assegnati_in_silenzio += 1
        else:
            restano.append(volto)
    return restano


MARGINE = 0.08


class Conosciuti:
    def __init__(self, connessione: sqlite3.Connection, sicuro: float = SICURO,
                 margine: float = MARGINE):
        self.sicuro = sicuro
        self.margine = margine
        nominate = {riga["id"] for riga in tutti(
            connessione,
            "SELECT id FROM persone WHERE stato = 'attiva' AND nome IS NOT NULL")}
        confermati: dict[int, list[bytes]] = {}
        for riga in tutti(connessione, _VOLTI_CONFERMATI):
            if riga["persona_id"] in nominate:
                confermati.setdefault(riga["persona_id"], []).append(riga["impronta"])
        insegnati: dict[int, list[bytes]] = {}
        for riga in tutti(connessione,
                          "SELECT persona_id, impronta FROM volti_riferimento ORDER BY id"):
            if riga["persona_id"] in nominate:
                insegnati.setdefault(riga["persona_id"], []).append(riga["impronta"])
        centri, numeri = [], []
        for gruppo in (confermati, insegnati):
            for persona, impronte in sorted(gruppo.items()):
                centri.append(_centro(impronte))
                numeri.append(persona)
        self.persone = sorted(set(numeri))
        if not centri:
            self._centri = None
            return
        numpy = vettori.numpy_o_spiega()
        self._centri = numpy.asarray(centri, dtype=numpy.float32)
        dove = {persona: posto for posto, persona in enumerate(self.persone)}
        self._di_chi = numpy.asarray([dove[persona] for persona in numeri])

    def __bool__(self) -> bool:
        return self._centri is not None

    def chi_e(self, impronta: bytes) -> int | None:
        if self._centri is None:
            return None
        numpy = vettori.numpy_o_spiega()
        mio = numpy.frombuffer(impronta, dtype="<f4")
        somiglianze = self._centri @ mio
        per_persona = numpy.full(len(self.persone), -1.0, dtype=numpy.float32)
        numpy.maximum.at(per_persona, self._di_chi, somiglianze)
        ordine = numpy.argsort(-per_persona)
        primo = float(per_persona[ordine[0]])
        secondo = float(per_persona[ordine[1]]) if len(ordine) > 1 else -1.0
        if primo >= self.sicuro and primo - secondo >= self.margine:
            return self.persone[int(ordine[0])]
        return None


_VOLTI_CONFERMATI = (
    "SELECT persona_id, impronta FROM volti "
    "WHERE deciso_da = 'utente' AND persona_id IS NOT NULL AND impronta IS NOT NULL "
    "UNION ALL "
    "SELECT v.persona_id, v.impronta FROM persone_negli_scatti n CROSS "
    "JOIN volti v ON v.scatto_id = n.scatto_id AND v.persona_id = n.persona_id "
    "WHERE v.deciso_da = 'sistema' AND v.impronta IS NOT NULL")


def _centro(impronte: list[bytes]):
    numpy = vettori.numpy_o_spiega()
    tabella = vettori.matrice(impronte)
    media = tabella.mean(axis=0)
    lunghezza = float(numpy.linalg.norm(media)) or 1.0
    return media / lunghezza


QUANTI_ALLA_VOLTA = 256


def _amici_degli_amici(tabella, soglia: float) -> list[list[int]]:
    numpy = vettori.numpy_o_spiega()
    quanti = tabella.shape[0]
    insiemi = InsiemiUniti()

    for principio in range(0, quanti, QUANTI_ALLA_VOLTA):
        fetta = tabella[principio:principio + QUANTI_ALLA_VOLTA]
        vicini = (fetta @ tabella.T) >= soglia
        mie, loro = numpy.nonzero(vicini)
        mie = mie + principio
        sopra = loro > mie
        for uno, altro in zip(mie[sopra].tolist(), loro[sopra].tolist(), strict=True):
            insiemi.unisci(uno, altro)
        for quale in range(fetta.shape[0]):
            insiemi.aggiungi(principio + quale)

    return insiemi.gruppi(anche_i_soli=True)


def _cerca_i_forse(connessione: sqlite3.Connection, fuori: Raccolto,
                   soglia: float = FORSE, insieme: float = INSIEME) -> None:
    voci = [voce for voce in persone.elenco(connessione) if voce["volti"]]
    if len(voci) < 2:
        return

    centri, numeri = [], []
    for voce in voci:
        impronte = [riga["impronta"] for riga in tutti(
            connessione,
            "SELECT impronta FROM volti WHERE persona_id = ? "
            "AND impronta IS NOT NULL", voce["id"])]
        if impronte:
            centri.append(_centro(impronte))
            numeri.append(voce["id"])
    if len(centri) < 2:
        return

    numpy = vettori.numpy_o_spiega()
    tabella = numpy.asarray(centri, dtype=numpy.float32)
    somiglianze = tabella @ tabella.T
    for una in range(len(numeri)):
        for altra in range(una + 1, len(numeri)):
            quanto = float(somiglianze[una][altra])
            if soglia <= quanto < insieme:
                persone.segna_forse(connessione, numeri[una], numeri[altra],
                                    quanto)
                fuori.forse += 1
