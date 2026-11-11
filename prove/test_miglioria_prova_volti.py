from __future__ import annotations

import hashlib
import io
import struct
import zlib
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from officina.miglioria import motori, prova_volti, veloce
from officina.miglioria import prova_veloce_corsa as corsa

QUI = "prove.test_miglioria_prova_volti"
SEED = "prove.test_miglioria_giro_lucidflux:FintoSeed"
LAVORO = {"motori": {"video": "finto"}}


class FintoVolti:

    nome = "volti-finti"
    versione = "1"
    creati = 0
    parcheggiati = 0
    sporco = False

    def __init__(self, **_opzioni) -> None:
        type(self).creati += 1
        self.usi = 0

    def sistema(self, immagine, persone=None):
        self.usi += 1
        fatta = immagine.copy()
        fatta.paste((250, 0, 0) if persone else (0, 0, 250), (0, 0, 16, 16))
        if type(self).sporco and self.usi > 1:
            fatta.paste((0, 250, 0), (16, 16, 32, 32))
        return fatta

    def parcheggia(self) -> int:
        type(self).parcheggiati += 1
        return 100

    def spegni(self) -> None:
        pass


class FintoFaceMe(FintoVolti):
    creati = 0
    parcheggiati = 0
    sporco = False


@pytest.fixture
def finti(monkeypatch):
    monkeypatch.setitem(motori.FOTO, motori.SEEDVR2, SEED)
    monkeypatch.setitem(motori.VOLTI, motori.CODEFORMER, f"{QUI}:FintoVolti")
    monkeypatch.setitem(motori.VOLTI, motori.FACEME, f"{QUI}:FintoFaceMe")
    monkeypatch.setattr(motori, "_accesi", {})
    monkeypatch.setattr(motori, "_parcheggiati", {})
    for classe in (FintoVolti, FintoFaceMe):
        monkeypatch.setattr(classe, "creati", 0)
        monkeypatch.setattr(classe, "parcheggiati", 0)
        monkeypatch.setattr(classe, "sporco", False)


def _jpg(seme: int) -> bytes:
    quadro = np.random.default_rng(seme).integers(0, 256, (48, 64, 3), dtype=np.uint8)
    dentro = io.BytesIO()
    Image.fromarray(quadro).save(dentro, "PNG")
    return dentro.getvalue()


def _voce(nome: str, dati: bytes, inizio: int) -> tuple[dict, bytes]:
    stretto = zlib.compressobj(9, zlib.DEFLATED, -15)
    compressi = stretto.compress(dati) + stretto.flush()
    nome_dentro = f"WIDER_val/images/x/{nome}.jpg"
    testa = (prova_volti.SEGNO + struct.pack("<HHHHHIIIHH", 20, 0, 8, 0, 0, 0,
                                             len(compressi), len(dati),
                                             len(nome_dentro), 4)
             + nome_dentro.encode() + b"\x00" * 4)
    voce = {"nome": nome, "voce": nome_dentro, "inizio": inizio,
            "compressi": len(compressi), "byte": len(dati), "misura": (64, 48),
            "sha256": hashlib.sha256(dati).hexdigest(), "volti": ((8, 8, 16, 16),)}
    return voce, testa + compressi


@pytest.fixture
def zip_finto(monkeypatch):
    archivio = b""
    voci = []
    for numero, nome in enumerate(("uno", "due", "tre")):
        voce, pezzo = _voce(nome, _jpg(numero), len(archivio) + 7)
        archivio += b"\x01" * 7 + pezzo
        voci.append(voce)
    archivio += b"\x02" * 900
    monkeypatch.setattr(prova_volti, "FOTO", tuple(voci))
    chieste = []

    def rete(inizio: int, quanti: int) -> bytes:
        chieste.append((inizio, quanti))
        return archivio[inizio:inizio + quanti]

    return rete, chieste


def test_le_sei_foto_vere_sono_scritte_bene():
    assert len(prova_volti.FOTO) == 6
    assert len({voce["nome"] for voce in prova_volti.FOTO}) == 6
    for voce in prova_volti.FOTO:
        assert len(voce["sha256"]) == 64 and voce["voce"].endswith(".jpg")
        assert voce["inizio"] + voce["compressi"] < prova_volti.ARCHIVIO_BYTE
        for riquadro in prova_volti.riquadri(voce):
            assert all(0 <= valore <= 1 for valore in riquadro)
    assert prova_volti.REVISIONE in prova_volti.indirizzo()


def test_scarica_solo_i_pezzi_e_li_controlla(tmp_path, zip_finto):
    rete, chieste = zip_finto
    passi = []
    fatte = prova_volti.scarica(tmp_path, lambda f, t: passi.append((f, t)), rete)
    assert [uno["nome"] for uno in fatte] == ["uno", "due", "tre"]
    assert passi[-1] == (3, 3) and len(chieste) == 3
    for uno, voce in zip(fatte, prova_volti.FOTO):
        dati = Path(uno["file"][0]).read_bytes()
        assert hashlib.sha256(dati).hexdigest() == voce["sha256"]
        assert uno["persone"][0]["riferimenti"][0]["file"] == uno["file"][0]
        assert uno["persone"][0]["riquadri"] == [[0.125, 8 / 48, 0.25, 16 / 48]]
    prova_volti.scarica(tmp_path, None, rete)
    assert len(chieste) == 3


def test_una_foto_rovinata_sul_disco_si_riscarica(tmp_path, zip_finto):
    rete, chieste = zip_finto
    fatte = prova_volti.scarica(tmp_path, None, rete)
    Path(fatte[1]["file"][0]).write_bytes(b"rotta")
    prova_volti.scarica(tmp_path, None, rete)
    assert len(chieste) == 4


def test_un_pezzo_sbagliato_non_entra(tmp_path, zip_finto):
    rete, _ = zip_finto

    def spostata(inizio: int, quanti: int) -> bytes:
        return rete(inizio + 1, quanti)

    with pytest.raises(prova_volti.VoltiSbagliati):
        prova_volti.scarica(tmp_path, None, spostata)
    assert not list((tmp_path / prova_volti.CARTELLA).glob("*.jpg"))

    def cambiata(inizio: int, quanti: int) -> bytes:
        pezzo = bytearray(rete(inizio, quanti))
        pezzo[60] ^= 1
        return bytes(pezzo)

    with pytest.raises(prova_volti.VoltiSbagliati):
        prova_volti.scarica(tmp_path, None, cambiata)
    assert not list((tmp_path / prova_volti.CARTELLA).glob("*.jpg"))


def _volti(tmp_path: Path, rete) -> list[dict]:
    return prova_volti.scarica(tmp_path / "dati", None, rete)


def test_i_volti_passano_e_accendono_le_due_idee(tmp_path, finti, zip_finto):
    volti = _volti(tmp_path, zip_finto[0])
    passi = []
    dati = corsa.corri(tmp_path / "prova", [], LAVORO, volte=2, volti=volti,
                       al_passo=lambda f, t: passi.append((f, t)),
                       quali_volti=[motori.CODEFORMER, motori.FACEME])
    assert passi[-1] == (2 * 3 * 4 + 4, 2 * 3 * 4 + 4)
    assert dati["passata"], dati
    assert dati["idee"] == [veloce.VOLTI_ACCESI, veloce.FACEME_ACCESO,
                            veloce.IMPRONTE_FILI]
    assert len(dati["volti"]) == 6 and all(riga["uguale"] for riga in dati["volti"])
    assert FintoVolti.creati == 2 * 3 + 2 and FintoVolti.parcheggiati == 2 * 3
    assert FintoFaceMe.creati == 2 * 3 + 2
    faceme = [riga for riga in dati["volti"] if riga["nome"].startswith("faceme-")]
    codeformer = [riga for riga in dati["volti"] if riga["nome"].startswith("codeformer-")]
    assert faceme[0]["vecchi"][0] != codeformer[0]["vecchi"][0]

    def mai(*_argomenti, **_chiavi):
        raise AssertionError("rifatto")

    corsa_vera = corsa._una_foto
    try:
        corsa._una_foto = mai
        assert corsa.corri(tmp_path / "prova", [], LAVORO, volte=2, volti=volti,
                           quali_volti=[motori.CODEFORMER, motori.FACEME])["passata"]
    finally:
        corsa._una_foto = corsa_vera


def test_se_il_motore_tenuto_cambia_un_pixel_l_idea_resta_spenta(tmp_path, finti,
                                                                zip_finto, monkeypatch):
    volti = _volti(tmp_path, zip_finto[0])
    monkeypatch.setattr(FintoFaceMe, "sporco", True)
    dati = corsa.corri(tmp_path / "prova", [], LAVORO, volte=2, volti=volti,
                       quali_volti=[motori.CODEFORMER, motori.FACEME])
    assert not dati["passata"]
    assert dati["idee"] == [veloce.VOLTI_ACCESI, veloce.IMPRONTE_FILI]


def test_senza_motori_dei_volti_la_parte_si_salta(tmp_path, finti, zip_finto):
    volti = _volti(tmp_path, zip_finto[0])
    dati = corsa.corri(tmp_path / "prova", [], LAVORO, volte=2, volti=volti,
                       quali_volti=[])
    assert dati["volti"] == [] and dati["idee"] == [veloce.IMPRONTE_FILI]
    assert FintoVolti.creati == 0


def test_i_fili_vedono_un_ritaglio_diverso(tmp_path, zip_finto, monkeypatch):
    volti = _volti(tmp_path, zip_finto[0])
    file = corsa.file_per_i_fili([], [], volti)
    assert len(file) == 3
    uno = corsa.un_giro_di_fili(file, 0, corsa.VECCHIO)
    due = corsa.un_giro_di_fili(file, 1, corsa.NUOVO)
    assert uno["impronta"] == due["impronta"]
    assert corsa.un_giro_di_fili(file[::-1], 1, corsa.NUOVO)["impronta"] != uno["impronta"]
    assert corsa.file_per_i_fili([{"file": ["a.heic", "b.PNG"]}], [], []) == ["b.PNG"]
