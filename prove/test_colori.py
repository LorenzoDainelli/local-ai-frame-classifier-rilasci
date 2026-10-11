from __future__ import annotations

import re
from pathlib import Path

FOGLIO = (Path(__file__).resolve().parent.parent
          / "officina" / "web" / "statici" / "css" / "fondamenta.css")

BASTA = 4.5

FONDI = ("fondo", "superficie", "superficie-alta")

SCRITTE = ("ink", "attenuato", "tenue")


TEMI = {"scuro": ":root {", "chiaro": ':root[data-theme="light"] {'}


def tavolozza(tema: str = "scuro") -> dict[str, str]:
    testo = FOGLIO.read_text(encoding="utf-8")
    inizio = testo.index(TEMI[tema])
    blocco = testo[inizio:testo.index("\n}", inizio)]
    colori = {nome: colore for nome, colore in
              re.findall(r"--([a-z-]+):\s*(#[0-9A-Fa-f]{6})\s*;", blocco)}
    for nome, altro in re.findall(r"--([a-z-]+):\s*var\(--([a-z-]+)\)\s*;", testo):
        if nome not in colori and altro in colori:
            colori[nome] = colori[altro]
    return colori


def _chiarezza(colore: str) -> float:
    def canale(due_cifre: str) -> float:
        v = int(due_cifre, 16) / 255
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4

    c = colore.lstrip("#")
    return (0.2126 * canale(c[0:2]) + 0.7152 * canale(c[2:4])
            + 0.0722 * canale(c[4:6]))


def contrasto(uno: str, altro: str) -> float:
    a, b = _chiarezza(uno), _chiarezza(altro)
    return (max(a, b) + 0.05) / (min(a, b) + 0.05)


def test_ogni_scritta_si_legge_su_ogni_fondo():
    magre = []
    for tema in TEMI:
        magre += _magre(tavolozza(tema), tema)
    assert not magre, (
        "queste scritte non si leggono abbastanza. Al testo piccolo serve "
        f"{BASTA}, e questi stanno sotto:\n  " + "\n  ".join(magre))


def _magre(colori: dict[str, str], tema: str) -> list[str]:
    magre = []
    for scritta in SCRITTE:
        for fondo in FONDI:
            quanto = contrasto(colori[scritta], colori[fondo])
            if quanto < BASTA:
                magre.append(f"tema {tema}: --{scritta} ({colori[scritta]}) su --{fondo} "
                             f"({colori[fondo]}): {quanto:.2f}")
    return magre


def test_i_tre_grigi_restano_tre():
    for tema in TEMI:
        colori = tavolozza(tema)
        gradini = [(nome, _chiarezza(colori[nome])) for nome in SCRITTE]
        for (primo, uno), (secondo, due) in zip(gradini, gradini[1:]):
            assert max(uno, due) / min(uno, due) >= 1.25, (
                f"--{primo} e --{secondo} sono quasi lo stesso grigio "
                f"({colori[primo]} e {colori[secondo]}): i tre gradini del testo "
                "sono diventati due")


def test_la_prova_saprebbe_accorgersene():
    prima = "#65656A"
    assert contrasto(prima, "#191A1C") < BASTA
    assert round(contrasto(prima, "#0B0B0C"), 2) == 3.39
"""E il conto in sé: due colori che si conoscono, per non fidarsi della
   propria aritmetica. Bianco su nero fa ventuno, ed è il massimo che esista."""
def test_il_conto_e_quello_giusto():
    assert round(contrasto("#FFFFFF", "#000000"), 2) == 21.0
    assert round(contrasto("#777777", "#FFFFFF"), 2) == 4.48


CSS = FOGLIO.parent


def _colori_scritti_a_mano() -> list[tuple[str, int, str]]:
    trovati = []
    fine_tavolozza = FOGLIO.read_text(encoding="utf-8").index(
        ':root[data-accento="bianco"]')
    for foglio in sorted(CSS.glob("*.css")):
        testo = foglio.read_text(encoding="utf-8")
        for incontro in re.finditer(r"#[0-9a-fA-F]{6}\b|rgba?\([^)]*\)", testo):
            if foglio.name == "fondamenta.css" and incontro.start() < fine_tavolozza:
                continue
            riga = testo.count("\n", 0, incontro.start()) + 1
            trovati.append((foglio.name, riga, incontro.group(0)))
    return trovati


def _terzine(scritto: str) -> tuple[int, int, int] | None:
    numeri = re.findall(r"[\d.]+", scritto)
    if scritto.startswith("#"):
        return tuple(int(scritto[i:i + 2], 16) for i in (1, 3, 5))
    if len(numeri) >= 3 and all("." not in n for n in numeri[:3]):
        return tuple(int(n) for n in numeri[:3])
    return None


def test_nessun_colore_della_tavolozza_ricopiato_a_mano():
    per_colore = {v.upper(): n for tema in TEMI for n, v in tavolozza(tema).items()}
    colpevoli = []
    for foglio, riga, scritto in _colori_scritti_a_mano():
        terzina = _terzine(scritto)
        if terzina is None:
            continue
        come_esadecimale = "#%02X%02X%02X" % terzina
        if come_esadecimale in per_colore:
            colpevoli.append(
                f"{foglio}:{riga} «{scritto}» è {per_colore[come_esadecimale]} "
                "scritto a mano")
    assert not colpevoli, "\n".join(colpevoli)


def test_la_prova_dei_colori_a_mano_saprebbe_accorgersene():
    assert _terzine("rgba(38, 38, 36, 0.62)") == (38, 38, 36)
    assert _terzine("#262624") == (38, 38, 36)
    assert "#%02X%02X%02X" % _terzine("rgba(38,38,36,0.94)") in {
        v.upper() for v in tavolozza().values()}
    assert "#%02X%02X%02X" % _terzine("rgba(0, 0, 0, 0.55)") not in {
        v.upper() for v in tavolozza().values()}


VELATO = re.compile(
    r"color-mix\(\s*in srgb\s*,\s*var\(--su-fill\)\s*(\d+)%\s*,\s*transparent\s*\)")


def _velata_su(percentuale: int, su_fill: str, fill: str) -> str:
    def canale(a: str, b: str) -> int:
        quota = percentuale / 100
        return round(quota * int(a, 16) + (1 - quota) * int(b, 16))

    s, f = su_fill.lstrip("#"), fill.lstrip("#")
    return "#%02X%02X%02X" % tuple(
        canale(s[i:i + 2], f[i:i + 2]) for i in (0, 2, 4))


def test_le_pillole_piene_si_leggono_in_tutti_e_due_i_temi():
    for tema in ("scuro", "chiaro"):
        colori = tavolozza(tema)
        alone = _velata_su(26, colori["arancio"], colori["fondo"])
        quanto = contrasto(colori["ink"], alone)
        assert quanto >= BASTA, f"{tema}: pillola piena a {quanto:.2f}, ne servono {BASTA}"
