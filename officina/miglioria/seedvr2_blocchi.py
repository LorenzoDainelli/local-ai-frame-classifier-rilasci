from __future__ import annotations

import math

from officina.errori import ErroreOfficina

MARGINE_RAM = 3 * 2 ** 30
GIGA = 2 ** 30


class RamPoca(ErroreOfficina):
    codice = "ram_poca"
    senza_nomi = True

    def __init__(self, serve: int, libera: int, chi: str = "SeedVR2") -> None:
        super().__init__(f"Per {chi} servono almeno {math.ceil(serve / GIGA)} GB di RAM "
                         f"libera e ce ne sono {libera // GIGA}.")
        self.serve = int(serve)
        self.libera = int(libera)

    def dati(self) -> dict:
        return {"serve": self.serve, "libera": self.libera}


class DiscoNonBasta(RamPoca):
    codice = "ram_poca_anche_col_disco"


def ram_libera() -> int | None:
    try:
        import psutil
    except ImportError:
        return None
    return int(psutil.virtual_memory().available)


def in_giga(quanti: int) -> float:
    return round(quanti / GIGA, 1)


def _parti(modulo) -> list:
    return list(modulo.parameters()) + list(modulo.buffers())


def peso(modulo) -> int:
    return sum(int(parte.numel()) * int(parte.element_size()) for parte in _parti(modulo))


def quanti_ne_stanno(pesi: list[int], posto: int) -> int:
    usati = 0
    for numero, quanto in enumerate(pesi):
        if usati + quanto > posto:
            return numero
        usati += quanto
    return len(pesi)


def quanti_in_ram(pesi: list[int], libera: int | None, fisso: int, disco: bool,
                  chi: str = "SeedVR2") -> int:
    if libera is None:
        return len(pesi)
    posto = libera - MARGINE_RAM - fisso
    if posto >= sum(pesi):
        return len(pesi)
    if not disco:
        raise RamPoca(MARGINE_RAM + fisso + sum(pesi), libera, chi)
    if posto < max(pesi, default=0):
        raise DiscoNonBasta(MARGINE_RAM + fisso + max(pesi, default=0), libera, chi)
    return quanti_ne_stanno(pesi, posto)


def _svuota_la_ram_fissata() -> None:
    try:
        import torch
    except ImportError:
        return
    svuota = getattr(getattr(torch, "_C", None), "_host_emptyCache", None)
    if svuota is not None:
        try:
            svuota()
        except RuntimeError:
            pass


class Blocchi:

    def __init__(self, disco: bool = False, fissa: bool = True,
                 chi: str = "SeedVR2") -> None:
        self.disco = bool(disco)
        self.chi = chi
        self.fissa = fissa
        self.fuori: list = []
        self.in_ram: list[bool] = []
        self.pesi: list[int] = []
        self.fisso = 0
        self.girato = False
        self.dispositivo = None
        self._ganci: list = []

    def _copia(self, dato):
        if self.fissa:
            try:
                return dato.pin_memory()
            except RuntimeError:
                self.fissa = False
        return dato.clone()

    def prendi(self, modello, libera: int | None) -> None:
        quanti = int(getattr(modello, "blocks_to_swap", -1)) + 1
        blocchi = list(modello.blocks)[:max(quanti, 0)]
        if blocchi == self.fuori and all(getattr(b, "_officina", False) for b in blocchi):
            return
        self.togli()
        pesi = [peso(blocco) for blocco in blocchi]
        fisso = max(peso(modello) - sum(pesi), 0)
        dentro = quanti_in_ram(pesi, libera, fisso, self.disco, self.chi)
        self.dispositivo = modello.main_device
        self.pesi, self.fisso = pesi, fisso
        for numero, blocco in enumerate(blocchi):
            for parte in _parti(blocco):
                parte._dal_file = parte.data
                parte._in_ram = self._copia(parte.data) if numero < dentro else parte.data
                parte.data = parte._in_ram
            blocco._officina = True
            self._ganci.append(blocco.register_forward_pre_hook(self._entra))
            self._ganci.append(blocco.register_forward_hook(self._esce))
            self.fuori.append(blocco)
            self.in_ram.append(numero < dentro)

    def _entra(self, blocco, _ingresso) -> None:
        for parte in _parti(blocco):
            parte.data = parte._in_ram.to(self.dispositivo, non_blocking=True)

    def _esce(self, blocco, _ingresso, _uscita) -> None:
        for parte in _parti(blocco):
            parte.data = parte._in_ram

    def _sul_disco(self, numero: int) -> None:
        for parte in _parti(self.fuori[numero]):
            parte._in_ram = parte._dal_file
            parte.data = parte._dal_file
        self.in_ram[numero] = False

    def _nella_ram(self, numero: int) -> None:
        for parte in _parti(self.fuori[numero]):
            parte._in_ram = self._copia(parte._dal_file)
            parte.data = parte._in_ram
        self.in_ram[numero] = True

    def ribilancia(self, libera: int | None) -> bool:
        if libera is None or not self.fuori:
            return False
        posto = libera - MARGINE_RAM - (self.fisso if not self.girato else 0)
        cambiato = False
        if posto < 0:
            for numero in reversed(range(len(self.fuori))):
                if posto >= 0:
                    break
                if self.in_ram[numero]:
                    self._sul_disco(numero)
                    posto += self.pesi[numero]
                    cambiato = True
            if cambiato:
                _svuota_la_ram_fissata()
            return cambiato
        for numero in range(len(self.fuori)):
            if not self.in_ram[numero] and self.pesi[numero] <= posto:
                self._nella_ram(numero)
                posto -= self.pesi[numero]
                cambiato = True
        return cambiato

    def dove_stanno(self) -> dict | None:
        if not self.fuori:
            return None
        in_ram = sum(p for p, dentro in zip(self.pesi, self.in_ram, strict=True) if dentro)
        return {"scheda": in_giga(self.fisso), "ram": in_giga(in_ram),
                "disco": in_giga(sum(self.pesi) - in_ram)}

    def togli(self) -> None:
        for gancio in self._ganci:
            gancio.remove()
        for blocco in self.fuori:
            for parte in _parti(blocco):
                dal_file = getattr(parte, "_dal_file", None)
                if dal_file is not None:
                    parte.data = dal_file
                for nome in ("_in_ram", "_dal_file"):
                    if hasattr(parte, nome):
                        delattr(parte, nome)
            if hasattr(blocco, "_officina"):
                del blocco._officina
        tenuti = any(self.in_ram)
        self._ganci, self.fuori, self.in_ram, self.pesi = [], [], [], []
        self.fisso = 0
        self.girato = False
        if tenuti:
            _svuota_la_ram_fissata()


def non_avvolgere(*_argomenti, **_chiavi) -> None:
    return None


__all__ = ["Blocchi", "DiscoNonBasta", "GIGA", "MARGINE_RAM", "RamPoca", "in_giga",
           "non_avvolgere", "peso", "quanti_in_ram", "quanti_ne_stanno", "ram_libera"]
