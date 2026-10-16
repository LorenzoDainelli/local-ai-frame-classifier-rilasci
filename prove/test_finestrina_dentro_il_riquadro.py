from __future__ import annotations

from pathlib import Path

import pytest

from officina.programma import pagine

sync_api = pytest.importorskip("playwright.sync_api")

LUNGO = "SAM 3, RTMW, KPR, SAM 3D Body, Puffin, VGGT-Omega e Depth Anything 3"


@pytest.mark.parametrize("larghezza", [380, 546, 900])
def test_lo_scaricamento_dei_modelli_resta_nel_riquadro(larghezza):
    with sync_api.sync_playwright() as p:
        pronto = Path("/opt/pw-browsers/chromium")
        try:
            browser = p.chromium.launch(executable_path=str(pronto) if pronto.exists() else None)
        except sync_api.Error as guasto:
            pytest.skip(f"niente browser: {guasto}")
        pagina = browser.new_page(viewport={"width": larghezza, "height": 640})
        pagina.set_content(pagine.finestrina("2.0.0"))
        fuori = pagina.evaluate("""(lungo) => {
            document.querySelectorAll("[data-passo]").forEach(s => s.hidden = true);
            document.querySelector("[data-passo='modelli']").hidden = false;
            const sezione0 = document.querySelector("[data-passo='modelli']");
            sezione0.querySelector("[data-se='scegli']").hidden = true;
            sezione0.querySelector("[data-se='scarica']").hidden = false;
            sezione0.querySelector("[data-campo='adesso']").textContent = lungo + " · 46%";
            sezione0.querySelector("[data-campo='quanto']").textContent = "4,8 GB di 10,5 GB";
            sezione0.querySelector("[data-barra-modelli] .fatto").style.width = "46%";
            const li = document.createElement("li");
            li.className = "adesso";
            li.innerHTML = '<span class="tondo"></span><span></span><span>10,5 GB</span>';
            li.children[1].textContent = lungo;
            sezione0.querySelector("[data-fila]").appendChild(li);
            const scatola = document.querySelector("[data-passo='modelli'] .grande").getBoundingClientRect();
            const sezione = document.querySelector("[data-passo='modelli']");
            const male = [];
            sezione.querySelectorAll(".grande *, .fila-modelli *").forEach(e => {
                const r = e.getBoundingClientRect();
                if (r.width && r.right > Math.max(scatola.right, sezione.getBoundingClientRect().right) + 0.5) {
                    male.push(e.className || e.tagName);
                }
            });
            const quanto = sezione.querySelector("[data-campo='quanto']");
            if (quanto.getClientRects().length > 1 || quanto.offsetHeight > 30) { male.push("quanto a capo"); }
            if (document.documentElement.scrollWidth > window.innerWidth) { male.push("pagina larga"); }
            return male;
        }""", LUNGO)
        browser.close()
    assert fuori == []
