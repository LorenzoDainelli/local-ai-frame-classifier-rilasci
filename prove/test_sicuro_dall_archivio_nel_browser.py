from __future__ import annotations

from prove import test_pagine_nel_browser as nel_browser
from prove import test_sicuro_dall_archivio as dall_archivio
from prove import test_sicuro_servizio as servizio_di_prova

costo_leggero = servizio_di_prova.costo_leggero
navigatore = nel_browser.navigatore
foto_nell_archivio = dall_archivio.foto_nell_archivio
_rovina = dall_archivio._rovina
_stacca = dall_archivio._stacca


def test_la_foto_persa_si_vede_nel_browser_solo_quando_serve(navigatore,
                                                            foto_nell_archivio):
    pronta = foto_nell_archivio
    visto = {}

    def guarda(pagina):
        visto["persa"] = pagina.locator("#foto-persa").is_visible()
        visto["foto"] = pagina.locator("#lastra-principale").is_visible()

    assert nel_browser._guarda(navigatore, pronta.cliente, f"/scatto/{pronta.scatto_id}",
                               guarda) == []
    assert visto == {"persa": False, "foto": True}
    _stacca(pronta.casa)
    _rovina(pronta.casa, pronta.relativo)
    visto.clear()
    errori = nel_browser._guarda(navigatore, pronta.cliente, f"/scatto/{pronta.scatto_id}",
                                 guarda)
    assert [errore for errore in errori if "status of 400" not in errore] == []
    assert visto == {"persa": True, "foto": False}


def test_la_foto_rovinata_dopo_che_la_pagina_e_aperta_mostra_l_allarme(navigatore,
                                                                      foto_nell_archivio):
    pronta = foto_nell_archivio
    visto = {}

    def rompi_e_riprova(pagina):
        _stacca(pronta.casa)
        _rovina(pronta.casa, pronta.relativo)
        pagina.evaluate("""() => {
            const foto = document.getElementById("lastra-principale");
            foto.src = foto.src + "?di-nuovo=1";
        }""")
        pagina.wait_for_selector("#foto-persa", state="visible", timeout=5000)
        visto["persa"] = pagina.locator("#foto-persa").is_visible()
        visto["sostituto"] = pagina.locator("#foto-non-si-vede").is_visible()
        visto["foto"] = pagina.locator("#lastra-principale").is_visible()
        visto["pillola"] = pagina.locator(".ft-dall-archivio").count()

    errori = nel_browser._guarda(navigatore, pronta.cliente, f"/scatto/{pronta.scatto_id}",
                                 rompi_e_riprova)
    assert [errore for errore in errori if "status of 400" not in errore] == []
    assert visto == {"persa": True, "sostituto": False, "foto": False, "pillola": 0}
