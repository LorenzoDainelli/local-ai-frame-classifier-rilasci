from __future__ import annotations

from pathlib import Path

from officina.corpi import solo_numeri

LN2 = 0.69314718246459961
PARTI_DEL_GIUNTO = 7

CLASSI_CONOSCIUTE = {
    "__torch__": {"MHRDemo"},
    "__torch__.pymomentum.torch.character": {
        "BlendShapeBase", "BlendShape", "Character", "Skeleton", "Mesh",
        "ParameterTransform", "LinearBlendSkinning"},
    "__torch__.pymomentum.torch.parameter_limits": {"ParameterLimits"},
    "__torch__.pymomentum.mhr.mhr": {"MHRPoseCorrectivesModel"},
    "__torch__.pymomentum.mhr.utils": {"SparseLinear"},
    "__torch__.torch.nn.modules.container": {"Sequential"},
    "__torch__.torch.nn.modules.activation": {"ReLU"},
    "__torch__.torch.nn.modules.linear": {"Linear"},
}
FileNonValido = solo_numeri.FileNonValido


def leggi(percorso: Path):
    radice = solo_numeri.leggi(percorso, CLASSI_CONOSCIUTE)
    if type(radice).__name__ != "MHRDemo":
        raise FileNonValido("non è il modello MHR")
    return radice


def _figlio(oggetto, *strada: str):
    for passo in strada:
        oggetto = oggetto.stato[passo]
    return oggetto


def numeri(percorso: Path) -> dict:
    import torch

    radice = leggi(percorso)
    personaggio = _figlio(radice, "character_torch")
    scheletro = _figlio(personaggio, "skeleton")
    pelle = _figlio(personaggio, "linear_blend_skinning")
    forma = _figlio(personaggio, "blend_shape")
    correttivi = _figlio(radice, "pose_correctives_model", "pose_dirs_predictor")
    rado = correttivi.stato["0"]
    denso = correttivi.stato["2"]
    uscite, entrate = rado.stato["sparse_shape"]
    indici = rado.stato["sparse_indices"]
    pesi_radi = torch.zeros(int(uscite), int(entrate), dtype=rado.stato["sparse_weight"].dtype)
    pesi_radi.index_put_((indici[0], indici[1]), rado.stato["sparse_weight"], accumulate=True)
    return {
        "forme": forma.stato["shape_vectors"],
        "base": forma.stato["base_shape"],
        "espressioni": _figlio(radice, "face_expressions_model").stato["shape_vectors"],
        "trasformazione": _figlio(personaggio, "parameter_transform").stato["parameter_transform"],
        "spostamenti": scheletro.stato["joint_translation_offsets"],
        "prerotazioni": scheletro.stato["joint_prerotations"],
        "catena": scheletro.stato["pmi"],
        "anelli": [int(n) for n in scheletro.stato["_pmi_buffer_sizes"]],
        "padri": scheletro.stato["joint_parents"],
        "posa_inversa": pelle.stato["inverse_bind_pose"],
        "pelle_giunti": pelle.stato["skin_indices_flattened"],
        "pelle_pesi": pelle.stato["skin_weights_flattened"],
        "pelle_vertici": pelle.stato["vert_indices_flattened"],
        "vertici": int(pelle.stato["num_vertices"]),
        "facce": _figlio(personaggio, "mesh").stato["faces"],
        "correttivi_primo": pesi_radi,
        "correttivi_secondo": denso.stato["weight"],
        "nomi_dei_giunti": list(radice.stato.get("joint_names_list", [])),
        "nomi_dei_parametri": list(radice.stato.get("parameter_names_list", [])),
        "limiti": radice.stato.get("parameter_limits"),
    }


def _quaternione_da_euler(euler):
    import torch

    rollio, beccheggio, imbardata = torch.unbind(euler, -1)
    cy, sy = torch.cos(imbardata * 0.5), torch.sin(imbardata * 0.5)
    cp, sp = torch.cos(beccheggio * 0.5), torch.sin(beccheggio * 0.5)
    cr, sr = torch.cos(rollio * 0.5), torch.sin(rollio * 0.5)
    return torch.stack([sr * cp * cy - cr * sp * sy,
                        cr * sp * cy + sr * cp * sy,
                        cr * cp * sy - sr * sp * cy,
                        cr * cp * cy + sr * sp * sy], -1)


def _per_quaternione(q1, q2):
    import torch

    x1, y1, z1, w1 = torch.unbind(q1, -1)
    x2, y2, z2, w2 = torch.unbind(q2, -1)
    return torch.stack([w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
                        w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2,
                        w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2,
                        w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2], -1)


def _normalizza(q):
    import torch

    return q / torch.clamp_min(torch.norm(q, 2.0, [-1], True), 1e-12).expand_as(q)


def _ruota(q, v):
    import torch

    reale, asse = q[..., 3:4], q[..., 0:3]
    av = torch.cross(asse, v, dim=-1)
    aav = torch.cross(asse, av, dim=-1)
    return v + (av * reale + aav) * 2


def _componi(stato1, stato2):
    import torch

    t1, q1, s1 = stato1[..., :3], _normalizza(stato1[..., 3:7]), stato1[..., 7:]
    t2, q2, s2 = stato2[..., :3], _normalizza(stato2[..., 3:7]), stato2[..., 7:]
    return torch.cat([t1 + s1 * _ruota(q1, t2), _per_quaternione(q1, q2), s1 * s2], -1)


def _sposta(stato, punti):
    t, q, s = stato[..., :3], _normalizza(stato[..., 3:7]), stato[..., 7:]
    return t + _ruota(q, s * punti)


def _sei_da_euler(r):
    import torch

    c, s = torch.cos(r), torch.sin(r)
    cx, cy, cz = c[..., 0], c[..., 1], c[..., 2]
    sx, sy, sz = s[..., 0], s[..., 1], s[..., 2]
    return torch.stack([cy * cz, cy * sz, -sy,
                        -cx * sz + sx * sy * cz, cx * cz + sx * sy * sz, sx * cy], -1)


class Mhr:

    def __init__(self, numeri_mhr: dict, dispositivo="cpu"):
        import torch

        self.dispositivo = torch.device(dispositivo)
        self.n = {k: (v.to(self.dispositivo) if isinstance(v, torch.Tensor) else v)
                  for k, v in numeri_mhr.items()}
        catena = self.n["catena"]
        self.anelli = list(torch.split(catena, self.n["anelli"], 1))

    @classmethod
    def da_file(cls, percorso: Path, dispositivo="cpu") -> Mhr:
        return cls(numeri(percorso), dispositivo)

    @property
    def facce(self):
        return self.n["facce"]

    @property
    def quante_forme(self) -> int:
        return int(self.n["forme"].shape[0])

    @property
    def quante_espressioni(self) -> int:
        return int(self.n["espressioni"].shape[0])

    def giunti_locali(self, parametri_dei_giunti):
        import torch

        giunti = parametri_dei_giunti.view(*parametri_dei_giunti.shape[:-1], -1, PARTI_DEL_GIUNTO)
        t = giunti[..., :3] + self.n["spostamenti"].unsqueeze(0)
        q = _per_quaternione(self.n["prerotazioni"].unsqueeze(0), _quaternione_da_euler(giunti[..., 3:6]))
        s = torch.exp(giunti[..., 6:] * LN2)
        return torch.cat([t, q, s], -1)

    def giunti_nel_mondo(self, locali):
        stato = locali.clone().double()
        for anello in self.anelli:
            sorgente, bersaglio = anello[0], anello[1]
            primo = stato.index_select(-2, bersaglio)
            secondo = stato.index_select(-2, sorgente)
            stato.index_copy_(-2, sorgente, _componi(primo, secondo))
        return stato.to(locali.dtype)

    def correttivi(self, parametri_dei_giunti):
        import torch

        giunti = parametri_dei_giunti.reshape(parametri_dei_giunti.shape[0], -1, PARTI_DEL_GIUNTO)
        sei = _sei_da_euler(giunti[:, 2:, 3:6])
        sei[:, :, 0] -= 1
        sei[:, :, 4] -= 1
        sei = sei.flatten(1, 2)
        mezzo = torch.relu((self.n["correttivi_primo"] @ sei.T).T)
        uscita = torch.nn.functional.linear(mezzo, self.n["correttivi_secondo"])
        return uscita.reshape(sei.shape[0], -1, 3)

    def pelle(self, nel_mondo, riposo):
        import torch

        posa_inversa = self.n["posa_inversa"]
        while posa_inversa.dim() < nel_mondo.dim():
            posa_inversa = posa_inversa.unsqueeze(0)
        while riposo.dim() < nel_mondo.dim():
            riposo = riposo.unsqueeze(0)
        riposo = riposo.expand(*nel_mondo.shape[:-2], *riposo.shape[-2:])
        giunti = _componi(nel_mondo, posa_inversa)
        mossi = _sposta(giunti.index_select(-2, self.n["pelle_giunti"]),
                        riposo.index_select(-2, self.n["pelle_vertici"]))
        pesi = self.n["pelle_pesi"].unsqueeze(0)[:, :].unsqueeze(2)
        return torch.zeros_like(riposo).index_add(-2, self.n["pelle_vertici"], mossi * pesi)

    def __call__(self, identita, parametri, espressioni, con_i_correttivi: bool = True):
        import torch

        riposo = torch.einsum("nvd,...n->...vd", self.n["forme"], identita) + self.n["base"]
        parametri_dei_giunti = torch.einsum(
            "dn,...n->...d", self.n["trasformazione"],
            torch.cat([parametri, torch.zeros_like(identita)], 1))
        nel_mondo = self.giunti_nel_mondo(self.giunti_locali(parametri_dei_giunti))
        senza_posa = riposo + torch.einsum("nvd,...n->...vd", self.n["espressioni"], espressioni)
        if con_i_correttivi:
            senza_posa = senza_posa + self.correttivi(parametri_dei_giunti)
        return self.pelle(nel_mondo, senza_posa), nel_mondo
