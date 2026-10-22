from __future__ import annotations

import threading
import time
from pathlib import Path

from officina import forziere, registro
from officina.errori import ErroreOfficina, PasswordSbagliata
from officina.programma import carta

MESE = 30 * 24 * 3600
ASPETTA_ALLA_CHIUSURA = 20.0
USATO_DA_POCO = 30.0

ASSENTE = "assente"
SENZA_CHIAVE = "senza_chiave"
CHIUSO = "chiuso"
SI_APRE = "si_apre"
APERTO = "aperto"
PASSWORD_DIVERSA = "password_diversa"
GUASTO = "guasto"
DA_RICORDARE = (SI_APRE, PASSWORD_DIVERSA, GUASTO)

SCRITTA_IL = "sicuro_password_scritta_il"
PRIMA_COPIA = "sicuro_prima_copia"
CAMBIO = "sicuro_cambio_password"
VALE_LA_VECCHIA = "vecchia"
NON_SI_SA = "a_meta"
VALE_LA_NUOVA = "nuova"

OGGI_NIENTE_HELLO = (
    "Oggi niente Windows Hello: una volta al mese la password si scrive a mano, "
    "così non la dimentichi. Senza di lei l'Archivio sicuro non si apre più.")
SERVE_IL_FORZIERE = (
    "Finché c'è l'Archivio sicuro il forziere resta acceso: la password è una "
    "sola per tutti e due. Non ho spento niente.")
PASSWORD_DIVERSA_A_PAROLE = (
    "La password del forziere non apre l'Archivio sicuro. Scrivi la password "
    "dell'archivio: appena si apre, le due password tornano uguali. Finché non "
    "la scrivi, l'archivio non copia e non lascia cancellare niente.")
SENZA_CHIAVE_A_PAROLE = (
    "Nella cartella dell'Archivio sicuro ci sono dei file, ma manca il file con "
    "la chiave. Non tocco niente: attacca la chiavetta dell'archivio, che ne ha "
    "una copia.")
CHIUSO_A_PAROLE = "L'Archivio sicuro è chiuso: scrivi la sua password per aprirlo."
ASSENTE_A_PAROLE = "L'Archivio sicuro non c'è ancora."
NON_SI_APRE = (
    "L'Archivio sicuro non si è aperto per un guasto che non avevo previsto. "
    "Non ho toccato niente: chiudi il programma e riaprilo.")
CARTELLA_NON_SI_LEGGE = (
    "Non riesco a leggere la cartella dell'Archivio sicuro. Non tocco niente: "
    "controlla che il disco ci sia e riprova.")
SI_STA_CHIUDENDO = "Il programma si sta chiudendo: riprova quando si riapre."
SOLO_NEL_VERO = (
    "Adesso è aperto l'archivio di prova: l'Archivio sicuro e la sua password si "
    "toccano solo dal tuo archivio vero. Torna al tuo archivio e riprova. Non ho "
    "toccato niente.")
SENZA_HO_CAPITO = (
    "Prima leggi il riquadro rosso e premi «Ho capito»: senza la password le "
    "foto non si aprono più, e non c'è una chiave di riserva.")
NON_COINCIDONO = "Le due password non coincidono. Non ho toccato niente."
NON_E_QUELLA_DEL_FORZIERE = (
    "Questa non è la password del forziere. L'Archivio sicuro usa la stessa: "
    "scrivi quella. Non ho toccato niente.")
FORZIERE_CORTA = (
    "La password del forziere è giusta, ma per l'Archivio sicuro ne serve una di "
    "almeno dodici caratteri. Prima cambia la password, poi crea l'archivio.")
FORZIERE_NON_ACCESO = (
    "Il forziere non si è acceso, quindi non ho creato l'Archivio sicuro. Non ho "
    "toccato niente.")
SENZA_FORZIERE = "Il forziere è spento: non c'è una password da cambiare."
PRIMA_APRILO = (
    "Prima deve essere aperto l'Archivio sicuro: la password si cambia insieme, "
    "nel forziere e nell'archivio. Non ho cambiato niente.")
ADESSO_SBAGLIATA = "La password di adesso non è giusta. Non ho cambiato niente."
NUOVA_UGUALE = "La password nuova è uguale a quella di adesso. Non ho cambiato niente."
NON_CAMBIATA = (
    "Non sono riuscito a richiudere il forziere con la password nuova. Non ho "
    "cambiato niente: vale ancora quella di prima.")
RIAPRI_CON_LA_VECCHIA = (
    "Non sono riuscito a cambiare la password, e il forziere non si è riaperto. "
    "Chiudi il programma e riaprilo con la password di prima: vale ancora quella.")
RIAPRI_CON_LA_NUOVA = (
    "La password è cambiata, ma il forziere non si è riaperto. Chiudi il "
    "programma e riaprilo con la password nuova.")
A_META = (
    "Il cambio della password si è fermato a metà e non riesco a capire quale "
    "vale. Chiudi il programma e riaprilo: prova prima la password nuova e, se "
    "non va, quella di prima. L'Archivio sicuro si apre con tutte e due.")

PERCHE = {
    ASSENTE: (ASSENTE_A_PAROLE, "sicuro_mancante"),
    SENZA_CHIAVE: (SENZA_CHIAVE_A_PAROLE, "senza_chiave"),
    CHIUSO: (CHIUSO_A_PAROLE, "chiuso"),
    GUASTO: (CARTELLA_NON_SI_LEGGE, "cartella_non_si_legge"),
}

NOMI_DEI_TUOI = {
    "via_libera": "il controllo per il via libera",
    "cestino": "lo spostamento nel Cestino",
    "ricontrollo": "il ricontrollo dopo il Cestino",
    "estrai": "un'estrazione",
    "prova": "l'estrazione di prova",
    "verifica": "il controllo «È già tutto dentro?»",
    "ripara": "una riparazione",
}
PRIMA_COPIA_A_PAROLE = "la prima copia"


def cartella(posizione) -> Path:
    return Path(posizione.radice).parent / f"{posizione.nome}.sicuro"


def c_e(posizione) -> bool:
    from officina.sicuro import chiavi
    from officina.sicuro.servizio import ArchivioSicuro

    dove = cartella(posizione)
    try:
        return chiavi.esiste(dove) or ArchivioSicuro(dove).ha_qualcosa
    except OSError:
        return True


def serve_la_password_scritta(posizione, adesso: float | None = None) -> bool:
    if not c_e(posizione):
        return False
    scritta = carta.leggi().get(SCRITTA_IL)
    if isinstance(scritta, bool) or not isinstance(scritta, (int, float)):
        return True
    passato = (time.time() if adesso is None else adesso) - scritta
    return not 0 <= passato < MESE


def password_scritta(adesso: float | None = None) -> None:
    carta.aggiorna(**{SCRITTA_IL: time.time() if adesso is None else adesso})


def cambio_lasciato() -> str | None:
    scritto = carta.leggi().get(CAMBIO)
    return scritto if scritto in (VALE_LA_VECCHIA, NON_SI_SA, VALE_LA_NUOVA) else None


def _ricorda_il_cambio(come: str | None) -> None:
    carta.aggiorna(**{CAMBIO: come})


def _segna_il_cambio(come: str | None) -> None:
    try:
        _ricorda_il_cambio(come)
    except OSError as guasto:
        registro.avviso("sicuro.cambio_non_segnato", **registro.dove_si_e_rotto(guasto))


def _segna_la_password_scritta() -> None:
    try:
        password_scritta()
    except OSError as guasto:
        registro.avviso("sicuro.password_non_segnata", **registro.dove_si_e_rotto(guasto))


def dimentica_il_cambio() -> None:
    if CAMBIO in carta.leggi():
        _ricorda_il_cambio(None)


def programmino() -> Path | None:
    import officina
    from officina.programma import librerie
    from officina.sicuro.chiavetta import PROGRAMMINO

    percorso = Path(officina.__file__).resolve().parent.parent / "strumenti" / PROGRAMMINO
    if percorso.is_file() or librerie.e_il_programma_installato():
        return percorso
    return None


def stai_usando() -> bool:
    from officina.web import blocco

    return blocco.guardia.usato_da_poco(USATO_DA_POCO)


def prima_copia_segnata() -> bool:
    return bool(_lista(carta.leggi().get(PRIMA_COPIA)))


def _di_serie(dove: Path, salta, programmino):
    from officina.sicuro.servizio import ArchivioSicuro

    return ArchivioSicuro(dove, salta=salta, programmino=programmino, rallenta=stai_usando)


def _lista(valore) -> list[str]:
    if not isinstance(valore, list):
        return []
    return [voce for voce in valore if isinstance(voce, str)]


class Collegamento:

    def __init__(self, posizione, fabbrica=_di_serie):
        self.posizione = posizione
        self.cartella = cartella(posizione)
        self._fabbrica = fabbrica
        self._serratura = threading.RLock()
        self._filo: threading.Thread | None = None
        self._servizio = None
        self._finito = False
        self.stato = ASSENTE
        self.messaggio = ""
        self.codice = ""

    @property
    def servizio(self):
        with self._serratura:
            if self._servizio is None:
                from officina.sicuro import servizio

                self._servizio = self._fabbrica(self.cartella, self._da_saltare(),
                                                programmino())
                servizio.imposta(self._servizio)
            return self._servizio

    def _da_saltare(self) -> tuple[Path, ...]:
        return (Path(self.posizione.radice).parent, carta.casa())

    def _segna(self, stato: str, messaggio: str = "", codice: str = "") -> None:
        with self._serratura:
            self.stato, self.messaggio, self.codice = stato, messaggio, codice

    def _segna_dal_disco(self, stato: str) -> None:
        self._segna(stato, *PERCHE.get(stato, ("", "")))

    def _servizio_aperto(self) -> bool:
        return self._servizio is not None and self._servizio.aperto

    def _apre(self) -> bool:
        filo = self._filo
        return filo is not None and filo.is_alive()

    def _non_finito(self) -> None:
        if self._finito:
            raise ErroreOfficina(SI_STA_CHIUDENDO, codice="si_chiude")

    def _aspetta_l_apertura(self, quanto: float | None = None) -> None:
        filo = self._filo
        if filo is not None and filo is not threading.current_thread():
            filo.join(quanto)

    def _dal_disco(self) -> str:
        from officina.sicuro import chiavi

        try:
            if chiavi.esiste(self.cartella):
                return CHIUSO
            return SENZA_CHIAVE if self.servizio.ha_qualcosa else ASSENTE
        except OSError:
            return GUASTO

    def guarda(self) -> str:
        with self._serratura:
            if self._servizio_aperto():
                self._segna(APERTO)
            elif self.stato not in DA_RICORDARE or (self.stato == SI_APRE
                                                     and not self._apre()):
                self._segna_dal_disco(self._dal_disco())
            return self.stato

    def apri_in_sottofondo(self, password: str | None) -> str:
        with self._serratura:
            if (self._finito or self._servizio_aperto() or self._apre()
                    or self.stato in (PASSWORD_DIVERSA, GUASTO)):
                return self.guarda()
            stato = self._dal_disco()
            if stato != CHIUSO or not password:
                self._segna_dal_disco(stato)
                return stato
            self._segna(SI_APRE)
            self._filo = threading.Thread(target=self._apri, args=(password,),
                                          name="archivio-sicuro-apertura", daemon=True)
            self._filo.start()
            return SI_APRE

    def _apri(self, password: str) -> None:
        try:
            self.servizio.apri(password)
        except PasswordSbagliata:
            registro.avviso("sicuro.password_diversa")
            self._segna(PASSWORD_DIVERSA, PASSWORD_DIVERSA_A_PAROLE, "password_diversa")
        except ErroreOfficina as errore:
            registro.avviso("sicuro.non_aperto", motivo=registro.Parola(errore.codice))
            self._segna(GUASTO, errore.messaggio, errore.codice)
        except OSError as guasto:
            registro.avviso("sicuro.cartella_non_letta", **registro.dove_si_e_rotto(guasto))
            self._segna(GUASTO, CARTELLA_NON_SI_LEGGE, "cartella_non_si_legge")
        except Exception as guasto:
            registro.errore("sicuro.apertura_rotta", **registro.dove_si_e_rotto(guasto))
            self._segna(GUASTO, NON_SI_APRE, "apertura_rotta")
        else:
            with self._serratura:
                if not self._finito:
                    registro.evento("sicuro.aperto")
                    self._segna(APERTO)
                    return
            registro.evento("sicuro.aperto_mentre_si_chiude")
            self._segna(CHIUSO)
            self.servizio.chiudi(ASPETTA_ALLA_CHIUSURA)

    def riprova(self, password: str | None) -> str:
        self._aspetta_l_apertura()
        with self._serratura:
            if self.stato in (PASSWORD_DIVERSA, GUASTO):
                self._segna(CHIUSO)
        return self.apri_in_sottofondo(password)

    def apri_con_la_password(self, password: str, del_forziere: str | None) -> list[str]:
        self._aspetta_l_apertura()
        with self._serratura:
            self._non_finito()
            if self._servizio_aperto():
                return list(self.servizio.problemi)
            stato = self._dal_disco()
            if stato != CHIUSO:
                self._segna_dal_disco(stato)
                raise ErroreOfficina(*PERCHE[stato])
            riallinea = bool(del_forziere) and del_forziere != password
            try:
                self.servizio.apri(password, pulisci=not riallinea)
            except PasswordSbagliata:
                raise
            except ErroreOfficina as errore:
                self._segna(GUASTO, errore.messaggio, errore.codice)
                raise
            except OSError as errore:
                self._segna(GUASTO, CARTELLA_NON_SI_LEGGE, "cartella_non_si_legge")
                raise ErroreOfficina(CARTELLA_NON_SI_LEGGE,
                                     codice="cartella_non_si_legge") from errore
            registro.evento("sicuro.aperto_a_mano")
            self._segna(APERTO)
            _segna_la_password_scritta()
            if riallinea:
                self._riallinea(del_forziere)
            return list(self.servizio.problemi)

    def _riallinea(self, del_forziere: str) -> None:
        servizio = self.servizio
        try:
            servizio.aggiungi_password(del_forziere)
        except ErroreOfficina as errore:
            servizio.problemi.append("forziere_corta" if errore.codice == "password_corta"
                                     else "password_non_riallineata")
            return
        except OSError:
            servizio.problemi.append("password_non_riallineata")
            return
        try:
            servizio.tieni_solo(del_forziere)
        except (ErroreOfficina, OSError):
            servizio.problemi.append("password_vecchia_ancora_buona")
        registro.evento("sicuro.password_riallineata")

    def crea(self, password: str, ancora: str, ho_capito: bool, *,
             accendi_il_forziere) -> None:
        from officina.sicuro import chiavi

        if not ho_capito:
            raise ErroreOfficina(SENZA_HO_CAPITO, codice="manca_ho_capito")
        if password != ancora:
            raise ErroreOfficina(NON_COINCIDONO, codice="non_coincidono")
        self._aspetta_l_apertura()
        with self._serratura:
            self._non_finito()
            stato = APERTO if self._servizio_aperto() else self._dal_disco()
            if stato != ASSENTE:
                if stato in (CHIUSO, APERTO):
                    raise ErroreOfficina("L'Archivio sicuro c'è già.",
                                         codice="chiave_esiste")
                self._segna_dal_disco(stato)
                raise ErroreOfficina(*PERCHE[stato])
            cassa = forziere.per(self.posizione)
            if cassa.acceso:
                if not cassa.la_password_e_giusta(password):
                    raise ErroreOfficina(NON_E_QUELLA_DEL_FORZIERE,
                                         codice="non_e_quella_del_forziere")
                try:
                    chiavi.password_nuova_valida(password)
                except ErroreOfficina as errore:
                    raise ErroreOfficina(FORZIERE_CORTA, codice="forziere_corta") from errore
            else:
                chiavi.password_nuova_valida(password)
                accendi_il_forziere(password)
                if not (cassa.acceso and cassa.la_password_e_giusta(password)):
                    raise ErroreOfficina(FORZIERE_NON_ACCESO, codice="forziere_non_acceso")
            try:
                self.servizio.crea(password)
            except BaseException:
                self._segna_dal_disco(self._dal_disco())
                raise
            registro.evento("sicuro.creato")
            self._segna(APERTO)
            _segna_la_password_scritta()

    def cambia_la_password(self, vecchia: str, nuova: str, ancora: str, *,
                           richiudi, rimetti, sigilla) -> list[str]:
        from officina.sicuro import chiavi

        if nuova != ancora:
            raise ErroreOfficina(NON_COINCIDONO, codice="non_coincidono")
        if nuova == vecchia:
            raise ErroreOfficina(NUOVA_UGUALE, codice="uguale")
        chiavi.password_nuova_valida(nuova)
        self._aspetta_l_apertura()
        with self._serratura:
            self._non_finito()
            cassa = forziere.per(self.posizione)
            if not cassa.acceso:
                raise ErroreOfficina(SENZA_FORZIERE, codice="forziere_spento")
            if not cassa.la_password_e_giusta(vecchia):
                raise PasswordSbagliata(ADESSO_SBAGLIATA)
            aperto = self._servizio_aperto()
            con_archivio = aperto or self._dal_disco() != ASSENTE
            if con_archivio and not aperto:
                raise ErroreOfficina(PRIMA_APRILO, codice="sicuro_chiuso")
            prima = chiavi.porte(self.cartella) if con_archivio else 0
            _ricorda_il_cambio(VALE_LA_VECCHIA)
            if con_archivio:
                try:
                    self.servizio.aggiungi_password(nuova)
                except BaseException:
                    self._togli_la_nuova(vecchia, prima)
                    _segna_il_cambio(None)
                    raise
            _segna_il_cambio(NON_SI_SA)
            guasto = None
            try:
                richiudi(nuova)
            except Exception as errore:
                registro.errore("sicuro.forziere_non_richiuso",
                                **registro.dove_si_e_rotto(errore))
                guasto = errore
            if cassa.la_password_e_giusta(nuova):
                return self._finisci_il_cambio(nuova, con_archivio, guasto, sigilla)
            if cassa.la_password_e_giusta(vecchia):
                self._torna_alla_vecchia(vecchia, prima if con_archivio else None, rimetti)
            registro.errore("sicuro.cambio_a_meta")
            raise ErroreOfficina(A_META, codice="cambio_a_meta")

    def _togli_la_nuova(self, vecchia: str, prima: int) -> None:
        from officina.sicuro import chiavi

        try:
            if chiavi.porte(self.cartella) > prima:
                self.servizio.tieni_solo(vecchia)
        except (ErroreOfficina, OSError):
            self.servizio.problemi.append("password_nuova_ancora_buona")

    def _finisci_il_cambio(self, nuova: str, con_archivio: bool, guasto,
                           sigilla) -> list[str]:
        _segna_il_cambio(VALE_LA_NUOVA)
        avvisi = []
        try:
            sigilla(nuova)
        except Exception as errore:
            registro.errore("sicuro.sigillo_non_rifatto", **registro.dove_si_e_rotto(errore))
            avvisi.append("windows_da_rifare")
        if con_archivio:
            try:
                self.servizio.tieni_solo(nuova)
            except (ErroreOfficina, OSError):
                avvisi.append("password_vecchia_ancora_buona")
        _segna_la_password_scritta()
        registro.evento("sicuro.password_cambiata", con_archivio=con_archivio)
        if guasto is not None:
            raise ErroreOfficina(RIAPRI_CON_LA_NUOVA, codice="forziere_non_riaperto")
        _segna_il_cambio(None)
        return avvisi

    def _torna_alla_vecchia(self, vecchia: str, prima: int | None, rimetti) -> None:
        if prima is not None:
            self._togli_la_nuova(vecchia, prima)
        _segna_il_cambio(None)
        try:
            rimetti(vecchia)
        except Exception as errore:
            registro.errore("sicuro.forziere_non_riaperto",
                            **registro.dove_si_e_rotto(errore))
            raise ErroreOfficina(RIAPRI_CON_LA_VECCHIA,
                                 codice="forziere_non_riaperto") from errore
        raise ErroreOfficina(NON_CAMBIATA, codice="forziere_non_richiuso")

    def copia_tutto(self, percorsi, grandezze: dict[str, int] | None = None) -> list[dict]:
        nuove = self.servizio.copia_tutto(percorsi, grandezze)
        if nuove:
            segnate = set(_lista(carta.leggi().get(PRIMA_COPIA)))
            segnate.update(radice["id"] for radice in nuove)
            self._segna_la_prima_copia(segnate)
        return nuove

    @staticmethod
    def _segna_la_prima_copia(segnate: set[str]) -> None:
        try:
            carta.aggiorna(**{PRIMA_COPIA: sorted(segnate) or None})
        except OSError as guasto:
            registro.avviso("sicuro.prima_copia_non_segnata",
                            **registro.dove_si_e_rotto(guasto))

    def prima_copia_in_corso(self) -> bool:
        if not self._servizio_aperto():
            return False
        segnate = set(_lista(carta.leggi().get(PRIMA_COPIA)))
        if not segnate:
            return False
        da_finire = self._servizio.da_finire()
        if da_finire is None:
            return False
        restano = segnate & da_finire
        if restano != segnate:
            self._segna_la_prima_copia(restano)
        return bool(restano)

    def serve_la_sosta(self) -> bool | None:
        with self._serratura:
            if self._finito:
                return None
            if not self._servizio_aperto():
                return None if self.guarda() == SI_APRE else False
        voluta = self._servizio.copia_voluta()
        return voluta and self.prima_copia_in_corso()

    def lavori_tuoi(self) -> list[str]:
        if not self._servizio_aperto():
            return []
        nomi = [NOMI_DEI_TUOI.get(nome, nome) for nome in self._servizio.tuoi_accesi()]
        if self.prima_copia_in_corso():
            nomi.insert(0, PRIMA_COPIA_A_PAROLE)
        return nomi

    def chiudi(self, aspetta: float = ASPETTA_ALLA_CHIUSURA) -> bool:
        from officina.sicuro import servizio as modulo

        fine = time.monotonic() + max(0.0, aspetta)
        with self._serratura:
            self._finito = True
        self._aspetta_l_apertura(max(0.0, fine - time.monotonic()))
        servizio = self._servizio
        if servizio is None:
            return True
        fatto = servizio.chiudi(max(0.0, fine - time.monotonic()))
        if modulo.attuale() is servizio:
            modulo.imposta(None)
        registro.evento("sicuro.chiuso", fermo=fatto)
        self.guarda()
        return fatto

    def istantanea(self) -> dict:
        fuori = {"stato": self.guarda(), "messaggio": self.messaggio, "codice": self.codice,
                 "prima_copia": self.prima_copia_in_corso(),
                 "password_del_mese": serve_la_password_scritta(self.posizione),
                 "cambio_lasciato": cambio_lasciato()}
        if self._servizio is not None:
            fuori["archivio"] = self._servizio.istantanea()
        return fuori
