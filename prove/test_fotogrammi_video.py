from fractions import Fraction

from PIL import Image, ImageFilter

from officina.immagini import fotogrammi


def test_A_sul_video_lungo_non_si_saltano_quindici_secondi():
    un_ora = 3600 * 30
    passo = fotogrammi.passo_dei_candidati(un_ora, 30.0)

    assert passo < 450
    secondi_di_buco = passo / 30.0
    assert secondi_di_buco <= 5.0, f"un candidato ogni {secondi_di_buco:.0f} secondi"


def test_A_il_video_corto_resta_fitto():
    due_minuti = 120 * 30
    passo = fotogrammi.passo_dei_candidati(due_minuti, 30.0)
    assert passo / 30.0 <= fotogrammi.SECONDI_FRA_CANDIDATI


def test_A_il_tetto_regge_ancora_sul_video_lunghissimo():
    quattro_ore = 4 * 3600 * 30
    passo = fotogrammi.passo_dei_candidati(quattro_ore, 30.0)
    assert quattro_ore // passo <= fotogrammi.CANDIDATI_MASSIMI


class FintaTraccia:
    def __init__(self, frames, durata, base, ritmo):
        self.frames = frames
        self.duration = durata
        self.time_base = base
        self.average_rate = ritmo
        self.guessed_rate = ritmo


class FintoContenitore:
    def __init__(self, durata=None):
        self.duration = durata


def test_B_un_ora_senza_conteggio_si_guarda_tutta():
    traccia = FintaTraccia(frames=0, durata=3600 * 90000,
                           base=Fraction(1, 90000), ritmo=Fraction(30))
    quanti, al_secondo = fotogrammi._quanti_e_ritmo(FintoContenitore(), traccia)

    assert al_secondo == 30
    assert quanti > 100_000, "l'ora di video non è stata stimata"

    passo = fotogrammi.passo_dei_candidati(quanti, al_secondo)
    guardati = min(quanti // passo, fotogrammi.CANDIDATI_MASSIMI)
    arrivo_secondi = min(quanti, passo * guardati) / 30.0
    assert arrivo_secondi > 3000, (
        f"si guarda solo fino al secondo {arrivo_secondi:.0f} di 3600")


def test_B_la_durata_si_legge_anche_dal_contenitore():
    traccia = FintaTraccia(frames=0, durata=None, base=None, ritmo=Fraction(25))
    quanti, _ = fotogrammi._quanti_e_ritmo(
        FintoContenitore(durata=600 * 1_000_000), traccia)
    assert quanti == 600 * 25


def test_B_senza_niente_si_guarda_uno_per_uno_invece_di_indovinare():
    traccia = FintaTraccia(frames=0, durata=None, base=None, ritmo=0)
    quanti, al_secondo = fotogrammi._quanti_e_ritmo(FintoContenitore(), traccia)
    assert (quanti, al_secondo) == (0, 0.0)
    assert fotogrammi.passo_dei_candidati(0, 0.0) == 1


def _scacchiera(lato: int = 2) -> Image.Image:
    immagine = Image.new("L", (256, 256))
    pixel = immagine.load()
    for y in range(256):
        for x in range(256):
            pixel[x, y] = 255 if ((x // lato) + (y // lato)) % 2 else 0
    return immagine.convert("RGB")


def _fotogramma(numero: int, immagine: Image.Image) -> fotogrammi.Fotogramma:
    return fotogrammi.Fotogramma(numero, numero * 100, immagine)


def test_C_fra_due_ugualmente_nuovi_si_tiene_quello_a_fuoco():
    nitida = _scacchiera()
    mossa = nitida.filter(ImageFilter.GaussianBlur(6))

    assert fotogrammi._nitidezza(nitida) > fotogrammi._nitidezza(mossa) * 3

    nero = Image.new("RGB", (256, 256), (0, 0, 0))
    candidati = [_fotogramma(0, nero), _fotogramma(1, mossa), _fotogramma(2, nitida)]

    scelti = fotogrammi.scegli(candidati, quanti=2)
    assert [f.numero for f in scelti] == [0, 2], "ha tenuto il fotogramma mosso"


def test_C_la_differenza_resta_il_criterio():
    nero = Image.new("RGB", (64, 64), (0, 0, 0))
    quasi_nero = Image.new("RGB", (64, 64), (2, 2, 2))
    bianco = Image.new("RGB", (64, 64), (255, 255, 255))

    scelti = fotogrammi.scegli(
        [_fotogramma(0, nero), _fotogramma(1, quasi_nero), _fotogramma(2, bianco)],
        quanti=2)
    assert [f.numero for f in scelti] == [0, 2]


def test_C_il_video_statico_smette_ancora_presto():
    uguali = [_fotogramma(n, Image.new("RGB", (64, 64), (30, 30, 30)))
              for n in range(50)]
    assert len(fotogrammi.scegli(uguali, quanti=40)) == 1
