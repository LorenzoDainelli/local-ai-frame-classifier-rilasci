from __future__ import annotations

from pathlib import Path

from officina.errori import ErroreOfficina
from officina.volti import allineamento
from officina.volti.rilevatore import (Conteggio, Faccia, FILE_RICONOSCITORE,
                                       FILE_RILEVATORE, LATO_MINIMO, NOME, SICUREZZA_MINIMA,
                                       VERSIONE, c_e_onnxruntime,
                                       ci_sono_i_modelli, cosa_manca,
                                       dove_stanno, nitidezza_di,
                                       si_puo_usare)

GRADINI = (8, 16, 32)
PROPOSTE_PER_POSIZIONE = 2

SOVRAPPOSIZIONE_MASSIMA = 0.40

SOGLIA_DEL_MODELLO = 0.20

LATO_FACCIA = 112

LATO_DEL_QUADRATO = 640

__all__ = ["FILE_RICONOSCITORE", "FILE_RILEVATORE", "NOME", "VERSIONE",
           "ci_sono_i_modelli", "dove_stanno", "si_puo_usare"]


class MancaOnnxruntime(ErroreOfficina):
    codice = "manca_onnxruntime"


class MancanoIModelli(ErroreOfficina):
    codice = "mancano_modelli_volti"


class Rilevatore:

    def __init__(self, cartella_modelli: Path,
                 sicurezza_minima: float = SICUREZZA_MINIMA):
        self.casa = dove_stanno(cartella_modelli)
        self.sicurezza_minima = sicurezza_minima
        self.conteggio = Conteggio()
        self._trova = None
        self._riconosce = None

    @property
    def versione(self) -> str:
        return VERSIONE


    def accendi(self) -> None:
        if self._trova is not None:
            return
        manca = cosa_manca(self.casa.parent)
        if manca:
            raise (MancaOnnxruntime(manca) if not c_e_onnxruntime()
                   else MancanoIModelli(manca))
        import onnxruntime

        opzioni = ["CPUExecutionProvider"]
        self._trova = onnxruntime.InferenceSession(
            str(self.casa / FILE_RILEVATORE), providers=opzioni)
        self._riconosce = onnxruntime.InferenceSession(
            str(self.casa / FILE_RICONOSCITORE), providers=opzioni)

    def spegni(self) -> None:
        self._trova = None
        self._riconosce = None


    def guarda(self, immagine) -> list[Faccia]:
        from officina.descrittori import vettori

        numpy = vettori.numpy_o_spiega()
        self.accendi()
        self.conteggio.immagini += 1

        intera = _in_rgb(immagine)
        altezza, larghezza = intera.shape[:2]
        if larghezza < 16 or altezza < 16:
            return []

        piccola, scala = _rimpicciolita(intera)
        proposte = self._proposte(piccola)
        self.conteggio.proposte += len(proposte)
        tenute = _togli_i_doppioni(proposte, SOVRAPPOSIZIONE_MASSIMA)

        facce = []
        for riquadro, punti, sicurezza in tenute:
            if sicurezza < self.sicurezza_minima:
                self.conteggio.poco_sicure += 1
                continue
            riquadro = [valore / scala for valore in riquadro]
            punti = [(x / scala, y / scala) for x, y in punti]

            larga = (riquadro[2] - riquadro[0]) / larghezza
            alta = (riquadro[3] - riquadro[1]) / altezza
            if min(larga, alta) < LATO_MINIMO or larga <= 0 or alta <= 0:
                self.conteggio.troppo_piccole += 1
                continue

            dritta = self._raddrizza(immagine, intera, punti, numpy)
            if dritta is None:
                self.conteggio.non_raddrizzate += 1
                continue

            self.conteggio.tenute += 1
            facce.append(Faccia(
                riquadro=(max(0.0, riquadro[0] / larghezza),
                          max(0.0, riquadro[1] / altezza),
                          min(1.0, larga), min(1.0, alta)),
                sicurezza=float(sicurezza),
                nitidezza=nitidezza_di(dritta),
                impronta=self._impronta_di(dritta, numpy),
            ))
        return facce


    def _proposte(self, quadro) -> list:
        from officina.descrittori import vettori

        numpy = vettori.numpy_o_spiega()
        ingresso = _preparata_per_scrfd(quadro, numpy)
        uscite = self._trova.run(None, {self._trova.get_inputs()[0].name: ingresso})
        return leggi_le_uscite(uscite, quadro.shape[1], quadro.shape[0], numpy)

    def _raddrizza(self, originale, intera, punti, numpy):
        from PIL import Image

        try:
            sorgente = (originale if hasattr(originale, "convert")
                        else Image.fromarray(intera))
            return allineamento.raddrizza(sorgente, punti, lato=LATO_FACCIA)
        except Exception:
            return None

    def _impronta_di(self, dritta, numpy) -> list[float] | None:
        from officina.descrittori import vettori

        pixel = numpy.asarray(dritta.convert("RGB"), dtype=numpy.float32)
        pixel = (pixel / 255.0 - 0.5) / 0.5
        ingresso = numpy.ascontiguousarray(
            pixel.transpose(2, 0, 1)[None, ...], dtype=numpy.float32)
        nome = self._riconosce.get_inputs()[0].name
        grezza = self._riconosce.run(None, {nome: ingresso})[0]
        return vettori.normalizza(numpy.asarray(grezza).reshape(-1).tolist())


def leggi_le_uscite(uscite, larghezza: int, altezza: int, numpy) -> list:
    quanti = len(GRADINI)
    if len(uscite) < quanti * 3:
        return []

    fuori = []
    for indice, gradino in enumerate(GRADINI):
        sicurezze = numpy.asarray(uscite[indice]).reshape(-1)
        distanze = numpy.asarray(uscite[indice + quanti]).reshape(-1, 4)
        punti = numpy.asarray(uscite[indice + quanti * 2]).reshape(-1, 5, 2)

        alta = (altezza + gradino - 1) // gradino
        larga = (larghezza + gradino - 1) // gradino
        centri = _i_centri(larga, alta, gradino, numpy)
        if len(centri) != len(sicurezze):
            continue

        for riga in range(len(sicurezze)):
            sicurezza = float(sicurezze[riga])
            if sicurezza < SOGLIA_DEL_MODELLO:
                continue
            cx, cy = float(centri[riga][0]), float(centri[riga][1])
            sinistra, sopra, destra, sotto = (float(v) * gradino
                                              for v in distanze[riga])
            fuori.append((
                [cx - sinistra, cy - sopra, cx + destra, cy + sotto],
                [(cx + float(x) * gradino, cy + float(y) * gradino)
                 for x, y in punti[riga]],
                sicurezza,
            ))
    fuori.sort(key=lambda voce: voce[2], reverse=True)
    return fuori


def _i_centri(larga: int, alta: int, gradino: int, numpy):
    y, x = numpy.mgrid[:alta, :larga]
    centri = numpy.stack([x, y], axis=-1).astype(numpy.float32) * gradino
    centri = centri.reshape(-1, 2)
    if PROPOSTE_PER_POSIZIONE > 1:
        centri = numpy.repeat(centri, PROPOSTE_PER_POSIZIONE, axis=0)
    return centri


def _togli_i_doppioni(proposte, quanto: float) -> list:
    tenute: list = []
    for voce in proposte:
        if all(_quanto_si_sovrappongono(voce[0], gia[0]) <= quanto
               for gia in tenute):
            tenute.append(voce)
    return tenute


def _quanto_si_sovrappongono(uno, altro) -> float:
    sinistra = max(uno[0], altro[0])
    sopra = max(uno[1], altro[1])
    destra = min(uno[2], altro[2])
    sotto = min(uno[3], altro[3])
    dentro = max(0.0, destra - sinistra) * max(0.0, sotto - sopra)
    if dentro <= 0:
        return 0.0
    area_uno = max(0.0, uno[2] - uno[0]) * max(0.0, uno[3] - uno[1])
    area_altro = max(0.0, altro[2] - altro[0]) * max(0.0, altro[3] - altro[1])
    insieme = area_uno + area_altro - dentro
    return dentro / insieme if insieme > 0 else 0.0


def _in_rgb(immagine):
    from officina.descrittori import vettori

    numpy = vettori.numpy_o_spiega()
    if not hasattr(immagine, "convert"):
        return numpy.ascontiguousarray(immagine)
    return numpy.ascontiguousarray(
        numpy.asarray(immagine.convert("RGB"), dtype=numpy.uint8))


def _rimpicciolita(quadro) -> tuple[object, float]:
    from PIL import Image
    from officina.descrittori import vettori

    numpy = vettori.numpy_o_spiega()
    altezza, larghezza = quadro.shape[:2]
    scala = LATO_DEL_QUADRATO / max(altezza, larghezza)
    nuova = (max(1, round(larghezza * scala)), max(1, round(altezza * scala)))
    piccola = _in_rgb(Image.fromarray(quadro).resize(nuova, Image.BILINEAR))
    quadrato = numpy.zeros((LATO_DEL_QUADRATO, LATO_DEL_QUADRATO, 3), dtype=numpy.uint8)
    quadrato[:nuova[1], :nuova[0]] = piccola
    return quadrato, scala


def _preparata_per_scrfd(quadro, numpy):
    pixel = (numpy.asarray(quadro, dtype=numpy.float32) - 127.5) / 128.0
    return numpy.ascontiguousarray(pixel.transpose(2, 0, 1)[None, ...],
                                   dtype=numpy.float32)
