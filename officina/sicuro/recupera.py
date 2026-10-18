from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from officina.errori import ErroreOfficina, PasswordSbagliata
from officina.sicuro import chiavi, metadati, sveglia
from officina.sicuro import elenco as registro
from officina.sicuro.chiavetta import CARTELLA, senza_finestre_di_errore
from officina.sicuro.diretto import Lettore
from officina.sicuro.elenco import Elenco, ElencoRovinato
from officina.sicuro.estrai import MARGINE, Estrazione, _dentro, con_numero, scelti
from officina.sicuro.sottofondo import ATTIVI, ERRORE, FERMATO, FERMO, FINITO, GUASTO


__all__ = ["ARRIVO", "RAPPORTO", "Recupero", "Regia", "accanto", "dove_di_solito",
           "e_un_archivio", "principale", "trova"]

RAPPORTO = "Cosa è successo nel recupero.txt"
ARRIVO = "Foto recuperate"
OGNI = 200
CHIUDI_ENTRO = 10.0
NOMI_LIBERI = 1000

CERCA = "cerca"
PASSWORD = "password"
SBLOCCO = "sblocco"
LAVORO = "lavoro"
FINE = "fine"

SPIEGAZIONI = {
    "contenuto_mancante": "non è uscito: sulla chiavetta manca, oppure è rovinato "
                          "in tutte le sue copie",
    "rovinato": "è uscito, ma un suo pezzo era rovinato e al suo posto ci sono "
                "degli zeri",
    "incompleto": "era già incompleto quando è stato messo nell'archivio",
    "collegamento_non_creato": "era un collegamento e non si è riusciti a rifarlo",
    "flusso_mancante": "manca una sua parte nascosta di Windows",
    "flusso_rovinato": "una sua parte nascosta di Windows è rovinata",
    "flusso_scritto_male": "una sua parte nascosta di Windows non si è scritta bene",
    "cartella_non_creata": "la cartella non si è potuta creare",
    "file_non_creato": "il file non si è potuto creare",
    "nome_cambiato": "il nome aveva caratteri che Windows non accetta: è stato "
                     "cambiato",
    "rinominato": "c'era già qualcosa con lo stesso nome: ha preso un numero tra "
                  "parentesi",
    "in_uso": "quando è stato messo nell'archivio era aperto in un altro programma",
    "diverso_da_prima": "è cambiato mentre veniva messo nell'archivio",
    "flussi_non_rimessi": "le sue parti nascoste di Windows non si sono potute "
                          "rimettere",
    "flusso_strano": "aveva una parte nascosta di Windows con un nome strano",
    "cartella_cambiata": "la cartella è stata cambiata da fuori mentre lavoravo",
    "bersaglio_illeggibile": "non si è letto dove puntava il collegamento",
    "permessi_illeggibili": "i suoi permessi non si sono letti",
    "permessi_troppo_lunghi": "i suoi permessi erano troppo lunghi per rimetterli",
    "flussi_illeggibili": "le sue parti nascoste di Windows non si sono lette",
    "date_non_rimesse": "le sue date non si sono potute rimettere",
    "creazione_non_rimessa": "la sua data di creazione non si è potuta rimettere",
    "attributi_non_rimessi": "i suoi attributi (nascosto, sola lettura) non si "
                             "sono potuti rimettere",
}

RIFIUTI = {
    "poco_spazio": "non è uscita: lo spazio non bastava",
    "dove_non_creato": "non è uscita: la cartella dove metterla non si è potuta "
                       "creare",
    "dove_strano": "non è uscita: la cartella dove metterla non è una cartella vera",
    "cartella_non_creata": "non è uscita: la sua cartella non si è potuta creare",
    "estrai_nell_archivio": "non è uscita: non si può metterla dentro l'archivio",
    "niente_da_estrarre": "era vuota",
}

NOTE = {
    "fotografia_rovinata": "L'ultimo elenco dell'archivio era rovinato: ho usato "
                           "quello di prima e ho ritrovato le foto arrivate dopo "
                           "leggendo i file uno per uno.",
    "storia_persa": "L'elenco dell'archivio era rovinato: l'ho rifatto leggendo i "
                    "file uno per uno. Le foto ci sono, ma qualche versione vecchia "
                    "potrebbe mancare.",
    "file_illeggibili": "{illeggibili} file dell'archivio non si leggono. Se manca "
                        "qualche foto, prova con l'altra copia dell'archivio, "
                        "quella sul computer o su un'altra chiavetta.",
    "cartella_illeggibile": "Una cartella dell'archivio non si legge. Se manca "
                            "qualche foto, prova con l'altra copia dell'archivio.",
    "diario_rovinato": "Una parte dell'elenco dell'archivio era rovinata: le foto "
                       "aggiunte per ultime potrebbero mancare.",
}

FERMATE = {
    "spazio_finito": "Il disco dove le metti si è riempito e mi sono fermato. "
                     "Quello che è già uscito resta. Libera spazio o scegli un "
                     "altro disco e rifai: le foto già uscite non si toccano.",
    "archivio_sparito": "La chiavetta non si legge più: forse si è staccata. "
                        "Ricollegala e rifai da capo. Quello che è già uscito "
                        "resta.",
    "dove_cambiato": "La cartella dove le mettevo è sparita o è cambiata: mi sono "
                     "fermato per non scrivere altrove.",
    "scritto_male": "Il disco dove le metti non scrive bene: rileggendo, i file non "
                    "tornavano. Scegli un altro disco e rifai.",
}

FONDO = "#262624"
CARTA = "#30302E"
LINEA = "#55534D"
INK = "#F5F4EE"
TENUE = "#A6A49A"
ACCENTO = "#D97757"
SU_ACCENTO = "#1F1E1D"
MALE = "#D9776A"
BENE = "#8FB58A"


def _cartella_vera(percorso: Path) -> bool:
    try:
        return stat.S_ISDIR(os.stat(percorso).st_mode)
    except (OSError, ValueError):
        return False


def e_un_archivio(cartella) -> bool:
    cartella = Path(cartella)
    try:
        return chiavi.esiste(cartella) or _cartella_vera(cartella / registro.CONTENUTI)
    except (OSError, ValueError):
        return False


def trova(partenza) -> Path | None:
    if partenza is None:
        return None
    partenza = Path(partenza)
    candidati = [partenza / CARTELLA, partenza]
    if partenza.name in (registro.CONTENUTI, registro.ELENCO):
        candidati.append(partenza.parent)
    for candidato in candidati:
        if e_un_archivio(candidato):
            return candidato
    return None


def accanto() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path.cwd()


def dove_di_solito() -> Path:
    return Path.home() / ARRIVO


def numero(quanti: int) -> str:
    return f"{quanti:,}".replace(",", ".")


def misura(byte: int) -> str:
    if byte < 1024 ** 2:
        testo = f"{byte / 1024:.1f} KB" if byte >= 1024 else f"{byte} byte"
    elif byte < 1024 ** 3:
        testo = f"{byte / 1024 ** 2:.1f} MB"
    else:
        testo = f"{byte / 1024 ** 3:.1f} GB"
    return testo.replace(".", ",")


def _file(quanti: int) -> str:
    return f"{numero(quanti)} file"


@contextmanager
def _sveglio():
    senza_finestre_di_errore()
    with sveglia.sveglio() as acceso:
        yield acceso


def _errore(messaggio: str, codice: str) -> ErroreOfficina:
    return ErroreOfficina(messaggio, codice=codice)


class Recupero:

    def __init__(self, archivio, *, apri=Lettore, spazio=None, windows=None,
                 sveglio=_sveglio):
        self.archivio = Path(archivio)
        self._apri = apri
        self._spazio = spazio
        self._windows = windows
        self._sveglio = sveglio
        self.elenco: Elenco | None = None
        self.estrazione: Estrazione | None = None
        self.dove: Path | None = None
        self.totali: dict[str, tuple[int, int]] = {}
        self.radici: dict[str, str] = {}
        self.scritto: Path | None = None
        self.problemi: set[str] = set()
        self.illeggibili = 0
        self._massimo = (0, 0)

    @property
    def sbloccato(self) -> bool:
        return self.estrazione is not None

    def _leggi_la_chiave(self) -> None:
        if not _cartella_vera(self.archivio):
            raise _errore("La cartella dell'archivio non si legge più: ricollega la "
                          "chiavetta e riprova.", "archivio_sparito")
        try:
            chiavi._leggi(self.archivio)
        except chiavi.ChiaveRovinata as guasto:
            raise chiavi.ChiaveRovinata(
                "Il file con la chiave dell'archivio è rovinato, e anche la sua "
                "copia. Prova con l'altra copia dell'archivio: quella sul computer "
                "o su un'altra chiavetta.") from guasto
        except ErroreOfficina as guasto:
            if guasto.codice == "sicuro_mancante":
                raise _errore(
                    "Qui manca il file con la chiave dell'archivio («chiave.json»). "
                    "Scegli la cartella «Archivio sicuro» della chiavetta.",
                    "sicuro_mancante") from guasto
            if guasto.codice == "versione_piu_nuova":
                raise _errore(
                    "Questo archivio è stato scritto da una versione più nuova del "
                    "programma: usa il «Recupera foto» che sta sulla stessa "
                    "chiavetta.", "versione_piu_nuova") from guasto
            raise

    def sblocca(self, password: str) -> None:
        if self.sbloccato:
            return
        self._leggi_la_chiave()
        try:
            chiave = chiavi.apri(self.archivio, password, ripara=False)
        except PasswordSbagliata as guasto:
            if not password:
                raise
            raise PasswordSbagliata(
                "La password non è quella. Le foto non sono state toccate: "
                "riprova con calma, facendo caso alle maiuscole.") from guasto
        except OSError as guasto:
            raise _errore("La chiavetta non si legge più: ricollegala e riprova.",
                          "archivio_sparito") from guasto
        try:
            elenco = Elenco.apri(self.archivio, chiave, sola_lettura=True)
        except ElencoRovinato as guasto:
            if guasto.codice == "chiave_diversa":
                raise _errore(
                    "La password è giusta, ma i file dell'archivio non sono di "
                    "questa chiave: forse la cartella «Archivio sicuro» è stata "
                    "mescolata con un'altra.", "chiave_diversa") from guasto
            raise
        except OSError as guasto:
            raise _errore("La chiavetta non si legge più: ricollegala e riprova.",
                          "archivio_sparito") from guasto
        try:
            estrazione = Estrazione(self.archivio, elenco, chiave,
                                    sveglio=self._sveglio, apri=self._apri,
                                    spazio=self._spazio, windows=self._windows)
            for radice in elenco.radici():
                posti = scelti(elenco, radice["id"])
                self.radici[radice["id"]] = radice["percorso"]
                if posti:
                    self.totali[radice["id"]] = (
                        sum(posto.tipo != metadati.CARTELLA for posto in posti),
                        estrazione.estrattore._peso(posti))
        except BaseException:
            elenco.chiudi()
            self.totali.clear()
            self.radici.clear()
            raise
        self.problemi = set(elenco.problemi)
        self.illeggibili = len(elenco.illeggibili)
        self.elenco = elenco
        self.estrazione = estrazione

    def quanto(self) -> tuple[int, int]:
        return (sum(quanti for quanti, _ in self.totali.values()),
                sum(peso for _, peso in self.totali.values()))

    def parti(self, dove) -> bool:
        if not self.sbloccato:
            raise _errore("Prima scrivi la password.", "da_sbloccare")
        if self.estrazione.acceso:
            return False
        dove = Path(dove)
        if _dentro(dove, self.archivio):
            raise _errore("Le foto non si possono mettere dentro l'archivio: scegli "
                          "un'altra cartella.", "estrai_nell_archivio")
        richieste = self.estrazione.estrattore.richieste_per_tutto(dove)
        if not richieste:
            raise _errore("Nell'archivio non c'è niente da tirare fuori.",
                          "niente_da_estrarre")
        _, serve = self.quanto()
        try:
            libero = self.estrazione.estrattore._libero(dove)
        except OSError as guasto:
            raise _errore("La cartella scelta non si trova: scegline un'altra.",
                          "dove_strano") from guasto
        if libero - serve < MARGINE:
            raise _errore(
                f"Per tirare fuori tutto servono {misura(serve)}, ma lì ne restano "
                f"liberi {misura(max(libero, 0))}: scegli un disco con più spazio, "
                "anche uno esterno.", "poco_spazio")
        self.dove = dove
        self.scritto = None
        self._massimo = (0, 0)
        return self.estrazione.avvia(richieste)

    @property
    def acceso(self) -> bool:
        return self.estrazione is not None and self.estrazione.acceso

    def ferma(self, aspetta: float | None = None) -> None:
        if self.estrazione is not None:
            self.estrazione.ferma(aspetta)

    def aspetta_fine(self, quanto: float | None = None) -> bool:
        if self.estrazione is None:
            return True
        return self.estrazione.aspetta_fine(quanto)

    def avanzamento(self) -> dict:
        estrazione = self.estrazione
        file_totali, byte_totali = self.quanto()
        if estrazione is None:
            return {"file": 0, "byte": 0, "file_totali": file_totali,
                    "byte_totali": byte_totali, "percorso": None}
        estrattore = estrazione.estrattore
        corrente = estrattore.resoconto
        avanzamento = estrattore.avanzamento
        contate: set[str] = set()
        fatti = byte = 0
        for resoconto in list(estrazione.resoconti):
            if resoconto.finito and resoconto.radice not in contate:
                contate.add(resoconto.radice)
                quanti, peso = self.totali.get(resoconto.radice, (0, 0))
                fatti += quanti
                byte += peso
        for richiesta, _ in list(estrazione.rifiutate):
            radice = richiesta.get("radice")
            if radice is not None and radice not in contate:
                contate.add(radice)
                quanti, peso = self.totali.get(radice, (0, 0))
                fatti += quanti
                byte += peso
        if (corrente is not None and not corrente.finito
                and corrente.radice not in contate):
            fatti += avanzamento.file_veri
            byte += avanzamento.byte
        fatti = max(fatti, self._massimo[0])
        byte = max(byte, self._massimo[1])
        self._massimo = (fatti, byte)
        return {"file": min(fatti, file_totali), "byte": min(byte, byte_totali),
                "file_totali": file_totali, "byte_totali": byte_totali,
                "percorso": avanzamento.percorso if self.acceso else None}

    def note(self) -> list[str]:
        scritte = []
        for codice, testo in NOTE.items():
            if codice == "fotografia_rovinata" and "storia_persa" in self.problemi:
                continue
            if codice in self.problemi:
                scritte.append(testo.format(illeggibili=numero(self.illeggibili)))
        return scritte

    def _nome(self, radice: str) -> str:
        return self.radici.get(radice) or radice

    def riassunto(self) -> dict:
        estrazione = self.estrazione
        if estrazione is None:
            return {"stato": FERMO, "esito": None, "frase": None, "verde": False,
                    "rossi": 0, "gialli": False, "file": 0, "byte": 0,
                    "cartelle": [], "note": [], "rifiutate": 0}
        stato = estrazione.stato
        resoconti = list(estrazione.resoconti)
        rifiutate = list(estrazione.rifiutate)
        rossi = {(resoconto.radice, percorso) for resoconto in resoconti
                 for _, percorso in resoconto.rossi}
        file = sum(resoconto.file for resoconto in resoconti)
        byte = sum(resoconto.byte for resoconto in resoconti)
        gialli = any(problema not in resoconto.rossi for resoconto in resoconti
                     for problema in resoconto.problemi)
        note = self.note()
        verde = (stato == FINITO and not rifiutate
                 and all(resoconto.verde for resoconto in resoconti))
        uscite = f"{_file(file)}, {misura(byte)}"
        if stato in ATTIVI:
            esito = f"Sto tirando fuori le foto: finora {uscite}."
        elif stato == FINITO and verde:
            esito = f"Fatto! Sono uscite tutte: {uscite}."
        elif stato == FINITO:
            male = len(rossi)
            parti = []
            if male == 1:
                parti.append("1 file non è uscito bene")
            elif male:
                parti.append(f"{_file(male)} non sono usciti bene")
            if len(rifiutate) == 1:
                parti.append("1 cartella non è uscita")
            elif rifiutate:
                parti.append(f"{numero(len(rifiutate))} cartelle non sono uscite")
            esito = f"Finito, ma {' e '.join(parti)}. Gli altri sono usciti: {uscite}."
        elif stato == FERMATO:
            esito = f"Fermato. Quello che è già uscito resta: {uscite}."
        elif stato == GUASTO:
            esito = ("La chiavetta dà errori di lettura e mi sono fermato. Quello "
                     "che è già uscito resta. Prova con l'altra copia "
                     "dell'archivio.")
        elif stato == ERRORE:
            esito = FERMATE.get(estrazione.codice) or (
                f"Mi sono fermato per un errore: {estrazione.errore}")
        else:
            esito = None
        frase = esito
        if esito is not None and self.scritto is not None:
            dove = "nella cartella dove hai messo le foto"
            frase = (f"{esito} Trovi tutti i dettagli in «{self.scritto.name}», "
                     f"{dove}.")
        return {"stato": stato, "esito": esito, "frase": frase, "verde": verde,
                "rossi": len(rossi), "gialli": gialli, "file": file, "byte": byte,
                "cartelle": [resoconto.cartella for resoconto in resoconti
                             if resoconto.cartella],
                "note": note, "rifiutate": len(rifiutate)}

    def da_raccontare(self) -> bool:
        if self.estrazione is None or self.estrazione.stato in (*ATTIVI, FERMO):
            return False
        riassunto = self.riassunto()
        return not riassunto["verde"] or riassunto["gialli"] or bool(riassunto["note"])

    def testo_del_rapporto(self) -> str:
        riassunto = self.riassunto()
        estrazione = self.estrazione
        righe = ["Recupera foto: cosa è successo", "",
                 f"Quando: {datetime.now().strftime('%d/%m/%Y %H:%M')}",
                 f"Archivio: {self.archivio}",
                 f"Foto messe in: {self.dove}",
                 f"Com'è andata: {riassunto['esito']}"]
        if riassunto["note"]:
            righe += ["", "Da sapere sull'archivio:"]
            righe += [f"- {nota}" for nota in riassunto["note"]]
        for resoconto in list(estrazione.resoconti):
            righe += ["", f"Cartella {self._nome(resoconto.radice)}"]
            if resoconto.cartella:
                righe.append(f"  Messa in: {resoconto.cartella}")
            uscite = [_file(resoconto.file), misura(resoconto.byte)]
            if resoconto.cartelle:
                uscite.append(f"{numero(resoconto.cartelle)} cartelle")
            if resoconto.collegamenti:
                uscite.append(f"{numero(resoconto.collegamenti)} collegamenti")
            righe.append(f"  Uscite: {', '.join(uscite)}")
            if not resoconto.finito:
                righe.append("  Non è arrivata alla fine.")
            rossi = resoconto.rossi
            gialli = [problema for problema in resoconto.problemi
                      if problema not in rossi]
            for titolo, problemi in (("Non usciti bene", rossi),
                                     ("Da sapere", gialli)):
                if not problemi:
                    continue
                righe.append(f"  {titolo}:")
                for codice, percorso in problemi:
                    spiegazione = SPIEGAZIONI.get(codice, codice)
                    righe.append(f"  - {percorso or '(la cartella intera)'}: "
                                 f"{spiegazione}")
        for richiesta, codice in list(estrazione.rifiutate):
            nome = self._nome(richiesta.get("radice", ""))
            righe += ["", f"Cartella {nome}: {RIFIUTI.get(codice, codice)}."]
        righe.append("")
        return "\r\n".join(righe)

    def rapporto(self) -> Path | None:
        if self.dove is None or not self.da_raccontare():
            return None
        if _dentro(self.dove, self.archivio) or not _cartella_vera(self.dove):
            return None
        testo = self.testo_del_rapporto().encode("utf-8-sig")
        for volta in range(1, NOMI_LIBERI + 1):
            percorso = self.dove / con_numero(RAPPORTO, volta)
            try:
                with open(percorso, "xb") as fuori:
                    fuori.write(testo)
            except FileExistsError:
                continue
            except OSError:
                return None
            self.scritto = percorso
            return percorso
        return None

    def chiudi(self) -> None:
        if self.acceso:
            self.ferma(CHIUDI_ENTRO)
        if self.elenco is not None:
            try:
                self.elenco.chiudi()
            except Exception:
                pass
            self.elenco = None


class Regia:

    def __init__(self, archivio=None, dove=None, *, fabbrica=Recupero):
        self._fabbrica = fabbrica
        self._serratura = threading.Lock()
        self.archivio = Path(archivio) if archivio else None
        self.dove = Path(dove) if dove else dove_di_solito()
        self.fase = PASSWORD if self.archivio is not None else CERCA
        self.errore: str | None = None
        self.codice: str | None = None
        self.recupero: Recupero | None = None
        self._filo: threading.Thread | None = None
        self._fermato = False

    def scegli_archivio(self, percorso) -> bool:
        with self._serratura:
            if self.fase not in (CERCA, PASSWORD):
                return False
            trovato = trova(percorso) if percorso else None
            if trovato is None:
                self.errore = ("Qui non c'è un Archivio sicuro: scegli la cartella "
                               "«Archivio sicuro» che sta sulla chiavetta.")
                self.codice = "non_e_un_archivio"
                return False
            if self.archivio != trovato and self.recupero is not None:
                self.recupero.chiudi()
                self.recupero = None
            self.archivio = trovato
            self.errore = self.codice = None
            self.fase = PASSWORD
            return True

    def scegli_dove(self, percorso) -> None:
        if percorso:
            self.dove = Path(percorso)

    def inizia(self, password: str, dove=None) -> bool:
        with self._serratura:
            if self.fase != PASSWORD or self.archivio is None:
                return False
            if dove:
                self.dove = Path(dove)
            self.fase = SBLOCCO
            self.errore = self.codice = None
            self._fermato = False
            self._filo = threading.Thread(target=self._prepara, args=(password,),
                                          name="recupera-foto", daemon=True)
            self._filo.start()
        return True

    def _prepara(self, password: str) -> None:
        senza_finestre_di_errore()
        try:
            recupero = self.recupero
            if recupero is None or recupero.archivio != self.archivio:
                recupero = self._fabbrica(self.archivio)
                with self._serratura:
                    self.recupero = recupero
            recupero.sblocca(password)
            if self._fermato:
                self._indietro(None, None)
                return
            recupero.parti(self.dove)
            with self._serratura:
                self.fase = LAVORO
                fermato = self._fermato
            if fermato:
                recupero.ferma()
            recupero.aspetta_fine()
            recupero.rapporto()
        except ErroreOfficina as guasto:
            self._indietro(guasto.messaggio, guasto.codice)
            return
        except Exception as guasto:
            self._indietro(f"Qualcosa è andato storto: {guasto}",
                           type(guasto).__name__)
            return
        with self._serratura:
            self.fase = FINE

    def _indietro(self, messaggio: str | None, codice: str | None) -> None:
        with self._serratura:
            self.errore = messaggio
            self.codice = codice
            self.fase = PASSWORD

    def ferma(self) -> None:
        with self._serratura:
            self._fermato = True
            recupero = self.recupero
        if recupero is not None:
            recupero.ferma()

    def aspetta(self, quanto: float | None = None) -> bool:
        filo = self._filo
        if filo is not None:
            filo.join(quanto)
        return filo is None or not filo.is_alive()

    def chiudi(self) -> None:
        self.ferma()
        self.aspetta(CHIUDI_ENTRO)
        if self.recupero is not None:
            self.recupero.chiudi()

    def quadro(self) -> dict:
        with self._serratura:
            fase, errore, codice = self.fase, self.errore, self.codice
            recupero = self.recupero
        quadro = {"fase": fase, "errore": errore, "codice": codice,
                  "archivio": str(self.archivio) if self.archivio else None,
                  "dove": str(self.dove), "frazione": None, "testo": "",
                  "percorso": None, "frase": None, "verde": False,
                  "cartella": None, "rapporto": None}
        if recupero is None or not recupero.sbloccato or fase not in (LAVORO, FINE):
            return quadro
        avanzamento = recupero.avanzamento()
        if avanzamento["byte_totali"]:
            frazione = avanzamento["byte"] / avanzamento["byte_totali"]
        elif avanzamento["file_totali"]:
            frazione = avanzamento["file"] / avanzamento["file_totali"]
        else:
            frazione = 1.0
        riassunto = recupero.riassunto()
        quadro.update({
            "frazione": max(0.0, min(1.0, frazione)),
            "testo": (f"{numero(avanzamento['file'])} di "
                      f"{_file(avanzamento['file_totali'])} · "
                      f"{misura(avanzamento['byte'])} di "
                      f"{misura(avanzamento['byte_totali'])}"),
            "percorso": avanzamento["percorso"],
            "frase": riassunto["frase"],
            "verde": riassunto["verde"] and fase == FINE,
            "stato": riassunto["stato"],
            "file": riassunto["file"],
            "rossi": riassunto["rossi"],
            "cartella": str(recupero.dove) if recupero.dove else None,
            "rapporto": str(recupero.scritto) if recupero.scritto else None,
        })
        return quadro


def _corto(testo: str | None, quanto: int = 64) -> str:
    if not testo:
        return ""
    return testo if len(testo) <= quanto else "…" + testo[-(quanto - 1):]


def _nitida() -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        pass


def apri_cartella(percorso) -> None:
    try:
        if sys.platform == "win32":
            os.startfile(os.fspath(percorso))
        else:
            subprocess.Popen(["xdg-open", os.fspath(percorso)])
    except OSError:
        pass


class Finestra:

    def __init__(self, regia: Regia):
        import tkinter as tk
        from tkinter import ttk

        _nitida()
        self.regia = regia
        self.tk = tk
        self.finita = False
        radice = self.radice = tk.Tk()
        radice.title("Recupera foto")
        radice.configure(bg=FONDO)
        radice.minsize(520, 0)
        self._icona()
        carattere = "Segoe UI" if sys.platform == "win32" else "Helvetica"
        self.caratteri = {"titolo": (carattere, 17, "bold"), "testo": (carattere, 10),
                          "piccolo": (carattere, 9), "tasto": (carattere, 11, "bold")}
        stile = ttk.Style(radice)
        try:
            stile.theme_use("clam")
        except tk.TclError:
            pass
        stile.configure("Recupero.Horizontal.TProgressbar", troughcolor=CARTA,
                        background=ACCENTO, bordercolor=CARTA, lightcolor=ACCENTO,
                        darkcolor=ACCENTO, thickness=10)
        telaio = tk.Frame(radice, bg=FONDO, padx=28, pady=24)
        telaio.pack(fill="both", expand=True)
        telaio.columnconfigure(0, weight=1)
        self.telaio = telaio
        self._etichetta(telaio, "Recupera foto", "titolo", INK).grid(
            row=0, column=0, columnspan=2, sticky="w")
        self._etichetta(
            telaio, "Tira fuori le foto e i video dall'Archivio sicuro. Sulla "
            "chiavetta non viene scritto niente.", "testo", TENUE, a_capo=True).grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(4, 18))
        self._etichetta(telaio, "ARCHIVIO", "piccolo", TENUE).grid(
            row=2, column=0, columnspan=2, sticky="w")
        self.archivio = self._etichetta(telaio, "", "testo", INK, a_capo=True)
        self.archivio.grid(row=3, column=0, sticky="we", pady=(2, 12))
        self.cambia = self._tasto(telaio, "Cambia…", self._scegli_archivio)
        self.cambia.grid(row=3, column=1, sticky="e", padx=(12, 0), pady=(2, 12))
        self._etichetta(telaio, "PASSWORD", "piccolo", TENUE).grid(
            row=4, column=0, columnspan=2, sticky="w")
        self.password = self._campo(telaio, mostra="●")
        self.password.grid(row=5, column=0, columnspan=2, sticky="we", pady=(2, 12),
                           ipady=5)
        self.password.bind("<Return>", lambda _evento: self._via())
        self._etichetta(telaio, "DOVE METTERLE", "piccolo", TENUE).grid(
            row=6, column=0, columnspan=2, sticky="w")
        self.dove = self._campo(telaio)
        self.dove.insert(0, str(regia.dove))
        self.dove.grid(row=7, column=0, sticky="we", pady=(2, 4), ipady=5)
        self.scegli = self._tasto(telaio, "Scegli…", self._scegli_dove)
        self.scegli.grid(row=7, column=1, sticky="e", padx=(12, 0), pady=(2, 4))
        self._etichetta(telaio, "Dentro questa cartella ne nasce una per ogni "
                        "cartella dell'archivio.", "piccolo", TENUE,
                        a_capo=True).grid(row=8, column=0, columnspan=2, sticky="w")
        self.errore = self._etichetta(telaio, "", "testo", MALE, a_capo=True)
        self.errore.grid(row=9, column=0, columnspan=2, sticky="we", pady=(10, 0))
        self.via = self._tasto(telaio, "Tira fuori tutto", self._via, forte=True)
        self.via.grid(row=10, column=0, columnspan=2, sticky="we", pady=(14, 0))
        self.barra = ttk.Progressbar(telaio, style="Recupero.Horizontal.TProgressbar",
                                     mode="determinate", maximum=1000)
        self.conto = self._etichetta(telaio, "", "testo", INK)
        self.percorso = self._etichetta(telaio, "", "piccolo", TENUE)
        self.ferma = self._tasto(telaio, "Ferma", self._ferma)
        self.frase = self._etichetta(telaio, "", "testo", INK, a_capo=True)
        self.apri = self._tasto(telaio, "Apri la cartella", self._apri, forte=True)
        self.chiudi = self._tasto(telaio, "Chiudi", self._chiudi)
        self._lavoro = (self.barra, self.conto, self.percorso, self.ferma)
        self._fine = (self.frase, self.apri, self.chiudi)
        radice.protocol("WM_DELETE_WINDOW", self._chiudi)
        self._fase = None
        self._aggiorna()
        self.password.focus_set()

    def _icona(self) -> None:
        candidati = []
        base = getattr(sys, "_MEIPASS", None)
        if base:
            candidati.append(Path(base) / "officina.ico")
        candidati.append(Path(__file__).resolve().parent.parent / "web" / "statici"
                         / "officina.ico")
        for candidato in candidati:
            try:
                if candidato.is_file():
                    self.radice.iconbitmap(default=str(candidato))
                    return
            except self.tk.TclError:
                continue

    def _etichetta(self, dentro, testo: str, carattere: str, colore: str,
                   a_capo: bool = False):
        etichetta = self.tk.Label(dentro, text=testo, bg=FONDO, fg=colore,
                                  font=self.caratteri[carattere], anchor="w",
                                  justify="left")
        if a_capo:
            etichetta.configure(wraplength=480)
        return etichetta

    def _campo(self, dentro, mostra: str | None = None):
        campo = self.tk.Entry(dentro, bg=CARTA, fg=INK, insertbackground=INK,
                              relief="flat", highlightthickness=1,
                              highlightbackground=LINEA, highlightcolor=ACCENTO,
                              font=self.caratteri["testo"])
        if mostra:
            campo.configure(show=mostra)
        return campo

    def _tasto(self, dentro, testo: str, azione, forte: bool = False):
        fondo, scritta = (ACCENTO, SU_ACCENTO) if forte else (CARTA, INK)
        return self.tk.Button(dentro, text=testo, command=azione, bg=fondo, fg=scritta,
                              activebackground=fondo, activeforeground=scritta,
                              relief="flat", bd=0, padx=14, pady=7, cursor="hand2",
                              font=self.caratteri["tasto" if forte else "testo"],
                              disabledforeground=TENUE)

    def _scegli_archivio(self) -> None:
        from tkinter import filedialog

        scelta = filedialog.askdirectory(
            parent=self.radice, mustexist=True,
            title="Dov'è la cartella «Archivio sicuro»?")
        if scelta:
            self.regia.scegli_archivio(scelta)

    def _scegli_dove(self) -> None:
        from tkinter import filedialog

        scelta = filedialog.askdirectory(parent=self.radice,
                                         title="Dove metto le foto recuperate?")
        if scelta:
            self.dove.delete(0, "end")
            self.dove.insert(0, os.path.normpath(scelta))

    def _via(self) -> None:
        dove = self.dove.get().strip()
        if not dove:
            self.errore.configure(text="Scegli dove mettere le foto.")
            return
        self.regia.inizia(self.password.get(), dove)
        self._aggiorna(subito=True)

    def _ferma(self) -> None:
        self.regia.ferma()

    def _apri(self) -> None:
        cartella = self.regia.quadro().get("cartella")
        if cartella:
            apri_cartella(cartella)

    def _chiudi(self) -> None:
        if self.regia.fase in (SBLOCCO, LAVORO):
            from tkinter import messagebox

            if not messagebox.askyesno(
                    "Fermare il recupero?",
                    "Sto ancora tirando fuori le foto. Se chiudi adesso mi fermo: "
                    "quello che è già uscito resta. Chiudo lo stesso?",
                    parent=self.radice, icon="warning"):
                return
        self.regia.chiudi()
        self.finita = True
        self.radice.destroy()

    def _mostra(self, quali, righe) -> None:
        for widget, (riga, opzioni) in zip(quali, righe):
            widget.grid(row=riga, column=0, columnspan=2, **opzioni)

    def _nascondi(self, quali) -> None:
        for widget in quali:
            widget.grid_remove()

    def _cambia_fase(self, fase: str) -> None:
        self._fase = fase
        modificabile = fase in (CERCA, PASSWORD)
        stato = "normal" if modificabile else "disabled"
        for widget in (self.password, self.dove, self.scegli, self.cambia):
            widget.configure(state=stato)
        self.via.configure(state="normal" if fase == PASSWORD else "disabled",
                           text="Apro l'archivio…" if fase == SBLOCCO
                           else "Tira fuori tutto")
        if fase in (LAVORO, FINE):
            self.via.grid_remove()
            self._mostra(self._lavoro, [
                (11, {"sticky": "we", "pady": (16, 6)}),
                (12, {"sticky": "w"}),
                (13, {"sticky": "w", "pady": (2, 0)}),
                (14, {"sticky": "e", "pady": (12, 0)})])
        else:
            self.via.grid()
            self._nascondi(self._lavoro)
        if fase == FINE:
            self.ferma.grid_remove()
            self.percorso.grid_remove()
            self._mostra(self._fine, [
                (15, {"sticky": "we", "pady": (16, 0)}),
                (16, {"sticky": "we", "pady": (14, 0)}),
                (17, {"sticky": "we", "pady": (8, 0)})])
        else:
            self._nascondi(self._fine)
        if fase == PASSWORD:
            self.password.focus_set()
            self.password.select_range(0, "end")

    def _aggiorna(self, subito: bool = False) -> None:
        if self.finita:
            return
        quadro = self.regia.quadro()
        fase = quadro["fase"]
        if fase != self._fase:
            self._cambia_fase(fase)
        if quadro["archivio"]:
            self.archivio.configure(text=_corto(quadro["archivio"], 70), fg=INK)
        else:
            self.archivio.configure(
                text="Non l'ho trovato qui accanto: premi «Cambia…» e scegli la "
                     "cartella «Archivio sicuro» della chiavetta.", fg=TENUE)
        self.errore.configure(text=quadro["errore"] or "")
        if fase in (LAVORO, FINE):
            self.barra.configure(value=int((quadro["frazione"] or 0) * 1000))
            self.conto.configure(text=quadro["testo"])
            self.percorso.configure(text=_corto(quadro["percorso"]))
        if fase == FINE:
            self.frase.configure(text=quadro["frase"] or "",
                                 fg=BENE if quadro["verde"] else INK)
        if not subito:
            self.radice.after(OGNI, self._aggiorna)

    def gira(self) -> None:
        self.radice.mainloop()


def _scrivi_esito(percorso: Path, esito: dict) -> None:
    provvisorio = percorso.with_name(percorso.name + ".nuovo")
    provvisorio.write_text(json.dumps(esito, ensure_ascii=False, indent=1), "utf-8")
    os.replace(provvisorio, percorso)


def _collaudo_in_finestra(regia: Regia, richiesta: dict, esito: dict) -> None:
    limite = time.monotonic() + float(richiesta.get("attesa", 3600))
    finestra = Finestra(regia)
    visti: list[str] = []
    premuto = []

    def chiudi(finito: bool) -> None:
        try:
            esito["fasi_viste"] = visti
            esito["scritte"] = {"frase": finestra.frase.cget("text"),
                                "conto": finestra.conto.cget("text"),
                                "errore": finestra.errore.cget("text"),
                                "archivio": finestra.archivio.cget("text")}
            esito["tasto_apri"] = bool(finestra.apri.winfo_ismapped())
            esito["scaduto"] = not finito
        except Exception as guasto:
            esito["eccezione"] = f"{type(guasto).__name__}: {guasto}"
        finally:
            regia.chiudi()
            finestra.finita = True
            finestra.radice.destroy()

    def passo() -> None:
        try:
            quadro = regia.quadro()
            if not visti or visti[-1] != quadro["fase"]:
                visti.append(quadro["fase"])
            if quadro["fase"] == PASSWORD and not premuto:
                premuto.append(True)
                finestra.password.insert(0, richiesta.get("password", ""))
                if richiesta.get("dove"):
                    finestra.dove.delete(0, "end")
                    finestra.dove.insert(0, richiesta["dove"])
                finestra.via.invoke()
                finestra.radice.after(OGNI, passo)
                return
            finito = quadro["fase"] in (FINE, CERCA) or (
                quadro["fase"] == PASSWORD and regia.aspetta(0))
            if finito or time.monotonic() > limite:
                finestra._aggiorna(subito=True)
                finestra.radice.after(OGNI, lambda: chiudi(finito))
                return
        except Exception as guasto:
            esito["eccezione"] = f"{type(guasto).__name__}: {guasto}"
            chiudi(False)
            return
        finestra.radice.after(OGNI, passo)

    finestra.radice.after(OGNI, passo)
    finestra.gira()


def collaudo(percorso) -> int:
    try:
        richiesta = json.loads(Path(percorso).read_text("utf-8"))
        risultato = Path(richiesta["risultato"])
    except (OSError, ValueError, KeyError, TypeError):
        return 3
    esito: dict = {"frozen": bool(getattr(sys, "frozen", False)),
                   "accanto": str(accanto())}
    try:
        archivio = (Path(richiesta["archivio"]) if richiesta.get("archivio")
                    else trova(accanto()))
        regia = Regia(archivio, richiesta.get("dove"))
        if richiesta.get("finestra"):
            _collaudo_in_finestra(regia, richiesta, esito)
        else:
            regia.inizia(richiesta.get("password", ""))
            regia.aspetta(float(richiesta.get("attesa", 3600)))
            if regia.fase not in (FINE, PASSWORD):
                regia.chiudi()
        esito.update(regia.quadro())
        if regia.recupero is not None:
            esito["riassunto"] = regia.recupero.riassunto()
            regia.recupero.chiudi()
    except Exception as guasto:
        esito["eccezione"] = f"{type(guasto).__name__}: {guasto}"
    _scrivi_esito(risultato, esito)
    if esito.get("eccezione"):
        return 3
    if esito.get("verde"):
        return 0
    return 1 if esito.get("fase") == FINE else 2


def principale(argv=None) -> int:
    argomenti = list(sys.argv[1:] if argv is None else argv)
    senza_finestre_di_errore()
    if len(argomenti) >= 2 and argomenti[0] == "--collaudo":
        return collaudo(argomenti[1])
    liberi = [argomento for argomento in argomenti if not argomento.startswith("-")]
    archivio = trova(liberi[0]) if liberi else None
    if archivio is None:
        archivio = trova(accanto())
    regia = Regia(archivio)
    Finestra(regia).gira()
    return 0


if __name__ == "__main__":
    sys.exit(principale())
