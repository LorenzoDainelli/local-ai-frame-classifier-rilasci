from __future__ import annotations

import sys
import types

import pytest

from officina.miglioria import codeformer, motori

QUI = "prove.test_miglioria_parcheggio"


class Volti:

    creati = 0
    pesa = 400

    def __init__(self, **_opzioni) -> None:
        type(self).creati += 1
        self.parcheggiato = 0
        self.spento = 0

    def parcheggia(self) -> int:
        self.parcheggiato += 1
        return self.pesa

    def spegni(self) -> None:
        self.spento += 1


class Rotto(Volti):

    def parcheggia(self) -> int:
        raise RuntimeError("niente RAM")


class Semplice:

    def __init__(self, **_opzioni) -> None:
        self.spento = 0

    def spegni(self) -> None:
        self.spento += 1


ELENCO = {"volti": f"{QUI}:Volti", "rotto": f"{QUI}:Rotto", "semplice": f"{QUI}:Semplice"}


@pytest.fixture
def accesi(monkeypatch):
    monkeypatch.setattr(motori, "_accesi", {})
    monkeypatch.setattr(motori, "_parcheggiati", {})
    monkeypatch.setattr(Volti, "creati", 0)
    monkeypatch.setattr(Rotto, "creati", 0)


def test_senza_l_idea_si_ricarica_ogni_volta(accesi):
    primo = motori.apri(ELENCO, "volti")
    secondo = motori.apri(ELENCO, "volti")
    assert primo is not secondo and Volti.creati == 2
    primo.spegni()
    assert primo.spento == 1 and primo.parcheggiato == 0
    assert motori.parcheggiati() == 0


def test_con_l_idea_resta_parcheggiato_e_torna_lo_stesso(accesi):
    primo = motori.apri(ELENCO, "volti", tieni=True)
    primo.spegni()
    assert motori.vero(primo).parcheggiato == 1 and motori.vero(primo).spento == 0
    assert motori.parcheggiati() == 400
    secondo = motori.apri(ELENCO, "volti", tieni=True)
    assert secondo is primo and Volti.creati == 1
    assert motori.parcheggiati() == 0


def test_fuori_dalla_stanza_accesa_non_si_parcheggia(monkeypatch):
    monkeypatch.setattr(motori, "_accesi", None)
    monkeypatch.setattr(motori, "_parcheggiati", {})
    motore = motori.apri(ELENCO, "volti", tieni=True)
    assert isinstance(motore, Volti)
    motore.spegni()
    assert motore.spento == 1 and motori.parcheggiati() == 0


def test_chi_non_sa_parcheggiarsi_si_spegne_come_prima(accesi):
    motore = motori.apri(ELENCO, "semplice", tieni=True)
    assert isinstance(motore, Semplice)
    motore.spegni()
    assert motore.spento == 1


def test_se_serve_ram_i_parcheggiati_si_spengono_davvero(accesi, monkeypatch):
    from officina.miglioria import seedvr2_blocchi

    monkeypatch.setattr(seedvr2_blocchi, "ram_libera", lambda: 900)
    motore = motori.apri(ELENCO, "volti", tieni=True)
    motore.spegni()
    assert motori.libera_per(500, 600) == 600
    assert motori.vero(motore).spento == 0
    assert motori.libera_per(500, None) is None
    assert motori.libera_per(700, 600) == 900
    assert motori.vero(motore).spento == 1 and motori.parcheggiati() == 0
    assert motori._accesi == {}
    nuovo = motori.apri(ELENCO, "volti", tieni=True)
    assert nuovo is not motore and Volti.creati == 2


def test_senza_parcheggiati_la_ram_resta_quella(accesi):
    assert motori.libera_per(700, 600) == 600


def test_un_parcheggio_che_si_rompe_spegne_il_motore(accesi):
    motore = motori.apri(ELENCO, "rotto", tieni=True)
    motore.spegni()
    assert motori.vero(motore).spento == 1
    assert motori.parcheggiati() == 0 and motori._accesi == {}


def test_spegni_tutti_spegne_anche_i_parcheggiati(accesi):
    motore = motori.apri(ELENCO, "volti", tieni=True)
    motore.spegni()
    motori.spegni_tutti()
    assert motori.vero(motore).spento == 1 and motori.parcheggiati() == 0


class _Parte:

    def __init__(self, quanti: int) -> None:
        self.quanti = quanti

    def numel(self) -> int:
        return self.quanti

    def element_size(self) -> int:
        return 2


class _Rete:

    def __init__(self, quanti: int) -> None:
        self.parte = _Parte(quanti)
        self.dove = ["cuda"]

    def parameters(self):
        return [self.parte]

    def buffers(self):
        return []

    def to(self, dove):
        self.dove.append(dove)
        return self


def _codeformer(dispositivo: str = "cuda"):
    motore = codeformer.CodeFormer.__new__(codeformer.CodeFormer)
    motore._reti = {"volto": _Rete(100), "sagoma": _Rete(20), "dispositivo": dispositivo}
    motore._trova = object()
    return motore


@pytest.fixture
def torcia_finta(monkeypatch):
    vuotate = []
    finta = types.SimpleNamespace(cuda=types.SimpleNamespace(
        empty_cache=lambda: vuotate.append(1), is_available=lambda: True))
    monkeypatch.setitem(sys.modules, "torch", finta)
    return vuotate


def test_codeformer_va_in_ram_e_torna_sulla_scheda(torcia_finta):
    motore = _codeformer()
    reti = motore._reti
    assert motore.parcheggia() == 240
    assert reti["volto"].dove == ["cuda", "cpu"] and reti["sagoma"].dove == ["cuda", "cpu"]
    assert torcia_finta == [1] and motore._trova is not None
    assert motore.parcheggia() == 240
    assert reti["volto"].dove == ["cuda", "cpu"]
    assert motore._accendi() is reti
    assert reti["volto"].dove == ["cuda", "cpu", "cuda"]
    assert motore._accendi() is reti
    assert reti["volto"].dove == ["cuda", "cpu", "cuda"]


def test_codeformer_senza_scheda_non_si_sposta(torcia_finta):
    motore = _codeformer("cpu")
    assert motore.parcheggia() == 240
    assert motore._reti["volto"].dove == ["cuda"] and torcia_finta == []


def test_codeformer_mai_acceso_non_pesa():
    motore = codeformer.CodeFormer.__new__(codeformer.CodeFormer)
    motore._reti = None
    assert motore.parcheggia() == 0


def test_faceme_parcheggiato_dimentica_i_riferimenti(torcia_finta):
    from officina.miglioria import faceme

    motore = faceme.FaceMe.__new__(faceme.FaceMe)
    motore.volti = _codeformer()
    motore._pezzi = None
    motore._visti = {7: ["vecchio"]}
    assert motore.parcheggia() == 240
    assert motore._visti == {}


class _Catena(_Rete):

    def __init__(self) -> None:
        super().__init__(0)
        self.components = {"unet": _Rete(1000), "scheduler": object()}


class _Valore(_Parte):

    def __init__(self, quanti: int, dove: str = "cuda") -> None:
        super().__init__(quanti)
        self.dove = dove

    def to(self, dove):
        return _Valore(self.quanti, dove)


def test_faceme_sposta_tutto_e_lo_riporta(torcia_finta):
    from officina.miglioria import faceme

    motore = faceme.FaceMe.__new__(faceme.FaceMe)
    motore.volti = _codeformer()
    motore._visti = {}
    motore._pezzi = {"dispositivo": "cuda", "catena": _Catena(), "mix": _Rete(10),
                     "occhio": _Rete(30), "testo": {"indice": _Valore(5)}}
    pezzi = motore._pezzi
    assert motore.parcheggia() == 240 + 2 * (10 + 30 + 1000 + 5)
    assert pezzi["catena"].dove[-1] == "cpu" and pezzi["mix"].dove[-1] == "cpu"
    assert pezzi["testo"]["indice"].dove == "cpu"
    assert motore._accendi() is pezzi
    assert pezzi["catena"].dove[-1] == "cuda" and pezzi["occhio"].dove[-1] == "cuda"
    assert pezzi["testo"]["indice"].dove == "cuda" and not pezzi["a_riposo"]


def test_la_catena_chiede_di_tenere_i_volti_solo_con_l_idea(monkeypatch):
    from officina.miglioria import catena, veloce

    from officina.miglioria import motori as m

    assert catena._idea_dei_volti(m.CODEFORMER) == veloce.VOLTI_ACCESI
    assert catena._idea_dei_volti(m.FACEME) == veloce.FACEME_ACCESO
    assert {veloce.VOLTI_ACCESI, veloce.FACEME_ACCESO} <= set(veloce.IDEE)
    sorgente = __import__("inspect").getsource(catena.foto)
    assert "tieni=veloce.acceso(lavoro, _idea_dei_volti(volti))" in sorgente
