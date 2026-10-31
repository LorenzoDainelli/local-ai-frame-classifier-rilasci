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
SOSTITUISCI = "sostituisci"
RIMETTI = "rimetti"
AGGIUNGI = "aggiungi"
DATE = ("modifica", "accesso", "creazione")
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
    "base_non_c_e": ("Nell'Archivio sicuro non trovo lo scatto senza ritocchi al suo posto."
                     + DOPO),
    "al_posto_della_base_c_e_altro": ("Nell'Archivio sicuro, al posto dello scatto senza "
                                      "ritocchi, adesso c'è un altro file." + DOPO),
    "al_posto_della_copia_c_e_altro": ("Nell'Archivio sicuro, al posto della copia "
                                       "ritoccata, adesso c'è un altro file." + DOPO),
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


def date(elenco, impronta: str, dimensione: int | None, percorso) -> dict:
    numeri = set(elenco.con_impronta(impronta, dimensione))
    for radice in elenco.radici():
        if radice["tolta"]:
            continue
        trovata = _storia(elenco, radice, percorso)
        if trovata is None:
            continue
        for posto in reversed(trovata[1]):
            if _e_lei(posto, numeri):
                return {nome: posto.metadati[nome] for nome in DATE
                        if type(posto.metadati.get(nome)) is int}
    return {}


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


def _campi(richiesta: dict, percorsi: tuple[str, ...], impronte: tuple[str, ...]) -> dict:
    try:
        campi = {nome: richiesta[nome] for nome in (*percorsi, *impronte)}
    except KeyError as errore:
        raise _rifiuta("richiesta_strana") from errore
    if (not all(isinstance(campi[nome], str) and campi[nome] for nome in percorsi)
            or not all(isinstance(campi[nome], str) and _IMPRONTA.fullmatch(campi[nome])
                       for nome in impronte)):
        raise _rifiuta("richiesta_strana")
    return campi


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
        come = richiesta.get("come") if isinstance(richiesta, dict) else None
        if come is None:
            return self._scambia(_Domanda.da(richiesta))
        if come == SOSTITUISCI:
            return self._sostituisci(_campi(richiesta, ("copia", "nuova", "base"), (
                "impronta", "impronta_nuova", "impronta_base")))
        if come == RIMETTI:
            return self._rimetti(_campi(richiesta, ("copia", "base"),
                                        ("impronta", "impronta_base")))
        if come == AGGIUNGI:
            return self._aggiungi(_campi(richiesta, ("nuova", "verso", "base"),
                                         ("impronta_nuova", "impronta_base")))
        raise _rifiuta("richiesta_strana")

    def _scambia(self, domanda: _Domanda) -> dict:
        numeri = set(self.elenco.con_impronta(domanda.impronta, domanda.dimensione))
        if not numeri:
            raise _rifiuta(NON_C_E)
        radice, (originale, verso, spostato) = self._radice(
            (domanda.originale, domanda.verso, domanda.spostato), numeri,
            "originale_non_c_era")
        verso, spostato = self._nomi(radice["id"], {originale}, verso, spostato)
        prima = self.elenco.attuale(radice["id"], originale)
        dove_va = self.elenco.attuale(radice["id"], verso)
        gia = self.elenco.attuale(radice["id"], spostato)
        if gia is not None:
            if (_e_lei(gia, numeri) and CUSTODITO in gia.segni
                    and self._e_la_nuova(dove_va, domanda.impronta_nuova)):
                return self._gia_fatto(radice, dove_va.contenuto, verso, spostato)
            raise _rifiuta("c_e_gia")
        ritrovata = dove_va if self._e_la_nuova(dove_va, domanda.impronta_nuova) else None
        if dove_va is not None and ritrovata is None and verso != originale:
            raise _rifiuta("c_e_gia")
        vecchio = self._vecchio(radice, originale, prima, ritrovata, numeri,
                                "al_posto_c_e_altro", "originale_non_c_era")
        self._disco_libero(radice, (domanda.originale,), (
            domanda.verso, domanda.spostato, _assoluto(radice, verso),
            _assoluto(radice, spostato)))
        portato = self._porta(radice, verso, domanda.nuova, domanda.impronta_nuova,
                              ritrovata)

        def fatti(adesso: float) -> list[dict]:
            return [*self._portati(portato),
                    *self._trasloco(radice["id"], spostato, vecchio, adesso),
                    *self._spariti(radice["id"], originale, ritrovata, adesso)]

        self._scrivi(fatti, portato)
        numero = portato.numero if portato is not None else ritrovata.contenuto
        return self._fatto(radice, numero, verso, spostato, False)

    def _sostituisci(self, campi: dict) -> dict:
        radice, numeri, copia, verso, base = self._della_base(campi, "copia")
        ora = self.elenco.attuale(radice["id"], base)
        if ora is not None and not _e_lei(ora, numeri):
            raise _rifiuta("al_posto_della_base_c_e_altro")
        dove_va = self.elenco.attuale(radice["id"], verso)
        ritrovata = dove_va if self._e_la_nuova(dove_va, campi["impronta_nuova"]) else None
        self._prima_la_copia(radice, campi, copia, verso, dove_va, ritrovata)
        if ritrovata is not None and not self._altri(radice["id"], copia, ritrovata):
            return self._gia_fatto(radice, ritrovata.contenuto, verso, None)
        self._disco_libero(radice, (), (campi["copia"], _assoluto(radice, verso)))
        portato = self._porta(radice, verso, campi["nuova"], campi["impronta_nuova"],
                              ritrovata)

        def fatti(adesso: float) -> list[dict]:
            return [*self._portati(portato),
                    *self._spariti(radice["id"], copia, ritrovata, adesso)]

        self._scrivi(fatti, portato)
        numero = portato.numero if portato is not None else ritrovata.contenuto
        return self._fatto(radice, numero, verso, None, False)

    def _rimetti(self, campi: dict) -> dict:
        radice, numeri, copia, verso, base = self._della_base(campi, "copia")
        dove_va = self.elenco.attuale(radice["id"], verso)
        ritrovata = (dove_va if _e_lei(dove_va, numeri) and CUSTODITO in dove_va.segni
                     else None)
        self._prima_la_copia(radice, campi, copia, verso, dove_va, ritrovata)
        ora = self.elenco.attuale(radice["id"], base)
        vecchio = self._vecchio(radice, base, ora, None, numeri,
                                "al_posto_della_base_c_e_altro", "base_non_c_e")
        if (ritrovata is not None and ora is None
                and not self._altri(radice["id"], copia, ritrovata)):
            return self._gia_fatto(radice, ritrovata.contenuto, verso, None)
        self._disco_libero(radice, (campi["base"],), (campi["copia"],
                                                      _assoluto(radice, verso)))

        def fatti(adesso: float) -> list[dict]:
            tornato = ([] if ritrovata is not None
                       else self._trasloco(radice["id"], verso, vecchio, adesso))
            return [*tornato, *self._spariti(radice["id"], copia, ritrovata, adesso),
                    *self._spariti(radice["id"], base, None, adesso)]

        self._scrivi(fatti, None)
        numero = vecchio.contenuto if ritrovata is None else ritrovata.contenuto
        return self._fatto(radice, numero, verso, None, False)

    def _aggiungi(self, campi: dict) -> dict:
        radice, _, _, verso, _ = self._della_base(campi, "verso", nuovo=True)
        dove_va = self.elenco.attuale(radice["id"], verso)
        if dove_va is not None:
            if self._e_la_nuova(dove_va, campi["impronta_nuova"]):
                return self._gia_fatto(radice, dove_va.contenuto, verso, None)
            raise _rifiuta("c_e_gia")
        self._disco_libero(radice, (), (campi["verso"], _assoluto(radice, verso)))
        portato = self._porta(radice, verso, campi["nuova"], campi["impronta_nuova"], None)
        self._scrivi(lambda adesso: self._portati(portato), portato)
        return self._fatto(radice, portato.numero, verso, None, False)

    def _della_base(self, campi: dict, dove: str, nuovo: bool = False) -> tuple:
        numeri = set(self.elenco.con_impronta(campi["impronta_base"]))
        if not numeri:
            raise _rifiuta("base_non_c_e")
        radice, (base, percorso) = self._radice((campi["base"], campi[dove]), numeri,
                                                "base_non_c_e")
        verso, = self._nomi(radice["id"], set() if nuovo else {percorso}, percorso)
        return radice, numeri, percorso, verso, base

    def _prima_la_copia(self, radice: dict, campi: dict, copia: str, verso: str, dove_va,
                        ritrovata) -> None:
        if dove_va is not None and ritrovata is None and verso != copia:
            raise _rifiuta("c_e_gia")
        prima = self.elenco.attuale(radice["id"], copia)
        if (prima is not None and (ritrovata is None or prima.chiave != ritrovata.chiave)
                and not _e_lei(prima, set(self.elenco.con_impronta(campi["impronta"])))):
            raise _rifiuta("al_posto_della_copia_c_e_altro")

    def _gia_fatto(self, radice: dict, numero: str, verso: str,
                   spostato: str | None) -> dict:
        self.scritto = True
        self.elenco.salva()
        return self._fatto(radice, numero, verso, spostato, True)

    def _fatto(self, radice: dict, numero: str, verso: str, spostato: str | None,
               gia_fatto: bool) -> dict:
        self.esito = {"numero": numero, "gia_fatto": gia_fatto,
                      "verso": _assoluto(radice, verso),
                      "spostato": None if spostato is None else _assoluto(radice, spostato)}
        return self.esito

    def _radice(self, percorsi: tuple[str, ...], numeri: set[str],
                mai: str) -> tuple[dict, tuple]:
        dentro = False
        for radice in self.elenco.radici():
            if radice["tolta"]:
                continue
            relativi = tuple(_dentro_la_radice(radice["percorso"], percorso)
                             for percorso in percorsi)
            if not relativi[0]:
                continue
            dentro = True
            if not all(relativi) or not all(self._pulito(relativo)
                                            for relativo in relativi):
                raise _rifiuta("richiesta_strana")
            *prima, ultimo = map(registro.piegato, relativi)
            if ultimo in prima:
                raise _rifiuta("richiesta_strana")
            storia = self.elenco.storia(radice["id"], relativi[0])
            if any(_e_lei(posto, numeri) for posto in storia):
                return radice, relativi
        raise _rifiuta(mai if dentro else "fuori_dall_archivio")

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

    def _vecchio(self, radice: dict, percorso: str, prima, ritrovata, numeri: set[str],
                 altro: str, mai: str) -> registro.Posto:
        if prima is not None and (ritrovata is None or prima.chiave != ritrovata.chiave):
            if not _e_lei(prima, numeri):
                raise _rifiuta(altro)
            return prima
        storia = self.elenco.storia(radice["id"], percorso)
        vecchio = next((posto for posto in reversed(storia) if _e_lei(posto, numeri)),
                       None)
        if vecchio is None:
            raise _rifiuta(mai)
        return vecchio

    def _nomi(self, radice: str, gia: set[str], *nuovi: str) -> tuple[str, ...]:
        sopra = {"/".join(parti[:fine]) for parti in (nuovo.split("/") for nuovo in nuovi)
                 for fine in range(1, len(parti))}
        piegati = {registro.piegato(percorso) for percorso in sopra}
        cartelle: dict[str, set[str]] = {}
        uguali = set()
        for posto in self.elenco.omonimi(radice, (*sopra, *nuovi)):
            piegato = registro.piegato(posto.percorso)
            if piegato not in piegati:
                uguali.add(posto.percorso)
            elif posto.tipo != metadati.CARTELLA:
                raise _rifiuta("c_e_gia")
            else:
                cartelle.setdefault(piegato, set()).add(posto.percorso.rsplit("/", 1)[-1])
        nomi = tuple(self._come(nuovo, cartelle) for nuovo in nuovi)
        if uguali - {*gia, *nomi}:
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
    def _disco_libero(radice: dict, liberi: tuple[str, ...], nuovi: tuple[str, ...]) -> None:
        cima = Path(radice["percorso"]).anchor
        if cima and not os.path.isdir(percorso_lungo(cima)):
            raise _rifiuta("disco_staccato")
        for percorso in (*liberi, *nuovi):
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

    def _porta(self, radice: dict, verso: str, nuova: str, impronta: str, ritrovata):
        if ritrovata is not None:
            return None
        self._basta_lo_spazio(nuova)
        return self.copiatore.porta_intero(radice, verso, nuova, impronta,
                                           segni=(CUSTODITO,))

    @staticmethod
    def _portati(portato) -> list[dict]:
        return [] if portato is None else list(portato.fatti)

    def _trasloco(self, radice: str, percorso: str, vecchio: registro.Posto,
                  adesso: float) -> list[dict]:
        chiave = registro.nuova_chiave()
        return [registro.fatto_posto(radice, percorso, metadati.FILE, vecchio.contenuto,
                                     vecchio.metadati, segni=(*vecchio.segni, CUSTODITO),
                                     chiave=chiave, quando=adesso),
                *(registro.fatto_flusso(chiave, nome, numero)
                  for nome, numero in self.elenco.flussi_di(vecchio.chiave))]

    def _altri(self, radice: str, percorso: str, resta) -> list[registro.Posto]:
        tieni = None if resta is None else resta.chiave
        return [posto for posto in self.elenco.storia(radice, percorso)
                if posto.sparito is None and posto.chiave != tieni]

    def _spariti(self, radice: str, percorso: str, resta, adesso: float) -> list[dict]:
        return [registro.fatto_sparito(posto.chiave, adesso)
                for posto in self._altri(radice, percorso, resta)]

    def _scrivi(self, fai, portato) -> None:
        fatti: list[dict] = []
        try:
            fatti = fai(self._adesso())
            self.elenco.registra(fatti)
        except BaseException:
            self.scritto = self._forse_scritto(fatti)
            if not self.scritto and portato is not None and portato.nuovo:
                self.copiatore.togli_il_nuovo(portato.numero)
            raise
        self.scritto = True
        self.elenco.scrivi_nota(fatti)
        self.elenco.salva()

    def _forse_scritto(self, fatti: list[dict]) -> bool:
        try:
            for fatto in fatti:
                if fatto["fatto"] == "posto":
                    return self.elenco.posto(fatto["chiave"]) is not None
                if fatto["fatto"] == "sparito":
                    return self.elenco.posto(fatto["chiave"]).sparito is not None
            return False
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


__all__ = ["AGGIUNGI", "Accoglienza", "Accoglitore", "MESSAGGI", "NON_C_E", "RIMETTI",
           "Rifiutata", "SENZA_CASA", "SOSTITUISCI", "VERSIONE_DIVERSA", "casa"]
