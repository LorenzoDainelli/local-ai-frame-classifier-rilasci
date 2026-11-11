from __future__ import annotations

from officina.miglioria import ordine


class Orologio:

    def __init__(self) -> None:
        self.ora = 1000.0

    def __call__(self) -> float:
        return self.ora


def _riga(numero: int, genere: str = "immagine", secondi: float | None = 10.0,
          peso: float = 1.0) -> dict:
    return {"id": numero, "genere_del_file": genere, "secondi": secondi, "peso": peso}


def _modello(riga) -> str:
    return "foto" if riga["genere_del_file"] == "immagine" else "video"


def _stima(riga):
    return riga["secondi"], riga["peso"]


def _ids(righe) -> list[int]:
    return [riga["id"] for riga in righe]


def test_prima_le_corte_dello_stesso_modello():
    fila = ordine.Ordine(Orologio())
    righe = [_riga(1, secondi=50), _riga(2, secondi=5), _riga(3, secondi=20)]
    assert _ids(fila.in_fila(righe, _modello, _stima)) == [2, 3, 1]


def test_il_modello_gia_caricato_va_avanti_anche_se_piu_lungo():
    fila = ordine.Ordine(Orologio())
    fila.ultimo = "video"
    righe = [_riga(1, secondi=5), _riga(2, "video", secondi=900), _riga(3, "video",
                                                                     secondi=300)]
    assert _ids(fila.in_fila(righe, _modello, _stima)) == [3, 2, 1]


def test_senza_modello_caricato_parte_il_gruppo_col_lavoro_piu_corto():
    fila = ordine.Ordine(Orologio())
    righe = [_riga(1, "video", secondi=300), _riga(2, secondi=40), _riga(3, secondi=8)]
    assert _ids(fila.in_fila(righe, _modello, _stima)) == [3, 2, 1]


def test_senza_previsione_si_usa_quanto_c_e_da_fare():
    fila = ordine.Ordine(Orologio())
    righe = [_riga(1, secondi=None, peso=30), _riga(2, secondi=3, peso=90),
             _riga(3, secondi=None, peso=10)]
    assert _ids(fila.in_fila(righe, _modello, _stima)) == [3, 1, 2]


def test_a_parita_vale_l_ordine_di_arrivo():
    fila = ordine.Ordine(Orologio())
    righe = [_riga(4), _riga(2), _riga(9)]
    assert _ids(fila.in_fila(righe, _modello, _stima)) == [2, 4, 9]


def test_chi_aspetta_da_due_ore_passa_davanti():
    orologio = Orologio()
    fila = ordine.Ordine(orologio)
    lungo = _riga(1, "video", secondi=5000)
    fila.ultimo = "foto"
    assert _ids(fila.in_fila([lungo, _riga(2)], _modello, _stima)) == [2, 1]
    orologio.ora += ordine.ATTESA_MASSIMA - 1
    nuove = [lungo, _riga(3), _riga(4, secondi=1)]
    assert _ids(fila.in_fila(nuove, _modello, _stima)) == [4, 3, 1]
    orologio.ora += 1
    assert _ids(fila.in_fila(nuove, _modello, _stima)) == [1, 4, 3]


def test_l_attesa_conta_da_quando_il_lavoro_si_vede_nel_giro():
    orologio = Orologio()
    fila = ordine.Ordine(orologio)
    fila.in_fila([_riga(1, "video", secondi=5000), _riga(2)], _modello, _stima)
    orologio.ora += ordine.ATTESA_MASSIMA
    righe = [_riga(1, "video", secondi=5000), _riga(5, secondi=1)]
    assert _ids(fila.in_fila(righe, _modello, _stima)) == [1, 5]
    fila.in_fila([_riga(5, secondi=1)], _modello, _stima)
    righe = [_riga(1, "video", secondi=5000), _riga(5, secondi=1)]
    assert _ids(fila.in_fila(righe, _modello, _stima)) == [5, 1]


def test_il_peso_conta_pixel_e_fotogrammi():
    assert ordine.peso({"arrivo": 8.3}) == 8.3
    assert ordine.peso({"arrivo": 8.3, "fotogrammi": 300, "fluidi": 900}) == 8.3 * 1200
    assert ordine.peso({"megapixel": 2.0}) == 2.0
    assert ordine.peso({}) == 1.0
