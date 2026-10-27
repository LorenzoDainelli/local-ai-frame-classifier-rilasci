from __future__ import annotations

import functools
import itertools
import queue
import threading
import time

from officina import registro
from officina.errori import ErroreOfficina
from officina.sicuro import dall_archivio, prendi
from officina.sicuro.dall_archivio import DallArchivio, Ricerca


ATTESA = 60.0
CHIUSO = "L'Archivio sicuro è chiuso: aprilo e riprova."
NON_ESCE = "La chiave di una foto dell'Archivio sicuro non esce da questo programma."


def _chiuso() -> ErroreOfficina:
    return ErroreOfficina(CHIUSO, codice="archivio_chiuso")


class _ChiaveDiUnaFoto:

    __slots__ = ("_chiavi",)

    def __init__(self, chiavi: dict):
        self._chiavi = {}
        self.aggiungi(chiavi)

    def aggiungi(self, chiavi: dict) -> None:
        for numero, chiave in chiavi.items():
            self._chiavi[str(numero)] = bytes(chiave)

    def per_contenuto(self, numero: bytes) -> bytes:
        chiave = self._chiavi.get(bytes(numero).hex())
        if chiave is None:
            raise _chiuso()
        return chiave

    def __repr__(self) -> str:
        return "ChiaveDiUnaFoto(…)"

    def __reduce__(self):
        raise TypeError(NON_ESCE)


class Sportello:

    def __init__(self, nome: str, risposte, giro):
        self._nome = nome
        self._risposte = risposte
        self._giro = giro
        self._serratura = threading.Lock()
        self._legata = None
        self._avviso = None
        self._date: dict[str, bool] = {}

    def ricevi(self, domanda) -> None:
        numero = None
        try:
            numero, cosa, *argomenti = domanda
            risposta = (True, self._fai(cosa, argomenti))
        except ErroreOfficina as errore:
            risposta = (False, errore.messaggio, errore.codice)
        except Exception as guasto:
            registro.errore("sicuro.sportello_rotto", **registro.dove_si_e_rotto(guasto))
            risposta = (False, CHIUSO, "archivio_chiuso")
        if numero is None:
            return
        try:
            self._risposte.put((numero, risposta))
        except (OSError, ValueError) as guasto:
            registro.avviso("sicuro.risposta_persa", **registro.dove_si_e_rotto(guasto))

    def _fai(self, cosa: str, argomenti: list):
        if cosa == "cerca":
            return self._cerca(*argomenti)
        if cosa == "apri":
            return self._apri(*argomenti)
        if cosa == "altre":
            return self._altre(*argomenti)
        if cosa == "segnala":
            return self._segnala(*argomenti)
        if cosa == "letta":
            return self._letta(*argomenti)
        raise ValueError(f"domanda sconosciuta: {cosa!r}")

    def _servizio(self):
        from officina.archivio import accesso
        from officina.programma import archivio_sicuro

        try:
            nome = accesso.aperto().dove.nome
        except ErroreOfficina:
            nome = None
        if nome != self._nome:
            return dall_archivio.SENZA_ARCHIVIO, None
        return archivio_sicuro.per_le_foto()

    def _cerca(self, impronta: str, dimensione: int | None, percorsi: list, nome: str,
               intero: bool):
        perche, servizio = self._servizio()
        if servizio is None:
            return perche, None
        apertura = servizio.apertura
        if apertura is None:
            return dall_archivio.CHIUSO, None
        self._lega(apertura)
        ricerca = servizio.cerca(str(impronta), dimensione, [str(p) for p in percorsi],
                                 nome=str(nome), intero=bool(intero))
        trovata = ricerca.trovata
        if trovata is None:
            return ricerca.perche, None
        with self._serratura:
            if apertura is not self._legata:
                return dall_archivio.CHIUSO, None
            self._date[trovata.numero] = (self._date.get(trovata.numero, True)
                                          and trovata.diversa)
        return ricerca.perche, (trovata.numero, trovata.nome, trovata.dimensione,
                                trovata.blake2b, trovata.intero, trovata.diversa)

    def _data(self, numero: str):
        _, servizio = self._servizio()
        apertura = None if servizio is None else servizio.apertura
        with self._serratura:
            diversa = self._date.get(numero)
            if apertura is None or apertura is not self._legata or diversa is not False:
                raise _chiuso()
        return apertura

    def _ancora(self, apertura) -> None:
        with self._serratura:
            if apertura is not self._legata:
                raise _chiuso()

    def _apri(self, numero: str) -> dict:
        apertura = self._data(numero)
        giro = self._giro.value
        permesso = apertura.permesso(numero)
        self._ancora(apertura)
        return {**permesso, "giro": giro}

    def _altre(self, numero: str) -> dict:
        apertura = self._data(numero)
        altre = apertura.altre_per_un_figlio(numero)
        self._ancora(apertura)
        return altre

    def _segnala(self, numero: str, persa: bool) -> None:
        self._data(numero)._segnala(numero, bool(persa))

    def _letta(self, numero: str) -> None:
        self._data(numero)._letta(numero)

    def _lega(self, apertura) -> None:
        with self._serratura:
            if apertura is self._legata:
                return
        self._lascia()
        avviso = functools.partial(self._revoca, apertura)
        with self._serratura:
            self._legata, self._avviso = apertura, avviso
        apertura.quando_si_spegne(avviso)

    def _revoca(self, apertura=None) -> None:
        with self._serratura:
            if apertura is not None and apertura is not self._legata:
                return
            self._legata = None
            self._date = {}
            self._giro.value += 1

    def _lascia(self) -> None:
        with self._serratura:
            apertura, avviso = self._legata, self._avviso
            self._avviso = None
        if apertura is not None and avviso is not None:
            apertura.non_piu(avviso)
        self._revoca()

    def controlla(self) -> None:
        with self._serratura:
            legata = self._legata
        if legata is None:
            return
        try:
            _, servizio = self._servizio()
        except Exception as guasto:
            registro.avviso("sicuro.sportello_non_controllato",
                            **registro.dove_si_e_rotto(guasto))
            servizio = None
        if servizio is None or servizio.apertura is not legata:
            self._lascia()

    def chiudi(self) -> None:
        self._lascia()


class DaLontano:

    def __init__(self, notizie, risposte, giro):
        self._notizie = notizie
        self._risposte = risposte
        self._giro = giro
        self._serratura = threading.Lock()
        self._contatore = itertools.count(1)

    def _chiedi(self, cosa: str, *argomenti):
        with self._serratura:
            numero = next(self._contatore)
            try:
                self._notizie.put(("archivio", None, (numero, cosa, *argomenti)))
            except (OSError, ValueError) as errore:
                raise _chiuso() from errore
            scadenza = time.monotonic() + ATTESA
            while True:
                resta = scadenza - time.monotonic()
                if resta <= 0:
                    raise _chiuso()
                try:
                    arrivato, risposta = self._risposte.get(timeout=resta)
                except queue.Empty:
                    raise _chiuso() from None
                except (OSError, ValueError, EOFError) as errore:
                    raise _chiuso() from errore
                if arrivato == numero:
                    break
        if risposta[0]:
            return risposta[1]
        _, messaggio, codice = risposta
        if codice == prendi.Persa.codice:
            raise prendi.Persa(messaggio)
        raise ErroreOfficina(messaggio, codice=codice)

    def _avvisa(self, cosa: str, *argomenti) -> None:
        try:
            self._notizie.put(("archivio", None, (None, cosa, *argomenti)))
        except (OSError, ValueError) as guasto:
            registro.avviso("sicuro.avviso_perso", **registro.dove_si_e_rotto(guasto))

    def cerca(self, impronta: str, dimensione: int | None, percorsi, *, nome: str,
              intero: bool) -> Ricerca:
        try:
            perche, trovata = self._chiedi("cerca", impronta, dimensione,
                                           [str(percorso) for percorso in percorsi],
                                           nome, intero)
        except ErroreOfficina as errore:
            if errore.codice == "archivio_chiuso":
                return Ricerca(dall_archivio.CHIUSO)
            raise
        if trovata is None:
            return Ricerca(perche)
        numero, nome, dimensione, blake2b, intero, diversa = trovata
        return Ricerca(perche, DallArchivio(numero, nome, dimensione, blake2b, intero,
                                            diversa, self._prendi))

    def _prendi(self, trovata: DallArchivio):
        permesso = self._chiedi("apri", trovata.numero)
        giro = permesso["giro"]
        chiave = _ChiaveDiUnaFoto(permesso["chiavi"])

        def vivo() -> None:
            if self._giro.value != giro:
                raise _chiuso()

        def altre() -> list:
            vivo()
            piu = self._chiedi("altre", trovata.numero)
            chiave.aggiungi(piu["chiavi"])
            return [tuple(fonte) for fonte in piu["altre"]]

        vivo()
        return prendi.lettore(trovata.numero, permesso["informazioni"], chiave,
                              permesso["percorso"], trovata.intero, altre=altre,
                              segnala=self._segnala, letta=self._letta, vivo=vivo,
                              guasto=trovata.segna_guasto)

    def _segnala(self, numero: str, persa: bool) -> None:
        self._avvisa("segnala", numero, persa)

    def _letta(self, numero: str) -> None:
        self._avvisa("letta", numero)


_lontano: DaLontano | None = None


def installa(notizie, risposte, giro) -> DaLontano:
    global _lontano
    _lontano = DaLontano(notizie, risposte, giro)
    return _lontano


def qui() -> DaLontano | None:
    return _lontano


__all__ = ["ATTESA", "DaLontano", "Sportello", "installa", "qui"]
