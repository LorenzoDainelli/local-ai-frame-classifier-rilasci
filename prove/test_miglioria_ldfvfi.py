from __future__ import annotations

import json
import sys
import types

import numpy as np
import pytest

from officina.miglioria import (ldf_fette, ldf_foglio, ldf_giro, ldfvfi, scaricamento,
                                seedvr2_blocchi)

PACCHETTO_FINTO = {
    "training/models/precond.py": (
        b"from .transformer_wan import Rete\n"
        b"from .msk_encoder import Maschera\n"),
    "training/models/transformer_wan.py": (
        b"from training.distributed.util import all_to_all, gather_forward\n"
        b"class Rete:\n"
        b"    SPARGI = all_to_all\n"
        b"    RACCOGLI = gather_forward\n"),
    "training/models/msk_encoder.py": b"class Maschera:\n    pass\n",
}


@pytest.fixture
def pulito():
    yield
    for nome in [n for n in sys.modules
                 if n == ldfvfi.PACCHETTO or n.startswith(ldfvfi.PACCHETTO + ".")]:
        sys.modules.pop(nome, None)


def _scrivi(radice, file):
    for nome, dati in file.items():
        posto = radice / nome
        posto.parent.mkdir(parents=True, exist_ok=True)
        posto.write_bytes(dati)
    return radice.joinpath(*ldfvfi.RADICE)


def test_il_manifesto_vero_e_completo():
    atteso = scaricamento.manifesto(ldfvfi.NOME)
    assert len(atteso["commit"]) == 40
    assert atteso["deposito"] == "xypeng9903/LDF-VFI"
    assert atteso["licenza"] == "Apache-2.0"
    assert {"LICENSE", ldfvfi.CONFIGURAZIONE, "training/models/precond.py",
            "training/models/transformer_wan.py",
            "training/models/vae2_1_cond_v2.py"} <= set(atteso["file"])
    assert not any(n.endswith("__init__.py") for n in atteso["file"])
    assert all(len(v) == 64 for v in atteso["file"].values())
    assert [p["nome"] for p in atteso["pesi"]] == [ldfvfi.VAE, ldfvfi.DIT]
    assert all(len(p["sha256"]) == 64 and p["repo"] == "onecat-ai/LDF-VFI"
               for p in atteso["pesi"])


def test_la_licenza_e_quella_del_codice():
    from pathlib import Path

    posto = Path(ldfvfi.__file__).parent / "LICENZA-LDF-VFI.txt"
    testo = posto.read_text(encoding="utf-8")
    assert "Apache License" in testo and "Version 2.0" in testo


def test_senza_modello_il_motore_lo_dice(tmp_path):
    with pytest.raises(ldfvfi.MancaLdf):
        ldfvfi.LdfVFI(cartella_modelli=str(tmp_path))
    with pytest.raises(ldfvfi.MancaLdf):
        ldfvfi.LdfVFI()


def test_il_messaggio_quando_non_ci_sta():
    errore = ldfvfi.LdfNonCiSta(3840, 2160, 12)
    assert errore.codice == "memoria_scheda_finita"
    assert "12 GB" in str(errore) and "3840×2160" in str(errore)
    assert "si ferma" in str(errore)
    assert "nella scheda video" in str(ldfvfi.LdfNonCiSta(64, 64, None))


def test_i_pezzi_di_una_tessera():
    assert ldfvfi.pezzi_per_tessera((8, 24, 24), (1, 2, 2)) == 8 * 12 * 12
    assert ldfvfi.pezzi_per_tessera((8, 25, 24), (1, 2, 2)) == 8 * 12 * 12
    with pytest.raises(ValueError):
        ldfvfi.pezzi_per_tessera((8, 24), (1, 2, 2))


def test_la_griglia_numera_come_l_originale():
    griglia = ldf_fette.Griglia(3, 4, 5, 8, 12, 12)
    assert griglia.tessere == 60 and griglia.pezzi == 8 * 12 * 12
    visti = [griglia.indice(it, ih, iw)
             for it in range(3) for ih in range(4) for iw in range(5)]
    assert visti == list(range(60))
    assert all(griglia.posto(griglia.indice(*p)) == p
               for p in [(0, 0, 0), (2, 3, 4), (1, 2, 0), (0, 3, 1)])


def _vicine_a_mano(griglia, it, ih, iw, finestra):
    ft, fh, fw = finestra
    return tuple(griglia.indice(a, b, c)
                 for a in range(griglia.nt) for b in range(griglia.nh)
                 for c in range(griglia.nw)
                 if abs(a - it) <= ft and abs(b - ih) <= fh and abs(c - iw) <= fw)


@pytest.mark.parametrize("finestra", [(2, 1, 1), (1, 1, 1), (2, 0, 0)])
def test_le_vicine_come_la_maschera_dell_originale(finestra):
    griglia = ldf_fette.Griglia(3, 4, 5, 1, 1, 1)
    for it in range(3):
        for ih in range(4):
            for iw in range(5):
                assert ldf_fette.vicine(griglia, it, ih, iw, finestra) == \
                    _vicine_a_mano(griglia, it, ih, iw, finestra)


def test_i_gruppi_coprono_la_riga_una_volta_sola():
    griglia = ldf_fette.Griglia(3, 4, 5, 1, 1, 1)
    for ih in range(4):
        gruppi = ldf_fette.gruppi(griglia, ih)
        interrogate = [i for domande, _ in gruppi for i in domande]
        assert sorted(interrogate) == sorted(ldf_fette.riga(griglia, ih))
        assert len(interrogate) == len(set(interrogate))
        for domande, chiavi in gruppi:
            for indice in domande:
                assert chiavi == ldf_fette.vicine(griglia, *griglia.posto(indice))
                assert griglia.posto(indice)[1] == ih
            assert all(griglia.posto(c)[1] in ldf_fette.righe_servono(griglia, ih)
                       for c in chiavi)
    assert len(ldf_fette.gruppi(griglia, 0)) == 5


def test_le_righe_che_servono():
    griglia = ldf_fette.Griglia(1, 4, 1, 1, 1, 1)
    assert list(ldf_fette.righe_servono(griglia, 0)) == [0, 1]
    assert list(ldf_fette.righe_servono(griglia, 2)) == [1, 2, 3]
    assert list(ldf_fette.righe_servono(griglia, 3)) == [2, 3]


def test_i_pezzi_per_volta():
    assert ldf_fette.pezzi_per_volta(65536, 1152) == 56
    assert ldf_fette.pezzi_per_volta(10, 1152) == 1
    assert ldf_fette.pezzi_per_volta(10, 0) == 10


def test_le_fette_si_dimezzano_fino_al_minimo():
    fette = ldf_fette.Fette()
    assert fette.scelte() == {"ffn": ldf_fette.FFN_PEZZI, "domande": ldf_fette.DOMANDE,
                              "tessere": ldf_fette.TESSERE}
    assert fette.dimezza(1152) is True
    assert fette.scelte() == {"ffn": ldf_fette.FFN_PEZZI // 2, "domande": 1152 * 2,
                              "tessere": ldf_fette.TESSERE // 2}
    giri = 1
    while fette.dimezza(1152):
        giri += 1
        assert giri < 100
    assert fette.scelte() == {"ffn": ldf_fette.MINIMO, "domande": ldf_fette.MINIMO,
                              "tessere": 1}
    assert fette.dimezza(1152) is False


def test_il_lettore_legge_solo_quello_che_serve():
    letti = []

    def quadri():
        for numero in range(5):
            letti.append(numero)
            yield np.full((2, 3, 3), numero, np.uint8)

    lettore = ldf_giro.Lettore(quadri())
    assert lettore.forma is None and lettore.quanti() is None
    assert lettore.almeno(2) and letti == [0, 1]
    assert lettore.forma == (2, 3, 3)
    assert [int(q[0, 0, 0]) for q in lettore.prendi(1, 3)] == [1, 2]
    assert letti == [0, 1, 2]
    assert not lettore.almeno(9) and lettore.quanti() == 5
    assert [int(q[0, 0, 0]) for q in lettore.prendi(3, 9)] == [3, 4]
    lettore.dimentica_prima(3)
    assert sorted(lettore._tenuti) == [3, 4]


def _lettore(quanti):
    return ldf_giro.Lettore(np.zeros((1, 1, 3), np.uint8) for _ in range(quanti))


def _segni_originali(quanti, volte, da, a):
    segni = [False] * (quanti * volte)
    for numero in range(0, quanti * volte, volte):
        segni[numero] = True
    return segni[da:a], sum(segni[:da]), sum(segni[:a])


@pytest.mark.parametrize("quanti", [2, 3, 7, 16, 31, 40])
@pytest.mark.parametrize("volte", [2, 4])
def test_segni_e_conti_come_l_originale(quanti, volte):
    for da, a in [(0, 60), (40, 100), (20, 80), (100, 160), (0, 7), (59, 61)]:
        lettore = _lettore(quanti)
        segni, primo, ultimo = _segni_originali(quanti, volte, da, a)
        assert ldf_giro.segnati(lettore, da, a, volte) == segni
        assert ldf_giro.contati(lettore, da, volte) == primo
        assert ldf_giro.contati(lettore, a, volte) == ultimo


@pytest.mark.parametrize("quanti", [2, 3, 15, 16, 30, 31])
@pytest.mark.parametrize("volte", [2, 4])
def test_oltre_e_valido_come_l_originale(quanti, volte):
    totale = quanti * volte
    for posto in range(totale + 30):
        assert ldf_giro.c_e_oltre(_lettore(quanti), posto, volte) == (posto <= totale - 1)
        attesi = (quanti - 1) * volte + 1
        assert ldf_giro.valido(_lettore(quanti), posto, volte) == (posto < attesi)


def _finestre_originali(quanti, volte):
    totale = quanti * volte
    nt = ldf_giro.QUADRI // ldf_giro.PEZZO
    t0 = (nt - ldf_giro.LEGATI) * ldf_giro.PEZZO
    passo = (nt - ldf_giro.LEGATI * 2) * ldf_giro.PEZZO
    fatte = 1
    while True:
        if t0 + passo > totale - 1:
            break
        fatte += 2
        t0 += passo * 2
    if t0 < totale:
        fatte += 1
    return fatte


@pytest.mark.parametrize("quanti", [0, 1, 2, 10, 11, 15, 16, 25, 240, 480])
@pytest.mark.parametrize("volte", [2, 4])
def test_le_finestre(quanti, volte):
    atteso = 0 if quanti <= 0 else _finestre_originali(quanti, volte)
    assert ldf_giro.finestre(quanti, volte) == atteso


def test_i_tempi_della_discesa():
    pytest.importorskip("torch")
    tempi = ldf_giro.tempi(16, 8.0)
    assert len(tempi) == 17 and tempi[0] == pytest.approx(1.0) and tempi[-1] == 0.0
    assert all(a > b for a, b in zip(tempi, tempi[1:], strict=False))


def test_leggero_pronto_solo_se_viene_dai_pesi_giusti(tmp_path, monkeypatch):
    monkeypatch.setattr(ldfvfi, "_impronta_voluta", lambda nome: "a" * 64)
    assert not ldfvfi.leggero_pronto(tmp_path)
    (tmp_path / ldfvfi.LEGGERO).write_bytes(b"12345")
    assert not ldfvfi.leggero_pronto(tmp_path)
    scritto = tmp_path / ldfvfi.LEGGERO_DI_CHI
    scritto.write_text(json.dumps({"da": "a" * 64, "byte": 5}), encoding="utf-8")
    assert ldfvfi.leggero_pronto(tmp_path)
    scritto.write_text(json.dumps({"da": "b" * 64, "byte": 5}), encoding="utf-8")
    assert not ldfvfi.leggero_pronto(tmp_path)
    scritto.write_text(json.dumps({"da": "a" * 64, "byte": 6}), encoding="utf-8")
    assert not ldfvfi.leggero_pronto(tmp_path)
    scritto.write_text("{rotto", encoding="utf-8")
    assert not ldfvfi.leggero_pronto(tmp_path)


def test_l_impronta_voluta_e_quella_del_manifesto():
    pesi = {p["nome"]: p["sha256"] for p in scaricamento.manifesto(ldfvfi.NOME)["pesi"]}
    assert ldfvfi._impronta_voluta(ldfvfi.DIT) == pesi[ldfvfi.DIT]
    with pytest.raises(KeyError):
        ldfvfi._impronta_voluta("altro")


def test_solo_le_chiavi_ignorate_si_tolgono():
    stato = {"blocks.0.attn1.norm_added_q.weight": 1, "blocks.0.attn1.to_q.weight": 2}
    assert ldfvfi.stato_senza_ignorati(stato) == {"blocks.0.attn1.to_q.weight": 2}


def test_la_configurazione_toglie_i_commenti(tmp_path):
    posto = tmp_path / scaricamento.CODICE / ldfvfi.CONFIGURAZIONE
    posto.parent.mkdir(parents=True)
    posto.write_text(json.dumps({"_class_name": "X", "num_layers": 30}), encoding="utf-8")
    assert ldfvfi.configurazione(tmp_path) == {"num_layers": 30}


def test_le_entrate_del_dit_vengono_dai_pesi(tmp_path):
    posto = tmp_path / scaricamento.CODICE / ldfvfi.CONFIGURAZIONE
    posto.parent.mkdir(parents=True)
    posto.write_text(json.dumps({"_class_name": "X", "in_channels": 16, "out_channels": 16}),
                     encoding="utf-8")
    assert ldfvfi.scelte_del_dit(tmp_path, 36) == {"in_channels": 36, "out_channels": 16}


def test_il_pacchetto_si_carica_col_suo_nome_e_senza_training(tmp_path, pulito):
    cartella = _scrivi(tmp_path, PACCHETTO_FINTO)
    pacchetto = ldfvfi.carica_il_pacchetto(cartella)
    assert pacchetto.__name__ == ldfvfi.PACCHETTO
    rete = sys.modules[ldfvfi.PACCHETTO + ".models.transformer_wan"].Rete
    with pytest.raises(RuntimeError):
        rete.SPARGI()
    with pytest.raises(RuntimeError):
        rete.RACCOGLI()
    assert not any(n == "training" or n.startswith("training.") for n in sys.modules)
    assert ldfvfi.moduli_fuori(cartella) == []
    assert ldfvfi.carica_il_pacchetto(cartella) is pacchetto


def test_un_training_che_c_era_resta(tmp_path, pulito, monkeypatch):
    vero = types.ModuleType("training")
    monkeypatch.setitem(sys.modules, "training", vero)
    ldfvfi.carica_il_pacchetto(_scrivi(tmp_path, PACCHETTO_FINTO))
    assert sys.modules["training"] is vero
    assert "training.distributed" not in sys.modules


def test_un_pacchetto_rotto_non_resta_a_meta(tmp_path, pulito):
    rotto = dict(PACCHETTO_FINTO)
    rotto["training/models/msk_encoder.py"] = b"raise ImportError('no')\n"
    with pytest.raises(ImportError):
        ldfvfi.carica_il_pacchetto(_scrivi(tmp_path, rotto))
    assert not [n for n in sys.modules if n.startswith(ldfvfi.PACCHETTO)]
    assert not any(n == "training" or n.startswith("training.") for n in sys.modules)


def test_un_modulo_di_un_altro_posto_si_vede(tmp_path, pulito, monkeypatch):
    cartella = _scrivi(tmp_path / "giusto", PACCHETTO_FINTO)
    ldfvfi.carica_il_pacchetto(cartella)
    altrove = tmp_path / "altrove.py"
    altrove.write_text("")
    finto = types.ModuleType(ldfvfi.PACCHETTO + ".intruso")
    finto.__file__ = str(altrove)
    monkeypatch.setitem(sys.modules, finto.__name__, finto)
    assert ldfvfi.moduli_fuori(cartella) == [finto.__name__]


def test_la_firma_e_stabile():
    motore = ldfvfi.LdfVFI.__new__(ldfvfi.LdfVFI)
    motore.passi = 16
    firma = motore.firma()
    assert firma["nome"] == "ldfvfi" and firma["passi"] == 16 and firma["seme"] == 42
    assert firma["finestra"] == [2, 1, 1] and firma["quadri"] == 60
    assert json.loads(json.dumps(firma)) == firma


class _SenzaGradi:
    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


def _torcia_finta(monkeypatch, versione="2.7.1+cu118"):
    torcia = types.SimpleNamespace(
        __version__=versione, no_grad=_SenzaGradi,
        cuda=types.SimpleNamespace(is_available=lambda: False))
    monkeypatch.setitem(sys.modules, "torch", torcia)
    return torcia


def _motore_vuoto():
    motore = ldfvfi.LdfVFI.__new__(ldfvfi.LdfVFI)
    motore.largo, motore.alto = 3840, 2160
    motore.dispositivo = None
    motore.fette = ldf_fette.Fette()
    return motore


def test_se_la_memoria_finisce_riprova_con_meno(monkeypatch):
    _torcia_finta(monkeypatch)
    motore = _motore_vuoto()
    provati, dimezzati = [], []

    def fai():
        provati.append(1)
        if len(provati) < 3:
            raise RuntimeError("CUDA out of memory")
        return "fatto"

    def dimezza():
        dimezzati.append(1)
        return True

    assert motore._riprova(fai, dimezza) == "fatto"
    assert len(provati) == 3 and len(dimezzati) == 2


def test_al_minimo_si_ferma_e_lo_dice(monkeypatch):
    _torcia_finta(monkeypatch)
    motore = _motore_vuoto()

    def fai():
        raise RuntimeError("CUDA out of memory")

    with pytest.raises(ldfvfi.LdfNonCiSta) as preso:
        motore._riprova(fai, lambda: False)
    assert "3840×2160" in str(preso.value)


def test_un_altro_errore_non_si_riprova(monkeypatch):
    _torcia_finta(monkeypatch)
    motore = _motore_vuoto()
    dimezzati = []

    def fai():
        raise ValueError("rotto")

    with pytest.raises(ValueError):
        motore._riprova(fai, lambda: dimezzati.append(1) or True)
    assert dimezzati == []


def test_il_mucchio_si_dimezza_fino_a_uno():
    motore = _motore_vuoto()
    motore._vae = types.SimpleNamespace(batch_size=16)
    visti = []
    while motore._dimezza_il_mucchio():
        visti.append(motore._vae.batch_size)
    assert visti == [8, 4, 2, 1]


def test_con_un_quadro_solo_esce_ripetuto():
    motore = ldfvfi.LdfVFI.__new__(ldfvfi.LdfVFI)
    quadro = np.full((4, 6, 3), 7, np.uint8)
    fatti = list(motore.video(iter([quadro]), 4))
    assert len(fatti) == 4 and all(f is quadro for f in fatti)
    assert list(motore.video(iter([]), 2)) == []
    with pytest.raises(ValueError):
        list(motore.video(iter([quadro]), 1))


def _caricamento_finto(monkeypatch, tmp_path, motivo=None, fuori=(), versione="2.7.1+cu118"):
    visto = {}
    monkeypatch.setattr(ldfvfi.scaricamento, "motivo_del_codice_diverso",
                        lambda *_a, **_k: motivo)
    monkeypatch.setattr(ldfvfi.scaricamento, "manifesto", lambda nome: {"nome": nome})
    monkeypatch.setattr(ldfvfi, "carica_il_pacchetto",
                        lambda cartella: visto.setdefault("pacchetto", cartella))
    monkeypatch.setattr(ldfvfi, "moduli_fuori", lambda _c: list(fuori))
    monkeypatch.setattr(ldfvfi.importlib, "import_module",
                        lambda nome: visto.setdefault("moduli", []).append(nome) or nome)
    torcia = _torcia_finta(monkeypatch, versione)
    torcia.load = lambda *a, **k: visto.setdefault("caricato", (a, k))
    motore = ldfvfi.LdfVFI.__new__(ldfvfi.LdfVFI)
    motore.casa = tmp_path
    motore._dit = None
    motore._tipo_voluto = None
    motore.foglio = ldf_foglio.Foglio(tmp_path / ldf_foglio.CARTELLA, ldfvfi.CHI)
    return motore, visto


def test_il_caricamento_rifiuta_il_codice_cambiato(monkeypatch, tmp_path):
    monkeypatch.setattr(ldfvfi.scaricamento, "spiega_il_codice_diverso",
                        lambda motivo, cosa: f"{motivo}: {cosa}")
    motore, visto = _caricamento_finto(monkeypatch, tmp_path, motivo="cambiato")
    with pytest.raises(ldfvfi.MancaLdf) as preso:
        motore._carica()
    assert "cambiato" in str(preso.value) and "pacchetto" not in visto
    motore, visto = _caricamento_finto(monkeypatch, tmp_path, fuori=["altro"])
    with pytest.raises(ldfvfi.MancaLdf):
        motore._carica()
    assert visto["pacchetto"] == tmp_path.joinpath(scaricamento.CODICE, *ldfvfi.RADICE)
    assert "moduli" not in visto and "caricato" not in visto


def test_una_torch_vecchia_non_apre_i_pesi_di_ldf(monkeypatch, tmp_path):
    motore, visto = _caricamento_finto(monkeypatch, tmp_path, versione="2.5.1+cu121")
    with pytest.raises(ldfvfi.scheda.TorchTroppoVecchio):
        motore._carica()
    assert "caricato" not in visto and motore._dit is None
    assert sorted(visto["moduli"]) == sorted(
        f"{ldfvfi.PACCHETTO}.models.{nome}"
        for nome in ("precond", "transformer_wan", "vae2_1_cond_v2"))


def test_caricando_si_buttano_i_fogli_rimasti(monkeypatch, tmp_path):
    motore, _visto = _caricamento_finto(monkeypatch, tmp_path, versione="2.5.1+cu121")
    rimasto = tmp_path / ldf_foglio.CARTELLA / "foglio-4242.bin"
    rimasto.parent.mkdir()
    rimasto.write_bytes(b"x" * 8)
    with pytest.raises(ldfvfi.scheda.TorchTroppoVecchio):
        motore._carica()
    assert not rimasto.exists()


def test_il_foglio_sta_nella_casa_di_ldf(tmp_path, monkeypatch):
    monkeypatch.setattr(ldfvfi.scaricamento, "e_in_casa", lambda *_a: True)
    motore = ldfvfi.LdfVFI(str(tmp_path))
    assert motore.foglio.cartella == scaricamento.dove(tmp_path, ldfvfi.NOME) / "appoggio"
    assert motore.foglio.chi == "LDF-VFI" and not motore.fette.fuori


def test_i_blocchi_parlano_di_ldf():
    motore = ldfvfi.LdfVFI.__new__(ldfvfi.LdfVFI)
    motore._blocchi = seedvr2_blocchi.Blocchi(chi=ldfvfi.CHI)
    assert motore._blocchi.chi == "LDF-VFI"
    errore = seedvr2_blocchi.RamPoca(10 * 2 ** 30, 2 * 2 ** 30, chi=ldfvfi.CHI)
    assert "Per LDF-VFI" in str(errore)
    assert "Per SeedVR2" in str(seedvr2_blocchi.RamPoca(10 * 2 ** 30, 2 * 2 ** 30))
