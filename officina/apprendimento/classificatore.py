from __future__ import annotations

from dataclasses import dataclass

from officina.descrittori import vettori

FORZA = 1.0

PASSI = 300
ANDATURA = 0.35
INERZIA = 0.9


@dataclass
class Modello:

    pesi: object
    scarto: float
    esempi_si: int
    esempi_no: int
    forza: float = FORZA

    @property
    def esempi(self) -> int:
        return self.esempi_si + self.esempi_no

    def punteggi(self, tabella):
        numpy = vettori.numpy_o_spiega()
        return 1.0 / (1.0 + numpy.exp(-(tabella @ self.pesi + self.scarto)))

    def punteggio_di(self, impronta: bytes) -> float:
        numpy = vettori.numpy_o_spiega()
        riga = numpy.frombuffer(impronta, dtype="<f4")
        return float(self.punteggi(riga.reshape(1, -1))[0])


def addestra(tabella, risposte, forza: float = FORZA, passi: int = PASSI) -> Modello:
    numpy = vettori.numpy_o_spiega()
    tabella = numpy.asarray(tabella, dtype=numpy.float64)
    risposte = numpy.asarray(risposte, dtype=numpy.float64)
    quanti, larghezza = tabella.shape

    quanti_si = int(risposte.sum())
    quanti_no = quanti - quanti_si

    peso = numpy.where(risposte > 0.5,
                       quanti / (2.0 * max(quanti_si, 1)),
                       quanti / (2.0 * max(quanti_no, 1)))
    peso = peso / peso.sum()

    pesi = numpy.zeros(larghezza)
    scarto = 0.0
    spinta_pesi = numpy.zeros(larghezza)
    spinta_scarto = 0.0

    for _ in range(passi):
        previsione = 1.0 / (1.0 + numpy.exp(-(tabella @ pesi + scarto)))
        errore = (previsione - risposte) * peso
        pendenza_pesi = tabella.T @ errore + forza * pesi / max(quanti, 1)
        pendenza_scarto = float(errore.sum())

        spinta_pesi = INERZIA * spinta_pesi - ANDATURA * pendenza_pesi
        spinta_scarto = INERZIA * spinta_scarto - ANDATURA * pendenza_scarto
        pesi = pesi + spinta_pesi
        scarto = scarto + spinta_scarto

    return Modello(pesi=pesi, scarto=float(scarto), esempi_si=quanti_si,
                   esempi_no=quanti_no, forza=forza)
