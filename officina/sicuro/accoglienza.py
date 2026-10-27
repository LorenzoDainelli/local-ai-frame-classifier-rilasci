from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from pathlib import Path

from officina.errori import ErroreOfficina
from officina.sicuro import elenco as registro
from officina.sicuro import formato, metadati, sveglia
from officina.sicuro.copia import CUSTODITO, NON_PORTATO, STATI_BUONI, Copiatore
from officina.sicuro.disco import percorso_lungo
from officina.sicuro.lavoro import margine, uso_del_disco
from officina.sicuro.prendi import _dentro_la_radice, trova
from officina.sicuro.sottofondo import PAUSA_SE_USI, Sottofondo


VERSIONE_DIVERSA = "versione_diversa"
NON_C_E = "non_c_e"
SENZA_CASA = "senza_casa"
_IMPRONTA = re.compile(r"[0-9a-f]{64}")
DOPO = " Non ho cambiato niente nell'archivio."
MESSAGGI = {
    "richiesta_strana": "La richiesta per l'Archivio sicuro è strana." + DOPO,
    "uguale_all_originale": "La copia nuova è uguale all'originale." + DOPO,
    NON_C_E: "Nell'Archivio sicuro non trovo l'originale di questo file." + DOPO,
    "fuori_dall_archivio": ("Questo file non è dentro una cartella custodita "
                            "dall'Archivio sicuro." + DOPO),
    "originale_non_c_era": ("Nell'Archivio sicuro l'originale non è mai stato in questa "
                            "cartella." + DOPO),
    "al_posto_c_e_altro": ("Nell'Archivio sicuro, al posto dell'originale, adesso c'è un "
                           "altro file." + DOPO),
    "c_e_gia": ("Nell'Archivio sicuro c'è già un file con lo stesso nome: non lo "
                "copro." + DOPO),
    "sul_disco": "Sul disco c'è già un file con lo stesso nome: non lo copro." + DOPO,
    "disco_staccato": ("Il disco di questa cartella non si trova: se è staccato, "
                       "attaccalo e riprova." + DOPO),
    "spazio_archivio": ("Sul disco dell'Archivio sicuro non c'è abbastanza spazio: "
                        "liberane un po' e riprova." + DOPO),
    "maiuscole": ("Nell'Archivio sicuro c'è già una cartella con lo stesso nome scritto "
                  "in modi diversi, con maiuscole e minuscole: non scelgo io quale usare."
                  + DOPO),
    "non_portato": NON_PORTATO,
}


class Rifiutata(ErroreOfficina):
    codice = "rifiutata"


def _rifiuta(codice: str) -> Rifiutata:
    return Rifiutata(MESSAGGI[codice], codice=codice)


def _e_lei(posto: registro.Posto | None, numeri: set[str]) -> bool:
    return (posto is not None and posto.tipo == metadati.FILE
            and posto.contenuto in numeri)


def _storia(elenco, radice: dict, percorso) -> tuple[str, list] | None:
    relativo = _dentro_la_radice(radice["percorso"], percorso)
    if not relativo:
        return None
    try:
        return relativo, elenco.storia(radice["id"], relativo)
    except ValueError:
        return None


def casa(elenco, impronta: str, dimensione: int | None,
         percorsi) -> tuple[str | None, str | None]:
    numeri = set(elenco.con_impronta(impronta, dimensione))
    if not numeri:
        if trova(elenco, impronta, dimensione, percorsi) is not None:
            return None, VERSIONE_DIVERSA
        return None, NON_C_E
    radici = [radice for radice in elenco.radici() if not radice["tolta"]]
    nella_storia = None
    for percorso in percorsi:
        for radice in radici:
            trovata = _storia(elenco, radice, percorso)
            if trovata is None or not any(_e_lei(posto, numeri) for posto in trovata[1]):
                continue
            presenti = [posto for posto in trovata[1] if posto.sparito is None]
            if not presenti:
                nella_storia = nella_storia or percorso
            elif _e_lei(presenti[-1], numeri):
                return percorso, None
    if nella_storia is not None:
        return nella_storia, None
    return None, SENZA_CASA


@dataclass(frozen=True)
class _Domanda:
    originale: str
    impronta: str
    dimensione: int
    nuova: str
    impronta_nuova: str
    verso: str
    spostato: str

    @classmethod
    def da(cls, richiesta) -> _Domanda:
        try:
            domanda = cls(**{nome: richiesta[nome] for nome in cls.__dataclass_fields__})
        except (KeyError, TypeError) as errore:
            raise _rifiuta("richiesta_strana") from errore
        percorsi = (domanda.originale, domanda.nuova, domanda.verso, domanda.spostato)
        if (not all(isinstance(percorso, str) and percorso for percorso in percorsi)
                or not all(isinstance(impronta, str) and _IMPRONTA.fullmatch(impronta)
                           for impronta in (domanda.impronta, domanda.impronta_nuova))
                or type(domanda.dimensione) is not int or domanda.dimensione < 0):
            raise _rifiuta("richiesta_strana")
        if domanda.impronta_nuova == domanda.impronta:
            raise _rifiuta("uguale_all_originale")
        return domanda


def _assoluto(radice: dict, relativo: str) -> str:
    return os.path.join(radice["percorso"], *relativo.split("/"))


def _sopra_c_e_una_cartella(percorso: str) -> bool:
    dove = os.path.dirname(os.path.abspath(percorso))
    while True:
        try:
            stato = os.lstat(percorso_lungo(dove))
        except FileNotFoundError:
            stato = None
        except NotADirectoryError:
            return False
        if stato is not None:
            return metadati.tipo_di(stato) == metadati.CARTELLA
        sopra = os.path.dirname(dove)
        if sopra == dove:
            return False
        dove = sopra


class Accoglitore:

    def __init__(self, cartella: Path, elenco, chiave, *, aspetta=None, adesso=time.time,
                 disco=uso_del_disco, **per_copiatore):
        self.cartella = Path(cartella)
        self.elenco = elenco
        self._adesso = adesso
        self._disco = disco
        self.copiatore = Copiatore(self.cartella, elenco, chiave, aspetta=aspetta,
                                   adesso=adesso, **per_copiatore)
        self.scritto = False
        self.esito: dict | None = None

    def accogli(self, richiesta: dict) -> dict:
        self.scritto = False
        self.esito = None
        domanda = _Domanda.da(richiesta)
        numeri = set(self.elenco.con_impronta(domanda.impronta, domanda.dimensione))
        if not numeri:
            raise _rifiuta(NON_C_E)
        radice, (originale, verso, spostato) = self._radice(domanda, numeri)
        verso, spostato = self._nomi(radice["id"], originale, verso, spostato)
        prima = self.elenco.attuale(radice["id"], originale)
        dove_va = self.elenco.attuale(radice["id"], verso)
        gia = self.elenco.attuale(radice["id"], spostato)
        if gia is not None:
            if (_e_lei(gia, numeri) and CUSTODITO in gia.segni
                    and self._e_la_nuova(dove_va, domanda.impronta_nuova)):
                self.scritto = True
                self.elenco.salva()
                return self._fatto(radice, dove_va.contenuto, verso, spostato, True)
            raise _rifiuta("c_e_gia")
        ritrovata = dove_va if self._e_la_nuova(dove_va, domanda.impronta_nuova) else None
        if dove_va is not None and ritrovata is None and verso != originale:
            raise _rifiuta("c_e_gia")
        vecchio = self._vecchio(radice, originale, prima, ritrovata, numeri)
        self._disco_libero(radice, domanda, verso, spostato)
        portato = None
        if ritrovata is None:
            self._basta_lo_spazio(domanda.nuova)
            portato = self.copiatore.porta_intero(radice, verso, domanda.nuova,
                                                  domanda.impronta_nuova,
                                                  segni=(CUSTODITO,))
        chiave = registro.nuova_chiave()
        try:
            fatti = self._fatti(radice["id"], originale, spostato, chiave, vecchio, portato,
                                ritrovata)
            self.elenco.registra(fatti)
        except BaseException:
            self.scritto = self._forse_scritto(chiave)
            if not self.scritto and portato is not None and portato.nuovo:
                self.copiatore.togli_il_nuovo(portato.numero)
            raise
        self.scritto = True
        self.elenco.scrivi_nota(fatti)
        self.elenco.salva()
        numero = portato.numero if portato is not None else ritrovata.contenuto
        return self._fatto(radice, numero, verso, spostato, False)

    def _fatto(self, radice: dict, numero: str, verso: str, spostato: str,
               gia_fatto: bool) -> dict:
        self.esito = {"numero": numero, "gia_fatto": gia_fatto,
                      "verso": _assoluto(radice, verso),
                      "spostato": _assoluto(radice, spostato)}
        return self.esito

    def _radice(self, domanda: _Domanda, numeri: set[str]) -> tuple[dict, tuple]:
        dentro = False
        for radice in self.elenco.radici():
            if radice["tolta"]:
                continue
            relativi = tuple(_dentro_la_radice(radice["percorso"], percorso)
                             for percorso in (domanda.originale, domanda.verso,
                                              domanda.spostato))
            if not relativi[0]:
                continue
            dentro = True
            if not all(relativi) or not all(self._pulito(relativo)
                                            for relativo in relativi):
                raise _rifiuta("richiesta_strana")
            originale, verso, spostato = map(registro.piegato, relativi)
            if spostato in (originale, verso):
                raise _rifiuta("richiesta_strana")
            storia = self.elenco.storia(radice["id"], relativi[0])
            if any(_e_lei(posto, numeri) for posto in storia):
                return radice, relativi
        raise _rifiuta("originale_non_c_era" if dentro else "fuori_dall_archivio")

    @staticmethod
    def _pulito(relativo: str) -> bool:
        try:
            return registro.percorso_pulito(relativo) == relativo
        except ValueError:
            return False

    def _e_la_nuova(self, posto: registro.Posto | None, impronta: str) -> bool:
        if (posto is None or posto.tipo != metadati.FILE or not posto.contenuto
                or CUSTODITO not in posto.segni):
            return False
        informazioni = self.elenco.contenuto(posto.contenuto)
        return (informazioni is not None and informazioni["blake2b"] == impronta
                and informazioni["stato"] in STATI_BUONI)

    def _vecchio(self, radice: dict, originale: str, prima, ritrovata,
                 numeri: set[str]) -> registro.Posto:
        if prima is not None and (ritrovata is None or prima.chiave != ritrovata.chiave):
            if not _e_lei(prima, numeri):
                raise _rifiuta("al_posto_c_e_altro")
            return prima
        storia = self.elenco.storia(radice["id"], originale)
        vecchio = next((posto for posto in reversed(storia) if _e_lei(posto, numeri)),
                       None)
        if vecchio is None:
            raise _rifiuta("originale_non_c_era")
        return vecchio

    def _nomi(self, radice: str, originale: str, verso: str,
              spostato: str) -> tuple[str, str]:
        sopra = {"/".join(parti[:fine]) for parti in (verso.split("/"), spostato.split("/"))
                 for fine in range(1, len(parti))}
        piegati = {registro.piegato(percorso) for percorso in sopra}
        cartelle: dict[str, set[str]] = {}
        uguali = set()
        for posto in self.elenco.omonimi(radice, (*sopra, verso, spostato)):
            piegato = registro.piegato(posto.percorso)
            if piegato not in piegati:
                uguali.add(posto.percorso)
            elif posto.tipo != metadati.CARTELLA:
                raise _rifiuta("c_e_gia")
            else:
                cartelle.setdefault(piegato, set()).add(posto.percorso.rsplit("/", 1)[-1])
        nomi = (self._come(verso, cartelle), self._come(spostato, cartelle))
        if uguali - {originale, *nomi}:
            raise _rifiuta("c_e_gia")
        return nomi

    @staticmethod
    def _come(relativo: str, cartelle: dict[str, set[str]]) -> str:
        parti = relativo.split("/")
        for fine in range(1, len(parti)):
            nomi = cartelle.get(registro.piegato("/".join(parti[:fine])), set())
            if len(nomi) > 1:
                raise _rifiuta("maiuscole")
            if nomi:
                parti[fine - 1], = nomi
        return "/".join(parti)

    @staticmethod
    def _disco_libero(radice: dict, domanda: _Domanda, verso: str, spostato: str) -> None:
        cima = Path(radice["percorso"]).anchor
        if cima and not os.path.isdir(percorso_lungo(cima)):
            raise _rifiuta("disco_staccato")
        nuovi = (domanda.verso, domanda.spostato, _assoluto(radice, verso),
                 _assoluto(radice, spostato))
        for percorso in (domanda.originale, *nuovi):
            if os.path.lexists(percorso_lungo(percorso)):
                raise _rifiuta("sul_disco")
        if not all(_sopra_c_e_una_cartella(percorso) for percorso in nuovi):
            raise _rifiuta("sul_disco")

    def _basta_lo_spazio(self, nuova: str) -> None:
        try:
            dimensione = os.stat(percorso_lungo(nuova)).st_size
        except OSError as errore:
            raise _rifiuta("non_portato") from errore
        libero, totale = self._disco(self.cartella)
        if libero - formato.peso_previsto(dimensione) < margine(totale):
            raise _rifiuta("spazio_archivio")

    def _fatti(self, radice: str, originale: str, spostato: str, chiave: str,
               vecchio: registro.Posto, portato, ritrovata) -> list[dict]:
        adesso = self._adesso()
        fatti = list(portato.fatti) if portato is not None else []
        fatti.append(registro.fatto_posto(
            radice, spostato, metadati.FILE, vecchio.contenuto, vecchio.metadati,
            segni=(*vecchio.segni, CUSTODITO), chiave=chiave, quando=adesso))
        fatti += [registro.fatto_flusso(chiave, nome, numero)
                  for nome, numero in self.elenco.flussi_di(vecchio.chiave)]
        resta = None if ritrovata is None else ritrovata.chiave
        fatti += [registro.fatto_sparito(posto.chiave, adesso)
                  for posto in self.elenco.storia(radice, originale)
                  if posto.sparito is None and posto.chiave != resta]
        return fatti

    def _forse_scritto(self, chiave: str) -> bool:
        try:
            return self.elenco.posto(chiave) is not None
        except Exception:
            return True


class Accoglienza(Sottofondo):

    nome = "archivio-sicuro-accoglienza"

    def __init__(self, cartella: Path, elenco, chiave, *, sveglio=sveglia.sveglio,
                 pausa_se_usi: float = PAUSA_SE_USI, **per_accoglitore):
        super().__init__(sveglio=sveglio, pausa_se_usi=pausa_se_usi)
        self.accoglitore = Accoglitore(cartella, elenco, chiave, aspetta=self._aspetta,
                                       dormi=self._dormi_fermabile, **per_accoglitore)

    def avvia(self, richiesta: dict) -> bool:
        return self._parti(dict(richiesta))

    def _azzera(self) -> None:
        self.accoglitore.scritto = False
        self.accoglitore.esito = None

    def _lavora(self, richiesta: dict) -> None:
        self.accoglitore.accogli(richiesta)

    def istantanea(self) -> dict:
        esito = self.accoglitore.esito
        return {"stato": self.stato, "errore": self.errore, "codice": self.codice,
                "scritto": self.accoglitore.scritto,
                "esito": None if esito is None else dict(esito)}


__all__ = ["Accoglienza", "Accoglitore", "MESSAGGI", "NON_C_E", "Rifiutata", "SENZA_CASA",
           "VERSIONE_DIVERSA", "casa"]
