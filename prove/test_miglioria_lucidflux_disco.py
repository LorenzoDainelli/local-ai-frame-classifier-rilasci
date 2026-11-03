from __future__ import annotations

import contextlib
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from officina import registro
from officina.miglioria import catena, coda, lavoro, lucidflux, lucidflux_pesi, motori
from prove.test_miglioria import _jpeg, _metti, _riga, cartella, importato

__all__ = ["cartella", "importato"]

G = lucidflux.GIGA
MARGINE = lucidflux.MARGINE_RAM
FORME = {"img_in.weight": (8,), "double_blocks.0.w": (G,), "double_blocks.1.w": (G,),
         "single_blocks.0.w": (G // 2,), "single_blocks.1.w": (G // 2,),
         "single_blocks.2.w": (G // 4,), "single_blocks.2.b": (G // 4,)}
MISURA = {"secondi": 754.2, "dove_stanno": {"scheda": 7.1, "ram": 9.0, "disco": 6.2}}
DETTO = " (LucidFlux ci ha messo 12 min 34 s, 6,2 GB letti dal disco)"
CON_AV = pytest.mark.skipif(importlib.util.find_spec("av") is None, reason="manca av")


def test_nella_scheda_quel_che_ci_sta_poi_nella_ram_e_il_resto_dal_disco():
    pesi = [2 * G, 2 * G, G, G, G]
    assert lucidflux.dove_vanno(pesi, 2 * G, MARGINE + 3 * G) == (1, 3)
    assert lucidflux.dove_vanno(pesi, 2 * G, MARGINE + 3 * G - 1) == (1, 2)
    assert lucidflux.dove_vanno(pesi, 2 * G, MARGINE + 2 * G) == (1, 2)
    assert lucidflux.dove_vanno(pesi, 2 * G, 100 * G) == (1, 5)
    assert lucidflux.dove_vanno(pesi, -G, MARGINE + 4 * G) == (0, 2)
    assert lucidflux.dove_vanno(pesi, 6 * G, MARGINE + G) == (4, 5)
    assert lucidflux.dove_vanno(pesi, 100 * G, MARGINE) == (5, 5)
    assert lucidflux.dove_vanno(pesi, 2 * G, None) == (1, 1)
    assert lucidflux.dove_vanno(pesi, 2 * G, None, dal_disco=False) == (1, 5)
    assert lucidflux.dove_vanno(pesi, 2 * G, MARGINE + 5 * G, dal_disco=False) == (1, 5)


def test_la_ram_che_serve_e_un_blocco_solo_se_il_resto_si_legge_dal_disco():
    pesi = [2 * G, 2 * G, G, G, G]
    with pytest.raises(lucidflux.RamPoca) as preso:
        lucidflux.dove_vanno(pesi, 2 * G, MARGINE + 2 * G - 1)
    assert str(preso.value) == ("Per LucidFlux servono almeno 5 GB di RAM libera "
                                "e ce ne sono 4.")
    with pytest.raises(lucidflux.RamPoca) as preso:
        lucidflux.dove_vanno(pesi, 100 * G, MARGINE - 1)
    assert str(preso.value) == ("Per LucidFlux servono almeno 3 GB di RAM libera "
                                "e ce ne sono 2.")
    with pytest.raises(lucidflux.RamPoca) as preso:
        lucidflux.dove_vanno(pesi, 2 * G, MARGINE + 5 * G - 1, dal_disco=False)
    assert str(preso.value) == ("Per LucidFlux servono almeno 8 GB di RAM libera "
                                "e ce ne sono 7.")
    with pytest.raises(lucidflux.RamPoca) as preso:
        lucidflux.dove_vanno([G + G // 2], 0, MARGINE)
    assert str(preso.value) == ("Per LucidFlux servono almeno 5 GB di RAM libera "
                                "e ce ne sono 3.")


def test_la_ram_libera_la_dice_psutil_e_senza_non_si_sa(monkeypatch):
    monkeypatch.setitem(sys.modules, "psutil", SimpleNamespace(
        virtual_memory=lambda: SimpleNamespace(available=7.0 * G)))
    libera = lucidflux.ram_libera()
    assert libera == 7 * G and type(libera) is int
    monkeypatch.setitem(sys.modules, "psutil", None)
    assert lucidflux.ram_libera() is None


def test_appena_acceso_lucidflux_non_sa_ancora_dove_stanno_i_pesi(tmp_path, monkeypatch):
    monkeypatch.setattr(lucidflux_pesi, "e_in_casa", lambda cartella: True)
    monkeypatch.setattr(lucidflux_pesi, "dove", lambda cartella: cartella)
    assert lucidflux.LucidFlux(cartella_modelli=str(tmp_path)).dove_stanno is None


def test_i_giga_hanno_un_decimale():
    assert lucidflux.in_giga(0) == 0.0
    assert lucidflux.in_giga(3 * G // 2) == 1.5
    assert lucidflux.in_giga(G * 6.249) == 6.2
    assert lucidflux.in_giga(G * 6.251) == 6.3


class _Tensore:

    def __init__(self, nome: str, dove: str = "file", tipo: str = "BF16") -> None:
        self.nome, self.dove, self.tipo = nome, dove, tipo

    def to(self, dove, **_opzioni):
        if dove == "bf16":
            return self if self.tipo == "BF16" else _Tensore(self.nome, "ram")
        if getattr(dove, "type", dove) == "cpu":
            return self if self.dove != "scheda" else _Tensore(self.nome, "ram")
        return _Tensore(self.nome, "scheda")

    def pin_memory(self):
        return _Tensore(self.nome, "fissata")


class _Parte:

    def __init__(self, dato) -> None:
        self.data = dato


class _Blocco:

    def __init__(self) -> None:
        self.parti: list = []
        self.ganci: list = []

    def parameters(self):
        return iter(self.parti)

    def buffers(self):
        return iter([])

    def register_forward_pre_hook(self, gancio):
        self.ganci.append(gancio)
        return SimpleNamespace(remove=lambda: None)

    register_forward_hook = register_forward_pre_hook


class _Flux:

    def __init__(self, parametri) -> None:
        assert parametri == "parametri"
        self.double_blocks = [_Blocco(), _Blocco()]
        self.single_blocks = [_Blocco(), _Blocco(), _Blocco()]
        self.fuori: dict = {}

    def to(self, tipo):
        assert tipo == "bf16"
        return self

    def load_state_dict(self, stato, strict, assign):
        assert strict is False and assign is True
        for nome, tensore in stato.items():
            gruppo, _, resto = nome.partition(".")
            if gruppo in ("double_blocks", "single_blocks"):
                getattr(self, gruppo)[int(resto.split(".")[0])].parti.append(_Parte(tensore))
            else:
                self.fuori[nome] = tensore

    def eval(self):
        return self


class _File:

    def __init__(self, tipi: dict) -> None:
        self.tipi = tipi
        self.dati: dict = {}
        self.aperto: tuple | None = None

    def __call__(self, percorso, framework):
        self.aperto = (percorso, framework)
        return self

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def keys(self):
        return list(FORME)

    def get_slice(self, nome):
        return SimpleNamespace(get_shape=lambda: list(FORME[nome]),
                               get_dtype=lambda: self.tipi.get(nome, "BF16"))

    def get_tensor(self, nome):
        self.dati[nome] = _Tensore(nome, tipo=self.tipi.get(nome, "BF16"))
        return self.dati[nome]


def _flusso(monkeypatch, tmp_path, libera, tipo="cuda", tipi=None, fissa=True):
    file = _File(tipi or {})
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(
        bfloat16="bf16", device=lambda _tipo: contextlib.nullcontext(),
        cuda=SimpleNamespace(is_available=lambda: fissa)))
    monkeypatch.setitem(sys.modules, "safetensors", SimpleNamespace(safe_open=file))
    monkeypatch.setattr(lucidflux, "ram_libera", libera)
    motore = object.__new__(lucidflux.LucidFlux)
    motore.pesi = tmp_path
    motore._scambio = None
    motore.dove_stanno = None
    s = {"util": SimpleNamespace(configs={"flux-dev": SimpleNamespace(params="parametri")},
                                 Flux=_Flux)}
    modello, dentro, tutti = motore._flusso(s, SimpleNamespace(type=tipo), 2 * G)
    blocchi = modello.double_blocks + modello.single_blocks
    return motore, file, modello, blocchi, dentro, tutti


def _dove(blocco) -> list[str]:
    return [parte.data.dove for parte in blocco.parti]


def test_i_blocchi_che_non_stanno_nella_ram_restano_letti_dal_file(monkeypatch, tmp_path):
    motore, file, modello, blocchi, dentro, tutti = _flusso(
        monkeypatch, tmp_path, lambda: MARGINE + 3 * G)
    assert file.aperto == (str(tmp_path / lucidflux_pesi.FLUSSO), "pt")
    assert (dentro, tutti) == (1, 5)
    assert motore.dove_stanno == {"scheda": 2.0, "ram": 3.0, "disco": 2.0}
    assert modello.fuori["img_in.weight"].dove == "scheda"
    assert [_dove(blocco) for blocco in blocchi] == [
        ["scheda"], ["fissata"], ["fissata"], ["file"], ["file", "file"]]
    assert blocchi[0].ganci == [] and all(len(blocco.ganci) == 2 for blocco in blocchi[1:])
    assert motore._scambio.fuori == blocchi[1:] and motore._scambio.fissa is True
    for blocco in blocchi[1:]:
        assert all(parte._in_ram is parte.data for parte in blocco.parti)
    for blocco in blocchi[3:]:
        assert all(parte.data is file.dati[parte.data.nome] for parte in blocco.parti)

    entra, esce = blocchi[4].ganci
    entra(blocchi[4], ())
    assert _dove(blocchi[4]) == ["scheda", "scheda"]
    esce(blocchi[4], (), None)
    assert [parte.data for parte in blocchi[4].parti] == [
        file.dati["single_blocks.2.w"], file.dati["single_blocks.2.b"]]


def test_senza_sapere_la_ram_libera_tutto_quel_che_e_fuori_si_legge_dal_disco(
        monkeypatch, tmp_path):
    motore, file, _modello, blocchi, dentro, _tutti = _flusso(monkeypatch, tmp_path,
                                                              lambda: None)
    assert dentro == 1
    assert motore.dove_stanno == {"scheda": 2.0, "ram": 0.0, "disco": 5.0}
    assert [_dove(blocco) for blocco in blocchi] == [
        ["scheda"], ["file"], ["file"], ["file"], ["file", "file"]]


def test_un_peso_non_bf16_non_si_legge_dal_disco(monkeypatch, tmp_path):
    tipi = {"single_blocks.2.b": "F16"}
    with pytest.raises(lucidflux.RamPoca) as preso:
        _flusso(monkeypatch, tmp_path, lambda: MARGINE + 3 * G, tipi=tipi)
    assert "almeno 8 GB" in str(preso.value)
    motore, _file, _modello, blocchi, _dentro, _tutti = _flusso(
        monkeypatch, tmp_path, lambda: MARGINE + 5 * G, tipi=tipi)
    assert motore.dove_stanno == {"scheda": 2.0, "ram": 5.0, "disco": 0.0}
    assert [_dove(blocco) for blocco in blocchi] == [
        ["scheda"], ["fissata"], ["fissata"], ["fissata"], ["fissata", "fissata"]]
    motore, _file, _modello, blocchi, _dentro, _tutti = _flusso(
        monkeypatch, tmp_path, lambda: None, tipi={"img_in.weight": "F32"})
    assert motore.dove_stanno["disco"] == 0.0 and _dove(blocchi[4]) == ["fissata"] * 2


def test_senza_scheda_tutto_resta_dov_e_e_la_ram_non_si_chiede(monkeypatch, tmp_path):
    def mai():
        raise AssertionError("la RAM non si chiede")

    motore, _file, _modello, blocchi, dentro, tutti = _flusso(
        monkeypatch, tmp_path, mai, tipo="cpu", fissa=False)
    assert (dentro, tutti) == (5, 5) and motore.dove_stanno is None
    assert all(blocco.ganci == [] for blocco in blocchi)
    assert [_dove(blocco) for blocco in blocchi] == [
        ["file"], ["file"], ["file"], ["file"], ["file", "file"]]


def test_lo_scambiatore_non_fissa_quel_che_si_legge_dal_disco(monkeypatch):
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(
        cuda=SimpleNamespace(is_available=lambda: True)))
    scambio = lucidflux.Scambiatore(SimpleNamespace(type="cuda"))
    dal_disco, in_ram = _Blocco(), _Blocco()
    letto = _Tensore("a")
    dal_disco.parti.append(_Parte(letto))
    in_ram.parti.append(_Parte(_Tensore("b")))
    scambio.metti_fuori(dal_disco, in_ram=False)
    scambio.metti_fuori(in_ram)
    assert dal_disco.parti[0].data is letto and dal_disco.parti[0]._in_ram is letto
    assert in_ram.parti[0].data.dove == "fissata" and scambio.fissa is True


def test_quanto_ci_ha_messo_a_parole():
    assert lavoro.tempo_a_parole(0) == "0 s"
    assert lavoro.tempo_a_parole(-3) == "0 s"
    assert lavoro.tempo_a_parole(59.4) == "59 s"
    assert lavoro.tempo_a_parole(59.6) == "1 min 0 s"
    assert lavoro.tempo_a_parole(754.2) == "12 min 34 s"
    assert lavoro.tempo_a_parole(3599.4) == "59 min 59 s"
    assert lavoro.tempo_a_parole(3600) == "1 h 0 min"
    assert lavoro.tempo_a_parole(7385) == "2 h 3 min"


def _sentiti(monkeypatch) -> list:
    visti: list = []
    monkeypatch.setattr(registro, "evento",
                        lambda nome, **campi: visti.append((nome, campi)))
    return visti


def test_la_misura_di_lucidflux_si_dice_e_si_scrive_nel_registro(monkeypatch):
    eventi = _sentiti(monkeypatch)
    for senza in ({}, {"secondi": 754.2}, {"dove_stanno": MISURA["dove_stanno"]},
                  {"secondi": "754", "dove_stanno": MISURA["dove_stanno"]},
                  {"secondi": 754.2, "dove_stanno": [1, 2, 3]}):
        assert lavoro.misura_di_lucidflux(senza) == ""
    assert eventi == []
    assert lavoro.misura_di_lucidflux(MISURA) == DETTO
    assert eventi == [("miglioria.lucidflux_misura",
                       {"secondi": 754.2, "scheda": 7.1, "ram": 9.0, "disco": 6.2})]
    tutto_dentro = {"secondi": 61, "dove_stanno": {"scheda": 20.0, "ram": 3.5, "disco": 0.0}}
    assert lavoro.misura_di_lucidflux(tutto_dentro) == " (LucidFlux ci ha messo 1 min 1 s)"
    assert lavoro.misura_di_lucidflux({"secondi": 5, "dove_stanno": {}}) == (
        " (LucidFlux ci ha messo 5 s)")
    assert eventi[1:] == [
        ("miglioria.lucidflux_misura", {"secondi": 61.0, "scheda": 20.0, "ram": 3.5,
                                        "disco": 0.0}),
        ("miglioria.lucidflux_misura", {"secondi": 5.0, "scheda": 0.0, "ram": 0.0,
                                        "disco": 0.0})]
    assert all(type(valore) is float for _nome, campi in eventi for valore in campi.values())


class _Motore:

    nome = "di_prova"
    versione = "1"

    def __init__(self, dove_stanno=None) -> None:
        if dove_stanno is not None:
            self.dove_stanno = dove_stanno
        self.spento = False

    def foto(self, immagine, larghezza, altezza):
        return Image.new("RGB", (larghezza, altezza), (10, 20, 30))

    def spegni(self):
        self.spento = True


def _catena(monkeypatch, tmp_path, motore) -> tuple[dict, list]:
    originale = tmp_path / "a.jpg"
    _jpeg(originale, (640, 480), "2016:02:03 04:05:06")
    monkeypatch.setattr(motori, "apri", lambda genere, nome, **_: motore)
    monkeypatch.setattr(catena, "time", SimpleNamespace(
        monotonic=iter([100.0, 854.24]).__next__))
    riposi: list = []
    freno = SimpleNamespace(riposa=riposi.append)
    fatto = catena.foto({"originale": str(originale), "uscita": str(tmp_path / "b.jpg"),
                         "motori": {"foto": "di_prova"}}, freno=freno)
    assert motore.spento
    return fatto, riposi


def test_la_catena_dice_quanto_ci_ha_messo_e_dove_stavano_i_pesi(monkeypatch, tmp_path):
    stanno = {"scheda": 7.1, "ram": 9.0, "disco": 6.2}
    motore = _Motore(stanno)
    fatto, riposi = _catena(monkeypatch, tmp_path, motore)
    assert fatto["secondi"] == 754.2 and fatto["dove_stanno"] == stanno
    assert fatto["dove_stanno"] is not motore.dove_stanno
    assert fatto["motori"] == [{"nome": "di_prova", "versione": "1"}]
    assert riposi == [pytest.approx(754.24)]
    fatto, _riposi = _catena(monkeypatch, tmp_path, _Motore())
    assert fatto["secondi"] == 754.2 and "dove_stanno" not in fatto
    fatto, _riposi = _catena(monkeypatch, tmp_path, _Motore({}))
    assert "dove_stanno" not in fatto


def _con_la_misura(seedvr2: dict | None = None):
    def lancia(lavoro_da_fare, al_passo, ricorda):
        lucid = lavoro_da_fare["motori"]["foto"] == motori.LUCIDFLUX
        nome = motori.LUCIDFLUX if lucid else motori.SEEDVR2
        Path(lavoro_da_fare["uscita"]).write_bytes(f"versione di {nome}".encode())
        misura = MISURA if lucid else (seedvr2 or {})
        return {"fatto": {"larghezza": 1663, "altezza": 1247, **misura,
                          "motori": [{"nome": nome, "versione": "x"}]}}

    return lancia


def _gira(archivio, lancia, pronti: bool) -> lavoro.Miglioratore:
    from prove.test_miglioria import SCELTI

    miglioratore = lavoro.Miglioratore(archivio, lancia=lancia, motori_scelti=SCELTI,
                                       sfidanti_pronti=lambda: pronti)
    assert miglioratore.parti()
    assert miglioratore.lavoro.aspetta_che_finisca(60)
    assert not miglioratore.lavoro.guasto, miglioratore.lavoro.guasto
    return miglioratore


@CON_AV
def test_in_sfida_la_riga_dice_quanto_ci_ha_messo_lucidflux(importato, monkeypatch):
    eventi = _sentiti(monkeypatch)
    _metti(importato, "piccola.jpg")
    altra = {"secondi": 9.0, "dove_stanno": {"scheda": 1.0, "ram": 0.0, "disco": 4.0}}
    miglioratore = _gira(importato, _con_la_misura(altra), pronti=True)
    assert f"pronto da votare: «piccola.jpg»{DETTO}" in miglioratore.lavoro.righe
    misure = [campi for nome, campi in eventi if nome == "miglioria.lucidflux_misura"]
    assert misure == [{"secondi": 754.2, "scheda": 7.1, "ram": 9.0, "disco": 6.2}]


@CON_AV
def test_la_ripresa_e_il_lavoro_normale_dicono_la_misura_solo_di_lucidflux(importato):
    _metti(importato, "piccola.jpg")
    miglioratore = _gira(importato, _con_la_misura(), pronti=False)
    assert "pronto da rivedere: «piccola.jpg»" in miglioratore.lavoro.righe
    [riga] = _riga(importato, coda.DA_RIVEDERE)
    assert riga["in_revisione"]
    miglioratore = _gira(importato, _con_la_misura(), pronti=True)
    assert f"pronto da votare: «piccola.jpg»{DETTO}" in miglioratore.lavoro.righe


@CON_AV
def test_il_lavoro_normale_con_la_misura_la_dice(importato):
    _metti(importato, "piccola.jpg")
    miglioratore = _gira(importato, _con_la_misura(MISURA), pronti=False)
    detto = " (SeedVR2: scheda 7,1 GB · RAM 9 GB · disco 6,2 GB)"
    assert f"pronto da rivedere: «piccola.jpg»{detto}" in miglioratore.lavoro.righe
