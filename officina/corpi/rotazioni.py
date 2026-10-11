from __future__ import annotations

import math

import torch

ASSI = {"x": 0, "y": 1, "z": 2}


def quaternione_in_matrice(q):
    x, y, z, w = q[..., 0], q[..., 1], q[..., 2], q[..., 3]
    x2, y2, z2, w2 = x * x, y * y, z * z, w * w
    xy, zw, xz, yw, yz, xw = x * y, z * w, x * z, y * w, y * z, x * w
    return torch.stack((x2 - y2 - z2 + w2, 2 * (xy - zw), 2 * (xz + yw),
                        2 * (xy + zw), -x2 + y2 - z2 + w2, 2 * (yz - xw),
                        2 * (xz - yw), 2 * (yz + xw), -x2 - y2 + z2 + w2),
                       dim=-1).reshape(q.shape[:-1] + (3, 3))


def matrice_in_quaternione(R):
    forma = R.shape[:-2]
    m = R.reshape(-1, 3, 3)
    n = m.shape[0]
    decisione = torch.empty((n, 4), dtype=m.dtype, device=m.device)
    decisione[:, :3] = m.diagonal(dim1=1, dim2=2)
    decisione[:, -1] = decisione[:, :3].sum(axis=1)
    scelte = decisione.argmax(axis=1)
    q = torch.empty((n, 4), dtype=m.dtype, device=m.device)
    quali = torch.nonzero(scelte != 3, as_tuple=True)[0]
    i = scelte[quali]
    j = (i + 1) % 3
    k = (j + 1) % 3
    q[quali, i] = 1 - decisione[quali, -1] + 2 * m[quali, i, i]
    q[quali, j] = m[quali, j, i] + m[quali, i, j]
    q[quali, k] = m[quali, k, i] + m[quali, i, k]
    q[quali, 3] = m[quali, k, j] - m[quali, j, k]
    quali = torch.nonzero(scelte == 3, as_tuple=True)[0]
    q[quali, 0] = m[quali, 2, 1] - m[quali, 1, 2]
    q[quali, 1] = m[quali, 0, 2] - m[quali, 2, 0]
    q[quali, 2] = m[quali, 1, 0] - m[quali, 0, 1]
    q[quali, 3] = 1 + decisione[quali, -1]
    q = q / torch.norm(q, dim=1)[:, None]
    return q.reshape(forma + (4,))


def _prodotto(p, q):
    vettore = p[..., None, 3] * q[..., :3] + q[..., None, 3] * p[..., :3] + torch.cross(
        p[..., :3], q[..., :3], dim=-1)
    ultimo = p[..., 3] * q[..., 3] - torch.sum(p[..., :3] * q[..., :3], axis=-1)
    return torch.cat((vettore, ultimo[..., None]), dim=-1)


def _sinc(x, epsilon=1e-3):
    piccolo = x.abs() < epsilon
    x2 = x * x
    x4 = x2 * x2
    return torch.where(piccolo, 1 - x2 / 6 + x4 / 120,
                       torch.sin(x) / torch.where(piccolo, torch.ones_like(x), x))


def euler_in_quaternione(convenzione: str, angoli):
    angoli = [t.squeeze(dim=-1) for t in torch.split(angoli, 1, dim=-1)]
    if convenzione.islower():
        convenzione = convenzione.upper()[::-1]
        angoli = angoli[::-1]
    quaternioni = []
    for asse, angolo in zip(convenzione, angoli, strict=True):
        vettore = torch.zeros(angolo.shape + (3,), device=angolo.device, dtype=angolo.dtype)
        vettore[..., ASSI[asse.lower()]] = angolo
        norme = torch.norm(vettore, dim=-1)
        scala = _sinc(norme / 2) / 2.0
        quaternioni.append(torch.cat((scala[..., None] * vettore, torch.cos(norme / 2)[..., None]), -1))
    risultato = quaternioni[0]
    for q in quaternioni[1:]:
        risultato = _prodotto(risultato, q)
    return risultato / torch.norm(risultato, dim=-1, keepdim=True)


def euler_in_matrice(convenzione: str, angoli):
    return quaternione_in_matrice(euler_in_quaternione(convenzione, angoli))


def quaternione_in_euler(convenzione: str, quat, epsilon=1e-7):
    pi = math.pi
    estrinseca = convenzione.islower()
    if not estrinseca:
        convenzione = convenzione.lower()[::-1]
    forma = quat.shape[:-1]
    quat = quat.reshape(-1, 4)
    n = quat.shape[0]
    i, j, k = (ASSI[c] for c in convenzione)
    simmetrica = i == k
    if simmetrica:
        k = 3 - i - j
    segno = (i - j) * (j - k) * (k - i) // 2
    if simmetrica:
        a, b, c, d = quat[:, 3], quat[:, i], quat[:, j], quat[:, k] * segno
    else:
        a = quat[:, 3] - quat[:, j]
        b = quat[:, i] + quat[:, k] * segno
        c = quat[:, j] + quat[:, 3]
        d = quat[:, k] * segno - quat[:, i]
    primo, terzo = (0, 2) if estrinseca else (2, 0)
    angoli = [torch.empty(n, device=quat.device, dtype=quat.dtype) for _ in range(3)]
    angoli[1] = 2 * torch.atan2(torch.hypot(c, d), torch.hypot(a, b))
    caso1 = torch.abs(angoli[1]) <= epsilon
    caso2 = torch.abs(angoli[1] - pi) <= epsilon
    caso12 = torch.logical_or(caso1, caso2)
    mezza_somma = torch.atan2(b, a)
    mezza_differenza = torch.atan2(d, c)
    angoli[primo] = mezza_somma - mezza_differenza
    angoli[terzo] = mezza_somma + mezza_differenza
    angoli[2][caso12] = 0
    angoli[0][caso1] = 2 * mezza_somma[caso1]
    angoli[0][caso2] = 2 * (-1 if estrinseca else 1) * mezza_differenza[caso2]
    if not simmetrica:
        angoli[terzo] *= segno
        angoli[1] -= pi / 2
    for indice in range(3):
        valori = angoli[indice]
        valori[valori < -pi] += 2 * pi
        valori[valori > pi] -= 2 * pi
        angoli[indice] = valori.reshape(forma)
    return torch.stack(angoli, dim=-1)


def matrice_in_euler(convenzione: str, R, epsilon=1e-7):
    return quaternione_in_euler(convenzione, matrice_in_quaternione(R), epsilon)
