from __future__ import annotations

import html
import json
import math
import random
import re
import sqlite3
import time
from datetime import datetime
from pathlib import Path

import pytest

from officina import registro
from officina.archivio import migrazioni
from officina.archivio.database import scrivi_impostazione, tutti, uno
from officina.importazione import gruppi
from officina.miglioria import coda, lavoro, misura, previsione
from officina.programma import aspetto
from prove.test_miglioria import SCELTI, cartella, importato
from prove.test_miglioria import _metti as _metti_davvero
from prove.test_web_miglioramento import cliente

pytest.importorskip("av")

__all__ = ["cartella", "cliente", "importato"]

NUOVA = "7b-fp16"
QUANTE = 150
VECCHIA = "7b-fp8"
ORA = datetime(2026, 11, 2, 9, 0).timestamp()


@pytest.fixture(autouse=True)
def _dimentica():
    previsione._imparato.clear()
    yield
    previsione._imparato.clear()


def _file(genere="immagine", larghezza=640, altezza=480, dimensione=2_000_000,
          formato="JPEG", durata_ms=None, fps=None) -> dict:
    return {"genere": genere, "larghezza": larghezza, "altezza": altezza,
            "dimensione": dimensione, "formato": formato, "durata_ms": durata_ms,
            "fps": fps}


def _foto(larghezza, altezza, **campi) -> dict:
    return previsione.fattori(_file(larghezza=larghezza, altezza=altezza), **campi)


def _vera(dati: dict) -> float:
    secondi = 40.0 * dati["arrivo"]
    if dati["sfida"]:
        secondi *= 3
    if dati["disco"]:
        secondi *= 1.5
    return secondi * (1 + dati["volti"]) ** 0.5


def _a_caso(quante: int, seme: int = 7) -> list[tuple[dict, float]]:
    caso = random.Random(seme)
    fuori = []
    for _ in range(quante):
        larghezza = caso.choice((320, 640, 1024, 1600, 1920, 3000))
        dati = _foto(larghezza, larghezza * 3 // 4, sfida=caso.random() < 0.3,
                     disco=caso.random() < 0.3, volti=caso.choice((0, 0, 1, 3)))
        fuori.append((dati, _vera(dati) * math.exp(caso.gauss(0, 0.05))))
    return fuori


def _sbaglia(imparato, prove) -> float:
    return max(abs(imparato.secondi(dati) - secondi) / secondi for dati, secondi in prove)


def test_i_fattori_di_una_foto():
    dati = previsione.fattori(_file(), volti=2, dall_archivio=True, sfida=True,
                              disco=True, a_freddo=True, intensita=80)
    larghezza, altezza = misura.di_arrivo(640, 480)
    assert dati == {"genere": "immagine", "formato": "jpeg", "mb": 2.0, "volti": 2,
                    "dall_archivio": True, "sfida": True, "disco": True, "a_freddo": True,
                    "intensita": 80, "lucidflux": False, "megapixel": 640 * 480 / 1e6,
                    "arrivo": larghezza * altezza / 1e6, "durata": None,
                    "fotogrammi": None, "fluidi": 0, "fluido": ""}
    assert json.loads(json.dumps(dati)) == dati


def test_i_fattori_di_un_video():
    dati = previsione.fattori(_file("video", 1280, 720, 9_000_000, "mov", 4000, 30.0))
    assert dati["durata"] == 4.0 and dati["fotogrammi"] == 120.0
    assert dati["arrivo"] == 3840 * 2160 / 1e6
    assert not any(dati[nome] for nome in previsione.SI_O_NO)
    assert dati["intensita"] == 100 and dati["volti"] == 0


def test_i_fattori_seguono_la_misura_scelta_e_lucidflux():
    dati = previsione.fattori(_file("video", 1280, 720, 9_000_000, "mov", 4000, 30.0),
                              tetto="fhd")
    assert dati["arrivo"] == 1920 * 1080 / 1e6
    dati = previsione.fattori(_file(), tetto="2k", lucidflux=True)
    larghezza, altezza = misura.di_arrivo(640, 480, tetto="2k")
    assert dati["arrivo"] == larghezza * altezza / 1e6 and dati["lucidflux"] is True


@pytest.mark.parametrize(("campi", "nulli"), [
    ({"fps": None}, {"fotogrammi"}),
    ({"fps": 0}, {"fotogrammi"}),
    ({"durata_ms": 0}, {"durata", "fotogrammi"}),
    ({"larghezza": None}, {"megapixel", "arrivo"}),
    ({"altezza": 0}, {"megapixel", "arrivo"}),
])
def test_quel_che_non_si_sa_resta_vuoto(campi, nulli):
    dati = previsione.fattori({**_file("video", 1280, 720, 9_000_000, "mov", 4000, 30.0),
                               **campi})
    assert {nome for nome in previsione.NUMERI if dati[nome] is None} == nulli


def test_durata_e_fotogrammi_solo_per_i_video():
    dati = previsione.fattori(_file(durata_ms=3000, fps=30.0))
    assert dati["durata"] is None and dati["fotogrammi"] is None


def test_le_colonne():
    assert previsione._colonne("immagine", ["jpeg"]) == [
        "megapixel", "arrivo", "mb", "volti", "intensita", *previsione.SI_O_NO,
        "formato:jpeg"]
    assert previsione._colonne("video", []) == [*previsione.NUMERI, *previsione.SI_O_NO]


@pytest.mark.parametrize(("dati", "colonna", "atteso"), [
    ({"formato": "jpeg"}, "formato:jpeg", 1.0),
    ({"formato": "png"}, "formato:jpeg", 0.0),
    ({"sfida": True}, "sfida", 1.0),
    ({"sfida": False}, "sfida", 0.0),
    ({}, "sfida", 0.0),
    ({"volti": 3}, "volti", math.log(4)),
    ({"volti": -2}, "volti", 0.0),
    ({"intensita": 50}, "intensita", math.log(0.5)),
    ({"intensita": 0}, "intensita", math.log(0.01)),
    ({"arrivo": 2.0}, "arrivo", math.log(2.0)),
    ({"arrivo": 0}, "arrivo", math.log(previsione.QUASI_ZERO)),
    ({"arrivo": None}, "arrivo", None),
    ({"arrivo": True}, "arrivo", None),
    ({"arrivo": "2"}, "arrivo", None),
    ({}, "arrivo", None),
])
def test_il_valore_di_ogni_colonna(dati, colonna, atteso):
    assert previsione._valore(dati, colonna) == atteso


def test_risolve_un_sistema():
    soluzione = previsione._risolvi([[0.0, 2.0, 1.0], [1.0, 1.0, 0.0], [3.0, 0.0, 1.0]],
                                    [5.0, 3.0, 6.0])
    assert soluzione == pytest.approx([1.4, 1.6, 1.8])


def test_con_meno_di_tre_file_non_prevede():
    assert previsione.impara("immagine", _a_caso(2)) is None
    assert previsione.impara("immagine", [(dati, 0.0) for dati, _s in _a_caso(5)]) is None
    assert previsione.impara("immagine", _a_caso(3)) is not None


def test_con_tre_file_uguali_prevede_quei_secondi():
    dati = _foto(640, 480)
    imparato = previsione.impara("immagine", [(dati, 100.0)] * 3)
    assert imparato.quanti == 3
    assert imparato.secondi(dati) == pytest.approx(100.0, rel=1e-3)


def test_parte_dall_idea_che_il_tempo_segue_i_pixel_di_arrivo():
    piccola, grande = {**_foto(640, 480), "arrivo": 1.0}, {**_foto(640, 480), "arrivo": 4.0}
    imparato = previsione.impara("immagine", [(piccola, 100.0)] * 3)
    rapporto = imparato.secondi(grande) / imparato.secondi(piccola)
    assert rapporto == pytest.approx(grande["arrivo"] / piccola["arrivo"], rel=0.05)


def test_per_i_video_conta_anche_quanti_fotogrammi():
    corto = previsione.fattori(_file("video", 1280, 720, 9_000_000, "mov", 2000, 30.0))
    lungo = previsione.fattori(_file("video", 1280, 720, 9_000_000, "mov", 8000, 30.0))
    imparato = previsione.impara("video", [(corto, 100.0)] * 3)
    assert imparato.secondi(lungo) / imparato.secondi(corto) == pytest.approx(4.0, rel=0.1)


def test_impara_quanto_pesa_ogni_fattore():
    imparato = previsione.impara("immagine", _a_caso(200))
    base = _foto(1024, 768)
    assert imparato.secondi(base) == pytest.approx(_vera(base), rel=0.05)
    for campi in ({"sfida": True}, {"disco": True}, {"volti": 3},
                  {"sfida": True, "disco": True, "volti": 1}):
        dati = _foto(1024, 768, **campi)
        assert imparato.secondi(dati) == pytest.approx(_vera(dati), rel=0.08), campi


def test_piu_file_finisce_meno_sbaglia():
    prove = _a_caso(80, seme=99)
    errori = [_sbaglia(previsione.impara("immagine", _a_caso(quante)), prove)
              for quante in (4, 30, 300)]
    assert errori[0] > errori[1] > errori[2]
    assert errori[2] < 0.25


def test_un_fattore_mai_visto_non_rompe_niente():
    imparato = previsione.impara("immagine", _a_caso(20))
    dati = {**_foto(1024, 768), "formato": "heic", "megapixel": None, "arrivo": None}
    secondi = imparato.secondi(dati)
    assert math.isfinite(secondi) and secondi > 0


def test_la_correzione_rende_giusta_la_somma():
    caso = random.Random(3)
    dati = _foto(1024, 768)
    misure = [(dati, 100.0 * math.exp(caso.gauss(0, 0.6))) for _ in range(400)]
    imparato = previsione.impara("immagine", misure)
    media = sum(secondi for _dati, secondi in misure) / len(misure)
    assert imparato.correzione > 1.1
    assert imparato.secondi(dati) == pytest.approx(media, rel=0.02)


def test_quel_che_manca_vale_la_media():
    imparato = previsione.impara("immagine", _a_caso(200))
    base = _foto(1024, 768)
    media = math.exp(imparato.medie["arrivo"])
    assert abs(imparato.medie["arrivo"]) > 0.3
    assert imparato.secondi({**base, "arrivo": None}) == pytest.approx(
        imparato.secondi({**base, "arrivo": media}))


def test_un_numero_enorme_non_fa_esplodere():
    imparato = previsione.impara("immagine", _a_caso(10))
    imparato.pesi = [1000.0] * len(imparato.pesi)
    assert math.isfinite(imparato.secondi(_foto(640, 480)))


@pytest.mark.parametrize(("secondi", "parole"), [
    (0, "meno di un minuto"),
    (29, "meno di un minuto"),
    (31, "circa 1 minuto"),
    (60 * 25, "circa 25 minuti"),
    (3600, "circa 1 ora"),
    (3600 + 60, "circa 1 ora e 1 minuto"),
    (2 * 3600 + 40 * 60, "circa 2 ore e 40 minuti"),
    (86400, "circa 1 giorno"),
    (86400 + 3600, "circa 1 giorno e 1 ora"),
    (5 * 86400 + 3 * 3600 + 20 * 60, "circa 5 giorni e 3 ore"),
])
def test_la_durata_a_parole(secondi, parole):
    assert previsione.durata_a_parole(secondi) == parole


@pytest.mark.parametrize(("quando", "parole"), [
    (datetime(2026, 11, 2, 14, 21), "verso le 14:20"),
    (datetime(2026, 11, 2, 14, 26), "verso le 14:30"),
    (datetime(2026, 11, 2, 23, 58), "domani verso le 00:00"),
    (datetime(2026, 11, 3, 8, 0), "domani verso le 08:00"),
    (datetime(2026, 11, 4, 14, 0), "mercoledì verso le 14:00"),
    (datetime(2026, 11, 8, 14, 0), "domenica verso le 14:00"),
    (datetime(2026, 11, 9, 14, 0), "lunedì 9 novembre verso le 14:00"),
    (datetime(2026, 12, 25, 7, 3), "venerdì 25 dicembre verso le 07:00"),
])
def test_la_fine_a_parole(quando, parole):
    assert previsione.fine_a_parole(quando, datetime(2026, 11, 2, 9, 0)) == parole


@pytest.mark.parametrize(("lavoro_adesso", "resta"), [
    ({}, 300.0),
    ({"partito_il": ORA - 100}, 200.0),
    ({"partito_il": ORA - 500}, 0.0),
    ({"partito_il": ORA + 50}, 300.0),
    ({"partito_il": "ieri"}, 300.0),
    ({"partito_il": ORA - 100, "fatti": 1, "totale": 2}, 150.0),
    ({"partito_il": ORA - 100, "fatti": 3, "totale": 2}, 0.0),
    ({"partito_il": ORA - 100, "fatti": 0, "totale": 2}, 200.0),
    ({"partito_il": ORA - 100, "fatti": 1, "totale": 0}, 200.0),
    ({"partito_il": ORA - 100, "versione": 2, "versioni": 2}, 150.0),
    ({"partito_il": ORA - 100, "versione": 1, "versioni": 2, "fatti": 3, "totale": 2},
     150.0),
    ({"partito_il": ORA - 100, "versione": 1, "versioni": 2, "fatti": 1, "totale": 2},
     -100 + 0.25 * 400 + 0.75 * 300),
])
def test_quanto_resta_del_file_in_lavoro(lavoro_adesso, resta):
    assert previsione._quanto_resta(300.0, lavoro_adesso, ORA) == pytest.approx(resta)


def _tempi(connessione, quante, versione=NUOVA, genere="immagine", secondi=60.0,
           prevista=None, **campi):
    dati = {**_foto(640, 480), "genere": genere, **campi}
    for _ in range(quante):
        previsione.registra(connessione, 1, versione, secondi, prevista, dati)


def _memoria():
    connessione = sqlite3.connect(":memory:")
    connessione.row_factory = sqlite3.Row
    migrazioni._versione_72(connessione)
    return connessione


def test_la_migrazione_72_fa_la_tabella_dei_tempi():
    assert migrazioni.MIGRAZIONI[71].versione == 72
    assert migrazioni.MIGRAZIONI[71].applica is migrazioni._versione_72
    connessione = _memoria()
    previsione.registra(connessione, 4, NUOVA, 12.5, None, _foto(640, 480))
    riga = dict(uno(connessione, "SELECT * FROM tempi_miglioria"))
    assert json.loads(riga.pop("fattori")) == _foto(640, 480)
    assert riga.pop("finita_il").endswith("Z")
    assert riga == {"id": 1, "miglioria_id": 4, "genere": "immagine", "versione": NUOVA,
                    "secondi": 12.5, "prevista": None}
    assert uno(connessione, "SELECT name FROM sqlite_master WHERE type = 'index' "
               "AND tbl_name = 'tempi_miglioria'")["name"] == "tempi_miglioria_per_genere"


def test_impara_solo_dalla_versione_e_dal_genere_giusti():
    connessione = _memoria()
    _tempi(connessione, 2)
    _tempi(connessione, 5, versione=VECCHIA, secondi=1.0)
    _tempi(connessione, 5, genere="video", secondi=1.0)
    assert previsione.prevedi(connessione, NUOVA, _foto(640, 480)) is None
    _tempi(connessione, 1)
    assert previsione.prevedi(connessione, NUOVA, _foto(640, 480)) == pytest.approx(
        60.0, rel=1e-3)


def test_si_ricalcola_dopo_ogni_file_finito():
    connessione = _memoria()
    _tempi(connessione, 3)
    prima = previsione.imparato(connessione, "immagine", NUOVA)
    assert previsione.imparato(connessione, "immagine", NUOVA) is prima
    _tempi(connessione, 3, secondi=600.0)
    dopo = previsione.imparato(connessione, "immagine", NUOVA)
    assert dopo is not prima and dopo.quanti == 6
    assert dopo.secondi(_foto(640, 480)) > 150


def test_impara_dagli_ultimi_file():
    connessione = _memoria()
    _tempi(connessione, 5, secondi=1000.0)
    _tempi(connessione, 3, secondi=10.0)
    vecchio = previsione.QUANTE_PER_IMPARARE
    try:
        previsione.QUANTE_PER_IMPARARE = 3
        assert previsione.prevedi(connessione, NUOVA, _foto(640, 480)) == pytest.approx(
            10.0, rel=1e-3)
    finally:
        previsione.QUANTE_PER_IMPARARE = vecchio


def test_si_ricalcola_anche_quando_le_ultime_sono_sempre_tante():
    connessione = _memoria()
    vecchio = previsione.QUANTE_PER_IMPARARE
    try:
        previsione.QUANTE_PER_IMPARARE = 3
        _tempi(connessione, 3, secondi=1000.0)
        assert previsione.prevedi(connessione, NUOVA, _foto(640, 480)) == pytest.approx(
            1000.0, rel=1e-3)
        _tempi(connessione, 3, secondi=10.0)
        assert previsione.prevedi(connessione, NUOVA, _foto(640, 480)) == pytest.approx(
            10.0, rel=1e-3)
    finally:
        previsione.QUANTE_PER_IMPARARE = vecchio


def test_una_riga_rovinata_si_salta():
    connessione = _memoria()
    _tempi(connessione, 3)
    for fattori in ("non json", "[1, 2]"):
        connessione.execute(
            "INSERT INTO tempi_miglioria (miglioria_id, genere, versione, secondi, fattori, "
            "finita_il) VALUES (1, 'immagine', ?, 9999, ?, 'x')", (NUOVA, fattori))
    imparato = previsione.imparato(connessione, "immagine", NUOVA)
    assert imparato.quanti == 3


def test_quanto_sbaglia():
    connessione = _memoria()
    _tempi(connessione, 2, secondi=100.0, prevista=110.0)
    assert previsione.errore(connessione, NUOVA) is None
    _tempi(connessione, 3, secondi=100.0)
    _tempi(connessione, 1, versione=VECCHIA, secondi=100.0, prevista=900.0)
    assert previsione.errore(connessione, NUOVA) is None
    _tempi(connessione, 1, secondi=100.0, prevista=70.0)
    assert previsione.errore(connessione, NUOVA) == (3, pytest.approx(0.1))
    _tempi(connessione, 1, secondi=200.0, prevista=100.0)
    assert previsione.errore(connessione, NUOVA) == (4, pytest.approx(0.2))


def test_quanto_sbaglia_guarda_gli_ultimi_venti():
    connessione = _memoria()
    _tempi(connessione, 30, secondi=100.0, prevista=200.0)
    _tempi(connessione, 20, secondi=100.0, prevista=105.0)
    assert previsione.errore(connessione, NUOVA) == (20, pytest.approx(0.05))


def _metti(archivio, *nomi: str) -> None:
    with archivio.scrittura() as connessione:
        for nome in nomi:
            riga = uno(connessione, "SELECT file_id, percorso FROM percorsi WHERE nome = ?",
                       nome)
            connessione.execute(
                "INSERT INTO migliorie (file_id, stato, impronta_originale, "
                "percorso_originale, messa_il) VALUES (?, ?, 'i', ?, '2026-01-01')",
                (riga["file_id"], coda.IN_CODA, riga["percorso"]))


def _segna(archivio, nome: str, stato: str) -> int:
    with archivio.scrittura() as connessione:
        riga = uno(connessione, "SELECT m.id FROM migliorie m JOIN percorsi p "
                   "ON p.file_id = m.file_id WHERE p.nome = ?", nome)
        connessione.execute("UPDATE migliorie SET stato = ? WHERE id = ?",
                            (stato, riga["id"]))
    return riga["id"]


def _impara_le_foto(archivio, secondi=100.0, prevista=None, quante=3):
    with archivio.scrittura() as connessione:
        _tempi(connessione, quante, secondi=secondi, prevista=prevista)


def _impara_i_video(archivio, secondi=1000.0):
    with archivio.scrittura() as connessione:
        dati = previsione.fattori(_file("video", 1280, 720, 9_000_000, "mov", 4000, 30.0))
        for _ in range(3):
            previsione.registra(connessione, 1, NUOVA, secondi, None, dati)


def _manca(archivio, **campi):
    with archivio.lettura() as connessione:
        return previsione.quanto_manca(connessione, NUOVA, ora=ORA, **campi)


def test_senza_niente_in_coda_non_dice_niente(importato):
    assert _manca(importato) is None


def test_prima_dei_primi_file_dice_che_arriva_dopo(importato):
    _metti(importato, "piccola.jpg", "breve.MOV")
    assert _manca(importato) == {"quanti": 2, "secondi": None,
                                 "riga": f"Quanto manca: {previsione.ARRIVA_DOPO}.",
                                 "errore": ""}


def test_con_le_foto_imparate_e_i_video_no(importato):
    _metti(importato, "piccola.jpg", "grande.jpg", "breve.MOV")
    _impara_le_foto(importato)
    detto = _manca(importato)
    assert detto["riga"].startswith("Alle 2 foto in coda mancano circa ")
    assert "finisce" not in detto["riga"]
    assert detto["riga"].endswith(". Per il video in coda la previsione arriva dopo i "
                                  "primi video finiti.")


def test_con_i_video_imparati_e_le_foto_no(importato):
    _metti(importato, "piccola.jpg", "breve.MOV")
    _impara_i_video(importato)
    detto = _manca(importato)
    assert detto["riga"].startswith("Al video in coda mancano circa ")
    assert detto["riga"].endswith(". Per la foto in coda la previsione arriva dopo le "
                                  "prime foto finite.")


def test_tutto_imparato_dice_quando_finisce(importato):
    _metti(importato, "piccola.jpg", "grande.jpg", "breve.MOV")
    _impara_le_foto(importato)
    _impara_i_video(importato)
    with importato.lettura() as connessione:
        attesi = [previsione.prevedi(connessione, NUOVA, previsione.fattori(
            riga, a_freddo=posto == 0)) for posto, riga in enumerate(tutti(
                connessione, "SELECT f.* FROM migliorie m JOIN file_media f "
                "ON f.id = m.file_id ORDER BY m.id"))]
    detto = _manca(importato)
    assert detto["quanti"] == 3
    assert detto["secondi"] == pytest.approx(sum(attesi))
    momento = datetime.fromtimestamp(ORA)
    fine = previsione.fine_a_parole(
        datetime.fromtimestamp(ORA + sum(attesi)), momento)
    assert detto["riga"] == (f"Ai 3 file in coda mancano "
                             f"{previsione.durata_a_parole(sum(attesi))} "
                             f"(se lo avvii adesso, finisce {fine}).")
    acceso = _manca(importato, sta_lavorando=True)
    fine = previsione.fine_a_parole(datetime.fromtimestamp(ORA + acceso["secondi"]),
                                    momento)
    assert acceso["riga"].endswith(f"(finisce {fine}).")
    assert "se lo avvii" not in acceso["riga"]


@pytest.mark.parametrize(("nomi", "davanti"), [
    (("piccola.jpg",), "Alla foto in coda"),
    (("piccola.jpg", "grande.jpg"), "Alle 2 foto in coda"),
    (("breve.MOV",), "Al video in coda"),
])
def test_le_parole_per_quanti_sono(importato, nomi, davanti):
    _metti(importato, *nomi)
    _impara_le_foto(importato)
    _impara_i_video(importato)
    assert _manca(importato)["riga"].startswith(davanti + " mancano circa ")


def test_il_file_in_lavoro_conta_quello_che_ha_gia_fatto(importato):
    _metti(importato, "piccola.jpg", "grande.jpg")
    _impara_le_foto(importato, secondi=1000.0)
    in_lavoro = _segna(importato, "piccola.jpg", coda.IN_LAVORO)
    fermo = _manca(importato, sta_lavorando=True)["secondi"]
    adesso = {"id": in_lavoro, "prevista": 800.0, "partito_il": ORA - 300}
    assert _manca(importato, sta_lavorando=True, lavoro=adesso)["secondi"] == (
        pytest.approx(fermo - _sola(importato, "piccola.jpg") + 500.0))
    altro = {"id": in_lavoro + 100, "prevista": 1.0, "partito_il": ORA - 300}
    assert _manca(importato, sta_lavorando=True, lavoro=altro)["secondi"] == (
        pytest.approx(fermo))


def _sola(archivio, nome: str) -> float:
    with archivio.lettura() as connessione:
        riga = uno(connessione, "SELECT f.* FROM file_media f JOIN percorsi p "
                   "ON p.file_id = f.id WHERE p.nome = ?", nome)
        return previsione.prevedi(connessione, NUOVA, previsione.fattori(riga))


def test_il_file_in_lavoro_senza_prevista_usa_quella_di_adesso(importato):
    _metti(importato, "piccola.jpg")
    _impara_le_foto(importato, secondi=1000.0)
    in_lavoro = _segna(importato, "piccola.jpg", coda.IN_LAVORO)
    adesso = {"id": in_lavoro, "partito_il": ORA - 300}
    assert _manca(importato, sta_lavorando=True, lavoro=adesso)["secondi"] == (
        pytest.approx(_sola(importato, "piccola.jpg") - 300))


def test_solo_il_primo_file_parte_a_freddo_e_solo_da_fermo(importato):
    _metti(importato, "piccola.jpg", "grande.jpg")
    with importato.scrittura() as connessione:
        for a_freddo, secondi in ((False, 100.0), (True, 400.0)):
            for _ in range(QUANTE):
                previsione.registra(connessione, 1, NUOVA, secondi, None,
                                    {**_foto(640, 480), "a_freddo": a_freddo})
    fermo = _manca(importato)["secondi"]
    acceso = _manca(importato, sta_lavorando=True)["secondi"]
    assert fermo - acceso == pytest.approx(300.0, rel=0.1)


def test_la_sfida_conta_solo_per_le_foto_che_ci_stanno(importato):
    _metti(importato, "piccola.jpg", "grande.jpg", "breve.MOV")
    _impara_i_video(importato)
    with importato.scrittura() as connessione:
        for sfida, secondi in ((False, 100.0), (True, 300.0)):
            for _ in range(QUANTE):
                previsione.registra(connessione, 1, NUOVA, secondi, None,
                                    {**_foto(640, 480), "sfida": sfida})
    senza = _manca(importato, sta_lavorando=True)["secondi"]
    una = _manca(importato, sta_lavorando=True, posti_in_sfida=1)["secondi"]
    tutte = _manca(importato, sta_lavorando=True, posti_in_sfida=5)["secondi"]
    assert una - senza == pytest.approx(200.0, rel=0.1)
    assert tutte - senza == pytest.approx(400.0, rel=0.1)


def test_anche_la_foto_in_lavoro_prende_un_posto_nella_sfida(importato):
    _metti(importato, "piccola.jpg", "grande.jpg")
    with importato.scrittura() as connessione:
        for sfida, secondi in ((False, 100.0), (True, 300.0)):
            for _ in range(QUANTE):
                previsione.registra(connessione, 1, NUOVA, secondi, None,
                                    {**_foto(640, 480), "sfida": sfida})
    _segna(importato, "piccola.jpg", coda.IN_LAVORO)
    senza = _manca(importato, sta_lavorando=True)["secondi"]
    una = _manca(importato, sta_lavorando=True, posti_in_sfida=1)["secondi"]
    assert una - senza == pytest.approx(200.0, rel=0.1)


def test_il_video_non_prende_il_posto_nella_sfida(importato):
    _metti(importato, "breve.MOV", "piccola.jpg")
    _impara_i_video(importato)
    with importato.scrittura() as connessione:
        for sfida, secondi in ((False, 100.0), (True, 300.0)):
            for _ in range(QUANTE):
                previsione.registra(connessione, 1, NUOVA, secondi, None,
                                    {**_foto(640, 480), "sfida": sfida})
    senza = _manca(importato, sta_lavorando=True)["secondi"]
    una = _manca(importato, sta_lavorando=True, posti_in_sfida=1)["secondi"]
    assert una - senza == pytest.approx(200.0, rel=0.1)


def test_conta_l_intensita_della_scheda(importato):
    _metti(importato, "piccola.jpg")
    with importato.scrittura() as connessione:
        for intensita, secondi in ((100, 100.0), (50, 300.0)):
            for _ in range(QUANTE):
                previsione.registra(connessione, 1, NUOVA, secondi, None,
                                    {**_foto(640, 480), "intensita": intensita})
    assert _manca(importato, sta_lavorando=True)["secondi"] == pytest.approx(100.0, rel=0.1)
    assert _manca(importato, sta_lavorando=True, intensita=50)["secondi"] == (
        pytest.approx(300.0, rel=0.1))


def test_conta_solo_il_gruppo_scelto(importato):
    _metti(importato, "piccola.jpg")
    _impara_le_foto(importato)
    with importato.scrittura() as connessione:
        gruppo_id = gruppi.trova_o_crea(connessione, "Gruppo finto")
        gruppi.ricorda(connessione, "miglioramento", gruppo_id)
    assert _manca(importato) is None
    with importato.scrittura() as connessione:
        gruppi.ricorda(connessione, "miglioramento", None)
    assert _manca(importato)["quanti"] == 1


@pytest.mark.parametrize("nome", ["disco", "dall_archivio"])
def test_disco_e_archivio_contano(importato, nome):
    _metti(importato, "piccola.jpg")
    with importato.scrittura() as connessione:
        for si, secondi in ((False, 100.0), (True, 250.0)):
            for _ in range(QUANTE):
                previsione.registra(connessione, 1, NUOVA, secondi, None,
                                    {**_foto(640, 480), nome: si})
    assert _manca(importato, sta_lavorando=True)["secondi"] == pytest.approx(100.0, rel=0.1)
    if nome == "disco":
        assert _manca(importato, sta_lavorando=True, disco=True)["secondi"] == (
            pytest.approx(250.0, rel=0.1))
    else:
        with importato.scrittura() as connessione:
            connessione.execute("UPDATE percorsi SET presente = 0")
        assert _manca(importato, sta_lavorando=True)["secondi"] == (
            pytest.approx(250.0, rel=0.1))


def test_i_volti_contano_solo_con_faceme(importato, monkeypatch):
    _metti(importato, "piccola.jpg")
    with importato.scrittura() as connessione:
        for volti, secondi in ((0, 100.0), (2, 400.0)):
            for _ in range(QUANTE):
                previsione.registra(connessione, 1, NUOVA, secondi, None,
                                    {**_foto(640, 480), "volti": volti})
    with importato.lettura() as connessione:
        file_id = uno(connessione, "SELECT file_id FROM migliorie")["file_id"]
    monkeypatch.setattr(previsione, "_volti", lambda connessione: {file_id: 2})
    assert _manca(importato, sta_lavorando=True, faceme=True)["secondi"] == (
        pytest.approx(400.0, rel=0.1))
    assert _manca(importato, sta_lavorando=True)["secondi"] == pytest.approx(100.0, rel=0.1)


def test_conta_le_persone_con_un_nome(importato):
    _metti(importato, "piccola.jpg", "grande.jpg")
    with importato.scrittura() as connessione:
        piccola, grande = (riga["file_id"] for riga in tutti(
            connessione, "SELECT file_id FROM migliorie ORDER BY id"))
        for nome, stato in (("Anna", "attiva"), ("Bruno", "attiva"), (None, "attiva"),
                            ("Carla", "ignora")):
            connessione.execute("INSERT INTO persone (nome, stato, nata_il) "
                                "VALUES (?, ?, 'x')", (nome, stato))
        persone = [riga["id"] for riga in tutti(connessione,
                                                "SELECT id FROM persone ORDER BY id")]
        for file_id, persona, fotogramma in (
                (piccola, persone[0], 0), (piccola, persone[0], 0),
                (piccola, persone[1], 0), (piccola, persone[2], 0),
                (piccola, persone[3], 0), (grande, persone[1], 5)):
            connessione.execute(
                "INSERT INTO volti (file_id, scatto_id, persona_id, riquadro, fotogramma, "
                "area, nitidezza, sicurezza, modello, versione, trovato_il) "
                "SELECT ?, scatto_id, ?, '[0,0,1,1]', ?, 1, 1, 1, 'm', 'v', 'x' "
                "FROM file_media WHERE id = ?",
                (file_id, persona, fotogramma, file_id))
    with importato.lettura() as connessione:
        assert previsione._volti(connessione) == {piccola: 2}


def _fatta(versione=NUOVA, visti=None, miglioratore_di=None):
    def lancia(lavoro_da_fare, al_passo, ricorda):
        if visti is not None:
            visti.append(dict(miglioratore_di[-1].adesso))
        Path(lavoro_da_fare["uscita"]).write_bytes(b"fatta")
        nome = lavoro_da_fare["motori"]["foto"]
        nome = nome if nome == "lucidflux" else "seedvr2"
        return {"fatto": {"larghezza": 1663, "altezza": 1247,
                          "motori": [{"nome": nome, "versione": versione}]}}

    return lancia


def _gira(archivio, lancia, sfida=False, miglioratore_di=None):
    miglioratore = lavoro.Miglioratore(archivio, lancia=lancia, motori_scelti=SCELTI,
                                       sfidanti_pronti=lambda: sfida)
    if miglioratore_di is not None:
        miglioratore_di.append(miglioratore)
    assert miglioratore.parti()
    assert miglioratore.lavoro.aspetta_che_finisca(60)
    assert not miglioratore.lavoro.guasto, miglioratore.lavoro.guasto
    return miglioratore


def _di_nuovo_in_coda(archivio) -> None:
    with archivio.scrittura() as connessione:
        connessione.execute("UPDATE migliorie SET stato = ?, in_revisione = NULL",
                            (coda.IN_CODA,))


def _misure(archivio) -> list[dict]:
    with archivio.lettura() as connessione:
        return [dict(riga) for riga in tutti(connessione,
                                             "SELECT * FROM tempi_miglioria ORDER BY id")]


def test_la_versione_e_quella_di_seedvr2():
    assert lavoro._versione_di_seedvr2() == NUOVA


def test_ogni_file_finito_salva_i_suoi_secondi_e_i_fattori(importato):
    _metti_davvero(importato, "piccola.jpg")
    visti: list = []
    di: list = []
    for _ in range(4):
        _gira(importato, _fatta(visti=visti, miglioratore_di=di), miglioratore_di=di)
        _di_nuovo_in_coda(importato)
    misure = _misure(importato)
    assert len(misure) == 4
    with importato.lettura() as connessione:
        file = uno(connessione, "SELECT f.* FROM file_media f JOIN migliorie m "
                   "ON m.file_id = f.id")
        miglioria_id = uno(connessione, "SELECT id FROM migliorie")["id"]
    attesi = previsione.fattori(file, a_freddo=True)
    for riga in misure:
        assert json.loads(riga["fattori"]) == attesi
        assert riga["miglioria_id"] == miglioria_id and riga["genere"] == "immagine"
        assert riga["versione"] == NUOVA and 0 < riga["secondi"] < 60
        assert riga["finita_il"].endswith("Z")
    assert [riga["prevista"] is None for riga in misure] == [True, True, True, False]
    assert [("prevista" in visto) for visto in visti] == [False, False, False, True]
    assert visti[3]["prevista"] == misure[3]["prevista"]
    assert all(visto["disco"] is False and isinstance(visto["partito_il"], float)
               and abs(visto["partito_il"] - time.time()) < 600 for visto in visti)


def test_misura_tutto_il_file_dall_inizio_alla_fine(importato, monkeypatch):
    _metti_davvero(importato, "piccola.jpg")
    orologio = iter([1000.0, 1250.5, 99999.0])
    monkeypatch.setattr(lavoro.time, "monotonic", lambda: next(orologio))
    _gira(importato, _fatta())
    assert [riga["secondi"] for riga in _misure(importato)] == [250.5]


def test_tiene_conto_di_disco_e_intensita(importato, monkeypatch):
    _metti_davvero(importato, "piccola.jpg")
    with importato.scrittura() as connessione:
        scrivi_impostazione(connessione, "intensita_scheda", 70)
    vero = lavoro.Miglioratore._uno

    def col_disco(miglioratore, riga):
        miglioratore._disco = True
        return vero(miglioratore, riga)

    monkeypatch.setattr(lavoro.Miglioratore, "_uno", col_disco)
    visti: list = []
    di: list = []
    _gira(importato, _fatta(visti=visti, miglioratore_di=di), miglioratore_di=di)
    [riga] = _misure(importato)
    dati = json.loads(riga["fattori"])
    assert dati["disco"] is True and dati["intensita"] == 70
    assert visti[0]["disco"] is True


def test_un_file_si_misura_una_volta_sola(importato):
    miglioratore = lavoro.Miglioratore(importato, lancia=_fatta(), motori_scelti=SCELTI,
                                       sfidanti_pronti=lambda: False)
    miglioratore._misura = {"partito": 0.0, "fattori": _foto(640, 480), "prevista": None,
                            "versione": NUOVA}
    fatto = {"motori": [{"nome": "seedvr2", "versione": NUOVA}]}
    with importato.scrittura() as connessione:
        miglioratore._misurato(connessione, 1, fatto)
        miglioratore._misurato(connessione, 1, fatto)
    assert len(_misure(importato)) == 1


def test_tiene_conto_dei_volti_e_dell_archivio(importato, monkeypatch):
    _metti_davvero(importato, "piccola.jpg")
    vero = lavoro.Miglioratore._il_lavoro

    def con_persone(miglioratore, *argomenti):
        fatto = vero(miglioratore, *argomenti)
        return {**fatto, "persone": [{"id": 1}, {"id": 2}], "dall_archivio": {}}

    monkeypatch.setattr(lavoro.Miglioratore, "_il_lavoro", con_persone)
    _gira(importato, _fatta())
    [riga] = _misure(importato)
    dati = json.loads(riga["fattori"])
    assert dati["volti"] == 2 and dati["dall_archivio"] is True


@pytest.mark.parametrize("lancia", [
    _fatta(versione=VECCHIA),
    lambda lavoro_da_fare, al_passo, ricorda: {"guasto": "rotto"},
    lambda lavoro_da_fare, al_passo, ricorda: (
        Path(lavoro_da_fare["uscita"]).write_bytes(b"x"),
        {"fatto": {"motori": [{"nome": "finto", "versione": NUOVA}]}})[1],
    lambda lavoro_da_fare, al_passo, ricorda: (
        Path(lavoro_da_fare["uscita"]).write_bytes(b"x"), {"fatto": {}})[1],
    lambda lavoro_da_fare, al_passo, ricorda: (
        Path(lavoro_da_fare["uscita"]).write_bytes(b"x"),
        {"fatto": {"motori": ["seedvr2"]}})[1],
])
def test_non_salva_i_secondi_se_non_e_seedvr2_nuovo_o_non_finisce(importato, lancia):
    _metti_davvero(importato, "piccola.jpg")
    _gira(importato, lancia)
    assert _misure(importato) == []


def test_nella_sfida_salva_i_secondi_delle_due_versioni(importato):
    _metti_davvero(importato, "piccola.jpg")
    _gira(importato, _fatta(), sfida=True)
    [riga] = _misure(importato)
    assert json.loads(riga["fattori"])["sfida"] is True


def test_nella_sfida_saltata_salva_lo_stesso(importato):
    _metti_davvero(importato, "piccola.jpg")

    def lancia(lavoro_da_fare, al_passo, ricorda):
        if lavoro_da_fare["motori"]["foto"] == "lucidflux":
            return {"guasto": "rotto"}
        return _fatta()(lavoro_da_fare, al_passo, ricorda)

    _gira(importato, lancia, sfida=True)
    [riga] = _misure(importato)
    assert json.loads(riga["fattori"])["sfida"] is True


def test_se_la_previsione_si_rompe_il_lavoro_va_avanti(importato, monkeypatch):
    _metti_davvero(importato, "piccola.jpg")
    avvisi = []
    monkeypatch.setattr(registro, "avviso",
                        lambda nome, **campi: avvisi.append(nome))

    def rotta(*argomenti):
        raise sqlite3.OperationalError("finto")

    monkeypatch.setattr(previsione, "prevedi", rotta)
    _gira(importato, _fatta())
    [riga] = _misure(importato)
    assert riga["prevista"] is None
    assert "miglioria.previsione" in avvisi


def test_salva_la_prevista_vista_alla_partenza(importato, monkeypatch):
    _metti_davvero(importato, "piccola.jpg")
    monkeypatch.setattr(previsione, "prevedi", lambda *argomenti: 123.0)
    eventi = []
    vero = registro.evento

    def spia(nome, **campi):
        eventi.append((nome, campi))
        return vero(nome, **campi)

    monkeypatch.setattr(registro, "evento", spia)
    _gira(importato, _fatta())
    [riga] = _misure(importato)
    assert riga["prevista"] == 123.0
    [(_nome, campi)] = [evento for evento in eventi if evento[0] == "miglioria.secondi"]
    assert campi == {"secondi": round(riga["secondi"], 1), "prevista": 123.0}


def _pagina(cliente) -> str:
    return html.unescape(cliente.get("/miglioramento").text)


def test_la_pagina_dice_quando_arriva_la_previsione(cliente, importato):
    _metti_davvero(importato, "piccola.jpg")
    testo = _pagina(cliente)
    assert testo.count(f"Quanto manca: {previsione.ARRIVA_DOPO}.") == 1
    assert "sbagliato" not in testo


@pytest.mark.parametrize("versione", ["A", "B"])
def test_la_pagina_dice_quanto_manca_e_quanto_sbaglia(cliente, importato, versione):
    aspetto.imposta("miglioramento", versione)
    _metti_davvero(importato, "piccola.jpg")
    _impara_le_foto(importato, secondi=7200.0, prevista=6480.0, quante=5)
    testo = _pagina(cliente)
    assert re.search(r"Alla foto in coda mancano circa \d (ora|ore)( e \d+ minut[oi])? "
                     r"\(se lo avvii adesso, finisce (domani )?verso le \d\d:\d0\)\.",
                     testo)
    assert "Sugli ultimi 5 file finiti la previsione ha sbagliato di circa il 10%." in testo
    assert testo.count('id="previsione-miglioramento"') == 1


def test_senza_coda_la_pagina_non_dice_niente(cliente):
    testo = _pagina(cliente)
    assert 'id="previsione-miglioramento"' not in testo


def test_se_la_previsione_si_rompe_la_pagina_si_apre(cliente, importato, monkeypatch):
    _metti_davvero(importato, "piccola.jpg")
    avvisi = []
    monkeypatch.setattr(registro, "avviso", lambda nome, **campi: avvisi.append(nome))

    def rotta(*argomenti, **campi):
        raise sqlite3.OperationalError("finto")

    monkeypatch.setattr(previsione, "quanto_manca", rotta)
    risposta = cliente.get("/miglioramento")
    assert risposta.status_code == 200
    assert 'id="previsione-miglioramento"' not in risposta.text
    assert avvisi == ["miglioria.previsione"]


def test_la_pagina_passa_quello_che_sa(importato, monkeypatch):
    from officina.miglioria import motori, preparazione, sfida
    from officina.web import miglioramento as miglioramento_web

    visti = []
    monkeypatch.setattr(previsione, "quanto_manca",
                        lambda connessione, versione, **campi: visti.append(
                            (versione, campi)) or {"riga": "x", "errore": ""})
    monkeypatch.setattr(preparazione, "e_pronto", lambda *argomenti: True)
    miglioratore = miglioramento_web.il_miglioratore(importato)
    monkeypatch.setattr(miglioramento_web, "il_miglioratore", lambda archivio: miglioratore)
    monkeypatch.setattr(miglioratore, "_scelti", lambda: {"volti": motori.FACEME})
    miglioratore.adesso = {"id": 3, "disco": True}
    with importato.scrittura() as connessione:
        scrivi_impostazione(connessione, "intensita_scheda", 60)
    assert miglioramento_web.la_coda(importato)["previsione"] == {"riga": "x", "errore": ""}
    [(versione, campi)] = visti
    ora = campi.pop("ora")
    assert abs(ora - datetime.now().timestamp()) < 60
    assert versione == NUOVA
    assert campi == {"sta_lavorando": False, "lavoro": {"id": 3, "disco": True},
                     "faceme": True, "lucidflux": False, "posti_in_sfida": sfida.QUANTE,
                     "disco": True, "intensita": 60, "fluido": None}
    for spento in ({"pausa": True}, {"pronti": False}, {"chiusa": True}):
        visti.clear()
        with monkeypatch.context() as cambi:
            if "pausa" in spento:
                cambi.setattr(sfida, "in_pausa", lambda connessione: True)
            if "pronti" in spento:
                cambi.setattr(preparazione, "e_pronto",
                              lambda dove, quale=None: quale != motori.LUCIDFLUX)
            if "chiusa" in spento:
                cambi.setattr(sfida, "si_fa", lambda connessione, pronte: False)
            miglioramento_web.la_coda(importato)
        assert visti[0][1]["posti_in_sfida"] == 0, spento
    monkeypatch.setattr(sfida, "quante_fatte", lambda connessione: 40)
    visti.clear()
    miglioramento_web.la_coda(importato)
    assert visti[0][1]["posti_in_sfida"] == sfida.QUANTE - 40
