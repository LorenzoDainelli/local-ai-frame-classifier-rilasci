from __future__ import annotations

from officina.web import lavori
from officina.web.passi import Passi


def test_il_conto_arriva_in_fondo_solo_quando_tutti_i_passi_sono_finiti():
    lavoro = lavori.Lavoro("prova")
    stime = {"uno": 10, "due": 5, "tre": 0}
    passi = Passi(lavoro, {"uno": "Uno", "due": "Due", "tre": "Tre"}, lambda: dict(stime))
    assert lavoro.numeri["fatti"] == 0 and lavoro.numeri["totale"] == 15
    assert [m["nome"] for m in lavoro.numeri["modelli"]] == ["uno", "due"]

    passi.inizia("uno")
    passi.segna("uno", 10, 10, "poco", corpi=3)
    assert lavoro.numeri["fatti"] == 10 and lavoro.numeri["totale"] == 15
    assert lavoro.numeri["corpi"] == 3
    assert lavoro.numeri["passo"] == "Uno"
    stime.update({"due": 7, "tre": 4})
    passi.finito("uno")
    assert lavoro.numeri["fatti"] == 10 and lavoro.numeri["totale"] == 21
    assert [m["nome"] for m in lavoro.numeri["modelli"]] == ["uno", "due", "tre"]
    assert lavoro.numeri["modelli"][0]["percento"] == 100

    passi.fai("due", lambda: passi.segna("due", 7, 7), lambda: False)
    assert lavoro.numeri["fatti"] < lavoro.numeri["totale"]
    passi.fai("tre", lambda: passi.segna("tre", 2, 4), lambda: False)
    assert lavoro.numeri["fatti"] == lavoro.numeri["totale"] == 19
    assert all(m["percento"] == 100 for m in lavoro.numeri["modelli"])


def test_se_si_ferma_il_passo_non_si_segna_finito():
    lavoro = lavori.Lavoro("prova")
    passi = Passi(lavoro, {"uno": "Uno", "due": "Due"}, lambda: {"uno": 10, "due": 3})
    fermata = {"si": False}

    def lavora() -> None:
        passi.segna("uno", 4, 10)
        fermata["si"] = True

    passi.fai("uno", lavora, lambda: fermata["si"])
    passi.fai("due", lambda: passi.segna("due", 3, 3), lambda: fermata["si"])
    assert lavoro.numeri["fatti"] == 4 and lavoro.numeri["totale"] == 13


def test_una_stima_rotta_non_ferma_niente():
    lavoro = lavori.Lavoro("prova")

    def rotta():
        raise RuntimeError("no")

    Passi(lavoro, {"uno": "Uno"}, rotta)
    assert lavoro.numeri["totale"] == 0


class _Avanzamento:
    fatti = saltati = gia_fatti = corpi = 0
    totale = 0

    def a_parole(self) -> str:
        return "fatto"


class _PassataFinta:

    def __init__(self, quanti: int):
        self.quanti = quanti
        self.fermata = False
        self.archivio = None
        self.avanzamento = _Avanzamento()

    def quanti_mancano(self) -> int:
        return self.quanti

    def esegui(self, al_passo=None):
        for numero in range(1, self.quanti + 1):
            self.avanzamento.fatti = numero
            self.avanzamento.totale = self.quanti
            al_passo(self.avanzamento)
        return self.avanzamento


def test_corpi_dice_tutto_fatto_solo_alla_fine_di_tutti_i_passi(monkeypatch):
    from officina.web.strade import comune
    from officina.web.strade import intelligenza as ia

    visti = []
    monkeypatch.setattr(comune, "lavoro_corpi", lavori.Lavoro("i corpi"))
    monkeypatch.setattr(ia, "_stime_dei_corpi",
                        lambda passata: {"corpi": 3, "parti": 4, "chi_e": 1})

    def guarda() -> None:
        numeri = comune.lavoro_corpi.numeri
        visti.append((numeri["fatti"], numeri["totale"]))

    def parti(passata) -> None:
        for numero in range(1, 5):
            ia._metti_corpi("parti", {"fatti": numero, "totale": 4, "quanto_manca": ""})
            guarda()

    for nome in ("_rifai_i_punti", "_fai_le_figure", "_fai_le_superfici",
                 "_guarda_gli_aiuti_delle_persone", "_cerca_le_parti_imparate",
                 "_fai_le_stanze"):
        monkeypatch.setattr(ia, nome, lambda passata: None)
    monkeypatch.setattr(ia, "_cerca_le_parti", parti)
    monkeypatch.setattr(ia, "cerca_chi_e", lambda *a, segna=None, **k: segna(
        {"fatti": 2, "totale": 2, "corpi": 1, "quanto_manca": ""}))
    passata = _PassataFinta(3)
    ia._guarda_i_corpi(passata)
    assert all(fatti < totale for fatti, totale in visti)
    numeri = comune.lavoro_corpi.numeri
    assert numeri["fatti"] == numeri["totale"] == 3 + 4 + 2
    assert [m["nome"] for m in numeri["modelli"]] == ["corpi", "parti", "chi_e"]
    assert comune.passi_corpi is None
