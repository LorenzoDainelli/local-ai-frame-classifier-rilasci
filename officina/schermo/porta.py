from __future__ import annotations

import asyncio
import json
import secrets
import socket
import threading
import time
from dataclasses import dataclass, field

from officina import registro
from officina.errori import ErroreOfficina
from officina.programma import carta
from officina.schermo import (AGGIORNA, CHIUSO, DOMANDA, INTESTAZIONE, PORTA_TCP, PORTA_UDP,
                              certificato, patto, segna_dal_portatile, smetti)

DURATA_DEL_CODICE = 300.0
TENTATIVI_PER_CODICE = 5
TENTATIVI_IN_TUTTO = 20
DURATA_DI_UN_ABBINAMENTO = 60.0
MASSIMO_ABBINAMENTI_APERTI = 8
CHI_PORTATILE_ID = b"portatile"
CHI_FISSO_ID = b"fisso"

PORTA_CHIUSA = ("La porta del fisso è chiusa. Aprila dal fisso, in Impostazioni, "
                "alla voce «Il portatile».")
CODICE_SBAGLIATO = ("Il codice non è quello che si vede sul fisso. Controlla le "
                    "sei cifre e riprova.")
NON_TI_FA_ENTRARE = ("Il fisso non ti fa entrare: la password non è quella del "
                     "forziere del fisso, oppure il fisso non riconosce più questo "
                     "portatile. In quel caso abbinalo di nuovo con il codice.")
NESSUN_CODICE = ("Sul fisso adesso non c'è nessun codice valido. Apri sul fisso la "
                 "pagina «Il portatile» e scrivi il codice che vedi.")
TROPPI_SBAGLI = ("Troppi tentativi sbagliati con il codice: il fisso non ne accetta "
                 "altri finché sul fisso non premi «Nuovo codice».")
TROPPI_SBAGLI_SUL_FISSO = "Troppi tentativi sbagliati: premi «Nuovo codice»."


class NoDallaPorta(ErroreOfficina):
    codice = "porta_rifiuta"


@dataclass
class _Abbinamento:
    spake: object
    codice: str
    nato: float
    id_portatile: str
    nome_portatile: str


@dataclass
class _Sessione:
    id_portatile: str
    nata: float = field(default_factory=time.monotonic)


def nome_di_questo_computer() -> str:
    return socket.gethostname() or "Il fisso"


def portatili() -> dict[str, dict]:
    scritti = carta.leggi().get("portatili")
    return dict(scritti) if isinstance(scritti, dict) else {}


def dimentica(id_portatile: str) -> None:
    tutti = portatili()
    tutti.pop(id_portatile, None)
    carta.aggiorna(portatili=tutti)
    porta.stacca(id_portatile)


class Porta:

    def __init__(self) -> None:
        self._lucchetto = threading.RLock()
        self.aperta = False
        self._codice = ""
        self._codice_nato = 0.0
        self._sbagli = 0
        self._sbagli_in_tutto = 0
        self._abbinamenti: dict[str, _Abbinamento] = {}
        self._sessioni: dict[str, _Sessione] = {}
        self._servitore = None
        self._ascolto: threading.Thread | None = None
        self._basta_ascoltare = threading.Event()
        self.certificato: certificato.Certificato | None = None
        self.chi_password = None
        self.porta_tcp = PORTA_TCP
        self.chiusura: dict | None = None

    def _cartella(self):
        return carta.casa() / "schermo"

    def apri(self, controlla_password=None, con_servitore: bool = True) -> None:
        with self._lucchetto:
            self.chi_password = controlla_password
            if self.aperta:
                return
            self.certificato = certificato.carica_o_crea(self._cartella())
            self._togli_il_codice()
            self._sbagli_in_tutto = 0
            self.aperta = True
            if con_servitore:
                try:
                    self._accendi_il_servitore()
                    self._accendi_l_ascolto()
                except Exception:
                    self.aperta = False
                    raise
        registro.evento("schermo.porta_aperta")

    def chiudi(self) -> None:
        with self._lucchetto:
            self.aperta = False
            self.chiusura = None
            self._togli_il_codice()
            self._abbinamenti.clear()
            self._sessioni.clear()
            servitore, self._servitore = self._servitore, None
            ascolto, self._ascolto = self._ascolto, None
            self._basta_ascoltare.set()
        if servitore is not None:
            servitore.ferma(entro=3.0)
        if ascolto is not None:
            ascolto.join(timeout=2.0)
        registro.evento("schermo.porta_chiusa")

    def _accendi_il_servitore(self) -> None:
        from officina.programma.servitore import Servitore, e_libera, porta_libera

        self.porta_tcp = next((numero for numero in (PORTA_TCP, *range(PORTA_TCP + 2, PORTA_TCP + 10))
                               if e_libera(numero, "0.0.0.0")), 0) or porta_libera(0, "0.0.0.0")
        self._servitore = Servitore(app=app_della_porta, host="0.0.0.0",
                                    porta=self.porta_tcp,
                                    certificato=self.certificato.certificato,
                                    chiave=self.certificato.chiave)
        self._servitore.parti()

    def _accendi_l_ascolto(self) -> None:
        self._basta_ascoltare = threading.Event()
        orecchio = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            orecchio.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            orecchio.bind(("0.0.0.0", PORTA_UDP))
            orecchio.settimeout(0.5)
        except OSError as guasto:
            orecchio.close()
            registro.errore("schermo.ascolto_rotto", **registro.dove_si_e_rotto(guasto))
            return
        self._ascolto = threading.Thread(target=self._ascolta,
                                         args=(orecchio, self._basta_ascoltare),
                                         name="schermo-ascolto", daemon=True)
        self._ascolto.start()

    def _ascolta(self, orecchio: socket.socket, basta: threading.Event) -> None:
        try:
            with orecchio:
                while not basta.is_set():
                    try:
                        arrivato, da_chi = orecchio.recvfrom(256)
                    except socket.timeout:
                        continue
                    if arrivato.strip() != DOMANDA or not self.aperta:
                        continue
                    risposta = json.dumps({"nome": nome_di_questo_computer(),
                                           "porta": self.porta_tcp,
                                           "impronta": self.certificato.impronta})
                    orecchio.sendto(risposta.encode(), da_chi)
        except Exception as guasto:
            registro.errore("schermo.ascolto_rotto", **registro.dove_si_e_rotto(guasto))

    def _nuovo_codice(self) -> None:
        self._codice = f"{secrets.randbelow(1_000_000):06d}"
        self._codice_nato = time.monotonic()
        self._sbagli = 0

    def _togli_il_codice(self) -> None:
        self._codice = ""
        self._codice_nato = 0.0
        self._sbagli = 0

    def _codice_valido(self) -> tuple[str, int]:
        if not self.aperta or not self._codice or self.troppi_sbagli:
            return "", 0
        restano = DURATA_DEL_CODICE - (time.monotonic() - self._codice_nato)
        if restano <= 0:
            self._togli_il_codice()
            return "", 0
        return self._codice, int(restano)

    @property
    def troppi_sbagli(self) -> bool:
        return self._sbagli_in_tutto >= TENTATIVI_IN_TUTTO

    def codice(self) -> tuple[str, int]:
        with self._lucchetto:
            return self._codice_valido()

    def mostra_il_codice(self) -> tuple[str, int]:
        with self._lucchetto:
            if not self.aperta or self.troppi_sbagli:
                return "", 0
            codice, secondi = self._codice_valido()
            if codice:
                return codice, secondi
            self._nuovo_codice()
            return self._codice_valido()

    def nuovo_codice(self) -> tuple[str, int]:
        with self._lucchetto:
            if not self.aperta:
                return "", 0
            self._sbagli_in_tutto = 0
            self._abbinamenti.clear()
            self._nuovo_codice()
            return self._codice_valido()

    def _pulisci(self) -> None:
        adesso = time.monotonic()
        for chiave in [chiave for chiave, fatto in self._abbinamenti.items()
                       if adesso - fatto.nato > DURATA_DI_UN_ABBINAMENTO]:
            del self._abbinamenti[chiave]

    def abbina_uno(self, id_portatile: str, nome_portatile: str) -> dict:
        from spake2 import SPAKE2_B

        with self._lucchetto:
            if not self.aperta:
                raise NoDallaPorta(PORTA_CHIUSA)
            if self.troppi_sbagli:
                raise NoDallaPorta(TROPPI_SBAGLI)
            codice, _ = self._codice_valido()
            if not codice:
                raise NoDallaPorta(NESSUN_CODICE)
            self._pulisci()
            if len(self._abbinamenti) >= MASSIMO_ABBINAMENTI_APERTI:
                raise NoDallaPorta("Troppi tentativi insieme. Aspetta un minuto e riprova.")
            spake = SPAKE2_B(codice.encode(), idA=CHI_PORTATILE_ID, idB=CHI_FISSO_ID)
            risposta = spake.start()
            chiave = secrets.token_urlsafe(16)
            self._abbinamenti[chiave] = _Abbinamento(
                spake, codice, time.monotonic(), id_portatile[:64], nome_portatile[:80])
        return {"abbinamento": chiave, "messaggio": patto.in_base64(risposta)}

    def abbina_due(self, abbinamento: str, arrivato: str, prova_portatile: str) -> dict:
        with self._lucchetto:
            fatto = self._abbinamenti.pop(abbinamento, None)
            if fatto is None or not self.aperta:
                raise NoDallaPorta(PORTA_CHIUSA if not self.aperta else CODICE_SBAGLIATO)
            if self.troppi_sbagli:
                raise NoDallaPorta(TROPPI_SBAGLI)
            if fatto.codice != self._codice_valido()[0]:
                raise NoDallaPorta(NESSUN_CODICE)
            try:
                chiave = fatto.spake.finish(patto.da_base64(arrivato))
            except Exception:
                chiave = None
            impronta = self.certificato.impronta
            giusta = chiave is not None and patto.uguali(
                prova_portatile, patto.prova(chiave, patto.CHI_PORTATILE, impronta))
            if not giusta:
                self._sbagli += 1
                self._sbagli_in_tutto += 1
                if self._sbagli >= TENTATIVI_PER_CODICE or self.troppi_sbagli:
                    self._togli_il_codice()
                registro.avviso("schermo.codice_sbagliato")
                if self.troppi_sbagli:
                    self._abbinamenti.clear()
                    raise NoDallaPorta(TROPPI_SBAGLI)
                raise NoDallaPorta(CODICE_SBAGLIATO)
            gettone = secrets.token_urlsafe(32)
            tutti = portatili()
            tutti[fatto.id_portatile] = {
                "nome": fatto.nome_portatile,
                "gettone": patto.impronta_del_gettone(gettone),
                "abbinato_il": time.strftime("%Y-%m-%d %H:%M"),
                "ultima_volta": None,
            }
            carta.aggiorna(portatili=tutti)
            self._togli_il_codice()
            self._sbagli_in_tutto = 0
            self._abbinamenti.clear()
        registro.evento("schermo.abbinato")
        return {"prova": patto.prova(chiave, patto.CHI_FISSO, impronta),
                "gettone": patto.chiudi_il_gettone(chiave, gettone)}

    def serve_la_password(self) -> bool:
        return self.chi_password is not None and self.chi_password.serve()

    def entra(self, id_portatile: str, gettone: str, password: str) -> str:
        with self._lucchetto:
            if not self.aperta:
                raise NoDallaPorta(PORTA_CHIUSA)
        suo = portatili().get(id_portatile)
        if suo is None or not patto.uguali(patto.impronta_del_gettone(gettone),
                                           suo.get("gettone") or ""):
            registro.avviso("schermo.portatile_sconosciuto")
            raise NoDallaPorta(NON_TI_FA_ENTRARE)
        if self.serve_la_password() and not self.chi_password.e_giusta(password):
            registro.avviso("schermo.password_sbagliata")
            raise NoDallaPorta(NON_TI_FA_ENTRARE)
        sessione = secrets.token_urlsafe(32)
        with self._lucchetto:
            self._sessioni = {sessione: _Sessione(id_portatile)}
        tutti = portatili()
        if id_portatile in tutti:
            tutti[id_portatile]["ultima_volta"] = time.strftime("%Y-%m-%d %H:%M")
            carta.aggiorna(portatili=tutti)
        registro.evento("schermo.collegato")
        return sessione

    def chi_e(self, sessione: str | None) -> str | None:
        if not sessione:
            return None
        with self._lucchetto:
            for chiave, dentro in self._sessioni.items():
                if patto.uguali(chiave, sessione):
                    return dentro.id_portatile
        return None

    def collegato(self) -> dict | None:
        with self._lucchetto:
            if not self._sessioni:
                return None
            dentro = next(iter(self._sessioni.values()))
        suo = portatili().get(dentro.id_portatile, {})
        return {"id": dentro.id_portatile, "nome": suo.get("nome") or "il portatile"}

    def stacca(self, id_portatile: str | None = None) -> None:
        with self._lucchetto:
            if id_portatile is None:
                self._sessioni.clear()
            else:
                self._sessioni = {chiave: dentro for chiave, dentro in self._sessioni.items()
                                  if dentro.id_portatile != id_portatile}
        registro.evento("schermo.staccato")


porta = Porta()


async def _leggi_il_corpo(receive) -> bytes:
    pezzi = []
    while True:
        messaggio = await receive()
        pezzi.append(messaggio.get("body", b""))
        if not messaggio.get("more_body"):
            return b"".join(pezzi)


async def _rispondi(send, stato: int, dati: dict, altre: list | None = None) -> None:
    corpo = json.dumps(dati).encode()
    intestazioni = [(b"content-type", b"application/json"),
                    (b"cache-control", b"no-store"),
                    (b"content-length", str(len(corpo)).encode())] + (altre or [])
    await send({"type": "http.response.start", "status": stato, "headers": intestazioni})
    await send({"type": "http.response.body", "body": corpo})


def _intestazione(scope, nome: str) -> str | None:
    cercata = nome.encode()
    for chiave, valore in scope.get("headers", []):
        if chiave.lower() == cercata:
            return valore.decode("latin-1")
    return None


async def _della_porta(scope, receive, send) -> None:
    percorso = scope["path"]
    if percorso == "/schermo/chiusura" and scope["method"] == "GET":
        if porta.chi_e(_intestazione(scope, INTESTAZIONE)) is None:
            await _rispondi(send, 401, {"messaggio": "Il collegamento con il fisso è chiuso."})
            return
        await _rispondi(send, 200, {"chiusura": porta.chiusura})
        return
    if percorso == "/schermo/chi-sei" and scope["method"] == "GET":
        await _rispondi(send, 200, {"nome": nome_di_questo_computer(),
                                    "aperta": porta.aperta,
                                    "password": porta.serve_la_password()})
        return
    if scope["method"] != "POST":
        await _rispondi(send, 404, {"messaggio": "Qui non c'è niente."})
        return
    try:
        dati = json.loads(await _leggi_il_corpo(receive) or b"{}")
        if percorso == "/schermo/abbina/uno":
            fuori = porta.abbina_uno(str(dati["id"]), str(dati.get("nome") or ""))
        elif percorso == "/schermo/abbina/due":
            fuori = porta.abbina_due(str(dati["abbinamento"]), str(dati["messaggio"]),
                                     str(dati["prova"]))
        elif percorso == "/schermo/esci":
            chi = porta.chi_e(_intestazione(scope, INTESTAZIONE))
            if chi is not None:
                porta.stacca(chi)
            fuori = {"uscito": chi is not None}
        elif percorso == "/schermo/entra":
            sessione = await asyncio.to_thread(
                porta.entra, str(dati["id"]), str(dati["gettone"]),
                str(dati.get("password") or ""))
            fuori = {"sessione": sessione}
        else:
            await _rispondi(send, 404, {"messaggio": "Qui non c'è niente."})
            return
    except NoDallaPorta as errore:
        await _rispondi(send, 403, {"messaggio": errore.messaggio})
        return
    except (KeyError, ValueError, TypeError):
        await _rispondi(send, 400, {"messaggio": "Richiesta non valida."})
        return
    await _rispondi(send, 200, fuori)


async def app_della_porta(scope, receive, send) -> None:
    if scope["type"] != "http":
        return
    if scope["path"].startswith("/schermo/"):
        await _della_porta(scope, receive, send)
        return
    if porta.chi_e(_intestazione(scope, INTESTAZIONE)) is None:
        await _rispondi(send, 401, {"messaggio": "Il collegamento con il fisso è chiuso."},
                        [(CHIUSO.encode(), b"1")])
        return
    if porta.chiusura is not None:
        await _rispondi(send, 503, {"messaggio": "Il fisso si sta aggiornando."},
                        [(AGGIORNA.encode(), b"1")])
        return

    from officina.web.server import app

    dentro = dict(scope)
    dentro["client"] = ("127.0.0.2", 0)
    dentro["headers"] = [(chiave, valore) for chiave, valore in scope["headers"]
                         if chiave.lower() != INTESTAZIONE.encode()]

    async def manda(messaggio):
        if messaggio["type"] == "http.response.start":
            intestazioni = [(chiave, valore) for chiave, valore in messaggio.get("headers", [])
                            if chiave.lower() != b"cache-control"]
            intestazioni.append((b"cache-control", b"no-store"))
            messaggio = dict(messaggio, headers=intestazioni)
        await send(messaggio)

    segno = segna_dal_portatile(True)
    try:
        await app(dentro, receive, manda)
    finally:
        smetti(segno)
