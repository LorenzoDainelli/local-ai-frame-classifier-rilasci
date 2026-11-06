from __future__ import annotations

import functools
from dataclasses import dataclass

FINESTRA = (2, 1, 1)
FFN_PEZZI = 65536
DOMANDE = 1 << 30
TESSERE = 8
MINIMO = 1024


@dataclass(frozen=True)
class Griglia:
    nt: int
    nh: int
    nw: int
    t: int
    h: int
    w: int

    @property
    def tessere(self) -> int:
        return self.nt * self.nh * self.nw

    @property
    def pezzi(self) -> int:
        return self.t * self.h * self.w

    def indice(self, it: int, ih: int, iw: int) -> int:
        return (it * self.nh + ih) * self.nw + iw

    def posto(self, indice: int) -> tuple[int, int, int]:
        it, resto = divmod(int(indice), self.nh * self.nw)
        ih, iw = divmod(resto, self.nw)
        return it, ih, iw


class Fette:

    def __init__(self, ffn: int = FFN_PEZZI, domande: int = DOMANDE,
                 tessere: int = TESSERE) -> None:
        self.ffn = int(ffn)
        self.domande = int(domande)
        self.tessere = int(tessere)
        self.fuori = False

    def esci(self) -> bool:
        if self.fuori:
            return False
        self.fuori = True
        return True

    def dimezza(self, pezzi: int) -> bool:
        prima = (self.ffn, self.domande, self.tessere)
        self.ffn = max(MINIMO, self.ffn // 2)
        self.domande = max(MINIMO, min(self.domande, int(pezzi) * 4) // 2)
        self.tessere = max(1, self.tessere // 2)
        return (self.ffn, self.domande, self.tessere) != prima

    def scelte(self) -> dict:
        return {"ffn": self.ffn, "domande": self.domande, "tessere": self.tessere,
                **({"fuori": True} if self.fuori else {})}


def vicine(griglia: Griglia, it: int, ih: int, iw: int,
           finestra: tuple[int, int, int] = FINESTRA) -> tuple[int, ...]:
    ft, fh, fw = finestra
    return tuple(griglia.indice(jt, jh, jw)
                 for jt in range(max(0, it - ft), min(griglia.nt, it + ft + 1))
                 for jh in range(max(0, ih - fh), min(griglia.nh, ih + fh + 1))
                 for jw in range(max(0, iw - fw), min(griglia.nw, iw + fw + 1)))


def riga(griglia: Griglia, ih: int) -> list[int]:
    return [griglia.indice(it, ih, iw)
            for it in range(griglia.nt) for iw in range(griglia.nw)]


def gruppi(griglia: Griglia, ih: int, finestra: tuple[int, int, int] = FINESTRA,
           ) -> list[tuple[list[int], tuple[int, ...]]]:
    insieme: dict[tuple[int, ...], list[int]] = {}
    for indice in sorted(riga(griglia, ih)):
        it, _ih, iw = griglia.posto(indice)
        insieme.setdefault(vicine(griglia, it, ih, iw, finestra), []).append(indice)
    return sorted(((domande, chiavi) for chiavi, domande in insieme.items()),
                  key=lambda coppia: coppia[0][0])


def righe_servono(griglia: Griglia, ih: int, finestra: tuple[int, int, int] = FINESTRA):
    fh = finestra[1]
    return range(max(0, ih - fh), min(griglia.nh, ih + fh + 1))


def pezzi_per_volta(quanti: int, per_tessera: int) -> int:
    return max(1, int(quanti) // max(1, int(per_tessera)))


def rotazioni(modello, griglia: Griglia, indici, dispositivo):
    import torch

    rope = modello.rope
    dimensione = rope.attention_head_dim
    tutte = rope.freqs.to(dispositivo)
    parti = tutte.split_with_sizes(
        [dimensione // 2 - 2 * (dimensione // 6), dimensione // 6, dimensione // 6], dim=1)
    fatte = []
    for indice in indici:
        it, ih, iw = griglia.posto(indice)
        tempo = parti[0][it * griglia.t:(it + 1) * griglia.t]
        alto = parti[1][ih * griglia.h:(ih + 1) * griglia.h]
        largo = parti[2][iw * griglia.w:(iw + 1) * griglia.w]
        forma = (griglia.t, griglia.h, griglia.w)
        fatte.append(torch.cat([
            tempo.view(griglia.t, 1, 1, -1).expand(*forma, -1),
            alto.view(1, griglia.h, 1, -1).expand(*forma, -1),
            largo.view(1, 1, griglia.w, -1).expand(*forma, -1),
        ], dim=-1).reshape(griglia.pezzi, -1))
    return torch.stack(fatte)


def ruota(dato, giri):
    import torch

    if giri is None:
        return dato
    complesso = torch.view_as_complex(dato.to(torch.float64).unflatten(3, (-1, 2)))
    return torch.view_as_real(complesso * giri.unsqueeze(1)).flatten(-2, -1).type_as(dato)


def _teste(attn, dato, tipo):
    return dato.unflatten(2, (attn.heads, -1)).transpose(1, 2).to(tipo)


def domande(attn, prima, x, indici, giri):
    tipo = x.dtype
    dentro = prima(x, indici)
    q = attn.to_q(dentro)
    if attn.norm_q is not None:
        q = attn.norm_q(q)
    return ruota(_teste(attn, q, tipo), giri)


def chiavi(attn, prima, x, indici, giri):
    tipo = x.dtype
    dentro = prima(x, indici)
    k = attn.to_k(dentro)
    v = attn.to_v(dentro)
    if attn.norm_k is not None:
        k = attn.norm_k(k)
    return ruota(_teste(attn, k, tipo), giri), _teste(attn, v, tipo)


def guarda(attn, q, k, v, fette: Fette):
    import torch
    import torch.nn.functional as F

    tessere, teste, pezzi, lato = q.shape
    tutte_q = q.permute(1, 0, 2, 3).reshape(1, teste, tessere * pezzi, lato)
    tutte_k = k.permute(1, 0, 2, 3).reshape(1, teste, -1, lato)
    tutte_v = v.permute(1, 0, 2, 3).reshape(1, teste, -1, lato)
    passo = max(1, fette.domande)
    uscite = [F.scaled_dot_product_attention(tutte_q[:, :, da:da + passo], tutte_k, tutte_v)
              for da in range(0, tessere * pezzi, passo)]
    uscita = torch.cat(uscite, dim=2) if len(uscite) > 1 else uscite[0]
    uscita = uscita.reshape(teste, tessere, pezzi, lato).permute(1, 0, 2, 3)
    uscita = uscita.transpose(1, 2).flatten(2, 3).type_as(q)
    uscita = attn.to_out[0](uscita)
    return attn.to_out[1](uscita)


def _a_pezzi(indici: list[int], quanti: int):
    for da in range(0, len(indici), max(1, quanti)):
        yield indici[da:da + max(1, quanti)]


def _righe(dato, indici, dispositivo):
    return dato.index_select(0, _dove(dato, indici)).to(dispositivo)


def passa_l_attenzione(attn, prima, dopo, x, griglia: Griglia, giri_di, fette: Fette,
                       finestra: tuple[int, int, int] = FINESTRA,
                       dispositivo=None) -> None:
    import torch

    dispositivo = x.device if dispositivo is None else dispositivo
    cache: dict[int, tuple] = {}

    def prepara(ih: int) -> None:
        if ih in cache:
            return
        tutte_k, tutte_v = [], []
        indici = riga(griglia, ih)
        for pezzo in _a_pezzi(indici, fette.tessere):
            k, v = chiavi(attn, prima, x, pezzo, giri_di(pezzo))
            tutte_k.append(k.to(x.device))
            tutte_v.append(v.to(x.device))
        cache[ih] = ({n: i for i, n in enumerate(indici)}, torch.cat(tutte_k),
                     torch.cat(tutte_v))

    def raccogli(indici):
        k, v = [], []
        for indice in indici:
            _it, ih, _iw = griglia.posto(indice)
            dove, ck, cv = cache[ih]
            k.append(ck[dove[indice]])
            v.append(cv[dove[indice]])
        return torch.stack(k).to(dispositivo), torch.stack(v).to(dispositivo)

    for ih in range(griglia.nh):
        for altra in righe_servono(griglia, ih, finestra):
            prepara(altra)
        fatte = []
        for interrogate, guardate in gruppi(griglia, ih, finestra):
            k, v = raccogli(guardate)
            for pezzo in _a_pezzi(interrogate, fette.tessere):
                q = domande(attn, prima, x, pezzo, giri_di(pezzo))
                fatte.append((pezzo, guarda(attn, q, k, v, fette)))
            del k, v
        for pezzo, uscita in fatte:
            dove = _dove(x, pezzo)
            vecchio = x.index_select(0, dove).to(uscita.device)
            nuovo = dopo(vecchio, _dove(uscita, pezzo), uscita)
            x.index_copy_(0, dove, nuovo.to(x.device))
        cache.pop(ih - finestra[1], None)


def passa_il_ffn(blocco, x, c_shift, c_scale, c_gate, fette: Fette) -> None:
    per = pezzi_per_volta(fette.ffn, x.shape[1])
    for da in range(0, x.shape[0], per):
        a = da + per
        pezzo = x[da:a].to(c_scale.device)
        dentro = (blocco.norm3(pezzo.float()) * (1 + c_scale[da:a]) + c_shift[da:a])
        uscita = blocco.ffn(dentro.type_as(pezzo))
        x[da:a] = (pezzo.float() + uscita.float() * c_gate[da:a]).type_as(pezzo).to(x.device)


def blocco_a_fette(blocco, x, temb, griglia: Griglia, giri_di, fette: Fette,
                   finestra: tuple[int, int, int] = FINESTRA):
    misto = blocco.scale_shift_table + temb.float()
    dispositivo = misto.device
    shift, scale, gate, c_shift, c_scale, c_gate = (parte.unsqueeze(1)
                                                    for parte in misto.unbind(1))

    def prima_uno(dato, indici):
        dove = _dove(misto, indici)
        pezzo = _righe(dato, indici, dispositivo)
        return (blocco.norm1(pezzo.float()) * (1 + scale[dove]) + shift[dove]).type_as(pezzo)

    def dopo_uno(vecchio, dove, uscita):
        return (vecchio.float() + uscita * gate[dove]).type_as(vecchio)

    def prima_due(dato, indici):
        pezzo = _righe(dato, indici, dispositivo)
        return blocco.norm2(pezzo.float()).type_as(pezzo)

    def dopo_due(vecchio, _dove_, uscita):
        return vecchio + uscita

    passa_l_attenzione(blocco.attn1, prima_uno, dopo_uno, x, griglia, giri_di, fette,
                       finestra, dispositivo)
    passa_l_attenzione(blocco.attn2, prima_due, dopo_due, x, griglia, _senza_giri, fette,
                       finestra, dispositivo)
    passa_il_ffn(blocco, x, c_shift, c_scale, c_gate, fette)
    return x


def _senza_giri(_indici):
    return None


def _dove(dato, indici):
    import torch

    return torch.as_tensor(list(indici), device=dato.device, dtype=torch.long)


def aggancia(modello, griglia_di, fette_di, giri_di_di) -> None:
    for blocco in modello.blocks:
        blocco.forward = functools.partial(_avanti_del_blocco, blocco, griglia_di, fette_di,
                                           giri_di_di)


def _avanti_del_blocco(blocco, griglia_di, fette_di, giri_di_di, x, temb):
    return blocco_a_fette(blocco, x, temb, griglia_di(), giri_di_di(), fette_di())


def _in_ram(forma, tipo, _in_piu=0):
    import torch

    return torch.empty(forma, dtype=tipo)


def byte_della_cache(griglia: Griglia, interno: int, tipo,
                     finestra: tuple[int, int, int] = FINESTRA) -> int:
    righe = min(griglia.nh, 2 * finestra[1] + 1)
    return 2 * righe * griglia.nt * griglia.nw * griglia.pezzi * interno * int(tipo.itemsize)


def avanti(modello, entrata, tempo, fette: Fette, giri_di=None, foglio=None):
    import torch

    uno, nt, nh, nw, canali, t, h, w = entrata.shape
    if uno != 1:
        raise ValueError(uno)
    p_t, p_h, p_w = modello.config.patch_size
    griglia = Griglia(nt, nh, nw, t // p_t, h // p_h, w // p_w)
    tessere = entrata.reshape(griglia.tessere, canali, t, h, w)
    interno = modello.patch_embedding.out_channels
    tipo = modello.patch_embedding.weight.dtype
    forma = (griglia.tessere, griglia.pezzi, interno)
    if fette.fuori:
        x = (foglio or _in_ram)(forma, tipo, byte_della_cache(griglia, interno, tipo))
    else:
        x = torch.empty(forma, dtype=tipo, device=entrata.device)
    per = pezzi_per_volta(fette.ffn, griglia.pezzi)
    for da in range(0, griglia.tessere, per):
        fatto = modello.patch_embedding(tessere[da:da + per])
        x[da:da + per] = fatto.flatten(2).transpose(1, 2).to(x.device)
    del fatto
    temb, proiezione, _testo, _immagine = modello.condition_embedder(
        tempo.reshape(griglia.tessere), None, None)
    proiezione = proiezione.unflatten(1, (6, -1))
    if giri_di is None:
        def giri_di(indici):
            return rotazioni(modello, griglia, indici, entrata.device)
    modello._officina_ora = (griglia, fette, giri_di)
    for blocco in modello.blocks:
        x = blocco(x, proiezione)
    shift, scale = modello.scale_shift_table.view(2, 1, 1, -1) + temb.unsqueeze(1)
    shift = shift.to(entrata.device)
    scale = scale.to(entrata.device)
    uscita_canali = modello.proj_out.out_features // (p_t * p_h * p_w)
    uscita = torch.empty(griglia.tessere, uscita_canali, t, h, w, dtype=x.dtype,
                         device=entrata.device)
    for da in range(0, griglia.tessere, per):
        a = da + per
        pezzo = x[da:a].to(entrata.device)
        fatto = (modello.norm_out(pezzo.float()) * (1 + scale[da:a]) + shift[da:a])
        fatto = modello.proj_out(fatto.type_as(pezzo))
        quante = fatto.shape[0]
        fatto = fatto.view(quante, griglia.t, griglia.h, griglia.w, p_t, p_h, p_w,
                           uscita_canali)
        uscita[da:a] = fatto.permute(0, 7, 1, 4, 2, 5, 3, 6).reshape(
            quante, uscita_canali, t, h, w).to(uscita.dtype)
    modello._officina_ora = None
    return uscita.view(1, nt, nh, nw, uscita_canali, t, h, w)


def prepara(modello) -> None:
    def griglia_di():
        return modello._officina_ora[0]

    def fette_di():
        return modello._officina_ora[1]

    def giri_di_di():
        return modello._officina_ora[2]

    modello._officina_ora = None
    aggancia(modello, griglia_di, fette_di, giri_di_di)


__all__ = ["FINESTRA", "Fette", "Griglia", "avanti", "blocco_a_fette", "byte_della_cache",
           "gruppi", "prepara",
           "riga", "righe_servono", "rotazioni", "ruota", "vicine"]
