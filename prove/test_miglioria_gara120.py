from __future__ import annotations

import hashlib
import io
import random
import tarfile
import zipfile
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image

from officina.descrittori.scaricamento import ScaricamentoFallito
from officina.miglioria import gara120_casi as g
from officina.miglioria import gara120_corsa as corsa
from officina.miglioria import gara120_fonti as fonti
from officina.miglioria import gara120_rovina as rovina
from officina.miglioria import gara120_scarica as sc
from officina.miglioria import gara120_voti as voti
from officina.miglioria import gara120_voto as voto


@pytest.fixture(autouse=True)
def _spazio_largo(monkeypatch):
    monkeypatch.setattr(sc, "libero", lambda cartella: 2 ** 50)


def test_finestra_tiene_quattro_e_mette_i_veri_nel_mezzo():
    tenuti, veri = g.finestra(100, 8, 4)
    assert tenuti == (88, 96, 104, 112)
    assert veri == (98, 100, 102)
    tenuti, veri = g.finestra(100, 4, 2)
    assert tenuti == (94, 98, 102, 106) and veri == (100,)


def test_finestra_rifiuta_passi_strani():
    with pytest.raises(ValueError):
        g.finestra(100, 6, 4)
    with pytest.raises(ValueError):
        g.finestra(100, 7, 2)


def test_centri_dalla_lista_toglie_il_prefisso():
    testo = ("data/SNU-FILM/test/GOPRO_test/A/000010.png "
             "data/SNU-FILM/test/GOPRO_test/A/000014.png "
             "data/SNU-FILM/test/GOPRO_test/A/000018.png\n")
    assert g.centri_dalla_lista(testo) == [("test/GOPRO_test/A", 14)]


def test_mosso_chiede_anche_i_vicini():
    caso = g.Caso("x", g.DIFFICILISSIMO, "s", 8, 4, g.MOSSO, (10,), (12,))
    assert caso.servono() == list(range(6, 16))


def _piano_finto():
    presenti = {"a/s": set(range(1, 1000)), "b/t": set(range(40, 300))}
    centri = ([("a/s", x) for x in range(50, 950, 30)]
              + [("b/t", x) for x in range(30, 280, 20)])
    return presenti, centri, g.piano(centri, presenti)


def test_il_piano_usa_solo_fotogrammi_che_esistono():
    presenti, _, casi = _piano_finto()
    assert casi
    for caso in casi:
        assert all(n in presenti[caso.scena] for n in caso.servono())


def test_il_piano_e_sempre_uguale_e_non_supera_i_conti():
    _, centri, casi = _piano_finto()
    presenti = {"a/s": set(range(1, 1000)), "b/t": set(range(40, 300))}
    rovescio = g.piano(list(reversed(centri)), presenti)
    assert sorted(c.nome for c in casi) == sorted(c.nome for c in rovescio)
    gruppi = {}
    for caso in casi:
        gruppi[(caso.passo, caso.rovina)] = gruppi.get((caso.passo, caso.rovina), 0) + 1
    assert gruppi[(4, None)] <= g.QUANTI["facili"]
    assert all(gruppi.get((16, r), 0) <= g.QUANTI["rovinati"] for r in g.ROVINE)


def test_rovinati_vengono_dagli_estremi():
    _, _, casi = _piano_finto()
    estremi = {(c.scena, c.tenuti) for c in casi if c.passo == 16 and c.rovina is None}
    for caso in casi:
        if caso.rovina in g.ROVINE:
            assert (caso.scena, caso.tenuti) in estremi


def test_xtest_ha_quattro_versioni_per_spezzone():
    casi = g.casi_xtest(["Type1/A", "Type2/B"])
    assert len(casi) == 8
    assert {c.rovina for c in casi} == {None, *g.ROVINE}
    assert all(c.servono() == [0, 8, 16, 24, 32] for c in casi)
    assert all(c.gruppo == g.DIFFICILISSIMO for c in casi)


def test_adobe_sceglie_sempre_le_stesse_cartelle():
    cartelle = [f"x/{1000 + i}" for i in range(200)]
    uno = g.casi_adobe(cartelle)
    due = g.casi_adobe(list(reversed(cartelle)))
    assert [c.nome for c in uno] == [c.nome for c in due]
    assert len(uno) == g.QUANTI["adobe"]
    assert all(c.servono() == [0, 2, 4, 6, 8] for c in uno)


def test_righe_e_impronta():
    presenti, veri_nomi = g.presenti_da_nomi(["a/s/00001.png", "a/s/00002.png", "x.txt"])
    assert presenti == {"a/s": {1, 2}}
    righe = g.righe_tutte(veri_nomi, lambda n: ("h" + n[-5], 3))
    assert righe == ["h1 3 1 a/s/00001.png", "h2 3 2 a/s/00002.png"]
    assert g.impronta("ciao") == hashlib.sha256(b"ciao").hexdigest()


def test_voti_uguali_danno_il_tetto():
    quadro = np.full((64, 64, 3), 120, np.uint8)
    esito = voti.voti(quadro, quadro)
    assert esito["somiglianza"] == voti.TETTO
    assert esito["zona_peggiore"] == voti.TETTO
    assert esito["struttura"] == pytest.approx(1.0)


def test_zona_peggiore_vede_un_errore_piccolo_che_la_media_nasconde():
    vero = np.full((256, 256, 3), 120, np.uint8)
    fatto = vero.copy()
    fatto[:32, :32] = 0
    esito = voti.voti(fatto, vero)
    assert esito["zona_peggiore"] < esito["somiglianza"] - 10


def test_voti_rifiutano_misure_diverse():
    with pytest.raises(ValueError):
        voti.voti(np.zeros((8, 8, 3), np.uint8), np.zeros((8, 9, 3), np.uint8))


def test_buio_e_rumore_sono_ripetibili():
    quadro = np.random.default_rng(1).integers(0, 255, (32, 32, 3), dtype=np.uint8)
    seme = rovina.seme("caso", 3)
    assert np.array_equal(rovina.buio(quadro, seme), rovina.buio(quadro, seme))
    assert np.array_equal(rovina.rumore(quadro, seme), rovina.rumore(quadro, seme))
    assert rovina.buio(quadro, None).mean() < quadro.mean()
    assert not np.array_equal(rovina.rumore(quadro, seme), quadro)


def test_mosso_fa_la_media_dei_vicini():
    def prendi(numero):
        return np.full((4, 4, 3), 255 if numero == 10 else 0, np.uint8)

    mosso = rovina.mosso(prendi, 10)
    assert 0 < int(mosso[0, 0, 0]) < 255


def test_prepara_buio_ha_il_vero_buio_senza_grana():
    caso = g.Caso("n", g.DIFFICILISSIMO, "s", 16, 4, "buio", (1, 2), (3,))

    def prendi(numero):
        return np.full((8, 8, 3), 200, np.uint8)

    entrate, veri = rovina.prepara(caso, prendi)
    assert len(entrate) == 2 and len(veri) == 1
    assert np.array_equal(veri[0], rovina.buio(prendi(3), None))


def test_prepara_rumore_confronta_col_vero_pulito():
    caso = g.Caso("n", g.DIFFICILISSIMO, "s", 16, 4, "rumore", (1, 2), (3,))

    def prendi(numero):
        return np.full((8, 8, 3), 100, np.uint8)

    _, veri = rovina.prepara(caso, prendi)
    assert np.array_equal(veri[0], prendi(3))


class _VoceHf(SimpleNamespace):
    pass


def _png(valore: int) -> bytes:
    uscita = io.BytesIO()
    Image.fromarray(np.full((4, 4, 3), valore, np.uint8)).save(uscita, format="PNG")
    return uscita.getvalue()


def test_elenco_snu_rifiuta_un_elenco_diverso(tmp_path):
    info = SimpleNamespace(siblings=[_VoceHf(rfilename="a/s/00001.png", size=3,
                                             lfs={"sha256": "0" * 64})])
    api = SimpleNamespace(dataset_info=lambda *a, **k: info)
    with pytest.raises(ScaricamentoFallito):
        sc.elenco_snu(tmp_path, api=api, scarica_da_hf=lambda *a: None)


def test_elenco_snu_non_manda_la_chiave(tmp_path):
    visti = {}

    def dataset_info(*argomenti, **chiavi):
        visti.update(chiavi)
        return SimpleNamespace(siblings=[])

    with pytest.raises(ScaricamentoFallito):
        sc.elenco_snu(tmp_path, api=SimpleNamespace(dataset_info=dataset_info),
                      scarica_da_hf=lambda *a: None)
    assert visti["token"] is False
    assert visti["revision"] == fonti.SNU_REVISIONE


def _elenco_finto(file: dict[str, bytes]) -> sc.Elenco:
    voci = {n: (hashlib.sha256(d).hexdigest(), len(d)) for n, d in file.items()}
    presenti, veri_nomi = g.presenti_da_nomi(voci)
    return sc.Elenco([], voci, veri_nomi, presenti)


def _hf_finto(file: dict[str, bytes], chiamate: list):
    def scarica(nome, casa):
        chiamate.append(nome)
        posto = Path(casa) / nome
        posto.parent.mkdir(parents=True, exist_ok=True)
        posto.write_bytes(file[nome])
        return posto

    return scarica


def test_scarica_snu_controlla_e_non_riscarica(tmp_path):
    file = {"a/s/00001.png": _png(10), "a/s/00002.png": _png(20)}
    elenco = _elenco_finto(file)
    chiamate = []
    sc.scarica_snu(tmp_path, elenco, sorted(file), scarica_da_hf=_hf_finto(file, chiamate))
    assert sorted(chiamate) == sorted(file)
    sc.scarica_snu(tmp_path, elenco, sorted(file), scarica_da_hf=_hf_finto(file, chiamate))
    assert len(chiamate) == 2
    prendi = sc.prendi_snu(tmp_path, elenco, "a/s")
    assert int(prendi(2)[0, 0, 0]) == 20


def test_scarica_snu_butta_un_file_sbagliato(tmp_path):
    file = {"a/s/00001.png": _png(10)}
    elenco = _elenco_finto(file)
    falso = {"a/s/00001.png": _png(11)}
    with pytest.raises(ScaricamentoFallito):
        sc.scarica_snu(tmp_path, elenco, list(file), scarica_da_hf=_hf_finto(falso, []))
    assert not (tmp_path / sc.SNU / "a/s/00001.png").exists()


def test_scarica_snu_riscarica_un_file_rovinato_dopo(tmp_path):
    file = {"a/s/00001.png": _png(10)}
    elenco = _elenco_finto(file)
    chiamate = []
    sc.scarica_snu(tmp_path, elenco, list(file), scarica_da_hf=_hf_finto(file, chiamate))
    (tmp_path / sc.SNU / "a/s/00001.png").write_bytes(b"rotto")
    sc.scarica_snu(tmp_path, elenco, list(file), scarica_da_hf=_hf_finto(file, chiamate))
    assert len(chiamate) == 2


def _xvfi_finto(tmp_path, monkeypatch, adobe_cambiato=False):
    mp4 = {}
    for nome in ("Type1/A", "Type2/B"):
        mp4[nome] = f"video {nome}".encode()
    tar_byte = io.BytesIO()
    with tarfile.open(fileobj=tar_byte, mode="w:gz") as pacco:
        for nome, dati in mp4.items():
            voce = tarfile.TarInfo(fonti.XTEST_CARTELLA + nome + ".mp4")
            voce.size = len(dati)
            pacco.addfile(voce, io.BytesIO(dati))
    adobe_byte = io.BytesIO()
    with zipfile.ZipFile(adobe_byte, "w") as adobe:
        for cartella in range(3):
            for numero in range(9):
                adobe.writestr(f"Adobe/test/{1000 + cartella}/{numero:05d}.png",
                               _png(cartella * 10 + numero))
    grande = io.BytesIO()
    with zipfile.ZipFile(grande, "w") as zz:
        zz.writestr("encoded_test.tar.gz", tar_byte.getvalue())
        zz.writestr("Adobe240fps_test_spilt_XVFI.zip", adobe_byte.getvalue())
        zz.writestr("val.tar.gz", b"non serve")
    dentro = {"encoded_test.tar.gz": (hashlib.sha256(tar_byte.getvalue()).hexdigest(), 1),
              "Adobe240fps_test_spilt_XVFI.zip": (
                  ("0" * 64) if adobe_cambiato
                  else hashlib.sha256(adobe_byte.getvalue()).hexdigest(), 1)}
    monkeypatch.setattr(fonti, "DENTRO", dentro)
    monkeypatch.setattr(fonti, "XTEST_MP4",
                        {n: hashlib.sha256(d).hexdigest() for n, d in mp4.items()})
    monkeypatch.setattr(fonti, "XVFI_BYTE", len(grande.getvalue()))
    monkeypatch.setattr(g, "QUANTI", {**g.QUANTI, "adobe": 3})
    chiamate = []

    def dalla_rete(indirizzo, posto, al_byte):
        chiamate.append(indirizzo)
        Path(posto).write_bytes(grande.getvalue())

    return dalla_rete, chiamate


def test_scarica_xvfi_tiene_solo_cio_che_serve(tmp_path, monkeypatch):
    dalla_rete, chiamate = _xvfi_finto(tmp_path, monkeypatch)
    sc.scarica_xvfi(tmp_path, dalla_rete=dalla_rete)
    assert chiamate == [fonti.XVFI_INDIRIZZO]
    assert (tmp_path / sc.ADOBE).is_file()
    assert (tmp_path / sc.XTEST / "Type1/A.mp4").read_bytes() == b"video Type1/A"
    rimasti = sorted(p.name for p in tmp_path.iterdir())
    assert rimasti == sorted([sc.ADOBE, sc.XTEST, sc.CONTROLLATI])
    sc.scarica_xvfi(tmp_path, dalla_rete=dalla_rete)
    assert len(chiamate) == 1
    cartelle = sc.cartelle_adobe(tmp_path)
    assert sorted(cartelle) == [f"Adobe/test/{1000 + i}" for i in range(3)]
    prendi = sc.prendi_adobe(tmp_path, cartelle["Adobe/test/1001"])
    assert int(prendi(4)[0, 0, 0]) == 14


def test_scarica_xvfi_rifiuta_un_archivio_diverso(tmp_path, monkeypatch):
    dalla_rete, _ = _xvfi_finto(tmp_path, monkeypatch, adobe_cambiato=True)
    with pytest.raises(ScaricamentoFallito):
        sc.scarica_xvfi(tmp_path, dalla_rete=dalla_rete)
    assert not (tmp_path / sc.ADOBE).exists()
    assert not any(p.name.endswith(sc.PARTE) for p in tmp_path.rglob("*"))
    assert not (tmp_path / ("xvfi.zip" + sc.PARTE)).exists()


def test_poco_spazio_ferma_prima(tmp_path, monkeypatch):
    monkeypatch.setattr(sc, "libero", lambda cartella: 10)
    with pytest.raises(ScaricamentoFallito):
        sc.controlla_lo_spazio(tmp_path, 100)


def test_cancella_toglie_tutto(tmp_path):
    casa = tmp_path / "gara120"
    (casa / "snu").mkdir(parents=True)
    (casa / "snu" / "a.png").write_bytes(b"12345")
    assert sc.cancella(casa) == 5
    assert not casa.exists()
    assert sc.cancella(casa) == 0


def test_prepara_compresso_comprime_anche_il_vero(monkeypatch):
    chiamate = []

    def finto(quadri):
        chiamate.append(len(quadri))
        return [np.asarray(q) // 2 for q in quadri]

    monkeypatch.setattr(rovina, "compresso", finto)
    caso = g.Caso("n", g.DIFFICILISSIMO, "s", 32, 4, "compresso", (0, 32), (8, 16, 24))

    def prendi(numero):
        return np.full((8, 8, 3), 100 + numero, np.uint8)

    entrate, veri = rovina.prepara(caso, prendi)
    assert chiamate == [2, 5]
    assert [int(v[0, 0, 0]) for v in veri] == [54, 58, 62]
    assert int(entrate[0][0, 0, 0]) == 50


def test_compresso_vero_con_pyav():
    pytest.importorskip("av")
    quadri = [np.random.default_rng(n).integers(0, 255, (36, 50, 3), dtype=np.uint8)
              for n in range(5)]
    tornati = rovina.compresso(quadri)
    assert len(tornati) == 5
    assert all(t.shape == (36, 50, 3) for t in tornati)


class _MotoreFinto:

    def __init__(self, nome, sbaglio=0, non_ci_sta=None):
        self.nome = nome
        self.sbaglio = sbaglio
        self.non_ci_sta = non_ci_sta
        self.chiamate = 0
        self.spento = 0

    def firma(self):
        return {"nome": self.nome}

    def video(self, quadri, volte):
        quadri = [np.asarray(q, dtype=np.float64) for q in quadri]
        self.chiamate += 1
        if self.non_ci_sta is not None:
            raise self.non_ci_sta("grande")
        for prima, dopo in zip(quadri, quadri[1:]):
            yield prima.astype(np.uint8)
            for j in range(1, volte):
                mezzo = prima + (dopo - prima) * j / volte + self.sbaglio
                yield np.clip(np.rint(mezzo), 0, 255).astype(np.uint8)
        for _ in range(volte):
            yield quadri[-1].astype(np.uint8)

    def spegni(self):
        self.spento += 1


class _NonCiSta(Exception):
    pass


def _gara_finta(tmp_path, monkeypatch):
    monkeypatch.setattr(corsa, "_clip_xtest", lambda: [])
    nomi = {}
    for numero in range(1, 200):
        nome = f"s/a/{numero:05d}.png"
        posto = tmp_path / "dati" / sc.SNU / nome
        posto.parent.mkdir(parents=True, exist_ok=True)
        Image.fromarray(np.full((16, 16, 3), numero, np.uint8)).save(posto)
        nomi[nome] = ("0" * 64, 1)
    presenti, veri_nomi = g.presenti_da_nomi(nomi)
    casi = [g.Caso("s/a/000100/p8x4", g.DIFFICILE, "s/a", 8, 4, None,
                   *g.finestra(100, 8, 4)),
            g.Caso("s/a/000100/p16x4/buio", g.DIFFICILISSIMO, "s/a", 16, 4, "buio",
                   *g.finestra(100, 16, 4))]
    elenco = sc.Elenco(casi, nomi, veri_nomi, presenti)
    corsa.scrivi_piano(tmp_path / "dati", elenco, {})
    return tmp_path / "dati", tmp_path / "risultati"


def test_indice_trova_il_posto_nell_uscita():
    caso = g.Caso("x", g.DIFFICILE, "s", 8, 4, None, (88, 96, 104, 112), (98, 100, 102))
    assert [corsa.indice(caso, v) for v in caso.veri] == [(5, 4), (6, 4), (7, 4)]
    caso = g.Caso("x", g.DIFFICILISSIMO, "s", 32, 4, None, (0, 32), (8, 16, 24))
    assert [corsa.indice(caso, v)[0] for v in caso.veri] == [1, 2, 3]
    with pytest.raises(ValueError):
        corsa.indice(caso, 40)


def test_piano_si_rilegge_uguale(tmp_path, monkeypatch):
    dati, _ = _gara_finta(tmp_path, monkeypatch)
    piano = corsa.leggi_piano(dati)
    assert [c.nome for c in piano.casi] == ["s/a/000100/p8x4", "s/a/000100/p16x4/buio"]
    assert piano.casi[0].tenuti == (88, 96, 104, 112)
    prendi = corsa.prendi_per(dati, piano, piano.casi[0])
    assert int(prendi(96)[0, 0, 0]) == 96


def test_corsa_intera_e_classifica(tmp_path, monkeypatch):
    dati, risultati = _gara_finta(tmp_path, monkeypatch)
    gimm, ldf = _MotoreFinto("g", sbaglio=3), _MotoreFinto("l", sbaglio=0)
    visti = []
    registro = corsa.corri(dati, risultati, gimm, ldf,
                           al_caso=lambda f, a, b: visti.append((f, a, b)))
    assert visti[-1] == (corsa.LDF, 4, 4)
    assert gimm.spento == 1 and ldf.spento == 1
    piano = corsa.leggi_piano(dati)
    esito = corsa.classifiche(registro, piano.casi)
    assert esito["tutto"]["primo"] in (corsa.LDF, corsa.FUSIONE)
    assert esito["tutto"]["medie"][corsa.GIMM]["casi"] == 2
    assert esito["difficilissimi"]["medie"][corsa.GIMM]["casi"] == 1


def test_corsa_riprende_senza_rifare(tmp_path, monkeypatch):
    dati, risultati = _gara_finta(tmp_path, monkeypatch)
    gimm, ldf = _MotoreFinto("g"), _MotoreFinto("l")
    fatti = []
    corsa.corri(dati, risultati, gimm, ldf, fermati=lambda: len(fatti) >= 1,
                al_caso=lambda *a: fatti.append(a))
    assert gimm.chiamate == 1 and ldf.chiamate == 0
    gimm2, ldf2 = _MotoreFinto("g"), _MotoreFinto("l")
    corsa.corri(dati, risultati, gimm2, ldf2)
    assert gimm2.chiamate == 1 and ldf2.chiamate == 2


def test_corsa_ricomincia_se_cambia_un_modello(tmp_path, monkeypatch):
    dati, risultati = _gara_finta(tmp_path, monkeypatch)
    corsa.corri(dati, risultati, _MotoreFinto("g"), _MotoreFinto("l"))
    nuovo = _MotoreFinto("g2")
    corsa.corri(dati, risultati, nuovo, _MotoreFinto("l"))
    assert nuovo.chiamate == 2


def test_ldf_che_non_ci_sta_conta_come_zero(tmp_path, monkeypatch):
    dati, risultati = _gara_finta(tmp_path, monkeypatch)
    registro = corsa.corri(dati, risultati, _MotoreFinto("g"),
                           _MotoreFinto("l", non_ci_sta=_NonCiSta),
                           non_ci_sta=(_NonCiSta,))
    piano = corsa.leggi_piano(dati)
    esito = corsa.classifica(registro, piano.casi)
    assert esito["medie"][corsa.LDF]["non_riusciti"] == 2
    assert esito["medie"][corsa.LDF]["somiglianza"] == 0.0
    assert esito["primo"] == corsa.GIMM


def _registro_con(tmp_path, medie: dict[str, dict]):
    caso = g.Caso("c", g.DIFFICILISSIMO, "s", 8, 4, None, (1, 9), (3,))
    registro = corsa.Risultati(tmp_path)
    registro.ricomincia({"x": 1})
    registro.aggiungi({"fase": corsa.GIMM, "nome": "c", "secondi": 1,
                       "voti": [medie[corsa.GIMM]]})
    registro.aggiungi({"fase": corsa.LDF, "nome": "c", "secondi": 2, "fondere": 0.1,
                       "voti": [medie[corsa.LDF]], "voti_fusione": [medie[corsa.FUSIONE]]})
    return registro, [caso]


def test_primo_solo_con_due_misure_su_tre(tmp_path):
    def v(a, b, c):
        return {"somiglianza": a, "struttura": b, "zona_peggiore": c}

    registro, casi = _registro_con(tmp_path, {corsa.GIMM: v(30, 0.9, 20),
                                              corsa.LDF: v(31, 0.8, 19),
                                              corsa.FUSIONE: v(29, 0.85, 21)})
    esito = corsa.classifica(registro, casi)
    assert esito["vincitori"] == {"somiglianza": corsa.LDF, "struttura": corsa.GIMM,
                                  "zona_peggiore": corsa.FUSIONE}
    assert esito["primo"] is None
    registro, casi = _registro_con(tmp_path, {corsa.GIMM: v(30, 0.9, 20),
                                              corsa.LDF: v(31, 0.95, 19),
                                              corsa.FUSIONE: v(29, 0.85, 21)})
    assert corsa.classifica(registro, casi)["primo"] == corsa.LDF


def test_risultati_ignorano_una_riga_tagliata(tmp_path):
    registro = corsa.Risultati(tmp_path)
    registro.ricomincia({"x": 1})
    registro.aggiungi({"fase": corsa.GIMM, "nome": "a"})
    with open(tmp_path / corsa.RISULTATI, "a", encoding="utf-8") as uscita:
        uscita.write('{"fase": "gimm", "nom')
    di_nuovo = corsa.Risultati(tmp_path)
    assert list(di_nuovo.fatti(corsa.GIMM)) == ["a"]
    di_nuovo.aggiungi({"fase": corsa.GIMM, "nome": "b"})
    assert list(corsa.Risultati(tmp_path).fatti(corsa.GIMM)) == ["a", "b"]


def _registro_per_scegliere(tmp_path, casi, scarti, non_riusciti=()):
    registro = corsa.Risultati(tmp_path)
    registro.ricomincia({"x": 1})
    for caso, scarto in zip(casi, scarti):
        buono = {"somiglianza": 30.0, "struttura": 0.9, "zona_peggiore": 20.0}
        altro = {"somiglianza": 30.0 + scarto, "struttura": 0.9, "zona_peggiore": 20.0}
        registro.aggiungi({"fase": corsa.GIMM, "nome": caso.nome, "secondi": 1,
                           "voti": [buono]})
        if caso.nome in non_riusciti:
            registro.aggiungi({"fase": corsa.LDF, "nome": caso.nome, "non_riuscito": True})
        else:
            registro.aggiungi({"fase": corsa.LDF, "nome": caso.nome, "secondi": 1,
                               "fondere": 0, "voti": [altro], "voti_fusione": [buono]})
    return registro


def test_voto_sceglie_solo_difficilissimi_snu_e_due_per_scena(tmp_path):
    casi = [g.Caso(f"a/{k}", g.DIFFICILISSIMO, "a", 16, 4, "buio") for k in range(3)]
    casi += [g.Caso("b/0", g.DIFFICILISSIMO, "b", 16, 4, "rumore"),
             g.Caso("c/0", g.DIFFICILE, "c", 8, 4),
             g.Caso("xtest/z/p32x4", g.DIFFICILISSIMO, "xtest/z", 32, 4),
             g.Caso("d/0", g.DIFFICILISSIMO, "d", 16, 4, "buio")]
    registro = _registro_per_scegliere(tmp_path, casi, [9, 8, 7, 1, 50, 50, 40],
                                       non_riusciti={"d/0"})
    scelti = voto.scegli(registro, casi, quanti=20)
    assert [c.nome for c in scelti] == ["a/0", "a/1", "b/0"]
    assert [c.nome for c in voto.scegli(registro, casi, quanti=2)] == ["a/0", "a/1"]
    rifiuta = voto.scegli(registro, casi, adatto=lambda c: c.nome != "a/0")
    assert [c.nome for c in rifiuta] == ["a/1", "a/2", "b/0"]


def test_clip_resta_dentro_i_fotogrammi():
    caso = g.Caso("s/a/1000/p16x4/buio", g.DIFFICILISSIMO, "s/a", 16, 4, "buio",
                  *g.finestra(1000, 16, 4))
    clip = voto.clip_di(caso, set(range(1, 5000)))
    assert clip.tenuti[1] - clip.tenuti[0] == 8 and clip.passo == 8
    assert set(caso.tenuti) <= set(clip.tenuti)
    assert clip.veri[1] - clip.veri[0] == 2
    assert voto.velocita(clip) == 120
    assert (clip.tenuti[0], clip.tenuti[-1]) == (clip.veri[0], clip.veri[-1])
    assert clip.tenuti[-1] - clip.tenuti[0] <= 480
    assert len(clip.veri) == (len(clip.tenuti) - 1) * 4 + 1
    assert clip.rovina == "buio" and clip.nome == caso.nome
    vicino = voto.clip_di(caso, set(range(950, 1200)))
    assert min(vicino.tenuti) >= 950 and max(vicino.tenuti) < 1200
    assert voto.clip_di(caso, set(range(990, 1040))) is None


def test_clip_mosso_lascia_posto_all_otturatore():
    caso = g.Caso("s/a/1000/p8x4/mosso", g.DIFFICILISSIMO, "s/a", 8, 4, g.MOSSO,
                  *g.finestra(1000, 8, 4))
    clip = voto.clip_di(caso, set(range(900, 1100)))
    assert min(clip.tenuti) + g.OTTURATORE[0] >= 900
    assert max(clip.tenuti) + g.OTTURATORE[1] < 1100


def _clip_finta(rovinato=None):
    return g.Caso("s/a/100/p8x4", g.DIFFICILISSIMO, "s/a", 8, 4, rovinato,
                  tuple(range(80, 144, 8)), tuple(range(80, 137, 2)))


def _prendi(numero):
    quadro = np.zeros((32, 48, 3), np.uint8)
    quadro[:, :, 0] = numero % 256
    quadro[:, (numero % 40):(numero % 40) + 8, 1] = 200
    return quadro


def test_fai_clip_scrive_i_video_e_si_riprende(tmp_path):
    clip = [_clip_finta(), _clip_finta("buio")]
    gimm, ldf = _MotoreFinto("g", sbaglio=2), _MotoreFinto("l")
    visti = []
    voto.fai_clip(tmp_path, clip, lambda c: _prendi, gimm, ldf,
                  al_clip=lambda a, b: visti.append((a, b)),
                  fermati=lambda: len(visti) >= 3)
    assert not voto.clip_pronte(tmp_path)
    (tmp_path / voto.CARTELLA).mkdir(exist_ok=True)
    (tmp_path / voto.CARTELLA / voto.CLIP).write_text(g.testo_casi(clip), encoding="utf-8")
    gimm2, ldf2 = _MotoreFinto("g"), _MotoreFinto("l")
    voto.fai_clip(tmp_path, clip, lambda c: _prendi, gimm2, ldf2)
    assert gimm2.chiamate == 0 and ldf2.chiamate == 1
    assert voto.clip_pronte(tmp_path)
    assert voto.leggi_clip(tmp_path) == clip
    import av

    for numero in range(2):
        casa = tmp_path / voto.CARTELLA / f"{numero:02d}"
        assert not (casa / "gimm.npz").exists()
        for nome in (*corsa.CONCORRENTI, voto.VERO):
            with av.open(str(casa / f"{nome}.mp4")) as dentro:
                flusso = dentro.streams.video[0]
                assert sum(1 for _ in dentro.decode(flusso)) == 29
                assert round(float(flusso.average_rate)) == 120
        assert voto.secondi_di(tmp_path, numero, corsa.FUSIONE) is not None


def test_voto_cieco_e_vero_dopo(tmp_path):
    (tmp_path / voto.CARTELLA).mkdir()
    prima = voto.lettere(tmp_path, 0, random.Random(1))
    assert sorted(prima["lettere"].values()) == sorted(corsa.CONCORRENTI)
    assert voto.lettere(tmp_path, 0, random.Random(2)) == prima
    with pytest.raises(PermissionError):
        voto.video_di(tmp_path, 0, None)
    scelto = prima["lettere"]["B"]
    assert voto.video_di(tmp_path, 0, "B").name == f"{scelto}.mp4"
    voto.vota(tmp_path, 0, "B", 12.34)
    voto.vota(tmp_path, 0, "A")
    assert voto.video_di(tmp_path, 0, None).name == f"{voto.VERO}.mp4"
    conto = voto.conto(tmp_path, 2)
    assert conto["punti"][scelto] == 1 and conto["votati"] == 1 and conto["primo"] is None
    voto.lettere(tmp_path, 1, random.Random(3))
    seconda = voto.lettere(tmp_path, 1)
    lettera = next(k for k, v in seconda["lettere"].items() if v == scelto)
    voto.vota(tmp_path, 1, lettera)
    assert voto.conto(tmp_path, 2)["primo"] == scelto
    with pytest.raises(KeyError):
        voto.vota(tmp_path, 5, "A")


def test_vincitore_solo_se_d_accordo():
    assert voto.vincitore(corsa.LDF, corsa.LDF) == corsa.LDF
    assert voto.vincitore(corsa.LDF, corsa.GIMM) is None
    assert voto.vincitore(None, corsa.GIMM) is None


def test_stanza_fa_la_corsa_e_le_clip_senza_rete(tmp_path, monkeypatch):
    from officina.miglioria import gara120_stanza as stanza
    from officina.miglioria import rete

    chiusa = []
    monkeypatch.setattr(rete, "chiudi", lambda: chiusa.append(1))
    dati, risultati = _gara_finta(tmp_path, monkeypatch)
    messaggi = []

    def motori(lavoro):
        return _MotoreFinto("g", sbaglio=2), _MotoreFinto("l"), (_NonCiSta,)

    lavoro = {"azione": "corsa", "dati": str(dati), "risultati": str(risultati)}
    assert stanza.un_lavoro(lavoro, messaggi.append, motori) == 0
    assert chiusa == [1]
    assert messaggi[-1] == {"fatto": {"azione": "corsa", "gimm": 2, "ldf": 2}}
    assert {"fatti": 4, "totale": 4, "fase": corsa.LDF} in messaggi
    piano = corsa.leggi_piano(dati)
    elenco = sc.Elenco(piano.casi, {}, {("s/a", n): f"s/a/{n:05d}.png"
                                        for n in range(1, 200)}, {"s/a": set(range(1, 200))})
    registro = corsa.Risultati(risultati)
    clip = voto.prepara_voto(risultati, registro, elenco, piano)
    assert [c.nome for c in clip] == ["s/a/000100/p16x4/buio"]
    nomi = voto.nomi_del_voto(clip, elenco)
    assert nomi[0] == f"s/a/{clip[0].tenuti[0]:05d}.png" and len(nomi) == len(clip[0].veri)
    assert clip[0].passo == 8 and min(clip[0].tenuti) >= 1
    messaggi.clear()
    lavoro["azione"] = "clip"
    assert stanza.un_lavoro(lavoro, messaggi.append, motori) == 0
    assert messaggi[-1] == {"fatto": {"azione": "clip", "pronte": True}}
    assert messaggi[-2] == {"fatti": 2, "totale": 2}


def test_stanza_dice_il_guasto(tmp_path, monkeypatch):
    from officina.miglioria import gara120_stanza as stanza
    from officina.miglioria import rete

    monkeypatch.setattr(rete, "chiudi", lambda: None)
    messaggi = []
    assert stanza.un_lavoro({"azione": "boh"}, messaggi.append) == 2
    assert messaggi == [{"guasto": "azione_sconosciuta"}]

    def rotti(lavoro):
        raise RuntimeError("niente")

    messaggi.clear()
    lavoro = {"azione": "corsa", "dati": str(tmp_path), "risultati": str(tmp_path)}
    assert stanza.un_lavoro(lavoro, messaggi.append, rotti) == 1
    assert messaggi[-1]["guasto"] == "rotto"


def _regista(tmp_path, monkeypatch, motori=None, fermati_dopo=None):
    from officina.miglioria import gara120
    from officina.miglioria import gara120_stanza as stanza
    from officina.miglioria import rete
    from officina.web.lavori import TurnoDellaScheda

    monkeypatch.setattr(rete, "chiudi", lambda: None)
    dati, _ = _gara_finta(tmp_path, monkeypatch)
    piano = corsa.leggi_piano(dati)
    elenco = sc.Elenco(piano.casi, {}, {("s/a", n): f"s/a/{n:05d}.png"
                                        for n in range(1, 200)}, {"s/a": set(range(1, 200))})
    scaricati = []
    monkeypatch.setattr(sc, "elenco_snu", lambda *a, **k: elenco)
    monkeypatch.setattr(sc, "scarica_snu",
                        lambda cartella, el, nomi, *_: scaricati.append(nomi))
    monkeypatch.setattr(sc, "scarica_xvfi", lambda *a, **k: None)
    monkeypatch.setattr(sc, "cartelle_adobe", lambda cartella: {})
    azioni = []

    def lancia(lavoro, al_passo):
        azioni.append(lavoro["azione"])
        messaggi = []
        stanza.un_lavoro(lavoro, messaggi.append, motori or (
            lambda _: (_MotoreFinto("g", sbaglio=2), _MotoreFinto("l"), (_NonCiSta,))))
        if fermati_dopo is not None and len(azioni) == fermati_dopo:
            gara.ferma()
        return messaggi[-1]

    archivio = SimpleNamespace(dove=SimpleNamespace(modelli=tmp_path))
    gara = gara120.Gara120(archivio, cartella=tmp_path, lancia=lancia,
                           turno=TurnoDellaScheda())
    return gara, azioni, scaricati


def test_regista_fa_tutto_fino_al_voto(tmp_path, monkeypatch):
    from officina.miglioria import gara120

    gara, azioni, scaricati = _regista(tmp_path, monkeypatch)
    assert gara.fase() == gara120.CORSA
    gara._gira()
    assert azioni == ["corsa", "clip"]
    assert len(scaricati) == 2 and scaricati[1][0].startswith("s/a/")
    assert gara.fase() == gara120.VOTO
    assert gara.turno.chi is None
    esito = gara.esito()
    assert esito["automatico"] == esito["classifiche"]["difficilissimi"]["primo"]
    assert esito["vincitore"] is None and not esito["decidiamo_insieme"]
    lettere = voto.lettere(tmp_path / "risultati", 0)
    scelta = next(k for k, v in lettere["lettere"].items() if v == esito["automatico"])
    voto.vota(tmp_path / "risultati", 0, scelta)
    assert gara.fase() == gara120.VOTATA
    assert gara.esito()["vincitore"] == esito["automatico"]
    assert gara.occupa() > 0
    assert gara.cancella_i_dati() > 0 and gara.occupa() == 0
    assert voto.clip_pronte(tmp_path / "risultati")


def test_regista_fermato_riprende(tmp_path, monkeypatch):
    from officina.miglioria import gara120

    gara, azioni, _ = _regista(tmp_path, monkeypatch, fermati_dopo=1)
    gara._gira()
    assert azioni == ["corsa"]
    assert any("riprende" in riga for riga in gara.lavoro.righe)
    assert gara.fase() == gara120.CLIP
    gara._fermati.clear()
    gara._gira()
    assert azioni == ["corsa", "corsa", "clip"]
    assert gara.fase() == gara120.VOTO


def test_regista_dice_il_guasto_della_stanza(tmp_path, monkeypatch):
    from officina.errori import ErroreOfficina

    def rotti(lavoro):
        raise MemoryError()

    gara, _, _ = _regista(tmp_path, monkeypatch, motori=rotti)
    with pytest.raises(ErroreOfficina) as preso:
        gara._gira()
    assert preso.value.codice == "memoria_finita"
    assert gara.turno.chi is None


def test_regista_aspetta_la_scheda(tmp_path, monkeypatch):
    from officina.miglioria import gara120
    from officina.web.lavori import Lavoro

    gara, azioni, _ = _regista(tmp_path, monkeypatch)
    altro = Lavoro("altro")
    assert gara.turno.prendi_se_libera(altro)
    monkeypatch.setattr(gara120, "ASPETTA_LA_SCHEDA", 0.01)
    detto = gara.lavoro.di

    def di(riga):
        detto(riga)
        if "scheda" in riga:
            gara.ferma()

    gara.lavoro.di = di
    gara._gira()
    assert azioni == []
    assert "aspetto che la scheda si liberi" in gara.lavoro.righe
    assert gara.turno.chi is altro
