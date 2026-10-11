from __future__ import annotations

from officina.corpi import maschere
from officina.corpi.rilevatore import PUNTO_VISTO, VISO, VISO_DAL_CORPO

ALLARGA = 0.15
PUNTI_MINIMI = 3
BASTA_COI_PUNTI = 0.50
BASTA_COL_CONTORNO = 0.30


def punteggio(riquadro_corpo, maschera: bytes, punti, riquadro_volto) -> float:
    largo = _allargato(riquadro_volto)
    del_viso = [punti[i] for i in (*VISO_DAL_CORPO, *VISO) if i < len(punti)]
    visti = [(x, y) for x, y, sicuro in del_viso if sicuro >= PUNTO_VISTO]
    if len(visti) >= PUNTI_MINIMI:
        dentro = sum(1 for x, y in visti if _dentro(largo, x, y))
        if dentro < PUNTI_MINIMI:
            return 0.0
        return dentro / len(visti)
    cx = riquadro_volto[0] + riquadro_volto[2] / 2
    cy = riquadro_volto[1] + riquadro_volto[3] / 2
    if not maschere.c_e(maschera, riquadro_corpo, cx, cy):
        return 0.0
    if not maschera:
        return BASTA_COL_CONTORNO
    return 0.6 * maschere.quanto_copre(maschera, riquadro_corpo, riquadro_volto)


def abbina(corpi, volti) -> list[tuple[int, int, float]]:
    coppie = []
    for indice, corpo in enumerate(corpi):
        for volto_id, riquadro_volto in volti:
            voto = punteggio(corpo["riquadro"], corpo.get("maschera") or b"",
                             corpo.get("punti") or [], riquadro_volto)
            if voto >= _quanto_basta(corpo):
                coppie.append((voto, indice, volto_id))
    coppie.sort(key=lambda coppia: coppia[0], reverse=True)
    presi_corpi, presi_volti, fuori = set(), set(), []
    for voto, indice, volto_id in coppie:
        if indice in presi_corpi or volto_id in presi_volti:
            continue
        presi_corpi.add(indice)
        presi_volti.add(volto_id)
        fuori.append((indice, volto_id, round(voto, 3)))
    return fuori


def _quanto_basta(corpo) -> float:
    punti = corpo.get("punti") or []
    visti = sum(1 for i in (*VISO_DAL_CORPO, *VISO)
                if i < len(punti) and punti[i][2] >= PUNTO_VISTO)
    return BASTA_COI_PUNTI if visti >= PUNTI_MINIMI else BASTA_COL_CONTORNO


def _allargato(riquadro):
    x, y, larga, alta = riquadro
    return (x - larga * ALLARGA, y - alta * ALLARGA,
            larga * (1 + 2 * ALLARGA), alta * (1 + 2 * ALLARGA))


def _dentro(riquadro, x: float, y: float) -> bool:
    return (riquadro[0] <= x <= riquadro[0] + riquadro[2]
            and riquadro[1] <= y <= riquadro[1] + riquadro[3])
