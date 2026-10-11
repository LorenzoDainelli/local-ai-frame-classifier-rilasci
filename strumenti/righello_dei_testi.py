from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

INDIRIZZO = "http://127.0.0.1:8731"
LARGHEZZE = (1280, 900)

from strumenti.letture_larghe import SCHERMATE as PAGINE  # noqa: E402

TAGLIE = (32, 20, 16, 14, 12, 11)

TRACCIATI = ("normal", "0.09em", "-0.01em", "-0.02em")

FILO = 1.0

IL_CONTO = r"""(taglie) => {
    const dentro = (e) => {

        for (const n of e.childNodes) {
            if (n.nodeType === 3 && n.textContent.trim().length) return true;
        }
        return false;
    };
    const visibile = (e) => {
        const r = e.getBoundingClientRect();
        return r.width > 0 && r.height > 0;
    };
    const nome = (e) => e.tagName.toLowerCase() +
        (e.className ? '.' + e.className.toString().trim().split(/\s+/).slice(0, 2).join('.') : '');
    const numero = (s) => parseFloat(s) || 0;
    const quattro = (px) => {
        const v = Math.abs(numero(px));
        return v === 0 || Math.abs(v - 1) < 0.01 || Math.abs(v % 4) < 0.01
               || Math.abs(v % 4 - 4) < 0.01;
    };

    const taglieStorte = [], tracciatiStorti = [], stacchiStorti = [];
    let quante = 0;

    for (const e of document.querySelectorAll('body *')) {
        if (e.closest('.solo-per-chi-ascolta')) continue;
        const s = getComputedStyle(e);
        if (s.display === 'none' || s.visibility === 'hidden') continue;
        if (!visibile(e)) continue;

        const controllo = e.matches('input, select, textarea');
        for (const lato of ['Top', 'Bottom']) {
            if (controllo) break;
            const v = s['margin' + lato];
            if (v.endsWith('px') && !quattro(v)) {
                stacchiStorti.push({che: nome(e), cosa: 'margin' + lato, quanto: v});
            }
        }
        for (const lato of ['Top', 'Right', 'Bottom', 'Left']) {
            if (controllo) break;
            const v = s['padding' + lato];
            if (v.endsWith('px') && !quattro(v)) {
                stacchiStorti.push({che: nome(e), cosa: 'padding' + lato, quanto: v});
            }
        }

        if (!dentro(e)) continue;
        quante++;
        const px = Math.round(numero(s.fontSize) * 100) / 100;
        if (!taglie.includes(Math.round(px * 100) / 100)) {
            taglieStorte.push({che: nome(e), quanto: px});
        }
        const t = s.letterSpacing;
        if (t !== 'normal') {

            tracciatiStorti.push({che: nome(e), quanto: Math.round(numero(t) / px * 1000) / 1000,
                                  px: Math.round(numero(t) * 1000) / 1000});
        }
    }
    return {quante, taglieStorte, tracciatiStorti, stacchiStorti};
}"""

def _tracciato_ammesso(em: float, px: float) -> bool:
    for t in TRACCIATI:
        if t == "normal":
            continue
        quanto = float(t.replace("em", ""))
        if abs(em - quanto) < 0.002:
            return True
        if any(abs(px - quanto * taglia) < 0.02 for taglia in TAGLIE):
            return True
    return False

def guarda(indirizzo: str = INDIRIZZO) -> int:
    try:
        from playwright.sync_api import sync_playwright

        from strumenti import navigatore
    except ImportError:
        print("Serve playwright, e non è installato:\n"
              "    pip install playwright\n"
              "    playwright install chromium")
        return -1

    taglie: dict[float, set[str]] = {}
    tracciati: dict[float, set[str]] = {}
    stacchi: dict[tuple[str, str], set[str]] = {}
    quante = 0

    with sync_playwright() as teatro:
        browser = navigatore.apri(teatro)
        for larghezza in LARGHEZZE:
            print(f"--- a {larghezza} px")
            pagina = browser.new_page(viewport={"width": larghezza, "height": 860})
            for dove in PAGINE:
                try:
                    pagina.goto(indirizzo + dove, wait_until="networkidle",
                                timeout=20000)
                except Exception as guaio:
                    print(f"  {dove:<22} non si apre: {type(guaio).__name__}")
                    continue
                pagina.wait_for_timeout(200)
                m = pagina.evaluate(IL_CONTO, list(TAGLIE))
                quante += m["quante"]
                guai = 0
                for v in m["taglieStorte"]:
                    taglie.setdefault(v["quanto"], set()).add(v["che"])
                    guai += 1
                for v in m["tracciatiStorti"]:
                    if _tracciato_ammesso(v["quanto"], v["px"]):
                        continue
                    tracciati.setdefault(v["quanto"], set()).add(v["che"])
                    guai += 1
                for v in m["stacchiStorti"]:
                    stacchi.setdefault((v["cosa"], v["quanto"]), set()).add(v["che"])
                    guai += 1
                segno = "  !!" if guai else "    "
                print(f"{segno}{dove:<22} {m['quante']} scritte, {guai} fuori posto")
            pagina.close()
        browser.close()

    def elenca(titolo: str, roba: dict, scrivi) -> None:
        if not roba:
            return
        print("\n" + titolo)
        for chiave in sorted(roba, key=str):
            chi = ", ".join(sorted(roba[chiave]))[:86]
            print("  " + scrivi(chiave) + "   " + chi)

    elenca("Taglie che non stanno sulla scala:", taglie, lambda k: f"{k:>7} px")
    elenca("Spazi fra le lettere non dichiarati:", tracciati, lambda k: f"{k:>7} em")
    elenca("Stacchi fuori dalla scala dei quattro:", stacchi,
           lambda k: f"{k[0]:>13} {k[1]:>8}")

    guai = len(taglie) + len(tracciati) + len(stacchi)
    print(f"\n{quante} scritte guardate.")
    print("Ogni scritta sta su uno dei sei gradini, e ogni stacco su quella dei quattro."
          if not guai else f"\nNumeri fuori posto, in tutto: {guai}")
    return guai

if __name__ == "__main__":
    sys.exit(min(guarda(sys.argv[1] if len(sys.argv) > 1 else INDIRIZZO), 1))
