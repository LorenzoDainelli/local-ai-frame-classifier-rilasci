from __future__ import annotations

import base64
import binascii
import os
import secrets
import threading
import zipfile
from pathlib import Path

from officina.errori import ErroreOfficina

FINE_PARZIALE = ".officina-parziale"
NON_SALVATO = "Il file non si è salvato: riprova."


class Salvataggi:

    def __init__(self, scegli):
        self._scegli = scegli
        self._aperti: dict[str, dict] = {}
        self._lucchetto = threading.Lock()

    def apri(self, nome: str) -> dict:
        nome = Path(str(nome or "")).name or "file"
        scelto = self._scegli(nome)
        if not scelto:
            return {"annullato": True}
        dove = Path(scelto)
        if not dove.suffix and Path(nome).suffix:
            dove = dove.with_suffix(Path(nome).suffix)
        parziale = dove.with_name(dove.name + FINE_PARZIALE)
        try:
            aperto = open(parziale, "wb")
        except OSError as guasto:
            raise ErroreOfficina(f"Non riesco a scrivere lì: {guasto.strerror or guasto}.",
                                 codice="salva_non_scrivo") from guasto
        chi = secrets.token_hex(12)
        with self._lucchetto:
            self._aperti[chi] = {"dove": dove, "parziale": parziale, "file": aperto,
                                 "scritti": 0}
        return {"chi": chi, "dove": str(dove)}

    def _di(self, chi: str) -> dict:
        with self._lucchetto:
            uno = self._aperti.get(str(chi))
        if uno is None:
            raise ErroreOfficina(NON_SALVATO, codice="salva_sconosciuto")
        return uno

    def pezzo(self, chi: str, testo: str) -> dict:
        uno = self._di(chi)
        try:
            dati = base64.b64decode(str(testo), validate=True)
        except (binascii.Error, ValueError) as guasto:
            self.lascia(chi)
            raise ErroreOfficina(NON_SALVATO, codice="salva_pezzo_storto") from guasto
        try:
            uno["file"].write(dati)
        except OSError as guasto:
            self.lascia(chi)
            perche = guasto.strerror or guasto
            raise ErroreOfficina(f"Il disco non accetta il file: {perche}.",
                                 codice="salva_disco") from guasto
        uno["scritti"] += len(dati)
        return {"scritti": uno["scritti"]}

    def lascia(self, chi: str) -> dict:
        with self._lucchetto:
            uno = self._aperti.pop(str(chi), None)
        if uno is not None:
            try:
                uno["file"].close()
            finally:
                Path(uno["parziale"]).unlink(missing_ok=True)
        return {"lasciato": True}

    def chiudi(self, chi: str, quanti: int) -> dict:
        uno = self._di(chi)
        with self._lucchetto:
            self._aperti.pop(str(chi), None)
        parziale, dove = Path(uno["parziale"]), Path(uno["dove"])
        try:
            uno["file"].flush()
            os.fsync(uno["file"].fileno())
            uno["file"].close()
            if uno["scritti"] != int(quanti) or parziale.stat().st_size != int(quanti):
                raise ErroreOfficina(NON_SALVATO, codice="salva_misura_diversa")
            if dove.suffix.lower() == ".zip":
                with zipfile.ZipFile(parziale) as letto:
                    if letto.testzip() is not None:
                        raise ErroreOfficina(NON_SALVATO, codice="salva_zip_rotto")
            os.replace(parziale, dove)
        except zipfile.BadZipFile as guasto:
            parziale.unlink(missing_ok=True)
            raise ErroreOfficina(NON_SALVATO, codice="salva_zip_rotto") from guasto
        except BaseException:
            uno["file"].close()
            parziale.unlink(missing_ok=True)
            raise
        return {"dove": str(dove), "byte": int(quanti)}


__all__ = ["FINE_PARZIALE", "NON_SALVATO", "Salvataggi"]
