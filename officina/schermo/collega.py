from __future__ import annotations

import http.client
import json
import secrets
import socket
import ssl
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from officina import registro
from officina.errori import ErroreOfficina
from officina.programma import NOME, carta, segreti
from officina.schermo import (AGGIORNA, CHIUSO, DOMANDA, INTESTAZIONE, PORTA_TCP, PORTA_UDP,
                              certificato, patto)
from officina.schermo import rete as rete_di_casa

GETTONE = f"{NOME}/portatile"
ATTESA_RETE = 8.0
ATTESA_BUSSATA = 0.6
ATTESA_RICHIESTE = 120.0
PEZZO = 256 * 1024
AVVISO_DOPO = 120.0
SCELTA_DOPO = 210.0
ATTESA_TRA_I_TENTATIVI = 2.0
OGNI_QUANTO_GUARDO = 1.0
GUARDO_AL_MASSIMO = 3600.0

NON_RAGGIUNGO = ("Non riesco a raggiungere il fisso. Controlla che sia acceso, "
                 "che il programma sia aperto con la porta aperta, e che i due "
                 "computer siano nella stessa rete di casa.")
NON_E_LUI = ("Il fisso che risponde non è quello abbinato: per sicurezza non mi "
             "collego. Se hai reinstallato il programma sul fisso, abbinalo di nuovo.")
SPIATO = ("Il codice non torna, oppure qualcuno nella rete si è messo in mezzo. "
          "Controlla le sei cifre sul fisso e riprova.")

INTESTAZIONI_DI_PASSAGGIO = {"connection", "keep-alive", "proxy-authenticate",
                             "proxy-authorization", "te", "trailers",
                             "transfer-encoding", "upgrade", "host",
                             "content-length"}


class NoDalFisso(ErroreOfficina):
    codice = "fisso_rifiuta"


@dataclass
class Fisso:
    nome: str
    indirizzo: str
    porta: int
    impronta: str
    pem: str


def _chiedi_in_giro(secondi: float) -> dict[str, dict]:
    trovati: dict[str, dict] = {}
    destinazioni = ["255.255.255.255", "127.0.0.1"]
    destinazioni += [str(rete.broadcast_address) for rete in rete_di_casa.reti_di_casa()]
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as bocca:
        bocca.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        bocca.settimeout(0.3)
        for indirizzo in destinazioni:
            try:
                bocca.sendto(DOMANDA, (indirizzo, PORTA_UDP))
            except OSError:
                continue
        scade = time.monotonic() + secondi
        while time.monotonic() < scade:
            try:
                arrivato, (da_chi, _) = bocca.recvfrom(1024)
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                dati = json.loads(arrivato)
                voce = {"nome": str(dati["nome"])[:80], "indirizzo": da_chi,
                        "porta": int(dati["porta"]), "impronta": str(dati["impronta"])}
            except (ValueError, KeyError, TypeError):
                continue
            if da_chi == "127.0.0.1" and voce["impronta"] in trovati:
                continue
            trovati[voce["impronta"]] = voce
    return trovati


def _bussa(indirizzo: str, porta: int) -> dict | None:
    try:
        with socket.create_connection((indirizzo, porta), timeout=ATTESA_BUSSATA):
            pass
    except OSError:
        return None
    try:
        connessione = _connessione(indirizzo, porta, None, None, attesa=3.0)
    except NoDalFisso:
        return None
    try:
        impronta = certificato.impronta_di(connessione.sock.getpeercert(binary_form=True))
        chi = _chiedi(connessione, "GET", "/schermo/chi-sei")
    except NoDalFisso:
        return None
    finally:
        connessione.close()
    return {"nome": str(chi.get("nome") or "Il fisso")[:80], "indirizzo": indirizzo,
            "porta": porta, "impronta": impronta}


def _bussa_a_tutti(mio: set[str]) -> dict[str, dict]:
    candidati = [str(ip) for rete in rete_di_casa.reti_di_casa() for ip in rete.hosts()
                 if str(ip) not in mio]
    trovati: dict[str, dict] = {}
    if not candidati:
        return trovati
    with ThreadPoolExecutor(max_workers=64) as squadra:
        for voce in squadra.map(lambda ip: _bussa(ip, PORTA_TCP), candidati):
            if voce is not None:
                trovati[voce["impronta"]] = voce
    return trovati


def cerca(secondi: float = 1.5) -> list[dict]:
    trovati = _chiedi_in_giro(secondi)
    if not any(voce["indirizzo"] != "127.0.0.1" for voce in trovati.values()):
        for impronta, voce in _bussa_a_tutti(set(rete_di_casa.indirizzi_di_casa())).items():
            trovati.setdefault(impronta, voce)
    return list(trovati.values())


def leggi_l_indirizzo(scritto: str) -> tuple[str, int]:
    scritto = str(scritto or "").strip()
    for togli in ("https://", "http://"):
        if scritto.lower().startswith(togli):
            scritto = scritto[len(togli):]
    scritto = scritto.strip("/ ")
    porta = PORTA_TCP
    if scritto.count(":") == 1:
        scritto, numero = scritto.split(":")
        try:
            porta = int(numero)
        except ValueError:
            raise NoDalFisso("Dopo i due punti ci va il numero della porta, "
                             "come lo vedi sul fisso.") from None
    if not scritto:
        raise NoDalFisso("Scrivi l'indirizzo che vedi sul fisso.")
    return scritto, porta


def _contesto(pem: str | None) -> ssl.SSLContext:
    contesto = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    contesto.minimum_version = ssl.TLSVersion.TLSv1_2
    contesto.check_hostname = False
    if pem:
        contesto.load_verify_locations(cadata=pem)
        contesto.verify_mode = ssl.CERT_REQUIRED
    else:
        contesto.verify_mode = ssl.CERT_NONE
    return contesto


def _connessione(indirizzo: str, porta: int, pem: str | None, impronta: str | None,
                 attesa: float = ATTESA_RETE) -> http.client.HTTPSConnection:
    connessione = http.client.HTTPSConnection(indirizzo, porta, timeout=attesa,
                                              context=_contesto(pem))
    try:
        connessione.connect()
    except (OSError, ssl.SSLError) as guasto:
        raise NoDalFisso(NON_RAGGIUNGO) from guasto
    visto = certificato.impronta_di(connessione.sock.getpeercert(binary_form=True))
    if impronta is not None and visto != impronta:
        connessione.close()
        raise NoDalFisso(NON_E_LUI)
    return connessione


def _chiedi(connessione: http.client.HTTPSConnection, metodo: str, percorso: str,
            dati: dict | None = None) -> dict:
    corpo = json.dumps(dati).encode() if dati is not None else None
    try:
        connessione.request(metodo, percorso, body=corpo,
                            headers={"content-type": "application/json"})
        risposta = connessione.getresponse()
        letto = json.loads(risposta.read() or b"{}")
    except (OSError, ValueError, http.client.HTTPException) as guasto:
        raise NoDalFisso(NON_RAGGIUNGO) from guasto
    if risposta.status != 200:
        raise NoDalFisso(letto.get("messaggio") or NON_RAGGIUNGO)
    return letto


def com_e(indirizzo: str, porta: int, impronta: str | None = None) -> dict:
    connessione = _connessione(indirizzo, porta, None, impronta)
    try:
        return _chiedi(connessione, "GET", "/schermo/chi-sei")
    finally:
        connessione.close()


def id_di_questo_portatile() -> str:
    scritto = carta.leggi().get("id_portatile")
    if isinstance(scritto, str) and scritto:
        return scritto
    nuovo = secrets.token_hex(12)
    carta.aggiorna(id_portatile=nuovo)
    return nuovo


def abbina(indirizzo: str, porta: int, codice: str) -> Fisso:
    from spake2 import SPAKE2_A

    codice = "".join(cifra for cifra in str(codice) if cifra.isdigit())
    if len(codice) != 6:
        raise NoDalFisso("Il codice è fatto di sei cifre.")
    connessione = _connessione(indirizzo, porta, None, None)
    try:
        der = connessione.sock.getpeercert(binary_form=True)
        impronta = certificato.impronta_di(der)
        pem = ssl.DER_cert_to_PEM_cert(der)
        chi = _chiedi(connessione, "GET", "/schermo/chi-sei")
        mio = id_di_questo_portatile()
        spake = SPAKE2_A(codice.encode(), idA=b"portatile", idB=b"fisso")
        mio_messaggio = spake.start()
        primo = _chiedi(connessione, "POST", "/schermo/abbina/uno",
                        {"id": mio, "nome": socket.gethostname()})
        try:
            chiave = spake.finish(patto.da_base64(primo["messaggio"]))
        except Exception as guasto:
            raise NoDalFisso(SPIATO) from guasto
        secondo = _chiedi(connessione, "POST", "/schermo/abbina/due", {
            "abbinamento": primo["abbinamento"],
            "messaggio": patto.in_base64(mio_messaggio),
            "prova": patto.prova(chiave, patto.CHI_PORTATILE, impronta)})
        if not patto.uguali(secondo.get("prova") or "",
                            patto.prova(chiave, patto.CHI_FISSO, impronta)):
            raise NoDalFisso(SPIATO)
        gettone = patto.apri_il_gettone(chiave, secondo["gettone"])
    finally:
        connessione.close()
    fisso = Fisso(nome=str(chi.get("nome") or "Il fisso")[:80], indirizzo=indirizzo,
                  porta=int(porta), impronta=impronta, pem=pem)
    segreti.custodisci(GETTONE, gettone)
    carta.aggiorna(fisso=asdict(fisso))
    registro.evento("schermo.abbinato_al_fisso")
    return fisso


def fisso_abbinato() -> Fisso | None:
    scritto = carta.leggi().get("fisso")
    if not isinstance(scritto, dict) or not segreti.leggi(GETTONE):
        return None
    try:
        return Fisso(**{chiave: scritto[chiave] for chiave in
                        ("nome", "indirizzo", "porta", "impronta", "pem")})
    except (KeyError, TypeError):
        return None


def dimentica_il_fisso() -> None:
    segreti.togli(GETTONE)
    carta.aggiorna(fisso=None)


def ritrova(fisso: Fisso) -> Fisso:
    try:
        com_e(fisso.indirizzo, fisso.porta, fisso.impronta)
        return fisso
    except NoDalFisso:
        pass
    for voce in cerca():
        if voce["impronta"] == fisso.impronta:
            spostato = Fisso(fisso.nome, voce["indirizzo"], voce["porta"],
                             fisso.impronta, fisso.pem)
            carta.aggiorna(fisso=asdict(spostato))
            return spostato
    raise NoDalFisso(NON_RAGGIUNGO)


def serve_la_password(fisso: Fisso) -> bool:
    return bool(com_e(fisso.indirizzo, fisso.porta, fisso.impronta).get("password"))


def entra(fisso: Fisso, password: str) -> str:
    gettone = segreti.leggi(GETTONE)
    if not gettone:
        raise NoDalFisso("Questo portatile non è ancora abbinato al fisso.")
    connessione = _connessione(fisso.indirizzo, fisso.porta, fisso.pem, fisso.impronta)
    try:
        risposta = _chiedi(connessione, "POST", "/schermo/entra", {
            "id": id_di_questo_portatile(), "gettone": gettone, "password": password})
    finally:
        connessione.close()
    return str(risposta["sessione"])


def esci(ponte: "Ponte") -> None:
    fisso = ponte.fisso
    connessione = _connessione(fisso.indirizzo, fisso.porta, fisso.pem, fisso.impronta,
                               attesa=3.0)
    try:
        connessione.request("POST", "/schermo/esci", body=b"{}",
                            headers={"content-type": "application/json",
                                     INTESTAZIONE: ponte.sessione})
        connessione.getresponse().read()
    except (OSError, http.client.HTTPException, ssl.SSLError):
        pass
    finally:
        connessione.close()


PAGINA_CHIUSA = """<!doctype html><html lang="it"><head><meta charset="utf-8">
<title>Collegamento chiuso</title><style>
body{margin:0;min-height:100vh;display:grid;place-items:center;background:#262624;
color:#F5F4EE;font:15px/1.5 system-ui,sans-serif}
@media (prefers-color-scheme: light){body{background:#FAF9F5;color:#141413}}
main{display:grid;gap:14px;justify-items:center;text-align:center;max-width:420px;padding:24px}
h1{font:400 26px/1.2 Georgia,serif;margin:0}p{margin:0;opacity:.75}
button{height:36px;padding:0 16px;border-radius:10px;border:0;background:#D97757;
color:#1F1E1D;font:inherit;cursor:pointer}</style></head><body><main>
<h1>Il collegamento con il fisso è chiuso</h1>
<p>Il fisso l'ha chiuso, oppure non risponde più. Sul portatile non è rimasto niente.</p>
<button type="button" onclick="window.pywebview && window.pywebview.api.ricollegati()">Ricollegati</button>
</main></body></html>"""


PAGINA_AGGIORNA = """<!doctype html><html lang="it"><head><meta charset="utf-8">
<title>Il fisso si aggiorna</title><style>
:root{--fondo:#262624;--testo:#F5F4EE;--tenue:rgba(245,244,238,.6);--riga:rgba(245,244,238,.14);--accento:#D97757}
@media (prefers-color-scheme: light){:root{--fondo:#FAF9F5;--testo:#141413;--tenue:rgba(20,20,19,.6);--riga:rgba(20,20,19,.12)}}
body{margin:0;min-height:100vh;display:grid;place-items:center;background:var(--fondo);
color:var(--testo);font:15px/1.5 system-ui,sans-serif}
main{display:grid;gap:16px;width:min(440px,calc(100% - 48px))}
h1{font:400 26px/1.2 Georgia,serif;margin:0;text-align:center}
p{margin:0;color:var(--tenue);text-align:center}
ol{list-style:none;margin:0;padding:0;display:grid;gap:10px}
li{display:flex;gap:10px;align-items:center;color:var(--tenue)}
li::before{content:"";width:14px;height:14px;border-radius:50%;border:2px solid var(--riga);flex:none;box-sizing:border-box}
li.fatto{color:var(--testo)}li.fatto::before{background:var(--accento);border-color:var(--accento)}
li.ora{color:var(--testo)}li.ora::before{border-color:var(--accento);border-top-color:transparent;animation:gira 1s linear infinite}
@keyframes gira{to{transform:rotate(360deg)}}
.barra{height:6px;border-radius:3px;background:var(--riga);overflow:hidden}
.barra i{display:block;height:100%;width:0;background:var(--accento);transition:width .4s}
#avviso{display:grid;gap:10px;justify-items:center}
button{height:36px;padding:0 16px;border-radius:10px;border:0;background:var(--accento);
color:#1F1E1D;font:inherit;cursor:pointer}</style></head><body><main>
<h1>Il fisso si sta aggiornando</h1>
<p id="detto">Resto qui: quando il fisso riparte mi ricollego da solo.</p>
<div class="barra"><i id="barra"></i></div>
<ol id="passi"></ol>
<div id="avviso" hidden><p>Il fisso non risponde ancora. Continuo a provare da solo.</p>
<button type="button" id="riprova">Riprova</button></div>
</main><script>
const passi=document.getElementById("passi"),barra=document.getElementById("barra"),avviso=document.getElementById("avviso");
let finito=false;
async function guarda(subito){
if(finito)return;
try{
const r=await fetch("/__schermo/aggiorna/stato"+(subito?"?subito=1":""),{cache:"no-store"});
const d=await r.json();
passi.replaceChildren(...d.passi.map((nome,i)=>{const li=document.createElement("li");li.textContent=nome;
if(i<d.fatti)li.className="fatto";else if(i===d.fatti)li.className="ora";return li}));
barra.style.width=Math.round(100*d.fatti/Math.max(1,d.passi.length))+"%";
avviso.hidden=!d.avviso;
if(d.vai){finito=true;location.replace(d.vai);return}
if(d.scelta){finito=true;if(window.pywebview)window.pywebview.api.ricollegati();return}
}catch(e){}
setTimeout(guarda,1000)}
document.getElementById("riprova").onclick=()=>guarda(true);
guarda();
</script></body></html>"""


class Ponte:

    def __init__(self, fisso: Fisso, sessione: str, quando_chiuso=None,
                 password: str = "", quando_aggiorna=None):
        self.fisso = fisso
        self.sessione = sessione
        self.quando_chiuso = quando_chiuso or (lambda: None)
        self.password = password
        self.quando_aggiorna = quando_aggiorna or (lambda: None)
        self.aggiornamento: dict | None = None
        self.ultima_pagina = "/"
        self._lucchetto = threading.Lock()
        self._locale = threading.local()
        self._server: ThreadingHTTPServer | None = None
        self._filo: threading.Thread | None = None
        self.chiuso = False
        self._fermo = threading.Event()
        self._guardo = False

    @property
    def indirizzo(self) -> str:
        return f"http://127.0.0.1:{self._server.server_address[1]}/"

    def _verso_il_fisso(self) -> http.client.HTTPSConnection:
        connessione = getattr(self._locale, "connessione", None)
        if connessione is None:
            connessione = _connessione(self.fisso.indirizzo, self.fisso.porta,
                                       self.fisso.pem, self.fisso.impronta,
                                       attesa=ATTESA_RICHIESTE)
            self._locale.connessione = connessione
        return connessione

    def _butta_la_connessione(self) -> None:
        connessione = getattr(self._locale, "connessione", None)
        self._locale.connessione = None
        if connessione is not None:
            connessione.close()

    def parti(self) -> None:
        ponte = self

        class Gestore(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *argomenti):
                return

            def _tutto(self):
                ponte.passa(self)

            do_GET = do_POST = do_PUT = do_DELETE = do_HEAD = do_PATCH = _tutto

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Gestore)
        self._server.daemon_threads = True
        self._filo = threading.Thread(target=self._server.serve_forever,
                                      name="schermo-ponte", daemon=True)
        self._filo.start()

    def ferma(self) -> None:
        self._fermo.set()
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()

    def _chiuso(self, gestore: BaseHTTPRequestHandler) -> None:
        corpo = PAGINA_CHIUSA.encode()
        gestore.send_response(200)
        gestore.send_header("content-type", "text/html; charset=utf-8")
        gestore.send_header("cache-control", "no-store")
        gestore.send_header("content-length", str(len(corpo)))
        gestore.end_headers()
        if gestore.command != "HEAD":
            gestore.wfile.write(corpo)
        if not self.chiuso:
            self.chiuso = True
            self.quando_chiuso()

    def _manda(self, gestore: BaseHTTPRequestHandler, corpo: bytes, tipo: str) -> None:
        gestore.send_response(200)
        gestore.send_header("content-type", tipo)
        gestore.send_header("cache-control", "no-store")
        gestore.send_header("content-length", str(len(corpo)))
        gestore.end_headers()
        if gestore.command != "HEAD":
            gestore.wfile.write(corpo)

    def _comincia_l_aggiornamento(self) -> bool:
        with self._lucchetto:
            if self.aggiornamento is not None:
                return False
            self.aggiornamento = {"passi": ["Il fisso si prepara", "Installo l'aggiornamento",
                                            "Riparto"],
                                  "fatti": 0, "partito": time.monotonic(), "provato": 0.0,
                                  "spento": False}
        return True

    def _chiedi_la_chiusura(self) -> dict | None:
        connessione = _connessione(self.fisso.indirizzo, self.fisso.porta, self.fisso.pem,
                                   self.fisso.impronta, attesa=3.0)
        try:
            connessione.request("GET", "/schermo/chiusura",
                                headers={INTESTAZIONE: self.sessione})
            risposta = connessione.getresponse()
            dati = json.loads(risposta.read() or b"{}")
            return dati.get("chiusura") if risposta.status == 200 else None
        finally:
            connessione.close()

    def _parte_l_aggiornamento(self) -> None:
        if self._comincia_l_aggiornamento():
            self.quando_aggiorna()

    def guarda_l_aggiornamento(self) -> None:
        with self._lucchetto:
            if self._guardo:
                return
            self._guardo = True
        threading.Thread(target=self._guarda, name="schermo-aggiornamento", daemon=True).start()

    def _guarda(self) -> None:
        fine = time.monotonic() + GUARDO_AL_MASSIMO
        try:
            while self.aggiornamento is None and time.monotonic() < fine:
                if self._fermo.wait(OGNI_QUANTO_GUARDO):
                    return
                try:
                    chiusura = self._chiedi_la_chiusura()
                except (ErroreOfficina, OSError, http.client.HTTPException, ssl.SSLError):
                    chiusura = {}
                if chiusura is not None:
                    self._parte_l_aggiornamento()
                    return
        finally:
            with self._lucchetto:
                self._guardo = False

    def _rientra(self) -> bool:
        try:
            fisso = ritrova(self.fisso)
            sessione = entra(fisso, self.password)
        except (ErroreOfficina, OSError, http.client.HTTPException, ssl.SSLError):
            return False
        self.fisso, self.sessione = fisso, sessione
        self._butta_la_connessione()
        return True

    def stato_dell_aggiornamento(self, subito: bool = False) -> dict:
        stato = self.aggiornamento
        if stato is None:
            return {"passi": [], "fatti": 0, "vai": self.ultima_pagina}
        adesso = time.monotonic()
        passati = adesso - stato["partito"]
        if not stato["spento"]:
            try:
                chiusura = self._chiedi_la_chiusura()
            except (ErroreOfficina, OSError, http.client.HTTPException, ssl.SSLError):
                chiusura = None
            if chiusura:
                stato["passi"] = list(chiusura.get("passi") or stato["passi"])
                stato["fatti"] = int(chiusura.get("fatti") or 0)
            else:
                stato["spento"] = True
                stato["fatti"] = max(len(stato["passi"]) - 2, stato["fatti"])
        if stato["spento"] and (subito or adesso - stato["provato"] >= ATTESA_TRA_I_TENTATIVI):
            stato["provato"] = adesso
            if self._rientra():
                self.aggiornamento = None
                return {"passi": stato["passi"], "fatti": len(stato["passi"]),
                        "vai": self.ultima_pagina}
        return {"passi": stato["passi"], "fatti": stato["fatti"],
                "avviso": passati >= AVVISO_DOPO, "scelta": passati >= SCELTA_DOPO}

    def _del_ponte(self, gestore: BaseHTTPRequestHandler) -> bool:
        percorso, _, domanda = gestore.path.partition("?")
        if percorso == "/__schermo/aggiorna":
            self._manda(gestore, PAGINA_AGGIORNA.encode(), "text/html; charset=utf-8")
            return True
        if percorso == "/__schermo/aggiorna/stato":
            dati = self.stato_dell_aggiornamento(subito="subito=1" in domanda)
            self._manda(gestore, json.dumps(dati).encode(), "application/json")
            return True
        return False

    def passa(self, gestore: BaseHTTPRequestHandler) -> None:
        from officina.web import origine

        no = origine.perche_no(gestore.command, gestore.headers)
        if no is not None:
            gestore.send_error(403, no)
            return
        if self._del_ponte(gestore):
            return
        pagina = gestore.command == "GET" and "text/html" in (gestore.headers.get("accept") or "")
        if self.aggiornamento is not None:
            if pagina:
                self.ultima_pagina = gestore.path
                self._manda(gestore, PAGINA_AGGIORNA.encode(), "text/html; charset=utf-8")
            else:
                gestore.send_error(503, "Il fisso si sta aggiornando.")
            return
        lunghezza = int(gestore.headers.get("content-length") or 0)
        corpo = gestore.rfile.read(lunghezza) if lunghezza else None
        intestazioni = {chiave: valore for chiave, valore in gestore.headers.items()
                        if chiave.lower() not in INTESTAZIONI_DI_PASSAGGIO}
        intestazioni["host"] = gestore.headers.get("host") or "127.0.0.1"
        intestazioni[INTESTAZIONE] = self.sessione
        if corpo is not None:
            intestazioni["content-length"] = str(len(corpo))
        risposta = None
        for prova in range(2):
            try:
                connessione = self._verso_il_fisso()
                connessione.request(gestore.command, gestore.path, body=corpo,
                                    headers=intestazioni)
                risposta = connessione.getresponse()
                break
            except NoDalFisso:
                break
            except (OSError, http.client.HTTPException, ssl.SSLError):
                self._butta_la_connessione()
        if risposta is not None and risposta.status == 503 and risposta.getheader(AGGIORNA):
            risposta.read()
            self._parte_l_aggiornamento()
            if pagina:
                self._manda(gestore, PAGINA_AGGIORNA.encode(), "text/html; charset=utf-8")
            else:
                gestore.send_error(503, "Il fisso si sta aggiornando.")
            return
        if (gestore.path == "/api/programma/aggiorna_adesso" and risposta is not None
                and risposta.status == 200):
            self.guarda_l_aggiornamento()
        if pagina and risposta is not None and risposta.status < 400:
            self.ultima_pagina = gestore.path
        if risposta is None or (risposta.status == 401 and risposta.getheader(CHIUSO)):
            if risposta is not None:
                risposta.read()
            self._chiuso(gestore)
            return
        try:
            self._rimanda(gestore, risposta)
        except (OSError, http.client.HTTPException, ssl.SSLError):
            self._butta_la_connessione()

    def _rimanda(self, gestore: BaseHTTPRequestHandler, risposta) -> None:
        gestore.send_response_only(risposta.status, risposta.reason)
        lunghezza = risposta.getheader("content-length")
        for chiave, valore in risposta.getheaders():
            if chiave.lower() in INTESTAZIONI_DI_PASSAGGIO:
                continue
            gestore.send_header(chiave, valore)
        a_pezzi = lunghezza is None and gestore.command != "HEAD" and risposta.status not in (204, 304)
        if lunghezza is not None:
            gestore.send_header("content-length", lunghezza)
        elif a_pezzi:
            gestore.send_header("transfer-encoding", "chunked")
        else:
            gestore.send_header("content-length", "0")
        gestore.end_headers()
        if gestore.command == "HEAD":
            risposta.read()
            return
        while True:
            pezzo = risposta.read1(PEZZO) if hasattr(risposta, "read1") else risposta.read(PEZZO)
            if not pezzo:
                break
            if a_pezzi:
                gestore.wfile.write(f"{len(pezzo):x}\r\n".encode() + pezzo + b"\r\n")
            else:
                gestore.wfile.write(pezzo)
        if a_pezzi:
            gestore.wfile.write(b"0\r\n\r\n")
