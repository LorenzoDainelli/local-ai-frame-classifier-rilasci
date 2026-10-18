from __future__ import annotations

import io
import json
import math
import re
import struct

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from officina.corpi import figure, superfici
from officina.modello import stanze
from officina.stanza import costruzione, in3d

from prove.test_costruzione_stanza import ModelliFinti, _foto_dell_archivio, _un_posto_con
from prove.test_superfici import PelleFinta, _con_le_figure

CAMPO_DI_PUFFIN = math.radians(50)
DATE = ("2022-05-04T10:00:00", "2021-03-02T09:30:00", "2020-11-30T18:00:00", "2021-08-15T12:00:00",
        "2019-01-09T07:15:00", "2022-12-24T20:45:00", None)
ROLLI_PROVATI = (-0.4, -0.1, 0.25, 0.5)
BECCHEGGI_PROVATI = (-0.6, -0.2, 0.3, 0.9)
RAGGI_DELLA_CAMERA = ([0.3, -0.2, 1.0], [-0.5, 0.4, 1.0], [0.0, 0.0, 1.0])
LA_ROTAZIONE_DI_BASE = [list(riga) for riga in in3d.DI_BASE]


@pytest.fixture
def cliente(archivio_pieno):
    from officina.web import server

    return TestClient(server.app, client=("127.0.0.1", 51000))


@pytest.fixture
def con_i_corpi(archivio_pieno):
    _con_le_figure(archivio_pieno)
    superfici.Passata(archivio_pieno, pelle=PelleFinta()).esegui()
    return archivio_pieno


def _testa(dati: bytes, firma: bytes) -> tuple[dict, int]:
    assert dati[:4] == firma
    lunga = struct.unpack_from("<I", dati, 4)[0]
    assert lunga % 4 == 0
    return json.loads(dati[8:8 + lunga].decode("utf-8")), 8 + lunga


def _blocco(dati: bytes, inizio: int, tipo: str, forma: tuple[int, ...]):
    quanti = int(np.prod(forma))
    letto = np.frombuffer(dati, dtype=tipo, count=quanti, offset=inizio).reshape(forma)
    byte = quanti * np.dtype(tipo).itemsize
    return letto, inizio + byte + (-byte % 4)


def _persone_lette(dati: bytes) -> dict:
    testa, posto = _testa(dati, in3d.FIRMA_PERSONE)
    if not testa["persone"]:
        assert posto == len(dati)
        return {"testa": testa, "facce": None, "persone": []}
    facce, posto = _blocco(dati, posto, "<u4" if testa["grandi"] else "<u2", (testa["facce"], 3))
    persone = []
    for persona in testa["persone"]:
        quanti = persona["vertici"]
        posizioni, posto = _blocco(dati, posto, "<f4", (quanti, 3))
        uv, posto = _blocco(dati, posto, "<u2", (quanti, 2))
        visti, posto = _blocco(dati, posto, "u1", (quanti,))
        persone.append({"corpo_id": persona["corpo_id"], "posizioni": posizioni, "uv": uv, "visti": visti})
    assert posto == len(dati)
    return {"testa": testa, "facce": facce, "persone": persone}


def _nuvola_letta(dati: bytes) -> dict:
    testa, posto = _testa(dati, in3d.FIRMA_NUVOLA)
    quanti = testa["punti"]
    stretti, posto = _blocco(dati, posto, "<i2", (quanti, 3))
    colori, posto = _blocco(dati, posto, "u1", (quanti, 3))
    assert posto == len(dati)
    punti = np.asarray(testa["centro"]) + stretti / 32767.0 * np.asarray(testa["mezzo"])
    return {"testa": testa, "stretti": stretti, "punti": punti, "colori": colori}


def _rotazione_che_guarda(su: float) -> list[list[float]]:
    avanti = math.sqrt(1 - su * su)
    return [[1.0, 0.0, 0.0], [0.0, avanti, su], [0.0, -su, avanti]]


def _macchina(campo: float, centro=(0.0, 0.0, 0.0), rotazione=None, centro_x: float = 0.5,
              centro_y: float = 0.5) -> dict:
    return {"centro": list(centro), "rotazione": np.eye(3).tolist() if rotazione is None else rotazione,
            "campo": campo, "centro_x": centro_x, "centro_y": centro_y, "proporzione": 1.5}


def _scatti_con_le_superfici(archivio) -> list[int]:
    with archivio.lettura() as connessione:
        return [r["id"] for r in connessione.execute(
            "SELECT DISTINCT c.scatto_id AS id FROM superfici f JOIN corpi c ON c.id = f.corpo_id "
            "WHERE f.vertici > 0 ORDER BY 1")]


def _su_della_camera(rollio: float, beccheggio: float) -> np.ndarray:
    return np.array([-math.sin(rollio) * math.cos(beccheggio), -math.cos(rollio) * math.cos(beccheggio),
                     math.sin(beccheggio)])


def _orizzonte_di_geocalib(rollio: float, mezza_larghezza: float, fuoco: float) -> tuple[np.ndarray, np.ndarray]:
    a_sinistra = np.array([-mezza_larghezza, mezza_larghezza * math.tan(rollio), fuoco])
    a_destra = np.array([mezza_larghezza, -mezza_larghezza * math.tan(rollio), fuoco])
    return a_sinistra, a_destra


def _l_inclinazione(archivio, scatto_id: int) -> tuple | None:
    with archivio.lettura() as connessione:
        riga = connessione.execute(
            "SELECT rollio, beccheggio FROM obiettivi WHERE scatto_id = ?", (scatto_id,)).fetchone()
    return None if riga is None else (riga["rollio"], riga["beccheggio"])


def _metti_l_inclinazione(archivio, scatto_id: int, rollio, beccheggio) -> None:
    with archivio.scrittura() as connessione:
        cambiate = connessione.execute(
            "UPDATE obiettivi SET rollio = ?, beccheggio = ? WHERE scatto_id = ?",
            (rollio, beccheggio, scatto_id)).rowcount
    assert cambiate == 1
    assert _l_inclinazione(archivio, scatto_id) == (rollio, beccheggio)


def _a_terra_a_mano(archivio, scatto_id: int, corpi: list[int], rotazione) -> tuple[list[np.ndarray], float]:
    with archivio.lettura() as connessione:
        righe = superfici.di_scatto(connessione, scatto_id)
    ruotati = []
    for corpo_id in corpi:
        salvata = superfici.leggi(archivio.dove.superfici / righe[corpo_id]["file"])
        vertici = salvata["locali"].astype(np.float64) + salvata["spostamento"].astype(np.float64)
        ruotati.append(vertici @ np.asarray(rotazione, dtype=np.float64).T)
    basso = min(float(p[:, 1].min()) for p in ruotati)
    return [p - np.array([0.0, basso, 0.0]) for p in ruotati], -basso


def _il_principale(archivio, scatto_id: int) -> int:
    with archivio.lettura() as connessione:
        return connessione.execute(
            "SELECT id FROM file_media WHERE scatto_id = ? AND ruolo = 'principale'",
            (scatto_id,)).fetchone()["id"]


def _un_video(archivio) -> int:
    with archivio.lettura() as connessione:
        return connessione.execute("SELECT id FROM scatti WHERE genere = 'video' ORDER BY id").fetchone()["id"]


def _proporzione(archivio, scatto_id: int) -> float:
    with archivio.lettura() as connessione:
        riga = connessione.execute("SELECT larghezza, altezza FROM scatti WHERE id = ?", (scatto_id,)).fetchone()
    return riga["larghezza"] / riga["altezza"]


def _la_stanza(archivio, quante: int = 7, nome: str = "Cucina") -> tuple[int, list[int]]:
    scatti = _foto_dell_archivio(archivio)[:quante]
    posto_id = _un_posto_con(archivio, scatti, nome)
    costruzione.Passata(archivio, modelli=ModelliFinti()).esegui()
    return posto_id, scatti


def _metti_le_date(archivio, scatti: list[int]) -> None:
    with archivio.scrittura() as connessione:
        for scatto_id, data in zip(scatti, DATE, strict=True):
            connessione.execute("UPDATE scatti SET data_locale = ? WHERE id = ?", (data, scatto_id))


def _scena(archivio, scatto_id: int) -> dict | None:
    with archivio.lettura() as connessione:
        return in3d.scena(connessione, scatto_id)


def _c_e(archivio, scatto_id: int) -> bool:
    with archivio.lettura() as connessione:
        return in3d.c_e(connessione, scatto_id)


def _il_tasto_in_3d(pagina: str) -> bool:
    return re.search(r"<button[^>]*\sdata-apri-3d[\s>]", pagina) is not None


def _un_volto(connessione, scatto_id: int, persona_id: int | None) -> int:
    from officina.archivio.database import adesso

    connessione.execute(
        "INSERT INTO volti (scatto_id, fotogramma, riquadro, area, nitidezza, sicurezza, "
        "modello, versione, persona_id, trovato_il) VALUES (?, 0, '[0.1, 0.1, 0.1, 0.1]', 0.01, 1, 0.9, "
        "'volti', '1', ?, ?)", (scatto_id, persona_id, adesso()))
    return connessione.execute("SELECT max(id) FROM volti").fetchone()[0]


@pytest.mark.parametrize("campo, proporzione, attesi", [
    (2 * math.atan(12 / 50), 4 / 3, 50),
    (2 * math.atan(12 / 50), 1.0, 50),
    (2 * math.atan(12 / 50), 0.75, 67),
    (2 * math.atan(12 / 35), 1.5, 35),
    (2 * math.atan(12 / 35), 2 / 3, 53),
])
def test_i_millimetri_si_misurano_sul_lato_corto(campo, proporzione, attesi):
    assert in3d.millimetri(campo, proporzione) == attesi


def test_in_verticale_la_stessa_inquadratura_vale_meno_millimetri_di_quelli_in_orizzontale():
    campo = CAMPO_DI_PUFFIN
    assert in3d.millimetri(campo, 4 / 3) == 26
    assert in3d.millimetri(campo, 3 / 4) == 34


@pytest.mark.parametrize("su, parole", [
    (0.9, "guardando in su"),
    (0.3, "guardando un po' in su"),
    (0.0, "guardando dritto"),
    (0.1, "guardando dritto"),
    (-0.3, "guardando un po' in giù"),
    (-0.9, "guardando in giù"),
])
def test_descrivi_dice_dove_guarda_la_macchina(su, parole):
    foto = {"centro": [0.0, 1.5, 0.0], "rotazione": _rotazione_che_guarda(su)}
    assert in3d.descrivi(foto) == f"da 1,5 m di altezza, {parole}"


@pytest.mark.parametrize("altezza, scritta", [(1.64, "1,6"), (2.0, "2,0"), (0.04, "0,0"), (-0.8, "0,0"),
                                              (12.34, "12,3")])
def test_descrivi_scrive_l_altezza_con_la_virgola_e_mai_sotto_zero(altezza, scritta):
    foto = {"centro": [3.0, altezza, -2.0], "rotazione": _rotazione_che_guarda(0.0)}
    assert in3d.descrivi(foto) == f"da {scritta} m di altezza, guardando dritto"


@pytest.mark.parametrize("fonte, stanza, atteso", [
    ("exif", None, "50 mm, dai dati della foto"),
    ("exif", 2 * math.atan(12 / 35), "50 mm, dai dati della foto"),
    ("puffin", None, "50 mm, stimato da Puffin"),
    ("puffin", 2 * math.atan(12 / 35), "50 mm, stimato da Puffin"),
    ("base", 2 * math.atan(12 / 35), "35 mm, stimato dalla stanza"),
    ("base", None, "50 mm, a occhio"),
    ("base", 0.0, "50 mm, a occhio"),
])
def test_l_obiettivo_si_fida_prima_dei_dati_poi_di_puffin_poi_della_stanza_poi_dell_occhio(fonte, stanza, atteso):
    riga = {"fonte": fonte, "campo_verticale": 2 * math.atan(12 / 50)}
    assert in3d._obiettivo(riga, stanza, 4 / 3) == atteso


def test_senza_la_riga_dell_obiettivo_resta_la_stanza_o_il_vuoto():
    assert in3d._obiettivo(None, 2 * math.atan(12 / 35), 4 / 3) == "35 mm, stimato dalla stanza"
    assert in3d._obiettivo(None, None, 4 / 3) == ""


def test_senza_la_macchina_della_stanza_y_e_z_si_ribaltano():
    punti = in3d.nella_scena([[0.0, 0.0, 0.0], [1.0, 2.0, 3.0]], [0.5, -1.0, 4.0], 1.0, 1.5, None)
    assert punti.tolist() == [[0.5, 1.0, -4.0], [1.5, -1.0, -7.0]]


def test_con_la_macchina_che_ha_lo_stesso_fuoco_il_punto_sull_asse_resta_sull_asse():
    macchina = _macchina(2 * math.atan(0.25))
    punti = in3d.nella_scena([[0.0, 0.0, 0.0]], [0.0, 0.0, 3.0], 2.0, 1.5, macchina)
    assert punti[0] == pytest.approx([0.0, 0.0, 3.0])


def test_il_fuoco_della_stanza_scala_la_profondita_ma_non_la_grandezza():
    macchina = _macchina(2 * math.atan(0.25))
    spostamento = np.array([0.0, 0.0, 3.0])
    punti = in3d.nella_scena([[0.0, 0.0, 0.0], [0.3, -0.2, 0.0]], spostamento, 1.0, 1.5, macchina)
    assert punti[0] == pytest.approx([0.0, 0.0, 6.0])
    assert punti[1] - punti[0] == pytest.approx([0.3, -0.2, 0.0])
    assert spostamento.tolist() == [0.0, 0.0, 3.0]


def test_una_macchina_della_stanza_girata_e_spostata_porta_il_punto_lungo_il_suo_asse():
    rotazione = [[0.0, 0.0, 1.0], [0.0, -1.0, 0.0], [1.0, 0.0, 0.0]]
    macchina = _macchina(2 * math.atan(0.25), centro=(1.0, 2.0, 3.0), rotazione=rotazione)
    punti = in3d.nella_scena([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]], [0.0, 0.0, 2.0], 2.0, 1.5, macchina)
    assert punti[0] == pytest.approx([3.0, 2.0, 3.0])
    assert punti[1] == pytest.approx([3.0, 2.0, 4.0])


def test_il_centro_dell_immagine_della_stanza_sposta_il_punto_di_lato():
    macchina = _macchina(2 * math.atan(0.25), centro_x=0.6, centro_y=0.45)
    punti = in3d.nella_scena([[0.0, 0.0, 0.0]], [0.0, 0.0, 4.0], 2.0, 1.5, macchina)
    assert punti[0] == pytest.approx([-0.3, 0.1, 4.0])


def test_un_obiettivo_che_allunga_di_lato_stringe_le_persone_di_lato():
    macchina = {**_macchina(2 * math.atan(0.25)), "allungo": 2.0}
    punti = in3d.nella_scena([[0.0, 0.0, 0.0], [0.4, 0.2, 0.0]], [0.6, 0.0, 3.0], 2.0, 1.5, macchina)
    assert punti[0] == pytest.approx([0.3, 0.0, 3.0])
    assert punti[1] == pytest.approx([0.5, 0.2, 3.0])


def test_il_campo_della_foto_tiene_anche_quanto_l_obiettivo_allunga_di_lato():
    campo, cx, cy, proporzione, allungo = costruzione._campo_e_centro(
        [[44.0, 0.0, 24.0], [0.0, 40.0, 18.0], [0.0, 0.0, 1.0]], 48, 36)
    assert campo == pytest.approx(2 * math.atan(36 / 80))
    assert (cx, cy, proporzione) == pytest.approx((0.5, 0.5, 48 / 36))
    assert allungo == pytest.approx(1.1)


def test_la_macchina_di_base_ha_il_campo_giusto_e_guarda_dall_altezza_data():
    macchina = in3d.camera_di_base(0.75, 0.5, 1.7)
    assert macchina["campo"] == pytest.approx(math.pi / 2)
    assert macchina["centro"] == [0.0, 1.7, 0.0]
    assert np.linalg.det(np.asarray(macchina["rotazione"])) == pytest.approx(1.0)
    assert macchina["proporzione"] == 0.75
    assert (macchina["centro_x"], macchina["centro_y"]) == (0.5, 0.5)


def test_la_macchina_di_base_porta_la_rotazione_che_le_si_da_e_senza_porta_quella_di_base():
    rotazione = in3d.in_piano(0.2, 0.1)
    assert rotazione != LA_ROTAZIONE_DI_BASE
    inclinata = in3d.camera_di_base(1.5, 0.8, 1.6, rotazione=rotazione)
    assert inclinata["rotazione"] == rotazione
    assert inclinata["centro"] == [0.0, 1.6, 0.0]
    assert inclinata["campo"] == pytest.approx(2 * math.atan(0.5 / 0.8))
    assert (inclinata["centro_x"], inclinata["centro_y"], inclinata["proporzione"]) == (0.5, 0.5, 1.5)
    assert in3d.camera_di_base(1.5, 0.8, 1.6)["rotazione"] == LA_ROTAZIONE_DI_BASE
    assert in3d.camera_di_base(1.5, 0.8, 1.6, rotazione=None)["rotazione"] == LA_ROTAZIONE_DI_BASE


@pytest.mark.parametrize("rollio, beccheggio", [
    (0.0, 0.0), (0, 0), (None, 0.1), (0.1, None), (None, None), ("x", 0.1), (0.1, "x"), ([], 0.1),
    (math.nan, 0.1), (0.1, math.nan), (math.inf, 0.1), (-math.inf, 0.1), (0.1, math.inf), (0.1, -math.inf),
    (0.1, 1.4), (0.1, -1.4), (0.3, math.pi / 2)])
def test_senza_un_rollio_e_un_beccheggio_buoni_la_rotazione_del_piano_e_quella_di_base(rollio, beccheggio):
    assert in3d.in_piano(rollio, beccheggio) == LA_ROTAZIONE_DI_BASE


def test_il_beccheggio_buono_arriva_fino_al_massimo_e_poco_oltre_si_torna_alla_base():
    massimo = in3d.BECCHEGGIO_MASSIMO
    assert in3d.in_piano(0.1, massimo) != LA_ROTAZIONE_DI_BASE
    assert in3d.in_piano(0.1, -massimo) != LA_ROTAZIONE_DI_BASE
    assert in3d.in_piano(0.1, massimo + 1e-6) == LA_ROTAZIONE_DI_BASE
    assert in3d.in_piano(0.1, -massimo - 1e-6) == LA_ROTAZIONE_DI_BASE


def test_la_rotazione_del_piano_e_una_lista_di_liste_di_numeri_che_passa_per_il_json():
    rotazione = in3d.in_piano(0.3, -0.5)
    assert isinstance(rotazione, list) and len(rotazione) == 3
    assert all(isinstance(riga, list) and len(riga) == 3 for riga in rotazione)
    assert all(type(numero) is float for riga in rotazione for numero in riga)
    assert json.loads(json.dumps(rotazione)) == rotazione


@pytest.mark.parametrize("rollio", ROLLI_PROVATI)
@pytest.mark.parametrize("beccheggio", BECCHEGGI_PROVATI)
def test_la_rotazione_del_piano_e_una_rotazione_vera_e_porta_il_su_della_camera_verso_l_alto(rollio, beccheggio):
    rotazione = np.asarray(in3d.in_piano(rollio, beccheggio))
    assert rotazione.shape == (3, 3)
    assert rotazione @ rotazione.T == pytest.approx(np.eye(3), abs=1e-12)
    assert rotazione.T @ rotazione == pytest.approx(np.eye(3), abs=1e-12)
    assert np.linalg.det(rotazione) == pytest.approx(1.0, abs=1e-12)
    assert rotazione @ _su_della_camera(rollio, beccheggio) == pytest.approx([0.0, 1.0, 0.0], abs=1e-12)


@pytest.mark.parametrize("rollio", [math.pi, 2.5, -2.8])
@pytest.mark.parametrize("beccheggio", [0.0, 0.4])
def test_anche_con_il_telefono_capovolto_il_su_della_camera_va_verso_l_alto(rollio, beccheggio):
    rotazione = np.asarray(in3d.in_piano(rollio, beccheggio))
    assert rotazione @ rotazione.T == pytest.approx(np.eye(3), abs=1e-12)
    assert np.linalg.det(rotazione) == pytest.approx(1.0, abs=1e-12)
    assert rotazione @ _su_della_camera(rollio, beccheggio) == pytest.approx([0.0, 1.0, 0.0], abs=1e-12)


@pytest.mark.parametrize("rollio", ROLLI_PROVATI)
@pytest.mark.parametrize("beccheggio", BECCHEGGI_PROVATI)
def test_il_beccheggio_positivo_alza_lo_sguardo_e_l_avanti_orizzontale_va_verso_meno_z(rollio, beccheggio):
    avanti = np.asarray(in3d.in_piano(rollio, beccheggio)) @ np.array([0.0, 0.0, 1.0])
    assert avanti[1] == pytest.approx(math.sin(beccheggio), abs=1e-12)
    assert bool(avanti[1] > 0) == (beccheggio > 0)
    assert avanti[0] == pytest.approx(0.0, abs=1e-12)
    assert avanti[2] < 0
    assert avanti[2] == pytest.approx(-math.cos(beccheggio), abs=1e-12)


@pytest.mark.parametrize("rollio", [-0.5, -0.25, -0.1, 0.0, 0.1, 0.25, 0.5, 1.0])
def test_senza_beccheggio_la_macchina_guarda_dritta_verso_meno_z(rollio):
    avanti = np.asarray(in3d.in_piano(rollio, 0.0)) @ np.array([0.0, 0.0, 1.0])
    assert avanti == pytest.approx([0.0, 0.0, -1.0], abs=1e-12)


@pytest.mark.parametrize("rollio", [0.1, 0.25, 0.5, 1.0])
def test_con_il_rollio_positivo_l_orizzonte_di_geocalib_scende_a_sinistra_e_sale_a_destra(rollio):
    rotazione = np.asarray(in3d.in_piano(rollio, 0.0))
    mezza_larghezza, fuoco = 0.75, 1.1
    a_sinistra, a_destra = _orizzonte_di_geocalib(rollio, mezza_larghezza, fuoco)
    assert a_sinistra[1] > 0 > a_destra[1]
    assert (rotazione @ a_sinistra)[1] == pytest.approx(0.0, abs=1e-12)
    assert (rotazione @ a_destra)[1] == pytest.approx(0.0, abs=1e-12)
    a_destra_sulla_riga_centrale = np.array([mezza_larghezza, 0.0, fuoco])
    a_sinistra_sulla_riga_centrale = np.array([-mezza_larghezza, 0.0, fuoco])
    assert (rotazione @ a_destra_sulla_riga_centrale)[1] < 0
    assert (rotazione @ a_sinistra_sulla_riga_centrale)[1] > 0


@pytest.mark.parametrize("rollio", [-0.1, -0.25, -0.5, -1.0])
def test_con_il_rollio_negativo_l_orizzonte_di_geocalib_sale_a_sinistra_e_scende_a_destra(rollio):
    rotazione = np.asarray(in3d.in_piano(rollio, 0.0))
    mezza_larghezza, fuoco = 0.75, 1.1
    a_sinistra, a_destra = _orizzonte_di_geocalib(rollio, mezza_larghezza, fuoco)
    assert a_sinistra[1] < 0 < a_destra[1]
    assert (rotazione @ a_sinistra)[1] == pytest.approx(0.0, abs=1e-12)
    assert (rotazione @ a_destra)[1] == pytest.approx(0.0, abs=1e-12)
    assert (rotazione @ np.array([mezza_larghezza, 0.0, fuoco]))[1] > 0
    assert (rotazione @ np.array([-mezza_larghezza, 0.0, fuoco]))[1] < 0


@pytest.mark.parametrize("rollio", ROLLI_PROVATI)
@pytest.mark.parametrize("beccheggio", BECCHEGGI_PROVATI)
def test_l_asse_x_della_camera_sta_sotto_l_orizzonte_quando_il_rollio_e_positivo(rollio, beccheggio):
    a_destra = np.asarray(in3d.in_piano(rollio, beccheggio)) @ np.array([1.0, 0.0, 0.0])
    assert a_destra[1] == pytest.approx(-math.sin(rollio) * math.cos(beccheggio), abs=1e-12)
    assert bool(a_destra[1] < 0) == (rollio > 0)


@pytest.mark.parametrize("rollio", ROLLI_PROVATI)
@pytest.mark.parametrize("beccheggio", BECCHEGGI_PROVATI)
def test_l_angolo_sopra_l_orizzonte_di_geocalib_e_lo_stesso_nel_mondo(rollio, beccheggio):
    rotazione = np.asarray(in3d.in_piano(rollio, beccheggio))
    su = _su_della_camera(rollio, beccheggio)
    for raggio in RAGGI_DELLA_CAMERA:
        raggio = np.asarray(raggio) / np.linalg.norm(raggio)
        sopra_l_orizzonte = math.asin(float(raggio @ su))
        assert math.asin(float((rotazione @ raggio)[1])) == pytest.approx(sopra_l_orizzonte, abs=1e-12)
    assert math.asin(float((rotazione @ np.array([0.0, 0.0, 1.0]))[1])) == pytest.approx(beccheggio, abs=1e-12)


@pytest.mark.parametrize("rollio", ROLLI_PROVATI)
@pytest.mark.parametrize("beccheggio", BECCHEGGI_PROVATI)
def test_un_bastone_in_piedi_nel_mondo_visto_dalla_camera_torna_in_piedi_con_il_piano(rollio, beccheggio):
    piano = in3d.in_piano(rollio, beccheggio)
    rotazione = np.asarray(piano)
    altezze = np.linspace(0.0, 1.8, 10)
    nel_mondo = np.stack([np.zeros(10), altezze, np.full(10, -3.0)], axis=1)
    nella_camera = nel_mondo @ rotazione
    tornato = in3d.nella_scena(nella_camera, [0.0, 0.0, 0.0], 1.0, 1.5, None, piano)
    assert tornato[:, 0] == pytest.approx(np.zeros(10), abs=1e-12)
    assert tornato[:, 1] == pytest.approx(altezze, abs=1e-12)
    assert tornato[:, 2] == pytest.approx(np.full(10, -3.0), abs=1e-12)
    storto = in3d.nella_scena(nella_camera, [0.0, 0.0, 0.0], 1.0, 1.5, None)
    assert np.ptp(storto[:, 0]) > 0.05 or np.ptp(storto[:, 2]) > 0.05
    lungo_il_su = np.outer(altezze, _su_della_camera(rollio, beccheggio))
    dritto = in3d.nella_scena(lungo_il_su, [0.0, 0.0, 0.0], 1.0, 1.5, None, piano)
    assert dritto[:, 0] == pytest.approx(np.zeros(10), abs=1e-12)
    assert dritto[:, 1] == pytest.approx(altezze, abs=1e-12)
    assert dritto[:, 2] == pytest.approx(np.zeros(10), abs=1e-12)


def test_il_piano_di_base_e_il_piano_che_manca_danno_gli_stessi_punti_ribaltati():
    vertici = [[0.0, 0.0, 0.0], [1.0, 2.0, 3.0]]
    senza = in3d.nella_scena(vertici, [0.5, -1.0, 4.0], 1.0, 1.5, None)
    assert senza.tolist() == [[0.5, 1.0, -4.0], [1.5, -1.0, -7.0]]
    assert in3d.nella_scena(vertici, [0.5, -1.0, 4.0], 1.0, 1.5, None, in3d.DI_BASE).tolist() == senza.tolist()
    assert in3d.nella_scena(vertici, [0.5, -1.0, 4.0], 1.0, 1.5, None, in3d.in_piano(0.0, 0.0)).tolist() == (
        senza.tolist())
    assert in3d.nella_scena(vertici, [0.5, -1.0, 4.0], 1.0, 1.5, None, in3d.in_piano(None, None)).tolist() == (
        senza.tolist())


def test_con_la_macchina_della_stanza_il_piano_non_conta_niente():
    macchina = _macchina(2 * math.atan(0.25), centro=(1.0, 2.0, 3.0), rotazione=_rotazione_che_guarda(0.4))
    vertici = [[0.0, 0.0, 0.0], [0.3, -0.2, 0.1]]
    senza = in3d.nella_scena(vertici, [0.1, 0.2, 3.0], 2.0, 1.5, macchina)
    con = in3d.nella_scena(vertici, [0.1, 0.2, 3.0], 2.0, 1.5, macchina, in3d.in_piano(0.5, 0.9))
    assert con.tolist() == senza.tolist()


def test_il_binario_tiene_i_pezzi_a_quattro_byte_anche_con_le_lettere_accentate():
    dati = in3d._binario(b"PROV", {"nome": "città"}, [b"abc", b"", b"12345678"])
    testa, posto = _testa(dati, b"PROV")
    assert testa == {"nome": "città"}
    assert dati[posto:] == b"abc\0" + b"" + b"12345678"
    assert len(dati) % 4 == 0


def test_con_le_persone_ma_senza_stanza_c_e_il_piano(con_i_corpi):
    archivio = con_i_corpi
    scatto_id = _scatti_con_le_superfici(archivio)[0]
    assert _c_e(archivio, scatto_id)
    dati = _scena(archivio, scatto_id)
    assert dati["scatto_id"] == scatto_id
    assert dati["file_id"] == _il_principale(archivio, scatto_id)
    assert dati["proporzione"] == pytest.approx(_proporzione(archivio, scatto_id))
    assert dati["piano"] is True and dati["stanza"] is None and dati["questa_messa"] is False
    assert dati["foto"] == []
    assert len(dati["persone"]) == 2
    assert [p["numero"] for p in dati["persone"]] == [0, 1]
    assert [p["nome"] for p in dati["persone"]] == ["Persona 1 · senza volto", "Persona 2 · senza volto"]
    assert not any(p["con_nome"] for p in dati["persone"])
    assert dati["obiettivo"].endswith(" mm, stimato da Puffin")
    atteso = in3d.millimetri(CAMPO_DI_PUFFIN, dati["proporzione"])
    assert dati["obiettivo"] == f"{atteso} mm, stimato da Puffin"


def test_i_nomi_delle_persone_dicono_se_il_volto_c_e_e_se_ha_un_nome(con_i_corpi):
    from officina.modello import persone

    archivio = con_i_corpi
    scatto_id, altro_id = _scatti_con_le_superfici(archivio)[:2]
    prima = _scena(archivio, scatto_id)["persone"]
    primo, secondo = (p["corpo_id"] for p in prima)
    with archivio.scrittura() as connessione:
        ada = persone.crea(connessione, "Ada")
        connessione.execute("UPDATE corpi SET volto_id = ? WHERE id = ?",
                            (_un_volto(connessione, scatto_id, ada), primo))
        connessione.execute("UPDATE corpi SET volto_id = ? WHERE id = ?",
                            (_un_volto(connessione, scatto_id, None), secondo))
    dopo = _scena(archivio, scatto_id)["persone"]
    assert [(p["corpo_id"], p["numero"], p["nome"], p["con_nome"]) for p in dopo] == [
        (primo, 0, "Ada", True), (secondo, 1, "Persona 2 · volto senza nome", False)]
    assert [p["nome"] for p in _scena(archivio, altro_id)["persone"]] == [
        "Persona 1 · senza volto", "Persona 2 · senza volto"]


def test_le_persone_senza_stanza_vanno_a_terra_e_hanno_una_macchina_di_base(con_i_corpi):
    archivio = con_i_corpi
    scatto_id = _scatti_con_le_superfici(archivio)[0]
    letto = _persone_lette(in3d.persone_in_binario(archivio, scatto_id))
    testa, facce = letto["testa"], letto["facce"]
    facce_vere = superfici.leggi_le_facce(archivio.dove.superfici)
    assert testa["facce"] == len(facce_vere) == len(facce) > 0
    assert testa["grandi"] is False
    assert (facce == facce_vere).all()
    nella_scena = _scena(archivio, scatto_id)["persone"]
    assert [p["corpo_id"] for p in letto["persone"]] == [p["corpo_id"] for p in nella_scena]
    with archivio.lettura() as connessione:
        righe = superfici.di_scatto(connessione, scatto_id)
        fuochi = [figure.figura_di(connessione, p["corpo_id"])["fuoco"] for p in letto["persone"]]
    tutti_i_visti = set()
    for persona, vertici in zip(letto["persone"], (p["vertici"] for p in testa["persone"]), strict=True):
        riga = righe[persona["corpo_id"]]
        assert vertici == riga["vertici"] == len(persona["posizioni"]) == len(persona["uv"])
        assert facce.max() < vertici
        assert np.isfinite(persona["posizioni"]).all()
        assert persona["uv"].min() >= 0 and persona["uv"].max() <= 65535
        assert set(np.unique(persona["visti"]).tolist()) <= {0, 255}
        assert int((persona["visti"] == 255).sum()) == riga["visti"]
        tutti_i_visti |= set(np.unique(persona["visti"]).tolist())
        salvata = superfici.leggi(archivio.dove.superfici / riga["file"])
        assert (persona["visti"] == salvata["visti"] * 255).all()
        assert persona["uv"] / 65535.0 == pytest.approx(salvata["uv"], abs=1e-5)
    assert tutti_i_visti == {0, 255}
    bassi = min(float(p["posizioni"][:, 1].min()) for p in letto["persone"])
    assert bassi == pytest.approx(0.0, abs=1e-6)
    macchina = testa["macchina"]
    assert macchina["proporzione"] == pytest.approx(_proporzione(archivio, scatto_id))
    assert macchina["campo"] == pytest.approx(2 * math.atan(0.5 / np.median(fuochi)))
    inclinazione = _l_inclinazione(archivio, scatto_id)
    assert inclinazione == pytest.approx((0.01, 0.02))
    rotazione = in3d.in_piano(*inclinazione)
    assert rotazione != LA_ROTAZIONE_DI_BASE
    assert np.asarray(macchina["rotazione"]) == pytest.approx(np.asarray(rotazione), abs=1e-12)
    assert (macchina["centro_x"], macchina["centro_y"]) == (0.5, 0.5)
    assert macchina["centro"][0] == 0.0 and macchina["centro"][2] == 0.0
    _, altezza = _a_terra_a_mano(archivio, scatto_id, [p["corpo_id"] for p in letto["persone"]], rotazione)
    assert macchina["centro"][1] == pytest.approx(altezza, abs=1e-4)


@pytest.mark.parametrize("rollio, beccheggio", [(0.3, -0.5), (-0.6, 0.8)])
def test_senza_stanza_le_persone_si_raddrizzano_con_l_inclinazione_della_lente_e_poi_vanno_a_terra(
        con_i_corpi, rollio, beccheggio):
    archivio = con_i_corpi
    scatto_id = _scatti_con_le_superfici(archivio)[0]
    prima = _persone_lette(in3d.persone_in_binario(archivio, scatto_id))
    _metti_l_inclinazione(archivio, scatto_id, rollio, beccheggio)
    letto = _persone_lette(in3d.persone_in_binario(archivio, scatto_id))
    rotazione = in3d.in_piano(rollio, beccheggio)
    assert rotazione != LA_ROTAZIONE_DI_BASE
    macchina = letto["testa"]["macchina"]
    assert np.asarray(macchina["rotazione"]) == pytest.approx(np.asarray(rotazione), abs=1e-12)
    assert macchina["rotazione"] != prima["testa"]["macchina"]["rotazione"]
    assert len(letto["persone"]) == len(prima["persone"]) == 2
    corpi = [p["corpo_id"] for p in letto["persone"]]
    assert corpi == [p["corpo_id"] for p in prima["persone"]]
    a_mano, altezza = _a_terra_a_mano(archivio, scatto_id, corpi, rotazione)
    for persona, atteso, vecchia in zip(letto["persone"], a_mano, prima["persone"], strict=True):
        assert persona["posizioni"] == pytest.approx(atteso, abs=1e-4)
        assert not np.allclose(persona["posizioni"], vecchia["posizioni"], atol=1e-2)
        assert (persona["uv"] == vecchia["uv"]).all() and (persona["visti"] == vecchia["visti"]).all()
    assert min(float(p["posizioni"][:, 1].min()) for p in letto["persone"]) == pytest.approx(0.0, abs=1e-6)
    assert macchina["centro"] == pytest.approx([0.0, altezza, 0.0], abs=1e-4)


@pytest.mark.parametrize("rollio, beccheggio", [(None, None), (0.3, None), (None, -0.5), (0.3, 1.45)])
def test_se_l_inclinazione_della_lente_manca_o_e_assurda_le_persone_restano_con_la_rotazione_di_base(
        con_i_corpi, rollio, beccheggio):
    archivio = con_i_corpi
    scatto_id = _scatti_con_le_superfici(archivio)[0]
    _metti_l_inclinazione(archivio, scatto_id, rollio, beccheggio)
    letto = _persone_lette(in3d.persone_in_binario(archivio, scatto_id))
    macchina = letto["testa"]["macchina"]
    assert macchina["rotazione"] == LA_ROTAZIONE_DI_BASE
    assert len(letto["persone"]) == 2
    a_mano, altezza = _a_terra_a_mano(archivio, scatto_id, [p["corpo_id"] for p in letto["persone"]],
                                      LA_ROTAZIONE_DI_BASE)
    for persona, atteso in zip(letto["persone"], a_mano, strict=True):
        assert persona["posizioni"] == pytest.approx(atteso, abs=1e-4)
    assert min(float(p["posizioni"][:, 1].min()) for p in letto["persone"]) == pytest.approx(0.0, abs=1e-6)
    assert macchina["centro"] == pytest.approx([0.0, altezza, 0.0], abs=1e-4)


def test_senza_la_riga_dell_obiettivo_le_persone_restano_con_la_rotazione_di_base(con_i_corpi):
    archivio = con_i_corpi
    scatto_id = _scatti_con_le_superfici(archivio)[0]
    with archivio.scrittura() as connessione:
        connessione.execute("DELETE FROM obiettivi WHERE scatto_id = ?", (scatto_id,))
    assert _l_inclinazione(archivio, scatto_id) is None
    letto = _persone_lette(in3d.persone_in_binario(archivio, scatto_id))
    macchina = letto["testa"]["macchina"]
    assert macchina["rotazione"] == LA_ROTAZIONE_DI_BASE
    assert len(letto["persone"]) == 2
    a_mano, altezza = _a_terra_a_mano(archivio, scatto_id, [p["corpo_id"] for p in letto["persone"]],
                                      LA_ROTAZIONE_DI_BASE)
    for persona, atteso in zip(letto["persone"], a_mano, strict=True):
        assert persona["posizioni"] == pytest.approx(atteso, abs=1e-4)
    assert min(float(p["posizioni"][:, 1].min()) for p in letto["persone"]) == pytest.approx(0.0, abs=1e-6)
    assert macchina["centro"] == pytest.approx([0.0, altezza, 0.0], abs=1e-4)


@pytest.mark.parametrize("rollio, beccheggio", [(0.8, 1.2), (-0.7, -1.25)])
def test_con_la_stanza_l_inclinazione_della_lente_non_cambia_dove_stanno_le_persone(
        con_i_corpi, rollio, beccheggio):
    archivio = con_i_corpi
    posto_id, scatti = _la_stanza(archivio)
    questa = scatti[2]
    prima = in3d.persone_in_binario(archivio, questa)
    letto_prima = _persone_lette(prima)
    assert letto_prima["testa"]["macchina"] is None and len(letto_prima["persone"]) == 2
    _metti_l_inclinazione(archivio, questa, rollio, beccheggio)
    dopo = in3d.persone_in_binario(archivio, questa)
    letto_dopo = _persone_lette(dopo)
    assert letto_dopo["testa"] == letto_prima["testa"]
    for persona, vecchia in zip(letto_dopo["persone"], letto_prima["persone"], strict=True):
        assert persona["corpo_id"] == vecchia["corpo_id"]
        assert (persona["posizioni"] == vecchia["posizioni"]).all()
    assert dopo == prima


def test_le_facce_grandi_si_scrivono_a_quattro_byte(con_i_corpi):
    archivio = con_i_corpi
    scatto_id = _scatti_con_le_superfici(archivio)[0]
    facce = superfici.leggi_le_facce(archivio.dove.superfici)
    np.save(archivio.dove.superfici / superfici.FILE_DELLE_FACCE, facce.astype(np.uint32))
    letto = _persone_lette(in3d.persone_in_binario(archivio, scatto_id))
    assert letto["testa"]["grandi"] is True
    assert letto["facce"].dtype == np.dtype("<u4")
    assert (letto["facce"] == facce).all()
    assert len(letto["persone"]) == 2


def test_senza_il_file_delle_facce_le_persone_restano_vuote(con_i_corpi):
    archivio = con_i_corpi
    scatto_id = _scatti_con_le_superfici(archivio)[0]
    (archivio.dove.superfici / superfici.FILE_DELLE_FACCE).unlink()
    letto = _persone_lette(in3d.persone_in_binario(archivio, scatto_id))
    assert letto["persone"] == [] and letto["testa"] == {"persone": [], "facce": 0, "macchina": None}


def test_una_superficie_che_non_si_apre_si_salta_e_le_altre_restano(con_i_corpi):
    archivio = con_i_corpi
    scatto_id = _scatti_con_le_superfici(archivio)[0]
    persone = _scena(archivio, scatto_id)["persone"]
    with archivio.lettura() as connessione:
        rotta = superfici.di_scatto(connessione, scatto_id)[persone[1]["corpo_id"]]["file"]
    (archivio.dove.superfici / rotta).write_bytes(b"non e' un file di numeri")
    letto = _persone_lette(in3d.persone_in_binario(archivio, scatto_id))
    assert [p["corpo_id"] for p in letto["persone"]] == [persone[0]["corpo_id"]]
    (archivio.dove.superfici / rotta).unlink()
    letto = _persone_lette(in3d.persone_in_binario(archivio, scatto_id))
    assert [p["corpo_id"] for p in letto["persone"]] == [persone[0]["corpo_id"]]


def test_senza_niente_in_3d_la_foto_non_ha_scena(archivio_pieno, cliente):
    scatto_id = _foto_dell_archivio(archivio_pieno)[0]
    assert not _c_e(archivio_pieno, scatto_id)
    assert _scena(archivio_pieno, scatto_id) is None
    assert _scena(archivio_pieno, 999999) is None
    letto = _persone_lette(in3d.persone_in_binario(archivio_pieno, scatto_id))
    assert letto["persone"] == [] and letto["facce"] is None
    assert letto["testa"] == {"persone": [], "facce": 0, "macchina": None}
    for numero in (scatto_id, 999999):
        risposta = cliente.get(f"/api/scatto/{numero}/in3d")
        assert risposta.status_code == 404
        assert risposta.json() == {"messaggio": "Questa foto non ha ancora niente in 3D."}
    vuota = cliente.get(f"/api/scatto/{scatto_id}/in3d/persone")
    assert vuota.status_code == 200 and vuota.content == in3d.persone_in_binario(archivio_pieno, scatto_id)


def test_le_rotte_della_scena_e_delle_persone(con_i_corpi, cliente):
    from officina.web.strade import scatto as scatto_web

    archivio = con_i_corpi
    scatto_id = _scatti_con_le_superfici(archivio)[0]
    risposta = cliente.get(f"/api/scatto/{scatto_id}/in3d")
    assert risposta.status_code == 200
    assert risposta.headers["content-type"].startswith("application/json")
    dati = risposta.json()
    assert dati["piano"] is True and dati["stanza"] is None and len(dati["persone"]) == 2
    for persona in dati["persone"]:
        assert persona["colore"] == scatto_web.COLORI_CORPI[persona["numero"] % len(scatto_web.COLORI_CORPI)]
    binario = cliente.get(f"/api/scatto/{scatto_id}/in3d/persone")
    assert binario.status_code == 200
    assert binario.headers["content-type"] == "application/octet-stream"
    assert binario.headers["cache-control"] == "no-cache"
    assert binario.content == in3d.persone_in_binario(archivio, scatto_id)
    letto = _persone_lette(binario.content)
    assert [p["corpo_id"] for p in letto["persone"]] == [p["corpo_id"] for p in dati["persone"]]


def test_il_tasto_in_3d_c_e_solo_dove_c_e_qualcosa_da_vedere(archivio_pieno, cliente):
    scatto_id = _foto_dell_archivio(archivio_pieno)[2]
    fuori = _foto_dell_archivio(archivio_pieno)[10]
    pagina = cliente.get(f"/scatto/{scatto_id}")
    assert pagina.status_code == 200 and not _il_tasto_in_3d(pagina.text)
    _, scatti = _la_stanza(archivio_pieno)
    assert scatto_id in scatti and fuori not in scatti
    assert _il_tasto_in_3d(cliente.get(f"/scatto/{scatto_id}").text)
    assert not _il_tasto_in_3d(cliente.get(f"/scatto/{fuori}").text)


def test_il_tasto_in_3d_c_e_con_le_persone_ma_non_per_i_video(con_i_corpi, cliente):
    archivio = con_i_corpi
    scatto_id = _scatti_con_le_superfici(archivio)[0]
    pagina = cliente.get(f"/scatto/{scatto_id}")
    assert pagina.status_code == 200 and _il_tasto_in_3d(pagina.text)
    video = cliente.get(f"/scatto/{_un_video(archivio)}")
    assert video.status_code == 200 and not _il_tasto_in_3d(video.text)


def test_con_la_stanza_la_scena_ha_il_luogo_e_le_foto_con_questa_per_prima(con_i_corpi):
    archivio = con_i_corpi
    posto_id, scatti = _la_stanza(archivio)
    _metti_le_date(archivio, scatti)
    questa = scatti[2]
    assert _c_e(archivio, questa)
    dati = _scena(archivio, questa)
    with archivio.lettura() as connessione:
        riga = stanze.di_posto(connessione, posto_id)
    assert dati["piano"] is False and dati["questa_messa"] is True
    assert "obiettivo" not in dati
    assert len(dati["persone"]) == 2
    luogo = dati["stanza"]
    assert luogo["posto_id"] == posto_id and luogo["nome"] == "Cucina"
    assert luogo["costruita_da"] == "7 foto, dal 2019 al 2022"
    assert re.fullmatch(r"\d+,\d × \d+,\d m, alta \d+,\d m", luogo["misure"])
    assert luogo["misure"] == "{} × {} m, alta {} m".format(
        *(f"{riga[k]:.1f}".replace(".", ",") for k in ("larga", "lunga", "alta")))
    assert (luogo["larga"], luogo["lunga"], luogo["alta"]) == (riga["larga"], riga["lunga"], riga["alta"])
    assert luogo["versione"] == f"{riga['versione']}-{riga['costruita_il']}"
    ordine = [scatti[i] for i in (2, 4, 1, 3, 0, 5, 6)]
    assert [f["scatto_id"] for f in dati["foto"]] == ordine
    assert [f["questa"] for f in dati["foto"]] == [True] + [False] * 6
    assert [f["data"] for f in dati["foto"]][:3] == ["30 novembre 2020", "9 gennaio 2019", "2 marzo 2021"]
    assert dati["foto"][-1]["data"] == "senza data"
    for f in dati["foto"]:
        assert f["file_id"] == _il_principale(archivio, f["scatto_id"])
        assert set(f) == {"scatto_id", "file_id", "questa", "data", "centro", "rotazione", "campo", "centro_x",
                          "centro_y", "proporzione", "allungo", "descrizione", "obiettivo", "versione"}
        assert re.fullmatch(r"da \d+,\d m di altezza, guardando [a-z' ùài]+", f["descrizione"])
        assert f["proporzione"] == pytest.approx(_proporzione(archivio, f["scatto_id"]), abs=0.02)
        assert len(f["centro"]) == 3 and len(f["rotazione"]) == 3


def test_gli_obiettivi_delle_foto_della_stanza_seguono_la_fonte(con_i_corpi):
    archivio = con_i_corpi
    posto_id, scatti = _la_stanza(archivio)
    con_dati, con_base, senza_riga = scatti[3], scatti[4], scatti[5]
    with archivio.scrittura() as connessione:
        connessione.execute("UPDATE obiettivi SET fonte = 'exif' WHERE scatto_id = ?", (con_dati,))
        connessione.execute("UPDATE obiettivi SET fonte = 'base' WHERE scatto_id = ?", (con_base,))
        connessione.execute("DELETE FROM obiettivi WHERE scatto_id = ?", (senza_riga,))
    foto = {f["scatto_id"]: f for f in _scena(archivio, scatti[0])["foto"]}
    with archivio.lettura() as connessione:
        campi = {f["scatto_id"]: f["campo"] for f in stanze.foto_di(connessione, posto_id)}
    for scatto_id, f in foto.items():
        proporzione = f["proporzione"]
        puffin = in3d.millimetri(CAMPO_DI_PUFFIN, proporzione)
        della_stanza = in3d.millimetri(campi[scatto_id], proporzione)
        atteso = {con_dati: f"{puffin} mm, dai dati della foto",
                  con_base: f"{della_stanza} mm, stimato dalla stanza",
                  senza_riga: f"{della_stanza} mm, stimato dalla stanza"
                  }.get(scatto_id, f"{puffin} mm, stimato da Puffin")
        assert f["obiettivo"] == atteso


def test_le_persone_stanno_dove_la_macchina_della_stanza_le_vede(con_i_corpi):
    archivio = con_i_corpi
    posto_id, scatti = _la_stanza(archivio)
    questa = scatti[2]
    letto = _persone_lette(in3d.persone_in_binario(archivio, questa))
    assert letto["testa"]["macchina"] is None and len(letto["persone"]) == 2
    with archivio.lettura() as connessione:
        macchina = next(f for f in stanze.foto_di(connessione, posto_id) if f["scatto_id"] == questa)
        righe = superfici.di_scatto(connessione, questa)
        fuochi = {p["corpo_id"]: figure.figura_di(connessione, p["corpo_id"])["fuoco"] for p in letto["persone"]}
    fuoco_stanza = 0.5 / math.tan(macchina["campo"] / 2)
    rotazione = np.asarray(macchina["rotazione"])
    proporzione = _proporzione(archivio, questa)
    for persona in letto["persone"]:
        salvata = superfici.leggi(archivio.dove.superfici / righe[persona["corpo_id"]]["file"])
        nella_macchina = (persona["posizioni"].astype(np.float64) - np.asarray(macchina["centro"])) @ rotazione
        spostati = nella_macchina - salvata["locali"]
        assert spostati.std(axis=0) == pytest.approx([0.0, 0.0, 0.0], abs=1e-3)
        fuoco = fuochi[persona["corpo_id"]]
        profondita = float(salvata["spostamento"][2])
        atteso = [float(salvata["spostamento"][0]) - (macchina["centro_x"] - 0.5) * proporzione * profondita / fuoco,
                  float(salvata["spostamento"][1]) - (macchina["centro_y"] - 0.5) * profondita / fuoco,
                  profondita * fuoco_stanza / fuoco]
        assert spostati.mean(axis=0) == pytest.approx(atteso, abs=1e-3)


def test_la_stanza_c_e_anche_senza_persone_e_le_altre_foto_no(archivio_pieno):
    posto_id, scatti = _la_stanza(archivio_pieno)
    fuori = _foto_dell_archivio(archivio_pieno)[10]
    assert all(_c_e(archivio_pieno, s) for s in scatti)
    assert not _c_e(archivio_pieno, fuori)
    dati = _scena(archivio_pieno, scatti[0])
    assert dati["persone"] == [] and dati["stanza"]["nome"] == "Cucina" and dati["questa_messa"] is True
    assert len(dati["foto"]) == 7 and dati["foto"][0]["questa"] is True
    letto = _persone_lette(in3d.persone_in_binario(archivio_pieno, scatti[0]))
    assert letto["persone"] == []


def test_una_foto_nel_luogo_ma_non_ancora_nella_stanza_non_mostra_le_persone(con_i_corpi):
    from officina.modello import posti

    archivio = con_i_corpi
    posto_id, scatti = _la_stanza(archivio, quante=6)
    nuova = _foto_dell_archivio(archivio)[6]
    with archivio.scrittura() as connessione:
        posti.metti(connessione, nuova, posto_id)
    assert _c_e(archivio, nuova)
    dati = _scena(archivio, nuova)
    assert dati["stanza"]["nome"] == "Cucina" and dati["questa_messa"] is False and dati["piano"] is False
    assert dati["persone"] == []
    assert sorted(f["scatto_id"] for f in dati["foto"]) == sorted(scatti)
    assert not any(f["questa"] for f in dati["foto"])
    assert dati["obiettivo"] == f"{in3d.millimetri(CAMPO_DI_PUFFIN, dati['proporzione'])} mm, stimato da Puffin"
    assert _persone_lette(in3d.persone_in_binario(archivio, nuova))["persone"] == []


def test_se_la_foto_e_in_due_stanze_vince_quella_piu_dentro(archivio_pieno):
    from officina.modello import posti

    scatti = _foto_dell_archivio(archivio_pieno)[:6]
    with archivio_pieno.scrittura() as connessione:
        casa = posti.crea(connessione, "Casa", posti.crea(connessione, "Italia"))
        angolo = posti.crea(connessione, "Angolo", posti.crea(connessione, "Salotto", casa))
        cucina = posti.crea(connessione, "Cucina", casa)
        for scatto_id in scatti:
            posti.metti(connessione, scatto_id, angolo)
            posti.metti(connessione, scatto_id, cucina)
    assert angolo < cucina
    costruzione.Passata(archivio_pieno, modelli=ModelliFinti()).esegui()
    with archivio_pieno.lettura() as connessione:
        assert [s["posto_id"] for s in stanze.di_scatto(connessione, scatti[0])] == [angolo, cucina]
    dati = _scena(archivio_pieno, scatti[0])
    assert dati["stanza"]["posto_id"] == angolo and dati["stanza"]["nome"] == "Angolo"


def test_una_stanza_non_riuscita_o_nel_cestino_non_conta(archivio_pieno):
    posto_id, scatti = _la_stanza(archivio_pieno)
    mancata = _foto_dell_archivio(archivio_pieno)[8:14]
    altro_id = _un_posto_con(archivio_pieno, mancata, "Giardino")
    costruzione.Passata(archivio_pieno, modelli=ModelliFinti(rotti=True)).esegui()
    with archivio_pieno.lettura() as connessione:
        assert stanze.di_posto(connessione, altro_id)["stato"] == stanze.NON_RIUSCITA
    assert not any(_c_e(archivio_pieno, s) for s in mancata)
    assert all(_c_e(archivio_pieno, s) for s in scatti)
    with archivio_pieno.scrittura() as connessione:
        connessione.execute("UPDATE posti SET stato = 'cestino' WHERE id = ?", (posto_id,))
    assert not any(_c_e(archivio_pieno, s) for s in scatti)
    assert _scena(archivio_pieno, scatti[0]) is None


def test_la_nuvola_torna_dal_binario_entro_la_quantizzazione(archivio_pieno):
    posto_id, _ = _la_stanza(archivio_pieno)
    with archivio_pieno.lettura() as connessione:
        riga = stanze.di_posto(connessione, posto_id)
    originali, colori = costruzione.leggi_la_nuvola(archivio_pieno.dove.stanze / riga["file"])
    letta = _nuvola_letta(in3d.nuvola_in_binario(archivio_pieno, posto_id))
    testa = letta["testa"]
    assert testa["punti"] == riga["punti"] == len(originali) == len(letta["punti"]) > 0
    assert testa["centro"] == pytest.approx(((originali.min(axis=0) + originali.max(axis=0)) / 2).tolist())
    assert testa["mezzo"] == pytest.approx(((originali.max(axis=0) - originali.min(axis=0)) / 2).tolist())
    passo = np.asarray(testa["mezzo"]) / 32767.0
    assert (np.abs(letta["punti"] - originali) <= passo + 1e-5).all()
    assert np.abs(letta["stretti"]).max() == 32767
    assert (letta["colori"] == colori).all()


def test_una_nuvola_con_pochi_punti_dispari_si_riempie_e_si_legge(archivio_pieno):
    posto_id, _ = _la_stanza(archivio_pieno)
    with archivio_pieno.lettura() as connessione:
        riga = stanze.di_posto(connessione, posto_id)
    punti = np.array([[0, 0, 0], [1, 2, 3], [-1, -2, -3], [0.5, 1, -1.5], [1, -2, 3]], dtype=np.float64)
    colori = np.arange(15, dtype=np.uint8).reshape(5, 3)
    costruzione._salva_la_nuvola(archivio_pieno.dove.stanze / riga["file"], punti, colori)
    dati = in3d.nuvola_in_binario(archivio_pieno, posto_id)
    letta = _nuvola_letta(dati)
    assert letta["testa"] == {"punti": 5, "centro": [0.0, 0.0, 0.0], "mezzo": [1.0, 2.0, 3.0], "gruppi": [5]}
    assert len(dati) == _testa(dati, in3d.FIRMA_NUVOLA)[1] + 32 + 16
    assert letta["punti"] == pytest.approx(punti, abs=1e-4)
    assert (letta["colori"] == colori).all()


def test_una_nuvola_vuota_ha_solo_l_intestazione(archivio_pieno):
    posto_id, _ = _la_stanza(archivio_pieno)
    with archivio_pieno.lettura() as connessione:
        riga = stanze.di_posto(connessione, posto_id)
    costruzione._salva_la_nuvola(archivio_pieno.dove.stanze / riga["file"], np.zeros((0, 3)),
                                 np.zeros((0, 3), dtype=np.uint8))
    dati = in3d.nuvola_in_binario(archivio_pieno, posto_id)
    testa, fine = _testa(dati, in3d.FIRMA_NUVOLA)
    assert testa == {"punti": 0, "centro": [0, 0, 0], "mezzo": [1, 1, 1], "gruppi": []}
    assert fine == len(dati)


def test_la_rotta_della_nuvola_da_il_binario_e_dice_di_no_dove_non_c_e(archivio_pieno, cliente):
    posto_id, scatti = _la_stanza(archivio_pieno)
    risposta = cliente.get(f"/api/stanza/{posto_id}/nuvola")
    assert risposta.status_code == 200
    assert risposta.headers["content-type"] == "application/octet-stream"
    assert risposta.headers["cache-control"] == "private, max-age=86400"
    assert risposta.content == in3d.nuvola_in_binario(archivio_pieno, posto_id)
    assert _nuvola_letta(risposta.content)["testa"]["punti"] > 0
    assert cliente.get("/api/stanza/999999/nuvola").status_code == 404
    senza = _un_posto_con(archivio_pieno, _foto_dell_archivio(archivio_pieno)[10:12], "Cortile")
    assert cliente.get(f"/api/stanza/{senza}/nuvola").status_code == 404
    mancata = _un_posto_con(archivio_pieno, _foto_dell_archivio(archivio_pieno)[12:18], "Giardino")
    costruzione.Passata(archivio_pieno, modelli=ModelliFinti(rotti=True)).esegui()
    assert cliente.get(f"/api/stanza/{mancata}/nuvola").status_code == 404
    with archivio_pieno.lettura() as connessione:
        file = stanze.di_posto(connessione, posto_id)["file"]
    (archivio_pieno.dove.stanze / file).unlink()
    assert in3d.nuvola_in_binario(archivio_pieno, posto_id) is None
    assert cliente.get(f"/api/stanza/{posto_id}/nuvola").status_code == 404


def test_la_scena_con_la_stanza_passa_dalla_rotta(con_i_corpi, cliente):
    archivio = con_i_corpi
    posto_id, scatti = _la_stanza(archivio)
    risposta = cliente.get(f"/api/scatto/{scatti[1]}/in3d")
    assert risposta.status_code == 200
    dati = risposta.json()
    assert dati["stanza"]["nome"] == "Cucina" and dati["stanza"]["posto_id"] == posto_id
    assert dati["foto"][0]["scatto_id"] == scatti[1] and dati["foto"][0]["questa"] is True
    assert len(dati["foto"]) == 7 and len(dati["persone"]) == 2
    assert all(p["colore"].startswith("#") for p in dati["persone"])


def test_la_foto_intera_e_un_jpeg_e_si_puo_rimpicciolire(archivio_pieno, cliente):
    scatto_id = _foto_dell_archivio(archivio_pieno)[2]
    file_id = _il_principale(archivio_pieno, scatto_id)
    intera = cliente.get(f"/in3d/foto/{file_id}")
    assert intera.status_code == 200
    assert intera.headers["content-type"] == "image/jpeg"
    assert intera.headers["cache-control"] == "private, no-cache"
    assert intera.headers["etag"].startswith('W/"')
    assert cliente.get(f"/in3d/foto/{file_id}",
                       headers={"if-none-match": intera.headers["etag"]}).status_code == 304
    assert intera.content[:2] == b"\xff\xd8"
    larga, alta = Image.open(io.BytesIO(intera.content)).size
    assert (larga, alta) == (800, 600)
    piccola = cliente.get(f"/in3d/foto/{file_id}", params={"lato": 400})
    assert piccola.status_code == 200 and piccola.headers["content-type"] == "image/jpeg"
    assert Image.open(io.BytesIO(piccola.content)).size == (400, 300)
    minima = cliente.get(f"/in3d/foto/{file_id}", params={"lato": 10})
    assert Image.open(io.BytesIO(minima.content)).size == (256, 192)


def test_la_foto_intera_dice_di_no_se_non_e_un_immagine_o_non_c_e(archivio_pieno, cliente):
    assert cliente.get("/in3d/foto/999999").status_code == 404
    video = _il_principale(archivio_pieno, _un_video(archivio_pieno))
    assert cliente.get(f"/in3d/foto/{video}").status_code == 404


def test_le_foto_della_stanza_hanno_l_allungo_dell_obiettivo(con_i_corpi):
    posto_id, scatti = _la_stanza(con_i_corpi)
    dati = _scena(con_i_corpi, scatti[0])
    assert [f["allungo"] for f in dati["foto"]] == pytest.approx([1.0] * len(scatti))


def test_una_foto_messa_fuori_archivio_esce_dalla_stanza(con_i_corpi):
    archivio = con_i_corpi
    posto_id, scatti = _la_stanza(archivio)
    with archivio.scrittura() as connessione:
        connessione.execute("UPDATE scatti SET fuori_archivio = 1 WHERE id = ?", (scatti[0],))
    with archivio.lettura() as connessione:
        assert stanze.di_scatto(connessione, scatti[0]) == []
        assert [s["nome"] for s in stanze.di_scatto(connessione, scatti[1])] == ["Cucina"]
    dati = _scena(archivio, scatti[0])
    assert dati["questa_messa"] is False and dati["persone"] == []
    assert scatti[0] not in [f["scatto_id"] for f in dati["foto"]]


def test_una_figura_rovinata_si_salta_e_le_altre_persone_restano(con_i_corpi):
    archivio = con_i_corpi
    scatto_id = _scatti_con_le_superfici(archivio)[0]
    with archivio.scrittura() as connessione:
        corpo_id = connessione.execute(
            "SELECT a.corpo_id FROM aspetti a JOIN corpi c ON c.id = a.corpo_id "
            "WHERE c.scatto_id = ? AND a.modello = ? ORDER BY a.corpo_id LIMIT 1",
            (scatto_id, figure.ASPETTO)).fetchone()["corpo_id"]
        connessione.execute("UPDATE aspetti SET vettore = ? WHERE corpo_id = ? AND modello = ?",
                            (b"\0" * 8, corpo_id, figure.ASPETTO))
    letta = _persone_lette(in3d.persone_in_binario(archivio, scatto_id))
    rimaste = [p["corpo_id"] for p in letta["testa"]["persone"]]
    assert rimaste and corpo_id not in rimaste
