from __future__ import annotations

import io

import numpy as np
import pillow_heif
import pytest
from PIL import Image

from officina.miglioria import fedelta
from officina.miglioria import heif_scatole as hs

pillow_heif.register_heif_opener()

MAPPA = "urn:com:apple:photo:2020:aux:hdrgainmap"
PROFONDITA = "urn:mpeg:hevc:2015:auxid:2"
ALFA = "urn:mpeg:hevc:2015:auxid:1"


def _heic(immagine, **opzioni) -> bytes:
    uscita = io.BytesIO()
    immagine.save(uscita, format="HEIF", quality=90, **opzioni)
    return uscita.getvalue()


def _caso(misura, seme=0, grigia=False):
    caso = np.random.default_rng(seme)
    alto, largo = misura[1], misura[0]
    forma = (alto, largo) if grigia else (alto, largo, 3)
    return Image.fromarray(caso.integers(0, 255, forma, dtype=np.uint8))


def _con(base: bytes, mappa: bytes, urn: str, metodo: int = 0) -> bytes:
    a, m = hs.leggi(base), hs.leggi(mappa)
    nuovo = max(a.voci) + 1
    voce = m.voci[m.primaria]
    voci = dict(a.voci)
    voci[nuovo] = hs.Voce(nuovo, voce.tipo, voce.resto)
    contenuti = {n: (a.dove[n].metodo, hs.contenuto(a, n)) for n in a.dove}
    contenuti[nuovo] = (metodo, hs.contenuto(m, m.primaria))
    proprieta = list(a.proprieta)
    legami = {n: list(u) for n, u in a.legami.items()}
    uniti = []
    for essenziale, indice in m.legami[m.primaria]:
        proprieta.append(m.proprieta[indice - 1])
        uniti.append((essenziale, len(proprieta)))
    proprieta.append(hs._piena(b"auxC", 0, 0, urn.encode() + b"\0"))
    uniti.append((True, len(proprieta)))
    legami[nuovo] = uniti
    rimandi = list(a.rimandi) + [(b"auxl", nuovo, [a.primaria])]
    return hs.scrivi(a, voci, contenuti, rimandi, proprieta, legami)


def _originale(metodo: int = 0, mappa=(100, 75)) -> bytes:
    exif = Image.Exif()
    exif[0x010F] = "Prova"
    base = _heic(_caso((400, 300), 1), exif=exif.tobytes())
    base = _con(base, _heic(_caso(mappa, 2, grigia=True)), MAPPA, metodo)
    return _con(base, _heic(_caso((200, 150), 3, grigia=True)), PROFONDITA)


def _migliorata() -> bytes:
    exif = Image.Exif()
    exif[0x010F] = "Prova"
    return _heic(_caso((800, 600), 4), exif=exif.tobytes(), xmp=b"<x/>")


def _aux(dati: bytes) -> dict:
    file = pillow_heif.open_heif(io.BytesIO(dati))
    quadri = {tipo: np.asarray(file.get_aux_image(numeri[0]).to_pillow())
              for tipo, numeri in (file.info.get("aux") or {}).items()}
    quadri["profondita"] = [np.asarray(d.to_pillow())
                            for d in file.info.get("depth_images") or []]
    return quadri


@pytest.mark.parametrize("metodo", [0, 1])
def test_mappa_hdr_e_profondita_passano_uguali_bit_per_bit(metodo):
    originale, migliorata = _originale(metodo), _migliorata()
    nuova, tipi = hs.con_le_ausiliarie(migliorata, originale)
    assert tipi == [MAPPA, PROFONDITA]
    prima, dopo = _aux(originale), _aux(nuova)
    assert np.array_equal(prima[MAPPA], dopo[MAPPA])
    assert len(dopo["profondita"]) == 1
    assert np.array_equal(prima["profondita"][0], dopo["profondita"][0])
    assert hs.controlla(migliorata, nuova, originale)


def test_la_foto_e_i_metadati_della_migliorata_non_cambiano():
    migliorata = _migliorata()
    nuova, _ = hs.con_le_ausiliarie(migliorata, _originale())
    prima, dopo = Image.open(io.BytesIO(migliorata)), Image.open(io.BytesIO(nuova))
    assert dopo.size == (800, 600)
    assert np.array_equal(np.asarray(prima), np.asarray(dopo))
    assert dopo.getexif().get(0x010F) == "Prova"
    assert dopo.info.get("xmp")


def test_le_ausiliarie_byte_per_byte(tmp_path):
    originale = _originale()
    nuova, _ = hs.con_le_ausiliarie(_migliorata(), originale)
    vecchia, rifatta = hs.leggi(originale), hs.leggi(nuova)
    for prima, dopo in zip(hs.ausiliarie(vecchia), hs.ausiliarie(rifatta)):
        assert hs.contenuto(vecchia, prima) == hs.contenuto(rifatta, dopo)
        assert hs.tipo_ausiliario(vecchia, prima) == hs.tipo_ausiliario(rifatta, dopo)


def test_rimetti_sul_disco_e_la_revisione_non_avvisa_piu(tmp_path):
    originale = tmp_path / "IMG_1.HEIC"
    originale.write_bytes(_originale())
    uscita = tmp_path / "IMG_1.migliorata.HEIC"
    uscita.write_bytes(_migliorata())
    assert fedelta.cosa_perde(originale, uscita) == [fedelta.MAPPA_HDR, fedelta.PROFONDITA]
    assert hs.rimetti(originale, uscita) == [MAPPA, PROFONDITA]
    assert fedelta.cosa_perde(originale, uscita) == []
    assert not list(tmp_path.glob("*.aux"))


def test_senza_ausiliarie_il_file_resta_identico(tmp_path):
    originale = tmp_path / "a.heic"
    originale.write_bytes(_heic(_caso((400, 300), 1)))
    uscita = tmp_path / "b.heic"
    uscita.write_bytes(_migliorata())
    prima = uscita.read_bytes()
    assert hs.rimetti(originale, uscita) == []
    assert uscita.read_bytes() == prima


def test_la_trasparenza_non_si_copia():
    originale = _con(_heic(_caso((400, 300), 1)),
                     _heic(_caso((400, 300), 2, grigia=True)), ALFA)
    migliorata = _migliorata()
    nuova, tipi = hs.con_le_ausiliarie(migliorata, originale)
    assert tipi == [] and nuova == migliorata


def test_una_mappa_di_forma_diversa_non_si_copia(tmp_path):
    originale = tmp_path / "a.heic"
    originale.write_bytes(_originale(mappa=(75, 100)))
    uscita = tmp_path / "b.heic"
    uscita.write_bytes(_migliorata())
    prima = uscita.read_bytes()
    assert hs.rimetti(originale, uscita) == []
    assert uscita.read_bytes() == prima


def test_un_originale_rotto_non_tocca_la_migliorata(tmp_path):
    originale = tmp_path / "a.heic"
    originale.write_bytes(_originale()[:300])
    uscita = tmp_path / "b.heic"
    uscita.write_bytes(_migliorata())
    prima = uscita.read_bytes()
    assert hs.rimetti(originale, uscita) == []
    assert uscita.read_bytes() == prima


def test_se_il_controllo_non_torna_la_migliorata_resta_com_era(tmp_path, monkeypatch):
    originale = tmp_path / "a.heic"
    originale.write_bytes(_originale())
    uscita = tmp_path / "b.heic"
    uscita.write_bytes(_migliorata())
    prima = uscita.read_bytes()
    monkeypatch.setattr(hs, "controlla", lambda *a: False)
    assert hs.rimetti(originale, uscita) == []
    assert uscita.read_bytes() == prima


def test_i_formati_non_heif_non_si_toccano(tmp_path):
    originale = tmp_path / "a.jpg"
    originale.write_bytes(b"x")
    uscita = tmp_path / "b.jpg"
    uscita.write_bytes(b"y")
    assert hs.rimetti(originale, uscita) == []
    assert uscita.read_bytes() == b"y"


def test_dall_archivio_si_legge_col_suo_lettore(tmp_path):
    dati = _originale()

    class Finto:
        nome = "Vacanze/IMG_2.HEIC"

        def apri(self):
            return io.BytesIO(dati)

    uscita = tmp_path / "b.heic"
    uscita.write_bytes(_migliorata())
    assert hs.rimetti(Finto(), uscita) == [MAPPA, PROFONDITA]


def test_se_la_migliorata_ha_gia_la_profondita_non_si_raddoppia():
    originale = _originale()
    migliorata = _con(_migliorata(), _heic(_caso((400, 300), 9, grigia=True)), PROFONDITA)
    _, tipi = hs.con_le_ausiliarie(migliorata, originale)
    assert tipi == [MAPPA]


def test_un_file_che_non_e_heif_si_rifiuta():
    with pytest.raises(hs.ScatolaStrana):
        hs.leggi(b"\0\0\0\x10abcdefghijkl")


def test_il_controllo_scopre_una_mappa_diversa_da_quella_dell_originale():
    originale, migliorata = _originale(), _migliorata()
    altro = _con(_heic(_caso((400, 300), 1)), _heic(_caso((100, 75), 7, grigia=True)), MAPPA)
    altro = _con(altro, _heic(_caso((200, 150), 3, grigia=True)), PROFONDITA)
    sbagliata, _ = hs.con_le_ausiliarie(migliorata, altro)
    assert not hs.controlla(migliorata, sbagliata, originale)


def test_il_controllo_scopre_una_foto_cambiata():
    originale, migliorata = _originale(), _migliorata()
    nuova, _ = hs.con_le_ausiliarie(_heic(_caso((800, 600), 5)), originale)
    assert not hs.controlla(migliorata, nuova, originale)
