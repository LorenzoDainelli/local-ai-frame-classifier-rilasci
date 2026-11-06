from __future__ import annotations

import os
import sys
import types

import pytest

from officina.miglioria import (centoventi, fluido, ldf_fette, ldf_foglio, ldfvfi,
                                seedvr2_blocchi)

GIGA = 2 ** 30
DUE = types.SimpleNamespace(itemsize=2, nome="bf16")


class _Tensore:

    def __init__(self, forma, tipo, file=None):
        self.shape = tuple(forma)
        self.dtype = tipo
        self.file = file

    def view(self, forma):
        return _Tensore(forma, self.dtype, self.file)


def _torcia(monkeypatch):
    fatti = []

    def vuoto(forma, dtype):
        fatti.append(("ram", tuple(forma)))
        return _Tensore(forma, dtype)

    def dal_file(nome, shared, size, dtype):
        assert shared is True
        assert os.path.getsize(nome) == size * dtype.itemsize
        fatti.append(("disco", nome))
        return _Tensore((size,), dtype, nome)

    torcia = types.SimpleNamespace(empty=vuoto, from_file=dal_file)
    monkeypatch.setitem(sys.modules, "torch", torcia)
    return fatti


def _spazio(libero):
    return lambda _cartella: types.SimpleNamespace(free=libero)


def _foglio(tmp_path, ram, disco=100 * GIGA):
    return ldf_foglio.Foglio(tmp_path / "appoggio", "LDF-VFI", ram_libera=lambda: ram,
                             spazio=_spazio(disco))


def test_i_byte_del_foglio():
    assert ldf_foglio.byte_di((3, 4, 5), DUE) == 120


def test_con_ram_libera_il_foglio_sta_in_ram(tmp_path, monkeypatch):
    fatti = _torcia(monkeypatch)
    foglio = _foglio(tmp_path, ram=8 * GIGA)
    dato = foglio((2, GIGA), DUE)
    assert dato.shape == (2, GIGA) and foglio.dove == ldf_foglio.RAM
    assert fatti == [("ram", (2, GIGA))]
    assert not (tmp_path / "appoggio").exists()


def test_il_margine_della_ram_conta_anche_la_cache(tmp_path, monkeypatch):
    _torcia(monkeypatch)
    libera = 4 * GIGA + seedvr2_blocchi.MARGINE_RAM
    assert _foglio(tmp_path, ram=libera)((2, GIGA), DUE).file is None
    foglio = _foglio(tmp_path, ram=libera)
    foglio((2, GIGA), DUE, in_piu=1)
    assert foglio.dove == ldf_foglio.DISCO


def test_senza_ram_il_foglio_va_sul_disco_e_poi_si_cancella(tmp_path, monkeypatch):
    fatti = _torcia(monkeypatch)
    foglio = _foglio(tmp_path, ram=GIGA)
    dato = foglio((4, 8), DUE)
    file = tmp_path / "appoggio" / f"foglio-{os.getpid()}.bin"
    assert foglio.dove == ldf_foglio.DISCO and dato.shape == (4, 8)
    assert fatti == [("disco", str(file))] and file.stat().st_size == 64
    foglio.lascia()
    assert not file.exists() and foglio.dato is None and foglio.dove is None


def test_lo_stesso_foglio_si_riusa(tmp_path, monkeypatch):
    fatti = _torcia(monkeypatch)
    foglio = _foglio(tmp_path, ram=GIGA)
    primo = foglio((4, 8), DUE)
    assert foglio((4, 8), DUE) is primo and len(fatti) == 1
    foglio((4, 9), DUE)
    assert len(fatti) == 2 and foglio.byte == 72


def test_senza_spazio_sul_disco_si_ferma_e_dice_quanto_serve(tmp_path, monkeypatch):
    _torcia(monkeypatch)
    foglio = _foglio(tmp_path, ram=GIGA, disco=3 * GIGA)
    with pytest.raises(ldf_foglio.FoglioSenzaPosto) as preso:
        foglio((4, GIGA), DUE)
    errore = preso.value
    assert errore.codice == "spazio_modelli" and errore.senza_nomi
    assert "servono 9 GB liberi e ce ne sono 3" in str(errore)
    assert errore.dati() == {"serve": 9 * GIGA, "libero": 3 * GIGA}
    assert not list((tmp_path / "appoggio").glob("*.bin"))


def test_i_fogli_rimasti_si_puliscono(tmp_path, monkeypatch):
    _torcia(monkeypatch)
    cartella = tmp_path / "appoggio"
    cartella.mkdir()
    (cartella / "foglio-999999.bin").write_bytes(b"0" * 10)
    (cartella / "altro.txt").write_text("resta", encoding="utf-8")
    foglio = _foglio(tmp_path, ram=GIGA)
    foglio((2, 2), DUE)
    assert sorted(f.name for f in cartella.iterdir()) == [
        "altro.txt", f"foglio-{os.getpid()}.bin"]
    foglio.pulisci()
    assert foglio.file.exists()


def test_quanto_e_dove_nel_video(tmp_path, monkeypatch):
    _torcia(monkeypatch)
    foglio = _foglio(tmp_path, ram=None)
    foglio((GIGA, 3), DUE)
    foglio._ram_libera = lambda: 0
    foglio((GIGA, 1), DUE)
    foglio._ram_libera = lambda: None
    foglio((GIGA, 2), DUE)
    assert foglio.usato == ldf_foglio.DISCO and foglio.giga() == 6.0
    foglio.lascia()
    assert foglio.giga() == 6.0
    foglio.nuovo_video()
    assert foglio.usato is None and foglio.giga() == 0.0


def test_il_riassunto_dei_tempi():
    assert ldf_foglio.riassunto([]) is None
    assert ldf_foglio.riassunto([{"passi": 3}, "rotto"]) is None
    assert ldf_foglio.riassunto([{"foglio": "ram", "foglio_gb": 1.5},
                                 {"foglio": "ram", "foglio_gb": 4.2}]) == {
        "dove": "ram", "gb": 4.2}
    assert ldf_foglio.riassunto([{"foglio": "disco", "foglio_gb": 2.0},
                                 {"foglio": "ram", "foglio_gb": 4.2}]) == {
        "dove": "disco", "gb": 4.2}


def test_le_fette_escono_dalla_scheda_una_volta_sola():
    fette = ldf_fette.Fette()
    assert fette.scelte() == {"ffn": ldf_fette.FFN_PEZZI, "domande": ldf_fette.DOMANDE,
                              "tessere": ldf_fette.TESSERE}
    assert fette.esci() is True and fette.fuori
    assert fette.esci() is False
    assert fette.scelte()["fuori"] is True


class _SenzaGradi:
    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


def test_al_minimo_esce_dalla_scheda_e_solo_dopo_si_ferma(monkeypatch):
    monkeypatch.setitem(sys.modules, "torch", types.SimpleNamespace(
        no_grad=_SenzaGradi, cuda=types.SimpleNamespace(is_available=lambda: False)))
    motore = ldfvfi.LdfVFI.__new__(ldfvfi.LdfVFI)
    motore.largo, motore.alto = 7680, 4320
    motore.dispositivo = None
    motore.fette = ldf_fette.Fette()
    while motore.fette.dimezza(512):
        pass
    visti = []

    def fai():
        visti.append(motore.fette.fuori)
        if len(visti) < 2:
            raise RuntimeError("CUDA out of memory")
        return "fatto"

    def dimezza():
        return motore.fette.dimezza(512) or motore.fette.esci()

    assert motore._riprova(fai, dimezza) == "fatto"
    assert visti == [False, True]

    def sempre():
        raise RuntimeError("CUDA out of memory")

    with pytest.raises(ldfvfi.LdfNonCiSta):
        motore._riprova(sempre, dimezza)


def test_il_motore_120_legge_dove_stanno_i_pesi_di_ldf():
    motore = fluido.Motore.__new__(fluido.Motore)
    motore.ldf = types.SimpleNamespace(
        dove_stanno={"scheda": 1.0, "ram": 2.0, "disco": 0.0},
        tempi=[{"foglio": "ram", "foglio_gb": 3.1}])
    assert motore.dove_stanno() == {"scheda": 1.0, "ram": 2.0, "disco": 0.0}
    assert motore.foglio() == {"dove": "ram", "gb": 3.1}
    motore.ldf = None
    assert motore.dove_stanno() is None and motore.foglio() is None


def test_la_pagina_dice_dove_sono_stati_appoggiati_i_calcoli():
    usati = [{"nome": centoventi.NOME, "da": "30", "a": "120", "motore": "ldf",
              "foglio": {"dove": "disco", "gb": 4.0}}]
    detto = centoventi.con_chi(usati)
    assert detto.startswith("da 30 a 120 FPS con LDF-VFI (LDF-VFI non stava")
    assert "4 GB di calcoli appoggiati sul disco dei modelli" in detto
    assert "stesso risultato" in detto
    assert "nella RAM" in centoventi.appoggiato({"dove": "ram", "gb": 2.5})
    assert "2,5 GB" in centoventi.appoggiato({"dove": "ram", "gb": 2.5})
    for strano in (None, "ram", {"dove": "altrove"}, {"dove": "ram", "gb": "tanti"}):
        assert centoventi.appoggiato(strano) == ""
    usati[0].pop("foglio")
    assert centoventi.con_chi(usati) == "da 30 a 120 FPS con LDF-VFI"


def _dit_piccolo(torch, tipo):
    nn = torch.nn
    torch.manual_seed(7)
    dim, teste, canali, patch = 12, 2, 4, (1, 2, 2)

    class Attenzione(nn.Module):
        def __init__(self):
            super().__init__()
            self.heads = teste
            self.to_q = nn.Linear(dim, dim)
            self.to_k = nn.Linear(dim, dim)
            self.to_v = nn.Linear(dim, dim)
            self.norm_q = nn.RMSNorm(dim)
            self.norm_k = nn.RMSNorm(dim)
            self.to_out = nn.ModuleList([nn.Linear(dim, dim), nn.Dropout(0.0)])

    class Blocco(nn.Module):
        def __init__(self):
            super().__init__()
            self.scale_shift_table = nn.Parameter(torch.randn(1, 6, dim) / dim ** 0.5)
            self.norm1 = nn.LayerNorm(dim, elementwise_affine=False)
            self.norm2 = nn.LayerNorm(dim)
            self.norm3 = nn.LayerNorm(dim, elementwise_affine=False)
            self.attn1 = Attenzione()
            self.attn2 = Attenzione()
            self.ffn = nn.Sequential(nn.Linear(dim, 2 * dim), nn.GELU(),
                                     nn.Linear(2 * dim, dim))

    class Condizione(nn.Module):
        def __init__(self):
            super().__init__()
            self.tempo = nn.Linear(1, dim)
            self.proietta = nn.Linear(dim, 6 * dim)

        def forward(self, tempo, _testo, _immagine):
            temb = self.tempo((tempo.unsqueeze(-1) / 1000).to(self.tempo.weight.dtype))
            return temb, self.proietta(torch.nn.functional.silu(temb)), None, None

    class Dit(nn.Module):
        def __init__(self):
            super().__init__()
            self.config = types.SimpleNamespace(patch_size=patch)
            self.patch_embedding = nn.Conv3d(canali, dim, patch, stride=patch)
            self.condition_embedder = Condizione()
            self.blocks = nn.ModuleList([Blocco(), Blocco()])
            self.scale_shift_table = nn.Parameter(torch.randn(1, 2, dim) / dim ** 0.5)
            self.norm_out = nn.LayerNorm(dim, elementwise_affine=False)
            self.proj_out = nn.Linear(dim, canali * 4)
            angoli = torch.arange(16, dtype=torch.float64).view(-1, 1) * torch.tensor(
                [0.3, 0.7, 1.1], dtype=torch.float64)
            self.rope = types.SimpleNamespace(
                attention_head_dim=dim // teste,
                freqs=torch.polar(torch.ones_like(angoli), angoli))

    dit = Dit().to(tipo).eval()
    for blocco in dit.blocks:
        blocco.norm2.float()
    ldf_fette.prepara(dit)
    return dit


@pytest.mark.parametrize("tipo", ["float32", "bfloat16"])
@pytest.mark.parametrize("scelte", [(1, 1, 1), (8, 8, 2), None])
def test_fuori_dalla_scheda_il_risultato_e_identico(tmp_path, tipo, scelte):
    torch = pytest.importorskip("torch")
    tipo = getattr(torch, tipo)
    dit = _dit_piccolo(torch, tipo)
    generatore = torch.Generator().manual_seed(3)
    entrata = torch.randn(1, 2, 3, 3, 4, 2, 4, 4, generator=generatore).to(tipo)
    tempo = torch.randint(0, 1000, (1, 2, 3, 3), generator=generatore)

    def fette():
        return ldf_fette.Fette(*scelte) if scelte else ldf_fette.Fette()

    with torch.no_grad():
        atteso = ldf_fette.avanti(dit, entrata, tempo, fette())
        assert atteso.shape == (1, 2, 3, 3, 4, 2, 4, 4)
        for ram, dove in ((None, ldf_foglio.RAM), (0, ldf_foglio.DISCO)):
            foglio = ldf_foglio.Foglio(tmp_path / "appoggio", "LDF-VFI",
                                       ram_libera=lambda ram=ram: ram)
            scelta = fette()
            scelta.esci()
            fatto = ldf_fette.avanti(dit, entrata, tempo, scelta, foglio=foglio)
            assert foglio.dove == dove
            assert torch.equal(fatto, atteso)
            assert torch.equal(ldf_fette.avanti(dit, entrata, tempo, scelta, foglio=foglio),
                               atteso)
            foglio.lascia()
        senza = fette()
        senza.esci()
        assert torch.equal(ldf_fette.avanti(dit, entrata, tempo, senza), atteso)
    assert not list((tmp_path / "appoggio").glob("*.bin"))


def test_il_foglio_vero_sul_disco_tiene_i_bf16(tmp_path):
    torch = pytest.importorskip("torch")
    foglio = ldf_foglio.Foglio(tmp_path, "LDF-VFI", ram_libera=lambda: 0)
    dato = torch.randn(5, 7).to(torch.bfloat16)
    foglio((5, 7), torch.bfloat16).copy_(dato)
    assert torch.equal(foglio((5, 7), torch.bfloat16), dato)
    assert foglio.file.stat().st_size == 70
    foglio.lascia()
    assert not list(tmp_path.glob("*.bin"))
