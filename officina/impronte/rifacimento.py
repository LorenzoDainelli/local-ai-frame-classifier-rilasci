from __future__ import annotations

import threading
from pathlib import Path

from officina import registro

OGNI = 60.0


def da_rifare(archivio) -> str | None:
    from officina import descrittori
    from officina.modello import impronte as magazzino

    cartella = Path(archivio.dove.modelli)
    for vecchio, nuovo in descrittori.SUPERATI.items():
        if descrittori.superato_da(vecchio, cartella) != nuovo:
            continue
        versione = descrittori.scheda(nuovo).versione
        with archivio.lettura() as connessione:
            vecchie = connessione.execute(
                "SELECT 1 FROM impronte WHERE descrittore = ? LIMIT 1",
                (vecchio,)).fetchone()
            if vecchie and magazzino.quanti_da_fare(connessione, nuovo, versione):
                return nuovo
    return None


def _occupata() -> bool:
    from officina.web import sosta

    return bool(sosta.per_la_copia.attiva or sosta.per_la_copia.in_attesa()
                or sosta.per_la_copia.si_fermano())


def _parti(archivio, nome: str) -> bool:
    from officina.web.strade import misura

    return misura.parti_le_impronte_per(archivio, nome)


def _l_archivio():
    from officina.archivio import accesso

    return accesso.vero()


class Rifacimento:

    def __init__(self, *, archivio=_l_archivio, occupata=_occupata, parti=_parti,
                 ogni: float = OGNI):
        self._archivio = archivio
        self._occupata = occupata
        self._parti = parti
        self._ogni = ogni
        self._basta = threading.Event()
        self._fermato = threading.Event()
        self._filo: threading.Thread | None = None

    def fermato_da_te(self) -> None:
        self._fermato.set()

    def un_giro(self) -> str | None:
        if self._fermato.is_set():
            return None
        try:
            archivio = self._archivio()
        except Exception:
            return None
        if archivio is None or getattr(archivio, "di_prova", False):
            return None
        nome = da_rifare(archivio)
        if nome is None or self._occupata():
            return None
        if not self._parti(archivio, nome):
            return None
        registro.evento("impronte.rifacimento_partito", nome=registro.Parola(nome))
        return nome

    def guarda(self) -> None:
        if self._filo is not None and self._filo.is_alive():
            return
        self._basta.clear()
        self._filo = threading.Thread(target=self._gira, name="rifacimento_impronte",
                                      daemon=True)
        self._filo.start()

    def smetti(self) -> None:
        self._basta.set()

    def _gira(self) -> None:
        while not self._basta.wait(self._ogni):
            try:
                self.un_giro()
            except Exception as guasto:
                registro.errore("impronte.rifacimento_guasto",
                                **registro.dove_si_e_rotto(guasto))


del_programma = Rifacimento()

__all__ = ["OGNI", "Rifacimento", "da_rifare", "del_programma"]
