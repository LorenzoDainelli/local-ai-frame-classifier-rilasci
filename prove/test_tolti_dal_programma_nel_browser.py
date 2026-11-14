from __future__ import annotations

import pytest

from prove.test_impronte_giusto_nel_browser import _servito, navigatore  # noqa: F401
from prove.test_tolti_dal_programma import _c_e, rotto  # noqa: F401

sync_api = pytest.importorskip("playwright.sync_api")


def test_togli_chiede_conferma_poi_toglie_e_si_rimette(navigatore, rotto):  # noqa: F811
    from officina.web import origine
    from officina.web.server import app

    archivio, scatto, posto = rotto
    errori: list[str] = []
    with _servito(app) as indirizzo:
        pagina = navigatore.new_page(viewport={"width": 1280, "height": 900})
        pagina.on("pageerror", lambda e: errori.append(str(e)))
        pagina.goto(origine.indirizzo_per_entrare(indirizzo, "/intelligenza/perche-mancano"),
                    wait_until="load")
        via = pagina.locator(f"[data-pm-via='{scatto}']")
        conferma = via.locator("[data-pm-via-conferma]")
        assert conferma.is_hidden()
        via.locator("[data-pm-via-chiedi]").click()
        assert conferma.is_visible()
        assert "Il file sul disco resta" in conferma.inner_text()
        via.locator("[data-pm-via-no]").click()
        assert conferma.is_hidden() and _c_e(archivio, scatto)
        via.locator("[data-pm-via-chiedi]").click()
        via.locator("[data-pm-via-si]").click()
        sync_api.expect(via.locator("[data-pm-via-detto]")).to_contain_text("Tolto")
        assert not _c_e(archivio, scatto)
        assert posto.exists()
        for larga in (1440, 1024):
            pagina.set_viewport_size({"width": larga, "height": 900})
            assert pagina.evaluate(
                "document.documentElement.scrollWidth <= window.innerWidth")
        pagina.reload(wait_until="load")
        tolto = pagina.locator("#tolti-dal-programma [data-pm-tolto]")
        sync_api.expect(tolto).to_have_count(1)
        assert posto.name in tolto.inner_text()
        tolto.locator("[data-pm-rimetti]").click()
        sync_api.expect(tolto.locator("[data-pm-rimetti-detto]")).to_contain_text("Rimesso")
        assert not errori, errori
        pagina.close()
    with archivio.lettura() as connessione:
        assert connessione.execute(
            "SELECT count(*) FROM tolti_dal_programma").fetchone()[0] == 0
