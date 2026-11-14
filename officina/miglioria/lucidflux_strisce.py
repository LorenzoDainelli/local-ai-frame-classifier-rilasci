from __future__ import annotations

PIXEL_PER_STRISCIA = 2 ** 18
RIGHE_MINIME = 8


def righe_per(larghezza: int) -> int:
    return max(RIGHE_MINIME, PIXEL_PER_STRISCIA // max(1, int(larghezza)))


def statistiche(x, gruppi: int, righe: int):
    import torch

    quanti, canali, altezza, larghezza = x.shape
    somma = torch.zeros(quanti, gruppi, dtype=torch.float64, device=x.device)
    quadrati = torch.zeros_like(somma)
    for inizio in range(0, altezza, righe):
        pezzo = x[:, :, inizio:inizio + righe].double().reshape(quanti, gruppi, -1)
        somma += pezzo.sum(-1)
        quadrati += (pezzo * pezzo).sum(-1)
        del pezzo
    tanti = (canali // gruppi) * altezza * larghezza
    media = somma / tanti
    varianza = (quadrati / tanti - media * media).clamp_min(0.0)
    return media, varianza


def norma_e_swish(pezzo, norma, media, varianza):
    import torch

    quanti, canali = pezzo.shape[:2]
    gruppi = norma.num_groups
    scala = torch.rsqrt(varianza + norma.eps).to(pezzo.dtype)[..., None]
    centro = media.to(pezzo.dtype)[..., None]
    fuori = ((pezzo.reshape(quanti, gruppi, -1) - centro) * scala).reshape(pezzo.shape)
    fuori = fuori * norma.weight.to(pezzo.dtype)[None, :, None, None] \
        + norma.bias.to(pezzo.dtype)[None, :, None, None]
    return fuori * torch.sigmoid(fuori)


def a_strisce(sorgente, altezza: int, conv, uscita, righe: int, aggiungi=None) -> None:
    import torch.nn.functional as F

    for inizio in range(0, altezza, righe):
        fine = min(altezza, inizio + righe)
        da, a = max(0, inizio - 1), min(altezza, fine + 1)
        pezzo = sorgente(da, a)
        sopra = 1 if inizio == 0 else 0
        sotto = 1 if fine == altezza else 0
        if sopra or sotto:
            pezzo = F.pad(pezzo, (0, 0, sopra, sotto))
        fatto = F.conv2d(pezzo, conv.weight, conv.bias, padding=(0, 1))
        del pezzo
        if aggiungi is not None:
            fatto = aggiungi(inizio, fine) + fatto
        uscita[:, :, inizio:fine] = fatto
        del fatto


def resnet(blocco, x, righe: int):
    import torch

    quanti, _canali, altezza, larghezza = x.shape
    media, varianza = statistiche(x, blocco.norm1.num_groups, righe)
    mezzo = torch.empty((quanti, blocco.out_channels, altezza, larghezza),
                        dtype=x.dtype, device=x.device)
    a_strisce(lambda da, a: norma_e_swish(x[:, :, da:a], blocco.norm1, media, varianza),
              altezza, blocco.conv1, mezzo, righe)
    media, varianza = statistiche(mezzo, blocco.norm2.num_groups, righe)
    if blocco.in_channels != blocco.out_channels:
        uscita = torch.empty_like(mezzo)

        def aggiungi(inizio, fine):
            return blocco.nin_shortcut(x[:, :, inizio:fine])
    else:
        uscita = x

        def aggiungi(inizio, fine):
            return x[:, :, inizio:fine]
    a_strisce(lambda da, a: norma_e_swish(mezzo[:, :, da:a], blocco.norm2, media, varianza),
              altezza, blocco.conv2, uscita, righe, aggiungi)
    return uscita


def su(sali, x, righe: int):
    import torch
    import torch.nn.functional as F

    quanti, canali, altezza, larghezza = x.shape
    uscita = torch.empty((quanti, sali.conv.out_channels, altezza * 2, larghezza * 2),
                         dtype=x.dtype, device=x.device)

    def sorgente(da, a):
        primo, ultimo = da // 2, (a - 1) // 2 + 1
        grande = F.interpolate(x[:, :, primo:ultimo], scale_factor=2.0, mode="nearest")
        return grande[:, :, da - 2 * primo:a - 2 * primo]

    a_strisce(sorgente, altezza * 2, sali.conv, uscita, righe)
    return uscita


def fine(decoder, x, righe: int):
    import torch

    quanti, _canali, altezza, larghezza = x.shape
    media, varianza = statistiche(x, decoder.norm_out.num_groups, righe)
    uscita = torch.empty((quanti, decoder.conv_out.out_channels, altezza, larghezza),
                         dtype=x.dtype, device=x.device)
    a_strisce(lambda da, a: norma_e_swish(x[:, :, da:a], decoder.norm_out, media, varianza),
              altezza, decoder.conv_out, uscita, righe)
    return uscita


def decodifica(ae, z, righe: int | None = None):
    import torch

    decoder = ae.decoder
    with torch.no_grad():
        z = z.to(next(decoder.parameters()).dtype)
        z = z / ae.scale_factor + ae.shift_factor
        larghezza_finale = z.shape[-1] * decoder.ffactor
        passo = righe or righe_per(larghezza_finale)
        h = decoder.conv_in(z)
        del z
        h = resnet(decoder.mid.block_1, h, passo)
        h = decoder.mid.attn_1(h)
        h = resnet(decoder.mid.block_2, h, passo)
        for livello in reversed(range(decoder.num_resolutions)):
            salita = decoder.up[livello]
            for numero, blocco in enumerate(salita.block):
                h = resnet(blocco, h, passo)
                if len(salita.attn) > 0:
                    h = salita.attn[numero](h)
            if livello != 0:
                h = su(salita.upsample, h, passo)
        return fine(decoder, h, passo)


__all__ = ["PIXEL_PER_STRISCIA", "RIGHE_MINIME", "a_strisce", "decodifica", "fine",
           "norma_e_swish", "resnet", "righe_per", "statistiche", "su"]
