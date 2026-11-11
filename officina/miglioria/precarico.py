from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

ALLINEA = 256


def _allinea(quanti: int) -> int:
    return (int(quanti) + ALLINEA - 1) // ALLINEA * ALLINEA


def _byte(dato) -> int:
    return int(dato.numel()) * int(dato.element_size())


def _sulla_scheda(dispositivo) -> bool:
    tipo = getattr(dispositivo, "type", None)
    if tipo is None:
        tipo = str(dispositivo).split(":")[0]
    return tipo == "cuda"


class Precarico:

    def __init__(self) -> None:
        self.acceso = False
        self.tolto: str | None = None
        self.usati = 0
        self._attesi: dict[int, tuple] = {}
        self._laterale = None
        self._fondo: ThreadPoolExecutor | None = None
        self._appoggio = None

    def attivo(self, dispositivo) -> bool:
        return self.acceso and self.tolto is None and _sulla_scheda(dispositivo)

    def accendi(self, acceso: bool) -> None:
        acceso = bool(acceso)
        if acceso == self.acceso:
            return
        self.lascia()
        self.acceso = acceso
        self.tolto = None

    def togli(self, motivo: str) -> bool:
        if not self.acceso or self.tolto is not None:
            return False
        self.tolto = motivo
        self.lascia()
        return True

    def ha_appoggio(self) -> bool:
        return self._appoggio is not None

    def fai_appoggio(self, quanti: int) -> bool:
        import torch

        quanti = _allinea(quanti) + ALLINEA * 64
        if self._appoggio is not None and int(self._appoggio.numel()) >= quanti:
            return True
        self._appoggio = None
        try:
            self._appoggio = torch.empty(quanti, dtype=torch.uint8, pin_memory=True)
        except RuntimeError:
            self._appoggio = None
        return self._appoggio is not None

    def riassunto(self) -> dict:
        fatto = {"usati": self.usati, **({"tolto": self.tolto} if self.tolto else {})}
        self.usati = 0
        return fatto

    def entra(self, blocchi: list, numero: int, dispositivo, parti_di) -> None:
        import torch

        pronto = self._attesi.pop(numero, None)
        self._scarta()
        corrente = torch.cuda.current_stream(dispositivo)
        preso = None
        if pronto is not None:
            try:
                preso = self._aspetta(pronto)
            except Exception as errore:
                self.togli(type(errore).__name__)
        parti = parti_di(blocchi[numero])
        if preso is None:
            for parte in parti:
                parte.data = parte._in_ram.to(dispositivo, non_blocking=True)
        else:
            evento, nuovi = preso
            corrente.wait_event(evento)
            for parte, dato in zip(parti, nuovi, strict=True):
                dato.record_stream(corrente)
                parte.data = dato
            self.usati += 1
        if self.tolto is None and numero + 1 < len(blocchi):
            try:
                lanciato = self._lancia(parti_di(blocchi[numero + 1]), dispositivo)
            except Exception as errore:
                self.togli(type(errore).__name__)
                return
            if lanciato is not None:
                self._attesi[numero + 1] = lanciato

    def _flusso(self, dispositivo):
        import torch

        if self._laterale is None:
            self._laterale = torch.cuda.Stream(device=dispositivo)
        return self._laterale

    def _lancia(self, parti: list, dispositivo):
        import torch

        sorgenti = [parte._in_ram for parte in parti]
        if any(sorgente.device.type != "cpu" for sorgente in sorgenti):
            return None
        if all(sorgente.is_pinned() for sorgente in sorgenti):
            flusso = self._flusso(dispositivo)
            evento = torch.cuda.Event()
            flusso.wait_stream(torch.cuda.current_stream(dispositivo))
            with torch.cuda.stream(flusso):
                nuovi = [sorgente.to(dispositivo, non_blocking=True)
                         for sorgente in sorgenti]
                evento.record(flusso)
            return ("subito", evento, nuovi)
        if self._appoggio is None or not all(s.is_contiguous() for s in sorgenti):
            return None
        if sum(_allinea(_byte(s)) for s in sorgenti) > int(self._appoggio.numel()):
            return None
        flusso = self._flusso(dispositivo)
        flusso.wait_stream(torch.cuda.current_stream(dispositivo))
        if self._fondo is None:
            self._fondo = ThreadPoolExecutor(max_workers=1,
                                             thread_name_prefix="miglioria-precarico")
        return ("fondo", self._fondo.submit(self._dal_disco, sorgenti, dispositivo), None)

    def _dal_disco(self, sorgenti: list, dispositivo):
        import torch

        viste = []
        da = 0
        for sorgente in sorgenti:
            quanti = _byte(sorgente)
            vista = self._appoggio[da:da + quanti].view(sorgente.dtype).view(sorgente.shape)
            vista.copy_(sorgente)
            viste.append(vista)
            da += _allinea(quanti)
        flusso = self._flusso(dispositivo)
        evento = torch.cuda.Event()
        with torch.cuda.stream(flusso):
            nuovi = [vista.to(dispositivo, non_blocking=True) for vista in viste]
            evento.record(flusso)
        evento.synchronize()
        return evento, nuovi

    def _aspetta(self, pronto: tuple):
        genere, primo, secondo = pronto
        if genere == "fondo":
            return primo.result()
        return primo, secondo

    def _scarta(self) -> None:
        attesi, self._attesi = self._attesi, {}
        for pronto in attesi.values():
            try:
                evento, _nuovi = self._aspetta(pronto)
                evento.synchronize()
            except Exception:
                pass

    def svuota(self) -> None:
        self._scarta()

    def lascia(self) -> None:
        self._scarta()
        if self._fondo is not None:
            self._fondo.shutdown(wait=True)
            self._fondo = None
        self._appoggio = None


__all__ = ["ALLINEA", "Precarico"]
