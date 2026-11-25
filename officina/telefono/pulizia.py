from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from officina.telefono import formato

PARZIALE = ".parziale"
IN_CIMA = (formato.CARTA, formato.DATI, formato.RITORNO, ".cavo-locale.json", ".cavo.json")
A_CASO = re.compile(r"[0-9a-f]{32}(?:\.parziale)?")
SOTTO = re.compile(r"[0-9a-f]{2}")


@dataclass
class Pulita:
    tolti: int = 0
    rimasti: list[str] = field(default_factory=list)
    non_tolti: list[str] = field(default_factory=list)
    cartella_tolta: bool = False
    non_toccata: str = ""

    def a_parole(self) -> str:
        if self.non_toccata:
            return self.non_toccata
        if not self.tolti:
            return "Nella cartella di prima non c'era nessun file del pacchetto."
        detto = f"Tolti i {self.tolti} file del pacchetto di prima."
        if self.non_tolti:
            detto += (f" {len(self.non_tolti)} non si sono lasciati togliere, forse "
                      "perché aperti da un altro programma: riprova dopo.")
        if self.rimasti:
            detto += (f" Nella cartella restano {len(self.rimasti)} cose che non sono "
                      "del pacchetto: quelle non le tocco.")
        return detto


def _nostro_in_cima(nome: str) -> bool:
    return any(nome in (n, n + PARZIALE) for n in IN_CIMA)


def _togli(file: Path, esito: Pulita) -> None:
    try:
        file.unlink()
        esito.tolti += 1
    except FileNotFoundError:
        pass
    except OSError:
        esito.non_tolti.append(str(file))


def _togli_se_vuota(cartella: Path) -> bool:
    try:
        cartella.rmdir()
        return True
    except OSError:
        return False


def _nella_sottocartella(cartella: Path, esito: Pulita, con_due_lettere: bool) -> None:
    if not cartella.is_dir() or cartella.is_symlink():
        return
    for dentro in sorted(cartella.iterdir()):
        if con_due_lettere and dentro.is_dir() and not dentro.is_symlink() \
                and SOTTO.fullmatch(dentro.name):
            for file in sorted(dentro.iterdir()):
                if file.is_file() and A_CASO.fullmatch(file.name) \
                        and file.name.startswith(dentro.name):
                    _togli(file, esito)
                else:
                    esito.rimasti.append(str(file))
            _togli_se_vuota(dentro)
        elif not con_due_lettere and dentro.is_file() and A_CASO.fullmatch(dentro.name):
            _togli(dentro, esito)
        else:
            esito.rimasti.append(str(dentro))
    _togli_se_vuota(cartella)


def togli_il_pacchetto(cartella: Path | str | None, archivio: str, telefono: str) -> Pulita:
    esito = Pulita()
    if not cartella:
        return esito
    cartella = Path(cartella)
    if not cartella.is_dir() or cartella.is_symlink():
        return esito
    carta = cartella / formato.CARTA
    if not carta.is_file():
        esito.non_toccata = ("Nella cartella di prima non trovo la carta del pacchetto: "
                             "per sicurezza non tolgo niente.")
        return esito
    try:
        letta = formato.Carta.leggi(cartella)
    except Exception:                       # noqa: BLE001
        esito.non_toccata = ("La carta del pacchetto nella cartella di prima non si "
                             "legge: per sicurezza non tolgo niente.")
        return esito
    if letta.archivio != archivio or letta.telefono != telefono:
        esito.non_toccata = ("Nella cartella di prima c'è il pacchetto di un altro "
                             "archivio o di un altro telefono: non lo tocco.")
        return esito

    _nella_sottocartella(cartella / formato.FOTO, esito, con_due_lettere=True)
    _nella_sottocartella(cartella / formato.MINI, esito, con_due_lettere=True)
    _nella_sottocartella(cartella / formato.VOLTI, esito, con_due_lettere=False)
    for nome in IN_CIMA:
        if nome == formato.CARTA:
            continue
        for scelto in (nome, nome + PARZIALE):
            file = cartella / scelto
            if file.is_file():
                _togli(file, esito)
    parziale = cartella / (formato.CARTA + PARZIALE)
    if parziale.is_file():
        _togli(parziale, esito)
    if esito.non_tolti:
        return esito
    _togli(carta, esito)

    for dentro in cartella.iterdir():
        if not _nostro_in_cima(dentro.name) and dentro.name not in (
                formato.FOTO, formato.MINI, formato.VOLTI):
            esito.rimasti.append(str(dentro))
    if _togli_se_vuota(cartella):
        esito.cartella_tolta = True
        if cartella.parent.name == "Visore":
            _togli_se_vuota(cartella.parent)
    return esito
