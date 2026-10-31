from __future__ import annotations

import ast
import importlib
import io
import os
import struct
from pathlib import Path
from xml.etree import ElementTree

import numpy
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from officina.archivio.database import tutti, uno
from officina.importazione import impronta
from officina.importazione.motore import Motore
from officina.miglioria import attesa, coda
from officina.modello import file_media
from officina.ritocco import anteprime, copia, elenco, maschere, pixela

LARGA, ALTA = 96, 64
QUANDO = "2016:02:03 04:05:06"
ZONA_A = (20, 10, 40, 30)
ZONA_B = (60, 30, 84, 54)


def _scacchiera() -> Image.Image:
    y, x = numpy.indices((ALTA, LARGA))
    valori = (((x // 2) + (y // 2)) % 2 * 255).astype(numpy.uint8)
    return Image.fromarray(numpy.stack([valori] * 3, axis=-1), "RGB")


def _exif_semplice() -> bytes:
    exif = Image.Exif()
    exif[0x010F] = "Snap"
    exif.get_ifd(0x8769)[0x9003] = QUANDO
    return exif.tobytes()


def _jpeg(percorso: Path, exif: bytes | None = None) -> None:
    percorso.parent.mkdir(parents=True, exist_ok=True)
    _scacchiera().save(percorso, "JPEG", quality=95, subsampling=0,
                       exif=exif or _exif_semplice())


def numero(quanto: int) -> bytes:
    return struct.pack("<I", quanto)


def misura(voci) -> int:
    return 2 + 12 * len(voci) + 4


def _exif_con_anteprime(anteprima: bytes, nota: bytes) -> bytes:
    ascii_, lungo, grezzo = 2, 4, 7
    primo = [(0x010F, ascii_, b"Nikon\x00"), (0x8769, lungo, None)]
    sotto = [(0x9003, ascii_, QUANDO.encode() + b"\x00"), (0x927C, grezzo, nota)]
    secondo = [(0x0201, lungo, None), (0x0202, lungo, numero(len(anteprima)))]
    dove_sotto = 8 + misura(primo)
    dove_secondo = dove_sotto + misura(sotto)
    dati_da = dove_secondo + misura(secondo)
    dati = bytearray(anteprima)
    primo[1] = (0x8769, lungo, numero(dove_sotto))
    secondo[0] = (0x0201, lungo, numero(dati_da))

    def valore(grezzi: bytes) -> bytes:
        if len(grezzi) <= 4:
            return grezzi.ljust(4, b"\x00")
        if len(dati) % 2:
            dati.append(0)
        posto = dati_da + len(dati)
        dati.extend(grezzi)
        return numero(posto)

    def cartella(voci, prossima: int) -> bytes:
        pezzi = struct.pack("<H", len(voci))
        for etichetta, tipo, grezzi in voci:
            quanti = 1 if tipo == lungo else len(grezzi)
            pezzi += struct.pack("<HHI", etichetta, tipo, quanti) + valore(grezzi)
        return pezzi + numero(prossima)

    corpo = (cartella(primo, dove_secondo) + cartella(sotto, 0) + cartella(secondo, 0))
    return b"Exif\x00\x00II*\x00" + numero(8) + corpo + bytes(dati)


@pytest.fixture
def cartella(tmp_path) -> Path:
    dove = tmp_path / "foto"
    _jpeg(dove / "2016" / "piccola.jpg")
    return dove


@pytest.fixture
def importato(archivio, cartella):
    motore = Motore(archivio)
    motore.prepara([cartella])
    motore.esegui()
    return archivio


def _file_di(archivio, nome: str) -> int:
    with archivio.lettura() as connessione:
        return uno(connessione, "SELECT file_id FROM percorsi WHERE nome = ?", nome)["file_id"]


def _maschera(*zone) -> numpy.ndarray:
    scelta = numpy.zeros((ALTA, LARGA), dtype=bool)
    for x0, y0, x1, y1 in zone:
        scelta[y0:y1, x0:x1] = True
    return scelta


def _volto(zona, **altro) -> dict:
    return {"cosa": elenco.VOLTO, "larghezza": LARGA, "altezza": ALTA,
            "maschera": maschere.comprimi(_maschera(zona), (0, 0), LARGA, ALTA),
            "misura": zona[2] - zona[0], **altro}


def _pixel(percorso: Path) -> numpy.ndarray:
    with Image.open(percorso) as immagine:
        return numpy.asarray(immagine.convert("L"), dtype=float)


def _quanto_varia(pixel: numpy.ndarray, zona) -> float:
    x0, y0, x1, y1 = zona
    return float(pixel[y0:y1, x0:x1].std())


def _ritoccata(archivio, file_id: int):
    with archivio.lettura() as connessione:
        return copia.ritoccata(connessione, file_id)


def test_al_massimo_sei_quadretti_sulla_larghezza_del_volto():
    assert [pixela.quadretto_minimo(m) for m in (1, 5, 6, 7, 12, 13, 60, 61)] == \
        [1, 1, 1, 2, 2, 3, 10, 11]
    assert pixela.quadretto(60, 4) == 10
    assert pixela.quadretto(60, 14) == 14


def test_ogni_quadretto_toccato_si_riempie_tutto():
    rumore = numpy.random.default_rng(7).integers(0, 256, (30, 30, 3), dtype=numpy.uint8)
    immagine = Image.fromarray(rumore, "RGB")
    uno_solo = numpy.ones((1, 1), dtype=bool)

    fatta = numpy.asarray(pixela.pixela(immagine, uno_solo, (13, 13), 6, (0, 0)))

    cella = fatta[12:18, 12:18].reshape(-1, 3)
    assert (cella == cella[0]).all()
    assert numpy.abs(cella[0].astype(int) - rumore[12:18, 12:18].reshape(-1, 3)
                     .mean(axis=0)).max() <= 1
    fuori = numpy.ones((30, 30), dtype=bool)
    fuori[12:18, 12:18] = False
    assert (fatta[fuori] == rumore[fuori]).all()


def test_la_griglia_parte_dall_origine_scelta():
    rumore = numpy.random.default_rng(8).integers(0, 256, (30, 30, 3), dtype=numpy.uint8)
    immagine = Image.fromarray(rumore, "RGB")

    fatta = numpy.asarray(pixela.pixela(immagine, numpy.ones((1, 1), bool), (13, 13), 6,
                                        (2, 2)))

    cella = fatta[8:14, 8:14].reshape(-1, 3)
    assert (cella == cella[0]).all()
    assert (fatta[14:, 14:] == rumore[14:, 14:]).all()


def test_al_bordo_la_media_usa_solo_i_pixel_dello_scatto():
    rumore = numpy.random.default_rng(9).integers(0, 256, (20, 20, 3), dtype=numpy.uint8)
    immagine = Image.fromarray(rumore, "RGB")
    oltre = numpy.ones((4, 4), dtype=bool)

    fatta = numpy.asarray(pixela.pixela(immagine, oltre, (-2, -2), 6, (3, 3)))

    cella = fatta[0:3, 0:3].reshape(-1, 3)
    assert (cella == cella[0]).all()
    attesa_ = rumore[0:3, 0:3].reshape(-1, 3).mean(axis=0)
    assert numpy.abs(cella[0].astype(int) - attesa_).max() <= 1
    assert (fatta[3:, 3:] == rumore[3:, 3:]).all()


def test_niente_scelto_niente_cambia():
    immagine = _scacchiera()
    vuota = numpy.zeros((5, 5), dtype=bool)
    assert (numpy.asarray(pixela.pixela(immagine, vuota, (0, 0), 6, (0, 0)))
            == numpy.asarray(immagine)).all()
    assert maschere.comprimi(vuota, (0, 0), LARGA, ALTA) == b""
    assert maschere.apri(b"") is None


def test_la_parte_scelta_si_conserva_e_si_riapre_uguale():
    scelta = _maschera(ZONA_A)
    scelta[12, 22] = False

    pezzo = maschere.apri(maschere.comprimi(scelta, (0, 0), LARGA, ALTA))

    assert (pezzo.larghezza, pezzo.altezza, pezzo.x, pezzo.y) == (LARGA, ALTA, 20, 10)
    assert pezzo.maschera.shape == (20, 20)
    assert not pezzo.maschera[2, 2] and pezzo.maschera.sum() == 399
    assert maschere.misura_corta(pezzo) == 20


def test_su_uno_scatto_piu_grande_la_parte_copre_almeno_lo_stesso():
    pezzo = maschere.apri(maschere.comprimi(_maschera((21, 11, 39, 29)), (0, 0), LARGA, ALTA))

    grande = maschere.per_misura(pezzo, LARGA * 3, ALTA * 3)

    assert (grande.x, grande.y) == (63, 33)
    assert grande.maschera.shape == (54, 54) and grande.maschera.all()


def test_le_anteprime_nascoste_si_tolgono_e_le_note_di_apple_restano():
    exif = Image.Exif()
    exif[0x010F] = "Snap"
    exif[0x8649] = b"8BIM-anteprima"
    exif.get_ifd(0x8769)[0x9003] = QUANDO
    exif.get_ifd(0x8769)[0x927C] = b"Nikon\x00\x02\x10ANTEPRIMA"
    nikon = Image.Exif()
    nikon.load(anteprime.exif_senza(exif.tobytes()))
    assert 0x927C not in nikon.get_ifd(0x8769) and 0x8649 not in nikon
    assert nikon.get_ifd(0x8769)[0x9003] == QUANDO and nikon[0x010F] == "Snap"

    exif.get_ifd(0x8769)[0x927C] = b"Apple iOS\x00\x00\x01MMcontenuto"
    apple = Image.Exif()
    apple.load(anteprime.exif_senza(exif.tobytes()))
    assert bytes(apple.get_ifd(0x8769)[0x927C]).startswith(b"Apple iOS")


def test_dall_xmp_escono_solo_le_immagini_nascoste():
    xmp = (b'<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF '
           b'xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
           b'<rdf:Description rdf:about="" xmlns:xmp="http://ns.adobe.com/xap/1.0/" '
           b'xmlns:xmpGImg="http://ns.adobe.com/xap/1.0/g/img/" '
           b'xmlns:GCamera="http://ns.google.com/photos/1.0/camera/" '
           b'xmlns:GImage="http://ns.google.com/photos/1.0/image/" '
           b'xmp:CreateDate="2016-02-03T04:05:06" GCamera:MicroVideo="1" '
           b'GCamera:MicroVideoOffset="12345" GImage:Data="QUJDRA==">'
           b'<xmp:Thumbnails><rdf:Alt><rdf:li rdf:parseType="Resource">'
           b'<xmpGImg:image>QUJDRA==</xmpGImg:image></rdf:li></rdf:Alt></xmp:Thumbnails>'
           b'<xmp:Rating>3</xmp:Rating></rdf:Description></rdf:RDF></x:xmpmeta>')

    pulito = anteprime.xmp_senza(xmp)

    assert b"QUJDRA" not in pulito and b"MicroVideo" not in pulito
    assert b'xmp:CreateDate="2016-02-03T04:05:06"' in pulito
    assert b"<xmp:Rating>3</xmp:Rating>" in pulito
    ElementTree.fromstring(pulito)


def test_pixelare_mette_l_originale_in_originali_e_la_copia_al_suo_posto(importato,
                                                                         cartella):
    scatto = cartella / "2016" / "piccola.jpg"
    prima = impronta.del_file(scatto)
    quando = os.stat(scatto).st_mtime
    file_id = _file_di(importato, "piccola.jpg")

    finale = copia.metti(importato, file_id, [_volto(ZONA_A, misura=1)])

    spostato = cartella / "2016" / attesa.ORIGINALI / "piccola.jpg"
    assert finale == scatto
    assert impronta.del_file(spostato) == prima
    nuova = impronta.del_file(scatto)
    assert nuova != prima
    pixel = _pixel(scatto)
    assert _quanto_varia(pixel, ZONA_A) < 12
    assert _quanto_varia(pixel, ZONA_B) > 80
    assert abs(os.stat(scatto).st_mtime - quando) < 2
    with Image.open(scatto) as fatta:
        assert fatta.format == "JPEG" and fatta.size == (LARGA, ALTA)
        assert fatta.getexif().get_ifd(0x8769)[0x9003] == QUANDO
    with importato.lettura() as connessione:
        assert [r["percorso"] for r in file_media.percorsi_di(connessione, file_id)] == \
            [str(spostato)]
        assert file_media.da_mostrare(connessione, file_id) == (scatto, nuova)
        assert file_media.da_mostrare_sotto(connessione, file_id) == (spostato, prima)
        assert file_media.percorso_migliore(connessione, file_id) == spostato
        assert file_media.per_id(connessione, file_id)["miniatura"] is None
        [ritocco] = elenco.di_file(connessione, file_id)
    assert ritocco["misura"] == 20 and ritocco["quadretto"] == 4
    assert (ritocco["origine_x"], ritocco["origine_y"]) == (20, 10)
    riga = _ritoccata(importato, file_id)
    assert riga["stato"] == copia.FATTA and riga["impronta_copia"] == nuova
    assert riga["in_preparazione"] is None
    assert not list((cartella / "2016").glob(f"**/{copia.PREFISSO}-*"))


def test_togliere_un_ritocco_tiene_gli_altri_e_togliendoli_tutti_torna_l_originale(
        importato, cartella):
    scatto = cartella / "2016" / "piccola.jpg"
    prima = impronta.del_file(scatto)
    file_id = _file_di(importato, "piccola.jpg")
    copia.metti(importato, file_id, [_volto(ZONA_A)])
    copia.metti(importato, file_id, [_volto(ZONA_B)])
    pixel = _pixel(scatto)
    assert _quanto_varia(pixel, ZONA_A) < 12 and _quanto_varia(pixel, ZONA_B) < 12
    with importato.lettura() as connessione:
        primo, secondo = elenco.di_file(connessione, file_id)

    copia.togli(importato, primo["id"])

    pixel = _pixel(scatto)
    assert _quanto_varia(pixel, ZONA_A) > 80 and _quanto_varia(pixel, ZONA_B) < 12
    with importato.lettura() as connessione:
        assert [r["id"] for r in elenco.di_file(connessione, file_id)] == [secondo["id"]]
        assert elenco.per_id(connessione, primo["id"])["stato"] == elenco.TOLTO

    copia.togli(importato, secondo["id"])

    assert impronta.del_file(scatto) == prima
    assert not (cartella / "2016" / attesa.ORIGINALI / "piccola.jpg").exists()
    assert _ritoccata(importato, file_id) is None
    with importato.lettura() as connessione:
        assert [r["percorso"] for r in file_media.percorsi_di(connessione, file_id)] == \
            [str(scatto)]
        assert file_media.da_mostrare(connessione, file_id) == (scatto, None)
        assert file_media.per_id(connessione, file_id)["miniatura"] is None
    with pytest.raises(copia.RitoccoFermato):
        copia.togli(importato, secondo["id"])


def test_le_anteprime_nascoste_non_finiscono_nella_copia(archivio, tmp_path):
    piccola = io.BytesIO()
    Image.new("RGB", (16, 16), (250, 10, 10)).save(piccola, "JPEG")
    anteprima = piccola.getvalue()
    nota = b"Nikon\x00\x02\x10\x00\x00" + b"ANTEPRIMA-NASCOSTA" * 4
    dove = tmp_path / "foto"
    _jpeg(dove / "nikon.jpg", _exif_con_anteprime(anteprima, nota))
    assert anteprima in (dove / "nikon.jpg").read_bytes()
    motore = Motore(archivio)
    motore.prepara([dove])
    motore.esegui()

    copia.metti(archivio, _file_di(archivio, "nikon.jpg"), [_volto(ZONA_A)])

    fatta = (dove / "nikon.jpg").read_bytes()
    assert anteprima not in fatta and b"ANTEPRIMA-NASCOSTA" not in fatta
    with Image.open(dove / "nikon.jpg") as immagine:
        assert immagine.getexif().get_ifd(0x8769)[0x9003] == QUANDO
    intatto = (dove / attesa.ORIGINALI / "nikon.jpg").read_bytes()
    assert anteprima in intatto and b"ANTEPRIMA-NASCOSTA" in intatto


def test_se_in_originali_c_e_gia_quel_nome_non_si_ritocca(importato, cartella):
    scatto = cartella / "2016" / "piccola.jpg"
    prima = impronta.del_file(scatto)
    occupato = cartella / "2016" / attesa.ORIGINALI / "piccola.jpg"
    occupato.parent.mkdir()
    occupato.write_bytes(b"un altro file")
    file_id = _file_di(importato, "piccola.jpg")

    with pytest.raises(copia.RitoccoFermato):
        copia.metti(importato, file_id, [_volto(ZONA_A)])

    assert occupato.read_bytes() == b"un altro file"
    assert impronta.del_file(scatto) == prima
    assert _ritoccata(importato, file_id) is None
    with importato.lettura() as connessione:
        [ritocco] = tutti(connessione, "SELECT * FROM ritocchi WHERE file_id = ?", file_id)
    assert ritocco["stato"] == elenco.FALLITO and ritocco["guasto"]


def test_una_parte_scelta_sbagliata_non_entra_nemmeno(importato, cartella):
    scatto = cartella / "2016" / "piccola.jpg"
    prima = impronta.del_file(scatto)
    file_id = _file_di(importato, "piccola.jpg")
    storta = _volto(ZONA_A, larghezza=LARGA * 2)
    vuota = _volto(ZONA_A, maschera=b"")

    for sbagliato in (storta, vuota):
        with pytest.raises(copia.RitoccoFermato):
            copia.metti(importato, file_id, [sbagliato])

    assert impronta.del_file(scatto) == prima
    with importato.lettura() as connessione:
        assert not tutti(connessione, "SELECT id FROM ritocchi")


def test_uno_scambio_interrotto_prima_di_cominciare_si_finisce(importato, cartella,
                                                               monkeypatch):
    scatto = cartella / "2016" / "piccola.jpg"
    prima = impronta.del_file(scatto)
    file_id = _file_di(importato, "piccola.jpg")

    def si_spegne(*_):
        raise OSError("corrente saltata")

    monkeypatch.setattr(copia, "porta_a_termine", si_spegne)
    with pytest.raises(OSError):
        copia.metti(importato, file_id, [_volto(ZONA_A)])
    monkeypatch.undo()
    assert impronta.del_file(scatto) == prima
    with importato.lettura() as connessione:
        assert file_media.da_mostrare(connessione, file_id) == (None, None)
        assert elenco.di_file(connessione, file_id)

    assert copia.ripara(importato) == {"finiti": 1, "fermi": 0}

    assert impronta.del_file(cartella / "2016" / attesa.ORIGINALI / "piccola.jpg") == prima
    assert _quanto_varia(_pixel(scatto), ZONA_A) < 12
    assert _ritoccata(importato, file_id)["stato"] == copia.FATTA


def _spento_a_meta(monkeypatch):
    vero = copia.sposta
    fatti = []

    def sposta(da, verso):
        if fatti:
            raise OSError("corrente saltata")
        fatti.append(da)
        vero(da, verso)

    monkeypatch.setattr(copia, "sposta", sposta)


def test_uno_scambio_interrotto_a_meta_si_finisce(importato, cartella, monkeypatch):
    scatto = cartella / "2016" / "piccola.jpg"
    prima = impronta.del_file(scatto)
    file_id = _file_di(importato, "piccola.jpg")
    _spento_a_meta(monkeypatch)
    with pytest.raises(OSError):
        copia.metti(importato, file_id, [_volto(ZONA_A)])
    monkeypatch.undo()
    assert not scatto.exists()
    with importato.lettura() as connessione:
        assert file_media.da_mostrare(connessione, file_id) == (None, None)

    assert copia.ripara(importato) == {"finiti": 1, "fermi": 0}

    assert impronta.del_file(cartella / "2016" / attesa.ORIGINALI / "piccola.jpg") == prima
    assert _quanto_varia(_pixel(scatto), ZONA_A) < 12


def test_un_file_messo_a_mano_al_posto_della_copia_non_si_copre(importato, cartella,
                                                                 monkeypatch):
    scatto = cartella / "2016" / "piccola.jpg"
    prima = impronta.del_file(scatto)
    file_id = _file_di(importato, "piccola.jpg")
    _spento_a_meta(monkeypatch)
    with pytest.raises(OSError):
        copia.metti(importato, file_id, [_volto(ZONA_A)])
    monkeypatch.undo()
    scatto.write_bytes(b"messo a mano")

    assert copia.ripara(importato) == {"finiti": 0, "fermi": 1}

    assert scatto.read_bytes() == b"messo a mano"
    assert impronta.del_file(cartella / "2016" / attesa.ORIGINALI / "piccola.jpg") == prima
    riga = _ritoccata(importato, file_id)
    assert riga["stato"] == copia.IN_SCAMBIO and riga["guasto"]
    with importato.lettura() as connessione:
        assert file_media.da_mostrare(connessione, file_id) == (None, None)


def test_dopo_il_ritocco_l_importazione_non_vede_doppioni(importato, cartella):
    copia.metti(importato, _file_di(importato, "piccola.jpg"), [_volto(ZONA_A)])
    with importato.lettura() as connessione:
        prima = uno(connessione, "SELECT count(*) AS q FROM file_media")["q"]

    motore = Motore(importato)
    motore.prepara([cartella])
    motore.esegui()

    with importato.lettura() as connessione:
        assert uno(connessione, "SELECT count(*) AS q FROM file_media")["q"] == prima


def test_uno_scatto_ritoccato_aspetta_che_tu_dica_si_prima_del_miglioramento(importato):
    file_id = _file_di(importato, "piccola.jpg")
    copia.metti(importato, file_id, [_volto(ZONA_A)])
    with importato.scrittura() as connessione:
        scatto_id = file_media.per_id(connessione, file_id)["scatto_id"]
        esito = coda.metti(connessione, [scatto_id])
        assert esito.messi == 0 and esito.ritoccati == 1
        assert "aspetta che tu dica sì" in esito.a_parole()
        lasciato = coda.metti(connessione, [scatto_id], ritoccati=False)
        assert lasciato.messi == 0 and lasciato.lasciati == 1
        messo = coda.metti(connessione, [scatto_id], ritoccati=True)
        assert messo.messi == 1 and messo.con_ritocchi == 1
        assert "il pixelato si rifà sopra" in messo.a_parole()


def test_il_ritocco_si_fa_sopra_la_migliorata(importato, cartella):
    pytest.importorskip("av")
    from officina.miglioria import lavoro, scambio

    scatto = cartella / "2016" / "piccola.jpg"
    file_id = _file_di(importato, "piccola.jpg")
    with importato.scrittura() as connessione:
        scatto_id = file_media.per_id(connessione, file_id)["scatto_id"]
        assert coda.metti(connessione, [scatto_id]).messi == 1
    miglioratore = lavoro.Miglioratore(importato, motori_scelti={
        "foto": "finto", "video": "finto", "volti": None})
    assert miglioratore.parti() and miglioratore.lavoro.aspetta_che_finisca(120)
    with importato.lettura() as connessione:
        [migliorata] = coda.in_stato(connessione, coda.DA_RIVEDERE)
    scambio.approva(importato, migliorata["id"])
    larga, alta = Image.open(scatto).size
    segno_migliorata = impronta.del_file(scatto)
    zona = maschere.comprimi(_maschera((10, 10, 40, 40)), (0, 0), larga, alta)

    copia.metti(importato, file_id, [{"cosa": elenco.VOLTO, "larghezza": larga,
                                      "altezza": alta, "maschera": zona, "misura": 30}])

    messa_da_parte = cartella / "2016" / attesa.ORIGINALI / copia.CARTELLA / "piccola.jpg"
    assert impronta.del_file(messa_da_parte) == segno_migliorata
    with importato.lettura() as connessione:
        assert coda.per_id(connessione, migliorata["id"])["percorso_migliorata"] == \
            str(messa_da_parte)
        assert file_media.da_mostrare(connessione, file_id)[0] == scatto
        assert file_media.da_mostrare_sotto(connessione, file_id) == \
            (messa_da_parte, segno_migliorata)
        assert file_media.percorso_migliore(connessione, file_id) == \
            cartella / "2016" / attesa.ORIGINALI / "piccola.jpg"
        [ritocco] = elenco.di_file(connessione, file_id)

    copia.togli(importato, ritocco["id"])

    assert impronta.del_file(scatto) == segno_migliorata
    assert not messa_da_parte.parent.exists()
    with importato.lettura() as connessione:
        assert coda.per_id(connessione, migliorata["id"])["percorso_migliorata"] == \
            str(scatto)


def test_per_ora_una_foto_live_non_si_ritocca(importato, cartella):
    from datetime import datetime

    from officina.finto import contenitore_video

    fotogrammi = []
    for indice in range(3):
        appoggio = io.BytesIO()
        Image.new("RGB", (64, 48), (indice * 60, 80, 200)).save(appoggio, "JPEG")
        fotogrammi.append(appoggio.getvalue())
    contenitore_video.scrivi(cartella / "2017" / "breve.MOV", fotogrammi, 64, 48, 30,
                             "FINTO-0002", datetime(2017, 6, 5, 4, 3, 2), 120, "iPhone 6")
    motore = Motore(importato)
    motore.prepara([cartella])
    motore.esegui()
    scatto = cartella / "2016" / "piccola.jpg"
    prima = impronta.del_file(scatto)
    file_id = _file_di(importato, "piccola.jpg")
    with importato.scrittura() as connessione:
        scatto_id = file_media.per_id(connessione, file_id)["scatto_id"]
        file_media.collega_a_scatto(connessione, _file_di(importato, "breve.MOV"), scatto_id,
                                    "movimento")

    with pytest.raises(copia.RitoccoFermato):
        copia.metti(importato, file_id, [_volto(ZONA_A)])

    assert impronta.del_file(scatto) == prima
    with importato.lettura() as connessione:
        assert not tutti(connessione, "SELECT id FROM ritocchi")


def test_il_browser_rivede_la_foto_appena_ritoccata(importato):
    from officina.web.server import app

    cliente = TestClient(app, client=("127.0.0.1", 51000))
    file_id = _file_di(importato, "piccola.jpg")
    prima = cliente.get(f"/immagine/{file_id}")
    miniatura = cliente.get(f"/miniatura/{file_id}")
    assert prima.status_code == 200 and miniatura.status_code == 200
    assert prima.headers["cache-control"] == "private, no-cache"
    segno, segno_miniatura = prima.headers["etag"], miniatura.headers["etag"]
    assert cliente.get(f"/immagine/{file_id}",
                       headers={"if-none-match": segno}).status_code == 304
    assert cliente.get(f"/miniatura/{file_id}",
                       headers={"if-none-match": segno_miniatura}).status_code == 304

    copia.metti(importato, file_id, [_volto(ZONA_A)])

    dopo = cliente.get(f"/immagine/{file_id}", headers={"if-none-match": segno})
    assert dopo.status_code == 200 and dopo.headers["etag"] != segno
    nuova = cliente.get(f"/miniatura/{file_id}", headers={"if-none-match": segno_miniatura})
    assert nuova.status_code == 200 and nuova.headers["etag"] != segno_miniatura
    with Image.open(io.BytesIO(dopo.content)) as vista:
        pixel = numpy.asarray(vista.convert("L").resize((LARGA, ALTA)), dtype=float)
    assert _quanto_varia(pixel, (22, 12, 38, 28)) < 20


def _scritta_fissa(modulo, pezzo) -> bool:
    if isinstance(pezzo, ast.Constant):
        return isinstance(pezzo.value, str)
    if isinstance(pezzo, ast.Name):
        return isinstance(getattr(modulo, pezzo.id, None), str)
    if isinstance(pezzo, ast.Attribute) and isinstance(pezzo.value, ast.Name):
        return isinstance(getattr(getattr(modulo, pezzo.value.id, None), pezzo.attr, None), str)
    if isinstance(pezzo, ast.Subscript) and isinstance(pezzo.value, ast.Name):
        scritte = getattr(modulo, pezzo.value.id, None)
        return (isinstance(scritte, dict) and bool(scritte)
                and all(isinstance(scritta, str) for scritta in scritte.values()))
    return False


@pytest.mark.parametrize("nome", ["officina.ritocco.copia", "officina.ritocco.coda",
                                  "officina.ritocco.lavoro", "officina.web.coda_ritocco"])
def test_i_messaggi_del_ritocco_non_hanno_nomi_di_file(nome):
    modulo = importlib.import_module(nome)
    sorgente = Path(modulo.__file__).read_text(encoding="utf-8")
    trovati = 0
    for nodo in ast.walk(ast.parse(sorgente)):
        if (isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Name)
                and nodo.func.id == "RitoccoFermato"):
            trovati += 1
            assert nodo.args and all(_scritta_fissa(modulo, pezzo) for pezzo in nodo.args), \
                ast.unparse(nodo)
    assert trovati
