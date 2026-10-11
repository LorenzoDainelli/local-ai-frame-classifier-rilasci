from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from officina.errori import ErroreOfficina
from officina.miglioria import codeformer_pesi

NOME = "codeformer"
FEDELTA = 0.7
LATO = 512
GRIGIO = (135, 133, 132)
SAGOMA = (0, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 0, 255, 0, 0, 0)
BORDO_DELLA_SAGOMA = 10
MODELLO = (
    (192.98138, 239.94708),
    (318.90277, 240.1936),
    (256.63416, 314.01935),
    (201.26117, 371.41043),
    (313.08905, 371.15118),
)
LATO_PER_CERCARE = 1280
SICUREZZA_MINIMA = 0.60


class MancaCodeFormer(ErroreOfficina):
    codice = "motore_mancante"


@dataclass
class Volto:

    punti: object
    riquadro: tuple[float, float, float, float]


class CodeFormer:

    nome = NOME
    versione = f"0.1.0-w{FEDELTA}"

    def __init__(self, cartella_modelli: str | None = None, **_opzioni) -> None:
        from officina.volti import rilevatore

        if not cartella_modelli or not codeformer_pesi.e_in_casa(Path(cartella_modelli)):
            raise MancaCodeFormer("Il modello che sistema i volti non è ancora stato "
                                  "scaricato.")
        if not rilevatore.ci_sono_i_modelli(Path(cartella_modelli)):
            raise MancaCodeFormer("Per sistemare i volti servono anche i modelli che "
                                  "li trovano, e non sono ancora stati scaricati.")
        self.casa = codeformer_pesi.dove(Path(cartella_modelli))
        self.file_rilevatore = rilevatore.dove_stanno(Path(cartella_modelli)) / \
            rilevatore.FILE_RILEVATORE
        self._reti = None
        self._trova = None

    def _accendi(self):
        if self._reti is not None:
            return self._reti
        import torch
        from safetensors.torch import load_file

        from officina.miglioria import codeformer_rete

        dispositivo = "cuda" if torch.cuda.is_available() else "cpu"
        volto = codeformer_rete.CodeFormer()
        volto.load_state_dict(load_file(str(self.casa / "codeformer.safetensors")), strict=True)
        sagoma = codeformer_rete.ParseNet()
        sagoma.load_state_dict(load_file(str(self.casa / "sagoma.safetensors")), strict=True)
        self._reti = {"volto": volto.eval().to(dispositivo),
                      "sagoma": sagoma.eval().to(dispositivo), "dispositivo": dispositivo}
        return self._reti

    def _cercatore(self):
        if self._trova is None:
            import onnxruntime

            self._trova = onnxruntime.InferenceSession(
                str(self.file_rilevatore), providers=["CPUExecutionProvider"])
        return self._trova

    def trova(self, quadro) -> list:
        import cv2
        import numpy as np

        from officina.volti import insight

        altezza, larghezza = quadro.shape[:2]
        scala = min(1.0, LATO_PER_CERCARE / max(altezza, larghezza))
        piccolo = quadro if scala == 1.0 else cv2.resize(
            quadro, (max(1, int(larghezza * scala)), max(1, int(altezza * scala))),
            interpolation=cv2.INTER_AREA)
        cercatore = self._cercatore()
        ingresso = insight._preparata_per_scrfd(
            np.ascontiguousarray(piccolo[:, :, ::-1]), np)
        uscite = cercatore.run(None, {cercatore.get_inputs()[0].name: ingresso})
        proposte = [p for p in insight.leggi_le_uscite(
                        uscite, piccolo.shape[1], piccolo.shape[0], np)
                    if p[2] >= SICUREZZA_MINIMA]
        volti = []
        for riquadro, punti, _sicurezza in insight._togli_i_doppioni(
                proposte, insight.SOVRAPPOSIZIONE_MASSIMA):
            x1, y1, x2, y2 = (float(v) / scala for v in riquadro)
            volti.append(Volto(
                punti=np.asarray(punti, dtype=np.float32) / scala,
                riquadro=(x1 / larghezza, y1 / altezza,
                          (x2 - x1) / larghezza, (y2 - y1) / altezza)))
        return volti

    def sistema(self, immagine: Image.Image, persone=None) -> Image.Image:
        return self.sistema_con(immagine, lambda _volto: self._rifai)

    def sistema_con(self, immagine: Image.Image, chi_rifa) -> Image.Image:
        import numpy as np

        quadro = np.ascontiguousarray(np.asarray(immagine.convert("RGB"))[:, :, ::-1])
        volti = self.trova(quadro)
        if not volti:
            return immagine
        tela = quadro.astype(np.float32)
        for volto in volti:
            tela = self._una(quadro, tela, volto.punti, chi_rifa(volto))
        finita = np.clip(tela, 0, 255).astype(np.uint8)[:, :, ::-1]
        return Image.fromarray(np.ascontiguousarray(finita))

    def ritaglia(self, quadro, punti):
        import cv2
        import numpy as np

        matrice = cv2.estimateAffinePartial2D(punti, np.asarray(MODELLO, np.float32),
                                              method=cv2.LMEDS)[0]
        if matrice is None:
            return None, None
        return matrice, cv2.warpAffine(quadro, matrice, (LATO, LATO),
                                       borderMode=cv2.BORDER_CONSTANT, borderValue=GRIGIO)

    def _una(self, quadro, tela, punti, rifai=None):
        import cv2
        import numpy as np

        matrice, ritaglio = self.ritaglia(quadro, punti)
        if matrice is None:
            return tela
        rifatto = (rifai or self._rifai)(ritaglio)
        inversa = cv2.invertAffineTransform(matrice)
        altezza, larghezza = quadro.shape[:2]
        rimesso = cv2.warpAffine(rifatto, inversa, (larghezza, altezza)).astype(np.float32)
        maschera = cv2.warpAffine(np.ones((LATO, LATO), np.float32), inversa,
                                  (larghezza, altezza))
        maschera = cv2.erode(maschera, np.ones((2, 2), np.uint8))
        rimesso = maschera[:, :, None] * rimesso
        bordo = int(float(maschera.sum()) ** 0.5) // 20
        centro = cv2.erode(maschera, np.ones((bordo * 2, bordo * 2), np.uint8)) \
            if bordo else maschera
        morbida = cv2.GaussianBlur(centro, (bordo * 2 + 1, bordo * 2 + 1), 0)[:, :, None]
        sagoma = cv2.warpAffine(self._sagoma(rifatto), inversa, (larghezza, altezza),
                                flags=3)[:, :, None]
        dentro = (sagoma < morbida).astype(np.float32)
        morbida = sagoma * dentro + morbida * (1 - dentro)
        return morbida * rimesso + (1 - morbida) * tela

    def _in_tensore(self, quadro_bgr):
        import torch

        reti = self._accendi()
        rgb = torch.from_numpy(quadro_bgr[:, :, ::-1].copy()).permute(2, 0, 1).float()
        return ((rgb / 255.0 - 0.5) / 0.5).unsqueeze(0).to(reti["dispositivo"])

    def _rifai(self, ritaglio):
        import torch

        reti = self._accendi()
        with torch.inference_mode():
            uscita = reti["volto"](self._in_tensore(ritaglio), w=FEDELTA, adain=True)
            uscita = (uscita.squeeze(0).float().cpu().clamp(-1, 1) + 1) / 2
        rgb = (uscita.permute(1, 2, 0).numpy() * 255.0).round().astype("uint8")
        return rgb[:, :, ::-1].copy()

    def _sagoma(self, rifatto):
        import cv2
        import numpy as np
        import torch

        reti = self._accendi()
        with torch.inference_mode():
            parti = reti["sagoma"](self._in_tensore(rifatto))[0]
        parti = parti.argmax(dim=0).cpu().numpy()
        maschera = np.asarray(SAGOMA, np.float64)[parti]
        maschera = cv2.GaussianBlur(maschera, (101, 101), 11)
        maschera = cv2.GaussianBlur(maschera, (101, 101), 11)
        b = BORDO_DELLA_SAGOMA
        maschera[:b, :] = 0
        maschera[-b:, :] = 0
        maschera[:, :b] = 0
        maschera[:, -b:] = 0
        return (maschera / 255.0).astype(np.float32)

    def spegni(self) -> None:
        reti, self._reti, self._trova = self._reti, None, None
        if reti is None:
            return
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass
