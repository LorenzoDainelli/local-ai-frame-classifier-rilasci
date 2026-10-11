from __future__ import annotations

import sys
import types

import pytest
from PIL import Image

from officina.descrittori import base
from officina.descrittori import grandi
from officina.descrittori.grandi import Dinov3, Siglip2
from officina.descrittori import torcia


class _Tensore:

    def __init__(self, valori):
        import numpy

        self.valori = numpy.asarray(valori, dtype=numpy.float64)

    def to(self, _dispositivo):
        return self

    def float(self):
        return self

    def cpu(self):
        return self

    def norm(self, dim=None, keepdim=False):
        import numpy

        return _Tensore(numpy.linalg.norm(self.valori, axis=dim, keepdims=keepdim))

    def clamp(self, min=None):     # noqa: A002 - e' il nome di torch
        import numpy

        return _Tensore(numpy.clip(self.valori, min, None))

    def __truediv__(self, altro):
        return _Tensore(self.valori / (altro.valori if isinstance(altro, _Tensore) else altro))

    def __iter__(self):
        return (_Tensore(riga) for riga in self.valori)

    def tolist(self):
        return self.valori.tolist()

    @property
    def shape(self):
        return self.valori.shape


class _Uscita:
    def __init__(self, raccolto):
        self.pooler_output = raccolto


class _ModelloFinto:

    def __init__(self, larghezza: int, tipo_dei_pesi="float32"):
        self.larghezza = larghezza
        self.gruppi_visti: list[int] = []
        self.dispositivo = None
        self.in_valutazione = False
        self.tipo_dei_pesi = tipo_dei_pesi

    def parameters(self):
        return iter([types.SimpleNamespace(dtype=self.tipo_dei_pesi)])

    def to(self, dispositivo):
        self.dispositivo = dispositivo
        return self

    def eval(self):
        self.in_valutazione = True
        return self

    def _numeri(self, quanti):
        import numpy

        self.gruppi_visti.append(quanti)
        caso = numpy.random.default_rng(quanti)
        return _Tensore(caso.normal(size=(quanti, self.larghezza)) * 17.0)

    def __call__(self, **ingresso):
        return _Uscita(self._numeri(len(ingresso["pixel_values"].valori)))

    def get_image_features(self, **ingresso):
        return self._numeri(len(ingresso["pixel_values"].valori))


class _PreparatoreFinto:
    def __init__(self):
        self.immagini_viste = 0

    def __call__(self, images=None, return_tensors=None):
        import numpy

        self.immagini_viste += len(images)
        assert return_tensors == "pt"
        for immagine in images:
            assert isinstance(immagine, Image.Image)
        return {"pixel_values": _Tensore(numpy.zeros((len(images), 3, 4, 4)))}


@pytest.fixture
def librerie_finte(monkeypatch):
    import contextlib

    torch = types.ModuleType("torch")
    torch.float16 = "float16"
    torch.float32 = "float32"
    torch.inference_mode = contextlib.nullcontext
    torch.cuda = types.SimpleNamespace(
        is_available=lambda: False, empty_cache=lambda: None,
        ipc_collect=lambda: None)
    torch.backends = types.SimpleNamespace(mps=None)

    fatti: dict = {}

    def _modello(percorso, local_files_only=None, **altro):
        fatti["percorso_modello"] = percorso
        fatti["local_files_only"] = local_files_only
        fatti["nome_del_tipo"] = next(iter(altro), None)
        fatti["dtype"] = next(iter(altro.values()), None)
        return fatti["modello"]

    def _preparatore(percorso, local_files_only=None):
        fatti["percorso_preparatore"] = percorso
        return fatti["preparatore"]

    transformers = types.ModuleType("transformers")
    transformers.__version__ = "4.57.6"
    transformers.AutoModel = types.SimpleNamespace(from_pretrained=_modello)
    transformers.AutoImageProcessor = types.SimpleNamespace(from_pretrained=_preparatore)
    transformers.AutoTokenizer = types.SimpleNamespace(from_pretrained=lambda *a, **k: None)

    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.setitem(sys.modules, "transformers", transformers)
    monkeypatch.setitem(sys.modules, "torchvision", types.ModuleType("torchvision"))
    return fatti


def _modello_in_casa(cartella, nome: str):
    dove = cartella / nome
    dove.mkdir(parents=True, exist_ok=True)
    (dove / "config.json").write_text("{}", encoding="utf-8")
    return cartella


def _qualche_foto(quante: int) -> list[Image.Image]:
    from officina.descrittori import preparazione
    from officina.finto import immagini

    return [preparazione.in_quadrato(immagini.disegna("tema_a", seme, (240, 180)), 224)
            for seme in range(quante)]


def test_senza_librerie_lo_dice_in_italiano(tmp_path, monkeypatch):
    monkeypatch.setattr(grandi.torcia, "c_e_torch", lambda: False)
    with pytest.raises(grandi.MancanoLeLibrerie) as errore:
        Dinov3(tmp_path).apri()
    messaggio = str(errore.value)
    assert "pip install" in messaggio
    assert "funziona lo stesso" in messaggio


def test_senza_il_modello_lo_dice_e_non_lo_scarica(tmp_path, librerie_finte):
    with pytest.raises(grandi.ModelloNonInCasa) as errore:
        Dinov3(tmp_path).apri()
    assert "modelli --scarica" in str(errore.value)


@pytest.mark.parametrize("tipo", [Dinov3, Siglip2])
def test_le_impronte_escono_normalizzate_e_della_misura_giusta(tmp_path, librerie_finte, tipo):
    from officina.descrittori import vettori

    _modello_in_casa(tmp_path, tipo.scheda.nome)
    librerie_finte["modello"] = _ModelloFinto(tipo.scheda.dimensione)
    librerie_finte["preparatore"] = _PreparatoreFinto()

    descrittore = tipo(tmp_path)
    impronte = descrittore.descrivi(_qualche_foto(3))

    assert len(impronte) == 3
    for impronta in impronte:
        assert len(impronta) == tipo.scheda.dimensione
        assert vettori.somiglianza(impronta, impronta) == pytest.approx(1.0, abs=1e-6)


def test_le_immagini_arrivano_a_gruppi_della_misura_scelta(tmp_path, librerie_finte):
    _modello_in_casa(tmp_path, "dinov3")
    modello = _ModelloFinto(Dinov3.scheda.dimensione)
    librerie_finte["modello"] = modello
    librerie_finte["preparatore"] = _PreparatoreFinto()

    descrittore = Dinov3(tmp_path, per_gruppo=2)
    descrittore.descrivi(_qualche_foto(5))
    assert modello.gruppi_visti == [2, 2, 1]


def test_il_modello_si_legge_dal_disco_e_mai_dalla_rete(tmp_path, librerie_finte):
    _modello_in_casa(tmp_path, "siglip2")
    librerie_finte["modello"] = _ModelloFinto(Siglip2.scheda.dimensione)
    librerie_finte["preparatore"] = _PreparatoreFinto()

    Siglip2(tmp_path).apri()
    assert librerie_finte["local_files_only"] is True
    assert str(tmp_path / "siglip2") == librerie_finte["percorso_modello"]
    assert str(tmp_path / "siglip2") == librerie_finte["percorso_preparatore"]


def test_gli_interruttori_dell_offline_sono_accesi():
    import os

    from officina.descrittori import torcia    # noqa: F401 - e' l'import che le mette

    assert os.environ.get("HF_HUB_OFFLINE") == "1"
    assert os.environ.get("TRANSFORMERS_OFFLINE") == "1"


def test_chiudere_libera_davvero(tmp_path, librerie_finte):
    _modello_in_casa(tmp_path, "dinov3")
    librerie_finte["modello"] = _ModelloFinto(Dinov3.scheda.dimensione)
    librerie_finte["preparatore"] = _PreparatoreFinto()

    descrittore = Dinov3(tmp_path)
    descrittore.apri()
    assert descrittore.aperto and descrittore._modello is not None
    descrittore.chiudi()
    assert not descrittore.aperto and descrittore._modello is None
    descrittore.chiudi()


def test_la_carta_d_identita_e_completa():
    for scheda in (Dinov3.scheda, Siglip2.scheda):
        assert scheda.versione and scheda.dimensione > 0
        assert scheda.licenza and scheda.identificatore
        assert scheda.chiave == f"{scheda.nome}@{scheda.versione}"
        assert scheda.lato in (224, 384)
        assert scheda.precisione in (base.PIENA, base.MEZZA)
        assert scheda.versione_coerente()


@pytest.mark.parametrize("versione, atteso", [
    ("4.57.6", "dtype"), ("4.60.0", "dtype"), ("5.0.0", "dtype"),
    ("4.55.4", "torch_dtype"), ("4.40.0", "torch_dtype"),
])
def test_la_meta_precisione_arriva_col_nome_giusto(tmp_path, librerie_finte,
                                                   monkeypatch, versione, atteso):
    sys.modules["transformers"].__version__ = versione
    assert grandi._come_si_chiama_il_tipo() == atteso

    _modello_in_casa(tmp_path, "dinov3")
    librerie_finte["modello"] = _ModelloFinto(Dinov3.scheda.dimensione)
    librerie_finte["preparatore"] = _PreparatoreFinto()
    Dinov3(tmp_path).apri()
    assert librerie_finte["nome_del_tipo"] == atteso
    assert librerie_finte["dtype"] == "float32"


def _carta_finta():
    from officina.descrittori.base import Scheda
    return Scheda(nome="tale", titolo="Un Modello", versione="1",
                  famiglia="prova", dimensione=8, licenza="—",
                  identificatore="chi/che-cosa", byte_attesi=1, lato=224,
                  nota="")


def test_senza_rete_lo_dice_e_basta():
    from officina.descrittori import scaricamento
    testo = scaricamento._perche_e_andata_male(
        ConnectionError("giù"), _carta_finta(), None)
    assert "Non c'è rete" in testo
    assert "cambiato nome" not in testo


def test_il_permesso_porta_alla_pagina_giusta():
    errori = pytest.importorskip("huggingface_hub.errors")
    from officina.descrittori import scaricamento
    testo = scaricamento._perche_e_andata_male(
        errori.GatedRepoError("no"), _carta_finta(), None)
    assert "https://huggingface.co/chi/che-cosa" in testo
    assert "--chiave" in testo


def test_non_trovato_e_permesso_si_spiegano_insieme():
    errori = pytest.importorskip("huggingface_hub.errors")
    from officina.descrittori import scaricamento
    assert scaricamento._che_genere(
        errori.RepositoryNotFoundError("boh")) == "non_trovato"
    testo = scaricamento._perche_e_andata_male(
        errori.RepositoryNotFoundError("boh"), _carta_finta(), None)
    assert "chiede il permesso" in testo and "cambiato nome" in testo


def test_con_una_chiave_gia_data_il_consiglio_cambia():
    errori = pytest.importorskip("huggingface_hub.errors")
    from officina.descrittori import scaricamento
    testo = scaricamento._perche_e_andata_male(
        errori.GatedRepoError("no"), _carta_finta(), "hf_unsegreto")
    assert "non è bastata" in testo


def test_la_chiave_non_finisce_mai_nel_messaggio():
    from officina.descrittori import scaricamento
    for errore in (ConnectionError("giù"), RuntimeError("altro")):
        testo = scaricamento._perche_e_andata_male(
            errore, _carta_finta(), "hf_unsegreto")
        assert "hf_unsegreto" not in testo


def test_la_rete_si_riapre_anche_dove_e_gia_stata_letta():
    finto = types.ModuleType("huggingface_hub.constants")
    finto.HF_HUB_OFFLINE = True
    sys.modules["huggingface_hub.constants"] = finto
    try:
        prima = torcia.con_la_rete_accesa()
        assert finto.HF_HUB_OFFLINE is False, "la costante è rimasta chiusa"
        torcia.rimetti_la_rete_com_era(prima)
        assert finto.HF_HUB_OFFLINE is True, "la rete è rimasta aperta dopo"
    finally:
        del sys.modules["huggingface_hub.constants"]


def test_senza_la_libreria_in_memoria_non_la_importa():
    sys.modules.pop("huggingface_hub.constants", None)
    torcia.rimetti_la_rete_com_era(torcia.con_la_rete_accesa())
    assert "huggingface_hub.constants" not in sys.modules


def test_un_rifiuto_http_non_si_traveste_da_mancanza_di_rete():
    errori = pytest.importorskip("huggingface_hub.errors")
    from officina.descrittori import scaricamento

    class Risposta:
        status_code = 401

    guasto = errori.HfHubHTTPError("no")
    guasto.response = Risposta()
    assert isinstance(guasto, OSError)
    assert scaricamento._che_genere(guasto) == "permesso"


def test_il_dettaglio_tecnico_c_e_ma_senza_la_chiave():
    from officina.descrittori import scaricamento
    testo = scaricamento._dettaglio_tecnico(
        RuntimeError("fallito con hf_unsegreto dentro"), "hf_unsegreto")
    assert "RuntimeError" in testo
    assert "hf_unsegreto" not in testo and "«la chiave»" in testo


def test_manca_torchvision_lo_dice_col_suo_nome(monkeypatch):
    from officina.descrittori.grandi import _controlla_le_librerie, MancanoLeLibrerie
    monkeypatch.setattr(torcia, "c_e_torch", lambda: True)
    monkeypatch.setattr(torcia, "c_e_transformers", lambda: True)
    monkeypatch.setattr(torcia, "c_e_torchvision", lambda: False)
    with pytest.raises(MancanoLeLibrerie) as scoppio:
        _controlla_le_librerie(Dinov3.scheda)
    assert "torchvision" in str(scoppio.value)
    assert "requirements-modelli.txt" in str(scoppio.value)


class _Mezza(Dinov3):

    scheda = base.Scheda(
        nome="dinov3", titolo="finto grande", versione="1-f16",
        famiglia=base.VISIVO, dimensione=8, licenza="prova",
        identificatore="finto/grande", byte_attesi=1, lato=224, nota="",
        precisione=base.MEZZA,
    )


def _apri_con(tmp_path, tipo, librerie_finte, modello=None):
    _modello_in_casa(tmp_path, tipo.scheda.nome)
    librerie_finte["modello"] = modello or _ModelloFinto(tipo.scheda.dimensione)
    librerie_finte["preparatore"] = _PreparatoreFinto()
    descrittore = tipo(tmp_path)
    descrittore.apri()
    return descrittore


@pytest.mark.parametrize("tipo", [Dinov3, Siglip2])
def test_i_due_che_ci_stanno_girano_a_precisione_piena(tmp_path, librerie_finte, tipo):
    _apri_con(tmp_path, tipo, librerie_finte)
    assert librerie_finte["dtype"] == "float32"


def test_quello_che_non_ci_sta_gira_a_meta_precisione(tmp_path, librerie_finte,
                                                      monkeypatch):
    monkeypatch.setattr(torcia, "macchina",
                        lambda: torcia.Macchina("cuda", "finta", 12_000_000_000))
    _apri_con(tmp_path, _Mezza, librerie_finte,
              _ModelloFinto(_Mezza.scheda.dimensione, tipo_dei_pesi="float16"))
    assert librerie_finte["dtype"] == "float16"


def test_senza_scheda_video_nessuno_va_a_meta_precisione(tmp_path, librerie_finte):
    _apri_con(tmp_path, _Mezza, librerie_finte)
    assert librerie_finte["dtype"] == "float32"


def test_i_pesi_caricati_male_fermano_subito(tmp_path, librerie_finte):
    with pytest.raises(grandi.PrecisioneSbagliata) as errore:
        _apri_con(tmp_path, Dinov3, librerie_finte,
                  _ModelloFinto(Dinov3.scheda.dimensione, tipo_dei_pesi="float16"))
    assert "float32" in str(errore.value) and "float16" in str(errore.value)


def test_la_precisione_sta_dentro_la_versione(tmp_path, librerie_finte):
    from officina.descrittori import SCHEDE

    assert Dinov3.scheda.versione.endswith("-f32")
    assert _Mezza.scheda.versione.endswith("-f16")
    for carta in SCHEDE.values():
        assert carta.versione_coerente(), carta.nome


def test_le_impronte_si_conservano_a_trentadue_bit(tmp_path, librerie_finte):
    from officina.descrittori import vettori

    descrittore = _apri_con(tmp_path, _Mezza, librerie_finte)
    impronta = descrittore.descrivi(_qualche_foto(1))[0]
    scritta = vettori.a_byte(impronta)
    assert len(scritta) == len(impronta) * vettori.BYTE_PER_NUMERO
    assert vettori.BYTE_PER_NUMERO == 4


def _finta_libreria_che_scarica(monkeypatch, cosa_scrive):
    import sys
    import types
    from pathlib import Path

    def snapshot_download(repo_id, local_dir, **_):
        cartella = Path(local_dir)
        cartella.mkdir(parents=True, exist_ok=True)
        for nome, contenuto in cosa_scrive.items():
            (cartella / nome).write_text(contenuto)

    finta = types.ModuleType("huggingface_hub")
    finta.snapshot_download = snapshot_download
    monkeypatch.setitem(sys.modules, "huggingface_hub", finta)


def test_zero_file_scaricati_e_un_guasto_e_non_un_arrivo(tmp_path, monkeypatch):
    from officina.descrittori import scaricamento

    _finta_libreria_che_scarica(monkeypatch, {})
    detto = []
    with pytest.raises(scaricamento.ScaricamentoFallito) as guasto:
        scaricamento.scarica(_carta_finta(), tmp_path, al_passo=detto.append)

    testo = str(guasto.value)
    assert "nessun file" in testo
    assert "chi/che-cosa" in testo
    assert "*.safetensors" in testo
    assert "arrivato" not in " ".join(detto)


def test_con_i_file_dentro_lo_scaricamento_riesce(tmp_path, monkeypatch):
    from officina.descrittori import scaricamento

    _finta_libreria_che_scarica(
        monkeypatch, {"config.json": "{}", "model.safetensors": "xxxx"})
    rapporto = scaricamento.scarica(_carta_finta(), tmp_path)
    assert rapporto.file == 2
    assert not rapporto.gia_c_era


def _spazio(monkeypatch, libero):
    import shutil
    from collections import namedtuple

    from officina.descrittori import scaricamento

    uso = namedtuple("uso", "total used free")
    monkeypatch.setattr(scaricamento.shutil, "disk_usage",
                        lambda _dove: uso(10 ** 13, 0, libero))
    return shutil


def test_le_scritte_vecchie_si_buttano_e_le_nuove_lasciano_il_segno(tmp_path, monkeypatch):
    from officina import parole
    from officina.descrittori import scaricamento
    from officina.parole import lettore

    vecchia = tmp_path / "parole"
    vecchia.mkdir()
    (vecchia / "config.json").write_text("{}")
    (vecchia / "officina-florence-interna.txt").write_text("vecchio")
    (tmp_path / "lingua").mkdir()
    (tmp_path / "lingua" / "config.json").write_text("{}")
    assert not parole.in_casa(tmp_path)

    compressi = []

    def converti(grezzo, arrivo, al_passo=None):
        compressi.append(sorted(p.name for p in grezzo.iterdir()))
        assert (arrivo / "officina-florence-interna.txt").exists(), \
            "Florence-2 resta finché il nuovo non è pronto"
        import shutil

        shutil.rmtree(arrivo)
        arrivo.mkdir()
        (arrivo / "config.json").write_text("{}")
        (arrivo / "model.safetensors").write_text("4bit")
        (arrivo / parole.SCHEDA.prova_che_c_e).write_text(parole.SCHEDA.identificatore)

    monkeypatch.setattr(lettore, "converti", converti)
    _spazio(monkeypatch, 10 ** 12)
    _finta_libreria_che_scarica(
        monkeypatch, {"config.json": "{}", "model.safetensors": "xxxx"})
    scaricamento.scarica(parole.SCHEDA, tmp_path)

    assert compressi == [["config.json", "model.safetensors"]]
    assert not (vecchia / "officina-florence-interna.txt").exists()
    assert not (tmp_path / "parole.grezzo").exists()
    assert not (tmp_path / "lingua").exists()
    assert parole.in_casa(tmp_path)
    rapporto = scaricamento.scarica(parole.SCHEDA, tmp_path)
    assert rapporto.gia_c_era


def test_senza_spazio_per_qwen_lo_dice_prima_di_scaricare(tmp_path, monkeypatch):
    from officina import parole
    from officina.descrittori import scaricamento

    _spazio(monkeypatch, 5 * 10 ** 9)
    _finta_libreria_che_scarica(monkeypatch, {"config.json": "{}"})
    with pytest.raises(scaricamento.ScaricamentoFallito) as guasto:
        scaricamento.scarica(parole.SCHEDA, tmp_path)
    assert "GB liberi" in str(guasto.value)
    assert not (tmp_path / "parole.grezzo").exists()


def test_senza_rete_con_le_librerie_nuove_si_dice_che_manca_la_rete():
    from officina.descrittori import scaricamento

    class ConnectError(Exception):
        pass

    ConnectError.__module__ = "httpx"
    assert scaricamento._che_genere(ConnectError("giù")) == "niente_rete"
