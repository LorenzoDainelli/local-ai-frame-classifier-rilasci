from __future__ import annotations

import hashlib
import json
import sys

import numpy as np
import pytest

from officina.miglioria import gimm_spinta, gimmvfi, scaricamento


def _sha(dati: bytes) -> str:
    return hashlib.sha256(dati).hexdigest()


PACCHETTO_FINTO = {
    "src/models/__init__.py": b"from .generalizable_INR import gimmvfi_f\n",
    "src/models/generalizable_INR/__init__.py": b"from . import gimmvfi_f\n",
    "src/models/generalizable_INR/gimmvfi_f.py": (
        b"from turtle import forward\n"
        b"from .modules.softsplat import softsplat\n"
        b"PRESA = softsplat\n"),
    "src/models/generalizable_INR/modules/__init__.py": b"",
    "src/models/generalizable_INR/modules/module_config.py": (
        b"from dataclasses import dataclass\n"
        b"@dataclass\n"
        b"class Dentro:\n"
        b"    lati: int = 2\n"
        b"@dataclass\n"
        b"class Fuori:\n"
        b"    dentro: Dentro = Dentro()\n"),
}


@pytest.fixture
def pulito():
    yield
    for nome in [n for n in sys.modules
                 if n == gimmvfi.PACCHETTO or n.startswith(gimmvfi.PACCHETTO + ".")]:
        sys.modules.pop(nome, None)


def _scrivi(radice, file):
    for nome, dati in file.items():
        posto = radice / nome
        posto.parent.mkdir(parents=True, exist_ok=True)
        posto.write_bytes(dati)
    return radice.joinpath(*gimmvfi.RADICE)


def test_il_manifesto_vero_e_completo():
    atteso = scaricamento.manifesto(gimmvfi.NOME)
    assert len(atteso["commit"]) == 40
    assert atteso["deposito"] == "GSeanCDAT/GIMM-VFI"
    assert atteso["licenza"] == "S-Lab License 1.0"
    assert "LICENSE" in atteso["file"]
    assert "src/models/generalizable_INR/gimmvfi_f.py" in atteso["file"]
    assert not any(n.endswith("softsplat.py") for n in atteso["file"])
    assert not any("alt_cuda_corr" in n for n in atteso["file"])
    assert all(len(v) == 64 for v in atteso["file"].values())
    assert [p["nome"] for p in atteso["pesi"]] == [gimmvfi.PESI]
    assert all(len(p["sha256"]) == 64 and p["repo"] == "GSean/GIMM-VFI"
               for p in atteso["pesi"])


def test_senza_modello_il_motore_lo_dice(tmp_path):
    with pytest.raises(gimmvfi.MancaGimm):
        gimmvfi.GimmVFI(cartella_modelli=str(tmp_path))
    with pytest.raises(gimmvfi.MancaGimm):
        gimmvfi.GimmVFI()


@pytest.mark.parametrize(("largo", "alto", "atteso"), [
    (1920, 1080, 1.0), (1080, 1920, 1.0), (2048, 1080, 1.0), (2049, 1080, 0.5),
    (2560, 1440, 0.5), (2561, 1440, 0.25), (3840, 2160, 0.25), (7680, 4320, 0.25)])
def test_la_riduzione_dipende_dal_lato_lungo(largo, alto, atteso):
    assert gimmvfi.riduzione(largo, alto) == atteso


@pytest.mark.parametrize(("largo", "alto", "ridotto"), [
    (3840, 2160, 0.25), (1920, 1080, 1.0), (1921, 1081, 0.5), (640, 360, 0.125),
    (2560, 1440, 0.5), (32, 32, 1.0)])
def test_i_bordi_rendono_la_misura_ridotta_divisibile(largo, alto, ridotto):
    sinistra, destra, sopra, sotto = gimmvfi.bordi(largo, alto, ridotto)
    nuovo_largo, nuovo_alto = largo + sinistra + destra, alto + sopra + sotto
    assert 0 <= destra - sinistra <= 1 and 0 <= sotto - sopra <= 1
    passo = round(gimmvfi.MULTIPLO / ridotto)
    assert nuovo_largo % passo == 0 and nuovo_alto % passo == 0
    assert nuovo_largo - largo < passo and nuovo_alto - alto < passo
    assert (nuovo_largo * ridotto) % gimmvfi.MULTIPLO == 0


def test_i_bordi_del_4k():
    assert gimmvfi.bordi(3840, 2160, 0.25) == (0, 0, 8, 8)
    assert gimmvfi.bordi(1920, 1080, 1.0) == (0, 0, 4, 4)


def test_gli_istanti_in_mezzo():
    assert gimmvfi.istanti(2) == [0.5]
    assert gimmvfi.istanti(4) == [0.25, 0.5, 0.75]
    with pytest.raises(ValueError):
        gimmvfi.istanti(1)


def test_quanti_escono():
    assert gimmvfi.quanti_escono(240, 4) == 960
    assert gimmvfi.quanti_escono(480, 2) == 960
    assert gimmvfi.quanti_escono(0, 4) == 0


def _motore_finto(monkeypatch):
    motore = gimmvfi.GimmVFI.__new__(gimmvfi.GimmVFI)
    motore._rete = None
    motore.ridotto = None
    motore.tempi = []
    chiamate = []

    def in_mezzo(prima, dopo, tempi, ridotto):
        chiamate.append((int(prima[0, 0, 0]), int(dopo[0, 0, 0]), list(tempi), ridotto))
        return [np.full_like(prima, 100 + int(prima[0, 0, 0]) * 10 + numero)
                for numero in range(len(tempi))]

    monkeypatch.setattr(motore, "_in_mezzo", in_mezzo)
    return motore, chiamate


def test_il_video_esce_intero_e_in_ordine(monkeypatch):
    motore, chiamate = _motore_finto(monkeypatch)
    quadri = [np.full((4, 6, 3), numero, np.uint8) for numero in range(3)]
    fatti = [int(q[0, 0, 0]) for q in motore.video(iter(quadri), 4)]
    assert fatti == [0, 100, 101, 102, 1, 110, 111, 112, 2, 2, 2, 2]
    assert len(fatti) == gimmvfi.quanti_escono(3, 4)
    assert [c[:2] for c in chiamate] == [(0, 1), (1, 2)]
    assert all(c[2] == [0.25, 0.5, 0.75] and c[3] == 1.0 for c in chiamate)


def test_il_video_conta_le_coppie_e_regge_i_casi_piccoli(monkeypatch):
    motore, _ = _motore_finto(monkeypatch)
    contate = []
    quadri = [np.zeros((4, 6, 3), np.uint8)] * 3
    assert len(list(motore.video(quadri, 2, al_quadro=contate.append))) == 6
    assert contate == [1, 2]
    assert list(motore.video([], 2)) == []
    assert len(list(motore.video([np.zeros((4, 6, 3), np.uint8)], 4))) == 4


def test_se_la_memoria_finisce_riduce_ancora(monkeypatch):
    motore = gimmvfi.GimmVFI.__new__(gimmvfi.GimmVFI)
    motore.ridotto = None
    motore._rete = None
    provati = []
    svuotate = []

    def in_mezzo(prima, dopo, tempi, ridotto):
        provati.append(ridotto)
        if ridotto > 0.125:
            raise RuntimeError("CUDA out of memory")
        return ["ok"]

    monkeypatch.setattr(motore, "_in_mezzo", in_mezzo)
    monkeypatch.setattr(motore, "_svuota", lambda: svuotate.append(1))
    quadro = np.zeros((2160, 3840, 3), np.uint8)
    assert motore.coppia(quadro, quadro, 4) == ["ok"]
    assert provati == [0.25, 0.125] and len(svuotate) == 1
    assert motore.ridotto == 0.125
    provati.clear()
    motore.coppia(quadro, quadro, 4)
    assert provati == [0.125]


def test_alla_riduzione_minima_l_errore_esce(monkeypatch):
    motore = gimmvfi.GimmVFI.__new__(gimmvfi.GimmVFI)
    motore.ridotto = gimmvfi.RIDUZIONE_MINIMA

    def in_mezzo(*_):
        raise RuntimeError("CUDA out of memory")

    monkeypatch.setattr(motore, "_in_mezzo", in_mezzo)
    monkeypatch.setattr(motore, "_svuota", lambda: None)
    quadro = np.zeros((8, 8, 3), np.uint8)
    with pytest.raises(RuntimeError):
        motore.coppia(quadro, quadro, 2)


def test_un_altro_errore_non_si_riprova(monkeypatch):
    motore = gimmvfi.GimmVFI.__new__(gimmvfi.GimmVFI)
    motore.ridotto = None
    provati = []

    def in_mezzo(prima, dopo, tempi, ridotto):
        provati.append(ridotto)
        raise ValueError("rotto")

    monkeypatch.setattr(motore, "_in_mezzo", in_mezzo)
    quadro = np.zeros((8, 8, 3), np.uint8)
    with pytest.raises(ValueError):
        motore.coppia(quadro, quadro, 2)
    assert provati == [1.0]


def test_il_pacchetto_si_carica_col_suo_nome_e_la_spinta_nostra(tmp_path, pulito):
    cartella = _scrivi(tmp_path, PACCHETTO_FINTO)
    assert "turtle" not in sys.modules
    pacchetto = gimmvfi.carica_il_pacchetto(cartella)
    assert pacchetto.__name__ == gimmvfi.PACCHETTO
    assert pacchetto.gimmvfi_f.PRESA is gimm_spinta.softsplat
    assert "turtle" not in sys.modules
    assert "models" not in sys.modules
    assert gimmvfi.moduli_fuori(cartella) == []
    assert gimmvfi.carica_il_pacchetto(cartella) is pacchetto


class _SenzaTurtle:

    def find_spec(self, nome, percorso=None, obiettivo=None):
        if nome == "turtle":
            raise ModuleNotFoundError("No module named 'turtle'", name="turtle")
        return None


@pytest.fixture
def senza_turtle(monkeypatch):
    monkeypatch.delitem(sys.modules, "turtle", raising=False)
    monkeypatch.setattr(sys, "meta_path", [_SenzaTurtle(), *sys.meta_path])


def _con_un_pezzo_che_arriva_dopo(radice):
    file = dict(PACCHETTO_FINTO)
    chiave = "src/models/generalizable_INR/gimmvfi_f.py"
    file[chiave] = file[chiave] + (
        b"def costruisci():\n"
        b"    from .lento import Lento\n"
        b"    return Lento()\n")
    file["src/models/generalizable_INR/lento.py"] = (
        b"from turtle import forward\n"
        b"from dataclasses import dataclass\n"
        b"@dataclass\n"
        b"class Dentro:\n"
        b"    lati: int = 3\n"
        b"@dataclass\n"
        b"class Lento:\n"
        b"    dentro: Dentro = Dentro()\n")
    return _scrivi(radice, file)


def test_senza_turtle_vero_il_pezzo_che_arriva_dopo_si_rompe_fuori(
        tmp_path, pulito, senza_turtle):
    gimmvfi.carica_il_pacchetto(_con_un_pezzo_che_arriva_dopo(tmp_path))
    fatto = sys.modules[gimmvfi.PACCHETTO + ".generalizable_INR.gimmvfi_f"]
    with pytest.raises(ModuleNotFoundError):
        fatto.costruisci()


def test_senza_turtle_vero_il_pezzo_che_arriva_dopo_si_carica_col_codice_di_gimm(
        tmp_path, pulito, senza_turtle):
    import dataclasses

    cartella = _con_un_pezzo_che_arriva_dopo(tmp_path)
    gimmvfi.carica_il_pacchetto(cartella)
    fatto = sys.modules[gimmvfi.PACCHETTO + ".generalizable_INR.gimmvfi_f"]
    with gimmvfi.col_codice_di_gimm():
        lento = fatto.costruisci()
    assert lento.dentro.lati == 3
    assert "turtle" not in sys.modules
    assert dataclasses.dataclass.__module__ == "dataclasses"
    assert gimmvfi.moduli_fuori(cartella) == []


def test_col_codice_di_gimm_non_tocca_un_turtle_che_ce_gia(monkeypatch):
    import types

    vero = types.ModuleType("turtle")
    monkeypatch.setitem(sys.modules, "turtle", vero)
    with gimmvfi.col_codice_di_gimm():
        assert sys.modules["turtle"] is vero
    assert sys.modules["turtle"] is vero


def test_le_classi_di_gimm_reggono_un_predefinito_come_in_python_vecchio(tmp_path, pulito):
    import dataclasses

    vera = dataclasses.dataclass
    file = dict(PACCHETTO_FINTO)
    chiave = "src/models/generalizable_INR/gimmvfi_f.py"
    file[chiave] = file[chiave] + b"from .modules import module_config\n"
    gimmvfi.carica_il_pacchetto(_scrivi(tmp_path, file))
    scelte = sys.modules[gimmvfi.PACCHETTO + ".generalizable_INR.modules.module_config"]
    assert scelte.Fuori().dentro.lati == 2
    assert dataclasses.dataclass is vera

    @dataclasses.dataclass
    class Nostra:
        lati: int = 1

    assert Nostra.__hash__ is None
    with pytest.raises(ValueError):
        @dataclasses.dataclass
        class Storta:
            dentro: Nostra = Nostra()


def test_solo_le_classi_di_gimm_cambiano(monkeypatch):
    import dataclasses
    import types

    monkeypatch.setitem(sys.modules, gimmvfi.PACCHETTO + ".prova",
                        types.ModuleType(gimmvfi.PACCHETTO + ".prova"))
    with gimmvfi._classi_come_in_python_vecchio():
        @dataclasses.dataclass
        class Sua:
            __module__ = gimmvfi.PACCHETTO + ".prova"
            lati: int = 1

        @dataclasses.dataclass(eq=True)
        class SuaConScelte:
            __module__ = gimmvfi.PACCHETTO + ".prova"
            lati: int = 1

        @dataclasses.dataclass
        class Nostra:
            lati: int = 1

    assert Sua.__hash__ is not None and SuaConScelte.__hash__ is not None
    assert Nostra.__hash__ is None


def test_un_pacchetto_rotto_non_resta_a_meta(tmp_path, pulito):
    rotto = dict(PACCHETTO_FINTO)
    rotto["src/models/generalizable_INR/gimmvfi_f.py"] = b"raise ImportError('no')\n"
    cartella = _scrivi(tmp_path, rotto)
    with pytest.raises(ImportError):
        gimmvfi.carica_il_pacchetto(cartella)
    assert not [n for n in sys.modules if n.startswith(gimmvfi.PACCHETTO)]
    assert "turtle" not in sys.modules
    import dataclasses

    assert dataclasses.dataclass.__module__ == "dataclasses"


def test_un_modulo_di_un_altro_posto_si_vede(tmp_path, pulito, monkeypatch):
    cartella = _scrivi(tmp_path / "giusto", PACCHETTO_FINTO)
    gimmvfi.carica_il_pacchetto(cartella)
    altrove = tmp_path / "altrove.py"
    altrove.write_text("")
    finto = type(sys)(gimmvfi.PACCHETTO + ".intruso")
    finto.__file__ = str(altrove)
    monkeypatch.setitem(sys.modules, finto.__name__, finto)
    assert gimmvfi.moduli_fuori(cartella) == [finto.__name__]


def test_un_timm_finto_lascia_il_posto_a_quello_vero(monkeypatch):
    finto = type(sys)("timm")
    monkeypatch.setitem(sys.modules, "timm", finto)
    monkeypatch.setitem(sys.modules, "timm.models", type(sys)("timm.models"))
    gimmvfi._vero_timm()
    assert "timm" not in sys.modules and "timm.models" not in sys.modules


def _cartella_privata(monkeypatch, tmp_path, con_timm=True):
    from officina.programma import librerie

    monkeypatch.setattr(librerie, "cartella", lambda parte: tmp_path / parte)
    dove = tmp_path / "miglioria" / librerie.A_PARTE["timm"]
    if con_timm:
        (dove / "timm").mkdir(parents=True)
        (dove / "timm" / "__init__.py").write_text("")
    monkeypatch.setattr(sys, "path", list(sys.path))
    return dove


def test_il_timm_di_gimm_passa_davanti_a_quello_dei_modelli(monkeypatch, tmp_path):
    dove = _cartella_privata(monkeypatch, tmp_path)
    nuovo = type(sys)("timm")
    nuovo.__file__ = str(tmp_path / "modelli" / "timm" / "__init__.py")
    monkeypatch.setitem(sys.modules, "timm", nuovo)
    monkeypatch.setitem(sys.modules, "timm.layers", type(sys)("timm.layers"))
    sys.path.append(str(dove))
    gimmvfi._timm_di_gimm()
    assert "timm" not in sys.modules and "timm.layers" not in sys.modules
    assert sys.path[0] == str(dove) and sys.path.count(str(dove)) == 1


def test_il_timm_di_gimm_gia_caricato_resta(monkeypatch, tmp_path):
    dove = _cartella_privata(monkeypatch, tmp_path)
    suo = type(sys)("timm")
    suo.__file__ = str(dove / "timm" / "__init__.py")
    monkeypatch.setitem(sys.modules, "timm", suo)
    prima = list(sys.path)
    gimmvfi._timm_di_gimm()
    assert sys.modules["timm"] is suo and sys.path == prima


def test_senza_la_cartella_privata_si_torna_al_timm_vero(monkeypatch, tmp_path):
    _cartella_privata(monkeypatch, tmp_path, con_timm=False)
    vero = type(sys)("timm")
    vero.__file__ = str(tmp_path / "timm.py")
    monkeypatch.setitem(sys.modules, "timm", vero)
    prima = list(sys.path)
    gimmvfi._timm_di_gimm()
    assert sys.modules["timm"] is vero and sys.path == prima
    finto = type(sys)("timm")
    monkeypatch.setitem(sys.modules, "timm", finto)
    gimmvfi._timm_di_gimm()
    assert "timm" not in sys.modules


def test_un_timm_vero_resta(monkeypatch, tmp_path):
    vero = type(sys)("timm")
    vero.__file__ = str(tmp_path / "timm.py")
    monkeypatch.setitem(sys.modules, "timm", vero)
    gimmvfi._vero_timm()
    assert sys.modules["timm"] is vero


def test_la_firma_e_stabile():
    motore = gimmvfi.GimmVFI.__new__(gimmvfi.GimmVFI)
    firma = motore.firma()
    assert firma["nome"] == "gimmvfi" and firma["pesi"] == gimmvfi.PESI
    assert json.loads(json.dumps(firma)) == firma


def _caricamento_finto(monkeypatch, tmp_path, motivo=None, fuori=(), versione="2.7.1+cu118"):
    import types

    visto = {}

    class Rete:
        def __init__(self, scelte):
            visto["scelte"] = scelte

        def load_state_dict(self, stato, strict):
            visto["stato"], visto["strict"] = stato, strict

        def to(self, dove):
            visto["dove"] = dove
            return self

        def eval(self):
            visto["eval"] = True
            return self

    def flowformer():
        visto["vecchio"] = True

    scelte = types.SimpleNamespace(latentcostformer=types.SimpleNamespace(pretrain=True))
    moduli = {
        "gimmvfi_f": types.SimpleNamespace(GIMMVFI_F=Rete, initialize_Flowformer=flowformer),
        "configs": types.SimpleNamespace(GIMMVFIConfig=types.SimpleNamespace(
            create=lambda a: ("creata", a))),
        "flowformer": types.SimpleNamespace(get_cfg=lambda: scelte,
                                            build_flowformer=lambda s: ("flusso", s)),
    }

    def carica(percorso, map_location, weights_only):
        visto["carica"] = (percorso, map_location, weights_only)
        return {"state_dict": {"peso": 1}}

    torcia = types.SimpleNamespace(
        __version__=versione, load=carica, device=lambda nome: nome,
        cuda=types.SimpleNamespace(is_available=lambda: False))
    monkeypatch.setitem(sys.modules, "torch", torcia)
    monkeypatch.setattr(gimmvfi.importlib, "import_module",
                        lambda nome: moduli[nome.rsplit(".", 1)[1]])
    monkeypatch.setattr(gimmvfi.scaricamento, "motivo_del_codice_diverso",
                        lambda *_a, **_k: motivo)
    monkeypatch.setattr(gimmvfi.scaricamento, "manifesto", lambda nome: {"nome": nome})
    monkeypatch.setattr(gimmvfi, "carica_il_pacchetto",
                        lambda cartella: visto.setdefault("pacchetto", cartella))
    monkeypatch.setattr(gimmvfi, "moduli_fuori", lambda _c: list(fuori))
    motore = gimmvfi.GimmVFI.__new__(gimmvfi.GimmVFI)
    motore.casa = tmp_path
    motore._rete = None
    motore._dispositivo = None
    return motore, visto, moduli, scelte


def test_il_caricamento_vuole_tutti_i_pesi_e_niente_di_vecchio(monkeypatch, tmp_path):
    motore, visto, moduli, scelte = _caricamento_finto(monkeypatch, tmp_path)
    rete = motore._carica()
    assert visto["strict"] is True and visto["stato"] == {"peso": 1}
    assert visto["carica"] == (str(tmp_path / scaricamento.PESI / gimmvfi.PESI), "cpu", True)
    assert visto["scelte"] == ("creata", gimmvfi.ARCHITETTURA)
    assert visto["pacchetto"] == tmp_path.joinpath(scaricamento.CODICE, *gimmvfi.RADICE)
    assert visto["dove"] == "cpu" and visto["eval"]
    assert moduli["gimmvfi_f"].initialize_Flowformer() == ("flusso", scelte)
    assert scelte.latentcostformer.pretrain is False and "vecchio" not in visto
    visto.clear()
    assert motore._carica() is rete and visto == {}


def test_il_caricamento_rifiuta_il_codice_cambiato(monkeypatch, tmp_path):
    monkeypatch.setattr(gimmvfi.scaricamento, "spiega_il_codice_diverso",
                        lambda motivo, cosa: f"{motivo}: {cosa}")
    motore, visto, _m, _s = _caricamento_finto(monkeypatch, tmp_path, motivo="cambiato")
    with pytest.raises(gimmvfi.MancaGimm) as preso:
        motore._carica()
    assert "cambiato" in str(preso.value) and "pacchetto" not in visto
    motore, visto, _m, _s = _caricamento_finto(monkeypatch, tmp_path, fuori=["altro"])
    with pytest.raises(gimmvfi.MancaGimm):
        motore._carica()
    assert "carica" not in visto


def test_una_torch_vecchia_non_apre_i_pesi_di_gimm(monkeypatch, tmp_path):
    motore, visto, _m, _s = _caricamento_finto(monkeypatch, tmp_path, versione="2.5.1+cu121")
    with pytest.raises(gimmvfi.scheda.TorchTroppoVecchio):
        motore._carica()
    assert "carica" not in visto and "scelte" not in visto and motore._rete is None


def test_la_spinta_rifiuta_un_modo_sconosciuto():
    with pytest.raises(ValueError):
        gimm_spinta.softsplat(None, None, None, "strano")


def test_la_spinta_come_il_codice_originale():
    torch = pytest.importorskip("torch")
    entrata = torch.zeros(1, 1, 3, 4)
    entrata[0, 0, 1, 1] = 2.0
    flusso = torch.zeros(1, 2, 3, 4)
    flusso[0, 0, 1, 1] = 0.5
    flusso[0, 1, 1, 1] = 0.25
    uscita = gimm_spinta.spingi(entrata, flusso)[0, 0]
    assert float(uscita[1, 1]) == pytest.approx(2 * 0.5 * 0.75)
    assert float(uscita[1, 2]) == pytest.approx(2 * 0.5 * 0.75)
    assert float(uscita[2, 1]) == pytest.approx(2 * 0.5 * 0.25)
    assert float(uscita[2, 2]) == pytest.approx(2 * 0.5 * 0.25)
    assert float(uscita.sum()) == pytest.approx(2.0)
    flusso[0, 0, 1, 1] = float("nan")
    assert float(gimm_spinta.spingi(entrata, flusso).abs().sum()) == 0.0


def test_ogni_video_ha_la_riduzione_della_sua_misura(monkeypatch):
    motore, chiamate = _motore_finto(monkeypatch)
    for largo, alto in ((1280, 720), (4096, 2160), (1280, 720)):
        quadri = [np.zeros((alto, largo, 3), np.uint8) for _ in range(2)]
        list(motore.video(iter(quadri), 2))
    assert [c[3] for c in chiamate] == [1.0, gimmvfi.ULTIMA, 1.0]


def test_dentro_lo_stesso_video_la_riduzione_abbassata_resta(monkeypatch):
    motore = gimmvfi.GimmVFI.__new__(gimmvfi.GimmVFI)
    motore._rete = None
    motore.ridotto = None
    motore.tempi = []
    monkeypatch.setattr(motore, "_svuota", lambda: None)
    provati = []

    def in_mezzo(prima, dopo, tempi, ridotto):
        provati.append(ridotto)
        if ridotto > 0.5:
            raise RuntimeError("CUDA out of memory")
        return [prima]

    monkeypatch.setattr(motore, "_in_mezzo", in_mezzo)
    quadri = [np.zeros((8, 8, 3), np.uint8) for _ in range(3)]
    list(motore.video(iter(quadri), 2))
    assert provati == [1.0, 0.5, 0.5]


class AcceleratorError(RuntimeError):
    pass


@pytest.mark.parametrize(("guasto", "detto"), [
    (AcceleratorError("CUDA error: unspecified launch failure\nCUDA kernel errors "
                      "might be asynchronously reported"),
     "CUDA error: unspecified launch failure"),
    (RuntimeError("CUDA error: device-side assert triggered\nC:\\Users\\tizio\\x"),
     "CUDA error: device-side assert triggered"),
    (AcceleratorError("C:\\Users\\tizio\\foto.jpg si è rotto"), "CUDA error"),
    (AcceleratorError("CUDA error: out of memory"), ""),
    (RuntimeError("si è rotto"), ""),
    (None, ""),
])
def test_l_errore_della_scheda_si_dice_senza_nomi(guasto, detto):
    from officina.descrittori import torcia

    assert torcia.errore_della_scheda(guasto) == detto


def test_la_stanza_della_gara_dice_che_e_caduta_la_scheda(tmp_path, monkeypatch):
    from officina.miglioria import gara120_stanza, rete

    monkeypatch.setattr(rete, "chiudi", lambda: None)

    def motori(lavoro):
        raise AcceleratorError("CUDA error: unspecified launch failure\naltro")

    detti = []
    esito = gara120_stanza.un_lavoro(
        {"azione": gara120_stanza.CORSA, "dati": str(tmp_path), "risultati": str(tmp_path)},
        detti.append, motori=motori)
    assert esito == 1
    assert detti[-1]["guasto"] == "scheda_caduta"
    assert detti[-1]["passi"].startswith(
        "Scheda video: CUDA error: unspecified launch failure\nGuasto: AcceleratorError")
    from officina.miglioria.lavoro import a_parole

    assert "scheda video" in a_parole("scheda_caduta")
