from __future__ import annotations

import math

import numpy
import pytest
from PIL import Image

from officina.corpi import corpo3d, figure, maschere
from officina.corpi.rilevatore import Corpo, PUNTI


def _figura(segno: float = 1.0) -> corpo3d.Figura:
    return corpo3d.Figura(
        forma=[0.1 * segno] * 45, scala=[0.2] * 28, parametri=[0.3] * 204, spostamento=[0.0, 0.1, 3.0],
        fuoco=500.0, punti_3d=[[0.01 * i, 0.02, 0.03] for i in range(70)],
        punti_2d=[[10.0 + i, 20.0] for i in range(70)])


class FigureFinte:

    def __init__(self, campo=math.radians(50), rotte=()):
        self.campo = campo
        self.rotte = set(rotte)
        self.accese = []
        self.spente = 0
        self.camere = []
        self.chiamate = 0

    def accendi_la_lente(self):
        self.accese.append("lente")

    def accendi_il_corpo(self):
        self.accese.append("corpo")

    def spegni(self):
        self.spente += 1

    def stima(self, immagine):
        if self.campo is None:
            return None
        return figure.Lente(figure.PUFFIN, self.campo, 0.01, 0.02, 0.0)

    def ricostruisci(self, pixel, riquadri, intere, fuoco):
        self.chiamate += 1
        if self.chiamate in self.rotte:
            raise RuntimeError("si è rotta")
        assert pixel.ndim == 3 and pixel.shape[2] == 3
        assert intere.shape[0] == len(riquadri) and intere.shape[1:] == pixel.shape[:2]
        self.camere.append(fuoco)
        return [_figura() for _ in riquadri], [[True, False] for _ in riquadri]


def _punti():
    return [(0.2, 0.2, 0.9)] * PUNTI


class RilevatoreFinto:

    versione = "2-sam3-rtmw-kpr-siglip2"

    def guarda(self, immagine):
        return [Corpo((0.1, 0.1, 0.3, 0.8), 0.9, maschere.comprimi(numpy.ones((40, 20), dtype=bool)), _punti()),
                Corpo((0.5, 0.2, 0.2, 0.6), 0.8, b"", _punti())]

    def spegni(self):
        pass


def _con_i_corpi(archivio):
    from officina.corpi.motore import Passata

    Passata(archivio, rilevatore=RilevatoreFinto(), intensita=100).esegui()


def test_le_figure_si_fanno_una_volta_per_ogni_corpo(archivio_pieno):
    _con_i_corpi(archivio_pieno)
    finte = FigureFinte()
    passata = figure.Passata(archivio_pieno, figure=finte)
    totale = passata.quanti_mancano()
    assert totale > 0
    fatto = passata.esegui()
    assert fatto.fatti == totale and fatto.saltati == 0
    assert fatto.figure == 2 * totale
    assert finte.spente >= 1 and "corpo" in finte.accese
    with archivio_pieno.lettura() as connessione:
        corpi = connessione.execute("SELECT id FROM corpi").fetchall()
        lenti = connessione.execute("SELECT fonte, campo_verticale FROM obiettivi").fetchall()
        figura = figure.figura_di(connessione, corpi[0]["id"])
    assert len(lenti) == totale
    assert all(l["fonte"] in (figure.PUFFIN, figure.EXIF) for l in lenti)
    assert figura["mani"] == [True, False]
    assert len(figura["forma"]) == 45 and len(figura["punti_3d"]) == 70
    assert figure.Passata(archivio_pieno, figure=FigureFinte()).quanti_mancano() == 0


def test_la_camera_usa_il_fuoco_della_lente(archivio_pieno):
    _con_i_corpi(archivio_pieno)
    finte = FigureFinte(campo=2 * math.atan(0.5))
    figure.Passata(archivio_pieno, figure=finte).esegui(quanti=1)
    with archivio_pieno.lettura() as connessione:
        riga = connessione.execute("SELECT campo_verticale FROM obiettivi").fetchone()
    assert riga["campo_verticale"] == pytest.approx(2 * math.atan(0.5))
    assert finte.camere and all(f > 0 for f in finte.camere)


def test_se_puffin_non_risponde_si_usa_l_obiettivo_di_base(archivio_pieno):
    _con_i_corpi(archivio_pieno)
    figure.Passata(archivio_pieno, figure=FigureFinte(campo=None)).esegui(quanti=1)
    with archivio_pieno.lettura() as connessione:
        fonti = {r["fonte"] for r in connessione.execute("SELECT fonte FROM obiettivi")}
    assert fonti <= {figure.BASE, figure.EXIF}


def test_una_figura_rotta_si_segnala_e_si_salta(archivio_pieno):
    from officina.modello import segnalazioni

    _con_i_corpi(archivio_pieno)
    fatto = figure.Passata(archivio_pieno, figure=FigureFinte(rotte={1})).esegui()
    assert fatto.saltati == 1
    with archivio_pieno.lettura() as connessione:
        assert segnalazioni.quante(connessione, segnalazioni.FIGURE_NON_FATTE) == 1
        assert figure.quanti_mancano_senza_aprire(connessione) == 0


def test_la_lente_gia_trovata_non_si_ricalcola(archivio_pieno):
    _con_i_corpi(archivio_pieno)
    figure.Passata(archivio_pieno, figure=FigureFinte()).esegui(quanti=1)
    with archivio_pieno.scrittura() as connessione:
        connessione.execute("DELETE FROM aspetti WHERE modello = ?", (figure.ASPETTO,))
    finte = FigureFinte(campo=math.radians(10))
    figure.Passata(archivio_pieno, figure=finte).esegui(quanti=1)
    with archivio_pieno.lettura() as connessione:
        riga = connessione.execute("SELECT campo_verticale FROM obiettivi ORDER BY scatto_id").fetchone()
    assert riga["campo_verticale"] != pytest.approx(math.radians(10))


def test_i_numeri_della_figura_vanno_e_tornano():
    numeri = figure.figura_a_numeri(_figura(), 200, 100)
    assert len(numeri) == figure.NUMERI == 631
    tornata = figure.numeri_a_figura(numeri)
    assert tornata["forma"] == pytest.approx([0.1] * 45)
    assert tornata["fuoco"] == pytest.approx(5.0)
    assert tornata["punti_2d"][0] == pytest.approx([0.05, 0.2])
    with pytest.raises(ValueError):
        figure.numeri_a_figura(numeri[:-1])


def test_la_maschera_torna_grande_dentro_il_riquadro():
    piccola = numpy.zeros((10, 10), dtype=bool)
    piccola[:, :5] = True
    intera = figure.maschera_intera(maschere.comprimi(piccola), (0.5, 0.5, 0.5, 0.5), 40, 20)
    assert intera.shape == (20, 40)
    assert intera[:10, :].sum() == 0 and intera[:, :20].sum() == 0
    assert intera[10:, 20:30].all() and not intera[10:, 30:].any()
    vuota = figure.maschera_intera(b"", (0.0, 0.0, 0.25, 0.5), 40, 20)
    assert vuota[:10, :10].all() and vuota.sum() == 100


def _jpeg_con_fuoco(percorso, larga, alta, f35):
    immagine = Image.new("RGB", (larga, alta), (120, 120, 120))
    exif = Image.Exif()
    exif.get_ifd(figure.IFD_EXIF)[figure.FUOCO_35MM] = f35
    immagine.save(percorso, exif=exif)


def test_il_campo_viene_dal_fuoco_in_35mm(tmp_path):
    foto = tmp_path / "foto.jpg"
    _jpeg_con_fuoco(foto, 400, 300, 26)
    campo = figure.campo_dall_exif(foto, 400, 300)
    fuoco = 26 * math.hypot(400, 300) / figure.DIAGONALE_35MM
    assert campo == pytest.approx(2 * math.atan(300 / (2 * fuoco)))
    assert figure.campo_dall_exif(foto, 400, 301) is not None
    assert figure.campo_dall_exif(foto, 400, 250) is None
    senza = tmp_path / "senza.jpg"
    Image.new("RGB", (40, 30)).save(senza)
    assert figure.campo_dall_exif(senza, 40, 30) is None


def test_senza_modelli_si_dice_cosa_manca(tmp_path):
    testo = figure.cosa_manca(tmp_path)
    assert "SAM 3D Body" in testo and "Puffin" in testo


def test_la_figura_dentro_i_byte_resta_la_stessa(archivio):
    from officina.modello import corpi

    with archivio.scrittura() as connessione:
        connessione.execute("INSERT INTO scatti (genere, origine_data, creato_il) "
                            "VALUES ('foto','assente','2026-01-01T00:00:00')")
        scatto_id = connessione.execute("SELECT max(id) FROM scatti").fetchone()[0]
        corpi.salva(connessione, scatto_id, None, [(0, Corpo((0.1, 0.1, 0.3, 0.8), 0.9, b"", _punti()))],
                    "corpi", "1")
        corpo_id = connessione.execute("SELECT id FROM corpi").fetchone()[0]
        connessione.execute("INSERT INTO aspetti (corpo_id, modello, parti, vettore, visibili) "
                            "VALUES (?,?,1,?,?)", (corpo_id, figure.ASPETTO,
                                                   corpi.vettore_a_byte(figure.figura_a_numeri(_figura(-1), 10, 10)),
                                                   bytes([0, 1])))
    with archivio.lettura() as connessione:
        figura = figure.figura_di(connessione, corpo_id)
        assert figure.figura_di(connessione, corpo_id + 99) is None
    assert figura["forma"] == pytest.approx([-0.1] * 45)
    assert figura["mani"] == [False, True]


def _pezzi_finti(monkeypatch, scaricamento, contenuto=b"finto"):
    import hashlib

    impronta = hashlib.sha256(contenuto).hexdigest()
    finti = tuple(scaricamento.DaHuggingFace(p.titolo, p.repo, p.revisione, p.file, p.dove, impronta, 10)
                  for p in scaricamento.FIGURE)
    monkeypatch.setattr(scaricamento, "FIGURE", finti)
    return finti


def test_i_modelli_delle_figure_arrivano_al_loro_posto(tmp_path, monkeypatch):
    from officina.corpi import corpo3d, obiettivo, scaricamento

    _pezzi_finti(monkeypatch, scaricamento)
    chiesti = []

    def prendi(pezzo, arrivo, chiave):
        chiesti.append((pezzo.repo, pezzo.file, pezzo.revisione))
        preso = arrivo / pezzo.file
        preso.parent.mkdir(parents=True, exist_ok=True)
        preso.write_bytes(b"finto")
        return preso

    monkeypatch.setattr(scaricamento, "_prendi", prendi)
    passi = []
    scaricamento._scarica_le_figure(tmp_path, None, False, passi.append, None)
    assert all((tmp_path / p.dove).read_bytes() == b"finto" for p in scaricamento.FIGURE)
    assert (tmp_path / corpo3d.NOME / corpo3d.FILE_MHR).exists()
    assert (tmp_path / obiettivo.NOME / obiettivo.CARTELLA_LINGUA / "tokenizer.json").exists()
    assert ("facebook/sam-3d-body-dinov3", "assets/mhr_model.pt", scaricamento.REVISIONE_CORPO3D) in chiesti
    assert [p for p in tmp_path.rglob("arriva-*")] == []
    assert len(passi) == 2
    chiesti.clear()
    scaricamento._scarica_le_figure(tmp_path, None, False, None, None)
    assert chiesti == []


def test_un_modello_delle_figure_diverso_non_si_tiene(tmp_path, monkeypatch):
    from officina.corpi import scaricamento
    from officina.descrittori.scaricamento import ScaricamentoFallito

    _pezzi_finti(monkeypatch, scaricamento, b"provato")

    def prendi(pezzo, arrivo, chiave):
        preso = arrivo / "cambiato"
        preso.write_bytes(b"cambiato")
        return preso

    monkeypatch.setattr(scaricamento, "_prendi", prendi)
    with pytest.raises(ScaricamentoFallito) as preso:
        scaricamento._scarica_le_figure(tmp_path, None, False, None, None)
    assert "SAM 3D Body" in preso.value.messaggio and "non è identico" in preso.value.messaggio
    assert [p for p in tmp_path.rglob("*") if p.is_file()] == []


def test_senza_permesso_per_sam_3d_body_si_dice_dove_chiederlo(tmp_path, monkeypatch):
    from officina.corpi import scaricamento
    from officina.descrittori.scaricamento import ScaricamentoFallito

    _pezzi_finti(monkeypatch, scaricamento)
    monkeypatch.setattr(scaricamento, "_che_genere", lambda errore: "permesso")

    def prendi(pezzo, arrivo, chiave):
        raise RuntimeError("chiuso")

    monkeypatch.setattr(scaricamento, "_prendi", prendi)
    with pytest.raises(ScaricamentoFallito) as preso:
        scaricamento._scarica_le_figure(tmp_path, "chiave-finta", False, None, None)
    assert scaricamento.PAGINA_CORPO3D in preso.value.messaggio
    assert "chiave-finta" not in preso.value.messaggio


def test_i_corpi_sono_in_casa_solo_con_le_figure(tmp_path, monkeypatch):
    from officina.corpi import rilevatore, scaricamento

    monkeypatch.setattr(rilevatore, "ci_sono_i_modelli", lambda cartella: True)
    assert not scaricamento.gia_in_casa(tmp_path)
    casa = rilevatore.dove_stanno(tmp_path)
    for pezzo in scaricamento.FIGURE:
        (casa / pezzo.dove).parent.mkdir(parents=True, exist_ok=True)
        (casa / pezzo.dove).write_bytes(b"finto")
    assert scaricamento.gia_in_casa(tmp_path)
    assert figure.cosa_manca(tmp_path) == ""


def test_tante_persone_si_fanno_a_gruppi(archivio_pieno, monkeypatch):
    class Folla(RilevatoreFinto):
        def guarda(self, immagine):
            return [Corpo((0.01 * i, 0.1, 0.05, 0.5), 0.9, b"", _punti()) for i in range(19)]

    from officina.corpi.motore import Passata

    Passata(archivio_pieno, rilevatore=Folla(), intensita=100).esegui()
    monkeypatch.setattr(figure, "PERSONE_A_TURNO", 8)
    finte = FigureFinte()
    lotti = []
    vera = finte.ricostruisci

    def contata(pixel, riquadri, intere, fuoco):
        lotti.append(len(riquadri))
        return vera(pixel, riquadri, intere, fuoco)

    finte.ricostruisci = contata
    fatto = figure.Passata(archivio_pieno, figure=finte).esegui(quanti=1)
    assert lotti == [8, 8, 3] and fatto.figure == 19
