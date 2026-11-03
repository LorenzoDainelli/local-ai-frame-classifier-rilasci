from __future__ import annotations

import sys
from types import SimpleNamespace

import numpy as np
import pytest

from officina.miglioria import scaricamento, seedvr2, seedvr2_blocchi as blocchi
from prove.test_miglioria_seedvr2 import finto

__all__ = ["finto"]

G = blocchi.GIGA
MARGINE = blocchi.MARGINE_RAM


class _Dato:

    def __init__(self, byte: int, dove: str = "file", fissato: bool = False) -> None:
        self.byte = byte
        self.dove = dove
        self.fissato = fissato

    def numel(self) -> int:
        return self.byte // 2

    def element_size(self) -> int:
        return 2

    def pin_memory(self):
        return _Dato(self.byte, "ram", True)

    def clone(self):
        return _Dato(self.byte, "ram")

    def to(self, dispositivo, non_blocking=False):
        assert non_blocking is True
        return _Dato(self.byte, dispositivo)


class _Parte:

    def __init__(self, byte: int) -> None:
        self.data = _Dato(byte)

    def numel(self) -> int:
        return self.data.numel()

    def element_size(self) -> int:
        return self.data.element_size()


class _Blocco:

    def __init__(self, *byte: int, buffer: int = 0) -> None:
        self.parti = [_Parte(b) for b in byte]
        self.memorie = [_Parte(buffer)] if buffer else []
        self.prima: list = []
        self.dopo: list = []

    def parameters(self):
        return iter(self.parti)

    def buffers(self):
        return iter(self.memorie)

    def _aggancia(self, dove: list, gancio):
        dove.append(gancio)
        return SimpleNamespace(remove=lambda: dove.remove(gancio))

    def register_forward_pre_hook(self, gancio):
        return self._aggancia(self.prima, gancio)

    def register_forward_hook(self, gancio):
        return self._aggancia(self.dopo, gancio)

    def avanti(self) -> list:
        for gancio in self.prima:
            gancio(self, ())
        visti = [parte.data.dove for parte in self.parti]
        for gancio in self.dopo:
            gancio(self, (), None)
        return visti


class _Modello:

    def __init__(self, blocchi_: list, quanti: int, altro: int = G) -> None:
        self.blocks = blocchi_
        self.blocks_to_swap = quanti - 1
        self.main_device = "cuda:0"
        self.altro = _Blocco(altro)

    def parameters(self):
        for blocco in [*self.blocks, self.altro]:
            yield from blocco.parameters()

    def buffers(self):
        for blocco in [*self.blocks, self.altro]:
            yield from blocco.buffers()


def _dove(blocco) -> list:
    return [(parte.data.dove, parte.data.fissato) for parte in blocco.parti]


def test_quanti_in_ram_quando_la_ram_basta():
    pesi = [2 * G, G, G]
    assert blocchi.quanti_in_ram(pesi, None, 5 * G, False) == 3
    assert blocchi.quanti_in_ram(pesi, MARGINE + 5 * G + 4 * G, 5 * G, False) == 3
    assert blocchi.quanti_in_ram(pesi, MARGINE + 4 * G, 0, True) == 3
    assert blocchi.quanti_in_ram([], MARGINE, 0, False) == 0


def test_senza_il_disco_la_ram_poca_dice_quanta_ne_serve():
    with pytest.raises(blocchi.RamPoca) as preso:
        blocchi.quanti_in_ram([2 * G, G, G], MARGINE + 5 * G + 4 * G - 1, 5 * G, False)
    errore = preso.value
    assert type(errore) is blocchi.RamPoca and errore.codice == "ram_poca"
    assert str(errore) == "Per SeedVR2 servono almeno 12 GB di RAM libera e ce ne sono 11."
    assert errore.dati() == {"serve": MARGINE + 9 * G, "libera": MARGINE + 9 * G - 1}
    assert errore.senza_nomi is True


def test_col_disco_nella_ram_va_quel_che_ci_sta():
    pesi = [2 * G, G, G]
    assert blocchi.quanti_in_ram(pesi, MARGINE + G + 3 * G, G, True) == 2
    assert blocchi.quanti_in_ram(pesi, MARGINE + G + 3 * G - 1, G, True) == 1
    assert blocchi.quanti_in_ram(pesi, MARGINE + G + 2 * G, G, True) == 1


def test_se_non_ci_sta_neanche_un_blocco_nemmeno_il_disco_basta():
    with pytest.raises(blocchi.DiscoNonBasta) as preso:
        blocchi.quanti_in_ram([G, 2 * G, G], MARGINE + G + 2 * G - 1, G, True)
    errore = preso.value
    assert errore.codice == "ram_poca_anche_col_disco"
    assert errore.dati() == {"serve": MARGINE + 3 * G, "libera": MARGINE + 3 * G - 1}
    assert str(errore) == "Per SeedVR2 servono almeno 6 GB di RAM libera e ce ne sono 5."


def test_ci_stanno_finche_non_si_supera_il_posto():
    assert blocchi.quanti_ne_stanno([G, G, G], 2 * G) == 2
    assert blocchi.quanti_ne_stanno([G, G, G], 2 * G - 1) == 1
    assert blocchi.quanti_ne_stanno([G, G, G], 3 * G) == 3
    assert blocchi.quanti_ne_stanno([], 0) == 0


def test_il_peso_conta_parametri_e_memorie():
    assert blocchi.peso(_Blocco(G, G // 2, buffer=8)) == G + G // 2 + 8


def test_la_ram_libera_la_dice_psutil_e_senza_non_si_sa(monkeypatch):
    monkeypatch.setitem(sys.modules, "psutil", SimpleNamespace(
        virtual_memory=lambda: SimpleNamespace(available=7.0 * G)))
    libera = blocchi.ram_libera()
    assert libera == 7 * G and type(libera) is int
    monkeypatch.setitem(sys.modules, "psutil", None)
    assert blocchi.ram_libera() is None


def test_i_giga_hanno_un_decimale():
    assert blocchi.in_giga(3 * G // 2) == 1.5
    assert blocchi.in_giga(int(G * 6.249)) == 6.2


def test_non_avvolgere_non_fa_niente():
    blocco = _Blocco(G)
    assert blocchi.non_avvolgere(blocco, 0, None, debug=None) is None
    assert _dove(blocco) == [("file", False)]


def _modello(*pesi: int, quanti: int | None = None, altro: int = G) -> _Modello:
    quanti = len(pesi) if quanti is None else quanti
    return _Modello([_Blocco(p) for p in pesi], quanti, altro)


def test_i_primi_vanno_nella_ram_fissata_e_gli_altri_restano_sul_disco():
    modello = _modello(G, G, G, G, quanti=3)
    tenuti = blocchi.Blocchi(disco=True)
    tenuti.prendi(modello, MARGINE + 2 * G + 2 * G)
    assert [_dove(b) for b in modello.blocks] == [
        [("ram", True)], [("ram", True)], [("file", False)], [("file", False)]]
    assert tenuti.fuori == modello.blocks[:3] and tenuti.in_ram == [True, True, False]
    assert tenuti.pesi == [G, G, G] and tenuti.fisso == 2 * G
    assert tenuti.dispositivo == "cuda:0" and not tenuti.girato
    assert tenuti.dove_stanno() == {"scheda": 2.0, "ram": 2.0, "disco": 1.0}
    assert not modello.blocks[3].prima and all(b._officina for b in modello.blocks[:3])


def test_un_blocco_va_sulla_scheda_solo_mentre_lavora():
    modello = _modello(G, G, quanti=2)
    tenuti = blocchi.Blocchi(disco=True)
    tenuti.prendi(modello, MARGINE + 2 * G)
    assert modello.blocks[0].avanti() == ["cuda:0"]
    assert modello.blocks[1].avanti() == ["cuda:0"]
    assert [_dove(b) for b in modello.blocks] == [[("ram", True)], [("file", False)]]


def test_senza_ram_libera_conosciuta_tutto_va_nella_ram():
    modello = _modello(G, G)
    tenuti = blocchi.Blocchi()
    tenuti.prendi(modello, None)
    assert tenuti.in_ram == [True, True]


def test_senza_il_disco_e_senza_ram_non_si_tocca_niente():
    modello = _modello(G, G)
    tenuti = blocchi.Blocchi()
    with pytest.raises(blocchi.RamPoca):
        tenuti.prendi(modello, MARGINE + G + 2 * G - 1)
    assert tenuti.fuori == [] and not modello.blocks[0].prima
    assert [_dove(b) for b in modello.blocks] == [[("file", False)]] * 2


def test_se_la_ram_non_si_fissa_si_copia_e_basta():
    modello = _modello(G, G)

    def rotta():
        raise RuntimeError("pin")

    modello.blocks[0].parti[0].data.pin_memory = rotta
    tenuti = blocchi.Blocchi()
    tenuti.prendi(modello, None)
    assert [_dove(b) for b in modello.blocks] == [[("ram", False)]] * 2
    assert tenuti.fissa is False


def test_lo_stesso_modello_non_si_riprende_due_volte():
    modello = _modello(G, G)
    tenuti = blocchi.Blocchi()
    tenuti.prendi(modello, None)
    primi = [b.parti[0].data for b in modello.blocks]
    tenuti.prendi(modello, 0)
    assert [b.parti[0].data for b in modello.blocks] == primi
    assert len(modello.blocks[0].prima) == 1


def test_un_modello_nuovo_lascia_andare_quello_vecchio():
    vecchio = _modello(G, G)
    tenuti = blocchi.Blocchi()
    tenuti.prendi(vecchio, None)
    tenuti.girato = True
    nuovo = _modello(G, G, G)
    tenuti.prendi(nuovo, None)
    assert [_dove(b) for b in vecchio.blocks] == [[("file", False)]] * 2
    assert not vecchio.blocks[0].prima and not vecchio.blocks[0].dopo
    assert not hasattr(vecchio.blocks[0], "_officina")
    assert not hasattr(vecchio.blocks[0].parti[0], "_in_ram")
    assert not hasattr(vecchio.blocks[0].parti[0], "_dal_file")
    assert tenuti.fuori == nuovo.blocks and not tenuti.girato


def test_se_cambiano_i_blocchi_da_spostare_si_ripianifica():
    modello = _modello(G, G, G, quanti=2)
    tenuti = blocchi.Blocchi()
    tenuti.prendi(modello, None)
    modello.blocks_to_swap = 2
    tenuti.prendi(modello, None)
    assert tenuti.fuori == modello.blocks and len(modello.blocks[0].prima) == 1


def test_niente_da_spostare_niente_da_dire():
    modello = _modello(G, G, quanti=0)
    tenuti = blocchi.Blocchi()
    tenuti.prendi(modello, 0)
    assert tenuti.fuori == [] and tenuti.dove_stanno() is None
    assert tenuti.ribilancia(100 * G) is False
    modello.blocks_to_swap = -5
    tenuti.prendi(modello, 0)
    assert tenuti.fuori == []


def _disco(libera: int, *pesi: int, altro: int = G):
    modello = _modello(*pesi, altro=altro)
    tenuti = blocchi.Blocchi(disco=True)
    tenuti.prendi(modello, libera)
    return modello, tenuti


def test_se_la_ram_si_libera_i_blocchi_tornano_nella_ram_senza_ricaricare():
    modello, tenuti = _disco(MARGINE + G + G, G, G, G)
    assert tenuti.in_ram == [True, False, False]
    tenuti.girato = True
    assert tenuti.ribilancia(MARGINE + G) is True
    assert tenuti.in_ram == [True, True, False]
    assert _dove(modello.blocks[1]) == [("ram", True)]
    assert tenuti.ribilancia(MARGINE + G - 1) is False
    assert tenuti.ribilancia(MARGINE + 5 * G) is True
    assert tenuti.in_ram == [True, True, True]
    assert tenuti.dove_stanno() == {"scheda": 1.0, "ram": 3.0, "disco": 0.0}


def test_prima_del_primo_giro_la_parte_della_scheda_si_conta_ancora():
    _modello_, tenuti = _disco(MARGINE + G + G, G, G, G)
    assert tenuti.ribilancia(MARGINE + G) is False
    assert tenuti.ribilancia(MARGINE + 2 * G) is True
    assert tenuti.in_ram == [True, True, False]


def test_se_la_ram_scende_sotto_il_margine_i_blocchi_tornano_sul_disco(monkeypatch):
    svuotate = []
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(
        _C=SimpleNamespace(_host_emptyCache=lambda: svuotate.append(True))))
    modello, tenuti = _disco(MARGINE + G + 3 * G, G, G, G)
    tenuti.girato = True
    assert tenuti.ribilancia(MARGINE) is False and not svuotate
    assert tenuti.ribilancia(MARGINE - 1) is True
    assert tenuti.in_ram == [True, True, False] and svuotate == [True]
    assert _dove(modello.blocks[2]) == [("file", False)]
    assert tenuti.ribilancia(MARGINE - G - 1) is True
    assert tenuti.in_ram == [False, False, False]
    assert tenuti.ribilancia(MARGINE - 9 * G) is False
    assert len(svuotate) == 2


def test_senza_sapere_la_ram_non_si_sposta_niente():
    _modello_, tenuti = _disco(MARGINE + G + G, G, G)
    assert tenuti.ribilancia(None) is False and tenuti.in_ram == [True, False]


def test_togliere_svuota_la_ram_fissata_solo_se_c_era(monkeypatch):
    svuotate = []
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(
        _C=SimpleNamespace(_host_emptyCache=lambda: svuotate.append(True))))
    _modello_, tenuti = _disco(MARGINE + G + G, G, G)
    tenuti.togli()
    assert svuotate == [True]
    tenuti.togli()
    _modello_, tenuti = _disco(MARGINE + G + G, G, G)
    tenuti.girato = True
    tenuti.ribilancia(MARGINE - G)
    assert tenuti.in_ram == [False, False] and len(svuotate) == 2
    tenuti.togli()
    assert len(svuotate) == 2


def test_svuotare_la_ram_fissata_non_si_rompe(monkeypatch):
    def rotto():
        raise RuntimeError("no")

    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(
        _C=SimpleNamespace(_host_emptyCache=rotto)))
    _modello_, tenuti = _disco(100 * G, G)
    tenuti.togli()
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace())
    _modello_, tenuti = _disco(100 * G, G)
    tenuti.togli()
    monkeypatch.setitem(sys.modules, "torch", None)
    _modello_, tenuti = _disco(100 * G, G)
    tenuti.togli()


def _motore(finto):
    scaricamento.scarica(finto["modelli"], prendi_testo=finto["prendi_testo"],
                         prendi_peso=finto["prendi_peso"])
    return seedvr2.SeedVR2(cartella_modelli=str(finto["modelli"]))


def _librerie(chiamate: list):
    def originale(runner, config, debug):
        chiamate.append((runner, config, debug))

    configurazione = SimpleNamespace(apply_block_swap_to_dit=originale)
    blockswap = SimpleNamespace(_wrap_block_forward="vero")
    return configurazione, blockswap, originale


def test_seedvr2_mette_i_suoi_blocchi_dopo_quelli_della_libreria(finto, monkeypatch):
    motore = _motore(finto)
    chiamate: list = []
    configurazione, blockswap, originale = _librerie(chiamate)
    motore._aggancia(configurazione, blockswap)
    assert blockswap._wrap_block_forward is blocchi.non_avvolgere
    assert configurazione._officina_originale is originale
    monkeypatch.setattr(blocchi, "ram_libera", lambda: None)
    modello = _modello(G, G)
    runner = SimpleNamespace(dit=SimpleNamespace(dit_model=modello))
    configurazione.apply_block_swap_to_dit(runner, "config", "debug")
    assert chiamate == [(runner, "config", "debug")]
    assert motore._blocchi.fuori == modello.blocks
    assert motore.dove_stanno == {"scheda": 1.0, "ram": 2.0, "disco": 0.0}
    nudo = _modello(G)
    configurazione.apply_block_swap_to_dit(SimpleNamespace(dit=nudo), "c", "d")
    assert motore._blocchi.fuori == nudo.blocks


def test_un_secondo_seedvr2_non_si_aggancia_sopra_il_primo(finto, monkeypatch):
    primo, secondo = _motore(finto), _motore(finto)
    chiamate: list = []
    configurazione, blockswap, originale = _librerie(chiamate)
    primo._aggancia(configurazione, blockswap)
    secondo._aggancia(configurazione, blockswap)
    assert configurazione._officina_originale is originale
    monkeypatch.setattr(blocchi, "ram_libera", lambda: None)
    modello = _modello(G)
    configurazione.apply_block_swap_to_dit(SimpleNamespace(dit=modello), "c", "d")
    assert len(chiamate) == 1
    assert secondo._blocchi.fuori == modello.blocks and primo._blocchi.fuori == []


def test_seedvr2_passa_la_ram_libera_e_il_disco(finto, monkeypatch):
    scaricamento.scarica(finto["modelli"], prendi_testo=finto["prendi_testo"],
                         prendi_peso=finto["prendi_peso"])
    motore = seedvr2.SeedVR2(cartella_modelli=str(finto["modelli"]), disco=True)
    assert motore._blocchi.disco is True
    assert _motore(finto)._blocchi.disco is False
    configurazione, blockswap, _originale = _librerie([])
    motore._aggancia(configurazione, blockswap)
    monkeypatch.setattr(blocchi, "ram_libera", lambda: MARGINE + G + G)
    modello = _modello(G, G)
    configurazione.apply_block_swap_to_dit(SimpleNamespace(dit=modello), "c", "d")
    assert motore._blocchi.in_ram == [True, False]


def test_spegnere_seedvr2_lascia_andare_i_blocchi(finto, monkeypatch):
    motore = _motore(finto)
    monkeypatch.setattr(blocchi, "ram_libera", lambda: None)
    modello = _modello(G)
    motore._blocchi.prendi(modello, None)

    class Memoria:
        @staticmethod
        def clear_memory(**_):
            pass

    motore._s = {"memoria": Memoria, "debug": None}
    motore.spegni()
    assert motore._blocchi.fuori == [] and not modello.blocks[0].prima
    assert motore.dove_stanno is None


def test_quando_riprova_stretto_lascia_andare_i_blocchi(finto, monkeypatch):
    motore = _motore(finto)
    modello = _modello(G)
    motore._blocchi.prendi(modello, None)
    lasciati = []

    class Memoria:
        @staticmethod
        def clear_memory(**_):
            lasciati.append(list(motore._blocchi.fuori))

    motore._s = {"memoria": Memoria, "debug": None}

    def una_volta(quadri, larghezza, altezza):
        if not motore.stretto:
            raise RuntimeError("CUDA out of memory")
        return quadri

    monkeypatch.setattr(motore, "_una_volta", una_volta)
    motore._ingrandisci(np.zeros((1, 2, 2, 3), np.uint8), 4, 4)
    assert lasciati == [[]] and not modello.blocks[0].prima


def test_i_giga_che_servono_si_arrotondano_in_su():
    with pytest.raises(blocchi.RamPoca) as preso:
        blocchi.quanti_in_ram([G // 2], MARGINE, 0, False)
    detto = "Per SeedVR2 servono almeno 4 GB di RAM libera e ce ne sono 3."
    assert str(preso.value) == detto


def test_se_i_segni_sono_spariti_i_blocchi_si_riprendono():
    modello = _modello(G, G)
    tenuti = blocchi.Blocchi(disco=True)
    tenuti.prendi(modello, None)
    del modello.blocks[0]._officina
    tenuti.prendi(modello, MARGINE + G + G)
    assert tenuti.in_ram == [True, False] and len(modello.blocks[0].prima) == 1


def test_la_parte_della_scheda_non_va_sotto_zero():
    modello = _modello(G, G)
    modello.parameters = lambda: iter(())
    tenuti = blocchi.Blocchi()
    tenuti.prendi(modello, None)
    assert tenuti.fisso == 0


def test_dopo_aver_tolto_si_riparte_da_zero():
    modello = _modello(G, G)
    tenuti = blocchi.Blocchi()
    tenuti.prendi(modello, None)
    tenuti.girato = True
    assert tenuti.fisso == G
    tenuti.togli()
    assert tenuti.fisso == 0 and tenuti.girato is False


class _Tensore:

    def __init__(self, dati) -> None:
        self.dati = dati

    def to(self, *_argomenti):
        return self

    def div_(self, _quanto):
        return self

    def detach(self):
        return self

    def __getitem__(self, chiave):
        return _Tensore(self.dati[chiave])

    def clamp_(self, *_argomenti):
        return self

    def mul_(self, _quanto):
        return self

    def round_(self):
        return self

    def numpy(self):
        return self.dati


class _BlocchiSpia:

    def __init__(self, stanno) -> None:
        self.stanno = stanno
        self.visti: list = []
        self.girato = False

    def ribilancia(self, libera) -> bool:
        self.visti.append(("ribilancia", libera, self.girato))
        return False

    def dove_stanno(self):
        self.visti.append(("dove", self.girato))
        return self.stanno


def _gira_una_volta(finto, monkeypatch, stanno):
    motore = _motore(finto)
    spia = _BlocchiSpia(stanno)
    motore._blocchi = spia
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(
        cuda=SimpleNamespace(is_available=lambda: False), from_numpy=_Tensore,
        float16="f16", float32="f32", uint8="u8"))
    monkeypatch.setattr(blocchi, "ram_libera", lambda: 7 * G)

    def prepara():
        spia.visti.append(("prepara",))
        return "esecutore"

    monkeypatch.setattr(motore, "_prepara", prepara)

    def fase(*_argomenti, ctx, **_chiavi):
        return ctx

    def codifica(*_argomenti, images, **_chiavi):
        return {"final_video": images}

    motore._s = {
        "utili": SimpleNamespace(compute_generation_info=lambda **k: (k["images"], None)),
        "fasi": SimpleNamespace(encode_all_batches=codifica, upscale_all_batches=fase,
                                decode_all_batches=fase, postprocess_all_batches=fase),
        "debug": None}
    uscita = motore._una_volta(np.zeros((1, 2, 2, 4), np.uint8), 4, 4)
    assert uscita.shape == (1, 2, 2, 3)
    return motore, spia


def test_prima_di_ogni_giro_i_blocchi_si_ribilanciano_e_dopo_si_dice_dove_stanno(
        finto, monkeypatch):
    motore, spia = _gira_una_volta(finto, monkeypatch,
                                   {"scheda": 4.5, "ram": 8.0, "disco": 4.0})
    assert spia.visti == [("ribilancia", 7 * G, False), ("prepara",), ("dove", False)]
    assert spia.girato is True
    tempi = motore.tempi[-1]
    assert (tempi["scheda_gb"], tempi["ram_gb"], tempi["disco_gb"]) == (4.5, 8.0, 4.0)


def test_senza_blocchi_fuori_i_tempi_non_hanno_i_giga(finto, monkeypatch):
    motore, spia = _gira_una_volta(finto, monkeypatch, None)
    assert not [chiave for chiave in motore.tempi[-1] if chiave.endswith("_gb")]
    assert spia.girato is True


def test_caricare_seedvr2_aggancia_i_blocchi_alla_libreria(finto, monkeypatch):
    import importlib

    motore = _motore(finto)
    configurazione, blockswap, originale = _librerie([])
    finti = {"src.core.model_configuration": configurazione,
             "src.optimization.blockswap": blockswap,
             "src.utils.debug": SimpleNamespace(Debug=lambda enabled: ("debug", enabled))}
    monkeypatch.setattr(scaricamento, "motivo_del_codice_diverso",
                        lambda *a, **k: None)
    monkeypatch.setattr(scaricamento, "metti_il_codice_in_fondo", lambda casa: None)
    monkeypatch.setattr(scaricamento, "moduli_fuori_dal_codice", lambda moduli, casa: False)
    monkeypatch.setattr(importlib, "import_module",
                        lambda nome: finti.get(nome, SimpleNamespace(nome=nome)))
    s = motore._carica()
    assert s["debug"] == ("debug", False)
    assert configurazione._officina_originale is originale
    assert configurazione.apply_block_swap_to_dit is not originale
    assert blockswap._wrap_block_forward is blocchi.non_avvolgere
