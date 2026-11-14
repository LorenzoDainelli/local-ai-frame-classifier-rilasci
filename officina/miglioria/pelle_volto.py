from __future__ import annotations

import numpy as np

SICUREZZA = 0.5


def _area(riquadro) -> float:
    return max(0.0, riquadro[2] - riquadro[0]) * max(0.0, riquadro[3] - riquadro[1])


def proposta_piu_grande(rilevatore, pixel: np.ndarray):
    from officina.volti import insight

    quadro = np.ascontiguousarray(np.asarray(pixel)[..., :3])
    proposte = []
    for lato in insight.LATI_DEL_QUADRATO:
        piccola, scala = insight._rimpicciolita(quadro, lato)
        proposte.extend(
            ([v / scala for v in riquadro], [(x / scala, y / scala) for x, y in punti], s)
            for riquadro, punti, s in rilevatore._proposte(piccola) if s >= SICUREZZA)
    if not proposte:
        return None
    proposte.sort(key=lambda voce: -voce[2])
    tenute = insight._togli_i_doppioni(proposte, insight.SOVRAPPOSIZIONE_MASSIMA)
    return max(tenute, key=lambda voce: _area(voce[0]))


def volto_di(rilevatore, pixel: np.ndarray) -> dict:
    trovata = proposta_piu_grande(rilevatore, pixel)
    if trovata is None:
        return {}
    riquadro, punti, sicurezza = trovata
    quadro = np.ascontiguousarray(np.asarray(pixel)[..., :3])
    dritta = rilevatore._raddrizza(None, quadro, punti, np)
    impronta = None if dritta is None else rilevatore._impronta_di(dritta, np)
    return {"riquadro": [float(v) for v in riquadro],
            "punti": [(float(x), float(y)) for x, y in punti],
            "sicurezza": float(sicurezza), "impronta": impronta}


def misuratore(rilevatore):
    rilevatore.accendi()
    return lambda pixel: volto_di(rilevatore, pixel)


__all__ = ["misuratore", "proposta_piu_grande", "volto_di"]
