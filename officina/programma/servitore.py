from __future__ import annotations

import socket
import sys
import threading
import time
from pathlib import Path

from officina import registro
from officina.errori import ErroreOfficina

PORTA_PREFERITA = 8080
PORTA_DELLA_RETE = 8443


def e_libera(porta: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as prova:
        try:
            prova.bind((host, porta))
        except OSError:
            return False
    return True


def porta_libera(preferita: int = PORTA_PREFERITA, host: str = "127.0.0.1") -> int:
    if preferita and e_libera(preferita, host):
        return preferita
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as prova:
        prova.bind((host, 0))
        return prova.getsockname()[1]


def solo_per_chi_lo_usa(cartella: Path, chiave: Path) -> None:
    if sys.platform == "win32":
        return
    try:
        cartella.chmod(0o700)
        chiave.chmod(0o600)
    except OSError as guasto:
        registro.avviso("programma.chiave_della_rete_aperta", **registro.dove_si_e_rotto(guasto))


def per_la_rete(cartella: Path, preferita: int = PORTA_DELLA_RETE) -> tuple[Servitore, str]:
    from officina.schermo import certificato

    suo = certificato.carica_o_crea(cartella)
    solo_per_chi_lo_usa(cartella, suo.chiave)
    servitore = Servitore(host="0.0.0.0", porta=porta_libera(preferita, "0.0.0.0"),
                          certificato=suo.certificato, chiave=suo.chiave)
    return servitore, suo.impronta


class Servitore:

    def __init__(self, app="officina.web.server:app", host: str = "127.0.0.1",
                 porta: int | None = None, certificato=None, chiave=None):
        self.app = app
        self.certificato = certificato
        self.chiave = chiave
        self.host = host
        self.porta = porta or porta_libera(host=host)
        self._server = None
        self._filo: threading.Thread | None = None
        self.guasto: BaseException | None = None

    @property
    def indirizzo(self) -> str:
        schema = "https" if self.certificato else "http"
        return f"{schema}://127.0.0.1:{self.porta}/"

    @property
    def gira(self) -> bool:
        return self._filo is not None and self._filo.is_alive()

    def parti(self, entro: float = 30.0) -> None:
        import uvicorn

        configurazione = uvicorn.Config(self.app, host=self.host, port=self.porta,
                                        log_level="warning", access_log=False,
                                        log_config=None, lifespan="off",
                                        timeout_graceful_shutdown=1,
                                        ssl_certfile=(str(self.certificato)
                                                      if self.certificato else None),
                                        ssl_keyfile=str(self.chiave) if self.chiave else None)
        self._server = uvicorn.Server(configurazione)
        self._server.install_signal_handlers = lambda: None
        self._filo = threading.Thread(target=self._dentro, name="servitore", daemon=True)
        self._filo.start()
        scade = time.monotonic() + entro
        while time.monotonic() < scade:
            if self._server.started:
                return
            if not self._filo.is_alive():
                break
            time.sleep(0.05)
        raise ErroreOfficina(
            "Il programma non è riuscito a partire: la sua porta interna non "
            "risponde. Chiudilo e riaprilo; se succede ancora, riavvia il "
            "computer.", codice="servitore_muto")

    def _dentro(self) -> None:
        try:
            self._server.run()
        except BaseException as guasto:
            self.guasto = guasto

    def ferma(self, entro: float = 10.0) -> None:
        if self._server is None:
            return
        self._server.should_exit = True
        if self._filo is not None:
            self._filo.join(timeout=entro)
            if self._filo.is_alive():
                self._server.force_exit = True
                self._filo.join(timeout=2.0)
