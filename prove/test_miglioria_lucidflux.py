from __future__ import annotations

import hashlib
import json
import shutil

import pytest

from officina.miglioria import codeformer_pesi, lucidflux, lucidflux_pesi, motori, scaricamento
from prove import impronte_vuote

senza_impronte_vere = impronte_vuote.senza_impronte_vere


def _sha(dati: bytes) -> str:
    return hashlib.sha256(dati).hexdigest()


def test_il_manifesto_vero_e_completo():
    atteso = lucidflux_pesi.manifesto()
    assert atteso["deposito"] == "W2GenAI-Lab/LucidFlux" and len(atteso["commit"]) == 40
    assert "Non-Commercial" in atteso["licenza"]
    assert all(len(s) == 64 for s in atteso["file"].values())
    assert "src/flux/model.py" in atteso["file"] and "LICENSE" in atteso["file"]
    flux = [p for p in atteso["pesi"] if p["repo"] == "black-forest-labs/FLUX.1-dev"]
    assert {p["remoto"] for p in flux} == {"flux1-dev.safetensors", "ae.safetensors"}
    assert all(p["cancello"] for p in flux)
    locali = {p["locale"] for p in atteso["pesi"]}
    assert set(lucidflux_pesi.CONVERSIONI) <= locali
    assert lucidflux_pesi.byte_circa() > 23 * 2 ** 30
    assert motori.FOTO[motori.LUCIDFLUX] == "officina.miglioria.lucidflux:LucidFlux"
    assert motori.LUCIDFLUX not in motori.VIDEO


@pytest.fixture
def finto(tmp_path, monkeypatch):
    atteso = lucidflux_pesi.manifesto()
    codice = {file: b"codice di " + file.encode() for file in atteso["file"]}
    finto_manifesto = dict(atteso, file={f: _sha(d) for f, d in codice.items()})
    monkeypatch.setattr(lucidflux_pesi, "manifesto", lambda: finto_manifesto)
    depositi: dict[str, dict[str, bytes]] = {}
    for peso in atteso["pesi"]:
        depositi.setdefault(peso["repo"], {})[peso["remoto"]] = b"peso " + peso["remoto"].encode()
    monkeypatch.setattr(codeformer_pesi.shutil, "disk_usage",
                        lambda _p: shutil._ntuple_diskusage(1, 1, 2 ** 50))
    rete = {"accesa": False}
    stato = {"chiesti": [], "rete_alle_conversioni": [], "dichiarate": {}, "chiuso": False}

    def accendi():
        prima = dict(rete)
        rete["accesa"] = True
        return prima

    monkeypatch.setattr(lucidflux_pesi.torcia, "con_la_rete_accesa", accendi)
    monkeypatch.setattr(lucidflux_pesi.torcia, "rimetti_la_rete_com_era",
                        lambda prima: rete.update(prima))

    def prendi_testo(indirizzo):
        base = f"{scaricamento.GREZZO}/{atteso['deposito']}/{atteso['commit']}/"
        assert indirizzo.startswith(base)
        return codice[indirizzo[len(base):]]

    class Cancello(Exception):
        pass

    Cancello.__name__ = "GatedRepoError"

    def elenca(repo, chiave):
        if stato["chiuso"] and repo == "black-forest-labs/FLUX.1-dev":
            raise Cancello("401")
        return f"rev-{repo}", {n: (len(d), stato["dichiarate"].get(n, _sha(d)))
                               for n, d in depositi[repo].items()}

    def prendi_hf(repo, nome, revisione, cartella, chiave):
        assert revisione == f"rev-{repo}"
        stato["chiesti"].append(nome)
        posto = cartella / nome
        posto.parent.mkdir(parents=True, exist_ok=True)
        posto.write_bytes(depositi[repo][nome])
        return posto

    def converti_uno(sorgente, arrivo):
        stato["rete_alle_conversioni"].append(rete["accesa"])
        assert sorgente.read_bytes().startswith(b"peso ")
        arrivo.write_bytes(b"solo numeri")

    stato.update(modelli=tmp_path / "modelli", rete=rete, opzioni={
        "elenca": elenca, "prendi_hf": prendi_hf, "prendi_testo": prendi_testo,
        "converti_uno": converti_uno})
    return stato


def test_scarica_verifica_riscrive_e_mette_al_posto(finto):
    arrivo = lucidflux_pesi.scarica(finto["modelli"], **finto["opzioni"])
    assert lucidflux_pesi.e_in_casa(finto["modelli"])
    pesi = arrivo / lucidflux_pesi.PESI
    for nome in lucidflux_pesi.NECESSARI:
        assert (pesi / nome).is_file()
    assert not any((pesi / grezzo).exists() for grezzo in lucidflux_pesi.CONVERSIONI)
    assert (arrivo / "codice" / "src" / "flux" / "model.py").is_file()
    scritto = json.loads((arrivo / "pronto.json").read_text(encoding="utf-8"))
    assert scritto["fonti"]["black-forest-labs/FLUX.1-dev"] == "rev-black-forest-labs/FLUX.1-dev"
    assert finto["rete_alle_conversioni"] == [False, False, False]
    assert not finto["rete"]["accesa"]
    assert not arrivo.with_name("lucidflux.nuova").exists()


def test_gia_in_casa_non_riscarica(finto):
    lucidflux_pesi.scarica(finto["modelli"], **finto["opzioni"])
    finto["chiesti"].clear()
    lucidflux_pesi.scarica(finto["modelli"], **finto["opzioni"])
    assert finto["chiesti"] == []


def test_un_peso_diverso_da_quello_dichiarato_non_entra(finto):
    finto["dichiarate"]["ae.safetensors"] = "0" * 64
    with pytest.raises(scaricamento.ScaricamentoFallito):
        lucidflux_pesi.scarica(finto["modelli"], **finto["opzioni"])
    assert not lucidflux_pesi.e_in_casa(finto["modelli"])
    assert not lucidflux_pesi.dove(finto["modelli"]).exists()
    assert not finto["rete"]["accesa"]


def test_un_codice_cambiato_non_entra(finto):
    finto["opzioni"]["prendi_testo"] = lambda indirizzo: b"altro"
    with pytest.raises(scaricamento.ScaricamentoFallito):
        lucidflux_pesi.scarica(finto["modelli"], **finto["opzioni"])
    assert not lucidflux_pesi.e_in_casa(finto["modelli"])


def test_il_cancello_di_flux_manda_alla_pagina_giusta(finto):
    finto["chiuso"] = True
    with pytest.raises(lucidflux_pesi.ServeIlCancello) as preso:
        lucidflux_pesi.scarica(finto["modelli"], chiave="hf_segreto_finto",
                               **finto["opzioni"])
    assert lucidflux_pesi.PAGINA_DEL_CANCELLO in str(preso.value)
    assert "hf_segreto_finto" not in str(preso.value)
    with pytest.raises(lucidflux_pesi.ServeIlCancello) as senza:
        lucidflux_pesi.scarica(finto["modelli"], **finto["opzioni"])
    assert "chiave" in str(senza.value)


def test_la_chiave_non_finisce_nel_messaggio(finto):
    def rotto(repo, chiave):
        raise OSError(f"rifiutato con {chiave}")

    finto["opzioni"]["elenca"] = rotto
    with pytest.raises(scaricamento.ScaricamentoFallito) as preso:
        lucidflux_pesi.scarica(finto["modelli"], chiave="hf_segreto_finto",
                               **finto["opzioni"])
    assert "hf_segreto_finto" not in str(preso.value)


def test_appiattisce_e_rialza_senza_perdere_niente():
    torch = pytest.importorskip("torch")
    dati = {"connector": {"redux_up.weight": torch.ones(2)},
            "condition_lq": {"a.b": torch.zeros(1)}}
    piatto = lucidflux_pesi.appiattisci(dati)
    assert set(piatto) == {"connector/redux_up.weight", "condition_lq/a.b"}
    rialzato = lucidflux_pesi.rialza(piatto)
    assert set(rialzato["connector"]) == {"redux_up.weight"}


def test_senza_lucidflux_il_motore_lo_dice(tmp_path):
    from officina.miglioria import lavoro

    with pytest.raises(lucidflux.MancaLucidFlux) as preso:
        lucidflux.LucidFlux(cartella_modelli=str(tmp_path))
    assert lavoro.a_parole(preso.value.codice) != preso.value.codice


def test_la_misura_di_lavoro_e_a_multipli_di_sedici():
    assert lucidflux.misura_di_lavoro(1663, 1247) == (1648, 1232)
    assert lucidflux.misura_di_lavoro(10, 10) == (16, 16)


def test_nella_scheda_entrano_i_blocchi_che_ci_stanno_in_ordine():
    assert lucidflux.quanti_ne_stanno([3, 3, 3, 3], 7) == 2
    assert lucidflux.quanti_ne_stanno([3, 3], 100) == 2
    assert lucidflux.quanti_ne_stanno([3, 3], 0) == 0


def test_lo_scambiatore_porta_dentro_e_rimette_fuori():
    torch = pytest.importorskip("torch")
    blocco = torch.nn.Linear(2, 2)
    scambio = lucidflux.Scambiatore(torch.device("cpu"), fissa=False)
    scambio.metti_fuori(blocco)
    uscita = blocco(torch.ones(1, 2))
    assert uscita.shape == (1, 2)
    assert blocco.weight.data is blocco.weight._in_ram
    scambio.togli()


class _Pezzo:
    pass


def test_prima_dell_ultimo_passo_la_scheda_resta_solo_all_immagine(monkeypatch):
    import gc
    import inspect
    import sys
    import types
    import weakref

    svuotata = []
    monkeypatch.setitem(sys.modules, "torch", types.SimpleNamespace(
        cuda=types.SimpleNamespace(empty_cache=lambda: svuotata.append(1))))
    motore = object.__new__(lucidflux.LucidFlux)
    tolto = []
    motore._scambio = types.SimpleNamespace(togli=lambda: tolto.append(1))
    flusso, ramo = _Pezzo(), _Pezzo()
    resta_flusso, resta_ramo = weakref.ref(flusso), weakref.ref(ramo)
    pezzi = {"flusso": flusso, "ramo": ramo, "ae": "ae",
             "dispositivo": types.SimpleNamespace(type="cuda")}
    motore._pezzi = pezzi
    del flusso, ramo

    motore._libera_la_scheda(pezzi)
    gc.collect()
    assert resta_flusso() is None and resta_ramo() is None
    assert pezzi["ae"] == "ae"
    assert motore._pezzi is None and motore._scambio is None
    assert tolto == [1] and svuotata == [1]

    codice = inspect.getsource(lucidflux.LucidFlux.foto)
    assert codice.index("denoise_lucidflux(") < codice.index("_libera_la_scheda(")
    assert codice.index("_libera_la_scheda(") < codice.index(".decode(")


def test_i_messaggi_di_lucidflux_si_possono_mostrare():
    for errore in (lucidflux.MancaLucidFlux, lucidflux.RamPoca, lucidflux.SoloFoto):
        assert errore.senza_nomi is True


def test_timm_finto_basta_a_swinir():
    pytest.importorskip("torch")
    lucidflux.finto_timm()
    from timm.models.layers import to_2tuple

    assert to_2tuple(8) == (8, 8)


def test_uno_scaricamento_interrotto_riparte_da_quello_che_era_arrivato(finto):
    vero = finto["opzioni"]["prendi_hf"]

    def si_interrompe(repo, nome, revisione, cartella, chiave):
        if nome == "ae.safetensors":
            mezzo = cartella / ".cache" / "huggingface" / "download" / "ae.incomplete"
            mezzo.parent.mkdir(parents=True, exist_ok=True)
            mezzo.write_bytes(b"pe")
            raise OSError("la rete è caduta")
        return vero(repo, nome, revisione, cartella, chiave)

    with pytest.raises(scaricamento.ScaricamentoFallito):
        lucidflux_pesi.scarica(finto["modelli"], **dict(finto["opzioni"], prendi_hf=si_interrompe))
    nuova = lucidflux_pesi.dove(finto["modelli"]).with_name("lucidflux.nuova")
    pesi = nuova / lucidflux_pesi.PESI
    assert (pesi / "flux1-dev.safetensors").is_file()
    assert (pesi / lucidflux_pesi.GREZZI / ".cache" / "huggingface" / "download" / "ae.incomplete").exists()
    assert sorted(v.name for v in nuova.iterdir()) == [lucidflux_pesi.PESI]
    assert not finto["rete"]["accesa"]
    finto["chiesti"].clear()
    lucidflux_pesi.scarica(finto["modelli"], **finto["opzioni"])
    assert "flux1-dev.safetensors" not in finto["chiesti"] and "ae.safetensors" in finto["chiesti"]
    assert lucidflux_pesi.e_in_casa(finto["modelli"])
    assert not nuova.exists()


def test_un_peso_storto_si_butta_e_non_resta_per_la_volta_dopo(finto):
    finto["dichiarate"]["ae.safetensors"] = "0" * 64
    with pytest.raises(scaricamento.ScaricamentoFallito):
        lucidflux_pesi.scarica(finto["modelli"], **finto["opzioni"])
    pesi = lucidflux_pesi.dove(finto["modelli"]).with_name("lucidflux.nuova") / lucidflux_pesi.PESI
    assert not (pesi / "ae.safetensors").exists()
    assert (pesi / "flux1-dev.safetensors").is_file()
