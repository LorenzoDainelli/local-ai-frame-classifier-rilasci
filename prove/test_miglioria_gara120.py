from __future__ import annotations

import hashlib
import io
import tarfile
import zipfile
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image

from officina.descrittori.scaricamento import ScaricamentoFallito
from officina.miglioria import gara120_casi as g
from officina.miglioria import gara120_fonti as fonti
from officina.miglioria import gara120_rovina as rovina
from officina.miglioria import gara120_scarica as sc
from officina.miglioria import gara120_voti as voti


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
