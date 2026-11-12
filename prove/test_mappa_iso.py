from __future__ import annotations

import io
import struct

import numpy as np
import pillow_heif
import pytest
from PIL import Image

from officina.miglioria import heif_scatole as hs

pillow_heif.register_heif_opener()

NASCOSTA = 1
METADATI = (bytes([0]) + struct.pack(">HHB", 0, 0, 0x40) + struct.pack(">IIII", 0, 1, 1, 1)
            + struct.pack(">iIiIIIiIiI", 0, 1, 1, 1, 1, 1, 1, 64, 1, 64))


def _heic(misura, seme, grigia=False) -> bytes:
    caso = np.random.default_rng(seme)
    forma = (misura[1], misura[0]) if grigia else (misura[1], misura[0], 3)
    uscita = io.BytesIO()
    Image.fromarray(caso.integers(0, 255, forma, dtype=np.uint8)).save(
        uscita, format="HEIF", quality=90)
    return uscita.getvalue()


def _avif(misura, seme) -> bytes:
    imagecodecs = pytest.importorskip("imagecodecs")
    caso = np.random.default_rng(seme)
    pixel = caso.integers(0, 1023, (misura[1], misura[0], 3), dtype=np.uint16)
    return imagecodecs.avif_encode(pixel, level=90, bitspersample=10)


def _ispe(larga: int, alta: int) -> bytes:
    return hs._piena(b"ispe", 0, 0, struct.pack(">II", larga, alta))


def _con_iso(base: bytes, mappa: bytes, girata: bytes | None = None,
             ferma: bool = False) -> bytes:
    a, m = hs.leggi(base), hs.leggi(mappa)
    guadagno, iso = max(a.voci) + 1, max(a.voci) + 2
    voci = dict(a.voci)
    voce = m.voci[m.primaria]
    voci[guadagno] = hs.Voce(guadagno, voce.tipo, voce.resto, 0, NASCOSTA)
    voci[iso] = hs.Voce(iso, hs.MAPPA_ISO, b"\0")
    contenuti = {n: (a.dove[n].metodo, hs.contenuto(a, n)) for n in a.dove}
    contenuti[guadagno] = (0, hs.contenuto(m, m.primaria))
    contenuti[iso] = (1, METADATI)
    proprieta = list(a.proprieta)
    legami = {n: list(u) for n, u in a.legami.items()}
    uniti = []
    for essenziale, indice in m.legami[m.primaria]:
        proprieta.append(m.proprieta[indice - 1])
        uniti.append((essenziale, len(proprieta)))
    legami[guadagno] = uniti
    larga, alta = hs._misura(a, a.primaria)
    proprieta.append(_ispe(larga, alta))
    legami[iso] = [(False, len(proprieta))]
    proprieta.append(hs._scatola(b"colr", b"nclx" + bytes([0, 12, 0, 16, 0, 1, 0x80])))
    legami[iso].append((False, len(proprieta)))
    if ferma:
        proprieta.append(hs._scatola(b"irot", b"\0"))
        for numero in (a.primaria, guadagno, iso):
            legami[numero].append((True, len(proprieta)))
    if girata is not None:
        proprieta.append(girata)
        legami[a.primaria].append((True, len(proprieta)))
        legami[iso].append((True, len(proprieta)))
    rimandi = list(a.rimandi) + [(hs.DERIVATA, iso, [a.primaria, guadagno])]
    gruppo = hs._piena(hs.ALTERNATIVE, 0, 0,
                       struct.pack(">IIII", iso + 1, 2, iso, a.primaria))
    pronta = hs.replace(a, ftyp=a.ftyp + hs.MAPPA_ISO,
                        altre=[*a.altre, hs.Scatola(hs.GRUPPI, gruppo)])
    return hs.scrivi(pronta, voci, contenuti, rimandi, proprieta, legami)


def _originale(**opzioni) -> bytes:
    return _con_iso(_heic((400, 300), 1), _heic((100, 75), 2, grigia=True), **opzioni)


def test_la_mappa_iso_passa_uguale_e_prende_la_misura_nuova():
    originale, migliorata = _originale(), _heic((800, 600), 3)
    nuova = hs.con_la_mappa_iso(migliorata, originale)
    assert nuova is not None and hs.controlla_iso(migliorata, nuova, originale)
    letta, vecchia = hs.leggi(nuova), hs.leggi(originale)
    [(iso, guadagno)] = hs.mappe_iso(letta)
    [(iso_prima, guadagno_prima)] = hs.mappe_iso(vecchia)
    assert hs.contenuto(letta, iso) == METADATI
    assert hs.contenuto(letta, guadagno) == hs.contenuto(vecchia, guadagno_prima)
    assert letta.voci[guadagno].bandiere == NASCOSTA
    assert hs._misura(letta, iso) == (800, 600)
    assert hs.MAPPA_ISO in letta.ftyp[8:]
    colori = hs._proprieta_di(letta, iso, (b"colr",))
    assert colori == hs._proprieta_di(vecchia, iso_prima, (b"colr",))
    gruppi = [s for s in letta.altre if s.tipo == hs.GRUPPI]
    assert len(gruppi) == 1
    corpo = gruppi[0].corpo
    assert corpo[4:8] == hs.ALTERNATIVE
    gruppo, quante, prima, seconda = struct.unpack(">IIII", corpo[12:28])
    assert (quante, prima, seconda) == (2, iso, letta.primaria)
    assert gruppo not in letta.voci
    assert np.array_equal(np.asarray(Image.open(io.BytesIO(nuova))),
                          np.asarray(Image.open(io.BytesIO(migliorata))))


def test_rimetti_scrive_la_mappa_iso_nel_file(tmp_path):
    originale, uscita = tmp_path / "a.heic", tmp_path / "b.heic"
    originale.write_bytes(_originale())
    uscita.write_bytes(_heic((800, 600), 3))
    assert hs.rimetti(originale, uscita) == ["tmap"]
    assert len(hs.mappe_iso(hs.leggi(uscita.read_bytes()))) == 1
    assert not list(tmp_path.glob("*.aux"))


def test_rimetti_la_mappa_iso_anche_negli_avif(tmp_path):
    originale, uscita = tmp_path / "a.avif", tmp_path / "b.avif"
    originale.write_bytes(_con_iso(_avif((400, 300), 1), _avif((100, 75), 2)))
    migliorata = _avif((800, 600), 3)
    uscita.write_bytes(migliorata)
    assert hs.rimetti(originale, uscita) == ["tmap"]
    dopo = uscita.read_bytes()
    assert len(hs.mappe_iso(hs.leggi(dopo))) == 1
    import imagecodecs

    assert np.array_equal(imagecodecs.avif_decode(dopo), imagecodecs.avif_decode(migliorata))


def test_girata_in_modo_diverso_non_si_copia_e_il_file_resta(tmp_path):
    originale, uscita = tmp_path / "a.heic", tmp_path / "b.heic"
    originale.write_bytes(_originale(girata=hs._scatola(b"irot", b"\1")))
    migliorata = _heic((800, 600), 3)
    uscita.write_bytes(migliorata)
    assert hs.rimetti(originale, uscita) == []
    assert uscita.read_bytes() == migliorata


def test_la_rotazione_a_zero_gradi_del_mac_non_ferma_la_mappa_iso(tmp_path):
    originale, uscita = tmp_path / "a.heic", tmp_path / "b.heic"
    originale.write_bytes(_originale(ferma=True))
    migliorata = _heic((800, 600), 3)
    uscita.write_bytes(migliorata)
    assert hs.rimetti(originale, uscita) == ["tmap"]
    dopo = uscita.read_bytes()
    letta = hs.leggi(dopo)
    [(iso, guadagno)] = hs.mappe_iso(letta)
    assert hs._proprieta_di(letta, iso, (b"irot",)) == [hs._scatola(b"irot", b"\0")]
    assert np.array_equal(np.asarray(Image.open(io.BytesIO(dopo))),
                          np.asarray(Image.open(io.BytesIO(migliorata))))


def test_mappa_di_forma_diversa_non_si_copia():
    originale = _con_iso(_heic((400, 300), 1), _heic((75, 100), 2, grigia=True))
    with pytest.raises(hs.ScatolaStrana):
        hs.con_la_mappa_iso(_heic((800, 600), 3), originale)


def test_se_la_mappa_iso_c_e_gia_non_si_tocca():
    originale = _originale()
    gia = hs.con_la_mappa_iso(_heic((800, 600), 3), originale)
    assert hs.con_la_mappa_iso(gia, originale) is None


def test_senza_mappa_iso_nulla_cambia(tmp_path):
    originale, uscita = tmp_path / "a.heic", tmp_path / "b.heic"
    originale.write_bytes(_heic((400, 300), 1))
    migliorata = _heic((800, 600), 3)
    uscita.write_bytes(migliorata)
    assert hs.rimetti(originale, uscita) == []
    assert uscita.read_bytes() == migliorata


def test_le_voci_nascoste_restano_nascoste():
    originale = _originale()
    letta = hs.leggi(originale)
    [(_, guadagno)] = hs.mappe_iso(letta)
    assert letta.voci[guadagno].bandiere == NASCOSTA
    di_nuovo = hs.leggi(hs.scrivi(letta, letta.voci,
                                  {n: (letta.dove[n].metodo, hs.contenuto(letta, n))
                                   for n in letta.dove},
                                  letta.rimandi, letta.proprieta, letta.legami))
    assert di_nuovo.voci == letta.voci
