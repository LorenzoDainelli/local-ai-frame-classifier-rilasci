from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

INDIRIZZO = "http://127.0.0.1:8731"
LARGHEZZE = (1280, 900)

from strumenti.letture_larghe import SCHERMATE as PAGINE  # noqa: E402

FAMIGLIE = {
    "comando": (40, "button.tasto-comando, a.tasto-comando, input.campo, "
                    "select.campo, .tasto-pericolo, .campo-cerca"),
    "barra": (32, ".barra-alta .voce .nome, .barra-alta .apri-stanze > summary, "
                  ".tasto-lente, .senza-password, .barra-alta .pillola"),
    "lente-grande": (48, ".campo-lente"),
    "etichetta": (32, ".pillola"),
    "fitta": (24, ".pillola.scelta, .scheda .didascalia .pillola"),
}

IL_CONTO = """(famiglie) => {

    const ordine = ['fitta', 'lente-grande', 'barra', 'comando', 'etichetta'];
    const quale = (e) => ordine.find(f => e.matches(famiglie[f][1])) || null;

    const visti = [];
    for (const f of ordine) {
        for (const e of document.querySelectorAll(famiglie[f][1])) {
            if (quale(e) !== f) continue;
            if (visti.some(v => v.e === e)) continue;
            const r = e.getBoundingClientRect();
            if (r.width === 0 || r.height === 0) continue;
            visti.push({
                e, fam: f,
                che: e.tagName.toLowerCase() + '.' +
                     (e.className || '').toString().split(' ').slice(0, 2).join('.'),
                alto: Math.round(r.height * 10) / 10,
                su: r.top, giu: r.bottom, dove: e.parentElement,
            });
        }
    }

    const sbagliati = visti
        .filter(v => Math.round(v.alto) !== famiglie[v.fam][0])
        .map(v => ({che: v.che, alto: v.alto, fam: v.fam, deve: famiglie[v.fam][0]}));

    const righe = [];
    for (const v of visti) {
        let trovata = null;
        for (const riga of righe) {
            const a = riga[0];
            if (a.dove !== v.dove) continue;
            const quanto = Math.min(a.giu, v.giu) - Math.max(a.su, v.su);
            if (quanto > Math.min(a.giu - a.su, v.giu - v.su) / 2) { trovata = riga; break; }
        }
        if (trovata) trovata.push(v); else righe.push([v]);
    }

    const storte = [];
    for (const riga of righe) {
        for (const f of ordine) {
            const gente = riga.filter(v => v.fam === f);
            if (gente.length < 2) continue;
            if (new Set(gente.map(v => v.alto)).size > 1) {
                storte.push(gente.map(v => ({che: v.che, alto: v.alto})));
            }
        }
    }
    return {quanti: visti.length, sbagliati, storte};
}"""

IL_PAREGGIO = """() => {
    const COMANDI = "button, .tasto-comando, .pillola, .commuta, .campo, select,"
                  + " input[type=submit]";
    const TESTI = "h1, h2, h3, h4, p, span, label, em, strong, time, dt, dd";

    const centroDelTesto = (t) => {
        const s = getComputedStyle(t), fs = parseFloat(s.fontSize);
        const lh = parseFloat(s.lineHeight) || fs * 1.2;
        const r = t.getBoundingClientRect();
        if (!r.height) return null;
        return {y: r.top + (lh - fs) / 2 + 0.72 * fs / 2, fs, r};
    };

    const storti = [];
    for (const riga of document.querySelectorAll(".riga-fra, .in-fila")) {

        const comandi = [...riga.querySelectorAll(COMANDI)]
            .filter(e => e.getBoundingClientRect().height > 0);

        const testi = [...riga.children]
            .filter(e => !e.matches(COMANDI) && !e.querySelector(COMANDI))
            .flatMap(e => e.matches(TESTI) ? [e] : [...e.querySelectorAll(TESTI)])
            .filter(t => [...t.childNodes].some(
                n => n.nodeType === 3 && n.textContent.trim()));

        for (const c of comandi) {
            const cr = c.getBoundingClientRect();
            const centro = cr.top + cr.height / 2;
            for (const el of testi) {
                const t = centroDelTesto(el);
                if (!t) continue;

                const basso = Math.min(cr.bottom, t.r.bottom);
                const alto = Math.max(cr.top, t.r.top);
                if (basso - alto < 0.6 * Math.min(cr.height, t.r.height)) continue;
                const scarto = centro - t.y;
                if (Math.abs(scarto) >= 1.0) storti.push({
                    testo: (el.className || el.tagName).toString().slice(0, 24),
                    taglia: Math.round(t.fs),
                    comando: (c.className || c.tagName).toString().slice(0, 24),
                    scarto: Math.round(scarto * 10) / 10,
                });
            }
        }
    }
    return storti;
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
    fuori_asse = 0
    strane: dict[float, set[str]] = {}
    with sync_playwright() as teatro:
        browser = navigatore.apri(teatro)
        for larghezza in LARGHEZZE:
            print(f"--- a {larghezza} px")
            pagina = browser.new_page(
                viewport={"width": larghezza, "height": 860})
            for dove in PAGINE:
                try:
                    pagina.goto(indirizzo + dove, wait_until="networkidle",
                                timeout=20000)
                except Exception as guaio:
                    print(f"  {dove:<22} non si apre: {type(guaio).__name__}")
                    continue
                pagina.wait_for_timeout(200)
                misura = pagina.evaluate(IL_CONTO, FAMIGLIE)
                for voce in misura["sbagliati"]:
                    strane.setdefault(
                        (voce["fam"], voce["deve"], voce["alto"]),
                        set()).add(voce["che"])
                if misura["storte"]:
                    storte += len(misura["storte"])
                    print(f"  !!{dove:<22} {len(misura['storte'])} righe storte")
                    for gente in misura["storte"][:3]:
                        pezzi = ", ".join(f"{v['che']} {v['alto']}" for v in gente[:6])
                        print(f"         {pezzi}")
                else:
                    print(f"    {dove:<22} "
                          f"{misura['quanti']} comandi, tutti in riga")
                pareggio = pagina.evaluate(IL_PAREGGIO)
                if pareggio:
                    fuori_asse += len(pareggio)
                    print(f"  !!{dove:<22} {len(pareggio)} comandi fuori asse "
                          f"dal testo accanto")
                    for voce in pareggio[:3]:
                        print(f"         {voce['scarto']:+.1f}px  "
                              f"{voce['comando']} contro {voce['testo']} "
                              f"{voce['taglia']}px")
            pagina.close()
        browser.close()

    if strane:
        print("\nAltezze sbagliate per la loro famiglia:")
        for fam, deve, alto in sorted(strane):
            chi = ", ".join(sorted(strane[(fam, deve, alto)]))[:80]
            print(f"  {fam:<13} deve {deve:>3}, è {alto:>6}   {chi}")
    else:
        print("\nOgni comando è alto quanto dice la sua famiglia.")

    print("\nNessuna riga storta." if not storte
          else f"\nRighe storte in tutto: {storte}")
    print("Ogni comando è in asse con il testo che ha accanto."
          if not fuori_asse
          else f"Comandi fuori asse in tutto: {fuori_asse}")
    return storte + len(strane) + fuori_asse

if __name__ == "__main__":
    sys.exit(min(guarda(sys.argv[1] if len(sys.argv) > 1 else INDIRIZZO), 1))
