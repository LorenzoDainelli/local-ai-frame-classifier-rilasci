from __future__ import annotations

import errno
import io
import json
import threading
from dataclasses import dataclass, field
from pathlib import Path

from officina import VERSIONE, registro
from officina.archivio.accesso import Archivio
from officina.archivio.database import tutti
from officina.errori import ErroreOfficina, FileNonLeggibile, SpazioInsufficiente
from officina.modello import file_media, telefoni
from officina.telefono import cifratura, dati, formato, ritorno, selezione

LATO_MINIATURA = 640
LATO_VOLTO = 320
QUALITA = 84
A_GRUPPI = 64


@dataclass
class Compito:
    posto: str
    genere: str
    impronta: str = ""
    dimensione: int = 0
    sorgente: Path | None = None
    scatto_id: int | None = None
    file_id: int | None = None
    persona_id: int | None = None
    cache: str | None = None
    riquadro: str = ""
    e_video: bool = False
    identita: str = ""


@dataclass
class Saltato:
    posto: str
    perche: str


@dataclass
class Piano:
    telefono: str
    cartella: Path
    scelta: selezione.Selezione
    posti: list = field(default_factory=list)
    da_scrivere: list = field(default_factory=list)
    da_togliere: list = field(default_factory=list)
    gia_dentro: int = 0
    peso_da_scrivere: int = 0
    stima: selezione.Stima = field(default_factory=selezione.Stima)
    saltati: list = field(default_factory=list)
    ripresa: bool = False

    def a_parole(self) -> str:
        if not self.da_scrivere and not self.da_togliere:
            return ("le foto sono già tutte lì: si riscrive solo il "
                    "database e si rilegge tutto per controllo")
        pezzi = []
        if self.da_scrivere:
            pezzi.append(f"{selezione.a_numero(len(self.da_scrivere))} file "
                         f"nuovi ({selezione.a_misura(self.peso_da_scrivere)})")
        if self.da_togliere:
            pezzi.append(f"{selezione.a_numero(len(self.da_togliere))} da togliere")
        if self.gia_dentro:
            pezzi.append(f"{selezione.a_numero(self.gia_dentro)} già lì")
        return ", ".join(pezzi)


@dataclass
class Esito:
    scritti: int = 0
    tolti: int = 0
    peso: int = 0
    verificati: int = 0
    saltati: list = field(default_factory=list)
    guasti: list = field(default_factory=list)
    interrotto: bool = False
    tornato: ritorno.Tornato = field(default_factory=ritorno.Tornato)

    @property
    def completo(self) -> bool:
        return not self.interrotto and not self.guasti

    def a_parole(self) -> str:
        if self.guasti:
            quanti = len(self.guasti)
            return (("1 file è venuto diverso rileggendolo" if quanti == 1
                     else "%s file sono venuti diversi rileggendoli"
                     % selezione.a_numero(quanti))
                    + " dal pacchetto. Il travaso va rifatto: finché non lo "
                    "rifai, quelle foto sul telefono non si aprono.")

        pezzi = []
        if self.scritti:
            pezzi.append(selezione.conta(self.scritti, "file nuovo", "file nuovi")
                         + f" ({selezione.a_misura(self.peso)})")
        if self.tolti:
            pezzi.append(selezione.conta(self.tolti, "tolto", "tolti"))
        if not pezzi:
            pezzi.append("non c'era niente da cambiare")
            se_verificati = "file riletti e verificati"
        else:
            se_verificati = "riletti e verificati"
        if self.verificati:
            pezzi.append(selezione.conta(
                self.verificati,
                se_verificati.replace("riletti e verificati",
                                      "riletto e verificato"),
                se_verificati))
        cosa = ", ".join(pezzi)

        if self.interrotto:
            return ("Fermato: " + cosa + ". Quello che era già scritto resta "
                    "nel pacchetto, e la prossima volta riprende da lì.")

        riga = "Fatto: " + cosa + "."
        if self.saltati:
            quanti = len(self.saltati)
            riga += (" %d file non è entrato nel pacchetto." % quanti
                     if quanti == 1
                     else " %s file non sono entrati nel pacchetto."
                     % selezione.a_numero(quanti))
        return riga


class Travaso:

    def __init__(self, archivio: Archivio, telefono_id: int, cartella: Path,
                 password: str, quando_cambia=None):
        self.archivio = archivio
        self.telefono_id = telefono_id
        self.cartella = Path(cartella)
        self.password = password
        self.quando_cambia = quando_cambia or (lambda *_: None)
        self.fermati = threading.Event()
        self._chiave: cifratura.Chiave | None = None
        self._carta: formato.Carta | None = None


    def prepara(self) -> Piano:
        with self.archivio.lettura() as connessione:
            riga = telefoni.per_id(connessione, self.telefono_id)
            if riga is None:
                raise ErroreOfficina("Questo telefono non c'è più.")
            scelta = selezione.Selezione.da_json(riga["selezione"])
            piano = Piano(telefono=riga["nome"], cartella=self.cartella,
                          scelta=scelta)
            piano.stima = selezione.stima(connessione, scelta)
            piano.ripresa = bool(
                telefoni.travaso_lasciato_a_meta(connessione, self.telefono_id))

            gia = telefoni.dentro_il_pacchetto(connessione, self.telefono_id)
            voluti = self._cosa_ci_va(connessione, scelta, piano, _riusabili(gia))

        guardabile = self.cartella.is_dir()
        for compito in voluti:
            vecchio = gia.get(compito.posto)
            fatto = (vecchio is not None
                     and vecchio["impronta"] == compito.impronta
                     and vecchio["impronta"] != "")
            if fatto and guardabile:
                fatto = formato.dentro(self.cartella, compito.posto).is_file()
            if fatto:
                piano.gia_dentro += 1
            else:
                piano.da_scrivere.append(compito)
                piano.peso_da_scrivere += cifratura.peso_cifrato(
                    compito.dimensione)

        voluti_posti = {c.posto for c in voluti} | {formato.DATI}
        piano.da_togliere = sorted(set(gia) - voluti_posti)
        return piano

    def _cosa_ci_va(self, connessione, scelta: selezione.Selezione,
                    piano: Piano, riuso: dict[str, str]) -> list[Compito]:
        scelti = selezione.numeri(connessione, scelta)
        compiti: list[Compito] = []
        presi: set[str] = set()
        miniature: dict[str, Compito] = {}

        for scatto_id in scelti:
            righe = tutti(
                connessione,
                "SELECT * FROM file_media WHERE scatto_id = ? "
                "ORDER BY ruolo IS NULL, ruolo", scatto_id)

            principale = None
            movimento = None
            for riga in righe:
                percorso, migliorata = file_media.da_mostrare(connessione,
                                                              riga["id"])
                if percorso is None:
                    piano.saltati.append(Saltato(
                        posto=f"scatto {scatto_id}",
                        perche="l'originale non si trova più sul disco "
                               "(regola 96)"))
                    continue
                impronta = migliorata or riga["impronta"]
                posto = _posto(riuso, presi, _per_il_riuso("originale", impronta),
                               formato.posto_dell_originale)
                compito = Compito(
                    posto=posto, genere="originale",
                    impronta=impronta,
                    dimensione=(percorso.stat().st_size if migliorata
                                else riga["dimensione"]),
                    sorgente=percorso, scatto_id=scatto_id, file_id=riga["id"],
                    cache=riga["miniatura"], e_video=riga["genere"] == "video",
                    identita=riga["impronta"])
                compiti.append(compito)
                if riga["ruolo"] == "movimento":
                    movimento = compito
                elif principale is None:
                    principale = compito

            if principale is None:
                continue

            impronta_mini = f"mini:{principale.impronta}"
            if impronta_mini not in miniature:
                miniature[impronta_mini] = Compito(
                    posto=_posto(riuso, presi, _per_il_riuso("miniatura", impronta_mini),
                                 formato.posto_della_miniatura),
                    genere="miniatura",
                    impronta=impronta_mini,
                    dimensione=60 * 1024,
                    scatto_id=scatto_id, file_id=principale.file_id,
                    sorgente=principale.sorgente, cache=principale.cache,
                    e_video=principale.e_video)
            piano.posti.append(dati.Posto(
                scatto_id=scatto_id,
                impronta=principale.identita or principale.impronta,
                posto=principale.posto, dimensione=principale.dimensione,
                posto_movimento=movimento.posto if movimento else None,
                mini=miniature[impronta_mini].posto))

        compiti.extend(miniature.values())
        compiti.extend(self._volti(connessione, {p.scatto_id for p in piano.posti},
                                   riuso, presi))
        return compiti

    def _volti(self, connessione, scelti: set[int], riuso: dict[str, str],
               presi: set[str]) -> list[Compito]:
        if not scelti:
            return []
        righe = tutti(
            connessione,
            "SELECT p.id, v.riquadro, v.scatto_id, v.file_id "
            "FROM persone p JOIN volti v ON v.id = p.volto_copertina "
            "WHERE p.nome IS NOT NULL AND p.nome <> '' AND p.stato = 'attiva'")
        compiti = []
        for riga in righe:
            if riga["scatto_id"] not in scelti:
                continue
            percorso = (file_media.percorso_migliore(connessione, riga["file_id"])
                        if riga["file_id"] else None)
            if percorso is None:
                continue
            impronta = f"volto:{riga['id']}:{riga['riquadro']}"
            compiti.append(Compito(
                posto=_posto(riuso, presi, _per_il_riuso("volto", impronta),
                             formato.posto_del_volto),
                genere="volto",
                impronta=impronta,
                riquadro=riga["riquadro"],
                dimensione=30 * 1024, sorgente=percorso,
                persona_id=riga["id"], scatto_id=riga["scatto_id"]))
        return compiti


    def esegui(self, piano: Piano | None = None) -> Esito:
        piano = piano or self.prepara()
        esito = Esito(saltati=list(piano.saltati))

        self._apri_la_cartella(piano)
        arrivato = ritorno.apri(self.cartella, self._chiave)
        with self.archivio.scrittura() as connessione:
            esito.tornato = ritorno.leggi(connessione, self.telefono_id, arrivato)
        with self.archivio.scrittura_di_servizio() as connessione:
            travaso_id = self._apri_il_registro(connessione, piano)

        try:
            self._scrivi(piano, esito, travaso_id)
            if not self.fermati.is_set():
                self._scrivi_il_database(piano, esito)
                self._togli(piano, esito, travaso_id)
                self._verifica(esito)
        except SpazioInsufficiente:
            esito.interrotto = True
            registro.errore("visore.disco_pieno")
            raise
        finally:
            self._chiudi(piano, esito, travaso_id)
        return esito

    def ferma(self) -> None:
        self.fermati.set()


    def _apri_la_cartella(self, piano: Piano) -> None:
        with self.archivio.scrittura_di_servizio() as connessione:
            identificativo = telefoni.identificativo(connessione)
        self.cartella.mkdir(parents=True, exist_ok=True)

        vecchia = None
        if (self.cartella / formato.CARTA).is_file():
            vecchia = formato.Carta.leggi(self.cartella)
            vecchia.controlla_il_formato()
            if vecchia.archivio != identificativo:
                raise ErroreOfficina(
                    "In questa cartella c'è già il pacchetto di **un altro "
                    "archivio**. Mescolarli vorrebbe dire due metà che non "
                    "combaciano e nessun modo di separarle: scegli una "
                    "cartella vuota, oppure cancella quella che c'è.",
                    codice="archivio_diverso")
            if vecchia.telefono != piano.telefono:
                raise ErroreOfficina(
                    f"In questa cartella c'è il pacchetto di "
                    f"«{vecchia.telefono}», e stai preparando quello di "
                    f"«{piano.telefono}». Ogni telefono ha la sua cartella "
                    "(regola 368).",
                    codice="telefono_diverso")

        if vecchia:
            self._chiave = vecchia.chiave(self.password)
            sale, costo, blocco, parallelo = vecchia.sale, vecchia.n, vecchia.r, vecchia.p
        else:
            sale = cifratura.sale_nuovo().hex()
            costo, blocco, parallelo = (cifratura.COSTO, cifratura.BLOCCO_SCRYPT,
                                        cifratura.PARALLELO)
            self._chiave = cifratura.Chiave.dalla_password(
                self.password, bytes.fromhex(sale), costo, blocco, parallelo)

        self._carta = formato.Carta(
            telefono=piano.telefono, archivio=identificativo, sale=sale,
            prova=self._chiave.prova(), n=costo, r=blocco, p=parallelo,
            versione_officina=VERSIONE,
            stato=formato.INTERROTTO,
            fatto_il=_adesso(),
            quanti_scatti=len(piano.posti),
            quanti_video=piano.stima.quanti_video,
            dal_giorno=piano.stima.dal_giorno, al_giorno=piano.stima.al_giorno)
        self._carta.scrivi(self.cartella)

    def _apri_il_registro(self, connessione, piano: Piano) -> int:
        aperto = telefoni.travaso_lasciato_a_meta(connessione, self.telefono_id)
        if aperto:
            return aperto["id"]
        return telefoni.apri_travaso(connessione, self.telefono_id,
                                     str(self.cartella), len(piano.posti))

    def _scrivi(self, piano: Piano, esito: Esito, travaso_id: int) -> None:
        in_attesa: list[tuple] = []
        try:
            self._scrivi_tutti(piano, esito, in_attesa, travaso_id)
        finally:
            self._segna(in_attesa, travaso_id, esito)

    def _segna(self, in_attesa: list[tuple], travaso_id: int, esito: Esito) -> None:
        if not in_attesa:
            return
        with self.archivio.scrittura_di_servizio() as connessione:
            for compito, scritto in in_attesa:
                telefoni.segna_file(
                    connessione, self.telefono_id, compito.posto,
                    compito.genere, compito.impronta, scritto.dimensione,
                    scritto.peso, compito.scatto_id)
            telefoni.aggiorna_travaso(connessione, travaso_id,
                                      scritti=esito.scritti, peso=esito.peso)
        in_attesa.clear()

    def _scrivi_tutti(self, piano: Piano, esito: Esito, in_attesa: list[tuple],
                      travaso_id: int) -> None:
        quanti = len(piano.da_scrivere)
        for numero, compito in enumerate(piano.da_scrivere, start=1):
            if self.fermati.is_set():
                esito.interrotto = True
                return
            self.quando_cambia("scrivo", numero, quanti)
            try:
                scritto = self._scrivi_uno(compito)
            except FileNonLeggibile as guaio:
                esito.saltati.append(Saltato(compito.posto, guaio.messaggio))
                continue
            except OSError as guaio:
                if guaio.errno in (errno.ENOSPC, errno.EDQUOT):
                    raise SpazioInsufficiente(
                        "Il disco su cui stai costruendo il pacchetto è "
                        "pieno. Quello che è stato scritto finora resta, e il "
                        "prossimo travaso riprende da lì.") from guaio
                esito.saltati.append(Saltato(
                    compito.posto,
                    f"non si è potuto scrivere: {guaio.strerror or guaio}"))
                continue

            esito.scritti += 1
            esito.peso += scritto.peso
            in_attesa.append((compito, scritto))
            if len(in_attesa) >= A_GRUPPI:
                self._segna(in_attesa, travaso_id, esito)

    def _scrivi_uno(self, compito: Compito) -> cifratura.Scritto:
        dove = formato.dentro(self.cartella, compito.posto)
        if compito.genere == "originale":
            return self._chiave.cifra_file(compito.sorgente, dove, compito.posto)
        if compito.genere == "miniatura":
            return self._chiave.scrivi_byte(self._miniatura(compito), dove, compito.posto)
        return self._chiave.scrivi_byte(self._volto(compito), dove, compito.posto)

    def _miniatura(self, compito: Compito) -> bytes:
        from PIL import Image

        from officina.immagini import fotogrammi, lettura

        grezzo = (self.archivio.leggi_miniatura(compito.cache)
                  if compito.cache else None)
        if grezzo:
            immagine = Image.open(io.BytesIO(grezzo), formats=lettura.formati_aperti())
        elif compito.e_video:
            immagine = fotogrammi.copertina(compito.sorgente, LATO_MINIATURA, scansa_il_buio=True)
            if immagine is None:
                raise FileNonLeggibile(
                    "Di questo video non si riesce a tirare fuori nemmeno un "
                    "fotogramma: nel pacchetto va senza miniatura.",
                    codice="miniatura_impossibile")
        else:
            immagine = lettura.copia_di_lavoro(compito.sorgente, LATO_MINIATURA)

        immagine.thumbnail((LATO_MINIATURA, LATO_MINIATURA),
                           Image.Resampling.LANCZOS)
        if immagine.mode not in ("RGB", "L"):
            immagine = immagine.convert("RGB")
        appoggio = io.BytesIO()
        immagine.save(appoggio, "JPEG", quality=QUALITA, optimize=True)
        return appoggio.getvalue()

    def _volto(self, compito: Compito) -> bytes:
        from PIL import Image

        from officina.immagini import lettura

        riquadro = json.loads(compito.riquadro)
        immagine = lettura.copia_di_lavoro(compito.sorgente)
        larghezza, altezza = immagine.size
        x, y, larga, alta = riquadro
        centro_x = (x + larga / 2) * larghezza
        centro_y = (y + alta / 2) * altezza
        lato = max(larga * larghezza, alta * altezza) * 1.4
        mezzo = lato / 2
        ritaglio = immagine.crop((
            int(max(0, centro_x - mezzo)), int(max(0, centro_y - mezzo)),
            int(min(larghezza, centro_x + mezzo)),
            int(min(altezza, centro_y + mezzo))))
        if ritaglio.mode not in ("RGB", "L"):
            ritaglio = ritaglio.convert("RGB")
        ritaglio = ritaglio.resize((LATO_VOLTO, LATO_VOLTO),
                                   Image.Resampling.LANCZOS)
        appoggio = io.BytesIO()
        ritaglio.save(appoggio, "JPEG", quality=QUALITA, optimize=True)
        return appoggio.getvalue()

    def _scrivi_il_database(self, piano: Piano, esito: Esito) -> None:
        self.quando_cambia("database", 0, 1)
        with self.archivio.lettura() as connessione:
            via = set(piano.da_togliere)
            volti = {}
            for riga in tutti(connessione,
                              "SELECT posto, impronta FROM pacchetto_file "
                              "WHERE telefono_id = ? AND genere = 'volto'",
                              self.telefono_id):
                persona = _persona_del_volto(riga["impronta"])
                if persona is not None and riga["posto"] not in via:
                    volti[persona] = riga["posto"]
            volti.update({c.persona_id: c.posto for c in piano.da_scrivere
                          if c.genere == "volto"})
            grezzo = dati.costruisci(
                connessione, piano.posti, volti,
                {"versione_officina": VERSIONE,
                 "archivio": telefoni.identificativo(connessione),
                 "telefono": piano.telefono,
                 "fatto_il": _adesso(),
                 "nuove_ultimo_travaso": len({
                     c.scatto_id for c in piano.da_scrivere
                     if c.genere == "originale" and c.scatto_id is not None})},
                self.archivio.dove.radice / "lavoro",
                ritorno.copia_di_scorta(connessione, self.telefono_id))
        scritto = self._chiave.scrivi_byte(
            grezzo, formato.dentro(self.cartella, formato.DATI), formato.DATI)
        with self.archivio.scrittura_di_servizio() as connessione:
            telefoni.segna_file(connessione, self.telefono_id, formato.DATI,
                                "dati", scritto.impronta, scritto.dimensione,
                                scritto.peso)
        esito.peso += scritto.peso
        esito.scritti += 1

    def _togli(self, piano: Piano, esito: Esito, travaso_id: int) -> None:
        if not piano.da_togliere:
            return
        for posto in piano.da_togliere:
            formato.dentro(self.cartella, posto).unlink(missing_ok=True)
            esito.tolti += 1
        with self.archivio.scrittura_di_servizio() as connessione:
            telefoni.dimentica_file(connessione, self.telefono_id,
                                    piano.da_togliere)
        _svuota_le_cartelle_vuote(self.cartella)

    def _verifica(self, esito: Esito) -> None:
        with self.archivio.lettura() as connessione:
            elenco = tutti(connessione,
                           "SELECT posto, impronta, genere, dimensione "
                           "FROM pacchetto_file WHERE telefono_id = ?",
                           self.telefono_id)
        quanti = len(elenco)
        for numero, riga in enumerate(elenco, start=1):
            if self.fermati.is_set():
                esito.interrotto = True
                return
            self.quando_cambia("verifico", numero, quanti)
            dove = formato.dentro(self.cartella, riga["posto"])
            if not dove.is_file():
                esito.guasti.append(f"{riga['posto']}: non c'è più")
                continue
            try:
                if riga["genere"] == "originale":
                    letto = _impronta_letta(self._chiave, dove, riga["posto"])
                    if letto != riga["impronta"]:
                        esito.guasti.append(
                            f"{riga['posto']}: il contenuto non corrisponde")
                        continue
                else:
                    self._chiave.leggi_tutto(dove, riga["posto"])
            except cifratura.PacchettoRovinato as guaio:
                esito.guasti.append(f"{riga['posto']}: {guaio.messaggio}")
                continue
            esito.verificati += 1

    def _chiudi(self, piano: Piano, esito: Esito, travaso_id: int) -> None:
        finito = esito.completo
        with self.archivio.scrittura_di_servizio() as connessione:
            telefoni.aggiorna_travaso(
                connessione, travaso_id, scritti=esito.scritti,
                tolti=esito.tolti, saltati=len(esito.saltati),
                peso=esito.peso, verificato=1 if esito.verificati else 0)
            if finito:
                telefoni.chiudi_travaso(connessione, travaso_id, "finito")
                telefoni.ricorda_cartella(connessione, self.telefono_id,
                                          str(self.cartella))
            _, peso = telefoni.peso_del_pacchetto(connessione, self.telefono_id)

        if self._carta:
            self._carta.stato = (formato.COMPLETO if finito
                                 else formato.INTERROTTO)
            self._carta.finito_il = _adesso() if finito else ""
            self._carta.peso = peso
            self._carta.note = _note_in_chiaro(esito.saltati)
            self._carta.scrivi(self.cartella)
        registro.evento("visore.travaso", scritti=esito.scritti,
                        tolti=esito.tolti, completo=finito)


def _adesso() -> str:
    from officina.archivio.database import adesso
    return adesso()


def _riusabili(gia: dict) -> dict[str, str]:
    riuso: dict[str, str] = {}
    for posto, riga in gia.items():
        if formato.e_a_caso(posto) and riga["impronta"]:
            riuso.setdefault(_per_il_riuso(riga["genere"], riga["impronta"]), posto)
    return riuso


def _per_il_riuso(genere: str, impronta: str) -> str:
    if genere == "volto":
        return ":".join(impronta.split(":")[:2])
    return f"{genere}:{impronta}"


def _posto(riuso: dict[str, str], presi: set[str], chiave: str, nuovo) -> str:
    posto = riuso.pop(chiave, None)
    while posto is None or posto in presi:
        posto = nuovo()
    presi.add(posto)
    return posto


def _persona_del_volto(impronta: str) -> int | None:
    pezzi = impronta.split(":")
    if len(pezzi) < 2 or pezzi[0] != "volto" or not pezzi[1].isdecimal():
        return None
    return int(pezzi[1])


def _note_in_chiaro(saltati: list) -> list[str]:
    if not saltati:
        return []
    quanti = len(saltati)
    return ["1 file non è entrato nel pacchetto: i dettagli sono sul computer."
            if quanti == 1 else
            f"{selezione.a_numero(quanti)} file non sono entrati nel pacchetto: "
            "i dettagli sono sul computer."]


def _impronta_letta(chiave: cifratura.Chiave, dove: Path, posto: str) -> str:
    import hashlib

    impronta = hashlib.blake2b(digest_size=32)
    dimensione = chiave.dimensione_in_chiaro(dove)
    letti = 0
    while letti < dimensione or (dimensione == 0 and letti == 0):
        pezzo = chiave.leggi_pezzo(dove, letti, cifratura.BLOCCO, posto)
        if not pezzo:
            break
        impronta.update(pezzo)
        letti += len(pezzo)
    return impronta.hexdigest()


def _svuota_le_cartelle_vuote(cartella: Path) -> None:
    for dentro in sorted(cartella.rglob("*"), reverse=True):
        if dentro.is_dir():
            try:
                dentro.rmdir()
            except OSError:
                pass
