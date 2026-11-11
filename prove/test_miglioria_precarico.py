from __future__ import annotations

import sys
import threading
import types
from types import SimpleNamespace

import numpy as np
import pytest

from officina.miglioria import catena, motori, precarico, seedvr2_blocchi as blocchi, veloce

G = blocchi.GIGA
MARGINE = blocchi.MARGINE_RAM


class _Flusso:

    def __init__(self, nome: str) -> None:
        self.nome = nome
        self.aspettati: list = []
        self.dopo: list = []

    def wait_event(self, evento) -> None:
        self.aspettati.append(evento)

    def wait_stream(self, altro) -> None:
        self.dopo.append(altro)


class _Evento:

    def __init__(self) -> None:
        self.flusso = None
        self.atteso = 0

    def record(self, flusso) -> None:
        self.flusso = flusso

    def synchronize(self) -> None:
        self.atteso += 1


class _Tensore:

    def __init__(self, numeri, dispositivo: str = "cpu", fissato: bool = False,
                 flusso=None) -> None:
        self.numeri = numeri
        self.device = SimpleNamespace(type=dispositivo.split(":")[0])
        self.dove = dispositivo
        self.fissato = fissato
        self.flusso = flusso
        self.segnati: list = []

    @property
    def dtype(self):
        return self.numeri.dtype

    @property
    def shape(self):
        return self.numeri.shape

    def numel(self) -> int:
        return int(self.numeri.size)

    def element_size(self) -> int:
        return int(self.numeri.itemsize)

    def is_pinned(self) -> bool:
        return self.fissato

    def is_contiguous(self) -> bool:
        return bool(self.numeri.flags["C_CONTIGUOUS"])

    def to(self, dispositivo, non_blocking=False):
        assert non_blocking is True
        return _Tensore(self.numeri.copy(), str(dispositivo), flusso=_torcia.attuale())

    def record_stream(self, flusso) -> None:
        self.segnati.append(flusso)

    def __getitem__(self, fetta):
        return _Tensore(self.numeri[fetta], self.dove, self.fissato)

    def view(self, come):
        if isinstance(come, tuple):
            return _Tensore(self.numeri.reshape(come), self.dove, self.fissato)
        return _Tensore(self.numeri.view(come), self.dove, self.fissato)

    def copy_(self, altro) -> None:
        self.numeri[...] = altro.numeri


class _Torcia:

    def __init__(self) -> None:
        self.principale = _Flusso("principale")
        self.laterali: list = []
        self._qui = threading.local()
        self.appoggi: list = []
        self.uint8 = np.uint8
        self.cuda = types.SimpleNamespace(
            current_stream=lambda _dispositivo=None: self.attuale(),
            Stream=self._nuovo, Event=_Evento, stream=self._dentro)

    def _nuovo(self, device=None):
        flusso = _Flusso("laterale")
        self.laterali.append(flusso)
        return flusso

    def attuale(self):
        return getattr(self._qui, "flusso", None) or self.principale

    def _dentro(self, flusso):
        torcia = self

        class Dentro:
            def __enter__(self):
                torcia._qui.flusso = flusso

            def __exit__(self, *_):
                torcia._qui.flusso = None
        return Dentro()

    def empty(self, quanti, dtype=None, pin_memory=False):
        self.appoggi.append(quanti)
        return _Tensore(np.zeros(quanti, dtype=np.uint8), "cpu", pin_memory)


_torcia = _Torcia()


@pytest.fixture
def torcia(monkeypatch):
    global _torcia
    _torcia = _Torcia()
    monkeypatch.setitem(sys.modules, "torch", _torcia)
    return _torcia


class _Parte:

    def __init__(self, numeri, fissato: bool) -> None:
        self._in_ram = _Tensore(numeri, "cpu", fissato)
        self.data = self._in_ram


class _Blocco:

    def __init__(self, seme: int, fissato: bool = True) -> None:
        caso = np.random.default_rng(seme)
        self.parti = [_Parte(caso.standard_normal((3, 5)).astype(np.float16), fissato),
                      _Parte(caso.integers(0, 9, 7).astype(np.int64), fissato)]


def _parti(blocco) -> list:
    return list(blocco.parti)


def _uguali(blocco) -> bool:
    return all(parte.data.dove == "cuda:0"
               and np.array_equal(parte.data.numeri, parte._in_ram.numeri)
               and parte.data.dtype == parte._in_ram.dtype
               for parte in blocco.parti)


def _acceso() -> precarico.Precarico:
    fatto = precarico.Precarico()
    fatto.accendi(True)
    return fatto


def test_il_blocco_dopo_arriva_prima_sul_flusso_di_lato_e_identico(torcia):
    tutti = [_Blocco(numero) for numero in range(3)]
    pre = _acceso()
    pre.entra(tutti, 0, "cuda:0", _parti)
    assert _uguali(tutti[0]) and tutti[0].parti[0].data.flusso is torcia.principale
    assert set(pre._attesi) == {1}
    pre.entra(tutti, 1, "cuda:0", _parti)
    assert _uguali(tutti[1]) and pre.usati == 1
    assert tutti[1].parti[0].data.flusso is torcia.laterali[0]
    assert torcia.principale.aspettati and all(
        parte.data.segnati == [torcia.principale] for parte in tutti[1].parti)
    pre.entra(tutti, 2, "cuda:0", _parti)
    assert _uguali(tutti[2]) and pre.usati == 2 and pre._attesi == {}
    assert torcia.laterali[0].dopo == [torcia.principale, torcia.principale]


def test_dal_disco_passa_per_la_ram_fissata_in_un_filo_a_parte(torcia):
    tutti = [_Blocco(numero, fissato=False) for numero in range(3)]
    pre = _acceso()
    assert pre.fai_appoggio(4096)
    pre.entra(tutti, 0, "cuda:0", _parti)
    assert pre._attesi[1][0] == "fondo"
    pre.entra(tutti, 1, "cuda:0", _parti)
    pre.entra(tutti, 2, "cuda:0", _parti)
    assert all(_uguali(blocco) for blocco in tutti) and pre.usati == 2
    pre.lascia()
    assert pre._fondo is None and not pre.ha_appoggio()


def test_dal_disco_senza_ram_fissata_si_carica_come_prima(torcia):
    tutti = [_Blocco(numero, fissato=False) for numero in range(2)]
    pre = _acceso()
    pre.entra(tutti, 0, "cuda:0", _parti)
    pre.entra(tutti, 1, "cuda:0", _parti)
    assert all(_uguali(blocco) for blocco in tutti) and pre.usati == 0


def test_un_appoggio_troppo_piccolo_non_si_usa(torcia):
    tutti = [_Blocco(numero, fissato=False) for numero in range(2)]
    pre = _acceso()
    pre.fai_appoggio(1)
    pre._appoggio = pre._appoggio[:16]
    pre.entra(tutti, 0, "cuda:0", _parti)
    assert pre._attesi == {}
    pre.entra(tutti, 1, "cuda:0", _parti)
    assert _uguali(tutti[1]) and pre.usati == 0


def test_se_entra_un_altro_blocco_quello_pronto_si_butta(torcia):
    tutti = [_Blocco(numero) for numero in range(3)]
    pre = _acceso()
    pre.entra(tutti, 0, "cuda:0", _parti)
    pre.entra(tutti, 2, "cuda:0", _parti)
    assert _uguali(tutti[2]) and pre.usati == 0 and pre._attesi == {}


def test_se_il_precarico_si_rompe_si_toglie_e_si_va_avanti_uguale(torcia, monkeypatch):
    tutti = [_Blocco(numero) for numero in range(3)]
    pre = _acceso()

    def rotto(*_):
        raise RuntimeError("guasto")

    monkeypatch.setattr(pre, "_lancia", rotto)
    pre.entra(tutti, 0, "cuda:0", _parti)
    assert pre.tolto == "RuntimeError" and not pre.attivo("cuda:0")
    assert _uguali(tutti[0])


def test_un_errore_nel_filo_toglie_il_precarico_e_il_blocco_si_carica_lo_stesso(torcia,
                                                                                monkeypatch):
    tutti = [_Blocco(numero, fissato=False) for numero in range(2)]
    pre = _acceso()
    pre.fai_appoggio(4096)

    def rotto(*_):
        raise OSError("disco")

    monkeypatch.setattr(pre, "_dal_disco", rotto)
    pre.entra(tutti, 0, "cuda:0", _parti)
    pre.entra(tutti, 1, "cuda:0", _parti)
    assert pre.tolto == "OSError" and _uguali(tutti[1]) and pre.usati == 0


def test_acceso_solo_sulla_scheda_e_se_non_e_stato_tolto():
    pre = precarico.Precarico()
    assert not pre.attivo("cuda:0")
    pre.accendi(True)
    assert pre.attivo("cuda:0") and pre.attivo(SimpleNamespace(type="cuda"))
    assert not pre.attivo("cpu")
    assert pre.togli("memoria") and not pre.togli("memoria")
    pre.accendi(True)
    assert pre.tolto == "memoria"
    pre.accendi(False)
    assert pre.tolto is None and not pre.togli("memoria")
    assert pre.riassunto() == {"usati": 0}


def test_l_appoggio_e_allineato_e_ha_un_po_di_spazio_in_piu(torcia):
    pre = _acceso()
    assert pre.fai_appoggio(1000)
    assert torcia.appoggi == [1024 + precarico.ALLINEA * 64]
    assert pre.fai_appoggio(10) and len(torcia.appoggi) == 1


class _Dato:

    def __init__(self, byte: int) -> None:
        self.byte = byte

    def numel(self) -> int:
        return self.byte // 2

    def element_size(self) -> int:
        return 2

    def pin_memory(self):
        return _Dato(self.byte)

    def clone(self):
        return _Dato(self.byte)


class _ParteFinta:

    def __init__(self, byte: int) -> None:
        self.data = _Dato(byte)

    def numel(self) -> int:
        return self.data.numel()

    def element_size(self) -> int:
        return 2


class _BloccoFinto:

    def __init__(self, byte: int) -> None:
        self.parti = [_ParteFinta(byte)]
        self.spostato = None

    def parameters(self):
        return iter(self.parti)

    def buffers(self):
        return iter([])

    def register_forward_pre_hook(self, _gancio):
        return SimpleNamespace(remove=lambda: None)

    register_forward_hook = register_forward_pre_hook

    def to(self, dove):
        self.spostato = dove


def _modello(*pesi: int, quanti: int | None = None):
    fatti = [_BloccoFinto(peso) for peso in pesi]
    return SimpleNamespace(blocks=fatti, main_device="cuda:0",
                           blocks_to_swap=(len(fatti) if quanti is None else quanti) - 1,
                           parameters=lambda: iter([p for b in fatti for p in b.parti]),
                           buffers=lambda: iter([]))


def _con_appoggio(monkeypatch) -> list:
    fatti = []

    def fai(self, quanti):
        fatti.append(quanti)
        self._appoggio = object()
        return True

    monkeypatch.setattr(precarico.Precarico, "fai_appoggio", fai)
    return fatti


def test_col_precarico_un_blocco_in_meno_nella_ram_per_l_appoggio(monkeypatch):
    appoggi = _con_appoggio(monkeypatch)
    spento = blocchi.Blocchi(disco=True)
    spento.prendi(_modello(G, G, G, G), MARGINE + 3 * G)
    assert spento.in_ram == [True, True, True, False] and appoggi == []
    acceso = blocchi.Blocchi(disco=True)
    acceso.precarico.accendi(True)
    acceso.prendi(_modello(G, G, G, G), MARGINE + 3 * G)
    assert acceso.in_ram == [True, True, False, False] and appoggi == [G]


def test_col_precarico_se_sta_tutto_nella_ram_non_serve_appoggio(monkeypatch):
    appoggi = _con_appoggio(monkeypatch)
    acceso = blocchi.Blocchi(disco=True)
    acceso.precarico.accendi(True)
    acceso.prendi(_modello(G, G), MARGINE + 2 * G)
    assert acceso.in_ram == [True, True] and appoggi == []


def test_col_precarico_e_ram_per_un_solo_blocco_si_fa_senza_appoggio(monkeypatch):
    appoggi = _con_appoggio(monkeypatch)
    acceso = blocchi.Blocchi(disco=True)
    acceso.precarico.accendi(True)
    acceso.prendi(_modello(G, G), MARGINE + G)
    assert acceso.in_ram == [True, False] and appoggi == []


def test_se_la_ram_scende_col_precarico_un_blocco_in_piu_va_sul_disco(monkeypatch):
    appoggi = _con_appoggio(monkeypatch)
    acceso = blocchi.Blocchi(disco=True)
    acceso.precarico.accendi(True)
    acceso.prendi(_modello(G, G, G), MARGINE + 3 * G)
    acceso.girato = True
    assert acceso.in_ram == [True, True, True] and appoggi == []
    assert acceso.ribilancia(MARGINE - G)
    assert acceso.in_ram == [True, False, False] and appoggi == [G]


def test_se_la_ram_si_libera_col_precarico_si_tiene_posto_per_l_appoggio(monkeypatch):
    appoggi = _con_appoggio(monkeypatch)
    acceso = blocchi.Blocchi(disco=True)
    acceso.prendi(_modello(G, G, G, G), MARGINE + G)
    acceso.girato = True
    acceso.precarico.accendi(True)
    assert acceso.in_ram == [True, False, False, False]
    acceso.ribilancia(MARGINE + 2 * G)
    assert acceso.in_ram == [True, True, False, False] and appoggi == [G]


def test_se_meno_blocchi_vanno_spostati_quelli_lasciati_tornano_sulla_scheda():
    modello = _modello(G, G, G, quanti=3)
    tenuti = blocchi.Blocchi()
    tenuti.prendi(modello, None)
    modello.blocks_to_swap = 1
    tenuti.prendi(modello, None)
    assert [b.spostato for b in modello.blocks] == [None, None, "cuda:0"]
    altro = _modello(G)
    tenuti.prendi(altro, None)
    assert modello.blocks[0].spostato is None


def test_seedvr2_col_precarico_sposta_un_blocco_in_piu():
    from officina.miglioria import seedvr2

    assert seedvr2.impostazioni()["blocks_to_swap"] == seedvr2.BLOCCHI_NORMALI
    assert seedvr2.impostazioni(precarico=True)["blocks_to_swap"] == \
        seedvr2.BLOCCHI_NORMALI + 1
    assert seedvr2.impostazioni(True, True)["blocks_to_swap"] == seedvr2.BLOCCHI_STRETTI + 1


def _seedvr2(monkeypatch, fallisce):
    from officina.miglioria import seedvr2

    motore = seedvr2.SeedVR2.__new__(seedvr2.SeedVR2)
    motore.stretto = False
    motore.precarico = True
    motore._blocchi = blocchi.Blocchi()
    motore._ctx = None
    motore._pronto = False
    motore._s = {"memoria": SimpleNamespace(clear_memory=lambda **_: None), "debug": None}
    prove = []

    def una_volta(quadri, larghezza, altezza):
        prove.append((motore.stretto, motore._blocchi.precarico.attivo("cuda")))
        if fallisce(motore):
            raise RuntimeError("CUDA out of memory")
        return quadri

    monkeypatch.setattr(motore, "_una_volta", una_volta)
    return motore, prove


def test_seedvr2_se_non_ci_sta_prima_stretto_poi_senza_precarico(monkeypatch):
    motore, prove = _seedvr2(monkeypatch, lambda m: m._blocchi.precarico.attivo("cuda"))
    motore._ingrandisci(np.zeros((1, 2, 2, 3), np.uint8), 4, 4)
    assert prove == [(False, True), (True, True), (True, False)]
    assert motore._blocchi.precarico.tolto == "memoria"
    motore._ingrandisci(np.zeros((1, 2, 2, 3), np.uint8), 4, 4)
    assert prove[-1] == (True, False)


def test_seedvr2_senza_precarico_fa_come_prima(monkeypatch):
    motore, prove = _seedvr2(monkeypatch, lambda m: True)
    motore.precarico = False
    with pytest.raises(RuntimeError):
        motore._ingrandisci(np.zeros((1, 2, 2, 3), np.uint8), 4, 4)
    assert prove == [(False, False), (True, False)]


def test_ldf_se_non_ci_sta_prima_toglie_il_precarico_poi_le_fette():
    from officina.miglioria import ldfvfi

    motore = ldfvfi.LdfVFI.__new__(ldfvfi.LdfVFI)
    motore._blocchi = blocchi.Blocchi()
    motore._blocchi.precarico.accendi(True)
    dimezzate = []
    motore.fette = SimpleNamespace(dimezza=lambda pezzi: dimezzate.append(pezzi) or True,
                                   esci=lambda: False)
    motore.foglio = None
    motore._dit = SimpleNamespace(config=SimpleNamespace(patch_size=(1, 2, 2)))
    chiamate = []

    def riprova(fai, dimezza):
        chiamate.append(dimezza())
        chiamate.append(dimezza())
        return None

    motore._riprova = riprova
    finto = types.ModuleType("torch")
    finto.long = "long"
    finto.cat = lambda pezzi, dim: SimpleNamespace(shape=(1, 1, 1, 1, 4, 2, 8, 8))
    vecchio = sys.modules.get("torch")
    sys.modules["torch"] = finto
    try:
        motore.prevedi(SimpleNamespace(), SimpleNamespace(mul=lambda _: SimpleNamespace(
            to=lambda dtype: 0)), None, None)
    finally:
        if vecchio is None:
            sys.modules.pop("torch", None)
        else:
            sys.modules["torch"] = vecchio
    assert chiamate == [True, True] and len(dimezzate) == 1
    assert motore._blocchi.precarico.tolto == "memoria"


def test_il_lavoro_dice_ai_motori_se_precaricare():
    class Motore:
        precarico = None

    nudo = Motore()
    catena.precarica(nudo, {"veloce": [veloce.PRECARICO]})
    assert nudo.precarico is True
    acceso = motori.Acceso(Motore())
    catena.precarica(acceso, {"veloce": [veloce.SCRITTURA]})
    assert acceso.motore.precarico is False and "precarico" not in vars(acceso)
    catena.precarica(SimpleNamespace(), {})
    assert veloce.PRECARICO in veloce.IDEE
