from __future__ import annotations

import threading

from officina import registro

OGNI = 2.0
ASPETTA_A_FERMARSI = 10.0
DA_RIPARTIRE = "sicuro_da_ripartire"

IA = "ia"
MIGLIORAMENTO = "miglioramento"
RITOCCO = "ritocco"
GARA = "gara_video"
ORDINE = (IA, MIGLIORAMENTO, RITOCCO, GARA)
NOMI = {IA: "l'intelligenza artificiale", MIGLIORAMENTO: "il miglioramento",
        RITOCCO: "la coda del ritocco", GARA: "la gara dei video"}

ASPETTA_LA_COPIA = ("L'Archivio sicuro sta facendo la prima copia: {chi} parte da solo "
                    "appena finisce.")


class _Ia:

    def acceso(self) -> bool:
        from officina.web.strade import comune

        return comune.lavoro_ia.sta_lavorando

    def memoria(self) -> dict:
        from officina.web.strade import comune

        return {"scelti": list(comune.fila_ia["scelti"])}

    def ferma(self) -> None:
        from officina.web.strade import intelligenza

        intelligenza.ferma_la_fila()

    def riparti(self, archivio, memoria: dict) -> None:
        from officina.web.strade import intelligenza

        intelligenza.parti_la_fila(archivio, memoria.get("scelti"))


class _Miglioramento:

    def acceso(self) -> bool:
        from officina.web import miglioramento

        return miglioramento.sta_lavorando()

    def memoria(self) -> dict:
        return {}

    def ferma(self) -> None:
        from officina.archivio import accesso
        from officina.web.strade import miglioramento

        miglioramento.ferma_il_miglioramento(accesso.vero())

    def riparti(self, archivio, memoria: dict) -> None:
        from officina.web.strade import miglioramento

        miglioramento.avvia_il_miglioramento(archivio)


class _Ritocco:

    def acceso(self) -> bool:
        from officina.web import coda_ritocco

        return coda_ritocco.sta_lavorando()

    def memoria(self) -> dict:
        return {}

    def ferma(self) -> None:
        from officina.web import coda_ritocco

        coda_ritocco.ferma_la_coda(2.0)

    def riparti(self, archivio, memoria: dict) -> None:
        from officina.web import coda_ritocco

        coda_ritocco.riparti_se_accesa(archivio)


class _Gara:

    def acceso(self) -> bool:
        from officina.web import coda_ritocco

        return coda_ritocco.gara_in_corso()

    def memoria(self) -> dict:
        return {}

    def ferma(self) -> None:
        from officina.web import coda_ritocco

        coda_ritocco.ferma_la_gara(2.0)

    def riparti(self, archivio, memoria: dict) -> None:
        from officina.web import coda_ritocco

        coda_ritocco.parti_la_gara(archivio)


def _di_serie() -> dict:
    return {IA: _Ia(), MIGLIORAMENTO: _Miglioramento(), RITOCCO: _Ritocco(), GARA: _Gara()}


def _dalla_carta():
    from officina.programma import carta

    return carta.leggi().get(DA_RIPARTIRE)


def _nella_carta(valore: dict | None) -> None:
    from officina.programma import carta

    carta.aggiorna(**{DA_RIPARTIRE: valore})


def _l_archivio():
    from officina.archivio import accesso

    return accesso.vero()


def _vuota(dove: str | None = None) -> dict:
    return {"dove": dove, "lavori": {}}


def _valida(scritta) -> dict:
    if not isinstance(scritta, dict):
        return _vuota()
    dove = scritta.get("dove")
    lavori = scritta.get("lavori")
    if not isinstance(lavori, dict):
        lavori = {}
    return {"dove": dove if isinstance(dove, str) else None,
            "lavori": {nome: dict(valore) for nome, valore in lavori.items()
                       if nome in ORDINE and isinstance(valore, dict)}}


class Sosta:

    def __init__(self, lavori: dict | None = None, *, leggi=_dalla_carta,
                 scrivi=_nella_carta, archivio=_l_archivio, ogni: float = OGNI):
        self._lavori = lavori
        self._leggi = leggi
        self._scrivi = scrivi
        self._archivio = archivio
        self._ogni = ogni
        self._stato = threading.RLock()
        self._giro = threading.Lock()
        self._cambio = threading.Condition(threading.Lock())
        self._serve = None
        self._attiva = False
        self._basta = False
        self._presto = False
        self._ricordati: dict | None = None
        self._lasciati: set[str] = set()
        self._filo: threading.Thread | None = None

    @property
    def attiva(self) -> bool:
        with self._stato:
            return self._attiva

    def _il_lavoro(self, nome: str):
        if self._lavori is None:
            self._lavori = _di_serie()
        return self._lavori[nome]

    def guarda(self, serve, attiva: bool = False) -> None:
        with self._cambio:
            self._serve = serve
            self._basta = False
            with self._stato:
                self._attiva = bool(attiva)
            if self._filo is not None and self._filo.is_alive():
                self._presto = True
                self._cambio.notify_all()
                return
            self._presto = False
            self._filo = threading.Thread(target=self._gira, name="sosta-per-la-copia",
                                          daemon=True)
            self._filo.start()

    def subito(self) -> None:
        with self._cambio:
            self._presto = True
            self._cambio.notify_all()

    def smetti(self, aspetta: float = ASPETTA_A_FERMARSI) -> bool:
        with self._cambio:
            self._basta = True
            self._serve = None
            self._cambio.notify_all()
            filo = self._filo
        if filo is not None and filo is not threading.current_thread():
            filo.join(aspetta)
        return filo is None or not filo.is_alive()

    def _gira(self) -> None:
        while True:
            try:
                self.giro()
            except Exception as guasto:
                registro.errore("sosta.giro_rotto", **registro.dove_si_e_rotto(guasto))
            with self._cambio:
                if not self._basta and not self._presto:
                    self._cambio.wait(self._ogni)
                self._presto = False
                if self._basta:
                    self._filo = None
                    return

    def giro(self) -> None:
        with self._giro:
            with self._cambio:
                serve = None if self._basta else self._serve
            if serve is None:
                return
            try:
                adesso = serve()
            except Exception as guasto:
                registro.errore("sosta.non_so", **registro.dove_si_e_rotto(guasto))
                return
            if adesso is None or self._smesso():
                return
            with self._stato:
                if bool(adesso) != self._attiva:
                    registro.evento("sosta.comincia" if adesso else "sosta.finita")
                self._attiva = bool(adesso)
            if adesso:
                self._ferma_gli_accesi()
            else:
                self._fai_ripartire()

    def _ferma_gli_accesi(self) -> None:
        for nome in ORDINE:
            lavoro = self._il_lavoro(nome)
            try:
                acceso = lavoro.acceso()
                memoria = lavoro.memoria() if acceso else {}
            except Exception as guasto:
                registro.errore("sosta.non_guardato", lavoro=registro.Parola(nome),
                                **registro.dove_si_e_rotto(guasto))
                continue
            with self._stato:
                if not acceso:
                    self._lasciati.discard(nome)
                    continue
                if nome in self._lasciati:
                    continue
                self._ricorda(nome, memoria)
            try:
                lavoro.ferma()
            except Exception as guasto:
                registro.errore("sosta.non_fermato", lavoro=registro.Parola(nome),
                                **registro.dove_si_e_rotto(guasto))
                continue
            registro.evento("sosta.fermato", lavoro=registro.Parola(nome))

    def _fai_ripartire(self) -> None:
        with self._stato:
            if not self._memoria()["lavori"]:
                return
            try:
                archivio = self._archivio()
            except Exception:
                return
            ricordati = self._memoria()
            self._ricordati = _vuota()
            self._salva()
        dove = getattr(getattr(archivio, "dove", None), "nome", None)
        if ricordati["dove"] is None or ricordati["dove"] != dove:
            registro.avviso("sosta.archivio_cambiato", quanti=len(ricordati["lavori"]))
            return
        restano = [nome for nome in ORDINE if nome in ricordati["lavori"]]
        while restano:
            if self._smesso():
                self._rimetti(ricordati, restano)
                return
            nome = restano.pop(0)
            try:
                self._il_lavoro(nome).riparti(archivio, ricordati["lavori"][nome])
            except Exception as guasto:
                registro.errore("sosta.non_ripartito", lavoro=registro.Parola(nome),
                                **registro.dove_si_e_rotto(guasto))
                continue
            registro.evento("sosta.ripartito", lavoro=registro.Parola(nome))

    def _smesso(self) -> bool:
        with self._cambio:
            return self._basta

    def _rimetti(self, ricordati: dict, nomi: list[str]) -> None:
        with self._stato:
            memoria = self._memoria()
            if memoria["lavori"] and memoria["dove"] != ricordati["dove"]:
                registro.avviso("sosta.archivio_cambiato", quanti=len(nomi))
                return
            memoria["dove"] = ricordati["dove"]
            for nome in nomi:
                if nome not in self._lasciati:
                    memoria["lavori"].setdefault(nome, ricordati["lavori"][nome])
            self._salva()

    def _memoria(self) -> dict:
        if self._ricordati is None:
            try:
                scritta = self._leggi()
            except Exception as guasto:
                registro.avviso("sosta.non_letta", **registro.dove_si_e_rotto(guasto))
                scritta = None
            self._ricordati = _valida(scritta)
        return self._ricordati

    def _salva(self) -> None:
        ricordati = self._memoria()
        try:
            self._scrivi(ricordati if ricordati["lavori"] else None)
        except Exception as guasto:
            registro.avviso("sosta.non_salvata", **registro.dove_si_e_rotto(guasto))

    def _dove(self) -> str | None:
        try:
            return self._archivio().dove.nome
        except Exception:
            return None

    def _ricorda(self, nome: str, memoria: dict) -> None:
        ricordati = self._memoria()
        dove = self._dove()
        if dove is not None and ricordati["dove"] != dove:
            if ricordati["lavori"]:
                registro.avviso("sosta.archivio_cambiato", quanti=len(ricordati["lavori"]))
            ricordati = self._ricordati = _vuota(dove)
        ricordati["lavori"][nome] = dict(memoria)
        self._salva()

    def aspetta(self, nome: str, **memoria) -> bool:
        if nome not in ORDINE:
            raise ValueError(nome)
        with self._stato:
            self._lasciati.discard(nome)
            if not self._attiva:
                return False
            self._ricorda(nome, memoria)
        registro.evento("sosta.in_attesa", lavoro=registro.Parola(nome))
        return True

    def fermato_da_te(self, nome: str) -> None:
        if nome not in ORDINE:
            raise ValueError(nome)
        with self._stato:
            self._lasciati.add(nome)
            ricordati = self._memoria()
            if ricordati["lavori"].pop(nome, None) is not None:
                self._salva()

    def in_attesa(self) -> list[str]:
        with self._stato:
            lavori = self._memoria()["lavori"]
            return [nome for nome in ORDINE if nome in lavori]

    def aspetta_la_copia(self, nome: str) -> bool:
        return nome in self.in_attesa()

    def si_fermano(self) -> list[str]:
        accesi = []
        for nome in ORDINE:
            try:
                if self._il_lavoro(nome).acceso():
                    accesi.append(NOMI[nome])
            except Exception as guasto:
                registro.errore("sosta.non_guardato", lavoro=registro.Parola(nome),
                                **registro.dove_si_e_rotto(guasto))
        return accesi


per_la_copia = Sosta()
