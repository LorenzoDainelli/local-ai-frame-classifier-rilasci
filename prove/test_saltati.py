from __future__ import annotations

import re
from pathlib import Path

import pytest

from officina.errori import MOTIVO_SENZA_FRASE, PERCHE_SALTATO, perche_saltato

RADICE = Path(__file__).resolve().parent.parent
CODICE = re.compile(r'codice=["\']([a-z_]+)["\']')
A_MANO = re.compile(r'saltati\.append\(\([^,]+,\s*["\']([a-z_]+)["\']\)\)')


DA_DOVE_ARRIVANO = (
    "officina/impronte/motore.py",
    "officina/parole/motore.py",
    "officina/immagini/lettura.py",
    "officina/immagini/fotogrammi.py",
)


def _tutti_i_codici() -> dict[str, set[str]]:
    trovati: dict[str, set[str]] = {}
    for nome in DA_DOVE_ARRIVANO:
        sorgente = RADICE / nome
        testo = sorgente.read_text(encoding="utf-8")
        for espressione in (CODICE, A_MANO):
            for codice in espressione.findall(testo):
                trovati.setdefault(codice, set()).add(nome)
    return trovati


def test_ogni_codice_di_scarto_ha_una_frase_in_italiano():
    senza = {}
    for codice, dove in _tutti_i_codici().items():
        if codice not in PERCHE_SALTATO:
            senza[codice] = sorted(dove)
    assert not senza, (
        "Questi codici possono finire sotto la barra e non hanno una frase in "
        "italiano in PERCHE_SALTATO (officina/errori.py): " + repr(senza))


def test_un_codice_sconosciuto_non_arriva_mai_grezzo_sullo_schermo():
    frase = perche_saltato("qualcosa_di_mai_visto_prima")
    assert frase == MOTIVO_SENZA_FRASE
    assert "qualcosa_di_mai_visto_prima" not in frase


@pytest.mark.parametrize("codice,frase", sorted(PERCHE_SALTATO.items()))
def test_le_frasi_sono_in_italiano_e_minuscole(codice, frase):
    assert frase[0].islower(), codice
    assert not frase.endswith("."), codice
    assert codice not in frase, f"{codice}: la frase ripete il codice"


def test_il_codice_che_ha_fatto_nascere_questa_prova_non_esiste_piu():
    assert "video_senza_decodificatore" not in _tutti_i_codici()


def test_un_video_senza_indice_lo_dice_e_non_incolpa_il_decodificatore(tmp_path):
    from officina.immagini import fotogrammi

    if not fotogrammi.c_e_il_decodificatore():
        pytest.skip("senza PyAV il guasto è un altro, ed è quello giusto")

    monco = tmp_path / "interrotto.mp4"
    monco.write_bytes(
        bytes([0, 0, 0, 0x18]) + b"ftypmp42" + bytes(16) + bytes(4096))

    resa = fotogrammi.prendi(monco)

    assert not resa
    assert resa.codice == "video_senza_indice"
    assert "indice" in resa.motivo
    assert "pip install" not in resa.motivo
    assert resa.codice in PERCHE_SALTATO


def test_senza_decodificatore_il_motivo_e_ancora_quello_giusto(tmp_path, monkeypatch):
    from officina.immagini import fotogrammi

    monkeypatch.setattr(fotogrammi, "c_e_il_decodificatore", lambda: False)
    video = tmp_path / "qualsiasi.mp4"
    video.write_bytes(bytes([0, 0, 0, 0x18]) + b"ftypmp42" + bytes(16))

    resa = fotogrammi.prendi(video)

    assert resa.codice == "manca_decodificatore"
    assert "pip install" in resa.motivo
    assert resa.codice in PERCHE_SALTATO


def test_un_segnaposto_della_nuvola_non_e_un_video_rotto(tmp_path):
    from officina.immagini import fotogrammi

    if not fotogrammi.c_e_il_decodificatore():
        pytest.skip("serve PyAV per arrivare fin qui")

    segnaposto = tmp_path / "ancora_nella_nuvola.mp4"
    segnaposto.write_bytes(b"")

    resa = fotogrammi.prendi(segnaposto)

    assert resa.codice == "vuoto"
    assert "nuvola" in resa.motivo
    assert resa.codice in PERCHE_SALTATO
