from __future__ import annotations

ANGOLI = ((0, 0), (1, 0), (0, 1), (1, 1))
MODI = ("sum", "avg", "linear", "softmax")


def spingi(entrata, flusso):
    import torch

    entrata = entrata.float()
    flusso = flusso.float()
    numero, canali, alto, largo = entrata.shape
    uscita = entrata.new_zeros((numero, canali, alto * largo))
    colonne = torch.arange(largo, device=entrata.device, dtype=torch.float32)
    righe = torch.arange(alto, device=entrata.device, dtype=torch.float32)
    x = colonne.view(1, 1, largo) + flusso[:, 0]
    y = righe.view(1, alto, 1) + flusso[:, 1]
    finiti = torch.isfinite(x) & torch.isfinite(y)
    x = torch.where(finiti, x, torch.zeros_like(x))
    y = torch.where(finiti, y, torch.zeros_like(y))
    x0 = torch.floor(x)
    y0 = torch.floor(y)
    piatta = entrata.reshape(numero, canali, alto * largo)
    for dx, dy in ANGOLI:
        xi = x0 + dx
        yi = y0 + dy
        dentro = finiti & (xi >= 0) & (xi < largo) & (yi >= 0) & (yi < alto)
        peso = (1 - (x - xi).abs()) * (1 - (y - yi).abs())
        peso = torch.where(dentro, peso, torch.zeros_like(peso))
        indice = torch.where(dentro, yi * largo + xi, torch.zeros_like(xi)).long()
        indice = indice.reshape(numero, 1, alto * largo).expand(numero, canali, alto * largo)
        uscita.scatter_add_(2, indice, piatta * peso.reshape(numero, 1, alto * largo))
    return uscita.reshape(numero, canali, alto, largo)


def softsplat(tenIn, tenFlow, tenMetric, strMode, return_norm=False):
    parti = strMode.split("-")
    if parti[0] not in MODI:
        raise ValueError(strMode)
    import torch

    entrata = tenIn.float()
    if parti[0] == "avg":
        uno = entrata.new_ones((entrata.shape[0], 1, entrata.shape[2], entrata.shape[3]))
        entrata = torch.cat([entrata, uno], 1)
    elif parti[0] == "linear":
        metrica = tenMetric.float()
        entrata = torch.cat([entrata * metrica, metrica], 1)
    elif parti[0] == "softmax":
        metrica = tenMetric.float().exp()
        entrata = torch.cat([entrata * metrica, metrica], 1)
    uscita = spingi(entrata, tenFlow)
    if parti[0] == "sum":
        return uscita
    norma = uscita[:, -1:, :, :]
    regola = parti[1] if len(parti) > 1 else "addeps"
    if regola == "addeps":
        norma = norma + 0.0000001
    elif regola == "zeroeps":
        norma = torch.where(norma == 0.0, torch.ones_like(norma), norma)
    elif regola == "clipeps":
        norma = norma.clip(0.0000001, None)
    if return_norm:
        return uscita[:, :-1, :, :], norma
    return uscita[:, :-1, :, :] / norma


__all__ = ["softsplat", "spingi"]
