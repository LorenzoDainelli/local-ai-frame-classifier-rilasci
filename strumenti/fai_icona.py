from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

ARANCIO = (217, 119, 87, 255)
CARTA = (250, 249, 245, 255)
INCHIOSTRO = (20, 20, 19, 255)
MONTE = (190, 185, 172, 255)

DOVE = (Path(__file__).resolve().parent.parent
        / "officina" / "web" / "statici" / "officina.ico")

LATO = 1024
MISURE = (16, 24, 32, 48, 64, 128, 256)


def disegna(lato: int = LATO) -> Image.Image:
    u = lato / 200
    giu = 80 * u
    maschera = Image.new("L", (lato, lato), 0)
    ImageDraw.Draw(maschera).rounded_rectangle([0, 0, lato - 1, lato - 1], radius=int(44 * u), fill=255)

    tela = Image.new("RGBA", (lato, lato), ARANCIO)
    penna = ImageDraw.Draw(tela)
    fuori = [34 * u - 2.5 * u, 34 * u + giu - 2.5 * u, 166 * u + 2.5 * u, 166 * u + giu + 2.5 * u]
    dentro = [34 * u + 2.5 * u, 34 * u + giu + 2.5 * u, 166 * u - 2.5 * u, 166 * u + giu - 2.5 * u]
    penna.rounded_rectangle(fuori, radius=int(22.5 * u), fill=INCHIOSTRO)
    penna.rounded_rectangle(dentro, radius=int(17.5 * u), fill=CARTA)

    quadro = Image.new("RGBA", (lato, lato), (0, 0, 0, 0))
    disegno = ImageDraw.Draw(quadro)
    disegno.polygon([(36 * u, 166 * u + giu), (86 * u, 114 * u + giu), (124 * u, 152 * u + giu),
                     (146 * u, 132 * u + giu), (164 * u, 166 * u + giu)], fill=MONTE)
    disegno.ellipse([129 * u, 51 * u + giu, 151 * u, 73 * u + giu], fill=ARANCIO)
    for centro in (78 * u, 112 * u):
        disegno.ellipse([centro - 8.8 * u, 79 * u + giu, centro + 8.8 * u, 101 * u + giu], fill=INCHIOSTRO)
    interno = Image.new("L", (lato, lato), 0)
    ImageDraw.Draw(interno).rounded_rectangle(dentro, radius=int(17.5 * u), fill=255)
    tela.paste(quadro, (0, 0), Image.composite(quadro.getchannel("A"), Image.new("L", (lato, lato), 0), interno))

    fuori_tutto = Image.new("RGBA", (lato, lato), (0, 0, 0, 0))
    fuori_tutto.paste(tela, (0, 0), maschera)
    return fuori_tutto


def scrivi(dove: Path = DOVE) -> Path:
    dove.parent.mkdir(parents=True, exist_ok=True)
    disegna().resize((256, 256), Image.LANCZOS).save(
        dove, format="ICO", sizes=[(m, m) for m in MISURE])
    return dove


if __name__ == "__main__":
    fatto = scrivi()
    print(f"  {fatto} — {fatto.stat().st_size / 1024:.0f} KB")
