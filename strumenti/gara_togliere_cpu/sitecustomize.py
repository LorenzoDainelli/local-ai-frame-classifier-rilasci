import os

import torch

torch.cuda.is_available = lambda: False

if os.environ.get("GARA_OTTO_BIT") == "1":
    _sposta = torch.nn.Module.to

    def _al_primo_giro(modulo, _ingresso):
        from optimum.quanto import freeze, qint8, quantize

        modulo._gara_aggancio.remove()
        quantize(modulo, weights=qint8)
        freeze(modulo)

    def _sposta_e_segna(modulo, *dove, **altro):
        risultato = _sposta(modulo, *dove, **altro)
        if not getattr(modulo, "_gara_segnato", False):
            quanti = sum(p.numel() for p in modulo.parameters())
            if quanti > 2_000_000_000:
                modulo._gara_segnato = True
                modulo._gara_aggancio = modulo.register_forward_pre_hook(_al_primo_giro)
        return risultato

    torch.nn.Module.to = _sposta_e_segna
