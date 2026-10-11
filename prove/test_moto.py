from __future__ import annotations

import re
from pathlib import Path

import pytest

from prove.fogli import schermate

CSS = (Path(__file__).resolve().parent.parent
       / "officina" / "web" / "statici" / "css")

DICHIARAZIONE = re.compile(r"transition:\s*([^;}]+);", re.S)

HA_UN_TEMPO = re.compile(r"\d+(\.\d+)?m?s\b|var\(--gesto\)|var\(--scena\)")


def pezzi(dichiarazione: str) -> list[str]:
    fuori, profondita, corrente = [], 0, ""
    for carattere in dichiarazione:
        if carattere == "(":
            profondita += 1
        elif carattere == ")":
            profondita -= 1
        if carattere == "," and profondita == 0:
            fuori.append(corrente)
            corrente = ""
        else:
            corrente += carattere
    fuori.append(corrente)
    return [pezzo.strip() for pezzo in fuori if pezzo.strip()]


def tutte() -> list[tuple[str, int, str]]:
    trovate = []
    for foglio in sorted(CSS.glob("*.css")):
        testo = foglio.read_text(encoding="utf-8")
        for incontro in DICHIARAZIONE.finditer(testo):
            riga = testo.count("\n", 0, incontro.start()) + 1
            for pezzo in pezzi(incontro.group(1)):
                trovate.append((foglio.name, riga, pezzo))
    return trovate


def test_ce_n_e_abbastanza_da_guardare():
    assert len(tutte()) >= 40


@pytest.mark.parametrize("foglio,riga,pezzo", tutte(),
                         ids=lambda v: str(v).replace(" ", ""))
def test_ogni_transizione_ha_il_suo_tempo(foglio, riga, pezzo):
    assert HA_UN_TEMPO.search(pezzo), (
        f"{foglio}:{riga} — «{pezzo}» è una transizione senza tempo, cioè "
        "dura zero e non si vede. Di solito è una lista scritta con le "
        "virgole e il tempo solo in fondo: il tempo va dietro a ognuna")


def test_la_prova_saprebbe_accorgersene():
    prima = "color, border-color, opacity var(--gesto) var(--uscita)"
    assert [bool(HA_UN_TEMPO.search(p)) for p in pezzi(prima)] == [
        False, False, True]

    adesso = ("color var(--gesto) var(--uscita), "
              "border-color var(--gesto) var(--uscita), "
              "opacity var(--gesto) var(--uscita)")
    assert all(HA_UN_TEMPO.search(p) for p in pezzi(adesso))


def test_le_virgole_dentro_le_parentesi_non_separano():
    curva = "transform 380ms cubic-bezier(0.34, 1.26, 0.64, 1), opacity 150ms"
    assert pezzi(curva) == [
        "transform 380ms cubic-bezier(0.34, 1.26, 0.64, 1)", "opacity 150ms"]


def _fogli() -> dict[str, str]:
    return {f.name: f.read_text(encoding="utf-8") for f in sorted(CSS.glob("*.css"))}


NOME_ANIMAZIONE = re.compile(r"animation(?:-name)?:\s*([^;}]+);")
KEYFRAMES = re.compile(r"@keyframes\s+([\w-]+)")


def test_ogni_animazione_ha_i_suoi_keyframes():
    testo = "".join(_fogli().values())
    definiti = set(KEYFRAMES.findall(testo))
    for incontro in NOME_ANIMAZIONE.finditer(testo):
        for pezzo in pezzi(incontro.group(1)):
            nome = pezzo.split()[0]
            if nome in ("none", "inherit", "initial", "unset"):
                continue
            assert nome in definiti, (
                f"«{nome}» è chiamata ma non c'è nessun @keyframes così: "
                "quell'animazione non parte e nessuno lo dice")


def test_nessun_keyframes_dimenticato():
    testo = "".join(_fogli().values())
    usati = {pezzo.split()[0]
             for incontro in NOME_ANIMAZIONE.finditer(testo)
             for pezzo in pezzi(incontro.group(1))}
    dimenticati = sorted(set(KEYFRAMES.findall(testo)) - usati)
    assert not dimenticati, f"@keyframes che non usa più nessuno: {dimenticati}"


NON_SI_ANIMANO = {
    "display", "visibility", "position", "overflow", "overflow-x", "overflow-y",
    "z-index", "float", "background-image", "font-family", "white-space",
    "cursor", "flex-wrap", "flex-direction", "text-align", "border-style",
    "grid-template-columns", "grid-template-rows", "content", "pointer-events",
}


def test_nessuno_prova_ad_animare_una_cosa_che_non_si_anima():
    for nome, testo in _fogli().items():
        for incontro in DICHIARAZIONE.finditer(testo):
            riga = testo.count("\n", 0, incontro.start()) + 1
            for pezzo in pezzi(incontro.group(1)):
                quale = pezzo.split()[0]
                assert quale not in NON_SI_ANIMANO, (
                    f"{nome}:{riga} — «{quale}» cambia di scatto comunque: "
                    "la riga promette un passaggio morbido che non c'è")


FONDAMENTA = CSS / "fondamenta.css"


def _tempi_azzerati(blocco: str) -> set[str]:
    return set(re.findall(r"(--gesto|--scena):\s*0\.01ms\s*!important", blocco))


def test_le_due_strade_azzerano_gli_stessi_tempi():
    testo = FONDAMENTA.read_text(encoding="utf-8")
    dal_sistema = testo.index("@media (prefers-reduced-motion: reduce)")
    dall_interruttore = testo.index("body.senza-movimento {")

    sistema = testo[dal_sistema:dall_interruttore]
    interruttore = testo[dall_interruttore:dall_interruttore + 400]

    assert _tempi_azzerati(sistema) == {"--gesto", "--scena"}
    assert _tempi_azzerati(interruttore) == {"--gesto", "--scena"}, (
        "l'interruttore del programma non azzera più gli stessi tempi "
        "dell'impostazione di sistema: la stessa richiesta ottiene due "
        "risposte diverse a seconda di dove la si fa")


def test_le_due_strade_fermano_anche_i_figli_finti():
    testo = FONDAMENTA.read_text(encoding="utf-8")
    for strada in ("*, *::before, *::after { animation: none !important; }",
                   "body.senza-movimento *::before,\n"
                   "body.senza-movimento *::after { animation: none !important; }"):
        assert strada in testo, f"manca: {strada}"


def _curva(scritta: str) -> tuple[float, float, float, float]:
    numeri = [float(n) for n in re.findall(r"-?[\d.]+", scritta)]
    return tuple(numeri[:4])


def _a_meta(curva, u: float) -> float:
    p1, p2, p3, p4 = curva

    def x(t): return 3 * (1 - t) ** 2 * t * p1 + 3 * (1 - t) * t * t * p3 + t ** 3

    def y(t): return 3 * (1 - t) ** 2 * t * p2 + 3 * (1 - t) * t * t * p4 + t ** 3

    basso, alto = 0.0, 1.0
    for _ in range(60):
        mezzo = (basso + alto) / 2
        if x(mezzo) < u:
            basso = mezzo
        else:
            alto = mezzo
    return y((basso + alto) / 2)


def _scatto(curva) -> float:
    d = 1e-3
    prima = (_a_meta(curva, 1.0) - _a_meta(curva, 1.0 - d)) / d
    dopo = (_a_meta(curva, d) - _a_meta(curva, 0.0)) / d
    return abs(dopo - prima)


def test_le_due_pulsazioni_usano_la_stessa_curva():
    testo = schermate()
    senza_fine = re.findall(r"animation:\s*[\w-]+\s+[\d.]+m?s\s+([^;]+?)\s+infinite",
                            testo)
    assert senza_fine, "nessuna animazione senza fine: la prova non guarda più niente"
    assert set(senza_fine) == {"var(--andirivieni)"}, (
        "un'animazione che gira per sempre usa una curva che non è quella "
        f"dell'andirivieni: {sorted(set(senza_fine))}")


def test_la_curva_dell_andirivieni_non_fa_l_angolo():
    testo = FONDAMENTA.read_text(encoding="utf-8")
    andirivieni = _curva(re.search(r"--andirivieni:\s*cubic-bezier\(([^)]+)\)",
                                   testo).group(1))
    uscita = _curva(re.search(r"--uscita:\s*cubic-bezier\(([^)]+)\)",
                              testo).group(1))

    assert round(_scatto(uscita), 2) == 4.0
    assert _scatto(andirivieni) < 1e-9, (
        "l'andirivieni non arriva più fermo alle due estremità: nel punto in "
        "cui il respiro gira si vedrà un angolo")
