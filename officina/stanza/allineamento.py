from __future__ import annotations

import numpy as np


def umeyama(sorgente, destinazione, con_scala: bool = True):
    sorgente = np.asarray(sorgente, dtype=np.float64)
    destinazione = np.asarray(destinazione, dtype=np.float64)
    quanti = sorgente.shape[1]
    media_s = sorgente.mean(axis=1)
    media_d = destinazione.mean(axis=1)
    varianza = 1.0 / quanti * (np.linalg.norm(sorgente - media_s[:, None]) ** 2)
    somma = np.zeros((sorgente.shape[0], sorgente.shape[0]))
    for i in range(quanti):
        somma += np.outer(destinazione[:, i] - media_d, sorgente[:, i] - media_s)
    incrocio = np.multiply(1.0 / quanti, somma)
    u, d, v = np.linalg.svd(incrocio)
    if np.count_nonzero(d > np.finfo(d.dtype).eps) < sorgente.shape[0] - 1:
        raise ValueError("le macchine stanno tutte in fila: non si possono allineare")
    segni = np.eye(sorgente.shape[0])
    if np.linalg.det(u) * np.linalg.det(v) < 0.0:
        segni[-1, -1] = -1
    rotazione = u @ segni @ v
    scala = (1 / varianza) * np.trace(np.diag(d) @ segni) if con_scala else 1.0
    spostamento = media_d - scala * (rotazione @ media_s)
    return rotazione, spostamento, scala


def allinea_le_macchine(estrinseci_di_riferimento, estrinseci_stimati, ransac: bool = False,
                        giri: int = 10, seme: int | None = 42):
    def pose(estrinseci):
        estrinseci = np.asarray(estrinseci, dtype=np.float64)
        if estrinseci.shape[1] == 3:
            piene = np.repeat(np.eye(4)[None], len(estrinseci), 0)
            piene[:, :3, :4] = estrinseci
            estrinseci = piene
        rotazioni = estrinseci[:, :3, :3]
        girate = np.transpose(rotazioni, (0, 2, 1))
        fuori = np.repeat(np.eye(4)[None], len(estrinseci), 0)
        fuori[:, :3, :3] = girate
        fuori[:, :3, 3] = -np.einsum("nij,nj->ni", girate, estrinseci[:, :3, 3])
        return fuori

    riferimento = pose(estrinseci_di_riferimento)
    stimate = pose(estrinseci_stimati)

    def applica(poses, r, t, s):
        fuori = poses.copy()
        fuori[:, :3, :3] = r @ poses[:, :3, :3]
        fuori[:, :3, 3] = (r @ (s * poses[:, :3, 3].T)).T + t
        return fuori

    def una(indici):
        return umeyama(stimate[indici, :3, 3].T, riferimento[indici, :3, 3].T)

    tutti = np.arange(len(riferimento))
    r, t, s = una(tutti)
    if ransac:
        quanti = len(riferimento)
        sotto = max(3, (quanti + 1) // 2)
        allineate = applica(stimate, r, t, s)
        centri = riferimento[:, :3, 3]
        soglia = float(np.median([np.linalg.norm(centri - p[None], axis=1).min()
                                  for p in allineate[:, :3, 3]]))
        caso = np.random.default_rng(seme)
        migliore, buoni, punteggio = (r, t, s), None, (-1, np.inf)
        for _ in range(giri):
            scelti = caso.choice(tutti, size=sotto, replace=False)
            try:
                rr, tt, ss = una(scelti)
            except Exception:
                continue
            errori = np.linalg.norm(applica(stimate, rr, tt, ss)[:, :3, 3] - centri, axis=1)
            dentro = errori <= soglia
            k = int(dentro.sum())
            media = float(errori[dentro].mean()) if k > 0 else np.inf
            if k > punteggio[0] or (k == punteggio[0] and media < punteggio[1]):
                punteggio, migliore, buoni = (k, media), (rr, tt, ss), dentro
        r, t, s = una(tutti[buoni]) if buoni is not None and buoni.sum() >= 3 else migliore
    return r, t, s
