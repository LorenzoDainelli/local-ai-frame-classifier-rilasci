import io
import sys
import types
from types import SimpleNamespace

import numpy as np
import pytest

from officina.corpi import kpr, kpr_pesi
from officina.errori import ErroreOfficina


def _conf(gruppo="cck8", negativi=True):
    return SimpleNamespace(larghezza=128, altezza=384, soglia_punti=0.3, punti_continui=False,
                           negativi=negativi, raggruppamento=gruppo)


def test_la_campana_ha_la_misura_e_la_cima_giuste():
    nucleo = kpr.campana(128)
    assert nucleo.shape == (23, 23)
    assert nucleo[11, 11] == pytest.approx(1.0)
    assert nucleo[11, 0] == pytest.approx(np.exp(-0.5 * (11 / 5.75) ** 2))


def test_le_campane_saltano_i_punti_poco_sicuri_e_si_tagliano_ai_bordi():
    punti = np.array([[0.0, 0.0, 0.9], [60.0, 200.0, 0.2], [127.0, 383.0, 0.31]])
    caldi = kpr.campane(punti, 128, 384, 0.3, False)
    assert caldi.shape == (3, 384, 128)
    assert caldi[0, 0, 0] == pytest.approx(1.0)
    assert caldi[1].max() == 0
    assert caldi[2, 383, 127] == pytest.approx(1.0)
    assert caldi[2, 372, 116] > 0


def test_il_suggerimento_ha_sfondo_altri_e_le_otto_parti():
    bersaglio = np.zeros((17, 3))
    bersaglio[0] = (64, 30, 0.9)
    bersaglio[15] = (40, 370, 0.8)
    altro = np.zeros((17, 3))
    altro[5] = (100, 150, 0.9)
    fatto = kpr.suggerimento(bersaglio, [altro], _conf())
    assert fatto.shape == (10, 384, 128)
    assert fatto[1, 150, 100] == pytest.approx(1.0)
    assert fatto[2, 30, 64] == pytest.approx(1.0)
    assert fatto[6, 370, 40] == pytest.approx(1.0) and fatto[8, 370, 40] == pytest.approx(1.0)
    assert fatto[0, 200, 10] == 1 and fatto[0, 30, 64] == 0
    vicino = 1 - fatto[2, 33, 64]
    assert fatto[0, 33, 64] == pytest.approx(vicino) and 0 < vicino < 1


def test_senza_altre_persone_il_canale_degli_altri_resta_vuoto():
    fatto = kpr.suggerimento(np.zeros((17, 3)), [], _conf("cck6"))
    assert fatto.shape == (8, 384, 128)
    assert fatto[1].max() == 0 and fatto[0].min() == 1


def test_i_punti_fuori_dal_ritaglio_non_contano():
    punti = [[0.5, 0.5, 0.9], [0.05, 0.5, 0.9], [0.6, 0.6, 0.0]] + [[0, 0, 0]] * 130
    dentro = kpr.nel_ritaglio(punti, (400, 200, 600, 800), 1000, 1000, 128, 384)
    assert dentro.shape == (17, 3)
    assert tuple(dentro[0]) == pytest.approx((64.0, 192.0, 0.9))
    assert dentro[1].sum() == 0 and dentro[2].sum() == 0


def test_la_distanza_conta_solo_le_parti_viste_da_tutti_e_due():
    a = np.eye(3, 4, dtype=np.float32)
    b = a.copy()
    b[2] = (0, 1, 0, 0)
    assert kpr.distanza(a, [1, 1, 0], b, [1, 1, 1]) == pytest.approx(0.0)
    assert kpr.distanza(a, [1, 1, 1], b, [1, 1, 1]) == pytest.approx(np.sqrt(2) / 3 / 2)
    assert kpr.distanza(a, [1, 0, 0], b, [0, 1, 1]) == 1.0


PAGINA_DI_CONFERMA = """<html><body><form id="download-form"
action="https://drive.usercontent.google.com/download" method="get">
<input type="submit" value="Download anyway"/>
<input type="hidden" name="id" value="ABC_123">
<input type="hidden" name="export" value="download">
<input type="hidden" name="confirm" value="t">
<input type="hidden" name="uuid" value="u-1&amp;2"></form></body></html>"""


def test_la_pagina_di_conferma_di_drive_si_legge():
    indirizzo = kpr_pesi._modulo_di_conferma(PAGINA_DI_CONFERMA)
    assert indirizzo.startswith("https://drive.usercontent.google.com/download?")
    assert "id=ABC_123" in indirizzo and "uuid=u-1%262" in indirizzo


def test_una_pagina_che_manda_altrove_non_si_segue():
    altrove = PAGINA_DI_CONFERMA.replace("drive.usercontent.google.com", "esempio.invalid")
    assert kpr_pesi._modulo_di_conferma(altrove) is None
    assert kpr_pesi._modulo_di_conferma("<html>troppi download</html>") is None


class _Risposta(io.BytesIO):

    def __init__(self, dati: bytes, tipo: str):
        super().__init__(dati)
        self.headers = {"Content-Type": tipo, "Content-Length": str(len(dati))}

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


def test_drive_chiede_conferma_e_poi_da_il_file(tmp_path, monkeypatch):
    chiesti = []
    risposte = [_Risposta(PAGINA_DI_CONFERMA.encode(), "text/html; charset=utf-8"),
                _Risposta(b"pesi finti" * 1000, "application/octet-stream")]

    def chiedi(indirizzo):
        chiesti.append(indirizzo)
        return risposte.pop(0)

    monkeypatch.setattr(kpr_pesi, "_chiedi", chiedi)
    punti = []
    impronta = kpr_pesi.da_drive("ABC_123", tmp_path / "f", lambda f, t: punti.append((f, t)))
    import hashlib

    assert impronta == hashlib.sha256(b"pesi finti" * 1000).hexdigest()
    assert (tmp_path / "f").read_bytes() == b"pesi finti" * 1000
    assert "confirm=t" in chiesti[0] and "uuid=" in chiesti[1]
    assert punti[-1] == (10000, 10000)


def test_drive_chiuso_si_dice_a_parole(tmp_path, monkeypatch):
    monkeypatch.setattr(kpr_pesi, "_chiedi",
                        lambda indirizzo: _Risposta(b"<html>Quota exceeded</html>", "text/html"))
    with pytest.raises(ErroreOfficina) as preso:
        kpr_pesi.da_drive("X", tmp_path / "f")
    assert preso.value.codice == "drive_chiuso"


def test_la_cartella_di_drive_si_legge(monkeypatch):
    pagina = ('<div class="flip-entry"><a href="https://drive.google.com/file/d/id-uno_1/view?usp=drive_web">'
              '<div class="flip-entry-title">kpr_market_SOLIDER_93.25_96.59_41453430.pth.tar</div></a></div>'
              '<a href="https://drive.google.com/file/d/id2/view?usp=drive_web" target="_blank">'
              '<div class="x"></div><div class="flip-entry-title">altro.pth</div></a>')
    monkeypatch.setattr(kpr_pesi, "_chiedi", lambda indirizzo: _Risposta(pagina.encode(), "text/html"))
    elenco = kpr_pesi.elenco_della_cartella()
    assert elenco == {"kpr_market_SOLIDER_93.25_96.59_41453430.pth.tar": "id-uno_1",
                      "altro.pth": "id2"}


def test_senza_impronta_fissata_kpr_non_si_scarica(tmp_path, monkeypatch):
    import dataclasses

    monkeypatch.setattr(kpr_pesi, "PESI", tuple(dataclasses.replace(p, sha256="")
                                               for p in kpr_pesi.PESI))
    with pytest.raises(ErroreOfficina) as preso:
        kpr_pesi.scarica(tmp_path)
    assert preso.value.codice == "kpr_non_controllato"


def test_se_l_impronta_non_torna_il_file_non_si_apre(tmp_path, monkeypatch):
    import dataclasses

    pesi = tuple(dataclasses.replace(p, drive="id", sha256="0" * 64) for p in kpr_pesi.PESI)
    monkeypatch.setattr(kpr_pesi, "PESI", pesi)

    def finto(codice, dove, a_che_punto=None):
        dove.write_bytes(b"cambiato")
        return "1" * 64

    aperti = []
    monkeypatch.setattr(kpr_pesi, "da_drive", finto)
    monkeypatch.setattr(kpr_pesi, "converti", lambda *a: aperti.append(a))
    with pytest.raises(ErroreOfficina) as preso:
        kpr_pesi.scarica(tmp_path)
    assert preso.value.codice == "kpr_diverso" and not aperti
    assert not list(kpr_pesi.dove_stanno(tmp_path).glob("arriva-*"))


def test_i_resti_di_uno_scaricamento_di_kpr_ucciso_a_meta_si_tolgono(tmp_path, monkeypatch):
    import dataclasses

    casa = kpr_pesi.dove_stanno(tmp_path)
    avanzo = casa / "arriva-r4nd0m"
    avanzo.mkdir(parents=True)
    (avanzo / "pesi.pth.tar").write_bytes(b"x" * 64)
    monkeypatch.setattr(kpr_pesi, "PESI", tuple(dataclasses.replace(p, sha256="")
                                               for p in kpr_pesi.PESI))
    with pytest.raises(ErroreOfficina):
        kpr_pesi.scarica(tmp_path)
    assert not avanzo.exists()


def test_la_scheda_prende_la_configurazione_salvata_e_il_resto_dai_valori_di_kpr():
    pacco = {"config": {"model": {"kpr": {"masks": {"parts_num": 8, "prompt_parts_num": 8},
                                          "keypoints": {"prompt_preprocess": "cck8"}},
                                  "promptable_trans": {"no_background_token": True}}}}
    scheda = kpr_pesi.scheda_dal_pacco(pacco, kpr_pesi.PESI[0])
    assert scheda["kpr"]["masks"]["parts_num"] == 8
    assert scheda["kpr"]["keypoints"]["vis_thresh"] == 0.3
    assert scheda["promptable_trans"]["no_background_token"] is False
    assert scheda["solider"]["semantic_weight"] == 0.2
    assert scheda["data"]["height"] == 384 and scheda["data"]["norm_mean"] == [0.5] * 3


def test_senza_configurazione_dentro_non_si_indovina():
    with pytest.raises(ErroreOfficina):
        kpr_pesi.scheda_dal_pacco({"state_dict": {}}, kpr_pesi.PESI[1])


def test_un_file_con_dentro_un_comando_non_si_apre(tmp_path):
    torch = pytest.importorskip("torch")
    import os

    class Trappola:
        def __reduce__(self):
            return (os.system, ("echo preso",))

    percorso = tmp_path / "trappola.pth.tar"
    torch.save({"state_dict": {}, "trappola": Trappola()}, percorso)
    with pytest.raises(ErroreOfficina) as preso:
        kpr_pesi.apri_con_cautela(percorso)
    assert preso.value.codice == "pesi_strani"


def test_la_configurazione_di_yacs_si_apre_senza_yacs(tmp_path, monkeypatch):
    torch = pytest.importorskip("torch")
    modulo = types.ModuleType("yacs.config")

    class CfgNode(dict):
        pass

    CfgNode.__module__ = "yacs.config"
    CfgNode.__qualname__ = "CfgNode"
    modulo.CfgNode = CfgNode
    monkeypatch.setitem(sys.modules, "yacs", types.ModuleType("yacs"))
    monkeypatch.setitem(sys.modules, "yacs.config", modulo)
    nodo = CfgNode({"model": CfgNode({"kpr": CfgNode({"a": 1})})})
    nodo.__dict__["__deprecated_keys__"] = {"x"}
    percorso = tmp_path / "pesi.pth.tar"
    torch.save({"config": nodo, "rank1": np.float64(0.5), "state_dict": {"w": torch.ones(2)}},
               percorso)
    monkeypatch.delitem(sys.modules, "yacs.config")
    monkeypatch.delitem(sys.modules, "yacs")
    pacco = kpr_pesi.apri_con_cautela(percorso)
    assert kpr_pesi._come_dizionario(pacco["config"]) == {"model": {"kpr": {"a": 1}}}
    assert float(pacco["rank1"]) == 0.5
    assert torch.equal(pacco["state_dict"]["w"], torch.ones(2))


def test_la_rete_esce_con_una_riga_per_parte_e_lunga_uno():
    torch = pytest.importorskip("torch")
    from officina.corpi import kpr_rete

    scheda = kpr_pesi.scheda_dal_pacco(
        {"config": {"model": {"kpr": {"masks": {"parts_num": 5, "prompt_parts_num": 6},
                                      "keypoints": {"prompt_preprocess": "cck6"}}}}},
        kpr_pesi.PESI[1])
    conf = kpr_rete.Configurazione(scheda)
    modello = kpr_rete.KPR(conf).eval()
    immagini = torch.randn(2, 3, 384, 128)
    suggerimenti = torch.stack([torch.from_numpy(kpr.suggerimento(np.zeros((17, 3)), [], conf))] * 2)
    with torch.no_grad():
        immersione, visibili = modello(immagini, suggerimenti)
    assert immersione.shape == (2, 6, 512) and visibili.shape == (2, 6)
    assert torch.allclose(immersione.norm(dim=-1), torch.ones(2, 6), atol=1e-5)
    assert visibili.dtype == torch.bool and bool(visibili[:, 0].all())


def test_una_configurazione_mai_vista_si_ferma_subito():
    pytest.importorskip("torch")
    from officina.corpi import kpr_rete

    scheda = kpr_pesi.scheda_dal_pacco({"config": {"model": {"kpr": {"enable_fpn": True}}}},
                                       kpr_pesi.PESI[2])
    with pytest.raises(ValueError):
        kpr_rete.Configurazione(scheda)


def test_la_sagoma_tiene_la_persona_e_spegne_lo_sfondo():
    from PIL import Image

    from officina.corpi import maschere, vestiti

    immagine = Image.new("RGB", (200, 100), (250, 0, 0))
    forma = np.zeros((50, 40), dtype=bool)
    forma[10:40, 10:30] = True
    fatta = vestiti.sagoma(immagine, (0.25, 0.25, 0.2, 0.5), maschere.comprimi(forma))
    assert fatta.size == (50, 50)
    assert fatta.getpixel((25, 25)) == (250, 0, 0)
    assert fatta.getpixel((10, 2)) == vestiti.GRIGIO
    assert fatta.getpixel((2, 25)) == vestiti.GRIGIO


def test_una_persona_troppo_piccola_non_si_descrive():
    from PIL import Image

    from officina.corpi import vestiti

    assert vestiti.sagoma(Image.new("RGB", (100, 100)), (0.1, 0.1, 0.05, 0.3)) is None


def test_le_tre_versioni_hanno_codice_impronta_e_peso():
    for pesi in kpr_pesi.PESI:
        assert pesi.drive and len(pesi.sha256) == 64 and pesi.byte > 300_000_000
    assert {p.versione for p in kpr_pesi.PESI} == set(kpr.VERSIONI)


def test_se_drive_inciampa_si_riprova_da_solo(monkeypatch):
    import urllib.error
    import urllib.request

    volte = []

    def apri(richiesta, timeout=None):
        volte.append(1)
        if len(volte) < 3:
            raise urllib.error.HTTPError(richiesta.full_url, 500, "inciampo", {}, None)
        return "fatto"

    monkeypatch.setattr(urllib.request, "urlopen", apri)
    monkeypatch.setattr(kpr_pesi, "ATTESA", 0)
    assert kpr_pesi._chiedi("https://drive.usercontent.google.com/download?id=x") == "fatto"
    assert len(volte) == 3


def test_un_rifiuto_vero_di_drive_non_si_riprova(monkeypatch):
    import urllib.error
    import urllib.request

    volte = []

    def apri(richiesta, timeout=None):
        volte.append(1)
        raise urllib.error.HTTPError(richiesta.full_url, 404, "non c'è", {}, None)

    monkeypatch.setattr(urllib.request, "urlopen", apri)
    with pytest.raises(urllib.error.HTTPError):
        kpr_pesi._chiedi("https://drive.usercontent.google.com/download?id=x")
    assert len(volte) == 1
