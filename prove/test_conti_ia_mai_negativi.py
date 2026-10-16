from __future__ import annotations

import re

from fastapi.testclient import TestClient


def test_i_lavori_del_corpo_piu_degli_scatti_non_danno_numeri_negativi(archivio_pieno, monkeypatch):
    from officina.web.server import app
    from officina.web.strade import intelligenza

    vero = intelligenza.quanti_mancano_ia

    def gonfiato(archivio):
        conti = vero(archivio)
        conti["corpi"] = conti["totale"] * 2 + 2
        return conti

    monkeypatch.setattr(intelligenza, "quanti_mancano_ia", gonfiato)
    monkeypatch.setattr(intelligenza.corpi_rilevatore, "cosa_manca", lambda dove: [])
    cliente = TestClient(app, client=("127.0.0.1", 51000))
    pagina = cliente.get("/intelligenza").text
    totale = vero(intelligenza.accesso.aperto())["totale"]
    assert totale > 0
    carta = pagina.split('data-lavoro="corpi"', 1)[1].split("</section>", 1)[0]
    assert not re.search(r"ia-num numeri\">\s*-", carta)
    numeri = re.search(r'ia-num numeri">\s*([\d.]+) <small>di ([\d.]+)', carta)
    assert numeri and numeri.group(1) == "0"
    trovato = re.search(r"Mancano ([\d.]+) scatt", carta)
    assert not trovato or int(trovato.group(1).replace(".", "")) <= totale
