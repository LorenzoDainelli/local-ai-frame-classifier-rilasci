from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from officina.apprendimento import gruppi as divisione
from officina.apprendimento.classificatore import FORZA, addestra
from officina.descrittori import vettori

MINIMO_SI = 5
MINIMO_NO = 5

TROPPO_POCHI = "troppo pochi esempi per dirlo"


@dataclass
class Voto:

    esempi_si: int
    esempi_no: int
    gruppi_si: int
    gruppi_no: int
    abbastanza: bool
    azzeccati_si: int = 0
    azzeccati_no: int = 0
    proposti_a_torto: int = 0
    mancati: int = 0
    forza: float = FORZA
    detti_si_a_torto: list[int] = field(default_factory=list)
    non_visti: list[int] = field(default_factory=list)

    @property
    def azzecca(self) -> float | None:
        if not self.abbastanza or not self.esempi_si or not self.esempi_no:
            return None
        return (self.azzeccati_si / self.esempi_si
                + self.azzeccati_no / self.esempi_no) / 2

    @property
    def precisione(self) -> float | None:
        detti_si = self.azzeccati_si + self.proposti_a_torto
        if not self.abbastanza or not detti_si:
            return None
        return self.azzeccati_si / detti_si

    @property
    def richiamo(self) -> float | None:
        if not self.abbastanza or not self.esempi_si:
            return None
        return self.azzeccati_si / self.esempi_si

    def a_parole(self) -> str:
        if not self.abbastanza:
            return (f"{TROPPO_POCHI} "
                    f"({self.gruppi_si} sì, {self.gruppi_no} no)")
        return (f"{self.azzecca * 100:.0f}% su {self.esempi_si + self.esempi_no} "
                f"esempi ({self.gruppi_si + self.gruppi_no} gruppi)")


def valuta(tabella, risposte: Sequence[int], gruppi: Sequence[int],
           forza: float = FORZA, soglia: float = 0.5, fette: int = 5) -> Voto:
    quanti_si = sum(1 for r in risposte if r)
    quanti_no = len(risposte) - quanti_si
    gruppi_si = len({g for g, r in zip(gruppi, risposte, strict=True) if r})
    gruppi_no = len({g for g, r in zip(gruppi, risposte, strict=True) if not r})

    voto = Voto(esempi_si=quanti_si, esempi_no=quanti_no,
                gruppi_si=gruppi_si, gruppi_no=gruppi_no,
                abbastanza=gruppi_si >= MINIMO_SI and gruppi_no >= MINIMO_NO,
                forza=forza)
    if not voto.abbastanza:
        return voto

    numpy = vettori.numpy_o_spiega()
    risposte = numpy.asarray(risposte, dtype=numpy.float64)

    for fetta in divisione.a_fette(gruppi, fette):
        da_verificare = numpy.zeros(len(risposte), dtype=bool)
        da_verificare[fetta] = True
        per_imparare = ~da_verificare
        if len(set(risposte[per_imparare].tolist())) < 2:
            continue

        modello = addestra(tabella[per_imparare], risposte[per_imparare], forza=forza)
        detti = modello.punteggi(tabella[da_verificare]) >= soglia
        veri = risposte[da_verificare] > 0.5

        voto.azzeccati_si += int((detti & veri).sum())
        voto.azzeccati_no += int((~detti & ~veri).sum())
        voto.proposti_a_torto += int((detti & ~veri).sum())
        voto.mancati += int((~detti & veri).sum())

        dove = numpy.nonzero(da_verificare)[0]
        voto.detti_si_a_torto.extend(int(x) for x in dove[detti & ~veri])
        voto.non_visti.extend(int(x) for x in dove[~detti & veri])

    voto.esempi_si = voto.azzeccati_si + voto.mancati
    voto.esempi_no = voto.azzeccati_no + voto.proposti_a_torto
    if not voto.esempi_si or not voto.esempi_no:
        voto.abbastanza = False
    return voto


def valuta_impronte(impronte: Sequence[bytes], risposte: Sequence[int],
                    gruppi: Sequence[int], forza: float = FORZA,
                    soglia: float = 0.5, fette: int = 5) -> Voto:
    return valuta(vettori.matrice(list(impronte)), risposte, gruppi,
                  forza=forza, soglia=soglia, fette=fette)


@dataclass
class Confronto:

    etichetta: str
    voti: dict[str, Voto] = field(default_factory=dict)

    @property
    def media(self) -> float | None:
        numeri = [voto.azzecca for voto in self.voti.values()
                  if voto.azzecca is not None]
        return sum(numeri) / len(numeri) if numeri else None

    @property
    def nodi_giudicabili(self) -> int:
        return sum(1 for voto in self.voti.values() if voto.abbastanza)
