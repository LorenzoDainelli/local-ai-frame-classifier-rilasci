from __future__ import annotations

import math
from typing import Iterable, Iterator

QUADRI = 60
PEZZO = 20
LEGATI = 1
PASSI = 16
SPINTA = 8.0
T_LEGATO = 0.1


class Lettore:

    def __init__(self, quadri: Iterable) -> None:
        self._fonte = iter(quadri)
        self._tenuti: dict[int, object] = {}
        self._letti = 0
        self._finito = False
        self.forma = None

    def almeno(self, quanti: int) -> bool:
        while self._letti < quanti and not self._finito:
            try:
                quadro = next(self._fonte)
            except StopIteration:
                self._finito = True
                break
            if self.forma is None:
                self.forma = tuple(quadro.shape)
            self._tenuti[self._letti] = quadro
            self._letti += 1
        return self._letti >= quanti

    def quanti(self) -> int | None:
        return self._letti if self._finito else None

    def prendi(self, da: int, a: int) -> list:
        self.almeno(a)
        fino = min(a, self._letti)
        return [self._tenuti[n] for n in range(da, fino)]

    def dimentica_prima(self, da: int) -> None:
        for numero in [n for n in self._tenuti if n < da]:
            del self._tenuti[numero]


def contati(lettore: Lettore, fino: int, volte: int) -> int:
    voluti = math.ceil(max(int(fino), 0) / volte)
    lettore.almeno(voluti)
    return min(voluti, lettore._letti)


def segnati(lettore: Lettore, da: int, a: int, volte: int) -> list[bool]:
    contati(lettore, a, volte)
    fine = min(a, lettore._letti * volte)
    return [n % volte == 0 for n in range(da, max(da, fine))]


def c_e_oltre(lettore: Lettore, posto: int, volte: int) -> bool:
    return lettore.almeno(posto // volte + 1)


def valido(lettore: Lettore, indice: int, volte: int) -> bool:
    return lettore.almeno(math.ceil(indice / volte) + 1)


def tempi(passi: int = PASSI, spinta: float = SPINTA):
    import torch

    ts = torch.linspace(1.0, 0.0, steps=passi + 1).numpy()
    return spinta * ts / (1 + (spinta - 1) * ts)


def vicini_veri(quadri, segni: list[bool]):
    import torch

    msk = torch.tensor(segni, dtype=torch.bool)
    tenuti = torch.where(msk)[0]
    posti = torch.arange(len(segni))
    distanze = (posti.view(-1, 1) - tenuti.view(1, -1)).abs()
    return quadri[distanze.argmin(dim=1)]


class Giro:

    def __init__(self, motore, volte: int, passi: int = PASSI, spinta: float = SPINTA,
                 t_legato: float = T_LEGATO) -> None:
        self.motore = motore
        self.volte = int(volte)
        self.passi = int(passi)
        self.spinta = float(spinta)
        self.t_legato = float(t_legato)
        self.nt = QUADRI // PEZZO

    def _entrata(self, lettore: Lettore, da: int, a: int):
        import torch
        import torch.nn.functional as F
        from einops import rearrange, repeat

        motore = self.motore
        segni = segnati(lettore, da, a, self.volte)
        primo = contati(lettore, da, self.volte)
        ultimo = contati(lettore, a, self.volte)
        quadri = motore.in_tensore(lettore.prendi(primo, ultimo))
        msk = torch.tensor(segni, dtype=torch.bool)
        msk = F.pad(msk, (0, QUADRI - len(msk)))
        lq = vicini_veri(quadri, msk.tolist())
        lq = rearrange(lq, "t c h w -> 1 c t h w").to(dtype=motore.tipo).div(127.5).sub(1)
        msk = repeat(msk, "t -> 1 1 t h w", h=lq.shape[-2], w=lq.shape[-1]).to(
            dtype=motore.tipo)
        y = motore.codifica(lq)
        m = motore.maschera(msk)
        return lq, msk, y, m

    def _fuori(self, xt, lq, msk, da: int, a: int):
        from einops import rearrange

        alto, largo = self.motore.alto, self.motore.largo
        xt = rearrange(xt, "1 nt nh nw c t h w -> 1 nt c t (nh h) (nw w)")
        fatto = self.motore.decodifica(xt, lq[:, :, da:a], msk[:, :, da:a])
        fatto = fatto[..., :alto, :largo]
        return rearrange(fatto, "1 c t h w -> t c h w").add(1).mul(127.5).clip(0, 255).byte()

    def _scendi(self, xt, y, m, ts):
        import torch

        motore = self.motore
        for i in range(self.passi):
            t = torch.tensor([ts[i]], device=motore.dispositivo, dtype=motore.tipo).expand(
                xt.shape[:-4]).contiguous()
            vt = motore.prevedi(xt, t, y, m)
            xt = xt + vt * (ts[i + 1] - ts[i])
            motore.passo_fatto()
        return xt

    def _scendi_legato(self, xt_cat, prima, dopo, y, m, ts):
        import torch

        motore = self.motore
        t_prima = torch.tensor([self.t_legato]).expand(prima.shape[:-4])
        t_dopo = None if dopo is None else torch.tensor([self.t_legato]).expand(
            dopo.shape[:-4])
        fino = None if dopo is None else self.nt - LEGATI
        for i in range(self.passi):
            pezzi = [prima, xt_cat] + ([] if dopo is None else [dopo])
            xt = torch.cat(pezzi, dim=1)
            t_cat = torch.tensor([ts[i]]).expand(xt_cat.shape[:-4])
            tempi_ = [t_prima, t_cat] + ([] if dopo is None else [t_dopo])
            t = torch.cat(tempi_, dim=1).to(device=motore.dispositivo, dtype=motore.tipo)
            vt = motore.prevedi(xt, t, y, m)[:, LEGATI:fino]
            xt_cat = xt_cat + vt * (ts[i + 1] - ts[i])
            motore.passo_fatto()
        return xt_cat

    def _rumore_legato(self, x0):
        import torch

        return x0 * (1 - self.t_legato) + torch.randn_like(x0) * self.t_legato

    def quadri(self, lettore: Lettore) -> Iterator:
        import torch

        nt, legati = self.nt, LEGATI
        ts = tempi(self.passi, self.spinta)

        lq, msk, y, m = self._entrata(lettore, 0, QUADRI)
        xt = self._scendi(torch.randn_like(y), y, m, ts)
        xt = xt[:, :nt - legati]
        x0_prima = xt[:, xt.shape[1] - legati:]
        uscita = self._fuori(xt, lq, msk, 0, (nt - legati) * PEZZO)
        yield from self._valide(lettore, uscita, 0)

        t0 = (nt - legati) * PEZZO
        passo = (nt - legati * 2) * PEZZO
        while c_e_oltre(lettore, t0 + passo, self.volte):
            lq, msk, y, m = self._entrata(lettore, t0 + passo - legati * PEZZO,
                                          t0 + passo * 2 + legati * PEZZO)
            xt = self._scendi(torch.randn_like(y), y, m, ts)
            xt = xt[:, legati:nt - legati]
            x0_salto = xt[:, :legati]
            x0_prima_dopo = xt[:, xt.shape[1] - legati:]
            uscita_salto = self._fuori(xt, lq, msk, legati * PEZZO, (nt - legati) * PEZZO)

            lq, msk, y, m = self._entrata(lettore, t0 - legati * PEZZO,
                                          t0 + passo + legati * PEZZO)
            xt_cat = torch.randn_like(y[:, legati:nt - legati])
            prima = self._rumore_legato(x0_prima)
            dopo = self._rumore_legato(x0_salto)
            xt = self._scendi_legato(xt_cat, prima, dopo, y, m, ts)
            uscita_cat = self._fuori(xt, lq, msk, legati * PEZZO, (nt - legati) * PEZZO)

            yield from self._valide(lettore, uscita_cat, t0)
            yield from self._valide(lettore, uscita_salto, t0 + passo)
            x0_prima = x0_prima_dopo
            t0 += passo * 2
            lettore.dimentica_prima(contati(lettore, t0 - legati * PEZZO, self.volte))

        if c_e_oltre(lettore, t0, self.volte):
            lq, msk, y, m = self._entrata(lettore, t0 - legati * PEZZO,
                                          t0 - legati * PEZZO + QUADRI)
            prima = self._rumore_legato(x0_prima)
            xt_cat = torch.randn_like(y[:, legati:])
            xt = self._scendi_legato(xt_cat, prima, None, y, m, ts)
            uscita = self._fuori(xt, lq, msk, legati * PEZZO, QUADRI)
            yield from self._valide(lettore, uscita, t0)

    def _valide(self, lettore: Lettore, uscita, da: int) -> Iterator:
        for numero in range(uscita.shape[0]):
            if not valido(lettore, da + numero, self.volte):
                return
            yield uscita[numero]


def finestre(quanti: int, volte: int) -> int:
    quanti, volte = int(quanti), int(volte)
    if quanti <= 0:
        return 0
    totale = quanti * volte
    nt = QUADRI // PEZZO
    t0 = (nt - LEGATI) * PEZZO
    passo = (nt - LEGATI * 2) * PEZZO
    fatte = 1
    while t0 + passo <= totale - 1:
        fatte += 2
        t0 += passo * 2
    if t0 < totale:
        fatte += 1
    return fatte


__all__ = ["Giro", "Lettore", "c_e_oltre", "contati", "finestre", "segnati", "tempi",
           "valido", "vicini_veri"]
