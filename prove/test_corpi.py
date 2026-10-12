from __future__ import annotations

import hashlib
import io
import json
import zipfile
from pathlib import Path

import numpy
import pytest
from PIL import Image

from officina.archivio.database import adesso
from officina.corpi import abbinamento, maschere, rtmw
from officina.corpi.rilevatore import Corpo, PUNTI


def punti_finti(dove_il_viso=None, sicuri=0.9):
    punti = [(0.0, 0.0, 0.0)] * PUNTI
    if dove_il_viso is not None:
        x, y = dove_il_viso
        for i in (*range(0, 5), *range(23, 91)):
            punti[i] = (x + (i % 5) * 0.002, y + (i % 7) * 0.002, sicuri)
    return punti


def maschera_piena(lato=40):
    return maschere.comprimi(numpy.ones((lato, lato), dtype=bool))


def test_la_maschera_si_comprime_e_si_riapre_uguale():
    piena = numpy.zeros((50, 30), dtype=bool)
    piena[10:40, 5:25] = True
    dati = maschere.comprimi(piena)
    assert numpy.array_equal(maschere.apri(dati), piena)
    assert len(dati) < piena.size // 4


def test_una_maschera_grande_si_rimpicciolisce():
    grande = numpy.ones((900, 300), dtype=bool)
    riaperta = maschere.apri(maschere.comprimi(grande))
    assert max(riaperta.shape) == maschere.LATO_MASSIMO
    assert riaperta.all()


def test_un_punto_e_dentro_la_maschera_solo_dove_c_e_la_persona():
    pezzo = numpy.zeros((10, 10), dtype=bool)
    pezzo[:, :5] = True
    dati = maschere.comprimi(pezzo)
    riquadro = (0.2, 0.2, 0.4, 0.4)
    assert maschere.c_e(dati, riquadro, 0.25, 0.3)
    assert not maschere.c_e(dati, riquadro, 0.55, 0.3)
    assert not maschere.c_e(dati, riquadro, 0.9, 0.9)
    assert maschere.quanto_copre(dati, riquadro, (0.2, 0.2, 0.2, 0.4)) == pytest.approx(1.0)
    assert maschere.quanto_copre(dati, riquadro, (0.4, 0.2, 0.2, 0.4)) == pytest.approx(0.0)


def test_il_contorno_diventa_una_figura_trasparente():
    pezzo = numpy.zeros((12, 12), dtype=bool)
    pezzo[2:10, 2:10] = True
    png = maschere.in_png(maschere.comprimi(pezzo), (200, 10, 10))
    figura = Image.open(io.BytesIO(png))
    assert figura.mode == "RGBA" and figura.size == (12, 12)
    assert figura.getpixel((0, 0))[3] == 0
    assert figura.getpixel((2, 2))[3] == 255
    assert 0 < figura.getpixel((5, 5))[3] < 255


def test_il_ritaglio_di_rtmw_tiene_le_proporzioni_del_modello():
    centro, scala = rtmw.centro_e_scala((100, 50, 200, 450))
    assert centro.tolist() == [150, 250]
    assert scala[0] / scala[1] == pytest.approx(rtmw.LARGO / rtmw.ALTO)
    assert scala[1] == pytest.approx(400 * rtmw.MARGINE)
    ingresso, _, _ = rtmw.prepara(Image.new("RGB", (640, 480), (120, 110, 100)), (100, 50, 200, 450))
    assert ingresso.shape == (1, 3, rtmw.ALTO, rtmw.LARGO)
    assert ingresso.dtype == numpy.float32


def test_i_punti_di_rtmw_tornano_al_loro_posto_nella_foto():
    centro, scala = rtmw.centro_e_scala((100, 50, 200, 450))
    lungo_x = numpy.zeros((1, PUNTI, int(rtmw.LARGO * rtmw.DIVISO)), dtype=numpy.float32)
    lungo_y = numpy.zeros((1, PUNTI, int(rtmw.ALTO * rtmw.DIVISO)), dtype=numpy.float32)
    lungo_x[0, :, int(rtmw.LARGO * rtmw.DIVISO / 2)] = 4.0
    lungo_y[0, :, int(rtmw.ALTO * rtmw.DIVISO / 2)] = 3.0
    lungo_x[0, 5, :] = 0.0
    lungo_y[0, 5, :] = 0.0
    punti = rtmw.leggi([lungo_x, lungo_y], centro, scala, 640, 480)
    assert len(punti) == PUNTI
    x, y, sicuro = punti[0]
    assert x == pytest.approx(150 / 640, abs=0.01)
    assert y == pytest.approx(250 / 480, abs=0.01)
    assert sicuro == pytest.approx(0.35)
    assert punti[5] == (0.0, 0.0, 0.0)


def test_kpr_riceve_le_sicurezze_di_prima():
    punti = [(0.1, 0.2, 0.35), (0.3, 0.4, 0.05), (0.5, 0.6, 1.0), (0.0, 0.0, 0.0)]
    assert rtmw.per_kpr(punti) == [(0.1, 0.2, 1.0), (0.3, 0.4, pytest.approx(0.5)),
                                   (0.5, 0.6, 1.0), (0.0, 0.0, 0.0)]


def test_i_punti_del_viso_chiedono_piu_sicurezza():
    riquadro_volto = (0.10, 0.08, 0.08, 0.10)
    incerti = punti_finti((0.12, 0.10), sicuri=0.35)
    sicuri = punti_finti((0.12, 0.10), sicuri=0.45)
    assert abbinamento.punteggio((0.05, 0.05, 0.3, 0.9), b"", incerti,
                                 riquadro_volto) == abbinamento.BASTA_COL_CONTORNO
    assert abbinamento.punteggio((0.05, 0.05, 0.3, 0.9), b"", sicuri, riquadro_volto) == 1.0


def test_il_volto_va_al_corpo_che_ha_il_viso_dentro():
    volto = (0.12, 0.10, 0.06, 0.08)
    corpi = [
        {"riquadro": (0.5, 0.05, 0.3, 0.9), "maschera": maschera_piena(),
         "punti": punti_finti((0.62, 0.12))},
        {"riquadro": (0.05, 0.05, 0.3, 0.9), "maschera": maschera_piena(),
         "punti": punti_finti((0.14, 0.12))},
    ]
    assert [(indice, volto_id) for indice, volto_id, _ in
            abbinamento.abbina(corpi, [(7, volto)])] == [(1, 7)]


def test_due_volti_e_due_corpi_si_abbinano_uno_a_uno():
    corpi = [
        {"riquadro": (0.05, 0.05, 0.3, 0.9), "maschera": b"", "punti": punti_finti((0.14, 0.12))},
        {"riquadro": (0.5, 0.05, 0.3, 0.9), "maschera": b"", "punti": punti_finti((0.62, 0.12))},
    ]
    volti = [(1, (0.6, 0.1, 0.06, 0.08)), (2, (0.12, 0.10, 0.06, 0.08))]
    assert sorted((i, v) for i, v, _ in abbinamento.abbina(corpi, volti)) == [(0, 2), (1, 1)]


def test_senza_i_punti_del_viso_decide_il_contorno():
    pezzo = numpy.zeros((20, 10), dtype=bool)
    pezzo[:6, 2:8] = True
    corpo = {"riquadro": (0.4, 0.1, 0.2, 0.8), "maschera": maschere.comprimi(pezzo),
             "punti": punti_finti()}
    dentro = (0.45, 0.12, 0.1, 0.1)
    fuori = (0.45, 0.6, 0.1, 0.1)
    assert abbinamento.abbina([corpo], [(3, dentro)])
    assert not abbinamento.abbina([corpo], [(4, fuori)])


def test_un_volto_lontano_non_si_attacca_a_nessuno():
    corpo = {"riquadro": (0.05, 0.05, 0.3, 0.9), "maschera": b"", "punti": punti_finti((0.14, 0.12))}
    assert abbinamento.abbina([corpo], [(1, (0.7, 0.7, 0.05, 0.05))]) == []


def _scatto(connessione) -> int:
    connessione.execute("INSERT INTO scatti (genere, origine_data, creato_il) "
                        "VALUES ('foto','assente','2026-01-01T00:00:00')")
    return connessione.execute("SELECT max(id) FROM scatti").fetchone()[0]


def _volto(connessione, scatto_id, riquadro, persona_id=None) -> int:
    connessione.execute(
        "INSERT INTO volti (scatto_id, fotogramma, riquadro, area, nitidezza, sicurezza, "
        "modello, versione, persona_id, trovato_il) VALUES (?, 0, ?, 0.01, 1, 0.9, 'volti', '1', ?, ?)",
        (scatto_id, json.dumps(list(riquadro)), persona_id, adesso()))
    return connessione.execute("SELECT max(id) FROM volti").fetchone()[0]


def test_i_corpi_si_salvano_e_il_volto_si_collega(archivio):
    from officina.modello import corpi, persone

    with archivio.scrittura() as connessione:
        scatto_id = _scatto(connessione)
        chi = persone.crea(connessione, "Persona A")
        volto_id = _volto(connessione, scatto_id, (0.12, 0.10, 0.06, 0.08), chi)
        quanti = corpi.salva(connessione, scatto_id, None, [
            (0, Corpo((0.05, 0.05, 0.3, 0.9), 0.95, maschera_piena(), punti_finti((0.14, 0.12)))),
            (0, Corpo((0.5, 0.05, 0.3, 0.9), 0.80, maschera_piena(), punti_finti((0.62, 0.12)))),
        ], "corpi", "1")
    assert quanti == 2
    with archivio.lettura() as connessione:
        visti = corpi.di_scatto(connessione, scatto_id)
        assert corpi.quanti_guardati(connessione, "corpi", "1") == 1
    assert len(visti) == 2
    legato = [c for c in visti if c["volto_id"]]
    assert len(legato) == 1 and legato[0]["volto_id"] == volto_id
    assert legato[0]["persona"] == "Persona A"
    assert len(legato[0]["punti"]) == PUNTI
    assert legato[0]["punti"][0][2] == pytest.approx(0.9, abs=0.01)


def test_la_migrazione_toglie_i_corpi_poco_sicuri_senza_risposta(archivio):
    from officina.archivio import migrazioni
    from officina.modello import corpi, persone

    with archivio.scrittura() as connessione:
        scatto_id = _scatto(connessione)
        chi = persone.crea(connessione, "Persona A")
        corpi.salva(connessione, scatto_id, None, [
            (0, Corpo((0.05, 0.05, 0.2, 0.9), 0.95, maschera_piena(), punti_finti())),
            (0, Corpo((0.30, 0.05, 0.2, 0.9), 0.55, maschera_piena(), punti_finti())),
            (0, Corpo((0.60, 0.05, 0.2, 0.9), 0.60, maschera_piena(), punti_finti())),
        ], "corpi", "1")
        risposto = connessione.execute("SELECT id FROM corpi WHERE sicurezza < 0.58").fetchone()[0]
        connessione.execute(
            "INSERT INTO corpi_delle_persone (corpo_id, persona_id, risposta, deciso_il) "
            "VALUES (?, ?, 'no', ?)", (risposto, chi, adesso()))
        migrazioni._versione_50(connessione)
        rimasti = sorted(r[0] for r in connessione.execute("SELECT sicurezza FROM corpi"))
        quanti = connessione.execute("SELECT quanti FROM corpi_guardati").fetchone()[0]
    assert rimasti == [pytest.approx(0.55), pytest.approx(0.95)]
    assert quanti == 2


def test_se_i_volti_si_rifanno_il_corpo_si_ricollega(archivio):
    from officina.modello import corpi

    with archivio.scrittura() as connessione:
        scatto_id = _scatto(connessione)
        corpi.salva(connessione, scatto_id, None, [
            (0, Corpo((0.05, 0.05, 0.3, 0.9), 0.95, b"", punti_finti((0.14, 0.12))))], "corpi", "1")
        connessione.execute("DELETE FROM volti WHERE scatto_id = ?", (scatto_id,))
        nuovo = _volto(connessione, scatto_id, (0.12, 0.10, 0.06, 0.08))
        assert corpi.ricollega(connessione, scatto_id) == 1
    with archivio.lettura() as connessione:
        assert corpi.di_scatto(connessione, scatto_id)[0]["volto_id"] == nuovo


class RilevatoreFinto:

    versione = "1-finto"

    def __init__(self, rotto_su=()):
        self.rotto_su = set(rotto_su)
        self.visti = 0
        self.spento = False

    def guarda(self, immagine):
        self.visti += 1
        if self.visti in self.rotto_su:
            raise RuntimeError("si è rotto")
        return [Corpo((0.1, 0.1, 0.3, 0.8), 0.9, maschera_piena(), punti_finti((0.2, 0.15)))]

    def spegni(self):
        self.spento = True


def test_la_passata_guarda_tutti_gli_scatti_una_volta(archivio_pieno):
    from officina.corpi.motore import Passata

    finto = RilevatoreFinto()
    passata = Passata(archivio_pieno, rilevatore=finto, intensita=100)
    totale = passata.quanti_mancano()
    assert totale > 0
    fatto = passata.esegui()
    assert fatto.fatti + fatto.saltati == totale
    assert fatto.corpi == fatto.fatti
    assert finto.spento
    assert Passata(archivio_pieno, rilevatore=RilevatoreFinto(), intensita=100).quanti_mancano() == 0


class RipuntatoreFinto(RilevatoreFinto):

    def __init__(self):
        super().__init__()
        self.chiesti = []

    def punti_di(self, immagine, riquadri):
        self.chiesti.append(len(riquadri))
        return [punti_finti((0.2, 0.15), sicuri=0.45) for _ in riquadri]


def test_i_punti_vecchi_si_rifanno_e_il_volto_si_ricollega(archivio_pieno):
    from officina.corpi import motore
    from officina.corpi.motore import Passata

    Passata(archivio_pieno, rilevatore=RilevatoreFinto(), intensita=100).esegui()
    with archivio_pieno.scrittura() as connessione:
        nuovi = connessione.execute("SELECT count(*) FROM corpi WHERE punti_scala = 10").fetchone()[0]
        connessione.execute("UPDATE corpi SET punti_scala = 1")
        quanti = motore.quanti_da_ripuntare_senza_aprire(connessione)
    assert nuovi > 0 and quanti > 0
    finto = RipuntatoreFinto()
    passi = []
    rifatti = Passata(archivio_pieno, rilevatore=finto, intensita=100).rifai_i_punti(
        al_passo=lambda fatti, totale: passi.append((fatti, totale)))
    assert rifatti == nuovi and sum(finto.chiesti) == nuovi and finto.spento
    assert passi[-1] == (quanti, quanti)
    with archivio_pieno.lettura() as connessione:
        assert motore.quanti_da_ripuntare_senza_aprire(connessione) == 0
        riga = connessione.execute("SELECT punti FROM corpi LIMIT 1").fetchone()[0]
    from officina.modello import corpi

    assert corpi.punti_da_byte(riga)[0][2] == pytest.approx(0.45, abs=0.01)


class RipuntatoreRotto(RilevatoreFinto):

    def punti_di(self, immagine, riquadri):
        raise RuntimeError("guasto finto")


def test_i_punti_che_non_si_rifanno_non_restano_in_fila(archivio_pieno):
    from officina.corpi import motore
    from officina.corpi.motore import Passata

    Passata(archivio_pieno, rilevatore=RilevatoreFinto(), intensita=100).esegui()
    with archivio_pieno.scrittura() as connessione:
        connessione.execute("UPDATE corpi SET punti_scala = 1")
    finto = RipuntatoreRotto()
    assert Passata(archivio_pieno, rilevatore=finto, intensita=100).rifai_i_punti() == 0
    assert finto.spento
    with archivio_pieno.lettura() as connessione:
        assert motore.quanti_da_ripuntare_senza_aprire(connessione) == 0


def test_un_archivio_vecchio_ha_i_punti_da_rifare():
    import sqlite3

    from officina.archivio import migrazioni

    connessione = sqlite3.connect(":memory:")
    connessione.execute("CREATE TABLE corpi (id INTEGER PRIMARY KEY, punti BLOB)")
    connessione.execute("INSERT INTO corpi (punti) VALUES (NULL)")
    migrazioni._versione_51(connessione)
    assert connessione.execute("SELECT punti_scala FROM corpi").fetchone()[0] == 1


def test_uno_scatto_che_si_rompe_viene_segnalato_e_saltato(archivio_pieno):
    from officina.corpi.motore import Passata
    from officina.modello import segnalazioni

    passata = Passata(archivio_pieno, rilevatore=RilevatoreFinto(rotto_su={1}), intensita=100)
    fatto = passata.esegui()
    assert fatto.saltati >= 1
    with archivio_pieno.lettura() as connessione:
        assert segnalazioni.quante(connessione, segnalazioni.CORPI_NON_LETTI) >= 1


def test_senza_modelli_la_passata_si_ferma_subito(archivio_pieno):
    from officina import corpi as corpi_pacchetto
    from officina.corpi.motore import Passata

    passata = Passata(archivio_pieno, rilevatore=corpi_pacchetto.Rilevatore(archivio_pieno.dove.modelli),
                      intensita=100)
    with pytest.raises(corpi_pacchetto.MancanoIModelli):
        passata.esegui()


def test_i_corpi_sono_obbligatori_e_si_riconoscono_in_casa(tmp_path):
    from officina import modelli_in_casa
    from officina.corpi import rilevatore

    assert "corpi" in modelli_in_casa.OBBLIGATORI
    assert modelli_in_casa.OBBLIGATORI.index("corpi") > modelli_in_casa.OBBLIGATORI.index("volti")
    assert not modelli_in_casa.in_casa("corpi", tmp_path)
    casa = rilevatore.dove_stanno(tmp_path)
    (casa / rilevatore.CARTELLA_SAM3).mkdir(parents=True)
    (casa / rilevatore.CARTELLA_SAM3 / rilevatore.PROVA_SAM3).write_text("{}")
    (casa / rilevatore.FILE_POSE).write_bytes(b"onnx finto")
    assert not modelli_in_casa.in_casa("corpi", tmp_path)
    from officina.corpi import kpr_pesi

    kpr_casa = kpr_pesi.dove_stanno(tmp_path)
    kpr_casa.mkdir(parents=True)
    for pesi in kpr_pesi.PESI:
        (kpr_casa / f"kpr-{pesi.versione}.safetensors").write_bytes(b"finto")
        (kpr_casa / f"kpr-{pesi.versione}.json").write_text("{}")
    assert kpr_casa.parent == casa
    assert not modelli_in_casa.in_casa("corpi", tmp_path)
    from officina.corpi import scaricamento

    for pezzo in scaricamento.FIGURE:
        (casa / pezzo.dove).parent.mkdir(parents=True, exist_ok=True)
        (casa / pezzo.dove).write_bytes(b"finto")
    assert modelli_in_casa.in_casa("corpi", tmp_path)
    assert modelli_in_casa.nome("corpi") == "SAM 3, RTMW, KPR, SAM 3D Body, Puffin, VGGT-Omega e Depth Anything 3"


def test_rtmw_si_prende_dallo_zip_ufficiale(tmp_path):
    from officina.corpi import scaricamento

    zip_finto = tmp_path / "rtmw.zip"
    with zipfile.ZipFile(zip_finto, "w") as dentro:
        dentro.writestr("rtmw-x/end2end.onnx", b"onnx finto")
        dentro.writestr("rtmw-x/pipeline.json", "{}")
    vicino = tmp_path / "casa"
    vicino.mkdir()
    arrivi = []
    preso = scaricamento._da_indirizzo(
        scaricamento.Indirizzo(zip_finto.as_uri(), dentro="end2end.onnx"), vicino,
        lambda fatti, totale: arrivi.append(fatti))
    assert preso.read_bytes() == b"onnx finto"
    assert arrivi and not [p for p in vicino.iterdir() if p.is_dir()]


def test_un_file_diverso_da_quello_provato_non_si_tiene(tmp_path):
    from officina.corpi import scaricamento

    zip_finto = tmp_path / "rtmw.zip"
    with zipfile.ZipFile(zip_finto, "w") as dentro:
        dentro.writestr("end2end.onnx", b"onnx finto")
    vicino = tmp_path / "casa"
    vicino.mkdir()
    with pytest.raises(Exception):
        scaricamento._da_indirizzo(
            scaricamento.Indirizzo(zip_finto.as_uri(), dentro="end2end.onnx", sha256="0" * 64),
            vicino, None)
    assert list(vicino.iterdir()) == []


def test_rtmw_diverso_da_quello_collaudato_si_butta(tmp_path, monkeypatch):
    from officina.corpi import scaricamento

    assert len(scaricamento.POSE_SHA256) == 64
    finto = tmp_path / "arrivato.preso"
    finto.write_bytes(b"onnx finto")
    monkeypatch.setattr(scaricamento, "_da_indirizzo", lambda *_: finto)
    dove = tmp_path / "corpi" / "rtmw.onnx"
    dove.parent.mkdir()
    with pytest.raises(scaricamento.ScaricamentoFallito, match="non è identico"):
        scaricamento._scarica_la_pose(dove, None, None, None)
    assert not finto.exists() and not dove.exists()


def _sam3_finto(monkeypatch, scrivi):
    import sys
    import types

    chiesto = {}

    def snapshot_download(repo_id, local_dir, revision=None, **_):
        chiesto.update(repo=repo_id, revisione=revision)
        scrivi(Path(local_dir))

    finto = types.ModuleType("huggingface_hub")
    finto.snapshot_download = snapshot_download
    monkeypatch.setitem(sys.modules, "huggingface_hub", finto)
    return chiesto


def test_sam3_si_scarica_alla_versione_collaudata(tmp_path, monkeypatch):
    from officina.corpi import scaricamento

    impronte = {nome: hashlib.sha256(nome.encode()).hexdigest() for nome in scaricamento.SHA256_SAM3}
    monkeypatch.setattr(scaricamento, "SHA256_SAM3", impronte)

    def scrivi(dove):
        for nome in impronte:
            (dove / nome).write_bytes(nome.encode())

    chiesto = _sam3_finto(monkeypatch, scrivi)
    scaricamento._scarica_sam3(tmp_path / "sam3", None, None, None)
    assert chiesto == {"repo": "facebook/sam3", "revisione": scaricamento.REVISIONE_SAM3}
    assert len(scaricamento.REVISIONE_SAM3) == 40 and len(scaricamento.SHA256_SAM3) == 8
    assert all(len(v) == 64 for v in scaricamento.SHA256_SAM3.values())


def test_sam3_diverso_da_quello_collaudato_si_butta(tmp_path, monkeypatch):
    from officina.corpi import rilevatore, scaricamento

    def scrivi(dove):
        for nome in scaricamento.SHA256_SAM3:
            (dove / nome).write_bytes(b"cambiato")

    _sam3_finto(monkeypatch, scrivi)
    dove = tmp_path / "sam3"
    with pytest.raises(scaricamento.ScaricamentoFallito, match="non è identico"):
        scaricamento._scarica_sam3(dove, None, None, None)
    assert not (dove / "model.safetensors").exists()
    assert not (dove / rilevatore.PROVA_SAM3).exists()


def test_la_foto_aperta_ha_il_tasto_dei_corpi(archivio_pieno):
    from fastapi.testclient import TestClient

    from officina.modello import corpi
    from officina.web.server import app

    with archivio_pieno.scrittura() as connessione:
        scatto_id = connessione.execute(
            "SELECT s.id FROM scatti s JOIN file_media f ON f.scatto_id = s.id "
            "WHERE s.genere = 'foto' AND f.ruolo = 'principale' ORDER BY s.id LIMIT 1").fetchone()[0]
        corpi.salva(connessione, scatto_id, None, [
            (0, Corpo((0.1, 0.1, 0.3, 0.8), 0.9, maschera_piena(), punti_finti((0.2, 0.15))))],
            "corpi", "1")
    pagina = TestClient(app, client=("127.0.0.1", 51000)).get(f"/scatto/{scatto_id}")
    assert pagina.status_code == 200
    assert "data-mostra-corpi" in pagina.text
    assert 'id="corpi-dello-scatto"' in pagina.text
    assert "data:image/png;base64," in pagina.text


def test_la_foto_aperta_senza_corpi_non_ha_il_tasto(archivio_pieno):
    from fastapi.testclient import TestClient

    from officina.web.server import app

    with archivio_pieno.lettura() as connessione:
        scatto_id = connessione.execute(
            "SELECT id FROM scatti WHERE genere = 'foto' ORDER BY id LIMIT 1").fetchone()[0]
    pagina = TestClient(app, client=("127.0.0.1", 51000)).get(f"/scatto/{scatto_id}")
    assert pagina.status_code == 200
    assert "data-mostra-corpi" not in pagina.text


def test_se_i_modelli_non_si_accendono_nessuno_scatto_viene_segnato(archivio_pieno):
    from officina.corpi.motore import Passata
    from officina.errori import ErroreOfficina
    from officina.modello import segnalazioni

    class NonSiAccende(RilevatoreFinto):
        def accendi(self):
            raise RuntimeError("la scheda video non risponde")

    finto = NonSiAccende()
    passata = Passata(archivio_pieno, rilevatore=finto, intensita=100)
    prima = passata.quanti_mancano()
    with pytest.raises(ErroreOfficina) as preso:
        passata.esegui()
    assert preso.value.codice == "corpi_non_si_accendono"
    assert finto.spento and finto.visti == 0
    assert passata.quanti_mancano() == prima
    with archivio_pieno.lettura() as connessione:
        assert segnalazioni.quante(connessione, segnalazioni.CORPI_NON_LETTI) == 0


def test_la_chiave_si_controlla_anche_per_sam3(monkeypatch):
    huggingface_hub = pytest.importorskip("huggingface_hub")
    from huggingface_hub.errors import GatedRepoError

    from officina import modelli_in_casa
    from officina.errori import ErroreOfficina

    chiesti = []

    def controlla(repo, token=None):
        chiesti.append(repo)
        if repo == "facebook/sam3":
            raise GatedRepoError("non ancora accettato")

    monkeypatch.setattr(huggingface_hub, "auth_check", controlla)
    with pytest.raises(ErroreOfficina) as preso:
        modelli_in_casa.controlla_la_chiave("hf_finta")
    assert "SAM 3" in preso.value.messaggio
    assert chiesti[-1] == "facebook/sam3"
    assert any("dinov3" in repo for repo in chiesti)
