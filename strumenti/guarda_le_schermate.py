from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

INDIRIZZO = "http://127.0.0.1:8731"

LARGHEZZE = (1280, 900, 683)

from strumenti.letture_larghe import SCHERMATE as PAGINE  # noqa: E402

IL_CONTO = """() => {
    const largo = document.documentElement.clientWidth;
    const fuori = [];
    for (const e of document.querySelectorAll('body *')) {
        const r = e.getBoundingClientRect();
        if (r.width === 0 || r.height === 0) continue;
        if (r.right <= largo + 1 && r.left >= -1) continue;
        fuori.push({
            che: e.tagName.toLowerCase() + '.' +
                 (e.className || '').toString().split(' ')[0],
            da: Math.round(r.left), a: Math.round(r.right),
        });
    }
    return {scorre: document.documentElement.scrollWidth, largo,
            fuori: fuori.slice(0, 5)};
}"""

I_PANNELLI = """() => {
    const largo = document.documentElement.clientWidth;
    const fuori = [];
    const tasti = document.querySelectorAll('.chiedi');
    for (let n = 0; n < tasti.length; n++) {
        tasti[n].click();
        const aperto = document.querySelector('.pannello:not([hidden])');
        if (!aperto) { fuori.push({n, da: 0, a: 0, perche: 'non si apre'}); continue; }
        const r = aperto.getBoundingClientRect();
        if (r.left < -1 || r.right > largo + 1) {
            fuori.push({n, da: Math.round(r.left), a: Math.round(r.right),
                        perche: aperto.querySelector('.pannello-titolo').textContent});
        }
        tasti[n].click();
    }
    return {quanti: tasti.length, largo, fuori: fuori.slice(0, 5)};
}"""

def guarda(indirizzo: str = INDIRIZZO) -> int:
    try:
        from playwright.sync_api import sync_playwright

        from strumenti import navigatore
    except ImportError:
        print("Serve playwright, e non è installato:\n"
              "    pip install playwright\n"
              "    playwright install chromium")
        return -1

    storte = 0
    with sync_playwright() as teatro:
        browser = navigatore.apri(teatro)
        for larghezza in LARGHEZZE:
            print(f"--- a {larghezza} px")
            pagina = browser.new_page(
                viewport={"width": larghezza, "height": 860})
            detti: list[str] = []
            pagina.on("pageerror",
                      lambda guaio, detti=detti: detti.append(str(guaio)))
            pagina.on("console",
                      lambda voce, detti=detti: detti.append(voce.text)
                      if voce.type == "error" else None)
            for dove in PAGINE:
                try:
                    pagina.goto(indirizzo + dove, wait_until="networkidle",
                                timeout=20000)
                except Exception as guaio:
                    print(f"  {dove:<20} non si apre: {type(guaio).__name__}")
                    continue
                pagina.wait_for_timeout(250)
                misura = pagina.evaluate(IL_CONTO)
                storta = misura["scorre"] > misura["largo"] + 1
                storte += int(storta)
                print(f"{'  !!' if storta else '    '}{dove:<20} "
                      f"scorre {misura['scorre']:>5} / {misura['largo']}")
                for chi in misura["fuori"]:
                    print(f"         fuori: {chi['che']:<30} "
                          f"da {chi['da']} a {chi['a']}")

                pannelli = pagina.evaluate(I_PANNELLI)
                if pannelli["fuori"]:
                    storte += len(pannelli["fuori"])
                    for chi in pannelli["fuori"]:
                        print(f"  !!     il «?» numero {chi['n']} esce dalla "
                              f"finestra: da {chi['da']} a {chi['a']} su "
                              f"{pannelli['largo']} — {chi['perche']}")
            if detti:
                print("  il javascript ha detto:", detti[:4])
            pagina.close()
        browser.close()
    return storte

if __name__ == "__main__":
    dove = sys.argv[1] if len(sys.argv) > 1 else INDIRIZZO
    quante = guarda(dove)
    if quante > 0:
        print(f"\n{quante} pagine escono dalla finestra.")
    elif quante == 0:
        print("\nNessuna pagina esce dalla finestra.")
    raise SystemExit(1 if quante != 0 else 0)
