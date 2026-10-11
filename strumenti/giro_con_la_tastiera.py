from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

INDIRIZZO = "http://127.0.0.1:8731"

FERMATE_AL_MASSIMO = 200

from strumenti.letture_larghe import SCHERMATE as PAGINE  # noqa: E402

CHI_HA_IL_FUOCO = """() => {
    const e = document.activeElement;
    if (!e || e === document.body) return null;
    const s = getComputedStyle(e);
    const r = e.getBoundingClientRect();
    // Anche sopra: un campo dentro un riquadro non ha bordi suoi, e l'anello
    // sta al riquadro, che si accende con `:focus-within`.
    let anelloSopra = 0;
    let sopra = e.parentElement;
    for (let i = 0; i < 3 && sopra; i++, sopra = sopra.parentElement) {
        anelloSopra = Math.max(
            anelloSopra, parseFloat(getComputedStyle(sopra).outlineWidth) || 0);
    }
    // Il giro è chiuso quando si torna sul **primo** di tutti. Riconoscerlo
    // dal nome non basta: trentasei fotografie hanno nomi che si somigliano,
    // e il giro finirebbe alla seconda. Quindi il primo lo si segna, e lo si
    // riconosce perché è proprio quell'elemento lì.
    const primo = window.__primoDelGiro;
    // Un `input type="date"` si tiene il fuoco addosso mentre il tasto di
    // tabulazione cammina dentro di lui — giorno, mese, anno, e il tastino
    // del calendario. Da fuori sembrano quattro fermate sullo stesso campo,
    // e sull'ultima l'anello è nostro nemmeno per finta: quel tastino sta
    // nell'ombra del browser, e il segno del fuoco se lo disegna lui.
    // Quindi una fermata sullo stesso elemento di prima non è una fermata
    // nuova, e non si conta e non si giudica.
    const stessa = window.__quelloDiPrima === e;
    window.__quelloDiPrima = e;
    return {
        stessa: stessa,
        tornato: primo === e,
        chi: e.tagName.toLowerCase() +
             (typeof e.className === 'string' && e.className.trim()
              ? '.' + e.className.trim().split(/\\s+/)[0] : ''),
        nome: (e.innerText || e.value || e.getAttribute('aria-label') || '')
              .trim().slice(0, 34),
        anello: (parseFloat(s.outlineWidth) || 0) + anelloSopra,
        ombra: s.boxShadow !== 'none',
        largo: Math.round(r.width), alto: Math.round(r.height),
        visibile: r.width > 0 && r.height > 0 && s.visibility !== 'hidden',
    };
}"""


def gira(indirizzo: str = INDIRIZZO) -> int:
    try:
        from playwright.sync_api import sync_playwright

        from strumenti import navigatore
    except ImportError:
        print("Serve playwright, e non è installato:\n"
              "    pip install playwright\n"
              "    playwright install chromium")
        return -1

    cieche = 0
    with sync_playwright() as teatro:
        browser = navigatore.apri(teatro)
        pagina = browser.new_page(viewport={"width": 1280, "height": 900})
        for dove in PAGINE:
            try:
                pagina.goto(indirizzo + dove, wait_until="networkidle",
                            timeout=20000)
            except Exception as guaio:
                print(f"  !!{dove:<20} non si apre ({type(guaio).__name__})")
                continue
            pagina.wait_for_timeout(300)
            pagina.evaluate("() => { document.body.focus();"
                            " window.__primoDelGiro = null;"
                            " window.__quelloDiPrima = null; }")

            quante = 0
            guasti: list[str] = []
            for numero in range(FERMATE_AL_MASSIMO):
                pagina.keyboard.press("Tab")
                fermata = pagina.evaluate(CHI_HA_IL_FUOCO)
                if fermata is None or fermata["tornato"]:
                    break
                if fermata["stessa"]:
                    continue
                if numero == 0:
                    pagina.evaluate(
                        "() => { window.__primoDelGiro = document.activeElement; }")
                quante += 1
                if not fermata["visibile"]:
                    guasti.append(f"il fuoco va su una cosa invisibile: "
                                  f"{fermata['chi']} «{fermata['nome']}»")
                elif fermata["anello"] < 1 and not fermata["ombra"]:
                    guasti.append(f"nessun anello: {fermata['chi']} "
                                  f"«{fermata['nome']}» "
                                  f"{fermata['largo']}x{fermata['alto']}")

            cieche += len(guasti)
            oltre = " (e non è finita)" if quante == FERMATE_AL_MASSIMO else ""
            print(f"{'  !!' if guasti else '    '}{dove:<20} "
                  f"{quante:>3} fermate{oltre}")
            for guasto in guasti:
                print(f"         {guasto}")
        browser.close()
    return cieche


if __name__ == "__main__":
    dove = sys.argv[1] if len(sys.argv) > 1 else INDIRIZZO
    quante = gira(dove)
    if quante > 0:
        print(f"\n{quante} fermate non si vedono.")
    elif quante == 0:
        print("\nOgni fermata del fuoco si vede.")
    raise SystemExit(1 if quante != 0 else 0)
