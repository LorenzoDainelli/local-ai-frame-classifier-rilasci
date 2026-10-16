from __future__ import annotations

import torch
from torch.nn import functional as F


def inversa_affine(matrice: torch.Tensor) -> torch.Tensor:
    rotazione = matrice[..., :3, :3]
    spostamento = matrice[..., :3, 3:]
    resto = matrice[..., 3:, :]
    girata = rotazione.mT
    return torch.cat([torch.cat([girata, -girata @ spostamento], dim=-1), resto], dim=-2)


def _radice_positiva(x: torch.Tensor) -> torch.Tensor:
    fuori = torch.zeros_like(x)
    positivi = x > 0
    if torch.is_grad_enabled():
        fuori[positivi] = torch.sqrt(x[positivi])
        return fuori
    return torch.where(positivi, torch.sqrt(x), fuori)


def quaternione_a_matrice(quaternioni: torch.Tensor) -> torch.Tensor:
    i, j, k, r = torch.unbind(quaternioni, -1)
    due_s = 2.0 / (quaternioni * quaternioni).sum(-1)
    o = torch.stack((
        1 - due_s * (j * j + k * k), due_s * (i * j - k * r), due_s * (i * k + j * r),
        due_s * (i * j + k * r), 1 - due_s * (i * i + k * k), due_s * (j * k - i * r),
        due_s * (i * k - j * r), due_s * (j * k + i * r), 1 - due_s * (i * i + j * j),
    ), -1)
    return o.reshape(quaternioni.shape[:-1] + (3, 3))


def matrice_a_quaternione(matrice: torch.Tensor) -> torch.Tensor:
    lotto = matrice.shape[:-2]
    m00, m01, m02, m10, m11, m12, m20, m21, m22 = torch.unbind(matrice.reshape(lotto + (9,)), dim=-1)
    q_abs = _radice_positiva(torch.stack([
        1.0 + m00 + m11 + m22, 1.0 + m00 - m11 - m22,
        1.0 - m00 + m11 - m22, 1.0 - m00 - m11 + m22,
    ], dim=-1))
    per_rijk = torch.stack([
        torch.stack([q_abs[..., 0] ** 2, m21 - m12, m02 - m20, m10 - m01], dim=-1),
        torch.stack([m21 - m12, q_abs[..., 1] ** 2, m10 + m01, m02 + m20], dim=-1),
        torch.stack([m02 - m20, m10 + m01, q_abs[..., 2] ** 2, m12 + m21], dim=-1),
        torch.stack([m10 - m01, m20 + m02, m21 + m12, q_abs[..., 3] ** 2], dim=-1),
    ], dim=-2)
    pavimento = torch.tensor(0.1).to(dtype=q_abs.dtype, device=q_abs.device)
    candidati = per_rijk / (2.0 * q_abs[..., None].max(pavimento))
    fuori = candidati[F.one_hot(q_abs.argmax(dim=-1), num_classes=4) > 0.5, :].reshape(lotto + (4,))
    fuori = fuori[..., [1, 2, 3, 0]]
    return torch.where(fuori[..., 3:4] < 0, -fuori, fuori)


def codifica_posa(estrinseci: torch.Tensor, intrinseci: torch.Tensor, alto_largo) -> torch.Tensor:
    rotazione = estrinseci[:, :, :3, :3]
    spostamento = estrinseci[:, :, :3, 3]
    quaternione = matrice_a_quaternione(rotazione)
    alto, largo = alto_largo
    campo_alto = 2 * torch.atan((alto / 2) / intrinseci[..., 1, 1])
    campo_largo = 2 * torch.atan((largo / 2) / intrinseci[..., 0, 0])
    return torch.cat([spostamento, quaternione, campo_alto[..., None], campo_largo[..., None]], dim=-1).float()


def decodifica_posa(codice: torch.Tensor, alto_largo, limite: float | None = 1e-6):
    spostamento = codice[..., :3]
    quaternione = codice[..., 3:7]
    campo_alto = codice[..., 7]
    campo_largo = codice[..., 8]
    estrinseci = torch.cat([quaternione_a_matrice(quaternione), spostamento[..., None]], dim=-1)
    alto, largo = alto_largo
    tan_alto = torch.tan(campo_alto / 2.0)
    tan_largo = torch.tan(campo_largo / 2.0)
    if limite is not None:
        tan_alto = torch.clamp(tan_alto, limite)
        tan_largo = torch.clamp(tan_largo, limite)
    intrinseci = torch.zeros(codice.shape[:2] + (3, 3), device=codice.device)
    intrinseci[..., 0, 0] = (largo / 2.0) / tan_largo
    intrinseci[..., 1, 1] = (alto / 2.0) / tan_alto
    intrinseci[..., 0, 2] = largo / 2
    intrinseci[..., 1, 2] = alto / 2
    intrinseci[..., 2, 2] = 1.0
    return estrinseci, intrinseci
