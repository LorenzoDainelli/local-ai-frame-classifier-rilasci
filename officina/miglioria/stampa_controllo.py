from __future__ import annotations

import numpy as np

from officina.volti.gruppi import FORSE

SICUREZZA = 0.5
STESSA_PERSONA = FORSE
SPOSTAMENTO = 0.10
OCCHI_MINIMI = 24.0
STESSO_POSTO = 0.4
OCCHIO_SINISTRO = 0
OCCHIO_DESTRO = 1


def _sovrapposti(uno, altro) -> float:
    sinistra, sopra = max(uno[0], altro[0]), max(uno[1], altro[1])
    destra, sotto = min(uno[2], altro[2]), min(uno[3], altro[3])
    comune = max(0.0, destra - sinistra) * max(0.0, sotto - sopra)
    area = ((uno[2] - uno[0]) * (uno[3] - uno[1])
            + (altro[2] - altro[0]) * (altro[3] - altro[1]) - comune)
    return comune / area if area > 0 else 0.0


def volti(rilevatore, pixel: np.ndarray) -> list:
    from officina.volti import insight

    quadro = np.ascontiguousarray(np.asarray(pixel)[..., :3])
    proposte = []
    for lato in insight.LATI_DEL_QUADRATO:
        piccola, scala = insight._rimpicciolita(quadro, lato)
        proposte.extend(
            ([v / scala for v in riquadro], [(x / scala, y / scala) for x, y in punti], s)
            for riquadro, punti, s in rilevatore._proposte(piccola) if s >= SICUREZZA)
    proposte.sort(key=lambda voce: -voce[2])
    return insight._togli_i_doppioni(proposte, insight.SOVRAPPOSIZIONE_MASSIMA)


def impronta(rilevatore, pixel: np.ndarray, punti):
    quadro = np.ascontiguousarray(np.asarray(pixel)[..., :3])
    dritta = rilevatore._raddrizza(None, quadro, punti, np)
    return None if dritta is None else rilevatore._impronta_di(dritta, np)


def tra_gli_occhi(punti) -> float:
    punti = np.asarray(punti, dtype=np.float64)
    return float(np.linalg.norm(punti[OCCHIO_SINISTRO] - punti[OCCHIO_DESTRO]))


def somiglianza(a, b) -> float:
    if a is None or b is None:
        return 0.0
    a, b = np.asarray(a, dtype=np.float64), np.asarray(b, dtype=np.float64)
    sotto = float(np.linalg.norm(a) * np.linalg.norm(b))
    return float(a @ b) / sotto if sotto > 1e-12 else 0.0


def spostamento(punti_fatti, punti_veri) -> float:
    fatti = np.asarray(punti_fatti, dtype=np.float64)
    veri = np.asarray(punti_veri, dtype=np.float64)
    passo = tra_gli_occhi(veri)
    if passo <= 1e-6 or fatti.shape != veri.shape:
        return 1.0
    return float(np.linalg.norm(fatti - veri, axis=1).mean()) / passo


def _il_suo(riquadro, trovati):
    migliore, quanto = None, STESSO_POSTO
    for voce in trovati:
        sopra = _sovrapposti(riquadro, voce[0])
        if sopra >= quanto:
            migliore, quanto = voce, sopra
    return migliore


def controlla(rilevatore, vera: np.ndarray, fatte: dict, ingrandimento: float) -> dict:
    veri = volti(rilevatore, vera)
    trovati = {nome: volti(rilevatore, pixel) for nome, pixel in fatte.items()}
    esito = {nome: {"controllati": 0, "cambiati": 0, "piccoli": 0,
                    "persona": None, "spostati": None} for nome in fatte}
    for riquadro, punti, _sicurezza in veri:
        if tra_gli_occhi(punti) / max(ingrandimento, 1e-6) < OCCHI_MINIMI:
            for voce in esito.values():
                voce["piccoli"] += 1
            continue
        vera_impronta = impronta(rilevatore, vera, punti)
        for nome, pixel in fatte.items():
            voce = esito[nome]
            voce["controllati"] += 1
            suo = _il_suo(riquadro, trovati[nome])
            persona = 0.0 if suo is None else somiglianza(
                impronta(rilevatore, pixel, suo[1]), vera_impronta)
            spostati = 1.0 if suo is None else spostamento(suo[1], punti)
            if persona < STESSA_PERSONA or spostati > SPOSTAMENTO:
                voce["cambiati"] += 1
            voce["persona"] = round(min(persona, voce["persona"] if voce["persona"]
                                        is not None else 1.0), 3)
            voce["spostati"] = round(max(spostati, voce["spostati"] or 0.0), 3)
    return esito


__all__ = ["OCCHI_MINIMI", "SPOSTAMENTO", "STESSA_PERSONA", "controlla", "somiglianza",
           "spostamento", "volti"]
